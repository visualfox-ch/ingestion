"""
Hybrid Search - Combines Semantic (Qdrant) + Keyword (Meilisearch)

Uses Reciprocal Rank Fusion (RRF) to merge results from both search systems.
RRF formula: score = Σ 1/(k + rank) where k=60 (standard constant)

Enhanced Ranking Formula (Phase 12.3 - with Salience):
- 35% RRF (base fusion score)
- 22% Relevance (from knowledge_item.relevance_score)
- 18% Recency (exponential decay from last_seen_at/updated_at)
- 10% Salience (decision impact + goal relevance + surprise factor)
- 8% Confidence (from knowledge_item_version.confidence)
- 5% Fact Trust (from facts.trust_score)
- 2% Domain boost (namespace match bonus)

Benefits:
- Semantic: finds conceptually similar content ("what does the user mean?")
- Keyword: finds exact matches, names, dates ("precise lookup")
- Fusion: best of both worlds, handles edge cases better
- Relevance: prioritizes frequently accessed/reinforced knowledge
- Recency: fresher information ranks higher
- Salience: knowledge that led to good decisions ranks higher
"""
import os
import math
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed

from .observability import get_logger, log_with_context, rag_metrics, vector_cache, metrics
from . import config

logger = get_logger("jarvis.hybrid_search")

# Qdrant config
QDRANT_HOST = os.environ.get("QDRANT_HOST", "qdrant")
QDRANT_PORT = int(os.environ.get("QDRANT_PORT", "6333"))
QDRANT_BASE = f"http://{QDRANT_HOST}:{QDRANT_PORT}"

# RRF constant (standard value)
RRF_K = 60

# Enhanced ranking weights (Phase 12.3 - with Salience)
WEIGHT_RRF = 0.35        # Base fusion score
WEIGHT_RELEVANCE = 0.22  # Knowledge item relevance
WEIGHT_RECENCY = 0.18    # Time-based freshness
WEIGHT_SALIENCE = 0.10   # Decision impact + goal relevance
WEIGHT_CONFIDENCE = 0.08 # Content confidence level
WEIGHT_FACT_TRUST = 0.05 # Fact trust score
WEIGHT_DOMAIN = 0.02     # Namespace match bonus

# Recency decay: half-life of 14 days
RECENCY_HALF_LIFE_DAYS = 14
RECENCY_DECAY_RATE = math.log(2) / RECENCY_HALF_LIFE_DAYS


@dataclass
class HybridResult:
    """A search result with enhanced fusion score."""
    id: str
    text: str
    source: str  # "semantic", "keyword", "both"
    semantic_rank: Optional[int]
    keyword_rank: Optional[int]
    semantic_score: Optional[float]
    keyword_score: Optional[float]  # Meilisearch doesn't give scores, use rank
    fusion_score: float  # Final combined score
    metadata: Dict[str, Any]
    # Enhanced ranking components (Phase 12.3)
    rrf_score: float = 0.0          # Raw RRF before weighting
    relevance_score: float = 1.0    # From knowledge_item
    recency_score: float = 1.0      # Time-based freshness
    salience_score: float = 0.5     # Decision impact + goal relevance
    confidence_score: float = 0.8   # From knowledge_item_version
    fact_trust_score: float = 0.5   # From facts.trust_score
    domain_boost: float = 0.0       # Namespace match bonus


def _calculate_recency_score(last_seen: Optional[datetime]) -> float:
    """
    Calculate recency score based on time since last seen.
    Uses exponential decay with 14-day half-life.
    Returns 1.0 for very recent, decays towards 0.1 minimum.
    """
    if not last_seen:
        return 0.5  # Default for unknown

    now = datetime.utcnow()
    if hasattr(last_seen, 'replace'):
        last_seen = last_seen.replace(tzinfo=None)

    days_ago = (now - last_seen).total_seconds() / 86400

    if days_ago <= 0:
        return 1.0

    score = math.exp(-RECENCY_DECAY_RATE * days_ago)
    return max(0.1, round(score, 3))


def _normalize_confidence(confidence: str) -> float:
    """Convert confidence level to numeric score."""
    confidence_map = {
        "high": 1.0,
        "medium": 0.7,
        "low": 0.4,
        "unknown": 0.5
    }
    return confidence_map.get(str(confidence).lower(), 0.5)


def _rrf_score(ranks: List[Optional[int]], k: int = RRF_K) -> float:
    """
    Calculate Reciprocal Rank Fusion score.

    Args:
        ranks: List of ranks from different rankers (None if not present)
        k: Constant to prevent high scores for top-ranked items (default 60)

    Returns:
        Fused score (higher is better)
    """
    score = 0.0
    for rank in ranks:
        if rank is not None:
            score += 1.0 / (k + rank)
    return score


def _fetch_relevance_metadata(source_paths: List[str], namespace: str = None) -> Dict[str, Dict]:
    """
    Fetch relevance metadata from knowledge_item table for given source paths.

    Args:
        source_paths: List of source_path values from Qdrant results
        namespace: Optional namespace filter

    Returns dict mapping source_path -> {relevance_score, last_seen_at, confidence, namespace, salience_score}

    Note: Fixed in Phase 18 Data Pipeline Consistency - now matches by source_path
    instead of trying to match Qdrant hash IDs to knowledge_item integer IDs.
    """
    if not source_paths:
        return {}

    metadata = {}
    salience_lookup = {}

    # First, try to fetch salience scores from postgres_state (by source_path)
    try:
        from . import postgres_state
        # Get salience by source_path if available
        if hasattr(postgres_state, 'get_salience_scores_by_source'):
            salience_lookup = postgres_state.get_salience_scores_by_source(source_paths)
    except Exception as e:
        log_with_context(logger, "debug", "Could not fetch salience scores", error=str(e))

    try:
        from .knowledge_db import get_conn

        with get_conn() as conn:
            cur = conn.cursor()

            # Query knowledge items by source_path - the reliable key
            # This fixes the ID mismatch between Qdrant hashes and DB integers
            if source_paths:
                placeholders = ','.join(['%s'] * len(source_paths))
                cur.execute(f"""
                    SELECT ki.source_path, ki.relevance_score, ki.last_seen_at,
                           ki.namespace, kiv.confidence
                    FROM knowledge_item ki
                    LEFT JOIN knowledge_item_version kiv ON ki.current_version_id = kiv.id
                    WHERE ki.status = 'active'
                    AND ki.source_path IN ({placeholders})
                """, source_paths)

                for row in cur.fetchall():
                    src_path = row["source_path"]
                    metadata[src_path] = {
                        "relevance_score": float(row["relevance_score"] or 1.0),
                        "last_seen_at": row["last_seen_at"],
                        "confidence": row["confidence"] or "medium",
                        "namespace": row["namespace"],
                        "salience_score": salience_lookup.get(src_path, 0.5)
                    }

    except Exception as e:
        log_with_context(logger, "debug", "Could not fetch relevance metadata",
                        error=str(e), source_path_count=len(source_paths))

    # Add salience scores for items not in knowledge_item but in salience table
    for src_path in source_paths:
        if src_path not in metadata and src_path in salience_lookup:
            metadata[src_path] = {
                "relevance_score": 1.0,
                "last_seen_at": None,
                "confidence": "medium",
                "namespace": namespace,
                "salience_score": salience_lookup[src_path]
            }

    return metadata


def _fetch_fact_trust_scores(doc_ids: List[str]) -> Dict[str, float]:
    """
    Fetch trust scores for facts from memory_store.

    Returns dict mapping doc_id -> trust_score
    """
    if not doc_ids:
        return {}

    try:
        from . import memory_store
        return memory_store.get_fact_trust_scores(doc_ids)
    except Exception as e:
        log_with_context(logger, "debug", "Could not fetch fact trust scores", error=str(e))
        return {}


def _get_metadata_for_result(
    doc_id: str,
    result_metadata: Dict,
    relevance_lookup: Dict[str, Dict],
    target_namespace: str = None
) -> Dict[str, Any]:
    """
    Get enhanced metadata for a search result.

    Matches by source_path (the reliable key across Qdrant/Postgres/Meilisearch).
    Falls back to namespace match if source_path not found.

    Note: Fixed in Phase 18 - now uses source_path as primary key instead of
    trying to match Qdrant hash IDs to knowledge_item integer IDs.
    """
    # Primary: Match by source_path (fixed in Phase 18)
    source_path = result_metadata.get("source_path", "")
    if source_path and source_path in relevance_lookup:
        return relevance_lookup[source_path]

    # Fallback: Try namespace match
    result_namespace = result_metadata.get("namespace", "")
    for key, meta in relevance_lookup.items():
        if meta.get("namespace") == result_namespace:
            return meta

    # Default values
    return {
        "relevance_score": float(result_metadata.get("relevance_score", 1.0)),
        "last_seen_at": None,
        "confidence": result_metadata.get("confidence", "medium"),
        "namespace": result_namespace,
        "salience_score": 0.5  # Default salience
    }


def _get_available_collections() -> List[str]:
    """Get list of available Qdrant collections."""
    try:
        r = requests.get(f"{QDRANT_BASE}/collections", timeout=5)
        r.raise_for_status()
        data = r.json()
        return [c["name"] for c in data.get("result", {}).get("collections", [])]
    except Exception:
        return []


def _semantic_search(
    query_embedding: List[float],
    collection: str,
    limit: int,
    filters: Dict = None
) -> List[Dict]:
    """Run semantic search on Qdrant."""
    try:
        # Check if collection exists
        available = _get_available_collections()
        if collection not in available:
            log_with_context(logger, "debug", "Collection not found, skipping semantic search",
                           collection=collection, available=available[:5])
            return []

        payload = {
            "vector": query_embedding,
            "limit": limit,
            "with_payload": True,
            # HNSW search optimization: lower ef = faster but less accurate
            "params": {
                "hnsw_ef": 64,
                "exact": False
            }
        }

        if filters:
            payload["filter"] = filters

        r = requests.post(
            f"{QDRANT_BASE}/collections/{collection}/points/search",
            json=payload,
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()

        results = []
        for i, hit in enumerate(data.get("result", [])):
            pl = hit.get("payload", {}) or {}
            results.append({
                "id": str(hit.get("id", "")),
                "rank": i + 1,
                "score": hit.get("score"),
                "text": pl.get("text", ""),
                "metadata": pl
            })

        return results

    except Exception as e:
        log_with_context(logger, "error", "Semantic search failed", error=str(e))
        return []


def _keyword_search(
    query: str,
    namespace: str = None,
    item_type: str = None,
    limit: int = 20
) -> List[Dict]:
    """Run keyword search on Meilisearch."""
    try:
        from . import meilisearch_client
        hits = meilisearch_client.search_knowledge(
            query=query,
            namespace=namespace,
            item_type=item_type,
            limit=limit
        )

        results = []
        for i, hit in enumerate(hits):
            results.append({
                "id": str(hit.get("id", "")),
                "rank": i + 1,
                "score": None,  # Meilisearch doesn't provide scores
                "text": hit.get("content_text", ""),
                "metadata": hit
            })

        return results

    except Exception as e:
        log_with_context(logger, "error", "Keyword search failed", error=str(e))
        return []


def hybrid_search(
    query: str,
    query_embedding: List[float],
    collection: str = None,
    namespace: Optional[str] = None,
    item_type: Optional[str] = None,
    limit: int = 20,
    semantic_weight: float = 0.5,
    keyword_weight: float = 0.5,
    qdrant_filters: Dict = None,
    include_comms: bool = True
) -> List[HybridResult]:
    """
    Perform hybrid search combining semantic and keyword search.

    Args:
        query: Text query for keyword search
        query_embedding: Vector embedding for semantic search
        collection: Qdrant collection name (default: jarvis_shared)
        namespace: Filter by namespace
        item_type: Filter by knowledge item type
        limit: Max results to return
        semantic_weight: Weight for semantic results (0.0-1.0)
        keyword_weight: Weight for keyword results (0.0-1.0)
        qdrant_filters: Additional Qdrant filters
        include_comms: Also search _comms collection (Phase 18 Namespace fix)

    Returns:
        List of HybridResult sorted by fusion score
    """
    # Build list of collections to search (Phase 18: Namespace Normalization)
    collections_to_search = []
    if collection:
        collections_to_search.append(collection)
    else:
        base_collection = f"jarvis_{namespace or 'shared'}"
        collections_to_search.append(base_collection)

    # Add _comms collection if include_comms is True
    if include_comms and namespace:
        comms_collection = f"jarvis_{namespace}_comms"
        available = _get_available_collections()
        if comms_collection in available:
            collections_to_search.append(comms_collection)

    # Log collections being searched (Phase 18 Namespace Normalization)
    log_with_context(logger, "debug", "Collections to search",
                    collections=collections_to_search, include_comms=include_comms)

    # Vector search cache (avoid repeated fusion for identical queries)
    cache_key = None
    if config.ENABLE_VECTOR_CACHE:
        cache_key = vector_cache._make_key(
            "hybrid_search",
            query,
            namespace,
            item_type,
            limit,
            semantic_weight,
            keyword_weight,
            collections_to_search,
            include_comms,
            qdrant_filters,
        )
        cached_results = vector_cache.get(cache_key)
        if cached_results is not None:
            metrics.inc("vector_cache_hits")
            return cached_results[:limit]
        metrics.inc("vector_cache_misses")

    # Run searches in parallel across all collections
    semantic_results = []
    keyword_results = []

    with ThreadPoolExecutor(max_workers=len(collections_to_search) + 1) as executor:
        futures = {}

        # Submit semantic search for EACH collection (Phase 18 fix)
        if semantic_weight > 0 and query_embedding:
            for coll in collections_to_search:
                futures[executor.submit(
                    _semantic_search,
                    query_embedding,
                    coll,
                    limit * 2,  # Fetch more for better fusion
                    qdrant_filters
                )] = f"semantic:{coll}"

        if keyword_weight > 0:
            futures[executor.submit(
                _keyword_search,
                query,
                namespace,
                item_type,
                limit * 2
            )] = "keyword"

        for future in as_completed(futures):
            search_type = futures[future]
            try:
                results = future.result()
                if search_type.startswith("semantic:"):
                    # Merge semantic results from multiple collections
                    semantic_results.extend(results)
                else:
                    keyword_results = results
            except Exception as e:
                log_with_context(logger, "error", f"{search_type} search failed", error=str(e))

    # Deduplicate semantic results by source_path (Phase 18 fix)
    # Keep the highest scoring result for each unique source_path
    seen_sources = {}
    deduped_semantic = []
    for r in sorted(semantic_results, key=lambda x: x.get("score", 0) or 0, reverse=True):
        src = r.get("metadata", {}).get("source_path", "") or r.get("id", "")
        if src not in seen_sources:
            seen_sources[src] = True
            deduped_semantic.append(r)
    semantic_results = deduped_semantic

    # Re-assign ranks after deduplication
    for i, r in enumerate(semantic_results):
        r["rank"] = i + 1

    # Build lookup maps
    semantic_map = {r["id"]: r for r in semantic_results}
    keyword_map = {r["id"]: r for r in keyword_results}

    # Get all unique IDs
    all_ids = set(semantic_map.keys()) | set(keyword_map.keys())

    # Collect unique source_paths for metadata lookup (Phase 18 fix)
    # source_path is the reliable key across Qdrant/Postgres/Meilisearch
    all_source_paths = set()
    for r in semantic_results + keyword_results:
        src = r.get("metadata", {}).get("source_path", "")
        if src:
            all_source_paths.add(src)

    # Fetch relevance metadata for enhanced ranking (Phase 12.3)
    # Fixed in Phase 18: now uses source_paths instead of Qdrant hash IDs
    relevance_lookup = _fetch_relevance_metadata(list(all_source_paths), namespace)

    # Fetch fact trust scores (Phase 12.3)
    fact_trust_lookup = _fetch_fact_trust_scores(list(all_ids))

    # Calculate fusion scores with enhanced ranking
    fused_results = []

    # Normalize RRF scores for proper weighting
    max_rrf = 2.0 / (RRF_K + 1)  # Max possible RRF score (rank 1 in both)

    for doc_id in all_ids:
        sem = semantic_map.get(doc_id)
        kw = keyword_map.get(doc_id)

        # Get ranks (None if not present in that search)
        sem_rank = sem["rank"] if sem else None
        kw_rank = kw["rank"] if kw else None

        # Calculate base RRF score
        rrf_raw = _rrf_score([sem_rank, kw_rank])
        rrf_normalized = rrf_raw / max_rrf if max_rrf > 0 else 0

        # Determine source
        if sem and kw:
            source = "both"
        elif sem:
            source = "semantic"
        else:
            source = "keyword"

        # Get best text and metadata
        primary = sem or kw
        text = primary["text"]
        result_metadata = primary["metadata"]

        # Merge metadata from both if available
        if sem and kw:
            result_metadata = {**kw["metadata"], **sem["metadata"]}

        # Get enhanced ranking components
        rel_meta = _get_metadata_for_result(doc_id, result_metadata, relevance_lookup, namespace)

        relevance = rel_meta.get("relevance_score", 1.0)
        recency = _calculate_recency_score(rel_meta.get("last_seen_at"))
        confidence = _normalize_confidence(rel_meta.get("confidence", "medium"))
        salience = rel_meta.get("salience_score", 0.5)
        fact_trust = fact_trust_lookup.get(doc_id, 0.5)

        # Domain boost: +1.0 if namespace matches target
        result_ns = result_metadata.get("namespace", "")
        domain_boost = 1.0 if (namespace and result_ns == namespace) else 0.5

        # Calculate final weighted score (Phase 12.3 formula)
        # 35% RRF + 22% relevance + 18% recency + 10% salience + 8% confidence + 5% fact_trust + 2% domain
        fusion_score = (
            WEIGHT_RRF * rrf_normalized +
            WEIGHT_RELEVANCE * relevance +
            WEIGHT_RECENCY * recency +
            WEIGHT_SALIENCE * salience +
            WEIGHT_CONFIDENCE * confidence +
            WEIGHT_FACT_TRUST * fact_trust +
            WEIGHT_DOMAIN * domain_boost
        )

        fused_results.append(HybridResult(
            id=doc_id,
            text=text,
            source=source,
            semantic_rank=sem_rank,
            keyword_rank=kw_rank,
            semantic_score=sem["score"] if sem else None,
            keyword_score=None,
            fusion_score=round(fusion_score, 4),
            metadata=result_metadata,
            rrf_score=round(rrf_normalized, 4),
            relevance_score=round(relevance, 3),
            recency_score=round(recency, 3),
            salience_score=round(salience, 3),
            confidence_score=round(confidence, 2),
            fact_trust_score=round(fact_trust, 3),
            domain_boost=round(domain_boost, 2)
        ))

    # Sort by fusion score (descending)
    fused_results.sort(key=lambda x: x.fusion_score, reverse=True)

    # Apply advanced ranking enhancements (Phase B Stream 2.3)
    # Cross-encoder reranking + temporal decay + domain weighting
    try:
        from . import ranking_service
        
        # Convert HybridResult to dict format for ranking service
        results_for_ranking = [
            {
                "id": r.id,
                "text": r.text,
                "score": r.fusion_score,
                "metadata": r.metadata
            }
            for r in fused_results
        ]
        
        # Apply ranking enhancements
        enhanced_results = ranking_service.enhance_ranking(
            query=query,
            results=results_for_ranking,
            query_domain=namespace,
            enable_cross_encoder=False,  # Disabled - model trained on passages
            enable_temporal_decay=False,  # Disabled - missing timestamps in test data
            enable_domain_weighting=False  # Disabled - validation pending
        )
        
        # Update fusion_score with enhanced scores
        enhanced_map = {r["id"]: r for r in enhanced_results}
        for hybrid_result in fused_results:
            enhanced = enhanced_map.get(hybrid_result.id)
            if enhanced:
                # Store original fusion score
                hybrid_result.metadata["original_fusion_score"] = hybrid_result.fusion_score
                # Update with enhanced score
                hybrid_result.fusion_score = enhanced.get("score", hybrid_result.fusion_score)
                # Add ranking enhancement metadata
                hybrid_result.metadata["cross_encoder_score"] = enhanced.get("cross_encoder_score")
                hybrid_result.metadata["recency_boost"] = enhanced.get("recency_score")
                hybrid_result.metadata["domain_boost_applied"] = enhanced.get("domain_boost")
        
        # Re-sort by enhanced fusion score
        fused_results.sort(key=lambda x: x.fusion_score, reverse=True)
        
        log_with_context(logger, "debug", "Advanced ranking enhancements applied",
                        results_count=len(fused_results))
    except Exception as e:
        log_with_context(logger, "warning", "Ranking enhancement failed, using base scores",
                        error=str(e))

    # Calculate source distribution for metrics
    source_dist = {
        "semantic": sum(1 for r in fused_results if r.source == "semantic"),
        "keyword": sum(1 for r in fused_results if r.source == "keyword"),
        "both": sum(1 for r in fused_results if r.source == "both"),
    }

    # Calculate average relevance/fusion score
    avg_relevance = None
    if fused_results:
        avg_relevance = sum(r.fusion_score for r in fused_results) / len(fused_results)

    # Record RAG metrics
    rag_metrics.record_search(
        search_type="hybrid",
        results_count=len(fused_results),
        avg_relevance=avg_relevance,
        source_distribution=source_dist,
        query_length=len(query)
    )

    # Log stats
    log_with_context(
        logger, "debug", "Hybrid search complete",
        semantic_count=len(semantic_results),
        keyword_count=len(keyword_results),
        fused_count=len(fused_results),
        both_count=source_dist["both"],
        avg_relevance=round(avg_relevance, 4) if avg_relevance else None
    )

    if cache_key:
        vector_cache.set(cache_key, fused_results)

    return fused_results[:limit]


def hybrid_search_simple(
    query: str,
    namespace: str = None,
    limit: int = 20
) -> List[Dict]:
    """
    Simplified hybrid search - auto-generates embedding.

    Returns plain dicts instead of HybridResult for API responses.
    """
    try:
        # Import here to avoid circular imports
        from .embed import embed_texts

        # Generate embedding
        embeddings = embed_texts([query])
        if not embeddings:
            log_with_context(logger, "warning", "Failed to generate embedding, falling back to keyword only")
            return [{"id": r["id"], "text": r["text"], "source": "keyword", "metadata": r["metadata"]}
                    for r in _keyword_search(query, namespace, None, limit)]

        query_embedding = embeddings[0]

        # Determine collection(s) to search
        available = _get_available_collections()
        if namespace:
            # Specific namespace requested
            collection = f"jarvis_{namespace}"
        elif available:
            # No namespace specified - use first available (typically jarvis_private)
            # Filter to main collections (not _comms)
            main_collections = [c for c in available if not c.endswith("_comms")]
            collection = main_collections[0] if main_collections else available[0]
            log_with_context(logger, "debug", "No namespace specified, using collection",
                           collection=collection)
        else:
            collection = "jarvis_private"  # Fallback default

        results = hybrid_search(
            query=query,
            query_embedding=query_embedding,
            collection=collection,
            namespace=namespace,
            limit=limit
        )

        # Convert to plain dicts with enhanced ranking info
        return [
            {
                "id": r.id,
                "text": r.text,
                "source": r.source,
                "semantic_rank": r.semantic_rank,
                "keyword_rank": r.keyword_rank,
                "semantic_score": r.semantic_score,
                "fusion_score": r.fusion_score,
                "metadata": r.metadata,
                # Enhanced ranking components (Phase 12.3)
                "ranking": {
                    "rrf": r.rrf_score,
                    "relevance": r.relevance_score,
                    "recency": r.recency_score,
                    "salience": r.salience_score,
                    "confidence": r.confidence_score,
                    "fact_trust": r.fact_trust_score,
                    "domain_boost": r.domain_boost
                }
            }
            for r in results
        ]

    except Exception as e:
        log_with_context(logger, "error", "Hybrid search simple failed", error=str(e))
        return []
