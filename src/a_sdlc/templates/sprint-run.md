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
3. Submit self-review evidence via `mcp__asdlc__submit_self_review()` — the **orchestrator** handles task completion after review

**Do NOT** create intermediate Claude Code tasks (TodoWrite/TaskCreate). The a-sdlc task IS the work item.

---

## Syntax

```
/sdlc:sprint-run <sprint-id> [--parallel <n>] [--dry-run] [--sync] [--base-branch <branch>] [--resume] [--solo]
```

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `sprint-id` | Yes | Sprint ID to execute (e.g., PROJ-S0001) |
| `--parallel` | No | Max concurrent agents (default: 3) |
| `--dry-run` | No | Show execution plan without running |
| `--sync` | No | Sync status to external system as tasks complete |
| `--base-branch` | No | Branch to base worktrees on (multi-PRD mode only, default: current HEAD) |
| `--resume` | No | Resume from last checkpoint (reads state from `~/.a-sdlc/runs/{project_id}/`) |
| `--solo` | No | Disable persona round-table, run in single-agent mode |

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

### 1.5. Resume from Checkpoint (if --resume)

If the `--resume` flag is present:

1. Read the state file:
   ```
   context = mcp__asdlc__get_context()
   project_id = context["project_id"]
   state_file = f"~/.a-sdlc/runs/{project_id}/{sprint_id}-state.json"
   state = Read(state_file)  # Returns JSON content
   ```

2. If the state file does not exist, warn and fall through to normal execution:
   ```
   "⚠️ No checkpoint found for {sprint_id}. Starting fresh."
   ```

3. If the state file exists, parse it and display previous progress:
   ```
   Previous Sprint Run Progress (resumed from checkpoint):
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   Sprint: {state.sprint_id}
   Mode: {state.mode}
   Last updated: {state.updated_at}
   Completed: {len(state.outcomes)} tasks

   Previously completed tasks:
     ✅ {task_id}: {outcome.summary} ({outcome.verdict})
     ...

   Skipped: {len(state.skipped)} | Failed: {len(state.failed)}

   Resuming from batch {state.current_batch + 1}...
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   ```

4. Pass the resume state to the execution mode:
   - Set `resume_state = state` (the parsed JSON)
   - Pass it to `run_simple_mode()` or `run_isolated_mode()`

### 1.6. Persona Availability Check

After loading sprint context and handling resume, check for persona agents:

1. Check `~/.claude/agents/` for files matching `sdlc-*.md` pattern
2. Determine round-table eligibility:
   - If `--solo` or `--no-roundtable` appears in the user's command: **round_table_enabled = false**
   - If no `sdlc-*.md` files found: **round_table_enabled = false**
   - Otherwise: **round_table_enabled = true**
3. If round_table_enabled = false, skip ALL persona-specific sections below. The template operates in single-agent mode (existing behavior preserved).

```
Persona Check:
  Agents directory: ~/.claude/agents/
  Persona files found: {count} sdlc-*.md files
  Solo mode: {--solo flag present}
  Round-table: {enabled | disabled (reason)}
```

> **Reference**: This implements Section A from `_round-table-blocks.md`.

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

### 2.5. Domain Detection + Panel Assembly (Round-Table)

If round_table_enabled = true, perform domain detection after sprint analysis provides multi-domain signals:

#### Domain Detection

Analyze sprint context to identify relevant domains. Unlike single-PRD templates, a sprint may span multiple domains simultaneously. Check in priority order:

1. **Explicit tags** -- Look for `<!-- personas: frontend, security -->` markers in ALL PRD and task content across the sprint. If found, use those domains directly.
2. **Codebase signals** -- From `.sdlc/artifacts/architecture.md`, identify affected components across ALL sprint tasks (e.g., components with "UI", "React", "frontend" -> frontend domain; "API", "database" -> backend domain; "CI/CD", "Docker" -> devops domain).
3. **Keyword analysis** -- Scan ALL sprint PRDs and tasks for domain keywords:
   - Frontend: UI, component, React, CSS, layout, responsive, accessibility
   - Backend: API, endpoint, database, query, migration, service, middleware
   - DevOps: CI/CD, pipeline, Docker, deploy, infrastructure, monitoring
   - Security: auth, vulnerability, encryption, OWASP, credentials, permissions
4. **Content structure** -- PRD functional requirements referencing specific technical domains

**Sprint-specific note**: Multiple domains are expected in a sprint scope. Assemble all relevant domain personas rather than selecting a single lead domain.

#### Panel Assembly

Based on detected domains, assemble the persona panel:

| Rule | Logic |
|------|-------|
| **Domain personas** (Frontend, Backend, DevOps) | Include only if their domain is detected in any sprint PRD/task |
| **Cross-cutting** (Security, QA) | Always included as advisors |
| **Phase-role** (Product Manager, Architect) | PM for sprint goal alignment; Architect for cross-PRD dependency analysis |
| **Lead assignment** | The persona whose domain has the strongest signal becomes lead. If unclear, Architect leads (sprint-level cross-cutting concerns). |

Display the panel to the user:

```
Persona Panel (Sprint Scope):
  Lead: {persona_name} (signal: {detection_reason})
  Domain: {persona_name} (signal: {detection_reason})
  Domain: {persona_name} (signal: {detection_reason})
  Advisor: {persona_name} (signal: {detection_reason})
  ...

  Domains detected: {domain_list}
  PRDs analyzed: {prd_count}
  Tasks analyzed: {task_count}
```

> **Reference**: This implements Section B from `_round-table-blocks.md`, extended for multi-PRD sprint scope.

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

### 3.1. Round-Table: Sprint Execution Strategy

If round_table_enabled = true, run the round-table discussion BEFORE presenting the execution plan for user approval. The personas review the dependency graph and execution plan from their domain perspectives.

#### Build Context Packages per Persona

For each persona in the panel, build a filtered context package containing sprint-level information relevant to their domain:

- **PM**: Sprint goal, PRD summaries (titles + overviews), business context, acceptance criteria summaries
- **Architect**: Architecture sections from `.sdlc/artifacts/architecture.md`, design docs for all sprint PRDs, dependency graph structure, cross-PRD integration points
- **Frontend/Backend/DevOps**: Domain-specific architecture sections + PRD requirements relevant to their domain + task details for their component area
- **QA**: Acceptance criteria from all tasks, test patterns from `.sdlc/artifacts/`, quality gates, testing configuration from `.sdlc/config.yaml`
- **Security**: Security-related requirements across all PRDs, API surface area, authentication/authorization patterns, data handling requirements

Include the execution plan (batch structure with dependency reasoning) in every persona's context package.

#### Detect Round-Table Mode

Check the execution environment:
- If `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` environment variable equals `"1"`: Use **Agent Teams mode**
- Otherwise: Use **Task tool mode**

Display: `Round-Table Mode: {Agent Teams | Task Tool Fallback}`

#### Dispatch Personas

**Agent Teams mode** (when `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`):

1. Create an agent team with persona teammates. For each persona in the panel:
   - Spawn a teammate with the persona's role and sprint-level domain context
   - Instruct them to: analyze the sprint execution strategy from their domain, identify risks in the batch ordering, and suggest optimizations
2. Teammates debate via SendMessage:
   - Each persona presents their analysis of the execution plan
   - Personas challenge each other's findings on batch ordering, parallelization opportunities, and risk areas
   - Lead monitors progress and steers toward actionable recommendations
3. When discussion converges (or after each persona has spoken at least twice), lead collects final positions
4. Shut down teammates and clean up team

**Task tool mode** (fallback when Agent Teams not enabled):

Dispatch persona subagents in parallel via Task tool. For each persona:

```
Task(
  description="{persona_name} sprint strategy review",
  subagent_type="{persona_agent_name}",
  prompt="""You are the {persona_name} — {persona_description}.

{persona_sprint_context_package}

Analyze the sprint execution plan from your domain perspective. Consider:
- Batch ordering: Are dependencies correctly sequenced?
- Risk areas: Which tasks or transitions carry the highest risk?
- Optimization opportunities: Could any tasks be parallelized differently?
- Domain-specific concerns: Issues visible only from your expertise area

Structure your response as:

---PERSONA-FINDINGS---
role: {lead|advisor}
domain: {domain}
findings:
- {finding with domain context}
risks:
- {risk from your perspective}
recommendations:
- {specific, actionable recommendation}
---END-FINDINGS---
"""
)
```

Collect all `---PERSONA-FINDINGS---` blocks from subagent responses.

#### Synthesize Findings

Merge all persona findings into an attributed synthesis document:

```markdown
## Round-Table Synthesis: Sprint Execution Strategy

### [{Persona Name} -- {Role}]:
- {Finding/recommendation about batch ordering or execution plan}

### [{Persona Name} -- {Role}]:
- {Finding/recommendation about domain-specific risks}

### Consensus:
- [Agreed] {Point all personas support}
- [Debated] {Point with disagreement} -- {Persona A} suggests X, {Persona B} suggests Y -> escalating to user

### Risks Identified:
- [{Persona}] {Risk description with affected tasks/batches}

### Recommended Plan Adjustments:
- {Specific adjustment with rationale from persona analysis}
```

**Critical rule**: Disagreements between personas are ALWAYS surfaced to the user for decision. The orchestrator/lead never resolves disagreements autonomously.

#### Present Synthesis

Present the round-table synthesis to the user alongside the execution plan. The user reviews persona recommendations as part of the execution plan approval below.

> **Reference**: This implements Section C from `_round-table-blocks.md`, adapted for sprint execution strategy review.

After displaying the plan (and round-table synthesis if enabled), ask the user to approve before execution begins:

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
- The subagent submits self-review evidence via `submit_self_review()` and returns — it does NOT dispatch reviewer subagents or mark tasks complete
- **Review dispatch happens at the orchestrator level** (Step 4.4) — the orchestrator checks self-review, optionally dispatches a reviewer subagent, and handles the approve/reject flow
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
5. Read .sdlc/config.yaml — check `git.auto_commit`:
   - If `true`: git add <files> && git commit -m "[{task_id}] {task_title}"
   - If `false` or not set: git add <files> only — do NOT commit. Leave changes staged for user review.
6. Read .sdlc/config.yaml — check `testing.runtime` for runtime test configuration

## Review Gates

After completing implementation and tests:
1. Self-review: Re-read the task spec, verify each acceptance criterion
   - Read .sdlc/config.yaml — check `testing.relevance.enabled`
   - If relevance detection is enabled:
     a. Assess change scope based on files you modified:
        - backend-logic: .py files with business logic → RUN unit tests
        - api-endpoints: route handlers, middleware → RUN unit + integration
        - database: models, migrations → RUN unit + integration
        - documentation: .md files, docstrings, skill templates → SKIP all tests
        - configuration: .yaml, .env, build configs → SKIP unit tests
        - test-only: test files only → RUN unit tests
     b. For SKIP verdicts, output rationale: "Skipping unit tests: documentation-only change (modified {file})"
     c. For RUN verdicts, execute the command from `testing.commands.{type}` and capture output
   - If relevance detection is disabled or absent:
     Run ALL commands under `testing.commands` (e.g. pytest, lint, typecheck)
   - If no config exists, run the project's default test command
   - Capture and include ACTUAL test output for any tests run — no self-assertions without evidence
   - If any executed test fails, fix the issues before proceeding
2. Call `mcp__asdlc__submit_self_review(task_id='{task_id}', verdict='pass'|'fail', findings='...', test_output='...')` with actual test output
3. If self-review verdict is 'fail', fix the issues and re-submit until 'pass'
4. Log corrections for EVERY finding discovered during implementation:
   mcp__asdlc__log_correction(context_type='task', context_id='{task_id}', category='{category}', description='{what_was_found_and_fixed}')
5. Do NOT call `update_task(status='completed')` — the orchestrator handles completion after review
6. If you encounter questions you cannot resolve from the provided context, surface them via AskUserQuestion — do NOT guess

## CRITICAL: Structured Output

Your FINAL output MUST end with this exact block. The orchestrator parses it
for progress tracking. Do NOT omit it. Do NOT add text after it.

---TASK-OUTCOME---
verdict: PASS|FAIL|BLOCKED
files_changed: file1.py, file2.py
tests: {passed}/{total}
review: APPROVE|REQUEST_CHANGES|ESCALATE
summary: {one-line description of what was done}
corrections: {number of corrections logged}
---END-OUTCOME---

Replace the placeholders with actual values from your implementation:
- verdict: PASS if task completed successfully, FAIL if it could not be completed, BLOCKED if dependencies are missing
- files_changed: comma-separated list of files you modified
- tests: number of tests passed / total tests run (e.g., "12/12")
- review: the final review verdict (APPROVE, REQUEST_CHANGES, or ESCALATE)
- summary: one sentence describing what you implemented
- corrections: integer count of corrections logged via log_correction()
""",
  subagent_type="{resolve via Section D from _round-table-blocks.md using task.component}"
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

# Task 1: dispatch subagent → orchestrator review → complete
update_task("PROJ-T00001", status="in_progress")
context_1 = build_context_package("PROJ-T00001", outcomes)
result_1 = Task(description="Implement PROJ-T00001: Set up OAuth config",
                prompt=f"...{context_1}...", subagent_type="sdlc-backend-engineer")
# Subagent returns after submitting self-review evidence
# Orchestrator review dispatch (Step 4.4):
review_result = orchestrator_review_dispatch("PROJ-T00001", review_config)
if review_result == "approved":
    update_task("PROJ-T00001", status="completed")
outcomes["PROJ-T00001"] = "Added OAuth config to src/auth/config.py"

# Task 2 (receives outcome of Task 1 in context if it's a dependency)
update_task("PROJ-T00002", status="in_progress")
context_2 = build_context_package("PROJ-T00002", outcomes)
result_2 = Task(description="Implement PROJ-T00002: Create login endpoint",
                prompt=f"...{context_2}...", subagent_type="sdlc-backend-engineer")
review_result = orchestrator_review_dispatch("PROJ-T00002", review_config)
if review_result == "approved":
    update_task("PROJ-T00002", status="completed")
outcomes["PROJ-T00002"] = "Created POST /auth/login endpoint in src/api/auth.py"

# Task 3
update_task("PROJ-T00003", status="in_progress")
context_3 = build_context_package("PROJ-T00003", outcomes)
result_3 = Task(description="Implement PROJ-T00003: Add user model fields",
                prompt=f"...{context_3}...", subagent_type="sdlc-backend-engineer")
review_result = orchestrator_review_dispatch("PROJ-T00003", review_config)
if review_result == "approved":
    update_task("PROJ-T00003", status="completed")
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

#### Structured Outcome Parsing

When a subagent returns, the orchestrator first attempts to extract the structured outcome block:

1. Search the subagent result for `---TASK-OUTCOME---` and `---END-OUTCOME---` delimiters
2. If found, parse the key-value pairs between the delimiters
3. Store the parsed data in outcomes as a structured dict:
   outcomes[task_id] = {
       "verdict": "PASS",
       "files_changed": ["file1.py", "file2.py"],
       "tests": "12/12",
       "review": "APPROVE",
       "summary": "One-line description",
       "corrections": 0
   }
4. If the delimiters are NOT found (subagent non-compliance), fall back to the existing
   extract_outcome_summary() approach — extract a 1-2 sentence summary from raw text.
   Store as: outcomes[task_id] = "free-form summary string"

The orchestrator should handle both dict-style (structured) and string-style (fallback)
outcomes gracefully in all downstream consumers (build_context_package, present_batch_results).

### 4.4. Review Dispatch (Orchestrator Level)

After the implementing subagent returns for a task, the orchestrator runs the review dispatch sequence before marking the task complete. This ensures review is handled at the orchestrator layer, not inside the implementing subagent.

**Config check**: Read `.sdlc/config.yaml` — if the `review` section exists AND `review.self_review.enabled` is `true`, review is enabled. If the entire `review` section is absent, review is disabled and the orchestrator skips directly to step 5 (complete task).

#### Review Dispatch Sequence

1. **Check self-review**: Call `mcp__asdlc__get_review_evidence(task_id='{task_id}')` — verify self-review was submitted
   - If missing → `mcp__asdlc__block_task(task_id='{task_id}', reason='self-review not submitted')` — task cannot complete
   - If present and verdict='fail' → `mcp__asdlc__block_task(task_id='{task_id}', reason='self-review failed')` — task cannot complete

2. **Check subagent review config**: Read `.sdlc/config.yaml` `review.subagent_review.enabled`
   - If disabled or absent → skip to step 5 (complete task)

3. **Dispatch reviewer subagent**: Launch a fresh Task agent:
   ```
   Task(
     description="Review {task_id}: {task_title}",
     prompt="You are an independent code reviewer. Review task {task_id}.

            Call mcp__asdlc__get_review_evidence(task_id='{task_id}') to read the self-review.
            Review the git diff and test output.

            Evaluate: spec compliance, code quality, test coverage.

            Call mcp__asdlc__submit_review_verdict(task_id='{task_id}', verdict='approve'|'request_changes'|'escalate', findings='...') with:
            - 'approve' if implementation meets all criteria
            - 'request_changes' if issues found (list specific fixes needed)
            - 'escalate' if you cannot determine correctness
            ",
     subagent_type="sdlc-qa-engineer"
   )
   ```

4. **Read verdict**: Call `mcp__asdlc__get_review_evidence(task_id='{task_id}')` — check the subagent review verdict
   - **APPROVE** → proceed to step 5
   - **REQUEST_CHANGES** → self-heal loop: dispatch the implementing subagent again with fix instructions from the reviewer's findings. Repeat up to `review.max_rounds` from config (default 3). After max rounds → AskUserQuestion with escalation options:
     ```
     AskUserQuestion({
       questions: [{
         question: "Task {task_id} failed review after {max_rounds} rounds. How to proceed?",
         header: "Review Escalation",
         options: [
           { label: "Override & complete", description: "Accept current implementation despite review findings" },
           { label: "Continue fixing", description: "Allow more review rounds" },
           { label: "Block task", description: "Mark task as blocked for manual handling" }
         ],
         multiSelect: false
       }]
     })
     ```
   - **ESCALATE** → AskUserQuestion immediately with the same options as above

5. **Complete task**: Call `mcp__asdlc__update_task(task_id='{task_id}', status='completed')` — the hard gate in `update_task()` accepts this because approved review evidence now exists in the database

#### Review Dispatch in Isolated Mode

The same review dispatch sequence applies to isolated mode (multi-PRD with worktrees). When the PRD agent returns after executing all tasks, the orchestrator runs the review dispatch for each task that the PRD agent reported as completed.

For isolated mode, the orchestrator:
1. Parses the structured outcome blocks from the PRD agent's output (one `---TASK-OUTCOME---` block per task)
2. For each task with `verdict: PASS`, runs the review dispatch sequence above
3. For each task with `verdict: FAIL` or `verdict: BLOCKED`, skips review and handles via the Batch Failure Handler

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

When a task fails its orchestrator-level review dispatch (Step 4.4) after the maximum number of review rounds (read `review.max_rounds` from `.sdlc/config.yaml`, default: 3), the batch pauses and the orchestrator consults the user immediately — do not wait for the entire batch to finish.

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

### 6.5. Domain Detection + Panel Assembly (Round-Table, Isolated Mode)

If round_table_enabled = true, perform domain detection across all PRDs in the sprint. This is the same detection as Step 2.5 (Simple Mode) but applied across multiple PRDs with worktree isolation context.

The panel assembly follows the same rules as Step 2.5. See that section for the full domain detection and panel assembly procedure.

**Isolated mode note**: The overlap analysis from Step 6 provides additional domain signals. If two PRDs touch different components, the panel should include domain personas for both component areas. The Architect persona is particularly valuable here for cross-PRD integration analysis.

> **Reference**: This implements Section B from `_round-table-blocks.md`, applied in isolated mode context.

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

### 8.6. Round-Table: Isolated Execution Strategy

If round_table_enabled = true, run the round-table discussion BEFORE presenting the isolated execution plan for user approval.

This follows the same pattern as Step 3.1 (Simple Mode round-table) with the following differences for isolated mode:

1. **Context packages per persona** include cross-PRD information:
   - **PM**: Sprint goal, ALL PRD summaries, cross-PRD business dependencies
   - **Architect**: Overlap analysis results (Step 6), worktree isolation strategy, cross-PRD integration points, merge conflict risk areas
   - **Frontend/Backend/DevOps**: Domain-specific tasks grouped by PRD, worktree-specific environment configurations
   - **QA**: Acceptance criteria from ALL PRDs, cross-PRD integration test requirements
   - **Security**: Security requirements spanning all PRDs, isolation boundary analysis

2. **Dispatch personas** following Section C from `_round-table-blocks.md` (same Agent Teams / Task tool detection and dispatch pattern as Step 3.1).

3. **Synthesis** should additionally address:
   - PRD execution ordering recommendations (which PRDs to prioritize)
   - Cross-PRD integration risks that may surface during merge
   - Worktree isolation adequacy (are the PRDs sufficiently independent?)

Present the round-table synthesis to the user alongside the isolated execution plan below.

> **Reference**: This implements Section C from `_round-table-blocks.md`, adapted for isolated multi-PRD execution strategy.

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
4. Read .sdlc/config.yaml — check `git.auto_commit`:
   - If `true`: git add <files> && git commit -m "[{task_id}] {task_title}"
   - If `false` or not set: git add <files> only — do NOT commit. Leave changes staged for user review.
5. Read .sdlc/config.yaml — check `testing.runtime` for runtime test configuration
6. Run review gates (see below)
7. Do NOT call `update_task(status='completed')` — the orchestrator handles completion after review

## Batch 1 (independent tasks):

### Task: PROJ-T00001 — Set up OAuth config
{context_package_for_PROJ-T00001}

### Task: PROJ-T00002 — Create login endpoint
{context_package_for_PROJ-T00002}

## Batch 2 (depends on Batch 1):

### Task: PROJ-T00003 — Add token validation
{context_package_for_PROJ-T00003}

## Review Gates (for EACH task)

After completing implementation and tests for each task:
1. Self-review: Re-read the task's Acceptance Criteria from its context package above, verify each criterion is satisfied
   - Read .sdlc/config.yaml — check `testing.relevance.enabled`
   - If relevance detection is enabled:
     a. Assess change scope based on files you modified:
        - backend-logic: .py files with business logic → RUN unit tests
        - api-endpoints: route handlers, middleware → RUN unit + integration
        - database: models, migrations → RUN unit + integration
        - documentation: .md files, docstrings, skill templates → SKIP all tests
        - configuration: .yaml, .env, build configs → SKIP unit tests
        - test-only: test files only → RUN unit tests
     b. For SKIP verdicts, output rationale: "Skipping unit tests: documentation-only change (modified {file})"
     c. For RUN verdicts, execute the command from `testing.commands.{type}` and capture output
   - If relevance detection is disabled or absent:
     Run ALL commands under `testing.commands` (e.g. pytest, lint, typecheck)
   - If no config exists, run the project's default test command
   - Capture and include ACTUAL test output for any tests run — no self-assertions without evidence
   - If any executed test fails, fix the issues before proceeding
2. Call `mcp__asdlc__submit_self_review(task_id='{task_id}', verdict='pass'|'fail', findings='...', test_output='...')` with actual test output
3. If self-review verdict is 'fail', fix the issues and re-submit until 'pass'
4. Log corrections for EVERY finding discovered during implementation:
   mcp__asdlc__log_correction(context_type='task', context_id='{task_id}', category='{category}', description='{what_was_found_and_fixed}')
5. Do NOT call `update_task(status='completed')` — the orchestrator handles completion after review
6. If you encounter unresolvable questions, surface them via AskUserQuestion — do NOT guess

## CRITICAL: Structured Output (per task)

After completing EACH task in your batch, output a structured outcome block.
Your output for each task MUST include:

---TASK-OUTCOME---
task_id: {task_id}
verdict: PASS|FAIL|BLOCKED
files_changed: file1.py, file2.py
tests: {passed}/{total}
review: APPROVE|REQUEST_CHANGES|ESCALATE
summary: {one-line description of what was done}
corrections: {number of corrections logged}
---END-OUTCOME---

The orchestrator parses these blocks for progress tracking.
Replace placeholders with actual values from your implementation.

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
   - **Simple mode**: Run orchestrator review dispatch (Step 4.4), then mark task as COMPLETED if approved. Check if blocked tasks are unblocked, launch them.
   - **Isolated mode**: All tasks for that PRD are done. Run orchestrator review dispatch for each task (Step 4.4). Report branch name and worktree path.
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
def run_sprint(sprint_id: str, max_parallel: int = 3, base_branch: str = None,
               resume_flag: bool = False, solo: bool = False):
    sprint = get_sprint(sprint_id)
    grouped = get_sprint_tasks(sprint_id, group_by_prd=True)
    prd_groups = grouped["prd_groups"]

    # --- Persona Availability Check (Step 1.6) ---
    round_table_enabled = False
    if not solo:
        persona_files = Glob("~/.claude/agents/sdlc-*.md")
        if persona_files:
            round_table_enabled = True

    # --- Check for --resume flag (FR-005, Step 1.5) ---
    resume_state = None
    if resume_flag:
        context = mcp__asdlc__get_context()
        project_id = context["project_id"]
        state_file = f"~/.a-sdlc/runs/{project_id}/{sprint_id}-state.json"
        try:
            state_content = Read(state_file)
            resume_state = json.loads(state_content)
            # Display resume progress summary (see Step 1.5)
        except FileNotFoundError:
            warn(f"No checkpoint found for {sprint_id}. Starting fresh.")

    # Check git safety config for worktree support
    config = get_git_safety_config()
    worktree_enabled = config["config"]["effective"]["worktree_enabled"]

    # MODE DETECTION — worktree_enabled gates isolated mode
    if len(prd_groups) == 1 or not worktree_enabled:
        if len(prd_groups) > 1 and not worktree_enabled:
            warn("Multiple PRDs but worktree isolation disabled. Running sequentially.")
        run_simple_mode(sprint_id, prd_groups, max_parallel, resume_state, round_table_enabled)
    else:
        run_isolated_mode(sprint_id, prd_groups, max_parallel, base_branch, resume_state, round_table_enabled)


def run_simple_mode(sprint_id, prd_groups, max_parallel, resume_state=None,
                    round_table_enabled=False):
    """Single PRD or worktree-disabled — run tasks directly in working directory."""
    # Flatten all tasks across PRD groups
    tasks = [t for group in prd_groups for t in group["tasks"]]

    # Build dependency-ordered batches
    batches, unresolvable = build_batches(tasks)

    if unresolvable:
        warn_circular_deps(unresolvable)
        # Present unresolvable tasks to user before proceeding
        # Execution continues with the batches that CAN be resolved

    # --- Domain Detection + Panel Assembly (Step 2.5) ---
    persona_panel = None
    if round_table_enabled:
        persona_panel = detect_domains_and_assemble_panel(prd_groups, tasks)

    # --- Round-Table: Sprint Execution Strategy (Step 3.1) ---
    round_table_synthesis = None
    if round_table_enabled and persona_panel:
        round_table_synthesis = run_round_table(
            persona_panel, sprint_id, batches, prd_groups,
            topic="sprint_execution_strategy"
        )

    # --- Present execution plan and get user approval (Step 3) ---
    present_execution_plan(sprint_id, batches, unresolvable)
    if round_table_synthesis:
        present_round_table_synthesis(round_table_synthesis)
    plan_decision = ask_plan_approval()  # AskUserQuestion: Start/Adjust/Abort
    if plan_decision == "abort":
        report("Sprint execution cancelled by user.")
        return
    if plan_decision == "adjust":
        batches = apply_user_adjustments(batches)  # Re-display and re-ask
        # Loop until user chooses "start" or "abort"

    outcomes = {}  # {task_id: outcome_summary} — fed to build_context_package
    user_clarification = None  # Optional text from user, injected into context

    # --- State persistence setup (FR-001) ---
    # State file lives at ~/.a-sdlc/runs/{project_id}/{sprint-id}-state.json
    # The project_id comes from get_context() response
    context = mcp__asdlc__get_context()
    project_id = context["project_id"]
    state_dir = f"~/.a-sdlc/runs/{project_id}"
    state_file = f"{state_dir}/{sprint_id}-state.json"
    state_tmp = f"{state_dir}/{sprint_id}-state.tmp.json"
    sprint_started_at = current_iso_timestamp()

    # Ensure directory exists
    Bash(f"mkdir -p {state_dir}")

    # --- Context budget tracking (FR-004) ---
    context_chars_consumed = 0  # Running character count

    # Read budget from config (optional)
    # .sdlc/config.yaml may contain:
    #   sprint:
    #     context_budget: 150000
    budget_tokens = 150000  # Default
    try:
        config = Read(".sdlc/config.yaml")
        if "sprint:" in config and "context_budget:" in config:
            budget_tokens = int(config.sprint.context_budget)
    except:
        pass  # Use default

    # --- Auto-compact thresholds (FR-005) ---
    compact_threshold = 70   # Warn and pause at this percentage
    urgent_threshold = 85    # Warn urgently
    halt_threshold = 95      # Halt execution

    # Optional: read from .sdlc/config.yaml
    #   sprint:
    #     compact_threshold: 70
    try:
        if "compact_threshold:" in config:
            compact_threshold = int(config.sprint.compact_threshold)
    except:
        pass  # Use defaults

    # --- Resume support (FR-005) ---
    # If resuming, pre-populate outcomes and context budget from checkpoint
    starting_batch = 0
    if resume_state:
        outcomes = resume_state["outcomes"]
        starting_batch = resume_state["current_batch"]
        # Restore context budget tracking from checkpoint
        if "context_budget" in resume_state:
            context_chars_consumed = resume_state["context_budget"]["chars_consumed"]

    def write_state_checkpoint(outcomes, batches, batch_num, mode="simple"):
        """Write current execution state to disk atomically.

        Uses Write tool to create .tmp file, then Bash mv to rename.
        This ensures the state file is always valid JSON (NFR-001).
        """
        state = {
            "version": 1,
            "sprint_id": sprint_id,
            "project_id": project_id,
            "started_at": sprint_started_at,
            "updated_at": current_iso_timestamp(),
            "mode": mode,
            "current_batch": batch_num,
            "total_batches": len(batches),
            "outcomes": outcomes,
            "skipped": [tid for tid, o in outcomes.items() if isinstance(o, str) and "skipped" in o],
            "failed": {tid: o for tid, o in outcomes.items() if isinstance(o, str) and "failed" in o},
            "batches": [
                {"batch_num": i+1, "task_ids": [t["id"] for t in b]}
                for i, b in enumerate(batches)
            ]
        }

        # --- Include context budget in state (FR-004) ---
        state["context_budget"] = {
            "chars_consumed": context_chars_consumed,
            "estimated_tokens": context_chars_consumed // 4,
            "budget_tokens": budget_tokens,
            "percentage": round((context_chars_consumed // 4) / budget_tokens * 100, 1)
        }

        # Atomic write: tmp file → rename
        Write(state_tmp, json.dumps(state, indent=2))
        Bash(f"mv {state_tmp} {state_file}")

    for batch_num, batch in enumerate(batches, 1):
        # --- Skip completed batches on resume (FR-005) ---
        if resume_state and batch_num <= starting_batch:
            all_done = all(t["id"] in outcomes for t in batch)
            if all_done:
                continue  # Entire batch was completed previously

        # --- Filter out tasks with unmet dependencies (failed/skipped deps) ---
        # Also exclude already-completed tasks (resume scenario)
        executable = [t for t in batch
                      if t["id"] not in outcomes  # Not already completed (resume)
                      and deps_satisfied(t, outcomes)]
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

            # --- Track context consumption (FR-004) ---
            context_chars_consumed += len(str(result))
            # Estimate orchestrator output overhead (~500 chars per task for display)
            context_chars_consumed += 500

            # --- Orchestrator Review Dispatch (Step 4.4) ---
            review_config = load_review_config()  # from .sdlc/config.yaml
            if review_config.get("self_review", {}).get("enabled", False):
                review_result = orchestrator_review_dispatch(task, review_config)
                # review_result: "approved", "blocked", or "escalated"

                if review_result == "blocked":
                    # Handle review failure (Batch Failure Handler)
                    rounds = review_result.rounds
                    if rounds >= review_config.get("max_rounds", 3):
                        failure_decision = ask_failure_handler(task, review_result.feedback)
                        if failure_decision == "retry":
                            result = dispatch_subagent(task, context, fresh=True)
                            review_result = orchestrator_review_dispatch(task, review_config)
                        elif failure_decision == "skip":
                            update_task(task["id"], status="blocked", reason="review failure")
                        elif failure_decision == "abort_batch":
                            record_outcome(task, result, outcomes)
                            break  # Exit batch loop, proceed to checkpoint
                        elif failure_decision == "manual":
                            update_task(task["id"], status="blocked", reason="manual impl")
                            log_correction(task["id"], "review", "Deferred to manual")

                if review_result == "approved":
                    update_task(task["id"], status="completed")
            else:
                # Review disabled — complete task directly
                update_task(task["id"], status="completed")

            record_outcome(task, result, outcomes)
            batch_results[task["id"]] = result

            # --- Checkpoint state after task completion (FR-001) ---
            write_state_checkpoint(outcomes, batches, batch_num)

            # --- Intra-batch context check (FR-005) ---
            estimated_tokens = context_chars_consumed // 4
            budget_percentage = (estimated_tokens / budget_tokens) * 100

            if budget_percentage >= halt_threshold:
                write_state_checkpoint(outcomes, batches, batch_num)
                print(f"🛑 Context budget critical (~{budget_percentage:.0f}%). Halting mid-batch. State saved.")
                print(f"Resume: /compact → /sdlc:sprint-run {sprint_id} --resume")
                return  # Emergency exit

        # --- Batch checkpoint (Step 4.5) ---
        present_batch_results(batch_num, batch_results, skipped)

        # --- Persist state at batch boundary (FR-001) ---
        write_state_checkpoint(outcomes, batches, batch_num)

        # --- Context budget display (FR-004, AC-003) ---
        estimated_tokens = context_chars_consumed // 4
        budget_percentage = (estimated_tokens / budget_tokens) * 100

        # Display context health with color-coded indicator
        if budget_percentage < 50:
            budget_indicator = "🟢"
        elif budget_percentage < 70:
            budget_indicator = "🟡"
        elif budget_percentage < 85:
            budget_indicator = "🟠"
        else:
            budget_indicator = "🔴"

        print(f"{budget_indicator} Context: ~{budget_percentage:.0f}% estimated ({estimated_tokens:,}/{budget_tokens:,} tokens)")

        # --- Auto-compact guidance (FR-005) ---
        if budget_percentage >= halt_threshold:
            # HALT: Context critically high
            write_state_checkpoint(outcomes, batches, batch_num)
            print(f"""
🛑 CONTEXT BUDGET CRITICAL: ~{budget_percentage:.0f}%
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Execution halted to prevent context overflow.
State saved to: {state_file}

To resume after compacting:
  1. Run /compact
  2. Run /sdlc:sprint-run {sprint_id} --resume
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            """)
            break  # Exit the batch loop — halt execution

        elif budget_percentage >= urgent_threshold:
            # URGENT WARNING
            write_state_checkpoint(outcomes, batches, batch_num)
            print(f"""
⚠️ CONTEXT BUDGET HIGH: ~{budget_percentage:.0f}%
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
State saved. Strongly recommend compacting NOW.

To resume:
  1. Run /compact
  2. Run /sdlc:sprint-run {sprint_id} --resume

Execution will HALT at {halt_threshold}%.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            """)
            # Continue execution but user is warned

        elif budget_percentage >= compact_threshold:
            # PAUSE: Recommend compacting
            write_state_checkpoint(outcomes, batches, batch_num)

            compact_decision = AskUserQuestion({
                questions: [{
                    question: f"Context budget at ~{budget_percentage:.0f}%. State saved. Compact now?",
                    header: "Context",
                    options: [
                        { label: "Compact & resume", description: f"Run /compact, then /sdlc:sprint-run {sprint_id} --resume" },
                        { label: "Continue", description: f"Keep going (will warn again at {urgent_threshold}%, halt at {halt_threshold}%)" },
                        { label: "Abort sprint", description: "Stop execution, state is saved" }
                    ],
                    multiSelect: false
                }]
            })

            if compact_decision == "Compact & resume":
                print(f"""
State saved to: {state_file}

Next steps:
  1. Run /compact
  2. Run /sdlc:sprint-run {sprint_id} --resume
                """)
                return  # Exit run_simple_mode — user will compact and resume
            elif compact_decision == "Abort sprint":
                print("Sprint execution aborted. State saved for later resume.")
                return
            # "Continue" — proceed to next batch

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

    # --- Clean up state file on successful completion (FR-006) ---
    # Archive with timestamp for debugging, then remove active state file
    timestamp = current_iso_timestamp().replace(":", "-")
    Bash(f"mv {state_file} {state_dir}/{sprint_id}-state.{timestamp}.json 2>/dev/null || true")


def dispatch_subagent(task: dict, context_package: str, fresh: bool = False) -> Result:
    """Dispatch a single task to a fresh subagent and wait for completion.

    The subagent implements the task and submits self-review evidence via
    submit_self_review(). It does NOT dispatch reviewer subagents or mark
    the task as completed — that happens at the orchestrator level (Step 4.4).

    Args:
        task: Task metadata dict with id, title, etc.
        context_package: Inline text from build_context_package().
        fresh: If True, this is a retry — add retry context to prompt.

    Returns:
        Result with: success (bool), outcome_summary (str).
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
        subagent_type="{resolve via Section D from _round-table-blocks.md using task.component}",
        # run_in_background=false — orchestrator waits
    )

    return parse_subagent_result(result)


def orchestrator_review_dispatch(task: dict, review_config: dict) -> str:
    """Run the orchestrator-level review dispatch for a completed task.

    Implements Step 4.4: checks self-review evidence, optionally dispatches
    a reviewer subagent, and handles the approve/reject/escalate flow.

    Args:
        task: Task metadata dict with id, title, etc.
        review_config: The 'review' section from .sdlc/config.yaml.

    Returns:
        "approved" if review passed, "blocked" if review failed.
    """
    task_id = task["id"]

    # 1. Check self-review evidence
    evidence = mcp__asdlc__get_review_evidence(task_id=task_id)
    if not evidence.get("self_review"):
        mcp__asdlc__block_task(task_id=task_id, reason="self-review not submitted")
        return "blocked"
    if evidence["self_review"]["verdict"] == "fail":
        mcp__asdlc__block_task(task_id=task_id, reason="self-review failed")
        return "blocked"

    # 2. Check if subagent review is enabled
    if not review_config.get("subagent_review", {}).get("enabled", False):
        return "approved"  # Skip subagent review, proceed to completion

    # 3. Dispatch reviewer subagent
    max_rounds = review_config.get("max_rounds", 3)
    for round_num in range(1, max_rounds + 1):
        reviewer_result = Task(
            description=f"Review {task_id}: {task['title']}",
            prompt=REVIEWER_PROMPT_TEMPLATE.format(task_id=task_id),
            subagent_type="sdlc-qa-engineer",
        )

        # 4. Read verdict
        evidence = mcp__asdlc__get_review_evidence(task_id=task_id)
        verdict = evidence.get("review_verdict", {}).get("verdict", "")

        if verdict == "approve":
            return "approved"
        elif verdict == "escalate":
            # Escalate to user immediately
            decision = ask_escalation(task_id, evidence)
            if decision == "override":
                return "approved"
            else:
                return "blocked"
        elif verdict == "request_changes":
            if round_num < max_rounds:
                # Re-dispatch implementing subagent with fix instructions
                dispatch_subagent(task, context_with_fix_instructions, fresh=True)
            # else: loop ends, escalate below

    # Max rounds reached — escalate to user
    return "blocked"


# record_outcome() and extract_outcome_summary() — see Step 4.3 above for full definitions


def run_isolated_mode(sprint_id, prd_groups, max_parallel, base_branch,
                      resume_state=None, round_table_enabled=False):
    """Multiple PRDs — one worktree per PRD."""
    # --- State persistence setup (FR-001) ---
    context = mcp__asdlc__get_context()
    project_id = context["project_id"]
    state_dir = f"~/.a-sdlc/runs/{project_id}"
    state_file = f"{state_dir}/{sprint_id}-state.json"
    state_tmp = f"{state_dir}/{sprint_id}-state.tmp.json"
    sprint_started_at = current_iso_timestamp()
    Bash(f"mkdir -p {state_dir}")

    # --- Context budget tracking (FR-004) ---
    context_chars_consumed = 0  # Running character count

    # Read budget from config (optional)
    budget_tokens = 150000  # Default
    try:
        config = Read(".sdlc/config.yaml")
        if "sprint:" in config and "context_budget:" in config:
            budget_tokens = int(config.sprint.context_budget)
    except:
        pass  # Use default

    # --- Auto-compact thresholds (FR-005) ---
    compact_threshold = 70   # Warn and pause at this percentage
    urgent_threshold = 85    # Warn urgently
    halt_threshold = 95      # Halt execution

    # Optional: read from .sdlc/config.yaml
    #   sprint:
    #     compact_threshold: 70
    try:
        if "compact_threshold:" in config:
            compact_threshold = int(config.sprint.compact_threshold)
    except:
        pass  # Use defaults

    def write_state_checkpoint(outcomes, prd_groups, mode="isolated"):
        """Write current execution state to disk atomically."""
        state = {
            "version": 1,
            "sprint_id": sprint_id,
            "project_id": project_id,
            "started_at": sprint_started_at,
            "updated_at": current_iso_timestamp(),
            "mode": mode,
            "prd_groups": [
                {"prd_id": g["prd_id"], "task_count": len(g["tasks"])}
                for g in prd_groups
            ],
            "outcomes": outcomes,
        }

        # --- Include context budget in state (FR-004) ---
        state["context_budget"] = {
            "chars_consumed": context_chars_consumed,
            "estimated_tokens": context_chars_consumed // 4,
            "budget_tokens": budget_tokens,
            "percentage": round((context_chars_consumed // 4) / budget_tokens * 100, 1)
        }

        Write(state_tmp, json.dumps(state, indent=2))
        Bash(f"mv {state_tmp} {state_file}")

    outcomes = {}  # Track outcomes across all PRD agents

    # --- Resume support (FR-005) ---
    # If resuming, pre-populate outcomes and context budget from checkpoint
    if resume_state:
        outcomes = resume_state.get("outcomes", {})
        # Restore context budget tracking from checkpoint
        if "context_budget" in resume_state:
            context_chars_consumed = resume_state["context_budget"]["chars_consumed"]

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

    # --- Domain Detection + Panel Assembly (Step 6.5) ---
    persona_panel = None
    if round_table_enabled:
        all_tasks = [t for g in prd_groups for t in g["tasks"]]
        persona_panel = detect_domains_and_assemble_panel(prd_groups, all_tasks)

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

    # --- Round-Table: Isolated Execution Strategy (Step 8.6) ---
    round_table_synthesis = None
    if round_table_enabled and persona_panel:
        round_table_synthesis = run_round_table(
            persona_panel, sprint_id, prd_groups,
            topic="isolated_execution_strategy"
        )

    # --- Present isolated plan and get user approval (Step 9) ---
    present_isolated_plan(sprint_id, prd_groups)
    if round_table_synthesis:
        present_round_table_synthesis(round_table_synthesis)
    # User confirms execution (existing Step 9 confirmation flow)

    # --- Launch one agent per PRD (up to max_parallel) ---
    # Each agent receives pre-built context packages organized by batch
    active = {}
    queue = list(prd_groups)

    # --- Skip fully-completed PRD groups on resume (FR-005) ---
    if resume_state:
        remaining = []
        for group in queue:
            all_task_ids = [t["id"] for t in group["tasks"]]
            all_done = all(tid in outcomes for tid in all_task_ids)
            if all_done:
                continue  # Skip — all tasks for this PRD were completed previously
            remaining.append(group)
        queue = remaining

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

        completed_prd, prd_result = wait_for_any(active)
        del active[completed_prd]

        # --- Track context consumption (FR-004) ---
        context_chars_consumed += len(str(prd_result))
        context_chars_consumed += 500  # Orchestrator overhead estimate

        # --- Orchestrator Review Dispatch for isolated mode (Step 4.4) ---
        # Parse task outcomes from the PRD agent's structured output
        task_outcomes = parse_prd_agent_task_outcomes(prd_result)
        review_config = load_review_config()  # from .sdlc/config.yaml

        for task_id, task_outcome in task_outcomes.items():
            if task_outcome["verdict"] == "PASS" and review_config.get("self_review", {}).get("enabled", False):
                task = get_task_by_id(task_id)
                review_result = orchestrator_review_dispatch(task, review_config)
                if review_result == "approved":
                    update_task(task_id, status="completed")
                # else: task remains in current status (blocked by review dispatch)
            elif task_outcome["verdict"] == "PASS":
                # Review disabled — complete task directly
                update_task(task_id, status="completed")
            # FAIL/BLOCKED tasks: already handled by the PRD agent

        # --- Checkpoint state after PRD agent completion (FR-001) ---
        outcomes[completed_prd] = {"task_outcomes": task_outcomes}
        write_state_checkpoint(outcomes, prd_groups)

        # --- Context budget display (FR-004, AC-003) ---
        estimated_tokens = context_chars_consumed // 4
        budget_percentage = (estimated_tokens / budget_tokens) * 100

        # Display context health with color-coded indicator
        if budget_percentage < 50:
            budget_indicator = "🟢"
        elif budget_percentage < 70:
            budget_indicator = "🟡"
        elif budget_percentage < 85:
            budget_indicator = "🟠"
        else:
            budget_indicator = "🔴"

        print(f"{budget_indicator} Context: ~{budget_percentage:.0f}% estimated ({estimated_tokens:,}/{budget_tokens:,} tokens)")

        # --- Auto-compact guidance (FR-005) ---
        if budget_percentage >= halt_threshold:
            # HALT: Context critically high
            write_state_checkpoint(outcomes, prd_groups)
            print(f"""
🛑 CONTEXT BUDGET CRITICAL: ~{budget_percentage:.0f}%
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Execution halted to prevent context overflow.
State saved to: {state_file}

To resume after compacting:
  1. Run /compact
  2. Run /sdlc:sprint-run {sprint_id} --resume
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            """)
            # Stop launching new PRD agents — exit the while loop
            break

        elif budget_percentage >= urgent_threshold:
            # URGENT WARNING
            write_state_checkpoint(outcomes, prd_groups)
            print(f"""
⚠️ CONTEXT BUDGET HIGH: ~{budget_percentage:.0f}%
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
State saved. Strongly recommend compacting NOW.

To resume:
  1. Run /compact
  2. Run /sdlc:sprint-run {sprint_id} --resume

Execution will HALT at {halt_threshold}%.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            """)
            # Continue execution but user is warned

        elif budget_percentage >= compact_threshold:
            # PAUSE: Recommend compacting
            write_state_checkpoint(outcomes, prd_groups)

            compact_decision = AskUserQuestion({
                questions: [{
                    question: f"Context budget at ~{budget_percentage:.0f}%. State saved. Compact now?",
                    header: "Context",
                    options: [
                        { label: "Compact & resume", description: f"Run /compact, then /sdlc:sprint-run {sprint_id} --resume" },
                        { label: "Continue", description: f"Keep going (will warn again at {urgent_threshold}%, halt at {halt_threshold}%)" },
                        { label: "Abort sprint", description: "Stop execution, state is saved" }
                    ],
                    multiSelect: false
                }]
            })

            if compact_decision == "Compact & resume":
                print(f"""
State saved to: {state_file}

Next steps:
  1. Run /compact
  2. Run /sdlc:sprint-run {sprint_id} --resume
                """)
                return  # Exit run_isolated_mode — user will compact and resume
            elif compact_decision == "Abort sprint":
                print("Sprint execution aborted. State saved for later resume.")
                return
            # "Continue" — proceed to next PRD agent

    # Branch completion — use complete_prd_worktree with config-aware options
    config = get_git_safety_config()
    for group in prd_groups:
        action = prompt_completion_action(group["prd_id"], config)
        complete_prd_worktree(prd_id=group["prd_id"], action=action)

    generate_isolated_report(sprint_id, prd_groups)

    # --- Clean up state file on successful completion (FR-006) ---
    timestamp = current_iso_timestamp().replace(":", "-")
    Bash(f"mv {state_file} {state_dir}/{sprint_id}-state.{timestamp}.json 2>/dev/null || true")
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

# Resume after context compact
/sdlc:sprint-run PROJ-S0001 --resume

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
