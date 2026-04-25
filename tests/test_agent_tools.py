"""Tests for agent governance MCP tools.

Tests all merged MCP tool functions using mocks for the database and project context.
"""

from unittest.mock import MagicMock, patch

import pytest

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_db():
    """Mock the database singleton returned by get_db()."""
    with patch("a_sdlc.server.get_db") as mock:
        db = MagicMock()
        mock.return_value = db
        yield db


@pytest.fixture
def mock_project_id():
    """Mock _get_current_project_id to return a test project ID."""
    with patch("a_sdlc.server._get_current_project_id") as mock:
        mock.return_value = "test-project"
        yield mock


@pytest.fixture
def mock_no_project():
    """Mock _get_current_project_id to return None (no project)."""
    with patch("a_sdlc.server._get_current_project_id") as mock:
        mock.return_value = None
        yield mock


# =============================================================================
# Tool Imports (lazy to avoid import-time side effects)
# =============================================================================


def _import_tool(name):
    """Import a tool function from the server module."""
    import a_sdlc.server as server_module
    return getattr(server_module, name)


# =============================================================================
# 1. manage_agent (register/propose/suspend/retire)
# =============================================================================


class TestManageAgentRegister:
    """Test manage_agent action=register."""

    def test_happy_path(self, mock_db, mock_project_id):
        tool = _import_tool("manage_agent")
        mock_db.get_next_agent_id.return_value = "TEST-A001"
        mock_db.create_agent.return_value = {
            "id": "TEST-A001", "persona_type": "backend-engineer",
            "display_name": "Backend Engineer", "status": "active",
        }
        result = tool("register", persona_type="backend-engineer", display_name="Backend Engineer")
        assert result["status"] == "ok"
        assert result["agent"]["id"] == "TEST-A001"

    def test_no_project(self, mock_db, mock_no_project):
        tool = _import_tool("manage_agent")
        result = tool("register", persona_type="backend-engineer", display_name="Backend Engineer")
        assert result["status"] == "no_project"

    def test_error(self, mock_db, mock_project_id):
        tool = _import_tool("manage_agent")
        mock_db.get_next_agent_id.side_effect = Exception("DB error")
        result = tool("register", persona_type="backend-engineer", display_name="Backend Engineer")
        assert result["status"] == "error"
        assert "DB error" in result["message"]


class TestManageAgentPropose:
    """Test manage_agent action=propose."""

    def test_happy_path(self, mock_db, mock_project_id):
        tool = _import_tool("manage_agent")
        mock_db.get_next_agent_id.return_value = "TEST-A001"
        mock_db.create_agent.return_value = {
            "id": "TEST-A001", "status": "proposed",
            "persona_type": "qa_engineer", "display_name": "Qa Engineer",
        }
        mock_db.append_audit_log.return_value = {"id": 1}
        result = tool("propose", persona_type="qa_engineer", justification="Need QA coverage")
        assert result["status"] == "ok"
        assert result["agent"]["status"] == "proposed"

    def test_no_project(self, mock_db, mock_no_project):
        tool = _import_tool("manage_agent")
        result = tool("propose", persona_type="qa_engineer", justification="Need QA")
        assert result["status"] == "no_project"

    def test_error(self, mock_db, mock_project_id):
        tool = _import_tool("manage_agent")
        mock_db.get_next_agent_id.side_effect = Exception("DB error")
        result = tool("propose", persona_type="qa_engineer", justification="Need QA")
        assert result["status"] == "error"


class TestManageAgentSuspend:
    """Test manage_agent action=suspend."""

    def test_happy_path(self, mock_db, mock_project_id):
        tool = _import_tool("manage_agent")
        mock_db.list_claims_by_agent.return_value = []
        mock_db.suspend_agent.return_value = {
            "id": "TEST-A001", "status": "suspended",
        }
        mock_db.append_audit_log.return_value = {"id": 1}
        result = tool("suspend", agent_id="TEST-A001", reason="poor performance")
        assert result["status"] == "ok"
        assert result["agent"]["status"] == "suspended"

    def test_releases_active_claims(self, mock_db, mock_project_id):
        tool = _import_tool("manage_agent")
        mock_db.list_claims_by_agent.return_value = [
            {"task_id": "T1", "status": "active"},
            {"task_id": "T2", "status": "released"},
        ]
        mock_db.release_task.return_value = {"id": 1}
        mock_db.suspend_agent.return_value = {
            "id": "TEST-A001", "status": "suspended",
        }
        mock_db.append_audit_log.return_value = {"id": 1}
        result = tool("suspend", agent_id="TEST-A001")
        assert result["status"] == "ok"
        # Only the active claim should be released
        mock_db.release_task.assert_called_once_with(
            "T1", "TEST-A001", reason="agent_suspended"
        )

    def test_error(self, mock_db, mock_project_id):
        tool = _import_tool("manage_agent")
        mock_db.list_claims_by_agent.side_effect = Exception("fail")
        result = tool("suspend", agent_id="TEST-A001")
        assert result["status"] == "error"


class TestManageAgentRetire:
    """Test manage_agent action=retire."""

    def test_happy_path(self, mock_db, mock_project_id):
        tool = _import_tool("manage_agent")
        mock_db.list_claims_by_agent.return_value = []
        mock_db.retire_agent.return_value = {
            "id": "TEST-A001", "status": "retired",
        }
        mock_db.append_audit_log.return_value = {"id": 1}
        result = tool("retire", agent_id="TEST-A001")
        assert result["status"] == "ok"
        assert result["agent"]["status"] == "retired"
        assert "preserved" in result["message"].lower()

    def test_releases_active_claims(self, mock_db, mock_project_id):
        tool = _import_tool("manage_agent")
        mock_db.list_claims_by_agent.return_value = [
            {"task_id": "T1", "status": "active"},
        ]
        mock_db.release_task.return_value = {"id": 1}
        mock_db.retire_agent.return_value = {
            "id": "TEST-A001", "status": "retired",
        }
        mock_db.append_audit_log.return_value = {"id": 1}
        result = tool("retire", agent_id="TEST-A001")
        assert result["status"] == "ok"
        mock_db.release_task.assert_called_once_with(
            "T1", "TEST-A001", reason="agent_retired"
        )

    def test_error(self, mock_db, mock_project_id):
        tool = _import_tool("manage_agent")
        mock_db.list_claims_by_agent.side_effect = Exception("fail")
        result = tool("retire", agent_id="TEST-A001")
        assert result["status"] == "error"


class TestManageAgentInvalidAction:
    """Test manage_agent with invalid action."""

    def test_invalid_action(self, mock_db, mock_project_id):
        tool = _import_tool("manage_agent")
        result = tool("invalid_action")
        assert result["status"] == "error"
        assert "Invalid action" in result["message"]


# =============================================================================
# 2. check_permission
# =============================================================================


class TestCheckPermission:
    """Test check_permission MCP tool."""

    def test_happy_path_allowed(self, mock_db):
        tool = _import_tool("check_permission")
        mock_db.check_agent_permission.return_value = True
        result = tool("TEST-A001", "tool", "git_push")
        assert result["status"] == "ok"
        assert result["allowed"] is True

    def test_happy_path_denied(self, mock_db):
        tool = _import_tool("check_permission")
        mock_db.check_agent_permission.return_value = False
        result = tool("TEST-A001", "tool", "git_push")
        assert result["status"] == "ok"
        assert result["allowed"] is False

    def test_error(self, mock_db):
        tool = _import_tool("check_permission")
        mock_db.check_agent_permission.side_effect = Exception("fail")
        result = tool("TEST-A001", "tool", "git_push")
        assert result["status"] == "error"


# =============================================================================
# 3. manage_agent_budget (set/get/report)
# =============================================================================


class TestManageAgentBudgetSet:
    """Test manage_agent_budget action=set."""

    def test_happy_path(self, mock_db):
        tool = _import_tool("manage_agent_budget")
        mock_db.create_agent_budget.return_value = {
            "id": 1, "agent_id": "TEST-A001",
            "token_limit": 100000, "cost_limit_cents": 500,
        }
        result = tool("set", "TEST-A001", token_limit=100000, cost_limit_cents=500)
        assert result["status"] == "ok"
        assert result["budget"]["token_limit"] == 100000

    def test_with_run_id(self, mock_db):
        tool = _import_tool("manage_agent_budget")
        mock_db.create_agent_budget.return_value = {
            "id": 1, "agent_id": "TEST-A001", "run_id": "R001",
            "token_limit": 50000, "cost_limit_cents": 250,
        }
        result = tool("set", "TEST-A001", token_limit=50000, cost_limit_cents=250, run_id="R001")
        assert result["status"] == "ok"

    def test_error(self, mock_db):
        tool = _import_tool("manage_agent_budget")
        mock_db.create_agent_budget.side_effect = Exception("fail")
        result = tool("set", "TEST-A001")
        assert result["status"] == "error"


class TestManageAgentBudgetGet:
    """Test manage_agent_budget action=get."""

    def test_happy_path(self, mock_db):
        tool = _import_tool("manage_agent_budget")
        mock_db.get_agent_budget.return_value = {
            "id": 1, "agent_id": "TEST-A001",
            "token_limit": 100000, "token_used": 50000,
            "cost_limit_cents": 500, "cost_used_cents": 100,
        }
        result = tool("get", "TEST-A001")
        assert result["status"] == "ok"
        assert result["budget"]["token_usage_pct"] == 50.0

    def test_no_budget(self, mock_db):
        tool = _import_tool("manage_agent_budget")
        mock_db.get_agent_budget.return_value = None
        result = tool("get", "TEST-A001")
        assert result["status"] == "ok"
        assert result["budget"] is None

    def test_error(self, mock_db):
        tool = _import_tool("manage_agent_budget")
        mock_db.get_agent_budget.side_effect = Exception("fail")
        result = tool("get", "TEST-A001")
        assert result["status"] == "error"


# =============================================================================
# 4. get_available_work_for_agent
# =============================================================================


class TestGetAvailableWorkForAgent:
    """Test get_available_work_for_agent MCP tool."""

    def test_happy_path(self, mock_db, mock_project_id):
        tool = _import_tool("get_available_work_for_agent")
        mock_db.get_available_work.return_value = [
            {"id": "TEST-T00001", "priority": "high"},
            {"id": "TEST-T00002", "priority": "medium"},
        ]
        result = tool("TEST-A001")
        assert result["status"] == "ok"
        assert result["count"] == 2

    def test_no_project(self, mock_db, mock_no_project):
        tool = _import_tool("get_available_work_for_agent")
        result = tool("TEST-A001")
        assert result["status"] == "no_project"

    def test_agent_not_found(self, mock_db, mock_project_id):
        tool = _import_tool("get_available_work_for_agent")
        mock_db.get_available_work.side_effect = ValueError("Agent not found")
        result = tool("NONEXISTENT")
        assert result["status"] == "error"
        assert "Agent not found" in result["message"]


# =============================================================================
# 5. manage_agent_task (claim/release/assign)
# =============================================================================


class TestManageAgentTaskClaim:
    """Test manage_agent_task action=claim."""

    def test_happy_path(self, mock_db):
        tool = _import_tool("manage_agent_task")
        mock_db.claim_task.return_value = {
            "id": 1, "task_id": "TEST-T00001", "agent_id": "TEST-A001",
            "status": "active",
        }
        result = tool("claim", "TEST-A001", "TEST-T00001")
        assert result["status"] == "ok"
        assert "claimed" in result["message"].lower()

    def test_conflict(self, mock_db):
        tool = _import_tool("manage_agent_task")
        mock_db.claim_task.side_effect = ValueError("already has an active claim")
        result = tool("claim", "TEST-A001", "TEST-T00001")
        assert result["status"] == "conflict"

    def test_error(self, mock_db):
        tool = _import_tool("manage_agent_task")
        mock_db.claim_task.side_effect = Exception("DB error")
        result = tool("claim", "TEST-A001", "TEST-T00001")
        assert result["status"] == "error"


class TestManageAgentTaskRelease:
    """Test manage_agent_task action=release."""

    def test_happy_path(self, mock_db):
        tool = _import_tool("manage_agent_task")
        mock_db.release_task.return_value = {
            "id": 1, "task_id": "TEST-T00001", "status": "released",
        }
        result = tool("release", "TEST-A001", "TEST-T00001", reason="manual")
        assert result["status"] == "ok"
        assert "released" in result["message"].lower()

    def test_not_found(self, mock_db):
        tool = _import_tool("manage_agent_task")
        mock_db.release_task.return_value = None
        result = tool("release", "TEST-A001", "TEST-T00001")
        assert result["status"] == "not_found"

    def test_error(self, mock_db):
        tool = _import_tool("manage_agent_task")
        mock_db.release_task.side_effect = Exception("fail")
        result = tool("release", "TEST-A001", "TEST-T00001")
        assert result["status"] == "error"


class TestManageAgentTaskAssign:
    """Test manage_agent_task action=assign."""

    def test_happy_path(self, mock_db, mock_project_id):
        tool = _import_tool("manage_agent_task")
        mock_db.claim_task.return_value = {
            "id": 1, "task_id": "TEST-T00001", "agent_id": "TEST-A001",
        }
        mock_db.append_audit_log.return_value = {"id": 1}
        result = tool("assign", "TEST-A001", "TEST-T00001")
        assert result["status"] == "ok"
        assert "assigned" in result["message"].lower()

    def test_conflict(self, mock_db, mock_project_id):
        tool = _import_tool("manage_agent_task")
        mock_db.claim_task.side_effect = ValueError("already claimed")
        result = tool("assign", "TEST-A001", "TEST-T00001")
        assert result["status"] == "conflict"

    def test_error(self, mock_db, mock_project_id):
        tool = _import_tool("manage_agent_task")
        mock_db.claim_task.side_effect = Exception("DB error")
        result = tool("assign", "TEST-A001", "TEST-T00001")
        assert result["status"] == "error"


# =============================================================================
# 6. agent_messages (send/get)
# =============================================================================


class TestAgentMessagesSend:
    """Test agent_messages action=send."""

    def test_happy_path(self, mock_db):
        tool = _import_tool("agent_messages")
        mock_db.send_agent_message.return_value = {
            "id": 1, "from_agent_id": "TEST-A001",
            "to_agent_id": "TEST-A002", "content": "hello",
        }
        result = tool("send", from_agent_id="TEST-A001", to_agent_id="TEST-A002", message_type="handoff", content="hello")
        assert result["status"] == "ok"

    def test_with_related_task(self, mock_db):
        tool = _import_tool("agent_messages")
        mock_db.send_agent_message.return_value = {
            "id": 1, "related_task_id": "TEST-T00001",
        }
        result = tool("send", from_agent_id="TEST-A001", to_agent_id="TEST-A002", message_type="blocker", content="blocked", related_task_id="TEST-T00001")
        assert result["status"] == "ok"

    def test_error(self, mock_db):
        tool = _import_tool("agent_messages")
        mock_db.send_agent_message.side_effect = Exception("fail")
        result = tool("send", from_agent_id="TEST-A001", to_agent_id="TEST-A002", message_type="handoff", content="hello")
        assert result["status"] == "error"


class TestAgentMessagesGet:
    """Test agent_messages action=get."""

    def test_happy_path(self, mock_db):
        tool = _import_tool("agent_messages")
        mock_db.get_agent_messages.return_value = [
            {"id": 1, "content": "msg1"},
            {"id": 2, "content": "msg2"},
        ]
        result = tool("get", agent_id="TEST-A002")
        assert result["status"] == "ok"
        assert result["count"] == 2

    def test_unread_only(self, mock_db):
        tool = _import_tool("agent_messages")
        mock_db.get_agent_messages.return_value = [{"id": 1}]
        result = tool("get", agent_id="TEST-A002", unread_only=True)
        assert result["status"] == "ok"
        mock_db.get_agent_messages.assert_called_with("TEST-A002", unread_only=True)

    def test_error(self, mock_db):
        tool = _import_tool("agent_messages")
        mock_db.get_agent_messages.side_effect = Exception("fail")
        result = tool("get", agent_id="TEST-A002")
        assert result["status"] == "error"


# =============================================================================
# 7. get_agent_analytics (performance/org/team)
# =============================================================================


class TestGetAgentAnalyticsPerformance:
    """Test get_agent_analytics scope=performance."""

    def test_happy_path_aggregate(self, mock_db):
        tool = _import_tool("get_agent_analytics")
        mock_db.compute_agent_performance.return_value = {
            "total_completed": 10, "total_failed": 2,
        }
        result = tool("performance", agent_id="TEST-A001")
        assert result["status"] == "ok"
        assert result["performance"]["total_completed"] == 10

    def test_with_sprint_id(self, mock_db):
        tool = _import_tool("get_agent_analytics")
        mock_db.get_agent_performance.return_value = {
            "tasks_completed": 5, "sprint_id": "S001",
        }
        result = tool("performance", agent_id="TEST-A001", sprint_id="S001")
        assert result["status"] == "ok"
        mock_db.get_agent_performance.assert_called_with("TEST-A001", "S001")

    def test_error(self, mock_db):
        tool = _import_tool("get_agent_analytics")
        mock_db.compute_agent_performance.side_effect = Exception("fail")
        result = tool("performance", agent_id="TEST-A001")
        assert result["status"] == "error"


class TestGetAgentAnalyticsOrg:
    """Test get_agent_analytics scope=org."""

    def test_happy_path(self, mock_db, mock_project_id):
        tool = _import_tool("get_agent_analytics")
        mock_db.get_org_overview.return_value = {
            "project_id": "test-project",
            "agent_counts": {"active": 3},
            "team_count": 1,
            "agents": [],
        }
        result = tool("org")
        assert result["status"] == "ok"
        assert result["overview"]["agent_counts"]["active"] == 3

    def test_no_project(self, mock_db, mock_no_project):
        tool = _import_tool("get_agent_analytics")
        result = tool("org")
        assert result["status"] == "no_project"

    def test_error(self, mock_db, mock_project_id):
        tool = _import_tool("get_agent_analytics")
        mock_db.get_org_overview.side_effect = Exception("fail")
        result = tool("org")
        assert result["status"] == "error"


class TestGetAgentAnalyticsTeam:
    """Test get_agent_analytics scope=team."""

    def test_happy_path(self, mock_db):
        tool = _import_tool("get_agent_analytics")
        mock_db.get_team_composition.return_value = {
            "id": 1, "name": "Backend Team", "members": [],
        }
        result = tool("team", team_id=1)
        assert result["status"] == "ok"
        assert result["team"]["name"] == "Backend Team"

    def test_error(self, mock_db):
        tool = _import_tool("get_agent_analytics")
        mock_db.get_team_composition.side_effect = ValueError("Team not found")
        result = tool("team", team_id=99999)
        assert result["status"] == "error"
        assert "Team not found" in result["message"]
