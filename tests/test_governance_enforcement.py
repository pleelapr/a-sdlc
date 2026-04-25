"""Tests for Governance Behavioral Enforcement (SDLC-T00175).

Covers:
- REM-001: Escalation rule evaluation (evaluate_escalation_rules)
- REM-002: Permission surfacing in get_task / propose_work,
           check_permission_compliance MCP tool
- REM-003: Automatic audit logging in governance MCP tools
- REM-004: Budget counter tracking (increment_agent_budget, report_usage)
- REM-005: Budget pause state (auto-suspend on budget exceed)
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from a_sdlc.executor import _evaluate_condition, evaluate_escalation_rules

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
    """Mock _get_current_project_id to return None."""
    with patch("a_sdlc.server._get_current_project_id") as mock:
        mock.return_value = None
        yield mock


def _import_tool(name):
    """Import a tool function from the server module."""
    import a_sdlc.server as server_module

    return getattr(server_module, name)


# =============================================================================
# REM-001: Escalation Rule Evaluation
# =============================================================================


class TestEvaluateEscalationRules:
    """Tests for evaluate_escalation_rules() in executor.py."""

    def test_no_rules_returns_empty(self, tmp_path):
        """When no escalation rules are configured, nothing fires."""
        config_dir = tmp_path / ".sdlc"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text(
            "governance:\n  escalation:\n    rules: []\n"
        )
        result = evaluate_escalation_rules(
            "T001",
            task_metrics={"retry_count": 5},
            project_dir=str(tmp_path),
        )
        assert result == []

    def test_no_governance_section(self, tmp_path):
        """When governance section is missing, returns empty."""
        config_dir = tmp_path / ".sdlc"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text("testing: {}\n")
        result = evaluate_escalation_rules(
            "T001",
            task_metrics={"retry_count": 5},
            project_dir=str(tmp_path),
        )
        assert result == []

    def test_rule_fires_gt(self, tmp_path):
        """A '>' condition fires when metric exceeds threshold."""
        config_dir = tmp_path / ".sdlc"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text(
            "governance:\n"
            "  escalation:\n"
            "    rules:\n"
            "      - condition: 'retry_count > 3'\n"
            "        action: pause\n"
            "        notify: true\n"
        )
        result = evaluate_escalation_rules(
            "T001",
            task_metrics={"retry_count": 4},
            project_dir=str(tmp_path),
        )
        assert len(result) == 1
        assert result[0]["action"] == "pause"
        assert result[0]["notify"] is True
        assert "retry_count=4" in result[0]["reason"]

    def test_rule_does_not_fire(self, tmp_path):
        """A '>' condition does not fire when metric is below threshold."""
        config_dir = tmp_path / ".sdlc"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text(
            "governance:\n"
            "  escalation:\n"
            "    rules:\n"
            "      - condition: 'retry_count > 3'\n"
            "        action: pause\n"
        )
        result = evaluate_escalation_rules(
            "T001",
            task_metrics={"retry_count": 2},
            project_dir=str(tmp_path),
        )
        assert result == []

    def test_rule_fires_gte(self, tmp_path):
        """A '>=' condition fires when metric meets threshold exactly."""
        config_dir = tmp_path / ".sdlc"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text(
            "governance:\n"
            "  escalation:\n"
            "    rules:\n"
            "      - condition: 'cost >= 400'\n"
            "        action: alert\n"
        )
        result = evaluate_escalation_rules(
            "T001",
            task_metrics={"cost": 400},
            project_dir=str(tmp_path),
        )
        assert len(result) == 1
        assert result[0]["action"] == "alert"

    def test_multiple_rules(self, tmp_path):
        """Multiple rules can fire independently."""
        config_dir = tmp_path / ".sdlc"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text(
            "governance:\n"
            "  escalation:\n"
            "    rules:\n"
            "      - condition: 'retry_count > 3'\n"
            "        action: pause\n"
            "      - condition: 'cost > 400'\n"
            "        action: alert\n"
        )
        result = evaluate_escalation_rules(
            "T001",
            task_metrics={"retry_count": 5, "cost": 500},
            project_dir=str(tmp_path),
        )
        assert len(result) == 2
        actions = {r["action"] for r in result}
        assert actions == {"pause", "alert"}

    def test_missing_metric_does_not_fire(self, tmp_path):
        """When a metric is not in task_metrics, the rule does not fire."""
        config_dir = tmp_path / ".sdlc"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text(
            "governance:\n"
            "  escalation:\n"
            "    rules:\n"
            "      - condition: 'retry_count > 3'\n"
            "        action: pause\n"
        )
        result = evaluate_escalation_rules(
            "T001",
            task_metrics={"cost": 100},
            project_dir=str(tmp_path),
        )
        assert result == []


class TestEvaluateCondition:
    """Unit tests for _evaluate_condition helper."""

    def test_gt_fires(self):
        fired, reason = _evaluate_condition("cost > 100", {"cost": 150})
        assert fired is True
        assert "cost=150" in reason

    def test_gt_does_not_fire(self):
        fired, reason = _evaluate_condition("cost > 100", {"cost": 50})
        assert fired is False

    def test_gte_fires_at_boundary(self):
        fired, _ = _evaluate_condition("cost >= 100", {"cost": 100})
        assert fired is True

    def test_lt_fires(self):
        fired, _ = _evaluate_condition("score < 40", {"score": 30})
        assert fired is True

    def test_eq_fires(self):
        fired, _ = _evaluate_condition("status == 3", {"status": 3})
        assert fired is True

    def test_missing_metric(self):
        fired, reason = _evaluate_condition("x > 1", {})
        assert fired is False
        assert "not available" in reason

    def test_unparseable(self):
        fired, reason = _evaluate_condition("gibberish", {"x": 1})
        assert fired is False
        assert "unparseable" in reason


# =============================================================================
# REM-002: Permission Surfacing & Compliance
# =============================================================================


class TestGetTaskPermissionSurfacing:
    """get_task surfaces agent permissions when task has an active claim."""

    def test_permissions_included_when_claimed(self, mock_db, mock_project_id):
        tool = _import_tool("get_task")
        mock_db.get_task.return_value = {
            "id": "T001",
            "project_id": "test-project",
            "file_path": None,
            "prd_id": None,
        }
        mock_db.get_active_claim.return_value = {
            "agent_id": "A001",
            "task_id": "T001",
            "status": "active",
        }
        mock_db.get_agent_permissions.return_value = [
            {"permission_type": "tool", "permission_value": "Bash", "allowed": 1},
        ]

        with patch("a_sdlc.server.get_content_manager") as mock_cm:
            mock_cm.return_value.read_content.return_value = None
            mock_cm.return_value.read_task.return_value = None
            result = tool("T001")

        assert result["status"] == "ok"
        task = result["task"]
        assert task["claimed_by"] == "A001"
        assert len(task["agent_permissions"]) == 1
        assert task["agent_permissions"][0]["permission_value"] == "Bash"

    def test_no_permissions_when_unclaimed(self, mock_db, mock_project_id):
        tool = _import_tool("get_task")
        mock_db.get_task.return_value = {
            "id": "T001",
            "project_id": "test-project",
            "file_path": None,
            "prd_id": None,
        }
        mock_db.get_active_claim.return_value = None

        with patch("a_sdlc.server.get_content_manager") as mock_cm:
            mock_cm.return_value.read_content.return_value = None
            mock_cm.return_value.read_task.return_value = None
            result = tool("T001")

        assert result["status"] == "ok"
        assert "agent_permissions" not in result["task"]
        assert "claimed_by" not in result["task"]


class TestProposeWork:
    """Tests for propose_work MCP tool."""

    def test_happy_path(self, mock_db, mock_project_id):
        tool = _import_tool("propose_work")
        mock_db.get_available_work.return_value = [
            {"id": "T001", "title": "Task 1", "priority": "high"},
        ]
        mock_db.get_agent_permissions.return_value = [
            {"permission_type": "tool", "permission_value": "Bash", "allowed": 1},
        ]

        with patch("a_sdlc.server._load_routing_config", return_value={}):
            result = tool("A001")

        assert result["status"] == "ok"
        assert result["count"] == 1
        assert len(result["agent_permissions"]) == 1
        assert result["agent_id"] == "A001"

    def test_no_project(self, mock_db, mock_no_project):
        tool = _import_tool("propose_work")
        result = tool("A001")
        assert result["status"] == "no_project"

    def test_error(self, mock_db, mock_project_id):
        tool = _import_tool("propose_work")
        mock_db.get_available_work.side_effect = Exception("DB fail")

        with patch("a_sdlc.server._load_routing_config", return_value={}):
            result = tool("A001")

        assert result["status"] == "error"


class TestCheckPermissionCompliance:
    """Tests for check_permission_compliance MCP tool."""

    def test_all_compliant(self, mock_db, mock_project_id):
        tool = _import_tool("check_permission_compliance")
        mock_db.check_agent_permission.return_value = True

        result = tool("A001", ["tool:Bash", "file_path:/src/"])

        assert result["status"] == "ok"
        assert result["compliant"] is True
        assert result["total_checked"] == 2
        assert result["violations"] == []

    def test_violations_found(self, mock_db, mock_project_id):
        tool = _import_tool("check_permission_compliance")
        # Bash allowed, git_push denied
        mock_db.check_agent_permission.side_effect = [True, False]
        mock_db.append_audit_log.return_value = {"id": 1}

        result = tool("A001", ["tool:Bash", "tool:git_push"])

        assert result["status"] == "ok"
        assert result["compliant"] is False
        assert len(result["violations"]) == 1
        assert result["violations"][0]["permission_value"] == "git_push"

    def test_audit_logged_on_violation(self, mock_db, mock_project_id):
        tool = _import_tool("check_permission_compliance")
        mock_db.check_agent_permission.return_value = False
        mock_db.append_audit_log.return_value = {"id": 1}

        tool("A001", ["tool:dangerous_op"])

        mock_db.append_audit_log.assert_called_once()
        call_args = mock_db.append_audit_log.call_args
        assert call_args[0][1] == "permission_compliance_violation"

    def test_malformed_actions_skipped(self, mock_db, mock_project_id):
        tool = _import_tool("check_permission_compliance")
        mock_db.check_agent_permission.return_value = True

        result = tool("A001", ["no_colon", "tool:valid"])

        assert result["total_checked"] == 1  # skipped malformed entry

    def test_error(self, mock_db, mock_project_id):
        tool = _import_tool("check_permission_compliance")
        mock_db.check_agent_permission.side_effect = Exception("fail")

        result = tool("A001", ["tool:Bash"])

        assert result["status"] == "error"


# =============================================================================
# REM-003: Automatic Audit Logging
# =============================================================================


class TestAuditLoggingInGovernanceTools:
    """Verify audit log calls are made by governance MCP tools."""

    def test_register_agent_logs_audit(self, mock_db, mock_project_id):
        tool = _import_tool("manage_agent")
        mock_db.get_next_agent_id.return_value = "TEST-A001"
        mock_db.create_agent.return_value = {
            "id": "TEST-A001",
            "persona_type": "be",
            "display_name": "BE",
            "status": "active",
        }
        mock_db.append_audit_log.return_value = {"id": 1}

        tool("register", persona_type="be", display_name="BE")

        mock_db.append_audit_log.assert_called_once()
        call_args = mock_db.append_audit_log.call_args
        assert call_args[0][1] == "agent_registered"

    def test_set_agent_budget_logs_audit(self, mock_db, mock_project_id):
        tool = _import_tool("manage_agent_budget")
        mock_db.create_agent_budget.return_value = {
            "id": 1,
            "agent_id": "A001",
            "token_limit": 50000,
            "cost_limit_cents": 200,
        }
        mock_db.append_audit_log.return_value = {"id": 1}

        tool("set", "A001", token_limit=50000, cost_limit_cents=200)

        mock_db.append_audit_log.assert_called_once()
        call_args = mock_db.append_audit_log.call_args
        assert call_args[0][1] == "budget_set"
        # Verify details contain the limits
        details = json.loads(call_args[1]["details"])
        assert details["token_limit"] == 50000

    def test_update_task_completed_logs_audit(self, mock_db, mock_project_id):
        tool = _import_tool("update_task")
        mock_db.get_task.return_value = {
            "id": "T001",
            "project_id": "test-project",
            "status": "in_progress",
        }
        mock_db.update_task.return_value = {
            "id": "T001",
            "status": "completed",
        }
        mock_db.get_active_claim.return_value = {
            "agent_id": "A001",
            "task_id": "T001",
        }
        mock_db.append_audit_log.return_value = {"id": 1}

        # Disable review and quality gates for this test
        with patch("a_sdlc.server.load_review_config") as mock_rc, \
             patch("a_sdlc.server.load_quality_config") as mock_qc:
            mock_rc.return_value.enabled = False
            mock_qc.return_value.enabled = False

            tool("T001", status="completed")

        # Should have logged audit
        mock_db.append_audit_log.assert_called_once()
        call_args = mock_db.append_audit_log.call_args
        assert call_args[0][1] == "task_completed"
        assert call_args[1]["agent_id"] == "A001"
        assert call_args[1]["target_entity"] == "T001"

    def test_update_task_non_completed_no_audit(self, mock_db, mock_project_id):
        """Audit log is NOT generated for non-completed status changes."""
        tool = _import_tool("update_task")
        mock_db.get_task.return_value = {
            "id": "T001",
            "project_id": "test-project",
            "status": "pending",
        }
        mock_db.update_task.return_value = {
            "id": "T001",
            "status": "in_progress",
        }

        tool("T001", status="in_progress")

        mock_db.append_audit_log.assert_not_called()


# =============================================================================
# REM-004: Budget Counter Tracking
# =============================================================================


class TestIncrementAgentBudget:
    """Tests for increment_agent_budget in the database layer."""

    def test_increments_existing_budget(self):
        """Atomically increments token and cost counters."""
        with tempfile.TemporaryDirectory() as tmpdir:
            from a_sdlc.core.database import Database

            db = Database(db_path=Path(tmpdir) / "test.db")
            db.create_project("proj", "Test", "/tmp/test")
            db.create_agent("A001", "proj", "be", "Backend Engineer")
            db.create_agent_budget("A001", token_limit=10000, cost_limit_cents=500)

            # First increment
            result = db.increment_agent_budget("A001", tokens_delta=1000, cost_delta_cents=50)
            assert result is not None
            assert result["token_used"] == 1000
            assert result["cost_used_cents"] == 50

            # Second increment (cumulative)
            result = db.increment_agent_budget("A001", tokens_delta=500, cost_delta_cents=25)
            assert result["token_used"] == 1500
            assert result["cost_used_cents"] == 75

    def test_no_budget_returns_none(self):
        """When no budget exists, returns None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            from a_sdlc.core.database import Database

            db = Database(db_path=Path(tmpdir) / "test.db")
            db.create_project("proj", "Test", "/tmp/test")
            db.create_agent("A001", "proj", "be", "Backend Engineer")

            result = db.increment_agent_budget("A001", tokens_delta=100)
            assert result is None

    def test_run_scoped_budget(self):
        """Budget increment scoped to a specific run."""
        with tempfile.TemporaryDirectory() as tmpdir:
            from a_sdlc.core.database import Database

            db = Database(db_path=Path(tmpdir) / "test.db")
            db.create_project("proj", "Test", "/tmp/test")
            db.create_agent("A001", "proj", "be", "Backend Engineer")
            db.create_agent_budget(
                "A001", run_id="R001", token_limit=5000, cost_limit_cents=200
            )

            result = db.increment_agent_budget(
                "A001", tokens_delta=500, run_id="R001"
            )
            assert result is not None
            assert result["token_used"] == 500


class TestReportUsageTool:
    """Tests for manage_agent_budget(report, ...) MCP tool."""

    def test_happy_path_no_budget(self, mock_db, mock_project_id):
        tool = _import_tool("manage_agent_budget")
        mock_db.increment_agent_budget.return_value = None

        result = tool("report", "A001", tokens=1000, cost_cents=50)

        assert result["status"] == "ok"
        assert result["exceeded"] is False
        assert result["action_taken"] is None

    def test_budget_not_exceeded(self, mock_db, mock_project_id):
        tool = _import_tool("manage_agent_budget")
        mock_db.increment_agent_budget.return_value = {
            "id": 1,
            "agent_id": "A001",
            "token_limit": 10000,
            "token_used": 1000,
            "cost_limit_cents": 500,
            "cost_used_cents": 50,
        }

        result = tool("report", "A001", tokens=1000, cost_cents=50)

        assert result["status"] == "ok"
        assert result["exceeded"] is False
        assert result["action_taken"] is None

    def test_budget_exceeded_triggers_suspend(self, mock_db, mock_project_id):
        """REM-005: When budget is exceeded, agent is auto-suspended."""
        tool = _import_tool("manage_agent_budget")
        mock_db.increment_agent_budget.return_value = {
            "id": 1,
            "agent_id": "A001",
            "token_limit": 10000,
            "token_used": 10000,  # at limit
            "cost_limit_cents": 500,
            "cost_used_cents": 100,
        }
        mock_db.suspend_agent.return_value = {"id": "A001", "status": "suspended"}
        mock_db.append_audit_log.return_value = {"id": 1}

        # Default budget_action is "pause" when config loading fails
        with patch("a_sdlc.core.git_config._load_yaml", side_effect=Exception("no config")):
            result = tool("report", "A001", tokens=5000)

        assert result["status"] == "ok"
        assert result["exceeded"] is True
        assert result["action_taken"] == "suspended"
        mock_db.suspend_agent.assert_called_once_with("A001")

    def test_budget_exceeded_alert_action(self, mock_db, mock_project_id):
        """When budget_action is 'alert', agent is NOT suspended."""
        tool = _import_tool("manage_agent_budget")
        mock_db.increment_agent_budget.return_value = {
            "id": 1,
            "agent_id": "A001",
            "token_limit": 100,
            "token_used": 100,
            "cost_limit_cents": 0,
            "cost_used_cents": 0,
        }
        mock_db.append_audit_log.return_value = {"id": 1}

        with patch(
            "a_sdlc.core.git_config._load_yaml",
            return_value={
                "governance": {"budget": {"action": "alert"}},
            },
        ):
            result = tool("report", "A001", tokens=50)

        assert result["exceeded"] is True
        assert result["action_taken"] == "alert"
        mock_db.suspend_agent.assert_not_called()

    def test_error_handling(self, mock_db, mock_project_id):
        tool = _import_tool("manage_agent_budget")
        mock_db.increment_agent_budget.side_effect = Exception("DB fail")

        result = tool("report", "A001", tokens=100)

        assert result["status"] == "error"


# =============================================================================
# REM-005: Budget Pause State
# =============================================================================


class TestBudgetPauseState:
    """Tests for auto-suspend on budget exceed (REM-005)."""

    def test_cost_budget_exceeded_suspends(self, mock_db, mock_project_id):
        """Cost budget exceeded also triggers suspend."""
        tool = _import_tool("manage_agent_budget")
        mock_db.increment_agent_budget.return_value = {
            "id": 1,
            "agent_id": "A001",
            "token_limit": 0,  # no token limit
            "token_used": 0,
            "cost_limit_cents": 500,
            "cost_used_cents": 500,  # at limit
        }
        mock_db.suspend_agent.return_value = {"id": "A001", "status": "suspended"}
        mock_db.append_audit_log.return_value = {"id": 1}

        # Default action is pause
        with patch("a_sdlc.core.git_config._load_yaml", side_effect=Exception("no config")):
            result = tool("report", "A001", cost_cents=100)

        assert result["exceeded"] is True
        assert result["action_taken"] == "suspended"
        assert "cost:" in result["reasons"][0]

    def test_audit_logged_on_budget_suspend(self, mock_db, mock_project_id):
        """Audit log entry is created when agent is suspended for budget."""
        tool = _import_tool("manage_agent_budget")
        mock_db.increment_agent_budget.return_value = {
            "id": 1,
            "agent_id": "A001",
            "token_limit": 100,
            "token_used": 100,
            "cost_limit_cents": 0,
            "cost_used_cents": 0,
        }
        mock_db.suspend_agent.return_value = {"id": "A001", "status": "suspended"}
        mock_db.append_audit_log.return_value = {"id": 1}

        with patch("a_sdlc.core.git_config._load_yaml", side_effect=Exception("no config")):
            tool("report", "A001", tokens=50)

        mock_db.append_audit_log.assert_called_once()
        call_args = mock_db.append_audit_log.call_args
        assert call_args[0][1] == "budget_exceeded_suspend"
