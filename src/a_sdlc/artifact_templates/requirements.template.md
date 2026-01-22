# {{FEATURE_NAME}}

## Overview

{{OVERVIEW}}

## Problem Statement

{{PROBLEM_STATEMENT}}

## Requirements

### Functional Requirements

{{#FUNCTIONAL_REQUIREMENTS}}
#### {{ID}}: {{TITLE}}

**Priority:** {{PRIORITY}}
**Component:** {{COMPONENT}}
**Description:** {{DESCRIPTION}}
**Rationale:** {{RATIONALE}}

{{/FUNCTIONAL_REQUIREMENTS}}

### Non-Functional Requirements

{{#NONFUNCTIONAL_REQUIREMENTS}}
#### {{ID}}: {{TITLE}}

**Category:** {{CATEGORY}}
**Description:** {{DESCRIPTION}}
**Metric:** {{METRIC}}

{{/NONFUNCTIONAL_REQUIREMENTS}}

## Technical Analysis

### Affected Components

{{#AFFECTED_COMPONENTS}}
- **{{NAME}}** - {{IMPACT}}
{{/AFFECTED_COMPONENTS}}

### Data Model Changes

{{#DATA_MODEL_CHANGES}}
- **{{ENTITY}}** - {{CHANGE}}
{{/DATA_MODEL_CHANGES}}

### Workflow Impacts

{{#WORKFLOW_IMPACTS}}
- **{{WORKFLOW}}** - {{INTEGRATION}}
{{/WORKFLOW_IMPACTS}}

## Open Questions

{{#OPEN_QUESTIONS}}
{{NUMBER}}. {{QUESTION}}
{{/OPEN_QUESTIONS}}

## Out of Scope

{{#OUT_OF_SCOPE}}
- {{ITEM}}
{{/OUT_OF_SCOPE}}

## Acceptance Criteria

{{#ACCEPTANCE_CRITERIA}}
### {{ID}}: {{SCENARIO_NAME}}

**Given** {{GIVEN}}
**When** {{WHEN}}
**Then** {{THEN}}

{{/ACCEPTANCE_CRITERIA}}

---

*Generated from PRD: {{PRD_SOURCE}}*
*Generated on: {{GENERATED_AT}}*
