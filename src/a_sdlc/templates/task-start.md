# /sdlc:task-start

## Purpose

Mark a task as in-progress and begin working on it.

## Usage

Use the MCP tool to start a task:

```
mcp__asdlc__start_task(task_id="TASK-001")
```

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `task_id` | Yes | ID of the task to start |

## Execution

1. Validates task exists and is pending
2. Updates task status to `in_progress`
3. Sets `updated_at` timestamp
4. Returns updated task details

## Output

```json
{
  "status": "updated",
  "message": "Task updated: TASK-001",
  "task": {
    "id": "TASK-001",
    "title": "Implement authentication",
    "status": "in_progress",
    "description": "Add JWT-based auth...",
    "priority": "high",
    "component": "auth-service"
  }
}
```

## Display Format

After starting the task, check for relevant codebase context:

```
context = mcp__asdlc__get_context()
```

If `context.artifacts.scan_status` is `"complete"` or `"partial"` AND the task has a `component`:

```
Read: .sdlc/artifacts/architecture.md
```

Extract the section relevant to the task's component (its description, key files, dependencies) and display it alongside the task details.

```
Task Started: TASK-001

"Implement authentication"

Priority: High
Component: auth-service
Sprint: SPRINT-01

Description:
Add JWT-based authentication to the API endpoints.

Component Context (from architecture.md):
  auth-service: Handles authentication and authorization
  Key files: src/auth/handlers.py, src/auth/models.py
  Dependencies: database, config-service

Good luck! Run /sdlc:task-complete TASK-001 when done.
```

If no artifacts are available or the task has no component, display the standard format without the component context section.

## Examples

```
/sdlc:task-start TASK-001
/sdlc:task-start TASK-002
```

## Related Commands

- `/sdlc:task-complete` - Mark task as completed
- `/sdlc:task-list` - View all tasks
- `/sdlc:task` - Get task details