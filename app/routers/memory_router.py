"""Memory, profile, and context endpoints."""
from __future__ import annotations

from typing import Optional, Dict, Any, List

from fastapi import APIRouter, Request, Depends, HTTPException
from pydantic import BaseModel

from ..observability import get_logger
from ..auth import auth_dependency
from ..tracing import get_current_user_id
from .. import memory_service

logger = get_logger("jarvis.memory_router")
router = APIRouter()


class AutonomySettingsRequest(BaseModel):
    level: str  # low | medium | high
    focus_areas: Optional[List[str]] = None
    notify: bool = True


class TimezoneSettingRequest(BaseModel):
    timezone: str  # IANA tz, e.g., Europe/Zurich


# =============================================================================
# PHASE 16.4C: MEMORY SYSTEM
# =============================================================================

@router.post("/memory/timeline", response_model=Dict[str, Any])
async def add_timeline_event_endpoint(
    req: Dict[str, Any],
    request: Request = None
):
    """Add an event to the personal timeline."""
    request_id = getattr(request.state, "request_id", "unknown") if request else "unknown"

    try:
        from datetime import date as date_type

        event_date = None
        if req.get("event_date"):
            event_date = date_type.fromisoformat(req["event_date"])

        event_id = await memory_service.add_timeline_event(
            user_id=req.get("user_id", get_current_user_id()),
            event_type=req.get("event_type", "note"),
            title=req.get("title", ""),
            description=req.get("description"),
            event_date=event_date,
            event_time=req.get("event_time"),
            category=req.get("category"),
            importance=req.get("importance", 3),
            related_entities=req.get("related_entities"),
            source_type=req.get("source_type"),
            source_id=req.get("source_id"),
            tags=req.get("tags"),
            is_private=req.get("is_private", False)
        )

        if event_id:
            return {"status": "success", "event_id": event_id, "request_id": request_id}

        return {"status": "error", "error": "Failed to add event", "request_id": request_id}

    except Exception as e:
        logger.error(f"Failed to add timeline event: {e}")
        return {"status": "error", "error": str(e), "request_id": request_id}


@router.get("/memory/timeline", response_model=Dict[str, Any])
async def get_timeline_endpoint(
    user_id: str = "micha",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    event_type: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = 50,
    request: Request = None
):
    """Get timeline events."""
    request_id = getattr(request.state, "request_id", "unknown") if request else "unknown"

    try:
        from datetime import date as date_type

        start = date_type.fromisoformat(start_date) if start_date else None
        end = date_type.fromisoformat(end_date) if end_date else None

        events = await memory_service.get_timeline(
            user_id=user_id,
            start_date=start,
            end_date=end,
            event_type=event_type,
            category=category,
            limit=limit
        )

        return {
            "status": "success",
            "count": len(events),
            "events": events,
            "request_id": request_id
        }

    except Exception as e:
        logger.error(f"Failed to get timeline: {e}")
        return {"status": "error", "error": str(e), "events": [], "request_id": request_id}


@router.post("/memory/preferences/learn", response_model=Dict[str, Any])
async def learn_preference_endpoint(
    req: Dict[str, Any],
    request: Request = None
):
    """Learn or update a user preference."""
    request_id = getattr(request.state, "request_id", "unknown") if request else "unknown"

    try:
        success = await memory_service.learn_preference(
            user_id=req.get("user_id", get_current_user_id()),
            key=req.get("key"),
            value=req.get("value"),
            category=req.get("category"),
            source=req.get("source")
        )

        return {"status": "success" if success else "error", "key": req.get("key"), "request_id": request_id}

    except Exception as e:
        logger.error(f"Failed to learn preference: {e}")
        return {"status": "error", "error": str(e), "request_id": request_id}


@router.get("/memory/preferences", response_model=Dict[str, Any])
async def get_preferences_endpoint(
    user_id: str = "micha",
    category: Optional[str] = None,
    min_confidence: float = 0.3,
    request: Request = None
):
    """Get learned preferences."""
    request_id = getattr(request.state, "request_id", "unknown") if request else "unknown"

    try:
        preferences = await memory_service.get_all_preferences(
            user_id=user_id,
            category=category,
            min_confidence=min_confidence
        )

        return {
            "status": "success",
            "count": len(preferences),
            "preferences": preferences,
            "request_id": request_id
        }

    except Exception as e:
        logger.error(f"Failed to get preferences: {e}")
        return {"status": "error", "error": str(e), "preferences": [], "request_id": request_id}


@router.post("/memory/preferences/confirm", response_model=Dict[str, Any])
async def confirm_preference_endpoint(
    user_id: str = "micha",
    key: str = None,
    request: Request = None
):
    """Explicitly confirm a preference (increases confidence)."""
    request_id = getattr(request.state, "request_id", "unknown") if request else "unknown"

    if not key:
        return {"status": "error", "error": "Preference key required", "request_id": request_id}

    try:
        success = await memory_service.confirm_preference(
            user_id=user_id,
            key=key,
            source="user_confirmation"
        )

        return {
            "status": "success" if success else "not_found",
            "key": key,
            "confirmed": success,
            "request_id": request_id
        }

    except Exception as e:
        logger.error(f"Failed to confirm preference: {e}")
        return {"status": "error", "error": str(e), "request_id": request_id}


@router.post("/memory/preferences/contradict", response_model=Dict[str, Any])
async def contradict_preference_endpoint(
    user_id: str = "micha",
    key: str = None,
    new_value: Optional[str] = None,
    request: Request = None
):
    """Explicitly contradict a preference (decreases confidence or replaces value)."""
    request_id = getattr(request.state, "request_id", "unknown") if request else "unknown"

    if not key:
        return {"status": "error", "error": "Preference key required", "request_id": request_id}

    try:
        success = await memory_service.contradict_preference(
            user_id=user_id,
            key=key,
            new_value=new_value,
            source="user_contradiction"
        )

        return {
            "status": "success" if success else "not_found",
            "key": key,
            "contradicted": success,
            "new_value": new_value,
            "request_id": request_id
        }

    except Exception as e:
        logger.error(f"Failed to contradict preference: {e}")
        return {"status": "error", "error": str(e), "request_id": request_id}


# =============================================================================
# AUTONOMY + TIMEZONE SETTINGS
# =============================================================================


@router.post("/memory/settings/autonomy", response_model=Dict[str, Any])
async def set_autonomy_settings_endpoint(
    req: AutonomySettingsRequest,
    user_id: Optional[str] = None,
    request: Request = None
):
    """Persist autonomy preferences (used for proactive behavior tuning)."""
    request_id = getattr(request.state, "request_id", "unknown") if request else "unknown"

    try:
        await memory_service.learn_preference(
            user_id=user_id,
            key="autonomy.level",
            value=req.level,
            category="autonomy",
            source="user_setting"
        )
        if req.focus_areas is not None:
            await memory_service.learn_preference(
                user_id=user_id,
                key="autonomy.focus_areas",
                value=",".join(req.focus_areas),
                category="autonomy",
                source="user_setting"
            )
        await memory_service.learn_preference(
            user_id=user_id,
            key="autonomy.notify",
            value="true" if req.notify else "false",
            category="autonomy",
            source="user_setting"
        )

        return {
            "status": "success",
            "settings": req.dict(),
            "request_id": request_id
        }
    except Exception as e:
        logger.error(f"Failed to set autonomy settings: {e}")
        return {"status": "error", "error": str(e), "request_id": request_id}


@router.get("/memory/settings/autonomy", response_model=Dict[str, Any])
async def get_autonomy_settings_endpoint(
    user_id: Optional[str] = None,
    request: Request = None
):
    """Get stored autonomy preferences."""
    request_id = getattr(request.state, "request_id", "unknown") if request else "unknown"

    try:
        level = await memory_service.get_preference(user_id=user_id, key="autonomy.level")
        focus = await memory_service.get_preference(user_id=user_id, key="autonomy.focus_areas")
        notify = await memory_service.get_preference(user_id=user_id, key="autonomy.notify")

        focus_list = []
        if focus and focus.get("value"):
            focus_list = [f.strip() for f in str(focus.get("value")).split(",") if f.strip()]

        return {
            "status": "success",
            "settings": {
                "level": level.get("value") if level else None,
                "focus_areas": focus_list,
                "notify": (notify.get("value") == "true") if notify else True
            },
            "request_id": request_id
        }
    except Exception as e:
        logger.error(f"Failed to get autonomy settings: {e}")
        return {"status": "error", "error": str(e), "request_id": request_id}


@router.post("/memory/settings/timezone", response_model=Dict[str, Any])
async def set_timezone_endpoint(
    req: TimezoneSettingRequest,
    user_id: Optional[str] = None,
    request: Request = None
):
    """Persist user's preferred timezone (IANA name)."""
    request_id = getattr(request.state, "request_id", "unknown") if request else "unknown"

    try:
        await memory_service.learn_preference(
            user_id=user_id,
            key="timezone",
            value=req.timezone,
            category="preferences",
            source="user_setting"
        )

        return {
            "status": "success",
            "timezone": req.timezone,
            "request_id": request_id
        }
    except Exception as e:
        logger.error(f"Failed to set timezone preference: {e}")
        return {"status": "error", "error": str(e), "request_id": request_id}


@router.get("/memory/settings/timezone", response_model=Dict[str, Any])
async def get_timezone_endpoint(
    user_id: Optional[str] = None,
    request: Request = None
):
    """Get user's preferred timezone."""
    request_id = getattr(request.state, "request_id", "unknown") if request else "unknown"

    try:
        tz_pref = await memory_service.get_preference(user_id=user_id, key="timezone")
        return {
            "status": "success",
            "timezone": tz_pref.get("value") if tz_pref else None,
            "request_id": request_id
        }
    except Exception as e:
        logger.error(f"Failed to get timezone preference: {e}")
        return {"status": "error", "error": str(e), "request_id": request_id}


@router.post("/memory/preferences/decay", response_model=Dict[str, Any])
async def decay_preferences_endpoint(
    user_id: str = "micha",
    days_threshold: int = 60,
    request: Request = None
):
    """Decay stale preferences not confirmed recently."""
    request_id = getattr(request.state, "request_id", "unknown") if request else "unknown"

    try:
        decayed_count = await memory_service.decay_stale_preferences(
            user_id=user_id,
            days_threshold=days_threshold
        )

        return {
            "status": "success",
            "decayed_count": decayed_count,
            "days_threshold": days_threshold,
            "request_id": request_id
        }

    except Exception as e:
        logger.error(f"Failed to decay preferences: {e}")
        return {"status": "error", "error": str(e), "request_id": request_id}


@router.get("/memory/patterns", response_model=Dict[str, Any])
async def get_patterns_endpoint(
    user_id: str = "micha",
    pattern_type: Optional[str] = None,
    min_confidence: float = 0.4,
    request: Request = None
):
    """Get detected behavioral patterns."""
    request_id = getattr(request.state, "request_id", "unknown") if request else "unknown"

    try:
        patterns = await memory_service.get_active_patterns(
            user_id=user_id,
            pattern_type=pattern_type,
            min_confidence=min_confidence
        )

        return {
            "status": "success",
            "count": len(patterns),
            "patterns": patterns,
            "request_id": request_id
        }

    except Exception as e:
        logger.error(f"Failed to get patterns: {e}")
        return {"status": "error", "error": str(e), "patterns": [], "request_id": request_id}


@router.post("/memory/patterns/detect", response_model=Dict[str, Any])
async def trigger_pattern_detection(
    user_id: str = "micha",
    days_back: int = 30,
    request: Request = None
):
    """Trigger pattern detection job manually."""
    request_id = getattr(request.state, "request_id", "unknown") if request else "unknown"

    try:
        from ..jobs.pattern_detector import detect_patterns_daily

        patterns = detect_patterns_daily(user_id=user_id, days_back=days_back)

        return {
            "status": "success",
            "patterns_detected": len(patterns),
            "patterns": [
                {
                    "type": p["pattern_type"],
                    "description": p["description"],
                    "confidence": p["confidence"]
                }
                for p in patterns
            ],
            "request_id": request_id
        }

    except Exception as e:
        logger.error(f"Pattern detection failed: {e}")
        return {"status": "error", "error": str(e), "request_id": request_id}


@router.get("/memory/quality", response_model=Dict[str, Any])
async def get_interaction_quality_endpoint(
    days: int = 30,
    request: Request = None
):
    """Get interaction quality summary."""
    request_id = getattr(request.state, "request_id", "unknown") if request else "unknown"

    try:
        summary = await memory_service.get_quality_summary(days=days)

        return {"status": "success", **summary, "request_id": request_id}

    except Exception as e:
        logger.error(f"Failed to get quality summary: {e}")
        return {"status": "error", "error": str(e), "request_id": request_id}


@router.get("/memory/relationships/{person_name}", response_model=Dict[str, Any])
async def get_relationship_note_endpoint(
    person_name: str,
    user_id: str = "micha",
    request: Request = None
):
    """Get notes about a person."""
    request_id = getattr(request.state, "request_id", "unknown") if request else "unknown"

    try:
        note = await memory_service.get_relationship_note(
            user_id=user_id,
            person_name=person_name
        )

        if note:
            return {"status": "success", "person": note, "request_id": request_id}

        return {"status": "not_found", "message": f"No notes found for {person_name}", "request_id": request_id}

    except Exception as e:
        logger.error(f"Failed to get relationship note: {e}")
        return {"status": "error", "error": str(e), "request_id": request_id}


@router.get("/memory/vip", response_model=Dict[str, Any])
async def get_vip_contacts_endpoint(
    user_id: str = "micha",
    request: Request = None
):
    """Get VIP contacts."""
    request_id = getattr(request.state, "request_id", "unknown") if request else "unknown"

    try:
        contacts = await memory_service.get_vip_contacts(user_id=user_id)

        return {"status": "success", "count": len(contacts), "vip_contacts": contacts, "request_id": request_id}

    except Exception as e:
        logger.error(f"Failed to get VIP contacts: {e}")
        return {"status": "error", "error": str(e), "vip_contacts": [], "request_id": request_id}


# =============================================================================
# MEMORY STORE (FACTS / ENTITIES)
# =============================================================================


@router.get("/memory/stats")
def memory_stats():
    """Get memory store statistics"""
    from .. import memory_store
    return memory_store.get_memory_stats()


@router.get("/memory/facts")
def get_facts(category: Optional[str] = None, query: Optional[str] = None, limit: int = 50):
    """List stored facts with optional filters"""
    from .. import memory_store
    facts = memory_store.get_facts(category=category, query=query, limit=limit)
    return {"facts": facts, "count": len(facts)}


@router.post("/memory/facts")
def add_fact(fact: str, category: str):
    """Add a new fact to memory"""
    from .. import memory_store
    fact_id = memory_store.add_fact(fact, category)
    return {"fact_id": fact_id, "status": "stored"}


@router.get("/memory/entities")
def get_entities(entity_type: Optional[str] = None, limit: int = 50):
    """List stored entities"""
    from .. import memory_store
    entities = memory_store.get_entities(entity_type=entity_type, limit=limit)
    return {"entities": entities, "count": len(entities)}


@router.post("/memory/facts/decay")
def decay_facts_endpoint(
    min_days: int = 14,
    decay_rate: float = 0.05,
    limit: int = 100,
    dry_run: bool = False
):
    """Apply time-based decay to facts that haven't been accessed recently."""
    from .. import memory_store
    result = memory_store.decay_facts(
        min_days_since_accessed=min_days,
        decay_rate=decay_rate,
        limit=limit,
        dry_run=dry_run
    )
    return result


@router.get("/memory/facts/mature")
def get_mature_facts_endpoint(
    min_trust: float = 0.5,
    min_access_count: int = 5,
    min_age_days: int = 7,
    limit: int = 50
):
    """Get facts that are mature enough for migration to permanent config."""
    from .. import memory_store
    facts = memory_store.get_mature_facts(
        min_trust_score=min_trust,
        min_access_count=min_access_count,
        min_age_days=min_age_days
    )
    facts = facts[:limit]
    return {
        "mature_facts": facts,
        "count": len(facts),
        "criteria": {
            "min_trust": min_trust,
            "min_access_count": min_access_count,
            "min_age_days": min_age_days
        }
    }


@router.get("/memory/trust-distribution")
def get_trust_distribution():
    """Get distribution of trust scores across all active facts."""
    from .. import memory_store
    distribution = memory_store.get_trust_score_distribution()
    return {"distribution": distribution}


@router.post("/memory/threads/migrate")
def migrate_thread_state():
    """Migrate thread_state from SQLite to PostgreSQL active_context_buffer."""
    from .. import session_manager
    result = session_manager.migrate_thread_state_to_postgres()
    return result


@router.get("/context/threads")
def get_context_threads(
    user_id: int = None,
    status: str = None,
    include_closed: bool = False
):
    """Get thread states for a user from the consolidated PostgreSQL store."""
    from .. import session_manager

    if user_id:
        threads = session_manager.get_thread_states(user_id, status=status, include_closed=include_closed)
    else:
        from .. import postgres_state
        with postgres_state.get_cursor() as cur:
            query = "SELECT * FROM active_context_buffer"
            if status:
                pg_status = session_manager._status_to_postgres(status)
                query += f" WHERE status = '{pg_status}'"
            elif not include_closed:
                query += " WHERE status NOT IN ('completed', 'evicted')"

            cur.execute(query)
            threads = cur.fetchall()

    return {"threads": threads, "count": len(threads)}


# =============================================================================
# Coach OS: User Profile Endpoints
# =============================================================================


class UserProfileUpdate(BaseModel):
    communication_style: Optional[str] = None
    response_length: Optional[str] = None
    language: Optional[str] = None
    adhd_mode: Optional[bool] = None
    chunk_size: Optional[str] = None
    reminder_frequency: Optional[str] = None
    energy_awareness: Optional[bool] = None
    default_energy_level: Optional[str] = None
    coaching_areas: Optional[list] = None
    active_coaching_mode: Optional[str] = None
    timezone: Optional[str] = None


@router.get("/profile/{telegram_id}")
def get_user_profile_endpoint(telegram_id: int):
    """Get user profile by Telegram ID"""
    from .. import knowledge_db

    profile = knowledge_db.get_user_profile(telegram_id=telegram_id)
    if not profile:
        return {"error": "Profile not found", "telegram_id": telegram_id}

    result = dict(profile)
    for key in ["created_at", "updated_at"]:
        if result.get(key):
            result[key] = str(result[key])

    return result


@router.post("/profile/{telegram_id}")
def create_or_get_profile(telegram_id: int, name: str = None):
    """Get or create user profile for a Telegram user"""
    from .. import knowledge_db

    profile = knowledge_db.get_or_create_user_profile(
        telegram_id=telegram_id,
        name=name
    )

    result = dict(profile)
    for key in ["created_at", "updated_at"]:
        if result.get(key):
            result[key] = str(result[key])

    return result


@router.put("/profile/{user_id}/settings")
def update_user_profile_endpoint(
    user_id: int,
    updates: UserProfileUpdate,
    changed_by: str = "api",
    change_reason: str = None
):
    """Update user profile settings"""
    from .. import knowledge_db

    update_dict = {k: v for k, v in updates.dict().items() if v is not None}

    if not update_dict:
        return {"success": False, "error": "No updates provided"}

    success = knowledge_db.update_user_profile(
        user_id=user_id,
        updates=update_dict,
        changed_by=changed_by,
        change_reason=change_reason
    )

    return {"success": success, "updated_fields": list(update_dict.keys())}


@router.get("/profile/{user_id}/history")
def get_profile_history_endpoint(user_id: int, limit: int = 10):
    """Get version history for user profile"""
    from .. import knowledge_db

    history = knowledge_db.get_user_profile_history(user_id=user_id, limit=limit)

    for entry in history:
        if entry.get("created_at"):
            entry["created_at"] = str(entry["created_at"])

    return {"history": history, "count": len(history)}


@router.get("/profile/{user_id}/coaching")
def get_coaching_context_endpoint(user_id: int):
    """Get complete coaching context for a user"""
    from .. import knowledge_db

    context = knowledge_db.get_coaching_context(user_id=user_id)

    if context.get("profile"):
        for key in ["created_at", "updated_at"]:
            if context["profile"].get(key):
                context["profile"][key] = str(context["profile"][key])

    return context


@router.post("/profile/{user_id}/feedback")
def record_feedback_endpoint(
    user_id: int,
    feedback_type: str,
    message_id: str = None,
    conversation_id: str = None,
    context: dict = None
):
    """Record user feedback for learning."""
    from .. import knowledge_db

    feedback_id = knowledge_db.record_user_feedback(
        user_id=user_id,
        feedback_type=feedback_type,
        context=context,
        message_id=message_id,
        conversation_id=conversation_id
    )

    return {"success": feedback_id is not None, "feedback_id": feedback_id}


@router.get("/profile/{user_id}/feedback/stats")
def get_feedback_stats_endpoint(user_id: int):
    """Get aggregated feedback stats for a user"""
    from .. import knowledge_db

    stats = knowledge_db.get_user_feedback_stats(user_id=user_id)
    return {"user_id": user_id, "stats": stats}


@router.post("/profile/{user_id}/adhd")
def toggle_adhd_mode(user_id: int, enabled: bool):
    """Quick toggle for ADHD mode"""
    from .. import knowledge_db

    success = knowledge_db.update_user_profile(
        user_id=user_id,
        updates={"adhd_mode": enabled},
        changed_by="api",
        change_reason="ADHD mode toggle"
    )

    return {"success": success, "adhd_mode": enabled}


@router.post("/profile/{user_id}/coaching_mode")
def set_coaching_mode(user_id: int, mode: str):
    """Set active coaching mode."""
    from .. import knowledge_db

    valid_modes = ["coach", "analyst", "exec", "debug", "mirror"]
    if mode not in valid_modes:
        return {"success": False, "error": f"Invalid mode. Must be one of: {valid_modes}"}

    success = knowledge_db.update_user_profile(
        user_id=user_id,
        updates={"active_coaching_mode": mode},
        changed_by="api",
        change_reason=f"Coaching mode changed to {mode}"
    )

    return {"success": success, "active_coaching_mode": mode}


# =============================================================================
# SESSION SNAPSHOTS (Consciousness Continuity - T-018)
# =============================================================================


@router.get("/memory/snapshot/{user_id}")
def get_user_snapshot(
    user_id: str,
    auth: bool = Depends(auth_dependency)
):
    """
    Get latest session snapshot for a user.

    Session snapshots capture the state at the end of each agent run,
    enabling consciousness continuity across sessions.

    Returns facette weights, mood, energy level, last query, etc.
    """
    try:
        from .. import config as cfg
        from ..memory import MemoryStore
        import redis

        redis_client = redis.Redis(host=cfg.REDIS_HOST, port=cfg.REDIS_PORT, db=0)
        store = MemoryStore(redis_client)
        snapshot = store.get_latest_snapshot(user_id)

        if not snapshot:
            raise HTTPException(status_code=404, detail=f"No snapshot found for user {user_id}")

        return snapshot.to_dict()

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get snapshot for {user_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get snapshot: {str(e)}")


@router.get("/memory/snapshot/{user_id}/history")
def get_user_snapshot_history(
    user_id: str,
    limit: int = 10,
    auth: bool = Depends(auth_dependency)
):
    """
    Get session snapshot history for a user.

    Returns the most recent snapshots (up to limit) for tracking
    facette evolution and session patterns over time.
    """
    try:
        from .. import config as cfg
        from ..memory import MemoryStore
        import redis

        redis_client = redis.Redis(host=cfg.REDIS_HOST, port=cfg.REDIS_PORT, db=0)
        store = MemoryStore(redis_client)
        snapshots = store.get_user_snapshot_history(user_id, limit=limit)

        return {
            "user_id": user_id,
            "count": len(snapshots),
            "snapshots": [s.to_dict() for s in snapshots]
        }

    except Exception as e:
        logger.error(f"Failed to get snapshot history for {user_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get snapshot history: {str(e)}")
