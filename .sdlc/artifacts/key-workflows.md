# Key Workflows

## 1. Project Initialization

**Main Components**: CLI (`init`), MCP Server (`init_project`), Database, InitFiles

**Relevance**: Entry point for all new projects. Sets up storage, generates CLAUDE.md, and registers project in the database.

### Sequence Flow

1. User runs `/sdlc:init` or `a-sdlc init`
2. MCP `init_project()` resolves `os.getcwd()` as project path
3. Database checks for existing project at path (`get_project_by_path()`)
4. If new: generates shortname (4 uppercase letters from project name)
5. Database creates project record with shortname
6. `init_files.generate_init_files()` creates:
   - `.sdlc/` directory
   - `CLAUDE.md` from `claude-md.template.md`
   - `.sdlc/lesson-learn.md` from `lesson-learn.template.md`
   - `~/.a-sdlc/lesson-learn.md` (global, if not exists)
7. Returns project details with ID format examples

---

## 2. PRD Creation

**Main Components**: Skill Template (`prd-generate.md`), MCP Server (`create_prd`), HybridStorage, ContentManager

**Relevance**: Core document creation flow. Agent follows template instructions to gather requirements and produce structured PRD.

### Sequence Flow

1. User runs `/sdlc:prd-generate "<description>"`
2. Agent loads template → calls `mcp__asdlc__get_context()` for project info
3. Agent reads `.sdlc/artifacts/` for codebase context
4. Interactive requirements gathering via `AskUserQuestion`
5. Agent generates PRD markdown content
6. Agent calls `mcp__asdlc__create_prd(title, content, sprint_id?)`
7. HybridStorage:
   a. ContentManager writes `~/.a-sdlc/content/{project}/prds/{id}.md`
   b. Database inserts PRD record with file_path reference
8. Returns PRD ID (e.g., `SDLC-P0001`)

---

## 3. Design Document Generation

**Main Components**: Skill Template (`prd-architect.md`), MCP Server (`create_design`), HybridStorage

**Relevance**: Creates ADR-style architecture design grounded in codebase analysis. Required before task splitting.

### Sequence Flow

1. User runs `/sdlc:prd-architect "<prd_id>"`
2. Agent loads PRD via `mcp__asdlc__get_prd(prd_id)`
3. Checks for existing design via `mcp__asdlc__get_design(prd_id)`
4. Reads `.sdlc/artifacts/` for architecture context
5. Analyzes affected codebase components (reads actual source files)
6. Generates 6 ADR sections: Context, Decision, Approach, Impact Analysis, Alternatives, Consequences
7. Section-by-section review via `AskUserQuestion` (Keep/Edit/Remove)
8. Saves via `mcp__asdlc__create_design(prd_id, content)`
9. HybridStorage writes `~/.a-sdlc/content/{project}/designs/{prd_id}.md` + DB record

---

## 4. PRD to Tasks Splitting

**Main Components**: Skill Template (`prd-split.md`), MCP Server (`create_task`), HybridStorage

**Relevance**: Decomposes PRD into executable tasks with dependency ordering. Design gate enforces architecture-first approach.

### Sequence Flow

1. User runs `/sdlc:prd-split "<prd_id>"`
2. Agent loads PRD + verifies design document exists (hard gate)
3. Reads design document for architecture decisions
4. Explores codebase to identify affected components
5. Plans task decomposition with dependency graph
6. Generates task list with:
   - Dependencies between tasks
   - Component assignments
   - Implementation steps
   - Success criteria
   - Design compliance mapping
7. Presents task plan for user review via `AskUserQuestion`
8. Creates tasks via `mcp__asdlc__create_task()` for each approved task
9. Updates PRD status to `split`
10. Design Decision Traceability Matrix validates 100% coverage

---

## 5. Sprint Execution

**Main Components**: Skill Template (`sprint-run.md`), MCP Server (task tools), HybridStorage

**Relevance**: Orchestrates parallel task execution within a sprint using dependency-based batching.

### Sequence Flow

1. User runs `/sdlc:sprint-run`
2. Agent loads sprint via `mcp__asdlc__get_sprint(sprint_id)`
3. Gets sprint tasks via `mcp__asdlc__get_sprint_tasks(sprint_id)`
4. Builds dependency graph → identifies execution batches
5. For each batch (topological order):
   a. Launches parallel Task agents for independent tasks
   b. Each agent: reads task → implements code → runs tests → marks complete
   c. Waits for batch completion before next batch
6. Updates task statuses via `mcp__asdlc__complete_task(task_id)`
7. Reports batch progress to user

---

## 6. External System Sync

**Main Components**: SyncService (`server/sync.py`), Plugins (Linear/Jira), Database (sync_mappings)

**Relevance**: Bidirectional sync between local sprints/tasks and external project management tools.

### Sequence Flow (Sync Sprint to Linear)

1. User runs `/sdlc:sprint-sync-to`
2. Agent calls `mcp__asdlc__sync_sprint_to(sprint_id)`
3. SyncService loads sprint + tasks
4. Checks `sync_mappings` for existing external linkage
5. If new: creates Linear cycle via GraphQL API
6. For each task:
   a. Maps status: pending→Backlog, in_progress→In Progress, etc.
   b. Maps priority: high→2, medium→3, etc.
   c. Creates/updates Linear issue
   d. Stores mapping in `sync_mappings` table
7. Updates `sync_status` to `synced` with timestamp

### Sequence Flow (Import from Jira)

1. User runs `a-sdlc sync jira pull --active`
2. CLI calls JiraPlugin with Atlassian REST client
3. JiraPlugin fetches active sprint via `/rest/agile/1.0/board/{id}/sprint`
4. Fetches sprint issues via JQL query
5. Creates local sprint + tasks via HybridStorage
6. Stores sync mappings for bidirectional tracking

---

## 7. Web Dashboard Serving

**Main Components**: CLI (`ui` command), FastAPI app (`ui/__init__.py`), Jinja2 templates

**Relevance**: Provides visual project management interface accessible via browser.

### Sequence Flow

1. User runs `a-sdlc ui` or `a-sdlc ui --port 8080`
2. CLI checks for stale PID file, cleans up if needed
3. Writes PID to `~/.a-sdlc/ui.pid`
4. Starts uvicorn ASGI server on `127.0.0.1:3847`
5. FastAPI handles requests:
   - GET `/` → project list (home.html)
   - GET `/projects/{id}` → dashboard with stats
   - GET `/prds`, `/tasks`, `/sprints` → list views with filters
   - GET `/prds/{id}` → detail with 4 tabs (docs, design, tasks, deps)
   - PUT endpoints → AJAX updates (status, content, sprint assignment)
   - POST endpoints → HTMX partial updates
   - GET `/analytics` → Chart.js dashboard
   - GET/POST `/settings` → integration management
6. Signal handler catches SIGTERM/SIGINT for graceful shutdown

---

## 8. Installation & Configuration

**Main Components**: Installer, MCP Setup, Monitoring Setup, SonarQube Setup

**Relevance**: One-command setup of the entire toolchain with progressive enhancement.

### Sequence Flow

1. User runs `a-sdlc install [--with-serena] [--with-monitoring] [--with-sonarqube]`
2. Installer:
   a. Copies `src/a_sdlc/templates/*.md` → `~/.claude/commands/sdlc/`
   b. Registers `asdlc` MCP server in `~/.claude.json`
3. If `--with-serena`:
   a. Installs `serena-mcp-server` via uv/pipx
   b. Configures in `~/.claude/settings.json` mcpServers section
4. If `--with-monitoring`:
   a. Deploys Langfuse hook + docker-compose to `~/monitoring/`
   b. Clones SigNoz repository
   c. Adds Stop hook to `~/.claude/settings.json`
   d. Sets OTEL environment variables in settings
5. If `--with-sonarqube`:
   a. Installs pysonar package
   b. Configures project key in `.sdlc/config.yaml`

---

## 9. PR Review Feedback Processing

**Main Components**: Skill Template (`pr-feedback.md`), GitHubClient (`server/github.py`), MCP Server (`get_pr_feedback`)

**Relevance**: Retrieves and processes GitHub PR review comments for automated resolution.

### Sequence Flow

1. User runs `/sdlc:pr-feedback`
2. Agent detects git branch and remote via `detect_git_info()`
3. Loads GitHub token from global config
4. GitHubClient:
   a. Finds open PR for current branch
   b. Fetches review comments (paginated REST)
   c. Fetches resolved thread IDs (GraphQL)
   d. Fetches issue comments
5. Agent categorizes comments by:
   - Severity (blocking, suggestion, nitpick)
   - Resolution status (resolved/unresolved)
   - File location (path + line number)
6. Presents actionable items for user review
7. Agent implements fixes for approved items

---

## 10. Artifact Scanning & Generation

**Main Components**: Skill Template (`scan.md`), Serena MCP tools, Artifact plugins

**Relevance**: Generates 5 living documentation artifacts from codebase analysis.

### Sequence Flow

1. User runs `/sdlc:scan`
2. Agent reads `.sdlc/config.yaml` for project type
3. Uses Serena MCP for codebase analysis:
   - `list_dir(recursive=true)` → directory tree
   - `get_symbols_overview()` → classes, functions, constants per file
   - `find_referencing_symbols()` → dependency graph
   - `find_symbol()` → key function bodies for workflow tracing
4. Generates 5 artifacts:
   - `directory-structure.md` — formatted tree with summary
   - `codebase-summary.md` — technology stack, concepts, configuration
   - `architecture.md` — component breakdown with responsibilities
   - `data-model.md` — entity definitions and relationships
   - `key-workflows.md` — sequence flows for key operations
5. Writes to `.sdlc/artifacts/`
6. Stores checksums in `.sdlc/.cache/checksums.json`
