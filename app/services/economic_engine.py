"""
Economic Accountability Engine

Inspired by ClawWork: Makes Jarvis economically accountable.
Tracks value created vs. costs incurred to ensure self-sustainability.

Core Metrics:
- Value Created: Task completions, user satisfaction, time saved
- Costs Incurred: API tokens, compute time, external services
- ROI per Feature: Which capabilities generate most value?
- Sustainability Score: Is Jarvis earning more than spending?

Philosophy: Jarvis should create more value than it consumes.
"""

import logging
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Any
from threading import Lock

logger = logging.getLogger(__name__)


# =============================================================================
# Value Types and Models
# =============================================================================

class ValueType(str, Enum):
    """Types of value Jarvis can create."""
    TASK_COMPLETION = "task_completion"  # Completed a user request
    TIME_SAVED = "time_saved"  # Saved user time (automation)
    KNOWLEDGE_CREATED = "knowledge_created"  # Created reusable knowledge
    PROBLEM_SOLVED = "problem_solved"  # Solved a problem
    DECISION_SUPPORT = "decision_support"  # Helped make a decision
    PROACTIVE_ALERT = "proactive_alert"  # Proactively notified user
    CODE_GENERATED = "code_generated"  # Generated useful code
    INSIGHT_PROVIDED = "insight_provided"  # Provided valuable insight


class CostType(str, Enum):
    """Types of costs Jarvis incurs."""
    LLM_TOKENS = "llm_tokens"  # API token costs
    EMBEDDING = "embedding"  # Embedding generation
    EXTERNAL_API = "external_api"  # External service calls
    COMPUTE = "compute"  # Compute time
    STORAGE = "storage"  # Storage costs


@dataclass
class ValueEvent:
    """A value creation event."""
    timestamp: datetime
    value_type: ValueType
    amount_usd: float  # Estimated value in USD
    feature: str  # Which feature created this value
    user_id: str
    description: str
    confidence: float = 0.8  # How confident are we in this value estimate
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CostEvent:
    """A cost incurrence event."""
    timestamp: datetime
    cost_type: CostType
    amount_usd: float
    feature: str
    user_id: str
    description: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EconomicSnapshot:
    """Point-in-time economic state."""
    timestamp: datetime
    total_value_created: float
    total_costs_incurred: float
    net_value: float
    roi_percent: float
    sustainability_score: float  # 0-1, >0.5 = sustainable
    top_value_features: List[Dict[str, Any]]
    top_cost_features: List[Dict[str, Any]]


# =============================================================================
# Value Estimation
# =============================================================================

# Estimated value per action type (USD)
VALUE_ESTIMATES = {
    ValueType.TASK_COMPLETION: {
        "simple": 0.50,  # Simple query answered
        "medium": 2.00,  # Medium complexity task
        "complex": 5.00,  # Complex multi-step task
        "critical": 10.00,  # Critical/urgent task
    },
    ValueType.TIME_SAVED: {
        "minutes_rate": 0.50,  # $0.50 per minute saved
    },
    ValueType.KNOWLEDGE_CREATED: {
        "fact": 0.10,  # Single fact stored
        "document": 1.00,  # Document processed
        "insight": 2.00,  # Insight generated
    },
    ValueType.PROBLEM_SOLVED: {
        "simple": 1.00,
        "medium": 3.00,
        "complex": 8.00,
    },
    ValueType.CODE_GENERATED: {
        "snippet": 0.50,
        "function": 2.00,
        "module": 5.00,
        "feature": 15.00,
    },
    ValueType.PROACTIVE_ALERT: {
        "info": 0.25,
        "warning": 1.00,
        "critical": 5.00,
    },
}


def estimate_value(
    value_type: ValueType,
    complexity: str = "medium",
    minutes_saved: int = 0,
    confidence: float = 0.8
) -> float:
    """
    Estimate the USD value of an action.

    Args:
        value_type: Type of value created
        complexity: simple/medium/complex/critical
        minutes_saved: For time_saved type
        confidence: Confidence in estimate (0-1)

    Returns:
        Estimated value in USD
    """
    base_values = VALUE_ESTIMATES.get(value_type, {})

    if value_type == ValueType.TIME_SAVED:
        value = minutes_saved * base_values.get("minutes_rate", 0.50)
    else:
        value = base_values.get(complexity, base_values.get("medium", 1.00))

    return round(value * confidence, 4)


# =============================================================================
# Economic Engine
# =============================================================================

class EconomicEngine:
    """
    Tracks economic accountability for Jarvis.

    Implements the ClawWork philosophy: AI should create more value than it consumes.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or os.environ.get(
            "JARVIS_ECONOMIC_DB",
            "/brain/system/data/jarvis_economics.db"
        )
        self._lock = Lock()
        self._init_db()

    def _init_db(self):
        """Initialize database tables."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS value_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    value_type TEXT NOT NULL,
                    amount_usd REAL NOT NULL,
                    feature TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    description TEXT,
                    confidence REAL DEFAULT 0.8,
                    metadata TEXT
                );

                CREATE TABLE IF NOT EXISTS cost_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    cost_type TEXT NOT NULL,
                    amount_usd REAL NOT NULL,
                    feature TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    description TEXT,
                    metadata TEXT
                );

                CREATE TABLE IF NOT EXISTS daily_snapshots (
                    date TEXT PRIMARY KEY,
                    total_value REAL NOT NULL,
                    total_cost REAL NOT NULL,
                    net_value REAL NOT NULL,
                    roi_percent REAL NOT NULL,
                    sustainability_score REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_value_timestamp ON value_events(timestamp);
                CREATE INDEX IF NOT EXISTS idx_cost_timestamp ON cost_events(timestamp);
                CREATE INDEX IF NOT EXISTS idx_value_feature ON value_events(feature);
                CREATE INDEX IF NOT EXISTS idx_cost_feature ON cost_events(feature);
            """)

    # -------------------------------------------------------------------------
    # Value Tracking
    # -------------------------------------------------------------------------

    def record_value(
        self,
        value_type: ValueType,
        feature: str,
        user_id: str,
        description: str,
        amount_usd: Optional[float] = None,
        complexity: str = "medium",
        minutes_saved: int = 0,
        confidence: float = 0.8,
        metadata: Optional[Dict] = None
    ) -> ValueEvent:
        """
        Record a value creation event.

        Args:
            value_type: Type of value created
            feature: Which feature/tool created this value
            user_id: User who received the value
            description: Description of value created
            amount_usd: Explicit value (if None, auto-estimate)
            complexity: For auto-estimation
            minutes_saved: For time_saved type
            confidence: Confidence in value estimate
            metadata: Additional context

        Returns:
            The recorded ValueEvent
        """
        if amount_usd is None:
            amount_usd = estimate_value(value_type, complexity, minutes_saved, confidence)

        event = ValueEvent(
            timestamp=datetime.utcnow(),
            value_type=value_type,
            amount_usd=amount_usd,
            feature=feature,
            user_id=user_id,
            description=description,
            confidence=confidence,
            metadata=metadata or {},
        )

        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO value_events
                    (timestamp, value_type, amount_usd, feature, user_id, description, confidence, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    event.timestamp.isoformat(),
                    event.value_type.value,
                    event.amount_usd,
                    event.feature,
                    event.user_id,
                    event.description,
                    event.confidence,
                    str(event.metadata),
                ))

        logger.info(f"Value recorded: ${event.amount_usd:.4f} from {feature} ({value_type.value})")
        return event

    def record_cost(
        self,
        cost_type: CostType,
        amount_usd: float,
        feature: str,
        user_id: str,
        description: str,
        metadata: Optional[Dict] = None
    ) -> CostEvent:
        """
        Record a cost event.

        Args:
            cost_type: Type of cost
            amount_usd: Cost in USD
            feature: Which feature incurred this cost
            user_id: User context
            description: Description
            metadata: Additional context

        Returns:
            The recorded CostEvent
        """
        event = CostEvent(
            timestamp=datetime.utcnow(),
            cost_type=cost_type,
            amount_usd=amount_usd,
            feature=feature,
            user_id=user_id,
            description=description,
            metadata=metadata or {},
        )

        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO cost_events
                    (timestamp, cost_type, amount_usd, feature, user_id, description, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    event.timestamp.isoformat(),
                    event.cost_type.value,
                    event.amount_usd,
                    event.feature,
                    event.user_id,
                    event.description,
                    str(event.metadata),
                ))

        logger.debug(f"Cost recorded: ${event.amount_usd:.4f} for {feature} ({cost_type.value})")
        return event

    # -------------------------------------------------------------------------
    # Economic Analysis
    # -------------------------------------------------------------------------

    def get_snapshot(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> EconomicSnapshot:
        """
        Get economic snapshot for a time period.

        Args:
            start_date: Start of period (default: 30 days ago)
            end_date: End of period (default: now)

        Returns:
            EconomicSnapshot with all metrics
        """
        if end_date is None:
            end_date = datetime.utcnow()
        if start_date is None:
            start_date = end_date - timedelta(days=30)

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            # Total value
            value_row = conn.execute("""
                SELECT COALESCE(SUM(amount_usd), 0) as total
                FROM value_events
                WHERE timestamp BETWEEN ? AND ?
            """, (start_date.isoformat(), end_date.isoformat())).fetchone()
            total_value = value_row["total"]

            # Total cost
            cost_row = conn.execute("""
                SELECT COALESCE(SUM(amount_usd), 0) as total
                FROM cost_events
                WHERE timestamp BETWEEN ? AND ?
            """, (start_date.isoformat(), end_date.isoformat())).fetchone()
            total_cost = cost_row["total"]

            # Top value features
            top_value = conn.execute("""
                SELECT feature, SUM(amount_usd) as total, COUNT(*) as count
                FROM value_events
                WHERE timestamp BETWEEN ? AND ?
                GROUP BY feature
                ORDER BY total DESC
                LIMIT 5
            """, (start_date.isoformat(), end_date.isoformat())).fetchall()

            # Top cost features
            top_cost = conn.execute("""
                SELECT feature, SUM(amount_usd) as total, COUNT(*) as count
                FROM cost_events
                WHERE timestamp BETWEEN ? AND ?
                GROUP BY feature
                ORDER BY total DESC
                LIMIT 5
            """, (start_date.isoformat(), end_date.isoformat())).fetchall()

        # Calculate metrics
        net_value = total_value - total_cost
        roi_percent = (net_value / total_cost * 100) if total_cost > 0 else 0

        # Sustainability score: 0-1, where 0.5 = break-even
        # Score > 0.5 means creating more value than consuming
        if total_cost == 0:
            sustainability = 1.0 if total_value > 0 else 0.5
        else:
            ratio = total_value / total_cost
            # Map ratio to 0-1 scale: ratio of 1 = 0.5, ratio of 2 = 0.75, etc.
            sustainability = min(1.0, ratio / 2)

        return EconomicSnapshot(
            timestamp=datetime.utcnow(),
            total_value_created=round(total_value, 4),
            total_costs_incurred=round(total_cost, 4),
            net_value=round(net_value, 4),
            roi_percent=round(roi_percent, 2),
            sustainability_score=round(sustainability, 3),
            top_value_features=[
                {"feature": r["feature"], "value": r["total"], "count": r["count"]}
                for r in top_value
            ],
            top_cost_features=[
                {"feature": r["feature"], "cost": r["total"], "count": r["count"]}
                for r in top_cost
            ],
        )

    def get_feature_roi(self, feature: str, days: int = 30) -> Dict[str, Any]:
        """
        Calculate ROI for a specific feature.

        Args:
            feature: Feature name
            days: Lookback period

        Returns:
            ROI metrics for the feature
        """
        start_date = datetime.utcnow() - timedelta(days=days)

        with sqlite3.connect(self.db_path) as conn:
            value = conn.execute("""
                SELECT COALESCE(SUM(amount_usd), 0) as total, COUNT(*) as count
                FROM value_events
                WHERE feature = ? AND timestamp > ?
            """, (feature, start_date.isoformat())).fetchone()

            cost = conn.execute("""
                SELECT COALESCE(SUM(amount_usd), 0) as total, COUNT(*) as count
                FROM cost_events
                WHERE feature = ? AND timestamp > ?
            """, (feature, start_date.isoformat())).fetchone()

        total_value = value[0]
        total_cost = cost[0]
        net = total_value - total_cost
        roi = (net / total_cost * 100) if total_cost > 0 else 0

        return {
            "feature": feature,
            "days": days,
            "total_value": round(total_value, 4),
            "total_cost": round(total_cost, 4),
            "net_value": round(net, 4),
            "roi_percent": round(roi, 2),
            "value_events": value[1],
            "cost_events": cost[1],
            "profitable": net > 0,
        }

    def get_daily_trend(self, days: int = 14) -> List[Dict[str, Any]]:
        """Get daily value/cost trend."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            rows = conn.execute("""
                WITH dates AS (
                    SELECT date(datetime('now', '-' || n || ' days')) as date
                    FROM (SELECT 0 as n UNION SELECT 1 UNION SELECT 2 UNION SELECT 3
                          UNION SELECT 4 UNION SELECT 5 UNION SELECT 6 UNION SELECT 7
                          UNION SELECT 8 UNION SELECT 9 UNION SELECT 10 UNION SELECT 11
                          UNION SELECT 12 UNION SELECT 13)
                    WHERE n < ?
                ),
                daily_value AS (
                    SELECT date(timestamp) as date, SUM(amount_usd) as value
                    FROM value_events
                    WHERE timestamp > datetime('now', '-' || ? || ' days')
                    GROUP BY date(timestamp)
                ),
                daily_cost AS (
                    SELECT date(timestamp) as date, SUM(amount_usd) as cost
                    FROM cost_events
                    WHERE timestamp > datetime('now', '-' || ? || ' days')
                    GROUP BY date(timestamp)
                )
                SELECT
                    d.date,
                    COALESCE(v.value, 0) as value,
                    COALESCE(c.cost, 0) as cost
                FROM dates d
                LEFT JOIN daily_value v ON d.date = v.date
                LEFT JOIN daily_cost c ON d.date = c.date
                ORDER BY d.date
            """, (days, days, days)).fetchall()

        return [
            {
                "date": r["date"],
                "value": round(r["value"], 4),
                "cost": round(r["cost"], 4),
                "net": round(r["value"] - r["cost"], 4),
            }
            for r in rows
        ]

    def is_sustainable(self, days: int = 7) -> bool:
        """Check if Jarvis is currently sustainable (creating more value than cost)."""
        snapshot = self.get_snapshot(
            start_date=datetime.utcnow() - timedelta(days=days)
        )
        return snapshot.sustainability_score > 0.5


# =============================================================================
# Global Instance
# =============================================================================

_economic_engine: Optional[EconomicEngine] = None


def get_economic_engine() -> EconomicEngine:
    """Get the global economic engine instance."""
    global _economic_engine
    if _economic_engine is None:
        _economic_engine = EconomicEngine()
    return _economic_engine
