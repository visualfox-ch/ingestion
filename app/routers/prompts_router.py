"""
Prompts Router

Extracted from main.py - Prompt management endpoints:
- Dynamic prompt fragments (list, create, approve, disable, delete, remember, summary, assembled)
- Prompt blueprints (create, list, get, get default, update, versions, render)
- A/B testing for blueprints (create, list, get, start, variant, result, complete, stats)
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, List, Optional

from ..observability import get_logger

logger = get_logger("jarvis.prompts")
router = APIRouter(prefix="/prompts", tags=["prompts"])


# =============================================================================
# PYDANTIC MODELS
# =============================================================================

class BlueprintCreate(BaseModel):
    blueprint_id: str
    name: str
    use_case: str  # briefing, email, decision, coaching, analysis
    template: str
    description: Optional[str] = None
    variables_schema: Optional[List[Dict]] = None
    is_default: bool = False


class BlueprintUpdate(BaseModel):
    template: Optional[str] = None
    variables_schema: Optional[List[Dict]] = None
    change_reason: Optional[str] = None


class BlueprintRender(BaseModel):
    variables: Dict[str, Any]


class ABTestCreate(BaseModel):
    test_id: str
    name: str
    blueprint_id: str
    variant_a_version: int
    variant_b_version: int
    success_metric: str = "user_rating"  # user_rating, task_completion, response_quality
    description: Optional[str] = None
    traffic_split: float = 0.5  # Percentage to variant B
    min_samples: int = 30
    confidence_threshold: float = 0.95


class ABTestResult(BaseModel):
    quality_score: Optional[float] = None
    task_completed: Optional[bool] = None
    tokens_used: Optional[int] = None
    response_time_ms: Optional[int] = None
    feedback_type: Optional[str] = None  # thumbs_up, thumbs_down, explicit_rating
    feedback_text: Optional[str] = None
    conversation_id: Optional[str] = None
    message_id: Optional[str] = None


# =============================================================================
# PROMPT FRAGMENTS
# =============================================================================

@router.get("/fragments")
def list_prompt_fragments(
    user_id: int = None,
    namespace: str = None,
    category: str = None,
    status: str = "approved"
):
    """List prompt fragments with optional filters"""
    from .. import knowledge_db

    fragments = knowledge_db.get_prompt_fragments(
        category=category,
        user_id=user_id,
        namespace=namespace,
        status=status,
        include_global=True
    )

    return {
        "count": len(fragments),
        "fragments": [
            {
                "fragment_id": f["fragment_id"],
                "category": f["category"],
                "content": f["content"],
                "priority": f["priority"],
                "status": f["status"],
                "trigger_condition": f.get("trigger_condition"),
                "learned_from": f.get("learned_from"),
                "created_at": str(f.get("created_at", ""))
            }
            for f in fragments
        ]
    }


@router.post("/fragments")
def create_prompt_fragment(
    category: str,
    content: str,
    priority: int = 50,
    user_id: int = None,
    namespace: str = None,
    trigger_condition: dict = None,
    auto_approve: bool = False
):
    """Create a new prompt fragment"""
    from .. import knowledge_db

    status = "approved" if auto_approve else "draft"

    db_id = knowledge_db.create_prompt_fragment(
        category=category,
        content=content,
        trigger_condition=trigger_condition,
        priority=priority,
        user_id=user_id,
        namespace=namespace,
        status=status,
        learned_from="api",
        created_by=f"api:user_{user_id}" if user_id else "api"
    )

    if db_id:
        # Get the created fragment
        with knowledge_db.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT fragment_id FROM prompt_fragment WHERE id = %s", (db_id,))
            row = cur.fetchone()
            fragment_id = row["fragment_id"] if row else None

        return {
            "success": True,
            "fragment_id": fragment_id,
            "status": status
        }

    return {"success": False, "error": "Failed to create fragment"}


@router.post("/fragments/{fragment_id}/approve")
def approve_fragment(fragment_id: str, approved_by: str = "api"):
    """Approve a draft fragment"""
    from .. import knowledge_db

    success = knowledge_db.approve_prompt_fragment(fragment_id, approved_by)
    return {"success": success}


@router.post("/fragments/{fragment_id}/disable")
def disable_fragment(fragment_id: str, disabled_by: str = "api"):
    """Disable a fragment"""
    from .. import knowledge_db

    success = knowledge_db.disable_prompt_fragment(fragment_id, disabled_by)
    return {"success": success}


@router.delete("/fragments/{fragment_id}")
def delete_fragment(fragment_id: str):
    """Delete a draft fragment (approved fragments can only be disabled)"""
    from .. import knowledge_db

    success = knowledge_db.delete_prompt_fragment(fragment_id)
    return {"success": success}


@router.post("/remember")
def remember_instruction(
    instruction: str,
    user_id: int = None,
    namespace: str = None,
    auto_approve: bool = True
):
    """
    Learn from natural language instruction.

    Examples:
    - "Merke dir: ich mag kurze Antworten"
    - "Bei Stress: sei empathischer"
    - "Ich bevorzuge Bullet Points"
    """
    from .. import prompt_assembler

    fragment_id = prompt_assembler.create_learning_fragment(
        user_input=instruction,
        user_id=user_id,
        namespace=namespace,
        auto_approve=auto_approve
    )

    if fragment_id:
        return {
            "success": True,
            "fragment_id": fragment_id,
            "instruction": instruction
        }

    return {
        "success": False,
        "error": "Could not parse instruction. Try: 'Merke dir: ...' or 'Bei Stress: ...'"
    }


@router.get("/summary")
def get_prompts_summary(user_id: int = None, namespace: str = None):
    """Get summary of active prompt fragments for a user"""
    from .. import prompt_assembler

    return prompt_assembler.get_active_fragments_summary(
        user_id=user_id,
        namespace=namespace
    )


@router.get("/assembled")
def get_assembled_prompt(
    user_id: int = None,
    namespace: str = None,
    query: str = "Test query"
):
    """Preview the assembled system prompt"""
    from .. import prompt_assembler
    from .. import sentiment_analyzer

    sentiment = sentiment_analyzer.analyze_sentiment(query)

    assembled = prompt_assembler.assemble_system_prompt(
        user_id=user_id,
        namespace=namespace,
        sentiment_result=sentiment.to_dict(),
        include_dynamic=True
    )

    return {
        "fixed_length": assembled.fixed_length,
        "dynamic_length": assembled.dynamic_length,
        "fragment_count": assembled.fragment_count,
        "fragment_ids": assembled.fragment_ids,
        "warnings": assembled.warnings,
        "full_prompt_preview": assembled.full_prompt[:2000] + "..." if len(assembled.full_prompt) > 2000 else assembled.full_prompt
    }


# =============================================================================
# BLUEPRINTS
# =============================================================================

# Note: Blueprints use /blueprints prefix via separate router inclusion
blueprints_router = APIRouter(prefix="/blueprints", tags=["blueprints"])


@blueprints_router.post("")
def create_blueprint(req: BlueprintCreate):
    """
    Create a new prompt blueprint.

    Blueprints are versioned prompt templates for specific use cases.

    Example:
    ```json
    {
        "blueprint_id": "morning_briefing_v1",
        "name": "Morning Briefing",
        "use_case": "briefing",
        "template": "Guten Morgen {{user_name}}!\\n\\n## Kalender\\n{{calendar_events}}\\n\\n## Prioritaeten\\n{{priorities}}",
        "variables_schema": [
            {"name": "user_name", "type": "string", "required": true, "default": "Micha"},
            {"name": "calendar_events", "type": "string", "required": true},
            {"name": "priorities", "type": "string", "required": false, "default": "Keine expliziten Prioritaeten"}
        ],
        "is_default": true
    }
    ```
    """
    from .. import knowledge_db

    result = knowledge_db.create_blueprint(
        blueprint_id=req.blueprint_id,
        name=req.name,
        use_case=req.use_case,
        template=req.template,
        description=req.description,
        variables_schema=req.variables_schema,
        is_default=req.is_default,
        created_by="api"
    )

    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("error"))

    return result


@blueprints_router.get("")
def list_blueprints(use_case: str = None, status: str = "active"):
    """
    List all blueprints.

    Query params:
    - use_case: Filter by use case (briefing, email, decision, coaching, analysis)
    - status: Filter by status (draft, active, deprecated, archived)
    """
    from .. import knowledge_db
    return knowledge_db.list_blueprints(use_case=use_case, status=status)


@blueprints_router.get("/{blueprint_id}")
def get_blueprint(blueprint_id: str):
    """Get a specific blueprint by ID."""
    from .. import knowledge_db

    blueprint = knowledge_db.get_blueprint(blueprint_id=blueprint_id)
    if not blueprint:
        raise HTTPException(status_code=404, detail="Blueprint not found")
    return blueprint


@blueprints_router.get("/default/{use_case}")
def get_default_blueprint(use_case: str):
    """Get the default blueprint for a use case."""
    from .. import knowledge_db

    blueprint = knowledge_db.get_blueprint(use_case=use_case, get_default=True)
    if not blueprint:
        raise HTTPException(status_code=404, detail=f"No default blueprint for use_case: {use_case}")
    return blueprint


@blueprints_router.put("/{blueprint_id}")
def update_blueprint(blueprint_id: str, req: BlueprintUpdate):
    """
    Update a blueprint (creates a new version).

    Only provided fields will be updated.
    """
    from .. import knowledge_db

    result = knowledge_db.update_blueprint(
        blueprint_id=blueprint_id,
        template=req.template,
        variables_schema=req.variables_schema,
        change_reason=req.change_reason,
        changed_by="api"
    )

    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("error"))

    return result


@blueprints_router.get("/{blueprint_id}/versions")
def get_blueprint_versions(blueprint_id: str, limit: int = 10):
    """Get version history for a blueprint."""
    from .. import knowledge_db
    return knowledge_db.get_blueprint_versions(blueprint_id, limit=limit)


@blueprints_router.post("/{blueprint_id}/render")
def render_blueprint(blueprint_id: str, req: BlueprintRender):
    """
    Render a blueprint template with provided variables.

    Returns the fully rendered prompt string.

    Example:
    ```json
    {
        "variables": {
            "user_name": "Micha",
            "calendar_events": "09:00 Standup\\n14:00 Client Call",
            "priorities": "1. Deploy v2.0\\n2. Review PR"
        }
    }
    ```
    """
    from .. import knowledge_db

    result = knowledge_db.render_blueprint(blueprint_id, req.variables)
    if result is None:
        raise HTTPException(status_code=404, detail="Blueprint not found or render failed")

    # Log usage
    knowledge_db.log_blueprint_usage(
        blueprint_id=blueprint_id,
        variables_provided=req.variables
    )

    return {"rendered": result}


# =============================================================================
# A/B TESTING
# =============================================================================

ab_tests_router = APIRouter(prefix="/ab-tests", tags=["ab-tests"])


@ab_tests_router.post("")
def create_ab_test(req: ABTestCreate):
    """
    Create a new A/B test for a blueprint.

    Tests two versions of a blueprint against each other.
    Users are deterministically assigned to variants based on their ID.

    Example:
    ```json
    {
        "test_id": "briefing_tone_test_2026",
        "name": "Morning Briefing Tone Test",
        "blueprint_id": "morning_briefing_v1",
        "variant_a_version": 1,
        "variant_b_version": 2,
        "success_metric": "user_rating",
        "traffic_split": 0.5,
        "min_samples": 30
    }
    ```
    """
    from .. import knowledge_db

    result = knowledge_db.create_ab_test(
        test_id=req.test_id,
        name=req.name,
        blueprint_id=req.blueprint_id,
        variant_a_version=req.variant_a_version,
        variant_b_version=req.variant_b_version,
        success_metric=req.success_metric,
        description=req.description,
        traffic_split=req.traffic_split,
        min_samples=req.min_samples,
        confidence_threshold=req.confidence_threshold,
        created_by="api"
    )

    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("error"))

    return result


@ab_tests_router.get("")
def list_ab_tests(status: str = None, blueprint_id: str = None):
    """
    List A/B tests.

    Query params:
    - status: Filter by status (draft, running, paused, completed, cancelled)
    - blueprint_id: Filter by blueprint
    """
    from .. import knowledge_db
    return knowledge_db.list_ab_tests(status=status, blueprint_id=blueprint_id)


@ab_tests_router.get("/{test_id}")
def get_ab_test(test_id: str):
    """Get A/B test details and statistics."""
    from .. import knowledge_db

    stats = knowledge_db.get_ab_test_stats(test_id)
    if stats.get("status") == "error":
        raise HTTPException(status_code=404, detail=stats.get("error"))
    return stats


@ab_tests_router.post("/{test_id}/start")
def start_ab_test(test_id: str):
    """Start an A/B test (change status from draft to running)."""
    from .. import knowledge_db

    result = knowledge_db.start_ab_test(test_id)
    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@ab_tests_router.get("/{test_id}/variant/{user_id}")
def get_ab_test_variant(test_id: str, user_id: str):
    """
    Get the variant assignment for a user.

    Returns which variant (A or B) the user should see.
    Assignment is deterministic based on user_id hash.
    """
    from .. import knowledge_db

    variant = knowledge_db.get_ab_test_variant(test_id, user_id)
    if variant is None:
        raise HTTPException(status_code=404, detail="Test not found or not running")
    return {"test_id": test_id, "user_id": user_id, "variant": variant}


@ab_tests_router.post("/{test_id}/result/{user_id}")
def record_ab_test_result(test_id: str, user_id: str, req: ABTestResult):
    """
    Record a result for an A/B test interaction.

    Call this after using a blueprint to record outcome metrics.

    Example:
    ```json
    {
        "quality_score": 0.8,
        "task_completed": true,
        "feedback_type": "thumbs_up"
    }
    ```
    """
    from .. import knowledge_db

    success = knowledge_db.record_ab_result(
        test_id=test_id,
        user_id=user_id,
        quality_score=req.quality_score,
        task_completed=req.task_completed,
        tokens_used=req.tokens_used,
        response_time_ms=req.response_time_ms,
        feedback_type=req.feedback_type,
        feedback_text=req.feedback_text,
        conversation_id=req.conversation_id,
        message_id=req.message_id
    )

    if not success:
        raise HTTPException(status_code=400, detail="Failed to record result")
    return {"status": "recorded"}


@ab_tests_router.post("/{test_id}/complete")
def complete_ab_test(test_id: str, winner: str = None, notes: str = None):
    """
    Complete an A/B test and declare a winner.

    If winner is not provided, it will be determined automatically
    based on statistical significance.

    Query params:
    - winner: Force winner (A or B), or omit for automatic determination
    - notes: Conclusion notes
    """
    from .. import knowledge_db

    result = knowledge_db.complete_ab_test(test_id, winner=winner, notes=notes)
    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@ab_tests_router.get("/{test_id}/stats")
def get_ab_test_stats(test_id: str):
    """Get detailed statistics for an A/B test."""
    from .. import knowledge_db

    stats = knowledge_db.get_ab_test_stats(test_id)
    if stats.get("status") == "error":
        raise HTTPException(status_code=404, detail=stats.get("error"))
    return stats
