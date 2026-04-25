"""Tests for execution adapters (adapters.py).

Covers:
- MockAdapter returns configurable results
- ClaudeCodeAdapter command construction and error handling
- GeminiAdapter command construction and error handling
- create_adapter() factory resolves names correctly
- execute_task MCP tool launches non-blocking subprocess
- check_execution reads log and reports status
- stop_execution kills process groups
- Process registry tracks and cleans up children
- _build_execute_task_prompt includes all sections
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from a_sdlc.adapters import (
    ClaudeCodeAdapter,
    GeminiAdapter,
    MockAdapter,
    _active_processes,
    _reap_if_dead,
    check_execution,
    create_adapter,
    stop_execution,
)

# ---------------------------------------------------------------------------
# MockAdapter
# ---------------------------------------------------------------------------


class TestMockAdapter:
    def test_returns_default_result(self):
        adapter = MockAdapter()
        result = adapter.execute(
            prompt="test", max_turns=10, working_dir="/tmp"
        )
        assert result["status"] == "ok"
        assert "---TASK-OUTCOME---" in result["result"]
        assert "MOCK-T00001" in result["result"]

    def test_returns_custom_result(self):
        custom = {"status": "ok", "result": "custom output"}
        adapter = MockAdapter(result=custom)
        result = adapter.execute(
            prompt="test", max_turns=10, working_dir="/tmp"
        )
        assert result["result"] == "custom output"

    def test_returns_copy_not_reference(self):
        adapter = MockAdapter()
        r1 = adapter.execute(prompt="test", max_turns=10, working_dir="/tmp")
        r2 = adapter.execute(prompt="test", max_turns=10, working_dir="/tmp")
        r1["extra"] = "modified"
        assert "extra" not in r2

    def test_launch_fallback_writes_log(self, tmp_path):
        adapter = MockAdapter()
        with patch("a_sdlc.adapters._ensure_log_dir", return_value=tmp_path):
            handle = adapter.launch(
                prompt="test",
                max_turns=10,
                working_dir="/tmp",
                task_id="MOCK-T00001",
            )
        assert handle["status"] == "completed"
        assert handle["pid"] == 0
        log = Path(handle["log_path"])
        assert log.exists()
        data = json.loads(log.read_text().strip())
        assert data["status"] == "ok"


# ---------------------------------------------------------------------------
# ClaudeCodeAdapter
# ---------------------------------------------------------------------------


class TestClaudeCodeAdapter:
    def test_init_fails_without_claude(self):
        with (
            patch("shutil.which", return_value=None),
            pytest.raises(RuntimeError, match="Claude Code CLI not found"),
        ):
            ClaudeCodeAdapter()

    def test_builds_correct_command(self):
        with patch("shutil.which", return_value="/usr/local/bin/claude"):
            adapter = ClaudeCodeAdapter()

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps(
            {"session_id": "sess-1", "result": "done"}
        )
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            adapter.execute(
                prompt="do task",
                max_turns=50,
                working_dir="/home/project",
                allowed_tools=["Read", "Write"],
            )

        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "/usr/local/bin/claude"
        assert "-p" in cmd
        assert "do task" in cmd
        assert "--output-format" in cmd
        assert "json" in cmd
        assert "--max-turns" in cmd
        assert "50" in cmd
        assert "--allowedTools" in cmd
        assert "Read,Write" in cmd
        assert "--dangerously-skip-permissions" in cmd
        assert mock_run.call_args[1]["cwd"] == "/home/project"

    def test_skip_permissions_disabled(self):
        with patch("shutil.which", return_value="/usr/local/bin/claude"):
            adapter = ClaudeCodeAdapter(skip_permissions=False)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({"result": "done"})
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            adapter.execute(
                prompt="test",
                max_turns=10,
                working_dir="/tmp",
            )

        cmd = mock_run.call_args[0][0]
        assert "--dangerously-skip-permissions" not in cmd

    def test_launch_uses_stream_json(self, tmp_path):
        with patch("shutil.which", return_value="/usr/local/bin/claude"):
            adapter = ClaudeCodeAdapter()

        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.poll.return_value = None  # process still running

        with (
            patch("a_sdlc.adapters._ensure_log_dir", return_value=tmp_path),
            patch("builtins.open", MagicMock()),
            patch("subprocess.Popen", return_value=mock_proc) as mock_popen,
            patch("a_sdlc.adapters.time"),
        ):
            handle = adapter.launch(
                prompt="do task",
                max_turns=50,
                working_dir=str(tmp_path),
                task_id="PROJ-T00001",
                allowed_tools=["Read", "Write"],
            )

        assert handle["pid"] == 12345
        assert handle["status"] == "running"
        assert "PROJ-T00001" in handle["log_path"]

        cmd = mock_popen.call_args[0][0]
        assert "--output-format" in cmd
        idx = cmd.index("--output-format")
        assert cmd[idx + 1] == "stream-json"
        assert "--verbose" in cmd
        assert "--dangerously-skip-permissions" in cmd

        # Verify subprocess isolation: stdin closed, new session, no fd leaks
        popen_kwargs = mock_popen.call_args[1]
        assert popen_kwargs["stdin"] == subprocess.DEVNULL
        assert popen_kwargs["start_new_session"] is True

        # Clean up registry
        _active_processes.pop(12345, None)

    def test_launch_registers_in_process_registry(self, tmp_path):
        with patch("shutil.which", return_value="/usr/local/bin/claude"):
            adapter = ClaudeCodeAdapter()

        mock_proc = MagicMock()
        mock_proc.pid = 54321
        mock_proc.poll.return_value = None  # process still running

        with (
            patch("a_sdlc.adapters._ensure_log_dir", return_value=tmp_path),
            patch("builtins.open", MagicMock()),
            patch("subprocess.Popen", return_value=mock_proc),
            patch("a_sdlc.adapters.time"),
        ):
            handle = adapter.launch(
                prompt="test",
                max_turns=10,
                working_dir=str(tmp_path),
                task_id="REG-T00001",
            )

        assert handle["pid"] == 54321
        assert 54321 in _active_processes
        assert _active_processes[54321] is mock_proc

        # Clean up
        _active_processes.pop(54321, None)

    def test_launch_sets_child_env(self, tmp_path):
        """launch() passes A_SDLC_CHILD=1 in the subprocess environment."""
        with patch("shutil.which", return_value="/usr/local/bin/claude"):
            adapter = ClaudeCodeAdapter()

        mock_proc = MagicMock()
        mock_proc.pid = 33333
        mock_proc.poll.return_value = None  # process still running

        with (
            patch("a_sdlc.adapters._ensure_log_dir", return_value=tmp_path),
            patch("builtins.open", MagicMock()),
            patch("subprocess.Popen", return_value=mock_proc) as mock_popen,
            patch("a_sdlc.adapters.time"),
        ):
            adapter.launch(
                prompt="test",
                max_turns=10,
                working_dir=str(tmp_path),
                task_id="ENV-T00001",
            )

        popen_kwargs = mock_popen.call_args[1]
        assert "env" in popen_kwargs
        assert popen_kwargs["env"]["A_SDLC_CHILD"] == "1"

        # Clean up
        _active_processes.pop(33333, None)

    def test_launch_handles_popen_failure(self, tmp_path):
        with patch("shutil.which", return_value="/usr/local/bin/claude"):
            adapter = ClaudeCodeAdapter()

        with (
            patch("a_sdlc.adapters._ensure_log_dir", return_value=tmp_path),
            patch("builtins.open", MagicMock()),
            patch("subprocess.Popen", side_effect=OSError("No such file")),
        ):
            handle = adapter.launch(
                prompt="test",
                max_turns=10,
                working_dir="/tmp",
                task_id="ERR-T00001",
            )

        assert handle["status"] == "error"
        assert "Failed to spawn" in handle["error"]
        assert handle["pid"] == 0

    def test_handles_timeout(self):
        with patch("shutil.which", return_value="/usr/local/bin/claude"):
            adapter = ClaudeCodeAdapter()

        with patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=["claude"], timeout=60),
        ):
            result = adapter.execute(
                prompt="test", max_turns=1, working_dir="/tmp"
            )
        assert result["status"] == "error"
        assert "timed out" in result["error"]

    def test_handles_nonzero_exit(self):
        with patch("shutil.which", return_value="/usr/local/bin/claude"):
            adapter = ClaudeCodeAdapter()

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "some error"

        with patch("subprocess.run", return_value=mock_result):
            result = adapter.execute(
                prompt="test", max_turns=10, working_dir="/tmp"
            )
        assert result["status"] == "error"
        assert result["exit_code"] == 1

    def test_handles_invalid_json(self):
        with patch("shutil.which", return_value="/usr/local/bin/claude"):
            adapter = ClaudeCodeAdapter()

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "not json"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            result = adapter.execute(
                prompt="test", max_turns=10, working_dir="/tmp"
            )
        assert result["status"] == "error"
        assert "json" in result["error"].lower()

    def test_returns_session_id(self):
        with patch("shutil.which", return_value="/usr/local/bin/claude"):
            adapter = ClaudeCodeAdapter()

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps(
            {"session_id": "abc-123", "result": "done"}
        )
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            result = adapter.execute(
                prompt="test", max_turns=10, working_dir="/tmp"
            )
        assert result["session_id"] == "abc-123"

    def test_no_allowed_tools_omits_flag(self):
        with patch("shutil.which", return_value="/usr/local/bin/claude"):
            adapter = ClaudeCodeAdapter()

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({"result": "done"})
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            adapter.execute(
                prompt="test", max_turns=10, working_dir="/tmp"
            )

        cmd = mock_run.call_args[0][0]
        assert "--allowedTools" not in cmd


# ---------------------------------------------------------------------------
# GeminiAdapter
# ---------------------------------------------------------------------------


class TestGeminiAdapter:
    def test_init_fails_without_gemini(self):
        with (
            patch("shutil.which", return_value=None),
            pytest.raises(RuntimeError, match="Gemini CLI not found"),
        ):
            GeminiAdapter()

    def test_builds_correct_command(self):
        with patch("shutil.which", return_value="/usr/local/bin/gemini"):
            adapter = GeminiAdapter()

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "task done"

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            result = adapter.execute(
                prompt="do gemini task",
                max_turns=30,
                working_dir="/home/project",
            )

        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "/usr/local/bin/gemini"
        assert "-p" in cmd
        assert "do gemini task" in cmd
        assert result["status"] == "ok"
        assert result["result"] == "task done"

    def test_handles_timeout(self):
        with patch("shutil.which", return_value="/usr/local/bin/gemini"):
            adapter = GeminiAdapter()

        with patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=["gemini"], timeout=60),
        ):
            result = adapter.execute(
                prompt="test", max_turns=1, working_dir="/tmp"
            )
        assert result["status"] == "error"
        assert "timed out" in result["error"]

    def test_handles_nonzero_exit(self):
        with patch("shutil.which", return_value="/usr/local/bin/gemini"):
            adapter = GeminiAdapter()

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "gemini error"

        with patch("subprocess.run", return_value=mock_result):
            result = adapter.execute(
                prompt="test", max_turns=10, working_dir="/tmp"
            )
        assert result["status"] == "error"
        assert result["exit_code"] == 1


# ---------------------------------------------------------------------------
# create_adapter factory
# ---------------------------------------------------------------------------


class TestCreateAdapter:
    def test_creates_mock_by_default(self):
        adapter = create_adapter()
        assert isinstance(adapter, MockAdapter)

    def test_creates_mock_explicitly(self):
        adapter = create_adapter("mock")
        assert isinstance(adapter, MockAdapter)

    def test_creates_claude_adapter(self):
        with patch("shutil.which", return_value="/usr/local/bin/claude"):
            adapter = create_adapter("claude")
        assert isinstance(adapter, ClaudeCodeAdapter)

    def test_creates_gemini_adapter(self):
        with patch("shutil.which", return_value="/usr/local/bin/gemini"):
            adapter = create_adapter("gemini")
        assert isinstance(adapter, GeminiAdapter)

    def test_unknown_adapter_raises(self):
        with pytest.raises(ValueError, match="Unknown adapter.*'invalid'"):
            create_adapter("invalid")


# ---------------------------------------------------------------------------
# Process registry
# ---------------------------------------------------------------------------


class TestProcessRegistry:
    def test_reap_dead_process(self):
        mock_proc = MagicMock()
        mock_proc.wait.return_value = 0
        _active_processes[77777] = mock_proc

        _reap_if_dead(77777)

        assert 77777 not in _active_processes
        mock_proc.wait.assert_called_once_with(timeout=0)

    def test_reap_living_process_stays(self):
        mock_proc = MagicMock()
        mock_proc.wait.side_effect = subprocess.TimeoutExpired(cmd=[], timeout=0)
        _active_processes[88888] = mock_proc

        _reap_if_dead(88888)

        assert 88888 in _active_processes
        # Clean up
        _active_processes.pop(88888, None)

    def test_reap_unknown_pid_is_noop(self):
        _reap_if_dead(99999)  # should not raise


# ---------------------------------------------------------------------------
# execute_task MCP tool (non-blocking)
# ---------------------------------------------------------------------------


class TestExecuteTaskMCPTool:
    """Tests for the execute_task() MCP tool in server/__init__.py."""

    def test_returns_launch_handle(self):
        from a_sdlc.server import execute_task

        mock_db = MagicMock()
        mock_db.get_task.return_value = {
            "id": "PROJ-T00001",
            "title": "Add login",
            "file_path": "/content/tasks/PROJ-T00001.md",
            "prd_id": "PROJ-P0001",
        }

        class FakeAdapter:
            def launch(self, **kwargs):
                return {
                    "pid": 99999,
                    "log_path": "/tmp/PROJ-T00001.jsonl",
                    "status": "running",
                }

        with (
            patch("a_sdlc.server.get_db", return_value=mock_db),
            patch("a_sdlc.adapters.create_adapter", return_value=FakeAdapter()),
        ):
            result = execute_task(task_id="PROJ-T00001", executor="mock")

        assert result["status"] == "launched"
        assert result["task_id"] == "PROJ-T00001"
        assert result["pid"] == 99999
        assert result["log_path"] == "/tmp/PROJ-T00001.jsonl"

    def test_handles_missing_task(self):
        from a_sdlc.server import execute_task

        mock_db = MagicMock()
        mock_db.get_task.return_value = None

        with patch("a_sdlc.server.get_db", return_value=mock_db):
            result = execute_task(task_id="PROJ-T99999")

        assert result["status"] == "error"
        assert "not found" in result["message"].lower()

    def test_handles_invalid_executor(self):
        from a_sdlc.server import execute_task

        mock_db = MagicMock()
        mock_db.get_task.return_value = {
            "id": "PROJ-T00001",
            "title": "Test",
            "file_path": "/tmp/task.md",
            "prd_id": None,
        }

        with patch("a_sdlc.server.get_db", return_value=mock_db):
            result = execute_task(
                task_id="PROJ-T00001", executor="nonexistent"
            )

        assert result["status"] == "error"
        assert "unknown adapter" in result["message"].lower()

    def test_dispatch_info_passed_to_prompt(self):
        from a_sdlc.server import execute_task

        mock_db = MagicMock()
        mock_db.get_task.return_value = {
            "id": "PROJ-T00002",
            "title": "Create login",
            "file_path": "/content/tasks/PROJ-T00002.md",
            "prd_id": None,
        }

        captured_prompt = {}

        class CapturingAdapter:
            def launch(self, prompt, **kwargs):
                captured_prompt["prompt"] = prompt
                return {"pid": 0, "log_path": "/tmp/test.jsonl", "status": "completed"}

        with (
            patch("a_sdlc.server.get_db", return_value=mock_db),
            patch("a_sdlc.adapters.create_adapter", return_value=CapturingAdapter()),
        ):
            execute_task(
                task_id="PROJ-T00002",
                executor="mock",
                dispatch_info="dependency_outcomes:\n  PROJ-T00001: OAuth config added",
            )

        assert "## Dispatch Info" in captured_prompt["prompt"]
        assert "PROJ-T00001: OAuth config added" in captured_prompt["prompt"]

    def test_no_dispatch_info_omits_section(self):
        from a_sdlc.server import execute_task

        mock_db = MagicMock()
        mock_db.get_task.return_value = {
            "id": "PROJ-T00001",
            "title": "Task",
            "file_path": "/tmp/task.md",
            "prd_id": None,
        }

        captured_prompt = {}

        class CapturingAdapter:
            def launch(self, prompt, **kwargs):
                captured_prompt["prompt"] = prompt
                return {"pid": 0, "log_path": "/tmp/test.jsonl", "status": "completed"}

        with (
            patch("a_sdlc.server.get_db", return_value=mock_db),
            patch("a_sdlc.adapters.create_adapter", return_value=CapturingAdapter()),
        ):
            execute_task(task_id="PROJ-T00001", executor="mock")

        assert "## Dispatch Info" not in captured_prompt["prompt"]


# ---------------------------------------------------------------------------
# check_execution
# ---------------------------------------------------------------------------


class TestCheckExecution:
    def test_completed_with_outcome(self, tmp_path):
        log = tmp_path / "task.jsonl"
        log.write_text(
            json.dumps({
                "type": "result",
                "total_cost_usd": 1.5,
                "num_turns": 10,
                "session_id": "sess-1",
                "result": (
                    "---TASK-OUTCOME---\n"
                    "task_id: PROJ-T00001\n"
                    "verdict: PASS\n"
                    "summary: Done\n"
                    "---END-OUTCOME---"
                ),
            }) + "\n"
        )

        result = check_execution(str(log), pid=0)
        assert result["status"] == "completed"
        assert result["outcome"]["verdict"] == "PASS"
        assert result["cost_usd"] == 1.5

    def test_running_with_activity(self, tmp_path):
        log = tmp_path / "task.jsonl"
        log.write_text(
            json.dumps({
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "tool_use", "name": "Read", "input": {}}
                    ]
                },
            }) + "\n"
        )

        # Simulate a running process
        with patch("os.kill", return_value=None):
            result = check_execution(str(log), pid=99999)

        assert result["status"] == "running"
        assert result["turns"] == 1
        assert result["last_tool"] == "Read"

    def test_failed_no_output(self, tmp_path):
        log = tmp_path / "task.jsonl"
        log.write_text("")

        result = check_execution(str(log), pid=0)
        assert result["status"] == "failed"

    def test_missing_log_file(self):
        result = check_execution("/nonexistent/path.jsonl", pid=0)
        assert result["status"] == "error"

    def test_completed_no_outcome_block(self, tmp_path):
        log = tmp_path / "task.jsonl"
        log.write_text(
            json.dumps({
                "type": "result",
                "total_cost_usd": 0.5,
                "result": "No structured output",
                "session_id": "sess-1",
            }) + "\n"
        )

        result = check_execution(str(log), pid=0)
        assert result["status"] == "completed"
        assert result["outcome"]["verdict"] == "UNKNOWN"

    def test_large_file_reads_tail_only(self, tmp_path):
        """check_execution reads only the tail of large log files."""
        log = tmp_path / "task.jsonl"
        # Write > 512KB of assistant turn lines, then a result line
        filler_line = json.dumps({
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "name": "Read", "input": {}}]},
        }) + "\n"
        # ~600KB of filler
        num_lines = (600 * 1024) // len(filler_line) + 1
        with open(log, "w") as f:
            for _ in range(num_lines):
                f.write(filler_line)
            # Append result at the end
            f.write(json.dumps({
                "type": "result",
                "total_cost_usd": 2.5,
                "result": (
                    "---TASK-OUTCOME---\n"
                    "task_id: PROJ-T00001\n"
                    "verdict: PASS\n"
                    "summary: Done\n"
                    "---END-OUTCOME---"
                ),
                "session_id": "sess-1",
            }) + "\n")

        result = check_execution(str(log), pid=0)
        assert result["status"] == "completed"
        assert result["outcome"]["verdict"] == "PASS"
        assert result["cost_usd"] == 2.5

    def test_cleans_registry_on_completion(self, tmp_path):
        """check_execution removes completed processes from registry."""
        mock_proc = MagicMock()
        mock_proc.wait.return_value = 0
        _active_processes[11111] = mock_proc

        log = tmp_path / "task.jsonl"
        log.write_text(
            json.dumps({
                "type": "result",
                "total_cost_usd": 0.5,
                "result": "---TASK-OUTCOME---\nverdic: PASS\n---END-OUTCOME---",
                "session_id": "sess-1",
            }) + "\n"
        )

        check_execution(str(log), pid=11111)
        assert 11111 not in _active_processes

    def test_completed_includes_peak_rss(self, tmp_path):
        """check_execution returns peak_rss_kb from memory log line."""
        log = tmp_path / "task.jsonl"
        log.write_text(
            json.dumps({
                "type": "result",
                "total_cost_usd": 1.0,
                "result": (
                    "---TASK-OUTCOME---\n"
                    "task_id: PROJ-T00001\n"
                    "verdict: PASS\n"
                    "summary: Done\n"
                    "---END-OUTCOME---"
                ),
                "session_id": "sess-1",
            }) + "\n"
            + json.dumps({
                "type": "memory",
                "peak_rss_kb": 204800,
            }) + "\n"
        )

        result = check_execution(str(log), pid=0)
        assert result["status"] == "completed"
        assert result["peak_rss_kb"] == 204800

    def test_running_includes_current_rss(self, tmp_path):
        """check_execution returns current_rss_kb when process is alive."""
        log = tmp_path / "task.jsonl"
        log.write_text(
            json.dumps({
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "tool_use", "name": "Read", "input": {}}
                    ]
                },
            }) + "\n"
        )

        mock_ps = MagicMock()
        mock_ps.returncode = 0
        mock_ps.stdout = "  102400\n"

        with (
            patch("os.kill", return_value=None),
            patch("subprocess.run", return_value=mock_ps) as mock_run,
        ):
            result = check_execution(str(log), pid=99999)

        assert result["status"] == "running"
        assert result["current_rss_kb"] == 102400
        # Verify ps was called with the right args
        mock_run.assert_called_once_with(
            ["ps", "-o", "rss=", "-p", "99999"],
            capture_output=True,
            text=True,
            timeout=5,
        )

    def test_memory_line_parsed_on_failure(self, tmp_path):
        """check_execution returns peak_rss_kb in failed dict."""
        log = tmp_path / "task.jsonl"
        log.write_text(
            json.dumps({
                "type": "memory",
                "peak_rss_kb": 51200,
            }) + "\n"
        )

        # pid=0 means process is not alive, no result line → failed
        result = check_execution(str(log), pid=0)
        assert result["status"] == "failed"
        assert result["peak_rss_kb"] == 51200

    def test_current_rss_ps_failure_returns_zero(self, tmp_path):
        """check_execution returns current_rss_kb=0 when ps fails."""
        log = tmp_path / "task.jsonl"
        log.write_text(
            json.dumps({
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "tool_use", "name": "Write", "input": {}}
                    ]
                },
            }) + "\n"
        )

        with (
            patch("os.kill", return_value=None),
            patch("subprocess.run", side_effect=OSError("ps not found")),
        ):
            result = check_execution(str(log), pid=99999)

        assert result["status"] == "running"
        assert result["current_rss_kb"] == 0

    def test_handles_ansi_in_log(self, tmp_path):
        """check_execution strips ANSI escape sequences from PTY output."""
        log = tmp_path / "task.jsonl"
        # Write a line with ANSI escape sequences embedded
        raw = '\x1b[32m' + json.dumps({
            "type": "result",
            "total_cost_usd": 0.5,
            "result": "done",
            "session_id": "sess-1",
        }) + '\x1b[0m\r\n'
        log.write_text(raw)

        result = check_execution(str(log), pid=0)
        assert result["status"] == "completed"


# ---------------------------------------------------------------------------
# stop_execution
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="Process groups not available on Windows")
class TestStopExecution:
    def test_stops_running_process_group(self):
        """stop_execution uses killpg to kill the entire process group."""
        call_count = {"killpg": 0, "kill": 0}

        def fake_getpgid(pid):
            return pid + 1000  # different pgid

        def fake_killpg(pgid, sig):
            call_count["killpg"] += 1

        def fake_kill(pid, sig):
            call_count["kill"] += 1
            if sig == 0:
                raise ProcessLookupError  # process is gone

        with (
            patch("os.getpgid", side_effect=fake_getpgid),
            patch("os.killpg", side_effect=fake_killpg),
            patch("os.kill", side_effect=fake_kill),
        ):
            result = stop_execution(12345)

        assert result["status"] == "stopped"
        assert call_count["killpg"] >= 1  # SIGTERM was sent via killpg

    def test_already_stopped(self):
        with patch("os.getpgid", side_effect=ProcessLookupError):
            result = stop_execution(12345)

        assert result["status"] == "already_stopped"

    def test_invalid_pid(self):
        result = stop_execution(0)
        assert result["status"] == "error"

    def test_cleans_process_registry(self):
        """stop_execution removes the PID from _active_processes."""
        mock_proc = MagicMock()
        _active_processes[22222] = mock_proc

        with (
            patch("os.getpgid", return_value=22222),
            patch("os.killpg"),
            patch("os.kill", side_effect=ProcessLookupError),
        ):
            stop_execution(22222)

        assert 22222 not in _active_processes


# ---------------------------------------------------------------------------
# _build_execute_task_prompt
# ---------------------------------------------------------------------------


class TestBuildExecuteTaskPrompt:
    def test_includes_task_id_and_title(self):
        from a_sdlc.server import _build_execute_task_prompt

        prompt = _build_execute_task_prompt(
            "PROJ-T00001",
            {
                "title": "Add login form",
                "file_path": "/content/tasks/PROJ-T00001.md",
                "prd_id": None,
            },
        )
        assert "PROJ-T00001" in prompt
        assert "Add login form" in prompt

    def test_includes_prd_section_when_prd_id_present(self):
        from a_sdlc.server import _build_execute_task_prompt

        prompt = _build_execute_task_prompt(
            "PROJ-T00001",
            {
                "title": "Task",
                "file_path": "/tmp/task.md",
                "prd_id": "PROJ-P0001",
            },
        )
        assert "mcp__asdlc__get_prd" in prompt
        assert "PROJ-P0001" in prompt

    def test_no_prd_section_when_prd_id_missing(self):
        from a_sdlc.server import _build_execute_task_prompt

        prompt = _build_execute_task_prompt(
            "PROJ-T00001",
            {
                "title": "Task",
                "file_path": "/tmp/task.md",
                "prd_id": None,
            },
        )
        assert "mcp__asdlc__get_prd" not in prompt

    def test_includes_dispatch_info_when_provided(self):
        from a_sdlc.server import _build_execute_task_prompt

        dispatch_info = (
            "task_id: PROJ-T00002\n"
            "dependency_outcomes:\n"
            "  PROJ-T00001: Added OAuth config"
        )
        prompt = _build_execute_task_prompt(
            "PROJ-T00002",
            {
                "title": "Create login",
                "file_path": "/tmp/task.md",
                "prd_id": None,
            },
            dispatch_info=dispatch_info,
        )
        assert "## Dispatch Info" in prompt
        assert "PROJ-T00001: Added OAuth config" in prompt

    def test_no_dispatch_info_section_when_empty(self):
        from a_sdlc.server import _build_execute_task_prompt

        prompt = _build_execute_task_prompt(
            "PROJ-T00001",
            {
                "title": "Task",
                "file_path": "/tmp/task.md",
                "prd_id": None,
            },
            dispatch_info="",
        )
        assert "## Dispatch Info" not in prompt

    def test_prompt_includes_self_review_instructions(self):
        from a_sdlc.server import _build_execute_task_prompt

        prompt = _build_execute_task_prompt(
            "PROJ-T00001",
            {
                "title": "Task",
                "file_path": "/tmp/task.md",
                "prd_id": None,
            },
        )
        assert "## Review Gates" in prompt
        assert "submit_review" in prompt
        assert "log_correction" in prompt

    def test_prompt_includes_structured_outcome_block(self):
        from a_sdlc.server import _build_execute_task_prompt

        prompt = _build_execute_task_prompt(
            "PROJ-T00001",
            {
                "title": "Task",
                "file_path": "/tmp/task.md",
                "prd_id": None,
            },
        )
        assert "---TASK-OUTCOME---" in prompt
        assert "---END-OUTCOME---" in prompt
        assert "corrections:" in prompt
        assert "review:" in prompt

    def test_shared_context_injected_into_prompt(self):
        from a_sdlc.server import _build_execute_task_prompt

        shared = "### Architecture\nUses layered pattern.\n### Config\ngit.auto_commit: false"
        prompt = _build_execute_task_prompt(
            "PROJ-T00001",
            {
                "title": "Task",
                "file_path": "/tmp/task.md",
                "prd_id": None,
            },
            shared_context=shared,
        )
        assert "## Pre-Loaded Shared Context" in prompt
        assert "Uses layered pattern" in prompt
        assert "git.auto_commit: false" in prompt
        assert "Do NOT re-read" in prompt

    def test_no_shared_context_omits_section(self):
        from a_sdlc.server import _build_execute_task_prompt

        prompt = _build_execute_task_prompt(
            "PROJ-T00001",
            {
                "title": "Task",
                "file_path": "/tmp/task.md",
                "prd_id": None,
            },
            shared_context="",
        )
        assert "## Pre-Loaded Shared Context" not in prompt


# ---------------------------------------------------------------------------
# Stderr capture and startup validation (adapters.py)
# ---------------------------------------------------------------------------


class TestStderrCapture:
    def test_launch_captures_stderr_to_err_file(self, tmp_path):
        """launch() writes stderr to a .err file instead of DEVNULL."""
        with patch("shutil.which", return_value="/usr/local/bin/claude"):
            adapter = ClaudeCodeAdapter()

        mock_proc = MagicMock()
        mock_proc.pid = 44444
        mock_proc.poll.return_value = None  # process still running

        opened_files = {}

        original_open = open

        def tracking_open(path, *args, **kwargs):
            if str(path).endswith(".err"):
                fh = MagicMock()
                opened_files["err"] = str(path)
                return fh
            return original_open(path, *args, **kwargs)

        with (
            patch("a_sdlc.adapters._ensure_log_dir", return_value=tmp_path),
            patch("builtins.open", side_effect=tracking_open),
            patch("subprocess.Popen", return_value=mock_proc) as mock_popen,
            patch("a_sdlc.adapters.time"),
        ):
            handle = adapter.launch(
                prompt="test",
                max_turns=10,
                working_dir=str(tmp_path),
                task_id="ERR-T00001",
            )

        assert handle["status"] == "running"
        # Verify stderr was NOT DEVNULL
        popen_kwargs = mock_popen.call_args[1]
        assert popen_kwargs["stderr"] != subprocess.DEVNULL

        # Clean up registry
        _active_processes.pop(44444, None)

    def test_launch_startup_validation_catches_crash(self, tmp_path):
        """launch() detects immediate process crash after 2s wait."""
        with patch("shutil.which", return_value="/usr/local/bin/claude"):
            adapter = ClaudeCodeAdapter()

        mock_proc = MagicMock()
        mock_proc.pid = 55555
        mock_proc.poll.return_value = 1  # exited with error

        err_file = tmp_path / "CRASH-T00001.err"
        err_file.write_text("Error: claude not found")

        with (
            patch("a_sdlc.adapters._ensure_log_dir", return_value=tmp_path),
            patch("builtins.open", return_value=MagicMock()),
            patch("subprocess.Popen", return_value=mock_proc),
            patch("a_sdlc.adapters.time"),
        ):
            handle = adapter.launch(
                prompt="test",
                max_turns=10,
                working_dir="/tmp",
                task_id="CRASH-T00001",
            )

        assert handle["status"] == "error"
        assert "exited immediately" in handle["error"].lower()
        assert 55555 not in _active_processes

    def test_launch_log_dir_writability_check(self, tmp_path):
        """launch() validates log directory is writable before spawning."""
        with patch("shutil.which", return_value="/usr/local/bin/claude"):
            adapter = ClaudeCodeAdapter()

        # Make a read-only directory
        read_only_dir = tmp_path / "readonly"
        read_only_dir.mkdir()

        # Patch _ensure_log_dir to return the dir but make touch fail
        with (
            patch("a_sdlc.adapters._ensure_log_dir", return_value=read_only_dir),
            patch.object(Path, "touch", side_effect=OSError("Permission denied")),
        ):
            handle = adapter.launch(
                prompt="test",
                max_turns=10,
                working_dir="/tmp",
                task_id="PERM-T00001",
            )

        assert handle["status"] == "error"
        assert "not writable" in handle["error"].lower()


class TestCheckExecutionStderr:
    def test_missing_log_includes_stderr(self, tmp_path):
        """check_execution includes .err content when log file is missing."""
        err_file = tmp_path / "task.err"
        err_file.write_text("ImportError: No module named 'claude'")

        result = check_execution(str(tmp_path / "task.jsonl"), pid=0)
        assert result["status"] == "error"
        assert result["stderr"] == "ImportError: No module named 'claude'"

    def test_failed_process_includes_stderr(self, tmp_path):
        """check_execution includes .err content when process exits with no result."""
        log = tmp_path / "task.jsonl"
        log.write_text(
            json.dumps({
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "working..."}]},
            }) + "\n"
        )

        err_file = tmp_path / "task.err"
        err_file.write_text("Segfault in pty wrapper")

        result = check_execution(str(log), pid=0)
        assert result["status"] == "failed"
        assert result["stderr"] == "Segfault in pty wrapper"

    def test_missing_log_no_stderr(self):
        """check_execution handles missing log with no .err file gracefully."""
        result = check_execution("/nonexistent/path.jsonl", pid=0)
        assert result["status"] == "error"
        assert result["stderr"] == ""


class TestSharedContextPassthrough:
    """Tests that shared_context flows from execute_task MCP tool to prompt."""

    def test_shared_context_passed_to_prompt(self):
        from a_sdlc.server import execute_task

        mock_db = MagicMock()
        mock_db.get_task.return_value = {
            "id": "PROJ-T00003",
            "title": "Add feature",
            "file_path": "/content/tasks/PROJ-T00003.md",
            "prd_id": None,
        }

        captured_prompt = {}

        class CapturingAdapter:
            def launch(self, prompt, **kwargs):
                captured_prompt["prompt"] = prompt
                return {"pid": 0, "log_path": "/tmp/test.jsonl", "status": "completed"}

        with (
            patch("a_sdlc.server.get_db", return_value=mock_db),
            patch("a_sdlc.adapters.create_adapter", return_value=CapturingAdapter()),
        ):
            execute_task(
                task_id="PROJ-T00003",
                executor="mock",
                shared_context="### Architecture\nMVC pattern\n### Config\ntesting.enabled: true",
            )

        assert "## Pre-Loaded Shared Context" in captured_prompt["prompt"]
        assert "MVC pattern" in captured_prompt["prompt"]
        assert "Do NOT re-read" in captured_prompt["prompt"]

    def test_no_shared_context_omits_section(self):
        from a_sdlc.server import execute_task

        mock_db = MagicMock()
        mock_db.get_task.return_value = {
            "id": "PROJ-T00003",
            "title": "Add feature",
            "file_path": "/content/tasks/PROJ-T00003.md",
            "prd_id": None,
        }

        captured_prompt = {}

        class CapturingAdapter:
            def launch(self, prompt, **kwargs):
                captured_prompt["prompt"] = prompt
                return {"pid": 0, "log_path": "/tmp/test.jsonl", "status": "completed"}

        with (
            patch("a_sdlc.server.get_db", return_value=mock_db),
            patch("a_sdlc.adapters.create_adapter", return_value=CapturingAdapter()),
        ):
            execute_task(task_id="PROJ-T00003", executor="mock")

        assert "## Pre-Loaded Shared Context" not in captured_prompt["prompt"]
