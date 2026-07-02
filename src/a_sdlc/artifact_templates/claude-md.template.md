# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## Project Overview

{{PROJECT_OVERVIEW}}

## Development Commands

{{DEVELOPMENT_COMMANDS}}

## a-sdlc Integration
<!-- a-sdlc:managed -->

This project uses a-sdlc for SDLC management.

**Session start — establish project context:** project context is per MCP
session (per conversation), not global; a server restart clears it. At the
start of a session, or whenever an a-sdlc tool returns a message beginning
"No project context":
1. Read `.sdlc/project.json` at this repository's root.
2. If it exists, call `switch_project(project_id=<the "id" field>)` — this binds
   the project to THIS conversation only.
3. If it does not exist, run `/sdlc:init` (local server) or call
   `create_project(name=...)` and write the returned `init_files` (remote server).

**Before starting work, read these files:**
- `.sdlc/lesson-learn.md` — Project-specific lessons and rules
- `~/.a-sdlc/lesson-learn.md` — Global cross-project lessons
- `.sdlc/artifacts/` — Generated codebase documentation (if available)

<!-- grounding-read-snippet:start -->
**Reading scan artifacts:** scan artifacts live in `.sdlc/artifacts/` and are transitioning from Markdown to HTML. For each artifact name (`architecture`, `codebase-summary`, `data-model`, `directory-structure`, `key-workflows`):

1. Prefer `.sdlc/artifacts/{name}.html` when it exists — the documentation content is inside the `<main>` element; ignore the surrounding chrome (`<head>`, `<style>`, `<nav>`, footer).
2. Fall back to `.sdlc/artifacts/{name}.md` when no `.html` file exists (pre-migration repository).
3. If neither file exists, the artifact has not been generated — proceed without it (optionally suggest running `/sdlc:scan`).

`code-quality.md` and `requirements.md` are always Markdown — read them directly with no extension fallback.
<!-- grounding-read-snippet:end -->

**During work:**
- Log corrections to `.sdlc/corrections.log` when fixing mistakes
- Update lesson-learn files when patterns emerge
- Use `/sdlc:help` for available commands
