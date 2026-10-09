"""Durable cancellable tasks, fair session scheduling and idle eviction."""
from __future__ import annotations
import copy
import hashlib
import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from contextvars import ContextVar
from .limits import LIMITS

progress_callback = ContextVar("progress_callback", default=None)
cancel_token = ContextVar("cancel_token", default=None)
TERMINAL = ("done", "error", "cancelled")


class TaskCancelled(BaseException):
    """Bypass tool-level Exception fallbacks; the task runner owns rollback."""


def check_cancelled():
    event = cancel_token.get()
    if event is not None and event.is_set():
        raise TaskCancelled("任务已取消，当前实验已恢复到任务开始前。")


def emit_progress(tool, status, **detail):
    check_cancelled()
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
        self.workers = workers or LIMITS["workers"]
        self.capacity = capacity or LIMITS["task_capacity"]
        self.pool = ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="experiment")
        self.lock = threading.RLock()
        self.condition = threading.Condition(self.lock)
        self.session_locks, self.session_users, self.session_used = {}, {}, {}
        self.events, self.active = {}, {}
        self.pending, self.running = [], set()
        self.accepting = True
        self.stopped = threading.Event()
        self.maintenance = threading.Thread(target=self._maintain, daemon=True, name="session-maintenance")
        self.maintenance.start()

    def _maintain(self):
        while not self.stopped.wait(min(60, LIMITS.get("idle_session_seconds", 900))):
            self.evict_idle()

    def evict_idle(self, make_room=False):
        with self.lock:
            now = time.monotonic()
            candidates = sorted((used, session) for session, used in self.session_used.items() if self.session_users[session] == 0)
            removed = 0
            for used, session in candidates:
                expired = now - used >= LIMITS.get("idle_session_seconds", 900)
                full = make_room and len(self.session_locks) >= LIMITS["session_capacity"]
                if not expired and not full:
                    continue
                self.agent.sessions.pop(session, None)
                del self.session_locks[session], self.session_users[session], self.session_used[session]
                removed += 1
            return removed

    def _pin(self, session):
        with self.lock:
            if session not in self.session_locks:
                self.evict_idle(make_room=True)
                if len(self.session_locks) >= LIMITS["session_capacity"]:
                    raise TaskBusy("All loaded sessions are busy; retry when a task finishes")
                self.session_locks[session] = threading.RLock()
                self.session_users[session] = 0
            self.session_users[session] += 1
            self.session_used[session] = time.monotonic()
            return self.session_locks[session]

    def _unpin(self, session):
        with self.lock:
            self.session_users[session] -= 1
            self.session_used[session] = time.monotonic()

    @contextmanager
    def session_lock(self, session):
        lock = self._pin(session)
        try:
            with lock:
                yield
        finally:
            self._unpin(session)

    def load_session(self, session):
        if session not in self.agent.sessions:
            try:
                self.agent.sessions[session] = self.store.load(self.store.auto_id(session), session)
            except KeyError:
                self.agent.get_session(session)

    def submit(self, session, request_id, payload, operation, cancellable=True):
        request_id = request_id or uuid.uuid4().hex
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128:
            raise ValueError("request_id must contain 1–128 characters")
        key = hashlib.sha256((session + "\0" + request_id).encode()).hexdigest()
        def digest(value):
            return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
        parameters = {k: v for k, v in payload.items() if k != "respond_async"}
        fingerprint = digest(parameters)
        compatible = {fingerprint, digest({**parameters, "respond_async": True}), digest({**parameters, "respond_async": False})}
        with self.condition, self.store.connect() as db:
            existing = db.execute("SELECT * FROM tasks WHERE id=?", (key,)).fetchone()
            if existing:
                if existing["fingerprint"] not in compatible:
                    raise TaskConflict("request_id was already used with different parameters")
                db.execute("UPDATE tasks SET fingerprint=? WHERE id=?", (fingerprint, key))
                return key
            if not self.accepting or len(self.active) >= self.capacity:
                raise TaskBusy("Task queue is full or stopping; retry with the same request_id")
            lock = self._pin(session)
            try:
                db.execute("INSERT INTO tasks (id,session,fingerprint,status,result,created,operation) VALUES (?,?,?,?,?,?,?)",
                           (key, session, fingerprint, "queued", None, time.time(), str(payload.get("operation", "task"))))
                db.commit()
                self.events[key] = []
                self.active[key] = {"session": session, "lock": lock, "operation": operation,
                                    "operation_name": str(payload.get('operation', 'task')),
                                    "cancel": threading.Event(), "cancellable": cancellable, "started": False, "committing": False}
                self.pending.append(key)
                self._dispatch()
            except Exception:
                self._unpin(session)
                raise
        return key

    def _dispatch(self):
        # Waiting tasks from one session never occupy all worker threads.
        while len(self.running) < self.workers:
            key = next((key for key in self.pending if self.active[key]["session"] not in self.running), None)
            if key is None:
                return
            self.pending.remove(key)
            record = self.active[key]
            record["started"] = True
            self.running.add(record["session"])
            self.pool.submit(self._run, key, record)

    def _emit(self, key, event):
        with self.condition:
            events = self.events.setdefault(key, [])
            sequence = events[-1]["sequence"] + 1 if events else 1
            events.append({**event, "task_id": key, "sequence": sequence})
            self.events[key] = events[-256:]
            self.condition.notify_all()

    def _finish(self, key, status, result):
        with self.store.connect() as db:
            db.execute("UPDATE tasks SET status=?,result=? WHERE id=?",
                       (status, json.dumps(result, ensure_ascii=False, allow_nan=False), key))

    def _run(self, key, record):
        session = record["session"]
        token = progress_callback.set(lambda event: self._emit(key, event))
        cancellation = cancel_token.set(record["cancel"])
        try:
            with record["lock"]:
                check_cancelled()
                self.load_session(session)
                with self.condition, self.store.connect() as db:
                    check_cancelled()
                    db.execute("UPDATE tasks SET status='running' WHERE id=?", (key,))
                previous = copy.deepcopy(self.agent.get_session(session))
                prior_processed = self.agent.get_session(session).processed
                try:
                    emit_progress("task", "running")
                    result = record["operation"]()
                    if not isinstance(result, dict):
                        raise ValueError('Task result must be an object')
                    json.dumps(result, ensure_ascii=False, allow_nan=False)
                    with self.condition:
                        check_cancelled()
                        record["committing"] = True
                    # Cancellation is refused after the save boundary.
                    current = self.agent.get_session(session)
                    capture = (current.bundle is not None and current.processed is not None and
                               'error' not in result and record['operation_name'] not in
                               ('open', 'import', 'save', 'rename', 'duplicate', 'delete') and
                               (current.processed is not prior_processed or record['operation_name'] == 'reveal'))
                    self.store.complete_task(key, current, result, capture)
                except (TaskCancelled, Exception):
                    self.agent.sessions[session] = previous
                    raise
        except TaskCancelled as exc:
            self._finish(key, "cancelled", {"error": str(exc), "cancelled": True})
        except Exception as exc:
            self._finish(key, "error", {"error": str(exc)})
        finally:
            cancel_token.reset(cancellation)
            progress_callback.reset(token)
            with self.condition:
                self.active.pop(key, None)
                self.running.discard(session)
                self._unpin(session)
                self._dispatch()
                if len(self.events) > 128:
                    for old in list(self.events):
                        if old not in self.active and old != key:
                            del self.events[old]
                            break
                self.condition.notify_all()

    def cancel(self, key, session):
        with self.condition:
            status = self.status(key, session)
            record = self.active.get(key)
            if not status["can_cancel"] or record is None:
                return {**status, "cancel_requested": False}
            record["cancel"].set()
            if not record["started"]:
                self.pending.remove(key)
                self._finish(key, "cancelled", {"error": "排队任务已取消。", "cancelled": True})
                del self.active[key]
                self._unpin(session)
                self._dispatch()
            else:
                with self.store.connect() as db:
                    db.execute("UPDATE tasks SET status='cancelling' WHERE id=?", (key,))
            self.condition.notify_all()
            return {**self.status(key, session), "cancel_requested": True}

    def status(self, key, session):
        with self.lock, self.store.connect() as db:
            row = db.execute("SELECT * FROM tasks WHERE id=?", (key,)).fetchone()
            if row is None or (session is not None and row["session"] != session):
                raise KeyError("Task not found")
            record = self.active.get(key)
            can_cancel = bool(record and row["status"] not in (*TERMINAL, "cancelling") and
                              not record["committing"] and (row["status"] == "queued" or record["cancellable"]))
            return {"task_id": key, "status": row["status"], "operation": row["operation"], "created": row["created"],
                    "queue_position": self.pending.index(key) + 1 if key in self.pending else 0,
                    "can_cancel": can_cancel, "result": json.loads(row["result"]) if row["result"] else None}

    def list(self, session):
        with self.store.connect() as db:
            keys = [r[0] for r in db.execute("SELECT id FROM tasks WHERE session=? ORDER BY created DESC LIMIT 50", (session,))]
        return [{k: v for k, v in self.status(key, session).items() if k != "result"} for key in keys]

    def wait(self, key, session):
        while True:
            status = self.status(key, session)
            if status["status"] in TERMINAL:
                return status["result"]
            with self.condition:
                self.condition.wait(timeout=0.5)

    def stream(self, key, session):
        cursor = 0
        yield {"event": "progress", "task_id": key, "tool": "task", "status": "queued"}
        while True:
            status = self.status(key, session)
            with self.condition:
                events = [event for event in self.events.get(key, []) if event["sequence"] > cursor]
                if events:
                    cursor = events[-1]["sequence"]
            yield from events
            if status["status"] in TERMINAL:
                yield {"event": "done" if status["status"] == "done" else "error", "task_id": key, **status["result"]}
                return
            with self.condition:
                self.condition.wait(timeout=1)
            yield {"event": "heartbeat", "task_id": key}

    def close(self):
        self.stopped.set()
        self.maintenance.join(timeout=2)
        with self.condition:
            self.accepting = False
            while self.active:
                self.condition.wait(timeout=0.5)
        self.pool.shutdown(wait=True)
