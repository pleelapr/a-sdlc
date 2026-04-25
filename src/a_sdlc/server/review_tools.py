"""Review MCP tools."""
from typing import Any

import a_sdlc.server as _server

__all__ = [
    "submit_review",
    "get_review_evidence",
]


@_server.mcp.tool()
def submit_review(
    task_id: str,
    reviewer_type: str,
    verdict: str,
    findings: str = "",
    test_output: str = "",
) -> dict[str, Any]:
    """Submit a review for a task.

    Args:
        task_id: Task identifier.
        reviewer_type: Who is reviewing — 'self' (developer verifies own work)
            or 'subagent' (independent reviewer).
        verdict: Review verdict. For self reviews: 'pass' or 'fail'.
            For subagent reviews: 'approve', 'request_changes', or 'escalate'.
        findings: Optional JSON array of finding objects.
        test_output: Optional raw test command output (typically for self reviews).

    Returns:
        Review record with round number and verdict.
    """
    valid_reviewer_types = ("self", "subagent")
    if reviewer_type not in valid_reviewer_types:
        return {
            "status": "error",
            "message": f"Invalid reviewer_type: {reviewer_type!r}. Must be one of {valid_reviewer_types}",
        }

    db = _server.get_db()

    task = db.get_task(task_id)
    if not task:
        return {"status": "not_found", "message": f"Task not found: {task_id}"}

    # Validate verdict based on reviewer type
    if reviewer_type == "self":
        valid_verdicts = ("pass", "fail")
    else:
        valid_verdicts = ("approve", "request_changes", "escalate")

    if verdict not in valid_verdicts:
        return {
            "status": "error",
            "message": f"Invalid verdict: {verdict!r}. Must be one of {valid_verdicts}",
        }

    project_id = task["project_id"]

    # Compute round number: count existing reviews of this type for this task + 1
    existing_reviews = db.get_reviews_for_task(task_id)
    typed_reviews = [r for r in existing_reviews if r["reviewer_type"] == reviewer_type]
    round_num = len(typed_reviews) + 1

    create_kwargs: dict[str, Any] = {
        "task_id": task_id,
        "project_id": project_id,
        "round_num": round_num,
        "reviewer_type": reviewer_type,
        "verdict": verdict,
        "findings": findings or None,
    }
    if test_output:
        create_kwargs["test_output"] = test_output

    review = db.create_review(**create_kwargs)

    return {
        "status": "ok",
        "review_id": review["id"],
        "round": round_num,
        "verdict": verdict,
    }


@_server.mcp.tool()
def get_review_evidence(task_id: str) -> dict[str, Any]:
    """Get all review evidence for a task with summary.

    Args:
        task_id: Task identifier.

    Returns:
        All reviews for the task with computed summary.
    """
    db = _server.get_db()

    task = db.get_task(task_id)
    if not task:
        return {"status": "not_found", "message": f"Task not found: {task_id}"}

    reviews = db.get_reviews_for_task(task_id)

    # Compute summary
    self_reviews = [r for r in reviews if r["reviewer_type"] == "self"]
    subagent_reviews = [r for r in reviews if r["reviewer_type"] == "subagent"]

    latest_self_verdict = self_reviews[-1]["verdict"] if self_reviews else None
    latest_subagent_verdict = subagent_reviews[-1]["verdict"] if subagent_reviews else None

    # Determine total rounds as max round across all reviews
    total_rounds = max((r["round"] for r in reviews), default=0)

    has_approved = any(
        r["verdict"] in ("pass", "approve") for r in reviews
    )

    summary = {
        "total_rounds": total_rounds,
        "latest_self_verdict": latest_self_verdict,
        "latest_subagent_verdict": latest_subagent_verdict,
        "has_approved": has_approved,
    }

    return {
        "status": "ok",
        "task_id": task_id,
        "reviews": [dict(r) for r in reviews],
        "summary": summary,
    }
