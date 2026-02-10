# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A-SDLC is an MCP server that provides SDLC (Software Development Lifecycle) management tools for PRDs, tasks, and sprints with external system integration (Linear, Jira). It also ships slash-command skill templates.

## Development Commands

```bash
# Setup
uv sync --all-extras

# Run all tests
uv run pytest tests/ -v

# Run a single test file
uv run pytest tests/test_cli.py -v

# Run a single test function
uv run pytest tests/test_cli.py::test_version -v

# Lint
uv run ruff check src/ tests/

# Type check
uv run mypy src/

# Format
uv run ruff format src/ tests/

# Dev install (editable mode, after code changes)
uv tool install --force --editable ".[all]"

# Reinstall skills only (after template changes)
a-sdlc install --force
```

All tests must pass before committing changes.

## Architecture

### High-Level Components

```
src/a_sdlc/
├── cli.py                # Click CLI entry point (a-sdlc command)
├── installer.py          # Deploys templates → ~/.claude/commands/sdlc/, MCP config → ~/.claude.json
├── server/__init__.py    # MCP server (@mcp.tool() decorators), started via `a-sdlc serve` / `uvx a-sdlc serve`
├── server/sync.py        # External sync service (Linear, Jira)
├── core/database.py      # SQLite schema and operations
├── core/content.py       # Markdown file management
├── storage/__init__.py   # HybridStorage adapter (bridges DB + content files)
├── plugins/              # Sync plugins: local.py, linear.py, jira.py (entry points in pyproject.toml)
├── artifacts/            # Artifact generation: scan → .sdlc/artifacts/
├── templates/            # Skill templates (~35 .md files, deployed to ~/.claude/commands/sdlc/)
└── artifact_templates/   # Mustache content templates (prd.template.md, task.template.md)
```

### Installer Flow

`a-sdlc install` (via `installer.py`):
1. Copies `src/a_sdlc/templates/*.md` → `~/.claude/commands/sdlc/`
2. Configures `asdlc` MCP server in `~/.claude.json` (command: `uvx a-sdlc serve`)

### Plugin System

Entry points defined in `pyproject.toml`:
- `a_sdlc.plugins`: `local`, `linear`, `jira` — sync plugins
- `a_sdlc.artifacts`: `local`, `confluence` — artifact publishing plugins

## Storage Architecture

### Hybrid Storage Model

```
~/.a-sdlc/                          # User-level storage (cross-project)
├── data.db                         # SQLite database (metadata + relationships)
└── content/                        # Markdown content files (source of truth)
    └── {project_id}/
        ├── prds/{prd_id}.md
        └── tasks/{task_id}.md

.sdlc/                              # Project-level (per repository)
├── artifacts/                      # Generated docs (5 standard artifacts)
├── .cache/checksums.json           # Scan metadata
└── config.yaml                     # Project-specific configuration
```

### Key Storage Rules

1. **Never reference `.sdlc/tasks/`** — Tasks are stored in `~/.a-sdlc/content/tasks/`
2. **Never reference `.sdlc/sprints/mappings.json`** — Mappings are in the database
3. **Always use MCP tools** — Don't read/write PRD/Task/Sprint files directly
4. **Artifacts stay in `.sdlc/`** — Generated docs belong with the project

## Entity Hierarchy

```
Sprint → PRD → Task
```

### Critical Relationship Rules

1. **Tasks inherit sprint membership through PRD** — Tasks do NOT have a direct `sprint_id` column
2. **PRDs can be optionally assigned to sprints** — `prd.sprint_id` is nullable
3. **Query sprint tasks via PRD join** — `WHERE prd_id IN (SELECT id FROM prds WHERE sprint_id = ?)`

### ID Formats

| Entity | Format | Example |
|--------|--------|---------|
| Project | 4-char uppercase shortname | `PCRA` |
| Task | `{shortname}-T{number:05d}` | `PCRA-T00001` |
| Sprint | `{shortname}-S{number:04d}` | `PCRA-S0001` |
| PRD | `{shortname}-P{number:04d}` | `PCRA-P0001` |

### Database Schema

```sql
projects (id, shortname UNIQUE, name, path UNIQUE, created_at, last_accessed)
prds (id, project_id FK, sprint_id FK nullable, title, file_path, status[draft|approved|split|completed], version)
tasks (id, project_id FK, prd_id FK, title, file_path, status[pending|in_progress|blocked|completed], priority[low|medium|high|critical], component)
sprints (id, project_id FK, title, goal, status[planned|active|completed], external_id)
sync_mappings (entity_type, local_id, external_system[linear|jira], external_id, sync_status[synced|pending|conflict|error])
```

## Template-Driven Workflows

Templates in `src/a_sdlc/templates/` are operational guides for Claude agents — they describe what MCP tools to call, in what order, and with what parameters.

| Template | Primary MCP Tools |
|----------|-------------------|
| `prd-generate.md` | `create_prd()` |
| `prd-split.md` | `get_prd()`, `create_task()` |
| `task-start.md` | `get_task()`, `update_task()` |
| `sprint-run.md` | `get_sprint()`, `get_task()`, `update_task()` |
| `sprint-sync.md` | `sync_sprint()`, `list_sync_mappings()` |

Content file generation: Agent generates markdown → calls MCP tool → tool inserts metadata into SQLite + writes content to `~/.a-sdlc/content/` + stores file_path in DB.

## MCP Tools Reference

### Context Tools
- `get_context()` — Current project + statistics
- `list_projects()` — All projects
- `init_project(name?, shortname?)` — Initialize project
- `relocate_project(shortname)` — Re-link project to current directory
- `switch_project(project_id)` — Switch project context

### PRD Tools
- `create_prd(title, content, sprint_id?)` — Creates PRD + content file
- `get_prd(prd_id)` — Returns metadata + content
- `update_prd(prd_id, ...)` — Updates fields + content
- `list_prds(sprint_id?, status?)` — Filter PRDs
- `delete_prd(prd_id)` — Removes PRD + content file

### Task Tools
- `create_task(prd_id, title, content, ...)` — Creates task + content file
- `get_task(task_id)` — Returns metadata + content (derives sprint from PRD)
- `update_task(task_id, status?, ...)` — Updates task
- `list_tasks(sprint_id?, prd_id?, status?)` — Filter tasks

### Sprint Tools
- `create_sprint(title, goal)` — Creates sprint
- `get_sprint(sprint_id)` — Returns sprint with PRD count
- `add_prd_to_sprint(prd_id, sprint_id)` — Links PRD to sprint
- `get_sprint_prds(sprint_id)` — All PRDs in sprint
- `get_sprint_tasks(sprint_id)` — All tasks (derived via PRDs)

### Sync Tools
- `configure_linear(api_key, team_id)` / `configure_jira(url, email, api_token, project_key)`
- `import_from_linear()` / `import_from_jira()` — Import cycles/sprints
- `sync_sprint(sprint_id)` — Bidirectional sync
- `sync_sprint_to(sprint_id)` / `sync_sprint_from(sprint_id)` — One-way sync
- `list_sync_mappings()` — View all mappings

## Key Workflows

1. **Init**: `/sdlc:init` → creates `.sdlc/`, registers project in DB with shortname
2. **Scan**: `/sdlc:scan` → analyzes codebase → generates 5 artifacts in `.sdlc/artifacts/`
3. **PRD**: `/sdlc:prd-generate` → interactive requirements → `create_prd()` → DB + content file
4. **Split**: `/sdlc:prd-split` → analyze PRD → propose tasks → user approves → `create_task()` for each
5. **Sprint**: `/sdlc:sprint-run` → get tasks via PRD join → build dependency graph → parallel execution
6. **Sync**: `/sdlc:sprint-sync` → `sync_sprint()` → create/update external issues → store sync mappings

## External System Sync

- **Linear**: GraphQL API, cycles as sprints
- **Jira**: REST API v3, sprints with ADF formatting
- Status mapping: pending↔Backlog/To Do, in_progress↔In Progress, blocked↔Blocked, completed↔Done

## Common Mistakes to Avoid

### Storage Mistakes
- **WRONG**: Reading tasks from `.sdlc/tasks/` → **RIGHT**: `get_task(task_id)` via MCP
- **WRONG**: Storing mappings in `.sdlc/sprints/mappings.json` → **RIGHT**: `sync_mappings` table via MCP
- **WRONG**: Writing PRD content directly to files → **RIGHT**: `create_prd()` which handles DB + file

### Hierarchy Mistakes
- **WRONG**: Adding `sprint_id` column to tasks → **RIGHT**: Tasks inherit sprint via PRD
- **WRONG**: Querying tasks directly by sprint_id → **RIGHT**: Join through PRDs

### Template Mistakes
- **WRONG**: Hardcoding file paths in templates → **RIGHT**: Using MCP tool calls that abstract storage
