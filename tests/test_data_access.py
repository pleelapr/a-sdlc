"""Tests for MCPDataAccess proxy."""

import logging
from unittest.mock import MagicMock

import pytest

from a_sdlc.server.data_access import (
    _ALLOWED_OPS,
    READ_OPS,
    WRITE_OPS,
    MCPDataAccess,
)


@pytest.fixture
def mock_db():
    """Create a MagicMock that responds to all allowlisted methods."""
    db = MagicMock()
    return db


@pytest.fixture
def proxy(mock_db):
    return MCPDataAccess(mock_db)


# ── Allowlist tests ──────────────────────────────────────────────────


class TestAllowlist:
    def test_read_op_passes_through(self, proxy, mock_db):
        mock_db.get_task.return_value = {"id": "T001"}
        result = proxy.get_task("T001")
        mock_db.get_task.assert_called_once_with("T001")
        assert result == {"id": "T001"}

    def test_write_op_passes_through(self, proxy, mock_db):
        mock_db.create_task.return_value = {"id": "T002"}
        result = proxy.create_task(title="Test", prd_id="P001")
        mock_db.create_task.assert_called_once_with(title="Test", prd_id="P001")
        assert result == {"id": "T002"}

    def test_blocked_op_raises_attribute_error(self, proxy):
        with pytest.raises(AttributeError, match="not in the MCP allowlist"):
            proxy.connection()

    def test_unknown_method_raises(self, proxy):
        with pytest.raises(AttributeError, match="not in the MCP allowlist"):
            proxy.drop_all_tables()

    def test_dunder_not_intercepted(self, proxy):
        # repr should work (uses __repr__ defined on class)
        r = repr(proxy)
        assert "MCPDataAccess" in r

    def test_private_attr_raises(self, proxy):
        with pytest.raises(AttributeError, match="private attribute"):
            proxy._init_db()

    def test_all_read_ops_accessible(self, proxy, mock_db):
        for op in READ_OPS:
            getattr(mock_db, op).return_value = None
            result = getattr(proxy, op)
            assert callable(result), f"{op} should be callable"

    def test_all_write_ops_accessible(self, proxy, mock_db):
        for op in WRITE_OPS:
            getattr(mock_db, op).return_value = None
            result = getattr(proxy, op)
            assert callable(result), f"{op} should be callable"

    def test_no_overlap_between_read_and_write(self):
        overlap = READ_OPS & WRITE_OPS
        assert overlap == set(), f"Overlap found: {overlap}"


# ── Write monitoring tests ───────────────────────────────────────────


class TestWriteMonitoring:
    def test_write_logged(self, proxy, mock_db, caplog):
        mock_db.create_task.return_value = {"id": "T003"}
        with caplog.at_level(logging.DEBUG, logger="a-sdlc-server"):
            proxy.create_task("title", prd_id="P001")
        assert any("MCP write: create_task" in r.message for r in caplog.records)

    def test_read_not_logged(self, proxy, mock_db, caplog):
        mock_db.get_task.return_value = {"id": "T001"}
        with caplog.at_level(logging.DEBUG, logger="a-sdlc-server"):
            proxy.get_task("T001")
        assert not any("MCP write:" in r.message for r in caplog.records)


# ── Method caching tests ────────────────────────────────────────────


class TestMethodCaching:
    def test_read_cached(self, proxy, mock_db):
        mock_db.get_task.return_value = None
        first = proxy.get_task
        second = proxy.get_task
        assert first is second

    def test_write_cached(self, proxy, mock_db):
        mock_db.create_task.return_value = None
        first = proxy.create_task
        second = proxy.create_task
        assert first is second


# ── Allowlist completeness tests ─────────────────────────────────────


class TestAllowlistCompleteness:
    # All methods used by server/__init__.py and server/sync.py
    KNOWN_SERVER_METHODS = {
        # Read ops
        "check_agent_permission",
        "compute_agent_performance",
        "get_ac_verifications",
        "get_active_claim",
        "get_agent",
        "get_agent_budget",
        "get_agent_messages",
        "get_agent_performance",
        "get_agent_permissions",
        "get_available_work",
        "get_challenge_rounds",
        "get_challenge_status",
        "get_coverage_stats",
        "get_external_config",
        "get_latest_approved_review",
        "get_next_agent_id",
        "get_next_prd_id",
        "get_next_sprint_id",
        "get_next_task_id",
        "get_next_worktree_id",
        "get_org_overview",
        "get_orphaned_requirements",
        "get_prd",
        "get_project",
        "get_project_by_path",
        "get_project_by_shortname",
        "get_requirement",
        "get_requirement_tasks",
        "get_requirements",
        "get_reviews_for_task",
        "get_sprint",
        "get_sprint_prds",
        "get_sync_mapping",
        "get_sync_mapping_by_external",
        "get_task",
        "get_task_requirements",
        "get_team_composition",
        "get_unverified_acs",
        "get_worktree_by_prd",
        "is_shortname_available",
        "generate_unique_shortname",
        "validate_shortname",
        "list_agents",
        "list_claims_by_agent",
        "list_external_configs",
        "list_prds",
        "list_projects",
        "list_sprints",
        "list_sync_mappings",
        "list_tasks",
        "list_tasks_by_sprint",
        "list_worktrees",
        # Write ops
        "append_audit_log",
        "assign_prd_to_sprint",
        "claim_task",
        "create_agent",
        "create_agent_budget",
        "create_prd",
        "create_project",
        "create_review",
        "create_sprint",
        "create_sync_mapping",
        "create_task",
        "create_worktree",
        "delete_external_config",
        "delete_prd",
        "delete_sprint",
        "delete_sync_mapping",
        "delete_task",
        "increment_agent_budget",
        "link_task_requirement",
        "record_ac_verification",
        "release_task",
        "retire_agent",
        "send_agent_message",
        "set_external_config",
        "suspend_agent",
        "update_prd",
        "update_project_accessed",
        "update_project_path",
        "update_sprint",
        "update_sync_mapping",
        "update_task",
        "update_worktree",
        "upsert_requirement",
    }

    def test_known_server_methods_covered(self):
        missing = self.KNOWN_SERVER_METHODS - _ALLOWED_OPS
        assert missing == set(), f"Methods missing from allowlist: {missing}"

    def test_allowlist_covers_known_methods(self):
        extra = _ALLOWED_OPS - self.KNOWN_SERVER_METHODS
        assert extra == set(), f"Extra methods in allowlist: {extra}"
