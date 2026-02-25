# /sdlc:prd-update "<prd_id>" [options]

## Purpose

Update an existing Product Requirements Document through section-by-section review.

## Arguments

- **prd_id**: ID (slug) of PRD to update (e.g., "feature-auth")
- **--section, -s**: Focus on specific section only (optional)
- **--status**: Update PRD status: draft, ready, split, completed (optional)

## Execution Steps

### 1. Load PRD from Database

```
mcp__asdlc__get_prd(prd_id="<prd_id>")
```

Returns:
```json
{
  "id": "feature-auth",
  "title": "User Authentication System",
  "content": "# User Authentication System\n\n## Overview\n...",
  "status": "draft",
  "sprint_id": null,
  "created_at": "2025-01-20T10:00:00Z",
  "updated_at": "2025-01-22T15:30:00Z"
}
```

### 2. Display Current Content

Parse and display the PRD content by sections:
- Overview
- Problem Statement
- Goals
- Affected Components
- Functional Requirements
- Non-Functional Requirements
- User Stories
- Acceptance Criteria
- Out of Scope
- Open Questions

### CRITICAL: Anti-Fluff Rules

**When editing sections, use the user's exact content. Zero AI embellishment.**

- **MUST NOT** rephrase, expand, or "improve" the user's input when applying edits
- **MUST NOT** add requirements, acceptance criteria, or scope items the user didn't type
- **MUST NOT** insert boilerplate ("ensure proper...", "follow best practices...", "handle edge cases...")
- **MUST NOT** merge your suggestions into the user's content without explicit approval
- **MUST** apply the user's edited text verbatim — formatting corrections only
- **MUST** ask if something seems missing rather than adding it yourself

**If the user types two bullet points for Goals, save two bullet points — not five.**

### 3. Section-by-Section Review

For each section (or `--section` if specified):

```
━━━ Section: Goals ━━━

Current content:
- Enable OAuth authentication
- Support Google and GitHub

Action? [keep/edit/skip]
```

If edit selected:
- Collect new content from user
- Track modified sections

### 4. Save Updates

For **content changes**, edit the PRD file directly:
```
prd = mcp__asdlc__get_prd(prd_id="<prd_id>")
Edit(file_path=prd["prd"]["file_path"], old_string="...", new_string="...")
```

For **metadata changes** (status, version, sprint):
```
mcp__asdlc__update_prd(
    prd_id="<prd_id>",
    status="ready",
    version="1.1.0"
)
```

### 5. Display Summary

```
✅ PRD updated: feature-auth

📊 Changes:
- Sections modified: 2
- Status: draft

🔗 Next steps:
- View PRD: /sdlc:prd-list
- Split into tasks: /sdlc:prd-split "feature-auth"
```

## Output Examples

**Full interactive update:**
```
User: /sdlc:prd-update "feature-auth"

Loading PRD: feature-auth...

━━━ Section: Goals ━━━
Current content:
- Enable OAuth authentication

Action? [keep/edit/skip] edit

Enter new content (end with empty line):
> - Enable OAuth authentication
> - Support Google and GitHub
> - Login completes in <2 seconds
>

✓ Updated Goals

━━━ Section: Requirements ━━━
...

✅ PRD updated: feature-auth

📊 Changes:
- Sections modified: 2
```

**Update specific section:**
```
User: /sdlc:prd-update "feature-auth" --section "Goals"

Only updating section: Goals

━━━ Section: Goals ━━━
[Section-specific update workflow]

✅ PRD updated
```

**Update status only:**
```
User: /sdlc:prd-update "feature-auth" --status ready

✅ PRD status updated: draft → ready
```

## Error Handling

**PRD Not Found:**
```
❌ PRD not found: feature-auth

Available PRDs:
  - feature-dashboard
  - model-downgrade

Run: /sdlc:prd-list
```

**Section Not Found:**
```
❌ Section not found: Invalid

Available sections:
  - Overview
  - Goals
  - Requirements
  ...
```

## MCP Tools Used

| Tool | Purpose |
|------|---------|
| `mcp__asdlc__get_prd` | Load PRD content |
| `mcp__asdlc__update_prd` | Update PRD metadata (status, version) |
| `Edit` | Edit PRD content directly in file |
| `mcp__asdlc__list_prds` | Show available PRDs (for errors) |

## PRD Status Values

| Status | Description |
|--------|-------------|
| `draft` | Initial creation, still being refined |
| `ready` | Approved and ready for task breakdown |
| `split` | Tasks have been generated from this PRD |
| `completed` | All tasks done, PRD fully implemented |

## Notes

- PRD content is stored as markdown in the database
- Updates preserve existing structure and metadata
- Status transitions: draft → ready → split → completed
- Use `/sdlc:prd-split` after marking PRD as ready
