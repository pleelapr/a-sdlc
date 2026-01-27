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
- `--sprint <sprint-id>` - Assign all tasks to sprint (e.g., SPRINT-001)
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

Assign all tasks to sprint (recommended for parallel execution):
```
/sdlc:prd-split "feature-auth" --sprint SPRINT-001
```

Create sprint and assign tasks in one workflow:
```
/sdlc:sprint-create "Auth Sprint" --goal "Complete OAuth flow"
/sdlc:prd-split "feature-auth" --sprint SPRINT-001
/sdlc:sprint-start SPRINT-001
/sdlc:sprint-run SPRINT-001
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

**Step 3: Sprint Assignment (if --sprint provided)**

If `--sprint` option is provided:
1. Validate sprint exists: Read `.sdlc/sprints/active/{sprint_id}.json`
2. Verify sprint is not COMPLETED
3. For each generated task:
   - Set `task.sprint_id = sprint_id`
   - Add task ID to `sprint.task_ids`
4. Update sprint JSON file with new task_ids list

```python
# Sprint integration logic
if sprint_id:
    sprint = load_sprint(sprint_id)
    if sprint.status == "completed":
        error("Cannot add tasks to completed sprint")

    for task in generated_tasks:
        task.sprint_id = sprint_id
        sprint.task_ids.append(task.id)

    save_sprint(sprint)
```

**Step 4: Update PRD Status to "split"**

After successfully creating tasks, update the PRD status:

```
mcp__asdlc__update_prd(prd_id="<prd_id>", status="split")
```

This marks the PRD as having been broken down into tasks.

**Step 5: Show summary to user**

Display a summary showing:
- Number of tasks created
- Task IDs (TASK-001, TASK-002, etc.)
- Requirements covered
- Components affected
- Sprint assignment (if `--sprint` was used)
- Location of generated files
- Sync status (if `--sync` was used)
- PRD status updated to "split"

**Step 6: STOP**

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

⚠️ **DUAL-FILE REQUIREMENT**: For EACH task, you MUST create TWO files:

1. **JSON file** (machine-readable, required for tooling):
   - Path: `.sdlc/tasks/active/TASK-XXX.json`
   - Contains all task data in structured JSON format
   - Used by `/sdlc:task-list`, `/sdlc:task-start`, sprint management

2. **Markdown file** (human-readable, required for developers):
   - Path: `.sdlc/tasks/active/TASK-XXX.md`
   - Contains full task documentation with all sections
   - Used for task review, implementation guidance

⛔ **BOTH files are required for each task. Do not create one without the other.**

### JSON Schema (Required)

Every task JSON file MUST include ALL these fields:

```json
{
  "id": "TASK-001",
  "title": "Set up OAuth Configuration",
  "description": "Configure OAuth 2.0 provider settings for third-party authentication",
  "status": "pending",
  "priority": "high",
  "requirement_id": "FR-001",
  "prd_ref": "feature-auth.md",
  "component": "auth-service",
  "dependencies": [],
  "sprint_id": null,
  "goal": "Configure OAuth 2.0 provider settings to enable third-party authentication",
  "files_to_modify": [
    "src/auth/config.py",
    "config/oauth.yaml"
  ],
  "key_requirements": [
    "Support Google and GitHub OAuth providers",
    "Store client secrets securely (environment variables)"
  ],
  "technical_notes": [
    "Use existing ConfigLoader pattern from src/config/",
    "OAuth callback URL format: /auth/callback/{provider}"
  ],
  "deliverables": [
    "OAuth configuration dataclass",
    "Provider-specific config loading",
    "Environment variable validation"
  ],
  "exclusions": [
    "OAuth flow implementation (separate task)",
    "UI changes (separate task)",
    "Token storage (separate task)"
  ],
  "implementation_steps": [
    {
      "title": "Create OAuth config dataclass",
      "description": "Define configuration structure for OAuth providers",
      "code_hint": "@dataclass\nclass OAuthConfig:\n    provider: str\n    client_id: str\n    client_secret: str\n    redirect_uri: str",
      "test_expectation": "Config loads without errors"
    },
    {
      "title": "Add provider configuration loading",
      "description": "Implement loading from oauth.yaml with env var substitution",
      "code_hint": null,
      "test_expectation": "Each provider config resolves correctly"
    },
    {
      "title": "Add configuration validation",
      "description": "Validate required fields are present and non-empty",
      "code_hint": null,
      "test_expectation": "Missing fields raise ConfigError"
    }
  ],
  "success_criteria": [
    "OAuth config loads for Google provider",
    "OAuth config loads for GitHub provider",
    "Missing client_secret raises clear error",
    "Config is accessible via dependency injection"
  ],
  "scope_constraint": "Implement only the changes described above. Do not modify unrelated components, add features not in requirements, or refactor existing code unless necessary.",
  "created_at": "2025-01-26T12:00:00",
  "updated_at": "2025-01-26T12:00:00",
  "completed_at": null,
  "external_id": null,
  "external_url": null
}
```

#### JSON Field Reference

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | ✅ | Unique task ID (TASK-XXX) |
| `title` | string | ✅ | Short descriptive title |
| `description` | string | ✅ | Brief task description |
| `status` | string | ✅ | pending, in_progress, blocked, completed |
| `priority` | string | ✅ | low, medium, high, critical |
| `requirement_id` | string | ✅ | Source requirement (FR-XXX, NFR-XXX) |
| `prd_ref` | string | ✅ | Source PRD filename |
| `component` | string | ✅ | Target component/module |
| `dependencies` | array | ✅ | Task IDs this depends on |
| `sprint_id` | string | ⬜ | Sprint assignment (if --sprint used) |
| `goal` | string | ✅ | Clear statement of task purpose |
| `files_to_modify` | array | ✅ | Files that will be changed |
| `key_requirements` | array | ✅ | Requirements from PRD |
| `technical_notes` | array | ✅ | Implementation hints |
| `deliverables` | array | ✅ | What will be produced |
| `exclusions` | array | ✅ | What is NOT in scope |
| `implementation_steps` | array | ✅ | Structured step objects (see below) |
| `success_criteria` | array | ✅ | Verification checkpoints |
| `scope_constraint` | string | ✅ | Reminder to stay focused |
| `created_at` | string | ✅ | ISO 8601 timestamp |
| `updated_at` | string | ✅ | ISO 8601 timestamp |
| `completed_at` | string | ⬜ | ISO 8601 timestamp (when done) |
| `external_id` | string | ⬜ | ID in Jira/Linear (if synced) |
| `external_url` | string | ⬜ | URL in Jira/Linear (if synced) |

#### Implementation Step Schema

Each step in `implementation_steps` array:

```json
{
  "title": "Step title (required)",
  "description": "Detailed description of what to do (required)",
  "code_hint": "Optional code snippet or example",
  "test_expectation": "Optional: what test should verify"
}
```

### Markdown Template Reference

Use the template at `src/a_sdlc/artifact_templates/task.template.md` for the full markdown structure.

Each generated task MUST include ALL sections:

1. **Header** - ID, Title, Status, Priority, Requirement, Component, Dependencies
2. **Goal** - Clear statement of what this task accomplishes
3. **Implementation Context**
   - Files to Modify (with paths)
   - Key Requirements (from PRD)
   - Technical Notes (implementation hints)
4. **Scope Definition**
   - Deliverables (what will be produced)
   - Exclusions (what is explicitly NOT in scope)
5. **Implementation Steps** - Numbered steps with:
   - Step title and description
   - Code hints where helpful
   - Test expectations for each step
6. **Success Criteria** - Checkboxes for verification
7. **Scope Constraint** - Standard reminder to stay focused
8. **Timestamps** - Created/Updated dates

### Example Task (Full Format)

```markdown
# TASK-001: Set up OAuth Configuration

**Status:** pending
**Priority:** high
**Requirement:** FR-001
**Component:** auth-service
**Dependencies:** None

## Goal

Configure OAuth 2.0 provider settings to enable third-party authentication.

## Implementation Context

### Files to Modify

- `src/auth/config.py`
- `config/oauth.yaml`

### Key Requirements

- Support Google and GitHub OAuth providers
- Store client secrets securely (environment variables)

### Technical Notes

- Use existing `ConfigLoader` pattern from `src/config/`
- OAuth callback URL format: `/auth/callback/{provider}`

## Scope Definition

### Deliverables

- OAuth configuration dataclass
- Provider-specific config loading
- Environment variable validation

### Exclusions

- OAuth flow implementation (separate task)
- UI changes (separate task)
- Token storage (separate task)

## Implementation Steps

1. **Create OAuth config dataclass**
   Define configuration structure for OAuth providers.
   ```python
   @dataclass
   class OAuthConfig:
       provider: str
       client_id: str
       client_secret: str
       redirect_uri: str
   ```
   - **Test:** Config loads without errors

2. **Add provider configuration loading**
   Implement loading from oauth.yaml with env var substitution.
   - **Test:** Each provider config resolves correctly

3. **Add configuration validation**
   Validate required fields are present and non-empty.
   - **Test:** Missing fields raise ConfigError

## Success Criteria

- [ ] OAuth config loads for Google provider
- [ ] OAuth config loads for GitHub provider
- [ ] Missing client_secret raises clear error
- [ ] Config is accessible via dependency injection

## Scope Constraint

Implement only the changes described above. Do not:
- Modify unrelated components
- Add features not in requirements
- Refactor existing code unless necessary

---

**Created:** 2025-01-26
**Updated:** 2025-01-26
```

## Sprint Integration

When `--sprint` is provided, this command:
1. Validates the sprint exists and is not completed
2. Sets `sprint_id` on all generated tasks
3. Adds all task IDs to the sprint's `task_ids` array
4. Updates both task JSON files and sprint JSON file

After splitting with `--sprint`:
```
/sdlc:prd-split "feature-auth" --sprint SPRINT-001

→ Created 5 tasks assigned to SPRINT-001
→ Next: /sdlc:sprint-start SPRINT-001
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
