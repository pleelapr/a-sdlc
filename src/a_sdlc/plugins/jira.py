"""
Jira Cloud integration plugin for task storage.

Syncs tasks with Jira issue tracker via REST API v3,
allowing bidirectional updates between local SDLC workflow and Jira projects.
"""

from datetime import datetime
from typing import Any

from a_sdlc.plugins.atlassian import APITokenAuth, AtlassianClient
from a_sdlc.plugins.atlassian.client import AtlassianAPIError
from a_sdlc.plugins.base import Task, TaskPlugin, TaskPriority, TaskStatus


class JiraPlugin(TaskPlugin):
    """Sync tasks with Jira Cloud issue tracker.

    This plugin integrates with Jira Cloud REST API v3,
    allowing tasks to be created, updated, and synced with Jira issues.

    Configuration:
        - base_url: Jira site URL (e.g., https://company.atlassian.net)
        - email: Atlassian account email
        - api_token: API token (or set ATLASSIAN_API_TOKEN env var)
        - project_key: Jira project key (e.g., 'PROJ')
        - issue_type: Default issue type (default: 'Task')
        - sync_on_create: Auto-sync new tasks to Jira (default: True)
        - sync_on_complete: Auto-update Jira on completion (default: True)
    """

    # Map SDLC priorities to Jira priority names
    PRIORITY_MAP = {
        TaskPriority.URGENT: "Highest",
        TaskPriority.HIGH: "High",
        TaskPriority.MEDIUM: "Medium",
        TaskPriority.LOW: "Low",
    }

    # Map Jira priority names back to SDLC priorities
    PRIORITY_REVERSE_MAP = {
        "Highest": TaskPriority.URGENT,
        "High": TaskPriority.HIGH,
        "Medium": TaskPriority.MEDIUM,
        "Low": TaskPriority.LOW,
        "Lowest": TaskPriority.LOW,
    }

    # Map SDLC status to common Jira workflow states
    STATUS_MAP = {
        TaskStatus.PENDING: "To Do",
        TaskStatus.IN_PROGRESS: "In Progress",
        TaskStatus.BLOCKED: "Blocked",
        TaskStatus.COMPLETED: "Done",
        TaskStatus.CANCELLED: "Cancelled",
    }

    # Map Jira workflow states back to SDLC status
    STATUS_REVERSE_MAP = {
        "To Do": TaskStatus.PENDING,
        "Backlog": TaskStatus.PENDING,
        "Open": TaskStatus.PENDING,
        "In Progress": TaskStatus.IN_PROGRESS,
        "In Review": TaskStatus.IN_PROGRESS,
        "Blocked": TaskStatus.BLOCKED,
        "On Hold": TaskStatus.BLOCKED,
        "Done": TaskStatus.COMPLETED,
        "Closed": TaskStatus.COMPLETED,
        "Resolved": TaskStatus.COMPLETED,
        "Cancelled": TaskStatus.CANCELLED,
        "Won't Do": TaskStatus.CANCELLED,
    }

    def __init__(self, config: dict) -> None:
        """Initialize Jira plugin.

        Args:
            config: Configuration with base_url, email, api_token, project_key, etc.
        """
        super().__init__(config)

        self.base_url = config.get("base_url", "")
        self.email = config.get("email", "")
        self.api_token = config.get("api_token", "")
        self.project_key = config.get("project_key", "")
        self.issue_type = config.get("issue_type", "Task")
        self.sync_on_create = config.get("sync_on_create", True)
        self.sync_on_complete = config.get("sync_on_complete", True)

        # Local cache for offline support
        self._local_cache: dict[str, Task] = {}
        self._client: AtlassianClient | None = None
        self._transitions_cache: dict[str, list[dict]] = {}

    def _check_configured(self) -> None:
        """Verify plugin is properly configured."""
        if not self.base_url or not self.project_key:
            raise RuntimeError(
                "Jira plugin not configured. Run: a-sdlc plugins configure jira"
            )

    def _get_client(self) -> AtlassianClient:
        """Get or create Atlassian client."""
        if self._client is None:
            auth = APITokenAuth(email=self.email, api_token=self.api_token)
            self._client = AtlassianClient(self.base_url, auth)
        return self._client

    def _format_description_adf(self, task: Task) -> dict:
        """Format task description as Atlassian Document Format (ADF).

        Jira Cloud API v3 requires descriptions in ADF format.

        Args:
            task: Task to format.

        Returns:
            ADF document structure.
        """
        content: list[dict[str, Any]] = []

        # Main description paragraph
        if task.description:
            content.append({
                "type": "paragraph",
                "content": [{"type": "text", "text": task.description}],
            })

        # Requirement ID
        if task.requirement_id:
            content.append({
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "Requirement: ", "marks": [{"type": "strong"}]},
                    {"type": "text", "text": task.requirement_id},
                ],
            })

        # Component
        if task.component:
            content.append({
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "Component: ", "marks": [{"type": "strong"}]},
                    {"type": "text", "text": task.component},
                ],
            })

        # Files to modify
        if task.files_to_modify:
            content.append({
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "Files to Modify:", "marks": [{"type": "strong"}]},
                ],
            })
            content.append({
                "type": "bulletList",
                "content": [
                    {
                        "type": "listItem",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "text": f, "marks": [{"type": "code"}]}],
                            }
                        ],
                    }
                    for f in task.files_to_modify
                ],
            })

        # Implementation steps
        if task.implementation_steps:
            content.append({
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "Implementation Steps:", "marks": [{"type": "strong"}]},
                ],
            })
            content.append({
                "type": "orderedList",
                "content": [
                    {
                        "type": "listItem",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "text": step}],
                            }
                        ],
                    }
                    for step in task.implementation_steps
                ],
            })

        # Success criteria
        if task.success_criteria:
            content.append({
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "Success Criteria:", "marks": [{"type": "strong"}]},
                ],
            })
            content.append({
                "type": "bulletList",
                "content": [
                    {
                        "type": "listItem",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "text": f"☐ {criterion}"}],
                            }
                        ],
                    }
                    for criterion in task.success_criteria
                ],
            })

        # Footer
        content.append({"type": "rule"})
        content.append({
            "type": "paragraph",
            "content": [
                {"type": "text", "text": f"Generated by a-sdlc | Local ID: {task.id}", "marks": [{"type": "em"}]},
            ],
        })

        return {
            "type": "doc",
            "version": 1,
            "content": content,
        }

    def _parse_jira_issue(self, issue: dict) -> Task:
        """Parse Jira issue into Task object.

        Args:
            issue: Jira issue dict from API.

        Returns:
            Task object.
        """
        fields = issue.get("fields", {})

        # Parse priority
        priority_name = fields.get("priority", {}).get("name", "Medium")
        priority = self.PRIORITY_REVERSE_MAP.get(priority_name, TaskPriority.MEDIUM)

        # Parse status
        status_name = fields.get("status", {}).get("name", "To Do")
        status = self.STATUS_REVERSE_MAP.get(status_name, TaskStatus.PENDING)

        # Parse dates
        created = fields.get("created", "")
        updated = fields.get("updated", "")
        resolution_date = fields.get("resolutiondate")

        return Task(
            id=issue["key"],
            title=fields.get("summary", ""),
            description=self._extract_text_from_adf(fields.get("description", {})),
            status=status,
            priority=priority,
            requirement_id=self._extract_requirement_id(fields),
            component=fields.get("components", [{}])[0].get("name") if fields.get("components") else None,
            created_at=datetime.fromisoformat(created.replace("Z", "+00:00")) if created else datetime.now(),
            updated_at=datetime.fromisoformat(updated.replace("Z", "+00:00")) if updated else datetime.now(),
            completed_at=datetime.fromisoformat(resolution_date.replace("Z", "+00:00")) if resolution_date else None,
            external_id=issue["key"],
            external_url=f"{self.base_url}/browse/{issue['key']}",
        )

    def _extract_text_from_adf(self, adf: dict | None) -> str:
        """Extract plain text from ADF document.

        Args:
            adf: ADF document structure.

        Returns:
            Plain text content.
        """
        if not adf or not isinstance(adf, dict):
            return ""

        texts: list[str] = []

        def extract_content(node: dict) -> None:
            if node.get("type") == "text":
                texts.append(node.get("text", ""))
            for child in node.get("content", []):
                if isinstance(child, dict):
                    extract_content(child)

        extract_content(adf)
        return " ".join(texts)

    def _extract_requirement_id(self, fields: dict) -> str | None:
        """Extract requirement ID from labels or custom field.

        Args:
            fields: Jira issue fields.

        Returns:
            Requirement ID if found.
        """
        labels = fields.get("labels", [])
        for label in labels:
            if label.startswith("REQ-"):
                return label
        return None

    def _get_transitions(self, issue_key: str) -> list[dict]:
        """Get available transitions for an issue.

        Args:
            issue_key: Jira issue key.

        Returns:
            List of available transitions.
        """
        if issue_key in self._transitions_cache:
            return self._transitions_cache[issue_key]

        client = self._get_client()
        response = client.get(f"/rest/api/3/issue/{issue_key}/transitions")

        transitions = response.get("transitions", []) if isinstance(response, dict) else []
        self._transitions_cache[issue_key] = transitions
        return transitions

    def _find_transition_id(self, issue_key: str, target_status: str) -> str | None:
        """Find transition ID to reach target status.

        Args:
            issue_key: Jira issue key.
            target_status: Target status name.

        Returns:
            Transition ID if found, None otherwise.
        """
        transitions = self._get_transitions(issue_key)
        target_lower = target_status.lower()

        for transition in transitions:
            if transition.get("to", {}).get("name", "").lower() == target_lower:
                return transition.get("id")
            if transition.get("name", "").lower() == target_lower:
                return transition.get("id")

        return None

    def create_task(self, task: Task) -> str:
        """Create a task and optionally sync to Jira.

        If sync_on_create is True, creates a Jira issue and
        stores the external_id reference.
        """
        self._check_configured()

        # Generate local ID if not provided
        if not task.id:
            task.id = f"TASK-{len(self._local_cache) + 1:03d}"

        # Store locally first
        self._local_cache[task.id] = task

        if self.sync_on_create:
            try:
                client = self._get_client()

                # Build Jira issue creation payload
                issue_data = {
                    "fields": {
                        "project": {"key": self.project_key},
                        "summary": task.title,
                        "description": self._format_description_adf(task),
                        "issuetype": {"name": self.issue_type},
                        "priority": {"name": self.PRIORITY_MAP.get(task.priority, "Medium")},
                    }
                }

                # Add labels for requirement ID
                if task.requirement_id:
                    issue_data["fields"]["labels"] = [task.requirement_id]

                # Add component if specified
                if task.component:
                    issue_data["fields"]["components"] = [{"name": task.component}]

                response = client.post("/rest/api/3/issue", issue_data)

                if isinstance(response, dict) and "key" in response:
                    task.external_id = response["key"]
                    task.external_url = f"{self.base_url}/browse/{response['key']}"

            except AtlassianAPIError as e:
                # Store pending sync marker on failure
                task.external_id = f"JIRA-PENDING-{task.id}"
                raise RuntimeError(f"Failed to create Jira issue: {e}") from e

        return task.id

    def get_task(self, task_id: str) -> Task | None:
        """Retrieve a task by ID.

        First checks local cache, then queries Jira if task_id
        looks like a Jira issue key.
        """
        # Check local cache first
        if task_id in self._local_cache:
            return self._local_cache[task_id]

        # If it looks like a Jira key, fetch from Jira
        if "-" in task_id and not task_id.startswith("TASK-"):
            try:
                self._check_configured()
                client = self._get_client()
                response = client.get(f"/rest/api/3/issue/{task_id}")

                if isinstance(response, dict):
                    task = self._parse_jira_issue(response)
                    self._local_cache[task.id] = task
                    return task

            except AtlassianAPIError:
                pass

        return None

    def list_tasks(self, status: TaskStatus | None = None) -> list[Task]:
        """List tasks, optionally filtered by status.

        Returns tasks from local cache. Use sync_from_jira() to
        pull latest from Jira first.
        """
        tasks = list(self._local_cache.values())

        if status is not None:
            tasks = [t for t in tasks if t.status == status]

        return sorted(tasks, key=lambda t: t.id)

    def update_task(self, task_id: str, updates: dict) -> None:
        """Update fields on a task."""
        task = self._local_cache.get(task_id)
        if task is None:
            raise KeyError(f"Task not found: {task_id}")

        # Apply updates locally
        for key, value in updates.items():
            if key == "status":
                task.status = TaskStatus(value) if isinstance(value, str) else value
            elif key == "priority":
                task.priority = TaskPriority(value) if isinstance(value, str) else value
            elif hasattr(task, key):
                setattr(task, key, value)

        task.updated_at = datetime.now()

        # Sync to Jira if connected
        if task.external_id and not task.external_id.startswith("JIRA-PENDING"):
            try:
                client = self._get_client()

                # Build update payload
                update_data: dict[str, Any] = {"fields": {}}

                if "title" in updates:
                    update_data["fields"]["summary"] = updates["title"]

                if "description" in updates:
                    update_data["fields"]["description"] = self._format_description_adf(task)

                if "priority" in updates:
                    priority = TaskPriority(updates["priority"]) if isinstance(updates["priority"], str) else updates["priority"]
                    update_data["fields"]["priority"] = {"name": self.PRIORITY_MAP.get(priority, "Medium")}

                if update_data["fields"]:
                    client.put(f"/rest/api/3/issue/{task.external_id}", update_data)

                # Handle status change via transitions
                if "status" in updates:
                    new_status = TaskStatus(updates["status"]) if isinstance(updates["status"], str) else updates["status"]
                    target_status = self.STATUS_MAP.get(new_status, "To Do")
                    transition_id = self._find_transition_id(task.external_id, target_status)

                    if transition_id:
                        client.post(
                            f"/rest/api/3/issue/{task.external_id}/transitions",
                            {"transition": {"id": transition_id}},
                        )

            except AtlassianAPIError:
                # Silently fail sync on update - task is still updated locally
                pass

    def complete_task(self, task_id: str) -> None:
        """Mark a task as completed and sync to Jira."""
        task = self._local_cache.get(task_id)
        if task is None:
            raise KeyError(f"Task not found: {task_id}")

        task.status = TaskStatus.COMPLETED
        task.completed_at = datetime.now()
        task.updated_at = datetime.now()

        if self.sync_on_complete and task.external_id and not task.external_id.startswith("JIRA-PENDING"):
            try:
                client = self._get_client()
                transition_id = self._find_transition_id(task.external_id, "Done")

                if transition_id:
                    client.post(
                        f"/rest/api/3/issue/{task.external_id}/transitions",
                        {"transition": {"id": transition_id}},
                    )
            except AtlassianAPIError:
                pass

    def delete_task(self, task_id: str) -> None:
        """Delete a task from local cache.

        Note: Does NOT delete the Jira issue. Use Jira UI for that.
        """
        if task_id not in self._local_cache:
            raise KeyError(f"Task not found: {task_id}")

        del self._local_cache[task_id]

    def sync_from_jira(self, jql: str | None = None) -> int:
        """Pull issues from Jira to local cache.

        Args:
            jql: Custom JQL query. If None, uses default project query.

        Returns:
            Number of tasks synced.
        """
        self._check_configured()
        client = self._get_client()

        if jql is None:
            jql = f"project = {self.project_key} ORDER BY updated DESC"

        response = client.get(
            "/rest/api/3/search/jql",
            params={
                "jql": jql,
                "maxResults": 100,
                "fields": "summary,description,status,priority,components,labels,created,updated,resolutiondate",
            },
        )

        issues = response.get("issues", []) if isinstance(response, dict) else []
        synced = 0

        for issue in issues:
            task = self._parse_jira_issue(issue)
            self._local_cache[task.id] = task
            synced += 1

        return synced

    def sync_to_jira(self, task_id: str | None = None) -> int:
        """Push local tasks to Jira.

        Args:
            task_id: Specific task to sync. If None, syncs all pending.

        Returns:
            Number of tasks synced.
        """
        self._check_configured()
        synced = 0

        tasks_to_sync = (
            [self._local_cache[task_id]] if task_id and task_id in self._local_cache
            else list(self._local_cache.values())
        )

        for task in tasks_to_sync:
            if task.external_id and task.external_id.startswith("JIRA-PENDING"):
                # Create new issue
                task.external_id = None  # Clear pending marker
                self.sync_on_create = True
                try:
                    self.create_task(task)
                    synced += 1
                except RuntimeError:
                    task.external_id = f"JIRA-PENDING-{task.id}"

        return synced

    def link_task(self, local_id: str, jira_key: str) -> None:
        """Link a local task to an existing Jira issue.

        Args:
            local_id: Local task ID.
            jira_key: Jira issue key (e.g., PROJ-123).
        """
        task = self._local_cache.get(local_id)
        if task is None:
            raise KeyError(f"Task not found: {local_id}")

        task.external_id = jira_key
        task.external_url = f"{self.base_url}/browse/{jira_key}"
        task.updated_at = datetime.now()

    def get_jira_instructions(self, task: Task) -> str:
        """Generate instructions for manual Jira issue creation.

        Returns:
            Markdown-formatted instructions.
        """
        priority = self.PRIORITY_MAP.get(task.priority, "Medium")

        description_parts = [task.description]

        if task.requirement_id:
            description_parts.append(f"\n**Requirement:** {task.requirement_id}")

        if task.files_to_modify:
            description_parts.append("\n**Files to Modify:**")
            for f in task.files_to_modify:
                description_parts.append(f"- `{f}`")

        if task.implementation_steps:
            description_parts.append("\n**Implementation Steps:**")
            for i, step in enumerate(task.implementation_steps, 1):
                description_parts.append(f"{i}. {step}")

        description = "\n".join(description_parts)

        return f"""## Create Jira Issue

**To create this task in Jira:**

```
Project: {self.project_key}
Type: {self.issue_type}
Summary: {task.title}
Priority: {priority}
```

**Description:**

{description}

---

After creating the issue, link it with:
```
/sdlc:task link {task.id} <JIRA-ISSUE-KEY>
```
"""
