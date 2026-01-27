# /sdlc:init - Initialize SDLC for Project

Initialize a-sdlc for the current project. This registers the project in the a-sdlc database and sets up the foundation for task, PRD, and sprint management.

## Quick Start

Use the MCP tool to initialize:

```
mcp__asdlc__init_project()
```

This will:
1. Detect the project name from the current directory
2. Register the project in the a-sdlc database
3. Return the project context

## Optional: Create Local Artifacts Directory

If you want to store codebase documentation artifacts (architecture, data-model, etc.) in the repo, create the `.sdlc/artifacts/` directory:

```
mkdir -p .sdlc/artifacts
```

Add to `.gitignore`:
```
# a-sdlc artifacts (optional - keep if you want to track documentation)
# .sdlc/artifacts/
```

## MCP Tools Available

After initialization, the following MCP tools are available:

### Context & Navigation
- `mcp__asdlc__get_context()` - Get current project summary
- `mcp__asdlc__list_projects()` - List all known projects
- `mcp__asdlc__switch_project(project_id)` - Change active project

### PRD Management
- `mcp__asdlc__list_prds()` - List PRDs
- `mcp__asdlc__get_prd(prd_id)` - Get full PRD content
- `mcp__asdlc__create_prd(title, content)` - Create new PRD
- `mcp__asdlc__update_prd(prd_id, ...)` - Update PRD
- `mcp__asdlc__delete_prd(prd_id)` - Delete PRD

### Task Management
- `mcp__asdlc__list_tasks()` - List tasks (filterable)
- `mcp__asdlc__get_task(task_id)` - Get task details
- `mcp__asdlc__create_task(title, description, ...)` - Create task
- `mcp__asdlc__update_task(task_id, ...)` - Update task
- `mcp__asdlc__start_task(task_id)` - Mark as in_progress
- `mcp__asdlc__complete_task(task_id)` - Mark as completed
- `mcp__asdlc__block_task(task_id, reason)` - Mark as blocked
- `mcp__asdlc__delete_task(task_id)` - Delete task

### Sprint Management
- `mcp__asdlc__list_sprints()` - List sprints
- `mcp__asdlc__get_sprint(sprint_id)` - Get sprint with tasks
- `mcp__asdlc__create_sprint(title, goal)` - Create sprint
- `mcp__asdlc__start_sprint(sprint_id)` - Activate sprint
- `mcp__asdlc__complete_sprint(sprint_id)` - Complete sprint
- `mcp__asdlc__add_tasks_to_sprint(sprint_id, task_ids)` - Add tasks
- `mcp__asdlc__remove_tasks_from_sprint(sprint_id, task_ids)` - Remove tasks

## Output

```
Project initialized: my-project

Project ID: my-project
Path: /path/to/my-project

Next steps:
1. Create a PRD: /sdlc:prd-generate "Feature description"
2. Create a sprint: /sdlc:sprint-create "Sprint 1"
3. View tasks: /sdlc:task-list
```

## Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `name` | Optional project name | Folder name |

## Examples

```
/sdlc:init                    # Initialize with default name
/sdlc:init "My App"          # Initialize with custom name
```

## Notes

- All data is stored in user-level SQLite database (`~/.a-sdlc/data.db`)
- No files are created in the repository (except optional artifacts)
- Data persists across Claude Code sessions