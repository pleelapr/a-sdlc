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

Create task metadata, then write content to the returned file:

```
result = mcp__asdlc__create_task(
    title="Implement user authentication",
    priority="high",
    component="auth-service",
    prd_id="feature-auth"  # Optional - task inherits sprint from PRD
)
# Then write task content to the returned file_path:
Write(file_path=result["file_path"], content="<task description markdown>")
```

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `title` | Yes | Task title |
| `project_id` | No | Project ID (auto-detected) |
| `prd_id` | No | Link to parent PRD (task inherits sprint from PRD) |
| `priority` | No | low, medium, high, critical (default: medium) |
| `component` | No | Component/module name |
| `data` | No | Additional structured data (JSON) |

## Output

```json
{
  "status": "created",
  "message": "Task created: PROJ-T00001",
  "task": {
    "id": "PROJ-T00001",
    "title": "Implement user authentication",
    "status": "pending",
    "priority": "high",
    "component": "auth-service",
    "prd_id": "feature-auth",
    "created_at": "2025-01-26T10:00:00Z"
  },
  "file_path": "~/.a-sdlc/content/proj/tasks/PROJ-T00001.md"
}
```

## CRITICAL: Anti-Fluff Rules

**Every task field must reflect exactly what the user specified. Zero AI-embellished content.**

- **MUST NOT** expand the user's description with extra implementation details, edge cases, or technical notes they didn't mention
- **MUST NOT** add acceptance criteria, success metrics, or NFRs the user didn't specify
- **MUST NOT** suggest a higher priority than what the task content warrants
- **MUST NOT** add components, dependencies, or related tasks the user didn't ask for
- **MUST NOT** pad the description with boilerplate ("ensure proper error handling", "follow best practices", "add appropriate tests")
- **MUST** use the user's own words for title and description — do not rephrase or "improve" them
- **MUST** ask if information is missing rather than filling in blanks yourself

**If the user says "Fix login timeout bug", the task is about fixing the login timeout bug — not about refactoring the auth system, adding monitoring, or improving test coverage.**

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