---
hooks:
  PreToolUse:
    - matcher: "Edit|Write|Bash|MultiEdit|NotebookEdit"
      hooks:
        - type: command
          command: "~/.a-sdlc/hooks/block-source-edits.sh prd-investigate"
---

# /sdlc:prd-investigate

## Purpose

Validate and refine an existing PRD against codebase reality, ensuring alignment with both technical implementation context and PRD template compliance.

**Key Difference from `/sdlc:investigate`:**

| Command | Purpose | Modifies PRD |
|---------|---------|--------------|
| `/sdlc:investigate` | Prepare context for task generation | No |
| `/sdlc:prd-investigate` | Validate & update PRD itself | Yes (with approval) |

---

## Usage

```
/sdlc:prd-investigate <prd_id> [options]
```

**Arguments:**
- `prd_id` - ID of PRD to investigate (e.g., `PROJ-P0001`)

**Options:**
- `--depth <level>` - Analysis depth: `quick`, `thorough` (default: thorough)
- `--auto-fix` - Auto-apply non-breaking fixes without prompting
- `--report-only` - Generate report without making changes

## Examples

```
/sdlc:prd-investigate PROJ-P0001
/sdlc:prd-investigate PROJ-P0001 --depth quick
/sdlc:prd-investigate PROJ-P0001 --report-only
/sdlc:prd-investigate PROJ-P0001 --auto-fix
```

---

## Execution Steps

### Phase 1: Load PRD

**1. Get Project Context**

```
mcp__asdlc__get_context()
```

Returns project info including shortname and current statistics.

**2. Load PRD Content**

```
mcp__asdlc__get_prd(prd_id="<prd_id>")
```

Returns:
```json
{
  "id": "PROJ-P0001",
  "title": "Feature Title",
  "content": "# Feature Title\n\n## Overview\n...",
  "status": "draft",
  "version": "1.0",
  "sprint_id": null
}
```

**3. Parse PRD into Sections**

Extract sections from markdown content:
- Overview
- Goals
- Functional Requirements
- Non-Functional Requirements
- User Stories
- Technical Considerations
- Out of Scope
- Success Metrics

---

### Phase 2: Load Context

**1. Read Available Artifacts**

Check and read artifacts from `.sdlc/artifacts/`:

```
Read: .sdlc/artifacts/architecture.md
Read: .sdlc/artifacts/codebase-summary.md
Read: .sdlc/artifacts/directory-structure.md
Read: .sdlc/artifacts/data-model.md
Read: .sdlc/artifacts/key-workflows.md
```

If artifacts are missing or stale, note for recommendation.

**2. Extract PRD References**

From PRD content, identify:
- **Component references**: Files, modules, classes mentioned
- **API references**: Endpoints, services, integrations
- **Data references**: Models, schemas, entities
- **Dependency references**: Libraries, external systems

**3. Verify Referenced Components Exist**

For each component referenced in the PRD:

```
Glob: Find files matching component names
Read: Check component structure and interfaces
Grep: Search for patterns mentioned in PRD
```

**4. Search for Related Patterns**

```
Grep: Search for similar functionality
Grep: Find integration points
Grep: Locate related configuration
```

---

### Phase 3: Validate Alignment

Check if PRD claims match codebase reality:

**Validation Checks:**

| Check | What to Validate | Severity |
|-------|------------------|----------|
| Component Existence | Do referenced files/modules exist? | Error |
| Architecture Fit | Does proposed approach match existing patterns? | Warning |
| Dependency Accuracy | Are listed dependencies available? | Error |
| Technical Assumptions | Are technical claims accurate? | Warning |
| API Compatibility | Do referenced APIs exist and have correct signatures? | Error |
| Data Model Alignment | Do referenced entities match actual schema? | Warning |

**For each discrepancy found:**
1. Record the issue with location (PRD section + line if possible)
2. Categorize severity (Error, Warning, Info)
3. Generate recommended fix
4. Create diff preview if applicable

---

### Phase 4: Template Compliance

Verify PRD has all sections per `prd.template.md`:

**Required Sections (Error if missing):**
- Overview
- Goals
- Functional Requirements
- User Stories
- Out of Scope

**Recommended Sections (Warning if missing):**
- Non-Functional Requirements
- Technical Considerations
- Success Metrics

**Quality Checks:**
- Goals are specific and measurable
- Requirements have clear acceptance criteria
- User stories follow "As a... I want... So that..." format
- Out of Scope explicitly lists exclusions

---

### Phase 5: Generate Investigation Report

Create a comprehensive report:

```markdown
# PRD Investigation Report: {Title}

**PRD ID:** {id}
**Date:** {timestamp}
**Depth:** {quick|thorough}
**Status:** {N} errors, {M} warnings, {P} info

---

## Executive Summary

[Brief overview of findings: X issues found, Y can be auto-fixed]

---

## Template Compliance

| Section | Status | Notes |
|---------|--------|-------|
| Overview | ✅ Present | - |
| Goals | ✅ Present | 3 goals defined |
| Functional Requirements | ✅ Present | 5 requirements |
| Non-Functional Requirements | ⚠️ Missing | Recommended: Add performance requirements |
| User Stories | ✅ Present | 2 stories with acceptance criteria |
| Technical Considerations | ⚠️ Sparse | Only 1 item listed |
| Out of Scope | ✅ Present | 4 exclusions |
| Success Metrics | ❌ Missing | Required for tracking implementation success |

---

## Technical Validation

### Components Referenced

| Component | PRD Claim | Actual Status | Action |
|-----------|-----------|---------------|--------|
| `src/auth/service.ts` | "Existing auth service" | ✅ Found | None |
| `src/api/oauth.ts` | "OAuth handler" | ❌ Not found | Create or update PRD |
| `UserModel` | "Has email field" | ⚠️ Different | Field is `emailAddress` |

### Architecture Alignment

| Aspect | PRD Assumption | Codebase Reality | Match |
|--------|----------------|------------------|-------|
| Pattern | "Service layer" | Uses service pattern ✅ | ✅ |
| Auth | "JWT tokens" | Uses session cookies | ❌ |
| DB | "PostgreSQL" | PostgreSQL ✅ | ✅ |

### Dependencies

| Dependency | PRD States | Actual | Status |
|------------|------------|--------|--------|
| `passport` | "Use for OAuth" | Not in package.json | ❌ Missing |
| `express` | "Framework" | v4.18.2 installed | ✅ OK |

---

## Recommended Adjustments

### Required Fixes (Severity: Error)

**1. Missing component: `src/api/oauth.ts`**
- **Section:** Technical Considerations
- **Current:** "Modify existing OAuth handler at `src/api/oauth.ts`"
- **Fix:** Either create the file or update PRD to reflect creating new handler
- **Recommendation:** Update PRD text to "Create OAuth handler at `src/auth/oauth.ts`"

**2. Incorrect dependency: `passport`**
- **Section:** Technical Considerations
- **Current:** "Use existing passport.js integration"
- **Fix:** Add passport as dependency or use alternative
- **Recommendation:** Add to PRD: "Add passport.js v0.7.0 as new dependency"

### Recommended Updates (Severity: Warning)

**1. Field name mismatch: UserModel.email**
- **Section:** Functional Requirements
- **Current:** "Update user.email with OAuth provider email"
- **Fix:** Use correct field name
- **Recommendation:** Change to "Update user.emailAddress with OAuth provider email"

**2. Missing non-functional requirements**
- **Section:** Non-Functional Requirements
- **Current:** Section missing
- **Recommendation:** Add section with performance and security requirements

### Suggestions (Severity: Info)

**1. Consider adding Success Metrics**
- Helps track implementation completeness
- Suggested metrics based on PRD goals:
  - "OAuth login success rate > 95%"
  - "Login flow completes in < 2 seconds"

---

## Adjustment Preview

```diff
## Technical Considerations

- - Use existing passport.js integration
+ - Add passport.js v0.7.0 as new dependency
- - Modify existing OAuth handler at `src/api/oauth.ts`
+ - Create OAuth handler at `src/auth/oauth.ts`

## Functional Requirements

- 1. **User Email Update**: Update user.email with OAuth provider email
+ 1. **User Email Update**: Update user.emailAddress with OAuth provider email
```

---

## Next Steps

Based on investigation findings:

1. [ ] Review and approve recommended adjustments
2. [ ] Apply fixes to PRD
3. [ ] Run `/sdlc:investigate` for task generation context
4. [ ] Split PRD into tasks with `/sdlc:prd-split`
```

---

### Phase 6: Interactive Updates

Present options to user based on `--auto-fix` and `--report-only` flags:

**Default (Interactive):**

```
📋 Investigation Complete

Found: 2 errors, 2 warnings, 1 suggestion

How would you like to proceed?

1. Apply all fixes (2 errors + 2 warnings)
2. Apply required only (2 errors)
3. Select individual fixes
4. Cancel (no changes)

Choice [1-4]:
```

**With `--report-only`:**
Display report only, no prompts.

**With `--auto-fix`:**
Automatically apply all non-breaking fixes (warnings + info), prompt for errors.

**Applying Updates:**

```
mcp__asdlc__update_prd(
    prd_id="<prd_id>",
    content="<updated_markdown_content>",
    version="<incremented_version>"
)
```

**Confirmation Output:**

```
✅ PRD Updated: PROJ-P0001

📊 Changes Applied:
- Fixed 2 component references
- Updated 1 field name
- Added Non-Functional Requirements section

📋 Version: 1.0 → 1.1

🔗 Next Steps:
- Review changes: /sdlc:prd "PROJ-P0001"
- Investigate for tasks: /sdlc:investigate "PROJ-P0001"
- Split into tasks: /sdlc:prd-split "PROJ-P0001"
```

---

## MCP Tools Used

| Tool | Purpose |
|------|---------|
| `mcp__asdlc__get_context()` | Get project info and statistics |
| `mcp__asdlc__get_prd(prd_id)` | Load PRD content |
| `mcp__asdlc__update_prd(prd_id, content, version)` | Apply PRD changes |
| `Read` | Read artifacts and source files |
| `Grep` | Search for patterns in codebase |
| `Glob` | Find files by name pattern |

---

## Error Handling

**PRD Not Found:**
```
❌ PRD not found: PROJ-P0001

Available PRDs:
  - PROJ-P0002: User Dashboard
  - PROJ-P0003: Payment Integration

Run: /sdlc:prd-list
```

**No Artifacts Available:**
```
⚠️ No artifacts found in .sdlc/artifacts/

Recommendations:
1. Run /sdlc:scan to generate codebase artifacts
2. Continue with --depth quick for limited validation

Proceed without artifacts? [y/N]
```

**No Issues Found:**
```
✅ PRD Investigation Complete: PROJ-P0001

No issues found!

✓ Template compliance: All required sections present
✓ Technical validation: All references verified
✓ Architecture alignment: Matches codebase patterns

PRD is ready for task generation.
Next: /sdlc:prd-split "PROJ-P0001"
```

---

## Quick Investigation (--depth quick)

When using `--depth quick`:

1. Read artifacts only (no deep codebase search)
2. Check template compliance (section presence only)
3. Verify explicitly named files exist (no pattern search)
4. Generate abbreviated report
5. Skip architecture alignment checks

**Use quick depth for:**
- Well-documented codebases with fresh artifacts
- Simple PRDs with limited scope
- Quick sanity checks before task generation

**Use thorough depth for:**
- Complex PRDs spanning multiple components
- PRDs referencing unfamiliar codebase areas
- When artifacts are stale or incomplete

---

## Notes

1. **Run after PRD creation:** Best results when PRD has been drafted but not yet split
2. **Preserves PRD structure:** Updates fix issues without changing overall organization
3. **Version tracking:** Each update increments PRD version for audit trail
4. **Non-destructive:** Original content preserved until explicit approval
5. **Complements `/sdlc:investigate`:** Use this to validate PRD, then `/sdlc:investigate` for task context
