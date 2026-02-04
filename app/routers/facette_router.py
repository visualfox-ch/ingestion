"""Facette Detection API Endpoints (T-005)

Exposes facette detection for external use and emits Prometheus metrics.

Endpoints:
- POST /facette/detect - Detect facettes for a query
- GET /facette/weights - Get current default weights from hot config
- GET /facette/stats/{user_id} - Get user's facette usage stats

Author: Claude Code
Created: 2026-02-03
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Dict, Optional

from ..observability import get_logger
from ..auth import auth_dependency
from ..facette_detector import get_facette_detector
from .. import metrics
from .. import hot_config

logger = get_logger("jarvis.facette_router")
router = APIRouter(prefix="/facette", tags=["Facette"])


# =============================================================================
# PYDANTIC MODELS
# =============================================================================

class FacetteDetectRequest(BaseModel):
    """Request model for facette detection."""
    query: str = Field(..., min_length=1, max_length=2000, description="Query text to analyze")
    context: Optional[str] = Field(None, max_length=1000, description="Optional context for better detection")


class FacetteDetectResponse(BaseModel):
    """Response model for facette detection."""
    weights: Dict[str, float] = Field(..., description="Facette weights (sum to 1.0)")
    dominant: str = Field(..., description="Dominant facette name")
    domain: str = Field(..., description="Detected domain context")


class FacetteWeightsResponse(BaseModel):
    """Response model for default facette weights."""
    weights: Dict[str, float] = Field(..., description="Default facette weights from hot config")
    description: str = Field(..., description="Description of the weights")


class FacetteStatsResponse(BaseModel):
    """Response model for user facette stats."""
    user_id: str
    total_sessions: int = 0
    facette_counts: Dict[str, int] = Field(default_factory=dict)
    latest_weights: Optional[Dict[str, float]] = None


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.post("/detect", response_model=FacetteDetectResponse)
def detect_facettes(
    request: FacetteDetectRequest,
    auth: bool = Depends(auth_dependency)
):
    """
    Detect facette weights for a query.

    Analyzes the query text to determine which personality facettes
    should be activated (Analytical, Empathic, Pragmatic, Creative).

    Also emits Prometheus metrics for facette usage tracking.
    """
    try:
        detector = get_facette_detector()
        result = detector.detect(request.query, request.context)
        domain = detector.detect_domain(request.query)

        # Emit Prometheus metrics
        metrics.record_facette_usage(result.to_dict(), domain)

        logger.info(f"Facette detection: dominant={result.dominant_facette()}, domain={domain}")

        return FacetteDetectResponse(
            weights=result.to_dict(),
            dominant=result.dominant_facette(),
            domain=domain
        )
    except Exception as e:
        logger.error(f"Facette detection failed: {e}")
        raise HTTPException(status_code=500, detail=f"Facette detection failed: {str(e)}")


@router.get("/weights", response_model=FacetteWeightsResponse)
def get_default_weights(auth: bool = Depends(auth_dependency)):
    """
    Get current default facette weights from hot config.

    These are the baseline weights used when no specific detection
    patterns are found in the query.
    """
    return FacetteWeightsResponse(
        weights=hot_config.get_facette_weights(),
        description="Personality facette blend weights (sum should be ~1.0)"
    )


@router.get("/stats/{user_id}", response_model=FacetteStatsResponse)
def get_user_facette_stats(
    user_id: str,
    auth: bool = Depends(auth_dependency)
):
    """
    Get cumulative facette usage stats for a user.

    Shows which facettes have been dominant across sessions,
    enabling personality evolution tracking.
    """
    try:
        from .. import config as cfg
        from ..memory import MemoryStore
        import redis

        redis_client = redis.Redis(host=cfg.REDIS_HOST, port=cfg.REDIS_PORT, db=0)
        store = MemoryStore(redis_client)
        stats = store.get_facette_stats(user_id)

        return FacetteStatsResponse(
            user_id=user_id,
            total_sessions=stats.get("total_sessions", 0),
            facette_counts=stats.get("facette_counts", {}),
            latest_weights=stats.get("latest_weights")
        )
    except Exception as e:
        logger.error(f"Failed to get facette stats for {user_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get facette stats: {str(e)}")
