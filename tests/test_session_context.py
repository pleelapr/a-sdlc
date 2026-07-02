"""Unit tests for per-session project context (FIX: session isolation).

Covers the SessionProjectStore, the mcp-session-id resolution helper, the
set_active_project binder, and the fail-closed resolution rule that keeps one
session from ever seeing another session's (or a test's) project binding.
"""

from __future__ import annotations

from unittest.mock import MagicMock, PropertyMock, patch

from a_sdlc.server.session_context import SessionProjectStore

# ---------------------------------------------------------------------------
# SessionProjectStore
# ---------------------------------------------------------------------------


class TestSessionProjectStore:
    def test_set_get_roundtrip(self):
        store = SessionProjectStore()
        store.set("sess-1", "proj-a")
        assert store.get("sess-1") == "proj-a"
        assert store.get("missing") is None

    def test_clear_removes_binding(self):
        store = SessionProjectStore()
        store.set("sess-1", "proj-a")
        store.clear("sess-1")
        assert store.get("sess-1") is None
        # clearing an unknown key is a no-op
        store.clear("nope")

    def test_count_and_reset(self):
        store = SessionProjectStore()
        store.set("a", "p1")
        store.set("b", "p2")
        assert store.count() == 2
        store.reset()
        assert store.count() == 0

    def test_lru_eviction_at_cap(self):
        store = SessionProjectStore(max_entries=2)
        store.set("a", "p1")
        store.set("b", "p2")
        store.set("c", "p3")  # evicts "a" (least recently used)
        assert store.get("a") is None
        assert store.get("b") == "p2"
        assert store.get("c") == "p3"

    def test_get_refreshes_recency(self):
        store = SessionProjectStore(max_entries=2)
        store.set("a", "p1")
        store.set("b", "p2")
        store.get("a")  # "a" now most-recently used
        store.set("c", "p3")  # evicts "b", not "a"
        assert store.get("a") == "p1"
        assert store.get("b") is None

    def test_ttl_expiry(self):
        # Drive the monotonic clock deterministically.
        clock = {"t": 1000.0}
        with patch("a_sdlc.server.session_context.time.monotonic", side_effect=lambda: clock["t"]):
            store = SessionProjectStore(ttl_seconds=10.0)
            store.set("a", "p1")
            clock["t"] = 1005.0
            assert store.get("a") == "p1"  # within TTL, refreshes last_used
            clock["t"] = 1020.0  # 15s after the refresh -> expired
            assert store.get("a") is None
            assert store.count() == 0  # expired entry dropped

    def test_zero_max_entries_floored_to_one(self):
        store = SessionProjectStore(max_entries=0)
        store.set("a", "p1")
        assert store.get("a") == "p1"


# ---------------------------------------------------------------------------
# _current_session_id
# ---------------------------------------------------------------------------


def _ctx_with_header(value):
    """A get_context() return whose request carries an mcp-session-id header."""
    ctx = MagicMock()
    ctx.request_context.request.headers = {"mcp-session-id": value}
    return ctx


def _ctx_no_request():
    """A get_context() return with request_context.request == None."""
    ctx = MagicMock()
    ctx.request_context.request = None
    return ctx


class TestCurrentSessionId:
    def test_returns_none_outside_request(self):
        import a_sdlc.server as server

        ctx = MagicMock()
        # .request_context raises ValueError outside a request (real SDK behavior)
        type(ctx).request_context = PropertyMock(side_effect=ValueError("no request"))
        with patch.object(server.mcp, "get_context", return_value=ctx):
            assert server._current_session_id() is None

    def test_returns_none_when_request_missing(self):
        import a_sdlc.server as server

        with patch.object(server.mcp, "get_context", return_value=_ctx_no_request()):
            assert server._current_session_id() is None

    def test_returns_header_value(self):
        import a_sdlc.server as server

        with patch.object(server.mcp, "get_context", return_value=_ctx_with_header("sess-xyz")):
            assert server._current_session_id() == "sess-xyz"


# ---------------------------------------------------------------------------
# set_active_project
# ---------------------------------------------------------------------------


class TestSetActiveProject:
    def test_session_scope_binds_store_not_global(self):
        import a_sdlc.server as server

        server._active_project_id = None
        with patch.object(server, "_current_session_id", return_value="sess-1"):
            scope = server.set_active_project("proj-a")
        assert scope == "session"
        assert server._session_projects.get("sess-1") == "proj-a"
        assert server._active_project_id is None  # global untouched

    def test_process_scope_sets_global(self):
        import a_sdlc.server as server

        server._active_project_id = None
        with patch.object(server, "_current_session_id", return_value=None):
            scope = server.set_active_project("proj-b")
        assert scope == "process"
        assert server._active_project_id == "proj-b"


# ---------------------------------------------------------------------------
# _get_current_project_id resolution + fail-closed isolation
# ---------------------------------------------------------------------------


class TestResolutionFailClosed:
    def test_session_request_never_reads_process_global(self, tmp_path):
        """The core isolation guarantee: a session request must not inherit the
        process-global binding (which a test or another code path may have set).
        """
        import a_sdlc.server as server

        server._active_project_id = "other-session-project"
        db = MagicMock()
        db.get_project.return_value = {"id": "other-session-project"}
        with (
            patch.object(server, "_current_session_id", return_value="sess-1"),
            patch.object(server, "get_db", return_value=db),
            patch("a_sdlc.server.os.getcwd", return_value=str(tmp_path)),  # no marker
        ):
            # Session has no binding and no marker -> resolves to None, NOT the global.
            assert server._get_current_project_id() is None

    def test_session_binding_resolves(self, tmp_path):
        import a_sdlc.server as server

        server._session_projects.reset()
        server._session_projects.set("sess-1", "proj-a")
        db = MagicMock()
        db.get_project.return_value = {"id": "proj-a"}
        with (
            patch.object(server, "_current_session_id", return_value="sess-1"),
            patch.object(server, "get_db", return_value=db),
            patch("a_sdlc.server.os.getcwd", return_value=str(tmp_path)),
        ):
            assert server._get_current_project_id() == "proj-a"

    def test_session_binding_beats_marker(self, tmp_path):
        import a_sdlc.server as server
        from a_sdlc.core.project_marker import write_marker

        write_marker(tmp_path, "marker-project", "MARK", "Marker Project")
        server._session_projects.reset()
        server._session_projects.set("sess-1", "proj-a")
        db = MagicMock()
        db.get_project.return_value = {"id": "proj-a"}
        with (
            patch.object(server, "_current_session_id", return_value="sess-1"),
            patch.object(server, "get_db", return_value=db),
            patch("a_sdlc.server.os.getcwd", return_value=str(tmp_path)),
        ):
            assert server._get_current_project_id() == "proj-a"

    def test_deleted_bound_project_falls_through_to_marker(self, tmp_path):
        import a_sdlc.server as server
        from a_sdlc.core.project_marker import write_marker

        write_marker(tmp_path, "marker-project", "MARK", "Marker Project")
        server._session_projects.reset()
        server._session_projects.set("sess-1", "gone")

        def get_project(pid):
            return None if pid == "gone" else {"id": pid}

        db = MagicMock()
        db.get_project.side_effect = get_project
        with (
            patch.object(server, "_current_session_id", return_value="sess-1"),
            patch.object(server, "get_db", return_value=db),
            patch("a_sdlc.server.os.getcwd", return_value=str(tmp_path)),
        ):
            # bound project deleted -> stale binding cleared -> marker used
            assert server._get_current_project_id() == "marker-project"
        assert server._session_projects.get("sess-1") is None  # stale binding cleared

    def test_no_session_uses_process_global(self, tmp_path):
        import a_sdlc.server as server

        server._active_project_id = "proj-global"
        db = MagicMock()
        db.get_project.return_value = {"id": "proj-global"}
        with (
            patch.object(server, "_current_session_id", return_value=None),
            patch.object(server, "get_db", return_value=db),
            patch("a_sdlc.server.os.getcwd", return_value=str(tmp_path)),
        ):
            assert server._get_current_project_id() == "proj-global"


# ---------------------------------------------------------------------------
# switch_project tool: scope reporting + isolation
# ---------------------------------------------------------------------------


class TestSwitchProjectTool:
    def test_direct_call_reports_process_scope(self):
        import a_sdlc.server as server
        from a_sdlc.server import switch_project

        server._active_project_id = None
        db = MagicMock()
        db.get_project.return_value = {"id": "proj-a", "name": "A"}
        with (
            patch.object(server, "get_db", return_value=db),
            patch.object(server, "_current_session_id", return_value=None),
        ):
            result = switch_project("proj-a")
        assert result["status"] == "ok"
        assert result["context_scope"] == "process"
        assert server._active_project_id == "proj-a"

    def test_session_call_reports_session_scope(self):
        import a_sdlc.server as server
        from a_sdlc.server import switch_project

        server._active_project_id = None
        server._session_projects.reset()
        db = MagicMock()
        db.get_project.return_value = {"id": "proj-a", "name": "A"}
        with (
            patch.object(server, "get_db", return_value=db),
            patch.object(server, "_current_session_id", return_value="sess-1"),
        ):
            result = switch_project("proj-a")
        assert result["context_scope"] == "session"
        assert server._session_projects.get("sess-1") == "proj-a"
        assert server._active_project_id is None  # isolation: global untouched

    def test_not_found(self):
        import a_sdlc.server as server
        from a_sdlc.server import switch_project

        db = MagicMock()
        db.get_project.return_value = None
        with patch.object(server, "get_db", return_value=db):
            result = switch_project("nope")
        assert result["status"] == "not_found"
