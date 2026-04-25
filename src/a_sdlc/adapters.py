"""Execution adapters for spawning CLI coding-agent subprocesses.

Each adapter wraps a specific CLI (Claude Code, Gemini CLI, etc.) and
returns only the compact outcome — the full subprocess transcript stays
in the child process's own session file, never in the orchestrator's
context.
"""

from __future__ import annotations

import atexit
import contextlib
import json
import logging
import os
import re
import shutil
import signal
import subprocess
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Valid adapter names for ``create_adapter()``
_VALID_ADAPTERS = ("mock", "claude", "gemini")

# Directory for execution logs
_EXEC_LOG_DIR = Path.home() / ".a-sdlc" / "exec-logs"

# Compiled regex for ANSI stripping (avoid re-compiling on every call)
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")

# ---------------------------------------------------------------------------
# Process registry — tracks all launched subprocesses so they can be
# cleaned up when the MCP server exits (gracefully or via signal).
# ---------------------------------------------------------------------------
_active_processes: dict[int, subprocess.Popen] = {}


def _cleanup_children() -> None:
    """Terminate all tracked child processes on exit.

    Sends SIGTERM to the entire process group (killing both the PTY
    wrapper and the ``claude`` grandchild), then SIGKILL if needed.
    """
    for pid, proc in list(_active_processes.items()):
        try:
            pgid = os.getpgid(pid)
            os.killpg(pgid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            pass
        try:
            proc.wait(timeout=3)
        except Exception:
            try:
                pgid = os.getpgid(pid)
                os.killpg(pgid, signal.SIGKILL)
            except (OSError, ProcessLookupError):
                pass
    _active_processes.clear()


atexit.register(_cleanup_children)


def _reap_if_dead(pid: int) -> None:
    """Remove a process from the registry and reap it if it has exited."""
    proc = _active_processes.get(pid)
    if proc is None:
        return
    try:
        proc.wait(timeout=0)
    except subprocess.TimeoutExpired:
        return  # still running
    except Exception:
        pass
    _active_processes.pop(pid, None)


def _ensure_log_dir() -> Path:
    """Create the execution log directory if needed."""
    try:
        _EXEC_LOG_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RuntimeError(f"Cannot create exec-log directory: {exc}") from exc
    return _EXEC_LOG_DIR


class ExecutionAdapter(ABC):
    """Abstract base class for CLI execution adapters."""

    @abstractmethod
    def execute(
        self,
        prompt: str,
        max_turns: int,
        working_dir: str,
        allowed_tools: list[str] | None = None,
    ) -> dict[str, Any]:
        """Execute a prompt via a CLI subprocess and return the result.

        Args:
            prompt: The prompt to send to the coding agent.
            max_turns: Maximum agentic turns for the session.
            working_dir: Working directory for the subprocess.
            allowed_tools: Tools to auto-approve without permission prompts.

        Returns:
            Dictionary with at least ``result`` (stdout text) and
            optionally ``session_id``, ``status``, ``error`` keys.
        """

    def launch(
        self,
        prompt: str,
        max_turns: int,
        working_dir: str,
        task_id: str,
        allowed_tools: list[str] | None = None,
    ) -> dict[str, Any]:
        """Non-blocking launch — start subprocess and return immediately.

        Default implementation falls back to blocking ``execute()``.
        Adapters that support non-blocking should override this.

        Returns:
            Dict with ``pid``, ``log_path``, ``status`` keys.
        """
        # Fallback: run blocking and write result to log
        log_dir = _ensure_log_dir()
        log_path = str(log_dir / f"{task_id}.jsonl")
        result = self.execute(prompt, max_turns, working_dir, allowed_tools)
        Path(log_path).write_text(json.dumps(result) + "\n")
        return {
            "pid": 0,
            "log_path": log_path,
            "status": "completed",
            "result": result,
        }


class ClaudeCodeAdapter(ExecutionAdapter):
    """Spawns ``claude -p`` subprocesses.

    Args:
        skip_permissions: When ``True``, passes
            ``--dangerously-skip-permissions`` to the subprocess.
            Required for headless execution where no user can respond
            to permission prompts.  Defaults to ``True`` because
            ``claude -p`` is inherently non-interactive.
    """

    def __init__(self, *, skip_permissions: bool = True) -> None:
        self.claude_path = shutil.which("claude")
        if not self.claude_path:
            raise RuntimeError(
                "Claude Code CLI not found on PATH. "
                "Install from: https://claude.ai/code"
            )
        self.skip_permissions = skip_permissions

    # Tools that must NEVER be available in subprocess sessions.
    # Task/TaskOutput/TaskStop would cause recursive sub-agent spawning
    # which defeats the memory-isolation purpose of subprocess dispatch.
    _DISALLOWED_TOOLS = ["Task", "TaskOutput", "TaskStop"]

    def _build_cmd(
        self,
        prompt: str,
        max_turns: int,
        output_format: str = "json",
        allowed_tools: list[str] | None = None,
    ) -> list[str]:
        """Build the claude CLI command."""
        cmd: list[str] = [
            self.claude_path,
            "-p",
            prompt,
            "--output-format",
            output_format,
            "--max-turns",
            str(max_turns),
        ]

        if self.skip_permissions:
            cmd.append("--dangerously-skip-permissions")

        # Block recursive delegation tools
        cmd.extend([
            "--disallowedTools",
            ",".join(self._DISALLOWED_TOOLS),
        ])

        if output_format == "stream-json":
            cmd.append("--verbose")

        if allowed_tools:
            cmd.extend(["--allowedTools", ",".join(allowed_tools)])

        return cmd

    def execute(
        self,
        prompt: str,
        max_turns: int,
        working_dir: str,
        allowed_tools: list[str] | None = None,
    ) -> dict[str, Any]:
        cmd = self._build_cmd(prompt, max_turns, "json", allowed_tools)

        try:
            result = subprocess.run(
                cmd,
                cwd=working_dir,
                capture_output=True,
                text=True,
                timeout=max_turns * 60,
            )
        except subprocess.TimeoutExpired:
            return {
                "status": "error",
                "error": f"Claude Code session timed out after {max_turns * 60}s",
                "result": "",
            }

        if result.returncode != 0:
            return {
                "status": "error",
                "error": result.stderr[:2000],
                "result": "",
                "exit_code": result.returncode,
            }

        if result.stderr:
            logger.info("Claude subprocess stderr: %s", result.stderr[:500])

        try:
            parsed = json.loads(result.stdout)
            return {
                "status": "ok",
                "result": str(parsed.get("result", parsed.get("text", ""))),
                "session_id": parsed.get("session_id"),
            }
        except json.JSONDecodeError:
            return {
                "status": "error",
                "error": "Failed to parse Claude Code output as JSON",
                "result": result.stdout[:2000],
            }

    def launch(
        self,
        prompt: str,
        max_turns: int,
        working_dir: str,
        task_id: str,
        allowed_tools: list[str] | None = None,
    ) -> dict[str, Any]:
        """Non-blocking launch with stream-json output for monitoring.

        Spawns ``claude -p`` with ``--output-format stream-json`` inside
        a Python PTY wrapper so the ``claude`` CLI sees a TTY and flushes
        output in real time.  Without the PTY, ``claude`` fully buffers
        stdout to files and the log stays empty until the process exits.

        Process isolation:
            - ``stdin=DEVNULL`` prevents inheriting the MCP server's stdin
            - PTY wrapper closes fd 0 and reopens as ``/dev/null`` so
              ``pty._copy``'s select loop gets immediate EOF on stdin
            - ``start_new_session=True`` puts the child in its own
              process group for clean ``os.killpg()`` cleanup

        Returns:
            Dict with ``pid``, ``log_path``, ``status``.
        """
        import sys

        log_dir = _ensure_log_dir()
        log_path = log_dir / f"{task_id}.jsonl"

        claude_cmd = self._build_cmd(prompt, max_turns, "stream-json", allowed_tools)

        # PTY wrapper script — runs as a child process.
        #
        # CRITICAL design decisions:
        #   1. Close stdin (fd 0) → reopen as /dev/null BEFORE pty.spawn()
        #      so pty._copy's select loop sees immediate EOF on stdin and
        #      does NOT steal MCP protocol messages from the parent's pipe.
        #   2. try/finally on log_fd to prevent fd leaks if pty.spawn fails.
        #   3. Guard os.write with `if data:` to avoid busy-loop on EOF
        #      platforms where os.read returns b"" repeatedly.
        pty_wrapper = (
            "import pty, os, sys, resource, json, platform\n"
            "os.close(0)\n"
            "os.open(os.devnull, os.O_RDONLY)\n"
            "log_fd = os.open(sys.argv[1], os.O_WRONLY | os.O_CREAT | os.O_TRUNC)\n"
            "try:\n"
            "    def read_cb(fd):\n"
            "        data = os.read(fd, 65536)\n"
            "        if data:\n"
            "            os.write(log_fd, data)\n"
            "        return data\n"
            "    pty.spawn(sys.argv[2:], read_cb)\n"
            "    ru = resource.getrusage(resource.RUSAGE_CHILDREN)\n"
            "    peak = ru.ru_maxrss\n"
            "    if platform.system() == 'Darwin':\n"
            "        peak = peak // 1024\n"
            "    line = json.dumps({'type': 'memory', 'peak_rss_kb': peak}) + '\\n'\n"
            "    os.write(log_fd, line.encode())\n"
            "finally:\n"
            "    os.close(log_fd)\n"
        )

        wrapper_cmd = [
            sys.executable, "-c", pty_wrapper,
            str(log_path),
        ] + claude_cmd

        # Child processes get A_SDLC_CHILD=1 so their MCP server
        # skips the singleton PID lock (children need their own server
        # for stdio transport).
        child_env = os.environ.copy()
        child_env["A_SDLC_CHILD"] = "1"

        # Validate log directory is writable before spawning
        test_file = log_dir / ".write_test"
        try:
            test_file.touch()
            test_file.unlink()
        except OSError as exc:
            return {
                "pid": 0,
                "log_path": str(log_path),
                "status": "error",
                "error": f"Log directory not writable: {exc}",
            }

        # Capture stderr to a .err file for diagnostics
        err_path = log_dir / f"{task_id}.err"
        err_fh = open(err_path, "w")  # noqa: SIM115

        try:
            proc = subprocess.Popen(
                wrapper_cmd,
                cwd=working_dir,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=err_fh,
                start_new_session=True,
                env=child_env,
            )
        except OSError as exc:
            err_fh.close()
            return {
                "pid": 0,
                "log_path": str(log_path),
                "status": "error",
                "error": f"Failed to spawn subprocess: {exc}",
            }

        # Track for cleanup on exit
        _active_processes[proc.pid] = proc

        # Startup validation: wait briefly and check for immediate crash
        time.sleep(2)
        poll_result = proc.poll()
        if poll_result is not None:
            err_fh.close()
            err_content = ""
            if err_path.exists():
                err_content = err_path.read_text(errors="replace")[:2000]
            _active_processes.pop(proc.pid, None)
            return {
                "pid": proc.pid,
                "log_path": str(log_path),
                "status": "error",
                "error": f"Subprocess exited immediately (code {poll_result}): {err_content}",
            }

        return {
            "pid": proc.pid,
            "log_path": str(log_path),
            "status": "running",
        }


class GeminiAdapter(ExecutionAdapter):
    """Spawns ``gemini`` CLI subprocesses."""

    def __init__(self) -> None:
        self.gemini_path = shutil.which("gemini")
        if not self.gemini_path:
            raise RuntimeError(
                "Gemini CLI not found on PATH. "
                "Install from: https://github.com/google-gemini/gemini-cli"
            )

    def _build_cmd(
        self,
        prompt: str,
        output_format: str = "text",
    ) -> list[str]:
        """Build the gemini CLI command."""
        cmd: list[str] = [
            self.gemini_path,
            "-p",
            prompt,
            "-y",  # YOLO mode for headless execution
        ]

        if output_format:
            cmd.extend(["--output-format", output_format])

        return cmd

    def execute(
        self,
        prompt: str,
        max_turns: int,
        working_dir: str,
        allowed_tools: list[str] | None = None,
    ) -> dict[str, Any]:
        cmd = self._build_cmd(prompt, "text")

        try:
            result = subprocess.run(
                cmd,
                cwd=working_dir,
                capture_output=True,
                text=True,
                timeout=max_turns * 60,
            )
        except subprocess.TimeoutExpired:
            return {
                "status": "error",
                "error": f"Gemini session timed out after {max_turns * 60}s",
                "result": "",
            }

        if result.returncode != 0:
            return {
                "status": "error",
                "error": result.stderr[:2000],
                "result": "",
                "exit_code": result.returncode,
            }

        return {
            "status": "ok",
            "result": result.stdout,
        }

    def launch(
        self,
        prompt: str,
        max_turns: int,
        working_dir: str,
        task_id: str,
        allowed_tools: list[str] | None = None,
    ) -> dict[str, Any]:
        """Non-blocking launch for Gemini CLI with real-time monitoring."""
        import sys

        log_dir = _ensure_log_dir()
        log_path = log_dir / f"{task_id}.jsonl"

        gemini_cmd = self._build_cmd(prompt, "stream-json")

        # PTY wrapper script (reused from ClaudeCodeAdapter pattern)
        pty_wrapper = (
            "import pty, os, sys, resource, json, platform\n"
            "os.close(0)\n"
            "os.open(os.devnull, os.O_RDONLY)\n"
            "log_fd = os.open(sys.argv[1], os.O_WRONLY | os.O_CREAT | os.O_TRUNC)\n"
            "try:\n"
            "    def read_cb(fd):\n"
            "        data = os.read(fd, 65536)\n"
            "        if data:\n"
            "            os.write(log_fd, data)\n"
            "        return data\n"
            "    pty.spawn(sys.argv[2:], read_cb)\n"
            "    ru = resource.getrusage(resource.RUSAGE_CHILDREN)\n"
            "    peak = ru.ru_maxrss\n"
            "    if platform.system() == 'Darwin':\n"
            "        peak = peak // 1024\n"
            "    line = json.dumps({'type': 'memory', 'peak_rss_kb': peak}) + '\\n'\n"
            "    os.write(log_fd, line.encode())\n"
            "finally:\n"
            "    os.close(log_fd)\n"
        )

        wrapper_cmd = [
            sys.executable, "-c", pty_wrapper,
            str(log_path),
        ] + gemini_cmd

        child_env = os.environ.copy()
        child_env["A_SDLC_CHILD"] = "1"

        # Capture stderr to a .err file
        err_path = log_dir / f"{task_id}.err"
        err_fh = open(err_path, "w")  # noqa: SIM115

        try:
            proc = subprocess.Popen(
                wrapper_cmd,
                cwd=working_dir,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=err_fh,
                start_new_session=True,
                env=child_env,
            )
        except OSError as exc:
            err_fh.close()
            return {
                "pid": 0,
                "log_path": str(log_path),
                "status": "error",
                "error": f"Failed to spawn subprocess: {exc}",
            }

        _active_processes[proc.pid] = proc

        # Startup validation
        time.sleep(2)
        poll_result = proc.poll()
        if poll_result is not None:
            err_fh.close()
            err_content = ""
            if err_path.exists():
                err_content = err_path.read_text(errors="replace")[:2000]
            _active_processes.pop(proc.pid, None)
            return {
                "pid": proc.pid,
                "log_path": str(log_path),
                "status": "error",
                "error": f"Gemini subprocess exited immediately (code {poll_result}): {err_content}",
            }

        return {
            "pid": proc.pid,
            "log_path": str(log_path),
            "status": "running",
        }


class MockAdapter(ExecutionAdapter):
    """Configurable mock adapter for testing.

    Returns a pre-configured result dict without spawning any process.
    """

    def __init__(self, result: dict[str, Any] | None = None) -> None:
        self.mock_result = result or {
            "status": "ok",
            "result": (
                "---TASK-OUTCOME---\n"
                "task_id: MOCK-T00001\n"
                "verdict: PASS\n"
                "files_changed: none\n"
                "tests: 0/0\n"
                "summary: Mock execution (no real subprocess spawned)\n"
                "---END-OUTCOME---"
            ),
        }

    def execute(
        self,
        prompt: str,
        max_turns: int,
        working_dir: str,
        allowed_tools: list[str] | None = None,
    ) -> dict[str, Any]:
        logger.info(
            "MockAdapter.execute called (max_turns=%d, working_dir=%s)",
            max_turns,
            working_dir,
        )
        return dict(self.mock_result)


def create_adapter(adapter_name: str = "mock") -> ExecutionAdapter:
    """Factory function to create an execution adapter by name.

    Args:
        adapter_name: One of ``"mock"``, ``"claude"``, ``"gemini"``.

    Returns:
        An ``ExecutionAdapter`` instance.

    Raises:
        ValueError: If *adapter_name* is not recognised.
    """
    if adapter_name == "mock":
        return MockAdapter()
    if adapter_name == "claude":
        return ClaudeCodeAdapter()
    if adapter_name == "gemini":
        return GeminiAdapter()

    raise ValueError(
        f"Unknown adapter: {adapter_name!r}. "
        f"Must be one of {_VALID_ADAPTERS}"
    )


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences and carriage returns from PTY output."""
    text = _ANSI_RE.sub("", text)
    return text.replace("\r", "")


def check_execution(log_path: str, pid: int) -> dict[str, Any]:
    """Check on a launched subprocess execution.

    Reads the stream-json log file, checks if the process is still
    alive, extracts the latest activity and final outcome if done.

    The log may contain ANSI escape sequences from the PTY wrapper,
    which are stripped before JSON parsing.

    For large log files (>512 KB), only the tail is read for efficiency.

    Args:
        log_path: Path to the stream-json log file.
        pid: Process ID of the subprocess.

    Returns:
        Dict with ``status`` (running/completed/failed),
        ``turns``, ``last_tool``, ``cost_usd``,
        and ``outcome`` when completed.
    """
    from a_sdlc.executor import Executor

    # Reap zombie if process has exited
    if pid > 0:
        _reap_if_dead(pid)

    # Check if process is still running
    process_alive = False
    if pid > 0:
        try:
            os.kill(pid, 0)
            process_alive = True
        except (OSError, ProcessLookupError):
            process_alive = False

    # Read the log file (tail for large files to stay fast)
    log = Path(log_path)
    try:
        if not log.exists():
            err_path = Path(log_path).with_suffix(".err")
            err_msg = ""
            if err_path.exists():
                err_msg = err_path.read_text(errors="replace")[:2000]
            return {
                "status": "error",
                "message": f"Log file not found: {log_path}",
                "stderr": err_msg,
            }

        max_read_bytes = 512 * 1024  # 512 KB
        file_size = log.stat().st_size
        if file_size > max_read_bytes:
            with open(log_path, errors="replace") as fh:
                fh.seek(max(0, file_size - max_read_bytes))
                fh.readline()  # skip partial first line
                raw_text = _strip_ansi(fh.read())
        else:
            raw_text = _strip_ansi(log.read_text(errors="replace"))
    except (FileNotFoundError, OSError) as exc:
        return {
            "status": "error",
            "message": f"Cannot read log file: {exc}",
        }

    lines = raw_text.strip().splitlines()
    if not lines:
        if process_alive:
            return {"status": "running", "message": "Process started, no output yet"}
        return {"status": "failed", "message": "Process exited with no output"}

    # Parse stream-json lines for activity summary
    turns = 0
    last_tool = ""
    last_text = ""
    cost = 0.0
    result_text = ""
    session_id = ""
    peak_rss_kb = 0

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue

        msg_type = d.get("type", "")

        if msg_type == "assistant":
            turns += 1
            content = d.get("message", {}).get("content", [])
            for c in content:
                if c.get("type") == "tool_use":
                    last_tool = c.get("name", "")
                elif c.get("type") == "text":
                    last_text = c.get("text", "")[:200]

        elif msg_type == "result":
            cost = d.get("total_cost_usd", 0.0)
            result_text = d.get("result", "")
            session_id = d.get("session_id", "")

        elif msg_type == "memory":
            peak_rss_kb = d.get("peak_rss_kb", 0)

    # If we got a result line, the process is done
    if result_text:
        outcome = Executor._extract_outcome_block(
            result_text,
            "---TASK-OUTCOME---",
            "---END-OUTCOME---",
        )
        # Clean up registry
        _active_processes.pop(pid, None)
        return {
            "status": "completed",
            "turns": turns,
            "cost_usd": round(cost, 2),
            "session_id": session_id,
            "peak_rss_kb": peak_rss_kb,
            "outcome": outcome or {
                "verdict": "UNKNOWN",
                "summary": "No outcome block found",
            },
        }

    # Process still running — sample current RSS via ps
    if process_alive:
        current_rss_kb = 0
        if pid > 0:
            try:
                ps_result = subprocess.run(
                    ["ps", "-o", "rss=", "-p", str(pid)],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if ps_result.returncode == 0:
                    current_rss_kb = int(ps_result.stdout.strip())
            except (subprocess.TimeoutExpired, ValueError, OSError):
                current_rss_kb = 0
        return {
            "status": "running",
            "turns": turns,
            "last_tool": last_tool,
            "last_text": last_text[:150],
            "current_rss_kb": current_rss_kb,
        }

    # Process exited but no result line — likely crashed
    _active_processes.pop(pid, None)
    err_path = Path(log_path).with_suffix(".err")
    err_msg = ""
    if err_path.exists():
        err_msg = err_path.read_text(errors="replace")[:2000]
    return {
        "status": "failed",
        "turns": turns,
        "last_tool": last_tool,
        "last_text": last_text[:150],
        "peak_rss_kb": peak_rss_kb,
        "message": "Process exited without producing a result",
        "stderr": err_msg,
    }


def stop_execution(pid: int) -> dict[str, Any]:
    """Kill a running subprocess and its entire process group.

    Uses ``os.killpg()`` to kill the PTY wrapper AND the ``claude``
    grandchild process.  Sends SIGTERM first for graceful shutdown,
    then SIGKILL after 2 seconds if needed.

    Args:
        pid: Process ID to kill (the PTY wrapper's PID).

    Returns:
        Dict with status.
    """
    if pid <= 0:
        return {"status": "error", "message": "Invalid PID"}

    try:
        pgid = os.getpgid(pid)
    except (OSError, ProcessLookupError):
        _active_processes.pop(pid, None)
        return {"status": "already_stopped", "pid": pid}

    try:
        os.killpg(pgid, signal.SIGTERM)
        # Wait up to 2 seconds for graceful termination
        for _ in range(8):
            time.sleep(0.25)
            try:
                os.kill(pid, 0)
            except (OSError, ProcessLookupError):
                _active_processes.pop(pid, None)
                return {"status": "stopped", "pid": pid}
        # Force kill the entire group
        with contextlib.suppress(OSError, ProcessLookupError):
            os.killpg(pgid, signal.SIGKILL)
        _active_processes.pop(pid, None)
        return {"status": "killed", "pid": pid}
    except (OSError, ProcessLookupError):
        _active_processes.pop(pid, None)
        return {"status": "already_stopped", "pid": pid}
