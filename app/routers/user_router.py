"""
User Router

Extracted from main.py - User profile and preferences endpoints:
- Notification preferences
- User profile management
- Goals management
- Profile snapshots
"""

from fastapi import APIRouter, Request
from pydantic import BaseModel
from typing import Dict, Any, List, Optional

from ..observability import get_logger

logger = get_logger("jarvis.user")
router = APIRouter(prefix="/user", tags=["user"])


# =============================================================================
# PYDANTIC MODELS
# =============================================================================

class UpdatePreferencesRequest(BaseModel):
    """Request body for updating notification preferences."""
    telegram_enabled: Optional[bool] = None
    email_enabled: Optional[bool] = None
    dashboard_enabled: Optional[bool] = None
    quiet_hours_enabled: Optional[bool] = None
    quiet_hours_start: Optional[str] = None
    quiet_hours_end: Optional[str] = None
    max_notifications_per_hour: Optional[int] = None
    max_notifications_per_day: Optional[int] = None


class UpdateUserProfileRequest(BaseModel):
    """Request for updating user profile"""
    display_name: Optional[str] = None
    roles: Optional[List[str]] = None
    communication_prefs: Optional[dict] = None
    work_prefs: Optional[dict] = None
    adhd_patterns: Optional[dict] = None
    boundaries: Optional[dict] = None
    what_works: Optional[List[str]] = None
    what_fails: Optional[List[str]] = None


class AddGoalRequest(BaseModel):
    """Request for adding a goal"""
    title: str
    priority: int = 3
    deadline: Optional[str] = None
    namespace: Optional[str] = None
    goal_type: str = "current"  # "current" or "long_term"


# =============================================================================
# NOTIFICATION PREFERENCES
# =============================================================================

@router.get("/notification-preferences", response_model=Dict[str, Any])
async def get_user_preferences_endpoint(
    user_id: str = "micha",
    request: Request = None
):
    """
    Get user notification preferences.

    Phase 16.4B: Settings page data.
    """
    from ..services.notification_service import notification_service

    request_id = getattr(request.state, 'request_id', 'unknown') if request else 'unknown'

    try:
        prefs = await notification_service.get_user_preferences(user_id)

        return {
            "status": "success",
            "user_id": user_id,
            "preferences": prefs,
            "request_id": request_id
        }

    except Exception as e:
        logger.error(f"Failed to get user preferences: {e}")
        return {
            "status": "error",
            "error": str(e),
            "request_id": request_id
        }


@router.put("/notification-preferences", response_model=Dict[str, Any])
async def update_user_preferences_endpoint(
    req: UpdatePreferencesRequest,
    user_id: str = "micha",
    request: Request = None
):
    """
    Update user notification preferences.

    Phase 16.4B: Settings page update.
    """
    from ..services.notification_service import notification_service

    request_id = getattr(request.state, 'request_id', 'unknown') if request else 'unknown'

    try:
        success = await notification_service.update_user_preferences(
            user_id=user_id,
            telegram_enabled=req.telegram_enabled,
            email_enabled=req.email_enabled,
            dashboard_enabled=req.dashboard_enabled,
            quiet_hours_enabled=req.quiet_hours_enabled,
            quiet_hours_start=req.quiet_hours_start,
            quiet_hours_end=req.quiet_hours_end,
            max_notifications_per_hour=req.max_notifications_per_hour,
            max_notifications_per_day=req.max_notifications_per_day
        )

        if success:
            return {
                "status": "success",
                "message": "Preferences updated",
                "request_id": request_id
            }
        else:
            return {
                "status": "error",
                "error": "Failed to update preferences",
                "request_id": request_id
            }

    except Exception as e:
        logger.error(f"Failed to update user preferences: {e}")
        return {
            "status": "error",
            "error": str(e),
            "request_id": request_id
        }


# =============================================================================
# USER PROFILE
# =============================================================================

@router.get("/profile")
def get_user_profile_endpoint(profile_id: str = "micha"):
    """
    Get the comprehensive user profile.
    Much richer than external person profiles.
    """
    from .. import knowledge_db
    profile = knowledge_db.get_jarvis_user_profile(profile_id)
    if not profile:
        profile = knowledge_db.ensure_user_profile(profile_id)
    return {"profile": profile}


@router.get("/profile/for-prompt")
def get_user_profile_for_prompt_endpoint(profile_id: str = "micha"):
    """Get user profile formatted for prompt injection."""
    from .. import knowledge_db
    prompt_text = knowledge_db.get_user_profile_for_prompt(profile_id)
    return {"prompt_injection": prompt_text, "length": len(prompt_text)}


@router.post("/profile")
def update_user_profile_endpoint(req: UpdateUserProfileRequest, profile_id: str = "micha"):
    """
    Update user profile fields.
    JSONB fields are merged with existing data.
    """
    from .. import knowledge_db

    result = knowledge_db.update_user_profile(
        profile_id=profile_id,
        display_name=req.display_name,
        roles=req.roles,
        communication_prefs=req.communication_prefs,
        work_prefs=req.work_prefs,
        adhd_patterns=req.adhd_patterns,
        boundaries=req.boundaries,
        what_works=req.what_works,
        what_fails=req.what_fails
    )

    if not result:
        return {"status": "error", "message": "Failed to update profile"}
    return {"status": "updated", "profile": result}


@router.post("/profile/snapshot")
def create_user_snapshot(profile_id: str = "micha", reason: str = "manual"):
    """Create a snapshot of the current user profile."""
    from .. import knowledge_db

    snapshot_id = knowledge_db.create_user_profile_snapshot(profile_id, reason)
    if snapshot_id:
        return {"status": "created", "snapshot_id": snapshot_id}
    return {"status": "error", "message": "Failed to create snapshot"}


# =============================================================================
# GOALS
# =============================================================================

@router.post("/goals")
def add_user_goal_endpoint(req: AddGoalRequest, profile_id: str = "micha"):
    """Add a goal to the user profile."""
    from .. import knowledge_db

    goal = knowledge_db.add_user_goal(
        title=req.title,
        priority=req.priority,
        deadline=req.deadline,
        namespace=req.namespace,
        goal_type=req.goal_type,
        profile_id=profile_id
    )
    return {"status": "added", "goal": goal}


@router.post("/goals/{goal_id}/complete")
def complete_user_goal_endpoint(goal_id: str, profile_id: str = "micha"):
    """Mark a goal as completed."""
    from .. import knowledge_db

    success = knowledge_db.complete_user_goal(goal_id, profile_id)
    if success:
        return {"status": "completed", "goal_id": goal_id}
    return {"status": "error", "message": "Goal not found or already completed"}


@router.get("/goals")
def list_user_goals(profile_id: str = "micha"):
    """List current user goals."""
    from .. import knowledge_db

    profile = knowledge_db.get_jarvis_user_profile(profile_id)
    if not profile:
        return {"current_goals": [], "long_term_goals": []}

    return {
        "current_goals": profile.get("current_goals", []),
        "long_term_goals": profile.get("long_term_goals", [])
    }
