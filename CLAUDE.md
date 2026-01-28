# A-SDLC Project Context

This document provides essential context for AI agents working with the a-sdlc codebase. It covers architecture, workflows, and critical rules that must be followed.

## Project Overview

A-SDLC is an MCP server that provides SDLC (Software Development Lifecycle) management tools for PRDs, tasks, and sprints with external system integration (Linear, Jira).

## Storage Architecture

### Hybrid Storage Model

The system uses a **hybrid storage architecture** combining SQLite metadata with markdown content files:

```
~/.a-sdlc/                          # User-level storage (cross-project)
├── data.db                         # SQLite database (metadata + relationships)
└── content/                        # Markdown content files (source of truth)
    └── {project_id}/               # Project-first organization
        ├── prds/                   # PRD content files
        │   └── {prd_id}.md
        └── tasks/                  # Task content files
            └── {task_id}.md

.sdlc/                              # Project-level (per repository)
├── artifacts/                      # Generated documentation artifacts
│   ├── directory-structure.md
│   ├── codebase-summary.md
│   ├── architecture.md
│   ├── data-model.md
│   └── key-workflows.md
├── .cache/                         # Checksums and scan metadata
│   └── checksums.json
└── config.yaml                     # Project-specific configuration
```

### Why Hybrid Storage?

- **SQLite** (`data.db`): Fast queries, relationships, filtering, ID generation
- **Markdown files** (`content/`): Git-friendly, human-readable, LLM-optimized
- **Project artifacts** (`.sdlc/`): Repository-specific, versioned with code

### Key Storage Rules

1. **Never reference `.sdlc/tasks/`** - Tasks are stored in `~/.a-sdlc/content/tasks/`
2. **Never reference `.sdlc/sprints/mappings.json`** - Mappings are in the database
3. **Always use MCP tools** - Don't read/write files directly for PRDs/Tasks/Sprints
4. **Artifacts stay in `.sdlc/`** - Generated docs belong with the project

## Entity Hierarchy

### Sprint → PRD → Task

```
Sprint (container for a development cycle)
└── PRD (requirements document)
    └── Task (atomic implementation unit)
```

### Critical Relationship Rules

1. **Tasks inherit sprint membership through PRD** - Tasks do NOT have a direct `sprint_id` column
2. **PRDs can be optionally assigned to sprints** - `prd.sprint_id` is nullable
3. **Query sprint tasks via PRD join** - `SELECT * FROM tasks WHERE prd_id IN (SELECT id FROM prds WHERE sprint_id = ?)`

### Database Schema (Simplified)

```sql
projects (
    id TEXT PRIMARY KEY,
    shortname TEXT UNIQUE NOT NULL,  -- 4-char uppercase (e.g., "PCRA")
    name TEXT NOT NULL,
    path TEXT NOT NULL UNIQUE,
    created_at, last_accessed
)

prds (
    id TEXT PRIMARY KEY,             -- Format: {shortname}-P{number:04d}
    project_id TEXT REFERENCES projects(id),
    sprint_id TEXT REFERENCES sprints(id),  -- Nullable!
    title TEXT,
    file_path TEXT,  -- Points to ~/.a-sdlc/content/prds/...
    status TEXT,     -- draft, approved, split, completed
    version TEXT
)

tasks (
    id TEXT PRIMARY KEY,             -- Format: {shortname}-T{number:05d}
    project_id TEXT REFERENCES projects(id),
    prd_id TEXT REFERENCES prds(id),  -- Parent PRD
    title TEXT,
    file_path TEXT,  -- Points to ~/.a-sdlc/content/tasks/...
    status TEXT,     -- pending, in_progress, blocked, completed
    priority TEXT,   -- low, medium, high, critical
    component TEXT
)

sprints (
    id TEXT PRIMARY KEY,             -- Format: {shortname}-S{number:04d}
    project_id TEXT REFERENCES projects(id),
    title TEXT,
    goal TEXT,
    status TEXT,     -- planned, active, completed
    external_id TEXT -- For sync mappings
)

sync_mappings (
    entity_type TEXT,       -- 'sprint', 'task', 'prd'
    local_id TEXT,
    external_system TEXT,   -- 'linear', 'jira'
    external_id TEXT,
    sync_status TEXT        -- synced, pending, conflict, error
)
```

### Project Shortnames (Jira-style Project Keys)

Each project has a **4-character uppercase shortname** that uniquely identifies it across all projects. This shortname is used as a prefix for all entity IDs, making them compact and human-readable.

**ID Format**:
| Entity | Format | Example |
|--------|--------|---------|
| Task | `{shortname}-T{number:05d}` | `PCRA-T00001` |
| Sprint | `{shortname}-S{number:04d}` | `PCRA-S0001` |
| PRD | `{shortname}-P{number:04d}` | `PCRA-P0001` |

**Shortname Rules**:
- Exactly 4 characters
- Uppercase letters only (A-Z)
- Must be unique across all projects
- Auto-generated from project name if not specified (prefers consonants)

**Benefits**:
- Compact IDs that fit in conversations and external systems
- Repository-independent (can relocate projects)
- Jira-compatible format for integrations

## Template-Driven Workflows

### How Templates Work

Templates in `src/a_sdlc/templates/` are **operational guides** for Claude agents. They describe:
- What MCP tools to call
- In what order
- With what parameters
- Expected outputs

### Template → MCP Tool Mapping

| Template | Primary MCP Tools |
|----------|-------------------|
| `prd-generate.md` | `mcp__asdlc__create_prd()` |
| `prd-split.md` | `mcp__asdlc__get_prd()`, `mcp__asdlc__create_task()` |
| `task-start.md` | `mcp__asdlc__get_task()`, `mcp__asdlc__update_task()` |
| `sprint-run.md` | `mcp__asdlc__get_sprint()`, `mcp__asdlc__get_task()`, `mcp__asdlc__update_task()` |
| `sprint-sync.md` | `mcp__asdlc__sync_sprint()`, `mcp__asdlc__list_sync_mappings()` |

### Content File Generation Flow

When creating PRDs or Tasks:

```
1. Agent follows template instructions
2. Agent generates markdown content (using artifact templates)
3. Agent calls MCP tool with content
4. MCP tool:
   a. Inserts metadata into SQLite
   b. Writes content to ~/.a-sdlc/content/{project_id}/{type}/{id}.md
   c. Stores file_path in database row
5. Later retrieval: MCP tool reads file_path, returns content
```

## Artifact System

### Five Standard Artifacts

Generated by `/sdlc:scan` and stored in `.sdlc/artifacts/`:

1. **directory-structure.md** - File tree with descriptions
2. **codebase-summary.md** - Tech stack, dependencies, overview
3. **architecture.md** - Components, layers, patterns
4. **data-model.md** - Entities, relationships, schemas
5. **key-workflows.md** - Core processes, data flows

### Using Artifacts for PRD/Task Generation

When generating PRDs or tasks, artifacts provide context:

```
architecture.md → Identifies components for task assignment
data-model.md → Provides entity context for implementation
key-workflows.md → Shows integration points and dependencies
```

### Artifact Templates

Located in `src/a_sdlc/artifact_templates/`:

- `prd.template.md` - Mustache template for PRD structure
- `task.template.md` - Detailed task template with implementation steps

Template variables use `{{VARIABLE}}` syntax (Mustache-style).

## Task Content Architecture

### Flexible, User-Configurable Design

The task system uses a flexible architecture where:

- **Database stores metadata only**: id, title, status, priority, component, file_path
- **Markdown files store content**: Full task details in user-defined format
- **Templates are guidance, not enforcement**: Agent follows template, but no code validates format

### Task Template Customization

Users can customize the task format by creating:
```
.sdlc/templates/task.template.md
```

The agent will read this template and generate task content following its structure.

Default template provides:
- Goal, Implementation Context, Files to Modify
- Key Requirements, Technical Notes
- Deliverables, Exclusions
- Implementation Steps with code hints and tests
- Success Criteria, Scope Constraints

### Why This Design?

1. **Flexibility**: Teams can define their own task structure
2. **No schema lock-in**: Content format can evolve without code changes
3. **LLM-friendly**: Agent generates markdown, system just stores it
4. **Git-friendly**: Markdown files version well, easy to review

### Data Flow

```
1. Agent reads task template (default or custom)
2. Agent generates markdown content following template
3. Agent calls split_prd(prd_id, task_specs=[{title, description=full_content, ...}])
4. System stores:
   - Metadata → SQLite database
   - Content → ~/.a-sdlc/content/{project}/tasks/{task_id}.md
5. Retrieval joins metadata + file content
```

### Template Structure Reference

The default `task.template.md` structure:

```markdown
# {{TASK_ID}}: {{TASK_TITLE}}

**Status:** {{STATUS}}
**Priority:** {{PRIORITY}}
**Component:** {{COMPONENT}}
**Dependencies:** {{DEPENDENCIES}}
**PRD Reference:** {{PRD_REF}}

## Goal
{{GOAL}}

## Implementation Context
### Files to Modify
### Key Requirements
### Technical Notes

## Scope Definition
### Deliverables
### Exclusions

## Implementation Steps
(Numbered steps with code hints and tests)

## Success Criteria
(Checkboxes derived from acceptance criteria)

## Scope Constraint
(What NOT to do)
```

## External System Sync

### Supported Systems

- **Linear** - GraphQL API, cycles as sprints
- **Jira** - REST API v3, sprints with ADF formatting

### Sync Architecture

```
Local Sprint ←→ Sync Mapping ←→ External Sprint (Linear Cycle / Jira Sprint)
    ↓                              ↓
Local Tasks ←→ Sync Mapping ←→ External Issues
```

### Sync Mapping Storage

All sync mappings are stored in `sync_mappings` table in SQLite:

```sql
-- NOT in .sdlc/sprints/mappings.json!
SELECT * FROM sync_mappings WHERE local_id = 'SPRINT-001';
```

### Status Mapping

| Local Status | Linear Status | Jira Status |
|--------------|---------------|-------------|
| pending | Backlog | To Do |
| in_progress | In Progress | In Progress |
| blocked | Blocked | Blocked |
| completed | Done | Done |

### Priority Mapping

| Local Priority | Linear Priority | Jira Priority |
|----------------|-----------------|---------------|
| critical | 1 (Urgent) | Highest |
| high | 2 (High) | High |
| medium | 3 (Medium) | Medium |
| low | 4 (Low) | Low |

## MCP Tools Reference

### Context Tools
- `get_context()` - Current project + statistics (includes shortname)
- `list_projects()` - All projects (includes shortname for each)
- `init_project(name?, shortname?)` - Initialize project with optional shortname
- `relocate_project(shortname)` - Re-link existing project to current directory
- `switch_project(project_id)` - Switch to different project context

### PRD Tools
- `create_prd(title, content, sprint_id?)` - Creates PRD + content file
- `get_prd(prd_id)` - Returns metadata + content
- `update_prd(prd_id, ...)` - Updates fields + content
- `list_prds(sprint_id?, status?)` - Filter PRDs
- `delete_prd(prd_id)` - Removes PRD + content file

### Task Tools
- `create_task(prd_id, title, content, ...)` - Creates task + content file
- `get_task(task_id)` - Returns metadata + content (derives sprint from PRD)
- `update_task(task_id, status?, ...)` - Updates task
- `list_tasks(sprint_id?, prd_id?, status?)` - Filter tasks
- `list_tasks_by_sprint(sprint_id)` - All sprint tasks via PRD join

### Sprint Tools
- `create_sprint(title, goal)` - Creates sprint
- `get_sprint(sprint_id)` - Returns sprint with PRD count
- `assign_prd_to_sprint(prd_id, sprint_id)` - Links PRD to sprint
- `get_sprint_prds(sprint_id)` - All PRDs in sprint
- `get_sprint_tasks(sprint_id)` - All tasks (derived via PRDs)

### Sync Tools
- `configure_linear(api_key, team_id)` - Set Linear config
- `configure_jira(url, email, api_token, project_key)` - Set Jira config
- `import_from_linear()` / `import_from_jira()` - Import cycles/sprints
- `sync_sprint(sprint_id)` - Bidirectional sync
- `sync_sprint_to(sprint_id)` - Push local → external
- `sync_sprint_from(sprint_id)` - Pull external → local
- `list_sync_mappings()` - View all mappings

## Key Workflows

### 1. Initialize Project

```
/sdlc:init [shortname=XXXX]
↓
Creates .sdlc/ directory structure
↓
Registers project in database with shortname
↓
Returns shortname and ID format examples

Example output:
  Project 'my-project' initialized with shortname 'MYPR'
  ID formats: MYPR-T00001 (task), MYPR-S0001 (sprint), MYPR-P0001 (PRD)
```

### Relocating Projects

If you move a repository to a new location:
```
cd /new/path/to/project
/sdlc:relocate MYPR
↓
Updates project path in database
↓
All existing data (PRDs, tasks, sprints) remains linked
```

### 2. Scan Codebase

```
/sdlc:scan
↓
Analyzes codebase (uses Serena MCP for symbol analysis)
↓
Generates 5 artifacts in .sdlc/artifacts/
↓
Creates checksums in .sdlc/.cache/
```

### 3. Generate PRD

```
/sdlc:prd-generate "Feature description"
↓
Interactive requirements gathering
↓
Uses prd.template.md structure
↓
mcp__asdlc__create_prd() → DB + ~/.a-sdlc/content/{project}/prds/
```

### 4. Split PRD into Tasks

```
/sdlc:prd-split "prd-id"
↓
Phase 1: Interactive - analyze PRD, propose tasks, refine
↓
Phase 2: Atomic - user approves
↓
mcp__asdlc__create_task() for each → DB + ~/.a-sdlc/content/{project}/tasks/
↓
PRD status → "split"
```

### 5. Execute Sprint

```
/sdlc:sprint-run SPRINT-001
↓
Get sprint tasks (via PRD join)
↓
Build dependency graph (ready vs blocked)
↓
Launch parallel Task agents (max 3 concurrent)
↓
Monitor completion, unblock dependent tasks
↓
mcp__asdlc__update_task() for each completion
```

### 6. Sync to External System

```
/sdlc:sprint-sync SPRINT-001
↓
mcp__asdlc__sync_sprint()
↓
For each task: create/update external issue
↓
Store sync mapping in database
↓
Update sync_status to "synced"
```

## Development Best Practices

### When Generating Tasks

1. **Use artifacts for context** - Read architecture.md, data-model.md
2. **Follow granularity levels**:
   - Coarse (3-5 tasks): High-level feature chunks
   - Medium (5-10 tasks): Balanced breakdown (default)
   - Fine (10-20 tasks): Detailed implementation steps
3. **Include implementation steps with code hints**
4. **Define clear success criteria**
5. **Specify scope constraints (what NOT to do)**

### When Executing Tasks

1. **Fetch full task via MCP** - `mcp__asdlc__get_task(task_id)`
2. **Follow implementation steps exactly**
3. **Run tests before marking complete**
4. **Update status via MCP** - `mcp__asdlc__update_task(task_id, status="completed")`

### When Syncing

1. **Configure integration first** - `configure_linear()` or `configure_jira()`
2. **Use sync mappings table** - Never file-based mappings
3. **Handle conflicts** - Use strategy parameter (local-wins, external-wins)
4. **Check sync status** - `list_sync_mappings()` shows sync health

## Common Mistakes to Avoid

### Storage Mistakes

- **WRONG**: Reading tasks from `.sdlc/tasks/active/TASK-001.json`
- **RIGHT**: `mcp__asdlc__get_task(task_id="TASK-001")`

- **WRONG**: Storing mappings in `.sdlc/sprints/mappings.json`
- **RIGHT**: Using `sync_mappings` table via MCP tools

- **WRONG**: Writing PRD content directly to files
- **RIGHT**: Using `mcp__asdlc__create_prd()` which handles both DB + file

### Hierarchy Mistakes

- **WRONG**: Adding `sprint_id` column to tasks table
- **RIGHT**: Tasks inherit sprint membership through PRD relationship

- **WRONG**: Querying tasks directly by sprint_id
- **RIGHT**: Join through PRDs: `WHERE prd_id IN (SELECT id FROM prds WHERE sprint_id = ?)`

### Template Mistakes

- **WRONG**: Hardcoding file paths in templates
- **RIGHT**: Using MCP tool calls that abstract storage

## File Reference

### Core Implementation

```
src/a_sdlc/
├── core/
│   ├── database.py       # SQLite schema and operations
│   └── content.py        # Markdown file management
├── storage/
│   └── __init__.py       # HybridStorage adapter
├── server/
│   ├── __init__.py       # MCP tool definitions
│   └── sync.py           # External sync service
├── plugins/
│   ├── base.py           # Plugin interface
│   ├── local.py          # Local-only plugin
│   ├── linear.py         # Linear integration
│   └── jira.py           # Jira integration
├── artifacts/
│   ├── __init__.py       # Artifact plugin manager
│   └── task_generator.py # PRD → Task generation
├── templates/            # Command operation guides (35 files)
└── artifact_templates/   # Mustache content templates
```

### Test Files

```
tests/
├── test_file_storage.py  # Storage layer tests
├── test_external_sync.py # Sync integration tests
├── test_plugins.py       # Plugin tests
└── ...
```

## Running Tests

```bash
uv run pytest tests/ -v
```

All 148 tests should pass before committing changes.
