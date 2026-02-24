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
```

**Store Output As:** `task_breakdown`

---

### Step 3.5: Design Decision Traceability Matrix

Before presenting tasks for approval, generate and verify a traceability matrix.

**3.5.1: Extract Design Decisions**
From the design document, extract each key decision from the Decision and Approach sections.

**3.5.2: Map Decisions to Tasks**
For each design decision, identify which task(s) implement it:

```
## Design Decision Traceability Matrix

| Design Decision | Implementing Task(s) | Coverage |
|----------------|----------------------|----------|
| {decision_1}   | {task_id_1}, {task_id_2} | Covered |
| {decision_2}   | {task_id_3}              | Covered |
| {decision_3}   | —                        | GAP     |
```

**3.5.3: Verify 100% Coverage**
Every design decision must have at least one implementing task.

If gaps found:
```
AskUserQuestion({
  questions: [{
    question: "Design traceability found {N} uncovered decisions. How to proceed?",
    header: "Traceability",
    options: [
      { label: "Add tasks", description: "Go back and add tasks to cover the gaps" },
      { label: "Acknowledge gaps", description: "Gaps are intentional — proceed with current breakdown" },
      { label: "Cancel", description: "Abort and rethink the breakdown" }
    ],
    multiSelect: false
  }]
})
```

If 100% covered:
```
Design Traceability: All {N} design decisions are covered by the task breakdown.
```

Present the matrix to the user as part of the task breakdown in Step 4.

---

### Step 4: User Approval

Present the task breakdown to the user for review:

```
## Proposed Tasks for PRD: {prd_id}

{task_breakdown}

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

### Design Compliance

This task implements the following design decisions:
- **[Decision from design doc]**: [Brief description]

**Implementation guidance from design doc:**
- [Relevant approach/pattern from design's Approach section]
- [Relevant file paths from design's Impact Analysis]

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

## Success Criteria

{derived from PRD acceptance criteria - checkboxes}

- [ ] {criterion 1}
- [ ] {criterion 2}

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

Before persisting tasks, verify the breakdown covers the PRD completely:

**5.5.1: Requirements Coverage Check**
Cross-reference the PRD's Functional Requirements against the proposed tasks:
- List each FR and the task(s) that address it
- Flag any FRs with no corresponding task

**5.5.2: Testing Coverage Check**
Verify at least one task includes:
- Unit test scope for new functionality
- Integration test scope if multiple components are involved

**5.5.3: Integration Check**
If the PRD affects 2+ components, verify:
- At least one task covers wiring/integration between components
- Dependencies between components are reflected in task dependencies

**5.5.4: Present Results**

If gaps found:
```
AskUserQuestion({
  questions: [{
    question: "Quality gate found potential gaps. How to proceed?",
    header: "Quality gate",
    options: [
      { label: "Add tasks", description: "Go back and add missing tasks to cover the gaps" },
      { label: "Acknowledged", description: "Gaps are intentional — proceed with current breakdown" },
      { label: "Cancel", description: "Abort and rethink the breakdown" }
    ],
    multiSelect: false
  }]
})
```

If no gaps found, display:
> Quality gate passed. All requirements covered, tests included, integration tasks present.

**5.5.5: Log Quality Gate Corrections**

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

Once all files are written, persist to database:

```
mcp__asdlc__split_prd(
    prd_id="{prd_id}",
    task_specs=[
        {
            "task_id": "{task_id}",  # Pre-written file
            "title": "{title}",
            "priority": "{priority}",
            "component": "{component}",
            "dependencies": ["{dep_id}", ...]
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
