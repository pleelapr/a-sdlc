# Codebase Summary

## Overall Purpose & Domain

A-SDLC is an MCP (Model Context Protocol) server and CLI tool that provides Software Development Lifecycle management for Claude Code. It manages PRDs (Product Requirements Documents), tasks, sprints, and design documents with external system integrations (Linear, Jira, Confluence, GitHub).

The system operates as a bridge between AI-assisted development workflows and traditional project management, enabling Claude Code agents to create, track, and execute structured development plans through slash-command skill templates.

## Key Concepts & Domain Terminology

| Term | Definition |
|------|-----------|
| **PRD** | Product Requirements Document — structured specification for a feature |
| **Task** | Atomic unit of work derived from splitting a PRD |
| **Sprint** | Time-boxed collection of PRDs and their tasks |
| **Design Document** | ADR-style architecture design linked 1:1 to a PRD |
| **Skill Template** | Markdown file defining a Claude Code slash command workflow |
| **MCP Tool** | Server-side function exposed via Model Context Protocol |
| **Artifact** | Generated documentation (architecture, data model, etc.) |
| **Hybrid Storage** | Pattern combining SQLite metadata with markdown content files |
| **Sync Mapping** | Linkage between local entities and external system IDs |
| **Shortname** | 4-character uppercase project identifier (e.g., `SDLC`) |

## Technology Stack

| Layer | Technology |
|-------|-----------|
| **Language** | Python 3.10+ |
| **Build System** | Hatchling |
| **Package Manager** | uv |
| **CLI Framework** | Click 8.1+ with Rich for terminal output |
| **MCP Server** | `mcp` library (stdio transport) |
| **Web UI** | FastAPI + Jinja2 + HTMX + Chart.js |
| **Database** | SQLite (schema v5) |
| **HTTP Client** | httpx (for Linear, Jira, GitHub APIs) |
| **Data Validation** | Pydantic 2.0+ |
| **Configuration** | PyYAML |
| **Testing** | pytest 8.0+ with unittest.mock |
| **Linting** | ruff |
| **Type Checking** | mypy (strict mode) |
| **Monitoring** | Langfuse (conversation tracing) + SigNoz (OTEL metrics) |
| **Code Analysis** | SonarQube integration |

## Data Persistence & State Management

### Hybrid Storage Model

The system uses a dual-storage architecture:

1. **SQLite Database** (`~/.a-sdlc/data.db`): Stores metadata, relationships, and indexes
   - Schema version 5 with migration chain
   - Tables: projects, prds, tasks, sprints, designs, sync_mappings
   - Foreign key relationships with cascade deletes

2. **Markdown Content Files** (`~/.a-sdlc/content/{project_id}/`):
   - PRDs: `prds/{prd_id}.md`
   - Tasks: `tasks/{task_id}.md`
   - Designs: `designs/{prd_id}.md`
   - Source of truth for document content

3. **Project-Level Storage** (`.sdlc/` per repository):
   - Generated artifacts in `.sdlc/artifacts/`
   - Scan cache in `.sdlc/.cache/`
   - Project config in `.sdlc/config.yaml`

### Entity Hierarchy

```
Project (SDLC)
  └── Sprint (SDLC-S0001)
        └── PRD (SDLC-P0001) ← has optional Design
              └── Task (SDLC-T00001)
```

Tasks inherit sprint membership through their parent PRD. Tasks do NOT have a direct `sprint_id`.

## External Dependencies & APIs

| System | Protocol | Purpose |
|--------|----------|---------|
| **Linear** | GraphQL API | Cycle/issue sync (bidirectional) |
| **Jira** | REST API v3 | Sprint/issue sync with ADF formatting |
| **Confluence** | REST API v3 | Artifact and PRD publishing |
| **GitHub** | REST + GraphQL | PR review comment retrieval |
| **SonarQube** | REST API | Code quality analysis |
| **Langfuse** | HTTP hooks | Conversation tracing |
| **SigNoz** | OTEL | Metrics and observability |

## Configuration & Deployment

### Installation Flow

```
uv tool install a-sdlc[all]    # Install package
a-sdlc install                  # Deploy templates + MCP config
a-sdlc install --with-serena    # + Serena MCP for code analysis
a-sdlc install --with-monitoring # + Langfuse/SigNoz stack
```

### Configuration Files

| File | Scope | Purpose |
|------|-------|---------|
| `~/.claude.json` | Global | MCP server registration |
| `~/.claude/settings.json` | Global | Serena config, hooks, env vars |
| `~/.config/a-sdlc/config.yaml` | Global | Plugin configs (Linear, Jira, GitHub) |
| `.sdlc/config.yaml` | Project | SonarQube, project-specific settings |
| `~/.claude/commands/sdlc/` | Global | Deployed skill templates |

### MCP Server

Started via `uvx a-sdlc serve` (stdio transport) or `a-sdlc serve --transport sse` for SSE.
Registered automatically in `~/.claude.json` during `a-sdlc install`.

### Web UI

```
a-sdlc ui                      # Start on localhost:3847
a-sdlc ui --port 8080          # Custom port
a-sdlc ui stop                 # Stop server
```

PID-managed process with signal handling for graceful shutdown.
