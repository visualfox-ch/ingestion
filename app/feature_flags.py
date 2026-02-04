"""
Feature Flags Management with Hot-Reload Support

Phase 18.3: Infrastructure Hardening
- Runtime toggle without restart
- Versioning with history/audit
- Staged rollouts (percentage-based)
- Emergency kill-switch

Based on Jarvis recommendations:
- Hot-reload at runtime (no restart required)
- Version history for audit trail
- Staged rollouts (5% → 25% → 100%)
- Emergency kill-switch stays simple boolean
"""
import os
import json
import threading
from datetime import datetime
from typing import Dict, List, Optional, Any
from contextlib import contextmanager

from .observability import get_logger, log_with_context
from . import config

logger = get_logger("jarvis.feature_flags")

# In-memory cache for hot-reload
_flag_cache: Dict[str, Any] = {}
_cache_lock = threading.RLock()
_last_refresh: Optional[datetime] = None
CACHE_TTL_SECONDS = 30  # Refresh from DB every 30 seconds


def init_feature_flags_schema():
    """Initialize feature flags table in PostgreSQL.

    Should be called from main app startup after postgres_state.init_state_schema()
    """
    from .postgres_state import get_cursor

    with get_cursor() as cur:
        # Feature Flags Table with versioning and rollout support
        cur.execute("""
            CREATE TABLE IF NOT EXISTS feature_flags (
                id SERIAL PRIMARY KEY,
                flag_name TEXT UNIQUE NOT NULL,

                -- Core state
                enabled BOOLEAN DEFAULT FALSE,
                rollout_percent INTEGER DEFAULT 100 CHECK (rollout_percent >= 0 AND rollout_percent <= 100),

                -- Metadata
                description TEXT,
                category TEXT DEFAULT 'general',

                -- Version tracking
                version INTEGER DEFAULT 1,

                -- Kill-switch: if true, overrides all other settings and disables
                kill_switch BOOLEAN DEFAULT FALSE,

                -- Timestamps
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                enabled_at TIMESTAMP,
                disabled_at TIMESTAMP
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ff_name ON feature_flags(flag_name)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ff_category ON feature_flags(category)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ff_enabled ON feature_flags(enabled)")

        # Feature Flag History Table (audit trail)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS feature_flag_history (
                id SERIAL PRIMARY KEY,
                flag_id INTEGER NOT NULL REFERENCES feature_flags(id),
                flag_name TEXT NOT NULL,

                -- Change details
                action TEXT NOT NULL CHECK (action IN ('created', 'enabled', 'disabled', 'updated', 'rollout_changed', 'kill_switch')),
                old_value JSONB,
                new_value JSONB,

                -- Who/why/when
                changed_by TEXT DEFAULT 'system',
                change_reason TEXT,
                changed_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ffh_flag ON feature_flag_history(flag_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ffh_changed ON feature_flag_history(changed_at DESC)")

        log_with_context(logger, "info", "Feature flags schema initialized")


def _refresh_cache_if_needed():
    """Refresh in-memory cache from DB if TTL expired."""
    global _flag_cache, _last_refresh

    now = datetime.utcnow()
    if _last_refresh and (now - _last_refresh).total_seconds() < CACHE_TTL_SECONDS:
        return  # Cache still fresh

    try:
        from .postgres_state import get_cursor

        with get_cursor() as cur:
            cur.execute("""
                SELECT flag_name, enabled, rollout_percent, kill_switch, version, category
                FROM feature_flags
            """)
            rows = cur.fetchall()

        with _cache_lock:
            _flag_cache = {}
            for row in rows:
                # RealDictCursor returns dicts
                _flag_cache[row["flag_name"]] = {
                    "enabled": row["enabled"] and not row["kill_switch"],  # Kill-switch overrides
                    "rollout_percent": row["rollout_percent"],
                    "kill_switch": row["kill_switch"],
                    "version": row["version"],
                    "category": row["category"],
                }
            _last_refresh = now

    except Exception as e:
        log_with_context(logger, "warning", f"Failed to refresh feature flag cache: {e}")


def is_enabled(flag_name: str, default: bool = False, user_id: Optional[int] = None) -> bool:
    """Check if a feature flag is enabled.

    Args:
        flag_name: Name of the feature flag
        default: Default value if flag not found
        user_id: Optional user ID for percentage-based rollouts

    Returns:
        True if feature is enabled (considering rollout percentage)
    """
    if not config.FEATURE_FLAGS_ENABLED:
        return config.FEATURE_FLAGS_DEFAULTS.get(flag_name, default)

    _refresh_cache_if_needed()

    with _cache_lock:
        flag = _flag_cache.get(flag_name)

    if flag is None:
        return config.FEATURE_FLAGS_DEFAULTS.get(flag_name, default)

    if not flag["enabled"]:
        return False

    # Percentage-based rollout
    rollout = flag.get("rollout_percent", 100)
    if rollout < 100 and user_id is not None:
        # Deterministic hash for consistent experience per user
        bucket = hash(f"{flag_name}:{user_id}") % 100
        return bucket < rollout

    return rollout == 100


def get_flag(flag_name: str) -> Optional[Dict[str, Any]]:
    """Get full flag details."""
    from .postgres_state import get_cursor

    try:
        with get_cursor() as cur:
            cur.execute("""
                SELECT id, flag_name, enabled, rollout_percent, description,
                       category, version, kill_switch, created_at, updated_at,
                       enabled_at, disabled_at
                FROM feature_flags WHERE flag_name = %s
            """, (flag_name,))
            row = cur.fetchone()

        if not row:
            return None

        # RealDictCursor returns dicts, access by column name
        return {
            "id": row["id"],
            "flag_name": row["flag_name"],
            "enabled": row["enabled"] and not row["kill_switch"],  # Kill-switch check
            "rollout_percent": row["rollout_percent"],
            "description": row["description"],
            "category": row["category"],
            "version": row["version"],
            "kill_switch": row["kill_switch"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
            "enabled_at": row["enabled_at"].isoformat() if row["enabled_at"] else None,
            "disabled_at": row["disabled_at"].isoformat() if row["disabled_at"] else None,
        }
    except Exception as e:
        log_with_context(logger, "error", f"Failed to get flag {flag_name}: {e}")
        return None


def list_flags(category: Optional[str] = None) -> List[Dict[str, Any]]:
    """List all feature flags, optionally filtered by category."""
    from .postgres_state import get_cursor

    try:
        with get_cursor() as cur:
            if category:
                cur.execute("""
                    SELECT id, flag_name, enabled, rollout_percent, description,
                           category, version, kill_switch, created_at, updated_at
                    FROM feature_flags WHERE category = %s
                    ORDER BY category, flag_name
                """, (category,))
            else:
                cur.execute("""
                    SELECT id, flag_name, enabled, rollout_percent, description,
                           category, version, kill_switch, created_at, updated_at
                    FROM feature_flags
                    ORDER BY category, flag_name
                """)
            rows = cur.fetchall()

        # RealDictCursor returns dicts
        return [{
            "id": row["id"],
            "flag_name": row["flag_name"],
            "enabled": row["enabled"] and not row["kill_switch"],
            "rollout_percent": row["rollout_percent"],
            "description": row["description"],
            "category": row["category"],
            "version": row["version"],
            "kill_switch": row["kill_switch"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        } for row in rows]
    except Exception as e:
        log_with_context(logger, "error", f"Failed to list flags: {e}")
        return []


def create_flag(
    flag_name: str,
    description: str = "",
    category: str = "general",
    enabled: bool = False,
    rollout_percent: int = 100,
    changed_by: str = "system"
) -> Dict[str, Any]:
    """Create a new feature flag."""
    from .postgres_state import get_cursor

    with get_cursor() as cur:
        cur.execute("""
            INSERT INTO feature_flags (flag_name, description, category, enabled, rollout_percent)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
        """, (flag_name, description, category, enabled, rollout_percent))
        # RealDictCursor returns dicts
        flag_id = cur.fetchone()["id"]

        # Record history
        cur.execute("""
            INSERT INTO feature_flag_history (flag_id, flag_name, action, new_value, changed_by)
            VALUES (%s, %s, 'created', %s, %s)
        """, (flag_id, flag_name, json.dumps({
            "enabled": enabled,
            "rollout_percent": rollout_percent,
            "description": description,
            "category": category
        }), changed_by))

    # Invalidate cache
    global _last_refresh
    _last_refresh = None

    log_with_context(logger, "info", f"Created feature flag: {flag_name}", flag_id=flag_id)
    return get_flag(flag_name)


def update_flag(
    flag_name: str,
    enabled: Optional[bool] = None,
    rollout_percent: Optional[int] = None,
    description: Optional[str] = None,
    kill_switch: Optional[bool] = None,
    changed_by: str = "system",
    change_reason: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Update a feature flag with history tracking."""
    from .postgres_state import get_cursor

    current = get_flag(flag_name)
    if not current:
        return None

    updates = []
    params = []
    old_value = {}
    new_value = {}
    action = "updated"

    if enabled is not None and enabled != current["enabled"]:
        updates.append("enabled = %s")
        params.append(enabled)
        old_value["enabled"] = current["enabled"]
        new_value["enabled"] = enabled
        action = "enabled" if enabled else "disabled"
        if enabled:
            updates.append("enabled_at = NOW()")
        else:
            updates.append("disabled_at = NOW()")

    if rollout_percent is not None and rollout_percent != current["rollout_percent"]:
        updates.append("rollout_percent = %s")
        params.append(rollout_percent)
        old_value["rollout_percent"] = current["rollout_percent"]
        new_value["rollout_percent"] = rollout_percent
        action = "rollout_changed"

    if description is not None:
        updates.append("description = %s")
        params.append(description)

    if kill_switch is not None and kill_switch != current["kill_switch"]:
        updates.append("kill_switch = %s")
        params.append(kill_switch)
        old_value["kill_switch"] = current["kill_switch"]
        new_value["kill_switch"] = kill_switch
        action = "kill_switch"

    if not updates:
        return current  # Nothing to update

    updates.append("version = version + 1")
    updates.append("updated_at = NOW()")
    params.append(flag_name)

    with get_cursor() as cur:
        cur.execute(f"""
            UPDATE feature_flags
            SET {', '.join(updates)}
            WHERE flag_name = %s
        """, params)

        # Record history
        cur.execute("""
            INSERT INTO feature_flag_history (flag_id, flag_name, action, old_value, new_value, changed_by, change_reason)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (current["id"], flag_name, action, json.dumps(old_value), json.dumps(new_value), changed_by, change_reason))

    # Invalidate cache
    global _last_refresh
    _last_refresh = None

    log_with_context(logger, "info", f"Updated feature flag: {flag_name}", action=action)
    return get_flag(flag_name)


def delete_flag(flag_name: str, changed_by: str = "system") -> bool:
    """Delete a feature flag (soft delete via kill_switch, then hard delete)."""
    from .postgres_state import get_cursor

    current = get_flag(flag_name)
    if not current:
        return False

    with get_cursor() as cur:
        # First, record the deletion in history
        cur.execute("""
            INSERT INTO feature_flag_history (flag_id, flag_name, action, old_value, changed_by)
            VALUES (%s, %s, 'disabled', %s, %s)
        """, (current["id"], flag_name, json.dumps(current), changed_by))

        # Then delete
        cur.execute("DELETE FROM feature_flags WHERE flag_name = %s", (flag_name,))

    # Invalidate cache
    global _last_refresh
    _last_refresh = None

    log_with_context(logger, "info", f"Deleted feature flag: {flag_name}")
    return True


def get_flag_history(flag_name: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Get history of changes for a feature flag."""
    from .postgres_state import get_cursor

    try:
        with get_cursor() as cur:
            cur.execute("""
                SELECT id, flag_name, action, old_value, new_value,
                       changed_by, change_reason, changed_at
                FROM feature_flag_history
                WHERE flag_name = %s
                ORDER BY changed_at DESC
                LIMIT %s
            """, (flag_name, limit))
            rows = cur.fetchall()

        # RealDictCursor returns dicts
        return [{
            "id": row["id"],
            "flag_name": row["flag_name"],
            "action": row["action"],
            "old_value": row["old_value"],
            "new_value": row["new_value"],
            "changed_by": row["changed_by"],
            "change_reason": row["change_reason"],
            "changed_at": row["changed_at"].isoformat() if row["changed_at"] else None,
        } for row in rows]
    except Exception as e:
        log_with_context(logger, "error", f"Failed to get flag history: {e}")
        return []


# Decorator for feature-flagged functions
def feature_flag(flag_name: str, default: bool = False):
    """Decorator to conditionally execute a function based on feature flag.

    Usage:
        @feature_flag("experimental_search")
        def enhanced_search():
            # Only runs if flag is enabled
            pass
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            if is_enabled(flag_name, default):
                return func(*args, **kwargs)
            return None
        wrapper.__name__ = func.__name__
        wrapper.__doc__ = func.__doc__
        return wrapper
    return decorator
