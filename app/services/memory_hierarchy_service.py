"""
Memory Hierarchy Service - Phase B1 (AGI Evolution)

Based on MemGPT (Packer et al. 2023):
- Tiered memory: working → recall → longterm → archive
- Automatic promotion/demotion based on importance and recency
- Summary-based compression for recall buffer
- Importance scoring (Generative Agents style)

Enables Jarvis to manage memory like an operating system.
"""

import logging
import math
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Singleton instance
_memory_service = None

# Recency decay parameters
RECENCY_HALF_LIFE_HOURS = 24  # Score halves every 24 hours
IMPORTANCE_WEIGHT = 0.4
RECENCY_WEIGHT = 0.3
ACCESS_WEIGHT = 0.3


def get_memory_hierarchy_service():
    """Get or create the memory hierarchy service singleton."""
    global _memory_service
    if _memory_service is None:
        _memory_service = MemoryHierarchyService()
    return _memory_service


class MemoryHierarchyService:
    """
    Service for managing hierarchical memory.

    Implements MemGPT-style memory tiers:
    - Working: Active context (limited, high recency)
    - Recall: Summarized, quick access
    - Long-term: Full content, persistent
    - Archive: Compressed, permanent
    """

    def __init__(self):
        self.tiers = {}
        self._load_tiers()
        logger.info("MemoryHierarchyService initialized")

    def _get_cursor(self):
        """Get database cursor."""
        from app.services.db_client import get_cursor
        return get_cursor()

    def _load_tiers(self):
        """Load tier definitions from database."""
        try:
            with self._get_cursor() as cur:
                cur.execute("SELECT * FROM memory_tiers ORDER BY tier_level")
                for row in cur.fetchall():
                    columns = [desc[0] for desc in cur.description]
                    tier = dict(zip(columns, row))
                    self.tiers[tier['tier_name']] = tier
        except Exception as e:
            logger.warning(f"Could not load memory tiers: {e}")
            # Default tiers
            self.tiers = {
                'working': {'tier_level': 0, 'max_items': 20, 'max_age_hours': 2},
                'recall': {'tier_level': 1, 'max_items': 100, 'max_age_hours': 168},
                'longterm': {'tier_level': 2, 'max_items': None, 'max_age_hours': 2160},
                'archive': {'tier_level': 3, 'max_items': None, 'max_age_hours': None}
            }

    # =========================================================================
    # MEMORY STORAGE
    # =========================================================================

    def store_memory(
        self,
        content: str,
        memory_key: str = None,
        tier: str = "longterm",
        content_type: str = "text",
        source: str = None,
        domain: str = None,
        tags: List[str] = None,
        importance: float = 0.5,
        related_to: List[str] = None
    ) -> Dict[str, Any]:
        """
        Store a memory item.

        Args:
            content: The memory content
            memory_key: Unique identifier (auto-generated if not provided)
            tier: Target tier (working, recall, longterm, archive)
            content_type: Type of content (text, summary, fact, episode)
            source: Where this memory came from
            domain: Domain/category
            tags: Tags for organization
            importance: Importance score 0-1
            related_to: Related memory keys

        Returns:
            Dict with memory info
        """
        try:
            import json
            import hashlib

            # Generate key if not provided
            if not memory_key:
                memory_key = hashlib.sha256(
                    f"{content[:100]}:{datetime.now().isoformat()}".encode()
                ).hexdigest()[:16]

            # Get tier ID
            tier_info = self.tiers.get(tier, self.tiers.get('longterm'))
            tier_id = tier_info.get('id') if isinstance(tier_info, dict) and 'id' in tier_info else None

            if tier_id is None:
                with self._get_cursor() as cur:
                    cur.execute("SELECT id FROM memory_tiers WHERE tier_name = %s", (tier,))
                    row = cur.fetchone()
                    tier_id = row[0] if row else 2  # Default to longterm

            # Generate summary for recall buffer
            summary = None
            if tier in ['recall', 'working'] and len(content) > 500:
                summary = self._generate_summary(content)

            with self._get_cursor() as cur:
                cur.execute("""
                    INSERT INTO memory_items
                    (memory_key, tier_id, content, content_type, summary,
                     source, domain, tags, importance, related_memories)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (memory_key)
                    DO UPDATE SET
                        content = EXCLUDED.content,
                        tier_id = EXCLUDED.tier_id,
                        summary = COALESCE(EXCLUDED.summary, memory_items.summary),
                        importance = (memory_items.importance + EXCLUDED.importance) / 2,
                        access_count = memory_items.access_count + 1,
                        last_accessed = NOW()
                    RETURNING id, memory_key, tier_id
                """, (
                    memory_key, tier_id, content, content_type, summary,
                    source, domain, json.dumps(tags or []), importance,
                    json.dumps([{"memory_key": k} for k in (related_to or [])])
                ))

                row = cur.fetchone()

                return {
                    "success": True,
                    "memory_id": row[0],
                    "memory_key": row[1],
                    "tier": tier,
                    "has_summary": summary is not None
                }

        except Exception as e:
            logger.error(f"Store memory failed: {e}")
            return {"success": False, "error": str(e)}

    def recall_memory(
        self,
        memory_key: str = None,
        memory_id: int = None,
        include_full: bool = True
    ) -> Dict[str, Any]:
        """
        Recall a specific memory and update access stats.
        """
        try:
            with self._get_cursor() as cur:
                if memory_key:
                    cur.execute("""
                        SELECT m.*, t.tier_name
                        FROM memory_items m
                        JOIN memory_tiers t ON m.tier_id = t.id
                        WHERE m.memory_key = %s
                    """, (memory_key,))
                elif memory_id:
                    cur.execute("""
                        SELECT m.*, t.tier_name
                        FROM memory_items m
                        JOIN memory_tiers t ON m.tier_id = t.id
                        WHERE m.id = %s
                    """, (memory_id,))
                else:
                    return {"success": False, "error": "Must provide memory_key or memory_id"}

                row = cur.fetchone()
                if not row:
                    return {"success": False, "error": "Memory not found"}

                columns = [desc[0] for desc in cur.description]
                memory = dict(zip(columns, row))

                # Update access stats
                cur.execute("""
                    UPDATE memory_items
                    SET access_count = access_count + 1,
                        last_accessed = NOW(),
                        recency_score = 1.0
                    WHERE id = %s
                """, (memory['id'],))

                # Log access
                cur.execute("""
                    INSERT INTO memory_access_log (memory_id, access_type, context)
                    VALUES (%s, 'read', 'direct_recall')
                """, (memory['id'],))

                # Return summary or full content based on tier
                result = {
                    "success": True,
                    "memory_id": memory['id'],
                    "memory_key": memory['memory_key'],
                    "tier": memory['tier_name'],
                    "importance": memory['importance'],
                    "access_count": memory['access_count'] + 1,
                    "created_at": memory['created_at'].isoformat() if memory.get('created_at') else None
                }

                if include_full or memory['tier_name'] in ['working', 'longterm']:
                    result['content'] = memory['content']
                else:
                    result['content'] = memory.get('summary') or memory['content'][:500]

                return result

        except Exception as e:
            logger.error(f"Recall memory failed: {e}")
            return {"success": False, "error": str(e)}

    # =========================================================================
    # MEMORY SEARCH
    # =========================================================================

    def search_memories(
        self,
        query: str = None,
        domain: str = None,
        tier: str = None,
        tags: List[str] = None,
        min_importance: float = None,
        limit: int = 20,
        include_archived: bool = False
    ) -> Dict[str, Any]:
        """
        Search memories with importance-weighted ranking.
        """
        try:
            with self._get_cursor() as cur:
                conditions = []
                params = []

                if query:
                    conditions.append("(content ILIKE %s OR summary ILIKE %s)")
                    params.extend([f"%{query}%", f"%{query}%"])

                if domain:
                    conditions.append("domain = %s")
                    params.append(domain)

                if tier:
                    conditions.append("t.tier_name = %s")
                    params.append(tier)

                if min_importance is not None:
                    conditions.append("importance >= %s")
                    params.append(min_importance)

                if not include_archived:
                    conditions.append("t.tier_name != 'archive'")

                if tags:
                    conditions.append("tags ?| %s")
                    params.append(tags)

                where_clause = " AND ".join(conditions) if conditions else "1=1"
                params.append(limit)

                # Importance-weighted search with recency decay
                cur.execute(f"""
                    SELECT
                        m.id, m.memory_key, m.content, m.summary,
                        m.content_type, m.domain, m.tags,
                        m.importance, m.recency_score, m.access_count,
                        m.created_at, m.last_accessed,
                        t.tier_name,
                        -- Composite score (Generative Agents style)
                        (m.importance * {IMPORTANCE_WEIGHT} +
                         m.recency_score * {RECENCY_WEIGHT} +
                         LEAST(m.access_count / 10.0, 1.0) * {ACCESS_WEIGHT}) as relevance_score
                    FROM memory_items m
                    JOIN memory_tiers t ON m.tier_id = t.id
                    WHERE {where_clause}
                    ORDER BY relevance_score DESC, m.last_accessed DESC
                    LIMIT %s
                """, params)

                columns = [desc[0] for desc in cur.description]
                memories = [dict(zip(columns, row)) for row in cur.fetchall()]

                # Convert datetimes
                for mem in memories:
                    if mem.get('created_at'):
                        mem['created_at'] = mem['created_at'].isoformat()
                    if mem.get('last_accessed'):
                        mem['last_accessed'] = mem['last_accessed'].isoformat()

                return {
                    "success": True,
                    "memories": memories,
                    "count": len(memories)
                }

        except Exception as e:
            logger.error(f"Search memories failed: {e}")
            return {"success": False, "error": str(e)}

    # =========================================================================
    # TIER MANAGEMENT
    # =========================================================================

    def promote_memory(self, memory_key: str, target_tier: str) -> Dict[str, Any]:
        """
        Promote a memory to a higher tier (lower tier_level).
        """
        try:
            with self._get_cursor() as cur:
                # Get target tier ID
                cur.execute("SELECT id, tier_level FROM memory_tiers WHERE tier_name = %s", (target_tier,))
                target = cur.fetchone()
                if not target:
                    return {"success": False, "error": f"Unknown tier: {target_tier}"}

                # Update memory
                cur.execute("""
                    UPDATE memory_items
                    SET tier_id = %s,
                        promoted_at = NOW(),
                        recency_score = 1.0
                    WHERE memory_key = %s
                    RETURNING id
                """, (target[0], memory_key))

                row = cur.fetchone()
                if not row:
                    return {"success": False, "error": "Memory not found"}

                return {
                    "success": True,
                    "memory_key": memory_key,
                    "new_tier": target_tier,
                    "action": "promoted"
                }

        except Exception as e:
            logger.error(f"Promote memory failed: {e}")
            return {"success": False, "error": str(e)}

    def demote_memory(self, memory_key: str, target_tier: str = None) -> Dict[str, Any]:
        """
        Demote a memory to a lower tier (higher tier_level).
        If no target specified, demotes to next tier.
        """
        try:
            with self._get_cursor() as cur:
                # Get current tier
                cur.execute("""
                    SELECT m.id, t.tier_level, t.tier_name
                    FROM memory_items m
                    JOIN memory_tiers t ON m.tier_id = t.id
                    WHERE m.memory_key = %s
                """, (memory_key,))
                current = cur.fetchone()
                if not current:
                    return {"success": False, "error": "Memory not found"}

                current_level = current[1]

                # Determine target
                if target_tier:
                    cur.execute("SELECT id, tier_level FROM memory_tiers WHERE tier_name = %s", (target_tier,))
                    target = cur.fetchone()
                else:
                    # Next tier down
                    cur.execute("""
                        SELECT id, tier_name FROM memory_tiers
                        WHERE tier_level = %s + 1
                    """, (current_level,))
                    target = cur.fetchone()

                if not target:
                    return {"success": False, "error": "Cannot demote further"}

                # Generate summary if moving to recall
                summary = None
                if target[1] == 'recall' if len(target) > 1 else False:
                    cur.execute("SELECT content FROM memory_items WHERE memory_key = %s", (memory_key,))
                    content_row = cur.fetchone()
                    if content_row and len(content_row[0]) > 500:
                        summary = self._generate_summary(content_row[0])

                # Update memory
                update_sql = """
                    UPDATE memory_items
                    SET tier_id = %s,
                        demoted_at = NOW()
                """
                params = [target[0]]

                if summary:
                    update_sql += ", summary = %s"
                    params.append(summary)

                update_sql += " WHERE memory_key = %s RETURNING id"
                params.append(memory_key)

                cur.execute(update_sql, params)

                return {
                    "success": True,
                    "memory_key": memory_key,
                    "new_tier": target_tier or f"tier_{target[0]}",
                    "action": "demoted",
                    "summary_generated": summary is not None
                }

        except Exception as e:
            logger.error(f"Demote memory failed: {e}")
            return {"success": False, "error": str(e)}

    def run_memory_maintenance(self) -> Dict[str, Any]:
        """
        Run maintenance: decay recency scores, auto-demote old memories.
        Should be called periodically (e.g., every hour).
        """
        try:
            with self._get_cursor() as cur:
                # Decay recency scores
                decay_factor = 0.5 ** (1.0 / RECENCY_HALF_LIFE_HOURS)
                cur.execute("""
                    UPDATE memory_items
                    SET recency_score = recency_score * %s
                    WHERE recency_score > 0.01
                """, (decay_factor,))
                decayed_count = cur.rowcount

                # Auto-demote old memories from working to recall
                cur.execute("""
                    WITH to_demote AS (
                        SELECT m.id
                        FROM memory_items m
                        JOIN memory_tiers t ON m.tier_id = t.id
                        WHERE t.tier_name = 'working'
                          AND m.last_accessed < NOW() - INTERVAL '2 hours'
                    )
                    UPDATE memory_items m
                    SET tier_id = (SELECT id FROM memory_tiers WHERE tier_name = 'recall'),
                        demoted_at = NOW()
                    FROM to_demote
                    WHERE m.id = to_demote.id
                """)
                working_demoted = cur.rowcount

                # Auto-demote old recall items to longterm
                cur.execute("""
                    WITH to_demote AS (
                        SELECT m.id
                        FROM memory_items m
                        JOIN memory_tiers t ON m.tier_id = t.id
                        WHERE t.tier_name = 'recall'
                          AND m.last_accessed < NOW() - INTERVAL '1 week'
                    )
                    UPDATE memory_items m
                    SET tier_id = (SELECT id FROM memory_tiers WHERE tier_name = 'longterm'),
                        demoted_at = NOW()
                    FROM to_demote
                    WHERE m.id = to_demote.id
                """)
                recall_demoted = cur.rowcount

                # Auto-archive very old longterm items
                cur.execute("""
                    WITH to_archive AS (
                        SELECT m.id
                        FROM memory_items m
                        JOIN memory_tiers t ON m.tier_id = t.id
                        WHERE t.tier_name = 'longterm'
                          AND m.last_accessed < NOW() - INTERVAL '90 days'
                          AND m.importance < 0.7
                    )
                    UPDATE memory_items m
                    SET tier_id = (SELECT id FROM memory_tiers WHERE tier_name = 'archive'),
                        demoted_at = NOW(),
                        archived_at = NOW()
                    FROM to_archive
                    WHERE m.id = to_archive.id
                """)
                archived = cur.rowcount

                return {
                    "success": True,
                    "recency_decayed": decayed_count,
                    "working_to_recall": working_demoted,
                    "recall_to_longterm": recall_demoted,
                    "archived": archived
                }

        except Exception as e:
            logger.error(f"Memory maintenance failed: {e}")
            return {"success": False, "error": str(e)}

    # =========================================================================
    # WORKING CONTEXT MANAGEMENT
    # =========================================================================

    def get_working_context(self, session_id: str = None, max_items: int = 20) -> Dict[str, Any]:
        """
        Get current working context - most relevant active memories.
        """
        try:
            with self._get_cursor() as cur:
                cur.execute("""
                    SELECT
                        m.id, m.memory_key, m.content, m.summary,
                        m.importance, m.recency_score, m.access_count,
                        m.domain, m.tags,
                        (m.importance * %s + m.recency_score * %s +
                         LEAST(m.access_count / 10.0, 1.0) * %s) as score
                    FROM memory_items m
                    JOIN memory_tiers t ON m.tier_id = t.id
                    WHERE t.tier_name = 'working'
                    ORDER BY score DESC
                    LIMIT %s
                """, (IMPORTANCE_WEIGHT, RECENCY_WEIGHT, ACCESS_WEIGHT, max_items))

                columns = [desc[0] for desc in cur.description]
                memories = [dict(zip(columns, row)) for row in cur.fetchall()]

                # Estimate token count (rough)
                total_tokens = sum(len(m.get('content', '')) // 4 for m in memories)

                return {
                    "success": True,
                    "memories": memories,
                    "count": len(memories),
                    "estimated_tokens": total_tokens
                }

        except Exception as e:
            logger.error(f"Get working context failed: {e}")
            return {"success": False, "error": str(e)}

    def load_to_working(
        self,
        memory_keys: List[str] = None,
        query: str = None,
        domain: str = None,
        limit: int = 5
    ) -> Dict[str, Any]:
        """
        Load memories into working context for active use.
        """
        try:
            loaded = []

            if memory_keys:
                for key in memory_keys:
                    result = self.promote_memory(key, "working")
                    if result["success"]:
                        loaded.append(key)

            elif query or domain:
                # Search and promote top results
                search_result = self.search_memories(
                    query=query,
                    domain=domain,
                    limit=limit,
                    include_archived=False
                )

                if search_result["success"]:
                    for mem in search_result["memories"]:
                        result = self.promote_memory(mem["memory_key"], "working")
                        if result["success"]:
                            loaded.append(mem["memory_key"])

            return {
                "success": True,
                "loaded_count": len(loaded),
                "loaded_keys": loaded
            }

        except Exception as e:
            logger.error(f"Load to working failed: {e}")
            return {"success": False, "error": str(e)}

    def clear_working(self, demote_to: str = "recall") -> Dict[str, Any]:
        """
        Clear working context by demoting all items.
        """
        try:
            with self._get_cursor() as cur:
                cur.execute("""
                    SELECT memory_key FROM memory_items m
                    JOIN memory_tiers t ON m.tier_id = t.id
                    WHERE t.tier_name = 'working'
                """)

                keys = [row[0] for row in cur.fetchall()]
                demoted = 0

                for key in keys:
                    result = self.demote_memory(key, demote_to)
                    if result["success"]:
                        demoted += 1

                return {
                    "success": True,
                    "cleared_count": demoted
                }

        except Exception as e:
            logger.error(f"Clear working failed: {e}")
            return {"success": False, "error": str(e)}

    # =========================================================================
    # SUMMARY GENERATION
    # =========================================================================

    def _generate_summary(self, content: str, max_length: int = 200) -> str:
        """
        Generate a summary of content.
        For now, uses simple extraction. Can be enhanced with LLM.
        """
        # Simple extraction: first sentence + key phrases
        sentences = content.split('. ')
        if len(sentences) > 0:
            summary = sentences[0]
            if len(summary) > max_length:
                summary = summary[:max_length] + "..."
            return summary
        return content[:max_length]

    def create_session_summary(self, session_id: str) -> Dict[str, Any]:
        """
        Create a summary of a session's memories.
        """
        try:
            import json

            with self._get_cursor() as cur:
                # Get session memories
                cur.execute("""
                    SELECT content, importance, domain
                    FROM memory_items
                    WHERE source = %s OR memory_key LIKE %s
                    ORDER BY importance DESC
                    LIMIT 20
                """, (session_id, f"session_{session_id}%"))

                memories = cur.fetchall()
                if not memories:
                    return {"success": False, "error": "No memories found for session"}

                # Combine and summarize
                combined = "\n".join([m[0] for m in memories])
                summary = self._generate_summary(combined, max_length=500)

                # Extract key facts (simplified)
                key_facts = [m[0][:100] for m in memories[:5]]

                # Store summary
                cur.execute("""
                    INSERT INTO memory_summaries
                    (source_type, source_id, summary, key_facts, source_item_count)
                    VALUES ('session', %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    RETURNING id
                """, (session_id, summary, json.dumps(key_facts), len(memories)))

                row = cur.fetchone()

                return {
                    "success": True,
                    "summary_id": row[0] if row else None,
                    "summary": summary,
                    "key_facts": key_facts,
                    "source_count": len(memories)
                }

        except Exception as e:
            logger.error(f"Create session summary failed: {e}")
            return {"success": False, "error": str(e)}

    # =========================================================================
    # STATISTICS
    # =========================================================================

    def get_memory_stats(self) -> Dict[str, Any]:
        """Get statistics about the memory hierarchy."""
        try:
            with self._get_cursor() as cur:
                # Counts by tier
                cur.execute("""
                    SELECT t.tier_name, COUNT(m.id) as count,
                           AVG(m.importance) as avg_importance,
                           AVG(m.recency_score) as avg_recency
                    FROM memory_tiers t
                    LEFT JOIN memory_items m ON t.id = m.tier_id
                    GROUP BY t.tier_name, t.tier_level
                    ORDER BY t.tier_level
                """)

                tier_stats = {}
                for row in cur.fetchall():
                    tier_stats[row[0]] = {
                        "count": row[1],
                        "avg_importance": round(row[2], 2) if row[2] else 0,
                        "avg_recency": round(row[3], 2) if row[3] else 0
                    }

                # Total stats
                cur.execute("""
                    SELECT
                        COUNT(*) as total_memories,
                        AVG(importance) as avg_importance,
                        SUM(access_count) as total_accesses
                    FROM memory_items
                """)
                totals = cur.fetchone()

                # Summary stats
                cur.execute("SELECT COUNT(*) FROM memory_summaries WHERE is_active = TRUE")
                active_summaries = cur.fetchone()[0]

                # Contradiction stats
                cur.execute("""
                    SELECT resolution_status, COUNT(*)
                    FROM memory_contradictions
                    GROUP BY resolution_status
                """)
                contradictions = {row[0]: row[1] for row in cur.fetchall()}

                return {
                    "success": True,
                    "tiers": tier_stats,
                    "totals": {
                        "memories": totals[0] if totals else 0,
                        "avg_importance": round(totals[1], 2) if totals and totals[1] else 0,
                        "total_accesses": totals[2] if totals else 0
                    },
                    "summaries": active_summaries,
                    "contradictions": contradictions
                }

        except Exception as e:
            logger.error(f"Get memory stats failed: {e}")
            return {"success": False, "error": str(e)}
