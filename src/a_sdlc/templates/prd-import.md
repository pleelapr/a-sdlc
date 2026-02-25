# /sdlc:prd-import

## Purpose

Import a single Jira issue as a local PRD with interactive sprint assignment.

## Syntax

```
/sdlc:prd-import jira <issue-key>
```

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `system` | Yes | External system: "jira" (Linear support pending) |
| `issue-key` | Yes | Jira issue key (e.g., PROJ-123) |

## Prerequisites

- Jira integration must be configured via MCP tool or CLI
- Project must be initialized with `/sdlc:init`

## Execution Steps

### 1. Validate Integration

Check that Jira is configured:

```
Use MCP tool: mcp__asdlc__get_integrations()

If Jira not configured:
  Error: Jira integration not configured.

  Configure first with MCP tool:
    mcp__asdlc__configure_jira(
      base_url="https://company.atlassian.net",
      email="your-email@example.com",
      api_token="your-api-token",
      project_key="PROJ"
    )
```

### 2. Create Placeholder PRD

Create a PRD with the issue key as initial title:

```python
result = mcp__asdlc__create_prd(
    title="PROJ-123",  # Placeholder, will be updated by sync
    status="draft",
    source="jira:PROJ-123"
)
prd_id = result["prd"]["id"]  # e.g., "PROJ-P0001"
# Content will be populated by sync_prd_from() in step 4
```

### 3. Link PRD to External System

Create sync mapping with explicit system parameter (future-proof for Linear, etc.):

```python
mcp__asdlc__link_prd(
    prd_id=prd_id,
    system="jira",      # Explicit: "jira" | "linear" | future systems
    external_id="PROJ-123"
)
```

### 4. Sync Content from External System

Pull the actual content from Jira:

```python
result = mcp__asdlc__sync_prd_from(prd_id=prd_id)
# This fetches title, description, status from Jira and updates the PRD
```

### 5. Display Imported PRD

Show what was imported:

```
PRD Imported from Jira: PROJ-123

  PRD ID: PROJ-P0001
  Title: Implement user authentication
  Status: draft (mapped from Jira: In Progress)

  Description:
  Add OAuth 2.0 authentication flow with support for
  Google and GitHub providers...

  Sync: Linked to jira:PROJ-123 for future updates
```

### 6. Ask About Sprint Assignment (INTERACTIVE)

**IMPORTANT: Wait for user response before proceeding.**

```
Would you like to assign this PRD to a sprint?

1. Yes, assign to existing sprint
2. No, keep in backlog
```

**If user selects "Yes":**

Call `mcp__asdlc__list_sprints()` and present options:

```
Available Sprints:

1. PROJ-S0001: Authentication Sprint (active)
2. PROJ-S0002: API Development (planned)
3. PROJ-S0003: Testing Phase (planned)

Which sprint? (enter number or sprint ID, or 'skip' for backlog)
```

**If user picks a sprint:**

```python
mcp__asdlc__update_prd(
    prd_id="PROJ-P0001",
    sprint_id="PROJ-S0001"
)
```

### 7. Display Final Result

```
PRD Imported: PROJ-P0001

  Title: Implement user authentication
  Source: jira:PROJ-123
  Sprint: PROJ-S0001 (Authentication Sprint)
  Status: draft

  Sync mapping created - use mcp__asdlc__sync_prd_from() to pull updates.
```

### 8. Ask About Next Steps (INTERACTIVE)

```
Would you like to:

1. Split this PRD into tasks now -> /sdlc:prd-split PROJ-P0001
2. View the full PRD -> /sdlc:prd PROJ-P0001
3. Done for now
```

## Status Mapping

| Jira Status | PRD Status |
|-------------|------------|
| To Do | draft |
| In Progress | ready |
| Done | split |
| Closed | completed |

## Examples

```
# Import specific Jira issue
/sdlc:prd-import jira PROJ-123

# Import and assign to sprint interactively
/sdlc:prd-import jira PROJ-456
> Would you like to assign to a sprint? Yes
> Which sprint? 1
> Would you like to split into tasks? Yes
```

## Error Cases

### Issue Not Found
```
Error: Jira issue PROJ-999 not found.

Verify:
  - Issue key is correct
  - You have access to the project
  - Integration is configured: mcp__asdlc__get_integrations()
```

### Already Imported
```
Issue Already Imported

Jira issue PROJ-123 is already linked to PRD PROJ-P0001.

Options:
  1. View existing PRD: /sdlc:prd PROJ-P0001
  2. Sync latest changes: mcp__asdlc__sync_prd_from(prd_id="PROJ-P0001")
  3. Reimport (will create duplicate): Continue anyway
```

### Integration Not Configured
```
Error: Jira integration not configured.

Configure with MCP tool:
  mcp__asdlc__configure_jira(
    base_url="https://company.atlassian.net",
    email="your-email@example.com",
    api_token="your-api-token",
    project_key="PROJ"
  )
```

## MCP Tools Used

| Tool | Purpose |
|------|---------|
| `mcp__asdlc__get_integrations` | Check Jira is configured |
| `mcp__asdlc__list_sprints` | Get available sprints for assignment |
| `mcp__asdlc__create_prd` | Create the PRD with Jira content |
| `mcp__asdlc__link_prd` | Create sync mapping to Jira |
| `mcp__asdlc__sync_prd_from` | Pull content from Jira |
| `mcp__asdlc__update_prd` | Assign PRD to sprint |
| `mcp__asdlc__list_sync_mappings` | Check if already imported |

## Notes

- Importing creates a local copy; use `mcp__asdlc__sync_prd_from` for updates
- PRD content is derived from Jira issue description
- Subtasks from Jira are appended to PRD content as a checklist
- Labels and components are preserved in PRD metadata
