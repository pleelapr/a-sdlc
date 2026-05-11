# Codebase Summary

## Project Identity

| Field | Value |
|-------|-------|
| **Name** | a-sdlc |
| **Version** | 0.7.0 |
| **License** | MIT |
| **Python** | >=3.10 |
| **Build System** | Hatchling |
| **Package Manager** | uv |
| **Status** | Alpha (Development Status :: 3) |

## Overall Purpose and Domain

a-sdlc is an MCP (Model Context Protocol) server and CLI tool that provides Software Development Lifecycle management for AI coding assistants, primarily Claude Code and Gemini CLI. It manages PRDs (Product Requirement Documents), tasks, sprints, and design documents with external system integrations (Linear, Jira, Confluence, GitHub).

The system operates as a bridge between AI-assisted development workflows and traditional project management. It enables Claude Code agents to create, track, and execute structured development plans through slash-command skill templates, while providing pipeline orchestration for multi-agent execution with persona-based routing, governance, and budgets.

### Core Capabilities

- **PRD Management**: Create, version, review, and split Product Requirement Documents into actionable tasks
- **Task Tracking**: Generate tasks from PRDs, track status and priority, assign to agents by component
- **Sprint Planning**: Group PRDs into sprints, execute via autonomous agents with dependency ordering
- **External Sync**: Bidirectional synchronization with Linear (cycles) and Jira (sprints)
- **Quality Gates**: Acceptance criteria verification, challenge rounds, correction logging, and retrospectives
- **Pipeline Orchestration**: Multi-agent execution with persona-based routing, governance policies, and budgets
- **Web Dashboard**: FastAPI-based UI for monitoring sprints, tasks, PRDs, and pipeline runs

## Key Concepts and Domain Terminology

| Term | Definition |
|------|-----------|
| **PRD** | Product Requirement Document -- the primary planning artifact, versioned using SemVer |
| **Task** | Atomic unit of work derived from splitting a PRD, with priority, status, and component |
| **Sprint** | Time-boxed collection of PRDs and their derived tasks for iteration-based execution |
| **Design Document** | ADR-style architecture design linked 1:1 to a PRD |
| **Skill Template** | Markdown file defining a Claude Code slash command workflow (47 templates) |
| **MCP Tool** | Server-side function exposed via Model Context Protocol for agent interaction |
| **Artifact** | Generated documentation (architecture, data model, codebase summary, etc.) |
| **Hybrid Storage** | Pattern combining SQLite metadata/indexes with Markdown content files as source of truth |
| **Sync Mapping** | Linkage between local entities and external system identifiers (Linear, Jira) |
| **Shortname** | 4-character uppercase project identifier (e.g., `SDLC`) used as ID prefix |
| **Persona** | Role-based agent profile (architect, backend-engineer, QA, etc.) for task routing |
| **Challenge System** | Adversarial review rounds for quality gates and verification |
| **Correction Log** | Append-only log of mistakes that feeds into retrospectives and lesson-learn files |
| **Entity Hierarchy** | Sprint -> PRD -> Task (tasks inherit sprint membership through their parent PRD) |

## Technology Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **Language** | Python 3.10+ | Runtime and all application code |
| **Build System** | Hatchling | Package building and distribution |
| **Package Manager** | uv | Dependency management and virtual environments |
| **CLI Framework** | Click 8.1+ with Rich | Terminal interface and formatted output |
| **MCP Server** | FastMCP (mcp>=1.0.0) | Model Context Protocol server (stdio and SSE transport) |
| **Data Validation** | Pydantic v2 | Request/response models and configuration schemas |
| **Database** | SQLite | Metadata storage (schema v14, 14 migration versions) |
| **Web UI** | FastAPI + Uvicorn + Jinja2 | Dashboard for monitoring and management |
| **HTTP Client** | httpx | Linear GraphQL, Jira REST v3, Confluence, GitHub APIs |
| **Configuration** | PyYAML | YAML-based project and global configuration |
| **Observability** | Langfuse (traces) + SigNoz (OpenTelemetry) | Conversation tracing and metrics |
| **Code Quality** | SonarQube (optional) | Static analysis integration |
| **Testing** | pytest 8.0+ | 2654 tests across 55 test files |
| **Linting** | ruff | Style checking and import sorting |
| **Type Checking** | mypy | Static type verification |
| **CI/CD** | GitHub Actions | 4 workflows: ci, lint, release, smoke-test |

## Data Persistence and State Management

### Hybrid Storage Model

The system uses a dual-storage architecture that separates metadata from content.

**User-level storage** (`~/.a-sdlc/`):

- `data.db` -- SQLite database storing metadata, relationships, and indexes (schema v14)
- `content/{project_id}/prds/{prd_id}.md` -- PRD content files
- `content/{project_id}/tasks/{task_id}.md` -- Task content files
- `content/{project_id}/designs/{prd_id}.md` -- Design document content files
- `lesson-learn.md` -- Global cross-project lessons

**Project-level storage** (`.sdlc/` per repository):

- `artifacts/` -- Generated documentation (5 standard artifacts)
- `.cache/checksums.json` -- Scan metadata cache
- `config.yaml` -- Project-specific configuration
- `corrections.log` -- Append-only correction entries
- `lesson-learn.md` -- Project-specific lessons

### Content Editing Pattern

MCP tools handle metadata (database), while files handle content (Markdown). The pattern is:

1. `create_*()` returns a `file_path`
2. The agent writes content using the Write tool
3. `update_*()` modifies metadata only (status, priority, etc.)
4. Content edits go directly to the Markdown file using the Edit tool

### Entity Hierarchy and ID Formats

```
Project (SDLC)
  +-- Sprint (SDLC-S0001)
        +-- PRD (SDLC-P0001) -- has optional Design
              +-- Task (SDLC-T00001)
```

Tasks inherit sprint membership through their parent PRD. Tasks do NOT have a direct `sprint_id` column.

| Entity | Format | Example |
|--------|--------|---------|
| Project | 4-char uppercase shortname | `PCRA` |
| Sprint | `{shortname}-S{number:04d}` | `PCRA-S0001` |
| PRD | `{shortname}-P{number:04d}` | `PCRA-P0001` |
| Task | `{shortname}-T{number:05d}` | `PCRA-T00001` |

### Database Schema (v14)

Core tables: `projects`, `prds`, `tasks`, `sprints`, `designs`, `sync_mappings`, `agents`, `execution_runs`, `work_queue`, `artifact_threads`, `requirements`, `challenge_records`, `schema_version`, and supporting tables.

Key status enumerations:

- **PRD status**: draft, approved, split, completed
- **Task status**: pending, in_progress, blocked, completed
- **Sprint status**: planned, active, completed
- **Task priority**: low, medium, high, critical
- **Sync status**: synced, pending, conflict, error

## Entry Points

| Command | Module | Description |
|---------|--------|-------------|
| `a-sdlc` | `src/a_sdlc/cli.py:main()` | Click CLI entry point |
| `a-sdlc serve` | `src/a_sdlc/server/__init__.py:run_server()` | MCP server (stdio or SSE) |
| `a-sdlc ui` | `src/a_sdlc/ui/__init__.py:run_server()` | Web dashboard (FastAPI) |
| `a-sdlc daemon start` | `src/a_sdlc/daemon.py:run_daemon()` | Background daemon process |
| `a-sdlc install` | `src/a_sdlc/installer.py` | Template and MCP config deployment |

## Plugin System

Entry points defined in `pyproject.toml` enable extensible sync and artifact publishing.

**Sync plugins** (`a_sdlc.plugins`):

| Plugin | Module | Purpose |
|--------|--------|---------|
| local | `a_sdlc.plugins.local:LocalPlugin` | Local-only task management (no external sync) |
| linear | `a_sdlc.plugins.linear:LinearPlugin` | Linear GraphQL API sync (cycles as sprints) |
| jira | `a_sdlc.plugins.jira:JiraPlugin` | Jira REST v3 API sync (sprints with ADF formatting) |

**Artifact plugins** (`a_sdlc.artifacts`):

| Plugin | Module | Purpose |
|--------|--------|---------|
| local | `a_sdlc.artifacts.local:LocalArtifactPlugin` | Local file system artifact generation |
| confluence | `a_sdlc.artifacts.confluence:ConfluencePlugin` | Confluence REST API publishing |

Both plugin types use an abstract base class (`TaskPlugin` and `ArtifactPlugin` respectively) for consistent interfaces.

## External Dependencies and APIs

| System | Protocol | Purpose |
|--------|----------|---------|
| **Linear** | GraphQL API | Bidirectional cycle and issue synchronization |
| **Jira** | REST API v3 | Bidirectional sprint and issue sync with ADF formatting |
| **Confluence** | REST API v3 | PRD and artifact publishing |
| **GitHub** | REST API | PR review comment retrieval and processing |
| **SonarQube** | REST API | Code quality scanning and analysis |
| **Langfuse** | HTTP hooks | Conversation tracing and observability |
| **SigNoz** | OpenTelemetry | Metrics and distributed tracing |

Status mapping for external sync:

- `pending` maps to Backlog / To Do
- `in_progress` maps to In Progress
- `blocked` maps to Blocked
- `completed` maps to Done

## Persona System

Seven role-based agent profiles in `src/a_sdlc/personas/` provide specialized behavior for task routing:

| Persona | File | Focus |
|---------|------|-------|
| Architect | `sdlc-architect.md` | System design and architecture decisions |
| Backend Engineer | `sdlc-backend-engineer.md` | Server-side implementation |
| Frontend Engineer | `sdlc-frontend-engineer.md` | Client-side implementation |
| DevOps Engineer | `sdlc-devops-engineer.md` | Infrastructure and deployment |
| QA Engineer | `sdlc-qa-engineer.md` | Testing and quality assurance |
| Security Engineer | `sdlc-security-engineer.md` | Security analysis and hardening |
| Product Manager | `sdlc-product-manager.md` | Requirements and prioritization |

## Configuration

| File | Scope | Purpose |
|------|-------|---------|
| `.sdlc/config.yaml` | Project | Testing, review, quality, sprint, daemon, governance, orchestrator, routing, git settings |
| `~/.claude.json` | Global | MCP server registration (auto-configured by `a-sdlc install`) |
| `~/.claude/commands/sdlc/` | Global | Deployed skill templates (47 files) |
| `~/.config/a-sdlc/config.yaml` | Global | Plugin configurations (Linear, Jira, GitHub API keys) |
| `~/.claude/settings.json` | Global | Serena config, hooks, environment variables |

## Quality Gate System

The quality feedback loop captures corrections, distills them into lessons, and enforces them via preflight checks.

```
corrections.log --> retrospective --> lesson-learn.md --> preflight checks
```

1. **Corrections Log** (`.sdlc/corrections.log`) -- Append-only log of all fixes, format: `TIMESTAMP | CONTEXT:ID | CATEGORY | DESCRIPTION`
2. **Retrospective** (`/sdlc:sprint-complete`) -- Reads corrections, identifies patterns (2+ in same category), proposes lessons
3. **Lessons Learned** (`.sdlc/lesson-learn.md` + `~/.a-sdlc/lesson-learn.md`) -- Categorized rules with MUST/SHOULD/MAY priorities
4. **Preflight Checks** -- Lessons presented before work starts in prd-split, task-start, sprint-run
5. **Quality Gates** -- Completeness verification at prd-split (Step 5.5) and task-complete (DoD checklist)

## MCP Server Tool Categories

The MCP server exposes tools organized across multiple modules in `src/a_sdlc/server/`:

| Module | Tool Category | Key Tools |
|--------|--------------|-----------|
| `project_tools.py` | Context and Projects | `get_context`, `init_project`, `list_projects`, `switch_project`, `relocate_project` |
| `prd_tools.py` | PRD Management | `create_prd`, `get_prd`, `update_prd`, `list_prds`, `delete_prd` |
| `design_tools.py` | Design Documents | `create_design`, `get_design`, `delete_design`, `list_designs` |
| `task_tools.py` | Task Management | `create_task`, `get_task`, `update_task`, `list_tasks` |
| `sprint_tools.py` | Sprint Management | `create_sprint`, `get_sprint`, `update_sprint`, `complete_sprint`, `manage_sprint_prds`, `get_sprint_prds`, `get_sprint_tasks` |
| `sync_tools.py` | External Sync | `manage_integration`, `import_from_linear`, `import_from_jira`, `sync_sprint`, `sync_prd`, `manage_sync_mapping`, `list_sync_mappings` |
| `review_tools.py` | Code Review | `submit_review`, `get_review_evidence` |
| `quality_tools.py` | Quality Gates | `log_correction` |
| `execution_tools.py` | Pipeline Execution | Orchestrator and daemon management tools |
| `agent_tools.py` | Agent Management | Agent registration and status tools |
| `challenge_tools.py` | Challenge System | Adversarial review round tools |
| `github_tools.py` | GitHub Integration | PR review comment processing tools |
| `worktree_tools.py` | Git Worktrees | Git worktree management for parallel execution |

## Skill Templates

47 skill templates in `src/a_sdlc/templates/` define slash-command workflows for Claude Code agents. These are deployed to `~/.claude/commands/sdlc/` during installation.

Key workflow templates:

| Template | Primary MCP Tools | Purpose |
|----------|-------------------|---------|
| `init.md` | `init_project()` | Initialize a-sdlc in a repository |
| `scan.md` | File analysis | Analyze codebase, generate artifacts |
| `prd-generate.md` | `create_prd()` | Interactive requirements gathering and PRD creation |
| `prd-architect.md` | `get_prd()`, `create_design()` | Architecture design from PRD |
| `prd-split.md` | `get_prd()`, `create_task()` | Split PRD into implementation tasks |
| `task-start.md` | `get_task()`, `update_task()` | Begin work on a task |
| `task-complete.md` | `update_task()`, `submit_review()` | Complete task with DoD verification |
| `sprint-run.md` | `get_sprint()`, `get_task()`, `update_task()` | Execute sprint with dependency ordering |
| `sprint-sync.md` | `sync_sprint()`, `list_sync_mappings()` | Sync sprint with external systems |
| `sprint-complete.md` | `complete_sprint()` | Complete sprint with quality gate checks |
| `retrospective.md` | Correction log analysis | Review corrections, extract lessons |

## Installation and Deployment

```
uv tool install a-sdlc[all]         # Install package with all extras
a-sdlc install                       # Deploy templates and MCP config
a-sdlc install --with-serena         # Include Serena MCP for code analysis
a-sdlc install --with-monitoring     # Include Langfuse/SigNoz stack
```

The installer (`src/a_sdlc/installer.py`) performs two actions:

1. Copies `src/a_sdlc/templates/*.md` to `~/.claude/commands/sdlc/`
2. Configures the `asdlc` MCP server in `~/.claude.json` (command: `uvx a-sdlc serve`)

## Testing

- **Framework**: pytest 8.0+
- **Test count**: 2654 tests across 55 test files
- **Location**: `tests/` directory
- **Tools**: ruff (linting), mypy (type checking)
- **CI**: GitHub Actions with 4 workflows (ci, lint, release, smoke-test)

Run commands:

```
uv run pytest tests/ -v              # Run all tests
uv run ruff check src/ tests/        # Lint
uv run mypy src/                     # Type check
uv run ruff format src/ tests/       # Format
```
