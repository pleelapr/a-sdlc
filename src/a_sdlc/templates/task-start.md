# /sdlc:task-start

## Purpose

Mark a task as in-progress and set it as the active task.

## Execution

1. Validate task exists and is pending
2. Check dependencies are completed
3. Update task status to `in_progress`
4. Store as active task in Serena memory: `sdlc_active_task`

## Output

```
Task Started: TASK-001

"Implement FR-001 in auth-service"

Files to modify:
  - src/auth/handlers.py
  - src/auth/models.py

Implementation steps:
  1. Add authentication middleware
  2. Create user validation logic
  3. Implement token generation

Good luck! Run /sdlc:task-complete TASK-001 when done.
```
