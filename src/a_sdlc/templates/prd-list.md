# /sdlc:prd-list

## Purpose

List all PRDs for the current project.

## Usage

Use the MCP tool to list PRDs:

```
mcp__asdlc__list_prds()
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
  "prds": [
    {
      "id": "feature-auth",
      "title": "User Authentication System",
      "status": "ready",
      "version": "1.0.0",
      "updated_at": "2025-01-26T10:00:00Z"
    },
    {
      "id": "feature-dashboard",
      "title": "Analytics Dashboard",
      "status": "draft",
      "version": "0.1.0",
      "updated_at": "2025-01-25T14:30:00Z"
    }
  ]
}
```

## Display Format

```
PRDs Overview (3 total)

📋 Ready (1):
  feature-auth          "User Authentication System"       v1.0.0

📝 Draft (2):
  feature-dashboard     "Analytics Dashboard"              v0.1.0
  feature-payments      "Payment Integration"              v0.1.0
```

## Get Full PRD

For full content, use:

```
mcp__asdlc__get_prd(prd_id="feature-auth")
```

## Examples

```
/sdlc:prd-list                  # All PRDs
```

## Related Commands

- `/sdlc:prd` - View PRD details
- `/sdlc:prd-generate` - Create new PRD
- `/sdlc:prd-split` - Generate tasks from PRD