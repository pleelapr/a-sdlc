"""Execution MCP tools."""
import os
from typing import Any

import a_sdlc.server as _server

__all__ = [
    "build_execute_task_prompt",
    "_build_execute_task_prompt",
    "execute_task",
    "check_execution",
    "stop_execution",
]


def build_execute_task_prompt(
    task_id: str,
    task: dict[str, Any],
    dispatch_info: str = "",
    shared_context: str = "",
) -> str:
    """Build a self-contained prompt for a subprocess to execute a task.

    The prompt is designed to be comprehensive: the subprocess self-loads
    full content via MCP tools, runs self-review with test evidence, logs
    corrections, and returns a structured outcome block.

    Args:
        task_id: The task identifier.
        task: Task metadata dict from the database.
        dispatch_info: Optional lightweight context from the orchestrator
            (dependency outcomes, batch context). Injected into the
            ``## Dispatch Info`` section of the prompt.
        shared_context: Optional pre-loaded shared context from the
            orchestrator (architecture summary, config flags, lessons).
            When provided, the subprocess skips re-reading these files.

    Returns:
        Fully-formed prompt string.
    """
    title = task.get("title", "Untitled")
    prd_id = task.get("prd_id", "")

    dispatch_section = ""
    if dispatch_info:
        dispatch_section = f"\n## Dispatch Info\n{dispatch_info}\n"

    shared_section = ""
    if shared_context:
        shared_section = (
            "\n## Pre-Loaded Shared Context\n\n"
            f"{shared_context}\n\n"
            "NOTE: The above was pre-loaded by the orchestrator. Do NOT re-read\n"
            ".sdlc/artifacts/architecture.md or .sdlc/config.yaml — use the values above.\n"
            "Only read additional files specific to your task implementation.\n"
        )

    prd_load = ""
    if prd_id:
        prd_load = (
            f"2. Call mcp__asdlc__get_prd(prd_id=\"{prd_id}\") for PRD context\n"
            f"3. Call mcp__asdlc__get_design(prd_id=\"{prd_id}\") for design context (may not exist -- that's OK)\n"
        )
    else:
        prd_load = ""

    # Build quality verification section (config-gated)
    quality_section = ""
    try:
        from a_sdlc.core.quality_config import load_quality_config

        qcfg = load_quality_config()
        if qcfg.enabled and qcfg.ac_gate:
            challenge_note = ""
            if qcfg.challenge.enabled and qcfg.challenge.is_gate_active("implementation"):
                challenge_note = (
                    "4. If quality.challenge.gates.implementation is true, "
                    "be aware your implementation may be challenged after completion\n"
                )
            quality_section = f"""
## Quality Verification

Read .sdlc/config.yaml — if quality.enabled is true AND quality.ac_gate is true:
1. Call mcp__asdlc__get_task_requirements(task_id="{task_id}") to load linked ACs
2. For each AC with depth="behavioral": write a test that exercises the AC, then call:
   mcp__asdlc__verify_acceptance_criteria(task_id="{task_id}", ac_id="<ac_id>", evidence_type="test", evidence="<test name and output>")
3. For each AC with depth="structural": verify by code inspection, then call:
   mcp__asdlc__verify_acceptance_criteria(task_id="{task_id}", ac_id="<ac_id>", evidence_type="manual", evidence="<verification description>")
{challenge_note}"""
    except (ImportError, Exception):
        pass

    return f"""You are implementing task {task_id}: {title}
{dispatch_section}{shared_section}
## Self-Loading Instructions

Load your own context -- the orchestrator intentionally does NOT pre-read content for you.

1. Call mcp__asdlc__get_task(task_id="{task_id}") to get full task content, metadata, and file_path
{prd_load}4. Read .sdlc/artifacts/architecture.md for codebase patterns and conventions (if it exists)

## Implementation

1. Implement the task following the Implementation Steps from the task content you loaded
2. Write tests as specified in the Acceptance Criteria
3. When you discover and fix issues during implementation, log them:
   mcp__asdlc__log_correction(context_type="task", context_id="{task_id}", category="<category>", description="<what was corrected and why>")
   Categories: testing, code-quality, task-completeness, integration, documentation, architecture, security, performance, process
4. Read .sdlc/config.yaml -- check git.auto_commit:
   - If true: git add <files> && git commit -m "[{task_id}] {title}"
   - If false or not set: git add <files> only -- do NOT commit
5. Read .sdlc/config.yaml -- check testing.runtime for runtime test configuration
{quality_section}
## Review Gates

After completing implementation and tests:
1. Self-review: Re-read the task spec, verify each acceptance criterion
   - Read .sdlc/config.yaml -- check testing.relevance.enabled
   - If relevance detection is enabled:
     a. Assess change scope based on files you modified:
        - backend-logic: .py files with business logic -> RUN unit tests
        - api-endpoints: route handlers, middleware -> RUN unit + integration
        - database: models, migrations -> RUN unit + integration
        - documentation: .md files, docstrings, skill templates -> SKIP all tests
        - configuration: .yaml, .env, build configs -> SKIP unit tests
        - test-only: test files only -> RUN unit tests
     b. For SKIP verdicts, output rationale
     c. For RUN verdicts, execute the command from testing.commands.<type> and capture output
   - If relevance detection is disabled or absent:
     Run ALL commands under testing.commands (e.g. pytest, lint, typecheck)
   - If no config exists, run the project's default test command
   - Capture and include ACTUAL test output -- no self-assertions without evidence
   - If any executed test fails, fix the issues before proceeding
2. Call mcp__asdlc__submit_review(task_id="{task_id}", reviewer_type="self", verdict="pass"|"fail", findings="...", test_output="...") with actual test output
3. If self-review verdict is "fail", fix the issues and re-submit until "pass"
4. Log corrections for EVERY finding discovered during implementation
5. Do NOT call update_task(status="completed") -- the orchestrator handles completion after review

IMPORTANT: This is a background execution -- do not use AskUserQuestion.
Make autonomous decisions. If blocked, mark the task as blocked.

## CRITICAL: Structured Output

Your FINAL output MUST end with this exact block. Do NOT omit it.

---TASK-OUTCOME---
task_id: {task_id}
verdict: PASS|FAIL|BLOCKED
files_changed: <comma-separated list of files you modified>
tests: <passed>/<total>
review: APPROVE|REQUEST_CHANGES|ESCALATE
summary: <one-line description of what was done>
corrections: <number of corrections logged>
---END-OUTCOME---
"""


# Backward-compat alias for external callers using the old private name
_build_execute_task_prompt = build_execute_task_prompt


@_server.mcp.tool()
def execute_task(
    task_id: str,
    executor: str = "mock",
    max_turns: int = 50,
    dispatch_info: str = "",
    shared_context: str = "",
) -> dict[str, Any]:
    """Launch a task subprocess and return immediately with a handle.

    Non-blocking: spawns the subprocess in the background and returns
    a ``pid`` + ``log_path`` handle.  The orchestrator MUST then poll
    ``check_execution(log_path, pid)`` periodically to monitor progress
    and detect stalls.

    Memory-safe: the subprocess runs in its own process with its own
    context window.  Only the ~200-byte parsed outcome is extracted
    when ``check_execution`` finds the result.

    Args:
        task_id: Task identifier (e.g. ``PROJ-T00001``).
        executor: Adapter name — ``"mock"``, ``"claude"``, or ``"gemini"``.
            Defaults to ``"mock"`` (safe, no real subprocess).
        max_turns: Maximum agentic turns for the subprocess session.
        dispatch_info: Optional lightweight context from the sprint-run
            orchestrator (dependency outcomes, batch context).
        shared_context: Optional pre-loaded shared context from the
            orchestrator (architecture summary, config flags, lessons).
            Injected into the subprocess prompt to avoid redundant reads.

    Returns:
        Dict with ``pid``, ``log_path``, ``task_id``, ``executor``.
        Use ``check_execution(log_path, pid)`` to monitor and get results.
    """
    from a_sdlc.adapters import create_adapter

    db = _server.get_db()
    task = db.get_task(task_id)
    if not task:
        return {"status": "error", "message": f"Task not found: {task_id}"}

    prompt = build_execute_task_prompt(
        task_id, task, dispatch_info=dispatch_info, shared_context=shared_context,
    )

    try:
        adapter = create_adapter(executor)
    except (ValueError, RuntimeError) as exc:
        return {"status": "error", "message": str(exc)}

    handle = adapter.launch(
        prompt=prompt,
        max_turns=max_turns,
        working_dir=os.getcwd(),
        task_id=task_id,
        allowed_tools=[
            "Read", "Write", "Edit", "Bash",
            "Glob", "Grep", "mcp__asdlc__*",
        ],
    )

    return {
        "status": "launched",
        "task_id": task_id,
        "executor": executor,
        "pid": handle.get("pid", 0),
        "log_path": handle.get("log_path", ""),
    }


@_server.mcp.tool()
def check_execution(
    log_path: str,
    pid: int,
) -> dict[str, Any]:
    """Check progress of a launched task subprocess.

    Reads the stream-json log file to determine current status,
    recent activity, and final outcome if the subprocess has finished.

    The orchestrator MUST call this periodically (e.g. every 30s) after
    ``execute_task`` to monitor progress and detect stalls.

    Args:
        log_path: Path to the log file returned by ``execute_task``.
        pid: Process ID returned by ``execute_task``.

    Returns:
        Dict with ``status`` (running/completed/failed/stalled),
        ``turns``, ``last_tool``, ``last_text``, ``cost_usd``,
        and ``outcome`` when completed.
    """
    from a_sdlc.adapters import check_execution as _check

    return _check(log_path, pid)


@_server.mcp.tool()
def stop_execution(
    pid: int,
) -> dict[str, Any]:
    """Stop a running task subprocess.

    Sends SIGTERM to the process and waits up to 5 seconds for graceful
    shutdown, then SIGKILL if needed.

    Args:
        pid: Process ID to stop.

    Returns:
        Dict with ``status`` (stopped/killed/already_stopped).
    """
    from a_sdlc.adapters import stop_execution as _stop

    return _stop(pid)
