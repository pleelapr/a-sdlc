"""Tests for sprint-run template behaviors.

Validates that the MCP tools referenced by the sprint-run.md template
work correctly for the worktree-based workflow:
- Mode detection with git safety config gating
- Resume state detection via list_worktrees()
- Branch completion via complete_prd_worktree()
- Config-aware option filtering (disabled operations not offered)
"""

import re
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# =============================================================================
# Template Content Validation
# =============================================================================


class TestTemplateContent:
    """Verify sprint-run.md template references correct MCP tools and patterns."""

    @pytest.fixture(autouse=True)
    def load_template(self):
        """Load the sprint-run template content."""
        template_path = (
            Path(__file__).parent.parent
            / "src"
            / "a_sdlc"
            / "templates"
            / "sprint-run.md"
        )
        self.content = template_path.read_text(encoding="utf-8")

    def test_template_references_list_worktrees_for_resume(self):
        """Resume state should use list_worktrees, not .state.json."""
        assert "mcp__asdlc__list_worktrees" in self.content
        assert ".state.json" not in self.content

    def test_template_references_complete_prd_worktree(self):
        """Branch completion should use complete_prd_worktree."""
        assert "mcp__asdlc__complete_prd_worktree" in self.content

    def test_template_references_manage_git_safety(self):
        """Template should check git safety config before mode detection."""
        assert "mcp__asdlc__manage_git_safety" in self.content

    def test_template_references_worktree_enabled_check(self):
        """Template should check worktree_enabled flag."""
        assert "worktree_enabled" in self.content

    def test_template_documents_config_gated_options(self):
        """Template should document that disabled operations are not presented."""
        # Check for the config-aware completion option filtering
        assert "auto_pr" in self.content
        assert "auto_merge" in self.content
        assert "disabled" in self.content.lower()

    def test_template_documents_four_completion_actions(self):
        """Template should document all four completion actions."""
        assert '"keep"' in self.content
        assert '"discard"' in self.content
        assert '"pr"' in self.content
        assert '"merge"' in self.content

    def test_template_no_state_json_references(self):
        """No references to deprecated .state.json file."""
        # The old resume mechanism used .worktrees/.state.json
        assert ".state.json" not in self.content

    def test_template_references_branch_naming_convention(self):
        """Template should use sprint/ prefix for branch naming."""
        assert "sprint/" in self.content
        # Should show the branch pattern in examples
        assert re.search(r"sprint/PROJ-S\d+/PROJ-P\d+", self.content)

    def test_template_documents_db_backed_resume(self):
        """Template should mention DB-backed resume."""
        assert "DB" in self.content or "database" in self.content.lower()

    def test_template_documents_manage_git_safety_configure(self):
        """Template should tell users how to enable worktree isolation."""
        assert "manage_git_safety" in self.content

    def test_template_keep_and_discard_always_available(self):
        """Template should document that keep and discard are always available."""
        # These are the two actions that don't depend on config
        assert "always available" in self.content.lower() or (
            "keep" in self.content and "discard" in self.content
        )

    def test_template_worktree_disabled_fallback_to_simple(self):
        """Template should document fallback to simple mode when worktree disabled."""
        assert "simple mode" in self.content.lower() or "Simple Mode" in self.content
        # Should mention the fallback scenario
        assert "worktree_enabled" in self.content


# =============================================================================
# Mode Detection with Git Safety Config
# =============================================================================


class TestModeDetectionWithConfig:
    """Test that git safety config gates isolated mode."""

    def _enabled_config(self, worktree_enabled=True, auto_pr=False, auto_merge=False):
        from a_sdlc.core.git_config import GitSafetyConfig

        return GitSafetyConfig(
            worktree_enabled=worktree_enabled,
            auto_pr=auto_pr,
            auto_merge=auto_merge,
        )

    @patch("a_sdlc.server.load_git_safety_config")
    @patch("a_sdlc.server.os.getcwd")
    def test_setup_worktree_blocked_when_disabled(self, mock_getcwd, mock_config, tmp_path):
        """setup_prd_worktree returns disabled status when worktree_enabled=False."""
        from a_sdlc.server import setup_prd_worktree

        mock_getcwd.return_value = str(tmp_path)
        mock_config.return_value = self._enabled_config(worktree_enabled=False)

        result = setup_prd_worktree(prd_id="TEST-P0001", sprint_id="TEST-S0001")

        assert result["status"] == "disabled"
        assert "worktree_enabled" in result["message"]

    @patch("a_sdlc.server.load_git_safety_config")
    @patch("a_sdlc.server.subprocess.run")
    @patch("a_sdlc.server._get_current_project_id")
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_setup_worktree_allowed_when_enabled(
        self, mock_getcwd, mock_get_db, mock_pid, mock_run, mock_config, tmp_path
    ):
        """setup_prd_worktree proceeds when worktree_enabled=True."""
        from a_sdlc.server import setup_prd_worktree

        mock_getcwd.return_value = str(tmp_path)
        mock_config.return_value = self._enabled_config(worktree_enabled=True)
        mock_pid.return_value = "test-project"
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_project.return_value = {"shortname": "TEST"}
        mock_db.get_worktree_by_prd.return_value = None
        mock_db.get_next_worktree_id.return_value = "TEST-W0001"
        (tmp_path / ".gitignore").write_text("")
        mock_run.return_value = MagicMock(returncode=0)

        result = setup_prd_worktree(prd_id="TEST-P0001", sprint_id="TEST-S0001")

        assert result["status"] == "created"

    def test_manage_git_safety_get_returns_effective(self):
        """manage_git_safety('get') returns effective config with sources."""
        from a_sdlc.server import manage_git_safety

        with patch("a_sdlc.server.get_effective_config_summary") as mock_summary:
            mock_summary.return_value = {
                "effective": {
                    "auto_pr": False,
                    "auto_merge": False,
                    "worktree_enabled": False,
                },
                "sources": {
                    "auto_pr": "default",
                    "auto_merge": "default",
                    "worktree_enabled": "default",
                },
                "always_require_confirmation": ["branch_delete", "force_push"],
            }

            result = manage_git_safety("get")

            assert result["status"] == "ok"
            assert result["config"]["effective"]["worktree_enabled"] is False
            assert result["config"]["effective"]["auto_pr"] is False


# =============================================================================
# Resume State Detection via list_worktrees
# =============================================================================


class TestResumeViaListWorktrees:
    """Test resume state detection using list_worktrees MCP tool."""

    def _make_worktree(self, prd_id, status="active", sprint_id="TEST-S0001", base_path=None):
        path = str(base_path / ".worktrees" / prd_id) if base_path else str(Path(tempfile.gettempdir()) / ".worktrees" / prd_id)
        return {
            "id": f"TEST-W{prd_id[-4:]}",
            "project_id": "test-project",
            "prd_id": prd_id,
            "sprint_id": sprint_id,
            "branch_name": f"sprint/{sprint_id}/{prd_id}",
            "path": path,
            "status": status,
            "created_at": "2026-01-01T00:00:00+00:00",
            "cleaned_at": None,
        }

    @patch("a_sdlc.server._get_current_project_id")
    @patch("a_sdlc.server.get_db")
    def test_resume_detected_when_active_worktrees_exist(self, mock_get_db, mock_pid):
        """list_worktrees returns active worktrees for resume detection."""
        from a_sdlc.server import list_worktrees

        mock_pid.return_value = "test-project"
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.list_worktrees.return_value = [
            self._make_worktree("TEST-P0001", status="active"),
            self._make_worktree("TEST-P0002", status="completed"),
        ]

        result = list_worktrees(sprint_id="TEST-S0001")

        assert result["status"] == "ok"
        assert result["count"] == 2
        # Agent can check which are active vs completed
        statuses = [w["status"] for w in result["worktrees"]]
        assert "active" in statuses
        assert "completed" in statuses

    @patch("a_sdlc.server._get_current_project_id")
    @patch("a_sdlc.server.get_db")
    def test_no_resume_when_no_worktrees(self, mock_get_db, mock_pid):
        """list_worktrees returns empty when no previous run exists."""
        from a_sdlc.server import list_worktrees

        mock_pid.return_value = "test-project"
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.list_worktrees.return_value = []

        result = list_worktrees(sprint_id="TEST-S0001")

        assert result["status"] == "ok"
        assert result["count"] == 0
        # No resume needed

    @patch("a_sdlc.server._get_current_project_id")
    @patch("a_sdlc.server.get_db")
    def test_sprint_filter_isolates_correct_sprint(self, mock_get_db, mock_pid):
        """list_worktrees sprint_id filter passes through to DB."""
        from a_sdlc.server import list_worktrees

        mock_pid.return_value = "test-project"
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.list_worktrees.return_value = []

        list_worktrees(sprint_id="TEST-S0002")

        mock_db.list_worktrees.assert_called_once_with(
            "test-project", status=None, sprint_id="TEST-S0002"
        )

    @patch("a_sdlc.server._get_current_project_id")
    @patch("a_sdlc.server.get_db")
    def test_worktree_fields_include_resume_info(self, mock_get_db, mock_pid):
        """Each worktree entry has fields needed for resume decisions."""
        from a_sdlc.server import list_worktrees

        mock_pid.return_value = "test-project"
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.list_worktrees.return_value = [self._make_worktree("TEST-P0001")]

        result = list_worktrees(sprint_id="TEST-S0001")

        w = result["worktrees"][0]
        # Fields needed for resume logic
        assert "status" in w  # active/completed/cleaned
        assert "prd_id" in w  # which PRD to resume
        assert "branch_name" in w  # for display
        assert "sprint_id" in w  # for sprint matching

    @patch("a_sdlc.server._get_current_project_id")
    @patch("a_sdlc.server.get_db")
    def test_filter_by_active_status_for_resume(self, mock_get_db, mock_pid):
        """Can filter worktrees by status=active to find resumable ones."""
        from a_sdlc.server import list_worktrees

        mock_pid.return_value = "test-project"
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.list_worktrees.return_value = [
            self._make_worktree("TEST-P0001", status="active"),
        ]

        result = list_worktrees(status="active", sprint_id="TEST-S0001")

        assert result["filters"]["status"] == "active"
        assert result["filters"]["sprint_id"] == "TEST-S0001"
        mock_db.list_worktrees.assert_called_once_with(
            "test-project", status="active", sprint_id="TEST-S0001"
        )


# =============================================================================
# Branch Completion via complete_prd_worktree
# =============================================================================


class TestBranchCompletion:
    """Test complete_prd_worktree with config-aware action filtering."""

    def _make_worktree_record(self, tmp_path, prd_id="TEST-P0001"):
        return {
            "id": "TEST-W0001",
            "project_id": "test-project",
            "prd_id": prd_id,
            "sprint_id": "TEST-S0001",
            "branch_name": f"sprint/TEST-S0001/{prd_id}",
            "path": str(tmp_path / ".worktrees" / prd_id),
            "status": "active",
            "created_at": "2026-01-01T00:00:00+00:00",
            "cleaned_at": None,
        }

    def _make_config(self, auto_pr=False, auto_merge=False, worktree_enabled=True):
        from a_sdlc.core.git_config import GitSafetyConfig

        return GitSafetyConfig(
            auto_pr=auto_pr,
            auto_merge=auto_merge,
            worktree_enabled=worktree_enabled,
        )

    # --- keep action (always available) ---

    @patch("a_sdlc.server.load_git_safety_config")
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_keep_always_works(self, mock_getcwd, mock_get_db, mock_config, tmp_path):
        """keep action works regardless of git safety config."""
        from a_sdlc.server import complete_prd_worktree

        mock_getcwd.return_value = str(tmp_path)
        mock_config.return_value = self._make_config(auto_pr=False, auto_merge=False)
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_worktree_by_prd.return_value = self._make_worktree_record(tmp_path)

        result = complete_prd_worktree(prd_id="TEST-P0001", action="keep")

        assert result["status"] == "kept"
        assert result["branch"] == "sprint/TEST-S0001/TEST-P0001"

    # --- discard action (always available, requires confirmation) ---

    @patch("a_sdlc.server.load_git_safety_config")
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_discard_always_available_but_requires_confirm(
        self, mock_getcwd, mock_get_db, mock_config, tmp_path
    ):
        """discard is always available but requires confirmation."""
        from a_sdlc.server import complete_prd_worktree

        mock_getcwd.return_value = str(tmp_path)
        mock_config.return_value = self._make_config(auto_pr=False, auto_merge=False)
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_worktree_by_prd.return_value = self._make_worktree_record(tmp_path)

        result = complete_prd_worktree(prd_id="TEST-P0001", action="discard")

        assert result["status"] == "confirmation_required"
        assert "confirm_discard" in result["message"]

    @patch("a_sdlc.server.cleanup_prd_worktree")
    @patch("a_sdlc.server.load_git_safety_config")
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_discard_confirmed_proceeds(
        self, mock_getcwd, mock_get_db, mock_config, mock_cleanup, tmp_path
    ):
        """discard with confirm_discard=True proceeds to cleanup."""
        from a_sdlc.server import complete_prd_worktree

        mock_getcwd.return_value = str(tmp_path)
        mock_config.return_value = self._make_config()
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_worktree_by_prd.return_value = self._make_worktree_record(tmp_path)
        mock_cleanup.return_value = {"status": "cleaned"}

        complete_prd_worktree(
            prd_id="TEST-P0001", action="discard", confirm_discard=True
        )

        mock_cleanup.assert_called_once_with(
            prd_id="TEST-P0001",
            remove_branch=True,
            confirm_branch_delete=True,
            docker_cleanup=True,
        )

    # --- pr action (config-gated) ---

    @patch("a_sdlc.server.load_git_safety_config")
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_pr_blocked_when_auto_pr_disabled(
        self, mock_getcwd, mock_get_db, mock_config, tmp_path
    ):
        """pr action returns disabled status when auto_pr is False."""
        from a_sdlc.server import complete_prd_worktree

        mock_getcwd.return_value = str(tmp_path)
        mock_config.return_value = self._make_config(auto_pr=False)
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_worktree_by_prd.return_value = self._make_worktree_record(tmp_path)

        result = complete_prd_worktree(prd_id="TEST-P0001", action="pr")

        assert result["status"] == "disabled"
        assert "auto_pr" in result["message"]

    @patch("a_sdlc.server.create_prd_pr")
    @patch("a_sdlc.server.load_git_safety_config")
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_pr_proceeds_when_auto_pr_enabled(
        self, mock_getcwd, mock_get_db, mock_config, mock_create_pr, tmp_path
    ):
        """pr action delegates to create_prd_pr when auto_pr is True."""
        from a_sdlc.server import complete_prd_worktree

        mock_getcwd.return_value = str(tmp_path)
        mock_config.return_value = self._make_config(auto_pr=True)
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_worktree_by_prd.return_value = self._make_worktree_record(tmp_path)
        mock_create_pr.return_value = {
            "status": "created",
            "pr_url": "https://github.com/org/repo/pull/1",
        }

        result = complete_prd_worktree(prd_id="TEST-P0001", action="pr")

        assert result["status"] == "created"
        mock_create_pr.assert_called_once()

    # --- merge action (config-gated) ---

    @patch("a_sdlc.server.load_git_safety_config")
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_merge_blocked_when_auto_merge_disabled(
        self, mock_getcwd, mock_get_db, mock_config, tmp_path
    ):
        """merge action returns disabled status when auto_merge is False."""
        from a_sdlc.server import complete_prd_worktree

        mock_getcwd.return_value = str(tmp_path)
        mock_config.return_value = self._make_config(auto_merge=False)
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_worktree_by_prd.return_value = self._make_worktree_record(tmp_path)

        result = complete_prd_worktree(prd_id="TEST-P0001", action="merge")

        assert result["status"] == "disabled"
        assert "auto_merge" in result["message"]

    @patch("a_sdlc.server.cleanup_prd_worktree")
    @patch("a_sdlc.server.subprocess.run")
    @patch("a_sdlc.server.load_git_safety_config")
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_merge_proceeds_when_auto_merge_enabled(
        self, mock_getcwd, mock_get_db, mock_config, mock_run, mock_cleanup, tmp_path
    ):
        """merge action proceeds when auto_merge is True."""
        from a_sdlc.server import complete_prd_worktree

        mock_getcwd.return_value = str(tmp_path)
        mock_config.return_value = self._make_config(auto_merge=True)
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_worktree_by_prd.return_value = self._make_worktree_record(tmp_path)
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="refs/remotes/origin/main\n"),
            MagicMock(returncode=0),
        ]
        mock_cleanup.return_value = {"status": "cleaned"}

        result = complete_prd_worktree(prd_id="TEST-P0001", action="merge")

        assert result["status"] == "merged"

    # --- invalid action ---

    def test_invalid_action_rejected(self):
        """Invalid action returns error."""
        from a_sdlc.server import complete_prd_worktree

        result = complete_prd_worktree(prd_id="TEST-P0001", action="rebase")

        assert result["status"] == "error"
        assert "Invalid action" in result["message"]

    # --- no worktree found ---

    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_not_found_when_no_worktree(self, mock_getcwd, mock_get_db, tmp_path):
        """Returns not_found when no worktree exists for prd_id."""
        from a_sdlc.server import complete_prd_worktree

        mock_getcwd.return_value = str(tmp_path)
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_worktree_by_prd.return_value = None

        result = complete_prd_worktree(prd_id="MISSING-P0001", action="keep")

        assert result["status"] == "not_found"


# =============================================================================
# Git Safety Config — Operation Allowed Checks
# =============================================================================


class TestGitSafetyConfigOperations:
    """Test GitSafetyConfig.is_operation_allowed for sprint-run decisions."""

    def test_default_config_all_disabled(self):
        """Default config has all operations disabled."""
        from a_sdlc.core.git_config import GitSafetyConfig

        config = GitSafetyConfig()
        assert config.is_operation_allowed("auto_pr") is False
        assert config.is_operation_allowed("auto_merge") is False
        assert config.is_operation_allowed("worktree_enabled") is False

    def test_worktree_enabled_check(self):
        """worktree_enabled controls isolated mode gating."""
        from a_sdlc.core.git_config import GitSafetyConfig

        config = GitSafetyConfig(worktree_enabled=True)
        assert config.is_operation_allowed("worktree_enabled") is True

        config = GitSafetyConfig(worktree_enabled=False)
        assert config.is_operation_allowed("worktree_enabled") is False

    def test_auto_pr_check(self):
        """auto_pr controls PR creation option availability."""
        from a_sdlc.core.git_config import GitSafetyConfig

        config = GitSafetyConfig(auto_pr=True)
        assert config.is_operation_allowed("auto_pr") is True

        config = GitSafetyConfig(auto_pr=False)
        assert config.is_operation_allowed("auto_pr") is False

    def test_auto_merge_check(self):
        """auto_merge controls merge option availability."""
        from a_sdlc.core.git_config import GitSafetyConfig

        config = GitSafetyConfig(auto_merge=True)
        assert config.is_operation_allowed("auto_merge") is True

        config = GitSafetyConfig(auto_merge=False)
        assert config.is_operation_allowed("auto_merge") is False

    def test_destructive_operations_always_blocked(self):
        """force_push and branch_delete always return False."""
        from a_sdlc.core.git_config import GitSafetyConfig

        config = GitSafetyConfig(auto_pr=True, auto_merge=True, worktree_enabled=True)
        assert config.is_operation_allowed("force_push") is False
        assert config.is_operation_allowed("branch_delete") is False

    def test_requires_confirmation_for_destructive(self):
        """Destructive operations always require confirmation."""
        from a_sdlc.core.git_config import GitSafetyConfig

        config = GitSafetyConfig()
        assert config.requires_confirmation("force_push") is True
        assert config.requires_confirmation("branch_delete") is True
        assert config.requires_confirmation("auto_pr") is False

    def test_config_to_dict(self):
        """Config serializes to dict with all keys."""
        from a_sdlc.core.git_config import GitSafetyConfig

        config = GitSafetyConfig(auto_pr=True, auto_merge=False, worktree_enabled=True)
        d = config.to_dict()
        assert d == {
            "auto_commit": False,
            "auto_pr": True,
            "auto_merge": False,
            "worktree_enabled": True,
        }


# =============================================================================
# Config Loading — Layered Merge
# =============================================================================


class TestConfigLayeredLoading:
    """Test that git safety config loads with correct priority."""

    def test_defaults_when_no_config_files(self, tmp_path):
        """Without config files, all operations default to False."""
        from a_sdlc.core.git_config import load_git_safety_config

        config = load_git_safety_config(project_dir=tmp_path)
        assert config.auto_pr is False
        assert config.auto_merge is False
        assert config.worktree_enabled is False

    def test_project_config_overrides_global(self, tmp_path):
        """Project config takes precedence over global config."""
        from a_sdlc.core.git_config import load_git_safety_config

        # Create project config enabling worktree
        sdlc_dir = tmp_path / ".sdlc"
        sdlc_dir.mkdir()
        (sdlc_dir / "config.yaml").write_text("git:\n  worktree_enabled: true\n")

        with patch("a_sdlc.core.git_config.GLOBAL_CONFIG_FILE", tmp_path / "global.yaml"):
            # Global has worktree disabled
            (tmp_path / "global.yaml").write_text("git:\n  worktree_enabled: false\n")

            config = load_git_safety_config(project_dir=tmp_path)
            # Project override wins
            assert config.worktree_enabled is True

    def test_global_config_used_when_no_project_config(self, tmp_path):
        """Global config applies when no project config exists."""
        from a_sdlc.core.git_config import load_git_safety_config

        with patch("a_sdlc.core.git_config.GLOBAL_CONFIG_FILE", tmp_path / "global.yaml"):
            (tmp_path / "global.yaml").write_text("git:\n  auto_pr: true\n")

            config = load_git_safety_config(project_dir=tmp_path)
            assert config.auto_pr is True
            # Others remain default
            assert config.auto_merge is False
            assert config.worktree_enabled is False


# =============================================================================
# create_prd_pr Config Gating
# =============================================================================


class TestCreatePrdPrConfigGating:
    """Test that create_prd_pr respects auto_pr config."""

    @patch("a_sdlc.server.load_git_safety_config")
    @patch("a_sdlc.server.os.getcwd")
    def test_create_prd_pr_blocked_when_disabled(self, mock_getcwd, mock_config, tmp_path):
        """create_prd_pr returns disabled when auto_pr is False."""
        from a_sdlc.server import create_prd_pr

        mock_getcwd.return_value = str(tmp_path)
        from a_sdlc.core.git_config import GitSafetyConfig

        mock_config.return_value = GitSafetyConfig(auto_pr=False)

        result = create_prd_pr(prd_id="TEST-P0001", sprint_id="TEST-S0001")

        assert result["status"] == "disabled"
        assert "auto_pr" in result["message"]

    @patch("a_sdlc.server.subprocess.run")
    @patch("a_sdlc.server.load_git_safety_config")
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_create_prd_pr_requires_worktree_record(
        self, mock_getcwd, mock_get_db, mock_config, mock_run, tmp_path
    ):
        """create_prd_pr returns not_found when no worktree exists."""
        from a_sdlc.core.git_config import GitSafetyConfig
        from a_sdlc.server import create_prd_pr

        mock_getcwd.return_value = str(tmp_path)
        mock_config.return_value = GitSafetyConfig(auto_pr=True)
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_worktree_by_prd.return_value = None

        result = create_prd_pr(prd_id="TEST-P0001", sprint_id="TEST-S0001")

        assert result["status"] == "not_found"

    @patch("a_sdlc.server.subprocess.run")
    @patch("a_sdlc.server.load_git_safety_config")
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_create_prd_pr_updates_worktree_status(
        self, mock_getcwd, mock_get_db, mock_config, mock_run, tmp_path
    ):
        """create_prd_pr stores pr_url without changing worktree status."""
        from a_sdlc.core.git_config import GitSafetyConfig
        from a_sdlc.server import create_prd_pr

        mock_getcwd.return_value = str(tmp_path)
        mock_config.return_value = GitSafetyConfig(auto_pr=True)
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_worktree_by_prd.return_value = {
            "id": "TEST-W0001",
            "branch_name": "sprint/TEST-S0001/TEST-P0001",
        }
        mock_db.get_prd.return_value = {"title": "Auth Feature"}

        # git push succeeds, gh pr create returns URL
        mock_run.side_effect = [
            MagicMock(returncode=0),  # git push
            MagicMock(returncode=0, stdout="https://github.com/org/repo/pull/42\n"),  # gh pr create
        ]

        result = create_prd_pr(prd_id="TEST-P0001", sprint_id="TEST-S0001")

        assert result["status"] == "created"
        assert result["pr_url"] == "https://github.com/org/repo/pull/42"
        mock_db.update_worktree.assert_called_once_with(
            "TEST-W0001", pr_url="https://github.com/org/repo/pull/42"
        )


# =============================================================================
# Branch Naming Convention
# =============================================================================


class TestBranchNamingConvention:
    """Verify branch naming uses sprint/ prefix convention."""

    @patch("a_sdlc.server.load_git_safety_config")
    @patch("a_sdlc.server.subprocess.run")
    @patch("a_sdlc.server._get_current_project_id")
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_branch_uses_sprint_prefix(
        self, mock_getcwd, mock_get_db, mock_pid, mock_run, mock_config, tmp_path
    ):
        """setup_prd_worktree creates branch with sprint/ prefix."""
        from a_sdlc.core.git_config import GitSafetyConfig
        from a_sdlc.server import setup_prd_worktree

        mock_getcwd.return_value = str(tmp_path)
        mock_config.return_value = GitSafetyConfig(worktree_enabled=True)
        mock_pid.return_value = "test-project"
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_project.return_value = {"shortname": "TEST"}
        mock_db.get_worktree_by_prd.return_value = None
        mock_db.get_next_worktree_id.return_value = "TEST-W0001"
        (tmp_path / ".gitignore").write_text("")
        mock_run.return_value = MagicMock(returncode=0)

        result = setup_prd_worktree(prd_id="TEST-P0001", sprint_id="TEST-S0001")

        assert result["status"] == "created"
        assert result["worktree"]["branch"] == "sprint/TEST-S0001/TEST-P0001"

        # Verify git branch command used sprint/ prefix
        branch_call = mock_run.call_args_list[0]
        assert "sprint/TEST-S0001/TEST-P0001" in branch_call[0][0]

    @patch("a_sdlc.server.load_git_safety_config")
    @patch("a_sdlc.server.subprocess.run")
    @patch("a_sdlc.server._get_current_project_id")
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_branch_recorded_in_db(
        self, mock_getcwd, mock_get_db, mock_pid, mock_run, mock_config, tmp_path
    ):
        """DB record has correct branch name with sprint/ prefix."""
        from a_sdlc.core.git_config import GitSafetyConfig
        from a_sdlc.server import setup_prd_worktree

        mock_getcwd.return_value = str(tmp_path)
        mock_config.return_value = GitSafetyConfig(worktree_enabled=True)
        mock_pid.return_value = "test-project"
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_project.return_value = {"shortname": "TEST"}
        mock_db.get_worktree_by_prd.return_value = None
        mock_db.get_next_worktree_id.return_value = "TEST-W0001"
        (tmp_path / ".gitignore").write_text("")
        mock_run.return_value = MagicMock(returncode=0)

        setup_prd_worktree(prd_id="TEST-P0001", sprint_id="TEST-S0001")

        mock_db.create_worktree.assert_called_once()
        call_kwargs = mock_db.create_worktree.call_args[1]
        assert call_kwargs["branch_name"] == "sprint/TEST-S0001/TEST-P0001"


# =============================================================================
# Completion Action — Config Awareness Integration
# =============================================================================


class TestCompletionConfigAwareness:
    """Test the full flow: config check → action filtering → execution."""

    def _make_worktree_record(self, tmp_path, prd_id="TEST-P0001"):
        return {
            "id": "TEST-W0001",
            "project_id": "test-project",
            "prd_id": prd_id,
            "sprint_id": "TEST-S0001",
            "branch_name": f"sprint/TEST-S0001/{prd_id}",
            "path": str(tmp_path / ".worktrees" / prd_id),
            "status": "active",
            "created_at": "2026-01-01T00:00:00+00:00",
            "cleaned_at": None,
        }

    def test_all_operations_disabled_by_default(self):
        """With default config, only keep and discard should work."""
        from a_sdlc.core.git_config import GitSafetyConfig

        config = GitSafetyConfig()

        # These are the only options that should be presented
        # keep: always available (no config check)
        # discard: always available (requires confirmation, not config)
        assert config.is_operation_allowed("auto_pr") is False
        assert config.is_operation_allowed("auto_merge") is False
        # keep and discard don't use is_operation_allowed

    @patch("a_sdlc.server.load_git_safety_config")
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_pr_and_merge_both_disabled(self, mock_getcwd, mock_get_db, mock_config, tmp_path):
        """When both auto_pr and auto_merge are disabled, both actions return disabled."""
        from a_sdlc.core.git_config import GitSafetyConfig
        from a_sdlc.server import complete_prd_worktree

        mock_getcwd.return_value = str(tmp_path)
        mock_config.return_value = GitSafetyConfig()  # All defaults
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_worktree_by_prd.return_value = self._make_worktree_record(tmp_path)

        pr_result = complete_prd_worktree(prd_id="TEST-P0001", action="pr")
        assert pr_result["status"] == "disabled"

        merge_result = complete_prd_worktree(prd_id="TEST-P0001", action="merge")
        assert merge_result["status"] == "disabled"

    @patch("a_sdlc.server.create_prd_pr")
    @patch("a_sdlc.server.load_git_safety_config")
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_pr_enabled_merge_disabled(
        self, mock_getcwd, mock_get_db, mock_config, mock_create_pr, tmp_path
    ):
        """When auto_pr=True but auto_merge=False, only PR works."""
        from a_sdlc.core.git_config import GitSafetyConfig
        from a_sdlc.server import complete_prd_worktree

        mock_getcwd.return_value = str(tmp_path)
        mock_config.return_value = GitSafetyConfig(auto_pr=True, auto_merge=False)
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_worktree_by_prd.return_value = self._make_worktree_record(tmp_path)
        mock_create_pr.return_value = {"status": "created", "pr_url": "https://example.com/pr/1"}

        pr_result = complete_prd_worktree(prd_id="TEST-P0001", action="pr")
        assert pr_result["status"] == "created"

        merge_result = complete_prd_worktree(prd_id="TEST-P0001", action="merge")
        assert merge_result["status"] == "disabled"

    @patch("a_sdlc.server.cleanup_prd_worktree")
    @patch("a_sdlc.server.subprocess.run")
    @patch("a_sdlc.server.load_git_safety_config")
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_merge_enabled_pr_disabled(
        self, mock_getcwd, mock_get_db, mock_config, mock_run, mock_cleanup, tmp_path
    ):
        """When auto_merge=True but auto_pr=False, only merge works."""
        from a_sdlc.core.git_config import GitSafetyConfig
        from a_sdlc.server import complete_prd_worktree

        mock_getcwd.return_value = str(tmp_path)
        mock_config.return_value = GitSafetyConfig(auto_pr=False, auto_merge=True)
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_worktree_by_prd.return_value = self._make_worktree_record(tmp_path)
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="refs/remotes/origin/main\n"),
            MagicMock(returncode=0),
        ]
        mock_cleanup.return_value = {"status": "cleaned"}

        merge_result = complete_prd_worktree(prd_id="TEST-P0001", action="merge")
        assert merge_result["status"] == "merged"

        pr_result = complete_prd_worktree(prd_id="TEST-P0001", action="pr")
        assert pr_result["status"] == "disabled"


# =============================================================================
# Subagent Type Mapping Validation
# =============================================================================


class TestSubagentTypeMapping:
    """Validate subagent_type specialization across templates."""

    @pytest.fixture(autouse=True)
    def load_templates(self):
        """Load all affected template files."""
        base = Path(__file__).parent.parent / "src" / "a_sdlc" / "templates"
        self.round_table = (base / "_round-table-blocks.md").read_text(encoding="utf-8")
        self.task_start = (base / "task-start.md").read_text(encoding="utf-8")
        self.task_complete = (base / "task-complete.md").read_text(encoding="utf-8")
        self.sprint_run = (base / "sprint-run.md").read_text(encoding="utf-8")
        self.investigate = (base / "investigate.md").read_text(encoding="utf-8")

    # AC-001: Zero general-purpose in task-start, task-complete, _round-table-blocks
    def test_no_general_purpose_in_round_table(self):
        assert 'subagent_type="general-purpose"' not in self.round_table

    def test_no_general_purpose_in_task_start(self):
        assert 'subagent_type="general-purpose"' not in self.task_start

    def test_no_general_purpose_in_task_complete(self):
        assert 'subagent_type="general-purpose"' not in self.task_complete

    # AC-002: sprint-run has general-purpose only at PRD agent sites (exactly 2)
    def test_sprint_run_general_purpose_only_at_prd_agents(self):
        count = self.sprint_run.count('subagent_type="general-purpose"')
        assert count == 2, f"Expected 2 PRD agent dispatches, found {count}"

    # AC-003: Section D exists with all personas
    def test_section_d_exists(self):
        assert "## Section D" in self.round_table

    def test_section_d_contains_all_personas(self):
        personas = [
            "sdlc-backend-engineer", "sdlc-frontend-engineer",
            "sdlc-devops-engineer", "sdlc-security-engineer",
            "sdlc-architect", "sdlc-qa-engineer", "sdlc-product-manager",
        ]
        for persona in personas:
            assert persona in self.round_table, f"Missing persona: {persona}"

    # Reviewer-specific tests
    def test_task_start_reviewer_uses_qa(self):
        assert 'subagent_type="sdlc-qa-engineer"' in self.task_start

    def test_task_complete_reviewer_uses_qa(self):
        assert 'subagent_type="sdlc-qa-engineer"' in self.task_complete

    def test_sprint_run_reviewer_uses_qa(self):
        assert 'subagent_type="sdlc-qa-engineer"' in self.sprint_run

    # investigate template test
    def test_no_general_purpose_in_investigate(self):
        assert 'subagent_type="general-purpose"' not in self.investigate
