"""Notification hook system for execution runs.

Supports two hook types configured in ``.sdlc/config.yaml`` under
``daemon.notifications``:

- **file**: Write a markdown summary to a path (supports ``{run_id}``
  placeholder and ``~`` expansion).
- **webhook**: POST a JSON payload to a URL, filtered by event type.
  Requires the optional ``httpx`` dependency.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore[assignment]  # Optional dependency for webhooks

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_notification_hooks(
    run_id: str,
    outcome: dict[str, Any],
    config: dict[str, Any],
    hook_logger: logging.Logger | None = None,
) -> None:
    """Execute configured notification hooks after run completion.

    Reads notification config from ``config["daemon"]["notifications"]``
    and executes each hook based on its type (``file`` or ``webhook``).

    Each hook is executed independently -- a failure in one hook does not
    prevent subsequent hooks from running.

    Args:
        run_id: Execution run identifier (e.g. ``SDLC-R0001``).
        outcome: Run outcome dict with ``status``, ``summary``, counts, etc.
        config: Full daemon configuration dict (the ``daemon:`` section
            from ``.sdlc/config.yaml``, as returned by
            :func:`~a_sdlc.executor.load_daemon_config`).
        hook_logger: Optional logger override.  Defaults to the module
            logger.
    """
    log = hook_logger or logger

    notifications: list[dict[str, Any]] = config.get("notifications", [])

    if not notifications:
        return  # No hooks configured

    log.info("Running %d notification hook(s) for %s", len(notifications), run_id)

    for hook in notifications:
        hook_type = hook.get("type")

        try:
            if hook_type == "file":
                _run_file_hook(run_id, outcome, hook, log)
            elif hook_type == "webhook":
                _run_webhook_hook(run_id, outcome, hook, log)
            else:
                log.warning("Unknown notification hook type: %s", hook_type)
        except Exception:
            log.error(
                "Notification hook failed (type=%s)",
                hook_type,
                exc_info=True,
            )


# ---------------------------------------------------------------------------
# File hook
# ---------------------------------------------------------------------------


def _run_file_hook(
    run_id: str,
    outcome: dict[str, Any],
    hook: dict[str, Any],
    log: logging.Logger,
) -> None:
    """Write run summary to a file.

    Supports ``{run_id}`` placeholder in the ``path`` field and ``~``
    expansion for home directory paths.  Creates parent directories if
    they do not exist.

    Args:
        run_id: Execution run identifier.
        outcome: Run outcome dict.
        hook: Hook config dict with a ``path`` field.
        log: Logger instance.
    """
    path_template = hook.get("path")
    if not path_template:
        log.warning("File hook missing 'path' field")
        return

    # Replace placeholders
    path_str = path_template.replace("{run_id}", run_id)
    path = Path(path_str).expanduser()

    # Create parent directories
    path.parent.mkdir(parents=True, exist_ok=True)

    # Generate summary content
    summary = format_run_summary(run_id, outcome)

    # Write to file
    path.write_text(summary)

    log.info("File notification written: %s", path)


# ---------------------------------------------------------------------------
# Webhook hook
# ---------------------------------------------------------------------------


def _run_webhook_hook(
    run_id: str,
    outcome: dict[str, Any],
    hook: dict[str, Any],
    log: logging.Logger,
) -> None:
    """Send run summary to a webhook URL via HTTP POST.

    Supports event filtering via the ``events`` field in the hook
    config.  Requires the ``httpx`` library; logs a warning and skips
    if ``httpx`` is not installed.

    Args:
        run_id: Execution run identifier.
        outcome: Run outcome dict.
        hook: Hook config dict with ``url`` and optional ``events`` fields.
        log: Logger instance.
    """
    if httpx is None:
        log.warning(
            "httpx not installed, skipping webhook notification. "
            "Install with: pip install httpx"
        )
        return

    url = hook.get("url")
    if not url:
        log.warning("Webhook hook missing 'url' field")
        return

    # Check event filter
    events = hook.get("events", ["run_completed", "run_failed"])

    # Determine event type from outcome
    status = outcome.get("status", "unknown")
    event = "run_completed" if status == "completed" else "run_failed"

    if event not in events:
        log.debug("Webhook skipped (event=%s not in %s)", event, events)
        return

    # Build payload
    payload: dict[str, Any] = {
        "run_id": run_id,
        "event": event,
        "status": status,
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "summary": outcome.get("summary", ""),
        "entity_type": outcome.get("entity_type"),
        "entity_id": outcome.get("entity_id"),
        "completed_count": outcome.get("completed", 0),
        "failed_count": outcome.get("failed", 0),
    }

    # Send POST request
    try:
        response = httpx.post(url, json=payload, timeout=10.0)
        response.raise_for_status()
        log.info(
            "Webhook notification sent: %s (status=%d)",
            url,
            response.status_code,
        )
    except httpx.HTTPError as exc:
        log.error("Webhook request failed: %s", exc)


# ---------------------------------------------------------------------------
# Summary formatter
# ---------------------------------------------------------------------------


def format_run_summary(run_id: str, outcome: dict[str, Any]) -> str:
    """Format a run outcome as a markdown summary.

    Args:
        run_id: Execution run identifier.
        outcome: Run outcome dict.

    Returns:
        Markdown-formatted summary string.
    """
    status = outcome.get("status", "unknown")
    entity_type = outcome.get("entity_type", "unknown")
    entity_id = outcome.get("entity_id", "unknown")
    completed = outcome.get("completed", 0)
    failed = outcome.get("failed", 0)
    skipped = outcome.get("skipped", 0)
    summary = outcome.get("summary", "No summary available")

    timestamp = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    return (
        f"# Execution Run Summary\n"
        f"\n"
        f"**Run ID**: {run_id}\n"
        f"**Status**: {status}\n"
        f"**Entity**: {entity_type} `{entity_id}`\n"
        f"**Timestamp**: {timestamp}\n"
        f"\n"
        f"## Results\n"
        f"\n"
        f"- Completed: {completed}\n"
        f"- Failed: {failed}\n"
        f"- Skipped: {skipped}\n"
        f"\n"
        f"## Summary\n"
        f"\n"
        f"{summary}\n"
    )
