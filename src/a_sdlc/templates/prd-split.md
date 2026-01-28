# /sdlc:prd-split

## Purpose

Break down a Product Requirements Document (PRD) into actionable development tasks using a **two-phase approach** that ensures reliable persistence. Tasks are generated following a flexible, user-configurable template that produces rich implementation guidance.

---

## ⚠️ CRITICAL: DOCUMENTATION ONLY

**This skill generates TASK DOCUMENTATION, not code.**

You MUST:
- ✅ Generate markdown task descriptions with implementation guidance
- ✅ Use ONLY `mcp__asdlc__split_prd()` to create task records
- ✅ Wait for user approval before calling any MCP tools

You MUST NOT:
- ❌ Use Edit, Write, MultiEdit tools
- ❌ Create or modify source code files
- ❌ Implement any features
- ❌ Run tests or builds

**All code snippets in this template are EXAMPLES for task documentation, not instructions to implement.**

---

## Usage

```
/sdlc:prd-split "<prd_id>" [options]
```

**Arguments:**
- `prd_id` - ID of PRD to split (e.g., "feature-auth")

**Options:**
- `--granularity <level>` - Task detail: coarse, medium, fine (default: medium)

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

---

## Context Gathering

Before generating tasks, gather project context to produce well-informed, implementable tasks.

### 1. Load Project Artifacts (if available)

Read from `.sdlc/artifacts/` to understand the codebase:

| Artifact | Use For |
|----------|---------|
| `architecture.md` | Component list for task assignment, existing patterns |
| `data-model.md` | Entity understanding, schema references |
| `key-workflows.md` | Dependency identification, integration points |
| `directory-structure.md` | Files to modify, module locations |
| `codebase-summary.md` | Tech stack, dependencies, conventions |

**Note:** If artifacts don't exist, run `/sdlc:scan` first or work with the PRD content alone.

### 2. Load Task Template

The task template defines the structure of generated task content:

- **Project-specific:** `.sdlc/templates/task.template.md` (if exists)
- **Default:** `src/a_sdlc/artifact_templates/task.template.md`

Users can customize the template to match their workflow. The agent generates content following whatever template is in use.

### 3. Parse PRD Content

Extract from the PRD:

| PRD Section | Maps To |
|-------------|---------|
| Functional Requirements (FR-XXX) | Primary tasks |
| Non-Functional Requirements (NFR-XXX) | Quality/cross-cutting tasks |
| Acceptance Criteria | Success criteria |
| Technical Considerations | Technical notes |
| Out of Scope | Task exclusions |

---

## Task Content Generation

Generate markdown content following the task template structure. The `description` field passed to `split_prd` contains the **full task markdown content**.

### Default Task Template Structure

The default template (`task.template.md`) provides this structure:

```markdown
# {{TASK_ID}}: {{TASK_TITLE}}

**Status:** {{STATUS}}
**Priority:** {{PRIORITY}}
**Component:** {{COMPONENT}}
**Dependencies:** {{DEPENDENCIES}}
**PRD Reference:** {{PRD_REF}}

## Goal

{{GOAL}}

## Implementation Context

### Files to Modify
{{#FILES_TO_MODIFY}}
- `{{PATH}}`
{{/FILES_TO_MODIFY}}

### Key Requirements
{{#KEY_REQUIREMENTS}}
- {{REQUIREMENT}}
{{/KEY_REQUIREMENTS}}

### Technical Notes
{{#TECHNICAL_NOTES}}
- {{NOTE}}
{{/TECHNICAL_NOTES}}

## Scope Definition

### Deliverables
{{#DELIVERABLES}}
- {{DELIVERABLE}}
{{/DELIVERABLES}}

### Exclusions
{{#EXCLUSIONS}}
- {{EXCLUSION}}
{{/EXCLUSIONS}}

## Implementation Guidance (Documentation Only)

> The following steps and code hints are for DOCUMENTATION.
> They describe what the developer should do when working on this task.

{{#IMPLEMENTATION_STEPS}}
{{NUMBER}}. **{{STEP_TITLE}}**
   {{DESCRIPTION}}
   ```{{LANGUAGE}}
   {{CODE}}
   ```
   - **Test:** {{TEST_DESCRIPTION}}
{{/IMPLEMENTATION_STEPS}}

## Success Criteria

{{#SUCCESS_CRITERIA}}
- [ ] {{CRITERION}}
{{/SUCCESS_CRITERIA}}

## Scope Constraint

{{SCOPE_CONSTRAINT}}
```

**Important:** Users can customize this template at `.sdlc/templates/task.template.md`. The agent should read and follow whatever template is in use.

### Content Generation Guidelines

For each task, the agent should:

1. **Write a clear Goal** - Single sentence describing what this task accomplishes
2. **Identify Files to Modify** - Use directory-structure.md or codebase knowledge
3. **Extract Key Requirements** - From PRD acceptance criteria
4. **Add Technical Notes** - Patterns from architecture.md, constraints
5. **Define Deliverables** - Concrete outputs (functions, files, endpoints)
6. **Define Exclusions** - What's explicitly NOT in scope
7. **Write Implementation Steps** - With code hints and test criteria
8. **Derive Success Criteria** - Checkboxes from acceptance criteria

---

## Dependency Analysis

### Common Dependency Patterns

| Pattern | Flow | When to Use |
|---------|------|-------------|
| Data First | Model → API → UI | Feature needs data persistence |
| Config First | Config → Feature | Feature needs configuration |
| Auth First | Auth → Protected | Feature needs authentication |
| Schema First | Migration → ORM → API | Feature changes database |
| Infrastructure First | Setup → Implementation | Feature needs new infrastructure |

### Identifying Dependencies

For each task, ask:

1. Does this need data/models from another task?
2. Does this call functions created in another task?
3. Does this require configuration from another task?
4. Is this a test for another task's implementation?
5. Does this need infrastructure set up by another task?

If YES to any → add as dependency

### Expressing Dependencies in Task Breakdown

Show dependencies clearly when presenting the task breakdown:

```
Based on get_context(): shortname="CWAI", total_tasks=0

CWAI-T00001: Set up OAuth config (no dependencies)
    ↓
CWAI-T00002: Implement OAuth flow (depends on: CWAI-T00001)
    ↓
CWAI-T00003: Handle callback (depends on: CWAI-T00002)
    ↓
CWAI-T00004: Create user on login (depends on: CWAI-T00003)
```

### Dependency Rules

1. **No circular dependencies** - Tasks cannot depend on each other
2. **Minimize chains** - Prefer parallel tasks over long sequential chains
3. **Use full task IDs** - Reference by calculated ID (e.g., "CWAI-T00001" based on context)

---

## Two-Phase Execution

**Allowed Tools for This Skill:**
- `mcp__asdlc__get_context()` - Get project info
- `mcp__asdlc__get_prd()` - Read PRD content
- `mcp__asdlc__split_prd()` - Create task records
- `Read` - Read artifacts and templates

**Forbidden Tools:**
- `Edit`, `Write`, `MultiEdit` - No code changes
- `Bash` - No command execution (except read-only)
- Any tool that modifies the codebase

This skill uses a two-phase approach to ensure tasks are always persisted, even if the session is interrupted.

### Phase 1: Draft & Refine (Interactive)

1. **Get project context to calculate task IDs:**
   ```
   mcp__asdlc__get_context()
   ```

   This returns:
   - `project.shortname` - e.g., "CWAI"
   - `statistics.total_tasks` - current task count

   Calculate expected task IDs for this split:
   - If shortname = "CWAI" and total_tasks = 5
   - First new task: CWAI-T00006
   - Second new task: CWAI-T00007
   - And so on...

   Use these calculated IDs when:
   - Displaying the task breakdown
   - Specifying dependencies between tasks
   - Showing the dependency graph

2. **Get PRD content:**
   ```
   mcp__asdlc__get_prd(prd_id="<prd_id>")
   ```

3. **Gather context:**
   - Read `.sdlc/artifacts/` for component/entity info (if available)
   - Check for custom task template at `.sdlc/templates/task.template.md`
   - Note the granularity level requested

4. **For each requirement, generate task content:**

   a. **Identify affected component(s)** from architecture
   b. **Determine files to modify** from directory structure
   c. **Write Goal** from requirement description
   d. **Extract Key Requirements** from acceptance criteria
   e. **Add Technical Notes** from architecture patterns
   f. **Define Deliverables** (concrete outputs)
   g. **Define Exclusions** (what's NOT in scope)
   h. **Write Implementation Steps** with code hints
   i. **Derive Success Criteria** from acceptance criteria
   j. **Identify dependencies** on other tasks

5. **Present full task breakdown:**

   Display the proposed tasks with enough detail for meaningful review:

   ```
   ## Proposed Tasks for PRD: <prd_id>

   ### TASK 1: Set up OAuth configuration
   **Priority:** high | **Component:** auth-service | **Dependencies:** None

   **Goal:** Configure OAuth 2.0 provider settings to enable Google authentication.

   **Files to Modify:**
   - `src/auth/oauth_config.py` - New file for OAuth configuration
   - `config/settings.py` - Add OAuth environment variables

   **Implementation Steps:**
   1. Create OAuth config dataclass
   2. Add environment variable loading
   3. Add configuration validation

   **Success Criteria:**
   - [ ] OAuth config loads for Google provider
   - [ ] Missing credentials raise clear error

   ---

   ### TASK 2: Implement OAuth flow
   **Priority:** high | **Component:** auth-service | **Dependencies:** {shortname}-T00001

   **Goal:** Implement OAuth 2.0 authorization flow with Google.
   ...

   ---

   **Total: X tasks**
   **Dependency Graph:**
   {shortname}-T00001 → {shortname}-T00002 → {shortname}-T00003 → {shortname}-T00004

   Would you like to:
   - Approve and create these tasks
   - Modify the breakdown (add/remove/change tasks)
   - See full content for a specific task
   - Cancel
   ```

6. **Allow refinement:**
   - User can discuss and refine task details
   - Adjust priorities, components, or descriptions
   - Add or remove tasks as needed
   - Request more/less detail in implementation steps
   - Iterate until user is satisfied

### Phase 2: Commit (Atomic)

7. **Once user approves, create all tasks atomically:**

   ```
   mcp__asdlc__split_prd(
       prd_id="<prd_id>",
       task_specs=[
           {
               "title": "Set up OAuth configuration",
               "description": "<full markdown content following template>",
               "priority": "high",
               "component": "auth-service",
               "dependencies": []
           },
           {
               "title": "Implement OAuth flow",
               "description": "<full markdown content following template>",
               "priority": "high",
               "component": "auth-service",
               "dependencies": ["{shortname}-T00001"]  # Use calculated full IDs
           },
           ...
       ]
   )
   ```

   **Important:** The `description` field contains the **full task markdown content** generated following the template, not just a brief description.

   This single MCP call:
   - Creates all tasks in the database with content in `~/.a-sdlc/content/tasks/`
   - Links them to the PRD
   - Updates PRD status to "split"
   - Ensures atomic persistence (all or nothing)

8. **Display created tasks summary:**

   ```
   ## Tasks Created

   PRD '<prd_id>' has been split into X tasks:

   | ID | Title | Priority | Component | Dependencies |
   |----|-------|----------|-----------|--------------|
   | {shortname}-T00001 | Set up OAuth configuration | high | auth-service | - |
   | {shortname}-T00002 | Implement OAuth flow | high | auth-service | {shortname}-T00001 |
   | {shortname}-T00003 | Handle OAuth callback | high | auth-service | {shortname}-T00002 |
   | {shortname}-T00004 | Create user on first login | medium | user-service | {shortname}-T00003 |

   PRD status updated to: split

   **Dependency Graph:**
   {shortname}-T00001 → {shortname}-T00002 → {shortname}-T00003 → {shortname}-T00004

   **Next steps:**
   - View tasks: /sdlc:task-list
   - See task details: /sdlc:task-show {shortname}-T00001
   - Start working: /sdlc:task-start TASK-001
   ```

---

## Task Specification Format

Each task in `task_specs` should include:

| Field | Required | Description |
|-------|----------|-------------|
| `title` | Yes | Short descriptive title |
| `description` | Yes | **Full task markdown content** following template |
| `priority` | No | low, medium, high, critical (default: medium) |
| `component` | No | Target component/module |
| `dependencies` | No | List of full task IDs (e.g., ["CWAI-T00001", "CWAI-T00002"]) this task depends on |

**Important - Task ID Format:**

Before generating tasks, call `mcp__asdlc__get_context()` to get:
- `project.shortname` (e.g., "CWAI")
- `statistics.total_tasks` (e.g., 5)

Calculate task IDs as: `{shortname}-T{(total_tasks + position):05d}`
- Example: CWAI with 5 existing tasks, creating 3 new tasks
- Task 1: CWAI-T00006
- Task 2: CWAI-T00007
- Task 3: CWAI-T00008

Use these full IDs in:
- The task breakdown display
- The `dependencies` array in task_specs
- The dependency graph visualization

---

## Granularity Levels

**Coarse (3-5 tasks):**
- High-level feature chunks
- Good for initial planning or simple features
- Implementation steps are broader

**Medium (5-10 tasks):**
- Balanced breakdown
- Default and recommended for most PRDs
- Each task is 1-4 hours of work

**Fine (10-20 tasks):**
- Detailed implementation steps
- Good for complex features or junior developers
- Each task is a single focused change

---

## Complete Example

> **⚠️ IMPORTANT:** The code snippets below show what task DOCUMENTATION should contain.
> These are implementation hints to include in the task markdown files.
> DO NOT write this code to the codebase - only include it in the task description field.

### Input: PRD "feature-oauth"

```markdown
# OAuth Authentication

## Overview
Add Google OAuth authentication to allow users to sign in with their Google accounts.

## Requirements

### Functional Requirements
- FR-001: Users can authenticate via Google OAuth
- FR-002: System creates user record on first OAuth login
- FR-003: Returning users are recognized and logged in

### Non-Functional Requirements
- NFR-001: OAuth flow completes in under 3 seconds
- NFR-002: Failed OAuth attempts are logged for security

### Acceptance Criteria
- User clicks "Login with Google" → redirected to Google
- After auth, user is logged in with profile showing Google email
- New users have account created automatically
- Returning users see their existing profile

### Technical Considerations
- Use existing ConfigLoader pattern
- OAuth callback URL: /auth/callback/google
- Store refresh tokens securely

### Out of Scope
- Other OAuth providers (GitHub, Facebook)
- Custom OAuth server implementation
```

### Output: Generated Tasks (Medium Granularity)

Based on `get_context()`: shortname="OAUT", total_tasks=0

**OAUT-T00001: Set up OAuth configuration**

```markdown
# OAUT-T00001: Set up OAuth configuration

**Status:** pending
**Priority:** high
**Component:** auth-service
**Dependencies:** None
**PRD Reference:** feature-oauth

## Goal

Configure OAuth 2.0 provider settings to enable Google authentication.

## Implementation Context

### Files to Modify
- `src/auth/oauth_config.py` - New file for OAuth configuration
- `config/settings.py` - Add OAuth environment variables

### Key Requirements
- Support Google OAuth provider
- Store client secrets securely using environment variables
- Validate configuration on startup

### Technical Notes
- Use existing ConfigLoader pattern from src/config/base.py
- OAuth callback URL: /auth/callback/google
- Follow existing config dataclass patterns

## Scope Definition

### Deliverables
- OAuth configuration dataclass
- Environment variable loading function
- Configuration validation

### Exclusions
- OAuth flow implementation (OAUT-T00002)
- User creation logic (OAUT-T00003)
- UI changes
- Other OAuth providers

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
       scopes: list[str]
   ```
   - **Test:** Config instantiates with valid inputs

2. **Add environment variable loading**
   Load OAuth credentials from environment.
   ```python
   def load_google_oauth() -> OAuthConfig:
       return OAuthConfig(
           provider="google",
           client_id=os.environ["GOOGLE_CLIENT_ID"],
           client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
           redirect_uri=os.environ.get("GOOGLE_REDIRECT_URI", "/auth/callback/google"),
           scopes=["openid", "email", "profile"]
       )
   ```
   - **Test:** Missing env var raises ConfigurationError

3. **Add configuration validation**
   Validate OAuth config on load.
   ```python
   def validate_oauth_config(config: OAuthConfig) -> None:
       if not config.client_id:
           raise ConfigurationError("OAuth client_id is required")
       if not config.redirect_uri.startswith("/"):
           raise ConfigurationError("redirect_uri must be a path")
   ```
   - **Test:** Invalid config raises appropriate error

## Success Criteria

- [ ] OAuth config loads for Google provider
- [ ] Missing credentials raise clear ConfigurationError
- [ ] Config validates redirect URI format
- [ ] Environment variables documented in README

## Scope Constraint

Implement only OAuth configuration loading. Do not implement OAuth flows, token handling, or UI changes.
```

---

**OAUT-T00002: Implement OAuth flow** (depends on OAUT-T00001)

```markdown
# OAUT-T00002: Implement OAuth flow

**Status:** pending
**Priority:** high
**Component:** auth-service
**Dependencies:** OAUT-T00001
**PRD Reference:** feature-oauth

## Goal

Implement OAuth 2.0 authorization flow with Google for user authentication.

## Implementation Context

### Files to Modify
- `src/auth/oauth.py` - New file for OAuth flow logic
- `src/routes/auth.py` - Add OAuth endpoints

### Key Requirements
- Redirect users to Google for authentication
- Handle OAuth callback with authorization code
- Exchange code for access token
- Retrieve user profile from Google

### Technical Notes
- Use requests library for HTTP calls
- Follow OAuth 2.0 authorization code flow
- Handle state parameter for CSRF protection

## Scope Definition

### Deliverables
- OAuth authorization URL generator
- Callback handler with code exchange
- Google profile retrieval function
- /auth/google and /auth/callback/google endpoints

### Exclusions
- User creation (OAUT-T00003)
- Session management (OAUT-T00004)
- Token refresh logic
- Error UI

## Implementation Steps

1. **Create authorization URL generator**
   Generate Google OAuth authorization URL with state.
   ```python
   def get_authorization_url(config: OAuthConfig, state: str) -> str:
       params = {
           "client_id": config.client_id,
           "redirect_uri": config.redirect_uri,
           "scope": " ".join(config.scopes),
           "response_type": "code",
           "state": state
       }
       return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"
   ```
   - **Test:** URL contains all required parameters

2. **Implement code exchange**
   Exchange authorization code for tokens.
   ```python
   def exchange_code(config: OAuthConfig, code: str) -> dict:
       response = requests.post(
           "https://oauth2.googleapis.com/token",
           data={
               "client_id": config.client_id,
               "client_secret": config.client_secret,
               "code": code,
               "grant_type": "authorization_code",
               "redirect_uri": config.redirect_uri
           }
       )
       return response.json()
   ```
   - **Test:** Valid code returns access_token

3. **Add profile retrieval**
   Get user profile from Google API.
   ```python
   def get_google_profile(access_token: str) -> dict:
       response = requests.get(
           "https://www.googleapis.com/oauth2/v2/userinfo",
           headers={"Authorization": f"Bearer {access_token}"}
       )
       return response.json()
   ```
   - **Test:** Valid token returns email and name

4. **Create OAuth endpoints**
   Add routes for OAuth flow.
   - **Test:** /auth/google redirects to Google
   - **Test:** /auth/callback/google handles code

## Success Criteria

- [ ] /auth/google redirects to Google with correct parameters
- [ ] Callback exchanges code for access token
- [ ] User profile retrieved from Google
- [ ] State parameter validates CSRF protection
- [ ] OAuth flow completes in under 3 seconds (NFR-001)

## Scope Constraint

Implement only the OAuth flow mechanics. Do not create users, manage sessions, or build UI.
```

---

**OAUT-T00003: Create user on first OAuth login** (depends on OAUT-T00002)

```markdown
# OAUT-T00003: Create user on first OAuth login

**Status:** pending
**Priority:** medium
**Component:** user-service
**Dependencies:** OAUT-T00002
**PRD Reference:** feature-oauth

## Goal

Create user records automatically when users authenticate via OAuth for the first time.

## Implementation Context

### Files to Modify
- `src/auth/oauth.py` - Add user creation logic
- `src/models/user.py` - May need OAuth fields

### Key Requirements
- Check if user exists by Google ID or email
- Create new user if not found
- Return existing user if found
- Store Google ID for future lookups

### Technical Notes
- Use existing User model patterns
- Google ID is the primary identifier
- Email may change, Google ID is stable

## Scope Definition

### Deliverables
- find_or_create_oauth_user function
- Google ID field on User model (if needed)

### Exclusions
- Session creation (OAUT-T00004)
- Profile editing
- Account linking

## Implementation Steps

1. **Add Google ID to User model** (if not present)
   ```python
   class User:
       google_id: str | None = None
   ```
   - **Test:** User can be created with google_id

2. **Implement find_or_create_oauth_user**
   ```python
   def find_or_create_oauth_user(profile: dict) -> User:
       # Try to find by Google ID first
       user = User.find_by_google_id(profile["id"])
       if user:
           return user

       # Try by email as fallback
       user = User.find_by_email(profile["email"])
       if user:
           user.google_id = profile["id"]
           user.save()
           return user

       # Create new user
       return User.create(
           email=profile["email"],
           name=profile["name"],
           google_id=profile["id"]
       )
   ```
   - **Test:** New user created on first login
   - **Test:** Existing user returned on subsequent login

## Success Criteria

- [ ] New users created with Google profile data
- [ ] Returning users recognized by Google ID
- [ ] Users recognized by email get Google ID linked
- [ ] User record includes name from Google profile

## Scope Constraint

Implement only user find/create logic. Do not handle sessions, authentication state, or profile updates.
```

---

**OAUT-T00004: Integrate OAuth with session management** (depends on OAUT-T00003)

```markdown
# OAUT-T00004: Integrate OAuth with session management

**Status:** pending
**Priority:** medium
**Component:** auth-service
**Dependencies:** OAUT-T00003
**PRD Reference:** feature-oauth

## Goal

Complete the OAuth flow by creating user sessions after successful authentication.

## Implementation Context

### Files to Modify
- `src/routes/auth.py` - Complete callback handler
- `src/auth/session.py` - May need integration

### Key Requirements
- Create session after OAuth success
- Redirect to appropriate page
- Handle OAuth failures gracefully
- Log failed attempts (NFR-002)

## Scope Definition

### Deliverables
- Complete callback handler with session creation
- Error handling for OAuth failures
- Security logging for failures

### Exclusions
- Login UI
- Logout functionality
- Session refresh

## Implementation Steps

1. **Complete callback handler**
   ```python
   @app.route("/auth/callback/google")
   def oauth_callback():
       code = request.args.get("code")
       state = request.args.get("state")

       if not validate_state(state):
           log_security_event("invalid_oauth_state")
           return redirect("/login?error=invalid_state")

       try:
           tokens = exchange_code(oauth_config, code)
           profile = get_google_profile(tokens["access_token"])
           user = find_or_create_oauth_user(profile)
           create_session(user)
           return redirect("/dashboard")
       except OAuthError as e:
           log_security_event("oauth_failure", error=str(e))
           return redirect("/login?error=oauth_failed")
   ```
   - **Test:** Successful OAuth creates session and redirects
   - **Test:** Failed OAuth logs and redirects with error

2. **Add security logging**
   ```python
   def log_security_event(event_type: str, **details):
       logger.warning(f"Security event: {event_type}", extra=details)
   ```
   - **Test:** Failed attempts are logged with details

## Success Criteria

- [ ] Successful OAuth creates user session
- [ ] User redirected to dashboard after login
- [ ] Failed OAuth attempts logged (NFR-002)
- [ ] Invalid state parameter handled securely
- [ ] Error messages don't leak sensitive info

## Scope Constraint

Implement only session creation and error handling. Do not build login UI or logout functionality.
```

---

## Important Notes

1. **Atomic Persistence:** The `split_prd` MCP call creates all tasks in the database (`~/.a-sdlc/data.db`) with content files. Even if the session is interrupted after this call, the tasks are safely persisted.

2. **User Approval Required:** Always wait for explicit user approval before calling `split_prd`. This allows refinement and prevents accidental task creation.

3. **Full Content in Description:** The `description` field must contain the complete task markdown content following the template structure, not just a brief summary.

4. **PRD Status:** After successful split, the PRD status is automatically updated to "split".

5. **Template Flexibility:** Users can customize the task template at `.sdlc/templates/task.template.md`. The agent should follow whatever template is in use.

6. **No Implementation:** This skill only creates task records. It does NOT:
   - Implement any code
   - Create source files
   - Modify the codebase
   - Install dependencies

---

## Common Issues

**PRD not found:**
```
Error: PRD not found: feature-auth
```
Solution: Run `/sdlc:prd-list` to see available PRDs, or create one with `/sdlc:prd-generate`.

**No project context:**
```
Error: No project context. Run /sdlc:init first.
```
Solution: Initialize the project with `/sdlc:init`.

**Empty task specs:**
```
Error: No task specifications provided
```
Solution: Generate at least one task from the PRD analysis.

**Artifacts not found:**
```
Warning: .sdlc/artifacts/ not found
```
Solution: Run `/sdlc:scan` to generate codebase artifacts, or proceed without them.
