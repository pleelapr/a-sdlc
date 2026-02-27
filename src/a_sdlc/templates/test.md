# /sdlc:test

## Purpose

Execute runtime tests against a running application using browser automation (Playwright MCP) and API endpoint validation (Bash/curl). Tests are auto-generated from PRD acceptance criteria or provided as developer-defined scenarios in task content.

---

## Syntax

```
/sdlc:test <flags>
```

## Flags

| Flag | Description |
|------|-------------|
| `--task <id>` | Test changes for a specific task |
| `--prd <id>` | Test all acceptance criteria for a PRD |
| `--full` | Full regression test across all PRDs |
| `--api-only` | API tests only (skip browser tests) |
| `--browser-only` | Browser tests only (skip API tests) |

---

## Execution Steps

### Step 1: Parse Arguments

Parse the command argument to extract the scope flag and target ID. Determine the test scope and mode filter.

```
Parse the user's input after "/sdlc:test":

If argument contains "--task <id>":
  scope = "task"
  target_id = <id>

If argument contains "--prd <id>":
  scope = "prd"
  target_id = <id>

If argument contains "--full":
  scope = "full"
  target_id = null

If argument contains "--api-only":
  mode_filter = "api-only"

If argument contains "--browser-only":
  mode_filter = "browser-only"

If no flags provided:
  AskUserQuestion({
    questions: [{
      question: "What would you like to test?",
      header: "Test Scope",
      options: [
        { label: "Task", description: "Test changes for a specific task (provide task ID)" },
        { label: "PRD", description: "Test all acceptance criteria for a PRD (provide PRD ID)" },
        { label: "Full regression", description: "Run full regression across all PRDs" }
      ],
      multiSelect: false
    }]
  })

  If "Task" selected: ask for task ID, set scope = "task"
  If "PRD" selected: ask for PRD ID, set scope = "prd"
  If "Full regression" selected: set scope = "full"
```

Default `mode_filter` is `"both"` (run both browser and API tests) unless overridden by `--api-only` or `--browser-only`.

---

### Step 2: Load Configuration

Read `.sdlc/config.yaml` and extract the `testing.runtime` section.

```
Read(".sdlc/config.yaml")
```

Extract the `testing.runtime` block. Expected schema:

```yaml
testing:
  runtime:
    app_url: "http://localhost:3000"        # Base URL of the running application
    start_command: "npm run dev"            # Command to start the app (optional)
    health_check: "http://localhost:3000/health"  # Health endpoint (optional)
    mode: "both"                            # Default mode: both | api-only | browser-only
    api:
      base_url: "http://localhost:3000/api" # API base URL (defaults to {app_url}/api)
      schema: ""                            # Path to OpenAPI/JSON schema file (optional)
    browser:
      viewport_width: 1280                  # Browser viewport width (default: 1280)
      viewport_height: 720                  # Browser viewport height (default: 720)
```

**If `testing.runtime` is NOT present or empty:**

Display a warning:

```
Runtime testing configuration not found in .sdlc/config.yaml.

To configure, add the following section to .sdlc/config.yaml:

  testing:
    runtime:
      app_url: "http://localhost:3000"
      start_command: "npm run dev"
      health_check: "http://localhost:3000/health"

Alternatively, provide the application URL now.
```

Then ask the user for the minimum configuration:

```
AskUserQuestion({
  questions: [{
    question: "What is the application URL to test against?",
    header: "App URL Required",
    options: [
      { label: "http://localhost:3000", description: "Common default for Node.js apps" },
      { label: "http://localhost:8080", description: "Common default for Java/Go apps" },
      { label: "http://localhost:5173", description: "Common default for Vite dev server" },
      { label: "http://localhost:4200", description: "Common default for Angular apps" },
      { label: "Custom", description: "I will provide a custom URL" }
    ],
    multiSelect: false
  }]
})
```

If "Custom" is selected, ask for the URL as a follow-up question.

Set `app_url` from the user's response. Use defaults for all other settings:
- `api_base` = `{app_url}/api`
- `mode` = `"both"`
- `start_command` = null
- `health_check` = null

---

### Step 3: Check App Readiness

Verify the application is running and reachable using a fallback discovery chain.

#### 3a. Determine App URL

Use the following priority order:

1. **Config value**: Use `testing.runtime.app_url` from `.sdlc/config.yaml` if present
2. **Auto-detect**: If no config, attempt to discover the app:
   ```
   # Check package.json for dev/start scripts and infer port
   Read("package.json")
   # Look for "dev", "start", or "serve" scripts
   # Common patterns: "next dev" → port 3000, "vite" → port 5173, "ng serve" → port 4200

   # Check for docker-compose.yml
   Read("docker-compose.yml")
   # Look for exposed ports in service definitions

   # Probe common ports
   Bash("curl -s -o /dev/null -w '%{http_code}' http://localhost:3000 2>/dev/null || echo 000")
   Bash("curl -s -o /dev/null -w '%{http_code}' http://localhost:8080 2>/dev/null || echo 000")
   Bash("curl -s -o /dev/null -w '%{http_code}' http://localhost:5173 2>/dev/null || echo 000")
   Bash("curl -s -o /dev/null -w '%{http_code}' http://localhost:4200 2>/dev/null || echo 000")
   ```
3. **Ask user**: If nothing found, use `AskUserQuestion` to request the app URL (same prompt as Step 2 fallback)

#### 3b. Verify App Reachability

Once the `app_url` is determined, verify the app is reachable:

```
Bash("curl -s -o /dev/null -w '%{http_code}' {app_url}")
```

- If the response is `200`, `301`, `302`, or `304`: app is reachable, proceed to Step 4
- If the response is `000` or any error: app is not reachable

#### 3c. Attempt to Start App (if not reachable)

If the app is not reachable and `start_command` is configured:

```
AskUserQuestion({
  questions: [{
    question: "App at {app_url} is not reachable. Start it with: {start_command}?",
    header: "Start Application",
    options: [
      { label: "Start", description: "Run the start command and wait for the app to be ready" },
      { label: "Skip", description: "I will start the app manually — wait for me" },
      { label: "Abort", description: "Cancel testing" }
    ],
    multiSelect: false
  }]
})
```

If "Start" is selected:

```
Bash("{start_command}", run_in_background=true)
```

Then poll for readiness using the health check URL (or `app_url` if no health check configured):

```
health_url = health_check or app_url
max_wait = 30  # seconds
interval = 2   # seconds
elapsed = 0

while elapsed < max_wait:
  Bash("sleep 2")
  result = Bash("curl -s -o /dev/null -w '%{http_code}' {health_url}")
  if result in ("200", "301", "302", "304"):
    # App is ready
    break
  elapsed += interval

if elapsed >= max_wait:
  Report error: "App failed to start within 30 seconds. Check the start command and try again."
  STOP
```

If "Skip" is selected, wait for the user to confirm the app is running, then re-check.

If "Abort" is selected, stop execution entirely.

#### 3d. Final Reachability Check

If the app is still not reachable after all attempts:

```
App at {app_url} is not reachable.

Attempted:
  - Config URL: {app_url}
  - Start command: {start_command or "not configured"}
  - Health check: {health_check or "not configured"}

Please start the application manually and re-run /sdlc:test.
```

STOP execution.

---

### Step 4: Check Playwright Availability

Determine whether Playwright MCP tools are available for browser testing.

```
If mode_filter == "api-only":
  # Skip Playwright check entirely — not needed for API-only mode
  playwright_available = false
  Proceed to Step 5

# Attempt to verify Playwright MCP is available by checking tool availability
# Try a lightweight Playwright operation:
Try:
  mcp__playwright__browser_navigate(url="{app_url}")
  mcp__playwright__browser_snapshot()
  playwright_available = true
  # Close the browser to start fresh for actual tests
  mcp__playwright__browser_close()
Catch:
  playwright_available = false
```

**Handle unavailability:**

```
If playwright_available == false AND mode_filter == "browser-only":
  # Browser-only mode was requested but Playwright is not available
  Report error:
    "Playwright MCP is required for browser-only testing but is not available.

    To install Playwright MCP:
      a-sdlc install --with-playwright

    Or run with --api-only to skip browser tests."
  STOP

If playwright_available == false AND mode_filter == "both":
  # Playwright not available, but not explicitly required
  Report warning:
    "Playwright MCP not available. Falling back to API-only testing.

    To enable browser testing, install Playwright MCP:
      a-sdlc install --with-playwright"
  mode_filter = "api-only"
```

---

### Step 5: Load Context & Generate Test Scenarios

Based on the scope determined in Step 1, load the relevant a-sdlc context and generate test scenarios from acceptance criteria or developer-defined test definitions.

#### 5a. Load Context

**For `scope == "task"`:**

1. Fetch the task and its parent PRD:
   ```
   task = mcp__asdlc__get_task(task_id="{target_id}")
   task_content = task["content"]
   prd_id = task["prd_id"]

   If prd_id:
     prd = mcp__asdlc__get_prd(prd_id="{prd_id}")
     prd_content = prd["content"]
   ```

2. Check the task content for a `## Test Scenarios` section with Given/When/Then format:
   ```
   Search task_content for "## Test Scenarios" heading.

   If found, parse each scenario block:
     Scenario: {name}
       Given {precondition}
       When {action}
       Then {expected outcome}

   These are developer-defined scenarios — use them directly.
   Mark: source = "developer-defined"
   ```

3. If no developer-defined scenarios exist, parse acceptance criteria from the PRD content:
   ```
   Search prd_content for "## Acceptance Criteria" heading.
   Extract all lines matching patterns:
     - AC-NNN: {description}
     - [ ] {description}

   Filter to ACs that relate to this task's component/scope:
     - Match on task["component"] keywords
     - Match on task title keywords
     - Match on requirement IDs in the task's "### Traces To" section

   Mark: source = "auto-generated from PRD acceptance criteria"
   ```

**For `scope == "prd"`:**

1. Fetch the PRD:
   ```
   prd = mcp__asdlc__get_prd(prd_id="{target_id}")
   prd_content = prd["content"]
   ```

2. Parse ALL acceptance criteria and user stories from the PRD content
3. Generate scenarios from every AC

**For `scope == "full"`:**

1. List all PRDs:
   ```
   prds = mcp__asdlc__list_prds()
   ```

2. For each PRD, load its content and parse acceptance criteria
3. Aggregate into a comprehensive regression set

#### 5b. Classify and Generate Scenarios

For each acceptance criterion or test scenario, classify it into one or more test types:

**Browser scenario** — AC mentions any of these keywords:
- UI, page, form, button, navigate, display, render, click, modal, toast, dialog, menu, dropdown, tab, sidebar, header, footer, layout, responsive, visible, hidden, show, hide, redirect, dashboard, screen, view

Generate Playwright MCP steps:
```
Browser Test: {scenario_name}
  Steps:
    1. mcp__playwright__browser_navigate(url="{app_url}{path}")
    2. mcp__playwright__browser_snapshot() — verify initial state
    3. {interaction steps — fill_form, click, wait_for, etc.}
    4. mcp__playwright__browser_snapshot() — verify final state
  Expected: {expected_outcome}
```

**API scenario** — AC mentions any of these keywords:
- endpoint, request, response, status code, API, POST, GET, PUT, DELETE, PATCH, JSON, header, authentication, token, 200, 201, 400, 401, 403, 404, 500, payload, body, schema

Generate curl steps:
```
API Test: {scenario_name}
  Method: {HTTP_METHOD}
  Path: {api_path}
  Headers: {headers}
  Body: {request_body or "none"}
  Expected Status: {expected_status_code}
  Expected Response: {expected_response_shape}
```

**Behavioral scenario** — AC describes a multi-step flow (create, verify, update, delete):
```
Behavioral Test: {scenario_name}
  Steps:
    1. {action} → verify {assertion}
    2. {action} → verify {assertion}
    ...
  Type: mixed (API + Browser steps in sequence)
```

#### 5c. Apply Mode Filter

After classification, filter scenarios based on `mode_filter`:

```
If mode_filter == "api-only":
  Remove all browser scenarios
  Keep API and behavioral scenarios (behavioral runs API steps only)

If mode_filter == "browser-only":
  Remove all API scenarios
  Keep browser and behavioral scenarios (behavioral runs browser steps only)

If mode_filter == "both":
  Keep all scenarios
```

#### 5d. Present Scenarios for Approval

Before executing, display the generated scenarios to the user:

```
Generated Test Scenarios ({source}):
─────────────────────────────────────────────

  Browser Tests ({browser_count}):
    B1: {scenario_description}
    B2: {scenario_description}
    B3: {scenario_description}

  API Tests ({api_count}):
    A1: {scenario_description}
    A2: {scenario_description}
    A3: {scenario_description}
    A4: {scenario_description}

  Behavioral Tests ({behavioral_count}):
    F1: {scenario_description} ({step_count} steps)

  Total: {total_count} scenarios

AskUserQuestion({
  questions: [{
    question: "Review the generated test scenarios above. Proceed with execution?",
    header: "Test Scenarios Approval",
    options: [
      { label: "Execute all", description: "Run all generated test scenarios" },
      { label: "Select scenarios", description: "Choose which scenarios to run" },
      { label: "Edit scenarios", description: "Modify scenarios before running (describe changes)" },
      { label: "Abort", description: "Cancel testing" }
    ],
    multiSelect: false
  }]
})
```

**Handling responses:**

- **"Execute all"** — Proceed to Step 6 (Browser Tests) and Step 7 (API Tests) with all scenarios
- **"Select scenarios"** — Ask: "Which scenarios to run? Provide scenario IDs (e.g., B1, A2, F1)." Filter to selected scenarios.
- **"Edit scenarios"** — Ask: "Describe the changes you want to make to the scenarios." Apply the described changes and re-display.
- **"Abort"** — Stop execution. Report: "Testing cancelled by user."

**Concrete example output:**

```
Generated Test Scenarios (auto-generated from PRD acceptance criteria):
─────────────────────────────────────────────

  Browser Tests (3):
    B1: Navigate to login page, verify form renders with email and password fields
    B2: Submit valid credentials, verify redirect to dashboard
    B3: Submit invalid credentials, verify error message displays

  API Tests (4):
    A1: POST /api/login with valid credentials → 200 + JWT token in response
    A2: POST /api/login with invalid credentials → 401 + error message
    A3: GET /api/profile without Authorization header → 401
    A4: GET /api/profile with valid Bearer token → 200 + user data

  Behavioral Tests (1):
    F1: Login flow end-to-end — POST login → extract token → GET profile with token → verify user data (3 steps)

  Total: 8 scenarios

Proceed with execution? [Execute all]
```

---

### Step 6: Execute Browser Tests

For each browser test scenario, execute using Playwright MCP tools. Skip this step entirely if `mode_filter == "api-only"` or `playwright_available == false`.

```
browser_results = []

For each browser scenario (B1, B2, ...):

  # Log start
  "Running browser test {scenario_id}: {scenario_description}..."

  try:
    # 1. Navigate to the target page
    mcp__playwright__browser_navigate(url="{app_url}{scenario_path}")

    # 2. Verify initial page state
    initial_snapshot = mcp__playwright__browser_snapshot()
    # Check that the expected elements are present in the snapshot
    # e.g., verify page title, form fields, navigation elements

    # 3. Execute interaction steps (varies per scenario)
    # Example interactions:

    # Fill a form:
    mcp__playwright__browser_fill_form(fields=[
      {"selector": "{field_selector}", "value": "{field_value}"},
      {"selector": "{field_selector}", "value": "{field_value}"}
    ])

    # Click a button or link:
    mcp__playwright__browser_click(selector="{button_selector}")

    # Wait for navigation or element:
    mcp__playwright__browser_wait_for(selector="{expected_element_selector}")

    # Handle dialogs if expected:
    mcp__playwright__browser_handle_dialog(action="accept")

    # 4. Verify final page state
    final_snapshot = mcp__playwright__browser_snapshot()

    # 5. Validate against expected outcome
    # Parse the snapshot content and check for expected text, elements, or states
    # Compare snapshot content against the scenario's expected outcome

    if expected_outcome_found_in_snapshot:
      browser_results.append({
        "id": "{scenario_id}",
        "description": "{scenario_description}",
        "status": "pass",
        "evidence": "Snapshot confirmed: {what was verified}"
      })
    else:
      # Take a screenshot for failure evidence
      mcp__playwright__browser_take_screenshot(path="/tmp/test-failure-{scenario_id}.png")
      browser_results.append({
        "id": "{scenario_id}",
        "description": "{scenario_description}",
        "status": "fail",
        "expected": "{expected_outcome}",
        "actual": "{what was actually found in snapshot}",
        "screenshot": "/tmp/test-failure-{scenario_id}.png"
      })

  except Exception as e:
    # Capture failure with screenshot if possible
    try:
      mcp__playwright__browser_take_screenshot(path="/tmp/test-failure-{scenario_id}.png")
    except:
      pass  # Screenshot may fail if browser crashed

    browser_results.append({
      "id": "{scenario_id}",
      "description": "{scenario_description}",
      "status": "fail",
      "expected": "{expected_outcome}",
      "actual": "Error: {error_message}",
      "screenshot": "/tmp/test-failure-{scenario_id}.png"
    })

# After all browser tests complete, close the browser
mcp__playwright__browser_close()
```

#### Browser Test Patterns

Use these Playwright MCP tool patterns for common test scenarios:

**Navigation and page verification:**
```
mcp__playwright__browser_navigate(url="{app_url}/login")
snapshot = mcp__playwright__browser_snapshot()
# Check snapshot for expected elements (form, inputs, buttons)
```

**Form submission:**
```
mcp__playwright__browser_fill_form(fields=[
  {"selector": "input[name='email']", "value": "test@example.com"},
  {"selector": "input[name='password']", "value": "password123"}
])
mcp__playwright__browser_click(selector="button[type='submit']")
mcp__playwright__browser_wait_for(selector=".dashboard")
```

**Verifying text content:**
```
snapshot = mcp__playwright__browser_snapshot()
# Parse snapshot for expected text strings, error messages, success messages
```

**Verifying redirects:**
```
mcp__playwright__browser_click(selector="{trigger_selector}")
mcp__playwright__browser_wait_for(selector="{target_page_indicator}")
snapshot = mcp__playwright__browser_snapshot()
# Verify the URL changed and target page content is visible
```

**Verifying error states:**
```
mcp__playwright__browser_fill_form(fields=[...invalid_data...])
mcp__playwright__browser_click(selector="button[type='submit']")
mcp__playwright__browser_wait_for(selector=".error-message")
snapshot = mcp__playwright__browser_snapshot()
# Verify error text matches expected message
```

---

### Step 7: Execute API Tests

For each API test scenario, execute using Bash/curl. Skip this step entirely if `mode_filter == "browser-only"`.

```
api_results = []
stored_tokens = {}  # Store tokens/IDs for multi-step behavioral tests

For each API scenario (A1, A2, ...) and behavioral API steps (F1-step1, F1-step2, ...):

  # Log start
  "Running API test {scenario_id}: {scenario_description}..."

  # 1. Build and execute curl command
  curl_command = build_curl_command(scenario)

  result = Bash("{curl_command}")

  # The curl command uses -w '\n%{http_code}' to append the status code
  # Split the output: everything before the last line is the response body,
  # the last line is the HTTP status code.

  lines = result.strip().split('\n')
  actual_status = lines[-1]  # Last line is the HTTP status code
  response_body = '\n'.join(lines[:-1])  # Everything else is the body

  # 2. Parse response
  try:
    response_json = parse_json(response_body)
  except:
    response_json = null  # Response is not JSON

  # 3. Validate based on configured depth

  ## Status code validation (always performed)
  status_match = (actual_status == expected_status)

  ## Response shape validation (check expected keys exist)
  shape_match = true
  if expected_response_keys:
    for key in expected_response_keys:
      if key not in response_json:
        shape_match = false

  ## Full contract validation (if api_schema is configured)
  contract_match = true
  if api_schema_path:
    schema = Read("{api_schema_path}")
    # Compare response structure against schema definition for this endpoint
    # Verify all required fields are present and types match
    contract_match = validate_against_schema(response_json, schema, endpoint)

  ## Behavioral validation (for multi-step flows)
  # For behavioral tests, extract values for subsequent steps
  if scenario_type == "behavioral":
    # Extract IDs, tokens, or other values needed by later steps
    # e.g., token = response_json["token"]
    # e.g., created_id = response_json["id"]
    # Store for use in subsequent steps
    if "token" in response_json:
      stored_tokens["auth_token"] = response_json["token"]
    if "id" in response_json:
      stored_tokens["created_id"] = response_json["id"]

  # 4. Record result
  passed = status_match and shape_match and contract_match

  if passed:
    api_results.append({
      "id": "{scenario_id}",
      "description": "{scenario_description}",
      "status": "pass",
      "http_status": actual_status,
      "evidence": "Status {actual_status} matches expected {expected_status}"
    })
  else:
    api_results.append({
      "id": "{scenario_id}",
      "description": "{scenario_description}",
      "status": "fail",
      "http_status": actual_status,
      "expected_status": expected_status,
      "expected_body": "{expected_response_description}",
      "actual_body": response_body,
      "evidence": "Full response captured"
    })
```

#### Curl Command Construction

Build curl commands with proper headers, methods, and body handling:

**GET request (no auth):**
```
Bash("curl -s -w '\n%{http_code}' -X GET {api_base}{path} -H 'Content-Type: application/json'")
```

**GET request (with auth token):**
```
Bash("curl -s -w '\n%{http_code}' -X GET {api_base}{path} -H 'Content-Type: application/json' -H 'Authorization: Bearer {token}'")
```

**POST request (with JSON body):**
```
Bash("curl -s -w '\n%{http_code}' -X POST {api_base}{path} -H 'Content-Type: application/json' -d '{\"key\": \"value\"}'")
```

**PUT request (with JSON body and auth):**
```
Bash("curl -s -w '\n%{http_code}' -X PUT {api_base}{path} -H 'Content-Type: application/json' -H 'Authorization: Bearer {token}' -d '{\"key\": \"updated_value\"}'")
```

**DELETE request (with auth):**
```
Bash("curl -s -w '\n%{http_code}' -X DELETE {api_base}{path} -H 'Content-Type: application/json' -H 'Authorization: Bearer {token}'")
```

#### Behavioral Test Flows

For behavioral tests that span multiple steps, execute each step in order and carry state between them:

```
Behavioral Test Example: CRUD Flow
  Step 1: POST /api/items (create) → extract "id" from response
  Step 2: GET /api/items/{id} (read) → verify data matches creation payload
  Step 3: PUT /api/items/{id} (update) → verify 200
  Step 4: GET /api/items/{id} (re-read) → verify updated data
  Step 5: DELETE /api/items/{id} (delete) → verify 200 or 204
  Step 6: GET /api/items/{id} (verify gone) → verify 404
```

Each step uses `stored_tokens` to carry forward values like IDs, tokens, or other dynamic data extracted from previous responses.

---

### Step 8: Report Results

After all tests complete, display a structured results report.

```
scope_description = derive_scope_description(scope, target_id)
# e.g., "Task PROJ-T00001", "PRD PROJ-P0001", "Full Regression"

browser_passed = count(r for r in browser_results if r["status"] == "pass")
browser_total = len(browser_results)
api_passed = count(r for r in api_results if r["status"] == "pass")
api_total = len(api_results)
total_passed = browser_passed + api_passed
total_tests = browser_total + api_total
total_failed = total_tests - total_passed
```

Display the report:

```
Runtime Test Results for {scope_description}:
─────────────────────────────────────────────
```

**Browser Tests section** (skip if `mode_filter == "api-only"` or no browser tests were generated):

```
Browser Tests: {browser_passed}/{browser_total}
```

For each browser result:

```
  If status == "pass":
    "  {checkmark} {scenario_id}: {scenario_description}"

  If status == "fail":
    "  {cross} {scenario_id}: {scenario_description}"
    "     Screenshot: {screenshot_path}"
    "     Expected: {expected_outcome}"
    "     Actual: {actual_outcome}"
```

**API Tests section** (skip if `mode_filter == "browser-only"` or no API tests were generated):

```
API Tests: {api_passed}/{api_total}
```

For each API result:

```
  If status == "pass":
    "  {checkmark} {scenario_id}: {scenario_description} -> {actual_status}"

  If status == "fail":
    "  {cross} {scenario_id}: {scenario_description} -> expected {expected_status}, got {actual_status}"
    "     Response: {actual_body}"  (truncated to first 200 chars if longer)
```

**Summary section:**

```
Summary: {total_passed}/{total_tests} passed, {total_failed} failed
Status: {PASS if total_failed == 0, FAIL if total_failed > 0}
```

**Outcome messages:**

```
If total_failed == 0:
  "All runtime tests passed. This result can be used by quality gates."

If total_failed > 0:
  "Runtime tests failed. Fix the failing tests before proceeding."

  AskUserQuestion({
    questions: [{
      question: "{total_failed} test(s) failed. How would you like to proceed?",
      header: "Test Failures",
      options: [
        { label: "Review failures", description: "Investigate each failure in detail" },
        { label: "Re-run failed", description: "Re-execute only the failed scenarios" },
        { label: "Accept and continue", description: "Acknowledge failures and proceed anyway" },
        { label: "Abort", description: "Stop and fix failures before continuing" }
      ],
      multiSelect: false
    }]
  })

  If "Review failures":
    For each failed result, display full details:
      - Full curl command used (for API tests)
      - Full response body (for API tests)
      - Screenshot path and snapshot content (for browser tests)
      - Expected vs actual comparison

  If "Re-run failed":
    Collect failed scenario IDs
    Re-execute only those scenarios (loop back to Step 6/7 with filtered list)
    Re-display updated results

  If "Accept and continue":
    Log a warning:
      "Runtime test failures accepted by user. {total_failed} failures noted."
    Proceed (caller can check this result)

  If "Abort":
    "Testing stopped. Fix the {total_failed} failing test(s) and re-run /sdlc:test."
    STOP
```

**Concrete report example:**

```
Runtime Test Results for Task PROJ-T00001:
─────────────────────────────────────────────

Browser Tests: 2/3
  B1: Navigate to login page — form renders correctly
  B2: Valid credentials — redirect to dashboard
  B3: Invalid credentials — error message
     Screenshot: /tmp/test-failure-B3.png
     Expected: Error toast with "Invalid email or password"
     Actual: No error element found on page

API Tests: 3/4
  A1: POST /api/login (valid) — 200
  A2: POST /api/login (invalid) — 401
  A3: GET /api/profile (no token) — 401
  A4: GET /api/profile (with token) — expected 200, got 500
     Response: {"error": "Internal server error"}

Summary: 5/7 passed, 2 failed
Status: FAIL

Runtime tests failed. Fix the failing tests before proceeding.
```

---

## Integration Notes

This template integrates with the a-sdlc quality gate system at multiple points:

### Quality Gate Integration Points

1. **`task-complete.md`** calls `/sdlc:test --task <id>` as part of the review gate process before allowing task completion. If runtime tests fail, the task cannot be marked complete unless the user explicitly overrides.

2. **`sprint-run.md`** calls `/sdlc:test --task <id>` after each task implementation in the subagent review gates. Failed runtime tests trigger the self-heal loop.

3. **`pr-feedback.md`** calls `/sdlc:test --full` as a pre-merge regression check before processing PR feedback. Full regression failure blocks PR approval.

### Correction Logging

When runtime tests fail and are later fixed, log corrections for the retrospective:

```
mcp__asdlc__log_correction(
  context_type="task",
  context_id="{task_id}",
  category="testing",
  description="Runtime test failure: {scenario_id} — {failure_description}. Fixed by: {fix_description}"
)
```

### Configuration Precedence

1. Explicit flags (`--api-only`, `--browser-only`) override all config
2. `testing.runtime.mode` from `.sdlc/config.yaml` provides project defaults
3. Playwright availability is a hard constraint — if unavailable, browser tests are skipped regardless of config

---

## Edge Cases

| Scenario | Handling |
|----------|----------|
| App not running | Fallback chain: config URL, auto-detect, ask user, offer to start |
| Playwright not installed | Warn and fall back to API-only (unless `--browser-only` flag) |
| No acceptance criteria found | Ask user to describe test scenarios manually |
| PRD has no testable ACs | Report: "No testable acceptance criteria found. Add AC-xxx entries to the PRD." |
| API returns non-JSON response | Treat as raw text, skip JSON shape validation |
| Browser test element not found | Take screenshot, report failure with snapshot context |
| Auth token needed but not available | Prompt user for credentials or token, or look for test credentials in config |
| Behavioral test step fails mid-flow | Mark remaining steps as skipped, report the failing step |
| Full regression with many PRDs | Process PRDs sequentially, aggregate all results into single report |
| Config has no `testing.runtime` section | Prompt user for app URL and use defaults for everything else |

---

## Examples

```
# Test changes for a specific task
/sdlc:test --task PROJ-T00001

# Test all acceptance criteria for a PRD
/sdlc:test --prd PROJ-P0001

# Full regression test
/sdlc:test --full

# API tests only (no browser)
/sdlc:test --task PROJ-T00001 --api-only

# Browser tests only (no API)
/sdlc:test --prd PROJ-P0001 --browser-only

# Interactive mode (no flags — asks what to test)
/sdlc:test
```

## Related Commands

- `/sdlc:task-complete` — Marks task as completed (calls `/sdlc:test` in review gates)
- `/sdlc:sprint-run` — Executes sprint tasks (calls `/sdlc:test` after each task)
- `/sdlc:task-start` — Starts task implementation
- `/sdlc:pr-feedback` — Processes PR feedback (calls `/sdlc:test --full` for regression)
