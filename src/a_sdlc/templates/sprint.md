# /sdlc:sprint - Sprint Management

Manage sprints for iteration-based progress tracking. Sprints contain PRDs, which contain tasks.

## Architecture

```
Sprint (SPRINT-001)
  └── PRD (feature-auth)
        ├── TASK-001
        ├── TASK-002
        └── TASK-003
```

**Key concept**: Tasks don't belong directly to sprints. Tasks belong to PRDs, and PRDs are assigned to sprints. This allows grouping related tasks under their requirements document.

## Available Subcommands

| Command | Description |
|---------|-------------|
| `/sdlc:sprint-create "<name>"` | Create a new sprint |
| `/sdlc:sprint-list` | List all sprints |
| `/sdlc:sprint-show <id>` | Show sprint details + PRDs + tasks |
| `/sdlc:sprint-start <id>` | Activate a sprint |
| `/sdlc:sprint-complete <id>` | Close a sprint |
| `/sdlc:sprint-run <id>` | Execute sprint tasks in parallel |

## Quick Start Workflow

1. **Create sprint**: `/sdlc:sprint-create "Auth Sprint"`
2. **Create or get PRD**: `/sdlc:prd-generate "Auth feature"` or use existing
3. **Assign PRD to sprint**:
   ```
   mcp__asdlc__manage_sprint_prds(action="add", prd_id="feature-auth", sprint_id="SPRINT-01")
   ```
4. **Generate tasks from PRD**: `/sdlc:prd-split "feature-auth"`
5. **View sprint**: `/sdlc:sprint-show SPRINT-01`
6. **Start sprint**: `/sdlc:sprint-start SPRINT-01`
7. **Run tasks**: `/sdlc:sprint-run SPRINT-01`
8. **Complete**: `/sdlc:sprint-complete SPRINT-01`

## Sprint Statuses

| Status | Description |
|--------|-------------|
| `planned` | Sprint created, not yet started |
| `active` | Sprint in progress |
| `completed` | Sprint finished |

## Assigning PRDs to Sprints

PRDs can be assigned to sprints using the MCP tool:

```
# Assign PRD to sprint
mcp__asdlc__manage_sprint_prds(action="add", prd_id="feature-auth", sprint_id="SPRINT-01")

# Remove PRD from sprint (move to backlog)
mcp__asdlc__manage_sprint_prds(action="remove", prd_id="feature-auth")

# List PRDs in a sprint
mcp__asdlc__get_sprint_prds(sprint_id="SPRINT-01")
```

## Task Inheritance

When you create tasks for a PRD that's assigned to a sprint:
- Tasks automatically "belong" to that sprint through their parent PRD
- Moving a PRD to a different sprint moves all its tasks too
- Tasks cannot be assigned directly to sprints

## Storage

All sprint data is stored in the SQLite database at `~/.a-sdlc/data.db`. No file-based storage is used.

## Notes

- Multiple sprints can be active simultaneously (no single-active restriction)
- Dependencies between tasks are respected during parallel execution
- Failed tasks are marked BLOCKED, other tasks continue
