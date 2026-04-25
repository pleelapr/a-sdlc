"""GitHub PR feedback MCP tools."""

from __future__ import annotations

import contextlib
import os
from typing import Any

import httpx

import a_sdlc.server as _server

__all__ = ["get_pr_feedback"]


@_server.mcp.tool()
def get_pr_feedback(
    unresolved_only: bool = False,
    reviewer: str | None = None,
) -> dict[str, Any]:
    """Fetch PR review comments for the current branch.

    Detects the GitHub repo and branch from git, finds the open PR,
    and retrieves all review comments (line-level, review summaries,
    and general conversation).

    Token resolution: project config → global config (~/.config/a-sdlc/) → GITHUB_TOKEN env var.

    Args:
        unresolved_only: If True, only return unresolved review threads.
        reviewer: Filter comments by this GitHub username.

    Returns:
        Structured dict with PR info and categorized comments.
    """
    from a_sdlc.server.github import GitHubClient, detect_git_info, load_global_github_config

    db = _server.get_db()
    project_id = _server._get_current_project_id()

    # Resolve token: project config → global config → env var
    token = None
    if project_id:
        config = db.get_external_config(project_id, "github")
        if config:
            token = config["config"].get("token")

    if not token:
        global_cfg = load_global_github_config()
        if global_cfg:
            token = global_cfg.get("token")

    if not token:
        token = os.environ.get("GITHUB_TOKEN")

    if not token:
        return {
            "status": "error",
            "message": (
                "No GitHub token found. Either:\n"
                "1. Configure per-project: use configure_integration(system='github', config={...}) tool\n"
                "2. Configure globally: a-sdlc connect github --global\n"
                "3. Set GITHUB_TOKEN environment variable"
            ),
        }

    # Detect repo info from git
    try:
        owner, repo, branch = detect_git_info()
    except RuntimeError as e:
        return {"status": "error", "message": str(e)}

    client = GitHubClient(token)

    # Find PR for current branch
    try:
        pr = client.get_pr_for_branch(owner, repo, branch)
    except httpx.HTTPStatusError as e:
        return {
            "status": "error",
            "message": f"GitHub API error: {e.response.status_code} — {e.response.text[:200]}",
        }

    if not pr:
        return {
            "status": "no_pr",
            "message": f"No open PR found for branch '{branch}' in {owner}/{repo}.",
            "branch": branch,
            "repo": f"{owner}/{repo}",
        }

    pr_number = pr["number"]

    # Fetch all comment types
    try:
        reviews = client.get_reviews(owner, repo, pr_number)
        review_comments = client.get_review_comments(owner, repo, pr_number)
        issue_comments = client.get_issue_comments(owner, repo, pr_number)
    except httpx.HTTPStatusError as e:
        return {
            "status": "error",
            "message": f"Failed to fetch comments: {e.response.status_code}",
        }

    # Get resolved thread IDs if filtering
    resolved_ids: set[str] = set()
    if unresolved_only:
        # GraphQL may fail with limited token scopes; continue without filtering
        with contextlib.suppress(Exception):
            resolved_ids = client.get_resolved_thread_ids(owner, repo, pr_number)

    # Process review comments (line-level)
    processed_review_comments = []
    for c in review_comments:
        comment_id = str(c["id"])

        # Filter resolved
        if unresolved_only and comment_id in resolved_ids:
            continue

        # Filter by reviewer
        if reviewer and c.get("user", {}).get("login") != reviewer:
            continue

        processed_review_comments.append({
            "id": comment_id,
            "type": "review_comment",
            "author": c.get("user", {}).get("login", "unknown"),
            "body": c.get("body", ""),
            "path": c.get("path", ""),
            "line": c.get("original_line") or c.get("line"),
            "side": c.get("side", "RIGHT"),
            "diff_hunk": c.get("diff_hunk", ""),
            "created_at": c.get("created_at", ""),
            "updated_at": c.get("updated_at", ""),
            "in_reply_to_id": c.get("in_reply_to_id"),
            "html_url": c.get("html_url", ""),
        })

    # Process review summaries
    processed_reviews = []
    for r in reviews:
        if reviewer and r.get("user", {}).get("login") != reviewer:
            continue

        # Skip empty review summaries (just approvals with no body)
        body = r.get("body", "").strip()
        state = r.get("state", "")

        processed_reviews.append({
            "id": str(r["id"]),
            "type": "review",
            "author": r.get("user", {}).get("login", "unknown"),
            "body": body,
            "state": state,
            "created_at": r.get("submitted_at", ""),
            "html_url": r.get("html_url", ""),
        })

    # Process general conversation comments
    processed_issue_comments = []
    for c in issue_comments:
        if reviewer and c.get("user", {}).get("login") != reviewer:
            continue

        processed_issue_comments.append({
            "id": str(c["id"]),
            "type": "issue_comment",
            "author": c.get("user", {}).get("login", "unknown"),
            "body": c.get("body", ""),
            "created_at": c.get("created_at", ""),
            "updated_at": c.get("updated_at", ""),
            "html_url": c.get("html_url", ""),
        })

    total = (
        len(processed_review_comments)
        + len(processed_reviews)
        + len(processed_issue_comments)
    )

    return {
        "status": "ok",
        "pr": {
            "number": pr_number,
            "title": pr.get("title", ""),
            "author": pr.get("user", {}).get("login", "unknown"),
            "html_url": pr.get("html_url", ""),
            "state": pr.get("state", ""),
            "branch": branch,
            "base": pr.get("base", {}).get("ref", ""),
        },
        "repo": f"{owner}/{repo}",
        "filters": {
            "unresolved_only": unresolved_only,
            "reviewer": reviewer,
        },
        "summary": {
            "total_comments": total,
            "review_comments": len(processed_review_comments),
            "reviews": len(processed_reviews),
            "issue_comments": len(processed_issue_comments),
        },
        "reviews": processed_reviews,
        "review_comments": processed_review_comments,
        "issue_comments": processed_issue_comments,
    }
