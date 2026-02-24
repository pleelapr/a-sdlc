# /sdlc:sprint-complete

## Purpose

Close a sprint and generate a summary report. Optionally update PRD statuses.

## Syntax

```
/sdlc:sprint-complete <sprint-id> [--force]
```

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `sprint-id` | Yes | Sprint ID to complete (e.g., SPRINT-01) |
| `--force` | No | Complete even if tasks remain incomplete |

## Execution Steps

### 1. Get Sprint and Analyze Status

```
mcp__asdlc__get_sprint(sprint_id="SPRINT-01")
```

Check:
- Sprint exists
- Sprint status is `active` (or `planned` with --force)

### 2. Get Tasks via PRDs

```
mcp__asdlc__get_sprint_prds(sprint_id="SPRINT-01")
```

For each PRD, get tasks:
```
mcp__asdlc__list_tasks(prd_id="<prd_id>")
```

Count by status:
- Completed
- In Progress
- Pending
- Blocked

### 3. Handle Incomplete Tasks

If incomplete tasks exist and no --force:
```
Sprint SPRINT-01 has incomplete tasks:

  In Progress (1):
    TASK-004: Implement token refresh

  Pending (1):
    TASK-005: Add logout endpoint

Options:
1. Complete remaining tasks first
2. Force complete: /sdlc:sprint-complete SPRINT-01 --force
   (Incomplete tasks remain in their PRDs for future sprints)
```

### 4. Update PRD Statuses

For each PRD in the sprint, check if all tasks are completed:

```
mcp__asdlc__list_tasks(prd_id="<prd_id>")
```

If ALL tasks for a PRD are completed:
```
mcp__asdlc__update_prd(prd_id="<prd_id>", status="completed")
```

**Output:**
```
PRD Status Updates:
  ✅ feature-auth → completed (4/4 tasks done)
  ⏳ feature-payments → split (2/5 tasks done)
```

### 5. Complete Sprint

```
mcp__asdlc__complete_sprint(sprint_id="SPRINT-01")
```

This will:
1. Update sprint status to `completed`
2. Set `completed_at` timestamp
3. Return summary with task counts

### Step 5.5: Auto-Retrospective & Lesson Distillation

After sprint completion, before generating the final report:

**5.5.1: Load Correction Log**

Corrections are logged throughout the sprint via `mcp__asdlc__log_correction()` from any workflow — task implementation, PRD splits, sprint execution, PR feedback, and ad-hoc fixes. Read the accumulated log:

```
Read: .sdlc/corrections.log
```

If the file does not exist or is empty:
> No corrections logged during this sprint. Skipping retrospective.

Proceed to the report step.

**5.5.2: Filter & Analyze**

Parse correction log entries. Filter to entries relevant to this sprint:
- Entries with `sprint:{sprint_id}` context
- Entries with `task:{task_id}` where task belongs to this sprint
- Entries timestamped during the sprint period

Group by category and count:
```
Category Analysis:
- testing: 4 corrections (most frequent)
- code-quality: 2 corrections
- task-completeness: 2 corrections
- architecture: 1 correction
```

**5.5.3: Propose Lessons**

**CRITICAL: Anti-Fluff Rules for Retrospective**

- **MUST NOT** generalize beyond what the correction log shows — no "best practices" or generic advice
- **MUST NOT** invent patterns that aren't evidenced by 2+ actual corrections
- **MUST NOT** add recommendations for processes, tools, or practices not directly related to observed corrections
- **MUST** cite specific correction log entries as evidence for each proposed lesson
- **MUST** keep lesson descriptions factual and grounded in sprint data

**If the log shows 3 testing corrections about missing edge cases, the lesson is about missing edge cases — not about "improving overall test strategy".**

For each category with 2+ corrections, draft a lesson-learn entry:

```
Proposed Lesson 1 of N:

Category: Testing
Priority: SHOULD (suggested based on frequency)
Description: "Ensure unit tests cover edge cases for {pattern observed}.
             This sprint had 4 corrections related to missing test coverage."
Example: "{specific correction from the log}"
```

Present each proposed lesson via AskUserQuestion:

```
AskUserQuestion({
  questions: [
    {
      question: "Proposed lesson from 4 testing corrections. Accept this lesson?",
      header: "Lesson 1",
      options: [
        { label: "Approve", description: "Add this lesson as-is to lesson-learn.md" },
        { label: "Edit", description: "Modify the description or priority before saving" },
        { label: "Promote to MUST", description: "This is critical enough to be a MUST-level lesson" },
        { label: "Skip", description: "Don't save this lesson" }
      ],
      multiSelect: false
    },
    {
      question: "Where should this lesson be saved?",
      header: "Scope",
      options: [
        { label: "Project only", description: "Save to .sdlc/lesson-learn.md (this project only)" },
        { label: "Global", description: "Save to ~/.a-sdlc/lesson-learn.md (all projects)" },
        { label: "Both", description: "Save to both project and global lesson-learn files" }
      ],
      multiSelect: false
    }
  ]
})
```

**5.5.4: Write Approved Lessons**

For each approved lesson, append to the appropriate lesson-learn.md file(s):

```markdown
### {Category}

- **[{PRIORITY}]** {Description}
  - *Source:* Sprint {sprint_id} retrospective ({N} corrections)
  - *Example:* {example from correction log}
  - *Added:* {timestamp}
```

**5.5.5: Archive Corrections**

After all lessons are processed:
1. Rename `.sdlc/corrections.log` to `.sdlc/corrections.log.{sprint_id}`
2. Create a fresh empty `.sdlc/corrections.log` (or let it be created on next append)

Display:
> Retrospective complete. {N} lessons saved, {M} corrections archived to corrections.log.{sprint_id}

**5.5.6: Include in Sprint Report**

Add a "Lessons Learned" section to the final sprint report:
```
## Lessons Learned This Sprint

- [{PRIORITY}] {Category}: {Description} (from {N} corrections)
- ...

Corrections archived: .sdlc/corrections.log.{sprint_id}
```

### 6. Generate Report

```
Sprint Completed: SPRINT-01 ✅

Name: Auth Feature Sprint
Duration: 5 days (Jan 27 - Jan 31, 2025)

Results:
  ✅ Completed: 4 tasks
  ⏳ Remaining: 1 task

PRD Status Updates:
  ✅ feature-auth → completed (all tasks done)

Task Summary:
  TASK-001: Set up OAuth config ✅
  TASK-002: Create login endpoint ✅
  TASK-003: Add user model fields ✅
  TASK-004: Implement token refresh ✅
  TASK-005: Add logout endpoint (pending)
```

## Examples

```
# Complete sprint (all tasks should be done)
/sdlc:sprint-complete SPRINT-01

# Force complete even with incomplete tasks
/sdlc:sprint-complete SPRINT-01 --force
```

## Error Cases

### Sprint Not Found
```
Error: Sprint not found: SPRINT-99
```

### Sprint Not Active
```
Error: Sprint SPRINT-01 is not active.

Current status: planned

Start the sprint first: /sdlc:sprint-start SPRINT-01
```

### Incomplete Tasks Without Force
```
Warning: Sprint has 2 incomplete tasks.

Use --force to complete anyway.
Or complete the tasks first with /sdlc:task-complete.
```

## Notes

- Completing a sprint does NOT delete tasks or PRDs
- Incomplete tasks remain in their PRDs for future work
- PRDs with all tasks done are automatically marked as "completed"
- Sprint data is stored in the database (not archived to files)

## Related Commands

- `/sdlc:sprint-show` - View sprint before completing
- `/sdlc:task-complete` - Complete individual tasks
- `/sdlc:sprint-create` - Create a new sprint for remaining work
