"""
Feedback Loop Service Module

Phase 21: Jarvis Self-Programming - Feedback Loop Tools
Implements tools for closing the learning loop between actions and outcomes.

Tools implemented:
1. track_intervention_outcomes() - Track whether suggestions/interventions helped
2. measure_cognitive_load_reduction() - Measure if clarifying questions are declining
3. request_targeted_feedback() - Ask specific yes/no/maybe questions

These tools enable Jarvis to learn from the effects of his actions and adapt.
"""

import os
import json
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict

from .observability import get_logger
from .db_safety import safe_list_query, safe_aggregate_query

logger = get_logger("jarvis.feedback_loop")

# Storage path for intervention tracking
INTERVENTION_LOG_PATH = os.environ.get(
    "JARVIS_INTERVENTION_LOG_PATH",
    "/brain/system/logs/intervention_outcomes.jsonl"
)


@dataclass
class InterventionOutcome:
    """Tracks the outcome of a Jarvis intervention/suggestion."""
    intervention_id: str
    intervention_type: str  # suggestion, reminder, proactive_hint, coaching
    description: str
    outcome_rating: Optional[int]  # 1-5 scale from user
    was_helpful: Optional[bool]
    cognitive_load_before: Optional[float]  # 0.0-1.0
    cognitive_load_after: Optional[float]   # 0.0-1.0
    effectiveness_score: Optional[float]    # Calculated
    user_feedback_text: Optional[str]
    context: Dict[str, Any]
    created_at: str
    outcome_recorded_at: Optional[str]


@dataclass
class CognitiveLoadMeasurement:
    """Measures cognitive load indicators over time."""
    period_start: str
    period_end: str
    clarifying_questions_asked: int
    total_queries: int
    clarification_rate: float  # questions/queries
    avg_message_length: float
    context_switches: int
    repeat_questions: int
    load_score: float  # 0.0-1.0 (lower is better)


@dataclass
class TargetedFeedbackRequest:
    """A specific feedback question for the user."""
    request_id: str
    question: str
    question_type: str  # yes_no, rating, choice
    options: Optional[List[str]]
    context: str
    rationale: str  # Why we're asking
    priority: str  # high, medium, low
    expires_at: Optional[str]
    created_at: str
    response: Optional[str]
    responded_at: Optional[str]


# =============================================================================
# 1. INTERVENTION OUTCOME TRACKING
# =============================================================================

async def track_intervention_outcomes(
    days: int = 30
) -> Dict[str, Any]:
    """
    Analyze intervention outcomes to understand what helps and what doesn't.

    Returns:
        - interventions_tracked: Total interventions in period
        - outcome_distribution: How outcomes are distributed
        - effectiveness_by_type: Which intervention types work best
        - learning_insights: Patterns discovered
    """
    result = {
        "status": "success",
        "analyzed_at": datetime.now().isoformat(),
        "period_days": days
    }

    try:
        # 1. Load intervention log
        interventions = _load_interventions(days)
        result["interventions_tracked"] = len(interventions)

        if not interventions:
            result["message"] = "No interventions tracked yet"
            result["outcome_distribution"] = {}
            result["effectiveness_by_type"] = {}
            result["learning_insights"] = []
            return result

        # 2. Calculate outcome distribution
        outcomes = Counter()
        by_type = defaultdict(list)

        for intervention in interventions:
            if intervention.get("was_helpful") is True:
                outcomes["helpful"] += 1
            elif intervention.get("was_helpful") is False:
                outcomes["not_helpful"] += 1
            else:
                outcomes["no_feedback"] += 1

            int_type = intervention.get("intervention_type", "unknown")
            if intervention.get("effectiveness_score"):
                by_type[int_type].append(intervention["effectiveness_score"])

        result["outcome_distribution"] = dict(outcomes)

        # 3. Calculate effectiveness by type
        effectiveness = {}
        for int_type, scores in by_type.items():
            if scores:
                effectiveness[int_type] = {
                    "count": len(scores),
                    "avg_effectiveness": round(sum(scores) / len(scores), 3),
                    "min": round(min(scores), 3),
                    "max": round(max(scores), 3)
                }
        result["effectiveness_by_type"] = effectiveness

        # 4. Generate learning insights
        insights = _generate_intervention_insights(interventions, effectiveness)
        result["learning_insights"] = insights

        # 5. Calculate overall effectiveness
        total_with_outcome = outcomes["helpful"] + outcomes["not_helpful"]
        if total_with_outcome > 0:
            result["overall_effectiveness"] = round(
                outcomes["helpful"] / total_with_outcome, 3
            )
        else:
            result["overall_effectiveness"] = None

        return result

    except Exception as e:
        logger.error(f"Error tracking intervention outcomes: {e}", exc_info=True)
        result["status"] = "error"
        result["error"] = str(e)
        return result


def _load_interventions(days: int) -> List[Dict[str, Any]]:
    """Load interventions from log file."""
    interventions = []
    cutoff = datetime.now() - timedelta(days=days)

    try:
        if os.path.exists(INTERVENTION_LOG_PATH):
            with open(INTERVENTION_LOG_PATH, "r") as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())
                        created = datetime.fromisoformat(
                            entry.get("created_at", "2000-01-01")
                        )
                        if created > cutoff:
                            interventions.append(entry)
                    except (json.JSONDecodeError, ValueError):
                        continue
    except Exception as e:
        logger.warning(f"Could not load interventions: {e}")

    return interventions


def _generate_intervention_insights(
    interventions: List[Dict],
    effectiveness: Dict[str, Dict]
) -> List[Dict[str, Any]]:
    """Generate learning insights from intervention data."""
    insights = []

    # Find most/least effective types
    if effectiveness:
        sorted_types = sorted(
            effectiveness.items(),
            key=lambda x: x[1].get("avg_effectiveness", 0),
            reverse=True
        )

        if sorted_types:
            best = sorted_types[0]
            insights.append({
                "type": "best_performing",
                "insight": f"'{best[0]}' interventions are most effective ({best[1]['avg_effectiveness']:.0%})",
                "recommendation": f"Prioritize {best[0]} interventions"
            })

            if len(sorted_types) > 1:
                worst = sorted_types[-1]
                if worst[1].get("avg_effectiveness", 1) < 0.5:
                    insights.append({
                        "type": "needs_improvement",
                        "insight": f"'{worst[0]}' interventions have low effectiveness ({worst[1]['avg_effectiveness']:.0%})",
                        "recommendation": f"Review and refine {worst[0]} approach"
                    })

    # Check for recent trends
    recent = [i for i in interventions if i.get("was_helpful") is not None][-10:]
    if len(recent) >= 5:
        recent_helpful = sum(1 for i in recent if i.get("was_helpful"))
        recent_rate = recent_helpful / len(recent)

        if recent_rate > 0.8:
            insights.append({
                "type": "positive_trend",
                "insight": f"Recent interventions are {recent_rate:.0%} helpful",
                "recommendation": "Current approach is working well"
            })
        elif recent_rate < 0.4:
            insights.append({
                "type": "negative_trend",
                "insight": f"Recent interventions only {recent_rate:.0%} helpful",
                "recommendation": "Review recent intervention strategy"
            })

    return insights


async def record_intervention(
    intervention_type: str,
    description: str,
    context: Dict[str, Any] = None
) -> str:
    """Record a new intervention for later outcome tracking."""
    intervention_id = f"int_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"

    entry = {
        "intervention_id": intervention_id,
        "intervention_type": intervention_type,
        "description": description,
        "context": context or {},
        "created_at": datetime.now().isoformat(),
        "was_helpful": None,
        "outcome_rating": None,
        "effectiveness_score": None,
        "outcome_recorded_at": None
    }

    try:
        os.makedirs(os.path.dirname(INTERVENTION_LOG_PATH), exist_ok=True)
        with open(INTERVENTION_LOG_PATH, "a") as f:
            f.write(json.dumps(entry) + "\n")
        logger.info(f"Recorded intervention: {intervention_id}")
    except Exception as e:
        logger.error(f"Failed to record intervention: {e}")

    return intervention_id


async def record_outcome(
    intervention_id: str,
    was_helpful: bool,
    outcome_rating: Optional[int] = None,
    feedback_text: Optional[str] = None
) -> Dict[str, Any]:
    """Record the outcome of a previously tracked intervention."""
    entries = []
    found = False

    try:
        if os.path.exists(INTERVENTION_LOG_PATH):
            with open(INTERVENTION_LOG_PATH, "r") as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())
                        if entry.get("intervention_id") == intervention_id:
                            entry["was_helpful"] = was_helpful
                            entry["outcome_rating"] = outcome_rating
                            entry["user_feedback_text"] = feedback_text
                            entry["outcome_recorded_at"] = datetime.now().isoformat()

                            # Calculate effectiveness score
                            if outcome_rating:
                                entry["effectiveness_score"] = outcome_rating / 5.0
                            elif was_helpful:
                                entry["effectiveness_score"] = 0.8
                            else:
                                entry["effectiveness_score"] = 0.2

                            found = True
                        entries.append(entry)
                    except json.JSONDecodeError:
                        continue

        if not found:
            return {"status": "error", "message": f"Intervention {intervention_id} not found"}

        with open(INTERVENTION_LOG_PATH, "w") as f:
            for entry in entries:
                f.write(json.dumps(entry) + "\n")

        return {
            "status": "success",
            "message": f"Outcome recorded for {intervention_id}",
            "was_helpful": was_helpful
        }

    except Exception as e:
        return {"status": "error", "message": str(e)}


# =============================================================================
# 2. COGNITIVE LOAD MEASUREMENT
# =============================================================================

async def measure_cognitive_load_reduction(
    days: int = 30,
    compare_periods: bool = True
) -> Dict[str, Any]:
    """
    Measure if Jarvis is reducing cognitive load over time.

    Indicators:
    - Clarifying questions declining
    - Shorter back-and-forth conversations
    - Fewer repeat questions
    - More direct answers

    Returns:
        - current_load: Current cognitive load score
        - trend: Is load increasing or decreasing?
        - indicators: Breakdown of load components
        - comparison: Period-over-period if enabled
    """
    result = {
        "status": "success",
        "analyzed_at": datetime.now().isoformat(),
        "period_days": days
    }

    try:
        # 1. Get current period metrics
        current = await _calculate_load_metrics(days)
        result["current_period"] = current

        # 2. Get previous period for comparison
        if compare_periods:
            previous = await _calculate_load_metrics(days, offset_days=days)
            result["previous_period"] = previous

            # Calculate trend
            if current["load_score"] is not None and previous["load_score"] is not None:
                change = current["load_score"] - previous["load_score"]
                result["trend"] = {
                    "direction": "improving" if change < 0 else "worsening" if change > 0 else "stable",
                    "change": round(change, 3),
                    "change_percent": round(change / max(previous["load_score"], 0.01) * 100, 1)
                }

        # 3. Generate recommendations
        recommendations = _generate_load_recommendations(current)
        result["recommendations"] = recommendations

        return result

    except Exception as e:
        logger.error(f"Error measuring cognitive load: {e}", exc_info=True)
        result["status"] = "error"
        result["error"] = str(e)
        return result


async def _calculate_load_metrics(
    days: int,
    offset_days: int = 0
) -> Dict[str, Any]:
    """Calculate cognitive load metrics for a period."""
    metrics = {
        "period_start": (datetime.now() - timedelta(days=days + offset_days)).isoformat(),
        "period_end": (datetime.now() - timedelta(days=offset_days)).isoformat(),
        "clarifying_questions": 0,
        "total_messages": 0,
        "clarification_rate": 0.0,
        "avg_conversation_length": 0.0,
        "repeat_queries": 0,
        "load_score": None
    }

    try:
        # Get clarifying question count (messages with ? that are follow-ups)
        with safe_aggregate_query('message') as cur:
            cur.execute("""
                SELECT
                    COUNT(*) as total_messages,
                    COUNT(*) FILTER (WHERE content LIKE '%%?%%' AND role = 'assistant') as questions_asked,
                    AVG(LENGTH(content)) as avg_length
                FROM message
                WHERE created_at > NOW() - INTERVAL '%s days'
                  AND created_at <= NOW() - INTERVAL '%s days'
            """, (days + offset_days, offset_days))
            row = cur.fetchone()

            if row:
                metrics["total_messages"] = row['total_messages'] or 0
                metrics["clarifying_questions"] = row['questions_asked'] or 0
                metrics["avg_message_length"] = round(float(row['avg_length'] or 0), 1)

                if metrics["total_messages"] > 0:
                    metrics["clarification_rate"] = round(
                        metrics["clarifying_questions"] / metrics["total_messages"], 3
                    )

        # Get average conversation length
        with safe_aggregate_query('conversation') as cur:
            cur.execute("""
                SELECT AVG(message_count) as avg_length
                FROM conversation
                WHERE created_at > NOW() - INTERVAL '%s days'
                  AND created_at <= NOW() - INTERVAL '%s days'
                  AND message_count > 0
            """, (days + offset_days, offset_days))
            row = cur.fetchone()

            if row and row['avg_length']:
                metrics["avg_conversation_length"] = round(float(row['avg_length']), 1)

        # Calculate composite load score (0.0 = no load, 1.0 = high load)
        # Factors: clarification rate (40%), conversation length (30%), repeat queries (30%)
        if metrics["total_messages"] > 0:
            clarification_component = min(1.0, metrics["clarification_rate"] * 5)  # 20% rate = 1.0
            length_component = min(1.0, metrics["avg_conversation_length"] / 20)   # 20 msgs = 1.0

            metrics["load_score"] = round(
                0.4 * clarification_component +
                0.3 * length_component +
                0.3 * 0.5,  # Placeholder for repeat queries
                3
            )

    except Exception as e:
        logger.warning(f"Could not calculate load metrics: {e}")
        metrics["error"] = str(e)

    return metrics


def _generate_load_recommendations(metrics: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Generate recommendations based on cognitive load metrics."""
    recommendations = []

    load_score = metrics.get("load_score")
    if load_score is None:
        return recommendations

    if load_score > 0.7:
        recommendations.append({
            "priority": "high",
            "area": "overall_load",
            "recommendation": "Cognitive load is high - focus on more direct answers"
        })

    clarification_rate = metrics.get("clarification_rate", 0)
    if clarification_rate > 0.15:
        recommendations.append({
            "priority": "medium",
            "area": "clarification",
            "recommendation": f"Asking too many clarifying questions ({clarification_rate:.0%})",
            "action": "Improve context understanding before responding"
        })

    avg_length = metrics.get("avg_conversation_length", 0)
    if avg_length > 15:
        recommendations.append({
            "priority": "medium",
            "area": "conversation_length",
            "recommendation": f"Conversations averaging {avg_length:.0f} messages",
            "action": "Aim for more concise resolution"
        })

    return recommendations


# =============================================================================
# 3. TARGETED FEEDBACK REQUESTS
# =============================================================================

# Storage for pending feedback requests
FEEDBACK_REQUESTS_PATH = os.environ.get(
    "JARVIS_FEEDBACK_REQUESTS_PATH",
    "/brain/system/logs/feedback_requests.jsonl"
)


async def request_targeted_feedback(
    pattern_observed: Optional[str] = None
) -> Dict[str, Any]:
    """
    Generate targeted feedback questions based on observed patterns.

    Instead of generic "was this helpful?", asks specific questions like:
    - "I noticed I've been suggesting X often - is this actually useful?"
    - "You asked about Y 3 times this week - should I create a quick reference?"

    Returns:
        - pending_requests: Feedback questions awaiting response
        - new_requests: Newly generated questions based on patterns
        - response_rate: How often feedback is provided
    """
    result = {
        "status": "success",
        "analyzed_at": datetime.now().isoformat()
    }

    try:
        # 1. Load pending requests
        pending = _load_feedback_requests(status="pending")
        result["pending_requests"] = pending
        result["pending_count"] = len(pending)

        # 2. Check response rate
        all_requests = _load_feedback_requests()
        responded = [r for r in all_requests if r.get("response")]
        if all_requests:
            result["response_rate"] = round(len(responded) / len(all_requests), 3)
        else:
            result["response_rate"] = 0.0

        # 3. Generate new questions based on patterns
        if pattern_observed:
            new_request = await _generate_targeted_question(pattern_observed)
            if new_request:
                result["new_request"] = new_request

        # 4. Auto-generate questions from analytics if no specific pattern
        if not pattern_observed:
            auto_questions = await _auto_generate_questions()
            result["auto_generated_questions"] = auto_questions

        return result

    except Exception as e:
        logger.error(f"Error in targeted feedback: {e}", exc_info=True)
        result["status"] = "error"
        result["error"] = str(e)
        return result


def _load_feedback_requests(status: Optional[str] = None) -> List[Dict[str, Any]]:
    """Load feedback requests from storage."""
    requests = []

    try:
        if os.path.exists(FEEDBACK_REQUESTS_PATH):
            with open(FEEDBACK_REQUESTS_PATH, "r") as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())
                        if status is None:
                            requests.append(entry)
                        elif status == "pending" and not entry.get("response"):
                            requests.append(entry)
                        elif status == "responded" and entry.get("response"):
                            requests.append(entry)
                    except json.JSONDecodeError:
                        continue
    except Exception as e:
        logger.warning(f"Could not load feedback requests: {e}")

    return requests


async def _generate_targeted_question(pattern: str) -> Optional[Dict[str, Any]]:
    """Generate a specific feedback question based on an observed pattern."""
    request_id = f"fb_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    # Pattern-based question templates
    templates = {
        "repeated_search": {
            "question": f"I noticed you've searched for '{pattern}' multiple times. Should I create a quick reference?",
            "question_type": "yes_no",
            "rationale": "Repeated searches suggest missing knowledge"
        },
        "long_conversation": {
            "question": "Our last conversation was quite long. Was I missing context that made it harder?",
            "question_type": "yes_no",
            "rationale": "Long conversations may indicate communication inefficiency"
        },
        "suggestion_pattern": {
            "question": f"I've been suggesting '{pattern}' often - is this actually helpful?",
            "question_type": "rating",
            "rationale": "Validating suggestion effectiveness"
        }
    }

    # Select appropriate template based on pattern keywords
    template = templates.get("suggestion_pattern")  # Default

    if "search" in pattern.lower():
        template = templates["repeated_search"]
    elif "long" in pattern.lower() or "conversation" in pattern.lower():
        template = templates["long_conversation"]

    request = {
        "request_id": request_id,
        "question": template["question"],
        "question_type": template["question_type"],
        "rationale": template["rationale"],
        "pattern_observed": pattern,
        "priority": "medium",
        "created_at": datetime.now().isoformat(),
        "expires_at": (datetime.now() + timedelta(days=7)).isoformat(),
        "response": None,
        "responded_at": None
    }

    # Save request
    try:
        os.makedirs(os.path.dirname(FEEDBACK_REQUESTS_PATH), exist_ok=True)
        with open(FEEDBACK_REQUESTS_PATH, "a") as f:
            f.write(json.dumps(request) + "\n")
    except Exception as e:
        logger.error(f"Failed to save feedback request: {e}")

    return request


async def _auto_generate_questions() -> List[Dict[str, Any]]:
    """Auto-generate feedback questions from analytics data."""
    questions = []

    try:
        # Check for knowledge gaps
        with safe_aggregate_query('message') as cur:
            cur.execute("""
                SELECT
                    LOWER(SUBSTRING(content FROM 1 FOR 50)) as query_start,
                    COUNT(*) as count
                FROM message
                WHERE role = 'user'
                  AND created_at > NOW() - INTERVAL '7 days'
                GROUP BY LOWER(SUBSTRING(content FROM 1 FOR 50))
                HAVING COUNT(*) >= 3
                ORDER BY count DESC
                LIMIT 3
            """)
            rows = cur.fetchall()

            for row in rows:
                if row['count'] >= 3:
                    questions.append({
                        "type": "repeated_query",
                        "query_pattern": row['query_start'],
                        "frequency": row['count'],
                        "suggested_question": f"You've asked about this {row['count']} times - want me to remember the answer?"
                    })

    except Exception as e:
        logger.warning(f"Could not auto-generate questions: {e}")

    return questions


async def respond_to_feedback_request(
    request_id: str,
    response: str
) -> Dict[str, Any]:
    """Record a response to a feedback request."""
    entries = []
    found = False

    try:
        if os.path.exists(FEEDBACK_REQUESTS_PATH):
            with open(FEEDBACK_REQUESTS_PATH, "r") as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())
                        if entry.get("request_id") == request_id:
                            entry["response"] = response
                            entry["responded_at"] = datetime.now().isoformat()
                            found = True
                        entries.append(entry)
                    except json.JSONDecodeError:
                        continue

        if not found:
            return {"status": "error", "message": f"Request {request_id} not found"}

        with open(FEEDBACK_REQUESTS_PATH, "w") as f:
            for entry in entries:
                f.write(json.dumps(entry) + "\n")

        return {
            "status": "success",
            "message": f"Response recorded for {request_id}"
        }

    except Exception as e:
        return {"status": "error", "message": str(e)}


# =============================================================================
# DASHBOARD / SUMMARY
# =============================================================================

async def get_feedback_loop_dashboard(days: int = 30) -> Dict[str, Any]:
    """
    Get a combined view of all feedback loop metrics.

    Returns:
        - intervention_summary: Intervention effectiveness
        - cognitive_load_summary: Load metrics and trend
        - feedback_summary: Pending questions and response rate
        - overall_learning_score: How well the feedback loop is working
    """
    result = {
        "status": "success",
        "analyzed_at": datetime.now().isoformat(),
        "period_days": days
    }

    try:
        # 1. Intervention outcomes
        interventions = await track_intervention_outcomes(days)
        result["intervention_summary"] = {
            "total_tracked": interventions.get("interventions_tracked", 0),
            "overall_effectiveness": interventions.get("overall_effectiveness"),
            "outcome_distribution": interventions.get("outcome_distribution", {})
        }

        # 2. Cognitive load
        load = await measure_cognitive_load_reduction(days)
        result["cognitive_load_summary"] = {
            "current_score": load.get("current_period", {}).get("load_score"),
            "trend": load.get("trend", {}).get("direction", "unknown"),
            "clarification_rate": load.get("current_period", {}).get("clarification_rate", 0)
        }

        # 3. Feedback requests
        feedback = await request_targeted_feedback()
        result["feedback_summary"] = {
            "pending_requests": feedback.get("pending_count", 0),
            "response_rate": feedback.get("response_rate", 0)
        }

        # 4. Calculate overall learning score
        scores = []

        if interventions.get("overall_effectiveness") is not None:
            scores.append(interventions["overall_effectiveness"])

        if load.get("current_period", {}).get("load_score") is not None:
            # Invert load score (lower load = better)
            scores.append(1.0 - load["current_period"]["load_score"])

        if feedback.get("response_rate", 0) > 0:
            scores.append(feedback["response_rate"])

        if scores:
            result["overall_learning_score"] = round(sum(scores) / len(scores), 3)
        else:
            result["overall_learning_score"] = None

        return result

    except Exception as e:
        logger.error(f"Error getting feedback dashboard: {e}", exc_info=True)
        result["status"] = "error"
        result["error"] = str(e)
        return result
