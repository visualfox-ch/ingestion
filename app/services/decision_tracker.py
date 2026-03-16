"""
Decision Tracker - Phase 3.2

Tracks decisions and learns from outcomes:
- Records decisions made during query processing
- Tracks outcomes and effectiveness
- Provides decision history and analysis
- Learns patterns for better future decisions
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
import json
import hashlib

from ..postgres_state import get_cursor

logger = logging.getLogger(__name__)

# Decision categories
DECISION_CATEGORIES = [
    'tool_selection',      # Which tool to use
    'response_style',      # How to format response
    'context_inclusion',   # What context to include
    'clarification',       # Whether to ask for clarification
    'delegation',          # Whether to delegate to subagent
    'autonomy',           # Whether to act autonomously
    'safety'              # Safety-related decisions
]


class DecisionTracker:
    """
    Tracks and analyzes decisions made during query processing.

    Provides insight into decision patterns and helps improve
    future decision-making through outcome tracking.
    """

    def __init__(self):
        self._ensure_tables()

    def _ensure_tables(self):
        """Ensure decision tracking tables exist."""
        try:
            with get_cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS decision_log (
                        id SERIAL PRIMARY KEY,
                        decision_id VARCHAR(64) UNIQUE NOT NULL,
                        query_hash VARCHAR(64),
                        category VARCHAR(50) NOT NULL,
                        decision_point VARCHAR(200) NOT NULL,
                        options_considered JSONB DEFAULT '[]'::jsonb,
                        decision_made VARCHAR(200) NOT NULL,
                        reasoning TEXT,
                        confidence FLOAT DEFAULT 0.5,
                        context_snapshot JSONB,
                        outcome VARCHAR(50),
                        outcome_score FLOAT,
                        outcome_notes TEXT,
                        created_at TIMESTAMP DEFAULT NOW(),
                        resolved_at TIMESTAMP
                    );

                    CREATE INDEX IF NOT EXISTS idx_decision_log_category
                        ON decision_log(category);
                    CREATE INDEX IF NOT EXISTS idx_decision_log_created
                        ON decision_log(created_at DESC);
                    CREATE INDEX IF NOT EXISTS idx_decision_log_outcome
                        ON decision_log(outcome);

                    CREATE TABLE IF NOT EXISTS decision_patterns (
                        id SERIAL PRIMARY KEY,
                        pattern_key VARCHAR(200) UNIQUE NOT NULL,
                        category VARCHAR(50) NOT NULL,
                        condition_signature JSONB NOT NULL,
                        preferred_decision VARCHAR(200),
                        success_count INTEGER DEFAULT 0,
                        total_count INTEGER DEFAULT 0,
                        avg_outcome_score FLOAT DEFAULT 0.5,
                        last_seen_at TIMESTAMP DEFAULT NOW(),
                        created_at TIMESTAMP DEFAULT NOW()
                    );

                    CREATE INDEX IF NOT EXISTS idx_decision_patterns_category
                        ON decision_patterns(category);
                    CREATE INDEX IF NOT EXISTS idx_decision_patterns_score
                        ON decision_patterns(avg_outcome_score DESC);

                    CREATE TABLE IF NOT EXISTS decision_feedback (
                        id SERIAL PRIMARY KEY,
                        decision_id VARCHAR(64) NOT NULL,
                        feedback_type VARCHAR(50) NOT NULL,
                        feedback_value FLOAT,
                        feedback_text TEXT,
                        source VARCHAR(50) DEFAULT 'system',
                        created_at TIMESTAMP DEFAULT NOW()
                    );

                    CREATE INDEX IF NOT EXISTS idx_decision_feedback_id
                        ON decision_feedback(decision_id);
                """)
        except Exception as e:
            logger.debug(f"Tables may already exist: {e}")

    def record_decision(
        self,
        category: str,
        decision_point: str,
        decision_made: str,
        options_considered: List[str] = None,
        reasoning: str = None,
        confidence: float = 0.5,
        context: Dict[str, Any] = None,
        query: str = None
    ) -> Dict[str, Any]:
        """
        Record a decision made during processing.

        Args:
            category: Decision category (tool_selection, response_style, etc.)
            decision_point: What decision was being made
            decision_made: The actual decision
            options_considered: Other options that were considered
            reasoning: Why this decision was made
            confidence: Confidence level (0-1)
            context: Context at time of decision
            query: Original query if applicable

        Returns:
            Dict with decision_id for later outcome tracking
        """
        try:
            decision_id = hashlib.md5(
                f"{datetime.now().isoformat()}{decision_point}{decision_made}".encode()
            ).hexdigest()

            query_hash = hashlib.md5(query.encode()).hexdigest() if query else None

            with get_cursor() as cur:
                cur.execute("""
                    INSERT INTO decision_log
                    (decision_id, query_hash, category, decision_point, options_considered,
                     decision_made, reasoning, confidence, context_snapshot)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (
                    decision_id,
                    query_hash,
                    category,
                    decision_point,
                    json.dumps(options_considered or []),
                    decision_made,
                    reasoning,
                    confidence,
                    json.dumps(context or {})
                ))

                row = cur.fetchone()
                return {
                    "success": True,
                    "decision_id": decision_id,
                    "record_id": row['id'],
                    "category": category
                }

        except Exception as e:
            logger.error(f"Record decision failed: {e}")
            return {"success": False, "error": str(e)}

    def record_outcome(
        self,
        decision_id: str,
        outcome: str,
        outcome_score: float = None,
        notes: str = None
    ) -> Dict[str, Any]:
        """
        Record the outcome of a decision.

        Args:
            decision_id: ID from record_decision
            outcome: Outcome status (success, partial, failure, unknown)
            outcome_score: Numeric score (0-1)
            notes: Additional notes about outcome

        Returns:
            Dict with update confirmation
        """
        try:
            with get_cursor() as cur:
                # Update decision record
                cur.execute("""
                    UPDATE decision_log
                    SET outcome = %s,
                        outcome_score = %s,
                        outcome_notes = %s,
                        resolved_at = NOW()
                    WHERE decision_id = %s
                    RETURNING category, decision_point, decision_made, context_snapshot
                """, (outcome, outcome_score, notes, decision_id))

                row = cur.fetchone()
                if not row:
                    return {"success": False, "error": "Decision not found"}

                # Update decision patterns
                self._update_pattern(
                    cur,
                    row['category'],
                    row['context_snapshot'],
                    row['decision_made'],
                    outcome == 'success',
                    outcome_score
                )

                return {
                    "success": True,
                    "decision_id": decision_id,
                    "outcome": outcome,
                    "pattern_updated": True
                }

        except Exception as e:
            logger.error(f"Record outcome failed: {e}")
            return {"success": False, "error": str(e)}

    def _update_pattern(
        self,
        cur,
        category: str,
        context: Dict[str, Any],
        decision: str,
        was_successful: bool,
        score: float = None
    ):
        """Update decision pattern based on outcome."""
        try:
            # Create pattern key from context
            pattern_key = self._create_pattern_key(category, context)
            condition_sig = self._extract_condition_signature(context)

            score = score if score is not None else (1.0 if was_successful else 0.0)

            cur.execute("""
                INSERT INTO decision_patterns
                (pattern_key, category, condition_signature, preferred_decision,
                 success_count, total_count, avg_outcome_score)
                VALUES (%s, %s, %s, %s, %s, 1, %s)
                ON CONFLICT (pattern_key) DO UPDATE SET
                    success_count = decision_patterns.success_count + %s,
                    total_count = decision_patterns.total_count + 1,
                    avg_outcome_score = (
                        decision_patterns.avg_outcome_score * decision_patterns.total_count + %s
                    ) / (decision_patterns.total_count + 1),
                    preferred_decision = CASE
                        WHEN %s > decision_patterns.avg_outcome_score
                        THEN %s
                        ELSE decision_patterns.preferred_decision
                    END,
                    last_seen_at = NOW()
            """, (
                pattern_key,
                category,
                json.dumps(condition_sig),
                decision,
                1 if was_successful else 0,
                score,
                1 if was_successful else 0,
                score,
                score,
                decision
            ))
        except Exception as e:
            logger.debug(f"Pattern update failed: {e}")

    def _create_pattern_key(self, category: str, context: Dict[str, Any]) -> str:
        """Create a unique key for a decision pattern."""
        sig = self._extract_condition_signature(context)
        sig_str = json.dumps(sig, sort_keys=True)
        return f"{category}:{hashlib.md5(sig_str.encode()).hexdigest()[:16]}"

    def _extract_condition_signature(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Extract key conditions from context for pattern matching."""
        if not context:
            return {}

        return {
            "session_type": context.get("session_type"),
            "has_context": bool(context.get("loaded_context")),
            "time_of_day": self._get_time_bucket(),
            "query_type": context.get("query_type"),
        }

    def _get_time_bucket(self) -> str:
        """Get time-of-day bucket."""
        hour = datetime.now().hour
        if 6 <= hour < 12:
            return "morning"
        elif 12 <= hour < 18:
            return "afternoon"
        elif 18 <= hour < 22:
            return "evening"
        else:
            return "night"

    def get_decision_history(
        self,
        category: str = None,
        days: int = 7,
        limit: int = 50
    ) -> Dict[str, Any]:
        """Get recent decision history."""
        try:
            with get_cursor() as cur:
                if category:
                    cur.execute("""
                        SELECT decision_id, category, decision_point, decision_made,
                               confidence, outcome, outcome_score, created_at
                        FROM decision_log
                        WHERE category = %s
                        AND created_at > NOW() - make_interval(days => %s)
                        ORDER BY created_at DESC
                        LIMIT %s
                    """, (category, days, limit))
                else:
                    cur.execute("""
                        SELECT decision_id, category, decision_point, decision_made,
                               confidence, outcome, outcome_score, created_at
                        FROM decision_log
                        WHERE created_at > NOW() - make_interval(days => %s)
                        ORDER BY created_at DESC
                        LIMIT %s
                    """, (days, limit))

                decisions = []
                for row in cur.fetchall():
                    decisions.append({
                        "id": row['decision_id'][:8],
                        "category": row['category'],
                        "point": row['decision_point'][:50],
                        "decision": row['decision_made'],
                        "confidence": round(row['confidence'], 2),
                        "outcome": row['outcome'],
                        "score": round(row['outcome_score'], 2) if row['outcome_score'] else None,
                        "when": row['created_at'].isoformat()
                    })

                return {
                    "success": True,
                    "period_days": days,
                    "total": len(decisions),
                    "decisions": decisions
                }

        except Exception as e:
            logger.error(f"Get decision history failed: {e}")
            return {"success": False, "error": str(e)}

    def get_decision_stats(
        self,
        category: str = None,
        days: int = 30
    ) -> Dict[str, Any]:
        """Get decision statistics and patterns."""
        try:
            with get_cursor() as cur:
                # Overall stats
                if category:
                    cur.execute("""
                        SELECT
                            COUNT(*) as total,
                            COUNT(CASE WHEN outcome = 'success' THEN 1 END) as successes,
                            AVG(outcome_score) as avg_score,
                            AVG(confidence) as avg_confidence
                        FROM decision_log
                        WHERE category = %s
                        AND created_at > NOW() - make_interval(days => %s)
                    """, (category, days))
                else:
                    cur.execute("""
                        SELECT
                            COUNT(*) as total,
                            COUNT(CASE WHEN outcome = 'success' THEN 1 END) as successes,
                            AVG(outcome_score) as avg_score,
                            AVG(confidence) as avg_confidence
                        FROM decision_log
                        WHERE created_at > NOW() - make_interval(days => %s)
                    """, (days,))

                row = cur.fetchone()
                stats = {
                    "total_decisions": row['total'],
                    "successful": row['successes'] or 0,
                    "success_rate": round((row['successes'] or 0) / row['total'] * 100, 1) if row['total'] > 0 else 0,
                    "avg_outcome_score": round(row['avg_score'], 3) if row['avg_score'] else 0,
                    "avg_confidence": round(row['avg_confidence'], 3) if row['avg_confidence'] else 0
                }

                # By category
                cur.execute("""
                    SELECT category, COUNT(*) as count,
                           AVG(outcome_score) as avg_score
                    FROM decision_log
                    WHERE created_at > NOW() - make_interval(days => %s)
                    AND outcome IS NOT NULL
                    GROUP BY category
                    ORDER BY count DESC
                """, (days,))

                by_category = [{
                    "category": row['category'],
                    "count": row['count'],
                    "avg_score": round(row['avg_score'], 3) if row['avg_score'] else 0
                } for row in cur.fetchall()]

                # Top patterns
                cur.execute("""
                    SELECT category, preferred_decision, avg_outcome_score, total_count
                    FROM decision_patterns
                    WHERE total_count >= 3
                    ORDER BY avg_outcome_score DESC
                    LIMIT 10
                """)

                top_patterns = [{
                    "category": row['category'],
                    "decision": row['preferred_decision'],
                    "score": round(row['avg_outcome_score'], 3),
                    "uses": row['total_count']
                } for row in cur.fetchall()]

                return {
                    "success": True,
                    "period_days": days,
                    "stats": stats,
                    "by_category": by_category,
                    "top_patterns": top_patterns
                }

        except Exception as e:
            logger.error(f"Get decision stats failed: {e}")
            return {"success": False, "error": str(e)}

    def suggest_decision(
        self,
        category: str,
        context: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Suggest a decision based on learned patterns.

        Args:
            category: Decision category
            context: Current context

        Returns:
            Dict with suggested decision and confidence
        """
        try:
            pattern_key = self._create_pattern_key(category, context or {})

            with get_cursor() as cur:
                # Look for exact pattern match
                cur.execute("""
                    SELECT preferred_decision, avg_outcome_score, total_count
                    FROM decision_patterns
                    WHERE pattern_key = %s
                    AND total_count >= 2
                """, (pattern_key,))

                row = cur.fetchone()
                if row:
                    return {
                        "success": True,
                        "match_type": "exact",
                        "suggested_decision": row['preferred_decision'],
                        "confidence": row['avg_outcome_score'],
                        "based_on": row['total_count']
                    }

                # Fall back to category-level best decision
                cur.execute("""
                    SELECT preferred_decision, avg_outcome_score, total_count
                    FROM decision_patterns
                    WHERE category = %s
                    AND total_count >= 3
                    ORDER BY avg_outcome_score DESC
                    LIMIT 1
                """, (category,))

                row = cur.fetchone()
                if row:
                    return {
                        "success": True,
                        "match_type": "category",
                        "suggested_decision": row['preferred_decision'],
                        "confidence": row['avg_outcome_score'] * 0.7,  # Lower confidence for category match
                        "based_on": row['total_count']
                    }

                return {
                    "success": True,
                    "match_type": "none",
                    "suggested_decision": None,
                    "message": "No pattern found"
                }

        except Exception as e:
            logger.error(f"Suggest decision failed: {e}")
            return {"success": False, "error": str(e)}


# Singleton instance
_service: Optional[DecisionTracker] = None


def get_decision_tracker() -> DecisionTracker:
    """Get or create service instance."""
    global _service
    if _service is None:
        _service = DecisionTracker()
    return _service
