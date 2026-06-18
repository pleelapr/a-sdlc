"""Tests for port conflict detection, stale PID cleanup, and health check retry."""

import os
import socket
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# PortConflictError
# ---------------------------------------------------------------------------


class TestPortConflictError:
    """Tests for the PortConflictError exception class."""

    def test_error_with_pid(self):
        from a_sdlc.server import PortConflictError

        exc = PortConflictError(8765, pid=1234)
        assert exc.port == 8765
        assert exc.pid == 1234
        assert "8765" in str(exc)
        assert "1234" in str(exc)
        assert "--mcp-port" in str(exc) or "--ui-port" in str(exc)

    def test_error_without_pid(self):
        from a_sdlc.server import PortConflictError

        exc = PortConflictError(3847)
        assert exc.port == 3847
        assert exc.pid is None
        assert "3847" in str(exc)
        assert "--mcp-port" in str(exc) or "--ui-port" in str(exc)

    def test_inherits_from_exception(self):
        from a_sdlc.server import PortConflictError

        assert issubclass(PortConflictError, Exception)


# ---------------------------------------------------------------------------
# _is_port_in_use
# ---------------------------------------------------------------------------


class TestIsPortInUse:
    """Tests for the _is_port_in_use helper."""

    def test_detects_port_in_use(self):
        from a_sdlc.server import _is_port_in_use

        # Bind a socket to a port and verify detection
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", 0))
            s.listen(1)
            port = s.getsockname()[1]
            assert _is_port_in_use(port) is True

    def test_detects_port_available(self):
        from a_sdlc.server import _is_port_in_use

        # Find an available port
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        # Port should be free after socket is closed
        assert _is_port_in_use(port) is False


# ---------------------------------------------------------------------------
# _get_port_pid
# ---------------------------------------------------------------------------


class TestGetPortPid:
    """Tests for identifying the PID using a port."""

    def test_returns_pid_when_lsof_succeeds(self):
        from a_sdlc.server import _get_port_pid

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "12345\n"

        with patch("a_sdlc.server.subprocess.run", return_value=mock_result):
            pid = _get_port_pid(8765)

        assert pid == 12345

    def test_returns_first_pid_when_multiple(self):
        from a_sdlc.server import _get_port_pid

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "12345\n67890\n"

        with patch("a_sdlc.server.subprocess.run", return_value=mock_result):
            pid = _get_port_pid(8765)

        assert pid == 12345

    def test_returns_none_when_lsof_fails(self):
        from a_sdlc.server import _get_port_pid

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""

        with patch("a_sdlc.server.subprocess.run", return_value=mock_result):
            pid = _get_port_pid(8765)

        assert pid is None

    def test_returns_none_when_lsof_not_found(self):
        from a_sdlc.server import _get_port_pid

        with patch(
            "a_sdlc.server.subprocess.run", side_effect=FileNotFoundError
        ):
            pid = _get_port_pid(8765)

        assert pid is None

    def test_returns_none_when_lsof_times_out(self):
        import subprocess

        from a_sdlc.server import _get_port_pid

        with patch(
            "a_sdlc.server.subprocess.run",
            side_effect=subprocess.TimeoutExpired("lsof", 5),
        ):
            pid = _get_port_pid(8765)

        assert pid is None

    def test_returns_none_on_invalid_output(self):
        from a_sdlc.server import _get_port_pid

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "not-a-number\n"

        with patch("a_sdlc.server.subprocess.run", return_value=mock_result):
            pid = _get_port_pid(8765)

        assert pid is None


# ---------------------------------------------------------------------------
# _cleanup_stale_mcp_pid
# ---------------------------------------------------------------------------


class TestCleanupStaleMcpPid:
    """Tests for stale PID file cleanup."""

    def test_no_pid_file_returns_false(self, tmp_path):
        from a_sdlc.server import _cleanup_stale_mcp_pid

        pid_file = tmp_path / "mcp.pid"
        with patch("a_sdlc.server._MCP_PID_FILE", pid_file):
            assert _cleanup_stale_mcp_pid() is False

    def test_corrupt_pid_file_is_cleaned(self, tmp_path):
        from a_sdlc.server import _cleanup_stale_mcp_pid

        pid_file = tmp_path / "mcp.pid"
        pid_file.write_text("not-a-number")

        with patch("a_sdlc.server._MCP_PID_FILE", pid_file):
            result = _cleanup_stale_mcp_pid()

        assert result is True
        assert not pid_file.exists()

    def test_dead_process_pid_is_cleaned(self, tmp_path):
        from a_sdlc.server import _cleanup_stale_mcp_pid

        pid_file = tmp_path / "mcp.pid"
        pid_file.write_text("999999")

        with (
            patch("a_sdlc.server._MCP_PID_FILE", pid_file),
            patch("os.kill", side_effect=OSError("No such process")),
        ):
            result = _cleanup_stale_mcp_pid()

        assert result is True
        assert not pid_file.exists()

    def test_live_process_is_not_cleaned(self, tmp_path):
        from a_sdlc.server import _cleanup_stale_mcp_pid

        # Use a PID that is *not* ours: _cleanup_stale_mcp_pid() treats its own
        # PID as stale (container PID-1 restart guard) and would unlink the
        # file before consulting os.kill, defeating the "live process" mock.
        pid_file = tmp_path / "mcp.pid"
        pid_file.write_text(str(os.getpid() + 1))

        with (
            patch("a_sdlc.server._MCP_PID_FILE", pid_file),
            patch("os.kill"),  # Doesn't raise — process alive
        ):
            result = _cleanup_stale_mcp_pid()

        assert result is False
        assert pid_file.exists()

    def test_empty_pid_file_is_cleaned(self, tmp_path):
        from a_sdlc.server import _cleanup_stale_mcp_pid

        pid_file = tmp_path / "mcp.pid"
        pid_file.write_text("")

        with patch("a_sdlc.server._MCP_PID_FILE", pid_file):
            result = _cleanup_stale_mcp_pid()

        assert result is True
        assert not pid_file.exists()


# ---------------------------------------------------------------------------
# _check_port_availability
# ---------------------------------------------------------------------------


class TestCheckPortAvailability:
    """Tests for pre-binding port availability checks."""

    def test_raises_when_mcp_port_in_use(self):
        from a_sdlc.server import PortConflictError, _check_port_availability

        with (
            patch("a_sdlc.server._is_port_in_use", side_effect=lambda p: p == 8765),
            patch("a_sdlc.server._get_port_pid", return_value=1234),
            pytest.raises(PortConflictError) as exc_info,
        ):
            _check_port_availability(8765, 3847)

        assert exc_info.value.port == 8765
        assert exc_info.value.pid == 1234

    def test_raises_when_ui_port_in_use(self):
        from a_sdlc.server import PortConflictError, _check_port_availability

        with (
            patch("a_sdlc.server._is_port_in_use", side_effect=lambda p: p == 3847),
            patch("a_sdlc.server._get_port_pid", return_value=5678),
            pytest.raises(PortConflictError) as exc_info,
        ):
            _check_port_availability(8765, 3847)

        assert exc_info.value.port == 3847
        assert exc_info.value.pid == 5678

    def test_raises_when_pid_unknown(self):
        from a_sdlc.server import PortConflictError, _check_port_availability

        with (
            patch("a_sdlc.server._is_port_in_use", return_value=True),
            patch("a_sdlc.server._get_port_pid", return_value=None),
            pytest.raises(PortConflictError) as exc_info,
        ):
            _check_port_availability(8765, 3847)

        assert exc_info.value.pid is None

    def test_no_error_when_ports_free(self):
        from a_sdlc.server import _check_port_availability

        with patch("a_sdlc.server._is_port_in_use", return_value=False):
            # Should not raise
            _check_port_availability(8765, 3847)


# ---------------------------------------------------------------------------
# run_combined_server port conflict integration
# ---------------------------------------------------------------------------


class TestRunCombinedServerPortConflict:
    """Tests that run_combined_server checks ports and handles stale PIDs."""

    def test_exits_on_port_conflict(self, tmp_path):
        """run_combined_server raises SystemExit when port is in use."""
        import logging

        from a_sdlc.server import run_combined_server

        with (
            patch("a_sdlc.server._cleanup_stale_mcp_pid", return_value=False),
            patch("a_sdlc.server._mcp_acquire_pid", return_value=True),
            patch(
                "a_sdlc.server._check_port_availability",
                side_effect=__import__("a_sdlc.server", fromlist=["PortConflictError"]).PortConflictError(8765, 1234),
            ),
            patch("a_sdlc.server._mcp_remove_pid"),
            patch("a_sdlc.server.RotatingFileHandler", return_value=logging.NullHandler()),
            patch("a_sdlc.server.signal.signal"),
            patch("a_sdlc.server.atexit.register"),
            patch("a_sdlc.server.Path.home", return_value=tmp_path),
            pytest.raises(SystemExit) as exc_info,
        ):
            run_combined_server()

        assert "8765" in str(exc_info.value)

    def test_cleans_stale_pid_before_acquiring(self, tmp_path):
        """run_combined_server calls _cleanup_stale_mcp_pid before _mcp_acquire_pid."""
        import logging

        from a_sdlc.server import run_combined_server

        call_order = []

        def mock_cleanup():
            call_order.append("cleanup")
            return True

        def mock_acquire():
            call_order.append("acquire")
            return False  # Another instance running

        with (
            patch("a_sdlc.server._cleanup_stale_mcp_pid", side_effect=mock_cleanup),
            patch("a_sdlc.server._mcp_acquire_pid", side_effect=mock_acquire),
            patch("a_sdlc.server.RotatingFileHandler", return_value=logging.NullHandler()),
            patch("a_sdlc.server.signal.signal"),
            patch("a_sdlc.server.atexit.register"),
            patch("a_sdlc.server.Path.home", return_value=tmp_path),
            pytest.raises(SystemExit),
        ):
            run_combined_server()

        assert call_order == ["cleanup", "acquire"]

    def test_port_check_happens_after_pid_acquired(self, tmp_path):
        """Port check runs only after PID lock is acquired."""
        import logging

        from a_sdlc.server import run_combined_server

        call_order = []

        def mock_acquire():
            call_order.append("acquire")
            return True

        def mock_check(mcp_port, ui_port):
            call_order.append("check_ports")
            # Ports are free — no exception

        with (
            patch("a_sdlc.server._cleanup_stale_mcp_pid", return_value=False),
            patch("a_sdlc.server._mcp_acquire_pid", side_effect=mock_acquire),
            patch("a_sdlc.server._check_port_availability", side_effect=mock_check),
            patch("a_sdlc.server._init_storage_backend"),
            patch("a_sdlc.server.RotatingFileHandler", return_value=logging.NullHandler()),
            patch("a_sdlc.server.signal.signal"),
            patch("a_sdlc.server.atexit.register"),
            patch("a_sdlc.server.Path.home", return_value=tmp_path),
            patch("a_sdlc.server.asyncio.run", side_effect=KeyboardInterrupt),
            patch.dict("os.environ", {"A_SDLC_NO_BROWSER": "1"}, clear=False),
            patch("a_sdlc.server.uvicorn", MagicMock(), create=True),
            patch("a_sdlc.ui.create_app", return_value=MagicMock()),
        ):
            run_combined_server()

        assert call_order == ["acquire", "check_ports"]

    def test_pid_removed_on_port_conflict(self, tmp_path):
        """PID file is cleaned up when port conflict is detected."""
        import logging

        from a_sdlc.server import PortConflictError, run_combined_server

        with (
            patch("a_sdlc.server._cleanup_stale_mcp_pid", return_value=False),
            patch("a_sdlc.server._mcp_acquire_pid", return_value=True),
            patch(
                "a_sdlc.server._check_port_availability",
                side_effect=PortConflictError(8765, 1234),
            ),
            patch("a_sdlc.server._mcp_remove_pid") as mock_remove,
            patch("a_sdlc.server.RotatingFileHandler", return_value=logging.NullHandler()),
            patch("a_sdlc.server.signal.signal"),
            patch("a_sdlc.server.atexit.register"),
            patch("a_sdlc.server.Path.home", return_value=tmp_path),
            pytest.raises(SystemExit),
        ):
            run_combined_server()

        mock_remove.assert_called_once()


# ---------------------------------------------------------------------------
# _daemon_start_serve port conflict
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# _health_check_with_retry
# ---------------------------------------------------------------------------


class TestHealthCheckWithRetry:
    """Tests for HTTP health check with exponential backoff."""

    def test_returns_true_on_first_success(self):
        from a_sdlc.cli import _health_check_with_retry

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = _health_check_with_retry("http://127.0.0.1:8765/health")

        assert result is True

    def test_returns_false_after_all_retries(self):
        from a_sdlc.cli import _health_check_with_retry

        with patch(
            "urllib.request.urlopen",
            side_effect=ConnectionRefusedError("refused"),
        ):
            result = _health_check_with_retry(
                "http://127.0.0.1:8765/health",
                retries=3,
                backoff_delays=(0.01, 0.02, 0.04),
            )

        assert result is False

    def test_retries_on_transient_failure_then_succeeds(self):
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

    def test_returns_http_status_on_non_200(self):
        from a_sdlc.cli import _health_check_with_retry

        mock_response = MagicMock()
        mock_response.status = 503
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = _health_check_with_retry("http://127.0.0.1:8765/health")

        assert result == "HTTP 503"

    def test_uses_exponential_backoff_delays(self):
        from a_sdlc.cli import _health_check_with_retry

        sleep_calls = []

        def mock_sleep(seconds):
            sleep_calls.append(seconds)

        with (
            patch(
                "urllib.request.urlopen",
                side_effect=ConnectionRefusedError("refused"),
            ),
            patch("time.sleep", side_effect=mock_sleep),
        ):
            _health_check_with_retry(
                "http://127.0.0.1:8765/health",
                retries=3,
                backoff_delays=(0.5, 1.0, 2.0),
            )

        # Should have 2 delays (between 3 retries)
        assert len(sleep_calls) == 2
        assert sleep_calls[0] == 0.5
        assert sleep_calls[1] == 1.0

    def test_single_retry_no_backoff(self):
        from a_sdlc.cli import _health_check_with_retry

        with patch(
            "urllib.request.urlopen",
            side_effect=ConnectionRefusedError("refused"),
        ):
            result = _health_check_with_retry(
                "http://127.0.0.1:8765/health",
                retries=1,
                backoff_delays=(0.01,),
            )

        assert result is False


