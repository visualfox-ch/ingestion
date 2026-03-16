"""
Live Config Router - Phase B

API endpoints for runtime configuration management.
Allows changing Jarvis behavior without code deployment.
"""
from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, Optional, List

from ..observability import get_logger, log_with_context

logger = get_logger("jarvis.config_router")
router = APIRouter(prefix="/config", tags=["config"])


class ConfigUpdate(BaseModel):
    """Request body for updating config."""
    value: Any
    updated_by: Optional[str] = "api"


# =============================================================================
# GET ENDPOINTS
# =============================================================================

@router.get("/")
def get_all_config(category: Optional[str] = None):
    """
    Get all configuration values.

    Args:
        category: Filter by category (diagnostics, proactive, memory, tools, etc.)
    """
    from ..live_config import get_live_config

    config = get_live_config()

    return {
        "values": config.get_all(category),
        "category_filter": category,
        "total": len(config.get_all(category))
    }


@router.get("/full")
def get_all_config_full(category: Optional[str] = None):
    """
    Get all configuration values with full metadata.
    """
    from ..live_config import get_live_config

    config = get_live_config()

    return {
        "values": config.get_all_full(category),
        "category_filter": category
    }


@router.get("/schema")
def get_config_schema():
    """
    Get the configuration schema.

    Shows all available config keys, their types, defaults, and descriptions.
    """
    from ..live_config import get_live_config

    config = get_live_config()

    return {
        "schema": config.get_schema(),
        "categories": config.get_categories()
    }


@router.get("/categories")
def get_config_categories():
    """Get list of config categories."""
    from ..live_config import get_live_config

    config = get_live_config()
    categories = config.get_categories()

    # Count items per category
    all_config = config.get_all_full()
    counts = {}
    for key, val in all_config.items():
        cat = val["category"]
        counts[cat] = counts.get(cat, 0) + 1

    return {
        "categories": [
            {"name": cat, "count": counts.get(cat, 0)}
            for cat in sorted(categories)
        ]
    }


@router.get("/history")
def get_config_history(
    key: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=500)
):
    """
    Get configuration change history.

    Args:
        key: Filter by specific config key
        limit: Max number of history entries
    """
    from ..live_config import get_live_config

    config = get_live_config()

    return {
        "history": config.get_history(key, limit),
        "key_filter": key,
        "limit": limit
    }


@router.get("/{key}")
def get_config_value(key: str):
    """
    Get a specific configuration value.
    """
    from ..live_config import get_live_config

    config = get_live_config()
    full = config.get_full(key)

    if full is None:
        raise HTTPException(status_code=404, detail=f"Config key '{key}' not found")

    return {
        "key": key,
        "value": full.value,
        "type": full.value_type,
        "category": full.category,
        "description": full.description,
        "default": full.default,
        "updated_at": full.updated_at,
        "updated_by": full.updated_by
    }


# =============================================================================
# SET ENDPOINTS
# =============================================================================

@router.put("/{key}")
def set_config_value(key: str, update: ConfigUpdate):
    """
    Set a configuration value.

    Changes take effect immediately without restart.

    Example:
        PUT /config/proactive_level
        {"value": 3, "updated_by": "micha"}
    """
    from ..live_config import get_live_config

    config = get_live_config()

    # Check if key exists
    if config.get_full(key) is None:
        raise HTTPException(status_code=404, detail=f"Config key '{key}' not found")

    success = config.set(key, update.value, updated_by=update.updated_by or "api")

    if not success:
        raise HTTPException(status_code=400, detail="Failed to set config value")

    log_with_context(logger, "info", "Config updated via API",
                    key=key, value=update.value, by=update.updated_by)

    return {
        "status": "success",
        "key": key,
        "value": update.value,
        "message": f"Config '{key}' updated. Change is active immediately."
    }


@router.post("/{key}/reset")
def reset_config_value(key: str, updated_by: str = "api"):
    """
    Reset a configuration value to its default.
    """
    from ..live_config import get_live_config

    config = get_live_config()

    if config.get_full(key) is None:
        raise HTTPException(status_code=404, detail=f"Config key '{key}' not found")

    success = config.reset_to_default(key, updated_by=updated_by)

    if not success:
        raise HTTPException(status_code=400, detail="Failed to reset config value")

    new_value = config.get(key)

    return {
        "status": "success",
        "key": key,
        "value": new_value,
        "message": f"Config '{key}' reset to default"
    }


@router.post("/reset-all")
def reset_all_config(updated_by: str = "api"):
    """
    Reset ALL configuration values to defaults.

    Use with caution!
    """
    from ..live_config import get_live_config

    config = get_live_config()
    count = config.reset_all(updated_by=updated_by)

    log_with_context(logger, "warning", "All config reset to defaults",
                    count=count, by=updated_by)

    return {
        "status": "success",
        "reset_count": count,
        "message": "All configuration values reset to defaults"
    }


# =============================================================================
# BATCH OPERATIONS
# =============================================================================

@router.post("/batch")
def set_config_batch(updates: Dict[str, Any], updated_by: str = "api"):
    """
    Set multiple configuration values at once.

    Example:
        POST /config/batch?updated_by=micha
        {
            "proactive_level": 3,
            "memory_auto_persist": false,
            "tool_timeout_ms": 60000
        }
    """
    from ..live_config import get_live_config

    config = get_live_config()
    results = {"success": [], "failed": []}

    for key, value in updates.items():
        if config.set(key, value, updated_by=updated_by):
            results["success"].append(key)
        else:
            results["failed"].append(key)

    log_with_context(logger, "info", "Batch config update",
                    success_count=len(results["success"]),
                    failed_count=len(results["failed"]),
                    by=updated_by)

    return {
        "status": "partial" if results["failed"] else "success",
        "results": results
    }


# =============================================================================
# CATEGORY-BASED OPERATIONS
# =============================================================================

@router.get("/by-category/{category}")
def get_config_by_category(category: str):
    """
    Get all config values in a specific category.
    """
    from ..live_config import get_live_config

    config = get_live_config()
    values = config.get_all_full(category)

    if not values:
        raise HTTPException(status_code=404, detail=f"Category '{category}' not found or empty")

    return {
        "category": category,
        "values": values,
        "count": len(values)
    }
