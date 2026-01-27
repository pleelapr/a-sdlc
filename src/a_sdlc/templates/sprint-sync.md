# /sdlc:sprint-sync

## Purpose

Bidirectional sync between a local sprint and its linked external system sprint/cycle. Pulls changes from external, then pushes local changes.

## Syntax

```
/sdlc:sprint-sync <sprint-id> [--strategy <strategy>] [--dry-run]
```

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `sprint-id` | Yes | Local sprint ID (e.g., SPRINT-001) |
| `--strategy` | No | Conflict resolution: "local-wins", "external-wins", "ask" (default: local-wins) |
| `--dry-run` | No | Show changes without applying |

## Prerequisites

- Sprint must be linked to an external system (Linear or Jira)
- External integration must be configured via `a-sdlc connect`

## Execution Steps

### 1. Call Sync MCP Tool

```
mcp__asdlc__sync_sprint(
    sprint_id="SPRINT-001",
    strategy="local-wins",  # or "external-wins"
    dry_run=false
)
```

### 2. Review Sync Result

The MCP tool performs bidirectional sync and returns detailed results:

```json
{
  "status": "success",
  "sprint_id": "SPRINT-001",
  "external_system": "linear",
  "external_id": "ENG-Q1-2025",
  "pulled": {
    "status_updates": [
      {"task_id": "TASK-002", "old": "pending", "new": "in_progress"}
    ],
    "new_tasks": [
      {"task_id": "TASK-006", "title": "API rate limiting", "external_id": "ENG-128"}
    ]
  },
  "pushed": {
    "status_updates": [
      {"task_id": "TASK-001", "external_id": "ENG-123", "status": "completed"}
    ],
    "new_issues": [
      {"task_id": "TASK-005", "external_id": "ENG-129", "title": "Add logout endpoint"}
    ]
  },
  "conflicts_resolved": 1,
  "strategy_used": "local-wins"
}
```

### 3. Output

```
Syncing SPRINT-001 ↔ Linear ENG-Q1-2025...

Changes from Linear (pulled):
  ~ TASK-002: Status changed to "in_progress"
  + TASK-006: API rate limiting (new from ENG-128)

Changes to Linear (pushed):
  ~ ENG-123: Status updated to Done
  + ENG-129: Created from TASK-005

Conflicts (using local-wins strategy):
  ! TASK-004: Local=completed, External=in_progress
    → Pushed local status to Linear

Summary:
  Pulled: 2 changes
  Pushed: 2 changes
  Conflicts: 1 (resolved with local-wins)

Sync Status: SYNCED
Last Synced: 2025-01-26T14:30:00Z

Next sync: /sdlc:sprint-sync SPRINT-001
View details: /sdlc:sprint-show SPRINT-001
```

## Conflict Resolution Strategies

### local-wins (default)
Local changes override external. Best for active development where local is source of truth.

### external-wins
External changes override local. Best for reporting/tracking where external is source of truth.

### ask
When using `--dry-run`, conflicts are listed for manual review. Without dry-run, the default strategy applies.

```
Conflict: TASK-004 - Implement token refresh

Local state:  completed (updated 5m ago)
External:     in_progress (updated 2m ago)

Using local-wins strategy: pushed local status
```

## Dry Run Mode

Preview changes without applying:

```
mcp__asdlc__sync_sprint(
    sprint_id="SPRINT-001",
    strategy="local-wins",
    dry_run=true
)
```

Output shows what would happen:
```
[DRY RUN] Syncing SPRINT-001 ↔ Linear ENG-Q1-2025...

Would pull:
  ~ TASK-002: Status pending → in_progress
  + NEW: API rate limiting (would create TASK-006)

Would push:
  ~ TASK-001: Completed → Linear Done
  + TASK-005: Would create Linear issue

No changes applied. Remove --dry-run to execute.
```

## Examples

```
# Standard bidirectional sync
/sdlc:sprint-sync SPRINT-001

# Preview changes without applying
/sdlc:sprint-sync SPRINT-001 --dry-run

# Let external system win conflicts
/sdlc:sprint-sync SPRINT-001 --strategy external-wins

# For one-way sync only
/sdlc:sprint-sync-from SPRINT-001  # Pull only
/sdlc:sprint-sync-to SPRINT-001    # Push only
```

## Error Cases

### Sprint Not Linked
```
Error: Sprint SPRINT-001 is not linked to an external system.

Link first: /sdlc:sprint-link SPRINT-001 linear <cycle-id>
Or import: /sdlc:sprint-import linear
```

### Integration Not Configured
```
Error: Linear integration not configured for this project.

Configure: a-sdlc connect linear --api-key <key> --team-id <team>
```

### External System Unavailable
```
Error: Could not connect to Linear API.

Check:
  - API key is valid
  - Network connectivity
  - Linear service status

Retry: /sdlc:sprint-sync SPRINT-001
```

### External Sprint Not Found
```
Error: Linear cycle ENG-Q1-2025 not found or inaccessible.

The cycle may have been deleted or access revoked.

To unlink: /sdlc:sprint-unlink SPRINT-001
```

## Notes

- Sync is atomic: all changes apply or none
- Timestamps are used to determine which change is newer
- New tasks created locally will be pushed to external system
- New issues in external will be imported as tasks
- Consider running `--dry-run` first to preview changes
- For one-way sync, use `/sdlc:sprint-sync-from` or `/sdlc:sprint-sync-to`
