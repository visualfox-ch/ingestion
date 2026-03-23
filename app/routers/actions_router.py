"""
Actions Router

Extracted from main.py - Action Approval System endpoints:
- Request action approval
- Get pending actions
- Get action status
- Approve/reject actions
- Check expired actions
- Check action permissions
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional

from ..observability import get_logger
from ..auth import auth_dependency

logger = get_logger("jarvis.actions")
# Action approval endpoints require authentication
router = APIRouter(
    prefix="/actions",
    tags=["actions"],
    dependencies=[Depends(auth_dependency)]
)


# =============================================================================
# PYDANTIC MODELS
# =============================================================================

class ActionRequest(BaseModel):
    action: str  # Action identifier (e.g., "file.read", "git.commit")
    description: str  # Human-readable description
    target: str | None = None  # Target file/resource path
    context: dict | None = None  # Additional context
    urgent: bool = False  # Mark as urgent for shorter timeout


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.post("/request")
def request_action(req: ActionRequest):
    """
    Request approval for an action through the Intent-Approval-Execution system.

    This is the main entry point for Jarvis to request permission to perform actions.
    Based on the action's tier, it will either:
    - Execute immediately (Tier 1: Autonomous)
    - Execute and notify (Tier 2: Notify)
    - Queue for approval (Tier 3a/3b: Approve)
    - Block the request (Tier 4: Forbidden)

    Returns:
        Action request with status indicating if approval is needed
    """
    from ..telegram_bot import request_action_approval

    result = request_action_approval(
        action_name=req.action,
        description=req.description,
        target=req.target,
        context=req.context,
        urgent=req.urgent
    )

    return result


@router.get("/pending")
def get_pending_actions():
    """
    Get all pending action requests waiting for approval.

    Returns:
        List of pending actions with their details
    """
    from .. import action_queue

    pending = action_queue.get_pending_actions()
    return {
        "count": len(pending),
        "actions": pending
    }


@router.get("/{action_id}")
def get_action_status(action_id: str):
    """
    Get the status of a specific action request.

    Returns:
        Action details including current status
    """
    from .. import action_queue

    action = action_queue.get_action(action_id)
    if not action:
        raise HTTPException(status_code=404, detail="Action not found")

    return action


@router.post("/{action_id}/approve")
def approve_action_endpoint(action_id: str):
    """
    Approve a pending action request.

    This endpoint is typically called by the user via Telegram buttons,
    but can also be called directly via API.

    Returns:
        Updated action with approved status
    """
    from .. import action_queue

    result = action_queue.approve_action(action_id, approved_by="api")
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    return result


@router.post("/{action_id}/reject")
def reject_action_endpoint(action_id: str, reason: str = None):
    """
    Reject a pending action request.

    Args:
        reason: Optional reason for rejection

    Returns:
        Updated action with rejected status
    """
    from .. import action_queue

    result = action_queue.reject_action(action_id, rejected_by="api", reason=reason)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    return result


@router.post("/check-expired")
def check_expired_actions():
    """
    Check for and process expired action requests.

    This endpoint can be called periodically (e.g., via n8n cron)
    to clean up expired pending actions.

    Returns:
        List of actions that were marked as expired
    """
    from .. import action_queue

    expired = action_queue.check_expired_actions()
    return {
        "expired_count": len(expired),
        "actions": expired
    }


@router.get("/permissions/{action_name}")
def check_action_permission(action_name: str, user_id: Optional[str] = None):
    """
    Check the permission tier for a specific action type.

    This is useful for Jarvis to know beforehand if an action
    will require approval.

    Returns:
        Permission tier and requirements for the action
    """
    from .. import action_queue

    tier = action_queue.get_action_tier(action_name, user_id=user_id)
    permissions = action_queue.load_permissions()
    tier_config = permissions.get("tiers", {}).get(tier.value, {})

    return {
        "action": action_name,
        "tier": tier.value,
        "tier_config": tier_config,
        "is_allowed": tier != action_queue.ActionTier.FORBIDDEN,
        "requires_approval": tier in [
            action_queue.ActionTier.APPROVE_STANDARD,
            action_queue.ActionTier.APPROVE_CRITICAL
        ]
    }
