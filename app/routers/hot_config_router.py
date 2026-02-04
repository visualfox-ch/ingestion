"""Hot Config API Endpoints

Micha's 4 Ideas (Feb 3, 2026): Hot Config Reload
Allows changing performance thresholds and behavior settings at runtime
without requiring a Jarvis restart.

Endpoints:
- GET /admin/config/hot - List all hot config values
- GET /admin/config/hot/schema - Get schema with descriptions
- GET /admin/config/hot/{key} - Get single value
- PATCH /admin/config/hot - Update single value
- POST /admin/config/hot/reload - Force cache refresh

Author: Claude Code
Created: 2026-02-03
"""
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..observability import get_logger
from ..auth import auth_dependency
from .. import hot_config

logger = get_logger("jarvis.hot_config_router")
router = APIRouter(prefix="/admin/config", tags=["Admin Config"])


# =============================================================================
# PYDANTIC MODELS
# =============================================================================

class HotConfigUpdate(BaseModel):
    """Request model for updating a hot config value."""
    key: str = Field(..., description="Config key to update")
    value: Any = Field(..., description="New value (type must match schema)")
    reason: Optional[str] = Field(None, max_length=500, description="Reason for change (audit)")


class HotConfigResponse(BaseModel):
    """Response model for a single hot config value."""
    key: str
    value: Any
    type: str
    default: Any
    description: str


class HotConfigUpdateResponse(BaseModel):
    """Response model after updating a config value."""
    key: str
    old_value: Any
    new_value: Any
    changed_at: str
    changed_by: str


class HotConfigAllResponse(BaseModel):
    """Response model for all hot config values."""
    config: Dict[str, Any]
    last_reload: Optional[str] = None


class HotConfigSchemaEntry(BaseModel):
    """Schema entry for a single config key."""
    type: str
    default: Any
    description: str
    current: Any


class HotConfigReloadResponse(BaseModel):
    """Response model after forcing cache reload."""
    config: Dict[str, Any]
    reloaded_at: str


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get("/hot", response_model=HotConfigAllResponse)
def get_all_config(
    auth: bool = Depends(auth_dependency)
):
    """Get all current hot config values."""
    return HotConfigAllResponse(
        config=hot_config.get_all_hot_config()
    )


@router.get("/hot/schema", response_model=Dict[str, HotConfigSchemaEntry])
def get_config_schema(
    auth: bool = Depends(auth_dependency)
):
    """Get hot config schema with types, defaults, and descriptions."""
    return hot_config.get_hot_config_schema()


@router.get("/hot/{key}", response_model=HotConfigResponse)
def get_single_config(
    key: str,
    auth: bool = Depends(auth_dependency)
):
    """Get a single hot config value by key."""
    schema = hot_config.HOT_CONFIG_SCHEMA.get(key)
    if not schema:
        valid_keys = list(hot_config.HOT_CONFIG_SCHEMA.keys())
        raise HTTPException(
            status_code=404,
            detail=f"Config key '{key}' not found. Valid keys: {valid_keys}"
        )

    return HotConfigResponse(
        key=key,
        value=hot_config.get_hot_config(key),
        type=schema["type"],
        default=schema["default"],
        description=schema["description"]
    )


@router.patch("/hot", response_model=HotConfigUpdateResponse)
def update_config(
    request: HotConfigUpdate,
    auth: bool = Depends(auth_dependency)
):
    """Update a single hot config value (hot-reload, no restart required).

    Validates value against schema before updating.
    Changes are persisted to database and take effect immediately.
    """
    try:
        result = hot_config.set_hot_config(
            key=request.key,
            value=request.value,
            changed_by="api",
            reason=request.reason
        )
        return HotConfigUpdateResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/hot/reload", response_model=HotConfigReloadResponse)
def reload_config(
    auth: bool = Depends(auth_dependency)
):
    """Force reload all hot config from database.

    Clears the feature_flags cache to force immediate reload.
    Use this after manual database changes or to verify persistence.
    """
    result = hot_config.reload_hot_config()
    return HotConfigReloadResponse(**result)


# =============================================================================
# CONVENIENCE ENDPOINTS
# =============================================================================

@router.get("/hot/facette-weights")
def get_facette_weights(
    auth: bool = Depends(auth_dependency)
):
    """Get all facette weights as a convenience endpoint."""
    return {
        "weights": hot_config.get_facette_weights(),
        "description": "Personality facette blend weights (sum should be ~1.0)"
    }


@router.patch("/hot/facette-weights")
def update_facette_weights(
    analytical: Optional[float] = None,
    empathic: Optional[float] = None,
    pragmatic: Optional[float] = None,
    creative: Optional[float] = None,
    auth: bool = Depends(auth_dependency)
):
    """Update multiple facette weights at once.

    Only provided weights are updated. Validates each weight is 0.0-1.0.
    """
    updates = {}

    if analytical is not None:
        updates["analytical"] = hot_config.set_hot_config(
            "facette_weight_analytical", analytical, "api", "Facette weights batch update"
        )
    if empathic is not None:
        updates["empathic"] = hot_config.set_hot_config(
            "facette_weight_empathic", empathic, "api", "Facette weights batch update"
        )
    if pragmatic is not None:
        updates["pragmatic"] = hot_config.set_hot_config(
            "facette_weight_pragmatic", pragmatic, "api", "Facette weights batch update"
        )
    if creative is not None:
        updates["creative"] = hot_config.set_hot_config(
            "facette_weight_creative", creative, "api", "Facette weights batch update"
        )

    if not updates:
        raise HTTPException(status_code=400, detail="No weights provided to update")

    return {
        "updated": updates,
        "current_weights": hot_config.get_facette_weights()
    }


@router.get("/hot/proactive")
def get_proactive_settings(
    auth: bool = Depends(auth_dependency)
):
    """Get proactivity settings as a convenience endpoint."""
    return {
        "level": hot_config.get_proactive_level(),
        "max_per_day": hot_config.get_proactive_max_per_day(),
        "description": "Proactivity dial (1=silent, 3=balanced, 5=proactive)"
    }


@router.get("/hot/agent")
def get_agent_settings(
    auth: bool = Depends(auth_dependency)
):
    """Get agent execution settings as a convenience endpoint."""
    return {
        "max_rounds": hot_config.get_agent_max_rounds(),
        "timeout_seconds": hot_config.get_agent_timeout_seconds(),
        "description": "Agent tool loop limits"
    }
