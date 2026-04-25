"""Quality MCP tools."""
import contextlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import a_sdlc.server as _server
from a_sdlc.server.quality_helpers import VALID_EVIDENCE_TYPES

__all__ = [
    "BEHAVIORAL_KEYWORDS",
    "INTEGRATION_KEYWORDS",
    "REQ_PATTERN",
    "STRUCTURAL_KEYWORDS",
    "VALID_CONTEXT_TYPES",
    "VALID_CORRECTION_CATEGORIES",
    "_CANDIDATE_PATTERN",
    "classify_depth",
    "create_remediation_tasks",
    "get_quality_report",
    "get_task_requirements",
    "link_task_requirements",
    "log_correction",
    "parse_requirements",
    "verify_acceptance_criteria",
    "waive_sprint_quality",
]

VALID_CONTEXT_TYPES = {"task", "prd", "sprint", "pr", "ad-hoc"}
VALID_CORRECTION_CATEGORIES = {
    "testing",
    "code-quality",
    "task-completeness",
    "integration",
    "documentation",
    "architecture",
    "security",
    "performance",
    "process",
}

# =========================================================================
# Requirement Parsing & Depth Classification (SDLC-P0029)
# =========================================================================

# Keyword sets for deterministic depth classification.
# Priority order: behavioral > integration > structural (default).
BEHAVIORAL_KEYWORDS: frozenset[str] = frozenset({
    "enforce",
    "block",
    "deny",
    "pause",
    "trigger",
    "alert",
    "validate",
    "prevent",
    "must not",
    "reject",
    "escalate",
    "track",
})

INTEGRATION_KEYWORDS: frozenset[str] = frozenset({
    "respects",
    "uses from",
    "depends on",
    "integrates with",
    "informed by",
})

STRUCTURAL_KEYWORDS: frozenset[str] = frozenset({
    "table",
    "column",
    "schema",
    "create",
    "store",
    "field",
    "record",
})

# Regex to extract requirement identifiers and their summaries from PRD markdown.
# Handles: "- FR-001: desc", "**FR-001**: desc", "- FR-001 - desc",
#           "* NFR-003: desc", bullet+bold combos, em-dash separators.
REQ_PATTERN = re.compile(
    r'[-*]?\s*\*{0,2}((?:FR|NFR|AC)-\d{3})\*{0,2}\s*[:\u2013\u2014-]\s*(.*)',
    re.MULTILINE,
)

# Looser pattern to detect non-standard requirement-like identifiers that
# were NOT captured by REQ_PATTERN (e.g., REQ-001, FREQ-1).
# Only matches REQ and FREQ prefixes to avoid false positives from FR/NFR/AC.
_CANDIDATE_PATTERN = re.compile(
    r'[-*]?\s*\*{0,2}((?:REQ|FREQ)-\d+[\w-]*)\*{0,2}\s*[:\u2013\u2014-]\s*(.*)',
    re.MULTILINE,
)


def classify_depth(text: str) -> str:
    """Classify a requirement's depth from its summary text.

    Uses deterministic keyword matching with priority:
    behavioral > integration > structural (default).

    When the text matches both behavioral and structural keywords,
    behavioral wins (as specified by the ambiguity rule).

    Args:
        text: The requirement summary text.

    Returns:
        One of "behavioral", "integration", or "structural".
    """
    lower = text.lower()

    # Check behavioral first (highest priority)
    for kw in BEHAVIORAL_KEYWORDS:
        if kw in lower:
            return "behavioral"

    # Check integration second
    for kw in INTEGRATION_KEYWORDS:
        if kw in lower:
            return "integration"

    # Default to structural
    return "structural"


@_server.mcp.tool()
def log_correction(
    context_type: str, context_id: str, category: str, description: str
) -> dict:
    """Log a correction to .sdlc/corrections.log.

    Records fixes, mistakes, and improvements made during any workflow step
    (task work, PRD updates, sprint execution, PR feedback, ad-hoc fixes).

    Args:
        context_type: One of: task, prd, sprint, pr, ad-hoc
        context_id: Entity ID (e.g., PROJ-T00001, PROJ-P0001, PR #42, or "none" for ad-hoc)
        category: One of: testing, code-quality, task-completeness, integration,
                  documentation, architecture, security, performance, process
        description: What was corrected and why
    """
    if context_type not in VALID_CONTEXT_TYPES:
        return {
            "status": "error",
            "message": f"Invalid context_type '{context_type}'. Must be one of: {', '.join(sorted(VALID_CONTEXT_TYPES))}",
        }

    if category not in VALID_CORRECTION_CATEGORIES:
        return {
            "status": "error",
            "message": f"Invalid category '{category}'. Must be one of: {', '.join(sorted(VALID_CORRECTION_CATEGORIES))}",
        }

    if not description or not description.strip():
        return {
            "status": "error",
            "message": "Description must not be empty.",
        }

    # Resolve project path: prefer DB project, fallback to cwd
    project_path = None
    try:
        db = _server.get_db()
        project_id = _server._get_current_project_id()
        if project_id:
            project = db.get_project(project_id)
            if project:
                project_path = project["path"]
    except Exception:
        pass

    if not project_path:
        project_path = os.getcwd()

    sdlc_dir = Path(project_path) / ".sdlc"
    sdlc_dir.mkdir(parents=True, exist_ok=True)
    log_file = sdlc_dir / "corrections.log"

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry_line = f"{timestamp} | {context_type}:{context_id} | {category} | {description.strip()}\n"

    try:
        with open(log_file, "a") as f:
            f.write(entry_line)
    except Exception as e:
        return {"status": "error", "message": f"Failed to write corrections.log: {e}"}

    return {
        "status": "logged",
        "entry": {
            "timestamp": timestamp,
            "context": f"{context_type}:{context_id}",
            "category": category,
            "description": description.strip(),
        },
    }


@_server.mcp.tool()
def parse_requirements(prd_id: str) -> dict[str, Any]:
    """Parse requirements from a PRD and store them with depth classification.

    Reads the PRD markdown content, extracts FR-xxx / NFR-xxx / AC-xxx
    requirements using regex, classifies each by depth (structural /
    behavioral / integration), and upserts them to the database.

    Re-running on the same PRD is idempotent: existing requirements are
    deleted first, then re-inserted from the current content.

    Args:
        prd_id: PRD identifier (e.g., "PROJ-P0001").

    Returns:
        Parsed requirements with counts, depth classifications, and any
        unrecognized candidates found in the content.
    """
    try:
        db = _server.get_db()
        content_mgr = _server.get_content_manager()

        # Retrieve PRD metadata
        prd = db.get_prd(prd_id)
        if not prd:
            return {"status": "not_found", "message": f"PRD not found: {prd_id}"}

        # Read PRD content from file
        content = None
        if prd.get("file_path"):
            content = content_mgr.read_content(Path(prd["file_path"]))
        else:
            content = content_mgr.read_prd(prd["project_id"], prd_id)

        if not content:
            return {
                "status": "ok",
                "counts": {"FR": 0, "NFR": 0, "AC": 0},
                "total": 0,
                "requirements": [],
                "unrecognized_candidates": [],
            }

        # Extract requirements via regex
        matches = REQ_PATTERN.findall(content)

        # Build requirement list with depth classification
        requirements: list[dict[str, Any]] = []
        seen_numbers: set[str] = set()
        counts: dict[str, int] = {"FR": 0, "NFR": 0, "AC": 0}

        for req_number, summary in matches:
            # Skip duplicates within the same parse (e.g., if a requirement
            # appears in both a heading and a list item)
            if req_number in seen_numbers:
                continue
            seen_numbers.add(req_number)

            summary_clean = summary.strip()
            depth = classify_depth(summary_clean)
            prefix = req_number.split("-")[0]  # "FR", "NFR", or "AC"
            req_type = prefix
            requirement_id = f"{prd_id}:{req_number}"

            requirements.append({
                "id": requirement_id,
                "req_number": req_number,
                "req_type": req_type,
                "summary": summary_clean,
                "depth": depth,
            })
            counts[prefix] = counts.get(prefix, 0) + 1

        # Delete existing requirements for idempotent re-parse
        storage = _server.get_storage()
        storage.delete_requirements(prd_id)

        # Upsert each requirement
        for req in requirements:
            storage.upsert_requirement(
                id=req["id"],
                prd_id=prd_id,
                req_type=req["req_type"],
                req_number=req["req_number"],
                summary=req["summary"],
                depth=req["depth"],
            )

        # Scan for unrecognized candidates (non-standard patterns)
        candidate_matches = _CANDIDATE_PATTERN.findall(content)
        unrecognized: list[dict[str, str]] = []
        for cand_id, cand_summary in candidate_matches:
            if cand_id not in seen_numbers:
                unrecognized.append({
                    "id": cand_id,
                    "text": cand_summary.strip(),
                })

        total = sum(counts.values())
        return {
            "status": "ok",
            "counts": counts,
            "total": total,
            "requirements": requirements,
            "unrecognized_candidates": unrecognized,
        }
    except Exception as exc:
        return {"status": "error", "message": f"Failed to parse requirements: {exc}"}


@_server.mcp.tool()
def verify_acceptance_criteria(
    task_id: str,
    ac_id: str,
    evidence_type: str,
    evidence: str,
) -> dict[str, Any]:
    """Record evidence-based verification for an acceptance criterion.

    Validates the AC exists, is linked to the task, and enforces behavioral
    strictness when configured. Re-verification overwrites previous evidence.

    Args:
        task_id: Task identifier (e.g., PROJ-T00001).
        ac_id: Acceptance criterion requirement ID (e.g., PROJ-P0001:AC-003).
        evidence_type: Type of evidence: 'test', 'manual', or 'demo'.
        evidence: Description of the verification evidence.

    Returns:
        Verification result with status and recorded evidence details.
    """
    # 1. Validate evidence_type
    if evidence_type not in VALID_EVIDENCE_TYPES:
        return {
            "status": "error",
            "message": (
                f"Invalid evidence_type '{evidence_type}'. "
                f"Must be one of: {', '.join(sorted(VALID_EVIDENCE_TYPES))}"
            ),
        }

    db = _server.get_db()

    # 2. Validate AC exists
    try:
        req = db.get_requirement(ac_id)
    except Exception as exc:
        return {"status": "error", "message": f"Failed to look up requirement: {exc}"}

    if not req:
        return {"status": "error", "message": f"Requirement not found: {ac_id}"}

    # 3. Validate requirement is an AC type
    if req.get("req_type") not in ("AC", "FR", "NFR"):
        return {
            "status": "error",
            "message": (
                f"{ac_id} is not an AC "
                f"(type: {req.get('req_type', 'unknown')})"
            ),
        }

    # 4. Validate task is linked to this AC
    try:
        task_reqs = db.get_task_requirements(task_id)
    except Exception as exc:
        return {
            "status": "error",
            "message": f"Failed to look up task requirements: {exc}",
        }

    linked_ids = {r["id"] for r in task_reqs}
    if ac_id not in linked_ids:
        return {
            "status": "error",
            "message": f"Task {task_id} is not linked to {ac_id}",
        }

    # 5. Behavioral strictness check
    quality_config = _server._load_quality_config_safe()
    if quality_config is not None:
        config_enabled = getattr(quality_config, "enabled", False)
        behavioral_test_required = getattr(
            quality_config, "behavioral_test_required", False
        )
        if config_enabled and behavioral_test_required:
            depth = req.get("depth", "structural")
            if depth == "behavioral" and evidence_type != "test":
                return {
                    "status": "error",
                    "message": (
                        f"Behavioral AC {ac_id} requires test evidence "
                        f"(got: {evidence_type}). Set "
                        "quality.behavioral_test_required=false "
                        "to override."
                    ),
                }

    # 6. Record verification
    try:
        db.record_ac_verification(
            requirement_id=ac_id,
            task_id=task_id,
            verified_by="mcp_tool",
            evidence_type=evidence_type,
            evidence=evidence,
        )
    except Exception as exc:
        return {
            "status": "error",
            "message": f"Failed to record verification: {exc}",
        }

    return {
        "status": "ok",
        "verification": {
            "ac_id": ac_id,
            "task_id": task_id,
            "evidence_type": evidence_type,
            "evidence": evidence,
        },
    }


@_server.mcp.tool()
def get_quality_report(
    scope: str,
    prd_id: str = "",
    sprint_id: str = "",
) -> dict[str, Any]:
    """Get quality reports: coverage, verification, or sprint-level quality.

    Scopes:
    - coverage: Requirement coverage and completion metrics for a PRD.
      Requires prd_id.
    - verification: AC verification status for a PRD. Requires prd_id.
    - sprint: Aggregated quality report for a sprint. Requires sprint_id.

    Args:
        scope: One of "coverage", "verification", "sprint".
        prd_id: PRD identifier (coverage/verification).
        sprint_id: Sprint identifier (sprint).
    """
    valid_scopes = ("coverage", "verification", "sprint")
    if scope not in valid_scopes:
        return {
            "status": "error",
            "message": f"Invalid scope '{scope}'. Must be one of: {', '.join(valid_scopes)}",
        }

    db = _server.get_db()

    if scope == "coverage":
        try:
            prd = db.get_prd(prd_id)
            if not prd:
                return {"status": "error", "message": f"PRD not found: {prd_id}"}

            stats = db.get_coverage_stats(prd_id)
            total = stats["total"]
            linked = stats["linked"]
            linkage_pct = round((linked / total) * 100, 1) if total > 0 else 100.0

            orphaned = db.get_orphaned_requirements(prd_id)

            all_reqs = db.get_requirements(prd_id)
            completed_tasks = 0
            total_tasks = 0
            behavioral_gaps: list[dict[str, Any]] = []

            for req in all_reqs:
                tasks = db.get_requirement_tasks(req["id"])
                total_tasks += len(tasks)
                completed_tasks += sum(
                    1 for t in tasks if t.get("status") == "completed"
                )

                if req.get("depth") == "behavioral" and len(tasks) > 0:
                    has_test_evidence = False
                    for t in tasks:
                        verifications = db.get_ac_verifications(t["id"])
                        for v in verifications:
                            if v.get("evidence_type") == "test":
                                has_test_evidence = True
                                break
                        if has_test_evidence:
                            break
                    if not has_test_evidence:
                        behavioral_gaps.append({
                            "id": req["id"],
                            "req_number": req["req_number"],
                            "summary": req.get("summary", ""),
                        })
                elif req.get("depth") == "behavioral" and len(tasks) == 0:
                    behavioral_gaps.append({
                        "id": req["id"],
                        "req_number": req["req_number"],
                        "summary": req.get("summary", ""),
                    })

            completion_pct = (
                round((completed_tasks / total_tasks) * 100, 1)
                if total_tasks > 0
                else 100.0
            )

            return {
                "status": "ok",
                "prd_id": prd_id,
                "linkage": {
                    "total": total,
                    "linked": linked,
                    "orphaned_count": len(orphaned),
                    "linkage_pct": linkage_pct,
                },
                "completion": {
                    "completed_tasks": completed_tasks,
                    "total_tasks": total_tasks,
                    "completion_pct": completion_pct,
                },
                "orphaned_requirements": [
                    {
                        "id": r["id"],
                        "req_number": r["req_number"],
                        "summary": r.get("summary", ""),
                    }
                    for r in orphaned
                ],
                "behavioral_gaps": behavioral_gaps,
                "by_type": stats["by_type"],
            }
        except Exception as exc:
            return {
                "status": "error",
                "message": f"Failed to generate coverage report: {exc}",
            }

    elif scope == "verification":
        try:
            prd = db.get_prd(prd_id)
            if not prd:
                return {"status": "error", "message": f"PRD not found: {prd_id}"}

            ac_reqs = db.get_requirements(prd_id, req_type="AC")
            acs: list[dict[str, Any]] = []
            verified_count = 0

            for req in ac_reqs:
                tasks = db.get_requirement_tasks(req["id"])
                verified = False
                evidence_type = None
                evidence = None

                for t in tasks:
                    verifications = db.get_ac_verifications(t["id"])
                    for v in verifications:
                        if v.get("requirement_id") == req["id"]:
                            verified = True
                            evidence_type = v.get("evidence_type")
                            evidence = v.get("evidence")
                            break
                    if verified:
                        break

                if verified:
                    verified_count += 1

                acs.append({
                    "id": req["id"],
                    "summary": req.get("summary", ""),
                    "depth": req.get("depth", "structural"),
                    "verified": verified,
                    "evidence_type": evidence_type,
                    "evidence": evidence,
                })

            total = len(acs)
            verified_pct = (
                round((verified_count / total) * 100, 1) if total > 0 else 100.0
            )

            return {
                "status": "ok",
                "prd_id": prd_id,
                "acs": acs,
                "total": total,
                "verified": verified_count,
                "verified_pct": verified_pct,
            }
        except Exception as exc:
            return {
                "status": "error",
                "message": f"Failed to get verification status: {exc}",
            }

    else:  # sprint
        return _get_sprint_quality_report(sprint_id)


def _get_sprint_quality_report(sprint_id: str) -> dict[str, Any]:
    """Get aggregated quality report for a sprint.

    Combines coverage, verification, challenge statistics, and scope drift
    across all PRDs in the sprint. Used by CLI gaps command and sprint
    completion gates.

    Args:
        sprint_id: Sprint identifier.

    Returns:
        Sprint-level quality report with per-PRD metrics, challenge stats,
        and scope drift analysis.
    """
    db = _server.get_db()
    try:
        sprint = db.get_sprint(sprint_id)
        if not sprint:
            return {
                "status": "error",
                "message": f"Sprint not found: {sprint_id}",
            }

        prds = db.get_sprint_prds(sprint_id)
        prd_reports: list[dict[str, Any]] = []

        # Aggregation accumulators
        agg_total_reqs = 0
        agg_linked_reqs = 0
        agg_orphaned_reqs = 0
        agg_verified_acs = 0
        agg_total_acs = 0

        for prd in prds:
            prd_id = prd["id"]

            # Coverage
            cov_stats = db.get_coverage_stats(prd_id)
            cov_total = cov_stats["total"]
            cov_linked = cov_stats["linked"]
            cov_orphaned = cov_total - cov_linked

            agg_total_reqs += cov_total
            agg_linked_reqs += cov_linked
            agg_orphaned_reqs += cov_orphaned

            # Verification
            ac_reqs = db.get_requirements(prd_id, req_type="AC")
            prd_verified = 0
            prd_total_acs = len(ac_reqs)

            for req in ac_reqs:
                tasks = db.get_requirement_tasks(req["id"])
                verified = False
                for t in tasks:
                    verifications = db.get_ac_verifications(t["id"])
                    for v in verifications:
                        if v.get("requirement_id") == req["id"]:
                            verified = True
                            break
                    if verified:
                        break
                if verified:
                    prd_verified += 1

            agg_verified_acs += prd_verified
            agg_total_acs += prd_total_acs

            prd_reports.append({
                "prd_id": prd_id,
                "coverage": {
                    "total": cov_total,
                    "linked": cov_linked,
                    "orphaned": cov_orphaned,
                    "linkage_pct": (
                        round((cov_linked / cov_total) * 100, 1)
                        if cov_total > 0
                        else 100.0
                    ),
                },
                "verification": {
                    "total": prd_total_acs,
                    "verified": prd_verified,
                    "verified_pct": (
                        round((prd_verified / prd_total_acs) * 100, 1)
                        if prd_total_acs > 0
                        else 100.0
                    ),
                },
            })

        # Aggregate percentages
        agg_coverage_pct = (
            round((agg_linked_reqs / agg_total_reqs) * 100, 1)
            if agg_total_reqs > 0
            else 100.0
        )
        agg_verification_pct = (
            round((agg_verified_acs / agg_total_acs) * 100, 1)
            if agg_total_acs > 0
            else 100.0
        )

        # Challenge stats: iterate artifacts (prd, design, split) per sprint PRD
        challenged = 0
        unchallenged = 0
        objections_by_category: dict[str, int] = {}
        resolutions: dict[str, int] = {
            "resolved": 0,
            "escalated": 0,
            "accepted": 0,
        }
        total_challenge_rounds = 0
        first_round_resolutions = 0
        auto_terminated_challenges = 0
        escalated_challenges = 0

        for prd in prds:
            prd_id = prd["id"]
            for artifact_type in ("prd", "design", "split"):
                ch_status = db.get_challenge_status(artifact_type, prd_id)
                if ch_status["total_rounds"] > 0:
                    challenged += 1
                    # Parse objections and effectiveness from challenge rounds
                    rounds = db.get_challenge_rounds(artifact_type, prd_id)
                    total_challenge_rounds += len(rounds)
                    for rnd in rounds:
                        if rnd.get("round_number") == 1 and rnd.get("status") == "resolved":
                            first_round_resolutions += 1
                        if rnd.get("status") == "auto_terminated":
                            auto_terminated_challenges += 1
                        if rnd.get("status") == "escalated":
                            escalated_challenges += 1
                        objs = rnd.get("objections", [])
                        if isinstance(objs, str):
                            with contextlib.suppress(
                                json.JSONDecodeError, TypeError
                            ):
                                objs = json.loads(objs)
                        if isinstance(objs, list):
                            for obj in objs:
                                if isinstance(obj, dict):
                                    cat = obj.get("category", "unknown")
                                    objections_by_category[cat] = (
                                        objections_by_category.get(cat, 0)
                                        + 1
                                    )
                        # Resolution tracking from verdict
                        verd = rnd.get("verdict")
                        if isinstance(verd, str):
                            try:
                                verd = json.loads(verd)
                            except (json.JSONDecodeError, TypeError):
                                verd = None
                        if isinstance(verd, dict):
                            resolutions["resolved"] += len(
                                verd.get("resolved", [])
                            )
                            resolutions["accepted"] += len(
                                verd.get("accepted", [])
                            )
                            resolutions["escalated"] += len(
                                verd.get("escalated", [])
                            )
                else:
                    unchallenged += 1

        # Scope drift: tasks in sprint with no requirement links
        sprint_tasks = db.list_tasks_by_sprint(
            sprint["project_id"], sprint_id
        )
        unlinked_tasks: list[dict[str, Any]] = []
        for task in sprint_tasks:
            task_reqs = db.get_task_requirements(task["id"])
            if len(task_reqs) == 0:
                unlinked_tasks.append({
                    "id": task["id"],
                    "title": task["title"],
                    "prd_id": task.get("prd_id"),
                })

        # Pass/fail: all requirements linked and all ACs verified
        quality_pass = (
            agg_coverage_pct >= 100.0 and agg_verification_pct >= 100.0
        )

        return {
            "status": "ok",
            "sprint_id": sprint_id,
            "prds": prd_reports,
            "aggregate": {
                "total_requirements": agg_total_reqs,
                "linked_requirements": agg_linked_reqs,
                "orphaned_requirements": agg_orphaned_reqs,
                "verified_acs": agg_verified_acs,
                "total_acs": agg_total_acs,
                "coverage_pct": agg_coverage_pct,
                "verification_pct": agg_verification_pct,
            },
            "challenge_stats": {
                "challenged": challenged,
                "unchallenged": unchallenged,
                "objections_by_category": objections_by_category,
                "resolutions": resolutions,
                "effectiveness": {
                    "first_round_resolution_rate": round(first_round_resolutions / challenged, 2) if challenged else 0.0,
                    "escalation_rate": round(escalated_challenges / challenged, 2) if challenged else 0.0,
                    "auto_termination_rate": round(auto_terminated_challenges / challenged, 2) if challenged else 0.0,
                    "avg_rounds_per_artifact": round(total_challenge_rounds / challenged, 2) if challenged else 0.0,
                    "total_objections": sum(objections_by_category.values()),
                    "resolution_rate": round(
                        (resolutions["resolved"] + resolutions["accepted"]) /
                        sum(objections_by_category.values()), 2
                    ) if sum(objections_by_category.values()) else 0.0,
                },
            },
            "scope_drift": {
                "unlinked_tasks": unlinked_tasks,
                "unlinked_count": len(unlinked_tasks),
            },
            "pass": quality_pass,
        }
    except Exception as exc:
        return {
            "status": "error",
            "message": f"Failed to generate sprint quality report: {exc}",
        }


@_server.mcp.tool()
def link_task_requirements(
    task_id: str,
    requirement_ids: list[str],
) -> dict[str, Any]:
    """Link a task to one or more requirements.

    Validates that the task and all requirement IDs exist before creating
    any links. If any requirement IDs are invalid, returns an error
    without creating any links.

    Args:
        task_id: The task to link requirements to.
        requirement_ids: List of requirement IDs to link (e.g. ["PROJ-P0001:FR-001"]).

    Returns:
        Status with count of linked requirements, or error details.
    """
    db = _server.get_db()

    # Validate task exists
    task = db.get_task(task_id)
    if not task:
        return {"status": "error", "message": f"Task not found: {task_id}"}

    if not requirement_ids:
        return {"status": "error", "message": "No requirement IDs provided"}

    # Validate all requirement IDs exist before linking any
    invalid_ids = []
    for req_id in requirement_ids:
        req = db.get_requirement(req_id)
        if req is None:
            invalid_ids.append(req_id)

    if invalid_ids:
        return {
            "status": "error",
            "message": f"Requirements not found: {invalid_ids}",
        }

    # All valid -- create links
    try:
        linked = 0
        for req_id in requirement_ids:
            db.link_task_requirement(req_id, task_id)
            linked += 1

        return {"status": "ok", "linked": linked, "task_id": task_id}
    except Exception as exc:
        return {"status": "error", "message": f"Failed to link requirements: {exc}"}


@_server.mcp.tool()
def get_task_requirements(task_id: str) -> dict[str, Any]:
    """Get all requirements linked to a task, grouped by type.

    Returns requirements with depth and verification status from
    a LEFT JOIN on ac_verifications.

    Args:
        task_id: The task to query requirements for.

    Returns:
        Requirements grouped by type (functional, non-functional, ac)
        with depth and verification status.
    """
    db = _server.get_db()

    # Validate task exists
    task = db.get_task(task_id)
    if not task:
        return {"status": "error", "message": f"Task not found: {task_id}"}

    try:
        reqs = db.get_task_requirements(task_id)

        # Group by req_type
        grouped: dict[str, list[dict[str, Any]]] = {}
        for req in reqs:
            req_type = req.get("req_type", "unknown")
            if req_type not in grouped:
                grouped[req_type] = []
            grouped[req_type].append(req)

        return {
            "status": "ok",
            "task_id": task_id,
            "requirements": grouped,
            "total": len(reqs),
        }
    except Exception as exc:
        return {"status": "error", "message": f"Failed to get requirements: {exc}"}


# =============================================================================
# Remediation & Sprint Quality Gate (SDLC-P0029)
# =============================================================================

@_server.mcp.tool()
def create_remediation_tasks(sprint_id: str) -> dict[str, Any]:
    """Create remediation tasks for quality gaps in a sprint (FR-036 / AC-021).

    Inspects the sprint quality report and creates a task for each:
    - Orphaned requirement (no linked tasks)
    - Unverified acceptance criterion (linked but not verified)
    - Scope-drift task (task with no requirement links)

    All created tasks are tagged with ``remediation:true`` metadata so they
    can be distinguished from regular implementation tasks.

    Args:
        sprint_id: Sprint identifier.

    Returns:
        List of created remediation tasks with IDs and titles.
    """
    db = _server.get_db()
    content_mgr = _server.get_content_manager()

    try:
        sprint = db.get_sprint(sprint_id)
        if not sprint:
            return {"status": "error", "message": f"Sprint not found: {sprint_id}"}

        project_id = sprint["project_id"]
        prds = db.get_sprint_prds(sprint_id)

        created_tasks: list[dict[str, Any]] = []

        # 1. Orphaned requirements -- requirements with no linked tasks
        for prd in prds:
            prd_id = prd["id"]
            orphaned = db.get_orphaned_requirements(prd_id)
            for req in orphaned:
                title = f"Remediate: {req['req_number']} \u2014 {req['summary']}"
                task_id = db.get_next_task_id(project_id)
                file_path = content_mgr.write_task(
                    project_id=project_id,
                    task_id=task_id,
                    title=title,
                    description=f"Link tasks to requirement {req['id']} or implement coverage.",
                    priority="high",
                    status="pending",
                    component="remediation",
                    prd_id=prd_id,
                    data={"remediation": True, "gap_type": "orphaned_requirement", "source_id": req["id"]},
                )
                task = db.create_task(
                    task_id=task_id,
                    project_id=project_id,
                    title=title,
                    file_path=str(file_path),
                    prd_id=prd_id,
                    priority="high",
                    component="remediation",
                )
                created_tasks.append({
                    "task_id": task_id,
                    "title": title,
                    "gap_type": "orphaned_requirement",
                    "source_id": req["id"],
                })

        # 2. Unverified acceptance criteria
        for prd in prds:
            prd_id = prd["id"]
            ac_reqs = db.get_requirements(prd_id, req_type="AC")
            for req in ac_reqs:
                # Check if any linked task has verified this AC
                linked_tasks = db.get_requirement_tasks(req["id"])
                verified = False
                for t in linked_tasks:
                    verifications = db.get_ac_verifications(t["id"])
                    for v in verifications:
                        if v.get("requirement_id") == req["id"]:
                            verified = True
                            break
                    if verified:
                        break

                if not verified and linked_tasks:
                    title = f"Verify: {req['req_number']} \u2014 {req['summary']}"
                    task_id = db.get_next_task_id(project_id)
                    file_path = content_mgr.write_task(
                        project_id=project_id,
                        task_id=task_id,
                        title=title,
                        description=f"Verify acceptance criterion {req['id']} with evidence.",
                        priority="high",
                        status="pending",
                        component="remediation",
                        prd_id=prd_id,
                        data={"remediation": True, "gap_type": "unverified_ac", "source_id": req["id"]},
                    )
                    task = db.create_task(
                        task_id=task_id,
                        project_id=project_id,
                        title=title,
                        file_path=str(file_path),
                        prd_id=prd_id,
                        priority="high",
                        component="remediation",
                    )
                    created_tasks.append({
                        "task_id": task_id,
                        "title": title,
                        "gap_type": "unverified_ac",
                        "source_id": req["id"],
                    })

        # 3. Scope-drift tasks -- tasks with no requirement links
        sprint_tasks = db.list_tasks_by_sprint(project_id, sprint_id)
        for task in sprint_tasks:
            task_reqs = db.get_task_requirements(task["id"])
            if len(task_reqs) == 0:
                title = f"Trace: {task['id']}"
                task_id = db.get_next_task_id(project_id)
                file_path = content_mgr.write_task(
                    project_id=project_id,
                    task_id=task_id,
                    title=title,
                    description=f"Link task {task['id']} to requirements or justify its scope.",
                    priority="medium",
                    status="pending",
                    component="remediation",
                    prd_id=task.get("prd_id"),
                    data={"remediation": True, "gap_type": "scope_drift", "source_id": task["id"]},
                )
                db.create_task(
                    task_id=task_id,
                    project_id=project_id,
                    title=title,
                    file_path=str(file_path),
                    prd_id=task.get("prd_id"),
                    priority="medium",
                    component="remediation",
                )
                created_tasks.append({
                    "task_id": task_id,
                    "title": title,
                    "gap_type": "scope_drift",
                    "source_id": task["id"],
                })

        return {
            "status": "ok",
            "sprint_id": sprint_id,
            "created": len(created_tasks),
            "tasks": created_tasks,
        }
    except Exception as exc:
        return {"status": "error", "message": f"Failed to create remediation tasks: {exc}"}


@_server.mcp.tool()
def waive_sprint_quality(sprint_id: str, reason: str) -> dict[str, Any]:
    """Waive quality gate for sprint completion (FR-037 / AC-023).

    Records a waiver that allows ``complete_sprint`` to proceed despite
    unresolved quality gaps. The waiver is stored in memory for the
    lifetime of the MCP server process and includes an audit trail with
    reason, sprint_id, and timestamp.

    Args:
        sprint_id: Sprint identifier to waive quality checks for.
        reason: Human-readable justification for the waiver.

    Returns:
        Waiver confirmation with timestamp and sprint_id.
    """
    db = _server.get_db()

    sprint = db.get_sprint(sprint_id)
    if not sprint:
        return {"status": "error", "message": f"Sprint not found: {sprint_id}"}

    if not reason or not reason.strip():
        return {"status": "error", "message": "A non-empty reason is required for quality waiver."}

    waiver = {
        "sprint_id": sprint_id,
        "reason": reason.strip(),
        "waived_at": datetime.now(timezone.utc).isoformat(),
    }
    _server._sprint_waivers[sprint_id] = waiver

    return {
        "status": "ok",
        "message": f"Quality gate waived for sprint {sprint_id}.",
        "waiver": waiver,
    }
