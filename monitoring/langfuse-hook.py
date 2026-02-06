#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "langfuse>=3.0",
# ]
# ///
"""
Claude Code Stop hook – sends per-turn observations to Langfuse,
accumulated into a single trace per session.

Fires after each Claude response (the Stop hook triggers on every
back-and-forth, not just session end). Uses byte-offset state tracking
so only NEW transcript entries are sent each time.

All turns within a session are nested under ONE trace (deterministic
trace_id derived from session_id), giving a complete conversation view
in the Langfuse UI.

Uses the Langfuse SDK v3 API (context-manager based).

Opt-in: exits silently if LANGFUSE_SECRET_KEY is not set.

Usage in ~/.claude/settings.json:
  "Stop": [{
    "matcher": "",
    "hooks": [{
      "type": "command",
      "command": "uv run ~/.a-sdlc/monitoring/langfuse-hook.py"
    }]
  }]
"""

import hashlib
import json
import os
import sys
import time
from pathlib import Path

STATE_DIR = Path.home() / ".a-sdlc" / "monitoring" / ".hook-state"


def get_state_path(session_id: str) -> Path:
    """Get state file path for a session."""
    safe_name = hashlib.md5(session_id.encode()).hexdigest()[:16]
    return STATE_DIR / f"{safe_name}.json"


def load_state(session_id: str) -> dict:
    """Load last-processed state for a session."""
    state_path = get_state_path(session_id)
    if state_path.exists():
        try:
            return json.loads(state_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"offset": 0, "turn_index": 0, "turn_number": 0}


def save_state(session_id: str, offset: int, turn_index: int, turn_number: int):
    """Save processing state for a session."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_path = get_state_path(session_id)
    state_path.write_text(json.dumps({
        "offset": offset,
        "turn_index": turn_index,
        "turn_number": turn_number,
    }))


def cleanup_old_states(max_age_hours: int = 24):
    """Remove state files older than max_age_hours."""
    if not STATE_DIR.exists():
        return
    cutoff = time.time() - (max_age_hours * 3600)
    for f in STATE_DIR.iterdir():
        try:
            if f.suffix == ".json" and f.stat().st_mtime < cutoff:
                f.unlink(missing_ok=True)
        except OSError:
            continue


def main():
    # Opt-in: skip if Langfuse is not configured
    if not os.environ.get("LANGFUSE_SECRET_KEY"):
        sys.exit(0)

    try:
        input_data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    session_id = input_data.get("session_id", "")
    transcript_path = input_data.get("transcript_path", "")

    if not transcript_path or not Path(transcript_path).exists():
        sys.exit(0)

    # Load state for incremental processing
    state = load_state(session_id)
    last_offset = state["offset"]
    turn_index = state["turn_index"]
    turn_number = state.get("turn_number", 0)

    # Read only new entries since last offset
    new_entries = []
    with open(transcript_path, "r") as f:
        f.seek(last_offset)
        for line in f:
            line_stripped = line.strip()
            if not line_stripped:
                continue
            try:
                new_entries.append(json.loads(line_stripped))
            except json.JSONDecodeError:
                continue
        new_offset = f.tell()

    # Nothing new to process
    if not new_entries or new_offset == last_offset:
        sys.exit(0)

    # Lazy import so the dependency doesn't block when unconfigured
    from langfuse import get_client

    langfuse = get_client()

    # Deterministic trace_id from session_id — every hook invocation for this
    # session appends to the SAME trace, giving one accumulated conversation view.
    trace_id = langfuse.create_trace_id(seed=session_id)

    # Increment turn number for this invocation
    turn_number += 1

    # Create a turn span attached to the session-level trace
    with langfuse.start_as_current_observation(
        as_type="span",
        name=f"turn-{turn_number}",
        trace_context={"trace_id": trace_id},
        metadata={"turn_offset": last_offset},
    ):
        # Set session_id on the trace (idempotent — safe to call every turn)
        langfuse.update_current_trace(
            session_id=session_id,
            name="claude-code-session",
            metadata={
                "cwd": input_data.get("cwd", ""),
                "permission_mode": input_data.get("permission_mode", ""),
            },
        )

        for entry in new_entries:
            msg = entry.get("message")
            if not msg:
                continue

            role = msg.get("role", "")
            content = msg.get("content", "")
            model = msg.get("model", "")
            entry_type = entry.get("type", "")

            # Flatten content if it's a list of blocks
            if isinstance(content, list):
                # Check for tool_use blocks → create spans
                tool_blocks = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_use"]
                text_blocks = [
                    b.get("text", "") for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                ]
                text_content = "\n".join(t for t in text_blocks if t)

                if role == "assistant" and text_content:
                    turn_index += 1
                    with langfuse.start_as_current_observation(
                        as_type="generation",
                        name=f"assistant-turn-{turn_index}",
                        model=model or "claude-opus-4-6",
                        output=text_content,
                        metadata={"entry_type": entry_type},
                    ):
                        pass

                for tb in tool_blocks:
                    with langfuse.start_as_current_observation(
                        as_type="span",
                        name=f"tool:{tb.get('name', 'unknown')}",
                        input=tb.get("input"),
                        metadata={"tool_use_id": tb.get("id", "")},
                    ):
                        pass

            elif isinstance(content, str) and content:
                if role == "user":
                    turn_index += 1
                    with langfuse.start_as_current_observation(
                        as_type="generation",
                        name=f"user-turn-{turn_index}",
                        input=content,
                        metadata={"entry_type": entry_type},
                    ):
                        pass
                elif role == "assistant":
                    turn_index += 1
                    with langfuse.start_as_current_observation(
                        as_type="generation",
                        name=f"assistant-turn-{turn_index}",
                        model=model or "claude-opus-4-6",
                        output=content,
                        metadata={"entry_type": entry_type},
                    ):
                        pass

    # Ensure all events are sent
    langfuse.flush()

    # Save state for next invocation
    save_state(session_id, new_offset, turn_index, turn_number)

    # Periodically clean up old state files
    cleanup_old_states()

    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Never block Claude Code on hook failure
        sys.exit(0)
