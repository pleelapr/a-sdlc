# a-sdlc

SDLC Automation System for Claude Code - Generate and maintain BrainGrid-style documentation artifacts.

## Overview

a-sdlc streamlines the software development lifecycle by:

- **Generating living documentation** - Automated codebase analysis produces 5 key artifacts
- **PRD → Requirements → Tasks** - Structured workflow from product specs to implementation
- **Claude Code integration** - Skills (`/sdlc:*`) work seamlessly in your development flow
- **External integrations** - Optional sync with Linear, GitHub Issues, and more

## Installation

```bash
# Install via uv (recommended)
uv tool install a-sdlc
uv tool update-shell   # Add to PATH (first time only)
# Restart terminal or: source ~/.zshenv

# Or via pipx (alternative)
pipx install a-sdlc

# Deploy skills to Claude Code
a-sdlc install

# Set up Serena MCP for code analysis (recommended)
# Safe to re-run - skips if already configured
a-sdlc setup-mcp

# Verify installation
a-sdlc doctor
```

### One-liner Setup

```bash
uv tool install a-sdlc && uv tool update-shell && source ~/.zshenv && a-sdlc install --with-serena
```

## Quick Start

```bash
# In your project directory, using Claude Code:

/sdlc:init      # Initialize .sdlc/ structure
/sdlc:scan      # Generate all documentation artifacts
/sdlc:status    # Check artifact freshness
```

## Skills Reference

| Skill | Purpose |
|-------|---------|
| `/sdlc:init` | Initialize `.sdlc/` directory structure |
| `/sdlc:scan` | Full repo scan → generate all artifacts |
| `/sdlc:update` | Incremental update of stale artifacts |
| `/sdlc:prd` | PRD ingestion → draft requirements |
| `/sdlc:task` | Requirements → actionable tasks |
| `/sdlc:status` | Show artifact freshness |

## Generated Artifacts

The system generates 5 living documentation artifacts in `.sdlc/artifacts/`:

| Artifact | Content |
|----------|---------|
| `directory-structure.md` | Repository file tree |
| `codebase-summary.md` | Project overview, stack, dependencies |
| `architecture.md` | Component breakdown and interactions |
| `data-model.md` | Entity definitions and relationships |
| `key-workflows.md` | Traced execution flows |

## Directory Structure

After initialization, your project will have:

```
.sdlc/
├── artifacts/              # Generated documentation
│   ├── codebase-summary.md
│   ├── architecture.md
│   ├── data-model.md
│   ├── key-workflows.md
│   └── directory-structure.md
├── requirements/           # Requirements management
│   ├── current.md
│   └── versions/
├── tasks/                  # Task tracking
│   ├── active/
│   ├── completed/
│   └── index.json
├── prd/                    # PRD pipeline
│   ├── inbox/
│   └── processed/
├── templates/              # Customizable templates
└── config.yaml             # Project configuration
```

## Workflow Example

### 1. Initialize and Scan

```bash
/sdlc:init    # Creates .sdlc/ structure
/sdlc:scan    # Analyzes codebase, generates artifacts
```

### 2. Import a PRD

```bash
/sdlc:prd ingest docs/feature-spec.md   # Import PRD
/sdlc:prd draft                          # Generate requirements
/sdlc:prd review                         # Approve requirements
```

### 3. Create and Work Tasks

```bash
/sdlc:task split               # Create tasks from requirements
/sdlc:task list                # View all tasks
/sdlc:task start TASK-001      # Begin work on task
/sdlc:task complete TASK-001   # Mark task done
```

### 4. Keep Documentation Fresh

```bash
/sdlc:status    # Check what's stale
/sdlc:update    # Refresh changed artifacts
```

## Plugin System

Task storage can be configured with different backends:

### Local (Default)

Tasks stored as files in `.sdlc/tasks/`:

```yaml
# .sdlc/config.yaml
plugins:
  tasks:
    provider: "local"
```

### Linear Integration

Sync tasks with Linear issue tracker:

```bash
a-sdlc plugins enable linear
a-sdlc plugins configure linear
```

```yaml
# .sdlc/config.yaml
plugins:
  tasks:
    provider: "linear"
    linear:
      team_id: "ENG"
      sync_on_create: true
      sync_on_complete: true
```

## Claude Code Integration

Add artifact references to your project's `.claude/CLAUDE.md`:

```markdown
# SDLC Context
@.sdlc/artifacts/codebase-summary.md
@.sdlc/artifacts/architecture.md
@.sdlc/artifacts/data-model.md
@.sdlc/requirements/current.md
```

This gives Claude Code context about your codebase structure and requirements.

## CLI Commands

```bash
a-sdlc install               # Deploy skills to Claude Code
a-sdlc install --list        # List installed skills
a-sdlc install --force       # Reinstall all skills
a-sdlc install --with-serena # Install skills + configure Serena MCP
a-sdlc setup-mcp             # Configure Serena MCP server
a-sdlc setup-mcp --force     # Reconfigure Serena MCP
a-sdlc doctor                # Run diagnostics
a-sdlc plugins list          # List available plugins
a-sdlc plugins enable <name>     # Enable a plugin
a-sdlc plugins configure <name>  # Configure a plugin
```

## Configuration

Project configuration in `.sdlc/config.yaml`:

```yaml
version: "1.0"
project:
  name: "my-project"
  type: "python"  # python | typescript | mixed

artifacts:
  enabled:
    - codebase-summary
    - architecture
    - data-model
    - key-workflows
    - directory-structure

scanning:
  include: ["src/", "lib/"]
  exclude: ["**/__pycache__/", "**/node_modules/"]

requirements:
  id_prefix: "FR"
  template: "bdd"

tasks:
  id_prefix: "TASK"
  auto_dependencies: true
```

## Development

```bash
# Clone and set up development environment
git clone https://github.com/a-sdlc/a-sdlc.git
cd a-sdlc
uv sync --all-extras

# Run tests
uv run pytest

# Run linting
uv run ruff check src/
uv run mypy src/
```

## License

MIT License - see LICENSE file for details.
