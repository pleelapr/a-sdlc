# Lessons Learned

Rules and patterns discovered during development. Claude Code reads this file at the start of every session and follows these lessons during all work.

**Priority Levels:**
- **MUST** — Always follow. Never skip without explicit user override
- **SHOULD** — Follow by default. Skip only with justification
- **MAY** — Consider when relevant. Skip freely if not applicable

## Testing

<!-- Lessons about test coverage, test quality, edge cases -->

- **[SHOULD]** Use dynamic references (imports or constants) instead of hardcoded values in test assertions for schema versions, config paths, and other values that increment or change across releases.
  - *Source:* Retrospective (5 corrections)
  - *Example:* Hardcoded schema version assertion `== 5` broke when SCHEMA_VERSION bumped to 6 (task:SDLC-T00041)
  - *Added:* 2026-03-05

- **[SHOULD]** When refactoring storage or state mechanisms (e.g., JSON to DB), update all mock targets in tests within the same task to prevent cascading test failures in downstream tasks.
  - *Source:* Retrospective (3 corrections)
  - *Example:* Removed TestWorktreeStateHelpers and replaced file-based assertions with DB mock assertions after JSON-to-DB migration (task:SDLC-T00044)
  - *Added:* 2026-03-06

## Code Quality

<!-- Lessons about code style, duplication, naming, patterns -->

- **[SHOULD]** Verify cleanup/teardown functions handle all degraded states: missing directory on disk, orphan records without DB entry, and partial completion. Add explicit existence checks before destructive operations.
  - *Source:* Retrospective (4 corrections)
  - *Example:* Added orphan worktree cleanup when directory exists on disk but has no DB record, plus conditional existence check before git worktree remove (task:SDLC-T00045)
  - *Added:* 2026-03-06

## Task Completeness

<!-- Lessons about missing requirements, incomplete implementations -->

## Integration

<!-- Lessons about component wiring, API contracts, cross-module issues -->

## Documentation

<!-- Lessons about missing docs, unclear comments, outdated references -->
