# /sdlc:sprint-show

## Purpose

Display detailed information about a sprint including assigned PRDs and their tasks.

## Syntax

```
/sdlc:sprint-show <sprint-id>
```

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `sprint-id` | Yes | Sprint ID (e.g., SPRINT-001) |

## Execution Steps

### 1. Load Sprint Data

Use MCP tool: `mcp__asdlc__get_sprint(sprint_id)`

### 2. Load Sprint PRDs

Use MCP tool: `mcp__asdlc__get_sprint_prds(sprint_id)`

### 3. Load Sprint Tasks

Use MCP tool: `mcp__asdlc__get_sprint_tasks(sprint_id)` (derived via PRDs)

### 4. Output

```
Sprint: SPRINT-001 - Week 4 Auth Feature

Status: ACTIVE
Goal: Complete OAuth implementation
Started: 2025-01-27T09:00:00Z

PRDs (2):
  📄 feature-auth [ready]     OAuth Authentication
  📄 user-profile [draft]     User Profile Management

Progress: ████████████░░░░░░░░ 60%
          3/5 tasks completed

Tasks by PRD:

feature-auth (3 tasks):
  ✅ TASK-001  [Completed]    Set up OAuth config
  ✅ TASK-002  [Completed]    Create login endpoint
  🔄 TASK-003  [In Progress]  Implement token refresh

user-profile (2 tasks):
  ⏳ TASK-004  [Pending]      Add profile fields
  ⏳ TASK-005  [Pending]      Create profile API

Task Summary:
  Completed:   3
  In Progress: 1
  Pending:     2
  Blocked:     0

Commands:
  Start sprint: /sdlc:sprint-start SPRINT-001
  Add PRD: mcp__asdlc__add_prd_to_sprint("SPRINT-001", "prd-id")
  Complete: /sdlc:sprint-complete SPRINT-001
```

## Sprint → PRD → Task Hierarchy

Sprints now contain PRDs, not tasks directly:
- **Sprint**: Groups related PRDs for a development cycle
- **PRD**: Product requirements assigned to a sprint
- **Task**: Implementation work under a PRD (inherits sprint from PRD)

## Related Tools

| Tool | Description |
|------|-------------|
| `get_sprint(sprint_id)` | Get sprint with PRD/task counts |
| `get_sprint_prds(sprint_id)` | List all PRDs in sprint |
| `get_sprint_tasks(sprint_id)` | List all tasks (derived via PRDs) |
| `add_prd_to_sprint(sprint_id, prd_id)` | Assign PRD to sprint |
| `remove_prd_from_sprint(prd_id)` | Move PRD to backlog |

## Examples

```
/sdlc:sprint-show SPRINT-001
/sdlc:sprint-show SPRINT-002
```
