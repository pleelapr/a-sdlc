# /sdlc:sprint-create

## Purpose

Create a new sprint for grouping and executing tasks together, then immediately link PRDs to it.

## Execution Steps

### Step 1: Create the Sprint

Use the MCP tool to create a sprint:

```
result = mcp__asdlc__create_sprint(
    title="<title from user>",
    goal="<goal from user, if provided>"
)
sprint_id = result["sprint"]["id"]
```

Display the result:

```
Sprint Created: {sprint_id}

Title: {title}
Status: planned
Goal: {goal or 'N/A'}
```

### Step 2: Fetch Available PRDs

Immediately after creating the sprint, fetch unassigned PRDs:

```
prds = mcp__asdlc__list_prds()
```

Filter to PRDs that are NOT already assigned to a sprint (those with `sprint_id == null`).

**If no unassigned PRDs exist:**

```
No unassigned PRDs available. Create PRDs first with /sdlc:prd-generate, then link them with /sdlc:sprint-link.
```

STOP here.

**If unassigned PRDs exist**, proceed to Step 3.

### Step 3: Ask Which PRDs to Link

Present the available PRDs using `AskUserQuestion` with `multiSelect: true`:

```
AskUserQuestion([
  {
    question: "Which PRDs should be added to sprint {sprint_id}?",
    header: "Link PRDs",
    options: [
      // One option per unassigned PRD, up to 4
      { label: "{prd.id}", description: "{prd.title} ({prd.status})" },
      ...
    ],
    multiSelect: true
  }
])
```

If there are more than 4 unassigned PRDs, show the first 4 and include a note: "Showing 4 of {N} unassigned PRDs. Use /sdlc:sprint-link to add more."

**If the user selects "Other"** (e.g., "none" or "skip"), do not link any PRDs.

### Step 4: Link Selected PRDs

For each selected PRD, call:

```
mcp__asdlc__manage_sprint_prds(action="add", prd_id="{prd_id}", sprint_id="{sprint_id}")
```

### Step 5: Display Summary

```
Sprint {sprint_id} created with {N} PRD(s) linked.

PRDs:
- {prd_id}: {prd_title}
- ...

Next steps:
- Run sprint: /sdlc:sprint-run {sprint_id}  (auto-activates the sprint)
- Add more PRDs: /sdlc:sprint-link {sprint_id}
```

## Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `title` | Yes | Sprint name |
| `goal` | No | Sprint objective/goal statement |
| `project_id` | No | Project ID (auto-detected) |

## Sprint Lifecycle

1. **planned** - Sprint created, adding PRDs
2. **active** - Sprint started, work in progress
3. **completed** - All work done, sprint closed

## Examples

```
# Simple sprint
/sdlc:sprint-create "Auth Sprint"

# Sprint with goal
/sdlc:sprint-create "Auth Sprint" --goal "Implement OAuth flow"
```

## Related Commands

- `/sdlc:sprint-list` - View all sprints
- `/sdlc:sprint-link` - Link PRDs to a sprint
- `/sdlc:sprint-start` - Activate a sprint
- `/sdlc:sprint-run` - Execute sprint tasks
- `/sdlc:sprint-complete` - Complete a sprint
