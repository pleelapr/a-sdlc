# Data Model

## Entity Overview

```
┌──────────┐     ┌──────────┐     ┌──────────┐
│ projects │     │ sprints  │     │ designs  │
│          │◄────│          │     │          │
│          │     └────┬─────┘     └────┬─────┘
│          │          │                │
│          │     ┌────▼─────┐         │
│          │◄────│  prds    │◄────────┘
│          │     │          │
│          │     └────┬─────┘
│          │          │
│          │     ┌────▼──────┐
│          │◄────│  tasks    │
└──────────┘     └───────────┘
                      │
                 ┌────▼──────────┐
                 │ sync_mappings │
                 └───────────────┘
```

## Entity Definitions

### projects

**Purpose**: Root entity representing a software project linked to a filesystem directory.

| Column | Type | Constraints | Description |
|--------|------|------------|-------------|
| id | TEXT | PRIMARY KEY | Slugified folder name |
| shortname | TEXT | UNIQUE, NOT NULL | 4-char uppercase key (e.g., `SDLC`) |
| name | TEXT | NOT NULL | Human-readable project name |
| path | TEXT | UNIQUE, NOT NULL | Absolute filesystem path |
| created_at | TEXT | DEFAULT CURRENT_TIMESTAMP | Creation timestamp |
| last_accessed | TEXT | DEFAULT CURRENT_TIMESTAMP | Last access timestamp |

**Relationships**: Parent of prds, tasks, sprints (via `project_id` FK)

---

### prds

**Purpose**: Product Requirements Documents — structured feature specifications.

| Column | Type | Constraints | Description |
|--------|------|------------|-------------|
| id | TEXT | PRIMARY KEY | Format: `{SHORTNAME}-P{NNNN}` |
| project_id | TEXT | FK → projects(id) | Parent project |
| sprint_id | TEXT | FK → sprints(id), NULLABLE | Optional sprint assignment |
| title | TEXT | NOT NULL | PRD title |
| file_path | TEXT | | Path to markdown content file |
| status | TEXT | DEFAULT 'draft' | One of: `draft`, `ready`, `split`, `completed` |
| version | TEXT | DEFAULT '1.0.0' | Semantic version |
| source | TEXT | | Origin: `manual`, `confluence`, `imported` |
| external_id | TEXT | | External system ID |
| external_url | TEXT | | External system URL |
| created_at | TEXT | DEFAULT CURRENT_TIMESTAMP | |
| updated_at | TEXT | DEFAULT CURRENT_TIMESTAMP | |

**Relationships**:
- Belongs to `projects` (required)
- Optionally assigned to `sprints`
- Parent of `tasks` (via `prd_id` FK)
- Has one optional `designs` (via `prd_id` FK)

---

### tasks

**Purpose**: Atomic units of work derived from splitting PRDs.

| Column | Type | Constraints | Description |
|--------|------|------------|-------------|
| id | TEXT | PRIMARY KEY | Format: `{SHORTNAME}-T{NNNNN}` |
| project_id | TEXT | FK → projects(id) | Parent project |
| prd_id | TEXT | FK → prds(id) | Parent PRD |
| title | TEXT | NOT NULL | Task title |
| file_path | TEXT | | Path to markdown content file |
| status | TEXT | DEFAULT 'pending' | One of: `pending`, `in_progress`, `blocked`, `completed` |
| priority | TEXT | DEFAULT 'medium' | One of: `low`, `medium`, `high`, `critical` |
| component | TEXT | | Component/module assignment |
| created_at | TEXT | DEFAULT CURRENT_TIMESTAMP | |
| updated_at | TEXT | DEFAULT CURRENT_TIMESTAMP | |
| completed_at | TEXT | NULLABLE | Completion timestamp |
| started_at | TEXT | NULLABLE | When work began |

**Relationships**:
- Belongs to `projects` (required)
- Belongs to `prds` (required)
- Inherits sprint membership through parent PRD (`prd.sprint_id`)

**Note**: Tasks do NOT have a direct `sprint_id` column. Sprint membership is derived through the PRD relationship.

---

### sprints

**Purpose**: Time-boxed work periods grouping PRDs and their tasks.

| Column | Type | Constraints | Description |
|--------|------|------------|-------------|
| id | TEXT | PRIMARY KEY | Format: `{SHORTNAME}-S{NNNN}` |
| project_id | TEXT | FK → projects(id) | Parent project |
| title | TEXT | NOT NULL | Sprint title |
| goal | TEXT | | Sprint goal/objective |
| status | TEXT | DEFAULT 'planned' | One of: `planned`, `active`, `completed` |
| external_id | TEXT | | External system ID (Linear cycle, Jira sprint) |
| created_at | TEXT | DEFAULT CURRENT_TIMESTAMP | |
| started_at | TEXT | NULLABLE | When sprint was activated |
| completed_at | TEXT | NULLABLE | Completion timestamp |

**Relationships**:
- Belongs to `projects` (required)
- Contains `prds` (via `prd.sprint_id` FK)
- Contains tasks transitively (via PRDs)

---

### designs

**Purpose**: ADR-style architecture design documents linked 1:1 to PRDs.

| Column | Type | Constraints | Description |
|--------|------|------------|-------------|
| id | TEXT | PRIMARY KEY | Format: `{SHORTNAME}-D{NNNN}` |
| project_id | TEXT | FK → projects(id) | Parent project |
| prd_id | TEXT | FK → prds(id), UNIQUE | Linked PRD (1:1) |
| file_path | TEXT | | Path to markdown design file |
| created_at | TEXT | DEFAULT CURRENT_TIMESTAMP | |
| updated_at | TEXT | DEFAULT CURRENT_TIMESTAMP | |

**Relationships**:
- Belongs to `projects` (required)
- Linked to exactly one `prds` (unique constraint on `prd_id`)
- Content stored at `~/.a-sdlc/content/{project_id}/designs/{prd_id}.md`

---

### sync_mappings

**Purpose**: Track linkage between local entities and external system entities for bidirectional sync.

| Column | Type | Constraints | Description |
|--------|------|------------|-------------|
| entity_type | TEXT | PK (composite) | `sprint`, `prd`, `task` |
| local_id | TEXT | PK (composite) | Local entity ID |
| external_system | TEXT | PK (composite) | `linear`, `jira`, `confluence` |
| external_id | TEXT | NOT NULL | External system entity ID |
| sync_status | TEXT | DEFAULT 'pending' | One of: `synced`, `pending`, `conflict`, `error` |
| last_synced | TEXT | | Last successful sync timestamp |
| created_at | TEXT | DEFAULT CURRENT_TIMESTAMP | |

**Composite Primary Key**: (`entity_type`, `local_id`, `external_system`)

## ID Format Reference

| Entity | Format | Example | Counter Scope |
|--------|--------|---------|---------------|
| Project | Slugified folder name | `a-sdlc` | Global unique |
| Shortname | 4 uppercase letters | `SDLC` | Global unique |
| PRD | `{SHORTNAME}-P{NNNN}` | `SDLC-P0001` | Per project |
| Task | `{SHORTNAME}-T{NNNNN}` | `SDLC-T00001` | Per project |
| Sprint | `{SHORTNAME}-S{NNNN}` | `SDLC-S0001` | Per project |
| Design | `{SHORTNAME}-D{NNNN}` | `SDLC-D0001` | Per project |

## Content File Layout

```
~/.a-sdlc/
├── data.db                              # SQLite database
└── content/
    └── {project_id}/
        ├── prds/
        │   ├── {SHORTNAME}-P0001.md
        │   └── {SHORTNAME}-P0002.md
        ├── tasks/
        │   ├── {SHORTNAME}-T00001.md
        │   └── {SHORTNAME}-T00002.md
        └── designs/
            └── {SHORTNAME}-P0001.md     # Keyed by PRD ID
```

## Status Workflows

### PRD Status Flow
```
draft → ready → split → completed
```

### Task Status Flow
```
pending → in_progress → completed
              ↓↑
           blocked
```

### Sprint Status Flow
```
planned → active → completed
```

### Sync Status Flow
```
pending → synced
    ↓        ↓
  error   conflict
```

## Schema Migration History

| Version | Changes |
|---------|---------|
| v1 | Initial schema: projects, prds, tasks, sprints |
| v2 | Added sync_mappings table, external_id to sprints |
| v3 | Added shortname to projects, updated ID formats |
| v4 | Added source, external_id, external_url to prds; started_at to tasks |
| v5 | Added designs table with prd_id unique constraint |
