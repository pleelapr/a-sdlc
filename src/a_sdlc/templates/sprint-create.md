# /sdlc:sprint-create

## Purpose

Create a new sprint for grouping and executing tasks together.

## Usage

Use the MCP tool to create a sprint:

```
mcp__asdlc__create_sprint(
    title="Week 4 - Auth Feature",
    goal="Complete OAuth implementation"
)
```

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `title` | Yes | Sprint name |
| `goal` | No | Sprint objective/goal statement |
| `project_id` | No | Project ID (auto-detected) |

## Output

```json
{
  "status": "created",
  "message": "Sprint created: SPRINT-01",
  "sprint": {
    "id": "SPRINT-01",
    "title": "Week 4 - Auth Feature",
    "goal": "Complete OAuth implementation",
    "status": "planned",
    "created_at": "2025-01-26T12:00:00Z",
    "task_counts": {}
  }
}
```

## Display Format

```
Sprint Created: SPRINT-01

Title: Week 4 - Auth Feature
Status: planned
Goal: Complete OAuth implementation

Next steps:
- Add tasks: /sdlc:task-create --sprint SPRINT-01
- Or split PRD: /sdlc:prd-split "feature" --sprint SPRINT-01
- Start sprint: /sdlc:sprint-start SPRINT-01
```

## Sprint Lifecycle

1. **planned** - Sprint created, adding tasks
2. **active** - Sprint started, work in progress
3. **completed** - All work done, sprint closed

## Examples

```
# Simple sprint
/sdlc:sprint-create "Auth Sprint"

# Sprint with goal
/sdlc:sprint-create "Auth Sprint" --goal "Implement OAuth flow"
```

## Related Commands

- `/sdlc:sprint-list` - View all sprints
- `/sdlc:sprint-start` - Activate a sprint
- `/sdlc:sprint-complete` - Complete a sprint
- `/sdlc:sprint-run` - Execute sprint tasks