# /sdlc:task-link

## Purpose

Link a local task to an external system (Linear, GitHub).

## Usage

```
/sdlc:task-link TASK-001 ENG-123
```

## Execution

1. Validate local task exists
2. Store external ID in task metadata
3. Fetch external URL (if possible)
4. Update task file with external reference

## Output

```
Task Linked!

Local: TASK-001
External: ENG-123
URL: https://linear.app/team/issue/ENG-123

Future updates will sync to Linear.
```
