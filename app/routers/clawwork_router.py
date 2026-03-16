"""
ClawWork Integration Router

API endpoints for ClawWork-inspired features:
- Economic Accountability
- Strategic Learning (Work vs Learn)
- Quality Scoring
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/clawwork", tags=["clawwork"])


# =============================================================================
# Request/Response Models
# =============================================================================

# Economic Models
class EconomicSnapshotResponse(BaseModel):
    """Economic snapshot."""
    timestamp: str
    total_value_created: float
    total_costs_incurred: float
    net_value: float
    roi_percent: float
    sustainability_score: float
    sustainable: bool
    top_value_features: List[dict]
    top_cost_features: List[dict]


class ValueEventRequest(BaseModel):
    """Record value event."""
    value_type: str = Field(..., description="Type: task_completion, time_saved, knowledge_created, etc.")
    feature: str = Field(..., description="Feature that created value")
    user_id: str = Field(default="system")
    description: str = Field(..., description="Description of value created")
    amount_usd: Optional[float] = Field(None, description="Explicit USD value (auto-calculated if None)")
    complexity: str = Field("medium", description="simple/medium/complex/critical")
    confidence: float = Field(0.8, ge=0, le=1)


class FeatureROIResponse(BaseModel):
    """Feature ROI."""
    feature: str
    days: int
    total_value: float
    total_cost: float
    net_value: float
    roi_percent: float
    profitable: bool


# Learning Models
class LearningInvestmentRequest(BaseModel):
    """Learning investment request."""
    domain: str = Field(..., description="Domain: coding, system_admin, data_analysis, etc.")
    topic: str = Field(..., description="Specific topic")
    knowledge_gained: str = Field(..., description="What was learned")
    cost_usd: float = Field(0.0, ge=0)
    time_seconds: int = Field(0, ge=0)
    source: str = Field("interaction")
    confidence: float = Field(0.7, ge=0, le=1)


class SkillResponse(BaseModel):
    """Skill info."""
    domain: str
    name: str
    proficiency: float
    investments: int
    applications: int


class LearningROIResponse(BaseModel):
    """Learning ROI."""
    days: int
    total_learning_cost: float
    value_from_knowledge: float
    skills_improved: int
    average_proficiency: float
    learning_roi_percent: float


# Quality Models
class QualityScoreRequest(BaseModel):
    """Quality score request."""
    task_id: str
    task_type: str = Field("question_answer", description="Type: question_answer, code_generation, analysis, etc.")
    query: str
    response: str
    use_llm: bool = Field(False, description="Use LLM for detailed evaluation")


class QualityScoreResponse(BaseModel):
    """Quality score."""
    task_id: str
    task_type: str
    overall_score: float
    dimension_scores: dict
    strengths: List[str]
    improvements: List[str]
    feedback: str
    evaluator: str


class QualitySummaryResponse(BaseModel):
    """Quality summary."""
    days: int
    total_evaluations: int
    by_task_type: List[dict]
    dimension_averages: dict


# =============================================================================
# Economic Endpoints
# =============================================================================

@router.get("/economic/snapshot", response_model=EconomicSnapshotResponse)
async def get_economic_snapshot(
    days: int = Query(30, ge=1, le=365, description="Lookback days")
):
    """Get economic snapshot showing value vs costs."""
    try:
        from ..services.economic_engine import get_economic_engine

        engine = get_economic_engine()
        start_date = datetime.utcnow() - timedelta(days=days)
        snapshot = engine.get_snapshot(start_date=start_date)

        return EconomicSnapshotResponse(
            timestamp=snapshot.timestamp.isoformat(),
            total_value_created=snapshot.total_value_created,
            total_costs_incurred=snapshot.total_costs_incurred,
            net_value=snapshot.net_value,
            roi_percent=snapshot.roi_percent,
            sustainability_score=snapshot.sustainability_score,
            sustainable=snapshot.sustainability_score > 0.5,
            top_value_features=snapshot.top_value_features,
            top_cost_features=snapshot.top_cost_features,
        )

    except Exception as e:
        logger.error(f"Failed to get economic snapshot: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/economic/value")
async def record_value_event(request: ValueEventRequest):
    """Record a value creation event."""
    try:
        from ..services.economic_engine import get_economic_engine, ValueType

        engine = get_economic_engine()

        try:
            value_type = ValueType(request.value_type)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid value_type. Use: {[v.value for v in ValueType]}"
            )

        event = engine.record_value(
            value_type=value_type,
            feature=request.feature,
            user_id=request.user_id,
            description=request.description,
            amount_usd=request.amount_usd,
            complexity=request.complexity,
            confidence=request.confidence,
        )

        return {
            "status": "recorded",
            "value_usd": event.amount_usd,
            "value_type": event.value_type.value,
            "feature": event.feature,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to record value: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/economic/feature/{feature}", response_model=FeatureROIResponse)
async def get_feature_roi(
    feature: str,
    days: int = Query(30, ge=1, le=365)
):
    """Get ROI for a specific feature."""
    try:
        from ..services.economic_engine import get_economic_engine

        engine = get_economic_engine()
        roi = engine.get_feature_roi(feature, days=days)

        return FeatureROIResponse(**roi)

    except Exception as e:
        logger.error(f"Failed to get feature ROI: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/economic/trend")
async def get_economic_trend(
    days: int = Query(14, ge=1, le=90)
):
    """Get daily value/cost trend."""
    try:
        from ..services.economic_engine import get_economic_engine

        engine = get_economic_engine()
        trend = engine.get_daily_trend(days=days)

        return {"days": days, "trend": trend}

    except Exception as e:
        logger.error(f"Failed to get trend: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/economic/sustainable")
async def check_sustainability(
    days: int = Query(7, ge=1, le=30)
):
    """Check if Jarvis is economically sustainable."""
    try:
        from ..services.economic_engine import get_economic_engine

        engine = get_economic_engine()
        is_sustainable = engine.is_sustainable(days=days)
        snapshot = engine.get_snapshot(
            start_date=datetime.utcnow() - timedelta(days=days)
        )

        return {
            "sustainable": is_sustainable,
            "sustainability_score": snapshot.sustainability_score,
            "net_value": snapshot.net_value,
            "recommendation": (
                "Continue current operations" if is_sustainable
                else "Focus on high-value tasks to improve sustainability"
            ),
        }

    except Exception as e:
        logger.error(f"Sustainability check failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Learning Endpoints
# =============================================================================

@router.post("/learning/invest")
async def invest_in_learning(request: LearningInvestmentRequest):
    """Record a learning investment."""
    try:
        from ..services.strategic_learner import get_strategic_learner, LearningDomain

        learner = get_strategic_learner()

        try:
            domain = LearningDomain(request.domain)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid domain. Use: {[d.value for d in LearningDomain]}"
            )

        investment = learner.invest_in_learning(
            domain=domain,
            topic=request.topic,
            knowledge_gained=request.knowledge_gained,
            cost_usd=request.cost_usd,
            time_seconds=request.time_seconds,
            source=request.source,
            confidence=request.confidence,
        )

        return {
            "status": "invested",
            "domain": investment.domain.value,
            "topic": investment.topic,
            "cost_usd": investment.cost_usd,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to record learning: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/learning/skills", response_model=List[SkillResponse])
async def get_skills():
    """Get all skills and proficiency levels."""
    try:
        from ..services.strategic_learner import get_strategic_learner

        learner = get_strategic_learner()
        skills = learner.get_skills_summary()

        return [SkillResponse(**s) for s in skills]

    except Exception as e:
        logger.error(f"Failed to get skills: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/learning/roi", response_model=LearningROIResponse)
async def get_learning_roi(
    days: int = Query(30, ge=1, le=365)
):
    """Get ROI of learning investments."""
    try:
        from ..services.strategic_learner import get_strategic_learner

        learner = get_strategic_learner()
        roi = learner.get_learning_roi(days=days)

        return LearningROIResponse(**roi)

    except Exception as e:
        logger.error(f"Failed to get learning ROI: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/learning/knowledge")
async def recall_knowledge(
    domain: Optional[str] = None,
    topic: Optional[str] = None,
    limit: int = Query(10, ge=1, le=50)
):
    """Recall stored knowledge."""
    try:
        from ..services.strategic_learner import get_strategic_learner, LearningDomain

        learner = get_strategic_learner()

        domain_enum = None
        if domain:
            try:
                domain_enum = LearningDomain(domain)
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid domain. Use: {[d.value for d in LearningDomain]}"
                )

        knowledge = learner.recall_knowledge(
            domain=domain_enum,
            topic=topic,
            limit=limit,
        )

        return {"count": len(knowledge), "knowledge": knowledge}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to recall knowledge: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/learning/decide")
async def should_learn_or_work(
    task_value: float = Query(..., description="Expected value of immediate work"),
    task_complexity: str = Query("medium", description="simple/medium/complex"),
    available_time: int = Query(300, description="Available time in seconds")
):
    """Get strategic recommendation: work or learn."""
    try:
        from ..services.strategic_learner import get_strategic_learner
        from ..services.economic_engine import get_economic_engine

        learner = get_strategic_learner()
        engine = get_economic_engine()

        # Get current economic state
        snapshot = engine.get_snapshot(
            start_date=datetime.utcnow() - timedelta(days=7)
        )
        economic_state = {
            "sustainability_score": snapshot.sustainability_score,
            "net_value": snapshot.net_value,
            "roi_percent": snapshot.roi_percent,
        }

        decision, reasoning = learner.should_learn_or_work(
            task_value=task_value,
            task_complexity=task_complexity,
            available_time_seconds=available_time,
            economic_state=economic_state,
        )

        return {
            "recommendation": decision.value,
            "reasoning": reasoning,
            "economic_state": economic_state,
        }

    except Exception as e:
        logger.error(f"Decision failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Quality Endpoints
# =============================================================================

@router.post("/quality/score", response_model=QualityScoreResponse)
async def score_quality(request: QualityScoreRequest):
    """Score the quality of a response."""
    try:
        from ..services.quality_scorer import get_quality_scorer, TaskType

        scorer = get_quality_scorer()

        try:
            task_type = TaskType(request.task_type)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid task_type. Use: {[t.value for t in TaskType]}"
            )

        score = scorer.score_output(
            task_id=request.task_id,
            task_type=task_type,
            query=request.query,
            response=request.response,
            use_llm=request.use_llm,
        )

        return QualityScoreResponse(
            task_id=score.task_id,
            task_type=score.task_type.value,
            overall_score=score.overall_score,
            dimension_scores={k.value: v for k, v in score.dimension_scores.items()},
            strengths=score.strengths,
            improvements=score.improvements,
            feedback=score.feedback,
            evaluator=score.evaluator,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Quality scoring failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/quality/summary", response_model=QualitySummaryResponse)
async def get_quality_summary(
    days: int = Query(30, ge=1, le=365),
    task_type: Optional[str] = None
):
    """Get quality summary."""
    try:
        from ..services.quality_scorer import get_quality_scorer, TaskType

        scorer = get_quality_scorer()

        task_type_enum = None
        if task_type:
            try:
                task_type_enum = TaskType(task_type)
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid task_type. Use: {[t.value for t in TaskType]}"
                )

        summary = scorer.get_quality_summary(days=days, task_type=task_type_enum)

        return QualitySummaryResponse(**summary)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Quality summary failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/quality/improvements")
async def get_improvement_suggestions():
    """Get suggestions for quality improvement."""
    try:
        from ..services.quality_scorer import get_quality_scorer

        scorer = get_quality_scorer()
        suggestions = scorer.get_improvement_suggestions()

        return {"suggestions": suggestions}

    except Exception as e:
        logger.error(f"Improvement suggestions failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/quality/feedback")
async def record_user_feedback(
    task_id: str,
    score: float = Query(..., ge=0, le=1),
    feedback: str = ""
):
    """Record user feedback on a response."""
    try:
        from ..services.quality_scorer import get_quality_scorer

        scorer = get_quality_scorer()
        scorer.record_user_feedback(task_id, score, feedback)

        return {"status": "recorded", "task_id": task_id, "score": score}

    except Exception as e:
        logger.error(f"Feedback recording failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Dashboard Endpoint
# =============================================================================

@router.get("/dashboard")
async def get_clawwork_dashboard():
    """Get complete ClawWork dashboard data."""
    try:
        from ..services.economic_engine import get_economic_engine
        from ..services.strategic_learner import get_strategic_learner
        from ..services.quality_scorer import get_quality_scorer

        engine = get_economic_engine()
        learner = get_strategic_learner()
        scorer = get_quality_scorer()

        # Economic snapshot
        snapshot = engine.get_snapshot()

        # Skills
        skills = learner.get_skills_summary()

        # Quality
        quality = scorer.get_quality_summary(days=7)

        return {
            "economic": {
                "sustainable": snapshot.sustainability_score > 0.5,
                "sustainability_score": snapshot.sustainability_score,
                "net_value": snapshot.net_value,
                "roi_percent": snapshot.roi_percent,
            },
            "learning": {
                "total_skills": len(skills),
                "top_skills": skills[:5],
                "learning_roi": learner.get_learning_roi(days=30),
            },
            "quality": {
                "total_evaluations": quality["total_evaluations"],
                "dimension_averages": quality["dimension_averages"],
                "improvements_needed": scorer.get_improvement_suggestions()[:3],
            },
        }

    except Exception as e:
        logger.error(f"Dashboard failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
