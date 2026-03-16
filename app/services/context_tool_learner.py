"""
Context → Tool Learner Service

Learns which query patterns lead to which tools:
- Extracts keywords from successful tool calls
- Builds keyword → tool mappings with confidence scores
- Suggests tools based on query context
- Auto-learns from new interactions
"""

import logging
import re
import hashlib
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from collections import defaultdict

from ..postgres_state import get_cursor, get_dict_cursor

logger = logging.getLogger(__name__)

# Stop words to ignore in keyword extraction
STOP_WORDS = {
    'der', 'die', 'das', 'ein', 'eine', 'und', 'oder', 'aber', 'wenn', 'als',
    'mit', 'von', 'zu', 'für', 'auf', 'in', 'an', 'bei', 'nach', 'vor',
    'the', 'a', 'an', 'and', 'or', 'but', 'if', 'as', 'with', 'from', 'to',
    'for', 'on', 'in', 'at', 'by', 'after', 'before', 'is', 'are', 'was',
    'ich', 'du', 'er', 'sie', 'es', 'wir', 'ihr', 'mir', 'dir', 'mich', 'dich',
    'wie', 'was', 'wer', 'wann', 'wo', 'warum', 'welche', 'welcher', 'welches',
    'how', 'what', 'who', 'when', 'where', 'why', 'which', 'can', 'could',
    'bitte', 'please', 'danke', 'thanks', 'ja', 'nein', 'yes', 'no',
    'kannst', 'könntest', 'zeig', 'zeige', 'sag', 'sage', 'gibt', 'gibt es',
    'hast', 'hat', 'haben', 'sind', 'ist', 'war', 'waren', 'meine', 'deine'
}

# Minimum keyword length
MIN_KEYWORD_LENGTH = 3


class ContextToolLearner:
    """
    Learns context → tool mappings from usage data.

    Uses tool_audit to build mappings and stores them in context_tool_mapping.
    """

    def __init__(self):
        pass  # Uses postgres_state cursor helpers for DB access

    def extract_keywords(self, text: str) -> List[str]:
        """Extract meaningful keywords from text."""
        if not text:
            return []

        # Lowercase and extract words
        text = text.lower()
        words = re.findall(r'\b[a-zäöüß]+\b', text)

        # Filter out stop words and short words
        keywords = [
            w for w in words
            if w not in STOP_WORDS and len(w) >= MIN_KEYWORD_LENGTH
        ]

        # Return unique keywords (max 10)
        return list(dict.fromkeys(keywords))[:10]

    def learn_from_audit(
        self,
        days: int = 30,
        min_occurrences: int = 2
    ) -> Dict[str, Any]:
        """
        Learn context → tool mappings from tool_audit data.

        Analyzes successful tool calls and builds keyword → tool mappings.
        """
        try:
            with get_cursor() as cur:
                # Get successful tool calls with queries
                cur.execute("""
                    SELECT tool_name, tool_input, duration_ms
                    FROM tool_audit
                    WHERE created_at > NOW() - make_interval(days => %s)
                    AND success = true
                    AND tool_input IS NOT NULL
                    AND tool_input != '{}'::jsonb
                """, (days,))

                rows = cur.fetchall()

                # Build keyword → tool mappings
                keyword_tools = defaultdict(lambda: defaultdict(lambda: {
                    'count': 0,
                    'total_duration': 0
                }))

                for tool_name, tool_input, duration_ms in rows:
                    # Extract query text from various fields
                    query_text = ''
                    for field in ['query', 'search_query', 'question', 'topic', 'keyword', 'text']:
                        if field in tool_input and tool_input[field]:
                            query_text += ' ' + str(tool_input[field])

                    keywords = self.extract_keywords(query_text)

                    for kw in keywords:
                        keyword_tools[kw][tool_name]['count'] += 1
                        keyword_tools[kw][tool_name]['total_duration'] += (duration_ms or 0)

                # Save to database
                saved_count = 0
                for keyword, tools in keyword_tools.items():
                    for tool_name, stats in tools.items():
                        if stats['count'] >= min_occurrences:
                            avg_duration = stats['total_duration'] / stats['count'] if stats['count'] > 0 else 0

                            cur.execute("""
                                INSERT INTO context_tool_mapping
                                (context_keyword, tool_name, occurrence_count, avg_duration_ms, last_seen_at)
                                VALUES (%s, %s, %s, %s, NOW())
                                ON CONFLICT (context_keyword, tool_name) DO UPDATE SET
                                    occurrence_count = context_tool_mapping.occurrence_count + EXCLUDED.occurrence_count,
                                    avg_duration_ms = (context_tool_mapping.avg_duration_ms + EXCLUDED.avg_duration_ms) / 2,
                                    last_seen_at = NOW()
                            """, (keyword, tool_name, stats['count'], avg_duration))
                            saved_count += 1

                return {
                    "success": True,
                    "keywords_analyzed": len(keyword_tools),
                    "mappings_saved": saved_count,
                    "period_days": days
                }

        except Exception as e:
            logger.error(f"Learn from audit failed: {e}")
            return {"success": False, "error": str(e)}

    def suggest_tools(
        self,
        query: str,
        limit: int = 5
    ) -> Dict[str, Any]:
        """
        Suggest tools based on query context.

        Analyzes query keywords and returns tools that worked well for similar queries.
        """
        try:
            keywords = self.extract_keywords(query)

            if not keywords:
                return {
                    "success": True,
                    "query": query,
                    "suggestions": [],
                    "reason": "No meaningful keywords extracted"
                }

            with get_cursor() as cur:
                # Find tools for each keyword
                placeholders = ','.join(['%s'] * len(keywords))
                cur.execute(f"""
                    SELECT tool_name,
                           SUM(occurrence_count) as total_occurrences,
                           AVG(success_rate) as avg_success_rate,
                           AVG(avg_duration_ms) as avg_duration,
                           ARRAY_AGG(DISTINCT context_keyword) as matched_keywords
                    FROM context_tool_mapping
                    WHERE context_keyword IN ({placeholders})
                    GROUP BY tool_name
                    ORDER BY SUM(occurrence_count) DESC
                    LIMIT %s
                """, (*keywords, limit))

                rows = cur.fetchall()

                suggestions = []
                for row in rows:
                    occurrences = row['total_occurrences'] or 0
                    suggestions.append({
                        "tool": row['tool_name'],
                        "confidence": min(occurrences / 10, 1.0),  # Normalize to 0-1
                        "occurrences": occurrences,
                        "success_rate": round(row['avg_success_rate'] * 100, 1) if row['avg_success_rate'] else 100.0,
                        "avg_duration_ms": round(row['avg_duration'], 1) if row['avg_duration'] else 0,
                        "matched_keywords": row['matched_keywords']
                    })

                return {
                    "success": True,
                    "query": query,
                    "extracted_keywords": keywords,
                    "suggestions": suggestions
                }

        except Exception as e:
            logger.error(f"Suggest tools failed: {e}")
            return {"success": False, "error": str(e)}

    def record_tool_success(
        self,
        query: str,
        tool_name: str,
        success: bool = True,
        duration_ms: int = None
    ) -> Dict[str, Any]:
        """
        Record a tool usage for learning.

        Called after each tool execution to update context mappings.
        """
        try:
            keywords = self.extract_keywords(query)

            if not keywords:
                return {"success": True, "recorded": 0}

            with get_cursor() as cur:
                recorded = 0
                for kw in keywords:
                    # Update or insert mapping
                    cur.execute("""
                        INSERT INTO context_tool_mapping
                        (context_keyword, tool_name, occurrence_count, success_rate, avg_duration_ms, last_seen_at)
                        VALUES (%s, %s, 1, %s, %s, NOW())
                        ON CONFLICT (context_keyword, tool_name) DO UPDATE SET
                            occurrence_count = context_tool_mapping.occurrence_count + 1,
                            success_rate = (context_tool_mapping.success_rate * context_tool_mapping.occurrence_count + %s) /
                                          (context_tool_mapping.occurrence_count + 1),
                            avg_duration_ms = CASE
                                WHEN %s IS NOT NULL THEN
                                    (COALESCE(context_tool_mapping.avg_duration_ms, 0) * context_tool_mapping.occurrence_count + %s) /
                                    (context_tool_mapping.occurrence_count + 1)
                                ELSE context_tool_mapping.avg_duration_ms
                            END,
                            last_seen_at = NOW()
                    """, (
                        kw, tool_name,
                        1.0 if success else 0.0,
                        duration_ms,
                        1.0 if success else 0.0,
                        duration_ms, duration_ms
                    ))
                    recorded += 1

                return {"success": True, "recorded": recorded, "keywords": keywords}

        except Exception as e:
            logger.error(f"Record tool success failed: {e}")
            return {"success": False, "error": str(e)}

    def get_top_mappings(
        self,
        limit: int = 30
    ) -> Dict[str, Any]:
        """
        Get top keyword → tool mappings.

        Shows the most reliable context → tool associations.
        """
        try:
            with get_dict_cursor() as cur:
                cur.execute("""
                    SELECT context_keyword, tool_name, occurrence_count,
                           success_rate, avg_duration_ms, last_seen_at
                    FROM context_tool_mapping
                    ORDER BY occurrence_count DESC
                    LIMIT %s
                """, (limit,))

                rows = cur.fetchall()

                mappings = []
                for row in rows:
                    mappings.append({
                        "keyword": row['context_keyword'],
                        "tool": row['tool_name'],
                        "occurrences": row['occurrence_count'],
                        "success_rate": round(row['success_rate'] * 100, 1) if row['success_rate'] else 100.0,
                        "avg_duration_ms": round(row['avg_duration_ms'], 1) if row['avg_duration_ms'] else 0,
                        "last_seen": row['last_seen_at'].isoformat() if row['last_seen_at'] else None
                    })

                return {
                    "success": True,
                    "total_mappings": len(mappings),
                    "mappings": mappings
                }

        except Exception as e:
            logger.error(f"Get top mappings failed: {e}")
            return {"success": False, "error": str(e)}

    def get_tool_contexts(
        self,
        tool_name: str,
        limit: int = 20
    ) -> Dict[str, Any]:
        """
        Get contexts/keywords that lead to a specific tool.

        Helps understand when a tool is most useful.
        """
        try:
            with get_dict_cursor() as cur:
                cur.execute("""
                    SELECT context_keyword, occurrence_count, success_rate, avg_duration_ms
                    FROM context_tool_mapping
                    WHERE tool_name = %s
                    ORDER BY occurrence_count DESC
                    LIMIT %s
                """, (tool_name, limit))

                rows = cur.fetchall()

                contexts = []
                for row in rows:
                    contexts.append({
                        "keyword": row['context_keyword'],
                        "occurrences": row['occurrence_count'],
                        "success_rate": round(row['success_rate'] * 100, 1) if row['success_rate'] else 100.0,
                        "avg_duration_ms": round(row['avg_duration_ms'], 1) if row['avg_duration_ms'] else 0
                    })

                return {
                    "success": True,
                    "tool_name": tool_name,
                    "contexts": contexts
                }

        except Exception as e:
            logger.error(f"Get tool contexts failed: {e}")
            return {"success": False, "error": str(e)}

    def detect_session_type(
        self,
        recent_tools: List[str],
        query: str = None
    ) -> Dict[str, Any]:
        """
        Detect the current session type based on tools used and query.

        Returns session type (coding, planning, research, etc.) with confidence.
        """
        try:
            with get_dict_cursor() as cur:
                # Get session type patterns
                cur.execute("""
                    SELECT session_type, indicators, tool_preferences, confidence
                    FROM session_type_patterns
                    ORDER BY confidence DESC
                """)

                patterns = cur.fetchall()

                best_match = None
                best_score = 0

                for row in patterns:
                    session_type = row['session_type']
                    indicators = row['indicators']
                    preferences = row['tool_preferences']
                    base_confidence = row['confidence']

                    score = 0

                    # Check tool matches
                    indicator_tools = indicators.get('tools', []) if indicators else []
                    tool_matches = len(set(recent_tools) & set(indicator_tools))
                    score += tool_matches * 0.3

                    # Check keyword matches
                    if query:
                        keywords = self.extract_keywords(query)
                        indicator_keywords = indicators.get('keywords', []) if indicators else []
                        kw_matches = len(set(keywords) & set(indicator_keywords))
                        score += kw_matches * 0.2

                    score *= (base_confidence or 0.5)

                    if score > best_score:
                        best_score = score
                        best_match = {
                            "session_type": session_type,
                            "confidence": min(score, 1.0),
                            "tool_preferences": preferences,
                            "matched_indicators": {
                                "tools": list(set(recent_tools) & set(indicator_tools)),
                                "keywords": list(set(self.extract_keywords(query or '')) & set(indicators.get('keywords', []) if indicators else []))
                            }
                        }

                return {
                    "success": True,
                    "detected": best_match,
                    "all_types": [p['session_type'] for p in patterns]
                }

        except Exception as e:
            logger.error(f"Detect session type failed: {e}")
            return {"success": False, "error": str(e)}


# Singleton instance
_learner: Optional[ContextToolLearner] = None


def get_context_tool_learner() -> ContextToolLearner:
    """Get or create learner instance."""
    global _learner
    if _learner is None:
        _learner = ContextToolLearner()
    return _learner
