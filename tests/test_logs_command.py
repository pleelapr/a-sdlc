"""Tests for the ``a-sdlc logs`` CLI command."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from a_sdlc.cli import _format_log_line, main


@pytest.fixture
def runner() -> CliRunner:
    """Create CLI test runner."""
    return CliRunner()


def _make_json_line(
    level: str = "INFO",
    event: str = "test_event",
    ts: str = "2026-05-20T10:30:00.123+00:00",
    **extra: object,
) -> str:
    """Build a JSON log line matching the JsonFormatter output."""
    entry = {"ts": ts, "level": level, "event": event, **extra}
    return json.dumps(entry)


# ---------------------------------------------------------------------------
# _format_log_line unit tests
# ---------------------------------------------------------------------------


class TestFormatLogLine:
    """Unit tests for the _format_log_line helper."""

    def test_valid_json_info(self) -> None:
        line = _make_json_line(level="INFO", event="server_starting")
        result = _format_log_line(line, level_filter=None)
        assert result is not None
        assert "server_starting" in result
        assert "INFO" in result

    def test_valid_json_error(self) -> None:
        line = _make_json_line(level="ERROR", event="something_broke")
        result = _format_log_line(line, level_filter=None)
        assert result is not None
        assert "ERROR" in result
        assert "something_broke" in result

    def test_level_filter_passes(self) -> None:
        line = _make_json_line(level="ERROR", event="err")
        result = _format_log_line(line, level_filter="warning")
        assert result is not None

    def test_level_filter_blocks(self) -> None:
        line = _make_json_line(level="DEBUG", event="noisy")
        result = _format_log_line(line, level_filter="warning")
        assert result is None

    def test_level_filter_exact_boundary(self) -> None:
        line = _make_json_line(level="WARNING", event="warn")
        result = _format_log_line(line, level_filter="warning")
        assert result is not None

    def test_non_json_line_no_filter(self) -> None:
        result = _format_log_line("plain text line", level_filter=None)
        assert result is not None
        assert "plain text line" in result

    def test_non_json_line_with_filter(self) -> None:
        result = _format_log_line("plain text line", level_filter="info")
        assert result is None

    def test_empty_line(self) -> None:
        assert _format_log_line("", level_filter=None) is None
        assert _format_log_line("  \n", level_filter=None) is None

    def test_extra_fields_tool_and_duration(self) -> None:
        line = _make_json_line(
            event="tool_call_end", tool="get_context", duration_ms=42
        )
        result = _format_log_line(line, level_filter=None)
        assert result is not None
        assert "tool=get_context" in result
        assert "42ms" in result

    def test_extra_field_error_message(self) -> None:
        line = _make_json_line(
            level="ERROR", event="tool_call_error", error_message="not found"
        )
        result = _format_log_line(line, level_filter=None)
        assert result is not None
        assert "err=not found" in result

    def test_extra_field_status(self) -> None:
        line = _make_json_line(event="tool_call_end", status="ok")
        result = _format_log_line(line, level_filter=None)
        assert result is not None
        assert "status=ok" in result

    def test_timestamp_formatting_strips_offset(self) -> None:
        line = _make_json_line(ts="2026-05-20T10:30:00.123+00:00")
        result = _format_log_line(line, level_filter=None)
        assert result is not None
        # Should contain space-separated date/time without offset
        assert "2026-05-20 10:30:00.123" in result

    def test_timestamp_formatting_strips_z(self) -> None:
        line = _make_json_line(ts="2026-05-20T10:30:00.123Z")
        result = _format_log_line(line, level_filter=None)
        assert result is not None
        assert "2026-05-20 10:30:00.123" in result


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------


class TestLogsCommand:
    """Integration tests for ``a-sdlc logs``."""

    def test_no_log_file(self, runner: CliRunner, tmp_path: Path) -> None:
        """Missing log file produces a helpful message, not a crash."""
        fake_path = tmp_path / "nonexistent" / "server.log"
        with patch("a_sdlc.cli._SERVER_LOG_PATH", fake_path):
            result = runner.invoke(main, ["logs"])
        assert result.exit_code == 0
        assert "No log file found" in result.output
        assert "a-sdlc serve" in result.output

    def test_empty_log_file(self, runner: CliRunner, tmp_path: Path) -> None:
        log_file = tmp_path / "server.log"
        log_file.write_text("")
        with patch("a_sdlc.cli._SERVER_LOG_PATH", log_file):
            result = runner.invoke(main, ["logs"])
        assert result.exit_code == 0
        assert "Log file is empty" in result.output

    def test_shows_last_n_lines(self, runner: CliRunner, tmp_path: Path) -> None:
        log_file = tmp_path / "server.log"
        lines = [_make_json_line(event=f"event_{i}") for i in range(100)]
        log_file.write_text("\n".join(lines) + "\n")

        with patch("a_sdlc.cli._SERVER_LOG_PATH", log_file):
            result = runner.invoke(main, ["logs", "-n", "10"])
        assert result.exit_code == 0
        # Should show events 90-99 (last 10)
        assert "event_90" in result.output
        assert "event_99" in result.output
        # Should NOT show early events
        assert "event_0" not in result.output
        assert "event_89" not in result.output

    def test_default_50_lines(self, runner: CliRunner, tmp_path: Path) -> None:
        log_file = tmp_path / "server.log"
        lines = [_make_json_line(event=f"evt_{i}") for i in range(80)]
        log_file.write_text("\n".join(lines) + "\n")

        with patch("a_sdlc.cli._SERVER_LOG_PATH", log_file):
            result = runner.invoke(main, ["logs"])
        assert result.exit_code == 0
        # Should show events 30-79 (last 50)
        assert "evt_30" in result.output
        assert "evt_79" in result.output
        assert "evt_29" not in result.output

    def test_level_filter_error(self, runner: CliRunner, tmp_path: Path) -> None:
        log_file = tmp_path / "server.log"
        lines = [
            _make_json_line(level="INFO", event="info_event"),
            _make_json_line(level="WARNING", event="warn_event"),
            _make_json_line(level="ERROR", event="error_event"),
            _make_json_line(level="DEBUG", event="debug_event"),
        ]
        log_file.write_text("\n".join(lines) + "\n")

        with patch("a_sdlc.cli._SERVER_LOG_PATH", log_file):
            result = runner.invoke(main, ["logs", "--level", "error"])
        assert result.exit_code == 0
        assert "error_event" in result.output
        assert "info_event" not in result.output
        assert "warn_event" not in result.output
        assert "debug_event" not in result.output

    def test_level_filter_warning(self, runner: CliRunner, tmp_path: Path) -> None:
        log_file = tmp_path / "server.log"
        lines = [
            _make_json_line(level="INFO", event="info_evt"),
            _make_json_line(level="WARNING", event="warn_evt"),
            _make_json_line(level="ERROR", event="error_evt"),
        ]
        log_file.write_text("\n".join(lines) + "\n")

        with patch("a_sdlc.cli._SERVER_LOG_PATH", log_file):
            result = runner.invoke(main, ["logs", "--level", "warning"])
        assert result.exit_code == 0
        assert "warn_evt" in result.output
        assert "error_evt" in result.output
        assert "info_evt" not in result.output

    def test_level_filter_no_matches(self, runner: CliRunner, tmp_path: Path) -> None:
        log_file = tmp_path / "server.log"
        lines = [_make_json_line(level="INFO", event="info_only")]
        log_file.write_text("\n".join(lines) + "\n")

        with patch("a_sdlc.cli._SERVER_LOG_PATH", log_file):
            result = runner.invoke(main, ["logs", "--level", "error"])
        assert result.exit_code == 0
        assert "No log entries found at level" in result.output

    def test_mixed_json_and_plain_lines(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        log_file = tmp_path / "server.log"
        content = (
            "Some old plain text log line\n"
            + _make_json_line(level="INFO", event="json_event")
            + "\n"
            + "Another plain line\n"
        )
        log_file.write_text(content)

        with patch("a_sdlc.cli._SERVER_LOG_PATH", log_file):
            result = runner.invoke(main, ["logs"])
        assert result.exit_code == 0
        assert "json_event" in result.output
        assert "Some old plain text log line" in result.output

    def test_follow_flag_exits_on_keyboard_interrupt(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """--follow mode exits cleanly on KeyboardInterrupt."""
        log_file = tmp_path / "server.log"
        log_file.write_text(_make_json_line(event="initial") + "\n")

        # Mock time.sleep to raise KeyboardInterrupt after first call
        call_count = 0

        def mock_sleep(seconds: float) -> None:
            nonlocal call_count
            call_count += 1
            if call_count >= 1:
                raise KeyboardInterrupt()

        with (
            patch("a_sdlc.cli._SERVER_LOG_PATH", log_file),
            patch("time.sleep", mock_sleep),
        ):
            result = runner.invoke(main, ["logs", "--follow"])

        assert result.exit_code == 0
        assert "initial" in result.output
        assert "following" in result.output

    def test_follow_reads_new_lines(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """--follow mode picks up newly appended lines."""
        log_file = tmp_path / "server.log"
        log_file.write_text(_make_json_line(event="existing") + "\n")

        call_count = 0

        def mock_sleep(seconds: float) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Append a new line while "following"
                with open(log_file, "a") as f:
                    f.write(_make_json_line(event="new_entry") + "\n")
            elif call_count >= 2:
                raise KeyboardInterrupt()

        with (
            patch("a_sdlc.cli._SERVER_LOG_PATH", log_file),
            patch("time.sleep", mock_sleep),
        ):
            result = runner.invoke(main, ["logs", "--follow"])

        assert result.exit_code == 0
        assert "existing" in result.output
        assert "new_entry" in result.output

    def test_logs_help(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["logs", "--help"])
        assert result.exit_code == 0
        assert "--follow" in result.output
        assert "--level" in result.output
        assert "--lines" in result.output

    def test_invalid_level_choice(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["logs", "--level", "fatal"])
        assert result.exit_code != 0
        assert "Invalid value" in result.output or "fatal" in result.output

    def test_fewer_lines_than_requested(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """When log has fewer lines than -n, show all of them."""
        log_file = tmp_path / "server.log"
        lines = [_make_json_line(event=f"e_{i}") for i in range(5)]
        log_file.write_text("\n".join(lines) + "\n")

        with patch("a_sdlc.cli._SERVER_LOG_PATH", log_file):
            result = runner.invoke(main, ["logs", "-n", "50"])
        assert result.exit_code == 0
        for i in range(5):
            assert f"e_{i}" in result.output
