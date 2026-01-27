# /sdlc:sprint-sync-from

## Purpose

Pull changes from an external system (Linear/Jira) to update the local sprint. One-way sync: external → local.

## Syntax

```
/sdlc:sprint-sync-from <sprint-id>
```

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `sprint-id` | Yes | Local sprint ID (e.g., SPRINT-001) |

## Prerequisites

- Sprint must be linked to an external system
- External integration must be configured via `a-sdlc connect`

## Execution Steps

### 1. Call Sync From MCP Tool

```
mcp__asdlc__sync_sprint_from(sprint_id="SPRINT-001")
```

### 2. Review Pull Result

The MCP tool fetches external state and applies changes locally:

```json
{
  "status": "success",
  "sprint_id": "SPRINT-001",
  "external_system": "linear",
  "external_id": "ENG-Q1-2025",
  "changes": {
    "status_updates": [
      {"task_id": "TASK-002", "old": "pending", "new": "in_progress"},
      {"task_id": "TASK-004", "old": "in_progress", "new": "blocked"}
    ],
    "content_updates": [
      {"task_id": "TASK-003", "field": "title", "old": "Add user fields", "new": "Add user model fields and validation"}
    ],
    "new_tasks": [
      {"task_id": "TASK-006", "title": "API rate limiting", "external_id": "ENG-128"}
    ]
  },
  "summary": {
    "status_updates": 2,
    "content_updates": 1,
    "new_tasks": 1
  }
}
```

### 3. Output

```
Pulling from Linear ENG-Q1-2025 → SPRINT-001...

Status Updates (2):
  ~ TASK-002: pending → in_progress
  ~ TASK-004: in_progress → blocked

Content Updates (1):
  ~ TASK-003: Title updated
    Old: "Add user fields"
    New: "Add user model fields and validation"

New Tasks Imported (1):
  + TASK-006: API rate limiting (from ENG-128)

Pull Complete: Linear ENG-Q1-2025 → SPRINT-001

Summary:
  Status updates: 2
  Content updates: 1
  New tasks: 1

Last synced: 2025-01-26T14:30:00Z

Note: Local changes not pushed. To push: /sdlc:sprint-sync-to SPRINT-001
```

## What Gets Pulled

| External Change | Local Action |
|-----------------|--------------|
| Issue status changed | Update task status |
| Issue title/description changed | Update task title/description |
| New issue in cycle/sprint | Create new task |
| Issue priority changed | Update task priority |

## What Does NOT Get Pulled

- Issues removed from cycle (local tasks preserved)
- Assignee changes (not tracked locally)
- Labels/tags (not mapped to local fields)

## Examples

```
# Pull all changes from external
/sdlc:sprint-sync-from SPRINT-001

# For bidirectional sync
/sdlc:sprint-sync SPRINT-001

# To push changes instead
/sdlc:sprint-sync-to SPRINT-001
```

## Error Cases

### Sprint Not Linked
```
Error: Sprint SPRINT-001 is not linked to an external system.

Link first: /sdlc:sprint-link SPRINT-001 linear <cycle-id>
```

### No Changes Found
```
Pull from Linear ENG-Q1-2025 → SPRINT-001

No changes detected. Local sprint is up to date.

Last synced: 2025-01-26T14:00:00Z (30 minutes ago)
```

### External Sprint Not Found
```
Error: Linear cycle ENG-Q1-2025 not found or no longer accessible.

The cycle may have been:
  - Deleted
  - Moved to a different team
  - Access revoked

To unlink: /sdlc:sprint-unlink SPRINT-001
```

### Integration Not Configured
```
Error: Linear integration not configured.

Configure: a-sdlc connect linear --api-key <key> --team-id <team>
```

## Notes

- This is a one-way sync (external → local)
- Local changes are preserved; use `/sdlc:sprint-sync` for bidirectional
- New issues are automatically imported as tasks
- Does not delete local tasks even if removed from external cycle
- Sync mapping is updated with last_synced_at timestamp
