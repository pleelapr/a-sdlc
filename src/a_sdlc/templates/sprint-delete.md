# /sdlc:sprint-delete

## Purpose

Delete a sprint permanently.

## Syntax

/sdlc:sprint-delete <sprint-id>

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `sprint-id` | Yes | Sprint ID to delete (e.g., PROJ-S0001) |

## Execution

```
mcp__asdlc__delete_sprint(sprint_id="<sprint-id>")
```

## Behavior

- Deletes sprint from database
- Unlinks all PRDs (sets their sprint_id to NULL)
- Removes any Linear/Jira sync mappings
- Does NOT delete PRDs or tasks

## Output

```
Sprint Deleted: PROJ-S0001 🗑️
"Sprint 1: Authentication"

2 PRDs were unlinked from this sprint.
They are preserved and can be assigned to another sprint.
```

## Related Commands

- `/sdlc:sprint-list` - View all sprints
- `/sdlc:sprint-show` - View sprint before deleting
