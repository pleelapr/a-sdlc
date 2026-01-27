# /sdlc:task-split

## Purpose

Decompose requirements into actionable implementation tasks, automatically detecting dependencies and affected components.

## Syntax

```
/sdlc:task-split [--sprint <sprint-id>]
```

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `--sprint` | No | Assign all generated tasks to sprint (e.g., SPRINT-001) |

## Execution Steps

### 1. Load Requirements

Read `.sdlc/requirements/current.md` and parse:
- All FR-XXX entries
- All NFR-XXX entries
- Acceptance criteria

### 2. Load Architecture Context

Read `.sdlc/artifacts/architecture.md` to understand:
- Component boundaries
- File locations
- Existing patterns

### 3. Decomposition Algorithm

For each requirement:

```python
def decompose_requirement(req, architecture, sprint_id=None):
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
            priority=req.priority,
            sprint_id=sprint_id  # Assign to sprint if provided
        ))

        # Create test task if testable
        if req.has_acceptance_criteria:
            tasks.append(Task(
                title=f"Test {req.id} - {component.name}",
                requirement_id=req.id,
                component=component.name,
                dependencies=[tasks[-1].id],
                sprint_id=sprint_id  # Assign to sprint if provided
            ))

    return tasks
```

### 4. Generate Task Files

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
  "sprint_id": "SPRINT-001",
  "created_at": "2025-01-21T12:00:00Z"
}
```

### 5. Sync to External System (if configured)

If Linear plugin is enabled:
- Create issues in Linear for each task
- Store Linear issue IDs in task metadata
- Provide links to external issues

### 6. Output

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

Next step: Run /sdlc:task-start TASK-001 to begin work
```
