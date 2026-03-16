"""
Memory Maintenance Router

API endpoints for memory maintenance UI integration:
- Self-Healing operations
- Decay policy management
- Archive management
- Maintenance scheduling
- Health monitoring

All endpoints under /memory/maintenance/
"""

import logging
from datetime import datetime
from typing import List, Optional, Any, Dict

from fastapi import APIRouter, HTTPException, Query, Body, BackgroundTasks
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/memory/maintenance", tags=["memory-maintenance"])


# =============================================================================
# Request/Response Models
# =============================================================================

# Health Check Models
class HealthCheckRequest(BaseModel):
    """Request for health check."""
    item_id: str
    content: str
    memory_type: str = "fact"
    confidence: float = Field(0.5, ge=0, le=1)
    created_at: Optional[str] = None
    last_accessed: Optional[str] = None
    access_count: int = 0
    source: str = "unknown"
    tags: List[str] = []
    metadata: Dict[str, Any] = {}


class HealthCheckResponse(BaseModel):
    """Response from health check."""
    item_id: str
    status: str
    issues: List[str]
    repairs_needed: List[str]
    can_auto_repair: bool


class RepairRequest(BaseModel):
    """Request to repair an item."""
    item: HealthCheckRequest
    auto_repair: bool = True


class RepairResponse(BaseModel):
    """Response from repair operation."""
    item_id: str
    repaired: bool
    actions_taken: List[str]
    new_item: Optional[Dict[str, Any]] = None


# Decay Models
class DecayPolicyRequest(BaseModel):
    """Request to set decay policy."""
    policy: str = Field(..., description="aggressive, moderate, conservative, none, custom")
    custom_config: Optional[Dict[str, float]] = Field(None, description="Custom config for 'custom' policy")


class DecaySimulationRequest(BaseModel):
    """Request for decay simulation."""
    items: List[HealthCheckRequest]
    days_forward: int = Field(30, ge=1, le=365)


class DecayCalculationRequest(BaseModel):
    """Request to calculate decay for an item."""
    item: HealthCheckRequest


class DecayResponse(BaseModel):
    """Response from decay calculation."""
    item_id: str
    original_confidence: float
    new_confidence: float
    decay_applied: float
    should_archive: bool
    reason: Optional[str]


# Archive Models
class ArchiveRequest(BaseModel):
    """Request to archive an item."""
    item: HealthCheckRequest
    reason: str = Field(..., description="low_confidence, stale, unused, superseded, user_request, contradiction, duplicate")


class ArchiveResponse(BaseModel):
    """Response from archive operation."""
    item_id: str
    archived: bool
    reason: str
    archived_at: str
    can_restore: bool


class RestoreRequest(BaseModel):
    """Request to restore an archived item."""
    archive_id: str


# Maintenance Models
class MaintenanceRequest(BaseModel):
    """Request for maintenance run."""
    items: List[HealthCheckRequest]
    apply_decay: bool = True
    apply_healing: bool = True
    apply_archive: bool = True
    dry_run: bool = False


class MaintenanceResponse(BaseModel):
    """Response from maintenance run."""
    run_id: str
    started_at: str
    completed_at: str
    items_scanned: int
    items_decayed: int
    items_archived: int
    items_healed: int
    items_failed: int
    total_confidence_decay: float
    issues_found: List[Dict[str, Any]]
    actions_taken: List[Dict[str, Any]]


# =============================================================================
# Helper Functions
# =============================================================================

def _to_memory_item(req: HealthCheckRequest):
    """Convert request to MemoryItem."""
    from ..services.memory_maintenance import MemoryItem

    return MemoryItem(
        id=req.item_id,
        content=req.content,
        memory_type=req.memory_type,
        confidence=req.confidence,
        created_at=datetime.fromisoformat(req.created_at) if req.created_at else datetime.utcnow(),
        last_accessed=datetime.fromisoformat(req.last_accessed) if req.last_accessed else None,
        access_count=req.access_count,
        source=req.source,
        tags=req.tags,
        metadata=req.metadata,
    )


# =============================================================================
# Health Check Endpoints
# =============================================================================

@router.post("/health/check", response_model=HealthCheckResponse)
async def check_item_health(request: HealthCheckRequest):
    """
    Check health of a single memory item.

    Detects corruption, inconsistencies, and orphaned references.
    """
    try:
        from ..services.memory_maintenance import get_memory_maintenance

        maintenance = get_memory_maintenance()
        item = _to_memory_item(request)

        result = maintenance.healing_engine.check_health(item)

        return HealthCheckResponse(
            item_id=result.item_id,
            status=result.status.value,
            issues=result.issues,
            repairs_needed=result.repairs_needed,
            can_auto_repair=result.can_auto_repair,
        )

    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/health/repair", response_model=RepairResponse)
async def repair_item(request: RepairRequest):
    """
    Attempt to repair a memory item.

    Fixes clamped confidence, invalid dates, orphaned refs, etc.
    """
    try:
        from ..services.memory_maintenance import get_memory_maintenance

        maintenance = get_memory_maintenance()
        item = _to_memory_item(request.item)

        # First check health
        health = maintenance.healing_engine.check_health(item)

        if health.status.value == "healthy":
            return RepairResponse(
                item_id=item.id,
                repaired=False,
                actions_taken=["No repairs needed - item is healthy"],
            )

        if not health.can_auto_repair and request.auto_repair:
            return RepairResponse(
                item_id=item.id,
                repaired=False,
                actions_taken=["Cannot auto-repair - manual intervention needed"],
            )

        # Repair
        repaired_item, actions = maintenance.healing_engine.repair(item, health)

        return RepairResponse(
            item_id=item.id,
            repaired=len(actions) > 0,
            actions_taken=actions,
            new_item={
                "id": repaired_item.id,
                "content": repaired_item.content,
                "confidence": repaired_item.confidence,
                "tags": repaired_item.tags,
            },
        )

    except Exception as e:
        logger.error(f"Repair failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health/statuses")
async def get_health_statuses():
    """Get available health status types."""
    from ..services.memory_maintenance import HealthStatus

    return {
        "statuses": [
            {"name": s.value, "description": {
                "healthy": "No issues detected",
                "degraded": "Minor issues that can be auto-repaired",
                "corrupted": "Serious issues requiring attention",
                "orphaned": "References to non-existent parent items",
            }.get(s.value, "")}
            for s in HealthStatus
        ]
    }


# =============================================================================
# Decay Policy Endpoints
# =============================================================================

@router.get("/decay/policy")
async def get_decay_policy():
    """Get current decay policy configuration."""
    try:
        from ..services.memory_maintenance import get_memory_maintenance

        maintenance = get_memory_maintenance()
        return maintenance.get_decay_policy()

    except Exception as e:
        logger.error(f"Get policy failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/decay/policy")
async def set_decay_policy(request: DecayPolicyRequest):
    """
    Set decay policy.

    Policies:
    - aggressive: 2% daily decay, archive after 30 days
    - moderate: 0.5% daily decay, archive after 90 days
    - conservative: 0.1% daily decay, archive after 365 days
    - none: No automatic decay
    - custom: Provide custom_config with daily_decay_rate, archive_threshold, etc.
    """
    try:
        from ..services.memory_maintenance import get_memory_maintenance, DecayPolicy

        maintenance = get_memory_maintenance()

        try:
            policy = DecayPolicy(request.policy)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid policy. Use: {[p.value for p in DecayPolicy]}"
            )

        if policy == DecayPolicy.CUSTOM and not request.custom_config:
            raise HTTPException(
                status_code=400,
                detail="custom_config required for 'custom' policy"
            )

        maintenance.set_decay_policy(policy, request.custom_config)

        return {
            "status": "updated",
            "policy": policy.value,
            "config": maintenance.get_decay_policy()["config"],
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Set policy failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/decay/policies")
async def get_decay_policies():
    """Get all available decay policies with configurations."""
    from ..services.memory_maintenance import DecayPolicy, DECAY_CONFIGS

    return {
        "policies": [
            {
                "name": p.value,
                "config": DECAY_CONFIGS.get(p, {}),
                "description": {
                    "aggressive": "Fast decay for short-term memories",
                    "moderate": "Balanced decay (recommended)",
                    "conservative": "Slow decay for long-term retention",
                    "none": "No automatic decay",
                    "custom": "User-defined parameters",
                }.get(p.value, ""),
            }
            for p in DecayPolicy
        ]
    }


@router.post("/decay/calculate", response_model=DecayResponse)
async def calculate_decay(request: DecayCalculationRequest):
    """Calculate decay for a single item (doesn't apply it)."""
    try:
        from ..services.memory_maintenance import get_memory_maintenance

        maintenance = get_memory_maintenance()
        item = _to_memory_item(request.item)

        result = maintenance.decay_engine.calculate_decay(item)

        return DecayResponse(
            item_id=result.item_id,
            original_confidence=result.original_confidence,
            new_confidence=result.new_confidence,
            decay_applied=result.decay_applied,
            should_archive=result.should_archive,
            reason=result.reason.value if result.reason else None,
        )

    except Exception as e:
        logger.error(f"Calculate decay failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/decay/simulate")
async def simulate_decay(request: DecaySimulationRequest):
    """
    Simulate decay over time for planning.

    Returns projections of items remaining and avg confidence per day.
    """
    try:
        from ..services.memory_maintenance import get_memory_maintenance

        maintenance = get_memory_maintenance()
        items = [_to_memory_item(req) for req in request.items]

        return maintenance.simulate_maintenance(items, request.days_forward)

    except Exception as e:
        logger.error(f"Simulate decay failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Archive Endpoints
# =============================================================================

@router.post("/archive", response_model=ArchiveResponse)
async def archive_item(request: ArchiveRequest):
    """Archive a memory item."""
    try:
        from ..services.memory_maintenance import get_memory_maintenance, ArchiveReason

        maintenance = get_memory_maintenance()
        item = _to_memory_item(request.item)

        try:
            reason = ArchiveReason(request.reason)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid reason. Use: {[r.value for r in ArchiveReason]}"
            )

        result = maintenance.archive_manager.archive(item, reason)

        return ArchiveResponse(
            item_id=result.item_id,
            archived=result.archived,
            reason=result.reason.value,
            archived_at=result.archived_at.isoformat(),
            can_restore=result.can_restore,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Archive failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/archive/restore")
async def restore_item(request: RestoreRequest):
    """Restore an archived item."""
    try:
        from ..services.memory_maintenance import get_memory_maintenance

        maintenance = get_memory_maintenance()
        item = maintenance.archive_manager.restore(request.archive_id)

        if not item:
            raise HTTPException(status_code=404, detail="Archive not found or cannot be restored")

        return {
            "restored": True,
            "item": {
                "id": item.id,
                "content": item.content[:200],
                "confidence": item.confidence,
                "memory_type": item.memory_type,
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Restore failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/archive/list")
async def list_archived(
    reason: Optional[str] = None,
    days_back: int = Query(30, ge=1, le=365),
    limit: int = Query(100, ge=1, le=500)
):
    """List archived items with optional filters."""
    try:
        from ..services.memory_maintenance import get_memory_maintenance, ArchiveReason

        maintenance = get_memory_maintenance()

        reason_enum = None
        if reason:
            try:
                reason_enum = ArchiveReason(reason)
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid reason. Use: {[r.value for r in ArchiveReason]}"
                )

        items = maintenance.archive_manager.get_archived(reason_enum, days_back, limit)

        return {
            "count": len(items),
            "filters": {"reason": reason, "days_back": days_back},
            "items": items,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"List archived failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/archive/stats")
async def get_archive_stats(days: int = Query(30, ge=1, le=365)):
    """Get archive statistics."""
    try:
        from ..services.memory_maintenance import get_memory_maintenance

        maintenance = get_memory_maintenance()
        return maintenance.archive_manager.get_stats(days)

    except Exception as e:
        logger.error(f"Get stats failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/archive/reasons")
async def get_archive_reasons():
    """Get available archive reasons."""
    from ..services.memory_maintenance import ArchiveReason

    return {
        "reasons": [
            {"name": r.value, "description": {
                "low_confidence": "Confidence dropped below threshold",
                "stale": "Item exceeded maximum age",
                "unused": "Item not accessed for too long",
                "superseded": "Replaced by newer information",
                "user_request": "User requested archival",
                "contradiction": "Contradicted by confirmed info",
                "duplicate": "Duplicate of another item",
            }.get(r.value, "")}
            for r in ArchiveReason
        ]
    }


# =============================================================================
# Maintenance Run Endpoints
# =============================================================================

@router.post("/run", response_model=MaintenanceResponse)
async def run_maintenance(request: MaintenanceRequest):
    """
    Run full maintenance cycle on provided items.

    Operations:
    - Health check and auto-repair
    - Apply confidence decay
    - Archive qualifying items
    """
    try:
        from ..services.memory_maintenance import get_memory_maintenance

        maintenance = get_memory_maintenance()
        items = [_to_memory_item(req) for req in request.items]

        report = maintenance.run_maintenance(
            items=items,
            apply_decay=request.apply_decay,
            apply_healing=request.apply_healing,
            apply_archive=request.apply_archive,
            dry_run=request.dry_run,
        )

        return MaintenanceResponse(
            run_id=report.run_id,
            started_at=report.started_at.isoformat(),
            completed_at=report.completed_at.isoformat(),
            items_scanned=report.items_scanned,
            items_decayed=report.items_decayed,
            items_archived=report.items_archived,
            items_healed=report.items_healed,
            items_failed=report.items_failed,
            total_confidence_decay=report.total_confidence_decay,
            issues_found=report.issues_found,
            actions_taken=report.actions_taken,
        )

    except Exception as e:
        logger.error(f"Maintenance run failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/run/dry")
async def dry_run_maintenance(request: MaintenanceRequest):
    """
    Dry run maintenance - preview actions without making changes.
    """
    request.dry_run = True
    return await run_maintenance(request)


@router.post("/run/background")
async def run_maintenance_background(
    request: MaintenanceRequest,
    background_tasks: BackgroundTasks
):
    """
    Run maintenance in background (non-blocking).

    Returns immediately with job ID.
    """
    from ..services.memory_maintenance import get_memory_maintenance
    import uuid

    job_id = str(uuid.uuid4())[:8]

    def run_bg():
        try:
            maintenance = get_memory_maintenance()
            items = [_to_memory_item(req) for req in request.items]
            maintenance.run_maintenance(
                items=items,
                apply_decay=request.apply_decay,
                apply_healing=request.apply_healing,
                apply_archive=request.apply_archive,
                dry_run=request.dry_run,
            )
            logger.info(f"Background maintenance {job_id} completed")
        except Exception as e:
            logger.error(f"Background maintenance {job_id} failed: {e}")

    background_tasks.add_task(run_bg)

    return {
        "job_id": job_id,
        "status": "started",
        "items_count": len(request.items),
    }


# =============================================================================
# Dashboard / UI Endpoints
# =============================================================================

@router.get("/dashboard")
async def get_maintenance_dashboard():
    """
    Get comprehensive maintenance dashboard data.

    Includes current policy, archive stats, and system health.
    """
    try:
        from ..services.memory_maintenance import get_memory_maintenance

        maintenance = get_memory_maintenance()

        return {
            "decay_policy": maintenance.get_decay_policy(),
            "archive_stats": maintenance.archive_manager.get_stats(30),
            "last_run": maintenance._last_run.isoformat() if maintenance._last_run else None,
            "system": {
                "healing_engine": "active",
                "decay_engine": "active",
                "archive_manager": "active",
            },
        }

    except Exception as e:
        logger.error(f"Dashboard failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ui/config")
async def get_ui_config():
    """
    Get UI configuration for memory maintenance interface.

    Returns form schemas, options, and validation rules.
    """
    from ..services.memory_maintenance import DecayPolicy, ArchiveReason, HealthStatus

    return {
        "decay_policies": [
            {"value": p.value, "label": p.value.title()}
            for p in DecayPolicy
        ],
        "archive_reasons": [
            {"value": r.value, "label": r.value.replace("_", " ").title()}
            for r in ArchiveReason
        ],
        "health_statuses": [
            {"value": s.value, "label": s.value.title()}
            for s in HealthStatus
        ],
        "custom_decay_fields": [
            {"name": "daily_decay_rate", "type": "number", "min": 0, "max": 0.1, "step": 0.001},
            {"name": "archive_threshold", "type": "number", "min": 0, "max": 0.5, "step": 0.01},
            {"name": "stale_days", "type": "number", "min": 1, "max": 365},
            {"name": "unused_days", "type": "number", "min": 1, "max": 365},
        ],
    }


# =============================================================================
# Phase 19.2: Context Sync Endpoints
# =============================================================================

@router.post("/sync-contexts")
async def sync_conversation_contexts(
    hours_back: int = Query(24, description="Hours to look back for sessions"),
    background_tasks: BackgroundTasks = None
):
    """
    Manually trigger synchronization of conversation contexts.

    Processes session_messages and generates conversation_contexts entries.
    This fixes the gap where Jarvis doesn't always call remember_conversation_context.
    """
    try:
        from ..services.auto_context_summarizer import get_auto_context_summarizer

        summarizer = get_auto_context_summarizer()
        stats = summarizer.sync_all_sessions(hours_back=hours_back)

        return {
            "status": "completed",
            "hours_back": hours_back,
            "sessions_synced": stats["synced"],
            "sessions_failed": stats["failed"],
            "sessions_skipped": stats["skipped"],
        }

    except Exception as e:
        logger.error(f"Context sync failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/context-stats")
async def get_context_stats():
    """
    Get statistics about conversation contexts and session messages.

    Shows the gap between raw messages and summarized contexts.
    """
    try:
        import sqlite3
        from datetime import datetime, timedelta

        db_path = "/brain/system/state/jarvis_state.db"
        conn = sqlite3.connect(db_path, timeout=10.0)
        cur = conn.cursor()

        # Session messages stats
        cur.execute("SELECT COUNT(*), COUNT(DISTINCT session_id) FROM session_messages")
        msg_count, msg_sessions = cur.fetchone()

        # Conversation contexts stats
        cur.execute("SELECT COUNT(*), COUNT(DISTINCT session_id) FROM conversation_contexts")
        ctx_count, ctx_sessions = cur.fetchone()

        # Recent activity (last 7 days)
        cutoff = (datetime.utcnow() - timedelta(days=7)).isoformat()
        cur.execute("SELECT COUNT(DISTINCT session_id) FROM session_messages WHERE timestamp > ?", (cutoff,))
        recent_msg_sessions = cur.fetchone()[0]

        cur.execute("SELECT COUNT(DISTINCT session_id) FROM conversation_contexts WHERE start_time > ?", (cutoff,))
        recent_ctx_sessions = cur.fetchone()[0]

        conn.close()

        gap = recent_msg_sessions - recent_ctx_sessions

        return {
            "session_messages": {
                "total_messages": msg_count,
                "unique_sessions": msg_sessions,
                "recent_sessions_7d": recent_msg_sessions,
            },
            "conversation_contexts": {
                "total_contexts": ctx_count,
                "unique_sessions": ctx_sessions,
                "recent_sessions_7d": recent_ctx_sessions,
            },
            "gap": {
                "sessions_without_context": gap,
                "status": "healthy" if gap == 0 else "needs_sync" if gap > 0 else "ok",
            },
        }

    except Exception as e:
        logger.error(f"Context stats failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
