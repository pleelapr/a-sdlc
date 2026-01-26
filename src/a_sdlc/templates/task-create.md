# /sdlc:task-create

## Purpose

Manually create a task without deriving from requirements.

## Interactive Prompts

```
Task title: Fix login timeout bug
Priority [high/medium/low]: high
Component (optional): auth-service
Related requirement (optional): FR-001
Description:
> The login process times out after 5 seconds...

Files to modify (comma-separated):
> src/auth/login.py, src/auth/config.py

Success criteria (one per line, empty to finish):
> Login completes within 30 seconds
> Timeout is configurable
>
```

## Output

```
Task Created: TASK-012

Title: Fix login timeout bug
Priority: high
Component: auth-service

Location: .sdlc/tasks/active/TASK-012.md
```
