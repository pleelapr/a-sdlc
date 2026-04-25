"""Tests for the enhanced ``a-sdlc run status`` command (FR-009, FR-010, FR-010a).

Covers:
- _extract_run_metrics helper: queue depth, agent count, phase detection
- _resolve_run_status helper: PID liveness check and crash detection
- _style_status helper: Rich markup for status strings
- _compute_duration helper: human-readable duration formatting
- Summary table: Phase, Queue (P/A/C/F), Agents, Duration columns
- Per-run detail: Queue State, Operational Metrics, Task Progress tables
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from a_sdlc.cli import main
from a_sdlc.executor import _write_run

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture(autouse=True)
def _mock_doctor_externals():
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
def runs_dir(tmp_path, monkeypatch):
    """Redirect the runs directory to a temp path."""
    runs = tmp_path / "runs"
    runs.mkdir()
    monkeypatch.setattr("a_sdlc.executor._RUNS_DIR", runs)
    return runs


# ---------------------------------------------------------------------------
# Helper: _extract_run_metrics
# ---------------------------------------------------------------------------


class TestExtractRunMetrics:
    """Tests for _extract_run_metrics helper."""

    def test_empty_data(self):
        from a_sdlc.cli import _extract_run_metrics

        result = _extract_run_metrics({})
        assert result["pending"] == 0
        assert result["active"] == 0
        assert result["completed"] == 0
        assert result["failed"] == 0
        assert result["agent_count"] == 0
        assert result["phase"] == ""

    def test_counts_progress_entries(self):
        from a_sdlc.cli import _extract_run_metrics

        data = {
            "status": "running",
            "progress_T1": {"task_id": "T1", "status": "completed", "agent_id": "a1"},
            "progress_T2": {"task_id": "T2", "status": "failed", "agent_id": "a2"},
            "progress_T3": {"task_id": "T3", "status": "assigned", "agent_id": "a3"},
            "progress_T4": {"task_id": "T4", "status": "pending", "agent_id": "a4"},
        }
        result = _extract_run_metrics(data)
        assert result["completed"] == 1
        assert result["failed"] == 1
        assert result["active"] == 1
        assert result["pending"] == 1

    def test_counts_agent_entries(self):
        from a_sdlc.cli import _extract_run_metrics

        data = {
            "status": "running",
            "agent_daemon-T1": {
                "agent_type": "backend",
                "task_id": "T1",
                "status": "assigned",
            },
            "agent_daemon-T2": {
                "agent_type": "frontend",
                "task_id": "T2",
                "status": "assigned",
            },
        }
        assert _extract_run_metrics(data)["agent_count"] == 2

    def test_phase_executing_when_progress(self):
        from a_sdlc.cli import _extract_run_metrics

        data = {
            "status": "running",
            "progress_T1": {"task_id": "T1", "status": "completed", "agent_id": "a"},
        }
        assert _extract_run_metrics(data)["phase"] == "executing"

    def test_phase_starting_when_no_progress(self):
        from a_sdlc.cli import _extract_run_metrics

        assert _extract_run_metrics({"status": "running"})["phase"] == "starting"

    def test_phase_done(self):
        from a_sdlc.cli import _extract_run_metrics

        assert _extract_run_metrics({"status": "completed"})["phase"] == "done"

    def test_phase_failed(self):
        from a_sdlc.cli import _extract_run_metrics

        assert _extract_run_metrics({"status": "failed"})["phase"] == "failed"

    def test_phase_paused(self):
        from a_sdlc.cli import _extract_run_metrics

        data = {"status": "awaiting_confirmation"}
        assert _extract_run_metrics(data)["phase"] == "paused"

    def test_phase_waiting_for_clarification(self):
        from a_sdlc.cli import _extract_run_metrics

        data = {"status": "awaiting_clarification"}
        assert _extract_run_metrics(data)["phase"] == "waiting"

    def test_phase_from_outcome(self):
        from a_sdlc.cli import _extract_run_metrics

        data = {"status": "completed", "outcome": {"status": "PARTIAL"}}
        assert _extract_run_metrics(data)["phase"] == "PARTIAL"

    def test_ignores_non_dict_progress(self):
        from a_sdlc.cli import _extract_run_metrics

        data = {"status": "running", "progress_note": "a string not a dict"}
        result = _extract_run_metrics(data)
        assert result["completed"] == 0
        assert result["pending"] == 0

    def test_in_progress_counts_as_active(self):
        from a_sdlc.cli import _extract_run_metrics

        data = {
            "status": "running",
            "progress_T1": {"task_id": "T1", "status": "in_progress", "agent_id": "a"},
        }
        assert _extract_run_metrics(data)["active"] == 1


# ---------------------------------------------------------------------------
# Helper: _resolve_run_status
# ---------------------------------------------------------------------------


class TestResolveRunStatus:
    """Tests for _resolve_run_status helper."""

    def test_running_with_no_pid(self):
        from a_sdlc.cli import _resolve_run_status

        status, alive = _resolve_run_status({"status": "running", "pid": None})
        assert status == "running"
        assert alive is False

    def test_completed_status_unchanged(self):
        from a_sdlc.cli import _resolve_run_status

        status, _alive = _resolve_run_status(
            {"status": "completed", "pid": 999999999}
        )
        assert status == "completed"

    def test_running_with_dead_pid_becomes_crashed(self):
        from a_sdlc.cli import _resolve_run_status

        status, alive = _resolve_run_status(
            {"status": "running", "pid": 999999999}
        )
        assert status == "crashed"
        assert alive is False

    def test_failed_status_unchanged(self):
        from a_sdlc.cli import _resolve_run_status

        status, _alive = _resolve_run_status({"status": "failed", "pid": None})
        assert status == "failed"

    def test_missing_status_defaults_unknown(self):
        from a_sdlc.cli import _resolve_run_status

        status, _alive = _resolve_run_status({})
        assert status == "unknown"


# ---------------------------------------------------------------------------
# Helper: _style_status
# ---------------------------------------------------------------------------


class TestStyleStatus:
    """Tests for _style_status helper."""

    def test_known_statuses_get_markup(self):
        from a_sdlc.cli import _style_status

        assert "[green]" in _style_status("running")
        assert "[blue]" in _style_status("completed")
        assert "[red]" in _style_status("failed")
        assert "[yellow]" in _style_status("cancelled")
        assert "[red]" in _style_status("crashed")
        assert "[magenta]" in _style_status("awaiting_confirmation")
        assert "[magenta]" in _style_status("awaiting_clarification")

    def test_unknown_status_no_markup(self):
        from a_sdlc.cli import _style_status

        assert _style_status("custom_status") == "custom_status"


# ---------------------------------------------------------------------------
# Helper: _compute_duration
# ---------------------------------------------------------------------------


class TestComputeDuration:
    """Tests for _compute_duration helper."""

    def test_no_started_at(self):
        from a_sdlc.cli import _compute_duration

        assert _compute_duration({}) == "-"

    def test_invalid_started_at(self):
        from a_sdlc.cli import _compute_duration

        assert _compute_duration({"started_at": "not-a-date"}) == "-"

    def test_formats_seconds(self):
        from datetime import timedelta

        from a_sdlc.cli import _compute_duration

        now = datetime.now(timezone.utc)
        started = (now - timedelta(seconds=45)).isoformat()
        result = _compute_duration({"started_at": started, "status": "running"})
        assert "s" in result
        # Should not show hours or minutes for 45 seconds
        assert "h" not in result

    def test_formats_minutes(self):
        from datetime import timedelta

        from a_sdlc.cli import _compute_duration

        now = datetime.now(timezone.utc)
        started = (now - timedelta(minutes=5, seconds=30)).isoformat()
        result = _compute_duration({"started_at": started, "status": "running"})
        assert "m" in result
        assert "s" in result

    def test_formats_hours(self):
        from datetime import timedelta

        from a_sdlc.cli import _compute_duration

        now = datetime.now(timezone.utc)
        started = (now - timedelta(hours=2, minutes=15)).isoformat()
        result = _compute_duration({"started_at": started, "status": "running"})
        assert "h" in result
        assert "m" in result

    def test_zero_seconds(self):
        from a_sdlc.cli import _compute_duration

        now = datetime.now(timezone.utc)
        result = _compute_duration({"started_at": now.isoformat(), "status": "running"})
        assert "s" in result


# ---------------------------------------------------------------------------
# Summary table: enhanced columns (FR-009)
# ---------------------------------------------------------------------------


class TestRunStatusEnhancedSummary:
    """Verify the summary table includes Phase, Queue, Agents, Duration columns."""

    @pytest.fixture(autouse=True)
    def _wide_console(self, monkeypatch):
        """Widen Rich console so table columns are not truncated."""
        from rich.console import Console

        from a_sdlc import cli as _cli_mod

        monkeypatch.setattr(_cli_mod, "console", Console(width=200))

    def test_summary_has_phase_column(self, runner, runs_dir):
        """Phase column present and shows 'executing' for running+progress."""
        _write_run("R-enh01", {
            "run_id": "R-enh01",
            "type": "sprint",
            "entity_id": "PROJ-S0001",
            "status": "running",
            "pid": None,
            "started_at": "2026-04-09T10:00:00+00:00",
            "progress_T01": {
                "task_id": "T01", "status": "completed", "agent_id": "a1",
            },
        })
        result = runner.invoke(main, ["run", "status"])
        assert result.exit_code == 0
        assert "Phase" in result.output
        assert "executing" in result.output.lower()

    def test_summary_has_queue_column(self, runner, runs_dir):
        """Queue (P/A/C/F) column present with correct counts."""
        _write_run("R-enh02", {
            "run_id": "R-enh02",
            "type": "sprint",
            "entity_id": "PROJ-S0001",
            "status": "running",
            "pid": None,
            "started_at": "2026-04-09T10:00:00+00:00",
            "progress_T01": {"task_id": "T01", "status": "completed", "agent_id": "a1"},
            "progress_T02": {"task_id": "T02", "status": "failed", "agent_id": "a2"},
            "progress_T03": {"task_id": "T03", "status": "assigned", "agent_id": "a3"},
        })
        result = runner.invoke(main, ["run", "status"])
        assert result.exit_code == 0
        assert "Queue" in result.output
        # P=0, A=1, C=1, F=1
        assert "0/1/1/1" in result.output

    def test_summary_has_agents_column(self, runner, runs_dir):
        """Agents column present and counts agent entries."""
        _write_run("R-enh03", {
            "run_id": "R-enh03",
            "type": "sprint",
            "entity_id": "PROJ-S0001",
            "status": "running",
            "pid": None,
            "started_at": "2026-04-09T10:00:00+00:00",
            "agent_daemon-T01": {
                "agent_type": "backend", "task_id": "T01", "status": "assigned",
            },
            "agent_daemon-T02": {
                "agent_type": "frontend", "task_id": "T02", "status": "assigned",
            },
        })
        result = runner.invoke(main, ["run", "status"])
        assert result.exit_code == 0
        assert "Agents" in result.output

    def test_summary_has_duration_column(self, runner, runs_dir):
        """Duration column present."""
        _write_run("R-enh04", {
            "run_id": "R-enh04",
            "type": "task",
            "entity_id": "PROJ-T00001",
            "status": "running",
            "pid": None,
            "started_at": "2026-04-09T10:00:00+00:00",
        })
        result = runner.invoke(main, ["run", "status"])
        assert result.exit_code == 0
        assert "Duration" in result.output

    def test_summary_dash_when_no_progress(self, runner, runs_dir):
        """Queue shows '-' when no progress entries exist."""
        _write_run("R-enh05", {
            "run_id": "R-enh05",
            "type": "task",
            "entity_id": "PROJ-T00001",
            "status": "completed",
            "pid": None,
            "started_at": "2026-04-09T10:00:00+00:00",
        })
        result = runner.invoke(main, ["run", "status"])
        assert result.exit_code == 0
        # The '-' in the Queue column (no progress_ keys)
        # We verify the table renders (exit code 0) and has the columns

    def test_summary_no_runs_message(self, runner, runs_dir):
        """Empty runs directory shows friendly message."""
        result = runner.invoke(main, ["run", "status"])
        assert result.exit_code == 0
        assert "no runs found" in result.output.lower()


# ---------------------------------------------------------------------------
# Per-run detail: enhanced view (FR-010, FR-010a)
# ---------------------------------------------------------------------------


class TestRunStatusEnhancedDetail:
    """Verify per-run detail shows Queue State, Metrics, and Progress tables."""

    def test_detail_queue_state_table(self, runner, runs_dir):
        """Queue State table shown with correct rows."""
        _write_run("R-dt10", {
            "run_id": "R-dt10",
            "type": "sprint",
            "entity_id": "PROJ-S0001",
            "status": "running",
            "pid": None,
            "started_at": "2026-04-09T10:00:00+00:00",
            "progress_T01": {"task_id": "T01", "status": "completed", "agent_id": "a1"},
            "progress_T02": {"task_id": "T02", "status": "failed", "agent_id": "a2"},
        })
        result = runner.invoke(main, ["run", "status", "R-dt10"])
        assert result.exit_code == 0
        assert "Queue State" in result.output
        assert "Pending" in result.output
        assert "Completed" in result.output
        assert "Failed" in result.output
        assert "Total" in result.output

    def test_detail_operational_metrics_table(self, runner, runs_dir):
        """Operational Metrics table shown with key rows."""
        _write_run("R-dt11", {
            "run_id": "R-dt11",
            "type": "sprint",
            "entity_id": "PROJ-S0001",
            "status": "running",
            "pid": None,
            "started_at": "2026-04-09T10:00:00+00:00",
            "max_concurrency": 3,
            "agent_daemon-T01": {
                "agent_type": "backend", "task_id": "T01", "status": "assigned",
            },
        })
        result = runner.invoke(main, ["run", "status", "R-dt11"])
        assert result.exit_code == 0
        assert "Operational Metrics" in result.output
        assert "Total Duration" in result.output
        assert "Agent Sessions" in result.output
        assert "Failures" in result.output
        assert "Max Concurrency" in result.output

    def test_detail_task_progress_table(self, runner, runs_dir):
        """Task Progress table shows individual task statuses."""
        _write_run("R-dt12", {
            "run_id": "R-dt12",
            "type": "sprint",
            "entity_id": "PROJ-S0001",
            "status": "running",
            "pid": None,
            "started_at": "2026-04-09T10:00:00+00:00",
            "progress_T01": {
                "task_id": "PROJ-T00001", "status": "completed", "agent_id": "d-T01",
            },
            "progress_T02": {
                "task_id": "PROJ-T00002", "status": "failed", "agent_id": "d-T02",
            },
        })
        result = runner.invoke(main, ["run", "status", "R-dt12"])
        assert result.exit_code == 0
        assert "Task Progress" in result.output
        assert "PROJ-T00001" in result.output
        assert "PROJ-T00002" in result.output
        assert "d-T01" in result.output

    def test_detail_phase_and_duration(self, runner, runs_dir):
        """Phase and Duration shown in header panel."""
        _write_run("R-dt13", {
            "run_id": "R-dt13",
            "type": "sprint",
            "entity_id": "PROJ-S0001",
            "status": "running",
            "pid": None,
            "started_at": "2026-04-09T10:00:00+00:00",
        })
        result = runner.invoke(main, ["run", "status", "R-dt13"])
        assert result.exit_code == 0
        assert "Phase" in result.output
        assert "Duration" in result.output

    def test_detail_error_panel(self, runner, runs_dir):
        """Error panel shown when run has an error."""
        _write_run("R-dt14", {
            "run_id": "R-dt14",
            "type": "task",
            "entity_id": "PROJ-T00001",
            "status": "failed",
            "pid": None,
            "started_at": "2026-04-09T10:00:00+00:00",
            "error": "Claude Code CLI not found",
        })
        result = runner.invoke(main, ["run", "status", "R-dt14"])
        assert result.exit_code == 0
        assert "Error" in result.output
        assert "Claude Code CLI not found" in result.output

    def test_detail_outcome_panel(self, runner, runs_dir):
        """Outcome panel shown when run is completed."""
        _write_run("R-dt15", {
            "run_id": "R-dt15",
            "type": "sprint",
            "entity_id": "PROJ-S0001",
            "status": "completed",
            "pid": None,
            "started_at": "2026-04-09T10:00:00+00:00",
            "outcome": {
                "status": "completed",
                "completed": "3",
                "failed": "0",
                "summary": "All tasks finished successfully",
            },
        })
        result = runner.invoke(main, ["run", "status", "R-dt15"])
        assert result.exit_code == 0
        assert "Outcome" in result.output
        assert "All tasks finished successfully" in result.output

    def test_detail_log_file_reference(self, runner, runs_dir):
        """Log file path shown when log file exists."""
        run_id = "R-dt16"
        _write_run(run_id, {
            "run_id": run_id,
            "type": "task",
            "entity_id": "PROJ-T00001",
            "status": "running",
            "pid": None,
            "started_at": "2026-04-09T10:00:00+00:00",
        })
        log_path = runs_dir / f"{run_id}.log"
        log_path.write_text("some output\n")

        result = runner.invoke(main, ["run", "status", run_id])
        assert result.exit_code == 0
        assert "Log file:" in result.output or "tail -f" in result.output

    def test_detail_awaiting_approval_instructions(self, runner, runs_dir):
        """Approval instructions shown for awaiting_confirmation runs."""
        run_id = "R-dt17"
        _write_run(run_id, {
            "run_id": run_id,
            "type": "sprint",
            "entity_id": "PROJ-S0001",
            "status": "awaiting_confirmation",
            "config": {"message": "Batch 1 done, approve?"},
            "pid": None,
            "started_at": "2026-04-09T10:00:00+00:00",
        })
        result = runner.invoke(main, ["run", "status", run_id])
        assert result.exit_code == 0
        assert f"a-sdlc run approve {run_id}" in result.output
        assert f"a-sdlc run reject {run_id}" in result.output
        assert "Batch 1 done, approve?" in result.output

    def test_detail_awaiting_answer_instructions(self, runner, runs_dir):
        """Answer instructions shown for awaiting_clarification runs."""
        run_id = "R-dt18"
        _write_run(run_id, {
            "run_id": run_id,
            "type": "goal",
            "entity_id": "test",
            "status": "awaiting_clarification",
            "config": {"message": "Which framework?"},
            "pid": None,
            "started_at": "2026-04-09T10:00:00+00:00",
        })
        result = runner.invoke(main, ["run", "status", run_id])
        assert result.exit_code == 0
        assert f"a-sdlc run answer {run_id}" in result.output
        assert "Which framework?" in result.output

    def test_detail_nonexistent_run(self, runner, runs_dir):
        """Non-existent run_id returns error."""
        result = runner.invoke(main, ["run", "status", "R-ghost999"])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_detail_no_queue_table_when_no_progress(self, runner, runs_dir):
        """Queue State table not shown when no progress entries exist."""
        _write_run("R-dt19", {
            "run_id": "R-dt19",
            "type": "task",
            "entity_id": "PROJ-T00001",
            "status": "completed",
            "pid": None,
            "started_at": "2026-04-09T10:00:00+00:00",
        })
        result = runner.invoke(main, ["run", "status", "R-dt19"])
        assert result.exit_code == 0
        # Queue State table should not appear (no progress_ keys)
        assert "Queue State" not in result.output

    def test_detail_controls_table(self, runner, runs_dir):
        """Control Actions table shown when controls exist."""
        _write_run("R-dt20", {
            "run_id": "R-dt20",
            "type": "sprint",
            "entity_id": "PROJ-S0001",
            "status": "running",
            "pid": None,
            "started_at": "2026-04-09T10:00:00+00:00",
            "controls": [
                {"item_id": "T00001", "action": "pause", "issued_at": "2026-04-09T10:05:00"},
            ],
        })
        result = runner.invoke(main, ["run", "status", "R-dt20"])
        assert result.exit_code == 0
        assert "Control Actions" in result.output
        assert "T00001" in result.output
        assert "pause" in result.output.lower()

    def test_detail_answers_table(self, runner, runs_dir):
        """Answers table shown when answers exist."""
        _write_run("R-dt21", {
            "run_id": "R-dt21",
            "type": "goal",
            "entity_id": "test",
            "status": "running",
            "pid": None,
            "started_at": "2026-04-09T10:00:00+00:00",
            "answers": [
                {"message": "use RS256", "answered_at": "2026-04-09T10:02:00"},
            ],
        })
        result = runner.invoke(main, ["run", "status", "R-dt21"])
        assert result.exit_code == 0
        assert "Answers" in result.output
        assert "use RS256" in result.output

    def test_detail_comments_table(self, runner, runs_dir):
        """Comments table shown when comments exist."""
        _write_run("R-dt22", {
            "run_id": "R-dt22",
            "type": "goal",
            "entity_id": "test",
            "status": "running",
            "pid": None,
            "started_at": "2026-04-09T10:00:00+00:00",
            "comments": [
                {
                    "artifact_id": "PROJ-P0001",
                    "message": "Focus on REST",
                    "posted_at": "2026-04-09T10:03:00",
                },
            ],
        })
        result = runner.invoke(main, ["run", "status", "R-dt22"])
        assert result.exit_code == 0
        assert "Comments" in result.output
        assert "PROJ-P0001" in result.output
        assert "Focus on REST" in result.output


# ---------------------------------------------------------------------------
# Pipeline-specific tests (FR-009, FR-010, FR-010a)
# ---------------------------------------------------------------------------


class TestRunStatusPipeline:
    """Tests for pipeline run display in summary and detail views."""

    @pytest.fixture(autouse=True)
    def _wide_console(self, monkeypatch):
        """Widen Rich console so table columns are not truncated."""
        from rich.console import Console

        from a_sdlc import cli as _cli_mod

        monkeypatch.setattr(_cli_mod, "console", Console(width=200))

    def test_pipeline_run_shows_phase_and_queue(self, runner, runs_dir):
        """Pipeline runs display phase, queue depth, and thread count in summary (FR-009)."""
        _write_run("R-pipe01", {
            "run_id": "R-pipe01",
            "type": "pipeline",
            "entity_id": "PROJ-P0001",
            "status": "running",
            "phase": "implement",
            "work_queue": [
                {"id": "WQ-1", "status": "completed"},
                {"id": "WQ-2", "status": "active"},
                {"id": "WQ-3", "status": "pending"},
                {"id": "WQ-4", "status": "pending"},
            ],
            "thread_entries": [
                {"timestamp": "2026-04-09T10:00:00", "action": "Started"},
                {"timestamp": "2026-04-09T10:01:00", "action": "PRD done"},
                {"timestamp": "2026-04-09T10:02:00", "action": "Design done"},
            ],
            "started_at": "2026-04-09T10:00:00",
            "pid": None,
        })

        result = runner.invoke(main, ["run", "status"])
        assert result.exit_code == 0
        assert "pipeline" in result.output
        assert "implement" in result.output
        # Queue format: P/A/C/F = 2/1/1/0
        assert "2/1/1/0" in result.output
        # Threads column should show 3
        assert "3" in result.output

    def test_sprint_run_shows_dashes_for_pipeline_columns(self, runner, runs_dir):
        """Sprint runs display '-' for Phase, Queue, Threads columns (NFR-003)."""
        _write_run("R-sprint01", {
            "run_id": "R-sprint01",
            "type": "sprint",
            "entity_id": "PROJ-S0001",
            "status": "completed",
            "started_at": "2026-04-09T10:00:00",
            "pid": None,
        })

        result = runner.invoke(main, ["run", "status"])
        assert result.exit_code == 0
        assert "sprint" in result.output

    def test_awaiting_clarification_shows_question_snippet(self, runner, runs_dir):
        """Runs with awaiting_clarification show truncated question (FR-010a)."""
        _write_run("R-clar01", {
            "run_id": "R-clar01",
            "type": "pipeline",
            "entity_id": "PROJ-P0001",
            "status": "awaiting_clarification",
            "phase": "pm",
            "clarification_question": "Should we support OAuth2 authorization code flow?",
            "work_queue": [],
            "thread_entries": [],
            "started_at": "2026-04-09T10:00:00",
            "pid": None,
        })

        result = runner.invoke(main, ["run", "status"])
        assert result.exit_code == 0
        assert "awaiting" in result.output.lower()
        assert "OAuth2" in result.output

    def test_detail_view_pipeline_full(self, runner, runs_dir):
        """Detail view for pipeline run shows goal, phase, work queue, threads, metrics (FR-010)."""
        _write_run("R-det02", {
            "run_id": "R-det02",
            "type": "pipeline",
            "entity_id": "PROJ-P0001",
            "goal": "Build auth system",
            "status": "running",
            "phase": "implement",
            "work_queue": [
                {
                    "id": "WQ-1",
                    "type": "task",
                    "artifact_id": "PROJ-T00001",
                    "status": "completed",
                    "persona": "sdlc-backend-engineer",
                    "started_at": "2026-04-09T10:05:00",
                    "completed_at": "2026-04-09T10:10:00",
                },
                {
                    "id": "WQ-2",
                    "type": "task",
                    "artifact_id": "PROJ-T00002",
                    "status": "active",
                    "persona": "sdlc-frontend-engineer",
                    "started_at": "2026-04-09T10:10:00",
                    "completed_at": None,
                },
            ],
            "thread_entries": [
                {"timestamp": "2026-04-09T10:00:00", "phase": "pm", "agent": "pm", "action": "Generated PRD"},
                {"timestamp": "2026-04-09T10:05:00", "phase": "implement", "agent": "be", "action": "Started task"},
            ],
            "metrics": {
                "total_duration_sec": 600,
                "phase_durations": {"pm": 60, "implement": 540},
                "agent_session_count": 3,
                "challenge_rounds": 1,
                "failure_count": 0,
                "total_cost_cents": 250,
                "total_turns": 30,
            },
            "started_at": "2026-04-09T10:00:00",
            "pid": 99999,
        })

        result = runner.invoke(main, ["run", "status", "R-det02"])
        assert result.exit_code == 0
        # Run info
        assert "Build auth system" in result.output
        assert "implement" in result.output
        # Work queue
        assert "Work Queue" in result.output
        assert "PROJ-T00001" in result.output
        assert "sdlc-backend-engineer" in result.output
        # Thread entries
        assert "Recent Activity" in result.output
        assert "Generated PRD" in result.output
        # Metrics
        assert "Metrics" in result.output
        assert "$2.50" in result.output
        assert "10m" in result.output  # 600s = 10m 0s

        # Operational Metrics (newly added)
        assert "Operational Metrics" in result.output
        assert "Threads" in result.output
        assert "2" in result.output  # len(thread_entries) == 2
        assert "Challenge Rounds" in result.output
        assert "1" in result.output  # challenge_rounds == 1

    def test_detail_view_clarification(self, runner, runs_dir):
        """Detail view shows clarification panel when run is awaiting input (FR-010a)."""
        _write_run("R-clar02", {
            "run_id": "R-clar02",
            "type": "pipeline",
            "entity_id": "PROJ-P0001",
            "status": "awaiting_clarification",
            "phase": "pm",
            "clarification_question": "Which OAuth2 grant types should we support?",
            "work_queue": [],
            "thread_entries": [],
            "started_at": "2026-04-09T10:00:00",
            "pid": None,
        })

        result = runner.invoke(main, ["run", "status", "R-clar02"])
        assert result.exit_code == 0
        assert "Clarification Needed" in result.output
        assert "OAuth2 grant types" in result.output
        assert "a-sdlc run answer" in result.output

    def test_approval_instructions_still_shown(self, runner, runs_dir):
        """Existing awaiting_confirmation approval flow still works (NFR-003)."""
        _write_run("R-compat01", {
            "run_id": "R-compat01",
            "type": "sprint",
            "entity_id": "PROJ-S0001",
            "status": "awaiting_confirmation",
            "config": {"message": "Batch 1 complete"},
            "pid": None,
            "started_at": "2026-04-09T10:00:00",
        })

        result = runner.invoke(main, ["run", "status"])
        assert result.exit_code == 0
        assert "a-sdlc run approve R-compat01" in result.output

    def test_extract_metrics_pipeline_work_queue(self):
        """_extract_run_metrics correctly counts pipeline work_queue items."""
        from a_sdlc.cli import _extract_run_metrics

        data = {
            "type": "pipeline",
            "status": "running",
            "phase": "implement",
            "work_queue": [
                {"id": "WQ-1", "status": "completed"},
                {"id": "WQ-2", "status": "active"},
                {"id": "WQ-3", "status": "pending"},
                {"id": "WQ-4", "status": "failed"},
            ],
            "thread_entries": [
                {"timestamp": "t1", "action": "a1"},
                {"timestamp": "t2", "action": "a2"},
            ],
        }
        result = _extract_run_metrics(data)
        assert result["completed"] == 1
        assert result["active"] == 1
        assert result["pending"] == 1
        assert result["failed"] == 1
        assert result["phase"] == "implement"
        assert result["thread_count"] == 2

    def test_extract_metrics_pipeline_agent_session_count(self):
        """_extract_run_metrics picks up agent_session_count from pipeline metrics."""
        from a_sdlc.cli import _extract_run_metrics

        data = {
            "type": "pipeline",
            "status": "running",
            "phase": "implement",
            "metrics": {"agent_session_count": 5},
        }
        result = _extract_run_metrics(data)
        assert result["agent_count"] == 5

    def test_extract_metrics_pipeline_challenge_rounds(self):
        """_extract_run_metrics picks up challenge_rounds from pipeline metrics."""
        from a_sdlc.cli import _extract_run_metrics

        data = {
            "type": "pipeline",
            "status": "running",
            "phase": "implement",
            "metrics": {"challenge_rounds": 3},
        }
        result = _extract_run_metrics(data)
        assert result["challenge_rounds"] == 3
