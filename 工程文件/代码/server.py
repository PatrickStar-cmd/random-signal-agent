"""HTTP server for the conversational random signal agent.

The server uses only the Python standard library so it can run on a small cloud
VM without extra framework dependencies.
"""

from __future__ import annotations

import argparse
import array
import base64
import cgi
import json
import math
import secrets
import sys
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from src.dialogue_agent import RandomSignalDialogueAgent


ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "web"
UPLOAD_DIR = ROOT / "uploads"
OUTPUT_DIR = ROOT / "outputs"
AGENT = RandomSignalDialogueAgent()


def _json_bytes(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _positive_sample_rate(value: object) -> float:
    try:
        rate = float(value)
    except (ValueError, TypeError) as exc:
        raise ValueError("sample_rate must be a finite positive number") from exc
    if not math.isfinite(rate) or rate <= 0:
        raise ValueError("sample_rate must be a finite positive number")
    return rate


class AgentRequestHandler(BaseHTTPRequestHandler):
    """Route HTTP requests to the dialogue agent."""

    server_version = "RandomSignalAgentHTTP/0.1"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path in ["/", "/chat", "/index.html"]:
            self._send_file(STATIC_DIR / "chat.html", "text/html; charset=utf-8")
            return
        if parsed.path == "/api/health":
            self._send_json({"status": "ok", "llm": AGENT.llm.status()})
            return
        if parsed.path == "/api/state":
            query = parse_qs(parsed.query)
            session_id = query.get("session_id", ["default"])[0]
            state = AGENT.get_session(session_id)
            self._send_json({"state": AGENT.serialize_state(state)})
            return
        if parsed.path.startswith("/outputs/"):
            output_path = (OUTPUT_DIR / parsed.path.removeprefix("/outputs/")).resolve()
            if OUTPUT_DIR.resolve() in output_path.parents and output_path.exists() and output_path.is_file():
                self._send_file(output_path, self._content_type(output_path))
                return
            self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)
            return
        static_path = (STATIC_DIR / parsed.path.lstrip("/")).resolve()
        if STATIC_DIR.resolve() in static_path.parents and static_path.is_file():
            self._send_file(static_path, self._content_type(static_path))
            return
        self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/chat":
            payload = self._read_json()
            if payload is None:
                return
            session_id = str(payload.get("session_id") or "default")
            message = str(payload.get("message") or "")
            if not message.strip():
                self._send_json({"error": "message is required"}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json(
                AGENT.chat(
                    session_id,
                    message,
                    tool_library=payload.get("tool_library"),
                    agent_mode=_truthy(payload.get("agent_mode")),
                )
            )
            return
        if parsed.path == "/api/chat/stream":
            payload = self._read_json()
            if payload is None:
                return
            session_id = str(payload.get("session_id") or "default")
            message = str(payload.get("message") or "")
            if not message.strip():
                self._send_json({"error": "message is required"}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_event_stream(
                AGENT.chat_stream(
                    session_id,
                    message,
                    tool_library=payload.get("tool_library"),
                    agent_mode=_truthy(payload.get("agent_mode")),
                )
            )
            return
        if parsed.path == "/api/upload":
            self._handle_upload()
            return
        if parsed.path == "/api/microphone":
            payload = self._read_json()
            if payload is None:
                return
            session_id = str(payload.get("session_id") or "default")
            try:
                sample_rate = _positive_sample_rate(payload.get("sample_rate"))
            except ValueError as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            samples = payload.get("samples")
            if not isinstance(samples, list):
                pcm16 = payload.get("pcm16")
                if isinstance(pcm16, str) and pcm16:
                    try:
                        raw_pcm = base64.b64decode(pcm16, validate=True)
                        if len(raw_pcm) % 2:
                            raise ValueError("pcm16 byte length must be even")
                        pcm = array.array("h")
                        pcm.frombytes(raw_pcm)
                        if sys.byteorder != "little":
                            pcm.byteswap()
                        samples = [value / 32768.0 for value in pcm]
                    except Exception as exc:
                        self._send_json({"error": f"invalid pcm16 microphone payload: {exc}"}, status=HTTPStatus.BAD_REQUEST)
                        return
                else:
                    self._send_json({"error": "samples must be a numeric array or pcm16 base64"}, status=HTTPStatus.BAD_REQUEST)
                    return
            try:
                self._send_json(AGENT.use_microphone_samples(session_id, samples, sample_rate=sample_rate))
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        if parsed.path == "/api/realtime/stop":
            payload = self._read_json()
            if payload is None:
                return
            session_id = str(payload.get("session_id") or "default")
            sample_count = payload.get("sample_count")
            try:
                sample_count = int(sample_count) if sample_count is not None else None
                self._send_json(
                    AGENT.stop_realtime_acquisition(
                        session_id,
                        sample_count=sample_count,
                        tool_library=payload.get("tool_library"),
                        agent_mode=_truthy(payload.get("agent_mode")),
                    )
                )
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)

    def _handle_upload(self) -> None:
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            self._send_json({"error": "multipart/form-data is required"}, status=HTTPStatus.BAD_REQUEST)
            return

        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": content_type,
            },
        )
        session_id = str(form.getvalue("session_id") or "default")
        try:
            sample_rate = _positive_sample_rate(form.getvalue("sample_rate") or 200.0)
        except ValueError as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        agent_mode = _truthy(form.getvalue("agent_mode"))
        tool_library: dict | None = None
        raw_tool_library = form.getvalue("tool_library")
        if raw_tool_library:
            try:
                parsed = json.loads(str(raw_tool_library))
                if isinstance(parsed, dict):
                    tool_library = parsed
            except json.JSONDecodeError:
                tool_library = None
        file_item = form["file"] if "file" in form else None
        if file_item is None or not getattr(file_item, "filename", ""):
            self._send_json({"error": "file is required"}, status=HTTPStatus.BAD_REQUEST)
            return

        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        safe_name = Path(str(file_item.filename).replace("\\", "/")).name
        target = UPLOAD_DIR / f"{secrets.token_hex(16)}_{safe_name}"
        with target.open("wb") as file:
            file.write(file_item.file.read())

        try:
            result = AGENT.use_uploaded_file(
                session_id,
                str(target),
                sample_rate=sample_rate,
                tool_library=tool_library,
                agent_mode=agent_mode,
            )
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        self._send_json(result)

    def _read_json(self) -> dict | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0:
                raise ValueError("Content-Length must be non-negative")
            raw = self.rfile.read(length)
            payload = json.loads(raw.decode("utf-8")) if raw else {}
            if not isinstance(payload, dict):
                raise ValueError("JSON body must be an object")
            return payload
        except (ValueError, UnicodeError) as exc:
            self._send_json({"error": f"invalid JSON request: {exc}"}, status=HTTPStatus.BAD_REQUEST)
            return None

    def _send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = _json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_event_stream(self, events: object) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        try:
            for event in events:
                payload = json.dumps(event, ensure_ascii=False)
                self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            self.close_connection = True
        except Exception as exc:
            traceback.print_exc()
            try:
                payload = json.dumps({"event": "error", "error": str(exc)}, ensure_ascii=False)
                self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
                self.close_connection = True
            except Exception:
                return

    def _send_file(self, path: Path, content_type: str) -> None:
        if not path.exists():
            self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)
            return
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _content_type(self, path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix == ".html":
            return "text/html; charset=utf-8"
        if suffix == ".css":
            return "text/css; charset=utf-8"
        if suffix == ".js":
            return "application/javascript; charset=utf-8"
        if suffix in {".jpg", ".jpeg"}:
            return "image/jpeg"
        if suffix == ".png":
            return "image/png"
        if suffix == ".webp":
            return "image/webp"
        if suffix == ".wav":
            return "audio/wav"
        if suffix == ".mp3":
            return "audio/mpeg"
        return "application/octet-stream"

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the random signal dialogue agent server.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    httpd = ThreadingHTTPServer((args.host, args.port), AgentRequestHandler)
    print(f"Random signal dialogue agent running at http://{args.host}:{args.port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")


if __name__ == "__main__":
    main()
