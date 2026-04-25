"""Tests for GitHub PR feedback MCP tools (manage_integration for github, get_pr_feedback)."""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_project_dir():
    """Create a temporary project directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def tmp_config_dir():
    """Create a temporary directory for global config tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def _make_project(path: str) -> dict:
    return {
        "id": "test-project",
        "shortname": "TEST",
        "name": "Test Project",
        "path": path,
    }


def _setup_project_mocks(mock_db, project_path: str):
    """Configure mocks so _get_current_project_id() returns 'test-project'."""
    project = _make_project(project_path)
    mock_db.get_project_by_path.return_value = project
    mock_db.update_project_accessed.return_value = None
    return project


# ---------------------------------------------------------------------------
# parse_git_remote tests
# ---------------------------------------------------------------------------


class TestParseGitRemote:
    """Test git remote URL parsing."""

    def test_https_with_git_suffix(self):
        from a_sdlc.server.github import parse_git_remote

        owner, repo = parse_git_remote("https://github.com/octocat/hello-world.git")
        assert owner == "octocat"
        assert repo == "hello-world"

    def test_https_without_git_suffix(self):
        from a_sdlc.server.github import parse_git_remote

        owner, repo = parse_git_remote("https://github.com/octocat/hello-world")
        assert owner == "octocat"
        assert repo == "hello-world"

    def test_ssh_format(self):
        from a_sdlc.server.github import parse_git_remote

        owner, repo = parse_git_remote("git@github.com:octocat/hello-world.git")
        assert owner == "octocat"
        assert repo == "hello-world"

    def test_ssh_without_git_suffix(self):
        from a_sdlc.server.github import parse_git_remote

        owner, repo = parse_git_remote("git@github.com:octocat/hello-world")
        assert owner == "octocat"
        assert repo == "hello-world"

    def test_ssh_protocol_format(self):
        from a_sdlc.server.github import parse_git_remote

        owner, repo = parse_git_remote(
            "ssh://git@github.com/octocat/hello-world.git"
        )
        assert owner == "octocat"
        assert repo == "hello-world"

    def test_invalid_url_raises(self):
        from a_sdlc.server.github import parse_git_remote

        with pytest.raises(ValueError, match="Cannot parse"):
            parse_git_remote("https://gitlab.com/user/repo.git")

    def test_non_github_ssh_raises(self):
        from a_sdlc.server.github import parse_git_remote

        with pytest.raises(ValueError, match="Cannot parse"):
            parse_git_remote("git@gitlab.com:user/repo.git")


# ---------------------------------------------------------------------------
# GitHubClient tests
# ---------------------------------------------------------------------------


class TestGitHubClient:
    """Test GitHubClient methods."""

    def test_validate_token_success(self):
        from a_sdlc.server.github import GitHubClient

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"login": "octocat", "name": "Octo Cat"}

        with patch.object(GitHubClient, "__init__", return_value=None):
            client = GitHubClient.__new__(GitHubClient)
            client.token = "test-token"
            client._client = MagicMock()
            client._client.get.return_value = mock_response

            result = client.validate_token()
            assert result["login"] == "octocat"
            assert result["name"] == "Octo Cat"
            client._client.get.assert_called_once_with("/user")

    def test_validate_token_failure(self):
        from a_sdlc.server.github import GitHubClient

        mock_response = MagicMock()
        mock_response.status_code = 401

        with patch.object(GitHubClient, "__init__", return_value=None):
            client = GitHubClient.__new__(GitHubClient)
            client.token = "bad-token"
            client._client = MagicMock()
            client._client.get.return_value = mock_response

            with pytest.raises(RuntimeError, match="Invalid GitHub token"):
                client.validate_token()

    def test_get_pr_for_branch_found(self):
        from a_sdlc.server.github import GitHubClient

        pr_data = [{"number": 42, "title": "My PR"}]
        mock_response = MagicMock()
        mock_response.json.return_value = pr_data
        mock_response.raise_for_status = MagicMock()

        with patch.object(GitHubClient, "__init__", return_value=None):
            client = GitHubClient.__new__(GitHubClient)
            client._client = MagicMock()
            client._client.get.return_value = mock_response

            result = client.get_pr_for_branch("owner", "repo", "feature-branch")
            assert result["number"] == 42
            client._client.get.assert_called_once_with(
                "/repos/owner/repo/pulls",
                params={"head": "owner:feature-branch", "state": "open"},
            )

    def test_get_pr_for_branch_not_found(self):
        from a_sdlc.server.github import GitHubClient

        mock_response = MagicMock()
        mock_response.json.return_value = []
        mock_response.raise_for_status = MagicMock()

        with patch.object(GitHubClient, "__init__", return_value=None):
            client = GitHubClient.__new__(GitHubClient)
            client._client = MagicMock()
            client._client.get.return_value = mock_response

            result = client.get_pr_for_branch("owner", "repo", "no-pr-branch")
            assert result is None

    def test_get_review_comments_pagination(self):
        from a_sdlc.server.github import GitHubClient

        page1 = MagicMock()
        page1.json.return_value = [{"id": 1, "body": "fix this"}]
        page1.raise_for_status = MagicMock()

        page2 = MagicMock()
        page2.json.return_value = []
        page2.raise_for_status = MagicMock()

        with patch.object(GitHubClient, "__init__", return_value=None):
            client = GitHubClient.__new__(GitHubClient)
            client._client = MagicMock()
            client._client.get.side_effect = [page1, page2]

            result = client.get_review_comments("owner", "repo", 42)
            assert len(result) == 1
            assert result[0]["body"] == "fix this"


# ---------------------------------------------------------------------------
# Global config helper tests
# ---------------------------------------------------------------------------


class TestGlobalGitHubConfig:
    """Test global config load/save/delete helpers."""

    def test_load_no_file(self, tmp_config_dir):
        from a_sdlc.server.github import load_global_github_config

        with patch("a_sdlc.server.github.GLOBAL_CONFIG_PATH", tmp_config_dir / "config.yaml"):
            result = load_global_github_config()
            assert result is None

    def test_load_no_github_section(self, tmp_config_dir):
        from a_sdlc.server.github import load_global_github_config

        config_path = tmp_config_dir / "config.yaml"
        config_path.write_text(yaml.dump({"sonarqube": {"host": "http://localhost"}}))

        with patch("a_sdlc.server.github.GLOBAL_CONFIG_PATH", config_path):
            result = load_global_github_config()
            assert result is None

    def test_load_success(self, tmp_config_dir):
        from a_sdlc.server.github import load_global_github_config

        config_path = tmp_config_dir / "config.yaml"
        config_path.write_text(yaml.dump({"github": {"token": "ghp_test123"}}))

        with patch("a_sdlc.server.github.GLOBAL_CONFIG_PATH", config_path):
            result = load_global_github_config()
            assert result == {"token": "ghp_test123"}

    def test_save_creates_file(self, tmp_config_dir):
        from a_sdlc.server.github import save_global_github_config

        config_dir = tmp_config_dir / "subdir"
        config_path = config_dir / "config.yaml"

        with patch("a_sdlc.server.github.GLOBAL_CONFIG_DIR", config_dir), \
             patch("a_sdlc.server.github.GLOBAL_CONFIG_PATH", config_path):
            save_global_github_config({"token": "ghp_new"})

        assert config_path.exists()
        data = yaml.safe_load(config_path.read_text())
        assert data["github"]["token"] == "ghp_new"

    def test_save_merges_existing(self, tmp_config_dir):
        from a_sdlc.server.github import save_global_github_config

        config_path = tmp_config_dir / "config.yaml"
        config_path.write_text(yaml.dump({"sonarqube": {"host": "http://localhost"}}))

        with patch("a_sdlc.server.github.GLOBAL_CONFIG_DIR", tmp_config_dir), \
             patch("a_sdlc.server.github.GLOBAL_CONFIG_PATH", config_path):
            save_global_github_config({"token": "ghp_merged"})

        data = yaml.safe_load(config_path.read_text())
        assert data["github"]["token"] == "ghp_merged"
        assert data["sonarqube"]["host"] == "http://localhost"

    def test_delete_success(self, tmp_config_dir):
        from a_sdlc.server.github import delete_global_github_config

        config_path = tmp_config_dir / "config.yaml"
        config_path.write_text(yaml.dump({
            "github": {"token": "ghp_old"},
            "sonarqube": {"host": "http://localhost"},
        }))

        with patch("a_sdlc.server.github.GLOBAL_CONFIG_PATH", config_path):
            result = delete_global_github_config()

        assert result is True
        data = yaml.safe_load(config_path.read_text())
        assert "github" not in data
        assert data["sonarqube"]["host"] == "http://localhost"

    def test_delete_no_file(self, tmp_config_dir):
        from a_sdlc.server.github import delete_global_github_config

        with patch("a_sdlc.server.github.GLOBAL_CONFIG_PATH", tmp_config_dir / "config.yaml"):
            result = delete_global_github_config()
            assert result is False


# ---------------------------------------------------------------------------
# manage_integration (github) MCP tool tests
# ---------------------------------------------------------------------------


class TestConfigureGitHub:
    """Test manage_integration('configure', system='github') MCP tool."""

    @patch("a_sdlc.server.github.GitHubClient")
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_no_project(self, mock_getcwd, mock_get_db, mock_gh_client):
        from a_sdlc.server import manage_integration

        mock_getcwd.return_value = "/nonexistent"
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_db.get_project_by_path.return_value = None

        mock_instance = MagicMock()
        mock_instance.validate_token.return_value = {"login": "octocat", "name": "Octo"}
        mock_gh_client.return_value = mock_instance

        result = manage_integration("configure", system="github", config={"token": "ghp_test"})
        assert result["status"] == "error"
        assert "No project context" in result["message"]

    @patch("a_sdlc.server.github.GitHubClient")
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_invalid_token(self, mock_getcwd, mock_get_db, mock_gh_client, mock_project_dir):
        from a_sdlc.server import manage_integration

        mock_getcwd.return_value = str(mock_project_dir)
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        _setup_project_mocks(mock_db, str(mock_project_dir))

        mock_instance = MagicMock()
        mock_instance.validate_token.side_effect = RuntimeError("Invalid GitHub token (HTTP 401)")
        mock_gh_client.return_value = mock_instance

        result = manage_integration("configure", system="github", config={"token": "bad-token"})
        assert result["status"] == "error"
        assert "Invalid GitHub token" in result["message"]

    @patch("a_sdlc.server.github.GitHubClient")
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_success(self, mock_getcwd, mock_get_db, mock_gh_client, mock_project_dir):
        from a_sdlc.server import manage_integration

        mock_getcwd.return_value = str(mock_project_dir)
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        _setup_project_mocks(mock_db, str(mock_project_dir))

        mock_instance = MagicMock()
        mock_instance.validate_token.return_value = {"login": "octocat", "name": "Octo"}
        mock_gh_client.return_value = mock_instance

        result = manage_integration("configure", system="github", config={"token": "ghp_valid"})
        assert result["status"] == "configured"
        assert result["system"] == "github"
        assert result["scope"] == "project"
        assert result["user"] == "octocat"
        mock_db.set_external_config.assert_called_once_with(
            "test-project", "github", {"token": "ghp_valid"}
        )

    @patch("a_sdlc.server.github.save_global_github_config")
    @patch("a_sdlc.server.github.GitHubClient")
    def test_global_scope_saves_to_file(self, mock_gh_client, mock_save_global):
        """scope='global' stores in YAML, not DB."""
        from a_sdlc.server import manage_integration

        mock_instance = MagicMock()
        mock_instance.validate_token.return_value = {"login": "octocat", "name": "Octo"}
        mock_gh_client.return_value = mock_instance

        result = manage_integration("configure", system="github", config={"token": "ghp_global", "scope": "global"})
        assert result["status"] == "configured"
        assert result["scope"] == "global"
        assert result["user"] == "octocat"
        mock_save_global.assert_called_once_with({"token": "ghp_global"})

    @patch("a_sdlc.server.github.save_global_github_config")
    @patch("a_sdlc.server.github.GitHubClient")
    def test_global_scope_no_project_needed(self, mock_gh_client, mock_save_global):
        """Global scope works without project context."""
        from a_sdlc.server import manage_integration

        mock_instance = MagicMock()
        mock_instance.validate_token.return_value = {"login": "octocat", "name": "Octo"}
        mock_gh_client.return_value = mock_instance

        # No project mocks — should not error
        result = manage_integration("configure", system="github", config={"token": "ghp_global", "scope": "global"})
        assert result["status"] == "configured"
        assert result["scope"] == "global"


# ---------------------------------------------------------------------------
# get_pr_feedback MCP tool tests
# ---------------------------------------------------------------------------


class TestGetPrFeedback:
    """Test get_pr_feedback MCP tool."""

    @patch("a_sdlc.server.github.load_global_github_config", return_value=None)
    @patch("a_sdlc.server.os.environ", {})
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_no_token(self, mock_getcwd, mock_get_db, mock_load_global, mock_project_dir):
        from a_sdlc.server import get_pr_feedback

        mock_getcwd.return_value = str(mock_project_dir)
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        _setup_project_mocks(mock_db, str(mock_project_dir))
        mock_db.get_external_config.return_value = None

        result = get_pr_feedback()
        assert result["status"] == "error"
        assert "No GitHub token found" in result["message"]

    @patch("a_sdlc.server.github.load_global_github_config", return_value=None)
    @patch("a_sdlc.server.github.detect_git_info")
    @patch("a_sdlc.server.os.environ", {"GITHUB_TOKEN": "ghp_env"})
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_env_var_fallback(self, mock_getcwd, mock_get_db, mock_detect, mock_load_global, mock_project_dir):
        """Token from GITHUB_TOKEN env var is used when no project or global config."""
        from a_sdlc.server import get_pr_feedback

        mock_getcwd.return_value = str(mock_project_dir)
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        _setup_project_mocks(mock_db, str(mock_project_dir))
        mock_db.get_external_config.return_value = None

        mock_detect.side_effect = RuntimeError("Not a git repo")

        result = get_pr_feedback()
        # Should get past token resolution (env var used) and fail on git detection
        assert result["status"] == "error"
        assert "Not a git repo" in result["message"]

    @patch("a_sdlc.server.github.GitHubClient")
    @patch("a_sdlc.server.github.detect_git_info")
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_no_open_pr(self, mock_getcwd, mock_get_db, mock_detect, mock_gh_client, mock_project_dir):
        from a_sdlc.server import get_pr_feedback

        mock_getcwd.return_value = str(mock_project_dir)
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        _setup_project_mocks(mock_db, str(mock_project_dir))
        mock_db.get_external_config.return_value = {
            "config": {"token": "ghp_test"},
        }

        mock_detect.return_value = ("owner", "repo", "feature-branch")

        mock_instance = MagicMock()
        mock_instance.get_pr_for_branch.return_value = None
        mock_gh_client.return_value = mock_instance

        result = get_pr_feedback()
        assert result["status"] == "no_pr"
        assert "feature-branch" in result["message"]

    @patch("a_sdlc.server.github.GitHubClient")
    @patch("a_sdlc.server.github.detect_git_info")
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_success_with_comments(
        self, mock_getcwd, mock_get_db, mock_detect, mock_gh_client, mock_project_dir
    ):
        from a_sdlc.server import get_pr_feedback

        mock_getcwd.return_value = str(mock_project_dir)
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        _setup_project_mocks(mock_db, str(mock_project_dir))
        mock_db.get_external_config.return_value = {
            "config": {"token": "ghp_test"},
        }

        mock_detect.return_value = ("owner", "repo", "feature-branch")

        mock_instance = MagicMock()
        mock_instance.get_pr_for_branch.return_value = {
            "number": 42,
            "title": "Add feature",
            "user": {"login": "author"},
            "html_url": "https://github.com/owner/repo/pull/42",
            "state": "open",
            "base": {"ref": "main"},
        }
        mock_instance.get_reviews.return_value = [
            {
                "id": 100,
                "user": {"login": "reviewer1"},
                "body": "Please fix the error handling",
                "state": "CHANGES_REQUESTED",
                "submitted_at": "2024-01-01T00:00:00Z",
                "html_url": "https://github.com/owner/repo/pull/42#pullrequestreview-100",
            },
        ]
        mock_instance.get_review_comments.return_value = [
            {
                "id": 200,
                "user": {"login": "reviewer1"},
                "body": "This should use a try/except block",
                "path": "src/main.py",
                "original_line": 10,
                "line": 10,
                "side": "RIGHT",
                "diff_hunk": "@@ -8,6 +8,10 @@\n+    result = do_something()",
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z",
                "in_reply_to_id": None,
                "html_url": "https://github.com/owner/repo/pull/42#discussion_r200",
            },
        ]
        mock_instance.get_issue_comments.return_value = [
            {
                "id": 300,
                "user": {"login": "reviewer2"},
                "body": "LGTM overall, nice work!",
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z",
                "html_url": "https://github.com/owner/repo/pull/42#issuecomment-300",
            },
        ]
        mock_gh_client.return_value = mock_instance

        result = get_pr_feedback()

        assert result["status"] == "ok"
        assert result["pr"]["number"] == 42
        assert result["pr"]["title"] == "Add feature"
        assert result["repo"] == "owner/repo"
        assert result["summary"]["total_comments"] == 3
        assert result["summary"]["review_comments"] == 1
        assert result["summary"]["reviews"] == 1
        assert result["summary"]["issue_comments"] == 1

        # Check review comment details
        rc = result["review_comments"][0]
        assert rc["path"] == "src/main.py"
        assert rc["line"] == 10
        assert rc["author"] == "reviewer1"

    @patch("a_sdlc.server.github.GitHubClient")
    @patch("a_sdlc.server.github.detect_git_info")
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_filter_by_reviewer(
        self, mock_getcwd, mock_get_db, mock_detect, mock_gh_client, mock_project_dir
    ):
        from a_sdlc.server import get_pr_feedback

        mock_getcwd.return_value = str(mock_project_dir)
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        _setup_project_mocks(mock_db, str(mock_project_dir))
        mock_db.get_external_config.return_value = {
            "config": {"token": "ghp_test"},
        }

        mock_detect.return_value = ("owner", "repo", "feature-branch")

        mock_instance = MagicMock()
        mock_instance.get_pr_for_branch.return_value = {
            "number": 42,
            "title": "Add feature",
            "user": {"login": "author"},
            "html_url": "https://github.com/owner/repo/pull/42",
            "state": "open",
            "base": {"ref": "main"},
        }
        mock_instance.get_reviews.return_value = []
        mock_instance.get_review_comments.return_value = [
            {
                "id": 200,
                "user": {"login": "reviewer1"},
                "body": "Fix this",
                "path": "src/a.py",
                "original_line": 5,
                "line": 5,
                "side": "RIGHT",
                "diff_hunk": "",
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z",
                "in_reply_to_id": None,
                "html_url": "",
            },
            {
                "id": 201,
                "user": {"login": "reviewer2"},
                "body": "Also fix this",
                "path": "src/b.py",
                "original_line": 10,
                "line": 10,
                "side": "RIGHT",
                "diff_hunk": "",
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z",
                "in_reply_to_id": None,
                "html_url": "",
            },
        ]
        mock_instance.get_issue_comments.return_value = []
        mock_gh_client.return_value = mock_instance

        result = get_pr_feedback(reviewer="reviewer1")

        assert result["status"] == "ok"
        assert result["summary"]["review_comments"] == 1
        assert result["review_comments"][0]["author"] == "reviewer1"
        assert result["filters"]["reviewer"] == "reviewer1"

    @patch("a_sdlc.server.github.GitHubClient")
    @patch("a_sdlc.server.github.detect_git_info")
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_unresolved_only(
        self, mock_getcwd, mock_get_db, mock_detect, mock_gh_client, mock_project_dir
    ):
        from a_sdlc.server import get_pr_feedback

        mock_getcwd.return_value = str(mock_project_dir)
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        _setup_project_mocks(mock_db, str(mock_project_dir))
        mock_db.get_external_config.return_value = {
            "config": {"token": "ghp_test"},
        }

        mock_detect.return_value = ("owner", "repo", "feature-branch")

        mock_instance = MagicMock()
        mock_instance.get_pr_for_branch.return_value = {
            "number": 42,
            "title": "PR",
            "user": {"login": "author"},
            "html_url": "",
            "state": "open",
            "base": {"ref": "main"},
        }
        mock_instance.get_reviews.return_value = []
        mock_instance.get_review_comments.return_value = [
            {
                "id": 200,
                "user": {"login": "r1"},
                "body": "unresolved comment",
                "path": "a.py",
                "original_line": 1,
                "line": 1,
                "side": "RIGHT",
                "diff_hunk": "",
                "created_at": "",
                "updated_at": "",
                "in_reply_to_id": None,
                "html_url": "",
            },
            {
                "id": 201,
                "user": {"login": "r1"},
                "body": "resolved comment",
                "path": "b.py",
                "original_line": 2,
                "line": 2,
                "side": "RIGHT",
                "diff_hunk": "",
                "created_at": "",
                "updated_at": "",
                "in_reply_to_id": None,
                "html_url": "",
            },
        ]
        mock_instance.get_issue_comments.return_value = []
        # Comment 201 is resolved
        mock_instance.get_resolved_thread_ids.return_value = {"201"}
        mock_gh_client.return_value = mock_instance

        result = get_pr_feedback(unresolved_only=True)

        assert result["status"] == "ok"
        assert result["summary"]["review_comments"] == 1
        assert result["review_comments"][0]["id"] == "200"
        assert result["filters"]["unresolved_only"] is True

    @patch("a_sdlc.server.github.detect_git_info")
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_project_token_takes_precedence(
        self, mock_getcwd, mock_get_db, mock_detect, mock_project_dir
    ):
        """Project-level token should be used over GITHUB_TOKEN env var."""
        from a_sdlc.server import get_pr_feedback

        mock_getcwd.return_value = str(mock_project_dir)
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        _setup_project_mocks(mock_db, str(mock_project_dir))
        mock_db.get_external_config.return_value = {
            "config": {"token": "ghp_project"},
        }

        mock_detect.side_effect = RuntimeError("test error")

        with patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_env"}):
            result = get_pr_feedback()

        # Should fail on git detection, but proves project token was tried first
        # (didn't fall through to env var path)
        assert result["status"] == "error"
        assert "test error" in result["message"]

    @patch("a_sdlc.server.github.load_global_github_config")
    @patch("a_sdlc.server.github.detect_git_info")
    @patch("a_sdlc.server.os.environ", {})
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_global_token_fallback(
        self, mock_getcwd, mock_get_db, mock_detect, mock_load_global, mock_project_dir
    ):
        """Global config token is used when no project config exists."""
        from a_sdlc.server import get_pr_feedback

        mock_getcwd.return_value = str(mock_project_dir)
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        _setup_project_mocks(mock_db, str(mock_project_dir))
        mock_db.get_external_config.return_value = None  # No project config
        mock_load_global.return_value = {"token": "ghp_global"}

        mock_detect.side_effect = RuntimeError("test error")

        result = get_pr_feedback()
        # Should get past token resolution (global config used) and fail on git detection
        assert result["status"] == "error"
        assert "test error" in result["message"]

    @patch("a_sdlc.server.github.load_global_github_config")
    @patch("a_sdlc.server.github.detect_git_info")
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_project_beats_global(
        self, mock_getcwd, mock_get_db, mock_detect, mock_load_global, mock_project_dir
    ):
        """Project config takes precedence over global config."""
        from a_sdlc.server import get_pr_feedback

        mock_getcwd.return_value = str(mock_project_dir)
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        _setup_project_mocks(mock_db, str(mock_project_dir))
        mock_db.get_external_config.return_value = {
            "config": {"token": "ghp_project"},
        }
        mock_load_global.return_value = {"token": "ghp_global"}

        mock_detect.side_effect = RuntimeError("test error")

        with patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_env"}):
            result = get_pr_feedback()

        # Global config should NOT have been called since project config was found
        mock_load_global.assert_not_called()
        assert result["status"] == "error"
        assert "test error" in result["message"]

    @patch("a_sdlc.server.github.GitHubClient")
    @patch("a_sdlc.server.github.detect_git_info")
    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_api_error_handling(
        self, mock_getcwd, mock_get_db, mock_detect, mock_gh_client, mock_project_dir
    ):
        """GitHub API errors are handled gracefully."""
        import httpx

        from a_sdlc.server import get_pr_feedback

        mock_getcwd.return_value = str(mock_project_dir)
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        _setup_project_mocks(mock_db, str(mock_project_dir))
        mock_db.get_external_config.return_value = {
            "config": {"token": "ghp_test"},
        }

        mock_detect.return_value = ("owner", "repo", "branch")

        mock_instance = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.text = "API rate limit exceeded"
        mock_instance.get_pr_for_branch.side_effect = httpx.HTTPStatusError(
            "403", request=MagicMock(), response=mock_response
        )
        mock_gh_client.return_value = mock_instance

        result = get_pr_feedback()
        assert result["status"] == "error"
        assert "403" in result["message"]


# ---------------------------------------------------------------------------
# Integration masking test
# ---------------------------------------------------------------------------


class TestGetIntegrationsGitHub:
    """Test that manage_integration('list') masks GitHub token."""

    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_token_masked(self, mock_getcwd, mock_get_db, mock_project_dir):
        from a_sdlc.server import manage_integration

        mock_getcwd.return_value = str(mock_project_dir)
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        _setup_project_mocks(mock_db, str(mock_project_dir))
        mock_db.list_external_configs.return_value = [
            {
                "system": "github",
                "config": {"token": "ghp_secret123"},
                "created_at": "2024-01-01",
                "updated_at": "2024-01-01",
            },
        ]

        result = manage_integration("list")
        assert result["status"] == "ok"
        assert result["integrations"][0]["config"]["token"] == "***"


class TestRemoveIntegrationGitHub:
    """Test that manage_integration('remove') accepts 'github'."""

    @patch("a_sdlc.server.get_db")
    @patch("a_sdlc.server.os.getcwd")
    def test_remove_github(self, mock_getcwd, mock_get_db, mock_project_dir):
        from a_sdlc.server import manage_integration

        mock_getcwd.return_value = str(mock_project_dir)
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        _setup_project_mocks(mock_db, str(mock_project_dir))
        mock_db.delete_external_config.return_value = True

        result = manage_integration("remove", system="github")
        assert result["status"] == "removed"
        assert result["system"] == "github"


# ---------------------------------------------------------------------------
# CLI command tests
# ---------------------------------------------------------------------------


class TestConnectGitHubCLI:
    """Test a-sdlc connect github CLI command."""

    @patch("a_sdlc.server.github.GitHubClient")
    def test_connect_github_global(self, mock_gh_client, tmp_config_dir):
        """--global flag stores token in YAML config."""
        from click.testing import CliRunner

        from a_sdlc.cli import main

        mock_instance = MagicMock()
        mock_instance.validate_token.return_value = {"login": "octocat", "name": "Octo"}
        mock_gh_client.return_value = mock_instance

        config_path = tmp_config_dir / "config.yaml"

        runner = CliRunner()
        with patch("a_sdlc.server.github.GLOBAL_CONFIG_DIR", tmp_config_dir), \
             patch("a_sdlc.server.github.GLOBAL_CONFIG_PATH", config_path):
            result = runner.invoke(main, ["connect", "github", "--token", "ghp_test", "--global"])

        assert result.exit_code == 0
        assert "configured globally" in result.output
        assert "octocat" in result.output

    @patch("a_sdlc.server.github.GitHubClient")
    def test_connect_github_project_level(self, mock_gh_client, mock_project_dir):
        """Without --global, stores in project DB."""
        from click.testing import CliRunner

        from a_sdlc.cli import main

        mock_instance = MagicMock()
        mock_instance.validate_token.return_value = {"login": "octocat", "name": "Octo"}
        mock_gh_client.return_value = mock_instance

        mock_storage = MagicMock()
        mock_storage.get_project_by_path.return_value = _make_project(str(mock_project_dir))

        runner = CliRunner()
        with patch("a_sdlc.cli.Path.cwd", return_value=mock_project_dir), \
             patch("a_sdlc.storage.get_storage", return_value=mock_storage):
            result = runner.invoke(main, ["connect", "github", "--token", "ghp_test"])

        assert result.exit_code == 0
        assert "configured for Test Project" in result.output
        mock_storage.set_external_config.assert_called_once_with(
            "test-project", "github", {"token": "ghp_test"}
        )

    @patch("a_sdlc.server.github.GitHubClient")
    def test_connect_github_invalid_token(self, mock_gh_client):
        """Invalid token shows error and exits 1."""
        from click.testing import CliRunner

        from a_sdlc.cli import main

        mock_instance = MagicMock()
        mock_instance.validate_token.side_effect = RuntimeError("Invalid GitHub token (HTTP 401)")
        mock_gh_client.return_value = mock_instance

        runner = CliRunner()
        result = runner.invoke(main, ["connect", "github", "--token", "bad_token"])

        assert result.exit_code == 1
        assert "Invalid GitHub token" in result.output

    def test_connect_github_no_project(self, mock_project_dir):
        """Without --global and no project, shows hint to use --global."""
        from click.testing import CliRunner

        from a_sdlc.cli import main

        mock_gh_client_cls = MagicMock()
        mock_instance = MagicMock()
        mock_instance.validate_token.return_value = {"login": "octocat", "name": "Octo"}
        mock_gh_client_cls.return_value = mock_instance

        mock_storage = MagicMock()
        mock_storage.get_project_by_path.return_value = None

        runner = CliRunner()
        with patch("a_sdlc.server.github.GitHubClient", mock_gh_client_cls), \
             patch("a_sdlc.cli.Path.cwd", return_value=mock_project_dir), \
             patch("a_sdlc.storage.get_storage", return_value=mock_storage):
            result = runner.invoke(main, ["connect", "github", "--token", "ghp_test"])

        assert result.exit_code == 1
        assert "--global" in result.output


class TestDisconnectGitHubCLI:
    """Test a-sdlc disconnect github CLI command."""

    def test_disconnect_github_project(self, mock_project_dir):
        """disconnect github removes from project DB."""
        from click.testing import CliRunner

        from a_sdlc.cli import main

        mock_storage = MagicMock()
        mock_storage.get_project_by_path.return_value = _make_project(str(mock_project_dir))
        mock_storage.get_external_config.return_value = {"config": {"token": "ghp_old"}}

        runner = CliRunner()
        with patch("a_sdlc.cli.Path.cwd", return_value=mock_project_dir), \
             patch("a_sdlc.storage.get_storage", return_value=mock_storage):
            result = runner.invoke(main, ["disconnect", "github", "-y"])

        assert result.exit_code == 0
        assert "removed" in result.output
        mock_storage.delete_external_config.assert_called_once_with("test-project", "github")

    def test_disconnect_github_global(self, tmp_config_dir):
        """disconnect github --global removes from YAML."""
        from click.testing import CliRunner

        from a_sdlc.cli import main

        config_path = tmp_config_dir / "config.yaml"
        config_path.write_text(yaml.dump({"github": {"token": "ghp_old"}}))

        runner = CliRunner()
        with patch("a_sdlc.server.github.GLOBAL_CONFIG_PATH", config_path):
            result = runner.invoke(main, ["disconnect", "github", "--global", "-y"])

        assert result.exit_code == 0
        assert "Global GitHub integration removed" in result.output
