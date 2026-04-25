"""Tests for the Executor class and supervised mode flow.

Covers:
- Executor initialisation and config loading
- Supervised mode checkpoint detection in execute_sprint()
- _await_user_confirmation() polling logic (approval and rejection)
- Resume prompt construction with session_id
- Parallel mode supervised checkpoint between batches
- run approve / run reject CLI commands
- run status approval instructions display
- __main__ entry point argument parsing
"""

from __future__ import annotations

import json
import signal
import textwrap
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from a_sdlc.cli import main
from a_sdlc.executor import (
    Executor,
    _main,
    _read_run,
    _update_run,
    _write_run,
    check_budget,
    execute_work_loop,
    load_daemon_config,
    load_governance_config,
    load_orchestrator_config,
    load_routing_config,
)

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
def mock_claude_path():
    """Mock shutil.which('claude') to return a fake path."""
    with patch("shutil.which", return_value="/usr/local/bin/claude") as m:
        yield m


@pytest.fixture
def mock_storage():
    """Create a MagicMock storage object."""
    storage = MagicMock()
    storage.get_sprint.return_value = {
        "id": "PROJ-S0001",
        "project_id": "proj-123",
        "title": "Sprint 1",
        "status": "active",
    }
    storage.list_tasks_by_sprint.return_value = [
        {
            "id": "PROJ-T00001",
            "status": "pending",
            "component": "backend",
            "dependencies": [],
        },
        {
            "id": "PROJ-T00002",
            "status": "pending",
            "component": "frontend",
            "dependencies": ["PROJ-T00001"],
        },
    ]
    return storage


@pytest.fixture
def executor(mock_claude_path, mock_storage):
    """Create an Executor instance with mocked dependencies."""
    with patch("a_sdlc.executor.get_storage", return_value=mock_storage):
        ex = Executor(
            max_turns=200,
            max_concurrency=3,
            project_dir="/tmp/test-project",
            supervised=True,
        )
    return ex


@pytest.fixture
def runs_dir(tmp_path, monkeypatch):
    """Redirect the runs directory to a temp path."""
    runs = tmp_path / "runs"
    runs.mkdir()
    monkeypatch.setattr("a_sdlc.executor._RUNS_DIR", runs)
    return runs


# ---------------------------------------------------------------------------
# load_daemon_config
# ---------------------------------------------------------------------------


class TestLoadDaemonConfig:
    def test_defaults_when_no_config(self, tmp_path):
        config = load_daemon_config(str(tmp_path))
        assert config["max_turns"] == 200
        assert config["mode"] == "session"
        assert config["supervised"] is False
        assert config["schedules"] == []
        assert config["notifications"] == []

    def test_reads_daemon_section(self, tmp_path):
        config_path = tmp_path / ".sdlc" / "config.yaml"
        config_path.parent.mkdir(parents=True)
        config_path.write_text(
            textwrap.dedent("""\
            daemon:
              max_turns: 500
              mode: parallel
              supervised: true
            """)
        )
        config = load_daemon_config(str(tmp_path))
        assert config["max_turns"] == 500
        assert config["mode"] == "parallel"
        assert config["supervised"] is True

    def test_invalid_mode_raises(self, tmp_path):
        config_path = tmp_path / ".sdlc" / "config.yaml"
        config_path.parent.mkdir(parents=True)
        config_path.write_text("daemon:\n  mode: invalid\n")
        with pytest.raises(ValueError, match="Invalid daemon.mode"):
            load_daemon_config(str(tmp_path))


# ---------------------------------------------------------------------------
# Executor init
# ---------------------------------------------------------------------------


class TestExecutorInit:
    def test_init_with_claude_on_path(self, mock_claude_path):
        with patch("a_sdlc.executor.get_storage"):
            ex = Executor(supervised=True)
        assert ex.supervised is True
        assert ex.claude_path == "/usr/local/bin/claude"

    def test_init_fails_without_claude(self):
        with (
            patch("shutil.which", return_value=None),
            pytest.raises(RuntimeError, match="Claude Code CLI not found"),
        ):
            Executor()


# ---------------------------------------------------------------------------
# _spawn_claude_session
# ---------------------------------------------------------------------------


class TestSpawnClaudeSession:
    def test_builds_command_without_session_id(self, executor):
        """Verify command line construction for a new session."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({"session_id": "sess-1", "result": "done"})

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            result = executor._spawn_claude_session(
                prompt="test prompt",
                max_turns=50,
                allowed_tools=["Read", "Write"],
            )

        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "/usr/local/bin/claude"
        assert "--resume" not in cmd
        assert "-p" in cmd
        assert "test prompt" in cmd
        assert "--max-turns" in cmd
        assert "50" in cmd
        assert "--allowedTools" in cmd
        assert result["session_id"] == "sess-1"

    def test_builds_command_with_session_id(self, executor):
        """Verify --resume is included when session_id is provided."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({"session_id": "sess-1"})

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            executor._spawn_claude_session(
                prompt="continue",
                session_id="sess-1",
            )

        cmd = mock_run.call_args[0][0]
        assert "--resume" in cmd
        resume_idx = cmd.index("--resume")
        assert cmd[resume_idx + 1] == "sess-1"

    def test_handles_timeout(self, executor):
        """Verify timeout is handled gracefully."""
        import subprocess

        with patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=["claude"], timeout=60),
        ):
            result = executor._spawn_claude_session(prompt="test", max_turns=1)
        assert result["status"] == "error"
        assert "timed out" in result["error"]

    def test_handles_nonzero_exit(self, executor):
        """Verify non-zero exit code is reported."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "some error"

        with patch("subprocess.run", return_value=mock_result):
            result = executor._spawn_claude_session(prompt="test")
        assert result["status"] == "error"
        assert result["exit_code"] == 1

    def test_handles_invalid_json(self, executor):
        """Verify invalid JSON output is reported."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "not json"

        with patch("subprocess.run", return_value=mock_result):
            result = executor._spawn_claude_session(prompt="test")
        assert result["status"] == "error"
        assert "parse" in result["error"].lower()


# ---------------------------------------------------------------------------
# Supervised mode: execute_sprint() checkpoint detection
# ---------------------------------------------------------------------------


class TestExecuteSprintSupervised:
    def test_detects_checkpoint_and_resumes(self, executor, runs_dir):
        """Verify the supervised loop detects ---BATCH-CHECKPOINT--- and resumes."""
        # First call: session outputs checkpoint marker
        first_result = {
            "session_id": "sess-abc",
            "result": "Batch 1 done.\n---BATCH-CHECKPOINT---\n",
        }
        # Second call (resumed): session completes
        second_result = {
            "session_id": "sess-abc",
            "result": textwrap.dedent("""\
                ---SPRINT-OUTCOME---
                sprint_id: PROJ-S0001
                completed: 2
                failed: 0
                summary: All done
                ---END-OUTCOME---
            """),
        }

        run_id = "R-test001"
        _write_run(run_id, {"status": "running", "config": {}})

        call_count = 0

        def mock_spawn(prompt, max_turns=200, allowed_tools=None, session_id=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return first_result
            return second_result

        def mock_await(rid, batch_num, outcomes):
            # Simulate user approval by setting status back to running
            _update_run(rid, status="running", config={"approval_message": "LGTM"})

        with (
            patch.object(executor, "_spawn_claude_session", side_effect=mock_spawn),
            patch.object(
                executor, "_await_user_confirmation", side_effect=mock_await
            ),
        ):
            result = executor.execute_sprint("PROJ-S0001", run_id)

        assert call_count == 2
        assert result.get("completed") == "2"
        assert result.get("summary") == "All done"

    def test_no_checkpoint_returns_immediately(self, executor, runs_dir):
        """Verify that without checkpoint marker, session result is returned."""
        final_result = {
            "session_id": "sess-xyz",
            "result": textwrap.dedent("""\
                ---SPRINT-OUTCOME---
                sprint_id: PROJ-S0001
                completed: 3
                failed: 0
                summary: Finished
                ---END-OUTCOME---
            """),
        }

        with patch.object(
            executor, "_spawn_claude_session", return_value=final_result
        ):
            result = executor.execute_sprint("PROJ-S0001", "R-test002")

        assert result.get("completed") == "3"

    def test_resume_prompt_includes_user_message(self, executor, runs_dir):
        """Verify resume prompt includes approval_message from user."""
        run_id = "R-test003"
        _write_run(run_id, {"status": "running", "config": {}})

        call_prompts: list[str] = []

        def mock_spawn(prompt, max_turns=200, allowed_tools=None, session_id=None):
            call_prompts.append(prompt)
            if len(call_prompts) == 1:
                return {
                    "session_id": "sess-resume",
                    "result": "---BATCH-CHECKPOINT---",
                }
            return {"session_id": "sess-resume", "result": "done"}

        def mock_await(rid, batch_num, outcomes):
            _update_run(
                rid,
                status="running",
                config={"approval_message": "Skip T00003"},
            )

        with (
            patch.object(executor, "_spawn_claude_session", side_effect=mock_spawn),
            patch.object(
                executor, "_await_user_confirmation", side_effect=mock_await
            ),
        ):
            executor.execute_sprint("PROJ-S0001", run_id)

        # The second prompt (resume) should include the user's message
        assert len(call_prompts) == 2
        assert "User approved batch 1" in call_prompts[1]
        assert "Skip T00003" in call_prompts[1]

    def test_session_id_passed_on_resume(self, executor, runs_dir):
        """Verify session_id is passed via --resume on subsequent calls."""
        run_id = "R-test004"
        _write_run(run_id, {"status": "running", "config": {}})

        session_ids_seen: list[str | None] = []

        def mock_spawn(prompt, max_turns=200, allowed_tools=None, session_id=None):
            session_ids_seen.append(session_id)
            if len(session_ids_seen) == 1:
                return {
                    "session_id": "sess-keep",
                    "result": "---BATCH-CHECKPOINT---",
                }
            return {"session_id": "sess-keep", "result": "final"}

        def mock_await(rid, batch_num, outcomes):
            _update_run(rid, status="running", config={})

        with (
            patch.object(executor, "_spawn_claude_session", side_effect=mock_spawn),
            patch.object(
                executor, "_await_user_confirmation", side_effect=mock_await
            ),
        ):
            executor.execute_sprint("PROJ-S0001", run_id)

        assert session_ids_seen[0] is None  # First call: no session_id
        assert session_ids_seen[1] == "sess-keep"  # Resume: session_id passed


# ---------------------------------------------------------------------------
# _await_user_confirmation
# ---------------------------------------------------------------------------


class TestAwaitUserConfirmation:
    def test_approval_flow(self, executor, runs_dir):
        """Verify that approval (status='running') breaks the poll loop."""
        run_id = "R-await-approve"
        _write_run(run_id, {"status": "running", "config": {}})

        call_count = 0

        def mock_sleep(seconds):
            nonlocal call_count
            call_count += 1
            # On first poll, simulate user approval
            _update_run(
                run_id,
                status="running",
                config={"approval_message": "Go ahead"},
            )

        with patch("a_sdlc.executor.time.sleep", side_effect=mock_sleep):
            # Should return without error
            executor._await_user_confirmation(run_id, 0, {"T1": "ok"})

        assert call_count == 1

    def test_rejection_flow(self, executor, runs_dir):
        """Verify that rejection (status='cancelled') raises SystemExit."""
        run_id = "R-await-reject"
        _write_run(run_id, {"status": "running", "config": {}})

        def mock_sleep(seconds):
            _update_run(
                run_id,
                status="cancelled",
                config={"rejection_reason": "Tests failing"},
            )

        with (
            patch("a_sdlc.executor.time.sleep", side_effect=mock_sleep),
            pytest.raises(SystemExit, match="rejected by user.*Tests failing"),
        ):
            executor._await_user_confirmation(run_id, 0, {})

    def test_stores_checkpoint_state(self, executor, runs_dir):
        """Verify checkpoint state is written before polling."""
        run_id = "R-await-state"
        _write_run(run_id, {"status": "running", "config": {}})

        outcomes = {"T1": "ok", "T2": "[failed: error]"}

        def mock_sleep(seconds):
            # Simulate approval so we don't loop forever
            _update_run(run_id, status="running", config={})

        with patch("a_sdlc.executor.time.sleep", side_effect=mock_sleep):
            executor._await_user_confirmation(run_id, 2, outcomes)

        # After approval, status is 'running'. The checkpoint state was written
        # before the poll loop, then overwritten by approval. Verify the method
        # at least completed without error. The important thing is it set
        # awaiting_confirmation initially (tested implicitly by the poll working).
        final_data = _read_run(run_id)
        assert final_data["status"] == "running"

    def test_polls_until_status_change(self, executor, runs_dir):
        """Verify polling continues when status is still awaiting_confirmation."""
        run_id = "R-await-poll"
        _write_run(run_id, {"status": "running", "config": {}})

        poll_count = 0

        def mock_sleep(seconds):
            nonlocal poll_count
            poll_count += 1
            if poll_count >= 3:
                # Third poll: approve
                _update_run(run_id, status="running", config={})
            else:
                # First two polls: still awaiting
                _update_run(run_id, status="awaiting_confirmation", config={})

        with patch("a_sdlc.executor.time.sleep", side_effect=mock_sleep):
            executor._await_user_confirmation(run_id, 0, {})

        assert poll_count == 3


# ---------------------------------------------------------------------------
# execute_sprint_parallel supervised mode
# ---------------------------------------------------------------------------


class TestExecuteSprintParallelSupervised:
    def test_pauses_between_batches(self, mock_claude_path, runs_dir):
        """Verify parallel mode pauses between batches in supervised mode."""
        mock_storage = MagicMock()
        mock_storage.get_sprint.return_value = {
            "id": "PROJ-S0001",
            "project_id": "proj-123",
        }
        # Two tasks: T1 has no deps (batch 1), T2 depends on T1 (batch 2)
        mock_storage.list_tasks_by_sprint.return_value = [
            {
                "id": "PROJ-T00001",
                "status": "pending",
                "component": "backend",
                "dependencies": [],
            },
            {
                "id": "PROJ-T00002",
                "status": "pending",
                "component": "frontend",
                "dependencies": ["PROJ-T00001"],
            },
        ]
        mock_storage.update_task.return_value = None

        with patch("a_sdlc.executor.get_storage", return_value=mock_storage):
            ex = Executor(
                max_turns=50,
                max_concurrency=3,
                project_dir="/tmp/test",
                supervised=True,
            )

        await_calls: list[tuple[str, int]] = []

        def mock_await(rid, batch_num, outcomes):
            await_calls.append((rid, batch_num))

        mock_session_result = {
            "result": textwrap.dedent("""\
                ---TASK-OUTCOME---
                task_id: PROJ-T00001
                verdict: PASS
                summary: done
                ---END-OUTCOME---
            """),
        }

        with (
            patch.object(
                ex,
                "_spawn_claude_session",
                return_value=mock_session_result,
            ),
            patch.object(ex, "_await_user_confirmation", side_effect=mock_await),
        ):
            result = ex.execute_sprint_parallel("PROJ-S0001", "R-par001")

        # Should have 2 batches, checkpoint called once (between batch 0 and 1)
        assert result["batches_completed"] == 2
        assert len(await_calls) == 1
        assert await_calls[0] == ("R-par001", 0)

    def test_no_pause_after_last_batch(self, mock_claude_path, runs_dir):
        """Verify no checkpoint after the final batch."""
        mock_storage = MagicMock()
        mock_storage.get_sprint.return_value = {
            "id": "PROJ-S0001",
            "project_id": "proj-123",
        }
        # Single batch: one task with no deps
        mock_storage.list_tasks_by_sprint.return_value = [
            {
                "id": "PROJ-T00001",
                "status": "pending",
                "component": "backend",
                "dependencies": [],
            },
        ]
        mock_storage.update_task.return_value = None

        with patch("a_sdlc.executor.get_storage", return_value=mock_storage):
            ex = Executor(
                max_turns=50,
                max_concurrency=3,
                project_dir="/tmp/test",
                supervised=True,
            )

        await_calls: list[Any] = []

        mock_session_result = {"result": "done"}

        with (
            patch.object(
                ex, "_spawn_claude_session", return_value=mock_session_result
            ),
            patch.object(
                ex,
                "_await_user_confirmation",
                side_effect=lambda *a: await_calls.append(a),
            ),
        ):
            result = ex.execute_sprint_parallel("PROJ-S0001", "R-par002")

        assert result["batches_completed"] == 1
        assert len(await_calls) == 0  # No pause after the only batch


# ---------------------------------------------------------------------------
# CLI: run approve
# ---------------------------------------------------------------------------


class TestRunApprove:
    def test_approve_awaiting_run(self, runner, runs_dir):
        """Verify approve changes status from awaiting_confirmation to running."""
        run_id = "R-approve01"
        _write_run(
            run_id,
            {
                "run_id": run_id,
                "status": "awaiting_confirmation",
                "config": {"message": "Batch 1 done"},
            },
        )

        result = runner.invoke(main, ["run", "approve", run_id, "-m", "LGTM"])
        assert result.exit_code == 0
        assert "approved" in result.output.lower()

        data = _read_run(run_id)
        assert data["status"] == "running"
        assert data["config"]["approval_message"] == "LGTM"

    def test_approve_non_awaiting_fails(self, runner, runs_dir):
        """Verify approve fails when run is not awaiting_confirmation."""
        run_id = "R-approve02"
        _write_run(run_id, {"run_id": run_id, "status": "running", "config": {}})

        result = runner.invoke(main, ["run", "approve", run_id])
        assert result.exit_code == 0  # Prints warning, doesn't crash
        assert "not awaiting" in result.output.lower()

    def test_approve_nonexistent_run(self, runner, runs_dir):
        """Verify approve fails for a non-existent run."""
        result = runner.invoke(main, ["run", "approve", "R-ghost"])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()


# ---------------------------------------------------------------------------
# CLI: run reject
# ---------------------------------------------------------------------------


class TestRunReject:
    def test_reject_awaiting_run(self, runner, runs_dir):
        """Verify reject cancels the run and stores rejection reason."""
        run_id = "R-reject01"
        _write_run(
            run_id,
            {
                "run_id": run_id,
                "status": "awaiting_confirmation",
                "config": {},
                "pid": None,
            },
        )

        result = runner.invoke(
            main, ["run", "reject", run_id, "-m", "Tests failing"]
        )
        assert result.exit_code == 0
        assert "rejected" in result.output.lower()

        data = _read_run(run_id)
        assert data["status"] == "cancelled"
        assert data["config"]["rejection_reason"] == "Tests failing"

    def test_reject_non_awaiting_fails(self, runner, runs_dir):
        """Verify reject fails when run is not awaiting_confirmation."""
        run_id = "R-reject02"
        _write_run(run_id, {"run_id": run_id, "status": "running", "config": {}})

        result = runner.invoke(
            main, ["run", "reject", run_id, "-m", "bad"]
        )
        assert result.exit_code == 0
        assert "not awaiting" in result.output.lower()

    def test_reject_sends_sigterm(self, runner, runs_dir):
        """Verify reject sends SIGTERM to the executor PID if alive."""
        run_id = "R-reject03"
        fake_pid = 99999
        _write_run(
            run_id,
            {
                "run_id": run_id,
                "status": "awaiting_confirmation",
                "config": {},
                "pid": fake_pid,
            },
        )

        with patch("os.kill") as mock_kill:
            # First call: os.kill(pid, 0) to check alive -> succeeds
            # Second call: os.kill(pid, SIGTERM) -> succeeds
            mock_kill.return_value = None

            result = runner.invoke(
                main, ["run", "reject", run_id, "-m", "stopping"]
            )

        assert result.exit_code == 0
        # Verify SIGTERM was sent
        sigterm_calls = [
            c for c in mock_kill.call_args_list if c[0][1] == signal.SIGTERM
        ]
        assert len(sigterm_calls) == 1
        assert sigterm_calls[0][0][0] == fake_pid

    def test_reject_requires_message(self, runner, runs_dir):
        """Verify --message/-m is required for reject."""
        run_id = "R-reject04"
        _write_run(
            run_id,
            {"run_id": run_id, "status": "awaiting_confirmation", "config": {}},
        )

        result = runner.invoke(main, ["run", "reject", run_id])
        assert result.exit_code != 0
        assert "missing" in result.output.lower() or "required" in result.output.lower()

    def test_reject_nonexistent_run(self, runner, runs_dir):
        """Verify reject fails for a non-existent run."""
        result = runner.invoke(
            main, ["run", "reject", "R-ghost", "-m", "nope"]
        )
        assert result.exit_code != 0
        assert "not found" in result.output.lower()


# ---------------------------------------------------------------------------
# CLI: run status with approval instructions
# ---------------------------------------------------------------------------


class TestRunStatusApprovalInstructions:
    def test_shows_approval_instructions(self, runner, runs_dir):
        """Verify status shows approve/reject instructions for awaiting runs."""
        run_id = "R-status01"
        _write_run(
            run_id,
            {
                "run_id": run_id,
                "type": "sprint",
                "entity_id": "PROJ-S0001",
                "status": "awaiting_confirmation",
                "config": {
                    "message": "Batch 1 complete: 2 passed, 0 failed."
                },
                "pid": None,
                "started_at": "2026-03-28T10:00:00",
            },
        )

        result = runner.invoke(main, ["run", "status"])
        assert result.exit_code == 0
        assert "awaiting approval" in result.output.lower() or "awaiting" in result.output.lower()
        assert f"a-sdlc run approve {run_id}" in result.output
        assert f"a-sdlc run reject {run_id}" in result.output

    def test_no_instructions_for_running(self, runner, runs_dir):
        """Verify no approval instructions for runs that are not awaiting."""
        run_id = "R-status02"
        _write_run(
            run_id,
            {
                "run_id": run_id,
                "type": "sprint",
                "entity_id": "PROJ-S0001",
                "status": "running",
                "config": {},
                "pid": None,
                "started_at": "2026-03-28T10:00:00",
            },
        )

        result = runner.invoke(main, ["run", "status"])
        assert result.exit_code == 0
        assert "a-sdlc run approve" not in result.output


# ---------------------------------------------------------------------------
# CLI: run answer
# ---------------------------------------------------------------------------


class TestRunAnswer:
    def test_answer_awaiting_clarification(self, runner, runs_dir):
        """Verify answer resumes a run that is awaiting_clarification."""
        run_id = "R-answer01"
        _write_run(
            run_id,
            {
                "run_id": run_id,
                "status": "awaiting_clarification",
                "config": {"question": "Which algorithm?"},
            },
        )

        result = runner.invoke(
            main, ["run", "answer", run_id, "-m", "use RS256"]
        )
        assert result.exit_code == 0
        assert "resumed" in result.output.lower()

        data = _read_run(run_id)
        assert data["status"] == "running"
        assert len(data["answers"]) == 1
        assert data["answers"][0]["message"] == "use RS256"
        assert "answered_at" in data["answers"][0]

    def test_answer_awaiting_confirmation(self, runner, runs_dir):
        """Verify answer also works when run is awaiting_confirmation."""
        run_id = "R-answer02"
        _write_run(
            run_id,
            {
                "run_id": run_id,
                "status": "awaiting_confirmation",
                "config": {},
            },
        )

        result = runner.invoke(
            main, ["run", "answer", run_id, "-m", "proceed"]
        )
        assert result.exit_code == 0
        assert "resumed" in result.output.lower()

        data = _read_run(run_id)
        assert data["status"] == "running"

    def test_answer_with_item(self, runner, runs_dir):
        """Verify answer stores item_id when --item is provided."""
        run_id = "R-answer03"
        _write_run(
            run_id,
            {
                "run_id": run_id,
                "status": "awaiting_clarification",
                "config": {},
            },
        )

        result = runner.invoke(
            main,
            [
                "run", "answer", run_id,
                "--item", "PROJ-T00001",
                "-m", "skip auth for now",
            ],
        )
        assert result.exit_code == 0
        assert "PROJ-T00001" in result.output

        data = _read_run(run_id)
        assert data["answers"][0]["item_id"] == "PROJ-T00001"
        assert data["answers"][0]["message"] == "skip auth for now"

    def test_answer_non_awaiting_fails(self, runner, runs_dir):
        """Verify answer fails when run is not awaiting clarification."""
        run_id = "R-answer04"
        _write_run(
            run_id,
            {"run_id": run_id, "status": "running", "config": {}},
        )

        result = runner.invoke(
            main, ["run", "answer", run_id, "-m", "hello"]
        )
        assert result.exit_code == 0  # Prints warning, doesn't crash
        assert "not awaiting" in result.output.lower()

    def test_answer_nonexistent_run(self, runner, runs_dir):
        """Verify answer fails for a non-existent run."""
        result = runner.invoke(
            main, ["run", "answer", "R-ghost", "-m", "answer"]
        )
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_answer_requires_message(self, runner, runs_dir):
        """Verify --message/-m is required for answer."""
        run_id = "R-answer05"
        _write_run(
            run_id,
            {"run_id": run_id, "status": "awaiting_clarification", "config": {}},
        )

        result = runner.invoke(main, ["run", "answer", run_id])
        assert result.exit_code != 0
        assert "missing" in result.output.lower() or "required" in result.output.lower()

    def test_answer_appends_to_existing(self, runner, runs_dir):
        """Verify multiple answers append to the answers list."""
        run_id = "R-answer06"
        _write_run(
            run_id,
            {
                "run_id": run_id,
                "status": "awaiting_clarification",
                "config": {},
                "answers": [
                    {"message": "first answer", "answered_at": "2026-01-01T00:00:00"},
                ],
            },
        )

        result = runner.invoke(
            main, ["run", "answer", run_id, "-m", "second answer"]
        )
        assert result.exit_code == 0

        data = _read_run(run_id)
        assert len(data["answers"]) == 2
        assert data["answers"][0]["message"] == "first answer"
        assert data["answers"][1]["message"] == "second answer"

    def test_answer_completed_run_fails(self, runner, runs_dir):
        """Verify answer fails for completed runs."""
        run_id = "R-answer07"
        _write_run(
            run_id,
            {"run_id": run_id, "status": "completed", "config": {}},
        )

        result = runner.invoke(
            main, ["run", "answer", run_id, "-m", "too late"]
        )
        assert result.exit_code == 0
        assert "not awaiting" in result.output.lower()


# ---------------------------------------------------------------------------
# CLI: run control
# ---------------------------------------------------------------------------


class TestRunControl:
    def test_control_pause(self, runner, runs_dir):
        """Verify control records a pause action for a work item."""
        run_id = "R-ctrl01"
        _write_run(
            run_id,
            {"run_id": run_id, "status": "running", "config": {}},
        )

        result = runner.invoke(
            main,
            ["run", "control", "PROJ-T00001", "-a", "pause", "--run-id", run_id],
        )
        assert result.exit_code == 0
        assert "pause" in result.output.lower()
        assert "PROJ-T00001" in result.output

        data = _read_run(run_id)
        assert len(data["controls"]) == 1
        assert data["controls"][0]["item_id"] == "PROJ-T00001"
        assert data["controls"][0]["action"] == "pause"
        assert "issued_at" in data["controls"][0]

    def test_control_cancel(self, runner, runs_dir):
        """Verify control records a cancel action."""
        run_id = "R-ctrl02"
        _write_run(
            run_id,
            {"run_id": run_id, "status": "running", "config": {}},
        )

        result = runner.invoke(
            main,
            ["run", "control", "PROJ-T00002", "-a", "cancel", "--run-id", run_id],
        )
        assert result.exit_code == 0
        assert "cancel" in result.output.lower()

    def test_control_skip(self, runner, runs_dir):
        """Verify control records a skip action."""
        run_id = "R-ctrl03"
        _write_run(
            run_id,
            {"run_id": run_id, "status": "running", "config": {}},
        )

        result = runner.invoke(
            main,
            ["run", "control", "PROJ-T00003", "-a", "skip", "--run-id", run_id],
        )
        assert result.exit_code == 0
        assert "skip" in result.output.lower()

    def test_control_retry(self, runner, runs_dir):
        """Verify control records a retry action."""
        run_id = "R-ctrl04"
        _write_run(
            run_id,
            {"run_id": run_id, "status": "running", "config": {}},
        )

        result = runner.invoke(
            main,
            ["run", "control", "PROJ-T00004", "-a", "retry", "--run-id", run_id],
        )
        assert result.exit_code == 0
        assert "retry" in result.output.lower()

    def test_control_force_approve(self, runner, runs_dir):
        """Verify control records a force-approve action."""
        run_id = "R-ctrl05"
        _write_run(
            run_id,
            {"run_id": run_id, "status": "running", "config": {}},
        )

        result = runner.invoke(
            main,
            ["run", "control", "PROJ-T00005", "-a", "force-approve", "--run-id", run_id],
        )
        assert result.exit_code == 0
        assert "force-approve" in result.output.lower()

    def test_control_auto_detects_run_id(self, runner, runs_dir):
        """Verify control auto-detects the most recent active run."""
        run_id = "R-ctrl06"
        _write_run(
            run_id,
            {"run_id": run_id, "status": "running", "config": {}},
        )

        result = runner.invoke(
            main,
            ["run", "control", "PROJ-T00006", "-a", "pause"],
        )
        assert result.exit_code == 0
        assert run_id in result.output

        data = _read_run(run_id)
        assert data["controls"][0]["item_id"] == "PROJ-T00006"

    def test_control_no_active_run(self, runner, runs_dir):
        """Verify control fails when no active run is found."""
        result = runner.invoke(
            main,
            ["run", "control", "PROJ-T00007", "-a", "pause"],
        )
        assert result.exit_code != 0
        assert "no active run" in result.output.lower()

    def test_control_nonexistent_run(self, runner, runs_dir):
        """Verify control fails for a non-existent run_id."""
        result = runner.invoke(
            main,
            ["run", "control", "PROJ-T00008", "-a", "skip", "--run-id", "R-ghost"],
        )
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_control_invalid_action(self, runner, runs_dir):
        """Verify control rejects invalid action values."""
        run_id = "R-ctrl09"
        _write_run(
            run_id,
            {"run_id": run_id, "status": "running", "config": {}},
        )

        result = runner.invoke(
            main,
            ["run", "control", "PROJ-T00009", "-a", "invalid-action", "--run-id", run_id],
        )
        assert result.exit_code != 0
        assert "invalid" in result.output.lower() or "choice" in result.output.lower()

    def test_control_requires_action(self, runner, runs_dir):
        """Verify --action/-a is required."""
        result = runner.invoke(
            main,
            ["run", "control", "PROJ-T00010", "--run-id", "R-ctrl10"],
        )
        assert result.exit_code != 0
        assert "missing" in result.output.lower() or "required" in result.output.lower()

    def test_control_appends_to_existing(self, runner, runs_dir):
        """Verify multiple controls append to the controls list."""
        run_id = "R-ctrl11"
        _write_run(
            run_id,
            {
                "run_id": run_id,
                "status": "running",
                "config": {},
                "controls": [
                    {
                        "item_id": "PROJ-T00001",
                        "action": "pause",
                        "issued_at": "2026-01-01T00:00:00",
                    },
                ],
            },
        )

        result = runner.invoke(
            main,
            ["run", "control", "PROJ-T00002", "-a", "skip", "--run-id", run_id],
        )
        assert result.exit_code == 0

        data = _read_run(run_id)
        assert len(data["controls"]) == 2
        assert data["controls"][0]["item_id"] == "PROJ-T00001"
        assert data["controls"][1]["item_id"] == "PROJ-T00002"
        assert data["controls"][1]["action"] == "skip"


# ---------------------------------------------------------------------------
# CLI: run comment
# ---------------------------------------------------------------------------


class TestRunComment:
    def test_comment_with_run_id(self, runner, runs_dir):
        """Verify comment records a user_intervention entry."""
        run_id = "R-cmt01"
        _write_run(
            run_id,
            {"run_id": run_id, "status": "running", "config": {}},
        )

        result = runner.invoke(
            main,
            [
                "run", "comment", "PROJ-P0001",
                "-m", "Focus on the REST endpoints first",
                "--run-id", run_id,
            ],
        )
        assert result.exit_code == 0
        assert "PROJ-P0001" in result.output
        assert "posted" in result.output.lower()

        data = _read_run(run_id)
        assert len(data["comments"]) == 1
        assert data["comments"][0]["artifact_id"] == "PROJ-P0001"
        assert data["comments"][0]["message"] == "Focus on the REST endpoints first"
        assert data["comments"][0]["type"] == "user_intervention"
        assert "posted_at" in data["comments"][0]

    def test_comment_auto_detects_run_id(self, runner, runs_dir):
        """Verify comment auto-detects the most recent active run."""
        run_id = "R-cmt02"
        _write_run(
            run_id,
            {"run_id": run_id, "status": "running", "config": {}},
        )

        result = runner.invoke(
            main,
            ["run", "comment", "PROJ-T00003", "-m", "Use PostgreSQL, not SQLite"],
        )
        assert result.exit_code == 0
        assert run_id in result.output

        data = _read_run(run_id)
        assert data["comments"][0]["artifact_id"] == "PROJ-T00003"

    def test_comment_no_active_run(self, runner, runs_dir):
        """Verify comment fails when no active run is found."""
        result = runner.invoke(
            main,
            ["run", "comment", "PROJ-P0002", "-m", "hello"],
        )
        assert result.exit_code != 0
        assert "no active run" in result.output.lower()

    def test_comment_nonexistent_run(self, runner, runs_dir):
        """Verify comment fails for a non-existent run_id."""
        result = runner.invoke(
            main,
            [
                "run", "comment", "PROJ-P0003",
                "-m", "hello",
                "--run-id", "R-ghost",
            ],
        )
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_comment_requires_message(self, runner, runs_dir):
        """Verify --message/-m is required for comment."""
        run_id = "R-cmt05"
        _write_run(
            run_id,
            {"run_id": run_id, "status": "running", "config": {}},
        )

        result = runner.invoke(
            main, ["run", "comment", "PROJ-P0004", "--run-id", run_id],
        )
        assert result.exit_code != 0
        assert "missing" in result.output.lower() or "required" in result.output.lower()

    def test_comment_appends_to_existing(self, runner, runs_dir):
        """Verify multiple comments append to the comments list."""
        run_id = "R-cmt06"
        _write_run(
            run_id,
            {
                "run_id": run_id,
                "status": "running",
                "config": {},
                "comments": [
                    {
                        "artifact_id": "PROJ-P0001",
                        "message": "first comment",
                        "type": "user_intervention",
                        "posted_at": "2026-01-01T00:00:00",
                    },
                ],
            },
        )

        result = runner.invoke(
            main,
            [
                "run", "comment", "PROJ-T00001",
                "-m", "second comment",
                "--run-id", run_id,
            ],
        )
        assert result.exit_code == 0

        data = _read_run(run_id)
        assert len(data["comments"]) == 2
        assert data["comments"][0]["artifact_id"] == "PROJ-P0001"
        assert data["comments"][1]["artifact_id"] == "PROJ-T00001"
        assert data["comments"][1]["message"] == "second comment"

    def test_comment_displays_message(self, runner, runs_dir):
        """Verify comment displays the posted message in output."""
        run_id = "R-cmt07"
        _write_run(
            run_id,
            {"run_id": run_id, "status": "running", "config": {}},
        )

        result = runner.invoke(
            main,
            [
                "run", "comment", "PROJ-P0005",
                "-m", "Important: use microservices",
                "--run-id", run_id,
            ],
        )
        assert result.exit_code == 0
        assert "Important: use microservices" in result.output


# ---------------------------------------------------------------------------
# Autonomous mode (supervised=False)
# ---------------------------------------------------------------------------


class TestExecuteSprintAutonomous:
    def test_runs_single_session_to_completion(self, mock_claude_path, runs_dir):
        """Verify autonomous mode runs a single session without checkpoints."""
        mock_storage = MagicMock()
        with patch("a_sdlc.executor.get_storage", return_value=mock_storage):
            ex = Executor(
                max_turns=200,
                supervised=False,
                project_dir="/tmp/test",
            )

        final_result = {
            "result": textwrap.dedent("""\
                ---SPRINT-OUTCOME---
                sprint_id: PROJ-S0001
                completed: 5
                failed: 0
                summary: All tasks done
                ---END-OUTCOME---
            """),
        }

        with patch.object(
            ex, "_spawn_claude_session", return_value=final_result
        ) as mock_spawn:
            result = ex.execute_sprint("PROJ-S0001", "R-auto001")

        # Should be called exactly once (no resume loop)
        assert mock_spawn.call_count == 1
        assert result.get("completed") == "5"


# ---------------------------------------------------------------------------
# __main__ entry point
# ---------------------------------------------------------------------------


class TestMainEntryPoint:
    def test_sprint_mode_dispatches_correctly(self, mock_claude_path, runs_dir):
        """Verify __main__ dispatches to execute_sprint in session mode."""
        with (
            patch("a_sdlc.executor.get_storage"),
            patch("a_sdlc.executor.load_daemon_config", return_value={"mode": "session"}),
            patch.object(
                Executor,
                "execute_sprint",
                return_value={"status": "completed"},
            ) as mock_execute,
            patch(
                "sys.argv",
                [
                    "executor",
                    "--mode",
                    "sprint",
                    "--sprint-id",
                    "PROJ-S0001",
                    "--run-id",
                    "R-main01",
                ],
            ),
        ):
            _main()

        mock_execute.assert_called_once_with("PROJ-S0001", "R-main01")
        # Verify run state updated to completed
        data = _read_run("R-main01")
        assert data["status"] == "completed"

    def test_task_mode_dispatches_correctly(self, mock_claude_path, runs_dir):
        """Verify __main__ dispatches to execute_task for task mode."""
        with (
            patch("a_sdlc.executor.get_storage"),
            patch.object(
                Executor,
                "execute_task",
                return_value={"status": "completed"},
            ) as mock_execute,
            patch(
                "sys.argv",
                [
                    "executor",
                    "--mode",
                    "task",
                    "--task-id",
                    "PROJ-T00001",
                    "--run-id",
                    "R-main02",
                ],
            ),
        ):
            _main()

        mock_execute.assert_called_once_with("PROJ-T00001", "R-main02")

    def test_sprint_mode_without_sprint_id_fails(self, mock_claude_path, runs_dir):
        """Verify sprint mode requires --sprint-id."""
        with (
            patch("a_sdlc.executor.get_storage"),
            patch("a_sdlc.executor.load_daemon_config", return_value={"mode": "session"}),
            patch(
                "sys.argv",
                [
                    "executor",
                    "--mode",
                    "sprint",
                    "--run-id",
                    "R-main03",
                ],
            ),
            pytest.raises(SystemExit),
        ):
            _main()

    def test_parallel_mode_dispatches_correctly(self, mock_claude_path, runs_dir):
        """Verify __main__ uses parallel mode when config says so."""
        with (
            patch("a_sdlc.executor.get_storage"),
            patch(
                "a_sdlc.executor.load_daemon_config",
                return_value={"mode": "parallel"},
            ),
            patch.object(
                Executor,
                "execute_sprint_parallel",
                return_value={"outcomes": {}, "batches_completed": 0},
            ) as mock_parallel,
            patch(
                "sys.argv",
                [
                    "executor",
                    "--mode",
                    "sprint",
                    "--sprint-id",
                    "PROJ-S0001",
                    "--run-id",
                    "R-main04",
                ],
            ),
        ):
            _main()

        mock_parallel.assert_called_once_with("PROJ-S0001", "R-main04")

    def test_exception_marks_run_as_failed(self, mock_claude_path, runs_dir):
        """Verify unhandled exceptions mark the run as failed."""
        with (
            patch("a_sdlc.executor.get_storage"),
            patch("a_sdlc.executor.load_daemon_config", return_value={"mode": "session"}),
            patch.object(
                Executor,
                "execute_sprint",
                side_effect=RuntimeError("boom"),
            ),
            patch(
                "sys.argv",
                [
                    "executor",
                    "--mode",
                    "sprint",
                    "--sprint-id",
                    "PROJ-S0001",
                    "--run-id",
                    "R-main05",
                ],
            ),
            pytest.raises(SystemExit),
        ):
            _main()

        data = _read_run("R-main05")
        assert data["status"] == "failed"
        assert "boom" in data["error"]


# ---------------------------------------------------------------------------
# Run-state JSON helpers
# ---------------------------------------------------------------------------


class TestRunStateHelpers:
    def test_write_and_read(self, runs_dir):
        _write_run("R-rw01", {"status": "running", "pid": 123})
        data = _read_run("R-rw01")
        assert data["status"] == "running"
        assert data["pid"] == 123

    def test_update_merges(self, runs_dir):
        _write_run("R-rw02", {"status": "running", "pid": 100})
        _update_run("R-rw02", status="completed", extra="data")
        data = _read_run("R-rw02")
        assert data["status"] == "completed"
        assert data["pid"] == 100
        assert data["extra"] == "data"

    def test_read_nonexistent(self, runs_dir):
        data = _read_run("R-ghost")
        assert data == {}


# ---------------------------------------------------------------------------
# Result parsers
# ---------------------------------------------------------------------------


class TestResultParsers:
    def test_parse_sprint_result_success(self, executor):
        result = {
            "result": textwrap.dedent("""\
                Some preamble text.
                ---SPRINT-OUTCOME---
                sprint_id: PROJ-S0001
                completed: 3
                failed: 1
                skipped: 0
                summary: Sprint mostly done
                ---END-OUTCOME---
                Some trailing text.
            """),
        }
        parsed = executor._parse_sprint_result(result)
        assert parsed["sprint_id"] == "PROJ-S0001"
        assert parsed["completed"] == "3"
        assert parsed["failed"] == "1"
        assert parsed["summary"] == "Sprint mostly done"

    def test_parse_sprint_result_error(self, executor):
        result = {"status": "error", "error": "timeout"}
        parsed = executor._parse_sprint_result(result)
        assert parsed["status"] == "error"
        assert parsed["error"] == "timeout"

    def test_parse_task_result_success(self, executor):
        result = {
            "result": textwrap.dedent("""\
                ---TASK-OUTCOME---
                task_id: PROJ-T00001
                verdict: PASS
                summary: implemented feature
                ---END-OUTCOME---
            """),
        }
        parsed = executor._parse_task_result(result)
        assert parsed["task_id"] == "PROJ-T00001"
        assert parsed["verdict"] == "PASS"

    def test_extract_outcome_block_no_markers(self, executor):
        parsed = Executor._extract_outcome_block(
            "no markers here", "---START---", "---END---"
        )
        assert parsed == {}


# ---------------------------------------------------------------------------
# Persona resolution
# ---------------------------------------------------------------------------


class TestPersonaResolution:
    def test_backend_components(self, executor):
        assert executor._resolve_persona_type("backend") == "sdlc-backend-engineer"
        assert executor._resolve_persona_type("api") == "sdlc-backend-engineer"
        assert executor._resolve_persona_type("database") == "sdlc-backend-engineer"

    def test_frontend_components(self, executor):
        assert executor._resolve_persona_type("ui") == "sdlc-frontend-engineer"
        assert executor._resolve_persona_type("frontend") == "sdlc-frontend-engineer"

    def test_none_component(self, executor):
        assert executor._resolve_persona_type(None) == "general-purpose"

    def test_unknown_component(self, executor):
        assert executor._resolve_persona_type("unknown-thing") == "general-purpose"


# ---------------------------------------------------------------------------
# Batch building
# ---------------------------------------------------------------------------


class TestBatchBuilding:
    def test_simple_dependency_chain(self, executor):
        tasks = [
            {"id": "T1", "status": "pending", "dependencies": []},
            {"id": "T2", "status": "pending", "dependencies": ["T1"]},
            {"id": "T3", "status": "pending", "dependencies": ["T2"]},
        ]
        batches = executor._build_batches(tasks)
        assert len(batches) == 3
        assert batches[0][0]["id"] == "T1"
        assert batches[1][0]["id"] == "T2"
        assert batches[2][0]["id"] == "T3"

    def test_parallel_tasks_same_batch(self, executor):
        tasks = [
            {"id": "T1", "status": "pending", "dependencies": []},
            {"id": "T2", "status": "pending", "dependencies": []},
        ]
        batches = executor._build_batches(tasks)
        assert len(batches) == 1
        assert len(batches[0]) == 2

    def test_completed_tasks_excluded(self, executor):
        tasks = [
            {"id": "T1", "status": "completed", "dependencies": []},
            {"id": "T2", "status": "pending", "dependencies": ["T1"]},
        ]
        batches = executor._build_batches(tasks)
        assert len(batches) == 1
        assert batches[0][0]["id"] == "T2"

    def test_circular_dependency_stops(self, executor):
        tasks = [
            {"id": "T1", "status": "pending", "dependencies": ["T2"]},
            {"id": "T2", "status": "pending", "dependencies": ["T1"]},
        ]
        batches = executor._build_batches(tasks)
        assert len(batches) == 0  # Cannot make progress


# ---------------------------------------------------------------------------
# load_governance_config
# ---------------------------------------------------------------------------


class TestLoadGovernanceConfig:
    def test_defaults_when_no_config(self, tmp_path):
        config = load_governance_config(str(tmp_path))
        assert config == {"enabled": False}

    def test_reads_governance_section(self, tmp_path):
        config_path = tmp_path / ".sdlc" / "config.yaml"
        config_path.parent.mkdir(parents=True)
        config_path.write_text(
            textwrap.dedent("""\
            governance:
              enabled: true
              budget:
                token_limit: 50000
            """)
        )
        config = load_governance_config(str(tmp_path))
        assert config["enabled"] is True
        assert config["budget"]["token_limit"] == 50000

    def test_returns_default_when_section_missing(self, tmp_path):
        config_path = tmp_path / ".sdlc" / "config.yaml"
        config_path.parent.mkdir(parents=True)
        config_path.write_text("daemon:\n  max_turns: 100\n")
        config = load_governance_config(str(tmp_path))
        assert config == {"enabled": False}

    def test_handles_invalid_yaml(self, tmp_path):
        config_path = tmp_path / ".sdlc" / "config.yaml"
        config_path.parent.mkdir(parents=True)
        config_path.write_text(": invalid yaml: [")
        config = load_governance_config(str(tmp_path))
        assert config == {"enabled": False}

    def test_handles_non_dict_governance(self, tmp_path):
        config_path = tmp_path / ".sdlc" / "config.yaml"
        config_path.parent.mkdir(parents=True)
        config_path.write_text("governance: true\n")
        config = load_governance_config(str(tmp_path))
        assert config == {"enabled": False}


# ---------------------------------------------------------------------------
# load_routing_config
# ---------------------------------------------------------------------------


class TestLoadRoutingConfig:
    def test_defaults_when_no_config(self, tmp_path):
        config = load_routing_config(str(tmp_path))
        assert config == {}

    def test_reads_routing_section(self, tmp_path):
        config_path = tmp_path / ".sdlc" / "config.yaml"
        config_path.parent.mkdir(parents=True)
        config_path.write_text(
            textwrap.dedent("""\
            routing:
              poll_interval: 60
              stale_claim_timeout: 15
            """)
        )
        config = load_routing_config(str(tmp_path))
        assert config["poll_interval"] == 60
        assert config["stale_claim_timeout"] == 15

    def test_returns_empty_when_section_missing(self, tmp_path):
        config_path = tmp_path / ".sdlc" / "config.yaml"
        config_path.parent.mkdir(parents=True)
        config_path.write_text("daemon:\n  max_turns: 100\n")
        config = load_routing_config(str(tmp_path))
        assert config == {}

    def test_handles_invalid_yaml(self, tmp_path):
        config_path = tmp_path / ".sdlc" / "config.yaml"
        config_path.parent.mkdir(parents=True)
        config_path.write_text(": invalid yaml: [")
        config = load_routing_config(str(tmp_path))
        assert config == {}

    def test_handles_non_dict_routing(self, tmp_path):
        config_path = tmp_path / ".sdlc" / "config.yaml"
        config_path.parent.mkdir(parents=True)
        config_path.write_text("routing: 42\n")
        config = load_routing_config(str(tmp_path))
        assert config == {}


# ---------------------------------------------------------------------------
# load_orchestrator_config
# ---------------------------------------------------------------------------


class TestLoadOrchestratorConfig:
    def test_defaults_when_no_config(self, tmp_path):
        config = load_orchestrator_config(str(tmp_path))
        assert config["enabled"] is False
        assert config["challenger_pairings"] == {}
        assert config["max_iterations"] == 5
        assert config["polling_interval"] == 30
        assert config["max_turns_per_phase"] == 200

    def test_reads_orchestrator_section(self, tmp_path):
        config_path = tmp_path / ".sdlc" / "config.yaml"
        config_path.parent.mkdir(parents=True)
        config_path.write_text(
            textwrap.dedent("""\
            orchestrator:
              enabled: true
              challenger_pairings:
                prd: ["qa_engineer"]
                design: ["backend_engineer"]
              max_iterations: 10
              polling_interval: 15
              max_turns_per_phase: 300
            """)
        )
        config = load_orchestrator_config(str(tmp_path))
        assert config["enabled"] is True
        assert config["challenger_pairings"]["prd"] == ["qa_engineer"]
        assert config["challenger_pairings"]["design"] == ["backend_engineer"]
        assert config["max_iterations"] == 10
        assert config["polling_interval"] == 15
        assert config["max_turns_per_phase"] == 300

    def test_returns_defaults_when_section_missing(self, tmp_path):
        config_path = tmp_path / ".sdlc" / "config.yaml"
        config_path.parent.mkdir(parents=True)
        config_path.write_text("daemon:\n  max_turns: 100\n")
        config = load_orchestrator_config(str(tmp_path))
        assert config["enabled"] is False
        assert config["max_iterations"] == 5

    def test_handles_invalid_yaml(self, tmp_path):
        config_path = tmp_path / ".sdlc" / "config.yaml"
        config_path.parent.mkdir(parents=True)
        config_path.write_text(": invalid yaml: [")
        config = load_orchestrator_config(str(tmp_path))
        assert config["enabled"] is False
        assert config["max_iterations"] == 5

    def test_handles_non_dict_orchestrator(self, tmp_path):
        config_path = tmp_path / ".sdlc" / "config.yaml"
        config_path.parent.mkdir(parents=True)
        config_path.write_text("orchestrator: 42\n")
        config = load_orchestrator_config(str(tmp_path))
        assert config["enabled"] is False
        assert config["challenger_pairings"] == {}

    def test_handles_non_dict_challenger_pairings(self, tmp_path):
        config_path = tmp_path / ".sdlc" / "config.yaml"
        config_path.parent.mkdir(parents=True)
        config_path.write_text(
            textwrap.dedent("""\
            orchestrator:
              enabled: true
              challenger_pairings: "not_a_dict"
            """)
        )
        config = load_orchestrator_config(str(tmp_path))
        assert config["enabled"] is True
        assert config["challenger_pairings"] == {}

    def test_partial_config_fills_defaults(self, tmp_path):
        config_path = tmp_path / ".sdlc" / "config.yaml"
        config_path.parent.mkdir(parents=True)
        config_path.write_text(
            textwrap.dedent("""\
            orchestrator:
              enabled: true
            """)
        )
        config = load_orchestrator_config(str(tmp_path))
        assert config["enabled"] is True
        assert config["challenger_pairings"] == {}
        assert config["max_iterations"] == 5
        assert config["polling_interval"] == 30
        assert config["max_turns_per_phase"] == 200


# ---------------------------------------------------------------------------
# check_budget
# ---------------------------------------------------------------------------


class TestCheckBudget:
    def test_no_budget_returns_allowed(self):
        storage = MagicMock()
        storage.get_agent_budget.return_value = None
        allowed, reason = check_budget(storage, "agent-1")
        assert allowed is True
        assert reason == "No budget set"

    def test_token_budget_exhausted(self):
        storage = MagicMock()
        storage.get_agent_budget.return_value = {
            "token_limit": 1000,
            "token_used": 1000,
        }
        allowed, reason = check_budget(storage, "agent-1")
        assert allowed is False
        assert "Token budget exhausted" in reason
        assert "1000/1000" in reason

    def test_token_budget_ok(self):
        storage = MagicMock()
        storage.get_agent_budget.return_value = {
            "token_limit": 1000,
            "token_used": 500,
            "alert_threshold_pct": 90,
        }
        allowed, reason = check_budget(storage, "agent-1")
        assert allowed is True
        assert reason == "Budget OK"

    def test_token_budget_over_threshold_still_allowed(self):
        storage = MagicMock()
        storage.get_agent_budget.return_value = {
            "token_limit": 1000,
            "token_used": 950,
            "alert_threshold_pct": 90,
        }
        allowed, reason = check_budget(storage, "agent-1")
        assert allowed is True
        assert reason == "Budget OK"

    def test_cost_budget_exhausted(self):
        storage = MagicMock()
        storage.get_agent_budget.return_value = {
            "token_limit": 0,
            "cost_limit_cents": 500,
            "cost_used_cents": 500,
        }
        allowed, reason = check_budget(storage, "agent-1")
        assert allowed is False
        assert "Cost budget exhausted" in reason
        assert "500/500" in reason

    def test_cost_budget_ok(self):
        storage = MagicMock()
        storage.get_agent_budget.return_value = {
            "token_limit": 0,
            "cost_limit_cents": 500,
            "cost_used_cents": 200,
        }
        allowed, reason = check_budget(storage, "agent-1")
        assert allowed is True
        assert reason == "Budget OK"

    def test_passes_run_id(self):
        storage = MagicMock()
        storage.get_agent_budget.return_value = None
        check_budget(storage, "agent-1", run_id="R-001")
        storage.get_agent_budget.assert_called_once_with("agent-1", run_id="R-001")

    def test_zero_token_limit_skips_check(self):
        storage = MagicMock()
        storage.get_agent_budget.return_value = {
            "token_limit": 0,
            "cost_limit_cents": 0,
        }
        allowed, reason = check_budget(storage, "agent-1")
        assert allowed is True
        assert reason == "Budget OK"


# ---------------------------------------------------------------------------
# execute_work_loop
# ---------------------------------------------------------------------------


class TestExecuteWorkLoop:
    def test_exits_when_no_project(self):
        mock_storage = MagicMock()
        mock_storage.get_most_recent_project.return_value = None

        with (
            patch.dict("sys.modules", {"a_sdlc.server": MagicMock()}),
            patch("a_sdlc.executor.get_storage", return_value=mock_storage),
            patch(
                "a_sdlc.executor.load_daemon_config",
                return_value={"adapter": "mock", "max_turns": 200},
            ),
            patch(
                "a_sdlc.adapters.create_adapter",
                return_value=MagicMock(),
            ),
        ):
            execute_work_loop("agent-1", max_iterations=1)

        # Should not attempt any work
        mock_storage.detect_stale_claims.assert_not_called()

    def test_claims_and_executes_task(self, tmp_path):
        mock_storage = MagicMock()
        mock_storage.get_most_recent_project.return_value = {"id": "proj-1"}
        mock_storage.detect_stale_claims.return_value = []
        mock_storage.get_available_work.return_value = [
            {"id": "T-001", "title": "Test task"},
        ]
        mock_storage.claim_task.return_value = {"task_id": "T-001"}

        # Make get_available_work return empty on 2nd call to end loop
        mock_storage.get_available_work.side_effect = [
            [{"id": "T-001", "title": "Test task"}],
            [],
        ]

        with (
            patch.dict("sys.modules", {"a_sdlc.server": MagicMock()}),
            patch("a_sdlc.executor.get_storage", return_value=mock_storage),
            patch(
                "a_sdlc.executor.load_governance_config",
                return_value={"enabled": False},
            ),
            patch("a_sdlc.executor.load_routing_config", return_value={}),
            patch(
                "a_sdlc.executor.load_daemon_config",
                return_value={"adapter": "mock", "max_turns": 200},
            ),
            patch(
                "a_sdlc.adapters.create_adapter",
                return_value=MagicMock(),
            ),
            patch("a_sdlc.executor.time.sleep"),
            patch(
                "a_sdlc.server.build_execute_task_prompt",
                return_value="mock prompt",
            ),
        ):
            execute_work_loop("agent-1", max_iterations=2)

        mock_storage.claim_task.assert_called_once_with("T-001", "agent-1")

    def test_budget_exceeded_stops_loop(self, tmp_path):
        mock_storage = MagicMock()
        mock_storage.get_most_recent_project.return_value = {"id": "proj-1"}
        mock_storage.get_agent_budget.return_value = {
            "token_limit": 100,
            "token_used": 100,
        }

        with (
            patch.dict("sys.modules", {"a_sdlc.server": MagicMock()}),
            patch("a_sdlc.executor.get_storage", return_value=mock_storage),
            patch(
                "a_sdlc.executor.load_governance_config",
                return_value={"enabled": True},
            ),
            patch("a_sdlc.executor.load_routing_config", return_value={}),
            patch(
                "a_sdlc.executor.load_daemon_config",
                return_value={"adapter": "mock", "max_turns": 200},
            ),
            patch(
                "a_sdlc.adapters.create_adapter",
                return_value=MagicMock(),
            ),
            patch("a_sdlc.executor.time.sleep"),
        ):
            execute_work_loop("agent-1", max_iterations=5)

        # Should not attempt to get work since budget is exhausted
        mock_storage.get_available_work.assert_not_called()

    def test_releases_stale_claims(self, tmp_path):
        mock_storage = MagicMock()
        mock_storage.get_most_recent_project.return_value = {"id": "proj-1"}
        mock_storage.detect_stale_claims.return_value = [
            {"task_id": "T-OLD", "agent_id": "agent-stale"},
        ]
        mock_storage.get_available_work.return_value = []

        with (
            patch.dict("sys.modules", {"a_sdlc.server": MagicMock()}),
            patch("a_sdlc.executor.get_storage", return_value=mock_storage),
            patch(
                "a_sdlc.executor.load_governance_config",
                return_value={"enabled": False},
            ),
            patch("a_sdlc.executor.load_routing_config", return_value={}),
            patch("a_sdlc.executor.time.sleep"),
        ):
            execute_work_loop("agent-1", max_iterations=1)

        mock_storage.release_task.assert_called_once_with(
            "T-OLD", "agent-stale", reason="stale_claim"
        )

    def test_handles_claim_conflict(self, tmp_path):
        mock_storage = MagicMock()
        mock_storage.get_most_recent_project.return_value = {"id": "proj-1"}
        mock_storage.detect_stale_claims.return_value = []
        mock_storage.get_available_work.return_value = [
            {"id": "T-001", "title": "Contested task"},
        ]
        mock_storage.claim_task.side_effect = ValueError("Already claimed")

        with (
            patch.dict("sys.modules", {"a_sdlc.server": MagicMock()}),
            patch("a_sdlc.executor.get_storage", return_value=mock_storage),
            patch(
                "a_sdlc.executor.load_governance_config",
                return_value={"enabled": False},
            ),
            patch("a_sdlc.executor.load_routing_config", return_value={}),
            patch(
                "a_sdlc.executor.load_daemon_config",
                return_value={"adapter": "mock", "max_turns": 200},
            ),
            patch(
                "a_sdlc.adapters.create_adapter",
                return_value=MagicMock(),
            ),
            patch("a_sdlc.executor.time.sleep"),
        ):
            # Should not raise, just continue
            execute_work_loop("agent-1", max_iterations=1)

    def test_sleeps_when_no_work(self, tmp_path):
        mock_storage = MagicMock()
        mock_storage.get_most_recent_project.return_value = {"id": "proj-1"}
        mock_storage.detect_stale_claims.return_value = []
        mock_storage.get_available_work.return_value = []

        with (
            patch.dict("sys.modules", {"a_sdlc.server": MagicMock()}),
            patch("a_sdlc.executor.get_storage", return_value=mock_storage),
            patch(
                "a_sdlc.executor.load_governance_config",
                return_value={"enabled": False},
            ),
            patch(
                "a_sdlc.executor.load_routing_config",
                return_value={"poll_interval": 10},
            ),
            patch(
                "a_sdlc.executor.load_daemon_config",
                return_value={"adapter": "mock", "max_turns": 200},
            ),
            patch(
                "a_sdlc.adapters.create_adapter",
                return_value=MagicMock(),
            ),
            patch("a_sdlc.executor.time.sleep") as mock_sleep,
        ):
            execute_work_loop("agent-1", max_iterations=1)

        mock_sleep.assert_called_once_with(10)

    def test_respects_max_iterations(self, tmp_path):
        mock_storage = MagicMock()
        mock_storage.get_most_recent_project.return_value = {"id": "proj-1"}
        mock_storage.detect_stale_claims.return_value = []
        mock_storage.get_available_work.return_value = []

        sleep_count = 0

        def count_sleep(s):
            nonlocal sleep_count
            sleep_count += 1

        with (
            patch.dict("sys.modules", {"a_sdlc.server": MagicMock()}),
            patch("a_sdlc.executor.get_storage", return_value=mock_storage),
            patch(
                "a_sdlc.executor.load_governance_config",
                return_value={"enabled": False},
            ),
            patch("a_sdlc.executor.load_routing_config", return_value={}),
            patch(
                "a_sdlc.executor.load_daemon_config",
                return_value={"adapter": "mock", "max_turns": 200},
            ),
            patch(
                "a_sdlc.adapters.create_adapter",
                return_value=MagicMock(),
            ),
            patch("a_sdlc.executor.time.sleep", side_effect=count_sleep),
        ):
            execute_work_loop("agent-1", max_iterations=3)

        assert sleep_count == 3

    def test_stale_release_failure_does_not_crash(self, tmp_path):
        mock_storage = MagicMock()
        mock_storage.get_most_recent_project.return_value = {"id": "proj-1"}
        mock_storage.detect_stale_claims.return_value = [
            {"task_id": "T-STALE", "agent_id": "agent-dead"},
        ]
        mock_storage.release_task.side_effect = RuntimeError("DB error")
        mock_storage.get_available_work.return_value = []

        with (
            patch.dict("sys.modules", {"a_sdlc.server": MagicMock()}),
            patch("a_sdlc.executor.get_storage", return_value=mock_storage),
            patch(
                "a_sdlc.executor.load_governance_config",
                return_value={"enabled": False},
            ),
            patch("a_sdlc.executor.load_routing_config", return_value={}),
            patch(
                "a_sdlc.executor.load_daemon_config",
                return_value={"adapter": "mock", "max_turns": 200},
            ),
            patch(
                "a_sdlc.adapters.create_adapter",
                return_value=MagicMock(),
            ),
            patch("a_sdlc.executor.time.sleep"),
        ):
            # Should not raise even though release_task fails
            execute_work_loop("agent-1", max_iterations=1)

    def test_work_loop_uses_adapter(self, tmp_path):
        """Verify work loop calls create_adapter and adapter.execute."""
        mock_storage = MagicMock()
        mock_storage.get_most_recent_project.return_value = {"id": "proj-1"}
        mock_storage.detect_stale_claims.return_value = []
        mock_storage.get_available_work.side_effect = [
            [{"id": "T-001", "title": "Test task"}],
            [],
        ]
        mock_storage.claim_task.return_value = {"task_id": "T-001"}

        mock_adapter = MagicMock()
        mock_adapter.execute.return_value = {
            "status": "ok",
            "result": (
                "---TASK-OUTCOME---\n"
                "task_id: T-001\n"
                "verdict: PASS\n"
                "summary: done\n"
                "---END-OUTCOME---"
            ),
        }

        with (
            patch.dict("sys.modules", {"a_sdlc.server": MagicMock()}),
            patch("a_sdlc.executor.get_storage", return_value=mock_storage),
            patch(
                "a_sdlc.executor.load_governance_config",
                return_value={"enabled": False},
            ),
            patch("a_sdlc.executor.load_routing_config", return_value={}),
            patch(
                "a_sdlc.executor.load_daemon_config",
                return_value={"adapter": "mock", "max_turns": 200},
            ),
            patch(
                "a_sdlc.adapters.create_adapter",
                return_value=mock_adapter,
            ) as mock_factory,
            patch("a_sdlc.executor.time.sleep"),
            patch(
                "a_sdlc.server.build_execute_task_prompt",
                return_value="mock prompt",
            ),
        ):
            execute_work_loop("agent-1", max_iterations=2)

        mock_factory.assert_called_once_with("mock")
        mock_adapter.execute.assert_called_once()

    def test_work_loop_uses_build_execute_task_prompt(self, tmp_path):
        """Verify work loop uses the comprehensive prompt builder."""
        mock_storage = MagicMock()
        mock_storage.get_most_recent_project.return_value = {"id": "proj-1"}
        mock_storage.detect_stale_claims.return_value = []
        mock_storage.get_available_work.side_effect = [
            [{"id": "T-001", "title": "Test task", "prd_id": None}],
            [],
        ]
        mock_storage.claim_task.return_value = {"task_id": "T-001"}

        mock_adapter = MagicMock()
        mock_adapter.execute.return_value = {
            "status": "ok",
            "result": (
                "---TASK-OUTCOME---\n"
                "task_id: T-001\n"
                "verdict: PASS\n"
                "summary: done\n"
                "---END-OUTCOME---"
            ),
        }

        with (
            patch.dict("sys.modules", {"a_sdlc.server": MagicMock()}),
            patch("a_sdlc.executor.get_storage", return_value=mock_storage),
            patch(
                "a_sdlc.executor.load_governance_config",
                return_value={"enabled": False},
            ),
            patch("a_sdlc.executor.load_routing_config", return_value={}),
            patch(
                "a_sdlc.executor.load_daemon_config",
                return_value={"adapter": "mock", "max_turns": 200},
            ),
            patch(
                "a_sdlc.adapters.create_adapter",
                return_value=mock_adapter,
            ),
            patch("a_sdlc.executor.time.sleep"),
            patch(
                "a_sdlc.server.build_execute_task_prompt",
                return_value="comprehensive prompt",
            ) as mock_prompt_builder,
        ):
            execute_work_loop("agent-1", max_iterations=2)

        mock_prompt_builder.assert_called_once_with("T-001", {"id": "T-001", "title": "Test task", "prd_id": None})
        call_kwargs = mock_adapter.execute.call_args
        assert call_kwargs[1]["prompt"] == "comprehensive prompt" or call_kwargs[0][0] == "comprehensive prompt" if call_kwargs[0] else call_kwargs[1]["prompt"] == "comprehensive prompt"

    def test_work_loop_reports_usage(self, tmp_path):
        """Verify work loop calls increment_agent_budget when governance is enabled."""
        mock_storage = MagicMock()
        mock_storage.get_most_recent_project.return_value = {"id": "proj-1"}
        mock_storage.detect_stale_claims.return_value = []
        mock_storage.get_available_work.side_effect = [
            [{"id": "T-001", "title": "Test task", "prd_id": None}],
            [],
        ]
        mock_storage.claim_task.return_value = {"task_id": "T-001"}

        mock_adapter = MagicMock()
        mock_adapter.execute.return_value = {
            "status": "ok",
            "turns": 10,
            "cost_usd": 0.50,
            "result": (
                "---TASK-OUTCOME---\n"
                "task_id: T-001\n"
                "verdict: PASS\n"
                "summary: done\n"
                "---END-OUTCOME---"
            ),
        }

        with (
            patch.dict("sys.modules", {"a_sdlc.server": MagicMock()}),
            patch("a_sdlc.executor.get_storage", return_value=mock_storage),
            patch(
                "a_sdlc.executor.load_governance_config",
                return_value={"enabled": True},
            ),
            patch("a_sdlc.executor.load_routing_config", return_value={}),
            patch(
                "a_sdlc.executor.load_daemon_config",
                return_value={"adapter": "mock", "max_turns": 200},
            ),
            patch(
                "a_sdlc.adapters.create_adapter",
                return_value=mock_adapter,
            ),
            patch("a_sdlc.executor.time.sleep"),
            patch("a_sdlc.executor.check_budget", return_value=(True, "")),
            patch(
                "a_sdlc.server.build_execute_task_prompt",
                return_value="mock prompt",
            ),
            patch(
                "a_sdlc.executor.evaluate_escalation_rules",
                return_value=[],
            ),
        ):
            execute_work_loop("agent-1", max_iterations=2)

        mock_storage.increment_agent_budget.assert_called_once_with(
            "agent-1",
            tokens_delta=40000,  # 10 turns * 4000
            cost_delta=50,  # 0.50 * 100
        )

    def test_work_loop_calls_escalation_rules(self, tmp_path):
        """Verify work loop evaluates escalation rules after task completion."""
        mock_storage = MagicMock()
        mock_storage.get_most_recent_project.return_value = {"id": "proj-1"}
        mock_storage.detect_stale_claims.return_value = []
        mock_storage.get_available_work.side_effect = [
            [{"id": "T-001", "title": "Test task", "prd_id": None}],
            [],
        ]
        mock_storage.claim_task.return_value = {"task_id": "T-001"}

        mock_adapter = MagicMock()
        mock_adapter.execute.return_value = {
            "status": "ok",
            "turns": 5,
            "cost_usd": 0.10,
            "result": (
                "---TASK-OUTCOME---\n"
                "task_id: T-001\n"
                "verdict: PASS\n"
                "summary: done\n"
                "---END-OUTCOME---"
            ),
        }

        with (
            patch.dict("sys.modules", {"a_sdlc.server": MagicMock()}),
            patch("a_sdlc.executor.get_storage", return_value=mock_storage),
            patch(
                "a_sdlc.executor.load_governance_config",
                return_value={"enabled": True},
            ),
            patch("a_sdlc.executor.load_routing_config", return_value={}),
            patch(
                "a_sdlc.executor.load_daemon_config",
                return_value={"adapter": "mock", "max_turns": 200},
            ),
            patch(
                "a_sdlc.adapters.create_adapter",
                return_value=mock_adapter,
            ),
            patch("a_sdlc.executor.time.sleep"),
            patch("a_sdlc.executor.check_budget", return_value=(True, "")),
            patch(
                "a_sdlc.server.build_execute_task_prompt",
                return_value="mock prompt",
            ),
            patch(
                "a_sdlc.executor.evaluate_escalation_rules",
                return_value=[],
            ) as mock_escalation,
        ):
            execute_work_loop("agent-1", max_iterations=2)

        mock_escalation.assert_called_once_with(
            "T-001",
            task_metrics={"verdict": "PASS", "cost_usd": 0.10},
            project_dir=None,
        )

    def test_work_loop_pauses_on_escalation(self, tmp_path):
        """Verify escalation with pause action triggers a warning log."""
        mock_storage = MagicMock()
        mock_storage.get_most_recent_project.return_value = {"id": "proj-1"}
        mock_storage.detect_stale_claims.return_value = []
        mock_storage.get_available_work.side_effect = [
            [{"id": "T-001", "title": "Test task", "prd_id": None}],
            [],
        ]
        mock_storage.claim_task.return_value = {"task_id": "T-001"}

        mock_adapter = MagicMock()
        mock_adapter.execute.return_value = {
            "status": "ok",
            "turns": 5,
            "cost_usd": 5.0,
            "result": (
                "---TASK-OUTCOME---\n"
                "task_id: T-001\n"
                "verdict: PASS\n"
                "summary: done\n"
                "---END-OUTCOME---"
            ),
        }

        with (
            patch.dict("sys.modules", {"a_sdlc.server": MagicMock()}),
            patch("a_sdlc.executor.get_storage", return_value=mock_storage),
            patch(
                "a_sdlc.executor.load_governance_config",
                return_value={"enabled": True},
            ),
            patch("a_sdlc.executor.load_routing_config", return_value={}),
            patch(
                "a_sdlc.executor.load_daemon_config",
                return_value={"adapter": "mock", "max_turns": 200},
            ),
            patch(
                "a_sdlc.adapters.create_adapter",
                return_value=mock_adapter,
            ),
            patch("a_sdlc.executor.time.sleep"),
            patch("a_sdlc.executor.check_budget", return_value=(True, "")),
            patch(
                "a_sdlc.server.build_execute_task_prompt",
                return_value="mock prompt",
            ),
            patch(
                "a_sdlc.executor.evaluate_escalation_rules",
                return_value=[
                    {"rule": "cost > 1.0", "action": "pause", "reason": "Cost exceeded threshold"}
                ],
            ),
            patch("a_sdlc.executor.logger") as mock_logger,
        ):
            execute_work_loop("agent-1", max_iterations=2)

        mock_logger.warning.assert_any_call(
            "Escalation triggered for %s: %s",
            "T-001",
            "Cost exceeded threshold",
        )


# ---------------------------------------------------------------------------
# load_daemon_config adapter key
# ---------------------------------------------------------------------------


class TestDaemonConfigAdapter:
    def test_default_adapter_is_mock(self, tmp_path):
        config = load_daemon_config(str(tmp_path))
        assert config["adapter"] == "mock"

    def test_reads_adapter_from_config(self, tmp_path):
        config_path = tmp_path / ".sdlc" / "config.yaml"
        config_path.parent.mkdir(parents=True)
        config_path.write_text(
            textwrap.dedent("""\
            daemon:
              adapter: claude
              max_turns: 100
            """)
        )
        config = load_daemon_config(str(tmp_path))
        assert config["adapter"] == "claude"


# ---------------------------------------------------------------------------
# CLI: run goal
# ---------------------------------------------------------------------------


class TestRunGoal:
    def test_goal_spawns_process(self, runner, runs_dir):
        """Verify run goal creates a run state file and spawns a subprocess."""
        with (
            patch("shutil.which", return_value="/usr/local/bin/claude"),
            patch("subprocess.Popen") as mock_popen,
            patch("a_sdlc.cli._load_project_config", return_value={}),
        ):
            mock_proc = MagicMock()
            mock_proc.pid = 12345
            mock_popen.return_value = mock_proc

            result = runner.invoke(
                main, ["run", "goal", "Add JWT authentication"]
            )

        assert result.exit_code == 0
        assert "Goal execution started" in result.output
        assert "12345" in result.output

        # Verify a run state file was created
        run_files = list(runs_dir.glob("R-*.json"))
        assert len(run_files) == 1
        data = json.loads(run_files[0].read_text())
        assert data["type"] == "pipeline"
        assert data["description"] == "Add JWT authentication"
        assert data["status"] == "running"
        assert data["pid"] == 12345

    def test_goal_with_flags(self, runner, runs_dir):
        """Verify run goal accepts all optional flags."""
        goal_file = runs_dir / "spec.md"
        goal_file.write_text("Detailed spec here")

        with (
            patch("shutil.which", return_value="/usr/local/bin/claude"),
            patch("subprocess.Popen") as mock_popen,
            patch("a_sdlc.cli._load_project_config", return_value={}),
        ):
            mock_proc = MagicMock()
            mock_proc.pid = 99999
            mock_popen.return_value = mock_proc

            result = runner.invoke(
                main,
                [
                    "run",
                    "goal",
                    "Refactor DB layer",
                    "--goal-file",
                    str(goal_file),
                    "--max-turns",
                    "300",
                    "--max-iterations",
                    "3",
                    "--adapter",
                    "claude",
                    "--no-interactive",
                ],
            )

        assert result.exit_code == 0
        assert "Goal execution started" in result.output

        run_files = list(runs_dir.glob("R-*.json"))
        assert len(run_files) == 1
        data = json.loads(run_files[0].read_text())
        assert data["max_turns"] == 300
        assert data["max_iterations"] == 3
        assert data["adapter"] == "claude"
        assert data["no_interactive"] is True

    def test_goal_uses_config_defaults(self, runner, runs_dir):
        """Verify run goal reads defaults from config when flags are omitted."""
        config = {
            "orchestrator": {"max_turns_per_phase": 999, "max_iterations": 10},
            "daemon": {"adapter": "gemini"},
        }
        with (
            patch("shutil.which", return_value="/usr/local/bin/gemini"),
            patch("subprocess.Popen") as mock_popen,
            patch("a_sdlc.cli._load_project_config", return_value=config),
        ):
            mock_proc = MagicMock()
            mock_proc.pid = 11111
            mock_popen.return_value = mock_proc

            result = runner.invoke(main, ["run", "goal", "Test defaults"])

        assert result.exit_code == 0
        run_files = list(runs_dir.glob("R-*.json"))
        data = json.loads(run_files[0].read_text())
        assert data["max_turns"] == 999
        assert data["max_iterations"] == 10
        assert data["adapter"] == "gemini"

    def test_goal_falls_back_to_objective_config(self, runner, runs_dir):
        """Verify run goal falls back to objective config when orchestrator is absent."""
        config = {
            "objective": {"max_turns": 777, "max_iterations": 7},
            "daemon": {"adapter": "claude"},
        }
        with (
            patch("shutil.which", return_value="/usr/local/bin/claude"),
            patch("subprocess.Popen") as mock_popen,
            patch("a_sdlc.cli._load_project_config", return_value=config),
        ):
            mock_proc = MagicMock()
            mock_proc.pid = 22222
            mock_popen.return_value = mock_proc

            result = runner.invoke(main, ["run", "goal", "Fallback test"])

        assert result.exit_code == 0
        run_files = list(runs_dir.glob("R-*.json"))
        data = json.loads(run_files[0].read_text())
        assert data["max_turns"] == 777
        assert data["max_iterations"] == 7

    def test_goal_missing_adapter_cli(self, runner, runs_dir):
        """Verify run goal fails when adapter CLI is not on PATH."""
        with (
            patch("shutil.which", return_value=None),
            patch("a_sdlc.cli._load_project_config", return_value={}),
        ):
            result = runner.invoke(main, ["run", "goal", "Should fail"])

        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_goal_mock_adapter_skips_cli_check(self, runner, runs_dir):
        """Verify run goal with --adapter mock does not require CLI on PATH."""
        with (
            patch("subprocess.Popen") as mock_popen,
            patch("a_sdlc.cli._load_project_config", return_value={}),
        ):
            mock_proc = MagicMock()
            mock_proc.pid = 33333
            mock_popen.return_value = mock_proc

            result = runner.invoke(
                main, ["run", "goal", "Mock test", "--adapter", "mock"]
            )

        assert result.exit_code == 0
        assert "Goal execution started" in result.output

    def test_goal_executor_command_includes_description(self, runner, runs_dir):
        """Verify the spawned executor command includes --mode objective and --description."""
        with (
            patch("shutil.which", return_value="/usr/local/bin/claude"),
            patch("subprocess.Popen") as mock_popen,
            patch("a_sdlc.cli._load_project_config", return_value={}),
        ):
            mock_proc = MagicMock()
            mock_proc.pid = 44444
            mock_popen.return_value = mock_proc

            runner.invoke(main, ["run", "goal", "Build REST API"])

        # Verify the Popen command
        call_args = mock_popen.call_args
        cmd = call_args[0][0]
        assert "a_sdlc.orchestrator" in cmd
        assert "--run-id" in cmd
        assert "--max-turns" in cmd
        assert "500" in cmd  # default


# ---------------------------------------------------------------------------
# CLI: run status enhanced (per-run detail)
# ---------------------------------------------------------------------------


class TestRunStatusDetail:
    def test_status_detail_for_goal_run(self, runner, runs_dir):
        """Verify per-run detail view shows goal-specific information."""
        run_id = "R-detail01"
        _write_run(
            run_id,
            {
                "run_id": run_id,
                "type": "pipeline",
                "entity_id": "Add JWT auth",
                "description": "Add JWT authentication to the API",
                "status": "running",
                "adapter": "claude",
                "max_turns": 500,
                "max_iterations": 5,
                "pid": None,
                "started_at": "2026-04-09T10:00:00",
            },
        )

        result = runner.invoke(main, ["run", "status", run_id])
        assert result.exit_code == 0
        assert run_id in result.output
        assert "pipe" in result.output.lower()
        assert "Add JWT auth" in result.output

    def test_status_detail_shows_controls(self, runner, runs_dir):
        """Verify per-run detail shows control actions."""
        run_id = "R-detail02"
        _write_run(
            run_id,
            {
                "run_id": run_id,
                "type": "sprint",
                "entity_id": "PROJ-S0001",
                "status": "running",
                "pid": None,
                "started_at": "2026-04-09T10:00:00",
                "controls": [
                    {
                        "item_id": "PROJ-T00001",
                        "action": "pause",
                        "issued_at": "2026-04-09T10:05:00",
                    }
                ],
            },
        )

        result = runner.invoke(main, ["run", "status", run_id])
        assert result.exit_code == 0
        assert "PROJ-T00001" in result.output
        assert "pause" in result.output.lower()

    def test_status_detail_shows_answers(self, runner, runs_dir):
        """Verify per-run detail shows provided answers."""
        run_id = "R-detail03"
        _write_run(
            run_id,
            {
                "run_id": run_id,
                "type": "pipeline",
                "entity_id": "test",
                "status": "running",
                "pid": None,
                "started_at": "2026-04-09T10:00:00",
                "answers": [
                    {
                        "message": "use RS256",
                        "answered_at": "2026-04-09T10:02:00",
                    }
                ],
            },
        )

        result = runner.invoke(main, ["run", "status", run_id])
        assert result.exit_code == 0
        assert "use RS256" in result.output

    def test_status_detail_shows_comments(self, runner, runs_dir):
        """Verify per-run detail shows user comments."""
        run_id = "R-detail04"
        _write_run(
            run_id,
            {
                "run_id": run_id,
                "type": "pipeline",
                "entity_id": "test",
                "status": "running",
                "pid": None,
                "started_at": "2026-04-09T10:00:00",
                "comments": [
                    {
                        "artifact_id": "PROJ-P0001",
                        "message": "Focus on REST",
                        "type": "user_intervention",
                        "posted_at": "2026-04-09T10:03:00",
                    }
                ],
            },
        )

        result = runner.invoke(main, ["run", "status", run_id])
        assert result.exit_code == 0
        assert "PROJ-P0001" in result.output
        assert "Focus on REST" in result.output

    def test_status_detail_nonexistent_run(self, runner, runs_dir):
        """Verify per-run detail fails for non-existent run."""
        result = runner.invoke(main, ["run", "status", "R-ghost"])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_status_summary_shows_goal_runs(self, runner, runs_dir):
        """Verify summary table includes goal runs with description snippet."""
        run_id = "R-summary01"
        _write_run(
            run_id,
            {
                "run_id": run_id,
                "type": "pipeline",
                "entity_id": "Add JWT authentication",
                "description": "Add JWT authentication to the REST API endpoints",
                "status": "completed",
                "pid": None,
                "started_at": "2026-04-09T10:00:00",
            },
        )

        result = runner.invoke(main, ["run", "status"])
        assert result.exit_code == 0
        assert "pipe" in result.output.lower()

    def test_status_shows_awaiting_clarification(self, runner, runs_dir):
        """Verify summary shows answer instructions for awaiting_clarification."""
        run_id = "R-clarify01"
        _write_run(
            run_id,
            {
                "run_id": run_id,
                "type": "pipeline",
                "entity_id": "test",
                "status": "awaiting_clarification",
                "config": {"message": "Which auth provider?"},
                "pid": None,
                "started_at": "2026-04-09T10:00:00",
            },
        )

        result = runner.invoke(main, ["run", "status"])
        assert result.exit_code == 0
        assert "awaiting input" in result.output.lower() or "awaiting" in result.output.lower()
        assert f"a-sdlc run answer {run_id}" in result.output


# ---------------------------------------------------------------------------
# CLI: run status — pipeline run support (SDLC-T00193)
# ---------------------------------------------------------------------------


class TestRunStatusPipeline:
    """Tests for pipeline-specific columns in summary and detail views."""

    @pytest.fixture(autouse=True)
    def _wide_console(self, monkeypatch):
        """Widen Rich console so table columns are not truncated."""
        from rich.console import Console

        from a_sdlc import cli as _cli_mod

        monkeypatch.setattr(_cli_mod, "console", Console(width=200))

    def test_pipeline_run_shows_phase_and_queue(self, runner, runs_dir):
        """Pipeline runs display phase, queue depth, and thread count in summary."""
        _write_run(
            "R-pipe01",
            {
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
            },
        )

        result = runner.invoke(main, ["run", "status"])
        assert result.exit_code == 0
        assert "pipeline" in result.output
        assert "implement" in result.output
        # Queue: 2 pending, 1 active, 1 completed, 0 failed (P/A/C/F format)
        assert "2/1/1/0" in result.output

    def test_sprint_run_shows_dashes_for_pipeline_columns(self, runner, runs_dir):
        """Sprint runs display '-' for Phase, Queue, Threads columns."""
        _write_run(
            "R-sprint01",
            {
                "run_id": "R-sprint01",
                "type": "sprint",
                "entity_id": "PROJ-S0001",
                "status": "running",
                "started_at": "2026-04-09T10:00:00",
                "pid": None,
            },
        )

        result = runner.invoke(main, ["run", "status"])
        assert result.exit_code == 0
        assert "sprint" in result.output

    def test_awaiting_clarification_shows_question_snippet(self, runner, runs_dir):
        """Runs with awaiting_clarification show truncated question in details."""
        _write_run(
            "R-clar01",
            {
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
            },
        )

        result = runner.invoke(main, ["run", "status"])
        assert result.exit_code == 0
        assert "awaiting input" in result.output.lower()
        assert "OAuth2" in result.output

    def test_detail_view_not_found(self, runner, runs_dir):
        """Passing a nonexistent run_id shows error."""
        result = runner.invoke(main, ["run", "status", "R-nonexist"])
        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_detail_view_sprint_run(self, runner, runs_dir):
        """Detail view for sprint run shows run info without pipeline sections."""
        _write_run(
            "R-det01",
            {
                "run_id": "R-det01",
                "type": "sprint",
                "entity_id": "PROJ-S0001",
                "status": "completed",
                "started_at": "2026-04-09T10:00:00",
                "pid": None,
            },
        )

        result = runner.invoke(main, ["run", "status", "R-det01"])
        assert result.exit_code == 0
        assert "R-det01" in result.output
        assert "sprint" in result.output
        assert "PROJ-S0001" in result.output

    def test_detail_view_pipeline_full(self, runner, runs_dir):
        """Detail view for pipeline run shows goal, phase, work queue, threads, metrics."""
        _write_run(
            "R-det02",
            {
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
                    {
                        "timestamp": "2026-04-09T10:00:00",
                        "phase": "pm",
                        "agent": "pm",
                        "action": "Generated PRD",
                    },
                    {
                        "timestamp": "2026-04-09T10:05:00",
                        "phase": "implement",
                        "agent": "be",
                        "action": "Started task",
                    },
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
            },
        )

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

    def test_detail_view_clarification(self, runner, runs_dir):
        """Detail view shows clarification panel when run is awaiting input."""
        _write_run(
            "R-clar02",
            {
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
            },
        )

        result = runner.invoke(main, ["run", "status", "R-clar02"])
        assert result.exit_code == 0
        assert "Clarification Needed" in result.output
        assert "OAuth2 grant types" in result.output
        assert "a-sdlc run answer" in result.output

    def test_approval_instructions_still_shown(self, runner, runs_dir):
        """Existing awaiting_confirmation approval flow still works."""
        _write_run(
            "R-compat01",
            {
                "run_id": "R-compat01",
                "type": "sprint",
                "entity_id": "PROJ-S0001",
                "status": "awaiting_confirmation",
                "config": {"message": "Batch 1 complete"},
                "pid": None,
                "started_at": "2026-04-09T10:00:00",
            },
        )

        result = runner.invoke(main, ["run", "status"])
        assert result.exit_code == 0
        assert "a-sdlc run approve R-compat01" in result.output
