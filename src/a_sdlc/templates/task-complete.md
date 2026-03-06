# /sdlc:task-complete

## Purpose

Mark a task as completed.

## Usage

Use the MCP tool to complete a task:

```
mcp__asdlc__complete_task(task_id="TASK-001")
```

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `task_id` | Yes | ID of the task to complete |

## Execution

1. Validates task exists
2. Updates status to `completed`
3. Sets `completed_at` timestamp
4. Returns updated task details
5. **Check if all PRD tasks are completed** (see below)

## Output

```json
{
  "status": "updated",
  "message": "Task updated: TASK-001",
  "task": {
    "id": "TASK-001",
    "title": "Implement authentication",
    "status": "completed",
    "completed_at": "2025-01-26T15:30:00Z"
  }
}
```

## Display Format

```
Task Completed: TASK-001 ✅

"Implement authentication"

Status: Completed
Completed at: 2025-01-26 15:30

Great work! 🎉
```

### Orchestration Compatibility Note

When this skill is invoked after subagent dispatch (from `/sdlc:task-start` or `/sdlc:sprint-run`), the implementation subagent may have already submitted self-review evidence via `submit_self_review()`. Before re-triggering the full review cycle:

1. Call `mcp__asdlc__get_review_evidence(task_id='{task_id}')` to check existing review state
2. If self-review evidence exists AND a subagent review verdict of `approve` is already recorded, **skip directly to Phase 4: Evidence-Based Completion** to avoid redundant review rounds
3. If self-review evidence exists but no subagent review verdict, skip the Self-Review Phase and proceed directly to **Phase 2: Orchestrator Review Dispatch**

If no review evidence is found, proceed with the full review cycle below.

### Persona Check (Section A from _round-table-blocks.md)

After loading task context, check for persona agents:
1. Check `~/.claude/agents/` for `sdlc-*.md` files
2. If `--solo` specified OR no personas found: round_table_enabled = false
3. Otherwise: round_table_enabled = true

### Domain Detection (Section B from _round-table-blocks.md)

If round_table_enabled = true:
1. Analyze task metadata and PRD content for domain signals
2. Assemble persona panel — QA Engineer leads review, Security Engineer as advisor
3. Display panel to user

### Self-Review Phase

Before finalizing completion, the implementing agent performs a structured self-review.

**Step 1: Load Review Configuration**

Read `.sdlc/config.yaml` and check the `review` and `testing` sections.

- If `review.self_review.enabled` is `false` OR `.sdlc/config.yaml` does not exist, skip to **Step 6** (Legacy DoD Checklist).
- Otherwise, proceed with Steps 2-5.
- Note the `review.max_rounds` value (default: 3) for the self-heal loop.
- Note `review.evidence_required` (default: true) for test output requirements.

**Step 2: Gather Review Context**

Collect everything needed for a thorough self-review:

1. Read the task content file (`get_task()` returns `file_path`) — extract:
   - **Traces To** — linked PRD requirements (FR-xxx, NFR-xxx, AC-xxx)
   - **Acceptance Criteria** — testable criteria from the task spec
   - **Scope Definition** — deliverables and exclusions
2. If the task has a `prd_id`, read the parent PRD content (`get_prd()`) — extract:
   - Functional requirements mapped to this task via Traces To
   - Non-functional requirements relevant to this task's component
   - PRD acceptance criteria linked via Traces To
3. Read `.sdlc/lesson-learn.md` and `~/.a-sdlc/lesson-learn.md` (if they exist) — filter for MUST/SHOULD lessons matching `{task.component}`.

**Step 3: Spec Compliance Review**

For each item in the task's **Traces To** section, verify:

- The linked PRD requirement is addressed by the implementation
- No requirement was partially implemented or skipped
- No functionality was added beyond what the linked requirements specify (anti-bloat check)

For each item in the task's **Acceptance Criteria**, verify:

- The criterion is satisfied by the implementation
- Evidence exists (test, output, or observable behavior) that proves it

Build a findings list:
```
findings = []

For each traced requirement:
  if NOT addressed → findings.append({
    dimension: "spec_compliance",
    severity: "critical",
    item: "<requirement_id>",
    detail: "Requirement not addressed in implementation"
  })

For each acceptance criterion:
  if NOT satisfied → findings.append({
    dimension: "spec_compliance",
    severity: "critical",
    item: "<criterion>",
    detail: "Acceptance criterion not met"
  })

For any extra functionality beyond scope:
  findings.append({
    dimension: "spec_compliance",
    severity: "warning",
    item: "scope_creep",
    detail: "Added <description> which is not in task requirements"
  })
```

**Step 4: Code Quality & Test Coverage Review**

Assess the implementation against code quality standards:

- **Lint check**: Run the project's lint command (e.g., from `testing.commands` in config). If it fails, add a finding with `dimension: "code_quality"` and `severity: "critical"`.
- **Duplication**: Check that no duplicative code was introduced — existing utilities should have been reused.
- **Pattern adherence**: Verify the implementation follows project patterns (naming, error handling, file placement).
- **Component lessons**: If MUST-level lessons were found in Step 2, verify each is followed. Add a `severity: "critical"` finding for any violated MUST lesson.

Assess test coverage using the **Smart Test Relevance Detection** section below (Steps 1-7 in that section). Incorporate the results:

- For each relevant test type with a RUN verdict, verify tests exist and pass.
- If `review.evidence_required` is `true`, the actual test command output from Step 6 of Smart Test Relevance Detection serves as evidence.

Add findings for any issues:
```
if lint_fails → findings.append({dimension: "code_quality", severity: "critical", ...})
if tests_missing → findings.append({dimension: "test_coverage", severity: "critical", ...})
if tests_fail → findings.append({dimension: "test_coverage", severity: "critical", ...})
if coverage_below_threshold → findings.append({dimension: "test_coverage", severity: "warning", ...})
if must_lesson_violated → findings.append({dimension: "code_quality", severity: "critical", ...})
```

**Step 5: Self-Heal Loop**

If findings with severity `critical` exist:

```
round = 1
max_rounds = config.review.max_rounds  # default: 3

while critical_findings exist AND round <= max_rounds:
  1. Fix each critical finding
  2. Re-run Steps 3-4 for affected dimensions only
  3. round += 1

if critical_findings still exist after max_rounds:
  Present unresolved issues to user via AskUserQuestion:

  AskUserQuestion({
    questions: [{
      question: "Self-review found unresolved issues after {max_rounds} fix attempts:",
      header: "Unresolved Review Findings",
      options: [
        { label: "Complete anyway", description: "Accept remaining issues and mark task complete" },
        { label: "Keep fixing", description: "Continue attempting to resolve the issues" },
        { label: "Block task", description: "Mark task as blocked for manual investigation" }
      ],
      multiSelect: false
    }]
  })

  If "Block task" → call update_task(task_id, status="blocked") and stop.
  If "Keep fixing" → reset round counter and continue the self-heal loop.
  If "Complete anyway" → proceed with warnings noted in the summary.
```

If no critical findings remain (or all were resolved), present the self-review summary:

```
Self-Review Summary for {task_id}:

Spec Compliance:
  {count} requirements verified ✅
  {count} acceptance criteria met ✅

Code Quality:
  Lint: ✅ passing
  Patterns: ✅ followed
  Lessons: ✅ {count} MUST items verified

Test Coverage:
  Relevant types: {list}
  Skipped (not relevant): {list with justification}
  Results: ✅ all passing
  {if evidence_required: "Evidence: <actual command output snippet>"}

Self-heal rounds used: {rounds_used} / {max_rounds}
Warnings: {count}
  {list any non-critical warnings}
```

Log review findings for retrospective use:
```
mcp__asdlc__log_correction(
  context_type="task",
  context_id="{task_id}",
  category="process",
  description="Self-review: {rounds_used} rounds, {critical_count} critical findings resolved, {warning_count} warnings"
)
```

Submit self-review evidence via the MCP tool:
```
mcp__asdlc__submit_self_review(
  task_id="{task_id}",
  verdict="pass",
  findings="{self_review_findings_summary}",
  test_output="{actual_test_command_output}"
)
```

If critical findings remain (user chose "Complete anyway"), submit with verdict `fail` and note the override:
```
mcp__asdlc__submit_self_review(
  task_id="{task_id}",
  verdict="fail",
  findings="{unresolved_findings}",
  test_output="{actual_test_command_output}"
)
```

Proceed to Phase 2 (Orchestrator Review Dispatch).

### Round-Table: Task Review (Section C from _round-table-blocks.md)

If round_table_enabled = true, extend the review step:

Execute round-table discussion following `_round-table-blocks.md` Section C:
1. Build context packages: each persona receives task content, changes made, and acceptance criteria
2. Detect mode (Agent Teams vs Task tool)
3. Dispatch personas for domain-specific review:
   - QA (lead): Test coverage, acceptance criteria verification, edge cases
   - Security (advisor): Vulnerability check, compliance, credential handling
   - Domain leads: Implementation quality from their perspective
4. Synthesize review findings — each finding attributed to its persona
5. Present before proceeding with completion

### Phase 2: Orchestrator Review Dispatch

After self-review passes and evidence is submitted via `submit_self_review()`, the task-complete orchestrator runs the review dispatch sequence. This follows the same pattern as sprint-run Step 4.4.

**Step 7: Check Review Configuration**

Read `.sdlc/config.yaml` — if the `review` section exists AND `review.self_review.enabled` is `true`, review is enabled. If the entire `review` section is absent, review is disabled — skip Phase 2 and Phase 3 entirely and proceed to Phase 4 (Evidence-Based Completion).

**Step 8: Verify Self-Review Evidence**

Call `mcp__asdlc__get_review_evidence(task_id='{task_id}')` to verify self-review was submitted:

- If missing → `mcp__asdlc__block_task(task_id='{task_id}', reason='self-review not submitted')` — task cannot complete. STOP.
- If present and verdict='fail' → `mcp__asdlc__block_task(task_id='{task_id}', reason='self-review failed')` — task cannot complete. STOP.
- If present and verdict='pass' → proceed to Step 9.

**Step 9: Check Subagent Review Configuration**

Read `.sdlc/config.yaml` and check `review.subagent_review.enabled`:

- If `review.subagent_review.enabled` is `false` OR the section does not exist → skip Phase 2 and Phase 3, proceed to Phase 4 (Evidence-Based Completion).
- Otherwise, continue with Step 10.

**Step 10: Dispatch Reviewer Subagent**

Launch a fresh Task agent for independent review. The reviewer reads self-review evidence via MCP tools and submits its verdict via `submit_review_verdict()`.

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

**Important**: Do NOT use `run_in_background=true` — this review must complete before proceeding.

**Step 11: Read and Process Verdict**

After the reviewer subagent returns, read the verdict:

```
evidence = mcp__asdlc__get_review_evidence(task_id='{task_id}')
verdict = evidence.review_verdict.verdict  # 'approve', 'request_changes', or 'escalate'
```

**If verdict is APPROVE:**
```
Subagent Review: APPROVED
Reviewer found no critical issues.
{include any warnings or info-level findings from evidence.review_verdict.findings}
```

Proceed directly to Phase 4 (Evidence-Based Completion).

**If verdict is ESCALATE:**

Present the reviewer's concerns to the user immediately:
```
AskUserQuestion({
  questions: [{
    question: "Task {task_id} reviewer escalated. Findings: {evidence.review_verdict.findings}. How to proceed?",
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

Handle the user's choice (same as Phase 3 escalation handling below).

**If verdict is REQUEST_CHANGES:**

Enter Phase 3 (Self-Heal Loop) below.

### Phase 3: Self-Heal Loop

When the reviewer subagent returns `request_changes` via `submit_review_verdict()`, the implementer fixes the issues and a fresh reviewer re-reviews. This loop repeats up to a configurable maximum number of rounds. After the maximum is exceeded, the user is escalated.

**Step 12: Initialize Loop State**

```
review_round = 1
max_rounds = config.review.max_rounds  # from .sdlc/config.yaml, default: 3
all_findings = []           # accumulated findings across all rounds
resolved_findings = []      # findings that were fixed
unresolved_findings = []    # findings still open
review_log = []             # per-round log entries for task file appendage
```

Parse the reviewer's findings from the `get_review_evidence()` response:
```
evidence = mcp__asdlc__get_review_evidence(task_id='{task_id}')
current_findings = evidence.review_verdict.findings  # structured list from submit_review_verdict
all_findings.extend(current_findings)
```

**Step 13: Fix-Review Cycle**

```
while unresolved critical findings exist AND review_round <= max_rounds:

  ## 13a: Dispatch implementing subagent with fix instructions
  Launch a fresh implementing subagent with the reviewer's findings:

  Task(
    description="Fix review findings for {task_id}: {task_title}",
    prompt="You are fixing review findings for task {task_id}.

           Previous reviewer findings:
           {evidence.review_verdict.findings}

           Fix each critical finding, re-run tests, then:
           1. Call mcp__asdlc__submit_self_review(task_id='{task_id}', verdict='pass'|'fail', findings='...', test_output='...')
           2. Do NOT call update_task(status='completed') — the orchestrator handles completion
           ",
    subagent_type="{resolve via Section D from _round-table-blocks.md using task.component}"
  )

  ## 13b: Verify updated self-review
  evidence = mcp__asdlc__get_review_evidence(task_id='{task_id}')
  if not evidence.self_review or evidence.self_review.verdict == 'fail':
      mcp__asdlc__block_task(task_id='{task_id}', reason='self-review failed after fix round')
      break

  ## 13c: Dispatch fresh reviewer subagent
  Launch a NEW reviewer Task agent (same pattern as Step 10):

  Task(
    description="Review {task_id}: {task_title} (round {review_round + 1})",
    prompt="You are an independent code reviewer. Review task {task_id}.

           Call mcp__asdlc__get_review_evidence(task_id='{task_id}') to read the self-review.
           Review the git diff and test output.

           This is review round {review_round + 1}. Previous findings were:
           {previous_findings_summary}

           Focus on: (1) whether fixes address previous findings, (2) any new issues from fixes, (3) remaining unresolved items.

           Evaluate: spec compliance, code quality, test coverage.

           Call mcp__asdlc__submit_review_verdict(task_id='{task_id}', verdict='approve'|'request_changes'|'escalate', findings='...') with your verdict.
           ",
    subagent_type="sdlc-qa-engineer"
  )

  ## 13d: Read new verdict
  evidence = mcp__asdlc__get_review_evidence(task_id='{task_id}')
  verdict = evidence.review_verdict.verdict

  ## 13e: Log round to review log
  review_log.append({
    round: review_round,
    findings_in: count of findings entering this round,
    resolved: count resolved this round,
    remaining: count still unresolved,
    verdict: verdict
  })

  ## 13f: Process new verdict
  If verdict is 'approve' → break loop, proceed to Phase 4
  If verdict is 'request_changes' → parse new findings, review_round += 1, continue loop
  If verdict is 'escalate' → AskUserQuestion immediately (same as Step 14 below)

  review_round += 1
```

**Step 14: User Escalation (Max Rounds Exceeded)**

If `review_round > max_rounds` and unresolved critical findings still exist:

```
AskUserQuestion({
  questions: [{
    question: "Task {task_id} failed review after {review_round - 1} rounds. How to proceed?",
    header: "Review Escalation — Max Rounds Reached",
    options: [
      { label: "Override & complete", description: "Accept current state with remaining issues noted, mark task complete" },
      { label: "Continue fixing", description: "Reset round counter and continue attempting fixes (you may also fix issues manually)" },
      { label: "Block task", description: "Mark task as blocked for manual investigation later" }
    ],
    multiSelect: false
  }]
})
```

Handle the user's choice:

```
If "Block task":
  call mcp__asdlc__block_task(task_id="{task_id}", reason="Review failed after {max_rounds} rounds")
  Log to corrections:
    mcp__asdlc__log_correction(
      context_type="task",
      context_id="{task_id}",
      category="process",
      description="Task blocked after {review_round - 1} review rounds. Unresolved: {unresolved_findings summary}"
    )
  STOP — do not proceed further.

If "Continue fixing":
  review_round = 1  # reset counter
  Re-enter the fix-review cycle at Step 13.
  (User may also make manual fixes before the next cycle.)

If "Override & complete":
  Note all unresolved findings as warnings in the completion summary.
  Proceed to Phase 4 with override_mode = true.
```

**Step 15: Log All Review Findings**

After the self-heal loop completes (whether by approval, override, or block), log all findings for retrospective consumption:

```
For each finding in all_findings:
  mcp__asdlc__log_correction(
    context_type="task",
    context_id="{task_id}",
    category="{finding.dimension}",  # maps to: code-quality, testing, task-completeness
    description="Review finding [{finding.severity}]: {finding.detail} — Status: {resolved|unresolved}"
  )
```

Category mapping for `log_correction()`:
- `spec_compliance` dimension → category `"task-completeness"`
- `code_quality` dimension → category `"code-quality"`
- `test_coverage` dimension → category `"testing"`

Additionally, log a process-level summary:
```
mcp__asdlc__log_correction(
  context_type="task",
  context_id="{task_id}",
  category="process",
  description="Review completed: {total_rounds} rounds, {resolved_count} findings resolved, {unresolved_count} unresolved, verdict: {final_verdict}"
)
```

**Step 16: Append Review Log to Task File**

After logging corrections, append a review history section to the task's content file. Read the task file path from `get_task(task_id)`, then append:

```markdown
## Review Log

| Round | Findings | Resolved | Remaining | Verdict |
|-------|----------|----------|-----------|---------|
{for each entry in review_log:}
| {round} | {findings_in} | {resolved} | {remaining} | {verdict} |

**Final Verdict:** {APPROVED | OVERRIDDEN | BLOCKED}
**Total Rounds:** {total_rounds} / {max_rounds}
**Resolved:** {resolved_count} | **Unresolved:** {unresolved_count}

{if unresolved findings exist:}
### Unresolved Findings
{for each unresolved finding:}
- [{severity}] {dimension}: {detail}
```

Use the `Edit` tool to append this section to the task file (do not overwrite existing content).

### Phase 4: Evidence-Based Completion

After the review process concludes with approval (or user override), present an evidence-based completion summary to the user before finalizing.

**Step 17: Build Evidence Summary**

Gather actual evidence from the review process:

1. **Review evidence** — Call `mcp__asdlc__get_review_evidence(task_id='{task_id}')` to retrieve self-review findings and subagent review verdict
2. **Test results** — Actual command output from Smart Test Relevance Detection (Step 6 of that section), also available in the self-review evidence
3. **Lint results** — Actual lint command output from Step 4 (Code Quality review)
4. **Acceptance criteria** — Count from Step 3 (Spec Compliance review)
5. **Review verdict** — Final verdict and round count from Phase 3 (or Phase 2 if approved on first pass)
6. **Manual tests** — Any test types that were deferred or skipped with rationale

Present the summary:

```
DoD Evidence Summary for {task_id}:
  Tests:       {PASS|FAIL} ({X} passed, {Y} failed) — ran: {test_command}
  Lint:        {PASS|FAIL} ({N} warnings) — ran: {lint_command}
  ACs:         {met}/{total} PASS
  Review:      {Approved|Overridden} (round {N}/{max_rounds})
  {if override_mode: "⚠️  Overridden with unresolved findings — see Review Log"}
  Manual tests deferred: {list with rationale, or "none"}
```

**Step 18: User Confirmation**

Ask the user to confirm task completion:

```
AskUserQuestion({
  questions: [{
    question: "Review the evidence summary above. Confirm task completion?",
    header: "Task Completion Confirmation — {task_id}",
    options: [
      { label: "Confirm complete", description: "Mark task as completed with the evidence above" },
      { label: "Hold", description: "Do not complete yet — I want to review or make changes first" }
    ],
    multiSelect: false
  }]
})
```

**If "Confirm complete":**
```
call mcp__asdlc__complete_task(task_id="{task_id}")
```
Then proceed to Log Corrections, Check PRD Completion, and Suggest Next Task.

**If "Hold":**
```
Task {task_id} held for review. Status remains "in_progress".
The evidence summary and review log are preserved in the task file.
Run /sdlc:task-complete {task_id} again when ready to finalize.
```
STOP — do not proceed further.

**Step 6: Legacy DoD Checklist (Fallback)**

This step runs only when self-review is disabled (`review.self_review.enabled: false`) or `.sdlc/config.yaml` does not exist.

Read `.sdlc/lesson-learn.md` (if exists) for component-specific lessons.

```
AskUserQuestion({
  questions: [{
    question: "Confirm definition-of-done for this task:",
    header: "DoD check",
    options: [
      { label: "Tests passing", description: "All new and existing tests pass" },
      { label: "Lint clean", description: "No new linting warnings or errors" },
      { label: "Requirements met", description: "All task acceptance criteria satisfied" },
      { label: "No duplication", description: "No duplicative code introduced — reused existing utilities" }
    ],
    multiSelect: true
  }]
})
```

If lesson-learn.md has MUST-level items for this task's component, add them to the checklist.

If any standard checks are unchecked, warn:
> Some definition-of-done items were not confirmed. Consider addressing before completion.

Proceed to Smart Test Relevance Detection, then Log Corrections regardless (user has been warned).

## Smart Test Relevance Detection

Before running tests, assess which test types are actually relevant to the changes made in this task. This avoids wasting time on irrelevant test suites and produces meaningful coverage evidence.

### Step 1: Load Testing Configuration

Read `.sdlc/config.yaml` and extract the `testing` section:

```yaml
testing:
  defaults:
    required: [unit, integration]
  commands:
    unit: uv run pytest tests/ -v
    integration: ""
    e2e: ""
  coverage:
    min_threshold: 0
  relevance:
    enabled: true
```

If `testing.relevance.enabled` is `false` or the `testing` section is missing, skip relevance detection and run all configured test types from `testing.defaults.required`.

### Step 2: Assess Change Scope

Analyze the task's changes to determine what was modified. Categorize the change scope:

| Change Scope | Description | Examples |
|--------------|-------------|----------|
| **backend-logic** | Business logic, data processing, algorithms | Service functions, utilities, core modules |
| **api-endpoints** | HTTP routes, request/response handling | Controllers, route handlers, middleware |
| **database** | Schema changes, queries, migrations | Models, repositories, migration files |
| **frontend-ui** | Visual components, layouts, styles | Components, CSS, templates |
| **configuration** | Config files, environment, build setup | YAML, env files, build configs |
| **documentation** | Docs, comments, templates (non-code) | Markdown files, docstrings, skill templates |
| **infrastructure** | Deployment, CI/CD, containerization | Dockerfiles, pipeline configs, IaC |
| **test-only** | Only test files were changed | Test files, fixtures, test utilities |

### Step 3: Apply Decision Matrix

For each test type in `testing.defaults.required`, determine relevance based on the change scope:

| Test Type | backend-logic | api-endpoints | database | frontend-ui | configuration | documentation | infrastructure | test-only |
|-----------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **unit** | RUN | RUN | RUN | RUN | SKIP | SKIP | SKIP | RUN |
| **integration** | ASSESS | RUN | RUN | ASSESS | ASSESS | SKIP | ASSESS | SKIP |
| **e2e** | SKIP | ASSESS | ASSESS | RUN | SKIP | SKIP | ASSESS | SKIP |
| **performance** | ASSESS | ASSESS | ASSESS | SKIP | SKIP | SKIP | SKIP | SKIP |
| **security** | ASSESS | RUN | RUN | SKIP | ASSESS | SKIP | ASSESS | SKIP |
| **accessibility** | SKIP | SKIP | SKIP | RUN | SKIP | SKIP | SKIP | SKIP |

Legend:
- **RUN** — Always relevant for this change scope. Run the test suite.
- **ASSESS** — May be relevant. Evaluate based on the specific files changed (see Step 4).
- **SKIP** — Not relevant for this change scope. Skip with rationale.

### Step 4: Resolve ASSESS Verdicts

For each test type marked ASSESS, evaluate the specific changes:

- **Does the change affect a boundary between components?** If yes, integration tests are relevant.
- **Does the change alter user-facing behavior or flows?** If yes, e2e tests are relevant.
- **Does the change affect data handling, input parsing, or auth?** If yes, security tests are relevant.
- **Does the change affect response times, query complexity, or resource usage?** If yes, performance tests are relevant.
- **Does the change affect infrastructure that serves user traffic?** If yes, e2e/integration tests are relevant.

If uncertain after assessment, default to **RUN** — it is better to run a potentially irrelevant suite than to miss a regression.

### Step 5: Produce Relevance Report

Before executing any tests, output the relevance determination in this format:

```
Test Relevance Assessment for {task_id}:
Change scope: {scope(s) identified}

  unit         → RUN    (business logic changed in core/database.py)
  integration  → SKIP   (no cross-component boundaries affected)
  e2e          → SKIP   (no user-facing behavior changed — template-only edit)
```

For each SKIP verdict, a rationale is **required**. The rationale must reference the specific change scope and explain why the test type does not apply.

### Step 6: Execute Relevant Tests

For each test type with a RUN verdict:

1. Look up the command in `testing.commands.{type}` from config
2. If the command is empty (`""`), warn: `No command configured for {type} tests — skipping`
3. If the command exists, execute it and capture the output
4. The actual command output serves as **evidence of completion** (per `review.evidence_required`)

```
Running unit tests: uv run pytest tests/ -v
─────────────────────────────────────────
{actual test output here}
─────────────────────────────────────────
Result: PASSED (42 tests, 0 failures)
```

If any test suite fails, do NOT proceed to completion. Fix the failures first, then re-run.

### Step 7: Coverage Check

If `testing.coverage.min_threshold` is greater than 0:

1. Run coverage collection alongside the relevant test commands
2. Compare actual coverage against the threshold
3. If below threshold, warn the user and do not proceed to completion

If `min_threshold` is 0, skip coverage enforcement.

## Runtime Test Validation

**Config-gated**: Only runs if `testing.runtime` is configured in `.sdlc/config.yaml`.

> This section validates the running application after code changes. It catches issues that static tests miss — broken UI flows, API regressions, and runtime errors.

### Step RT-1: Check Runtime Test Configuration

Read `.sdlc/config.yaml` and check for `testing.runtime` section:
- If `testing.runtime` is **NOT** present or empty → **SKIP** this entire section, proceed to the next section
- If `testing.runtime` **IS** present → continue to Step RT-2

### Step RT-2: Determine Test Scope

Using the current task ID:
1. The task ID is already known from the task-complete context
2. The parent PRD ID is already loaded from task metadata

### Step RT-3: Execute Runtime Tests

Run the same test logic as `/sdlc:test --task {task_id}`:
1. Load `testing.runtime` config (app_url, mode, api_base, etc.)
2. Check app readiness — verify the app is running at the configured URL
3. If app is not running and `start_command` is configured, offer to start it
4. Generate test scenarios from the task's acceptance criteria and parent PRD
5. Execute browser tests via Playwright MCP (if available and mode includes frontend)
6. Execute API tests via Bash/curl (if mode includes backend)
7. Collect results

### Step RT-4: Evaluate Results

**If all runtime tests pass:**
- Log: "Runtime tests passed ({passed}/{total})"
- Add to evidence: include test result summary
- Proceed to the next section

**If any runtime tests fail:**
- Display the failure report with screenshots (browser) and response bodies (API)
- **BLOCK**: Do NOT proceed to task completion
- Display message: "Runtime tests failed. Fix the issues and re-run /sdlc:task-complete"
- Log correction: `mcp__asdlc__log_correction(context_type='task', context_id='{task_id}', category='testing', description='Runtime test failure: {summary of failures}')`
- Use `AskUserQuestion` to offer options:
  - "Fix and retry" — Stop here, let user fix issues, then re-run task-complete
  - "Skip runtime tests" — Proceed without runtime validation (logs a warning)
  - "View details" — Show full test output before deciding

**If app is not reachable and no start_command configured:**
- Display warning: "Runtime testing configured but app is not reachable at {app_url}. Skipping runtime tests."
- Proceed to the next section (do not block)

## Log Corrections

After Phase 4 (Evidence-Based Completion) confirms the task, or after the Legacy DoD Checklist, log any additional corrections or fixes made during this task's implementation that were not already logged by Phase 3 (Step 14).

Note: If the full review pipeline ran (Phases 1-4), review findings are already logged in Step 14. This section captures any remaining implementation-level corrections not covered by the review process.

For each fix, bug correction, or mistake caught during the task:

```
mcp__asdlc__log_correction(
  context_type="task",
  context_id="{task_id}",
  category="{category}",
  description="{what was fixed and why}"
)
```

**Categories:** `testing`, `code-quality`, `task-completeness`, `integration`, `documentation`, `architecture`, `security`, `performance`, `process`

If no corrections were needed, skip this step.

## Check PRD Completion

After completing a task, check if all tasks for the parent PRD are now completed:

1. Get the task's `prd_id` from the completed task response
2. If `prd_id` exists, list all tasks for that PRD:
   ```
   mcp__asdlc__list_tasks(prd_id="<prd_id>")
   ```
3. Check if ALL tasks have status "completed"
4. If yes, update PRD status to "completed":
   ```
   mcp__asdlc__update_prd(prd_id="<prd_id>", status="completed")
   ```
5. Notify user: "All tasks for PRD <prd_id> are complete. PRD marked as completed."

**Example check:**
```
Tasks for PRD feature-auth:
  TASK-001: completed ✅
  TASK-002: completed ✅
  TASK-003: completed ✅  ← just completed

All tasks done → Update PRD status to "completed"
```

## Suggest Next Task

After completing, optionally suggest the next task:

```
mcp__asdlc__list_tasks(status="pending")
```

```
Next suggested tasks:
  TASK-002  [High] Add rate limiting         [SPRINT-01]
  TASK-003  [High] Implement user profile    [SPRINT-01]
```

## Examples

```
/sdlc:task-complete TASK-001
/sdlc:task-complete TASK-002
```

## Related Commands

- `/sdlc:task-start` - Start a task
- `/sdlc:task-list` - View all tasks
- `/sdlc:sprint-run` - Continue sprint execution