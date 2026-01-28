# /sdlc:prd-split

## Purpose

Break down a Product Requirements Document (PRD) into actionable development tasks using a **two-phase approach** that ensures reliable persistence.

## Usage

```
/sdlc:prd-split "<prd_id>" [options]
```

**Arguments:**
- `prd_id` - ID of PRD to split (e.g., "feature-auth")

**Options:**
- `--granularity <level>` - Task detail: coarse, medium, fine (default: medium)

## Examples

List available PRDs first:
```
/sdlc:prd-list
```

Split PRD with default options:
```
/sdlc:prd-split "feature-auth"
```

Fine-grained tasks:
```
/sdlc:prd-split "feature-auth" --granularity fine
```

## Two-Phase Execution

This skill uses a two-phase approach to ensure tasks are always persisted, even if the session is interrupted.

### Phase 1: Draft & Refine (Interactive)

1. **Get PRD content:**
   ```
   mcp__asdlc__get_prd(prd_id="<prd_id>")
   ```

2. **Analyze PRD and generate task breakdown:**
   - Read requirements from PRD content
   - Break down into logical, implementable tasks
   - Consider dependencies between tasks
   - Apply granularity level (coarse/medium/fine)

3. **Present task breakdown to user:**
   Display the proposed tasks in a clear format:
   ```
   ## Proposed Tasks for PRD: <prd_id>

   | # | Title | Priority | Component |
   |---|-------|----------|-----------|
   | 1 | Set up OAuth config | high | auth |
   | 2 | Implement login flow | high | auth |
   | 3 | Add logout endpoint | medium | auth |

   **Total: X tasks**

   Would you like to:
   - Approve and create these tasks
   - Modify the breakdown (add/remove/change tasks)
   - Cancel
   ```

4. **Allow refinement:**
   - User can discuss and refine task details through chat
   - Adjust priorities, components, or descriptions
   - Add or remove tasks as needed
   - Iterate until user is satisfied

### Phase 2: Commit (Atomic)

5. **Once user approves, create all tasks atomically:**
   ```
   mcp__asdlc__split_prd(
       prd_id="<prd_id>",
       task_specs=[
           {"title": "Set up OAuth config", "priority": "high", "component": "auth", "description": "..."},
           {"title": "Implement login flow", "priority": "high", "component": "auth", "description": "..."},
           {"title": "Add logout endpoint", "priority": "medium", "component": "auth", "description": "..."}
       ]
   )
   ```

   This single MCP call:
   - Creates all tasks in the database
   - Links them to the PRD
   - Updates PRD status to "split"
   - Ensures atomic persistence (all or nothing)

6. **Display created tasks summary:**
   ```
   ## Tasks Created

   PRD '<prd_id>' has been split into X tasks:

   | ID | Title | Priority | Component |
   |----|-------|----------|-----------|
   | TASK-001 | Set up OAuth config | high | auth |
   | TASK-002 | Implement login flow | high | auth |
   | TASK-003 | Add logout endpoint | medium | auth |

   PRD status updated to: split

   **Next steps:**
   - View tasks: /sdlc:task-list
   - See task details: /sdlc:task-show TASK-001
   - Start working: /sdlc:task-start TASK-001
   ```

## Task Specification Format

Each task in `task_specs` should include:

| Field | Required | Description |
|-------|----------|-------------|
| `title` | Yes | Short descriptive title |
| `description` | No | Detailed task description |
| `priority` | No | low, medium, high, critical (default: medium) |
| `component` | No | Target component/module |
| `dependencies` | No | List of task IDs this task depends on |

## Granularity Levels

**Coarse (3-5 tasks):**
- High-level feature chunks
- Good for initial planning or simple features

**Medium (5-10 tasks):**
- Balanced breakdown
- Default and recommended for most PRDs

**Fine (10-20 tasks):**
- Detailed implementation steps
- Good for complex features or junior developers

## Important Notes

1. **Atomic Persistence:** The `split_prd` MCP call creates all tasks in a single transaction. Even if the session is interrupted after this call, the tasks are safely stored.

2. **User Approval Required:** Always wait for explicit user approval before calling `split_prd`. This allows refinement and prevents accidental task creation.

3. **PRD Status:** After successful split, the PRD status is automatically updated to "split".

4. **No Implementation:** This skill only creates task records. It does NOT:
   - Implement any code
   - Create source files
   - Modify the codebase
   - Install dependencies

## Common Issues

**PRD not found:**
```
Error: PRD not found: feature-auth
```
Solution: Run `/sdlc:prd-list` to see available PRDs, or create one with `/sdlc:prd-generate`.

**No project context:**
```
Error: No project context. Run /sdlc:init first.
```
Solution: Initialize the project with `/sdlc:init`.

**Empty task specs:**
```
Error: No task specifications provided
```
Solution: Generate at least one task from the PRD analysis.
