"""
Jarvis Action Queue System
Intent-Approval-Execution architecture for controlled autonomy.

This module handles:
- Permission checking for actions
- Action request creation and storage
- Approval/rejection processing
- Timeout and expiration handling
"""

import os
import json
import uuid
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List, Literal
from enum import Enum

import yaml

from .observability import log_with_context
from .db_safety import safe_list_query
from .metrics import (
    AUTONOMOUS_ACTIONS_TOTAL,
    AUTONOMOUS_APPROVAL_DECISIONS,
    AUTONOMOUS_ERRORS_TOTAL,
    AUTONOMOUS_APPROVAL_LATENCY_SECONDS,
)

logger = logging.getLogger(__name__)

# =============================================================================
# CONFIGURATION
# =============================================================================

# Paths
ACTION_QUEUE_BASE = os.environ.get(
    "ACTION_QUEUE_PATH",
    "/brain/system/data/action_queue"
)
PERMISSIONS_FILE = os.environ.get(
    "PERMISSIONS_FILE",
    "/brain/system/policies/jarvis_permissions.yaml"
)

# Queue subdirectories
QUEUE_DIRS = ["pending", "approved", "completed", "rejected", "expired"]


class ActionTier(Enum):
    """Action permission tiers."""
    AUTONOMOUS = "autonomous"
    NOTIFY = "notify"
    APPROVE_STANDARD = "approve_standard"
    APPROVE_CRITICAL = "approve_critical"
    FORBIDDEN = "forbidden"


class ActionStatus(Enum):
    """Action request status."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    COMPLETED = "completed"
    EXPIRED = "expired"
    FAILED = "failed"


# =============================================================================
# PERMISSIONS LOADING
# =============================================================================

_permissions_cache: Optional[Dict] = None
_permissions_mtime: float = 0


def load_permissions(force_reload: bool = False) -> Dict:
    """Load permissions from YAML file with caching."""
    global _permissions_cache, _permissions_mtime

    if not os.path.exists(PERMISSIONS_FILE):
        log_with_context(logger, "warning", "Permissions file not found",
                        path=PERMISSIONS_FILE)
        return _get_default_permissions()

    current_mtime = os.path.getmtime(PERMISSIONS_FILE)

    if not force_reload and _permissions_cache and current_mtime == _permissions_mtime:
        return _permissions_cache

    try:
        with open(PERMISSIONS_FILE, 'r') as f:
            _permissions_cache = yaml.safe_load(f)
            _permissions_mtime = current_mtime
            log_with_context(logger, "info", "Permissions loaded",
                            path=PERMISSIONS_FILE)
            return _permissions_cache
    except Exception as e:
        log_with_context(logger, "error", "Failed to load permissions",
                        error=str(e))
        return _get_default_permissions()


def _get_default_permissions() -> Dict:
    """Return restrictive default permissions."""
    return {
        "tiers": {
            "autonomous": {"requires_approval": False, "notify_user": False},
            "notify": {"requires_approval": False, "notify_user": True},
            "approve_standard": {"requires_approval": True, "timeout_hours": 4},
            "approve_critical": {"requires_approval": True, "timeout_hours": 24},
            "forbidden": {"blocked": True},
        },
        "actions": {
            "autonomous": [],
            "notify": [],
            "approve_standard": [],
            "approve_critical": [],
            "forbidden": [{"action": "*", "reason": "Default deny"}],
        },
        "sandbox": {
            "allowed_paths": [],
            "forbidden_paths": [{"path": "/", "reason": "Default deny"}],
        },
    }


# =============================================================================
# PERMISSION CHECKING
# =============================================================================

def _get_autonomy_level(user_id: Optional[str]) -> Optional[str]:
    if not user_id:
        return None

    try:
        with safe_list_query('user_learned_preferences') as cur:
            cur.execute(
                """
                SELECT preference_value
                FROM user_learned_preferences
                WHERE user_id = %s
                  AND preference_key = %s
                  AND is_active = true
                ORDER BY updated_at DESC NULLS LAST
                LIMIT 1
                """,
                (user_id, "autonomy.level"),
            )
            row = cur.fetchone()
        if row and row.get("preference_value"):
            return str(row.get("preference_value")).strip().lower()
    except Exception as exc:
        log_with_context(logger, "warning", "Failed to load autonomy level", error=str(exc))

    return None


def _apply_autonomy_level_to_tier(tier: ActionTier, autonomy_level: Optional[str]) -> ActionTier:
    if autonomy_level not in {"low", "medium", "high"}:
        return tier

    # Conservative defaults: lower autonomy increases required oversight.
    if autonomy_level == "low":
        if tier == ActionTier.AUTONOMOUS:
            return ActionTier.NOTIFY
        if tier == ActionTier.NOTIFY:
            return ActionTier.APPROVE_STANDARD

    return tier


def get_action_tier(action_name: str, user_id: Optional[str] = None) -> ActionTier:
    """
    Determine the tier for a given action.
    Returns FORBIDDEN for unknown actions (fail-safe default).
    """
    permissions = load_permissions()
    actions = permissions.get("actions", {})

    for tier_name in ["autonomous", "notify", "approve_standard", "approve_critical"]:
        tier_actions = actions.get(tier_name, [])
        for action_def in tier_actions:
            if action_def.get("action") == action_name:
                base_tier = ActionTier(tier_name)
                autonomy_level = _get_autonomy_level(user_id)
                return _apply_autonomy_level_to_tier(base_tier, autonomy_level)

    # Check if explicitly forbidden
    forbidden_actions = actions.get("forbidden", [])
    for action_def in forbidden_actions:
        if action_def.get("action") == action_name or action_def.get("action") == "*":
            return ActionTier.FORBIDDEN

    # Default: forbidden (fail-safe)
    log_with_context(logger, "warning", "Unknown action, defaulting to FORBIDDEN",
                    action=action_name)
    base_tier = ActionTier.FORBIDDEN

    autonomy_level = _get_autonomy_level(user_id)
    adjusted = _apply_autonomy_level_to_tier(base_tier, autonomy_level)
    return adjusted


def is_action_allowed(action_name: str, user_id: Optional[str] = None) -> bool:
    """Check if an action is allowed (not forbidden)."""
    tier = get_action_tier(action_name, user_id=user_id)
    return tier != ActionTier.FORBIDDEN


def requires_approval(action_name: str, user_id: Optional[str] = None) -> bool:
    """Check if an action requires user approval."""
    tier = get_action_tier(action_name, user_id=user_id)
    return tier in [ActionTier.APPROVE_STANDARD, ActionTier.APPROVE_CRITICAL]


def check_path_permission(path: str, operation: str = "read") -> Dict[str, Any]:
    """
    Check if a path operation is allowed.

    Returns:
        {"allowed": bool, "reason": str}
    """
    permissions = load_permissions()
    sandbox = permissions.get("sandbox", {})

    # Normalize path
    path = os.path.normpath(path)

    # Check forbidden paths first
    for forbidden in sandbox.get("forbidden_paths", []):
        forbidden_path = os.path.normpath(forbidden.get("path", ""))
        if path.startswith(forbidden_path):
            return {
                "allowed": False,
                "reason": forbidden.get("reason", "Path is forbidden")
            }

    # Check allowed paths
    for allowed in sandbox.get("allowed_paths", []):
        allowed_path = os.path.normpath(allowed.get("path", ""))
        if path.startswith(allowed_path):
            perms = allowed.get("permissions", [])
            if operation in perms or "write" in perms and operation == "read":
                return {"allowed": True, "reason": "Path is allowed"}
            return {
                "allowed": False,
                "reason": f"Operation '{operation}' not permitted on this path"
            }

    # Default deny
    return {"allowed": False, "reason": "Path not in allowed list"}


# =============================================================================
# ACTION QUEUE OPERATIONS
# =============================================================================

def _ensure_queue_dirs():
    """Ensure queue directories exist."""
    for subdir in QUEUE_DIRS:
        Path(ACTION_QUEUE_BASE, subdir).mkdir(parents=True, exist_ok=True)


def create_action_request(
    action_name: str,
    description: str,
    target: Optional[str] = None,
    context: Optional[Dict] = None,
    content_preview: Optional[str] = None,
    urgent: bool = False,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a new action request.

    Returns action request dict with status based on tier:
    - AUTONOMOUS: immediate execution allowed
    - NOTIFY: immediate execution, notification queued
    - APPROVE_*: request queued for approval
    - FORBIDDEN: request blocked
    """
    _ensure_queue_dirs()

    if user_id is None and context and isinstance(context, dict):
        user_id = context.get("user_id")

    tier = get_action_tier(action_name, user_id=user_id)
    permissions = load_permissions()
    tier_config = permissions.get("tiers", {}).get(tier.value, {})

    action_id = str(uuid.uuid4())[:12]
    now = datetime.utcnow()

    # Calculate timeout
    timeout_hours = tier_config.get("timeout_hours", 4)
    if urgent:
        timeout_hours = permissions.get("approval", {}).get("timeouts", {}).get("urgent_minutes", 30) / 60

    expires_at = now + timedelta(hours=timeout_hours)

    request = {
        "id": action_id,
        "action": action_name,
        "description": description,
        "tier": tier.value,
        "target": target,
        "context": context or {},
        "content_preview": content_preview[:500] if content_preview else None,
        "urgent": urgent,
        "created_at": now.isoformat() + "Z",
        "expires_at": expires_at.isoformat() + "Z",
        "status": None,  # Will be set below
        "result": None,
    }

    # Determine status based on tier
    if tier == ActionTier.FORBIDDEN:
        request["status"] = "blocked"
        request["result"] = {"error": "Action is forbidden"}
        _save_action(request, "rejected")
        AUTONOMOUS_ACTIONS_TOTAL.labels(
            action=action_name, tier=tier.value, status="blocked"
        ).inc()
        AUTONOMOUS_ERRORS_TOTAL.labels(
            action=action_name, stage="create", error_type="forbidden"
        ).inc()
        log_with_context(logger, "warning", "Forbidden action attempted",
                        action=action_name, id=action_id)
        return request

    if tier == ActionTier.AUTONOMOUS:
        request["status"] = "approved"
        request["result"] = {"auto_approved": True, "reason": "Tier 1 autonomous"}
        # Don't save to queue, just return for immediate execution
        AUTONOMOUS_ACTIONS_TOTAL.labels(
            action=action_name, tier=tier.value, status="auto_approved"
        ).inc()
        log_with_context(logger, "info", "Autonomous action approved",
                        action=action_name, id=action_id)
        return request

    if tier == ActionTier.NOTIFY:
        request["status"] = "approved"
        request["result"] = {"auto_approved": True, "reason": "Tier 2 notify", "notify": True}
        # Save to completed for audit trail
        _save_action(request, "completed")
        AUTONOMOUS_ACTIONS_TOTAL.labels(
            action=action_name, tier=tier.value, status="auto_approved_notify"
        ).inc()
        log_with_context(logger, "info", "Notify action approved",
                        action=action_name, id=action_id)
        return request

    # APPROVE_STANDARD or APPROVE_CRITICAL
    request["status"] = "pending"
    _save_action(request, "pending")
    AUTONOMOUS_ACTIONS_TOTAL.labels(
        action=action_name, tier=tier.value, status="pending"
    ).inc()
    log_with_context(logger, "info", "Action queued for approval",
                    action=action_name, tier=tier.value, id=action_id,
                    expires_at=request["expires_at"])
    return request


def _save_action(request: Dict, status_dir: str) -> bool:
    """Save action request to appropriate directory."""
    try:
        file_path = Path(ACTION_QUEUE_BASE, status_dir, f"{request['id']}.json")
        with open(file_path, 'w') as f:
            json.dump(request, f, indent=2)
        return True
    except Exception as e:
        log_with_context(logger, "error", "Failed to save action",
                        id=request.get("id"), error=str(e))
        return False


def _move_action(action_id: str, from_dir: str, to_dir: str) -> bool:
    """Move action file between status directories."""
    try:
        src = Path(ACTION_QUEUE_BASE, from_dir, f"{action_id}.json")
        dst = Path(ACTION_QUEUE_BASE, to_dir, f"{action_id}.json")
        if src.exists():
            src.rename(dst)
            return True
        return False
    except Exception as e:
        log_with_context(logger, "error", "Failed to move action",
                        id=action_id, error=str(e))
        return False


def get_action(action_id: str) -> Optional[Dict]:
    """Get action request by ID from any status directory."""
    for status_dir in QUEUE_DIRS:
        file_path = Path(ACTION_QUEUE_BASE, status_dir, f"{action_id}.json")
        if file_path.exists():
            try:
                with open(file_path) as f:
                    return json.load(f)
            except Exception as e:
                log_with_context(logger, "error", "Failed to read action",
                                id=action_id, error=str(e))
    return None


def get_pending_actions() -> List[Dict]:
    """Get all pending action requests."""
    pending_dir = Path(ACTION_QUEUE_BASE, "pending")
    actions = []

    if not pending_dir.exists():
        return actions

    for file_path in pending_dir.glob("*.json"):
        try:
            with open(file_path) as f:
                actions.append(json.load(f))
        except Exception as e:
            log_with_context(logger, "error", "Failed to read pending action",
                            file=str(file_path), error=str(e))

    # Sort by creation time
    actions.sort(key=lambda x: x.get("created_at", ""))
    return actions


def approve_action(action_id: str, approved_by: str = "user") -> Dict[str, Any]:
    """
    Approve a pending action.

    Returns the updated action request.
    """
    action = get_action(action_id)
    if not action:
        return {"error": "Action not found", "id": action_id}

    if action.get("status") != "pending":
        return {"error": f"Action is not pending (status: {action.get('status')})", "id": action_id}

    # Update action
    action["status"] = "approved"
    action["approved_at"] = datetime.utcnow().isoformat() + "Z"
    action["approved_by"] = approved_by

    # Move to approved directory
    if _move_action(action_id, "pending", "approved"):
        # Save updated content
        _save_action(action, "approved")
        AUTONOMOUS_ACTIONS_TOTAL.labels(
            action=action.get("action", "unknown"),
            tier=action.get("tier", "unknown"),
            status="approved"
        ).inc()
        AUTONOMOUS_APPROVAL_DECISIONS.labels(
            decision="approved",
            tier=action.get("tier", "unknown")
        ).inc()
        _record_approval_latency(action, decision="approved")
        log_with_context(logger, "info", "Action approved",
                        id=action_id, by=approved_by)
        return action

    return {"error": "Failed to approve action", "id": action_id}


def reject_action(action_id: str, rejected_by: str = "user", reason: str = None) -> Dict[str, Any]:
    """
    Reject a pending action.

    Returns the updated action request.
    """
    action = get_action(action_id)
    if not action:
        return {"error": "Action not found", "id": action_id}

    if action.get("status") != "pending":
        return {"error": f"Action is not pending (status: {action.get('status')})", "id": action_id}

    # Update action
    action["status"] = "rejected"
    action["rejected_at"] = datetime.utcnow().isoformat() + "Z"
    action["rejected_by"] = rejected_by
    action["rejection_reason"] = reason

    # Move to rejected directory
    if _move_action(action_id, "pending", "rejected"):
        _save_action(action, "rejected")
        AUTONOMOUS_ACTIONS_TOTAL.labels(
            action=action.get("action", "unknown"),
            tier=action.get("tier", "unknown"),
            status="rejected"
        ).inc()
        AUTONOMOUS_APPROVAL_DECISIONS.labels(
            decision="rejected",
            tier=action.get("tier", "unknown")
        ).inc()
        _record_approval_latency(action, decision="rejected")
        log_with_context(logger, "info", "Action rejected",
                        id=action_id, by=rejected_by, reason=reason)
        return action

    return {"error": "Failed to reject action", "id": action_id}


def mark_action_completed(action_id: str, result: Optional[Dict] = None) -> Dict[str, Any]:
    """Mark an approved action as completed."""
    action = get_action(action_id)
    if not action:
        return {"error": "Action not found", "id": action_id}

    if action.get("status") != "approved":
        return {"error": f"Action is not approved (status: {action.get('status')})", "id": action_id}

    action["status"] = "completed"
    action["completed_at"] = datetime.utcnow().isoformat() + "Z"
    action["result"] = result

    if _move_action(action_id, "approved", "completed"):
        _save_action(action, "completed")
        AUTONOMOUS_ACTIONS_TOTAL.labels(
            action=action.get("action", "unknown"),
            tier=action.get("tier", "unknown"),
            status="completed"
        ).inc()
        log_with_context(logger, "info", "Action completed", id=action_id)
        return action

    return {"error": "Failed to mark action completed", "id": action_id}


def check_expired_actions() -> List[Dict]:
    """
    Check for and process expired actions.

    Returns list of expired actions.
    """
    expired = []
    now = datetime.utcnow()
    permissions = load_permissions()
    fallback = permissions.get("approval", {}).get("fallback_on_timeout", "queue")

    for action in get_pending_actions():
        expires_at_str = action.get("expires_at")
        if not expires_at_str:
            continue

        try:
            expires_at = datetime.fromisoformat(expires_at_str.rstrip("Z"))
            if now > expires_at:
                action["status"] = "expired"
                action["expired_at"] = now.isoformat() + "Z"
                action["fallback_applied"] = fallback

                _move_action(action["id"], "pending", "expired")
                _save_action(action, "expired")
                AUTONOMOUS_ACTIONS_TOTAL.labels(
                    action=action.get("action", "unknown"),
                    tier=action.get("tier", "unknown"),
                    status="expired"
                ).inc()
                AUTONOMOUS_APPROVAL_DECISIONS.labels(
                    decision="expired",
                    tier=action.get("tier", "unknown")
                ).inc()
                _record_approval_latency(action, decision="expired")
                expired.append(action)

                log_with_context(logger, "info", "Action expired",
                                id=action["id"], fallback=fallback)
        except Exception as e:
            log_with_context(logger, "error", "Error checking expiration",
                            id=action.get("id"), error=str(e))

    return expired


# =============================================================================
# NOTIFICATION HELPERS
# =============================================================================

def format_approval_message(action: Dict) -> str:
    """Format action request for Telegram notification."""
    permissions = load_permissions()
    template = permissions.get("notification", {}).get("format", "")

    if not template:
        template = "🤖 Jarvis möchte: {description}\n\n⏰ Timeout: {timeout}"

    # Calculate remaining time
    expires_at_str = action.get("expires_at", "")
    try:
        expires_at = datetime.fromisoformat(expires_at_str.rstrip("Z"))
        remaining = expires_at - datetime.utcnow()
        hours = int(remaining.total_seconds() // 3600)
        minutes = int((remaining.total_seconds() % 3600) // 60)
        timeout_str = f"{hours}h {minutes}m"
    except Exception:
        timeout_str = "unbekannt"

    return template.format(
        action_description=action.get("description", "Unbekannte Aktion"),
        reason=action.get("context", {}).get("reason", "Kein Grund angegeben"),
        timeout=timeout_str,
    )


def get_approval_buttons(action_id: str) -> List[List[Dict]]:
    """Get inline keyboard buttons for approval."""
    return [
        [
            {"text": "✅ Ja", "callback_data": f"approval:approve:{action_id}"},
            {"text": "❌ Nein", "callback_data": f"approval:reject:{action_id}"},
        ],
        [
            {"text": "ℹ️ Details", "callback_data": f"approval:info:{action_id}"},
        ]
    ]


def _record_approval_latency(action: Dict[str, Any], decision: str) -> None:
    """Record approval latency (seconds) from created_at to decision time."""
    try:
        created_at = action.get("created_at")
        if not created_at:
            return
        created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        latency_seconds = (datetime.utcnow() - created.replace(tzinfo=None)).total_seconds()
        AUTONOMOUS_APPROVAL_LATENCY_SECONDS.labels(
            decision=decision,
            tier=action.get("tier", "unknown")
        ).observe(max(0, latency_seconds))
    except Exception as e:
        log_with_context(logger, "warning", "Failed to record approval latency",
                        error=str(e), action_id=action.get("id"))
