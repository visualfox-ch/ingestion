"""
Domain Separation - Namespace Enforcement and Cross-Domain Protection

Ensures:
- Explicit namespace required for all knowledge operations
- Private data stays private (no LLM by default)
- Cross-namespace access is logged and controlled
- Configurable flags for flexibility
"""
import os
from typing import Optional, List, Dict
from datetime import datetime

from .knowledge_db import get_conn
from .observability import get_logger, log_with_context

logger = get_logger("jarvis.domain")


# ============ Configuration (from environment) ============

def _get_bool_env(key: str, default: bool) -> bool:
    val = os.environ.get(key, "").lower()
    if val in ("true", "1", "yes"):
        return True
    if val in ("false", "0", "no"):
        return False
    return default


# Private namespace protection
ALLOW_LLM_PRIVATE = _get_bool_env("ALLOW_LLM_PRIVATE", False)

# Cross-namespace access
ALLOW_CROSS_NAMESPACE = _get_bool_env("ALLOW_CROSS_NAMESPACE", False)

# Logging level for access
LOG_ALL_ACCESS = _get_bool_env("LOG_ALL_ACCESS", False)  # Log all namespace access


# ============ Namespace Definitions ============

NAMESPACES = {
    "private": {
        "description": "Personal private data",
        "llm_allowed": ALLOW_LLM_PRIVATE,
        "cross_access_allowed": False,
        "collections": ["jarvis_private", "private_comms"]
    },
    "work_projektil": {
        "description": "Projektil work data",
        "llm_allowed": True,
        "cross_access_allowed": ALLOW_CROSS_NAMESPACE,
        "collections": ["jarvis_work", "work_comms"]
    },
    "work_visualfox": {
        "description": "Visualfox work data",
        "llm_allowed": True,
        "cross_access_allowed": ALLOW_CROSS_NAMESPACE,
        "collections": ["jarvis_work", "work_comms"]
    },
    "shared": {
        "description": "Cross-domain shared data",
        "llm_allowed": True,
        "cross_access_allowed": True,
        "collections": ["jarvis_shared"]
    }
}

# Work namespaces that can access each other
WORK_NAMESPACE_GROUP = ["work_projektil", "work_visualfox"]


# ============ Access Control ============

class NamespaceAccessDenied(Exception):
    """Raised when namespace access is not allowed"""
    def __init__(self, source: str, target: str, reason: str):
        self.source = source
        self.target = target
        self.reason = reason
        super().__init__(f"Access denied: {source} -> {target}: {reason}")


def validate_namespace(namespace: str) -> bool:
    """Check if namespace is valid"""
    return namespace in NAMESPACES


def check_access(
    source_namespace: str,
    target_namespace: str,
    access_type: str = "query",
    user_id: str = None,
    log_access: bool = True
) -> Dict:
    """
    Check if access from source to target namespace is allowed.

    Args:
        source_namespace: The namespace making the request
        target_namespace: The namespace being accessed
        access_type: query, retrieve, inference
        user_id: User making the request
        log_access: Whether to log this access

    Returns:
        Dict with allowed status and reason
    """
    result = {
        "source": source_namespace,
        "target": target_namespace,
        "access_type": access_type,
        "allowed": False,
        "reason": None
    }

    # Validate namespaces
    if not validate_namespace(source_namespace):
        result["reason"] = f"invalid_source_namespace: {source_namespace}"
        return result

    if not validate_namespace(target_namespace):
        result["reason"] = f"invalid_target_namespace: {target_namespace}"
        return result

    # Same namespace always allowed
    if source_namespace == target_namespace:
        result["allowed"] = True
        result["reason"] = "same_namespace"
        if LOG_ALL_ACCESS and log_access:
            _log_access(result, user_id)
        return result

    # Shared namespace accessible from anywhere
    if target_namespace == "shared":
        result["allowed"] = True
        result["reason"] = "shared_namespace"
        if log_access:
            _log_access(result, user_id)
        return result

    # Private namespace strict protection
    if target_namespace == "private":
        if source_namespace == "private":
            result["allowed"] = True
            result["reason"] = "same_namespace"
        else:
            result["allowed"] = False
            result["reason"] = "private_namespace_protected"
        if log_access:
            _log_access(result, user_id)
        return result

    # Work namespaces can access each other if in same group
    if source_namespace in WORK_NAMESPACE_GROUP and target_namespace in WORK_NAMESPACE_GROUP:
        if ALLOW_CROSS_NAMESPACE:
            result["allowed"] = True
            result["reason"] = "work_namespace_group"
        else:
            result["allowed"] = False
            result["reason"] = "cross_namespace_disabled"
        if log_access:
            _log_access(result, user_id)
        return result

    # Default: deny
    result["allowed"] = False
    result["reason"] = "cross_namespace_not_allowed"
    if log_access:
        _log_access(result, user_id)
    return result


def _log_access(result: Dict, user_id: str = None):
    """Log access attempt to database"""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO domain_access_log
                (user_id, source_namespace, target_namespace, access_type, allowed, reason)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                user_id,
                result["source"],
                result["target"],
                result.get("access_type", "unknown"),
                result["allowed"],
                result["reason"]
            ))

    except Exception as e:
        log_with_context(logger, "warning", "Failed to log domain access", error=str(e))


def require_namespace(namespace: str) -> None:
    """
    Decorator helper to require valid namespace.
    Raises NamespaceAccessDenied if namespace is invalid or None.
    """
    if not namespace:
        raise NamespaceAccessDenied("unknown", "unknown", "namespace_required")

    if not validate_namespace(namespace):
        raise NamespaceAccessDenied("unknown", namespace, "invalid_namespace")


def check_llm_allowed(namespace: str) -> bool:
    """Check if LLM access is allowed for this namespace"""
    if namespace not in NAMESPACES:
        return False
    return NAMESPACES[namespace]["llm_allowed"]


def get_allowed_collections(namespace: str) -> List[str]:
    """Get the vector/search collections allowed for this namespace"""
    if namespace not in NAMESPACES:
        return []
    return NAMESPACES[namespace]["collections"]


# ============ DB-driven Scope API (Release 1 additions) ============

_scope_policy_cache: Dict[str, Dict] = {}


def get_scope_policy(org: str, visibility: str) -> Dict:
    """Load scope policy from DB (in-process cached per process).

    Falls back to the hardcoded NAMESPACES dict when the scope_policy table
    doesn't exist yet (pre-migration environments).
    """
    cache_key = f"{org}/{visibility}"
    if cache_key in _scope_policy_cache:
        return _scope_policy_cache[cache_key]

    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT llm_allowed, cross_access_allowed, qdrant_collections "
                "FROM scope_policy WHERE org=%s AND visibility=%s AND active=true",
                (org, visibility),
            )
            row = cur.fetchone()
        if row:
            result = {
                "llm_allowed": row[0],
                "cross_access_allowed": row[1],
                "qdrant_collections": row[2] if isinstance(row[2], list) else [],
            }
            _scope_policy_cache[cache_key] = result
            return result
    except Exception as e:
        log_with_context(logger, "warning", "scope_policy DB lookup failed, using fallback", error=str(e))

    # Fallback: derive from legacy NAMESPACES dict
    from .models import _NAMESPACE_TO_SCOPE, _SCOPE_TO_NAMESPACE
    legacy_ns = _SCOPE_TO_NAMESPACE.get((org, visibility))
    if legacy_ns and legacy_ns in NAMESPACES:
        ns_cfg = NAMESPACES[legacy_ns]
        return {
            "llm_allowed": ns_cfg["llm_allowed"],
            "cross_access_allowed": ns_cfg["cross_access_allowed"],
            "qdrant_collections": ns_cfg["collections"],
        }
    return {"llm_allowed": True, "cross_access_allowed": False, "qdrant_collections": []}


def invalidate_scope_cache() -> None:
    """Clear the in-process scope_policy cache (call after DB updates)."""
    _scope_policy_cache.clear()


def get_default_scope(channel: str) -> Dict[str, str]:
    """Return the default scope dict for a given channel.

    Reads from scope_defaults table; falls back to projektil/internal.
    """
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT default_org, default_visibility, default_owner "
                "FROM scope_defaults WHERE channel=%s AND active=true "
                "ORDER BY user_id NULLS LAST, source_type NULLS LAST LIMIT 1",
                (channel,),
            )
            row = cur.fetchone()
        if row:
            return {"org": row[0], "visibility": row[1], "owner": row[2]}
    except Exception as e:
        log_with_context(logger, "warning", "scope_defaults DB lookup failed, using fallback", error=str(e))

    return {"org": "projektil", "visibility": "internal", "owner": "michael_bohl"}


# ============ Access Statistics ============

def get_access_stats(days: int = 7, namespace: str = None) -> Dict:
    """Get access statistics for the past N days"""
    try:
        with get_conn() as conn:
            cur = conn.cursor()

            namespace_filter = "AND (source_namespace = %s OR target_namespace = %s)" if namespace else ""
            params = [days]
            if namespace:
                params.extend([namespace, namespace])

            cur.execute(f"""
                SELECT
                    COUNT(*) as total_requests,
                    COUNT(*) FILTER (WHERE allowed = true) as allowed,
                    COUNT(*) FILTER (WHERE allowed = false) as denied,
                    COUNT(DISTINCT user_id) as unique_users,
                    COUNT(*) FILTER (WHERE source_namespace != target_namespace) as cross_namespace
                FROM domain_access_log
                WHERE created_at > NOW() - INTERVAL '%s days'
                {namespace_filter}
            """, params)

            row = cur.fetchone()
            return dict(row) if row else {}

    except Exception as e:
        log_with_context(logger, "error", "Failed to get access stats", error=str(e))
        return {}


def get_denied_accesses(limit: int = 20) -> List[Dict]:
    """Get recent denied access attempts"""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT * FROM domain_access_log
                WHERE allowed = false
                ORDER BY created_at DESC
                LIMIT %s
            """, (limit,))

            return [dict(row) for row in cur.fetchall()]

    except Exception as e:
        log_with_context(logger, "error", "Failed to get denied accesses", error=str(e))
        return []


# ============ Configuration Info ============

def get_config() -> Dict:
    """Get current domain separation configuration"""
    return {
        "allow_llm_private": ALLOW_LLM_PRIVATE,
        "allow_cross_namespace": ALLOW_CROSS_NAMESPACE,
        "log_all_access": LOG_ALL_ACCESS,
        "namespaces": {
            ns: {
                "description": cfg["description"],
                "llm_allowed": cfg["llm_allowed"],
                "cross_access_allowed": cfg["cross_access_allowed"]
            }
            for ns, cfg in NAMESPACES.items()
        }
    }
