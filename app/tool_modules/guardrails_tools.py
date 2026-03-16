"""
Guardrails Tools - Phase L0 (Leitplanken-System)

Tools for Jarvis to manage and check guardrails:
- Check before autonomous actions
- Manage guardrails (add, update, view)
- Handle overrides
- View audit log

These tools are the foundation for safe autonomy.
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def check_guardrails(
    action_type: str,
    tool_name: str = None,
    action_details: Dict = None,
    domain: str = None,
    context: Dict = None,
    session_id: str = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Check guardrails before an autonomous action.

    MUST be called before ANY autonomous action.
    Returns whether action is allowed and any blocking reasons.

    Args:
        action_type: Type of action (tool_call, decision, memory_write, etc.)
        tool_name: Name of tool being called (if applicable)
        action_details: Full details of the action
        domain: Domain context (work, personal, finance, etc.)
        context: Additional context info
        session_id: Current session ID

    Returns:
        Dict with allowed status and blocking reasons
    """
    try:
        from app.services.guardrails_service import get_guardrails_service

        service = get_guardrails_service()
        all_passed, results, audit_id = service.check_before_action(
            action_type=action_type,
            action_details=action_details or {},
            tool_name=tool_name,
            domain=domain,
            session_id=session_id,
            context=context
        )

        return {
            "success": True,
            "allowed": all_passed,
            "audit_id": audit_id,
            "checks": [r.to_dict() for r in results],
            "blocking_reasons": [
                {"guardrail": r.guardrail_name, "reason": r.reason, "action": r.action}
                for r in results if not r.passed
            ],
            "can_override": any(r.override_allowed for r in results if not r.passed)
        }

    except Exception as e:
        logger.error(f"Check guardrails failed: {e}")
        return {"success": False, "allowed": False, "error": str(e)}


def get_guardrails(
    guardrail_type: str = None,
    scope: str = None,
    active_only: bool = True,
    **kwargs
) -> Dict[str, Any]:
    """
    Get configured guardrails.

    Args:
        guardrail_type: Filter by type (hard, soft, context)
        scope: Filter by scope (tool, action_type, domain, global)
        active_only: Only return active guardrails (default: True)

    Returns:
        Dict with list of guardrails
    """
    try:
        from app.services.guardrails_service import get_guardrails_service

        service = get_guardrails_service()
        return service.get_guardrails(
            guardrail_type=guardrail_type,
            scope=scope,
            active_only=active_only
        )

    except Exception as e:
        logger.error(f"Get guardrails failed: {e}")
        return {"success": False, "error": str(e)}


def add_guardrail(
    name: str,
    guardrail_type: str,
    scope: str,
    condition: Dict,
    description: str = None,
    scope_pattern: str = None,
    action_on_violation: str = "block",
    override_allowed: bool = False,
    override_requires: str = None,
    context_conditions: Dict = None,
    priority: int = 100,
    **kwargs
) -> Dict[str, Any]:
    """
    Add a new guardrail.

    Args:
        name: Unique name for the guardrail
        guardrail_type: Type (hard, soft, context)
        scope: What it applies to (tool, action_type, domain, global)
        condition: The check condition (e.g., {"check": "requires_approval"})
        description: Human-readable description
        scope_pattern: Regex pattern for matching (e.g., "remember_*")
        action_on_violation: What to do (block, warn, log_only, ask_user)
        override_allowed: Can this be overridden? (Only for soft limits)
        override_requires: What's needed to override (user_confirmation, admin)
        context_conditions: When this applies (for context type)
        priority: Lower = higher priority (1 is highest)

    Returns:
        Dict with confirmation
    """
    try:
        from app.services.guardrails_service import get_guardrails_service

        service = get_guardrails_service()
        return service.add_guardrail(
            name=name,
            guardrail_type=guardrail_type,
            scope=scope,
            condition=condition,
            description=description,
            scope_pattern=scope_pattern,
            action_on_violation=action_on_violation,
            override_allowed=override_allowed,
            override_requires=override_requires,
            context_conditions=context_conditions,
            priority=priority
        )

    except Exception as e:
        logger.error(f"Add guardrail failed: {e}")
        return {"success": False, "error": str(e)}


def update_guardrail(
    guardrail_id: int = None,
    name: str = None,
    is_active: bool = None,
    condition: Dict = None,
    action_on_violation: str = None,
    priority: int = None,
    description: str = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Update an existing guardrail.

    Args:
        guardrail_id: ID of guardrail to update
        name: Name of guardrail (alternative to ID)
        is_active: Enable/disable the guardrail
        condition: New condition
        action_on_violation: New action
        priority: New priority
        description: New description

    Returns:
        Dict with confirmation
    """
    try:
        from app.services.guardrails_service import get_guardrails_service

        service = get_guardrails_service()

        updates = {}
        if is_active is not None:
            updates['is_active'] = is_active
        if condition is not None:
            updates['condition'] = condition
        if action_on_violation is not None:
            updates['action_on_violation'] = action_on_violation
        if priority is not None:
            updates['priority'] = priority
        if description is not None:
            updates['description'] = description

        return service.update_guardrail(
            guardrail_id=guardrail_id,
            name=name,
            **updates
        )

    except Exception as e:
        logger.error(f"Update guardrail failed: {e}")
        return {"success": False, "error": str(e)}


def request_override(
    guardrail_id: int = None,
    guardrail_name: str = None,
    reason: str = "",
    duration_hours: int = None,
    session_id: str = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Request an override for a soft guardrail.

    Cannot override hard limits.

    Args:
        guardrail_id: ID of guardrail to override
        guardrail_name: Name of guardrail (alternative to ID)
        reason: Why override is needed
        duration_hours: How long override is valid (None = permanent)
        session_id: Limit override to this session

    Returns:
        Dict with override ID
    """
    try:
        from app.services.guardrails_service import get_guardrails_service

        service = get_guardrails_service()
        return service.create_override(
            guardrail_id=guardrail_id,
            guardrail_name=guardrail_name,
            override_type="temporary" if duration_hours else "permanent",
            reason=reason,
            valid_duration_hours=duration_hours,
            session_id=session_id,
            authorized_by="jarvis"  # Will need user confirmation in practice
        )

    except Exception as e:
        logger.error(f"Request override failed: {e}")
        return {"success": False, "error": str(e)}


def revoke_override(
    override_id: int,
    **kwargs
) -> Dict[str, Any]:
    """
    Revoke an active override.

    Args:
        override_id: ID of override to revoke

    Returns:
        Dict with confirmation
    """
    try:
        from app.services.guardrails_service import get_guardrails_service

        service = get_guardrails_service()
        return service.revoke_override(override_id=override_id, revoked_by="jarvis")

    except Exception as e:
        logger.error(f"Revoke override failed: {e}")
        return {"success": False, "error": str(e)}


def get_audit_log(
    limit: int = 50,
    action_type: str = None,
    blocked_only: bool = False,
    session_id: str = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Get the autonomy audit log.

    Shows all guardrail checks and their outcomes.

    Args:
        limit: Max entries to return (default: 50)
        action_type: Filter by action type
        blocked_only: Only show blocked actions
        session_id: Filter by session

    Returns:
        Dict with audit entries
    """
    try:
        from app.services.guardrails_service import get_guardrails_service

        service = get_guardrails_service()
        return service.get_audit_log(
            limit=limit,
            action_type=action_type,
            passed_only=False if blocked_only else None,
            session_id=session_id
        )

    except Exception as e:
        logger.error(f"Get audit log failed: {e}")
        return {"success": False, "error": str(e)}


def add_guardrail_feedback(
    guardrail_id: int,
    feedback_type: str,
    feedback_details: str = None,
    suggested_change: Dict = None,
    audit_id: int = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Add feedback for a guardrail.

    Use this to suggest adjustments to soft limits.

    Args:
        guardrail_id: ID of the guardrail
        feedback_type: Type (too_strict, too_loose, correct, unclear)
        feedback_details: Details about the feedback
        suggested_change: Suggested condition changes
        audit_id: Related audit entry (if applicable)

    Returns:
        Dict with confirmation
    """
    try:
        from app.services.guardrails_service import get_guardrails_service

        service = get_guardrails_service()
        return service.add_feedback(
            guardrail_id=guardrail_id,
            feedback_type=feedback_type,
            feedback_details=feedback_details,
            suggested_change=suggested_change,
            audit_id=audit_id,
            created_by="jarvis"
        )

    except Exception as e:
        logger.error(f"Add guardrail feedback failed: {e}")
        return {"success": False, "error": str(e)}


def get_guardrails_summary(**kwargs) -> Dict[str, Any]:
    """
    Get summary of guardrails and recent activity.

    Returns:
        Dict with summary stats
    """
    try:
        from app.services.guardrails_service import get_guardrails_service

        service = get_guardrails_service()
        return service.get_guardrails_summary()

    except Exception as e:
        logger.error(f"Get guardrails summary failed: {e}")
        return {"success": False, "error": str(e)}


# ============================================
# L0.1: Risk Tier Management Tools
# ============================================

def get_tool_risk_tiers(
    tier: int = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Get tools grouped by risk tier.

    Tiers:
    - 0: Safe (read-only, always allowed)
    - 1: Standard (requires confidence >= 80%)
    - 2: Sensitive (requires user confirmation)
    - 3: Critical (requires explicit override)

    Args:
        tier: Filter by specific tier (0-3)

    Returns:
        Dict with tools grouped by tier
    """
    try:
        from app.services.guardrails_service import get_guardrails_service

        service = get_guardrails_service()
        return service.get_tool_risk_tiers(tier=tier)

    except Exception as e:
        logger.error(f"Get tool risk tiers failed: {e}")
        return {"success": False, "error": str(e)}


def set_tool_risk_tier(
    tool_name: str,
    tier: int,
    reason: str = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Set the risk tier for a tool.

    Args:
        tool_name: Name of the tool
        tier: New tier (0-3)
        reason: Why the tier is being changed

    Returns:
        Dict with confirmation
    """
    try:
        from app.services.guardrails_service import get_guardrails_service

        service = get_guardrails_service()
        return service.set_tool_risk_tier(
            tool_name=tool_name,
            tier=tier,
            reason=reason
        )

    except Exception as e:
        logger.error(f"Set tool risk tier failed: {e}")
        return {"success": False, "error": str(e)}


def get_tier_definitions(**kwargs) -> Dict[str, Any]:
    """
    Get all risk tier definitions.

    Returns:
        Dict with tier definitions including requirements
    """
    try:
        from app.services.guardrails_service import get_guardrails_service

        service = get_guardrails_service()
        return service.get_tier_definitions()

    except Exception as e:
        logger.error(f"Get tier definitions failed: {e}")
        return {"success": False, "error": str(e)}


def get_risk_tier_summary(**kwargs) -> Dict[str, Any]:
    """
    Get summary of tools by risk tier.

    Returns:
        Dict with count of tools per tier
    """
    try:
        from app.services.guardrails_service import get_guardrails_service

        service = get_guardrails_service()
        return service.get_risk_tier_summary()

    except Exception as e:
        logger.error(f"Get risk tier summary failed: {e}")
        return {"success": False, "error": str(e)}


# Tool definitions for Claude
GUARDRAILS_TOOLS = [
    {
        "name": "check_guardrails",
        "description": "Check guardrails before an autonomous action. MUST be called before any autonomous action.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action_type": {
                    "type": "string",
                    "description": "Type of action (tool_call, decision, memory_write, notify, etc.)"
                },
                "tool_name": {
                    "type": "string",
                    "description": "Name of tool being called (if applicable)"
                },
                "action_details": {
                    "type": "object",
                    "description": "Full details of the action"
                },
                "domain": {
                    "type": "string",
                    "description": "Domain context (work, personal, finance, etc.)"
                },
                "context": {
                    "type": "object",
                    "description": "Additional context (chain_depth, confidence, etc.)"
                }
            },
            "required": ["action_type"]
        }
    },
    {
        "name": "get_guardrails",
        "description": "Get configured guardrails.",
        "input_schema": {
            "type": "object",
            "properties": {
                "guardrail_type": {
                    "type": "string",
                    "enum": ["hard", "soft", "context"],
                    "description": "Filter by type"
                },
                "scope": {
                    "type": "string",
                    "enum": ["tool", "action_type", "domain", "global"],
                    "description": "Filter by scope"
                },
                "active_only": {
                    "type": "boolean",
                    "description": "Only return active guardrails (default: true)"
                }
            }
        }
    },
    {
        "name": "add_guardrail",
        "description": "Add a new guardrail (requires user confirmation).",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Unique name for the guardrail"
                },
                "guardrail_type": {
                    "type": "string",
                    "enum": ["hard", "soft", "context"],
                    "description": "Type of guardrail"
                },
                "scope": {
                    "type": "string",
                    "enum": ["tool", "action_type", "domain", "global"],
                    "description": "What it applies to"
                },
                "condition": {
                    "type": "object",
                    "description": "The check condition"
                },
                "description": {
                    "type": "string",
                    "description": "Human-readable description"
                },
                "scope_pattern": {
                    "type": "string",
                    "description": "Regex pattern for matching"
                },
                "action_on_violation": {
                    "type": "string",
                    "enum": ["block", "warn", "log_only", "ask_user"],
                    "description": "What to do on violation"
                },
                "priority": {
                    "type": "integer",
                    "description": "Priority (lower = higher priority)"
                }
            },
            "required": ["name", "guardrail_type", "scope", "condition"]
        }
    },
    {
        "name": "update_guardrail",
        "description": "Update an existing guardrail.",
        "input_schema": {
            "type": "object",
            "properties": {
                "guardrail_id": {
                    "type": "integer",
                    "description": "ID of guardrail to update"
                },
                "name": {
                    "type": "string",
                    "description": "Name of guardrail (alternative to ID)"
                },
                "is_active": {
                    "type": "boolean",
                    "description": "Enable/disable"
                },
                "condition": {
                    "type": "object",
                    "description": "New condition"
                },
                "action_on_violation": {
                    "type": "string",
                    "description": "New action"
                },
                "priority": {
                    "type": "integer",
                    "description": "New priority"
                }
            }
        }
    },
    {
        "name": "request_override",
        "description": "Request an override for a soft guardrail. Cannot override hard limits.",
        "input_schema": {
            "type": "object",
            "properties": {
                "guardrail_id": {
                    "type": "integer",
                    "description": "ID of guardrail to override"
                },
                "guardrail_name": {
                    "type": "string",
                    "description": "Name of guardrail (alternative to ID)"
                },
                "reason": {
                    "type": "string",
                    "description": "Why override is needed"
                },
                "duration_hours": {
                    "type": "integer",
                    "description": "How long override is valid"
                }
            }
        }
    },
    {
        "name": "revoke_override",
        "description": "Revoke an active override.",
        "input_schema": {
            "type": "object",
            "properties": {
                "override_id": {
                    "type": "integer",
                    "description": "ID of override to revoke"
                }
            },
            "required": ["override_id"]
        }
    },
    {
        "name": "get_audit_log",
        "description": "Get the autonomy audit log showing all guardrail checks.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Max entries (default: 50)"
                },
                "action_type": {
                    "type": "string",
                    "description": "Filter by action type"
                },
                "blocked_only": {
                    "type": "boolean",
                    "description": "Only show blocked actions"
                },
                "session_id": {
                    "type": "string",
                    "description": "Filter by session"
                }
            }
        }
    },
    {
        "name": "add_guardrail_feedback",
        "description": "Add feedback for adjusting soft limits.",
        "input_schema": {
            "type": "object",
            "properties": {
                "guardrail_id": {
                    "type": "integer",
                    "description": "ID of the guardrail"
                },
                "feedback_type": {
                    "type": "string",
                    "enum": ["too_strict", "too_loose", "correct", "unclear"],
                    "description": "Type of feedback"
                },
                "feedback_details": {
                    "type": "string",
                    "description": "Details"
                },
                "suggested_change": {
                    "type": "object",
                    "description": "Suggested condition changes"
                }
            },
            "required": ["guardrail_id", "feedback_type"]
        }
    },
    {
        "name": "get_guardrails_summary",
        "description": "Get summary of guardrails and recent activity.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    # L0.1: Risk Tier Tools
    {
        "name": "get_tool_risk_tiers",
        "description": "Get tools grouped by risk tier. Tiers: 0=safe, 1=standard (conf>80%), 2=sensitive (confirm), 3=critical (override).",
        "input_schema": {
            "type": "object",
            "properties": {
                "tier": {
                    "type": "integer",
                    "description": "Filter by specific tier (0-3)"
                }
            }
        }
    },
    {
        "name": "set_tool_risk_tier",
        "description": "Set the risk tier for a tool (requires user confirmation).",
        "input_schema": {
            "type": "object",
            "properties": {
                "tool_name": {
                    "type": "string",
                    "description": "Name of the tool"
                },
                "tier": {
                    "type": "integer",
                    "description": "New tier (0-3)"
                },
                "reason": {
                    "type": "string",
                    "description": "Why the tier is being changed"
                }
            },
            "required": ["tool_name", "tier"]
        }
    },
    {
        "name": "get_tier_definitions",
        "description": "Get all risk tier definitions including requirements.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "get_risk_tier_summary",
        "description": "Get summary of tools by risk tier with counts.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    }
]
