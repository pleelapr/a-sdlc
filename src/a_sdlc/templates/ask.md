# /sdlc:ask - Answer Questions About This Repository

## Purpose

Answer any question about the current repository — setup, running, environment, architecture, workflows, dependencies, configuration, and project state. This is a **read-only, general-purpose Q&A skill** that gathers context from multiple sources and delivers a focused answer.

**Key Difference from Other Commands:**

| Command | Purpose | Modifies Data |
|---------|---------|---------------|
| **`/sdlc:ask "<question>"`** | Answer any repo question | No (read-only) |
| `/sdlc:investigate "<problem>"` | Root cause analysis for bugs | No (read-only) |
| `/sdlc:status` | Show artifact freshness | No (read-only) |
| `/sdlc:scan` | Generate codebase artifacts | Yes (writes artifacts) |

---

## CRITICAL: Scope Boundaries

**This skill ONLY answers questions. It does NOT make changes.**

- **NEVER** modify source code, configuration, or project files
- **NEVER** create PRDs, tasks, or sprints
- **NEVER** use Edit, Write, or Bash tools to modify project files
- **NEVER** install dependencies or run build commands
- **ALWAYS** stop after delivering the answer and wait for user's next command

**RIGHT**: Gather context → Analyze → Answer → STOP
**WRONG**: Answer question → Start implementing changes

---

## Usage

```
/sdlc:ask "<question>" [options]
```

**Arguments:**
- `question` - Natural language question about the repository

**Options:**
- `--depth <quick|thorough>` - Quick skims artifacts and config only; thorough reads source files too (default: quick)
- `--web` - Enable web search for external docs (off by default; most repo questions are local)

## Examples

```
/sdlc:ask "how do I run this project?"
/sdlc:ask "what database does this use?"
/sdlc:ask "how is authentication implemented?"
/sdlc:ask "what are the environment variables I need?"
/sdlc:ask "what's the project structure?"
/sdlc:ask "how do I run tests?"
/sdlc:ask "what PRDs are in progress?"
/sdlc:ask "what tasks are blocked?"
/sdlc:ask "how does the sync system work?" --depth thorough
/sdlc:ask "what version of React does this use?" --web
```

---

## Execution Steps

### Phase 1: Parse Question & Classify

Analyze the question to determine which sources to consult:

| Question Type | Examples | Primary Sources |
|---------------|----------|-----------------|
| **Setup & Running** | "how to run", "how to install", "how to build" | Config files, README |
| **Architecture** | "how is X structured", "what pattern does Y use" | Artifacts, source code |
| **Dependencies** | "what version of X", "what libraries" | package.json, pyproject.toml, lock files |
| **Environment** | "what env vars", "how to configure" | .env.example, docker-compose, config files |
| **Workflows** | "how does X work", "what happens when" | Artifacts, source code |
| **Project State** | "what PRDs exist", "what tasks are blocked" | SDLC data via MCP tools |
| **External/Library** | "how does library X work", "API for Y" | Web search, Context7 |

---

### Phase 2: Gather Context (Priority Order)

Check sources in priority order. Stop early if the answer is found with sufficient confidence.

#### Source 1: SDLC Artifacts (always check first)

Read available artifacts from `.sdlc/artifacts/`:

```
Read: .sdlc/artifacts/architecture.md
Read: .sdlc/artifacts/codebase-summary.md
Read: .sdlc/artifacts/key-workflows.md
Read: .sdlc/artifacts/data-model.md
Read: .sdlc/artifacts/directory-structure.md
```

Only read artifacts relevant to the question type. For example:
- "how is auth structured?" → architecture.md, key-workflows.md
- "what's the project layout?" → directory-structure.md, codebase-summary.md
- "what database tables exist?" → data-model.md

#### Source 2: Project Config Files

Read configuration files relevant to the question:

```
Read: README.md
Read: CLAUDE.md
Read: package.json / pyproject.toml / Cargo.toml / go.mod
Read: Makefile / Justfile / Taskfile.yml
Read: docker-compose.yml / Dockerfile
Read: .env.example / .env.sample
Read: tsconfig.json / vite.config.* / webpack.config.*
```

Only read files that exist and are relevant to the question.

#### Source 3: SDLC Data (for project state questions)

Query MCP tools when the question is about project management state:

```
mcp__asdlc__get_context()           # Project info and statistics
mcp__asdlc__list_prds(status?)      # PRD listing
mcp__asdlc__list_tasks(status?)     # Task listing
mcp__asdlc__list_sprints()          # Sprint listing
mcp__asdlc__list_sync_mappings()    # External sync status
```

#### Source 4: Codebase (thorough depth only)

**Only when `--depth thorough` is specified.**

Search source files for implementation details:

```
Grep: Search for relevant patterns, function names, class names
Glob: Find files matching the question topic
Read: Examine relevant source code sections
```

#### Source 5: Web Search (opt-in only)

**Only when `--web` flag is specified.**

Search external documentation:

```
mcp__context7__resolve-library-id(library_name)
mcp__context7__query-docs(library_id, query)
WebSearch: "<library> <specific question>"
```

---

### Phase 3: Analyze & Synthesize

1. Combine findings from all consulted sources
2. Resolve any conflicts between sources (prefer source code over documentation if they disagree)
3. Identify the most direct, actionable answer

**Priority of Truth:**
1. Source code (what actually runs)
2. Configuration files (what's actually configured)
3. SDLC artifacts (generated analysis)
4. README/docs (may be outdated)
5. Web search (general, not project-specific)

---

### Phase 4: Deliver Answer

**Answer Format:**

```markdown
## Answer

{Direct, concise answer to the question}

{Code snippets, commands, or configuration examples as appropriate}

---

**Sources:** {List of files/artifacts consulted}

**Related commands:**
- {Suggest relevant `/sdlc:*` follow-ups if applicable}
```

**Formatting Guidelines:**
- Lead with the direct answer — no preamble
- Include runnable commands when the question is "how do I..."
- Include code snippets when the question is "how does X work"
- Include file paths with line references when pointing to implementations
- Keep the answer focused — don't dump everything found, only what's relevant

---

## ⛔ STOP HERE

**Do NOT proceed further.** The answer has been delivered.

- **NEVER** start implementing changes based on the answer
- **NEVER** create PRDs or tasks from the answer
- **NEVER** modify any files

**Wait for user's next instruction.**

---

## MCP Tools Used

| Tool | Purpose |
|------|---------|
| `mcp__asdlc__get_context()` | Project info and statistics |
| `mcp__asdlc__list_prds()` | PRD listing for state questions |
| `mcp__asdlc__list_tasks()` | Task listing for state questions |
| `mcp__asdlc__list_sprints()` | Sprint listing for state questions |
| `mcp__asdlc__list_sync_mappings()` | External sync status |
| `mcp__context7__resolve-library-id()` | Find library documentation (--web) |
| `mcp__context7__query-docs()` | Query official documentation (--web) |
| `WebSearch` | Online search (--web) |
| `Read` | Read artifacts, config files, source code |
| `Grep` | Pattern search in codebase (--depth thorough) |
| `Glob` | File discovery (--depth thorough) |

---

## Quick Mode (--depth quick)

Default behavior. Only consults:
1. SDLC artifacts (`.sdlc/artifacts/`)
2. Project config files (README, package.json, etc.)
3. SDLC data via MCP tools (if project state question)

**Use quick for:**
- "How do I run this?"
- "What's the project structure?"
- "What env vars do I need?"
- "What PRDs are in progress?"

## Thorough Mode (--depth thorough)

Additionally searches source code:
1. Everything in quick mode
2. Grep/Glob/Read source files for implementation details

**Use thorough for:**
- "How does the authentication middleware work?"
- "What happens when a user submits the form?"
- "How is the database connection pool managed?"

---

## Error Handling

**No Project Initialized:**
```
⚠️ No .sdlc/ artifacts found. Answers will be based on config files and source code only.

For better answers, run:
  /sdlc:init
  /sdlc:scan
```

**No Relevant Information Found:**
```
❓ Could not find a confident answer from local sources.

Suggestions:
- Try with --depth thorough to search source code
- Try with --web to search external documentation
- Try rephrasing the question with more specific terms
```

---

## Notes

1. **Start here when onboarding:** Use `/sdlc:ask` as the first command when joining a new project
2. **Non-destructive:** Only reads and analyzes, never modifies anything
3. **Builds on artifacts:** Better answers when `/sdlc:scan` has been run first
4. **Quick by default:** Use `--depth thorough` only when quick doesn't provide enough detail
5. **Web is opt-in:** Most repository questions are answerable locally
