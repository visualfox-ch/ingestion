"""
Jarvis Competency Model - Skill Progression Tracking

Tracks competency development across domains:
- Skill levels (1-5 scale)
- Evidence-based assessments
- Progress over time
- Skill gap identification
"""
import json
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field

from .knowledge_db import get_conn
from .observability import get_logger, log_with_context

logger = get_logger("jarvis.competency")


# ============ Skill Level Definitions ============

SKILL_LEVELS = {
    1: {
        "name": "Beginner",
        "description": "Just starting, needs guidance on basics",
        "characteristics": ["Needs step-by-step instructions", "Asks fundamental questions"],
    },
    2: {
        "name": "Advanced Beginner",
        "description": "Understands basics, can follow instructions",
        "characteristics": ["Can apply learned patterns", "Needs help with edge cases"],
    },
    3: {
        "name": "Competent",
        "description": "Can work independently on routine tasks",
        "characteristics": ["Plans own approach", "Handles most situations"],
    },
    4: {
        "name": "Proficient",
        "description": "Strong grasp, can mentor others",
        "characteristics": ["Sees bigger picture", "Adapts approaches"],
    },
    5: {
        "name": "Expert",
        "description": "Deep expertise, intuitive mastery",
        "characteristics": ["Innovates", "Coaches others", "Handles complexity"],
    },
}


# ============ Domain Competency Frameworks ============

DOMAIN_COMPETENCIES = {
    "linkedin": [
        {"id": "content_creation", "name": "Content Creation", "description": "Creating engaging posts"},
        {"id": "storytelling", "name": "Storytelling", "description": "Crafting compelling narratives"},
        {"id": "engagement", "name": "Engagement", "description": "Building audience interaction"},
        {"id": "personal_brand", "name": "Personal Brand", "description": "Consistent brand presence"},
    ],
    "communication": [
        {"id": "feedback_giving", "name": "Feedback Giving", "description": "Delivering constructive feedback"},
        {"id": "conflict_resolution", "name": "Conflict Resolution", "description": "Resolving disagreements"},
        {"id": "active_listening", "name": "Active Listening", "description": "Understanding others fully"},
        {"id": "assertiveness", "name": "Assertiveness", "description": "Expressing needs clearly"},
    ],
    "fitness": [
        {"id": "consistency", "name": "Consistency", "description": "Regular training habit"},
        {"id": "technique", "name": "Technique", "description": "Proper exercise form"},
        {"id": "recovery", "name": "Recovery", "description": "Rest and recuperation"},
        {"id": "nutrition_timing", "name": "Nutrition Timing", "description": "Fueling for performance"},
    ],
    "nutrition": [
        {"id": "meal_planning", "name": "Meal Planning", "description": "Planning ahead"},
        {"id": "macro_balance", "name": "Macro Balance", "description": "Balancing nutrients"},
        {"id": "mindful_eating", "name": "Mindful Eating", "description": "Eating awareness"},
        {"id": "prep_skills", "name": "Prep Skills", "description": "Kitchen efficiency"},
    ],
    "work": [
        {"id": "prioritization", "name": "Prioritization", "description": "Focus on what matters"},
        {"id": "stakeholder_mgmt", "name": "Stakeholder Management", "description": "Managing relationships"},
        {"id": "project_planning", "name": "Project Planning", "description": "Planning work effectively"},
        {"id": "delegation", "name": "Delegation", "description": "Distributing work appropriately"},
    ],
    "ideas": [
        {"id": "divergent_thinking", "name": "Divergent Thinking", "description": "Generating many ideas"},
        {"id": "critical_analysis", "name": "Critical Analysis", "description": "Evaluating ideas"},
        {"id": "creativity", "name": "Creativity", "description": "Novel combinations"},
        {"id": "synthesis", "name": "Synthesis", "description": "Combining ideas"},
    ],
    "presentation": [
        {"id": "structure", "name": "Structure", "description": "Clear presentation flow"},
        {"id": "storytelling_pres", "name": "Storytelling", "description": "Engaging narrative"},
        {"id": "delivery", "name": "Delivery", "description": "Speaking presence"},
        {"id": "visual_design", "name": "Visual Design", "description": "Effective slides"},
    ],
}


# ============ Data Classes ============

@dataclass
class Competency:
    """A competency with current level and history"""
    user_id: int
    domain_id: str
    competency_id: str
    competency_name: str
    current_level: int
    target_level: Optional[int]
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    last_assessed: Optional[datetime] = None


@dataclass
class CompetencyAssessment:
    """A single assessment of a competency"""
    user_id: int
    domain_id: str
    competency_id: str
    assessed_level: int
    evidence: str
    assessed_by: str  # "self", "system", "coach"
    created_at: datetime = None


# ============ Competency Management ============

def get_user_competencies(
    user_id: int,
    domain_id: str
) -> List[Competency]:
    """Get all competencies for a user in a domain."""
    competencies = []

    # Get framework for domain
    framework = DOMAIN_COMPETENCIES.get(domain_id, [])

    try:
        with get_conn() as conn:
            cur = conn.cursor()

            for comp_def in framework:
                cur.execute("""
                    SELECT current_level, target_level, evidence, last_assessed_at
                    FROM user_competency
                    WHERE user_id = %s AND domain_id = %s AND competency_name = %s
                """, (user_id, domain_id, comp_def["id"]))

                row = cur.fetchone()

                if row:
                    evidence = json.loads(row["evidence"]) if row["evidence"] else []
                    competencies.append(Competency(
                        user_id=user_id,
                        domain_id=domain_id,
                        competency_id=comp_def["id"],
                        competency_name=comp_def["name"],
                        current_level=row["current_level"],
                        target_level=row["target_level"],
                        evidence=evidence,
                        last_assessed=row["last_assessed_at"]
                    ))
                else:
                    # Create default entry
                    competencies.append(Competency(
                        user_id=user_id,
                        domain_id=domain_id,
                        competency_id=comp_def["id"],
                        competency_name=comp_def["name"],
                        current_level=1,
                        target_level=None,
                        evidence=[],
                        last_assessed=None
                    ))

    except Exception as e:
        log_with_context(logger, "error", "Failed to get competencies", error=str(e))

    return competencies


def update_competency(
    user_id: int,
    domain_id: str,
    competency_id: str,
    new_level: int,
    evidence: str,
    assessed_by: str = "system"
) -> bool:
    """Update a competency level with evidence."""
    if new_level < 1 or new_level > 5:
        return False

    try:
        with get_conn() as conn:
            cur = conn.cursor()

            # Get current evidence
            cur.execute("""
                SELECT evidence FROM user_competency
                WHERE user_id = %s AND domain_id = %s AND competency_name = %s
            """, (user_id, domain_id, competency_id))

            row = cur.fetchone()
            existing_evidence = json.loads(row["evidence"]) if row and row["evidence"] else []

            # Add new evidence
            existing_evidence.append({
                "level": new_level,
                "evidence": evidence,
                "assessed_by": assessed_by,
                "timestamp": datetime.utcnow().isoformat()
            })

            # Keep last 10 evidence entries
            existing_evidence = existing_evidence[-10:]

            # Upsert competency
            cur.execute("""
                INSERT INTO user_competency
                (user_id, domain_id, competency_name, current_level, evidence, last_assessed_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id, domain_id, competency_name)
                DO UPDATE SET
                    current_level = EXCLUDED.current_level,
                    evidence = EXCLUDED.evidence,
                    last_assessed_at = EXCLUDED.last_assessed_at,
                    updated_at = EXCLUDED.updated_at
            """, (
                user_id, domain_id, competency_id, new_level,
                json.dumps(existing_evidence),
                datetime.utcnow(), datetime.utcnow()
            ))

            # Store assessment record
            cur.execute("""
                INSERT INTO competency_assessment
                (user_id, domain_id, competency_name, assessed_level, evidence, assessed_by, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (user_id, domain_id, competency_id, new_level, evidence, assessed_by, datetime.utcnow()))

            log_with_context(logger, "info", "Competency updated",
                           user_id=user_id, domain=domain_id,
                           competency=competency_id, level=new_level)
            return True

    except Exception as e:
        log_with_context(logger, "error", "Failed to update competency", error=str(e))
        return False


def set_target_level(
    user_id: int,
    domain_id: str,
    competency_id: str,
    target_level: int
) -> bool:
    """Set a target level for a competency."""
    if target_level < 1 or target_level > 5:
        return False

    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                UPDATE user_competency
                SET target_level = %s, updated_at = %s
                WHERE user_id = %s AND domain_id = %s AND competency_name = %s
            """, (target_level, datetime.utcnow(), user_id, domain_id, competency_id))

            if cur.rowcount == 0:
                # Create entry if doesn't exist
                cur.execute("""
                    INSERT INTO user_competency
                    (user_id, domain_id, competency_name, current_level, target_level, created_at, updated_at)
                    VALUES (%s, %s, %s, 1, %s, %s, %s)
                """, (user_id, domain_id, competency_id, target_level, datetime.utcnow(), datetime.utcnow()))

            return True
    except Exception as e:
        log_with_context(logger, "error", "Failed to set target", error=str(e))
        return False


# ============ Gap Analysis ============

def get_skill_gaps(
    user_id: int,
    domain_id: str = None
) -> List[Dict[str, Any]]:
    """Identify skill gaps (current < target)."""
    gaps = []

    try:
        with get_conn() as conn:
            cur = conn.cursor()

            domain_filter = "AND domain_id = %s" if domain_id else ""
            params = [user_id]
            if domain_id:
                params.append(domain_id)

            cur.execute(f"""
                SELECT domain_id, competency_name, current_level, target_level
                FROM user_competency
                WHERE user_id = %s {domain_filter}
                  AND target_level IS NOT NULL
                  AND current_level < target_level
                ORDER BY (target_level - current_level) DESC
            """, params)

            for row in cur.fetchall():
                gap_size = row["target_level"] - row["current_level"]
                gaps.append({
                    "domain_id": row["domain_id"],
                    "competency_id": row["competency_name"],
                    "current_level": row["current_level"],
                    "target_level": row["target_level"],
                    "gap_size": gap_size,
                    "priority": "high" if gap_size >= 2 else "medium" if gap_size == 1 else "low"
                })

    except Exception as e:
        log_with_context(logger, "error", "Failed to get gaps", error=str(e))

    return gaps


def get_development_suggestions(
    user_id: int,
    domain_id: str,
    competency_id: str
) -> List[str]:
    """Get suggestions for developing a competency."""
    suggestions = []

    competencies = get_user_competencies(user_id, domain_id)
    current_comp = next((c for c in competencies if c.competency_id == competency_id), None)

    if not current_comp:
        return ["Start practicing this skill regularly"]

    level = current_comp.current_level

    # Level-specific suggestions
    if level == 1:
        suggestions.extend([
            "Start with the basics - follow structured guides",
            "Practice in low-stakes situations first",
            "Ask for feedback on fundamentals",
        ])
    elif level == 2:
        suggestions.extend([
            "Try applying skills without step-by-step guidance",
            "Experiment with variations of learned patterns",
            "Seek feedback on edge cases",
        ])
    elif level == 3:
        suggestions.extend([
            "Take on more complex challenges",
            "Start helping others with basics",
            "Analyze what experts do differently",
        ])
    elif level == 4:
        suggestions.extend([
            "Mentor someone at a lower level",
            "Develop your own frameworks",
            "Share your approach publicly",
        ])
    elif level == 5:
        suggestions.extend([
            "Continue innovating",
            "Teach advanced concepts",
            "Contribute to the field",
        ])

    return suggestions


# ============ Progress Tracking ============

def get_competency_history(
    user_id: int,
    domain_id: str,
    competency_id: str,
    limit: int = 20
) -> List[Dict[str, Any]]:
    """Get assessment history for a competency."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT assessed_level, evidence, assessed_by, created_at
                FROM competency_assessment
                WHERE user_id = %s AND domain_id = %s AND competency_name = %s
                ORDER BY created_at DESC
                LIMIT %s
            """, (user_id, domain_id, competency_id, limit))

            return [dict(row) for row in cur.fetchall()]
    except Exception as e:
        log_with_context(logger, "error", "Failed to get history", error=str(e))
        return []


def get_domain_progress(
    user_id: int,
    domain_id: str,
    days: int = 90
) -> Dict[str, Any]:
    """Get overall progress in a domain."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cutoff = datetime.utcnow() - timedelta(days=days)

            # Get current average level
            cur.execute("""
                SELECT AVG(current_level) as avg_level, COUNT(*) as competency_count
                FROM user_competency
                WHERE user_id = %s AND domain_id = %s
            """, (user_id, domain_id))

            current = cur.fetchone()

            # Get historical average (start of period)
            cur.execute("""
                SELECT AVG(assessed_level) as avg_level
                FROM competency_assessment
                WHERE user_id = %s AND domain_id = %s
                  AND created_at < %s
                ORDER BY created_at ASC
                LIMIT 1
            """, (user_id, domain_id, cutoff))

            historical = cur.fetchone()

            # Get recent assessments
            cur.execute("""
                SELECT competency_name, assessed_level, created_at
                FROM competency_assessment
                WHERE user_id = %s AND domain_id = %s AND created_at > %s
                ORDER BY created_at DESC
            """, (user_id, domain_id, cutoff))

            assessments = [dict(row) for row in cur.fetchall()]

            current_avg = current["avg_level"] or 1.0 if current else 1.0
            historical_avg = historical["avg_level"] if historical and historical["avg_level"] else current_avg

            return {
                "domain_id": domain_id,
                "current_avg_level": round(current_avg, 2),
                "competency_count": current["competency_count"] if current else 0,
                "progress_delta": round(current_avg - historical_avg, 2),
                "recent_assessments": assessments[:10],
                "trend": "improving" if current_avg > historical_avg else "stable" if current_avg == historical_avg else "declining"
            }

    except Exception as e:
        log_with_context(logger, "error", "Failed to get progress", error=str(e))
        return {}


# ============ Context Building ============

def build_competency_context(
    user_id: int,
    domain_id: str
) -> str:
    """Build competency context for system prompt."""
    context_parts = []

    competencies = get_user_competencies(user_id, domain_id)
    gaps = get_skill_gaps(user_id, domain_id)

    if competencies:
        context_parts.append("=== SKILL LEVELS ===")
        for comp in competencies:
            level_name = SKILL_LEVELS.get(comp.current_level, {}).get("name", "Unknown")
            target_str = f" (Ziel: {comp.target_level})" if comp.target_level else ""
            context_parts.append(f"- {comp.competency_name}: Level {comp.current_level} ({level_name}){target_str}")
        context_parts.append("")

    if gaps:
        high_priority = [g for g in gaps if g["priority"] == "high"]
        if high_priority:
            context_parts.append("Fokus-Skills (größte Gaps):")
            for gap in high_priority[:3]:
                context_parts.append(f"- {gap['competency_id']}: {gap['current_level']} → {gap['target_level']}")
            context_parts.append("")

    return "\n".join(context_parts) if context_parts else ""


# ============ Automatic Assessment ============

def assess_from_conversation(
    user_id: int,
    domain_id: str,
    message: str,
    response: str
) -> List[Tuple[str, int, str]]:
    """
    Attempt to assess competencies from conversation.

    Returns list of (competency_id, suggested_level, evidence)
    """
    assessments = []
    message_lower = message.lower()

    # Define indicators per competency
    indicators = {
        "linkedin": {
            "content_creation": {
                3: ["post", "carousel", "content"],
                4: ["viral", "engagement rate", "regelmäßig"],
            },
            "storytelling": {
                3: ["story", "personal", "erfahrung"],
                4: ["hook", "narrative", "emotional"],
            },
        },
        "communication": {
            "feedback_giving": {
                2: ["feedback", "sagen", "ansprechen"],
                3: ["sbi", "situation", "impact"],
                4: ["konstruktiv", "balance", "follow-up"],
            },
        },
        "fitness": {
            "consistency": {
                2: ["manchmal", "versuche"],
                3: ["regelmäßig", "routine", "plan"],
                4: ["jeden tag", "nie auslassen", "discipline"],
            },
        },
    }

    domain_indicators = indicators.get(domain_id, {})

    for comp_id, levels in domain_indicators.items():
        for level, keywords in levels.items():
            matches = [k for k in keywords if k in message_lower]
            if matches:
                assessments.append((
                    comp_id,
                    level,
                    f"Mentioned: {', '.join(matches)}"
                ))
                break  # Only one assessment per competency

    return assessments
