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

### Step 5.5: Archive Corrections & Suggest Retrospective

After sprint completion, before generating the final report:

**5.5.1: Archive Correction Log**

```
Read: .sdlc/corrections.log
```

If the file exists and is not empty:
1. Rename `.sdlc/corrections.log` to `.sdlc/corrections.log.{sprint_id}`
2. Display: `Corrections archived to .sdlc/corrections.log.{sprint_id}`

If the file does not exist or is empty:
> No corrections logged during this sprint.

**5.5.2: Suggest Retrospective**

If corrections were archived, suggest running the dedicated retrospective command:

```
Corrections from this sprint have been archived.

To analyze patterns and distill lessons, run:
  /sdlc:retrospective --sprint {sprint_id}
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
