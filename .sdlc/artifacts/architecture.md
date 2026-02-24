# Architecture

## Component Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     User Interfaces                          │
│  ┌──────────┐  ┌───────────────┐  ┌───────────────────────┐ │
│  │  CLI     │  │  MCP Server   │  │  Web Dashboard (UI)   │ │
│  │ (Click)  │  │ (stdio/SSE)   │  │  (FastAPI + HTMX)     │ │
│  └────┬─────┘  └───────┬───────┘  └───────────┬───────────┘ │
│       │                │                       │             │
│       ▼                ▼                       ▼             │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │              HybridStorage Adapter                      │ │
│  │         (bridges Database + ContentManager)             │ │
│  └─────────────┬──────────────────────┬────────────────────┘ │
│                │                      │                      │
│       ┌────────▼────────┐   ┌────────▼─────────┐           │
│       │  Database       │   │  ContentManager   │           │
│       │  (SQLite v5)    │   │  (Markdown files)  │           │
│       └────────┬────────┘   └────────┬──────────┘           │
│                │                      │                      │
│       ~/.a-sdlc/data.db    ~/.a-sdlc/content/               │
└─────────────────────────────────────────────────────────────┘
                    │
          ┌─────────┼─────────┐
          ▼         ▼         ▼
   ┌──────────┐ ┌────────┐ ┌────────┐
   │  Linear  │ │  Jira  │ │ GitHub │
   │ (GraphQL)│ │(REST)  │ │(REST+  │
   │          │ │        │ │GraphQL)│
   └──────────┘ └────────┘ └────────┘
```

## Core Components

### 1. CLI (`cli.py`)

**Primary Responsibility**: Click-based command-line interface providing all user-facing commands for installation, configuration, monitoring, plugins, artifacts, PRDs, tasks, sprints, and external system connections.

**Key Functions/Commands**:
- `main()` — Click group entry point
- `serve()` — Start MCP server (stdio/SSE transport)
- `install()` — Deploy templates, configure MCP servers (Serena, monitoring, SonarQube)
- `uninstall()` — Remove all components with plan/execute pattern
- `setup_mcp()` — Configure Serena MCP in settings.json
- `doctor()` — System health check across all components
- `monitoring` group — `configure`, `start`, `stop`, `status`
- `sonarqube` group — `configure`, `scan`, `results`, `status`
- `plugins` group — `list`, `enable`, `configure`
- `artifacts` group — `status`, `push`, `pull`
- `prd` group — `list`, `show`, `pull`, `push`, `delete`, `update`, `split`
- `connect` group — `linear`, `jira`, `confluence`, `github`
- `disconnect` — Remove integrations
- `sync` group — `jira` (pull/push/status), `linear` (pull/push/status)
- `ui` group — Start/stop web dashboard
- `init` — Initialize project

**Internal Structure**: Single-file module organized by command sections with helper functions for display and business logic.

**Key Imports**: `click`, `rich` (Console, Table, Panel, Progress), `a_sdlc.installer`, `a_sdlc.mcp_setup`, `a_sdlc.monitoring_setup`, `a_sdlc.sonarqube_setup`, `a_sdlc.uninstall`, `a_sdlc.storage`

---

### 2. MCP Server (`server/__init__.py`)

**Primary Responsibility**: Exposes ~45 MCP tools for Claude Code agents to manage projects, PRDs, tasks, sprints, designs, and sync operations.

**Key Tool Groups**:
- **Context**: `get_context()`, `list_projects()`, `init_project()`, `switch_project()`, `relocate_project()`
- **PRD Operations**: `create_prd()`, `get_prd()`, `update_prd()`, `list_prds()`, `delete_prd()`
- **Design Operations**: `create_design()`, `get_design()`, `update_design()`, `delete_design()`, `list_designs()`
- **Task Operations**: `create_task()`, `get_task()`, `update_task()`, `list_tasks()`, `delete_task()`, `start_task()`, `complete_task()`, `block_task()`
- **Sprint Operations**: `create_sprint()`, `get_sprint()`, `start_sprint()`, `complete_sprint()`, `delete_sprint()`, `add_prd_to_sprint()`, `remove_prd_from_sprint()`, `get_sprint_prds()`, `get_sprint_tasks()`
- **Sync Operations**: `configure_linear()`, `configure_jira()`, `configure_confluence()`, `configure_github()`, `remove_integration()`, `get_integrations()`, `import_from_linear()`, `import_from_jira()`, `sync_sprint()`, `sync_sprint_to()`, `sync_sprint_from()`, `sync_prd()`, `sync_prd_to()`, `sync_prd_from()`, `list_sync_mappings()`
- **PRD Worktree**: `setup_prd_worktree()`, `cleanup_prd_worktree()`, `create_prd_pr()`
- **PR Feedback**: `get_pr_feedback()`
- **Linking**: `link_prd()`, `unlink_prd()`, `link_sprint()`, `unlink_sprint()`

**State Management**: Lazy singleton pattern via `get_db()`, `get_content_manager()`, `get_storage()`. Project context resolved from `os.getcwd()`.

**Data Handling**: Returns typed dictionaries with status codes. All tools include comprehensive docstrings that become the MCP tool descriptions.

---

### 3. Database (`core/database.py`)

**Primary Responsibility**: SQLite schema definition, versioned migrations (v1→v5), and all CRUD operations for projects, PRDs, tasks, sprints, designs, and sync mappings.

**Key Class**: `Database`
- Schema version 5 with automatic migration chain
- Tables: `projects`, `prds`, `tasks`, `sprints`, `designs`, `sync_mappings`
- Shortname generation with collision avoidance
- ID format: `{SHORTNAME}-{TYPE}{NUMBER}` (e.g., `SDLC-T00001`)
- Foreign key enforcement with cascade deletes
- Analytics queries: task completion trends, sprint velocity, lead/cycle times

**State Management**: Thread-local connection via `sqlite3.connect()` with WAL journal mode.

---

### 4. Content Manager (`core/content.py`)

**Primary Responsibility**: Markdown file I/O for PRDs, tasks, and designs in `~/.a-sdlc/content/{project_id}/`.

**Key Class**: `ContentManager`
- `write_content(project_id, entity_type, entity_id, content)` — Write markdown file
- `read_content(project_id, entity_type, entity_id)` — Read markdown file
- `delete_content(project_id, entity_type, entity_id)` — Delete markdown file
- `list_content(project_id, entity_type)` — List all files for entity type
- Directory creation on demand per project/entity type

---

### 5. HybridStorage (`storage/__init__.py`)

**Primary Responsibility**: Unified adapter bridging Database and ContentManager. All higher-level code uses HybridStorage rather than accessing DB or content files directly.

**Key Class**: `HybridStorage`
- PRD methods: `create_prd()`, `get_prd()`, `update_prd()`, `list_prds()`, `delete_prd()`
- Task methods: `create_task()`, `get_task()`, `update_task()`, `list_tasks()`, `delete_task()`
- Sprint methods: `create_sprint()`, `get_sprint()`, `list_sprints()`, `delete_sprint()`
- Design methods: `create_design()`, `get_design()`, `get_design_by_prd()`, `update_design()`, `delete_design()`, `list_designs()`
- Sync methods: `save_sync_mapping()`, `get_sync_mapping()`, `list_sync_mappings()`
- Analytics methods: `get_analytics()`

**Pattern**: File-first persistence — writes content file, then inserts/updates DB metadata with file path reference.

---

### 6. Sync Service (`server/sync.py`)

**Primary Responsibility**: Bidirectional synchronization between local sprints/PRDs and external systems (Linear, Jira, Confluence).

**Key Class**: `SyncService`
- Sprint sync: `sync_sprint()`, `sync_sprint_to()`, `sync_sprint_from()`, `import_sprint()`
- PRD sync: `sync_prd()`, `sync_prd_to()`, `sync_prd_from()`
- Uses plugin system to abstract external API differences
- Manages sync_mappings table for entity linkage and conflict detection

---

### 7. GitHub Client (`server/github.py`)

**Primary Responsibility**: GitHub REST and GraphQL API client for PR review comment retrieval and resolution status.

**Key Class**: `GitHubClient`
- `validate_token()` — Verify authentication
- `get_pr_for_branch()` — Find open PR for current branch
- `get_reviews()` — PR review summaries
- `get_review_comments()` — Line-level review comments (paginated)
- `get_issue_comments()` — General PR conversation comments
- `get_resolved_thread_ids()` — GraphQL query for resolved threads

**Helpers**: `parse_git_remote()`, `detect_git_info()`, `load_global_github_config()`, `save_global_github_config()`

---

### 8. Web Dashboard (`ui/__init__.py`)

**Primary Responsibility**: FastAPI web application providing a browser-based dashboard for PRD, task, and sprint management with analytics.

**Key Routes** (31 handlers):
- Home & project navigation
- CRUD views for PRDs, tasks, sprints
- Design document management
- Integration settings (Linear, Jira, Confluence, GitHub)
- Analytics with Chart.js visualizations
- HTMX-powered inline editing

**Process Management**: PID file at `~/.a-sdlc/ui.pid` with signal handling for graceful shutdown.

---

### 9. Plugin System (`plugins/`)

**Primary Responsibility**: Extensible backend for task storage and external system integration.

**Plugin Types**:
- `LocalPlugin` — File-based storage in `.sdlc/tasks/` and `.sdlc/sprints/`
- `LinearPlugin` — Linear Cloud integration via GraphQL
- `JiraPlugin` — Jira Cloud integration via REST API v3

**Base Interfaces**: `TaskPlugin` (abstract), `Task`, `Sprint`, `ExternalSprintMapping`, `ImplementationStep` (dataclasses)

**Configuration**: YAML-based with global (`~/.config/a-sdlc/config.yaml`) and project (`.sdlc/config.yaml`) layers with deep merge.

---

### 10. Artifact System (`artifacts/`)

**Primary Responsibility**: Generate, store, and publish documentation artifacts (architecture, data model, workflows, etc.).

**Plugin Types**:
- `LocalArtifactPlugin` — File storage in `.sdlc/artifacts/`
- `ConfluencePlugin` — Publish to Confluence Cloud with ADF conversion

**Supporting Modules**:
- `prd.py` — PRD data model with versioning and section management
- `prd_local.py` — Local PRD storage with metadata
- `task_generator.py` — AI prompt generation for task decomposition

---

### 11. Installer (`installer.py`)

**Primary Responsibility**: Deploy skill templates from package to `~/.claude/commands/sdlc/` and configure `asdlc` MCP server in `~/.claude.json`.

**Key Class**: `Installer`
- `install(force)` — Copy templates, configure MCP
- `uninstall()` — Remove templates directory
- `list_installed_skills()` — List deployed templates
- `get_mcp_server_config()` — Generate MCP server entry

---

### 12. Setup Modules

| Module | Purpose |
|--------|---------|
| `mcp_setup.py` | Serena MCP server configuration in settings.json |
| `monitoring_setup.py` | Langfuse + SigNoz Docker stack deployment |
| `sonarqube_setup.py` | SonarQube project configuration and scanning |
| `uninstall.py` | Build plan → execute removal of all components |
| `core/init_files.py` | Generate CLAUDE.md and lesson-learn.md from templates |

## Cross-Cutting Concerns

### Error Handling
- MCP tools return `{"status": "error", "message": "..."}` dictionaries
- CLI uses `click.echo()` + `sys.exit(1)` for errors
- UI returns HTML error responses via Jinja2 templates

### Configuration
- Three-tier config: global YAML → project YAML → environment variables
- Settings.json for Claude Code integration (MCP servers, hooks, env vars)

### Testing
- 16 test modules with 200+ tests
- `unittest.mock.patch` for all external dependencies
- In-memory SQLite for database tests
- Temporary directories for file system tests
