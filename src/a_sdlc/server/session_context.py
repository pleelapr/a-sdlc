"""Bounded, thread-safe per-session project-context store.

One MCP streamable-http session (one server-minted ``mcp-session-id``)
corresponds to one Claude Code conversation. Binding project context to that
id instead of a process-global makes concurrent sessions on different projects
independent: ``switch_project`` in one conversation never affects another.

The MCP SDK does not notify application code when a session terminates
(DELETE-terminated transports are not even removed from its own internal map),
so eviction here is lazy: an LRU cap plus an idle TTL enforced under the lock
on every ``get``/``set``. The SDK's own ``session_idle_timeout`` separately
reaps idle transports server-side. Together these bound memory without relying
on a session-close callback the SDK does not provide.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass

DEFAULT_MAX_ENTRIES = 1024
DEFAULT_TTL_SECONDS = 86400.0  # 24h idle


@dataclass
class _Entry:
    project_id: str
    last_used: float  # time.monotonic()


class SessionProjectStore:
    """Maps ``mcp-session-id`` -> bound ``project_id`` with LRU + TTL eviction.

    Thread-safe: sync MCP tools run inline on the request task today, but the
    process co-hosts the UI uvicorn server and a future SDK could thread tool
    execution, so every operation takes a lock. The lock is uncontended in the
    common case and cheap.
    """

    def __init__(
        self,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
    ) -> None:
        self._max = max(1, max_entries)
        self._ttl = ttl_seconds
        self._entries: OrderedDict[str, _Entry] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, session_id: str) -> str | None:
        """Return the project bound to *session_id*, or ``None``.

        Refreshes recency on hit; drops and returns ``None`` on TTL expiry.
        """
        now = time.monotonic()
        with self._lock:
            entry = self._entries.get(session_id)
            if entry is None:
                return None
            if now - entry.last_used > self._ttl:
                del self._entries[session_id]
                return None
            entry.last_used = now
            self._entries.move_to_end(session_id)
            return entry.project_id

    def set(self, session_id: str, project_id: str) -> None:
        """Bind *project_id* to *session_id*, evicting the LRU entry if over cap."""
        with self._lock:
            self._entries[session_id] = _Entry(project_id, time.monotonic())
            self._entries.move_to_end(session_id)
            while len(self._entries) > self._max:
                self._entries.popitem(last=False)

    def clear(self, session_id: str) -> None:
        """Drop the binding for *session_id* (e.g. its project was deleted)."""
        with self._lock:
            self._entries.pop(session_id, None)

    def count(self) -> int:
        """Number of live bindings (for the /health snapshot)."""
        with self._lock:
            return len(self._entries)

    def reset(self) -> None:
        """Drop all bindings. Test hook, called from conftest between tests."""
        with self._lock:
            self._entries.clear()
