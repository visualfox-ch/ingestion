"""
Jarvis Cross-Domain Learner - Pattern Transfer Between Coaching Domains

Identifies patterns that apply across domains:
- Stress patterns (work stress affecting fitness)
- Time patterns (busy periods affecting all domains)
- Success patterns (what works in one domain may work in another)
- Blocker patterns (recurring obstacles)
"""
import json
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass

from .knowledge_db import get_conn
from .observability import get_logger, log_with_context

logger = get_logger("jarvis.crossdomain")


# ============ Data Classes ============

@dataclass
class CrossDomainInsight:
    """An insight that spans multiple domains"""
    id: Optional[int]
    user_id: int
    source_domain: str
    target_domain: Optional[str]
    insight_type: str
    content: str
    confidence: float
    evidence: List[Dict[str, Any]]
    applied: bool = False
    created_at: datetime = None


@dataclass
class DomainCorrelation:
    """Correlation between two domains"""
    domain_a: str
    domain_b: str
    correlation_type: str
    strength: float  # -1 to 1
    sample_count: int
    description: str


# ============ Pattern Detection ============

PATTERN_DEFINITIONS = {
    "stress_spillover": {
        "description": "Stress in one domain affecting another",
        "source_indicators": ["stress", "überlastet", "overwhelm", "zu viel"],
        "connections": [
            ("work", "fitness", "Work stress reducing workout motivation"),
            ("work", "nutrition", "Work stress affecting eating habits"),
            ("communication", "work", "Conflicts affecting work focus"),
        ]
    },
    "time_competition": {
        "description": "Time constraints affecting multiple domains",
        "source_indicators": ["keine zeit", "zu wenig zeit", "busy", "termine"],
        "connections": [
            ("work", "fitness", "Busy work schedule reducing exercise"),
            ("work", "nutrition", "No time for meal prep"),
        ]
    },
    "energy_correlation": {
        "description": "Energy levels connecting domains",
        "source_indicators": ["müde", "energie", "erschöpft", "fit"],
        "connections": [
            ("fitness", "work", "Exercise improving work energy"),
            ("nutrition", "fitness", "Diet affecting workout performance"),
            ("fitness", "nutrition", "Training affecting hunger/cravings"),
        ]
    },
    "success_transfer": {
        "description": "Success patterns that transfer",
        "source_indicators": ["geschafft", "erreicht", "erfolg", "funktioniert"],
        "connections": [
            ("fitness", "work", "Discipline from fitness helping work"),
            ("work", "presentation", "Project success building presentation confidence"),
        ]
    },
    "habit_chain": {
        "description": "Habits that reinforce each other",
        "source_indicators": ["routine", "gewohnheit", "jeden tag", "regelmäßig"],
        "connections": [
            ("fitness", "nutrition", "Exercise routine improving eating habits"),
            ("nutrition", "fitness", "Meal prep enabling consistent training"),
        ]
    },
}


def detect_patterns_in_message(
    user_id: int,
    domain_id: str,
    message: str,
    response: str
) -> List[CrossDomainInsight]:
    """
    Analyze a message for cross-domain patterns.
    """
    insights = []
    message_lower = message.lower()

    for pattern_type, pattern_def in PATTERN_DEFINITIONS.items():
        # Check if any indicators are present
        indicators_found = [
            ind for ind in pattern_def["source_indicators"]
            if ind in message_lower
        ]

        if indicators_found:
            # Check which connections apply
            for source, target, description in pattern_def["connections"]:
                if source == domain_id:
                    insights.append(CrossDomainInsight(
                        id=None,
                        user_id=user_id,
                        source_domain=source,
                        target_domain=target,
                        insight_type=pattern_type,
                        content=description,
                        confidence=min(len(indicators_found) * 0.3, 0.9),
                        evidence=[{
                            "indicators": indicators_found,
                            "message_snippet": message[:200],
                            "domain": domain_id,
                            "timestamp": datetime.utcnow().isoformat()
                        }]
                    ))

    return insights


def store_insight(insight: CrossDomainInsight) -> Optional[int]:
    """Store a cross-domain insight."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO cross_domain_insight
                (user_id, source_domain, target_domain, insight_type, content,
                 confidence, evidence, applied, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                insight.user_id,
                insight.source_domain,
                insight.target_domain,
                insight.insight_type,
                insight.content,
                insight.confidence,
                json.dumps(insight.evidence),
                insight.applied,
                datetime.utcnow()
            ))
            row = cur.fetchone()
            return row["id"] if row else None
    except Exception as e:
        log_with_context(logger, "error", "Failed to store insight", error=str(e))
        return None


def get_insights_for_domain(
    user_id: int,
    target_domain: str,
    min_confidence: float = 0.5,
    limit: int = 10
) -> List[Dict[str, Any]]:
    """
    Get cross-domain insights relevant to a target domain.

    Used when entering a domain to surface relevant patterns from other domains.
    """
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT * FROM cross_domain_insight
                WHERE user_id = %s
                  AND (target_domain = %s OR target_domain IS NULL)
                  AND confidence >= %s
                  AND applied = false
                ORDER BY confidence DESC, created_at DESC
                LIMIT %s
            """, (user_id, target_domain, min_confidence, limit))

            return [dict(row) for row in cur.fetchall()]
    except Exception as e:
        log_with_context(logger, "error", "Failed to get insights", error=str(e))
        return []


def mark_insight_applied(insight_id: int) -> bool:
    """Mark an insight as applied/acknowledged."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                UPDATE cross_domain_insight
                SET applied = true
                WHERE id = %s
            """, (insight_id,))
            return True
    except Exception as e:
        log_with_context(logger, "error", "Failed to mark insight", error=str(e))
        return False


# ============ Correlation Analysis ============

def calculate_domain_correlations(
    user_id: int,
    days: int = 30
) -> List[DomainCorrelation]:
    """
    Calculate correlations between domain activities.

    Looks at:
    - Activity overlap (using both domains on same day)
    - Success overlap (positive metrics in both)
    - Pattern co-occurrence
    """
    correlations = []

    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cutoff = datetime.utcnow() - timedelta(days=days)

            # Get domain pairs with their activity patterns
            cur.execute("""
                WITH domain_days AS (
                    SELECT
                        domain_id,
                        DATE(created_at) as activity_date,
                        AVG(metric_value) as avg_metric
                    FROM coaching_effectiveness
                    WHERE user_id = %s AND created_at > %s
                    GROUP BY domain_id, DATE(created_at)
                )
                SELECT
                    a.domain_id as domain_a,
                    b.domain_id as domain_b,
                    COUNT(*) as overlap_days,
                    CORR(a.avg_metric, b.avg_metric) as metric_correlation
                FROM domain_days a
                JOIN domain_days b ON a.activity_date = b.activity_date
                                   AND a.domain_id < b.domain_id
                GROUP BY a.domain_id, b.domain_id
                HAVING COUNT(*) >= 3
            """, (user_id, cutoff))

            for row in cur.fetchall():
                correlation = row["metric_correlation"] or 0

                if abs(correlation) >= 0.3:
                    if correlation > 0:
                        desc = f"Positive correlation: success in {row['domain_a']} correlates with {row['domain_b']}"
                    else:
                        desc = f"Negative correlation: high activity in {row['domain_a']} may impact {row['domain_b']}"

                    correlations.append(DomainCorrelation(
                        domain_a=row["domain_a"],
                        domain_b=row["domain_b"],
                        correlation_type="activity_metric",
                        strength=correlation,
                        sample_count=row["overlap_days"],
                        description=desc
                    ))

    except Exception as e:
        log_with_context(logger, "error", "Failed to calculate correlations", error=str(e))

    return correlations


def get_domain_synergies(user_id: int) -> List[Dict[str, Any]]:
    """
    Identify positive synergies between domains.

    Domains that benefit each other when used together.
    """
    correlations = calculate_domain_correlations(user_id)

    synergies = []
    for corr in correlations:
        if corr.strength >= 0.5:
            synergies.append({
                "domains": [corr.domain_a, corr.domain_b],
                "strength": corr.strength,
                "type": "synergy",
                "recommendation": f"Keep combining {corr.domain_a} and {corr.domain_b} - they reinforce each other",
            })

    return synergies


def get_domain_conflicts(user_id: int) -> List[Dict[str, Any]]:
    """
    Identify conflicts between domains.

    Domains that may compete for resources (time, energy).
    """
    correlations = calculate_domain_correlations(user_id)

    conflicts = []
    for corr in correlations:
        if corr.strength <= -0.5:
            conflicts.append({
                "domains": [corr.domain_a, corr.domain_b],
                "strength": abs(corr.strength),
                "type": "conflict",
                "recommendation": f"Consider scheduling {corr.domain_a} and {corr.domain_b} on different days",
            })

    return conflicts


# ============ Learning Transfer ============

def suggest_technique_transfer(
    user_id: int,
    target_domain: str
) -> List[Dict[str, Any]]:
    """
    Suggest techniques from successful domains that might help target domain.
    """
    suggestions = []

    try:
        # Find user's most successful domains
        from . import feedback_tracker
        comparison = feedback_tracker.get_domain_comparison(user_id, days=30)

        successful_domains = [
            d for d in comparison
            if d["domain_id"] != target_domain and d["avg_effectiveness"] >= 0.7
        ]

        # Get patterns from successful domains
        for domain_data in successful_domains[:3]:
            source_domain = domain_data["domain_id"]

            # Check for applicable patterns
            for pattern_type, pattern_def in PATTERN_DEFINITIONS.items():
                for source, target, description in pattern_def["connections"]:
                    if source == source_domain and target == target_domain:
                        suggestions.append({
                            "source_domain": source_domain,
                            "target_domain": target_domain,
                            "pattern": pattern_type,
                            "suggestion": f"Apply success from {source_domain}: {description}",
                            "confidence": domain_data["avg_effectiveness"]
                        })

    except Exception as e:
        log_with_context(logger, "error", "Failed to suggest transfers", error=str(e))

    return suggestions


# ============ Context Building ============

def build_cross_domain_context(
    user_id: int,
    current_domain: str
) -> str:
    """
    Build cross-domain context to inject into system prompt.

    Includes relevant insights from other domains.
    """
    context_parts = []

    # Get pending insights for this domain
    insights = get_insights_for_domain(user_id, current_domain, min_confidence=0.6, limit=3)

    if insights:
        context_parts.append("=== CROSS-DOMAIN PATTERNS ===")
        context_parts.append("")

        for insight in insights:
            source = insight.get("source_domain", "unknown")
            content = insight.get("content", "")
            confidence = insight.get("confidence", 0)

            context_parts.append(f"- From {source} ({confidence:.0%} confidence): {content}")

        context_parts.append("")

    # Get technique transfer suggestions
    suggestions = suggest_technique_transfer(user_id, current_domain)

    if suggestions:
        context_parts.append("Consider applying:")
        for sugg in suggestions[:2]:
            context_parts.append(f"- {sugg['suggestion']}")
        context_parts.append("")

    return "\n".join(context_parts) if context_parts else ""


# ============ Weekly Digest ============

def generate_weekly_learning_digest(user_id: int) -> Dict[str, Any]:
    """
    Generate a weekly digest of cross-domain learnings.
    """
    digest = {
        "generated_at": datetime.utcnow().isoformat(),
        "period": "last_7_days",
        "insights": [],
        "synergies": [],
        "conflicts": [],
        "recommendations": [],
    }

    try:
        # Get recent insights
        with get_conn() as conn:
            cur = conn.cursor()
            cutoff = datetime.utcnow() - timedelta(days=7)

            cur.execute("""
                SELECT source_domain, target_domain, insight_type, content, confidence
                FROM cross_domain_insight
                WHERE user_id = %s AND created_at > %s AND confidence >= 0.6
                ORDER BY confidence DESC
                LIMIT 10
            """, (user_id, cutoff))

            digest["insights"] = [dict(row) for row in cur.fetchall()]

        # Get synergies and conflicts
        digest["synergies"] = get_domain_synergies(user_id)[:3]
        digest["conflicts"] = get_domain_conflicts(user_id)[:3]

        # Generate recommendations
        if digest["synergies"]:
            best_synergy = digest["synergies"][0]
            digest["recommendations"].append(
                f"Double down on {' + '.join(best_synergy['domains'])} - starke Synergie"
            )

        if digest["conflicts"]:
            worst_conflict = digest["conflicts"][0]
            digest["recommendations"].append(
                f"Achtung: {' vs '.join(worst_conflict['domains'])} konkurrieren um Ressourcen"
            )

        if not digest["insights"]:
            digest["recommendations"].append(
                "Mehr Domains aktiv nutzen für bessere Cross-Domain-Insights"
            )

    except Exception as e:
        log_with_context(logger, "error", "Failed to generate digest", error=str(e))
        digest["error"] = str(e)

    return digest
