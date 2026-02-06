# /sdlc:sprint-run

## Purpose

Execute sprint tasks in parallel using multiple Claude Code Task agents. Automatically detects whether the sprint has **one PRD** (simple mode) or **multiple PRDs** (isolated mode with git worktrees). Independent tasks run concurrently while respecting dependency chains.

---

## Agent Execution vs Task Management

This skill launches Claude Code agents to execute a-sdlc tasks. Key distinction:

- **Agent = Execution unit** (launched via Claude Code's `Task` tool)
- **a-sdlc Task = Work item** (retrieved/updated via `mcp__asdlc__*` tools)

**Each agent MUST:**
1. Call `mcp__asdlc__get_task(task_id)` to fetch task details
2. Execute the implementation steps from the task content
3. Call `mcp__asdlc__update_task(task_id, status="completed")` when done

**Do NOT** create intermediate Claude Code tasks (TodoWrite/TaskCreate). The a-sdlc task IS the work item.

---

## Syntax

```
/sdlc:sprint-run <sprint-id> [--parallel <n>] [--dry-run] [--sync] [--base-branch <branch>]
```

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `sprint-id` | Yes | Sprint ID to execute (e.g., PROJ-S0001) |
| `--parallel` | No | Max concurrent agents (default: 3) |
| `--dry-run` | No | Show execution plan without running |
| `--sync` | No | Sync status to external system as tasks complete |
| `--base-branch` | No | Branch to base worktrees on (multi-PRD mode only, default: current HEAD) |

---

## Execution Steps

### 1. Validate Sprint & Detect Mode

1. Use `mcp__asdlc__get_sprint(sprint_id)` to get sprint details
2. Verify status is ACTIVE
3. Use `mcp__asdlc__get_sprint_tasks(sprint_id, group_by_prd=True)` to load tasks grouped by PRD
4. **Detect execution mode**:
   - **1 PRD** → **Simple mode**: Run tasks directly in the working directory (same as before)
   - **2+ PRDs** → **Isolated mode**: Create a git worktree per PRD for full filesystem/branch isolation

```
Sprint: PROJ-S0001 - Auth Sprint

PRD count: 2 → Using ISOLATED MODE (git worktrees)

  PROJ-P0001 (Auth Feature): 3 tasks
  PROJ-P0002 (User Profile): 2 tasks
```

If only 1 PRD is detected, skip ahead to **Step 3** (Simple Mode).

---

## Simple Mode (1 PRD)

When the sprint has a single PRD, tasks run directly in the current working directory with no worktree overhead.

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
Sprint: PROJ-S0001 - Week 4 Auth
Mode: Simple (1 PRD)

Execution Plan:
  Ready for parallel execution (3 tasks):
    PROJ-T00001: Set up OAuth config
    PROJ-T00002: Create login endpoint
    PROJ-T00003: Add user model fields

  Blocked (will unblock as dependencies complete):
    PROJ-T00004: Implement token refresh
      └─ Waiting on: PROJ-T00001
    PROJ-T00005: Add logout endpoint
      └─ Waiting on: PROJ-T00002

Max parallel agents: 3
Estimated execution batches: 2

Proceed with execution? [Y/n]
```

### 3.5. Load Codebase Context for Agents

Before launching task agents, read project artifacts to build a shared context summary that each agent receives:

```
context = mcp__asdlc__get_context()
```

If `context.artifacts.scan_status` is `"complete"` or `"partial"`:

```
Read: .sdlc/artifacts/codebase-summary.md    → Tech stack, conventions, main patterns
Read: .sdlc/artifacts/key-workflows.md       → Existing flows agents must integrate with
```

Extract key points into a concise `codebase_context` string:
- Tech stack and language versions
- Naming conventions and code style
- Key architectural patterns (e.g., "uses repository pattern", "Click CLI framework")
- Import conventions and module structure

This context is injected into each agent's prompt (see Step 4) so agents follow project patterns instead of guessing.

If no artifacts are available, agents proceed without codebase context (they can still read individual files as needed).

### 4. Launch Parallel Agents

**CRITICAL**: Use Claude Code's Task tool with **multiple tool calls in a single message** to achieve parallelism.

For each batch of ready tasks (up to max_parallel):

```
Launch agents in parallel by including multiple Task tool calls in ONE message:

Task(
  description="Execute PROJ-T00001",
  prompt="Execute task PROJ-T00001: Set up OAuth config.\n\n## Codebase Context\n{codebase_context}\n\nFetch task details using mcp__asdlc__get_task(task_id='PROJ-T00001'). Follow the implementation steps exactly. Follow the project patterns described in the codebase context above. When complete, use mcp__asdlc__update_task to set status to completed.",
  subagent_type="general-purpose",
  run_in_background=true
)

Task(
  description="Execute PROJ-T00002",
  prompt="Execute task PROJ-T00002: Create login endpoint.\n\n## Codebase Context\n{codebase_context}\n\nFetch task details using mcp__asdlc__get_task(task_id='PROJ-T00002'). Follow the implementation steps exactly. Follow the project patterns described in the codebase context above. When complete, use mcp__asdlc__update_task to set status to completed.",
  subagent_type="general-purpose",
  run_in_background=true
)
```

### 5. Monitor, Complete, Handle Failures

Continue to **Shared Steps** below (Step 10 onwards).

---

## Isolated Mode (2+ PRDs)

When the sprint has multiple PRDs, each PRD gets its own git worktree with a separate branch, preventing file conflicts between agents working on different features.

### 6. Overlap Analysis

For each PRD, read task content to identify potential conflicts:
- **Files to Modify** sections in task descriptions
- **Component** fields on tasks
- Any explicit file paths mentioned

```
Overlap Analysis:
  PROJ-P0001 (Auth Feature):
    Components: auth, middleware
    Files: src/auth/*.py, src/middleware/auth.py

  PROJ-P0002 (User Profile):
    Components: user, api
    Files: src/user/*.py, src/api/routes.py

  Result: No file overlap detected. Safe for parallel execution.
```

If overlap is detected, warn the user:
```
  WARNING: File overlap detected!
    Both PROJ-P0001 and PROJ-P0002 modify: src/api/routes.py

  Recommendation: Run PROJ-P0001 first, then PROJ-P0002
  (or proceed in parallel and resolve conflicts when merging branches)

  Proceed with parallel execution? [Y/n]
```

### 7. Check for Resume

Check if `.worktrees/.state.json` exists from a previous run:

```
If .worktrees/.state.json exists and state.sprint_id matches:
    Show status of each PRD worktree:
    - completed: Skip (already done)
    - active: Offer resume/restart/abort
    - removed: Re-create if needed

    Resume previous run? [Y/n/restart]
```

### 8. Setup Worktrees

For each PRD that needs execution:

```
For idx, prd in enumerate(prd_groups):
    mcp__asdlc__setup_prd_worktree(
        prd_id=prd.prd_id,
        sprint_id=sprint_id,
        base_branch=base_branch,    # --base-branch flag, or default HEAD
        port_offset=idx * 100
    )
```

This creates per PRD:
- `.worktrees/{prd_id}/` — isolated working copy
- Branch `sprint/{sprint_id}/{prd_id}` — separate branch
- `.env.prd-override` — Docker namespace config (`COMPOSE_PROJECT_NAME`, `A_SDLC_PORT_OFFSET`)

### 8.5. Auto-Detect Docker Ports (if applicable)

For each worktree, check if `docker-compose.yml` exists:

1. Read `docker-compose.yml` in the worktree
2. Find all exposed host ports
3. Apply `A_SDLC_PORT_OFFSET` to host ports
4. Generate `docker-compose.override.yml` in the worktree

```yaml
# Auto-generated for PROJ-P0002 (port offset: 100)
services:
  web:
    ports:
      - "8180:8080"    # 8080 + 100
  db:
    ports:
      - "5532:5432"    # 5432 + 100
```

If no `docker-compose.yml` exists, skip this step entirely.

### 9. Show Isolated Plan & Confirm

```
Sprint: PROJ-S0001 - Authentication Sprint
Mode: Isolated (2 PRDs → git worktrees)

PRD Execution Plan:
  PROJ-P0001 (Auth Feature):
    Branch: sprint/PROJ-S0001/PROJ-P0001
    Worktree: .worktrees/PROJ-P0001/
    Docker namespace: proj-p0001 (ports +0)
    Tasks: 3 (PROJ-T00001, PROJ-T00002, PROJ-T00003)

  PROJ-P0002 (User Profile):
    Branch: sprint/PROJ-S0001/PROJ-P0002
    Worktree: .worktrees/PROJ-P0002/
    Docker namespace: proj-p0002 (ports +100)
    Tasks: 2 (PROJ-T00004, PROJ-T00005)

Max parallel PRDs: 2
Overlap warnings: None

Proceed with execution? [Y/n]
```

### 9.5. Load Codebase Context

Same as Simple Mode Step 3.5 — read `.sdlc/artifacts/` and build `codebase_context` string.

### 9.6. Launch PRD Agents

**CRITICAL**: Launch one agent per PRD. Each agent receives ALL tasks for its PRD and executes them sequentially (respecting intra-PRD dependencies).

```
Task(
  description="Execute PRD PROJ-P0001",
  prompt="""You are executing PRD PROJ-P0001 (Auth Feature) in an isolated git worktree.

## CRITICAL: Working Directory
Your working directory is: {worktree_path}
Run `cd {worktree_path}` as your FIRST action.

## Environment
- COMPOSE_PROJECT_NAME=proj-p0001
- A_SDLC_PORT_OFFSET=0
- Branch: sprint/PROJ-S0001/PROJ-P0001

## Docker Isolation (if using Docker)
Use the generated override file:
  docker compose --env-file .env.prd-override -f docker-compose.yml -f docker-compose.override.yml up -d

## Codebase Context
{codebase_context}

## Tasks (execute in order)
1. PROJ-T00001: Set up OAuth config
2. PROJ-T00002: Create login endpoint
3. PROJ-T00003: Add token validation

For EACH task:
1. Call mcp__asdlc__get_task(task_id) to get full details
2. Call mcp__asdlc__update_task(task_id, status="in_progress")
3. Implement the task following project patterns
4. Commit changes: git add <files> && git commit -m "[PROJ-T00001] Set up OAuth config"
5. Call mcp__asdlc__update_task(task_id, status="completed")

When ALL tasks are done:
- Stop any Docker services you started
- Report completion
""",
  subagent_type="general-purpose",
  run_in_background=true
)

Task(
  description="Execute PRD PROJ-P0002",
  prompt="...(same pattern, different worktree/tasks)...",
  subagent_type="general-purpose",
  run_in_background=true
)
```

---

## Shared Steps (Both Modes)

### 10. Monitor Progress

**Simple mode** — per-task tracking:
```
┌─────────────────────────────────────────────────────────────┐
│  Sprint: PROJ-S0001 (Simple Mode)                            │
│  Tasks: 5 total, 3 running, 2 blocked                       │
├─────────────────────────────────────────────────────────────┤
│  [Agent 1] PROJ-T00001: Set up OAuth config     🔄 Running │
│  [Agent 2] PROJ-T00002: Create login endpoint   🔄 Running │
│  [Agent 3] PROJ-T00003: Add user model fields   🔄 Running │
│  [Queued]  PROJ-T00004: Implement token refresh  ⏳ Blocked │
│  [Queued]  PROJ-T00005: Add logout endpoint      ⏳ Blocked │
│  Progress: ████████░░░░░░░░░░░░ 40%                         │
└─────────────────────────────────────────────────────────────┘
```

**Isolated mode** — per-PRD tracking:
```
┌─────────────────────────────────────────────────────────────┐
│  Sprint: PROJ-S0001 (Isolated Mode — git worktrees)          │
│  PRDs: 2 total, 2 running                                    │
├─────────────────────────────────────────────────────────────┤
│  [Agent 1] PROJ-P0001: Auth Feature             🔄 Running │
│            Tasks: 1/3 completed                              │
│            Branch: sprint/PROJ-S0001/PROJ-P0001              │
│                                                              │
│  [Agent 2] PROJ-P0002: User Profile             🔄 Running │
│            Tasks: 0/2 completed                              │
│            Branch: sprint/PROJ-S0001/PROJ-P0002              │
│  Progress: ████████░░░░░░░░░░░░ 20%                         │
└─────────────────────────────────────────────────────────────┘
```

### 11. Handle Completion Events

When an agent completes:

1. Check result via TaskOutput tool
2. If success:
   - **Simple mode**: Mark task as COMPLETED, check if blocked tasks are unblocked, launch them
   - **Isolated mode**: All tasks for that PRD are done. Report branch name and worktree path.
3. If failure:
   - Mark task as BLOCKED with failure reason
   - Log error details
   - **Continue with other tasks/PRDs** (don't stop the sprint)

### 12. Handle Failures

```
[Agent 2] PROJ-T00002: ❌ Failed

Error: Unable to create login endpoint - missing auth middleware

Action Taken:
  - Task marked as BLOCKED
  - Dependent tasks (PROJ-T00005) remain blocked
  - Continuing with other independent tasks

To retry: /sdlc:task-start PROJ-T00002
```

### 13. Generate Summary

**Simple mode:**
```
Sprint Run Complete: PROJ-S0001
Mode: Simple (1 PRD)

Duration: 12m 45s
Parallel Efficiency: 2.3x (vs sequential)

Results:
  ✅ Completed: 4 tasks
  ❌ Blocked: 1 task

Completed Tasks:
  ✅ PROJ-T00001: Set up OAuth config (3m 24s)
  ✅ PROJ-T00003: Add user model fields (2m 15s)
  ✅ PROJ-T00004: Implement token refresh (4m 30s)
  ✅ PROJ-T00005: Add logout endpoint (2m 36s)

Blocked Tasks:
  ❌ PROJ-T00002: Create login endpoint
     Reason: Failed - missing auth middleware
     To retry: /sdlc:task-start PROJ-T00002

Next Steps:
  - Fix blocked task: /sdlc:task-show PROJ-T00002
  - Complete sprint: /sdlc:sprint-complete PROJ-S0001
```

**Isolated mode:**
```
Sprint Run Complete: PROJ-S0001
Mode: Isolated (2 PRDs)

Results:
  ✅ PROJ-P0001 (Auth Feature): 3/3 tasks completed
     Branch: sprint/PROJ-S0001/PROJ-P0001
     Worktree: .worktrees/PROJ-P0001/

  ✅ PROJ-P0002 (User Profile): 2/2 tasks completed
     Branch: sprint/PROJ-S0001/PROJ-P0002
     Worktree: .worktrees/PROJ-P0002/

Review each PRD's changes:
  git diff main...sprint/PROJ-S0001/PROJ-P0001
  git diff main...sprint/PROJ-S0001/PROJ-P0002

When ready, create PRs manually:
  mcp__asdlc__create_prd_pr(prd_id="PROJ-P0001", sprint_id="PROJ-S0001")
  mcp__asdlc__create_prd_pr(prd_id="PROJ-P0002", sprint_id="PROJ-S0001")

Cleanup worktrees when done:
  mcp__asdlc__cleanup_prd_worktree(prd_id="PROJ-P0001")
  mcp__asdlc__cleanup_prd_worktree(prd_id="PROJ-P0002")

Next Steps:
  - Review changes on each branch
  - Create PRs when satisfied (user-initiated)
  - Complete sprint: /sdlc:sprint-complete PROJ-S0001
```

### 14. External System Sync (with --sync flag)

When `--sync` is enabled and sprint is linked to an external system:

**On task completion:**
```python
if sync_enabled and task.external_id:
    if task.status == TaskStatus.COMPLETED:
        update_external_issue(task.external_id, state="Done")
    elif task.status == TaskStatus.BLOCKED:
        update_external_issue(task.external_id, state="Blocked")
```

**Note:** If external sync fails, local execution continues. Failed syncs can be retried with `/sdlc:sprint-sync-to`.

---

## Execution Algorithm (Pseudocode)

```python
def run_sprint(sprint_id: str, max_parallel: int = 3, base_branch: str = None):
    sprint = get_sprint(sprint_id)
    grouped = get_sprint_tasks(sprint_id, group_by_prd=True)
    prd_groups = grouped["prd_groups"]

    # MODE DETECTION
    if len(prd_groups) == 1:
        run_simple_mode(sprint_id, prd_groups[0]["tasks"], max_parallel)
    else:
        run_isolated_mode(sprint_id, prd_groups, max_parallel, base_branch)


def run_simple_mode(sprint_id, tasks, max_parallel):
    """Single PRD — run tasks directly in working directory."""
    pending = [t for t in tasks if t["status"] != "completed"]
    ready, blocked = categorize_tasks(pending)

    active_agents = {}
    results = {}

    while ready or active_agents:
        while len(active_agents) < max_parallel and ready:
            task = ready.pop(0)
            update_task(task["id"], status="in_progress")
            agent_id = launch_task_agent(task)
            active_agents[task["id"]] = agent_id

        completed_id, success, error = wait_for_any(active_agents)
        del active_agents[completed_id]

        if success:
            results[completed_id] = "completed"
            # Unblock dependents
            for t, deps in blocked[:]:
                if all(d in results for d in deps):
                    blocked.remove((t, deps))
                    ready.append(t)
        else:
            results[completed_id] = "blocked"

    generate_report(sprint_id, results)


def run_isolated_mode(sprint_id, prd_groups, max_parallel, base_branch):
    """Multiple PRDs — one worktree per PRD."""
    # Check for resume state
    # Analyze overlap between PRDs
    # Setup worktrees
    for idx, group in enumerate(prd_groups):
        setup_prd_worktree(
            prd_id=group["prd_id"],
            sprint_id=sprint_id,
            base_branch=base_branch,
            port_offset=idx * 100,
        )

    # Launch one agent per PRD (up to max_parallel)
    # Each agent handles all tasks within its PRD sequentially
    active = {}
    queue = list(prd_groups)

    while queue or active:
        while len(active) < max_parallel and queue:
            group = queue.pop(0)
            agent_id = launch_prd_agent(group, worktree_path)
            active[group["prd_id"]] = agent_id

        completed_prd, success, error = wait_for_any(active)
        del active[completed_prd]
        # Report branch + worktree for review

    generate_isolated_report(sprint_id, prd_groups)
```

## Edge Cases (Isolated Mode)

| Scenario | Handling |
|----------|----------|
| Two PRDs modify same file | Warned during overlap analysis. User decides to proceed or serialize. |
| Docker ports already in use | Port offset shifts until ports are available |
| No docker-compose.yml | Port isolation step skipped entirely |
| Agent crashes mid-execution | Worktree remains; re-run detects via `.state.json` and offers resume |
| Resume after interruption | `.state.json` tracks status; completed PRDs skipped |
| PRD has no tasks | Skipped with warning |

## Examples

```
# Run sprint (auto-detects simple vs isolated mode)
/sdlc:sprint-run PROJ-S0001

# Run with 5 parallel agents
/sdlc:sprint-run PROJ-S0001 --parallel 5

# Preview execution plan without running
/sdlc:sprint-run PROJ-S0001 --dry-run

# Specify base branch for worktrees (multi-PRD only)
/sdlc:sprint-run PROJ-S0001 --base-branch develop

# Run with external system sync
/sdlc:sprint-run PROJ-S0001 --sync

# After isolated run — review and create PRs manually
git diff main...sprint/PROJ-S0001/PROJ-P0001
mcp__asdlc__create_prd_pr(prd_id="PROJ-P0001", sprint_id="PROJ-S0001")
```

## Important Notes

- **Auto-Detection**: Single PRD → simple mode, multiple PRDs → isolated worktrees
- **Parallel Execution**: Independent tasks/PRDs run simultaneously
- **Dependency Respect**: Blocked tasks wait for their dependencies
- **Failure Isolation**: One failed task/PRD doesn't stop others
- **Progress Tracking**: Real-time visibility into execution
- **Resumable**: Run again to continue any incomplete work
- **No Auto-PR**: PRs are never created automatically. Use `create_prd_pr` explicitly when ready.
- **Worktree Cleanup**: Use `cleanup_prd_worktree` to remove worktrees after merging
