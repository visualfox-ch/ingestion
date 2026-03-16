"""
Workflow Skill Router

API endpoints for managing SKILL.md workflow definitions.
These are orchestration-level skills that guide multi-step processes.
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..skill_loader import SkillLoader, Skill
from ..observability import get_logger, log_with_context

logger = get_logger("jarvis.workflow_skill_router")
router = APIRouter(prefix="/workflow-skills", tags=["workflow-skills"])


# =========================================================================
# Response Models
# =========================================================================

class SkillSummary(BaseModel):
    """Summary of a workflow skill."""
    name: str
    description: str
    triggers: List[str]
    tools_required: List[str]
    time_trigger: Optional[str]
    activation_count: int
    version: str


class SkillDetail(BaseModel):
    """Detailed skill information including instructions."""
    name: str
    description: str
    triggers: List[str]
    not_triggers: List[str]
    tools_required: List[str]
    time_trigger: Optional[str]
    instructions: str
    references: Dict[str, str]
    activation_count: int
    last_activated: Optional[str]
    version: str
    author: str


class SkillMatchResult(BaseModel):
    """Result of skill matching for a query."""
    matched: bool
    skill_name: Optional[str]
    confidence_score: int
    context_preview: str


# =========================================================================
# Endpoints
# =========================================================================

@router.get("/", response_model=List[SkillSummary])
async def list_workflow_skills():
    """
    List all available workflow skills.

    Returns summaries of all loaded SKILL.md definitions.
    """
    skills = SkillLoader.get_all_skills()

    return [
        SkillSummary(
            name=s.name,
            description=s.description[:200],
            triggers=s.triggers[:5],
            tools_required=s.tools_required,
            time_trigger=s.time_trigger,
            activation_count=s.activation_count,
            version=s.version
        )
        for s in skills.values()
    ]


@router.get("/status")
async def get_skills_status():
    """
    Get status of the workflow skills system.

    Returns initialization state, directory info, and loaded skills.
    """
    return SkillLoader.get_status()


@router.get("/{skill_name}", response_model=SkillDetail)
async def get_skill(skill_name: str):
    """
    Get detailed information about a specific skill.

    Includes full instructions and references.
    """
    skill = SkillLoader.get_skill(skill_name)

    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found")

    return SkillDetail(
        name=skill.name,
        description=skill.description,
        triggers=skill.triggers,
        not_triggers=skill.not_triggers,
        tools_required=skill.tools_required,
        time_trigger=skill.time_trigger,
        instructions=skill.instructions,
        references=skill.references,
        activation_count=skill.activation_count,
        last_activated=skill.last_activated.isoformat() if skill.last_activated else None,
        version=skill.version,
        author=skill.author
    )


@router.get("/{skill_name}/context")
async def get_skill_context(skill_name: str, level: int = 2):
    """
    Get the context that would be injected for a skill.

    Args:
        skill_name: Name of the skill
        level: Disclosure level (1=summary, 2=full, 3=with references)
    """
    skill = SkillLoader.get_skill(skill_name)

    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found")

    context = SkillLoader.get_skill_context(skill_name, level=level)

    return {
        "skill_name": skill_name,
        "level": level,
        "context": context,
        "context_length": len(context)
    }


@router.post("/match")
async def match_skill(query: str) -> SkillMatchResult:
    """
    Find the best matching skill for a query.

    Useful for testing skill triggers.
    """
    skill = SkillLoader.find_skill_for_query(query)

    if skill:
        context = SkillLoader.get_skill_context(skill.name, level=1)
        return SkillMatchResult(
            matched=True,
            skill_name=skill.name,
            confidence_score=skill.activation_count,  # Use activation count as proxy
            context_preview=context[:200] + "..." if len(context) > 200 else context
        )
    else:
        return SkillMatchResult(
            matched=False,
            skill_name=None,
            confidence_score=0,
            context_preview=""
        )


@router.post("/reload")
async def reload_skills(skill_name: Optional[str] = None):
    """
    Reload workflow skills.

    Args:
        skill_name: Specific skill to reload, or None for all
    """
    result = SkillLoader.reload(skill_name)

    log_with_context(logger, "info", "Skills reloaded",
                    skill=skill_name or "all",
                    result=result)

    return result


@router.get("/scheduled/{time}")
async def get_scheduled_skills(time: str):
    """
    Get skills scheduled for a specific time.

    Args:
        time: Time in HH:MM format (e.g., "08:00")
    """
    skills = SkillLoader.get_scheduled_skills(time)

    return {
        "time": time,
        "skills": [s.name for s in skills],
        "count": len(skills)
    }


@router.get("/summary/prompt")
async def get_skills_prompt_summary():
    """
    Get the skills summary that's added to the system prompt.

    This is the Level 1 progressive disclosure content.
    """
    summary = SkillLoader.get_skills_summary()

    return {
        "summary": summary,
        "length": len(summary)
    }
