# Directory Structure

> **Version**: 0.7.0 | **Generated**: 2026-05-11 | **Type**: Living document (regenerate with `/sdlc:scan`)

## Repository Structure

```
a-sdlc/
├── .github/workflows/                    # CI/CD pipelines
│   ├── ci.yml                            # Main CI: tests + type checks
│   ├── lint.yml                          # Linting (ruff)
│   ├── release.yml                       # PyPI release automation
│   └── smoke-test.yml                    # Post-install smoke tests
│
├── .sdlc/                                # Project-level SDLC metadata
│   ├── .cache/                           # Scan checksums (gitignored)
│   │   └── checksums.json
│   ├── artifacts/                        # Generated living documentation
│   │   ├── architecture.md
│   │   ├── codebase-summary.md
│   │   ├── data-model.md
│   │   ├── directory-structure.md        # This file
│   │   └── key-workflows.md
│   ├── config.yaml                       # Project-specific configuration
│   ├── corrections.log                   # Quality correction log (append-only)
│   └── lesson-learn.md                   # Project-specific lessons learned
│
├── src/a_sdlc/                           # Main Python package
│   ├── __init__.py                       # Package root, version export
│   │
│   │  ── Top-Level Modules ──────────────────────────────────────────
│   │
│   ├── cli.py                            # Click CLI entry point (7205 lines)
│   │                                     #   `a-sdlc` command with subcommands:
│   │                                     #   serve, install, uninstall, scan, run, ui
│   ├── cli_targets.py                    # CLI target detection (Claude, Gemini)
│   ├── adapters.py                       # Execution adapters (Claude, Gemini, Mock) - 848 lines
│   ├── executor.py                       # Sprint/task/objective execution engine - 1881 lines
│   ├── orchestrator.py                   # Pipeline orchestrator entry point
│   ├── orchestrator_prompts.py           # Prompt builders for multi-agent pipeline - 1171 lines
│   ├── daemon.py                         # Background daemon (cron scheduling, PID mgmt) - 694 lines
│   ├── installer.py                      # Template + persona installer -> ~/.claude/
│   ├── gemini_extension.py               # Gemini CLI extension builder
│   ├── notifications.py                  # Webhook + file notification hooks
│   ├── transpiler.py                     # Template -> TOML transpiler
│   ├── mcp_setup.py                      # Serena MCP setup utilities
│   ├── playwright_setup.py               # Playwright MCP setup
│   ├── monitoring_setup.py               # Docker-based monitoring stack setup
│   ├── sonarqube_setup.py                # SonarQube config + scanner - 745 lines
│   └── uninstall.py                      # System cleanup utility
│   │
│   │  ── Core Infrastructure ────────────────────────────────────────
│   │
│   ├── core/                             # Core data layer and configuration
│   │   ├── __init__.py
│   │   ├── database.py                   # SQLite schema + CRUD operations - 5465 lines
│   │   │                                 #   14 migrations, 6 tables, full query API
│   │   ├── content.py                    # ContentManager: markdown file I/O - 669 lines
│   │   ├── config_loader.py              # YAML config loading
│   │   ├── init_files.py                 # Project initialization file generators
│   │   ├── git_config.py                 # GitSafetyConfig
│   │   ├── quality_config.py             # QualityConfig, ChallengeConfig
│   │   └── review_config.py              # ReviewConfig
│   │
│   │  ── Storage Abstraction ────────────────────────────────────────
│   │
│   ├── storage/                          # Hybrid storage adapter
│   │   └── __init__.py                   # HybridStorage (DB + ContentManager) - 1582 lines
│   │                                     #   Bridges SQLite metadata with markdown content files
│   │
│   │  ── MCP Server ─────────────────────────────────────────────────
│   │
│   ├── server/                           # MCP server tools (20 modules)
│   │   ├── __init__.py                   # FastMCP init, server bootstrap - 490+ lines
│   │   │                                 #   Tool registration, middleware, lifespan
│   │   │
│   │   │  ── CRUD Tool Modules ──
│   │   ├── project_tools.py              # Project context MCP tools
│   │   ├── prd_tools.py                  # PRD CRUD MCP tools - 502 lines
│   │   ├── task_tools.py                 # Task CRUD MCP tools
│   │   ├── sprint_tools.py               # Sprint CRUD MCP tools
│   │   ├── design_tools.py               # Design document MCP tools
│   │   │
│   │   │  ── Execution & Review ──
│   │   ├── execution_tools.py            # Task execution MCP tools
│   │   ├── review_tools.py               # Review evidence MCP tools
│   │   ├── agent_tools.py                # Agent governance MCP tools - 1041 lines
│   │   │
│   │   │  ── Quality & Governance ──
│   │   ├── quality_tools.py              # Quality gate MCP tools - 1124 lines
│   │   ├── quality_helpers.py            # Quality config helpers
│   │   ├── challenge.py                  # Challenge detection + status
│   │   ├── challenge_tools.py            # Challenge MCP tools
│   │   ├── governance_helpers.py         # Routing + health config loaders
│   │   │
│   │   │  ── External Integrations ──
│   │   ├── sync.py                       # Linear + Jira sync clients - 1759 lines
│   │   ├── sync_tools.py                 # Sync MCP tools - 696 lines
│   │   ├── github.py                     # GitHub client (PR review comments)
│   │   ├── github_tools.py               # PR feedback MCP tool
│   │   ├── worktree_tools.py             # Git worktree MCP tools - 776 lines
│   │   │
│   │   │  ── Internal Services ──
│   │   └── data_access.py               # MCPDataAccess proxy
│   │
│   │  ── Sync Plugins ───────────────────────────────────────────────
│   │
│   ├── plugins/                          # External system sync plugins (entry points)
│   │   ├── __init__.py                   # PluginManager (discovery + config)
│   │   ├── base.py                       # TaskPlugin ABC, Task/Sprint data models, enums
│   │   ├── local.py                      # LocalPlugin: file-based fallback - 649 lines
│   │   ├── linear.py                     # LinearPlugin: GraphQL API - 584 lines
│   │   ├── jira.py                       # JiraPlugin: REST API v3 - 656 lines
│   │   └── atlassian/                    # Shared Atlassian Cloud client
│   │       ├── __init__.py
│   │       ├── auth.py                   # API token authentication
│   │       └── client.py                 # HTTP client with retry logic
│   │
│   │  ── Artifact Management ────────────────────────────────────────
│   │
│   ├── artifacts/                        # Artifact generation and publishing
│   │   ├── __init__.py                   # ArtifactPluginManager
│   │   ├── base.py                       # ArtifactType, Artifact, ArtifactPlugin (ABC)
│   │   ├── local.py                      # LocalArtifactPlugin
│   │   ├── confluence.py                 # Confluence integration (ADF conversion) - 1688 lines
│   │   ├── prd.py                        # PRD model, version bumping, section mgmt
│   │   ├── prd_local.py                  # LocalPRDPlugin
│   │   └── task_generator.py             # AI prompt builder for task generation
│   │
│   │  ── Content Templates ──────────────────────────────────────────
│   │
│   ├── artifact_templates/               # Mustache content templates (12 files)
│   │   ├── prd.template.md               # PRD skeleton
│   │   ├── task.template.md              # Task skeleton
│   │   ├── architecture.template.md      # Architecture artifact template
│   │   ├── codebase-summary.template.md  # Codebase summary artifact template
│   │   ├── data-model.template.md        # Data model artifact template
│   │   ├── directory-structure.template.md # Directory structure artifact template
│   │   ├── key-workflows.template.md     # Key workflows artifact template
│   │   ├── requirements.template.md      # Requirements artifact template
│   │   ├── claude-md.template.md         # CLAUDE.md generator template
│   │   ├── gemini-md.template.md         # Gemini GEMINI.md generator template
│   │   ├── config.template.yaml          # Project config template
│   │   └── lesson-learn.template.md      # Lesson-learn file template
│   │
│   │  ── Slash Command Templates ────────────────────────────────────
│   │
│   ├── templates/                        # Skill templates (47 .md files)
│   │   │                                 #   Deployed to ~/.claude/commands/sdlc/
│   │   │
│   │   │  ── Core Commands ──
│   │   ├── init.md                       # Project initialization
│   │   ├── scan.md                       # Repository scanning
│   │   ├── help.md                       # Command reference
│   │   ├── ask.md                        # Q&A about repository
│   │   ├── ideate.md                     # Brainstorming workflow
│   │   ├── investigate.md                # Root cause analysis
│   │   ├── test.md                       # Test generation
│   │   ├── retrospective.md             # Sprint retrospective
│   │   ├── _round-table-blocks.md       # Shared round-table discussion blocks
│   │   │
│   │   │  ── PRD Commands ──
│   │   ├── prd.md                        # PRD overview
│   │   ├── prd-generate.md               # PRD creation
│   │   ├── prd-architect.md              # ADR design document generation
│   │   ├── prd-split.md                  # PRD to tasks decomposition
│   │   ├── prd-update.md                 # PRD modification
│   │   ├── prd-import.md                 # PRD import from external source
│   │   ├── prd-investigate.md            # PRD investigation
│   │   ├── prd-list.md                   # PRD listing
│   │   └── prd-delete.md                 # PRD deletion
│   │   │
│   │   │  ── Task Commands ──
│   │   ├── task.md                       # Task overview
│   │   ├── task-create.md                # Manual task creation
│   │   ├── task-start.md                 # Task execution
│   │   ├── task-complete.md              # Task completion with DoD checklist
│   │   ├── task-split.md                 # Task subdivision
│   │   ├── task-list.md                  # Task listing
│   │   ├── task-show.md                  # Task detail view
│   │   ├── task-delete.md                # Task deletion
│   │   └── task-link.md                  # Task linking
│   │   │
│   │   │  ── Sprint Commands ──
│   │   ├── sprint.md                     # Sprint overview
│   │   ├── sprint-create.md              # Sprint creation
│   │   ├── sprint-start.md               # Sprint activation
│   │   ├── sprint-run.md                 # Sprint execution
│   │   ├── sprint-complete.md            # Sprint completion with quality gates
│   │   ├── sprint-list.md                # Sprint listing
│   │   ├── sprint-show.md                # Sprint detail view
│   │   ├── sprint-delete.md              # Sprint deletion
│   │   │
│   │   │  ── Sprint Sync Commands ──
│   │   ├── sprint-sync.md                # Bidirectional sync
│   │   ├── sprint-sync-to.md             # Push to external system
│   │   ├── sprint-sync-from.md           # Pull from external system
│   │   ├── sprint-import.md              # External sprint import
│   │   ├── sprint-link.md                # Link to external sprint
│   │   ├── sprint-unlink.md              # Unlink from external sprint
│   │   ├── sprint-mappings.md            # Sync mapping viewer
│   │   │
│   │   │  ── Integration Commands ──
│   │   ├── pr-feedback.md                # PR review comment processor
│   │   ├── sonar-scan.md                 # SonarQube integration
│   │   ├── publish.md                    # Artifact publishing
│   │   ├── status.md                     # Artifact freshness check
│   │   └── update.md                     # Incremental artifact updates
│   │
│   │  ── Agent Personas ─────────────────────────────────────────────
│   │
│   ├── personas/                         # Agent persona templates (7 .md files)
│   │   ├── __init__.py
│   │   ├── sdlc-architect.md             # Solution architect persona
│   │   ├── sdlc-backend-engineer.md      # Backend engineer persona
│   │   ├── sdlc-devops-engineer.md       # DevOps engineer persona
│   │   ├── sdlc-frontend-engineer.md     # Frontend engineer persona
│   │   ├── sdlc-product-manager.md       # Product manager persona
│   │   ├── sdlc-qa-engineer.md           # QA engineer persona
│   │   └── sdlc-security-engineer.md     # Security engineer persona
│   │
│   │  ── Web Dashboard ──────────────────────────────────────────────
│   │
│   ├── ui/                               # FastAPI web dashboard
│   │   ├── __init__.py                   # Routes, WebSocket, SSE - 1751 lines
│   │   │                                 #   ~31 route handlers, real-time updates
│   │   └── templates/                    # Jinja2 HTML templates (16 files + partials)
│   │       ├── base.html                 # Master layout (dark theme, nav, utilities)
│   │       ├── home.html                 # Cross-project overview
│   │       ├── dashboard.html            # Per-project dashboard
│   │       ├── prds.html                 # PRD list view
│   │       ├── prd_detail.html           # PRD detail (4 tabs)
│   │       ├── tasks.html                # Task list view
│   │       ├── task_detail.html          # Task detail view
│   │       ├── sprints.html              # Sprint list view
│   │       ├── sprint_detail.html        # Sprint detail view
│   │       ├── pipeline_runs.html        # Pipeline run history
│   │       ├── run_detail.html           # Individual run detail
│   │       ├── analytics.html            # Metrics dashboard (Chart.js)
│   │       ├── settings.html             # Integration settings
│   │       ├── no_project.html           # No project state
│   │       ├── onboarding.html           # First-run onboarding
│   │       ├── work_item_card.html       # Work item card component
│   │       └── partials/                 # Reusable template fragments
│   │           ├── integration_card.html
│   │           ├── integration_form.html
│   │           └── thread_viewer.html
│   │
│   │  ── Monitoring Files ───────────────────────────────────────────
│   │
│   └── monitoring_files/                 # Bundled monitoring configs
│       └── langfuse-hook.py              # Langfuse transcript processing + trace creation
│
│  ── Tests ──────────────────────────────────────────────────────────
│
├── tests/                                # Test suite (54 files)
│   ├── __init__.py
│   ├── conftest.py                       # Shared fixtures
│   │
│   │  ── Core Tests ──
│   ├── test_cli.py                       # CLI command tests
│   ├── test_cli_pipeline.py              # CLI pipeline tests
│   ├── test_cli_targets.py               # CLI target detection tests
│   ├── test_file_storage.py              # HybridStorage tests
│   ├── test_init_files.py                # Init file generation tests
│   ├── test_content_objective.py         # Content objective tests
│   ├── test_database_v14.py              # Database migration v14 tests
│   │
│   │  ── Server Tests ──
│   ├── test_server.py                    # MCP server tool tests
│   ├── test_agent_tools.py               # Agent tools tests
│   ├── test_agent_governance.py          # Agent governance tests
│   ├── test_agent_org.py                 # Agent organization tests
│   ├── test_data_access.py               # Data access proxy tests
│   ├── test_governance_enforcement.py    # Governance enforcement tests
│   ├── test_routing_teams.py             # Routing team tests
│   │
│   │  ── Execution Tests ──
│   ├── test_executor.py                  # Executor tests
│   ├── test_executor_objective.py        # Objective execution tests
│   ├── test_adapters.py                  # Execution adapter tests
│   ├── test_orchestrator.py              # Pipeline orchestrator tests
│   ├── test_orchestrator_prompts.py      # Prompt builder tests
│   ├── test_daemon.py                    # Background daemon tests
│   ├── test_work_pickup.py               # Work pickup tests
│   ├── test_work_queue_db.py             # Work queue database tests
│   ├── test_thread_context.py            # Thread context tests
│   │
│   │  ── Quality & Review Tests ──
│   ├── test_quality.py                   # Quality gate tests
│   ├── test_quality_config.py            # Quality config tests
│   ├── test_challenge.py                 # Challenge system tests
│   ├── test_review_config.py             # Review config tests
│   ├── test_reviews_db.py                # Reviews database tests
│   │
│   │  ── Feature Tests ──
│   ├── test_design.py                    # Design document tests
│   ├── test_enhanced_run_status.py       # Enhanced run status tests
│   ├── test_run_goal_answer.py           # Run goal answer tests
│   ├── test_prd_update.py                # PRD update tests
│   ├── test_task_generator.py            # Task generation tests
│   ├── test_notifications.py             # Notification tests
│   ├── test_worktree_db.py               # Worktree database tests
│   │
│   │  ── Plugin & Integration Tests ──
│   ├── test_plugins.py                   # Plugin system tests
│   ├── test_external_sync.py             # External sync tests
│   ├── test_pr_feedback.py               # PR feedback tests
│   ├── test_git_config.py                # Git config tests
│   │
│   │  ── Setup & Infrastructure Tests ──
│   ├── test_mcp_setup.py                 # Serena MCP setup tests
│   ├── test_monitoring_setup.py          # Monitoring setup tests
│   ├── test_playwright_setup.py          # Playwright setup tests
│   ├── test_sonarqube_setup.py           # SonarQube setup tests
│   ├── test_gemini_extension.py          # Gemini extension tests
│   ├── test_transpiler.py                # Transpiler tests
│   ├── test_uninstall.py                 # Uninstall tests
│   │
│   │  ── UI Tests ──
│   ├── test_ui.py                        # UI route tests
│   ├── test_ui_pipeline.py               # UI pipeline tests
│   │
│   │  ── Template Tests ──
│   ├── test_sprint_run_template.py       # Sprint run template tests
│   ├── test_prd_architect_template.py    # PRD architect template tests
│   ├── test_prd_generate_template.py     # PRD generate template tests
│   └── test_prd_split_template.py        # PRD split template tests
│
│  ── Supporting Directories ─────────────────────────────────────────
│
├── example-artifacts/                    # Example scan output for documentation
│   ├── architecture.md
│   ├── codebase-summary.md
│   ├── data-model.md
│   ├── directory-structure.md
│   ├── key-workflows.md
│   ├── requirements.md
│   └── task.md
│
├── monitoring/                           # Observability stack (deployed)
│   ├── docker-compose.yaml               # Langfuse + SigNoz services
│   ├── langfuse-hook.py                  # Conversation hook script
│   ├── langfuse.env                      # Langfuse environment variables
│   ├── logs/                             # Monitoring logs
│   └── signoz/                           # SigNoz submodule (OpenTelemetry)
│
├── logs/                                 # Runtime log outputs
│
│  ── Project Configuration ──────────────────────────────────────────
│
├── CLAUDE.md                             # Claude Code project instructions
├── COMMAND_REFERENCE.md                  # CLI command documentation
├── DEPLOYMENT_GUIDE.md                   # Deployment instructions
├── IMPLEMENTATION_SUMMARY.md             # Implementation notes
├── pyproject.toml                        # Project metadata + dependencies (hatchling build)
├── uv.lock                              # Dependency lock file
└── Dockerfile.test                       # Test container definition
```

## Directory Purpose Guide

| Directory | Purpose | Audience |
|-----------|---------|----------|
| `src/a_sdlc/core/` | Data layer: SQLite schema, markdown I/O, config loading | Core contributors |
| `src/a_sdlc/storage/` | Hybrid storage adapter bridging database and content files | Core contributors |
| `src/a_sdlc/server/` | MCP server tools exposed to Claude Code agents | Server/tool developers |
| `src/a_sdlc/plugins/` | External system sync (Linear, Jira, local fallback) | Integration developers |
| `src/a_sdlc/artifacts/` | Artifact generation, publishing, Confluence integration | Artifact system developers |
| `src/a_sdlc/templates/` | Slash command skill templates deployed to `~/.claude/` | Template authors |
| `src/a_sdlc/personas/` | Agent persona definitions for multi-agent pipeline | Pipeline developers |
| `src/a_sdlc/artifact_templates/` | Mustache content templates for generated files | Template authors |
| `src/a_sdlc/ui/` | FastAPI web dashboard with Jinja2 templates | UI developers |
| `tests/` | Comprehensive test suite covering all subsystems | All contributors |
| `.sdlc/` | Project-level SDLC metadata and generated artifacts | Project maintainers |
| `monitoring/` | Docker-based observability stack (Langfuse, SigNoz) | DevOps |

## Key File Relationships

```
cli.py ──> executor.py ──> adapters.py ──> Claude/Gemini CLI
  │              │
  │              └──> orchestrator.py ──> orchestrator_prompts.py
  │
  └──> installer.py ──> templates/*.md ──> ~/.claude/commands/sdlc/
                    └──> personas/*.md ──> ~/.claude/commands/sdlc/personas/

server/__init__.py ──> *_tools.py ──> storage/__init__.py ──> core/database.py
                                                          └──> core/content.py

plugins/__init__.py ──> local.py / linear.py / jira.py ──> plugins/base.py
                                    └──> atlassian/client.py

artifacts/__init__.py ──> local.py / confluence.py ──> artifacts/base.py
```

## Runtime File Locations

| Path | Created By | Purpose |
|------|-----------|---------|
| `~/.a-sdlc/data.db` | `init_project()` | SQLite database (metadata + relationships) |
| `~/.a-sdlc/content/{project}/prds/` | `create_prd()` | PRD markdown content files |
| `~/.a-sdlc/content/{project}/tasks/` | `create_task()` | Task markdown content files |
| `~/.a-sdlc/lesson-learn.md` | `a-sdlc install` | Global cross-project lessons |
| `~/.claude/commands/sdlc/` | `a-sdlc install` | Deployed slash command templates |
| `~/.claude.json` | `a-sdlc install` | MCP server configuration |
| `.sdlc/config.yaml` | `/sdlc:init` | Per-project configuration |
| `.sdlc/artifacts/` | `/sdlc:scan` | Generated living documentation |
| `.sdlc/corrections.log` | `log_correction()` | Append-only quality correction log |
| `.sdlc/lesson-learn.md` | `/sdlc:init` | Project-specific lessons |

## Summary

| Category | Count | Details |
|----------|-------|---------|
| **Total files in repository** | ~6,334 | Including all source, tests, templates, and assets |
| **Python source files** | 65 | ~42,109 lines of code in `src/a_sdlc/` |
| **Python test files** | 54 | ~46,594 lines of code in `tests/` (2,653 tests) |
| **Slash command templates** | 47 | Markdown skill files deployed to `~/.claude/commands/sdlc/` |
| **Agent persona templates** | 7 | Role-based persona definitions for multi-agent pipeline |
| **Artifact content templates** | 12 | Mustache templates for generated content files |
| **UI HTML templates** | 16 + 3 partials | Jinja2 templates for FastAPI web dashboard |
| **CI/CD workflows** | 4 | GitHub Actions: CI, lint, release, smoke test |
| **MCP server modules** | 20 | Tool modules in `src/a_sdlc/server/` |
| **Sync plugins** | 3 | Local, Linear (GraphQL), Jira (REST v3) |
| **Artifact plugins** | 2 | Local filesystem, Confluence (ADF) |

### Largest Modules by Line Count

| Module | Lines | Responsibility |
|--------|-------|----------------|
| `cli.py` | 7,205 | CLI entry point with all subcommands |
| `core/database.py` | 5,465 | SQLite schema, 14 migrations, full CRUD |
| `executor.py` | 1,881 | Sprint and task execution engine |
| `server/sync.py` | 1,759 | Linear + Jira sync clients |
| `ui/__init__.py` | 1,751 | FastAPI dashboard routes and WebSocket |
| `artifacts/confluence.py` | 1,688 | Confluence publishing with ADF conversion |
| `storage/__init__.py` | 1,582 | HybridStorage adapter |
| `orchestrator_prompts.py` | 1,171 | Multi-agent pipeline prompt builders |
| `server/quality_tools.py` | 1,124 | Quality gate MCP tools |
| `server/agent_tools.py` | 1,041 | Agent governance MCP tools |
