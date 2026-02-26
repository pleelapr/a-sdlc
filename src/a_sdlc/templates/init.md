# /sdlc:init - Initialize SDLC for Project

Initialize a-sdlc for the current project. This registers the project in the a-sdlc database and sets up the foundation for task, PRD, and sprint management.

## Quick Start

### Step 1: Determine Project Name and Generate Shortname

First, determine the project name from the current directory (or user input) and generate a suggested shortname:

```
Project name: {folder_name or user-provided name}
Suggested shortname: {4 uppercase letters derived from project name}
```

**Shortname generation rules:**
- Extract 4 uppercase letters from project name
- Prefer consonants and significant letters
- Examples: "my-project" → "MYPR", "api-gateway" → "APGT", "user-service" → "USRS"

### Step 2: Confirm Shortname with User

**IMPORTANT: Always ask the user before initializing.**

Present the suggestion and ask:

> "Your project shortname will be **{SUGGESTED}**. This is used as a prefix for all entity IDs:
> - Tasks: `{SUGGESTED}-T00001`
> - Sprints: `{SUGGESTED}-S0001`
> - PRDs: `{SUGGESTED}-P0001`
>
> Would you like to use this shortname or provide a custom one?"

**Options to present:**
1. Use suggested shortname `{SUGGESTED}` (default)
2. Enter custom shortname (must be exactly 4 uppercase letters A-Z)

Wait for user response before proceeding.

### Step 3: Initialize Project

Once the user confirms their choice:

```
mcp__asdlc__init_project(shortname="{chosen_shortname}")
```

Or with a custom project name:

```
mcp__asdlc__init_project(name="My Project", shortname="{chosen_shortname}")
```

This will:
1. Register the project with the chosen shortname
2. Create the project in the a-sdlc database
3. Generate `CLAUDE.md` in the project root (with lesson-learn and correction logging rules)
4. Generate `.sdlc/lesson-learn.md` (project-level lessons tracking)
5. Generate `~/.a-sdlc/lesson-learn.md` (global lessons, if it doesn't exist)
6. Return the project context with ID format examples

**Note:** If `CLAUDE.md` or `lesson-learn.md` already exists, they will NOT be overwritten.

### Upgrade Path: Existing Project

If `init_project()` returns `status: "exists"`, the project is already registered. Instead of stopping, perform an upgrade check using the `init_files` context from the response:

#### 3a. Check CLAUDE.md

Read the project's `CLAUDE.md`. Search for the marker `<!-- a-sdlc:managed -->`.

- **If marker is missing**: Append the a-sdlc integration block at the end of the file:

```markdown
## a-sdlc Integration
<!-- a-sdlc:managed -->

This project uses a-sdlc for SDLC management.

**Before starting work, read these files:**
- `.sdlc/lesson-learn.md` — Project-specific lessons and rules
- `~/.a-sdlc/lesson-learn.md` — Global cross-project lessons
- `.sdlc/artifacts/` — Generated codebase documentation (if available)

**During work:**
- Log corrections to `.sdlc/corrections.log` when fixing mistakes
- Update lesson-learn files when patterns emerge
- Use `/sdlc:help` for available commands
```

- **If marker exists but content is outdated**: Replace the content between `<!-- a-sdlc:managed -->` and the next `## ` heading (or end of file) with the block above.
- **If marker exists and content is current**: No changes needed.

#### 3b. Check `.sdlc/lesson-learn.md`

If `init_files.lesson_learn` is `false`, create `.sdlc/lesson-learn.md` with the standard lesson-learn template content:

```markdown
# Lessons Learned

Rules and patterns discovered during development. Claude Code reads this file at the start of every session and follows these lessons during all work.

**Priority Levels:**
- **MUST** — Always follow. Never skip without explicit user override
- **SHOULD** — Follow by default. Skip only with justification
- **MAY** — Consider when relevant. Skip freely if not applicable

## Testing

<!-- Lessons about test coverage, test quality, edge cases -->

## Code Quality

<!-- Lessons about code style, duplication, naming, patterns -->

## Task Completeness

<!-- Lessons about missing requirements, incomplete implementations -->

## Integration

<!-- Lessons about component wiring, API contracts, cross-module issues -->

## Documentation

<!-- Lessons about missing docs, unclear comments, outdated references -->
```

#### 3c. Check `~/.a-sdlc/lesson-learn.md`

If the global lesson-learn file does not exist at `~/.a-sdlc/lesson-learn.md`, create it with the same template content as above.

#### 3d. Check `.sdlc/` directory structure

If `init_files.sdlc_dir` is `false`, or if subdirectories are missing, create:

```bash
mkdir -p .sdlc/artifacts
mkdir -p .sdlc/.cache
```

#### 3e. Check `.sdlc/config.yaml`

If `.sdlc/config.yaml` does not exist, create it with the default `testing` and `review` sections (see Step 6 below for the full template).

If `.sdlc/config.yaml` exists, read it and check whether `testing` and `review` top-level keys are present:
- If both sections exist: No changes needed
- If sections are missing: Append the missing sections to the existing file (preserve existing content)

#### 3f. Report Upgrade Results

Report what was created or updated to the user:

```
✓ Project upgrade check complete: {project_name}

  Shortname: {shortname}
  Project ID: {project_id}

  Checked/Updated:
  - CLAUDE.md: {created a-sdlc block | already current | appended a-sdlc block}
  - .sdlc/config.yaml: {created | added testing/review sections | already current}
  - .sdlc/lesson-learn.md: {created | already exists}
  - ~/.a-sdlc/lesson-learn.md: {created | already exists}
  - .sdlc/artifacts/: {created | already exists}
  - .sdlc/.cache/: {created | already exists}
```

Then skip to the **Output** section (do not repeat Steps 4-6 for existing projects).

---

### Step 4: Create Project Folder Structure

After successful registration, create the `.sdlc/` directory structure:

```bash
mkdir -p .sdlc/artifacts
mkdir -p .sdlc/.cache
```

This creates:
- `.sdlc/artifacts/` - For generated documentation (architecture, data-model, etc.)
- `.sdlc/.cache/` - For checksums and scan metadata (always gitignored)

### Step 5: Configure .gitignore

Ask the user about artifact tracking preference:

> "Would you like to track `.sdlc/artifacts/` in version control?
> - **Yes (recommended)**: Documentation artifacts are versioned with code
> - **No**: Artifacts are gitignored and regenerated as needed"

**Options to present:**
1. Yes, track artifacts in git (recommended)
2. No, gitignore artifacts

Then update `.gitignore` (create if it doesn't exist):

**If user chose "Yes" (track artifacts):**
```
# a-sdlc cache (always excluded)
.sdlc/.cache/
```

**If user chose "No" (gitignore artifacts):**
```
# a-sdlc cache (always excluded)
.sdlc/.cache/

# a-sdlc artifacts (regenerated via /sdlc:scan)
.sdlc/artifacts/
```

### Step 6: Generate config.yaml

Create `.sdlc/config.yaml` with default testing and review configuration (if it doesn't already exist):

```yaml
testing:
  defaults:
    # Required test types for all tasks (unless overridden or deemed irrelevant)
    required:
    - unit
    - integration
    # Available test types: unit, integration, e2e, performance, security, accessibility
  commands:
    # Commands to run for each test type (project-specific)
    unit: ""
    integration: ""
    e2e: ""
  coverage:
    # Minimum coverage threshold (percentage) — 0 to disable
    min_threshold: 0
  relevance:
    # Smart relevance detection — skip test types that don't apply to a change
    # When enabled, the reviewer assesses which test types are relevant based on change scope
    enabled: true

review:
  self_review:
    # Whether implementing agent must self-review before subagent review
    enabled: true
  subagent_review:
    # Whether a fresh subagent performs independent review after self-review
    enabled: true
  # Maximum self-heal iterations before escalating to user
  max_rounds: 3
  # Require actual test command output before marking task complete
  evidence_required: true
```

**Customization prompt**: After writing the default config, ask the user:

> "Default testing and review configuration has been created in `.sdlc/config.yaml`.
>
> Would you like to customize your test commands now?
> - **unit**: Command to run unit tests (e.g., `pytest tests/`, `npm test`)
> - **integration**: Command to run integration tests (leave empty if not applicable)
> - **e2e**: Command to run end-to-end tests (leave empty if not applicable)"

If the user provides test commands, update the `testing.commands` section accordingly.

**If `.sdlc/config.yaml` already exists**, read it and check whether `testing` and `review` sections are present:
- If both sections exist: No changes needed
- If sections are missing: Append the missing sections to the existing file (preserve existing content like `sonarqube` configuration)

## MCP Tools Available

After initialization, the following MCP tools are available:

### Context & Navigation
- `mcp__asdlc__get_context()` - Get current project summary
- `mcp__asdlc__list_projects()` - List all known projects
- `mcp__asdlc__switch_project(project_id)` - Change active project

### PRD Management
- `mcp__asdlc__list_prds()` - List PRDs
- `mcp__asdlc__get_prd(prd_id)` - Get full PRD with file_path
- `mcp__asdlc__create_prd(title)` - Create PRD (returns file_path → Write content)
- `mcp__asdlc__update_prd(prd_id, status?, version?)` - Update PRD metadata
- `mcp__asdlc__delete_prd(prd_id)` - Delete PRD

### Task Management
- `mcp__asdlc__list_tasks()` - List tasks (filterable)
- `mcp__asdlc__get_task(task_id)` - Get task details with file_path
- `mcp__asdlc__create_task(title, prd_id?, priority?)` - Create task (returns file_path → Write content)
- `mcp__asdlc__update_task(task_id, status?, priority?)` - Update task metadata
- `mcp__asdlc__start_task(task_id)` - Mark as in_progress
- `mcp__asdlc__complete_task(task_id)` - Mark as completed
- `mcp__asdlc__block_task(task_id)` - Mark as blocked
- `mcp__asdlc__delete_task(task_id)` - Delete task

### Sprint Management
- `mcp__asdlc__list_sprints()` - List sprints
- `mcp__asdlc__get_sprint(sprint_id)` - Get sprint with tasks
- `mcp__asdlc__create_sprint(title, goal)` - Create sprint
- `mcp__asdlc__start_sprint(sprint_id)` - Activate sprint
- `mcp__asdlc__complete_sprint(sprint_id)` - Complete sprint
- `mcp__asdlc__add_tasks_to_sprint(sprint_id, task_ids)` - Add tasks
- `mcp__asdlc__remove_tasks_from_sprint(sprint_id, task_ids)` - Remove tasks

## Output

After successful initialization, display:

```
✓ Project initialized: my-project

  Shortname: MYPR
  Project ID: my-project
  Path: /path/to/my-project

  ID Formats:
  - Tasks:   MYPR-T00001
  - Sprints: MYPR-S0001
  - PRDs:    MYPR-P0001

  Files generated:
  - CLAUDE.md (project rules + lesson-learn references)
  - .sdlc/config.yaml (testing and review configuration)
  - .sdlc/lesson-learn.md (project lessons)
  - ~/.a-sdlc/lesson-learn.md (global lessons)

  Folders created:
  - .sdlc/artifacts/
  - .sdlc/.cache/

  Git configuration:
  - .sdlc/.cache/ added to .gitignore
  - .sdlc/artifacts/ {tracked in git | added to .gitignore}

Next steps:
1. Scan codebase: /sdlc:scan (generates documentation artifacts)
2. Create a PRD: /sdlc:prd-generate "Feature description"
3. Create a sprint: /sdlc:sprint-create "Sprint 1"
4. View status: /sdlc:status
```

## Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `name` | Optional project name | Folder name |
| `shortname` | 4-letter uppercase project identifier (A-Z only) | Auto-generated from name |

## Examples

```
/sdlc:init                           # Interactive: suggests shortname, asks for confirmation
/sdlc:init "My App"                  # Interactive: uses "My App" as name, suggests shortname
/sdlc:init shortname=MYAP            # Uses specified shortname directly
/sdlc:init "My App" shortname=MYAP   # Uses both custom name and shortname
```

### Interactive Flow Example

```
User: /sdlc:init

Agent: Your project shortname will be **ASDL** (from "a-sdlc").
       This is used as a prefix for all entity IDs:
       - Tasks: ASDL-T00001
       - Sprints: ASDL-S0001
       - PRDs: ASDL-P0001

       Would you like to use this shortname or provide a custom one?

User: Use SDLC instead

Agent: ✓ Registered project with shortname SDLC

       Would you like to track `.sdlc/artifacts/` in version control?
       - Yes (recommended): Documentation artifacts are versioned with code
       - No: Artifacts are gitignored and regenerated as needed

User: Yes

Agent: ✓ Project initialized: a-sdlc

         Shortname: SDLC
         Project ID: a-sdlc
         Path: /path/to/a-sdlc

         ID Formats:
         - Tasks:   SDLC-T00001
         - Sprints: SDLC-S0001
         - PRDs:    SDLC-P0001

         Folders created:
         - .sdlc/artifacts/
         - .sdlc/.cache/

         Git configuration:
         - .sdlc/.cache/ added to .gitignore
         - .sdlc/artifacts/ tracked in git

       Next steps:
       1. Scan codebase: /sdlc:scan
       2. Create a PRD: /sdlc:prd-generate "Feature description"
```

## Notes

- All data is stored in user-level SQLite database (`~/.a-sdlc/data.db`)
- The `.sdlc/` directory is created in the repository for artifacts and cache
- `.sdlc/.cache/` is always gitignored (contains checksums and metadata)
- `.sdlc/artifacts/` can optionally be tracked in git (user's choice)
- Data persists across Claude Code sessions