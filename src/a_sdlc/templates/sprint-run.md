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
4. **Check git safety configuration** before deciding on isolated mode:
   ```
   config = mcp__asdlc__get_git_safety_config()
   worktree_enabled = config["config"]["effective"]["worktree_enabled"]
   ```
5. **Detect execution mode**:
   - **1 PRD** → **Simple mode**: Run tasks directly in the working directory (same as before)
   - **2+ PRDs AND `worktree_enabled` is True** → **Isolated mode**: Create a git worktree per PRD for full filesystem/branch isolation
   - **2+ PRDs AND `worktree_enabled` is False** → **Simple mode (sequential PRDs)**: Run PRDs sequentially in the working directory, warn user that worktree isolation is disabled

```
Sprint: PROJ-S0001 - Auth Sprint

Git safety config: worktree_enabled=True
PRD count: 2 → Using ISOLATED MODE (git worktrees)

  PROJ-P0001 (Auth Feature): 3 tasks
  PROJ-P0002 (User Profile): 2 tasks
```

If worktree is disabled but multiple PRDs exist:
```
Sprint: PROJ-S0001 - Auth Sprint

Git safety config: worktree_enabled=False
PRD count: 2 → Using SIMPLE MODE (worktree isolation disabled)

  WARNING: Multiple PRDs will run sequentially in the working directory.
  Enable worktree isolation for parallel PRD execution:
    mcp__asdlc__configure_git_safety(worktree_enabled=True)

  PROJ-P0001 (Auth Feature): 3 tasks
  PROJ-P0002 (User Profile): 2 tasks
```

### Step 1.5: Sprint-Level Lesson Preflight

Read `.sdlc/lesson-learn.md` and `~/.a-sdlc/lesson-learn.md`.
Aggregate lessons relevant to ALL task components in this sprint.

Present consolidated summary:
```
AskUserQuestion({
  questions: [{
    question: "Sprint lesson summary — {N} lessons across {M} categories. Ready to proceed?",
    header: "Sprint prep",
    options: [
      { label: "Ready", description: "Reviewed all lessons, ready to start sprint execution" },
      { label: "Review details", description: "Show me the full lesson list before proceeding" },
      { label: "Skip preflight", description: "Proceed without lesson review" }
    ],
    multiSelect: false
  }]
})
```

If only 1 PRD is detected, or if `worktree_enabled` is False (even with multiple PRDs), skip ahead to **Step 3** (Simple Mode).

---

## Simple Mode (1 PRD)

When the sprint has a single PRD, tasks run directly in the current working directory with no worktree overhead.

### 2. Build Dependency Graph

Group tasks into **ordered batches** using topological sort. Each batch contains tasks that are independent of each other. Batches execute in order — all tasks in batch N must complete before batch N+1 begins.

- **Batch 0**: Tasks with no unmet dependencies (entry points)
- **Batch 1**: Tasks whose dependencies are all in batch 0
- **Batch N**: Tasks whose dependencies are all in batches 0..N-1
- **Completed/In-Progress**: Treated as already satisfied (skip from batching, count as resolved)
- **Circular dependencies**: Detected and reported — remaining tasks returned as unresolvable

```python
def build_batches(tasks: list[dict]) -> tuple[list[list[dict]], list[dict]]:
    """Group tasks into dependency-ordered batches via topological sort.

    Returns:
        (batches, unresolvable)
        - batches: Ordered list of lists. Each inner list is a batch of
          independent tasks that can execute in any order within the batch.
        - unresolvable: Tasks involved in circular dependencies (if any).
    """
    # --- 1. Identify already-resolved tasks ---
    resolved_ids = {
        t["id"] for t in tasks
        if t["status"] in ("completed", "in_progress")
    }

    # --- 2. Build pending set (tasks that need execution) ---
    pending = [
        t for t in tasks
        if t["status"] not in ("completed", "in_progress")
    ]

    # --- 3. Kahn's algorithm — layer-by-layer topological sort ---
    batches = []
    placed_ids = set(resolved_ids)  # Pre-resolved count as placed

    while pending:
        # Find tasks whose dependencies are ALL in placed_ids
        current_batch = []
        still_pending = []

        for task in pending:
            deps = task.get("dependencies", [])
            unmet = [d for d in deps if d not in placed_ids]
            if not unmet:
                current_batch.append(task)
            else:
                still_pending.append(task)

        if not current_batch:
            # No progress — remaining tasks form circular dependencies
            return batches, still_pending

        # Record this batch and mark its tasks as placed
        batches.append(current_batch)
        for task in current_batch:
            placed_ids.add(task["id"])

        pending = still_pending

    return batches, []  # No unresolvable tasks
```

**Circular dependency detection**: If an iteration produces no new batch members but pending tasks remain, those tasks form one or more dependency cycles. They are returned as `unresolvable` and reported to the user before execution begins.

### 3. Display Execution Plan

Present the batch-grouped execution plan derived from `build_batches()` (Step 2). The plan shows each batch with its tasks and dependency reasoning, giving the user a clear picture of execution order before committing.

```
Sprint: {sprint_id} — {sprint_title}
Mode: Simple ({N} PRD(s))
Execution Plan ({B} batches, {M} tasks):

  Batch 1 ({count} tasks, independent):
    {task_id}: {title} ({component})
    {task_id}: {title} ({component})
    {task_id}: {title} ({component})

  Batch 2 ({count} tasks, depend on Batch 1):
    {task_id}: {title} ({component})
      └─ depends on: {dep_task_id}
    {task_id}: {title} ({component})
      └─ depends on: {dep_task_id}

  Batch 3 ({count} tasks, depend on Batches 1–2):
    {task_id}: {title} ({component})
      └─ depends on: {dep_task_id}, {dep_task_id}

  {if unresolvable:}
  ⚠ Unresolvable (circular dependencies):
    {task_id}: {title} — depends on {dep_ids}
    {task_id}: {title} — depends on {dep_ids}
    These tasks will be skipped unless dependencies are manually resolved.
```

**Concrete example:**
```
Sprint: PROJ-S0001 — Week 4 Auth
Mode: Simple (1 PRD)
Execution Plan (2 batches, 5 tasks):

  Batch 1 (3 tasks, independent):
    PROJ-T00001: Set up OAuth config (auth)
    PROJ-T00002: Create login endpoint (auth)
    PROJ-T00003: Add user model fields (models)

  Batch 2 (2 tasks, depend on Batch 1):
    PROJ-T00004: Implement token refresh (auth)
      └─ depends on: PROJ-T00001
    PROJ-T00005: Add logout endpoint (auth)
      └─ depends on: PROJ-T00002
```

After displaying the plan, ask the user to approve before execution begins:

```
AskUserQuestion({
  questions: [{
    question: "Review the execution plan above. Ready to start?",
    header: "Execution Plan Approval",
    options: [
      { label: "Start execution", description: "Begin batch-by-batch execution as shown" },
      { label: "Adjust plan", description: "Modify task order, skip tasks, or add clarification before starting" },
      { label: "Abort", description: "Cancel sprint execution entirely" }
    ],
    multiSelect: false
  }]
})
```

**Handling user responses:**
- **"Start execution"** — Proceed to Step 3.5 (Build Context Packages) then Step 4 (Launch Agents).
- **"Adjust plan"** — Ask follow-up: "Which tasks to skip or reorder? Provide task IDs and instructions." Apply adjustments (remove skipped tasks from batches, re-run `build_batches()` if reordering changes dependencies), then re-display the updated plan and ask again.
- **"Abort"** — Stop execution. Report: "Sprint execution cancelled by user." No tasks are started.

If `--dry-run` flag was passed, display the plan and stop here without asking for approval.

### 3.5. Build Context Packages

Before launching task agents, the orchestrator builds a **context package** for each task. The context package is a single text block containing everything the subagent needs — the subagent never reads plan files directly.

```python
def build_context_package(task_id: str, completed_outcomes: dict[str, str]) -> str:
    """Build an inline text context package for a task agent.

    The orchestrator calls this BEFORE dispatching each subagent.
    Returns a single string that is injected into the agent prompt.

    Args:
        task_id: The task to build context for.
        completed_outcomes: Map of {task_id: outcome_summary} for tasks
            that have already finished in this sprint run.
    """

    # --- 1. Task content (full) ---
    task = mcp__asdlc__get_task(task_id=task_id)
    task_content = task["content"]          # Complete markdown from file_path
    task_meta = {
        "id": task["id"],
        "title": task["title"],
        "status": task["status"],
        "priority": task["priority"],
        "component": task["component"],
        "prd_id": task["prd_id"],
    }

    # --- 2. Parent PRD content (filtered) ---
    prd_section = ""
    if task["prd_id"]:
        prd = mcp__asdlc__get_prd(prd_id=task["prd_id"])
        prd_section = filter_prd_for_task(prd["content"], task_meta)

    # --- 3. Design doc content (filtered) ---
    design_section = ""
    if task["prd_id"]:
        try:
            design = mcp__asdlc__get_design(prd_id=task["prd_id"])
            design_section = filter_design_for_task(design["content"], task_meta)
        except NotFound:
            pass  # No design doc exists — skip

    # --- 4. Codebase artifacts (concise) ---
    codebase_section = ""
    context = mcp__asdlc__get_context()
    if context["artifacts"]["scan_status"] in ("complete", "partial"):
        summary = Read(".sdlc/artifacts/codebase-summary.md")
        workflows = Read(".sdlc/artifacts/key-workflows.md")
        codebase_section = extract_relevant_sections(
            summary, workflows, task_meta["component"]
        )

    # --- 5. Completed task outcomes (from this sprint run) ---
    dependency_outcomes = ""
    for dep_id in task.get("dependencies", []):
        if dep_id in completed_outcomes:
            dependency_outcomes += f"- {dep_id}: {completed_outcomes[dep_id]}\n"

    # --- Assemble inline text package ---
    return assemble_package(
        task_content, task_meta, prd_section,
        design_section, codebase_section, dependency_outcomes
    )
```

#### Context Package Output Structure

The assembled package is a single text block injected into the agent prompt. No file paths — all content is inline.

```
## Task
ID: PROJ-T00001
Title: Set up OAuth config
Priority: high | Component: auth | PRD: PROJ-P0001

{full task markdown content}

## Parent PRD (filtered)
{PRD sections relevant to this task — see filtering rules below}

## Design (filtered)
{Design sections relevant to this task — see filtering rules below}

## Codebase Context
- Stack: Python 3.12, Click CLI, SQLite
- Patterns: repository pattern, hybrid storage (DB + markdown files)
- Conventions: snake_case, src/ layout, uv for dependency management
- Key workflows: create_*() → file_path → Write content → update_*() for metadata

## Prior Task Outcomes
- PROJ-T00003: Added user model fields to src/models/user.py (migration 004)
```

#### Conciseness Rules

PRD and design documents can be large. Filter them to include only what the task agent needs.

**PRD filtering** (`filter_prd_for_task`):

- **Always include**: Title, overview/summary, tech stack, constraints
- **Include if matches task component**: The functional requirement section(s) that the task traces to (match via `### Traces To` entries in task content)
- **Exclude**: Sections for unrelated components, full appendices, revision history, stakeholder lists

**Design doc filtering** (`filter_design_for_task`):

- **Always include**: Architecture overview, API contracts the task must conform to
- **Include if matches task component**: Component-specific design decisions, data models the task touches
- **Exclude**: Components the task does not interact with, deployment diagrams, full sequence diagrams for other flows

**Codebase artifact extraction** (`extract_relevant_sections`):

- From `codebase-summary.md`: Tech stack, naming conventions, architectural patterns
- From `key-workflows.md`: Only workflows the task's component participates in
- If no artifacts available: Omit section entirely (agents can still read files as needed)

**Completed outcomes**: One-line summary per dependency — what changed and where. Omit tasks that are not direct dependencies.

> **Cross-reference**: `task-start.md` uses the same pattern for single-task context loading (component context from `architecture.md`, traceability display). The context package here extends that pattern for batch dispatch.

### 4. Dispatch Task Agents (Sequential Within Batch)

Tasks within a batch execute **sequentially** — the orchestrator dispatches one subagent at a time, waits for it to complete, records the outcome, then dispatches the next. This ensures deterministic execution order and allows prior task outcomes to flow into subsequent context packages.

**Key principles:**
- Each task gets a fresh subagent via Claude Code's `Task` tool with `run_in_background=false`
- The subagent receives a curated context package (from Step 3.5) — it never reads plan files directly
- Review gates are embedded in the subagent prompt
- If the subagent encounters unresolvable questions, it surfaces them via `AskUserQuestion` — the orchestrator does NOT need to intercept these; they propagate to the user automatically

#### Subagent Prompt Template

For each task in the current batch, the orchestrator builds and dispatches:

```
Task(
  description="Implement {task_id}: {task_title}",
  prompt="""You are implementing task {task_id}: {task_title}

{context_package}

## Instructions

1. Read the task content above — it contains everything you need
2. Implement the task following the Implementation Steps section
3. Write tests as specified in the Acceptance Criteria
4. When you discover and fix issues during implementation, log them:
   mcp__asdlc__log_correction(context_type='task', context_id='{task_id}', category='{category}', description='{what was corrected and why}')
   Categories: testing, code-quality, task-completeness, integration, documentation, architecture, security, performance, process
5. Commit your changes: git add <files> && git commit -m "[{task_id}] {task_title}"

## Review Gates (MANDATORY before completion)

Do NOT call update_task(status='completed') until the review process completes with APPROVE.

### 1. Self-Review
- Re-read task spec above — extract Acceptance Criteria
- Verify EACH acceptance criterion is satisfied by your implementation
- Read .sdlc/config.yaml (if exists) — run ALL commands under `testing.commands` (e.g. pytest, lint, typecheck)
- If no config exists, run the project's default test command
- Capture and include ACTUAL test output — no self-assertions without evidence
- If any check fails, fix before proceeding
- Build a findings list for any issues found

### 2. Subagent Review
- Dispatch a fresh reviewer agent via the Task tool with this prompt:

  'You are an independent code reviewer. Review the implementation of task {task_id} against its specification.

  ## Review Materials
  Task spec: {task_spec_summary}
  Code diff:
  ```diff
  {your_git_diff}
  ```
  Self-review results: {test_output_and_ac_checklist}

  ## Evaluate
  - Spec compliance: Are all Acceptance Criteria and Traces To requirements addressed?
  - Code quality: Does the code follow project patterns? Any duplication, security concerns?
  - Test coverage: Do tests exist and pass for the new functionality?

  ## Required Output
  REVIEW VERDICT: [APPROVE | REQUEST_CHANGES | ESCALATE_TO_USER]
  FINDINGS: [list each finding with severity and detail]
  SUMMARY: [1-2 sentence assessment]'

- Wait for the reviewer verdict

### 3. Self-Heal Loop
- If reviewer says REQUEST_CHANGES: fix the cited issues, re-run tests, dispatch a NEW reviewer
- Max review rounds: read `review.max_rounds` from .sdlc/config.yaml (default: 3)
- After max rounds with no approval: use AskUserQuestion to escalate to the user
  Options: "Override & complete", "Continue fixing", "Block task"

### 4. Log & Complete
- For EVERY finding (yours or reviewer's), call:
  mcp__asdlc__log_correction(context_type='task', context_id='{task_id}', category='{category}', description='{what_was_found_and_fixed}')
- Only after reviewer APPROVE (or user override): call mcp__asdlc__update_task(task_id='{task_id}', status='completed')
- If you encounter questions you cannot resolve from the provided context, surface them via AskUserQuestion — do NOT guess
""",
  subagent_type="general-purpose"
)
```

**IMPORTANT**: Do NOT use `run_in_background=true` — the orchestrator waits for each subagent to complete so it can:
1. Record the outcome in `completed_outcomes` for downstream context packages
2. Handle review failures via the Batch Failure Handler (Step 4.5)
3. Proceed to the next task in the batch

#### Question Escalation (FR-004)

When a subagent encounters an unresolvable question (missing information, ambiguous requirement, conflicting constraints), it uses `AskUserQuestion` directly. Because `run_in_background=false`, the question propagates to the user in the orchestrator's session. The user's response flows back to the subagent, which resumes execution.

No special handling is needed in the orchestrator — the `AskUserQuestion` mechanism handles this transparently.

#### Dispatch Sequence (Concrete Example)

```
# Batch 1: 3 independent tasks — dispatched sequentially
outcomes = {}

# Task 1
update_task("PROJ-T00001", status="in_progress")
context_1 = build_context_package("PROJ-T00001", outcomes)
result_1 = Task(description="Implement PROJ-T00001: Set up OAuth config",
                prompt=f"...{context_1}...", subagent_type="general-purpose")
outcomes["PROJ-T00001"] = "Added OAuth config to src/auth/config.py"

# Task 2 (receives outcome of Task 1 in context if it's a dependency)
update_task("PROJ-T00002", status="in_progress")
context_2 = build_context_package("PROJ-T00002", outcomes)
result_2 = Task(description="Implement PROJ-T00002: Create login endpoint",
                prompt=f"...{context_2}...", subagent_type="general-purpose")
outcomes["PROJ-T00002"] = "Created POST /auth/login endpoint in src/api/auth.py"

# Task 3
update_task("PROJ-T00003", status="in_progress")
context_3 = build_context_package("PROJ-T00003", outcomes)
result_3 = Task(description="Implement PROJ-T00003: Add user model fields",
                prompt=f"...{context_3}...", subagent_type="general-purpose")
outcomes["PROJ-T00003"] = "Added email, role fields to User model, migration 004"

# → Batch checkpoint (Step 4.5) → proceed to Batch 2
```

### 4.3. Track Task Outcomes

After each subagent completes, the orchestrator extracts an outcome summary and stores it. These outcomes serve two purposes:
1. **Context for downstream tasks** — via `build_context_package()` (Step 3.5), which injects dependency outcomes into subsequent subagent prompts
2. **Batch checkpoint reports** — via `present_batch_results()` (Step 4.5), which shows per-task results

#### Outcome Data Structure

```python
# outcomes dict: {task_id: outcome_summary_string}
# Populated after each subagent returns.

outcomes = {}  # Initialized at the start of run_simple_mode()

def record_outcome(task: dict, result, outcomes: dict, reason: str = None):
    """Extract and record a concise outcome summary after subagent completion.

    Args:
        task: Task metadata dict.
        result: Subagent result (from dispatch_subagent).
        outcomes: The shared outcomes dict to append to.
        reason: Override reason (for skipped/failed tasks).
    """
    if reason:
        # Task was skipped or manually failed
        outcomes[task["id"]] = f"[{reason}]"
        return

    if result.success:
        # Extract from subagent output:
        #   - Files changed (from git diff summary or commit message)
        #   - Key changes (1-2 sentences)
        summary = extract_outcome_summary(result.output)
        outcomes[task["id"]] = summary
        # Example: "Added OAuth config to src/auth/config.py, 3 tests added"
    else:
        outcomes[task["id"]] = f"[failed: {result.error_summary}]"
```

#### Outcome Summary Extraction

When a subagent completes successfully, extract a concise outcome summary from its output. The summary should be **1-2 sentences** covering:

- **What was done**: Key changes or additions
- **Where**: Primary files modified
- **Test status**: Pass/fail count if available

```
# Good outcome summaries (concise):
"Added OAuth config to src/auth/config.py and src/auth/constants.py. 3 unit tests added, all passing."
"Created POST /auth/login endpoint in src/api/auth.py with JWT token generation. Integration test added."
"Added email, role fields to User model (migration 004). Updated 2 existing tests."

# Bad outcome summaries (too verbose — avoid):
"I implemented the OAuth configuration by creating a new file at src/auth/config.py which contains..."
```

If the subagent output is too long to summarize automatically, fall back to the git commit message(s) produced during the task.

#### Integration with Context Package

The `build_context_package()` function (Step 3.5) already accepts `completed_outcomes` and includes a `## Prior Task Outcomes` section. The `outcomes` dict populated here is passed directly:

```python
context = build_context_package(task["id"], outcomes)
# → outcomes for dependency tasks are included in the "## Prior Task Outcomes" section
```

Only **direct dependency** outcomes are included in the context package (not all completed tasks). This keeps context concise per NFR-002.

### 4.5. Batch Checkpoint

After ALL tasks in a batch complete (or fail), the orchestrator presents a checkpoint report to the user before moving to the next batch. This gives the user visibility into progress and control over the remaining execution.

#### Batch Completion Report

```
Batch {N} Complete ({completed}/{total} tasks):
  ✅ {task_id}: {title} — Completed
  ✅ {task_id}: {title} — Completed
  ❌ {task_id}: {title} — Failed ({reason})

Next: Batch {N+1} ({count} tasks)
  {task_id}: {title} ({component})
  {task_id}: {title} ({component})
```

**Concrete example:**
```
Batch 1 Complete (2/3 tasks):
  ✅ PROJ-T00001: Set up OAuth config — Completed
  ✅ PROJ-T00003: Add user model fields — Completed
  ❌ PROJ-T00002: Create login endpoint — Failed (test failures in auth middleware)

Next: Batch 2 (2 tasks)
  PROJ-T00004: Implement token refresh (auth)
  PROJ-T00005: Add logout endpoint (auth)
    ⚠ depends on PROJ-T00002 (failed) — will be skipped unless resolved
```

Then ask the user for a decision:

```
AskUserQuestion({
  questions: [{
    question: "Batch {N} done. Proceed to Batch {N+1}?",
    header: "Batch Checkpoint",
    options: [
      { label: "Continue", description: "Proceed to next batch as planned" },
      { label: "Skip tasks", description: "Choose specific tasks to skip in the next batch" },
      { label: "Add clarification", description: "Provide additional guidance or context for upcoming tasks" },
      { label: "Abort", description: "Stop remaining execution and generate summary" }
    ],
    multiSelect: false
  }]
})
```

**Handling user responses:**
- **"Continue"** — Proceed to the next batch. Tasks whose dependencies failed are automatically skipped (their unmet dependencies cannot be satisfied).
- **"Skip tasks"** — Ask follow-up: "Which tasks to skip? Provide task IDs." Remove those tasks from subsequent batches. Re-evaluate downstream dependencies — any task that depends solely on skipped tasks is also flagged for the user.
- **"Add clarification"** — Ask follow-up: "Enter clarification for upcoming tasks." The clarification text is appended to the context package for all tasks in the next batch under a `## User Clarification` section.
- **"Abort"** — Stop execution. Mark remaining tasks as unchanged (keep current status). Generate the sprint summary with partial results.

**Final batch checkpoint**: After the LAST batch completes, present a completion report instead of a next-batch prompt:

```
All Batches Complete ({completed_total}/{task_total} tasks):
  Batch 1: {passed}/{total} passed
  Batch 2: {passed}/{total} passed
  ...

Overall: {completed} completed, {failed} failed, {skipped} skipped

Proceeding to sprint summary...
```

#### Batch Failure Handler

When a task fails its review gates after the maximum number of review rounds (read `review.max_rounds` from `.sdlc/config.yaml`, default: 3), the batch pauses and the orchestrator consults the user immediately — do not wait for the entire batch to finish.

```
Task {task_id} failed review after {max_rounds} rounds.
Last reviewer feedback:
  {feedback_summary}

AskUserQuestion({
  questions: [{
    question: "How to handle the failed task {task_id}?",
    header: "Task Review Failure",
    options: [
      { label: "Retry with fresh agent", description: "Dispatch a new subagent to re-attempt this task from scratch" },
      { label: "Skip and continue", description: "Skip this task and proceed with remaining batch tasks" },
      { label: "Abort batch", description: "Stop the current batch and proceed to batch checkpoint" },
      { label: "Implement manually", description: "Leave task for manual implementation, mark as blocked" }
    ],
    multiSelect: false
  }]
})
```

**Handling user responses:**
- **"Retry with fresh agent"** — Dispatch a new subagent for this task with a fresh context package. The retry counts as an additional attempt but does NOT reset the review round counter for logging purposes. If the fresh agent also fails review, escalate again.
- **"Skip and continue"** — Mark task status as `blocked` with reason "Skipped after review failure". Continue executing other tasks in the current batch. Downstream tasks that depend on this task will be flagged at the next batch checkpoint.
- **"Abort batch"** — Stop all remaining tasks in the current batch. Proceed directly to the batch checkpoint report (Step 4.5) with partial results.
- **"Implement manually"** — Mark task as `blocked` with reason "Deferred to manual implementation". Log a correction via `mcp__asdlc__log_correction()`. Continue with remaining batch tasks.

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

### 7. Check for Resume via DB State

Query the database for existing worktrees from a previous run:

```
worktrees = mcp__asdlc__list_worktrees(sprint_id=sprint_id)
```

If `worktrees["count"] > 0`, a previous run exists:

```
If worktrees exist for this sprint:
    Show status of each PRD worktree (from DB records):
    - completed / pr_created: Skip (already done)
    - active: Offer resume/restart/abort
    - cleaned: Re-create if needed

    Previous run detected for {sprint_id}:
      PROJ-P0001: active (branch: sprint/PROJ-S0001/PROJ-P0001)
      PROJ-P0002: completed (branch: sprint/PROJ-S0001/PROJ-P0002)

    Resume previous run? [Y/n/restart]
```

If "restart" is chosen, clean up existing worktrees before proceeding:
```
for w in worktrees["worktrees"]:
    if w["status"] == "active":
        mcp__asdlc__cleanup_prd_worktree(prd_id=w["prd_id"])
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

### 9.5. Build Context Packages for All PRD Tasks

Before launching PRD agents, the orchestrator pre-builds context packages for **all tasks across all PRDs** and groups them into dependency-ordered batches per PRD. This is the same `build_context_package()` from Step 3.5.

```python
for group in prd_groups:
    # Group this PRD's tasks into dependency-ordered batches
    batches, unresolvable = build_batches(group["tasks"])
    group["batches"] = batches

    # Pre-build context packages for all tasks in this PRD
    group["context_packages"] = {}
    for batch in batches:
        for task in batch:
            group["context_packages"][task["id"]] = build_context_package(
                task["id"], completed_outcomes={}  # No prior outcomes for fresh PRD agent
            )
```

### 9.6. Launch PRD Agents

**CRITICAL**: Launch one agent per PRD. Each agent receives ALL tasks with pre-built context packages organized by batch. The agent executes tasks sequentially within each batch, in batch order.

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

## Execution Instructions

Execute tasks in batch order, sequentially within each batch.
All tasks in Batch N must complete before starting Batch N+1.
Each task's curated context package is provided below — you do NOT need to call get_task().

For EACH task:
1. Read the context package below
2. Call mcp__asdlc__update_task(task_id, status="in_progress")
3. Implement the task following the Implementation Steps in its context
4. Commit changes: git add <files> && git commit -m "[{task_id}] {task_title}"
5. Run review gates (see below)
6. Only after reviewer APPROVE: call mcp__asdlc__update_task(task_id, status="completed")

## Batch 1 (independent tasks):

### Task: PROJ-T00001 — Set up OAuth config
{context_package_for_PROJ-T00001}

### Task: PROJ-T00002 — Create login endpoint
{context_package_for_PROJ-T00002}

## Batch 2 (depends on Batch 1):

### Task: PROJ-T00003 — Add token validation
{context_package_for_PROJ-T00003}

## Review Gates (MANDATORY for EACH task before marking completed)

### 1. Self-Review
- Re-read the task's Acceptance Criteria from its context package above
- Verify EACH acceptance criterion is satisfied by your implementation
- Read .sdlc/config.yaml (if exists) — run ALL commands under `testing.commands`
- If no config exists, run the project's default test command
- Capture and include ACTUAL test output — no self-assertions without evidence
- If any check fails, fix before proceeding

### 2. Subagent Review
- Dispatch a fresh reviewer agent via the Task tool:
  'You are an independent code reviewer. Review the implementation of task {task_id}.
  Task spec: {task_spec_summary}
  Code diff: {your_git_diff}
  Self-review results: {test_output_and_ac_checklist}
  Evaluate: spec compliance, code quality, test coverage.
  REVIEW VERDICT: [APPROVE | REQUEST_CHANGES | ESCALATE_TO_USER]
  FINDINGS: [list each finding]
  SUMMARY: [1-2 sentence assessment]'
- Wait for the reviewer verdict

### 3. Self-Heal Loop
- If REQUEST_CHANGES: fix cited issues, re-run tests, dispatch a NEW reviewer
- Max rounds: `review.max_rounds` from .sdlc/config.yaml (default 3)
- After max rounds: AskUserQuestion to escalate

### 4. Log & Complete
- For EVERY finding, call: mcp__asdlc__log_correction(context_type='task', context_id=task_id, category='{category}', description='{finding}')
- Only after APPROVE: call mcp__asdlc__update_task(task_id, status="completed")
- If you encounter unresolvable questions, surface them via AskUserQuestion — do NOT guess

When ALL tasks are done:
- Stop any Docker services you started
- Report completion
""",
  subagent_type="general-purpose",
  run_in_background=true
)

Task(
  description="Execute PRD PROJ-P0002",
  prompt="...(same pattern, different worktree/tasks/batches/context packages)...",
  subagent_type="general-purpose",
  run_in_background=true
)
```

**Note**: PRD agents use `run_in_background=true` because the orchestrator manages multiple PRDs concurrently. Within each PRD agent, tasks execute sequentially (no background dispatch).

---

## Shared Steps (Both Modes)

### 10. Monitor Progress

**Simple mode** — batch progress tracking:

Since tasks execute sequentially within batches, the monitoring display shows the current batch's progress:

```
Sprint: PROJ-S0001 (Simple Mode)
Batch 2/3 in progress:
  ✅ PROJ-T00004: Implement token refresh — Completed (review passed)
  🔄 PROJ-T00005: Add logout endpoint — In progress
  ⏳ PROJ-T00006: Add session management — Pending

Overall: ████████████░░░░░░░░ 60% (6/10 tasks)
```

Between batches (at checkpoint), show the full batch summary (see Step 4.5).

**Isolated mode** — per-PRD tracking:
```
Sprint: PROJ-S0001 (Isolated Mode — git worktrees)
PRDs: 2 total, 2 running

  PROJ-P0001 (Auth Feature):              🔄 Running
    Tasks: 1/3 completed (Batch 1/2)
    Branch: sprint/PROJ-S0001/PROJ-P0001

  PROJ-P0002 (User Profile):              🔄 Running
    Tasks: 0/2 completed (Batch 1/1)
    Branch: sprint/PROJ-S0001/PROJ-P0002

Overall: ████░░░░░░░░░░░░░░░░ 20% (1/5 tasks)
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

**Log failures as corrections** so the retrospective can identify patterns:

```
mcp__asdlc__log_correction(
  context_type="task",
  context_id="PROJ-T00002",
  category="{appropriate_category}",
  description="Task failed: {error reason}. {what was learned or needs fixing}"
)
```

**Reminder to agents:** Each task agent should call `mcp__asdlc__log_correction()` whenever it discovers and fixes issues during implementation (bugs, missing tests, pattern violations, etc.). Log corrections as they happen — don't wait until task completion.

### 13. Generate Summary

**Simple mode:**
```
Sprint Run Complete: PROJ-S0001
Mode: Simple (1 PRD)

Batch Results:
  Batch 1 (3 tasks): ✅ 2 passed, ❌ 1 failed
  Batch 2 (2 tasks): ✅ 2 passed

Results:
  ✅ Completed: 4 tasks
  ❌ Failed: 1 task
  ⏭️ Skipped: 0 tasks

Completed Tasks:
  ✅ PROJ-T00001: Set up OAuth config
  ✅ PROJ-T00003: Add user model fields
  ✅ PROJ-T00004: Implement token refresh
  ✅ PROJ-T00005: Add logout endpoint

Failed Tasks:
  ❌ PROJ-T00002: Create login endpoint
     Reason: Failed - review failure after 3 rounds
     To retry: /sdlc:task-start PROJ-T00002

Next Steps:
  - Fix failed task: /sdlc:task-show PROJ-T00002
  - Complete sprint: /sdlc:sprint-complete PROJ-S0001
```

**Isolated mode:**

After all PRD agents complete, present the branch completion workflow. The available actions depend on git safety configuration:

```
config = mcp__asdlc__get_git_safety_config()
auto_pr = config["config"]["effective"]["auto_pr"]
auto_merge = config["config"]["effective"]["auto_merge"]
```

For each completed PRD, present only the **allowed** completion options:

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
```

Then for each PRD, ask the user to choose a completion action using `complete_prd_worktree`:

```
AskUserQuestion({
  questions: [{
    question: "Choose completion action for PROJ-P0001 (Auth Feature)",
    header: "PRD Branch Completion",
    options: [
      { label: "keep", description: "Keep worktree and branch for manual handling" },
      { label: "discard", description: "Remove worktree and delete branch (destructive)" }
      // Only show if auto_pr is enabled:
      // { label: "pr", description: "Create a pull request for this branch" }
      // Only show if auto_merge is enabled:
      // { label: "merge", description: "Merge branch into base branch locally" }
    ],
    multiSelect: false
  }]
})
```

Execute the chosen action:
```
mcp__asdlc__complete_prd_worktree(prd_id="PROJ-P0001", action="{chosen_action}")
mcp__asdlc__complete_prd_worktree(prd_id="PROJ-P0002", action="{chosen_action}")
```

**Action behavior:**
- **keep**: No cleanup. Branch and worktree remain for manual review/handling.
- **pr**: Creates a PR via `gh` CLI. Requires `auto_pr` enabled in git safety config. Worktree is kept.
- **merge**: Merges branch into base branch locally. Requires `auto_merge` enabled. Worktree is cleaned up.
- **discard**: Removes worktree and deletes branch. Requires explicit confirmation (`confirm_discard=True`).

**IMPORTANT**: Do NOT present `pr` or `merge` options if they are disabled in the git safety configuration. Only `keep` and `discard` are always available. This ensures disabled operations are never offered to the user.

```
Next Steps:
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

    # Check git safety config for worktree support
    config = get_git_safety_config()
    worktree_enabled = config["config"]["effective"]["worktree_enabled"]

    # MODE DETECTION — worktree_enabled gates isolated mode
    if len(prd_groups) == 1 or not worktree_enabled:
        if len(prd_groups) > 1 and not worktree_enabled:
            warn("Multiple PRDs but worktree isolation disabled. Running sequentially.")
        run_simple_mode(sprint_id, prd_groups, max_parallel)
    else:
        run_isolated_mode(sprint_id, prd_groups, max_parallel, base_branch)


def run_simple_mode(sprint_id, prd_groups, max_parallel):
    """Single PRD or worktree-disabled — run tasks directly in working directory."""
    # Flatten all tasks across PRD groups
    tasks = [t for group in prd_groups for t in group["tasks"]]

    # Build dependency-ordered batches
    batches, unresolvable = build_batches(tasks)

    if unresolvable:
        warn_circular_deps(unresolvable)
        # Present unresolvable tasks to user before proceeding
        # Execution continues with the batches that CAN be resolved

    # --- Present execution plan and get user approval (Step 3) ---
    present_execution_plan(sprint_id, batches, unresolvable)
    plan_decision = ask_plan_approval()  # AskUserQuestion: Start/Adjust/Abort
    if plan_decision == "abort":
        report("Sprint execution cancelled by user.")
        return
    if plan_decision == "adjust":
        batches = apply_user_adjustments(batches)  # Re-display and re-ask
        # Loop until user chooses "start" or "abort"

    outcomes = {}  # {task_id: outcome_summary} — fed to build_context_package
    user_clarification = None  # Optional text from user, injected into context

    for batch_num, batch in enumerate(batches, 1):
        # --- Filter out tasks with unmet dependencies (failed/skipped deps) ---
        executable = [t for t in batch if deps_satisfied(t, outcomes)]
        skipped = [t for t in batch if t not in executable]
        for t in skipped:
            record_outcome(t, "skipped", outcomes, reason="unmet dependency")

        # --- Execute each task in the batch ---
        batch_results = {}
        for task in executable:
            update_task(task["id"], status="in_progress")
            context = build_context_package(task["id"], outcomes)
            if user_clarification:
                context += f"\n\n## User Clarification\n{user_clarification}"
            result = dispatch_subagent(task, context)  # See dispatch_subagent() below

            # --- Handle review failure within batch (Batch Failure Handler) ---
            if result.review_failed and result.rounds >= max_review_rounds:
                failure_decision = ask_failure_handler(task, result.feedback)
                if failure_decision == "retry":
                    result = dispatch_subagent(task, context, fresh=True)
                elif failure_decision == "skip":
                    update_task(task["id"], status="blocked", reason="review failure")
                elif failure_decision == "abort_batch":
                    record_outcome(task, result, outcomes)
                    break  # Exit batch loop, proceed to checkpoint
                elif failure_decision == "manual":
                    update_task(task["id"], status="blocked", reason="manual impl")
                    log_correction(task["id"], "review", "Deferred to manual")

            record_outcome(task, result, outcomes)
            batch_results[task["id"]] = result

        # --- Batch checkpoint (Step 4.5) ---
        present_batch_results(batch_num, batch_results, skipped)

        if batch_num < len(batches):
            next_batch = batches[batch_num]  # 0-indexed: batch_num is next
            checkpoint_decision = ask_batch_checkpoint(batch_num, next_batch)
            if checkpoint_decision == "abort":
                break
            elif checkpoint_decision == "skip_tasks":
                skip_ids = ask_which_tasks_to_skip(next_batch)
                batches[batch_num] = [t for t in next_batch if t["id"] not in skip_ids]
            elif checkpoint_decision == "add_clarification":
                user_clarification = ask_for_clarification()
            # "continue" — no action needed, proceed to next batch

    # --- Final completion report ---
    present_completion_summary(batches, outcomes)
    generate_report(sprint_id, outcomes)


def dispatch_subagent(task: dict, context_package: str, fresh: bool = False) -> Result:
    """Dispatch a single task to a fresh subagent and wait for completion.

    Args:
        task: Task metadata dict with id, title, etc.
        context_package: Inline text from build_context_package().
        fresh: If True, this is a retry — add retry context to prompt.

    Returns:
        Result with: success (bool), review_verdict, rounds, outcome_summary,
                     review_failed (bool), feedback (str).
    """
    retry_note = ""
    if fresh:
        retry_note = (
            "\n\n## RETRY NOTE\n"
            "This is a retry attempt. A previous agent failed review.\n"
            "Pay extra attention to the review feedback from the prior attempt.\n"
        )

    # Synchronous dispatch — orchestrator waits for completion
    result = Task(
        description=f"Implement {task['id']}: {task['title']}",
        prompt=SUBAGENT_PROMPT_TEMPLATE.format(
            task_id=task["id"],
            task_title=task["title"],
            context_package=context_package,
            retry_note=retry_note,
        ),
        subagent_type="general-purpose",
        # run_in_background=false — orchestrator waits
    )

    return parse_subagent_result(result)


def record_outcome(task: dict, result, outcomes: dict, reason: str = None):
    """Record a concise outcome summary after subagent completion."""
    if reason:
        outcomes[task["id"]] = f"[{reason}]"
    elif result.success:
        outcomes[task["id"]] = extract_outcome_summary(result.output)
    else:
        outcomes[task["id"]] = f"[failed: {result.error_summary}]"


def extract_outcome_summary(agent_output: str) -> str:
    """Extract 1-2 sentence summary from subagent output.

    Looks for: git commit messages, files changed, test results.
    Falls back to last commit message if output is too verbose.
    """
    # Implementation: parse agent output for commit messages and test results
    # Return concise summary like:
    #   "Added OAuth config to src/auth/config.py. 3 tests passing."
    pass


def run_isolated_mode(sprint_id, prd_groups, max_parallel, base_branch):
    """Multiple PRDs — one worktree per PRD."""
    # Check for resume state via DB (not filesystem)
    existing = list_worktrees(sprint_id=sprint_id)
    if existing["count"] > 0:
        handle_resume(existing["worktrees"], prd_groups)

    # Analyze overlap between PRDs
    # Setup worktrees
    for idx, group in enumerate(prd_groups):
        setup_prd_worktree(
            prd_id=group["prd_id"],
            sprint_id=sprint_id,
            base_branch=base_branch,
            port_offset=idx * 100,
        )

    # --- Pre-build context packages and batch groupings per PRD ---
    for group in prd_groups:
        batches, unresolvable = build_batches(group["tasks"])
        group["batches"] = batches
        if unresolvable:
            warn_circular_deps(unresolvable)

        # Build context packages for all tasks in this PRD
        group["context_packages"] = {}
        for batch in batches:
            for task in batch:
                group["context_packages"][task["id"]] = build_context_package(
                    task["id"], completed_outcomes={}
                )

    # --- Launch one agent per PRD (up to max_parallel) ---
    # Each agent receives pre-built context packages organized by batch
    active = {}
    queue = list(prd_groups)

    while queue or active:
        while len(active) < max_parallel and queue:
            group = queue.pop(0)
            agent_id = launch_prd_agent(
                group,
                worktree_path=f".worktrees/{group['prd_id']}/",
                batches=group["batches"],
                context_packages=group["context_packages"],
            )
            active[group["prd_id"]] = agent_id

        completed_prd, success, error = wait_for_any(active)
        del active[completed_prd]
        # Report branch + worktree for review

    # Branch completion — use complete_prd_worktree with config-aware options
    config = get_git_safety_config()
    for group in prd_groups:
        action = prompt_completion_action(group["prd_id"], config)
        complete_prd_worktree(prd_id=group["prd_id"], action=action)

    generate_isolated_report(sprint_id, prd_groups)
```

## Edge Cases (Isolated Mode)

| Scenario | Handling |
|----------|----------|
| Two PRDs modify same file | Warned during overlap analysis. User decides to proceed or serialize. |
| Docker ports already in use | Port offset shifts until ports are available |
| No docker-compose.yml | Port isolation step skipped entirely |
| Agent crashes mid-execution | Worktree remains in DB as `active`; re-run detects via `list_worktrees()` and offers resume |
| Resume after interruption | DB tracks worktree status; completed PRDs skipped |
| PRD has no tasks | Skipped with warning |
| `worktree_enabled` is False | Falls back to simple mode with sequential PRD execution; warns user |
| `auto_pr` or `auto_merge` disabled | Those completion options are not presented to the user |

## Examples

```
# Run sprint (auto-detects simple vs isolated mode based on PRD count + worktree_enabled config)
/sdlc:sprint-run PROJ-S0001

# Run with 5 parallel agents
/sdlc:sprint-run PROJ-S0001 --parallel 5

# Preview execution plan without running
/sdlc:sprint-run PROJ-S0001 --dry-run

# Specify base branch for worktrees (multi-PRD only)
/sdlc:sprint-run PROJ-S0001 --base-branch develop

# Run with external system sync
/sdlc:sprint-run PROJ-S0001 --sync

# After isolated run — complete PRD branches using the completion tool
mcp__asdlc__complete_prd_worktree(prd_id="PROJ-P0001", action="keep")
mcp__asdlc__complete_prd_worktree(prd_id="PROJ-P0002", action="pr")
mcp__asdlc__complete_prd_worktree(prd_id="PROJ-P0003", action="discard", confirm_discard=True)

# Check existing worktree state (e.g., for resume)
mcp__asdlc__list_worktrees(sprint_id="PROJ-S0001")
```

## Important Notes

- **Config-Gated Mode**: Isolated mode requires `worktree_enabled=True` in git safety config. Without it, multi-PRD sprints fall back to simple mode.
- **Auto-Detection**: Single PRD → simple mode; multiple PRDs + `worktree_enabled` → isolated worktrees
- **Parallel Execution**: Independent tasks/PRDs run simultaneously
- **Dependency Respect**: Blocked tasks wait for their dependencies
- **Failure Isolation**: One failed task/PRD doesn't stop others
- **Progress Tracking**: Real-time visibility into execution
- **DB-Backed Resume**: Worktree state is tracked in the database via `list_worktrees()`. Re-running a sprint detects previous worktrees and offers resume.
- **Config-Aware Completion**: Use `complete_prd_worktree(prd_id, action)` for branch finalization. Only `keep` and `discard` are always available; `pr` requires `auto_pr=True`; `merge` requires `auto_merge=True`. Disabled operations are never presented as options.
- **Worktree Cleanup**: Handled automatically by `complete_prd_worktree` for `merge` and `discard` actions. For `keep` and `pr`, worktrees remain until explicitly cleaned with `cleanup_prd_worktree`.
