# Round-Table Shared Instruction Blocks

> This file contains reusable instruction blocks for persona-integrated templates.
> Templates reference these sections by name (Section A, B, C).
> This file is NOT deployed as a skill (underscore prefix excludes it).

---

## Section A: Persona Availability Check

Perform this check at template start, after loading context:

1. Check `~/.claude/agents/` for files matching `sdlc-*.md` pattern
2. Determine round-table eligibility:
   - If `--solo` or `--no-roundtable` appears in the user's command: **round_table_enabled = false**
   - If no `sdlc-*.md` files found: **round_table_enabled = false**
   - Otherwise: **round_table_enabled = true**
3. If round_table_enabled = false, skip ALL persona-specific sections below. The template operates in single-agent mode (existing behavior preserved).

---

## Section B: Domain Detection + Panel Assembly

If round_table_enabled = true, perform domain detection before the first major decision point:

### B.1 Domain Detection

Analyze available context to identify relevant domains. Check in priority order:

1. **Explicit tags** — Look for `<!-- personas: frontend, security -->` markers in PRD/task content. If found, use those domains directly.
2. **Codebase signals** — From `.sdlc/artifacts/architecture.md`, identify affected components (e.g., components with "UI", "React", "frontend" → frontend domain; "API", "database" → backend domain; "CI/CD", "Docker" → devops domain).
3. **Keyword analysis** — Scan user input for domain keywords:
   - Frontend: UI, component, React, CSS, layout, responsive, accessibility
   - Backend: API, endpoint, database, query, migration, service, middleware
   - DevOps: CI/CD, pipeline, Docker, deploy, infrastructure, monitoring
   - Security: auth, vulnerability, encryption, OWASP, credentials, permissions
4. **Content structure** — PRD functional requirements referencing specific technical domains

### B.2 Panel Assembly

Based on detected domains, assemble the persona panel:

| Rule | Logic |
|------|-------|
| **Domain personas** (Frontend, Backend, DevOps) | Include only if their domain is detected |
| **Cross-cutting** (Security, QA) | Always included as advisors |
| **Phase-role** (Product Manager, Architect) | PM for discovery/ideation phases; Architect for design/architecture phases |
| **Lead assignment** | The persona whose domain has the strongest signal becomes lead. If unclear, use the phase-role persona as lead. |

Display the panel to the user:

```
Persona Panel:
  Lead: {persona_name} (signal: {detection_reason})
  Advisor: {persona_name} (signal: {detection_reason})
  ...
```

---

## Section C: Round-Table Discussion

If round_table_enabled = true, execute before each major AskUserQuestion checkpoint:

### C.1 Build Context Packages

For each persona in the panel, build a filtered context package containing:
- The current phase's working content (PRD draft, task plan, test strategy, etc.)
- Domain-relevant artifacts (e.g., frontend engineer gets component structure, backend gets API docs)
- The specific question or decision point being discussed

### C.2 Detect Round-Table Mode

Check the execution environment:
- If `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` environment variable equals `"1"`: Use **Agent Teams mode**
- Otherwise: Use **Task tool mode**

Display: `Round-Table Mode: {Agent Teams | Task Tool Fallback}`

### C.3a Agent Teams Mode (when CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1)

1. Create an agent team with persona teammates. For each persona in the panel:
   - Spawn a teammate with the persona's role and domain context
   - Instruct them to: analyze from their domain perspective, share findings, and challenge other perspectives
2. Teammates debate via SendMessage:
   - Each persona presents their analysis
   - Personas challenge each other's findings and suggest alternatives
   - Lead monitors progress and steers toward actionable recommendations
3. When discussion converges (or after each persona has spoken at least twice), lead collects final positions
4. Shut down teammates and clean up team

### C.3b Task Tool Mode (fallback when Agent Teams not enabled)

1. Dispatch persona subagents in parallel via Task tool. For each persona:

```
Task(
  description="{persona_name} analysis for {phase_name}",
  subagent_type="{persona_agent_name}",
  prompt="""You are the {persona_name} — {persona_description}.

{persona_context_package}

Analyze this from your domain perspective. Structure your response as:

---PERSONA-FINDINGS---
role: {lead|advisor}
domain: {domain}
findings:
- {finding with domain context}
risks:
- {risk from your perspective}
recommendations:
- {specific, actionable recommendation}
---END-FINDINGS---
"""
)
```

2. Collect all `---PERSONA-FINDINGS---` blocks from subagent responses

### C.4 Synthesize Findings

Merge all persona findings into an attributed synthesis document:

```markdown
## Round-Table Synthesis: {Phase Name}

### [{Persona Name} — {Role}]:
- {Finding/recommendation with domain context}

### [{Persona Name} — {Role}]:
- {Finding/recommendation with domain context}

### Consensus:
- [Agreed] {Point all personas support}
- [Debated] {Point with disagreement} — {Persona A} suggests X, {Persona B} suggests Y → escalating to user

### Risks Identified:
- [{Persona}] {Risk description}
```

**Critical rule**: Disagreements between personas are ALWAYS surfaced to the user for decision. The orchestrator/lead never resolves disagreements autonomously.

### C.5 Present and Continue

Present the synthesis to the user, then proceed to the template's existing AskUserQuestion checkpoint. The user's decision incorporates persona recommendations.

---

## Section D: Component-to-Persona Mapping

When dispatching Task agents for individual tasks (e.g., during sprint execution or task-start), use this mapping to select the correct `subagent_type` based on the task's `component` field. This table is the single source of truth for component-based persona routing.

### D.1 Mapping Table

| Component Keywords (case-insensitive substring match) | subagent_type |
|---|---|
| api, backend, server, service, middleware, database, model | `sdlc-backend-engineer` |
| ui, frontend, component, layout, style, css, react | `sdlc-frontend-engineer` |
| ci, cd, pipeline, docker, deploy, infra, monitoring | `sdlc-devops-engineer` |
| auth, security, encryption, permissions, owasp | `sdlc-security-engineer` |
| architecture, design, system | `sdlc-architect` |
| test, qa, coverage, e2e | `sdlc-qa-engineer` |
| _(null, empty, or no match)_ | `general-purpose` |

> **Row ordering matters.** The table is scanned top-to-bottom, and the first matching row wins. Security keywords (auth, security, encryption, permissions, owasp) are listed BEFORE architecture keywords (architecture, design, system) to ensure that tasks with "auth" in their component match `sdlc-security-engineer`, not `sdlc-architect`.

> **Note on `sdlc-product-manager`:** The Product Manager persona is not dispatched via component matching. It is used for phase-role contexts such as ideation (`/sdlc:ideate`), PRD generation (`/sdlc:prd-generate`), and requirements discovery, where the workflow itself determines the persona rather than a task's component field.

### D.2 Resolution Pseudocode

```
function resolve_subagent_type(task):
    component = task.component

    # 1. Handle null or empty component
    if component is null or component.strip() == "":
        return "general-purpose"

    # 2. Normalize to lowercase
    component_lower = component.lower()

    # 3. Define mapping rows (order matters — first match wins)
    mapping = [
        (["api", "backend", "server", "service", "middleware", "database", "model"], "sdlc-backend-engineer"),
        (["ui", "frontend", "component", "layout", "style", "css", "react"],        "sdlc-frontend-engineer"),
        (["ci", "cd", "pipeline", "docker", "deploy", "infra", "monitoring"],       "sdlc-devops-engineer"),
        (["auth", "security", "encryption", "permissions", "owasp"],                "sdlc-security-engineer"),
        (["architecture", "design", "system"],                                      "sdlc-architect"),
        (["test", "qa", "coverage", "e2e"],                                         "sdlc-qa-engineer"),
    ]

    # 4. Scan top-to-bottom; return first match
    for keywords, subagent_type in mapping:
        for keyword in keywords:
            if keyword in component_lower:
                return subagent_type

    # 5. No match — fall back to general-purpose
    return "general-purpose"
```
