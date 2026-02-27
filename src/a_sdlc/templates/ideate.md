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

## CRITICAL: Interaction Model — Use AskUserQuestion Tool

**ALL user-facing questions MUST use the `AskUserQuestion` tool** with structured multi-choice options. This provides a better UX than free-text questions.

### Rules

1. **Always use `AskUserQuestion`** when you need user input, verification, or clarification
2. **Provide 2–4 meaningful options** per question — the user can always select "Other" for custom input
3. **Group related questions** into a single `AskUserQuestion` call (up to 4 questions per call)
4. **Use `multiSelect: true`** when the user can pick more than one option (e.g., "Which areas feel slow?")
5. **Keep option labels concise** (1–5 words) and use descriptions for context
6. **Keep headers short** (max 12 chars) — they appear as chip/tag labels

### When to Use AskUserQuestion

| Situation | Use AskUserQuestion? | Example |
|-----------|---------------------|---------|
| Exploring user's motivation | Yes — offer common motivations as options | "What triggered this?" |
| Clarifying scope | Yes — offer scope levels as options | "How big should this be?" |
| Presenting solution approaches | Yes — each approach is an option | "Which approach resonates?" |
| Confirming PRD grouping | Yes — approve/merge/split/re-scope | "Does this grouping work?" |
| Reviewing a PRD draft | Yes — save/edit/skip options | "What to do with this PRD?" |
| Phase transition confirmation | Yes — continue/skip/go back | "Ready for next phase?" |

## CRITICAL: Anti-Fluff Rules

**Every PRD created from ideation must contain ONLY content the user explicitly discussed.**

- **MUST NOT** add features, scope, or requirements the user didn't mention during conversation
- **MUST NOT** hallucinate problem statements — only use problems the user described
- **MUST NOT** infer user pain points — ask if unclear
- **MUST NOT** expand PRD themes beyond what was discussed in Phases 1-5
- **MUST** trace every PRD requirement to a specific user answer from the conversation
- **MUST** ask for specifics rather than filling in blanks with assumptions

**If the user's idea is vague, ask for specifics — do NOT fill in the blanks yourself.**

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

**Use `AskUserQuestion`** to explore motivation and vision. Provide a brief context message before the tool call summarizing what you understand so far.

Example tool call:
```
AskUserQuestion({
  questions: [
    {
      question: "What triggered this idea?",
      header: "Motivation",
      options: [
        { label: "User complaints", description: "Users have reported issues or frustrations" },
        { label: "Proactive improvement", description: "No complaints yet, but you see an opportunity" },
        { label: "Technical debt", description: "Existing implementation is limiting progress" },
        { label: "New opportunity", description: "Market change, new tech, or business need" }
      ],
      multiSelect: false
    },
    {
      question: "What would success look like?",
      header: "Success",
      options: [
        { label: "Better UX", description: "Users have a smoother, faster experience" },
        { label: "Better DX", description: "Developers can work faster and with less friction" },
        { label: "Business metrics", description: "Measurable impact on revenue, engagement, or retention" },
        { label: "Risk reduction", description: "Fewer incidents, better security, or compliance" }
      ],
      multiSelect: true
    }
  ]
})
```

Adapt the options based on the user's initial thought and project context. The examples above are illustrative — tailor them to what makes sense for the specific idea.

**Additional question for reality grounding:**

```
AskUserQuestion([
  {
    question: "What evidence exists that this is a real problem or opportunity?",
    header: "Evidence",
    options: [
      { label: "User feedback", description: "Users/customers have reported this issue or requested this" },
      { label: "Metrics/data", description: "Logs, analytics, or metrics show the problem exists" },
      { label: "Competitor gap", description: "Competitors offer this and we don't" },
      { label: "Intuition", description: "Based on experience — no hard data yet" }
    ],
    multiSelect: true
  }
])
```

Use the evidence type to ground the PRD's Problem Statement. If "Intuition" only, note this in the PRD's Open Questions section.

**Do NOT** jump to solutions. Stay in the problem/aspiration space.

### Phase 2: Map the Problem Space

**Goal**: Identify users, problems, and constraints concretely.

**Style**: Structured exploration — ground the vision in specifics.

**Use `AskUserQuestion`** to map users, problems, and constraints. Reference real codebase components in option descriptions when artifacts are available.

Example tool call:
```
AskUserQuestion({
  questions: [
    {
      question: "Who are the primary users affected by this?",
      header: "Users",
      options: [
        { label: "End users", description: "External users of the product" },
        { label: "Developers", description: "Internal team working on the codebase" },
        { label: "Admins/Ops", description: "Operations team managing the system" },
        { label: "API consumers", description: "Third-party integrations or services" }
      ],
      multiSelect: true
    },
    {
      question: "What are the main constraints we should respect?",
      header: "Constraints",
      options: [
        { label: "Tech stack", description: "Must work within existing technology choices" },
        { label: "Timeline", description: "Tight deadline or phased delivery needed" },
        { label: "Team capacity", description: "Limited developer bandwidth" },
        { label: "Backward compat", description: "Cannot break existing behavior or APIs" }
      ],
      multiSelect: true
    }
  ]
})
```

Adapt options based on prior answers and codebase context. If artifacts are available, reference real components in the descriptions (e.g., "Friction in `UserService` login flow" instead of generic descriptions).

### Phase 3: Explore Solution Approaches

**Goal**: Surface trade-offs and alternatives the user may not have considered.

**Style**: Present options — "Here's approach A vs B, which resonates?"

**Use `AskUserQuestion`** to present distinct approaches with trade-offs. Provide a brief explanation of each approach before the tool call, then let the user pick.

Example tool call:
```
AskUserQuestion({
  questions: [
    {
      question: "Which approach resonates most for tackling this?",
      header: "Approach",
      options: [
        { label: "Incremental", description: "Ship quick wins first, iterate on larger changes over time" },
        { label: "Big bang", description: "Single comprehensive change — more effort upfront, cleaner result" },
        { label: "Parallel tracks", description: "Quick fix now + proper solution in parallel" }
      ],
      multiSelect: false
    },
    {
      question: "What's the right scope for the first version?",
      header: "Scope",
      options: [
        { label: "Minimal MVP", description: "Smallest valuable slice — validate the approach first" },
        { label: "Feature-complete", description: "Full solution for the core use case, skip edge cases" },
        { label: "Production-grade", description: "Complete with error handling, monitoring, and docs" }
      ],
      multiSelect: false
    }
  ]
})
```

Tailor the approaches to the specific idea being explored. Reference real trade-offs from the discussion.

**Keep a mental "parking lot"** of ideas that come up but don't fit the current focus. These will be captured in the final summary.

### Phase 4: Identify Boundaries

**Goal**: Help the user say "no" — define what's in scope and what's deferred.

**Style**: Convergent — narrow down to actionable boundaries.

**Use `AskUserQuestion`** to help the user define scope boundaries. List the concrete items discussed so far as options to include or defer.

Example tool call (adapt items from actual discussion):
```
AskUserQuestion({
  questions: [
    {
      question: "Which items are must-haves for the first version?",
      header: "Must-haves",
      options: [
        { label: "[Item A]", description: "Brief description of item A from discussion" },
        { label: "[Item B]", description: "Brief description of item B from discussion" },
        { label: "[Item C]", description: "Brief description of item C from discussion" },
        { label: "[Item D]", description: "Brief description of item D from discussion" }
      ],
      multiSelect: true
    },
    {
      question: "Are there non-negotiable constraints?",
      header: "Constraints",
      options: [
        { label: "No breaking changes", description: "Existing APIs and behavior must remain stable" },
        { label: "Performance budget", description: "Must not regress current performance metrics" },
        { label: "No new dependencies", description: "Work within existing tech stack" }
      ],
      multiSelect: true
    }
  ]
})
```

Items not selected as must-haves become candidates for the parking lot.

### Phase 5: Converge on PRD Themes

**Goal**: Group the explored ideas into logical PRD-sized units.

**Style**: Propose a grouping, iterate until the user agrees.

First, present the proposed grouping as a text summary:

```
Based on our discussion, I see [N] distinct PRDs:

1. **[Theme A title]** — [one-sentence scope summary]
2. **[Theme B title]** — [one-sentence scope summary]

Parking lot (deferred ideas):
- [Idea X] — deferred because [reason]
- [Idea Y] — could be a future PRD
```

Then **use `AskUserQuestion`** to get approval:

```
AskUserQuestion({
  questions: [
    {
      question: "Does this PRD grouping work for you?",
      header: "PRD grouping",
      options: [
        { label: "Looks good", description: "Proceed with this grouping as-is" },
        { label: "Merge some", description: "Combine two or more themes into a single PRD" },
        { label: "Split further", description: "Break a theme into smaller, more focused PRDs" },
        { label: "Re-scope", description: "Adjust what's included in one or more themes" }
      ],
      multiSelect: false
    }
  ]
})
```

If the user selects "Merge some", "Split further", or "Re-scope", ask follow-up questions (also via `AskUserQuestion`) to refine. Iterate until the user selects "Looks good" or equivalent approval.

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

2. **Pre-save validation:** Before presenting each PRD draft for review, check:
- Every requirement traces to content discussed in Phases 1-5
- Problem statement references the evidence type from Phase 1
- No features or scope items that weren't part of the conversation
- No AI-inferred requirements that the user didn't confirm

If validation flags are found, display them alongside the PRD draft:
```
⚠️ Validation: {N} items may not trace to conversation
- [FLAG] FR-002: "Support bulk operations" — not discussed in any phase
  → Remove or ask user to confirm
```

3. **Present to user for review** — display the generated content, then **use `AskUserQuestion`**:

```
AskUserQuestion({
  questions: [
    {
      question: "PRD 1 of [N]: '[Title]' — what would you like to do?",
      header: "PRD review",
      options: [
        { label: "Save", description: "Create this PRD as-is" },
        { label: "Edit", description: "Revise the content before saving" },
        { label: "Skip", description: "Don't create this PRD" }
      ],
      multiSelect: false
    }
  ]
})
```

**Wait for explicit approval before saving each PRD.** If the user selects "Edit", ask what to change (also via `AskUserQuestion` if the changes can be categorized, or accept free-text via "Other").

4. **Save approved PRDs**:

```
result = mcp__asdlc__create_prd(title="<title>")
# Then write content to the returned file_path:
Write(file_path=result["file_path"], content="<markdown_content>")
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
- Design architecture: /sdlc:prd-architect "{prd-id}"  ← recommended before splitting
- Split into tasks: /sdlc:prd-split "{prd-id}"
- Investigate feasibility: /sdlc:prd-investigate "{prd-id}"
```

## ⛔ STOP HERE

**Do NOT proceed further.** The ideation workflow is complete.

The user must explicitly run one of these commands to continue:
- `/sdlc:prd-update` — To refine a PRD
- `/sdlc:prd-architect` — To design architecture before splitting (recommended next step)
- `/sdlc:prd-split` — To create tasks from a PRD (run architect first)
- `/sdlc:prd-investigate` — To validate a PRD against the codebase

**Wait for user's next instruction.**

## Conversation Guidelines

- **Always use `AskUserQuestion`** for user input — never rely on plain-text questions that require the user to type free-form answers. The "Other" option always provides an escape hatch for custom responses.
- **Ask 2–4 questions per `AskUserQuestion` call**, grouping related questions together. Don't overwhelm with too many calls in sequence.
- **Provide context before the tool call** — summarize what you've heard, explain the options briefly, then present the choices.
- **Follow the user's energy**. If they want to dive deep on one aspect, go with it. If they want to skip ahead, let them.
- **Use codebase context** to make options concrete when artifacts are available (e.g., reference real component names in option descriptions).
- **Name the phase transitions** so the user knows where they are: "Now that we have a clear picture of the problem, let's explore some approaches..."
- **Don't force phases**. A simple idea might go straight from Phase 1 to Phase 5. A complex idea might loop between Phases 2–4 multiple times.
- **Adapt options dynamically** — each `AskUserQuestion` call should reflect what you've learned so far, not use generic/static options.
- **Never expand scope beyond what the user discussed** — if the user described 2 features, the PRDs cover 2 features (not 3)
- **If user's idea is vague, ask for specifics** — a follow-up question is always better than an assumption

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
let me understand the landscape.
```

Then Claude calls:
```
AskUserQuestion({
  questions: [
    {
      question: "What's prompting this performance concern?",
      header: "Motivation",
      options: [
        { label: "User complaints", description: "Users have reported the app feeling slow" },
        { label: "Proactive", description: "No complaints yet, but you see room for improvement" },
        { label: "Metrics/alerts", description: "Monitoring shows degraded performance" },
        { label: "Scaling concerns", description: "Current performance won't sustain growth" }
      ],
      multiSelect: false
    },
    {
      question: "Where do you feel the slowness most?",
      header: "Pain point",
      options: [
        { label: "Page loads", description: "Initial render and navigation feel sluggish" },
        { label: "API responses", description: "Backend endpoints are too slow" },
        { label: "Data processing", description: "Background jobs or batch operations lag" },
        { label: "Build/deploy", description: "Development and deployment pipeline is slow" }
      ],
      multiSelect: true
    }
  ]
})
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
```

Then Claude calls:
```
AskUserQuestion({
  questions: [
    {
      question: "Does this PRD grouping work for you?",
      header: "PRD grouping",
      options: [
        { label: "Looks good", description: "Proceed with these 2 PRDs as-is" },
        { label: "Merge into one", description: "Combine both into a single performance PRD" },
        { label: "Split further", description: "Break one of these into more specific PRDs" },
        { label: "Re-scope", description: "Adjust what's included or excluded" }
      ],
      multiSelect: false
    }
  ]
})
```

**Phase 6 — reviewing PRDs one by one, creating on approval via `AskUserQuestion`.**

## Notes

- Ideation naturally precedes `/sdlc:prd-generate` — use ideate when the user doesn't yet know what to build
- Each ideation session may produce 0–N PRDs (zero is fine if the user decides to think more)
- The "parking lot" ensures no ideas are lost, just deferred
- All PRDs start in `draft` status
- Works with or without a prior `/sdlc:scan` — questions adapt accordingly
