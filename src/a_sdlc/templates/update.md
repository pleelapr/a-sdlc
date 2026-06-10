# /sdlc:update - Incremental Artifact Updates

Detect changes since last scan and update only affected artifacts, optimizing for speed and efficiency.

## Prerequisites

- `.sdlc/` directory must exist
- Initial scan must have been run (`/sdlc:scan`) — artifacts exist as `.html` files
- `.sdlc/.cache/checksums.json` must exist

## Change Detection Strategy

Change detection decides **WHAT to regenerate** — it never changes HOW regeneration happens (see the whole-file regeneration rule below).

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

If git is unavailable, compare current file checksums against `.sdlc/.cache/checksums.json` (artifact entries are keyed on the `.html` filenames).

## Artifact-to-File Trigger Matrix

| Changed File Pattern | Triggers Update To |
|---------------------|-------------------|
| Any file/dir add/delete | `directory-structure.html` |
| `package.json`, `pyproject.toml`, `README*`, `docker*` | `codebase-summary.html` |
| `src/**/*.py` (new modules), `*agent*.py`, `*service*.py` | `architecture.html` |
| `*schema*.py`, `*model*.py`, `state.py`, `types.py` | `data-model.html` |
| `graph.py`, `*agent*.py`, `*handler*.py`, `*workflow*.py` | `key-workflows.html` |

## Whole-File Regeneration Rule (MANDATORY)

Changed artifacts are ALWAYS rewritten as a complete file — **NEVER patch-edit HTML**.

- Section-level change detection is allowed (and encouraged) to decide which artifacts need regeneration and to focus the re-analysis on the affected sections.
- Once an artifact is selected for update, regenerate the entire `<main>` content and write the whole `.html` file in one pass, exactly as `/sdlc:scan` Phase 4 does (section pattern, TOC, diagram vocabulary, allowlist).
- Do NOT use string/regex edits, partial `Edit` operations, or in-place surgical patches on existing HTML files. Patch-edits drift from the structure contract and break the validation gate.
- Unchanged artifacts are left completely untouched.

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

You may additionally inspect the existing artifact's sections to narrow WHICH content needs re-analysis (section-level detection) — but the write in Phase 2 is always whole-file.

### Phase 2: Selective Regeneration

For each affected artifact, re-run the corresponding analysis from `/sdlc:scan` (Phase 2) and regenerate the artifact **whole-file** following `/sdlc:scan` Phase 4 (fill `<main>` + flat TOC; section pattern `<section id><details open><summary><h2>`; diagram vocabulary; no forbidden content). When rewriting an existing artifact whole-file, keep the existing chrome (`<head>`, `<style>` block, nav strip, footer) unchanged — only the `<main>` content and the TOC list change.

#### 2.1 Directory Structure Update

If `directory-structure` is affected:
- Re-run `list_dir` with recursive=true
- Regenerate the tree and summary counts
- Rewrite `directory-structure.html` in full

#### 2.2 Codebase Summary Update

If `codebase-summary` is affected:
- Re-read package files (pyproject.toml, package.json), README, Docker configurations
- Rewrite `codebase-summary.html` in full (carry forward still-accurate analysis, but emit the complete file)

#### 2.3 Architecture Update

If `architecture` is affected:
- Identify new/modified components; re-run `get_symbols_overview` for affected files
- Rewrite `architecture.html` in full — unchanged component documentation is re-emitted as part of the new file, never patch-merged

#### 2.4 Data Model Update

If `data-model` is affected:
- Re-scan for model definitions in changed files
- Rewrite `data-model.html` in full

#### 2.5 Key Workflows Update

If `key-workflows` is affected:
- Re-trace affected workflows
- Rewrite `key-workflows.html` in full

### Phase 3: Validate (blocking gate)

After regenerating the affected artifacts, run the validator — same gate as `/sdlc:scan` Phase 5:

```bash
a-sdlc artifacts validate
```

- Exit `0`: proceed to Phase 4.
- Exit `1`: fix the reported errors by rewriting the offending files whole-file, log each failed attempt via `log_correction(category="documentation", ...)`, and re-validate (max 2 retries). The update is NOT complete until `.sdlc/.cache/validation.json` reports `"passed": true`.
- Exit `2`: I/O or usage error — fix and re-run.

### Phase 4: Cache Update

#### 4.1 Update Checksums

Regenerate checksums for all artifacts, keyed on the `.html` filenames:

```json
{
  "generated_at": "2026-06-09T14:00:00Z",
  "last_scan": "2026-06-09T12:00:00Z",
  "artifacts": {
    "directory-structure.html": "sha256:...",
    "codebase-summary.html": "sha256:...",
    "architecture.html": "sha256:...",
    "data-model.html": "sha256:...",
    "key-workflows.html": "sha256:...",
    "index.html": "sha256:..."
  },
  "source_files": {
    "src/module.py": "sha256:...",
    ...
  }
}
```

#### 4.2 Record Update History

Append to `.sdlc/.cache/update_history.json`:

```json
{
  "updates": [
    {
      "timestamp": "2026-06-09T14:00:00Z",
      "changed_files": ["src/new_module.py"],
      "artifacts_updated": ["architecture", "directory-structure"],
      "duration_ms": 1234
    }
  ]
}
```

### Phase 5: Output

Print update summary:

```
Update Complete!

Changes detected:
  - src/new_module.py (added)
  - src/models/user.py (modified)

Artifacts updated (whole-file regeneration):
  ✓ directory-structure.html
  ✓ architecture.html
  ✓ data-model.html

Artifacts unchanged:
  ○ codebase-summary.html
  ○ key-workflows.html

Validation: PASS (.sdlc/.cache/validation.json)
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
- If artifacts still exist only as `.md` files (pre-migration), run a full `/sdlc:scan` instead — `/sdlc:update` operates on the `.html` artifacts
