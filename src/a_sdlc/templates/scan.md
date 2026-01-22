# /sdlc:scan - Full Repository Scan

Perform a comprehensive scan of the codebase and generate all five living documentation artifacts.

## Prerequisites

- `.sdlc/` directory must exist (run `/sdlc:init` first)
- Serena MCP should be available for symbol analysis

## Execution Steps

### Phase 1: Discovery

#### 1.1 Load Configuration

Read `.sdlc/config.yaml` to get:
- Project type (python, typescript, etc.)
- Include/exclude patterns
- Enabled artifacts

#### 1.2 Directory Scan

Use Serena's `list_dir` with recursive=true to map the entire codebase:

```
list_dir(relative_path=".", recursive=true, skip_ignored_files=true)
```

Store results in `.sdlc/.cache/directory_tree.json`

#### 1.3 Identify Key Files

Based on project type, identify:

**Python Projects:**
- `pyproject.toml`, `setup.py`, `requirements.txt`
- `Dockerfile`, `docker-compose.yml`
- `README.md`, `CHANGELOG.md`
- Files matching: `*schema*.py`, `*model*.py`, `*state*.py`
- Entry points: `main.py`, `app.py`, `cli.py`, `__main__.py`

**TypeScript/Node Projects:**
- `package.json`, `tsconfig.json`
- `Dockerfile`, `docker-compose.yml`
- Files matching: `*.schema.ts`, `*.model.ts`, `*.types.ts`
- Entry points: `index.ts`, `main.ts`, `app.ts`

### Phase 2: Analysis

#### 2.1 Get Symbols Overview

For each source file, use Serena's `get_symbols_overview`:

```
get_symbols_overview(relative_path="src/module.py", depth=1)
```

Collect:
- Classes and their methods
- Functions
- Type definitions
- Constants

#### 2.2 Analyze Dependencies

For key components, use `find_referencing_symbols` to map relationships:

```
find_referencing_symbols(name_path="ClassName", relative_path="src/module.py")
```

Build a dependency graph of components.

#### 2.3 Extract Data Models

Find all data model definitions:

**Python:**
- Pydantic BaseModel classes
- TypedDict definitions
- dataclass decorators

**TypeScript:**
- Interface definitions
- Type aliases
- Zod schemas

#### 2.4 Trace Workflows

Starting from entry points, follow call chains to identify key workflows:

1. Find entry point functions (main, app factory, CLI handlers)
2. Use `find_symbol` to get function bodies
3. Extract function calls and build sequence diagrams
4. Identify external service interactions

### Phase 3: Generation

Generate each artifact using the templates in `.sdlc/templates/`:

#### 3.1 Directory Structure (`directory-structure.md`)

**Input:** Directory tree from Phase 1.2
**Output:** Formatted tree with summary

```markdown
# Directory Structure

## Repository Structure

\`\`\`
src/
  module_a/
    __init__.py
    handlers.py
    models.py
  module_b/
    ...
tests/
  ...
\`\`\`

## Summary

- Total files: X
- Source files: Y
- Test files: Z
```

#### 3.2 Codebase Summary (`codebase-summary.md`)

**Input:** README, package files, config files, symbol overview
**Output:** Comprehensive project overview

Sections:
- Overall Purpose & Domain
- Key Concepts & Domain Terminology
- Data Persistence & State Management
- External Dependencies & APIs
- Configuration, Deployment & Environment
- Technology Stack

#### 3.3 Architecture (`architecture.md`)

**Input:** Symbol overview, dependency graph
**Output:** Component breakdown

For each major component:
- Primary Responsibility
- Key Functions/Methods/Exports
- Internal Structure
- State Management
- Key Imports & Interactions
- Data Handling

#### 3.4 Data Model (`data-model.md`)

**Input:** Extracted data models from Phase 2.3
**Output:** Entity documentation

For each entity:
- Purpose
- Key Attributes (with types and constraints)
- Relationships

Include:
- Entity breakdown
- Relationship diagram (if applicable)
- Additional entities summary

#### 3.5 Key Workflows (`key-workflows.md`)

**Input:** Traced workflows from Phase 2.4
**Output:** Workflow documentation

For each workflow:
- Main Components involved
- Relevance (why it matters)
- Sequence Flow (step by step)

### Phase 4: Validation

#### 4.1 Cross-Reference Check

Verify artifacts are consistent:
- All components in architecture exist in directory structure
- All data models mentioned in workflows exist in data-model
- All files referenced exist in the codebase

#### 4.2 Generate Checksums

Store artifact checksums in `.sdlc/.cache/checksums.json`:

```json
{
  "generated_at": "2025-01-21T12:00:00Z",
  "artifacts": {
    "directory-structure": "sha256:...",
    "codebase-summary": "sha256:...",
    "architecture": "sha256:...",
    "data-model": "sha256:...",
    "key-workflows": "sha256:..."
  }
}
```

### Phase 5: Output

Write all artifacts to `.sdlc/artifacts/`:

```
.sdlc/artifacts/
├── directory-structure.md
├── codebase-summary.md
├── architecture.md
├── data-model.md
└── key-workflows.md
```

Print summary:

```
Scan Complete!

Generated Artifacts:
  ✓ directory-structure.md (X lines)
  ✓ codebase-summary.md (Y lines)
  ✓ architecture.md (Z lines)
  ✓ data-model.md (W lines)
  ✓ key-workflows.md (V lines)

Components found: N
Data models found: M
Workflows traced: K

Location: .sdlc/artifacts/
```

## Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--artifact <name>` | Generate only specific artifact | all |
| `--force` | Regenerate even if no changes detected | false |
| `--verbose` | Show detailed progress | false |

## Examples

```
/sdlc:scan                           # Full scan
/sdlc:scan --artifact architecture   # Only architecture
/sdlc:scan --force                   # Force regeneration
```

## Notes

- First scan may take longer as it builds the full cache
- Subsequent scans can use `/sdlc:update` for incremental updates
- Use `--verbose` to debug scanning issues
