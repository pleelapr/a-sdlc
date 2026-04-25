# /sdlc:sprint-run

## Purpose

Execute sprint tasks using subagent dispatch. Automatically detects whether the sprint has **one PRD** (simple mode) or **multiple PRDs** (isolated mode with git worktrees). Independent tasks run concurrently while respecting dependency chains.

---

## Agent Execution vs Task Management

This skill launches subagents to execute a-sdlc tasks. Key distinction:

- **Agent = Execution unit** (launched via the orchestrator's `Task` tool)
- **a-sdlc Task = Work item** (retrieved/updated via `mcp__asdlc__*` tools)

**Each agent MUST:**
1. Call `mcp__asdlc__get_task(task_id)` to fetch task details
2. Execute the implementation steps from the task content
3. Submit self-review evidence via `mcp__asdlc__submit_review(reviewer_type='self')` — the **orchestrator** handles task completion after review

**Do NOT** create intermediate task-tracking items (TodoWrite/TaskCreate). The a-sdlc task IS the work item.

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
   config = mcp__asdlc__manage_git_safety("get")
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
    mcp__asdlc__manage_git_safety("configure", worktree_enabled=True)

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

### Step 1.7: Pre-Flight Quality Check

**Config-gated**: Only runs if quality is enabled. If `.sdlc/config.yaml` does not exist, or `quality.enabled` is `false` or absent, skip this entire section (backward compatibility per AC-007).

```python
# Load quality config
quality_config = load_quality_config()  # from quality_config.py

if not quality_config.enabled:
    # Quality system disabled — skip pre-flight quality check
    pass
else:
    # 1. Run sprint quality report
    report = mcp__asdlc__get_quality_report("sprint", sprint_id=sprint_id)

    if report["status"] == "ok":
        # 2. Display coverage summary
        agg = report["aggregate"]
        print(f"""
Pre-Flight Quality Report for {sprint_id}:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Requirements: {agg["linked_requirements"]}/{agg["total_requirements"]} linked
  Orphaned:     {agg["orphaned_requirements"]} requirements with no linked tasks
  ACs:          {agg["verified_acs"]}/{agg["total_acs"]} verified
  Scope drift:  {report["scope_drift"]["unlinked_count"]} tasks with no requirement links
  Overall:      {"PASS" if report.get("pass", False) else "GAPS DETECTED"}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        """)

        # 3. Check for unresolved PRD/design/split challenges
        # Load challenge gate mode from quality config (default: "soft")
        quality_cfg = {}
        try:
            cfg_path = Path(".sdlc/config.yaml")
            if cfg_path.exists():
                with open(cfg_path) as f:
                    cfg = yaml.safe_load(f) or {}
                quality_cfg = cfg.get("quality", {})
        except Exception:
            pass
        challenge_cfg = quality_cfg.get("challenge", {}) if isinstance(quality_cfg, dict) else {}
        challenge_gate_mode = challenge_cfg.get("gate", "soft") if isinstance(challenge_cfg, dict) else "soft"

        for prd_report in report.get("prd_reports", []):
            prd_id = prd_report["prd_id"]
            for artifact_type in ["prd", "design", "split"]:
                challenge_status = mcp__asdlc__get_challenge_status(
                    artifact_type=artifact_type,
                    artifact_id=prd_id
                )
                if challenge_status.get("challenge_status") not in ("resolved", "unchallenged"):
                    if challenge_gate_mode == "hard":
                        # BLOCK: unresolved challenge prevents sprint execution under hard gate
                        print(f"  BLOCKED: {artifact_type} {prd_id} has unresolved challenge (hard gate) — status: {challenge_status['challenge_status']}")
                        action = AskUserQuestion(
                            f"Unresolved challenge on {artifact_type} {prd_id} blocks sprint execution (hard gate). How to proceed?",
                            options=["Re-challenge now", "Waive and continue", "Abort sprint"]
                        )
                        if action == "Abort sprint":
                            print("  Sprint aborted by user due to unresolved challenge.")
                            return
                        elif action == "Re-challenge now":
                            print(f"  Re-challenge {artifact_type} {prd_id} before continuing.")
                            mcp__asdlc__challenge_artifact(artifact_type=artifact_type, artifact_id=prd_id)
                        else:
                            print(f"  Waived challenge block on {artifact_type} {prd_id}. Continuing.")
                    else:
                        # Soft gate: warn and continue
                        print(f"  WARNING (soft gate): {artifact_type} {prd_id} has unresolved challenge — status: {challenge_status['challenge_status']}")

        # 4. If orphaned requirements or gaps exist, create remediation tasks (AC-021)
        if agg["orphaned_requirements"] > 0 or not report.get("pass", True):
            remediation_result = mcp__asdlc__create_remediation_tasks(sprint_id=sprint_id)
            if remediation_result["status"] == "ok" and remediation_result.get("created_count", 0) > 0:
                print(f"\n  Created {remediation_result['created_count']} remediation tasks:")
                for rt in remediation_result.get("tasks", []):
                    print(f"    {rt['task_id']}: {rt['title']}")
                print("  Remediation tasks added to execution queue.")
                # Re-fetch sprint tasks to include newly created remediation tasks
                all_tasks = mcp__asdlc__get_sprint_tasks(sprint_id=sprint_id)
                batches, unresolvable = build_batches(all_tasks["tasks"])
                print(f"  Re-built execution plan: {len(batches)} batches with remediation tasks included.")
            else:
                print("  No remediation tasks needed or creation returned no tasks.")
    else:
        print(f"  Quality report failed: {report.get('message', 'unknown error')}. Proceeding without quality check.")
```

### Step 1.8: Agent Governance Integration

**Config-gated**: Only runs if `governance.enabled` is `true` in `.sdlc/config.yaml`. If absent or `false`, skip this entire section (backward compatibility).

```python
# Load governance config
from pathlib import Path
import yaml

config_path = Path(".sdlc/config.yaml")
governance_enabled = False
if config_path.exists():
    with open(config_path) as f:
        config = yaml.safe_load(f) or {}
    governance_enabled = config.get("governance", {}).get("enabled", False)

if governance_enabled:
    # 1. Team health pre-flight
    teams = mcp__asdlc__list_agent_teams(project_id=project_id)
    for team in teams.get("teams", []):
        health = mcp__asdlc__enforce_team_health(team_id=team["id"])
        if health["status"] == "ok":
            summary = health["summary"]
            print(f"  Team '{health['team_name']}': "
                  f"{summary['healthy']}/{summary['total_members']} healthy")
            if summary["unhealthy"] > 0:
                for action in health.get("actions_taken", []):
                    print(f"    Action: {action['action']} on {action['agent_id']}: "
                          f"{', '.join(action['issues'])}")

    # 2. Auto-composition suggestion
    compose = mcp__asdlc__auto_compose_team(sprint_id=sprint_id)
    if compose["status"] == "ok" and compose.get("proposed_assignments"):
        print(f"\n  Team composition suggestion for {sprint_id}:")
        for assignment in compose["proposed_assignments"]:
            print(f"    {assignment['display_name']} ({assignment['persona_type']}) "
                  f"-> {assignment['assigned_component']} ({assignment['task_count']} tasks)")
        if compose.get("coverage_gaps"):
            print(f"    Coverage gaps: {compose['coverage_gaps']}")

    # 3. Self-assessment for task routing
    # During execution, before claiming each task, agents call:
    #   assessment = mcp__asdlc__self_assess(agent_id=my_id, task_id=task_id)
    #   if assessment["confidence"] < 40:
    #       # Consider reassigning to a better-matched agent
    print("\n  Governance pre-flight complete. Self-assessment enabled for task routing.")
else:
    # Governance disabled — skip all team health and composition checks
    pass
```

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
Mode: Simple (1 PRD), max_parallel=3
Execution Plan (2 batches, 5 tasks):

  Batch 1 (3 tasks, independent):
    PROJ-T00001: Set up OAuth config (auth) [light, 20 turns]
    PROJ-T00002: Create login endpoint (auth) [medium, 50 turns]
    PROJ-T00003: Add user model fields (models) [medium, 50 turns]

  Batch 2 (2 tasks, depend on Batch 1):
    PROJ-T00004: Implement token refresh (auth) [heavy, 80 turns]
      └─ depends on: PROJ-T00001
    PROJ-T00005: Add logout endpoint (auth) [medium, 50 turns]
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

### 3.5. Build Dispatch Info

Before launching task agents, the orchestrator builds a **lightweight dispatch info** block for each task. The dispatch info contains ONLY identity and dependency data — the subagent loads its own content via MCP tools.

**The orchestrator MUST NOT call** `get_task()`, `get_prd()`, `get_design()`, or `Read()` to build dispatch info. All data comes from the in-memory sprint task list already loaded in Step 1.

```python
def build_dispatch_info(task: dict, completed_outcomes: dict[str, dict]) -> str:
    """Build a minimal dispatch info block for a task agent.

    The orchestrator calls this BEFORE dispatching each subagent.
    Returns a small string (~200-500 bytes) with task identity and
    dependency outcomes only. The subagent self-loads full content.

    When quality is enabled (FR-021), the dispatch info also includes
    requirement context from get_task_requirements so the subagent
    knows which FRs and ACs to verify during implementation.

    Args:
        task: Task metadata from the sprint task list (already in memory).
        completed_outcomes: Map of {task_id: outcome_dict} for tasks
            that have already finished in this sprint run.
    """

    # --- 1. Task identity (from in-memory sprint task list) ---
    info = f"""task_id: {task["id"]}
title: {task["title"]}
component: {task.get("component", "general")}
priority: {task.get("priority", "medium")}
prd_id: {task.get("prd_id", "none")}"""

    # --- 2. Direct-dependency outcomes ONLY ---
    deps = task.get("dependencies", [])
    if deps:
        dep_lines = []
        for dep_id in deps:
            if dep_id in completed_outcomes:
                outcome = completed_outcomes[dep_id]
                summary = outcome.get("summary", "completed") if isinstance(outcome, dict) else str(outcome)
                dep_lines.append(f"  {dep_id}: {summary}")
        if dep_lines:
            info += "\ndependency_outcomes:\n" + "\n".join(dep_lines)

    # --- 3. Requirement context injection (FR-021, quality-gated) ---
    # Only when quality is enabled — adds linked requirements to dispatch info
    # so the subagent knows which FRs/ACs to verify during implementation.
    quality_config = load_quality_config()
    if quality_config.enabled:
        reqs = mcp__asdlc__get_task_requirements(task_id=task["id"])
        if reqs.get("status") == "ok" and reqs.get("total", 0) > 0:
            info += "\nlinked_requirements:"
            for req_type, req_list in reqs.get("requirements", {}).items():
                for req in req_list:
                    req_id = req.get("req_id", req.get("id", "unknown"))
                    summary = req.get("summary", "")
                    depth = req.get("depth", "")
                    verified = req.get("verified", False)
                    depth_label = f" [{depth}]" if depth else ""
                    verified_label = " (verified)" if verified else " (unverified)"
                    info += f"\n  {req_type}: {req_id}{depth_label} — {summary}{verified_label}"
            # Include required evidence types for ACs
            ac_reqs = reqs.get("requirements", {}).get("ac", [])
            if ac_reqs:
                info += "\nac_evidence_required:"
                for ac in ac_reqs:
                    ac_id = ac.get("req_id", ac.get("id", "unknown"))
                    depth = ac.get("depth", "structural")
                    evidence = "test" if depth == "behavioral" else "manual"
                    info += f"\n  {ac_id}: evidence_type={evidence} depth={depth}"

    return info
```

#### Dispatch Info Output Structure

The dispatch info is a compact block (~200-500 bytes) injected into the agent prompt. The subagent loads full content via MCP tools.

```
task_id: PROJ-T00004
title: Implement token refresh
component: auth
priority: high
prd_id: PROJ-P0001
dependency_outcomes:
  PROJ-T00001: Added OAuth config to src/auth/config.py
```

> **Design rationale**: The orchestrator never pre-reads task/PRD/design content. Subagents self-load via `get_task()`, `get_prd()`, and `get_design()` MCP calls, which populate their own context window — not the orchestrator's. This reduces orchestrator context consumption by ~96% per task dispatch.

#### Batch-Aware Shared Context

The orchestrator builds shared context **once per batch** and injects it into every subprocess via the `shared_context` parameter. This replaces ~20-50KB of per-agent file reads with a ~2-3KB pre-loaded summary.

```python
def build_batch_shared_context() -> str:
    """Build shared context once per batch, injected into every subprocess.

    Reads common files once and compresses them into a compact summary.
    This prevents N subagents from each independently reading the same
    ~20KB architecture.md, ~5KB config.yaml, and ~3KB lesson-learn.md.

    Target: ~2-3KB total (replaces ~20-50KB of per-agent reads).

    Returns:
        Compact string with architecture summary, config flags, and lessons.
    """
    sections = []

    # 1. Architecture summary (~1KB compressed from architecture.md)
    try:
        arch = Read(".sdlc/artifacts/architecture.md")
        # Extract key sections only: project structure, conventions, patterns
        # Compress to ~1KB — enough for agents to follow conventions
        sections.append("### Architecture (compressed)\n" + compress_to_summary(arch, max_chars=1000))
    except FileNotFoundError:
        pass

    # 2. Config flags as compact JSON (~200B — testing, git, review settings)
    try:
        config = Read(".sdlc/config.yaml")
        # Extract only the flags agents need: testing.commands, git.auto_commit,
        # review.enabled, quality.enabled
        config_summary = extract_config_flags(config)
        sections.append("### Config Flags\n```json\n" + json.dumps(config_summary, indent=0) + "\n```")
    except FileNotFoundError:
        pass

    # 3. Top lessons from lesson-learn.md (~500B)
    try:
        lessons = Read(".sdlc/lesson-learn.md")
        # Extract MUST rules only — agents need these for compliance
        must_rules = [line for line in lessons.split("\n")
                      if "MUST" in line or line.startswith("- **MUST")][:10]
        if must_rules:
            sections.append("### Key Lessons (MUST rules)\n" + "\n".join(must_rules))
    except FileNotFoundError:
        pass

    return "\n\n".join(sections)
```

#### Task Complexity Classification

Tasks are classified by complexity to set appropriate `max_turns` — heavy tasks get more room, light tasks are capped early.

```python
def classify_max_turns(task: dict) -> int:
    """Classify task complexity and return appropriate max_turns.

    Classification (can be customized via .sdlc/config.yaml sprint.dispatch):
    - Heavy (80 turns): critical priority, database/migration keywords, new modules
    - Light (20 turns): test-only, config, docs, small additions
    - Medium (50 turns): everything else

    The orchestrator displays this classification in the execution plan.
    """
    title = task.get("title", "").lower()
    component = task.get("component", "").lower()
    priority = task.get("priority", "medium")

    # Heavy indicators
    heavy_keywords = ["migration", "schema", "refactor", "redesign", "architect"]
    if priority == "critical" or any(kw in title for kw in heavy_keywords):
        return 80

    # Light indicators
    light_keywords = ["test", "doc", "readme", "config", "typo", "comment", "lint"]
    light_components = ["test", "qa", "docs", "documentation"]
    if any(kw in title for kw in light_keywords) or component in light_components:
        return 20

    # Medium (default)
    return 50
```

### 4. Dispatch Task Agents (Capped Parallelism Within Batch)

Tasks within a batch dispatch up to `max_parallel` concurrently — the orchestrator fills available slots, polls all active subprocesses, and fills new slots as tasks complete. This balances throughput against API rate limits and token consumption.

**Key principles:**
- Each task gets a fresh subprocess via `mcp__asdlc__execute_task()`
- The subagent receives lightweight dispatch info (from Step 3.5) plus pre-loaded shared context and self-loads task-specific content via MCP tools
- The subagent submits self-review evidence via `submit_review(reviewer_type='self')` and returns — it does NOT dispatch reviewer subagents or mark tasks complete
- **Review dispatch happens at the orchestrator level** (Step 4.4) — the orchestrator checks self-review, optionally dispatches a reviewer subagent, and handles the approve/reject flow
- **Parallelism is capped** at `max_parallel` (default: 3) to prevent token overconsumption
- **Fallback policy**: If `execute_task` returns `{"status": "error"}`, the task is marked BLOCKED — do NOT fall back to Task tool subagents (which share context and cause token bloat)

#### Subprocess Dispatch via `execute_task` (Non-Blocking)

For each task in the current batch, the orchestrator dispatches a **memory-safe subprocess** via the `execute_task` MCP tool. The call is **non-blocking** — it returns immediately with a handle (`pid` + `log_path`). The orchestrator MUST then poll `check_execution()` every 30 seconds to monitor progress, detect stalls, and retrieve the final outcome.

```python
# Step 1: Launch (returns immediately)
handle = mcp__asdlc__execute_task(
    task_id=task["id"],
    executor="claude",    # or read from .sdlc/config.yaml daemon.adapter
    max_turns=classify_max_turns(task),  # heavy=80, medium=50, light=20
    dispatch_info=dispatch_info,  # from build_dispatch_info() — ~200-500 bytes
    shared_context=batch_shared_context,  # pre-loaded once per batch — ~2-3KB
)
# handle = {"status": "launched", "pid": 12345, "log_path": "~/.a-sdlc/exec-logs/PROJ-T00001.jsonl"}

# IMPORTANT: If execute_task returns {"status": "error"}, mark task as BLOCKED
# Do NOT fall back to Task tool subagents (causes context bloat)
if handle.get("status") == "error":
    mcp__asdlc__log_correction(
        context_type="task", context_id=task["id"],
        category="process", description=f"execute_task failed: {handle.get('error', 'unknown')}")
    mcp__asdlc__update_task(task_id=task["id"], status="blocked")
    record_outcome(task, {"verdict": "BLOCKED", "summary": f"Dispatch failed: {handle.get('error', '')[:100]}"}, outcomes)
    continue  # Skip to next task

# Step 2: Poll until completion (MANDATORY — never fire-and-forget)
result = poll_until_completion(handle, task_id=task["id"])
# result = {"status": "completed", "outcome": {"verdict": "PASS", ...}, "turns": 25, "cost_usd": 1.50}
```

The subprocess prompt is built internally by `execute_task` and includes:
- Pre-loaded shared context (architecture, config, lessons) — avoids ~20-50KB of redundant reads per agent
- Self-loading instructions (get_task, get_prd, get_design via MCP) — only task-specific content
- Full implementation instructions
- Self-review gates with test evidence requirements
- Correction logging instructions
- Git config awareness (auto_commit, testing.runtime)
- Structured `---TASK-OUTCOME---` output block

The `dispatch_info` string (from `build_dispatch_info()`, Step 3.5) is injected into the subprocess prompt, providing dependency outcomes and batch context.

The `shared_context` string (from `build_batch_shared_context()`, see below) is built **once per batch** and injected into every subprocess, replacing ~20-50KB of per-agent file reads with a ~2-3KB pre-loaded summary.

**Note**: The subprocess runs autonomously — it cannot propagate `AskUserQuestion` back to the user. If the subprocess encounters unresolvable questions, it marks the task as `BLOCKED` in its outcome.

#### Polling and Stall Detection

The orchestrator MUST continuously monitor every dispatched subprocess. **Never leave a subprocess running without active polling.**

```python
def poll_until_completion(handle: dict, task_id: str,
                          max_stall_minutes: int = 5,
                          poll_interval: int = 30) -> dict:
    """Poll check_execution until task completes, with automatic stall detection.

    CRITICAL: The orchestrator MUST call this after every execute_task dispatch.
    Fire-and-forget is forbidden — a stuck subprocess wastes API credits and
    blocks sprint progress.

    Args:
        handle: Non-blocking handle from execute_task: {status, pid, log_path}
        task_id: For logging and diagnostics.
        max_stall_minutes: Kill process if no activity for this long (default: 5).
        poll_interval: Seconds between check_execution polls (default: 30).

    Returns:
        Completed status dict with outcome, or failure dict.
    """
    log_path = handle["log_path"]
    pid = handle["pid"]
    max_stall_seconds = max_stall_minutes * 60
    last_turns = -1
    last_tool = ""
    stall_start = None  # timestamp when stall was first detected

    while True:
        sleep(poll_interval)
        status = mcp__asdlc__check_execution(log_path=log_path, pid=pid)

        # --- Terminal states: return immediately ---
        if status["status"] == "completed":
            return status  # Contains status["outcome"]
        if status["status"] in ("failed", "error"):
            return {
                "status": "failed",
                "outcome": {
                    "verdict": "FAIL",
                    "summary": status.get("message", "Process failed"),
                },
            }

        # --- Running: check for stall ---
        current_turns = status.get("turns", 0)
        current_tool = status.get("last_tool", "")

        if current_turns != last_turns or current_tool != last_tool:
            # Progress detected — reset stall timer
            last_turns = current_turns
            last_tool = current_tool
            stall_start = None
        else:
            # No progress — start or continue stall timer
            if stall_start is None:
                stall_start = current_time()
            elapsed = current_time() - stall_start
            if elapsed > max_stall_seconds:
                # STALL: kill the subprocess
                mcp__asdlc__stop_execution(pid=pid)
                return {
                    "status": "failed",
                    "outcome": {
                        "verdict": "FAIL",
                        "summary": f"Process stalled ({elapsed}s no activity). Auto-killed.",
                    },
                }
```

#### Dispatch Sequence (Capped Parallelism Example)

```python
# Batch 1: 5 tasks, max_parallel=3 — dispatch up to 3 concurrently
outcomes = {}
active_handles = {}  # {task_id: (task, handle)}
pending = list(executable)  # tasks in this batch

# Build shared context ONCE for the entire batch
batch_shared_context = build_batch_shared_context()

while pending or active_handles:
    # --- Fill up to max_parallel slots ---
    while pending and len(active_handles) < max_parallel:
        task = pending.pop(0)
        update_task(task["id"], status="in_progress")
        info = build_dispatch_info(task, outcomes)
        handle = mcp__asdlc__execute_task(
            task_id=task["id"],
            executor=executor,
            max_turns=classify_max_turns(task),
            dispatch_info=info,
            shared_context=batch_shared_context,
        )

        # Error check: if dispatch failed, mark BLOCKED and skip
        if handle.get("status") == "error":
            mcp__asdlc__log_correction(
                context_type="task", context_id=task["id"],
                category="process",
                description=f"execute_task failed: {handle.get('error', 'unknown')}")
            mcp__asdlc__update_task(task_id=task["id"], status="blocked")
            record_outcome(task, {"verdict": "BLOCKED",
                "summary": f"Dispatch failed: {handle.get('error', '')[:100]}"}, outcomes)
            continue

        active_handles[task["id"]] = (task, handle)

    # --- Poll all active handles ---
    if not active_handles:
        break
    sleep(30)
    for task_id, (task, handle) in list(active_handles.items()):
        status = mcp__asdlc__check_execution(
            log_path=handle["log_path"], pid=handle["pid"])

        if status["status"] in ("completed", "failed", "error"):
            del active_handles[task_id]
            outcome = parse_task_outcome(status)
            review_result = orchestrator_review_dispatch(task, review_config)
            if review_result == "approved":
                update_task(task_id, status="completed")
            record_outcome(task, status, outcomes)
            write_state_checkpoint(outcomes, batches, batch_num)

# → Batch checkpoint (Step 4.5) → proceed to Batch 2
```

### 4.3. Track Task Outcomes

After each subagent completes, the orchestrator extracts an outcome summary and stores it. These outcomes serve two purposes:
1. **Context for downstream tasks** — via `build_dispatch_info()` (Step 3.5), which injects dependency outcomes into subsequent subagent prompts
2. **Batch checkpoint reports** — via `present_batch_results()` (Step 4.5), which shows per-task results

#### Outcome Data Structure

```python
# outcomes dict: {task_id: outcome_dict}
# Each entry is ~200 bytes. Populated after each subagent returns.

outcomes = {}  # Initialized at the start of run_simple_mode()

def parse_task_outcome(result) -> dict:
    """Extract the outcome dict from a completed check_execution result.

    After polling with ``poll_until_completion()``, the completed status
    dict contains an ``outcome`` key with the parsed result.

    For backward compatibility, if the result is a raw string (e.g. from
    a Task tool dispatch), it falls back to parsing the ---TASK-OUTCOME---
    block.

    Returns a compact dict (~200 bytes) that stays in orchestrator context.

    Args:
        result: Completed check_execution status dict (has "outcome" key)
                or raw subagent result string.

    Returns:
        Structured outcome dict with verdict, summary, files, tests.
    """
    # Completed check_execution() result has outcome key
    if isinstance(result, dict) and "outcome" in result:
        return result["outcome"]

    # Fallback: parse raw text (backward compat with Task tool dispatch)
    text = str(result)

    # Search for structured delimiters
    start = text.find("---TASK-OUTCOME---")
    end = text.find("---END-OUTCOME---")

    if start >= 0 and end > start:
        block = text[start:end]
        outcome = {}
        for line in block.split("\n"):
            if ":" in line and not line.startswith("---"):
                key, _, value = line.partition(":")
                outcome[key.strip()] = value.strip()
        return outcome

    # Fallback for non-compliant subagents — minimal placeholder
    return {"verdict": "UNKNOWN", "summary": "No structured outcome block returned"}


def record_outcome(task: dict, result, outcomes: dict, reason: str = None):
    """Record a compact outcome after subagent completion.

    Args:
        task: Task metadata dict.
        result: Subagent result (from dispatch_subagent).
        outcomes: The shared outcomes dict to append to.
        reason: Override reason (for skipped/failed tasks).
    """
    if reason:
        outcomes[task["id"]] = {"verdict": "SKIPPED", "summary": reason}
        return

    outcomes[task["id"]] = parse_task_outcome(result)
```

#### Outcome Size Guarantee

Each outcome entry is a compact dict (~200 bytes). The orchestrator **never** retains the full subagent output — only the parsed `---TASK-OUTCOME---` block.

```python
# Stored outcome — ~200 bytes:
outcomes["PROJ-T00001"] = {
    "verdict": "PASS",
    "files_changed": "src/auth/config.py, src/auth/constants.py",
    "tests": "3/3",
    "review": "APPROVE",
    "summary": "Added OAuth config with environment-based provider selection",
    "corrections": "1"
}

# Fallback for non-compliant subagent — ~60 bytes:
outcomes["PROJ-T00002"] = {
    "verdict": "UNKNOWN",
    "summary": "No structured outcome block returned"
}
```

### 4.4. Review Dispatch (Orchestrator Level)

After the implementing subagent returns for a task, the orchestrator runs the review dispatch sequence before marking the task complete. This ensures review is handled at the orchestrator layer, not inside the implementing subagent.

**Config check**: Read `.sdlc/config.yaml` — if `review.enabled` is `true`, the review system is active. If `review.enabled` is `false` or the entire `review` section is absent, review is disabled and the orchestrator skips directly to step 5 (complete task). When the master toggle is on, sub-features default to enabled: `self_review` defaults to `true`, `subagent_review` defaults to `true`.

#### Review Dispatch Sequence

1. **Check self-review**: Call `mcp__asdlc__get_review_evidence(task_id='{task_id}')` — verify self-review was submitted
   - If missing → `mcp__asdlc__update_task(task_id='{task_id}', status='blocked')` — task cannot complete
   - If present and verdict='fail' → `mcp__asdlc__update_task(task_id='{task_id}', status='blocked')` — task cannot complete

2. **Check subagent review config**: Read `.sdlc/config.yaml` `review.subagent_review.enabled` (defaults to `true` when `review.enabled` is `true`)
   - If explicitly set to `false` → skip to step 5 (complete task)

3. **Dispatch reviewer subagent**: Launch a fresh Task agent:
   ```
   Task(
     description="Review {task_id}: {task_title}",
     prompt="You are an independent code reviewer. Review task {task_id}.

            Call mcp__asdlc__get_review_evidence(task_id='{task_id}') to read the self-review.
            Review the git diff and test output.

            Evaluate: spec compliance, code quality, test coverage.

            Call mcp__asdlc__submit_review(task_id='{task_id}', reviewer_type='subagent', verdict='approve'|'request_changes'|'escalate', findings='...') with:
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

5. **AC Verification Gate (FR-022, quality-gated)**: Before calling `update_task(status='completed')`, verify all linked acceptance criteria have evidence recorded. This step only runs when `quality.enabled` is `true` AND `quality.ac_gate` is `true`.

   ```python
   quality_config = load_quality_config()
   if quality_config.enabled and quality_config.ac_gate:
       # Get all requirements linked to this task
       reqs = mcp__asdlc__get_task_requirements(task_id=task_id)
       if reqs.get("status") == "ok":
           ac_reqs = reqs.get("requirements", {}).get("ac", [])
           unverified = [ac for ac in ac_reqs if not ac.get("verified", False)]

           if unverified:
               print(f"  AC Verification Gate: {len(unverified)} unverified acceptance criteria for {task_id}:")
               for ac in unverified:
                   ac_id = ac.get("req_id", ac.get("id", "unknown"))
                   depth = ac.get("depth", "structural")
                   print(f"    {ac_id} [{depth}] — not yet verified")

               # Instruct the agent to verify each unverified AC
               for ac in unverified:
                   ac_id = ac.get("req_id", ac.get("id", "unknown"))
                   depth = ac.get("depth", "structural")
                   evidence_type = "test" if depth == "behavioral" else "manual"

                   # AC-015: Behavioral ACs require test evidence, not structural-only code
                   mcp__asdlc__verify_acceptance_criteria(
                       task_id=task_id,
                       ac_id=ac_id,
                       evidence_type=evidence_type,
                       evidence=f"Verified during task completion review"
                   )

               # Re-check after verification
               reqs = mcp__asdlc__get_task_requirements(task_id=task_id)
               ac_reqs = reqs.get("requirements", {}).get("ac", [])
               still_unverified = [ac for ac in ac_reqs if not ac.get("verified", False)]
               if still_unverified:
                   print(f"  WARNING: {len(still_unverified)} ACs still unverified after verification attempt")
   ```

6. **Implementation Challenge Gate (FR-031, quality-gated)**: After AC verification, if `quality.challenge.gates.implementation` is enabled, spawn a challenger agent to challenge the task implementation. Independent task challenges can run in parallel per NFR-009.

   ```python
   quality_config = load_quality_config()
   if quality_config.enabled and quality_config.challenge.is_gate_active("implementation"):
       # Get or generate the challenge prompt
       challenge = mcp__asdlc__challenge_artifact(
           artifact_type="task",
           artifact_id=task_id,
           challenge_context=f"Post-implementation challenge for {task_id}"
       )

       if challenge.get("status") == "ok":
           challenge_prompt = challenge["challenge_prompt"]
           round_number = challenge.get("round_number", 1)

           # Dispatch challenger subagent via Task tool
           challenger_result = Task(
               description=f"Challenge implementation of {task_id}",
               prompt=f"""You are a challenger reviewing the implementation of task {task_id}.

   {challenge_prompt}

   Review the implementation critically. For each concern:
   1. State the objection clearly
   2. Reference specific code or acceptance criteria
   3. Classify as: resolved (no action needed), accepted (must fix), or escalated (needs human decision)

   Output your findings as structured objections.
   """,
               subagent_type="sdlc-qa-engineer"
           )

           # Parse challenger findings and record the round
           objections = parse_challenge_objections(challenger_result)
           mcp__asdlc__record_challenge_round(
               artifact_type="task",
               artifact_id=task_id,
               round_number=round_number,
               objections=objections,
               verdict={"resolved": [], "accepted": [], "escalated": []}
           )

           # Check challenge status
           challenge_status = mcp__asdlc__get_challenge_status(
               artifact_type="task",
               artifact_id=task_id
           )

           # AC-024: Accepted objections must be acted on
           accepted = challenge_status.get("stats", {}).get("accepted", 0)
           if accepted > 0:
               print(f"  Implementation challenge: {accepted} accepted objections require fixes")
               # These will be addressed in the post-flight remediation loop
               # or the implementing agent must fix them before completion
               mcp__asdlc__log_correction(
                   context_type="task",
                   context_id=task_id,
                   category="code-quality",
                   description=f"Implementation challenge: {accepted} accepted objections pending resolution"
               )
   ```

   **Parallel challenges (NFR-009)**: When multiple tasks in a batch complete independently, their implementation challenges can be dispatched in parallel. The orchestrator should batch challenge dispatches for independent tasks:

   ```python
   # After all tasks in a batch complete and pass review:
   challenge_tasks = [t for t in batch_completed_tasks
                      if quality_config.challenge.is_gate_active("implementation")]

   # Dispatch challengers in parallel for independent tasks
   challenge_handles = {}
   for task in challenge_tasks:
       handle = Task(
           description=f"Challenge {task['id']}",
           prompt=f"...(challenge prompt for {task['id']})...",
           subagent_type="sdlc-qa-engineer",
           run_in_background=True  # Parallel dispatch
       )
       challenge_handles[task["id"]] = handle

   # Collect results
   for task_id, handle in challenge_handles.items():
       result = wait_for(handle)
       # Process and record challenge round
   ```

7. **Complete task**: Call `mcp__asdlc__update_task(task_id='{task_id}', status='completed')` — the hard gate in `update_task()` accepts this because approved review evidence now exists in the database

#### Review Dispatch in Isolated Mode

The same review dispatch sequence applies to isolated mode (multi-PRD with worktrees). When the PRD agent returns after executing all tasks, the orchestrator runs the review dispatch for each task that the PRD agent reported as completed.

For isolated mode, the orchestrator:
1. Parses the structured outcome blocks from the PRD agent's output (one `---TASK-OUTCOME---` block per task)
2. For each task with `verdict: PASS`, runs the review dispatch sequence above
3. For each task with `verdict: FAIL` or `verdict: BLOCKED`, skips review and handles via the Batch Failure Handler

#### Integration with Context Package

The `build_dispatch_info()` function (Step 3.5) already accepts `completed_outcomes` and includes a `## Prior Task Outcomes` section. The `outcomes` dict populated here is passed directly:

```python
context = build_dispatch_info(task["id"], outcomes)
# → outcomes for dependency tasks are included in the "## Prior Task Outcomes" section
```

Only **direct dependency** outcomes are included in the dispatch info (not all completed tasks). This keeps context concise per NFR-002.

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
- **"Add clarification"** — Ask follow-up: "Enter clarification for upcoming tasks." The clarification text is appended to the dispatch info for all tasks in the next batch under a `## User Clarification` section.
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
- **"Retry with fresh agent"** — Dispatch a new subagent for this task with fresh dispatch info. The retry counts as an additional attempt but does NOT reset the review round counter for logging purposes. If the fresh agent also fails review, escalate again.
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

### 9.5. Build Dispatch Info and Batch Groupings per PRD

Before launching PRD agents, the orchestrator groups tasks into dependency-ordered batches per PRD and builds lightweight dispatch info for each task. The orchestrator does NOT pre-read task/PRD/design content.

```python
for group in prd_groups:
    # Group this PRD's tasks into dependency-ordered batches
    batches, unresolvable = build_batches(group["tasks"])
    group["batches"] = batches

    # Build lightweight dispatch info per task (from in-memory task list only)
    group["dispatch_info"] = {}
    for batch in batches:
        for task in batch:
            group["dispatch_info"][task["id"]] = build_dispatch_info(
                task, completed_outcomes={}  # No prior outcomes for fresh PRD agent
            )
```

### 9.6. Launch PRD Agents

**CRITICAL**: Launch one agent per PRD. Each agent receives task IDs organized by batch and self-loads full content via MCP tools. The agent executes tasks sequentially within each batch, in batch order.

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

For EACH task:
1. Call `mcp__asdlc__get_task(task_id)` to load full task content
2. Call `mcp__asdlc__get_prd(prd_id)` if you need PRD context
3. Call `mcp__asdlc__get_design(prd_id)` if you need design context (may not exist)
4. Read `.sdlc/artifacts/architecture.md` for codebase patterns (if it exists)
5. Call mcp__asdlc__update_task(task_id, status="in_progress")
6. Implement the task following the Implementation Steps from the task content
7. Read .sdlc/config.yaml — check `git.auto_commit`:
   - If `true`: git add <files> && git commit -m "[{task_id}] {task_title}"
   - If `false` or not set: git add <files> only — do NOT commit. Leave changes staged for user review.
8. Read .sdlc/config.yaml — check `testing.runtime` for runtime test configuration
9. Run review gates (see below)
10. Do NOT call `update_task(status='completed')` — the orchestrator handles completion after review

## Batch 1 (independent tasks):
{dispatch_info_for_PROJ-T00001}
{dispatch_info_for_PROJ-T00002}

## Batch 2 (depends on Batch 1):
{dispatch_info_for_PROJ-T00003}

## Review Gates (for EACH task)

After completing implementation and tests for each task:
1. Self-review: Re-read the task spec, verify each acceptance criterion is satisfied
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
2. Call `mcp__asdlc__submit_review(task_id='{task_id}', reviewer_type='self', verdict='pass'|'fail', findings='...', test_output='...')` with actual test output
3. If self-review verdict is 'fail', fix the issues and re-submit until 'pass'
4. Log corrections for EVERY finding discovered during implementation:
   mcp__asdlc__log_correction(context_type='task', context_id='{task_id}', category='{category}', description='{what_was_found_and_fixed}')
5. Do NOT call `update_task(status='completed')` — the orchestrator handles completion after review
6. If you encounter unresolvable questions, surface them via AskUserQuestion — do NOT guess

## CRITICAL: Structured Output (per task)

The orchestrator parses ONLY the ---TASK-OUTCOME--- blocks below.
Everything else in your output is discarded by the orchestrator.
After completing EACH task, output a structured outcome block:

---TASK-OUTCOME---
task_id: {task_id}
verdict: PASS|FAIL|BLOCKED
files_changed: file1.py, file2.py
tests: {passed}/{total}
review: APPROVE|REQUEST_CHANGES|ESCALATE
summary: {one-line description of what was done}
corrections: {number of corrections logged}
---END-OUTCOME---

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
  prompt="...(same pattern, different worktree/tasks/batches/dispatch info)...",
  subagent_type="general-purpose",
  run_in_background=true
)
```

**Note**: PRD agents use `run_in_background=true` via the `Task` tool because the orchestrator manages multiple PRDs concurrently. Within each PRD agent, tasks execute sequentially (no background dispatch). Isolated mode keeps `Task()` dispatch because each PRD agent is a single long-running session (lower memory pressure than per-task subagents in simple mode). Optionally, each PRD agent can call `mcp__asdlc__execute_task()` per task within the PRD to get memory-safe per-task isolation — but MUST then poll `mcp__asdlc__check_execution()` every 30 seconds until completion (see `poll_until_completion()` pattern above).

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
config = mcp__asdlc__manage_git_safety("get")
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
    config = manage_git_safety("get")
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

    outcomes = {}  # {task_id: outcome_summary} — fed to build_dispatch_info
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

    # --- Context pressure thresholds (FR-005) ---
    warn_threshold = 70      # Log notice + save checkpoint
    urgent_threshold = 85    # Prompt user to halt or continue
    compact_threshold = 95   # Auto-compact context and continue

    # Optional: read from .sdlc/config.yaml
    #   sprint:
    #     context_thresholds:
    #       warn: 70
    #       urgent: 85
    #       compact: 95
    try:
        if "context_thresholds:" in config:
            warn_threshold = int(config.sprint.context_thresholds.warn)
            urgent_threshold = int(config.sprint.context_thresholds.urgent)
            compact_threshold = int(config.sprint.context_thresholds.compact)
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

        # --- Build shared context ONCE per batch (token savings) ---
        batch_shared_context = build_batch_shared_context()

        # --- Execute tasks with capped parallelism ---
        batch_results = {}
        for task in executable:
            update_task(task["id"], status="in_progress")
            info = build_dispatch_info(task, outcomes)
            if user_clarification:
                info += f"\n\n## User Clarification\n{user_clarification}"
            result = dispatch_subagent(task, info,
                                       shared_context=batch_shared_context)  # Non-blocking launch + poll

            # --- Track context consumption (FR-004) ---
            # Only count what stays in orchestrator context: the parsed outcome dict
            outcome_block = parse_task_outcome(result)  # Extracts result["outcome"]
            context_chars_consumed += len(str(outcome_block)) + 300  # outcome + orchestrator overhead

            # --- Orchestrator Review Dispatch (Step 4.4) ---
            review_config = load_review_config()  # from .sdlc/config.yaml
            if review_config.get("enabled", False):
                review_result = orchestrator_review_dispatch(task, review_config)
                # review_result: "approved", "blocked", or "escalated"

                if review_result == "blocked":
                    # Handle review failure (Batch Failure Handler)
                    rounds = review_result.rounds
                    if rounds >= review_config.get("max_rounds", 3):
                        failure_decision = ask_failure_handler(task, review_result.feedback)
                        if failure_decision == "retry":
                            result = dispatch_subagent(task, info, fresh=True)  # Launches + polls
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

            if budget_percentage >= compact_threshold:
                write_state_checkpoint(outcomes, batches, batch_num)
                print(f"🔄 Context at ~{budget_percentage:.0f}%. Auto-compacting and continuing...")
                # Auto-compact: summarize held context to minimal form
                # The orchestrator drops verbose state, keeping only structured outcomes
                # Execution continues — no halt, no user intervention needed

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

        # --- Context pressure management (FR-005) ---
        if budget_percentage >= compact_threshold:
            # AUTO-COMPACT: Context critically high — compact automatically and continue
            write_state_checkpoint(outcomes, batches, batch_num)
            print(f"""
🔄 AUTO-COMPACT: Context at ~{budget_percentage:.0f}%
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Checkpoint saved. Compacting context to minimal form...
Dropping verbose state, keeping only structured outcomes.
Execution continues.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            """)
            # Reset tracking — after compact, context consumption is reduced
            context_chars_consumed = len(str(outcomes)) + 1000  # Re-baseline to current outcome size

        elif budget_percentage >= urgent_threshold:
            # URGENT: Prompt user — halt or continue
            write_state_checkpoint(outcomes, batches, batch_num)

            urgent_decision = AskUserQuestion({
                questions: [{
                    question: f"Context budget at ~{budget_percentage:.0f}%. Auto-compact triggers at {compact_threshold}%.",
                    header: "Context pressure",
                    options: [
                        { label: "Continue", description: f"Keep going (auto-compact at {compact_threshold}%)" },
                        { label: "Halt and resume later", description: f"Save state, end session. Resume: /sdlc:sprint-run {sprint_id} --resume" },
                        { label: "Abort sprint", description: "Stop execution, state is saved" }
                    ],
                    multiSelect: false
                }]
            })

            if urgent_decision == "Halt and resume later":
                print(f"State saved to: {state_file}")
                print(f"Resume: /sdlc:sprint-run {sprint_id} --resume")
                return
            elif urgent_decision == "Abort sprint":
                print("Sprint execution aborted. State saved for later resume.")
                return
            # "Continue" — proceed to next batch

        elif budget_percentage >= warn_threshold:
            # WARN: Log notice + save checkpoint (passive)
            write_state_checkpoint(outcomes, batches, batch_num)
            print(f"ℹ️ Context at ~{budget_percentage:.0f}%. Checkpoint saved. Continuing...")

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

    # =========================================================================
    # Post-Flight Remediation Loop (FR-023, FR-038, AC-022, AC-025)
    # =========================================================================
    # Config-gated: Only runs when quality.enabled is true.
    # After all batches complete, check for remaining quality gaps and
    # create/execute remediation tasks in a loop up to max_remediation_passes.

    quality_config = load_quality_config()
    if quality_config.enabled:
        max_passes = quality_config.max_remediation_passes  # default: 2
        remediation_pass = 0

        while remediation_pass < max_passes:
            # 1. Get current sprint quality report
            report = mcp__asdlc__get_quality_report("sprint", sprint_id=sprint_id)

            if report.get("status") != "ok":
                print(f"  Quality report failed: {report.get('message', 'unknown')}. Skipping remediation.")
                break

            # 2. Check if gaps exist
            if report.get("pass", True):
                print(f"  Post-flight quality check: PASS — no gaps remaining.")
                break

            remediation_pass += 1
            agg = report["aggregate"]
            print(f"""
Post-Flight Remediation (Pass {remediation_pass}/{max_passes}):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Orphaned requirements: {agg["orphaned_requirements"]}
  Unverified ACs:        {agg["total_acs"] - agg["verified_acs"]}
  Scope drift tasks:     {report["scope_drift"]["unlinked_count"]}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            """)

            # 3. Check for accepted challenge objections (FR-039, AC-024)
            # Accepted challenge objections become remediation items
            for prd_report in report.get("prd_reports", []):
                prd_id = prd_report["prd_id"]
                for artifact_type in ["prd", "design", "split", "task"]:
                    challenge_status = mcp__asdlc__get_challenge_status(
                        artifact_type=artifact_type,
                        artifact_id=prd_id
                    )
                    accepted = challenge_status.get("stats", {}).get("accepted", 0)
                    if accepted > 0:
                        print(f"  {artifact_type} {prd_id}: {accepted} accepted challenge objections pending")

            # 4. Create remediation tasks for gaps
            remediation_result = mcp__asdlc__create_remediation_tasks(sprint_id=sprint_id)
            if remediation_result.get("status") != "ok" or remediation_result.get("created_count", 0) == 0:
                print("  No remediation tasks could be created. Exiting remediation loop.")
                break

            created_count = remediation_result["created_count"]
            print(f"  Created {created_count} remediation tasks.")

            # 5. Execute remediation tasks as a new batch
            remediation_tasks = []
            for rt in remediation_result.get("tasks", []):
                task_data = mcp__asdlc__get_task(task_id=rt["task_id"])
                if task_data.get("status") != "error":
                    remediation_tasks.append(task_data)

            if not remediation_tasks:
                print("  No executable remediation tasks. Exiting remediation loop.")
                break

            # Build and execute remediation batch
            for task in remediation_tasks:
                update_task(task["id"], status="in_progress")
                info = build_dispatch_info(task, outcomes)
                info += "\n\n## REMEDIATION CONTEXT\nThis is a remediation task created to close quality gaps."
                result = dispatch_subagent(task, info)
                outcome = parse_task_outcome(result)
                record_outcome(task, result, outcomes)

                # Run review dispatch for remediation tasks
                review_config = load_review_config()
                if review_config.get("enabled", False):
                    review_result = orchestrator_review_dispatch(task, review_config)
                    if review_result == "approved":
                        update_task(task["id"], status="completed")
                else:
                    update_task(task["id"], status="completed")

            # Checkpoint after remediation pass
            write_state_checkpoint(outcomes, batches, len(batches))

            # 6. Re-check quality (loop continues if gaps persist)

        # AC-025: If gaps persist after max passes, exit with incomplete status
        if remediation_pass >= max_passes:
            final_report = mcp__asdlc__get_quality_report("sprint", sprint_id=sprint_id)
            if final_report.get("status") == "ok" and not final_report.get("pass", True):
                agg = final_report["aggregate"]
                print(f"""
Post-Flight Remediation: INCOMPLETE (max passes reached)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Remediation passes used: {remediation_pass}/{max_passes}
  Remaining gaps:
    Orphaned requirements: {agg["orphaned_requirements"]}
    Unverified ACs:        {agg["total_acs"] - agg["verified_acs"]}
    Scope drift tasks:     {final_report["scope_drift"]["unlinked_count"]}

  WARNING: Sprint has unresolved quality gaps after {max_passes} remediation passes.
  Use /sdlc:sprint-complete with force=True or mcp__asdlc__waive_sprint_quality()
  to complete the sprint despite gaps.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                """)
                mcp__asdlc__log_correction(
                    context_type="sprint",
                    context_id=sprint_id,
                    category="process",
                    description=f"Post-flight remediation incomplete after {max_passes} passes. "
                                f"Gaps: {agg['orphaned_requirements']} orphaned, "
                                f"{agg['total_acs'] - agg['verified_acs']} unverified ACs, "
                                f"{final_report['scope_drift']['unlinked_count']} scope drift"
                )
    # End of post-flight remediation loop

    # --- Final completion report ---
    present_completion_summary(batches, outcomes)
    generate_report(sprint_id, outcomes)

    # --- Clean up state file on successful completion (FR-006) ---
    # Archive with timestamp for debugging, then remove active state file
    timestamp = current_iso_timestamp().replace(":", "-")
    Bash(f"mv {state_file} {state_dir}/{sprint_id}-state.{timestamp}.json 2>/dev/null || true")


def dispatch_subagent(task: dict, dispatch_info: str, fresh: bool = False,
                      shared_context: str = "") -> dict:
    """Dispatch a task to a memory-safe subprocess and poll until completion.

    Non-blocking: launches the subprocess via ``execute_task`` (returns
    immediately), then polls ``check_execution`` every 30 seconds with
    automatic stall detection.

    The subprocess receives pre-loaded shared context to avoid redundant reads
    of architecture.md, config.yaml, and lesson-learn.md (~20-50KB savings per
    agent). It self-loads only task-specific content via MCP tools and submits
    self-review evidence via submit_review(reviewer_type='self'). It does NOT dispatch reviewer
    subagents or mark the task as completed — that happens at the orchestrator
    level (Step 4.4).

    Args:
        task: Task metadata dict with id, title, etc.
        dispatch_info: Lightweight text from build_dispatch_info() (~200-500 bytes).
        fresh: If True, this is a retry — add retry context to dispatch_info.
        shared_context: Pre-loaded shared context from build_batch_shared_context().

    Returns:
        Completed status dict with ``outcome`` key from poll_until_completion(),
        or error dict if dispatch failed.
    """
    info = dispatch_info
    if fresh:
        info += (
            "\n\n## RETRY NOTE\n"
            "This is a retry attempt. A previous agent failed review.\n"
            "Pay extra attention to the review feedback from the prior attempt.\n"
        )

    # Read executor from .sdlc/config.yaml daemon.adapter (default: "claude")
    executor = read_config_value("daemon.adapter", default="claude")

    # NON-BLOCKING MCP call — returns immediately with a handle
    handle = mcp__asdlc__execute_task(
        task_id=task["id"],
        executor=executor,
        max_turns=classify_max_turns(task),
        dispatch_info=info,
        shared_context=shared_context,
    )
    # handle = {"status": "launched", "pid": N, "log_path": "..."}

    # ERROR CHECK: If dispatch failed, do NOT fall back to Task tool subagents
    if handle.get("status") == "error":
        mcp__asdlc__log_correction(
            context_type="task", context_id=task["id"],
            category="process",
            description=f"execute_task failed: {handle.get('error', 'unknown')}")
        return {
            "status": "failed",
            "outcome": {
                "verdict": "BLOCKED",
                "summary": f"Dispatch failed: {handle.get('error', '')[:200]}",
            },
        }

    # MANDATORY: Poll until completion with stall detection
    # Never fire-and-forget — always monitor the subprocess
    result = poll_until_completion(handle, task_id=task["id"])

    return result


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
        mcp__asdlc__update_task(task_id=task_id, status="blocked")
        return "blocked"
    if evidence["self_review"]["verdict"] == "fail":
        mcp__asdlc__update_task(task_id=task_id, status="blocked")
        return "blocked"

    # 2. Check if subagent review is enabled (defaults to True when review.enabled is True)
    subagent_cfg = review_config.get("subagent_review", {})
    subagent_enabled = subagent_cfg.get("enabled", True) if isinstance(subagent_cfg, dict) else bool(subagent_cfg)
    if not subagent_enabled:
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


# record_outcome() and parse_task_outcome() — see Step 4.3 above for full definitions


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

    # --- Context pressure thresholds (FR-005) ---
    warn_threshold = 70      # Log notice + save checkpoint
    urgent_threshold = 85    # Prompt user to halt or continue
    compact_threshold = 95   # Auto-compact context and continue

    # Optional: read from .sdlc/config.yaml
    #   sprint:
    #     context_thresholds:
    #       warn: 70
    #       urgent: 85
    #       compact: 95
    try:
        if "context_thresholds:" in config:
            warn_threshold = int(config.sprint.context_thresholds.warn)
            urgent_threshold = int(config.sprint.context_thresholds.urgent)
            compact_threshold = int(config.sprint.context_thresholds.compact)
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

    # --- Build batch groupings and dispatch info per PRD ---
    for group in prd_groups:
        batches, unresolvable = build_batches(group["tasks"])
        group["batches"] = batches
        if unresolvable:
            warn_circular_deps(unresolvable)

        # Build lightweight dispatch info per task (from in-memory task list only)
        group["dispatch_info"] = {}
        for batch in batches:
            for task in batch:
                group["dispatch_info"][task["id"]] = build_dispatch_info(
                    task, completed_outcomes={}
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
    # Each agent receives lightweight dispatch info and self-loads content
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
                dispatch_info=group["dispatch_info"],
            )
            active[group["prd_id"]] = agent_id

        completed_prd, prd_result = wait_for_any(active)
        del active[completed_prd]

        # --- Track context consumption (FR-004) ---
        # Only count what stays in orchestrator context: parsed outcome blocks
        task_outcome_blocks = parse_prd_agent_task_outcomes(prd_result)
        context_chars_consumed += len(str(task_outcome_blocks)) + 300  # outcomes + overhead

        # --- Orchestrator Review Dispatch for isolated mode (Step 4.4) ---
        # task_outcome_blocks already parsed above for context tracking
        task_outcomes = task_outcome_blocks
        review_config = load_review_config()  # from .sdlc/config.yaml

        for task_id, task_outcome in task_outcomes.items():
            if task_outcome["verdict"] == "PASS" and review_config.get("enabled", False):
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

        # --- Context pressure management (FR-005) ---
        if budget_percentage >= compact_threshold:
            # AUTO-COMPACT: Context critically high — compact automatically and continue
            write_state_checkpoint(outcomes, prd_groups)
            print(f"""
🔄 AUTO-COMPACT: Context at ~{budget_percentage:.0f}%
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Checkpoint saved. Compacting context to minimal form...
Dropping verbose state, keeping only structured outcomes.
Execution continues.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            """)
            # Reset tracking — after compact, context consumption is reduced
            context_chars_consumed = len(str(outcomes)) + 1000  # Re-baseline

        elif budget_percentage >= urgent_threshold:
            # URGENT: Prompt user — halt or continue
            write_state_checkpoint(outcomes, prd_groups)

            urgent_decision = AskUserQuestion({
                questions: [{
                    question: f"Context budget at ~{budget_percentage:.0f}%. Auto-compact triggers at {compact_threshold}%.",
                    header: "Context pressure",
                    options: [
                        { label: "Continue", description: f"Keep going (auto-compact at {compact_threshold}%)" },
                        { label: "Halt and resume later", description: f"Save state, end session. Resume: /sdlc:sprint-run {sprint_id} --resume" },
                        { label: "Abort sprint", description: "Stop execution, state is saved" }
                    ],
                    multiSelect: false
                }]
            })

            if urgent_decision == "Halt and resume later":
                print(f"State saved to: {state_file}")
                print(f"Resume: /sdlc:sprint-run {sprint_id} --resume")
                return
            elif urgent_decision == "Abort sprint":
                print("Sprint execution aborted. State saved for later resume.")
                return
            # "Continue" — proceed to next PRD agent

        elif budget_percentage >= warn_threshold:
            # WARN: Log notice + save checkpoint (passive)
            write_state_checkpoint(outcomes, prd_groups)
            print(f"ℹ️ Context at ~{budget_percentage:.0f}%. Checkpoint saved. Continuing...")

    # =========================================================================
    # Post-Flight Remediation Loop — Isolated Mode (FR-023, FR-038, AC-022, AC-025)
    # =========================================================================
    # Same logic as simple mode. Config-gated: Only runs when quality.enabled is true.
    quality_config = load_quality_config()
    if quality_config.enabled:
        max_passes = quality_config.max_remediation_passes
        remediation_pass = 0

        while remediation_pass < max_passes:
            report = mcp__asdlc__get_quality_report("sprint", sprint_id=sprint_id)
            if report.get("status") != "ok" or report.get("pass", True):
                if report.get("pass", True):
                    print("  Post-flight quality check: PASS — no gaps remaining.")
                break

            remediation_pass += 1
            agg = report["aggregate"]
            print(f"Post-Flight Remediation (Pass {remediation_pass}/{max_passes}): "
                  f"{agg['orphaned_requirements']} orphaned, "
                  f"{agg['total_acs'] - agg['verified_acs']} unverified ACs")

            remediation_result = mcp__asdlc__create_remediation_tasks(sprint_id=sprint_id)
            if remediation_result.get("status") != "ok" or remediation_result.get("created_count", 0) == 0:
                break

            # Execute remediation tasks
            for rt in remediation_result.get("tasks", []):
                task_data = mcp__asdlc__get_task(task_id=rt["task_id"])
                if task_data.get("status") != "error":
                    update_task(rt["task_id"], status="in_progress")
                    info = build_dispatch_info(task_data, outcomes)
                    info += "\n\n## REMEDIATION CONTEXT\nThis is a remediation task."
                    result = dispatch_subagent(task_data, info)
                    record_outcome(task_data, result, outcomes)
                    update_task(rt["task_id"], status="completed")

            write_state_checkpoint(outcomes, prd_groups)

        # AC-025: Max passes reached with remaining gaps
        if remediation_pass >= max_passes:
            final_report = mcp__asdlc__get_quality_report("sprint", sprint_id=sprint_id)
            if final_report.get("status") == "ok" and not final_report.get("pass", True):
                agg = final_report["aggregate"]
                print(f"Post-Flight Remediation: INCOMPLETE after {max_passes} passes. "
                      f"Gaps: {agg['orphaned_requirements']} orphaned, "
                      f"{agg['total_acs'] - agg['verified_acs']} unverified ACs")
                mcp__asdlc__log_correction(
                    context_type="sprint", context_id=sprint_id, category="process",
                    description=f"Post-flight remediation incomplete after {max_passes} passes"
                )

    # Branch completion — use complete_prd_worktree with config-aware options
    config = manage_git_safety("get")
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
