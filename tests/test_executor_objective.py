"""Tests for Executor.execute_objective() and supporting helpers.

Covers:
- Autonomous objective execution (single session)
- Supervised objective execution (checkpoint detection, resume)
- _build_objective_prompt() content variations
- _parse_objective_result() structured parsing
- __main__ entry point objective mode dispatch
"""

from __future__ import annotations

import textwrap
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from a_sdlc.executor import (
    Executor,
    _main,
    _read_run,
    _update_run,
    _write_run,
    load_objective_config,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
    with patch("shutil.which", return_value="/usr/bin/claude") as m:
        yield m


@pytest.fixture
def mock_storage():
    """Create a MagicMock storage object."""
    return MagicMock()


@pytest.fixture
def executor(mock_claude_path, mock_storage):
    """Create a supervised Executor instance with mocked dependencies."""
    with patch("a_sdlc.executor.get_storage", return_value=mock_storage):
        ex = Executor(
            max_turns=200,
            max_concurrency=3,
            project_dir="/tmp/test-project",
            supervised=True,
        )
    return ex


@pytest.fixture
def autonomous_executor(mock_claude_path, mock_storage):
    """Create an autonomous (non-supervised) Executor instance."""
    with patch("a_sdlc.executor.get_storage", return_value=mock_storage):
        ex = Executor(
            max_turns=200,
            max_concurrency=3,
            project_dir="/tmp/test-project",
            supervised=False,
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
# load_objective_config
# ---------------------------------------------------------------------------


class TestLoadObjectiveConfig:
    def test_load_defaults_when_no_config(self, tmp_path):
        """Returns defaults when no config.yaml exists."""
        result = load_objective_config(project_dir=str(tmp_path))
        assert result["max_iterations"] == 5
        assert result["max_turns"] == 500
        assert result["evaluation"]["commands"] == []

    def test_load_from_config_file(self, tmp_path):
        """Reads values from a well-formed config file."""
        sdlc_dir = tmp_path / ".sdlc"
        sdlc_dir.mkdir()
        (sdlc_dir / "config.yaml").write_text(
            "objective:\n"
            "  max_iterations: 10\n"
            "  max_turns: 800\n"
            "  evaluation:\n"
            '    commands:\n      - "pytest"\n      - "ruff check"\n'
        )
        result = load_objective_config(project_dir=str(tmp_path))
        assert result["max_iterations"] == 10
        assert result["max_turns"] == 800
        assert result["evaluation"]["commands"] == ["pytest", "ruff check"]

    def test_load_partial_config(self, tmp_path):
        """Missing fields get defaults filled in."""
        sdlc_dir = tmp_path / ".sdlc"
        sdlc_dir.mkdir()
        (sdlc_dir / "config.yaml").write_text(
            "objective:\n  max_iterations: 3\n"
        )
        result = load_objective_config(project_dir=str(tmp_path))
        assert result["max_iterations"] == 3
        assert result["max_turns"] == 500  # default
        assert result["evaluation"]["commands"] == []  # default

    def test_load_empty_evaluation(self, tmp_path):
        """Empty evaluation section returns defaults."""
        sdlc_dir = tmp_path / ".sdlc"
        sdlc_dir.mkdir()
        (sdlc_dir / "config.yaml").write_text(
            "objective:\n  max_iterations: 2\n  evaluation:\n"
        )
        result = load_objective_config(project_dir=str(tmp_path))
        assert result["max_iterations"] == 2
        assert result["evaluation"]["commands"] == []

    def test_load_with_evaluation_commands(self, tmp_path):
        """Reads evaluation commands from config."""
        sdlc_dir = tmp_path / ".sdlc"
        sdlc_dir.mkdir()
        (sdlc_dir / "config.yaml").write_text(
            "objective:\n"
            "  evaluation:\n"
            "    commands:\n"
            '      - "uv run pytest tests/ -v"\n'
            '      - "uv run ruff check src/"\n'
            '      - "uv run mypy src/"\n'
        )
        result = load_objective_config(project_dir=str(tmp_path))
        assert result["evaluation"]["commands"] == [
            "uv run pytest tests/ -v",
            "uv run ruff check src/",
            "uv run mypy src/",
        ]


# ---------------------------------------------------------------------------
# execute_objective: autonomous mode
# ---------------------------------------------------------------------------


class TestExecuteObjectiveAutonomous:
    def test_spawns_session_with_correct_tools(self, autonomous_executor):
        """Verify autonomous mode spawns one session with correct allowed_tools."""
        final_result = {
            "result": textwrap.dedent("""\
                ---OBJECTIVE-OUTCOME---
                run_id: R-obj001
                iterations_used: 2/5
                status: ACHIEVED
                summary: Done
                ---END-OUTCOME---
            """),
        }

        with patch.object(
            autonomous_executor,
            "_spawn_claude_session",
            return_value=final_result,
        ) as mock_spawn:
            result = autonomous_executor.execute_objective(
                description="Build a REST API",
                run_id="R-obj001",
                max_iterations=5,
            )

        # Verify single call
        assert mock_spawn.call_count == 1
        call_kwargs = mock_spawn.call_args
        # Check allowed_tools includes Task and mcp__asdlc__*
        tools = call_kwargs.kwargs.get("allowed_tools") or call_kwargs[1].get(
            "allowed_tools"
        )
        assert "Task" in tools
        assert "TaskOutput" in tools
        assert "TaskStop" in tools
        assert "mcp__asdlc__*" in tools
        assert "Read" in tools
        assert "Write" in tools
        assert "Edit" in tools
        assert "Bash" in tools
        assert "Glob" in tools
        assert "Grep" in tools
        # Check prompt content
        prompt = call_kwargs.kwargs.get("prompt") or call_kwargs[0][0]
        assert "Build a REST API" in prompt
        assert "R-obj001" in prompt
        # Verify parsed result
        assert result["status"] == "ACHIEVED"
        assert result["iterations_used"] == "2/5"

    def test_returns_parsed_result(self, autonomous_executor):
        """Verify autonomous mode returns properly parsed outcome."""
        final_result = {
            "result": textwrap.dedent("""\
                ---OBJECTIVE-OUTCOME---
                run_id: R-obj002
                iterations: 3
                status: PARTIAL
                prds_created: 2
                completed: 4
                failed: 1
                skipped: 0
                summary: Most tasks done
                ---END-OUTCOME---
            """),
        }

        with patch.object(
            autonomous_executor,
            "_spawn_claude_session",
            return_value=final_result,
        ):
            result = autonomous_executor.execute_objective(
                description="Refactor auth",
                run_id="R-obj002",
            )

        assert result["prds_created"] == "2"
        assert result["completed"] == "4"
        assert result["failed"] == "1"
        assert result["skipped"] == "0"
        assert result["summary"] == "Most tasks done"


# ---------------------------------------------------------------------------
# execute_objective: supervised mode
# ---------------------------------------------------------------------------


class TestExecuteObjectiveSupervised:
    def test_detects_checkpoint_and_calls_await(self, executor, runs_dir):
        """Verify supervised mode detects ---ITERATION-CHECKPOINT--- and pauses."""
        run_id = "R-obj-sup01"
        _write_run(run_id, {"status": "running", "config": {}})

        # First call: outputs checkpoint marker
        first_result = {
            "session_id": "sess-obj-1",
            "result": "Iteration 1 done.\n---ITERATION-CHECKPOINT---\n",
        }
        # Second call: completes
        second_result = {
            "session_id": "sess-obj-1",
            "result": textwrap.dedent("""\
                ---OBJECTIVE-OUTCOME---
                run_id: R-obj-sup01
                iterations_used: 2/5
                status: ACHIEVED
                summary: All criteria met
                ---END-OUTCOME---
            """),
        }

        call_count = 0

        def mock_spawn(prompt, max_turns=200, allowed_tools=None, session_id=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return first_result
            return second_result

        await_calls: list[tuple[str, int]] = []

        def mock_await(rid, iteration, outcomes):
            await_calls.append((rid, iteration))
            _update_run(rid, status="running", config={"approval_message": "Continue"})

        with (
            patch.object(executor, "_spawn_claude_session", side_effect=mock_spawn),
            patch.object(
                executor, "_await_user_confirmation", side_effect=mock_await
            ),
        ):
            result = executor.execute_objective(
                description="Build feature",
                run_id=run_id,
            )

        assert call_count == 2
        assert len(await_calls) == 1
        assert await_calls[0] == (run_id, 0)
        assert result["status"] == "ACHIEVED"

    def test_resumes_with_feedback(self, executor, runs_dir):
        """Verify resume prompt includes user approval message."""
        run_id = "R-obj-sup02"
        _write_run(run_id, {"status": "running", "config": {}})

        call_prompts: list[str] = []

        def mock_spawn(prompt, max_turns=200, allowed_tools=None, session_id=None):
            call_prompts.append(prompt)
            if len(call_prompts) == 1:
                return {
                    "session_id": "sess-obj-2",
                    "result": "---ITERATION-CHECKPOINT---",
                }
            return {"session_id": "sess-obj-2", "result": "done"}

        def mock_await(rid, iteration, outcomes):
            _update_run(
                rid,
                status="running",
                config={"approval_message": "Focus on tests"},
            )

        with (
            patch.object(executor, "_spawn_claude_session", side_effect=mock_spawn),
            patch.object(
                executor, "_await_user_confirmation", side_effect=mock_await
            ),
        ):
            executor.execute_objective(
                description="Improve coverage",
                run_id=run_id,
            )

        assert len(call_prompts) == 2
        assert "User approved iteration 1" in call_prompts[1]
        assert "Focus on tests" in call_prompts[1]

    def test_completes_when_no_checkpoint(self, executor, runs_dir):
        """Verify supervised mode returns immediately when no checkpoint marker."""
        final_result = {
            "session_id": "sess-obj-3",
            "result": textwrap.dedent("""\
                ---OBJECTIVE-OUTCOME---
                run_id: R-obj-sup03
                iterations_used: 1/5
                status: ACHIEVED
                summary: Done in one shot
                ---END-OUTCOME---
            """),
        }

        await_calls: list[Any] = []

        with (
            patch.object(
                executor, "_spawn_claude_session", return_value=final_result
            ),
            patch.object(
                executor,
                "_await_user_confirmation",
                side_effect=lambda *a: await_calls.append(a),
            ),
        ):
            result = executor.execute_objective(
                description="Quick fix",
                run_id="R-obj-sup03",
            )

        assert len(await_calls) == 0
        assert result["status"] == "ACHIEVED"
        assert result["summary"] == "Done in one shot"

    def test_session_id_passed_on_resume(self, executor, runs_dir):
        """Verify session_id is passed via --resume on subsequent calls."""
        run_id = "R-obj-sup04"
        _write_run(run_id, {"status": "running", "config": {}})

        session_ids_seen: list[str | None] = []

        def mock_spawn(prompt, max_turns=200, allowed_tools=None, session_id=None):
            session_ids_seen.append(session_id)
            if len(session_ids_seen) == 1:
                return {
                    "session_id": "sess-obj-keep",
                    "result": "---ITERATION-CHECKPOINT---",
                }
            return {"session_id": "sess-obj-keep", "result": "final"}

        def mock_await(rid, iteration, outcomes):
            _update_run(rid, status="running", config={})

        with (
            patch.object(executor, "_spawn_claude_session", side_effect=mock_spawn),
            patch.object(
                executor, "_await_user_confirmation", side_effect=mock_await
            ),
        ):
            executor.execute_objective(
                description="Test resume",
                run_id=run_id,
            )

        assert session_ids_seen[0] is None  # First call: no session_id
        assert session_ids_seen[1] == "sess-obj-keep"  # Resume: session_id passed


# ---------------------------------------------------------------------------
# _build_objective_prompt
# ---------------------------------------------------------------------------


class TestBuildObjectivePrompt:
    def test_includes_description(self, autonomous_executor):
        """Verify prompt contains the objective description."""
        prompt = autonomous_executor._build_objective_prompt(
            description="Build a payment gateway integration",
            run_id="R-prompt01",
            max_iterations=3,
        )
        assert "Build a payment gateway integration" in prompt
        assert "R-prompt01" in prompt
        assert "3" in prompt

    def test_supervised_includes_checkpoint_instructions(self, executor):
        """Verify supervised mode prompt includes checkpoint instructions."""
        prompt = executor._build_objective_prompt(
            description="Test objective",
            run_id="R-prompt02",
            max_iterations=5,
        )
        assert "SUPERVISED MODE" in prompt
        assert "---ITERATION-CHECKPOINT---" in prompt
        assert "STOP and wait" in prompt

    def test_autonomous_includes_no_ask_instructions(self, autonomous_executor):
        """Verify autonomous mode prompt includes no-ask instructions."""
        prompt = autonomous_executor._build_objective_prompt(
            description="Test objective",
            run_id="R-prompt03",
            max_iterations=5,
        )
        assert "Do not use AskUserQuestion" in prompt
        assert "Make autonomous decisions" in prompt
        # Should NOT have supervised checkpoint instructions
        assert "SUPERVISED MODE" not in prompt
        assert "---ITERATION-CHECKPOINT---" not in prompt

    def test_includes_objective_file(self, autonomous_executor):
        """Verify prompt includes objective file path when provided."""
        prompt = autonomous_executor._build_objective_prompt(
            description="Build feature",
            run_id="R-prompt04",
            max_iterations=5,
            objective_file="/path/to/objective.md",
        )
        assert "/path/to/objective.md" in prompt
        assert "Read this file" in prompt

    def test_no_objective_file_section_when_none(self, autonomous_executor):
        """Verify no file section when objective_file is None."""
        prompt = autonomous_executor._build_objective_prompt(
            description="Build feature",
            run_id="R-prompt05",
            max_iterations=5,
            objective_file=None,
        )
        assert "Objective specification file" not in prompt

    def test_includes_outcome_markers(self, autonomous_executor):
        """Verify prompt includes the structured output markers."""
        prompt = autonomous_executor._build_objective_prompt(
            description="Test",
            run_id="R-prompt06",
            max_iterations=3,
        )
        assert "---OBJECTIVE-OUTCOME---" in prompt
        assert "---END-OUTCOME---" in prompt

    def test_includes_orchestrator_steps(self, autonomous_executor):
        """Verify prompt includes the SDLC orchestrator loop steps."""
        prompt = autonomous_executor._build_objective_prompt(
            description="Test",
            run_id="R-prompt07",
            max_iterations=3,
        )
        assert "mcp__asdlc__create_prd" in prompt
        assert "mcp__asdlc__create_task" in prompt
        assert "mcp__asdlc__create_sprint" in prompt
        assert "acceptance criteria" in prompt.lower()

    def test_includes_all_four_phases(self, autonomous_executor):
        """Verify prompt contains all four SDLC loop phases."""
        prompt = autonomous_executor._build_objective_prompt(
            description="Test phases",
            run_id="R-prompt08",
            max_iterations=3,
        )
        assert "Phase 1: Planning" in prompt
        assert "Phase 2: Sprint Execution" in prompt
        assert "Phase 3: Evaluation" in prompt
        assert "Phase 3b: Iteration" in prompt
        assert "Phase 4: Completion" in prompt

    def test_includes_anti_repetition_rule(self, autonomous_executor):
        """Verify prompt contains the anti-repetition rule for iterations."""
        prompt = autonomous_executor._build_objective_prompt(
            description="Test anti-repeat",
            run_id="R-prompt09",
            max_iterations=3,
        )
        assert "ANTI-REPETITION RULE" in prompt
        assert "DIFFERENT strategy" in prompt
        assert "Never repeat" in prompt
        assert "failing approach" in prompt

    def test_includes_file_content_instructions(self, autonomous_executor):
        """Verify prompt instructs writing content via Write tool, not MCP params."""
        prompt = autonomous_executor._build_objective_prompt(
            description="Test content",
            run_id="R-prompt10",
            max_iterations=3,
        )
        assert "Write tool" in prompt
        assert "file_path" in prompt

    def test_includes_log_correction_tool(self, autonomous_executor):
        """Verify prompt references the log_correction tool."""
        prompt = autonomous_executor._build_objective_prompt(
            description="Test corrections",
            run_id="R-prompt11",
            max_iterations=3,
        )
        assert "mcp__asdlc__log_correction" in prompt

    def test_includes_lesson_learn_files(self, autonomous_executor):
        """Verify prompt instructs reading lesson-learn files."""
        prompt = autonomous_executor._build_objective_prompt(
            description="Test lessons",
            run_id="R-prompt12",
            max_iterations=3,
        )
        assert "lesson-learn.md" in prompt

    def test_outcome_block_has_required_fields(self, autonomous_executor):
        """Verify the outcome block template includes all required fields."""
        prompt = autonomous_executor._build_objective_prompt(
            description="Test fields",
            run_id="R-prompt13",
            max_iterations=3,
        )
        assert "iterations_used:" in prompt
        assert "status: COMPLETED|PARTIAL|FAILED" in prompt
        assert "sprints_created:" in prompt
        assert "prds_created:" in prompt
        assert "completed:" in prompt
        assert "failed:" in prompt
        assert "skipped:" in prompt
        assert "tests_passing:" in prompt
        assert "criteria_met:" in prompt
        assert "criteria_not_met:" in prompt

    def test_includes_get_context_call(self, autonomous_executor):
        """Verify prompt instructs calling get_context for project context."""
        prompt = autonomous_executor._build_objective_prompt(
            description="Test context",
            run_id="R-prompt14",
            max_iterations=3,
        )
        assert "mcp__asdlc__get_context" in prompt

    def test_includes_submit_review(self, autonomous_executor):
        """Verify prompt instructs calling submit_review for tasks."""
        prompt = autonomous_executor._build_objective_prompt(
            description="Test review",
            run_id="R-prompt15",
            max_iterations=3,
        )
        assert "mcp__asdlc__submit_review" in prompt

    def test_max_iterations_in_evaluation_decision(self, autonomous_executor):
        """Verify max_iterations value appears in the evaluation decision logic."""
        prompt = autonomous_executor._build_objective_prompt(
            description="Test max iter",
            run_id="R-prompt16",
            max_iterations=7,
        )
        # Should reference max_iterations in the evaluation phase decision
        assert "7" in prompt
        assert "PARTIAL" in prompt

    def test_supervised_no_autonomous_instructions(self, executor):
        """Verify supervised mode does NOT include AUTONOMOUS MODE block."""
        prompt = executor._build_objective_prompt(
            description="Test supervised only",
            run_id="R-prompt17",
            max_iterations=5,
        )
        assert "SUPERVISED MODE" in prompt
        assert "AUTONOMOUS MODE" not in prompt

    def test_autonomous_no_supervised_instructions(self, autonomous_executor):
        """Verify autonomous mode does NOT include SUPERVISED MODE block."""
        prompt = autonomous_executor._build_objective_prompt(
            description="Test autonomous only",
            run_id="R-prompt18",
            max_iterations=5,
        )
        assert "AUTONOMOUS MODE" in prompt
        assert "SUPERVISED MODE" not in prompt


# ---------------------------------------------------------------------------
# _parse_objective_result
# ---------------------------------------------------------------------------


class TestParseObjectiveResult:
    def test_extracts_block(self, executor):
        """Verify outcome block is parsed correctly."""
        result = {
            "result": textwrap.dedent("""\
                Some preamble.
                ---OBJECTIVE-OUTCOME---
                run_id: R-parse01
                iterations_used: 3/5
                status: ACHIEVED
                prds_created: 2
                completed: 8
                failed: 0
                skipped: 0
                summary: All acceptance criteria met
                ---END-OUTCOME---
                Some trailing text.
            """),
        }
        parsed = executor._parse_objective_result(result)
        assert parsed["run_id"] == "R-parse01"
        assert parsed["iterations_used"] == "3/5"
        assert parsed["status"] == "ACHIEVED"
        assert parsed["prds_created"] == "2"
        assert parsed["completed"] == "8"
        assert parsed["failed"] == "0"
        assert parsed["skipped"] == "0"
        assert parsed["summary"] == "All acceptance criteria met"
        assert "raw" in parsed

    def test_handles_error(self, executor):
        """Verify error status is propagated correctly."""
        result = {"status": "error", "error": "Session timed out"}
        parsed = executor._parse_objective_result(result)
        assert parsed["status"] == "error"
        assert parsed["error"] == "Session timed out"
        assert "raw" in parsed

    def test_handles_missing_block(self, executor):
        """Verify missing markers result in default status."""
        result = {"result": "No outcome markers here."}
        parsed = executor._parse_objective_result(result)
        # When markers are not found, _extract_outcome_block returns {}
        # and setdefault provides "completed"
        assert parsed["status"] == "completed"
        assert "raw" in parsed


# ---------------------------------------------------------------------------
# __main__ entry point: objective mode
# ---------------------------------------------------------------------------


class TestMainObjectiveMode:
    def test_dispatches_to_execute_objective(self, mock_claude_path, runs_dir):
        """Verify __main__ dispatches to execute_objective for objective mode."""
        with (
            patch("a_sdlc.executor.get_storage"),
            patch(
                "a_sdlc.executor.load_daemon_config",
                return_value={"mode": "session"},
            ),
            patch.object(
                Executor,
                "execute_objective",
                return_value={"status": "completed"},
            ) as mock_execute,
            patch(
                "sys.argv",
                [
                    "executor",
                    "--mode",
                    "objective",
                    "--description",
                    "Build a REST API for user management",
                    "--run-id",
                    "R-main-obj01",
                    "--max-iterations",
                    "3",
                    "--objective-file",
                    "/tmp/obj.md",
                ],
            ),
        ):
            _main()

        mock_execute.assert_called_once_with(
            description="Build a REST API for user management",
            run_id="R-main-obj01",
            max_iterations=3,
            objective_file="/tmp/obj.md",
        )
        # Verify run state updated to completed
        data = _read_run("R-main-obj01")
        assert data["status"] == "completed"

    def test_requires_description(self, mock_claude_path, runs_dir):
        """Verify objective mode requires --description argument."""
        with (
            patch("a_sdlc.executor.get_storage"),
            patch(
                "a_sdlc.executor.load_daemon_config",
                return_value={"mode": "session"},
            ),
            patch(
                "sys.argv",
                [
                    "executor",
                    "--mode",
                    "objective",
                    "--run-id",
                    "R-main-obj02",
                ],
            ),
            pytest.raises(SystemExit),
        ):
            _main()

        data = _read_run("R-main-obj02")
        assert data["status"] == "failed"
        assert "Missing --description" in data["error"]

    def test_default_max_iterations(self, mock_claude_path, runs_dir):
        """Verify default max_iterations is 5 when not specified."""
        with (
            patch("a_sdlc.executor.get_storage"),
            patch(
                "a_sdlc.executor.load_daemon_config",
                return_value={"mode": "session"},
            ),
            patch.object(
                Executor,
                "execute_objective",
                return_value={"status": "completed"},
            ) as mock_execute,
            patch(
                "sys.argv",
                [
                    "executor",
                    "--mode",
                    "objective",
                    "--description",
                    "Quick task",
                    "--run-id",
                    "R-main-obj03",
                ],
            ),
        ):
            _main()

        call_kwargs = mock_execute.call_args.kwargs
        assert call_kwargs["max_iterations"] == 5
        assert call_kwargs["objective_file"] is None

    def test_exception_marks_run_as_failed(self, mock_claude_path, runs_dir):
        """Verify unhandled exceptions in objective mode mark run as failed."""
        with (
            patch("a_sdlc.executor.get_storage"),
            patch(
                "a_sdlc.executor.load_daemon_config",
                return_value={"mode": "session"},
            ),
            patch.object(
                Executor,
                "execute_objective",
                side_effect=RuntimeError("objective boom"),
            ),
            patch(
                "sys.argv",
                [
                    "executor",
                    "--mode",
                    "objective",
                    "--description",
                    "Will fail",
                    "--run-id",
                    "R-main-obj04",
                ],
            ),
            pytest.raises(SystemExit),
        ):
            _main()

        data = _read_run("R-main-obj04")
        assert data["status"] == "failed"
        assert "objective boom" in data["error"]

    def test_triggers_notifications_on_completion(self, mock_claude_path, runs_dir):
        """Verify notification hooks are triggered after objective completes."""
        outcome = {"status": "completed", "completed": 5, "failed": 0}
        with (
            patch("a_sdlc.executor.get_storage"),
            patch(
                "a_sdlc.executor.load_daemon_config",
                return_value={"mode": "session", "notifications": [{"type": "file", "path": "/tmp/test.md"}]},
            ),
            patch.object(
                Executor,
                "execute_objective",
                return_value=outcome,
            ),
            patch("a_sdlc.notifications.run_notification_hooks") as mock_notify,
            patch(
                "sys.argv",
                [
                    "executor",
                    "--mode",
                    "objective",
                    "--description",
                    "Notify me",
                    "--run-id",
                    "R-notify-01",
                ],
            ),
        ):
            _main()

        mock_notify.assert_called_once_with("R-notify-01", outcome, {"mode": "session", "notifications": [{"type": "file", "path": "/tmp/test.md"}]})
