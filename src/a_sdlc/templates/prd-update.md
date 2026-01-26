# /sdlc:prd-update "<prd_id>" [options]

## Purpose

AI-assisted revision of existing PRDs through section-by-section review with intelligent suggestions.

## Arguments

- **prd_id**: ID (slug) of PRD to update (e.g., "feature-auth")
- **--section, -s**: Focus on specific section only (optional)
- **--fix**: Quick fix mode for typos and formatting (auto-patch bump)
- **--version, -v**: Specify version bump type: patch, minor, or major (optional)
- **--push**: Push to Confluence after update (optional)

## Execution Steps

### 1. Load PRD and Context

- Read `.sdlc/prds/{prd_id}.md`
- Load `.sdlc/prds/.metadata.json` for current version
- Read project artifacts for context (if available):
  - `.sdlc/artifacts/architecture.md`
  - `.sdlc/artifacts/data-model.md`
  - `.sdlc/artifacts/key-workflows.md`

### 2. Parse PRD Sections

Extract sections from markdown:
- Overview
- Problem Statement
- Goals
- Affected Components
- Data Model Changes
- Functional Requirements
- Non-Functional Requirements
- User Stories
- Acceptance Criteria
- Out of Scope
- Open Questions

### 3. Section-by-Section Review

For each section (or --section if specified):

**Display current content:**
```
━━━ Section: Goals ━━━

Current content:
- Enable OAuth authentication
- Support Google and GitHub

🤖 AI Analysis:
⚠ Missing quantitative metrics
⚠ No security requirements

Action? [keep/edit/skip]
```

**If edit selected:**
- Opens text editor with current content
- User makes changes
- System tracks modified sections

**AI Suggestion Phase** (Phase 3 enhancement):
```
🤖 Suggested improvements:
1. Add: "Login completes in <2 seconds"
2. Add: "OAuth tokens encrypted at rest"
3. Add: "99.9% uptime SLA"

Apply AI suggestions? [yes/custom/no]
```

### 4. Version Bump Detection

Analyze changes and suggest bump:

```
🔢 Version Bump Recommendation

Current: 1.0.0
Change type: Content updates
Suggested: MINOR → 1.1.0

Confirm bump type? [patch/minor/major]
```

**Version Bump Rules**:
- **PATCH** (x.y.Z): Typo fixes, formatting, metadata updates
- **MINOR** (x.Y.0): Content updates, requirement clarifications, added details
- **MAJOR** (X.0.0): Structural changes, scope modifications, component additions/removals

### 5. Save and Update Metadata

- Update PRD content
- Bump version
- Update timestamp
- Append to update_history
- Save to `.sdlc/prds/{prd_id}.md`
- Update `.sdlc/prds/.metadata.json`

### 6. Display Summary

```
✅ PRD updated: .sdlc/prds/feature-auth.md

📊 Changes:
- Version: 1.0.0 → 1.1.0
- Sections modified: 2
- Change type: Minor update

🔗 Next steps:
- View: a-sdlc prd show feature-auth
- Push to Confluence: a-sdlc prd push feature-auth
```

## Output Examples

**Full interactive update:**
```
User: /sdlc:prd-update "feature-auth"

Updating PRD: User Authentication System
Current version: 1.0.0

━━━ Section: Goals ━━━
Current content:
- Enable OAuth authentication

Action? [keep/edit/skip] edit

[Opens editor for changes]

✓ Updated Goals

━━━ Section: Requirements ━━━
...

🔢 Version Bump Recommendation
Current: 1.0.0
Suggested: MINOR → 1.1.0

Confirm bump type? [patch/minor/major] minor

Brief summary of changes: Added quantitative goals and security requirements

✅ PRD updated: .sdlc/prds/feature-auth.md

📊 Changes:
- Version: 1.0.0 → 1.1.0
- Sections modified: 2
- Change type: Minor

🔗 Next steps:
- View: a-sdlc prd show feature-auth
- Push: a-sdlc prd push feature-auth
```

**Update specific section:**
```
User: /sdlc:prd-update "feature-auth" --section "Goals"

Only updating section: Goals

━━━ Section: Goals ━━━
[Section-specific update workflow]

✅ PRD updated
Version: 1.0.0 → 1.0.1 (patch)
```

**Quick fix mode:**
```
User: /sdlc:prd-update "feature-auth" --fix

Quick fix mode: Auto-detecting issues...

Enter your fixes (or press Enter to skip):
Changes: Fixed typos in Requirements section

✅ PRD updated
Version: 1.0.0 → 1.0.1 (patch)
```

**With Confluence push:**
```
User: /sdlc:prd-update "feature-auth" --push

[Update workflow...]

✅ PRD updated locally
Pushing to Confluence...
✓ Pushed to Confluence
  URL: https://your-workspace.atlassian.net/wiki/spaces/...
```

## Error Handling

**PRD Not Found:**
```
[red]PRD not found: feature-auth[/red]

Available PRDs:
  - feature-dashboard
  - model-downgrade

Run: a-sdlc prd list
```

**Section Not Found:**
```
[red]Section not found: Invalid[/red]

Available sections:
  - Overview
  - Goals
  - Requirements
  ...
```

**Confluence Not Configured:**
```
✅ PRD updated locally

[yellow]Confluence push failed: Plugin not configured[/yellow]
PRD updated locally. Push manually with:
  a-sdlc prd push feature-auth
```

## Notes

- Changes are local-first (not auto-pushed to Confluence)
- Use `a-sdlc prd push {id}` or `--push` flag to sync after update
- Version history tracked in `.metadata.json`
- AI suggestions enhance but don't replace user judgment (Phase 3)
- Quick fix mode is best for typos and formatting corrections
- Section-specific updates allow focused revisions
- Update history preserved for audit trail

## Version History Format

Update history is stored in `.sdlc/prds/.metadata.json`:

```json
{
  "feature-auth": {
    "title": "User Authentication System",
    "version": "1.2.0",
    "created_at": "2025-01-20T10:00:00",
    "updated_at": "2025-01-22T15:30:00",
    "update_history": [
      {
        "version": "1.1.0",
        "timestamp": "2025-01-21T14:00:00",
        "change_type": "minor",
        "sections_modified": ["Goals", "Acceptance Criteria"],
        "summary": "Added quantitative goals"
      },
      {
        "version": "1.2.0",
        "timestamp": "2025-01-22T15:30:00",
        "change_type": "minor",
        "sections_modified": ["Data Model Changes"],
        "summary": "Added user roles table"
      }
    ]
  }
}
```
