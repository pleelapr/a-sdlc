# SDLC Artifact Publishing

Publish SDLC artifacts to external documentation systems (Confluence).

## Usage

```
/sdlc:publish                    # Publish all publishable (Markdown) artifacts
/sdlc:publish requirements       # Publish specific artifact
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

## HTML Scan Artifacts Are Skipped

The five scan artifacts (`codebase-summary`, `architecture`, `data-model`, `key-workflows`, `directory-structure`) are generated as **HTML** files (`*.html`). Confluence publishing for HTML artifacts is **deferred until the follow-up PRD** — they are skipped by publish, and the CLI push guard reports:

```
scan artifacts are HTML — Confluence publish for HTML is deferred (see follow-up PRD)
```

Only the Markdown artifacts still publish to Confluence:

- `code-quality.md`
- `requirements.md`

Do not attempt to convert the HTML artifacts to Confluence pages manually or via the plugin — report them as skipped.

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

For each **Markdown** artifact to publish (HTML scan artifacts are skipped — see above):

1. Read the markdown content from `.sdlc/artifacts/{artifact}.md`
2. Use the Confluence plugin to create/update the page
3. Update `.sdlc/artifacts/.metadata.json` with:
   - `external_id`: Confluence page ID
   - `external_url`: Full URL to the page
   - `updated_at`: Timestamp of publish

### Artifact Types

| Artifact | Format | Publish Behavior |
|----------|--------|------------------|
| `codebase-summary.html` | HTML | ⏭️ Skipped (deferred until follow-up PRD) |
| `architecture.html` | HTML | ⏭️ Skipped (deferred until follow-up PRD) |
| `data-model.html` | HTML | ⏭️ Skipped (deferred until follow-up PRD) |
| `key-workflows.html` | HTML | ⏭️ Skipped (deferred until follow-up PRD) |
| `directory-structure.html` | HTML | ⏭️ Skipped (deferred until follow-up PRD) |
| `code-quality.md` | Markdown | ✅ Publishes as "[SDLC] Code Quality" |
| `requirements.md` | Markdown | ✅ Publishes as "[SDLC] Requirements" |

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

scan artifacts are HTML — Confluence publish for HTML is deferred (see follow-up PRD)

Published 2 artifacts to Confluence:

| Artifact | Status | URL |
|----------|--------|-----|
| code-quality | ✅ Created | https://company.atlassian.net/wiki/... |
| requirements | ✅ Updated | https://company.atlassian.net/wiki/... |
| codebase-summary | ⏭️ Skipped | HTML (deferred) |
| architecture | ⏭️ Skipped | HTML (deferred) |
| data-model | ⏭️ Skipped | HTML (deferred) |
| key-workflows | ⏭️ Skipped | HTML (deferred) |
| directory-structure | ⏭️ Skipped | HTML (deferred) |

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

If Confluence API is not available, provide manual instructions (Markdown artifacts only — HTML scan artifacts stay local):

```markdown
## Manual Publishing Required

Could not connect to Confluence. Create pages manually:

### 1. Requirements
- Space: PROJ
- Title: [SDLC] Requirements
- Content: Copy from `.sdlc/artifacts/requirements.md`

### 2. Code Quality
- Space: PROJ
- Title: [SDLC] Code Quality
- Content: Copy from `.sdlc/artifacts/code-quality.md`
```
