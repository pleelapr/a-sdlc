#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "langfuse>=3.0",
# ]
# ///
"""
Sends Claude Code traces to Langfuse after each response.

Based on the official Langfuse Claude Code integration hook:
  https://langfuse.com/integrations/other/claude-code

Adaptations for a-sdlc:
  - uv run --script with inline deps (no separate pip install)
  - load_env_from_settings() bridges settings.json env to subprocess
  - stdin-based session_id + transcript_path (more reliable than scanning)
  - State/logs stored in ~/.a-sdlc/monitoring/

Data model (matches official pattern):
  Session  = groups all turns via session_id
  Trace    = one per turn (user -> assistant)
  Generation = one per turn (Claude LLM call)
  Span     = one per tool call with matched result
"""

import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Paths
STATE_FILE = Path.home() / ".a-sdlc" / "monitoring" / ".hook-state" / "langfuse_state.json"
DEBUG_LOG = Path.home() / ".a-sdlc" / "monitoring" / "hook-debug.log"
SETTINGS_PATH = Path.home() / ".claude" / "settings.json"


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def debug_log(message: str) -> None:
    """Append a timestamped debug message to the hook log file."""
    try:
        DEBUG_LOG.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        with open(DEBUG_LOG, "a") as f:
            f.write(f"[{timestamp}] {message}\n")
    except Exception:
        pass  # debug logging must never block the hook


# ---------------------------------------------------------------------------
# Environment bridge
# ---------------------------------------------------------------------------

def load_env_from_settings():
    """Load LANGFUSE_* env vars from ~/.claude/settings.json if not already set.

    Claude Code's settings.json 'environment' section is not propagated to
    hook subprocesses. This function bridges the gap by reading that config
    directly and injecting any missing LANGFUSE_* vars into os.environ.
    """
    if not SETTINGS_PATH.exists():
        return
    try:
        settings = json.loads(SETTINGS_PATH.read_text())
        env_section = settings.get("environment", {})
        loaded = []
        for key, value in env_section.items():
            if key.startswith("LANGFUSE_") and not os.environ.get(key):
                os.environ[key] = str(value)
                loaded.append(key)
        if loaded:
            debug_log(f"Loaded from settings.json: {loaded}")
    except (json.JSONDecodeError, OSError) as e:
        debug_log(f"Failed to read settings.json: {e}")


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------

def load_state() -> dict:
    """Load the state file containing session tracking info."""
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(state: dict) -> None:
    """Save the state file."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


# ---------------------------------------------------------------------------
# Message helpers (from official Langfuse hook)
# ---------------------------------------------------------------------------

def get_content(msg: dict) -> Any:
    """Extract content from a message."""
    if isinstance(msg, dict):
        if "message" in msg:
            return msg["message"].get("content")
        return msg.get("content")
    return None


def is_tool_result(msg: dict) -> bool:
    """Check if a message contains tool results."""
    content = get_content(msg)
    if isinstance(content, list):
        return any(
            isinstance(item, dict) and item.get("type") == "tool_result"
            for item in content
        )
    return False


def get_tool_calls(msg: dict) -> list:
    """Extract tool use blocks from a message."""
    content = get_content(msg)
    if isinstance(content, list):
        return [
            item for item in content
            if isinstance(item, dict) and item.get("type") == "tool_use"
        ]
    return []


def get_text_content(msg: dict) -> str:
    """Extract text content from a message."""
    content = get_content(msg)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text_parts.append(item.get("text", ""))
            elif isinstance(item, str):
                text_parts.append(item)
        return "\n".join(text_parts)
    return ""


def merge_assistant_parts(parts: list) -> dict:
    """Merge multiple assistant message parts into one."""
    if not parts:
        return {}

    merged_content = []
    for part in parts:
        content = get_content(part)
        if isinstance(content, list):
            merged_content.extend(content)
        elif content:
            merged_content.append({"type": "text", "text": str(content)})

    # Use the structure from the first part
    result = parts[0].copy()
    if "message" in result:
        result["message"] = result["message"].copy()
        result["message"]["content"] = merged_content
    else:
        result["content"] = merged_content

    return result


# ---------------------------------------------------------------------------
# Trace creation (from official Langfuse hook)
# ---------------------------------------------------------------------------

def create_trace(
    langfuse,
    session_id: str,
    turn_num: int,
    user_msg: dict,
    assistant_msgs: list,
    tool_results: list,
) -> None:
    """Create a Langfuse trace for a single turn using the SDK v3 context-manager API."""
    user_text = get_text_content(user_msg)

    # Extract final assistant text
    final_output = ""
    if assistant_msgs:
        final_output = get_text_content(assistant_msgs[-1])

    # Get model info from first assistant message
    model = "claude"
    if assistant_msgs and isinstance(assistant_msgs[0], dict) and "message" in assistant_msgs[0]:
        model = assistant_msgs[0]["message"].get("model", "claude")

    # Collect all tool calls and match results
    all_tool_calls = []
    for assistant_msg in assistant_msgs:
        tool_calls = get_tool_calls(assistant_msg)
        for tool_call in tool_calls:
            tool_name = tool_call.get("name", "unknown")
            tool_input = tool_call.get("input", {})
            tool_id = tool_call.get("id", "")

            # Find matching tool result by tool_use_id
            tool_output = None
            for tr in tool_results:
                tr_content = get_content(tr)
                if isinstance(tr_content, list):
                    for item in tr_content:
                        if isinstance(item, dict) and item.get("tool_use_id") == tool_id:
                            tool_output = item.get("content")
                            break

            all_tool_calls.append({
                "name": tool_name,
                "input": tool_input,
                "output": tool_output,
                "id": tool_id,
            })

    # Create trace with nested observations
    with langfuse.start_as_current_span(
        name=f"Turn {turn_num}",
        input={"role": "user", "content": user_text},
        metadata={
            "source": "claude-code",
            "turn_number": turn_num,
            "session_id": session_id,
        },
    ) as trace_span:
        # Update the parent trace with session grouping
        langfuse.update_current_trace(
            session_id=session_id,
            name="claude-code-session",
        )

        # One generation for the LLM response
        with langfuse.start_as_current_observation(
            name="Claude Response",
            as_type="generation",
            model=model,
            input={"role": "user", "content": user_text},
            output={"role": "assistant", "content": final_output},
            metadata={"tool_count": len(all_tool_calls)},
        ):
            pass  # auto-completed on context exit

        # Spans for each tool call with matched results
        for tool_call in all_tool_calls:
            with langfuse.start_as_current_span(
                name=f"Tool: {tool_call['name']}",
                input=tool_call["input"],
                metadata={
                    "tool_name": tool_call["name"],
                    "tool_id": tool_call["id"],
                },
            ) as tool_span:
                tool_span.update(output=tool_call["output"])

        # Update trace span with final output
        trace_span.update(output={"role": "assistant", "content": final_output})

    debug_log(f"Created trace for turn {turn_num} ({len(all_tool_calls)} tools)")


# ---------------------------------------------------------------------------
# Transcript processing (from official Langfuse hook)
# ---------------------------------------------------------------------------

def process_transcript(langfuse, session_id: str, transcript_path: str, state: dict) -> int:
    """Process a transcript file and create traces for new turns."""
    transcript_file = Path(transcript_path)

    # Get previous state for this session
    session_state = state.get(session_id, {})
    last_line = session_state.get("last_line", 0)
    turn_count = session_state.get("turn_count", 0)

    # Read transcript
    lines = transcript_file.read_text().strip().split("\n")
    total_lines = len(lines)

    if last_line >= total_lines:
        debug_log(f"No new lines to process (last: {last_line}, total: {total_lines})")
        return 0

    # Parse new messages
    new_messages = []
    for i in range(last_line, total_lines):
        try:
            msg = json.loads(lines[i])
            new_messages.append(msg)
        except json.JSONDecodeError:
            continue

    if not new_messages:
        return 0

    debug_log(f"Processing {len(new_messages)} new messages (lines {last_line}->{total_lines})")

    # Group messages into turns (user -> assistant(s) -> tool_results)
    turns = 0
    current_user = None
    current_assistants = []
    current_assistant_parts = []
    current_msg_id = None
    current_tool_results = []

    for msg in new_messages:
        role = msg.get("type") or (msg.get("message", {}).get("role"))

        if role == "user":
            # Check if this is a tool result
            if is_tool_result(msg):
                current_tool_results.append(msg)
                continue

            # New user message — finalize previous assistant parts
            if current_msg_id and current_assistant_parts:
                merged = merge_assistant_parts(current_assistant_parts)
                current_assistants.append(merged)
                current_assistant_parts = []
                current_msg_id = None

            # Emit previous turn
            if current_user and current_assistants:
                turns += 1
                turn_num = turn_count + turns
                create_trace(langfuse, session_id, turn_num, current_user, current_assistants, current_tool_results)

            # Start new turn
            current_user = msg
            current_assistants = []
            current_assistant_parts = []
            current_msg_id = None
            current_tool_results = []

        elif role == "assistant":
            msg_id = None
            if isinstance(msg, dict) and "message" in msg:
                msg_id = msg["message"].get("id")

            if not msg_id:
                # No message ID, treat as continuation
                current_assistant_parts.append(msg)
            elif msg_id == current_msg_id:
                # Same message ID, add to current parts
                current_assistant_parts.append(msg)
            else:
                # New message ID — finalize previous message
                if current_msg_id and current_assistant_parts:
                    merged = merge_assistant_parts(current_assistant_parts)
                    current_assistants.append(merged)

                # Start new assistant message
                current_msg_id = msg_id
                current_assistant_parts = [msg]

    # Process final turn
    if current_msg_id and current_assistant_parts:
        merged = merge_assistant_parts(current_assistant_parts)
        current_assistants.append(merged)

    if current_user and current_assistants:
        turns += 1
        turn_num = turn_count + turns
        create_trace(langfuse, session_id, turn_num, current_user, current_assistants, current_tool_results)

    # Update state
    state[session_id] = {
        "last_line": total_lines,
        "turn_count": turn_count + turns,
        "updated": datetime.now(timezone.utc).isoformat(),
    }
    save_state(state)

    debug_log(f"Processed {turns} turns (total lines: {total_lines})")
    return turns


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    debug_log("Hook invoked")

    # Bridge settings.json environment to subprocess
    load_env_from_settings()

    # Opt-in: skip if Langfuse is not configured
    public_key = os.environ.get("LANGFUSE_PUBLIC_KEY")
    secret_key = os.environ.get("LANGFUSE_SECRET_KEY")
    host = os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com")

    if not secret_key:
        debug_log("EXIT: LANGFUSE_SECRET_KEY not set (checked env + settings.json)")
        sys.exit(0)

    debug_log(
        f"Config: secret_key=...{secret_key[-8:]}, "
        f"public_key={public_key or '<not set>'}, "
        f"host={host}"
    )

    # Read session_id and transcript_path from stdin (provided by Claude Code hook)
    try:
        input_data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError) as e:
        debug_log(f"EXIT: stdin JSON parse failed: {e}")
        sys.exit(0)

    session_id = input_data.get("session_id", "")
    transcript_path = input_data.get("transcript_path", "")

    debug_log(f"session_id={session_id}, transcript_path={transcript_path}")

    if not transcript_path or not Path(transcript_path).exists():
        debug_log("EXIT: transcript_path missing or not found")
        sys.exit(0)

    if not session_id:
        debug_log("EXIT: session_id missing")
        sys.exit(0)

    # Lazy import so the dependency doesn't block when unconfigured
    from langfuse import Langfuse

    try:
        langfuse = Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            host=host,
        )
    except Exception as e:
        debug_log(f"EXIT: Failed to initialize Langfuse client: {e}")
        sys.exit(0)

    # Load state and process transcript
    state = load_state()

    try:
        turns = process_transcript(langfuse, session_id, transcript_path, state)
        langfuse.flush()
        debug_log(f"Flushed {turns} turns successfully")
    except Exception as e:
        debug_log(f"Error processing transcript: {e}\n{traceback.format_exc()}")
    finally:
        langfuse.shutdown()

    debug_log("Hook completed successfully")
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        debug_log(f"FATAL EXCEPTION:\n{traceback.format_exc()}")
        # Never block Claude Code on hook failure
        sys.exit(0)
