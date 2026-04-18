"""Per-session tracking."""
import time
import uuid


class SessionTracker:
    def __init__(self):
        self._session_id: str = str(uuid.uuid4())[:8]
        self._start_time: float = time.time()
        self._call_count: int = 0
        self._success_count: int = 0
        self._error_count: int = 0
        self._total_duration_ms: float = 0

    def record_call(self, status: str, duration_ms: float):
        self._call_count += 1
        self._total_duration_ms += duration_ms
        if status == "success":
            self._success_count += 1
        else:
            self._error_count += 1

    @property
    def session_id(self) -> str:
        return self._session_id

    def get_stats(self) -> dict:
        elapsed = time.time() - self._start_time
        return {
            "session_id": self._session_id,
            "uptime_seconds": round(elapsed, 1),
            "total_calls": self._call_count,
            "success_calls": self._success_count,
            "error_calls": self._error_count,
            "avg_duration_ms": round(self._total_duration_ms / max(self._call_count, 1), 2),
        }

    def reset(self):
        self._session_id = str(uuid.uuid4())[:8]
        self._start_time = time.time()
        self._call_count = 0
        self._success_count = 0
        self._error_count = 0
        self._total_duration_ms = 0
