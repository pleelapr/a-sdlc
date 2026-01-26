# SDLC Artifact Publishing

Publish SDLC artifacts to external documentation systems (Confluence).

## Usage

```
/sdlc:publish                    # Publish all artifacts
/sdlc:publish architecture       # Publish specific artifact
/sdlc:publish --force            # Force republish all
/sdlc:publish --status           # Show publish status
```

## Prerequisites

1. **Configure Confluence Plugin**:
   ```bash
   a-sdlc plugins enable confluence
   a-sdlc plugins configure confluence
   ```

2. **Generate Artifacts First**:
   Run `/sdlc:scan` to generate artifacts before publishing.

## Workflow

### Check Publish Status

First, check what artifacts exist and their publish status:

1. Read `.sdlc/artifacts/` directory to find all artifacts
2. Check `.sdlc/artifacts/.metadata.json` for external links
3. Report status for each artifact:
   - 🟢 Published (has external_url)
   - 🟡 Stale (local changes since last publish)
   - 🔴 Not published (no external_id)

### Publish Artifacts

For each artifact to publish:

1. Read the markdown content from `.sdlc/artifacts/{artifact}.md`
2. Use the Confluence plugin to create/update the page
3. Update `.sdlc/artifacts/.metadata.json` with:
   - `external_id`: Confluence page ID
   - `external_url`: Full URL to the page
   - `updated_at`: Timestamp of publish

### Artifact Types

| Artifact | Confluence Page Title |
|----------|----------------------|
| `codebase-summary.md` | [SDLC] Codebase Summary |
| `architecture.md` | [SDLC] Architecture |
| `data-model.md` | [SDLC] Data Model |
| `key-workflows.md` | [SDLC] Key Workflows |
| `directory-structure.md` | [SDLC] Directory Structure |
| `requirements.md` | [SDLC] Requirements |

## Configuration

### Project Config (`.sdlc/config.yaml`)

```yaml
plugins:
  artifacts:
    provider: confluence
    confluence:
      space_key: PROJ
      parent_page_id: "123456789"  # Optional
      page_title_prefix: "[SDLC]"
```

### User Config (`~/.config/a-sdlc/config.yaml`)

```yaml
atlassian:
  email: "user@company.com"
  api_token: "${ATLASSIAN_API_TOKEN}"
  base_url: "https://company.atlassian.net"

plugins:
  artifacts:
    provider: confluence
    confluence:
      space_key: PROJ
```

## Output Format

After publishing, report:

```
## Publish Summary

Published 5 artifacts to Confluence:

| Artifact | Status | URL |
|----------|--------|-----|
| codebase-summary | ✅ Created | https://company.atlassian.net/wiki/... |
| architecture | ✅ Updated | https://company.atlassian.net/wiki/... |
| data-model | ✅ Created | https://company.atlassian.net/wiki/... |
| key-workflows | ❌ Failed | Error: Permission denied |
| requirements | ⏭️ Skipped | No changes |

Space: PROJ
Parent Page: SDLC Documentation
```

## Error Handling

If publishing fails:
1. Report which artifacts failed and why
2. Successfully published artifacts are still recorded
3. Suggest running with `--force` to retry failed items
4. Check credentials: `a-sdlc plugins configure confluence`

## Manual Fallback

If Confluence API is not available, provide manual instructions:

```markdown
## Manual Publishing Required

Could not connect to Confluence. Create pages manually:

### 1. Codebase Summary
- Space: PROJ
- Title: [SDLC] Codebase Summary
- Content: Copy from `.sdlc/artifacts/codebase-summary.md`

[Continue for each artifact...]
```
