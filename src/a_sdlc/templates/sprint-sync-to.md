# /sdlc:sprint-sync-to

## Purpose

Push local sprint changes to the linked external system (Linear/Jira). One-way sync: local → external.

## Syntax

```
/sdlc:sprint-sync-to <sprint-id>
```

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `sprint-id` | Yes | Local sprint ID (e.g., SPRINT-001) |

## Prerequisites

- Sprint must be linked to an external system
- External integration must be configured via `a-sdlc connect`

## Execution Steps

### 1. Call Sync To MCP Tool

```
mcp__asdlc__sync_sprint(sprint_id="SPRINT-001", direction="push")
```

### 2. Review Push Result

The MCP tool pushes local changes to the external system:

```json
{
  "status": "success",
  "sprint_id": "SPRINT-001",
  "external_system": "linear",
  "external_id": "ENG-Q1-2025",
  "changes": {
    "status_updates": [
      {"task_id": "TASK-001", "external_id": "ENG-123", "status": "completed"},
      {"task_id": "TASK-003", "external_id": "ENG-125", "status": "blocked"}
    ],
    "new_issues": [
      {"task_id": "TASK-005", "external_id": "ENG-129", "title": "Add logout endpoint"}
    ]
  },
  "summary": {
    "status_updates": 2,
    "new_issues": 1
  }
}
```

### 3. Output

```
Pushing SPRINT-001 → Linear ENG-Q1-2025...

Status Updates (2):
  ~ TASK-001: completed → Linear "Done"
  ~ TASK-003: blocked → Linear "Blocked"

New Issues Created (1):
  + TASK-005: "Add logout endpoint" → ENG-129

Push Complete: SPRINT-001 → Linear ENG-Q1-2025

Summary:
  Status updates: 2
  Issues created: 1

Last synced: 2025-01-26T14:30:00Z

Note: External changes not pulled. To pull: /sdlc:sprint-sync-from SPRINT-001
```

## What Gets Pushed

| Local Change | External Action |
|--------------|-----------------|
| Task status changed | Update issue status |
| New task (no external_id) | Create new issue in cycle/sprint |
| Task priority changed | Update issue priority |

## What Does NOT Get Pushed

- Task descriptions (to avoid overwriting external details)
- Deleted tasks (external issues preserved)
- Implementation steps, success criteria (local-only fields)

## Status Mapping

### SDLC → Linear

| SDLC Status | Linear State |
|-------------|--------------|
| pending | Todo |
| in_progress | In Progress |
| blocked | Blocked |
| completed | Done |
| cancelled | Canceled |

### SDLC → Jira

| SDLC Status | Jira Transition |
|-------------|-----------------|
| pending | To Do |
| in_progress | In Progress |
| blocked | Blocked |
| completed | Done |

## Examples

```
# Push all local changes to external
/sdlc:sprint-sync-to SPRINT-001

# For bidirectional sync
/sdlc:sprint-sync SPRINT-001

# To pull changes instead
/sdlc:sprint-sync-from SPRINT-001
```

## Error Cases

### Sprint Not Linked
```
Error: Sprint SPRINT-001 is not linked to an external system.

Link first: /sdlc:sprint-link SPRINT-001 linear <cycle-id>
```

### No Changes to Push
```
Push SPRINT-001 → Linear ENG-Q1-2025

No changes to push. External system is up to date.

Last synced: 2025-01-26T14:00:00Z (30 minutes ago)
```

### External API Error
```
Error: Failed to update Linear issue ENG-123.

Response: 403 Forbidden
Message: "You don't have permission to modify this issue"

Check:
  - API key has write permissions
  - Issue is not locked
  - You have team access
```

### Cycle Completed/Archived
```
Error: Linear cycle ENG-Q1-2025 is completed and cannot be modified.

Options:
  1. Unlink sprint: /sdlc:sprint-unlink SPRINT-001
  2. Link to new cycle: /sdlc:sprint-link SPRINT-001 linear <new-cycle-id>
```

### Integration Not Configured
```
Error: Linear integration not configured.

Configure: a-sdlc connect linear --api-key <key> --team-id <team>
```

## Notes

- This is a one-way sync (local → external)
- External changes are not pulled; use `/sdlc:sprint-sync` for bidirectional
- New local tasks without external_id will be created in external system
- Tasks gain external_id and external_url after being pushed
- Sync mapping is updated with last_synced_at timestamp
