# a-sdlc

**AI-native SDLC automation for Claude Code** — from vague idea to shipped code, with built-in quality feedback loops.

a-sdlc gives Claude Code a structured development workflow: ideation, PRD generation, architecture design, task decomposition, sprint execution, and retrospectives. Every step is grounded in your actual codebase — no hallucinated file paths, no speculative architecture, no scope creep.

<!-- screenshot placeholder: add workflow demo here -->

## Install

```bash
uv tool install git+https://github.com/pleelapr/a-sdlc.git
a-sdlc setup       # guided wizard: skills, MCP config, optional integrations
a-sdlc doctor      # verify everything works
```

To upgrade:

```bash
uv tool install --force git+https://github.com/pleelapr/a-sdlc.git
a-sdlc setup --upgrade
```

> Need pip, pipx, or development install? See [All Installation Methods](#all-installation-methods).

## Quick Start

In Claude Code, inside your project directory:

```
/sdlc:init      # initialize .sdlc/ structure and register project
/sdlc:scan      # analyze codebase → generate 5 living documentation artifacts
/sdlc:status    # check artifact freshness
```

## The Workflow

a-sdlc models the full development lifecycle as a series of slash commands. Each step feeds into the next, and quality gates prevent drift between what was planned and what gets built.

```
Ideate → PRD → Design → Decompose → Sprint → Complete
```

### Ideate

```
/sdlc:ideate "maybe we need better caching"
```

Exploratory Socratic dialogue that takes a vague idea and converges on well-defined requirements. Claude asks probing questions — what problem does this solve, who benefits, what constraints exist — and synthesizes the answers into one or more PRDs. No assumptions, no AI-inferred features.

### Generate PRD

```
/sdlc:prd-generate "Add OAuth authentication"
```

Structured Q&A that builds a comprehensive Product Requirements Document. Every line traces to a user answer — zero fluff. Clarifying questions cover scope, acceptance criteria, non-functional requirements, and edge cases. The PRD becomes the single source of truth for everything downstream.

### Design Architecture

```
/sdlc:prd-architect PROJ-P0001
```

Generates an ADR-style (Architecture Decision Record) design document by analyzing your actual codebase. Every design decision cites real files, real modules, real patterns already in use. If a pattern or library isn't in the codebase and the PRD doesn't require it, it doesn't appear in the design.

### Decompose into Tasks

```
/sdlc:prd-split PROJ-P0001
```

Multi-agent orchestration breaks the PRD into implementable tasks. Specialized agents handle investigation, design, content generation, and persistence. Each task gets dependency analysis, implementation steps, acceptance criteria, and a definition of done — all grounded in the design document and codebase.

### Sprint Execution

```
/sdlc:sprint-run SPRINT-01
```

Executes sprint tasks using parallel Claude Code agents. Two modes:

- **Simple mode** (single PRD): tasks run in the current branch, respecting dependency chains
- **Isolated mode** (multiple PRDs): each PRD gets its own git worktree for conflict-free parallel development

Independent tasks run concurrently. Blocked tasks wait for their dependencies to complete.

### Complete & Retrospect

```
/sdlc:sprint-complete SPRINT-01
```

Closes the sprint, updates PRD statuses, and runs an automated retrospective. The retrospective reads the correction log accumulated during the sprint, identifies patterns (categories with 2+ corrections), and proposes evidence-based lessons. Each proposed lesson requires user approval before being saved. No generic "best practices" — only lessons grounded in what actually happened.

## Self-Healing Quality System

a-sdlc includes a feedback loop that captures mistakes, distills them into lessons, and enforces them on future work.

```
  Corrections Log          Retrospective           Lesson-Learn Files
  ┌──────────────┐    ┌──────────────────┐    ┌──────────────────────┐
  │ log_correction│───▶│ sprint-complete  │───▶│ .sdlc/lesson-learn.md│
  │ during work   │    │ analyzes patterns│    │ ~/.a-sdlc/lesson-    │
  │               │    │ proposes lessons │    │   learn.md           │
  └──────────────┘    └──────────────────┘    └──────────┬───────────┘
                                                         │
                                              ┌──────────▼───────────┐
                                              │ Preflight Checks     │
                                              │ prd-split, task-start│
                                              │ sprint-run           │
                                              └──────────────────────┘
```

**How it works:**

1. **Corrections are logged** throughout the sprint via `log_correction()` — during task implementation, PRD splits, PR feedback, and ad-hoc fixes
2. **Retrospective analyzes patterns** — categories with 2+ corrections become candidate lessons, each citing specific log entries as evidence
3. **User approves lessons** — choose project-scope, global-scope, or both; set priority (MUST/SHOULD/MAY)
4. **Preflight checks enforce lessons** — before starting tasks, splitting PRDs, or running sprints, lessons are presented as rules to follow

Additional quality mechanisms:
- **Self-review**: task completion runs a definition-of-done checklist
- **Correction logging**: any workflow can record mistakes for future retrospectives
- **Anti-fluff rules**: PRDs, designs, and retrospectives reject AI-inferred content not backed by user input or codebase evidence

## Living Documentation

`/sdlc:scan` analyzes your codebase and generates 5 artifacts in `.sdlc/artifacts/`:

| Artifact | Content |
|----------|---------|
| `directory-structure.md` | Repository file tree |
| `codebase-summary.md` | Project overview, stack, dependencies |
| `architecture.md` | Component breakdown and interactions |
| `data-model.md` | Entity definitions and relationships |
| `key-workflows.md` | Traced execution flows |

These artifacts stay fresh through incremental updates:

```
/sdlc:status    # check what's stale
/sdlc:update    # refresh only changed artifacts
```

## Investigation & Analysis

```bash
/sdlc:investigate "login fails after token refresh"   # root cause analysis with web search
/sdlc:ask "how does the auth middleware work?"         # read-only Q&A about the repo
/sdlc:pr-feedback                                      # fetch, categorize, resolve PR review comments
/sdlc:sonar-scan                                       # SonarQube scan with auto-fix
/sdlc:test                                             # runtime testing via Playwright + API validation
```

## External Integrations

a-sdlc syncs sprints and tasks with external systems:

| System | What syncs | Setup |
|--------|-----------|-------|
| **Linear** | Cycles as sprints, issues as tasks | `a-sdlc connect linear` |
| **Jira** | Sprints, issues with ADF formatting | `a-sdlc connect jira` |
| **Confluence** | Publish artifacts as pages | `a-sdlc connect confluence` |

Sync operations:

```
/sdlc:sprint-import linear          # import cycle as sprint
/sdlc:sprint-sync SPRINT-01         # bidirectional sync
/sdlc:sprint-sync-to SPRINT-01      # push to external
/sdlc:sprint-sync-from SPRINT-01    # pull from external
```

Status mapping: `pending` ↔ Backlog/To Do, `in_progress` ↔ In Progress, `blocked` ↔ Blocked, `completed` ↔ Done.

## Skills Reference

### Project Setup

| Skill | Purpose |
|-------|---------|
| `/sdlc:init` | Initialize `.sdlc/` directory and register project |
| `/sdlc:scan` | Full repo scan → generate all artifacts |
| `/sdlc:update` | Incremental update of stale artifacts |
| `/sdlc:status` | Show artifact freshness |

### PRD Management

| Skill | Purpose |
|-------|---------|
| `/sdlc:ideate` | Socratic dialogue → vague idea to PRD(s) |
| `/sdlc:prd-generate` | Structured Q&A → single PRD |
| `/sdlc:prd-architect` | Design document from PRD + codebase analysis |
| `/sdlc:prd-split` | Decompose PRD into tasks |
| `/sdlc:prd-investigate` | Deep-dive analysis of a PRD |
| `/sdlc:prd-import` | Import external PRD document |
| `/sdlc:prd-update` | Update PRD metadata |
| `/sdlc:prd` | PRD management hub |
| `/sdlc:prd-list` | List all PRDs |
| `/sdlc:prd-delete` | Delete a PRD |

### Task Management

| Skill | Purpose |
|-------|---------|
| `/sdlc:task-create` | Create a task manually |
| `/sdlc:task-start` | Begin work on a task (with preflight checks) |
| `/sdlc:task-complete` | Mark task done (with DoD checklist) |
| `/sdlc:task-split` | Split a task into subtasks |
| `/sdlc:task-show` | View task details |
| `/sdlc:task-link` | Link task to external system |
| `/sdlc:task` | Task management hub |
| `/sdlc:task-list` | List all tasks |
| `/sdlc:task-delete` | Delete a task |

### Sprint Management

| Skill | Purpose |
|-------|---------|
| `/sdlc:sprint-create` | Create a new sprint |
| `/sdlc:sprint-start` | Activate a sprint |
| `/sdlc:sprint-run` | Execute sprint tasks (parallel agents) |
| `/sdlc:sprint-complete` | Close sprint + retrospective |
| `/sdlc:sprint-import` | Import sprint from Linear/Jira |
| `/sdlc:sprint-sync` | Bidirectional sync with external system |
| `/sdlc:sprint-sync-to` | Push changes to external |
| `/sdlc:sprint-sync-from` | Pull changes from external |
| `/sdlc:sprint-link` | Link sprint to external system |
| `/sdlc:sprint-unlink` | Unlink sprint from external |
| `/sdlc:sprint-show` | View sprint details |
| `/sdlc:sprint` | Sprint management hub |
| `/sdlc:sprint-list` | List all sprints |
| `/sdlc:sprint-mappings` | View sync mappings |
| `/sdlc:sprint-delete` | Delete a sprint |

### Analysis & Quality

| Skill | Purpose |
|-------|---------|
| `/sdlc:investigate` | Root cause analysis with web search |
| `/sdlc:ask` | Read-only Q&A about the repo |
| `/sdlc:pr-feedback` | Process PR review comments |
| `/sdlc:sonar-scan` | SonarQube scan + auto-fix |
| `/sdlc:test` | Runtime testing (Playwright + API) |
| `/sdlc:publish` | Publish artifacts to Confluence |
| `/sdlc:help` | List available commands |

---

<details>
<summary><strong>All Installation Methods</strong></summary>

### Prerequisites

- **Python 3.10+** — Check with `python3 --version`
- **[uv](https://docs.astral.sh/uv/)** (recommended), pip, or [pipx](https://pypa.github.io/pipx/)
- **[Claude Code](https://docs.anthropic.com/en/docs/claude-code)** — for MCP integration and `/sdlc:*` skills

```bash
# Install uv if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh
```

> **Why uv?** uv provides `uvx` which runs Python tools on-demand without permanent installation. This is how a-sdlc runs its MCP server and Serena — they are downloaded and cached automatically on first use.

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

### Optional Extras

| Extra | What it adds | Install flag |
|-------|-------------|--------------|
| `[linear]` | Linear integration (httpx) | `a-sdlc[linear]` |
| `[atlassian]` | Jira and Confluence integration (httpx) | `a-sdlc[atlassian]` |
| `[sonarqube]` | SonarQube integration (pysonar) | `a-sdlc[sonarqube]` |
| `[all]` | All of the above plus dev tools | `a-sdlc[all]` |

</details>

<details>
<summary><strong>CLI Commands Reference</strong></summary>

```bash
# Setup & diagnostics
a-sdlc setup                 # Guided setup wizard
a-sdlc setup --upgrade       # Upgrade: refresh templates, migrate DB, update MCP config
a-sdlc doctor                # Run diagnostics

# Install skills
a-sdlc install               # Deploy skills to Claude Code
a-sdlc install --list        # List installed skills
a-sdlc install --force       # Reinstall all skills
a-sdlc install --with-serena # Install skills + configure Serena MCP

# MCP setup
a-sdlc setup-mcp             # Configure Serena MCP server
a-sdlc setup-mcp --force     # Reconfigure Serena MCP

# External integrations
a-sdlc connect linear        # Connect to Linear (interactive prompts)
a-sdlc connect jira          # Connect to Jira
a-sdlc connect confluence    # Connect to Confluence
a-sdlc integrations          # List configured integrations
a-sdlc disconnect linear     # Remove integration

# Artifact publishing
a-sdlc artifacts push        # Push all unpublished artifacts to Confluence
a-sdlc artifacts push architecture  # Push specific artifact
a-sdlc artifacts push --force       # Force republish all
a-sdlc artifacts status             # Check publish status

# SonarQube
a-sdlc sonarqube configure   # Configure SonarQube connection

# Uninstall
a-sdlc uninstall                  # Remove skills, MCP config; keep project data
a-sdlc uninstall --include-data   # Remove everything including ~/.a-sdlc data
a-sdlc uninstall --dry-run        # Preview what would be removed
uv tool uninstall a-sdlc          # Remove the Python package itself
```

</details>

<details>
<summary><strong>Configuration</strong></summary>

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

</details>

<details>
<summary><strong>Serena MCP Setup</strong></summary>

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
4. Serena runs as an MCP server providing semantic code understanding

**Safe to re-run:** If Serena is already configured, `--with-serena` skips setup automatically.

</details>

<details>
<summary><strong>Monitoring Setup</strong></summary>

a-sdlc supports optional observability via Langfuse and SigNoz:

```bash
a-sdlc setup    # Select monitoring options during guided wizard
```

The setup wizard will prompt for Langfuse API keys and/or SigNoz configuration if you choose to enable monitoring.

</details>

## Development

```bash
git clone https://github.com/pleelapr/a-sdlc.git
cd a-sdlc
uv sync --all-extras

uv run pytest tests/ -v      # run tests
uv run ruff check src/       # lint
uv run mypy src/              # type check
uv run ruff format src/ tests/  # format
```

Development workflow with editable install:

```bash
uv tool install --force --editable ".[all]"   # install in editable mode
a-sdlc install --force                         # redeploy skills + MCP config
# Restart Claude Code to pick up changes
```

## License

MIT License - see LICENSE file for details.
