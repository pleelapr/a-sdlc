# /sdlc:status - Show Artifact Freshness

Display the status of all SDLC artifacts, showing which are current and which need updates.

## Purpose

Quickly assess the state of your SDLC documentation to determine if updates are needed.

## Execution Steps

### 1. Check .sdlc Directory Exists

If `.sdlc/` doesn't exist:
```
SDLC not initialized!

Run /sdlc:init to set up SDLC for this project.
```

### 2. Load Cache Data

Read `.sdlc/.cache/checksums.json`:
- Last scan timestamp
- Artifact checksums
- Source file checksums

### 3. Detect Changes

#### Git-based Detection (Primary)

```bash
# Get files changed since last scan
git log --oneline --since="<last_scan_timestamp>" --name-only
```

#### Checksum-based Detection (Fallback)

Compare current source file checksums against cached values.

### 4. Calculate Freshness

For each artifact, determine:
- **Fresh**: No relevant source files changed
- **Stale**: Relevant source files have changed
- **Missing**: Artifact doesn't exist

### 5. Gather Task Status

Read task index to show:
- Total tasks
- Tasks by status (pending, in-progress, completed)
- Current active task

### 6. Check Requirements Status

Read requirements to show:
- Current requirements document exists
- Number of requirements
- PRDs pending processing

## Output Format

```
╭──────────────────────────────────────────────────────────╮
│                    SDLC Status Report                     │
│                     2025-01-21 14:30                      │
╰──────────────────────────────────────────────────────────╯

📁 Artifacts

  ┌────────────────────────┬──────────┬─────────────────────┐
  │ Artifact               │ Status   │ Last Updated        │
  ├────────────────────────┼──────────┼─────────────────────┤
  │ directory-structure.md │ ✅ Fresh  │ 2025-01-21 10:00   │
  │ codebase-summary.md    │ ✅ Fresh  │ 2025-01-21 10:00   │
  │ architecture.md        │ ⚠️ Stale  │ 2025-01-20 15:30   │
  │ data-model.md          │ ⚠️ Stale  │ 2025-01-19 09:00   │
  │ key-workflows.md       │ ✅ Fresh  │ 2025-01-21 10:00   │
  └────────────────────────┴──────────┴─────────────────────┘

  Changes detected:
    - src/auth/models.py (modified)
    - src/auth/service.py (added)

  Recommendation: Run /sdlc:update to refresh stale artifacts

📋 Requirements

  Status: Current requirements exist
  Document: .sdlc/requirements/current.md
  Requirements: 8 functional, 3 non-functional

  PRD Inbox: 1 pending
    - feature-dashboard.md (awaiting /sdlc:prd-generate)

📌 Tasks

  ┌─────────────────┬───────┐
  │ Status          │ Count │
  ├─────────────────┼───────┤
  │ Pending         │   5   │
  │ In Progress     │   1   │
  │ Blocked         │   1   │
  │ Completed       │   8   │
  └─────────────────┴───────┘

  Current task: TASK-006 "Implement FR-004 in data-layer"

  Blocked: TASK-007 (Waiting for API credentials)

🔌 Plugin

  Task storage: local (.sdlc/tasks/)

╭──────────────────────────────────────────────────────────╮
│ Quick Actions                                             │
│                                                           │
│   /sdlc:update         - Refresh stale artifacts          │
│   /sdlc:prd-generate      - Process pending PRD              │
│   /sdlc:task-list      - View all tasks                   │
│   /sdlc:task-complete  - Complete current task            │
╰──────────────────────────────────────────────────────────╯
```

## Status Indicators

| Indicator | Meaning |
|-----------|---------|
| ✅ Fresh | Artifact is up-to-date |
| ⚠️ Stale | Source files changed since last generation |
| ❌ Missing | Artifact doesn't exist |
| ⏳ Generating | Artifact is being generated |

## Staleness Detection Rules

| Artifact | Stale If Changed |
|----------|-----------------|
| directory-structure | Any file/dir added or removed |
| codebase-summary | package.json, pyproject.toml, README, docker* |
| architecture | New modules, *service*.py, *agent*.py |
| data-model | *schema*.py, *model*.py, types.py |
| key-workflows | graph.py, *handler*.py, *workflow*.py |

## Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--json` | Output as JSON | false |
| `--brief` | Minimal output | false |
| `--artifacts` | Show only artifact status | false |
| `--tasks` | Show only task status | false |

## Examples

```
/sdlc:status                  # Full status report
/sdlc:status --brief          # Just the summary
/sdlc:status --json           # Machine-readable output
/sdlc:status --artifacts      # Only artifact freshness
/sdlc:status --tasks          # Only task overview
```

## Brief Output Mode

```
/sdlc:status --brief

SDLC: 2/5 artifacts stale | Tasks: 5 pending, 1 active | PRD: 1 pending
Recommendation: /sdlc:update
```

## JSON Output Mode

```json
{
  "timestamp": "2025-01-21T14:30:00Z",
  "artifacts": {
    "directory-structure": {"status": "fresh", "updated": "2025-01-21T10:00:00Z"},
    "codebase-summary": {"status": "fresh", "updated": "2025-01-21T10:00:00Z"},
    "architecture": {"status": "stale", "updated": "2025-01-20T15:30:00Z"},
    "data-model": {"status": "stale", "updated": "2025-01-19T09:00:00Z"},
    "key-workflows": {"status": "fresh", "updated": "2025-01-21T10:00:00Z"}
  },
  "requirements": {
    "exists": true,
    "functional_count": 8,
    "nonfunctional_count": 3
  },
  "tasks": {
    "pending": 5,
    "in_progress": 1,
    "blocked": 1,
    "completed": 8
  },
  "prd_inbox": 1,
  "recommendations": ["/sdlc:update", "/sdlc:prd-generate"]
}
```

## Notes

- Run status check frequently to stay aware of documentation drift
- Stale artifacts should be updated before major development sessions
- The `--brief` mode is useful for terminal prompts or status bars
