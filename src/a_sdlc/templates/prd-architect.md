# /sdlc:prd-architect "<prd_id>"

## Purpose

Generate an ADR-style (Architecture Decision Record) design document for an existing PRD by analyzing the actual codebase. Produces a codebase-grounded architecture document with user review.

## Arguments

- **prd_id**: PRD identifier (e.g., "PROJ-P0001")

## CRITICAL: Scope Boundaries

**This skill ONLY creates design documents. It does NOT implement features.**

- **NEVER** proceed to task creation, splitting, or implementation
- **NEVER** write source code or make code changes
- **NEVER** use TaskCreate, TodoWrite, or Edit tools
- **NEVER** call `mcp__asdlc__create_task()` or `mcp__asdlc__split_prd()`
- **ALWAYS** stop after design document creation and wait for user's next command

**RIGHT**: Analyze codebase → Generate design → Review → Save → STOP
**WRONG**: Generate design → Split into tasks → Start implementing

## CRITICAL: Anti-Fluff Rules

**Every design decision must trace to PRD requirements AND codebase analysis. Zero speculative architecture.**

- **MUST NOT** propose patterns, frameworks, or libraries not already in the codebase unless the PRD explicitly requires them
- **MUST NOT** add architectural decisions that address problems not stated in the PRD
- **MUST NOT** hallucinate file paths, module names, or component names — every reference must come from actually reading the code
- **MUST NOT** suggest "future-proofing" changes beyond what the PRD scope requires
- **MUST NOT** use vague architecture language ("scalable solution", "robust framework", "clean architecture") without grounding in specific codebase patterns
- **MUST NOT** infer integration points — verify they exist by reading the actual code
- **MUST NOT** propose alternatives that cannot be implemented given the current codebase constraints
- **MUST** cite real file paths (e.g., `src/auth/middleware.py:45`) for every affected component
- **MUST** reference existing patterns found in the codebase (e.g., "follows the same adapter pattern as `storage/__init__.py`")
- **MUST** ground every decision in either a PRD requirement (cite FR/NFR ID) or a codebase constraint (cite file/pattern)
- **MUST** verify component existence by reading code before referencing it

**Traceability Rule:** For each design decision, tag it with `[FR-XXX]` or `[Codebase: path/to/file]` to verify grounding. If you cannot tag it, do not include it.

**If evidence is missing, state the gap — do not fill it with assumptions.**

## Execution Steps

### 1. Load Context

```
context = mcp__asdlc__get_context()
prd = mcp__asdlc__get_prd(prd_id)
existing_design = mcp__asdlc__get_design(prd_id)
```

- If `context.status == "no_project"`: Display error and stop
- If `prd.status == "not_found"`: Display error and stop
- If `existing_design.status == "ok"`: Warn that design already exists. Ask user via AskUserQuestion whether to overwrite or cancel.

Display PRD title and key requirements for reference.

### Persona Check (Section A from _round-table-blocks.md)

After loading context, check for persona agents:
1. Check `~/.claude/agents/` for `sdlc-*.md` files
2. If `--solo` specified OR no personas found: round_table_enabled = false
3. Otherwise: round_table_enabled = true

### Domain Detection (Section B from _round-table-blocks.md)

If round_table_enabled = true:
1. Analyze PRD requirements for domain signals
2. Assemble persona panel — Architect always included as lead for design phase
3. Display panel to user

### 2. Codebase Analysis

**This step MUST read actual code. Do NOT skip or approximate.**

#### 2.1: Read Artifacts (Parallel Batch)

**Read all files in a single parallel batch — do NOT read them sequentially.**

If `.sdlc/artifacts/` exists, read all 7 files in one parallel batch:
```
Parallel Read (all at once):
- .sdlc/artifacts/architecture.md
- .sdlc/artifacts/directory-structure.md
- .sdlc/artifacts/codebase-summary.md
- .sdlc/artifacts/data-model.md
- .sdlc/artifacts/key-workflows.md
- .sdlc/lesson-learn.md
- ~/.a-sdlc/lesson-learn.md
```

If artifacts don't exist:
```
Warn: No codebase artifacts found. Run `/sdlc:scan` first for best results.
      Proceeding with direct codebase analysis...
```
Read only the lesson-learn files (parallel) and continue to direct codebase analysis.

#### 2.2: Analyze Affected Components (Batched)

**Group related FRs by component rather than analyzing each FR individually.**

1. Scan all functional requirements and group them by affected component/module
2. For each component group:
   - If artifacts already describe the component sufficiently, use artifact data — do NOT re-read the source
   - If artifacts are missing or insufficient for this component, read the actual source files
   - Find 1-2 similar implementations in the codebase that this design should follow
3. Document existing patterns with file paths and line references

Record findings as structured evidence:
```
Evidence Log:
- [src/module/file.py] FR-001, FR-003 → class X, method Y (from artifacts)
- [src/new_area/] FR-002 → new component needed, follows pattern in src/existing/similar.py (source read)
- Existing pattern: adapter pattern used in src/storage/__init__.py
```

#### 2.3: Identify Constraints

From codebase analysis, identify:
- Database schema implications (migrations needed?)
- API contract changes (backward compatibility?)
- Dependency additions (new packages?)
- Test infrastructure (existing test patterns?)

### Round-Table: Architecture Review (Section C from _round-table-blocks.md)

If round_table_enabled = true, run after Step 2 and before Step 3:

Execute round-table discussion following `_round-table-blocks.md` Section C:
1. Build context packages: each persona receives PRD + codebase analysis from Step 2
2. Detect mode (Agent Teams vs Task tool)
3. Dispatch personas — Architect leads architecture review:
   - Architect evaluates architectural patterns and trade-offs
   - Domain leads challenge design from their implementation perspective
   - Security validates security architecture decisions
   - QA validates testability of proposed architecture
4. Synthesize — present architectural recommendations and disagreements
5. User reviews synthesis before ADR generation proceeds

### 3. Generate ADR Sections

Generate each section grounded in evidence from Steps 1-2.

#### Section: Context

**What this section covers:** Why this design is needed — the problem, current state, and motivation.

**Grounding sources:** PRD problem statement + current codebase state

```markdown
## Context

{Problem statement from PRD — cite PRD section}

Current state of the codebase:
- {What exists today — cite file paths from codebase analysis}
- {What gap exists — grounded in PRD requirements}
- {Why change is needed now — from PRD motivation}
```

#### Section: Decision

**What this section covers:** The core architectural approach chosen.

**Grounding sources:** PRD requirements + codebase patterns

```markdown
## Decision

{One-paragraph summary of the architectural approach}

This decision addresses:
- {FR-XXX}: {How this decision satisfies the requirement}
- {FR-YYY}: {How this decision satisfies the requirement}

The approach follows the existing {pattern name} pattern found in `{file_path}`.
```

#### Section: Approach

**What this section covers:** Detailed implementation approach — patterns, data flow, component interactions.

**Grounding sources:** Codebase patterns with file paths

```markdown
## Approach

### Component Changes

{For each affected component:}
- **`path/to/file.py`**: {What changes and why — cite FR}
  - Current: {What it does now}
  - Proposed: {What it will do}

### Data Flow

{How data moves through the system after changes — reference actual module/class names}

### Patterns Used

{Existing codebase patterns being followed — cite where they're used today}
- Pattern: {name} — used in `{file_path}`, applied here for {reason}
```

#### Section: Impact Analysis

**What this section covers:** Files to modify, breaking changes, migrations needed.

**Grounding sources:** Codebase analysis — MUST reference real files

```markdown
## Impact Analysis

### Files to Modify
{List every file that needs changes — must be verified to exist}
- `path/to/file.py` — {what changes} [FR-XXX]

### Files to Create
{List new files needed — with rationale}
- `path/to/new_file.py` — {purpose} [FR-XXX]

### Breaking Changes
{Any backward-incompatible changes — or "None" if fully compatible}

### Migrations
{Database migrations, config changes, etc. — or "None"}

### Test Impact
{Which test files need updates — reference existing test patterns}
```

#### Section: Consequences

**What this section covers:** Positive and negative outcomes of the decision.

**Grounding sources:** PRD goals and codebase implications

```markdown
## Consequences

### Positive
- {Benefit aligned with PRD goal — cite FR/NFR}
- {Technical benefit from codebase perspective}

### Negative
- {Trade-off or limitation}
- {Technical debt introduced, if any}

### Risks
- {Implementation risk — with mitigation strategy}
```

### 4. Present-and-Flag Review

**Present the full design document first, then ask which sections need edits.**

#### 4.1: Present Full Design

Display the complete design document with all 5 sections (Context, Decision, Approach, Impact Analysis, Consequences) as a single block so the user can read the full picture.

#### 4.2: Flag Sections for Revision

Ask a single multiSelect question to identify which sections need changes:

```
AskUserQuestion([
  {
    question: "Which sections need edits? (Select none to keep all as-is)",
    header: "Review",
    multiSelect: true,
    options: [
      { label: "Context", description: "Problem statement and current state" },
      { label: "Decision", description: "Core architectural approach" },
      { label: "Approach", description: "Component changes, data flow, patterns" },
      { label: "Impact Analysis", description: "Files to modify/create, breaking changes" },
      { label: "Consequences", description: "Positive/negative outcomes and risks" }
    ]
  }
])
```

#### 4.3: Revise Flagged Sections Only

For each section the user flagged:
1. Ask the user what to change
2. Revise the section
3. Re-present the revised section for confirmation

Sections NOT flagged are kept as-is — do not re-present them.

#### 4.4: Final Confirmation

After revisions (or if no sections were flagged):

```
AskUserQuestion([
  {
    question: "Design document ready. How would you like to proceed?",
    header: "Save",
    options: [
      { label: "Save", description: "Save this design document" },
      { label: "Re-review", description: "Review the full document again" },
      { label: "Cancel", description: "Discard without saving" }
    ]
  }
])
```

- If **Save**: Proceed to Step 5
- If **Re-review**: Loop back to Step 4.1
- If **Cancel**: Discard and stop

### 4.5. Design Validation (FR-018, AC-009)

**REQUIRED:** Before saving, the design must provide concrete answers to the following four validation questions. Answers must NOT contain TBDs, placeholders, or deferred decisions (AC-009).

#### 4.5.1: Validation Questions

For each question, extract the answer from the design document sections (Context, Decision, Approach, Impact Analysis). If an answer cannot be found, the design is incomplete.

**Question 1: Runtime Model**
> How does the system execute at runtime after this change?

Answer must describe:
- Process/thread model for the new components
- How new components are started, managed, and stopped
- Resource lifecycle (connections, file handles, caches)

**Question 2: Integration Contracts**
> What are the exact API contracts between components?

Answer must describe:
- Function/method signatures for new interfaces
- Request/response shapes for new or modified APIs
- Data formats passed between components (types, not just names)

**Question 3: Enforcement Audit**
> How is each requirement enforced in code?

Answer must provide:
- For each FR cited in the Decision section: the specific code mechanism that enforces it
- For each NFR: the technical approach (e.g., "rate limiting via middleware X at path Y")
- No requirement should rely on "developer discipline" alone

**Question 4: End-to-End Scenario**
> Walk through one complete user journey end-to-end with the proposed changes.

Answer must describe:
- A concrete scenario (not abstract)
- Each step from user action to system response
- Which components are involved at each step (cite file paths)

#### 4.5.2: Validate Answers

Check each answer against these rules:

| Question | Validation Rule | Flag If |
|----------|----------------|---------|
| Runtime Model | Concrete process description | Contains "TBD", "to be determined", "will decide later" |
| Integration Contracts | Specific signatures/shapes | Uses vague terms like "appropriate format", "standard interface" |
| Enforcement Audit | Maps every FR/NFR to code | Any requirement has no enforcement mechanism |
| E2E Scenario | Concrete step-by-step | Uses abstract language like "the system handles it" |

If any question has an incomplete answer:

```
Design Validation: {N} incomplete answers found

- [INCOMPLETE] Runtime Model: {reason}
- [INCOMPLETE] Integration Contracts: {reason}

The design document must provide concrete answers to all 4 validation questions
before it can be saved (AC-009). Edit the flagged sections to provide specific answers.
```

Return to Step 4.2 (flag sections for revision) with the incomplete validation questions highlighted.

If all questions have concrete answers:

```
Design Validation: All 4 questions answered with concrete details.
```

Proceed to Step 5.

### 4.6. Challenge Gate (Post-Design)

**This gate is conditional on quality configuration. Skip entirely if not configured.**

#### 4.6.1: Check Quality Config

```
Read: .sdlc/config.yaml → look for quality.enabled and quality.challenge sections
```

**Skip this entire section if ANY of these are true:**
- `.sdlc/config.yaml` does not exist
- `quality.enabled` is `false` or absent
- `quality.challenge.enabled` is `false`
- `quality.challenge.gates.design` is `false`

If skipping:
```
Challenge gate: skipped (quality challenges not enabled for design)
```
Proceed to Step 5.

#### 4.6.2: Check PRD Challenge Status (AC-012)

Before challenging the design, verify the PRD challenge is resolved:

```
prd_status = mcp__asdlc__get_challenge_status(
    artifact_type="prd",
    artifact_id=prd_id
)
```

If `prd_status.challenge_status` is not `"accepted"` and not `"unchallenged"`, and the gate mode is `"hard"`:

```
BLOCKED: PRD {prd_id} has unresolved escalations from its challenge.
The design cannot proceed until the PRD challenge is resolved (AC-012).

PRD challenge status: {prd_status.challenge_status}
Unresolved escalations: {count}

Resolve the PRD challenge first, then re-run /sdlc:prd-architect.
```

**STOP HERE. Do not proceed to save.**

If PRD challenge is resolved or gate is "soft", continue.

#### 4.6.3: Initiate Design Challenge

```
challenge = mcp__asdlc__challenge_artifact(
    artifact_type="design",
    artifact_id=prd_id
)
```

#### 4.6.4: Run Challenger via Task Tool

Launch a challenger agent:

```
Task:
  description: "Challenge this design document as a critical reviewer"
  prompt: |
    You are a challenger reviewing a design document for architectural quality.

    {challenge.challenge_prompt}

    Focus your review on:
    - Design decisions that lack evidence from codebase analysis
    - Missing integration contracts between components
    - File paths that may not exist or are inaccurate
    - Patterns proposed that conflict with existing codebase patterns
    - Requirements cited in the design that are not actually in the PRD
    - Validation questions with incomplete or vague answers

    Return your objections in this format:
    ---CHALLENGE-OBJECTIONS---
    - category: evidence|contract|accuracy|consistency|completeness
      description: "..."
      severity: blocking|warning
      requirement_ref: "FR-xxx or DD-N if applicable"
    ---END-OBJECTIONS---
```

#### 4.6.5: Record and Resolve

Follow the same challenge round loop as the PRD challenge gate:

1. Record objections via `mcp__asdlc__record_challenge_round(artifact_type="design", artifact_id=prd_id, ...)`
2. Present objections to user
3. User addresses, accepts risk, or skips (soft gate only)
4. Re-challenge if needed, up to `quality.challenge.max_rounds`
5. Check status via `mcp__asdlc__get_challenge_status(artifact_type="design", artifact_id=prd_id)`

#### 4.6.6: Gate Enforcement

- If `quality.challenge.gate` is `"hard"` AND unresolved blocking objections remain:
  ```
  BLOCKED: Design challenge has unresolved blocking objections.
  The design cannot be saved until these are addressed.

  Unresolved:
  - {objection description}

  Edit the design and re-run the challenge.
  ```
  **STOP HERE. Do not proceed to Step 5.**

- If `quality.challenge.gate` is `"soft"` AND unresolved objections remain:
  ```
  WARNING: Design challenge has unresolved objections. Proceeding with warnings.
  Consider addressing these before splitting:
  - {objection description}
  ```
  Proceed to Step 5.

- If all objections resolved:
  ```
  Design challenge passed. All objections resolved.
  ```
  Proceed to Step 5.

### 5. Save Design Document

For a **new** design:
```
result = mcp__asdlc__create_design(prd_id="{prd_id}")
# Then write content to the returned file_path:
Write(file_path=result["file_path"], content="{assembled_markdown}")
```

If design already existed and user chose to overwrite, get the file path and edit directly:
```
design = mcp__asdlc__get_design(prd_id="{prd_id}")
Write(file_path=design["design"]["file_path"], content="{assembled_markdown}")
```

### 6. Display Summary

```
Design document saved for PRD {prd_id}

Summary:
- {N} sections included
- {M} files affected
- {K} new files to create

Next steps for user:
- View design: mcp__asdlc__get_design("{prd_id}")
- Split into tasks: /sdlc:prd-split "{prd_id}"
- Edit PRD: /sdlc:prd-update "{prd_id}"
```

## STOP HERE

**Do NOT proceed further.** The design document workflow is complete.

The user must explicitly run one of these commands to continue:
- `/sdlc:prd-split` — To create tasks from the PRD (will use this design as input)
- `/sdlc:prd-update` — To edit the PRD
- `/sdlc:prd-architect` — To regenerate the design

**Wait for user's next instruction.**

## MCP Tools Used

| Tool | Purpose |
|------|---------|
| `mcp__asdlc__get_context` | Load project context |
| `mcp__asdlc__get_prd` | Load PRD content |
| `mcp__asdlc__get_design` | Check for existing design |
| `mcp__asdlc__create_design` | Create design document (returns file_path) |
| `Write` / `Edit` | Write or edit design content directly |
| `mcp__asdlc__challenge_artifact` | Initiate design challenge (quality gate) |
| `mcp__asdlc__record_challenge_round` | Record challenger objections and responses |
| `mcp__asdlc__get_challenge_status` | Check challenge resolution status |

## Notes

- Design documents have a 1:1 relationship with PRDs
- Every design decision must cite either a PRD requirement or a codebase file
- The design document is used by `/sdlc:prd-split` to create better task breakdowns
- Design documents are stored as markdown in `~/.a-sdlc/content/{project}/designs/`
