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
3. Return the project context with ID format examples

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

## MCP Tools Available

After initialization, the following MCP tools are available:

### Context & Navigation
- `mcp__asdlc__get_context()` - Get current project summary
- `mcp__asdlc__list_projects()` - List all known projects
- `mcp__asdlc__switch_project(project_id)` - Change active project

### PRD Management
- `mcp__asdlc__list_prds()` - List PRDs
- `mcp__asdlc__get_prd(prd_id)` - Get full PRD content
- `mcp__asdlc__create_prd(title, content)` - Create new PRD
- `mcp__asdlc__update_prd(prd_id, ...)` - Update PRD
- `mcp__asdlc__delete_prd(prd_id)` - Delete PRD

### Task Management
- `mcp__asdlc__list_tasks()` - List tasks (filterable)
- `mcp__asdlc__get_task(task_id)` - Get task details
- `mcp__asdlc__create_task(title, description, ...)` - Create task
- `mcp__asdlc__update_task(task_id, ...)` - Update task
- `mcp__asdlc__start_task(task_id)` - Mark as in_progress
- `mcp__asdlc__complete_task(task_id)` - Mark as completed
- `mcp__asdlc__block_task(task_id, reason)` - Mark as blocked
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