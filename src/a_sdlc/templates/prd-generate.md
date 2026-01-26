# /sdlc:prd-generate "<description>"

## Purpose

Create a Product Requirements Document interactively from a brief description, using existing project artifacts for context and asking clarifying questions to guide PRD creation.

## Arguments

- **description**: Brief statement of the proposed change or feature (e.g., "Add OAuth authentication", "Migrate to PostgreSQL", "Change default model from GPT-5 to GPT-4")

## Execution Steps

### 1. Parse User Description

- Extract key entities and change type
- Identify potential affected areas

### 2. Load Project Artifacts

- Read `.sdlc/artifacts/architecture.md` (understand components)
- Read `.sdlc/artifacts/data-model.md` (understand data dependencies)
- Read `.sdlc/artifacts/key-workflows.md` (understand user flows)
- Read `.sdlc/artifacts/codebase-summary.md` (understand tech stack)

### 3. Analyze Context

- Map description entities to components in architecture.md
- Identify data model impacts from data-model.md
- Find affected workflows in key-workflows.md
- Determine technical constraints from codebase-summary.md

### 4. Ask Clarifying Questions (Interactive)

**Problem Context:**
- "What problem does this solve?"
- "Why is this change needed now?"
- "What's the impact if we don't make this change?"

**Scope Questions (artifact-driven):**
- "This affects [X components from architecture.md]. Should we change all or specific ones?"
- "This impacts [Y workflows from key-workflows.md]. Which are in scope?"
- "Will this require changes to [Z entities from data-model.md]?"

**Requirements Discovery:**
- "What are the quantitative goals?" (cost reduction %, latency targets, uptime requirements)
- "What quality standards must be met?"
- "Is backward compatibility required?"
- "What's the target timeline?"

**Acceptance Criteria:**
- "How will success be measured?"
- "What tests will validate this change?"
- "What's the rollback plan?"

**Boundaries:**
- "What's explicitly out of scope for this PRD?"
- "What dependencies must be resolved first?"

### 5. Generate PRD Document

Create `.sdlc/prds/{slug}.md` with structure:

```markdown
# {Title from description}

**Version**: 1.0.0
**Status**: Draft
**Author**: {from git config}
**Created**: {timestamp}

## Overview
{Synthesized from description and answers}

## Problem Statement
{From problem context questions}

## Goals
{Derived from requirements discovery}

## Affected Components
{Cross-referenced from architecture.md}
- Component A: {impact description}
- Component B: {impact description}

## Data Model Changes
{Cross-referenced from data-model.md}
- Entity X: {changes needed}

## Functional Requirements
- FR-001: {requirement from answers}
- FR-002: {requirement from answers}
[Generated from question responses]

## Non-Functional Requirements
- NFR-001: {requirement from answers}
- NFR-002: {requirement from answers}
[Performance, cost, reliability from quantitative goals]

## User Stories
{Generated from affected workflows}
- As a {user type}, I want {capability}, so that {benefit}

## Acceptance Criteria
- AC-001: {criterion from answers}
- AC-002: {criterion from answers}
[From validation questions]

## Out of Scope
{From boundaries questions}

## Open Questions
{Unresolved items from interactive session}

## References
- Architecture: .sdlc/artifacts/architecture.md
- Data Model: .sdlc/artifacts/data-model.md
- Workflows: .sdlc/artifacts/key-workflows.md
```

### 6. Update Metadata

Add entry to `.sdlc/prds/.metadata.json`:
```json
{
  "id": "{slug}",
  "title": "{title}",
  "version": "1.0.0",
  "created_at": "{timestamp}",
  "updated_at": "{timestamp}",
  "external_id": null,
  "external_url": null
}
```

### 7. Display Summary

```
✅ PRD created: .sdlc/prds/{slug}.md

📊 Summary:
- X functional requirements
- Y non-functional requirements
- Z acceptance criteria
- N affected components (from architecture.md)
- M workflow impacts (from key-workflows.md)

🔗 Next steps:
- List all PRDs: /sdlc:prd-list
- View PRD: a-sdlc prd show {slug}
- Push to Confluence: a-sdlc prd push {slug}.md
```

## Example Session

**Input:**
```
/sdlc:prd-generate "Change default model from GPT-5 to GPT-4"
```

**Claude's Response:**
```
📂 Loading project artifacts...
   ✓ architecture.md (3 components found)
   ✓ data-model.md (2 entities found)
   ✓ key-workflows.md (1 workflow found)

🔍 Analysis:
   This change likely affects:
   - inference-service (from architecture.md)
   - api-gateway (from architecture.md)
   - model-config (from architecture.md)
   - llm-workflow (from key-workflows.md)

❓ Let me ask some clarifying questions:

1. What problem does this solve?
   > Reduce operational costs while maintaining acceptable quality

2. Why change from GPT-5 to GPT-4 specifically?
   > GPT-5 pricing is 3x GPT-4, quality difference minimal for our use case

3. Should this affect all 3 components (inference-service, api-gateway, model-config)?
   > Yes, update all to use GPT-4-turbo as default

4. Will llm-workflow need updates?
   > No changes to workflow logic, just model reference

5. Target cost reduction percentage?
   > 65% cost reduction

6. Acceptable latency increase?
   > Max 15% slower than GPT-5 baseline

7. Backward compatibility needed?
   > Yes, API should accept model parameter for overrides

8. How will success be measured?
   > Cost metrics dashboard + latency monitoring

9. What's out of scope?
   > Model fine-tuning, prompt optimization

✅ PRD created: .sdlc/prds/model-downgrade-gpt4.md

📊 Summary:
   - 4 functional requirements
   - 4 non-functional requirements
   - 3 acceptance criteria
   - 3 affected components (from architecture.md)
   - 1 workflow reference (from key-workflows.md)

🔗 Next: /sdlc:prd-list
```

## Notes

- Questions adapt based on available artifacts
- If artifacts missing, ask more detailed questions
- Cross-references enhance PRD quality and traceability
- Generated PRD is a draft - you can edit the file directly in `.sdlc/prds/`
