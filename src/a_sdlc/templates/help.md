# /sdlc:help - List Available Commands

Display all available SDLC skills with descriptions and usage examples.

## Purpose

Quick reference for all `/sdlc:*` commands without leaving Claude Code.

## Output Format

```
╭──────────────────────────────────────────────────────────╮
│                    SDLC Commands                          │
╰──────────────────────────────────────────────────────────╯

📚 Core Commands

  /sdlc:init     Initialize a-sdlc for the current project
  /sdlc:scan     Full repo scan → generate codebase artifacts
  /sdlc:update   Incremental update of stale artifacts
  /sdlc:status   Show project context and statistics
  /sdlc:ask      Answer any question about this repository

📋 PRD Management

  /sdlc:ideate "<idea>"        Explore a vague idea → one or more PRDs
  /sdlc:prd-generate "<desc>"  Create PRD via interactive Q&A
  /sdlc:prd-architect "<id>"   Generate ADR-style design doc for PRD
  /sdlc:prd-split "<id>"       Decompose PRD into tasks (design required)
  /sdlc:prd-import jira <key>  Import Jira issue as PRD
  /sdlc:prd-list               List all PRDs
  /sdlc:prd "<id>"             PRD management hub
  /sdlc:prd-update "<id>"      Update existing PRD
  /sdlc:prd-delete <id>        Delete a PRD
  /sdlc:prd-investigate "<id>" Validate PRD against codebase

🔍 Investigation & Analysis

  /sdlc:investigate "<problem>"     Root cause analysis for bugs/errors
  /sdlc:investigate --error "<msg>" Analyze error message or stack trace
  /sdlc:pr-feedback                 Fetch & process PR review comments
  /sdlc:sonar-scan                  SonarQube scan & auto-fix

📋 Task Management

  /sdlc:task                   Task management hub
  /sdlc:task-list              List all tasks
  /sdlc:task-show <id>         Show task details
  /sdlc:task-create            Create a new task
  /sdlc:task-start <id>        Mark task as in-progress
  /sdlc:task-complete <id>     Mark task as completed
  /sdlc:task-split <id>        Split task into subtasks
  /sdlc:task-link <id>         Link task to external system
  /sdlc:task-delete <id>       Delete a task

🏃 Sprint Management

  /sdlc:sprint                 Sprint management hub
  /sdlc:sprint-create          Create a new sprint
  /sdlc:sprint-list            List all sprints
  /sdlc:sprint-show <id>       Show sprint details + tasks
  /sdlc:sprint-start <id>      Activate a sprint
  /sdlc:sprint-run <id>        Execute tasks in dependency order
  /sdlc:sprint-complete <id>   Close sprint + retrospective
  /sdlc:sprint-delete <id>     Delete a sprint

🔬 Quality & Retrospective

  /sdlc:retrospective           Analyze corrections → distill lessons

🔄 External Sync (Jira/Linear)

  /sdlc:sprint-import          Import sprints from Jira/Linear
  /sdlc:sprint-link            Link local sprint to external
  /sdlc:sprint-sync            Bidirectional sprint sync
  /sdlc:sprint-sync-to         Push sprint to external system
  /sdlc:sprint-sync-from       Pull sprint from external system
  /sdlc:sprint-unlink          Remove external sprint link
  /sdlc:sprint-mappings        View all sync mappings

📤 Publishing

  /sdlc:publish                Publish artifacts to Confluence

📖 Help

  /sdlc:help     Show this command reference
```

## MCP Tools Reference

All commands use the a-sdlc MCP server tools:

### Context & Navigation
- `mcp__asdlc__get_context()` - Get current project summary
- `mcp__asdlc__init_project(name?)` - Initialize project
- `mcp__asdlc__list_projects()` - List all projects
- `mcp__asdlc__switch_project(project_id)` - Change project
- `mcp__asdlc__relocate_project(shortname)` - Re-link project to current directory

### PRD Operations
- `mcp__asdlc__list_prds()` - List PRDs
- `mcp__asdlc__get_prd(prd_id)` - Get full PRD with file_path
- `mcp__asdlc__create_prd(title)` - Create PRD (returns file_path → Write content)
- `mcp__asdlc__update_prd(prd_id, status?, version?, sprint_id?)` - Update PRD metadata
- `mcp__asdlc__delete_prd(prd_id)` - Delete PRD
- `mcp__asdlc__split_prd(prd_id, task_specs)` - Decompose PRD into tasks

### Design Operations
- `mcp__asdlc__create_design(prd_id)` - Create design doc (returns file_path → Write content)
- `mcp__asdlc__get_design(prd_id)` - Get design doc with file_path and content
- `mcp__asdlc__delete_design(prd_id)` - Delete design doc
- `mcp__asdlc__list_designs()` - List design docs for current project

### Task Operations
- `mcp__asdlc__list_tasks(status?, sprint_id?, prd_id?)` - List tasks
- `mcp__asdlc__get_task(task_id)` - Get task details with file_path
- `mcp__asdlc__create_task(title, prd_id?, priority?, component?)` - Create task (returns file_path → Write content)
- `mcp__asdlc__update_task(task_id, status?, priority?, ...)` - Update task metadata (use status="in_progress"/"completed"/"blocked")
- `mcp__asdlc__delete_task(task_id)` - Delete task

### Sprint Operations
- `mcp__asdlc__list_sprints()` - List sprints
- `mcp__asdlc__get_sprint(sprint_id)` - Get sprint details
- `mcp__asdlc__create_sprint(title, goal?)` - Create sprint
- `mcp__asdlc__update_sprint(sprint_id, status?, title?, goal?)` - Update sprint (use status="active" to start)
- `mcp__asdlc__complete_sprint(sprint_id)` - Complete sprint
- `mcp__asdlc__manage_sprint_prds(action, prd_id, sprint_id?)` - Add/remove PRDs from sprint
- `mcp__asdlc__get_sprint_prds(sprint_id)` - List PRDs in sprint
- `mcp__asdlc__get_sprint_tasks(sprint_id)` - List tasks in sprint (derived via PRDs)
- `mcp__asdlc__delete_sprint(sprint_id)` - Delete sprint

### Sync Operations
- `mcp__asdlc__manage_sync_mapping(action, entity_type, entity_id, system?, external_id?)` - Link/unlink sprint or PRD
- `mcp__asdlc__sync_sprint(sprint_id, direction?)` - Sync sprint (direction: "bidirectional"/"push"/"pull")
- `mcp__asdlc__sync_prd(prd_id, direction?)` - Sync PRD (direction: "bidirectional"/"push"/"pull")
- `mcp__asdlc__import_from_linear()` - Import cycles from Linear
- `mcp__asdlc__import_from_jira()` - Import sprints from Jira
- `mcp__asdlc__list_sync_mappings()` - View all sync mappings

### Worktree & PR Operations
- `mcp__asdlc__setup_prd_worktree(prd_id)` - Create git worktree for PRD
- `mcp__asdlc__cleanup_prd_worktree(prd_id)` - Remove PRD worktree
- `mcp__asdlc__create_prd_pr(prd_id)` - Create PR from PRD worktree

### Integration Configuration
- `mcp__asdlc__manage_integration(action, system?, config?)` - Manage integrations (action: "configure"|"list"|"remove")

### Review Tools
- `mcp__asdlc__submit_review(task_id, reviewer_type, verdict, findings?, test_output?)` - Submit review (reviewer_type: "self"/"subagent")
- `mcp__asdlc__get_review_evidence(task_id)` - Get all review evidence for a task

### Quality Tools
- `mcp__asdlc__log_correction(context_type, context_id, category, description)` - Log a correction to `.sdlc/corrections.log`
- `mcp__asdlc__get_pr_feedback(pr_url?)` - Fetch and parse PR review comments

## Quick Start Workflow

```
1. /sdlc:init                              # Initialize (once per project)
2. /sdlc:scan                              # Generate codebase artifacts
3. /sdlc:ideate "vague idea"               # (Optional) Explore idea → PRDs
4. /sdlc:prd-generate "Feature description" # Create PRD
5. /sdlc:prd-architect "<prd-id>"          # Generate design document
6. /sdlc:prd-split "<prd-id>"             # Decompose into tasks
7. /sdlc:sprint-create "Sprint 1"          # Create sprint
   → use manage_sprint_prds(action="add") to assign PRDs  # Link PRDs to sprint
8. /sdlc:sprint-start "<sprint-id>"        # Activate sprint
9. /sdlc:sprint-run "<sprint-id>"          # Execute tasks in order
```

## Lessons Learned System

a-sdlc tracks lessons learned at two levels:
- **Project:** `.sdlc/lesson-learn.md` — rules specific to this project
- **Global:** `~/.a-sdlc/lesson-learn.md` — rules from all projects

Lessons are categorized (Testing, Code Quality, Task Completeness, Integration, Documentation) with priorities (MUST/SHOULD/MAY). They are automatically loaded during key workflows:
- `/sdlc:prd-generate` — Lessons inform PRD quality
- `/sdlc:prd-split` — Preflight check + quality gate
- `/sdlc:task-start` — Preflight check before implementation
- `/sdlc:sprint-run` — Sprint-level lesson summary
- `/sdlc:task-complete` — Definition-of-done checklist
- `/sdlc:sprint-complete` — Auto-retrospective with lesson distillation
- `/sdlc:pr-feedback` — Logs corrections to `.sdlc/corrections.log`

## Quality System

a-sdlc includes a built-in quality feedback loop:

1. **Corrections Log** — Fixes are logged via `mcp__asdlc__log_correction()` from any workflow step
2. **Retrospective** — `/sdlc:retrospective` analyzes corrections and distills them into lessons (also triggered by `/sdlc:sprint-complete`)
3. **Lessons Learned** — Stored in `.sdlc/lesson-learn.md` (project) and `~/.a-sdlc/lesson-learn.md` (global)
4. **Preflight Checks** — Lessons are presented before key workflow steps
5. **Quality Gates** — Completeness verified at PRD split and task completion

### Commands with Quality Gates

- `/sdlc:prd-split` — Includes lesson-learn preflight check and requirements coverage gate
- `/sdlc:task-start` — Includes lesson-learn preflight before implementation
- `/sdlc:task-complete` — Includes definition-of-done checklist
- `/sdlc:sprint-run` — Includes sprint-level lesson preflight
- `/sdlc:sprint-complete` — Includes auto-retrospective with lesson distillation
- `/sdlc:pr-feedback` — Logs corrections to `.sdlc/corrections.log`

## Data Storage

- All data stored in user-level SQLite: `~/.a-sdlc/data.db`
- Content files: `~/.a-sdlc/content/{project_id}/prds/` and `tasks/`
- Lesson-learn files: `.sdlc/lesson-learn.md` (project), `~/.a-sdlc/lesson-learn.md` (global)
- Correction log: `.sdlc/corrections.log` (append-only)
- Data persists across Claude Code sessions

## CLI Commands

```bash
a-sdlc install      # Install skill templates + configure MCP server
a-sdlc serve        # Start MCP server (auto-started by Claude Code)
a-sdlc doctor       # Run system diagnostics
a-sdlc tasks        # CLI task management
a-sdlc ui           # Start web UI dashboard
```

---

## Important: a-sdlc Tasks vs Claude Code Internal Tasks

When using a-sdlc, you will encounter two different "task" systems. Understanding the distinction is critical:

### a-sdlc Tasks (Use These for Project Management)

- **What:** Persistent work items stored in database + markdown files
- **Location:** `~/.a-sdlc/content/{project_id}/tasks/{task_id}.md`
- **Tools:** `mcp__asdlc__create_task()`, `mcp__asdlc__update_task()`, `mcp__asdlc__split_prd()`
- **Commands:** `/sdlc:task-create`, `/sdlc:task-start`, `/sdlc:task-complete`
- **Features:** PRD linking, sprint assignment, external sync (Linear/Jira)

### Claude Code Internal Tasks (NOT for a-sdlc)

- **What:** Temporary workflow tracking within a single Claude Code session
- **Tools:** `TodoWrite`, `TaskCreate`, `TaskUpdate`, `TaskList`
- **Use For:** Organizing multi-step coding operations, tracking implementation progress
- **NOT For:** Creating a-sdlc project tasks, sprint planning, PRD breakdown

### Quick Reference

| Action | CORRECT Tool | WRONG Tool |
|--------|--------------|------------|
| Create task from PRD | `mcp__asdlc__split_prd()` | `TaskCreate` |
| Mark task in progress | `mcp__asdlc__update_task(status="in_progress")` | `TaskUpdate` |
| List project tasks | `mcp__asdlc__list_tasks()` | `TaskList` |
| Track coding steps | `TodoWrite` (OK for this) | - |

---

## Notes

- All commands work from the project root directory
- Run `/sdlc:init` before using other commands
- Use `/sdlc:status` to see project overview
