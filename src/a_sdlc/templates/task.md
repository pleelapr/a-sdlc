# /sdlc:task - Task Management

Manage implementation tasks derived from PRDs.

## Architecture

```
Sprint (SPRINT-01)
  └── PRD (feature-auth)
        ├── TASK-001
        ├── TASK-002
        └── TASK-003
```

**Key concept**: Tasks belong to PRDs. Tasks inherit sprint membership through their parent PRD. You cannot assign a task directly to a sprint.

## Available Subcommands

| Command | Description |
|---------|-------------|
| `/sdlc:task-list` | List all tasks |
| `/sdlc:task-show <id>` | Show task details |
| `/sdlc:task-start <id>` | Mark task as in-progress |
| `/sdlc:task-complete <id>` | Mark task as completed |
| `/sdlc:task-create` | Manually create a task |

## Task Statuses

| Status | Description |
|--------|-------------|
| `pending` | Not started |
| `in_progress` | Currently being worked on |
| `completed` | Finished |
| `blocked` | Cannot proceed (use `update_task(status="blocked")`) |

## Quick Start

1. **Generate tasks from PRD**: `/sdlc:prd-split "feature-name"`
2. **View tasks**: `/sdlc:task-list`
3. **Start working**: `/sdlc:task-start TASK-001`
4. **Complete task**: `/sdlc:task-complete TASK-001`

## MCP Tools

### List Tasks

```
mcp__asdlc__list_tasks()                          # All tasks
mcp__asdlc__list_tasks(status="pending")          # By status
mcp__asdlc__list_tasks(prd_id="feature-auth")     # By PRD
```

### Get Task Details

```
mcp__asdlc__get_task(task_id="TASK-001")
```

### Create Task

```
result = mcp__asdlc__create_task(
    title="Implement login",
    prd_id="feature-auth",        # Required for sprint inheritance
    priority="high",              # low, medium, high, critical
    component="auth-service"
)
# Then write task content to the returned file_path:
Write(file_path=result["file_path"], content="<task description markdown>")
```

### Update Task Status

```
mcp__asdlc__update_task(task_id="TASK-001", status="in_progress")   # → in_progress
mcp__asdlc__update_task(task_id="TASK-001", status="completed")    # → completed
mcp__asdlc__update_task(task_id="TASK-001", status="blocked")      # → blocked
```

## Sprint Integration

Tasks belong to sprints **through their parent PRD**:

1. Create or get a PRD
2. Assign PRD to sprint: `mcp__asdlc__manage_sprint_prds(action="add", prd_id="...", sprint_id="...")`
3. Create tasks with that PRD: `mcp__asdlc__create_task(..., prd_id="...")`
4. Tasks are now part of the sprint

To list tasks in a sprint, get the sprint's PRDs first:
```
mcp__asdlc__get_sprint_prds(sprint_id="SPRINT-01")
# Then list tasks for each PRD
mcp__asdlc__list_tasks(prd_id="<prd_id>")
```

## Storage

All task data is stored in the SQLite database at `~/.a-sdlc/data.db`. No file-based storage is used.

## Notes

- Tasks are auto-numbered (TASK-001, TASK-002, etc.)
- Completing all tasks for a PRD should trigger updating PRD status to "completed"
- Use `update_task(status="blocked")` when a task cannot proceed
- Task priorities: low, medium, high, critical

## Related Commands

- `/sdlc:prd-split` - Generate tasks from a PRD
- `/sdlc:sprint-run` - Execute sprint tasks in parallel
