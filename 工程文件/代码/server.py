"""FastAPI workbench. Run one process: session locks are process-local."""
from __future__ import annotations
import argparse
import copy
import base64
import hashlib
import json
import math
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
import numpy as np
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from starlette.concurrency import run_in_threadpool
from src.dialogue_agent import RandomSignalDialogueAgent, ConversationState
from src.signal_processing import SignalConfig, generate_random_signal
from src.preprocessing import PREPROCESS_METHODS
from src.tasks import TaskEngine, TaskConflict, TaskBusy, emit_progress
from src.limits import LIMITS
from src.data_import import inspect_data
from src import diagnostics
from src import pdf_report
from src.model_settings import ModelSettings, CONFIG as MODEL_CONFIG
from src.llm_client import LLMClientError
from src.experiment_compare import compare_experiments, comparison_html, comparison_svg
from src.workbench import ExperimentStore, VERSION, MAX_SAMPLES, csv_data, snapshot, report_html, export_archive, import_archive

ROOT = Path(__file__).resolve().parent
STATIC_DIR, UPLOAD_DIR, OUTPUT_DIR = ROOT / "web", ROOT / "uploads", ROOT / "outputs"
DATA_DIR = Path(os.environ.get("RS_AGENT_DATA_DIR", ROOT / "data"))
MAX_BODY = LIMITS["request_bytes"]


def truthy(value):
    return str(value or "").lower() in {"1", "true", "yes", "on"}


def sample_rate(value):
    try:
        rate = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("sample_rate must be finite and positive") from exc
    if not math.isfinite(rate) or not 0 < rate <= 192000:
        raise ValueError("sample_rate must be between 0 and 192000 Hz")
    return rate


def session_key(value):
    value = value or "default"
    if not isinstance(value, str) or not 1 <= len(value) <= 256:
        raise ValueError("session_id must contain 1–256 characters")
    return value


def experiment_name(value):
    if not isinstance(value, str) or not value.strip() or value.strip() == "Autosave" or len(value.strip()) > 120:
        raise ValueError("Experiment name must contain 1–120 characters and cannot be Autosave")
    return value.strip()


class BodyLimit:
    """Bound actual bytes before parsing, including chunked bodies."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in ("POST", "PUT"):
            return await self.app(scope, receive, send)
        try:
            length = int(dict(scope["headers"]).get(b"content-length", b"0"))
            if length < 0:
                raise ValueError()
        except ValueError:
            return await JSONResponse({"error": "Invalid Content-Length"}, 400)(scope, receive, send)
        limit = LIMITS["experiment_package_bytes"] if scope["path"] == "/api/experiments/import" else MAX_BODY
        if length > limit:
            return await JSONResponse({"error": f"Request exceeds {limit} byte limit"}, 413)(scope, receive, send)
        chunks, size = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunks.append(message.get("body", b""))
            size += len(chunks[-1])
            if size > limit:
                return await JSONResponse({"error": f"Request exceeds {limit} byte limit"}, 413)(scope, receive, send)
            if not message.get("more_body"):
                break
        consumed = False
        async def bounded_receive():
            nonlocal consumed
            if not consumed:
                consumed = True
                return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
            return await receive()
        await self.app(scope, bounded_receive, send)


def create_app(agent=None, data_dir=None, static_dir=None, upload_dir=None, output_dir=None):
    agent = agent or RandomSignalDialogueAgent()
    store = ExperimentStore(Path(data_dir or DATA_DIR))
    engine = TaskEngine(agent, store)
    model_settings = ModelSettings(store.root, agent.llm)
    agent.model_settings = model_settings
    static, uploads, outputs = Path(static_dir or STATIC_DIR), Path(upload_dir or UPLOAD_DIR), Path(output_dir or OUTPUT_DIR)

    @asynccontextmanager
    async def lifespan(app):
        yield
        await run_in_threadpool(engine.close)

    app = FastAPI(title="Random Signal Agent", version=VERSION, lifespan=lifespan)
    app.add_middleware(BodyLimit)
    app.state.agent, app.state.store, app.state.engine = agent, store, engine

    @app.exception_handler(ValueError)
    async def bad_request(request, exc):
        status = 409 if isinstance(exc, TaskConflict) else 429 if isinstance(exc, TaskBusy) else 400
        return JSONResponse({"error": str(exc)}, status_code=status)

    @app.exception_handler(KeyError)
    async def missing(request, exc):
        return JSONResponse({"error": str(exc)}, status_code=404)

    @app.middleware("http")
    async def response_headers(request, call_next):
        result = await call_next(request)
        result.headers["Cache-Control"] = "no-store"
        result.headers["X-Content-Type-Options"] = "nosniff"
        return result

    async def body(request):
        try:
            value = json.loads(await request.body())
        except (ValueError, UnicodeError) as exc:
            raise ValueError("Invalid JSON request") from exc
        if not isinstance(value, dict):
            raise ValueError("JSON body must be an object")
        return value

    def result_response(result):
        return JSONResponse(result, status_code=400 if "error" in result else 200)

    def locked(session, operation):
        with engine.session_lock(session):
            engine.load_session(session)
            return operation()

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": VERSION, "llm": agent.llm.status(),
                "limits": {"body_bytes": MAX_BODY, "samples": MAX_SAMPLES, **LIMITS}}

    @app.get("/api/tasks")
    def tasks(session_id: str):
        return {"tasks": engine.list(session_key(session_id))}

    @app.get('/api/model/settings')
    def model_status(session_id: str):
        return {'settings':model_settings.public(session_key(session_id)), 'providers':MODEL_CONFIG['providers']}

    @app.post('/api/model/{action}')
    async def configure_model(action: str, request: Request):
        # JSON and same-origin requests protect browser users from cross-site configuration changes.
        origin=request.headers.get('origin')
        if origin and origin.rstrip('/') != str(request.base_url).rstrip('/'):
            return JSONResponse({'error':'模型配置仅支持同源请求。'},status_code=403)
        if request.headers.get('content-type','').split(';')[0]!='application/json':raise ValueError('模型配置需要 JSON 请求。')
        payload=await body(request);session=session_key(payload.get('session_id'))
        if action not in ('models','test','save','disable','clear'):raise ValueError('未知的模型配置操作。')
        if set(payload)-{'session_id','configuration'}:raise ValueError('未知的模型配置请求字段。')
        configuration=payload.get('configuration',{})
        def operation():
            try:
                if action=='models':return model_settings.models(session,configuration)
                if action=='test':return model_settings.test(session,configuration)
                if action=='save':return {'settings':model_settings.save(session,configuration)}
                if action=='disable':return {'settings':model_settings.disable(session)}
                return {'settings':model_settings.clear(session)}
            except LLMClientError as exc:raise ValueError(str(exc)) from None
        # Configuration bodies/keys are never put in durable task payloads or experiment snapshots.
        return await run_in_threadpool(lambda: locked(session,operation))

    @app.post("/api/tasks/{key}/cancel")
    async def cancel_task(key: str, request: Request):
        payload = await body(request)
        return await run_in_threadpool(engine.cancel, key, session_key(payload.get('session_id')))

    @app.get("/api/state")
    def state(session_id: str = "default"):
        session = session_key(session_id)
        return locked(session, lambda: {"state": agent.serialize_state(agent.get_session(session))})

    @app.get("/api/tasks/{key}")
    def task_status(key: str, session_id: str):
        return engine.status(key, session_id)

    @app.get("/api/tasks/{key}/events")
    def task_events(key: str, session_id: str):
        engine.status(key, session_id)
        def events():
            for event in engine.stream(key, session_id):
                yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(events(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})

    async def chat_request(request, streaming=False):
        payload = await body(request)
        session = session_key(payload.get("session_id"))
        message = payload.get("message")
        if not isinstance(message, str) or not message.strip() or len(message) > 16000:
            raise ValueError("message must contain 1–16000 characters")
        key = engine.submit(session, payload.get("request_id"), {**payload, "operation": "chat"},
                            lambda: agent.chat(session, message, tool_library=payload.get("tool_library"), agent_mode=truthy(payload.get("agent_mode"))))
        if streaming:
            def events():
                for event in engine.stream(key, session):
                    yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
                yield "data: [DONE]\n\n"
            return StreamingResponse(events(), media_type="text/event-stream", headers={"X-Task-ID": key, "X-Accel-Buffering": "no"})
        response = result_response(await run_in_threadpool(engine.wait, key, session))
        response.headers["X-Task-ID"] = key
        return response

    @app.post("/api/chat")
    async def chat(request: Request):
        return await chat_request(request)

    @app.post("/api/chat/stream")
    async def stream(request: Request):
        return await chat_request(request, True)

    async def run_task(payload, operation_name, operation):
        session = session_key(payload.get("session_id"))
        key = engine.submit(session, payload.get("request_id"), {**payload, "operation": operation_name}, operation,
                            cancellable=operation_name in ('experiment','upload','microphone','stop','import-data','diagnose','inject','reveal','verify','adopt','demo'))
        if payload.get("respond_async"):
            return JSONResponse({"task_id": key, "status": "accepted"}, status_code=202)
        return result_response(await run_in_threadpool(engine.wait, key, session))

    async def import_fields(request):
        async with request.form(max_files=1, max_fields=6, max_part_size=MAX_BODY) as form:
            session = session_key(form.get('session_id'))
            file = form.get('file')
            if file is None or not getattr(file, 'filename', None):
                raise ValueError('CSV/TXT file is required')
            name = Path(file.filename.replace('\\', '/')).name[:240]
            if Path(name).suffix.lower() not in ('.csv', '.txt'):
                raise ValueError('Upload CSV or TXT signal samples')
            raw = await file.read(MAX_BODY+1)
            options = json.loads(str(form.get('options', '{}')))
            return session, name, raw, options, form.get('token'), form.get('request_id')

    @app.post('/api/data/preview')
    async def preview_data(request: Request):
        _, name, raw, options, _, _ = await import_fields(request)
        preview, _ = await run_in_threadpool(inspect_data, raw, options)
        return {**preview, 'file_name': name}

    @app.post('/api/data/import')
    async def import_data(request: Request):
        session, name, raw, options, token, request_id = await import_fields(request)
        payload = {'session_id':session,'request_id':request_id,'file_sha256':hashlib.sha256(raw).hexdigest(),
                   'name':name,'options':options,'token':token}
        def operation():
            emit_progress('load_signal_file', 'running')
            preview, bundle = inspect_data(raw, options)
            if not preview['valid']:
                raise ValueError(f"数据校验失败：{preview['issues'][0]}")
            if token != preview['token']:
                raise ValueError('文件或列设置已改变，请重新预览并确认。')
            bundle.source = 'file/' + name
            current = ConversationState(session_id=session, bundle=bundle)
            current.acquisition_plan = {'channel':'uploaded_file','channel_label':'文件导入','file_name':name,
                'file_sha256':preview['file_sha256'],'mapping':preview['mapping']}
            reply = f"已导入 {name}：{preview['rows']} 个采样点，{preview['sample_rate']:.6g} Hz。可继续比较处理方法。"
            current.messages.append({'role':'assistant','content':reply})
            current.tool_calls.append({'tool':'load_signal_file','status':'success','arguments':current.acquisition_plan})
            agent.sessions[session] = current
            emit_progress('load_signal_file','success')
            return {'reply':reply,'state':agent.serialize_state(current)}
        return await run_task(payload, 'import-data', operation)

    @app.post('/api/experiments/compare')
    async def compare(request: Request):
        payload = await body(request)
        if payload.get('format', 'json') not in ('json', 'html'):
            raise ValueError('Comparison format must be json or html')
        data = await run_in_threadpool(compare_experiments, store, session_key(payload.get('session_id')), payload.get('ids'))
        if payload.get('format') == 'html':
            return Response(comparison_html(data), media_type='text/html',
                            headers={'Content-Disposition':'attachment; filename="comparison.html"'})
        return {**data, 'waveform_svg':comparison_svg(data,'waveform'), 'spectrum_svg':comparison_svg(data,'spectrum')}

    @app.get('/api/storage')
    def storage():
        return store.storage_preview()

    @app.post('/api/diagnostics/{action}')
    async def diagnostic_action(action: str, request: Request):
        payload = await body(request)
        session = session_key(payload.get('session_id'))
        if action not in ('analyze','inject','reveal','verify','adopt','demo'):
            raise ValueError('Unknown diagnostic action')
        def operation():
            state = agent.get_session(session)
            emit_progress('diagnostic_' + action, 'running')
            if action == 'demo':
                state.bundle = generate_random_signal(SignalConfig(sample_rate=200,duration=8,base_frequency=8,
                    amplitude=1,noise_std=.025,impulse_probability=0,seed=42,waveform='sine',noise_model='gaussian'))
                state.diagnostic_lab = {}
                state.acquisition_plan = None
                diagnostics.inject(state,[{'kind':'narrowband','start':2.4,'end':3.5,'strength':1.8,'frequency':38},
                    {'kind':'dropout','start':5.5,'end':5.85,'strength':1},
                    {'kind':'impulse','start':6.7,'end':7.1,'strength':4}],42,payload.get('blind',False))
                result = diagnostics.diagnose_state(state)
            elif action == 'analyze':
                result = diagnostics.diagnose_state(state, payload.get('options'))
            elif action == 'inject':
                diagnostics.inject(state, payload.get('faults'), payload.get('seed',42), payload.get('blind',False))
                result = diagnostics.diagnose_state(state)
            elif action == 'reveal': result = diagnostics.reveal(state)
            elif action == 'verify': result = diagnostics.verify(state, payload.get('event_id'), payload.get('token'))
            else: result = diagnostics.adopt(state)
            return {'diagnostics':result,'state':agent.serialize_state(state)}
        return await run_task(payload, 'diagnose' if action=='analyze' else action, operation)

    @app.get('/api/diagnostics/view')
    def diagnostic_view(session_id: str, format: str = 'json'):
        def operation():
            state = agent.get_session(session_id)
            lab = diagnostics.lab_for(state)
            params = {k:v for k,v in lab.get('analysis',{}).get('parameters',{}).items() if k!='effective_window'}
            data = diagnostics.analyze(state, params)
            if format == 'html':
                return Response(diagnostics.report_html(data, diagnostics.public_lab(state)),media_type='text/html',
                                headers={'Content-Disposition':'attachment; filename="diagnostics.html"'})
            if format != 'json': raise ValueError('Unknown diagnostic report format')
            return {'diagnostics':data,'lab':diagnostics.public_lab(state)}
        return locked(session_key(session_id),operation)

    @app.post('/api/storage/cleanup')
    async def cleanup(request: Request):
        payload = await body(request)
        if payload.get('confirm') is not True:
            raise ValueError('请先预览并确认清理范围。')
        return await run_in_threadpool(store.storage_cleanup, payload.get('token'))

    @app.post("/api/upload")
    async def upload(request: Request):
        async with request.form(max_files=1, max_fields=8, max_part_size=MAX_BODY) as form:
            rate = sample_rate(form.get("sample_rate", 200))
            session = session_key(form.get("session_id"))
            file = form.get("file")
            if file is None or not getattr(file, "filename", None):
                raise ValueError("file is required")
            name = Path(file.filename.replace("\\", "/")).name
            if Path(name).suffix.lower() not in (".csv", ".txt"):
                raise ValueError("Upload CSV or TXT signal samples")
            raw = await file.read(MAX_BODY + 1)
            library = json.loads(str(form.get("tool_library", "{}")))
            agent_mode = truthy(form.get("agent_mode"))
            payload = {"session_id": session, "request_id": form.get("request_id"), "sample_rate": rate,
                       "file_sha256": hashlib.sha256(raw).hexdigest(), "tool_library": library, "agent_mode": agent_mode}
        def operation():
            uploads.mkdir(parents=True, exist_ok=True)
            target = uploads / (secrets.token_hex(16) + "_" + name)
            target.write_bytes(raw)
            try:
                return agent.use_uploaded_file(session, str(target), sample_rate=rate, tool_library=library, agent_mode=agent_mode)
            except Exception:
                target.unlink(missing_ok=True)
                raise
        return await run_task(payload, "upload", operation)

    @app.post("/api/microphone")
    async def microphone(request: Request):
        payload = await body(request)
        session, rate = session_key(payload.get("session_id")), sample_rate(payload.get("sample_rate"))
        samples = payload.get("samples")
        if not isinstance(samples, list):
            try:
                raw = base64.b64decode(payload.get("pcm16", ""), validate=True)
                samples = np.frombuffer(raw, dtype="<i2").astype(float) / 32768
            except Exception as exc:
                raise ValueError("Invalid pcm16 microphone payload") from exc
        samples = np.asarray(samples, dtype=float)
        if samples.ndim != 1 or not 1 <= len(samples) <= MAX_SAMPLES or not np.isfinite(samples).all():
            raise ValueError(f"Provide 1–{MAX_SAMPLES} finite samples")
        return await run_task(payload, "microphone", lambda: agent.use_microphone_samples(session, samples.tolist(), sample_rate=rate))

    @app.post("/api/realtime/stop")
    async def stop(request: Request):
        payload = await body(request)
        session = session_key(payload.get("session_id"))
        count = payload.get("sample_count")
        if count is not None and (not isinstance(count, int) or not 1 <= count <= MAX_SAMPLES):
            raise ValueError("Invalid sample_count")
        return await run_task(payload, "stop", lambda: agent.stop_realtime_acquisition(session, sample_count=count,
                              tool_library=payload.get("tool_library"), agent_mode=truthy(payload.get("agent_mode"))))

    @app.post("/api/experiment/run")
    async def run_experiment(request: Request):
        payload = await body(request)
        session = session_key(payload.get("session_id"))
        goal, template = payload.get("goal", "waveform"), payload.get("template", "sine")
        if goal not in ("denoise", "waveform", "transient") or template not in ("sine", "impulse", "ar", "current"):
            raise ValueError("Unknown template or comparison goal")
        config = payload.get("config", {})
        if not isinstance(config, dict) or set(config) - {"sample_rate", "duration", "base_frequency", "amplitude", "noise_std", "seed", "ar_coefficient", "impulse_probability"}:
            raise ValueError("Unknown signal parameter")
        if "sample_rate" in config:
            config["sample_rate"] = sample_rate(config["sample_rate"])
        for field, value in config.items():
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError(f"{field} must be a finite number")
        def operation():
            state = agent.get_session(session)
            if template != "current":
                emit_progress("acquire_signal", "running")
                bundle = generate_random_signal(SignalConfig(**config, waveform="ar_process" if template == "ar" else "sine",
                    noise_model="gaussian_impulse" if template == "impulse" else "gaussian"))
                state = ConversationState(session_id=session, bundle=bundle)
                agent.sessions[session] = state
                emit_progress("acquire_signal", "success")
            if state.bundle is None:
                raise ValueError("Upload or generate a signal first")
            state.comparison_goal = goal
            agent._update_tool_library(state, payload.get("tool_library"))
            calls = []
            reply = agent._call_tool(calls, "compare_preprocess_methods", agent._compare_preprocess_methods,
                                     state, list(PREPROCESS_METHODS), "", "manual")
            state.tool_calls.extend(calls)
            state.messages.append({"role": "assistant", "content": reply})
            return {"reply": reply, "state": agent.serialize_state(state), "tool_calls": calls}
        return await run_task(payload, "experiment", operation)

    @app.get("/api/experiments")
    def experiments(session_id: str):
        return {"experiments": store.list(session_key(session_id))}

    @app.post("/api/experiments/save")
    async def save(request: Request):
        payload = await body(request)
        session = session_key(payload.get("session_id"))
        name = experiment_name(payload.get("name", "Untitled experiment"))
        def operation():
            state = agent.get_session(session)
            if state.bundle is None:
                raise ValueError("Generate or upload a signal first")
            return {"id": store.save(state, name)}
        return await run_task(payload, "save", operation)

    @app.post("/api/experiments/open")
    async def open_experiment(request: Request):
        payload = await body(request)
        session = session_key(payload.get("session_id"))
        def operation():
            state = store.load(str(payload.get("id")), session)
            agent.sessions[session] = state
            return {"state": agent.serialize_state(state)}
        return await run_task(payload, "open", operation)

    @app.post("/api/experiments/duplicate")
    async def duplicate(request: Request):
        payload = await body(request)
        session = session_key(payload.get("session_id"))
        name = experiment_name(payload.get("name", "Experiment copy"))
        def operation():
            source = store.load(str(payload.get("id")), session)
            return {"id": store.save(source, name)}
        return await run_task(payload, "duplicate", operation)

    @app.post("/api/experiments/rename")
    async def rename(request: Request):
        payload = await body(request)
        session = session_key(payload.get("session_id"))
        name = experiment_name(payload.get("name"))
        def operation():
            key = str(payload.get("id"))
            store.rename(key, session, name)
            return {"id": key, "name": name}
        return await run_task(payload, "rename", operation)

    @app.post("/api/experiments/delete")
    async def delete(request: Request):
        payload = await body(request)
        session = session_key(payload.get("session_id"))
        def operation():
            key = str(payload.get("id"))
            store.delete(key, session)
            return {"id": key, "deleted": True}
        return await run_task(payload, "delete", operation)

    @app.post('/api/reports/{action}')
    async def analysis_report(action: str, request: Request):
        if action not in ('preview', 'pdf'):
            raise ValueError('未知报告操作。')
        if request.headers.get('content-type','').split(';')[0] != 'application/json':
            raise ValueError('报告请求须使用 JSON。')
        payload = await body(request)
        if set(payload) - {'session_id','options','token'}:
            raise ValueError('报告请求包含未知字段。')
        session = session_key(payload.get('session_id'))
        preferences = pdf_report.options(payload.get('options'))
        def prepare():
            frozen = locked(session, lambda: copy.deepcopy(agent.get_session(session)))
            return pdf_report.build(frozen, preferences)
        facts = await run_in_threadpool(prepare)
        if action == 'preview':
            return pdf_report.preview(facts)
        token = payload.get('token')
        if not isinstance(token,str) or not secrets.compare_digest(token, facts['token']):
            raise TaskConflict('实验或报告设置已变化，请重新预览后下载。')
        raw = await run_in_threadpool(pdf_report.render, facts)
        return Response(raw, media_type='application/pdf',
                        headers={'Content-Disposition':'attachment; filename="signal-analysis.pdf"'})

    @app.get("/api/experiments/export")
    def export(session_id: str, format: str = "zip", name: str = "Experiment"):
        def operation():
            state = agent.get_session(session_id)
            lab = diagnostics.lab_for(state)
            if lab.get('blind') and not lab.get('revealed'):
                raise ValueError('请先揭晓盲测再导出完整实验；诊断报告可在盲测中导出。')
            formats = {"zip": (lambda: export_archive(state, name), "application/zip"),
                       "csv": (lambda: csv_data(state), "text/csv"),
                       "html": (lambda: report_html(state, name), "text/html"),
                       "json": (lambda: snapshot(state)[0], "application/json")}
            if format not in formats:
                raise ValueError("Unknown export format")
            build, mime = formats[format]
            return Response(build(), media_type=mime, headers={"Content-Disposition": f'attachment; filename="experiment.{format}"'})
        return locked(session_key(session_id), operation)

    @app.post("/api/experiments/import")
    async def import_experiment(request: Request):
        async with request.form(max_files=1, max_fields=3, max_part_size=LIMITS["experiment_package_bytes"]) as form:
            session = session_key(form.get("session_id"))
            file = form.get("file")
            if file is None or not hasattr(file, "read"):
                raise ValueError("Experiment ZIP is required")
            raw = await file.read(LIMITS["experiment_package_bytes"] + 1)
            payload = {"session_id": session, "request_id": form.get("request_id"), "sha256": hashlib.sha256(raw).hexdigest()}
        def operation():
            try:
                state = import_archive(raw, session)
            except Exception as exc:
                raise ValueError(f"Invalid experiment package: {exc}") from exc
            agent.sessions[session] = state
            key = store.save(state, "Imported experiment")
            return {"id": key, "state": agent.serialize_state(state)}
        return await run_task(payload, "import", operation)

    @app.get("/{path:path}")
    def files(path: str):
        if "\x00" in path or "\\" in path:
            raise KeyError("Not found")
        if path in ("", "chat", "index.html"):
            return FileResponse(static / "chat.html")
        root = outputs if path.startswith("outputs/") else static
        target = (root / (path[8:] if path.startswith("outputs/") else path)).resolve()
        if root.resolve() not in target.parents or not target.is_file():
            raise KeyError("Not found")
        return FileResponse(target)

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    uvicorn.run(create_app(), host=args.host, port=args.port, limit_concurrency=32)


if __name__ == "__main__":
    main()
