# {{TASK_ID}}: {{TASK_TITLE}}

**Status:** {{STATUS}}
**Priority:** {{PRIORITY}}
**Requirement:** {{REQUIREMENT_ID}}
**Component:** {{COMPONENT}}
**Dependencies:** {{DEPENDENCIES}}
{{#PRD_REF}}**PRD Reference:** {{PRD_REF}}{{/PRD_REF}}

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

## Implementation Steps

{{#IMPLEMENTATION_STEPS}}
{{NUMBER}}. **{{STEP_TITLE}}**
   {{DESCRIPTION}}
   {{#CODE_HINT}}
   ```{{LANGUAGE}}
   {{CODE}}
   ```
   {{/CODE_HINT}}
   {{#TEST}}
   - **Test:** {{TEST_DESCRIPTION}}
   {{/TEST}}

{{/IMPLEMENTATION_STEPS}}

## Success Criteria

{{#SUCCESS_CRITERIA}}
- [ ] {{CRITERION}}
{{/SUCCESS_CRITERIA}}

## Scope Constraint

{{#SCOPE_CONSTRAINT}}
{{SCOPE_CONSTRAINT}}
{{/SCOPE_CONSTRAINT}}
{{^SCOPE_CONSTRAINT}}
Implement only the changes described above. Do not:
- Modify unrelated components
- Add features not in requirements
- Refactor existing code unless necessary
{{/SCOPE_CONSTRAINT}}

---

**Created:** {{CREATED_AT}}
**Updated:** {{UPDATED_AT}}
{{#COMPLETED_AT}}
**Completed:** {{COMPLETED_AT}}
{{/COMPLETED_AT}}
