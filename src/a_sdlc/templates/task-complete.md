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

When this skill is invoked after subagent dispatch (from `/sdlc:task-start` or `/sdlc:sprint-run`), the implementation subagent may have already performed self-review, subagent review, and committed changes. Before re-triggering the full review cycle:

1. Check if the task has recent commits by the implementation subagent (`git log --oneline -5`)
2. Check if corrections were already logged for this task (`grep {task_id} .sdlc/corrections.log`)
3. If evidence of prior review exists (commits, logged corrections, review verdicts in agent output), **skip directly to Phase 4: Evidence-Based Completion** (the final confirmation and logging steps) to avoid redundant review rounds

If no evidence of prior review is found, proceed with the full review cycle below.

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

Proceed to Phase 2 (Subagent Review).

### Phase 2: Subagent Review

After self-review passes (no critical findings remaining), dispatch a fresh subagent for independent review. This provides an unbiased second opinion with full context but without the implementing agent's assumptions.

**Step 7: Check Subagent Review Configuration**

Read `.sdlc/config.yaml` and check the `review.subagent_review` section:

```yaml
review:
  subagent_review:
    enabled: true
```

- If `review.subagent_review.enabled` is `false` OR the section does not exist, skip Phase 2 and Phase 3 entirely and proceed to Phase 4 (Evidence-Based Completion).
- Otherwise, continue with Steps 8-10.

**Step 8: Gather Review Context**

Collect curated context for the reviewer subagent. Use selective injection — diffs and summaries, not full file contents:

1. **Task spec** — Read task content via `get_task(task_id)`. Extract:
   - Traces To section (requirement IDs)
   - Acceptance Criteria (testable criteria)
   - Scope Definition (deliverables and exclusions)
   - Implementation Steps (expected approach)

2. **PRD content** — If the task has a `prd_id`, read PRD via `get_prd(prd_id)`. Extract:
   - Functional requirements mapped to this task
   - Non-functional requirements for this task's component
   - Acceptance criteria linked via Traces To

3. **Design doc** — If the PRD has a design doc, read via `get_design(prd_id)`. Extract:
   - Architecture decisions relevant to this task
   - Technical constraints and patterns specified

4. **Self-review report** — The summary produced at the end of Step 5, including:
   - Spec compliance results
   - Code quality assessment
   - Test coverage results
   - Self-heal rounds used and any warnings

5. **Code diff** — Run `git diff` to capture the task's changes:
   ```
   git diff HEAD~1  # or appropriate range covering this task's commits
   ```
   Use the diff output directly — do NOT include full file contents. If the diff exceeds 200 lines, summarize unchanged sections with `[... N unchanged lines ...]` markers.

6. **Codebase artifacts** (truncated) — Read from `.sdlc/artifacts/`:
   - `architecture.md` — first 100 lines (high-level structure only)
   - `codebase-summary.md` — first 100 lines (overview only)
   If these files do not exist, skip them.

**Step 9: Dispatch Reviewer Subagent**

Launch a fresh Task agent with the review prompt. The subagent must run synchronously — wait for its result before proceeding.

```
Task(
  description="Independent code review for {task_id}",
  prompt="You are an independent code reviewer. Review the implementation of task {task_id} against its specification.

## Your Role
You are a fresh reviewer with NO prior context about this implementation. Evaluate objectively based ONLY on the materials provided below. If the provided documentation does not answer a question, use AskUserQuestion to escalate — do NOT assume or guess.

## Review Materials

### Task Specification
{task_spec_content}

### PRD Requirements
{prd_content_or_'No PRD linked to this task'}

### Design Document
{design_doc_content_or_'No design doc available'}

### Self-Review Report (from implementing agent)
{self_review_summary}

### Code Changes (diff)
```diff
{git_diff_output}
```

### Codebase Context
{truncated_architecture_md}
{truncated_codebase_summary_md}

## Evaluation Dimensions

Evaluate the implementation across three dimensions:

### 1. Spec Compliance
- For each item in Traces To: Is the linked requirement fully addressed?
- For each Acceptance Criterion: Is it satisfied by the implementation?
- Scope check: Was anything added beyond what the spec requires? (anti-bloat)
- Scope check: Was anything omitted that the spec requires? (gap detection)

### 2. Code Quality
- Does the code follow project patterns visible in the codebase context?
- Is error handling appropriate and consistent?
- Are naming conventions consistent with the project?
- Is there unnecessary duplication that should use existing utilities?
- Are there security concerns (hardcoded secrets, injection risks, etc.)?

### 3. Test Coverage
- Do tests exist for the new functionality?
- Do the tests cover the acceptance criteria?
- Are edge cases tested?
- Did the self-review report show all tests passing?

## Escalation Rule
If you encounter a question that the provided documentation does not answer — for example, an ambiguous requirement, an unclear project convention, or a design decision not documented — you MUST escalate to the user:

AskUserQuestion({{
  questions: [{{
    question: 'During review of {task_id}, I need clarification: {{your_specific_question}}',
    header: 'Reviewer Question',
    options: [
      {{ label: 'Provide answer', description: 'I will answer this question' }},
      {{ label: 'Skip this check', description: 'Proceed without this evaluation point' }}
    ],
    multiSelect: false
  }}]
}})

## Required Output Format

You MUST produce your review in exactly this structure:

REVIEW VERDICT: [APPROVE | REQUEST_CHANGES | ESCALATE_TO_USER]

SPEC COMPLIANCE:
  Status: [PASS | FAIL]
  Requirements verified: [count]
  Gaps found: [list or 'none']
  Bloat detected: [list or 'none']

CODE QUALITY:
  Status: [PASS | FAIL]
  Pattern adherence: [GOOD | ISSUES_FOUND]
  Issues: [list or 'none']

TEST COVERAGE:
  Status: [PASS | FAIL]
  Tests exist: [yes/no]
  Tests passing: [yes/no/not_verified]
  AC coverage: [complete/partial/missing]
  Gaps: [list or 'none']

FINDINGS:
  [List each finding with severity (critical/warning/info) and actionable detail]
  [If no findings: 'No issues found']

SUMMARY:
  [1-2 sentence overall assessment]
",
  subagent_type="general-purpose"
)
```

**Important**: Do NOT use `run_in_background=true` — this review must complete before proceeding.

**Step 10: Process Initial Review Result**

Parse the reviewer subagent's output and extract the verdict. The initial verdict determines the next step:

**If verdict is APPROVE:**
```
Subagent Review: APPROVED ✅
Reviewer found no critical issues.
{include any warnings or info-level findings}
```

Proceed directly to Phase 4 (Evidence-Based Completion).

**If verdict is ESCALATE_TO_USER:**
```
Subagent Review: ESCALATED TO USER
The reviewer needs clarification on the following:
{list each escalation question}
```

Present the reviewer's questions to the user via AskUserQuestion. After receiving answers, re-dispatch the reviewer subagent (Step 9) with the user's answers appended to the review prompt:

```
### User Clarifications
Q: {question}
A: {user_answer}
```

After re-dispatch, process the new verdict through this same Step 10.

**If verdict is REQUEST_CHANGES:**

Enter Phase 3 (Self-Heal Loop) below.

### Phase 3: Self-Heal Loop

When the subagent reviewer returns `REQUEST_CHANGES`, the implementer fixes the issues and a fresh reviewer re-reviews. This loop repeats up to a configurable maximum number of rounds. After the maximum is exceeded, the user is escalated with an unresolved issue summary.

**Step 11: Initialize Loop State**

```
review_round = 1
max_rounds = config.review.max_rounds  # from .sdlc/config.yaml, default: 3
all_findings = []           # accumulated findings across all rounds
resolved_findings = []      # findings that were fixed
unresolved_findings = []    # findings still open
review_log = []             # per-round log entries for task file appendage
```

Parse the reviewer's findings from the `REQUEST_CHANGES` verdict into a structured list:
```
current_findings = [
  { severity: "critical|warning|info", dimension: "spec_compliance|code_quality|test_coverage", detail: "..." },
  ...
]
all_findings.extend(current_findings)
```

**Step 12: Fix-Review Cycle**

```
while unresolved critical findings exist AND review_round <= max_rounds:

  ## 12a: Fix each critical finding
  For each finding with severity "critical":
    1. Implement the fix (code change, test addition, etc.)
    2. Re-run ONLY the affected checks:
       - If dimension is "code_quality" → re-run lint command
       - If dimension is "test_coverage" → re-run relevant test commands
       - If dimension is "spec_compliance" → re-verify the specific requirement
    3. If fix resolves the finding, move it to resolved_findings
    4. If fix does NOT resolve it, keep in unresolved_findings

  ## 12b: Update self-review report
  Re-run Steps 3-4 (Spec Compliance and Code Quality reviews) for affected dimensions only.
  Update the self-review summary with current state.

  ## 12c: Capture updated diff
  Run: git diff HEAD~1  (or appropriate range covering all task changes including fixes)

  ## 12d: Dispatch fresh reviewer subagent
  Launch a NEW Task agent (not the same instance) with:
    - Updated code diff (from 12c, reflecting all fixes made so far)
    - Previous round's findings summary (NOT the full transcript)
    - Updated self-review report (from 12b)
    - Same review prompt structure as Step 9, with this additional section:

    ### Previous Review Round ({review_round})
    Findings from previous round:
    {list each finding with status: resolved/unresolved}

    Resolved in this round:
    {list fixes applied}

    Focus your review on:
    1. Whether the fixes adequately address the previous findings
    2. Whether any new issues were introduced by the fixes
    3. Any remaining unresolved items

  ## 12e: Log round to review log
  review_log.append({
    round: review_round,
    findings_in: count of findings entering this round,
    resolved: count resolved this round,
    remaining: count still unresolved,
    verdict: reviewer_verdict
  })

  ## 12f: Process new verdict
  If verdict is APPROVE → break loop, proceed to Phase 4
  If verdict is REQUEST_CHANGES → parse new findings, review_round += 1, continue loop
  If verdict is ESCALATE_TO_USER → handle escalation (present questions, re-dispatch), then re-process verdict

  review_round += 1
```

**Step 13: User Escalation (Max Rounds Exceeded)**

If `review_round > max_rounds` and unresolved critical findings still exist:

```
AskUserQuestion({
  questions: [{
    question: "Review found unresolved issues after {review_round - 1} fix rounds:\n\n" +
              "{for each unresolved finding: '- [{severity}] {dimension}: {detail}\n'}" +
              "\nRounds summary:\n" +
              "{for each round in review_log: 'Round {round}: {findings_in} findings → {resolved} resolved, {remaining} remaining\n'}",
    header: "Unresolved Review Findings — Max Rounds Reached",
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
  call mcp__asdlc__update_task(task_id="{task_id}", status="blocked")
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
  Re-enter the fix-review cycle at Step 12.
  (User may also make manual fixes before the next cycle.)

If "Override & complete":
  Note all unresolved findings as warnings in the completion summary.
  Proceed to Phase 4 with override_mode = true.
```

**Step 14: Log All Review Findings**

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

**Step 15: Append Review Log to Task File**

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

**Step 16: Build Evidence Summary**

Gather actual evidence from the review process:

1. **Test results** — Actual command output from Smart Test Relevance Detection (Step 6 of that section)
2. **Lint results** — Actual lint command output from Step 4 (Code Quality review)
3. **Acceptance criteria** — Count from Step 3 (Spec Compliance review)
4. **Review verdict** — Final verdict and round count from Phase 3 (or Phase 2 if approved on first pass)
5. **Manual tests** — Any test types that were deferred or skipped with rationale

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

**Step 17: User Confirmation**

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