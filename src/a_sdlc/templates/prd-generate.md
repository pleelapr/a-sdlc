# /sdlc:prd-generate "<description>"

## Purpose

Create a Product Requirements Document interactively from a brief description. Uses clarifying questions to build comprehensive requirements.

## Arguments

- **description**: Brief statement of the proposed change or feature (e.g., "Add OAuth authentication", "Migrate to PostgreSQL")

## CRITICAL: Scope Boundaries

**This skill ONLY creates PRD documents. It does NOT implement features.**

- **NEVER** proceed to task creation or splitting automatically
- **NEVER** write source code or make code changes
- **NEVER** use TaskCreate, TodoWrite, or Edit tools
- **NEVER** call `mcp__asdlc__create_task()` or split PRD
- **ALWAYS** stop after PRD creation and wait for user's next command

**RIGHT**: Create PRD → Display summary → STOP
**WRONG**: Create PRD → Split into tasks → Start implementing

## CRITICAL: Anti-Fluff Rules

**Every line in the PRD must trace to a user answer. Zero AI-inferred content.**

- **MUST NOT** add features, parameters, NFRs, or scope items that were not explicitly discussed and confirmed by the user via AskUserQuestion
- **MUST NOT** hallucinate acceptance criteria — every AC must trace to a specific user answer from a specific round
- **MUST NOT** expand scope beyond what the user confirmed in clarifying questions
- **MUST NOT** use vague language ("improve", "better", "ensure", "handle properly") without measurable targets provided by the user
- **MUST NOT** add User Stories for user types the user did not mention
- **MUST NOT** infer "obvious" requirements — if it wasn't discussed, it doesn't belong in the PRD
- **MUST** map every Functional Requirement to a specific user answer (cite the round and question)
- **MUST** map every Non-Functional Requirement to a specific user answer
- **MUST** ask the user if information is missing — never fill in the blanks yourself

**Traceability Rule:** When generating PRD content in Step 3, mentally tag each requirement with `[Round N, Q M]` to verify it traces to a real answer. If you cannot tag it, do not include it.

**If in doubt, ASK — do not assume.**

## Execution Steps

### 1. Parse User Description

- Extract key entities and change type
- Identify potential affected areas
- Determine scope of the change

### 1.5. Load Codebase Context (if available)

Before asking clarifying questions, check for existing codebase artifacts to make questions codebase-aware:

```
context = mcp__asdlc__get_context()
```

If `context.artifacts.scan_status` is `"complete"` or `"partial"`:

```
Read: .sdlc/artifacts/codebase-summary.md    → Tech stack, conventions
Read: .sdlc/artifacts/architecture.md         → Components and patterns
```

Use this context to:
- Reference real component names in questions (e.g., "This will affect `AuthService` — what changes to the login flow?")
- Understand existing patterns before asking about implementation approach
- Identify affected areas more precisely

Also read lesson-learn files if available:
```
Read: .sdlc/lesson-learn.md        → Project-specific lessons
Read: ~/.a-sdlc/lesson-learn.md    → Global lessons (if exists)
```

Use lessons to inform PRD quality — e.g., if past lessons mention "missing test tasks", ensure the PRD explicitly calls out testing requirements.

If `context.artifacts.scan_status` is `"not_scanned"`:
```
⚠️ No codebase artifacts found. Run `/sdlc:scan` first for codebase-aware PRD generation.
   Continuing without codebase context...
```

### Persona Check (Section A from _round-table-blocks.md)

After loading context, check for persona agents:
1. Check `~/.claude/agents/` for files matching `sdlc-*.md` pattern
2. If `--solo` specified OR no personas found: round_table_enabled = false, skip all persona sections
3. Otherwise: round_table_enabled = true

### Domain Detection (Section B from _round-table-blocks.md)

If round_table_enabled = true:
1. Analyze the user's description for domain signals
2. Assemble persona panel — Product Manager always included for PRD generation
3. Display panel to user

### 2. Ask Clarifying Questions (Interactive with AskUserQuestion)

**IMPORTANT**: Use the `AskUserQuestion` tool for ALL clarifying questions. This gives users selectable multiple-choice options instead of free-form text. Users can always pick "Other" to provide custom answers.

Ask questions in **3 base rounds + up to 3 adaptive follow-up rounds** (max 6 rounds total, max 3 questions per round). Adapt options based on the description, codebase context, and prior answers.

**Round structure:**
- **Rounds 1-3**: Base rounds (always run) — Problem & Change Type, Scope & Requirements, Acceptance & Boundaries
- **Rounds 4-6**: Adaptive follow-ups (only if scope is still ambiguous after Round 3)
- **Each round**: Max 3 questions via a single AskUserQuestion call
- **Early stop**: If scope is clear after any round, proceed to Step 3 immediately

#### Round 1: Problem & Change Type

Use `AskUserQuestion` with 2-3 questions:

```
Question 1: "What type of change is this?"
Header: "Change type"
Options (adapt to description):
- "New feature" — Adding entirely new functionality
- "Enhancement" — Improving existing functionality
- "Refactor" — Restructuring without behavior change
- "Bug fix" — Correcting broken behavior

Question 2: "What's the primary motivation?"
Header: "Motivation"
Options (adapt to description):
- "User request" — Users/customers have asked for this
- "Cost reduction" — Reduce operational or infrastructure costs
- "Tech debt" — Address accumulated technical debt
- "Performance" — Improve speed, latency, or resource usage

Question 3: "How urgent is this change?"
Header: "Priority"
Options:
- "Critical" — Blocking other work or causing incidents
- "High" — Needed this sprint/cycle
- "Medium" — Important but not time-sensitive
- "Low" — Nice to have, can wait
```

#### Round-Table: Requirements Enrichment (Section C from _round-table-blocks.md)

If round_table_enabled = true, run before Round 2:

Execute round-table discussion following `_round-table-blocks.md` Section C:
1. Build context packages: each persona receives the user description + Round 1 answers
2. Detect mode (Agent Teams vs Task tool)
3. Dispatch personas to identify missing requirements from their domains:
   - PM validates requirement completeness and user story coverage
   - Domain leads identify technical requirements from their perspective
   - Security identifies security-related requirements that may be missing
   - QA identifies testability gaps
4. Synthesize — present gaps/additions for user to confirm before Round 2

#### Round 2: Scope & Requirements

Based on Round 1 answers, ask 2-4 more questions:

```
Question 1: "What's the expected scope of changes?"
Header: "Scope"
Options (adapt based on codebase artifacts):
- "Single component" — Isolated to one module/service
- "Multiple components" — Touches 2-3 related modules
- "Cross-cutting" — Affects many parts of the system
- "Infrastructure" — Config, CI/CD, deployment changes

Question 2: "Is backward compatibility required?"
Header: "Compat"
Options:
- "Full compat" — Existing APIs/behavior must not break
- "Migration path" — Breaking changes OK with migration plan
- "No constraint" — Clean break is acceptable

Question 3 (if applicable): "What quality attributes matter most?"
Header: "Quality"
multiSelect: true
Options (pick relevant ones):
- "Performance" — Latency, throughput targets
- "Security" — Auth, data protection, compliance
- "Reliability" — Uptime, error handling, recovery
- "Scalability" — Handle growth in users/data
```

#### Round 3: Acceptance & Boundaries

Final round of 2-3 questions:

```
Question 1: "How should we validate success?"
Header: "Validation"
multiSelect: true
Options:
- "Unit tests" — Function-level test coverage
- "Integration tests" — Cross-component verification
- "Performance benchmarks" — Measurable perf targets
- "Manual QA" — Human verification of workflows

Question 2: "What should be explicitly OUT of scope?"
Header: "Exclusions"
multiSelect: true
Options (adapt based on description — suggest likely scope-creep areas):
- "{Related feature A}" — Description of why excluded
- "{Related feature B}" — Description of why excluded
- "{Optimization area}" — Description of why excluded
- "Nothing excluded" — Everything related is in scope
```

#### Adapting Questions to Context

- If codebase artifacts exist, reference **real component names** in options (e.g., "AuthService" instead of "Single component")
- If the description implies a specific domain (e.g., "authentication"), tailor options to that domain
- Skip questions that are already answered by the description (e.g., don't ask change type if description says "Add new...")
- Use `multiSelect: true` when multiple answers are valid (quality attributes, validation methods, exclusions)
- **If user gives vague answers, do NOT proceed** — ask a follow-up round to get specifics
- **Each round should narrow scope, not expand it** — never introduce new topics the user didn't mention

#### Adaptive Follow-Up Rounds (Rounds 4-6)

After Round 3, evaluate whether scope is sufficiently clear to generate a quality PRD.

**Ambiguity triggers** — run an additional round if ANY of these are true:
- User selected "Other" with vague or incomplete text in any round
- Scope is "Cross-cutting" but affected components are not specifically named
- Multiple components were selected but boundaries between them are unclear
- Acceptance criteria lack measurable targets (no numbers, thresholds, or specific behaviors)
- The user's answers conflict or leave gaps (e.g., said "high priority" but "no timeline")
- Key questions were skipped because they seemed obvious — but the answers would change the PRD

**Adaptive round content:**
Each follow-up round targets the specific ambiguity found. Examples:

```
Round 4 example (if acceptance criteria lack measurable targets):
  Question: "You mentioned [quality attribute] matters. What's the specific target?"
  Header: "Target"
  Options:
  - "{Specific measurable option A}" — e.g., "Response time < 200ms"
  - "{Specific measurable option B}" — e.g., "99.9% uptime"
  - "No specific target" — Directional improvement only
```

```
Round 5 example (if component boundaries are unclear):
  Question: "You selected [Component A] and [Component B]. What's the boundary?"
  Header: "Boundary"
  Options:
  - "{Component A} owns X, {Component B} owns Y"
  - "Shared responsibility" — Both components involved equally
  - "Not sure yet" — Needs investigation
```

**Stop conditions** — stop asking and proceed to Step 3 if:
- All ambiguity triggers are resolved
- User explicitly says scope is clear (via "Other" response)
- Maximum 6 rounds reached

#### Round-Table: Pre-Generation Review (Section C from _round-table-blocks.md)

If round_table_enabled = true, run after Round 3 and before Step 3:

Execute round-table discussion following `_round-table-blocks.md` Section C:
1. Build context packages: each persona receives all rounds of Q&A
2. Detect mode (Agent Teams vs Task tool)
3. Dispatch personas for final validation before PRD is generated:
   - Each persona validates that their domain's requirements are adequately captured
   - PM confirms scope boundaries are clear
   - Security confirms security requirements are explicit, not implied
   - QA confirms acceptance criteria are measurable
4. Synthesize — surface any final gaps for user confirmation before PRD generation

### 3. Generate PRD Content

**CRITICAL: Apply Anti-Fluff Rules during generation.** Every item below must trace to a specific user answer. Do NOT add content that wasn't discussed.

Build markdown content with structure:

```markdown
# {Title from description}

**Status**: draft
**Created**: {timestamp}

## Overview
{Synthesized ONLY from description and confirmed answers — no embellishment}

## Problem Statement
{From problem context questions — state only what the user described as the problem}

## Goals
{ONLY goals the user confirmed — each must have a measurable target or timeline if the user provided one}

## Affected Components
{ONLY components the user selected or confirmed in scope questions}
- Component A: {impact as described by user}
- Component B: {impact as described by user}

## Functional Requirements
{ONLY requirements derived from user answers — cite the source}
- FR-001: {requirement} [from Round N, Question M]
- FR-002: {requirement} [from Round N, Question M]

## Non-Functional Requirements
{ONLY if user discussed quality attributes or constraints}
- NFR-001: {requirement} [from Round N, Question M]

## User Stories
{ONLY for user types the user mentioned — omit this section if no user types were discussed}
- As a {user type mentioned by user}, I want {capability from answers}, so that {benefit from answers}

## Acceptance Criteria
{ONLY testable criteria derived from validation answers}
- AC-001: {criterion} [from Round N, Question M]
- AC-002: {criterion} [from Round N, Question M]

## Out of Scope
{ONLY exclusions the user confirmed in boundary questions}

## Open Questions
{Unresolved items from interactive session — things the user said "not sure" about}
```

**Post-generation check:** Before presenting to user, verify every FR, NFR, and AC traces to a user answer. Remove any that don't.

### 3.5. Anti-Fluff Validation

Before presenting the PRD for section-by-section review, validate the generated content against quality rules.

#### Validation Rules

Check each section against these rules:

| Section | Rule | Flag If |
|---------|------|---------|
| Goals | Measurability | Any goal lacks a measurable target or timeline that the user provided |
| Functional Requirements | Traceability | Any FR cannot be mapped to a specific user answer from Rounds 1-6 |
| Non-Functional Requirements | Traceability | Any NFR was not discussed in clarifying questions |
| Acceptance Criteria | Testability | Any AC uses vague language or cannot be verified with a concrete test |
| User Stories | Relevance | Any user story describes a user type not mentioned by the user |
| Out of Scope | Specificity | Fewer than 2 specific exclusions, or only generic phrases like "future work" |
| Affected Components | Evidence | Any component listed that wasn't identified during questions |

#### Vague Language Detection

Flag any of these words/phrases when they appear in requirements or criteria WITHOUT measurable targets:
- "improve", "better", "enhance", "optimize"
- "ensure", "handle properly", "manage effectively"
- "as needed", "where appropriate", "when necessary"
- "robust", "scalable", "efficient", "reliable" (without specific thresholds)
- "etc.", "and more", "various", "several"

#### Traceability Check

For each FR and NFR, verify it has a `[from Round N, Question M]` tag. If a requirement cannot be traced to a user answer, flag it as "potentially AI-inferred — consider removing."

#### Present Results

If flags are found:

```
⚠️ Anti-Fluff Validation — {N} potential issues found

**Goals:**
- [FLAG] Goal 2: "Improve developer experience" — lacks measurable target
  → Ask user for a specific metric, or remove this goal

**Functional Requirements:**
- [FLAG] FR-003: "Handle edge cases gracefully" — no user answer traces to this
  → This appears to be AI-inferred. Remove unless user confirms it.

**Acceptance Criteria:**
- [FLAG] AC-002: "System performs well under load" — not testable as stated
  → Needs specific threshold from user (e.g., "handles 100 req/s")

These flags will be highlighted during the section-by-section review.
Flagged items are candidates for removal or revision.
```

If no flags are found:

```
✅ Anti-Fluff Validation Passed — all content traces to user answers.
```

Proceed to Step 4 (section-by-section review) regardless of flag count. Flags are informational — the user decides what to keep or remove during review.

#### Flag Integration with Section Review

During Step 4 (section-by-section review), if a section contains flagged items:
- Display the flags alongside the section content
- Add a note: "⚠️ This section has {N} flagged items (see validation results above)"
- This guides the user to focus attention on potentially problematic sections

### 4. Section-by-Section Review

**Do NOT present the entire PRD for bulk approval.** Instead, review each section individually so the user can confirm, edit, or remove each one.

#### 4.1: Announce Review

```
📝 PRD Generated — Starting Section-by-Section Review

I'll present each section of the PRD individually. For each section, you can:
- **Keep** it as-is
- **Edit** it (tell me what to change)
- **Remove** it entirely
```

#### 4.2: Review Each Section

For each section in this order — Overview, Problem Statement, Goals, Affected Components, Functional Requirements, Non-Functional Requirements, User Stories, Acceptance Criteria, Out of Scope, Open Questions:

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
      { label: "Remove", description: "Remove this section — not needed in this PRD" }
    ]
  }
])
```

- If **Keep**: Include as-is, move to next section
- If **Edit**: Ask the user what to change. Revise the section. Re-present the SAME section for approval (loop until user selects Keep or Remove)
- If **Remove**: Exclude from final PRD, move to next section

#### 4.3: Assemble Final PRD

After all sections are reviewed, assemble the final PRD from kept/edited sections only.

Display a summary:

```
📋 PRD Assembly Summary:

  ✅ Overview — kept
  ✅ Problem Statement — kept
  ✏️ Goals — edited
  ✅ Functional Requirements — kept
  ❌ User Stories — removed
  ✅ Acceptance Criteria — kept
  ✅ Out of Scope — kept
```

#### 4.4: Final Confirmation

```
AskUserQuestion([
  {
    question: "Final PRD assembled. How would you like to proceed?",
    header: "Save PRD",
    options: [
      { label: "Save", description: "Create this PRD in a-sdlc as draft" },
      { label: "Re-review", description: "Go through the sections again from the start" },
      { label: "Cancel", description: "Discard without saving" }
    ]
  }
])
```

- If **Save**: Proceed to Step 5
- If **Re-review**: Loop back to Step 4.2
- If **Cancel**: Discard and stop

**Wait for explicit user approval before saving.**

### 5. Save PRD

```
result = mcp__asdlc__create_prd(title="<title>")
```

This creates a DB record and skeleton file. Then write the full content:

```
Write(file_path=result["file_path"], content="<markdown_content>")
```

Returns:
```json
{
  "status": "created",
  "message": "PRD created: PROJ-P0001",
  "prd": {
    "id": "PROJ-P0001",
    "title": "User Authentication System",
    "status": "draft",
    "sprint_id": null,
    "created_at": "2025-01-26T12:00:00Z"
  },
  "file_path": "~/.a-sdlc/content/proj/prds/PROJ-P0001.md"
}
```

### 6. Display Summary

```
✅ PRD created: feature-auth

📊 Summary:
- 4 functional requirements
- 3 non-functional requirements
- 3 acceptance criteria
- 2 affected components

🔗 Next steps for user:
- View PRD: /sdlc:prd-list
- Mark ready: /sdlc:prd-update "feature-auth" --status ready
- Design architecture: /sdlc:prd-architect "feature-auth"  ← recommended before splitting
- Split into tasks: /sdlc:prd-split "feature-auth"
```

## ⛔ STOP HERE

**Do NOT proceed further.** The PRD generation workflow is complete.

The user must explicitly run one of these commands to continue:
- `/sdlc:prd-update` - To edit the PRD
- `/sdlc:prd-architect` - To design architecture before splitting (recommended next step)
- `/sdlc:prd-split` - To create tasks from the PRD (run architect first)
- `/sdlc:investigate` - To analyze codebase before splitting

**Wait for user's next instruction.**

## Example Session

**Input:**
```
/sdlc:prd-generate "Change default model from GPT-5 to GPT-4"
```

**Claude's Flow:**

**Step 1** — Parse description + load codebase context

**Step 2** — Round 1 questions via `AskUserQuestion`:
```
AskUserQuestion([
  {
    question: "What type of change is this?",
    header: "Change type",
    options: [
      { label: "Enhancement", description: "Improving existing model configuration" },
      { label: "Cost optimization", description: "Reducing operational costs" },
      { label: "Refactor", description: "Restructuring without behavior change" }
    ]
  },
  {
    question: "What's the primary motivation?",
    header: "Motivation",
    options: [
      { label: "Cost reduction", description: "GPT-5 pricing is too high for current usage" },
      { label: "Performance", description: "GPT-4 latency is better for our use case" },
      { label: "Simplification", description: "Reduce model dependency complexity" }
    ]
  }
])
```
User selects: **Cost optimization**, **Cost reduction**

**Step 3** — Round 2 questions (adapted to answers):
```
AskUserQuestion([
  {
    question: "Which components will need changes?",
    header: "Scope",
    multiSelect: true,
    options: [
      { label: "inference-service", description: "Model invocation and routing" },
      { label: "api-gateway", description: "Request handling and model parameter" },
      { label: "model-config", description: "Default model settings" },
      { label: "monitoring", description: "Cost tracking dashboards" }
    ]
  },
  {
    question: "Is backward compatibility required?",
    header: "Compat",
    options: [
      { label: "Full compat", description: "API still accepts model param for GPT-5 override" },
      { label: "Migration path", description: "Deprecate GPT-5 with transition period" },
      { label: "Clean break", description: "Switch entirely, no override" }
    ]
  }
])
```
User selects: **inference-service + api-gateway + model-config**, **Full compat**

**Step 4** — Round 3 questions:
```
AskUserQuestion([
  {
    question: "How should we validate success?",
    header: "Validation",
    multiSelect: true,
    options: [
      { label: "Cost metrics", description: "65%+ reduction in model API costs" },
      { label: "Latency benchmarks", description: "Max 15% slower than GPT-5 baseline" },
      { label: "Integration tests", description: "All existing API tests pass" },
      { label: "Manual QA", description: "Verify output quality on sample prompts" }
    ]
  },
  {
    question: "What should be explicitly OUT of scope?",
    header: "Exclusions",
    multiSelect: true,
    options: [
      { label: "Prompt optimization", description: "No rewriting prompts for GPT-4" },
      { label: "Model fine-tuning", description: "No custom GPT-4 fine-tuning" },
      { label: "Multi-model routing", description: "No dynamic model selection logic" }
    ]
  }
])
```
User selects: **Cost metrics + Latency benchmarks + Integration tests**, **Prompt optimization + Model fine-tuning**

**Step 5** — Generate PRD content from structured answers

**Step 6** — Section-by-section review:
- Overview: Keep ✅
- Problem Statement: Keep ✅
- Goals: Edit ✏️ (user removes a vague goal, adds measurable target)
- Functional Requirements: Keep ✅
- Non-Functional Requirements: Keep ✅
- User Stories: Remove ❌ (not relevant for this change)
- Acceptance Criteria: Keep ✅
- Out of Scope: Keep ✅

**Step 7** — After user approves final assembly:
```
✅ PRD created: model-downgrade-gpt4

📊 Summary:
- 4 functional requirements
- 4 non-functional requirements
- 3 acceptance criteria
- 3 affected components

🔗 Next steps for user:
- View: /sdlc:prd-list
- Design architecture: /sdlc:prd-architect "model-downgrade-gpt4"  ← recommended before splitting
- Split: /sdlc:prd-split "model-downgrade-gpt4"
```

## MCP Tools Used

| Tool | Purpose |
|------|---------|
| `mcp__asdlc__create_prd` | Save new PRD to database |
| `mcp__asdlc__list_prds` | Check for duplicate IDs |

## PRD Status Flow

```
draft (initial) → ready (approved) → split (tasks created) → completed (done)
```

New PRDs are created with status `draft`. Use `/sdlc:prd-update` to change status.

## Notes

- PRD ID (slug) is auto-generated from title
- All PRDs start in `draft` status
- Questions adapt based on the type of change
- Generated PRD can be edited with `/sdlc:prd-update`
- PRDs can optionally be assigned to a sprint after creation
- **PRD Creation Only:** This skill creates PRD documents ONLY.
  It does NOT split into tasks or implement features.
  Use `/sdlc:prd-architect` to design architecture, then `/sdlc:prd-split` to create tasks.
