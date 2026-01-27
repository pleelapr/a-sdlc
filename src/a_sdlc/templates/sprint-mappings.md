# /sdlc:sprint-mappings

## Purpose

View all sprint mappings between local sprints and external systems (Linear/Jira).

## Syntax

```
/sdlc:sprint-mappings [--system <system>] [--status <status>]
```

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `--system` | No | Filter by system: "linear" or "jira" |
| `--status` | No | Filter by sync status: "synced", "pending", "conflict", "error" |

## Execution Steps

### 1. Load Mappings

Read `.sdlc/sprints/mappings.json`:
```json
{
  "SPRINT-001": {
    "local_sprint_id": "SPRINT-001",
    "external_system": "linear",
    "external_sprint_id": "ENG-Q1-2025",
    "external_sprint_name": "Q1 Auth Sprint",
    "sync_status": "synced",
    "last_synced_at": "2025-01-26T14:30:00Z"
  },
  "SPRINT-002": {
    "local_sprint_id": "SPRINT-002",
    "external_system": "jira",
    "external_sprint_id": "123",
    "external_sprint_name": "API Development Sprint",
    "sync_status": "pending",
    "last_synced_at": null
  }
}
```

### 2. Apply Filters

Filter by system and/or status if specified.

### 3. Enrich with Sprint Details

For each mapping, load the local sprint to get current status:
```python
for mapping in mappings:
    sprint = get_sprint(mapping.local_sprint_id)
    mapping.sprint_status = sprint.status if sprint else "deleted"
    mapping.task_count = len(sprint.task_ids) if sprint else 0
```

### 4. Display Mappings

```
Sprint Mappings
═══════════════════════════════════════════════════════════════════════════

Local Sprint    │ External System │ External ID      │ Sync Status │ Last Sync
────────────────┼─────────────────┼──────────────────┼─────────────┼───────────
SPRINT-001      │ Linear          │ ENG-Q1-2025      │ ✅ synced   │ 30m ago
  └─ Q1 Auth Sprint (ACTIVE, 5 tasks)
────────────────┼─────────────────┼──────────────────┼─────────────┼───────────
SPRINT-002      │ Jira            │ 123              │ ⏳ pending  │ never
  └─ API Development Sprint (PLANNED, 8 tasks)
────────────────┼─────────────────┼──────────────────┼─────────────┼───────────
SPRINT-003      │ Linear          │ ENG-Q1-2026      │ ⚠️ conflict │ 2h ago
  └─ Q1 API Sprint (ACTIVE, 3 tasks)

Summary:
  Total mappings: 3
  Synced: 1
  Pending: 1
  Conflicts: 1

Actions:
  Sync all: /sdlc:sprint-sync <id>
  View details: /sdlc:sprint-show <id>
  Unlink: /sdlc:sprint-unlink <id>
```

## Status Icons

| Status | Icon | Meaning |
|--------|------|---------|
| synced | ✅ | Up to date with external |
| pending | ⏳ | Never synced or changes pending |
| conflict | ⚠️ | Sync conflict detected |
| error | ❌ | Last sync failed |

## Detailed View

For each mapping with `--verbose`:

```
SPRINT-001 ↔ Linear ENG-Q1-2025
───────────────────────────────────────
Local Sprint:
  ID: SPRINT-001
  Name: Week 4 - Auth Feature
  Status: ACTIVE
  Tasks: 5 (3 completed, 2 in progress)

External Sprint:
  System: Linear
  ID: ENG-Q1-2025
  Name: Q1 Auth Sprint
  URL: https://linear.app/team/ENG/cycle/25

Sync Status:
  Status: SYNCED
  Last Synced: 2025-01-26T14:30:00Z (30 minutes ago)
  Direction: bidirectional

Task Mapping:
  TASK-001 ↔ ENG-123 (synced)
  TASK-002 ↔ ENG-124 (synced)
  TASK-003 ↔ ENG-125 (synced)
  TASK-004 ↔ ENG-126 (synced)
  TASK-005 ↔ (not linked)
```

## Examples

```
# View all mappings
/sdlc:sprint-mappings

# Filter by system
/sdlc:sprint-mappings --system linear

# Filter by status
/sdlc:sprint-mappings --status conflict

# Combine filters
/sdlc:sprint-mappings --system linear --status synced
```

## Output When No Mappings

```
No Sprint Mappings Found

No sprints are linked to external systems.

To link a sprint:
  /sdlc:sprint-link <sprint-id> <system> <external-id>

To import from external:
  /sdlc:sprint-import linear
  /sdlc:sprint-import jira --project PROJ
```

## Notes

- Mappings are stored in `.sdlc/sprints/mappings.json`
- Sync status is updated after each sync operation
- Deleted sprints will show as "deleted" in mapping list
- Use `/sdlc:sprint-unlink` to remove stale mappings
