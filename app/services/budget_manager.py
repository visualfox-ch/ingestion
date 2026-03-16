"""
Budget Manager Service

Manages spending limits and alerts for API usage.
Prevents runaway costs in autonomous operations.

Usage:
    from app.services.budget_manager import get_budget_manager

    manager = get_budget_manager()

    # Set a monthly budget
    manager.set_budget("agent", monthly_limit=50.0, alert_threshold=0.8)

    # Check before making a call
    if manager.can_spend("agent", estimated_cost=0.05):
        # Make the API call
        ...

    # Get budget status
    status = manager.get_budget_status("agent")
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
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class BudgetPeriod(str, Enum):
    """Budget time periods."""
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class AlertLevel(str, Enum):
    """Alert severity levels."""
    INFO = "info"           # 50% of budget
    WARNING = "warning"     # 80% of budget
    CRITICAL = "critical"   # 95% of budget
    EXCEEDED = "exceeded"   # 100%+ of budget


@dataclass
class Budget:
    """A budget configuration."""
    feature: str
    period: BudgetPeriod = BudgetPeriod.MONTHLY
    limit_usd: float = 100.0
    alert_threshold: float = 0.8  # Alert at 80%
    hard_limit: bool = False       # If True, block requests when exceeded
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "feature": self.feature,
            "period": self.period.value,
            "limit_usd": self.limit_usd,
            "alert_threshold": self.alert_threshold,
            "hard_limit": self.hard_limit,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass
class BudgetStatus:
    """Current status of a budget."""
    feature: str
    period: BudgetPeriod
    limit_usd: float
    spent_usd: float
    remaining_usd: float
    usage_percent: float
    alert_level: AlertLevel
    hard_limit: bool
    period_start: datetime
    period_end: datetime
    is_blocked: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "feature": self.feature,
            "period": self.period.value,
            "limit_usd": round(self.limit_usd, 2),
            "spent_usd": round(self.spent_usd, 4),
            "remaining_usd": round(self.remaining_usd, 4),
            "usage_percent": round(self.usage_percent, 1),
            "alert_level": self.alert_level.value,
            "hard_limit": self.hard_limit,
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "is_blocked": self.is_blocked,
        }


@dataclass
class BudgetAlert:
    """A budget alert notification."""
    id: Optional[int] = None
    feature: str = ""
    level: AlertLevel = AlertLevel.INFO
    message: str = ""
    spent_usd: float = 0.0
    limit_usd: float = 0.0
    usage_percent: float = 0.0
    timestamp: datetime = field(default_factory=datetime.utcnow)
    acknowledged: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "feature": self.feature,
            "level": self.level.value,
            "message": self.message,
            "spent_usd": round(self.spent_usd, 4),
            "limit_usd": round(self.limit_usd, 2),
            "usage_percent": round(self.usage_percent, 1),
            "timestamp": self.timestamp.isoformat(),
            "acknowledged": self.acknowledged,
        }


class BudgetManager:
    """
    Manages spending budgets and alerts.

    Features:
    - Set daily/weekly/monthly budgets per feature
    - Alert thresholds (50%, 80%, 95%)
    - Hard limits that block requests
    - Alert history and acknowledgment
    - Telegram notifications (optional)
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        alert_callback: Optional[Callable[[BudgetAlert], None]] = None,
    ):
        """
        Initialize budget manager.

        Args:
            db_path: Path to SQLite database
            alert_callback: Function to call when alerts are triggered
        """
        self._db_path = Path(
            db_path or os.environ.get(
                "BUDGET_MANAGER_DB",
                "/brain/system/state/budget_manager.db"
            )
        )
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._alert_callback = alert_callback
        self._alert_cache: Dict[str, AlertLevel] = {}  # Track last alert level
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
            # Budgets table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS budgets (
                    feature TEXT PRIMARY KEY,
                    period TEXT NOT NULL,
                    limit_usd REAL NOT NULL,
                    alert_threshold REAL DEFAULT 0.8,
                    hard_limit INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            # Alerts table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS budget_alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    feature TEXT NOT NULL,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL,
                    spent_usd REAL NOT NULL,
                    limit_usd REAL NOT NULL,
                    usage_percent REAL NOT NULL,
                    timestamp TEXT NOT NULL,
                    acknowledged INTEGER DEFAULT 0
                )
            """)

            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_alerts_feature
                ON budget_alerts(feature)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_alerts_timestamp
                ON budget_alerts(timestamp)
            """)

        logger.info(f"Budget manager initialized: {self._db_path}")

    def set_budget(
        self,
        feature: str,
        limit_usd: float,
        period: BudgetPeriod = BudgetPeriod.MONTHLY,
        alert_threshold: float = 0.8,
        hard_limit: bool = False,
    ) -> Budget:
        """
        Set or update a budget for a feature.

        Args:
            feature: Feature name (e.g., "agent", "voice", "embedding")
            limit_usd: Maximum spend in USD
            period: Budget period (daily, weekly, monthly)
            alert_threshold: Percentage at which to trigger alerts (0.0-1.0)
            hard_limit: If True, block requests when budget exceeded

        Returns:
            Budget configuration
        """
        now = datetime.utcnow()

        budget = Budget(
            feature=feature,
            period=period,
            limit_usd=limit_usd,
            alert_threshold=alert_threshold,
            hard_limit=hard_limit,
            created_at=now,
            updated_at=now,
        )

        with self._cursor() as cur:
            cur.execute("""
                INSERT INTO budgets
                (feature, period, limit_usd, alert_threshold, hard_limit, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(feature) DO UPDATE SET
                    period = excluded.period,
                    limit_usd = excluded.limit_usd,
                    alert_threshold = excluded.alert_threshold,
                    hard_limit = excluded.hard_limit,
                    updated_at = excluded.updated_at
            """, (
                feature,
                period.value,
                limit_usd,
                alert_threshold,
                1 if hard_limit else 0,
                now.isoformat(),
                now.isoformat(),
            ))

        logger.info(
            f"Budget set: {feature} = ${limit_usd:.2f}/{period.value} "
            f"(alert: {alert_threshold*100:.0f}%, hard: {hard_limit})"
        )

        return budget

    def get_budget(self, feature: str) -> Optional[Budget]:
        """Get budget configuration for a feature."""
        with self._cursor() as cur:
            cur.execute("SELECT * FROM budgets WHERE feature = ?", (feature,))
            row = cur.fetchone()

            if row:
                return Budget(
                    feature=row["feature"],
                    period=BudgetPeriod(row["period"]),
                    limit_usd=row["limit_usd"],
                    alert_threshold=row["alert_threshold"],
                    hard_limit=bool(row["hard_limit"]),
                    created_at=datetime.fromisoformat(row["created_at"]),
                    updated_at=datetime.fromisoformat(row["updated_at"]),
                )
            return None

    def list_budgets(self) -> List[Budget]:
        """List all configured budgets."""
        with self._cursor() as cur:
            cur.execute("SELECT * FROM budgets ORDER BY feature")
            return [
                Budget(
                    feature=row["feature"],
                    period=BudgetPeriod(row["period"]),
                    limit_usd=row["limit_usd"],
                    alert_threshold=row["alert_threshold"],
                    hard_limit=bool(row["hard_limit"]),
                    created_at=datetime.fromisoformat(row["created_at"]),
                    updated_at=datetime.fromisoformat(row["updated_at"]),
                )
                for row in cur.fetchall()
            ]

    def delete_budget(self, feature: str) -> bool:
        """Delete a budget configuration."""
        with self._cursor() as cur:
            cur.execute("DELETE FROM budgets WHERE feature = ?", (feature,))
            deleted = cur.rowcount > 0

        if deleted:
            logger.info(f"Budget deleted: {feature}")
        return deleted

    def _get_period_range(self, period: BudgetPeriod) -> tuple[datetime, datetime]:
        """Get start and end dates for a budget period."""
        now = datetime.utcnow()

        if period == BudgetPeriod.DAILY:
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=1)
        elif period == BudgetPeriod.WEEKLY:
            start = now - timedelta(days=now.weekday())
            start = start.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=7)
        else:  # MONTHLY
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            if now.month == 12:
                end = start.replace(year=now.year + 1, month=1)
            else:
                end = start.replace(month=now.month + 1)

        return start, end

    def get_spent(self, feature: str, period: BudgetPeriod) -> float:
        """Get amount spent for a feature in the current period."""
        start, end = self._get_period_range(period)

        # Import here to avoid circular import
        from .cost_tracker import get_cost_tracker

        tracker = get_cost_tracker()
        summary = tracker.get_summary(
            start_date=start,
            end_date=end,
            feature=feature,
        )

        return summary.total_cost_usd

    def get_budget_status(self, feature: str) -> Optional[BudgetStatus]:
        """
        Get current budget status for a feature.

        Returns:
            BudgetStatus with spending info and alert level
        """
        budget = self.get_budget(feature)
        if not budget:
            return None

        start, end = self._get_period_range(budget.period)
        spent = self.get_spent(feature, budget.period)
        remaining = max(0, budget.limit_usd - spent)
        usage_percent = (spent / budget.limit_usd * 100) if budget.limit_usd > 0 else 0

        # Determine alert level
        if usage_percent >= 100:
            alert_level = AlertLevel.EXCEEDED
        elif usage_percent >= 95:
            alert_level = AlertLevel.CRITICAL
        elif usage_percent >= budget.alert_threshold * 100:
            alert_level = AlertLevel.WARNING
        elif usage_percent >= 50:
            alert_level = AlertLevel.INFO
        else:
            alert_level = AlertLevel.INFO

        # Check if blocked
        is_blocked = budget.hard_limit and usage_percent >= 100

        return BudgetStatus(
            feature=feature,
            period=budget.period,
            limit_usd=budget.limit_usd,
            spent_usd=spent,
            remaining_usd=remaining,
            usage_percent=usage_percent,
            alert_level=alert_level,
            hard_limit=budget.hard_limit,
            period_start=start,
            period_end=end,
            is_blocked=is_blocked,
        )

    def get_all_statuses(self) -> List[BudgetStatus]:
        """Get status for all configured budgets."""
        budgets = self.list_budgets()
        return [
            status
            for budget in budgets
            if (status := self.get_budget_status(budget.feature)) is not None
        ]

    def can_spend(
        self,
        feature: str,
        estimated_cost: float = 0.0,
    ) -> tuple[bool, Optional[str]]:
        """
        Check if a spend is allowed within budget.

        Args:
            feature: Feature name
            estimated_cost: Estimated cost of the operation

        Returns:
            (allowed, reason) - True if allowed, reason if not
        """
        status = self.get_budget_status(feature)

        # No budget = always allowed
        if not status:
            return True, None

        # Check hard limit
        if status.is_blocked:
            return False, f"Budget exceeded: ${status.spent_usd:.2f}/${status.limit_usd:.2f}"

        # Check if this spend would exceed
        if status.hard_limit:
            projected = status.spent_usd + estimated_cost
            if projected > status.limit_usd:
                return False, f"Would exceed budget: ${projected:.2f}/${status.limit_usd:.2f}"

        return True, None

    def check_and_alert(self, feature: str) -> Optional[BudgetAlert]:
        """
        Check budget status and trigger alert if needed.

        Only triggers alert if level has changed since last check.

        Returns:
            BudgetAlert if triggered, None otherwise
        """
        status = self.get_budget_status(feature)
        if not status:
            return None

        # Get last alert level for this feature
        last_level = self._alert_cache.get(feature)

        # Only alert on level changes or exceeded
        if status.alert_level == last_level and status.alert_level != AlertLevel.EXCEEDED:
            return None

        # Skip INFO level alerts
        if status.alert_level == AlertLevel.INFO:
            self._alert_cache[feature] = status.alert_level
            return None

        # Create alert
        alert = BudgetAlert(
            feature=feature,
            level=status.alert_level,
            message=self._format_alert_message(status),
            spent_usd=status.spent_usd,
            limit_usd=status.limit_usd,
            usage_percent=status.usage_percent,
            timestamp=datetime.utcnow(),
        )

        # Store alert
        self._store_alert(alert)

        # Update cache
        self._alert_cache[feature] = status.alert_level

        # Trigger callback
        if self._alert_callback:
            try:
                self._alert_callback(alert)
            except Exception as e:
                logger.error(f"Alert callback failed: {e}")

        logger.warning(f"Budget alert: {alert.message}")

        return alert

    def _format_alert_message(self, status: BudgetStatus) -> str:
        """Format alert message based on status."""
        if status.alert_level == AlertLevel.EXCEEDED:
            return (
                f"Budget EXCEEDED for {status.feature}: "
                f"${status.spent_usd:.2f}/${status.limit_usd:.2f} "
                f"({status.usage_percent:.0f}%)"
            )
        elif status.alert_level == AlertLevel.CRITICAL:
            return (
                f"Budget CRITICAL for {status.feature}: "
                f"${status.spent_usd:.2f}/${status.limit_usd:.2f} "
                f"({status.usage_percent:.0f}%) - only ${status.remaining_usd:.2f} remaining"
            )
        else:
            return (
                f"Budget WARNING for {status.feature}: "
                f"${status.spent_usd:.2f}/${status.limit_usd:.2f} "
                f"({status.usage_percent:.0f}%)"
            )

    def _store_alert(self, alert: BudgetAlert) -> None:
        """Store alert in database."""
        with self._cursor() as cur:
            cur.execute("""
                INSERT INTO budget_alerts
                (feature, level, message, spent_usd, limit_usd, usage_percent, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                alert.feature,
                alert.level.value,
                alert.message,
                alert.spent_usd,
                alert.limit_usd,
                alert.usage_percent,
                alert.timestamp.isoformat(),
            ))
            alert.id = cur.lastrowid

    def get_alerts(
        self,
        feature: Optional[str] = None,
        unacknowledged_only: bool = False,
        limit: int = 50,
    ) -> List[BudgetAlert]:
        """Get budget alerts."""
        query = "SELECT * FROM budget_alerts WHERE 1=1"
        params: List[Any] = []

        if feature:
            query += " AND feature = ?"
            params.append(feature)
        if unacknowledged_only:
            query += " AND acknowledged = 0"

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        with self._cursor() as cur:
            cur.execute(query, params)
            return [
                BudgetAlert(
                    id=row["id"],
                    feature=row["feature"],
                    level=AlertLevel(row["level"]),
                    message=row["message"],
                    spent_usd=row["spent_usd"],
                    limit_usd=row["limit_usd"],
                    usage_percent=row["usage_percent"],
                    timestamp=datetime.fromisoformat(row["timestamp"]),
                    acknowledged=bool(row["acknowledged"]),
                )
                for row in cur.fetchall()
            ]

    def acknowledge_alert(self, alert_id: int) -> bool:
        """Acknowledge an alert."""
        with self._cursor() as cur:
            cur.execute(
                "UPDATE budget_alerts SET acknowledged = 1 WHERE id = ?",
                (alert_id,)
            )
            return cur.rowcount > 0


# =============================================================================
# Singleton & Convenience Functions
# =============================================================================

_manager: Optional[BudgetManager] = None


def get_budget_manager() -> BudgetManager:
    """Get the singleton budget manager instance."""
    global _manager
    if _manager is None:
        _manager = BudgetManager()
    return _manager


def check_budget(feature: str, estimated_cost: float = 0.0) -> tuple[bool, Optional[str]]:
    """
    Convenience function to check if a spend is allowed.

    Returns:
        (allowed, reason)
    """
    manager = get_budget_manager()
    return manager.can_spend(feature, estimated_cost)
