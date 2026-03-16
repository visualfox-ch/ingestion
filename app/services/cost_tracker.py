"""
Cost Tracker Service

Tracks token usage and API costs across all Jarvis features.
Inspired by ClawWork's economic accountability concept.

Usage:
    from app.services.cost_tracker import get_cost_tracker, track_llm_cost

    tracker = get_cost_tracker()

    # Track an LLM call
    tracker.track_llm_call(
        model="claude-sonnet-4-20250514",
        input_tokens=1500,
        output_tokens=500,
        feature="agent",
        user_id="micha"
    )

    # Get costs
    daily = tracker.get_daily_costs()
    by_feature = tracker.get_costs_by_feature()
"""

import json
import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# =============================================================================
# Pricing Configuration (USD per 1M tokens/units)
# =============================================================================

class ModelPricing:
    """Current API pricing (as of Feb 2026)."""

    # Anthropic Claude
    CLAUDE_OPUS_INPUT = 15.0      # $15/1M input tokens
    CLAUDE_OPUS_OUTPUT = 75.0    # $75/1M output tokens
    CLAUDE_SONNET_INPUT = 3.0    # $3/1M input tokens
    CLAUDE_SONNET_OUTPUT = 15.0  # $15/1M output tokens
    CLAUDE_HAIKU_INPUT = 0.25    # $0.25/1M input tokens
    CLAUDE_HAIKU_OUTPUT = 1.25   # $1.25/1M output tokens

    # OpenAI
    GPT4O_INPUT = 2.50           # $2.50/1M input tokens
    GPT4O_OUTPUT = 10.0          # $10/1M output tokens
    GPT4O_MINI_INPUT = 0.15      # $0.15/1M input tokens
    GPT4O_MINI_OUTPUT = 0.60     # $0.60/1M output tokens
    WHISPER_PER_MINUTE = 0.006   # $0.006/minute
    TTS_PER_CHAR = 0.000015      # $15/1M chars = $0.000015/char

    # Embedding models
    EMBED_3_SMALL = 0.02         # $0.02/1M tokens
    EMBED_3_LARGE = 0.13         # $0.13/1M tokens

    @classmethod
    def get_pricing(cls, model: str) -> tuple[float, float]:
        """Get (input_price, output_price) per 1M tokens for a model."""
        model_lower = model.lower()

        # Claude models
        if "opus" in model_lower:
            return (cls.CLAUDE_OPUS_INPUT, cls.CLAUDE_OPUS_OUTPUT)
        elif "sonnet" in model_lower:
            return (cls.CLAUDE_SONNET_INPUT, cls.CLAUDE_SONNET_OUTPUT)
        elif "haiku" in model_lower:
            return (cls.CLAUDE_HAIKU_INPUT, cls.CLAUDE_HAIKU_OUTPUT)

        # OpenAI models
        elif "gpt-4o-mini" in model_lower:
            return (cls.GPT4O_MINI_INPUT, cls.GPT4O_MINI_OUTPUT)
        elif "gpt-4o" in model_lower or "gpt-4" in model_lower:
            return (cls.GPT4O_INPUT, cls.GPT4O_OUTPUT)

        # Default to Sonnet pricing
        return (cls.CLAUDE_SONNET_INPUT, cls.CLAUDE_SONNET_OUTPUT)


@dataclass
class CostEntry:
    """A single cost tracking entry."""
    id: Optional[int] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
    model: str = ""
    feature: str = "unknown"
    user_id: str = "system"
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "model": self.model,
            "feature": self.feature,
            "user_id": self.user_id,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": self.cost_usd,
            "metadata": self.metadata,
        }


@dataclass
class CostSummary:
    """Aggregated cost summary."""
    period: str  # "daily", "weekly", "monthly", "all_time"
    start_date: datetime
    end_date: datetime
    total_cost_usd: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_requests: int = 0
    by_feature: Dict[str, float] = field(default_factory=dict)
    by_model: Dict[str, float] = field(default_factory=dict)
    by_user: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "period": self.period,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "total_cost_usd": round(self.total_cost_usd, 4),
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_requests": self.total_requests,
            "by_feature": {k: round(v, 4) for k, v in self.by_feature.items()},
            "by_model": {k: round(v, 4) for k, v in self.by_model.items()},
            "by_user": {k: round(v, 4) for k, v in self.by_user.items()},
        }


class CostTracker:
    """
    Central cost tracking service for all API usage.

    Features:
    - Track LLM calls (Claude, OpenAI)
    - Track voice API usage (Whisper, TTS)
    - Track embedding calls
    - Aggregate by feature, model, user, time period
    - Persistent storage in SQLite
    """

    def __init__(self, db_path: Optional[str] = None):
        """Initialize cost tracker with SQLite storage."""
        self._db_path = Path(
            db_path or os.environ.get(
                "COST_TRACKER_DB",
                "/brain/system/state/cost_tracker.db"
            )
        )
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        """Get thread-local database connection."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(
                str(self._db_path),
                check_same_thread=False
            )
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn

    @contextmanager
    def _cursor(self):
        """Context manager for database cursor."""
        conn = self._get_conn()
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()

    def _init_db(self) -> None:
        """Initialize database schema."""
        with self._cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS cost_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    model TEXT NOT NULL,
                    feature TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    input_tokens INTEGER DEFAULT 0,
                    output_tokens INTEGER DEFAULT 0,
                    total_tokens INTEGER DEFAULT 0,
                    cost_usd REAL DEFAULT 0.0,
                    metadata TEXT DEFAULT '{}'
                )
            """)

            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_cost_timestamp
                ON cost_entries(timestamp)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_cost_feature
                ON cost_entries(feature)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_cost_user
                ON cost_entries(user_id)
            """)

            # Daily aggregates table for faster queries
            cur.execute("""
                CREATE TABLE IF NOT EXISTS cost_daily_aggregates (
                    date TEXT NOT NULL,
                    feature TEXT NOT NULL,
                    model TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    total_cost_usd REAL DEFAULT 0.0,
                    total_input_tokens INTEGER DEFAULT 0,
                    total_output_tokens INTEGER DEFAULT 0,
                    request_count INTEGER DEFAULT 0,
                    PRIMARY KEY (date, feature, model, user_id)
                )
            """)

        logger.info(f"Cost tracker initialized: {self._db_path}")

    def calculate_cost(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        """Calculate cost in USD for token usage."""
        input_price, output_price = ModelPricing.get_pricing(model)

        input_cost = (input_tokens / 1_000_000) * input_price
        output_cost = (output_tokens / 1_000_000) * output_price

        return input_cost + output_cost

    def track_llm_call(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        feature: str = "unknown",
        user_id: str = "system",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> CostEntry:
        """
        Track an LLM API call.

        Args:
            model: Model identifier (e.g., "claude-sonnet-4-20250514")
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            feature: Feature/tool that made the call (e.g., "agent", "rewrite")
            user_id: User identifier
            metadata: Additional metadata

        Returns:
            CostEntry with calculated cost
        """
        cost_usd = self.calculate_cost(model, input_tokens, output_tokens)

        entry = CostEntry(
            timestamp=datetime.utcnow(),
            model=model,
            feature=feature,
            user_id=user_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            cost_usd=cost_usd,
            metadata=metadata or {},
        )

        self._store_entry(entry)
        self._update_daily_aggregate(entry)

        logger.debug(
            f"Tracked cost: {feature}/{model} - "
            f"{input_tokens}+{output_tokens} tokens = ${cost_usd:.4f}"
        )

        return entry

    def track_voice_stt(
        self,
        duration_seconds: float,
        feature: str = "voice_stt",
        user_id: str = "system",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> CostEntry:
        """Track Whisper STT usage."""
        minutes = duration_seconds / 60
        cost_usd = minutes * ModelPricing.WHISPER_PER_MINUTE

        entry = CostEntry(
            timestamp=datetime.utcnow(),
            model="whisper-1",
            feature=feature,
            user_id=user_id,
            cost_usd=cost_usd,
            metadata={"duration_seconds": duration_seconds, **(metadata or {})},
        )

        self._store_entry(entry)
        self._update_daily_aggregate(entry)

        return entry

    def track_voice_tts(
        self,
        character_count: int,
        feature: str = "voice_tts",
        user_id: str = "system",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> CostEntry:
        """Track TTS usage."""
        cost_usd = character_count * ModelPricing.TTS_PER_CHAR

        entry = CostEntry(
            timestamp=datetime.utcnow(),
            model="tts-1",
            feature=feature,
            user_id=user_id,
            cost_usd=cost_usd,
            metadata={"character_count": character_count, **(metadata or {})},
        )

        self._store_entry(entry)
        self._update_daily_aggregate(entry)

        return entry

    def track_embedding(
        self,
        token_count: int,
        model: str = "text-embedding-3-small",
        feature: str = "embedding",
        user_id: str = "system",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> CostEntry:
        """Track embedding API usage."""
        if "large" in model.lower():
            price_per_million = ModelPricing.EMBED_3_LARGE
        else:
            price_per_million = ModelPricing.EMBED_3_SMALL

        cost_usd = (token_count / 1_000_000) * price_per_million

        entry = CostEntry(
            timestamp=datetime.utcnow(),
            model=model,
            feature=feature,
            user_id=user_id,
            input_tokens=token_count,
            total_tokens=token_count,
            cost_usd=cost_usd,
            metadata=metadata or {},
        )

        self._store_entry(entry)
        self._update_daily_aggregate(entry)

        return entry

    def _store_entry(self, entry: CostEntry) -> None:
        """Store a cost entry in the database."""
        with self._cursor() as cur:
            cur.execute("""
                INSERT INTO cost_entries
                (timestamp, model, feature, user_id, input_tokens,
                 output_tokens, total_tokens, cost_usd, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                entry.timestamp.isoformat(),
                entry.model,
                entry.feature,
                entry.user_id,
                entry.input_tokens,
                entry.output_tokens,
                entry.total_tokens,
                entry.cost_usd,
                json.dumps(entry.metadata),
            ))
            entry.id = cur.lastrowid

    def _update_daily_aggregate(self, entry: CostEntry) -> None:
        """Update daily aggregate table."""
        date_str = entry.timestamp.strftime("%Y-%m-%d")

        with self._cursor() as cur:
            cur.execute("""
                INSERT INTO cost_daily_aggregates
                (date, feature, model, user_id, total_cost_usd,
                 total_input_tokens, total_output_tokens, request_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(date, feature, model, user_id) DO UPDATE SET
                    total_cost_usd = total_cost_usd + excluded.total_cost_usd,
                    total_input_tokens = total_input_tokens + excluded.total_input_tokens,
                    total_output_tokens = total_output_tokens + excluded.total_output_tokens,
                    request_count = request_count + 1
            """, (
                date_str,
                entry.feature,
                entry.model,
                entry.user_id,
                entry.cost_usd,
                entry.input_tokens,
                entry.output_tokens,
            ))

    def get_summary(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        feature: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> CostSummary:
        """
        Get cost summary for a time period.

        Args:
            start_date: Start of period (default: 30 days ago)
            end_date: End of period (default: now)
            feature: Filter by feature
            user_id: Filter by user

        Returns:
            CostSummary with aggregated data
        """
        end_date = end_date or datetime.utcnow()
        start_date = start_date or (end_date - timedelta(days=30))

        # Determine period name
        days = (end_date - start_date).days
        if days <= 1:
            period = "daily"
        elif days <= 7:
            period = "weekly"
        elif days <= 31:
            period = "monthly"
        else:
            period = "custom"

        # Build query
        query = """
            SELECT
                SUM(total_cost_usd) as total_cost,
                SUM(total_input_tokens) as input_tokens,
                SUM(total_output_tokens) as output_tokens,
                SUM(request_count) as requests
            FROM cost_daily_aggregates
            WHERE date >= ? AND date <= ?
        """
        params: List[Any] = [
            start_date.strftime("%Y-%m-%d"),
            end_date.strftime("%Y-%m-%d"),
        ]

        if feature:
            query += " AND feature = ?"
            params.append(feature)
        if user_id:
            query += " AND user_id = ?"
            params.append(user_id)

        with self._cursor() as cur:
            cur.execute(query, params)
            row = cur.fetchone()

            summary = CostSummary(
                period=period,
                start_date=start_date,
                end_date=end_date,
                total_cost_usd=row["total_cost"] or 0.0,
                total_input_tokens=row["input_tokens"] or 0,
                total_output_tokens=row["output_tokens"] or 0,
                total_requests=row["requests"] or 0,
            )

            # Get breakdown by feature
            cur.execute("""
                SELECT feature, SUM(total_cost_usd) as cost
                FROM cost_daily_aggregates
                WHERE date >= ? AND date <= ?
                GROUP BY feature
                ORDER BY cost DESC
            """, params[:2])
            summary.by_feature = {row["feature"]: row["cost"] for row in cur.fetchall()}

            # Get breakdown by model
            cur.execute("""
                SELECT model, SUM(total_cost_usd) as cost
                FROM cost_daily_aggregates
                WHERE date >= ? AND date <= ?
                GROUP BY model
                ORDER BY cost DESC
            """, params[:2])
            summary.by_model = {row["model"]: row["cost"] for row in cur.fetchall()}

            # Get breakdown by user
            cur.execute("""
                SELECT user_id, SUM(total_cost_usd) as cost
                FROM cost_daily_aggregates
                WHERE date >= ? AND date <= ?
                GROUP BY user_id
                ORDER BY cost DESC
            """, params[:2])
            summary.by_user = {row["user_id"]: row["cost"] for row in cur.fetchall()}

        return summary

    def get_daily_costs(self, days: int = 30) -> List[Dict[str, Any]]:
        """Get daily cost totals for the last N days."""
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)

        with self._cursor() as cur:
            cur.execute("""
                SELECT
                    date,
                    SUM(total_cost_usd) as cost,
                    SUM(request_count) as requests
                FROM cost_daily_aggregates
                WHERE date >= ? AND date <= ?
                GROUP BY date
                ORDER BY date DESC
            """, (
                start_date.strftime("%Y-%m-%d"),
                end_date.strftime("%Y-%m-%d"),
            ))

            return [
                {
                    "date": row["date"],
                    "cost_usd": round(row["cost"] or 0, 4),
                    "requests": row["requests"] or 0,
                }
                for row in cur.fetchall()
            ]

    def get_feature_costs(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """Get costs grouped by feature."""
        end_date = end_date or datetime.utcnow()
        start_date = start_date or (end_date - timedelta(days=30))

        with self._cursor() as cur:
            cur.execute("""
                SELECT
                    feature,
                    SUM(total_cost_usd) as cost,
                    SUM(request_count) as requests,
                    SUM(total_input_tokens) as input_tokens,
                    SUM(total_output_tokens) as output_tokens
                FROM cost_daily_aggregates
                WHERE date >= ? AND date <= ?
                GROUP BY feature
                ORDER BY cost DESC
            """, (
                start_date.strftime("%Y-%m-%d"),
                end_date.strftime("%Y-%m-%d"),
            ))

            return [
                {
                    "feature": row["feature"],
                    "cost_usd": round(row["cost"] or 0, 4),
                    "requests": row["requests"] or 0,
                    "input_tokens": row["input_tokens"] or 0,
                    "output_tokens": row["output_tokens"] or 0,
                }
                for row in cur.fetchall()
            ]

    def get_recent_entries(
        self,
        limit: int = 50,
        feature: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get recent cost entries."""
        query = """
            SELECT * FROM cost_entries
            WHERE 1=1
        """
        params: List[Any] = []

        if feature:
            query += " AND feature = ?"
            params.append(feature)

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        with self._cursor() as cur:
            cur.execute(query, params)
            return [
                {
                    "id": row["id"],
                    "timestamp": row["timestamp"],
                    "model": row["model"],
                    "feature": row["feature"],
                    "user_id": row["user_id"],
                    "tokens": row["total_tokens"],
                    "cost_usd": round(row["cost_usd"], 6),
                }
                for row in cur.fetchall()
            ]


# =============================================================================
# Singleton & Convenience Functions
# =============================================================================

_tracker: Optional[CostTracker] = None


def get_cost_tracker() -> CostTracker:
    """Get the singleton cost tracker instance."""
    global _tracker
    if _tracker is None:
        _tracker = CostTracker()
    return _tracker


def track_llm_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    feature: str = "unknown",
    user_id: str = "system",
) -> float:
    """
    Convenience function to track LLM cost.

    Returns:
        Cost in USD
    """
    tracker = get_cost_tracker()
    entry = tracker.track_llm_call(
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        feature=feature,
        user_id=user_id,
    )
    return entry.cost_usd


# =============================================================================
# Budget Management (Tier 1 Quick Win - Hard Budget Enforcement)
# =============================================================================

@dataclass
class Budget:
    """Budget configuration."""
    budget_id: str  # e.g., "daily", "monthly", "feature:agent"
    limit_usd: float
    spent_usd: float = 0.0
    hard_limit: bool = False  # If True, reject requests when exceeded
    alert_threshold: float = 0.8  # Alert when spent >= limit * threshold
    reset_period: str = "daily"  # "daily", "monthly", "never"
    last_reset: Optional[datetime] = None

    def remaining(self) -> float:
        return max(0.0, self.limit_usd - self.spent_usd)

    def is_exceeded(self) -> bool:
        return self.spent_usd >= self.limit_usd

    def should_alert(self) -> bool:
        return self.spent_usd >= (self.limit_usd * self.alert_threshold)


class BudgetManager:
    """
    Manages cost budgets with hard limit enforcement.

    Usage:
        manager = get_budget_manager()

        # Set a daily budget with hard limit
        manager.set_budget("daily", limit_usd=10.0, hard_limit=True)

        # Check before making LLM call
        if manager.check_budget_ok("daily", estimated_cost=0.05):
            # Proceed with LLM call
            pass
        else:
            raise BudgetExceededException("Daily budget exceeded")
    """

    def __init__(self, tracker: CostTracker):
        self._tracker = tracker
        self._budgets: Dict[str, Budget] = {}
        self._init_db()
        self._load_budgets()

    def _init_db(self) -> None:
        """Initialize budget table."""
        with self._tracker._cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS cost_budgets (
                    budget_id TEXT PRIMARY KEY,
                    limit_usd REAL NOT NULL,
                    spent_usd REAL DEFAULT 0.0,
                    hard_limit INTEGER DEFAULT 0,
                    alert_threshold REAL DEFAULT 0.8,
                    reset_period TEXT DEFAULT 'daily',
                    last_reset TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

    def _load_budgets(self) -> None:
        """Load budgets from database."""
        try:
            with self._tracker._cursor() as cur:
                cur.execute("SELECT * FROM cost_budgets")
                for row in cur.fetchall():
                    budget = Budget(
                        budget_id=row["budget_id"],
                        limit_usd=row["limit_usd"],
                        spent_usd=row["spent_usd"],
                        hard_limit=bool(row["hard_limit"]),
                        alert_threshold=row["alert_threshold"],
                        reset_period=row["reset_period"],
                        last_reset=datetime.fromisoformat(row["last_reset"]) if row["last_reset"] else None,
                    )
                    self._budgets[budget.budget_id] = budget
        except Exception as e:
            logger.warning(f"Failed to load budgets: {e}")

    def set_budget(
        self,
        budget_id: str,
        limit_usd: float,
        hard_limit: bool = False,
        alert_threshold: float = 0.8,
        reset_period: str = "daily"
    ) -> Budget:
        """Set or update a budget."""
        budget = Budget(
            budget_id=budget_id,
            limit_usd=limit_usd,
            spent_usd=0.0,
            hard_limit=hard_limit,
            alert_threshold=alert_threshold,
            reset_period=reset_period,
            last_reset=datetime.utcnow(),
        )

        with self._tracker._cursor() as cur:
            cur.execute("""
                INSERT INTO cost_budgets
                (budget_id, limit_usd, spent_usd, hard_limit, alert_threshold, reset_period, last_reset, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(budget_id) DO UPDATE SET
                    limit_usd = excluded.limit_usd,
                    hard_limit = excluded.hard_limit,
                    alert_threshold = excluded.alert_threshold,
                    reset_period = excluded.reset_period,
                    updated_at = CURRENT_TIMESTAMP
            """, (
                budget_id,
                limit_usd,
                budget.spent_usd,
                1 if hard_limit else 0,
                alert_threshold,
                reset_period,
                budget.last_reset.isoformat() if budget.last_reset else None,
            ))

        self._budgets[budget_id] = budget
        logger.info(f"Budget set: {budget_id} = ${limit_usd} (hard_limit={hard_limit})")
        return budget

    def get_budget(self, budget_id: str) -> Optional[Budget]:
        """Get a budget by ID."""
        self._check_reset(budget_id)
        return self._budgets.get(budget_id)

    def _check_reset(self, budget_id: str) -> None:
        """Check if budget needs reset based on period."""
        budget = self._budgets.get(budget_id)
        if not budget or not budget.last_reset:
            return

        now = datetime.utcnow()
        should_reset = False

        if budget.reset_period == "daily":
            should_reset = budget.last_reset.date() < now.date()
        elif budget.reset_period == "monthly":
            should_reset = (budget.last_reset.year, budget.last_reset.month) < (now.year, now.month)

        if should_reset:
            self._reset_budget(budget_id)

    def _reset_budget(self, budget_id: str) -> None:
        """Reset a budget's spent amount."""
        budget = self._budgets.get(budget_id)
        if not budget:
            return

        budget.spent_usd = 0.0
        budget.last_reset = datetime.utcnow()

        with self._tracker._cursor() as cur:
            cur.execute("""
                UPDATE cost_budgets
                SET spent_usd = 0.0, last_reset = ?, updated_at = CURRENT_TIMESTAMP
                WHERE budget_id = ?
            """, (budget.last_reset.isoformat(), budget_id))

        logger.info(f"Budget reset: {budget_id}")

    def add_spent(self, budget_id: str, amount_usd: float) -> None:
        """Add spent amount to a budget."""
        self._check_reset(budget_id)
        budget = self._budgets.get(budget_id)
        if not budget:
            return

        budget.spent_usd += amount_usd

        with self._tracker._cursor() as cur:
            cur.execute("""
                UPDATE cost_budgets
                SET spent_usd = spent_usd + ?, updated_at = CURRENT_TIMESTAMP
                WHERE budget_id = ?
            """, (amount_usd, budget_id))

    def check_budget_ok(
        self,
        budget_id: str,
        estimated_cost: float = 0.0
    ) -> bool:
        """
        Check if a budget allows the estimated cost.

        Returns True if:
        - Budget doesn't exist (no limit)
        - Budget is not hard_limit
        - Budget has remaining capacity for estimated_cost

        Returns False if:
        - Budget is hard_limit AND would be exceeded
        """
        self._check_reset(budget_id)
        budget = self._budgets.get(budget_id)

        if not budget:
            return True  # No budget = no limit

        if not budget.hard_limit:
            return True  # Soft limit = allow but alert

        remaining = budget.remaining()
        return remaining >= estimated_cost

    def get_budget_status(self, budget_id: str) -> Dict[str, Any]:
        """Get current status of a budget."""
        self._check_reset(budget_id)
        budget = self._budgets.get(budget_id)

        if not budget:
            return {"budget_id": budget_id, "exists": False}

        return {
            "budget_id": budget_id,
            "exists": True,
            "limit_usd": budget.limit_usd,
            "spent_usd": round(budget.spent_usd, 4),
            "remaining_usd": round(budget.remaining(), 4),
            "percent_used": round((budget.spent_usd / budget.limit_usd) * 100, 1) if budget.limit_usd > 0 else 0,
            "hard_limit": budget.hard_limit,
            "is_exceeded": budget.is_exceeded(),
            "should_alert": budget.should_alert(),
            "reset_period": budget.reset_period,
            "last_reset": budget.last_reset.isoformat() if budget.last_reset else None,
        }

    def get_all_budgets(self) -> List[Dict[str, Any]]:
        """Get status of all budgets."""
        return [self.get_budget_status(bid) for bid in self._budgets.keys()]


# Singleton budget manager
_budget_manager: Optional[BudgetManager] = None


def get_budget_manager() -> BudgetManager:
    """Get the singleton budget manager instance."""
    global _budget_manager
    if _budget_manager is None:
        tracker = get_cost_tracker()
        _budget_manager = BudgetManager(tracker)
    return _budget_manager


def check_budget_before_llm_call(
    estimated_tokens: int = 5000,
    model: str = "claude-sonnet-4-20250514",
    budget_id: str = "daily"
) -> Tuple[bool, Optional[str]]:
    """
    Pre-flight check before making an LLM call.

    Args:
        estimated_tokens: Estimated total tokens (input + output)
        model: Model to use for cost estimation
        budget_id: Budget to check against

    Returns:
        (ok: bool, error_message: Optional[str])
    """
    try:
        manager = get_budget_manager()
        tracker = get_cost_tracker()

        # Estimate cost (assume 50/50 input/output split)
        input_tokens = estimated_tokens // 2
        output_tokens = estimated_tokens - input_tokens
        estimated_cost = tracker.calculate_cost(model, input_tokens, output_tokens)

        if manager.check_budget_ok(budget_id, estimated_cost):
            return True, None
        else:
            budget = manager.get_budget(budget_id)
            remaining = budget.remaining() if budget else 0
            return False, f"Budget '{budget_id}' exceeded. Remaining: ${remaining:.4f}, Estimated: ${estimated_cost:.4f}"

    except Exception as e:
        logger.warning(f"Budget check failed: {e}")
        return True, None  # Fail open - allow call if budget check fails


class BudgetExceededException(Exception):
    """Raised when a hard budget limit is exceeded."""
    pass
