# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A-SDLC is an MCP server that provides SDLC (Software Development Lifecycle) management tools for PRDs, tasks, and sprints with external system integration (Linear, Jira). It also ships slash-command skill templates. Docker Compose is the canonical deployment method.

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

# Database migration management (Alembic)
a-sdlc db status                               # Show current migration state
a-sdlc db migrate                              # Apply all pending migrations
a-sdlc db migrate -r <revision>                # Migrate to a specific revision
a-sdlc db rollback                             # Revert one migration step
a-sdlc db rollback -r -2                       # Revert two steps
a-sdlc db rollback -r base                     # Revert all migrations

# Server management
a-sdlc serve                                    # Start combined MCP + UI server (foreground)
a-sdlc serve --mcp-port 9000 --ui-port 9001    # Custom ports
a-sdlc serve --host 0.0.0.0                    # Bind to all interfaces

# Docker (canonical deployment)
docker compose up -d                            # Start all services
docker compose logs -f                          # Follow logs
docker compose down                             # Stop (data persists in named volumes)
```

All tests must pass before committing changes.

## Architecture

### High-Level Components

```
src/a_sdlc/
├── cli.py                     # Click CLI entry point (a-sdlc command, includes `db` subgroup)
├── installer.py               # Deploys templates → ~/.claude/commands/sdlc/, MCP config → ~/.claude.json
├── server/__init__.py         # Combined MCP + UI server (run_server)
├── server/sync.py             # External sync service (Linear, Jira)
├── core/
│   ├── database.py            # Legacy raw-SQL SQLite driver (kept for test base_path mode only)
│   ├── models.py              # SQLModel ORM entity models for all 15 tables (v15 schema)
│   ├── engine.py              # SQLAlchemy engine factory with connection pooling (SQLite/PostgreSQL)
│   ├── session_database.py    # SessionDatabase — ORM-based drop-in replacement for Database class
│   ├── storage_config.py      # StorageConfig — layered config for DB URL, content backend, S3
│   └── content.py             # Content backends (LocalContentBackend, S3ContentBackend)
├── storage/__init__.py        # HybridStorage adapter (bridges DB + content files, backend selection)
├── plugins/                   # Sync plugins: linear.py, jira.py (entry points in pyproject.toml)
├── artifacts/                 # Artifact generation: scan → .sdlc/artifacts/
├── templates/                 # Skill templates (~35 .md files, deployed to ~/.claude/commands/sdlc/)
└── artifact_templates/        # Mustache content templates (prd.template.md, task.template.md)

alembic/
├── env.py                     # Alembic environment — resolves DB URL via StorageConfig
├── script.py.mako             # Migration script template
└── versions/
    └── 0001_baseline_v15.py   # Baseline migration — creates all 15 tables from scratch
```

### Installer Flow

`a-sdlc install` (via `installer.py`):
1. Copies `src/a_sdlc/templates/*.md` → `~/.claude/commands/sdlc/`
2. Configures `asdlc` MCP server in `~/.claude.json` with HTTP transport (flags: `--url`, `--auth-token`, `--force`, `--list`, `--target`)

`--force` refreshes templates/personas but preserves a previously configured MCP `url` and `Authorization` header unless `--url`/`--auth-token` are explicitly passed again.

Every successful MCP configuration is also recorded in `{data_dir}/mcp-registration.json` (a-sdlc's own record, independent of the client's settings file). If the client loses the `asdlc` entry — e.g., Claude Code rewriting `~/.claude.json` from stale in-memory state while an install ran — `a-sdlc install` restores the recorded URL/auth automatically and `a-sdlc doctor` flags the loss.

### Plugin System

Entry points defined in `pyproject.toml`:
- `a_sdlc.plugins`: `linear`, `jira` — sync plugins
- `a_sdlc.artifacts`: `local`, `confluence` — artifact publishing plugins

## Server Architecture

`a-sdlc serve` runs a combined HTTP server (`run_server()` in `server/__init__.py`) that serves both the MCP endpoint (streamable-http) and the web UI dashboard (uvicorn/FastAPI) in a single process. Both share the same asyncio event loop and HybridStorage instance.

Docker Compose handles process management (restart policies, health checks). There is no built-in daemon or background process manager.

### Port Configuration

| Port | Service | Default | Override |
|------|---------|---------|----------|
| 8765 | MCP server (streamable-http) | `8765` | `--mcp-port` flag |
| 3847 | Web UI dashboard | `3847` | `--ui-port` flag |

Port conflicts are detected before binding via `_check_port_availability()`. When a port is in use, the error message identifies the blocking PID (using `lsof` on macOS/Linux) and suggests using `--mcp-port` or `--ui-port` to choose different ports.

### MCP Configuration (Claude Code)

The `a-sdlc install` command writes MCP configuration to `~/.claude.json`:

```json
{
  "mcpServers": {
    "asdlc": {
      "type": "http",
      "url": "http://localhost:8765/mcp"
    }
  }
}
```

The server must be running before Claude Code can connect. Start it with `a-sdlc serve` (foreground) or via Docker Compose.

## Storage Architecture

### Hybrid Storage Model

```
~/.a-sdlc/                          # User-level storage (cross-project)
└── content/                        # Markdown content files (source of truth)
    └── {project_id}/
        ├── prds/{prd_id}.md
        └── tasks/{task_id}.md

.sdlc/                              # Project-level (per repository)
├── artifacts/                      # Generated docs (5 standard artifacts)
├── .cache/checksums.json           # Scan metadata
└── config.yaml                     # Project-specific configuration
```

### Data Layer Architecture

The data layer has two implementations that share the same API surface:

| Component | Role |
|-----------|------|
| `core/database.py` (`Database`) | Legacy raw-SQL SQLite driver -- kept for test `base_path` mode only |
| `core/session_database.py` (`SessionDatabase`) | ORM-based replacement using SQLModel/SQLAlchemy sessions |
| `core/models.py` | 15 SQLModel entity classes mirroring the v15 schema |
| `core/engine.py` | `get_engine()` / `get_session()` factories with connection pooling |
| `core/storage_config.py` | `StorageConfig` -- layered configuration for DB URL and content backend |

**`SessionDatabase`** is API-compatible with `Database` -- all public methods return `dict[str, Any]` or `list[dict]`. Callers (HybridStorage, MCP tools) do not need to change.

### Database Backends

| Backend | URL Scheme | Pool | Notes |
|---------|-----------|------|-------|
| PostgreSQL (production) | `postgresql://user:pass@host/db` | `QueuePool(5, overflow=10)` | `pool_pre_ping=True` for connection health checks |
| SQLite (tests only) | `sqlite:///path/to/data.db` | `StaticPool` | WAL mode, `busy_timeout=30000`, FK enforcement. Used via `base_path` in tests |

### Content Backends

| Backend | Config Value | Storage |
|---------|-------------|---------|
| S3-compatible (default) | `content_backend: s3` | S3 bucket (or MinIO) via boto3. Requires `s3_bucket` |
| Local (tests only) | `content_backend: local` | Filesystem paths. Used via `base_path` in tests |

### Schema Management (Alembic)

Schema migrations are managed by Alembic, with migration scripts in `alembic/versions/`. The current baseline is revision `0001` which creates all 15 tables of the v15 schema.

- `alembic/env.py` resolves the database URL at runtime via `StorageConfig`, so environment variables and config files are respected.
- `render_as_batch=True` is set for SQLite ALTER TABLE support.
- Migrations support both offline (SQL script generation) and online (live connection) modes.

### Storage Configuration

Configuration is resolved with the following priority (highest first):

1. **Environment variables** (`A_SDLC_DATABASE_URL`, `A_SDLC_S3_*`, etc.)
2. **Project config** (`.sdlc/config.yaml` `storage` section)
3. **Global config** (`~/.config/a-sdlc/config.yaml` `storage` section)

There are no built-in defaults for `database_url`. The `A_SDLC_DATABASE_URL` environment variable is required.

#### Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `A_SDLC_DATABASE_URL` | Database connection URL (required) | -- (none) |
| `A_SDLC_CONTENT_BACKEND` | Content storage backend (`local` or `s3`) | `s3` |
| `A_SDLC_S3_BUCKET` | S3 bucket name (required when backend is `s3`) | -- |
| `A_SDLC_S3_ENDPOINT` | S3-compatible endpoint URL (for MinIO, etc.) | -- |
| `A_SDLC_S3_ACCESS_KEY` | S3 access key ID | -- |
| `A_SDLC_S3_SECRET_KEY` | S3 secret access key | -- |
| `A_SDLC_DATA_DIR` | Override base data directory | `~/.a-sdlc` |

### Key Storage Rules

1. **Never reference `.sdlc/tasks/`** -- Tasks are stored via the content backend (S3 or local)
2. **Never reference `.sdlc/sprints/mappings.json`** -- Mappings are in the database
3. **Use MCP tools for metadata and content** -- See Content Editing Pattern below
4. **Artifacts stay in `.sdlc/`** -- Generated docs belong with the project
5. **No filesystem path is stored in the DB** -- A checkout links to its project via the local `.sdlc/project.json` marker (`core/project_marker.py`). Project context is resolved by walking up from cwd to that marker, so the same project works across machines/containers against one central database. Commit `.sdlc/project.json` so identity travels with the repo; `a-sdlc init` regenerates it if missing.

## Content Editing Pattern

PRD, Design, and Task content can be managed via the optional `content` parameter on MCP tools. This routes writes through the configured content backend (S3 or local filesystem), ensuring correct behavior in Docker/cloud deployments.

- **Create with content**: `create_*(title=..., content="# Full markdown...")` -- writes through backend
- **Create skeleton only**: `create_*(title=...)` -- creates skeleton file, returns `file_path`
- **Read**: `get_*(id)` -- returns `file_path` + content
- **Update content**: `update_*(id, content="# Updated markdown...")` -- writes through backend (read-modify-write pattern)
- **Update metadata only**: `update_*(id, status=..., ...)` -- DB only, no file changes
- **Update design**: `update_design(prd_id, content=...)` -- writes design content through backend

**Preferred pattern (works with all backends including S3/Docker):**
```
result = create_prd(title="Feature X", content="# Feature X\n\n## Overview\n...")
```

**Read-modify-write pattern for updates:**
```
prd = get_prd(prd_id)           # Get current content
# ... modify content in-memory ...
update_prd(prd_id, content="<full updated markdown>")
```

## Entity Hierarchy

```
Sprint -> PRD -> Task
```

### Critical Relationship Rules

1. **Tasks inherit sprint membership through PRD** -- Tasks do NOT have a direct `sprint_id` column
2. **PRDs can be optionally assigned to sprints** -- `prd.sprint_id` is nullable
3. **Query sprint tasks via PRD join** -- `WHERE prd_id IN (SELECT id FROM prds WHERE sprint_id = ?)`

### ID Formats

| Entity | Format | Example |
|--------|--------|---------|
| Project | 4-char uppercase shortname | `PCRA` |
| Task | `{shortname}-T{number:05d}` | `PCRA-T00001` |
| Sprint | `{shortname}-S{number:04d}` | `PCRA-S0001` |
| PRD | `{shortname}-P{number:04d}` | `PCRA-P0001` |

### Database Schema

```sql
projects (id, shortname UNIQUE, name, created_at, last_accessed)  -- no filesystem path; a checkout links to its project via .sdlc/project.json
prds (id, project_id FK, sprint_id FK nullable, title, file_path, status[draft|approved|split|completed], version)
tasks (id, project_id FK, prd_id FK, title, file_path, status[pending|in_progress|blocked|completed], priority[low|medium|high|critical], component)
sprints (id, project_id FK, title, goal, status[planned|active|completed], external_id)
sync_mappings (entity_type, local_id, external_system[linear|jira], external_id, sync_status[synced|pending|conflict|error])
```

## Template-Driven Workflows

Templates in `src/a_sdlc/templates/` are operational guides for Claude agents -- they describe what MCP tools to call, in what order, and with what parameters.

| Template | Primary MCP Tools |
|----------|-------------------|
| `prd-generate.md` | `create_prd()` |
| `prd-split.md` | `get_prd()`, `create_task()` |
| `task-start.md` | `get_task()`, `update_task()` |
| `sprint-run.md` | `get_sprint()`, `get_task()`, `update_task()` |
| `sprint-sync.md` | `sync_sprint()`, `list_sync_mappings()` |

Content editing pattern: `create_*()` returns `file_path` -> agent writes content via `Write` tool -> `update_*()` for metadata only.

## MCP Tools Reference

### Context Tools
- `get_context()` -- Current project + statistics
- `list_projects()` -- All projects
- `init_project(name?, shortname?)` -- Initialize project for the server's current directory (local deployments); writes the `.sdlc/project.json` marker. Re-links (no new row) when a project with the derived id already exists.
- `create_project(name, shortname?)` -- Create a project independent of the server's cwd (remote/centralized deployments). Writes no files on the server; returns `init_files` specs (path, scope, content) -- including `.sdlc/project.json` -- for the client to create locally. Sets the new project as the active context.
- `switch_project(project_id)` -- Switch project context

### PRD Tools
- `create_prd(title, content?)` -- Creates PRD; when `content` provided, writes through backend
- `get_prd(prd_id)` -- Returns metadata + content + `file_path`
- `update_prd(prd_id, status?, version?, sprint_id?, content?)` -- Updates metadata and/or content
- `list_prds(sprint_id?, status?)` -- Filter PRDs
- `delete_prd(prd_id)` -- Removes PRD + content file
- `split_prd(prd_id, task_specs)` -- Decompose PRD into tasks; specs support optional `content` key

### Design Tools
- `create_design(prd_id, content?)` -- Creates design; when `content` provided, writes through backend
- `get_design(prd_id)` -- Returns metadata + content + `file_path`
- `update_design(prd_id, content)` -- Updates design document content through backend
- `delete_design(prd_id)` -- Removes design + content file
- `list_designs()` -- List design docs

### Task Tools
- `create_task(title, prd_id?, priority?, component?, content?)` -- Creates task; when `content` provided, writes through backend
- `get_task(task_id)` -- Returns metadata + content + `file_path` (derives sprint from PRD)
- `update_task(task_id, status?, priority?, component?, content?)` -- Updates metadata and/or content
- `list_tasks(sprint_id?, prd_id?, status?)` -- Filter tasks

### Sprint Tools
- `create_sprint(title, goal)` -- Creates sprint
- `get_sprint(sprint_id)` -- Returns sprint with PRD count
- `update_sprint(sprint_id, title?, goal?, status?)` -- Update sprint metadata (use `complete_sprint` for completion)
- `complete_sprint(sprint_id)` -- Complete sprint with quality gate checks
- `manage_sprint_prds(action, prd_id, sprint_id?)` -- Add/remove PRDs from sprint (action: "add"|"remove")
- `get_sprint_prds(sprint_id)` -- All PRDs in sprint
- `get_sprint_tasks(sprint_id)` -- All tasks (derived via PRDs)

### Sync Tools
- `manage_integration(action, system?, config?)` -- Manage integrations (action: "configure"|"list"|"remove")
- `import_from_linear()` / `import_from_jira()` -- Import cycles/sprints
- `sync_sprint(sprint_id, direction?)` -- Sync sprint (direction: "bidirectional"|"push"|"pull")
- `sync_prd(prd_id, direction?)` -- Sync PRD (direction: "bidirectional"|"push"|"pull")
- `manage_sync_mapping(action, entity_type, entity_id, system?, external_id?)` -- Link/unlink sync mappings
- `list_sync_mappings()` -- View all mappings

### Review Tools
- `submit_review(task_id, reviewer_type, verdict, findings?, test_output?)` -- Submit review (reviewer_type: "self"|"subagent")
- `get_review_evidence(task_id)` -- Get all review evidence for a task

### Challenge Tools
- `challenge_artifact(artifact_type, artifact_id, challenge_context?)` -- Generate a structured challenge prompt for an artifact (artifact_type: "prd"|"design"|"split"|"task")
- `record_challenge_round(artifact_type, artifact_id, round_number, objections, responses?, verdict?)` -- Record objections, responses, and verdict for a challenge round; detects stale loops
- `get_challenge_status(artifact_type, artifact_id)` -- Get aggregated challenge status with round summaries and effectiveness metrics

### Quality Tools
- `log_correction(context_type, context_id, category, description)` -- Log a correction to `.sdlc/corrections.log`

## Key Workflows

1. **Init**: `/sdlc:init` -> creates `.sdlc/`, registers project in DB with shortname, generates `CLAUDE.md` + `.sdlc/lesson-learn.md` + `~/.a-sdlc/lesson-learn.md`
2. **Scan**: `/sdlc:scan` -> analyzes codebase -> generates 5 artifacts in `.sdlc/artifacts/`
3. **PRD**: `/sdlc:prd-generate` -> interactive requirements -> `create_prd()` -> DB + content file
4. **Split**: `/sdlc:prd-split` -> analyze PRD -> propose tasks -> user approves -> `create_task()` for each
5. **Sprint**: `/sdlc:sprint-run` -> get tasks via PRD join -> build dependency graph -> parallel execution
6. **Sync**: `/sdlc:sprint-sync` -> `sync_sprint()` -> create/update external issues -> store sync mappings

## External System Sync

- **Linear**: GraphQL API, cycles as sprints
- **Jira**: REST API v3, sprints with ADF formatting
- Status mapping: pending<->Backlog/To Do, in_progress<->In Progress, blocked<->Blocked, completed<->Done

## Quality Gate System

a-sdlc includes a quality feedback loop that captures corrections, distills them into lessons, and enforces them via preflight checks.

### Data Flow

```
corrections.log -> retrospective -> lesson-learn.md -> preflight checks
```

1. **Corrections Log** (`.sdlc/corrections.log`) -- Append-only log of all fixes, format: `TIMESTAMP | CONTEXT:ID | CATEGORY | DESCRIPTION`
2. **Retrospective** (`/sdlc:sprint-complete`) -- Reads corrections, identifies patterns (2+ in same category), proposes lessons via AskUserQuestion
3. **Lessons Learned** (`.sdlc/lesson-learn.md` + `~/.a-sdlc/lesson-learn.md`) -- Categorized rules with MUST/SHOULD/MAY priorities
4. **Preflight Checks** -- Lessons presented before work starts in prd-split, task-start, sprint-run
5. **Quality Gates** -- Completeness verification at prd-split (Step 5.5) and task-complete (DoD checklist)

### File Locations

| File | Location | Purpose |
|------|----------|---------|
| Project lessons | `.sdlc/lesson-learn.md` | Project-specific rules |
| Global lessons | `~/.a-sdlc/lesson-learn.md` | Cross-project rules |
| Correction log | `.sdlc/corrections.log` | Raw correction entries |
| Archived corrections | `.sdlc/corrections.log.{sprint_id}` | Post-retrospective archive |
| CLAUDE.md template | `src/a_sdlc/artifact_templates/claude-md.template.md` | Generated during init |
| Lesson template | `src/a_sdlc/artifact_templates/lesson-learn.template.md` | Generated during init |

## Docker Deployment

Docker Compose is the canonical deployment method. The project includes a multi-stage `Dockerfile` and a `docker-compose.yml` for containerized deployment with PostgreSQL and MinIO.

### Docker Compose (PostgreSQL + MinIO)

```bash
cp .env.example .env       # Edit with your values
docker compose up -d        # Start all services
docker compose logs -f      # Follow logs
docker compose down          # Stop (data persists in named volumes)
docker compose down -v       # Stop and remove volumes (destroys data)
```

Services:
- **postgres** -- PostgreSQL 16 Alpine, metadata store
- **minio** -- S3-compatible object storage for content files
- **minio-init** -- One-shot bucket initialization
- **a-sdlc** -- Combined MCP + UI server, connects to postgres and minio

The compose file configures environment variables automatically (`A_SDLC_DATABASE_URL`, `A_SDLC_CONTENT_BACKEND=s3`, `A_SDLC_S3_*`).

The image exposes two ports:
- **8765** -- MCP server (streamable-http, `/health` endpoint)
- **3847** -- Web UI dashboard

### Port Mapping

Port mapping in `docker-compose.yml`:

```yaml
ports:
  - "${A_SDLC_MCP_PORT:-8765}:8765"   # MCP server
  - "${A_SDLC_UI_PORT:-3847}:3847"    # Web UI dashboard
```

Override ports with environment variables in `.env`:

```bash
A_SDLC_MCP_PORT=9000
A_SDLC_UI_PORT=9001
```

Point Claude Code to the Docker-hosted server by configuring the MCP URL:

```json
{
  "mcpServers": {
    "asdlc": {
      "type": "http",
      "url": "http://localhost:9000/mcp"
    }
  }
}
```

## PostgreSQL Setup

### Prerequisites

1. PostgreSQL 16+ running and accessible
2. Target database created (e.g., `CREATE DATABASE asdlc;`)
3. a-sdlc installed with `uv sync --all-extras` (includes `sqlalchemy`, `alembic`, `psycopg2`)
4. S3-compatible bucket for content storage (MinIO or AWS S3)

### Initialize Schema

Set the database URL and apply migrations:

```bash
export A_SDLC_DATABASE_URL="postgresql://user:pass@localhost/asdlc"
a-sdlc db migrate    # Creates all 15 tables via Alembic
```

### Configure Backend

Set environment variables or edit `~/.config/a-sdlc/config.yaml`:

```yaml
# ~/.config/a-sdlc/config.yaml
storage:
  database_url: "postgresql://user:pass@localhost/asdlc"
  content_backend: "s3"
  s3_bucket: "asdlc-content"
  s3_endpoint: "http://localhost:9000"
  s3_access_key: "minioadmin"
  s3_secret_key: "minioadmin"
```

Or via environment variables:

```bash
export A_SDLC_DATABASE_URL="postgresql://user:pass@localhost/asdlc"
export A_SDLC_CONTENT_BACKEND="s3"
export A_SDLC_S3_BUCKET="asdlc-content"
export A_SDLC_S3_ENDPOINT="http://localhost:9000"
export A_SDLC_S3_ACCESS_KEY="minioadmin"
export A_SDLC_S3_SECRET_KEY="minioadmin"
```

### Verify

```bash
a-sdlc db status      # Should show "Up to date"
a-sdlc serve          # Start the server against the configured backend
```

### Docker Deployment Option

Instead of manual setup, use `docker compose up -d` to spin up PostgreSQL, MinIO, and the a-sdlc server together. See the Docker Deployment section above.

### Rollback

If a migration fails or you need to revert:

```bash
# Revert Alembic migrations
a-sdlc db rollback -r base -y
```

## Observability

a-sdlc includes built-in observability features for monitoring, diagnosing, and troubleshooting the MCP server and web UI.

### Structured Logging

The MCP server writes structured JSON logs to `~/.a-sdlc/server.log` using a `RotatingFileHandler` (1 MB max, 3 backups). Every log line is a single JSON object with the following schema:

```json
{
  "ts": "2026-05-20T10:30:00.123+00:00",
  "level": "INFO",
  "event": "tool_call_end",
  "tool": "get_task",
  "duration_ms": 12.45,
  "status": "ok"
}
```

**Log entry fields:**

| Field | Type | Description |
|-------|------|-------------|
| `ts` | string | ISO-8601 timestamp with milliseconds |
| `level` | string | Log level: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `event` | string | Log event / message |
| `tool` | string? | MCP tool name (present on tool call events) |
| `duration_ms` | number? | Tool execution time in milliseconds |
| `status` | string? | `started`, `ok`, or `error` |
| `error_type` | string? | Exception class name (on errors) |
| `error_message` | string? | Exception message string (on errors) |
| `traceback` | string? | Full traceback (when exception info is present) |

The `instrument_tool` decorator in `server/__init__.py` automatically wraps every MCP tool handler to emit `tool_call_start`, `tool_call_end`, and `tool_call_error` events with timing and error details.

### Health Endpoint

The `/health` route is registered on the MCP server (port 8765). It returns an in-memory health snapshot with no I/O, targeting <100ms response time.

**Request:** `GET /health`

**Response schema:**

```json
{
  "status": "healthy",
  "version": "0.7.1",
  "uptime_seconds": 3600.25,
  "pid": 12345,
  "memory_mb": 48.5,
  "active_connections": 2,
  "last_error": null
}
```

**Health response fields:**

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | Always `"healthy"` (server-side singleton) |
| `version` | string | a-sdlc package version |
| `uptime_seconds` | number | Seconds since server start (monotonic clock) |
| `pid` | number | Server process ID |
| `memory_mb` | number | Peak RSS memory usage in MB |
| `active_connections` | number | Currently active connections |
| `last_error` | object? | Most recent error (`{type, message, timestamp}`) or `null` |

The `ServerHealth` class (`server/health.py`) is a thread-safe singleton with atomic counters protected by a threading lock.

### Health Dashboard

The web UI includes a health dashboard at `/health` (on the UI port, default 3847). It provides:

- Real-time status indicator (Healthy / Degraded / Unhealthy)
- Uptime, memory usage, active connections, and error count metrics

The dashboard uses a WebSocket at `/ws/health` that pushes health snapshots every 5 seconds for real-time updates without polling.

### CLI Observability Commands

```bash
# View server logs (last 50 entries by default)
a-sdlc logs

# Show more entries
a-sdlc logs -n 100

# Filter by minimum log level
a-sdlc logs --level error

# Stream new log entries in real-time
a-sdlc logs --follow
a-sdlc logs -f -l warning    # Stream warnings and errors only

# Continuous health monitoring (polls /health every 2s)
a-sdlc doctor --live
```

The `logs` command reads `~/.a-sdlc/server.log`, parses JSON entries, and displays them with color-coded severity levels. The `--follow` / `-f` flag tails the log file for new entries.

The `doctor --live` command polls the MCP server health endpoint at `http://127.0.0.1:8765/health` every 2 seconds and displays color-coded status, uptime, connections, memory, and last error. It shows `unreachable` in red if the server is not running or not reachable.

### Troubleshooting Workflow

When MCP tools are not working or behaving unexpectedly, follow this diagnostic workflow:

1. **Run diagnostics**: `a-sdlc doctor`
   - Checks Python version, uv/uvx availability, MCP configuration, database accessibility, and schema version
   - Reports pass/warn/fail for each check with actionable fix suggestions

2. **Check server logs**: `a-sdlc logs --level error`
   - Look for `tool_call_error` events with `error_type` and `error_message`
   - Check for `server_crashed` or `server_shutdown` events
   - Use `-n 200` for more context around the error

3. **Monitor live health**: `a-sdlc doctor --live`
   - Verify the server is reachable and reporting `healthy`
   - Watch for `degraded` status (indicates recent errors)
   - Check `active_connections` count and `memory_mb` for resource issues

4. **Open health dashboard**: Navigate to `http://localhost:3847/health`
   - View real-time status and metrics (uptime, memory, connections)

5. **Check raw logs**: `a-sdlc logs -f` to stream all new log entries while reproducing the issue

**Common diagnostic patterns:**

| Symptom | Check | Likely Cause |
|---------|-------|-------------|
| MCP tools not responding | `a-sdlc doctor` | Server not running or MCP not configured |
| Tools slow | `a-sdlc logs` (check `duration_ms`) | Database lock contention or large queries |
| Intermittent failures | `a-sdlc logs --level error` | Transient errors in tool handlers |
| Server unreachable | `a-sdlc doctor --live` | Port conflict or process crash |
| High memory usage | Health dashboard | Memory leak or resource exhaustion |
| Port already in use | `a-sdlc serve` | Another process on port 8765/3847. Use `--mcp-port`/`--ui-port` or `lsof -ti :8765` to find the blocker |
| Claude Code can't connect | Verify `~/.claude.json` | MCP config URL may be wrong. Run `a-sdlc install --force` |
| Docker container won't start | `docker compose logs a-sdlc` | Check for missing environment variables or database connection errors |

## Common Mistakes to Avoid

### Storage Mistakes
- **WRONG**: Reading tasks from `.sdlc/tasks/` -> **RIGHT**: `get_task(task_id)` via MCP
- **WRONG**: Storing mappings in `.sdlc/sprints/mappings.json` -> **RIGHT**: `sync_mappings` table via MCP
- **WRONG**: Passing content/description through MCP tools -> **RIGHT**: `create_*()` returns `file_path`, write with `Write` tool
- **WRONG**: Using `update_prd(content=...)` -> **RIGHT**: Edit the file directly, use `update_prd(status=...)` for metadata

### Hierarchy Mistakes
- **WRONG**: Adding `sprint_id` column to tasks -> **RIGHT**: Tasks inherit sprint via PRD
- **WRONG**: Querying tasks directly by sprint_id -> **RIGHT**: Join through PRDs

### Template Mistakes
- **WRONG**: Hardcoding file paths in templates -> **RIGHT**: Using MCP tool calls that abstract storage

## a-sdlc Integration
<!-- a-sdlc:managed -->

This project uses a-sdlc for SDLC management.

**Before starting work, read these files:**
- `.sdlc/lesson-learn.md` -- Project-specific lessons and rules
- `~/.a-sdlc/lesson-learn.md` -- Global cross-project lessons
- `.sdlc/artifacts/` -- Generated codebase documentation (if available)

**During work:**
- Log corrections to `.sdlc/corrections.log` when fixing mistakes
- Update lesson-learn files when patterns emerge
- Use `/sdlc:help` for available commands
