# /sdlc:sprint-import

## Purpose

Import sprints/cycles from external systems (Jira/Linear) into the local a-sdlc system for parallel execution.

## Syntax

```
/sdlc:sprint-import <system> [--status <status>] [--cycle-id <id>] [--sprint-id <id>] [--board-id <id>]
```

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `system` | Yes | External system: "linear" or "jira" |
| `--status` | No | Filter by status: "active", "upcoming", "completed" |
| `--cycle-id` | No | Linear: specific cycle ID to import |
| `--sprint-id` | No | Jira: specific sprint ID to import |
| `--board-id` | No | Jira: board ID (required if not configured) |

## Prerequisites

Before importing, ensure the integration is configured:

```bash
# For Linear
a-sdlc connect linear --api-key <key> --team-id <team>

# For Jira
a-sdlc connect jira --url <url> --email <email> --api-token <token> --project-key <key>
```

## Execution Steps

### 1. Validate Integration

Check that the external system is configured:

```
Use MCP tool: mcp__asdlc__manage_integration("list")

Expected response:
{
  "status": "success",
  "integrations": [
    {"system": "linear", "configured": true, "team_id": "ENG"}
  ]
}
```

### 2. Import Sprint

Call the appropriate MCP tool based on the system:

**For Linear:**
```
mcp__asdlc__import_from_linear(
    cycle_id="ENG-Q1-2025",  # Optional: specific cycle
    status="active"          # Optional: filter by status
)
```

**For Jira:**
```
mcp__asdlc__import_from_jira(
    sprint_id="123",         # Optional: specific sprint
    board_id="10",           # Optional: board ID
    state="active"           # Optional: filter by state
)
```

### 3. Review Import Result

The MCP tool returns the created sprint and tasks:

```json
{
  "status": "success",
  "sprint": {
    "id": "SPRINT-001",
    "name": "Q1 Auth Sprint",
    "external_id": "ENG-Q1-2025",
    "external_url": "https://linear.app/team/ENG/cycle/25",
    "task_count": 5
  },
  "tasks": [
    {"id": "TASK-001", "title": "Set up OAuth config", "external_id": "ENG-123"},
    {"id": "TASK-002", "title": "Create login endpoint", "external_id": "ENG-124"}
  ]
}
```

### 4. Output

```
Importing ENG-Q1-2025...

Sprint Created: SPRINT-001
  Name: Q1 Auth Sprint
  External: Linear cycle ENG-Q1-2025
  URL: https://linear.app/team/ENG/cycle/25

Tasks Imported: 5
  TASK-001: Set up OAuth config (from ENG-123)
  TASK-002: Create login endpoint (from ENG-124)
  TASK-003: Add user model fields (from ENG-125)
  TASK-004: Implement token refresh (from ENG-126)
  TASK-005: Add logout endpoint (from ENG-127)

Sync mapping created automatically.

Next steps:
  - View sprint: /sdlc:sprint-show SPRINT-001
  - Start sprint: /sdlc:sprint-start SPRINT-001
  - Sync changes: /sdlc:sprint-sync SPRINT-001
```

## Status Mapping

### Linear → SDLC

| Linear State | SDLC Status |
|--------------|-------------|
| Backlog | pending |
| Todo | pending |
| In Progress | in_progress |
| In Review | in_progress |
| Blocked | blocked |
| Done | completed |
| Canceled | cancelled |

### Jira → SDLC

| Jira Status | SDLC Status |
|-------------|-------------|
| To Do | pending |
| In Progress | in_progress |
| Blocked | blocked |
| Done | completed |

## Examples

```
# Import active Linear cycles
/sdlc:sprint-import linear --status active

# Import specific Linear cycle
/sdlc:sprint-import linear --cycle-id ENG-Q1-2025

# Import Jira sprints
/sdlc:sprint-import jira --board-id 10 --status active

# Import specific Jira sprint
/sdlc:sprint-import jira --sprint-id 123
```

## Handling Duplicate Imports

### Sprint Already Imported

When the MCP tool returns `status: "already_exists"`, the agent should present the user with clear options:

**Response Format:**
```json
{
  "status": "already_exists",
  "message": "Sprint already imported as SPRINT-001",
  "existing_sprint_id": "SPRINT-001",
  "existing_sprint_title": "Q1 Auth Sprint",
  "external_id": "ENG-Q1-2025",
  "last_synced": "2025-01-15T10:30:00Z",
  "options": [
    "use_existing: Use the existing sprint",
    "sync: Re-sync with /sdlc:sprint-sync",
    "reimport: Unlink first with /sdlc:sprint-unlink, then reimport",
    "cancel: Cancel the import"
  ]
}
```

**Agent Action:** Present the user with choices:

```
⚠️ Sprint Already Imported

The external sprint {external_id} is already imported as local sprint {existing_sprint_id}.

  Sprint: {existing_sprint_title}
  Last Synced: {last_synced}

What would you like to do?

1. **Use existing** - Continue working with the existing sprint
   → Run: /sdlc:sprint-show {existing_sprint_id}

2. **Re-sync** - Pull latest changes from the external system
   → Run: /sdlc:sprint-sync {existing_sprint_id}

3. **Reimport** - Remove the link and import fresh
   → Run: /sdlc:sprint-unlink {existing_sprint_id}
   → Then reimport

4. **Cancel** - Abort the import operation
```

**Wait for user input before proceeding.**

## Error Cases

### Integration Not Configured
```
Error: Linear integration not configured.

Configure first:
  a-sdlc connect linear --api-key <key> --team-id <team>

Or check status:
  a-sdlc integrations
```

### No Sprints Found
```
No active sprints found in Linear.

Try:
  - Different status: --status upcoming
  - Check Linear directly
  - Verify team_id is correct
```

## Notes

- Importing creates a snapshot; use `/sdlc:sprint-sync` for ongoing updates
- Task priorities are mapped to closest equivalent
- External URLs are preserved for easy navigation
- Duplicate detection prevents re-importing the same sprint
- Sync mappings are created automatically in the SQLite database
