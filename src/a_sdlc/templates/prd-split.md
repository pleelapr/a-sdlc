# /sdlc:prd-split

## Purpose

Break down a Product Requirements Document (PRD) into actionable development tasks using a **multi-agent orchestration approach**. This skill coordinates specialized agents for investigation, design, content generation, and persistence to produce high-quality, implementable tasks.

---

## CRITICAL: Task System Distinction

This skill uses two different "task" concepts - do not confuse them:

| System | Purpose | Tools | Persistence |
|--------|---------|-------|-------------|
| **Claude Code Task tool** | Agent orchestration (launching Explore/Plan agents) | `Task` tool | Session only |
| **a-sdlc tasks** | Project work items linked to PRDs/Sprints | `mcp__asdlc__*` tools | Database + markdown files |

**RULES:**
- Use Claude Code's `Task` tool ONLY for launching agents (Explore, Plan)
- Use `mcp__asdlc__split_prd()` to create a-sdlc tasks
- **NEVER use** `TodoWrite`, `TaskCreate`, or `TaskUpdate` for a-sdlc tasks
- **NEVER use** `TaskList` or `TaskGet` for a-sdlc tasks

**Example of WRONG approach:**
```
TodoWrite: ["Create auth task", "Create login task"]  # WRONG!
TaskCreate: title="Implement login"                    # WRONG!
```

**Example of CORRECT approach:**
```
mcp__asdlc__split_prd(prd_id="PROJ-P0001", task_specs=[...])  # CORRECT!
```

---

## CRITICAL: Scope Boundaries

**This skill ONLY creates task documentation. It does NOT implement tasks.**

- **NEVER** proceed to task implementation automatically
- **NEVER** write source code or make code changes
- **NEVER** use Edit, Write, or Bash tools to modify project files
- **NEVER** call `/sdlc:task-start` or begin task execution
- **ALWAYS** stop after task creation and wait for user's next command

**RIGHT**: Generate tasks → Create task files → Call split_prd() → Display results → STOP
**WRONG**: Generate tasks → Start implementing first task → Write code

---

## CRITICAL: Anti-Fluff Rules

**Every task must trace to a specific requirement in the PRD. Zero AI-invented scope.**

- **MUST NOT** create tasks for features, components, or requirements not in the PRD
- **MUST NOT** add implementation steps that go beyond what the PRD specifies
- **MUST NOT** pad task content with unnecessary steps, boilerplate, or "nice-to-have" items
- **MUST NOT** add acceptance criteria the PRD doesn't require
- **MUST NOT** invent NFRs, error handling patterns, or testing approaches not specified in the PRD
- **MUST NOT** add tasks for "documentation", "monitoring", "observability", or "cleanup" unless the PRD explicitly requires them
- **MUST** map every task to a specific FR, NFR, or AC from the PRD
- **MUST** keep task scope tight — if the PRD says "add a button", the task is about adding a button, not refactoring the entire UI
- **MUST** ask the user if a task seems necessary but isn't covered by the PRD — never silently add it

**Traceability Rule:** Each task's "Key Requirements" section must cite specific PRD requirement IDs (e.g., FR-001, AC-002). If a task cannot cite a PRD requirement, it should not exist.

**If the PRD is missing something, flag it — do not silently compensate by adding extra tasks.**

---

## Usage

```
/sdlc:prd-split "<prd_id>" [options]
```

**Arguments:**
- `prd_id` - ID of PRD to split (e.g., "PROJ-P0001")

**Options:**
- `--granularity <level>` - Task detail: coarse, medium, fine (default: medium)

---

## Multi-Agent Architecture

This skill orchestrates multiple specialized agents via Claude Code's Task tool:

```
/sdlc:prd-split <prd_id>
    │
    ├── Phase 1: Investigation Agent (Explore)
    │   └── Analyze codebase patterns, find similar implementations
    │
    ├── Phase 2: Task Design Agent (Plan)
    │   └── Design task breakdown with dependencies
    │
    ├── Phase 3: Content Generation (Direct)
    │   └── Generate full task markdown for each task
    │
    └── Phase 4: Persistence
        └── Write files + call split_prd() MCP tool
```

---

## Execution Flow

### Step 1: Initialize Context

Get project context and PRD content:

```
mcp__asdlc__get_context()  →  shortname, total_tasks
mcp__asdlc__get_prd(prd_id)  →  PRD content
```

Store results:
- `shortname` - For calculating task IDs
- `total_tasks` - For ID sequence
- `prd_content` - For analysis

---

### Step 1.5: Design Document Gate

**HARD GATE:** A design document is required before splitting a PRD into tasks.

Check for an existing design document:

```
design = mcp__asdlc__get_design(prd_id)
```

**If design NOT found** (`design.status == "not_found"`):

```
BLOCKED: No design document found for PRD {prd_id}.

A design document is required before splitting a PRD into tasks.
The design doc ensures tasks are grounded in architectural decisions.

Run this command first:
  /sdlc:prd-architect "{prd_id}"

Then re-run:
  /sdlc:prd-split "{prd_id}"
```

**STOP HERE. Do not proceed to investigation or task creation.**

**If design found** (`design.status == "ok"`):

Store design content for use in Phase 1 and Phase 2:
- `design_content` - Full design document markdown
- `design_decisions` - Extract key decisions from the Decision and Approach sections

Display confirmation:
```
Design document found for PRD {prd_id}
Design decisions will be used to guide task breakdown.
```

Proceed to Step 1.5b.

---

### Step 1.5b: Extract PRD Requirements

Parse the PRD content and extract all identifiable requirements into a structured `requirement_list`. This list is used downstream by the Plan agent (Step 3), the traceability matrix (Step 3.5), and the coverage checker (Step 3.6).

**1.5b.1: Scan PRD for Requirement IDs**

Scan the PRD content for requirement identifiers matching these patterns:
- `FR-xxx` — Functional Requirements
- `NFR-xxx` — Non-Functional Requirements
- `AC-xxx` — Acceptance Criteria

For each match, extract:
- **ID**: The requirement identifier (e.g., `FR-001`)
- **Type**: `Functional`, `Non-Functional`, or `Acceptance Criteria`
- **Description**: The text following the ID on the same line

**1.5b.2: Build requirement_list**

```
requirement_list = [
    { "id": "FR-001", "type": "Functional", "description": "..." },
    { "id": "FR-002", "type": "Functional", "description": "..." },
    { "id": "NFR-001", "type": "Non-Functional", "description": "..." },
    { "id": "AC-001", "type": "Acceptance Criteria", "description": "..." },
    ...
]
```

**1.5b.3: Validate Extraction**

If `requirement_list` is empty (no FR-xxx, NFR-xxx, or AC-xxx found in the PRD):

```
⚠️ WARNING: No structured requirements found in PRD {prd_id}.
The PRD does not contain identifiable requirement IDs (FR-xxx, NFR-xxx, AC-xxx).
Traceability coverage will be limited.

Recommendation: Update the PRD to include structured requirement IDs,
then re-run /sdlc:prd-split.

Proceeding with unstructured analysis...
```

If requirements found, display confirmation:
```
Extracted {N} requirements from PRD {prd_id}:
  - {count_FR} Functional Requirements (FR-xxx)
  - {count_NFR} Non-Functional Requirements (NFR-xxx)
  - {count_AC} Acceptance Criteria (AC-xxx)
```

**Store Output As:** `requirement_list`

Proceed to Step 1.5c.

---

### Step 1.5c: Extract Design Decisions

Parse the design document and extract all key design decisions into a structured `design_decisions` list. This list is used downstream by the Plan agent (Step 3), the traceability matrix (Step 3.5), and the coverage checker (Step 3.6).

**1.5c.1: Scan Design Document for Decisions**

Scan the `design_content` for design decisions. Look for:
- Explicitly numbered decisions (e.g., `DD-1`, `DD-2`, or `Decision 1:`)
- Key decisions in the "Decision" or "Approach" sections
- Architecture choices with clear rationale

For each decision, extract:
- **ID**: Assign `DD-{N}` identifiers (sequentially numbered)
- **Description**: A concise summary of the decision
- **Rationale**: The reasoning behind the decision (if stated)

**1.5c.2: Build design_decisions**

```
design_decisions = [
    { "id": "DD-1", "description": "...", "rationale": "..." },
    { "id": "DD-2", "description": "...", "rationale": "..." },
    ...
]
```

**1.5c.3: Validate Extraction**

If `design_decisions` is empty:

```
⚠️ WARNING: No design decisions could be extracted from the design document.
The design document may lack explicit decision sections.
Design traceability will be limited.

Proceeding with requirement traceability only...
```

If decisions found, display confirmation:
```
Extracted {N} design decisions from design document for PRD {prd_id}.
```

**Store Output As:** `design_decisions`

Proceed to Step 1.5d.

---

### Step 1.5d: Persona Check

After loading context, check for persona agents:

1. Check `~/.claude/agents/` for files matching `sdlc-*.md` pattern
2. Determine round-table eligibility:
   - If `--solo` or `--no-roundtable` appears in the user's command: **round_table_enabled = false**
   - If no `sdlc-*.md` files found: **round_table_enabled = false**
   - Otherwise: **round_table_enabled = true**
3. If round_table_enabled = false, skip ALL persona-specific sections below. The template operates in single-agent mode (existing behavior preserved).

Reference: `_round-table-blocks.md` Section A

---

### Step 1.5e: Domain Detection + Panel Assembly

**Gate:** If round_table_enabled = false, skip this step entirely and proceed to Step 2.

If round_table_enabled = true, perform domain detection and panel assembly:

**1.5e.1: Domain Detection**

Analyze available context to identify relevant domains. Check in priority order:

1. **Explicit tags** — Look for `<!-- personas: frontend, security -->` markers in PRD/design content. If found, use those domains directly.
2. **Codebase signals** — From `.sdlc/artifacts/architecture.md`, identify affected components (e.g., components with "UI", "React", "frontend" -> frontend domain; "API", "database" -> backend domain; "CI/CD", "Docker" -> devops domain).
3. **Keyword analysis** — Scan PRD content and design doc for domain keywords:
   - Frontend: UI, component, React, CSS, layout, responsive, accessibility
   - Backend: API, endpoint, database, query, migration, service, middleware
   - DevOps: CI/CD, pipeline, Docker, deploy, infrastructure, monitoring
   - Security: auth, vulnerability, encryption, OWASP, credentials, permissions
4. **Content structure** — PRD functional requirements referencing specific technical domains

**1.5e.2: Panel Assembly**

Based on detected domains, assemble the persona panel:

| Rule | Logic |
|------|-------|
| **Domain personas** (Frontend, Backend, DevOps) | Include only if their domain is detected |
| **Cross-cutting** (Security, QA) | Always included — both are always relevant for task splitting |
| **Phase-role** (Architect) | Always included — Architect validates task granularity and dependency structure |
| **Lead assignment** | The persona whose domain has the strongest signal becomes lead. If unclear, Architect leads. |

Display the panel to the user:

```
Persona Panel for PRD Split:
  Lead: {persona_name} (signal: {detection_reason})
  Advisor: {persona_name} (signal: {detection_reason})
  ...
```

Reference: `_round-table-blocks.md` Section B

Proceed to Step 2.

---

### Step 2: Phase 1 - Investigation (Explore Agent)

Launch an **Explore** agent to investigate the codebase:

**Agent Configuration:**
```
Tool: Task
subagent_type: "Explore"
description: "Investigate codebase for PRD implementation"
```

**Prompt Template:**
```
Investigate the codebase to gather context for implementing this PRD.

## PRD Content
{prd_content}

## Design Document
{design_content}

Use the design document to:
- Focus investigation on components identified in the Impact Analysis section
- Verify file paths mentioned in the design actually exist
- Find implementation patterns mentioned in the Approach section

## Investigation Tasks

1. **Read Project Artifacts** (CRITICAL for task quality)
   Read ALL available artifacts — these provide essential context for accurate component
   assignments, file paths, and pattern adherence in generated tasks:
   ```
   Read: .sdlc/artifacts/architecture.md         → Components, boundaries, dependencies
   Read: .sdlc/artifacts/directory-structure.md   → File organization and placement
   Read: .sdlc/artifacts/codebase-summary.md      → Tech stack, conventions, patterns
   Read: .sdlc/artifacts/data-model.md            → Entities, relationships, schemas
   Read: .sdlc/artifacts/key-workflows.md         → Existing flows to integrate with
   ```
   If NO artifacts are found:
   ```
   ⚠️ WARNING: No codebase artifacts found in .sdlc/artifacts/.
   Task generation quality will be significantly lower without codebase context.
   Recommendation: Run `/sdlc:scan` first, then re-run `/sdlc:prd-split`.
   Proceeding with limited context...
   ```

2. **Find Similar Implementations**
   Search for 2-3 examples of similar features in the codebase.
   Focus on:
   - How similar features are structured
   - What utilities and helpers are reused
   - Error handling patterns
   - Testing approaches

3. **Identify Project Patterns**
   Document:
   - Naming conventions (camelCase, snake_case, etc.)
   - File organization for new features
   - Import patterns and module structure
   - Error handling approach (custom errors, try/catch patterns)
   - Logging patterns
   - Testing framework and patterns

4. **Find Reusable Code**
   List specific files/functions that could be leveraged:
   - Existing utilities to use (NOT recreate)
   - Base classes or interfaces to extend
   - Validation helpers
   - Configuration patterns

## Output Format

Return a structured investigation report:

### Architecture Summary
[Brief overview of relevant components]

### Similar Implementations Found
- [File]: [What it does and how it's relevant]

### Project Patterns
- **Naming:** [convention]
- **File Organization:** [pattern]
- **Error Handling:** [approach]
- **Testing:** [framework and patterns]
- **Logging:** [approach]

### Existing Code to Leverage
- `path/to/file.py`: [What to reuse]

### Key Technical Constraints
[Any constraints discovered]
```

**Store Output As:** `investigation_report`

---

### Step 2.5: Round-Table — Task Breakdown Review

**Gate:** If round_table_enabled = false, skip this step entirely and proceed to Step 3.

If round_table_enabled = true, run a round-table discussion after the investigation phase and before proposing the task breakdown in Step 3.

Execute the round-table following `_round-table-blocks.md` Section C:

**2.5.1: Build Context Packages**

For each persona in the panel, build a filtered context package containing:
- PRD content (`prd_content`)
- Design document (`design_content`)
- Investigation report from Step 2 (`investigation_report`)
- Extracted requirements (`requirement_list`) and design decisions (`design_decisions`)
- The specific question: "How should this PRD be decomposed into implementation tasks?"

**2.5.2: Detect Round-Table Mode**

Check the execution environment:
- If `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` environment variable equals `"1"`: Use **Agent Teams mode** (Section C.3a)
- Otherwise: Use **Task tool mode** (Section C.3b)

Display: `Round-Table Mode: {Agent Teams | Task Tool Fallback}`

**2.5.3: Dispatch Personas**

Launch persona subagents (parallel via Task tool, or as teammates in Agent Teams mode). Each persona analyzes from their domain perspective:

- **Architect** reviews task granularity, validates dependency structure, and checks that the proposed decomposition aligns with the system architecture
- **QA** validates that each proposed task area has testable acceptance criteria and identifies testing gaps
- **Security** validates presence of security-related tasks where the PRD touches authentication, authorization, data handling, or external integrations
- **Domain leads** (Frontend, Backend, DevOps — if on panel) validate implementation feasibility from their domain perspective, flag missing technical tasks

Each persona responds using the structured `---PERSONA-FINDINGS---` format from Section C.3b.

**2.5.4: Synthesize Recommendations**

Merge all persona findings into an attributed synthesis (Section C.4):

```markdown
## Round-Table Synthesis: Task Breakdown Review

### [{Persona Name} — {Role}]:
- {Finding/recommendation about task structure}

### Consensus:
- [Agreed] {Points all personas support about the decomposition}
- [Debated] {Disagreements} — {Persona A} suggests X, {Persona B} suggests Y → escalating to user

### Risks Identified:
- [{Persona}] {Risk to the task breakdown approach}
```

**Critical rule**: Disagreements between personas are ALWAYS surfaced to the user for decision. The orchestrator never resolves disagreements autonomously.

**2.5.5: Present and Continue**

Present the synthesis to the user. The synthesized recommendations inform the task breakdown proposal in Step 3. The Plan agent in Step 3 receives the round-table synthesis as additional input.

**Store Output As:** `roundtable_breakdown_review`

---

### Step 3: Phase 2 - Task Design (Plan Agent)

Launch a **Plan** agent to design the task breakdown:

**Agent Configuration:**
```
Tool: Task
subagent_type: "Plan"
description: "Design task breakdown for PRD"
```

**Prompt Template:**
```
Design an optimal task breakdown for implementing this PRD.

## PRD Content
{prd_content}

## Investigation Report
{investigation_report}

## Design Document
{design_content}

Use the design document to:
- Align tasks with design decisions — each task should implement specific design decisions
- Use file paths from the Impact Analysis for accurate "Files to Modify" lists
- Follow patterns specified in the Approach section
- Ensure the task breakdown covers ALL design decisions (100% coverage required)
- Include a "Design Compliance" mapping for each task showing which design decisions it implements

## PRD Requirements (Extracted)
{requirement_list}

This is the structured list of all PRD requirements (FR-xxx, NFR-xxx, AC-xxx) extracted in Step 1.5b.
Every task MUST trace back to at least one requirement from this list via its `traces_to` field.

## Design Decisions (Extracted)
{design_decisions}

This is the structured list of all design decisions (DD-N) extracted in Step 1.5c.
Every task MUST declare which design decisions it implements via its `design_compliance` field.

## Round-Table Recommendations (if available)
{roundtable_breakdown_review or "No round-table review performed (single-agent mode)."}

If round-table recommendations are present, incorporate them into the task breakdown:
- Address consensus points as requirements for the breakdown structure
- Resolve or flag debated points in the output
- Account for identified risks in task scope and dependencies

## Traceability Mapping Instructions

When designing the task breakdown, ensure full traceability:

1. **Requirement-to-Task Mapping:** For each task, identify which PRD requirements (FR-xxx, NFR-xxx, AC-xxx) it addresses. Record these in the task's `traces_to` field.
2. **Design Decision-to-Task Mapping:** For each task, identify which design decisions (DD-N) it implements. Record these in the task's `design_compliance` field.
3. **Coverage Validation:** After designing all tasks, verify:
   - Every requirement in `requirement_list` is referenced by at least one task's `traces_to`
   - Every decision in `design_decisions` is referenced by at least one task's `design_compliance`
4. **Gap Resolution:** If any requirement or design decision is not covered:
   - Add a task to cover it, OR
   - Flag it explicitly in the output as an uncovered item

## Task Design Guidelines

### Granularity: {granularity}
- **Coarse (3-5 tasks):** High-level feature chunks
- **Medium (5-10 tasks):** Balanced breakdown, 1-4 hours per task
- **Fine (10-20 tasks):** Detailed steps, single focused changes

### Dependency Analysis
Identify task dependencies using these patterns:
| Pattern | Flow | When to Use |
|---------|------|-------------|
| Data First | Model → API → UI | Feature needs data persistence |
| Config First | Config → Feature | Feature needs configuration |
| Auth First | Auth → Protected | Feature needs authentication |
| Schema First | Migration → ORM → API | Feature changes database |

For each task, ask:
1. Does this need data/models from another task?
2. Does this call functions created in another task?
3. Does this require configuration from another task?

### Task ID Format
Calculate IDs from context:
- Shortname: {shortname}
- Current total_tasks: {total_tasks}
- First new task: {shortname}-T{(total_tasks + 1):05d}

### Component Assignment
Assign each task to a component from the architecture.

## Output Format

Return a structured task breakdown:

### Task Breakdown Summary
Total tasks: [N]
Components involved: [list]

### Tasks

#### {shortname}-T{n}: [Title]
- **Priority:** high/medium/low
- **Component:** [component]
- **Dependencies:** [list of task IDs or "None"]
- **Goal:** [Single sentence describing what this accomplishes]
- **Key Requirements:** [From PRD acceptance criteria]
- **Traces To:** [List of PRD requirement IDs this task addresses, e.g., FR-001, AC-002, NFR-001]
- **Design Compliance:** [List of design decision IDs this task implements, e.g., DD-1, DD-3]
- **Files to Modify:** [Specific paths from investigation]
- **Existing Code to Leverage:** [From investigation report]

[Repeat for each task]

### Dependency Graph
```
{shortname}-T00001 → {shortname}-T00002 → {shortname}-T00003
                  ↘ {shortname}-T00004 ↗
```

### Implementation Order
1. [task_id]: [reason it's first]
2. [task_id]: [dependency on previous]
...

### Requirement Coverage Summary
| Requirement ID | Type | Covered By Task(s) | Status |
|----------------|------|---------------------|--------|
| FR-001         | Functional | {task_id_1}, {task_id_2} | Covered |
| NFR-001        | Non-Functional | {task_id_3} | Covered |
| AC-001         | Acceptance Criteria | {task_id_1} | Covered |
| FR-003         | Functional | — | UNCOVERED |

### Design Decision Coverage Summary
| Decision ID | Description | Implemented By Task(s) | Status |
|-------------|-------------|------------------------|--------|
| DD-1        | [description] | {task_id_1} | Covered |
| DD-2        | [description] | — | UNCOVERED |

### Uncovered Items (if any)
List any requirements or design decisions not covered by the task breakdown.
If all items are covered, state: "Full coverage achieved — all requirements and design decisions are traced to tasks."
```

**Store Output As:** `task_breakdown`

---

### Step 3.5: Unified Traceability Matrix

Before presenting tasks for approval, merge PRD requirements and design decisions into a single traceability view. This ensures every requirement and design decision is accounted for in the task breakdown.

**3.5.1: Build Matrix**

Cross-reference `requirement_list` (from Step 1.5b) and `design_decisions` (from Step 1.5c) against all tasks' `traces_to` and `design_compliance` fields:

```
## Traceability Matrix

### PRD Requirements Coverage
| Requirement | Type | Description | Implementing Task(s) | Coverage |
|-------------|------|-------------|---------------------|----------|
| FR-001      | Functional | {desc} | {task_id_1}, {task_id_2} | Covered |
| FR-002      | Functional | {desc} | {task_id_3} | Covered |
| NFR-001     | Non-Functional | {desc} | — | GAP |
| AC-001      | Acceptance Criteria | {desc} | {task_id_1} | Covered |

### Design Decision Coverage
| Decision | Description | Implementing Task(s) | Coverage |
|----------|-------------|---------------------|----------|
| DD-1     | {desc} | {task_id_2} | Covered |
| DD-2     | {desc} | {task_id_1}, {task_id_3} | Covered |
| DD-3     | {desc} | — | GAP |
```

**3.5.2: Identify Cross-Cutting Concerns**

Scan the traceability matrix for cross-cutting patterns:
- **Requirements appearing in 3+ tasks** are cross-cutting concerns (e.g., a security NFR implemented across many tasks)
- **NFRs that apply globally** (performance, security, accessibility) are flagged even if they appear in fewer tasks

Display as a separate table:

```
### Cross-Cutting Concerns
| Item | Type | Appears In | Nature |
|------|------|-----------|--------|
| NFR-001 | Non-Functional | T00001, T00003, T00005, T00007 | Security — applies across all API tasks |
| FR-003  | Functional | T00002, T00004, T00006 | Logging — spans multiple components |
```

If no cross-cutting concerns found:
```
No cross-cutting concerns identified — all requirements are isolated to 1-2 tasks.
```

**3.5.3: Verify Coverage**

Every requirement in `requirement_list` and every decision in `design_decisions` must have at least one implementing task.

If gaps found:
```
AskUserQuestion({
  questions: [{
    question: "Traceability matrix found {N} uncovered items ({R} requirements, {D} design decisions). How to proceed?",
    header: "Traceability Gaps",
    options: [
      { label: "Add tasks", description: "Return to Step 3 to design additional tasks covering the gaps" },
      { label: "Acknowledge gaps", description: "Gaps are intentional — proceed with documented gaps" },
      { label: "Cancel", description: "Abort splitting and rethink the breakdown" }
    ],
    multiSelect: false
  }]
})
```

If "Add tasks" selected: Return to Step 3 (Plan Agent) with gap information to design additional tasks.
If "Acknowledge gaps": Record the acknowledged gaps and proceed.
If "Cancel": Abort the splitting process.

If 100% covered:
```
Traceability: All {N} requirements and {M} design decisions are covered by the task breakdown.
```

**Store Output As:** `traceability_matrix`

---

### Step 3.6: Coverage Report

Generate a human-readable coverage summary from the traceability matrix built in Step 3.5.

**3.6.1: Calculate Coverage Metrics**

From the traceability matrix, compute:
- `req_covered`: Count of requirements with at least one implementing task
- `req_total`: Total count of items in `requirement_list`
- `req_percentage`: `(req_covered / req_total) * 100`
- `dd_covered`: Count of design decisions with at least one implementing task
- `dd_total`: Total count of items in `design_decisions`
- `dd_percentage`: `(dd_covered / dd_total) * 100`
- `cross_cutting_count`: Number of cross-cutting concerns identified in Step 3.5.2

**3.6.2: Generate Summary**

```
## Coverage Summary

- Requirements: {req_covered}/{req_total} covered ({req_percentage}%)
- Design Decisions: {dd_covered}/{dd_total} covered ({dd_percentage}%)
- Cross-Cutting Concerns: {cross_cutting_count} identified
```

**3.6.3: List Uncovered Items (if any)**

If there are uncovered items, list them explicitly:

```
### Uncovered Items
| ID | Type | Description |
|----|------|-------------|
| NFR-001 | Non-Functional Requirement | {description} |
| DD-3    | Design Decision | {description} |
```

**3.6.4: Present Coverage Result**

If 100% covered:
```
All {req_total} requirements and {dd_total} design decisions are covered by the task breakdown.
No action needed — proceeding to user approval.
```

If gaps exist, present via AskUserQuestion before proceeding to Step 4:
```
AskUserQuestion({
  questions: [{
    question: "Coverage is incomplete: {req_percentage}% requirements, {dd_percentage}% design decisions. Review the uncovered items above. How to proceed?",
    header: "Coverage Report",
    options: [
      { label: "Add tasks", description: "Return to Step 3 to add tasks for uncovered items" },
      { label: "Acknowledge gaps", description: "Proceed with incomplete coverage — gaps are documented" },
      { label: "Cancel", description: "Abort splitting" }
    ],
    multiSelect: false
  }]
})
```

If "Add tasks" selected: Return to Step 3 (Plan Agent) with uncovered items to design additional tasks.
If "Acknowledge gaps": Record the acknowledged gaps and proceed to Step 4.
If "Cancel": Abort the splitting process.

**Store Output As:** `coverage_summary`

---

### Step 3.7: Round-Table — Pre-Approval Validation

**Gate:** If round_table_enabled = false, skip this step entirely and proceed to Step 4.

If round_table_enabled = true, run a round-table discussion after the task breakdown is finalized (Step 3 through 3.6) and before presenting to the user for approval in Step 4.

Execute the round-table following `_round-table-blocks.md` Section C:

**3.7.1: Build Context Packages**

For each persona in the panel, build a filtered context package containing:
- The proposed task breakdown (`task_breakdown`)
- The traceability matrix (`traceability_matrix`)
- The coverage summary (`coverage_summary`)
- The specific question: "Does this task breakdown fully cover your domain's requirements? Are there traceability gaps or missing tasks?"

**3.7.2: Detect Round-Table Mode**

Check the execution environment:
- If `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` environment variable equals `"1"`: Use **Agent Teams mode** (Section C.3a)
- Otherwise: Use **Task tool mode** (Section C.3b)

Display: `Round-Table Mode: {Agent Teams | Task Tool Fallback}`

**3.7.3: Dispatch Personas for Final Validation**

Launch persona subagents (parallel via Task tool, or as teammates in Agent Teams mode). Each persona validates the complete breakdown:

- **Each persona validates**: Does this breakdown cover my domain's requirements from the PRD?
- **Traceability check**: Every PRD requirement has at least one task (`traces_to` coverage is 100%)
- **Completeness check**: No orphan tasks exist without PRD requirement traceability
- **Feasibility check**: Each task is implementable as scoped, with realistic dependencies

Each persona responds using the structured `---PERSONA-FINDINGS---` format from Section C.3b.

**3.7.4: Synthesize Validation Results**

Merge all persona findings into an attributed synthesis (Section C.4):

```markdown
## Round-Table Synthesis: Pre-Approval Validation

### [{Persona Name} — {Role}]:
- {Validation finding about task completeness from their domain}

### Consensus:
- [Agreed] {Points all personas confirm about the breakdown}
- [Debated] {Disagreements about task completeness} — {Persona A} suggests X, {Persona B} suggests Y → escalating to user

### Traceability Gaps Surfaced:
- [{Persona}] {Any requirement or design decision they believe is inadequately covered}

### Missing Tasks Identified:
- [{Persona}] {Any task they believe should be added}
```

**Critical rule**: Disagreements about task completeness are ALWAYS escalated to the user. The orchestrator never resolves completeness disputes autonomously.

**3.7.5: Handle Validation Findings**

If personas identified traceability gaps or missing tasks:

```
AskUserQuestion({
  questions: [{
    question: "Round-table validation surfaced {N} findings ({G} traceability gaps, {M} missing tasks). How to proceed?",
    header: "Round-Table Validation",
    options: [
      { label: "Add tasks", description: "Return to Step 3 to design additional tasks addressing the findings" },
      { label: "Acknowledge findings", description: "Findings noted — proceed to approval with current breakdown" },
      { label: "Cancel", description: "Abort splitting and rethink the breakdown" }
    ],
    multiSelect: false
  }]
})
```

If "Add tasks" selected: Return to Step 3 (Plan Agent) with the validation findings to design additional tasks.
If "Acknowledge findings": Record the findings and proceed to Step 4.
If "Cancel": Abort the splitting process.

If no gaps or missing tasks identified:
```
Round-table validation passed. All personas confirm the task breakdown is complete and traceable.
```

**3.7.6: Present and Continue**

Present the validation synthesis to the user. The results are included alongside the task breakdown in Step 4's approval presentation.

**Store Output As:** `roundtable_validation`

---

### Step 4: User Approval

Present the task breakdown and coverage summary to the user for review:

```
## Proposed Tasks for PRD: {prd_id}

{task_breakdown}

---

## Coverage Summary

- Requirements: {req_covered}/{req_total} covered ({req_percentage}%)
- Design Decisions: {dd_covered}/{dd_total} covered ({dd_percentage}%)
- Cross-Cutting Concerns: {cross_cutting_count} identified
{if gaps: "⚠️ Uncovered items documented — see traceability matrix above."}

{if roundtable_validation: include round-table validation synthesis here}

---

**Options:**
1. ✅ **Approve** - Create these tasks
2. ✏️ **Modify** - Adjust the breakdown (add/remove/change tasks)
3. 🔍 **Details** - See full content preview for a specific task
4. ❌ **Cancel** - Abort without creating tasks
```

Allow the user to:
- Approve the breakdown as-is
- Request modifications (adjust priorities, components, scope)
- Add or remove tasks
- Refine dependencies
- Request more or less detail

**Loop until user approves or cancels.**

---

### Step 4.5: Lesson-Learn Preflight Check

Before generating task content, validate against documented lessons:

**4.5.1: Load Lessons**
```
Read: .sdlc/lesson-learn.md       → Project-specific lessons
Read: ~/.a-sdlc/lesson-learn.md   → Global lessons (if exists)
```

If neither file exists, display:
> No lesson-learn.md found. Skipping preflight. Consider running `/sdlc:init` to set up lessons tracking.

Proceed to Step 5.

**4.5.2: Filter by Relevance**
Match lessons to PRD components/categories. A lesson is relevant if:
- Its category matches a component in the proposed task breakdown
- It references a pattern used in the affected files

**4.5.3: Present Lessons by Priority**

For MUST-level lessons (blocking):
```
AskUserQuestion({
  questions: [{
    question: "These MUST-level lessons apply. Acknowledge before proceeding:",
    header: "MUST lessons",
    options: [
      { label: "Acknowledged", description: "I've reviewed these and the task breakdown accounts for them" },
      { label: "Adjust tasks", description: "Go back and modify the task breakdown to address these" }
    ],
    multiSelect: false
  }]
})
```

For SHOULD-level lessons (warning):
```
AskUserQuestion({
  questions: [{
    question: "These SHOULD-level lessons may apply. Review before proceeding:",
    header: "SHOULD lessons",
    options: [
      { label: "Noted", description: "Reviewed — the task breakdown addresses these" },
      { label: "Adjust tasks", description: "Go back and modify the task breakdown" },
      { label: "Skip", description: "Not relevant to this PRD" }
    ],
    multiSelect: false
  }]
})
```

Display MAY-level lessons as informational text (no interaction required).

---

### Step 5: Phase 3 - Content Generation

For each approved task, generate full markdown content following the task template.

**Read the task template:**
```
Check for: .sdlc/templates/task.template.md (project-specific)
Fallback to: Default template structure
```

**For each task, generate content:**

```markdown
# {task_id}: {task_title}

**Status:** pending
**Priority:** {priority}
**Requirement:** {requirement_id}
**Component:** {component}
**Dependencies:** {dependencies}
**PRD Reference:** {prd_id}

## Goal

{goal from task breakdown}

## Implementation Context

### Files to Modify

{files from investigation + task design}

### Key Requirements

{requirements mapped from PRD}

### Traces To

{For each req_id in task.traces_to from the Plan agent output:}
- **{req_id}**: {look up full description from requirement_list extracted in Step 1.5b}

If the task has no traces_to entries, flag it:
> ⚠️ This task has no requirement traceability. Every task must trace to at least one PRD requirement.

### Design Compliance

This task implements the following design decisions:
{For each dd_id in task.design_compliance from the Plan agent output:}
- **{dd_id}**: {look up description from design_decisions extracted in Step 1.5c}

**Implementation guidance from design doc:**
- {Relevant approach/pattern from design's Approach section for the referenced decisions}
- {Relevant file paths from design's Impact Analysis for the referenced decisions}

If the task has no design_compliance entries, include:
> No specific design decisions mapped to this task.

### Technical Notes

{from investigation: patterns, constraints}

### Existing Code to Leverage

{from investigation report - specific files and functions}

### Project Patterns to Follow

- **Naming:** {convention from investigation}
- **File Organization:** {pattern from investigation}
- **Error Handling:** {approach from investigation}
- **Testing:** {pattern from investigation}

## Scope Definition

### Deliverables

{concrete outputs for this task}

### Exclusions

{what's NOT in scope - reference other tasks}

## Implementation Steps

{numbered steps with code hints following project style}

1. **{step_title}**
   {description}
   ```{language}
   {code hint following project patterns}
   ```
   - **Test:** {test description}

## Best Practices Checklist

**Before Coding:**
- [ ] Identified existing code to leverage
- [ ] Understand project patterns to follow
- [ ] Know where new code belongs

**During Coding:**
- [ ] Following naming conventions
- [ ] No code duplication (extracted shared logic)
- [ ] Each function has single responsibility
- [ ] Error handling follows project patterns

**After Coding:**
- [ ] Linting passes
- [ ] Tests written and passing
- [ ] Code follows project patterns
- [ ] No over-engineering

## Anti-Patterns to Avoid

{specific to this task from common patterns}

- Do not duplicate existing functionality - search first
- Do not over-engineer for hypothetical futures
- {task-specific anti-patterns}

## Acceptance Criteria

{For each requirement in task.traces_to, derive testable acceptance criteria from the PRD requirement text:}
- [ ] {testable criterion derived from the traced PRD requirement description}

Each task MUST have at least one acceptance criterion. Criteria must be:
- Derived from the traced PRD requirements (not invented)
- Specific and testable (can be verified as pass/fail)
- Actionable (describes observable behavior or output)

If no traces_to entries exist, flag:
> ⚠️ Cannot derive acceptance criteria without requirement traceability. Add traces_to entries first.

## Success Criteria

See Acceptance Criteria above — derived from traced PRD requirements.

### Quality Gates (Required Before Completion)

**Code Quality:**
- [ ] All linting checks pass
- [ ] No code duplication introduced
- [ ] Follows project naming conventions

**Testing:**
- [ ] Unit tests for new functionality
- [ ] Edge cases covered
- [ ] All tests pass

**Integration:**
- [ ] Code placed in correct location
- [ ] Uses existing utilities where available
- [ ] Follows error handling patterns

## Scope Constraint

{explicit statement of what NOT to do}
```

---

### Step 5.5: Quality Gate — Task Completeness Verification

Before persisting tasks, verify the breakdown covers the PRD completely and traceability is intact:

**5.5.1: Requirements Coverage Check**
Cross-reference the PRD's Functional Requirements against the proposed tasks:
- List each FR and the task(s) that address it
- Flag any FRs with no corresponding task

**5.5.2: Traceability Completeness Check**
For each generated task, verify:
- The `### Traces To` section contains at least 1 requirement ID from `requirement_list`
- The `### Acceptance Criteria` section contains at least 1 testable criterion
- Cross-reference against the coverage report from Step 3.6 to ensure no regressions

If a task fails traceability checks:
```
⚠️ Traceability gap in {task_id}:
  - Traces To: {count} entries (minimum: 1) {PASS/FAIL}
  - Acceptance Criteria: {count} entries (minimum: 1) {PASS/FAIL}
```

**5.5.3: Testing Coverage Check**
Verify at least one task includes:
- Unit test scope for new functionality
- Integration test scope if multiple components are involved

**5.5.4: Integration Check**
If the PRD affects 2+ components, verify:
- At least one task covers wiring/integration between components
- Dependencies between components are reflected in task dependencies

**5.5.5: Present Results**

If gaps found (including traceability gaps):
```
AskUserQuestion({
  questions: [{
    question: "Quality gate found potential gaps. How to proceed?",
    header: "Quality gate",
    options: [
      { label: "Add tasks", description: "Go back and add missing tasks to cover the gaps" },
      { label: "Fix traceability", description: "Go back to Step 5 to add missing traces_to or acceptance criteria" },
      { label: "Acknowledged", description: "Gaps are intentional — proceed with current breakdown" },
      { label: "Cancel", description: "Abort and rethink the breakdown" }
    ],
    multiSelect: false
  }]
})
```

If no gaps found, display:
> Quality gate passed. All requirements covered, traceability complete, tests included, integration tasks present.

**5.5.6: Log Quality Gate Corrections**

If the quality gate found gaps that were addressed (tasks added/modified), log the corrections:

```
mcp__asdlc__log_correction(
  context_type="prd",
  context_id="{prd_id}",
  category="{category}",
  description="{gap found and how it was addressed}"
)
```

For example, if a missing FR was caught and a task was added, log it as `task-completeness`.
If a traceability gap was found and fixed, log it as `traceability`.

Proceed to Step 6: Persistence.

---

### Step 6: Persistence

Write task files and persist to database:

**6.1: Write Task Files**

For each task, write the generated content:

```
# Use the Write tool to write each task file
Write tool:
  file_path: ~/.a-sdlc/content/{project_id}/tasks/{task_id}.md
  content: {generated_task_content}
```

**6.2: Call split_prd() with task_ids**

Once all files are written, persist to database. Include `traces_to` and `design_compliance` data from each task in the `data` dict so traceability information is stored alongside the task metadata:

```
mcp__asdlc__split_prd(
    prd_id="{prd_id}",
    task_specs=[
        {
            "task_id": "{task_id}",  # Pre-written file
            "title": "{title}",
            "priority": "{priority}",
            "component": "{component}",
            "dependencies": ["{dep_id}", ...],
            "data": {
                "traces_to": ["FR-001", "AC-002"],       # PRD requirement IDs this task addresses
                "design_compliance": ["DD-1", "DD-3"]     # Design decision IDs this task implements
            }
        },
        ...
    ]
)
```

The tool will:
- Detect pre-written files
- Register tasks in database
- Update PRD status to "split"

---

### Step 6.5: Post-Split Verification

After tasks are persisted, run server-side requirement parsing and coverage verification to ensure the split is complete.

#### 6.5.1: Parse Requirements (MCP Tool)

Call the `parse_requirements` MCP tool to extract and classify PRD requirements server-side. This ensures the database has up-to-date requirement records with depth classifications for the coverage report.

```
parse_result = mcp__asdlc__parse_requirements(prd_id="{prd_id}")
```

Display the result:
```
Requirements parsed: {parse_result.total} total
  - {parse_result.counts.FR} Functional Requirements
  - {parse_result.counts.NFR} Non-Functional Requirements
  - {parse_result.counts.AC} Acceptance Criteria

{If parse_result.unrecognized_candidates is non-empty:}
  Unrecognized candidates found (may be requirements with non-standard IDs):
  {list unrecognized_candidates}
```

If `parse_requirements` returns `status: "not_found"`, the PRD was not saved correctly. Report an error and stop.

#### 6.5.2: Coverage Report (MCP Tool)

Call the `get_quality_report` MCP tool to verify that all parsed requirements are linked to tasks:

```
coverage = mcp__asdlc__get_quality_report("coverage", prd_id="{prd_id}")
```

Display the coverage summary:
```
Coverage Report for PRD {prd_id}:
  - Linkage: {coverage.linkage_pct}% ({coverage.linked}/{coverage.total} requirements linked to tasks)
  - Completion: {coverage.completion_pct}% ({coverage.completed_tasks}/{coverage.total_tasks} tasks completed)

{If coverage.orphaned is non-empty:}
  Orphaned requirements (not linked to any task):
  {list each orphaned requirement with ID and summary}

{If coverage.behavioral_gaps is non-empty:}
  Behavioral requirements lacking test-evidence tasks:
  {list each behavioral gap}
```

If orphaned requirements are found (AC-014), present them for resolution:

```
AskUserQuestion([
  {
    question: "Coverage report found {N} orphaned requirements not linked to any task. How to proceed?",
    header: "Orphaned Requirements",
    options: [
      { label: "Add tasks", description: "Return to Step 3 to design tasks covering orphaned requirements" },
      { label: "Acknowledge gaps", description: "Orphaned requirements are intentional — proceed" },
      { label: "Cancel", description: "Abort and rethink the split" }
    ]
  }
])
```

- If **Add tasks**: Return to Step 3 (Plan Agent) with orphaned requirement IDs
- If **Acknowledge gaps**: Record and proceed
- If **Cancel**: Abort

#### 6.5.3: Cross-PRD Integration Recommendations (FR-019)

Check if the project has other active PRDs that may interact with this one:

```
all_prds = mcp__asdlc__list_prds(status="approved")
# Also check draft and split PRDs
draft_prds = mcp__asdlc__list_prds(status="draft")
split_prds = mcp__asdlc__list_prds(status="split")
```

If other PRDs exist, scan for potential integration points:
1. Compare affected components across PRDs (from task component assignments)
2. Look for shared files in "Files to Modify" across PRDs
3. Identify overlapping requirement areas (e.g., both PRDs touch authentication)

If integration points are found:
```
Cross-PRD Integration Recommendations:

- PRD {other_prd_id} ("{other_prd_title}") shares component "{component}":
  Tasks {task_ids} may need coordination with tasks from {other_prd_id}.

- PRD {other_prd_id} modifies "{shared_file}":
  Consider dependency ordering to avoid merge conflicts.

Recommendation: Review these integration points during sprint planning.
```

If no other PRDs exist or no integration points found:
```
No cross-PRD integration concerns identified.
```

---

### Step 6.6: Challenge Gate (Post-Split)

**This gate is conditional on quality configuration. Skip entirely if not configured.**

#### 6.6.1: Check Quality Config

```
Read: .sdlc/config.yaml → look for quality.enabled and quality.challenge sections
```

**Skip this entire section if ANY of these are true:**
- `.sdlc/config.yaml` does not exist
- `quality.enabled` is `false` or absent
- `quality.challenge.enabled` is `false`
- `quality.challenge.gates.split` is `false`

If skipping:
```
Challenge gate: skipped (quality challenges not enabled for split)
```
Proceed to Step 7.

#### 6.6.2: Initiate Split Challenge

```
challenge = mcp__asdlc__challenge_artifact(
    artifact_type="split",
    artifact_id="{prd_id}"
)
```

The challenge tool assembles:
- The list of tasks created for this PRD
- Linked requirements and their coverage status
- The challenge checklist for split reviews

#### 6.6.3: Run Challenger via Task Tool

Launch a challenger agent:

```
Task:
  description: "Challenge this task split as a critical reviewer"
  prompt: |
    You are a challenger reviewing a PRD-to-task split for completeness and quality.

    {challenge.challenge_prompt}

    ## Coverage Report
    {coverage report from Step 6.5.2}

    ## Cross-PRD Integration
    {integration recommendations from Step 6.5.3}

    Focus your review on:
    - Orphaned requirements not covered by any task (AC-014)
    - Tasks that are too large or too vague to implement in one session
    - Missing dependencies between tasks
    - Component assignments that don't match the architecture
    - Cross-PRD integration risks that are not addressed
    - Tasks without clear acceptance criteria

    Return your objections in this format:
    ---CHALLENGE-OBJECTIONS---
    - category: coverage|granularity|dependency|assignment|integration|criteria
      description: "..."
      severity: blocking|warning
      requirement_ref: "FR-xxx or AC-xxx if applicable"
    ---END-OBJECTIONS---
```

#### 6.6.4: Record and Resolve

Follow the same challenge round loop:

1. Record objections via `mcp__asdlc__record_challenge_round(artifact_type="split", artifact_id="{prd_id}", ...)`
2. Present objections to user
3. User addresses (may need to add/modify tasks), accepts risk, or skips (soft gate only)
4. Re-challenge if needed, up to `quality.challenge.max_rounds`
5. Check status via `mcp__asdlc__get_challenge_status(artifact_type="split", artifact_id="{prd_id}")`

#### 6.6.5: Gate Enforcement

- If `quality.challenge.gate` is `"hard"` AND unresolved blocking objections remain:
  ```
  BLOCKED: Split challenge has unresolved blocking objections.
  The split cannot be finalized until these are addressed.

  Unresolved:
  - {objection description}

  Modify the tasks and re-run the challenge.
  ```
  **Do not proceed to Step 7. Return to Step 4 (User Approval) to modify the split.**

- If `quality.challenge.gate` is `"soft"` AND unresolved objections remain:
  ```
  WARNING: Split challenge has unresolved objections. Proceeding with warnings.
  Consider addressing these before starting implementation:
  - {objection description}
  ```
  Proceed to Step 7.

- If all objections resolved:
  ```
  Split challenge passed. All objections resolved.
  ```
  Proceed to Step 7.

---

### Step 7: Display Results

```
## Tasks Created

PRD '{prd_id}' has been split into {N} tasks:

| ID | Title | Priority | Component | Dependencies |
|----|-------|----------|-----------|--------------|
| {task_id} | {title} | {priority} | {component} | {deps} |
...

PRD status updated to: **split**

**Dependency Graph:**
{visual dependency graph}

**Next steps for user:**
- View tasks: `/sdlc:task-list`
- See task details: `/sdlc:task-show {task_id}`
- Start working: `/sdlc:task-start {task_id}`
```

## ⛔ STOP HERE

**Do NOT proceed further.** The task creation workflow is complete.

The user must explicitly run one of these commands to continue:
- `/sdlc:task-list` - View all tasks
- `/sdlc:task-show {task_id}` - See task details
- `/sdlc:task-start {task_id}` - Begin implementing a specific task

**Wait for user's next instruction.**

---

## Granularity Levels

| Level | Tasks | Description | Use When |
|-------|-------|-------------|----------|
| **Coarse** | 3-5 | High-level feature chunks | Initial planning, simple features |
| **Medium** | 5-10 | Balanced breakdown (1-4 hrs each) | Default, most PRDs |
| **Fine** | 10-20 | Detailed implementation steps | Complex features, junior devs |

---

## Best Practices Framework

### Coding Principles (Embedded in Task Content)

Every generated task includes guidance for:

1. **DRY - Don't Repeat Yourself**
   - "Existing Code to Leverage" section from investigation
   - Warn against recreating existing utilities

2. **Single Responsibility**
   - Task scope kept narrow and focused
   - Explicit exclusions referencing other tasks

3. **Clean Code**
   - Naming guidance specific to the feature
   - Code hints follow project style

4. **KISS - Keep It Simple**
   - Anti-patterns section warns against over-engineering
   - Scope constraints limit gold-plating

5. **Proper Abstraction**
   - Task design considers appropriate abstraction level
   - Implementation steps guide incremental abstraction

### Quality Gates

Every task includes:
- Pre-coding checklist (understanding)
- During-coding checklist (execution)
- Post-coding checklist (validation)
- Success criteria (acceptance)

---

## Common Issues

**PRD not found:**
```
Error: PRD not found: feature-auth
```
Solution: Run `/sdlc:prd-list` to see available PRDs.

**No project context:**
```
Error: No project context. Run /sdlc:init first.
```
Solution: Initialize the project with `/sdlc:init`.

**Investigation agent finds no patterns:**
```
Warning: No .sdlc/artifacts/ found
```
Solution: Run `/sdlc:scan` first for better task generation, or proceed with limited context.

**Task file write fails:**
```
Error: Permission denied writing to ~/.a-sdlc/content/...
```
Solution: Check directory permissions.

---

## Important Notes

1. **Multi-Agent Workflow:** This skill coordinates multiple agents. Allow each phase to complete before proceeding.

2. **User Approval Required:** Always wait for explicit user approval before creating tasks.

3. **Investigation Quality:** The investigation phase significantly improves task quality. If artifacts aren't available, consider running `/sdlc:scan` first.

4. **File-First Persistence:** Task files are written before database records to ensure content is never lost.

5. **Template Flexibility:** Users can customize `.sdlc/templates/task.template.md` for project-specific task structure.

6. **No Implementation:** This skill creates task documentation only. It does NOT write source code, modify project files, or execute tasks. Wait for user's explicit instruction to proceed.
