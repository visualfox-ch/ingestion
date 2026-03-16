"""
Knowledge Base Analytics Service - Tier 2 Feature

Provides insights into knowledge base effectiveness:
- Track which facts/knowledge entries are used
- Identify stale/unused knowledge
- Find gaps (queries without good matches)
- Quality scoring for knowledge sources
- Recommendations for KB optimization

Builds on existing:
- tool_usage_analytics.py (tool stats)
- quality_scorer.py (quality assessment)
- self_knowledge.py (Jarvis knowledge)
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timedelta
from collections import defaultdict
import json

from ..observability import get_logger, log_with_context
from ..postgres_state import get_conn

logger = get_logger("jarvis.knowledge_analytics")


@dataclass
class KnowledgeEntry:
    """A knowledge base entry with usage stats."""
    entry_id: str
    source: str
    content_preview: str
    created_at: datetime
    last_used_at: Optional[datetime] = None
    usage_count: int = 0
    avg_relevance_score: float = 0.0
    helped_queries: int = 0  # Queries where this entry contributed to success


@dataclass
class KnowledgeGap:
    """A gap in the knowledge base."""
    query_pattern: str
    occurrences: int
    sample_queries: List[str]
    suggested_topic: str
    priority: str  # high, medium, low


@dataclass
class KBHealthReport:
    """Overall KB health report."""
    total_entries: int
    active_entries: int  # Used in last 30 days
    stale_entries: int   # Not used in 60+ days
    avg_usage_score: float
    top_sources: List[Tuple[str, int]]
    gaps_found: int
    recommendations: List[str]


class KnowledgeAnalyticsService:
    """
    Analytics for Knowledge Base effectiveness.

    Tracks:
    - Knowledge entry usage (which facts help answer queries)
    - Source quality (which sources provide best answers)
    - Query gaps (what knowledge is missing)
    - Staleness (unused knowledge)
    """

    def __init__(self):
        self._ensure_tables()

    def _ensure_tables(self):
        """Ensure analytics tables exist."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    # Knowledge usage tracking
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS jarvis_knowledge_usage (
                            id SERIAL PRIMARY KEY,
                            entry_id VARCHAR(100) NOT NULL,
                            source VARCHAR(200),
                            query_hash VARCHAR(32),
                            query_keywords JSONB,
                            relevance_score FLOAT,
                            contributed_to_answer BOOLEAN DEFAULT FALSE,
                            session_id VARCHAR(100),
                            created_at TIMESTAMP DEFAULT NOW()
                        )
                    """)

                    # Knowledge gaps tracking
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS jarvis_knowledge_gaps (
                            id SERIAL PRIMARY KEY,
                            query_pattern VARCHAR(500) NOT NULL,
                            query_keywords JSONB NOT NULL,
                            occurrence_count INTEGER DEFAULT 1,
                            sample_queries JSONB DEFAULT '[]'::jsonb,
                            suggested_topic VARCHAR(200),
                            priority VARCHAR(20) DEFAULT 'medium',
                            resolved BOOLEAN DEFAULT FALSE,
                            resolved_at TIMESTAMP,
                            created_at TIMESTAMP DEFAULT NOW(),
                            updated_at TIMESTAMP DEFAULT NOW()
                        )
                    """)

                    # Source quality metrics
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS jarvis_source_quality (
                            id SERIAL PRIMARY KEY,
                            source_path VARCHAR(500) NOT NULL UNIQUE,
                            source_type VARCHAR(50),
                            total_uses INTEGER DEFAULT 0,
                            successful_uses INTEGER DEFAULT 0,
                            avg_relevance FLOAT DEFAULT 0.0,
                            last_used_at TIMESTAMP,
                            quality_score FLOAT DEFAULT 0.5,
                            created_at TIMESTAMP DEFAULT NOW(),
                            updated_at TIMESTAMP DEFAULT NOW()
                        )
                    """)

                    # Indexes
                    cur.execute("""
                        CREATE INDEX IF NOT EXISTS idx_knowledge_usage_entry
                        ON jarvis_knowledge_usage(entry_id)
                    """)
                    cur.execute("""
                        CREATE INDEX IF NOT EXISTS idx_knowledge_usage_source
                        ON jarvis_knowledge_usage(source)
                    """)
                    cur.execute("""
                        CREATE INDEX IF NOT EXISTS idx_knowledge_gaps_keywords
                        ON jarvis_knowledge_gaps USING GIN (query_keywords)
                    """)

                    conn.commit()

        except Exception as e:
            log_with_context(logger, "debug", "KB analytics tables init", error=str(e))

    def record_knowledge_usage(
        self,
        entry_id: str,
        source: str,
        query: str,
        relevance_score: float,
        contributed_to_answer: bool = False,
        session_id: Optional[str] = None
    ):
        """Record that a knowledge entry was used."""
        try:
            import hashlib
            import re

            # Extract keywords
            words = re.findall(r'\b[a-zäöüß]+\b', query.lower())
            keywords = [w for w in words if len(w) > 2][:10]
            query_hash = hashlib.md5(query.encode()).hexdigest()[:16]

            with get_conn() as conn:
                with conn.cursor() as cur:
                    # Record usage
                    cur.execute("""
                        INSERT INTO jarvis_knowledge_usage
                        (entry_id, source, query_hash, query_keywords, relevance_score,
                         contributed_to_answer, session_id)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """, (
                        entry_id, source, query_hash, json.dumps(keywords),
                        relevance_score, contributed_to_answer, session_id
                    ))

                    # Update source quality
                    cur.execute("""
                        INSERT INTO jarvis_source_quality
                        (source_path, source_type, total_uses, successful_uses, avg_relevance, last_used_at)
                        VALUES (%s, %s, 1, %s, %s, NOW())
                        ON CONFLICT (source_path) DO UPDATE SET
                            total_uses = jarvis_source_quality.total_uses + 1,
                            successful_uses = jarvis_source_quality.successful_uses + EXCLUDED.successful_uses,
                            avg_relevance = (jarvis_source_quality.avg_relevance * jarvis_source_quality.total_uses + EXCLUDED.avg_relevance)
                                          / (jarvis_source_quality.total_uses + 1),
                            last_used_at = NOW(),
                            quality_score = CASE
                                WHEN jarvis_source_quality.total_uses > 5
                                THEN (jarvis_source_quality.successful_uses::float + EXCLUDED.successful_uses)
                                     / (jarvis_source_quality.total_uses + 1) * 0.6
                                     + (jarvis_source_quality.avg_relevance * jarvis_source_quality.total_uses + EXCLUDED.avg_relevance)
                                       / (jarvis_source_quality.total_uses + 1) * 0.4
                                ELSE jarvis_source_quality.quality_score
                            END,
                            updated_at = NOW()
                    """, (
                        source,
                        source.split('/')[-1].split('.')[-1] if '.' in source else 'unknown',
                        1 if contributed_to_answer else 0,
                        relevance_score
                    ))

                    conn.commit()

        except Exception as e:
            log_with_context(logger, "debug", "Knowledge usage recording failed", error=str(e))

    def record_knowledge_gap(
        self,
        query: str,
        best_score: float,
        threshold: float = 0.5
    ):
        """Record a potential knowledge gap if search quality was low."""
        if best_score >= threshold:
            return  # Not a gap

        try:
            import re
            import hashlib

            words = re.findall(r'\b[a-zäöüß]+\b', query.lower())
            keywords = [w for w in words if len(w) > 2][:10]

            if not keywords:
                return

            # Use first keyword as pattern (simplified)
            pattern = keywords[0] if keywords else "unknown"

            with get_conn() as conn:
                with conn.cursor() as cur:
                    # Check if similar gap exists
                    cur.execute("""
                        SELECT id, occurrence_count, sample_queries
                        FROM jarvis_knowledge_gaps
                        WHERE query_keywords ?| %s
                        AND resolved = FALSE
                        LIMIT 1
                    """, (keywords,))

                    existing = cur.fetchone()

                    if existing:
                        # Update existing gap
                        samples = existing["sample_queries"] or []
                        if len(samples) < 5:
                            samples.append(query[:200])

                        cur.execute("""
                            UPDATE jarvis_knowledge_gaps
                            SET occurrence_count = occurrence_count + 1,
                                sample_queries = %s,
                                updated_at = NOW(),
                                priority = CASE
                                    WHEN occurrence_count >= 10 THEN 'high'
                                    WHEN occurrence_count >= 5 THEN 'medium'
                                    ELSE 'low'
                                END
                            WHERE id = %s
                        """, (json.dumps(samples), existing["id"]))
                    else:
                        # Create new gap
                        cur.execute("""
                            INSERT INTO jarvis_knowledge_gaps
                            (query_pattern, query_keywords, sample_queries, suggested_topic)
                            VALUES (%s, %s, %s, %s)
                        """, (
                            pattern,
                            json.dumps(keywords),
                            json.dumps([query[:200]]),
                            f"Knowledge about: {', '.join(keywords[:3])}"
                        ))

                    conn.commit()

        except Exception as e:
            log_with_context(logger, "debug", "Gap recording failed", error=str(e))

    def get_kb_health_report(self, days: int = 30) -> Dict[str, Any]:
        """Get overall KB health report."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    # Total entries with usage
                    cur.execute("""
                        SELECT COUNT(DISTINCT entry_id) as total
                        FROM jarvis_knowledge_usage
                    """)
                    total = cur.fetchone()["total"]

                    # Active entries (used recently)
                    cur.execute("""
                        SELECT COUNT(DISTINCT entry_id) as active
                        FROM jarvis_knowledge_usage
                        WHERE created_at > NOW() - INTERVAL '%s days'
                    """, (days,))
                    active = cur.fetchone()["active"]

                    # Top sources
                    cur.execute("""
                        SELECT source_path, total_uses, quality_score
                        FROM jarvis_source_quality
                        ORDER BY total_uses DESC
                        LIMIT 10
                    """)
                    top_sources = [
                        {
                            "source": row["source_path"],
                            "uses": row["total_uses"],
                            "quality": round(row["quality_score"], 2)
                        }
                        for row in cur.fetchall()
                    ]

                    # Unresolved gaps
                    cur.execute("""
                        SELECT COUNT(*) as cnt FROM jarvis_knowledge_gaps
                        WHERE resolved = FALSE
                    """)
                    gaps = cur.fetchone()["cnt"]

                    # High priority gaps
                    cur.execute("""
                        SELECT query_pattern, occurrence_count, suggested_topic
                        FROM jarvis_knowledge_gaps
                        WHERE resolved = FALSE AND priority = 'high'
                        ORDER BY occurrence_count DESC
                        LIMIT 5
                    """)
                    high_priority_gaps = [
                        {
                            "pattern": row["query_pattern"],
                            "occurrences": row["occurrence_count"],
                            "topic": row["suggested_topic"]
                        }
                        for row in cur.fetchall()
                    ]

                    # Average relevance
                    cur.execute("""
                        SELECT AVG(relevance_score) as avg
                        FROM jarvis_knowledge_usage
                        WHERE created_at > NOW() - INTERVAL '%s days'
                    """, (days,))
                    avg_relevance = cur.fetchone()["avg"] or 0

                    # Generate recommendations
                    recommendations = []
                    if gaps > 10:
                        recommendations.append(f"Hohe Priorität: {gaps} Wissenslücken gefunden")
                    if avg_relevance < 0.6:
                        recommendations.append("Knowledge Quality unter 60% - Quellen überprüfen")
                    if active < total * 0.3:
                        recommendations.append("Viele ungenutzte Einträge - KB aufräumen")
                    if high_priority_gaps:
                        topics = [g["topic"] for g in high_priority_gaps[:3]]
                        recommendations.append(f"Fehlende Themen: {', '.join(topics)}")

                    return {
                        "success": True,
                        "period_days": days,
                        "total_entries_tracked": total,
                        "active_entries": active,
                        "stale_ratio": round(1 - (active / max(total, 1)), 2),
                        "avg_relevance_score": round(avg_relevance, 2),
                        "unresolved_gaps": gaps,
                        "high_priority_gaps": high_priority_gaps,
                        "top_sources": top_sources,
                        "recommendations": recommendations,
                        "health_score": self._calculate_health_score(total, active, avg_relevance, gaps)
                    }

        except Exception as e:
            log_with_context(logger, "error", "KB health report failed", error=str(e))
            return {"success": False, "error": str(e)}

    def _calculate_health_score(
        self,
        total: int,
        active: int,
        avg_relevance: float,
        gaps: int
    ) -> float:
        """Calculate overall KB health score (0-1)."""
        if total == 0:
            return 0.5  # Neutral if no data

        activity_score = min(1.0, active / max(total * 0.3, 1))  # 30% active = 100%
        relevance_score = avg_relevance
        gap_penalty = min(0.3, gaps * 0.02)  # Max 30% penalty for gaps

        health = (activity_score * 0.3 + relevance_score * 0.5) - gap_penalty
        return round(max(0.0, min(1.0, health + 0.2)), 2)  # Add 0.2 base

    def get_source_rankings(self, limit: int = 20) -> Dict[str, Any]:
        """Get ranked list of knowledge sources by quality."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT
                            source_path,
                            source_type,
                            total_uses,
                            successful_uses,
                            avg_relevance,
                            quality_score,
                            last_used_at
                        FROM jarvis_source_quality
                        WHERE total_uses >= 3
                        ORDER BY quality_score DESC
                        LIMIT %s
                    """, (limit,))

                    sources = []
                    for row in cur.fetchall():
                        sources.append({
                            "source": row["source_path"],
                            "type": row["source_type"],
                            "uses": row["total_uses"],
                            "success_rate": round(row["successful_uses"] / max(row["total_uses"], 1), 2),
                            "avg_relevance": round(row["avg_relevance"], 2),
                            "quality_score": round(row["quality_score"], 2),
                            "last_used": row["last_used_at"].isoformat() if row["last_used_at"] else None
                        })

                    return {
                        "success": True,
                        "count": len(sources),
                        "sources": sources
                    }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_knowledge_gaps(
        self,
        priority: Optional[str] = None,
        limit: int = 20
    ) -> Dict[str, Any]:
        """Get list of knowledge gaps."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    query = """
                        SELECT
                            query_pattern,
                            query_keywords,
                            occurrence_count,
                            sample_queries,
                            suggested_topic,
                            priority,
                            created_at
                        FROM jarvis_knowledge_gaps
                        WHERE resolved = FALSE
                    """
                    params = []

                    if priority:
                        query += " AND priority = %s"
                        params.append(priority)

                    query += " ORDER BY occurrence_count DESC LIMIT %s"
                    params.append(limit)

                    cur.execute(query, params)

                    gaps = []
                    for row in cur.fetchall():
                        gaps.append({
                            "pattern": row["query_pattern"],
                            "keywords": row["query_keywords"],
                            "occurrences": row["occurrence_count"],
                            "samples": row["sample_queries"][:3] if row["sample_queries"] else [],
                            "suggested_topic": row["suggested_topic"],
                            "priority": row["priority"]
                        })

                    return {
                        "success": True,
                        "count": len(gaps),
                        "gaps": gaps
                    }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def mark_gap_resolved(self, gap_id: int) -> bool:
        """Mark a knowledge gap as resolved."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE jarvis_knowledge_gaps
                        SET resolved = TRUE, resolved_at = NOW()
                        WHERE id = %s
                    """, (gap_id,))
                    conn.commit()
                    return True
        except Exception as e:
            log_with_context(logger, "error", "Mark gap resolved failed", error=str(e))
            return False


# Singleton
_service: Optional[KnowledgeAnalyticsService] = None


def get_knowledge_analytics() -> KnowledgeAnalyticsService:
    """Get or create knowledge analytics service singleton."""
    global _service
    if _service is None:
        _service = KnowledgeAnalyticsService()
    return _service
