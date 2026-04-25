"""Agent governance MCP tools."""

import json
from pathlib import Path
from typing import Any

import a_sdlc.server as _server

__all__ = [
    "manage_agent",
    "check_permission",
    "log_audit_event",
    "manage_agent_budget",
    "propose_work",
    "check_permission_compliance",
    "get_agent_analytics",
    "get_available_work_for_agent",
    "manage_agent_task",
    "agent_messages",
    "self_assess",
    "auto_compose_team",
    "enforce_team_health",
]


# =============================================================================
# Merge 3.1: Agent Lifecycle (register + propose + suspend + retire → 1 tool)
# =============================================================================


@_server.mcp.tool()
def manage_agent(
    action: str,
    persona_type: str = "",
    display_name: str = "",
    agent_id: str = "",
    justification: str = "",
    reason: str = "",
) -> dict[str, Any]:
    """Manage agent lifecycle: register, propose, suspend, or retire.

    Actions:
    - register: Create active agent. Requires persona_type, display_name.
    - propose: Propose agent for human approval. Requires persona_type, justification.
    - suspend: Suspend agent, releasing active claims. Requires agent_id.
    - retire: Permanently retire agent. Requires agent_id.

    Args:
        action: One of "register", "propose", "suspend", "retire".
        persona_type: Agent persona type (register/propose).
        display_name: Display name (register only).
        agent_id: Agent ID (suspend/retire).
        justification: Reason for proposal (propose only).
        reason: Reason for suspension (suspend only).
    """
    valid_actions = ("register", "propose", "suspend", "retire")
    if action not in valid_actions:
        return {
            "status": "error",
            "message": f"Invalid action '{action}'. Must be one of: {', '.join(valid_actions)}",
        }

    db = _server.get_db()
    project_id = _server._get_current_project_id()

    if action == "register":
        if not project_id:
            return {
                "status": "no_project",
                "message": "No project found. Run /sdlc:init first.",
            }
        try:
            aid = db.get_next_agent_id(project_id)
            agent = db.create_agent(aid, project_id, persona_type, display_name)
            db.append_audit_log(
                project_id,
                "agent_registered",
                "success",
                agent_id=aid,
                details=f"persona_type={persona_type}",
            )
            return {"status": "ok", "agent": agent}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    elif action == "propose":
        if not project_id:
            return {
                "status": "no_project",
                "message": "No project found. Run /sdlc:init first.",
            }
        try:
            aid = db.get_next_agent_id(project_id)
            dn = persona_type.replace("_", " ").title()
            agent = db.create_agent(
                aid, project_id, persona_type, dn, status="proposed"
            )
            db.append_audit_log(
                project_id,
                "agent_proposed",
                "pending",
                agent_id=aid,
                details=justification,
            )
            return {
                "status": "ok",
                "agent": agent,
                "message": (
                    f"Agent {aid} proposed. Awaiting approval via "
                    f"'a-sdlc agent approve {aid}'."
                ),
            }
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    elif action == "suspend":
        try:
            claims = db.list_claims_by_agent(agent_id)
            for claim in claims:
                if claim.get("status") == "active":
                    db.release_task(claim["task_id"], agent_id, reason="agent_suspended")
            agent = db.suspend_agent(agent_id)
            if project_id:
                db.append_audit_log(
                    project_id,
                    "agent_suspended",
                    "success",
                    agent_id=agent_id,
                    details=reason or None,
                )
            return {"status": "ok", "agent": agent}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    else:  # retire
        try:
            claims = db.list_claims_by_agent(agent_id)
            for claim in claims:
                if claim.get("status") == "active":
                    db.release_task(claim["task_id"], agent_id, reason="agent_retired")
            agent = db.retire_agent(agent_id)
            if project_id:
                db.append_audit_log(
                    project_id,
                    "agent_retired",
                    "success",
                    agent_id=agent_id,
                )
            return {
                "status": "ok",
                "agent": agent,
                "message": "Agent retired. All historical data preserved.",
            }
        except Exception as exc:
            return {"status": "error", "message": str(exc)}


@_server.mcp.tool()
def check_permission(
    agent_id: str, permission_type: str, permission_value: str
) -> dict[str, Any]:
    """Check if an agent has a specific permission.

    Returns whether the agent is allowed to perform the specified action.
    Fast indexed query for <10ms response.
    """
    db = _server.get_db()
    try:
        allowed = db.check_agent_permission(
            agent_id, permission_type, permission_value
        )
        return {
            "status": "ok",
            "allowed": allowed,
            "agent_id": agent_id,
            "permission_type": permission_type,
            "permission_value": permission_value,
        }
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


@_server.mcp.tool()
def log_audit_event(
    agent_id: str,
    action_type: str,
    outcome: str = "success",
    target_entity: str = "",
    details: str = "",
) -> dict[str, Any]:
    """Log an event to the governance audit trail.

    Append-only audit log for tracking agent actions, decisions, and outcomes.
    """
    db = _server.get_db()
    project_id = _server._get_current_project_id()
    if not project_id:
        return {
            "status": "no_project",
            "message": "No project found. Run /sdlc:init first.",
        }
    try:
        entry = db.append_audit_log(
            project_id,
            action_type,
            outcome,
            agent_id=agent_id,
            target_entity=target_entity or None,
            details=details or None,
        )
        return {"status": "ok", "audit_entry": entry}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


# =============================================================================
# Merge 3.3: Agent Budget (set + get + report → 1 tool)
# =============================================================================


@_server.mcp.tool()
def manage_agent_budget(
    action: str,
    agent_id: str,
    token_limit: int = 100000,
    cost_limit_cents: int = 500,
    tokens: int = 0,
    cost_cents: int = 0,
    run_id: str = "",
) -> dict[str, Any]:
    """Manage agent budget: set limits, get status, or report usage.

    Actions:
    - set: Create/update budget with token and cost limits.
    - get: Get current budget status with usage percentages.
    - report: Report resource consumption; auto-enforces budget limits (REM-004/005).

    Args:
        action: One of "set", "get", "report".
        agent_id: Agent identifier.
        token_limit: Max tokens allowed (set only).
        cost_limit_cents: Max cost in cents (set only).
        tokens: Token count to add (report only).
        cost_cents: Cost in cents to add (report only).
        run_id: Optional execution run scope.
    """
    valid_actions = ("set", "get", "report")
    if action not in valid_actions:
        return {
            "status": "error",
            "message": f"Invalid action '{action}'. Must be one of: {', '.join(valid_actions)}",
        }

    db = _server.get_db()
    project_id = _server._get_current_project_id()

    if action == "set":
        try:
            budget = db.create_agent_budget(
                agent_id,
                run_id=run_id or None,
                token_limit=token_limit,
                cost_limit_cents=cost_limit_cents,
            )
            if project_id:
                db.append_audit_log(
                    project_id,
                    "budget_set",
                    "success",
                    agent_id=agent_id,
                    details=json.dumps({
                        "token_limit": token_limit,
                        "cost_limit_cents": cost_limit_cents,
                        "run_id": run_id or None,
                    }),
                )
            return {"status": "ok", "budget": budget}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    elif action == "get":
        try:
            budget = db.get_agent_budget(agent_id, run_id=run_id or None)
            if not budget:
                return {
                    "status": "ok",
                    "budget": None,
                    "message": f"No budget set for agent {agent_id}",
                }
            result = dict(budget)
            if budget.get("token_limit") and budget["token_limit"] > 0:
                result["token_usage_pct"] = round(
                    budget["token_used"] * 100 / budget["token_limit"], 1
                )
            if budget.get("cost_limit_cents") and budget["cost_limit_cents"] > 0:
                result["cost_usage_pct"] = round(
                    budget["cost_used_cents"] * 100 / budget["cost_limit_cents"], 1
                )
            return {"status": "ok", "budget": result}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    else:  # report
        try:
            updated = db.increment_agent_budget(
                agent_id,
                tokens_delta=tokens,
                cost_delta_cents=cost_cents,
                run_id=run_id or None,
            )
            if not updated:
                return {
                    "status": "ok",
                    "message": f"No budget set for agent {agent_id}; usage not tracked.",
                    "exceeded": False,
                    "action_taken": None,
                }

            exceeded = False
            reasons: list[str] = []
            if (
                updated.get("token_limit")
                and updated["token_limit"] > 0
                and updated.get("token_used", 0) >= updated["token_limit"]
            ):
                exceeded = True
                reasons.append(
                    f"tokens: {updated['token_used']}/{updated['token_limit']}"
                )
            if (
                updated.get("cost_limit_cents")
                and updated["cost_limit_cents"] > 0
                and updated.get("cost_used_cents", 0) >= updated["cost_limit_cents"]
            ):
                exceeded = True
                reasons.append(
                    f"cost: {updated['cost_used_cents']}/{updated['cost_limit_cents']}c"
                )

            action_taken = None
            if exceeded:
                budget_action = "pause"
                try:
                    from a_sdlc.core.git_config import (
                        PROJECT_CONFIG_DIR,
                        PROJECT_CONFIG_FILE,
                        _load_yaml,
                    )

                    config_path = Path.cwd() / PROJECT_CONFIG_DIR / PROJECT_CONFIG_FILE
                    config = _load_yaml(config_path)
                    gov = config.get("governance", {})
                    if isinstance(gov, dict):
                        budget_cfg = gov.get("budget", {})
                        if isinstance(budget_cfg, dict):
                            budget_action = budget_cfg.get("action", "pause")
                except Exception:
                    pass

                if budget_action in ("pause", "abort"):
                    db.suspend_agent(agent_id)
                    action_taken = "suspended"
                    if project_id:
                        db.append_audit_log(
                            project_id,
                            "budget_exceeded_suspend",
                            "success",
                            agent_id=agent_id,
                            details=json.dumps({
                                "reasons": reasons,
                                "action": budget_action,
                            }),
                        )
                elif budget_action == "alert":
                    action_taken = "alert"
                    if project_id:
                        db.append_audit_log(
                            project_id,
                            "budget_exceeded_alert",
                            "warning",
                            agent_id=agent_id,
                            details=json.dumps({"reasons": reasons}),
                        )

            return {
                "status": "ok",
                "budget": dict(updated),
                "exceeded": exceeded,
                "reasons": reasons,
                "action_taken": action_taken,
            }
        except Exception as exc:
            return {"status": "error", "message": str(exc)}


@_server.mcp.tool()
def propose_work(agent_id: str, sprint_id: str = "") -> dict[str, Any]:
    """Propose work for an agent with permission-aware routing (REM-002).

    Combines ``get_available_work_for_agent`` with the agent's permission
    set so the caller can make informed assignment decisions.

    Args:
        agent_id: Agent requesting work.
        sprint_id: Optional sprint scope.

    Returns:
        Available tasks annotated with the agent's permissions.
    """
    db = _server.get_db()
    project_id = _server._get_current_project_id()
    if not project_id:
        return {
            "status": "no_project",
            "message": "No project found. Run /sdlc:init first.",
        }
    try:
        routing_config = _server._load_routing_config()
        component_map = routing_config.get("component_map")
        if component_map and not isinstance(component_map, dict):
            component_map = None

        tasks = db.get_available_work(
            project_id,
            agent_id,
            sprint_id=sprint_id or None,
            component_map=component_map,
        )
        permissions = db.get_agent_permissions(agent_id)
        return {
            "status": "ok",
            "available_tasks": tasks,
            "count": len(tasks),
            "agent_permissions": permissions,
            "agent_id": agent_id,
        }
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


@_server.mcp.tool()
def check_permission_compliance(
    agent_id: str,
    actions: list[str],
) -> dict[str, Any]:
    """Post-hoc audit of agent actions against its permission set (REM-002).

    Accepts a list of ``type:value`` action strings and checks each against
    the agent's permissions.  Returns a compliance report with violations.

    Example actions: ``["tool:git_push", "file_path:/src/config.py"]``

    Args:
        agent_id: Agent to audit.
        actions: List of ``"permission_type:permission_value"`` strings.

    Returns:
        Compliance report with ``compliant`` flag, violations list, and total
        checked count.
    """
    db = _server.get_db()
    project_id = _server._get_current_project_id()
    try:
        violations: list[dict[str, str]] = []
        checked = 0

        for action in actions:
            if ":" not in action:
                continue
            ptype, _, pvalue = action.partition(":")
            ptype = ptype.strip()
            pvalue = pvalue.strip()
            checked += 1

            allowed = db.check_agent_permission(agent_id, ptype, pvalue)
            if not allowed:
                violations.append({
                    "action": action,
                    "permission_type": ptype,
                    "permission_value": pvalue,
                    "allowed": False,
                })

        compliant = len(violations) == 0

        # Log non-compliant results to audit (REM-003)
        if not compliant and project_id:
            db.append_audit_log(
                project_id,
                "permission_compliance_violation",
                "warning",
                agent_id=agent_id,
                details=json.dumps({
                    "violations": violations,
                    "total_checked": checked,
                }),
            )

        return {
            "status": "ok",
            "agent_id": agent_id,
            "compliant": compliant,
            "violations": violations,
            "total_checked": checked,
        }
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


# =============================================================================
# Merge 3.5: Agent Analytics (performance + org + team → 1 tool)
# =============================================================================


@_server.mcp.tool()
def get_agent_analytics(
    scope: str,
    agent_id: str = "",
    sprint_id: str = "",
    team_id: int = 0,
) -> dict[str, Any]:
    """Get agent analytics: performance metrics, org overview, or team composition.

    Scopes:
    - performance: Agent performance metrics. Requires agent_id, optional sprint_id.
    - org: Organizational overview of all agents.
    - team: Team details with member agents. Requires team_id.

    Args:
        scope: One of "performance", "org", "team".
        agent_id: Agent ID (performance only).
        sprint_id: Optional sprint filter (performance only).
        team_id: Team ID (team only).
    """
    valid_scopes = ("performance", "org", "team")
    if scope not in valid_scopes:
        return {
            "status": "error",
            "message": f"Invalid scope '{scope}'. Must be one of: {', '.join(valid_scopes)}",
        }

    db = _server.get_db()

    if scope == "performance":
        try:
            if sprint_id:
                perf = db.get_agent_performance(agent_id, sprint_id)
            else:
                perf = db.compute_agent_performance(agent_id)
            return {"status": "ok", "performance": perf}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    elif scope == "org":
        project_id = _server._get_current_project_id()
        if not project_id:
            return {
                "status": "no_project",
                "message": "No project found. Run /sdlc:init first.",
            }
        try:
            overview = db.get_org_overview(project_id)
            return {"status": "ok", "overview": overview}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    else:  # team
        try:
            team = db.get_team_composition(team_id)
            return {"status": "ok", "team": team}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}


@_server.mcp.tool()
def get_available_work_for_agent(
    agent_id: str, sprint_id: str = ""
) -> dict[str, Any]:
    """Get available tasks for an agent to claim with three-tier routing.

    Three-tier priority routing:
    - Tier 1: Component match -- tasks whose component matches the agent's
      persona type via the routing.component_map configuration
    - Tier 2: Priority sort -- remaining tasks ordered by priority
      (critical > high > medium > low)
    - Tier 3: Fallback -- any remaining available task

    Within each tier, tasks include the agent's performance_score for
    downstream weighting decisions.

    Optionally filter by sprint (derived via PRD relationship).
    """
    db = _server.get_db()
    project_id = _server._get_current_project_id()
    if not project_id:
        return {
            "status": "no_project",
            "message": "No project found. Run /sdlc:init first.",
        }
    try:
        # Load component map from routing config (REM-007)
        routing_config = _server._load_routing_config()
        component_map = routing_config.get("component_map")
        if component_map and not isinstance(component_map, dict):
            component_map = None

        tasks = db.get_available_work(
            project_id,
            agent_id,
            sprint_id=sprint_id or None,
            component_map=component_map,
        )
        return {"status": "ok", "available_tasks": tasks, "count": len(tasks)}
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


# =============================================================================
# Merge 3.2: Agent Task Ops (claim + release + assign → 1 tool)
# =============================================================================


@_server.mcp.tool()
def manage_agent_task(
    action: str,
    agent_id: str,
    task_id: str,
    reason: str = "manual",
) -> dict[str, Any]:
    """Manage agent-task relationships: claim, release, or assign.

    Actions:
    - claim: Atomically claim a task for an agent.
    - release: Release a task claim, returning to pending pool.
    - assign: Explicitly assign task (by human or lead agent), with audit log.

    Args:
        action: One of "claim", "release", "assign".
        agent_id: Agent identifier.
        task_id: Task identifier.
        reason: Reason for release (release only, default "manual").
    """
    valid_actions = ("claim", "release", "assign")
    if action not in valid_actions:
        return {
            "status": "error",
            "message": f"Invalid action '{action}'. Must be one of: {', '.join(valid_actions)}",
        }

    db = _server.get_db()

    if action == "claim":
        try:
            claim = db.claim_task(task_id, agent_id)
            return {
                "status": "ok",
                "claim": claim,
                "message": f"Task {task_id} claimed by {agent_id}",
            }
        except ValueError as exc:
            return {"status": "conflict", "message": str(exc)}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    elif action == "release":
        try:
            claim = db.release_task(task_id, agent_id, reason)
            if claim is None:
                return {
                    "status": "not_found",
                    "message": (
                        f"No active claim found for task {task_id} by agent {agent_id}"
                    ),
                }
            return {
                "status": "ok",
                "claim": claim,
                "message": f"Task {task_id} released by {agent_id}",
            }
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    else:  # assign
        try:
            claim = db.claim_task(task_id, agent_id)
            project_id = _server._get_current_project_id() or ""
            db.append_audit_log(
                project_id,
                "task_assigned",
                "success",
                agent_id=agent_id,
                target_entity=task_id,
                details="Explicit assignment",
            )
            return {
                "status": "ok",
                "claim": claim,
                "message": f"Task {task_id} assigned to {agent_id}",
            }
        except ValueError as exc:
            return {"status": "conflict", "message": str(exc)}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}


# =============================================================================
# Merge 3.4: Agent Messaging (send + get → 1 tool)
# =============================================================================


@_server.mcp.tool()
def agent_messages(
    action: str,
    agent_id: str = "",
    from_agent_id: str = "",
    to_agent_id: str = "",
    message_type: str = "",
    content: str = "",
    related_task_id: str = "",
    unread_only: bool = False,
) -> dict[str, Any]:
    """Send or retrieve agent messages.

    Actions:
    - send: Send message between agents. Requires from_agent_id, to_agent_id,
      message_type, content.
    - get: Get messages for an agent. Requires agent_id.

    Args:
        action: One of "send", "get".
        agent_id: Receiving agent ID (get only).
        from_agent_id: Sender agent ID (send only).
        to_agent_id: Recipient agent ID (send only).
        message_type: Message type e.g. 'handoff', 'blocker' (send only).
        content: Message content (send only).
        related_task_id: Optional linked task (send only).
        unread_only: Filter to unread messages (get only).
    """
    valid_actions = ("send", "get")
    if action not in valid_actions:
        return {
            "status": "error",
            "message": f"Invalid action '{action}'. Must be one of: {', '.join(valid_actions)}",
        }

    db = _server.get_db()

    if action == "send":
        try:
            msg = db.send_agent_message(
                from_agent_id,
                to_agent_id,
                message_type,
                content,
                related_task_id=related_task_id or None,
            )
            return {"status": "ok", "message": msg}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    else:  # get
        try:
            messages = db.get_agent_messages(agent_id, unread_only=unread_only)
            return {"status": "ok", "messages": messages, "count": len(messages)}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}


# =============================================================================
# Agent Routing & Team Health Tools (SDLC-P0027/P0028)
# =============================================================================


@_server.mcp.tool()
def self_assess(agent_id: str, task_id: str) -> dict[str, Any]:
    """Self-assess an agent's confidence for a specific task (REM-008).

    Returns a confidence score (0-100) based on:
    - Component match: Does the agent's persona match the task component?
    - Historical success rate: Agent's performance on similar tasks.
    - Overall performance score: Rolling agent quality metric.

    Args:
        agent_id: Agent identifier to assess.
        task_id: Task identifier to assess against.

    Returns:
        Assessment dict with confidence score, factors, and recommendation.
    """
    db = _server.get_db()
    try:
        agent = db.get_agent(agent_id)
        if not agent:
            return {"status": "error", "message": f"Agent not found: {agent_id}"}

        task = db.get_task(task_id)
        if not task:
            return {"status": "error", "message": f"Task not found: {task_id}"}

        persona_type = agent.get("persona_type", "")
        perf_score = agent.get("performance_score") or 50.0
        task_component = (task.get("component") or "").lower()

        # Factor 1: Component match via routing config
        routing_config = _server._load_routing_config()
        component_map = routing_config.get("component_map", {})
        component_match = False
        if task_component and isinstance(component_map, dict):
            matched_personas = component_map.get(task_component, [])
            component_match = persona_type in matched_personas

        component_score = 30.0 if component_match else 0.0

        # Factor 2: Historical performance (aggregated)
        perf = db.compute_agent_performance(agent_id)
        total = (perf.get("total_completed") or 0) + (perf.get("total_failed") or 0)
        if total > 0:
            success_rate = (perf.get("total_completed") or 0) / total
            history_score = success_rate * 40.0
        else:
            history_score = 20.0  # Neutral for new agents

        # Factor 3: Rolling performance score (0-100 mapped to 0-30)
        perf_factor = (perf_score / 100.0) * 30.0

        confidence = min(100.0, component_score + history_score + perf_factor)

        return {
            "status": "ok",
            "agent_id": agent_id,
            "task_id": task_id,
            "confidence": round(confidence, 1),
            "factors": {
                "component_match": component_match,
                "component_score": round(component_score, 1),
                "history_score": round(history_score, 1),
                "performance_factor": round(perf_factor, 1),
            },
            "recommendation": (
                "strong_match" if confidence >= 70
                else "moderate_match" if confidence >= 40
                else "weak_match"
            ),
        }
    except Exception as exc:
        return {"status": "error", "message": f"Self-assessment failed: {exc}"}


@_server.mcp.tool()
def auto_compose_team(sprint_id: str) -> dict[str, Any]:
    """Auto-compose a team for a sprint based on PRD component analysis (REM-014).

    Analyzes sprint PRDs to identify required components, then proposes
    a team composition by matching components to available agents via
    the routing.component_map configuration.

    Args:
        sprint_id: Sprint identifier to compose a team for.

    Returns:
        Proposed team composition with role assignments and coverage gaps.
    """
    db = _server.get_db()
    project_id = _server._get_current_project_id()
    if not project_id:
        return {
            "status": "no_project",
            "message": "No project found. Run /sdlc:init first.",
        }
    try:
        sprint = db.get_sprint(sprint_id)
        if not sprint:
            return {"status": "error", "message": f"Sprint not found: {sprint_id}"}

        # Get all tasks for this sprint to identify needed components
        tasks = db.list_tasks_by_sprint(project_id, sprint_id)
        component_counts: dict[str, int] = {}
        for task in tasks:
            comp = (task.get("component") or "general").lower()
            component_counts[comp] = component_counts.get(comp, 0) + 1

        # Load component map from config
        routing_config = _server._load_routing_config()
        component_map = routing_config.get("component_map", {})
        if not isinstance(component_map, dict):
            component_map = {}

        # Get available agents
        agents = db.list_agents(project_id, status="active")

        # Build proposed assignments
        assignments: list[dict[str, Any]] = []
        coverage_gaps: list[str] = []
        assigned_agent_ids: set[str] = set()

        for component, count in sorted(
            component_counts.items(), key=lambda x: x[1], reverse=True
        ):
            needed_personas = component_map.get(component, [])
            matched = False
            for agent in agents:
                if agent["id"] in assigned_agent_ids:
                    continue
                if agent["persona_type"] in needed_personas:
                    assignments.append({
                        "agent_id": agent["id"],
                        "display_name": agent["display_name"],
                        "persona_type": agent["persona_type"],
                        "assigned_component": component,
                        "task_count": count,
                        "performance_score": agent.get("performance_score", 50.0),
                    })
                    assigned_agent_ids.add(agent["id"])
                    matched = True
                    break
            if not matched:
                coverage_gaps.append(component)

        return {
            "status": "ok",
            "sprint_id": sprint_id,
            "components_detected": component_counts,
            "proposed_assignments": assignments,
            "coverage_gaps": coverage_gaps,
            "total_agents_proposed": len(assignments),
            "message": (
                f"Proposed {len(assignments)} agent(s) for {len(component_counts)} component(s)."
                + (f" {len(coverage_gaps)} gap(s): {coverage_gaps}" if coverage_gaps else "")
            ),
        }
    except Exception as exc:
        return {"status": "error", "message": f"Auto-compose failed: {exc}"}


@_server.mcp.tool()
def enforce_team_health(team_id: int) -> dict[str, Any]:
    """Enforce team health by evaluating metrics against configured thresholds (REM-016).

    Loads health thresholds from governance.health config (not hardcoded),
    evaluates each team member's health, and applies the configured action
    (alert, pause, or abort) for unhealthy agents.

    Args:
        team_id: Team identifier (integer primary key).

    Returns:
        Health evaluation results with actions taken per agent.
    """
    db = _server.get_db()
    project_id = _server._get_current_project_id()
    if not project_id:
        return {
            "status": "no_project",
            "message": "No project found. Run /sdlc:init first.",
        }
    try:
        # Load health thresholds from config (REM-013)
        health_config = _server._load_governance_health_config()
        quality_threshold = health_config.get("quality_threshold", 40)
        error_rate_threshold = health_config.get("error_rate_threshold_pct", 30)
        action = health_config.get("action", "alert")

        team = db.get_team_composition(team_id)
        members = team.get("members", [])

        evaluations: list[dict[str, Any]] = []
        actions_taken: list[dict[str, Any]] = []

        for member in members:
            agent_id = member["id"]
            perf_score = member.get("performance_score") or 50.0
            agent_status = member.get("status", "active")

            issues: list[str] = []

            # Check performance score
            if perf_score < quality_threshold:
                issues.append(
                    f"low_quality: score {perf_score} < threshold {quality_threshold}"
                )

            # Check error rate from performance records
            perf = db.compute_agent_performance(agent_id)
            total = (perf.get("total_completed") or 0) + (perf.get("total_failed") or 0)
            if total > 0:
                error_rate = ((perf.get("total_failed") or 0) / total) * 100
                if error_rate > error_rate_threshold:
                    issues.append(
                        f"high_error_rate: {error_rate:.1f}% > threshold {error_rate_threshold}%"
                    )

            healthy = len(issues) == 0
            evaluation = {
                "agent_id": agent_id,
                "display_name": member.get("display_name", ""),
                "status": agent_status,
                "performance_score": perf_score,
                "healthy": healthy,
                "issues": issues,
            }
            evaluations.append(evaluation)

            # Apply configured action for unhealthy agents
            if not healthy:
                action_result = {
                    "agent_id": agent_id,
                    "action": action,
                    "issues": issues,
                }
                if action == "pause" and agent_status == "active":
                    db.suspend_agent(agent_id)
                    action_result["applied"] = "suspended"
                elif action == "alert":
                    action_result["applied"] = "alert_generated"
                elif action == "abort":
                    db.suspend_agent(agent_id)
                    action_result["applied"] = "suspended_abort"
                else:
                    action_result["applied"] = "none"
                actions_taken.append(action_result)

        healthy_count = sum(1 for e in evaluations if e["healthy"])
        return {
            "status": "ok",
            "team_id": team_id,
            "team_name": team.get("name", ""),
            "health_config": health_config,
            "evaluations": evaluations,
            "actions_taken": actions_taken,
            "summary": {
                "total_members": len(members),
                "healthy": healthy_count,
                "unhealthy": len(members) - healthy_count,
            },
        }
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}
    except Exception as exc:
        return {"status": "error", "message": f"Health enforcement failed: {exc}"}
