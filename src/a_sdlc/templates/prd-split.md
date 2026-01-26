# /sdlc:prd-split

⚠️ **CRITICAL INSTRUCTION**: This skill creates task description files ONLY.
- DO NOT implement code
- DO NOT create files mentioned in tasks
- DO NOT modify the codebase
- Tasks are planning documents for FUTURE work

## Purpose

Break down a Product Requirements Document (PRD) into actionable development tasks.
Generates task files in `.sdlc/tasks/active/` for later implementation.

## Usage

```
/sdlc:prd-split "<prd_id>" [options]
```

**Arguments:**
- `prd_id` - ID of PRD to split (e.g., "feature-auth")

**Options:**
- `--granularity <level>` - Task detail: coarse, medium, fine (default: medium)
- `--sync` - Auto-sync to Jira/Linear after generation
- `--format <fmt>` - Output: interactive, json, markdown (default: interactive)

## Examples

List available PRDs first:

```
/sdlc:prd-list
```

Split PRD with default options:
```
/sdlc:prd-split "feature-auth"
```

Fine-grained tasks:
```
/sdlc:prd-split "feature-auth" --granularity fine
```

Auto-sync to Jira:
```
/sdlc:prd-split "feature-auth" --sync
```

## Execution Instructions

**Step 1: Check if PRD exists**

List available PRDs first:
```
/sdlc:prd-list
```

If PRD not found, tell user to create it first with `/sdlc:prd-generate`.

**Step 2: This skill is self-contained**

When invoked, this skill automatically:
- Parses the specified PRD from `.sdlc/prds/`
- Analyzes requirements and breaks them into tasks
- Generates task files in `.sdlc/tasks/active/`
- Creates both markdown and JSON formats
- Displays a summary of created tasks

**Step 3: Show summary to user**

Display a summary showing:
- Number of tasks created
- Task IDs (TASK-001, TASK-002, etc.)
- Requirements covered
- Components affected
- Location of generated files
- Sync status (if `--sync` was used)

**Step 4: STOP**

⛔ **DO NOT PROCEED TO IMPLEMENTATION**

Do NOT:
- ❌ Read task files and start implementing them
- ❌ Create source code files mentioned in tasks
- ❌ Modify the codebase
- ❌ Install dependencies
- ❌ Run tests

The tasks are now saved and ready for developers to work on later.

## What Happens Next

Users can now:
- View tasks: `/sdlc:task-list`
- See task details: `/sdlc:task-show TASK-001`
- Start working: `/sdlc:task-start TASK-001`

## Task File Format

Generated tasks are saved as:
- **Markdown**: `.sdlc/tasks/active/TASK-001.md` (human-readable)
- **JSON**: `.sdlc/tasks/active/TASK-001.json` (machine-readable)

Example task structure:
```
TASK-001: Set up OAuth configuration
- Requirement: FR-001
- Component: auth-service
- Dependencies: None
- Files to modify: src/auth/config.py, config/oauth.yaml
- Implementation steps: 3-5 concrete steps
- Success criteria: Testable acceptance criteria
```

## Common Issues

**PRD not found:**
```
Error: PRD not found: feature-auth
Available PRDs: auth-system, payment-v2
```
Solution: Use one of the available PRD IDs or create the PRD first.

**No requirements in PRD:**
```
Warning: No requirements found in PRD
PRD must include "Functional Requirements" or "Non-Functional Requirements" section
```
Solution: Edit the PRD to add requirement sections.

**Artifacts missing:**
```
⚠ architecture not found (run /sdlc:scan)
⚠ data-model not found (run /sdlc:scan)
```
This is a warning, not an error. The command will continue with limited context.
For better task generation, run `/sdlc:scan` first.
