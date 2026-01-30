# /sdlc:prd-delete

## Purpose

Delete a PRD permanently.

## Syntax

/sdlc:prd-delete <prd-id>

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `prd-id` | Yes | PRD ID to delete (e.g., PROJ-P0001) |

## Execution

```
mcp__asdlc__delete_prd(prd_id="<prd-id>")
```

## Behavior

- Deletes PRD from database
- Removes content file from ~/.a-sdlc/content/{project}/prds/
- WARNING: Does NOT delete associated tasks

## Output

```
PRD Deleted: PROJ-P0001 🗑️
"User Authentication Feature"

Warning: 3 tasks were associated with this PRD.
They are now orphaned. Use /sdlc:task-list to review.
```

## Related Commands

- `/sdlc:prd-list` - View all PRDs
- `/sdlc:prd` - View PRD before deleting
