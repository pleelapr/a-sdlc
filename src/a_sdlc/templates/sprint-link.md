# /sdlc:sprint-link

## Purpose

Link an existing local sprint to an external system sprint/cycle for bidirectional sync.

## Syntax

```
/sdlc:sprint-link <sprint-id> <system> <external-id>
```

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `sprint-id` | Yes | Local sprint ID (e.g., SPRINT-001) |
| `system` | Yes | External system: "linear" or "jira" |
| `external-id` | Yes | External sprint/cycle ID |

## Prerequisites

- External integration must be configured via `a-sdlc connect`
- Local sprint must exist

## Execution Steps

### 1. Call Link Sprint MCP Tool

```
mcp__asdlc__link_sprint(
    sprint_id="SPRINT-001",
    system="linear",
    external_id="ENG-Q1-2025"
)
```

### 2. Review Link Result

The MCP tool validates and creates the mapping:

```json
{
  "status": "success",
  "sprint_id": "SPRINT-001",
  "external_system": "linear",
  "external_id": "ENG-Q1-2025",
  "external_name": "Q1 Auth Sprint",
  "external_url": "https://linear.app/team/ENG/cycle/25",
  "sync_status": "pending"
}
```

### 3. Output

```
Sprint Linked: SPRINT-001 ↔ Linear ENG-Q1-2025

Local Sprint:
  ID: SPRINT-001
  Name: Week 4 Auth
  Tasks: 5

External Sprint:
  System: Linear
  ID: ENG-Q1-2025
  Name: Q1 Auth Sprint
  URL: https://linear.app/team/ENG/cycle/25

Status: PENDING (not yet synced)

Next steps:
  - Initial sync: /sdlc:sprint-sync SPRINT-001
  - View mappings: /sdlc:sprint-mappings
```

## Use Cases

### Link Local Sprint to Existing External Cycle

```
# Create sprint locally
/sdlc:sprint-create --name "Auth Feature" --goal "Complete authentication"

# Link to existing Linear cycle
/sdlc:sprint-link SPRINT-001 linear ENG-Q1-2025

# Sync to pull existing issues or push local tasks
/sdlc:sprint-sync SPRINT-001
```

### Switch External System

```
# Unlink from Jira
/sdlc:sprint-unlink SPRINT-001

# Link to Linear instead
/sdlc:sprint-link SPRINT-001 linear ENG-Q2-2025
```

## Examples

```
# Link to Linear cycle
/sdlc:sprint-link SPRINT-001 linear ENG-Q1-2025

# Link to Jira sprint
/sdlc:sprint-link SPRINT-002 jira 123
```

## Error Cases

### Sprint Not Found
```
Error: Sprint SPRINT-001 not found.

Available sprints:
  - SPRINT-002: API Development
  - SPRINT-003: Testing Phase

List all: /sdlc:sprint-list
```

### Sprint Already Linked
```
Error: Sprint SPRINT-001 is already linked to Linear ENG-Q1-2020.

Options:
  1. Unlink first: /sdlc:sprint-unlink SPRINT-001
  2. Keep existing link

To unlink: /sdlc:sprint-unlink SPRINT-001
```

### External Sprint Not Found
```
Error: Could not find Linear cycle: ENG-INVALID

Verify:
  - Cycle ID is correct
  - You have access to the team
  - Integration is configured: a-sdlc integrations
```

### Invalid System
```
Error: Unknown system "github".

Supported systems:
  - linear: Linear cycles
  - jira: Jira sprints
```

### Integration Not Configured
```
Error: Linear integration not configured.

Configure first:
  a-sdlc connect linear --api-key <key> --team-id <team>
```

## Notes

- Linking does not sync tasks; run `/sdlc:sprint-sync` after linking
- Each local sprint can only be linked to one external sprint
- Unlinking preserves local data; use `/sdlc:sprint-unlink` to remove
- External sprint is validated before creating the link
