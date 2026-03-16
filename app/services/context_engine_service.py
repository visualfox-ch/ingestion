"""
Context Engine Service - Tier 3 #10

Aggregates multiple context signals for mood-aware responses.
"Stressed" → different tools/tone than "Relaxed"

Context signals:
- Emotion (from EmotionTracker)
- Time of day (morning/afternoon/evening/night)
- Calendar load (free/busy)
- Energy level (estimated)
- Recent activity patterns

Produces:
- Aggregated context profile
- Tone/verbosity recommendations
- Tool priority adjustments
- Prompt injections
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timedelta
from enum import Enum
import uuid
import json

from ..observability import get_logger, log_with_context
from ..postgres_state import get_conn

logger = get_logger("jarvis.context_engine")


class Mood(str, Enum):
    CALM = "calm"
    STRESSED = "stressed"
    ENERGIZED = "energized"
    TIRED = "tired"
    FOCUSED = "focused"
    OVERWHELMED = "overwhelmed"
    FRUSTRATED = "frustrated"
    UNKNOWN = "unknown"


class TimeOfDay(str, Enum):
    MORNING = "morning"       # 6-12
    AFTERNOON = "afternoon"   # 12-17
    EVENING = "evening"       # 17-21
    NIGHT = "night"           # 21-6


class CalendarLoad(str, Enum):
    FREE = "free"
    LIGHT = "light"
    MODERATE = "moderate"
    BUSY = "busy"
    PACKED = "packed"


class DayType(str, Enum):
    WORKDAY = "workday"
    WEEKEND = "weekend"
    HOLIDAY = "holiday"


@dataclass
class ContextSignal:
    """Individual context signal."""
    signal_type: str
    signal_value: str
    intensity: float = 0.5
    source: str = "auto_detect"
    confidence: float = 0.8
    raw_data: Optional[Dict] = None


@dataclass
class ContextProfile:
    """Aggregated context state."""
    profile_id: str
    primary_mood: Mood
    energy_level: float  # 0-1
    stress_level: float  # 0-1
    focus_level: float   # 0-1
    time_of_day: TimeOfDay
    day_type: DayType
    calendar_load: CalendarLoad
    task_load: str
    recommended_tone: str
    recommended_verbosity: str
    tool_adjustments: Dict[str, float]
    prompt_injection: Optional[str] = None
    specialist_preference: Optional[str] = None
    signals_used: List[str] = field(default_factory=list)


@dataclass
class ContextRule:
    """Rule for context-based adjustments."""
    rule_name: str
    conditions: Dict[str, Any]
    tone_adjustment: Optional[str]
    verbosity_adjustment: Optional[str]
    tool_adjustments: Dict[str, float]
    prompt_injection: Optional[str]
    specialist_preference: Optional[str]
    priority: int


class ContextEngineService:
    """
    Aggregates context signals and produces mood-aware recommendations.

    Flow:
    1. Collect signals (emotion, time, calendar, etc.)
    2. Build context profile
    3. Match against rules
    4. Return recommendations for agent
    """

    def __init__(self):
        self._rules_cache: List[ContextRule] = []
        self._cache_time: Optional[datetime] = None
        self._cache_ttl = timedelta(minutes=5)
        self._ensure_tables()

    def _ensure_tables(self):
        """Ensure context tables exist."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT EXISTS (
                            SELECT FROM information_schema.tables
                            WHERE table_name = 'jarvis_context_signals'
                        )
                    """)
                    if not cur.fetchone()[0]:
                        log_with_context(logger, "info", "Context tables not found, will be created")
        except Exception as e:
            log_with_context(logger, "debug", "Context tables check failed", error=str(e))

    def _get_time_of_day(self) -> TimeOfDay:
        """Get current time of day."""
        hour = datetime.now().hour
        if 6 <= hour < 12:
            return TimeOfDay.MORNING
        elif 12 <= hour < 17:
            return TimeOfDay.AFTERNOON
        elif 17 <= hour < 21:
            return TimeOfDay.EVENING
        else:
            return TimeOfDay.NIGHT

    def _get_day_type(self) -> DayType:
        """Get current day type."""
        weekday = datetime.now().weekday()
        if weekday >= 5:
            return DayType.WEEKEND
        return DayType.WORKDAY

    def _detect_mood_from_emotion(self, emotion_state: str, intensity: float) -> Tuple[Mood, float]:
        """Map emotion state to mood."""
        emotion_to_mood = {
            "calm": (Mood.CALM, 1.0 - intensity * 0.3),  # Low stress
            "stressed": (Mood.STRESSED, intensity),
            "overwhelmed": (Mood.OVERWHELMED, intensity),
            "frustrated": (Mood.FRUSTRATED, intensity),
            "energized": (Mood.ENERGIZED, intensity),
            "unknown": (Mood.UNKNOWN, 0.5)
        }
        return emotion_to_mood.get(emotion_state.lower(), (Mood.UNKNOWN, 0.5))

    def _estimate_energy_level(
        self,
        time_of_day: TimeOfDay,
        mood: Mood,
        stress_level: float
    ) -> float:
        """Estimate energy level based on time, mood, and stress."""
        # Base energy by time of day
        time_energy = {
            TimeOfDay.MORNING: 0.7,
            TimeOfDay.AFTERNOON: 0.5,
            TimeOfDay.EVENING: 0.4,
            TimeOfDay.NIGHT: 0.3
        }
        base = time_energy.get(time_of_day, 0.5)

        # Mood adjustments
        mood_adjustments = {
            Mood.ENERGIZED: 0.3,
            Mood.CALM: 0.1,
            Mood.FOCUSED: 0.1,
            Mood.TIRED: -0.3,
            Mood.STRESSED: -0.1,
            Mood.OVERWHELMED: -0.2,
            Mood.FRUSTRATED: -0.1
        }
        adjustment = mood_adjustments.get(mood, 0)

        # Stress reduces energy
        stress_penalty = stress_level * 0.2

        energy = max(0.1, min(1.0, base + adjustment - stress_penalty))
        return round(energy, 2)

    def _get_calendar_load(self, user_id: Optional[str] = None) -> CalendarLoad:
        """Get calendar load for today."""
        try:
            # Try to get today's events count
            from datetime import date
            today = date.today().isoformat()

            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT COUNT(*) as cnt
                        FROM calendar_events
                        WHERE DATE(start_time) = %s
                    """, (today,))
                    row = cur.fetchone()
                    count = row["cnt"] if row else 0

                    if count == 0:
                        return CalendarLoad.FREE
                    elif count <= 2:
                        return CalendarLoad.LIGHT
                    elif count <= 4:
                        return CalendarLoad.MODERATE
                    elif count <= 6:
                        return CalendarLoad.BUSY
                    else:
                        return CalendarLoad.PACKED

        except Exception as e:
            log_with_context(logger, "debug", "Calendar load check failed", error=str(e))
            return CalendarLoad.MODERATE  # Default assumption

    def record_signal(
        self,
        signal_type: str,
        signal_value: str,
        intensity: float = 0.5,
        source: str = "auto_detect",
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        raw_data: Optional[Dict] = None,
        confidence: float = 0.8,
        expires_in_minutes: Optional[int] = None
    ) -> Dict[str, Any]:
        """Record a context signal."""
        try:
            expires_at = None
            if expires_in_minutes:
                expires_at = datetime.now() + timedelta(minutes=expires_in_minutes)

            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO jarvis_context_signals
                        (signal_type, signal_value, intensity, source, user_id,
                         session_id, raw_data, confidence, expires_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                    """, (
                        signal_type, signal_value, intensity, source, user_id,
                        session_id, json.dumps(raw_data) if raw_data else None,
                        confidence, expires_at
                    ))
                    signal_id = cur.fetchone()["id"]
                    conn.commit()

                    return {
                        "success": True,
                        "signal_id": signal_id,
                        "type": signal_type,
                        "value": signal_value
                    }

        except Exception as e:
            log_with_context(logger, "debug", "Signal recording failed", error=str(e))
            return {"success": False, "error": str(e)}

    def build_context_profile(
        self,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        query: Optional[str] = None
    ) -> ContextProfile:
        """
        Build aggregated context profile from all available signals.

        Collects:
        - Recent emotion signals
        - Time context
        - Calendar load
        - Derived estimates
        """
        profile_id = f"ctx_{uuid.uuid4().hex[:12]}"
        signals_used = []

        # 1. Get time context
        time_of_day = self._get_time_of_day()
        day_type = self._get_day_type()

        # 2. Get emotion from EmotionTracker if available
        mood = Mood.UNKNOWN
        stress_level = 0.3  # Default moderate-low
        try:
            from ..emotion_tracker import EmotionTracker
            tracker = EmotionTracker()

            if query:
                emotion_state, intensity = tracker.detect_emotion_from_text(query)
                mood, stress_level = self._detect_mood_from_emotion(
                    emotion_state.value, intensity
                )
                signals_used.append(f"emotion:{emotion_state.value}")

        except Exception as e:
            log_with_context(logger, "debug", "Emotion detection failed", error=str(e))

        # 3. Get recent signals from DB
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    # Get recent emotion signals
                    cur.execute("""
                        SELECT signal_type, signal_value, intensity, confidence
                        FROM jarvis_context_signals
                        WHERE (session_id = %s OR user_id = %s)
                          AND (expires_at IS NULL OR expires_at > NOW())
                          AND created_at > NOW() - INTERVAL '1 hour'
                        ORDER BY created_at DESC
                        LIMIT 10
                    """, (session_id, user_id))

                    for row in cur.fetchall():
                        signal_type = row["signal_type"]
                        signal_value = row["signal_value"]
                        intensity = row["intensity"]

                        if signal_type == "emotion" and mood == Mood.UNKNOWN:
                            mood, stress_level = self._detect_mood_from_emotion(
                                signal_value, intensity
                            )
                            signals_used.append(f"db_emotion:{signal_value}")

                        elif signal_type == "stress":
                            stress_level = max(stress_level, intensity)
                            signals_used.append(f"db_stress:{intensity}")

        except Exception as e:
            log_with_context(logger, "debug", "Signal retrieval failed", error=str(e))

        # 4. Get calendar load
        calendar_load = self._get_calendar_load(user_id)

        # 5. Estimate energy level
        energy_level = self._estimate_energy_level(time_of_day, mood, stress_level)

        # 6. Estimate focus level (based on time and load)
        focus_level = 0.5
        if time_of_day == TimeOfDay.MORNING:
            focus_level = 0.7
        elif calendar_load in [CalendarLoad.BUSY, CalendarLoad.PACKED]:
            focus_level = 0.4  # Hard to focus when packed
        if mood == Mood.FOCUSED:
            focus_level = 0.9

        # 7. Get task load estimation
        task_load = "normal"
        if calendar_load in [CalendarLoad.PACKED]:
            task_load = "high"
        elif mood in [Mood.OVERWHELMED, Mood.STRESSED]:
            task_load = "overwhelming"

        # 8. Apply rules to get recommendations
        tone, verbosity, tool_adjustments, prompt_injection, specialist = self._apply_rules(
            mood=mood,
            energy_level=energy_level,
            stress_level=stress_level,
            time_of_day=time_of_day,
            day_type=day_type,
            calendar_load=calendar_load
        )

        profile = ContextProfile(
            profile_id=profile_id,
            primary_mood=mood,
            energy_level=energy_level,
            stress_level=stress_level,
            focus_level=focus_level,
            time_of_day=time_of_day,
            day_type=day_type,
            calendar_load=calendar_load,
            task_load=task_load,
            recommended_tone=tone,
            recommended_verbosity=verbosity,
            tool_adjustments=tool_adjustments,
            prompt_injection=prompt_injection,
            specialist_preference=specialist,
            signals_used=signals_used
        )

        # Save profile
        self._save_profile(profile, user_id, session_id)

        return profile

    def _load_rules(self) -> List[ContextRule]:
        """Load context rules from database."""
        now = datetime.now()
        if self._cache_time and (now - self._cache_time) < self._cache_ttl:
            return self._rules_cache

        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT rule_name, conditions, tone_adjustment, verbosity_adjustment,
                               tool_adjustments, prompt_injection, specialist_preference, priority
                        FROM jarvis_context_rules
                        WHERE enabled = TRUE
                        ORDER BY priority ASC
                    """)

                    self._rules_cache = []
                    for row in cur.fetchall():
                        self._rules_cache.append(ContextRule(
                            rule_name=row["rule_name"],
                            conditions=row["conditions"] or {},
                            tone_adjustment=row["tone_adjustment"],
                            verbosity_adjustment=row["verbosity_adjustment"],
                            tool_adjustments=row["tool_adjustments"] or {},
                            prompt_injection=row["prompt_injection"],
                            specialist_preference=row["specialist_preference"],
                            priority=row["priority"]
                        ))

                    self._cache_time = now

        except Exception as e:
            log_with_context(logger, "debug", "Rule loading failed", error=str(e))

        return self._rules_cache

    def _check_condition(self, condition_key: str, condition_value: Any, actual_value: Any) -> bool:
        """Check if a single condition matches."""
        if isinstance(condition_value, dict):
            # Comparison operators
            if "gte" in condition_value:
                return actual_value >= condition_value["gte"]
            if "gt" in condition_value:
                return actual_value > condition_value["gt"]
            if "lte" in condition_value:
                return actual_value <= condition_value["lte"]
            if "lt" in condition_value:
                return actual_value < condition_value["lt"]
            if "eq" in condition_value:
                return actual_value == condition_value["eq"]
            if "in" in condition_value:
                return actual_value in condition_value["in"]
        else:
            # Direct comparison
            return str(actual_value).lower() == str(condition_value).lower()

        return False

    def _apply_rules(
        self,
        mood: Mood,
        energy_level: float,
        stress_level: float,
        time_of_day: TimeOfDay,
        day_type: DayType,
        calendar_load: CalendarLoad
    ) -> Tuple[str, str, Dict[str, float], Optional[str], Optional[str]]:
        """Apply matching rules and return recommendations."""
        rules = self._load_rules()

        # Build context dict for matching
        context = {
            "mood": mood.value,
            "energy_level": energy_level,
            "stress_level": stress_level,
            "time_of_day": time_of_day.value,
            "day_type": day_type.value,
            "calendar_load": calendar_load.value
        }

        # Defaults
        tone = "friendly"
        verbosity = "concise"
        tool_adjustments: Dict[str, float] = {}
        prompt_injections: List[str] = []
        specialist = None

        # Check each rule
        for rule in rules:
            all_match = True
            for cond_key, cond_value in rule.conditions.items():
                actual = context.get(cond_key)
                if actual is None or not self._check_condition(cond_key, cond_value, actual):
                    all_match = False
                    break

            if all_match:
                # Apply rule
                if rule.tone_adjustment:
                    tone = rule.tone_adjustment
                if rule.verbosity_adjustment:
                    verbosity = rule.verbosity_adjustment
                if rule.tool_adjustments:
                    for tool, adj in rule.tool_adjustments.items():
                        tool_adjustments[tool] = tool_adjustments.get(tool, 0) + adj
                if rule.prompt_injection:
                    prompt_injections.append(rule.prompt_injection)
                if rule.specialist_preference and not specialist:
                    specialist = rule.specialist_preference

                # Record rule trigger
                self._record_rule_trigger(rule.rule_name)

        prompt_injection = "\n\n".join(prompt_injections) if prompt_injections else None

        return tone, verbosity, tool_adjustments, prompt_injection, specialist

    def _record_rule_trigger(self, rule_name: str):
        """Record that a rule was triggered."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE jarvis_context_rules
                        SET trigger_count = trigger_count + 1,
                            last_triggered_at = NOW()
                        WHERE rule_name = %s
                    """, (rule_name,))
                    conn.commit()
        except Exception:
            pass

    def _save_profile(
        self,
        profile: ContextProfile,
        user_id: Optional[str],
        session_id: Optional[str]
    ):
        """Save context profile to database."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO jarvis_context_profiles
                        (profile_id, primary_mood, energy_level, stress_level, focus_level,
                         time_of_day, day_type, calendar_load, task_load,
                         recommended_tone, recommended_verbosity, tool_priority_adjustments,
                         user_id, session_id, signals_used, valid_until)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (profile_id) DO UPDATE SET
                            primary_mood = EXCLUDED.primary_mood,
                            energy_level = EXCLUDED.energy_level,
                            stress_level = EXCLUDED.stress_level,
                            updated_at = NOW()
                    """, (
                        profile.profile_id,
                        profile.primary_mood.value,
                        profile.energy_level,
                        profile.stress_level,
                        profile.focus_level,
                        profile.time_of_day.value,
                        profile.day_type.value,
                        profile.calendar_load.value,
                        profile.task_load,
                        profile.recommended_tone,
                        profile.recommended_verbosity,
                        json.dumps(profile.tool_adjustments),
                        user_id,
                        session_id,
                        json.dumps(profile.signals_used),
                        datetime.now() + timedelta(hours=1)  # Valid for 1 hour
                    ))
                    conn.commit()
        except Exception as e:
            log_with_context(logger, "debug", "Profile save failed", error=str(e))

    def get_current_context(
        self,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get summary of current context."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT profile_id, primary_mood, energy_level, stress_level,
                               focus_level, time_of_day, day_type, calendar_load,
                               recommended_tone, recommended_verbosity
                        FROM jarvis_context_profiles
                        WHERE (session_id = %s OR user_id = %s)
                          AND valid_until > NOW()
                        ORDER BY created_at DESC
                        LIMIT 1
                    """, (session_id, user_id))

                    row = cur.fetchone()
                    if row:
                        return {
                            "success": True,
                            "profile_id": row["profile_id"],
                            "mood": row["primary_mood"],
                            "energy": row["energy_level"],
                            "stress": row["stress_level"],
                            "focus": row["focus_level"],
                            "time_of_day": row["time_of_day"],
                            "day_type": row["day_type"],
                            "calendar_load": row["calendar_load"],
                            "recommended_tone": row["recommended_tone"],
                            "recommended_verbosity": row["recommended_verbosity"]
                        }

        except Exception as e:
            log_with_context(logger, "debug", "Context retrieval failed", error=str(e))

        return {"success": False, "error": "No current context"}

    def get_context_stats(self) -> Dict[str, Any]:
        """Get context engine statistics."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    # Rule stats
                    cur.execute("""
                        SELECT rule_name, trigger_count, last_triggered_at
                        FROM jarvis_context_rules
                        WHERE trigger_count > 0
                        ORDER BY trigger_count DESC
                        LIMIT 10
                    """)

                    rules = [
                        {
                            "name": row["rule_name"],
                            "triggers": row["trigger_count"],
                            "last": row["last_triggered_at"].isoformat() if row["last_triggered_at"] else None
                        }
                        for row in cur.fetchall()
                    ]

                    # Signal counts
                    cur.execute("""
                        SELECT signal_type, COUNT(*) as cnt
                        FROM jarvis_context_signals
                        WHERE created_at > NOW() - INTERVAL '24 hours'
                        GROUP BY signal_type
                    """)

                    signals = {row["signal_type"]: row["cnt"] for row in cur.fetchall()}

                    return {
                        "success": True,
                        "top_rules": rules,
                        "signals_24h": signals,
                        "total_signals_24h": sum(signals.values())
                    }

        except Exception as e:
            return {"success": False, "error": str(e)}


# Singleton
_service: Optional[ContextEngineService] = None


def get_context_engine_service() -> ContextEngineService:
    """Get or create context engine service singleton."""
    global _service
    if _service is None:
        _service = ContextEngineService()
    return _service
