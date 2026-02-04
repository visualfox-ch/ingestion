"""Feature Flags CRUD Endpoints

Phase 18.3: Infrastructure Hardening
- List, create, update, delete feature flags
- Hot-reload without restart
- Audit history tracking
"""
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..observability import get_logger
from ..auth import auth_dependency
from .. import feature_flags

logger = get_logger("jarvis.feature_flags_router")
router = APIRouter(prefix="/flags", tags=["Feature Flags"])


# =============================================================================
# PYDANTIC MODELS
# =============================================================================

class FlagCreate(BaseModel):
    """Request model for creating a new feature flag."""
    flag_name: str = Field(..., min_length=1, max_length=100, description="Unique flag name (snake_case)")
    description: str = Field("", max_length=500, description="Human-readable description")
    category: str = Field("general", max_length=50, description="Category for grouping flags")
    enabled: bool = Field(False, description="Initial enabled state")
    rollout_percent: int = Field(100, ge=0, le=100, description="Percentage of users to enable for (0-100)")


class FlagUpdate(BaseModel):
    """Request model for updating a feature flag."""
    enabled: Optional[bool] = Field(None, description="Enable/disable the flag")
    rollout_percent: Optional[int] = Field(None, ge=0, le=100, description="Rollout percentage (0-100)")
    description: Optional[str] = Field(None, max_length=500, description="Update description")
    kill_switch: Optional[bool] = Field(None, description="Emergency kill-switch (overrides enabled)")
    change_reason: Optional[str] = Field(None, max_length=500, description="Reason for change (audit)")


class FlagResponse(BaseModel):
    """Response model for a feature flag."""
    id: int
    flag_name: str
    enabled: bool
    rollout_percent: int
    description: Optional[str]
    category: str
    version: int
    kill_switch: bool
    created_at: Optional[str]
    updated_at: Optional[str]
    enabled_at: Optional[str] = None
    disabled_at: Optional[str] = None


class FlagHistoryEntry(BaseModel):
    """Response model for a history entry."""
    id: int
    flag_name: str
    action: str
    old_value: Optional[dict]
    new_value: Optional[dict]
    changed_by: str
    change_reason: Optional[str]
    changed_at: str


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get("", response_model=List[FlagResponse])
def list_flags(
    category: Optional[str] = None,
    auth: bool = Depends(auth_dependency)
):
    """List all feature flags, optionally filtered by category."""
    flags = feature_flags.list_flags(category=category)
    return [FlagResponse(**f) for f in flags]


@router.get("/{flag_name}", response_model=FlagResponse)
def get_flag(
    flag_name: str,
    auth: bool = Depends(auth_dependency)
):
    """Get a specific feature flag by name."""
    flag = feature_flags.get_flag(flag_name)
    if not flag:
        raise HTTPException(status_code=404, detail=f"Flag '{flag_name}' not found")
    return FlagResponse(**flag)


@router.post("", response_model=FlagResponse, status_code=201)
def create_flag(
    request: FlagCreate,
    auth: bool = Depends(auth_dependency)
):
    """Create a new feature flag."""
    try:
        flag = feature_flags.create_flag(
            flag_name=request.flag_name,
            description=request.description,
            category=request.category,
            enabled=request.enabled,
            rollout_percent=request.rollout_percent,
            changed_by="api"
        )
        if flag is None:
            raise HTTPException(status_code=500, detail="Flag created but could not be retrieved")
        return FlagResponse(**flag)
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        logger.error(f"Flag creation failed: {type(e).__name__}: {e}\n{traceback.format_exc()}")
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            raise HTTPException(status_code=409, detail=f"Flag '{request.flag_name}' already exists")
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {str(e)}")


@router.patch("/{flag_name}", response_model=FlagResponse)
def update_flag(
    flag_name: str,
    request: FlagUpdate,
    auth: bool = Depends(auth_dependency)
):
    """Update a feature flag (hot-reload, no restart required)."""
    flag = feature_flags.update_flag(
        flag_name=flag_name,
        enabled=request.enabled,
        rollout_percent=request.rollout_percent,
        description=request.description,
        kill_switch=request.kill_switch,
        changed_by="api",
        change_reason=request.change_reason
    )
    if not flag:
        raise HTTPException(status_code=404, detail=f"Flag '{flag_name}' not found")
    return FlagResponse(**flag)


@router.delete("/{flag_name}", status_code=204)
def delete_flag(
    flag_name: str,
    auth: bool = Depends(auth_dependency)
):
    """Delete a feature flag."""
    if not feature_flags.delete_flag(flag_name, changed_by="api"):
        raise HTTPException(status_code=404, detail=f"Flag '{flag_name}' not found")


@router.get("/{flag_name}/history", response_model=List[FlagHistoryEntry])
def get_flag_history(
    flag_name: str,
    limit: int = 50,
    auth: bool = Depends(auth_dependency)
):
    """Get change history for a feature flag (audit trail)."""
    history = feature_flags.get_flag_history(flag_name, limit=limit)
    return [FlagHistoryEntry(**h) for h in history]


@router.post("/{flag_name}/enable", response_model=FlagResponse)
def enable_flag(
    flag_name: str,
    reason: Optional[str] = None,
    auth: bool = Depends(auth_dependency)
):
    """Quick enable a feature flag."""
    flag = feature_flags.update_flag(
        flag_name=flag_name,
        enabled=True,
        changed_by="api",
        change_reason=reason or "Quick enable via API"
    )
    if not flag:
        raise HTTPException(status_code=404, detail=f"Flag '{flag_name}' not found")
    return FlagResponse(**flag)


@router.post("/{flag_name}/disable", response_model=FlagResponse)
def disable_flag(
    flag_name: str,
    reason: Optional[str] = None,
    auth: bool = Depends(auth_dependency)
):
    """Quick disable a feature flag."""
    flag = feature_flags.update_flag(
        flag_name=flag_name,
        enabled=False,
        changed_by="api",
        change_reason=reason or "Quick disable via API"
    )
    if not flag:
        raise HTTPException(status_code=404, detail=f"Flag '{flag_name}' not found")
    return FlagResponse(**flag)


@router.post("/{flag_name}/kill", response_model=FlagResponse)
def kill_flag(
    flag_name: str,
    reason: Optional[str] = None,
    auth: bool = Depends(auth_dependency)
):
    """Emergency kill-switch - immediately disables flag regardless of other settings."""
    flag = feature_flags.update_flag(
        flag_name=flag_name,
        kill_switch=True,
        changed_by="api_emergency",
        change_reason=reason or "Emergency kill-switch activated"
    )
    if not flag:
        raise HTTPException(status_code=404, detail=f"Flag '{flag_name}' not found")
    return FlagResponse(**flag)


@router.post("/{flag_name}/revive", response_model=FlagResponse)
def revive_flag(
    flag_name: str,
    reason: Optional[str] = None,
    auth: bool = Depends(auth_dependency)
):
    """Remove kill-switch from a flag."""
    flag = feature_flags.update_flag(
        flag_name=flag_name,
        kill_switch=False,
        changed_by="api",
        change_reason=reason or "Kill-switch removed"
    )
    if not flag:
        raise HTTPException(status_code=404, detail=f"Flag '{flag_name}' not found")
    return FlagResponse(**flag)


# =============================================================================
# UTILITY ENDPOINTS
# =============================================================================

@router.get("/check/{flag_name}")
def check_flag(
    flag_name: str,
    user_id: Optional[int] = None,
    default: bool = False
):
    """Check if a flag is enabled (public endpoint for client-side checks).

    Does not require authentication for easy client integration.
    """
    is_enabled = feature_flags.is_enabled(flag_name, default=default, user_id=user_id)
    return {
        "flag_name": flag_name,
        "enabled": is_enabled,
        "user_id": user_id
    }
