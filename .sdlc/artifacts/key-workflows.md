# Key Workflows

## 1. Project Initialization (`/sdlc:init`)

**Components**: `cli.py:init_project_cmd`, `server/project_tools.py:init_project`, `core/init_files.py`, `storage/__init__.py`

**Relevance**: Entry point for all new projects. Creates the project registration, config files, and directory structure that every other workflow depends on.

### Sequence Flow

1. User runs `/sdlc:init` or calls `init_project()` MCP tool.
2. `init_project()` resolves the current working directory via `os.getcwd()`.
3. Database checks for an existing project at that path (`get_project_by_path()`).
4. If the project already exists, returns current state with file existence checks for `CLAUDE.md`, `.sdlc/lesson-learn.md`, `.sdlc/config.yaml`.
5. If new: generates a 4-character uppercase shortname from the project name (or uses the user-provided shortname after validation and uniqueness check).
6. Database creates the project record with `create_project(project_id, name, path, shortname)`.
7. `generate_init_files()` creates the following files from bundled templates:
   - `CLAUDE.md` (from `claude-md.template.md`, with `<!-- a-sdlc:managed -->` marker)
   - `GEMINI.md` (if Gemini CLI is detected, from `gemini-md.template.md`)
   - `.sdlc/lesson-learn.md` (from `lesson-learn.template.md`)
   - `.sdlc/config.yaml` (from `config.template.yaml`)
   - `~/.a-sdlc/lesson-learn.md` (global, created only if missing)
8. Returns project details including shortname and ID format examples (e.g., `PCRA-T00001`, `PCRA-S0001`).

---

## 2. Codebase Scan (`/sdlc:scan`)

**Components**: `templates/scan.md`, `artifacts/local.py:LocalArtifactPlugin`, Serena MCP tools (optional)

**Relevance**: Generates five living documentation artifacts from codebase analysis. These artifacts provide context for PRD generation, task planning, and sprint execution.

### Sequence Flow

1. User runs `/sdlc:scan`.
2. Agent reads `.sdlc/config.yaml` for project type and configuration.
3. Performs codebase analysis using available tools:
   - Recursive directory scan to identify key files by project type.
   - Symbol extraction (classes, functions, constants) per file.
   - Dependency graph mapping via reference tracing.
   - Workflow tracing through key function bodies.
4. Generates five artifacts:
   - `directory-structure.md` -- formatted tree with file summaries.
   - `codebase-summary.md` -- technology stack, key concepts, configuration.
   - `architecture.md` -- component breakdown with responsibilities and boundaries.
   - `data-model.md` -- entity definitions, relationships, and schema.
   - `key-workflows.md` -- sequence flows for major operations.
5. Writes all artifacts to `.sdlc/artifacts/`.
6. Stores checksums in `.sdlc/.cache/checksums.json` for change detection.

---

## 3. PRD Generation (`/sdlc:prd-generate`)

**Components**: `templates/prd-generate.md`, `server/prd_tools.py:create_prd`, `core/content.py:ContentManager`, `storage/__init__.py`

**Relevance**: Creates structured Product Requirements Documents from interactive requirements discovery. The PRD is the source of truth for all downstream tasks.

### Sequence Flow

1. Agent reads `.sdlc/lesson-learn.md` and `~/.a-sdlc/lesson-learn.md` for preflight lessons.
2. Agent loads project context via `get_context()` and reads `.sdlc/artifacts/` for codebase understanding.
3. Interactive requirements discovery with the user via structured dialogue.
4. Agent calls `create_prd(title)`:
   - Database generates the next PRD ID using the project shortname (e.g., `PCRA-P0001`).
   - ContentManager writes a skeleton markdown file to `~/.a-sdlc/content/{project_id}/prds/{prd_id}.md`.
   - Database inserts a PRD record with `file_path` reference and status `draft`.
5. Returns `file_path` to the agent.
6. Agent writes the full PRD content via the Write tool (content is never passed through MCP parameters).
7. PRD content includes: Overview, Goals, Functional Requirements (FR-NNN), Non-Functional Requirements (NFR-NNN), Acceptance Criteria (AC-NNN), and Technical Constraints.
8. Auto-parsing extracts requirements from the written content and upserts them into the `requirements` table with depth classification (structural/behavioral/integration).
9. Optional: `update_prd(status="approved")` after user review.

---

## 4. PRD Architecture Review (`/sdlc:prd-architect`)

**Components**: `templates/prd-architect.md`, `server/prd_tools.py:get_prd`, `server/design_tools.py:create_design`

**Relevance**: Creates ADR-style technical design documents grounded in codebase analysis. Each PRD has at most one design document (1:1 relationship).

### Sequence Flow

1. User runs `/sdlc:prd-architect` with the target PRD ID.
2. Agent loads PRD content via `get_prd(prd_id)`.
3. Checks for an existing design via `get_design(prd_id)` (one design per PRD).
4. Reads `.sdlc/artifacts/architecture.md` for current architecture context.
5. Analyzes affected codebase components by reading actual source files.
6. Generates six ADR sections: Context, Decision, Approach, Impact Analysis, Alternatives, and Consequences.
7. Section-by-section review with the user (Keep/Edit/Remove per section).
8. Calls `create_design(prd_id)`:
   - Storage creates a DB record and an empty markdown file at `~/.a-sdlc/content/{project_id}/designs/{prd_id}.md`.
   - Returns `file_path` for content writing.
9. Agent writes the full design content via the Write tool.

---

## 5. PRD Split (`/sdlc:prd-split`)

**Components**: `templates/prd-split.md`, `server/prd_tools.py:get_prd`, `server/task_tools.py:create_task`, `server/quality_tools.py:parse_requirements`

**Relevance**: Converts PRDs into actionable, dependency-ordered tasks. The quality gate at Step 5.5 ensures that all requirements are covered before proceeding.

### Sequence Flow

1. Agent loads PRD via `get_prd(prd_id)` and reads its content.
2. Reads `.sdlc/lesson-learn.md` for preflight checks and project-specific rules.
3. Loads design document via `get_design(prd_id)` for architecture decisions.
4. Parses requirements (FR/NFR/AC) from PRD content.
5. Proposes a task breakdown with: titles, priorities, components, dependencies, and design compliance mapping.
6. User reviews and approves the task list.
7. For each approved task, agent calls `create_task(title, prd_id, priority, component)`:
   - Database generates the next task ID (e.g., `PCRA-T00001`).
   - ContentManager writes a skeleton task file to `~/.a-sdlc/content/{project_id}/tasks/{task_id}.md`.
   - Database inserts a task record with `file_path`, `prd_id`, and status `pending`.
   - Returns `file_path`.
8. Agent writes task content with: goal, key requirements, implementation steps, success criteria, deliverables, and dependency references.
9. Quality gate (Step 5.5): agent verifies completeness -- every FR, NFR, and AC from the PRD is covered by at least one task.
10. Agent calls `update_prd(prd_id, status="split")` to mark the PRD as decomposed.

---

## 6. Sprint Execution (`/sdlc:sprint-run`)

**Components**: `templates/sprint-run.md`, `server/sprint_tools.py`, `server/task_tools.py`, `server/review_tools.py`, `executor.py:Executor`

**Relevance**: Core execution loop. Runs all tasks in a sprint via dependency ordering and parallel batching, with review gates at each task completion.

### Sequence Flow

1. Agent loads sprint via `get_sprint(sprint_id)`.
2. Gets sprint tasks via `get_sprint_tasks(sprint_id)` (tasks are derived via PRD join -- tasks inherit sprint membership through their parent PRD).
3. Reads `.sdlc/lesson-learn.md` for preflight lessons.
4. Builds a dependency graph from task dependency metadata.
5. Creates execution batches using topological sort (tasks with no unmet dependencies form a batch).
6. For each batch:
   a. Starts tasks: `update_task(task_id, status="in_progress")`.
   b. Launches parallel Task agents for independent tasks within the batch.
   c. Each agent: reads task content, implements changes, runs tests, performs self-review.
   d. Waits for batch completion before proceeding to next batch.
7. Self-review: `submit_review(task_id, reviewer_type="self", verdict="pass"|"fail", findings, test_output)`.
8. Subagent review (if configured): independent agent reviews and calls `submit_review(task_id, reviewer_type="subagent", verdict="approve"|"request_changes"|"escalate")`.
9. Completion: `update_task(task_id, status="completed")`.
10. Context pressure monitoring: warns at 70%, urgent at 85%, compact at 95%.
11. Sprint completion with quality gate checks via `complete_sprint(sprint_id)`.

---

## 7. Task Execution (`/sdlc:task-start` + `/sdlc:task-complete`)

**Components**: `templates/task-start.md`, `templates/task-complete.md`, `server/task_tools.py`, `server/review_tools.py`, `server/quality_tools.py`

**Relevance**: Individual task lifecycle from start to verified completion with review evidence and correction logging.

### Sequence Flow

1. Agent calls `get_task(task_id)` to load metadata, content, and `file_path`.
   - Sprint ID is derived from the parent PRD's sprint assignment.
   - If the task has an active claim, agent permissions are surfaced.
2. Agent calls `update_task(task_id, status="in_progress")`.
3. Agent reads task content for implementation steps, success criteria, and dependencies.
4. Implements changes per the task specification.
5. Runs test commands from `.sdlc/config.yaml`.
6. Self-review: `submit_review(task_id, reviewer_type="self", verdict, findings, test_output)`.
   - Round number is auto-computed from existing reviews of the same type.
7. Subagent review (if configured in `.sdlc/config.yaml`): a fresh agent reviews the implementation independently.
8. Quality verification: acceptance criteria check against linked requirements.
9. Agent calls `update_task(task_id, status="completed")`.
10. If mistakes were found during implementation: `log_correction(context_type="task", context_id=task_id, category, description)` appends to `.sdlc/corrections.log`.

---

## 8. Pipeline Orchestration (`a-sdlc run goal`)

**Components**: `executor.py:Executor.execute_objective`, `server/execution_tools.py`, `server/agent_tools.py`, `server/challenge_tools.py`

**Relevance**: Autonomous multi-agent pipeline that takes a high-level goal through the full SDLC lifecycle via a single Claude Code session.

### Sequence Flow

1. User runs `a-sdlc run goal "<description>"` from the CLI.
2. Executor initializes: verifies `claude` CLI is available, sets max turns and concurrency.
3. Calls `execute_objective(description, run_id, max_iterations)`:
   - Builds a comprehensive prompt that instructs the session to orchestrate the full SDLC cycle.
   - Spawns a headless `claude -p` session with MCP tool access.
4. The session autonomously:
   a. Analyzes the objective and creates PRDs.
   b. Generates design documents for each PRD.
   c. Splits PRDs into tasks.
   d. Creates and runs sprints.
   e. Implements tasks with self-review.
5. Challenge rounds: `challenge_artifact(artifact_type, artifact_id)` generates structured challenge prompts for PRDs, designs, splits, and tasks.
6. Evaluation: runs evaluation commands after each iteration, checks if acceptance criteria are met.
7. Iterates (up to `max_iterations`, default 5) if the objective is not yet met.
8. In supervised mode: outputs `---ITERATION-CHECKPOINT---` markers and pauses for user approval via `a-sdlc run approve`.
9. Returns a parsed objective outcome dictionary.

---

## 9. External System Sync (`/sdlc:sprint-sync`)

**Components**: `templates/sprint-sync.md`, `server/sync_tools.py`, `server/sync.py:ExternalSyncService`, `plugins/linear.py`, `plugins/jira.py`

**Relevance**: Bidirectional sync between a-sdlc and Linear/Jira for team collaboration, with conflict detection and status mapping.

### Sequence Flow

1. **Configure integration**: `manage_integration(action="configure", system="linear", config={api_key, team_id})`.
   - Stores credentials in the `external_configs` table for the current project.
   - Supported systems: `linear`, `jira`, `confluence`, `github`.
2. **Import**: `import_from_linear()` or `import_from_jira()` fetches cycles/sprints and creates local sprint, PRD, and task records.
3. **Sync** (bidirectional):
   a. `sync_sprint(sprint_id, direction="bidirectional")`.
   b. Push direction: creates or updates issues in the external system.
   c. Pull direction: imports new or updated issues from the external system.
   d. Status mapping:
      - `pending` maps to `Backlog` (Linear) / `To Do` (Jira).
      - `in_progress` maps to `In Progress`.
      - `blocked` maps to `Blocked`.
      - `completed` maps to `Done`.
4. **Mapping management**: `sync_mappings` table tracks `entity_type`, `local_id`, `external_system`, `external_id`, and `sync_status`.
5. **Conflict resolution**: `sync_status` is set to `conflict` when both local and external sides have been modified since the last sync.

---

## 10. Quality Feedback Loop

**Components**: `server/quality_tools.py:log_correction`, `templates/retrospective.md`, `templates/sprint-complete.md`, `server/sprint_tools.py:complete_sprint`

**Relevance**: Continuous improvement through correction logging, pattern detection, and lesson extraction. Lessons feed back into preflight checks for all future work.

### Sequence Flow

1. **During work**: `log_correction(context_type, context_id, category, description)` appends to `.sdlc/corrections.log`.
   - Valid context types: `task`, `prd`, `sprint`, `pr`, `ad-hoc`.
   - Valid categories: `testing`, `code-quality`, `task-completeness`, `integration`, `documentation`, `architecture`, `security`, `performance`, `process`.
   - Format: `TIMESTAMP | CONTEXT:ID | CATEGORY | DESCRIPTION`.
2. **Sprint complete**: `complete_sprint(sprint_id)` enforces quality gates:
   - Checks for orphaned requirements (not linked to any task).
   - Checks for unverified acceptance criteria.
   - Checks for scope-drift tasks (tasks not linked to a PRD).
   - Returns `blocked` status with gap details if issues exist (unless `force=True` or a quality waiver is active).
   - Auto-completes PRDs where all child tasks are done.
3. **Retrospective** (`/sdlc:retrospective`):
   a. Reads the corrections log.
   b. Identifies patterns (2+ corrections in the same category).
   c. Proposes lessons via user dialogue.
   d. Writes approved lessons to `.sdlc/lesson-learn.md` and/or `~/.a-sdlc/lesson-learn.md`.
   e. Archives corrections to `.sdlc/corrections.log.{sprint_id}`.
4. **Preflight**: Next sprint/task reads `lesson-learn` files before starting work, applying MUST/SHOULD/MAY priority rules.

---

## 11. Daemon and Background Execution

**Components**: `daemon.py:run_daemon`, `executor.py:Executor`, `cli.py:daemon_start/stop/status`

**Relevance**: Enables unattended sprint execution and external sync with cron scheduling, crash recovery, and graceful lifecycle management.

### Sequence Flow

1. `a-sdlc daemon start` forks a background process:
   - Configures rotating file logging to `~/.a-sdlc/daemon.log`.
   - Registers `SIGTERM` and `SIGINT` signal handlers for graceful shutdown.
   - Writes PID to `~/.a-sdlc/daemon.pid` and registers `atexit` cleanup.
2. Crash recovery: detects incomplete runs on startup and offers resume.
3. Main event loop (60-second interval):
   a. For each configured schedule in `.sdlc/config.yaml`, checks the cron expression against the current minute.
   b. De-duplicates triggers within the same minute.
   c. On trigger: calls `_execute_scheduled_run()`.
4. Schedule types:
   - `sprint_run`: spawns a detached `Executor` subprocess via `python -m a_sdlc.executor` with configured max turns and supervised mode.
   - `sync`: calls `sync_sprint()` directly (blocking, typically fast).
5. Supervised mode: pauses between batches, waits for `a-sdlc run approve`.
6. `a-sdlc daemon stop`: sends `SIGTERM` for graceful shutdown, escalates to `SIGKILL` after 10 seconds.
7. `a-sdlc daemon status`: reads PID file and checks if the process is alive.

---

## 12. Installation and Setup

**Components**: `installer.py:Installer`, `cli.py:install/setup`, `mcp_setup.py`, `playwright_setup.py`, `monitoring_setup.py`, `sonarqube_setup.py`

**Relevance**: Deploys skill templates, agent personas, and MCP server configuration. Supports progressive enhancement with optional toolchain add-ons.

### Sequence Flow

1. `a-sdlc install`:
   a. Copies `src/a_sdlc/templates/*.md` to `~/.claude/commands/sdlc/` (or the target CLI's commands directory).
   b. Copies `personas/*.md` to `~/.claude/agents/` for agent persona definitions.
   c. Configures `asdlc` MCP server in `~/.claude.json` (command: `uvx a-sdlc serve`).
   d. Auto-detects installed CLIs (Claude, Gemini) and installs for each detected target.
   e. Optionally enables Agent Teams experimental feature.
2. `a-sdlc setup serena`: installs and configures Serena MCP for semantic code navigation.
3. `a-sdlc setup playwright`: installs and configures Playwright MCP for browser testing.
4. `a-sdlc setup monitoring`: deploys Langfuse hook + SigNoz Docker stack to `~/monitoring/`, configures OTEL environment variables.
5. `a-sdlc setup sonarqube`: installs pysonar package and configures project key in `.sdlc/config.yaml`.
6. Verification: `a-sdlc doctor` checks all dependencies (Python version, uv/uvx availability, Claude Code installation).

---

## 13. Web Dashboard

**Components**: `ui/__init__.py`, `ui/templates/*.html`, `cli.py:ui`

**Relevance**: Visual interface for monitoring and managing SDLC artifacts, pipeline runs, and integration settings.

### Sequence Flow

1. `a-sdlc ui` starts a FastAPI server on `127.0.0.1:3847` (configurable via `--port`).
2. Startup sequence:
   a. Checks for stale PID file and cleans up if needed.
   b. Writes PID to `~/.a-sdlc/ui.pid`.
   c. Registers signal handlers (`SIGTERM`, `SIGINT`) for graceful shutdown.
   d. Starts uvicorn ASGI server.
3. Pages:
   - Home (`/`) -- project picker.
   - Dashboard (`/projects/{id}`) -- project statistics overview.
   - Tasks, Sprints, PRDs -- list views with status filters.
   - PRD detail -- tabs for docs, design, tasks, dependencies.
   - Pipeline Runs -- execution history and status.
   - Analytics -- Chart.js dashboard for project metrics.
   - Settings -- integration management (Linear, Jira, Confluence, GitHub).
4. WebSocket endpoint `/ws/runs/{run_id}` for live pipeline run updates:
   - `ConnectionManager` groups connections by run ID.
   - Broadcasts status changes to all connected clients.
5. HTMX-based interactions for task/sprint/PRD status updates (partial page refreshes).
6. `a-sdlc ui stop` sends `SIGTERM` to the running server process.

---

## 14. PR Review Feedback (`/sdlc:pr-feedback`)

**Components**: `templates/pr-feedback.md`, `server/github_tools.py:get_pr_feedback`, `server/github.py:GitHubClient`

**Relevance**: Retrieves and categorizes GitHub PR review comments for automated resolution, bridging code review with the task workflow.

### Sequence Flow

1. User runs `/sdlc:pr-feedback`.
2. Agent detects git branch and remote via `detect_git_info()`.
3. Resolves GitHub token (project config, then global `~/.config/a-sdlc/`, then `GITHUB_TOKEN` environment variable).
4. `GitHubClient` operations:
   a. Finds the open PR for the current branch.
   b. Fetches review comments (paginated REST API).
   c. Fetches resolved thread IDs (GraphQL API).
   d. Fetches issue comments.
5. Agent categorizes comments by:
   - Severity: blocking, suggestion, nitpick.
   - Resolution status: resolved or unresolved.
   - File location: path and line number.
6. Presents actionable items for user review.
7. Agent implements fixes for approved items.

---

## 15. Agent Governance

**Components**: `server/agent_tools.py`, `server/governance_helpers.py`, `executor.py:evaluate_escalation_rules`, `executor.py:check_budget`

**Relevance**: Multi-agent lifecycle management with registration, permission checking, budget enforcement, and escalation rules for autonomous execution.

### Sequence Flow

1. **Agent registration**: `manage_agent(action="register", persona_type, display_name)` creates an agent record with a unique ID and active status. Audit log entry is appended.
2. **Agent proposal**: `manage_agent(action="propose", persona_type, justification)` creates a `proposed` agent awaiting human approval.
3. **Permission check**: `check_permission(agent_id, permission_type)` validates that an agent has the required permissions for an operation.
4. **Task claiming**: `manage_agent_task(action="claim", agent_id, task_id)` assigns a task to an agent with exclusive ownership.
5. **Budget enforcement** (governance-gated):
   - `manage_agent_budget(action="set", agent_id, token_limit, cost_limit_cents)` configures per-agent budget limits.
   - `check_budget(storage, agent_id)` verifies remaining budget before each work loop iteration.
   - Budget is incremented after each task execution with token and cost deltas.
6. **Escalation rules**: `evaluate_escalation_rules(task_id, task_metrics)` checks conditions like `retry_count > 3` or `cost > threshold` and triggers actions (pause, alert).
7. **Team composition**: `auto_compose_team()` and `enforce_team_health()` manage agent teams for complex projects.
8. **Agent suspension/retirement**: `manage_agent(action="suspend"|"retire", agent_id)` changes agent status and releases active task claims.

---

## 16. Git Worktree Isolation

**Components**: `server/worktree_tools.py`, `server/github.py:GitHubClient`

**Relevance**: Provides git worktree-based isolation for parallel PRD implementation, enabling multiple features to be developed simultaneously without branch conflicts.

### Sequence Flow

1. **Setup**: `setup_prd_worktree(prd_id)` creates a git worktree for a PRD:
   - Creates a feature branch named after the PRD.
   - Sets up a worktree directory in `.worktrees/`.
   - Ensures `.worktrees/` is in `.gitignore`.
2. **List**: `list_worktrees()` shows all active worktrees with their associated PRDs.
3. **Safety configuration**: `manage_git_safety(action="configure", auto_commit, auto_pr, auto_merge, worktree_enabled)` controls what git operations agents are allowed to perform.
4. **PR creation**: `create_prd_pr(prd_id)` creates a GitHub pull request from the PRD's worktree branch.
5. **Completion**: `complete_prd_worktree(prd_id)` finalizes the worktree (merge or PR).
6. **Cleanup**: `cleanup_prd_worktree(prd_id)` removes the worktree and optionally the branch.
