"""Background daemon for scheduled a-sdlc execution.

Manages daemon process lifecycle: PID file operations, rotating log
handler, graceful signal handling, and main event loop.  The PID
management follows the pattern established in
``src/a_sdlc/ui/__init__.py``.

Schedule matching uses a lightweight stdlib-only cron parser that
supports ``*``, specific values, and comma-separated lists for each
of the five standard cron fields (minute, hour, day-of-month, month,
day-of-week).  No external cron library is required.
"""

from __future__ import annotations

import atexit
import logging
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import FrameType

PID_FILE = Path.home() / ".a-sdlc" / "daemon.pid"
LOG_FILE = Path.home() / ".a-sdlc" / "daemon.log"

# ---------------------------------------------------------------------------
# PID management (follows ui/__init__.py:35-97 pattern)
# ---------------------------------------------------------------------------


def _get_pid() -> int | None:
    """Read PID from file if it exists.

    Returns:
        The PID as an integer, or ``None`` if the file does not exist
        or contains invalid data.
    """
    if PID_FILE.exists():
        try:
            return int(PID_FILE.read_text().strip())
        except (ValueError, OSError):
            return None
    return None


def _is_process_running(pid: int) -> bool:
    """Check if a process with the given PID is running.

    Uses ``os.kill(pid, 0)`` which sends no signal but raises
    :class:`OSError` if the process does not exist.

    Args:
        pid: Process ID to check.

    Returns:
        ``True`` if the process is alive, ``False`` otherwise.
    """
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _write_pid() -> None:
    """Write the current process PID to the PID file.

    Creates the parent directory (``~/.a-sdlc/``) if it does not
    exist.
    """
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))


def _remove_pid() -> None:
    """Remove the PID file if it exists.

    Silently ignores :class:`FileNotFoundError` and other OS errors
    so this is safe to call from ``atexit`` handlers.
    """
    try:
        if PID_FILE.exists():
            PID_FILE.unlink()
    except OSError:
        pass


def _cleanup_stale_pid() -> bool:
    """Detect and remove a stale PID file.

    If the PID file exists but the process is dead, the file is
    removed and ``True`` is returned (stale state was cleaned).

    If the PID file exists and the process is alive, no action is
    taken and ``False`` is returned (not stale -- daemon is running).

    If no PID file exists, returns ``False``.

    Returns:
        ``True`` if a stale PID file was cleaned up, ``False``
        otherwise.
    """
    pid = _get_pid()
    if pid is None:
        return False

    if _is_process_running(pid):
        # Process is alive -- not stale
        return False

    # PID file exists but process is gone -- clean up
    _remove_pid()
    return True


def stop_daemon() -> bool:
    """Stop the running daemon process.

    Sends ``SIGTERM`` for graceful shutdown.  If the process is still
    alive after 10 seconds, sends ``SIGKILL``.

    Returns:
        ``True`` if a daemon was stopped, ``False`` if no daemon was
        running.
    """
    pid = _get_pid()
    if pid is None:
        return False

    if not _is_process_running(pid):
        _remove_pid()
        return False

    try:
        os.kill(pid, signal.SIGTERM)

        # Wait up to 10 seconds for graceful shutdown
        for _ in range(20):
            time.sleep(0.5)
            if not _is_process_running(pid):
                _remove_pid()
                return True

        # Force kill if still running after timeout
        os.kill(pid, signal.SIGKILL)
        time.sleep(0.5)

        _remove_pid()
        return True
    except (OSError, ProcessLookupError):
        _remove_pid()
        return False


# ---------------------------------------------------------------------------
# Logging (NFR-005)
# ---------------------------------------------------------------------------


def _setup_logging() -> logging.Logger:
    """Configure daemon logging with rotation.

    Sets up a :class:`~logging.handlers.RotatingFileHandler` writing
    to ``~/.a-sdlc/daemon.log`` with a maximum size of 10 MB and up
    to 5 backup files.

    Returns:
        Configured logger instance named ``a-sdlc-daemon``.
    """
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=10_000_000,  # 10 MB
        backupCount=5,
    )
    handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(message)s"))
    logger = logging.getLogger("a-sdlc-daemon")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return logger


# ---------------------------------------------------------------------------
# Signal handling (NFR-003)
# ---------------------------------------------------------------------------

_shutdown_requested = False


def _signal_handler(signum: int, frame: FrameType | None) -> None:
    """Handle SIGTERM/SIGINT gracefully.

    Sets the module-level ``_shutdown_requested`` flag so the event
    loop can exit cleanly after its current iteration.  Does **not**
    call ``sys.exit()`` -- the event loop checks the flag.

    Args:
        signum: Signal number received.
        frame: Current stack frame (unused).
    """
    global _shutdown_requested
    _shutdown_requested = True


# ---------------------------------------------------------------------------
# Crash recovery (FR-012 / SDLC-T00123)
# ---------------------------------------------------------------------------


def _recover_incomplete_runs(logger: logging.Logger) -> int:
    """Detect and recover incomplete execution runs from crashes.

    On daemon startup, scans ``~/.a-sdlc/runs/`` for JSON run state
    files with ``status='running'`` or ``status='awaiting_confirmation'``.
    For each incomplete run, checks whether the executor process (PID
    stored in the run state) is still alive via :func:`_is_process_running`.

    Recovery actions:

    * If the PID is dead: mark the run as ``"failed"`` with crash
      metadata (``crash_reason``, ``crash_detected_at``,
      ``original_status``), and log a warning.
    * If the PID is alive: the run is legitimately in progress; log an
      informational message and leave it alone.
    * If no PID field exists: assume the executor crashed before it
      could record its PID; mark as failed.

    Args:
        logger: Logger instance for recovery events.

    Returns:
        Number of runs that were marked as failed (recovered).
    """
    from a_sdlc.executor import _RUNS_DIR, _read_run

    logger.info("Starting crash recovery check...")

    # Guard: runs directory may not exist yet (fresh install)
    if not _RUNS_DIR.exists():
        logger.info("Runs directory does not exist, nothing to recover")
        return 0

    # Collect all run state files
    run_files = sorted(_RUNS_DIR.glob("*.json"))
    if not run_files:
        logger.info("No run state files found, nothing to recover")
        return 0

    recovered_count = 0

    for run_file in run_files:
        run_id = run_file.stem  # filename without .json extension

        try:
            run_data = _read_run(run_id)
        except Exception as exc:
            logger.warning("Failed to read run state file %s: %s", run_file, exc)
            continue

        if not run_data:
            continue

        status = run_data.get("status")
        if status not in ("running", "awaiting_confirmation"):
            continue

        executor_pid = run_data.get("pid")

        if executor_pid is None:
            # No PID recorded -- executor crashed before writing PID,
            # or legacy run state format without PID tracking.
            logger.warning(
                "Run %s (status=%s) has no executor PID, assuming crashed",
                run_id,
                status,
            )
            _mark_run_as_crashed(run_id, status, None, logger)
            recovered_count += 1
            continue

        # Ensure PID is an integer
        try:
            executor_pid = int(executor_pid)
        except (TypeError, ValueError):
            logger.warning(
                "Run %s has invalid PID value %r, assuming crashed",
                run_id,
                executor_pid,
            )
            _mark_run_as_crashed(run_id, status, None, logger)
            recovered_count += 1
            continue

        # Check if the executor process is still alive
        if _is_process_running(executor_pid):
            logger.info(
                "Run %s executor (PID %d) is still running (status=%s)",
                run_id,
                executor_pid,
                status,
            )
            continue

        # Process is dead -- mark as crashed
        logger.warning(
            "Run %s executor (PID %d) is dead, marking as crashed (was: %s)",
            run_id,
            executor_pid,
            status,
        )
        _mark_run_as_crashed(run_id, status, executor_pid, logger)
        recovered_count += 1

    logger.info("Crash recovery complete: %d run(s) recovered", recovered_count)
    return recovered_count


def _mark_run_as_crashed(
    run_id: str,
    original_status: str,
    executor_pid: int | None,
    logger: logging.Logger,
) -> None:
    """Mark a run as failed due to executor crash.

    Updates the run state file with crash metadata so the failure is
    traceable during debugging or post-mortem analysis.

    Args:
        run_id: Execution run identifier.
        original_status: The status the run had before being marked as
            crashed (e.g. ``"running"`` or ``"awaiting_confirmation"``).
        executor_pid: The PID of the dead executor process, or ``None``
            if no PID was recorded.
        logger: Logger instance for diagnostic messages.
    """
    from a_sdlc.executor import _update_run

    crash_reason = (
        f"Executor process (PID {executor_pid}) is no longer running"
        if executor_pid is not None
        else "Executor process PID not recorded; assumed crashed"
    )

    _update_run(
        run_id,
        status="failed",
        crash_reason=crash_reason,
        crash_detected=True,
        crash_detected_at=datetime.now().isoformat(),
        original_status=original_status,
    )

    logger.info("Run %s marked as crashed: %s", run_id, crash_reason)


def _match_cron_field(field: str, value: int) -> bool:
    """Check whether *value* matches a single cron field expression.

    Supported syntax (v1):

    * ``*`` -- matches any value.
    * ``5`` -- matches the exact integer.
    * ``1,15,30`` -- comma-separated list of integers.

    Ranges (``1-5``) and step values (``*/5``) are **not** supported
    in this initial implementation.

    Args:
        field: Cron field string (e.g. ``"*"``, ``"0"``, ``"1,15"``).
        value: Current time component to test against.

    Returns:
        ``True`` if *value* satisfies the field expression.
    """
    field = field.strip()

    if field == "*":
        return True

    # Comma-separated list (also handles single values)
    try:
        allowed = {int(v.strip()) for v in field.split(",")}
        return value in allowed
    except (ValueError, TypeError):
        return False


def _should_trigger(schedule: dict, now: datetime | None = None) -> bool:
    """Check if a schedule entry should trigger at the current minute.

    Parses the five-field cron expression from ``schedule["cron"]``
    (minute, hour, day-of-month, month, day-of-week) and matches each
    field against the current local time.

    The *now* parameter exists for testability; production callers
    should omit it so that ``datetime.now()`` is used.

    Args:
        schedule: Schedule configuration dict with at least a
            ``cron`` key whose value is a five-field cron string
            (e.g. ``"0 2 * * *"``).
        now: Override for the current time (used by tests).

    Returns:
        ``True`` if the current minute matches the cron expression,
        ``False`` otherwise (including for malformed expressions).
    """
    cron_expr = schedule.get("cron")
    if not cron_expr or not isinstance(cron_expr, str):
        return False

    parts = cron_expr.split()
    if len(parts) != 5:
        return False

    if now is None:
        now = datetime.now()

    # Cron fields: minute hour dom month dow
    cron_minute, cron_hour, cron_dom, cron_month, cron_dow = parts

    try:
        return (
            _match_cron_field(cron_minute, now.minute)
            and _match_cron_field(cron_hour, now.hour)
            and _match_cron_field(cron_dom, now.day)
            and _match_cron_field(cron_month, now.month)
            # Python weekday: Monday=0 .. Sunday=6
            # Cron weekday:   Sunday=0 .. Saturday=6
            # Convert Python → cron: (weekday + 1) % 7
            and _match_cron_field(cron_dow, (now.weekday() + 1) % 7)
        )
    except Exception:
        return False


def _resolve_sprint_id(
    sprint_id_value: str | None,
    logger: logging.Logger,
) -> str | None:
    """Resolve a ``sprint_id`` config value to an actual sprint ID.

    If the value is ``"auto"``, the current active sprint is looked up
    via storage.  Otherwise the literal value is returned.

    Args:
        sprint_id_value: Either an explicit sprint ID string,
            ``"auto"`` for automatic resolution, or ``None``.
        logger: Logger for warnings when resolution fails.

    Returns:
        A resolved sprint ID string, or ``None`` if no sprint could
        be determined.
    """
    if not sprint_id_value:
        return None

    if sprint_id_value != "auto":
        return sprint_id_value

    # "auto" -- find current active sprint
    try:
        from a_sdlc.storage import get_storage

        storage = get_storage()
        sprints = storage.list_sprints(status="active")
        if not sprints:
            logger.warning("No active sprint found for 'auto' schedule")
            return None
        return sprints[0]["id"]
    except Exception as exc:
        logger.error("Failed to resolve auto sprint_id: %s", exc)
        return None


def _execute_scheduled_run(
    schedule: dict,
    config: dict,
    logger: logging.Logger,
) -> None:
    """Execute a scheduled run by spawning an Executor subprocess.

    Reads schedule type (``sprint_run`` or ``sync``) and dispatches
    accordingly:

    * **sprint_run** -- spawns the executor module as a subprocess
      (``python -m a_sdlc.executor --mode sprint ...``).  The
      subprocess is fully detached (``start_new_session=True``) so
      it survives daemon restarts.
    * **sync** -- calls :func:`a_sdlc.server.sync.sync_sprint`
      directly (blocking, typically fast).

    Args:
        schedule: Schedule configuration dict with ``type`` and
            ``sprint_id`` keys.
        config: Full ``.sdlc/config.yaml`` contents (daemon section
            used for ``max_turns``, ``supervised``, etc.).
        logger: Logger for operational messages.
    """
    schedule_type = schedule.get("type")
    daemon_config = config.get("daemon", {})

    if schedule_type == "sprint_run":
        sprint_id = _resolve_sprint_id(schedule.get("sprint_id"), logger)
        if not sprint_id:
            logger.warning("Skipping sprint_run schedule -- could not resolve sprint_id")
            return

        logger.info("Triggering scheduled sprint run: %s", sprint_id)

        # Generate a run ID from timestamp
        run_id = f"sched-{int(time.time())}"

        # Write initial run state
        from a_sdlc.executor import _write_run

        _write_run(
            run_id,
            {
                "status": "running",
                "type": "sprint_run",
                "sprint_id": sprint_id,
                "scheduled": True,
            },
        )

        # Build subprocess command
        max_turns = daemon_config.get("max_turns", 200)
        supervised = daemon_config.get("supervised", False)

        cmd = [
            sys.executable,
            "-m",
            "a_sdlc.executor",
            "--mode",
            "sprint",
            "--sprint-id",
            sprint_id,
            "--run-id",
            run_id,
            "--max-turns",
            str(max_turns),
        ]
        if supervised:
            cmd.append("--supervised")

        # Spawn detached executor subprocess
        log_file = Path.home() / ".a-sdlc" / f"run-{run_id}.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)

        try:
            proc = subprocess.Popen(
                cmd,
                start_new_session=True,
                stdout=open(log_file, "w"),  # noqa: SIM115
                stderr=subprocess.STDOUT,
                cwd=os.getcwd(),
            )
            logger.info("Spawned executor for run %s (PID: %d)", run_id, proc.pid)
        except Exception as exc:
            logger.error("Failed to spawn executor: %s", exc)

    elif schedule_type == "sync":
        sprint_id = _resolve_sprint_id(schedule.get("sprint_id", "auto"), logger)
        if not sprint_id:
            logger.warning("Skipping sync schedule -- could not resolve sprint_id")
            return

        logger.info("Triggering scheduled sync: %s", sprint_id)

        try:
            from a_sdlc.server import sync_sprint

            result = sync_sprint(sprint_id)
            logger.info("Sync completed: %s", result)
        except Exception as exc:
            logger.error("Sync failed for %s: %s", sprint_id, exc)

    else:
        logger.warning("Unknown schedule type: %s", schedule_type)


# ---------------------------------------------------------------------------
# Main daemon event loop
# ---------------------------------------------------------------------------


def run_daemon(config: dict) -> None:
    """Main daemon event loop.

    Performs the following startup sequence:

    1. Configures rotating file logging.
    2. Registers ``SIGTERM`` and ``SIGINT`` signal handlers.
    3. Writes the PID file and registers ``atexit`` cleanup.
    4. Runs crash recovery for incomplete runs.
    5. Enters the schedule-check loop (60-second interval).

    The loop runs until ``_shutdown_requested`` is set (by signal
    handler), at which point it logs a shutdown message and removes
    the PID file.

    Args:
        config: Daemon configuration dict, typically the parsed
            contents of ``.sdlc/config.yaml``.
    """
    global _shutdown_requested
    _shutdown_requested = False

    logger = _setup_logging()

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    _write_pid()
    atexit.register(_remove_pid)

    logger.info("Daemon started (PID: %d)", os.getpid())

    # Load daemon config with defaults
    daemon_config = config.get("daemon", {})
    max_turns = daemon_config.get("max_turns", 200)
    mode = daemon_config.get("mode", "session")
    supervised = daemon_config.get("supervised", False)
    schedules = daemon_config.get("schedules") or []
    notifications = daemon_config.get("notifications") or []

    logger.info(
        "Daemon config: max_turns=%d, mode=%s, supervised=%s, schedules=%d, notifications=%d",
        max_turns,
        mode,
        supervised,
        len(schedules),
        len(notifications),
    )

    # Crash recovery (SDLC-T00123)
    _recover_incomplete_runs(logger)

    # Track last trigger time per schedule to prevent double-execution
    # within the same minute.  Key: "idx:cron_expr", value: datetime
    # truncated to the minute.
    last_triggered: dict[str, datetime] = {}

    while not _shutdown_requested:
        current_minute = datetime.now().replace(second=0, microsecond=0)

        for idx, schedule in enumerate(schedules):
            schedule_key = f"{idx}:{schedule.get('cron', '')}"

            # Skip if already triggered this minute
            if last_triggered.get(schedule_key) == current_minute:
                continue

            if _should_trigger(schedule):
                logger.info("Schedule triggered: %s", schedule)
                last_triggered[schedule_key] = current_minute

                try:
                    _execute_scheduled_run(schedule, config, logger)
                except Exception:
                    logger.error(
                        "Schedule execution failed: %s",
                        schedule,
                        exc_info=True,
                    )

        time.sleep(60)  # Check schedules every minute

    logger.info("Daemon shutting down gracefully")
    _remove_pid()


# ---------------------------------------------------------------------------
# __main__ entry point — used by CLI subprocess spawn (daemon start)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import yaml

    config_path = Path.cwd() / ".sdlc" / "config.yaml"
    config: dict = {}
    if config_path.exists():
        with open(config_path) as _f:
            config = yaml.safe_load(_f) or {}

    run_daemon(config)
