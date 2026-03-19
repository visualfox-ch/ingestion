"""
Self-Reflection Service - Phase A1 (AGI Evolution)

Implements the Reflexion pattern (Shinn et al. 2023):
Query -> Execute -> Evaluate -> Reflect -> Learn
                      ^________________________|

Core components:
1. EvaluationModule - Score responses against critique rules
2. ReflectionGenerator - Generate improvement suggestions
3. LearningExtractor - Extract concrete learnings
4. ImprovementTracker - Track progress over time
"""

import hashlib
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Singleton instance
_reflection_service = None


def get_reflection_service():
    """Get singleton instance of ReflectionService."""
    global _reflection_service
    if _reflection_service is None:
        _reflection_service = ReflectionService()
    return _reflection_service


class ReflectionService:
    """
    Self-Reflection Engine for continuous self-improvement.

    Based on Reflexion (Shinn et al. 2023) - uses verbal reinforcement
    learning to improve responses over time.
    """

    def __init__(self):
        self.logger = logging.getLogger(self.__class__.__name__)

    # ==================== EVALUATION MODULE ====================

    def evaluate_response(
        self,
        query: str,
        response: str,
        tool_calls: List[Dict] = None,
        session_id: str = None,
        context: Dict = None
    ) -> Dict[str, Any]:
        """
        Evaluate a response against self-critique rules.

        Args:
            query: The original query
            response: The generated response
            tool_calls: List of tools that were called
            session_id: Current session ID
            context: Additional context (user info, etc.)

        Returns:
            Dict with evaluation scores and overall quality
        """
        try:
            from app.postgres_state import get_dict_cursor

            # Get active critique rules
            rules = self._get_active_rules(context)

            if not rules:
                return {
                    "success": True,
                    "quality_score": 0.7,  # Default neutral score
                    "critique_scores": {},
                    "message": "No critique rules configured"
                }

            # Evaluate against each rule
            critique_scores = {}
            weighted_sum = 0.0
            weight_total = 0.0

            for rule in rules:
                # Check if rule applies to this context
                if not self._rule_applies(rule, query, response, tool_calls, context):
                    continue

                # Get score for this rule
                score = self._evaluate_rule(rule, query, response, tool_calls, context)
                critique_scores[rule["rule_name"]] = {
                    "score": score,
                    "category": rule["rule_category"],
                    "weight": rule["weight"],
                    "threshold": rule["min_score_threshold"]
                }

                weighted_sum += score * rule["weight"]
                weight_total += rule["weight"]

            # Calculate overall quality
            quality_score = weighted_sum / weight_total if weight_total > 0 else 0.7

            # Identify rules that need reflection (below threshold)
            needs_reflection = [
                name for name, data in critique_scores.items()
                if data["score"] < data["threshold"]
            ]

            # Log to database
            query_hash = hashlib.sha256(query.encode()).hexdigest()[:64]
            reflection_id = self._log_evaluation(
                session_id=session_id,
                query_hash=query_hash,
                query_summary=query[:500],
                quality_score=quality_score,
                critique_scores=critique_scores
            )

            return {
                "success": True,
                "reflection_id": reflection_id,
                "quality_score": round(quality_score, 3),
                "critique_scores": critique_scores,
                "needs_reflection": needs_reflection,
                "rules_evaluated": len(critique_scores)
            }

        except Exception as e:
            self.logger.error(f"Evaluate response failed: {e}")
            return {"success": False, "error": str(e)}

    def _get_active_rules(self, context: Dict = None) -> List[Dict]:
        """Get active critique rules from database."""
        try:
            from app.postgres_state import get_dict_cursor

            with get_dict_cursor() as cur:
                cur.execute("""
                    SELECT rule_name, rule_category, rule_condition,
                           critique_prompt, weight, min_score_threshold, examples
                    FROM self_critique_rules
                    WHERE is_active = TRUE
                    ORDER BY weight DESC
                """)
                rows = cur.fetchall()

            return [
                {
                    "rule_name": r["rule_name"],
                    "rule_category": r["rule_category"],
                    "rule_condition": r["rule_condition"],
                    "critique_prompt": r["critique_prompt"],
                    "weight": r["weight"],
                    "min_score_threshold": r["min_score_threshold"],
                    "examples": r["examples"] or []
                }
                for r in rows
            ]
        except Exception as e:
            self.logger.warning(f"Failed to get critique rules: {e}")
            return []

    def _rule_applies(
        self,
        rule: Dict,
        query: str,
        response: str,
        tool_calls: List[Dict],
        context: Dict
    ) -> bool:
        """Check if a rule applies to this interaction."""
        condition = rule.get("rule_condition", "all")

        if condition == "all":
            return True
        elif condition == "tool_call":
            return bool(tool_calls)
        elif condition == "personal_info":
            # Simple check for personal info keywords
            personal_keywords = ["password", "secret", "private", "personal", "account"]
            text = f"{query} {response}".lower()
            return any(kw in text for kw in personal_keywords)
        else:
            # Custom condition - check if keyword in query
            return condition.lower() in query.lower()

    def _evaluate_rule(
        self,
        rule: Dict,
        query: str,
        response: str,
        tool_calls: List[Dict],
        context: Dict
    ) -> float:
        """
        Evaluate a single rule.

        For now, uses heuristic scoring. Future: LLM-based evaluation.
        """
        rule_name = rule["rule_name"]

        # Heuristic evaluations (to be enhanced with LLM later)
        if rule_name == "conciseness":
            # Penalize very long responses
            response_len = len(response)
            if response_len < 500:
                return 1.0
            elif response_len < 1500:
                return 0.8
            elif response_len < 3000:
                return 0.6
            else:
                return 0.4

        elif rule_name == "tool_efficiency":
            # Check for redundant tool calls
            if not tool_calls:
                return 1.0
            tool_names = [tc.get("name") for tc in tool_calls]
            unique_ratio = len(set(tool_names)) / len(tool_names)
            return min(1.0, unique_ratio + 0.2)

        elif rule_name == "clarity":
            # Simple clarity heuristics
            avg_sentence_len = len(response.split()) / max(1, response.count('.') + response.count('?') + response.count('!'))
            if avg_sentence_len < 25:
                return 0.9
            elif avg_sentence_len < 40:
                return 0.7
            else:
                return 0.5

        elif rule_name == "relevance":
            # Check keyword overlap
            query_words = set(query.lower().split())
            response_words = set(response.lower().split())
            overlap = len(query_words & response_words) / max(1, len(query_words))
            return min(1.0, overlap * 2)

        elif rule_name == "safety_check":
            # Basic safety check
            unsafe_patterns = ["hack", "exploit", "illegal", "weapon"]
            text = response.lower()
            if any(p in text for p in unsafe_patterns):
                return 0.3
            return 1.0

        else:
            # Default: assume good unless proven otherwise
            return 0.75

    def _log_evaluation(
        self,
        session_id: str,
        query_hash: str,
        query_summary: str,
        quality_score: float,
        critique_scores: Dict
    ) -> Optional[int]:
        """Log evaluation to database."""
        try:
            from app.postgres_state import get_dict_cursor
            import json

            with get_dict_cursor() as cur:
                cur.execute("""
                    INSERT INTO reflection_log
                    (session_id, query_hash, query_summary, response_quality, critique_scores)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                """, (session_id, query_hash, query_summary, quality_score, json.dumps(critique_scores)))

                result = cur.fetchone()
                return result["id"] if result else None

        except Exception as e:
            self.logger.warning(f"Failed to log evaluation: {e}")
            return None

    # ==================== REFLECTION GENERATOR ====================

    def generate_reflection(
        self,
        reflection_id: int,
        query: str,
        response: str,
        critique_scores: Dict
    ) -> Dict[str, Any]:
        """
        Generate reflection on low-scoring areas.

        Asks: "What could have been better?"

        Args:
            reflection_id: ID of the evaluation log
            query: Original query
            response: Generated response
            critique_scores: Scores from evaluation

        Returns:
            Dict with reflection text and improvement suggestions
        """
        try:
            # Find low-scoring rules
            low_scores = {
                name: data for name, data in critique_scores.items()
                if data["score"] < data.get("threshold", 0.5)
            }

            if not low_scores:
                return {
                    "success": True,
                    "reflection": "Response met all quality criteria.",
                    "improvements": [],
                    "needs_action": False
                }

            # Generate reflection for each low-scoring area
            reflection_parts = []
            improvements = []

            for rule_name, data in low_scores.items():
                category = data["category"]
                score = data["score"]

                # Generate specific reflection
                reflection_text, improvement = self._reflect_on_rule(
                    rule_name, category, score, query, response
                )

                if reflection_text:
                    reflection_parts.append(reflection_text)
                if improvement:
                    improvements.append(improvement)

            # Combine reflections
            full_reflection = "\n".join(reflection_parts)

            # Update database
            self._save_reflection(reflection_id, full_reflection, improvements)

            return {
                "success": True,
                "reflection": full_reflection,
                "improvements": improvements,
                "needs_action": len(improvements) > 0,
                "low_scoring_areas": list(low_scores.keys())
            }

        except Exception as e:
            self.logger.error(f"Generate reflection failed: {e}")
            return {"success": False, "error": str(e)}

    def _reflect_on_rule(
        self,
        rule_name: str,
        category: str,
        score: float,
        query: str,
        response: str
    ) -> tuple:
        """Generate reflection and improvement for a specific rule."""

        reflection_templates = {
            "conciseness": (
                f"Response was too verbose (score: {score:.2f}). Could have been more concise.",
                {"type": "style", "description": "Reduce verbosity in responses",
                 "action": "Focus on key points, remove redundant explanations", "priority": "medium"}
            ),
            "tool_efficiency": (
                f"Tool usage could be more efficient (score: {score:.2f}). Potential redundant calls.",
                {"type": "tool_usage", "description": "Optimize tool call patterns",
                 "action": "Combine related queries, avoid duplicate calls", "priority": "medium"}
            ),
            "clarity": (
                f"Response clarity could improve (score: {score:.2f}). Sentences may be too complex.",
                {"type": "style", "description": "Improve response clarity",
                 "action": "Use shorter sentences, clearer structure", "priority": "low"}
            ),
            "relevance": (
                f"Response relevance lower than expected (score: {score:.2f}). May have drifted from topic.",
                {"type": "reasoning", "description": "Stay focused on user's actual question",
                 "action": "Re-read query before responding, check alignment", "priority": "high"}
            ),
            "task_completion": (
                f"Task may not be fully completed (score: {score:.2f}). User request might be partially addressed.",
                {"type": "reasoning", "description": "Ensure complete task fulfillment",
                 "action": "Verify all parts of request are addressed", "priority": "high"}
            ),
            "factual_accuracy": (
                f"Potential accuracy concerns (score: {score:.2f}). Should verify facts.",
                {"type": "knowledge_gap", "description": "Verify factual claims",
                 "action": "Cross-check facts, acknowledge uncertainty", "priority": "critical"}
            ),
            "safety_check": (
                f"Safety concern detected (score: {score:.2f}). Review response for inappropriate content.",
                {"type": "reasoning", "description": "Review safety of response",
                 "action": "Check for harmful or inappropriate content", "priority": "critical"}
            )
        }

        if rule_name in reflection_templates:
            return reflection_templates[rule_name]

        # Default reflection
        return (
            f"Area '{rule_name}' ({category}) scored {score:.2f}, below threshold.",
            {"type": category, "description": f"Improve {rule_name}",
             "action": f"Review and improve {rule_name} in future responses", "priority": "medium"}
        )

    def _save_reflection(
        self,
        reflection_id: int,
        reflection: str,
        improvements: List[Dict]
    ):
        """Save reflection and improvements to database."""
        try:
            from app.postgres_state import get_dict_cursor
            import json

            with get_dict_cursor() as cur:
                # Update reflection log
                cur.execute("""
                    UPDATE reflection_log
                    SET reflection = %s, improvements_identified = %s, updated_at = NOW()
                    WHERE id = %s
                """, (reflection, json.dumps(improvements), reflection_id))

                # Insert improvements
                for imp in improvements:
                    cur.execute("""
                        INSERT INTO reflection_improvements
                        (reflection_id, improvement_type, description, action_required, priority)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (
                        reflection_id,
                        imp.get("type", "general"),
                        imp.get("description", ""),
                        imp.get("action", ""),
                        imp.get("priority", "medium")
                    ))

        except Exception as e:
            self.logger.warning(f"Failed to save reflection: {e}")

    # ==================== LEARNING EXTRACTOR ====================

    def extract_learnings(
        self,
        days: int = 7,
        min_occurrences: int = 2
    ) -> Dict[str, Any]:
        """
        Extract learnings from accumulated reflections.

        Finds recurring improvement patterns to turn into actionable learnings.

        Args:
            days: Days to look back
            min_occurrences: Minimum times a pattern must occur

        Returns:
            Dict with extracted learnings
        """
        try:
            from app.postgres_state import get_dict_cursor

            with get_dict_cursor() as cur:
                # Get improvement patterns
                cur.execute("""
                    SELECT improvement_type, description, action_required, COUNT(*) as occurrences,
                           AVG(CASE WHEN outcome_verified THEN outcome_score ELSE NULL END) as avg_outcome
                    FROM reflection_improvements
                    WHERE created_at > NOW() - INTERVAL '%s days'
                    GROUP BY improvement_type, description, action_required
                    HAVING COUNT(*) >= %s
                    ORDER BY occurrences DESC
                    LIMIT 20
                """, (days, min_occurrences))

                patterns = cur.fetchall()

            learnings = []
            for p in patterns:
                learnings.append({
                    "type": p["improvement_type"],
                    "pattern": p["description"],
                    "action": p["action_required"],
                    "occurrences": p["occurrences"],
                    "avg_outcome": round(p["avg_outcome"], 2) if p["avg_outcome"] else None,
                    "status": "recurring" if p["occurrences"] >= 5 else "emerging"
                })

            # Categorize learnings
            categorized = {}
            for learning in learnings:
                cat = learning["type"]
                if cat not in categorized:
                    categorized[cat] = []
                categorized[cat].append(learning)

            return {
                "success": True,
                "period_days": days,
                "total_learnings": len(learnings),
                "learnings": learnings,
                "by_category": categorized,
                "top_priority": [l for l in learnings if l["occurrences"] >= 5][:3]
            }

        except Exception as e:
            self.logger.error(f"Extract learnings failed: {e}")
            return {"success": False, "error": str(e)}

    # ==================== IMPROVEMENT TRACKER ====================

    def get_improvement_metrics(
        self,
        days: int = 30
    ) -> Dict[str, Any]:
        """
        Get metrics on improvement over time.

        Tracks quality scores, rule compliance, and improvement rates.
        """
        try:
            from app.postgres_state import get_dict_cursor

            with get_dict_cursor() as cur:
                # Overall quality trend
                cur.execute("""
                    SELECT DATE(created_at) as day,
                           AVG(response_quality) as avg_quality,
                           COUNT(*) as evaluations
                    FROM reflection_log
                    WHERE created_at > NOW() - INTERVAL '%s days'
                    GROUP BY DATE(created_at)
                    ORDER BY day
                """, (days,))

                daily_quality = [
                    {"date": str(r["day"]), "avg_quality": round(r["avg_quality"], 3), "evaluations": r["evaluations"]}
                    for r in cur.fetchall()
                ]

                # Improvement application rate
                cur.execute("""
                    SELECT
                        COUNT(*) FILTER (WHERE status = 'applied') as applied,
                        COUNT(*) FILTER (WHERE status = 'dismissed') as dismissed,
                        COUNT(*) FILTER (WHERE status = 'pending') as pending,
                        COUNT(*) as total
                    FROM reflection_improvements
                    WHERE created_at > NOW() - INTERVAL '%s days'
                """, (days,))

                improvement_stats = cur.fetchone()

                # Category breakdown
                cur.execute("""
                    SELECT improvement_type, COUNT(*),
                           AVG(CASE WHEN outcome_verified THEN outcome_score ELSE NULL END)
                    FROM reflection_improvements
                    WHERE created_at > NOW() - INTERVAL '%s days'
                    GROUP BY improvement_type
                    ORDER BY COUNT(*) DESC
                """, (days,))

                by_category = [
                    {"type": r["improvement_type"], "count": r["count"], "avg_outcome": round(r["avg"]) if r["avg"] else None}
                    for r in cur.fetchall()
                ]

            # Calculate trends
            if len(daily_quality) >= 2:
                first_half = daily_quality[:len(daily_quality)//2]
                second_half = daily_quality[len(daily_quality)//2:]
                first_avg = sum(d["avg_quality"] for d in first_half) / len(first_half)
                second_avg = sum(d["avg_quality"] for d in second_half) / len(second_half)
                trend = "improving" if second_avg > first_avg else "declining" if second_avg < first_avg else "stable"
                trend_delta = round(second_avg - first_avg, 3)
            else:
                trend = "insufficient_data"
                trend_delta = 0

            return {
                "success": True,
                "period_days": days,
                "daily_quality": daily_quality,
                "trend": trend,
                "trend_delta": trend_delta,
                "improvements": {
                    "applied": improvement_stats["applied"] if improvement_stats else 0,
                    "dismissed": improvement_stats["dismissed"] if improvement_stats else 0,
                    "pending": improvement_stats["pending"] if improvement_stats else 0,
                    "total": improvement_stats["total"] if improvement_stats else 0,
                    "application_rate": round(
                        improvement_stats["applied"] / improvement_stats["total"], 2
                    ) if improvement_stats and improvement_stats["total"] > 0 else 0
                },
                "by_category": by_category
            }

        except Exception as e:
            self.logger.error(f"Get improvement metrics failed: {e}")
            return {"success": False, "error": str(e)}

    def apply_improvement(
        self,
        improvement_id: int,
        outcome_score: float = None
    ) -> Dict[str, Any]:
        """Mark an improvement as applied with optional outcome score."""
        try:
            from app.postgres_state import get_dict_cursor

            with get_dict_cursor() as cur:
                cur.execute("""
                    UPDATE reflection_improvements
                    SET status = 'applied', applied_at = NOW(),
                        outcome_verified = %s, outcome_score = %s
                    WHERE id = %s
                    RETURNING improvement_type, description
                """, (
                    outcome_score is not None,
                    outcome_score,
                    improvement_id
                ))

                result = cur.fetchone()

            if result:
                return {
                    "success": True,
                    "improvement_id": improvement_id,
                    "type": result["improvement_type"],
                    "description": result["description"],
                    "outcome_score": outcome_score
                }
            else:
                return {"success": False, "error": "Improvement not found"}

        except Exception as e:
            self.logger.error(f"Apply improvement failed: {e}")
            return {"success": False, "error": str(e)}

    def get_pending_improvements(
        self,
        priority: str = None,
        limit: int = 10
    ) -> Dict[str, Any]:
        """Get pending improvements waiting to be applied."""
        try:
            from app.postgres_state import get_dict_cursor

            query = """
                SELECT ri.id, ri.improvement_type, ri.description, ri.action_required,
                       ri.priority, ri.created_at, rl.query_summary
                FROM reflection_improvements ri
                JOIN reflection_log rl ON ri.reflection_id = rl.id
                WHERE ri.status = 'pending'
            """
            params = []

            if priority:
                query += " AND ri.priority = %s"
                params.append(priority)

            query += " ORDER BY CASE ri.priority WHEN 'critical' THEN 1 WHEN 'high' THEN 2 WHEN 'medium' THEN 3 ELSE 4 END, ri.created_at DESC LIMIT %s"
            params.append(limit)

            with get_dict_cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()

            improvements = [
                {
                    "id": r["id"],
                    "type": r["improvement_type"],
                    "description": r["description"],
                    "action": r["action_required"],
                    "priority": r["priority"],
                    "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                    "query_context": r["query_summary"][:100] if r["query_summary"] else None
                }
                for r in rows
            ]

            return {
                "success": True,
                "pending_count": len(improvements),
                "improvements": improvements
            }

        except Exception as e:
            self.logger.error(f"Get pending improvements failed: {e}")
            return {"success": False, "error": str(e)}

    # ==================== FULL REFLECTION LOOP ====================

    def run_reflection_loop(
        self,
        query: str,
        response: str,
        tool_calls: List[Dict] = None,
        session_id: str = None,
        context: Dict = None,
        auto_extract: bool = True
    ) -> Dict[str, Any]:
        """
        Run the full reflection loop on an interaction.

        Complete Reflexion pattern:
        1. Evaluate response quality
        2. Generate reflection if needed
        3. Extract learnings (if auto_extract)

        Args:
            query: Original query
            response: Generated response
            tool_calls: Tools that were called
            session_id: Session ID
            context: Additional context
            auto_extract: Whether to extract learnings automatically

        Returns:
            Dict with evaluation, reflection, and learnings
        """
        # Step 1: Evaluate
        evaluation = self.evaluate_response(
            query=query,
            response=response,
            tool_calls=tool_calls,
            session_id=session_id,
            context=context
        )

        if not evaluation.get("success"):
            return evaluation

        result = {
            "success": True,
            "evaluation": evaluation,
            "reflection": None,
            "learnings_extracted": False
        }

        # Step 2: Generate reflection if needed
        if evaluation.get("needs_reflection"):
            reflection = self.generate_reflection(
                reflection_id=evaluation.get("reflection_id"),
                query=query,
                response=response,
                critique_scores=evaluation.get("critique_scores", {})
            )
            result["reflection"] = reflection

        # Step 3: Extract learnings periodically
        if auto_extract and evaluation.get("reflection_id") and evaluation["reflection_id"] % 10 == 0:
            learnings = self.extract_learnings(days=7, min_occurrences=2)
            if learnings.get("total_learnings", 0) > 0:
                result["learnings_extracted"] = True
                result["learning_summary"] = f"{learnings['total_learnings']} patterns found"

        return result

    # ==================== CRITIQUE RULE MANAGEMENT ====================

    def add_critique_rule(
        self,
        rule_name: str,
        rule_category: str,
        critique_prompt: str,
        rule_condition: str = "all",
        weight: float = 1.0,
        min_score_threshold: float = 0.5,
        examples: List[Dict] = None
    ) -> Dict[str, Any]:
        """Add or update a self-critique rule."""
        try:
            from app.postgres_state import get_dict_cursor
            import json

            with get_dict_cursor() as cur:
                cur.execute("""
                    INSERT INTO self_critique_rules
                    (rule_name, rule_category, rule_condition, critique_prompt, weight, min_score_threshold, examples)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (rule_name) DO UPDATE SET
                        rule_category = EXCLUDED.rule_category,
                        rule_condition = EXCLUDED.rule_condition,
                        critique_prompt = EXCLUDED.critique_prompt,
                        weight = EXCLUDED.weight,
                        min_score_threshold = EXCLUDED.min_score_threshold,
                        examples = EXCLUDED.examples
                    RETURNING id
                """, (
                    rule_name, rule_category, rule_condition, critique_prompt,
                    weight, min_score_threshold, json.dumps(examples or [])
                ))

                result = cur.fetchone()

            return {
                "success": True,
                "rule_id": result[0] if result else None,
                "rule_name": rule_name,
                "message": f"Critique rule '{rule_name}' saved"
            }

        except Exception as e:
            self.logger.error(f"Add critique rule failed: {e}")
            return {"success": False, "error": str(e)}

    def get_critique_rules(
        self,
        category: str = None,
        active_only: bool = True
    ) -> Dict[str, Any]:
        """Get all critique rules."""
        try:
            from app.postgres_state import get_dict_cursor

            query = "SELECT * FROM self_critique_rules WHERE 1=1"
            params = []

            if active_only:
                query += " AND is_active = TRUE"
            if category:
                query += " AND rule_category = %s"
                params.append(category)

            query += " ORDER BY weight DESC"

            with get_dict_cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()

            # RealDictCursor already returns dict-like rows
            rules = [dict(row) for row in rows]

            return {
                "success": True,
                "rule_count": len(rules),
                "rules": rules
            }

        except Exception as e:
            self.logger.error(f"Get critique rules failed: {e}")
            return {"success": False, "error": str(e)}
