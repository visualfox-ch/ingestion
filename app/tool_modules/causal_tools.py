"""
Causal Tools.

Predictive context, causal observations and patterns.
Extracted from tools.py (Phase S6).
"""
from typing import Any, Dict, List, Optional
from datetime import datetime

from ..observability import get_logger, log_with_context, metrics

logger = get_logger("jarvis.tools.causal")


CAUSAL_TOOLS = [
    {
        "name": "learn_causal_relationship",
        "description": "Learn a new cause-effect relationship and add it to the causal graph.",
        "input_schema": {
            "type": "object",
            "properties": {
                "cause_description": {"type": "string"},
                "effect_description": {"type": "string"},
                "relationship_type": {"type": "string"},
                "confidence": {"type": "number"},
                "mechanism": {"type": "string"},
                "source": {"type": "string"},
                "domain": {"type": "string"},
                "session_id": {"type": "string"},
            },
            "required": ["cause_description", "effect_description"],
        },
    },
    {
        "name": "why_does",
        "description": "Explain why an outcome happens by tracing known causal ancestors.",
        "input_schema": {
            "type": "object",
            "properties": {
                "effect_name": {"type": "string"},
                "domain": {"type": "string"},
                "max_depth": {"type": "integer"},
                "session_id": {"type": "string"},
            },
            "required": ["effect_name"],
        },
    },
    {
        "name": "what_if",
        "description": "Predict downstream effects of a hypothetical intervention.",
        "input_schema": {
            "type": "object",
            "properties": {
                "intervention_name": {"type": "string"},
                "intervention_value": {"type": "string"},
                "domain": {"type": "string"},
                "max_depth": {"type": "integer"},
                "session_id": {"type": "string"},
            },
            "required": ["intervention_name"],
        },
    },
    {
        "name": "how_to_achieve",
        "description": "Find manipulable upstream causes that can help achieve a goal.",
        "input_schema": {
            "type": "object",
            "properties": {
                "goal_name": {"type": "string"},
                "domain": {"type": "string"},
                "max_depth": {"type": "integer"},
                "session_id": {"type": "string"},
            },
            "required": ["goal_name"],
        },
    },
    {
        "name": "get_causal_chain",
        "description": "Retrieve the causal chain of effects or causes for a node.",
        "input_schema": {
            "type": "object",
            "properties": {
                "start_node_id": {"type": "integer"},
                "start_node_name": {"type": "string"},
                "direction": {"type": "string", "enum": ["effects", "causes"]},
                "max_depth": {"type": "integer"},
                "min_confidence": {"type": "number"},
            },
        },
    },
    {
        "name": "record_intervention",
        "description": "Record an intervention so its predicted effects can be verified later.",
        "input_schema": {
            "type": "object",
            "properties": {
                "target_name": {"type": "string"},
                "intervention_type": {"type": "string"},
                "target_value": {"type": "string"},
                "original_value": {"type": "string"},
                "predicted_effects": {"type": "array", "items": {"type": "object"}},
                "domain": {"type": "string"},
                "session_id": {"type": "string"},
            },
            "required": ["target_name", "intervention_type", "target_value"],
        },
    },
    {
        "name": "verify_intervention_outcome",
        "description": "Compare predicted intervention effects with actual observed outcomes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "intervention_id": {"type": "integer"},
                "actual_effects": {"type": "array", "items": {"type": "object"}},
            },
            "required": ["intervention_id", "actual_effects"],
        },
    },
    {
        "name": "find_causal_nodes",
        "description": "Search the causal graph for nodes by name, type, or domain.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "node_type": {"type": "string"},
                "domain": {"type": "string"},
                "limit": {"type": "integer"},
            },
        },
    },
    {
        "name": "get_causal_summary",
        "description": "Return summary statistics for the causal knowledge graph.",
        "input_schema": {
            "type": "object",
            "properties": {
                "domain": {"type": "string"},
            },
        },
    },
    {
        "name": "add_causal_node",
        "description": "Add or update a causal graph node.",
        "input_schema": {
            "type": "object",
            "properties": {
                "node_name": {"type": "string"},
                "node_type": {"type": "string"},
                "domain": {"type": "string"},
                "description": {"type": "string"},
                "is_observable": {"type": "boolean"},
                "is_manipulable": {"type": "boolean"},
                "typical_values": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["node_name", "node_type"],
        },
    },
]


def _get_causal_service():
    from ..services.causal_knowledge_service import get_causal_service

    return get_causal_service()


def tool_get_predictive_context(
    context_type: str = "day_ahead",
    **kwargs
) -> Dict[str, Any]:
    """
    Get predictive insights based on patterns and upcoming events.

    Jarvis can anticipate needs based on:
    - Calendar events and their typical preparation needs
    - Historical patterns (e.g., "Mondays are usually busy")
    - Recent emotional/energy trends

    Args:
        context_type: Type of prediction (day_ahead, week_ahead, meeting_prep)

    Returns:
        Predictions, recommendations, and proactive suggestions
    """
    log_with_context(logger, "info", "Tool: get_predictive_context", context_type=context_type)
    metrics.inc("tool_get_predictive_context")

    try:
        from datetime import datetime, timedelta

        now = datetime.now()
        result = {
            "context_type": context_type,
            "generated_at": now.isoformat(),
            "predictions": [],
            "recommendations": [],
            "energy_forecast": None
        }

        # Get today's calendar
        from ..postgres_state import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                # Check for patterns about this weekday
                weekday = now.strftime("%A").lower()
                cur.execute("""
                    SELECT value, confidence
                    FROM jarvis_context
                    WHERE key LIKE %s
                    AND category = 'pattern'
                    ORDER BY confidence DESC
                    LIMIT 3
                """, (f"%{weekday}%",))
                weekday_patterns = cur.fetchall()

                for p in weekday_patterns:
                    result["predictions"].append({
                        "type": "weekday_pattern",
                        "prediction": p["value"],
                        "confidence": p["confidence"] or 0.5
                    })

                # Check recent energy/mood trends
                cur.execute("""
                    SELECT value, updated_at
                    FROM jarvis_context
                    WHERE category IN ('energy', 'mood', 'stress')
                    AND updated_at >= NOW() - INTERVAL '3 days'
                    ORDER BY updated_at DESC
                    LIMIT 5
                """)
                energy_rows = cur.fetchall()

                if energy_rows:
                    recent_states = [r["value"] for r in energy_rows]
                    # Simple trend analysis
                    if any("tired" in s.lower() or "müde" in s.lower() for s in recent_states if s):
                        result["energy_forecast"] = "niedrig"
                        result["recommendations"].append("Plane Pausen ein - letzte Tage waren anstrengend")
                    elif any("stress" in s.lower() for s in recent_states if s):
                        result["energy_forecast"] = "angespannt"
                        result["recommendations"].append("Fokus auf wichtigste Task, Rest delegieren oder verschieben")
                    else:
                        result["energy_forecast"] = "normal"

        # Default recommendations based on context_type
        if context_type == "day_ahead":
            result["recommendations"].extend([
                "Morgens Deep Work, nachmittags Meetings",
                "Prüfe offene Follow-ups vor erstem Meeting"
            ])
        elif context_type == "meeting_prep":
            result["recommendations"].append("Hole Person-Context für Meeting-Teilnehmer")

        return result

    except Exception as e:
        log_with_context(logger, "error", "get_predictive_context failed", error=str(e))
        return {"error": str(e)}


# Phase 20: Identity Evolution Tools MOVED to tool_modules/identity_tools.py (T006 refactor)
# Implementations: tool_get_self_model, tool_evolve_identity, tool_log_experience,
#                  tool_get_relationship, tool_update_relationship, tool_get_learning_patterns,
#                  tool_record_session_learning


def tool_record_causal_observation(
    cause_event: str,
    effect_event: str,
    cause_type: str = "event",
    effect_type: str = "outcome",
    **kwargs
) -> Dict[str, Any]:
    """Record a cause-effect observation."""
    user_id = str(kwargs.get("user_id", "1"))
    session_id = kwargs.get("session_id")

    log_with_context(logger, "info", "Tool: record_causal_observation",
                    cause=cause_event, effect=effect_event)
    metrics.inc("tool_record_causal_observation")

    try:
        from app.services.causal_knowledge_tracker import get_causal_knowledge_tracker
        tracker = get_causal_knowledge_tracker()
        return tracker.record_observation(
            user_id=user_id,
            cause_event=cause_event,
            effect_event=effect_event,
            cause_type=cause_type,
            effect_type=effect_type,
            session_id=session_id
        )
    except Exception as e:
        log_with_context(logger, "error", "record_causal_observation failed", error=str(e))
        return {"error": str(e)}


def tool_predict_from_cause(
    cause: str,
    min_confidence: float = 0.6,
    **kwargs
) -> Dict[str, Any]:
    """Predict effects from a cause."""
    user_id = str(kwargs.get("user_id", "1"))

    log_with_context(logger, "info", "Tool: predict_from_cause", cause=cause)
    metrics.inc("tool_predict_from_cause")

    try:
        from app.services.causal_knowledge_tracker import get_causal_knowledge_tracker
        tracker = get_causal_knowledge_tracker()
        predictions = tracker.predict_effects(user_id, cause, min_confidence)
        return {"cause": cause, "predicted_effects": predictions, "count": len(predictions)}
    except Exception as e:
        log_with_context(logger, "error", "predict_from_cause failed", error=str(e))
        return {"error": str(e)}


def tool_get_causal_patterns(
    min_confidence: float = 0.5,
    limit: int = 50,
    **kwargs
) -> Dict[str, Any]:
    """Get all causal patterns."""
    user_id = str(kwargs.get("user_id", "1"))

    log_with_context(logger, "info", "Tool: get_causal_patterns")
    metrics.inc("tool_get_causal_patterns")

    try:
        from app.services.causal_knowledge_tracker import get_causal_knowledge_tracker
        tracker = get_causal_knowledge_tracker()
        patterns = tracker.get_all_patterns(user_id, min_confidence, 1, limit)
        return {"patterns": patterns, "count": len(patterns)}
    except Exception as e:
        log_with_context(logger, "error", "get_causal_patterns failed", error=str(e))
        return {"error": str(e)}


def add_causal_node(
    node_name: str,
    node_type: str,
    domain: str = None,
    description: str = None,
    is_observable: bool = True,
    is_manipulable: bool = False,
    typical_values: List[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """Add a node to the causal graph."""
    log_with_context(logger, "info", "Tool: add_causal_node", node_name=node_name, node_type=node_type, domain=domain)
    metrics.inc("add_causal_node")

    try:
        service = _get_causal_service()
        return service.add_node(
            node_name=node_name,
            node_type=node_type,
            domain=domain,
            description=description,
            is_observable=is_observable,
            is_manipulable=is_manipulable,
            typical_values=typical_values,
        )
    except Exception as e:
        log_with_context(logger, "error", "add_causal_node failed", error=str(e))
        return {"success": False, "error": str(e)}


def find_causal_nodes(
    query: str = None,
    node_type: str = None,
    domain: str = None,
    limit: int = 20,
    **kwargs
) -> Dict[str, Any]:
    """Search causal nodes by name, type, or domain."""
    log_with_context(logger, "info", "Tool: find_causal_nodes", query=query, node_type=node_type, domain=domain, limit=limit)
    metrics.inc("find_causal_nodes")

    try:
        from ..postgres_state import get_conn

        filters = []
        params: List[Any] = []

        if query:
            filters.append("(node_name ILIKE %s OR COALESCE(description, '') ILIKE %s)")
            like_query = f"%{query}%"
            params.extend([like_query, like_query])
        if node_type:
            filters.append("node_type = %s")
            params.append(node_type)
        if domain:
            filters.append("domain = %s")
            params.append(domain)

        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
        params.append(limit)

        sql = f"""
            SELECT
                id,
                node_name,
                node_type,
                domain,
                description,
                is_observable,
                is_manipulable,
                typical_values,
                occurrence_count,
                last_observed
            FROM causal_nodes
            {where_clause}
            ORDER BY occurrence_count DESC NULLS LAST, node_name ASC
            LIMIT %s
        """

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, tuple(params))
                columns = [desc[0] for desc in cur.description]
                nodes = [dict(zip(columns, row)) for row in cur.fetchall()]

        return {
            "success": True,
            "query": query,
            "node_type": node_type,
            "domain": domain,
            "count": len(nodes),
            "nodes": nodes,
        }
    except Exception as e:
        log_with_context(logger, "error", "find_causal_nodes failed", error=str(e))
        return {"success": False, "error": str(e)}


def get_causal_chain(
    start_node_id: int = None,
    start_node_name: str = None,
    direction: str = "effects",
    max_depth: int = 3,
    min_confidence: float = 0.3,
    **kwargs
) -> Dict[str, Any]:
    """Get a causal chain from a node."""
    log_with_context(
        logger,
        "info",
        "Tool: get_causal_chain",
        start_node_id=start_node_id,
        start_node_name=start_node_name,
        direction=direction,
        max_depth=max_depth,
        min_confidence=min_confidence,
    )
    metrics.inc("get_causal_chain")

    try:
        service = _get_causal_service()
        return service.get_causal_chain(
            start_node_id=start_node_id,
            start_node_name=start_node_name,
            direction=direction,
            max_depth=max_depth,
            min_confidence=min_confidence,
        )
    except Exception as e:
        log_with_context(logger, "error", "get_causal_chain failed", error=str(e))
        return {"success": False, "error": str(e)}


def why_does(
    effect_name: str,
    domain: str = None,
    max_depth: int = 3,
    session_id: str = None,
    **kwargs
) -> Dict[str, Any]:
    """Explain why an effect happens."""
    log_with_context(logger, "info", "Tool: why_does", effect_name=effect_name, domain=domain, max_depth=max_depth)
    metrics.inc("why_does")

    try:
        service = _get_causal_service()
        return service.why_query(
            effect_name=effect_name,
            domain=domain,
            max_depth=max_depth,
            session_id=session_id,
        )
    except Exception as e:
        log_with_context(logger, "error", "why_does failed", error=str(e))
        return {"success": False, "error": str(e)}


def what_if(
    intervention_name: str,
    intervention_value: str = None,
    domain: str = None,
    max_depth: int = 3,
    session_id: str = None,
    **kwargs
) -> Dict[str, Any]:
    """Predict what happens if an intervention changes."""
    log_with_context(
        logger,
        "info",
        "Tool: what_if",
        intervention_name=intervention_name,
        intervention_value=intervention_value,
        domain=domain,
        max_depth=max_depth,
    )
    metrics.inc("what_if")

    try:
        service = _get_causal_service()
        return service.what_if_query(
            intervention_name=intervention_name,
            intervention_value=intervention_value,
            domain=domain,
            max_depth=max_depth,
            session_id=session_id,
        )
    except Exception as e:
        log_with_context(logger, "error", "what_if failed", error=str(e))
        return {"success": False, "error": str(e)}


def how_to_achieve(
    goal_name: str,
    domain: str = None,
    max_depth: int = 4,
    session_id: str = None,
    **kwargs
) -> Dict[str, Any]:
    """Find intervention points for achieving a goal."""
    log_with_context(logger, "info", "Tool: how_to_achieve", goal_name=goal_name, domain=domain, max_depth=max_depth)
    metrics.inc("how_to_achieve")

    try:
        service = _get_causal_service()
        return service.how_to_query(
            goal_name=goal_name,
            domain=domain,
            max_depth=max_depth,
            session_id=session_id,
        )
    except Exception as e:
        log_with_context(logger, "error", "how_to_achieve failed", error=str(e))
        return {"success": False, "error": str(e)}


def record_intervention(
    target_name: str,
    intervention_type: str,
    target_value: str,
    original_value: str = None,
    predicted_effects: List[Dict[str, Any]] = None,
    domain: str = None,
    session_id: str = None,
    **kwargs
) -> Dict[str, Any]:
    """Record an intervention for later verification."""
    log_with_context(
        logger,
        "info",
        "Tool: record_intervention",
        target_name=target_name,
        intervention_type=intervention_type,
        domain=domain,
    )
    metrics.inc("record_intervention")

    try:
        service = _get_causal_service()
        return service.record_intervention(
            target_name=target_name,
            intervention_type=intervention_type,
            target_value=target_value,
            original_value=original_value,
            predicted_effects=predicted_effects,
            domain=domain,
            session_id=session_id,
        )
    except Exception as e:
        log_with_context(logger, "error", "record_intervention failed", error=str(e))
        return {"success": False, "error": str(e)}


def verify_intervention_outcome(
    intervention_id: int,
    actual_effects: List[Dict[str, Any]],
    **kwargs
) -> Dict[str, Any]:
    """Verify predicted effects against observed intervention outcomes."""
    log_with_context(logger, "info", "Tool: verify_intervention_outcome", intervention_id=intervention_id)
    metrics.inc("verify_intervention_outcome")

    try:
        service = _get_causal_service()
        return service.record_intervention_outcome(
            intervention_id=intervention_id,
            actual_effects=actual_effects,
        )
    except Exception as e:
        log_with_context(logger, "error", "verify_intervention_outcome failed", error=str(e))
        return {"success": False, "error": str(e)}


def learn_causal_relationship(
    cause_description: str,
    effect_description: str,
    relationship_type: str = "causes",
    confidence: float = 0.5,
    mechanism: str = None,
    source: str = "user_feedback",
    domain: str = None,
    session_id: str = None,
    **kwargs
) -> Dict[str, Any]:
    """Learn a new causal relationship."""
    log_with_context(
        logger,
        "info",
        "Tool: learn_causal_relationship",
        cause_description=cause_description,
        effect_description=effect_description,
        relationship_type=relationship_type,
        confidence=confidence,
        domain=domain,
    )
    metrics.inc("learn_causal_relationship")

    try:
        service = _get_causal_service()
        return service.learn_causal_relationship(
            cause_description=cause_description,
            effect_description=effect_description,
            relationship_type=relationship_type,
            confidence=confidence,
            mechanism=mechanism,
            source=source,
            domain=domain,
            session_id=session_id,
        )
    except Exception as e:
        log_with_context(logger, "error", "learn_causal_relationship failed", error=str(e))
        return {"success": False, "error": str(e)}


def get_causal_summary(
    domain: str = None,
    **kwargs
) -> Dict[str, Any]:
    """Get summary stats for the causal graph."""
    log_with_context(logger, "info", "Tool: get_causal_summary", domain=domain)
    metrics.inc("get_causal_summary")

    try:
        service = _get_causal_service()
        return service.get_causal_summary(domain=domain)
    except Exception as e:
        log_with_context(logger, "error", "get_causal_summary failed", error=str(e))
        return {"success": False, "error": str(e)}
