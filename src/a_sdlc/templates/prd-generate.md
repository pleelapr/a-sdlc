# /sdlc:prd-generate "<description>"

## Purpose

Create a Product Requirements Document interactively from a brief description. Uses clarifying questions to build comprehensive requirements.

## Arguments

- **description**: Brief statement of the proposed change or feature (e.g., "Add OAuth authentication", "Migrate to PostgreSQL")

## Execution Steps

### 1. Parse User Description

- Extract key entities and change type
- Identify potential affected areas
- Determine scope of the change

### 2. Ask Clarifying Questions (Interactive)

**Problem Context:**
- "What problem does this solve?"
- "Why is this change needed now?"
- "What's the impact if we don't make this change?"

**Scope Questions:**
- "What components will be affected?"
- "Which user workflows are impacted?"
- "Will this require data model changes?"

**Requirements Discovery:**
- "What are the quantitative goals?" (cost reduction %, latency targets, uptime)
- "What quality standards must be met?"
- "Is backward compatibility required?"
- "What's the target timeline?"

**Acceptance Criteria:**
- "How will success be measured?"
- "What tests will validate this change?"
- "What's the rollback plan?"

**Boundaries:**
- "What's explicitly out of scope?"
- "What dependencies must be resolved first?"

### 3. Generate PRD Content

Build markdown content with structure:

```markdown
# {Title from description}

**Status**: draft
**Created**: {timestamp}

## Overview
{Synthesized from description and answers}

## Problem Statement
{From problem context questions}

## Goals
{Derived from requirements discovery}

## Affected Components
{From scope questions}
- Component A: {impact description}
- Component B: {impact description}

## Functional Requirements
- FR-001: {requirement from answers}
- FR-002: {requirement from answers}

## Non-Functional Requirements
- NFR-001: {requirement from answers}
- NFR-002: {requirement from answers}

## User Stories
- As a {user type}, I want {capability}, so that {benefit}

## Acceptance Criteria
- AC-001: {criterion from answers}
- AC-002: {criterion from answers}

## Out of Scope
{From boundaries questions}

## Open Questions
{Unresolved items from interactive session}
```

### 4. Save PRD to Database

```
mcp__asdlc__create_prd(
    prd_id="<slug>",
    title="<title>",
    content="<markdown_content>"
)
```

The slug is generated from the title (lowercase, hyphens).

Returns:
```json
{
  "status": "created",
  "message": "PRD created: feature-auth",
  "prd": {
    "id": "feature-auth",
    "title": "User Authentication System",
    "status": "draft",
    "sprint_id": null,
    "created_at": "2025-01-26T12:00:00Z"
  }
}
```

### 5. Display Summary

```
✅ PRD created: feature-auth

📊 Summary:
- 4 functional requirements
- 3 non-functional requirements
- 3 acceptance criteria
- 2 affected components

🔗 Next steps:
- View PRD: /sdlc:prd-list
- Mark ready: /sdlc:prd-update "feature-auth" --status ready
- Split into tasks: /sdlc:prd-split "feature-auth"
```

## Example Session

**Input:**
```
/sdlc:prd-generate "Change default model from GPT-5 to GPT-4"
```

**Claude's Response:**
```
📝 Creating PRD for: Change default model from GPT-5 to GPT-4

❓ Let me ask some clarifying questions:

1. What problem does this solve?
   > Reduce operational costs while maintaining acceptable quality

2. Why change from GPT-5 to GPT-4 specifically?
   > GPT-5 pricing is 3x GPT-4, quality difference minimal for our use case

3. What components will be affected?
   > inference-service, api-gateway, model-config

4. Target cost reduction percentage?
   > 65% cost reduction

5. Acceptable latency increase?
   > Max 15% slower than GPT-5 baseline

6. Backward compatibility needed?
   > Yes, API should accept model parameter for overrides

7. How will success be measured?
   > Cost metrics dashboard + latency monitoring

8. What's out of scope?
   > Model fine-tuning, prompt optimization

✅ PRD created: model-downgrade-gpt4

📊 Summary:
- 4 functional requirements
- 4 non-functional requirements
- 3 acceptance criteria
- 3 affected components

🔗 Next steps:
- View: /sdlc:prd-list
- Split: /sdlc:prd-split "model-downgrade-gpt4"
```

## MCP Tools Used

| Tool | Purpose |
|------|---------|
| `mcp__asdlc__create_prd` | Save new PRD to database |
| `mcp__asdlc__list_prds` | Check for duplicate IDs |

## PRD Status Flow

```
draft (initial) → ready (approved) → split (tasks created) → completed (done)
```

New PRDs are created with status `draft`. Use `/sdlc:prd-update` to change status.

## Notes

- PRD ID (slug) is auto-generated from title
- All PRDs start in `draft` status
- Questions adapt based on the type of change
- Generated PRD can be edited with `/sdlc:prd-update`
- PRDs can optionally be assigned to a sprint after creation
