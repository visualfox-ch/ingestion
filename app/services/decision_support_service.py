"""
Decision Support Service - Tier 1 Quick Win

Provides decision support based on historical causal patterns and observations.
Answers questions like "Soll ich heute Abend Sport machen oder morgen früh?"
with data from similar past situations.

Uses:
- jarvis_causal_patterns: Learned cause-effect relationships
- jarvis_causal_observations: Evidence supporting patterns
- causal_knowledge_service: For why/what-if reasoning
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass

from app.postgres_state import get_conn
from app.observability import get_logger

logger = get_logger("jarvis.decision_support")


@dataclass
class DecisionOption:
    """A decision option with historical data."""
    name: str
    success_rate: float
    total_observations: int
    avg_outcome_score: float
    confidence: float
    supporting_patterns: List[Dict[str, Any]]
    recent_observations: List[Dict[str, Any]]
    recommendation_strength: str  # "strong", "moderate", "weak", "insufficient_data"


@dataclass
class SimilarSituation:
    """A similar past situation."""
    pattern_id: int
    cause: str
    effect: str
    confidence: float
    evidence_count: int
    context: Optional[Dict[str, Any]]
    last_observed: Optional[datetime]
    outcome_type: str  # "positive", "negative", "neutral"


class DecisionSupportService:
    """
    Provides data-driven decision support.

    Example usage:
        service = get_decision_support()
        result = service.analyze_decision(
            user_id="micha",
            decision_query="Soll ich heute Abend Sport machen oder morgen früh?",
            options=["heute abend sport", "morgen früh sport"],
            context={"current_energy": "medium", "schedule": "evening free"}
        )
        # Returns: recommendation with historical success rates
    """

    def __init__(self):
        self.min_observations_for_recommendation = 3
        self.strong_confidence_threshold = 0.75
        self.moderate_confidence_threshold = 0.6

    def find_similar_situations(
        self,
        user_id: str,
        query_keywords: List[str],
        context: Dict[str, Any] = None,
        limit: int = 20
    ) -> List[SimilarSituation]:
        """
        Find similar past situations based on keywords and context.

        Args:
            user_id: User identifier
            query_keywords: Keywords to match against causes/effects
            context: Optional context for filtering
            limit: Maximum results

        Returns:
            List of similar situations with outcomes
        """
        situations = []

        with get_conn() as conn:
            with conn.cursor() as cur:
                # Build keyword search conditions
                keyword_conditions = []
                params = [user_id]

                for keyword in query_keywords:
                    keyword_lower = keyword.lower().strip()
                    if len(keyword_lower) > 2:  # Skip very short words
                        keyword_conditions.append(
                            "(LOWER(cause) LIKE %s OR LOWER(effect) LIKE %s)"
                        )
                        params.extend([f"%{keyword_lower}%", f"%{keyword_lower}%"])

                if not keyword_conditions:
                    return []

                where_clause = " OR ".join(keyword_conditions)

                cur.execute(f"""
                    SELECT id, cause, effect, cause_type, effect_type,
                           confidence, evidence_count, metadata, last_observed_at
                    FROM jarvis_causal_patterns
                    WHERE user_id = %s AND active = TRUE AND ({where_clause})
                    ORDER BY confidence DESC, evidence_count DESC
                    LIMIT %s
                """, params + [limit])

                rows = cur.fetchall()

                for row in rows:
                    # Determine outcome type based on effect_type
                    effect_type = row['effect_type']
                    if effect_type in ('need', 'warning'):
                        outcome_type = 'negative'
                    elif effect_type in ('opportunity', 'recommendation'):
                        outcome_type = 'positive'
                    else:
                        outcome_type = 'neutral'

                    situations.append(SimilarSituation(
                        pattern_id=row['id'],
                        cause=row['cause'],
                        effect=row['effect'],
                        confidence=row['confidence'],
                        evidence_count=row['evidence_count'],
                        context=row['metadata'] if row['metadata'] else None,
                        last_observed=row['last_observed_at'],
                        outcome_type=outcome_type
                    ))

        return situations

    def analyze_option(
        self,
        user_id: str,
        option_text: str,
        context: Dict[str, Any] = None
    ) -> DecisionOption:
        """
        Analyze a single decision option.

        Args:
            user_id: User identifier
            option_text: The option to analyze
            context: Optional context

        Returns:
            DecisionOption with historical data
        """
        option_lower = option_text.lower().strip()
        keywords = [w for w in option_lower.split() if len(w) > 2]

        # Find patterns where this option is the cause
        with get_conn() as conn:
            with conn.cursor() as cur:
                # Get patterns where option appears in cause
                cur.execute("""
                    SELECT id, cause, effect, effect_type, confidence, evidence_count,
                           metadata, last_observed_at
                    FROM jarvis_causal_patterns
                    WHERE user_id = %s AND active = TRUE
                      AND LOWER(cause) LIKE %s
                    ORDER BY evidence_count DESC
                    LIMIT 20
                """, (user_id, f"%{option_lower}%"))

                patterns = cur.fetchall()

                # Calculate success metrics
                total_observations = sum(p['evidence_count'] for p in patterns)
                positive_outcomes = 0
                negative_outcomes = 0
                neutral_outcomes = 0

                supporting_patterns = []
                for p in patterns:
                    effect_type = p['effect_type']
                    count = p['evidence_count']

                    if effect_type in ('opportunity', 'recommendation', 'outcome'):
                        positive_outcomes += count
                    elif effect_type in ('need', 'warning'):
                        negative_outcomes += count
                    else:
                        neutral_outcomes += count

                    supporting_patterns.append({
                        "cause": p['cause'],
                        "effect": p['effect'],
                        "confidence": float(p['confidence']),
                        "observations": p['evidence_count']
                    })

                # Calculate success rate
                if total_observations > 0:
                    success_rate = positive_outcomes / total_observations
                    avg_confidence = sum(p['confidence'] for p in patterns) / len(patterns) if patterns else 0.5
                else:
                    success_rate = 0.5  # Neutral if no data
                    avg_confidence = 0.0

                # Get recent observations
                recent = []
                if patterns:
                    pattern_ids = [p['id'] for p in patterns[:5]]
                    cur.execute("""
                        SELECT cause_event, effect_event, time_delta_minutes, context, created_at
                        FROM jarvis_causal_observations
                        WHERE pattern_id = ANY(%s)
                        ORDER BY created_at DESC
                        LIMIT 5
                    """, (pattern_ids,))

                    for obs in cur.fetchall():
                        recent.append({
                            "cause": obs['cause_event'],
                            "effect": obs['effect_event'],
                            "time_delta": obs['time_delta_minutes'],
                            "date": obs['created_at'].isoformat() if obs['created_at'] else None
                        })

                # Determine recommendation strength
                if total_observations >= self.min_observations_for_recommendation:
                    if avg_confidence >= self.strong_confidence_threshold:
                        strength = "strong"
                    elif avg_confidence >= self.moderate_confidence_threshold:
                        strength = "moderate"
                    else:
                        strength = "weak"
                else:
                    strength = "insufficient_data"

                return DecisionOption(
                    name=option_text,
                    success_rate=round(success_rate, 2),
                    total_observations=total_observations,
                    avg_outcome_score=round(
                        (positive_outcomes - negative_outcomes) / max(1, total_observations), 2
                    ),
                    confidence=round(avg_confidence, 2),
                    supporting_patterns=supporting_patterns,
                    recent_observations=recent,
                    recommendation_strength=strength
                )

    def analyze_decision(
        self,
        user_id: str,
        decision_query: str,
        options: List[str] = None,
        context: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Analyze a decision with multiple options.

        Args:
            user_id: User identifier
            decision_query: The decision question
            options: List of options (auto-extracted if None)
            context: Optional context

        Returns:
            Analysis with recommendation
        """
        # Extract options from query if not provided
        if not options:
            options = self._extract_options_from_query(decision_query)

        if not options:
            # Fall back to general analysis
            keywords = [w for w in decision_query.lower().split() if len(w) > 2]
            similar = self.find_similar_situations(user_id, keywords, context)

            return {
                "query": decision_query,
                "options": [],
                "similar_situations_count": len(similar),
                "similar_situations": [
                    {
                        "pattern": f"{s.cause} → {s.effect}",
                        "confidence": s.confidence,
                        "observations": s.evidence_count,
                        "outcome": s.outcome_type
                    }
                    for s in similar[:10]
                ],
                "recommendation": None,
                "reasoning": "Konnte keine konkreten Optionen aus der Frage extrahieren. "
                            f"Gefunden: {len(similar)} ähnliche Situationen.",
                "confidence": 0.0,
                "data_quality": "insufficient"
            }

        # Analyze each option
        analyzed_options = []
        for option in options:
            analysis = self.analyze_option(user_id, option, context)
            analyzed_options.append({
                "option": analysis.name,
                "success_rate": analysis.success_rate,
                "observations": analysis.total_observations,
                "outcome_score": analysis.avg_outcome_score,
                "confidence": analysis.confidence,
                "strength": analysis.recommendation_strength,
                "patterns": analysis.supporting_patterns[:3],
                "recent": analysis.recent_observations[:2]
            })

        # Sort by success rate and confidence
        analyzed_options.sort(
            key=lambda x: (x["success_rate"], x["confidence"]),
            reverse=True
        )

        # Generate recommendation
        best_option = analyzed_options[0] if analyzed_options else None
        total_observations = sum(o["observations"] for o in analyzed_options)

        if best_option and best_option["observations"] >= self.min_observations_for_recommendation:
            if best_option["success_rate"] >= 0.7:
                reasoning = (
                    f"Basierend auf {total_observations} ähnlichen Situationen: "
                    f"'{best_option['option']}' hatte eine {best_option['success_rate']*100:.0f}% Erfolgsrate."
                )
                recommendation = best_option["option"]
                confidence = best_option["confidence"]
                data_quality = "good" if total_observations >= 10 else "moderate"
            else:
                # No clear winner
                reasoning = (
                    f"Basierend auf {total_observations} Beobachtungen: "
                    "Keine klare Empfehlung möglich. "
                    f"Beste Option '{best_option['option']}' hat nur {best_option['success_rate']*100:.0f}% Erfolgsrate."
                )
                recommendation = None
                confidence = best_option["confidence"]
                data_quality = "mixed"
        else:
            reasoning = (
                f"Nicht genug Daten ({total_observations} Beobachtungen). "
                "Empfehlung basiert auf allgemeinem Muster."
            )
            recommendation = best_option["option"] if best_option else None
            confidence = 0.3
            data_quality = "insufficient"

        return {
            "query": decision_query,
            "options": analyzed_options,
            "total_observations": total_observations,
            "recommendation": recommendation,
            "reasoning": reasoning,
            "confidence": confidence,
            "data_quality": data_quality,
            "timestamp": datetime.now().isoformat()
        }

    def get_decision_history(
        self,
        user_id: str,
        domain: str = None,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Get recent decisions and their outcomes."""
        with get_conn() as conn:
            with conn.cursor() as cur:
                # Get recent causal observations as decision history
                query = """
                    SELECT o.cause_event, o.effect_event, o.time_delta_minutes,
                           o.context, o.created_at, p.confidence, p.cause_type
                    FROM jarvis_causal_observations o
                    JOIN jarvis_causal_patterns p ON o.pattern_id = p.id
                    WHERE o.user_id = %s
                    ORDER BY o.created_at DESC
                    LIMIT %s
                """
                cur.execute(query, (user_id, limit))

                return [
                    {
                        "decision": row['cause_event'],
                        "outcome": row['effect_event'],
                        "time_to_effect_minutes": row['time_delta_minutes'],
                        "context": row['context'] if row['context'] else {},
                        "date": row['created_at'].isoformat() if row['created_at'] else None,
                        "pattern_confidence": float(row['confidence'])
                    }
                    for row in cur.fetchall()
                ]

    def _extract_options_from_query(self, query: str) -> List[str]:
        """Extract decision options from a query string."""
        query_lower = query.lower()

        # Common patterns
        patterns = [
            (" oder ", 2),   # "A oder B"
            (" vs ", 2),     # "A vs B"
            (" versus ", 2), # "A versus B"
        ]

        for pattern, expected_parts in patterns:
            if pattern in query_lower:
                parts = query.split(pattern if pattern == " oder " else pattern.upper())
                if len(parts) == expected_parts:
                    # Clean up the options
                    options = []
                    for part in parts:
                        # Remove question marks and common prefixes
                        clean = part.strip().rstrip("?").strip()
                        clean = clean.replace("soll ich ", "").replace("sollte ich ", "")
                        clean = clean.replace("lieber ", "").replace("besser ", "")
                        if clean:
                            options.append(clean)
                    return options

        return []

    def record_decision_outcome(
        self,
        user_id: str,
        decision: str,
        outcome: str,
        outcome_type: str = "outcome",  # outcome, warning, opportunity
        time_delta_minutes: int = None,
        context: Dict[str, Any] = None,
        session_id: str = None
    ) -> Dict[str, Any]:
        """
        Record a decision outcome for future learning.

        Args:
            user_id: User identifier
            decision: The decision made
            outcome: What happened as a result
            outcome_type: Type of outcome
            time_delta_minutes: Time between decision and outcome
            context: Contextual information
            session_id: Session identifier

        Returns:
            Recording status
        """
        from app.services.causal_knowledge_tracker import get_causal_knowledge_tracker

        tracker = get_causal_knowledge_tracker()
        result = tracker.record_observation(
            user_id=user_id,
            cause_event=decision,
            effect_event=outcome,
            cause_type="action",
            effect_type=outcome_type,
            time_delta_minutes=time_delta_minutes,
            session_id=session_id,
            context=context
        )

        return {
            "recorded": result.get("recorded", False),
            "pattern_id": result.get("pattern_id"),
            "is_new_pattern": result.get("is_new", False),
            "message": f"Entscheidung '{decision}' mit Ergebnis '{outcome}' aufgezeichnet."
        }

    def get_stats(self, user_id: str) -> Dict[str, Any]:
        """Get decision support statistics."""
        with get_conn() as conn:
            with conn.cursor() as cur:
                # Total patterns
                cur.execute("""
                    SELECT COUNT(*) as total FROM jarvis_causal_patterns
                    WHERE user_id = %s AND active = TRUE
                """, (user_id,))
                total_patterns = cur.fetchone()['total']

                # High confidence patterns
                cur.execute("""
                    SELECT COUNT(*) as count FROM jarvis_causal_patterns
                    WHERE user_id = %s AND active = TRUE AND confidence >= 0.7
                """, (user_id,))
                high_confidence = cur.fetchone()['count']

                # Total observations
                cur.execute("""
                    SELECT COUNT(*) as count FROM jarvis_causal_observations
                    WHERE user_id = %s
                """, (user_id,))
                total_observations = cur.fetchone()['count']

                # Recent decisions (last 7 days)
                cur.execute("""
                    SELECT COUNT(*) as count FROM jarvis_causal_observations
                    WHERE user_id = %s AND created_at > NOW() - INTERVAL '7 days'
                """, (user_id,))
                recent_decisions = cur.fetchone()['count']

                return {
                    "total_patterns": total_patterns,
                    "high_confidence_patterns": high_confidence,
                    "total_observations": total_observations,
                    "decisions_last_7_days": recent_decisions,
                    "recommendation_readiness": "good" if total_observations >= 50 else
                                                "moderate" if total_observations >= 20 else
                                                "building"
                }


# Singleton
_decision_support: Optional[DecisionSupportService] = None


def get_decision_support() -> DecisionSupportService:
    """Get the singleton decision support service."""
    global _decision_support
    if _decision_support is None:
        _decision_support = DecisionSupportService()
    return _decision_support
