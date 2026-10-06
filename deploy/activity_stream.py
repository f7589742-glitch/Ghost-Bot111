import asyncio
import datetime
import queue
import threading
from collections import deque
from typing import List, Set, Tuple
from fastapi import WebSocket


class ActivityStreamManager:
    def __init__(self, maxlen: int = 100):
        # Per-tenant histories: tenant A never sees tenant B's lines.
        self._histories: dict = {}
        self._maxlen = maxlen
        self._clients: Set[WebSocket] = set()
        self._lock = asyncio.Lock()
        self._tlock = threading.Lock()
        # Waiters stored as (queue, user_id)
        self._waiters_raw: List[Tuple[queue.Queue, str]] = []
        self._waiters_clean: List[Tuple[queue.Queue, str]] = []
        self._wlock = threading.Lock()

    def subscribe(self, raw: bool = False, user_id: str = "") -> queue.Queue:
        """Register an SSE subscriber. Returns its live-line queue strictly partitioned by user_id."""
        q: queue.Queue = queue.Queue(maxsize=500)
        uid = str(user_id or "").strip()
        with self._wlock:
            target_list = self._waiters_raw if raw else self._waiters_clean
            target_list.append((q, uid))
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._wlock:
            for waiters in (self._waiters_raw, self._waiters_clean):
                entry = next((e for e in waiters if e[0] is q), None)
                if entry:
                    try:
                        waiters.remove(entry)
                        break
                    except ValueError:
                        continue

    @staticmethod
    def _fanout(waiters: List[Tuple[queue.Queue, str]], line: str, user_id: str = "") -> None:
        uid = str(user_id or "").strip()
        for q, w_uid in waiters:
            # Deliver if waiter has no uid constraint (admin/system) or waiter matches message's user_id
            if not w_uid or not uid or w_uid == uid:
                try:
                    q.put_nowait(line)
                except queue.Full:
                    try:
                        for _ in range(max(1, q.qsize() // 2)):
                            q.get_nowait()
                        q.put_nowait(line)
                    except Exception:
                        pass

    def notify(self, line: str, user_id: str = "") -> None:
        with self._wlock:
            waiters = list(self._waiters_raw)
        self._fanout(waiters, line, user_id=user_id)

    def notify_clean(self, line: str, user_id: str = "") -> None:
        with self._wlock:
            waiters = list(self._waiters_clean)
        self._fanout(waiters, line, user_id=user_id)

    def push_line(self, line: str, user_id: str = "") -> None:
        with self._tlock:
            self._history(user_id or "").append(line)

    def _history(self, user_id: str = ""):
        key = user_id or ""
        dq = self._histories.get(key)
        if dq is None:
            dq = deque(maxlen=self._maxlen)
            self._histories[key] = dq
        return dq

    def format_event(self, action: str, kingdom_id: str = None) -> str:
        now = datetime.datetime.now()
        time_str = now.strftime("%I:%M:%S %p")
        if kingdom_id:
            kd_clean = str(kingdom_id).replace("KD", "").strip()
            return f"{time_str} [{kd_clean} KD] {action}"
        else:
            return f"{time_str} {action}"

    async def connect(self, websocket: WebSocket, user_id: str = ""):
        await websocket.accept()
        async with self._lock:
            self._clients.add(websocket)
            # Send current tenant backlog
            for item in list(self._history(user_id)):
                try:
                    await websocket.send_text(item)
                except Exception:
                    pass

    async def disconnect(self, websocket: WebSocket):
        async with self._lock:
            if websocket in self._clients:
                self._clients.remove(websocket)

    _RAW_PATTERNS = (
        "socketworker",
        "gateway ack",
        "opcode:",
        "api_routes",
        "using cached token",
        "autonomousscheduler",
    )

    async def broadcast(self, message: str, kingdom_id: str = None, user_id: str = ""):
        if any(p in (message or "").lower() for p in self._RAW_PATTERNS):
            return
        formatted = self.format_event(message, kingdom_id)
        uid = str(user_id or "").strip()

        try:
            from app.services.logger import log_buffer
            log_buffer.push(formatted)
        except Exception:
            pass

        # Fan out to clean subscribers matching this tenant
        self.notify_clean(formatted, user_id=uid)
        self.notify(formatted, user_id=uid)

        async with self._lock:
            self._history(uid).append(formatted)
            dead_clients = set()
            for ws in self._clients:
                try:
                    await ws.send_text(formatted)
                except Exception:
                    dead_clients.add(ws)
            for dead in dead_clients:
                self._clients.discard(dead)

    def get_recent(self, user_id: str = "") -> List[str]:
        uid = str(user_id or "").strip()
        return list(self._history(uid))


activity_stream = ActivityStreamManager(maxlen=100)
