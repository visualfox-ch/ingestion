"""
Proactive Context Service - Phase 2.1

Automatically loads relevant context before query processing:
- Detects context needs from query keywords and session type
- Loads relevant facts, recent conversations, user preferences
- Provides context hints for prompt injection
- Uses session patterns to anticipate needs
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
import json

from ..postgres_state import get_cursor

logger = logging.getLogger(__name__)

# Context categories and their priority
CONTEXT_PRIORITIES = {
    'user_preferences': 0.9,
    'recent_conversations': 0.8,
    'relevant_facts': 0.7,
    'session_context': 0.6,
    'domain_knowledge': 0.5
}

# Keywords that trigger specific context loading
CONTEXT_TRIGGERS = {
    'user_preferences': [
        'meine', 'mein', 'ich', 'mir', 'my', 'me', 'i', 'prefer', 'bevorzuge',
        'mag', 'like', 'want', 'will', 'möchte'
    ],
    'recent_conversations': [
        'vorher', 'earlier', 'gestern', 'yesterday', 'letztens', 'recently',
        'wir haben', 'we talked', 'du hast gesagt', 'you said', 'erinnere',
        'remember', 'recall'
    ],
    'project_context': [
        'projekt', 'project', 'code', 'app', 'system', 'jarvis', 'implementation',
        'feature', 'bug', 'error', 'fehler'
    ],
    'calendar_context': [
        'termin', 'meeting', 'kalender', 'calendar', 'heute', 'today', 'morgen',
        'tomorrow', 'woche', 'week', 'schedule', 'zeitplan'
    ],
    'communication_context': [
        'email', 'nachricht', 'message', 'antwort', 'reply', 'kontakt', 'contact',
        'schreiben', 'write', 'senden', 'send'
    ]
}


class ProactiveContextService:
    """
    Proactively loads relevant context based on query analysis.

    Analyzes incoming queries and session state to determine what
    context information might be useful, then loads it automatically.
    """

    def __init__(self):
        self._ensure_tables()

    def _ensure_tables(self):
        """Ensure context tracking tables exist."""
        try:
            with get_cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS context_load_history (
                        id SERIAL PRIMARY KEY,
                        query_hash VARCHAR(64),
                        context_types JSONB DEFAULT '[]'::jsonb,
                        context_loaded JSONB DEFAULT '{}'::jsonb,
                        was_useful BOOLEAN,
                        created_at TIMESTAMP DEFAULT NOW()
                    );

                    CREATE INDEX IF NOT EXISTS idx_context_load_query
                        ON context_load_history(query_hash);
                    CREATE INDEX IF NOT EXISTS idx_context_load_created
                        ON context_load_history(created_at DESC);

                    CREATE TABLE IF NOT EXISTS context_effectiveness (
                        id SERIAL PRIMARY KEY,
                        context_type VARCHAR(50) NOT NULL,
                        trigger_keyword VARCHAR(100),
                        times_loaded INTEGER DEFAULT 1,
                        times_useful INTEGER DEFAULT 0,
                        effectiveness_score FLOAT DEFAULT 0.5,
                        last_used_at TIMESTAMP DEFAULT NOW(),
                        UNIQUE(context_type, trigger_keyword)
                    );

                    CREATE INDEX IF NOT EXISTS idx_context_effectiveness_type
                        ON context_effectiveness(context_type);
                """)
        except Exception as e:
            logger.debug(f"Tables may already exist: {e}")

    def analyze_query(self, query: str) -> Dict[str, Any]:
        """
        Analyze query to determine what context might be needed.

        Returns context needs with priorities.
        """
        query_lower = query.lower()
        needed_contexts = []

        for context_type, keywords in CONTEXT_TRIGGERS.items():
            for keyword in keywords:
                if keyword in query_lower:
                    priority = CONTEXT_PRIORITIES.get(context_type, 0.5)
                    needed_contexts.append({
                        'type': context_type,
                        'trigger': keyword,
                        'priority': priority
                    })
                    break  # Only add each context type once

        # Sort by priority
        needed_contexts.sort(key=lambda x: x['priority'], reverse=True)

        return {
            'query': query[:100],
            'needed_contexts': needed_contexts,
            'analysis_time': datetime.now().isoformat()
        }

    def load_proactive_context(
        self,
        query: str,
        user_id: str = "default",
        session_type: str = None,
        max_items_per_type: int = 3
    ) -> Dict[str, Any]:
        """
        Load relevant context based on query analysis.

        Returns loaded context organized by type.
        """
        try:
            # Analyze what context is needed
            analysis = self.analyze_query(query)
            needed = analysis['needed_contexts']

            loaded_context = {
                'types_analyzed': len(needed),
                'context': {}
            }

            # Load each context type independently to avoid transaction cascade failures
            for ctx in needed[:5]:  # Limit to top 5 context types
                ctx_type = ctx['type']
                try:
                    with get_cursor() as cur:
                        if ctx_type == 'user_preferences':
                            loaded_context['context']['preferences'] = \
                                self._load_user_preferences(cur, user_id, max_items_per_type)

                        elif ctx_type == 'recent_conversations':
                            loaded_context['context']['recent_conversations'] = \
                                self._load_recent_conversations(cur, user_id, max_items_per_type)

                        elif ctx_type == 'project_context':
                            loaded_context['context']['project'] = \
                                self._load_project_context(cur, query, max_items_per_type)

                        elif ctx_type == 'calendar_context':
                            loaded_context['context']['calendar'] = \
                                self._load_calendar_context(cur, max_items_per_type)

                        elif ctx_type == 'communication_context':
                            loaded_context['context']['communication'] = \
                                self._load_communication_context(cur, max_items_per_type)
                except Exception as ctx_err:
                    logger.debug(f"Failed to load context type {ctx_type}: {ctx_err}")

            # Load session context
            if session_type:
                try:
                    with get_cursor() as cur:
                        loaded_context['context']['session'] = \
                            self._load_session_context(cur, session_type)
                except Exception as sess_err:
                    logger.debug(f"Failed to load session context: {sess_err}")

            # Record what we loaded (non-critical)
            try:
                with get_cursor() as cur:
                    self._record_context_load(cur, query, loaded_context)
            except Exception as rec_err:
                logger.debug(f"Failed to record context load: {rec_err}")

            loaded_context['success'] = True
            return loaded_context

        except Exception as e:
            logger.error(f"Load proactive context failed: {e}")
            return {"success": False, "error": str(e)}

    def _load_user_preferences(
        self,
        cur,
        user_id: str,
        limit: int
    ) -> List[Dict[str, Any]]:
        """Load user preferences from facts."""
        try:
            cur.execute("""
                SELECT fact, category, trust_score
                FROM facts
                WHERE category IN ('preference', 'user_preference', 'style')
                AND trust_score > 0.5
                ORDER BY trust_score DESC, updated_at DESC
                LIMIT %s
            """, (limit,))

            return [{"fact": row['fact'], "confidence": row['trust_score']}
                    for row in cur.fetchall()]
        except Exception:
            return []

    def _load_recent_conversations(
        self,
        cur,
        user_id: str,
        limit: int
    ) -> List[Dict[str, Any]]:
        """Load recent conversation summaries."""
        try:
            cur.execute("""
                SELECT topic, summary, updated_at
                FROM conversation_contexts
                WHERE updated_at > NOW() - INTERVAL '7 days'
                ORDER BY updated_at DESC
                LIMIT %s
            """, (limit,))

            return [{"topic": row['topic'], "summary": row['summary'][:200],
                    "when": row['updated_at'].isoformat()}
                    for row in cur.fetchall()]
        except Exception:
            return []

    def _load_project_context(
        self,
        cur,
        query: str,
        limit: int
    ) -> List[Dict[str, Any]]:
        """Load relevant project context."""
        try:
            # Get recent tool audit entries for code-related tools
            cur.execute("""
                SELECT tool_name, tool_input, created_at
                FROM tool_audit
                WHERE tool_name IN ('read_project_file', 'write_project_file', 'read_my_source_files')
                AND success = true
                AND created_at > NOW() - INTERVAL '1 day'
                ORDER BY created_at DESC
                LIMIT %s
            """, (limit,))

            results = []
            for row in cur.fetchall():
                file_path = row['tool_input'].get('file_path', '') if row['tool_input'] else ''
                if file_path:
                    results.append({
                        "tool": row['tool_name'],
                        "file": file_path.split('/')[-1],
                        "when": row['created_at'].isoformat()
                    })
            return results
        except Exception:
            return []

    def _load_calendar_context(self, cur, limit: int) -> List[Dict[str, Any]]:
        """Load upcoming calendar context."""
        try:
            cur.execute("""
                SELECT tool_input, created_at
                FROM tool_audit
                WHERE tool_name = 'get_calendar_events'
                AND success = true
                ORDER BY created_at DESC
                LIMIT 1
            """)

            row = cur.fetchone()
            if row and row['tool_input']:
                return [{"note": "Calendar tools recently used",
                        "when": row['created_at'].isoformat()}]
            return []
        except Exception:
            return []

    def _load_communication_context(self, cur, limit: int) -> List[Dict[str, Any]]:
        """Load recent communication context."""
        try:
            cur.execute("""
                SELECT tool_name, tool_input, created_at
                FROM tool_audit
                WHERE tool_name IN ('send_email', 'get_gmail_messages', 'send_telegram_message')
                AND success = true
                AND created_at > NOW() - INTERVAL '1 day'
                ORDER BY created_at DESC
                LIMIT %s
            """, (limit,))

            results = []
            for row in cur.fetchall():
                results.append({
                    "tool": row['tool_name'],
                    "when": row['created_at'].isoformat()
                })
            return results
        except Exception:
            return []

    def _load_session_context(
        self,
        cur,
        session_type: str
    ) -> Dict[str, Any]:
        """Load context relevant to current session type."""
        try:
            cur.execute("""
                SELECT tool_preferences, indicators
                FROM session_type_patterns
                WHERE session_type = %s
            """, (session_type,))

            row = cur.fetchone()
            if row:
                return {
                    "session_type": session_type,
                    "preferred_tools": row['tool_preferences'].get('preferred', []) if row['tool_preferences'] else [],
                    "typical_keywords": row['indicators'].get('keywords', [])[:5] if row['indicators'] else []
                }
            return {"session_type": session_type}
        except Exception:
            return {"session_type": session_type}

    def _record_context_load(
        self,
        cur,
        query: str,
        loaded_context: Dict[str, Any]
    ):
        """Record what context was loaded for learning."""
        import hashlib
        query_hash = hashlib.md5(query.encode()).hexdigest()

        context_types = list(loaded_context.get('context', {}).keys())

        cur.execute("""
            INSERT INTO context_load_history
            (query_hash, context_types, context_loaded)
            VALUES (%s, %s, %s)
        """, (query_hash, json.dumps(context_types), json.dumps({"types": context_types})))

    def mark_context_useful(
        self,
        query: str,
        useful_types: List[str]
    ) -> Dict[str, Any]:
        """Mark which context types were actually useful."""
        try:
            import hashlib
            query_hash = hashlib.md5(query.encode()).hexdigest()

            with get_cursor() as cur:
                # Update history
                cur.execute("""
                    UPDATE context_load_history
                    SET was_useful = true
                    WHERE query_hash = %s
                    AND created_at > NOW() - INTERVAL '1 hour'
                """, (query_hash,))

                # Update effectiveness scores
                for ctx_type in useful_types:
                    cur.execute("""
                        INSERT INTO context_effectiveness
                        (context_type, times_loaded, times_useful, effectiveness_score)
                        VALUES (%s, 1, 1, 0.6)
                        ON CONFLICT (context_type, trigger_keyword) DO UPDATE SET
                            times_loaded = context_effectiveness.times_loaded + 1,
                            times_useful = context_effectiveness.times_useful + 1,
                            effectiveness_score = (
                                context_effectiveness.times_useful + 1
                            )::float / (context_effectiveness.times_loaded + 1),
                            last_used_at = NOW()
                    """, (ctx_type,))

            return {"success": True, "marked_useful": useful_types}

        except Exception as e:
            logger.error(f"Mark context useful failed: {e}")
            return {"success": False, "error": str(e)}

    def get_context_stats(self) -> Dict[str, Any]:
        """Get statistics on context loading effectiveness."""
        try:
            with get_cursor() as cur:
                cur.execute("""
                    SELECT context_type,
                           SUM(times_loaded) as total_loaded,
                           SUM(times_useful) as total_useful,
                           AVG(effectiveness_score) as avg_effectiveness
                    FROM context_effectiveness
                    GROUP BY context_type
                    ORDER BY avg_effectiveness DESC
                """)

                stats = []
                for row in cur.fetchall():
                    stats.append({
                        "type": row['context_type'],
                        "loaded": row['total_loaded'],
                        "useful": row['total_useful'],
                        "effectiveness": round(row['avg_effectiveness'] * 100, 1) if row['avg_effectiveness'] else 0
                    })

                return {"success": True, "stats": stats}

        except Exception as e:
            logger.error(f"Get context stats failed: {e}")
            return {"success": False, "error": str(e)}

    def build_context_prompt(
        self,
        loaded_context: Dict[str, Any]
    ) -> str:
        """
        Build a context string for prompt injection.

        Formats loaded context into a concise prompt section.
        """
        if not loaded_context.get('success') or not loaded_context.get('context'):
            return ""

        sections = []
        ctx = loaded_context['context']

        if ctx.get('preferences'):
            prefs = [p['fact'] for p in ctx['preferences'][:2]]
            if prefs:
                sections.append(f"User Preferences: {'; '.join(prefs)}")

        if ctx.get('recent_conversations'):
            topics = [c['topic'] for c in ctx['recent_conversations'][:2]]
            if topics:
                sections.append(f"Recent Topics: {', '.join(topics)}")

        if ctx.get('project'):
            files = [p['file'] for p in ctx['project'][:3]]
            if files:
                sections.append(f"Recent Files: {', '.join(files)}")

        if ctx.get('session'):
            session = ctx['session']
            if session.get('session_type'):
                sections.append(f"Session Mode: {session['session_type']}")

        if sections:
            return "\n## Proactive Context\n" + "\n".join(f"- {s}" for s in sections)
        return ""


# Singleton instance
_service: Optional[ProactiveContextService] = None


def get_proactive_context_service() -> ProactiveContextService:
    """Get or create service instance."""
    global _service
    if _service is None:
        _service = ProactiveContextService()
    return _service
