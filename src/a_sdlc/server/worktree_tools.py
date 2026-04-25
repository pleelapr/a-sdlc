"""Worktree MCP tools."""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import a_sdlc.server as _server

__all__ = [
    "_ensure_gitignore_entry",
    "cleanup_prd_worktree",
    "complete_prd_worktree",
    "manage_git_safety",
    "create_prd_pr",
    "list_worktrees",
    "setup_prd_worktree",
]


@_server.mcp.tool()
def manage_git_safety(
    action: str,
    auto_commit: bool | None = None,
    auto_pr: bool | None = None,
    auto_merge: bool | None = None,
    worktree_enabled: bool | None = None,
    scope: str = "project",
) -> dict[str, Any]:
    """Manage git safety configuration: configure settings or get current config.

    Actions:
    - configure: Set git safety settings. Provide one or more of auto_commit,
      auto_pr, auto_merge, worktree_enabled.
    - get: Get the current effective configuration with sources.

    Args:
        action: One of "configure", "get".
        auto_commit: Allow agent to commit changes automatically (configure only).
        auto_pr: Allow agent to create pull requests (configure only).
        auto_merge: Allow agent to merge branches (configure only).
        worktree_enabled: Use git worktree isolation (configure only).
        scope: Where to save — "global" or "project" (configure only, default: project).
    """
    valid_actions = ("configure", "get")
    if action not in valid_actions:
        return {
            "status": "error",
            "message": f"Invalid action '{action}'. Must be one of: {', '.join(valid_actions)}",
        }

    if action == "get":
        summary = _server.get_effective_config_summary()
        return {
            "status": "ok",
            "config": summary,
        }

    # action == "configure"
    if scope not in ("global", "project"):
        return {
            "status": "error",
            "message": f"Invalid scope: {scope}. Use 'global' or 'project'.",
        }

    # Build settings dict from provided arguments only
    settings: dict[str, bool] = {}
    if auto_commit is not None:
        settings["auto_commit"] = auto_commit
    if auto_pr is not None:
        settings["auto_pr"] = auto_pr
    if auto_merge is not None:
        settings["auto_merge"] = auto_merge
    if worktree_enabled is not None:
        settings["worktree_enabled"] = worktree_enabled

    if not settings:
        # No settings provided — return current config
        summary = _server.get_effective_config_summary()
        return {
            "status": "ok",
            "message": "Current git safety configuration (no changes made).",
            "config": summary,
        }

    try:
        config_path = _server.save_git_safety_config(
            settings=settings,
            target=scope,  # type: ignore[arg-type]
        )
    except ValueError as e:
        return {"status": "error", "message": str(e)}

    summary = _server.get_effective_config_summary()
    return {
        "status": "configured",
        "message": f"Git safety settings saved to {scope} config ({config_path}).",
        "config": summary,
    }


# =============================================================================
# PRD Worktree Isolation Tools
# =============================================================================


def _ensure_gitignore_entry(repo_root: Path, entry: str) -> None:
    """Ensure an entry exists in .gitignore."""
    gitignore = repo_root / ".gitignore"
    if gitignore.exists():
        content = gitignore.read_text(encoding="utf-8")
        if entry not in content.splitlines():
            with open(gitignore, "a", encoding="utf-8") as f:
                if not content.endswith("\n"):
                    f.write("\n")
                f.write(f"{entry}\n")
    else:
        gitignore.write_text(f"{entry}\n", encoding="utf-8")


@_server.mcp.tool()
def setup_prd_worktree(
    prd_id: str,
    sprint_id: str,
    base_branch: str | None = None,
    port_offset: int = 0,
) -> dict[str, Any]:
    """Set up an isolated git worktree for a PRD's tasks.

    Creates a git worktree with its own branch for isolated PRD execution.
    Writes environment overrides for Docker namespace isolation.

    Args:
        prd_id: PRD identifier (e.g., PROJ-P0001).
        sprint_id: Sprint identifier for branch naming.
        base_branch: Branch to base worktree on. Defaults to current HEAD.
        port_offset: Port offset for Docker service isolation (0, 100, 200...).

    Returns:
        Worktree details including path, branch name, and environment config.
    """
    repo_root = Path(os.getcwd())

    # Check git safety config — worktree_enabled must be true
    git_config = _server.load_git_safety_config(repo_root)
    if not git_config.is_operation_allowed("worktree_enabled"):
        return {
            "status": "disabled",
            "message": (
                "Worktree isolation is disabled by git safety configuration. "
                "Enable it with: configure_git_safety(worktree_enabled=True)"
            ),
        }

    worktree_dir = repo_root / ".worktrees"
    worktree_path = worktree_dir / prd_id
    branch_name = f"sprint/{sprint_id}/{prd_id}"

    # Get project context and DB
    db = _server.get_db()
    project_id = _server._get_current_project_id()
    project = db.get_project(project_id) if project_id else None
    shortname = project["shortname"].lower() if project else "proj"

    # Check if worktree already exists in DB
    existing = db.get_worktree_by_prd(prd_id)
    if existing and Path(existing["path"]).exists():
        return {
            "status": "exists",
            "message": f"Worktree for {prd_id} already exists",
            "worktree": existing,
        }

    # Ensure .worktrees/ is in .gitignore
    _ensure_gitignore_entry(repo_root, ".worktrees/")

    # Create branch from base
    base = base_branch or "HEAD"
    try:
        subprocess.run(
            ["git", "branch", branch_name, base],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        # Branch may already exist (resume scenario)
        if "already exists" not in e.stderr:
            return {
                "status": "error",
                "message": f"Failed to create branch: {e.stderr.strip()}",
            }

    # Create worktree
    try:
        subprocess.run(
            ["git", "worktree", "add", str(worktree_path), branch_name],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        return {
            "status": "error",
            "message": f"Failed to create worktree: {e.stderr.strip()}",
        }

    # Ensure worktree directory exists (git worktree add creates it,
    # but we ensure it for robustness)
    worktree_path.mkdir(parents=True, exist_ok=True)

    # Write .env.prd-override in worktree
    compose_name = f"{shortname}-{prd_id.lower()}"
    env_content = (
        f"COMPOSE_PROJECT_NAME={compose_name}\n"
        f"A_SDLC_PORT_OFFSET={port_offset}\n"
        f"A_SDLC_PRD_ID={prd_id}\n"
    )
    env_path = worktree_path / ".env.prd-override"
    env_path.write_text(env_content)

    # Record worktree in database
    worktree_id = db.get_next_worktree_id(project_id) if project_id else prd_id
    db.create_worktree(
        worktree_id=worktree_id,
        project_id=project_id or "",
        prd_id=prd_id,
        branch_name=branch_name,
        path=str(worktree_path),
        sprint_id=sprint_id,
        status="active",
    )

    return {
        "status": "created",
        "message": f"Worktree created for {prd_id}",
        "worktree": {
            "id": worktree_id,
            "prd_id": prd_id,
            "branch": branch_name,
            "path": str(worktree_path),
            "port_offset": port_offset,
            "compose_name": compose_name,
            "env_file": str(env_path),
        },
    }


@_server.mcp.tool()
def cleanup_prd_worktree(
    prd_id: str,
    remove_branch: bool = False,
    confirm_branch_delete: bool = False,
    docker_cleanup: bool = True,
) -> dict[str, Any]:
    """Clean up a PRD's git worktree and optionally its Docker resources.

    Looks up worktree state from the database. If no DB record exists but
    an orphaned worktree directory is found on disk, cleans it up anyway.

    Branch deletion is a destructive operation and always requires explicit
    confirmation via confirm_branch_delete=True, regardless of git safety
    configuration.

    Args:
        prd_id: PRD identifier.
        remove_branch: If True, also delete the worktree's branch.
        confirm_branch_delete: Must be True to actually delete the branch.
            Required as a safety measure for destructive operations.
        docker_cleanup: If True, run docker compose down for the PRD's namespace.

    Returns:
        Cleanup status.
    """
    repo_root = Path(os.getcwd())
    db = _server.get_db()
    worktree_info = db.get_worktree_by_prd(prd_id)

    # Fallback: detect orphan worktree on disk when DB has no record
    if not worktree_info:
        orphan_path = repo_root / ".worktrees" / prd_id
        if orphan_path.exists():
            return _cleanup_orphan_worktree(repo_root, orphan_path, prd_id)
        return {
            "status": "not_found",
            "message": f"No worktree found for {prd_id}",
        }

    worktree_path = Path(worktree_info["path"])
    branch_name = worktree_info["branch_name"]

    # Branch deletion requires explicit confirmation (destructive operation)
    if remove_branch and not confirm_branch_delete:
        return {
            "status": "confirmation_required",
            "message": (
                f"Branch deletion is a destructive operation that always requires "
                f"explicit confirmation. To delete branch '{branch_name}', "
                f"call again with confirm_branch_delete=True."
            ),
            "branch": branch_name,
        }

    errors = []

    # Docker cleanup (compose_name not stored in DB -- derive from project)
    compose_name = ""
    project_id = worktree_info.get("project_id")
    if project_id:
        project = db.get_project(project_id)
        if project:
            compose_name = f"{project['shortname'].lower()}-{prd_id.lower()}"

    if docker_cleanup and compose_name:
        try:
            subprocess.run(
                ["docker", "compose", "-p", compose_name, "down", "-v"],
                cwd=str(worktree_path) if worktree_path.exists() else str(repo_root),
                capture_output=True,
                text=True,
                timeout=60,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
            errors.append(f"Docker cleanup warning: {e}")

    # Remove worktree directory via git
    if worktree_path.exists():
        try:
            subprocess.run(
                ["git", "worktree", "remove", str(worktree_path), "--force"],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            errors.append(f"Worktree removal warning: {e.stderr.strip()}")

    # Prune stale worktree references
    try:
        subprocess.run(
            ["git", "worktree", "prune"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        errors.append(f"Worktree prune warning: {e.stderr.strip()}")

    # Remove branch if requested AND confirmed
    if remove_branch and confirm_branch_delete:
        try:
            subprocess.run(
                ["git", "branch", "-D", branch_name],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            errors.append(f"Branch deletion warning: {e.stderr.strip()}")

    # Update worktree status in database
    db.update_worktree(worktree_info["id"], status="abandoned")

    result: dict[str, Any] = {
        "status": "cleaned",
        "message": f"Worktree for {prd_id} cleaned up",
        "branch_removed": remove_branch and confirm_branch_delete,
        "docker_cleaned": docker_cleanup,
    }
    if errors:
        result["warnings"] = errors

    return result


def _cleanup_orphan_worktree(
    repo_root: Path,
    orphan_path: Path,
    prd_id: str,
) -> dict[str, Any]:
    """Clean up an orphaned worktree directory that has no database record.

    This handles the edge case where a worktree exists on disk (e.g. from
    a previous run, manual creation, or DB reset) but has no corresponding
    database entry.

    Args:
        repo_root: Repository root path.
        orphan_path: Path to the orphaned worktree directory.
        prd_id: PRD identifier.

    Returns:
        Cleanup result dict.
    """
    errors: list[str] = []

    # Try git worktree remove first
    try:
        subprocess.run(
            ["git", "worktree", "remove", str(orphan_path), "--force"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        errors.append(f"Worktree removal warning: {e.stderr.strip()}")
        # Fall back to manual directory removal if git worktree remove fails
        try:
            shutil.rmtree(str(orphan_path))
        except OSError as rm_err:
            errors.append(f"Manual removal warning: {rm_err}")

    # Prune stale worktree references
    try:
        subprocess.run(
            ["git", "worktree", "prune"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        errors.append(f"Worktree prune warning: {e.stderr.strip()}")

    result: dict[str, Any] = {
        "status": "cleaned",
        "message": f"Orphaned worktree for {prd_id} cleaned up (no DB record found)",
        "orphan": True,
        "branch_removed": False,
        "docker_cleaned": False,
    }
    if errors:
        result["warnings"] = errors

    return result


@_server.mcp.tool()
def create_prd_pr(
    prd_id: str,
    sprint_id: str,
    base_branch: str | None = None,
    title: str | None = None,
    body: str | None = None,
) -> dict[str, Any]:
    """Create a pull request for a PRD's worktree branch.

    Pushes the PRD branch to remote and creates a PR via gh CLI.

    Args:
        prd_id: PRD identifier.
        sprint_id: Sprint identifier (for branch name lookup).
        base_branch: Target branch for the PR. Defaults to repo default branch.
        title: PR title. Auto-generated from PRD metadata if not provided.
        body: PR body. Auto-generated if not provided.

    Returns:
        PR URL and details.
    """
    repo_root = Path(os.getcwd())

    # Check git safety config — auto_pr must be enabled
    git_config = _server.load_git_safety_config(repo_root)
    if not git_config.is_operation_allowed("auto_pr"):
        return {
            "status": "disabled",
            "message": (
                "Automatic PR creation is disabled by git safety configuration. "
                "Enable it with: configure_git_safety(auto_pr=True)"
            ),
        }

    db = _server.get_db()
    worktree_info = db.get_worktree_by_prd(prd_id)

    if not worktree_info:
        return {
            "status": "not_found",
            "message": f"No worktree found for {prd_id}. Run setup_prd_worktree first.",
        }

    branch_name = worktree_info["branch_name"]

    # Get PRD metadata for auto-generated title/body
    prd = db.get_prd(prd_id)
    prd_title = prd["title"] if prd else prd_id

    pr_title = title or f"[{sprint_id}] {prd_title}"
    pr_body = body or (
        f"## Summary\n\n"
        f"Implementation for PRD **{prd_id}**: {prd_title}\n\n"
        f"Sprint: {sprint_id}\n"
        f"Branch: `{branch_name}`\n"
    )

    # Push branch to remote
    try:
        subprocess.run(
            ["git", "push", "-u", "origin", branch_name],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        return {
            "status": "error",
            "message": f"Failed to push branch: {e.stderr.strip()}",
        }

    # Create PR via gh CLI
    gh_cmd = ["gh", "pr", "create", "--title", pr_title, "--body", pr_body, "--head", branch_name]
    if base_branch:
        gh_cmd.extend(["--base", base_branch])

    try:
        result = subprocess.run(
            gh_cmd,
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=True,
        )
        pr_url = result.stdout.strip()
    except subprocess.CalledProcessError as e:
        return {
            "status": "error",
            "message": f"Failed to create PR: {e.stderr.strip()}",
        }

    # Store PR URL in database (keep status as "active" — status changes via complete_prd_worktree)
    db.update_worktree(worktree_info["id"], pr_url=pr_url)

    return {
        "status": "created",
        "message": f"PR created for {prd_id}",
        "pr_url": pr_url,
        "branch": branch_name,
        "title": pr_title,
    }


@_server.mcp.tool()
def list_worktrees(
    project_id: str | None = None,
    status: str | None = None,
    sprint_id: str | None = None,
) -> dict[str, Any]:
    """List tracked worktrees with optional filters.

    Returns all worktrees for the current project with their state,
    associated PRD/sprint, branch name, and path.

    Args:
        project_id: Optional project ID. Auto-detects if not provided.
        status: Filter by worktree status (active, completed, abandoned).
        sprint_id: Filter by sprint ID.

    Returns:
        List of worktree summaries.
    """
    db = _server.get_db()
    pid = project_id or _server._get_current_project_id()

    if not pid:
        return {"status": "error", "message": "No project context. Run /sdlc:init first."}

    worktrees = db.list_worktrees(pid, status=status, sprint_id=sprint_id)
    return {
        "status": "ok",
        "project_id": pid,
        "filters": {
            "status": status,
            "sprint_id": sprint_id,
        },
        "count": len(worktrees),
        "worktrees": [
            {
                "id": w["id"],
                "prd_id": w["prd_id"],
                "sprint_id": w.get("sprint_id"),
                "branch_name": w["branch_name"],
                "path": w["path"],
                "status": w["status"],
                "created_at": w["created_at"],
                "cleaned_at": w.get("cleaned_at"),
            }
            for w in worktrees
        ],
    }


@_server.mcp.tool()
def complete_prd_worktree(
    prd_id: str,
    action: str,
    base_branch: str | None = None,
    pr_title: str | None = None,
    pr_body: str | None = None,
    confirm_discard: bool = False,
) -> dict[str, Any]:
    """Complete a PRD worktree by applying a chosen action.

    After all tasks for a PRD pass review, use this tool to finalize
    the worktree. Four actions are available:

    - **merge**: Merge the worktree branch into the base branch locally.
      Requires auto_merge to be enabled in git safety config.
      Worktree is cleaned up after merge.
    - **pr**: Create a pull request for the worktree branch.
      Requires auto_pr to be enabled in git safety config.
      Worktree is kept (not cleaned up) so the branch stays available.
    - **keep**: Keep the worktree and branch as-is for manual handling.
      No cleanup is performed.
    - **discard**: Remove the worktree and branch entirely.
      Requires confirm_discard=True as a safety measure.
      Worktree is cleaned up and branch is deleted.

    Args:
        prd_id: PRD identifier.
        action: Completion action — one of "merge", "pr", "keep", "discard".
        base_branch: Target branch for merge/PR. Defaults to repo default branch.
        pr_title: Custom PR title (for "pr" action). Auto-generated if not provided.
        pr_body: Custom PR body (for "pr" action). Auto-generated if not provided.
        confirm_discard: Must be True to execute "discard" action. Safety measure.

    Returns:
        Completion result with action taken and any relevant details.
    """
    valid_actions = ("merge", "pr", "keep", "discard")
    if action not in valid_actions:
        return {
            "status": "error",
            "message": (
                f"Invalid action: '{action}'. "
                f"Valid actions: {', '.join(valid_actions)}"
            ),
        }

    repo_root = Path(os.getcwd())
    db = _server.get_db()
    worktree_info = db.get_worktree_by_prd(prd_id)

    if not worktree_info:
        return {
            "status": "not_found",
            "message": f"No active worktree found for {prd_id}.",
        }

    branch_name = worktree_info["branch_name"]
    sprint_id = worktree_info.get("sprint_id", "")

    git_config = _server.load_git_safety_config(repo_root)

    # --- action: keep ---
    if action == "keep":
        return {
            "status": "kept",
            "message": f"Worktree for {prd_id} kept as-is. Branch: {branch_name}",
            "worktree_id": worktree_info["id"],
            "branch": branch_name,
            "path": worktree_info["path"],
        }

    # --- action: discard ---
    if action == "discard":
        if not confirm_discard:
            return {
                "status": "confirmation_required",
                "message": (
                    f"Discard is a destructive operation. It will remove the worktree "
                    f"and delete branch '{branch_name}'. "
                    f"Call again with confirm_discard=True to proceed."
                ),
                "branch": branch_name,
            }
        # Delegate to cleanup_prd_worktree with branch removal
        # Use _server.xxx() so @patch("a_sdlc.server.cleanup_prd_worktree") works in tests
        return _server.cleanup_prd_worktree(
            prd_id=prd_id,
            remove_branch=True,
            confirm_branch_delete=True,
            docker_cleanup=True,
        )

    # --- action: pr ---
    if action == "pr":
        if not git_config.is_operation_allowed("auto_pr"):
            return {
                "status": "disabled",
                "message": (
                    "Automatic PR creation is disabled by git safety configuration. "
                    "Enable it with: configure_git_safety(auto_pr=True)"
                ),
            }
        # Delegate to create_prd_pr
        # Use _server.xxx() so @patch("a_sdlc.server.create_prd_pr") works in tests
        return _server.create_prd_pr(
            prd_id=prd_id,
            sprint_id=sprint_id,
            base_branch=base_branch,
            title=pr_title,
            body=pr_body,
        )

    # --- action: merge ---
    if action == "merge":
        if not git_config.is_operation_allowed("auto_merge"):
            return {
                "status": "disabled",
                "message": (
                    "Automatic merge is disabled by git safety configuration. "
                    "Enable it with: configure_git_safety(auto_merge=True)"
                ),
            }

        # Determine base branch
        target_branch = base_branch
        if not target_branch:
            try:
                result = subprocess.run(
                    ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
                    cwd=str(repo_root),
                    capture_output=True,
                    text=True,
                )
                if result.returncode == 0:
                    # e.g., "refs/remotes/origin/main" -> "main"
                    target_branch = result.stdout.strip().split("/")[-1]
            except Exception:
                pass
            if not target_branch:
                target_branch = "main"

        # Merge the worktree branch into target
        try:
            subprocess.run(
                ["git", "merge", branch_name, "--no-ff",
                 "-m", f"Merge {prd_id} ({branch_name}) into {target_branch}"],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            return {
                "status": "error",
                "message": f"Merge failed: {e.stderr.strip()}",
            }

        # Cleanup worktree after successful merge (no branch removal —
        # branch is merged, can be deleted separately if desired)
        cleanup_result = _server.cleanup_prd_worktree(
            prd_id=prd_id,
            remove_branch=False,
            docker_cleanup=True,
        )

        return {
            "status": "merged",
            "message": f"Branch {branch_name} merged into {target_branch}. Worktree cleaned up.",
            "worktree_id": worktree_info["id"],
            "branch": branch_name,
            "target_branch": target_branch,
            "cleanup": cleanup_result,
        }

    # Should not reach here due to validation above, but satisfy type checker
    return {"status": "error", "message": "Unexpected action."}
