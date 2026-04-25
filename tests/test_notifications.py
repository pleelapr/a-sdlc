"""Tests for the notification hook system.

Covers:
- run_notification_hooks() dispatch and error handling
- _run_file_hook() path templating, expansion, directory creation, writing
- _run_webhook_hook() event filtering, payload construction, HTTP error handling
- _run_webhook_hook() graceful skip when httpx is not installed
- format_run_summary() output format
- Integration with executor._main() notification call
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from a_sdlc.notifications import (
    _run_file_hook,
    _run_webhook_hook,
    format_run_summary,
    run_notification_hooks,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_outcome() -> dict[str, Any]:
    """A typical run outcome dict."""
    return {
        "status": "completed",
        "summary": "All tasks done",
        "entity_type": "sprint",
        "entity_id": "PROJ-S0001",
        "completed": 3,
        "failed": 0,
        "skipped": 1,
    }


@pytest.fixture
def failed_outcome() -> dict[str, Any]:
    """A failed run outcome dict."""
    return {
        "status": "failed",
        "summary": "Some tasks failed",
        "entity_type": "sprint",
        "entity_id": "PROJ-S0001",
        "completed": 1,
        "failed": 2,
        "skipped": 0,
    }


@pytest.fixture
def log() -> MagicMock:
    """A mock logger."""
    return MagicMock()


# ---------------------------------------------------------------------------
# run_notification_hooks
# ---------------------------------------------------------------------------


class TestRunNotificationHooks:
    def test_no_notifications_returns_early(self, sample_outcome, log):
        """No hooks configured should return without action."""
        config: dict[str, Any] = {"notifications": []}
        run_notification_hooks("R-001", sample_outcome, config, hook_logger=log)
        log.info.assert_not_called()

    def test_missing_notifications_key(self, sample_outcome, log):
        """Config without notifications key should not raise."""
        config: dict[str, Any] = {}
        run_notification_hooks("R-001", sample_outcome, config, hook_logger=log)
        log.info.assert_not_called()

    def test_dispatches_file_hook(self, sample_outcome, log, tmp_path):
        """File hook type dispatches to _run_file_hook."""
        out_file = tmp_path / "summary.md"
        config: dict[str, Any] = {
            "notifications": [
                {"type": "file", "path": str(out_file)},
            ]
        }

        run_notification_hooks("R-001", sample_outcome, config, hook_logger=log)

        assert out_file.exists()
        content = out_file.read_text()
        assert "R-001" in content

    def test_dispatches_webhook_hook(self, sample_outcome, log):
        """Webhook hook type dispatches to _run_webhook_hook."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        config: dict[str, Any] = {
            "notifications": [
                {
                    "type": "webhook",
                    "url": "https://example.com/hook",
                    "events": ["run_completed"],
                },
            ]
        }

        with patch("a_sdlc.notifications.httpx") as mock_httpx:
            mock_httpx.post.return_value = mock_response
            mock_httpx.HTTPError = Exception
            run_notification_hooks("R-001", sample_outcome, config, hook_logger=log)

        mock_httpx.post.assert_called_once()

    def test_unknown_type_logs_warning(self, sample_outcome, log):
        """Unknown hook type logs a warning."""
        config: dict[str, Any] = {
            "notifications": [
                {"type": "smoke_signal"},
            ]
        }

        run_notification_hooks("R-001", sample_outcome, config, hook_logger=log)
        log.warning.assert_called_once()
        assert "Unknown" in log.warning.call_args[0][0]

    def test_hook_exception_does_not_propagate(self, sample_outcome, log, tmp_path):
        """A failing hook should not prevent subsequent hooks from running."""
        good_file = tmp_path / "good.md"

        config: dict[str, Any] = {
            "notifications": [
                {"type": "webhook", "url": "https://example.com/hook"},
                {"type": "file", "path": str(good_file)},
            ]
        }

        with patch("a_sdlc.notifications.httpx") as mock_httpx:
            mock_httpx.post.side_effect = Exception("network error")
            mock_httpx.HTTPError = Exception
            run_notification_hooks("R-001", sample_outcome, config, hook_logger=log)

        # The file hook should still have run
        assert good_file.exists()

    def test_multiple_hooks_all_execute(self, sample_outcome, log, tmp_path):
        """Multiple file hooks should all be executed."""
        f1 = tmp_path / "a.md"
        f2 = tmp_path / "b.md"

        config: dict[str, Any] = {
            "notifications": [
                {"type": "file", "path": str(f1)},
                {"type": "file", "path": str(f2)},
            ]
        }

        run_notification_hooks("R-001", sample_outcome, config, hook_logger=log)

        assert f1.exists()
        assert f2.exists()


# ---------------------------------------------------------------------------
# _run_file_hook
# ---------------------------------------------------------------------------


class TestRunFileHook:
    def test_writes_summary_to_path(self, sample_outcome, log, tmp_path):
        """File hook writes markdown summary to the configured path."""
        out_file = tmp_path / "summary.md"
        hook = {"path": str(out_file)}

        _run_file_hook("R-001", sample_outcome, hook, log)

        assert out_file.exists()
        content = out_file.read_text()
        assert "# Execution Run Summary" in content
        assert "R-001" in content

    def test_replaces_run_id_placeholder(self, sample_outcome, log, tmp_path):
        """The {run_id} placeholder in path is replaced with the actual ID."""
        hook = {"path": str(tmp_path / "{run_id}.md")}

        _run_file_hook("R-XYZ", sample_outcome, hook, log)

        expected = tmp_path / "R-XYZ.md"
        assert expected.exists()

    def test_creates_parent_directories(self, sample_outcome, log, tmp_path):
        """Parent directories are created if they do not exist."""
        hook = {"path": str(tmp_path / "deep" / "nested" / "dir" / "out.md")}

        _run_file_hook("R-001", sample_outcome, hook, log)

        assert (tmp_path / "deep" / "nested" / "dir" / "out.md").exists()

    def test_expands_tilde(self, sample_outcome, log, tmp_path):
        """Tilde in path is expanded to home directory."""
        hook = {"path": "~/test-notification-{run_id}.md"}

        with (
            patch.object(Path, "expanduser", return_value=tmp_path / "expanded.md"),
            patch.object(Path, "write_text"),
        ):
            _run_file_hook("R-001", sample_outcome, hook, log)

    def test_missing_path_logs_warning(self, sample_outcome, log):
        """Missing 'path' field logs a warning and returns."""
        hook: dict[str, Any] = {"type": "file"}

        _run_file_hook("R-001", sample_outcome, hook, log)

        log.warning.assert_called_once()
        assert "path" in log.warning.call_args[0][0].lower()

    def test_empty_path_logs_warning(self, sample_outcome, log):
        """Empty string 'path' field logs a warning."""
        hook: dict[str, Any] = {"type": "file", "path": ""}

        _run_file_hook("R-001", sample_outcome, hook, log)

        log.warning.assert_called_once()


# ---------------------------------------------------------------------------
# _run_webhook_hook
# ---------------------------------------------------------------------------


class TestRunWebhookHook:
    def test_sends_post_request(self, sample_outcome, log):
        """Webhook sends a POST to the configured URL."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        hook = {
            "url": "https://example.com/hook",
            "events": ["run_completed"],
        }

        with patch("a_sdlc.notifications.httpx") as mock_httpx:
            mock_httpx.post.return_value = mock_response
            mock_httpx.HTTPError = Exception
            _run_webhook_hook("R-001", sample_outcome, hook, log)

        call_args = mock_httpx.post.call_args
        assert call_args[0][0] == "https://example.com/hook"
        payload = call_args[1]["json"]
        assert payload["run_id"] == "R-001"
        assert payload["event"] == "run_completed"
        assert payload["status"] == "completed"
        assert payload["summary"] == "All tasks done"
        assert payload["completed_count"] == 3
        assert payload["failed_count"] == 0

    def test_filters_by_event_type(self, sample_outcome, log):
        """Webhook skips when the event is not in the configured events list."""
        hook = {
            "url": "https://example.com/hook",
            "events": ["run_failed"],  # Only want failures
        }

        with patch("a_sdlc.notifications.httpx") as mock_httpx:
            mock_httpx.HTTPError = Exception
            _run_webhook_hook("R-001", sample_outcome, hook, log)

        # Should not have been called since outcome is "completed"
        mock_httpx.post.assert_not_called()

    def test_run_failed_event_matches(self, failed_outcome, log):
        """Webhook fires for run_failed when outcome status is not completed."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        hook = {
            "url": "https://example.com/hook",
            "events": ["run_failed"],
        }

        with patch("a_sdlc.notifications.httpx") as mock_httpx:
            mock_httpx.post.return_value = mock_response
            mock_httpx.HTTPError = Exception
            _run_webhook_hook("R-001", failed_outcome, hook, log)

        mock_httpx.post.assert_called_once()
        payload = mock_httpx.post.call_args[1]["json"]
        assert payload["event"] == "run_failed"

    def test_default_events_both(self, sample_outcome, log):
        """Default events list includes both run_completed and run_failed."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        hook = {"url": "https://example.com/hook"}  # No events specified

        with patch("a_sdlc.notifications.httpx") as mock_httpx:
            mock_httpx.post.return_value = mock_response
            mock_httpx.HTTPError = Exception
            _run_webhook_hook("R-001", sample_outcome, hook, log)

        # Should fire because default includes run_completed
        mock_httpx.post.assert_called_once()

    def test_skips_when_httpx_not_installed(self, sample_outcome, log):
        """When httpx is not installed, logs warning and skips."""
        hook = {"url": "https://example.com/hook"}

        with patch("a_sdlc.notifications.httpx", None):
            _run_webhook_hook("R-001", sample_outcome, hook, log)

        log.warning.assert_called_once()
        assert "httpx" in log.warning.call_args[0][0].lower()

    def test_handles_http_error(self, sample_outcome, log):
        """HTTP errors are logged but do not propagate."""
        hook = {
            "url": "https://example.com/hook",
            "events": ["run_completed"],
        }

        with patch("a_sdlc.notifications.httpx") as mock_httpx:
            mock_httpx.HTTPError = Exception
            mock_httpx.post.side_effect = Exception("connection refused")
            _run_webhook_hook("R-001", sample_outcome, hook, log)

        log.error.assert_called_once()
        assert "failed" in log.error.call_args[0][0].lower()

    def test_missing_url_logs_warning(self, sample_outcome, log):
        """Missing 'url' field logs a warning."""
        hook: dict[str, Any] = {"type": "webhook", "events": ["run_completed"]}

        with patch("a_sdlc.notifications.httpx", MagicMock()):
            _run_webhook_hook("R-001", sample_outcome, hook, log)

        log.warning.assert_called_once()
        assert "url" in log.warning.call_args[0][0].lower()

    def test_timeout_parameter(self, sample_outcome, log):
        """Verify timeout is set to 10 seconds."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        hook = {"url": "https://example.com/hook"}

        with patch("a_sdlc.notifications.httpx") as mock_httpx:
            mock_httpx.post.return_value = mock_response
            mock_httpx.HTTPError = Exception
            _run_webhook_hook("R-001", sample_outcome, hook, log)

        assert mock_httpx.post.call_args[1]["timeout"] == 10.0

    def test_payload_includes_timestamp(self, sample_outcome, log):
        """Verify payload includes an ISO timestamp."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        hook = {"url": "https://example.com/hook"}

        with patch("a_sdlc.notifications.httpx") as mock_httpx:
            mock_httpx.post.return_value = mock_response
            mock_httpx.HTTPError = Exception
            _run_webhook_hook("R-001", sample_outcome, hook, log)

        payload = mock_httpx.post.call_args[1]["json"]
        # Should be parseable as ISO format
        assert "T" in payload["timestamp"]


# ---------------------------------------------------------------------------
# format_run_summary
# ---------------------------------------------------------------------------


class TestFormatRunSummary:
    def test_basic_format(self, sample_outcome):
        """Verify markdown structure and field inclusion."""
        summary = format_run_summary("R-001", sample_outcome)

        assert "# Execution Run Summary" in summary
        assert "**Run ID**: R-001" in summary
        assert "**Status**: completed" in summary
        assert "sprint" in summary
        assert "PROJ-S0001" in summary
        assert "- Completed: 3" in summary
        assert "- Failed: 0" in summary
        assert "- Skipped: 1" in summary
        assert "All tasks done" in summary

    def test_defaults_for_missing_fields(self):
        """Verify defaults when outcome dict has minimal fields."""
        summary = format_run_summary("R-002", {})

        assert "R-002" in summary
        assert "unknown" in summary
        assert "No summary available" in summary
        assert "- Completed: 0" in summary

    def test_contains_timestamp(self, sample_outcome):
        """Verify timestamp is present in summary."""
        summary = format_run_summary("R-001", sample_outcome)
        assert "**Timestamp**:" in summary
        assert "UTC" in summary


# ---------------------------------------------------------------------------
# Integration: executor._main() calls notification hooks
# ---------------------------------------------------------------------------


class TestMainNotificationIntegration:
    """Verify that _main() in executor.py calls notification hooks."""

    @pytest.fixture(autouse=True)
    def _mock_doctor_externals(self):
        """Auto-mock slow external calls used by the doctor command."""
        with (
            patch("a_sdlc.cli.check_docker_available", return_value=False),
            patch(
                "a_sdlc.cli.check_services_health",
                return_value={
                    "langfuse_reachable": False,
                    "signoz_reachable": False,
                    "services_running": False,
                },
            ),
            patch(
                "a_sdlc.cli.verify_monitoring_setup",
                return_value={
                    "files_ready": False,
                    "ready": False,
                    "hook_registered": False,
                    "otel_configured": False,
                },
            ),
            patch(
                "a_sdlc.cli.verify_sonarqube_setup",
                return_value={"ready": False, "host_url_configured": False},
            ),
        ):
            yield

    @pytest.fixture
    def runs_dir(self, tmp_path, monkeypatch):
        """Redirect the runs directory to a temp path."""
        runs = tmp_path / "runs"
        runs.mkdir()
        monkeypatch.setattr("a_sdlc.executor._RUNS_DIR", runs)
        return runs

    def test_main_calls_notifications_on_task_complete(self, runs_dir):
        """Verify _main() calls run_notification_hooks after task execution."""
        from a_sdlc.executor import Executor, _main

        with (
            patch("shutil.which", return_value="/usr/local/bin/claude"),
            patch("a_sdlc.executor.get_storage"),
            patch(
                "a_sdlc.executor.load_daemon_config",
                return_value={
                    "mode": "session",
                    "max_turns": 200,
                    "supervised": False,
                    "schedules": [],
                    "notifications": [
                        {"type": "file", "path": str(runs_dir / "{run_id}-notify.md")},
                    ],
                },
            ),
            patch.object(
                Executor,
                "execute_task",
                return_value={"status": "completed", "summary": "done"},
            ),
            patch(
                "sys.argv",
                [
                    "executor",
                    "--mode", "task",
                    "--task-id", "PROJ-T00001",
                    "--run-id", "R-notify01",
                ],
            ),
        ):
            _main()

        # Verify the notification file was created
        notify_file = runs_dir / "R-notify01-notify.md"
        assert notify_file.exists()
        assert "R-notify01" in notify_file.read_text()

    def test_main_notification_failure_does_not_crash(self, runs_dir):
        """Verify notification hook failure does not crash _main()."""
        from a_sdlc.executor import Executor, _main
        from a_sdlc.executor import _read_run as read_run

        with (
            patch("shutil.which", return_value="/usr/local/bin/claude"),
            patch("a_sdlc.executor.get_storage"),
            patch(
                "a_sdlc.executor.load_daemon_config",
                return_value={
                    "mode": "session",
                    "max_turns": 200,
                    "supervised": False,
                    "schedules": [],
                    "notifications": [
                        {"type": "webhook", "url": "https://bad.example.com"},
                    ],
                },
            ),
            patch.object(
                Executor,
                "execute_sprint",
                return_value={"status": "completed"},
            ),
            patch(
                "a_sdlc.notifications.httpx",
                None,  # Simulate httpx not installed
            ),
            patch(
                "sys.argv",
                [
                    "executor",
                    "--mode", "sprint",
                    "--sprint-id", "PROJ-S0001",
                    "--run-id", "R-notify02",
                ],
            ),
        ):
            # Should not raise even though webhook will fail
            _main()

        data = read_run("R-notify02")
        assert data["status"] == "completed"  # Run still marked as completed

    def test_main_sprint_calls_notifications(self, runs_dir):
        """Verify _main() calls notifications for sprint mode too."""
        from a_sdlc.executor import Executor, _main

        with (
            patch("shutil.which", return_value="/usr/local/bin/claude"),
            patch("a_sdlc.executor.get_storage"),
            patch(
                "a_sdlc.executor.load_daemon_config",
                return_value={
                    "mode": "session",
                    "max_turns": 200,
                    "supervised": False,
                    "schedules": [],
                    "notifications": [
                        {"type": "file", "path": str(runs_dir / "sprint-{run_id}.md")},
                    ],
                },
            ),
            patch.object(
                Executor,
                "execute_sprint",
                return_value={"status": "completed", "summary": "sprint done"},
            ),
            patch(
                "sys.argv",
                [
                    "executor",
                    "--mode", "sprint",
                    "--sprint-id", "PROJ-S0001",
                    "--run-id", "R-notify03",
                ],
            ),
        ):
            _main()

        notify_file = runs_dir / "sprint-R-notify03.md"
        assert notify_file.exists()
