# Architecture

## Component Overview

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                            User Interfaces                                   │
│                                                                              │
│  ┌──────────────┐  ┌─────────────────┐  ┌──────────────────┐  ┌──────────┐  │
│  │     CLI      │  │   MCP Server    │  │  Web Dashboard   │  │  Daemon  │  │
│  │   (Click)    │  │ (stdio/SSE/     │  │ (FastAPI + HTMX  │  │ (cron +  │  │
│  │  7205 lines  │  │  streamable-    │  │  + WebSocket)    │  │  PID)    │  │
│  │              │  │  http)          │  │  1751 lines      │  │ 694 lines│  │
│  └──────┬───────┘  └───────┬─────────┘  └────────┬─────────┘  └────┬─────┘  │
│         │                  │                      │                 │         │
│         ▼                  ▼                      ▼                 ▼         │
│  ┌───────────────────────────────────────────────────────────────────────┐    │
│  │                      Business Logic Layer                             │    │
│  │                                                                       │    │
│  │  ┌──────────────┐  ┌────────────────────┐  ┌──────────────────────┐   │    │
│  │  │   Executor   │  │ Orchestrator       │  │  External Sync       │   │    │
│  │  │  1881 lines  │  │ Prompts 1171 lines │  │  Service 1759 lines  │   │    │
│  │  └──────┬───────┘  └────────┬───────────┘  └──────────┬───────────┘   │    │
│  │         │                   │                         │               │    │
│  │         ▼                   │                         │               │    │
│  │  ┌──────────────┐           │                         │               │    │
│  │  │   Adapters   │           │                         │               │    │
│  │  │  (Claude,    │           │                         │               │    │
│  │  │   Gemini,    │           │                         │               │    │
│  │  │   Mock)      │           │                         │               │    │
│  │  │  848 lines   │           │                         │               │    │
│  │  └──────────────┘           │                         │               │    │
│  └─────────────────────────────┼─────────────────────────┼───────────────┘    │
│                                │                         │                    │
│         ┌──────────────────────┼─────────────────────────┘                    │
│         ▼                      ▼                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐    │
│  │                    HybridStorage Adapter (1582 lines)                  │    │
│  │              Unified facade for all data operations                    │    │
│  └───────────────┬──────────────────────────────┬────────────────────────┘    │
│                  │                              │                             │
│         ┌────────▼──────────┐          ┌────────▼───────────┐                │
│         │     Database      │          │  ContentManager    │                │
│         │  (SQLite v14)     │          │  (Markdown files)  │                │
│         │   5465 lines      │          │   669 lines        │                │
│         └────────┬──────────┘          └────────┬───────────┘                │
│                  │                              │                             │
│         ~/.a-sdlc/data.db            ~/.a-sdlc/content/                      │
└──────────────────────────────────────────────────────────────────────────────┘
                          │
                ┌─────────┼──────────┐
                ▼         ▼          ▼
         ┌──────────┐ ┌────────┐ ┌────────┐
         │  Linear  │ │  Jira  │ │ GitHub │
         │ (GraphQL)│ │(REST)  │ │(REST + │
         │          │ │        │ │GraphQL)│
         └──────────┘ └────────┘ └────────┘
```

## Layered Architecture

a-sdlc is structured as a six-layer system. Each layer depends only on the layers below it. The following sections describe each layer from the outermost (user-facing) to the innermost (data persistence).

---

### Layer 1: Entry Points

Four distinct entry points serve different interaction modes. All converge on the same business logic and storage layers.

#### CLI (`cli.py` -- 7205 lines)

Click-based command-line interface providing all user-facing commands for SDLC management.

**Command groups:**

| Group | Purpose | Example Commands |
|-------|---------|-----------------|
| `serve` | Start MCP server | `a-sdlc serve` (stdio, SSE, streamable-http) |
| `install` / `uninstall` | Deploy/remove templates and MCP config | `a-sdlc install --force` |
| `setup-mcp` | Configure Serena MCP in settings.json | `a-sdlc setup-mcp` |
| `doctor` | System health check across all components | `a-sdlc doctor` |
| `monitoring` | Langfuse + SigNoz Docker stack | `configure`, `start`, `stop`, `status` |
| `sonarqube` | SonarQube project scanning | `configure`, `scan`, `results`, `status` |
| `plugins` | Plugin management | `list`, `enable`, `configure` |
| `artifacts` | Generated documentation | `status`, `push`, `pull` |
| `prd` | PRD management | `list`, `show`, `pull`, `push`, `delete`, `update`, `split` |
| `connect` / `disconnect` | External system integration | `linear`, `jira`, `confluence`, `github` |
| `sync` | Bidirectional sync | `jira` / `linear` with `pull`, `push`, `status` |
| `ui` | Web dashboard process | `start`, `stop` |
| `run` | Background execution | `sprint`, `task`, `goal`, `status`, `logs`, `stop` |
| `agent` | Agent governance | `list`, `show`, `budget`, `retire` |
| `quality` | Quality feedback loop | `corrections`, `lessons`, `report` |

**Key dependencies:** `click`, `rich` (Console, Table, Panel, Progress)

#### MCP Server (`server/__init__.py` -- 498 lines)

FastMCP-based server registered as `asdlc`. Exposes MCP tools for Claude Code agents to manage the full SDLC lifecycle programmatically.

**Transport options:**

- **stdio** -- Default for Claude Code integration via `uvx a-sdlc serve`
- **SSE** -- Server-sent events for web clients
- **streamable-http** -- HTTP streaming transport

**State management:** Lazy singleton pattern via `get_db()`, `get_content_manager()`, `get_storage()`. Project context is resolved from `os.getcwd()`.

**Data access control:** All database access routes through `MCPDataAccess`, a transparent proxy that enforces an explicit allowlist of permitted operations (65 read operations, 33 write operations) and logs write activity for monitoring.

**Tool registration:** Tools are organized across submodules. Each submodule imports the server module and accesses shared state (`mcp`, `get_db()`, etc.) via module-attribute lookup at call time. This pattern preserves `@patch()` testability.

#### Web Dashboard (`ui/__init__.py` -- 1751 lines)

FastAPI application with Jinja2 templates providing a browser-based management interface.

**Capabilities:**

- CRUD views for PRDs, tasks, sprints, and designs
- Live pipeline run monitoring via WebSocket
- Analytics with Chart.js visualizations
- HTMX-powered inline editing
- SSE change detection for auto-refresh
- Integration settings management (Linear, Jira, Confluence, GitHub)

**Process management:** PID file at `~/.a-sdlc/ui.pid` with signal handling for graceful shutdown.

#### Daemon (`daemon.py` -- 694 lines)

Background process for scheduled and automated SDLC operations.

**Capabilities:**

- PID file management for single-instance enforcement
- Cron-like scheduling via `croniter`
- Graceful shutdown via POSIX signal handlers (SIGTERM, SIGINT)
- Auto-recovery for incomplete runs

---

### Layer 2: MCP Tool Modules (`server/`)

Each module registers `@mcp.tool()` decorators and handles request validation, error formatting, and response construction. All tools return typed dictionaries with status codes.

| Module | Lines | Responsibility | Key Tools |
|--------|------:|----------------|-----------|
| `project_tools.py` | 294 | Project context and initialization | `get_context`, `init_project`, `switch_project`, `relocate_project`, `list_projects` |
| `prd_tools.py` | 502 | PRD CRUD and lifecycle | `create_prd`, `get_prd`, `update_prd`, `list_prds`, `delete_prd` |
| `task_tools.py` | 346 | Task CRUD and status transitions | `create_task`, `get_task`, `update_task`, `list_tasks`, `delete_task` |
| `sprint_tools.py` | 498 | Sprint management and PRD assignment | `create_sprint`, `get_sprint`, `update_sprint`, `complete_sprint`, `manage_sprint_prds`, `get_sprint_prds`, `get_sprint_tasks` |
| `design_tools.py` | 120 | Design document management | `create_design`, `get_design`, `delete_design`, `list_designs` |
| `sync_tools.py` | 696 | External system synchronization | `manage_integration`, `import_from_linear`, `import_from_jira`, `sync_sprint`, `sync_prd`, `manage_sync_mapping`, `list_sync_mappings` |
| `review_tools.py` | 131 | Code review evidence | `submit_review`, `get_review_evidence` |
| `quality_tools.py` | 1124 | Quality gates and requirements | `log_correction`, `parse_requirements`, `verify_acceptance_criteria`, `get_quality_report` |
| `agent_tools.py` | 1041 | Agent governance and budgets | `manage_agent`, `check_permission`, `manage_agent_budget`, `auto_compose_team` |
| `execution_tools.py` | 475 | Background task execution | `build_execute_task_prompt`, `execute_task`, `check_execution`, `stop_execution` |
| `challenge_tools.py` | 501 | Adversarial artifact review | `challenge_artifact`, `record_challenge_round`, `get_challenge_status` |
| `worktree_tools.py` | 776 | Git worktree isolation | `setup_prd_worktree`, `cleanup_prd_worktree`, `create_prd_pr`, `manage_git_safety` |
| `github_tools.py` | 207 | GitHub PR feedback | `get_pr_feedback` |

**Supporting server modules:**

| Module | Lines | Purpose |
|--------|------:|---------|
| `data_access.py` | 162 | `MCPDataAccess` proxy -- operation allowlist enforcement |
| `sync.py` | 1759 | `LinearClient`, `JiraClient`, `ExternalSyncService` -- bidirectional sync coordination |
| `github.py` | 366 | `GitHubClient` -- REST and GraphQL API for PR reviews and comments |
| `challenge.py` | 123 | Challenge configuration loading |
| `governance_helpers.py` | 52 | Governance and routing config loaders |
| `quality_helpers.py` | 28 | Quality config safe-loading wrapper |

---

### Layer 3: Business Logic

#### Executor (`executor.py` -- 1881 lines)

The `Executor` class orchestrates sprint, task, and goal execution by spawning headless coding-agent sessions as subprocesses.

**Responsibilities:**

- Build prompts with task context, persona, and sprint state
- Spawn Claude Code or Gemini CLI sessions via Adapters
- Manage dependency ordering and parallel execution
- Track execution runs (start, progress, completion) in the database
- Enforce governance: budget checks, escalation rules, health monitoring
- Handle batching for sprint-level execution across multiple tasks

**Execution modes:**

- **Session** -- Sequential task execution within a single agent session
- **Parallel** -- Concurrent task execution with configurable concurrency

#### Orchestrator Prompts (`orchestrator_prompts.py` -- 1171 lines)

Builds structured prompts for multi-agent pipeline phases.

**Pipeline phases:**

| Phase | Persona | Purpose |
|-------|---------|---------|
| PM | Product Manager | Requirements gathering and PRD creation |
| Design | Architect | System design and technical specification |
| Split | Product Manager | PRD decomposition into tasks |
| Engineer | Backend/Frontend/DevOps | Implementation |
| QA | QA Engineer | Testing and validation |
| Challenger | Security Engineer | Adversarial review |

**Key components:**

- `ThreadContext` -- Manages artifact discussion threads with token budgets
- Persona loading from markdown frontmatter with project-level overrides
- Signal protocol for inter-agent communication
- Conversation log formatting with persona attribution
- Truncation with most-recent priority; user interventions are always preserved

#### Orchestrator (`orchestrator.py` -- 134 lines)

Entry point for `python -m a_sdlc.orchestrator`, spawned by `a-sdlc run goal`. Parses arguments (run ID, goal, max iterations) and delegates to `Executor`.

#### Adapters (`adapters.py` -- 848 lines)

Abstract base class `ExecutionAdapter` with `execute()` and `launch()` methods. Three concrete implementations:

| Adapter | CLI Command | Purpose |
|---------|-------------|---------|
| `ClaudeCodeAdapter` | `claude -p` | Production -- spawns Claude Code sessions |
| `GeminiAdapter` | `gemini -p` | Alternative -- spawns Gemini CLI sessions |
| `MockAdapter` | (none) | Testing -- no-op execution for test suites |

**Process lifecycle management:**

- Global process registry (`_active_processes`) tracks all launched subprocesses
- `atexit` hook sends SIGTERM to process groups, escalates to SIGKILL after 3 seconds
- PID reaping for dead processes
- ANSI escape code stripping from subprocess output
- Execution logs stored in `~/.a-sdlc/exec-logs/`

#### External Sync Service (`server/sync.py` -- 1759 lines)

Bidirectional synchronization between local SDLC entities and external project management systems.

**Client implementations:**

| Client | Protocol | Entity Mapping |
|--------|----------|----------------|
| `LinearClient` | GraphQL | Cycles as sprints, Issues as tasks |
| `JiraClient` | REST API v3 | Sprints as sprints, Issues as tasks |

**Sync directions:**

- **Push** -- Local changes propagated to external system
- **Pull** -- External changes imported to local storage
- **Bidirectional** -- Merge with conflict detection

**Status mapping:**

| Local Status | Linear | Jira |
|-------------|--------|------|
| `pending` | Backlog | To Do |
| `in_progress` | In Progress | In Progress |
| `blocked` | Blocked | Blocked |
| `completed` | Done | Done |

---

### Layer 4: Storage

#### HybridStorage (`storage/__init__.py` -- 1582 lines)

Unified facade combining Database and ContentManager. All higher-level code accesses data through HybridStorage rather than touching the database or content files directly.

**Pattern:** File-first persistence -- writes the content file first, then inserts or updates the database metadata with a file path reference.

**Entity methods:**

- **Projects** -- `create_project()`, `get_project()`, `list_projects()`, `update_project()`
- **PRDs** -- `create_prd()`, `get_prd()`, `update_prd()`, `list_prds()`, `delete_prd()`
- **Tasks** -- `create_task()`, `get_task()`, `update_task()`, `list_tasks()`, `delete_task()`
- **Sprints** -- `create_sprint()`, `get_sprint()`, `list_sprints()`, `delete_sprint()`
- **Designs** -- `create_design()`, `get_design()`, `update_design()`, `delete_design()`, `list_designs()`
- **Sync** -- `save_sync_mapping()`, `get_sync_mapping()`, `list_sync_mappings()`
- **Agents** -- Agent CRUD, budget management, task claiming
- **Analytics** -- `get_analytics()` for task completion trends, sprint velocity, lead/cycle times

**Consistency features:** Built-in consistency checking and repair capabilities for database-to-file synchronization.

#### Database (`core/database.py` -- 5465 lines)

SQLite database with 20+ tables, schema version 14, and a 14-step migration chain (v1 through v14) with backup/restore on failure.

**Core tables:**

```sql
projects     (id, shortname UNIQUE, name, path UNIQUE, created_at, last_accessed)
prds         (id, project_id FK, sprint_id FK nullable, title, file_path,
              status[draft|approved|split|completed], version)
tasks        (id, project_id FK, prd_id FK, title, file_path,
              status[pending|in_progress|blocked|completed],
              priority[low|medium|high|critical], component)
sprints      (id, project_id FK, title, goal,
              status[planned|active|completed], external_id)
designs      (id, project_id FK, prd_id FK, file_path, created_at)
sync_mappings(entity_type, local_id, external_system[linear|jira],
              external_id, sync_status[synced|pending|conflict|error])
```

**Extended tables (agents, execution, quality):**

```sql
agents            -- Agent registration, roles, status, permissions
agent_budgets     -- Token/cost budgets per agent
agent_messages    -- Inter-agent communication
work_queue        -- Task claims and assignment
execution_runs    -- Background run tracking (status, logs, timing)
audit_log         -- Operation audit trail
requirements      -- Parsed acceptance criteria
ac_verifications  -- Acceptance criteria verification records
reviews           -- Code review submissions and verdicts
challenge_records -- Adversarial review rounds
artifact_threads  -- Discussion thread context per artifact
worktrees         -- Git worktree isolation tracking
```

**Connection management:** Thread-local connection via `sqlite3.connect()` with WAL journal mode for concurrent read access.

**ID formats:**

| Entity | Format | Example |
|--------|--------|---------|
| Project | 4-char uppercase shortname | `PCRA` |
| Task | `{shortname}-T{number:05d}` | `PCRA-T00001` |
| Sprint | `{shortname}-S{number:04d}` | `PCRA-S0001` |
| PRD | `{shortname}-P{number:04d}` | `PCRA-P0001` |

#### ContentManager (`core/content.py` -- 669 lines)

Markdown file I/O for PRDs, tasks, designs, and objectives.

**File path convention:**

```
~/.a-sdlc/content/{project_id}/
    prds/{prd_id}.md
    tasks/{task_id}.md
    designs/{prd_id}.md
    objectives/{objective_id}.md
```

**Operations:**

- `write_content(project_id, entity_type, entity_id, content)` -- Write markdown file
- `read_content(project_id, entity_type, entity_id)` -- Read markdown file
- `delete_content(project_id, entity_type, entity_id)` -- Delete markdown file
- `list_content(project_id, entity_type)` -- List all files for an entity type
- Directory creation on demand per project and entity type

---

### Layer 5: Plugin System

#### Sync Plugins (`plugins/`)

Entry points defined in `pyproject.toml` under `a_sdlc.plugins`.

| Plugin | Backend | Protocol |
|--------|---------|----------|
| `LocalPlugin` | File-based storage | Local filesystem |
| `LinearPlugin` | Linear Cloud | GraphQL API |
| `JiraPlugin` | Jira Cloud | REST API v3 |

**Base interface:** `TaskPlugin` ABC defining `create_task()`, `get_task()`, `list_tasks()`, `update_task()`, `complete_task()`, `delete_task()`, and sprint management methods.

**Shared infrastructure:** `AtlassianClient` in `plugins/atlassian/` provides HTTP request handling for Jira and Confluence APIs.

#### Artifact Plugins (`artifacts/`)

Entry points defined in `pyproject.toml` under `a_sdlc.artifacts`.

| Plugin | Target | Format |
|--------|--------|--------|
| `LocalArtifactPlugin` | `.sdlc/artifacts/` | Markdown files with metadata |
| `ConfluencePlugin` | Confluence Cloud | ADF (Atlassian Document Format) |

**Supporting modules:**

- `prd.py` -- PRD data model with versioning and section management
- `prd_local.py` -- Local PRD storage with metadata tracking
- `task_generator.py` -- AI prompt generation for task decomposition
- `StorageToMarkdownConverter` / `MarkdownToADFConverter` -- Format translation

---

### Layer 6: Templates and Configuration

#### Skill Templates (`templates/` -- 47 files)

Slash command definitions for Claude Code agents, deployed to `~/.claude/commands/sdlc/` via `a-sdlc install`. Each template defines a workflow specifying which MCP tools to call, in what order, and with what parameters.

**Key workflows:**

| Template | Primary MCP Tools | Purpose |
|----------|-------------------|---------|
| `prd-generate.md` | `create_prd()` | Interactive requirements to PRD |
| `prd-split.md` | `get_prd()`, `create_task()` | PRD decomposition into tasks |
| `prd-architect.md` | `get_prd()`, `create_design()` | Technical design from PRD |
| `task-start.md` | `get_task()`, `update_task()` | Begin task implementation |
| `task-complete.md` | `update_task()`, `submit_review()` | Complete task with review |
| `sprint-run.md` | `get_sprint()`, `get_task()`, `update_task()` | Execute sprint tasks |
| `sprint-sync.md` | `sync_sprint()`, `list_sync_mappings()` | Sync with external systems |
| `sprint-complete.md` | `complete_sprint()` | Finish sprint with quality gates |
| `retrospective.md` | `log_correction()` | Corrections to lessons pipeline |
| `scan.md` | (filesystem) | Codebase analysis to artifacts |

#### Personas (`personas/` -- 7 files + `__init__.py`)

Role definitions loaded as markdown with structured frontmatter. Used by the orchestrator for persona-based task routing.

| Persona | File |
|---------|------|
| Architect | `sdlc-architect.md` |
| Backend Engineer | `sdlc-backend-engineer.md` |
| Frontend Engineer | `sdlc-frontend-engineer.md` |
| DevOps Engineer | `sdlc-devops-engineer.md` |
| Product Manager | `sdlc-product-manager.md` |
| QA Engineer | `sdlc-qa-engineer.md` |
| Security Engineer | `sdlc-security-engineer.md` |

#### Configuration System

**Configuration hierarchy (highest precedence first):**

1. Environment variables
2. Project-level YAML (`.sdlc/config.yaml`)
3. Global-level YAML (`~/.config/a-sdlc/config.yaml`)
4. Built-in defaults

**Config dataclasses:**

| Dataclass | Module | Sections |
|-----------|--------|----------|
| `QualityConfig` | `core/quality_config.py` (236 lines) | Testing, coverage, linting thresholds |
| `ReviewConfig` | `core/review_config.py` (132 lines) | Review requirements, approval rules |
| `GitSafetyConfig` | `core/git_config.py` (304 lines) | Auto-commit, auto-PR, auto-merge flags |
| `ChallengeConfig` | `server/challenge.py` (123 lines) | Adversarial review round limits |

**Template-driven config:** `config.yaml` template with sections for testing, review, quality, git, sprint, daemon, governance, orchestrator, and routing.

---

## Cross-Cutting Concerns

### Data Flow Patterns

#### Content Editing Pattern

PRD, design, and task content is managed via files, not MCP parameters:

1. **Create** -- `create_*(metadata)` returns `file_path`; agent writes content with the `Write` tool
2. **Read** -- `get_*(id)` returns `file_path` + content
3. **Edit content** -- Read `file_path`, then edit with the `Edit` tool (diff-based, token efficient)
4. **Update metadata** -- `update_*(id, status=...)` modifies the database only, never touches the file

#### Entity Hierarchy

```
Sprint --> PRD --> Task
```

- Tasks inherit sprint membership through their parent PRD
- PRDs can be optionally assigned to sprints (`prd.sprint_id` is nullable)
- Sprint task queries join through PRDs: `WHERE prd_id IN (SELECT id FROM prds WHERE sprint_id = ?)`

### Quality Gate System

```
corrections.log --> retrospective --> lesson-learn.md --> preflight checks
```

1. **Corrections Log** (`.sdlc/corrections.log`) -- Append-only log of all fixes. Format: `TIMESTAMP | CONTEXT:ID | CATEGORY | DESCRIPTION`
2. **Retrospective** (`/sdlc:sprint-complete`) -- Reads corrections, identifies patterns (2+ in same category), proposes lessons
3. **Lessons Learned** (`.sdlc/lesson-learn.md` + `~/.a-sdlc/lesson-learn.md`) -- Categorized rules with MUST/SHOULD/MAY priorities
4. **Preflight Checks** -- Lessons presented before work starts in `prd-split`, `task-start`, `sprint-run`
5. **Quality Gates** -- Completeness verification at `prd-split` (Step 5.5) and `task-complete` (DoD checklist)
6. **Acceptance Criteria** -- Requirements parsed and tracked in `requirements` and `ac_verifications` tables
7. **Challenge Rounds** -- Adversarial review per artifact via `challenge_tools`

### Agent Governance

The agent system provides multi-agent orchestration with guardrails:

- **Registration** -- Agents registered with roles and permissions via `manage_agent()`
- **Budget enforcement** -- Token and cost budgets tracked per agent via `manage_agent_budget()`
- **Permission checking** -- Operation allowlists per agent role via `check_permission()`
- **Team composition** -- Automatic team assembly based on task requirements via `auto_compose_team()`
- **Health monitoring** -- Executor checks agent health and triggers escalation rules

### Error Handling

| Layer | Strategy |
|-------|----------|
| MCP tools | Return `{"status": "error", "message": "..."}` dictionaries |
| CLI | `click.echo()` + `sys.exit(1)` |
| Web Dashboard | HTML error responses via Jinja2 templates |
| Database migrations | Backup before migration, restore on failure |
| Subprocess execution | SIGTERM with SIGKILL escalation, PID reaping |

### Monitoring and Observability

| System | Purpose | Integration |
|--------|---------|-------------|
| Langfuse | Trace analysis from Claude Code transcripts | Hook script in `monitoring_files/langfuse-hook.py` |
| SigNoz | OpenTelemetry-based observability | Docker stack via `monitoring_setup.py` |
| SonarQube | Static analysis and code quality | Project configuration via `sonarqube_setup.py` |
| Notifications | Post-execution alerts | Webhook + file hooks after execution runs |

### Git Integration

- **Worktree isolation** -- Optional per-PRD worktrees for parallel development (`worktree_tools.py`)
- **Git safety config** -- `auto_commit`, `auto_pr`, `auto_merge` flags with per-project overrides
- **PR creation** -- Automated PR generation from worktree branches
- **Cleanup** -- Worktree removal after PR merge or manual cleanup

### File System Layout

```
~/.a-sdlc/                           # User-level storage (cross-project)
├── data.db                          # SQLite database (metadata + relationships)
├── content/                         # Markdown content files (source of truth)
│   └── {project_id}/
│       ├── prds/{prd_id}.md
│       ├── tasks/{task_id}.md
│       ├── designs/{prd_id}.md
│       └── objectives/{id}.md
├── exec-logs/                       # Subprocess execution logs
├── ui.pid                           # Web dashboard PID file
└── lesson-learn.md                  # Global cross-project lessons

.sdlc/                               # Project-level (per repository)
├── artifacts/                       # Generated documentation (5 standard artifacts)
├── .cache/checksums.json            # Scan metadata
├── config.yaml                      # Project-specific configuration
├── corrections.log                  # Quality feedback loop entries
└── lesson-learn.md                  # Project-specific lessons

~/.claude/commands/sdlc/             # Deployed skill templates (47 files)
```

### Testing

- Test modules in `tests/` with 200+ test cases
- `unittest.mock.patch` for all external dependencies
- In-memory SQLite for database tests
- Temporary directories for filesystem tests
- `MCPDataAccess` proxy ensures MCP tools cannot run arbitrary database operations
