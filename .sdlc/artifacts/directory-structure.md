# Directory Structure

## Repository Structure

```
a-sdlc/
├── CLAUDE.md                          # Claude Code project instructions
├── COMMAND_REFERENCE.md               # CLI command documentation
├── DEPLOYMENT_GUIDE.md                # Deployment guide
├── IMPLEMENTATION_SUMMARY.md          # Implementation summary
├── pyproject.toml                     # Python project config (hatchling build)
├── uv.lock                           # Dependency lock file
│
├── src/a_sdlc/                        # Main Python package
│   ├── __init__.py                    # Package init (version)
│   ├── cli.py                         # Click CLI entry point (~3800 lines)
│   ├── installer.py                   # Template & MCP server installer
│   ├── mcp_setup.py                   # Serena MCP setup utilities
│   ├── monitoring_setup.py            # Langfuse + SigNoz monitoring setup
│   ├── sonarqube_setup.py             # SonarQube integration setup
│   ├── uninstall.py                   # System cleanup & uninstall logic
│   │
│   ├── core/                          # Core data layer
│   │   ├── __init__.py
│   │   ├── database.py                # SQLite schema (v5), migrations, CRUD
│   │   ├── content.py                 # Markdown file management
│   │   └── init_files.py              # CLAUDE.md & lesson-learn generators
│   │
│   ├── storage/                       # Storage abstraction
│   │   └── __init__.py                # HybridStorage adapter (DB + files)
│   │
│   ├── server/                        # MCP server
│   │   ├── __init__.py                # MCP tool definitions (~45 tools)
│   │   ├── sync.py                    # External sync service (Linear, Jira)
│   │   └── github.py                  # GitHub API client (REST + GraphQL)
│   │
│   ├── plugins/                       # Sync plugins
│   │   ├── __init__.py                # PluginManager (discovery + config)
│   │   ├── base.py                    # Abstract interfaces + data models
│   │   ├── local.py                   # File-based task/sprint storage
│   │   ├── linear.py                  # Linear GraphQL integration
│   │   ├── jira.py                    # Jira REST API v3 integration
│   │   └── atlassian/                 # Shared Atlassian Cloud client
│   │       ├── __init__.py
│   │       ├── auth.py                # API token authentication
│   │       └── client.py              # HTTP client with retry logic
│   │
│   ├── artifacts/                     # Artifact management
│   │   ├── __init__.py                # ArtifactPluginManager
│   │   ├── base.py                    # Abstract interfaces + models
│   │   ├── local.py                   # File-based artifact storage
│   │   ├── confluence.py              # Confluence publishing (ADF conversion)
│   │   ├── prd.py                     # PRD data model + versioning
│   │   ├── prd_local.py               # File-based PRD storage
│   │   └── task_generator.py          # AI-assisted task generation
│   │
│   ├── templates/                     # Skill templates (~40 .md files)
│   │   ├── help.md                    # Command reference
│   │   ├── init.md                    # Project initialization
│   │   ├── scan.md                    # Repository scanning
│   │   ├── ask.md                     # Q&A about repository
│   │   ├── ideate.md                  # Brainstorming workflow
│   │   ├── investigate.md             # Root cause analysis
│   │   ├── prd-generate.md            # PRD creation
│   │   ├── prd-architect.md           # ADR design document generation
│   │   ├── prd-split.md               # PRD to tasks decomposition
│   │   ├── prd-update.md              # PRD modification
│   │   ├── prd-import.md              # PRD import
│   │   ├── prd-investigate.md         # PRD investigation
│   │   ├── prd-list.md / prd-delete.md / prd.md
│   │   ├── task-start.md              # Task execution
│   │   ├── task-create.md             # Manual task creation
│   │   ├── task-complete.md           # Task completion
│   │   ├── task-split.md              # Task subdivision
│   │   ├── task-list.md / task-show.md / task-delete.md / task-link.md / task.md
│   │   ├── sprint-run.md              # Sprint execution
│   │   ├── sprint-create.md           # Sprint creation
│   │   ├── sprint-start.md            # Sprint activation
│   │   ├── sprint-complete.md         # Sprint completion
│   │   ├── sprint-sync.md             # Bidirectional sync
│   │   ├── sprint-sync-to.md / sprint-sync-from.md
│   │   ├── sprint-import.md           # External sprint import
│   │   ├── sprint-link.md / sprint-unlink.md
│   │   ├── sprint-list.md / sprint-show.md / sprint-delete.md / sprint.md
│   │   ├── sprint-mappings.md         # Sync mapping viewer
│   │   ├── pr-feedback.md             # PR review comment processor
│   │   ├── sonar-scan.md              # SonarQube integration
│   │   ├── publish.md                 # Artifact publishing
│   │   ├── status.md                  # Artifact freshness
│   │   └── update.md                  # Incremental artifact updates
│   │
│   ├── artifact_templates/            # Mustache-style content templates
│   │   ├── prd.template.md
│   │   ├── task.template.md
│   │   ├── architecture.template.md
│   │   ├── codebase-summary.template.md
│   │   ├── data-model.template.md
│   │   ├── directory-structure.template.md
│   │   ├── key-workflows.template.md
│   │   ├── requirements.template.md
│   │   ├── lesson-learn.template.md
│   │   └── claude-md.template.md
│   │
│   ├── ui/                            # Web dashboard
│   │   ├── __init__.py                # FastAPI app + routes (~31 handlers)
│   │   └── templates/                 # Jinja2 HTML templates
│   │       ├── base.html              # Master layout (dark theme, nav, utils)
│   │       ├── home.html              # Cross-project overview
│   │       ├── dashboard.html         # Per-project dashboard
│   │       ├── prds.html              # PRD list
│   │       ├── prd_detail.html        # PRD detail (4 tabs)
│   │       ├── tasks.html             # Task list
│   │       ├── task_detail.html       # Task detail
│   │       ├── sprints.html           # Sprint list
│   │       ├── sprint_detail.html     # Sprint detail
│   │       ├── settings.html          # Integration settings
│   │       ├── analytics.html         # Metrics dashboard (Chart.js)
│   │       ├── no_project.html        # No project state
│   │       ├── onboarding.html        # First-run onboarding
│   │       └── partials/
│   │           ├── integration_card.html
│   │           └── integration_form.html
│   │
│   └── monitoring_files/              # Bundled monitoring configs
│       ├── __init__.py
│       └── langfuse-hook.py           # Langfuse conversation hook
│
├── tests/                             # Test suite
│   ├── __init__.py
│   ├── test_cli.py                    # CLI command tests
│   ├── test_design.py                 # Design document tests
│   ├── test_external_sync.py          # External sync tests
│   ├── test_file_storage.py           # HybridStorage tests
│   ├── test_init_files.py             # Init file generation tests
│   ├── test_mcp_setup.py             # Serena MCP setup tests
│   ├── test_monitoring_setup.py       # Monitoring setup tests
│   ├── test_plugins.py               # Plugin system tests
│   ├── test_pr_feedback.py           # PR feedback tests
│   ├── test_prd_update.py            # PRD update tests
│   ├── test_server.py                # MCP server tool tests
│   ├── test_sonarqube_setup.py       # SonarQube setup tests
│   ├── test_task_generator.py         # Task generation tests
│   ├── test_ui.py                     # UI route tests
│   └── test_uninstall.py             # Uninstall tests
│
├── monitoring/                        # Monitoring stack (deployed)
│   ├── docker-compose.yaml
│   ├── langfuse-hook.py
│   └── signoz/                        # SigNoz submodule
│
├── example-artifacts/                 # Example generated artifacts
│   ├── architecture.md
│   ├── codebase-summary.md
│   ├── data-model.md
│   ├── directory-structure.md
│   ├── key-workflows.md
│   ├── requirements.md
│   └── task.md
│
├── logs/                              # Hook log outputs
│   ├── chat.json
│   ├── post_tool_use.json
│   └── stop.json
│
└── .sdlc/                             # Project-level SDLC config
    ├── config.yaml                    # Project configuration
    ├── artifacts/                     # Generated documentation
    └── .cache/                        # Scan metadata
```

## Summary

- **Source files**: 38 Python modules
- **Test files**: 16 test modules
- **Skill templates**: ~40 markdown files
- **Content templates**: 10 mustache templates
- **UI templates**: 14 HTML templates
- **Total Python LOC**: ~15,000+ lines
