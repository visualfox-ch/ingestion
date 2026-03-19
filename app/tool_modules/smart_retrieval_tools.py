"""
Smart Retrieval Tools - U3: Memory Ranking

Exposes smart multi-signal retrieval to Jarvis:
- Adaptive strategy selection
- Multi-signal ranking (semantic, keyword, recency, trust, context)
- Memory type filtering
- Retrieval strategy control
"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def smart_recall(
    query: str,
    strategy: str = "adaptive",
    memory_types: List[str] = None,
    max_results: int = 10,
    min_confidence: float = 0.3,
    time_range_days: int = None,
    include_scores: bool = False
) -> Dict[str, Any]:
    """
    Smart memory retrieval with multi-signal ranking.

    Args:
        query: What to search for
        strategy: semantic, keyword, hybrid, temporal, relational, contextual, adaptive
        memory_types: Filter by type (fact, preference, pattern, event, conversation, knowledge)
        max_results: Maximum results to return
        min_confidence: Minimum confidence threshold (0.0-1.0)
        time_range_days: Only search within N days (optional)
        include_scores: Include detailed scoring breakdown

    Returns:
        Ranked memory results with relevance scores
    """
    try:
        from app.services.smart_retrieval import (
            get_smart_retrieval, RetrievalContext, RetrievalStrategy, MemoryType
        )

        retrieval = get_smart_retrieval()

        # Map strategy string to enum
        strategy_map = {
            "semantic": RetrievalStrategy.SEMANTIC,
            "keyword": RetrievalStrategy.KEYWORD,
            "hybrid": RetrievalStrategy.HYBRID,
            "temporal": RetrievalStrategy.TEMPORAL,
            "relational": RetrievalStrategy.RELATIONAL,
            "contextual": RetrievalStrategy.CONTEXTUAL,
            "adaptive": RetrievalStrategy.ADAPTIVE,
        }
        strategy_enum = strategy_map.get(strategy.lower(), RetrievalStrategy.ADAPTIVE)

        # Map memory types
        type_map = {
            "fact": MemoryType.FACT,
            "preference": MemoryType.PREFERENCE,
            "pattern": MemoryType.PATTERN,
            "event": MemoryType.EVENT,
            "conversation": MemoryType.CONVERSATION,
            "relationship": MemoryType.RELATIONSHIP,
            "knowledge": MemoryType.KNOWLEDGE,
            "all": MemoryType.ALL,
        }
        types = [type_map.get(t.lower(), MemoryType.ALL) for t in (memory_types or ["all"])]

        # Build time range
        time_range = None
        if time_range_days:
            end = datetime.now()
            start = end - timedelta(days=time_range_days)
            time_range = (start, end)

        # Create context
        context = RetrievalContext(
            user_id="micha",
            query=query,
            namespace="private",
            memory_types=types,
            time_range=time_range,
            min_confidence=min_confidence,
            max_results=max_results,
            include_related=True
        )

        # Execute retrieval
        response = retrieval.retrieve(context, strategy=strategy_enum)

        # Format results
        results = []
        for r in response.results:
            item = {
                "content": r.content,
                "type": r.memory_type.value if hasattr(r.memory_type, 'value') else str(r.memory_type),
                "source": r.source,
                "score": round(r.final_score, 3),
                "created": r.created_at.isoformat() if r.created_at else None
            }
            if include_scores:
                item["scores"] = {
                    "semantic": round(r.semantic_score, 3),
                    "keyword": round(r.keyword_score, 3),
                    "recency": round(r.recency_score, 3),
                    "access": round(r.access_score, 3),
                    "trust": round(r.trust_score, 3),
                    "context": round(r.context_score, 3)
                }
            results.append(item)

        return {
            "success": True,
            "query": query,
            "strategy_used": response.strategy_used.value,
            "results": results,
            "count": len(results),
            "total_candidates": response.total_candidates,
            "retrieval_time_ms": round(response.retrieval_time_ms, 1),
            "query_understanding": response.query_understanding
        }

    except Exception as e:
        logger.error(f"Smart recall failed: {e}")
        return {"success": False, "error": str(e)}


def get_retrieval_strategies() -> Dict[str, Any]:
    """
    Get available retrieval strategies and their configurations.

    Returns:
        List of strategies with descriptions and signal weights
    """
    try:
        from app.services.smart_retrieval import STRATEGY_WEIGHTS, DEFAULT_WEIGHTS

        strategies = []
        descriptions = {
            "semantic": "Vector similarity search - best for conceptual queries",
            "keyword": "BM25 keyword matching - best for specific terms",
            "hybrid": "Combined semantic + keyword - balanced approach",
            "temporal": "Recency-weighted - best for recent events",
            "relational": "Entity graph traversal - best for connected information",
            "contextual": "Context-aware matching - best for session continuity",
            "adaptive": "Auto-selects based on query analysis"
        }

        for name, weights in STRATEGY_WEIGHTS.items():
            strategies.append({
                "name": name.value if hasattr(name, 'value') else str(name),
                "description": descriptions.get(name.value if hasattr(name, 'value') else str(name), ""),
                "weights": {k: round(v, 2) for k, v in weights.items()}
            })

        return {
            "success": True,
            "strategies": strategies,
            "default_weights": {k: round(v, 2) for k, v in DEFAULT_WEIGHTS.items()},
            "signals": ["semantic", "keyword", "recency", "access", "trust", "context"]
        }

    except Exception as e:
        logger.error(f"Get retrieval strategies failed: {e}")
        return {"success": False, "error": str(e)}


def analyze_query_for_retrieval(
    query: str
) -> Dict[str, Any]:
    """
    Analyze a query to determine optimal retrieval strategy.

    Args:
        query: The query to analyze

    Returns:
        Query analysis with suggested strategy and extracted entities
    """
    try:
        from app.services.smart_retrieval import get_smart_retrieval

        retrieval = get_smart_retrieval()
        analysis = retrieval.query_analyzer.analyze(query)

        return {
            "success": True,
            "query": query,
            "suggested_strategy": analysis.get("suggested_strategy", "adaptive").value
                if hasattr(analysis.get("suggested_strategy"), 'value')
                else str(analysis.get("suggested_strategy", "adaptive")),
            "query_type": analysis.get("query_type", "unknown"),
            "extracted_entities": analysis.get("extracted_entities", []),
            "temporal_hints": analysis.get("temporal_hints", []),
            "confidence": round(analysis.get("confidence", 0.5), 2)
        }

    except Exception as e:
        logger.error(f"Analyze query failed: {e}")
        return {"success": False, "error": str(e)}


def get_memory_stats() -> Dict[str, Any]:
    """
    Get statistics about stored memories and retrieval performance.

    Returns:
        Memory statistics including counts, access patterns, quality metrics
    """
    try:
        from app.postgres_state import get_dict_cursor

        with get_dict_cursor() as cur:
            # Fact counts by category
            cur.execute("""
                SELECT category, COUNT(*) as count, AVG(trust_score) as avg_trust
                FROM facts
                GROUP BY category
                ORDER BY count DESC
            """)
            facts_by_category = [dict(r) for r in cur.fetchall()]

            # Recent retrieval stats
            cur.execute("""
                SELECT
                    COUNT(*) as total_requests,
                    AVG(result_count) as avg_results,
                    AVG(retrieval_time_ms) as avg_time_ms
                FROM retrieval_requests
                WHERE created_at > NOW() - INTERVAL '7 days'
            """)
            retrieval_stats = dict(cur.fetchone() or {})

            # Importance distribution
            cur.execute("""
                SELECT
                    CASE
                        WHEN importance_score >= 0.8 THEN 'critical'
                        WHEN importance_score >= 0.6 THEN 'high'
                        WHEN importance_score >= 0.4 THEN 'medium'
                        ELSE 'low'
                    END as tier,
                    COUNT(*) as count
                FROM importance_assessments
                GROUP BY tier
                ORDER BY count DESC
            """)
            importance_dist = [dict(r) for r in cur.fetchall()]

        return {
            "success": True,
            "facts": {
                "by_category": facts_by_category,
                "total": sum(f["count"] for f in facts_by_category)
            },
            "retrieval": {
                "last_7_days": retrieval_stats
            },
            "importance": {
                "distribution": importance_dist
            }
        }

    except Exception as e:
        logger.error(f"Get memory stats failed: {e}")
        return {"success": False, "error": str(e)}


# Tool definitions for registration
SMART_RETRIEVAL_TOOLS = [
    {
        "name": "smart_recall",
        "description": "Smart memory retrieval with multi-signal ranking. Better than basic recall_facts - uses semantic similarity, keyword matching, recency, trust scores, and context relevance.",
        "function": smart_recall,
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What to search for in memories"
                },
                "strategy": {
                    "type": "string",
                    "enum": ["semantic", "keyword", "hybrid", "temporal", "relational", "contextual", "adaptive"],
                    "default": "adaptive",
                    "description": "Retrieval strategy (adaptive auto-selects)"
                },
                "memory_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter by types: fact, preference, pattern, event, conversation, knowledge"
                },
                "max_results": {
                    "type": "integer",
                    "default": 10,
                    "description": "Maximum results"
                },
                "min_confidence": {
                    "type": "number",
                    "default": 0.3,
                    "description": "Minimum confidence threshold (0.0-1.0)"
                },
                "time_range_days": {
                    "type": "integer",
                    "description": "Only search within N days (optional)"
                },
                "include_scores": {
                    "type": "boolean",
                    "default": False,
                    "description": "Include detailed score breakdown"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "get_retrieval_strategies",
        "description": "Get available memory retrieval strategies and their signal weights.",
        "function": get_retrieval_strategies,
        "parameters": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "analyze_query_for_retrieval",
        "description": "Analyze a query to determine the optimal retrieval strategy before searching.",
        "function": analyze_query_for_retrieval,
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The query to analyze"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "get_memory_stats",
        "description": "Get statistics about stored memories, retrieval performance, and importance distribution.",
        "function": get_memory_stats,
        "parameters": {
            "type": "object",
            "properties": {}
        }
    }
]


def get_smart_retrieval_tools() -> list:
    """Return all smart retrieval tool definitions."""
    return SMART_RETRIEVAL_TOOLS
