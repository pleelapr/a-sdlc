# /sdlc:task-list

## Purpose

Display all tasks with status and priority.

## Output

```
Tasks Overview

Active (5):
  🔴 TASK-001  [High]   Implement FR-001 in auth-service
  🔴 TASK-002  [High]   Test FR-001 - auth-service
  🟡 TASK-003  [Medium] Implement FR-002 in user-service
  🟡 TASK-004  [Medium] Implement FR-003 in api-gateway
  🟢 TASK-005  [Low]    Update documentation

In Progress (1):
  ⏳ TASK-006  [High]   Implement FR-004 in data-layer

Blocked (1):
  🚫 TASK-007  [High]   Integrate with external API
     Reason: Waiting for API credentials

Completed (3):
  ✅ TASK-008  Completed 2025-01-20
  ✅ TASK-009  Completed 2025-01-20
  ✅ TASK-010  Completed 2025-01-21
```

## Filters

```
/sdlc:task-list                    # All tasks
/sdlc:task-list --active           # Only pending/in-progress
/sdlc:task-list --completed        # Only completed
/sdlc:task-list --priority high    # Only high priority
/sdlc:task-list --component auth   # Only auth component
```
