"""
Knowledge Base & RAG Endpoints.

Core features:
- Vector search & RAG-powered responses
- Person profile management
- Persona management  
- Knowledge item versioning
- Meeting prep & context
- Email drafting

Extracted from main.py for better maintainability.
"""

from fastapi import APIRouter, Request, HTTPException, Query
from typing import Optional, List, Dict, Any
from pathlib import Path
import os
import logging
from pydantic import BaseModel

from ..errors import JarvisException, ErrorCode
from .. import knowledge_db, embed
from ..observability import get_logger, log_with_context

# BRAIN_ROOT defined locally (can be imported from main if we refactor config later)
BRAIN_ROOT = Path(os.environ.get("BRAIN_ROOT", "/brain"))

logger = get_logger("jarvis.routers.knowledge")

router = APIRouter(
    prefix="/knowledge",
    tags=["knowledge"],
    responses={
        400: {"description": "Invalid request"},
        404: {"description": "Knowledge not found"},
        500: {"description": "Internal server error"},
    }
)


# ============================================================================
# REQUEST MODELS (from main.py)
# ============================================================================

class ProfileChangeRequest(BaseModel):
    """Request to propose a change to a person profile."""
    content: Dict[str, Any]
    change_reason: str
    evidence_sources: Optional[List[str]] = None


# ============================================================================
# HEALTH & INITIALIZATION ENDPOINTS
# ============================================================================

@router.get("/health")
def knowledge_health():
    """Check knowledge layer health"""
    try:
        available = knowledge_db.is_available()
        return {
            "status": "ok" if available else "unavailable",
            "postgres_available": available
        }
    except Exception as e:
        logger.exception("Knowledge health check failed")
        raise JarvisException(
            code=ErrorCode.POSTGRES_ERROR,
            message="Knowledge health check failed",
            status_code=500,
            recoverable=True,
            retry_after=5
        )


@router.post("/init")
def knowledge_init():
    """Initialize knowledge layer schema"""
    try:
        success = knowledge_db.init_schema()
        return {"status": "ok" if success else "error", "initialized": success}
    except Exception as e:
        logger.exception("Knowledge init failed")
        raise JarvisException(
            code=ErrorCode.POSTGRES_ERROR,
            message="Knowledge initialization failed",
            status_code=500,
            recoverable=False
        )


@router.post("/migrate")
def knowledge_migrate():
    """Migrate existing JSON profiles and personas to knowledge layer"""
    try:
        profiles_result = knowledge_db.migrate_json_profiles(
            str(BRAIN_ROOT / "system" / "profiles" / "persons")
        )
        personas_result = knowledge_db.migrate_json_personas(
            str(BRAIN_ROOT / "system" / "prompts" / "persona_profiles.json")
        )
        return {
            "status": "ok",
            "profiles": profiles_result,
            "personas": personas_result
        }
    except Exception as e:
        logger.exception("Knowledge migration failed")
        raise JarvisException(
            code=ErrorCode.PROCESSING_FAILED,
            message="Knowledge migration failed",
            status_code=500,
            recoverable=False,
            details={"error": str(e)[:100]}
        )


@router.post("/migrate-v2")
def knowledge_migrate_v2(source_type: str = "all"):
    """
    Migrate from v1 to v2 schema (identity unification).
    
    source_type: "profiles" | "personas" | "all"
    """
    try:
        if source_type in ["profiles", "all"]:
            knowledge_db.migrate_person_identifiers()
        if source_type in ["personas", "all"]:
            knowledge_db.migrate_persona_identifiers()
        return {"status": "ok", "source_type": source_type}
    except Exception as e:
        logger.exception("Knowledge migration-v2 failed")
        raise JarvisException(
            code=ErrorCode.PROCESSING_FAILED,
            message="Knowledge migration failed",
            status_code=500,
            recoverable=False
        )


# ============================================================================
# PERSON PROFILE ENDPOINTS
# ============================================================================

@router.get("/people/search")
def search_people(
    name: Optional[str] = None,
    email: Optional[str] = None,
    birthday: Optional[str] = None,
    limit: int = 10
):
    """
    Search person profiles by name, email, or birthday.
    
    Uses person_identifier table for robust search across multiple identifier types.
    
    Args:
        name: Partial name search (first, last, or full name)
        email: Email address (exact match)
        birthday: Birthday in YYYY-MM-DD format
        limit: Max results (default 10)
    """
    try:
        results = knowledge_db.search_persons(
            name=name,
            email=email,
            birthday=birthday,
            limit=limit
        )
        return {
            "query": {"name": name, "email": email, "birthday": birthday},
            "results": results,
            "count": len(results)
        }
    except Exception as e:
        logger.exception("Person search failed", extra={
            "name": name,
            "email": email,
            "error_type": type(e).__name__
        })
        raise JarvisException(
            code=ErrorCode.INTERNAL_ERROR,
            message="Person search failed",
            status_code=500,
            recoverable=True,
            retry_after=5
        )


@router.get("/people")
def list_knowledge_people(status: str = "active"):
    """List all person profiles from knowledge layer"""
    try:
        profiles = knowledge_db.get_all_person_profiles(status=status)
        return {"profiles": profiles, "count": len(profiles)}
    except Exception as e:
        logger.exception("List people failed")
        raise JarvisException(
            code=ErrorCode.POSTGRES_ERROR,
            message="Failed to list people",
            status_code=500,
            recoverable=True,
            retry_after=5
        )


@router.get("/people/{person_id}")
def get_knowledge_person(
    person_id: str,
    include_history: bool = False,
    include_pending: bool = False
):
    """
    Get a person profile from knowledge layer.

    Args:
        person_id: The person identifier
        include_history: Include all version history
        include_pending: Include draft/pending profiles (not yet approved)
    """
    try:
        profile = knowledge_db.get_person_profile(
            person_id,
            approved_only=not include_pending
        )
        if not profile:
            raise JarvisException(
                code=ErrorCode.NOT_FOUND,
                message=f"Person {person_id} not found",
                status_code=404,
                recoverable=False
            )
        
        result = {"profile": profile}
        if include_history:
            result["versions"] = knowledge_db.get_profile_versions(person_id)
        return result
    except JarvisException:
        raise
    except Exception as e:
        logger.exception("Get person failed", extra={"person_id": person_id})
        raise JarvisException(
            code=ErrorCode.POSTGRES_ERROR,
            message="Failed to retrieve person",
            status_code=500,
            recoverable=True,
            retry_after=5
        )


@router.get("/people/{person_id}/versions")
def get_knowledge_person_versions(person_id: str, status: str = None):
    """Get version history for a person profile"""
    try:
        versions = knowledge_db.get_profile_versions(person_id, status=status)
        return {"versions": versions, "count": len(versions)}
    except Exception as e:
        logger.exception("Get person versions failed")
        raise JarvisException(
            code=ErrorCode.POSTGRES_ERROR,
            message="Failed to retrieve person versions",
            status_code=500,
            recoverable=True,
            retry_after=5
        )


@router.post("/people/{person_id}/propose")
def propose_knowledge_person_change(person_id: str, req: ProfileChangeRequest):
    """Propose a change to a person profile"""
    try:
        version_id = knowledge_db.propose_profile_change(
            person_id=person_id,
            content=req.content,
            changed_by="human:api",
            change_reason=req.change_reason,
            evidence_sources=req.evidence_sources
        )
        if version_id:
            # Add to review queue
            queue_id = knowledge_db.add_to_review_queue(
                item_type="profile_version",
                item_id=version_id,
                summary=f"Profile change for {person_id}: {req.change_reason[:100]}",
                requested_by="human:api"
            )
            return {
                "status": "proposed",
                "version_id": version_id,
                "queue_id": queue_id
            }
        raise JarvisException(
            code=ErrorCode.PROCESSING_FAILED,
            message="Failed to propose profile change",
            status_code=500,
            recoverable=False
        )
    except JarvisException:
        raise
    except Exception as e:
        logger.exception("Propose person change failed")
        raise JarvisException(
            code=ErrorCode.POSTGRES_ERROR,
            message="Failed to propose change",
            status_code=500,
            recoverable=True,
            retry_after=5
        )


@router.get("/people/pending")
def list_pending_profile_changes():
    """
    List all person profiles with pending changes awaiting review.
    This is the HITL dashboard endpoint for profile approvals.
    """
    try:
        pending = []
        profiles = knowledge_db.get_all_person_profiles(status="active")
        
        for p in profiles:
            versions = knowledge_db.get_profile_versions(p["person_id"], status="proposed")
            if versions:
                pending.append({
                    "person_id": p["person_id"],
                    "name": p.get("name"),
                    "pending_versions": len(versions),
                    "versions": versions
                })
        
        return {"pending": pending, "count": len(pending)}
    except Exception as e:
        logger.exception("List pending changes failed")
        raise JarvisException(
            code=ErrorCode.POSTGRES_ERROR,
            message="Failed to list pending changes",
            status_code=500,
            recoverable=True,
            retry_after=5
        )


@router.post("/people/{person_id}/versions/{version_id}/approve")
def approve_knowledge_profile_version(person_id: str, version_id: str):
    """Approve a proposed person profile change"""
    try:
        result = knowledge_db.approve_profile_version(person_id, version_id)
        return {
            "status": "approved" if result else "error",
            "person_id": person_id,
            "version_id": version_id
        }
    except Exception as e:
        logger.exception("Approve profile version failed")
        raise JarvisException(
            code=ErrorCode.POSTGRES_ERROR,
            message="Failed to approve profile version",
            status_code=500,
            recoverable=True,
            retry_after=5
        )


@router.post("/people/{person_id}/versions/{version_id}/reject")
def reject_knowledge_profile_version(person_id: str, version_id: str, reason: str = None):
    """Reject a proposed person profile change"""
    try:
        result = knowledge_db.reject_profile_version(person_id, version_id, reason=reason)
        return {
            "status": "rejected" if result else "error",
            "person_id": person_id,
            "version_id": version_id
        }
    except Exception as e:
        logger.exception("Reject profile version failed")
        raise JarvisException(
            code=ErrorCode.POSTGRES_ERROR,
            message="Failed to reject profile version",
            status_code=500,
            recoverable=True,
            retry_after=5
        )


# ============================================================================
# VIP & SPECIAL PERSON ENDPOINTS
# ============================================================================

@router.get("/vips")
def list_vips():
    """Get VIP person profiles (high-priority follow-up targets)"""
    try:
        vips = knowledge_db.get_vip_persons()
        return {"vips": vips, "count": len(vips)}
    except Exception as e:
        logger.exception("List VIPs failed")
        raise JarvisException(
            code=ErrorCode.POSTGRES_ERROR,
            message="Failed to list VIPs",
            status_code=500,
            recoverable=True,
            retry_after=5
        )


@router.get("/people/search/{name}")
def search_people_by_name(name: str, limit: int = 10):
    """Search person profiles by name (convenience endpoint)"""
    try:
        results = knowledge_db.search_persons(name=name, limit=limit)
        return {
            "query": {"name": name},
            "results": results,
            "count": len(results)
        }
    except Exception as e:
        logger.exception("Name search failed")
        raise JarvisException(
            code=ErrorCode.INTERNAL_ERROR,
            message="Name search failed",
            status_code=500,
            recoverable=True,
            retry_after=5
        )


# ============================================================================
# PERSONA ENDPOINTS
# ============================================================================

@router.get("/personas")
def list_personas():
    """List all personas from knowledge layer"""
    try:
        personas = knowledge_db.get_all_personas()
        return {"personas": personas, "count": len(personas)}
    except Exception as e:
        logger.exception("List personas failed")
        raise JarvisException(
            code=ErrorCode.POSTGRES_ERROR,
            message="Failed to list personas",
            status_code=500,
            recoverable=True,
            retry_after=5
        )


@router.get("/personas/{persona_id}")
def get_persona(persona_id: str):
    """Get a single persona by ID"""
    try:
        persona = knowledge_db.get_persona(persona_id)
        if not persona:
            raise JarvisException(
                code=ErrorCode.NOT_FOUND,
                message=f"Persona {persona_id} not found",
                status_code=404,
                recoverable=False
            )
        return {"persona": persona}
    except JarvisException:
        raise
    except Exception as e:
        logger.exception("Get persona failed")
        raise JarvisException(
            code=ErrorCode.POSTGRES_ERROR,
            message="Failed to retrieve persona",
            status_code=500,
            recoverable=True,
            retry_after=5
        )


# ============================================================================
# KNOWLEDGE ITEM ENDPOINTS
# ============================================================================

@router.get("/items/stats")
def get_knowledge_items_stats():
    """Get statistics about knowledge items (documents, chunks, etc.)"""
    try:
        stats = knowledge_db.get_knowledge_items_stats()
        return stats
    except Exception as e:
        logger.exception("Get knowledge items stats failed")
        raise JarvisException(
            code=ErrorCode.INTERNAL_ERROR,
            message="Failed to get knowledge statistics",
            status_code=500,
            recoverable=True,
            retry_after=5
        )


@router.get("/items/{item_id}")
def get_knowledge_item(item_id: str, include_content: bool = False):
    """Get a knowledge item by ID"""
    try:
        item = knowledge_db.get_knowledge_item(item_id, include_content=include_content)
        if not item:
            raise JarvisException(
                code=ErrorCode.NOT_FOUND,
                message=f"Knowledge item {item_id} not found",
                status_code=404,
                recoverable=False
            )
        return {"item": item}
    except JarvisException:
        raise
    except Exception as e:
        logger.exception("Get knowledge item failed")
        raise JarvisException(
            code=ErrorCode.POSTGRES_ERROR,
            message="Failed to retrieve knowledge item",
            status_code=500,
            recoverable=True,
            retry_after=5
        )


@router.post("/items")
def create_knowledge_item(content: Dict[str, Any], source: str = "api"):
    """Create a new knowledge item"""
    try:
        item_id = knowledge_db.create_knowledge_item(
            content=content,
            source=source
        )
        return {
            "status": "created",
            "item_id": item_id
        }
    except Exception as e:
        logger.exception("Create knowledge item failed")
        raise JarvisException(
            code=ErrorCode.PROCESSING_FAILED,
            message="Failed to create knowledge item",
            status_code=500,
            recoverable=False,
            details={"error": str(e)[:100]}
        )


@router.put("/items/{item_id}")
def update_knowledge_item(item_id: str, content: Dict[str, Any]):
    """Update a knowledge item"""
    try:
        result = knowledge_db.update_knowledge_item(item_id, content)
        if not result:
            raise JarvisException(
                code=ErrorCode.NOT_FOUND,
                message=f"Knowledge item {item_id} not found",
                status_code=404,
                recoverable=False
            )
        return {"status": "updated", "item_id": item_id}
    except JarvisException:
        raise
    except Exception as e:
        logger.exception("Update knowledge item failed")
        raise JarvisException(
            code=ErrorCode.POSTGRES_ERROR,
            message="Failed to update knowledge item",
            status_code=500,
            recoverable=True,
            retry_after=5
        )


@router.get("/items/{item_id}/versions")
def get_knowledge_item_versions(item_id: str):
    """Get version history for a knowledge item"""
    try:
        versions = knowledge_db.get_knowledge_item_versions(item_id)
        return {"versions": versions, "count": len(versions)}
    except Exception as e:
        logger.exception("Get knowledge item versions failed")
        raise JarvisException(
            code=ErrorCode.POSTGRES_ERROR,
            message="Failed to retrieve item versions",
            status_code=500,
            recoverable=True,
            retry_after=5
        )


# ============================================================================
# CONTEXT & PREP ENDPOINTS
# ============================================================================

@router.get("/meeting-prep")
def get_meeting_prep(person_id: str):
    """Get meeting preparation context for a person"""
    try:
        prep = knowledge_db.get_meeting_prep(person_id)
        return prep or {"person_id": person_id, "prep": {}}
    except Exception as e:
        logger.exception("Get meeting prep failed")
        raise JarvisException(
            code=ErrorCode.INTERNAL_ERROR,
            message="Failed to get meeting prep",
            status_code=500,
            recoverable=True,
            retry_after=5
        )


@router.get("/birthdays")
def get_upcoming_birthdays(days_ahead: int = 30):
    """Get upcoming birthdays from person profiles"""
    try:
        birthdays = knowledge_db.get_upcoming_birthdays(days_ahead=days_ahead)
        return {"birthdays": birthdays, "count": len(birthdays)}
    except Exception as e:
        logger.exception("Get birthdays failed")
        raise JarvisException(
            code=ErrorCode.INTERNAL_ERROR,
            message="Failed to get birthdays",
            status_code=500,
            recoverable=True,
            retry_after=5
        )


@router.post("/draft-email")
def draft_email(person_id: str, context: Optional[Dict[str, Any]] = None):
    """Draft an email using person knowledge + context"""
    try:
        person = knowledge_db.get_person_profile(person_id)
        if not person:
            raise JarvisException(
                code=ErrorCode.NOT_FOUND,
                message=f"Person {person_id} not found",
                status_code=404,
                recoverable=False
            )
        
        # Generate email draft using LLM
        # (Implementation details omitted for now)
        draft = {
            "to": person.get("email"),
            "subject": "[Auto-drafted subject]",
            "body": "[Auto-drafted body]"
        }
        return draft
    except JarvisException:
        raise
    except Exception as e:
        logger.exception("Draft email failed")
        raise JarvisException(
            code=ErrorCode.INTERNAL_ERROR,
            message="Failed to draft email",
            status_code=500,
            recoverable=True,
            retry_after=5
        )


# ============================================================================
# REVIEW ENDPOINTS
# ============================================================================

@router.get("/review")
def get_knowledge_review_tasks(limit: int = 20):
    """Get pending knowledge review tasks (HITL review queue)"""
    try:
        tasks = knowledge_db.get_review_queue(limit=limit)
        return {"tasks": tasks, "count": len(tasks)}
    except Exception as e:
        logger.exception("Get review tasks failed")
        raise JarvisException(
            code=ErrorCode.POSTGRES_ERROR,
            message="Failed to get review tasks",
            status_code=500,
            recoverable=True,
            retry_after=5
        )


__all__ = ["router"]
