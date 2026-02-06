#!/usr/bin/env bash
# block-source-edits.sh - PreToolUse hook for planning-only /sdlc:* commands
#
# Blocks source code modifications during planning-only skills.
# Allows writes to ~/.a-sdlc/ and .sdlc/ paths (a-sdlc content files).
#
# Usage: block-source-edits.sh <template-name>
# Reads: JSON from stdin with { tool_name, tool_input }
# Exit codes: 0 = allow, 2 = block (with stderr message)

set -euo pipefail

TEMPLATE_NAME="${1:-unknown}"

# Read JSON input from stdin
INPUT=$(cat)

TOOL_NAME=$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('tool_name',''))" 2>/dev/null || echo "")

# Guidance messages per template
get_guidance() {
  case "$1" in
    prd-generate)
      echo "Your job: Ask clarifying questions, generate PRD markdown, get user approval, then call mcp__asdlc__create_prd() to save. Do NOT split into tasks or write code" ;;
    prd-split)
      echo "Your job: Launch Explore/Plan agents, design task breakdown, get user approval, Write task files to ~/.a-sdlc/ only, then call mcp__asdlc__split_prd(). Do NOT implement tasks or edit source code" ;;
    prd-investigate)
      echo "Your job: Load PRD, read .sdlc/artifacts/, verify components exist via Read/Grep/Glob, check template compliance, present report, then optionally call mcp__asdlc__update_prd(). Do NOT edit source code" ;;
    prd-import)
      echo "Your job: Validate Jira integration, call mcp__asdlc__create_prd(), mcp__asdlc__link_prd(), mcp__asdlc__sync_prd_from(), then ask user about sprint assignment. Do NOT edit source code" ;;
    investigate)
      echo "Your job: Parse error signals, search SDLC history via MCP tools, analyze codebase with Read/Grep/Glob, search web, synthesize root cause report. Optionally create PRD with --create-prd flag. Do NOT fix code or edit files" ;;
    task-create)
      echo "Your job: Get context via mcp__asdlc__get_context(), gather task details interactively, generate task markdown, Write file to ~/.a-sdlc/ only, then call mcp__asdlc__create_task() to save. Do NOT implement the task or edit source code" ;;
    *)
      echo "This command does not modify source code" ;;
  esac
}

# For Bash: allow for investigation templates with reminder, block for others
if [ "$TOOL_NAME" = "Bash" ]; then
  if [ "$TEMPLATE_NAME" = "investigate" ] || [ "$TEMPLATE_NAME" = "prd-investigate" ]; then
    echo "REMINDER: Bash allowed for read-only investigation only. Do NOT modify, create, or delete any files. Do NOT run git commit, npm install, pip install, or any command that changes project state." >&2
    exit 0
  fi
  GUIDANCE=$(get_guidance "$TEMPLATE_NAME")
  echo "BLOCKED: /sdlc:${TEMPLATE_NAME} does not modify source code. ${GUIDANCE}. Stop and wait for user's next command." >&2
  exit 2
fi

# For Edit/Write/MultiEdit/NotebookEdit: check file path
if [ "$TOOL_NAME" = "Edit" ] || [ "$TOOL_NAME" = "Write" ] || [ "$TOOL_NAME" = "MultiEdit" ] || [ "$TOOL_NAME" = "NotebookEdit" ]; then
  FILE_PATH=$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('tool_input',{}).get('file_path',''))" 2>/dev/null || echo "")

  # Allow writes to ~/.a-sdlc/ paths (a-sdlc content files)
  if echo "$FILE_PATH" | grep -q '\.a-sdlc/'; then
    exit 0
  fi

  # Allow writes to .sdlc/ paths (project artifacts)
  if echo "$FILE_PATH" | grep -q '\.sdlc/'; then
    exit 0
  fi

  # Block everything else
  GUIDANCE=$(get_guidance "$TEMPLATE_NAME")
  echo "BLOCKED: /sdlc:${TEMPLATE_NAME} does not modify source code. ${GUIDANCE}. Stop and wait for user's next command." >&2
  exit 2
fi

# Everything else (Read, Grep, Glob, Task, MCP tools): allow
exit 0
