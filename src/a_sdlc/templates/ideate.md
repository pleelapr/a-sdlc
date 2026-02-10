# /sdlc:ideate "<initial thought>"

## Purpose

Exploratory Socratic dialogue that helps you go from a vague idea to one or more well-defined PRDs. Designed for users who don't yet know exactly what they want to build.

## Arguments

- **initial thought**: A rough idea, question, or aspiration (e.g., "I want to make the app faster", "Maybe we need better auth", "Thinking about adding a dashboard")

## CRITICAL: Scope Boundaries

**This skill creates PRD documents through guided exploration. It does NOT implement features.**

- **NEVER** proceed to task creation or splitting automatically
- **NEVER** write source code or make code changes
- **NEVER** use TaskCreate, TodoWrite, or Edit tools
- **NEVER** call `mcp__asdlc__create_task()` or split PRD
- **ALWAYS** stop after PRD creation and wait for user's next command

**RIGHT**: Explore idea → Converge on themes → Create PRD(s) → STOP
**WRONG**: Explore idea → Create PRDs → Split into tasks → Start implementing

## Ideate vs PRD-Generate

| Aspect | `/sdlc:ideate` | `/sdlc:prd-generate` |
|--------|----------------|----------------------|
| Starting point | Vague idea, aspiration | Clear feature description |
| Conversation style | Divergent → convergent | Structured Q&A checklist |
| Output | One or more PRDs | Exactly one PRD |
| Questions per turn | 2–3, conversational | Full checklist |
| Duration | Multi-turn exploration | Single focused session |
| Best for | "I'm not sure what I need" | "I know what I want to build" |

## Conversational Phases

Phases are **advisory, not rigid**. The user can skip ahead ("enough exploring, let's create PRDs") or revisit earlier phases at any time. Follow the user's energy.

### Phase 0: Load Context

**Automated — run before the first conversational turn.**

```
context = mcp__asdlc__get_context()
```

**If no project exists** (context indicates no active project):
- Inform the user: "No a-sdlc project found. Let me initialize one first."
- Run inline initialization: `mcp__asdlc__init_project()` (follow `/sdlc:init` shortname flow)
- Continue to Phase 1 after successful init

**If project exists**, gather grounding context:
- Check `context.artifacts.scan_status`:
  - If `"complete"` or `"partial"`: Read `.sdlc/artifacts/codebase-summary.md` and `.sdlc/artifacts/architecture.md` for grounding
  - If `"not_scanned"`: Note this — questions will be more open-ended without codebase context
- Check existing PRDs: `mcp__asdlc__list_prds()` — avoid duplicating existing work

**Then acknowledge the user's initial thought and transition to Phase 1.**

### Phase 1: Understand the Vision

**Goal**: Explore the user's aspirations openly. Understand *why* they're thinking about this.

**Style**: Divergent — encourage broad thinking.

Ask 2–3 questions like:
- "What would success look like if this were done perfectly?"
- "What triggered this idea? Was there a specific frustration or opportunity?"
- "Who benefits most from this change?"
- "If you had a magic wand, what would be different about your system tomorrow?"

**Do NOT** jump to solutions. Stay in the problem/aspiration space.

### Phase 2: Map the Problem Space

**Goal**: Identify users, problems, and constraints concretely.

**Style**: Structured exploration — ground the vision in specifics.

Explore dimensions like:
- **Users**: "Who are the distinct user types that interact with this? What are their workflows?"
- **Problems**: "What's broken, slow, or missing today? What workarounds exist?"
- **Constraints**: "What can't change? Budget, timeline, tech stack, team size?"
- **Dependencies**: "What else is in flight that could affect or be affected by this?"

If codebase artifacts are available, reference real components:
- "I see you have a `UserService` and `AuthMiddleware` — is the friction you're describing in the login flow or session management?"

### Phase 3: Explore Solution Approaches

**Goal**: Surface trade-offs and alternatives the user may not have considered.

**Style**: Present options — "Here's approach A vs B, which resonates?"

Techniques:
- Present 2–3 distinct approaches with trade-offs
- "We could tackle this incrementally (ship X first, then Y) or as a single big change. What feels right?"
- "There's a quick-win version and a thorough version — want to explore both?"
- Identify what could be phased vs what must ship together

**Keep a mental "parking lot"** of ideas that come up but don't fit the current focus. These will be captured in the final summary.

### Phase 4: Identify Boundaries

**Goal**: Help the user say "no" — define what's in scope and what's deferred.

**Style**: Convergent — narrow down to actionable boundaries.

Questions like:
- "Of everything we've discussed, what's the absolute must-have for a first version?"
- "What can we explicitly defer to a future iteration?"
- "Are there any hard constraints — things that are non-negotiable?"
- "What's the minimum viable version that would still be valuable?"

### Phase 5: Converge on PRD Themes

**Goal**: Group the explored ideas into logical PRD-sized units.

**Style**: Propose a grouping, iterate until the user agrees.

Present a proposed grouping:

```
Based on our discussion, I see [N] distinct PRDs:

1. **[Theme A title]** — [one-sentence scope summary]
2. **[Theme B title]** — [one-sentence scope summary]

Parking lot (deferred ideas):
- [Idea X] — deferred because [reason]
- [Idea Y] — could be a future PRD

Does this grouping make sense? Want to merge, split, or re-scope any of these?
```

Iterate until the user approves the grouping. It's OK if the result is a single PRD — not every ideation produces multiple.

### Phase 6: Draft and Create PRDs

**Goal**: Generate PRD content and persist each one, reviewed individually.

For **each** approved PRD theme:

1. **Generate content** using this structure:

```markdown
# {Title}

**Status**: draft
**Created**: {timestamp}
**Origin**: Ideation session

## Overview
{Synthesized from exploration — what this PRD covers and why}

## Problem Statement
{From Phase 1–2 insights}

## Goals
{Concrete, measurable where possible}

## Affected Components
{From codebase context if available, otherwise from discussion}

## Functional Requirements
- FR-001: {requirement}
- FR-002: {requirement}

## Non-Functional Requirements
- NFR-001: {requirement}

## User Stories
- As a {user type}, I want {capability}, so that {benefit}

## Acceptance Criteria
- AC-001: {criterion}

## Out of Scope
{Explicit boundaries from Phase 4}

## Open Questions
{Unresolved items from the exploration}
```

2. **Present to user for review**:

```
📝 PRD 1 of [N]: "[Title]"

[Display generated content]

Options:
1. ✅ Save — Create this PRD
2. ✏️ Edit — Revise before saving
3. ⏭️ Skip — Don't create this one
```

**Wait for explicit approval before saving each PRD.**

3. **Save approved PRDs**:

```
mcp__asdlc__create_prd(
    title="<title>",
    content="<markdown_content>"
)
```

### Final Summary

After all PRDs are processed, display:

```
✅ Ideation Complete

📋 PRDs Created:
- {PRD-ID}: {Title} (draft)
- {PRD-ID}: {Title} (draft)

🅿️ Parking Lot (deferred ideas):
- {Idea} — {reason deferred}

🔗 Next steps:
- Review PRDs: /sdlc:prd-list
- Refine a PRD: /sdlc:prd-update "{prd-id}"
- Split into tasks: /sdlc:prd-split "{prd-id}"
- Investigate feasibility: /sdlc:prd-investigate "{prd-id}"
```

## ⛔ STOP HERE

**Do NOT proceed further.** The ideation workflow is complete.

The user must explicitly run one of these commands to continue:
- `/sdlc:prd-update` — To refine a PRD
- `/sdlc:prd-split` — To create tasks from a PRD
- `/sdlc:prd-investigate` — To validate a PRD against the codebase

**Wait for user's next instruction.**

## Conversation Guidelines

- **Ask 2–3 questions per turn**, not a checklist of 10. Keep it conversational.
- **Summarize what you've heard** before moving to the next phase. "So far I'm hearing X, Y, and Z — does that capture it?"
- **Follow the user's energy**. If they want to dive deep on one aspect, go with it. If they want to skip ahead, let them.
- **Use codebase context** to make questions concrete when artifacts are available.
- **Name the phase transitions** so the user knows where they are: "Now that we have a clear picture of the problem, let's explore some approaches..."
- **Don't force phases**. A simple idea might go straight from Phase 1 to Phase 5. A complex idea might loop between Phases 2–4 multiple times.

## MCP Tools Used

| Tool | Purpose |
|------|---------|
| `mcp__asdlc__get_context` | Load project context and artifact status |
| `mcp__asdlc__init_project` | Initialize project if none exists |
| `mcp__asdlc__list_prds` | Check existing PRDs to avoid duplication |
| `mcp__asdlc__create_prd` | Save finalized PRDs |

## Example Session

**Input:**
```
/sdlc:ideate "thinking about making the app faster"
```

**Claude's Response (Phase 0+1):**
```
📍 Project: my-app (MYAP) — codebase scan available

I see you're thinking about performance. Before we dive into solutions,
let me understand the landscape:

1. What's prompting this? Are users complaining, or is this proactive?
2. Where do you feel the slowness most — page loads, API responses,
   data processing, or something else?
3. What would "fast enough" look like? Any specific targets?
```

**After several turns of exploration, Phase 5:**
```
Based on our discussion, I see 2 distinct PRDs:

1. **API Response Time Optimization** — Reduce P95 latency from 800ms
   to 200ms by adding caching and optimizing DB queries
2. **Frontend Bundle Optimization** — Cut initial load time by 60%
   through code splitting and lazy loading

Parking lot (for later):
- CDN migration — good idea but depends on infra team availability
- Real-time dashboard — separate initiative, not a performance fix

Does this grouping work? Want to adjust anything?
```

**Phase 6 — reviewing PRDs one by one, creating on approval.**

## Notes

- Ideation naturally precedes `/sdlc:prd-generate` — use ideate when the user doesn't yet know what to build
- Each ideation session may produce 0–N PRDs (zero is fine if the user decides to think more)
- The "parking lot" ensures no ideas are lost, just deferred
- All PRDs start in `draft` status
- Works with or without a prior `/sdlc:scan` — questions adapt accordingly
