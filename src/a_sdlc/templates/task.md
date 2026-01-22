# /sdlc:task - Task Management

Manage implementation tasks derived from requirements. Supports local storage and external integrations (Linear, GitHub Issues).

## Subcommands

| Command | Description |
|---------|-------------|
| `/sdlc:task split` | Split requirements into tasks |
| `/sdlc:task list` | List all tasks |
| `/sdlc:task show <id>` | Show task details |
| `/sdlc:task start <id>` | Mark task as in-progress |
| `/sdlc:task complete <id>` | Mark task as completed |
| `/sdlc:task create` | Manually create a task |
| `/sdlc:task link <id> <external-id>` | Link task to external system |

---

## /sdlc:task split

### Purpose

Decompose requirements into actionable implementation tasks, automatically detecting dependencies and affected components.

### Execution Steps

#### 1. Load Requirements

Read `.sdlc/requirements/current.md` and parse:
- All FR-XXX entries
- All NFR-XXX entries
- Acceptance criteria

#### 2. Load Architecture Context

Read `.sdlc/artifacts/architecture.md` to understand:
- Component boundaries
- File locations
- Existing patterns

#### 3. Decomposition Algorithm

For each requirement:

```python
def decompose_requirement(req, architecture):
    tasks = []

    # Identify affected components
    components = find_affected_components(req, architecture)

    for component in components:
        # Create implementation task
        tasks.append(Task(
            title=f"Implement {req.id} in {component.name}",
            requirement_id=req.id,
            component=component.name,
            files_to_modify=component.files,
            priority=req.priority
        ))

        # Create test task if testable
        if req.has_acceptance_criteria:
            tasks.append(Task(
                title=f"Test {req.id} - {component.name}",
                requirement_id=req.id,
                component=component.name,
                dependencies=[tasks[-1].id]
            ))

    return tasks
```

#### 4. Generate Task Files

For each task, create:

**`.sdlc/tasks/active/TASK-001.md`:**

```markdown
# TASK-001: [Task Title]

**Status:** pending
**Priority:** high
**Requirement:** FR-001
**Component:** auth-service
**Dependencies:** None

## Goal

[Clear statement of what needs to be accomplished]

## Implementation Context

### Files to Modify
- `src/auth/handlers.py`
- `src/auth/models.py`

### Key Requirements
- [Specific requirement from FR-001]
- [Technical constraint]

### Technical Notes
- [Pattern to follow from existing code]
- [Integration point]

## Implementation Steps

1. **Step 1:** [Description]
   ```python
   # Code hint or example
   ```

2. **Step 2:** [Description]
   ```python
   # Code hint or example
   ```

3. **Step 3:** [Description]

## Success Criteria

- [ ] [Criterion 1 from acceptance criteria]
- [ ] [Criterion 2]
- [ ] All tests pass
- [ ] No type errors

## Scope Constraint

Implement only the changes described above. Do not:
- Modify unrelated components
- Add features not in requirements
- Refactor existing code unless necessary
```

**`.sdlc/tasks/active/TASK-001.json`:**

```json
{
  "id": "TASK-001",
  "title": "Implement FR-001 in auth-service",
  "status": "pending",
  "priority": "high",
  "requirement_id": "FR-001",
  "component": "auth-service",
  "dependencies": [],
  "files_to_modify": ["src/auth/handlers.py"],
  "created_at": "2025-01-21T12:00:00Z"
}
```

#### 5. Sync to External System (if configured)

If Linear plugin is enabled:
- Create issues in Linear for each task
- Store Linear issue IDs in task metadata
- Provide links to external issues

#### 6. Output

```
Tasks Generated!

From: .sdlc/requirements/current.md
Requirements processed: 8

Tasks created:
  TASK-001: Implement FR-001 in auth-service [High]
  TASK-002: Test FR-001 - auth-service [High]
  TASK-003: Implement FR-002 in user-service [Medium]
  TASK-004: Implement FR-003 in api-gateway [Medium]
  ...

Total: 12 tasks
Dependencies detected: 4

Location: .sdlc/tasks/active/

Next step: Run /sdlc:task start TASK-001 to begin work
```

---

## /sdlc:task list

### Purpose

Display all tasks with status and priority.

### Output

```
Tasks Overview

Active (5):
  🔴 TASK-001  [High]   Implement FR-001 in auth-service
  🔴 TASK-002  [High]   Test FR-001 - auth-service
  🟡 TASK-003  [Medium] Implement FR-002 in user-service
  🟡 TASK-004  [Medium] Implement FR-003 in api-gateway
  🟢 TASK-005  [Low]    Update documentation

In Progress (1):
  ⏳ TASK-006  [High]   Implement FR-004 in data-layer

Blocked (1):
  🚫 TASK-007  [High]   Integrate with external API
     Reason: Waiting for API credentials

Completed (3):
  ✅ TASK-008  Completed 2025-01-20
  ✅ TASK-009  Completed 2025-01-20
  ✅ TASK-010  Completed 2025-01-21
```

### Filters

```
/sdlc:task list                    # All tasks
/sdlc:task list --active           # Only pending/in-progress
/sdlc:task list --completed        # Only completed
/sdlc:task list --priority high    # Only high priority
/sdlc:task list --component auth   # Only auth component
```

---

## /sdlc:task show

### Purpose

Display detailed task information.

### Usage

```
/sdlc:task show TASK-001
```

### Output

Shows the full content of `TASK-001.md`.

---

## /sdlc:task start

### Purpose

Mark a task as in-progress and set it as the active task.

### Execution

1. Validate task exists and is pending
2. Check dependencies are completed
3. Update task status to `in_progress`
4. Store as active task in Serena memory: `sdlc_active_task`

### Output

```
Task Started: TASK-001

"Implement FR-001 in auth-service"

Files to modify:
  - src/auth/handlers.py
  - src/auth/models.py

Implementation steps:
  1. Add authentication middleware
  2. Create user validation logic
  3. Implement token generation

Good luck! Run /sdlc:task complete TASK-001 when done.
```

---

## /sdlc:task complete

### Purpose

Mark a task as completed and archive it.

### Execution

1. Validate task exists and is in-progress
2. Update status to `completed`
3. Set `completed_at` timestamp
4. Move from `active/` to `completed/`
5. Sync to external system if configured
6. Clear active task from memory

### Output

```
Task Completed: TASK-001 ✓

"Implement FR-001 in auth-service"

Duration: 2h 15m
Archived to: .sdlc/tasks/completed/TASK-001.md

Remaining tasks: 11
Next suggested: TASK-002 (depends on this task)
```

---

## /sdlc:task create

### Purpose

Manually create a task without deriving from requirements.

### Interactive Prompts

```
Task title: Fix login timeout bug
Priority [high/medium/low]: high
Component (optional): auth-service
Related requirement (optional): FR-001
Description:
> The login process times out after 5 seconds...

Files to modify (comma-separated):
> src/auth/login.py, src/auth/config.py

Success criteria (one per line, empty to finish):
> Login completes within 30 seconds
> Timeout is configurable
>
```

### Output

```
Task Created: TASK-012

Title: Fix login timeout bug
Priority: high
Component: auth-service

Location: .sdlc/tasks/active/TASK-012.md
```

---

## /sdlc:task link

### Purpose

Link a local task to an external system (Linear, GitHub).

### Usage

```
/sdlc:task link TASK-001 ENG-123
```

### Execution

1. Validate local task exists
2. Store external ID in task metadata
3. Fetch external URL (if possible)
4. Update task file with external reference

### Output

```
Task Linked!

Local: TASK-001
External: ENG-123
URL: https://linear.app/team/issue/ENG-123

Future updates will sync to Linear.
```

---

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
/sdlc:task split                     # Create tasks from requirements
/sdlc:task list                      # Show all tasks
/sdlc:task list --active             # Show only active
/sdlc:task show TASK-001             # Show task details
/sdlc:task start TASK-001            # Begin working on task
/sdlc:task complete TASK-001         # Mark as done
/sdlc:task create                    # Manual task creation
/sdlc:task link TASK-001 ENG-123     # Link to Linear
```

## Notes

- Tasks are stored as both Markdown (human-readable) and JSON (machine-parseable)
- Dependencies are checked before starting a task
- Only one task can be in-progress at a time (enforced)
- Completed tasks are archived, not deleted
