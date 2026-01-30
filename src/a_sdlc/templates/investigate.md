# /sdlc:investigate

## Purpose

Discover existing codebase patterns and prepare context for high-quality task generation.
Ensures tasks follow project conventions AND coding best practices.

---

## Usage

```
/sdlc:investigate <prd_id> [options]
```

**Arguments:**
- `prd_id` - ID of PRD to investigate context for

**Options:**
- `--depth <level>` - Analysis depth: quick, thorough (default: thorough)
- `--save` - Save investigation report to `.sdlc/investigation/`

## Examples

```
/sdlc:investigate PROJ-P0001
/sdlc:investigate PROJ-P0001 --depth quick
/sdlc:investigate PROJ-P0001 --save
```

---

## Execution Steps

### Phase 1: Project Pattern Discovery

Analyze the existing codebase to understand its conventions:

**1. Coding Style & Conventions**

Search for patterns in the codebase:

```
# Naming conventions
- Look for consistent casing: camelCase, snake_case, PascalCase
- Function naming patterns: getUser, fetch_user, retrieveUser
- File naming: user.service.ts, UserService.ts, user_service.py

# Documentation style
- Comment patterns: JSDoc, docstrings, inline comments
- README structure and conventions
```

**2. Architecture Patterns**

Use artifacts if available, otherwise analyze directly:

```
# Read architecture context
- .sdlc/artifacts/architecture.md (if exists)
- .sdlc/artifacts/directory-structure.md (if exists)

# Identify patterns
- Layer separation (controllers, services, repositories)
- Dependency injection approach
- Configuration management
- Error handling patterns
```

**3. Testing Patterns**

```
# Find test files
- Location: tests/, __tests__/, *.test.ts, *_test.py
- Framework: Jest, pytest, Mocha, etc.
- Patterns: mocks, fixtures, factories

# Coverage expectations
- Look for coverage config in package.json, pytest.ini, etc.
```

**4. Existing Utilities & Abstractions**

```
# Search for reusable code
- Common utilities: src/utils/, lib/, helpers/
- Base classes: BaseService, AbstractController
- Shared validation: validators/, schemas/
- Error handling: errors/, exceptions/
```

### Phase 2: Best Practices Assessment

Evaluate how well the codebase follows best practices:

**Code Quality Principles**

| Principle | What to Look For | Assessment |
|-----------|------------------|------------|
| **DRY** | Duplicate code patterns, copy-pasted logic | Note violations for task guidance |
| **SOLID** | Large classes, mixed responsibilities | Identify refactoring opportunities |
| **KISS** | Over-engineered solutions, unnecessary abstraction | Note for simplification |
| **YAGNI** | Unused features, speculative code | Identify dead code |

**Code Organization**

- Separation of concerns: Are layers properly isolated?
- Module boundaries: Clear interfaces between modules?
- Cohesion: Are related functions grouped together?
- Coupling: Are modules loosely coupled?

**Security Practices**

- Input validation patterns in place?
- Authentication/authorization approach?
- Secret management (env vars, vaults)?
- Data sanitization patterns?

**Performance Patterns**

- Caching strategies used?
- Database query patterns (N+1 issues)?
- Async/await usage?
- Resource management (connections, files)?

### Phase 3: PRD-Specific Analysis

For the given PRD, identify:

**1. Affected Components**
```
Based on PRD requirements:
- Which existing components will be modified?
- What new components need to be created?
- What integration points exist?
```

**2. Existing Code to Leverage**
```
Search for:
- Similar functionality already implemented
- Utilities that can be reused
- Patterns to follow for consistency
- Base classes to extend
```

**3. Potential Anti-Patterns to Avoid**
```
Based on codebase analysis:
- Common mistakes in this area
- Patterns that lead to bugs
- Over-engineering tendencies
```

---

## Investigation Report Format

Generate a markdown report with the following structure:

```markdown
# Investigation Report: [PRD Title]

**PRD ID:** [prd_id]
**Date:** [timestamp]
**Depth:** [quick|thorough]

---

## Project Conventions (Follow These)

| Aspect | Observed Pattern | Example |
|--------|------------------|---------|
| Naming | [convention] | `getUserById`, `user_service.py` |
| File Structure | [pattern] | `src/services/`, `tests/unit/` |
| Error Handling | [pattern] | `throw new AppError()`, try/except |
| Testing | [pattern] | `*.test.ts`, pytest fixtures |
| Config | [pattern] | `.env`, `config/` module |
| Logging | [pattern] | `logger.info()`, structured logs |

---

## Existing Code to Leverage

| Functionality | Location | Reuse Strategy |
|---------------|----------|----------------|
| [utility] | `path/file` | Import and use directly |
| [base class] | `path/file` | Extend for new functionality |
| [pattern] | `path/file` | Follow same approach |
| [validation] | `path/file` | Reuse validation logic |

---

## Architecture Context

### Affected Components

Based on PRD requirements, these components are affected:

| Component | Impact | Notes |
|-----------|--------|-------|
| [component] | [modify/extend/create] | [details] |

### Integration Points

| Integration | Type | Consideration |
|-------------|------|---------------|
| [service] | [API/event/direct] | [notes] |

---

## Best Practices Checklist for This PRD

### Must Follow (Project Conventions)

- [ ] Use [naming convention] for new code
- [ ] Place files in [correct directories]
- [ ] Follow [error handling pattern]
- [ ] Write tests in [testing style]
- [ ] Use [logging pattern] for observability
- [ ] Follow [config pattern] for settings

### Must Follow (Universal Best Practices)

- [ ] No code duplication - extract shared logic
- [ ] Single responsibility per function/class
- [ ] Meaningful names that reveal intent
- [ ] Keep functions small and focused (< 20 lines typical)
- [ ] Handle errors appropriately at boundaries
- [ ] Validate inputs at system boundaries
- [ ] Write tests for new functionality
- [ ] Document complex logic with comments explaining WHY

---

## Anti-Patterns to Avoid

Based on codebase analysis and this PRD's scope:

| Anti-Pattern | Why to Avoid | Alternative |
|--------------|--------------|-------------|
| [pattern] | [reason] | [better approach] |

### Common Mistakes in This Area

- [Specific anti-pattern relevant to PRD domain]
- [Another specific anti-pattern]
- [Over-engineering warning]

---

## Recommended Task Structure

Based on investigation, tasks should:

1. **Start with:** [foundational work first]
2. **Follow dependency order:** [suggested flow]
3. **Include quality gates:** [specific checks for this PRD]
4. **Avoid scope creep:** [what to explicitly exclude]
```

---

## Output Options

**Default:** Display report in conversation

**With `--save`:** Save to `.sdlc/investigation/<prd_id>.md`
- Creates `.sdlc/investigation/` directory if needed
- Report can be referenced by `/sdlc:prd-split`

---

## MCP Tools Used

- `mcp__asdlc__get_context()` - Get project info
- `mcp__asdlc__get_prd(prd_id)` - Read PRD content
- `Read` - Read source files and artifacts
- `Grep` - Search for patterns
- `Glob` - Find files by pattern

---

## Integration with prd-split

When `/sdlc:prd-split` is executed:

1. Check for `.sdlc/investigation/<prd_id>.md`
2. If exists, load and apply:
   - Project conventions → Task "Patterns to Follow" section
   - Existing code → Task "Existing Code to Leverage" section
   - Anti-patterns → Task "Anti-Patterns to Avoid" section
   - Quality checklist → Task "Best Practices Checklist" section
3. If missing, perform inline discovery (abbreviated)

---

## Quick Investigation (--depth quick)

When time is limited, perform abbreviated analysis:

1. Read artifacts only (no deep codebase search)
2. Identify naming conventions from 2-3 sample files
3. Find test directory location
4. List obvious utilities
5. Generate abbreviated report

**Use quick depth for:**
- Simple PRDs with limited scope
- Well-documented codebases with good artifacts
- When artifacts are fresh and comprehensive

**Use thorough depth for:**
- Complex PRDs spanning multiple components
- Unfamiliar codebases
- When artifacts are stale or missing

---

## Example Output

```markdown
# Investigation Report: OAuth Authentication

**PRD ID:** AUTH-P0001
**Date:** 2025-01-28
**Depth:** thorough

---

## Project Conventions (Follow These)

| Aspect | Observed Pattern | Example |
|--------|------------------|---------|
| Naming | camelCase functions, PascalCase classes | `getUserById`, `AuthService` |
| File Structure | Feature folders under `src/` | `src/auth/`, `src/users/` |
| Error Handling | Custom AppError class | `throw new AppError('NOT_FOUND', 404)` |
| Testing | Jest with `*.test.ts` | `auth.service.test.ts` |
| Config | Environment via `config/` module | `config.get('oauth.clientId')` |

---

## Existing Code to Leverage

| Functionality | Location | Reuse Strategy |
|---------------|----------|----------------|
| Config loader | `src/config/index.ts` | Use for OAuth config |
| Session manager | `src/auth/session.ts` | Extend for OAuth sessions |
| User model | `src/models/user.ts` | Add OAuth fields |
| HTTP client | `src/utils/http.ts` | Use for OAuth API calls |
| Validation | `src/utils/validators.ts` | Use for token validation |

---

## Best Practices Checklist for This PRD

### Must Follow (Project Conventions)

- [ ] Use camelCase for functions, PascalCase for classes
- [ ] Place OAuth files in `src/auth/oauth/`
- [ ] Use AppError for all error conditions
- [ ] Write Jest tests in `tests/auth/`
- [ ] Use config module for OAuth credentials

### Must Follow (Universal Best Practices)

- [ ] Single OAuth service class, not multiple utilities
- [ ] Extract token validation to reusable function
- [ ] Keep OAuth flow functions small and focused
- [ ] Validate all external OAuth responses
- [ ] Test happy path AND error scenarios
- [ ] Document OAuth state parameter security

---

## Anti-Patterns to Avoid

| Anti-Pattern | Why to Avoid | Alternative |
|--------------|--------------|-------------|
| Hardcoded OAuth URLs | Breaks in different environments | Use config module |
| Silent token failures | Security risk, hard to debug | Log and throw AppError |
| Mixed session logic | Violates SRP | Separate OAuth from session |

### Common Mistakes in OAuth

- Storing tokens in plain cookies (use httpOnly, secure)
- Not validating state parameter (CSRF risk)
- Catching all errors silently (masks issues)
- Creating multiple HTTP clients (use shared util)
```

---

## Notes

1. **Run before prd-split:** Best results when investigation is done before splitting
2. **Saves time overall:** Upfront investigation prevents rework
3. **Promotes consistency:** Ensures new code follows established patterns
4. **Catches issues early:** Identifies anti-patterns before they're coded
