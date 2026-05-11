# Data Model

This document describes the a-sdlc data model: all database tables, their columns, relationships, constraints, and the hybrid storage architecture that separates metadata (SQLite) from content (Markdown files).

**Schema version**: 14

---

## Storage Architecture

a-sdlc uses a hybrid storage model. SQLite stores metadata, relationships, and indexes. Markdown files on disk store the actual content that agents read and write.

```
~/.a-sdlc/                              # User-level storage (macOS/Linux)
  data.db                               # SQLite database (all tables below)
  content/                              # Markdown content files
    {project_id}/
      prds/{SHORTNAME}-P0001.md         # PRD content
      tasks/{SHORTNAME}-T00001.md       # Task content
      designs/{SHORTNAME}-P0001.md      # Design content (keyed by PRD ID)
      objectives/{SHORTNAME}-R0001.md   # Objective content (keyed by run ID)

.sdlc/                                  # Project-level (per repository)
  config.yaml                           # Project-specific configuration
  artifacts/                            # Generated documentation
  corrections.log                       # Quality feedback log
  .cache/checksums.json                 # Scan metadata
```

On Windows, the user-level directory is `%LOCALAPPDATA%/a-sdlc/` instead of `~/.a-sdlc/`.

### Content Editing Pattern

MCP tools manage metadata. File tools manage content.

1. `create_*()` returns a `file_path` pointing to a skeleton Markdown file.
2. The agent writes content into that file using the `Write` tool.
3. `update_*()` changes metadata fields in the database only -- it never touches the file.
4. `get_*()` returns both metadata and the content read from the file.

---

## Entity Relationship Diagram

```
                                  +-----------------+
                                  |    projects     |
                                  |  (top-level)    |
                                  +--------+--------+
                                           |
              +------------+---------------+---------------+-----------+
              |            |               |               |           |
      +-------v---+  +----v------+  +-----v-----+  +-----v-----+  +--v----------+
      |  sprints  |  |  agents   |  |  designs  |  |   prds    |  |   tasks     |
      +-----------+  +-----------+  +-----------+  +-----+-----+  +------+------+
           |              |              |               |                |
           |              |              | 1:1           |                |
           |              |              +------+--------+   +-----+-----+
           |              |                     |            |     |
           |              |                  (PRD owns)      |     |
           |              |                                  |     |
      +----v--------+     |         +-----------+    +------v-+ +-v---------+
      | execution   |     |         |  reviews  |    | req    | | sync      |
      |   _runs     |     |         +-----------+    | _links | | _mappings |
      +------+------+     |                          +--------+ +-----------+
             |             |
      +------v------+  +--v-----------+
      | work_queue  |  | agent_teams  |
      +-------------+  | agent_perms  |
      | artifact    |  | agent_budget |
      |  _threads   |  | agent_perf   |
      +-------------+  | agent_msgs   |
                        | task_claims  |
                        +--------------+

Legend:
  Sprint -->> PRD         (PRD.sprint_id FK, nullable)
  PRD -->> Task           (Task.prd_id FK, nullable)
  PRD -->> Design         (Design.prd_id FK, unique 1:1)
  Task --> Agent          (Task.assigned_agent_id FK, nullable)
  Task inherits Sprint membership through its parent PRD
```

---

## ID Format Reference

All entity IDs are deterministic, human-readable strings scoped to a project shortname. Counters are per-project.

| Entity | Format | Digits | Example |
|--------|--------|--------|---------|
| Project | Slugified folder name | -- | `a-sdlc` |
| Shortname | 4 uppercase letters | 4 | `SDLC` |
| PRD | `{SHORTNAME}-P{NNNN}` | 4 | `SDLC-P0001` |
| Task | `{SHORTNAME}-T{NNNNN}` | 5 | `SDLC-T00001` |
| Sprint | `{SHORTNAME}-S{NNNN}` | 4 | `SDLC-S0001` |
| Agent | `{SHORTNAME}-A{NNNN}` | 4 | `SDLC-A0001` |
| Execution Run | `{SHORTNAME}-R{NNNN}` | 4 | `SDLC-R0001` |
| Design | Derived from PRD ID | -- | (uses PRD ID internally) |

---

## Core Entities

### projects

Top-level container. Every other entity belongs to exactly one project.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | TEXT | PRIMARY KEY | Slugified folder name (e.g., `a-sdlc`) |
| `shortname` | TEXT | UNIQUE NOT NULL | 4-char uppercase key (e.g., `SDLC`) |
| `name` | TEXT | NOT NULL | Human-readable display name |
| `path` | TEXT | NOT NULL UNIQUE | Absolute filesystem path to project root |
| `created_at` | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | Creation time |
| `last_accessed` | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | Last access time, updated on context switches |

**Indexes**: `idx_projects_path` (path), `idx_projects_shortname` (shortname, unique)

**Relationships**: One-to-many parent of `prds`, `tasks`, `sprints`, `agents`, `designs`, `execution_runs`, `worktrees`, `agent_teams`

---

### prds

Product Requirement Documents. The primary planning artifact. Content lives in a Markdown file; the database row holds metadata and the file path.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | TEXT | PRIMARY KEY | Format: `{SHORTNAME}-P{NNNN}` |
| `project_id` | TEXT | FK -> projects, NOT NULL | Parent project |
| `sprint_id` | TEXT | FK -> sprints, NULLABLE | Optional sprint assignment (SET NULL on sprint delete) |
| `title` | TEXT | NOT NULL | PRD title |
| `file_path` | TEXT | | Absolute path to Markdown content file |
| `status` | TEXT | DEFAULT 'draft' | `draft` / `ready` / `split` / `completed` |
| `source` | TEXT | | Origin label (e.g., `manual`, `confluence`, `imported`) |
| `version` | TEXT | DEFAULT '1.0.0' | Semantic version string |
| `created_at` | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | |
| `updated_at` | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | |
| `ready_at` | TIMESTAMP | NULLABLE | Set on first transition to `ready` |
| `split_at` | TIMESTAMP | NULLABLE | Set on first transition to `split` |
| `completed_at` | TIMESTAMP | NULLABLE | Set on first transition to `completed` |

**Indexes**: `idx_prds_project`, `idx_prds_status`, `idx_prds_sprint`

**Relationships**:

- Belongs to one `projects` (required, CASCADE on delete)
- Optionally assigned to one `sprints` (SET NULL on sprint delete)
- Has many `tasks` (via `tasks.prd_id`)
- Has at most one `designs` (via `designs.prd_id`, UNIQUE constraint)
- Has many `requirements` (via `requirements.prd_id`)

**Content location**: `~/.a-sdlc/content/{project_id}/prds/{id}.md`

---

### tasks

Atomic work units. Derived from splitting a PRD. Sprint membership is inherited through the parent PRD -- tasks do NOT have a `sprint_id` column.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | TEXT | PRIMARY KEY | Format: `{SHORTNAME}-T{NNNNN}` |
| `project_id` | TEXT | FK -> projects, NOT NULL | Parent project |
| `prd_id` | TEXT | FK -> prds, NULLABLE | Parent PRD (SET NULL on PRD delete) |
| `title` | TEXT | NOT NULL | Task title |
| `file_path` | TEXT | | Absolute path to Markdown content file |
| `status` | TEXT | DEFAULT 'pending' | `pending` / `in_progress` / `blocked` / `completed` |
| `priority` | TEXT | DEFAULT 'medium' | `low` / `medium` / `high` / `critical` |
| `component` | TEXT | | Component/module label for routing |
| `assigned_agent_id` | TEXT | FK -> agents, NULLABLE | Assigned AI agent (SET NULL on agent delete) |
| `created_at` | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | |
| `updated_at` | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | |
| `started_at` | TIMESTAMP | NULLABLE | Set when work begins |
| `completed_at` | TIMESTAMP | NULLABLE | Set on completion |

**Indexes**: `idx_tasks_project`, `idx_tasks_status`, `idx_tasks_prd`, `idx_tasks_assigned_agent`

**Relationships**:

- Belongs to one `projects` (required, CASCADE on delete)
- Belongs to one `prds` (optional, SET NULL on PRD delete)
- Optionally assigned to one `agents` (SET NULL on agent delete)
- Sprint membership derived via: `WHERE prd_id IN (SELECT id FROM prds WHERE sprint_id = ?)`

**Content location**: `~/.a-sdlc/content/{project_id}/tasks/{id}.md`

**Important**: To query tasks for a sprint, always join through the `prds` table. Never add a `sprint_id` column to tasks.

---

### sprints

Time-boxed iterations that group PRDs (and transitively their tasks) for execution planning.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | TEXT | PRIMARY KEY | Format: `{SHORTNAME}-S{NNNN}` |
| `project_id` | TEXT | FK -> projects, NOT NULL | Parent project |
| `title` | TEXT | NOT NULL | Sprint title |
| `goal` | TEXT | | Sprint goal or objective statement |
| `status` | TEXT | DEFAULT 'planned' | `planned` / `active` / `completed` |
| `external_id` | TEXT | | ID in external system (Linear cycle ID, Jira sprint ID) |
| `external_url` | TEXT | | URL to the sprint in the external system |
| `created_at` | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | |
| `started_at` | TIMESTAMP | NULLABLE | When sprint was activated |
| `completed_at` | TIMESTAMP | NULLABLE | Completion timestamp |

**Indexes**: `idx_sprints_project`, `idx_sprints_status`

**Relationships**:

- Belongs to one `projects` (required, CASCADE on delete)
- Contains many `prds` (via `prds.sprint_id`)
- Contains tasks transitively through PRDs

---

### designs

Technical design documents. One-to-one relationship with a PRD, enforced by a UNIQUE constraint on `prd_id`.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | TEXT | PRIMARY KEY | Design document ID |
| `prd_id` | TEXT | FK -> prds, UNIQUE NOT NULL | Linked PRD (1:1, CASCADE on PRD delete) |
| `project_id` | TEXT | FK -> projects, NOT NULL | Parent project |
| `file_path` | TEXT | | Absolute path to Markdown design file |
| `created_at` | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | |
| `updated_at` | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | |

**Indexes**: `idx_designs_prd`, `idx_designs_project`

**Content location**: `~/.a-sdlc/content/{project_id}/designs/{prd_id}.md` (keyed by PRD ID, not design ID)

---

## Agent and Governance Entities

### agents

Registered AI agents with personas, permissions, and performance tracking.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | TEXT | PRIMARY KEY | Format: `{SHORTNAME}-A{NNNN}` |
| `project_id` | TEXT | FK -> projects, NOT NULL | Parent project |
| `persona_type` | TEXT | NOT NULL | Agent role (e.g., `backend_engineer`, `qa_engineer`) |
| `display_name` | TEXT | NOT NULL | Human-readable agent name |
| `status` | TEXT | DEFAULT 'active' | `active` / `suspended` / `retired` |
| `permissions_profile` | TEXT | | Named permission profile |
| `created_at` | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | |
| `approved_by` | TEXT | | Who approved agent creation |
| `team_id` | TEXT | | Team assignment |
| `reports_to_agent_id` | TEXT | | Reporting hierarchy |
| `hired_at` | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | |
| `suspended_at` | TIMESTAMP | NULLABLE | When suspended |
| `retired_at` | TIMESTAMP | NULLABLE | When retired |
| `performance_score` | REAL | DEFAULT 50.0 | Aggregate performance metric (0-100) |

**Indexes**: `idx_agents_project`, `idx_agents_status`, `idx_agents_persona`

---

### agent_permissions

Fine-grained permission scopes per agent. Controls what actions an agent can perform.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| `agent_id` | TEXT | FK -> agents, NOT NULL | Agent this permission applies to |
| `permission_type` | TEXT | NOT NULL | Permission category |
| `permission_value` | TEXT | NOT NULL | Specific permission scope |
| `allowed` | INTEGER | DEFAULT 1 | Boolean: 1 = allowed, 0 = denied |

**Constraint**: UNIQUE(`agent_id`, `permission_type`, `permission_value`)

**Index**: `idx_agent_perms_agent`

---

### agent_budgets

Token and cost budget tracking per agent per execution run.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| `agent_id` | TEXT | FK -> agents, NOT NULL | |
| `run_id` | TEXT | | Execution run this budget applies to |
| `token_limit` | INTEGER | | Maximum tokens allowed |
| `token_used` | INTEGER | DEFAULT 0 | Tokens consumed so far |
| `cost_limit_cents` | INTEGER | | Maximum cost in cents |
| `cost_used_cents` | INTEGER | DEFAULT 0 | Cost consumed so far |
| `alert_threshold_pct` | INTEGER | DEFAULT 90 | Alert when usage exceeds this percentage |
| `created_at` | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | |
| `updated_at` | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | |

**Indexes**: `idx_agent_budgets_agent`, `idx_agent_budgets_run`

---

### agent_performance

Sprint-level performance metrics per agent. Used for tracking quality and throughput over time.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| `agent_id` | TEXT | FK -> agents, NOT NULL | |
| `sprint_id` | TEXT | FK -> sprints, NULLABLE | Sprint measured (SET NULL on sprint delete) |
| `tasks_completed` | INTEGER | DEFAULT 0 | Tasks successfully completed |
| `tasks_failed` | INTEGER | DEFAULT 0 | Tasks that failed |
| `avg_quality_score` | REAL | | Average quality score across tasks |
| `avg_completion_time_min` | REAL | | Average time to complete tasks (minutes) |
| `corrections_count` | INTEGER | DEFAULT 0 | Number of corrections logged |
| `review_pass_rate` | REAL | | Fraction of reviews passed on first attempt |
| `created_at` | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | |

**Constraint**: UNIQUE(`agent_id`, `sprint_id`)

**Indexes**: `idx_agent_perf_agent`, `idx_agent_perf_sprint`

---

### agent_teams

Team composition. Groups agents under a lead for coordinated sprint work.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| `name` | TEXT | NOT NULL | Team name |
| `project_id` | TEXT | FK -> projects, NOT NULL | |
| `lead_agent_id` | TEXT | FK -> agents, NULLABLE | Team lead (SET NULL on agent delete) |
| `sprint_id` | TEXT | FK -> sprints, NULLABLE | Sprint assignment (SET NULL on sprint delete) |
| `created_at` | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | |

**Indexes**: `idx_agent_teams_project`, `idx_agent_teams_lead`, `idx_agent_teams_sprint`

---

### agent_messages

Inter-agent communication channel. Supports typed messages optionally linked to a task.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| `from_agent_id` | TEXT | FK -> agents, NOT NULL | Sender |
| `to_agent_id` | TEXT | FK -> agents, NOT NULL | Recipient |
| `message_type` | TEXT | NOT NULL | Message category (e.g., `request`, `response`, `alert`) |
| `content` | TEXT | NOT NULL | Message body |
| `related_task_id` | TEXT | FK -> tasks, NULLABLE | Related task (SET NULL on task delete) |
| `created_at` | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | |
| `read_at` | TIMESTAMP | NULLABLE | When recipient read the message |

**Indexes**: `idx_agent_messages_to`, `idx_agent_messages_from`, `idx_agent_messages_task`

---

### task_claims

Work-pickup mechanism. An agent claims a task before starting work. Only one active claim per task is allowed, enforced by a partial unique index.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| `task_id` | TEXT | FK -> tasks, NOT NULL | Claimed task |
| `agent_id` | TEXT | FK -> agents, NOT NULL | Claiming agent |
| `claimed_at` | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | |
| `released_at` | TIMESTAMP | NULLABLE | When the claim was released |
| `status` | TEXT | DEFAULT 'active' | `active` / `released` |
| `release_reason` | TEXT | | Why the claim was released |

**Constraint**: `UNIQUE INDEX idx_task_claims_active ON task_claims(task_id) WHERE status = 'active'` -- at most one active claim per task

**Indexes**: `idx_task_claims_task`, `idx_task_claims_agent`, `idx_task_claims_status`

---

## Execution Entities

### execution_runs

Top-level execution tracking. Represents a sprint execution, a single-task run, or an objective-driven goal loop.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | TEXT | PRIMARY KEY | Format: `{SHORTNAME}-R{NNNN}` |
| `project_id` | TEXT | FK -> projects, NOT NULL | |
| `sprint_id` | TEXT | FK -> sprints, NULLABLE | Associated sprint (SET NULL on sprint delete) |
| `status` | TEXT | DEFAULT 'pending' | `pending` / `active` / `paused` / `awaiting_confirmation` / `completed` / `failed` / `cancelled` |
| `run_type` | TEXT | DEFAULT 'sprint' | `sprint` / `task` / `objective` |
| `goal` | TEXT | | Goal statement for objective runs |
| `current_phase` | TEXT | | Current execution phase |
| `governance_config` | TEXT | | JSON governance configuration |
| `total_budget_cents` | INTEGER | | Total budget for the run |
| `total_spent_cents` | INTEGER | DEFAULT 0 | Total cost so far |
| `agent_count` | INTEGER | DEFAULT 0 | Number of agents involved |
| `config` | TEXT | | JSON run configuration |
| `clarification_question` | TEXT | | Pending clarification question |
| `clarification_answer` | TEXT | | Answer to clarification question |
| `started_at` | TIMESTAMP | NULLABLE | |
| `completed_at` | TIMESTAMP | NULLABLE | |
| `created_at` | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | |

**Indexes**: `idx_execution_runs_project`, `idx_execution_runs_sprint`, `idx_execution_runs_status`

---

### work_queue

Individual work items within an execution run. Each item represents a discrete unit of work (create a PRD, write a design, implement a task, run QA) dispatched to an agent.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | TEXT | PRIMARY KEY | Work item ID |
| `run_id` | TEXT | FK -> execution_runs, NOT NULL | Parent execution run |
| `project_id` | TEXT | FK -> projects, NOT NULL | |
| `work_type` | TEXT | NOT NULL | `prd` / `design` / `split` / `task` / `qa` |
| `artifact_type` | TEXT | | Type of artifact being produced |
| `artifact_id` | TEXT | | ID of the artifact |
| `status` | TEXT | DEFAULT 'pending' | `pending` / `dispatched` / `running` / `completed` / `failed` / `skipped` / `cancelled` |
| `priority` | INTEGER | DEFAULT 0 | Execution priority (higher = more urgent) |
| `depends_on` | TEXT | | Comma-separated list of work item IDs this depends on |
| `assigned_agent_id` | TEXT | FK -> agents, NULLABLE | Agent assigned to this work |
| `config` | TEXT | | JSON configuration for the work item |
| `result` | TEXT | | JSON result after completion |
| `retry_count` | INTEGER | DEFAULT 0 | Number of retry attempts |
| `pid` | INTEGER | | OS process ID when running |
| `log_path` | TEXT | | Path to execution log file |
| `created_at` | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | |
| `started_at` | TIMESTAMP | NULLABLE | |
| `completed_at` | TIMESTAMP | NULLABLE | |

**Indexes**: `idx_work_queue_run`, `idx_work_queue_status`, `idx_work_queue_run_status`, `idx_work_queue_project`

---

### artifact_threads

Discussion threads per artifact during pipeline execution. Supports multi-round convergence where agents comment, revise, challenge, and approve artifacts.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| `run_id` | TEXT | FK -> execution_runs, NOT NULL | Parent execution run |
| `project_id` | TEXT | FK -> projects, NOT NULL | |
| `artifact_type` | TEXT | NOT NULL | Type of artifact (e.g., `prd`, `design`, `task`) |
| `artifact_id` | TEXT | NOT NULL | ID of the artifact under discussion |
| `agent_id` | TEXT | FK -> agents, NULLABLE | Agent who posted (SET NULL on delete) |
| `agent_persona` | TEXT | | Persona type of the posting agent |
| `round_number` | INTEGER | DEFAULT 1 | Discussion round |
| `entry_type` | TEXT | NOT NULL | `comment` / `revision` / `challenge` / `approval` |
| `content` | TEXT | | Thread entry content |
| `parent_thread_id` | INTEGER | FK -> artifact_threads, NULLABLE | Parent entry for nested replies |
| `created_at` | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | |

**Indexes**: `idx_artifact_threads_run`, `idx_artifact_threads_artifact`, `idx_artifact_threads_run_artifact`, `idx_artifact_threads_entry_type`, `idx_artifact_threads_parent`

---

## Quality and Traceability Entities

### requirements

Individual requirements extracted from PRDs. Enables traceability from requirement to task to verification evidence.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | TEXT | PRIMARY KEY | Requirement ID |
| `prd_id` | TEXT | FK -> prds, NOT NULL | Source PRD |
| `req_type` | TEXT | NOT NULL | `FR` (functional) or `NFR` (non-functional) |
| `req_number` | TEXT | NOT NULL | Requirement number within PRD |
| `summary` | TEXT | NOT NULL | Requirement description |
| `depth` | TEXT | DEFAULT 'structural' | `structural` / `behavioral` |
| `created_at` | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | |

**Constraint**: UNIQUE(`prd_id`, `req_number`)

**Indexes**: `idx_requirements_prd`, `idx_requirements_type`

---

### requirement_links

Many-to-many join table between `requirements` and `tasks`. A requirement can be covered by multiple tasks, and a task can satisfy multiple requirements.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `requirement_id` | TEXT | FK -> requirements, NOT NULL | |
| `task_id` | TEXT | FK -> tasks, NOT NULL | |
| `created_at` | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | |

**Primary Key**: (`requirement_id`, `task_id`) -- composite

---

### ac_verifications

Acceptance criteria verification evidence. Records how and by whom each requirement was verified for a given task.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| `requirement_id` | TEXT | FK -> requirements, NOT NULL | Verified requirement |
| `task_id` | TEXT | FK -> tasks, NOT NULL | Task providing the implementation |
| `verified_by` | TEXT | | Who/what performed verification |
| `evidence_type` | TEXT | | Type of evidence (e.g., `test`, `review`, `demo`) |
| `evidence` | TEXT | | Verification evidence content |
| `verified_at` | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | |

**Constraint**: UNIQUE(`requirement_id`, `task_id`)

**Index**: `idx_ac_verifications_task`

---

### challenge_records

Adversarial review rounds per artifact. Used during convergence discussions where agents challenge design decisions.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| `artifact_type` | TEXT | NOT NULL | Type of artifact challenged |
| `artifact_id` | TEXT | NOT NULL | ID of the artifact |
| `round_number` | INTEGER | NOT NULL | Review round number |
| `objections` | TEXT | | Objections raised |
| `responses` | TEXT | | Responses to objections |
| `verdict` | TEXT | | Final verdict for this round |
| `challenger_context` | TEXT | | Context about the challenger |
| `status` | TEXT | DEFAULT 'open' | `open` / `resolved` |
| `created_at` | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | |

**Constraint**: UNIQUE(`artifact_type`, `artifact_id`, `round_number`)

**Index**: `idx_challenge_artifact`

---

### reviews

Review evidence per task per round. Captures self-reviews and sub-agent reviews with test output.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| `task_id` | TEXT | FK -> tasks, NOT NULL | Reviewed task |
| `project_id` | TEXT | FK -> projects, NOT NULL | |
| `round` | INTEGER | NOT NULL, DEFAULT 1 | Review round number |
| `reviewer_type` | TEXT | NOT NULL | `self` or `subagent` |
| `verdict` | TEXT | NOT NULL | Review verdict (e.g., `pass`, `fail`, `needs_revision`) |
| `findings` | TEXT | | Review findings text |
| `test_output` | TEXT | | Raw test output |
| `created_at` | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | |

**Indexes**: `idx_reviews_task`, `idx_reviews_project`

---

## Integration Entities

### sync_mappings

Links local a-sdlc entities to their counterparts in external systems (Linear, Jira). Enables bidirectional sync.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| `entity_type` | TEXT | NOT NULL | `sprint`, `prd`, or `task` |
| `local_id` | TEXT | NOT NULL | Local entity ID |
| `external_system` | TEXT | NOT NULL | `linear` or `jira` |
| `external_id` | TEXT | NOT NULL | ID in the external system |
| `sync_status` | TEXT | DEFAULT 'synced' | `synced` / `pending` / `conflict` / `error` |
| `last_synced` | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | Last successful sync time |

**Constraint**: UNIQUE(`entity_type`, `local_id`, `external_system`)

**Indexes**: `idx_sync_entity` (entity_type, local_id), `idx_sync_external` (external_system, external_id)

---

### external_config

Integration credentials and configuration per project per external system. Stores API tokens, team IDs, and other connection settings.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| `project_id` | TEXT | FK -> projects, NOT NULL | |
| `system` | TEXT | NOT NULL | `linear` or `jira` |
| `config` | JSON | NOT NULL | JSON configuration blob |
| `created_at` | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | |
| `updated_at` | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | |

**Constraint**: UNIQUE(`project_id`, `system`)

**Index**: `idx_external_config_project`

---

### worktrees

Git worktree lifecycle tracking per PRD. Each PRD can have an associated git worktree for isolated development.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | TEXT | PRIMARY KEY | Worktree ID |
| `project_id` | TEXT | FK -> projects, NOT NULL | |
| `prd_id` | TEXT | FK -> prds, NOT NULL | Associated PRD |
| `sprint_id` | TEXT | FK -> sprints, NULLABLE | Associated sprint (SET NULL on sprint delete) |
| `branch_name` | TEXT | NOT NULL | Git branch name |
| `path` | TEXT | NOT NULL | Filesystem path to the worktree |
| `status` | TEXT | DEFAULT 'active' | `active` / `cleaned` |
| `pr_url` | TEXT | | Pull request URL if one was created |
| `created_at` | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | |
| `cleaned_at` | TIMESTAMP | NULLABLE | When the worktree was removed |

**Indexes**: `idx_worktrees_project`, `idx_worktrees_prd`, `idx_worktrees_sprint`, `idx_worktrees_status`

---

## Audit and Logging

### audit_log

Append-only audit trail for governance. Records all significant actions taken by agents during execution runs.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| `project_id` | TEXT | NOT NULL | Project context |
| `agent_id` | TEXT | NULLABLE | Agent who performed the action |
| `run_id` | TEXT | NULLABLE | Execution run context |
| `action_type` | TEXT | NOT NULL | Action category |
| `target_entity` | TEXT | | Entity acted upon |
| `outcome` | TEXT | NOT NULL | Result of the action |
| `details` | TEXT | | Additional details (free text or JSON) |
| `created_at` | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | |

**Indexes**: `idx_audit_log_project`, `idx_audit_log_agent`, `idx_audit_log_run`, `idx_audit_log_action`

---

## Status Workflows

### PRD Status Flow

```
draft --> ready --> split --> completed
```

- **draft**: Initial state. Content is being written.
- **ready**: Requirements are finalized and approved. Sets `ready_at` timestamp.
- **split**: Tasks have been generated from the PRD. Sets `split_at` timestamp.
- **completed**: All derived tasks are done. Sets `completed_at` timestamp.

Transition to `draft` resets all phase timestamps (`ready_at`, `split_at`, `completed_at`).

### Task Status Flow

```
pending --> in_progress --> completed
                |  ^
                v  |
              blocked
```

- **pending**: Created but not yet started.
- **in_progress**: Agent is actively working. Sets `started_at` timestamp.
- **blocked**: Work is stalled due to a dependency or issue.
- **completed**: Work is done and verified. Sets `completed_at` timestamp.

### Sprint Status Flow

```
planned --> active --> completed
```

- **planned**: Sprint is defined but not started.
- **active**: Sprint is in progress. Sets `started_at` timestamp.
- **completed**: Sprint is finished. Triggers quality gate checks. Sets `completed_at` timestamp.

### Sync Status Flow

```
pending --> synced
  |           |
  v           v
error     conflict
```

- **pending**: Entity has been created or changed locally but not yet synced.
- **synced**: Local and external entities are in agreement.
- **conflict**: Local and external have diverged and need manual resolution.
- **error**: Sync attempt failed due to an API or connectivity issue.

### Execution Run Status Flow

```
pending --> active --> completed
              |
              +--> paused --> active
              |
              +--> awaiting_confirmation --> active
              |
              +--> failed
              |
              +--> cancelled
```

### Agent Status Flow

```
active --> suspended --> active
  |                       |
  +--------> retired <----+
```

---

## Enums (from plugins/base.py)

These Python enums define the canonical set of allowed values for status and priority fields. The database stores the string `.value` of each enum member.

| Enum | Values |
|------|--------|
| `TaskStatus` | `pending`, `in_progress`, `blocked`, `completed`, `cancelled` |
| `TaskPriority` | `low`, `medium`, `high`, `urgent` |
| `SprintStatus` | `planned`, `active`, `completed` |
| `SyncStatus` | `synced`, `pending`, `conflict`, `error` |

Note: The database schema uses `critical` as a task priority value while the `TaskPriority` enum uses `urgent`. Both are accepted in practice. The `TaskStatus` enum includes `cancelled` which is not present in the database DEFAULT constraint but is a valid runtime value.

---

## Plugin Dataclasses (from plugins/base.py)

These dataclasses are used by the plugin layer and template system. They carry richer structure than the database columns, since much of their content is serialized into the Markdown files rather than stored in SQLite.

### Task (dataclass)

Extended task representation used by plugins. Includes fields that are stored in the Markdown content file rather than the database.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `id` | str | required | Task ID |
| `title` | str | required | Task title |
| `description` | str | required | Full task description |
| `status` | TaskStatus | PENDING | Current status |
| `priority` | TaskPriority | MEDIUM | Priority level |
| `dependencies` | list[str] | [] | IDs of tasks this depends on |
| `requirement_id` | str or None | None | Source requirement ID |
| `component` | str or None | None | Component label |
| `files_to_modify` | list[str] | [] | Files the task will change |
| `implementation_steps` | list[ImplementationStep] | [] | Ordered implementation steps |
| `success_criteria` | list[str] | [] | Conditions for task completion |
| `goal` | str or None | None | Clear statement of task purpose |
| `prd_ref` | str or None | None | Reference to source PRD |
| `key_requirements` | list[str] | [] | Requirements from the PRD |
| `technical_notes` | list[str] | [] | Implementation hints |
| `deliverables` | list[str] | [] | What the task will produce |
| `exclusions` | list[str] | [] | What is explicitly out of scope |
| `scope_constraint` | str or None | None | Standard scope reminder text |
| `external_id` | str or None | None | ID in external system |
| `external_url` | str or None | None | URL in external system |
| `created_at` | datetime | now | |
| `updated_at` | datetime | now | |
| `completed_at` | datetime or None | None | |

### ImplementationStep (dataclass)

A single step within a task's implementation plan.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `title` | str | required | Step title |
| `description` | str | "" | Step description |
| `code_hint` | str or None | None | Optional code snippet or hint |
| `test_expectation` | str or None | None | Expected test outcome |

Supports backward compatibility: a plain string input is treated as the `title` with an empty description.

### ExternalSprintMapping (dataclass)

Maps a local sprint to its counterpart in an external issue tracker.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `local_sprint_id` | str | required | Local sprint ID (e.g., `SDLC-S0001`) |
| `external_system` | str | required | `linear` or `jira` |
| `external_sprint_id` | str | required | ID in the external system |
| `external_sprint_name` | str | required | Name in the external system |
| `sync_status` | SyncStatus | PENDING | Current sync status |
| `last_synced_at` | datetime or None | None | Last successful sync time |

### Sprint (dataclass)

Plugin-layer sprint representation with external system integration fields.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `id` | str | required | Sprint ID |
| `name` | str | required | Sprint name |
| `status` | SprintStatus | PLANNED | Current status |
| `goal` | str | "" | Sprint goal |
| `start_date` | datetime or None | None | Planned start date |
| `end_date` | datetime or None | None | Planned end date |
| `prd_ids` | list[str] | [] | PRDs assigned to this sprint |
| `external_id` | str or None | None | External sprint/cycle ID |
| `external_url` | str or None | None | URL to external sprint |
| `external_system` | str or None | None | `linear` or `jira` |
| `created_at` | datetime | now | |
| `completed_at` | datetime or None | None | |

---

## Schema Migration History

| Version | Changes |
|---------|---------|
| 1 | Initial schema: projects, prds, tasks, sprints |
| 2 | Added `sync_mappings` table, `external_id` to sprints |
| 3 | Added `shortname` to projects, updated ID formats |
| 4 | Added `source`, `external_id`, `external_url` to prds; `started_at` to tasks |
| 5 | Added `designs` table with `prd_id` unique constraint |
| 6 | Added `external_config` table for integration credentials |
| 7 | Added `worktrees` table for git worktree lifecycle tracking |
| 8 | Added `reviews` table for task review evidence |
| 9 | Added agent tables: `agents`, `agent_permissions`, `agent_budgets` |
| 10 | Added `execution_runs` table, `audit_log` table |
| 11 | Added `task_claims`, `agent_messages`, `agent_performance`, `agent_teams` |
| 12 | Added quality tables: `requirements`, `requirement_links`, `ac_verifications`, `challenge_records` |
| 13 | Added `work_queue` table for execution run work items |
| 14 | Added `artifact_threads` table for convergence discussions |
