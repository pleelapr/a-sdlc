"""Claude Code session executor for background task/sprint execution.

Spawns headless Claude Code sessions via ``claude -p`` to execute tasks
and sprints.  Each session has full access to MCP tools, file operations,
shell commands, and skill templates -- identical to interactive sessions.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from a_sdlc.storage import get_storage

logger = logging.getLogger(__name__)

# Valid daemon execution modes
_VALID_MODES = ("session", "parallel")


# ---------------------------------------------------------------------------
# Config loading / validation
# ---------------------------------------------------------------------------


def load_daemon_config(project_dir: str | None = None) -> dict[str, Any]:
    """Load and validate daemon config from ``.sdlc/config.yaml``.

    Reads the ``daemon:`` section from the project's config file and
    validates known fields.  Returns a dict with defaults applied for
    any missing keys.

    Args:
        project_dir: Project root directory.  Defaults to the current
            working directory.

    Returns:
        Validated daemon configuration dict with keys: ``max_turns``,
        ``mode``, ``supervised``, ``schedules``, ``notifications``.

    Raises:
        ValueError: If ``daemon.mode`` is not one of the valid modes.
    """
    import yaml

    base_dir = Path(project_dir) if project_dir else Path.cwd()
    config_path = base_dir / ".sdlc" / "config.yaml"

    full_config: dict[str, Any] = {}
    if config_path.exists():
        try:
            with open(config_path) as f:
                full_config = yaml.safe_load(f) or {}
        except Exception:
            logger.warning("Failed to parse %s, using defaults", config_path)

    daemon_config = full_config.get("daemon", {})
    if not isinstance(daemon_config, dict):
        daemon_config = {}

    # Apply defaults
    result: dict[str, Any] = {
        "max_turns": daemon_config.get("max_turns", 200),
        "mode": daemon_config.get("mode", "session"),
        "adapter": daemon_config.get("adapter", "mock"),
        "supervised": daemon_config.get("supervised", False),
        "schedules": daemon_config.get("schedules") or [],
        "notifications": daemon_config.get("notifications") or [],
    }

    # Validate mode
    if result["mode"] not in _VALID_MODES:
        raise ValueError(
            f"Invalid daemon.mode: {result['mode']!r}. "
            f"Must be one of {_VALID_MODES}"
        )

    return result


def load_governance_config(project_dir: str | None = None) -> dict[str, Any]:
    """Load governance config from ``.sdlc/config.yaml``.

    Reads the ``governance:`` section from the project's config file.
    Returns a dict with ``enabled: False`` as default when not configured.

    Args:
        project_dir: Project root directory.  Defaults to the current
            working directory.

    Returns:
        Governance configuration dict.
    """
    import yaml

    base_dir = Path(project_dir) if project_dir else Path.cwd()
    config_path = base_dir / ".sdlc" / "config.yaml"

    if not config_path.exists():
        return {"enabled": False}

    try:
        with open(config_path) as f:
            full_config = yaml.safe_load(f) or {}
    except Exception:
        logger.warning("Failed to parse %s, using defaults", config_path)
        return {"enabled": False}

    governance = full_config.get("governance", {"enabled": False})
    if not isinstance(governance, dict):
        return {"enabled": False}
    return governance


def load_routing_config(project_dir: str | None = None) -> dict[str, Any]:
    """Load routing config from ``.sdlc/config.yaml``.

    Reads the ``routing:`` section from the project's config file.
    Returns an empty dict when not configured.

    Args:
        project_dir: Project root directory.  Defaults to the current
            working directory.

    Returns:
        Routing configuration dict.
    """
    import yaml

    base_dir = Path(project_dir) if project_dir else Path.cwd()
    config_path = base_dir / ".sdlc" / "config.yaml"

    if not config_path.exists():
        return {}

    try:
        with open(config_path) as f:
            full_config = yaml.safe_load(f) or {}
    except Exception:
        logger.warning("Failed to parse %s, using defaults", config_path)
        return {}

    routing = full_config.get("routing", {})
    if not isinstance(routing, dict):
        return {}
    return routing


def load_orchestrator_config(project_dir: str | None = None) -> dict[str, Any]:
    """Load and validate orchestrator config from ``.sdlc/config.yaml``.

    Reads the ``orchestrator:`` section from the project's config file and
    validates known fields.  Returns a dict with defaults applied for
    any missing keys.

    Args:
        project_dir: Project root directory.  Defaults to the current
            working directory.

    Returns:
        Validated orchestrator configuration dict with keys: ``enabled``,
        ``challenger_pairings``, ``max_iterations``, ``polling_interval``,
        ``max_turns_per_phase``.
    """
    import yaml

    base_dir = Path(project_dir) if project_dir else Path.cwd()
    config_path = base_dir / ".sdlc" / "config.yaml"

    full_config: dict[str, Any] = {}
    if config_path.exists():
        try:
            with open(config_path) as f:
                full_config = yaml.safe_load(f) or {}
        except Exception:
            logger.warning("Failed to parse %s, using defaults", config_path)

    orch_config = full_config.get("orchestrator", {})
    if not isinstance(orch_config, dict):
        orch_config = {}

    challenger_pairings = orch_config.get("challenger_pairings", {})
    if not isinstance(challenger_pairings, dict):
        challenger_pairings = {}

    return {
        "enabled": bool(orch_config.get("enabled", False)),
        "challenger_pairings": challenger_pairings,
        "max_iterations": int(orch_config.get("max_iterations", 5)),
        "polling_interval": int(orch_config.get("polling_interval", 30)),
        "max_turns_per_phase": int(orch_config.get("max_turns_per_phase", 200)),
    }


def evaluate_escalation_rules(
    task_id: str,
    task_metrics: dict[str, Any] | None = None,
    project_dir: str | None = None,
) -> list[dict[str, Any]]:
    """Evaluate escalation rules against task metrics (REM-001).

    Reads ``governance.escalation.rules`` from ``.sdlc/config.yaml`` and
    evaluates each rule's condition against the supplied *task_metrics*.

    Supported condition operators (parsed from string):

    * ``metric > threshold`` -- metric exceeds threshold
    * ``metric >= threshold`` -- metric meets or exceeds threshold
    * ``metric == value`` -- metric equals value

    Where *metric* is a key in *task_metrics* and *threshold* is numeric.

    Each triggered rule returns its configured ``action`` (e.g. ``pause``,
    ``alert``) so the caller can act accordingly.

    Args:
        task_id: Task identifier for logging context.
        task_metrics: Dict of current task metrics (e.g.
            ``{"retry_count": 4, "cost": 450, "blocked_duration_min": 35}``).
            Defaults to an empty dict.
        project_dir: Project root directory.  Defaults to cwd.

    Returns:
        List of triggered rule dicts, each containing ``rule``,
        ``action``, and ``reason``.  Empty list when no rules fire.
    """
    governance = load_governance_config(project_dir)
    escalation = governance.get("escalation", {})
    if not isinstance(escalation, dict):
        return []

    rules = escalation.get("rules") or []
    if not rules:
        return []

    metrics = task_metrics or {}
    triggered: list[dict[str, Any]] = []

    for rule in rules:
        if not isinstance(rule, dict):
            continue
        condition = rule.get("condition", "")
        action = rule.get("action", "alert")

        try:
            fired, reason = _evaluate_condition(condition, metrics)
        except Exception as exc:
            logger.warning(
                "Failed to evaluate escalation rule %r for task %s: %s",
                condition,
                task_id,
                exc,
            )
            continue

        if fired:
            logger.info(
                "Escalation rule fired for task %s: %s -> action=%s",
                task_id,
                reason,
                action,
            )
            triggered.append({
                "rule": condition,
                "action": action,
                "reason": reason,
                "notify": rule.get("notify", False),
            })

    return triggered


def _evaluate_condition(
    condition: str,
    metrics: dict[str, Any],
) -> tuple[bool, str]:
    """Parse and evaluate a single escalation condition string.

    Supported formats:
    * ``metric > value``
    * ``metric >= value``
    * ``metric == value``
    * ``metric < value``
    * ``metric <= value``

    Args:
        condition: Condition string (e.g. ``"retry_count > 3"``).
        metrics: Task metrics dict.

    Returns:
        ``(fired, reason)`` tuple.
    """
    import operator

    ops = {
        ">=": operator.ge,
        "<=": operator.le,
        ">": operator.gt,
        "<": operator.lt,
        "==": operator.eq,
    }

    # Try each operator (longest first to avoid >= matching as >)
    for op_str, op_fn in ops.items():
        if op_str in condition:
            parts = condition.split(op_str, 1)
            if len(parts) != 2:
                continue
            metric_name = parts[0].strip()
            try:
                threshold = float(parts[1].strip())
            except ValueError:
                continue

            metric_value = metrics.get(metric_name)
            if metric_value is None:
                return False, f"metric '{metric_name}' not available"

            try:
                fired = op_fn(float(metric_value), threshold)
            except (ValueError, TypeError):
                return False, f"metric '{metric_name}' not numeric"

            reason = (
                f"{metric_name}={metric_value} {op_str} {threshold}"
                if fired
                else f"{metric_name}={metric_value} did not fire"
            )
            return fired, reason

    return False, f"unparseable condition: {condition}"


def check_budget(
    storage: Any,
    agent_id: str,
    run_id: str | None = None,
) -> tuple[bool, str]:
    """Check if an agent has remaining budget.

    Queries the storage layer for budget data and checks both token
    and cost limits.  Returns a tuple of ``(allowed, reason)``.

    Args:
        storage: A storage instance with a ``get_agent_budget`` method.
        agent_id: The agent identifier to check.
        run_id: Optional run identifier to scope the budget check.

    Returns:
        ``(True, reason)`` when execution is allowed, or
        ``(False, reason)`` when a budget limit is exhausted.
    """
    budget = storage.get_agent_budget(agent_id, run_id=run_id)
    if not budget:
        return True, "No budget set"

    if budget.get("token_limit") and budget["token_limit"] > 0:
        if budget.get("token_used", 0) >= budget["token_limit"]:
            return False, (
                f"Token budget exhausted: "
                f"{budget['token_used']}/{budget['token_limit']}"
            )
        pct = budget["token_used"] * 100 / budget["token_limit"]
        if pct >= budget.get("alert_threshold_pct", 90):
            logger.warning(
                "Agent %s token budget at %.0f%% (%d/%d)",
                agent_id,
                pct,
                budget["token_used"],
                budget["token_limit"],
            )

    if (
        budget.get("cost_limit_cents")
        and budget["cost_limit_cents"] > 0
        and budget.get("cost_used_cents", 0) >= budget["cost_limit_cents"]
    ):
        return False, (
            f"Cost budget exhausted: "
            f"{budget['cost_used_cents']}/{budget['cost_limit_cents']}c"
        )

    return True, "Budget OK"


def execute_work_loop(
    agent_id: str,
    sprint_id: str | None = None,
    poll_interval: int = 30,
    max_iterations: int = 100,
    project_dir: str | None = None,
) -> None:
    """Autonomous work polling loop: poll, claim, execute, complete, repeat.

    This function runs a blocking loop that:

    1. Checks budget constraints (if governance is enabled).
    2. Detects and releases stale task claims.
    3. Finds available work via the storage layer.
    4. Claims the highest-priority task and logs the claim.
    5. Delegates execution to the existing :meth:`Executor.execute_task`
       pattern (currently a placeholder for integration).
    6. Sleeps for ``poll_interval`` seconds when no work is available.

    The loop terminates when:

    - ``max_iterations`` iterations have been reached.
    - Budget is exhausted (governance enabled).
    - No project is found.

    Args:
        agent_id: Identifier for this polling agent.
        sprint_id: Optional sprint scope for work queries.
        poll_interval: Seconds between polling cycles when idle.
        max_iterations: Maximum loop iterations before stopping.
        project_dir: Project root directory.  Defaults to the current
            working directory.
    """
    storage = get_storage()

    project = storage.get_most_recent_project()
    if not project:
        logger.error("No project found")
        return

    governance = load_governance_config(project_dir)
    routing = load_routing_config(project_dir)
    poll_interval = routing.get("poll_interval", poll_interval)
    stale_timeout = routing.get("stale_claim_timeout", 30)

    logger.info(
        "Work loop started for agent %s, sprint=%s, poll_interval=%ds",
        agent_id,
        sprint_id,
        poll_interval,
    )

    iteration = 0
    while iteration < max_iterations:
        iteration += 1

        # Budget check
        if governance.get("enabled"):
            allowed, reason = check_budget(storage, agent_id)
            if not allowed:
                logger.warning(
                    "Budget exceeded for %s: %s", agent_id, reason
                )
                break

        # Stale claim detection
        stale = storage.detect_stale_claims(stale_timeout)
        for claim in stale:
            logger.info(
                "Releasing stale claim on task %s by agent %s",
                claim["task_id"],
                claim["agent_id"],
            )
            try:
                storage.release_task(
                    claim["task_id"], claim["agent_id"], reason="stale_claim"
                )
            except Exception as exc:
                logger.warning("Failed to release stale claim: %s", exc)

        # Find available work
        available = storage.get_available_work(
            project["id"], agent_id, sprint_id=sprint_id
        )
        if not available:
            logger.info("No available work. Waiting %ds...", poll_interval)
            time.sleep(poll_interval)
            continue

        # Claim the highest priority task
        task = available[0]
        try:
            storage.claim_task(task["id"], agent_id)
            logger.info("Claimed task %s: %s", task["id"], task["title"])
        except ValueError as exc:
            logger.info("Could not claim %s: %s", task["id"], exc)
            continue

        # Execute task via adapter
        try:
            from a_sdlc.adapters import create_adapter
            from a_sdlc.server import build_execute_task_prompt

            daemon_config = load_daemon_config(project_dir)
            adapter = create_adapter(daemon_config.get("adapter", "mock"))
            prompt = build_execute_task_prompt(task["id"], task)
            result = adapter.execute(
                prompt=prompt,
                max_turns=daemon_config.get("max_turns", 200),
                working_dir=project_dir or os.getcwd(),
                allowed_tools=[
                    "Read", "Write", "Edit", "Bash",
                    "Glob", "Grep", "mcp__asdlc__*",
                ],
            )
            outcome = Executor._extract_outcome_block(
                result.get("result", ""),
                "---TASK-OUTCOME---",
                "---END-OUTCOME---",
            )
            logger.info(
                "Task %s outcome: %s",
                task["id"],
                outcome.get("verdict", "UNKNOWN"),
            )

            # Governance: budget reporting and escalation (config-gated)
            if governance.get("enabled"):
                turns = result.get("turns", 0)
                cost_usd = result.get("cost_usd", 0)
                try:
                    storage.increment_agent_budget(
                        agent_id,
                        tokens_delta=turns * 4000,
                        cost_delta=int(cost_usd * 100),
                    )
                except Exception as budget_exc:
                    logger.warning(
                        "Budget reporting failed for %s: %s",
                        task["id"],
                        budget_exc,
                    )

                try:
                    triggered = evaluate_escalation_rules(
                        task["id"],
                        task_metrics={
                            "verdict": outcome.get("verdict", "UNKNOWN"),
                            "cost_usd": cost_usd,
                        },
                        project_dir=project_dir,
                    )
                    for rule in triggered:
                        if rule.get("action") == "pause":
                            logger.warning(
                                "Escalation triggered for %s: %s",
                                task["id"],
                                rule.get("reason", "unknown"),
                            )
                            break
                except Exception as esc_exc:
                    logger.warning(
                        "Escalation check failed for %s: %s",
                        task["id"],
                        esc_exc,
                    )
        except Exception as exc:
            logger.error("Task %s execution failed: %s", task["id"], exc)
            storage.release_task(
                task["id"], agent_id, reason=f"execution_error: {exc}"
            )
            continue

    logger.info("Work loop ended after %d iterations", iteration)


def load_objective_config(project_dir: str | None = None) -> dict[str, Any]:
    """Load and validate objective config from ``.sdlc/config.yaml``.

    Reads the ``objective:`` section and validates known fields.
    Returns a dict with defaults applied for any missing keys.

    Args:
        project_dir: Project root directory.  Defaults to the current
            working directory.

    Returns:
        Validated objective configuration dict with keys:
        ``max_iterations``, ``max_turns``, ``evaluation``.
    """
    import yaml

    base_dir = Path(project_dir) if project_dir else Path.cwd()
    config_path = base_dir / ".sdlc" / "config.yaml"

    full_config: dict[str, Any] = {}
    if config_path.exists():
        try:
            with open(config_path) as f:
                full_config = yaml.safe_load(f) or {}
        except Exception:
            logger.warning("Failed to parse %s, using defaults", config_path)

    obj_config = full_config.get("objective", {})
    if not isinstance(obj_config, dict):
        obj_config = {}

    evaluation = obj_config.get("evaluation", {})
    if not isinstance(evaluation, dict):
        evaluation = {}

    return {
        "max_iterations": obj_config.get("max_iterations", 5),
        "max_turns": obj_config.get("max_turns", 500),
        "evaluation": {
            "commands": evaluation.get("commands") or [],
        },
    }


# ---------------------------------------------------------------------------
# Interim run-state helpers (JSON files until P0020 execution_runs table)
# ---------------------------------------------------------------------------

_RUNS_DIR = Path.home() / ".a-sdlc" / "runs"


def _ensure_runs_dir() -> Path:
    """Create the interim runs directory if it does not exist."""
    _RUNS_DIR.mkdir(parents=True, exist_ok=True)
    return _RUNS_DIR


def _run_path(run_id: str) -> Path:
    """Return the path to a run's JSON state file."""
    return _ensure_runs_dir() / f"{run_id}.json"


def _read_run(run_id: str) -> dict[str, Any]:
    """Read a run's state from its JSON file.

    Returns an empty dict if the file does not exist.
    """
    path = _run_path(run_id)
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _write_run(run_id: str, data: dict[str, Any]) -> None:
    """Write a run's state to its JSON file."""
    path = _run_path(run_id)
    path.write_text(json.dumps(data, indent=2, default=str))


def _update_run(run_id: str, **kwargs: Any) -> dict[str, Any]:
    """Merge *kwargs* into the run's existing state and persist."""
    data = _read_run(run_id)
    data.update(kwargs)
    _write_run(run_id, data)
    return data


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


class Executor:
    """Orchestrates background execution by spawning Claude Code sessions.

    Instead of calling the Claude API directly, this executor spawns
    ``claude -p "<prompt>"`` subprocesses.  Each subprocess is a full
    Claude Code session with:

    * MCP tool access (``mcp__asdlc__*`` tools for state tracking)
    * File read/write/edit capabilities
    * Shell command execution (tests, git)
    * Skill template access (``/sdlc:task-start``, etc.)
    """

    def __init__(
        self,
        max_turns: int = 200,
        max_concurrency: int = 3,
        project_dir: str | None = None,
        supervised: bool = False,
    ) -> None:
        """Initialise the executor.

        Args:
            max_turns: Maximum agentic turns per Claude Code session.
            max_concurrency: Maximum concurrent ``claude -p`` sessions
                when using :meth:`execute_sprint_parallel`.
            project_dir: Working directory for spawned sessions.
                Defaults to the current working directory.
            supervised: When ``True``, execution pauses between batches
                and waits for user approval via ``a-sdlc run approve``.

        Raises:
            RuntimeError: If the ``claude`` CLI is not found on ``PATH``.
        """
        self.max_turns = max_turns
        self.max_concurrency = max_concurrency
        self.project_dir = project_dir or os.getcwd()
        self.supervised = supervised
        self.storage = get_storage()

        # Verify claude CLI is available
        claude_path = shutil.which("claude")
        if not claude_path:
            raise RuntimeError(
                "Claude Code CLI not found on PATH. "
                "Install from: https://claude.ai/code\n"
                "After installation, ensure 'claude' is available in your shell."
            )
        self.claude_path: str = claude_path

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def execute_sprint(self, sprint_id: str, run_id: str) -> dict[str, Any]:
        """Execute a full sprint via a single Claude Code session.

        Spawns one ``claude -p`` session with the sprint-run prompt.
        The session executes the entire sprint workflow internally,
        using the Task tool for subagent dispatch, batch management,
        and review gates -- identical to interactive ``/sdlc:sprint-run``.

        In **supervised mode** the prompt instructs the session to output
        a ``---BATCH-CHECKPOINT---`` marker and stop after each batch.
        The executor detects this, pauses for user approval, then resumes
        the same session via ``claude --resume <session_id> -p "Approved..."``.

        Args:
            sprint_id: The sprint identifier (e.g. ``PROJ-S0001``).
            run_id: The execution run identifier.

        Returns:
            Parsed sprint outcome dictionary.
        """
        prompt = self._build_sprint_prompt(sprint_id, run_id)
        allowed_tools = [
            "Read",
            "Write",
            "Edit",
            "Bash",
            "Glob",
            "Grep",
            "Task",
            "TaskOutput",
            "TaskStop",
            "mcp__asdlc__*",
        ]

        if not self.supervised:
            # Autonomous: single session runs to completion
            result = self._spawn_claude_session(
                prompt=prompt,
                max_turns=self.max_turns,
                allowed_tools=allowed_tools,
            )
            return self._parse_sprint_result(result)

        # Supervised: iterative session with pause/resume between batches
        session_id: str | None = None
        batch_num = 0

        while True:
            result = self._spawn_claude_session(
                prompt=prompt,
                max_turns=self.max_turns,
                allowed_tools=allowed_tools,
                session_id=session_id,
            )

            # Extract session_id from Claude Code JSON output for --resume
            session_id = result.get("session_id")

            # Check if session output contains a batch checkpoint
            output_text = result.get("result", result.get("text", ""))
            if "---BATCH-CHECKPOINT---" in str(output_text):
                # Session paused at batch boundary -- await user approval
                self._await_user_confirmation(run_id, batch_num, {})
                batch_num += 1

                # Build resume prompt with user's message (if any)
                run_data = _read_run(run_id)
                user_msg = run_data.get("config", {}).get("approval_message", "")
                prompt = f"User approved batch {batch_num}. Continue to next batch." + (
                    f"\nUser message: {user_msg}" if user_msg else ""
                )
                continue

            # No checkpoint marker -- session completed or errored
            return self._parse_sprint_result(result)

    def execute_task(self, task_id: str, run_id: str) -> dict[str, Any]:
        """Execute a single task via a Claude Code session.

        Builds a task-specific prompt and spawns a headless session with
        ``max_turns`` capped at 50 for single-task execution.

        Args:
            task_id: The task identifier (e.g. ``PROJ-T00001``).
            run_id: The execution run identifier.

        Returns:
            Parsed task outcome dictionary.
        """
        prompt = self._build_task_prompt(task_id, run_id)

        result = self._spawn_claude_session(
            prompt=prompt,
            max_turns=min(self.max_turns, 50),
            allowed_tools=[
                "Read",
                "Write",
                "Edit",
                "Bash",
                "Glob",
                "Grep",
                "mcp__asdlc__*",
            ],
        )

        return self._parse_task_result(result)

    def execute_sprint_parallel(self, sprint_id: str, run_id: str) -> dict[str, Any]:
        """Execute sprint tasks in parallel via multiple Claude Code sessions.

        Alternative to :meth:`execute_sprint` -- instead of one session
        running the sprint-run template, the executor manages batch
        orchestration itself and spawns one Claude Code session per task.

        Uses :class:`concurrent.futures.ThreadPoolExecutor` for
        parallelism, with one ``claude -p`` subprocess per task in each
        batch.

        Args:
            sprint_id: The sprint identifier.
            run_id: The execution run identifier.

        Returns:
            Dictionary with ``outcomes`` mapping task IDs to results
            and ``batches_completed`` count.
        """
        import concurrent.futures

        outcomes: dict[str, Any] = {}

        # Derive project_id from sprint
        sprint = self.storage.get_sprint(sprint_id)
        if not sprint:
            return {
                "outcomes": {},
                "batches_completed": 0,
                "error": f"Sprint {sprint_id} not found",
            }
        project_id = sprint["project_id"]

        sprint_tasks = self.storage.list_tasks_by_sprint(project_id, sprint_id)
        batches = self._build_batches(sprint_tasks)

        for batch_num, batch in enumerate(batches):
            # Pre-allocate outcome slots (SDLC-P0021 FR-001)
            for task in batch:
                outcomes[task["id"]] = None

            with concurrent.futures.ThreadPoolExecutor(
                max_workers=self.max_concurrency,
            ) as pool:
                future_to_task: dict[concurrent.futures.Future, dict] = {}
                for task in batch:
                    # Register agent + claim task
                    # TODO: Replace with self.storage.create_agent_assignment()
                    #       when P0020 execution_runs tables are implemented.
                    agent_id = f"daemon-{task['id']}"
                    agent_type = self._resolve_persona_type(task.get("component"))
                    _update_run(
                        run_id,
                        **{
                            f"agent_{agent_id}": {
                                "agent_type": agent_type,
                                "task_id": task["id"],
                                "status": "assigned",
                            }
                        },
                    )
                    self.storage.update_task(task["id"], status="in_progress")

                    prompt = self._build_task_prompt(task["id"], run_id)
                    future = pool.submit(
                        self._spawn_claude_session,
                        prompt=prompt,
                        max_turns=50,
                        allowed_tools=[
                            "Read",
                            "Write",
                            "Edit",
                            "Bash",
                            "Glob",
                            "Grep",
                            "mcp__asdlc__*",
                        ],
                    )
                    future_to_task[future] = task

                for future in concurrent.futures.as_completed(future_to_task):
                    task = future_to_task[future]
                    try:
                        result = future.result()
                        outcome = self._parse_task_result(result)
                        outcomes[task["id"]] = outcome.get("summary", "completed")
                        self.storage.update_task(task["id"], status="completed")
                    except Exception as exc:
                        outcomes[task["id"]] = f"[failed: {exc}]"
                        self.storage.update_task(task["id"], status="blocked")

                    # Report progress
                    # TODO: Replace with self.storage.create_agent_progress()
                    #       when P0020 execution_runs tables are implemented.
                    task_status = (
                        "completed"
                        if "failed" not in str(outcomes.get(task["id"], ""))
                        else "failed"
                    )
                    _update_run(
                        run_id,
                        **{
                            f"progress_{task['id']}": {
                                "agent_id": f"daemon-{task['id']}",
                                "task_id": task["id"],
                                "status": task_status,
                            }
                        },
                    )

            # Supervised mode: pause between batches (not after last batch)
            if self.supervised and batch_num < len(batches) - 1:
                self._await_user_confirmation(run_id, batch_num, outcomes)

        return {"outcomes": outcomes, "batches_completed": len(batches)}

    def execute_objective(
        self,
        description: str,
        run_id: str,
        max_iterations: int = 5,
        objective_file: str | None = None,
    ) -> dict[str, Any]:
        """Execute an autonomous goal loop via a single Claude Code session.

        Orchestrates the full SDLC cycle -- analyse objective, create PRDs,
        split tasks, create/run sprints -- until acceptance criteria are met
        or *max_iterations* is reached.

        In **supervised mode** the prompt instructs the session to output
        a ``---ITERATION-CHECKPOINT---`` marker after each iteration.  The
        executor detects this, pauses for user approval, then resumes the
        same session.

        Args:
            description: The objective description / goal statement.
            run_id: The execution run identifier.
            max_iterations: Maximum SDLC iterations before stopping.
            objective_file: Optional path to a file containing the full
                objective specification.

        Returns:
            Parsed objective outcome dictionary.
        """
        prompt = self._build_objective_prompt(
            description, run_id, max_iterations, objective_file
        )
        allowed_tools = [
            "Read",
            "Write",
            "Edit",
            "Bash",
            "Glob",
            "Grep",
            "Task",
            "TaskOutput",
            "TaskStop",
            "mcp__asdlc__*",
        ]

        if not self.supervised:
            # Autonomous: single session runs to completion
            result = self._spawn_claude_session(
                prompt=prompt,
                max_turns=self.max_turns,
                allowed_tools=allowed_tools,
            )
            return self._parse_objective_result(result)

        # Supervised: iterative session with pause/resume between iterations
        session_id: str | None = None
        iteration = 0

        while True:
            result = self._spawn_claude_session(
                prompt=prompt,
                max_turns=self.max_turns,
                allowed_tools=allowed_tools,
                session_id=session_id,
            )

            # Extract session_id from Claude Code JSON output for --resume
            session_id = result.get("session_id")

            # Check if session output contains an iteration checkpoint
            output_text = result.get("result", result.get("text", ""))
            if "---ITERATION-CHECKPOINT---" in str(output_text):
                # Session paused at iteration boundary -- await user approval
                self._await_user_confirmation(run_id, iteration, {})
                iteration += 1

                # Build resume prompt with user's message (if any)
                run_data = _read_run(run_id)
                user_msg = run_data.get("config", {}).get("approval_message", "")
                prompt = (
                    f"User approved iteration {iteration}. "
                    "Continue to next iteration."
                ) + (f"\nUser message: {user_msg}" if user_msg else "")
                continue

            # No checkpoint marker -- session completed or errored
            return self._parse_objective_result(result)

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def _spawn_claude_session(
        self,
        prompt: str,
        max_turns: int = 200,
        allowed_tools: list[str] | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Spawn a headless Claude Code session via ``claude -p``.

        Args:
            prompt: The prompt to send to Claude Code.
            max_turns: Maximum agentic turns.
            allowed_tools: Tools to auto-approve (no permission prompts).
            session_id: If provided, resumes an existing session via
                ``claude --resume <id> -p <prompt>`` instead of starting
                a new one.  Used for supervised-mode batch continuations.

        Returns:
            Parsed JSON response from Claude Code.  Includes a
            ``session_id`` field for potential ``--resume`` follow-ups.
        """
        cmd: list[str] = [self.claude_path]

        if session_id:
            cmd.extend(["--resume", session_id])

        cmd.extend(
            [
                "-p",
                prompt,
                "--output-format",
                "json",
                "--max-turns",
                str(max_turns),
            ]
        )

        if allowed_tools:
            cmd.extend(["--allowedTools", ",".join(allowed_tools)])

        try:
            result = subprocess.run(
                cmd,
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                timeout=max_turns * 60,  # ~1 min per turn as safety timeout
            )
        except subprocess.TimeoutExpired:
            return {
                "status": "error",
                "error": (f"Claude Code session timed out after {max_turns * 60} seconds"),
                "exit_code": -1,
            }

        if result.returncode != 0:
            return {
                "status": "error",
                "error": result.stderr[:2000],
                "exit_code": result.returncode,
            }

        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return {
                "status": "error",
                "error": "Failed to parse Claude Code output as JSON",
                "raw_output": result.stdout[:2000],
            }

    # ------------------------------------------------------------------
    # Supervised-mode confirmation
    # ------------------------------------------------------------------

    def _await_user_confirmation(
        self,
        run_id: str,
        batch_num: int,
        outcomes: dict[str, Any],
    ) -> None:
        """Pause execution and wait for user approval.

        Sets the execution run status to ``awaiting_confirmation`` with a
        summary of what was completed.  Polls the run state file every
        30 seconds for the user's response (set by ``a-sdlc run approve``
        or ``a-sdlc run reject``).

        Args:
            run_id: The execution run identifier.
            batch_num: Zero-based index of the completed batch.
            outcomes: Current outcomes dict mapping task IDs to results.

        Raises:
            SystemExit: If the user rejects the run via
                ``a-sdlc run reject``.
        """
        completed = sum(1 for v in outcomes.values() if v and "failed" not in str(v))
        failed = sum(1 for v in outcomes.values() if v and "failed" in str(v))

        # Store checkpoint state
        # TODO: Replace with self.storage.update_execution_run() when
        #       P0020 execution_runs tables are implemented.
        _update_run(
            run_id,
            status="awaiting_confirmation",
            config={
                "checkpoint_batch": batch_num,
                "completed_tasks": completed,
                "failed_tasks": failed,
                "message": (
                    f"Batch {batch_num + 1} complete: {completed} passed, "
                    f"{failed} failed. Approve to continue to "
                    f"batch {batch_num + 2}?"
                ),
            },
        )

        # Poll for user response
        while True:
            time.sleep(30)

            # TODO: Replace with self.storage.get_execution_run(run_id)
            #       when P0020 execution_runs tables are implemented.
            run_data = _read_run(run_id)
            status = run_data.get("status")

            if status == "running":
                # User approved via `a-sdlc run approve` -- continue
                user_msg = run_data.get("config", {}).get("approval_message", "")
                if user_msg:
                    logger.info(
                        "Run %s approved with message: %s",
                        run_id,
                        user_msg,
                    )
                return

            if status == "cancelled":
                # User rejected via `a-sdlc run reject` -- stop execution
                reason = run_data.get("config", {}).get("rejection_reason", "")
                raise SystemExit(f"Run {run_id} rejected by user: {reason}")

    # ------------------------------------------------------------------
    # Prompt builders
    # ------------------------------------------------------------------

    def _build_sprint_prompt(self, sprint_id: str, run_id: str) -> str:
        """Build prompt for sprint execution session.

        The prompt instructs Claude Code to run the sprint-run workflow,
        which handles batching, context packages, review gates, etc.

        In supervised mode, the prompt adds checkpoint instructions that
        tell the session to stop after each batch for user approval.

        Args:
            sprint_id: The sprint identifier.
            run_id: The execution run identifier.

        Returns:
            Fully-formed prompt string.
        """
        checkpoint_instructions = ""
        if self.supervised:
            checkpoint_instructions = """
SUPERVISED MODE: After completing each batch, you MUST:
1. Output a batch summary with completed/failed task counts
2. Output the marker: ---BATCH-CHECKPOINT---
3. STOP and wait. Do NOT proceed to the next batch.
The user will review your work and resume the session with approval.
"""

        autonomous_instructions = ""
        if not self.supervised:
            autonomous_instructions = (
                "IMPORTANT: This is a background execution -- do not use "
                "AskUserQuestion.\nMake autonomous decisions. If a task "
                "fails, mark it as blocked and continue.\n"
            )

        return f"""Execute sprint {sprint_id} (run: {run_id}).

Use the a-sdlc MCP tools and follow the sprint-run workflow:

1. Call mcp__asdlc__get_sprint(sprint_id="{sprint_id}") to load sprint data
2. Call mcp__asdlc__get_sprint_tasks(sprint_id="{sprint_id}") to get all tasks
3. Build dependency batches using topological sort (Kahn's algorithm)
4. For each batch, execute tasks following the sprint-run template pattern:
   - Build context package for each task (task content + PRD + design + codebase artifacts)
   - Implement the task: read specs, write code, run tests
   - Self-review: verify acceptance criteria, run test commands from .sdlc/config.yaml
   - Call mcp__asdlc__submit_review(reviewer_type='self') with test evidence
   - Call mcp__asdlc__report_progress() to update state
5. Call mcp__asdlc__complete_execution_run(run_id="{run_id}") when done
{checkpoint_instructions}{autonomous_instructions}
Output a structured summary at the end:
---SPRINT-OUTCOME---
sprint_id: {sprint_id}
run_id: {run_id}
completed: <count>
failed: <count>
skipped: <count>
summary: <one paragraph>
---END-OUTCOME---
"""

    def _build_task_prompt(self, task_id: str, run_id: str) -> str:
        """Build prompt for single-task execution session.

        Args:
            task_id: The task identifier.
            run_id: The execution run identifier.

        Returns:
            Fully-formed prompt string.
        """
        return f"""Execute task {task_id} (run: {run_id}).

1. Call mcp__asdlc__get_task(task_id="{task_id}") to load task details
2. Read the task content file for full specifications
3. If task has a PRD, read the PRD and design doc for context
4. Implement the task following the Implementation Steps
5. Write tests as specified in Acceptance Criteria
6. Run tests from .sdlc/config.yaml testing.commands
7. Call mcp__asdlc__submit_review(reviewer_type='self') with test evidence
8. Call mcp__asdlc__report_progress() to update state

IMPORTANT: This is a background execution -- do not use AskUserQuestion.

---TASK-OUTCOME---
task_id: {task_id}
verdict: PASS|FAIL|BLOCKED
files_changed: <comma-separated>
tests: <passed>/<total>
summary: <one-line description>
---END-OUTCOME---
"""

    def _build_objective_prompt(
        self,
        description: str,
        run_id: str,
        max_iterations: int,
        objective_file: str | None = None,
    ) -> str:
        """Build the full orchestrator prompt for the autonomous goal loop.

        Constructs a comprehensive prompt covering all SDLC loop phases:
        planning, sprint execution, evaluation, iteration, and completion.

        Args:
            description: The objective description / goal statement.
            run_id: The execution run identifier.
            max_iterations: Maximum SDLC iterations.
            objective_file: Optional path to a file with the full
                objective specification.

        Returns:
            Fully-formed prompt string.
        """
        checkpoint_instructions = ""
        if self.supervised:
            checkpoint_instructions = (
                "\nSUPERVISED MODE: After completing each iteration, you MUST:\n"
                "1. Output an iteration summary (what was done, test results, remaining gaps)\n"
                "2. Output the marker: ---ITERATION-CHECKPOINT---\n"
                "3. STOP and wait. Do NOT start the next iteration.\n"
                "The user will review your work and resume the session with approval.\n"
            )

        autonomous_instructions = ""
        if not self.supervised:
            autonomous_instructions = (
                "\nAUTONOMOUS MODE: Do not use AskUserQuestion. "
                "Make autonomous decisions.\n"
                "If a task fails, create a fix PRD in the next iteration "
                "instead of stopping.\n"
            )

        objective_file_section = ""
        if objective_file:
            objective_file_section = (
                f"\nObjective specification file: {objective_file}\n"
                "Read this file for the full objective details before starting.\n"
            )

        return f"""Execute objective (run: {run_id}, max iterations: {max_iterations}).

Objective: {description}
{objective_file_section}
You are an orchestrator agent driving the full SDLC loop. Follow these phases:

## Phase 0: Discovery (always start here)
1. Read project context: call mcp__asdlc__get_context()
2. Discover existing work:
   - mcp__asdlc__list_prds()
   - mcp__asdlc__list_sprints()
3. Match the goal description against existing entities.
   - If a specific PRD is mentioned (e.g. "pick up PROJ-P0001"), read it: mcp__asdlc__get_prd(prd_id)
   - If existing PRDs/sprints match the goal, decide where to pick up from:
     * PRD draft -> Go to Phase 1 (refine/update)
     * PRD ready, no tasks -> Go to Phase 1 (split)
     * Sprint active -> Go to Phase 2 (execute)

## Phase 1: Planning
1. Read .sdlc/lesson-learn.md and ~/.a-sdlc/lesson-learn.md for project lessons
2. Read .sdlc/artifacts/ for codebase documentation if available
3. Analyse the objective and produce concrete acceptance criteria
4. Create/Update PRDs: call mcp__asdlc__create_prd() or mcp__asdlc__update_prd()
   - Write/Update detailed content to the file_path using the Write/Edit tool
   - Include: Overview, Problem Statement, Goals, Functional Requirements, Acceptance Criteria
5. Split each PRD into tasks: call mcp__asdlc__split_prd() or mcp__asdlc__create_task()
   - Write detailed task content to the returned file_path using the Write tool

## Phase 2: Sprint Execution (per iteration)
1. Create sprint: mcp__asdlc__create_sprint(title="Objective - Iteration N", goal="...")
2. Add PRDs: mcp__asdlc__manage_sprint_prds(action="add", prd_id=..., sprint_id=...)
3. Start sprint: mcp__asdlc__update_sprint(sprint_id=..., status="active")
4. Execute tasks in dependency order. For each task:
   a. mcp__asdlc__get_task(task_id=...) to load details
   b. Implement the code changes
   c. Write tests as specified
   d. Run tests via Bash
   e. mcp__asdlc__submit_review(task_id=..., reviewer_type='self', verdict=..., findings=...)
   f. mcp__asdlc__update_task(task_id=..., status="completed")
5. If ALL tasks in a sprint fail, STOP immediately with status FAILED
6. Commit changes if git.auto_commit is enabled in .sdlc/config.yaml

## Phase 3: Evaluation (after each sprint)
1. Run test suite from .sdlc/config.yaml testing.commands (or objective.evaluation.commands)
2. Run linter/type checks if configured
3. Record results: total tests, passed, failed, coverage
4. Check acceptance criteria from Phase 1
5. Decision:
   - All criteria met -> Phase 4 (status: COMPLETED)
   - Max iterations ({max_iterations}) reached -> Phase 4 (status: PARTIAL)
   - Otherwise -> Phase 3b (iterate)
{checkpoint_instructions}
## Phase 3b: Iteration (loop back to Phase 2)
ANTI-REPETITION RULE (CRITICAL): Before creating new PRDs, review what was attempted
in previous iterations. If an approach failed, try a DIFFERENT strategy. Document why
the previous approach failed and what the new approach changes. Never repeat the same
failing approach.
1. Analyse failures from test output
2. Create targeted fix PRDs with structure:
   - Previous attempt: (what was tried)
   - Failure reason: (why it failed)
   - New approach: (what changes this time)
3. Split fix PRDs into tasks -> Go to Phase 2

## Phase 4: Completion
Write final summary to the objective file (if provided).
Output this structured block:
---OBJECTIVE-OUTCOME---
run_id: {run_id}
objective: {description}
iterations_used: <N>/{max_iterations}
status: COMPLETED|PARTIAL|FAILED
sprints_created: <comma-separated list>
prds_created: <comma-separated list>
completed: <total tasks completed>
failed: <total tasks failed>
skipped: <total tasks skipped>
tests_passing: <X>/<Y>
criteria_met: <comma-separated list>
criteria_not_met: <comma-separated list>
summary: <one paragraph>
---END-OUTCOME---

## Execution Rules
- Do NOT use AskUserQuestion (autonomous execution)
- Log corrections via mcp__asdlc__log_correction() when fixing mistakes
- Prefer small focused PRDs over large monolithic ones
- Each iteration's PRDs must reference previous iteration's failures
- Run tests frequently (after each task)
{autonomous_instructions}"""

    # ------------------------------------------------------------------
    # Batch / dependency management
    # ------------------------------------------------------------------

    def _build_batches(self, tasks: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
        """Build dependency-respecting batches using Kahn's algorithm.

        Tasks that are already completed or in-progress are treated as
        resolved and do not appear in any batch.  Remaining tasks are
        grouped into batches where all dependencies within a batch are
        satisfied by previously-resolved or previously-batched tasks.

        If circular dependencies are detected (no progress can be made),
        the algorithm stops and returns the batches built so far.

        Args:
            tasks: List of task dicts, each with at least ``id``,
                ``status``, and optionally ``dependencies`` (list of
                task IDs).

        Returns:
            List of batches, where each batch is a list of task dicts.
        """
        resolved_ids = {t["id"] for t in tasks if t.get("status") in ("completed", "in_progress")}
        pending = [t for t in tasks if t.get("status") not in ("completed", "in_progress")]
        batches: list[list[dict[str, Any]]] = []
        placed_ids = set(resolved_ids)

        while pending:
            current_batch: list[dict[str, Any]] = []
            still_pending: list[dict[str, Any]] = []

            for task in pending:
                deps = task.get("dependencies", [])
                unmet = [d for d in deps if d not in placed_ids]
                if not unmet:
                    current_batch.append(task)
                else:
                    still_pending.append(task)

            if not current_batch:
                # Circular dependencies detected -- cannot make progress
                logger.warning(
                    "Circular dependencies detected among %d remaining tasks: %s",
                    len(still_pending),
                    [t["id"] for t in still_pending],
                )
                break

            batches.append(current_batch)
            for task in current_batch:
                placed_ids.add(task["id"])
            pending = still_pending

        return batches

    # ------------------------------------------------------------------
    # Persona / agent type resolution
    # ------------------------------------------------------------------

    def _resolve_persona_type(self, component: str | None) -> str:
        """Map a component string to an agent persona type.

        Uses keyword matching against known component categories to
        select the most appropriate agent persona from the round-table
        configuration.

        Args:
            component: The task's component field (e.g. ``"backend"``,
                ``"ui"``, ``"auth"``).  May be ``None``.

        Returns:
            Agent type string (e.g. ``"sdlc-backend-engineer"``).
            Defaults to ``"general-purpose"`` when no keyword matches.
        """
        if not component:
            return "general-purpose"

        component_lower = component.lower()
        mapping: dict[str, list[str]] = {
            "sdlc-backend-engineer": [
                "api",
                "backend",
                "server",
                "service",
                "middleware",
                "database",
                "model",
            ],
            "sdlc-frontend-engineer": [
                "ui",
                "frontend",
                "component",
                "layout",
                "style",
                "css",
                "react",
            ],
            "sdlc-devops-engineer": [
                "ci",
                "cd",
                "pipeline",
                "docker",
                "deploy",
                "infra",
                "monitoring",
            ],
            "sdlc-security-engineer": [
                "auth",
                "security",
                "encryption",
                "permissions",
                "owasp",
            ],
            "sdlc-architect": [
                "architecture",
                "design",
                "system",
            ],
            "sdlc-qa-engineer": [
                "test",
                "qa",
                "coverage",
                "e2e",
            ],
        }

        for agent_type, keywords in mapping.items():
            if any(kw in component_lower for kw in keywords):
                return agent_type

        return "general-purpose"

    # ------------------------------------------------------------------
    # Result parsers
    # ------------------------------------------------------------------

    def _parse_sprint_result(self, result: dict[str, Any]) -> dict[str, Any]:
        """Extract structured outcome from a sprint session's JSON output.

        Looks for the ``---SPRINT-OUTCOME---`` / ``---END-OUTCOME---``
        block in the session output and parses the key-value pairs.

        Args:
            result: Raw JSON output from the Claude Code session.

        Returns:
            Dictionary with parsed fields (``sprint_id``, ``run_id``,
            ``completed``, ``failed``, ``skipped``, ``summary``) plus
            the raw ``result`` dict.
        """
        if result.get("status") == "error":
            return {
                "status": "error",
                "error": result.get("error", "Unknown error"),
                "raw": result,
            }

        output_text = str(result.get("result", result.get("text", "")))
        parsed = self._extract_outcome_block(
            output_text,
            "---SPRINT-OUTCOME---",
            "---END-OUTCOME---",
        )
        parsed["raw"] = result
        parsed.setdefault("status", "completed")
        return parsed

    def _parse_task_result(self, result: dict[str, Any]) -> dict[str, Any]:
        """Extract structured outcome from a task session's JSON output.

        Looks for the ``---TASK-OUTCOME---`` / ``---END-OUTCOME---``
        block in the session output and parses the key-value pairs.

        Args:
            result: Raw JSON output from the Claude Code session.

        Returns:
            Dictionary with parsed fields (``task_id``, ``verdict``,
            ``files_changed``, ``tests``, ``summary``) plus the raw
            ``result`` dict.
        """
        if result.get("status") == "error":
            return {
                "status": "error",
                "error": result.get("error", "Unknown error"),
                "raw": result,
            }

        output_text = str(result.get("result", result.get("text", "")))
        parsed = self._extract_outcome_block(
            output_text,
            "---TASK-OUTCOME---",
            "---END-OUTCOME---",
        )
        parsed["raw"] = result
        parsed.setdefault("status", "completed")
        return parsed

    def _parse_objective_result(self, result: dict[str, Any]) -> dict[str, Any]:
        """Extract structured outcome from an objective session's JSON output.

        Looks for the ``---OBJECTIVE-OUTCOME---`` / ``---END-OUTCOME---``
        block in the session output and parses the key-value pairs.

        Args:
            result: Raw JSON output from the Claude Code session.

        Returns:
            Dictionary with parsed fields (``run_id``, ``iterations_used``,
            ``status``, ``prds_created``, ``completed``, ``failed``,
            ``skipped``, ``summary``) plus the raw ``result`` dict.
        """
        if result.get("status") == "error":
            return {
                "status": "error",
                "error": result.get("error", "Unknown error"),
                "raw": result,
            }

        output_text = str(result.get("result", result.get("text", "")))
        parsed = self._extract_outcome_block(
            output_text,
            "---OBJECTIVE-OUTCOME---",
            "---END-OUTCOME---",
        )
        parsed["raw"] = result
        parsed.setdefault("status", "completed")
        return parsed

    @staticmethod
    def _extract_outcome_block(
        text: str,
        start_marker: str,
        end_marker: str,
    ) -> dict[str, str]:
        """Parse a structured outcome block from session output text.

        The block is expected to be in YAML-like ``key: value`` format
        between the *start_marker* and *end_marker*.

        Args:
            text: Full output text to search.
            start_marker: Opening delimiter (e.g. ``---SPRINT-OUTCOME---``).
            end_marker: Closing delimiter (e.g. ``---END-OUTCOME---``).

        Returns:
            Dictionary of parsed key-value pairs.  Returns an empty dict
            if the markers are not found.
        """
        pattern = re.escape(start_marker) + r"(.*?)" + re.escape(end_marker)
        match = re.search(pattern, text, re.DOTALL)
        if not match:
            return {}

        block = match.group(1).strip()
        parsed: dict[str, str] = {}
        for line in block.splitlines():
            line = line.strip()
            if ":" in line:
                key, _, value = line.partition(":")
                parsed[key.strip()] = value.strip()
        return parsed


# ---------------------------------------------------------------------------
# __main__ entry point — used by CLI subprocess spawn
# ---------------------------------------------------------------------------


def _main() -> None:
    """Entry point for ``python -m a_sdlc.executor``.

    Parses command-line arguments and dispatches to the appropriate
    executor method.  Called by the CLI's ``run sprint`` and ``run task``
    commands via ``subprocess.Popen``.
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="a-sdlc background executor",
    )
    parser.add_argument(
        "--mode",
        required=True,
        choices=["sprint", "task", "objective"],
        help="Execution mode: sprint, task, or objective.",
    )
    parser.add_argument("--sprint-id", default=None, help="Sprint ID (for sprint mode).")
    parser.add_argument("--task-id", default=None, help="Task ID (for task mode).")
    parser.add_argument(
        "--description",
        default=None,
        help="Objective description (for objective mode).",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=5,
        help="Max SDLC iterations (objective mode).",
    )
    parser.add_argument(
        "--objective-file",
        default=None,
        help="Path to objective specification file (objective mode).",
    )
    parser.add_argument("--run-id", required=True, help="Run ID for state tracking.")
    parser.add_argument(
        "--max-turns",
        type=int,
        default=200,
        help="Max agentic turns per session.",
    )
    parser.add_argument(
        "--max-concurrency",
        type=int,
        default=3,
        help="Max concurrent sessions (parallel mode).",
    )
    parser.add_argument(
        "--supervised",
        action="store_true",
        default=False,
        help="Enable supervised mode with batch checkpoints.",
    )
    parser.add_argument(
        "--project-dir",
        default=None,
        help="Project directory (defaults to cwd).",
    )

    args = parser.parse_args()

    # Update run state with PID
    _update_run(args.run_id, pid=os.getpid(), status="running")

    try:
        executor = Executor(
            max_turns=args.max_turns,
            max_concurrency=args.max_concurrency,
            project_dir=args.project_dir,
            supervised=args.supervised,
        )

        # Load daemon config for mode selection and notification hooks
        config = load_daemon_config(args.project_dir)

        if args.mode == "sprint":
            if not args.sprint_id:
                logger.error("--sprint-id is required for sprint mode")
                _update_run(args.run_id, status="failed", error="Missing --sprint-id")
                raise SystemExit(1)

            mode = config.get("mode", "session")

            if mode == "parallel":
                outcome = executor.execute_sprint_parallel(args.sprint_id, args.run_id)
            else:
                outcome = executor.execute_sprint(args.sprint_id, args.run_id)

        elif args.mode == "task":
            if not args.task_id:
                logger.error("--task-id is required for task mode")
                _update_run(args.run_id, status="failed", error="Missing --task-id")
                raise SystemExit(1)
            outcome = executor.execute_task(args.task_id, args.run_id)

        elif args.mode == "objective":
            if not args.description:
                logger.error("--description is required for objective mode")
                _update_run(
                    args.run_id, status="failed", error="Missing --description"
                )
                raise SystemExit(1)
            outcome = executor.execute_objective(
                description=args.description,
                run_id=args.run_id,
                max_iterations=args.max_iterations,
                objective_file=args.objective_file,
            )

        else:
            _update_run(args.run_id, status="failed", error=f"Unknown mode: {args.mode}")
            raise SystemExit(1)

        # Mark run as completed with outcome
        _update_run(args.run_id, status="completed", outcome=outcome)

        # Run notification hooks (best-effort -- failures do not affect run status)
        try:
            from a_sdlc.notifications import run_notification_hooks

            run_notification_hooks(args.run_id, outcome, config)
        except Exception:
            logger.warning(
                "Notification hooks failed for run %s",
                args.run_id,
                exc_info=True,
            )

    except SystemExit:
        # Re-raise SystemExit (includes rejections) without marking as failed
        # since _await_user_confirmation already sets status="cancelled"
        raise
    except Exception as exc:
        logger.exception("Executor failed for run %s", args.run_id)
        _update_run(args.run_id, status="failed", error=str(exc))
        raise SystemExit(1) from exc


if __name__ == "__main__":
    _main()
