# /sdlc:task-complete

## Purpose

Mark a task as completed.

## Usage

Use the MCP tool to complete a task:

```
mcp__asdlc__complete_task(task_id="TASK-001")
```

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `task_id` | Yes | ID of the task to complete |

## Execution

1. Validates task exists
2. Updates status to `completed`
3. Sets `completed_at` timestamp
4. Returns updated task details
5. **Check if all PRD tasks are completed** (see below)

## Output

```json
{
  "status": "updated",
  "message": "Task updated: TASK-001",
  "task": {
    "id": "TASK-001",
    "title": "Implement authentication",
    "status": "completed",
    "completed_at": "2025-01-26T15:30:00Z"
  }
}
```

## Display Format

```
Task Completed: TASK-001 ✅

"Implement authentication"

Status: Completed
Completed at: 2025-01-26 15:30

Great work! 🎉
```

## Check PRD Completion

After completing a task, check if all tasks for the parent PRD are now completed:

1. Get the task's `prd_id` from the completed task response
2. If `prd_id` exists, list all tasks for that PRD:
   ```
   mcp__asdlc__list_tasks(prd_id="<prd_id>")
   ```
3. Check if ALL tasks have status "completed"
4. If yes, update PRD status to "completed":
   ```
   mcp__asdlc__update_prd(prd_id="<prd_id>", status="completed")
   ```
5. Notify user: "All tasks for PRD <prd_id> are complete. PRD marked as completed."

**Example check:**
```
Tasks for PRD feature-auth:
  TASK-001: completed ✅
  TASK-002: completed ✅
  TASK-003: completed ✅  ← just completed

All tasks done → Update PRD status to "completed"
```

## Suggest Next Task

After completing, optionally suggest the next task:

```
mcp__asdlc__list_tasks(status="pending")
```

```
Next suggested tasks:
  TASK-002  [High] Add rate limiting         [SPRINT-01]
  TASK-003  [High] Implement user profile    [SPRINT-01]
```

## Examples

```
/sdlc:task-complete TASK-001
/sdlc:task-complete TASK-002
```

## Related Commands

- `/sdlc:task-start` - Start a task
- `/sdlc:task-list` - View all tasks
- `/sdlc:sprint-run` - Continue sprint execution