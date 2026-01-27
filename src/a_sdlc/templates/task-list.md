# /sdlc:task-list

## Purpose

Display all tasks for the current project with status and priority information.

## Usage

Use the MCP tool to list tasks:

```
mcp__asdlc__list_tasks()
```

### With Filters

```
mcp__asdlc__list_tasks(status="pending")
mcp__asdlc__list_tasks(prd_id="feature-auth")
mcp__asdlc__list_tasks(sprint_id="SPRINT-01")  # Derived via PRD
```

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `project_id` | No | Project ID (auto-detected from cwd) |
| `status` | No | Filter: pending, in_progress, completed, blocked |
| `prd_id` | No | Filter by parent PRD |
| `sprint_id` | No | Filter by sprint (derived from PRD's sprint) |

## Output Format

The tool returns a structured response:

```json
{
  "status": "ok",
  "project_id": "my-project",
  "count": 5,
  "tasks": [
    {
      "id": "TASK-001",
      "title": "Implement authentication",
      "status": "pending",
      "priority": "high",
      "component": "auth-service",
      "prd_id": "feature-auth",
      "updated_at": "2025-01-26T10:00:00Z"
    }
  ]
}
```

## Display Format

Present tasks in a readable format:

```
Tasks Overview (5 total)

🔴 Pending (3):
  TASK-001  [High]   Implement authentication          [PRD: feature-auth]
  TASK-002  [High]   Add rate limiting                 [PRD: feature-auth]
  TASK-003  [Medium] Update documentation              [No PRD]

⏳ In Progress (1):
  TASK-004  [High]   Implement user registration       [PRD: feature-auth]

🚫 Blocked (1):
  TASK-005  [High]   Integrate payment API             [PRD: payments]

✅ Completed: Use --completed flag to show
```

## Sprint-Filtered View

When filtering by sprint, tasks are found via their parent PRD's sprint:

```
/sdlc:task-list --sprint SPRINT-01

Tasks in SPRINT-01 (derived via PRDs) - 4 tasks

Progress: ████████░░░░░░░░ 25% (1/4 completed)

🔴 Pending:
  TASK-001  [High] Implement authentication   [PRD: feature-auth]
  TASK-002  [High] Add rate limiting          [PRD: feature-auth]

⏳ In Progress:
  TASK-004  [High] Implement user registration [PRD: feature-auth]

🚫 Blocked:
  TASK-005  [High] Integrate payment API       [PRD: payments]
```

## Sprint Relationship

Tasks no longer have direct `sprint_id`. Sprint membership is derived:
- Task → PRD → Sprint

To see which sprint a task belongs to:
1. Look at the task's `prd_id`
2. Check that PRD's `sprint_id`

## Examples

```
/sdlc:task-list                         # All tasks
/sdlc:task-list --prd feature-auth      # Tasks under a PRD
/sdlc:task-list --sprint SPRINT-01      # Tasks via PRDs in sprint
/sdlc:task-list --status pending        # Only pending tasks
```