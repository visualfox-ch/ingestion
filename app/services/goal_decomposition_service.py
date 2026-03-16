"""
Goal Decomposition Service - Tier 2 Feature

Enables proactive goal tracking by:
- Breaking long-term goals into milestones
- Tracking progress automatically
- Suggesting adjustments based on patterns
- Providing proactive reminders

Example:
    "Lose 5kg in 12 weeks" ->
    - Week 1-2: Establish baseline, -0.5kg target
    - Week 3-4: Build habits, -1kg target
    - Week 5-8: Accelerate, -2kg target
    - Week 9-12: Maintain momentum, -1.5kg target
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from enum import Enum
import json
import re

from ..observability import get_logger, log_with_context
from ..postgres_state import get_conn

logger = get_logger("jarvis.goal_decomposition")


class GoalStatus(Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    PAUSED = "paused"
    ABANDONED = "abandoned"


class MilestoneStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    OVERDUE = "overdue"


class GoalCategory(Enum):
    FITNESS = "fitness"
    HEALTH = "health"
    WORK = "work"
    LEARNING = "learning"
    FINANCE = "finance"
    RELATIONSHIP = "relationship"
    HABIT = "habit"
    PROJECT = "project"
    OTHER = "other"


@dataclass
class Milestone:
    """A single milestone within a goal."""
    id: Optional[int] = None
    goal_id: int = 0
    title: str = ""
    description: str = ""
    target_value: Optional[float] = None
    target_unit: str = ""
    due_date: Optional[datetime] = None
    status: MilestoneStatus = MilestoneStatus.PENDING
    order_index: int = 0
    progress_value: Optional[float] = None
    completed_at: Optional[datetime] = None
    notes: str = ""


@dataclass
class Goal:
    """A long-term goal with milestones."""
    id: Optional[int] = None
    user_id: str = "micha"
    title: str = ""
    description: str = ""
    category: GoalCategory = GoalCategory.OTHER
    target_value: Optional[float] = None
    target_unit: str = ""
    current_value: Optional[float] = None
    start_date: datetime = field(default_factory=datetime.now)
    target_date: Optional[datetime] = None
    status: GoalStatus = GoalStatus.ACTIVE
    milestones: List[Milestone] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)


class GoalDecompositionService:
    """
    Service for creating, decomposing, and tracking goals.

    Usage:
        service = GoalDecompositionService()

        # Create a goal
        goal = service.create_goal(
            user_id="micha",
            title="Lose 5kg",
            target_value=5.0,
            target_unit="kg",
            target_weeks=12,
            category=GoalCategory.FITNESS
        )

        # Decompose into milestones
        milestones = service.decompose_goal(goal.id)

        # Track progress
        service.record_progress(goal.id, current_value=2.5)

        # Get status
        status = service.get_goal_status(goal.id)
    """

    def __init__(self):
        self._ensure_tables()

    def _ensure_tables(self):
        """Ensure goal tables exist."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    # Check if tables exist
                    cur.execute("""
                        SELECT EXISTS (
                            SELECT FROM information_schema.tables
                            WHERE table_name = 'jarvis_goals'
                        )
                    """)
                    if not cur.fetchone()["exists"]:
                        self._create_tables(cur)
                        conn.commit()
        except Exception as e:
            log_with_context(logger, "warning", "Could not ensure goal tables", error=str(e))

    def _create_tables(self, cur):
        """Create goal tracking tables."""
        cur.execute("""
            CREATE TABLE IF NOT EXISTS jarvis_goals (
                id SERIAL PRIMARY KEY,
                user_id VARCHAR(100) NOT NULL DEFAULT 'micha',
                title VARCHAR(500) NOT NULL,
                description TEXT,
                category VARCHAR(50) DEFAULT 'other',
                target_value NUMERIC,
                target_unit VARCHAR(50),
                current_value NUMERIC,
                start_date TIMESTAMP DEFAULT NOW(),
                target_date TIMESTAMP,
                status VARCHAR(20) DEFAULT 'active',
                tags JSONB DEFAULT '[]'::jsonb,
                metadata JSONB DEFAULT '{}'::jsonb,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS jarvis_goal_milestones (
                id SERIAL PRIMARY KEY,
                goal_id INTEGER REFERENCES jarvis_goals(id) ON DELETE CASCADE,
                title VARCHAR(500) NOT NULL,
                description TEXT,
                target_value NUMERIC,
                target_unit VARCHAR(50),
                due_date TIMESTAMP,
                status VARCHAR(20) DEFAULT 'pending',
                order_index INTEGER DEFAULT 0,
                progress_value NUMERIC,
                completed_at TIMESTAMP,
                notes TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS jarvis_goal_progress (
                id SERIAL PRIMARY KEY,
                goal_id INTEGER REFERENCES jarvis_goals(id) ON DELETE CASCADE,
                milestone_id INTEGER REFERENCES jarvis_goal_milestones(id) ON DELETE SET NULL,
                value NUMERIC NOT NULL,
                unit VARCHAR(50),
                recorded_at TIMESTAMP DEFAULT NOW(),
                notes TEXT,
                source VARCHAR(100) DEFAULT 'manual'
            )
        """)

        cur.execute("CREATE INDEX IF NOT EXISTS idx_goals_user ON jarvis_goals(user_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_goals_status ON jarvis_goals(status)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_milestones_goal ON jarvis_goal_milestones(goal_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_progress_goal ON jarvis_goal_progress(goal_id)")

        log_with_context(logger, "info", "Created goal tracking tables")

    def create_goal(
        self,
        user_id: str,
        title: str,
        description: str = "",
        category: GoalCategory = GoalCategory.OTHER,
        target_value: Optional[float] = None,
        target_unit: str = "",
        current_value: Optional[float] = None,
        target_weeks: Optional[int] = None,
        target_date: Optional[datetime] = None,
        tags: Optional[List[str]] = None,
        auto_decompose: bool = True
    ) -> Goal:
        """Create a new goal, optionally decomposing into milestones."""
        if target_weeks and not target_date:
            target_date = datetime.now() + timedelta(weeks=target_weeks)

        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO jarvis_goals
                        (user_id, title, description, category, target_value, target_unit,
                         current_value, target_date, tags)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id, created_at
                    """, (
                        user_id, title, description, category.value,
                        target_value, target_unit, current_value,
                        target_date, json.dumps(tags or [])
                    ))
                    row = cur.fetchone()
                    conn.commit()

                    goal = Goal(
                        id=row["id"],
                        user_id=user_id,
                        title=title,
                        description=description,
                        category=category,
                        target_value=target_value,
                        target_unit=target_unit,
                        current_value=current_value,
                        target_date=target_date,
                        tags=tags or [],
                        created_at=row["created_at"]
                    )

                    log_with_context(logger, "info", "Goal created",
                                   goal_id=goal.id, title=title, category=category.value)

                    # Auto-decompose if requested and we have target info
                    if auto_decompose and target_value and target_date:
                        goal.milestones = self.decompose_goal(goal.id)

                    return goal

        except Exception as e:
            log_with_context(logger, "error", "Failed to create goal", error=str(e))
            raise

    def decompose_goal(
        self,
        goal_id: int,
        num_milestones: Optional[int] = None
    ) -> List[Milestone]:
        """
        Decompose a goal into milestones based on timeline and target.

        Uses intelligent decomposition:
        - Early milestones: Smaller targets (habit building)
        - Middle milestones: Larger targets (momentum)
        - Final milestones: Smaller targets (consolidation)
        """
        goal = self.get_goal(goal_id)
        if not goal:
            return []

        if not goal.target_date or not goal.target_value:
            log_with_context(logger, "warning", "Cannot decompose goal without target",
                           goal_id=goal_id)
            return []

        # Calculate duration and determine milestone count
        duration_days = (goal.target_date - datetime.now()).days
        if duration_days <= 0:
            return []

        # Determine number of milestones (default: ~1 per 2 weeks, min 2, max 12)
        if not num_milestones:
            num_milestones = max(2, min(12, duration_days // 14))

        # Calculate milestone intervals
        interval_days = duration_days / num_milestones

        # Distribute target value with acceleration curve
        # Pattern: 10%, 15%, 20%, 25%, 20%, 10% (roughly)
        weights = self._calculate_distribution_weights(num_milestones)
        cumulative_target = goal.current_value or 0

        milestones = []
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    # Clear existing milestones
                    cur.execute("DELETE FROM jarvis_goal_milestones WHERE goal_id = %s", (goal_id,))

                    for i in range(num_milestones):
                        # Calculate this milestone's target
                        milestone_delta = goal.target_value * weights[i]
                        cumulative_target += milestone_delta

                        # Calculate due date
                        due_date = datetime.now() + timedelta(days=int(interval_days * (i + 1)))

                        # Generate title based on phase
                        phase = self._get_phase_name(i, num_milestones)
                        title = f"{phase}: {milestone_delta:.1f} {goal.target_unit}"

                        cur.execute("""
                            INSERT INTO jarvis_goal_milestones
                            (goal_id, title, target_value, target_unit, due_date, order_index)
                            VALUES (%s, %s, %s, %s, %s, %s)
                            RETURNING id
                        """, (
                            goal_id, title, cumulative_target, goal.target_unit,
                            due_date, i
                        ))
                        row = cur.fetchone()

                        milestones.append(Milestone(
                            id=row["id"],
                            goal_id=goal_id,
                            title=title,
                            target_value=cumulative_target,
                            target_unit=goal.target_unit,
                            due_date=due_date,
                            order_index=i
                        ))

                    conn.commit()

        except Exception as e:
            log_with_context(logger, "error", "Failed to decompose goal", error=str(e))
            raise

        log_with_context(logger, "info", "Goal decomposed",
                       goal_id=goal_id, milestones=len(milestones))
        return milestones

    def _calculate_distribution_weights(self, n: int) -> List[float]:
        """Calculate weight distribution for milestones (sums to 1.0)."""
        if n <= 2:
            return [0.5] * n

        # Bell curve distribution: easier start and end
        weights = []
        mid = n / 2
        for i in range(n):
            # Distance from middle, normalized
            dist = abs(i - mid) / mid
            # Higher weight near middle
            w = 1.0 - (dist * 0.6)  # 0.4 to 1.0 range
            weights.append(w)

        # Normalize to sum to 1.0
        total = sum(weights)
        return [w / total for w in weights]

    def _get_phase_name(self, index: int, total: int) -> str:
        """Get phase name based on position in goal timeline."""
        progress = index / total
        if progress < 0.2:
            return "Foundation"
        elif progress < 0.4:
            return "Build Momentum"
        elif progress < 0.7:
            return "Accelerate"
        elif progress < 0.9:
            return "Push Through"
        else:
            return "Final Sprint"

    def get_goal(self, goal_id: int) -> Optional[Goal]:
        """Get a goal by ID with its milestones."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT * FROM jarvis_goals WHERE id = %s
                    """, (goal_id,))
                    row = cur.fetchone()
                    if not row:
                        return None

                    goal = Goal(
                        id=row["id"],
                        user_id=row["user_id"],
                        title=row["title"],
                        description=row["description"] or "",
                        category=GoalCategory(row["category"]),
                        target_value=float(row["target_value"]) if row["target_value"] else None,
                        target_unit=row["target_unit"] or "",
                        current_value=float(row["current_value"]) if row["current_value"] else None,
                        start_date=row["start_date"],
                        target_date=row["target_date"],
                        status=GoalStatus(row["status"]),
                        tags=row["tags"] or [],
                        created_at=row["created_at"],
                        updated_at=row["updated_at"]
                    )

                    # Load milestones
                    cur.execute("""
                        SELECT * FROM jarvis_goal_milestones
                        WHERE goal_id = %s
                        ORDER BY order_index
                    """, (goal_id,))

                    for m_row in cur.fetchall():
                        goal.milestones.append(Milestone(
                            id=m_row["id"],
                            goal_id=m_row["goal_id"],
                            title=m_row["title"],
                            description=m_row["description"] or "",
                            target_value=float(m_row["target_value"]) if m_row["target_value"] else None,
                            target_unit=m_row["target_unit"] or "",
                            due_date=m_row["due_date"],
                            status=MilestoneStatus(m_row["status"]),
                            order_index=m_row["order_index"],
                            progress_value=float(m_row["progress_value"]) if m_row["progress_value"] else None,
                            completed_at=m_row["completed_at"],
                            notes=m_row["notes"] or ""
                        ))

                    return goal

        except Exception as e:
            log_with_context(logger, "error", "Failed to get goal", error=str(e))
            return None

    def get_active_goals(self, user_id: str = "micha") -> List[Goal]:
        """Get all active goals for a user."""
        goals = []
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT id FROM jarvis_goals
                        WHERE user_id = %s AND status = 'active'
                        ORDER BY target_date ASC NULLS LAST
                    """, (user_id,))

                    for row in cur.fetchall():
                        goal = self.get_goal(row["id"])
                        if goal:
                            goals.append(goal)

        except Exception as e:
            log_with_context(logger, "error", "Failed to get active goals", error=str(e))

        return goals

    def record_progress(
        self,
        goal_id: int,
        current_value: float,
        notes: str = "",
        source: str = "manual"
    ) -> Dict[str, Any]:
        """Record progress on a goal."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    # Get goal info
                    cur.execute("SELECT target_unit FROM jarvis_goals WHERE id = %s", (goal_id,))
                    row = cur.fetchone()
                    if not row:
                        return {"success": False, "error": "Goal not found"}

                    target_unit = row["target_unit"]

                    # Record progress
                    cur.execute("""
                        INSERT INTO jarvis_goal_progress
                        (goal_id, value, unit, notes, source)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (goal_id, current_value, target_unit, notes, source))

                    # Update goal current value
                    cur.execute("""
                        UPDATE jarvis_goals
                        SET current_value = %s, updated_at = NOW()
                        WHERE id = %s
                    """, (current_value, goal_id))

                    # Check and update milestone statuses
                    self._update_milestone_statuses(cur, goal_id, current_value)

                    conn.commit()

                    log_with_context(logger, "info", "Progress recorded",
                                   goal_id=goal_id, value=current_value)

                    return {
                        "success": True,
                        "goal_id": goal_id,
                        "current_value": current_value,
                        "message": f"Progress recorded: {current_value} {target_unit}"
                    }

        except Exception as e:
            log_with_context(logger, "error", "Failed to record progress", error=str(e))
            return {"success": False, "error": str(e)}

    def _update_milestone_statuses(self, cur, goal_id: int, current_value: float):
        """Update milestone statuses based on current progress."""
        now = datetime.now()

        # Get milestones
        cur.execute("""
            SELECT id, target_value, due_date, status
            FROM jarvis_goal_milestones
            WHERE goal_id = %s
            ORDER BY order_index
        """, (goal_id,))

        for m in cur.fetchall():
            milestone_id = m["id"]
            target = float(m["target_value"]) if m["target_value"] else 0
            due_date = m["due_date"]
            current_status = m["status"]

            # Skip already completed
            if current_status == "completed":
                continue

            # Check if completed
            if current_value >= target:
                cur.execute("""
                    UPDATE jarvis_goal_milestones
                    SET status = 'completed', completed_at = NOW(), progress_value = %s
                    WHERE id = %s
                """, (current_value, milestone_id))
                continue

            # Check if overdue
            if due_date and due_date < now and current_status != "overdue":
                cur.execute("""
                    UPDATE jarvis_goal_milestones
                    SET status = 'overdue', progress_value = %s
                    WHERE id = %s
                """, (current_value, milestone_id))
                continue

            # Update to in_progress if it's the next one
            if current_status == "pending":
                cur.execute("""
                    UPDATE jarvis_goal_milestones
                    SET status = 'in_progress', progress_value = %s
                    WHERE id = %s
                """, (current_value, milestone_id))
                break  # Only one in_progress at a time

    def get_goal_status(self, goal_id: int) -> Dict[str, Any]:
        """Get comprehensive status of a goal."""
        goal = self.get_goal(goal_id)
        if not goal:
            return {"success": False, "error": "Goal not found"}

        now = datetime.now()

        # Calculate progress percentage
        progress_pct = 0.0
        if goal.target_value and goal.current_value:
            progress_pct = (goal.current_value / goal.target_value) * 100

        # Calculate time progress
        time_pct = 0.0
        if goal.target_date and goal.start_date:
            total_days = (goal.target_date - goal.start_date).days
            elapsed_days = (now - goal.start_date).days
            time_pct = (elapsed_days / total_days) * 100 if total_days > 0 else 0

        # Milestone summary
        completed_milestones = sum(1 for m in goal.milestones if m.status == MilestoneStatus.COMPLETED)
        overdue_milestones = sum(1 for m in goal.milestones if m.status == MilestoneStatus.OVERDUE)

        # Find current/next milestone
        current_milestone = None
        for m in goal.milestones:
            if m.status in [MilestoneStatus.IN_PROGRESS, MilestoneStatus.PENDING]:
                current_milestone = m
                break

        # Determine on-track status
        on_track = progress_pct >= time_pct * 0.9  # Within 10% of expected progress

        return {
            "success": True,
            "goal": {
                "id": goal.id,
                "title": goal.title,
                "category": goal.category.value,
                "status": goal.status.value,
            },
            "progress": {
                "current": goal.current_value,
                "target": goal.target_value,
                "unit": goal.target_unit,
                "percentage": round(progress_pct, 1),
            },
            "timeline": {
                "start": goal.start_date.isoformat() if goal.start_date else None,
                "target": goal.target_date.isoformat() if goal.target_date else None,
                "days_remaining": (goal.target_date - now).days if goal.target_date else None,
                "time_percentage": round(time_pct, 1),
            },
            "milestones": {
                "total": len(goal.milestones),
                "completed": completed_milestones,
                "overdue": overdue_milestones,
                "current": {
                    "title": current_milestone.title,
                    "target": current_milestone.target_value,
                    "due": current_milestone.due_date.isoformat() if current_milestone and current_milestone.due_date else None,
                } if current_milestone else None,
            },
            "on_track": on_track,
            "recommendation": self._generate_recommendation(goal, progress_pct, time_pct, on_track)
        }

    def _generate_recommendation(
        self,
        goal: Goal,
        progress_pct: float,
        time_pct: float,
        on_track: bool
    ) -> str:
        """Generate a recommendation based on goal status."""
        if progress_pct >= 100:
            return "Goal erreicht! Zeit zum Feiern."

        if on_track:
            if progress_pct > time_pct:
                return "Sehr gut! Du bist dem Zeitplan voraus."
            return "Du bist auf Kurs. Weiter so!"

        # Not on track
        gap = time_pct - progress_pct
        if gap < 10:
            return "Leicht hinter dem Plan. Ein kleiner Push diese Woche hilft."
        elif gap < 25:
            return "Du bist etwas zurück. Überleg ob du die nächsten Milestones anpassen willst."
        else:
            return "Deutlich hinter Plan. Wollen wir das Ziel oder den Zeitraum anpassen?"

    def update_goal_status(self, goal_id: int, status: GoalStatus) -> bool:
        """Update goal status."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE jarvis_goals
                        SET status = %s, updated_at = NOW()
                        WHERE id = %s
                    """, (status.value, goal_id))
                    conn.commit()
                    return True
        except Exception as e:
            log_with_context(logger, "error", "Failed to update goal status", error=str(e))
            return False

    def get_proactive_reminders(self, user_id: str = "micha") -> List[Dict[str, Any]]:
        """Get proactive reminders for goals needing attention."""
        reminders = []
        goals = self.get_active_goals(user_id)

        for goal in goals:
            status = self.get_goal_status(goal.id)
            if not status.get("success"):
                continue

            # Check for overdue milestones
            if status["milestones"]["overdue"] > 0:
                reminders.append({
                    "goal_id": goal.id,
                    "goal_title": goal.title,
                    "type": "overdue_milestone",
                    "priority": "high",
                    "message": f"Du hast {status['milestones']['overdue']} überfällige Milestone(s) für '{goal.title}'."
                })

            # Check if behind schedule
            if not status["on_track"]:
                reminders.append({
                    "goal_id": goal.id,
                    "goal_title": goal.title,
                    "type": "behind_schedule",
                    "priority": "medium",
                    "message": status["recommendation"]
                })

            # Check for upcoming milestone (within 3 days)
            current = status["milestones"].get("current")
            if current and current.get("due"):
                due_date = datetime.fromisoformat(current["due"])
                days_until = (due_date - datetime.now()).days
                if 0 < days_until <= 3:
                    reminders.append({
                        "goal_id": goal.id,
                        "goal_title": goal.title,
                        "type": "milestone_due_soon",
                        "priority": "medium",
                        "message": f"Milestone '{current['title']}' ist in {days_until} Tag(en) fällig."
                    })

        return reminders


# Singleton
_service: Optional[GoalDecompositionService] = None


def get_goal_service() -> GoalDecompositionService:
    """Get or create goal decomposition service singleton."""
    global _service
    if _service is None:
        _service = GoalDecompositionService()
    return _service
