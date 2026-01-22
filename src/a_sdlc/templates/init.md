# /sdlc:init - Initialize SDLC for Project

Initialize the `.sdlc/` directory structure for a project, setting up the foundation for automated documentation and workflow management.

## Execution Steps

### 1. Check for Existing .sdlc Directory

First, check if `.sdlc/` already exists:

```
Check if .sdlc/ directory exists in the current project root
```

**If exists**: Ask user whether to:
- Skip initialization (keep existing)
- Reset and reinitialize (backup existing first)

### 2. Create Directory Structure

Create the following directory structure:

```
.sdlc/
├── artifacts/              # Living documentation (auto-updated)
├── requirements/           # Requirements management
│   └── versions/          # Version history
├── tasks/                  # Task management
│   ├── active/            # Current tasks
│   └── completed/         # Archived tasks
├── prd/                    # PRD ingestion
│   ├── inbox/             # New PRDs
│   └── processed/         # Processed PRDs
├── templates/              # Customizable templates
└── .cache/                 # Scan cache for incremental updates
```

### 3. Detect Project Type

Analyze the project to determine its type:

1. Check for `pyproject.toml` or `setup.py` → Python project
2. Check for `package.json` → Node.js/TypeScript project
3. Check for `go.mod` → Go project
4. Check for `Cargo.toml` → Rust project
5. Check for `pom.xml` or `build.gradle` → Java project
6. Default to "mixed" if multiple or unknown

### 4. Create Configuration File

Create `.sdlc/config.yaml` with detected settings:

```yaml
version: "1.0"
project:
  name: "<detected from package file or directory name>"
  type: "<detected project type>"

artifacts:
  enabled:
    - codebase-summary
    - architecture
    - data-model
    - key-workflows
    - directory-structure

scanning:
  include:
    - "src/"
    - "lib/"
    - "app/"
  exclude:
    - "**/__pycache__/"
    - "**/node_modules/"
    - "**/.git/"
    - "**/dist/"
    - "**/build/"

requirements:
  id_prefix: "FR"
  template: "bdd"

tasks:
  id_prefix: "TASK"
  auto_dependencies: true

plugins:
  tasks:
    provider: "local"
    local:
      path: ".sdlc/tasks"
```

### 5. Copy Artifact Templates

Copy default artifact templates to `.sdlc/templates/`:

- `codebase-summary.template.md`
- `architecture.template.md`
- `data-model.template.md`
- `key-workflows.template.md`
- `directory-structure.template.md`
- `requirements.template.md`
- `task.template.md`

### 6. Create Task Index

Create `.sdlc/tasks/index.json`:

```json
{
  "tasks": {},
  "counter": 0
}
```

### 7. Update .gitignore (Optional)

If a `.gitignore` exists, suggest adding:

```
# SDLC cache
.sdlc/.cache/
```

### 8. Output Summary

Print initialization summary:

```
SDLC Initialized Successfully!

Project: <project_name>
Type: <project_type>
Location: .sdlc/

Next steps:
1. Run /sdlc:scan to generate initial artifacts
2. Review .sdlc/config.yaml to customize settings
3. Add artifact references to your CLAUDE.md:

   # SDLC Context
   @.sdlc/artifacts/codebase-summary.md
   @.sdlc/artifacts/architecture.md
   @.sdlc/requirements/current.md
```

## Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--reset` | Clear existing .sdlc and reinitialize | false |
| `--minimal` | Create minimal structure (no templates) | false |

## Examples

```
/sdlc:init                    # Standard initialization
/sdlc:init --reset            # Reset and reinitialize
/sdlc:init --minimal          # Minimal structure only
```

## Notes

- This command only creates the structure; it does not scan the codebase
- Run `/sdlc:scan` after initialization to generate artifacts
- Templates can be customized in `.sdlc/templates/` after init
