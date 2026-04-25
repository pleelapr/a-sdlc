"""Challenge MCP tools."""
import json
from pathlib import Path
from typing import Any

import a_sdlc.server as _server
from a_sdlc.server.challenge import CHALLENGE_CHECKLISTS
from a_sdlc.server.challenge import VALID_ARTIFACT_TYPES as _VALID_ARTIFACT_TYPES
from a_sdlc.server.challenge import compute_round_status as _compute_round_status
from a_sdlc.server.challenge import detect_stale_loop as _detect_stale_loop

# _load_challenge_config accessed via _server._server._load_challenge_config() for test patching

__all__ = [
    "CHALLENGE_CHECKLISTS",
    "_detect_stale_loop",
    "challenge_artifact",
    "get_challenge_status",
    "record_challenge_round",
]

_CHALLENGE_DEFAULTS = {"enabled": True, "max_rounds": 5}  # kept for backward compat


@_server.mcp.tool()
def challenge_artifact(
    artifact_type: str,
    artifact_id: str,
    challenge_context: str | None = None,
) -> dict[str, Any]:
    """Generate a structured challenge prompt for an artifact.

    Assembles artifact content, linked requirements, checklist, lesson-learn
    context, and previous round history into a prompt for the challenger agent.
    Does NOT call an LLM -- returns the prompt string for the caller.

    Args:
        artifact_type: One of: prd, design, split, task.
        artifact_id: The artifact identifier (e.g., PROJ-P0001, PROJ-T00001).
        challenge_context: Optional additional context for the challenger.

    Returns:
        Dict with challenge_prompt string, round_number, and checklist.
    """
    if artifact_type not in _VALID_ARTIFACT_TYPES:
        return {
            "status": "error",
            "message": (
                f"Invalid artifact_type '{artifact_type}'. "
                f"Must be one of: {', '.join(sorted(_VALID_ARTIFACT_TYPES))}"
            ),
        }

    try:
        db = _server.get_db()
        content_mgr = _server.get_content_manager()
        storage = _server.get_storage()

        # ---- Load artifact content ----
        artifact_content = ""
        prd_id_for_reqs: str | None = None

        if artifact_type == "prd":
            prd = db.get_prd(artifact_id)
            if not prd:
                return {"status": "not_found", "message": f"PRD not found: {artifact_id}"}
            if prd.get("file_path"):
                artifact_content = content_mgr.read_content(Path(prd["file_path"])) or ""
            prd_id_for_reqs = artifact_id

        elif artifact_type == "design":
            design = storage.get_design_by_prd(artifact_id)
            if not design:
                return {"status": "not_found", "message": f"Design not found for PRD: {artifact_id}"}
            artifact_content = design.get("content", "")
            prd_id_for_reqs = artifact_id

        elif artifact_type == "split":
            project_id = _server._get_current_project_id()
            if not project_id:
                return {"status": "error", "message": "No project context. Run /sdlc:init first."}
            tasks = db.list_tasks(project_id, prd_id=artifact_id)
            task_lines = []
            for t in tasks:
                task_lines.append(
                    f"- {t['id']}: {t['title']} [{t['status']}] (priority={t['priority']})"
                )
            artifact_content = "\n".join(task_lines) if task_lines else "(no tasks found)"
            prd_id_for_reqs = artifact_id

        elif artifact_type == "task":
            task = db.get_task(artifact_id)
            if not task:
                return {"status": "not_found", "message": f"Task not found: {artifact_id}"}
            if task.get("file_path"):
                artifact_content = content_mgr.read_content(Path(task["file_path"])) or ""
            prd_id_for_reqs = task.get("prd_id")

        # ---- Load linked requirements ----
        requirements_text = ""
        if prd_id_for_reqs:
            reqs = storage.get_requirements(prd_id_for_reqs)
            if reqs:
                req_lines = []
                for r in reqs:
                    req_lines.append(
                        f"- {r['req_number']} [{r['depth']}]: {r['summary']}"
                    )
                requirements_text = "\n".join(req_lines)

        # ---- Load checklist ----
        checklist = CHALLENGE_CHECKLISTS[artifact_type]

        # ---- Load lesson-learn files ----
        lessons_text = ""
        lesson_paths: list[Path] = []

        project_id = _server._get_current_project_id()
        if project_id:
            project = db.get_project(project_id)
            if project:
                lesson_paths.append(Path(project["path"]) / ".sdlc" / "lesson-learn.md")

        # Use _server module's Path so @patch("a_sdlc.server.Path") works in tests
        lesson_paths.append(_server.Path.home() / ".a-sdlc" / "lesson-learn.md")

        for lp in lesson_paths:
            if lp.is_file():
                try:
                    file_content = lp.read_text(encoding="utf-8").strip()
                    if file_content:
                        lessons_text += f"\n--- {lp.name} ---\n{file_content}\n"
                except Exception:
                    pass

        # ---- Load previous rounds ----
        previous_rounds = storage.get_challenge_rounds(artifact_type, artifact_id)
        round_number = len(previous_rounds) + 1

        # ---- Build diff-based continuation for round 2+ ----
        unresolved_text = ""
        if round_number > 1 and previous_rounds:
            last_round = previous_rounds[-1]
            last_objections = last_round.get("objections", [])
            if isinstance(last_objections, str):
                try:
                    last_objections = json.loads(last_objections)
                except (json.JSONDecodeError, TypeError):
                    last_objections = []

            last_verdict = last_round.get("verdict")
            if isinstance(last_verdict, str):
                try:
                    last_verdict = json.loads(last_verdict)
                except (json.JSONDecodeError, TypeError):
                    last_verdict = None

            # Filter to unresolved objections only
            resolved_set: set[str] = set()
            accepted_set: set[str] = set()
            if last_verdict and isinstance(last_verdict, dict):
                for item in last_verdict.get("resolved", []):
                    if isinstance(item, str):
                        resolved_set.add(item)
                    elif isinstance(item, dict):
                        resolved_set.add(item.get("description", ""))
                for item in last_verdict.get("accepted", []):
                    if isinstance(item, str):
                        accepted_set.add(item)
                    elif isinstance(item, dict):
                        accepted_set.add(item.get("description", ""))

            handled = resolved_set | accepted_set
            unresolved = []
            for obj in last_objections:
                desc = obj.get("description", "") if isinstance(obj, dict) else str(obj)
                if desc not in handled:
                    unresolved.append(obj)

            if unresolved:
                unresolved_lines = []
                for u in unresolved:
                    if isinstance(u, dict):
                        unresolved_lines.append(f"- {u.get('description', str(u))}")
                    else:
                        unresolved_lines.append(f"- {u}")
                unresolved_text = "\n".join(unresolved_lines)

        # ---- Assemble structured prompt ----
        sections: list[str] = []

        sections.append(f"## ARTIFACT CONTENT ({artifact_type}: {artifact_id})\n")
        sections.append(artifact_content or "(empty)")

        if requirements_text:
            sections.append("\n## REQUIREMENTS\n")
            sections.append(requirements_text)

        sections.append("\n## CHECKLIST\n")
        for i, item in enumerate(checklist, 1):
            sections.append(f"{i}. {item}")

        if lessons_text:
            sections.append("\n## LESSONS LEARNED\n")
            sections.append(lessons_text.strip())

        if unresolved_text:
            sections.append(f"\n## PREVIOUS UNRESOLVED (from round {round_number - 1})")
            sections.append(unresolved_text)

        if challenge_context:
            sections.append("\n## CHALLENGE CONTEXT\n")
            sections.append(challenge_context)

        prompt_string = "\n".join(sections)

        # ---- Store initial round marker ----
        prompt_summary = (
            f"Round {round_number} challenge prompt generated "
            f"for {artifact_type}:{artifact_id}"
        )
        storage.create_challenge_round(
            artifact_type=artifact_type,
            artifact_id=artifact_id,
            round_number=round_number,
            objections="[]",
            challenger_context=prompt_summary,
        )

        return {
            "status": "ok",
            "challenge_prompt": prompt_string,
            "round_number": round_number,
            "checklist": checklist,
        }
    except Exception as exc:
        return {"status": "error", "message": f"Failed to generate challenge prompt: {exc}"}


@_server.mcp.tool()
def record_challenge_round(
    artifact_type: str,
    artifact_id: str,
    round_number: int,
    objections: list[dict[str, Any]],
    responses: list[dict[str, Any]] | None = None,
    verdict: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record objections, responses, and verdict for a challenge round.

    Stores round data and detects stale loops (>80% objection overlap).
    If a stale loop is detected, the round is auto-terminated.

    Args:
        artifact_type: One of: prd, design, split, task.
        artifact_id: The artifact identifier.
        round_number: Round number (1-based, must be > 0).
        objections: List of objection dicts, each with at least a 'description' key.
        responses: Optional list of response dicts from the producer.
        verdict: Optional verdict dict with 'resolved', 'escalated', 'accepted' lists.

    Returns:
        Dict with status, round_number, and stats.
    """
    if artifact_type not in _VALID_ARTIFACT_TYPES:
        return {
            "status": "error",
            "message": (
                f"Invalid artifact_type '{artifact_type}'. "
                f"Must be one of: {', '.join(sorted(_VALID_ARTIFACT_TYPES))}"
            ),
        }

    if not isinstance(round_number, int) or round_number < 1:
        return {
            "status": "error",
            "message": f"round_number must be a positive integer, got: {round_number}",
        }

    try:
        storage = _server.get_storage()

        # ---- Stale loop detection ----
        previous_objections: list[dict[str, Any]] | None = None
        if round_number > 1:
            rounds = storage.get_challenge_rounds(artifact_type, artifact_id)
            for r in rounds:
                if r["round_number"] == round_number - 1:
                    prev_obj = r.get("objections", [])
                    if isinstance(prev_obj, str):
                        try:
                            prev_obj = json.loads(prev_obj)
                        except (json.JSONDecodeError, TypeError):
                            prev_obj = []
                    previous_objections = prev_obj
                    break

        is_stale, overlap_pct = _detect_stale_loop(objections, previous_objections)
        if is_stale:
            # Auto-terminate: update existing round marker
            storage.update_challenge_round(
                artifact_type=artifact_type,
                artifact_id=artifact_id,
                round_number=round_number,
                responses=json.dumps(responses) if responses else None,
                verdict=json.dumps(verdict) if verdict else None,
                status="auto_terminated",
            )
            return {
                "status": "auto_terminated",
                "reason": "stale_loop_detected",
                "overlap_pct": round(overlap_pct, 2),
                "round_number": round_number,
            }

        # ---- Check max_rounds ----
        challenge_config = _server._load_challenge_config()
        max_rounds = challenge_config.get("max_rounds", 5)

        # ---- Store or update round ----
        if responses is not None and verdict is not None:
            # Update existing round with responses and verdict
            computed_status = _compute_round_status(verdict)
            if round_number >= max_rounds:
                computed_status = "escalated"
            storage.update_challenge_round(
                artifact_type=artifact_type,
                artifact_id=artifact_id,
                round_number=round_number,
                responses=json.dumps(responses),
                verdict=json.dumps(verdict),
                status=computed_status,
            )
        else:
            # Initial objections only -- update round created by challenge_artifact
            status_val = "escalated" if round_number >= max_rounds else "open"
            storage.update_challenge_round(
                artifact_type=artifact_type,
                artifact_id=artifact_id,
                round_number=round_number,
                responses=json.dumps(objections),
                status=status_val,
            )

        # ---- Compute unresolved count ----
        unresolved_count = len(objections)
        if verdict:
            resolved_count = len(verdict.get("resolved", []))
            accepted_count = len(verdict.get("accepted", []))
            unresolved_count = max(0, len(objections) - resolved_count - accepted_count)

        result_status = "ok"
        if round_number >= max_rounds and not is_stale:
            result_status = "escalated"

        return {
            "status": result_status,
            "round_number": round_number,
            "unresolved": unresolved_count,
            "total_objections": len(objections),
        }
    except Exception as exc:
        return {"status": "error", "message": f"Failed to record challenge round: {exc}"}


@_server.mcp.tool()
def get_challenge_status(
    artifact_type: str,
    artifact_id: str,
) -> dict[str, Any]:
    """Get the aggregated status of challenge rounds for an artifact.

    Summarizes all rounds into an overall status with statistics on
    resolved, accepted, and escalated objections.

    Args:
        artifact_type: One of: prd, design, split, task.
        artifact_id: The artifact identifier.

    Returns:
        Dict with overall challenge_status, rounds list, and stats.
    """
    if artifact_type not in _VALID_ARTIFACT_TYPES:
        return {
            "status": "error",
            "message": (
                f"Invalid artifact_type '{artifact_type}'. "
                f"Must be one of: {', '.join(sorted(_VALID_ARTIFACT_TYPES))}"
            ),
        }

    try:
        storage = _server.get_storage()
        rounds = storage.get_challenge_rounds(artifact_type, artifact_id)

        if not rounds:
            return {
                "status": "ok",
                "artifact_type": artifact_type,
                "artifact_id": artifact_id,
                "challenge_status": "unchallenged",
                "rounds": [],
                "stats": {
                    "total_rounds": 0,
                    "total_objections": 0,
                    "resolved": 0,
                    "accepted": 0,
                    "escalated": 0,
                },
            }

        # ---- Aggregate stats from verdict dicts ----
        total_objections = 0
        total_resolved = 0
        total_accepted = 0
        total_escalated = 0

        round_summaries: list[dict[str, Any]] = []
        for r in rounds:
            # Count objections
            obj = r.get("objections", [])
            if isinstance(obj, str):
                try:
                    obj = json.loads(obj)
                except (json.JSONDecodeError, TypeError):
                    obj = []
            if isinstance(obj, list):
                total_objections += len(obj)

            # Parse verdict for counts
            verd = r.get("verdict")
            if isinstance(verd, str):
                try:
                    verd = json.loads(verd)
                except (json.JSONDecodeError, TypeError):
                    verd = None

            if isinstance(verd, dict):
                total_resolved += len(verd.get("resolved", []))
                total_accepted += len(verd.get("accepted", []))
                total_escalated += len(verd.get("escalated", []))

            round_summaries.append({
                "round_number": r["round_number"],
                "status": r.get("status", "open"),
                "objection_count": len(obj) if isinstance(obj, list) else 0,
            })

        # ---- Determine overall status ----
        latest_status = rounds[-1].get("status", "open")

        if latest_status == "auto_terminated":
            overall_status = "auto_terminated"
        elif total_escalated > 0 or latest_status == "escalated":
            overall_status = "escalated"
        elif (
            all(r.get("status") in ("resolved", "closed") for r in rounds)
            or latest_status in ("resolved", "closed")
        ):
            overall_status = "resolved"
        else:
            overall_status = "in_progress"

        # ---- Compute effectiveness metrics ----
        first_round_resolved = 0
        auto_terminated_count = 0
        escalated_round_count = 0
        for r in rounds:
            if r["round_number"] == 1 and r.get("status") == "resolved":
                first_round_resolved += 1
            if r.get("status") == "auto_terminated":
                auto_terminated_count += 1
            if r.get("status") == "escalated":
                escalated_round_count += 1

        total = len(rounds)

        return {
            "status": "ok",
            "artifact_type": artifact_type,
            "artifact_id": artifact_id,
            "challenge_status": overall_status,
            "rounds": round_summaries,
            "stats": {
                "total_rounds": total,
                "total_objections": total_objections,
                "resolved": total_resolved,
                "accepted": total_accepted,
                "escalated": total_escalated,
            },
            "effectiveness": {
                "first_round_resolution_rate": round(first_round_resolved / total, 2) if total else 0.0,
                "escalation_rate": round(escalated_round_count / total, 2) if total else 0.0,
                "auto_termination_rate": round(auto_terminated_count / total, 2) if total else 0.0,
                "avg_rounds": total,
                "total_objections": total_objections,
                "resolution_rate": round((total_resolved + total_accepted) / total_objections, 2) if total_objections else 0.0,
            },
        }
    except Exception as exc:
        return {"status": "error", "message": f"Failed to get challenge status: {exc}"}
