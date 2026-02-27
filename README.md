# a-sdlc

SDLC Automation System for Claude Code - Generate and maintain BrainGrid-style documentation artifacts.

## Overview

a-sdlc streamlines the software development lifecycle by:

- **Generating living documentation** - Automated codebase analysis produces 5 key artifacts
- **PRD → Requirements → Tasks** - Structured workflow from product specs to implementation
- **Claude Code integration** - Skills (`/sdlc:*`) work seamlessly in your development flow
- **External integrations** - Optional sync with Linear, GitHub Issues, and more

## Prerequisites

- **Python 3.10+** — Check with `python3 --version`
- **[uv](https://docs.astral.sh/uv/)** (recommended), pip, or [pipx](https://pypa.github.io/pipx/) — for package installation
- **[Claude Code](https://docs.anthropic.com/en/docs/claude-code)** — for MCP integration and `/sdlc:*` skills

```bash
# Install uv if you don't have it (recommended)
curl -LsSf https://astral.sh/uv/install.sh | sh
```

> **Why uv?** uv provides `uvx` which runs Python tools on-demand without permanent installation. This is how a-sdlc runs its MCP server and Serena — they are downloaded and cached automatically on first use.

## Installation

### Method 1: uv tool install from GitHub (recommended)

```bash
uv tool install git+https://github.com/pleelapr/a-sdlc.git
uv tool update-shell   # Add to PATH (first time only)
# Restart terminal or: source ~/.zshenv
```

With optional extras (Linear, Jira/Confluence, or all integrations):

```bash
uv tool install "a-sdlc[linear] @ git+https://github.com/pleelapr/a-sdlc.git"
uv tool install "a-sdlc[atlassian] @ git+https://github.com/pleelapr/a-sdlc.git"
uv tool install "a-sdlc[all] @ git+https://github.com/pleelapr/a-sdlc.git"
```

### Method 2: pip install from GitHub

```bash
pip install git+https://github.com/pleelapr/a-sdlc.git

# With extras
pip install "a-sdlc[all] @ git+https://github.com/pleelapr/a-sdlc.git"
```

### Method 3: pipx install from GitHub

```bash
pipx install git+https://github.com/pleelapr/a-sdlc.git

# With extras
pipx install "a-sdlc[all] @ git+https://github.com/pleelapr/a-sdlc.git"
```

### Method 4: From GitHub Release (stable)

Download the `.whl` file from the [latest release](https://github.com/pleelapr/a-sdlc/releases/latest), then:

```bash
uv tool install ./a_sdlc-*.whl

# Or with pip
pip install ./a_sdlc-*.whl

# Or with pipx
pipx install ./a_sdlc-*.whl
```

### Method 5: Development install (for contributors)

```bash
git clone https://github.com/pleelapr/a-sdlc.git
cd a-sdlc
uv sync --all-extras
uv tool install --force --editable ".[all]"
```

### Post-Install Setup

After installing the package, run the guided setup wizard:

```bash
a-sdlc setup
```

This walks you through deploying skills, configuring the MCP server, and optional Serena integration.

Alternatively, configure manually:

```bash
# Deploy skills + configure a-sdlc MCP server
a-sdlc install

# Optional: also configure Serena MCP for code analysis
a-sdlc install --with-serena

# Verify everything is working
a-sdlc doctor
```

### Optional Extras

| Extra | What it adds | Install flag |
|-------|-------------|--------------|
| `[linear]` | Linear integration (httpx) | `a-sdlc[linear]` |
| `[atlassian]` | Jira and Confluence integration (httpx) | `a-sdlc[atlassian]` |
| `[sonarqube]` | SonarQube integration (pysonar) | `a-sdlc[sonarqube]` |
| `[all]` | All of the above plus dev tools | `a-sdlc[all]` |

### How Serena MCP Works

Serena is **not permanently installed**. When you run `a-sdlc install --with-serena`:

1. a-sdlc adds this config to `~/.claude/settings.json`:
   ```json
   {
     "mcpServers": {
       "serena": {
         "command": "uvx",
         "args": ["--from", "serena-agent", "serena"]
       }
     }
   }
   ```
2. When Claude Code starts, it runs `uvx --from serena-agent serena`
3. uvx downloads and caches serena-agent from PyPI (first time only)
4. Serena runs as an MCP server

**Safe to re-run:** If Serena is already configured, `--with-serena` skips setup automatically.

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

## External Integrations

a-sdlc supports integration with external systems for sprint/task sync and artifact publishing.

### Linear Setup

```bash
# Via Claude Code MCP
# Use configure_linear tool with:
#   api_key: from Linear Settings > API
#   team_id: e.g., 'ENG'

# Via CLI
a-sdlc connect linear --api-key KEY --team-id TEAM [--default-project PROJECT]
a-sdlc connect linear  # Interactive prompts
```

### Jira Setup

```bash
# Via Claude Code MCP
# Use configure_jira tool with:
#   base_url: https://company.atlassian.net
#   email: your@email.com
#   api_token: from id.atlassian.com/manage-profile/security/api-tokens
#   project_key: e.g., 'PROJ'

# Via CLI
a-sdlc connect jira --url URL --email EMAIL --api-token TOKEN --project-key KEY
a-sdlc connect jira  # Interactive prompts
```

### Confluence Setup

```bash
# Via Claude Code MCP
# Use configure_confluence tool with:
#   base_url: https://company.atlassian.net
#   email: your@email.com
#   api_token: from id.atlassian.com/manage-profile/security/api-tokens
#   space_key: e.g., 'PROJ'

# Via CLI
a-sdlc connect confluence --url URL --email EMAIL --api-token TOKEN --space-key KEY
a-sdlc connect confluence  # Interactive prompts
```

### Managing Integrations

```bash
# List configured integrations
a-sdlc integrations

# Remove an integration
a-sdlc disconnect linear
a-sdlc disconnect jira
a-sdlc disconnect confluence
```

### Sprint Sync Operations

Once connected to Linear or Jira, you can sync sprints:

```bash
# Import a sprint from external system
/sdlc:sprint-import linear           # Import Linear cycle
/sdlc:sprint-import jira --board-id <id>  # Import Jira sprint

# Link existing sprint to external system
/sdlc:sprint-link SPRINT-01 linear <cycle-id>
/sdlc:sprint-link SPRINT-01 jira <sprint-id>

# Sync changes
/sdlc:sprint-sync SPRINT-01           # Bidirectional sync
/sdlc:sprint-sync-from SPRINT-01      # Pull from external
/sdlc:sprint-sync-to SPRINT-01        # Push to external

# Unlink sprint
/sdlc:sprint-unlink SPRINT-01
```

### Artifact Publishing (Confluence)

Push generated artifacts to Confluence:

```bash
# Push all unpublished artifacts
a-sdlc artifacts push

# Push specific artifact
a-sdlc artifacts push architecture

# Force republish all
a-sdlc artifacts push --force

# Check sync status
a-sdlc artifacts status
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
git clone https://github.com/pleelapr/a-sdlc.git
cd a-sdlc
uv sync --all-extras

# Run tests
uv run pytest

# Run linting
uv run ruff check src/
uv run mypy src/
```

### Local Installation (Editable Mode)

When developing a-sdlc, use editable mode to test changes without reinstalling:

```bash
# Install locally in editable mode (run from project root)
uv tool install --force --editable ".[all]"

# Deploy skills + configure MCP server
a-sdlc install --force

# Optional: Also configure Serena MCP for code analysis
a-sdlc install --force --with-serena
```

**What gets installed:**

| Command | What it does |
|---------|--------------|
| `uv tool install ...` | Installs CLI, Python package, all dependencies |
| `a-sdlc install --force` | Deploys skills to `~/.claude/commands/sdlc/` AND configures a-sdlc MCP server in `~/.claude.json` |
| `--with-serena` | Also configures Serena MCP in `~/.claude/settings.json` |

**Development workflow:**
1. Make changes to source code or templates
2. If you changed Python code: run `uv tool install --force --editable ".[all]"`
3. If you only changed templates/skills: run `a-sdlc install --force`
4. Restart Claude Code to pick up changes

## License

MIT License - see LICENSE file for details.
