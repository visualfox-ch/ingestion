"""
Smart Memory Retrieval System

Multi-signal ranking with context-aware retrieval for Jarvis.

Retrieval Strategies:
1. Semantic: Qdrant vector similarity
2. Keyword: Meilisearch BM25
3. Temporal: Recency-weighted scoring
4. Relational: Entity graph traversal
5. Contextual: Query context matching

Ranking Signals:
- Semantic similarity (40%)
- Keyword match (15%)
- Recency (15%)
- Access frequency (10%)
- Trust/confidence (10%)
- Context relevance (10%)
"""

import logging
import math
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from functools import lru_cache

logger = logging.getLogger(__name__)


# =============================================================================
# Retrieval Strategy Types
# =============================================================================

class RetrievalStrategy(str, Enum):
    """Available retrieval strategies."""
    SEMANTIC = "semantic"           # Vector similarity only
    KEYWORD = "keyword"             # BM25 keyword search only
    HYBRID = "hybrid"               # Semantic + keyword fusion
    TEMPORAL = "temporal"           # Prioritize recent memories
    RELATIONAL = "relational"       # Follow entity relationships
    CONTEXTUAL = "contextual"       # Match query context patterns
    ADAPTIVE = "adaptive"           # Auto-select based on query


class MemoryType(str, Enum):
    """Types of memories that can be retrieved."""
    FACT = "fact"
    PREFERENCE = "preference"
    PATTERN = "pattern"
    EVENT = "event"
    CONVERSATION = "conversation"
    RELATIONSHIP = "relationship"
    KNOWLEDGE = "knowledge"
    ALL = "all"


# =============================================================================
# Data Models
# =============================================================================

@dataclass
class RetrievalContext:
    """Context for retrieval operations."""
    user_id: str
    query: str
    namespace: str = "private"
    memory_types: List[MemoryType] = field(default_factory=lambda: [MemoryType.ALL])
    time_range: Optional[Tuple[datetime, datetime]] = None
    entity_filter: Optional[List[str]] = None
    min_confidence: float = 0.0
    max_results: int = 10
    include_related: bool = True
    session_context: Optional[Dict[str, Any]] = None


@dataclass
class RetrievalResult:
    """A single retrieval result with scoring details."""
    id: str
    content: str
    memory_type: MemoryType
    source: str
    created_at: datetime

    # Scoring signals
    semantic_score: float = 0.0
    keyword_score: float = 0.0
    recency_score: float = 0.0
    access_score: float = 0.0
    trust_score: float = 0.0
    context_score: float = 0.0

    # Combined score
    final_score: float = 0.0

    # Metadata
    tags: List[str] = field(default_factory=list)
    entities: List[str] = field(default_factory=list)
    confidence: float = 0.5
    access_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Explanation
    score_breakdown: Dict[str, float] = field(default_factory=dict)


@dataclass
class RetrievalResponse:
    """Complete retrieval response."""
    query: str
    strategy_used: RetrievalStrategy
    results: List[RetrievalResult]
    total_candidates: int
    retrieval_time_ms: float
    signals_used: List[str]
    query_understanding: Dict[str, Any] = field(default_factory=dict)


# =============================================================================
# Signal Weights Configuration
# =============================================================================

DEFAULT_WEIGHTS = {
    "semantic": 0.40,
    "keyword": 0.15,
    "recency": 0.15,
    "access": 0.10,
    "trust": 0.10,
    "context": 0.10,
}

# Strategy-specific weight overrides
STRATEGY_WEIGHTS = {
    RetrievalStrategy.SEMANTIC: {
        "semantic": 0.70, "keyword": 0.10, "recency": 0.05,
        "access": 0.05, "trust": 0.05, "context": 0.05
    },
    RetrievalStrategy.KEYWORD: {
        "semantic": 0.10, "keyword": 0.70, "recency": 0.05,
        "access": 0.05, "trust": 0.05, "context": 0.05
    },
    RetrievalStrategy.TEMPORAL: {
        "semantic": 0.25, "keyword": 0.10, "recency": 0.40,
        "access": 0.10, "trust": 0.05, "context": 0.10
    },
    RetrievalStrategy.CONTEXTUAL: {
        "semantic": 0.30, "keyword": 0.10, "recency": 0.10,
        "access": 0.05, "trust": 0.10, "context": 0.35
    },
}


# =============================================================================
# Query Understanding
# =============================================================================

class QueryAnalyzer:
    """Analyzes queries to determine optimal retrieval strategy."""

    # Temporal keywords
    TEMPORAL_KEYWORDS = {
        "recent", "recently", "latest", "last", "yesterday", "today",
        "this week", "this month", "gestern", "heute", "letzte", "neueste"
    }

    # Relational keywords
    RELATIONAL_KEYWORDS = {
        "about", "regarding", "related to", "concerning", "with",
        "über", "bezüglich", "zu", "mit"
    }

    # Fact-seeking keywords
    FACT_KEYWORDS = {
        "what is", "who is", "when", "where", "how many", "how much",
        "was ist", "wer ist", "wann", "wo", "wie viel"
    }

    # Preference keywords
    PREFERENCE_KEYWORDS = {
        "prefer", "like", "favorite", "usually", "always", "never",
        "bevorzuge", "mag", "lieblings", "normalerweise", "immer", "nie"
    }

    def analyze(self, query: str) -> Dict[str, Any]:
        """Analyze query to extract intent and suggest strategy."""
        query_lower = query.lower()

        analysis = {
            "intent": "general",
            "temporal_focus": False,
            "relational_focus": False,
            "fact_seeking": False,
            "preference_seeking": False,
            "extracted_entities": [],
            "suggested_strategy": RetrievalStrategy.HYBRID,
            "suggested_memory_types": [MemoryType.ALL],
            "time_hints": [],
        }

        # Check temporal focus
        if any(kw in query_lower for kw in self.TEMPORAL_KEYWORDS):
            analysis["temporal_focus"] = True
            analysis["suggested_strategy"] = RetrievalStrategy.TEMPORAL

        # Check relational focus
        if any(kw in query_lower for kw in self.RELATIONAL_KEYWORDS):
            analysis["relational_focus"] = True
            analysis["suggested_strategy"] = RetrievalStrategy.RELATIONAL

        # Check fact-seeking
        if any(kw in query_lower for kw in self.FACT_KEYWORDS):
            analysis["fact_seeking"] = True
            analysis["suggested_memory_types"] = [MemoryType.FACT, MemoryType.KNOWLEDGE]

        # Check preference-seeking
        if any(kw in query_lower for kw in self.PREFERENCE_KEYWORDS):
            analysis["preference_seeking"] = True
            analysis["suggested_memory_types"] = [MemoryType.PREFERENCE, MemoryType.PATTERN]

        # Extract potential entity mentions (capitalized words)
        words = query.split()
        entities = [w for w in words if w[0].isupper() and len(w) > 2 and w not in ["Was", "Wer", "What", "Who", "The"]]
        analysis["extracted_entities"] = entities

        return analysis


# =============================================================================
# Scoring Functions
# =============================================================================

class ScoringEngine:
    """Calculates multi-signal scores for retrieval results."""

    def __init__(self, weights: Optional[Dict[str, float]] = None):
        self.weights = weights or DEFAULT_WEIGHTS.copy()

    def calculate_recency_score(
        self,
        created_at: datetime,
        half_life_days: float = 14.0
    ) -> float:
        """Calculate recency score with exponential decay."""
        now = datetime.utcnow()
        age_days = (now - created_at).total_seconds() / 86400

        # Exponential decay with configurable half-life
        score = math.exp(-0.693 * age_days / half_life_days)
        return max(0.0, min(1.0, score))

    def calculate_access_score(
        self,
        access_count: int,
        max_accesses: int = 100
    ) -> float:
        """Calculate access frequency score (log-scaled)."""
        if access_count <= 0:
            return 0.0
        # Log scale to prevent high-access items from dominating
        score = math.log(1 + access_count) / math.log(1 + max_accesses)
        return max(0.0, min(1.0, score))

    def calculate_context_score(
        self,
        result_context: Dict[str, Any],
        query_context: Dict[str, Any]
    ) -> float:
        """Calculate context relevance score."""
        if not query_context or not result_context:
            return 0.5  # Neutral score if no context

        score = 0.0
        matches = 0

        # Check namespace match
        if result_context.get("namespace") == query_context.get("namespace"):
            score += 0.3
            matches += 1

        # Check entity overlap
        result_entities = set(result_context.get("entities", []))
        query_entities = set(query_context.get("entities", []))
        if result_entities and query_entities:
            overlap = len(result_entities & query_entities) / len(result_entities | query_entities)
            score += 0.4 * overlap
            matches += 1

        # Check tag overlap
        result_tags = set(result_context.get("tags", []))
        query_tags = set(query_context.get("tags", []))
        if result_tags and query_tags:
            overlap = len(result_tags & query_tags) / len(result_tags | query_tags)
            score += 0.3 * overlap
            matches += 1

        return score if matches > 0 else 0.5

    def calculate_final_score(
        self,
        result: RetrievalResult,
        query_context: Optional[Dict[str, Any]] = None
    ) -> float:
        """Calculate weighted final score from all signals."""

        # Calculate context score
        result.context_score = self.calculate_context_score(
            {"namespace": result.metadata.get("namespace"),
             "entities": result.entities,
             "tags": result.tags},
            query_context or {}
        )

        # Calculate recency score
        result.recency_score = self.calculate_recency_score(result.created_at)

        # Calculate access score
        result.access_score = self.calculate_access_score(result.access_count)

        # Weighted sum
        final = (
            self.weights["semantic"] * result.semantic_score +
            self.weights["keyword"] * result.keyword_score +
            self.weights["recency"] * result.recency_score +
            self.weights["access"] * result.access_score +
            self.weights["trust"] * result.trust_score +
            self.weights["context"] * result.context_score
        )

        result.final_score = final
        result.score_breakdown = {
            "semantic": round(self.weights["semantic"] * result.semantic_score, 4),
            "keyword": round(self.weights["keyword"] * result.keyword_score, 4),
            "recency": round(self.weights["recency"] * result.recency_score, 4),
            "access": round(self.weights["access"] * result.access_score, 4),
            "trust": round(self.weights["trust"] * result.trust_score, 4),
            "context": round(self.weights["context"] * result.context_score, 4),
        }

        return final


# =============================================================================
# Smart Retrieval Engine
# =============================================================================

class SmartRetrieval:
    """
    Main retrieval engine with multi-signal ranking.

    Combines multiple retrieval strategies and scoring signals
    to find the most relevant memories for a given query.
    """

    def __init__(self):
        self.query_analyzer = QueryAnalyzer()
        self.scoring_engine = ScoringEngine()
        self._qdrant_client = None
        self._meilisearch_client = None

    @property
    def qdrant(self):
        """Lazy-load Qdrant client."""
        if self._qdrant_client is None:
            from qdrant_client import QdrantClient
            self._qdrant_client = QdrantClient(
                host=os.getenv("QDRANT_HOST", "qdrant"),
                port=int(os.getenv("QDRANT_PORT", 6333))
            )
        return self._qdrant_client

    @property
    def meilisearch(self):
        """Lazy-load Meilisearch client."""
        if self._meilisearch_client is None:
            import meilisearch
            self._meilisearch_client = meilisearch.Client(
                f"http://{os.getenv('MEILISEARCH_HOST', 'meilisearch')}:{os.getenv('MEILISEARCH_PORT', 7700)}",
                os.getenv("MEILISEARCH_KEY", "")
            )
        return self._meilisearch_client

    def retrieve(
        self,
        context: RetrievalContext,
        strategy: Optional[RetrievalStrategy] = None
    ) -> RetrievalResponse:
        """
        Main retrieval method.

        Args:
            context: Retrieval context with query and filters
            strategy: Override strategy (or auto-detect if None)

        Returns:
            RetrievalResponse with ranked results
        """
        import time
        start_time = time.time()

        # Analyze query
        query_understanding = self.query_analyzer.analyze(context.query)

        # Determine strategy
        if strategy is None or strategy == RetrievalStrategy.ADAPTIVE:
            strategy = query_understanding["suggested_strategy"]

        # Get strategy-specific weights
        weights = STRATEGY_WEIGHTS.get(strategy, DEFAULT_WEIGHTS)
        self.scoring_engine.weights = weights

        # Execute retrieval based on strategy
        candidates = self._execute_retrieval(context, strategy)

        # Apply additional filters
        filtered = self._apply_filters(candidates, context)

        # Calculate final scores
        query_context = {
            "namespace": context.namespace,
            "entities": query_understanding.get("extracted_entities", []),
            "tags": [],
        }

        for result in filtered:
            self.scoring_engine.calculate_final_score(result, query_context)

        # Sort by final score
        filtered.sort(key=lambda r: r.final_score, reverse=True)

        # Limit results
        results = filtered[:context.max_results]

        # Update access counts (async would be better)
        self._update_access_counts(results)

        elapsed_ms = (time.time() - start_time) * 1000

        return RetrievalResponse(
            query=context.query,
            strategy_used=strategy,
            results=results,
            total_candidates=len(candidates),
            retrieval_time_ms=elapsed_ms,
            signals_used=list(weights.keys()),
            query_understanding=query_understanding,
        )

    def _execute_retrieval(
        self,
        context: RetrievalContext,
        strategy: RetrievalStrategy
    ) -> List[RetrievalResult]:
        """Execute retrieval based on strategy."""
        results = []

        if strategy in [RetrievalStrategy.SEMANTIC, RetrievalStrategy.HYBRID,
                       RetrievalStrategy.ADAPTIVE, RetrievalStrategy.CONTEXTUAL]:
            semantic_results = self._semantic_search(context)
            results.extend(semantic_results)

        if strategy in [RetrievalStrategy.KEYWORD, RetrievalStrategy.HYBRID,
                       RetrievalStrategy.ADAPTIVE]:
            keyword_results = self._keyword_search(context)
            # Merge with semantic results
            results = self._merge_results(results, keyword_results)

        if strategy == RetrievalStrategy.TEMPORAL:
            # Boost recency in temporal strategy
            temporal_results = self._temporal_search(context)
            results = self._merge_results(results, temporal_results)

        if strategy == RetrievalStrategy.RELATIONAL:
            relational_results = self._relational_search(context)
            results = self._merge_results(results, relational_results)

        return results

    def _semantic_search(self, context: RetrievalContext) -> List[RetrievalResult]:
        """Perform semantic (vector) search."""
        try:
            from ..embed import embed_texts

            # Get query embedding
            query_embedding = embed_texts([context.query])[0]

            # Search Qdrant
            search_results = self.qdrant.search(
                collection_name="jarvis_knowledge",
                query_vector=query_embedding,
                limit=context.max_results * 3,  # Get more for fusion
                with_payload=True,
            )

            results = []
            for hit in search_results:
                payload = hit.payload or {}
                result = RetrievalResult(
                    id=str(hit.id),
                    content=payload.get("content", payload.get("text", "")),
                    memory_type=MemoryType(payload.get("type", "knowledge")),
                    source=payload.get("source", "qdrant"),
                    created_at=datetime.fromisoformat(payload.get("created_at", datetime.utcnow().isoformat())),
                    semantic_score=hit.score,
                    trust_score=payload.get("trust_score", 0.5),
                    confidence=payload.get("confidence", 0.5),
                    access_count=payload.get("access_count", 0),
                    tags=payload.get("tags", []),
                    entities=payload.get("entities", []),
                    metadata=payload,
                )
                results.append(result)

            return results

        except Exception as e:
            logger.warning(f"Semantic search failed: {e}")
            return []

    def _keyword_search(self, context: RetrievalContext) -> List[RetrievalResult]:
        """Perform keyword (BM25) search."""
        try:
            index = self.meilisearch.index("jarvis_knowledge")

            search_results = index.search(
                context.query,
                {"limit": context.max_results * 3}
            )

            results = []
            max_score = 1.0
            if search_results.get("hits"):
                # Normalize scores
                scores = [h.get("_rankingScore", 0) for h in search_results["hits"]]
                max_score = max(scores) if scores else 1.0

            for hit in search_results.get("hits", []):
                result = RetrievalResult(
                    id=str(hit.get("id", "")),
                    content=hit.get("content", hit.get("text", "")),
                    memory_type=MemoryType(hit.get("type", "knowledge")),
                    source="meilisearch",
                    created_at=datetime.fromisoformat(hit.get("created_at", datetime.utcnow().isoformat())),
                    keyword_score=hit.get("_rankingScore", 0) / max_score,
                    trust_score=hit.get("trust_score", 0.5),
                    confidence=hit.get("confidence", 0.5),
                    access_count=hit.get("access_count", 0),
                    tags=hit.get("tags", []),
                    entities=hit.get("entities", []),
                    metadata=hit,
                )
                results.append(result)

            return results

        except Exception as e:
            logger.warning(f"Keyword search failed: {e}")
            return []

    def _temporal_search(self, context: RetrievalContext) -> List[RetrievalResult]:
        """Search with temporal priority."""
        # Use semantic search but heavily weight recency
        results = self._semantic_search(context)

        # Sort by created_at before returning
        results.sort(key=lambda r: r.created_at, reverse=True)

        return results

    def _relational_search(self, context: RetrievalContext) -> List[RetrievalResult]:
        """Search following entity relationships."""
        # First, find entities mentioned in query
        query_understanding = self.query_analyzer.analyze(context.query)
        entities = query_understanding.get("extracted_entities", [])

        if not entities:
            # Fall back to semantic search
            return self._semantic_search(context)

        # Search for each entity and related items
        results = []
        for entity in entities[:3]:  # Limit entity expansion
            entity_context = RetrievalContext(
                user_id=context.user_id,
                query=entity,
                namespace=context.namespace,
                max_results=context.max_results // len(entities) + 1,
            )
            entity_results = self._semantic_search(entity_context)
            results.extend(entity_results)

        return results

    def _merge_results(
        self,
        results1: List[RetrievalResult],
        results2: List[RetrievalResult],
        k: int = 60
    ) -> List[RetrievalResult]:
        """Merge results using Reciprocal Rank Fusion."""
        scores: Dict[str, float] = {}
        result_map: Dict[str, RetrievalResult] = {}

        # RRF from first list
        for rank, result in enumerate(results1):
            rrf_score = 1.0 / (k + rank + 1)
            scores[result.id] = scores.get(result.id, 0) + rrf_score
            if result.id not in result_map:
                result_map[result.id] = result
            else:
                # Merge scores
                existing = result_map[result.id]
                existing.semantic_score = max(existing.semantic_score, result.semantic_score)
                existing.keyword_score = max(existing.keyword_score, result.keyword_score)

        # RRF from second list
        for rank, result in enumerate(results2):
            rrf_score = 1.0 / (k + rank + 1)
            scores[result.id] = scores.get(result.id, 0) + rrf_score
            if result.id not in result_map:
                result_map[result.id] = result
            else:
                existing = result_map[result.id]
                existing.semantic_score = max(existing.semantic_score, result.semantic_score)
                existing.keyword_score = max(existing.keyword_score, result.keyword_score)

        # Sort by RRF score
        sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)

        return [result_map[id] for id in sorted_ids]

    def _apply_filters(
        self,
        results: List[RetrievalResult],
        context: RetrievalContext
    ) -> List[RetrievalResult]:
        """Apply context filters to results."""
        filtered = []

        for result in results:
            # Filter by confidence
            if result.confidence < context.min_confidence:
                continue

            # Filter by memory type
            if MemoryType.ALL not in context.memory_types:
                if result.memory_type not in context.memory_types:
                    continue

            # Filter by time range
            if context.time_range:
                start, end = context.time_range
                if not (start <= result.created_at <= end):
                    continue

            # Filter by entity
            if context.entity_filter:
                if not any(e in result.entities for e in context.entity_filter):
                    continue

            filtered.append(result)

        return filtered

    def _update_access_counts(self, results: List[RetrievalResult]):
        """Update access counts for retrieved results (async in production)."""
        # In a real implementation, this would be async and batched
        pass


# =============================================================================
# Singleton Instance
# =============================================================================

_smart_retrieval: Optional[SmartRetrieval] = None

def get_smart_retrieval() -> SmartRetrieval:
    """Get singleton instance of SmartRetrieval."""
    global _smart_retrieval
    if _smart_retrieval is None:
        _smart_retrieval = SmartRetrieval()
    return _smart_retrieval
