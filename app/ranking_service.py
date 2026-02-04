"""
Advanced Ranking Service - Phase B Stream 2.3 Implementation
=============================================================

Implements:
1. Cross-Encoder Semantic Re-ranking (two-stage ranking)
2. Temporal Decay Scoring (recency boost)
3. Domain Context Weighting

This module provides ranking enhancements to push quality from 81% → 83-85%
"""

import os
import math
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from .observability import get_logger, log_with_context

logger = get_logger("jarvis.ranking")

# Cross-encoder model configuration
CROSS_ENCODER_MODEL = os.getenv("CROSS_ENCODER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")
CROSS_ENCODER_ENABLED = os.getenv("CROSS_ENCODER_ENABLED", "true").lower() in ("true", "1", "yes")
CROSS_ENCODER_RERANK_TOP_K = int(os.getenv("CROSS_ENCODER_RERANK_TOP_K", "10"))
CROSS_ENCODER_WEIGHT = 0.4  # Weight for cross-encoder score in final ranking

# Temporal decay configuration
RECENCY_HALF_LIFE_DAYS = int(os.getenv("RECENCY_HALF_LIFE_DAYS", "90"))
RECENCY_WEIGHT = float(os.getenv("RECENCY_WEIGHT", "0.15"))

# Domain weighting configuration
DOMAIN_BOOST_FACTOR = float(os.getenv("DOMAIN_BOOST_FACTOR", "1.2"))

# Lazy-loaded cross-encoder model
_cross_encoder = None
_cross_encoder_failed = False  # Track if loading failed


def _get_cross_encoder():
    """Lazy-load cross-encoder model on first use."""
    global _cross_encoder, _cross_encoder_failed
    
    # If already failed, don't try again
    if _cross_encoder_failed:
        return None
    
    if _cross_encoder is None and CROSS_ENCODER_ENABLED:
        try:
            from sentence_transformers import CrossEncoder
            log_with_context(logger, "info", "Loading cross-encoder model", model=CROSS_ENCODER_MODEL)
            _cross_encoder = CrossEncoder(CROSS_ENCODER_MODEL, max_length=512)
            log_with_context(logger, "info", "Cross-encoder loaded successfully")
        except Exception as e:
            log_with_context(logger, "error", "Failed to load cross-encoder", error=str(e))
            # Mark as failed so we don't retry
            _cross_encoder_failed = True
    
    return _cross_encoder


@dataclass
class RankedResult:
    """A search result with enhanced ranking score."""
    id: str
    text: str
    score: float
    original_rank: int
    reranked_rank: int
    cross_encoder_score: Optional[float]
    recency_score: float
    domain_boost: float
    final_score: float
    metadata: Dict[str, Any]


def calculate_recency_score(
    timestamp: Optional[datetime],
    half_life_days: int = RECENCY_HALF_LIFE_DAYS
) -> float:
    """
    Calculate recency score using exponential decay.
    
    Formula: score = exp(-ln(2) * days_old / half_life)
    
    Args:
        timestamp: Document creation/update timestamp
        half_life_days: Days for score to decay to 50%
    
    Returns:
        Score between 0.0 and 1.0
    """
    if timestamp is None:
        return 0.5  # Default for unknown timestamps
    
    now = datetime.utcnow()
    
    # Normalize timestamp (remove timezone if present)
    if hasattr(timestamp, 'tzinfo') and timestamp.tzinfo is not None:
        timestamp = timestamp.replace(tzinfo=None)
    
    days_old = (now - timestamp).total_seconds() / 86400
    
    if days_old < 0:
        return 1.0  # Future dates = max score
    
    # Exponential decay
    decay_rate = math.log(2) / half_life_days
    score = math.exp(-decay_rate * days_old)
    
    return max(0.0, min(1.0, score))


def calculate_domain_boost(
    result_namespace: Optional[str],
    query_domain: Optional[str],
    boost_factor: float = DOMAIN_BOOST_FACTOR
) -> float:
    """
    Calculate domain boost factor.
    
    Args:
        result_namespace: Namespace/domain of the result
        query_domain: Expected domain from query
        boost_factor: Multiplier for same-domain results
    
    Returns:
        boost_factor if domains match, else 1.0
    """
    if not query_domain or not result_namespace:
        return 1.0
    
    if result_namespace == query_domain:
        return boost_factor
    
    return 1.0


def cross_encoder_rerank(
    query: str,
    results: List[Dict[str, Any]],
    top_k: int = CROSS_ENCODER_RERANK_TOP_K
) -> List[Dict[str, Any]]:
    """
    Re-rank top-K results using cross-encoder model.
    
    Two-stage ranking:
    1. Dense retrieval (already done) - fast, gets top candidates
    2. Cross-encoder scoring (this function) - slower but more accurate
    
    Args:
        query: Search query
        results: List of search results with 'text' field
        top_k: Number of results to rerank
    
    Returns:
        Results with cross_encoder_score added, sorted by new score
    """
    if not CROSS_ENCODER_ENABLED or not results:
        log_with_context(logger, "debug", "Cross-encoder disabled or no results")
        return results
    
    model = _get_cross_encoder()
    if model is None:
        log_with_context(logger, "warning", "Cross-encoder not available")
        return results
    
    try:
        # Only rerank top-K results (performance optimization)
        rerank_candidates = results[:top_k]
        pass_through = results[top_k:]
        
        # Prepare query-document pairs
        pairs = []
        for result in rerank_candidates:
            text = result.get("text", "")
            if isinstance(text, str) and text:
                pairs.append([query, text[:512]])  # Truncate to model's max length
            else:
                pairs.append([query, ""])
        
        if not pairs:
            return results
        
        # Score all pairs in batch (faster than one-by-one)
        scores = model.predict(pairs, show_progress_bar=False)
        
        # Normalize cross-encoder scores using sigmoid
        # MS MARCO model outputs unbounded scores, normalize to 0-1 range
        def sigmoid(x):
            """Convert unbounded score to 0-1 probability"""
            return 1 / (1 + math.exp(-x))
        
        normalized_scores = [sigmoid(float(score)) for score in scores]
        
        # Add normalized cross-encoder scores to results
        for i, norm_score in enumerate(normalized_scores):
            rerank_candidates[i]["cross_encoder_score"] = norm_score
        
        # Blend cross-encoder score with original fusion score
        # Final = 60% original (reliable baseline) + 40% cross-encoder (semantic relevance)
        for result in rerank_candidates:
            original_score = result.get("score", 0.5)
            ce_score = result.get("cross_encoder_score", 0.5)
            # Weighted blend: prioritize original fusion score stability + add CE bonus
            blended_score = (original_score * (1.0 - CROSS_ENCODER_WEIGHT)) + (ce_score * CROSS_ENCODER_WEIGHT)
            result["score"] = blended_score
        
        # Sort by blended score (descending)
        rerank_candidates.sort(key=lambda x: x.get("score", 0.0), reverse=True)
        
        # Combine reranked + pass-through
        final_results = rerank_candidates + pass_through
        
        log_with_context(
            logger, "debug", "Cross-encoder reranking complete",
            reranked_count=len(rerank_candidates),
            total_results=len(results)
        )
        
        return final_results
        
    except Exception as e:
        log_with_context(logger, "error", "Cross-encoder reranking failed", error=str(e))
        return results


def apply_temporal_decay(
    results: List[Dict[str, Any]],
    recency_weight: float = RECENCY_WEIGHT
) -> List[Dict[str, Any]]:
    """
    Apply temporal decay to ranking scores.
    
    Boosts recent documents while preserving relevance order.
    
    Args:
        results: List of search results with metadata
        recency_weight: Weight of recency in final score (0.0-1.0)
    
    Returns:
        Results with recency_score added and scores adjusted
    """
    if not results or recency_weight <= 0:
        return results
    
    try:
        for result in results:
            metadata = result.get("metadata", {})
            
            # Try multiple timestamp fields (different doc types use different names)
            timestamp = None
            for field in ["updated_at", "last_seen_at", "created_at", "timestamp"]:
                ts = metadata.get(field)
                if ts:
                    if isinstance(ts, str):
                        try:
                            timestamp = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                        except ValueError as e:
                            logger.debug(f"Failed to parse ISO timestamp '{ts}': {e}")
                            pass
                    elif isinstance(ts, datetime):
                        timestamp = ts
                    
                    if timestamp:
                        break
            
            # Calculate recency score
            recency_score = calculate_recency_score(timestamp)
            result["recency_score"] = recency_score
            
            # Adjust original score with recency
            original_score = result.get("score", 0.0) or 0.0
            
            # Combine: (1 - recency_weight) * original + recency_weight * recency
            adjusted_score = (
                (1.0 - recency_weight) * original_score +
                recency_weight * recency_score
            )
            
            result["original_score"] = original_score
            result["score"] = adjusted_score
        
        # Re-sort by adjusted score
        results.sort(key=lambda x: x.get("score", 0.0), reverse=True)
        
        log_with_context(
            logger, "debug", "Temporal decay applied",
            results_count=len(results),
            recency_weight=recency_weight
        )
        
        return results
        
    except Exception as e:
        log_with_context(logger, "error", "Temporal decay failed", error=str(e))
        return results


def apply_domain_weighting(
    results: List[Dict[str, Any]],
    query_domain: Optional[str] = None,
    boost_factor: float = DOMAIN_BOOST_FACTOR
) -> List[Dict[str, Any]]:
    """
    Apply domain boost to same-domain results.
    
    Args:
        results: List of search results
        query_domain: Expected domain/namespace from query
        boost_factor: Multiplier for same-domain results
    
    Returns:
        Results with domain boost applied
    """
    if not results or not query_domain or boost_factor <= 1.0:
        return results
    
    try:
        for result in results:
            metadata = result.get("metadata", {})
            result_namespace = metadata.get("namespace", "")
            
            domain_boost = calculate_domain_boost(result_namespace, query_domain, boost_factor)
            result["domain_boost"] = domain_boost
            
            # Apply boost to score
            if domain_boost > 1.0:
                original_score = result.get("score", 0.0) or 0.0
                result["score"] = original_score * domain_boost
        
        # Re-sort by boosted score
        results.sort(key=lambda x: x.get("score", 0.0), reverse=True)
        
        log_with_context(
            logger, "debug", "Domain weighting applied",
            query_domain=query_domain,
            boost_factor=boost_factor
        )
        
        return results
        
    except Exception as e:
        log_with_context(logger, "error", "Domain weighting failed", error=str(e))
        return results


def enhance_ranking(
    query: str,
    results: List[Dict[str, Any]],
    query_domain: Optional[str] = None,
    enable_cross_encoder: bool = True,
    enable_temporal_decay: bool = True,
    enable_domain_weighting: bool = True
) -> List[Dict[str, Any]]:
    """
    Apply all ranking enhancements in sequence.
    
    Pipeline:
    1. Cross-encoder re-ranking (top-K results)
    2. Temporal decay scoring (boost recent docs)
    3. Domain weighting (boost same-domain docs)
    
    Args:
        query: Search query
        results: List of search results
        query_domain: Expected domain/namespace
        enable_cross_encoder: Apply cross-encoder reranking
        enable_temporal_decay: Apply temporal decay
        enable_domain_weighting: Apply domain boost
    
    Returns:
        Enhanced and re-ranked results
    """
    if not results:
        return results
    
    log_with_context(
        logger, "info", "Phase B Stream 2.3: Advanced ranking enhancements starting",
        results_count=len(results),
        cross_encoder=enable_cross_encoder,
        temporal_decay=enable_temporal_decay,
        domain_weighting=enable_domain_weighting
    )
    
    # Stage 1: Cross-encoder reranking (highest impact, ~+5% quality)
    if enable_cross_encoder and CROSS_ENCODER_ENABLED:
        results = cross_encoder_rerank(query, results)
    
    # Stage 2: Temporal decay (~+2% quality)
    if enable_temporal_decay:
        results = apply_temporal_decay(results)
    
    # Stage 3: Domain weighting (~+1% quality)
    if enable_domain_weighting and query_domain:
        results = apply_domain_weighting(results, query_domain)
    
    log_with_context(
        logger, "debug", "Ranking enhancement complete",
        final_results_count=len(results)
    )
    
    return results
