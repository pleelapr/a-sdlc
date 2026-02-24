# /sdlc:prd-architect "<prd_id>"

## Purpose

Generate an ADR-style (Architecture Decision Record) design document for an existing PRD by analyzing the actual codebase. Produces a codebase-grounded architecture document with section-by-section user review.

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

### 2. Codebase Analysis

**This step MUST read actual code. Do NOT skip or approximate.**

#### 2.1: Read Artifacts

If `.sdlc/artifacts/` exists:
```
Read: .sdlc/artifacts/architecture.md
Read: .sdlc/artifacts/directory-structure.md
Read: .sdlc/artifacts/codebase-summary.md
Read: .sdlc/artifacts/data-model.md
Read: .sdlc/artifacts/key-workflows.md
```

Also read lesson-learn files if available:
```
Read: .sdlc/lesson-learn.md
Read: ~/.a-sdlc/lesson-learn.md
```

If artifacts don't exist:
```
Warn: No codebase artifacts found. Run `/sdlc:scan` first for best results.
      Proceeding with direct codebase analysis...
```

#### 2.2: Analyze Affected Components

For each functional requirement in the PRD:

1. Identify which existing components are affected
2. Read the actual source files to understand current implementation
3. Find 2-3 similar implementations in the codebase that this design should follow
4. Document existing patterns with file paths and line references

Record findings as structured evidence:
```
Evidence Log:
- FR-001 → affects src/module/file.py (class X, method Y)
- FR-002 → new component needed, follows pattern in src/existing/similar.py
- Existing pattern: adapter pattern used in src/storage/__init__.py
```

#### 2.3: Identify Constraints

From codebase analysis, identify:
- Database schema implications (migrations needed?)
- API contract changes (backward compatibility?)
- Dependency additions (new packages?)
- Test infrastructure (existing test patterns?)

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

#### Section: Alternatives Considered

**What this section covers:** Other approaches evaluated and why they were rejected.

**Grounding sources:** Codebase constraints and PRD requirements

```markdown
## Alternatives Considered

### Alternative 1: {Name}
- **Approach:** {Brief description}
- **Rejected because:** {Specific reason grounded in codebase or PRD constraints}

### Alternative 2: {Name}
- **Approach:** {Brief description}
- **Rejected because:** {Specific reason grounded in codebase or PRD constraints}
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

### 4. Section-by-Section Review

**Do NOT present the entire design for bulk approval.** Review each section individually.

#### 4.1: Announce Review

```
Design Document Generated — Starting Section-by-Section Review

I'll present each section individually. For each section, you can:
- **Keep** it as-is
- **Edit** it (tell me what to change)
- **Remove** it entirely
```

#### 4.2: Review Each Section

For each section in this order — Context, Decision, Approach, Impact Analysis, Alternatives Considered, Consequences:

1. Display the section content
2. Ask via AskUserQuestion:

```
AskUserQuestion([
  {
    question: "Review the '{section_name}' section above:",
    header: "{section}",
    options: [
      { label: "Keep", description: "This section is accurate and complete" },
      { label: "Edit", description: "I want to change something in this section" },
      { label: "Remove", description: "Remove this section from the design doc" }
    ]
  }
])
```

- If **Keep**: Include as-is, move to next section
- If **Edit**: Ask the user what to change. Revise the section. Re-present the SAME section for approval (loop until user selects Keep or Remove)
- If **Remove**: Exclude from final design doc, move to next section

#### 4.3: Assemble Final Design Document

After all sections are reviewed, assemble the final document from kept/edited sections.

Display a summary:

```
Design Document Assembly Summary:

  Keep  Context
  Keep  Decision
  Edit  Approach — revised per feedback
  Keep  Impact Analysis
  Remove  Alternatives Considered
  Keep  Consequences
```

#### 4.4: Final Confirmation

```
AskUserQuestion([
  {
    question: "Final design document assembled. How would you like to proceed?",
    header: "Save",
    options: [
      { label: "Save", description: "Save this design document" },
      { label: "Re-review", description: "Go through the sections again" },
      { label: "Cancel", description: "Discard without saving" }
    ]
  }
])
```

- If **Save**: Proceed to Step 5
- If **Re-review**: Loop back to Step 4.2
- If **Cancel**: Discard and stop

### 5. Save Design Document

```
mcp__asdlc__create_design(
    prd_id="{prd_id}",
    content="{assembled_markdown}"
)
```

If design already existed and user chose to overwrite:
```
mcp__asdlc__update_design(
    prd_id="{prd_id}",
    content="{assembled_markdown}"
)
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
| `mcp__asdlc__create_design` | Save new design document |
| `mcp__asdlc__update_design` | Update existing design document |

## Notes

- Design documents have a 1:1 relationship with PRDs
- Every design decision must cite either a PRD requirement or a codebase file
- The design document is used by `/sdlc:prd-split` to create better task breakdowns
- Design documents are stored as markdown in `~/.a-sdlc/content/{project}/designs/`
