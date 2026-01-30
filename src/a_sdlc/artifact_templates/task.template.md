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

### Existing Code to Leverage

{{#EXISTING_CODE}}
- `{{PATH}}`: {{USAGE}}
{{/EXISTING_CODE}}
{{^EXISTING_CODE}}
> Before implementation, search for and document:
> - Utilities that provide similar functionality
> - Base classes or patterns to extend
> - Existing validation/error handling to reuse
{{/EXISTING_CODE}}

### Project Patterns to Follow

{{#PROJECT_PATTERNS}}
- **{{ASPECT}}:** {{PATTERN}}
{{/PROJECT_PATTERNS}}
{{^PROJECT_PATTERNS}}
> Document from investigation:
> - Naming convention: [convention]
> - File organization: [pattern]
> - Error handling: [pattern]
> - Testing: [pattern]
{{/PROJECT_PATTERNS}}

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

## Best Practices Checklist

**Before Coding:**
- [ ] Identified existing code to leverage
- [ ] Understand project patterns to follow
- [ ] Know where new code belongs

**During Coding:**
- [ ] Following naming conventions
- [ ] No code duplication (extracted shared logic)
- [ ] Each function has single responsibility
- [ ] Names reveal intent
- [ ] Functions are small and focused
- [ ] Error handling follows project patterns

**After Coding:**
- [ ] Linting passes
- [ ] Tests written and passing
- [ ] Code follows project patterns
- [ ] No over-engineering

## Anti-Patterns to Avoid

{{#ANTI_PATTERNS}}
- **{{PATTERN}}:** {{ALTERNATIVE}}
{{/ANTI_PATTERNS}}
{{^ANTI_PATTERNS}}
- Do not duplicate existing functionality - search first
- Do not over-engineer for hypothetical futures
- Do not ignore error handling
- Do not skip testing
- Do not bypass established patterns
{{/ANTI_PATTERNS}}

## Code Placement

{{#CODE_PLACEMENT}}
| Change | Location | Reason |
|--------|----------|--------|
{{#PLACEMENTS}}
| {{ITEM}} | `{{LOCATION}}` | {{REASON}} |
{{/PLACEMENTS}}
{{/CODE_PLACEMENT}}
{{^CODE_PLACEMENT}}
> Verify file locations against project structure before creating new files.
{{/CODE_PLACEMENT}}

## Success Criteria

{{#SUCCESS_CRITERIA}}
- [ ] {{CRITERION}}
{{/SUCCESS_CRITERIA}}

### Quality Gates (Required Before Completion)

**Code Quality:**
- [ ] All linting checks pass (`lint`, `typecheck` if applicable)
- [ ] No code duplication introduced
- [ ] Follows project naming conventions
- [ ] Functions are small and focused

**Testing:**
- [ ] Unit tests for new functionality
- [ ] Edge cases covered
- [ ] Tests follow project testing patterns
- [ ] All tests pass

**Integration:**
- [ ] Code placed in correct location
- [ ] Uses existing utilities where available
- [ ] Follows error handling patterns
- [ ] Follows logging patterns (if applicable)

**Review:**
- [ ] Code is simple and readable
- [ ] No over-engineering
- [ ] Meets acceptance criteria from PRD

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
