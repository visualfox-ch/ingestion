"""
Cross-Session Learning API Routes
Separated from main.py to avoid loading issues with large monolithic files.
"""
from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from typing import Any, Dict, Optional
from datetime import datetime
import logging
import uuid

logger = logging.getLogger("jarvis.learning_routes")

router = APIRouter(prefix="/learning", tags=["learning"])


class AIContextEvent(BaseModel):
    """VS Code / Copilot event captured by Mac Bridge."""
    timestamp: Optional[str] = Field(None, description="ISO timestamp from client")
    ai_tool: str = Field(..., description="Source AI tool (e.g., copilot)")
    suggestion: str = Field(..., description="Suggested content or summary")
    file: str = Field(..., description="File path or name")
    action: str = Field(..., description="accepted | rejected | ignored")
    context: Dict[str, Any] = Field(default_factory=dict)


@router.post("/ai-event")
async def receive_ai_event(event: AIContextEvent):
    """Receive AI context events from the Mac Bridge and generate proactive hints."""
    event_id = str(uuid.uuid4())
    from .utils.timezone import now_zurich_iso
    received_at = now_zurich_iso()

    logger.info(
        "AI context event received",
        extra={
            "event_id": event_id,
            "ai_tool": event.ai_tool,
            "file": event.file,
            "action": event.action,
            "received_at": received_at,
        },
    )

    # Phase 3: Wire pattern detection → confidence scoring → hint generation
    insights: Dict[str, Any] = await generate_ai_hints(
        ai_tool=event.ai_tool,
        file_path=event.file,
        suggestion=event.suggestion,
        action=event.action,
        context=event.context,
        event_id=event_id,
    )

    return {
        "status": "received",
        "event_id": event_id,
        "received_at": received_at,
        "insights": insights,
    }


async def generate_ai_hints(
    ai_tool: str,
    file_path: str,
    suggestion: str,
    action: str,
    context: Dict[str, Any],
    event_id: str,
) -> Dict[str, Any]:
    """
    Generate proactive hints based on AI event patterns.
    
    Pipeline:
    1. Query recent patterns for this AI tool
    2. Score confidence based on frequency and recency
    3. Generate ranked hints
    4. Filter by confidence threshold
    """
    try:
        from .jobs.pattern_detector import detect_patterns_daily
        from .optimization import ConfidenceScorer
        
        hints = []
        
        # Step 1: Get recent patterns from pattern detection
        # For now, use daily pattern detection as a baseline
        from .tracing import get_current_user_id
        recent_patterns = detect_patterns_daily(user_id=get_current_user_id() or "unknown", days_back=7)
        
        # Filter patterns relevant to this AI tool
        relevant_patterns = [
            p for p in recent_patterns
            if ai_tool.lower() in p.get("description", "").lower()
            or p.get("pattern_type") in ["time_of_day_activity", "quality_trend"]
        ]
        
        # Step 2: Score and rank patterns
        scorer = ConfidenceScorer()
        
        for pattern in relevant_patterns:
            # Use pattern confidence directly, adjusted by recency
            confidence = float(pattern.get("confidence", 0.5))
            
            # Only surface high-confidence hints
            if confidence > 0.6:
                hints.append({
                    "pattern": pattern.get("description", ""),
                    "confidence": confidence,
                    "evidence": pattern.get("evidence", []),
                    "type": pattern.get("pattern_type", "general"),
                    "event_id": event_id,
                })
        
        # Sort by confidence descending
        hints.sort(key=lambda h: h["confidence"], reverse=True)
        
        # Limit to top 3 hints to avoid overwhelming
        hints = hints[:3]
        
        avg_confidence = (
            sum(h["confidence"] for h in hints) / len(hints)
            if hints
            else 0.0
        )
        
        logger.info(
            f"Generated {len(hints)} hints",
            extra={
                "event_id": event_id,
                "ai_tool": ai_tool,
                "avg_confidence": avg_confidence,
                "pattern_count": len(relevant_patterns),
            },
        )
        
        return {
            "hints": hints,
            "confidence": avg_confidence,
            "pattern_count": len(relevant_patterns),
        }
        
    except Exception as e:
        logger.error(
            f"Error generating hints: {e}",
            extra={"event_id": event_id},
        )
        return {
            "hints": [],
            "confidence": 0.0,
            "error": str(e),
        }


@router.post("/decision")
def log_decision(
    user_id: int,
    session_id: str,
    decision_text: str,
    context: str = "",
    category: str = "general",
    confidence: float = 0.5
):
    """Log a decision Jarvis made for cross-session learning."""
    from .cross_session_learner import cross_session_learner
    
    decision_id = cross_session_learner.log_decision(
        user_id=user_id,
        session_id=session_id,
        decision_text=decision_text,
        context=context,
        decision_category=category,
        confidence=confidence
    )
    
    return {
        "status": "logged",
        "decision_id": decision_id,
        "user_id": user_id,
        "session_id": session_id
    }


@router.post("/outcome")
def record_outcome(
    decision_id: str,
    outcome: str,
    feedback_score: float = None
):
    """Record the outcome of a decision and feedback (1-5 scale)."""
    from .cross_session_learner import cross_session_learner
    
    result = cross_session_learner.record_decision_outcome(
        decision_id=decision_id,
        outcome=outcome,
        feedback_score=feedback_score
    )
    
    return result


@router.get("/lessons")
def get_lessons(user_id: int, min_confidence: float = 0.5):
    """Get all active lessons learned from this user's sessions."""
    from .cross_session_learner import cross_session_learner
    
    lessons = cross_session_learner.get_active_lessons(
        user_id=user_id,
        min_confidence=min_confidence
    )
    
    return {
        "user_id": user_id,
        "lessons_count": len(lessons),
        "lessons": lessons
    }


@router.get("/insights")
def get_insights(user_id: int, days: int = 30):
    """Analyze decision quality and learning progress over time."""
    from .cross_session_learner import cross_session_learner

    insights = cross_session_learner.get_decision_insights(
        user_id=user_id,
        days=days
    )

    return {
        "user_id": user_id,
        **insights
    }


# ============ Suggestion Outcome Tracking (Phase 18) ============

@router.post("/suggestion")
def log_suggestion(
    user_id: int,
    session_id: str,
    suggestion_text: str,
    suggestion_type: str = "advice",
    context: str = "",
    confidence: float = 0.5,
    followup_hours: int = 24
):
    """
    Log a suggestion Jarvis made for outcome tracking.

    Args:
        user_id: The user receiving the suggestion
        session_id: Current session ID
        suggestion_text: The actual suggestion text
        suggestion_type: One of: advice, task, insight, recommendation
        context: Additional context
        confidence: Jarvis' confidence (0.0-1.0)
        followup_hours: Hours until follow-up (default 24)

    Returns:
        suggestion_id for tracking
    """
    from .cross_session_learner import cross_session_learner

    suggestion_id = cross_session_learner.log_suggestion(
        user_id=user_id,
        session_id=session_id,
        suggestion_text=suggestion_text,
        suggestion_type=suggestion_type,
        context=context,
        confidence=confidence,
        followup_hours=followup_hours
    )

    return {
        "status": "logged",
        "suggestion_id": suggestion_id,
        "user_id": user_id,
        "followup_in_hours": followup_hours
    }


@router.post("/suggestion-outcome")
def record_suggestion_outcome(
    suggestion_id: str,
    outcome: str,
    outcome_notes: str = ""
):
    """
    Record the outcome of a suggestion.

    Args:
        suggestion_id: The suggestion to update
        outcome: One of: worked, partially, didnt_work, not_tried
        outcome_notes: Optional notes about the outcome

    Returns:
        Status with updated info
    """
    from .cross_session_learner import cross_session_learner

    result = cross_session_learner.record_suggestion_outcome(
        suggestion_id=suggestion_id,
        outcome=outcome,
        outcome_notes=outcome_notes
    )

    return result


@router.get("/pending-followups")
def get_pending_followups(user_id: int = None, limit: int = 50):
    """
    Get suggestions due for follow-up (outcome not yet recorded).

    Used by n8n workflow to send follow-up messages.
    """
    from .cross_session_learner import cross_session_learner

    followups = cross_session_learner.get_pending_followups(
        user_id=user_id,
        limit=limit
    )

    return {
        "count": len(followups),
        "followups": followups
    }


@router.post("/mark-followup-sent")
def mark_followup_sent(suggestion_id: str):
    """Mark a suggestion as having its follow-up message sent."""
    from .cross_session_learner import cross_session_learner

    success = cross_session_learner.mark_followup_sent(suggestion_id)

    return {
        "status": "marked" if success else "not_found",
        "suggestion_id": suggestion_id
    }


@router.get("/suggestion-stats")
def get_suggestion_stats(user_id: int = None, days: int = 30):
    """
    Get statistics about suggestion outcomes.

    Returns:
        - Total suggestions
        - Outcomes recorded
        - Breakdown by outcome type
        - Effectiveness rate
    """
    from .cross_session_learner import cross_session_learner

    stats = cross_session_learner.get_suggestion_stats(
        user_id=user_id,
        days=days
    )

    return stats


@router.get("/top-suggestions")
def get_top_suggestions(user_id: int = None, limit: int = 5):
    """
    Get the suggestions that worked best (for weekly report).
    """
    from .cross_session_learner import cross_session_learner

    suggestions = cross_session_learner.get_top_working_suggestions(
        user_id=user_id,
        limit=limit
    )

    return {
        "count": len(suggestions),
        "top_suggestions": suggestions
    }


@router.get("/impact-summary")
def get_impact_summary(user_id: int = None, days: int = 30):
    """
    Compact impact summary for Jarvis suggestions.

    Includes outcome stats + best-performing suggestions.
    """
    from .cross_session_learner import cross_session_learner

    stats = cross_session_learner.get_suggestion_stats(user_id=user_id, days=days)
    top = cross_session_learner.get_top_working_suggestions(user_id=user_id, limit=5)

    return {
        "period_days": days,
        "stats": stats,
        "top_suggestions": top,
        "count_top": len(top)
    }

@router.get("/inject/context")
async def inject_context_hints(
    ai_tool: str = Query(..., description="AI tool (e.g., copilot)"),
    file_type: str = Query(..., description="File type extension"),
    context: str = Query("", description="Current context snippet"),
):
    """
    Get proactive hints to inject back to the extension.
    
    Called by Mac Bridge when user is about to use an AI tool.
    
    Args:
        ai_tool: Source AI tool (copilot, chatgpt, etc)
        file_type: File extension (py, js, md, etc)
        context: Optional current context/selection
    
    Returns:
        Ranked hints with confidence scores
    """
    event_id = str(uuid.uuid4())
    
    try:
        # Generate hints based on patterns for this ai_tool + file_type combo
        hints = await generate_ai_hints(
            ai_tool=ai_tool,
            file_path=f"unknown.{file_type}",
            suggestion="",
            action="requested",
            context={"context": context},
            event_id=event_id,
        )
        
        logger.info(
            f"Injection hints generated",
            extra={
                "event_id": event_id,
                "ai_tool": ai_tool,
                "file_type": file_type,
                "hint_count": len(hints.get("hints", [])),
                "confidence": hints.get("confidence", 0.0),
            },
        )
        
        return {
            "status": "success",
            "event_id": event_id,
            "hints": hints.get("hints", []),
            "confidence": hints.get("confidence", 0.0),
            "pattern_count": hints.get("pattern_count", 0),
        }
        
    except Exception as e:
        logger.error(
            f"Error in injection endpoint: {e}",
            extra={"event_id": event_id, "ai_tool": ai_tool},
        )
        return {
            "status": "error",
            "error": str(e),
            "hints": [],
            "confidence": 0.0,
        }
