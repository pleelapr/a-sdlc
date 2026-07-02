"""End-to-end HTTP test for per-session project isolation (FIX: session isolation).

This is the only test that drives the real ``streamable_http_app()`` over the
transport, so it catches contextvar/session regressions that unit tests (which
call tool functions directly) cannot. It proves two concurrent MCP sessions on
different projects resolve independently and never touch the process-global
binding.

Requires stateful mode (A_SDLC_STATELESS_HTTP unset, the default). The MCP
session manager can only be ``run()`` once per instance, so each test resets
``mcp._session_manager`` to force a fresh manager and enters exactly one
lifespan via a single ``with TestClient(...)`` block.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient

import a_sdlc.server as server

INIT_HEADERS = {"Accept": "application/json, text/event-stream"}
PROTOCOL_VERSION = "2025-06-18"


def _parse_sse(text: str) -> dict:
    """Extract the JSON payload from an SSE ``data:`` line."""
    for line in text.splitlines():
        if line.startswith("data:"):
            return json.loads(line[len("data:") :].strip())
    raise AssertionError(f"no SSE data line in response: {text!r}")


def _initialize(client: TestClient) -> str:
    """Perform the MCP initialize handshake; return the minted session id."""
    resp = client.post(
        "/mcp",
        headers=INIT_HEADERS,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "pytest", "version": "1.0"},
            },
        },
    )
    assert resp.status_code == 200, resp.text
    sid = resp.headers.get("mcp-session-id")
    assert sid, f"no mcp-session-id header: {dict(resp.headers)}"
    # Complete the handshake with the initialized notification.
    note = client.post(
        "/mcp",
        headers={**INIT_HEADERS, "mcp-session-id": sid},
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
    )
    assert note.status_code in (200, 202), note.text
    return sid


def _call_tool(client: TestClient, sid: str, name: str, arguments: dict, req_id: int) -> dict:
    """Call an MCP tool over the session; return the tool's structured result."""
    resp = client.post(
        "/mcp",
        headers={**INIT_HEADERS, "mcp-session-id": sid},
        json={
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
    )
    assert resp.status_code == 200, resp.text
    envelope = _parse_sse(resp.text)
    result = envelope["result"]
    # FastMCP puts a dict return in structuredContent; fall back to text content.
    if "structuredContent" in result and result["structuredContent"] is not None:
        return result["structuredContent"]
    return json.loads(result["content"][0]["text"])


def _mock_db():
    """DB stub covering switch_project + get_context for proj-a / proj-b."""
    db = MagicMock()

    def get_project(pid):
        if pid in ("proj-a", "proj-b"):
            return {"id": pid, "shortname": pid[-1].upper() * 4, "name": pid}
        return None

    db.get_project.side_effect = get_project
    db.list_tasks.return_value = []
    db.list_sprints.return_value = []
    db.list_prds.return_value = []
    db.list_projects.return_value = [
        {"id": "proj-a", "shortname": "AAAA", "name": "proj-a"},
        {"id": "proj-b", "shortname": "BBBB", "name": "proj-b"},
    ]
    db.update_project_accessed.return_value = None
    return db


@pytest.fixture
def http(monkeypatch, tmp_path):
    """Fresh MCP session manager + isolated cwd (no marker leakage) + mocked DB."""
    if server._STATELESS:
        pytest.skip("HTTP isolation requires stateful mode (A_SDLC_STATELESS_HTTP unset)")
    monkeypatch.chdir(tmp_path)
    server._active_project_id = None
    server._session_projects.reset()
    # Force a fresh session manager so run() can start in this test's lifespan.
    server.mcp._session_manager = None
    with patch.object(server, "get_db", return_value=_mock_db()):
        app = server.mcp.streamable_http_app()
        with TestClient(app) as client:
            yield client
    server.mcp._session_manager = None


class TestHttpSessionIsolation:
    def test_two_sessions_do_not_collide(self, http: TestClient):
        # Two independent conversations.
        sid_a = _initialize(http)
        sid_b = _initialize(http)
        assert sid_a != sid_b  # distinct server-minted session ids

        # Each binds a different project.
        r_a = _call_tool(http, sid_a, "switch_project", {"project_id": "proj-a"}, 10)
        r_b = _call_tool(http, sid_b, "switch_project", {"project_id": "proj-b"}, 20)
        assert r_a["context_scope"] == "session"
        assert r_b["context_scope"] == "session"

        # Resolution is per-session: A sees proj-a, B sees proj-b.
        ctx_a = _call_tool(http, sid_a, "get_context", {}, 11)
        ctx_b = _call_tool(http, sid_b, "get_context", {}, 21)
        assert ctx_a["status"] == "ok" and ctx_a["project"]["id"] == "proj-a"
        assert ctx_b["status"] == "ok" and ctx_b["project"]["id"] == "proj-b"

        # B re-switching does not disturb A.
        _call_tool(http, sid_b, "switch_project", {"project_id": "proj-a"}, 22)
        ctx_a_again = _call_tool(http, sid_a, "get_context", {}, 12)
        assert ctx_a_again["project"]["id"] == "proj-a"

        # HTTP writes never touch the process-global binding.
        assert server._active_project_id is None

    def test_fresh_session_gets_no_project_guidance(self, http: TestClient):
        sid = _initialize(http)
        ctx = _call_tool(http, sid, "get_context", {}, 30)
        assert ctx["status"] == "no_project"
        assert "next_steps" in ctx
        assert any(p["id"] == "proj-a" for p in ctx["known_projects"])
        assert server._active_project_id is None

    def test_unknown_session_id_is_rejected(self, http: TestClient):
        # A tools/call with a bogus session id must not be served.
        resp = http.post(
            "/mcp",
            headers={**INIT_HEADERS, "mcp-session-id": "deadbeefdeadbeef"},
            json={
                "jsonrpc": "2.0",
                "id": 99,
                "method": "tools/call",
                "params": {"name": "get_context", "arguments": {}},
            },
        )
        assert resp.status_code in (400, 404), resp.text
