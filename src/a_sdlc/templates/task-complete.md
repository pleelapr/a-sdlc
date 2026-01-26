# /sdlc:task-complete

## Purpose

Mark a task as completed and archive it.

## Execution

1. Validate task exists and is in-progress
2. Update status to `completed`
3. Set `completed_at` timestamp
4. Move from `active/` to `completed/`
5. Sync to external system if configured
6. Clear active task from memory

## Output

```
Task Completed: TASK-001 ✓

"Implement FR-001 in auth-service"

Duration: 2h 15m
Archived to: .sdlc/tasks/completed/TASK-001.md

Remaining tasks: 11
Next suggested: TASK-002 (depends on this task)
```
