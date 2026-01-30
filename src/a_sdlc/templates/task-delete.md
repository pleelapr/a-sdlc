# /sdlc:task-delete

## Purpose

Delete a task permanently.

## Syntax

/sdlc:task-delete <task-id>

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `task-id` | Yes | Task ID to delete (e.g., PROJ-T00001) |

## Execution

```
mcp__asdlc__delete_task(task_id="<task-id>")
```

## Behavior

- Deletes task from database
- Removes content file from ~/.a-sdlc/content/{project}/tasks/
- Does NOT affect parent PRD

## Output

```
Task Deleted: PROJ-T00001 🗑️
"Implement authentication"
```

## Related Commands

- `/sdlc:task-list` - View all tasks
- `/sdlc:task-show` - View task before deleting
