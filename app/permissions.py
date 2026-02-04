"""
Permission Matrix Module (Gate A)

Loads jarvis_permissions.yaml into Postgres and provides permission checking.
Policy-as-data: tool → action → risk → approver → timeout
"""

import os
import yaml
import json
from typing import Dict, List, Optional, Any
from datetime import datetime

from .observability import get_logger, log_with_context
from .postgres_state import get_cursor

logger = get_logger("jarvis.permissions")

# Path to permissions YAML
PERMISSIONS_YAML_PATH = os.environ.get(
    "PERMISSIONS_YAML_PATH",
    "/brain/system/policies/jarvis_permissions.yaml"
)

# Cache for permissions (hot-reload support)
_permissions_cache: Dict[str, Dict] = {}
_tiers_cache: Dict[str, Dict] = {}
_sandbox_cache: Dict[str, List[Dict]] = {}
_last_loaded: Optional[datetime] = None


def load_permissions_from_yaml(yaml_path: str = None) -> Dict[str, Any]:
    """
    Load permissions from YAML file.
    Returns the parsed YAML as a dict.
    """
    path = yaml_path or PERMISSIONS_YAML_PATH

    if not os.path.exists(path):
        log_with_context(logger, "warning", f"Permissions YAML not found: {path}")
        return {}

    try:
        with open(path, 'r') as f:
            data = yaml.safe_load(f)
        log_with_context(logger, "info", "Loaded permissions YAML", path=path)
        return data or {}
    except Exception as e:
        log_with_context(logger, "error", "Failed to load permissions YAML", error=str(e))
        return {}


def sync_permissions_to_db(yaml_path: str = None) -> Dict[str, int]:
    """
    Sync permissions from YAML to database.
    Returns counts of inserted/updated records.
    """
    global _permissions_cache, _tiers_cache, _sandbox_cache, _last_loaded

    data = load_permissions_from_yaml(yaml_path)
    if not data:
        return {"permissions": 0, "sandbox_paths": 0}

    counts = {"permissions": 0, "sandbox_paths": 0}

    # Load tiers
    _tiers_cache = data.get("tiers", {})

    # Sync actions to permissions table
    actions = data.get("actions", {})

    with get_cursor() as cur:
        for tier_name, action_list in actions.items():
            tier_config = _tiers_cache.get(tier_name, {})

            for action_def in action_list:
                action = action_def.get("action")
                if not action:
                    continue

                cur.execute("""
                    INSERT INTO permissions (action, tier, description, requires_approval,
                                            notify_user, timeout_hours, guidelines, reason, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (action) DO UPDATE SET
                        tier = EXCLUDED.tier,
                        description = EXCLUDED.description,
                        requires_approval = EXCLUDED.requires_approval,
                        notify_user = EXCLUDED.notify_user,
                        timeout_hours = EXCLUDED.timeout_hours,
                        guidelines = EXCLUDED.guidelines,
                        reason = EXCLUDED.reason,
                        updated_at = NOW()
                """, (
                    action,
                    tier_name,
                    action_def.get("description", ""),
                    tier_config.get("requires_approval", False),
                    tier_config.get("notify_user", False),
                    tier_config.get("timeout_hours"),
                    json.dumps(action_def.get("guidelines", [])),
                    action_def.get("reason", "")
                ))
                counts["permissions"] += 1

                # Update cache
                _permissions_cache[action] = {
                    "action": action,
                    "tier": tier_name,
                    "description": action_def.get("description", ""),
                    "requires_approval": tier_config.get("requires_approval", False),
                    "notify_user": tier_config.get("notify_user", False),
                    "timeout_hours": tier_config.get("timeout_hours"),
                    "guidelines": action_def.get("guidelines", []),
                    "reason": action_def.get("reason", ""),
                    "blocked": tier_config.get("blocked", False)
                }

        # Sync sandbox paths
        sandbox = data.get("sandbox", {})

        # Clear existing sandbox paths
        cur.execute("DELETE FROM sandbox_paths")

        for path_def in sandbox.get("allowed_paths", []):
            cur.execute("""
                INSERT INTO sandbox_paths (path, path_type, permissions, description)
                VALUES (%s, %s, %s, %s)
            """, (
                path_def.get("path", ""),
                "allowed",
                json.dumps(path_def.get("permissions", [])),
                path_def.get("description", "")
            ))
            counts["sandbox_paths"] += 1

        for path_def in sandbox.get("forbidden_paths", []):
            cur.execute("""
                INSERT INTO sandbox_paths (path, path_type, reason)
                VALUES (%s, %s, %s)
            """, (
                path_def.get("path", ""),
                "forbidden",
                path_def.get("reason", "")
            ))
            counts["sandbox_paths"] += 1

    # Update sandbox cache
    _sandbox_cache = {
        "allowed": sandbox.get("allowed_paths", []),
        "forbidden": sandbox.get("forbidden_paths", [])
    }

    _last_loaded = datetime.now()

    log_with_context(logger, "info", "Synced permissions to database",
                    permissions=counts["permissions"],
                    sandbox_paths=counts["sandbox_paths"])

    return counts


def get_permission(action: str) -> Optional[Dict[str, Any]]:
    """
    Get permission definition for an action.
    Uses cache if available, falls back to database.
    """
    # Check cache first
    if action in _permissions_cache:
        return _permissions_cache[action]

    # Load from database
    with get_cursor() as cur:
        cur.execute("""
            SELECT action, tier, description, requires_approval, notify_user,
                   timeout_hours, guidelines, reason
            FROM permissions
            WHERE action = %s
        """, (action,))
        row = cur.fetchone()

        if row:
            perm = {
                "action": row["action"],
                "tier": row["tier"],
                "description": row["description"],
                "requires_approval": row["requires_approval"],
                "notify_user": row["notify_user"],
                "timeout_hours": row["timeout_hours"],
                "guidelines": row["guidelines"] or [],
                "reason": row["reason"],
                "blocked": row["tier"] == "forbidden"
            }
            _permissions_cache[action] = perm
            return perm

    return None


def check_permission(action: str, actor: str = "jarvis", context: Dict = None) -> Dict[str, Any]:
    """
    Check if an action is permitted.

    Returns:
        {
            "allowed": bool,
            "tier": str,
            "requires_approval": bool,
            "notify_user": bool,
            "timeout_hours": int or None,
            "reason": str (if denied),
            "action": str
        }
    """
    context = context or {}

    perm = get_permission(action)

    if not perm:
        # Unknown action - default to requiring approval
        result = {
            "allowed": False,
            "tier": "unknown",
            "requires_approval": True,
            "notify_user": True,
            "timeout_hours": None,
            "reason": "Unknown action - not in permission matrix",
            "action": action
        }
        _log_audit(action, actor, "unknown", "denied_unknown", context)
        return result

    # Check if forbidden
    if perm.get("blocked") or perm["tier"] == "forbidden":
        result = {
            "allowed": False,
            "tier": perm["tier"],
            "requires_approval": False,
            "notify_user": False,
            "timeout_hours": None,
            "reason": perm.get("reason", "Action is forbidden"),
            "action": action
        }
        _log_audit(action, actor, perm["tier"], "denied_forbidden", context)
        return result

    # Autonomous tier - always allowed
    if perm["tier"] == "autonomous":
        result = {
            "allowed": True,
            "tier": perm["tier"],
            "requires_approval": False,
            "notify_user": False,
            "timeout_hours": None,
            "reason": None,
            "action": action
        }
        _log_audit(action, actor, perm["tier"], "allowed", context)
        return result

    # Notify tier - allowed but notify
    if perm["tier"] == "notify":
        result = {
            "allowed": True,
            "tier": perm["tier"],
            "requires_approval": False,
            "notify_user": True,
            "timeout_hours": None,
            "reason": None,
            "action": action,
            "guidelines": perm.get("guidelines", [])
        }
        _log_audit(action, actor, perm["tier"], "allowed_notify", context)
        return result

    # Approval tiers - needs approval
    if perm["tier"] in ("approve_standard", "approve_critical"):
        result = {
            "allowed": False,  # Not allowed without approval
            "tier": perm["tier"],
            "requires_approval": True,
            "notify_user": True,
            "timeout_hours": perm.get("timeout_hours"),
            "reason": "Requires approval",
            "action": action,
            "guidelines": perm.get("guidelines", [])
        }
        _log_audit(action, actor, perm["tier"], "needs_approval", context)
        return result

    # Default - deny unknown tier
    result = {
        "allowed": False,
        "tier": perm["tier"],
        "requires_approval": True,
        "notify_user": True,
        "timeout_hours": None,
        "reason": f"Unknown tier: {perm['tier']}",
        "action": action
    }
    _log_audit(action, actor, perm["tier"], "denied_unknown_tier", context)
    return result


def _log_audit(action: str, actor: str, tier: str, result: str, context: Dict):
    """Log permission check to audit table."""
    try:
        with get_cursor() as cur:
            cur.execute("""
                INSERT INTO permission_audit (action, actor, tier, result, context)
                VALUES (%s, %s, %s, %s, %s)
            """, (action, actor, tier, result, json.dumps(context)))
    except Exception as e:
        log_with_context(logger, "warning", "Failed to log permission audit", error=str(e))


def list_permissions(tier: str = None) -> List[Dict[str, Any]]:
    """List all permissions, optionally filtered by tier."""
    with get_cursor() as cur:
        if tier:
            cur.execute("""
                SELECT action, tier, description, requires_approval, notify_user,
                       timeout_hours, guidelines, reason
                FROM permissions
                WHERE tier = %s
                ORDER BY action
            """, (tier,))
        else:
            cur.execute("""
                SELECT action, tier, description, requires_approval, notify_user,
                       timeout_hours, guidelines, reason
                FROM permissions
                ORDER BY tier, action
            """)

        rows = cur.fetchall()
        return [dict(row) for row in rows]


def list_audit_log(action: str = None, actor: str = None, limit: int = 50) -> List[Dict[str, Any]]:
    """Get permission audit log."""
    with get_cursor() as cur:
        conditions = []
        params = []

        if action:
            conditions.append("action = %s")
            params.append(action)
        if actor:
            conditions.append("actor = %s")
            params.append(actor)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)

        cur.execute(f"""
            SELECT audit_id, action, actor, tier, result, context, created_at
            FROM permission_audit
            {where_clause}
            ORDER BY created_at DESC
            LIMIT %s
        """, params)

        rows = cur.fetchall()
        return [
            {
                **dict(row),
                "created_at": row["created_at"].isoformat() if row["created_at"] else None
            }
            for row in rows
        ]


def check_path_permission(path: str, operation: str = "read") -> Dict[str, Any]:
    """
    Check if a path operation is allowed in the sandbox.

    Args:
        path: The file/directory path
        operation: read, write, or append

    Returns:
        {
            "allowed": bool,
            "reason": str (if denied)
        }
    """
    # Check forbidden paths first
    for forbidden in _sandbox_cache.get("forbidden", []):
        forbidden_path = forbidden.get("path", "")
        if path.startswith(forbidden_path) or forbidden_path.startswith("~") and path.startswith(os.path.expanduser(forbidden_path)):
            return {
                "allowed": False,
                "reason": forbidden.get("reason", "Path is forbidden")
            }

    # Check allowed paths
    for allowed in _sandbox_cache.get("allowed", []):
        allowed_path = allowed.get("path", "")
        if path.startswith(allowed_path):
            allowed_ops = allowed.get("permissions", [])
            if operation in allowed_ops:
                return {
                    "allowed": True,
                    "reason": None
                }
            else:
                return {
                    "allowed": False,
                    "reason": f"Operation '{operation}' not allowed on this path"
                }

    # Default - not in any allowed path
    return {
        "allowed": False,
        "reason": "Path not in sandbox allowed list"
    }


def get_tier_stats() -> Dict[str, int]:
    """Get count of permissions by tier."""
    with get_cursor() as cur:
        cur.execute("""
            SELECT tier, COUNT(*) as count
            FROM permissions
            GROUP BY tier
            ORDER BY tier
        """)
        rows = cur.fetchall()
        return {row["tier"]: row["count"] for row in rows}


def get_last_loaded() -> Optional[str]:
    """Get timestamp of last YAML load."""
    return _last_loaded.isoformat() if _last_loaded else None


# Initialize on import
def init_permissions():
    """Initialize permissions system - load from YAML on startup."""
    try:
        counts = sync_permissions_to_db()
        log_with_context(logger, "info", "Permission system initialized", **counts)
    except Exception as e:
        log_with_context(logger, "warning", f"Failed to initialize permissions: {e}")
