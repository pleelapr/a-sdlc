"""
GitHub API client for a-sdlc.

Provides REST and GraphQL access to GitHub for PR review comment retrieval.
"""

import re
import subprocess
from pathlib import Path
from typing import Any

import httpx
import yaml

# Global config paths (shared with sonarqube_setup.py)
GLOBAL_CONFIG_DIR = Path.home() / ".config" / "a-sdlc"
GLOBAL_CONFIG_PATH = GLOBAL_CONFIG_DIR / "config.yaml"


def load_global_github_config() -> dict | None:
    """Load GitHub config from global config file.

    Returns:
        Dict with token key, or None if not configured.
    """
    if not GLOBAL_CONFIG_PATH.exists():
        return None
    try:
        raw = yaml.safe_load(GLOBAL_CONFIG_PATH.read_text()) or {}
        github_cfg = raw.get("github")
        if isinstance(github_cfg, dict) and github_cfg.get("token"):
            return github_cfg
        return None
    except Exception:
        return None


def save_global_github_config(config: dict) -> None:
    """Save GitHub config to global config file.

    Merges github key into existing YAML, creates dir/file if needed.

    Args:
        config: Dict with token key.
    """
    GLOBAL_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    existing: dict = {}
    if GLOBAL_CONFIG_PATH.exists():
        try:
            existing = yaml.safe_load(GLOBAL_CONFIG_PATH.read_text()) or {}
        except Exception:
            existing = {}

    existing["github"] = config
    GLOBAL_CONFIG_PATH.write_text(yaml.dump(existing, default_flow_style=False))


def delete_global_github_config() -> bool:
    """Remove GitHub config from global config file.

    Returns:
        True if github key was removed, False if not found.
    """
    if not GLOBAL_CONFIG_PATH.exists():
        return False
    try:
        raw = yaml.safe_load(GLOBAL_CONFIG_PATH.read_text()) or {}
    except Exception:
        return False

    if "github" not in raw:
        return False

    del raw["github"]
    GLOBAL_CONFIG_PATH.write_text(yaml.dump(raw, default_flow_style=False))
    return True


class GitHubClient:
    """Client for GitHub REST and GraphQL APIs."""

    BASE_URL = "https://api.github.com"
    GRAPHQL_URL = "https://api.github.com/graphql"

    def __init__(self, token: str):
        """Initialize GitHub client.

        Args:
            token: GitHub personal access token or fine-grained token.
        """
        self.token = token
        self._client = httpx.Client(
            base_url=self.BASE_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30.0,
        )

    def validate_token(self) -> dict[str, Any]:
        """Validate the token by fetching the authenticated user.

        Returns:
            User info dict with 'login' and 'name'.

        Raises:
            RuntimeError: If token is invalid.
        """
        response = self._client.get("/user")
        if response.status_code != 200:
            raise RuntimeError(
                f"Invalid GitHub token (HTTP {response.status_code}). "
                "Ensure the token has 'repo' scope."
            )
        data = response.json()
        return {"login": data["login"], "name": data.get("name", "")}

    def get_pr_for_branch(
        self, owner: str, repo: str, branch: str
    ) -> dict[str, Any] | None:
        """Find an open PR for the given branch.

        Args:
            owner: Repository owner.
            repo: Repository name.
            branch: Branch name (head ref).

        Returns:
            PR dict if found, None otherwise.
        """
        response = self._client.get(
            f"/repos/{owner}/{repo}/pulls",
            params={"head": f"{owner}:{branch}", "state": "open"},
        )
        response.raise_for_status()
        prs = response.json()
        if not prs:
            return None
        return prs[0]

    def get_reviews(
        self, owner: str, repo: str, pr_number: int
    ) -> list[dict[str, Any]]:
        """Get review summaries for a PR.

        Args:
            owner: Repository owner.
            repo: Repository name.
            pr_number: Pull request number.

        Returns:
            List of review dicts.
        """
        response = self._client.get(
            f"/repos/{owner}/{repo}/pulls/{pr_number}/reviews",
        )
        response.raise_for_status()
        return response.json()

    def get_review_comments(
        self, owner: str, repo: str, pr_number: int
    ) -> list[dict[str, Any]]:
        """Get line-level review comments for a PR.

        Args:
            owner: Repository owner.
            repo: Repository name.
            pr_number: Pull request number.

        Returns:
            List of review comment dicts.
        """
        comments = []
        page = 1
        while True:
            response = self._client.get(
                f"/repos/{owner}/{repo}/pulls/{pr_number}/comments",
                params={"per_page": 100, "page": page},
            )
            response.raise_for_status()
            batch = response.json()
            if not batch:
                break
            comments.extend(batch)
            page += 1
        return comments

    def get_issue_comments(
        self, owner: str, repo: str, pr_number: int
    ) -> list[dict[str, Any]]:
        """Get general conversation comments on a PR.

        Args:
            owner: Repository owner.
            repo: Repository name.
            pr_number: Pull request number.

        Returns:
            List of issue comment dicts.
        """
        comments = []
        page = 1
        while True:
            response = self._client.get(
                f"/repos/{owner}/{repo}/issues/{pr_number}/comments",
                params={"per_page": 100, "page": page},
            )
            response.raise_for_status()
            batch = response.json()
            if not batch:
                break
            comments.extend(batch)
            page += 1
        return comments

    def get_resolved_thread_ids(
        self, owner: str, repo: str, pr_number: int
    ) -> set[str]:
        """Get IDs of resolved review threads via GraphQL.

        Args:
            owner: Repository owner.
            repo: Repository name.
            pr_number: Pull request number.

        Returns:
            Set of resolved comment database IDs (as strings).
        """
        query = """
        query($owner: String!, $repo: String!, $number: Int!) {
          repository(owner: $owner, name: $repo) {
            pullRequest(number: $number) {
              reviewThreads(first: 100) {
                nodes {
                  isResolved
                  comments(first: 1) {
                    nodes {
                      databaseId
                    }
                  }
                }
              }
            }
          }
        }
        """
        response = httpx.post(
            self.GRAPHQL_URL,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
            json={
                "query": query,
                "variables": {
                    "owner": owner,
                    "repo": repo,
                    "number": pr_number,
                },
            },
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()

        if "errors" in data:
            raise RuntimeError(f"GitHub GraphQL error: {data['errors']}")

        resolved_ids: set[str] = set()
        threads = (
            data.get("data", {})
            .get("repository", {})
            .get("pullRequest", {})
            .get("reviewThreads", {})
            .get("nodes", [])
        )
        for thread in threads:
            if thread.get("isResolved"):
                comments = thread.get("comments", {}).get("nodes", [])
                if comments:
                    db_id = comments[0].get("databaseId")
                    if db_id is not None:
                        resolved_ids.add(str(db_id))
        return resolved_ids


def parse_git_remote(url: str) -> tuple[str, str]:
    """Parse GitHub owner and repo from a git remote URL.

    Supports HTTPS, SSH, and git:// formats:
      - https://github.com/owner/repo.git
      - git@github.com:owner/repo.git
      - ssh://git@github.com/owner/repo.git

    Args:
        url: Git remote URL string.

    Returns:
        Tuple of (owner, repo).

    Raises:
        ValueError: If URL cannot be parsed as a GitHub remote.
    """
    # HTTPS: https://github.com/owner/repo.git
    # SSH: git@github.com:owner/repo.git
    # SSH with protocol: ssh://git@github.com/owner/repo.git
    match = re.match(
        r"(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)"
        r"([^/]+)/([^/.]+?)(?:\.git)?$",
        url,
    )
    if not match:
        raise ValueError(f"Cannot parse GitHub remote URL: {url}")
    return match.group(1), match.group(2)


def detect_git_info() -> tuple[str, str, str]:
    """Detect owner, repo, and current branch from git.

    Returns:
        Tuple of (owner, repo, branch).

    Raises:
        RuntimeError: If git commands fail or remote is not GitHub.
    """
    try:
        remote_url = (
            subprocess.check_output(
                ["git", "remote", "get-url", "origin"],
                stderr=subprocess.PIPE,
            )
            .decode()
            .strip()
        )
    except subprocess.CalledProcessError:
        raise RuntimeError(
            "Could not get git remote URL. Ensure you're in a git repo with an 'origin' remote."
        )

    try:
        owner, repo = parse_git_remote(remote_url)
    except ValueError as e:
        raise RuntimeError(str(e))

    try:
        branch = (
            subprocess.check_output(
                ["git", "branch", "--show-current"],
                stderr=subprocess.PIPE,
            )
            .decode()
            .strip()
        )
    except subprocess.CalledProcessError:
        raise RuntimeError("Could not determine current git branch.")

    if not branch:
        raise RuntimeError(
            "Detached HEAD state — no current branch. Check out a branch first."
        )

    return owner, repo, branch
