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
  /sdlc:prd-import jira <key>  Import Jira issue as PRD
  /sdlc:prd-list               List all PRDs
  /sdlc:prd "<id>"             View PRD details
  /sdlc:prd-split "<id>"       Decompose PRD into tasks
  /sdlc:prd-update "<id>"      Update existing PRD
  /sdlc:prd-delete <id>        Delete a PRD
  /sdlc:prd-investigate "<id>" Validate PRD against codebase

🔍 Investigation & Debugging

  /sdlc:investigate "<problem>"     Root cause analysis for bugs/errors
  /sdlc:investigate --error "<msg>" Analyze error message or stack trace

🔍 Code Review

  /sdlc:pr-feedback                Fetch & process PR review comments

📋 Task Management

  /sdlc:task-list              List all tasks
  /sdlc:task-show <id>         Show task details
  /sdlc:task-create            Create a new task
  /sdlc:task-start <id>        Mark task as in-progress
  /sdlc:task-complete <id>     Mark task as completed
  /sdlc:task-delete <id>       Delete a task

🏃 Sprint Management

  /sdlc:sprint-create          Create a new sprint
  /sdlc:sprint-list            List all sprints
  /sdlc:sprint-show <id>       Show sprint details + tasks
  /sdlc:sprint-start <id>      Activate a sprint
  /sdlc:sprint-run <id>        Execute tasks in order
  /sdlc:sprint-complete <id>   Close a sprint
  /sdlc:sprint-delete <id>     Delete a sprint

🔄 External Sync (Jira/Linear)

  /sdlc:sprint-import          Import sprints from Jira/Linear
  /sdlc:sprint-link            Link local sprint to external
  /sdlc:sprint-sync            Bidirectional sync
  /sdlc:sprint-unlink          Remove external link
  /sdlc:prd-link               Link PRD to Jira issue
  /sdlc:prd-sync               Sync single PRD to/from Jira
  /sdlc:prd-unlink             Remove PRD external link

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

### PRD Operations
- `mcp__asdlc__list_prds()` - List PRDs
- `mcp__asdlc__get_prd(prd_id)` - Get full PRD
- `mcp__asdlc__create_prd(title, content, ...)` - Create PRD
- `mcp__asdlc__update_prd(prd_id, ...)` - Update PRD
- `mcp__asdlc__delete_prd(prd_id)` - Delete PRD

### Design Operations
- `mcp__asdlc__create_design(prd_id, content)` - Create design doc for PRD
- `mcp__asdlc__get_design(prd_id)` - Get design doc with content
- `mcp__asdlc__update_design(prd_id, content)` - Update design doc
- `mcp__asdlc__delete_design(prd_id)` - Delete design doc
- `mcp__asdlc__list_designs()` - List design docs for current project

### Task Operations
- `mcp__asdlc__list_tasks(status?, sprint_id?, prd_id?)` - List tasks
- `mcp__asdlc__get_task(task_id)` - Get task details
- `mcp__asdlc__create_task(title, description, ...)` - Create task
- `mcp__asdlc__update_task(task_id, ...)` - Update task
- `mcp__asdlc__start_task(task_id)` - Mark in_progress
- `mcp__asdlc__complete_task(task_id)` - Mark completed
- `mcp__asdlc__block_task(task_id, reason?)` - Mark blocked
- `mcp__asdlc__delete_task(task_id)` - Delete task

### Sprint Operations
- `mcp__asdlc__list_sprints()` - List sprints
- `mcp__asdlc__get_sprint(sprint_id)` - Get sprint with tasks
- `mcp__asdlc__create_sprint(title, goal?)` - Create sprint
- `mcp__asdlc__start_sprint(sprint_id)` - Activate sprint
- `mcp__asdlc__complete_sprint(sprint_id)` - Complete sprint
- `mcp__asdlc__add_tasks_to_sprint(sprint_id, task_ids)` - Add tasks
- `mcp__asdlc__remove_tasks_from_sprint(sprint_id, task_ids)` - Remove tasks
- `mcp__asdlc__delete_sprint(sprint_id)` - Delete sprint

### PRD Sync Operations
- `mcp__asdlc__link_prd(prd_id, system, external_id)` - Link PRD to Jira issue
- `mcp__asdlc__unlink_prd(prd_id)` - Remove PRD link
- `mcp__asdlc__sync_prd(prd_id, strategy?, dry_run?)` - Bidirectional sync
- `mcp__asdlc__sync_prd_to(prd_id)` - Push PRD to Jira
- `mcp__asdlc__sync_prd_from(prd_id)` - Pull from Jira to PRD

### Quality Tools
- `mcp__asdlc__log_correction(context_type, context_id, category, description)` - Log a correction to `.sdlc/corrections.log`

## Quick Start Workflow

```
1. /sdlc:init                              # Initialize (once per project)
2. /sdlc:status                            # Check project context
3. /sdlc:ideate "vague idea"               # (Optional) Explore idea → PRDs
4. /sdlc:prd-generate "Feature description" # Create PRD (if you know what to build)
5. /sdlc:sprint-create "Sprint 1"          # Create sprint
6. /sdlc:prd-split "prd-id" --sprint SPRINT-01  # Generate tasks
7. /sdlc:sprint-start SPRINT-01            # Activate sprint
8. /sdlc:sprint-run SPRINT-01              # Execute tasks
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
2. **Retrospective** — `/sdlc:sprint-complete` distills corrections into lessons
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
| Mark task in progress | `mcp__asdlc__start_task()` | `TaskUpdate` |
| List project tasks | `mcp__asdlc__list_tasks()` | `TaskList` |
| Track coding steps | `TodoWrite` (OK for this) | - |

---

## Notes

- All commands work from the project root directory
- Run `/sdlc:init` before using other commands
- Use `/sdlc:status` to see project overview