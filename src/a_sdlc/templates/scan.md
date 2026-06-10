# /sdlc:scan - Full Repository Scan

Perform a comprehensive scan of the codebase and generate the five living documentation artifacts as HTML pages (plus `index.html`) using the scaffold → fill → validate workflow.

## Prerequisites

- `.sdlc/` directory must exist (run `/sdlc:init` first)
- Serena MCP should be available for symbol analysis
- `a-sdlc` CLI available on PATH (provides `artifacts scaffold` / `artifacts validate`)

## Output Contract

The scan produces six HTML files in `.sdlc/artifacts/`:

```
.sdlc/artifacts/
├── index.html                  # Landing page (chrome, links to the 5 artifacts)
├── codebase-summary.html
├── architecture.html
├── data-model.html
├── key-workflows.html
└── directory-structure.html
```

`code-quality.md` and `requirements.md` are NOT scan artifacts — they remain markdown and are never created, modified, or deleted by this workflow.

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

### Phase 3: Scaffold

Run the scaffold command to write the six HTML skeleton files:

```bash
a-sdlc artifacts scaffold
```

- Exit code `0`: skeletons written to `.sdlc/artifacts/` — proceed.
- Exit code `2`: usage or I/O error — fix the reported problem and re-run before continuing.

The skeletons contain ALL page chrome: `<head>`, the inlined `<style>` block, the `<nav aria-label="Artifacts">` strip, the `<h1>`, an empty `<nav aria-label="Contents">` TOC, an empty `<main>` slot, and the footer. **Never regenerate or hand-edit the chrome.** Use `--dir` / `--project-name` only when the defaults (`.sdlc/artifacts`, repository directory name) are wrong.

### Phase 4: Fill `<main>` (per artifact)

`index.html` is generated complete by the scaffold (links and `aria-current` are pre-filled) and needs no agent edits. For each of the five artifact pages, the agent fills ONLY two slots:

1. The `<main>` element body (replace the `AGENT SLOT` comment)
2. One flat TOC entry per section inside `<nav aria-label="Contents"><ul>`

Everything else in the file stays byte-for-byte as scaffolded.

#### 4.1 Section Pattern

Every top-level block inside `<main>` follows this exact pattern:

```html
<section id="kebab-id">
  <details open>
    <summary><h2>Title</h2></summary>
    <p>Section content…</p>
  </details>
</section>
```

Rules:
- Top-level `<section>` elements carry a unique kebab-case `id`
- Top-level `<details>` MUST carry the `open` attribute
- `<summary>` MUST contain the section's `<h2>` heading
- Sub-headings inside a section are plain `<h3>` / `<h4>` — **no nested `<details>`**
- For each section, add one flat TOC entry: `<li><a href="#kebab-id">Title</a></li>` (the TOC list must stay flat — no nested `<ul>`)

#### 4.2 Required Sections (manifest)

Each page must contain at least these `<section id>` values (the validator enforces them):

| File | Required section ids |
|------|----------------------|
| `codebase-summary.html` | `overview`, `key-concepts`, `technology-stack` |
| `architecture.html` | `component-overview`, `data-flow` |
| `data-model.html` | `entities` |
| `key-workflows.html` | `workflows` |
| `directory-structure.html` | `repository-structure` |
| `index.html` | `artifacts` |

#### 4.3 Allowed Markup Inside `<main>`

Tags: `section`, `details`, `summary`, `h2`–`h4`, `p`, `ul`, `ol`, `li`, `table`, `thead`, `tbody`, `tr`, `th`, `td`, `pre`, `code`, `strong`, `em`, `a`, `figure`, `figcaption`, `div`, `span`, `br`, `hr`.

Attributes: `id`, `class`, `href`, `open`, `scope`, `colspan`, `rowspan`. `href` values must be `#fragment` or relative `*.html` links.

**Explicitly forbidden — the validator rejects the file:**
- `<script>` elements, raw `<script` sequences, and `javascript:`/`data:` URIs
- Event handler attributes (`onclick`, `onload`, any `on*`)
- `<svg>`, `<img>`, `<iframe>`, `<object>`, `<embed>`, `<video>`, `<audio>`, `<link>`, `<form>`
- Inline `style` attributes (all styling comes from the scaffolded `<style>` block)

Escape literal text: `&` → `&amp;`, `<` → `&lt;` (including inside `<pre>`/`<code>`). No `TODO` or `lorem` placeholder text — sections must carry real content.

#### 4.4 Composable Diagram Vocabulary

Diagrams are built from a fixed CSS class vocabulary (defined in `a_sdlc/artifacts/validator.py` `DIAGRAM_CLASSES`): `diagram`, `row`, `box`, `arrow`, `down`, `group`, `group-label`, `fallback`. The validator rejects any other class inside `<main>`. Compose them with `div`/`span` inside a `<figure class="diagram">`.

**Recipe — horizontal flow (`.row` flex row of `.box` nodes with `.arrow` glyphs):**

```html
<figure class="diagram">
  <div class="row">
    <div class="box">CLI</div>
    <div class="arrow">&#8594;</div>
    <div class="box">MCP Server</div>
    <div class="arrow">&#8594;</div>
    <div class="box">Database</div>
  </div>
  <figcaption>Request flow</figcaption>
</figure>
```

**Recipe — vertical flow (`.arrow.down` full-width downward glyph between rows):**

```html
<figure class="diagram">
  <div class="row"><div class="box">HTTP Request</div></div>
  <div class="arrow down">&#8595;</div>
  <div class="row"><div class="box">Router</div></div>
  <div class="arrow down">&#8595;</div>
  <div class="row"><div class="box">Handler</div></div>
  <figcaption>Request lifecycle</figcaption>
</figure>
```

**Recipe — grouped components (`.group` bordered container with a `.group-label`; ONE nesting level only — never nest a `.group` inside a `.group`):**

```html
<figure class="diagram">
  <div class="row">
    <div class="group">
      <span class="group-label">Storage</span>
      <div class="box">PostgreSQL</div>
      <div class="box">MinIO</div>
    </div>
    <div class="arrow">&#8594;</div>
    <div class="box">API Layer</div>
  </div>
  <figcaption>Storage architecture</figcaption>
</figure>
```

**Escape hatch — ASCII art in `<pre>` (optional `.fallback` class):** when a structure does not fit the box/row vocabulary (deep trees, wide sequence diagrams), use a plain `<pre>` block — optionally marked `class="fallback"` inside a diagram figure — with `&amp;`/`&lt;` escaping applied:

```html
<figure class="diagram">
  <pre class="fallback">
src/
├── cli.py
└── server/
    └── __init__.py
  </pre>
  <figcaption>Directory tree</figcaption>
</figure>
```

Never attempt SVG, image, canvas, or script-driven diagrams — they are rejected by the validator (see 4.3).

#### 4.5 Artifact Content Guides

- **`directory-structure.html`** (`repository-structure`): formatted tree (a `<pre>` tree is appropriate) + file count summary, from Phase 1.2
- **`codebase-summary.html`** (`overview`, `key-concepts`, `technology-stack`): purpose & domain, terminology, persistence, dependencies, configuration/deployment, stack
- **`architecture.html`** (`component-overview`, `data-flow`): per-component responsibility, key exports, state, interactions; diagrams from the vocabulary above
- **`data-model.html`** (`entities`): per-entity purpose, attributes (tables work well), relationships
- **`key-workflows.html`** (`workflows`): per-workflow components, relevance, sequence flow
- **`index.html`** (`artifacts`): pre-filled by the scaffold — do not edit (the validator still checks it)

### Phase 5: Validate (blocking gate)

Run the validator:

```bash
a-sdlc artifacts validate
```

Exit codes: `0` all files passed, `1` validation errors, `2` usage/I-O error. Every run writes evidence to `.sdlc/.cache/validation.json`.

**Retry loop (max 2 retries):**

1. Run `a-sdlc artifacts validate`.
2. If exit code `0`: gate passed — proceed to Phase 6.
3. If exit code `1`: read the error list (stdout or `.sdlc/.cache/validation.json` `results[].errors`), fix the offending files by rewriting their `<main>` content, and log the failure:
   ```
   log_correction(
     context_type="ad-hoc", context_id="none",
     category="documentation",
     description="scan validate attempt <N> failed: <summary of errors>"
   )
   ```
   Then re-run the validator. Log one correction per failed attempt.
4. After 2 retries (3 validation runs total) without a pass: **STOP.** Report the remaining errors to the user. The scan is NOT complete; do not proceed to Phase 6, do not delete any markdown, and do not update checksums.

**Completion requires `"passed": true` in `.sdlc/.cache/validation.json`.** There is no override.

### Phase 6: Finalize

Only after the validation gate passes:

#### 6.1 Update Checksums

Write `.sdlc/.cache/checksums.json`, **keyed on the `.html` filenames**:

```json
{
  "generated_at": "2026-06-09T12:00:00Z",
  "artifacts": {
    "directory-structure.html": "sha256:...",
    "codebase-summary.html": "sha256:...",
    "architecture.html": "sha256:...",
    "data-model.html": "sha256:...",
    "key-workflows.html": "sha256:...",
    "index.html": "sha256:..."
  }
}
```

#### 6.2 Delete Stale Markdown Artifacts

Remove the legacy `.md` versions that have been replaced by `.html` files. This step is scoped to EXACTLY these five filenames — never delete anything else:

- `architecture.md`
- `codebase-summary.md`
- `data-model.md`
- `directory-structure.md`
- `key-workflows.md`

Rules (matching the `remove_stale_markdown()` helper in `a_sdlc/artifacts/local.py`):
- Delete a `.md` file only when its `.html` sibling exists in `.sdlc/artifacts/`
- `code-quality.md` and `requirements.md` are NEVER touched — they remain markdown by design
- Any other `.md` file in the directory is out of scope and must be left alone

#### 6.3 Print Summary

```
Scan Complete!

Generated Artifacts:
  ✓ index.html
  ✓ codebase-summary.html
  ✓ architecture.html
  ✓ data-model.html
  ✓ key-workflows.html
  ✓ directory-structure.html

Validation: PASS (.sdlc/.cache/validation.json)
Stale markdown removed: architecture.md, codebase-summary.md, ...

Components found: N
Data models found: M
Workflows traced: K

Location: .sdlc/artifacts/ (open index.html in a browser)
```

## Reading Scan Artifacts (grounding)

Other workflows that read scan artifacts must use the following canonical lookup. This block is the single source of truth — templates that ground themselves on artifacts copy it verbatim.

<!-- grounding-read-snippet:start -->
**Reading scan artifacts:** scan artifacts live in `.sdlc/artifacts/` and are transitioning from Markdown to HTML. For each artifact name (`architecture`, `codebase-summary`, `data-model`, `directory-structure`, `key-workflows`):

1. Prefer `.sdlc/artifacts/{name}.html` when it exists — the documentation content is inside the `<main>` element; ignore the surrounding chrome (`<head>`, `<style>`, `<nav>`, footer).
2. Fall back to `.sdlc/artifacts/{name}.md` when no `.html` file exists (pre-migration repository).
3. If neither file exists, the artifact has not been generated — proceed without it (optionally suggest running `/sdlc:scan`).

`code-quality.md` and `requirements.md` are always Markdown — read them directly with no extension fallback.
<!-- grounding-read-snippet:end -->

## Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--force` | Regenerate even if no changes detected | false |
| `--verbose` | Show detailed progress | false |

To refresh a single artifact, use `/sdlc:update` instead — it regenerates affected artifacts whole-file without re-running `a-sdlc artifacts scaffold` (which overwrites all six skeletons).

## Examples

```
/sdlc:scan                           # Full scan
/sdlc:scan --force                   # Force regeneration
```

## Notes

- First scan may take longer as it builds the full cache
- Subsequent scans can use `/sdlc:update` for incremental updates
- Use `--verbose` to debug scanning issues
- `a-sdlc artifacts scaffold` is idempotent — re-running it overwrites the skeletons, so scaffold BEFORE filling, never after
- The validation gate is mandatory: a scan that does not end with a passing `.sdlc/.cache/validation.json` is incomplete
