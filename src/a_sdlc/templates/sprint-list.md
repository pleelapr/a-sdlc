# /sdlc:sprint-list

## Purpose

Display all sprints with status and task counts.

## Usage

Use the MCP tool to list sprints:

```
mcp__asdlc__list_sprints()
```

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `project_id` | No | Project ID (auto-detected from cwd) |

## Output

```json
{
  "status": "ok",
  "project_id": "my-project",
  "count": 3,
  "sprints": [
    {
      "id": "SPRINT-02",
      "title": "Week 5 - API Integration",
      "status": "active",
      "created_at": "2025-01-27T10:00:00Z",
      "started_at": "2025-01-27T10:00:00Z",
      "completed_at": null
    }
  ]
}
```

## Display Format

```
Sprints Overview (3 total)

🏃 Active (1):
  SPRINT-02  "Week 5 - API Integration"
    Started: 2025-01-27

📋 Planned (1):
  SPRINT-03  "Week 6 - Testing"

✅ Completed (1):
  SPRINT-01  "Week 4 - Auth Feature"
    Completed: 2025-01-26
```

## Get Sprint Details

For task counts and full details, use:

```
mcp__asdlc__get_sprint(sprint_id="SPRINT-02")
```

## Examples

```
/sdlc:sprint-list               # All sprints
```

## Related Commands

- `/sdlc:sprint-show` - View sprint details
- `/sdlc:sprint-create` - Create new sprint
- `/sdlc:sprint-start` - Activate sprint