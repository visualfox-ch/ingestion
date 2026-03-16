"""
Causal Knowledge Graph Tools - Phase A3 (AGI Evolution)

Tools for Jarvis to build and query causal knowledge:
- Learn cause-effect relationships
- Answer why/what-if/how-to questions
- Track interventions and outcomes

Based on Pearl's Causal Inference (2009).
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def learn_causal_relationship(
    cause: str,
    effect: str,
    relationship_type: str = "causes",
    confidence: float = 0.5,
    mechanism: str = None,
    domain: str = None,
    session_id: str = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Learn a new causal relationship.

    Use this when you observe or are told about cause-effect relationships.

    Args:
        cause: What causes the effect
        effect: What is caused
        relationship_type: causes, enables, prevents, influences, requires, triggers, inhibits
        confidence: How confident (0-1)
        mechanism: How does the cause lead to the effect?
        domain: Category/domain

    Returns:
        Dict with confirmation
    """
    try:
        from app.services.causal_knowledge_service import get_causal_service

        service = get_causal_service()
        return service.learn_causal_relationship(
            cause_description=cause,
            effect_description=effect,
            relationship_type=relationship_type,
            confidence=confidence,
            mechanism=mechanism,
            domain=domain,
            session_id=session_id
        )

    except Exception as e:
        logger.error(f"Learn causal relationship failed: {e}")
        return {"success": False, "error": str(e)}


def why_does(
    effect: str,
    domain: str = None,
    max_depth: int = 3,
    session_id: str = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Answer "Why does X happen?"

    Finds the causal chain that leads to an effect.

    Args:
        effect: What you want to understand
        domain: Limit to specific domain
        max_depth: How far back to trace causes

    Returns:
        Dict with reasoning chain and answer
    """
    try:
        from app.services.causal_knowledge_service import get_causal_service

        service = get_causal_service()
        return service.why_query(
            effect_name=effect,
            domain=domain,
            max_depth=max_depth,
            session_id=session_id
        )

    except Exception as e:
        logger.error(f"Why query failed: {e}")
        return {"success": False, "error": str(e)}


def what_if(
    intervention: str,
    new_value: str = None,
    domain: str = None,
    max_depth: int = 3,
    session_id: str = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Answer "What if X changes/happens?"

    Predicts the effects of an intervention using do-calculus.

    Args:
        intervention: What changes
        new_value: The new value (optional)
        domain: Limit to specific domain
        max_depth: How far to trace effects

    Returns:
        Dict with predicted effects
    """
    try:
        from app.services.causal_knowledge_service import get_causal_service

        service = get_causal_service()
        return service.what_if_query(
            intervention_name=intervention,
            intervention_value=new_value,
            domain=domain,
            max_depth=max_depth,
            session_id=session_id
        )

    except Exception as e:
        logger.error(f"What-if query failed: {e}")
        return {"success": False, "error": str(e)}


def how_to_achieve(
    goal: str,
    domain: str = None,
    max_depth: int = 4,
    session_id: str = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Answer "How to achieve X?"

    Finds manipulable intervention points that lead to the goal.

    Args:
        goal: What you want to achieve
        domain: Limit to specific domain
        max_depth: How far back to search

    Returns:
        Dict with intervention points
    """
    try:
        from app.services.causal_knowledge_service import get_causal_service

        service = get_causal_service()
        return service.how_to_query(
            goal_name=goal,
            domain=domain,
            max_depth=max_depth,
            session_id=session_id
        )

    except Exception as e:
        logger.error(f"How-to query failed: {e}")
        return {"success": False, "error": str(e)}


def get_causal_chain(
    node: str,
    direction: str = "effects",
    max_depth: int = 3,
    domain: str = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Get the causal chain from a node.

    Args:
        node: Starting node name
        direction: "effects" (what does this cause) or "causes" (what causes this)
        max_depth: How deep to trace
        domain: Limit to specific domain

    Returns:
        Dict with causal chain
    """
    try:
        from app.services.causal_knowledge_service import get_causal_service

        service = get_causal_service()

        # First get the node
        node_result = service.get_node(node_name=node, domain=domain)
        if not node_result["success"]:
            return {"success": False, "error": f"Node '{node}' not found"}

        return service.get_causal_chain(
            start_node_id=node_result["node"]["id"],
            direction=direction,
            max_depth=max_depth
        )

    except Exception as e:
        logger.error(f"Get causal chain failed: {e}")
        return {"success": False, "error": str(e)}


def record_intervention(
    target: str,
    action: str,
    new_value: str,
    old_value: str = None,
    expected_effects: List[Dict] = None,
    domain: str = None,
    session_id: str = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Record an intervention for later verification.

    Use this when you or the user take an action that should have causal effects.

    Args:
        target: What was changed
        action: Type of change (set, increase, decrease, toggle)
        new_value: The new value
        old_value: The old value
        expected_effects: What you predict will happen

    Returns:
        Dict with intervention ID for later outcome recording
    """
    try:
        from app.services.causal_knowledge_service import get_causal_service

        service = get_causal_service()
        return service.record_intervention(
            target_name=target,
            intervention_type=action,
            target_value=new_value,
            original_value=old_value,
            predicted_effects=expected_effects,
            domain=domain,
            session_id=session_id
        )

    except Exception as e:
        logger.error(f"Record intervention failed: {e}")
        return {"success": False, "error": str(e)}


def verify_intervention_outcome(
    intervention_id: int,
    actual_effects: List[Dict],
    **kwargs
) -> Dict[str, Any]:
    """
    Verify the outcome of a recorded intervention.

    Updates the causal model based on what actually happened.

    Args:
        intervention_id: ID from record_intervention
        actual_effects: What actually happened [{node_name, actual_value, was_predicted}]

    Returns:
        Dict with prediction accuracy
    """
    try:
        from app.services.causal_knowledge_service import get_causal_service

        service = get_causal_service()
        return service.record_intervention_outcome(
            intervention_id=intervention_id,
            actual_effects=actual_effects
        )

    except Exception as e:
        logger.error(f"Verify intervention outcome failed: {e}")
        return {"success": False, "error": str(e)}


def find_causal_nodes(
    search_term: str = None,
    node_type: str = None,
    domain: str = None,
    limit: int = 20,
    **kwargs
) -> Dict[str, Any]:
    """
    Find nodes in the causal graph.

    Args:
        search_term: Search in name/description
        node_type: Filter by type (event, state, action, entity, concept)
        domain: Filter by domain
        limit: Max results

    Returns:
        Dict with matching nodes
    """
    try:
        from app.services.causal_knowledge_service import get_causal_service

        service = get_causal_service()
        return service.find_nodes(
            search_term=search_term,
            node_type=node_type,
            domain=domain,
            limit=limit
        )

    except Exception as e:
        logger.error(f"Find causal nodes failed: {e}")
        return {"success": False, "error": str(e)}


def get_causal_summary(
    domain: str = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Get summary of the causal knowledge graph.

    Shows nodes, edges, queries, and intervention statistics.

    Args:
        domain: Limit to specific domain

    Returns:
        Dict with causal graph statistics
    """
    try:
        from app.services.causal_knowledge_service import get_causal_service

        service = get_causal_service()
        return service.get_causal_summary(domain=domain)

    except Exception as e:
        logger.error(f"Get causal summary failed: {e}")
        return {"success": False, "error": str(e)}


def add_causal_node(
    name: str,
    node_type: str,
    domain: str = None,
    description: str = None,
    is_observable: bool = True,
    is_manipulable: bool = False,
    typical_values: List[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Add a node to the causal graph.

    Args:
        name: Node name
        node_type: Type (event, state, action, entity, concept)
        domain: Domain/category
        description: Description
        is_observable: Can we observe this?
        is_manipulable: Can we intervene on this?
        typical_values: Typical values/states

    Returns:
        Dict with node info
    """
    try:
        from app.services.causal_knowledge_service import get_causal_service

        service = get_causal_service()
        return service.add_node(
            node_name=name,
            node_type=node_type,
            domain=domain,
            description=description,
            is_observable=is_observable,
            is_manipulable=is_manipulable,
            typical_values=typical_values
        )

    except Exception as e:
        logger.error(f"Add causal node failed: {e}")
        return {"success": False, "error": str(e)}


# Tool definitions for Claude
CAUSAL_TOOLS = [
    {
        "name": "learn_causal_relationship",
        "description": "Learn a cause-effect relationship. Use when observing or told about causal connections.",
        "input_schema": {
            "type": "object",
            "properties": {
                "cause": {
                    "type": "string",
                    "description": "What causes the effect"
                },
                "effect": {
                    "type": "string",
                    "description": "What is caused"
                },
                "relationship_type": {
                    "type": "string",
                    "enum": ["causes", "enables", "prevents", "influences", "requires", "triggers", "inhibits", "correlates"],
                    "description": "Type of causal relationship"
                },
                "confidence": {
                    "type": "number",
                    "description": "Confidence level 0-1 (default: 0.5)"
                },
                "mechanism": {
                    "type": "string",
                    "description": "How does the cause lead to the effect?"
                },
                "domain": {
                    "type": "string",
                    "description": "Domain/category"
                }
            },
            "required": ["cause", "effect"]
        }
    },
    {
        "name": "why_does",
        "description": "Answer 'Why does X happen?' by finding causal ancestors.",
        "input_schema": {
            "type": "object",
            "properties": {
                "effect": {
                    "type": "string",
                    "description": "What you want to understand"
                },
                "domain": {
                    "type": "string",
                    "description": "Limit to specific domain"
                },
                "max_depth": {
                    "type": "integer",
                    "description": "How far back to trace causes (default: 3)"
                }
            },
            "required": ["effect"]
        }
    },
    {
        "name": "what_if",
        "description": "Answer 'What if X changes?' by predicting intervention effects (do-calculus).",
        "input_schema": {
            "type": "object",
            "properties": {
                "intervention": {
                    "type": "string",
                    "description": "What changes"
                },
                "new_value": {
                    "type": "string",
                    "description": "The new value (optional)"
                },
                "domain": {
                    "type": "string",
                    "description": "Limit to specific domain"
                },
                "max_depth": {
                    "type": "integer",
                    "description": "How far to trace effects (default: 3)"
                }
            },
            "required": ["intervention"]
        }
    },
    {
        "name": "how_to_achieve",
        "description": "Answer 'How to achieve X?' by finding manipulable intervention points.",
        "input_schema": {
            "type": "object",
            "properties": {
                "goal": {
                    "type": "string",
                    "description": "What you want to achieve"
                },
                "domain": {
                    "type": "string",
                    "description": "Limit to specific domain"
                },
                "max_depth": {
                    "type": "integer",
                    "description": "How far back to search (default: 4)"
                }
            },
            "required": ["goal"]
        }
    },
    {
        "name": "get_causal_chain",
        "description": "Get the causal chain from a node - what it causes or what causes it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "node": {
                    "type": "string",
                    "description": "Starting node name"
                },
                "direction": {
                    "type": "string",
                    "enum": ["effects", "causes"],
                    "description": "effects (what this causes) or causes (what causes this)"
                },
                "max_depth": {
                    "type": "integer",
                    "description": "How deep to trace (default: 3)"
                },
                "domain": {
                    "type": "string",
                    "description": "Limit to specific domain"
                }
            },
            "required": ["node"]
        }
    },
    {
        "name": "record_intervention",
        "description": "Record an intervention for later verification. Use when taking actions with causal effects.",
        "input_schema": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "What was changed"
                },
                "action": {
                    "type": "string",
                    "enum": ["set", "increase", "decrease", "toggle"],
                    "description": "Type of change"
                },
                "new_value": {
                    "type": "string",
                    "description": "The new value"
                },
                "old_value": {
                    "type": "string",
                    "description": "The old value"
                },
                "expected_effects": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "Predicted effects [{node_name, predicted_value, confidence}]"
                },
                "domain": {
                    "type": "string",
                    "description": "Domain"
                }
            },
            "required": ["target", "action", "new_value"]
        }
    },
    {
        "name": "verify_intervention_outcome",
        "description": "Verify intervention outcome to improve causal model.",
        "input_schema": {
            "type": "object",
            "properties": {
                "intervention_id": {
                    "type": "integer",
                    "description": "ID from record_intervention"
                },
                "actual_effects": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "What actually happened [{node_name, actual_value, was_predicted}]"
                }
            },
            "required": ["intervention_id", "actual_effects"]
        }
    },
    {
        "name": "find_causal_nodes",
        "description": "Find nodes in the causal knowledge graph.",
        "input_schema": {
            "type": "object",
            "properties": {
                "search_term": {
                    "type": "string",
                    "description": "Search in name/description"
                },
                "node_type": {
                    "type": "string",
                    "enum": ["event", "state", "action", "entity", "concept"],
                    "description": "Filter by type"
                },
                "domain": {
                    "type": "string",
                    "description": "Filter by domain"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default: 20)"
                }
            }
        }
    },
    {
        "name": "get_causal_summary",
        "description": "Get statistics of the causal knowledge graph.",
        "input_schema": {
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "Limit to specific domain"
                }
            }
        }
    },
    {
        "name": "add_causal_node",
        "description": "Add a node to the causal graph.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Node name"
                },
                "node_type": {
                    "type": "string",
                    "enum": ["event", "state", "action", "entity", "concept"],
                    "description": "Node type"
                },
                "domain": {
                    "type": "string",
                    "description": "Domain/category"
                },
                "description": {
                    "type": "string",
                    "description": "Description"
                },
                "is_observable": {
                    "type": "boolean",
                    "description": "Can we observe this? (default: true)"
                },
                "is_manipulable": {
                    "type": "boolean",
                    "description": "Can we intervene on this? (default: false)"
                },
                "typical_values": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Typical values/states"
                }
            },
            "required": ["name", "node_type"]
        }
    }
]
