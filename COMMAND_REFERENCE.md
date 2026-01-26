# a-sdlc Command Reference

**Quick reference for all standardized `/sdlc:*` commands**

---

## Core Commands

Single-word commands for project setup and maintenance:

| Command | Description | Example |
|---------|-------------|---------|
| `/sdlc:init` | Initialize .sdlc/ structure | `/sdlc:init` |
| `/sdlc:scan` | Full repository scan | `/sdlc:scan` |
| `/sdlc:status` | Show artifact freshness | `/sdlc:status` |
| `/sdlc:update` | Incremental updates | `/sdlc:update` |
| `/sdlc:help` | List all commands | `/sdlc:help` |
| `/sdlc:publish` | Publish artifacts | `/sdlc:publish` |

---

## PRD Commands

Product Requirements Document management:

| Command | Description | Example |
|---------|-------------|---------|
| `/sdlc:prd-generate` | Create new PRD interactively | `/sdlc:prd-generate "Add OAuth"` |
| `/sdlc:prd-list` | List all PRDs | `/sdlc:prd-list` |
| `/sdlc:prd-update` | Update existing PRD | `/sdlc:prd-update "feature-auth"` |
| `/sdlc:prd-split` | Split PRD into tasks | `/sdlc:prd-split "feature-auth"` |

### PRD Workflow

```
1. /sdlc:prd-generate "Your feature description"
2. /sdlc:prd-list
3. /sdlc:prd-update "prd-id" (if needed)
4. /sdlc:prd-split "prd-id"
```

---

## Task Commands

Implementation task management:

| Command | Description | Example |
|---------|-------------|---------|
| `/sdlc:task-split` | Create tasks from requirements | `/sdlc:task-split` |
| `/sdlc:task-list` | List all tasks | `/sdlc:task-list` |
| `/sdlc:task-show` | Show task details | `/sdlc:task-show TASK-001` |
| `/sdlc:task-start` | Start working on task | `/sdlc:task-start TASK-001` |
| `/sdlc:task-complete` | Mark task as done | `/sdlc:task-complete TASK-001` |
| `/sdlc:task-create` | Manually create task | `/sdlc:task-create` |
| `/sdlc:task-link` | Link to external tracker | `/sdlc:task-link TASK-001 ENG-123` |

### Task Workflow

```
1. /sdlc:task-split (or /sdlc:prd-split)
2. /sdlc:task-list
3. /sdlc:task-start TASK-001
4. [Do the work]
5. /sdlc:task-complete TASK-001
```

---

## Naming Convention

**Pattern**: `/sdlc:{main-command}-{subcommand}`

### Rules

- **Single-word commands**: No hyphens (e.g., `/sdlc:init`)
- **Multi-word commands**: Use hyphens (e.g., `/sdlc:prd-generate`)
- **Consistent**: All commands follow this pattern
- **Clear**: Distinguishes main command from subcommand

### Examples

✅ **Correct**:
- `/sdlc:prd-generate "description"`
- `/sdlc:task-start TASK-001`
- `/sdlc:task-list --active`

❌ **Incorrect**:
- ~~`/sdlc:prd generate "description"`~~ (spaces deprecated)
- ~~`/sdlc:task start TASK-001`~~ (spaces deprecated)
- ~~`/sdlc:taskList`~~ (wrong format)

---

## Common Options

### PRD Options

```bash
/sdlc:prd-update "prd-id" --section "Goals"   # Update specific section
/sdlc:prd-update "prd-id" --fix              # Quick fix mode
/sdlc:prd-update "prd-id" --push             # Push to Confluence
/sdlc:prd-split "prd-id" --sync              # Sync to external tracker
```

### Task Options

```bash
/sdlc:task-list --active                     # Only active tasks
/sdlc:task-list --completed                  # Only completed
/sdlc:task-list --priority high              # Filter by priority
/sdlc:task-list --component auth             # Filter by component
```

---

## Quick Start

### First Time Setup

```
1. /sdlc:init                        # Initialize project
2. /sdlc:scan                        # Generate artifacts
3. /sdlc:status                      # Check what's created
```

### Creating Your First PRD

```
1. /sdlc:prd-generate "Your feature"  # Interactive creation
2. /sdlc:prd-list                     # Verify it's created
3. /sdlc:prd-split "prd-id"           # Generate tasks
```

### Working on Tasks

```
1. /sdlc:task-list                   # See all tasks
2. /sdlc:task-start TASK-001         # Start first task
3. [Implement the task]
4. /sdlc:task-complete TASK-001      # Mark as done
```

---

## Cheat Sheet

### Most Used Commands

```bash
# Project initialization
/sdlc:init
/sdlc:scan

# PRD workflow
/sdlc:prd-generate "description"
/sdlc:prd-list
/sdlc:prd-split "prd-id"

# Task workflow
/sdlc:task-list
/sdlc:task-start TASK-001
/sdlc:task-complete TASK-001

# Maintenance
/sdlc:status
/sdlc:update
```

### One-Line Workflows

```bash
# Initialize new project
/sdlc:init && /sdlc:scan

# Create PRD and tasks
/sdlc:prd-generate "feature" && /sdlc:prd-split "feature-id"

# Start next task
/sdlc:task-list --active && /sdlc:task-start TASK-001
```

---

## Tips & Tricks

### Autocomplete

Type `/sdlc:` in Claude Code to see all available commands with autocomplete suggestions.

### Command Discovery

```bash
/sdlc:help                # Full command reference
/sdlc:help --brief        # Compact list
```

### Status Checking

```bash
/sdlc:status              # See what needs updating
/sdlc:prd-list           # See all PRDs
/sdlc:task-list          # See all tasks
```

### Filtering

```bash
/sdlc:task-list --active --priority high
/sdlc:task-list --component auth
```

---

## Command Categories

### 📚 Setup (Run Once)
- `/sdlc:init` - Initialize project structure

### 🔍 Discovery (Run as Needed)
- `/sdlc:scan` - Generate all artifacts
- `/sdlc:status` - Check freshness
- `/sdlc:update` - Refresh stale artifacts

### 📋 Requirements (PRD Workflow)
- `/sdlc:prd-generate` - Create PRD
- `/sdlc:prd-list` - View all PRDs
- `/sdlc:prd-update` - Modify PRD
- `/sdlc:prd-split` - Generate tasks

### ✅ Tasks (Development Workflow)
- `/sdlc:task-split` - Create tasks
- `/sdlc:task-list` - View tasks
- `/sdlc:task-show` - Task details
- `/sdlc:task-start` - Begin work
- `/sdlc:task-complete` - Finish work
- `/sdlc:task-create` - Manual task
- `/sdlc:task-link` - External link

### 📖 Help
- `/sdlc:help` - Command reference
- `/sdlc:publish` - Publish artifacts

---

## Integration Points

### External Trackers

```bash
# Link to Jira
/sdlc:task-link TASK-001 PROJ-123

# Sync tasks to Linear
/sdlc:prd-split "prd-id" --sync
```

### Confluence

```bash
# Push PRD to Confluence
/sdlc:prd-update "prd-id" --push
```

---

## Version

**Command Format Version**: 1.0 (Hyphenated)
**Effective Date**: 2026-01-22

---

## See Also

- [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md) - How to update to latest commands
- [IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md) - Technical details
- `/sdlc:help` - Interactive help in Claude Code
