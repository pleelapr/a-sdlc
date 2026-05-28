"""
Server health tracking singleton with ring buffer for connection events.

Provides in-memory health state for the /health endpoint:
- Uptime tracking via monotonic clock
- Connection event ring buffer (last 100 events)
- Active connection counter
- Last error recording
- Memory usage via stdlib `resource` module

All reads are in-memory with no I/O, targeting <100ms response time.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any

import a_sdlc


class ServerHealth:
    """Singleton tracking server health metrics.

    Uses a deque-based ring buffer (maxlen=100) for connection events
    and atomic counters protected by a threading lock for concurrent
    safety in multi-threaded HTTP transports.
    """

    _instance: ServerHealth | None = None
    _lock = threading.Lock()

    def __new__(cls) -> ServerHealth:
        if cls._instance is None:
            with cls._lock:
                # Double-checked locking pattern
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._init()
                    cls._instance = instance
        return cls._instance

    def _init(self) -> None:
        """Initialize health state (called once on first instantiation)."""
        self._start_time: float = time.monotonic()
        self._connection_events: deque[dict[str, Any]] = deque(maxlen=100)
        self._last_error: dict[str, Any] | None = None
        self._active_connections: int = 0
        self._state_lock = threading.Lock()

    def record_event(self, event_type: str, detail: str = "") -> None:
        """Record a connection event in the ring buffer.

        Args:
            event_type: Type of event (e.g. "connect", "disconnect", "error").
            detail: Optional detail string describing the event.
        """
        event = {
            "type": event_type,
            "detail": detail,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "monotonic": time.monotonic(),
        }
        with self._state_lock:
            self._connection_events.append(event)

    def record_error(self, error: Exception | str) -> None:
        """Record the most recent error.

        Args:
            error: The exception or error message string.
        """
        if isinstance(error, Exception):
            error_detail = {
                "type": type(error).__name__,
                "message": str(error),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        else:
            error_detail = {
                "type": "Error",
                "message": str(error),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        with self._state_lock:
            self._last_error = error_detail

    def increment_connections(self) -> None:
        """Increment the active connection counter."""
        with self._state_lock:
            self._active_connections += 1

    def decrement_connections(self) -> None:
        """Decrement the active connection counter (floor at 0)."""
        with self._state_lock:
            self._active_connections = max(0, self._active_connections - 1)

    def _get_memory_mb(self) -> float:
        """Get current process memory usage in MB via stdlib resource module.

        On macOS (darwin), ru_maxrss is in bytes.
        On Linux, ru_maxrss is in kilobytes.
        On Windows, falls back to 0.0 since resource module is unavailable.
        """
        try:
            import resource as res_mod

            maxrss = res_mod.getrusage(res_mod.RUSAGE_SELF).ru_maxrss
            if sys.platform == "darwin":
                return round(maxrss / (1024 * 1024), 2)
            else:
                # Linux: kilobytes
                return round(maxrss / 1024, 2)
        except (ImportError, AttributeError):
            # Windows or other platforms without resource module
            return 0.0

    def get_health(self, include_events: bool = False) -> dict[str, Any]:
        """Build the health status payload.

        Args:
            include_events: If True, include the full ring buffer contents.

        Returns:
            Dictionary with health status fields suitable for JSON serialization.
        """
        uptime = time.monotonic() - self._start_time

        with self._state_lock:
            payload: dict[str, Any] = {
                "status": "healthy",
                "version": a_sdlc.__version__,
                "uptime_seconds": round(uptime, 2),
                "pid": os.getpid(),
                "memory_mb": self._get_memory_mb(),
                "active_connections": self._active_connections,
                "last_error": self._last_error,
                "connection_events_count": len(self._connection_events),
            }
            if include_events:
                payload["connection_events"] = list(self._connection_events)

        return payload

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton instance (for testing only)."""
        with cls._lock:
            cls._instance = None
