"""Tests for the daemon module (``src/a_sdlc/daemon.py``).

Covers:
- PID management: _get_pid, _is_process_running, _write_pid, _remove_pid,
  _cleanup_stale_pid, stop_daemon
- Logging: _setup_logging with RotatingFileHandler
- Signal handling: _signal_handler, _shutdown_requested flag
- Cron matching: _match_cron_field, _should_trigger with dedup
- Schedule execution: _resolve_sprint_id, _execute_scheduled_run
- Crash recovery: _recover_incomplete_runs, _mark_run_as_crashed
- Main event loop: run_daemon
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
from datetime import datetime
from pathlib import Path
from types import FrameType
from unittest.mock import MagicMock, patch

import pytest

import a_sdlc.daemon as daemon
from a_sdlc.daemon import (
    _cleanup_stale_pid,
    _execute_scheduled_run,
    _get_pid,
    _is_process_running,
    _mark_run_as_crashed,
    _match_cron_field,
    _recover_incomplete_runs,
    _remove_pid,
    _resolve_sprint_id,
    _setup_logging,
    _should_trigger,
    _signal_handler,
    _write_pid,
    run_daemon,
    stop_daemon,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_pid_and_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect PID_FILE and LOG_FILE to tmp_path for every test."""
    monkeypatch.setattr(daemon, "PID_FILE", tmp_path / "daemon.pid")
    monkeypatch.setattr(daemon, "LOG_FILE", tmp_path / "daemon.log")


@pytest.fixture
def pid_file(tmp_path: Path) -> Path:
    """Return the isolated PID file path."""
    return tmp_path / "daemon.pid"


@pytest.fixture
def log_file(tmp_path: Path) -> Path:
    """Return the isolated log file path."""
    return tmp_path / "daemon.log"


@pytest.fixture
def logger() -> logging.Logger:
    """Create a test logger that does not write to real files."""
    lg = logging.getLogger("test-daemon")
    lg.handlers.clear()
    lg.addHandler(logging.NullHandler())
    lg.setLevel(logging.DEBUG)
    return lg


# ---------------------------------------------------------------------------
# PID Management
# ---------------------------------------------------------------------------


class TestGetPid:
    """Tests for _get_pid()."""

    def test_returns_none_when_no_pid_file(self, pid_file: Path) -> None:
        assert not pid_file.exists()
        assert _get_pid() is None

    def test_returns_pid_from_file(self, pid_file: Path) -> None:
        pid_file.write_text("12345")
        assert _get_pid() == 12345

    def test_returns_none_for_invalid_content(self, pid_file: Path) -> None:
        pid_file.write_text("not-a-number")
        assert _get_pid() is None

    def test_returns_none_for_empty_file(self, pid_file: Path) -> None:
        pid_file.write_text("")
        assert _get_pid() is None

    def test_strips_whitespace(self, pid_file: Path) -> None:
        pid_file.write_text("  42  \n")
        assert _get_pid() == 42


class TestIsProcessRunning:
    """Tests for _is_process_running()."""

    def test_returns_true_when_process_alive(self) -> None:
        with patch("os.kill") as mock_kill:
            mock_kill.return_value = None  # no exception = alive
            assert _is_process_running(12345) is True
            mock_kill.assert_called_once_with(12345, 0)

    def test_returns_false_when_oserror(self) -> None:
        with patch("os.kill", side_effect=OSError("No such process")):
            assert _is_process_running(99999) is False

    def test_returns_false_when_process_lookup_error(self) -> None:
        with patch("os.kill", side_effect=ProcessLookupError):
            assert _is_process_running(99999) is False


class TestWritePid:
    """Tests for _write_pid()."""

    def test_writes_current_pid(self, pid_file: Path) -> None:
        _write_pid()
        assert pid_file.exists()
        assert int(pid_file.read_text()) == os.getpid()

    def test_creates_parent_directory(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        nested_pid = tmp_path / "deep" / "nested" / "daemon.pid"
        monkeypatch.setattr(daemon, "PID_FILE", nested_pid)
        _write_pid()
        assert nested_pid.exists()
        assert int(nested_pid.read_text()) == os.getpid()


class TestRemovePid:
    """Tests for _remove_pid()."""

    def test_removes_existing_pid_file(self, pid_file: Path) -> None:
        pid_file.write_text("12345")
        _remove_pid()
        assert not pid_file.exists()

    def test_noop_when_no_file(self, pid_file: Path) -> None:
        assert not pid_file.exists()
        _remove_pid()  # should not raise

    def test_handles_oserror_gracefully(self, pid_file: Path) -> None:
        pid_file.write_text("12345")
        with patch.object(Path, "unlink", side_effect=OSError("permission denied")):
            _remove_pid()  # should not raise


class TestCleanupStalePid:
    """Tests for _cleanup_stale_pid()."""

    def test_returns_false_when_no_pid_file(self) -> None:
        assert _cleanup_stale_pid() is False

    def test_returns_false_when_process_alive(self, pid_file: Path) -> None:
        pid_file.write_text("12345")
        with patch("a_sdlc.daemon._is_process_running", return_value=True):
            assert _cleanup_stale_pid() is False
        assert pid_file.exists()  # not removed

    def test_returns_true_and_removes_stale_pid(self, pid_file: Path) -> None:
        pid_file.write_text("12345")
        with patch("a_sdlc.daemon._is_process_running", return_value=False):
            assert _cleanup_stale_pid() is True
        assert not pid_file.exists()


class TestStopDaemon:
    """Tests for stop_daemon()."""

    def test_returns_false_when_no_pid(self, pid_file: Path) -> None:
        assert stop_daemon() is False

    def test_returns_false_when_process_not_running(self, pid_file: Path) -> None:
        pid_file.write_text("12345")
        with patch("a_sdlc.daemon._is_process_running", return_value=False):
            assert stop_daemon() is False
        # Stale PID file should be cleaned up
        assert not pid_file.exists()

    def test_sends_sigterm_and_stops_gracefully(self, pid_file: Path) -> None:
        pid_file.write_text("12345")
        call_count = 0

        def running_side_effect(pid: int) -> bool:
            nonlocal call_count
            call_count += 1
            # First 2 calls: alive (pre-check + 1 poll), then dead
            return call_count <= 2

        with (
            patch("a_sdlc.daemon._is_process_running", side_effect=running_side_effect),
            patch("os.kill") as mock_kill,
            patch("time.sleep"),
        ):
            result = stop_daemon()

        assert result is True
        mock_kill.assert_any_call(12345, signal.SIGTERM)

    @pytest.mark.skipif(sys.platform == "win32", reason="SIGKILL not available on Windows")
    def test_sends_sigkill_after_timeout(self, pid_file: Path) -> None:
        pid_file.write_text("12345")

        def always_running(pid: int) -> bool:
            return True

        kill_calls: list = []

        def mock_kill(pid: int, sig: int) -> None:
            kill_calls.append(sig)

        with (
            patch("a_sdlc.daemon._is_process_running", side_effect=always_running),
            patch("os.kill", side_effect=mock_kill),
            patch("time.sleep"),
        ):
            result = stop_daemon()

        assert result is True
        assert signal.SIGTERM in kill_calls
        assert signal.SIGKILL in kill_calls

    def test_returns_false_on_oserror(self, pid_file: Path) -> None:
        pid_file.write_text("12345")
        with (
            patch("a_sdlc.daemon._is_process_running", return_value=True),
            patch("os.kill", side_effect=OSError("permission denied")),
        ):
            result = stop_daemon()
        assert result is False
        assert not pid_file.exists()  # cleanup still happens


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


class TestSetupLogging:
    """Tests for _setup_logging()."""

    def test_returns_logger_instance(self) -> None:
        lg = _setup_logging()
        assert isinstance(lg, logging.Logger)
        assert lg.name == "a-sdlc-daemon"

    def test_creates_log_parent_directory(self, tmp_path: Path) -> None:
        nested_log = tmp_path / "deep" / "logs" / "daemon.log"
        with patch.object(daemon, "LOG_FILE", nested_log):
            _setup_logging()
        assert nested_log.parent.exists()

    def test_logger_has_rotating_handler(self) -> None:
        lg = _setup_logging()
        from logging.handlers import RotatingFileHandler

        rotating_handlers = [h for h in lg.handlers if isinstance(h, RotatingFileHandler)]
        assert len(rotating_handlers) >= 1

    def test_logger_level_is_info(self) -> None:
        lg = _setup_logging()
        assert lg.level == logging.INFO


# ---------------------------------------------------------------------------
# Signal Handling
# ---------------------------------------------------------------------------


class TestSignalHandler:
    """Tests for _signal_handler() and _shutdown_requested flag."""

    def test_sets_shutdown_requested(self) -> None:
        daemon._shutdown_requested = False
        _signal_handler(signal.SIGTERM, None)
        assert daemon._shutdown_requested is True

    def test_works_with_sigint(self) -> None:
        daemon._shutdown_requested = False
        _signal_handler(signal.SIGINT, None)
        assert daemon._shutdown_requested is True

    def test_accepts_frame_argument(self) -> None:
        daemon._shutdown_requested = False
        mock_frame = MagicMock(spec=FrameType)
        _signal_handler(signal.SIGTERM, mock_frame)
        assert daemon._shutdown_requested is True


# ---------------------------------------------------------------------------
# Cron Matching
# ---------------------------------------------------------------------------


class TestMatchCronField:
    """Tests for _match_cron_field()."""

    def test_wildcard_matches_any_value(self) -> None:
        assert _match_cron_field("*", 0) is True
        assert _match_cron_field("*", 59) is True
        assert _match_cron_field("*", 12) is True

    def test_exact_value_match(self) -> None:
        assert _match_cron_field("5", 5) is True
        assert _match_cron_field("5", 6) is False

    def test_comma_separated_list(self) -> None:
        assert _match_cron_field("1,15,30", 15) is True
        assert _match_cron_field("1,15,30", 1) is True
        assert _match_cron_field("1,15,30", 30) is True
        assert _match_cron_field("1,15,30", 7) is False

    def test_strips_whitespace(self) -> None:
        assert _match_cron_field("  *  ", 0) is True
        assert _match_cron_field(" 5 ", 5) is True
        assert _match_cron_field(" 1 , 2 , 3 ", 2) is True

    def test_invalid_field_returns_false(self) -> None:
        assert _match_cron_field("abc", 0) is False
        assert _match_cron_field("", 0) is False

    def test_zero_value(self) -> None:
        assert _match_cron_field("0", 0) is True
        assert _match_cron_field("0", 1) is False


class TestShouldTrigger:
    """Tests for _should_trigger()."""

    def test_matches_every_minute_cron(self) -> None:
        schedule = {"cron": "* * * * *"}
        now = datetime(2025, 3, 15, 10, 30)
        assert _should_trigger(schedule, now=now) is True

    def test_matches_specific_time(self) -> None:
        # Cron: 0 2 * * * = daily at 2:00 AM
        schedule = {"cron": "0 2 * * *"}
        at_2am = datetime(2025, 3, 15, 2, 0)
        assert _should_trigger(schedule, now=at_2am) is True

        not_2am = datetime(2025, 3, 15, 3, 0)
        assert _should_trigger(schedule, now=not_2am) is False

    def test_does_not_match_wrong_minute(self) -> None:
        schedule = {"cron": "30 * * * *"}
        at_15 = datetime(2025, 3, 15, 10, 15)
        assert _should_trigger(schedule, now=at_15) is False

    def test_day_of_week_conversion(self) -> None:
        # Python weekday: Monday=0, Sunday=6
        # Cron weekday: Sunday=0, Monday=1, Saturday=6
        # "* * * * 1" = every Monday
        schedule = {"cron": "* * * * 1"}
        # March 17, 2025 is a Monday (Python weekday=0, cron=(0+1)%7=1)
        monday = datetime(2025, 3, 17, 10, 0)
        assert _should_trigger(schedule, now=monday) is True

        # March 18, 2025 is a Tuesday (Python weekday=1, cron=(1+1)%7=2)
        tuesday = datetime(2025, 3, 18, 10, 0)
        assert _should_trigger(schedule, now=tuesday) is False

    def test_sunday_cron_conversion(self) -> None:
        # "* * * * 0" = every Sunday
        schedule = {"cron": "* * * * 0"}
        # March 16, 2025 is a Sunday (Python weekday=6, cron=(6+1)%7=0)
        sunday = datetime(2025, 3, 16, 10, 0)
        assert _should_trigger(schedule, now=sunday) is True

    def test_returns_false_for_missing_cron(self) -> None:
        assert _should_trigger({}, now=datetime(2025, 1, 1, 0, 0)) is False
        assert _should_trigger({"cron": None}, now=datetime(2025, 1, 1, 0, 0)) is False
        assert _should_trigger({"cron": ""}, now=datetime(2025, 1, 1, 0, 0)) is False

    def test_returns_false_for_invalid_cron_format(self) -> None:
        # Too few fields
        assert _should_trigger({"cron": "0 2 *"}, now=datetime(2025, 1, 1, 0, 0)) is False
        # Too many fields
        assert _should_trigger({"cron": "0 2 * * * *"}, now=datetime(2025, 1, 1, 0, 0)) is False

    def test_returns_false_for_non_string_cron(self) -> None:
        assert _should_trigger({"cron": 123}, now=datetime(2025, 1, 1, 0, 0)) is False

    def test_specific_day_of_month(self) -> None:
        schedule = {"cron": "0 0 15 * *"}
        on_15th = datetime(2025, 3, 15, 0, 0)
        assert _should_trigger(schedule, now=on_15th) is True

        on_14th = datetime(2025, 3, 14, 0, 0)
        assert _should_trigger(schedule, now=on_14th) is False

    def test_specific_month(self) -> None:
        schedule = {"cron": "0 0 * 12 *"}
        in_december = datetime(2025, 12, 1, 0, 0)
        assert _should_trigger(schedule, now=in_december) is True

        in_january = datetime(2025, 1, 1, 0, 0)
        assert _should_trigger(schedule, now=in_january) is False

    def test_uses_current_time_when_now_omitted(self) -> None:
        schedule = {"cron": "* * * * *"}
        # Wildcard should match any current time
        assert _should_trigger(schedule) is True


# ---------------------------------------------------------------------------
# Sprint ID Resolution
# ---------------------------------------------------------------------------


class TestResolveSprintId:
    """Tests for _resolve_sprint_id()."""

    def test_returns_none_for_empty_value(self, logger: logging.Logger) -> None:
        assert _resolve_sprint_id(None, logger) is None
        assert _resolve_sprint_id("", logger) is None

    def test_returns_literal_value_for_non_auto(self, logger: logging.Logger) -> None:
        assert _resolve_sprint_id("PROJ-S0001", logger) == "PROJ-S0001"

    def test_auto_resolves_active_sprint(self, logger: logging.Logger) -> None:
        mock_storage = MagicMock()
        mock_storage.list_sprints.return_value = [{"id": "PROJ-S0002"}]

        with patch("a_sdlc.storage.get_storage", return_value=mock_storage):
            result = _resolve_sprint_id("auto", logger)

        assert result == "PROJ-S0002"
        mock_storage.list_sprints.assert_called_once_with(status="active")

    def test_auto_returns_none_when_no_active_sprint(self, logger: logging.Logger) -> None:
        mock_storage = MagicMock()
        mock_storage.list_sprints.return_value = []

        with patch("a_sdlc.storage.get_storage", return_value=mock_storage):
            result = _resolve_sprint_id("auto", logger)

        assert result is None

    def test_auto_returns_none_on_exception(self, logger: logging.Logger) -> None:
        with patch("a_sdlc.storage.get_storage", side_effect=Exception("DB error")):
            _resolve_sprint_id("auto", logger)


# ---------------------------------------------------------------------------
# Schedule Execution
# ---------------------------------------------------------------------------


class TestExecuteScheduledRun:
    """Tests for _execute_scheduled_run()."""

    def test_sprint_run_spawns_subprocess(
        self, logger: logging.Logger, tmp_path: Path
    ) -> None:
        schedule = {"type": "sprint_run", "sprint_id": "PROJ-S0001"}
        config = {"daemon": {"max_turns": 100, "supervised": False}}

        with (
            patch("a_sdlc.daemon._resolve_sprint_id", return_value="PROJ-S0001"),
            patch("a_sdlc.executor._write_run") as mock_write_run,
            patch("subprocess.Popen") as mock_popen,
            patch("builtins.open", MagicMock()),
            patch("a_sdlc.daemon.Path.home", return_value=tmp_path),
        ):
            mock_proc = MagicMock()
            mock_proc.pid = 99999
            mock_popen.return_value = mock_proc

            _execute_scheduled_run(schedule, config, logger)

        mock_write_run.assert_called_once()
        mock_popen.assert_called_once()
        # Verify command includes expected arguments
        cmd = mock_popen.call_args[0][0]
        assert "--mode" in cmd
        assert "sprint" in cmd
        assert "--sprint-id" in cmd
        assert "PROJ-S0001" in cmd
        assert "--max-turns" in cmd
        assert "100" in cmd

    def test_sprint_run_with_supervised_flag(
        self, logger: logging.Logger, tmp_path: Path
    ) -> None:
        schedule = {"type": "sprint_run", "sprint_id": "PROJ-S0001"}
        config = {"daemon": {"max_turns": 50, "supervised": True}}

        with (
            patch("a_sdlc.daemon._resolve_sprint_id", return_value="PROJ-S0001"),
            patch("a_sdlc.executor._write_run"),
            patch("subprocess.Popen") as mock_popen,
            patch("builtins.open", MagicMock()),
            patch("a_sdlc.daemon.Path.home", return_value=tmp_path),
        ):
            mock_proc = MagicMock()
            mock_proc.pid = 99999
            mock_popen.return_value = mock_proc

            _execute_scheduled_run(schedule, config, logger)

        cmd = mock_popen.call_args[0][0]
        assert "--supervised" in cmd

    def test_sprint_run_skips_when_no_sprint_id(self, logger: logging.Logger) -> None:
        schedule = {"type": "sprint_run", "sprint_id": None}
        config = {"daemon": {}}

        with (
            patch("a_sdlc.daemon._resolve_sprint_id", return_value=None),
            patch("subprocess.Popen") as mock_popen,
        ):
            _execute_scheduled_run(schedule, config, logger)

        mock_popen.assert_not_called()

    def test_sprint_run_handles_popen_failure(
        self, logger: logging.Logger, tmp_path: Path
    ) -> None:
        schedule = {"type": "sprint_run", "sprint_id": "PROJ-S0001"}
        config = {"daemon": {}}

        with (
            patch("a_sdlc.daemon._resolve_sprint_id", return_value="PROJ-S0001"),
            patch("a_sdlc.executor._write_run"),
            patch("subprocess.Popen", side_effect=OSError("spawn failed")),
            patch("builtins.open", MagicMock()),
            patch("a_sdlc.daemon.Path.home", return_value=tmp_path),
        ):
            # Should not raise, just log error
            _execute_scheduled_run(schedule, config, logger)

    def test_sync_calls_sync_sprint(self, logger: logging.Logger) -> None:
        schedule = {"type": "sync", "sprint_id": "PROJ-S0001"}
        config = {"daemon": {}}

        with (
            patch("a_sdlc.daemon._resolve_sprint_id", return_value="PROJ-S0001"),
            patch("a_sdlc.server.sync_sprint") as mock_sync,
        ):
            mock_sync.return_value = {"status": "ok"}
            _execute_scheduled_run(schedule, config, logger)

        mock_sync.assert_called_once_with("PROJ-S0001")

    def test_sync_defaults_sprint_id_to_auto(self, logger: logging.Logger) -> None:
        schedule = {"type": "sync"}
        config = {"daemon": {}}

        with (
            patch("a_sdlc.daemon._resolve_sprint_id", return_value="PROJ-S0002") as mock_resolve,
            patch("a_sdlc.server.sync_sprint"),
        ):
            _execute_scheduled_run(schedule, config, logger)

        mock_resolve.assert_called_once_with("auto", logger)

    def test_sync_skips_when_no_sprint_id(self, logger: logging.Logger) -> None:
        schedule = {"type": "sync", "sprint_id": "auto"}
        config = {"daemon": {}}

        with (
            patch("a_sdlc.daemon._resolve_sprint_id", return_value=None),
            patch("a_sdlc.server.sync_sprint") as mock_sync,
        ):
            _execute_scheduled_run(schedule, config, logger)

        mock_sync.assert_not_called()

    def test_sync_handles_exception(self, logger: logging.Logger) -> None:
        schedule = {"type": "sync", "sprint_id": "PROJ-S0001"}
        config = {"daemon": {}}

        with (
            patch("a_sdlc.daemon._resolve_sprint_id", return_value="PROJ-S0001"),
            patch("a_sdlc.server.sync_sprint", side_effect=Exception("sync error")),
        ):
            # Should not raise, just log error
            _execute_scheduled_run(schedule, config, logger)

    def test_unknown_schedule_type_logs_warning(self, logger: logging.Logger) -> None:
        schedule = {"type": "unknown_type"}
        config = {"daemon": {}}

        # Should not raise
        _execute_scheduled_run(schedule, config, logger)

    def test_sprint_run_uses_default_max_turns(
        self, logger: logging.Logger, tmp_path: Path
    ) -> None:
        schedule = {"type": "sprint_run", "sprint_id": "PROJ-S0001"}
        config = {"daemon": {}}  # no max_turns specified

        with (
            patch("a_sdlc.daemon._resolve_sprint_id", return_value="PROJ-S0001"),
            patch("a_sdlc.executor._write_run"),
            patch("subprocess.Popen") as mock_popen,
            patch("builtins.open", MagicMock()),
            patch("a_sdlc.daemon.Path.home", return_value=tmp_path),
        ):
            mock_proc = MagicMock()
            mock_proc.pid = 99999
            mock_popen.return_value = mock_proc

            _execute_scheduled_run(schedule, config, logger)

        cmd = mock_popen.call_args[0][0]
        # Default max_turns is 200
        max_turns_idx = cmd.index("--max-turns")
        assert cmd[max_turns_idx + 1] == "200"


# ---------------------------------------------------------------------------
# Crash Recovery
# ---------------------------------------------------------------------------


class TestRecoverIncompleteRuns:
    """Tests for _recover_incomplete_runs()."""

    def test_returns_zero_when_runs_dir_missing(self, logger: logging.Logger) -> None:
        with patch("a_sdlc.executor._RUNS_DIR", Path("/nonexistent/runs")):
            result = _recover_incomplete_runs(logger)
        assert result == 0

    def test_returns_zero_when_no_run_files(
        self, logger: logging.Logger, tmp_path: Path
    ) -> None:
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()

        with patch("a_sdlc.executor._RUNS_DIR", runs_dir):
            result = _recover_incomplete_runs(logger)
        assert result == 0

    def test_skips_completed_runs(
        self, logger: logging.Logger, tmp_path: Path
    ) -> None:
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()
        run_file = runs_dir / "R-001.json"
        run_file.write_text(json.dumps({"status": "completed"}))

        with (
            patch("a_sdlc.executor._RUNS_DIR", runs_dir),
            patch("a_sdlc.daemon._mark_run_as_crashed") as mock_mark,
        ):
            result = _recover_incomplete_runs(logger)

        assert result == 0
        mock_mark.assert_not_called()

    def test_marks_crashed_run_with_dead_pid(
        self, logger: logging.Logger, tmp_path: Path
    ) -> None:
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()
        run_file = runs_dir / "R-001.json"
        run_file.write_text(json.dumps({"status": "running", "pid": 99999}))

        with (
            patch("a_sdlc.executor._RUNS_DIR", runs_dir),
            patch("a_sdlc.daemon._is_process_running", return_value=False),
            patch("a_sdlc.daemon._mark_run_as_crashed") as mock_mark,
        ):
            result = _recover_incomplete_runs(logger)

        assert result == 1
        mock_mark.assert_called_once_with("R-001", "running", 99999, logger)

    def test_leaves_alive_process_alone(
        self, logger: logging.Logger, tmp_path: Path
    ) -> None:
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()
        run_file = runs_dir / "R-001.json"
        run_file.write_text(json.dumps({"status": "running", "pid": 12345}))

        with (
            patch("a_sdlc.executor._RUNS_DIR", runs_dir),
            patch("a_sdlc.daemon._is_process_running", return_value=True),
            patch("a_sdlc.daemon._mark_run_as_crashed") as mock_mark,
        ):
            result = _recover_incomplete_runs(logger)

        assert result == 0
        mock_mark.assert_not_called()

    def test_marks_crashed_run_without_pid(
        self, logger: logging.Logger, tmp_path: Path
    ) -> None:
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()
        run_file = runs_dir / "R-001.json"
        # No pid field
        run_file.write_text(json.dumps({"status": "running"}))

        with (
            patch("a_sdlc.executor._RUNS_DIR", runs_dir),
            patch("a_sdlc.daemon._mark_run_as_crashed") as mock_mark,
        ):
            result = _recover_incomplete_runs(logger)

        assert result == 1
        mock_mark.assert_called_once_with("R-001", "running", None, logger)

    def test_marks_crashed_run_with_invalid_pid(
        self, logger: logging.Logger, tmp_path: Path
    ) -> None:
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()
        run_file = runs_dir / "R-001.json"
        run_file.write_text(json.dumps({"status": "awaiting_confirmation", "pid": "not-a-number"}))

        with (
            patch("a_sdlc.executor._RUNS_DIR", runs_dir),
            patch("a_sdlc.daemon._mark_run_as_crashed") as mock_mark,
        ):
            result = _recover_incomplete_runs(logger)

        assert result == 1
        mock_mark.assert_called_once_with("R-001", "awaiting_confirmation", None, logger)

    def test_handles_multiple_runs(
        self, logger: logging.Logger, tmp_path: Path
    ) -> None:
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()
        # Running with dead PID
        (runs_dir / "R-001.json").write_text(json.dumps({"status": "running", "pid": 11111}))
        # Completed -- should be skipped
        (runs_dir / "R-002.json").write_text(json.dumps({"status": "completed"}))
        # Awaiting confirmation with dead PID
        (runs_dir / "R-003.json").write_text(
            json.dumps({"status": "awaiting_confirmation", "pid": 22222})
        )

        with (
            patch("a_sdlc.executor._RUNS_DIR", runs_dir),
            patch("a_sdlc.daemon._is_process_running", return_value=False),
            patch("a_sdlc.daemon._mark_run_as_crashed") as mock_mark,
        ):
            result = _recover_incomplete_runs(logger)

        assert result == 2
        assert mock_mark.call_count == 2

    def test_handles_corrupted_run_file(
        self, logger: logging.Logger, tmp_path: Path
    ) -> None:
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()
        # Corrupted JSON
        (runs_dir / "R-bad.json").write_text("not-json{{{")

        with (
            patch("a_sdlc.executor._RUNS_DIR", runs_dir),
        ):
            # Should not raise
            result = _recover_incomplete_runs(logger)

        assert result == 0


class TestMarkRunAsCrashed:
    """Tests for _mark_run_as_crashed()."""

    def test_updates_run_with_crash_metadata_with_pid(
        self, logger: logging.Logger
    ) -> None:
        with patch("a_sdlc.executor._update_run") as mock_update:
            _mark_run_as_crashed("R-001", "running", 12345, logger)

        mock_update.assert_called_once()
        kwargs = mock_update.call_args[1]
        assert kwargs["status"] == "failed"
        assert kwargs["crash_detected"] is True
        assert "12345" in kwargs["crash_reason"]
        assert kwargs["original_status"] == "running"

    def test_updates_run_with_crash_metadata_without_pid(
        self, logger: logging.Logger
    ) -> None:
        with patch("a_sdlc.executor._update_run") as mock_update:
            _mark_run_as_crashed("R-001", "awaiting_confirmation", None, logger)

        kwargs = mock_update.call_args[1]
        assert kwargs["status"] == "failed"
        assert "not recorded" in kwargs["crash_reason"]
        assert kwargs["original_status"] == "awaiting_confirmation"


# ---------------------------------------------------------------------------
# Main Daemon Event Loop
# ---------------------------------------------------------------------------


class TestRunDaemon:
    """Tests for run_daemon()."""

    def test_starts_and_stops_on_shutdown_flag(self) -> None:
        """Daemon loop should exit after _shutdown_requested is set."""
        iteration = 0

        def fake_sleep(seconds: float) -> None:
            nonlocal iteration
            iteration += 1
            if iteration >= 1:
                daemon._shutdown_requested = True

        config = {"daemon": {"schedules": []}}

        with (
            patch("a_sdlc.daemon._setup_logging") as mock_logging,
            patch("a_sdlc.daemon._write_pid"),
            patch("a_sdlc.daemon._remove_pid"),
            patch("a_sdlc.daemon._recover_incomplete_runs", return_value=0),
            patch("time.sleep", side_effect=fake_sleep),
            patch("signal.signal"),
            patch("atexit.register"),
        ):
            mock_logger = MagicMock()
            mock_logging.return_value = mock_logger

            run_daemon(config)

        # Should have exited after flag was set
        assert daemon._shutdown_requested is True

    def test_registers_signal_handlers(self) -> None:
        config = {"daemon": {"schedules": []}}

        def _stop(_: float) -> None:
            daemon._shutdown_requested = True

        with (
            patch("a_sdlc.daemon._setup_logging", return_value=MagicMock()),
            patch("a_sdlc.daemon._write_pid"),
            patch("a_sdlc.daemon._remove_pid"),
            patch("a_sdlc.daemon._recover_incomplete_runs", return_value=0),
            patch("time.sleep", side_effect=_stop),
            patch("signal.signal") as mock_signal,
            patch("atexit.register"),
        ):
            run_daemon(config)

        # Should register SIGTERM and SIGINT handlers
        signal_calls = [call[0][0] for call in mock_signal.call_args_list]
        assert signal.SIGTERM in signal_calls
        assert signal.SIGINT in signal_calls

    def test_writes_pid_and_registers_atexit(self) -> None:
        config = {"daemon": {"schedules": []}}

        def _stop(_: float) -> None:
            daemon._shutdown_requested = True

        with (
            patch("a_sdlc.daemon._setup_logging", return_value=MagicMock()),
            patch("a_sdlc.daemon._write_pid") as mock_write,
            patch("a_sdlc.daemon._remove_pid"),
            patch("a_sdlc.daemon._recover_incomplete_runs", return_value=0),
            patch("time.sleep", side_effect=_stop),
            patch("signal.signal"),
            patch("atexit.register") as mock_atexit,
        ):
            run_daemon(config)

        mock_write.assert_called_once()
        mock_atexit.assert_called_once()

    def test_triggers_schedule_and_executes(self) -> None:
        """Daemon should execute a schedule when _should_trigger returns True."""
        iteration = 0

        def fake_sleep(seconds: float) -> None:
            nonlocal iteration
            iteration += 1
            daemon._shutdown_requested = True

        config = {
            "daemon": {
                "schedules": [{"cron": "* * * * *", "type": "sprint_run", "sprint_id": "S1"}],
            }
        }

        with (
            patch("a_sdlc.daemon._setup_logging", return_value=MagicMock()),
            patch("a_sdlc.daemon._write_pid"),
            patch("a_sdlc.daemon._remove_pid"),
            patch("a_sdlc.daemon._recover_incomplete_runs", return_value=0),
            patch("time.sleep", side_effect=fake_sleep),
            patch("signal.signal"),
            patch("atexit.register"),
            patch("a_sdlc.daemon._should_trigger", return_value=True),
            patch("a_sdlc.daemon._execute_scheduled_run") as mock_exec,
        ):
            run_daemon(config)

        mock_exec.assert_called_once()

    def test_does_not_double_trigger_same_minute(self) -> None:
        """Daemon should not trigger the same schedule twice in the same minute."""
        iteration = 0

        def fake_sleep(seconds: float) -> None:
            nonlocal iteration
            iteration += 1
            if iteration >= 3:
                daemon._shutdown_requested = True

        config = {
            "daemon": {
                "schedules": [{"cron": "0 * * * *", "type": "sprint_run", "sprint_id": "S1"}],
            }
        }

        with (
            patch("a_sdlc.daemon._setup_logging", return_value=MagicMock()),
            patch("a_sdlc.daemon._write_pid"),
            patch("a_sdlc.daemon._remove_pid"),
            patch("a_sdlc.daemon._recover_incomplete_runs", return_value=0),
            patch("time.sleep", side_effect=fake_sleep),
            patch("signal.signal"),
            patch("atexit.register"),
            patch("a_sdlc.daemon._should_trigger", return_value=True),
            patch("a_sdlc.daemon._execute_scheduled_run") as mock_exec,
        ):
            run_daemon(config)

        # Should only trigger once per unique minute (same minute across iterations)
        assert mock_exec.call_count == 1

    def test_handles_schedule_execution_exception(self) -> None:
        """Daemon should not crash when _execute_scheduled_run raises."""
        iteration = 0

        def fake_sleep(seconds: float) -> None:
            nonlocal iteration
            iteration += 1
            daemon._shutdown_requested = True

        config = {
            "daemon": {
                "schedules": [{"cron": "* * * * *", "type": "sprint_run", "sprint_id": "S1"}],
            }
        }

        with (
            patch("a_sdlc.daemon._setup_logging", return_value=MagicMock()),
            patch("a_sdlc.daemon._write_pid"),
            patch("a_sdlc.daemon._remove_pid"),
            patch("a_sdlc.daemon._recover_incomplete_runs", return_value=0),
            patch("time.sleep", side_effect=fake_sleep),
            patch("signal.signal"),
            patch("atexit.register"),
            patch("a_sdlc.daemon._should_trigger", return_value=True),
            patch("a_sdlc.daemon._execute_scheduled_run", side_effect=RuntimeError("boom")),
        ):
            # Should not raise
            run_daemon(config)

    def test_runs_crash_recovery_on_startup(self) -> None:
        config = {"daemon": {"schedules": []}}

        def _stop(_: float) -> None:
            daemon._shutdown_requested = True

        with (
            patch("a_sdlc.daemon._setup_logging", return_value=MagicMock()),
            patch("a_sdlc.daemon._write_pid"),
            patch("a_sdlc.daemon._remove_pid"),
            patch("a_sdlc.daemon._recover_incomplete_runs", return_value=2) as mock_recover,
            patch("time.sleep", side_effect=_stop),
            patch("signal.signal"),
            patch("atexit.register"),
        ):
            run_daemon(config)

        mock_recover.assert_called_once()

    def test_empty_config_uses_defaults(self) -> None:
        def _stop(_: float) -> None:
            daemon._shutdown_requested = True

        with (
            patch("a_sdlc.daemon._setup_logging", return_value=MagicMock()),
            patch("a_sdlc.daemon._write_pid"),
            patch("a_sdlc.daemon._remove_pid"),
            patch("a_sdlc.daemon._recover_incomplete_runs", return_value=0),
            patch("time.sleep", side_effect=_stop),
            patch("signal.signal"),
            patch("atexit.register"),
        ):
            # Empty config should not raise
            run_daemon({})
