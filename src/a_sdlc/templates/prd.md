# /sdlc:prd - PRD Ingestion Pipeline

Ingest a Product Requirements Document (PRD), cross-reference with existing artifacts, and generate structured requirements.

## Subcommands

| Command | Description |
|---------|-------------|
| `/sdlc:prd ingest <file>` | Import a PRD file into the system |
| `/sdlc:prd draft` | Generate requirements from ingested PRD |
| `/sdlc:prd review` | Interactive review and approval |
| `/sdlc:prd list` | List all PRDs (inbox and processed) |

---

## /sdlc:prd ingest

### Purpose

Import a PRD document into `.sdlc/prd/inbox/` for processing.

### Execution Steps

#### 1. Validate Input File

Check that the provided file:
- Exists
- Is readable
- Is a supported format (`.md`, `.txt`, `.docx`)

#### 2. Parse PRD Structure

Flexibly parse the PRD to extract:

**Metadata:**
- Title/Feature Name
- Author (if present)
- Date (if present)
- Version (if present)

**Content Sections:**
- Overview/Summary
- Problem Statement
- Goals/Objectives
- Requirements (functional and non-functional)
- User Stories (if present)
- Acceptance Criteria (if present)
- Out of Scope
- Open Questions

**Parsing Strategy:**
```
1. Look for markdown headers (# ## ###)
2. Identify numbered lists as requirements
3. Extract "As a... I want... So that..." patterns as user stories
4. Extract "Given... When... Then..." patterns as acceptance criteria
```

#### 3. Store in Inbox

Copy/move file to `.sdlc/prd/inbox/`:

```
.sdlc/prd/inbox/
├── prd-{timestamp}-{slug}.md
└── prd-{timestamp}-{slug}.meta.json
```

Meta file contains parsed structure for quick access.

#### 4. Output

```
PRD Ingested Successfully!

File: feature-xyz.md
Title: User Authentication System
Sections found:
  - Overview
  - Requirements (12 items)
  - Acceptance Criteria (5 items)
  - Open Questions (3 items)

Next step: Run /sdlc:prd draft to generate requirements
```

---

## /sdlc:prd draft

### Purpose

Generate structured requirements from the most recent ingested PRD, cross-referencing with existing codebase artifacts.

### Execution Steps

#### 1. Load PRD

Read the most recent PRD from `.sdlc/prd/inbox/` (or specified file).

#### 2. Cross-Reference with Artifacts

**Architecture Analysis:**
```
Read .sdlc/artifacts/architecture.md
Map PRD requirements to affected components:
- Which components need modification?
- Which new components are needed?
- What are the integration points?
```

**Data Model Analysis:**
```
Read .sdlc/artifacts/data-model.md
Identify schema impacts:
- New entities needed
- Entity modifications
- Relationship changes
```

**Workflow Analysis:**
```
Read .sdlc/artifacts/key-workflows.md
Identify workflow impacts:
- New workflows to create
- Existing workflows to modify
- Integration with existing flows
```

#### 3. Generate Requirements Document

Create `.sdlc/requirements/draft.md`:

```markdown
# [Feature Name]

## Overview

[Summarized from PRD overview]

## Problem Statement

[Extracted from PRD or synthesized]

## Requirements

### Functional Requirements

#### FR-001: [Requirement Title]
**Priority:** High | Medium | Low
**Component:** [Affected component from architecture.md]
**Description:** [Detailed requirement]
**Rationale:** [Why this is needed]

#### FR-002: [Requirement Title]
...

### Non-Functional Requirements

#### NFR-001: [Requirement Title]
**Category:** Performance | Security | Scalability | Usability
**Description:** [Detailed requirement]
**Metric:** [Measurable criteria]

## Technical Analysis

### Affected Components
- [Component A] - [Impact description]
- [Component B] - [Impact description]

### Data Model Changes
- [Entity A] - [Change description]
- [New Entity] - [Purpose]

### Workflow Impacts
- [Workflow A] - [Integration point]

## Open Questions

1. [Question from PRD]
2. [Question identified during analysis]

## Out of Scope

- [Item from PRD]
- [Identified exclusion]

## Acceptance Criteria

### AC-001: [Scenario Name]
**Given** [precondition]
**When** [action]
**Then** [expected result]

### AC-002: [Scenario Name]
...
```

#### 4. Output

```
Requirements Draft Generated!

Location: .sdlc/requirements/draft.md

Summary:
  - Functional Requirements: 8
  - Non-Functional Requirements: 3
  - Acceptance Criteria: 5
  - Affected Components: 4
  - Data Model Changes: 2

Cross-References:
  - architecture.md: 4 components identified
  - data-model.md: 2 entities affected
  - key-workflows.md: 1 workflow modified

Next step: Run /sdlc:prd review to approve requirements
```

---

## /sdlc:prd review

### Purpose

Interactive review and approval of drafted requirements.

### Execution Steps

#### 1. Load Draft

Read `.sdlc/requirements/draft.md`.

#### 2. Present for Review

Display requirements summary and ask for:
- Approval of each functional requirement
- Priority adjustments
- Clarification of open questions
- Additional requirements

#### 3. Interactive Loop

For each requirement:
```
FR-001: User Authentication
Priority: High
Component: auth-service

[Description]

Options:
  [A] Approve
  [M] Modify
  [R] Reject
  [S] Skip for now
```

#### 4. Resolve Open Questions

Present each open question:
```
Open Question #1:
"Should we support OAuth providers beyond Google?"

Your answer (or 'defer'):
```

#### 5. Finalize

On approval:

1. Move draft to current:
   ```
   .sdlc/requirements/draft.md → .sdlc/requirements/current.md
   ```

2. Archive version:
   ```
   .sdlc/requirements/versions/v1-{timestamp}.md
   ```

3. Move PRD to processed:
   ```
   .sdlc/prd/inbox/prd-xyz.md → .sdlc/prd/processed/
   ```

#### 6. Output

```
Requirements Approved!

Approved: 8 functional, 3 non-functional
Modified: 2
Rejected: 1
Open questions resolved: 2/3

Current requirements: .sdlc/requirements/current.md
Version archived: .sdlc/requirements/versions/v1-20250121.md

Next step: Run /sdlc:task split to create implementation tasks
```

---

## /sdlc:prd list

### Purpose

List all PRDs in the system.

### Output

```
PRDs in System:

Inbox (pending processing):
  1. feature-auth.md (2025-01-20)
     "User Authentication System"

  2. feature-dashboard.md (2025-01-21)
     "Analytics Dashboard"

Processed:
  1. feature-login.md (2025-01-15)
     "Login Flow Improvements"
     → requirements/versions/v1-20250115.md
```

---

## Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `ingest <file>` | PRD file to import | required |
| `draft --prd <file>` | Specific PRD to draft from | latest |
| `review --auto` | Auto-approve all requirements | false |

## Examples

```
/sdlc:prd ingest docs/feature-spec.md    # Import PRD
/sdlc:prd draft                          # Generate requirements
/sdlc:prd review                         # Interactive review
/sdlc:prd list                           # Show all PRDs
```

## Notes

- PRDs can be in any markdown format; the parser is flexible
- Cross-referencing requires artifacts to exist (run `/sdlc:scan` first)
- Multiple PRDs can be in inbox; specify which to draft with `--prd`
