# /sdlc:update - Incremental Artifact Updates

Detect changes since last scan and update only affected artifacts, optimizing for speed and efficiency.

## Prerequisites

- `.sdlc/` directory must exist
- Initial scan must have been run (`/sdlc:scan`)
- `.sdlc/.cache/checksums.json` must exist

## Change Detection Strategy

### Primary Method: Git Diff

If the project is a git repository:

```bash
git diff --name-only HEAD~1
```

Or for unstaged changes:

```bash
git diff --name-only
git diff --name-only --cached
```

### Fallback Method: Checksum Comparison

If git is unavailable, compare current file checksums against `.sdlc/.cache/checksums.json`.

## Artifact-to-File Trigger Matrix

| Changed File Pattern | Triggers Update To |
|---------------------|-------------------|
| Any file/dir add/delete | `directory-structure.md` |
| `package.json`, `pyproject.toml`, `README*`, `docker*` | `codebase-summary.md` |
| `src/**/*.py` (new modules), `*agent*.py`, `*service*.py` | `architecture.md` |
| `*schema*.py`, `*model*.py`, `state.py`, `types.py` | `data-model.md` |
| `graph.py`, `*agent*.py`, `*handler*.py`, `*workflow*.py` | `key-workflows.md` |

## Execution Steps

### Phase 1: Detect Changes

#### 1.1 Get Changed Files

```python
# Try git first
changed_files = git_diff_files()

# Fallback to checksum comparison
if not changed_files:
    changed_files = compare_checksums()
```

#### 1.2 Categorize Changes

Map changed files to affected artifacts:

```python
affected_artifacts = set()

for file in changed_files:
    if is_new_or_deleted(file):
        affected_artifacts.add("directory-structure")

    if matches_config_patterns(file):
        affected_artifacts.add("codebase-summary")

    if matches_architecture_patterns(file):
        affected_artifacts.add("architecture")

    if matches_model_patterns(file):
        affected_artifacts.add("data-model")

    if matches_workflow_patterns(file):
        affected_artifacts.add("key-workflows")
```

### Phase 2: Selective Regeneration

For each affected artifact, run the corresponding generation logic from `/sdlc:scan`.

#### 2.1 Directory Structure Update

If `directory-structure` is affected:
- Re-run `list_dir` with recursive=true
- Regenerate the tree structure
- Update summary counts

#### 2.2 Codebase Summary Update

If `codebase-summary` is affected:
- Re-read package files (pyproject.toml, package.json)
- Re-read README files
- Re-read Docker configurations
- Regenerate technology stack section

#### 2.3 Architecture Update

If `architecture` is affected:
- Identify new/modified components
- Re-run `get_symbols_overview` for affected files
- Update component breakdowns
- Preserve unchanged component documentation

#### 2.4 Data Model Update

If `data-model` is affected:
- Re-scan for model definitions in changed files
- Update entity documentation
- Preserve unchanged entity documentation

#### 2.5 Key Workflows Update

If `key-workflows` is affected:
- Re-trace affected workflows
- Update sequence flows
- Preserve unchanged workflow documentation

### Phase 3: Cache Update

#### 3.1 Update Checksums

Regenerate checksums for all artifacts:

```json
{
  "generated_at": "2025-01-21T14:00:00Z",
  "last_scan": "2025-01-21T12:00:00Z",
  "artifacts": {
    "directory-structure": "sha256:...",
    "codebase-summary": "sha256:...",
    "architecture": "sha256:...",
    "data-model": "sha256:...",
    "key-workflows": "sha256:..."
  },
  "source_files": {
    "src/module.py": "sha256:...",
    ...
  }
}
```

#### 3.2 Record Update History

Append to `.sdlc/.cache/update_history.json`:

```json
{
  "updates": [
    {
      "timestamp": "2025-01-21T14:00:00Z",
      "changed_files": ["src/new_module.py"],
      "artifacts_updated": ["architecture", "directory-structure"],
      "duration_ms": 1234
    }
  ]
}
```

### Phase 4: Output

Print update summary:

```
Update Complete!

Changes detected:
  - src/new_module.py (added)
  - src/models/user.py (modified)

Artifacts updated:
  ✓ directory-structure.md
  ✓ architecture.md
  ✓ data-model.md

Artifacts unchanged:
  ○ codebase-summary.md
  ○ key-workflows.md

Duration: 1.2s
```

## Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--all` | Force update all artifacts | false |
| `--dry-run` | Show what would be updated without changing | false |
| `--since <commit>` | Check changes since specific commit | HEAD~1 |

## Examples

```
/sdlc:update                    # Incremental update
/sdlc:update --all              # Force update all
/sdlc:update --dry-run          # Preview changes
/sdlc:update --since abc123     # Changes since commit
```

## Notes

- Much faster than full scan for small changes
- Use `--all` if artifacts seem out of sync
- Consider running after merging feature branches
