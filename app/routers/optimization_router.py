"""
Optimization and Coaching Router

Extracted from main.py - Phase 16.2 endpoints for metrics-driven optimization.
"""

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Dict, Any, List
from datetime import datetime

router = APIRouter(tags=["optimization"])


class RecommendationResponse(BaseModel):
    """API response for optimization recommendation"""
    id: str
    timestamp: str
    category: str
    severity: str
    title: str
    description: str
    metric_name: str
    current_value: float
    threshold: float
    action: str
    impact: str
    effort: str


# =============================================================================
# OPTIMIZATION RECOMMENDATIONS
# =============================================================================

@router.get("/optimize/analyze", response_model=Dict[str, Any])
async def analyze_metrics():
    """
    Analyze all metrics and return optimization recommendations.

    Returns recommendations grouped by severity level:
    - critical: Immediate action required
    - warning: Should address in short term
    - info: Good to know
    """
    from ..metrics_analyzer import get_metrics_analyzer, SeverityLevel

    analyzer = get_metrics_analyzer()
    recommendations = await analyzer.analyze_all()

    # Group by severity
    by_severity = {
        "critical": [r for r in recommendations if r.severity == SeverityLevel.CRITICAL],
        "warning": [r for r in recommendations if r.severity == SeverityLevel.WARNING],
        "info": [r for r in recommendations if r.severity == SeverityLevel.INFO]
    }

    return {
        "timestamp": datetime.utcnow().isoformat(),
        "total_recommendations": len(recommendations),
        "by_severity": {
            level: [
                {
                    "id": r.id,
                    "timestamp": r.timestamp,
                    "category": r.category.value,
                    "severity": r.severity.value,
                    "title": r.title,
                    "description": r.description,
                    "metric_name": r.metric_name,
                    "current_value": r.current_value,
                    "threshold": r.threshold,
                    "action": r.action,
                    "impact": r.impact,
                    "effort": r.effort
                }
                for r in recs
            ]
            for level, recs in by_severity.items()
        }
    }


@router.get("/optimize/latency", response_model=List[RecommendationResponse])
async def get_latency_optimization():
    """Get performance optimization recommendations for latency issues"""
    from ..metrics_analyzer import get_metrics_analyzer

    analyzer = get_metrics_analyzer()
    recommendations = await analyzer.analyze_latency()

    return [
        {
            "id": r.id,
            "timestamp": r.timestamp,
            "category": r.category.value,
            "severity": r.severity.value,
            "title": r.title,
            "description": r.description,
            "metric_name": r.metric_name,
            "current_value": r.current_value,
            "threshold": r.threshold,
            "action": r.action,
            "impact": r.impact,
            "effort": r.effort
        }
        for r in recommendations
    ]


@router.get("/optimize/reliability", response_model=List[RecommendationResponse])
async def get_reliability_optimization():
    """Get reliability optimization recommendations for error rates"""
    from ..metrics_analyzer import get_metrics_analyzer

    analyzer = get_metrics_analyzer()
    recommendations = await analyzer.analyze_reliability()

    return [
        {
            "id": r.id,
            "timestamp": r.timestamp,
            "category": r.category.value,
            "severity": r.severity.value,
            "title": r.title,
            "description": r.description,
            "metric_name": r.metric_name,
            "current_value": r.current_value,
            "threshold": r.threshold,
            "action": r.action,
            "impact": r.impact,
            "effort": r.effort
        }
        for r in recommendations
    ]


@router.get("/optimize/resources", response_model=List[RecommendationResponse])
async def get_resource_optimization():
    """Get resource optimization recommendations for memory/CPU issues"""
    from ..metrics_analyzer import get_metrics_analyzer

    analyzer = get_metrics_analyzer()
    recommendations = await analyzer.analyze_resources()

    return [
        {
            "id": r.id,
            "timestamp": r.timestamp,
            "category": r.category.value,
            "severity": r.severity.value,
            "title": r.title,
            "description": r.description,
            "metric_name": r.metric_name,
            "current_value": r.current_value,
            "threshold": r.threshold,
            "action": r.action,
            "impact": r.impact,
            "effort": r.effort
        }
        for r in recommendations
    ]


@router.get("/optimize/quality", response_model=List[RecommendationResponse])
async def get_quality_optimization():
    """Get quality optimization recommendations for preference learning"""
    from ..metrics_analyzer import get_metrics_analyzer

    analyzer = get_metrics_analyzer()
    recommendations = await analyzer.analyze_quality()

    return [
        {
            "id": r.id,
            "timestamp": r.timestamp,
            "category": r.category.value,
            "severity": r.severity.value,
            "title": r.title,
            "description": r.description,
            "metric_name": r.metric_name,
            "current_value": r.current_value,
            "threshold": r.threshold,
            "action": r.action,
            "impact": r.impact,
            "effort": r.effort
        }
        for r in recommendations
    ]


# =============================================================================
# OPTIMIZATION COACHING
# =============================================================================

@router.get("/coach/optimize", response_model=Dict[str, Any])
async def get_optimization_coaching():
    """
    Get comprehensive optimization coaching for the system.

    Provides structured coaching on:
    - Critical issues requiring immediate attention
    - Warnings to address in near term
    - Informational suggestions for long-term improvement
    """
    from ..optimization_coach import get_optimization_coach

    coach = get_optimization_coach()
    return await coach.get_optimization_guidance()


@router.get("/coach/performance", response_model=Dict[str, Any])
async def get_performance_coaching():
    """Get coaching specific to API performance and latency"""
    from ..optimization_coach import get_optimization_coach

    coach = get_optimization_coach()
    return await coach.get_performance_coaching()


@router.get("/coach/reliability", response_model=Dict[str, Any])
async def get_reliability_coaching():
    """Get coaching specific to system reliability and error rates"""
    from ..optimization_coach import get_optimization_coach

    coach = get_optimization_coach()
    return await coach.get_reliability_coaching()


@router.get("/coach/resources", response_model=Dict[str, Any])
async def get_resource_coaching():
    """Get coaching specific to memory and resource optimization"""
    from ..optimization_coach import get_optimization_coach

    coach = get_optimization_coach()
    return await coach.get_resource_coaching()


@router.get("/coach/learning", response_model=Dict[str, Any])
async def get_learning_coaching():
    """Get coaching specific to preference learning and model quality"""
    from ..optimization_coach import get_optimization_coach

    coach = get_optimization_coach()
    return await coach.get_learning_coaching()
