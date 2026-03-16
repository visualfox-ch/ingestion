"""
Quality Scoring Pipeline

Inspired by ClawWork: Automatic quality evaluation of all Jarvis outputs.
Uses LLM-based rubric scoring to ensure high-quality deliverables.

Features:
- Task-specific scoring rubrics
- Multi-dimensional quality assessment
- Feedback loop for improvement
- Historical quality tracking
"""

import logging
import os
import sqlite3
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from threading import Lock

logger = logging.getLogger(__name__)


# =============================================================================
# Quality Models
# =============================================================================

class TaskType(str, Enum):
    """Types of tasks for quality assessment."""
    QUESTION_ANSWER = "question_answer"
    CODE_GENERATION = "code_generation"
    ANALYSIS = "analysis"
    SUMMARY = "summary"
    CREATIVE = "creative"
    PLANNING = "planning"
    PROBLEM_SOLVING = "problem_solving"
    RESEARCH = "research"


class QualityDimension(str, Enum):
    """Dimensions of quality to assess."""
    ACCURACY = "accuracy"  # Factually correct
    COMPLETENESS = "completeness"  # Fully addresses request
    CLARITY = "clarity"  # Easy to understand
    RELEVANCE = "relevance"  # Addresses the actual question
    ACTIONABILITY = "actionability"  # Can be acted upon
    EFFICIENCY = "efficiency"  # Concise, no fluff
    CREATIVITY = "creativity"  # Novel/innovative approach
    SAFETY = "safety"  # No harmful content


@dataclass
class QualityScore:
    """Quality assessment result."""
    task_id: str
    task_type: TaskType
    timestamp: datetime
    overall_score: float  # 0-1
    dimension_scores: Dict[QualityDimension, float]
    strengths: List[str]
    improvements: List[str]
    feedback: str
    evaluator: str  # "llm", "heuristic", "user"
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class QualityRubric:
    """Scoring rubric for a task type."""
    task_type: TaskType
    dimensions: List[QualityDimension]
    weights: Dict[QualityDimension, float]
    criteria: Dict[QualityDimension, str]


# =============================================================================
# Default Rubrics
# =============================================================================

DEFAULT_RUBRICS = {
    TaskType.QUESTION_ANSWER: QualityRubric(
        task_type=TaskType.QUESTION_ANSWER,
        dimensions=[
            QualityDimension.ACCURACY,
            QualityDimension.COMPLETENESS,
            QualityDimension.CLARITY,
            QualityDimension.RELEVANCE,
        ],
        weights={
            QualityDimension.ACCURACY: 0.35,
            QualityDimension.COMPLETENESS: 0.25,
            QualityDimension.CLARITY: 0.20,
            QualityDimension.RELEVANCE: 0.20,
        },
        criteria={
            QualityDimension.ACCURACY: "Information is factually correct and verifiable",
            QualityDimension.COMPLETENESS: "Answer fully addresses all parts of the question",
            QualityDimension.CLARITY: "Response is clear, well-structured, and easy to understand",
            QualityDimension.RELEVANCE: "Answer directly addresses what was asked",
        }
    ),
    TaskType.CODE_GENERATION: QualityRubric(
        task_type=TaskType.CODE_GENERATION,
        dimensions=[
            QualityDimension.ACCURACY,
            QualityDimension.COMPLETENESS,
            QualityDimension.EFFICIENCY,
            QualityDimension.SAFETY,
        ],
        weights={
            QualityDimension.ACCURACY: 0.35,
            QualityDimension.COMPLETENESS: 0.25,
            QualityDimension.EFFICIENCY: 0.20,
            QualityDimension.SAFETY: 0.20,
        },
        criteria={
            QualityDimension.ACCURACY: "Code is syntactically correct and would execute properly",
            QualityDimension.COMPLETENESS: "Code handles all specified requirements and edge cases",
            QualityDimension.EFFICIENCY: "Code is performant and follows best practices",
            QualityDimension.SAFETY: "Code has no security vulnerabilities or unsafe patterns",
        }
    ),
    TaskType.ANALYSIS: QualityRubric(
        task_type=TaskType.ANALYSIS,
        dimensions=[
            QualityDimension.ACCURACY,
            QualityDimension.COMPLETENESS,
            QualityDimension.CLARITY,
            QualityDimension.ACTIONABILITY,
        ],
        weights={
            QualityDimension.ACCURACY: 0.30,
            QualityDimension.COMPLETENESS: 0.25,
            QualityDimension.CLARITY: 0.20,
            QualityDimension.ACTIONABILITY: 0.25,
        },
        criteria={
            QualityDimension.ACCURACY: "Analysis is based on correct data and sound reasoning",
            QualityDimension.COMPLETENESS: "Analysis covers all relevant aspects",
            QualityDimension.CLARITY: "Findings are presented clearly with supporting evidence",
            QualityDimension.ACTIONABILITY: "Analysis leads to clear, actionable insights",
        }
    ),
    TaskType.CREATIVE: QualityRubric(
        task_type=TaskType.CREATIVE,
        dimensions=[
            QualityDimension.CREATIVITY,
            QualityDimension.RELEVANCE,
            QualityDimension.CLARITY,
            QualityDimension.COMPLETENESS,
        ],
        weights={
            QualityDimension.CREATIVITY: 0.35,
            QualityDimension.RELEVANCE: 0.25,
            QualityDimension.CLARITY: 0.20,
            QualityDimension.COMPLETENESS: 0.20,
        },
        criteria={
            QualityDimension.CREATIVITY: "Response shows originality and innovative thinking",
            QualityDimension.RELEVANCE: "Creative output matches the requested style/tone/purpose",
            QualityDimension.CLARITY: "Output is well-crafted and professionally presented",
            QualityDimension.COMPLETENESS: "All creative requirements are fulfilled",
        }
    ),
}


# =============================================================================
# Quality Scorer
# =============================================================================

class QualityScorer:
    """
    Evaluates quality of Jarvis outputs.

    Uses a combination of:
    - LLM-based evaluation (for complex assessment)
    - Heuristic checks (for fast, simple checks)
    - User feedback integration
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or os.environ.get(
            "JARVIS_QUALITY_DB",
            "/brain/system/data/jarvis_quality.db"
        )
        self._lock = Lock()
        self.rubrics = DEFAULT_RUBRICS.copy()
        self._init_db()

    def _init_db(self):
        """Initialize database tables."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS quality_scores (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    overall_score REAL NOT NULL,
                    dimension_scores TEXT NOT NULL,
                    strengths TEXT,
                    improvements TEXT,
                    feedback TEXT,
                    evaluator TEXT NOT NULL,
                    metadata TEXT
                );

                CREATE TABLE IF NOT EXISTS quality_trends (
                    date TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    avg_score REAL NOT NULL,
                    score_count INTEGER NOT NULL,
                    PRIMARY KEY (date, task_type)
                );

                CREATE TABLE IF NOT EXISTS improvement_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    dimension TEXT NOT NULL,
                    issue TEXT NOT NULL,
                    action_taken TEXT,
                    result TEXT,
                    score_before REAL,
                    score_after REAL
                );

                CREATE INDEX IF NOT EXISTS idx_scores_task_id ON quality_scores(task_id);
                CREATE INDEX IF NOT EXISTS idx_scores_timestamp ON quality_scores(timestamp);
                CREATE INDEX IF NOT EXISTS idx_scores_type ON quality_scores(task_type);
            """)

    # -------------------------------------------------------------------------
    # Scoring
    # -------------------------------------------------------------------------

    def score_output(
        self,
        task_id: str,
        task_type: TaskType,
        query: str,
        response: str,
        use_llm: bool = True,
        metadata: Optional[Dict] = None
    ) -> QualityScore:
        """
        Score the quality of an output.

        Args:
            task_id: Unique task identifier
            task_type: Type of task
            query: Original user query
            response: Jarvis response to evaluate
            use_llm: Whether to use LLM for evaluation
            metadata: Additional context

        Returns:
            QualityScore with detailed assessment
        """
        rubric = self.rubrics.get(task_type, DEFAULT_RUBRICS[TaskType.QUESTION_ANSWER])

        if use_llm:
            score = self._llm_evaluate(task_id, task_type, query, response, rubric, metadata)
        else:
            score = self._heuristic_evaluate(task_id, task_type, query, response, rubric, metadata)

        # Persist score
        self._save_score(score)

        # Update trends
        self._update_trends(score)

        return score

    def _heuristic_evaluate(
        self,
        task_id: str,
        task_type: TaskType,
        query: str,
        response: str,
        rubric: QualityRubric,
        metadata: Optional[Dict]
    ) -> QualityScore:
        """Fast heuristic-based evaluation."""
        dimension_scores = {}
        strengths = []
        improvements = []

        # Basic checks
        response_len = len(response)
        query_len = len(query)

        # Completeness: response should be substantial
        if response_len < 50:
            dimension_scores[QualityDimension.COMPLETENESS] = 0.3
            improvements.append("Response is too brief")
        elif response_len < 200:
            dimension_scores[QualityDimension.COMPLETENESS] = 0.6
        else:
            dimension_scores[QualityDimension.COMPLETENESS] = 0.85
            strengths.append("Comprehensive response")

        # Clarity: check for structure
        has_structure = any(marker in response for marker in ["1.", "- ", "* ", "##", "**"])
        if has_structure:
            dimension_scores[QualityDimension.CLARITY] = 0.85
            strengths.append("Well-structured response")
        else:
            dimension_scores[QualityDimension.CLARITY] = 0.65

        # Relevance: check for query terms in response
        query_words = set(query.lower().split())
        response_words = set(response.lower().split())
        overlap = len(query_words & response_words) / max(1, len(query_words))
        dimension_scores[QualityDimension.RELEVANCE] = min(1.0, 0.5 + overlap * 0.5)

        # Accuracy: can't really check without LLM, assume moderate
        dimension_scores[QualityDimension.ACCURACY] = 0.7

        # Fill in other dimensions with defaults
        for dim in rubric.dimensions:
            if dim not in dimension_scores:
                dimension_scores[dim] = 0.7

        # Calculate weighted overall score
        overall = sum(
            dimension_scores.get(dim, 0.7) * rubric.weights.get(dim, 0.25)
            for dim in rubric.dimensions
        )

        return QualityScore(
            task_id=task_id,
            task_type=task_type,
            timestamp=datetime.utcnow(),
            overall_score=round(overall, 3),
            dimension_scores={k: round(v, 3) for k, v in dimension_scores.items()},
            strengths=strengths,
            improvements=improvements,
            feedback="Heuristic evaluation - consider LLM evaluation for detailed feedback",
            evaluator="heuristic",
            metadata=metadata or {},
        )

    def _llm_evaluate(
        self,
        task_id: str,
        task_type: TaskType,
        query: str,
        response: str,
        rubric: QualityRubric,
        metadata: Optional[Dict]
    ) -> QualityScore:
        """LLM-based detailed evaluation."""
        try:
            # Build evaluation prompt
            criteria_text = "\n".join([
                f"- {dim.value}: {rubric.criteria[dim]}"
                for dim in rubric.dimensions
            ])

            eval_prompt = f"""Evaluate this AI assistant response. Score each dimension from 0.0 to 1.0.

ORIGINAL QUERY:
{query}

RESPONSE TO EVALUATE:
{response}

SCORING CRITERIA:
{criteria_text}

Provide your evaluation as JSON:
{{
    "dimension_scores": {{
        {', '.join([f'"{dim.value}": <score 0.0-1.0>' for dim in rubric.dimensions])}
    }},
    "strengths": ["strength 1", "strength 2"],
    "improvements": ["improvement 1", "improvement 2"],
    "feedback": "Brief overall feedback"
}}"""

            # Call LLM for evaluation
            from ..llm_core import call_anthropic_for_chat

            result = call_anthropic_for_chat(
                user_prompt=eval_prompt,
                system_prompt="You are a quality evaluator. Assess AI responses objectively. Return only valid JSON.",
                model="claude-sonnet-4-20250514",
                max_tokens=500,
            )

            # Parse response
            eval_text = result.get("response", "{}")
            # Handle markdown code blocks
            if "```json" in eval_text:
                eval_text = eval_text.split("```json")[1].split("```")[0]
            elif "```" in eval_text:
                eval_text = eval_text.split("```")[1].split("```")[0]

            eval_data = json.loads(eval_text.strip())

            # Extract scores
            dimension_scores = {}
            for dim in rubric.dimensions:
                dim_key = dim.value
                score = eval_data.get("dimension_scores", {}).get(dim_key, 0.7)
                dimension_scores[dim] = min(1.0, max(0.0, float(score)))

            # Calculate overall
            overall = sum(
                dimension_scores.get(dim, 0.7) * rubric.weights.get(dim, 0.25)
                for dim in rubric.dimensions
            )

            return QualityScore(
                task_id=task_id,
                task_type=task_type,
                timestamp=datetime.utcnow(),
                overall_score=round(overall, 3),
                dimension_scores={k: round(v, 3) for k, v in dimension_scores.items()},
                strengths=eval_data.get("strengths", []),
                improvements=eval_data.get("improvements", []),
                feedback=eval_data.get("feedback", ""),
                evaluator="llm",
                metadata=metadata or {},
            )

        except Exception as e:
            logger.warning(f"LLM evaluation failed, falling back to heuristic: {e}")
            return self._heuristic_evaluate(task_id, task_type, query, response, rubric, metadata)

    def _save_score(self, score: QualityScore):
        """Persist quality score."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO quality_scores
                    (task_id, task_type, timestamp, overall_score,
                     dimension_scores, strengths, improvements, feedback, evaluator, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    score.task_id,
                    score.task_type.value,
                    score.timestamp.isoformat(),
                    score.overall_score,
                    json.dumps({k.value: v for k, v in score.dimension_scores.items()}),
                    json.dumps(score.strengths),
                    json.dumps(score.improvements),
                    score.feedback,
                    score.evaluator,
                    json.dumps(score.metadata),
                ))

    def _update_trends(self, score: QualityScore):
        """Update quality trends."""
        date = score.timestamp.strftime("%Y-%m-%d")

        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                # Get current trend
                row = conn.execute("""
                    SELECT avg_score, score_count FROM quality_trends
                    WHERE date = ? AND task_type = ?
                """, (date, score.task_type.value)).fetchone()

                if row:
                    # Update running average
                    old_avg, count = row
                    new_count = count + 1
                    new_avg = (old_avg * count + score.overall_score) / new_count

                    conn.execute("""
                        UPDATE quality_trends
                        SET avg_score = ?, score_count = ?
                        WHERE date = ? AND task_type = ?
                    """, (new_avg, new_count, date, score.task_type.value))
                else:
                    conn.execute("""
                        INSERT INTO quality_trends (date, task_type, avg_score, score_count)
                        VALUES (?, ?, ?, 1)
                    """, (date, score.task_type.value, score.overall_score))

    # -------------------------------------------------------------------------
    # Analysis
    # -------------------------------------------------------------------------

    def get_quality_summary(
        self,
        days: int = 30,
        task_type: Optional[TaskType] = None
    ) -> Dict[str, Any]:
        """Get quality summary for time period."""
        start_date = datetime.utcnow() - timedelta(days=days)

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            # Build query
            query = """
                SELECT
                    task_type,
                    AVG(overall_score) as avg_score,
                    MIN(overall_score) as min_score,
                    MAX(overall_score) as max_score,
                    COUNT(*) as count
                FROM quality_scores
                WHERE timestamp > ?
            """
            params = [start_date.isoformat()]

            if task_type:
                query += " AND task_type = ?"
                params.append(task_type.value)

            query += " GROUP BY task_type"

            rows = conn.execute(query, params).fetchall()

            # Get dimension breakdowns
            dim_query = """
                SELECT dimension_scores FROM quality_scores
                WHERE timestamp > ?
            """
            if task_type:
                dim_query += " AND task_type = ?"

            dim_rows = conn.execute(dim_query, params).fetchall()

        # Aggregate dimension scores
        dimension_averages = {}
        for row in dim_rows:
            scores = json.loads(row["dimension_scores"])
            for dim, score in scores.items():
                if dim not in dimension_averages:
                    dimension_averages[dim] = []
                dimension_averages[dim].append(score)

        dimension_summary = {
            dim: round(sum(scores) / len(scores), 3)
            for dim, scores in dimension_averages.items()
            if scores
        }

        return {
            "days": days,
            "task_type_filter": task_type.value if task_type else None,
            "by_task_type": [
                {
                    "task_type": r["task_type"],
                    "avg_score": round(r["avg_score"], 3),
                    "min_score": round(r["min_score"], 3),
                    "max_score": round(r["max_score"], 3),
                    "count": r["count"],
                }
                for r in rows
            ],
            "dimension_averages": dimension_summary,
            "total_evaluations": sum(r["count"] for r in rows),
        }

    def get_improvement_suggestions(self) -> List[Dict[str, Any]]:
        """Get suggestions for improvement based on quality data."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            # Find dimensions with consistently low scores
            rows = conn.execute("""
                SELECT dimension_scores FROM quality_scores
                WHERE timestamp > datetime('now', '-7 days')
            """).fetchall()

        if not rows:
            return []

        # Aggregate dimension scores
        dimension_scores = {}
        for row in rows:
            scores = json.loads(row["dimension_scores"])
            for dim, score in scores.items():
                if dim not in dimension_scores:
                    dimension_scores[dim] = []
                dimension_scores[dim].append(score)

        suggestions = []
        for dim, scores in dimension_scores.items():
            avg = sum(scores) / len(scores)
            if avg < 0.7:  # Below threshold
                suggestions.append({
                    "dimension": dim,
                    "current_score": round(avg, 3),
                    "target_score": 0.8,
                    "priority": "high" if avg < 0.5 else "medium",
                    "suggestion": self._get_improvement_action(dim, avg),
                })

        return sorted(suggestions, key=lambda x: x["current_score"])

    def _get_improvement_action(self, dimension: str, score: float) -> str:
        """Get improvement action for a dimension."""
        actions = {
            "accuracy": "Review sources, add fact-checking, cite references",
            "completeness": "Ensure all parts of query are addressed, add follow-up questions",
            "clarity": "Use structured formatting, bullet points, clear headings",
            "relevance": "Focus on directly answering the question before elaborating",
            "actionability": "Include specific next steps, concrete recommendations",
            "efficiency": "Remove redundant information, be more concise",
            "creativity": "Explore alternative approaches, add novel perspectives",
            "safety": "Review for sensitive content, add appropriate caveats",
        }
        return actions.get(dimension, "Review and improve this dimension")

    def record_user_feedback(
        self,
        task_id: str,
        user_score: float,
        feedback: str
    ):
        """Record user feedback on a response."""
        score = QualityScore(
            task_id=task_id,
            task_type=TaskType.QUESTION_ANSWER,  # Default
            timestamp=datetime.utcnow(),
            overall_score=user_score,
            dimension_scores={},
            strengths=[],
            improvements=[],
            feedback=feedback,
            evaluator="user",
        )
        self._save_score(score)
        logger.info(f"User feedback recorded for {task_id}: {user_score}")


# =============================================================================
# Global Instance
# =============================================================================

_quality_scorer: Optional[QualityScorer] = None


def get_quality_scorer() -> QualityScorer:
    """Get the global quality scorer instance."""
    global _quality_scorer
    if _quality_scorer is None:
        _quality_scorer = QualityScorer()
    return _quality_scorer
