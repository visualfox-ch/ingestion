"""
Dynamic Config Router - Phase 21
API endpoints for managing database-backed configurations.
"""
from fastapi import APIRouter, HTTPException, Query
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/dynamic", tags=["dynamic-config"])

# Import services
try:
    from ..services.dynamic_config import (
        # Roles
        get_role_from_db, list_roles_from_db, migrate_roles_to_db, record_role_usage,
        # Patterns
        classify_query_from_db, learn_query_pattern, migrate_query_patterns,
        # Skills
        get_skill, detect_skill_from_query, register_skill, load_skills_from_files, record_skill_execution,
        # Prompts
        get_active_prompt, save_prompt_version, list_prompt_versions, activate_prompt_version,
        # Entities
        add_entity, get_entity, search_entities, seed_known_entities,
        # Costs
        get_cost_summary, get_model_costs, update_model_cost,
        # Init
        initialize_all
    )
    _CONFIG_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Dynamic config not available: {e}")
    _CONFIG_AVAILABLE = False


# ============================================
# Pydantic Models
# ============================================

class RoleUpdate(BaseModel):
    description: Optional[str] = None
    system_prompt_addon: Optional[str] = None
    greeting: Optional[str] = None
    keywords: Optional[List[str]] = None
    default_namespace: Optional[str] = None
    enabled: Optional[bool] = None


class PatternCreate(BaseModel):
    pattern: str
    pattern_type: str  # 'simple', 'standard', 'complex'
    category: Optional[str] = None
    is_regex: bool = False
    confidence: float = 0.7


class SkillCreate(BaseModel):
    name: str
    category: Optional[str] = None
    description: Optional[str] = None
    triggers: List[str] = []
    not_triggers: List[str] = []
    required_tools: List[str] = []
    level: int = 1
    version: str = "1.0"


class PromptCreate(BaseModel):
    name: str
    content: str
    description: Optional[str] = None
    make_active: bool = False


class EntityCreate(BaseModel):
    name: str
    entity_type: str
    metadata: Optional[Dict[str, Any]] = None
    namespace: str = "shared"
    importance: str = "medium"
    aliases: Optional[List[str]] = None


class ModelCostUpdate(BaseModel):
    input_cost_per_1k: float
    output_cost_per_1k: float


# ============================================
# Initialization
# ============================================

@router.post("/init")
async def init_dynamic_config():
    """Initialize all Phase 21 dynamic config tables and migrate data."""
    if not _CONFIG_AVAILABLE:
        raise HTTPException(status_code=503, detail="Dynamic config not available")

    try:
        initialize_all()
        return {"success": True, "message": "Phase 21 dynamic config initialized"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# Roles Endpoints
# ============================================

@router.get("/roles")
async def list_roles():
    """List all available roles."""
    if not _CONFIG_AVAILABLE:
        raise HTTPException(status_code=503, detail="Dynamic config not available")

    roles = list_roles_from_db()
    return {"roles": roles, "count": len(roles)}


@router.get("/roles/{role_name}")
async def get_role(role_name: str):
    """Get a specific role."""
    if not _CONFIG_AVAILABLE:
        raise HTTPException(status_code=503, detail="Dynamic config not available")

    role = get_role_from_db(role_name)
    if not role:
        raise HTTPException(status_code=404, detail=f"Role '{role_name}' not found")

    return {
        "name": role.name,
        "description": role.description,
        "system_prompt_addon": role.system_prompt_addon,
        "greeting": role.greeting,
        "keywords": role.keywords,
        "default_namespace": role.default_namespace,
        "enabled": role.enabled,
        "usage_count": role.usage_count
    }


@router.post("/roles/migrate")
async def migrate_roles():
    """Migrate hardcoded roles to database."""
    if not _CONFIG_AVAILABLE:
        raise HTTPException(status_code=503, detail="Dynamic config not available")

    try:
        from ..roles import ROLES
        migrate_roles_to_db(ROLES)
        return {"success": True, "message": f"Migrated {len(ROLES)} roles"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# Query Patterns Endpoints
# ============================================

@router.get("/patterns/classify")
async def classify_query(query: str = Query(...)):
    """Classify a query using database patterns."""
    if not _CONFIG_AVAILABLE:
        raise HTTPException(status_code=503, detail="Dynamic config not available")

    result = classify_query_from_db(query)
    return {"query": query, "classification": result[0], "confidence": result[1]}


@router.post("/patterns/learn")
async def learn_pattern(data: PatternCreate):
    """Learn a new query pattern."""
    if not _CONFIG_AVAILABLE:
        raise HTTPException(status_code=503, detail="Dynamic config not available")

    learn_query_pattern(data.pattern, data.pattern_type, data.confidence)
    return {"success": True, "pattern": data.pattern, "type": data.pattern_type}


@router.post("/patterns/migrate")
async def migrate_patterns():
    """Migrate hardcoded patterns to database."""
    if not _CONFIG_AVAILABLE:
        raise HTTPException(status_code=503, detail="Dynamic config not available")

    try:
        from ..query_classifier import SIMPLE_PATTERNS, COMPLEX_INDICATORS, STANDARD_INDICATORS
        migrate_query_patterns(SIMPLE_PATTERNS, COMPLEX_INDICATORS, STANDARD_INDICATORS)
        total = len(SIMPLE_PATTERNS) + len(COMPLEX_INDICATORS) + len(STANDARD_INDICATORS)
        return {"success": True, "message": f"Migrated {total} patterns"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# Skills Endpoints
# ============================================

@router.get("/skills")
async def list_skills():
    """List all registered skills."""
    if not _CONFIG_AVAILABLE:
        raise HTTPException(status_code=503, detail="Dynamic config not available")

    # Use the skill registry directly
    import sqlite3
    from pathlib import Path

    db_path = Path("/brain/system/state/jarvis_config.db")
    if not db_path.exists():
        return {"skills": [], "count": 0}

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.execute("SELECT name, category, description, usage_count, enabled FROM skill_registry ORDER BY usage_count DESC")
    skills = [dict(row) for row in cursor.fetchall()]
    conn.close()

    return {"skills": skills, "count": len(skills)}


@router.get("/skills/{skill_name}")
async def get_skill_detail(skill_name: str):
    """Get a specific skill."""
    if not _CONFIG_AVAILABLE:
        raise HTTPException(status_code=503, detail="Dynamic config not available")

    skill = get_skill(skill_name)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found")

    return skill


@router.post("/skills/detect")
async def detect_skill(query: str = Query(...)):
    """Detect which skill matches a query."""
    if not _CONFIG_AVAILABLE:
        raise HTTPException(status_code=503, detail="Dynamic config not available")

    skill = detect_skill_from_query(query)
    if skill:
        return {"matched": True, "skill": skill["name"], "triggers": skill["triggers"]}
    return {"matched": False, "skill": None}


@router.post("/skills/reload")
async def reload_skills():
    """Reload skills from SKILL.md files."""
    if not _CONFIG_AVAILABLE:
        raise HTTPException(status_code=503, detail="Dynamic config not available")

    count = load_skills_from_files()
    return {"success": True, "loaded": count}


@router.post("/skills")
async def create_skill(data: SkillCreate):
    """Register a new skill."""
    if not _CONFIG_AVAILABLE:
        raise HTTPException(status_code=503, detail="Dynamic config not available")

    success = register_skill(data.dict())
    if success:
        return {"success": True, "skill": data.name}
    raise HTTPException(status_code=500, detail="Failed to register skill")


# ============================================
# Prompts Endpoints
# ============================================

@router.get("/prompts/{name}")
async def get_prompt(name: str):
    """Get active prompt by name."""
    if not _CONFIG_AVAILABLE:
        raise HTTPException(status_code=503, detail="Dynamic config not available")

    content = get_active_prompt(name)
    if not content:
        raise HTTPException(status_code=404, detail=f"Prompt '{name}' not found")

    return {"name": name, "content": content}


@router.get("/prompts/{name}/versions")
async def get_prompt_versions(name: str):
    """List all versions of a prompt."""
    if not _CONFIG_AVAILABLE:
        raise HTTPException(status_code=503, detail="Dynamic config not available")

    versions = list_prompt_versions(name)
    return {"name": name, "versions": versions}


@router.post("/prompts")
async def create_prompt(data: PromptCreate):
    """Create a new prompt version."""
    if not _CONFIG_AVAILABLE:
        raise HTTPException(status_code=503, detail="Dynamic config not available")

    version = save_prompt_version(
        name=data.name,
        content=data.content,
        description=data.description,
        make_active=data.make_active
    )
    if version:
        return {"success": True, "name": data.name, "version": version}
    raise HTTPException(status_code=500, detail="Failed to save prompt")


@router.put("/prompts/{name}/activate/{version}")
async def activate_prompt(name: str, version: int):
    """Activate a specific prompt version."""
    if not _CONFIG_AVAILABLE:
        raise HTTPException(status_code=503, detail="Dynamic config not available")

    success = activate_prompt_version(name, version)
    if success:
        return {"success": True, "name": name, "version": version}
    raise HTTPException(status_code=500, detail="Failed to activate prompt")


# ============================================
# Entities Endpoints
# ============================================

@router.get("/entities")
async def search_entities_endpoint(
    q: str = Query(None),
    entity_type: str = Query(None),
    limit: int = Query(20)
):
    """Search entities."""
    if not _CONFIG_AVAILABLE:
        raise HTTPException(status_code=503, detail="Dynamic config not available")

    if q:
        entities = search_entities(q, entity_type, limit)
    else:
        entities = search_entities("", entity_type, limit)

    return {"entities": entities, "count": len(entities)}


@router.get("/entities/{name}")
async def get_entity_detail(name: str, entity_type: str = Query(None)):
    """Get a specific entity."""
    if not _CONFIG_AVAILABLE:
        raise HTTPException(status_code=503, detail="Dynamic config not available")

    entity = get_entity(name, entity_type)
    if not entity:
        raise HTTPException(status_code=404, detail=f"Entity '{name}' not found")

    return entity


@router.post("/entities")
async def create_entity(data: EntityCreate):
    """Create or update an entity."""
    if not _CONFIG_AVAILABLE:
        raise HTTPException(status_code=503, detail="Dynamic config not available")

    success = add_entity(
        name=data.name,
        entity_type=data.entity_type,
        metadata=data.metadata,
        namespace=data.namespace,
        importance=data.importance,
        aliases=data.aliases
    )
    if success:
        return {"success": True, "entity": data.name}
    raise HTTPException(status_code=500, detail="Failed to create entity")


@router.post("/entities/seed")
async def seed_entities():
    """Seed database with known entities."""
    if not _CONFIG_AVAILABLE:
        raise HTTPException(status_code=503, detail="Dynamic config not available")

    seed_known_entities()
    return {"success": True, "message": "Entities seeded"}


# ============================================
# Cost Tracking Endpoints
# ============================================

@router.get("/costs/summary")
async def get_costs(days: int = Query(7)):
    """Get cost summary for recent days."""
    if not _CONFIG_AVAILABLE:
        raise HTTPException(status_code=503, detail="Dynamic config not available")

    return get_cost_summary(days)


@router.get("/costs/models")
async def get_models():
    """Get all model costs."""
    if not _CONFIG_AVAILABLE:
        raise HTTPException(status_code=503, detail="Dynamic config not available")

    return get_model_costs()


@router.put("/costs/models/{model}")
async def update_model(model: str, data: ModelCostUpdate):
    """Update model pricing."""
    if not _CONFIG_AVAILABLE:
        raise HTTPException(status_code=503, detail="Dynamic config not available")

    update_model_cost(model, data.input_cost_per_1k, data.output_cost_per_1k)
    return {"success": True, "model": model}
