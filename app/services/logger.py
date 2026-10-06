"""
In-memory log ring buffer + strict blacklist filter.

Every log line emitted anywhere in the engine is mirrored into a bounded,
thread-safe deque (maxlen=200) for RAM-slice serving. Internal/technical
noise (asyncio socket exceptions, tracebacks, HTTP access spam, DEBUG, ...)
is REJECTED from the buffer and instead appended to bot.err on disk for
background debugging — it can never leak into the customer-facing feed.
"""
import logging
import threading
import time
from collections import deque
from typing import Deque, List, Optional

# ---------------------------------------------------------------------------
# Strict blacklist: any line containing these substrings is technical noise.
# It is dropped from the memory ring buffer and redirected to bot.err.
# ---------------------------------------------------------------------------
BLACKLIST = (
    "asyncio",
    "socket.send",
    "traceback",
    "error 155",
    "exception",
    "brokenpipeerror",
    "connectionreset",
    "debug",
    "http",
    "get /",
    "post /",
    # Legacy raw-internal markers (defense in depth for older call sites):
    "socketworker",
    "gateway ack",
    "opcode:",
    "api_routes",
    "using cached token",
    "tokendaemon",
    "autonomousscheduler",
)

ERR_LOG_PATH = "bot.err"
_err_lock = threading.Lock()


def is_blacklisted(line: str) -> bool:
    """True when a line is internal/technical noise that must never reach the web feed."""
    lowered = (line or "").lower()
    return any(marker in lowered for marker in BLACKLIST)


def append_err_log(line: str) -> None:
    """Append a technical line to bot.err (background debugging only)."""
    try:
        with _err_lock:
            with open(ERR_LOG_PATH, "a", encoding="utf-8") as f:
                ts = time.strftime("%Y-%m-%d %H:%M:%S")
                f.write(f"{ts} {line}\n")
    except Exception:
        pass


class LogRingBuffer:
    """Thread-safe bounded buffer of recent log lines."""

    def __init__(self, maxlen: int = 200):
        self._buf: Deque[str] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def push(self, line: str) -> None:
        line = (line or "").rstrip("\r\n")
        if not line:
            return
        if is_blacklisted(line):
            # Redirect internal noise to the on-disk error log — NEVER the ring
            # buffer that serves the web terminal.
            append_err_log(line)
            return
        with self._lock:
            self._buf.append(line)
        # Instant fan-out to live SSE subscribers — real-time telemetry.
        # Lazy import avoids a circular import at module load.
        try:
            from app.services.activity_stream import activity_stream

            activity_stream.notify(line)
        except Exception:
            pass

    def tail(self, n: Optional[int] = None) -> List[str]:
        """Snapshot of the last n lines (or all, if n is falsy). Lock-held copy."""
        with self._lock:
            snapshot = list(self._buf)
        return snapshot[-n:] if n else snapshot


# Global singleton used by the API endpoints and the logging handler below.
log_buffer = LogRingBuffer(maxlen=200)


class RingBufferLogHandler(logging.Handler):
    """Mirrors every record reaching the root logger into the ring buffer."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
        except Exception:
            msg = record.getMessage()
        # Technical records go straight to bot.err without touching the buffer
        # (is_blacklisted runs again inside push, but skipping the fan-out here
        # avoids double work for clearly-blacklisted logger names).
        ts = time.strftime("%I:%M:%S %p")
        line = f"{ts} [{record.name}] {msg}"
        log_buffer.push(line)
        # NOTE: deliberately NO bridge into the per-tenant activity history —
        # that history feeds the customer-facing CLEAN feed, which must only
        # ever contain named scheduler/dashboard events, never raw protocol
        # internals. Raw (non-blacklisted) lines are served from this ring
        # buffer and the RAW SSE channel only.


_installed = False


def install_ring_buffer_handler(level: int = logging.INFO) -> None:
    """Attach the ring-buffer handler to the root logger (idempotent)."""
    global _installed
    if _installed:
        return
    handler = RingBufferLogHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    # App loggers emit INFO-level engine telemetry (workers, scheduler, combat).
    # Root defaults to WARNING, which would drop them before they reach us.
    if root.level == logging.NOTSET or root.level > level:
        root.setLevel(level)
    _installed = True
