"""Autonomous Pipeline Orchestrator (SDLC-P0032).

This module serves as the entry point for background goal execution.
It provides a specialized CLI for the orchestrator process, which is
typically spawned by ``a-sdlc run goal``.
"""

import argparse
import logging
import os
import sys

from a_sdlc.executor import Executor, _update_run, load_daemon_config

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("a_sdlc.orchestrator")


def main() -> None:
    """Entry point for ``python -m a_sdlc.orchestrator``."""
    parser = argparse.ArgumentParser(
        description="a-sdlc autonomous pipeline orchestrator",
    )
    parser.add_argument("--run-id", required=True, help="Run ID for state tracking.")
    parser.add_argument(
        "--goal",
        required=False,
        help="Natural language goal description (if not set, read from run state).",
    )
    parser.add_argument(
        "--goal-file",
        default=None,
        help="Path to goal specification file.",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=5,
        help="Max SDLC iterations before stopping.",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=500,
        help="Max agentic turns per phase.",
    )
    parser.add_argument(
        "--max-concurrency",
        type=int,
        default=3,
        help="Max concurrent agent sessions.",
    )
    parser.add_argument(
        "--polling-interval",
        type=int,
        default=30,
        help="Seconds between polling cycles.",
    )
    parser.add_argument(
        "--no-interactive",
        action="store_true",
        default=False,
        help="Disable clarification pauses (fully autonomous).",
    )
    parser.add_argument(
        "--project-dir",
        default=None,
        help="Project directory (defaults to cwd).",
    )
    parser.add_argument(
        "--adapter",
        default=None,
        help="Execution adapter (claude, gemini, mock).",
    )

    args = parser.parse_args()

    # Update run state with PID
    _update_run(args.run_id, pid=os.getpid(), status="running")

    try:
        # Reuse Executor's objective mode for the core logic
        executor = Executor(
            max_turns=args.max_turns,
            max_concurrency=args.max_concurrency,
            project_dir=args.project_dir,
            supervised=not args.no_interactive,  # no-interactive maps to NOT supervised
        )

        # Load daemon config for notifications
        config = load_daemon_config(args.project_dir)

        # If goal is not provided on CLI, it MUST be in the run state
        goal = args.goal
        if not goal:
            from a_sdlc.executor import _read_run
            run_data = _read_run(args.run_id)
            if run_data:
                goal = run_data.get("goal") or run_data.get("description")

        if not goal:
            logger.error("No goal provided and none found in run state for %s", args.run_id)
            _update_run(args.run_id, status="failed", error="Missing goal description")
            sys.exit(1)

        outcome = executor.execute_objective(
            description=goal,
            run_id=args.run_id,
            max_iterations=args.max_iterations,
            objective_file=args.goal_file,
        )

        # Mark run as completed with outcome
        _update_run(args.run_id, status="completed", outcome=outcome)

        # Run notification hooks
        try:
            from a_sdlc.notifications import run_notification_hooks
            run_notification_hooks(args.run_id, outcome, config)
        except Exception:
            logger.warning("Notification hooks failed", exc_info=True)

    except Exception as exc:
        logger.exception("Orchestrator failed for run %s", args.run_id)
        _update_run(args.run_id, status="failed", error=str(exc))
        sys.exit(1)


if __name__ == "__main__":
    main()
