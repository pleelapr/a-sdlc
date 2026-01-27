# /sdlc:help - List Available Commands

Display all available SDLC skills with descriptions and usage examples.

## Purpose

Quick reference for all `/sdlc:*` commands without leaving Claude Code.

## Output Format

```
╭──────────────────────────────────────────────────────────╮
│                    SDLC Commands                          │
╰──────────────────────────────────────────────────────────╯

📚 Core Commands

  /sdlc:init     Initialize a-sdlc for the current project
  /sdlc:scan     Full repo scan → generate codebase artifacts
  /sdlc:update   Incremental update of stale artifacts
  /sdlc:status   Show project context and statistics

📋 PRD Management

  /sdlc:prd-generate "<desc>"  Create PRD via interactive Q&A
  /sdlc:prd-list               List all PRDs
  /sdlc:prd "<id>"             View PRD details
  /sdlc:prd-split "<id>"       Decompose PRD into tasks
  /sdlc:prd-update "<id>"      Update existing PRD

📋 Task Management

  /sdlc:task-list              List all tasks
  /sdlc:task-show <id>         Show task details
  /sdlc:task-create            Create a new task
  /sdlc:task-start <id>        Mark task as in-progress
  /sdlc:task-complete <id>     Mark task as completed

🏃 Sprint Management

  /sdlc:sprint-create          Create a new sprint
  /sdlc:sprint-list            List all sprints
  /sdlc:sprint-show <id>       Show sprint details + tasks
  /sdlc:sprint-start <id>      Activate a sprint
  /sdlc:sprint-run <id>        Execute tasks in order
  /sdlc:sprint-complete <id>   Close a sprint

🔄 External Sync (Jira/Linear)

  /sdlc:sprint-import          Import sprints from Jira/Linear
  /sdlc:sprint-link            Link local sprint to external
  /sdlc:sprint-sync            Bidirectional sync
  /sdlc:sprint-unlink          Remove external link

📖 Help

  /sdlc:help     Show this command reference
```

## MCP Tools Reference

All commands use the a-sdlc MCP server tools:

### Context & Navigation
- `mcp__asdlc__get_context()` - Get current project summary
- `mcp__asdlc__init_project(name?)` - Initialize project
- `mcp__asdlc__list_projects()` - List all projects
- `mcp__asdlc__switch_project(project_id)` - Change project

### PRD Operations
- `mcp__asdlc__list_prds()` - List PRDs
- `mcp__asdlc__get_prd(prd_id)` - Get full PRD
- `mcp__asdlc__create_prd(title, content, ...)` - Create PRD
- `mcp__asdlc__update_prd(prd_id, ...)` - Update PRD
- `mcp__asdlc__delete_prd(prd_id)` - Delete PRD

### Task Operations
- `mcp__asdlc__list_tasks(status?, sprint_id?, prd_id?)` - List tasks
- `mcp__asdlc__get_task(task_id)` - Get task details
- `mcp__asdlc__create_task(title, description, ...)` - Create task
- `mcp__asdlc__update_task(task_id, ...)` - Update task
- `mcp__asdlc__start_task(task_id)` - Mark in_progress
- `mcp__asdlc__complete_task(task_id)` - Mark completed
- `mcp__asdlc__block_task(task_id, reason?)` - Mark blocked
- `mcp__asdlc__delete_task(task_id)` - Delete task

### Sprint Operations
- `mcp__asdlc__list_sprints()` - List sprints
- `mcp__asdlc__get_sprint(sprint_id)` - Get sprint with tasks
- `mcp__asdlc__create_sprint(title, goal?)` - Create sprint
- `mcp__asdlc__start_sprint(sprint_id)` - Activate sprint
- `mcp__asdlc__complete_sprint(sprint_id)` - Complete sprint
- `mcp__asdlc__add_tasks_to_sprint(sprint_id, task_ids)` - Add tasks
- `mcp__asdlc__remove_tasks_from_sprint(sprint_id, task_ids)` - Remove tasks

## Quick Start Workflow

```
1. /sdlc:init                              # Initialize (once per project)
2. /sdlc:status                            # Check project context
3. /sdlc:prd-generate "Feature description" # Create PRD
4. /sdlc:sprint-create "Sprint 1"          # Create sprint
5. /sdlc:prd-split "prd-id" --sprint SPRINT-01  # Generate tasks
6. /sdlc:sprint-start SPRINT-01            # Activate sprint
7. /sdlc:sprint-run SPRINT-01              # Execute tasks
```

## Data Storage

- All data stored in user-level SQLite: `~/.a-sdlc/data.db`
- No files created in repository (except optional artifacts)
- Data persists across Claude Code sessions

## CLI Commands

```bash
a-sdlc install      # Install skill templates + configure MCP server
a-sdlc serve        # Start MCP server (auto-started by Claude Code)
a-sdlc doctor       # Run system diagnostics
a-sdlc tasks        # CLI task management
a-sdlc ui           # Start web UI dashboard
```

## Notes

- All commands work from the project root directory
- Run `/sdlc:init` before using other commands
- Use `/sdlc:status` to see project overview