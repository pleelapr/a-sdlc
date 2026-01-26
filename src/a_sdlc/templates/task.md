# /sdlc:task - Task Management

Manage implementation tasks derived from requirements.

## Available Subcommands

| Command | Description |
|---------|-------------|
| `/sdlc:task-split` | Split requirements into tasks |
| `/sdlc:task-list` | List all tasks |
| `/sdlc:task-show <id>` | Show task details |
| `/sdlc:task-start <id>` | Mark task as in-progress |
| `/sdlc:task-complete <id>` | Mark task as completed |
| `/sdlc:task-create` | Manually create a task |
| `/sdlc:task-link <id> <external-id>` | Link to external system |

## Usage

This is a command group. Use one of the subcommands above.

Example:
```
/sdlc:task-list --active
/sdlc:task-start TASK-001
```

## Quick Start

1. **Generate tasks from PRD**: `/sdlc:prd-split "feature-name"`
2. **View tasks**: `/sdlc:task-list`
3. **Start working**: `/sdlc:task-start TASK-001`
4. **Complete task**: `/sdlc:task-complete TASK-001`

## Configuration

Task behavior is controlled by `.sdlc/config.yaml`:

```yaml
tasks:
  id_prefix: "TASK"           # Prefix for task IDs
  auto_dependencies: true     # Auto-detect dependencies

plugins:
  tasks:
    provider: "local"         # local | linear | github
    linear:
      team_id: "ENG"
      sync_on_create: true
      sync_on_complete: true
```

## Examples

```
/sdlc:task-split                     # Create tasks from requirements
/sdlc:task-list                      # Show all tasks
/sdlc:task-list --active             # Show only active
/sdlc:task-show TASK-001             # Show task details
/sdlc:task-start TASK-001            # Begin working on task
/sdlc:task-complete TASK-001         # Mark as done
/sdlc:task-create                    # Manual task creation
/sdlc:task-link TASK-001 ENG-123     # Link to Linear
```

## Notes

- Tasks are stored as both Markdown (human-readable) and JSON (machine-parseable)
- Dependencies are checked before starting a task
- Only one task can be in-progress at a time (enforced)
- Completed tasks are archived, not deleted
