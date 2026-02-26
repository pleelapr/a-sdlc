# /sdlc:task-start

## Purpose

Mark a task as in-progress and begin working on it.

## Usage

Use the MCP tool to start a task:

```
mcp__asdlc__start_task(task_id="TASK-001")
```

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `task_id` | Yes | ID of the task to start |

## Execution

1. Validates task exists and is pending
2. Updates task status to `in_progress`
3. Sets `updated_at` timestamp
4. Returns updated task details

## Output

```json
{
  "status": "updated",
  "message": "Task updated: TASK-001",
  "task": {
    "id": "TASK-001",
    "title": "Implement authentication",
    "status": "in_progress",
    "description": "Add JWT-based auth...",
    "priority": "high",
    "component": "auth-service"
  }
}
```

### Preflight: Lesson Check

Read `.sdlc/lesson-learn.md` and `~/.a-sdlc/lesson-learn.md` (if they exist).
Filter for lessons matching this task's component: `{task.component}`.

If MUST or SHOULD lessons found, present via AskUserQuestion:
```
AskUserQuestion({
  questions: [{
    question: "Lessons relevant to {component} — review before implementing:",
    header: "Lessons",
    options: [
      { label: "Acknowledged", description: "I'll follow these during implementation" },
      { label: "Not relevant", description: "These don't apply to this specific task" }
    ],
    multiSelect: false
  }]
})
```

If no relevant lessons, proceed silently.

## Display Format

After starting the task, check for relevant codebase context:

```
context = mcp__asdlc__get_context()
```

If `context.artifacts.scan_status` is `"complete"` or `"partial"` AND the task has a `component`:

```
Read: .sdlc/artifacts/architecture.md
```

Extract the section relevant to the task's component (its description, key files, dependencies) and display it alongside the task details.

```
Task Started: TASK-001

"Implement authentication"

Priority: High
Component: auth-service
Sprint: SPRINT-01

Description:
Add JWT-based authentication to the API endpoints.

Component Context (from architecture.md):
  auth-service: Handles authentication and authorization
  Key files: src/auth/handlers.py, src/auth/models.py
  Dependencies: database, config-service

Traceability Context:
  This task addresses:
  - FR-001: Traceability matrix mapping requirements to tasks
  - FR-003: Tasks include testable acceptance criteria

Design Compliance:
  - DD-9: Task-start display — Show traced requirements to implementer

Acceptance Criteria:
  - [ ] task-start.md displays Traces To section if present in task content
  - [ ] task-start.md displays Acceptance Criteria if present in task content
  - [ ] Legacy tasks without traceability sections display normally

Good luck! Run /sdlc:task-complete TASK-001 when done.
```

### Traceability Context Display

After the Component Context block, check the task content (from `get_task()` response) for traceability sections and display them conditionally.

#### Traces To

If the task content contains a `### Traces To` section, extract its entries and display:

```
Traceability Context:
  This task addresses:
  - FR-001: {description from the Traces To section}
  - AC-002: {description from the Traces To section}
```

Each line under `### Traces To` that matches the pattern `- **{ID}**: {description}` should be extracted and displayed as `- {ID}: {description}`.

If no `### Traces To` section exists in the task content, skip this block entirely.

#### Design Compliance

If the task content contains a `### Design Compliance` section, extract its entries and display:

```
Design Compliance:
  - DD-1: {description from the Design Compliance section}
```

Each line under `### Design Compliance` that matches the pattern `- **{ID}**: {description}` should be extracted and displayed as `- {ID}: {description}`.

If no `### Design Compliance` section exists in the task content, skip this block entirely.

#### Acceptance Criteria

If the task content contains a `### Acceptance Criteria` or `## Acceptance Criteria` section, extract its entries and display:

```
Acceptance Criteria:
  - [ ] {criterion 1}
  - [ ] {criterion 2}
```

Each line under the Acceptance Criteria heading that matches `- [ ]` or `- [x]` patterns should be extracted and displayed as-is.

If no Acceptance Criteria section exists in the task content, skip this block entirely.

### Fallback for Legacy Tasks

If no artifacts are available or the task has no component, display the standard format without the component context section. If no `### Traces To`, `### Design Compliance`, or `### Acceptance Criteria` sections exist in the task content, skip the traceability blocks entirely — no error, no placeholder. Legacy tasks without traceability data display the standard format unchanged.

### Review Gate Preview

Before starting implementation, show the implementer what "done" looks like by previewing the review gate criteria. This surfaces acceptance criteria, test expectations, and review process upfront so the implementer can work toward them from the start.

#### 1. Load Acceptance Criteria

If the task has a `prd_id`, fetch the parent PRD:

```
prd = mcp__asdlc__get_prd(prd_id="{task.prd_id}")
```

Parse the PRD content for an `## Acceptance Criteria` section. Extract all AC lines (lines matching `- AC-NNN:` or `- [ ]` patterns).

If the task file itself contains an `## Acceptance Criteria` section, use those instead (task-level ACs override PRD-level).

#### 2. Load Testing & Review Configuration

Read `.sdlc/config.yaml` (if it exists) and extract:

- `testing.defaults.required` — list of required test types
- `testing.commands` — commands for each test type
- `review.self_review.enabled` — whether self-review is active
- `review.subagent_review.enabled` — whether subagent review is active
- `review.max_rounds` — max self-heal iterations
- `review.evidence_required` — whether test output evidence is needed

#### 3. Display Review Gate Preview

```
──────────────────────────────────────
Review Gate Preview
──────────────────────────────────────

Acceptance Criteria (your "red" — satisfy all before completing):
  ☐ AC-001: Every task goes through self-review before completion
  ☐ AC-002: Subagent review dispatched with full context
  ☐ AC-003: Reviewer evaluates spec compliance, code quality, test coverage

Test Requirements:
  Required types: unit, integration
  Commands:
    unit: uv run pytest tests/ -v
    integration: (not configured)
  Evidence required: Yes — actual test output must be shown

Review Process:
  Self-review: Enabled
  Subagent review: Enabled
  Max heal rounds: 3

──────────────────────────────────────
```

#### 4. Fallback Handling

**If no acceptance criteria found** (no ACs in task file or parent PRD):

```
Acceptance Criteria:
  (none found — implementation will be reviewed against task description and PRD requirements)
```

**If `.sdlc/config.yaml` is missing or has no `testing`/`review` sections**:

```
Test Requirements:
  (no testing configuration — run project default tests before completing)

Review Process:
  (no review configuration — standard DoD checklist applies at completion)
```

**If task has no `prd_id`** (standalone task):

```
Acceptance Criteria:
  (no parent PRD — review against task description only)
```

Display whatever information is available; omit sections cleanly when their data source is absent.

## Implementation Dispatch

After reviewing the task details and review gate preview above, present the implementation options to the user:

```
AskUserQuestion({
  questions: [{
    question: "Ready to start implementation of {task_id}: {task.title}?",
    header: "Implementation",
    options: [
      { label: "Dispatch subagent", description: "Launch fresh agent with curated context (recommended)" },
      { label: "Implement here", description: "Implement in current session (existing behavior)" },
      { label: "Cancel", description: "Don't start this task" }
    ],
    multiSelect: false
  }]
})
```

### Option 1: Dispatch Subagent

If "Dispatch subagent" is selected, build a context package and launch a fresh agent with everything it needs inline.

#### Step 1: Build Context Package

Gather all relevant context into a single text block. The subagent receives everything inline — it never reads plan files directly.

```python
# 1. Task content (already loaded from start_task / get_task)
task = mcp__asdlc__get_task(task_id="{task_id}")
task_content = task["content"]  # Full markdown from file_path

# 2. Parent PRD content (if linked)
prd_section = ""
if task["prd_id"]:
    prd = mcp__asdlc__get_prd(prd_id=task["prd_id"])
    prd_section = prd["content"]

# 3. Design doc content (if exists)
design_section = ""
if task["prd_id"]:
    try:
        design = mcp__asdlc__get_design(prd_id=task["prd_id"])
        design_section = design["content"]
    except:
        pass  # No design doc — skip

# 4. Codebase artifacts (if scan completed)
codebase_section = ""
context = mcp__asdlc__get_context()
if context["artifacts"]["scan_status"] in ("complete", "partial"):
    codebase_summary = Read(".sdlc/artifacts/codebase-summary.md")
    codebase_section = codebase_summary

# 5. Review configuration
review_config = ""
try:
    config = Read(".sdlc/config.yaml")
    # Extract testing.commands, review.max_rounds, review.evidence_required
    review_config = config
except:
    pass  # No config — defaults apply
```

#### Step 2: Assemble Context Package

Build the inline text block that the subagent receives as its prompt context:

```
## Task
ID: {task.id}
Title: {task.title}
Priority: {task.priority} | Component: {task.component} | PRD: {task.prd_id}

{full task markdown content — including Implementation Steps, Acceptance Criteria, Traces To, etc.}

## Parent PRD
{prd content — or "No parent PRD linked to this task"}

## Design Document
{design doc content — or "No design document available"}

## Codebase Context
{codebase summary — or "No codebase scan available. Read files as needed."}

## Review Configuration
{review config excerpt — or "No .sdlc/config.yaml found. Use defaults: max_rounds=3, evidence_required=true"}
```

#### Step 3: Dispatch Subagent

Launch a fresh Task agent with the assembled context. The subagent runs synchronously — wait for its result.

```
Task(
  description="Implement {task.id}: {task.title}",
  prompt="""You are implementing task {task.id}: {task.title}

{assembled_context_package}

## Instructions

1. Read the task content above — it contains everything you need
2. Implement the task following the Implementation Steps section
3. Write tests as specified in the Acceptance Criteria
4. When you discover and fix issues during implementation, log them:
   mcp__asdlc__log_correction(context_type='task', context_id='{task.id}', category='{category}', description='{what was corrected and why}')
   Categories: testing, code-quality, task-completeness, integration, documentation, architecture, security, performance, process
5. Commit your changes: git add <files> && git commit -m "[{task.id}] {task.title}"

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

  'You are an independent code reviewer. Review the implementation of task {task.id} against its specification.

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
  mcp__asdlc__log_correction(context_type='task', context_id='{task.id}', category='{category}', description='{what_was_found_and_fixed}')
- Only after reviewer APPROVE (or user override): call mcp__asdlc__update_task(task_id='{task.id}', status='completed')
- If you encounter questions you cannot resolve from the provided context, surface them via AskUserQuestion — do NOT guess
""",
  subagent_type="general-purpose"
)
```

**Important**: Do NOT use `run_in_background=true` — wait for the subagent to complete so results can be displayed.

#### Step 4: Display Completion Result

After the subagent returns, display the outcome:

```
Subagent completed for {task.id}: {task.title}

Result: {COMPLETED | BLOCKED | FAILED}
Review: {APPROVED | OVERRIDDEN | BLOCKED}
Rounds: {rounds_used} / {max_rounds}

{if completed:}
  Run /sdlc:task-complete {task.id} to finalize (if not already marked complete by subagent).
  Or proceed to the next task.

{if blocked or failed:}
  Task remains in current status. Review the subagent output above for details.
  To retry: /sdlc:task-start {task.id}
```

---

### Option 2: Implement Here (Inline Mode)

If "Implement here" is selected, proceed with implementation in the current session. This preserves the existing behavior for users who prefer working inline.

#### During Implementation

When you discover and fix issues during implementation, log them immediately:

```
mcp__asdlc__log_correction(
  context_type="task",
  context_id="{task_id}",
  category="{category}",
  description="{what was corrected and why}"
)
```

**Categories:** `testing`, `code-quality`, `task-completeness`, `integration`, `documentation`, `architecture`, `security`, `performance`, `process`

Log corrections as they happen — don't wait until task completion.

When implementation is complete, run `/sdlc:task-complete {task_id}` which will trigger the full review gate process (self-review, subagent review, self-heal loop, evidence-based completion).

---

### Option 3: Cancel

If "Cancel" is selected, abort without starting the task. The task status remains unchanged (pending).

```
Task {task_id} was not started. Status remains: pending.
```

## Examples

```
/sdlc:task-start TASK-001
/sdlc:task-start TASK-002
```

## Related Commands

- `/sdlc:task-complete` - Mark task as completed (triggers review gates)
- `/sdlc:task-list` - View all tasks
- `/sdlc:task` - Get task details