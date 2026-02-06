"""
External sync service for a-sdlc.

Handles synchronization between local hybrid storage (SQLite + markdown files)
and external systems like Linear and Jira.
"""

from typing import Any

import httpx

from a_sdlc.core.database import Database
from a_sdlc.core.content import ContentManager


class LinearClient:
    """Client for Linear GraphQL API."""

    API_URL = "https://api.linear.app/graphql"

    # Map local status to Linear state names
    STATUS_TO_LINEAR = {
        "pending": "Backlog",
        "in_progress": "In Progress",
        "blocked": "Blocked",
        "completed": "Done",
    }

    # Map Linear states to local status
    LINEAR_TO_STATUS = {
        "Backlog": "pending",
        "Todo": "pending",
        "In Progress": "in_progress",
        "In Review": "in_progress",
        "Blocked": "blocked",
        "Done": "completed",
        "Canceled": "completed",
    }

    # Map local priority to Linear (1=urgent, 4=low)
    PRIORITY_TO_LINEAR = {
        "critical": 1,
        "high": 2,
        "medium": 3,
        "low": 4,
    }

    def __init__(self, api_key: str, team_id: str):
        """Initialize Linear client.

        Args:
            api_key: Linear API key
            team_id: Team identifier
        """
        self.api_key = api_key
        self.team_id = team_id
        self._client = httpx.Client(
            headers={
                "Authorization": api_key,
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    def _query(self, query: str, variables: dict | None = None) -> dict:
        """Execute GraphQL query."""
        response = self._client.post(
            self.API_URL,
            json={"query": query, "variables": variables or {}},
        )
        response.raise_for_status()
        data = response.json()
        if "errors" in data:
            raise RuntimeError(f"Linear API error: {data['errors']}")
        return data.get("data", {})

    def list_cycles(self, status: str | None = None) -> list[dict]:
        """List cycles (sprints) for the team.

        Args:
            status: Filter by 'active', 'upcoming', or 'completed'

        Returns:
            List of cycle dicts
        """
        # Build filter based on status
        filter_clause = ""
        if status == "active":
            filter_clause = ', filter: { isActive: { eq: true } }'
        elif status == "upcoming":
            filter_clause = ', filter: { startsAt: { gt: "now" } }'
        elif status == "completed":
            filter_clause = ', filter: { completedAt: { neq: null } }'

        query = f"""
        query ListCycles($teamId: String!) {{
            team(id: $teamId) {{
                cycles(first: 50{filter_clause}) {{
                    nodes {{
                        id
                        name
                        number
                        startsAt
                        endsAt
                        progress
                        issues {{
                            nodes {{
                                id
                                identifier
                                title
                                state {{ name }}
                                priority
                            }}
                        }}
                    }}
                }}
            }}
        }}
        """
        data = self._query(query, {"teamId": self.team_id})
        return data.get("team", {}).get("cycles", {}).get("nodes", [])

    def get_active_cycle(self) -> dict | None:
        """Get the currently active cycle for the team.

        Returns:
            Active cycle dict, or None if no active cycle
        """
        cycles = self.list_cycles(status="active")
        return cycles[0] if cycles else None

    def get_issue_with_children(self, issue_id: str) -> dict | None:
        """Get issue details with children (sub-issues).

        Args:
            issue_id: Linear issue ID

        Returns:
            Issue dict with children populated
        """
        query = """
        query GetIssueWithChildren($id: String!) {
            issue(id: $id) {
                id
                identifier
                title
                description
                state { name }
                priority
                children {
                    nodes {
                        id
                        identifier
                        title
                        state { name }
                    }
                }
            }
        }
        """
        data = self._query(query, {"id": issue_id})
        return data.get("issue")

    def get_cycle(self, cycle_id: str) -> dict | None:
        """Get cycle details with issues."""
        query = """
        query GetCycle($id: String!) {
            cycle(id: $id) {
                id
                name
                number
                startsAt
                endsAt
                progress
                issues {
                    nodes {
                        id
                        identifier
                        title
                        description
                        state { name }
                        priority
                        estimate
                        labels { nodes { name } }
                    }
                }
            }
        }
        """
        data = self._query(query, {"id": cycle_id})
        return data.get("cycle")

    def create_issue(
        self,
        title: str,
        description: str = "",
        priority: int = 3,
        cycle_id: str | None = None,
        labels: list[str] | None = None,
    ) -> dict:
        """Create a new issue in Linear.

        Returns:
            Created issue dict with id and identifier
        """
        mutation = """
        mutation CreateIssue($input: IssueCreateInput!) {
            issueCreate(input: $input) {
                success
                issue {
                    id
                    identifier
                    title
                    url
                }
            }
        }
        """
        input_data: dict[str, Any] = {
            "teamId": self.team_id,
            "title": title,
            "description": description,
            "priority": priority,
        }
        if cycle_id:
            input_data["cycleId"] = cycle_id
        if labels:
            input_data["labelIds"] = labels

        data = self._query(mutation, {"input": input_data})
        result = data.get("issueCreate", {})
        if not result.get("success"):
            raise RuntimeError("Failed to create Linear issue")
        return result.get("issue", {})

    def update_issue(
        self,
        issue_id: str,
        title: str | None = None,
        description: str | None = None,
        state_name: str | None = None,
        priority: int | None = None,
    ) -> dict:
        """Update an existing issue."""
        # First, get state ID if state_name provided
        state_id = None
        if state_name:
            states_query = """
            query GetStates($teamId: String!) {
                team(id: $teamId) {
                    states { nodes { id name } }
                }
            }
            """
            states_data = self._query(states_query, {"teamId": self.team_id})
            states = states_data.get("team", {}).get("states", {}).get("nodes", [])
            for state in states:
                if state["name"].lower() == state_name.lower():
                    state_id = state["id"]
                    break

        mutation = """
        mutation UpdateIssue($id: String!, $input: IssueUpdateInput!) {
            issueUpdate(id: $id, input: $input) {
                success
                issue {
                    id
                    identifier
                    state { name }
                }
            }
        }
        """
        input_data: dict[str, Any] = {}
        if title:
            input_data["title"] = title
        if description:
            input_data["description"] = description
        if state_id:
            input_data["stateId"] = state_id
        if priority is not None:
            input_data["priority"] = priority

        if not input_data:
            return {}

        data = self._query(mutation, {"id": issue_id, "input": input_data})
        return data.get("issueUpdate", {}).get("issue", {})


class JiraClient:
    """Client for Jira REST API v3."""

    # Map local status to Jira transitions
    STATUS_TO_JIRA = {
        "pending": "To Do",
        "in_progress": "In Progress",
        "blocked": "Blocked",
        "completed": "Done",
    }

    # Map Jira states to local status
    JIRA_TO_STATUS = {
        "To Do": "pending",
        "Backlog": "pending",
        "Open": "pending",
        "In Progress": "in_progress",
        "In Review": "in_progress",
        "Blocked": "blocked",
        "On Hold": "blocked",
        "Done": "completed",
        "Closed": "completed",
        "Resolved": "completed",
    }

    # Map local priority to Jira
    PRIORITY_TO_JIRA = {
        "critical": "Highest",
        "high": "High",
        "medium": "Medium",
        "low": "Low",
    }

    def __init__(self, base_url: str, email: str, api_token: str, project_key: str):
        """Initialize Jira client."""
        self.base_url = base_url.rstrip("/")
        self.project_key = project_key
        self._client = httpx.Client(
            auth=(email, api_token),
            headers={"Content-Type": "application/json"},
            timeout=30.0,
        )

    def _get(self, path: str, params: dict | None = None) -> dict:
        """GET request to Jira API."""
        response = self._client.get(
            f"{self.base_url}/rest/api/3{path}",
            params=params,
        )
        response.raise_for_status()
        return response.json()

    def _post(self, path: str, data: dict) -> dict:
        """POST request to Jira API."""
        response = self._client.post(
            f"{self.base_url}/rest/api/3{path}",
            json=data,
        )
        response.raise_for_status()
        return response.json()

    def list_sprints(self, board_id: str, state: str | None = None) -> list[dict]:
        """List sprints for a board.

        Args:
            board_id: Jira board ID
            state: Filter by 'active', 'future', or 'closed'
        """
        params: dict[str, Any] = {"maxResults": 50}
        if state:
            params["state"] = state

        # Sprints are in the agile API
        response = self._client.get(
            f"{self.base_url}/rest/agile/1.0/board/{board_id}/sprint",
            params=params,
        )
        response.raise_for_status()
        return response.json().get("values", [])

    def get_sprint(self, sprint_id: str) -> dict | None:
        """Get sprint details."""
        response = self._client.get(
            f"{self.base_url}/rest/agile/1.0/sprint/{sprint_id}",
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    def get_sprint_issues(self, sprint_id: str) -> list[dict]:
        """Get all issues in a sprint."""
        jql = f"sprint = {sprint_id}"
        return self.search_issues(jql)

    def search_issues(self, jql: str, max_results: int = 100) -> list[dict]:
        """Search issues with JQL."""
        data = self._get(
            "/search/jql",
            params={
                "jql": jql,
                "maxResults": max_results,
                "fields": "summary,description,status,priority,components,labels,created,updated",
            },
        )
        return data.get("issues", [])

    def get_issue_with_subtasks(self, issue_key: str) -> dict:
        """Get issue with subtasks expanded.

        Args:
            issue_key: The Jira issue key (e.g., 'PROJ-123')

        Returns:
            Issue dict with subtasks field populated
        """
        return self._get(
            f"/issue/{issue_key}",
            params={
                "fields": "summary,description,status,priority,subtasks",
            },
        )

    def get_subtask_details(self, subtask_keys: list[str]) -> list[dict]:
        """Get details for multiple subtasks.

        Args:
            subtask_keys: List of subtask issue keys

        Returns:
            List of subtask issue dicts
        """
        if not subtask_keys:
            return []

        # Use JQL to fetch all subtasks in one call
        jql = f"key in ({','.join(subtask_keys)})"
        return self.search_issues(jql, max_results=len(subtask_keys))

    def get_active_sprint(self, board_id: str) -> dict | None:
        """Get the currently active sprint for a board.

        Args:
            board_id: Jira board ID

        Returns:
            Active sprint dict, or None if no active sprint
        """
        sprints = self.list_sprints(board_id, state="active")
        return sprints[0] if sprints else None

    def create_issue(
        self,
        summary: str,
        description: str = "",
        issue_type: str = "Task",
        priority: str = "Medium",
        sprint_id: str | None = None,
    ) -> dict:
        """Create a new issue."""
        fields: dict[str, Any] = {
            "project": {"key": self.project_key},
            "summary": summary,
            "issuetype": {"name": issue_type},
            "priority": {"name": priority},
        }

        # Description in ADF format
        if description:
            fields["description"] = {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": description}],
                    }
                ],
            }

        issue = self._post("/issue", {"fields": fields})

        # Add to sprint if specified (requires separate call)
        if sprint_id and issue.get("key"):
            try:
                self._client.post(
                    f"{self.base_url}/rest/agile/1.0/sprint/{sprint_id}/issue",
                    json={"issues": [issue["key"]]},
                )
            except Exception:
                pass  # Sprint assignment is optional

        return issue

    def update_issue(self, issue_key: str, fields: dict) -> None:
        """Update issue fields."""
        response = self._client.put(
            f"{self.base_url}/rest/api/3/issue/{issue_key}",
            json={"fields": fields},
        )
        response.raise_for_status()

    def transition_issue(self, issue_key: str, target_status: str) -> bool:
        """Transition issue to a new status.

        Returns:
            True if transition succeeded, False if no matching transition found.
        """
        # Get available transitions
        transitions_resp = self._get(f"/issue/{issue_key}/transitions")
        transitions = transitions_resp.get("transitions", [])

        # Find matching transition
        target_lower = target_status.lower()
        for t in transitions:
            if t.get("to", {}).get("name", "").lower() == target_lower:
                self._post(
                    f"/issue/{issue_key}/transitions",
                    {"transition": {"id": t["id"]}},
                )
                return True
        return False


class ExternalSyncService:
    """Handles sync operations between local and external systems."""

    def __init__(self, db: Database, content_mgr: ContentManager):
        """Initialize sync service.

        Args:
            db: Database instance for metadata
            content_mgr: ContentManager instance for file operations
        """
        self.db = db
        self.content_mgr = content_mgr

    def _check_existing_sprint_mapping(
        self,
        project_id: str,
        external_system: str,
        external_id: str,
    ) -> dict[str, Any] | None:
        """Check if a sprint mapping already exists for the given external ID.

        Args:
            project_id: Local project ID
            external_system: External system name ('linear' or 'jira')
            external_id: External sprint/cycle ID

        Returns:
            Dict with existing sprint info and mapping if found, None otherwise.
            If mapping exists but local sprint is missing (orphaned), cleans up
            the mapping and returns None.
        """
        mapping = self.db.get_sync_mapping_by_external(
            "sprint", external_system, external_id
        )

        if not mapping:
            return None

        local_sprint = self.db.get_sprint(mapping["local_id"])
        if not local_sprint:
            # Orphaned mapping - clean up
            self.db.delete_sync_mapping("sprint", mapping["local_id"], external_system)
            return None

        return {
            "existing_sprint": local_sprint,
            "mapping": mapping,
            "external_system": external_system,
            "external_id": external_id,
        }

    def _get_linear_client(self, project_id: str) -> LinearClient:
        """Get configured Linear client for project."""
        config = self.db.get_external_config(project_id, "linear")
        if not config:
            raise RuntimeError(
                "Linear not configured. Run: a-sdlc connect linear"
            )
        cfg = config["config"]
        return LinearClient(cfg["api_key"], cfg["team_id"])

    def _get_jira_client(self, project_id: str) -> JiraClient:
        """Get configured Jira client for project."""
        config = self.db.get_external_config(project_id, "jira")
        if not config:
            raise RuntimeError(
                "Jira not configured. Run: a-sdlc connect jira"
            )
        cfg = config["config"]
        return JiraClient(
            cfg["base_url"],
            cfg["email"],
            cfg["api_token"],
            cfg["project_key"],
        )

    # =========================================================================
    # Linear Sync Operations
    # =========================================================================

    def import_linear_cycle(
        self, project_id: str, cycle_id: str
    ) -> dict[str, Any]:
        """Import a Linear cycle as a local sprint with PRDs.

        Linear issues are imported as PRDs (with subtasks appended
        to the PRD description). Each PRD is assigned to the sprint.

        Args:
            project_id: Local project ID
            cycle_id: Linear cycle ID

        Returns:
            Dict with sprint and PRDs info, or already_exists status if
            this cycle was previously imported.
        """
        # Check for existing mapping before making API call
        existing = self._check_existing_sprint_mapping(project_id, "linear", cycle_id)
        if existing:
            return {
                "status": "already_exists",
                "existing_sprint": existing["existing_sprint"],
                "mapping": existing["mapping"],
                "external_system": "linear",
                "external_id": cycle_id,
            }

        client = self._get_linear_client(project_id)
        cycle = client.get_cycle(cycle_id)

        if not cycle:
            raise RuntimeError(f"Cycle not found: {cycle_id}")

        # Create local sprint
        sprint_id = self.db.get_next_sprint_id(project_id)
        sprint = self.db.create_sprint(
            sprint_id=sprint_id,
            project_id=project_id,
            title=cycle.get("name", f"Cycle {cycle.get('number', '')}"),
            goal=f"Imported from Linear cycle {cycle_id}",
        )

        # Update sprint with external link
        self.db.update_sprint(
            sprint_id,
            external_id=cycle_id,
            external_url=f"https://linear.app/cycle/{cycle_id}",
        )

        # Create sync mapping
        self.db.create_sync_mapping(
            entity_type="sprint",
            local_id=sprint_id,
            external_system="linear",
            external_id=cycle_id,
        )

        # Import issues as PRDs
        prds_created = []
        issues = cycle.get("issues", {}).get("nodes", [])

        for issue in issues:
            # Map Linear state to PRD status
            state_name = issue.get("state", {}).get("name", "Backlog")
            linear_status = LinearClient.LINEAR_TO_STATUS.get(state_name, "pending")
            # Map to PRD status
            if linear_status == "completed":
                prd_status = "split"  # Completed issues are "done"
            elif linear_status in ("in_progress", "blocked"):
                prd_status = "ready"  # Active work
            else:
                prd_status = "draft"

            # Build PRD content from issue
            content = issue.get("description", "") or ""
            labels = issue.get("labels", {}).get("nodes", [])
            if labels:
                label_names = [label.get("name", "") for label in labels]
                content += f"\n\n**Labels**: {', '.join(label_names)}"

            # Fetch and append sub-issues (children)
            children_content = self._fetch_and_format_linear_children(
                client, issue.get("id", "")
            )
            if children_content:
                content += children_content

            # Create PRD with sprint assignment
            prd_id = self.db.get_next_prd_id(project_id)

            # Write content file
            file_path = self.content_mgr.write_prd(
                project_id=project_id,
                prd_id=prd_id,
                title=issue.get("title", "Untitled"),
                content=content,
            )

            # Register in database
            prd = self.db.create_prd(
                prd_id=prd_id,
                project_id=project_id,
                title=issue.get("title", "Untitled"),
                file_path=str(file_path),
                status=prd_status,
                source=f"linear:{issue.get('identifier', issue.get('id'))}",
                sprint_id=sprint_id,
            )

            # Create sync mapping for PRD
            self.db.create_sync_mapping(
                entity_type="prd",
                local_id=prd_id,
                external_system="linear",
                external_id=issue.get("id"),
            )

            prds_created.append(prd)

        return {
            "sprint": sprint,
            "prds_count": len(prds_created),
            "prds": prds_created,
            # Legacy field for backward compatibility
            "tasks_count": len(prds_created),
        }

    def _fetch_and_format_linear_children(
        self, client: LinearClient, issue_id: str
    ) -> str:
        """Fetch children (sub-issues) for an issue and format as markdown checklist.

        Args:
            client: LinearClient instance
            issue_id: The parent Linear issue ID

        Returns:
            Markdown formatted sub-issues section, or empty string if no children
        """
        if not issue_id:
            return ""

        try:
            issue = client.get_issue_with_children(issue_id)
            if not issue:
                return ""

            children = issue.get("children", {}).get("nodes", [])

            if not children:
                return ""

            # Format as markdown checklist
            lines = ["\n\n## Sub-issues"]
            for child in children:
                identifier = child.get("identifier", "")
                title = child.get("title", "Untitled")
                state_name = child.get("state", {}).get("name", "Backlog")

                # Check if completed
                is_done = state_name.lower() in ("done", "canceled", "completed")
                checkbox = "[x]" if is_done else "[ ]"

                lines.append(f"- {checkbox} [{identifier}] {title} ({state_name})")

            return "\n".join(lines)

        except Exception:
            # If children fetching fails, just skip it
            return ""

    def import_linear_active_cycle(self, project_id: str) -> dict[str, Any]:
        """Import the active cycle from Linear.

        Args:
            project_id: Local project ID

        Returns:
            Dict with sprint and PRDs info

        Raises:
            RuntimeError: If no active cycle found for the team
        """
        client = self._get_linear_client(project_id)
        cycle = client.get_active_cycle()

        if not cycle:
            raise RuntimeError("No active cycle found for this team")

        return self.import_linear_cycle(project_id, cycle["id"])

    def sync_sprint_to_linear(
        self, project_id: str, sprint_id: str
    ) -> dict[str, Any]:
        """Push local sprint PRDs to Linear cycle as issues.

        Args:
            project_id: Local project ID
            sprint_id: Local sprint ID

        Returns:
            Sync result with changes made
        """
        client = self._get_linear_client(project_id)
        sprint = self.db.get_sprint(sprint_id)

        if not sprint:
            raise RuntimeError(f"Sprint not found: {sprint_id}")

        # Get external mapping
        mapping = self.db.get_sync_mapping("sprint", sprint_id, "linear")
        if not mapping:
            raise RuntimeError(
                f"Sprint {sprint_id} is not linked to a Linear cycle. "
                "Use link_sprint to connect it first."
            )

        cycle_id = mapping["external_id"]
        prds = self.db.get_sprint_prds(sprint_id)

        results = {
            "sprint_id": sprint_id,
            "cycle_id": cycle_id,
            "prds_updated": 0,
            "prds_created": 0,
            "errors": [],
        }

        for prd in prds:
            prd_mapping = self.db.get_sync_mapping("prd", prd["id"], "linear")

            # Map PRD status to Linear state
            prd_status = prd.get("status", "draft")
            if prd_status == "split":
                linear_state = "Done"
            elif prd_status == "ready":
                linear_state = "In Progress"
            else:
                linear_state = "Backlog"

            # Read content from file
            content = ""
            if prd.get("file_path"):
                content = self.content_mgr.read_content(prd["file_path"]) or ""

            try:
                if prd_mapping:
                    # Update existing issue
                    client.update_issue(
                        prd_mapping["external_id"],
                        title=prd["title"],
                        description=content,
                        state_name=linear_state,
                    )
                    self.db.update_sync_mapping(
                        "prd", prd["id"], "linear", sync_status="synced"
                    )
                    results["prds_updated"] += 1
                else:
                    # Create new issue
                    issue = client.create_issue(
                        title=prd["title"],
                        description=content,
                        priority=3,  # Default medium
                        cycle_id=cycle_id,
                    )
                    self.db.create_sync_mapping(
                        entity_type="prd",
                        local_id=prd["id"],
                        external_system="linear",
                        external_id=issue["id"],
                    )
                    results["prds_created"] += 1

            except Exception as e:
                results["errors"].append(f"PRD {prd['id']}: {e}")

        # Update sprint sync status
        self.db.update_sync_mapping(
            "sprint", sprint_id, "linear", sync_status="synced"
        )

        return results

    def sync_sprint_from_linear(
        self, project_id: str, sprint_id: str
    ) -> dict[str, Any]:
        """Pull Linear cycle changes to local sprint as PRDs.

        Args:
            project_id: Local project ID
            sprint_id: Local sprint ID

        Returns:
            Sync result with changes
        """
        client = self._get_linear_client(project_id)
        sprint = self.db.get_sprint(sprint_id)

        if not sprint:
            raise RuntimeError(f"Sprint not found: {sprint_id}")

        mapping = self.db.get_sync_mapping("sprint", sprint_id, "linear")
        if not mapping:
            raise RuntimeError(f"Sprint {sprint_id} is not linked to a Linear cycle")

        cycle_id = mapping["external_id"]
        cycle = client.get_cycle(cycle_id)

        if not cycle:
            raise RuntimeError(f"Linear cycle not found: {cycle_id}")

        results = {
            "sprint_id": sprint_id,
            "cycle_id": cycle_id,
            "prds_updated": 0,
            "prds_created": 0,
            "errors": [],
        }

        issues = cycle.get("issues", {}).get("nodes", [])

        for issue in issues:
            # Check if we have a mapping for this issue
            prd_mapping = self.db.get_sync_mapping_by_external(
                "prd", "linear", issue["id"]
            )

            # Map Linear state to PRD status
            state_name = issue.get("state", {}).get("name", "Backlog")
            linear_status = LinearClient.LINEAR_TO_STATUS.get(state_name, "pending")
            if linear_status == "completed":
                prd_status = "split"
            elif linear_status in ("in_progress", "blocked"):
                prd_status = "ready"
            else:
                prd_status = "draft"

            try:
                if prd_mapping:
                    # Update existing PRD
                    prd_id = prd_mapping["local_id"]

                    # Update content file
                    self.content_mgr.write_prd(
                        project_id=project_id,
                        prd_id=prd_id,
                        title=issue.get("title", "Untitled"),
                        content=issue.get("description", ""),
                    )

                    # Update database
                    self.db.update_prd(
                        prd_id,
                        title=issue.get("title", "Untitled"),
                        status=prd_status,
                    )
                    self.db.update_sync_mapping(
                        "prd", prd_id, "linear",
                        sync_status="synced"
                    )
                    results["prds_updated"] += 1
                else:
                    # Create new PRD
                    prd_id = self.db.get_next_prd_id(project_id)

                    # Write content file
                    file_path = self.content_mgr.write_prd(
                        project_id=project_id,
                        prd_id=prd_id,
                        title=issue.get("title", "Untitled"),
                        content=issue.get("description", ""),
                    )

                    # Register in database
                    self.db.create_prd(
                        prd_id=prd_id,
                        project_id=project_id,
                        title=issue.get("title", "Untitled"),
                        file_path=str(file_path),
                        status=prd_status,
                        source=f"linear:{issue.get('identifier', issue.get('id'))}",
                        sprint_id=sprint_id,
                    )
                    self.db.create_sync_mapping(
                        entity_type="prd",
                        local_id=prd_id,
                        external_system="linear",
                        external_id=issue["id"],
                    )
                    results["prds_created"] += 1

            except Exception as e:
                results["errors"].append(f"Issue {issue.get('identifier', issue['id'])}: {e}")

        self.db.update_sync_mapping(
            "sprint", sprint_id, "linear", sync_status="synced"
        )

        return results

    # =========================================================================
    # Jira Sync Operations
    # =========================================================================

    def import_jira_sprint(
        self, project_id: str, sprint_id: str, board_id: str | None = None
    ) -> dict[str, Any]:
        """Import a Jira sprint with issues as PRDs.

        Jira issues are imported as PRDs (with subtasks appended
        to the PRD description). Each PRD is assigned to the sprint.

        Args:
            project_id: Local project ID
            sprint_id: Jira sprint ID
            board_id: Jira board ID (optional, for listing)

        Returns:
            Dict with sprint and PRDs info, or already_exists status if
            this sprint was previously imported.
        """
        # Check for existing mapping before making API call
        existing = self._check_existing_sprint_mapping(project_id, "jira", sprint_id)
        if existing:
            return {
                "status": "already_exists",
                "existing_sprint": existing["existing_sprint"],
                "mapping": existing["mapping"],
                "external_system": "jira",
                "external_id": sprint_id,
            }

        client = self._get_jira_client(project_id)
        jira_sprint = client.get_sprint(sprint_id)

        if not jira_sprint:
            raise RuntimeError(f"Jira sprint not found: {sprint_id}")

        # Create local sprint
        local_sprint_id = self.db.get_next_sprint_id(project_id)
        sprint = self.db.create_sprint(
            sprint_id=local_sprint_id,
            project_id=project_id,
            title=jira_sprint.get("name", f"Sprint {sprint_id}"),
            goal=jira_sprint.get("goal", ""),
        )

        # Update with external link
        jira_url = client.base_url
        self.db.update_sprint(
            local_sprint_id,
            external_id=sprint_id,
            external_url=f"{jira_url}/secure/RapidBoard.jspa?sprint={sprint_id}",
        )

        # Create sync mapping
        self.db.create_sync_mapping(
            entity_type="sprint",
            local_id=local_sprint_id,
            external_system="jira",
            external_id=sprint_id,
        )

        # Import issues as PRDs
        issues = client.get_sprint_issues(sprint_id)
        prds_created = []

        for issue in issues:
            fields = issue.get("fields", {})

            # Map Jira status to PRD status
            status_name = fields.get("status", {}).get("name", "To Do")
            jira_status = JiraClient.JIRA_TO_STATUS.get(status_name, "pending")
            if jira_status == "completed":
                prd_status = "split"
            elif jira_status in ("in_progress", "blocked"):
                prd_status = "ready"
            else:
                prd_status = "draft"

            # Build PRD content
            content = self._extract_jira_description(fields.get("description"))
            labels = fields.get("labels", [])
            if labels:
                content += f"\n\n**Labels**: {', '.join(labels)}"

            # Fetch and append subtasks
            subtasks_content = self._fetch_and_format_subtasks(client, issue["key"])
            if subtasks_content:
                content += subtasks_content

            # Create PRD with sprint assignment
            prd_id = self.db.get_next_prd_id(project_id)

            # Write content file
            file_path = self.content_mgr.write_prd(
                project_id=project_id,
                prd_id=prd_id,
                title=fields.get("summary", "Untitled"),
                content=content,
            )

            # Register in database
            prd = self.db.create_prd(
                prd_id=prd_id,
                project_id=project_id,
                title=fields.get("summary", "Untitled"),
                file_path=str(file_path),
                status=prd_status,
                source=f"jira:{issue['key']}",
                sprint_id=local_sprint_id,
            )

            # Create sync mapping
            self.db.create_sync_mapping(
                entity_type="prd",
                local_id=prd_id,
                external_system="jira",
                external_id=issue["key"],
            )

            prds_created.append(prd)

        return {
            "sprint": sprint,
            "prds_count": len(prds_created),
            "prds": prds_created,
            # Legacy field for backward compatibility
            "tasks_count": len(prds_created),
        }

    def _extract_jira_description(self, adf: dict | None) -> str:
        """Extract plain text from Jira ADF description."""
        if not adf or not isinstance(adf, dict):
            return ""

        texts = []

        def extract(node: dict) -> None:
            if node.get("type") == "text":
                texts.append(node.get("text", ""))
            for child in node.get("content", []):
                if isinstance(child, dict):
                    extract(child)

        extract(adf)
        return " ".join(texts)

    def _fetch_and_format_subtasks(
        self, client: JiraClient, issue_key: str
    ) -> str:
        """Fetch subtasks for an issue and format as markdown checklist.

        Args:
            client: JiraClient instance
            issue_key: The parent issue key (e.g., 'PROJ-123')

        Returns:
            Markdown formatted subtasks section, or empty string if no subtasks
        """
        try:
            issue = client.get_issue_with_subtasks(issue_key)
            subtasks = issue.get("fields", {}).get("subtasks", [])

            if not subtasks:
                return ""

            # Get subtask keys and fetch their full details
            subtask_keys = [st["key"] for st in subtasks]
            subtask_details = client.get_subtask_details(subtask_keys)

            # Create a lookup for status by key
            status_by_key: dict[str, str] = {}
            for detail in subtask_details:
                key = detail.get("key", "")
                status_name = (
                    detail.get("fields", {}).get("status", {}).get("name", "To Do")
                )
                status_by_key[key] = status_name

            # Format as markdown checklist
            lines = ["\n\n## Subtasks"]
            for subtask in subtasks:
                key = subtask.get("key", "")
                summary = subtask.get("fields", {}).get("summary", "Untitled")
                status = status_by_key.get(key, "To Do")

                # Check if completed
                is_done = status.lower() in ("done", "closed", "resolved", "completed")
                checkbox = "[x]" if is_done else "[ ]"

                lines.append(f"- {checkbox} [{key}] {summary} ({status})")

            return "\n".join(lines)

        except Exception:
            # If subtask fetching fails, just skip it
            return ""

    def import_jira_active_sprint(
        self, project_id: str, board_id: str
    ) -> dict[str, Any]:
        """Import the active sprint from a Jira board.

        Args:
            project_id: Local project ID
            board_id: Jira board ID

        Returns:
            Dict with sprint and PRDs info

        Raises:
            RuntimeError: If no active sprint found for the board
        """
        client = self._get_jira_client(project_id)
        sprint = client.get_active_sprint(board_id)

        if not sprint:
            raise RuntimeError(f"No active sprint found for board {board_id}")

        return self.import_jira_sprint(project_id, str(sprint["id"]), board_id)

    def sync_sprint_to_jira(
        self, project_id: str, sprint_id: str
    ) -> dict[str, Any]:
        """Push local sprint PRDs to Jira as issues."""
        client = self._get_jira_client(project_id)
        sprint = self.db.get_sprint(sprint_id)

        if not sprint:
            raise RuntimeError(f"Sprint not found: {sprint_id}")

        mapping = self.db.get_sync_mapping("sprint", sprint_id, "jira")
        if not mapping:
            raise RuntimeError(f"Sprint {sprint_id} is not linked to Jira")

        jira_sprint_id = mapping["external_id"]
        prds = self.db.get_sprint_prds(sprint_id)

        results = {
            "sprint_id": sprint_id,
            "jira_sprint_id": jira_sprint_id,
            "prds_updated": 0,
            "prds_created": 0,
            "errors": [],
        }

        for prd in prds:
            prd_mapping = self.db.get_sync_mapping("prd", prd["id"], "jira")

            # Map PRD status to Jira status
            prd_status = prd.get("status", "draft")
            if prd_status == "split":
                jira_status = "Done"
            elif prd_status == "ready":
                jira_status = "In Progress"
            else:
                jira_status = "To Do"

            # Read content from file
            content = ""
            if prd.get("file_path"):
                content = self.content_mgr.read_content(prd["file_path"]) or ""

            try:
                if prd_mapping:
                    # Update existing issue - transition status
                    client.transition_issue(
                        prd_mapping["external_id"], jira_status
                    )
                    # Also update summary if changed
                    client.update_issue(
                        prd_mapping["external_id"],
                        {"summary": prd["title"]}
                    )
                    self.db.update_sync_mapping(
                        "prd", prd["id"], "jira", sync_status="synced"
                    )
                    results["prds_updated"] += 1
                else:
                    # Create new issue
                    issue = client.create_issue(
                        summary=prd["title"],
                        description=content,
                        priority="Medium",
                        sprint_id=jira_sprint_id,
                    )
                    self.db.create_sync_mapping(
                        entity_type="prd",
                        local_id=prd["id"],
                        external_system="jira",
                        external_id=issue["key"],
                    )
                    results["prds_created"] += 1

            except Exception as e:
                results["errors"].append(f"PRD {prd['id']}: {e}")

        self.db.update_sync_mapping(
            "sprint", sprint_id, "jira", sync_status="synced"
        )

        return results

    def sync_sprint_from_jira(
        self, project_id: str, sprint_id: str
    ) -> dict[str, Any]:
        """Pull Jira sprint changes to local as PRDs."""
        client = self._get_jira_client(project_id)
        sprint = self.db.get_sprint(sprint_id)

        if not sprint:
            raise RuntimeError(f"Sprint not found: {sprint_id}")

        mapping = self.db.get_sync_mapping("sprint", sprint_id, "jira")
        if not mapping:
            raise RuntimeError(f"Sprint {sprint_id} is not linked to Jira")

        jira_sprint_id = mapping["external_id"]
        issues = client.get_sprint_issues(jira_sprint_id)

        results = {
            "sprint_id": sprint_id,
            "jira_sprint_id": jira_sprint_id,
            "prds_updated": 0,
            "prds_created": 0,
            "errors": [],
        }

        for issue in issues:
            prd_mapping = self.db.get_sync_mapping_by_external(
                "prd", "jira", issue["key"]
            )

            fields = issue.get("fields", {})
            status_name = fields.get("status", {}).get("name", "To Do")
            jira_status = JiraClient.JIRA_TO_STATUS.get(status_name, "pending")

            # Map to PRD status
            if jira_status == "completed":
                prd_status = "split"
            elif jira_status in ("in_progress", "blocked"):
                prd_status = "ready"
            else:
                prd_status = "draft"

            try:
                if prd_mapping:
                    prd_id = prd_mapping["local_id"]

                    # Update content file
                    self.content_mgr.write_prd(
                        project_id=project_id,
                        prd_id=prd_id,
                        title=fields.get("summary", "Untitled"),
                        content=self._extract_jira_description(fields.get("description")),
                    )

                    # Update database
                    self.db.update_prd(
                        prd_id,
                        title=fields.get("summary", "Untitled"),
                        status=prd_status,
                    )
                    self.db.update_sync_mapping(
                        "prd", prd_id, "jira",
                        sync_status="synced"
                    )
                    results["prds_updated"] += 1
                else:
                    prd_id = self.db.get_next_prd_id(project_id)

                    # Write content file
                    file_path = self.content_mgr.write_prd(
                        project_id=project_id,
                        prd_id=prd_id,
                        title=fields.get("summary", "Untitled"),
                        content=self._extract_jira_description(fields.get("description")),
                    )

                    # Register in database
                    self.db.create_prd(
                        prd_id=prd_id,
                        project_id=project_id,
                        title=fields.get("summary", "Untitled"),
                        file_path=str(file_path),
                        status=prd_status,
                        source=f"jira:{issue['key']}",
                        sprint_id=sprint_id,
                    )
                    self.db.create_sync_mapping(
                        entity_type="prd",
                        local_id=prd_id,
                        external_system="jira",
                        external_id=issue["key"],
                    )
                    results["prds_created"] += 1

            except Exception as e:
                results["errors"].append(f"Issue {issue['key']}: {e}")

        self.db.update_sync_mapping(
            "sprint", sprint_id, "jira", sync_status="synced"
        )

        return results

    # =========================================================================
    # Generic Operations
    # =========================================================================

    def link_sprint(
        self, project_id: str, sprint_id: str, system: str, external_id: str
    ) -> dict[str, Any]:
        """Link a local sprint to an external sprint/cycle.

        Args:
            project_id: Local project ID
            sprint_id: Local sprint ID
            system: External system ('linear' or 'jira')
            external_id: External sprint/cycle ID

        Returns:
            Created mapping
        """
        sprint = self.db.get_sprint(sprint_id)
        if not sprint:
            raise RuntimeError(f"Sprint not found: {sprint_id}")

        # Verify config exists
        config = self.db.get_external_config(project_id, system)
        if not config:
            raise RuntimeError(f"{system.title()} not configured for this project")

        # Create mapping
        mapping = self.db.create_sync_mapping(
            entity_type="sprint",
            local_id=sprint_id,
            external_system=system,
            external_id=external_id,
        )

        # Update sprint with external link
        if system == "linear":
            external_url = f"https://linear.app/cycle/{external_id}"
        else:
            base_url = config["config"].get("base_url", "")
            external_url = f"{base_url}/secure/RapidBoard.jspa?sprint={external_id}"

        self.db.update_sprint(
            sprint_id,
            external_id=external_id,
            external_url=external_url,
        )

        return mapping

    def unlink_sprint(self, sprint_id: str) -> bool:
        """Remove external system link from a sprint.

        Returns:
            True if unlinked, False if no link existed.
        """
        sprint = self.db.get_sprint(sprint_id)
        if not sprint:
            raise RuntimeError(f"Sprint not found: {sprint_id}")

        # Try both systems
        deleted_linear = self.db.delete_sync_mapping("sprint", sprint_id, "linear")
        deleted_jira = self.db.delete_sync_mapping("sprint", sprint_id, "jira")

        if deleted_linear or deleted_jira:
            # Clear external fields on sprint
            self.db.update_sprint(
                sprint_id,
                external_id=None,
                external_url=None,
            )
            return True

        return False

    def bidirectional_sync(
        self,
        project_id: str,
        sprint_id: str,
        strategy: str = "local-wins",
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Bidirectional sync between local and external.

        Args:
            project_id: Local project ID
            sprint_id: Local sprint ID
            strategy: Conflict resolution ('local-wins' or 'external-wins')
            dry_run: If True, only report what would change

        Returns:
            Sync results
        """
        # Determine which system the sprint is linked to
        linear_mapping = self.db.get_sync_mapping("sprint", sprint_id, "linear")
        jira_mapping = self.db.get_sync_mapping("sprint", sprint_id, "jira")

        if not linear_mapping and not jira_mapping:
            raise RuntimeError(
                f"Sprint {sprint_id} is not linked to any external system"
            )

        system = "linear" if linear_mapping else "jira"

        if dry_run:
            return {
                "status": "dry_run",
                "sprint_id": sprint_id,
                "system": system,
                "strategy": strategy,
                "message": f"Would sync with {system} using {strategy} strategy",
            }

        # Pull first, then push (strategy determines conflict resolution)
        if strategy == "external-wins":
            # Pull from external first (their changes win)
            if system == "linear":
                pull_result = self.sync_sprint_from_linear(project_id, sprint_id)
            else:
                pull_result = self.sync_sprint_from_jira(project_id, sprint_id)

            # Then push any new local tasks
            if system == "linear":
                push_result = self.sync_sprint_to_linear(project_id, sprint_id)
            else:
                push_result = self.sync_sprint_to_jira(project_id, sprint_id)
        else:
            # Local wins: push first, then pull new items
            if system == "linear":
                push_result = self.sync_sprint_to_linear(project_id, sprint_id)
                pull_result = self.sync_sprint_from_linear(project_id, sprint_id)
            else:
                push_result = self.sync_sprint_to_jira(project_id, sprint_id)
                pull_result = self.sync_sprint_from_jira(project_id, sprint_id)

        return {
            "status": "synced",
            "sprint_id": sprint_id,
            "system": system,
            "strategy": strategy,
            "pull": pull_result,
            "push": push_result,
        }

    # =========================================================================
    # PRD-Level Operations
    # =========================================================================

    def link_prd(
        self, project_id: str, prd_id: str, system: str, external_id: str
    ) -> dict[str, Any]:
        """Link a local PRD to an external issue.

        Args:
            project_id: Local project ID
            prd_id: Local PRD ID
            system: External system ('linear' or 'jira')
            external_id: External issue ID/key (e.g., 'PROJ-123')

        Returns:
            Created mapping
        """
        prd = self.db.get_prd(prd_id)
        if not prd:
            raise RuntimeError(f"PRD not found: {prd_id}")

        # Verify config exists
        config = self.db.get_external_config(project_id, system)
        if not config:
            raise RuntimeError(f"{system.title()} not configured for this project")

        # Create mapping
        mapping = self.db.create_sync_mapping(
            entity_type="prd",
            local_id=prd_id,
            external_system=system,
            external_id=external_id,
        )

        return mapping

    def unlink_prd(self, prd_id: str) -> bool:
        """Remove external system link from a PRD.

        Returns:
            True if unlinked, False if no link existed.
        """
        prd = self.db.get_prd(prd_id)
        if not prd:
            raise RuntimeError(f"PRD not found: {prd_id}")

        deleted_linear = self.db.delete_sync_mapping("prd", prd_id, "linear")
        deleted_jira = self.db.delete_sync_mapping("prd", prd_id, "jira")

        return deleted_linear or deleted_jira

    def sync_prd_to_jira(self, project_id: str, prd_id: str) -> dict[str, Any]:
        """Push a single PRD to its linked Jira issue.

        Returns:
            Sync result with update/create status
        """
        client = self._get_jira_client(project_id)
        prd = self.db.get_prd(prd_id)

        if not prd:
            raise RuntimeError(f"PRD not found: {prd_id}")

        prd_mapping = self.db.get_sync_mapping("prd", prd_id, "jira")

        # Map PRD status to Jira status
        prd_status = prd.get("status", "draft")
        if prd_status == "split":
            jira_status = "Done"
        elif prd_status == "ready":
            jira_status = "In Progress"
        else:
            jira_status = "To Do"

        # Read content from file
        content = ""
        if prd.get("file_path"):
            content = self.content_mgr.read_content(prd["file_path"]) or ""

        if prd_mapping:
            # Update existing issue
            client.transition_issue(prd_mapping["external_id"], jira_status)
            client.update_issue(
                prd_mapping["external_id"],
                {"summary": prd["title"], "description": content}
            )
            self.db.update_sync_mapping("prd", prd_id, "jira", sync_status="synced")

            return {
                "action": "updated",
                "prd_id": prd_id,
                "jira_key": prd_mapping["external_id"],
            }
        else:
            raise RuntimeError(
                f"PRD {prd_id} is not linked to Jira. Use link_prd first."
            )

    def sync_prd_from_jira(self, project_id: str, prd_id: str) -> dict[str, Any]:
        """Pull changes from linked Jira issue to PRD.

        Returns:
            Sync result with update status
        """
        client = self._get_jira_client(project_id)
        prd = self.db.get_prd(prd_id)

        if not prd:
            raise RuntimeError(f"PRD not found: {prd_id}")

        prd_mapping = self.db.get_sync_mapping("prd", prd_id, "jira")

        if not prd_mapping:
            raise RuntimeError(
                f"PRD {prd_id} is not linked to Jira. Use link_prd first."
            )

        # Fetch issue from Jira
        issues = client.search_issues(f"key = {prd_mapping['external_id']}", max_results=1)
        if not issues:
            raise RuntimeError(f"Jira issue not found: {prd_mapping['external_id']}")

        issue = issues[0]
        fields = issue.get("fields", {})

        # Map Jira status to PRD status
        jira_status = fields.get("status", {}).get("name", "To Do")
        if jira_status in ("Done", "Closed", "Resolved"):
            prd_status = "split"
        elif jira_status == "In Progress":
            prd_status = "ready"
        else:
            prd_status = "draft"

        # Update PRD
        self.db.update_prd(
            prd_id,
            title=fields.get("summary", prd["title"]),
            status=prd_status,
        )

        # Update content file if description changed
        description = self._extract_jira_description(fields.get("description"))
        if description and prd.get("file_path"):
            self.content_mgr.write_prd(
                project_id=project_id,
                prd_id=prd_id,
                title=fields.get("summary", prd["title"]),
                content=description,
            )

        self.db.update_sync_mapping("prd", prd_id, "jira", sync_status="synced")

        return {
            "action": "updated",
            "prd_id": prd_id,
            "jira_key": prd_mapping["external_id"],
            "status": prd_status,
        }

    def bidirectional_sync_prd(
        self,
        project_id: str,
        prd_id: str,
        strategy: str = "local-wins",
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Bidirectional sync between local PRD and external issue.

        Args:
            project_id: Local project ID
            prd_id: Local PRD ID
            strategy: Conflict resolution ('local-wins' or 'external-wins')
            dry_run: If True, only report what would change

        Returns:
            Sync results
        """
        linear_mapping = self.db.get_sync_mapping("prd", prd_id, "linear")
        jira_mapping = self.db.get_sync_mapping("prd", prd_id, "jira")

        if not linear_mapping and not jira_mapping:
            raise RuntimeError(f"PRD {prd_id} is not linked to any external system")

        system = "linear" if linear_mapping else "jira"

        if dry_run:
            return {
                "status": "dry_run",
                "prd_id": prd_id,
                "system": system,
                "strategy": strategy,
            }

        if system == "jira":
            if strategy == "external-wins":
                pull_result = self.sync_prd_from_jira(project_id, prd_id)
                push_result = self.sync_prd_to_jira(project_id, prd_id)
            else:
                push_result = self.sync_prd_to_jira(project_id, prd_id)
                pull_result = self.sync_prd_from_jira(project_id, prd_id)
        else:
            # Linear support would go here
            raise RuntimeError("Linear PRD sync not yet implemented")

        return {
            "status": "synced",
            "prd_id": prd_id,
            "system": system,
            "strategy": strategy,
            "pull": pull_result,
            "push": push_result,
        }
