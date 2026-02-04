"""
Feedback & Feedback Loop Endpoints.

Core features:
- User feedback collection (ratings, tags, text)
- Decision outcome tracking
- Intervention feedback & effectiveness
- Cognitive load monitoring
- Targeted feedback delivery
- Self-programming feedback loop dashboard

Extracted from main.py for better maintainability.
"""

from fastapi import APIRouter, Request
from typing import Optional, Dict, Any
import logging

from ..errors import JarvisException, ErrorCode
from ..observability import get_logger, log_with_context
from ..tracing import get_current_user_id
from ..feedback_service import (
    submit_feedback,
    get_feedback_summary,
    get_recent_feedback,
    record_decision,
    update_decision_outcome,
    get_decision_history,
    get_outcome_statistics,
    log_improvement,
)

logger = get_logger("jarvis.routers.feedback")

router = APIRouter(
    prefix="",  # No prefix - endpoints have /feedback and /feedback-loop prefixes
    tags=["feedback"],
    responses={
        400: {"description": "Invalid request"},
        500: {"description": "Internal server error"},
    }
)


# ============================================================================
# BASIC FEEDBACK ENDPOINTS
# ============================================================================

@router.post("/feedback/submit")
async def submit_feedback_endpoint(req: Dict[str, Any], request: Request = None):
    """
    Submit user feedback.

    Phase 16.4A: Feedback collection for learning.
    Accepts: rating, thumbs_up, feedback_text, session_id, context, tags
    """
    request_id = getattr(request.state, 'request_id', 'unknown') if request else 'unknown'

    try:
        feedback_id = await submit_feedback(
            user_id=req.get("user_id", get_current_user_id()),
            feedback_type=req.get("feedback_type", "general"),
            rating=req.get("rating"),
            thumbs_up=req.get("thumbs_up"),
            feedback_text=req.get("feedback_text"),
            feedback_tags=req.get("feedback_tags"),
            session_id=req.get("session_id"),
            context_type=req.get("context_type"),
            original_query=req.get("original_query"),
            original_response=req.get("original_response")
        )

        if feedback_id:
            return {
                "status": "success",
                "feedback_id": feedback_id,
                "request_id": request_id
            }
        else:
            raise JarvisException(
                code=ErrorCode.PROCESSING_FAILED,
                message="Failed to submit feedback",
                status_code=500,
                recoverable=False
            )

    except JarvisException:
        raise
    except Exception as e:
        logger.exception("Submit feedback failed")
        raise JarvisException(
            code=ErrorCode.INTERNAL_ERROR,
            message="Feedback submission failed",
            status_code=500,
            recoverable=False
        )


@router.post("/feedback/quick")
async def submit_quick_feedback_endpoint(req: Dict[str, Any], request: Request = None):
    """
    Submit quick thumbs up/down feedback.

    Phase 16.4A: Simple feedback submission (minimal form).
    """
    request_id = getattr(request.state, 'request_id', 'unknown') if request else 'unknown'

    try:
        feedback_id = await submit_feedback(
            user_id=req.get("user_id", get_current_user_id()),
            feedback_type="quick",
            thumbs_up=req.get("thumbs_up"),
            session_id=req.get("session_id"),
            original_query=req.get("original_query"),
            original_response=req.get("original_response")
        )

        if feedback_id:
            return {
                "status": "success",
                "feedback_id": feedback_id,
                "request_id": request_id
            }
        else:
            raise JarvisException(
                code=ErrorCode.PROCESSING_FAILED,
                message="Failed to submit quick feedback",
                status_code=500,
                recoverable=False
            )

    except JarvisException:
        raise
    except Exception as e:
        logger.exception("Submit quick feedback failed")
        raise JarvisException(
            code=ErrorCode.INTERNAL_ERROR,
            message="Quick feedback submission failed",
            status_code=500,
            recoverable=False
        )


# ============================================================================
# FEEDBACK ANALYTICS ENDPOINTS
# ============================================================================

@router.get("/feedback/summary")
async def feedback_summary_endpoint(
    user_id: Optional[str] = None,
    days: int = 30,
    request: Request = None
):
    """
    Get feedback summary for user.

    Phase 16.4B: Analytics on feedback trends
    Returns: rating distribution, common themes, improvement areas
    """
    request_id = getattr(request.state, 'request_id', 'unknown') if request else 'unknown'

    try:
        result = await get_feedback_summary(user_id=user_id or get_current_user_id(), days=days)
        result["request_id"] = request_id
        return result

    except JarvisException:
        raise
    except Exception as e:
        logger.exception("Get feedback summary failed")
        raise JarvisException(
            code=ErrorCode.INTERNAL_ERROR,
            message="Failed to retrieve feedback summary",
            status_code=500,
            recoverable=True,
            retry_after=5
        )


@router.get("/feedback/recent")
async def recent_feedback_endpoint(
    user_id: Optional[str] = None,
    limit: int = 20,
    request: Request = None
):
    """
    Get recent feedback entries for user.

    Phase 16.4B: Historical feedback data
    """
    request_id = getattr(request.state, 'request_id', 'unknown') if request else 'unknown'

    try:
        result = await get_recent_feedback(user_id=user_id or get_current_user_id(), limit=limit)
        result["request_id"] = request_id
        return result

    except JarvisException:
        raise
    except Exception as e:
        logger.exception("Get recent feedback failed")
        raise JarvisException(
            code=ErrorCode.INTERNAL_ERROR,
            message="Failed to retrieve recent feedback",
            status_code=500,
            recoverable=True,
            retry_after=5
        )


@router.get("/feedback/improvements")
async def improvement_recommendations_endpoint(
    user_id: Optional[str] = None,
    limit: int = 10,
    request: Request = None
):
    """
    Get improvement recommendations based on feedback.

    Phase 16.4B: Suggested improvements from feedback patterns
    """
    request_id = getattr(request.state, 'request_id', 'unknown') if request else 'unknown'

    try:
        improvements = await log_improvement(user_id=user_id or get_current_user_id(), limit=limit)

        return {
            "improvements": improvements,
            "count": len(improvements),
            "request_id": request_id
        }

    except JarvisException:
        raise
    except Exception as e:
        logger.exception("Get improvements failed")
        raise JarvisException(
            code=ErrorCode.INTERNAL_ERROR,
            message="Failed to retrieve improvement recommendations",
            status_code=500,
            recoverable=True,
            retry_after=5
        )


# ============================================================================
# DECISION TRACKING ENDPOINTS
# ============================================================================

@router.post("/feedback/decision")
async def record_decision_endpoint(req: Dict[str, Any], request: Request = None):
    """
    Record a decision made by Jarvis.

    Phase 16.4C: Track decisions for future analysis
    """
    request_id = getattr(request.state, 'request_id', 'unknown') if request else 'unknown'

    try:
        decision_id = await record_decision(
            user_id=req.get("user_id", get_current_user_id()),
            decision_type=req.get("decision_type"),
            content=req.get("content"),
            context=req.get("context"),
            confidence=req.get("confidence")
        )

        return {
            "status": "recorded",
            "decision_id": decision_id,
            "request_id": request_id
        }

    except JarvisException:
        raise
    except Exception as e:
        logger.exception("Record decision failed")
        raise JarvisException(
            code=ErrorCode.PROCESSING_FAILED,
            message="Failed to record decision",
            status_code=500,
            recoverable=False
        )


@router.put("/feedback/decision/{decision_id}/outcome")
async def update_decision_outcome_endpoint(
    decision_id: str,
    req: Dict[str, Any],
    request: Request = None
):
    """
    Record outcome of a decision.

    Phase 16.4C: Did the decision work well?
    """
    request_id = getattr(request.state, 'request_id', 'unknown') if request else 'unknown'

    try:
        result = await update_decision_outcome(
            decision_id=decision_id,
            outcome=req.get("outcome"),
            feedback_text=req.get("feedback_text"),
            tags=req.get("tags", [])
        )

        return {
            "status": "updated" if result else "error",
            "decision_id": decision_id,
            "request_id": request_id
        }

    except JarvisException:
        raise
    except Exception as e:
        logger.exception("Update decision outcome failed")
        raise JarvisException(
            code=ErrorCode.PROCESSING_FAILED,
            message="Failed to update decision outcome",
            status_code=500,
            recoverable=False
        )


@router.get("/feedback/decisions")
async def get_decisions_endpoint(
    user_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    request: Request = None
):
    """
    Get decision history.

    Phase 16.4C: Review past decisions and outcomes
    """
    request_id = getattr(request.state, 'request_id', 'unknown') if request else 'unknown'

    try:
        decisions = await get_decision_history(
            user_id=user_id or get_current_user_id(),
            status=status,
            limit=limit
        )

        return {
            "decisions": decisions,
            "count": len(decisions),
            "request_id": request_id
        }

    except JarvisException:
        raise
    except Exception as e:
        logger.exception("Get decisions failed")
        raise JarvisException(
            code=ErrorCode.INTERNAL_ERROR,
            message="Failed to retrieve decisions",
            status_code=500,
            recoverable=True,
            retry_after=5
        )


# ============================================================================
# DECISION OUTCOMES ENDPOINTS
# ============================================================================

@router.get("/feedback/outcomes/stats")
async def outcome_statistics_endpoint(
    user_id: Optional[str] = None,
    days: int = 30,
    request: Request = None
):
    """
    Get outcome statistics.

    Phase 16.4D: Analysis of decision effectiveness
    Returns: success rate, common issues, trends
    """
    request_id = getattr(request.state, 'request_id', 'unknown') if request else 'unknown'

    try:
        stats = await get_outcome_statistics(user_id=user_id or get_current_user_id(), days=days)
        stats["request_id"] = request_id
        return stats

    except JarvisException:
        raise
    except Exception as e:
        logger.exception("Get outcome statistics failed")
        raise JarvisException(
            code=ErrorCode.INTERNAL_ERROR,
            message="Failed to retrieve outcome statistics",
            status_code=500,
            recoverable=True,
            retry_after=5
        )


__all__ = ["router"]
