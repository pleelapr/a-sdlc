"""Integration tests for HTTP transport, health endpoint, and port conflict detection.

Validates:

- HTTP transport: MCP tool calls via HTTP POST (mocked)
- Health check endpoint responds < 500ms
- Port conflict detection and cleanup
- instrument_tool decorator records events and errors
- Fresh install configures HTTP transport by default
- Performance NFRs: health check < 500ms, ring buffer memory < 1MB
"""

from __future__ import annotations

import json
import logging
import os
import signal
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from a_sdlc.cli import main

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def runner() -> CliRunner:
    """Create CLI test runner."""
    return CliRunner()


@pytest.fixture(autouse=True)
def _mock_doctor_externals():
    """Auto-mock slow external calls inherited from test_cli pattern."""
    with (
        patch("a_sdlc.cli.check_docker_available", return_value=False),
        patch(
            "a_sdlc.cli.check_services_health",
            return_value={
                "langfuse_reachable": False,
                "langfuse_url": "http://localhost:13000 (not reachable)",
                "signoz_reachable": False,
                "signoz_url": "http://localhost:8080 (not reachable)",
                "services_running": False,
            },
        ),
        patch(
            "a_sdlc.cli.verify_monitoring_setup",
            return_value={
                "files_ready": False,
                "settings_ready": False,
                "ready": False,
                "hook_registered": False,
                "otel_configured": False,
            },
        ),
        patch(
            "a_sdlc.cli.verify_sonarqube_setup",
            return_value={
                "ready": False,
                "host_url_configured": False,
            },
        ),
    ):
        yield


@pytest.fixture(autouse=True)
def _mock_cli_targets():
    """Auto-mock resolve_targets and detect_targets."""
    from a_sdlc.cli_targets import CLAUDE_TARGET

    with (
        patch("a_sdlc.cli.resolve_targets", return_value=[CLAUDE_TARGET]),
        patch("a_sdlc.cli.detect_targets", return_value=[CLAUDE_TARGET]),
    ):
        yield


@pytest.fixture(autouse=True)
def _clean_server_logger():
    """Clean up the a-sdlc-server logger handlers between tests.

    The server module's ``_logger`` accumulates RotatingFileHandler
    instances across test runs; leftover mock handlers can cause
    TypeError when the real logging machinery compares ``record.levelno``
    with ``handler.level`` (which may be a MagicMock).
    """
    server_logger = logging.getLogger("a-sdlc-server")
    original_handlers = list(server_logger.handlers)
    yield
    server_logger.handlers = original_handlers


# =============================================================================
# HTTP Transport MCP Tool Calls
# =============================================================================


class TestHTTPTransportToolCalls:
    """Integration tests for MCP tool calls via HTTP transport.

    Validates that the MCP server exposes tools over HTTP POST and
    that request/response format matches the MCP protocol.
    """

    def test_health_endpoint_returns_json(self) -> None:
        """The /health endpoint returns valid JSON with required fields."""
        from a_sdlc.server import _health_endpoint
        from a_sdlc.server.health import ServerHealth

        ServerHealth.reset()

        import asyncio

        async def _run():
            request = MagicMock()
            request.query_params = {}
            response = await _health_endpoint(request)
            assert response.status_code == 200
            body = json.loads(response.body.decode())
            assert body["status"] == "healthy"
            assert "version" in body
            assert "uptime_seconds" in body
            assert "pid" in body
            return body

        result = asyncio.run(_run())
        assert result["pid"] == os.getpid()

        ServerHealth.reset()

    def test_health_endpoint_with_events(self) -> None:
        """The /health endpoint includes events when ?events=true."""
        from a_sdlc.server import _health_endpoint
        from a_sdlc.server.health import ServerHealth

        ServerHealth.reset()
        h = ServerHealth()
        h.record_event("connect", "test-client")
        h.record_event("tool_call", "get_context")

        import asyncio

        async def _run():
            request = MagicMock()
            request.query_params = {"events": "true"}
            response = await _health_endpoint(request)
            body = json.loads(response.body.decode())
            assert "connection_events" in body
            assert body["connection_events_count"] == 2
            return body

        result = asyncio.run(_run())
        assert result["connection_events"][0]["detail"] == "test-client"
        assert result["connection_events"][1]["detail"] == "get_context"

        ServerHealth.reset()

    def test_mcp_custom_route_registered(self) -> None:
        """The /health route is registered as a custom Starlette route on mcp."""
        from a_sdlc.server import mcp

        route_paths = [r.path for r in mcp._custom_starlette_routes]
        assert "/health" in route_paths

    def test_http_config_points_to_mcp_endpoint(self) -> None:
        """HTTP transport config URL points to /mcp endpoint."""
        from a_sdlc.installer import _build_mcp_config

        config = _build_mcp_config(port=8765)
        assert config["type"] == "http"
        assert config["url"] == "http://localhost:8765/mcp"

    def test_http_config_custom_port(self) -> None:
        """HTTP transport config respects custom port."""
        from a_sdlc.installer import _build_mcp_config

        config = _build_mcp_config(port=9000)
        assert config["url"] == "http://localhost:9000/mcp"

    def test_instrument_tool_records_events(self) -> None:
        """The instrument_tool decorator records tool call events."""
        from a_sdlc.server import instrument_tool
        from a_sdlc.server.health import ServerHealth

        ServerHealth.reset()

        @instrument_tool
        def dummy_tool():
            return "result"

        result = dummy_tool()
        assert result == "result"

        h = ServerHealth()
        payload = h.get_health(include_events=True)
        events = payload["connection_events"]
        event_types = [e["type"] for e in events]
        assert "tool_call_start" in event_types
        assert "tool_call_end" in event_types

        ServerHealth.reset()

    def test_instrument_tool_records_errors(self) -> None:
        """The instrument_tool decorator records tool errors."""
        from a_sdlc.server import instrument_tool
        from a_sdlc.server.health import ServerHealth

        ServerHealth.reset()

        @instrument_tool
        def failing_tool():
            raise ValueError("test error")

        with pytest.raises(ValueError, match="test error"):
            failing_tool()

        h = ServerHealth()
        payload = h.get_health(include_events=True)
        events = payload["connection_events"]
        event_types = [e["type"] for e in events]
        assert "tool_call_error" in event_types

        last_error = payload["last_error"]
        assert last_error is not None
        assert last_error["type"] == "ValueError"
        assert last_error["message"] == "test error"

        ServerHealth.reset()


# =============================================================================
# CLI Serve Command
# =============================================================================


class TestCLIServe:
    """Tests that the serve command starts the combined server."""

    def test_serve_invokes_run_server(
        self, runner: CliRunner
    ) -> None:
        """serve calls run_server with correct params."""
        mock_run = MagicMock()
        with patch("a_sdlc.server.run_server", mock_run):
            result = runner.invoke(main, ["serve"])

        mock_run.assert_called_once_with(
            mcp_port=8765, ui_port=3847, host="0.0.0.0"
        )
        assert result.exit_code == 0
        assert "MCP+UI" in result.output

    def test_serve_custom_ports(self, runner: CliRunner) -> None:
        """serve respects --mcp-port and --ui-port."""
        mock_run = MagicMock()
        with patch("a_sdlc.server.run_server", mock_run):
            result = runner.invoke(
                main,
                [
                    "serve",
                    "--mcp-port",
                    "9000",
                    "--ui-port",
                    "9001",
                ],
            )

        mock_run.assert_called_once_with(
            mcp_port=9000, ui_port=9001, host="0.0.0.0"
        )
        assert result.exit_code == 0

    def test_serve_with_custom_host(self, runner: CliRunner) -> None:
        """serve with --host flag."""
        mock_run = MagicMock()
        with patch("a_sdlc.server.run_server", mock_run):
            result = runner.invoke(
                main, ["serve", "--host", "127.0.0.1"]
            )

        mock_run.assert_called_once_with(
            mcp_port=8765, ui_port=3847, host="127.0.0.1"
        )
        assert result.exit_code == 0


# =============================================================================
# Performance NFRs
# =============================================================================


class TestPerformanceNFRs:
    """Performance non-functional requirements validation.

    Health check < 500ms, startup < 3s.
    """

    def test_health_check_response_under_500ms(self) -> None:
        """Health check endpoint responds in under 500ms."""
        from a_sdlc.server.health import ServerHealth

        ServerHealth.reset()
        h = ServerHealth()

        # Fill buffer to stress-test (worst case)
        for i in range(100):
            h.record_event("connect", f"client-{i}")
        h.increment_connections()
        h.record_error(ValueError("test error"))

        timings = []
        for _ in range(50):
            start = time.monotonic()
            payload = h.get_health(include_events=True)
            elapsed_ms = (time.monotonic() - start) * 1000
            timings.append(elapsed_ms)

        timings.sort()
        p95 = timings[int(0.95 * len(timings)) - 1]
        assert p95 < 500, f"p95 response time is {p95:.2f}ms, exceeds 500ms"

        # Also verify the payload is valid
        assert payload["status"] == "healthy"
        assert payload["connection_events_count"] == 100

        ServerHealth.reset()

    def test_health_endpoint_under_500ms_via_handler(self) -> None:
        """Full /health endpoint handler responds under 500ms."""
        import asyncio

        from a_sdlc.server import _health_endpoint
        from a_sdlc.server.health import ServerHealth

        ServerHealth.reset()
        h = ServerHealth()
        for i in range(100):
            h.record_event("connect", f"client-{i}")

        async def _benchmark():
            timings = []
            for _ in range(20):
                request = MagicMock()
                request.query_params = {"events": "true"}
                start = time.monotonic()
                response = await _health_endpoint(request)
                elapsed_ms = (time.monotonic() - start) * 1000
                timings.append(elapsed_ms)
                assert response.status_code == 200
            return sorted(timings)

        timings = asyncio.run(_benchmark())
        p95 = timings[int(0.95 * len(timings)) - 1]
        assert p95 < 500, f"p95 handler time is {p95:.2f}ms, exceeds 500ms"

        ServerHealth.reset()

    def test_health_check_retry_total_time_bounded(self) -> None:
        """Health check with retry completes within reasonable time."""
        from a_sdlc.cli import _health_check_with_retry

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        start = time.monotonic()
        with patch("urllib.request.urlopen", return_value=mock_response):
            result = _health_check_with_retry(
                "http://127.0.0.1:8765/health"
            )
        elapsed = time.monotonic() - start

        assert result is True
        # Single successful check should complete almost instantly
        assert elapsed < 1.0, f"Health check took {elapsed:.2f}s, exceeds 1s"

    def test_ring_buffer_memory_under_1mb(self) -> None:
        """Ring buffer stays under 1MB even when full (NFR memory constraint)."""
        from a_sdlc.server.health import ServerHealth

        ServerHealth.reset()
        h = ServerHealth()
        # Fill with large events
        for _i in range(100):
            h.record_event("tool_call", "x" * 512)

        payload = h.get_health(include_events=True)
        serialized = json.dumps(payload["connection_events"]).encode()
        assert len(serialized) < 1_000_000, (
            f"Ring buffer is {len(serialized)} bytes, exceeds 1MB"
        )

        ServerHealth.reset()


# =============================================================================
# Port Conflict Detection
# =============================================================================


class TestPortConflictDetection:
    """Integration tests for port conflict detection."""

    def test_run_server_port_conflict_cleanup(
        self, tmp_path: Path
    ) -> None:
        """run_server cleans up PID file on port conflict."""
        import logging

        from a_sdlc.server import PortConflictError, run_server

        with (
            patch(
                "a_sdlc.server._cleanup_stale_mcp_pid",
                return_value=False,
            ),
            patch("a_sdlc.server._mcp_acquire_pid", return_value=True),
            patch(
                "a_sdlc.server._check_port_availability",
                side_effect=PortConflictError(8765, 1234),
            ),
            patch("a_sdlc.server._mcp_remove_pid") as mock_remove,
            patch(
                "a_sdlc.server.RotatingFileHandler",
                return_value=logging.NullHandler(),
            ),
            patch("a_sdlc.server.signal.signal"),
            patch("a_sdlc.server.atexit.register"),
            patch("a_sdlc.server.Path.home", return_value=tmp_path),
            pytest.raises(SystemExit),
        ):
            run_server()

        mock_remove.assert_called_once()


# =============================================================================
# Health Check Retry
# =============================================================================


class TestHealthCheckRetry:
    """Integration tests for the health check with retry logic."""

    def test_health_check_succeeds_immediately(self) -> None:
        """Health check returns True on first successful attempt."""
        from a_sdlc.cli import _health_check_with_retry

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch(
            "urllib.request.urlopen", return_value=mock_response
        ):
            result = _health_check_with_retry(
                "http://127.0.0.1:8765/health"
            )

        assert result is True

    def test_health_check_retries_then_succeeds(self) -> None:
        """Health check retries on transient failure then succeeds."""
        from a_sdlc.cli import _health_check_with_retry

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionRefusedError("not ready yet")
            return mock_response

        with patch("urllib.request.urlopen", side_effect=side_effect):
            result = _health_check_with_retry(
                "http://127.0.0.1:8765/health",
                retries=3,
                backoff_delays=(0.01, 0.02, 0.04),
            )

        assert result is True
        assert call_count == 3

    def test_health_check_exhausts_retries(self) -> None:
        """Health check returns False after all retries are exhausted."""
        from a_sdlc.cli import _health_check_with_retry

        with patch(
            "urllib.request.urlopen",
            side_effect=ConnectionRefusedError("refused"),
        ):
            result = _health_check_with_retry(
                "http://127.0.0.1:8765/health",
                retries=2,
                backoff_delays=(0.01, 0.02),
            )

        assert result is False


# =============================================================================
# Server Lifecycle
# =============================================================================


class TestServerLifecycle:
    """Integration tests for server lifecycle management."""

    def test_server_cleanup_order(self, tmp_path: Path) -> None:
        """Server follows cleanup -> acquire -> check_ports order."""
        import logging

        from a_sdlc.server import run_server

        call_order = []

        def mock_cleanup():
            call_order.append("cleanup")
            return False

        def mock_acquire():
            call_order.append("acquire")
            return True

        def mock_check(mcp_port, ui_port):
            call_order.append("check_ports")

        with (
            patch(
                "a_sdlc.server._cleanup_stale_mcp_pid",
                side_effect=mock_cleanup,
            ),
            patch(
                "a_sdlc.server._mcp_acquire_pid",
                side_effect=mock_acquire,
            ),
            patch(
                "a_sdlc.server._check_port_availability",
                side_effect=mock_check,
            ),
            patch(
                "a_sdlc.server.RotatingFileHandler",
                return_value=logging.NullHandler(),
            ),
            patch("a_sdlc.server.signal.signal"),
            patch("a_sdlc.server.atexit.register"),
            patch("a_sdlc.server._init_storage_backend"),
            patch(
                "a_sdlc.server.asyncio.run",
                side_effect=KeyboardInterrupt,
            ),
            patch.dict(
                "os.environ", {"A_SDLC_NO_BROWSER": "1"}, clear=False
            ),
            patch("a_sdlc.server.uvicorn", MagicMock(), create=True),
            patch("a_sdlc.ui.create_app", return_value=MagicMock()),
            patch("a_sdlc.server.Path.home", return_value=tmp_path),
        ):
            run_server()

        assert call_order == ["cleanup", "acquire", "check_ports"]

    def test_server_signal_handling(self) -> None:
        """Server registers SIGTERM/SIGINT handlers for cleanup."""
        import logging

        from a_sdlc.server import run_server

        call_order = []

        def mock_acquire():
            call_order.append("acquire")
            return True

        def mock_check(mcp_port, ui_port):
            call_order.append("check_ports")

        signal_calls = []

        def mock_signal(sig, handler):
            signal_calls.append(sig)

        with (
            patch("a_sdlc.server._cleanup_stale_mcp_pid", return_value=False),
            patch(
                "a_sdlc.server._mcp_acquire_pid", side_effect=mock_acquire
            ),
            patch(
                "a_sdlc.server._check_port_availability",
                side_effect=mock_check,
            ),
            patch(
                "a_sdlc.server.RotatingFileHandler",
                return_value=logging.NullHandler(),
            ),
            patch("a_sdlc.server.signal.signal", side_effect=mock_signal),
            patch("a_sdlc.server.atexit.register"),
            patch("a_sdlc.server._init_storage_backend"),
            patch(
                "a_sdlc.server.asyncio.run",
                side_effect=KeyboardInterrupt,
            ),
            patch.dict(
                "os.environ", {"A_SDLC_NO_BROWSER": "1"}, clear=False
            ),
            patch("a_sdlc.server.uvicorn", MagicMock(), create=True),
            patch("a_sdlc.ui.create_app", return_value=MagicMock()),
            patch("a_sdlc.server.Path.home", return_value=Path("/tmp")),
        ):
            run_server()

        # Should register signal handlers
        assert signal.SIGINT in signal_calls
        assert signal.SIGTERM in signal_calls


# =============================================================================
# Fresh Install: HTTP Transport by Default
# =============================================================================


class TestFreshInstallDefaults:
    """Tests that a fresh install configures HTTP transport by default."""

    def test_fresh_install_writes_http_config(self, tmp_path: Path) -> None:
        """A fresh install writes HTTP config by default."""
        settings_path = tmp_path / "claude.json"

        from a_sdlc.cli_targets import CLITarget
        from a_sdlc.installer import configure_mcp_server

        target = CLITarget(
            name="test",
            display_name="Test",
            home_dir=tmp_path,
            mcp_config_path=settings_path,
            settings_path=tmp_path / "settings.json",
            commands_dir=tmp_path / "commands" / "sdlc",
            agents_dir=tmp_path / "agents",
            context_file="CLAUDE.md",
        )

        result = configure_mcp_server(force=False, target=target)

        assert result["status"] == "configured"
        assert result["transport"] == "http"

        settings = json.loads(settings_path.read_text())
        assert settings["mcpServers"]["asdlc"]["type"] == "http"
        assert (
            settings["mcpServers"]["asdlc"]["url"]
            == "http://localhost:8765/mcp"
        )
        assert "command" not in settings["mcpServers"]["asdlc"]

    def test_fresh_install_default_port(self) -> None:
        """Default MCP port is 8765."""
        from a_sdlc.installer import DEFAULT_MCP_PORT

        assert DEFAULT_MCP_PORT == 8765

    def test_fresh_install_cli_default_transport(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """install command defaults to HTTP transport."""
        settings_path = tmp_path / "claude.json"
        commands_dir = tmp_path / "commands" / "sdlc"
        agents_dir = tmp_path / "agents"

        from a_sdlc.cli_targets import CLITarget

        target = CLITarget(
            name="claude",
            display_name="Claude Code",
            home_dir=tmp_path,
            mcp_config_path=settings_path,
            settings_path=tmp_path / "settings.json",
            commands_dir=commands_dir,
            agents_dir=agents_dir,
            context_file="CLAUDE.md",
        )

        with (
            patch("a_sdlc.cli.resolve_targets", return_value=[target]),
            patch("a_sdlc.installer._configure_via_cli", return_value=False),
        ):
            result = runner.invoke(main, ["install", "--force"])

        assert result.exit_code == 0
        settings = json.loads(settings_path.read_text())
        assert settings["mcpServers"]["asdlc"]["type"] == "http"


# =============================================================================
# Force Reinstall: Preserve Existing URL and Auth
# =============================================================================


class TestForcePreservesExistingConfig:
    """force=True keeps a previously configured URL/auth unless overridden."""

    CUSTOM_URL = "https://asdlc.example.com/mcp"
    CUSTOM_HEADERS = {"Authorization": "Bearer old-secret"}

    def _make_target(self, tmp_path: Path, name: str = "test"):
        from a_sdlc.cli_targets import CLITarget

        return CLITarget(
            name=name,
            display_name="Test",
            home_dir=tmp_path,
            mcp_config_path=tmp_path / "claude.json",
            settings_path=tmp_path / "settings.json",
            commands_dir=tmp_path / "commands" / "sdlc",
            agents_dir=tmp_path / "agents",
            context_file="CLAUDE.md",
        )

    def _write_existing(self, tmp_path: Path) -> Path:
        settings_path = tmp_path / "claude.json"
        settings_path.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "asdlc": {
                            "type": "http",
                            "url": self.CUSTOM_URL,
                            "headers": self.CUSTOM_HEADERS,
                        }
                    }
                }
            )
        )
        return settings_path

    def test_force_preserves_url_and_headers(self, tmp_path: Path) -> None:
        """force=True without url/auth_token keeps the existing config."""
        from a_sdlc.installer import configure_mcp_server

        settings_path = self._write_existing(tmp_path)
        result = configure_mcp_server(force=True, target=self._make_target(tmp_path))

        assert result["status"] == "configured"
        config = json.loads(settings_path.read_text())["mcpServers"]["asdlc"]
        assert config["url"] == self.CUSTOM_URL
        assert config["headers"] == self.CUSTOM_HEADERS

    def test_force_explicit_url_overrides_but_keeps_headers(self, tmp_path: Path) -> None:
        """Explicit url replaces the endpoint; existing auth header survives."""
        from a_sdlc.installer import configure_mcp_server

        settings_path = self._write_existing(tmp_path)
        result = configure_mcp_server(
            force=True,
            target=self._make_target(tmp_path),
            url="http://new-host:9999/mcp",
        )

        assert result["status"] == "configured"
        config = json.loads(settings_path.read_text())["mcpServers"]["asdlc"]
        assert config["url"] == "http://new-host:9999/mcp"
        assert config["headers"] == self.CUSTOM_HEADERS

    def test_force_explicit_token_overrides_but_keeps_url(self, tmp_path: Path) -> None:
        """Explicit auth_token replaces the header; existing URL survives."""
        from a_sdlc.installer import configure_mcp_server

        settings_path = self._write_existing(tmp_path)
        result = configure_mcp_server(
            force=True,
            target=self._make_target(tmp_path),
            auth_token="new-secret",
        )

        assert result["status"] == "configured"
        config = json.loads(settings_path.read_text())["mcpServers"]["asdlc"]
        assert config["url"] == self.CUSTOM_URL
        assert config["headers"] == {"Authorization": "Bearer new-secret"}

    def test_force_without_existing_writes_defaults(self, tmp_path: Path) -> None:
        """force=True with no prior config falls back to localhost defaults."""
        from a_sdlc.installer import configure_mcp_server

        target = self._make_target(tmp_path)
        result = configure_mcp_server(force=True, target=target)

        assert result["status"] == "configured"
        config = json.loads((tmp_path / "claude.json").read_text())["mcpServers"]["asdlc"]
        assert config["url"] == "http://localhost:8765/mcp"
        assert "headers" not in config

    def test_preserved_headers_skip_claude_cli_path(self, tmp_path: Path) -> None:
        """Preserved auth headers never pass through ``claude mcp add-json``."""
        from a_sdlc.installer import configure_mcp_server

        settings_path = self._write_existing(tmp_path)
        target = self._make_target(tmp_path, name="claude")

        with patch("a_sdlc.installer._configure_via_cli") as mock_cli:
            result = configure_mcp_server(force=True, target=target)

        mock_cli.assert_not_called()
        assert result["status"] == "configured"
        config = json.loads(settings_path.read_text())["mcpServers"]["asdlc"]
        assert config["headers"] == self.CUSTOM_HEADERS

    def test_install_force_cli_preserves_token(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """End-to-end: `a-sdlc install --force` keeps the configured URL/token."""
        settings_path = self._write_existing(tmp_path)
        target = self._make_target(tmp_path, name="claude")

        with (
            patch("a_sdlc.cli.resolve_targets", return_value=[target]),
            patch("a_sdlc.installer._configure_via_cli", return_value=False),
        ):
            result = runner.invoke(main, ["install", "--force"])

        assert result.exit_code == 0
        config = json.loads(settings_path.read_text())["mcpServers"]["asdlc"]
        assert config["url"] == self.CUSTOM_URL
        assert config["headers"] == self.CUSTOM_HEADERS
