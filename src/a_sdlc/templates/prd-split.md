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

## Investigation Tasks

1. **Read Project Artifacts** (if available)
   - `.sdlc/artifacts/architecture.md` - Components and patterns
   - `.sdlc/artifacts/directory-structure.md` - File organization
   - `.sdlc/artifacts/codebase-summary.md` - Tech stack and conventions
   - `.sdlc/artifacts/data-model.md` - Entities and relationships

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

**Next steps:**
- View tasks: `/sdlc:task-list`
- See task details: `/sdlc:task-show {task_id}`
- Start working: `/sdlc:task-start {task_id}`
```

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

6. **No Implementation:** This skill creates task documentation only. It does NOT write source code.
