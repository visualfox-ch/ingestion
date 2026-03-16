"""
Importance Scoring Service - Phase B2 (AGI Evolution)

Based on Park et al. (2023) "Generative Agents: Interactive Simulacra"
Implements the retrieval formula:
    relevance = recency_weight * recency
              + importance_weight * importance
              + similarity_weight * semantic_similarity

Enables Jarvis to remember what matters most.
"""

import logging
import re
import math
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Singleton instance
_importance_service = None

# Default weights (Generative Agents paper)
DEFAULT_RECENCY_WEIGHT = 0.3
DEFAULT_IMPORTANCE_WEIGHT = 0.4
DEFAULT_SIMILARITY_WEIGHT = 0.3


def get_importance_service():
    """Get or create the importance scoring service singleton."""
    global _importance_service
    if _importance_service is None:
        _importance_service = ImportanceScoringService()
    return _importance_service


class ImportanceScoringService:
    """
    Service for scoring memory importance.

    Implements Generative Agents retrieval with:
    - Recency: Time-decay scoring
    - Importance: Content-based importance factors
    - Similarity: Semantic similarity (via embeddings)
    """

    def __init__(self):
        self.factors = {}
        self.decay_config = {}
        self._load_config()
        logger.info("ImportanceScoringService initialized")

    def _get_cursor(self):
        """Get database cursor."""
        from app.services.db_client import get_cursor
        return get_cursor()

    def _load_config(self):
        """Load importance factors and decay config from database."""
        try:
            with self._get_cursor() as cur:
                # Load factors
                cur.execute("""
                    SELECT factor_name, factor_type, detection_pattern, base_score, weight
                    FROM importance_factors WHERE is_active = TRUE
                """)
                for row in cur.fetchall():
                    self.factors[row[0]] = {
                        'type': row[1],
                        'pattern': row[2],
                        'base_score': row[3],
                        'weight': row[4]
                    }

                # Load decay config
                cur.execute("""
                    SELECT config_name, half_life_hours, min_score, boost_on_access
                    FROM recency_decay_config WHERE is_active = TRUE
                """)
                for row in cur.fetchall():
                    self.decay_config[row[0]] = {
                        'half_life': row[1],
                        'min_score': row[2],
                        'boost': row[3]
                    }

        except Exception as e:
            logger.warning(f"Could not load importance config: {e}")
            # Defaults
            self.factors = {
                'action_item': {'type': 'content', 'pattern': 'todo|task|aufgabe', 'base_score': 0.8, 'weight': 1.3},
                'urgency': {'type': 'emotional', 'pattern': 'urgent|dringend|wichtig', 'base_score': 0.9, 'weight': 1.4}
            }
            self.decay_config = {'default': {'half_life': 24, 'min_score': 0.01, 'boost': 1.0}}

    # =========================================================================
    # IMPORTANCE SCORING
    # =========================================================================

    def score_importance(
        self,
        content: str,
        context: Dict = None,
        entities: List[str] = None
    ) -> Dict[str, Any]:
        """
        Score the importance of content.

        Args:
            content: The text to score
            context: Optional context (source, session, etc.)
            entities: Entities mentioned

        Returns:
            Dict with importance scores and detected factors
        """
        try:
            detected_factors = []
            total_score = 0.5  # Base importance
            total_weight = 1.0

            # Check each factor
            for factor_name, factor_info in self.factors.items():
                pattern = factor_info.get('pattern')
                if pattern:
                    try:
                        if re.search(pattern, content, re.IGNORECASE):
                            contribution = factor_info['base_score'] * factor_info['weight']
                            detected_factors.append({
                                'factor': factor_name,
                                'type': factor_info['type'],
                                'contribution': contribution
                            })
                            total_score += contribution
                            total_weight += factor_info['weight']
                    except re.error:
                        pass

            # Check for entity mentions
            if entities:
                for entity in entities:
                    if entity.lower() in content.lower():
                        # Get entity importance
                        entity_importance = self._get_entity_importance(entity)
                        if entity_importance:
                            detected_factors.append({
                                'factor': f'entity:{entity}',
                                'type': 'entity',
                                'contribution': entity_importance * 0.3
                            })
                            total_score += entity_importance * 0.3
                            total_weight += 0.3

            # Normalize
            raw_importance = total_score / total_weight
            normalized = min(1.0, max(0.0, raw_importance))

            # Detect emotional valence
            emotional_valence = self._detect_emotional_valence(content)

            return {
                "success": True,
                "raw_importance": raw_importance,
                "normalized_importance": normalized,
                "factors_detected": detected_factors,
                "factor_count": len(detected_factors),
                "emotional_valence": emotional_valence
            }

        except Exception as e:
            logger.error(f"Score importance failed: {e}")
            return {"success": False, "error": str(e), "normalized_importance": 0.5}

    def _detect_emotional_valence(self, content: str) -> float:
        """Detect emotional valence (-1 to 1)."""
        positive_patterns = ['gut', 'great', 'super', 'toll', 'happy', 'freude', 'excited', 'love']
        negative_patterns = ['schlecht', 'bad', 'problem', 'fehler', 'error', 'frustrated', 'angry', 'sad']

        content_lower = content.lower()
        positive_count = sum(1 for p in positive_patterns if p in content_lower)
        negative_count = sum(1 for p in negative_patterns if p in content_lower)

        if positive_count + negative_count == 0:
            return 0.0

        return (positive_count - negative_count) / (positive_count + negative_count)

    def _get_entity_importance(self, entity: str) -> float:
        """Get importance score for an entity."""
        try:
            with self._get_cursor() as cur:
                cur.execute("""
                    SELECT base_importance, relationship_strength, manual_boost
                    FROM entity_importance
                    WHERE entity_name ILIKE %s
                    LIMIT 1
                """, (f"%{entity}%",))

                row = cur.fetchone()
                if row:
                    return (row[0] or 0.5) + (row[1] or 0) + (row[2] or 0)
                return 0.5
        except Exception:
            return 0.5

    # =========================================================================
    # RECENCY SCORING
    # =========================================================================

    def calculate_recency(
        self,
        created_at: datetime,
        last_accessed: datetime = None,
        config_name: str = "default"
    ) -> float:
        """
        Calculate recency score with exponential decay.

        Args:
            created_at: When the memory was created
            last_accessed: Last access time (uses this if newer)
            config_name: Decay configuration to use

        Returns:
            Recency score 0-1
        """
        try:
            config = self.decay_config.get(config_name, self.decay_config.get('default', {}))
            half_life_hours = config.get('half_life', 24)
            min_score = config.get('min_score', 0.01)

            # Use most recent timestamp
            reference_time = last_accessed if last_accessed and last_accessed > created_at else created_at
            if isinstance(reference_time, str):
                reference_time = datetime.fromisoformat(reference_time.replace('Z', '+00:00'))

            # Calculate hours since reference
            now = datetime.now(reference_time.tzinfo) if reference_time.tzinfo else datetime.now()
            hours_elapsed = (now - reference_time).total_seconds() / 3600

            # Exponential decay
            decay_factor = 0.5 ** (hours_elapsed / half_life_hours)
            recency_score = max(min_score, decay_factor)

            return recency_score

        except Exception as e:
            logger.error(f"Calculate recency failed: {e}")
            return 0.5

    def decay_all_recency(self, decay_factor: float = None) -> Dict[str, Any]:
        """
        Apply recency decay to all memories.

        Args:
            decay_factor: Custom decay factor (default: based on config)

        Returns:
            Dict with update count
        """
        try:
            if decay_factor is None:
                config = self.decay_config.get('default', {})
                half_life = config.get('half_life', 24)
                # Decay for 1 hour
                decay_factor = 0.5 ** (1.0 / half_life)

            with self._get_cursor() as cur:
                cur.execute("""
                    UPDATE memory_items
                    SET recency_score = GREATEST(recency_score * %s, 0.01)
                    WHERE recency_score > 0.01
                """, (decay_factor,))

                return {
                    "success": True,
                    "updated_count": cur.rowcount,
                    "decay_factor": decay_factor
                }

        except Exception as e:
            logger.error(f"Decay all recency failed: {e}")
            return {"success": False, "error": str(e)}

    # =========================================================================
    # COMPOSITE RETRIEVAL
    # =========================================================================

    def retrieve_relevant(
        self,
        query: str,
        limit: int = 10,
        recency_weight: float = DEFAULT_RECENCY_WEIGHT,
        importance_weight: float = DEFAULT_IMPORTANCE_WEIGHT,
        similarity_weight: float = DEFAULT_SIMILARITY_WEIGHT,
        min_score: float = 0.1,
        domain: str = None,
        session_id: str = None
    ) -> Dict[str, Any]:
        """
        Retrieve most relevant memories using composite scoring.

        Args:
            query: Search query
            limit: Max results
            recency_weight: Weight for recency (default: 0.3)
            importance_weight: Weight for importance (default: 0.4)
            similarity_weight: Weight for similarity (default: 0.3)
            min_score: Minimum composite score
            domain: Filter by domain
            session_id: Session for logging

        Returns:
            Dict with ranked memories
        """
        try:
            import time
            import json
            start_time = time.time()

            # Normalize weights
            total_weight = recency_weight + importance_weight + similarity_weight
            recency_w = recency_weight / total_weight
            importance_w = importance_weight / total_weight
            similarity_w = similarity_weight / total_weight

            with self._get_cursor() as cur:
                # Build query
                conditions = ["1=1"]
                params = []

                if domain:
                    conditions.append("m.domain = %s")
                    params.append(domain)

                # Text search for similarity (simplified - could use Qdrant)
                if query:
                    conditions.append("(m.content ILIKE %s OR m.summary ILIKE %s)")
                    params.extend([f"%{query}%", f"%{query}%"])

                where_clause = " AND ".join(conditions)

                # Retrieve with composite scoring
                cur.execute(f"""
                    SELECT
                        m.id,
                        m.memory_key,
                        m.content,
                        m.summary,
                        m.domain,
                        m.importance,
                        m.recency_score,
                        m.access_count,
                        m.created_at,
                        m.last_accessed,
                        t.tier_name,
                        -- Text similarity (simple for now)
                        CASE WHEN m.content ILIKE %s THEN 0.8
                             WHEN m.summary ILIKE %s THEN 0.6
                             ELSE 0.3 END as text_similarity,
                        -- Composite score
                        (m.recency_score * %s +
                         m.importance * %s +
                         CASE WHEN m.content ILIKE %s THEN 0.8
                              WHEN m.summary ILIKE %s THEN 0.6
                              ELSE 0.3 END * %s) as composite_score
                    FROM memory_items m
                    JOIN memory_tiers t ON m.tier_id = t.id
                    WHERE {where_clause}
                      AND t.tier_name != 'archive'
                    ORDER BY composite_score DESC
                    LIMIT %s
                """, [f"%{query}%", f"%{query}%",
                      recency_w, importance_w,
                      f"%{query}%", f"%{query}%", similarity_w,
                      *params, limit])

                columns = [desc[0] for desc in cur.description]
                results = []

                for i, row in enumerate(cur.fetchall()):
                    memory = dict(zip(columns, row))
                    if memory['composite_score'] >= min_score:
                        # Convert datetimes
                        for key in ['created_at', 'last_accessed']:
                            if memory.get(key):
                                memory[key] = memory[key].isoformat()

                        memory['rank'] = i + 1
                        results.append(memory)

                        # Update access count
                        cur.execute("""
                            UPDATE memory_items
                            SET access_count = access_count + 1,
                                last_accessed = NOW()
                            WHERE id = %s
                        """, (memory['id'],))

                retrieval_time = int((time.time() - start_time) * 1000)

                # Log retrieval
                if session_id:
                    cur.execute("""
                        INSERT INTO retrieval_requests
                        (query_text, recency_weight, importance_weight, similarity_weight,
                         results_count, top_results, retrieval_time_ms, session_id)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        query, recency_weight, importance_weight, similarity_weight,
                        len(results),
                        json.dumps([{'memory_id': r['id'], 'score': r['composite_score'], 'rank': r['rank']}
                                   for r in results[:5]]),
                        retrieval_time, session_id
                    ))

                return {
                    "success": True,
                    "results": results,
                    "count": len(results),
                    "weights": {
                        "recency": recency_w,
                        "importance": importance_w,
                        "similarity": similarity_w
                    },
                    "retrieval_time_ms": retrieval_time
                }

        except Exception as e:
            logger.error(f"Retrieve relevant failed: {e}")
            return {"success": False, "error": str(e)}

    # =========================================================================
    # ENTITY IMPORTANCE
    # =========================================================================

    def update_entity_importance(
        self,
        entity_name: str,
        entity_type: str = "concept",
        interaction: bool = False,
        manual_boost: float = None
    ) -> Dict[str, Any]:
        """
        Update importance tracking for an entity.

        Args:
            entity_name: The entity name
            entity_type: Type (person, project, concept, location)
            interaction: Whether this is an interaction
            manual_boost: Manual importance adjustment

        Returns:
            Dict with updated importance
        """
        try:
            with self._get_cursor() as cur:
                # Upsert entity
                cur.execute("""
                    INSERT INTO entity_importance
                    (entity_name, entity_type, mention_count, interaction_count, last_interaction, manual_boost)
                    VALUES (%s, %s, 1, %s, %s, %s)
                    ON CONFLICT (entity_name, entity_type)
                    DO UPDATE SET
                        mention_count = entity_importance.mention_count + 1,
                        interaction_count = entity_importance.interaction_count + (CASE WHEN %s THEN 1 ELSE 0 END),
                        last_interaction = CASE WHEN %s THEN NOW() ELSE entity_importance.last_interaction END,
                        manual_boost = COALESCE(%s, entity_importance.manual_boost),
                        updated_at = NOW()
                    RETURNING id, base_importance, mention_count, interaction_count
                """, (
                    entity_name, entity_type,
                    1 if interaction else 0,
                    datetime.now() if interaction else None,
                    manual_boost or 0,
                    interaction, interaction, manual_boost
                ))

                row = cur.fetchone()

                # Calculate current relevance based on interactions
                if row:
                    mentions = row[2]
                    interactions = row[3]
                    base = row[1] or 0.5

                    # More interactions = higher relevance
                    relevance = base + (interactions * 0.05) + (mentions * 0.01)
                    relevance = min(1.0, relevance)

                    cur.execute("""
                        UPDATE entity_importance
                        SET current_relevance = %s, base_importance = %s
                        WHERE id = %s
                    """, (relevance, min(0.9, base + 0.02), row[0]))

                    return {
                        "success": True,
                        "entity": entity_name,
                        "type": entity_type,
                        "current_relevance": relevance,
                        "mention_count": mentions,
                        "interaction_count": interactions
                    }

                return {"success": False, "error": "Failed to upsert entity"}

        except Exception as e:
            logger.error(f"Update entity importance failed: {e}")
            return {"success": False, "error": str(e)}

    def get_important_entities(
        self,
        entity_type: str = None,
        limit: int = 20
    ) -> Dict[str, Any]:
        """Get most important entities."""
        try:
            with self._get_cursor() as cur:
                if entity_type:
                    cur.execute("""
                        SELECT entity_name, entity_type, base_importance,
                               current_relevance, mention_count, interaction_count, last_interaction
                        FROM entity_importance
                        WHERE entity_type = %s
                        ORDER BY current_relevance DESC, interaction_count DESC
                        LIMIT %s
                    """, (entity_type, limit))
                else:
                    cur.execute("""
                        SELECT entity_name, entity_type, base_importance,
                               current_relevance, mention_count, interaction_count, last_interaction
                        FROM entity_importance
                        ORDER BY current_relevance DESC, interaction_count DESC
                        LIMIT %s
                    """, (limit,))

                columns = [desc[0] for desc in cur.description]
                entities = []
                for row in cur.fetchall():
                    entity = dict(zip(columns, row))
                    if entity.get('last_interaction'):
                        entity['last_interaction'] = entity['last_interaction'].isoformat()
                    entities.append(entity)

                return {
                    "success": True,
                    "entities": entities,
                    "count": len(entities)
                }

        except Exception as e:
            logger.error(f"Get important entities failed: {e}")
            return {"success": False, "error": str(e)}

    # =========================================================================
    # FACTOR MANAGEMENT
    # =========================================================================

    def add_importance_factor(
        self,
        factor_name: str,
        factor_type: str,
        detection_pattern: str,
        base_score: float = 0.5,
        weight: float = 1.0,
        description: str = None
    ) -> Dict[str, Any]:
        """Add a new importance factor."""
        try:
            with self._get_cursor() as cur:
                cur.execute("""
                    INSERT INTO importance_factors
                    (factor_name, factor_type, detection_pattern, base_score, weight, description)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (factor_name) DO UPDATE SET
                        detection_pattern = EXCLUDED.detection_pattern,
                        base_score = EXCLUDED.base_score,
                        weight = EXCLUDED.weight
                    RETURNING id
                """, (factor_name, factor_type, detection_pattern, base_score, weight, description))

                row = cur.fetchone()

                # Reload factors
                self._load_config()

                return {
                    "success": True,
                    "factor_id": row[0],
                    "factor_name": factor_name
                }

        except Exception as e:
            logger.error(f"Add importance factor failed: {e}")
            return {"success": False, "error": str(e)}

    def get_importance_factors(self) -> Dict[str, Any]:
        """Get all active importance factors."""
        try:
            with self._get_cursor() as cur:
                cur.execute("""
                    SELECT factor_name, factor_type, detection_pattern,
                           base_score, weight, description
                    FROM importance_factors
                    WHERE is_active = TRUE
                    ORDER BY factor_type, weight DESC
                """)

                columns = [desc[0] for desc in cur.description]
                factors = [dict(zip(columns, row)) for row in cur.fetchall()]

                return {
                    "success": True,
                    "factors": factors,
                    "count": len(factors)
                }

        except Exception as e:
            logger.error(f"Get importance factors failed: {e}")
            return {"success": False, "error": str(e)}

    # =========================================================================
    # STATISTICS
    # =========================================================================

    def get_scoring_stats(self, days: int = 7) -> Dict[str, Any]:
        """Get statistics about importance scoring and retrieval."""
        try:
            with self._get_cursor() as cur:
                # Retrieval stats
                cur.execute("""
                    SELECT
                        COUNT(*) as total_retrievals,
                        AVG(results_count) as avg_results,
                        AVG(retrieval_time_ms) as avg_time_ms
                    FROM retrieval_requests
                    WHERE created_at > NOW() - INTERVAL '%s days'
                """, (days,))
                retrieval_stats = cur.fetchone()

                # Weight distribution
                cur.execute("""
                    SELECT
                        AVG(recency_weight) as avg_recency_w,
                        AVG(importance_weight) as avg_importance_w,
                        AVG(similarity_weight) as avg_similarity_w
                    FROM retrieval_requests
                    WHERE created_at > NOW() - INTERVAL '%s days'
                """, (days,))
                weight_stats = cur.fetchone()

                # Memory importance distribution
                cur.execute("""
                    SELECT
                        CASE
                            WHEN importance < 0.3 THEN 'low'
                            WHEN importance < 0.6 THEN 'medium'
                            WHEN importance < 0.8 THEN 'high'
                            ELSE 'critical'
                        END as importance_level,
                        COUNT(*) as count
                    FROM memory_items
                    GROUP BY importance_level
                """)
                importance_dist = {row[0]: row[1] for row in cur.fetchall()}

                # Entity stats
                cur.execute("SELECT COUNT(*) FROM entity_importance")
                entity_count = cur.fetchone()[0]

                return {
                    "success": True,
                    "retrieval": {
                        "total": retrieval_stats[0] if retrieval_stats else 0,
                        "avg_results": round(retrieval_stats[1], 1) if retrieval_stats and retrieval_stats[1] else 0,
                        "avg_time_ms": round(retrieval_stats[2], 1) if retrieval_stats and retrieval_stats[2] else 0
                    },
                    "weights_used": {
                        "avg_recency": round(weight_stats[0], 2) if weight_stats and weight_stats[0] else DEFAULT_RECENCY_WEIGHT,
                        "avg_importance": round(weight_stats[1], 2) if weight_stats and weight_stats[1] else DEFAULT_IMPORTANCE_WEIGHT,
                        "avg_similarity": round(weight_stats[2], 2) if weight_stats and weight_stats[2] else DEFAULT_SIMILARITY_WEIGHT
                    },
                    "importance_distribution": importance_dist,
                    "tracked_entities": entity_count,
                    "days_analyzed": days
                }

        except Exception as e:
            logger.error(f"Get scoring stats failed: {e}")
            return {"success": False, "error": str(e)}
