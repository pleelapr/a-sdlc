# /sdlc:pr-feedback — PR Review Comment Processor

Fetch, categorize, and interactively resolve GitHub PR review comments for the current branch.

**CRITICAL: You MUST use the `mcp__asdlc__get_pr_feedback` MCP tool to fetch PR comments. Do NOT use `gh` CLI, `gh api`, `gh pr view`, or any other GitHub CLI commands. The MCP tool handles authentication automatically using the configured PAT token (project-level, global, or GITHUB_TOKEN env var). Do NOT attempt to fetch PR data through any other method.**

## Options

Parse the user's arguments for these flags:

- `--dry-run` — Show summary only, do not propose fixes
- `--filter <username>` — Only show comments from this GitHub reviewer
- `--unresolved` — Only show unresolved review threads

## Phase 1: Fetch Comments

**You MUST call the `mcp__asdlc__get_pr_feedback` MCP tool** — do NOT use `gh` CLI or Bash:

```
mcp__asdlc__get_pr_feedback(
  unresolved_only=<true if --unresolved>,
  reviewer=<username if --filter>
)
```

If the tool returns `status: "error"` or `status: "no_pr"`, display the message and stop.

## Phase 2: Categorize Comments

For each comment returned, classify it into one of these categories:

| Category | Description | Criteria |
|----------|-------------|----------|
| **Actionable — Code Change** | Requests a specific code modification | Suggests adding/removing/changing code, fixing a bug, renaming, refactoring |
| **Actionable — Question** | Asks a question that may lead to a change | "Why does this...?", "Should we...?", "What happens if...?" |
| **Informational** | Praise, acknowledgment, or general notes | "LGTM", "Nice!", "FYI", explanations with no action requested |
| **Resolved** | Already addressed or outdated | Thread is resolved, or reply indicates fix was applied |

Review summaries (type: "review") with state "APPROVED" and empty body are **Informational**.
Review summaries with state "CHANGES_REQUESTED" should be categorized based on their body content.

## Phase 3: Present Summary

Display a summary table:

```
╭─────────────────────────────────────────────────────╮
│  PR #<number>: <title>                               │
│  Branch: <branch> → <base>                           │
│  URL: <html_url>                                     │
╰─────────────────────────────────────────────────────╯

📊 Comment Summary
┌─────────────────────────┬───────┐
│ Category                │ Count │
├─────────────────────────┼───────┤
│ Actionable — Code Change│   X   │
│ Actionable — Question   │   X   │
│ Informational           │   X   │
│ Resolved                │   X   │
├─────────────────────────┼───────┤
│ Total                   │   X   │
└─────────────────────────┴───────┘
```

Then list each actionable comment with:
- Author and timestamp
- File path and line number (for review comments)
- The diff hunk context
- The comment body
- Your proposed category

If `--dry-run` was specified: **STOP HERE**. Do not proceed to Phase 4.

## Phase 4: Interactive Fix Loop

For each **Actionable — Code Change** comment, in order:

1. **Show Context**: Display the comment, the diff hunk, and read the current file at the relevant location
2. **Propose Fix**: Based on the reviewer's feedback, propose a specific code change
3. **Ask User**: Present these options:
   - **Apply** — Apply the proposed fix
   - **Modify** — Let the user adjust the fix before applying
   - **Skip** — Skip this comment, move to next
   - **Stop** — End the fix loop entirely

4. **Apply**: If the user chooses Apply or Modify, use the Edit tool to make the change

For **Actionable — Question** comments:
- Show the question and relevant code context
- Ask the user how they'd like to respond (code change, or note to address later)
- Apply if the user provides a fix

### Scope Boundaries

**NEVER** do any of the following without explicit user request:
- Push commits or branches
- Resolve or dismiss review threads on GitHub
- Post comments on the PR
- Modify files without per-comment user approval

### CRITICAL: Anti-Fluff Rules

**Every proposed fix must address ONLY what the reviewer's comment asks for. Zero scope creep.**

- **MUST NOT** refactor surrounding code while fixing a specific comment
- **MUST NOT** add error handling, validation, or edge-case coverage the reviewer didn't request
- **MUST NOT** "improve" code style, naming, or structure beyond the reviewer's specific ask
- **MUST NOT** fix unrelated issues you notice in the same file
- **MUST NOT** add tests, documentation, or logging unless the reviewer explicitly requested them
- **MUST NOT** propose architectural changes when the reviewer asked for a simple fix
- **MUST** scope each fix to the exact lines and concern the reviewer raised
- **MUST** ask the user if a fix seems to require broader changes — never silently expand scope

**If the reviewer says "rename this variable", the fix is renaming that variable — not restructuring the function.**

## Phase 5: Completion Summary

After processing all actionable comments (or if the user chose Stop):

```
╭─────────────────────────────────────────────────────╮
│  PR Feedback Processing Complete                     │
╰─────────────────────────────────────────────────────╯

✅ Fixed:   X comments
⏭️  Skipped: X comments
📋 Remaining: X comments (not yet addressed)

Next steps:
- Review the changes with `git diff`
- Run tests to verify the fixes
- Commit when ready: /commit
```

## Phase 6: Log Corrections

For each PR comment that was **Applied** or **Modified** in Phase 5, log it via the MCP tool:

```
mcp__asdlc__log_correction(
  context_type="pr",
  context_id="{pr_number}",
  category="{category}",
  description="{description_of_fix}"
)
```

**Category mapping from PR comment types:**
- Bug/Logic fix → `code-quality`
- Missing test → `testing`
- Security concern → `security`
- Performance issue → `performance`
- Design/Structure change → `architecture`
- Documentation gap → `documentation`
- Other → `process`

Skip comments marked as **Won't Fix** or **Already Done** — only log corrections that resulted in actual code changes.

## MCP Tools Used

- `mcp__asdlc__get_pr_feedback()` — **REQUIRED** — Fetch PR comments (handles all GitHub API work, token resolution, and pagination). Do NOT substitute with `gh` CLI.
- `mcp__asdlc__configure_github()` — One-time token setup (if needed)
