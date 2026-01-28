# /sdlc:sprint-run

## Purpose

Execute sprint tasks in parallel using multiple Claude Code Task agents. Independent tasks run concurrently while respecting dependency chains.

## Syntax

```
/sdlc:sprint-run <sprint-id> [--parallel <n>] [--dry-run] [--sync]
```

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `sprint-id` | Yes | Sprint ID to execute (e.g., SPRINT-001) |
| `--parallel` | No | Max concurrent agents (default: 3) |
| `--dry-run` | No | Show execution plan without running |
| `--sync` | No | Sync status to external system as tasks complete |

## Execution Steps

### 1. Validate Sprint

1. Use `mcp__asdlc__get_sprint(sprint_id)` to get sprint details
2. Verify status is ACTIVE
3. Use `mcp__asdlc__get_sprint_tasks(sprint_id)` to load all tasks (derived via PRDs)

### 2. Build Dependency Graph

Categorize tasks:
- **Ready**: No dependencies OR all dependencies completed
- **Blocked**: Has incomplete dependencies
- **Completed**: Already done (skip)
- **In Progress**: Currently being worked on

```python
def categorize_tasks(tasks):
    completed_ids = {t.id for t in tasks if t.status == "completed"}

    ready = []
    blocked = []

    for task in tasks:
        if task.status == "completed":
            continue
        if task.status == "in_progress":
            continue  # Already running

        unmet = [d for d in task.dependencies if d not in completed_ids]
        if unmet:
            blocked.append((task, unmet))
        else:
            ready.append(task)

    return ready, blocked
```

### 3. Display Execution Plan

```
Sprint: SPRINT-001 - Week 4 Auth

Execution Plan:
  Ready for parallel execution (3 tasks):
    TASK-001: Set up OAuth config
    TASK-002: Create login endpoint
    TASK-003: Add user model fields

  Blocked (will unblock as dependencies complete):
    TASK-004: Implement token refresh
      └─ Waiting on: TASK-001
    TASK-005: Add logout endpoint
      └─ Waiting on: TASK-002

Max parallel agents: 3
Estimated execution batches: 2

Proceed with execution? [Y/n]
```

### 4. Launch Parallel Agents

**CRITICAL**: Use Claude Code's Task tool with **multiple tool calls in a single message** to achieve parallelism.

For each batch of ready tasks (up to max_parallel):

```
Launch agents in parallel by including multiple Task tool calls in ONE message:

Task(
  description="Execute TASK-001",
  prompt="Execute task TASK-001: Set up OAuth config. Fetch task details using mcp__asdlc__get_task(task_id='TASK-001'). Follow the implementation steps exactly. When complete, use mcp__asdlc__update_task to set status to completed.",
  subagent_type="general-purpose",
  run_in_background=true
)

Task(
  description="Execute TASK-002",
  prompt="Execute task TASK-002: Create login endpoint. Fetch task details using mcp__asdlc__get_task(task_id='TASK-002'). Follow the implementation steps exactly. When complete, use mcp__asdlc__update_task to set status to completed.",
  subagent_type="general-purpose",
  run_in_background=true
)

Task(
  description="Execute TASK-003",
  prompt="Execute task TASK-003: Add user model fields. Fetch task details using mcp__asdlc__get_task(task_id='TASK-003'). Follow the implementation steps exactly. When complete, use mcp__asdlc__update_task to set status to completed.",
  subagent_type="general-purpose",
  run_in_background=true
)
```

### 5. Monitor Progress

Display real-time progress dashboard:

```
┌─────────────────────────────────────────────────────────────┐
│  Sprint: SPRINT-001 - Week 4 Auth                           │
│  Tasks: 5 total, 3 running, 2 blocked                       │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  [Agent 1] TASK-001: Set up OAuth config         🔄 Running │
│  [Agent 2] TASK-002: Create login endpoint       🔄 Running │
│  [Agent 3] TASK-003: Add user model fields       🔄 Running │
│  [Queued]  TASK-004: Implement token refresh     ⏳ Blocked │
│            (depends on: TASK-001)                            │
│  [Queued]  TASK-005: Add logout endpoint         ⏳ Blocked │
│            (depends on: TASK-002)                            │
│                                                              │
│  Progress: ████████░░░░░░░░░░░░ 40%                         │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### 6. Handle Completion Events

When an agent completes:

1. Check task result via TaskOutput tool
2. If success:
   - Mark task as COMPLETED
   - Check if any blocked tasks are now unblocked
   - Launch newly unblocked tasks (up to max_parallel)
3. If failure:
   - Mark task as BLOCKED with failure reason
   - Log error details
   - **Continue with other tasks** (don't stop the sprint)

```
[Agent 1] TASK-001: ✅ Completed (3m 24s)
[Agent 4] TASK-004: 🔄 Starting (unblocked by TASK-001)
```

### 7. Handle Failures

When a task fails:

```
[Agent 2] TASK-002: ❌ Failed

Error: Unable to create login endpoint - missing auth middleware

Action Taken:
  - Task marked as BLOCKED
  - Dependent tasks (TASK-005) remain blocked
  - Continuing with other independent tasks

To retry: /sdlc:task-start TASK-002
```

Update task:
```json
{
  "status": "blocked",
  "blocked_reason": "Failed during sprint-run: Unable to create login endpoint"
}
```

### 8. Generate Summary

When all tasks complete or are blocked:

```
Sprint Run Complete: SPRINT-001

Duration: 12m 45s
Parallel Efficiency: 2.3x (vs sequential)

Results:
  ✅ Completed: 4 tasks
  ❌ Blocked: 1 task (failed during execution)

Completed Tasks:
  ✅ TASK-001: Set up OAuth config (3m 24s)
  ✅ TASK-003: Add user model fields (2m 15s)
  ✅ TASK-004: Implement token refresh (4m 30s)
  ✅ TASK-005: Add logout endpoint (2m 36s)

Blocked Tasks:
  ❌ TASK-002: Create login endpoint
     Reason: Failed during sprint-run: Unable to create login endpoint
     To retry: /sdlc:task-start TASK-002

Next Steps:
  - Fix blocked task: /sdlc:task-show TASK-002
  - Complete sprint: /sdlc:sprint-complete SPRINT-001
```

### 9. External System Sync (with --sync flag)

When `--sync` is enabled and sprint is linked to an external system:

**On task completion:**
```python
if sync_enabled and task.external_id:
    # Update external issue status
    if task.status == TaskStatus.COMPLETED:
        update_external_issue(task.external_id, state="Done")
    elif task.status == TaskStatus.BLOCKED:
        update_external_issue(task.external_id, state="Blocked")

    # Update sprint mapping sync timestamp
    update_sprint_mapping_status(
        sprint_id,
        sync_status=SyncStatus.SYNCED,
        last_synced_at=datetime.now()
    )
```

**Progress sync:**
```
[Sync] TASK-001 completed → Linear ENG-123 updated to "Done"
[Sync] TASK-002 blocked → Linear ENG-124 updated to "Blocked"
```

**Final sync summary:**
```
External Sync Summary (Linear ENG-Q1-2025):
  ✅ 4 issues updated to "Done"
  ⚠️ 1 issue updated to "Blocked"

  Cycle progress: 40% → 80%
  Last synced: 2025-01-26T15:30:00Z
```

**Note:** If external sync fails for any task, the local execution continues and a warning is logged. Failed syncs can be retried with `/sdlc:sprint-sync-to`.

## Execution Algorithm (Pseudocode)

```python
def run_sprint(sprint_id: str, max_parallel: int = 3):
    sprint = load_sprint(sprint_id)  # mcp__asdlc__get_sprint()
    tasks = get_sprint_tasks(sprint_id)  # mcp__asdlc__get_sprint_tasks() - derived via PRDs

    # Skip completed tasks
    pending_tasks = [t for t in tasks if t.status != "completed"]

    # Build dependency graph
    ready, blocked = categorize_tasks(pending_tasks)

    active_agents = {}  # task_id -> agent_id
    results = {}  # task_id -> success/failure

    while ready or active_agents:
        # Launch agents for ready tasks (up to max_parallel)
        while len(active_agents) < max_parallel and ready:
            task = ready.pop(0)

            # Mark task as in_progress
            update_task_status(task.id, "in_progress")

            # Launch agent (use Task tool with run_in_background=true)
            agent_id = launch_task_agent(task)
            active_agents[task.id] = agent_id

            display_progress()

        # Wait for any agent to complete (check via TaskOutput)
        completed_task_id, success, error = wait_for_any_completion(active_agents)
        del active_agents[completed_task_id]

        if success:
            results[completed_task_id] = "completed"
            update_task_status(completed_task_id, "completed")

            # Check if any blocked tasks are now unblocked
            for task, unmet_deps in blocked[:]:
                if all(d in results and results[d] == "completed" for d in unmet_deps):
                    blocked.remove((task, unmet_deps))
                    ready.append(task)
        else:
            results[completed_task_id] = "blocked"
            update_task_status(completed_task_id, "blocked", error)

        display_progress()

    generate_sprint_report(sprint_id, results)
```

## Examples

```
# Run sprint with default parallelism (3)
/sdlc:sprint-run SPRINT-001

# Run with 5 parallel agents
/sdlc:sprint-run SPRINT-001 --parallel 5

# Preview execution plan without running
/sdlc:sprint-run SPRINT-001 --dry-run

# Run with external system sync (for linked sprints)
/sdlc:sprint-run SPRINT-001 --sync

# Run with high parallelism and sync
/sdlc:sprint-run SPRINT-001 --parallel 5 --sync
```

## Important Notes

- **Parallel Execution**: All independent tasks run simultaneously
- **Dependency Respect**: Blocked tasks wait for their dependencies
- **Failure Isolation**: One failed task doesn't stop others
- **Progress Tracking**: Real-time visibility into execution
- **Resumable**: Run again to continue any incomplete work
