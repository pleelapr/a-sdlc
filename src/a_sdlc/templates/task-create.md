# /sdlc:task-create

## Purpose

Create a new task for the current project.

---

## Note: This Creates Persistent a-sdlc Tasks

This command creates **database-backed tasks**, not Claude Code internal tasks.

**a-sdlc tasks:**
- Stored in `~/.a-sdlc/content/{project_id}/tasks/{task_id}.md`
- Persist across sessions and restarts
- Linkable to PRDs and Sprints
- Syncable to Linear/Jira

**Do not use** Claude Code's `TaskCreate` or `TodoWrite` for project work items.

---

## Usage

Use the MCP tool to create a task:

```
mcp__asdlc__create_task(
    title="Implement user authentication",
    description="Add JWT-based authentication to the API",
    priority="high",
    component="auth-service",
    prd_id="feature-auth"  # Optional - task inherits sprint from PRD
)
```

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `title` | Yes | Task title |
| `description` | No | Detailed description |
| `project_id` | No | Project ID (auto-detected) |
| `prd_id` | No | Link to parent PRD (task inherits sprint from PRD) |
| `priority` | No | low, medium, high, critical (default: medium) |
| `component` | No | Component/module name |
| `data` | No | Additional structured data (JSON) |

## Output

```json
{
  "status": "created",
  "message": "Task created: TASK-001",
  "task": {
    "id": "TASK-001",
    "title": "Implement user authentication",
    "description": "Add JWT-based authentication to the API",
    "status": "pending",
    "priority": "high",
    "component": "auth-service",
    "prd_id": "feature-auth",
    "created_at": "2025-01-26T10:00:00Z"
  }
}
```

## Interactive Mode

When invoked without arguments, prompt for task details interactively.

**Component Suggestion from Architecture:**

Before prompting, check for codebase artifacts:

```
context = mcp__asdlc__get_context()
```

If `context.artifacts.available` includes `"architecture"`:

```
Read: .sdlc/artifacts/architecture.md
```

Parse the component names from the architecture document. When the user provides a task title and description, suggest the most relevant component based on keyword matching against component descriptions.

```
Task title: Fix login timeout bug
Priority [high/medium/low]: high

Suggested component based on architecture: auth-service
  (matches: authentication, login flows)
Component [auth-service]: <Enter to accept or type different>

PRD (optional): feature-auth
Description:
> The login process times out after 5 seconds...
```

If no artifacts are available, fall back to the standard prompt without suggestions:

```
Task title: Fix login timeout bug
Priority [high/medium/low]: high
Component (optional): auth-service
PRD (optional): feature-auth
Description:
> The login process times out after 5 seconds...
```

## Sprint via PRD

Tasks inherit sprint membership from their parent PRD:
1. Set task's `prd_id` to link to a PRD
2. If the PRD is assigned to a sprint, the task is in that sprint
3. To change a task's sprint, either:
   - Move the task to a different PRD
   - Change the PRD's sprint assignment

## Examples

```
# Create task interactively
/sdlc:task-create

# Create with PRD link (inherits sprint from PRD)
/sdlc:task-create --title "Implement FR-001" --prd feature-auth

# Create standalone task (no PRD, no sprint)
/sdlc:task-create --title "Fix bug" --priority high
```

## Related Commands

- `/sdlc:task-list` - View all tasks
- `/sdlc:task-start` - Start working on a task
- `/sdlc:task-complete` - Mark task as done
- `/sdlc:prd-split` - Generate tasks from PRD automatically