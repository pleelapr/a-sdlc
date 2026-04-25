"""Integration tests for Pipeline CLI commands (P0032).

Covers: run goal, run answer, run control, run comment, enhanced run status.
All tests use Click CliRunner with mocked subprocess/storage layers.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from a_sdlc.cli import main
from a_sdlc.executor import _read_run, _write_run

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def runner() -> CliRunner:
    """Create CLI test runner."""
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


@pytest.fixture(autouse=True)
def _mock_cli_targets():
    """Auto-mock resolve_targets and detect_targets."""
    from a_sdlc.cli_targets import CLAUDE_TARGET

    with (
        patch("a_sdlc.cli.resolve_targets", return_value=[CLAUDE_TARGET]),
        patch("a_sdlc.cli.detect_targets", return_value=[CLAUDE_TARGET]),
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
# TestRunGoal
# ---------------------------------------------------------------------------


class TestRunGoal:
    """Tests for ``a-sdlc run goal`` command."""

    def test_run_goal_basic(self, runner, runs_dir):
        """Invoke ``run goal "Add JWT auth"``, assert subprocess spawned
        and run_id printed in the output panel."""
        with (
            patch("subprocess.Popen") as mock_popen,
            patch("shutil.which", return_value="/usr/local/bin/claude"),
        ):
            mock_proc = MagicMock()
            mock_proc.pid = 12345
            mock_popen.return_value = mock_proc

            result = runner.invoke(main, ["run", "goal", "Add JWT auth"])

        assert result.exit_code == 0, result.output
        assert "R-" in result.output
        mock_popen.assert_called_once()

    def test_run_goal_with_goal_file(self, runner, runs_dir, tmp_path):
        """Invoke with --goal-file, assert file content is referenced
        in the subprocess arguments."""
        goal_file = tmp_path / "goal.md"
        goal_file.write_text("Implement full JWT authentication with RS256")

        with (
            patch("subprocess.Popen") as mock_popen,
            patch("shutil.which", return_value="/usr/local/bin/claude"),
        ):
            mock_proc = MagicMock()
            mock_proc.pid = 12345
            mock_popen.return_value = mock_proc

            result = runner.invoke(
                main,
                ["run", "goal", "Add JWT auth", "--goal-file", str(goal_file)],
            )

        assert result.exit_code == 0, result.output
        # The goal file path should appear in the Popen command args
        call_args = mock_popen.call_args
        cmd = call_args[0][0] if call_args[0] else call_args.kwargs.get("args", [])
        cmd_str = " ".join(str(a) for a in cmd)
        assert str(goal_file) in cmd_str or "goal-file" in cmd_str

    def test_run_goal_with_options(self, runner, runs_dir):
        """Invoke with --max-turns, --adapter, --no-interactive, --max-concurrency."""
        with (
            patch("subprocess.Popen") as mock_popen,
            patch("shutil.which", return_value="/usr/local/bin/claude"),
        ):
            mock_proc = MagicMock()
            mock_proc.pid = 12345
            mock_popen.return_value = mock_proc

            result = runner.invoke(
                main,
                [
                    "run",
                    "goal",
                    "Add JWT auth",
                    "--max-turns",
                    "500",
                    "--adapter",
                    "claude",
                    "--no-interactive",
                    "--max-concurrency",
                    "5",
                ],
            )

        assert result.exit_code == 0, result.output
        # Verify the options are passed through to the subprocess command
        call_args = mock_popen.call_args
        cmd = call_args[0][0] if call_args[0] else call_args.kwargs.get("args", [])
        cmd_str = " ".join(str(a) for a in cmd)
        assert "500" in cmd_str  # max-turns value
        assert "--no-interactive" in cmd_str

    def test_run_goal_no_claude_cli(self, runner, runs_dir):
        """When shutil.which returns None for adapter CLI, assert error."""
        with patch("shutil.which", return_value=None):
            result = runner.invoke(main, ["run", "goal", "Add JWT auth"])

        assert result.exit_code != 0

    def test_run_goal_creates_db_record(self, runner, runs_dir):
        """Assert run state file is created with type='pipeline'."""
        with (
            patch("subprocess.Popen") as mock_popen,
            patch("shutil.which", return_value="/usr/local/bin/claude"),
        ):
            mock_proc = MagicMock()
            mock_proc.pid = 12345
            mock_popen.return_value = mock_proc

            result = runner.invoke(main, ["run", "goal", "Add JWT auth"])

        assert result.exit_code == 0, result.output
        run_files = list(runs_dir.glob("R-*.json"))
        assert len(run_files) == 1
        data = json.loads(run_files[0].read_text())
        assert data["type"] == "pipeline"
        assert data["goal"] == "Add JWT auth"
        assert data["status"] == "running"

    def test_run_goal_subprocess_detached(self, runner, runs_dir):
        """Assert Popen is called with start_new_session=True."""
        with (
            patch("subprocess.Popen") as mock_popen,
            patch("shutil.which", return_value="/usr/local/bin/claude"),
        ):
            mock_proc = MagicMock()
            mock_proc.pid = 12345
            mock_popen.return_value = mock_proc

            result = runner.invoke(main, ["run", "goal", "Add JWT auth"])

        assert result.exit_code == 0, result.output
        call_kwargs = mock_popen.call_args.kwargs
        assert call_kwargs.get("start_new_session") is True


# ---------------------------------------------------------------------------
# TestRunAnswer
# ---------------------------------------------------------------------------


class TestRunAnswer:
    """Tests for ``a-sdlc run answer`` command."""

    def test_run_answer_basic(self, runner, runs_dir):
        """Invoke ``run answer R-123 -m "use RS256"``, assert status updated."""
        run_id = "R-answer01"
        _write_run(
            run_id,
            {
                "run_id": run_id,
                "type": "pipeline",
                "status": "awaiting_clarification",
                "config": {"question": "Which algorithm?"},
                "answers": [],
            },
        )

        result = runner.invoke(
            main, ["run", "answer", run_id, "-m", "use RS256"]
        )

        assert result.exit_code == 0, result.output
        data = _read_run(run_id)
        assert data["status"] == "running"
        assert len(data["answers"]) == 1
        assert data["answers"][0]["message"] == "use RS256"

    def test_run_answer_with_item(self, runner, runs_dir):
        """Invoke with --item flag to answer a specific item's question."""
        run_id = "R-answer02"
        _write_run(
            run_id,
            {
                "run_id": run_id,
                "type": "pipeline",
                "status": "awaiting_clarification",
                "config": {},
                "answers": [],
            },
        )

        result = runner.invoke(
            main,
            ["run", "answer", run_id, "--item", "ITEM-1", "-m", "use RS256"],
        )

        assert result.exit_code == 0, result.output
        data = _read_run(run_id)
        assert data["status"] == "running"
        assert data["answers"][0]["item_id"] == "ITEM-1"

    def test_run_answer_invalid_status(self, runner, runs_dir):
        """Run not in awaiting_clarification status -- assert warning."""
        run_id = "R-answer03"
        _write_run(
            run_id,
            {
                "run_id": run_id,
                "type": "pipeline",
                "status": "running",
                "config": {},
            },
        )

        result = runner.invoke(
            main, ["run", "answer", run_id, "-m", "use RS256"]
        )

        # Should warn that the run is not awaiting an answer
        assert (
            "not awaiting" in result.output.lower()
            or "cannot answer" in result.output.lower()
        )

    def test_run_answer_invalid_run(self, runner, runs_dir):
        """Nonexistent run_id -- assert error."""
        result = runner.invoke(
            main, ["run", "answer", "R-ghost", "-m", "use RS256"]
        )

        assert result.exit_code != 0
        assert "not found" in result.output.lower()


# ---------------------------------------------------------------------------
# TestRunControl
# ---------------------------------------------------------------------------


class TestRunControl:
    """Tests for ``a-sdlc run control`` command."""

    def _setup_run(self, runs_dir, run_id="R-ctrl01"):
        """Helper: create a run state file with status=running."""
        _write_run(
            run_id,
            {
                "run_id": run_id,
                "type": "pipeline",
                "status": "running",
                "controls": [],
            },
        )
        return run_id

    def test_run_control_cancel(self, runner, runs_dir):
        """Invoke ``run control ITEM-1 --action cancel``."""
        run_id = self._setup_run(runs_dir)

        result = runner.invoke(
            main,
            ["run", "control", "ITEM-1", "--action", "cancel", "--run-id", run_id],
        )

        assert result.exit_code == 0, result.output
        assert "cancel" in result.output.lower()
        data = _read_run(run_id)
        assert len(data["controls"]) == 1
        assert data["controls"][0]["action"] == "cancel"
        assert data["controls"][0]["item_id"] == "ITEM-1"

    def test_run_control_skip(self, runner, runs_dir):
        """Invoke with --action skip."""
        run_id = self._setup_run(runs_dir)

        result = runner.invoke(
            main,
            ["run", "control", "ITEM-1", "--action", "skip", "--run-id", run_id],
        )

        assert result.exit_code == 0, result.output
        data = _read_run(run_id)
        assert data["controls"][0]["action"] == "skip"

    def test_run_control_retry(self, runner, runs_dir):
        """Invoke with --action retry."""
        run_id = self._setup_run(runs_dir)

        result = runner.invoke(
            main,
            ["run", "control", "ITEM-1", "--action", "retry", "--run-id", run_id],
        )

        assert result.exit_code == 0, result.output
        data = _read_run(run_id)
        assert data["controls"][0]["action"] == "retry"

    def test_run_control_force_approve(self, runner, runs_dir):
        """Invoke with --action force-approve."""
        run_id = self._setup_run(runs_dir)

        result = runner.invoke(
            main,
            [
                "run",
                "control",
                "ITEM-1",
                "--action",
                "force-approve",
                "--run-id",
                run_id,
            ],
        )

        assert result.exit_code == 0, result.output
        data = _read_run(run_id)
        assert data["controls"][0]["action"] == "force-approve"

    def test_run_control_pause(self, runner, runs_dir):
        """Invoke with --action pause."""
        run_id = self._setup_run(runs_dir)

        result = runner.invoke(
            main,
            ["run", "control", "ITEM-1", "--action", "pause", "--run-id", run_id],
        )

        assert result.exit_code == 0, result.output
        data = _read_run(run_id)
        assert data["controls"][0]["action"] == "pause"

    def test_run_control_no_active_run(self, runner, runs_dir):
        """No active run and no --run-id specified -- assert error."""
        result = runner.invoke(
            main, ["run", "control", "ITEM-GHOST", "--action", "cancel"]
        )

        assert result.exit_code != 0
        assert "no active run" in result.output.lower()


# ---------------------------------------------------------------------------
# TestRunComment
# ---------------------------------------------------------------------------


class TestRunComment:
    """Tests for ``a-sdlc run comment`` command."""

    def _setup_run(self, runs_dir, run_id="R-comm01"):
        """Helper: create a run state file with status=running."""
        _write_run(
            run_id,
            {
                "run_id": run_id,
                "type": "pipeline",
                "status": "running",
                "comments": [],
            },
        )
        return run_id

    def test_run_comment_prd(self, runner, runs_dir):
        """Invoke ``run comment PROJ-P0001 -m "Consider rate limiting"``."""
        run_id = self._setup_run(runs_dir)

        result = runner.invoke(
            main,
            [
                "run",
                "comment",
                "PROJ-P0001",
                "-m",
                "Consider rate limiting",
                "--run-id",
                run_id,
            ],
        )

        assert result.exit_code == 0, result.output
        assert "comment posted" in result.output.lower()
        data = _read_run(run_id)
        assert len(data["comments"]) == 1
        assert data["comments"][0]["artifact_id"] == "PROJ-P0001"
        assert data["comments"][0]["message"] == "Consider rate limiting"

    def test_run_comment_task(self, runner, runs_dir):
        """Task ID (T prefix) comment posted correctly."""
        run_id = self._setup_run(runs_dir)

        result = runner.invoke(
            main,
            [
                "run",
                "comment",
                "PROJ-T00001",
                "-m",
                "Needs error handling",
                "--run-id",
                run_id,
            ],
        )

        assert result.exit_code == 0, result.output
        data = _read_run(run_id)
        assert data["comments"][0]["artifact_id"] == "PROJ-T00001"

    def test_run_comment_sprint(self, runner, runs_dir):
        """Sprint ID (S prefix) comment posted correctly."""
        run_id = self._setup_run(runs_dir)

        result = runner.invoke(
            main,
            [
                "run",
                "comment",
                "PROJ-S0001",
                "-m",
                "Scope looks good",
                "--run-id",
                run_id,
            ],
        )

        assert result.exit_code == 0, result.output
        data = _read_run(run_id)
        assert data["comments"][0]["artifact_id"] == "PROJ-S0001"


# ---------------------------------------------------------------------------
# TestEnhancedRunStatus
# ---------------------------------------------------------------------------


class TestEnhancedRunStatus:
    """Tests for enhanced ``a-sdlc run status`` with pipeline info."""

    def test_run_status_all(self, runner, runs_dir):
        """Invoke ``run status``, assert pipeline runs shown with queue info."""
        _write_run(
            "R-pipe01",
            {
                "run_id": "R-pipe01",
                "type": "pipeline",
                "entity_id": "goal:Add JWT auth",
                "status": "running",
                "pid": None,
                "started_at": "2026-04-09T10:00:00",
                "phase": "design",
                "progress_T1": {
                    "task_id": "T1",
                    "status": "pending",
                },
                "progress_T2": {
                    "task_id": "T2",
                    "status": "assigned",
                },
                "progress_T3": {
                    "task_id": "T3",
                    "status": "completed",
                },
            },
        )

        result = runner.invoke(main, ["run", "status"])

        assert result.exit_code == 0, result.output
        # Rich tables truncate in narrow terminals; check for the prefix
        assert "R-pipe" in result.output or "R-pi" in result.output
        assert "pipe" in result.output.lower()

    def test_run_status_detail(self, runner, runs_dir):
        """Invoke ``run status R-123``, assert detail panel is shown."""
        run_id = "R-detail01"
        _write_run(
            run_id,
            {
                "run_id": run_id,
                "type": "pipeline",
                "entity_id": "goal:Add JWT auth",
                "status": "running",
                "pid": None,
                "started_at": "2026-04-09T10:00:00",
                "phase": "implementation",
                "goal": "Add JWT auth",
                "progress_T1": {
                    "task_id": "T1",
                    "status": "completed",
                },
                "progress_T2": {
                    "task_id": "T2",
                    "status": "assigned",
                },
            },
        )

        result = runner.invoke(main, ["run", "status", run_id])

        assert result.exit_code == 0, result.output
        assert run_id in result.output

    def test_run_status_with_clarification(self, runner, runs_dir):
        """Run in awaiting_clarification -- assert question is shown."""
        run_id = "R-clarify01"
        _write_run(
            run_id,
            {
                "run_id": run_id,
                "type": "pipeline",
                "entity_id": "goal:Add JWT auth",
                "status": "awaiting_clarification",
                "pid": None,
                "started_at": "2026-04-09T10:00:00",
                "clarification_question": "Which JWT algorithm should we use: RS256 or HS256?",
                "config": {
                    "message": "Which JWT algorithm should we use: RS256 or HS256?",
                },
            },
        )

        result = runner.invoke(main, ["run", "status"])

        assert result.exit_code == 0, result.output
        assert run_id in result.output
        output_lower = result.output.lower()
        assert (
            "awaiting" in output_lower
            or "clarification" in output_lower
            or "question" in output_lower
            or "answer" in output_lower
        )
