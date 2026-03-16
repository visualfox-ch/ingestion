"""
Salience Router

Extracted from main.py - Phase 11/12.3 Salience Engine endpoints:
- Salience statistics and correlation analysis
- High-salience item retrieval
- Goal relevance updates
- Time-based decay
- Outcome-based reinforcement
"""

from fastapi import APIRouter
from typing import Dict, Any
from datetime import datetime, timedelta
import math

from ..observability import get_logger

logger = get_logger("jarvis.salience")
router = APIRouter(prefix="/salience", tags=["salience"])


# =============================================================================
# STATISTICS & ANALYSIS
# =============================================================================

@router.get("/stats")
def get_salience_stats():
    """
    Get aggregate salience statistics.

    Phase 12.3: Monitor outcome-based learning health.

    Returns:
        Stats about salience data across all items
    """
    from .. import postgres_state
    return postgres_state.get_salience_stats()


@router.get("/correlation")
def get_salience_correlation():
    """
    Analyze correlation between salience scores and actual decision outcomes.

    Phase 15.5: Validate salience accuracy against real-world usage.

    Returns:
        Correlation analysis with sample size, Pearson coefficient,
        high-salience accuracy, and calibration recommendations.
    """
    from .. import postgres_state

    # Get items with outcome data
    with postgres_state.get_cursor() as cur:
        cur.execute("""
            SELECT
                knowledge_item_id,
                salience_score,
                decision_impact,
                goal_relevance,
                surprise_factor,
                positive_outcomes,
                negative_outcomes,
                (positive_outcomes - negative_outcomes) as net_outcome
            FROM knowledge_salience
            WHERE positive_outcomes > 0 OR negative_outcomes > 0
        """)
        items = [dict(row) for row in cur.fetchall()]

    if len(items) < 5:
        return {
            "status": "insufficient_data",
            "sample_size": len(items),
            "message": "Need at least 5 items with outcome data for analysis",
            "recommendation": "Record more decision outcomes via /decision-outcome endpoint"
        }

    # Calculate statistics
    salience_scores = [i['salience_score'] or 0 for i in items]
    net_outcomes = [i['net_outcome'] or 0 for i in items]

    # Basic statistics without numpy
    n = len(salience_scores)
    mean_salience = sum(salience_scores) / n
    mean_outcome = sum(net_outcomes) / n

    # Pearson correlation (manual calculation)
    numerator = sum((s - mean_salience) * (o - mean_outcome)
                   for s, o in zip(salience_scores, net_outcomes))
    denom_salience = sum((s - mean_salience) ** 2 for s in salience_scores) ** 0.5
    denom_outcome = sum((o - mean_outcome) ** 2 for o in net_outcomes) ** 0.5

    if denom_salience > 0 and denom_outcome > 0:
        correlation = numerator / (denom_salience * denom_outcome)
    else:
        correlation = 0.0

    # High-salience accuracy: % of high-salience items (>0.6) with positive outcomes
    high_salience_items = [i for i in items if (i['salience_score'] or 0) >= 0.6]
    if high_salience_items:
        high_salience_positive = sum(1 for i in high_salience_items if (i['net_outcome'] or 0) > 0)
        high_salience_accuracy = high_salience_positive / len(high_salience_items)
    else:
        high_salience_accuracy = None

    # Interpretation
    if correlation > 0.7:
        interpretation = "Strong positive correlation - salience predicts outcomes well"
    elif correlation > 0.4:
        interpretation = "Moderate correlation - salience is useful but could improve"
    elif correlation > 0.1:
        interpretation = "Weak correlation - salience needs recalibration"
    elif correlation > -0.1:
        interpretation = "No correlation - salience formula may need revision"
    else:
        interpretation = "Negative correlation - salience is inversely related to outcomes"

    # Generate recommendations
    recommendations = []
    if correlation < 0.4:
        recommendations.append("Consider adjusting decision_impact weight (currently 35%)")
    if high_salience_accuracy and high_salience_accuracy < 0.8:
        recommendations.append(f"High-salience accuracy is {high_salience_accuracy:.0%}, target is 90%+")
    if mean_salience < 0.3:
        recommendations.append("Average salience is low - check if decay is too aggressive")
    if n < 20:
        recommendations.append("Collect more decision outcomes for reliable analysis")

    return {
        "status": "ok",
        "sample_size": n,
        "correlation": round(correlation, 4),
        "interpretation": interpretation,
        "statistics": {
            "mean_salience": round(mean_salience, 4),
            "mean_net_outcome": round(mean_outcome, 4),
            "high_salience_count": len(high_salience_items),
            "high_salience_accuracy": round(high_salience_accuracy, 4) if high_salience_accuracy else None
        },
        "recommendations": recommendations if recommendations else ["Salience calibration looks good"],
        "formula": "0.35*decision_impact + 0.30*goal_relevance + 0.20*surprise_factor + 0.075 (baseline)"
    }


@router.get("/high")
def get_high_salience_items(
    limit: int = 20,
    min_salience: float = 0.3
):
    """
    Get knowledge items with high salience scores.

    Phase 12.3: Find knowledge that has led to good decisions.

    Args:
        limit: Max items to return
        min_salience: Minimum salience score

    Returns:
        List of high-salience knowledge items
    """
    from .. import postgres_state
    items = postgres_state.get_high_salience_items(limit=limit, min_salience=min_salience)
    return {"items": items, "count": len(items)}


# =============================================================================
# UPDATE ENDPOINTS
# =============================================================================

@router.post("/goal-relevance")
def update_goal_relevance_endpoint(
    knowledge_item_id: str,
    goal_relevance: float,
    goal_id: str = None
):
    """
    Update goal relevance for a knowledge item.

    Phase 12.3: Link knowledge to active goals.

    Args:
        knowledge_item_id: ID of the knowledge item
        goal_relevance: Relevance score (0.0-1.0)
        goal_id: Optional goal ID for tracking

    Returns:
        Success status
    """
    from .. import postgres_state
    success = postgres_state.update_goal_relevance(
        knowledge_item_id=knowledge_item_id,
        goal_relevance=goal_relevance,
        goal_id=goal_id
    )
    return {"success": success, "knowledge_item_id": knowledge_item_id}


@router.get("/{knowledge_item_id}")
def get_salience(knowledge_item_id: str):
    """
    Get salience data for a specific knowledge item.

    Phase 12.3: View decision impact, goal relevance, surprise factor.

    Returns:
        Salience breakdown for the item
    """
    from .. import postgres_state
    salience = postgres_state.get_knowledge_salience(knowledge_item_id)
    if not salience:
        return {"error": "No salience data found", "knowledge_item_id": knowledge_item_id}
    return salience


# =============================================================================
# DECAY ENDPOINTS
# =============================================================================

@router.post("/decay")
def decay_salience_endpoint(dry_run: bool = True):
    """
    Apply time-based decay to old knowledge items (PostgreSQL salience).

    Phase 12.3: Automatic memory hygiene with 60-day half-life.

    Args:
        dry_run: If true, only show what would be decayed without making changes

    Returns:
        List of facts that were/would be decayed
    """
    from .. import postgres_state

    # Get items older than 60 days with salience > 0.1
    cutoff_date = datetime.now() - timedelta(days=60)

    with postgres_state.get_cursor() as cur:
        cur.execute("""
            SELECT ks.knowledge_item_id, ks.salience_score, ks.updated_at,
                   EXTRACT(EPOCH FROM (NOW() - ks.updated_at)) / 86400 as age_days
            FROM knowledge_salience ks
            WHERE ks.updated_at < %s AND ks.salience_score > 0.1
            ORDER BY ks.salience_score ASC
            LIMIT 100
        """, (cutoff_date,))
        old_items = [dict(row) for row in cur.fetchall()]

        if not dry_run:
            # Apply decay: salience_score *= exp(-age_days / 60)
            # This gives 60-day half-life
            for item in old_items:
                age_days = item["age_days"]
                decay_factor = math.exp(-age_days / 60.0)
                new_salience = max(0.1, item["salience_score"] * decay_factor)

                cur.execute("""
                    UPDATE knowledge_salience
                    SET salience_score = %s, updated_at = NOW()
                    WHERE knowledge_item_id = %s
                """, (new_salience, item["knowledge_item_id"]))

                item["new_salience"] = round(new_salience, 3)
                item["decay_factor"] = round(decay_factor, 3)

    return {
        "dry_run": dry_run,
        "items_affected": len(old_items),
        "items": old_items[:20]  # Limit output to first 20
    }


@router.post("/init")
def init_salience_columns():
    """Add salience columns to knowledge_item table (safe migration)"""
    from .. import knowledge_db

    success = knowledge_db.add_salience_columns()
    return {"status": "success" if success else "error"}


@router.post("/decay/batch")
def decay_salience_batch(decay_rate: float = 0.05, min_salience: float = 0.1):
    """
    Apply time-based decay to salience components.

    Decays goal_relevance and surprise_factor (novelty wears off).
    decision_impact is NOT decayed (learning persists).

    Call daily via n8n cron.
    """
    from .. import knowledge_db

    result = knowledge_db.decay_salience_batch(decay_rate=decay_rate, min_salience=min_salience)
    return {"status": "processed", "result": result}


@router.post("/update/{item_id}")
def update_item_salience(
    item_id: int,
    decision_impact: float = None,
    goal_relevance: float = None,
    surprise_factor: float = None
):
    """
    Update salience components for a knowledge item.

    Pass only the components you want to update. Omitted components keep their current value.
    Salience score is automatically recomputed.
    """
    from .. import knowledge_db

    result = knowledge_db.update_knowledge_salience(
        item_id=item_id,
        decision_impact=decision_impact,
        goal_relevance=goal_relevance,
        surprise_factor=surprise_factor
    )
    if result:
        return {"status": "updated", "item": result}
    return {"status": "error", "message": "Failed to update salience or item not found"}


@router.post("/reinforce/{item_id}")
def reinforce_from_decision_outcome(
    item_id: int,
    outcome_rating: int,
    was_used: bool = True
):
    """
    Reinforce salience based on decision outcome.

    Called when knowledge was used in a decision with a measurable outcome.
    - Positive outcomes (7-10) increase decision_impact
    - Negative outcomes (1-4) decrease decision_impact

    Args:
        item_id: Knowledge item ID
        outcome_rating: 1-10 rating of the decision outcome
        was_used: Whether this knowledge was actually used (default True)
    """
    from .. import knowledge_db

    result = knowledge_db.reinforce_from_decision(
        item_id=item_id,
        outcome_rating=outcome_rating,
        was_used=was_used
    )
    if result:
        return {"status": "reinforced", "item": result}
    return {"status": "skipped" if not was_used else "error"}


@router.post("/goal/{item_id}")
def set_item_goal_relevance(item_id: int, goal_id: str, relevance: float):
    """
    Set goal relevance for a knowledge item.

    Call when linking knowledge to active goals/priorities.
    Higher relevance = knowledge is more important for current objectives.
    """
    from .. import knowledge_db

    result = knowledge_db.set_goal_relevance(item_id, goal_id, relevance)
    if result:
        return {"status": "updated", "item": result}
    return {"status": "error", "message": "Failed to set goal relevance"}


@router.post("/surprising/{item_id}")
def mark_item_surprising(item_id: int, surprise_level: float = 0.8):
    """
    Mark a knowledge item as surprising/novel.

    Surprise factor decays over time (daily decay batch).
    Use when discovering unexpected information.
    """
    from .. import knowledge_db

    result = knowledge_db.mark_as_surprising(item_id, surprise_level)
    if result:
        return {"status": "marked", "item": result}
    return {"status": "error", "message": "Failed to mark as surprising"}
