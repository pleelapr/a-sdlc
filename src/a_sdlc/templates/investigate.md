---
hooks:
  PreToolUse:
    - matcher: "Edit|Write|Bash|MultiEdit|NotebookEdit"
      hooks:
        - type: command
          command: "~/.a-sdlc/hooks/block-source-edits.sh investigate"
---

# /sdlc:investigate - Problem-Centric Root Cause Analysis

## Purpose

Systematically analyze bugs, errors, and problems using:
- All accumulated SDLC data (tasks, PRDs, sprints, artifacts)
- Codebase analysis
- Online documentation and web search
- Historical retrospective analysis

**Key Difference from Other Commands:**

| Command | Input | Purpose | Searches Web |
|---------|-------|---------|--------------|
| **`/sdlc:investigate "<problem>"`** | Problem description OR error | Root cause analysis | Yes |
| `/sdlc:prd-investigate <prd_id>` | PRD ID | PRD validation against codebase | No |

---

## CRITICAL: Scope Boundaries

**This skill ONLY investigates problems. It does NOT implement fixes.**

- **NEVER** proceed to code fixes or implementation automatically
- **NEVER** write source code or make code changes
- **NEVER** use Edit, Write, or Bash tools to modify project files
- **NEVER** automatically create tasks or split PRDs (only with `--create-prd` after user approval)
- **ALWAYS** stop after report generation and wait for user's next command

**RIGHT**: Investigate → Generate report → STOP (or create PRD if `--create-prd`)
**WRONG**: Investigate → Start fixing code → Create tasks → Implement

---

## Usage

```
/sdlc:investigate "<problem_description>" [options]
/sdlc:investigate --error "<paste_error_or_stack_trace>" [options]
```

**Arguments:**
- `problem_description` - Natural language description of the bug/error/issue
- `--error` - Flag to indicate input is an error message/stack trace

**Options:**
- `--depth <quick|thorough>` - Analysis depth (default: thorough)
- `--retrospect` - Enable historical pattern analysis across past sprints/tasks
- `--create-prd` - Generate a fix PRD after investigation
- `--save` - Save investigation report to `.sdlc/investigations/`
- `--no-web` - Disable online search (offline mode)

## Examples

```
/sdlc:investigate "API returns 500 error on user login"
/sdlc:investigate "Memory leak in background worker process"
/sdlc:investigate --error "TypeError: Cannot read property 'id' of undefined at UserService.ts:42"
/sdlc:investigate "Database connection timeout under load" --retrospect
/sdlc:investigate "OAuth callback failing" --create-prd
```

---

## Execution Steps

### Phase 1: Parse Input & Extract Signals

**For problem descriptions:**
1. Extract keywords (components, errors, behaviors)
2. Identify affected areas (auth, database, API, etc.)
3. Detect technology references (libraries, frameworks)

**For error messages/stack traces (`--error` flag):**
1. Parse error type and message
2. Extract file paths and line numbers
3. Identify library/framework from stack frames
4. Detect error codes or status codes

**Signal Extraction Pattern:**

```
Input: "TypeError: Cannot read property 'id' of undefined at UserService.ts:42"

Extracted Signals:
- Error Type: TypeError
- Error Message: Cannot read property 'id' of undefined
- File: UserService.ts
- Line: 42
- Keywords: id, undefined, UserService
- Component Area: User/Service layer
```

---

### Phase 2: Search SDLC History

Query all SDLC data for related context:

**1. Get Project Context**

```
mcp__asdlc__get_context()
```

Returns project info including shortname, statistics, and current state.

**2. Search Tasks for Related Work**

```
mcp__asdlc__list_tasks(status="completed")  # Past implementations
mcp__asdlc__list_tasks(status="blocked")    # Known blockers
```

For each potentially related task:
```
mcp__asdlc__get_task(task_id)
```

**3. Search PRDs for Requirements Context**

```
mcp__asdlc__list_prds()
```

For each potentially related PRD:
```
mcp__asdlc__get_prd(prd_id)
```

**4. Search Sprints for Timeline Context**

```
mcp__asdlc__list_sprints()
```

**5. Check External System Context**

```
mcp__asdlc__list_sync_mappings()
```

**Build Correlation Report:**
- Tasks that touched affected components
- PRDs that defined related requirements
- Sprints where similar issues occurred
- External issues (Jira/Linear) with related context

---

### Phase 3: Analyze Codebase

**1. Read Artifacts for Context**

```
Read: .sdlc/artifacts/architecture.md
Read: .sdlc/artifacts/data-model.md
Read: .sdlc/artifacts/key-workflows.md
Read: .sdlc/artifacts/codebase-summary.md
Read: .sdlc/artifacts/directory-structure.md
```

**2. Search for Affected Code**

From error stack trace or extracted keywords:

```
Grep: Search for error patterns in codebase
Glob: Find affected files by name patterns
Read: Examine suspect code sections
```

**3. Trace Dependencies (if Serena available)**

```
mcp__serena__find_symbol(symbol_name)
mcp__serena__find_referencing_symbols(symbol_name)
```

---

### Phase 4: Search Online Resources

**Always enabled unless `--no-web` is specified.**

**1. Search Official Documentation via Context7**

```
mcp__context7__resolve-library-id(library_name)
mcp__context7__query-docs(library_id, query)
```

**2. Web Search for Error Messages and Solutions**

```
WebSearch: "<error_message>" + <library> + "solution"
WebSearch: "known issues" + <library> + <version>
WebSearch: <error_code> + <framework> + "fix"
```

**3. Fetch Specific Documentation Pages**

```
WebFetch: Official docs for affected libraries
WebFetch: GitHub issues for relevant repos
```

**Search Targets:**
- Official library documentation
- Stack Overflow solutions
- GitHub issues for related libraries
- Known CVEs for dependencies
- Framework migration guides (if version mismatch suspected)

---

### Phase 5: Retrospective Analysis (--retrospect)

**Only executed when `--retrospect` flag is provided.**

**1. Analyze Completed Sprints**

- When did similar issues appear?
- What tasks addressed related areas?
- What was the resolution pattern?

**2. Track Recurring Issues**

- Same component failing repeatedly?
- Pattern of related bugs?
- Incomplete previous fixes?

**3. Identify Contributing Factors**

- Recent changes to affected areas
- Dependencies updated recently
- Configuration changes

**Retrospective Query Pattern:**

```
# Find tasks that modified affected files
mcp__asdlc__list_tasks(status="completed")
# Filter by: component matches affected area

# Find sprints with related work
mcp__asdlc__list_sprints()
# Check sprint goals and completed task patterns
```

---

### Phase 6: Root Cause Synthesis

Combine all findings into systematic analysis:

**Evidence Matrix Format:**

| Source | Finding | Confidence | Relevance |
|--------|---------|------------|-----------|
| SDLC History | Task X modified this code | High | Direct |
| Codebase | Missing null check at line 42 | High | Direct |
| Web Search | Known issue in library v2.3 | Medium | Related |
| Retrospect | Similar bug fixed in Sprint 3 | High | Pattern |

**Root Cause Candidates:**
1. **Primary hypothesis** with supporting evidence
2. **Alternative hypothesis** with evidence
3. **Contributing factors** that may exacerbate the issue

**Recommended Fix:**
- Immediate actions to resolve
- Long-term improvements to prevent recurrence
- Prevention measures for similar issues

---

### Phase 7: Generate Investigation Report

**Report Format:**

```markdown
# Investigation Report: {Problem Summary}

**Date:** {timestamp}
**Depth:** {quick|thorough}
**Retrospect:** {enabled|disabled}
**Web Search:** {enabled|disabled}

---

## Problem Statement

{Original problem description or parsed error}

**Extracted Signals:**
- Error Type: {type}
- Affected Component: {component}
- Keywords: {keyword1, keyword2, ...}

---

## Executive Summary

{Brief findings: root cause identified, confidence level, recommended action}

---

## Evidence from SDLC History

### Related Tasks

| Task ID | Title | Status | Relevance |
|---------|-------|--------|-----------|
| {id} | {title} | {status} | {how it relates} |

### Related PRDs

| PRD ID | Title | Connection |
|--------|-------|------------|
| {id} | {title} | {how it relates} |

### Sprint Context

{When this area was last modified, by whom, what changed}

---

## Codebase Analysis

### Affected Files

| File | Issue Found | Severity |
|------|-------------|----------|
| {path:line} | {description} | {High/Medium/Low} |

### Architecture Impact

{How this issue relates to system architecture}

### Code Patterns Observed

{Relevant patterns or anti-patterns found in affected code}

---

## Online Research Findings

### Official Documentation

- **{Library}**: {Relevant finding from docs}

### Known Issues

- **{Source}**: {GitHub issue or SO answer with solution}

### Security Advisories

- {Any CVEs or security notes, or "None found"}

---

## Retrospective Patterns (if --retrospect)

### Historical Occurrences

{Similar issues found in past sprints}

### Pattern Analysis

{Recurring theme or systemic issue}

### Timeline of Related Changes

{When affected code was last modified and by which tasks}

---

## Root Cause Analysis

### Primary Cause

{Description with evidence}

**Evidence:**
1. {Evidence point 1}
2. {Evidence point 2}

### Contributing Factors

1. {Factor 1 with explanation}
2. {Factor 2 with explanation}

### Confidence Level

**{High/Medium/Low}**

{Reasoning for confidence assessment}

---

## Recommendations

### Immediate Fix

{What to do now - specific steps}

### Prevention

{How to prevent recurrence}

### Follow-up Tasks

{Suggested additional work}

---

## Recommended Next Steps (For User to Execute)

1. [ ] Review findings and decide on approach
2. [ ] Apply immediate fix
3. [ ] Verify fix resolves the issue
4. [ ] Create fix PRD if needed: `/sdlc:investigate "..." --create-prd`
5. [ ] Update related documentation
6. [ ] Add regression tests
```

---

### Phase 8: Save Report (--save)

**When `--save` flag is used:**

1. Create `.sdlc/investigations/` directory if needed
2. Save report as `{timestamp}_{sanitized_problem_summary}.md`
3. Confirm save location to user

```
✅ Investigation saved: .sdlc/investigations/2025-01-28_api-500-error-login.md
```

---

### Phase 9: Optional PRD Creation (--create-prd)

**When `--create-prd` flag is used:**

1. Generate PRD content from investigation findings
2. Structure PRD with fix requirements
3. Call MCP tool to create PRD

```
mcp__asdlc__create_prd(
    title="Fix: {Problem Summary}",
    content="{Generated PRD from findings}"
)
```

**Generated PRD Structure:**

```markdown
# Fix: {Problem Summary}

## Overview

This PRD addresses the issue identified through investigation: {problem description}

**Investigation Date:** {date}
**Root Cause:** {primary cause summary}

## Goals

1. Resolve the immediate issue: {specific goal}
2. Prevent recurrence through: {prevention goal}
3. Add safeguards: {safeguard goal}

## Functional Requirements

### FR-1: {Fix Requirement}

{Description of what needs to be fixed}

**Acceptance Criteria:**
- [ ] {Specific testable criterion}
- [ ] {Another criterion}

### FR-2: {Prevention Requirement}

{Description of preventive measure}

## Technical Considerations

- Affected files: {list from investigation}
- Dependencies: {relevant dependencies}
- Risk areas: {identified risks}

## Out of Scope

- {What this fix explicitly does NOT address}

## Success Metrics

- Issue no longer reproducible
- {Additional metrics from investigation}
```

**Confirmation Output:**

```
✅ Fix PRD Created: {PRD_ID}

Title: Fix: {Problem Summary}
Status: draft

Next Steps:
1. Review PRD: /sdlc:prd "{PRD_ID}"
2. Split into tasks: /sdlc:prd-split "{PRD_ID}"
```

## ⛔ STOP HERE

**Do NOT proceed further.** The investigation workflow is complete.

The user must explicitly decide next steps:
- Review findings and apply fix manually
- Run `/sdlc:investigate "..." --create-prd` to generate a fix PRD
- Run `/sdlc:prd-split {prd_id}` if PRD was created

**Wait for user's next instruction.**

---

## MCP Tools Used

| Tool | Purpose |
|------|---------|
| `mcp__asdlc__get_context()` | Project info and statistics |
| `mcp__asdlc__list_tasks()` | Historical task search |
| `mcp__asdlc__get_task()` | Task details |
| `mcp__asdlc__list_prds()` | PRD search |
| `mcp__asdlc__get_prd()` | PRD content |
| `mcp__asdlc__list_sprints()` | Sprint history |
| `mcp__asdlc__list_sync_mappings()` | External system context |
| `mcp__asdlc__create_prd()` | Generate fix PRD |
| `mcp__context7__resolve-library-id()` | Find library documentation |
| `mcp__context7__query-docs()` | Query official documentation |
| `WebSearch` | Online solutions search |
| `WebFetch` | Fetch specific pages |
| `Read` | Read artifacts and source files |
| `Grep` | Pattern search in codebase |
| `Glob` | File discovery |
| `mcp__serena__find_symbol()` | Symbol analysis (if available) |
| `mcp__serena__find_referencing_symbols()` | Reference tracing (if available) |

---

## CRITICAL: Scope Boundaries

**This skill ONLY investigates problems. It does NOT implement fixes.**

### ALWAYS:
- Present findings and wait for user decision
- Stop after report generation (or PRD creation if `--create-prd`)
- Ask for approval before creating PRD

### NEVER:
- Automatically fix code without user approval
- Create tasks directly (only PRDs with `--create-prd`)
- Modify existing source files during investigation
- Assume permission to implement changes

**RIGHT**: Investigate → Report findings → STOP (or create PRD if `--create-prd`)
**WRONG**: Investigate → Start fixing code → Create tasks

---

## Quick Investigation (--depth quick)

When using `--depth quick`:

1. Read artifacts only (no deep codebase search)
2. Search SDLC data by keyword match only
3. Perform single web search per keyword
4. Generate abbreviated report
5. Skip retrospective analysis even if flag present

**Use quick depth for:**
- Initial triage of new issues
- Simple error messages with clear solutions
- Well-documented errors with known fixes

**Use thorough depth for:**
- Complex bugs spanning multiple components
- Intermittent or hard-to-reproduce issues
- Security-related concerns
- Performance problems

---

## Error Handling

**No Project Initialized:**
```
❌ No project context found

Initialize a project first:
  /sdlc:init

Or switch to existing project:
  /sdlc:status
```

**No SDLC History:**
```
⚠️ No SDLC history available for this project

Investigation will proceed with:
- Codebase analysis
- Online research

Consider running /sdlc:scan to generate artifacts first.
```

**Web Search Disabled/Failed:**
```
⚠️ Web search skipped (--no-web flag or connectivity issue)

Investigation proceeding with:
- SDLC history
- Local codebase analysis

For complete analysis, ensure internet connectivity and remove --no-web flag.
```

---

## Notes

1. **Run early in debugging:** Use this tool as first step when encountering issues
2. **Preserves context:** Investigation findings help inform fix implementation
3. **Non-destructive:** Only reads and analyzes, never modifies
4. **Builds on SDLC data:** More SDLC history = better investigation results
5. **Web search enhances:** Online resources provide broader solution context
