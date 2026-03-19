"""
Fitness Agent Service (FitJarvis) - Phase 22A-04

Domain-specific service for fitness, health, and nutrition:
- Workout logging and tracking
- Nutrition tracking
- Fitness trends and analytics
- Exercise suggestions
- Goal tracking
"""

from dataclasses import dataclass
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta, date
import json

from ..observability import get_logger, log_with_context
from ..postgres_state import get_conn

logger = get_logger("jarvis.fitness_agent")


@dataclass
class WorkoutSummary:
    """Summary of a workout."""
    workout_type: str
    activity: str
    duration_minutes: int
    calories_burned: int
    intensity: str
    date: date


class FitnessAgentService:
    """
    FitJarvis - Fitness and Health Specialist Agent.

    Provides:
    - Workout logging (strength, cardio, etc.)
    - Nutrition tracking
    - Fitness trends and analytics
    - Personalized exercise suggestions
    - Goal management
    """

    def __init__(self):
        self._ensure_tables()

    def _ensure_tables(self):
        """Ensure fitness tables exist."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT EXISTS (
                            SELECT FROM information_schema.tables
                            WHERE table_name = 'jarvis_workouts'
                        )
                    """)
                    if not cur.fetchone()[0]:
                        log_with_context(logger, "info", "Fitness tables will be created by migration")
        except Exception as e:
            log_with_context(logger, "debug", "Table check failed", error=str(e))

    # =========================================================================
    # Workout Logging
    # =========================================================================

    def log_workout(
        self,
        workout_type: str,
        activity: str,
        duration_minutes: int = None,
        intensity: str = "moderate",
        calories_burned: int = None,
        distance_km: float = None,
        sets_reps: List[Dict[str, Any]] = None,
        notes: str = None,
        mood_before: str = None,
        mood_after: str = None,
        energy_level: int = None,
        user_id: str = "1"
    ) -> Dict[str, Any]:
        """
        Log a workout.

        Args:
            workout_type: Type (strength, cardio, hiit, yoga, stretching, sports)
            activity: Specific activity (e.g., "running", "bench press")
            duration_minutes: Duration in minutes
            intensity: low, moderate, high, max
            calories_burned: Estimated calories (auto-calculated if not provided)
            distance_km: Distance for cardio
            sets_reps: For strength training [{"exercise": "...", "sets": 3, "reps": 10, "weight_kg": 50}]
            notes: Additional notes
            mood_before/after: Mood tracking
            energy_level: 1-10 scale
        """
        # Auto-estimate calories if not provided
        if not calories_burned and duration_minutes:
            calories_burned = self._estimate_calories(workout_type, intensity, duration_minutes)

        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO jarvis_workouts
                        (user_id, workout_type, activity, duration_minutes, intensity,
                         calories_burned, distance_km, sets_reps, notes,
                         mood_before, mood_after, energy_level)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id, workout_date
                    """, (
                        user_id, workout_type, activity, duration_minutes, intensity,
                        calories_burned, distance_km,
                        json.dumps(sets_reps) if sets_reps else None,
                        notes, mood_before, mood_after, energy_level
                    ))
                    result = cur.fetchone()
                    conn.commit()

                    # Get streak info
                    streak = self._get_workout_streak(user_id)

                    log_with_context(logger, "info", "Workout logged",
                                   workout_type=workout_type, activity=activity)

                    return {
                        "success": True,
                        "workout_id": result[0],
                        "date": result[1].isoformat(),
                        "workout_type": workout_type,
                        "activity": activity,
                        "duration_minutes": duration_minutes,
                        "calories_burned": calories_burned,
                        "streak_days": streak,
                        "message": f"Workout logged! {calories_burned or 0} kcal burned. Streak: {streak} days"
                    }

        except Exception as e:
            log_with_context(logger, "error", "Workout logging failed", error=str(e))
            return {"success": False, "error": str(e)}

    def _estimate_calories(self, workout_type: str, intensity: str, duration: int) -> int:
        """Estimate calories burned based on workout type and intensity."""
        # Base calories per minute by workout type
        base_rates = {
            "cardio": 8,
            "hiit": 12,
            "strength": 5,
            "yoga": 3,
            "stretching": 2,
            "sports": 7
        }

        # Intensity multipliers
        intensity_mult = {
            "low": 0.7,
            "moderate": 1.0,
            "high": 1.3,
            "max": 1.5
        }

        base = base_rates.get(workout_type, 5)
        mult = intensity_mult.get(intensity, 1.0)

        return int(base * mult * duration)

    def _get_workout_streak(self, user_id: str) -> int:
        """Calculate current workout streak in days."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        WITH daily_workouts AS (
                            SELECT DISTINCT workout_date
                            FROM jarvis_workouts
                            WHERE user_id = %s
                            ORDER BY workout_date DESC
                        )
                        SELECT COUNT(*) FROM (
                            SELECT workout_date,
                                   workout_date - (ROW_NUMBER() OVER (ORDER BY workout_date DESC))::int AS grp
                            FROM daily_workouts
                        ) sub
                        WHERE grp = (
                            SELECT workout_date - (ROW_NUMBER() OVER (ORDER BY workout_date DESC))::int
                            FROM daily_workouts
                            LIMIT 1
                        )
                    """, (user_id,))
                    result = cur.fetchone()
                    return result[0] if result else 0
        except:
            return 0

    # =========================================================================
    # Fitness Trends
    # =========================================================================

    def get_fitness_trends(
        self,
        period: str = "week",
        trend_type: str = "workouts",
        user_id: str = "1"
    ) -> Dict[str, Any]:
        """
        Get fitness trends and analytics.

        Args:
            period: "week", "month", "quarter", "year"
            trend_type: "workouts", "calories", "nutrition", "weight", "all"
        """
        days_map = {"week": 7, "month": 30, "quarter": 90, "year": 365}
        days = days_map.get(period, 7)

        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    trends = {"period": period, "days": days}

                    if trend_type in ["workouts", "all"]:
                        # Workout stats
                        cur.execute("""
                            SELECT
                                COUNT(*) as total_workouts,
                                COALESCE(SUM(duration_minutes), 0) as total_minutes,
                                COALESCE(SUM(calories_burned), 0) as total_calories,
                                COALESCE(AVG(duration_minutes), 0) as avg_duration,
                                COUNT(DISTINCT workout_date) as active_days
                            FROM jarvis_workouts
                            WHERE user_id = %s
                              AND workout_date >= CURRENT_DATE - INTERVAL '%s days'
                        """, (user_id, days))
                        row = cur.fetchone()

                        trends["workouts"] = {
                            "total": row[0],
                            "total_minutes": row[1],
                            "total_calories": row[2],
                            "avg_duration_minutes": round(row[3]),
                            "active_days": row[4],
                            "consistency_pct": round((row[4] / days) * 100, 1)
                        }

                        # By type breakdown
                        cur.execute("""
                            SELECT workout_type, COUNT(*), SUM(calories_burned)
                            FROM jarvis_workouts
                            WHERE user_id = %s
                              AND workout_date >= CURRENT_DATE - INTERVAL '%s days'
                            GROUP BY workout_type
                            ORDER BY COUNT(*) DESC
                        """, (user_id, days))
                        trends["workouts"]["by_type"] = [
                            {"type": r[0], "count": r[1], "calories": r[2] or 0}
                            for r in cur.fetchall()
                        ]

                    if trend_type in ["calories", "nutrition", "all"]:
                        # Nutrition stats
                        cur.execute("""
                            SELECT
                                COUNT(*) as total_meals,
                                COALESCE(AVG(total_calories), 0) as avg_daily_calories,
                                COALESCE(AVG(protein_g), 0) as avg_protein,
                                COALESCE(AVG(carbs_g), 0) as avg_carbs,
                                COALESCE(AVG(fat_g), 0) as avg_fat
                            FROM jarvis_nutrition
                            WHERE user_id = %s
                              AND meal_date >= CURRENT_DATE - INTERVAL '%s days'
                        """, (user_id, days))
                        row = cur.fetchone()

                        trends["nutrition"] = {
                            "total_meals": row[0],
                            "avg_daily_calories": round(row[1]),
                            "avg_protein_g": round(row[2], 1),
                            "avg_carbs_g": round(row[3], 1),
                            "avg_fat_g": round(row[4], 1)
                        }

                    if trend_type in ["weight", "all"]:
                        # Body metrics trend
                        cur.execute("""
                            SELECT weight_kg, body_fat_pct, measured_at
                            FROM jarvis_body_metrics
                            WHERE user_id = %s
                              AND measured_at >= CURRENT_DATE - INTERVAL '%s days'
                            ORDER BY measured_at DESC
                            LIMIT 10
                        """, (user_id, days))
                        metrics = cur.fetchall()

                        if metrics:
                            latest = metrics[0]
                            oldest = metrics[-1]
                            trends["body"] = {
                                "current_weight_kg": latest[0],
                                "current_body_fat_pct": latest[1],
                                "weight_change_kg": round(latest[0] - oldest[0], 1) if latest[0] and oldest[0] else None,
                                "measurements": len(metrics)
                            }

                    return {"success": True, **trends}

        except Exception as e:
            log_with_context(logger, "error", "Trends query failed", error=str(e))
            return {"success": False, "error": str(e)}

    # =========================================================================
    # Nutrition Tracking
    # =========================================================================

    def track_nutrition(
        self,
        meal_type: str,
        food_items: List[Dict[str, Any]],
        notes: str = None,
        user_id: str = "1"
    ) -> Dict[str, Any]:
        """
        Track a meal.

        Args:
            meal_type: breakfast, lunch, dinner, snack
            food_items: [{"name": "...", "calories": 200, "protein_g": 20, ...}]
            notes: Additional notes
        """
        # Calculate totals
        total_calories = sum(f.get("calories", 0) for f in food_items)
        total_protein = sum(f.get("protein_g", 0) for f in food_items)
        total_carbs = sum(f.get("carbs_g", 0) for f in food_items)
        total_fat = sum(f.get("fat_g", 0) for f in food_items)

        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO jarvis_nutrition
                        (user_id, meal_type, food_items, total_calories,
                         protein_g, carbs_g, fat_g, notes)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                    """, (
                        user_id, meal_type, json.dumps(food_items),
                        total_calories, total_protein, total_carbs, total_fat, notes
                    ))
                    meal_id = cur.fetchone()[0]

                    # Get today's totals
                    cur.execute("""
                        SELECT SUM(total_calories), SUM(protein_g), SUM(carbs_g), SUM(fat_g)
                        FROM jarvis_nutrition
                        WHERE user_id = %s AND meal_date = CURRENT_DATE
                    """, (user_id,))
                    today = cur.fetchone()

                    conn.commit()

                    return {
                        "success": True,
                        "meal_id": meal_id,
                        "meal_type": meal_type,
                        "items_count": len(food_items),
                        "meal_totals": {
                            "calories": total_calories,
                            "protein_g": total_protein,
                            "carbs_g": total_carbs,
                            "fat_g": total_fat
                        },
                        "today_totals": {
                            "calories": today[0] or 0,
                            "protein_g": today[1] or 0,
                            "carbs_g": today[2] or 0,
                            "fat_g": today[3] or 0
                        },
                        "message": f"{meal_type.capitalize()} logged: {total_calories} kcal"
                    }

        except Exception as e:
            log_with_context(logger, "error", "Nutrition tracking failed", error=str(e))
            return {"success": False, "error": str(e)}

    # =========================================================================
    # Exercise Suggestions
    # =========================================================================

    def suggest_exercise(
        self,
        category: str = None,
        muscle_groups: List[str] = None,
        difficulty: str = None,
        equipment: List[str] = None,
        avoid_recent: bool = True,
        limit: int = 5,
        user_id: str = "1"
    ) -> Dict[str, Any]:
        """
        Suggest exercises based on criteria and recent workout history.

        Args:
            category: strength, cardio, flexibility, balance
            muscle_groups: Target muscle groups
            difficulty: beginner, intermediate, advanced
            equipment: Available equipment
            avoid_recent: Avoid exercises done in last 2 days
            limit: Number of suggestions
        """
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    # Build query
                    query = """
                        SELECT name, category, muscle_groups, equipment,
                               difficulty, calories_per_minute, instructions, tips
                        FROM jarvis_exercise_library
                        WHERE 1=1
                    """
                    params = []

                    if category:
                        query += " AND category = %s"
                        params.append(category)

                    if difficulty:
                        query += " AND difficulty = %s"
                        params.append(difficulty)

                    if muscle_groups:
                        query += " AND muscle_groups ?| %s"
                        params.append(muscle_groups)

                    if equipment:
                        # Filter by available equipment
                        query += " AND (equipment = '[]' OR equipment ?| %s)"
                        params.append(equipment)

                    # Avoid recently done exercises
                    if avoid_recent:
                        query += """
                            AND name NOT IN (
                                SELECT DISTINCT activity FROM jarvis_workouts
                                WHERE user_id = %s AND workout_date >= CURRENT_DATE - 2
                            )
                        """
                        params.append(user_id)

                    query += " ORDER BY RANDOM() LIMIT %s"
                    params.append(limit)

                    cur.execute(query, tuple(params))

                    suggestions = []
                    for row in cur.fetchall():
                        suggestions.append({
                            "name": row[0],
                            "category": row[1],
                            "muscle_groups": row[2],
                            "equipment": row[3],
                            "difficulty": row[4],
                            "calories_per_minute": row[5],
                            "instructions": row[6],
                            "tips": row[7]
                        })

                    # Get recent workout context
                    cur.execute("""
                        SELECT workout_type, activity, workout_date
                        FROM jarvis_workouts
                        WHERE user_id = %s
                        ORDER BY created_at DESC
                        LIMIT 3
                    """, (user_id,))
                    recent = [{"type": r[0], "activity": r[1], "date": r[2].isoformat()} for r in cur.fetchall()]

                    return {
                        "success": True,
                        "suggestions": suggestions,
                        "count": len(suggestions),
                        "recent_workouts": recent,
                        "criteria": {
                            "category": category,
                            "muscle_groups": muscle_groups,
                            "difficulty": difficulty,
                            "equipment": equipment
                        }
                    }

        except Exception as e:
            log_with_context(logger, "error", "Exercise suggestion failed", error=str(e))
            return {"success": False, "error": str(e)}

    # =========================================================================
    # Goals & Progress
    # =========================================================================

    def set_fitness_goal(
        self,
        goal_type: str,
        target_metric: str,
        target_value: float,
        current_value: float = None,
        target_date: str = None,
        unit: str = None,
        user_id: str = "1"
    ) -> Dict[str, Any]:
        """Set a fitness goal."""
        try:
            target_dt = datetime.strptime(target_date, "%Y-%m-%d").date() if target_date else None

            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO jarvis_fitness_goals
                        (user_id, goal_type, target_metric, target_value, current_value, target_date, unit)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                    """, (user_id, goal_type, target_metric, target_value, current_value, target_dt, unit))
                    goal_id = cur.fetchone()[0]
                    conn.commit()

                    return {
                        "success": True,
                        "goal_id": goal_id,
                        "goal_type": goal_type,
                        "target": f"{target_value} {unit or ''}",
                        "message": f"Goal set: {target_metric} -> {target_value} {unit or ''}"
                    }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_fitness_goals(self, status: str = "active", user_id: str = "1") -> Dict[str, Any]:
        """Get fitness goals."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT id, goal_type, target_metric, target_value, current_value,
                               unit, target_date, progress_pct, status
                        FROM jarvis_fitness_goals
                        WHERE user_id = %s AND status = %s
                        ORDER BY target_date ASC NULLS LAST
                    """, (user_id, status))

                    goals = []
                    for row in cur.fetchall():
                        goals.append({
                            "id": row[0],
                            "type": row[1],
                            "metric": row[2],
                            "target": row[3],
                            "current": row[4],
                            "unit": row[5],
                            "target_date": row[6].isoformat() if row[6] else None,
                            "progress_pct": row[7],
                            "status": row[8]
                        })

                    return {"success": True, "goals": goals, "count": len(goals)}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_fitness_stats(self, user_id: str = "1") -> Dict[str, Any]:
        """Get overall fitness statistics."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    # Overall stats
                    cur.execute("""
                        SELECT
                            COUNT(*) as total_workouts,
                            SUM(duration_minutes) as total_minutes,
                            SUM(calories_burned) as total_calories,
                            MIN(workout_date) as first_workout
                        FROM jarvis_workouts
                        WHERE user_id = %s
                    """, (user_id,))
                    overall = cur.fetchone()

                    # This week
                    cur.execute("""
                        SELECT COUNT(*), SUM(calories_burned)
                        FROM jarvis_workouts
                        WHERE user_id = %s AND workout_date >= CURRENT_DATE - 7
                    """, (user_id,))
                    week = cur.fetchone()

                    # Streak
                    streak = self._get_workout_streak(user_id)

                    # Active goals
                    cur.execute("""
                        SELECT COUNT(*) FROM jarvis_fitness_goals
                        WHERE user_id = %s AND status = 'active'
                    """, (user_id,))
                    active_goals = cur.fetchone()[0]

                    return {
                        "success": True,
                        "overall": {
                            "total_workouts": overall[0],
                            "total_minutes": overall[1] or 0,
                            "total_calories": overall[2] or 0,
                            "member_since": overall[3].isoformat() if overall[3] else None
                        },
                        "this_week": {
                            "workouts": week[0],
                            "calories": week[1] or 0
                        },
                        "streak_days": streak,
                        "active_goals": active_goals
                    }

        except Exception as e:
            return {"success": False, "error": str(e)}


# Singleton
_service: Optional[FitnessAgentService] = None


def get_fitness_agent_service() -> FitnessAgentService:
    """Get or create fitness agent service singleton."""
    global _service
    if _service is None:
        _service = FitnessAgentService()
    return _service
