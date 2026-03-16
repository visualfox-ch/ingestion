"""
Strategic Learning System (Work vs Learn)

Inspired by ClawWork: Implements strategic decision-making between
immediate work (income) and learning (future capability investment).

Core Concept:
- WORK: Complete tasks now for immediate value
- LEARN: Invest in knowledge/skills for future higher-value work

The system tracks:
- Learning investments (time, cost, topics)
- Skill development over time
- ROI of learning investments
- Compound learning effects
"""

import logging
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from threading import Lock
import json

logger = logging.getLogger(__name__)


# =============================================================================
# Learning Models
# =============================================================================

class LearningDomain(str, Enum):
    """Domains Jarvis can learn in."""
    CODING = "coding"
    SYSTEM_ADMIN = "system_admin"
    DATA_ANALYSIS = "data_analysis"
    COMMUNICATION = "communication"
    DOMAIN_KNOWLEDGE = "domain_knowledge"
    TOOL_MASTERY = "tool_mastery"
    USER_PREFERENCES = "user_preferences"
    PROBLEM_SOLVING = "problem_solving"


class ActivityType(str, Enum):
    """Types of activities."""
    WORK = "work"  # Immediate task execution
    LEARN = "learn"  # Knowledge/skill investment
    REFLECT = "reflect"  # Self-evaluation and planning


@dataclass
class LearningInvestment:
    """A learning investment."""
    timestamp: datetime
    domain: LearningDomain
    topic: str
    cost_usd: float  # API cost for learning
    time_seconds: int
    knowledge_gained: str  # What was learned
    confidence: float  # 0-1, how well learned
    source: str  # Where knowledge came from
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Skill:
    """A skill with proficiency tracking."""
    domain: LearningDomain
    name: str
    proficiency: float  # 0-1
    total_investments: int
    total_cost: float
    last_used: datetime
    last_improved: datetime
    applications: int  # Times applied successfully


@dataclass
class StrategicDecision:
    """A work vs learn decision."""
    timestamp: datetime
    decision: ActivityType
    reasoning: str
    context: Dict[str, Any]
    expected_value: float
    expected_learning: float
    economic_state: Dict[str, Any]


# =============================================================================
# Strategic Learner
# =============================================================================

class StrategicLearner:
    """
    Manages strategic work vs learn decisions.

    Implements compound learning: early investments in learning
    pay off exponentially through improved future performance.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or os.environ.get(
            "JARVIS_LEARNING_DB",
            "/brain/system/data/jarvis_learning.db"
        )
        self._lock = Lock()
        self._init_db()

        # Learning decay: skills degrade if not used
        self.skill_decay_rate = 0.01  # 1% per week of non-use

        # Learning multiplier: higher skills = faster learning
        self.compound_learning_rate = 1.2  # 20% boost per proficiency level

    def _init_db(self):
        """Initialize database tables."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS learning_investments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    domain TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    cost_usd REAL NOT NULL,
                    time_seconds INTEGER NOT NULL,
                    knowledge_gained TEXT,
                    confidence REAL DEFAULT 0.5,
                    source TEXT,
                    metadata TEXT
                );

                CREATE TABLE IF NOT EXISTS skills (
                    domain TEXT NOT NULL,
                    name TEXT NOT NULL,
                    proficiency REAL DEFAULT 0.0,
                    total_investments INTEGER DEFAULT 0,
                    total_cost REAL DEFAULT 0.0,
                    last_used TEXT,
                    last_improved TEXT,
                    applications INTEGER DEFAULT 0,
                    PRIMARY KEY (domain, name)
                );

                CREATE TABLE IF NOT EXISTS strategic_decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    reasoning TEXT,
                    context TEXT,
                    expected_value REAL,
                    expected_learning REAL,
                    economic_state TEXT
                );

                CREATE TABLE IF NOT EXISTS knowledge_base (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    domain TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source TEXT,
                    confidence REAL DEFAULT 0.5,
                    created_at TEXT NOT NULL,
                    last_accessed TEXT,
                    access_count INTEGER DEFAULT 0,
                    value_generated REAL DEFAULT 0.0
                );

                CREATE INDEX IF NOT EXISTS idx_learning_domain ON learning_investments(domain);
                CREATE INDEX IF NOT EXISTS idx_knowledge_domain ON knowledge_base(domain);
                CREATE INDEX IF NOT EXISTS idx_decisions_timestamp ON strategic_decisions(timestamp);
            """)

    # -------------------------------------------------------------------------
    # Learning Investment
    # -------------------------------------------------------------------------

    def invest_in_learning(
        self,
        domain: LearningDomain,
        topic: str,
        knowledge_gained: str,
        cost_usd: float,
        time_seconds: int,
        source: str = "interaction",
        confidence: float = 0.7,
        metadata: Optional[Dict] = None
    ) -> LearningInvestment:
        """
        Record a learning investment.

        Args:
            domain: Learning domain
            topic: Specific topic learned
            knowledge_gained: What was learned
            cost_usd: Cost incurred (API calls, etc.)
            time_seconds: Time spent learning
            source: Source of knowledge
            confidence: How confident in learning (0-1)
            metadata: Additional context

        Returns:
            The recorded investment
        """
        investment = LearningInvestment(
            timestamp=datetime.utcnow(),
            domain=domain,
            topic=topic,
            cost_usd=cost_usd,
            time_seconds=time_seconds,
            knowledge_gained=knowledge_gained,
            confidence=confidence,
            source=source,
            metadata=metadata or {},
        )

        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                # Record investment
                conn.execute("""
                    INSERT INTO learning_investments
                    (timestamp, domain, topic, cost_usd, time_seconds,
                     knowledge_gained, confidence, source, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    investment.timestamp.isoformat(),
                    investment.domain.value,
                    investment.topic,
                    investment.cost_usd,
                    investment.time_seconds,
                    investment.knowledge_gained,
                    investment.confidence,
                    investment.source,
                    json.dumps(investment.metadata),
                ))

                # Update skill proficiency
                self._update_skill(conn, domain, topic, confidence)

                # Store knowledge
                conn.execute("""
                    INSERT INTO knowledge_base
                    (domain, topic, content, source, confidence, created_at, last_accessed)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    domain.value,
                    topic,
                    knowledge_gained,
                    source,
                    confidence,
                    investment.timestamp.isoformat(),
                    investment.timestamp.isoformat(),
                ))

        logger.info(f"Learning investment: {domain.value}/{topic} (${cost_usd:.4f})")
        return investment

    def _update_skill(
        self,
        conn: sqlite3.Connection,
        domain: LearningDomain,
        skill_name: str,
        learning_gain: float
    ):
        """Update skill proficiency with compound learning."""
        # Get current skill
        row = conn.execute("""
            SELECT proficiency, total_investments, total_cost
            FROM skills
            WHERE domain = ? AND name = ?
        """, (domain.value, skill_name)).fetchone()

        if row:
            current_prof = row[0]
            investments = row[1] + 1
            # Compound learning: higher proficiency = faster learning
            boost = 1 + (current_prof * (self.compound_learning_rate - 1))
            new_prof = min(1.0, current_prof + (learning_gain * 0.1 * boost))

            conn.execute("""
                UPDATE skills
                SET proficiency = ?, total_investments = ?, last_improved = ?
                WHERE domain = ? AND name = ?
            """, (new_prof, investments, datetime.utcnow().isoformat(),
                  domain.value, skill_name))
        else:
            # New skill
            conn.execute("""
                INSERT INTO skills
                (domain, name, proficiency, total_investments, last_improved, last_used)
                VALUES (?, ?, ?, 1, ?, ?)
            """, (domain.value, skill_name, learning_gain * 0.1,
                  datetime.utcnow().isoformat(), datetime.utcnow().isoformat()))

    # -------------------------------------------------------------------------
    # Strategic Decision Making
    # -------------------------------------------------------------------------

    def should_learn_or_work(
        self,
        task_value: float,
        task_complexity: str,
        available_time_seconds: int,
        economic_state: Dict[str, Any]
    ) -> Tuple[ActivityType, str]:
        """
        Decide whether to work or learn.

        Strategy:
        - If economic state is poor (low sustainability), prioritize work
        - If skills are weak for task, consider learning first
        - If time is limited, work
        - If skills are strong and sustainable, invest in learning

        Args:
            task_value: Expected value of immediate work
            task_complexity: simple/medium/complex
            available_time_seconds: Time available
            economic_state: Current economic snapshot

        Returns:
            (decision, reasoning)
        """
        sustainability = economic_state.get("sustainability_score", 0.5)
        net_value = economic_state.get("net_value", 0)

        # Get relevant skill proficiency
        skills = self.get_skills_summary()
        avg_proficiency = sum(s.get("proficiency", 0) for s in skills) / max(1, len(skills))

        # Decision logic
        reasons = []

        # Rule 1: If struggling economically, work
        if sustainability < 0.4:
            reasons.append(f"Low sustainability ({sustainability:.2f}) - need immediate value")
            return ActivityType.WORK, "; ".join(reasons)

        # Rule 2: If skills are very low and task is complex, consider learning
        if avg_proficiency < 0.3 and task_complexity in ["complex", "critical"]:
            if available_time_seconds > 300:  # Have at least 5 min
                reasons.append(f"Low skills ({avg_proficiency:.2f}) for complex task - learning investment")
                return ActivityType.LEARN, "; ".join(reasons)

        # Rule 3: If sustainable and skills are moderate, balance work and learning
        if sustainability > 0.6 and avg_proficiency < 0.7:
            # 30% chance to learn if sustainable
            import random
            if random.random() < 0.3:
                reasons.append(f"Sustainable ({sustainability:.2f}), investing in growth")
                return ActivityType.LEARN, "; ".join(reasons)

        # Rule 4: If very sustainable with strong skills, occasionally reflect
        if sustainability > 0.8 and avg_proficiency > 0.7:
            import random
            if random.random() < 0.1:
                reasons.append("Strong position - reflection time")
                return ActivityType.REFLECT, "; ".join(reasons)

        # Default: work
        reasons.append(f"Standard operation - value: ${task_value:.2f}")
        return ActivityType.WORK, "; ".join(reasons)

    def record_decision(
        self,
        decision: ActivityType,
        reasoning: str,
        context: Dict[str, Any],
        expected_value: float,
        expected_learning: float,
        economic_state: Dict[str, Any]
    ):
        """Record a strategic decision for analysis."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO strategic_decisions
                    (timestamp, decision, reasoning, context,
                     expected_value, expected_learning, economic_state)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    datetime.utcnow().isoformat(),
                    decision.value,
                    reasoning,
                    json.dumps(context),
                    expected_value,
                    expected_learning,
                    json.dumps(economic_state),
                ))

    # -------------------------------------------------------------------------
    # Skill Management
    # -------------------------------------------------------------------------

    def get_skill(self, domain: LearningDomain, name: str) -> Optional[Skill]:
        """Get a specific skill."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("""
                SELECT * FROM skills WHERE domain = ? AND name = ?
            """, (domain.value, name)).fetchone()

            if row:
                return Skill(
                    domain=LearningDomain(row["domain"]),
                    name=row["name"],
                    proficiency=row["proficiency"],
                    total_investments=row["total_investments"],
                    total_cost=row["total_cost"] or 0,
                    last_used=datetime.fromisoformat(row["last_used"]) if row["last_used"] else datetime.utcnow(),
                    last_improved=datetime.fromisoformat(row["last_improved"]) if row["last_improved"] else datetime.utcnow(),
                    applications=row["applications"] or 0,
                )
        return None

    def get_skills_summary(self) -> List[Dict[str, Any]]:
        """Get summary of all skills."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT domain, name, proficiency, total_investments, applications
                FROM skills
                ORDER BY proficiency DESC
            """).fetchall()

        return [
            {
                "domain": r["domain"],
                "name": r["name"],
                "proficiency": r["proficiency"],
                "investments": r["total_investments"],
                "applications": r["applications"],
            }
            for r in rows
        ]

    def apply_skill(self, domain: LearningDomain, name: str) -> float:
        """
        Record skill application and return proficiency boost.

        Returns multiplier for task value based on skill level.
        """
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute("""
                    SELECT proficiency, applications FROM skills
                    WHERE domain = ? AND name = ?
                """, (domain.value, name)).fetchone()

                if row:
                    proficiency = row[0]
                    applications = row[1] + 1

                    conn.execute("""
                        UPDATE skills
                        SET applications = ?, last_used = ?
                        WHERE domain = ? AND name = ?
                    """, (applications, datetime.utcnow().isoformat(),
                          domain.value, name))

                    # Return value multiplier based on proficiency
                    # 0.5 proficiency = 1.25x, 1.0 proficiency = 1.5x
                    return 1 + (proficiency * 0.5)

        return 1.0  # No skill = no boost

    # -------------------------------------------------------------------------
    # Knowledge Retrieval
    # -------------------------------------------------------------------------

    def recall_knowledge(
        self,
        domain: Optional[LearningDomain] = None,
        topic: Optional[str] = None,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Recall stored knowledge.

        Args:
            domain: Filter by domain
            topic: Filter by topic (partial match)
            limit: Max results

        Returns:
            List of knowledge entries
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            query = "SELECT * FROM knowledge_base WHERE 1=1"
            params = []

            if domain:
                query += " AND domain = ?"
                params.append(domain.value)

            if topic:
                query += " AND topic LIKE ?"
                params.append(f"%{topic}%")

            query += " ORDER BY confidence DESC, last_accessed DESC LIMIT ?"
            params.append(limit)

            rows = conn.execute(query, params).fetchall()

            # Update access stats
            for row in rows:
                conn.execute("""
                    UPDATE knowledge_base
                    SET last_accessed = ?, access_count = access_count + 1
                    WHERE id = ?
                """, (datetime.utcnow().isoformat(), row["id"]))

        return [
            {
                "domain": r["domain"],
                "topic": r["topic"],
                "content": r["content"],
                "confidence": r["confidence"],
                "access_count": r["access_count"],
            }
            for r in rows
        ]

    def get_learning_roi(self, days: int = 30) -> Dict[str, Any]:
        """Calculate ROI of learning investments."""
        start_date = datetime.utcnow() - timedelta(days=days)

        with sqlite3.connect(self.db_path) as conn:
            # Total learning cost
            cost_row = conn.execute("""
                SELECT COALESCE(SUM(cost_usd), 0) as total
                FROM learning_investments
                WHERE timestamp > ?
            """, (start_date.isoformat(),)).fetchone()

            # Value generated from knowledge
            value_row = conn.execute("""
                SELECT COALESCE(SUM(value_generated), 0) as total
                FROM knowledge_base
                WHERE created_at > ?
            """, (start_date.isoformat(),)).fetchone()

            # Skill improvements
            skills_row = conn.execute("""
                SELECT COUNT(*) as count, AVG(proficiency) as avg_prof
                FROM skills
                WHERE last_improved > ?
            """, (start_date.isoformat(),)).fetchone()

        total_cost = cost_row[0]
        total_value = value_row[0]
        skills_improved = skills_row[0]
        avg_proficiency = skills_row[1] or 0

        return {
            "days": days,
            "total_learning_cost": round(total_cost, 4),
            "value_from_knowledge": round(total_value, 4),
            "skills_improved": skills_improved,
            "average_proficiency": round(avg_proficiency, 3),
            "learning_roi_percent": round((total_value / total_cost * 100) if total_cost > 0 else 0, 2),
        }


# =============================================================================
# Global Instance
# =============================================================================

_strategic_learner: Optional[StrategicLearner] = None


def get_strategic_learner() -> StrategicLearner:
    """Get the global strategic learner instance."""
    global _strategic_learner
    if _strategic_learner is None:
        _strategic_learner = StrategicLearner()
    return _strategic_learner
