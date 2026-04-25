# /sdlc:prd - PRD Management

Product Requirements Document ingestion and management pipeline.

## Available Subcommands

| Command | Description |
|---------|-------------|
| `/sdlc:prd-generate "<desc>"` | Interactive PRD creation |
| `/sdlc:prd-list` | List all PRDs |
| `/sdlc:prd-update "<id>"` | Update existing PRD |
| `/sdlc:prd-split "<id>"` | Generate tasks from PRD |

## Usage

This is a command group. Use one of the subcommands above.

Example:
```
/sdlc:prd-generate "Add OAuth authentication"
/sdlc:prd-list
/sdlc:prd-split "feature-auth"
```

## Quick Start

1. **Create PRD**: `/sdlc:prd-generate "your feature description"`
2. **Assign to Sprint**: `mcp__asdlc__manage_sprint_prds(action="add", prd_id="feature-auth", sprint_id="SPRINT-01")`
3. **View PRDs**: `/sdlc:prd-list`
4. **Generate tasks**: `/sdlc:prd-split "<prd-id>"`

## Sprint Integration

PRDs can optionally be assigned to a sprint:
- **Backlog PRDs**: No sprint assigned (sprint_id = null)
- **Sprint PRDs**: Assigned to a sprint for execution

When a PRD is in a sprint, all its tasks are considered part of that sprint.

### Managing Sprint Assignment

```
# Assign PRD to sprint
mcp__asdlc__manage_sprint_prds(action="add", prd_id="feature-auth", sprint_id="SPRINT-01")

# Remove from sprint (move to backlog)
mcp__asdlc__manage_sprint_prds(action="remove", prd_id="feature-auth")

# List PRDs in a sprint
mcp__asdlc__get_sprint_prds("SPRINT-01")

# List backlog PRDs
mcp__asdlc__list_prds(sprint_id="")
```

## Hierarchy

```
Sprint (optional)
  └── PRD (can be backlog)
        └── Task (inherits sprint from PRD)
```

## Storage

PRDs are stored in the database with:
- `id`: Slug identifier
- `title`: Display name
- `content`: Markdown content
- `status`: draft, ready, split, completed
- `sprint_id`: Optional sprint assignment

## Notes

- PRDs can exist without a sprint (backlog)
- Tasks inherit their sprint from their parent PRD
- External imports (Linear/Jira) create PRDs, not tasks
