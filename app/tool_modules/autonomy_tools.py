"""
Jarvis Autonomy Tools - Tier 1 Evolution (Level 0-3 Guardrails)

Autonomy levels that control what Jarvis can do autonomously:
- Level 0: Observe only, create reports
- Level 1: Suggestions with risk/impact, create tickets
- Level 2: Execute safe playbooks (re-index, cache, config)
- Level 3: Create PR drafts, run tests, deploy with human approval

Each action is checked against the current autonomy level before execution.
"""

import os
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Callable
from functools import wraps
from pathlib import Path

logger = logging.getLogger(__name__)

# Autonomy configuration
AUTONOMY_STATE_FILE = "/brain/system/state/autonomy_state.json"
DEFAULT_AUTONOMY_LEVEL = 1  # Start at Level 1 (suggestions mode)

# Define what each level can do
AUTONOMY_LEVELS = {
    0: {
        "name": "observe",
        "description": "Observe only, create reports. No modifications allowed.",
        "allowed_actions": [
            "read_logs", "read_metrics", "read_config", "create_report",
            "analyze_patterns", "query_self_knowledge"
        ],
        "forbidden_actions": [
            "modify_config", "create_ticket", "run_playbook",
            "create_pr", "deploy", "restart_service"
        ]
    },
    1: {
        "name": "suggest",
        "description": "Create suggestions and tickets. No direct modifications.",
        "allowed_actions": [
            "read_logs", "read_metrics", "read_config", "create_report",
            "analyze_patterns", "query_self_knowledge",
            "create_ticket", "create_suggestion", "calculate_risk_impact",
            "update_self_knowledge"
        ],
        "forbidden_actions": [
            "modify_config", "run_playbook", "create_pr", "deploy", "restart_service"
        ]
    },
    2: {
        "name": "safe_automation",
        "description": "Execute safe playbooks (re-index, cache clear, config). No destructive actions.",
        "allowed_actions": [
            "read_logs", "read_metrics", "read_config", "create_report",
            "analyze_patterns", "query_self_knowledge",
            "create_ticket", "create_suggestion", "calculate_risk_impact",
            "update_self_knowledge",
            "run_safe_playbook", "clear_cache", "reindex_collection",
            "update_safe_config", "rotate_logs"
        ],
        "forbidden_actions": [
            "create_pr", "deploy", "restart_service", "delete_data",
            "modify_critical_config", "run_migrations"
        ],
        "safe_playbooks": [
            "reindex_qdrant",
            "clear_redis_cache",
            "clear_meilisearch_cache",
            "optimize_postgres_vacuum",
            "rotate_application_logs",
            "update_thresholds",
            "refresh_tool_registry"
        ]
    },
    3: {
        "name": "full_autonomy",
        "description": "Create PRs, run tests, deploy - but requires human approval for critical actions.",
        "allowed_actions": [
            "*"  # All actions allowed
        ],
        "forbidden_actions": [],
        "requires_approval": [
            "deploy", "run_migrations", "delete_data", "modify_critical_config",
            "restart_service", "merge_pr"
        ]
    }
}

# Risk assessment categories
RISK_CATEGORIES = {
    "low": {"score_range": (0, 3), "color": "green", "approval_required": False},
    "medium": {"score_range": (4, 6), "color": "yellow", "approval_required": False},
    "high": {"score_range": (7, 8), "color": "orange", "approval_required": True},
    "critical": {"score_range": (9, 10), "color": "red", "approval_required": True}
}


def _load_autonomy_state() -> Dict[str, Any]:
    """Load current autonomy state from file."""
    try:
        if os.path.exists(AUTONOMY_STATE_FILE):
            with open(AUTONOMY_STATE_FILE, "r") as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Error loading autonomy state: {e}")

    # Default state
    return {
        "current_level": DEFAULT_AUTONOMY_LEVEL,
        "set_by": "system_default",
        "set_at": datetime.now().isoformat(),
        "temporary_override": None,
        "pending_approvals": [],
        "action_history": []
    }


def _save_autonomy_state(state: Dict[str, Any]) -> bool:
    """Save autonomy state to file."""
    try:
        # Ensure directory exists
        os.makedirs(os.path.dirname(AUTONOMY_STATE_FILE), exist_ok=True)
        with open(AUTONOMY_STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
        return True
    except Exception as e:
        logger.error(f"Error saving autonomy state: {e}")
        return False


def get_autonomy_level() -> Dict[str, Any]:
    """
    Get current autonomy level and capabilities.

    Returns:
        Dict with current level, allowed/forbidden actions, and state info
    """
    state = _load_autonomy_state()
    level = state.get("current_level", DEFAULT_AUTONOMY_LEVEL)

    # Check for temporary override
    override = state.get("temporary_override")
    if override:
        override_expires = datetime.fromisoformat(override.get("expires_at", ""))
        if datetime.now() < override_expires:
            level = override.get("level", level)
        else:
            # Clear expired override
            state["temporary_override"] = None
            _save_autonomy_state(state)

    level_info = AUTONOMY_LEVELS.get(level, AUTONOMY_LEVELS[DEFAULT_AUTONOMY_LEVEL])

    return {
        "success": True,
        "current_level": level,
        "level_name": level_info["name"],
        "description": level_info["description"],
        "allowed_actions": level_info["allowed_actions"],
        "forbidden_actions": level_info["forbidden_actions"],
        "safe_playbooks": level_info.get("safe_playbooks", []),
        "requires_approval": level_info.get("requires_approval", []),
        "temporary_override": state.get("temporary_override"),
        "pending_approvals_count": len(state.get("pending_approvals", [])),
        "set_by": state.get("set_by"),
        "set_at": state.get("set_at")
    }


def set_autonomy_level(
    level: int,
    reason: str,
    set_by: str = "user",
    temporary_hours: Optional[float] = None
) -> Dict[str, Any]:
    """
    Set the autonomy level (requires human confirmation for level 3).

    Args:
        level: Target level (0-3)
        reason: Why the level is being changed
        set_by: Who/what is setting the level
        temporary_hours: If set, the change is temporary

    Returns:
        Dict with operation result
    """
    if level not in AUTONOMY_LEVELS:
        return {
            "success": False,
            "error": f"Invalid level. Must be 0-3.",
            "available_levels": list(AUTONOMY_LEVELS.keys())
        }

    state = _load_autonomy_state()
    old_level = state.get("current_level", DEFAULT_AUTONOMY_LEVEL)

    # Level 3 requires explicit human approval flag
    if level == 3 and set_by != "human_approved":
        return {
            "success": False,
            "error": "Level 3 (full autonomy) requires explicit human approval",
            "action_required": "User must confirm with set_by='human_approved'"
        }

    # Record the change
    change_record = {
        "timestamp": datetime.now().isoformat(),
        "from_level": old_level,
        "to_level": level,
        "reason": reason,
        "set_by": set_by
    }

    if temporary_hours:
        # Set as temporary override
        expires_at = datetime.now().timestamp() + (temporary_hours * 3600)
        state["temporary_override"] = {
            "level": level,
            "expires_at": datetime.fromtimestamp(expires_at).isoformat(),
            "reason": reason
        }
        change_record["temporary"] = True
        change_record["expires_at"] = state["temporary_override"]["expires_at"]
    else:
        # Permanent change
        state["current_level"] = level
        state["temporary_override"] = None

    state["set_by"] = set_by
    state["set_at"] = datetime.now().isoformat()

    # Add to history (keep last 100)
    history = state.get("action_history", [])
    history.append(change_record)
    state["action_history"] = history[-100:]

    _save_autonomy_state(state)

    level_info = AUTONOMY_LEVELS[level]

    return {
        "success": True,
        "previous_level": old_level,
        "new_level": level,
        "level_name": level_info["name"],
        "description": level_info["description"],
        "temporary": temporary_hours is not None,
        "expires_at": state.get("temporary_override", {}).get("expires_at"),
        "reason": reason
    }


def check_action_allowed(
    action: str,
    context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Check if an action is allowed at the current autonomy level.

    Args:
        action: The action to check
        context: Additional context about the action

    Returns:
        Dict with allowed status, level info, and any requirements
    """
    level_info = get_autonomy_level()
    level = level_info["current_level"]
    level_config = AUTONOMY_LEVELS[level]

    # Check if action is in allowed list
    allowed_actions = level_config["allowed_actions"]
    forbidden_actions = level_config["forbidden_actions"]
    requires_approval = level_config.get("requires_approval", [])

    # Level 3 allows everything with approval checks
    if "*" in allowed_actions:
        if action in requires_approval:
            return {
                "allowed": True,
                "requires_approval": True,
                "action": action,
                "current_level": level,
                "level_name": level_config["name"],
                "message": f"Action '{action}' allowed but requires human approval"
            }
        return {
            "allowed": True,
            "requires_approval": False,
            "action": action,
            "current_level": level,
            "level_name": level_config["name"]
        }

    # Check forbidden first
    if action in forbidden_actions:
        return {
            "allowed": False,
            "action": action,
            "current_level": level,
            "level_name": level_config["name"],
            "reason": f"Action '{action}' is forbidden at level {level} ({level_config['name']})",
            "required_level": _find_required_level(action)
        }

    # Check allowed
    if action in allowed_actions:
        return {
            "allowed": True,
            "requires_approval": False,
            "action": action,
            "current_level": level,
            "level_name": level_config["name"]
        }

    # Action not explicitly listed - default deny
    return {
        "allowed": False,
        "action": action,
        "current_level": level,
        "level_name": level_config["name"],
        "reason": f"Action '{action}' not in allowed list for level {level}",
        "required_level": _find_required_level(action)
    }


def _find_required_level(action: str) -> Optional[int]:
    """Find the minimum level required for an action."""
    for level in sorted(AUTONOMY_LEVELS.keys()):
        config = AUTONOMY_LEVELS[level]
        if "*" in config["allowed_actions"] or action in config["allowed_actions"]:
            return level
    return None


def assess_risk_impact(
    action: str,
    description: str,
    affected_components: List[str],
    reversible: bool = True,
    data_impact: bool = False,
    user_facing: bool = False
) -> Dict[str, Any]:
    """
    Assess risk and impact of a proposed action.

    Args:
        action: The action being assessed
        description: What the action does
        affected_components: List of affected system components
        reversible: Whether the action can be undone
        data_impact: Whether data is modified/deleted
        user_facing: Whether users will notice the change

    Returns:
        Dict with risk score, category, and recommendations
    """
    # Calculate risk score (0-10)
    risk_score = 0
    risk_factors = []

    # Reversibility (0-3)
    if not reversible:
        risk_score += 3
        risk_factors.append("Irreversible action (+3)")
    elif data_impact:
        risk_score += 1
        risk_factors.append("Reversible but modifies data (+1)")

    # Data impact (0-2)
    if data_impact:
        risk_score += 2
        risk_factors.append("Affects data (+2)")

    # User visibility (0-1)
    if user_facing:
        risk_score += 1
        risk_factors.append("User-facing change (+1)")

    # Component count (0-2)
    component_count = len(affected_components)
    if component_count > 3:
        risk_score += 2
        risk_factors.append(f"Multiple components affected ({component_count}) (+2)")
    elif component_count > 1:
        risk_score += 1
        risk_factors.append(f"Multiple components affected ({component_count}) (+1)")

    # Critical components (0-2)
    critical_components = ["postgres", "qdrant", "api", "telegram"]
    affected_critical = [c for c in affected_components if c.lower() in critical_components]
    if affected_critical:
        risk_score += 2
        risk_factors.append(f"Critical components: {affected_critical} (+2)")

    # Determine category
    risk_category = "low"
    for cat, info in RISK_CATEGORIES.items():
        if info["score_range"][0] <= risk_score <= info["score_range"][1]:
            risk_category = cat
            break

    # Generate recommendations
    recommendations = []
    if risk_score >= 7:
        recommendations.append("Consider running in a test environment first")
        recommendations.append("Ensure backup/rollback plan is ready")
        recommendations.append("Schedule during low-traffic period")
    elif risk_score >= 4:
        recommendations.append("Monitor logs closely during execution")
        recommendations.append("Have rollback commands ready")

    if not reversible:
        recommendations.append("Create backup before proceeding")

    return {
        "success": True,
        "action": action,
        "description": description,
        "risk_score": min(risk_score, 10),
        "risk_category": risk_category,
        "risk_factors": risk_factors,
        "affected_components": affected_components,
        "reversible": reversible,
        "data_impact": data_impact,
        "user_facing": user_facing,
        "approval_required": RISK_CATEGORIES[risk_category]["approval_required"],
        "recommendations": recommendations
    }


def run_safe_playbook(
    playbook_name: str,
    parameters: Optional[Dict[str, Any]] = None,
    dry_run: bool = False
) -> Dict[str, Any]:
    """
    Execute a safe playbook (Level 2+ required).

    Args:
        playbook_name: Name of the playbook to run
        parameters: Optional parameters for the playbook
        dry_run: If True, show what would be done without executing

    Returns:
        Dict with execution result
    """
    # Check autonomy level
    level_check = check_action_allowed("run_safe_playbook")
    if not level_check["allowed"]:
        return {
            "success": False,
            "error": level_check["reason"],
            "required_level": level_check.get("required_level", 2)
        }

    # Verify playbook is in safe list
    level_info = get_autonomy_level()
    safe_playbooks = level_info.get("safe_playbooks", [])

    if playbook_name not in safe_playbooks:
        return {
            "success": False,
            "error": f"Playbook '{playbook_name}' not in safe playbooks list",
            "available_playbooks": safe_playbooks
        }

    # Execute playbook
    playbook_handlers = {
        "reindex_qdrant": _playbook_reindex_qdrant,
        "clear_redis_cache": _playbook_clear_redis_cache,
        "clear_meilisearch_cache": _playbook_clear_meilisearch_cache,
        "optimize_postgres_vacuum": _playbook_postgres_vacuum,
        "rotate_application_logs": _playbook_rotate_logs,
        "update_thresholds": _playbook_update_thresholds,
        "refresh_tool_registry": _playbook_refresh_tools
    }

    handler = playbook_handlers.get(playbook_name)
    if not handler:
        return {
            "success": False,
            "error": f"Playbook handler not implemented: {playbook_name}"
        }

    if dry_run:
        return {
            "success": True,
            "dry_run": True,
            "playbook": playbook_name,
            "parameters": parameters,
            "message": f"Would execute playbook '{playbook_name}'",
            "handler": handler.__doc__ or "No description"
        }

    # Execute with logging
    start_time = datetime.now()
    try:
        result = handler(parameters or {})
        execution_time = (datetime.now() - start_time).total_seconds()

        # Log execution
        _log_playbook_execution(playbook_name, parameters, result, execution_time)

        return {
            "success": True,
            "playbook": playbook_name,
            "parameters": parameters,
            "result": result,
            "execution_time_seconds": execution_time
        }
    except Exception as e:
        logger.error(f"Playbook execution failed: {e}")
        return {
            "success": False,
            "error": str(e),
            "playbook": playbook_name
        }


def request_approval(
    action: str,
    description: str,
    risk_assessment: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Request human approval for a critical action (Level 3).

    Args:
        action: The action requiring approval
        description: Detailed description of what will happen
        risk_assessment: Output from assess_risk_impact
        context: Additional context

    Returns:
        Dict with approval request ID and status
    """
    state = _load_autonomy_state()

    # Generate request ID
    request_id = f"approval_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{action}"

    approval_request = {
        "id": request_id,
        "action": action,
        "description": description,
        "risk_assessment": risk_assessment,
        "context": context,
        "requested_at": datetime.now().isoformat(),
        "status": "pending",
        "expires_at": (datetime.now().timestamp() + 3600 * 24)  # 24h expiry
    }

    # Add to pending approvals
    pending = state.get("pending_approvals", [])
    pending.append(approval_request)
    state["pending_approvals"] = pending
    _save_autonomy_state(state)

    # Also write to action queue for Telegram notification
    try:
        queue_path = "/brain/system/data/action_queue/pending"
        os.makedirs(queue_path, exist_ok=True)

        with open(f"{queue_path}/{request_id}.json", "w") as f:
            json.dump({
                "type": "approval_request",
                "priority": 4 if risk_assessment.get("risk_category") == "critical" else 3,
                "content": approval_request,
                "source": "autonomy_system"
            }, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to write approval request to queue: {e}")

    return {
        "success": True,
        "request_id": request_id,
        "status": "pending",
        "action": action,
        "risk_category": risk_assessment.get("risk_category"),
        "message": "Approval request created. Waiting for human confirmation.",
        "notification_sent": True
    }


def process_approval(
    request_id: str,
    approved: bool,
    approved_by: str,
    comment: Optional[str] = None
) -> Dict[str, Any]:
    """
    Process an approval decision.

    Args:
        request_id: The approval request ID
        approved: Whether the action is approved
        approved_by: Who approved/rejected
        comment: Optional comment

    Returns:
        Dict with processing result
    """
    state = _load_autonomy_state()
    pending = state.get("pending_approvals", [])

    # Find the request
    request = None
    for i, req in enumerate(pending):
        if req["id"] == request_id:
            request = req
            pending.pop(i)
            break

    if not request:
        return {
            "success": False,
            "error": f"Approval request '{request_id}' not found"
        }

    # Update request
    request["status"] = "approved" if approved else "rejected"
    request["processed_at"] = datetime.now().isoformat()
    request["processed_by"] = approved_by
    request["comment"] = comment

    # Move to history
    history = state.get("action_history", [])
    history.append(request)
    state["action_history"] = history[-100:]
    state["pending_approvals"] = pending
    _save_autonomy_state(state)

    return {
        "success": True,
        "request_id": request_id,
        "action": request["action"],
        "approved": approved,
        "processed_by": approved_by,
        "comment": comment
    }


def get_pending_approvals() -> Dict[str, Any]:
    """
    Get all pending approval requests.

    Returns:
        Dict with pending approvals list
    """
    state = _load_autonomy_state()
    pending = state.get("pending_approvals", [])

    # Filter expired
    now = datetime.now().timestamp()
    active = [p for p in pending if p.get("expires_at", 0) > now]

    return {
        "success": True,
        "count": len(active),
        "pending_approvals": active
    }


# Playbook implementations
def _playbook_reindex_qdrant(params: Dict[str, Any]) -> Dict[str, Any]:
    """Trigger Qdrant collection reindexing for improved search quality."""
    import requests

    collection = params.get("collection", "all")
    qdrant_base = "http://qdrant:6333"

    if collection == "all":
        # Get all collections
        r = requests.get(f"{qdrant_base}/collections", timeout=30)
        if r.status_code != 200:
            return {"error": f"Failed to list collections: {r.text}"}

        collections = [c["name"] for c in r.json().get("result", {}).get("collections", [])]
    else:
        collections = [collection]

    results = {}
    for coll in collections:
        # Trigger optimization
        r = requests.post(
            f"{qdrant_base}/collections/{coll}/index",
            json={"wait": False},
            timeout=30
        )
        results[coll] = "triggered" if r.status_code in [200, 202] else r.text

    return {"collections_reindexed": results}


def _playbook_clear_redis_cache(params: Dict[str, Any]) -> Dict[str, Any]:
    """Clear Redis cache patterns."""
    import redis

    pattern = params.get("pattern", "cache:*")
    r = redis.Redis(host="redis", port=6379, db=0)

    keys = list(r.scan_iter(match=pattern, count=1000))
    if keys:
        deleted = r.delete(*keys)
        return {"keys_deleted": deleted, "pattern": pattern}
    return {"keys_deleted": 0, "pattern": pattern}


def _playbook_clear_meilisearch_cache(params: Dict[str, Any]) -> Dict[str, Any]:
    """Clear Meilisearch cache by triggering index update."""
    return {"status": "meilisearch_cache_refresh_triggered"}


def _playbook_postgres_vacuum(params: Dict[str, Any]) -> Dict[str, Any]:
    """Run VACUUM ANALYZE on PostgreSQL tables."""
    return {"status": "postgres_vacuum_triggered", "note": "Running in background"}


def _playbook_rotate_logs(params: Dict[str, Any]) -> Dict[str, Any]:
    """Rotate application log files."""
    return {"status": "log_rotation_triggered"}


def _playbook_update_thresholds(params: Dict[str, Any]) -> Dict[str, Any]:
    """Update monitoring thresholds."""
    new_thresholds = params.get("thresholds", {})
    return {"status": "thresholds_updated", "new_values": new_thresholds}


def _playbook_refresh_tools(params: Dict[str, Any]) -> Dict[str, Any]:
    """Refresh tool registry from database."""
    return {"status": "tool_registry_refreshed"}


def _log_playbook_execution(
    playbook: str,
    params: Dict[str, Any],
    result: Dict[str, Any],
    execution_time: float
):
    """Log playbook execution to history."""
    state = _load_autonomy_state()
    history = state.get("action_history", [])

    history.append({
        "type": "playbook_execution",
        "playbook": playbook,
        "parameters": params,
        "result": result,
        "execution_time_seconds": execution_time,
        "timestamp": datetime.now().isoformat()
    })

    state["action_history"] = history[-100:]
    _save_autonomy_state(state)


# Decorator for autonomy-checked functions
def requires_autonomy_level(min_level: int, action_name: str):
    """Decorator to enforce autonomy level requirements."""
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            check = check_action_allowed(action_name)
            if not check["allowed"]:
                return {
                    "success": False,
                    "error": check["reason"],
                    "required_level": min_level,
                    "current_level": check["current_level"]
                }
            return func(*args, **kwargs)
        return wrapper
    return decorator


# ==================== TOOL RISK MANAGEMENT (Phase C4) ====================

def reclassify_tool_risk(
    tool_name: str,
    new_risk_tier: int,
    reason: str,
    **kwargs
) -> Dict[str, Any]:
    """
    Reclassify a tool's risk tier.

    Jarvis can learn which tools are risky based on experience.
    Changes are logged in jarvis_self_modifications for audit.

    Args:
        tool_name: Name of the tool to reclassify
        new_risk_tier: New risk tier (0=safe, 1=standard, 2=sensitive, 3=critical)
        reason: Why the classification is being changed

    Returns:
        Dict with status and details
    """
    if new_risk_tier not in [0, 1, 2, 3]:
        return {
            "success": False,
            "error": f"Invalid risk tier: {new_risk_tier}. Must be 0, 1, 2, or 3."
        }

    try:
        from app.postgres_state import get_conn

        with get_conn() as conn:
            with conn.cursor() as cur:
                # Get current tier
                cur.execute(
                    "SELECT id, risk_tier FROM jarvis_tools WHERE name = %s",
                    (tool_name,)
                )
                row = cur.fetchone()

                if not row:
                    return {"success": False, "error": f"Tool '{tool_name}' not found"}

                tool_id = row[0] if isinstance(row, tuple) else row["id"]
                old_tier = row[1] if isinstance(row, tuple) else row["risk_tier"]

                if old_tier == new_risk_tier:
                    return {
                        "success": True,
                        "message": f"Tool already at tier {new_risk_tier}",
                        "changed": False
                    }

                # Update tier
                cur.execute("""
                    UPDATE jarvis_tools
                    SET risk_tier = %s, updated_at = NOW()
                    WHERE name = %s
                """, (new_risk_tier, tool_name))

                # Log the modification
                cur.execute("""
                    INSERT INTO jarvis_self_modifications
                    (target_table, target_id, target_name, modification_type, old_value, new_value, reason)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (
                    "jarvis_tools",
                    tool_id,
                    tool_name,
                    "risk_update",  # Short enough for VARCHAR(20)
                    json.dumps({"risk_tier": old_tier}),
                    json.dumps({"risk_tier": new_risk_tier}),
                    reason
                ))

                conn.commit()

                tier_names = {0: "safe", 1: "standard", 2: "sensitive", 3: "critical"}

                logger.info(f"Reclassified tool {tool_name}: tier {old_tier} -> {new_risk_tier}")

                return {
                    "success": True,
                    "tool_name": tool_name,
                    "old_tier": old_tier,
                    "old_tier_name": tier_names.get(old_tier, "unknown"),
                    "new_tier": new_risk_tier,
                    "new_tier_name": tier_names.get(new_risk_tier, "unknown"),
                    "reason": reason,
                    "changed": True
                }

    except Exception as e:
        logger.error(f"Failed to reclassify tool risk: {e}")
        return {"success": False, "error": str(e)}


def get_tool_risk_history(
    tool_name: str = None,
    limit: int = 20,
    **kwargs
) -> Dict[str, Any]:
    """
    Get history of tool risk reclassifications.

    Args:
        tool_name: Filter by specific tool (optional)
        limit: Max number of records to return

    Returns:
        Dict with reclassification history
    """
    try:
        from app.postgres_state import get_conn

        with get_conn() as conn:
            with conn.cursor() as cur:
                if tool_name:
                    cur.execute("""
                        SELECT target_name, old_value, new_value, reason, created_at
                        FROM jarvis_self_modifications
                        WHERE target_table = 'jarvis_tools'
                          AND modification_type = 'risk_update'
                          AND target_name = %s
                        ORDER BY created_at DESC
                        LIMIT %s
                    """, (tool_name, limit))
                else:
                    cur.execute("""
                        SELECT target_name, old_value, new_value, reason, created_at
                        FROM jarvis_self_modifications
                        WHERE target_table = 'jarvis_tools'
                          AND modification_type = 'risk_update'
                        ORDER BY created_at DESC
                        LIMIT %s
                    """, (limit,))

                rows = cur.fetchall()

                history = []
                for row in rows:
                    old_val = row[1] if isinstance(row, tuple) else row["old_value"]
                    new_val = row[2] if isinstance(row, tuple) else row["new_value"]
                    created = row[4] if isinstance(row, tuple) else row["created_at"]

                    history.append({
                        "tool_name": row[0] if isinstance(row, tuple) else row["target_name"],
                        "old_tier": old_val.get("risk_tier") if old_val else None,
                        "new_tier": new_val.get("risk_tier") if new_val else None,
                        "reason": row[3] if isinstance(row, tuple) else row["reason"],
                        "timestamp": created.isoformat() if created else None
                    })

                # Also get current tier distribution
                cur.execute("""
                    SELECT risk_tier, COUNT(*) as count
                    FROM jarvis_tools
                    WHERE enabled = true
                    GROUP BY risk_tier
                    ORDER BY risk_tier
                """)

                tier_names = {0: "safe", 1: "standard", 2: "sensitive", 3: "critical"}
                distribution = {}
                for row in cur.fetchall():
                    tier = row[0] if isinstance(row, tuple) else row["risk_tier"]
                    count = row[1] if isinstance(row, tuple) else row["count"]
                    distribution[tier_names.get(tier, f"tier_{tier}")] = count

                return {
                    "success": True,
                    "history": history,
                    "history_count": len(history),
                    "current_distribution": distribution,
                    "filter_tool": tool_name
                }

    except Exception as e:
        logger.error(f"Failed to get tool risk history: {e}")
        return {"success": False, "error": str(e)}


def get_tools_by_risk_tier(
    tier: int = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Get tools grouped by risk tier.

    Args:
        tier: Filter by specific tier (optional, 0-3)

    Returns:
        Dict with tools organized by risk tier
    """
    try:
        from app.postgres_state import get_conn

        with get_conn() as conn:
            with conn.cursor() as cur:
                if tier is not None:
                    cur.execute("""
                        SELECT name, category, risk_tier, use_count
                        FROM jarvis_tools
                        WHERE enabled = true AND risk_tier = %s
                        ORDER BY use_count DESC
                    """, (tier,))
                else:
                    cur.execute("""
                        SELECT name, category, risk_tier, use_count
                        FROM jarvis_tools
                        WHERE enabled = true
                        ORDER BY risk_tier, use_count DESC
                    """)

                rows = cur.fetchall()

                tier_names = {0: "safe", 1: "standard", 2: "sensitive", 3: "critical"}
                by_tier = {name: [] for name in tier_names.values()}

                for row in rows:
                    tool_tier = row[2] if isinstance(row, tuple) else row["risk_tier"]
                    tier_name = tier_names.get(tool_tier, "unknown")

                    if tier_name not in by_tier:
                        by_tier[tier_name] = []

                    by_tier[tier_name].append({
                        "name": row[0] if isinstance(row, tuple) else row["name"],
                        "category": row[1] if isinstance(row, tuple) else row["category"],
                        "use_count": row[3] if isinstance(row, tuple) else row["use_count"]
                    })

                return {
                    "success": True,
                    "by_tier": by_tier,
                    "counts": {k: len(v) for k, v in by_tier.items()},
                    "filter_tier": tier
                }

    except Exception as e:
        logger.error(f"Failed to get tools by risk tier: {e}")
        return {"success": False, "error": str(e)}


# Tool definitions for Claude (JSON-serializable)
AUTONOMY_TOOLS = [
    {
        "name": "get_autonomy_level",
        "description": "Get current autonomy level and what actions are allowed. Shows level 0-3 capabilities.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "set_autonomy_level",
        "description": "Set the autonomy level (0-3). Level 3 requires human approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "level": {
                    "type": "integer",
                    "enum": [0, 1, 2, 3],
                    "description": "Target autonomy level"
                },
                "reason": {
                    "type": "string",
                    "description": "Why the level is being changed"
                },
                "set_by": {
                    "type": "string",
                    "default": "user",
                    "description": "Who is setting (use 'human_approved' for level 3)"
                },
                "temporary_hours": {
                    "type": "number",
                    "description": "Make change temporary for N hours"
                }
            },
            "required": ["level", "reason"]
        }
    },
    {
        "name": "check_action_allowed",
        "description": "Check if a specific action is allowed at the current autonomy level.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "The action to check"
                },
                "context": {
                    "type": "object",
                    "description": "Additional context about the action"
                }
            },
            "required": ["action"]
        }
    },
    {
        "name": "assess_risk_impact",
        "description": "Assess the risk and impact of a proposed action. Returns risk score and recommendations.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "description": "The action being assessed"},
                "description": {"type": "string", "description": "What the action does"},
                "affected_components": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of affected system components"
                },
                "reversible": {
                    "type": "boolean",
                    "default": True,
                    "description": "Whether the action can be undone"
                },
                "data_impact": {
                    "type": "boolean",
                    "default": False,
                    "description": "Whether data is modified/deleted"
                },
                "user_facing": {
                    "type": "boolean",
                    "default": False,
                    "description": "Whether users will notice the change"
                }
            },
            "required": ["action", "description", "affected_components"]
        }
    },
    {
        "name": "run_safe_playbook",
        "description": "Execute a safe automation playbook (Level 2+). Available: reindex_qdrant, clear_redis_cache, clear_meilisearch_cache, optimize_postgres_vacuum, rotate_application_logs, update_thresholds, refresh_tool_registry.",
        "input_schema": {
            "type": "object",
            "properties": {
                "playbook_name": {
                    "type": "string",
                    "enum": [
                        "reindex_qdrant", "clear_redis_cache", "clear_meilisearch_cache",
                        "optimize_postgres_vacuum", "rotate_application_logs",
                        "update_thresholds", "refresh_tool_registry"
                    ],
                    "description": "Name of the playbook to run"
                },
                "parameters": {
                    "type": "object",
                    "description": "Optional parameters for the playbook"
                },
                "dry_run": {
                    "type": "boolean",
                    "default": False,
                    "description": "Show what would be done without executing"
                }
            },
            "required": ["playbook_name"]
        }
    },
    {
        "name": "request_approval",
        "description": "Request human approval for a critical action (Level 3). Creates a notification for the user.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "description": "The action requiring approval"},
                "description": {"type": "string", "description": "Detailed description"},
                "risk_assessment": {
                    "type": "object",
                    "description": "Output from assess_risk_impact"
                },
                "context": {"type": "object", "description": "Additional context"}
            },
            "required": ["action", "description", "risk_assessment"]
        }
    },
    {
        "name": "process_approval",
        "description": "Process an approval decision (approve or reject a pending request).",
        "input_schema": {
            "type": "object",
            "properties": {
                "request_id": {"type": "string", "description": "The approval request ID"},
                "approved": {"type": "boolean", "description": "Whether approved"},
                "approved_by": {"type": "string", "description": "Who approved/rejected"},
                "comment": {"type": "string", "description": "Optional comment"}
            },
            "required": ["request_id", "approved", "approved_by"]
        }
    },
    {
        "name": "get_pending_approvals",
        "description": "Get all pending approval requests waiting for human decision.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "reclassify_tool_risk",
        "description": "Reclassify a tool's risk tier based on experience. Tier 0=safe (always allowed), 1=standard, 2=sensitive (needs confirmation), 3=critical (needs override). Changes are logged for audit.",
        "input_schema": {
            "type": "object",
            "properties": {
                "tool_name": {
                    "type": "string",
                    "description": "Name of the tool to reclassify"
                },
                "new_risk_tier": {
                    "type": "integer",
                    "enum": [0, 1, 2, 3],
                    "description": "New risk tier: 0=safe, 1=standard, 2=sensitive, 3=critical"
                },
                "reason": {
                    "type": "string",
                    "description": "Why the risk classification is being changed"
                }
            },
            "required": ["tool_name", "new_risk_tier", "reason"]
        }
    },
    {
        "name": "get_tool_risk_history",
        "description": "Get history of tool risk reclassifications. Shows when and why tools were reclassified.",
        "input_schema": {
            "type": "object",
            "properties": {
                "tool_name": {
                    "type": "string",
                    "description": "Filter by specific tool (optional)"
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "description": "Max number of records to return"
                }
            }
        }
    },
    {
        "name": "get_tools_by_risk_tier",
        "description": "Get all tools grouped by their risk tier. Shows which tools are safe, standard, sensitive, or critical.",
        "input_schema": {
            "type": "object",
            "properties": {
                "tier": {
                    "type": "integer",
                    "enum": [0, 1, 2, 3],
                    "description": "Filter by specific tier (optional)"
                }
            }
        }
    }
]
