# /sdlc:retrospective

Analyze correction logs, identify patterns, and interactively distill them into lesson-learn entries.

## Options

Parse the user's arguments for these flags:

- `--sprint <sprint-id>` — Focus on corrections archived for a specific sprint (`corrections.log.{sprint_id}`)
- `--include-archived` — Include all archived correction logs in addition to the current log
- `--dry-run` — Show analysis only, do not propose or write lessons

## Step 1: Load Context

### 1.1: Verify Project

```
mcp__asdlc__get_context()
```

Confirm an active project exists. If not, instruct the user to run `/sdlc:init`.

### 1.2: Read Existing Lessons

Read both lesson-learn files and display a summary of what exists:

```
Read: .sdlc/lesson-learn.md
Read: ~/.a-sdlc/lesson-learn.md
```

Display:
```
Existing Lessons:
  Project (.sdlc/lesson-learn.md): {N} lessons across {M} categories
  Global  (~/.a-sdlc/lesson-learn.md): {N} lessons across {M} categories
```

If either file does not exist, note it and continue — the file will be created when lessons are written.

## Step 2: Collect Corrections

### 2.1: Determine Which Files to Read

**If `--sprint <sprint-id>` is provided:**
- Read `.sdlc/corrections.log.{sprint_id}` (the archived log for that sprint)
- If the file does not exist, inform the user and stop

**If `--include-archived` is provided:**
- Read `.sdlc/corrections.log` (current unarchived)
- Use `Glob` to find all `.sdlc/corrections.log.*` files
- Read each archived file

**Default (no flags):**
- Read `.sdlc/corrections.log` (current unarchived only)

### 2.2: Parse Entries

Each line in the correction log follows this format:
```
TIMESTAMP | context_type:context_id | category | description
```

Parse all entries into a structured list. If no entries are found:
> No corrections found. Nothing to analyze.

Stop here.

### 2.3: Display Raw Summary

```
Found {N} corrections from {source}:

  By Category:
    testing:            {count}
    code-quality:       {count}
    task-completeness:  {count}
    architecture:       {count}
    security:           {count}
    performance:        {count}
    documentation:      {count}
    process:            {count}

  By Context:
    task:   {count}
    prd:    {count}
    sprint: {count}
    pr:     {count}
```

## Step 3: Analyze Patterns

### 3.1: Identify Patterns

Group corrections by category. A **pattern** is a category with **2 or more** corrections.

### 3.2: Present Analysis

```
Patterns Detected:

  testing (4 corrections):
    - "Missing edge case test for auth token expiry" (task:PROJ-T00012)
    - "No integration test for payment webhook" (task:PROJ-T00015)
    - "Test didn't cover null input" (pr:42)
    - "Missing boundary test for pagination" (task:PROJ-T00018)

  code-quality (2 corrections):
    - "Duplicated validation logic in two handlers" (task:PROJ-T00014)
    - "Inconsistent error message format" (pr:42)

Categories with <2 corrections (no pattern):
  architecture (1), documentation (1)
```

If **no** categories have 2+ corrections:
> No patterns detected (all categories have fewer than 2 corrections). No lessons to propose.

Stop here.

If `--dry-run` was specified: **STOP HERE**. Do not proceed to Step 4.

## Step 4: Propose Lessons

**CRITICAL: Anti-Fluff Rules**

- **MUST NOT** generalize beyond what the correction log shows — no "best practices" or generic advice
- **MUST NOT** invent patterns that aren't evidenced by 2+ actual corrections
- **MUST NOT** add recommendations for processes, tools, or practices not directly related to observed corrections
- **MUST** cite specific correction log entries as evidence for each proposed lesson
- **MUST** keep lesson descriptions factual and grounded in the correction data

**If the log shows 3 testing corrections about missing edge cases, the lesson is about missing edge cases — not about "improving overall test strategy".**

### 4.1: For Each Pattern

For each category with 2+ corrections, propose a lesson via `AskUserQuestion`:

```
AskUserQuestion({
  questions: [
    {
      question: "Proposed lesson from {N} '{category}' corrections:\n\n\"{draft_description}\"\n\nEvidence:\n{bullet_list_of_correction_entries}\n\nAccept this lesson?",
      header: "Lesson",
      options: [
        { label: "Approve", description: "Add as SHOULD-level lesson" },
        { label: "Promote to MUST", description: "Add as MUST-level (always enforce)" },
        { label: "Edit", description: "Modify the description before saving" },
        { label: "Skip", description: "Don't save this lesson" }
      ],
      multiSelect: false
    },
    {
      question: "Where should this lesson be saved?",
      header: "Scope",
      options: [
        { label: "Project only", description: "Save to .sdlc/lesson-learn.md" },
        { label: "Global", description: "Save to ~/.a-sdlc/lesson-learn.md" },
        { label: "Both", description: "Save to both project and global files" }
      ],
      multiSelect: false
    }
  ]
})
```

**If user chooses "Edit":** Ask a follow-up question for the modified description, then write with the user's text.

### 4.2: Draft Description Guidelines

The draft description should:
- Start with an action verb (e.g., "Ensure", "Verify", "Include", "Check")
- Reference the specific pattern observed (not generic advice)
- Be one sentence, max two

Example drafts:
- From 4 testing corrections about missing edge cases: "Ensure unit tests cover boundary conditions and null inputs for all handler functions."
- From 2 code-quality corrections about duplication: "Extract shared validation logic into reusable helpers instead of duplicating across handlers."
- From 3 architecture corrections about coupling: "Keep API route handlers decoupled from database queries by using a service layer."

## Step 5: Write Approved Lessons

For each approved lesson, use the `Edit` tool to append to the correct `## {Category}` section in the target lesson-learn file(s).

### 5.1: Entry Format

```markdown
- **[{PRIORITY}]** {Description}
  - *Source:* Retrospective ({N} corrections)
  - *Example:* {most representative correction entry from the log}
  - *Added:* {YYYY-MM-DD}
```

### 5.2: Placement

Find the `## {Category}` section (e.g., `## Testing`, `## Code Quality`) in the lesson-learn file. Append the new entry after any existing entries in that section, before the next `##` heading.

If the category section does not exist, append a new `## {Category}` section at the end of the file.

### 5.3: File Creation

If the target lesson-learn file does not exist:
1. Read the template from `src/a_sdlc/artifact_templates/lesson-learn.template.md` (if available in the project)
2. Otherwise create with this minimal structure:

```markdown
# Lessons Learned

Rules and patterns discovered during development.

**Priority Levels:**
- **MUST** — Always follow. Never skip without explicit user override
- **SHOULD** — Follow by default. Skip only with justification
- **MAY** — Consider when relevant. Skip freely if not applicable
```

Then append the new category section and entry.

## Step 6: Summary

Display a final report:

```
╭─────────────────────────────────────────────────────╮
│  Retrospective Complete                              │
╰─────────────────────────────────────────────────────╯

Corrections analyzed: {total}
Patterns detected:    {count} categories with 2+ corrections
Lessons proposed:     {proposed}
Lessons saved:        {saved}
Lessons skipped:      {skipped}

Saved to:
  {list of files modified with lesson counts}

Next steps:
  - Lessons will be enforced in /sdlc:prd-split, /sdlc:task-start, /sdlc:sprint-run
  - Review with: cat .sdlc/lesson-learn.md
```

## MCP Tools Used

- `mcp__asdlc__get_context()` — Verify active project

## Native Tools Used

- `Read` — Read correction logs and lesson-learn files
- `Glob` — Find archived correction log files (`.sdlc/corrections.log.*`)
- `Edit` — Append lessons to lesson-learn files
- `AskUserQuestion` — Interactive lesson approval

## Related Commands

- `/sdlc:sprint-complete` — Completes a sprint and archives corrections (suggests running this command)
- `/sdlc:task-complete` — Definition-of-done checklist
- `/sdlc:pr-feedback` — Logs corrections from PR review comments
