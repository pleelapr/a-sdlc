# /sdlc:sprint-start

## Purpose

Activate a sprint, changing its status from `planned` to `active`.

## Syntax

```
/sdlc:sprint-start <sprint-id>
```

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `sprint-id` | Yes | Sprint ID to activate (e.g., SPRINT-01) |

## Execution

Use the MCP tool to start a sprint:

```
mcp__asdlc__start_sprint(sprint_id="SPRINT-01")
```

This will:
1. Validate the sprint exists
2. Update status to `active`
3. Set `started_at` timestamp
4. Return sprint details with PRD and task counts

## Output

```json
{
  "status": "updated",
  "message": "Sprint started: SPRINT-01",
  "sprint": {
    "id": "SPRINT-01",
    "title": "Auth Feature Sprint",
    "status": "active",
    "started_at": "2025-01-27T09:00:00Z",
    "prd_count": 1,
    "task_counts": {
      "pending": 3,
      "in_progress": 0,
      "completed": 0,
      "blocked": 0
    }
  }
}
```

## Display Format

```
Sprint Started: SPRINT-01 ✅

Name: Auth Feature Sprint
Status: Active
Started: 2025-01-27 09:00

PRDs in Sprint: 1
  - feature-auth (3 tasks)

Task Summary:
  Pending: 3
  In Progress: 0
  Completed: 0
  Blocked: 0

Next: /sdlc:sprint-run SPRINT-01
```

## Error Cases

### Sprint Not Found
```
Error: Sprint not found: SPRINT-999
```

### Sprint Already Active
```
Sprint SPRINT-01 is already active.
Started: 2025-01-27T09:00:00Z
```

### Sprint Already Completed
```
Sprint SPRINT-01 is already completed.
Completed: 2025-01-26T17:00:00Z

To continue work, create a new sprint.
```

## Notes

- Multiple sprints can be active at the same time
- Starting a sprint sets the `started_at` timestamp
- Tasks are accessed through their parent PRDs assigned to the sprint

## Related Commands

- `/sdlc:sprint-show` - View sprint details
- `/sdlc:sprint-run` - Execute sprint tasks
- `/sdlc:sprint-complete` - Close sprint
