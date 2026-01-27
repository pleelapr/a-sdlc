# /sdlc:sprint-unlink

## Purpose

Remove the link between a local sprint and its external system sprint/cycle. The local sprint and tasks are preserved.

## Syntax

```
/sdlc:sprint-unlink <sprint-id>
```

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `sprint-id` | Yes | Local sprint ID (e.g., SPRINT-001) |

## Execution Steps

### 1. Call Unlink Sprint MCP Tool

```
mcp__asdlc__unlink_sprint(sprint_id="SPRINT-001")
```

### 2. Review Unlink Result

The MCP tool removes the mapping and clears external references:

```json
{
  "status": "success",
  "sprint_id": "SPRINT-001",
  "previous_system": "linear",
  "previous_external_id": "ENG-Q1-2025",
  "message": "Sprint unlinked successfully"
}
```

### 3. Output

```
Sprint Unlinked: SPRINT-001

Removed link to: Linear ENG-Q1-2025

Local sprint preserved:
  ID: SPRINT-001
  Name: Week 4 - Auth Feature
  Status: ACTIVE
  Tasks: 5

External sprint unchanged:
  The Linear cycle ENG-Q1-2025 was not modified.

To re-link:
  /sdlc:sprint-link SPRINT-001 linear <cycle-id>

To import fresh:
  /sdlc:sprint-import linear
```

## What Gets Removed

- Sync mapping in database
- Sprint's `external_id`, `external_url`, `external_system` fields

## What Is Preserved

- Local sprint (ID, name, status, goal, dates)
- All tasks in the sprint
- Task external_id references (for potential re-linking)
- External sprint/cycle (not modified)

## Use Cases

### Re-link to Different Cycle

```bash
# Unlink from old cycle
/sdlc:sprint-unlink SPRINT-001

# Link to new cycle
/sdlc:sprint-link SPRINT-001 linear ENG-Q2-2025
```

### Clean Up After External Deletion

```bash
# External cycle was deleted, clean up mapping
/sdlc:sprint-unlink SPRINT-001
```

### Migrate Between Systems

```bash
# Unlink from Jira
/sdlc:sprint-unlink SPRINT-001

# Link to Linear
/sdlc:sprint-link SPRINT-001 linear <cycle-id>

# Sync to create issues in Linear
/sdlc:sprint-sync-to SPRINT-001
```

### Stop Syncing

```bash
# Stop syncing with external system
/sdlc:sprint-unlink SPRINT-001

# Continue working locally only
```

## Examples

```
# Basic unlink
/sdlc:sprint-unlink SPRINT-001

# Then re-link to different external sprint
/sdlc:sprint-link SPRINT-001 linear NEW-CYCLE-ID
```

## Error Cases

### Sprint Not Found
```
Error: Sprint SPRINT-001 not found.

Check:
  - Sprint ID is correct
  - Sprint hasn't been deleted

List sprints: /sdlc:sprint-list
```

### Sprint Not Linked
```
Error: Sprint SPRINT-001 is not linked to any external system.

Nothing to unlink. Current sprint status:
  ID: SPRINT-001
  Name: Week 4 - Auth Feature
  External: (none)

To link: /sdlc:sprint-link SPRINT-001 <system> <external-id>
```

## Notes

- Unlinking is reversible; re-link with `/sdlc:sprint-link`
- Local sprint and tasks are never deleted
- External sprint/cycle is not modified
- Sync history (last_synced_at) is lost
- Task external_ids are preserved for potential re-linking
- Consider syncing pending changes before unlinking
