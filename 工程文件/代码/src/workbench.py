"""Versioned, non-pickle experiment snapshots and explainable comparisons."""
from __future__ import annotations

import hashlib
import io
import json
import platform
import re
import sqlite3
import threading
import time
import uuid
import zipfile
from contextlib import contextmanager
from dataclasses import fields, is_dataclass
from html import escape
from pathlib import Path

import numpy as np

from .dialogue_agent import ConversationState
from .signal_processing import SignalBundle, SignalConfig, PreprocessResult
from .limits import LIMITS

VERSION = "0.3.0"
# Application maintenance releases do not change the saved algorithm contract.
ALGORITHM_VERSION = "0.2.0"
SCHEMA = 1
MAX_SAMPLES = LIMITS["max_samples"]
MAX_ARCHIVE = LIMITS["experiment_package_bytes"]
TYPES = {c.__name__: c for c in (ConversationState, SignalBundle, SignalConfig, PreprocessResult)}


def snapshot(state):
    arrays = {}

    def encode(value):
        if isinstance(value, np.ndarray):
            key = f"a{len(arrays)}"
            arrays[key] = value
            return {"$array": key}
        if isinstance(value, np.generic):
            return value.item()
        if is_dataclass(value):
            return {"$type": type(value).__name__, "fields": {f.name: encode(getattr(value, f.name)) for f in fields(value)}}
        if isinstance(value, dict):
            return {str(k): encode(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [encode(v) for v in value]
        return value

    document = encode(state)
    buffer = io.BytesIO()
    np.savez_compressed(buffer, **arrays)
    raw = buffer.getvalue()
    manifest = {"schema_version": SCHEMA, "algorithm_version": ALGORITHM_VERSION, "app_version": VERSION,
                "python": platform.python_version(), "numpy": np.__version__,
                "data_sha256": hashlib.sha256(raw).hexdigest(), "state": document}
    return json.dumps(manifest, ensure_ascii=False, allow_nan=False).encode(), raw


def restore(document, raw):
    manifest = json.loads(document)
    if manifest.get("schema_version") != SCHEMA or manifest.get("algorithm_version") != ALGORITHM_VERSION:
        raise ValueError("Unsupported experiment schema or algorithm version")
    if hashlib.sha256(raw).hexdigest() != manifest.get("data_sha256"):
        raise ValueError("Experiment data checksum mismatch")
    # Check nested NPZ expansion before NumPy allocates arrays. Never load pickles.
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if len(archive.infolist()) > 128 or sum(i.file_size for i in archive.infolist()) > MAX_ARCHIVE:
            raise ValueError("Experiment arrays exceed size limit")
        for member in archive.infolist():
            with archive.open(member) as stream:
                version = np.lib.format.read_magic(stream)
                if version not in ((1, 0), (2, 0)):
                    raise ValueError("Unsupported experiment array format")
                reader = np.lib.format.read_array_header_1_0 if version == (1, 0) else np.lib.format.read_array_header_2_0
                shape, _, dtype = reader(stream)
                if len(shape) != 1 or not 0 <= shape[0] <= MAX_SAMPLES or dtype.kind not in "bifu" or dtype.itemsize > 8:
                    raise ValueError("Invalid experiment array header")
                if stream.tell() + shape[0] * dtype.itemsize != member.file_size:
                    raise ValueError("Experiment array size does not match its header")
    with np.load(io.BytesIO(raw), allow_pickle=False) as arrays:
        def decode(value):
            if isinstance(value, dict):
                if "$array" in value:
                    array = arrays[value["$array"]]
                    if array.ndim != 1 or array.size > MAX_SAMPLES or array.dtype.kind not in "bifu" or not np.isfinite(array).all():
                        raise ValueError("Invalid experiment array")
                    return array.copy()
                if "$type" in value:
                    cls = TYPES.get(value["$type"])
                    if cls is None:
                        raise ValueError("Unknown experiment type")
                    return cls(**{k: decode(v) for k, v in value["fields"].items()})
                return {k: decode(v) for k, v in value.items()}
            if isinstance(value, list):
                return [decode(v) for v in value]
            return value
        state = decode(manifest["state"])
    if not isinstance(state, ConversationState):
        raise ValueError("Invalid experiment state")
    if not isinstance(state.diagnostic_lab, dict):
        raise ValueError("Invalid diagnostic state")
    if state.bundle is not None:
        b = state.bundle
        n = len(b.observed)
        if not n or any(len(getattr(b, k)) != n for k in ("time", "clean", "noise", "impulse_mask")):
            raise ValueError("Signal array lengths do not match")
        if not np.isfinite(b.config.sample_rate) or b.config.sample_rate <= 0:
            raise ValueError("Invalid sample rate")
        for result in [state.processed, *state.preprocess_results.values()]:
            if result is not None and (not isinstance(result, PreprocessResult) or len(result.signal) != n or len(result.anomaly_mask) != n):
                raise ValueError("Invalid preprocessing result")
        for array in [state.diagnostic_lab.get('baseline'), state.diagnostic_lab.get('reference_clean'),
                      state.diagnostic_lab.get('verification',{}).get('signal')]:
            if array is not None and (not isinstance(array,np.ndarray) or len(array)!=n):
                raise ValueError("Invalid diagnostic array length")
    return state


class ExperimentStore:
    def __init__(self, root: Path):
        self.root = root
        self.file_lock = threading.RLock()
        root.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS snapshots(id TEXT PRIMARY KEY, session TEXT NOT NULL,
                    name TEXT NOT NULL, document BLOB NOT NULL, data_file TEXT NOT NULL, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, session TEXT NOT NULL,
                    fingerprint TEXT NOT NULL, status TEXT NOT NULL, result TEXT, created REAL NOT NULL);
            """)
            if "operation" not in {row[1] for row in db.execute("PRAGMA table_info(tasks)")}:
                db.execute("ALTER TABLE tasks ADD COLUMN operation TEXT NOT NULL DEFAULT 'task'")
            db.execute("UPDATE tasks SET status='error', result=? WHERE status IN ('queued','running','cancelling')",
                       (json.dumps({"error": "Server restarted during task; inspect recovered experiment before starting a new task"}),))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.root / "experiments.sqlite3", timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def save(self, state, name="Autosave", experiment_id=None):
        with self.file_lock:
            return self._save(state, name, experiment_id)

    def _save(self, state, name="Autosave", experiment_id=None):
        document, raw = snapshot(state)
        data_file = hashlib.sha256(raw).hexdigest() + ".npz"
        path = self.root / data_file
        if not path.exists():
            temp = self.root / (uuid.uuid4().hex + ".tmp")
            temp.write_bytes(raw)
            temp.replace(path)
        key = experiment_id or uuid.uuid4().hex
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO snapshots VALUES (?,?,?,?,?,?)",
                       (key, state.session_id, name[:120], document, data_file, time.time()))
        return key

    def load(self, key, session):
        with self.file_lock:
            return self._load(key, session)

    def _load(self, key, session):
        with self.connect() as db:
            row = db.execute("SELECT * FROM snapshots WHERE id=? AND session=?", (key, session)).fetchone()
        if row is None:
            raise KeyError("Experiment not found in this browser session")
        state = restore(row["document"], (self.root / row["data_file"]).read_bytes())
        state.session_id = session
        return state

    def list(self, session):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT id,name,updated FROM snapshots WHERE session=? AND name<>'Autosave' ORDER BY updated DESC", (session,))]

    def rename(self, key, session, name):
        with self.connect() as db:
            result = db.execute("UPDATE snapshots SET name=?,updated=? WHERE id=? AND session=? AND name<>'Autosave'",
                                (name, time.time(), key, session))
            if not result.rowcount:
                raise KeyError("Saved experiment not found in this browser session")

    def delete(self, key, session):
        # Arrays may also be referenced by autosave or another snapshot. Keep them.
        with self.connect() as db:
            result = db.execute("DELETE FROM snapshots WHERE id=? AND session=? AND name<>'Autosave'", (key, session))
            if not result.rowcount:
                raise KeyError("Saved experiment not found in this browser session")

    @staticmethod
    def auto_id(session):
        return "auto-" + hashlib.sha256(session.encode()).hexdigest()

    def autosave(self, state):
        self.save(state, experiment_id=self.auto_id(state.session_id))

    def storage_preview(self):
        with self.file_lock, self.connect() as db:
            referenced = {row[0] for row in db.execute("SELECT DISTINCT data_file FROM snapshots")}
            files = [p for p in self.root.glob('*.npz') if re.fullmatch(r'[0-9a-f]{64}\.npz', p.name)
                     and not p.is_symlink() and p.is_file() and p.resolve().parent == self.root.resolve()]
            unused = sorted((p.name, p.stat().st_size, p.stat().st_mtime_ns) for p in files if p.name not in referenced)
            token = hashlib.sha256(json.dumps(unused).encode()).hexdigest()
            return {"total_bytes": sum(p.stat().st_size for p in files), "array_files": len(files),
                    "database_bytes": (self.root / 'experiments.sqlite3').stat().st_size,
                    "unused_files": len(unused), "reclaimable_bytes": sum(item[1] for item in unused),
                    "token": token, "files": [{"name": name, "bytes": size} for name, size, _ in unused]}

    def storage_cleanup(self, token):
        with self.file_lock:
            preview = self.storage_preview()
            if not isinstance(token, str) or token != preview['token']:
                raise ValueError("Storage changed; refresh the cleanup preview before confirming")
            removed, freed = 0, 0
            # Rechecked under the same lock as save/load: shared arrays and an
            # array being saved cannot become candidates between preview/delete.
            for item in preview['files']:
                path = self.root / item['name']
                if path.resolve().parent != self.root.resolve() or path.is_symlink():
                    raise ValueError("Invalid storage path")
                path.unlink()
                removed += 1
                freed += item['bytes']
            return {"removed_files": removed, "freed_bytes": freed}


def csv_data(state):
    b = state.bundle
    if b is None:
        raise ValueError("Generate or upload a signal first")
    labels = ["time_s", "observed"]
    arrays = [b.time, b.observed]
    if b.has_clean_reference:
        labels += ["clean", "noise"]
        arrays += [b.clean, b.noise]
    for method, result in state.preprocess_results.items():
        labels.append(method)
        arrays.append(result.signal)
    if state.processed is not None and state.processed.method not in state.preprocess_results:
        labels.append(state.processed.method)
        arrays.append(state.processed.signal)
    out = io.StringIO()
    np.savetxt(out, np.column_stack(arrays), delimiter=",", header=",".join(labels), comments="", fmt="%.17g")
    return out.getvalue().encode()


def report_html(state, name):
    b = state.bundle
    if b is None:
        raise ValueError("Generate or upload a signal first")
    comparison = state.preprocess_comparison or {}
    rows = "".join("<tr>" + "".join(f"<td>{escape(str(v))}</td>" for v in (
        r["label"], r["score"], r.get("processed_snr_db") if b.has_clean_reference else "N/A — no clean reference",
        r.get("duration_ms", ""), json.dumps(r["parameters"], ensure_ascii=False))) + "</tr>" for r in comparison.get("methods", []))
    details = {"configuration": b.config.to_dict(), "source": b.source, "sample_count": len(b.observed),
               "goal": state.comparison_goal, "comparison": comparison, "summary": state.summary,
               "tools": state.tool_calls, "algorithm_version": ALGORITHM_VERSION, "app_version": VERSION}
    # Standalone SVG uses the same extrema-preserving display sampling as the app.
    from .signal_processing import decimate_for_export
    series = [b.time, b.observed] + ([state.processed.signal] if state.processed else [])
    plotted = decimate_for_export(*series)
    lo, hi = min(min(x) for x in plotted[1:]), max(max(x) for x in plotted[1:])
    span = max(hi - lo, 1e-12)
    tspan = max(plotted[0][-1] - plotted[0][0], 1e-12)
    lines = "".join('<polyline fill="none" stroke="' + color + '" stroke-width="1.4" points="' +
                    " ".join(f"{20+860*(t-plotted[0][0])/tspan:.2f},{220-200*(v-lo)/span:.2f}" for t, v in zip(plotted[0], values)) + '"/>'
                    for color, values in zip(("#8192b4", "#5b3acb"), plotted[1:]))
    return (f'<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>{escape(name)}</title>'
            '<style>body{max-width:1100px;margin:40px auto;padding:24px;font:16px/1.6 system-ui;color:#182238}table{border-collapse:collapse;width:100%}td,th{padding:10px;border-bottom:1px solid #ddd;text-align:left}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f5fa;padding:18px}svg{width:100%}</style>'
            f'<h1>{escape(name)}</h1><p>Random Signal Agent v{VERSION} · {len(b.observed)} samples · {b.config.sample_rate:g} Hz</p>'
            f'<p>Scoring: {"clean reference" if b.has_clean_reference else "no-reference heuristic; SNR unavailable"}. Goal: {escape(state.comparison_goal)}. Scores are relative diagnostics, not a guarantee of denoising quality.</p>'
            f'<svg viewBox="0 0 900 240" role="img" aria-label="Observed (gray) and processed (purple) waveform">{lines}</svg><p>Observed: gray; processed: purple. Plot is downsampled; exported CSV contains every sample.</p>'
            f'<table><tr><th>Method</th><th>Score</th><th>SNR / dB</th><th>Search / ms</th><th>Parameters</th></tr>{rows}</table>'
            f'<h2>Parameters, scoring terms and tool records</h2><pre>{escape(json.dumps(details, ensure_ascii=False, indent=2))}</pre></html>').encode()


def export_archive(state, name):
    document, raw = snapshot(state)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", document)
        archive.writestr("samples.npz", raw)
        archive.writestr("samples.csv", csv_data(state))
        archive.writestr("report.html", report_html(state, name))
    return output.getvalue()


def import_archive(raw, session):
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if len(archive.infolist()) > 10 or sum(i.file_size for i in archive.infolist()) > MAX_ARCHIVE:
            raise ValueError("Experiment package exceeds size limit")
        state = restore(archive.read("manifest.json"), archive.read("samples.npz"))
    state.session_id = session
    # Local upload paths/audio links are not portable; original samples remain in NPZ.
    state.last_uploaded_path = None
    state.audio_result = None
    return state
