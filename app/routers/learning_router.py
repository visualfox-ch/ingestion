"""
Learning Router - Phase 19.5

Endpoints to view and manage Jarvis's auto-learned knowledge.
"""
from fastapi import APIRouter, Query
from typing import Optional

from ..observability import get_logger

logger = get_logger("jarvis.learning_router")
router = APIRouter(prefix="/learning", tags=["learning"])


@router.get("/stats")
def get_learning_stats(days: int = Query(7, description="Days to analyze")):
    """Get tool usage statistics for the last N days."""
    from ..services.auto_learner import get_tool_stats
    return get_tool_stats(days)


@router.get("/facts")
def get_learned_facts(
    fact_type: Optional[str] = Query(None, description="Filter by type: jarvis_capability, tool_pattern, error_pattern"),
    min_confidence: float = Query(0.0, description="Minimum confidence threshold")
):
    """Get facts that Jarvis has learned automatically."""
    from ..services.auto_learner import get_learned_facts
    facts = get_learned_facts(fact_type, min_confidence)
    return {"facts": facts, "count": len(facts)}


@router.get("/patterns")
def get_query_patterns(limit: int = Query(20, description="Max patterns to return")):
    """Get successful query patterns that Jarvis has learned."""
    import sqlite3
    from pathlib import Path
    import os

    BRAIN_ROOT = Path(os.environ.get("BRAIN_ROOT", "/brain"))
    db_path = BRAIN_ROOT / "system" / "state" / "jarvis_learning.db"

    if not db_path.exists():
        return {"patterns": [], "message": "No learning data yet"}

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.execute("""
        SELECT query_pattern, tools_used, success, occurrence_count, feedback_score, last_seen
        FROM query_patterns
        ORDER BY occurrence_count DESC, last_seen DESC
        LIMIT ?
    """, (limit,))

    patterns = [dict(row) for row in cursor.fetchall()]
    conn.close()

    return {"patterns": patterns, "count": len(patterns)}


@router.post("/facts")
def add_learned_fact(
    fact_type: str,
    fact_key: str,
    fact_value: str,
    confidence: float = Query(0.7, description="Confidence 0.0-1.0"),
    source: str = Query("manual", description="Source of this fact")
):
    """Manually add a learned fact."""
    from ..services.auto_learner import store_learned_fact

    success = store_learned_fact(
        fact_type=fact_type,
        fact_key=fact_key,
        fact_value=fact_value,
        confidence=confidence,
        source=source
    )

    return {
        "success": success,
        "fact_type": fact_type,
        "fact_key": fact_key
    }


@router.get("/recommendations")
def get_tool_recommendations(query: str = Query(..., description="Query to get recommendations for")):
    """Get tool recommendations based on similar past queries."""
    from ..services.auto_learner import get_tool_recommendations as get_recs
    recommendations = get_recs(query, top_n=5)
    return {"query": query, "recommendations": recommendations}


@router.post("/decay")
def run_decay(
    days_threshold: int = Query(14, description="Days before decay starts"),
    decay_rate: float = Query(0.05, description="Confidence reduction per run")
):
    """Apply confidence decay to old facts."""
    from ..services.auto_learner import decay_old_facts
    result = decay_old_facts(days_threshold, decay_rate)
    return result


@router.post("/migrate")
def migrate_facts(
    min_confidence: float = Query(0.8, description="Minimum confidence to migrate")
):
    """Migrate high-confidence facts to main facts system."""
    from ..services.auto_learner import migrate_to_main_facts
    result = migrate_to_main_facts(min_confidence)
    return result


@router.get("/prompt-hints")
def get_prompt_hints(query: str = Query(..., description="Query to get hints for")):
    """Get auto-learning hints for a query (used by prompt assembler)."""
    from ..services.auto_learner import get_prompt_hints
    hints = get_prompt_hints(query)
    return {"query": query, "hints": hints}


@router.get("/summary")
def get_learning_summary():
    """Get a summary of all learning activity."""
    import sqlite3
    from pathlib import Path
    import os

    BRAIN_ROOT = Path(os.environ.get("BRAIN_ROOT", "/brain"))
    db_path = BRAIN_ROOT / "system" / "state" / "jarvis_learning.db"

    if not db_path.exists():
        return {
            "status": "no_data",
            "message": "Learning database not initialized yet. Will be created after first tool usage."
        }

    try:
        conn = sqlite3.connect(str(db_path))

        # Tool usage stats
        cursor = conn.execute("SELECT COUNT(*) FROM tool_usage")
        tool_usage_count = cursor.fetchone()[0]

        cursor = conn.execute("SELECT COUNT(*) FROM tool_usage WHERE success = 1")
        successful_calls = cursor.fetchone()[0]

        # Pattern stats
        cursor = conn.execute("SELECT COUNT(*) FROM query_patterns")
        pattern_count = cursor.fetchone()[0]

        # Facts stats
        cursor = conn.execute("SELECT COUNT(*) FROM learned_facts")
        facts_count = cursor.fetchone()[0]

        cursor = conn.execute("SELECT AVG(confidence) FROM learned_facts")
        avg_confidence = cursor.fetchone()[0] or 0

        # Top 5 tools
        cursor = conn.execute("""
            SELECT tool_name, COUNT(*) as cnt
            FROM tool_usage
            GROUP BY tool_name
            ORDER BY cnt DESC
            LIMIT 5
        """)
        top_tools = [{"tool": row[0], "calls": row[1]} for row in cursor.fetchall()]

        conn.close()

        return {
            "status": "active",
            "tool_usage": {
                "total_calls": tool_usage_count,
                "successful": successful_calls,
                "success_rate": successful_calls / tool_usage_count if tool_usage_count > 0 else 0
            },
            "patterns": {
                "total": pattern_count
            },
            "facts": {
                "total": facts_count,
                "avg_confidence": round(avg_confidence, 2)
            },
            "top_tools": top_tools
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}
