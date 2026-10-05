"""Bounded background tasks with durable request IDs and per-session locks."""
from __future__ import annotations

import hashlib
import copy
import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from .limits import LIMITS

progress_callback = ContextVar("progress_callback", default=None)


def emit_progress(tool, status, **detail):
    callback = progress_callback.get()
    if callback:
        callback({"event": "progress", "tool": tool, "status": status, **detail})


class TaskConflict(ValueError):
    pass


class TaskBusy(ValueError):
    pass


class TaskEngine:
    def __init__(self, agent, store, workers=None, capacity=None):
        self.agent, self.store = agent, store
        self.pool = ThreadPoolExecutor(max_workers=workers or LIMITS["workers"], thread_name_prefix="experiment")
        self.slots = threading.BoundedSemaphore(capacity or LIMITS["task_capacity"])
        self.lock = threading.RLock()
        self.session_locks = {}
        self.events = {}
        self.condition = threading.Condition(self.lock)

    def session_lock(self, session):
        with self.lock:
            if session not in self.session_locks:
                if len(self.session_locks) >= LIMITS["session_capacity"]:
                    raise TaskBusy("Session capacity reached; restart the service to unload sessions")
                self.session_locks[session] = threading.RLock()
            return self.session_locks[session]

    def load_session(self, session):
        if session not in self.agent.sessions:
            try:
                self.agent.sessions[session] = self.store.load(self.store.auto_id(session), session)
            except KeyError:
                self.agent.get_session(session)

    def submit(self, session, request_id, payload, operation):
        request_id = request_id or uuid.uuid4().hex
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128:
            raise ValueError("request_id must contain 1–128 characters")
        key = hashlib.sha256((session + "\0" + request_id).encode()).hexdigest()
        def digest(value):
            return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
        parameters = {k: v for k, v in payload.items() if k != "respond_async"}
        fingerprint = digest(parameters)
        # Existing v0.2.0 tasks included transport preferences in their digest.
        compatible = {fingerprint, digest({**parameters, "respond_async": True}),
                      digest({**parameters, "respond_async": False})}
        session_lock = self.session_lock(session)
        with self.lock, self.store.connect() as db:
            existing = db.execute("SELECT * FROM tasks WHERE id=?", (key,)).fetchone()
            if existing:
                if existing["fingerprint"] not in compatible:
                    raise TaskConflict("request_id was already used with different parameters")
                db.execute("UPDATE tasks SET fingerprint=? WHERE id=?", (fingerprint, key))
                return key
            if not self.slots.acquire(blocking=False):
                raise TaskBusy("Task queue is full; retry with the same request_id")
            try:
                db.execute("INSERT INTO tasks VALUES (?,?,?,?,?,?)", (key, session, fingerprint, "queued", None, time.time()))
                db.commit()
                self.events[key] = []
                self.pool.submit(self._run, key, session, session_lock, operation)
            except Exception:
                self.slots.release()
                raise
        return key

    def _emit(self, key, event):
        with self.condition:
            events = self.events.setdefault(key, [])
            sequence = events[-1]["sequence"] + 1 if events else 1
            events.append({**event, "task_id": key, "sequence": sequence})
            # Progress replay is bounded; final result is persisted separately.
            self.events[key] = self.events[key][-256:]
            self.condition.notify_all()

    def _run(self, key, session, session_lock, operation):
        token = progress_callback.set(lambda event: self._emit(key, event))
        try:
            with session_lock:
                self.load_session(session)
                with self.store.connect() as db:
                    db.execute("UPDATE tasks SET status='running' WHERE id=?", (key,))
                self._emit(key, {"event": "progress", "tool": "task", "status": "running"})
                previous = copy.deepcopy(self.agent.get_session(session))
                try:
                    result = operation()
                    self.store.autosave(self.agent.get_session(session))
                except Exception:
                    self.agent.sessions[session] = previous
                    raise
                with self.store.connect() as db:
                    db.execute("UPDATE tasks SET status='done',result=? WHERE id=?", (json.dumps(result, ensure_ascii=False, allow_nan=False), key))
        except Exception as exc:
            with self.store.connect() as db:
                db.execute("UPDATE tasks SET status='error',result=? WHERE id=?", (json.dumps({"error": str(exc)}, ensure_ascii=False), key))
        finally:
            progress_callback.reset(token)
            self.slots.release()
            with self.condition:
                self.condition.notify_all()
                if len(self.events) > 128:
                    for old in list(self.events):
                        if old != key and self.status(old, None)["status"] in ("done", "error"):
                            del self.events[old]
                            break

    def status(self, key, session):
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM tasks WHERE id=?", (key,)).fetchone()
        if row is None or (session is not None and row["session"] != session):
            raise KeyError("Task not found")
        return {"task_id": key, "status": row["status"], "result": json.loads(row["result"]) if row["result"] else None}

    def wait(self, key, session):
        while True:
            status = self.status(key, session)
            if status["status"] in ("done", "error"):
                return status["result"]
            with self.condition:
                self.condition.wait(timeout=0.5)

    def stream(self, key, session):
        cursor = 0
        yield {"event": "progress", "task_id": key, "tool": "task", "status": "queued"}
        while True:
            # Read completion before draining progress so the final tool event is
            # included even when the worker finishes between these two reads.
            status = self.status(key, session)
            with self.condition:
                events = [event for event in self.events.get(key, []) if event["sequence"] > cursor]
                if events:
                    cursor = events[-1]["sequence"]
            yield from events
            if status["status"] == "done":
                yield {"event": "done", "task_id": key, **status["result"]}
                return
            if status["status"] == "error":
                yield {"event": "error", "task_id": key, **status["result"]}
                return
            with self.condition:
                self.condition.wait(timeout=1)
            yield {"event": "heartbeat", "task_id": key}

    def close(self):
        self.pool.shutdown(wait=True)
