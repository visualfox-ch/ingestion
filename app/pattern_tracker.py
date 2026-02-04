"""
Pattern Recognition Service for Jarvis
Tracks recurring topics and enables proactive responses
"""
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from dataclasses import dataclass
import json
from .postgres_state import get_conn

@dataclass
class Pattern:
    pattern_id: str
    user_id: int
    topic: str
    occurrence_count: int
    first_seen: datetime
    last_seen: datetime
    context_snippets: List[str]
    auto_triggered: bool = False
    
class PatternTracker:
    def __init__(self):
        self._init_tables()
    
    def _init_tables(self):
        """Create pattern tracking tables if not exists"""
        with get_conn() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS pattern_observations (
                pattern_id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                topic TEXT NOT NULL,
                occurrence_count INTEGER DEFAULT 1,
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                context_snippets JSONB DEFAULT '[]',
                auto_triggered BOOLEAN DEFAULT FALSE,
                metadata JSONB DEFAULT '{}'
            )
            """)
            
            cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_pattern_user_topic 
            ON pattern_observations(user_id, topic)
            """)
    
    def track_topic(self, user_id: int, topic: str, context: str) -> Optional[str]:
        """
        Track a topic mention and return action if threshold reached
        Returns: None or proactive message to send
        """
        with get_conn() as conn:
            cursor = conn.cursor()
            
            # Generate pattern ID
            pattern_id = f"{user_id}_{topic.lower().replace(' ', '_')}"
            
            # Check if pattern exists
            cursor.execute("""
            SELECT occurrence_count, auto_triggered, context_snippets
            FROM pattern_observations
            WHERE pattern_id = %s
            """, (pattern_id,))
            
            result = cursor.fetchone()
            
            if result:
                count, auto_triggered, snippets = result
                new_count = count + 1
                
                # Update existing pattern
                snippets = json.loads(snippets) if isinstance(snippets, str) else snippets
                snippets.append(context[:200])  # Keep last 200 chars
                snippets = snippets[-5:]  # Keep only last 5 occurrences
                
                cursor.execute("""
                UPDATE pattern_observations
                SET occurrence_count = %s,
                    last_seen = CURRENT_TIMESTAMP,
                    context_snippets = %s
                WHERE pattern_id = %s
                """, (new_count, json.dumps(snippets), pattern_id))
                
                # Check if we should auto-respond
                if new_count >= 3 and not auto_triggered:
                    cursor.execute("""
                    UPDATE pattern_observations
                    SET auto_triggered = TRUE
                    WHERE pattern_id = %s
                    """, (pattern_id,))
                    
                    return self._generate_pattern_response(topic, new_count, snippets)
            else:
                # Create new pattern
                cursor.execute("""
                INSERT INTO pattern_observations 
                (pattern_id, user_id, topic, context_snippets)
                VALUES (%s, %s, %s, %s)
                """, (pattern_id, user_id, topic, json.dumps([context[:200]])))
        
        return None
    
    def _generate_pattern_response(self, topic: str, count: int, contexts: List[str]) -> str:
        """Generate proactive pattern recognition message"""
        return f"""🔄 **Pattern erkannt**: Du hast "{topic}" jetzt {count}x erwähnt.

Mir ist aufgefallen, dass dieses Thema wiederholt aufkommt. 

**Möchtest du:**
- Eine strukturierte Lösung erarbeiten?
- Die verschiedenen Aspekte zusammenfassen?
- Einen Action Plan erstellen?

Oder soll ich erstmal nur zuhören?"""
    
    def get_user_patterns(self, user_id: int, days: int = 30) -> List[Dict[str, Any]]:
        """Get all patterns for a user in the last N days"""
        with get_conn() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
            SELECT topic, occurrence_count, first_seen, last_seen, auto_triggered
            FROM pattern_observations
            WHERE user_id = %s 
            AND last_seen > CURRENT_TIMESTAMP - INTERVAL '%s days'
            ORDER BY occurrence_count DESC
            """, (user_id, days))
            
            patterns = []
            for row in cursor.fetchall():
                patterns.append({
                    "topic": row[0],
                    "count": row[1],
                    "first_seen": row[2].isoformat(),
                    "last_seen": row[3].isoformat(),
                    "auto_triggered": row[4]
                })
            
            return patterns
    
    def reset_pattern(self, user_id: int, topic: str):
        """Reset a pattern after it's been addressed"""
        with get_conn() as conn:
            cursor = conn.cursor()
            
            pattern_id = f"{user_id}_{topic.lower().replace(' ', '_')}"
            cursor.execute("""
            UPDATE pattern_observations
            SET auto_triggered = FALSE, occurrence_count = 0
            WHERE pattern_id = %s
            """, (pattern_id,))

# Singleton instance
pattern_tracker = PatternTracker()