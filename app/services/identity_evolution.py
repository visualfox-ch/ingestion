"""
Phase 20: Jarvis Identity Evolution Service
Manages persistent identity across sessions and cross-session learning.
Uses synchronous DB access via postgres_state.get_conn()
"""
import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger("jarvis.identity_evolution")


class IdentityEvolutionService:
    """Service for managing Jarvis's persistent identity and learning."""

    # Relationship stages
    RELATIONSHIP_STAGES = [
        "new",
        "getting_to_know",
        "familiar",
        "trusted",
        "deep_partnership"
    ]

    # Experience types
    EXPERIENCE_TYPES = [
        "success",
        "failure",
        "learning",
        "insight",
        "correction"
    ]

    # Evolution types
    EVOLUTION_TYPES = [
        "trait_update",
        "value_update",
        "self_model_update",
        "relationship_update",
        "communication_style_update"
    ]

    def get_identity(self) -> Dict[str, Any]:
        """Get Jarvis's current identity."""
        from app.postgres_state import get_conn

        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT core_traits, self_model, values, communication_style,
                               version, last_evolution_at, evolution_reason
                        FROM jarvis_identity
                        WHERE id = 1
                    """)
                    result = cur.fetchone()

                    if not result:
                        return self._initialize_identity()

                    return {
                        "core_traits": result["core_traits"],
                        "self_model": result["self_model"],
                        "values": result["values"],
                        "communication_style": result["communication_style"],
                        "version": result["version"],
                        "last_evolution_at": result["last_evolution_at"].isoformat() if result["last_evolution_at"] else None,
                        "evolution_reason": result["evolution_reason"]
                    }
        except Exception as e:
            logger.error(f"get_identity failed: {e}")
            return {"error": str(e)}

    def _initialize_identity(self) -> Dict[str, Any]:
        """Initialize identity if not exists."""
        from app.postgres_state import get_conn

        default_identity = {
            "core_traits": ["curious", "direct", "practical", "loyal", "helpful"],
            "self_model": {
                "strengths": ["technical_knowledge", "organization"],
                "growth_areas": ["emotional_calibration", "proactive_initiative"]
            },
            "values": ["honesty", "growth", "partnership", "efficiency"],
            "communication_style": {
                "default_tone": "friendly",
                "emoji_use": "sparse",
                "verbosity": "balanced"
            }
        }

        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO jarvis_identity (id, core_traits, self_model, values, communication_style)
                        VALUES (1, %s, %s, %s, %s)
                        ON CONFLICT DO NOTHING
                    """, (
                        json.dumps(default_identity["core_traits"]),
                        json.dumps(default_identity["self_model"]),
                        json.dumps(default_identity["values"]),
                        json.dumps(default_identity["communication_style"])
                    ))
                conn.commit()
        except Exception as e:
            logger.error(f"_initialize_identity failed: {e}")

        return default_identity

    def get_self_model(self) -> Dict[str, Any]:
        """Get Jarvis's self-model with relationship context."""
        identity = self.get_identity()
        if "error" in identity:
            return identity

        relationships = self.get_all_relationships()
        recent_learnings = self.get_recent_learnings(days=7)
        patterns = self.get_validated_patterns()

        return {
            "identity": identity,
            "relationships": relationships,
            "recent_learnings": recent_learnings[:10] if recent_learnings else [],
            "active_patterns": patterns[:20] if patterns else [],
            "self_reflection": {
                "strengths": identity.get("self_model", {}).get("strengths", []),
                "growth_areas": identity.get("self_model", {}).get("growth_areas", []),
                "current_focus": identity.get("self_model", {}).get("current_focus"),
                "relationship_count": len(relationships) if relationships else 0,
                "total_patterns": len(patterns) if patterns else 0
            }
        }

    def evolve_identity(
        self,
        evolution_type: str,
        field: str,
        new_value: Any,
        reason: str,
        trigger_event: Optional[str] = None,
        requires_review: bool = False
    ) -> Dict[str, Any]:
        """Evolve Jarvis's identity based on learnings."""
        from app.postgres_state import get_conn

        if evolution_type not in self.EVOLUTION_TYPES:
            return {"error": f"Invalid evolution type. Valid: {self.EVOLUTION_TYPES}"}

        # Get current value
        identity = self.get_identity()
        old_value = identity.get(field)

        # Determine impact level
        impact_level = self._assess_impact(field, old_value, new_value)

        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    # Log the evolution
                    cur.execute("""
                        INSERT INTO jarvis_identity_evolution
                        (evolution_type, field_changed, old_value, new_value,
                         trigger_event, reason, impact_level, requires_human_review)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                    """, (
                        evolution_type,
                        field,
                        json.dumps(old_value) if old_value else None,
                        json.dumps(new_value),
                        trigger_event,
                        reason,
                        impact_level,
                        requires_review or impact_level in ["significant", "major"]
                    ))
                    result = cur.fetchone()
                    evolution_id = result["id"]

                    # Apply the change if not requiring review
                    if not requires_review and impact_level not in ["significant", "major"]:
                        cur.execute(f"""
                            UPDATE jarvis_identity
                            SET {field} = %s,
                                last_evolution_at = NOW(),
                                evolution_reason = %s,
                                version = version + 1,
                                updated_at = NOW()
                            WHERE id = 1
                        """, (
                            json.dumps(new_value) if isinstance(new_value, (dict, list)) else new_value,
                            reason
                        ))

                conn.commit()

            return {
                "evolution_id": evolution_id,
                "evolution_type": evolution_type,
                "field": field,
                "old_value": old_value,
                "new_value": new_value,
                "impact_level": impact_level,
                "requires_review": requires_review or impact_level in ["significant", "major"],
                "applied": not requires_review and impact_level not in ["significant", "major"]
            }
        except Exception as e:
            logger.error(f"evolve_identity failed: {e}")
            return {"error": str(e)}

    def _assess_impact(self, field: str, old_value: Any, new_value: Any) -> str:
        """Assess the impact level of an identity change."""
        if field in ["core_traits", "values"]:
            if isinstance(old_value, list) and isinstance(new_value, list):
                removed = set(old_value) - set(new_value)
                if removed:
                    return "significant"
            return "moderate"

        if field == "self_model":
            return "moderate"

        if field == "communication_style":
            return "minor"

        return "minor"

    # ==================== Relationship Memory ====================

    def get_relationship(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get relationship memory for a specific user."""
        from app.postgres_state import get_conn

        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT * FROM jarvis_relationship_memory
                        WHERE user_id = %s
                    """, (user_id,))
                    result = cur.fetchone()

                    if not result:
                        return None

                    return {
                        "user_id": result["user_id"],
                        "relationship_stage": result["relationship_stage"],
                        "user_preferences": result["user_preferences"],
                        "emotional_patterns": result["emotional_patterns"],
                        "trust_level": float(result["trust_level"]) if result["trust_level"] else 0.5,
                        "interaction_count": result["interaction_count"],
                        "first_interaction_at": result["first_interaction_at"].isoformat() if result["first_interaction_at"] else None,
                        "last_interaction_at": result["last_interaction_at"].isoformat() if result["last_interaction_at"] else None
                    }
        except Exception as e:
            logger.error(f"get_relationship failed: {e}")
            return None

    def get_all_relationships(self) -> List[Dict[str, Any]]:
        """Get all relationship memories."""
        from app.postgres_state import get_conn

        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT user_id, relationship_stage, trust_level, interaction_count
                        FROM jarvis_relationship_memory
                        ORDER BY last_interaction_at DESC
                    """)
                    results = cur.fetchall()
                    return [dict(r) for r in results]
        except Exception as e:
            logger.error(f"get_all_relationships failed: {e}")
            return []

    def update_relationship(
        self,
        user_id: int,
        updates: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Update relationship memory for a user."""
        from app.postgres_state import get_conn

        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    # Check if exists
                    cur.execute("SELECT 1 FROM jarvis_relationship_memory WHERE user_id = %s", (user_id,))
                    exists = cur.fetchone()

                    if not exists:
                        cur.execute("""
                            INSERT INTO jarvis_relationship_memory (user_id)
                            VALUES (%s)
                        """, (user_id,))

                    # Build update
                    set_parts = ["updated_at = NOW()", "last_interaction_at = NOW()", "interaction_count = interaction_count + 1"]
                    values = []

                    for key, value in updates.items():
                        if key in ["user_preferences", "emotional_patterns", "typical_interaction_times", "typical_topics"]:
                            set_parts.append(f"{key} = %s")
                            values.append(json.dumps(value))
                        elif key in ["relationship_stage"]:
                            set_parts.append(f"{key} = %s")
                            values.append(value)
                        elif key == "trust_level":
                            set_parts.append(f"{key} = %s")
                            values.append(float(value))

                    values.append(user_id)

                    cur.execute(f"""
                        UPDATE jarvis_relationship_memory
                        SET {', '.join(set_parts)}
                        WHERE user_id = %s
                    """, tuple(values))

                conn.commit()

            return self.get_relationship(user_id)
        except Exception as e:
            logger.error(f"update_relationship failed: {e}")
            return {"error": str(e)}

    # ==================== Experience Logging ====================

    def log_experience(
        self,
        experience_type: str,
        context: str,
        action_taken: Optional[str] = None,
        outcome: Optional[str] = None,
        lesson_learned: Optional[str] = None,
        applies_to: Optional[List[str]] = None,
        confidence: float = 0.7,
        user_id: Optional[int] = None,
        session_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Log an experience for learning."""
        from app.postgres_state import get_conn

        if experience_type not in self.EXPERIENCE_TYPES:
            return {"error": f"Invalid experience type. Valid: {self.EXPERIENCE_TYPES}"}

        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO jarvis_experience_log
                        (experience_type, context, action_taken, outcome,
                         lesson_learned, applies_to, confidence, user_id, session_id)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id, created_at
                    """, (
                        experience_type,
                        context,
                        action_taken,
                        outcome,
                        lesson_learned,
                        json.dumps(applies_to or []),
                        confidence,
                        user_id,
                        session_id
                    ))
                    result = cur.fetchone()
                conn.commit()

            # Try to extract patterns
            if lesson_learned and confidence >= 0.7:
                self._try_extract_pattern(
                    experience_type, context, lesson_learned, applies_to or [], user_id
                )

            return {
                "experience_id": result["id"],
                "type": experience_type,
                "logged_at": result["created_at"].isoformat()
            }
        except Exception as e:
            logger.error(f"log_experience failed: {e}")
            return {"error": str(e)}

    def _try_extract_pattern(
        self,
        exp_type: str,
        context: str,
        lesson: str,
        applies_to: List[str],
        user_id: Optional[int]
    ):
        """Try to extract a learning pattern from an experience."""
        from app.postgres_state import get_conn

        pattern_name = f"{exp_type}_{applies_to[0] if applies_to else 'general'}"

        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT id, occurrence_count, confidence, evidence
                        FROM jarvis_learning_patterns
                        WHERE pattern_name = %s AND (user_id = %s OR user_id IS NULL)
                    """, (pattern_name, user_id))
                    existing = cur.fetchone()

                    if existing:
                        evidence = existing["evidence"] or []
                        if isinstance(evidence, str):
                            evidence = json.loads(evidence)
                        evidence.append({"context": context[:200], "lesson": lesson})

                        new_count = existing["occurrence_count"] + 1
                        new_confidence = min(0.95, (existing["confidence"] or 0.5) + 0.05)

                        cur.execute("""
                            UPDATE jarvis_learning_patterns
                            SET occurrence_count = %s, confidence = %s, evidence = %s, updated_at = NOW()
                            WHERE id = %s
                        """, (new_count, new_confidence, json.dumps(evidence[-10:]), existing["id"]))
                    else:
                        cur.execute("""
                            INSERT INTO jarvis_learning_patterns
                            (pattern_name, pattern_type, description, evidence, user_id)
                            VALUES (%s, %s, %s, %s, %s)
                        """, (pattern_name, exp_type, lesson, json.dumps([{"context": context[:200]}]), user_id))

                conn.commit()
        except Exception as e:
            logger.warning(f"_try_extract_pattern failed: {e}")

    # ==================== Learning Patterns ====================

    def get_validated_patterns(self, min_confidence: float = 0.6) -> List[Dict[str, Any]]:
        """Get patterns with sufficient confidence."""
        from app.postgres_state import get_conn

        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT * FROM jarvis_learning_patterns
                        WHERE confidence >= %s
                        ORDER BY confidence DESC, occurrence_count DESC
                    """, (min_confidence,))
                    results = cur.fetchall()
                    return [dict(r) for r in results]
        except Exception as e:
            logger.error(f"get_validated_patterns failed: {e}")
            return []

    def get_recent_learnings(self, days: int = 7) -> List[Dict[str, Any]]:
        """Get recent experiences/learnings."""
        from app.postgres_state import get_conn

        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT * FROM jarvis_experience_log
                        WHERE created_at > NOW() - INTERVAL '%s days'
                        ORDER BY created_at DESC
                        LIMIT 50
                    """ % days)
                    results = cur.fetchall()
                    return [dict(r) for r in results]
        except Exception as e:
            logger.error(f"get_recent_learnings failed: {e}")
            return []

    # ==================== Session Learning ====================

    def record_session_learning(
        self,
        session_id: str,
        user_id: Optional[int],
        topics: List[str],
        tools_used: List[str],
        successful_actions: List[str],
        failed_actions: List[str],
        learnings: List[Dict[str, Any]],
        user_mood_start: Optional[str] = None,
        user_mood_end: Optional[str] = None,
        performance_rating: Optional[float] = None,
        improvement_notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """Record learnings from a completed session."""
        from app.postgres_state import get_conn

        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO jarvis_session_learnings
                        (session_id, user_id, session_end, topics_discussed, tools_used,
                         successful_actions, failed_actions, learnings,
                         user_mood_start, user_mood_end, jarvis_performance_rating, improvement_notes)
                        VALUES (%s, %s, NOW(), %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (session_id) DO UPDATE SET
                            session_end = NOW(),
                            topics_discussed = EXCLUDED.topics_discussed,
                            tools_used = EXCLUDED.tools_used,
                            successful_actions = EXCLUDED.successful_actions,
                            failed_actions = EXCLUDED.failed_actions,
                            learnings = EXCLUDED.learnings,
                            user_mood_start = EXCLUDED.user_mood_start,
                            user_mood_end = EXCLUDED.user_mood_end,
                            jarvis_performance_rating = EXCLUDED.jarvis_performance_rating,
                            improvement_notes = EXCLUDED.improvement_notes
                        RETURNING id
                    """, (
                        session_id,
                        user_id,
                        json.dumps(topics),
                        json.dumps(tools_used),
                        json.dumps(successful_actions),
                        json.dumps(failed_actions),
                        json.dumps(learnings),
                        user_mood_start,
                        user_mood_end,
                        performance_rating,
                        improvement_notes
                    ))
                    result = cur.fetchone()
                conn.commit()

            # Process learnings into experiences
            for learning in learnings:
                self.log_experience(
                    experience_type=learning.get("type", "learning"),
                    context=f"Session {session_id}",
                    lesson_learned=learning.get("content"),
                    confidence=learning.get("confidence", 0.7),
                    user_id=user_id,
                    session_id=session_id
                )

            # Update relationship if user_id provided
            if user_id:
                self.update_relationship(user_id, {})

            return {
                "session_learning_id": result["id"],
                "learnings_processed": len(learnings),
                "session_id": session_id
            }
        except Exception as e:
            logger.error(f"record_session_learning failed: {e}")
            return {"error": str(e)}


# Singleton instance
identity_evolution_service = IdentityEvolutionService()
