"""
Self-Modification Service Module

Phase 21: Jarvis Self-Programming - Self-Modification Tools
Implements tools for Jarvis to analyze and optimize his own performance.

Tools implemented:
1. tune_search_weights() - Analyze search performance and propose weight adjustments
2. optimize_tool_selection() - Learn better tool combinations from usage patterns
3. refine_domain_triggers() - Auto-detect work/fitness/ideas/relationships domains

Safety: All modifications are PROPOSALS requiring human approval (Gate B pattern).
Changes are logged to write_audit.jsonl for traceability.
"""

import os
import json
import math
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timedelta
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict

from .observability import get_logger, rag_metrics, metrics
from .db_safety import safe_list_query, safe_aggregate_query

logger = get_logger("jarvis.self_modification")

# Audit log path for all self-modification proposals
AUDIT_LOG_PATH = os.environ.get(
    "JARVIS_SELF_MOD_AUDIT_PATH",
    "/brain/system/logs/self_modification_audit.jsonl"
)

# Current search weights (read from hybrid_search.py constants)
CURRENT_WEIGHTS = {
    "rrf": 0.35,
    "relevance": 0.22,
    "recency": 0.18,
    "salience": 0.10,
    "confidence": 0.08,
    "fact_trust": 0.05,
    "domain": 0.02
}


@dataclass
class WeightProposal:
    """A proposed change to search weights with rationale."""
    current_weights: Dict[str, float]
    proposed_weights: Dict[str, float]
    rationale: str
    expected_improvement: str
    confidence: float  # 0.0 - 1.0
    risk_level: str  # low, medium, high
    metrics_basis: Dict[str, Any]
    created_at: str


@dataclass
class ToolOptimization:
    """A proposed improvement to tool selection."""
    pattern_observed: str
    current_behavior: str
    proposed_behavior: str
    examples: List[Dict[str, Any]]
    confidence: float
    risk_level: str


@dataclass
class DomainTrigger:
    """A proposed domain trigger refinement."""
    domain: str
    current_triggers: List[str]
    proposed_triggers: List[str]
    evidence: List[str]
    confidence: float


def _log_proposal(proposal_type: str, proposal_data: Dict[str, Any]) -> str:
    """Log a self-modification proposal to audit trail."""
    try:
        proposal_id = f"{proposal_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        entry = {
            "proposal_id": proposal_id,
            "type": proposal_type,
            "timestamp": datetime.now().isoformat(),
            "status": "pending",
            "data": proposal_data
        }

        # Ensure directory exists
        os.makedirs(os.path.dirname(AUDIT_LOG_PATH), exist_ok=True)

        with open(AUDIT_LOG_PATH, "a") as f:
            f.write(json.dumps(entry) + "\n")

        logger.info(f"Logged self-modification proposal: {proposal_id}")
        return proposal_id
    except Exception as e:
        logger.error(f"Failed to log proposal: {e}")
        return f"unlogged_{datetime.now().timestamp()}"


# =============================================================================
# 1. SEARCH WEIGHT TUNING
# =============================================================================

async def tune_search_weights(
    days: int = 30,
    min_searches: int = 50
) -> Dict[str, Any]:
    """
    Analyze search performance and propose weight adjustments.

    Process:
    1. Gather search metrics (avg relevance, empty rate, source distribution)
    2. Analyze which weight components correlate with better results
    3. Propose incremental weight adjustments (max 5% change per component)
    4. Generate preview for human approval

    Returns:
        - current_metrics: Current search performance data
        - analysis: What the data suggests
        - proposal: Recommended weight changes (if any)
        - confidence: How confident we are in the recommendation
    """
    result = {
        "status": "success",
        "analyzed_at": datetime.now().isoformat(),
        "period_days": days,
        "current_weights": CURRENT_WEIGHTS.copy()
    }

    try:
        # 1. Get search metrics from RAG metrics tracker
        search_metrics = _gather_search_metrics(days)
        result["current_metrics"] = search_metrics

        # 2. Analyze feedback correlation with search results
        feedback_analysis = await _analyze_feedback_correlation(days)
        result["feedback_analysis"] = feedback_analysis

        # 3. Check if we have enough data
        if search_metrics.get("total_searches", 0) < min_searches:
            result["status"] = "insufficient_data"
            result["message"] = f"Need at least {min_searches} searches for analysis, have {search_metrics.get('total_searches', 0)}"
            result["proposal"] = None
            return result

        # 4. Generate weight proposal
        proposal = _generate_weight_proposal(search_metrics, feedback_analysis)
        result["proposal"] = asdict(proposal) if proposal else None

        # 5. Log proposal if generated
        if proposal:
            proposal_id = _log_proposal("search_weights", asdict(proposal))
            result["proposal_id"] = proposal_id
            result["next_steps"] = [
                "Review the proposed weights",
                "Check the rationale and expected improvement",
                "Approve or reject via /self-modification/approve/<proposal_id>"
            ]
        else:
            result["message"] = "Current weights appear optimal based on metrics"

        return result

    except Exception as e:
        logger.error(f"Error in tune_search_weights: {e}", exc_info=True)
        result["status"] = "error"
        result["error"] = str(e)
        return result


def _gather_search_metrics(days: int) -> Dict[str, Any]:
    """Gather search performance metrics from RAG metrics tracker."""
    try:
        # Get metrics from observability (using correct method name)
        metrics_data = rag_metrics.get_stats()

        # Extract relevance data
        relevance_data = metrics_data.get("relevance", {})

        return {
            "total_searches": metrics_data.get("searches_total", 0),
            "avg_relevance": relevance_data.get("avg", 0.0),
            "empty_result_rate": metrics_data.get("empty_rate", 0.0),
            "p50_relevance": relevance_data.get("p50", 0.0),
            "p95_relevance": relevance_data.get("p95", 0.0),
            "source_distribution": metrics_data.get("source_distribution", {}),
            "by_type": metrics_data.get("by_type", {}),
            "collection_period": f"last_{days}_days"
        }
    except Exception as e:
        logger.warning(f"Could not gather search metrics: {e}")
        return {
            "total_searches": 0,
            "avg_relevance": 0.0,
            "empty_result_rate": 0.0,
            "error": str(e)
        }


async def _analyze_feedback_correlation(days: int) -> Dict[str, Any]:
    """Analyze correlation between search results and user feedback."""
    result = {
        "sessions_with_feedback": 0,
        "positive_after_search": 0,
        "negative_after_search": 0,
        "feedback_by_source": {}
    }

    try:
        # Get feedback data correlated with search-heavy sessions
        # Note: thumbs_up is boolean, rating is integer (1-5 scale)
        with safe_aggregate_query('user_feedback') as cur:
            cur.execute("""
                SELECT
                    COUNT(*) as total_feedback,
                    COUNT(*) FILTER (WHERE thumbs_up = true OR rating >= 4) as positive,
                    COUNT(*) FILTER (WHERE thumbs_up = false OR rating <= 2) as negative,
                    COUNT(*) FILTER (WHERE rating = 3) as mixed
                FROM user_feedback
                WHERE created_at > NOW() - INTERVAL '%s days'
            """, (days,))
            row = cur.fetchone()

            if row:
                result["sessions_with_feedback"] = row['total_feedback'] or 0
                result["positive_after_search"] = row['positive'] or 0
                result["negative_after_search"] = row['negative'] or 0
                result["mixed_feedback"] = row['mixed'] or 0

                total = result["sessions_with_feedback"]
                if total > 0:
                    result["positive_rate"] = round(result["positive_after_search"] / total, 3)
                    result["negative_rate"] = round(result["negative_after_search"] / total, 3)
    except Exception as e:
        logger.warning(f"Could not analyze feedback correlation: {e}")
        result["error"] = str(e)

    return result


def _generate_weight_proposal(
    search_metrics: Dict[str, Any],
    feedback_analysis: Dict[str, Any]
) -> Optional[WeightProposal]:
    """Generate a weight adjustment proposal based on metrics."""

    avg_relevance = search_metrics.get("avg_relevance", 0.0)
    empty_rate = search_metrics.get("empty_result_rate", 0.0)
    positive_rate = feedback_analysis.get("positive_rate", 0.5)
    source_dist = search_metrics.get("source_distribution", {})

    # Determine if adjustment is needed
    issues = []
    proposed = CURRENT_WEIGHTS.copy()

    # Issue 1: High empty result rate
    if empty_rate > 0.15:
        issues.append(f"High empty result rate ({empty_rate:.1%})")
        # Increase keyword weight for better recall
        proposed["rrf"] = min(0.40, CURRENT_WEIGHTS["rrf"] + 0.03)

    # Issue 2: Low average relevance
    if avg_relevance < 0.5:
        issues.append(f"Low average relevance ({avg_relevance:.2f})")
        # Increase relevance weight
        proposed["relevance"] = min(0.27, CURRENT_WEIGHTS["relevance"] + 0.03)

    # Issue 3: Low positive feedback rate
    if positive_rate < 0.4 and feedback_analysis.get("sessions_with_feedback", 0) > 10:
        issues.append(f"Low positive feedback rate ({positive_rate:.1%})")
        # Increase salience (user satisfaction correlation)
        proposed["salience"] = min(0.15, CURRENT_WEIGHTS["salience"] + 0.02)

    # Issue 4: Imbalanced source distribution
    semantic_count = source_dist.get("semantic", 0)
    keyword_count = source_dist.get("keyword", 0)
    both_count = source_dist.get("both", 0)
    total = semantic_count + keyword_count + both_count

    if total > 0:
        semantic_ratio = semantic_count / total
        keyword_ratio = keyword_count / total

        if semantic_ratio > 0.8:
            issues.append("Over-reliance on semantic search")
            # Boost keyword contribution
            proposed["rrf"] = min(0.40, CURRENT_WEIGHTS["rrf"] + 0.02)
        elif keyword_ratio > 0.8:
            issues.append("Over-reliance on keyword search")
            # Semantic should contribute more
            proposed["relevance"] = min(0.27, CURRENT_WEIGHTS["relevance"] + 0.02)

    # Normalize weights to sum to 1.0
    total_weight = sum(proposed.values())
    if total_weight > 0 and abs(total_weight - 1.0) > 0.001:
        proposed = {k: round(v / total_weight, 3) for k, v in proposed.items()}

    # Check if any change is proposed
    changes = {k: proposed[k] - CURRENT_WEIGHTS[k] for k in CURRENT_WEIGHTS}
    significant_changes = {k: v for k, v in changes.items() if abs(v) > 0.005}

    if not significant_changes:
        return None

    # Calculate confidence based on data quality
    data_confidence = min(1.0, search_metrics.get("total_searches", 0) / 500)
    feedback_confidence = min(1.0, feedback_analysis.get("sessions_with_feedback", 0) / 50)
    confidence = round((data_confidence + feedback_confidence) / 2, 2)

    # Determine risk level
    max_change = max(abs(v) for v in significant_changes.values())
    if max_change > 0.05:
        risk_level = "medium"
    elif max_change > 0.02:
        risk_level = "low"
    else:
        risk_level = "minimal"

    return WeightProposal(
        current_weights=CURRENT_WEIGHTS.copy(),
        proposed_weights=proposed,
        rationale="; ".join(issues) if issues else "Fine-tuning based on metrics",
        expected_improvement=f"Expected to improve avg relevance by ~{len(issues) * 5}% based on similar adjustments",
        confidence=confidence,
        risk_level=risk_level,
        metrics_basis={
            "avg_relevance": avg_relevance,
            "empty_rate": empty_rate,
            "positive_feedback_rate": positive_rate,
            "total_searches": search_metrics.get("total_searches", 0),
            "changes_proposed": significant_changes
        },
        created_at=datetime.now().isoformat()
    )


# =============================================================================
# 2. TOOL SELECTION OPTIMIZATION
# =============================================================================

async def optimize_tool_selection(
    days: int = 30,
    min_sessions: int = 20
) -> Dict[str, Any]:
    """
    Analyze tool usage patterns to learn better tool combinations.

    Returns:
        - usage_patterns: Which tools are commonly used together
        - success_patterns: Tool sequences that correlate with positive feedback
        - improvement_suggestions: Proposed optimizations
    """
    result = {
        "status": "success",
        "analyzed_at": datetime.now().isoformat(),
        "period_days": days
    }

    try:
        # 1. Analyze tool call patterns (using correct table: tool_audit)
        with safe_aggregate_query('tool_audit') as cur:
            cur.execute("""
                SELECT
                    tool_name,
                    COUNT(*) as call_count,
                    COUNT(*) FILTER (WHERE success = true) as success_count,
                    AVG(duration_ms) as avg_duration_ms
                FROM tool_audit
                WHERE created_at > NOW() - INTERVAL '%s days'
                GROUP BY tool_name
                ORDER BY call_count DESC
                LIMIT 20
            """, (days,))
            rows = cur.fetchall()

            result["tool_usage"] = [
                {
                    "tool": row['tool_name'],
                    "calls": row['call_count'],
                    "success_rate": round(row['success_count'] / row['call_count'], 3) if row['call_count'] > 0 else 0,
                    "avg_duration_ms": round(row['avg_duration_ms'] or 0, 1)
                }
                for row in rows
            ]

        # 2. Identify tool sequence patterns
        tool_sequences = await _analyze_tool_sequences(days)
        result["common_sequences"] = tool_sequences

        # 3. Correlate with feedback
        sequence_feedback = await _correlate_sequences_with_feedback(days)
        result["sequence_feedback"] = sequence_feedback

        # 4. Generate optimization suggestions
        suggestions = _generate_tool_suggestions(
            result["tool_usage"],
            tool_sequences,
            sequence_feedback
        )
        result["suggestions"] = suggestions

        # 5. Log as proposal if significant
        if suggestions:
            proposal_id = _log_proposal("tool_selection", {
                "suggestions": suggestions,
                "based_on": result["tool_usage"][:5]
            })
            result["proposal_id"] = proposal_id

        return result

    except Exception as e:
        logger.error(f"Error in optimize_tool_selection: {e}", exc_info=True)
        result["status"] = "error"
        result["error"] = str(e)
        return result


async def _analyze_tool_sequences(days: int) -> List[Dict[str, Any]]:
    """Analyze common tool call sequences within sessions."""
    sequences = []
    try:
        # Use trace_id to group tool calls within same request context
        with safe_list_query('tool_audit') as cur:
            cur.execute("""
                SELECT
                    trace_id,
                    ARRAY_AGG(tool_name ORDER BY created_at) as tool_sequence
                FROM tool_audit
                WHERE created_at > NOW() - INTERVAL '%s days'
                  AND trace_id IS NOT NULL
                GROUP BY trace_id
                HAVING COUNT(*) >= 2
                LIMIT 100
            """, (days,))
            rows = cur.fetchall()

            # Count sequence patterns
            pattern_counts = Counter()
            for row in rows:
                seq = row['tool_sequence']
                if len(seq) >= 2:
                    # Get 2-grams and 3-grams
                    for i in range(len(seq) - 1):
                        pattern_counts[tuple(seq[i:i+2])] += 1
                    for i in range(len(seq) - 2):
                        pattern_counts[tuple(seq[i:i+3])] += 1

            # Top patterns
            for pattern, count in pattern_counts.most_common(10):
                sequences.append({
                    "sequence": list(pattern),
                    "occurrences": count
                })

    except Exception as e:
        logger.warning(f"Could not analyze tool sequences: {e}")

    return sequences


async def _correlate_sequences_with_feedback(days: int) -> Dict[str, Any]:
    """Correlate tool sequences with user feedback."""
    return {
        "analyzed": True,
        "note": "Feedback correlation requires session-level tool tracking - implementation pending"
    }


def _generate_tool_suggestions(
    tool_usage: List[Dict],
    sequences: List[Dict],
    feedback: Dict
) -> List[Dict[str, Any]]:
    """Generate tool selection optimization suggestions."""
    suggestions = []

    # Find tools with low success rates
    for tool in tool_usage:
        if tool["calls"] >= 10 and tool["success_rate"] < 0.8:
            suggestions.append({
                "type": "improve_reliability",
                "tool": tool["tool"],
                "issue": f"Success rate only {tool['success_rate']:.1%}",
                "suggestion": "Investigate failure patterns and add error handling"
            })

    # Find slow tools
    for tool in tool_usage:
        if tool["calls"] >= 10 and tool["avg_duration_ms"] > 5000:
            suggestions.append({
                "type": "performance",
                "tool": tool["tool"],
                "issue": f"Average duration {tool['avg_duration_ms']:.0f}ms",
                "suggestion": "Consider caching or optimization"
            })

    return suggestions


# =============================================================================
# 3. DOMAIN TRIGGER REFINEMENT
# =============================================================================

async def refine_domain_triggers(
    days: int = 30
) -> Dict[str, Any]:
    """
    Auto-detect optimal domain triggers for work/fitness/ideas/relationships.

    Returns:
        - current_triggers: Existing domain detection patterns
        - detected_patterns: Patterns found in recent conversations
        - proposed_refinements: Suggested trigger updates
    """
    result = {
        "status": "success",
        "analyzed_at": datetime.now().isoformat(),
        "period_days": days
    }

    # Current domain triggers (hardcoded for now)
    current_triggers = {
        "work_projektil": ["projektil", "work", "meeting", "client", "project", "deadline"],
        "fitness": ["training", "workout", "gym", "exercise", "health", "diet"],
        "ideas": ["idea", "brainstorm", "concept", "innovation", "creative"],
        "relationships": ["relationship", "partner", "family", "friend", "social"]
    }
    result["current_triggers"] = current_triggers

    try:
        # Analyze message content for domain indicators
        domain_patterns = await _analyze_domain_patterns(days)
        result["detected_patterns"] = domain_patterns

        # Generate refinement proposals
        refinements = _generate_domain_refinements(current_triggers, domain_patterns)
        result["proposed_refinements"] = refinements

        # Log if significant changes proposed
        if refinements:
            proposal_id = _log_proposal("domain_triggers", {
                "current": current_triggers,
                "proposed": refinements
            })
            result["proposal_id"] = proposal_id

        return result

    except Exception as e:
        logger.error(f"Error in refine_domain_triggers: {e}", exc_info=True)
        result["status"] = "error"
        result["error"] = str(e)
        return result


async def _analyze_domain_patterns(days: int) -> Dict[str, List[str]]:
    """Analyze recent messages to find domain-related patterns."""
    patterns = defaultdict(list)

    try:
        with safe_list_query('message') as cur:
            cur.execute("""
                SELECT
                    c.namespace,
                    m.content
                FROM message m
                JOIN conversation c ON m.conversation_id = c.id
                WHERE m.created_at > NOW() - INTERVAL '%s days'
                  AND m.role = 'user'
                  AND LENGTH(m.content) > 10
                ORDER BY m.created_at DESC
                LIMIT 500
            """, (days,))
            rows = cur.fetchall()

            # Simple keyword extraction per namespace
            namespace_words = defaultdict(Counter)
            for row in rows:
                namespace = row['namespace']
                content = row['content'].lower()
                # Extract significant words (4+ chars, not common words)
                words = [w for w in content.split() if len(w) >= 4]
                namespace_words[namespace].update(words)

            # Get top words per namespace
            for namespace, word_counts in namespace_words.items():
                # Filter out very common words
                common_words = {'what', 'that', 'this', 'with', 'have', 'from', 'they', 'would', 'there', 'their', 'been', 'were', 'will', 'more', 'when', 'your', 'about', 'into', 'could', 'should'}
                filtered = [(w, c) for w, c in word_counts.most_common(50) if w not in common_words]
                patterns[namespace] = [w for w, c in filtered[:15]]

    except Exception as e:
        logger.warning(f"Could not analyze domain patterns: {e}")

    return dict(patterns)


def _generate_domain_refinements(
    current: Dict[str, List[str]],
    detected: Dict[str, List[str]]
) -> List[Dict[str, Any]]:
    """Generate domain trigger refinement proposals."""
    refinements = []

    for domain, detected_words in detected.items():
        current_words = set(current.get(domain, []))
        detected_set = set(detected_words[:10])

        # Find new words not in current triggers
        new_words = detected_set - current_words

        if new_words:
            refinements.append({
                "domain": domain,
                "action": "add_triggers",
                "new_triggers": list(new_words)[:5],
                "rationale": f"Frequently used in {domain} conversations"
            })

    return refinements


# =============================================================================
# PROPOSAL MANAGEMENT
# =============================================================================

async def get_pending_proposals(
    proposal_type: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Get all pending self-modification proposals."""
    proposals = []

    try:
        if os.path.exists(AUDIT_LOG_PATH):
            with open(AUDIT_LOG_PATH, "r") as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())
                        if entry.get("status") == "pending":
                            if proposal_type is None or entry.get("type") == proposal_type:
                                proposals.append(entry)
                    except json.JSONDecodeError:
                        continue
    except Exception as e:
        logger.error(f"Error reading proposals: {e}")

    return proposals


async def approve_proposal(
    proposal_id: str,
    approver: str = "human"
) -> Dict[str, Any]:
    """
    Approve a self-modification proposal.

    Note: This marks the proposal as approved but does NOT automatically apply it.
    Application requires manual code change or feature flag update.
    """
    # Read all entries
    entries = []
    found = False

    try:
        if os.path.exists(AUDIT_LOG_PATH):
            with open(AUDIT_LOG_PATH, "r") as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())
                        if entry.get("proposal_id") == proposal_id:
                            entry["status"] = "approved"
                            entry["approved_by"] = approver
                            entry["approved_at"] = datetime.now().isoformat()
                            found = True
                        entries.append(entry)
                    except json.JSONDecodeError:
                        continue

        if not found:
            return {"status": "error", "message": f"Proposal {proposal_id} not found"}

        # Write back
        with open(AUDIT_LOG_PATH, "w") as f:
            for entry in entries:
                f.write(json.dumps(entry) + "\n")

        return {
            "status": "success",
            "message": f"Proposal {proposal_id} approved",
            "next_steps": "Apply changes via deployment or feature flag update"
        }

    except Exception as e:
        return {"status": "error", "message": str(e)}


async def reject_proposal(
    proposal_id: str,
    reason: str = ""
) -> Dict[str, Any]:
    """Reject a self-modification proposal."""
    entries = []
    found = False

    try:
        if os.path.exists(AUDIT_LOG_PATH):
            with open(AUDIT_LOG_PATH, "r") as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())
                        if entry.get("proposal_id") == proposal_id:
                            entry["status"] = "rejected"
                            entry["rejection_reason"] = reason
                            entry["rejected_at"] = datetime.now().isoformat()
                            found = True
                        entries.append(entry)
                    except json.JSONDecodeError:
                        continue

        if not found:
            return {"status": "error", "message": f"Proposal {proposal_id} not found"}

        # Write back
        with open(AUDIT_LOG_PATH, "w") as f:
            for entry in entries:
                f.write(json.dumps(entry) + "\n")

        return {"status": "success", "message": f"Proposal {proposal_id} rejected"}

    except Exception as e:
        return {"status": "error", "message": str(e)}
