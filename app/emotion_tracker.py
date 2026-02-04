"""
Emotion Tracking Service for Jarvis
Tracks emotional states across sessions and enables proactive interventions
"""
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass
import json
from enum import Enum
from .postgres_state import get_conn
from .observability import get_logger, log_with_context

logger = get_logger("jarvis.emotion_tracker")

class EmotionState(Enum):
    """Simple emotion categories as recommended by Jarvis"""
    CALM = "calm"
    STRESSED = "stressed" 
    OVERWHELMED = "overwhelmed"
    FRUSTRATED = "frustrated"
    ENERGIZED = "energized"
    UNKNOWN = "unknown"  # For unclear states

@dataclass
class EmotionRecord:
    """Single emotion tracking record with Jarvis-recommended fields"""
    user_id: int
    timestamp: datetime
    emotion: EmotionState
    intensity: float  # 0.0 to 1.0 (replacing confidence)
    context: str  # What's happening
    session_id: Optional[str] = None
    trigger_context: Optional[str] = None  # Longer context if needed
    auto_detected: bool = True  # Minimal input - auto detection preferred
    intervention_triggered: bool = False
    
class EmotionTracker:
    def __init__(self):
        self._init_tables()
        self.stress_threshold = 3  # Number of stress signals before intervention
        self.lookback_hours = 24  # How far back to look for patterns
    
    def _init_tables(self):
        """Create emotion tracking tables if not exists"""
        with get_conn() as conn:
            cursor = conn.cursor()
            
            # Main emotion history table - Jarvis recommended schema
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS emotion_history (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                timestamp TIMESTAMP NOT NULL DEFAULT NOW(),
                emotion_state TEXT NOT NULL,
                intensity FLOAT NOT NULL DEFAULT 0.5,  -- 0.0 to 1.0
                context TEXT,  -- Simple context, not complex classification
                session_id TEXT,
                trigger_context TEXT,  -- Longer text if needed
                auto_detected BOOLEAN DEFAULT TRUE,  -- Minimal input preference
                intervention_triggered BOOLEAN DEFAULT FALSE,
                intervention_type TEXT
            )
            """)
            
            # Create indexes separately for PostgreSQL
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_emotion_user_time ON emotion_history (user_id, timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_emotion_state ON emotion_history (emotion_state)")
            
            # Emotion patterns table for aggregated insights
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS emotion_patterns (
                pattern_id VARCHAR(100) PRIMARY KEY,
                user_id INTEGER NOT NULL,
                pattern_type VARCHAR(50), -- 'daily', 'weekly', 'trigger-based'
                pattern_data JSONB,
                first_detected TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                intervention_effectiveness FLOAT
            )
            """)
            
            # Interventions tracking
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS emotion_interventions (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                emotion_before VARCHAR(50),
                emotion_after VARCHAR(50),
                intervention_type VARCHAR(100),
                intervention_text TEXT,
                success_score FLOAT,
                user_feedback TEXT
            )
            """)
            
            log_with_context(logger, "info", "Emotion tracking tables initialized")
    
    def detect_emotion_from_text(self, text: str) -> Tuple[EmotionState, float]:
        """
        Simple emotion detection from text - Jarvis recommended approach.
        Returns: (emotion, intensity)
        Supports German and English keywords.
        """
        text_lower = text.lower()
        
        # Simple keyword-based detection - German & English
        emotion_keywords = {
            EmotionState.STRESSED: [
                # English
                "stressed", "stress", "pressure", "deadline", "overwhelming",
                "too much", "can't handle", "burnt out", "exhausted",
                # German
                "gestresst", "stress", "druck", "deadline", "überlastet",
                "zu viel", "schaffe das nicht", "ausgebrannt", "erschöpft",
                "anstrengend", "belastend", "überarbeitet"
            ],
            EmotionState.OVERWHELMED: [
                # English
                "overwhelmed", "drowning", "too many", "can't cope",
                "falling behind", "chaos", "swamped", "buried",
                # German
                "überfordert", "überwältigt", "ertrinke", "zu viele",
                "komme nicht hinterher", "chaos", "überhäuft", "vergraben",
                "nicht mehr", "kann nicht mehr"
            ],
            EmotionState.FRUSTRATED: [
                # English
                "frustrated", "annoyed", "irritated", "stuck", "blocked",
                "not working", "waste of time", "angry", "pissed",
                # German
                "frustriert", "genervt", "verärgert", "stecke fest", "blockiert",
                "funktioniert nicht", "zeitverschwendung", "wütend", "sauer",
                "nervig", "ätzend", "kotzt mich an"
            ],
            EmotionState.ENERGIZED: [
                # English
                "excited", "energized", "motivated", "pumped", "ready",
                "great", "awesome", "productive", "flow", "focused",
                # German
                "aufgeregt", "energiegeladen", "motiviert", "gepumpt", "bereit",
                "super", "toll", "produktiv", "flow", "fokussiert",
                "läuft gut", "mega", "geil", "perfekt"
            ],
            EmotionState.CALM: [
                # English
                "calm", "peaceful", "relaxed", "good", "fine", "okay",
                "balanced", "centered", "content",
                # German
                "ruhig", "friedlich", "entspannt", "gut", "okay", "ok",
                "ausgeglichen", "zufrieden", "gelassen", "alles klar"
            ]
        }
        
        # Count matches for each emotion
        emotion_scores = {}
        for emotion, keywords in emotion_keywords.items():
            score = sum(1 for keyword in keywords if keyword in text_lower)
            if score > 0:
                emotion_scores[emotion] = score
        
        if not emotion_scores:
            return EmotionState.UNKNOWN, 0.3
        
        # Get emotion with highest score
        detected_emotion = max(emotion_scores.items(), key=lambda x: x[1])[0]
        
        # Calculate intensity based on matches and punctuation
        max_score = emotion_scores[detected_emotion]
        exclamation_count = text.count('!')
        intensity = min(0.3 + (max_score * 0.2) + (exclamation_count * 0.1), 1.0)
        
        return detected_emotion, intensity
    
    def track_emotion(
        self,
        user_id: int,
        text: str,
        session_id: Optional[str] = None,
        context: Optional[str] = None,
        manual_emotion: Optional[EmotionState] = None,
        manual_intensity: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Track emotion with minimal input - auto-detection preferred.
        Returns: emotion info and intervention if needed
        """
        with get_conn() as conn:
            cursor = conn.cursor()
            
            # Auto-detect or use manual input
            if manual_emotion:
                emotion = manual_emotion
                intensity = manual_intensity or 0.5
                auto_detected = False
            else:
                emotion, intensity = self.detect_emotion_from_text(text)
                auto_detected = True
            
            # Store emotion record
            cursor.execute("""
            INSERT INTO emotion_history 
            (user_id, emotion_state, intensity, context, session_id, trigger_context, auto_detected)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id, timestamp
            """, (
                user_id,
                emotion.value,
                intensity,
                context or text[:200],
                session_id,
                text[:500] if len(text) > 200 else None,
                auto_detected
            ))
            
            record_id, timestamp = cursor.fetchone()
            
            # Convert timestamp to string if needed
            if hasattr(timestamp, 'isoformat'):
                timestamp_str = timestamp.isoformat()
            else:
                timestamp_str = str(timestamp)
            
            # Check for patterns that need intervention
            intervention_needed = self._check_intervention_needed(user_id, emotion, cursor)
        
        response = {
            "emotion": emotion.value,
            "intensity": intensity,
            "auto_detected": auto_detected,
            "timestamp": timestamp_str,
            "record_id": record_id
        }
        
        if intervention_needed:
            response["intervention"] = self._get_intervention(user_id, emotion)
        
        return response
    
    def _check_intervention_needed(self, user_id: int, current_emotion: EmotionState, cursor) -> bool:
        """
        Check if intervention is needed based on patterns.
        Jarvis recommendation: Trigger after 3x negative spikes
        """
        # Skip if positive emotion
        if current_emotion in [EmotionState.CALM, EmotionState.ENERGIZED]:
            return False
        
        # Check last 7 days for negative patterns - Jarvis: "3x diese Woche"
        cursor.execute("""
        SELECT COUNT(*) as negative_count,
               emotion_state,
               AVG(intensity) as avg_intensity
        FROM emotion_history
        WHERE user_id = %s
          AND timestamp > NOW() - INTERVAL '7 days'
          AND emotion_state IN ('stressed', 'overwhelmed', 'frustrated')
          AND intervention_triggered = FALSE
        GROUP BY emotion_state
        HAVING COUNT(*) >= 3
        ORDER BY negative_count DESC
        LIMIT 1
        """, (user_id,))
        
        result = cursor.fetchone()
        if result:
            negative_count, dominant_emotion, avg_intensity = result
            log_with_context(
                logger, "info", 
                f"Pattern detected: {negative_count}x {dominant_emotion}",
                user_id=user_id, avg_intensity=avg_intensity
            )
            
            # Mark recent emotions as intervention triggered
            cursor.execute("""
            UPDATE emotion_history
            SET intervention_triggered = TRUE
            WHERE user_id = %s
              AND timestamp > NOW() - INTERVAL '7 days'
              AND emotion_state = %s
              AND intervention_triggered = FALSE
            """, (user_id, dominant_emotion))
            
            return True
        
        return False
    
    def _get_intervention(self, user_id: int, emotion: EmotionState) -> Dict[str, Any]:
        """Generate appropriate intervention based on emotion pattern - Jarvis style"""
        interventions = {
            EmotionState.STRESSED: {
                "type": "stress_relief",
                "message": "Hey, ich merke du bist diese Woche mehrfach gestresst. Möchtest du darüber reden? Oder soll ich dir eine kurze Atem-Übung zeigen?",
                "quick_actions": ["🗣️ Darüber reden", "🧘 Atem-Übung", "⏸️ Später"]
            },
            EmotionState.OVERWHELMED: {
                "type": "task_prioritization", 
                "message": "Du scheinst überwältigt zu sein. Lass uns deine Tasks priorisieren. Was ist wirklich wichtig vs. was kann warten?",
                "quick_actions": ["📋 Tasks sortieren", "🎯 Fokus-Session", "🚫 Nicht jetzt"]
            },
            EmotionState.FRUSTRATED: {
                "type": "problem_solving",
                "message": "Ich sehe Frustration. Was blockiert dich gerade? Manchmal hilft es, das Problem aus einem anderen Winkel zu betrachten.",
                "quick_actions": ["🔍 Problem analysieren", "💡 Perspektive wechseln", "🏃 Pause machen"]
            }
        }
        
        return interventions.get(emotion, {
            "type": "general_support",
            "message": "Ich bin hier wenn du reden möchtest.",
            "quick_actions": ["💬 Reden", "👍 Alles gut"]
        })
    
    def get_emotion_patterns(
        self, 
        user_id: int, 
        days: int = 7,
        include_interventions: bool = True
    ) -> Dict[str, Any]:
        """Get emotion patterns and trends for user - Jarvis: weekly trends"""
        with get_conn() as conn:
            cursor = conn.cursor()
            
            # Get emotion distribution
            cursor.execute("""
            SELECT 
                emotion_state,
                COUNT(*) as count,
                AVG(intensity) as avg_intensity,
                MAX(timestamp) as last_occurrence
            FROM emotion_history
            WHERE user_id = %s
              AND timestamp > NOW() - INTERVAL '%s days'
            GROUP BY emotion_state
            ORDER BY count DESC
            """, (user_id, days))
            
            emotions = []
            for row in cursor.fetchall():
                # RealDictCursor returns dicts, not tuples
                last_seen = row['last_occurrence']
                if hasattr(last_seen, 'isoformat'):
                    last_seen = last_seen.isoformat()
                emotions.append({
                    "emotion": row['emotion_state'],
                    "count": row['count'],
                    "avg_intensity": round(row['avg_intensity'], 2),
                    "last_seen": last_seen
                })
            
            # Get daily trends
            cursor.execute("""
            SELECT 
                DATE(timestamp) as day,
                emotion_state,
                COUNT(*) as count,
                AVG(intensity) as avg_intensity
            FROM emotion_history
            WHERE user_id = %s
              AND timestamp > NOW() - INTERVAL '%s days'
            GROUP BY DATE(timestamp), emotion_state
            ORDER BY day DESC, count DESC
            """, (user_id, days))
            
            daily_trends = {}
            for row in cursor.fetchall():
                # RealDictCursor returns dicts
                day_val = row['day']
                if hasattr(day_val, 'isoformat'):
                    day = day_val.isoformat()
                else:
                    day = str(day_val)
                if day not in daily_trends:
                    daily_trends[day] = []
                daily_trends[day].append({
                    "emotion": row['emotion_state'],
                    "count": row['count'],
                    "avg_intensity": round(row['avg_intensity'], 2)
                })
            
            # Calculate insights
            total_emotions = sum(e["count"] for e in emotions)
            negative_emotions = sum(
                e["count"] for e in emotions 
                if e["emotion"] in ["stressed", "overwhelmed", "frustrated"]
            )
            negative_percentage = (negative_emotions / total_emotions * 100) if total_emotions > 0 else 0
        
        return {
            "summary": {
                "total_tracked": total_emotions,
                "negative_percentage": round(negative_percentage, 1),
                "dominant_emotion": emotions[0]["emotion"] if emotions else None,
                "days_analyzed": days
            },
            "emotions": emotions,
            "daily_trends": daily_trends,
            "insights": self._generate_insights(emotions, daily_trends)
        }
    
    def _generate_insights(self, emotions: List[Dict], daily_trends: Dict) -> List[str]:
        """Generate insights from emotion patterns - Jarvis: actionable feedback"""
        insights = []
        
        if not emotions:
            return ["Noch keine Emotionsdaten vorhanden."]
        
        # Check stress levels
        stress_emotions = ["stressed", "overwhelmed", "frustrated"]
        stress_count = sum(e["count"] for e in emotions if e["emotion"] in stress_emotions)
        total_count = sum(e["count"] for e in emotions)
        
        if total_count > 0:
            stress_ratio = stress_count / total_count
            if stress_ratio > 0.5:
                insights.append("⚠️ Hohe Stress-Belastung erkannt. Zeit für Selbstfürsorge!")
            elif stress_ratio > 0.3:
                insights.append("📊 Moderate Stress-Level. Präventive Pausen empfohlen.")
        
        # Check for patterns
        if len(daily_trends) >= 3:
            # Look for increasing stress
            recent_days = sorted(daily_trends.keys())[-3:]
            stress_trend = []
            
            for day in recent_days:
                day_stress = sum(
                    e["count"] for e in daily_trends[day]
                    if e["emotion"] in stress_emotions
                )
                day_total = sum(e["count"] for e in daily_trends[day])
                stress_trend.append(day_stress / day_total if day_total > 0 else 0)
            
            if all(stress_trend[i] <= stress_trend[i+1] for i in range(len(stress_trend)-1)):
                insights.append("📈 Steigender Stress-Trend. Intervention empfohlen.")
            elif all(stress_trend[i] >= stress_trend[i+1] for i in range(len(stress_trend)-1)):
                insights.append("📉 Stress nimmt ab. Gute Entwicklung!")
        
        # Check dominant emotions
        if emotions[0]["emotion"] == "energized":
            insights.append("⚡ Hohe Energie! Nutze diese Phase für wichtige Aufgaben.")
        elif emotions[0]["emotion"] == "balanced":
            insights.append("⚖️ Ausgeglichene Stimmung. Idealer Zustand!")
        
        return insights if insights else ["Stabile emotionale Lage."]
    
    def track_intervention_result(
        self,
        user_id: int,
        intervention_type: str,
        accepted: bool,
        notes: Optional[str] = None
    ) -> bool:
        """Track if user accepted/rejected intervention - Jarvis: learn from feedback"""
        with get_conn() as conn:
            cursor = conn.cursor()
            
            # Store intervention feedback
            cursor.execute("""
            INSERT INTO emotion_intervention_feedback
            (user_id, intervention_type, accepted, notes, timestamp)
            VALUES (%s, %s, %s, %s, NOW())
            """, (user_id, intervention_type, accepted, notes))
        
        # TODO: Use this feedback to improve intervention timing/content
        logger.info(f"Intervention feedback tracked: {intervention_type} - {'accepted' if accepted else 'rejected'}")
        
        return True


# Singleton instance - Jarvis: "Einmal initialisiert, immer bereit"
emotion_tracker = EmotionTracker()