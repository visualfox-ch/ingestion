"""
Prompt Fragments Router - Phase 19.5

API endpoints for managing prompt fragments.
Allows Jarvis to modify his own behavior and personality.
"""
from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel
from typing import Optional, List

from ..observability import get_logger

logger = get_logger("jarvis.prompt_fragments_router")
router = APIRouter(prefix="/prompts", tags=["prompts"])


class FragmentCreate(BaseModel):
    name: str
    category: str
    content: str
    description: Optional[str] = None
    priority: int = 50


class FragmentUpdate(BaseModel):
    content: Optional[str] = None
    enabled: Optional[bool] = None
    priority: Optional[int] = None
    reason: Optional[str] = None


@router.get("/fragments/summary")
def get_fragments_summary():
    """Get summary of all prompt fragments."""
    from ..services.prompt_fragments import get_fragments_summary
    return get_fragments_summary()


@router.get("/fragments")
def list_fragments(
    category: Optional[str] = Query(None, description="Filter by category"),
    enabled_only: bool = Query(True, description="Only show enabled fragments")
):
    """List all prompt fragments."""
    from ..services.prompt_fragments import get_enabled_fragments, _get_conn

    if enabled_only:
        fragments = get_enabled_fragments(category)
    else:
        try:
            conn = _get_conn()
            sql = "SELECT * FROM prompt_fragments"
            params = []
            if category:
                sql += " WHERE category = ?"
                params.append(category)
            sql += " ORDER BY priority DESC, name ASC"
            cursor = conn.execute(sql, params)
            fragments = [dict(row) for row in cursor.fetchall()]
            conn.close()
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    return {"fragments": fragments, "count": len(fragments)}


@router.get("/fragments/{name}")
def get_fragment(name: str):
    """Get a specific prompt fragment."""
    from ..services.prompt_fragments import get_fragment
    fragment = get_fragment(name)
    if not fragment:
        raise HTTPException(status_code=404, detail=f"Fragment '{name}' not found")
    return fragment


@router.post("/fragments")
def create_fragment(data: FragmentCreate, created_by: str = Query("api", description="Who created this")):
    """Create a new prompt fragment."""
    from ..services.prompt_fragments import create_fragment

    success = create_fragment(
        name=data.name,
        category=data.category,
        content=data.content,
        description=data.description,
        priority=data.priority,
        created_by=created_by
    )

    if not success:
        raise HTTPException(status_code=400, detail="Failed to create fragment (may already exist)")

    return {"status": "created", "name": data.name}


@router.put("/fragments/{name}")
def update_fragment(
    name: str,
    data: FragmentUpdate,
    updated_by: str = Query("api", description="Who made this change")
):
    """Update a prompt fragment."""
    from ..services.prompt_fragments import update_fragment

    success = update_fragment(
        name=name,
        content=data.content,
        enabled=data.enabled,
        priority=data.priority,
        reason=data.reason,
        updated_by=updated_by
    )

    if not success:
        raise HTTPException(status_code=404, detail=f"Fragment '{name}' not found")

    return {"status": "updated", "name": name}


@router.get("/fragments/{name}/history")
def get_fragment_history(name: str, limit: int = Query(10, description="Max history entries")):
    """Get change history for a fragment."""
    from ..services.prompt_fragments import get_fragment_history
    history = get_fragment_history(name, limit)
    return {"fragment": name, "history": history, "count": len(history)}


@router.post("/fragments/init")
def init_default_fragments():
    """Initialize default prompt fragments."""
    from ..services.prompt_fragments import init_default_fragments
    result = init_default_fragments()
    return result


@router.get("/assemble")
def assemble_prompt(
    categories: Optional[str] = Query(None, description="Comma-separated categories to include")
):
    """Assemble a complete prompt from enabled fragments."""
    from ..services.prompt_fragments import assemble_prompt_from_fragments

    cat_list = categories.split(",") if categories else None
    prompt = assemble_prompt_from_fragments(cat_list)

    return {
        "prompt": prompt,
        "categories": cat_list or ["all"],
        "length": len(prompt)
    }


@router.get("/categories")
def list_categories():
    """List available fragment categories."""
    return {
        "categories": [
            {"name": "identity", "description": "Core identity and personality"},
            {"name": "style", "description": "Communication style"},
            {"name": "behavior", "description": "Behavioral guidelines"},
            {"name": "capability", "description": "Capabilities and features"},
            {"name": "context", "description": "Context-specific rules"},
            {"name": "custom", "description": "User-defined fragments"}
        ]
    }
