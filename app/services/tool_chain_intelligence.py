"""
Tool Chain Intelligence Service - Tier 2 Feature

Adds intelligence layer on top of existing tool chain tracking:
- Query-intent to chain mapping (learn which queries use which chains)
- Proactive chain suggestions based on context
- Integration with causal patterns for better recommendations
- Auto-inject chain hints into agent context

Builds on:
- tool_chain_analyzer.py (real-time tracking)
- smart_tool_chain_service.py (historical learning)
- causal_knowledge_service.py (pattern recognition)
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timedelta
from collections import defaultdict
import json
import re
import hashlib

from psycopg2.extras import RealDictCursor

from ..observability import get_logger, log_with_context
from ..postgres_state import get_conn

logger = get_logger("jarvis.tool_chain_intelligence")


@dataclass
class ChainRecommendation:
    """A recommended tool chain with context."""
    chain: List[str]
    confidence: float
    reason: str
    expected_duration_ms: int = 0
    success_rate: float = 0.0
    based_on_patterns: int = 0


@dataclass
class QueryChainMapping:
    """Maps query patterns to effective chains."""
    query_pattern: str
    query_keywords: List[str]
    effective_chains: List[ChainRecommendation]
    sample_queries: List[str] = field(default_factory=list)
    usage_count: int = 0


class ToolChainIntelligence:
    """
    Intelligent tool chain recommendation engine.

    Learns from:
    1. Historical tool chains (what worked together)
    2. Query patterns (what queries led to which chains)
    3. Causal patterns (cause→effect relationships)
    """

    def __init__(self):
        self._ensure_tables()
        self._query_chain_cache: Dict[str, List[ChainRecommendation]] = {}
        self._keyword_chain_map: Dict[str, List[str]] = {}

    def _ensure_tables(self):
        """Ensure intelligence tables exist."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS jarvis_query_chain_mappings (
                            id SERIAL PRIMARY KEY,
                            query_hash VARCHAR(32) NOT NULL,
                            query_keywords JSONB NOT NULL,
                            sample_query TEXT,
                            chain_pattern JSONB NOT NULL,
                            success_count INTEGER DEFAULT 1,
                            failure_count INTEGER DEFAULT 0,
                            avg_duration_ms FLOAT,
                            last_used_at TIMESTAMP DEFAULT NOW(),
                            created_at TIMESTAMP DEFAULT NOW(),
                            UNIQUE(query_hash, chain_pattern)
                        )
                    """)

                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS jarvis_chain_intent_clusters (
                            id SERIAL PRIMARY KEY,
                            intent_category VARCHAR(100) NOT NULL,
                            keywords JSONB NOT NULL,
                            common_chains JSONB NOT NULL,
                            confidence FLOAT DEFAULT 0.5,
                            sample_count INTEGER DEFAULT 0,
                            updated_at TIMESTAMP DEFAULT NOW()
                        )
                    """)

                    cur.execute("""
                        CREATE INDEX IF NOT EXISTS idx_query_chain_hash
                        ON jarvis_query_chain_mappings(query_hash)
                    """)
                    cur.execute("""
                        CREATE INDEX IF NOT EXISTS idx_chain_intent_category
                        ON jarvis_chain_intent_clusters(intent_category)
                    """)

                    conn.commit()
        except Exception as e:
            log_with_context(logger, "debug", "Table creation (may exist)", error=str(e))

    def _extract_keywords(self, query: str) -> List[str]:
        """Extract meaningful keywords from a query."""
        # Normalize
        query_lower = query.lower()

        # Remove common stop words
        stop_words = {
            "ich", "du", "er", "sie", "es", "wir", "ihr", "mich", "mir", "dir",
            "ein", "eine", "einer", "einem", "einen", "der", "die", "das",
            "und", "oder", "aber", "wenn", "weil", "dass", "wie", "was",
            "ist", "sind", "war", "waren", "hat", "haben", "wird", "werden",
            "kann", "können", "muss", "müssen", "soll", "sollen",
            "the", "a", "an", "is", "are", "was", "were", "be", "been",
            "have", "has", "do", "does", "did", "will", "would", "could",
            "should", "may", "might", "must", "shall",
            "i", "you", "he", "she", "it", "we", "they", "me", "him", "her",
            "bitte", "danke", "ja", "nein", "okay", "ok", "gut"
        }

        # Extract words
        words = re.findall(r'\b[a-zäöüß]+\b', query_lower)
        keywords = [w for w in words if w not in stop_words and len(w) > 2]

        return keywords[:10]  # Limit to 10 most relevant

    def _hash_keywords(self, keywords: List[str]) -> str:
        """Create a hash from sorted keywords for matching."""
        sorted_kw = sorted(set(keywords))
        return hashlib.md5(json.dumps(sorted_kw).encode()).hexdigest()[:16]

    def recommend_chains_for_query(
        self,
        query: str,
        current_tools: Optional[List[str]] = None,
        limit: int = 3
    ) -> List[ChainRecommendation]:
        """
        Recommend tool chains based on query analysis.

        Uses:
        1. Keyword matching against learned patterns
        2. Current tools context (what's already been used)
        3. Historical success rates
        """
        keywords = self._extract_keywords(query)
        if not keywords:
            return []

        recommendations = []

        try:
            with get_conn() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    # Find chains that match any of our keywords
                    cur.execute("""
                        SELECT
                            chain_pattern,
                            SUM(success_count) as total_success,
                            SUM(failure_count) as total_failure,
                            AVG(avg_duration_ms) as avg_duration,
                            COUNT(*) as pattern_count
                        FROM jarvis_query_chain_mappings
                        WHERE query_keywords ?| %s
                        GROUP BY chain_pattern
                        ORDER BY total_success DESC
                        LIMIT %s
                    """, (keywords, limit * 2))

                    rows = cur.fetchall()

                    for row in rows:
                        chain = json.loads(row["chain_pattern"]) if isinstance(row["chain_pattern"], str) else row["chain_pattern"]
                        total = row["total_success"] + row["total_failure"]
                        success_rate = row["total_success"] / total if total > 0 else 0.5

                        # Skip chains that start with tools we've already used
                        if current_tools and chain[0] in current_tools:
                            continue

                        recommendations.append(ChainRecommendation(
                            chain=chain,
                            confidence=success_rate,
                            reason="keyword_match",
                            expected_duration_ms=int(row["avg_duration"] or 0),
                            success_rate=success_rate,
                            based_on_patterns=row["pattern_count"]
                        ))

                    # Also check intent clusters
                    cur.execute("""
                        SELECT intent_category, common_chains, confidence
                        FROM jarvis_chain_intent_clusters
                        WHERE keywords ?| %s
                        ORDER BY confidence DESC
                        LIMIT 3
                    """, (keywords,))

                    for row in cur.fetchall():
                        chains = json.loads(row["common_chains"]) if isinstance(row["common_chains"], str) else row["common_chains"]
                        for chain in chains[:2]:
                            if current_tools and chain[0] in current_tools:
                                continue
                            recommendations.append(ChainRecommendation(
                                chain=chain,
                                confidence=row["confidence"],
                                reason=f"intent:{row['intent_category']}",
                                success_rate=row["confidence"]
                            ))

        except Exception as e:
            log_with_context(logger, "debug", "Chain recommendation failed", error=str(e))

        # Deduplicate and sort by confidence
        seen_chains = set()
        unique_recs = []
        for rec in sorted(recommendations, key=lambda x: x.confidence, reverse=True):
            chain_key = json.dumps(rec.chain)
            if chain_key not in seen_chains:
                seen_chains.add(chain_key)
                unique_recs.append(rec)

        return unique_recs[:limit]

    def record_query_chain_usage(
        self,
        query: str,
        chain: List[str],
        success: bool,
        duration_ms: Optional[int] = None
    ):
        """Record that a query led to using a specific chain."""
        if len(chain) < 2:
            return  # Only track multi-tool chains

        keywords = self._extract_keywords(query)
        if not keywords:
            return

        query_hash = self._hash_keywords(keywords)

        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    # Check if mapping exists
                    cur.execute("""
                        SELECT id, success_count, failure_count, avg_duration_ms
                        FROM jarvis_query_chain_mappings
                        WHERE query_hash = %s AND chain_pattern = %s
                    """, (query_hash, json.dumps(chain)))

                    existing = cur.fetchone()

                    if existing:
                        # Update existing
                        new_success = existing["success_count"] + (1 if success else 0)
                        new_failure = existing["failure_count"] + (0 if success else 1)
                        total = new_success + new_failure

                        if duration_ms and existing["avg_duration_ms"]:
                            new_duration = (existing["avg_duration_ms"] * (total - 1) + duration_ms) / total
                        else:
                            new_duration = duration_ms or existing["avg_duration_ms"]

                        cur.execute("""
                            UPDATE jarvis_query_chain_mappings
                            SET success_count = %s, failure_count = %s,
                                avg_duration_ms = %s, last_used_at = NOW()
                            WHERE id = %s
                        """, (new_success, new_failure, new_duration, existing["id"]))
                    else:
                        # Create new mapping
                        cur.execute("""
                            INSERT INTO jarvis_query_chain_mappings
                            (query_hash, query_keywords, sample_query, chain_pattern,
                             success_count, failure_count, avg_duration_ms)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """, (
                            query_hash, json.dumps(keywords), query[:200],
                            json.dumps(chain),
                            1 if success else 0,
                            0 if success else 1,
                            duration_ms
                        ))

                    conn.commit()

        except Exception as e:
            log_with_context(logger, "debug", "Recording chain usage failed", error=str(e))

    def learn_intent_clusters(self, min_samples: int = 5) -> Dict[str, Any]:
        """
        Learn intent clusters from query-chain mappings.

        Groups similar queries and identifies their common chains.
        """
        clusters = defaultdict(lambda: {"keywords": [], "chains": defaultdict(int), "count": 0})

        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT query_keywords, chain_pattern, success_count
                        FROM jarvis_query_chain_mappings
                        WHERE success_count >= 1
                    """)

                    for row in cur.fetchall():
                        keywords = json.loads(row["query_keywords"]) if isinstance(row["query_keywords"], str) else row["query_keywords"]
                        chain = json.dumps(row["chain_pattern"]) if not isinstance(row["chain_pattern"], str) else row["chain_pattern"]

                        # Simple clustering by first keyword
                        if keywords:
                            category = keywords[0]
                            clusters[category]["keywords"].extend(keywords)
                            clusters[category]["chains"][chain] += row["success_count"]
                            clusters[category]["count"] += 1

                    # Save clusters with enough samples
                    saved = 0
                    for category, data in clusters.items():
                        if data["count"] >= min_samples:
                            # Get top chains
                            top_chains = sorted(
                                data["chains"].items(),
                                key=lambda x: x[1],
                                reverse=True
                            )[:5]

                            common_chains = [json.loads(c) for c, _ in top_chains]
                            unique_keywords = list(set(data["keywords"]))[:20]
                            confidence = min(1.0, data["count"] / 20)  # Scale confidence

                            cur.execute("""
                                INSERT INTO jarvis_chain_intent_clusters
                                (intent_category, keywords, common_chains, confidence, sample_count)
                                VALUES (%s, %s, %s, %s, %s)
                                ON CONFLICT (intent_category) DO UPDATE
                                SET keywords = EXCLUDED.keywords,
                                    common_chains = EXCLUDED.common_chains,
                                    confidence = EXCLUDED.confidence,
                                    sample_count = EXCLUDED.sample_count,
                                    updated_at = NOW()
                            """, (category, json.dumps(unique_keywords), json.dumps(common_chains),
                                  confidence, data["count"]))
                            saved += 1

                    conn.commit()

                    return {
                        "success": True,
                        "clusters_analyzed": len(clusters),
                        "clusters_saved": saved,
                        "min_samples_required": min_samples
                    }

        except Exception as e:
            log_with_context(logger, "error", "Intent clustering failed", error=str(e))
            return {"success": False, "error": str(e)}

    def get_chain_context_injection(self, query: str) -> Optional[str]:
        """
        Generate context injection text for agent prompt.

        If we have strong chain recommendations, inject them as hints.
        """
        recommendations = self.recommend_chains_for_query(query, limit=2)

        if not recommendations or recommendations[0].confidence < 0.6:
            return None

        # Build injection text
        lines = ["[TOOL CHAIN HINT]"]
        for i, rec in enumerate(recommendations[:2]):
            chain_str = " → ".join(rec.chain)
            lines.append(f"- Option {i+1}: {chain_str} (confidence: {rec.confidence:.0%})")

        lines.append("Consider using these tool sequences if appropriate.")

        return "\n".join(lines)

    def get_intelligence_stats(self) -> Dict[str, Any]:
        """Get statistics about tool chain intelligence."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT COUNT(*) as cnt FROM jarvis_query_chain_mappings")
                    mappings = cur.fetchone()["cnt"]

                    cur.execute("SELECT COUNT(*) as cnt FROM jarvis_chain_intent_clusters")
                    clusters = cur.fetchone()["cnt"]

                    cur.execute("""
                        SELECT AVG(success_count::float / NULLIF(success_count + failure_count, 0)) as avg_success
                        FROM jarvis_query_chain_mappings
                    """)
                    avg_success = cur.fetchone()["avg_success"]

                    return {
                        "query_chain_mappings": mappings,
                        "intent_clusters": clusters,
                        "avg_chain_success_rate": round(avg_success or 0, 2),
                        "status": "active"
                    }

        except Exception as e:
            return {"status": "error", "error": str(e)}


# Singleton
_intelligence: Optional[ToolChainIntelligence] = None


def get_tool_chain_intelligence() -> ToolChainIntelligence:
    """Get or create tool chain intelligence singleton."""
    global _intelligence
    if _intelligence is None:
        _intelligence = ToolChainIntelligence()
    return _intelligence
