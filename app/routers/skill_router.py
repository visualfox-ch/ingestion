"""
Skill Management Router

API endpoints for managing dynamic skills.
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..services.skill_manager import (
    get_skill_manager,
    SkillValidationError,
    SkillMetadata,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/skills", tags=["skills"])


# =========================================================================
# Request/Response Models
# =========================================================================

class CreateSkillRequest(BaseModel):
    """Request to create a new skill."""
    name: str = Field(..., description="Skill name (lowercase, alphanumeric, underscores)")
    description: str = Field(..., description="What the skill does")
    code: str = Field(..., description="Python code for the execute function body")
    parameters: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="Parameter definitions: [{name, type, description, default?}]"
    )
    tags: Optional[List[str]] = Field(default=None, description="Tags for categorization")
    author: str = Field(default="jarvis", description="Author name")


class ExecuteSkillRequest(BaseModel):
    """Request to execute a skill."""
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Skill parameters")
    timeout: float = Field(default=30.0, ge=1.0, le=120.0, description="Timeout in seconds")


class SkillResponse(BaseModel):
    """Response containing skill metadata."""
    name: str
    description: str
    parameters: List[Dict[str, Any]]
    version: str
    author: str
    tags: List[str]
    enabled: bool
    execution_count: int
    avg_execution_time_ms: float


class ExecutionResultResponse(BaseModel):
    """Response from skill execution."""
    success: bool
    result: Optional[Any] = None
    error: Optional[str] = None
    execution_time_ms: float
    skill_name: str


# =========================================================================
# Endpoints
# =========================================================================

@router.get("/", response_model=List[SkillResponse])
async def list_skills(
    query: Optional[str] = Query(None, description="Search query"),
    tags: Optional[str] = Query(None, description="Comma-separated tags"),
    enabled_only: bool = Query(True, description="Only return enabled skills"),
):
    """List all registered skills."""
    manager = get_skill_manager()

    tag_list = tags.split(",") if tags else None
    skills = manager.search_skills(
        query=query,
        tags=tag_list,
        enabled_only=enabled_only,
    )

    return [
        SkillResponse(
            name=s.name,
            description=s.description,
            parameters=[
                {
                    "name": p.name,
                    "type": p.type,
                    "description": p.description,
                    "required": p.required,
                    "default": p.default,
                }
                for p in s.parameters
            ],
            version=s.version,
            author=s.author,
            tags=s.tags,
            enabled=s.enabled,
            execution_count=s.execution_count,
            avg_execution_time_ms=s.avg_execution_time_ms,
        )
        for s in skills
    ]


@router.get("/health")
async def skills_health():
    """Get skill manager health status."""
    manager = get_skill_manager()
    return manager.get_health_status()


@router.get("/{skill_name}", response_model=SkillResponse)
async def get_skill(skill_name: str):
    """Get details for a specific skill."""
    manager = get_skill_manager()
    skill = manager.get_skill(skill_name)

    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill not found: {skill_name}")

    return SkillResponse(
        name=skill.name,
        description=skill.description,
        parameters=[
            {
                "name": p.name,
                "type": p.type,
                "description": p.description,
                "required": p.required,
                "default": p.default,
            }
            for p in skill.parameters
        ],
        version=skill.version,
        author=skill.author,
        tags=skill.tags,
        enabled=skill.enabled,
        execution_count=skill.execution_count,
        avg_execution_time_ms=skill.avg_execution_time_ms,
    )


@router.post("/", response_model=SkillResponse)
async def create_skill(request: CreateSkillRequest):
    """Create a new skill."""
    manager = get_skill_manager()

    try:
        skill = manager.create_skill(
            name=request.name,
            description=request.description,
            code=request.code,
            parameters=request.parameters,
            tags=request.tags,
            author=request.author,
        )

        return SkillResponse(
            name=skill.name,
            description=skill.description,
            parameters=[
                {
                    "name": p.name,
                    "type": p.type,
                    "description": p.description,
                    "required": p.required,
                    "default": p.default,
                }
                for p in skill.parameters
            ],
            version=skill.version,
            author=skill.author,
            tags=skill.tags,
            enabled=skill.enabled,
            execution_count=skill.execution_count,
            avg_execution_time_ms=skill.avg_execution_time_ms,
        )

    except SkillValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to create skill: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create skill: {e}")


@router.post("/{skill_name}/execute", response_model=ExecutionResultResponse)
async def execute_skill(skill_name: str, request: ExecuteSkillRequest):
    """Execute a skill with given parameters."""
    manager = get_skill_manager()

    result = await manager.execute_skill(
        skill_name=skill_name,
        parameters=request.parameters,
        timeout=request.timeout,
    )

    return ExecutionResultResponse(
        success=result.success,
        result=result.result,
        error=result.error,
        execution_time_ms=result.execution_time_ms,
        skill_name=result.skill_name,
    )


@router.delete("/{skill_name}")
async def delete_skill(skill_name: str):
    """Delete a skill."""
    manager = get_skill_manager()

    if not manager.delete_skill(skill_name):
        raise HTTPException(status_code=404, detail=f"Skill not found: {skill_name}")

    return {"message": f"Skill deleted: {skill_name}"}


@router.post("/{skill_name}/enable")
async def enable_skill(skill_name: str):
    """Enable a disabled skill."""
    manager = get_skill_manager()

    if not manager.enable_skill(skill_name):
        raise HTTPException(status_code=404, detail=f"Skill not found: {skill_name}")

    return {"message": f"Skill enabled: {skill_name}"}


@router.post("/{skill_name}/disable")
async def disable_skill(skill_name: str):
    """Disable a skill without deleting it."""
    manager = get_skill_manager()

    if not manager.disable_skill(skill_name):
        raise HTTPException(status_code=404, detail=f"Skill not found: {skill_name}")

    return {"message": f"Skill disabled: {skill_name}"}


@router.post("/reload")
async def reload_skills():
    """Reload all skills from disk."""
    manager = get_skill_manager()
    count = manager.reload_all()
    return {"message": f"Reloaded {count} skills", "count": count}


@router.post("/check-updates")
async def check_updates():
    """Check for skill file changes and hot-reload."""
    manager = get_skill_manager()
    reloaded = manager.check_for_updates()
    return {
        "message": f"Checked for updates, reloaded {len(reloaded)} skills",
        "reloaded": reloaded,
    }
