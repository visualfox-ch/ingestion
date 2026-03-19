"""
Smart Tool Chain Service - Phase 2.2

Learns and suggests tool sequences (chains):
- Extracts common tool sequences from historical usage
- Suggests tool chains based on query intent
- Tracks chain effectiveness
- Provides multi-step workflow recommendations
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from collections import defaultdict
import json

from ..postgres_state import get_cursor, get_dict_cursor

logger = logging.getLogger(__name__)

# Minimum chain length to track
MIN_CHAIN_LENGTH = 2
# Maximum chain length to track
MAX_CHAIN_LENGTH = 5
# Time window for considering tools as part of same chain (minutes)
CHAIN_TIME_WINDOW = 10


class SmartToolChainService:
    """
    Learns and suggests tool chains (sequences).

    A tool chain is a sequence of tools commonly used together
    to accomplish a task. For example: search -> read_file -> write_file
    """

    def __init__(self):
        self._ensure_tables()

    def _ensure_tables(self):
        """Ensure tool chain tables exist."""
        try:
            with get_cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS tool_chains (
                        id SERIAL PRIMARY KEY,
                        chain_hash VARCHAR(64) UNIQUE NOT NULL,
                        chain_tools JSONB NOT NULL,
                        chain_length INTEGER NOT NULL,
                        occurrence_count INTEGER DEFAULT 1,
                        success_count INTEGER DEFAULT 0,
                        avg_duration_ms FLOAT,
                        trigger_keywords JSONB DEFAULT '[]'::jsonb,
                        last_seen_at TIMESTAMP DEFAULT NOW(),
                        created_at TIMESTAMP DEFAULT NOW()
                    );

                    CREATE INDEX IF NOT EXISTS idx_tool_chains_length
                        ON tool_chains(chain_length);
                    CREATE INDEX IF NOT EXISTS idx_tool_chains_count
                        ON tool_chains(occurrence_count DESC);
                    CREATE INDEX IF NOT EXISTS idx_tool_chains_hash
                        ON tool_chains(chain_hash);

                    CREATE TABLE IF NOT EXISTS chain_suggestions (
                        id SERIAL PRIMARY KEY,
                        trigger_tool VARCHAR(100) NOT NULL,
                        suggested_chain JSONB NOT NULL,
                        suggestion_count INTEGER DEFAULT 1,
                        acceptance_count INTEGER DEFAULT 0,
                        effectiveness_score FLOAT DEFAULT 0.5,
                        last_suggested_at TIMESTAMP DEFAULT NOW(),
                        UNIQUE(trigger_tool, suggested_chain)
                    );

                    CREATE INDEX IF NOT EXISTS idx_chain_suggestions_trigger
                        ON chain_suggestions(trigger_tool);
                """)
        except Exception as e:
            logger.debug(f"Tables may already exist: {e}")

    def learn_chains_from_audit(
        self,
        days: int = 30,
        min_occurrences: int = 2
    ) -> Dict[str, Any]:
        """
        Learn tool chains from tool_audit history.

        Analyzes tool sequences within sessions to find common patterns.
        """
        try:
            with get_cursor() as cur:
                # Get tool calls grouped by approximate session
                # (tools called within CHAIN_TIME_WINDOW minutes of each other)
                cur.execute("""
                    SELECT tool_name, tool_input, created_at, success
                    FROM tool_audit
                    WHERE created_at > NOW() - make_interval(days => %s)
                    ORDER BY created_at ASC
                """, (days,))

                # Convert to list of dicts for _extract_chains
                rows = []
                columns = ['tool_name', 'tool_input', 'created_at', 'success']
                for row in cur.fetchall():
                    rows.append(dict(zip(columns, row)))

                # Group into chains
                chains = self._extract_chains(rows)

                # Count and save chains
                chain_counts = defaultdict(lambda: {
                    'count': 0,
                    'successes': 0,
                    'keywords': set()
                })

                for chain, success, keywords in chains:
                    if MIN_CHAIN_LENGTH <= len(chain) <= MAX_CHAIN_LENGTH:
                        chain_key = tuple(chain)
                        chain_counts[chain_key]['count'] += 1
                        if success:
                            chain_counts[chain_key]['successes'] += 1
                        chain_counts[chain_key]['keywords'].update(keywords)

                # Save chains that meet minimum occurrence
                saved = 0
                for chain_tuple, stats in chain_counts.items():
                    if stats['count'] >= min_occurrences:
                        chain_list = list(chain_tuple)
                        chain_hash = self._hash_chain(chain_list)

                        keywords_list = list(stats['keywords'])[:10]

                        cur.execute("""
                            INSERT INTO tool_chains
                            (chain_hash, chain_tools, chain_length, occurrence_count,
                             success_count, trigger_keywords, last_seen_at)
                            VALUES (%s, %s, %s, %s, %s, %s, NOW())
                            ON CONFLICT (chain_hash) DO UPDATE SET
                                occurrence_count = tool_chains.occurrence_count + EXCLUDED.occurrence_count,
                                success_count = tool_chains.success_count + EXCLUDED.success_count,
                                trigger_keywords = EXCLUDED.trigger_keywords,
                                last_seen_at = NOW()
                        """, (
                            chain_hash,
                            json.dumps(chain_list),
                            len(chain_list),
                            stats['count'],
                            stats['successes'],
                            json.dumps(keywords_list)
                        ))
                        saved += 1

                return {
                    "success": True,
                    "chains_found": len(chain_counts),
                    "chains_saved": saved,
                    "period_days": days
                }

        except Exception as e:
            logger.error(f"Learn chains from audit failed: {e}")
            return {"success": False, "error": str(e)}

    def _extract_chains(
        self,
        rows: List[Any]
    ) -> List[Tuple[List[str], bool, List[str]]]:
        """Extract tool chains from ordered tool calls."""
        chains = []
        current_chain = []
        current_success = True
        current_keywords = []
        last_time = None

        for row in rows:
            tool_name = row['tool_name']
            created_at = row['created_at']
            success = row['success']
            tool_input = row['tool_input'] or {}

            # Extract keywords from input
            keywords = []
            for field in ['query', 'search_query', 'question', 'topic']:
                if field in tool_input and tool_input[field]:
                    words = str(tool_input[field]).lower().split()[:5]
                    keywords.extend(words)

            if last_time is None:
                # Start new chain
                current_chain = [tool_name]
                current_success = success
                current_keywords = keywords
                last_time = created_at
            elif (created_at - last_time).total_seconds() <= CHAIN_TIME_WINDOW * 60:
                # Continue chain
                current_chain.append(tool_name)
                current_success = current_success and success
                current_keywords.extend(keywords)
                last_time = created_at
            else:
                # Save current chain and start new
                if len(current_chain) >= MIN_CHAIN_LENGTH:
                    chains.append((current_chain, current_success, current_keywords))

                current_chain = [tool_name]
                current_success = success
                current_keywords = keywords
                last_time = created_at

        # Don't forget the last chain
        if len(current_chain) >= MIN_CHAIN_LENGTH:
            chains.append((current_chain, current_success, current_keywords))

        return chains

    def _hash_chain(self, chain: List[str]) -> str:
        """Create a hash for a tool chain."""
        import hashlib
        chain_str = "->".join(chain)
        return hashlib.md5(chain_str.encode()).hexdigest()

    def suggest_chain(
        self,
        trigger_tool: str = None,
        query: str = None,
        limit: int = 3
    ) -> Dict[str, Any]:
        """
        Suggest tool chains based on trigger tool or query.

        Args:
            trigger_tool: The tool that starts the chain (optional)
            query: Query to match against chain keywords (optional)
            limit: Max chains to suggest

        Returns:
            Dict with suggested chains and reasoning
        """
        try:
            with get_dict_cursor() as cur:
                suggestions = []

                # 1. Find chains starting with trigger tool
                if trigger_tool:
                    cur.execute("""
                        SELECT chain_tools, occurrence_count, success_count, trigger_keywords
                        FROM tool_chains
                        WHERE chain_tools->>0 = %s
                        ORDER BY occurrence_count DESC
                        LIMIT %s
                    """, (trigger_tool, limit))

                    for row in cur.fetchall():
                        chain = row['chain_tools']
                        success_rate = (row['success_count'] / row['occurrence_count'] * 100
                                       if row['occurrence_count'] > 0 else 0)
                        suggestions.append({
                            "chain": chain,
                            "occurrences": row['occurrence_count'],
                            "success_rate": round(success_rate, 1),
                            "reason": f"Common chain starting with {trigger_tool}",
                            "keywords": row['trigger_keywords'][:5] if row['trigger_keywords'] else []
                        })

                # 2. Find chains matching query keywords
                if query and len(suggestions) < limit:
                    query_words = query.lower().split()[:5]

                    for word in query_words:
                        if len(suggestions) >= limit:
                            break

                        cur.execute("""
                            SELECT chain_tools, occurrence_count, success_count, trigger_keywords
                            FROM tool_chains
                            WHERE trigger_keywords::text ILIKE %s
                            AND chain_hash NOT IN (
                                SELECT chain_hash FROM tool_chains
                                WHERE chain_tools->>0 = %s
                            )
                            ORDER BY occurrence_count DESC
                            LIMIT %s
                        """, (f'%{word}%', trigger_tool or '', limit - len(suggestions)))

                        for row in cur.fetchall():
                            chain = row['chain_tools']
                            if not any(s['chain'] == chain for s in suggestions):
                                success_rate = (row['success_count'] / row['occurrence_count'] * 100
                                               if row['occurrence_count'] > 0 else 0)
                                suggestions.append({
                                    "chain": chain,
                                    "occurrences": row['occurrence_count'],
                                    "success_rate": round(success_rate, 1),
                                    "reason": f"Matches keyword '{word}'",
                                    "keywords": row['trigger_keywords'][:5] if row['trigger_keywords'] else []
                                })

                # 3. Fall back to most common chains
                if not suggestions:
                    cur.execute("""
                        SELECT chain_tools, occurrence_count, success_count
                        FROM tool_chains
                        ORDER BY occurrence_count DESC
                        LIMIT %s
                    """, (limit,))

                    for row in cur.fetchall():
                        success_rate = (row['success_count'] / row['occurrence_count'] * 100
                                       if row['occurrence_count'] > 0 else 0)
                        suggestions.append({
                            "chain": row['chain_tools'],
                            "occurrences": row['occurrence_count'],
                            "success_rate": round(success_rate, 1),
                            "reason": "Most common chain"
                        })

                return {
                    "success": True,
                    "trigger_tool": trigger_tool,
                    "query": query[:50] if query else None,
                    "suggestions": suggestions
                }

        except Exception as e:
            logger.error(f"Suggest chain failed: {e}")
            return {"success": False, "error": str(e)}

    def get_top_chains(
        self,
        limit: int = 10,
        min_length: int = 2
    ) -> Dict[str, Any]:
        """Get top tool chains by usage."""
        try:
            with get_dict_cursor() as cur:
                cur.execute("""
                    SELECT chain_tools, chain_length, occurrence_count,
                           success_count, trigger_keywords
                    FROM tool_chains
                    WHERE chain_length >= %s
                    ORDER BY occurrence_count DESC
                    LIMIT %s
                """, (min_length, limit))

                chains = []
                for row in cur.fetchall():
                    success_rate = (row['success_count'] / row['occurrence_count'] * 100
                                   if row['occurrence_count'] > 0 else 0)
                    chains.append({
                        "chain": row['chain_tools'],
                        "length": row['chain_length'],
                        "occurrences": row['occurrence_count'],
                        "success_rate": round(success_rate, 1),
                        "keywords": row['trigger_keywords'][:5] if row['trigger_keywords'] else []
                    })

                return {
                    "success": True,
                    "total_chains": len(chains),
                    "chains": chains
                }

        except Exception as e:
            logger.error(f"Get top chains failed: {e}")
            return {"success": False, "error": str(e)}

    def get_chains_for_tool(
        self,
        tool_name: str,
        position: str = "any",
        limit: int = 5
    ) -> Dict[str, Any]:
        """
        Get chains that include a specific tool.

        Args:
            tool_name: Tool to find chains for
            position: "start", "end", or "any"
            limit: Max chains to return
        """
        try:
            with get_dict_cursor() as cur:
                if position == "start":
                    cur.execute("""
                        SELECT chain_tools, occurrence_count, success_count
                        FROM tool_chains
                        WHERE chain_tools->>0 = %s
                        ORDER BY occurrence_count DESC
                        LIMIT %s
                    """, (tool_name, limit))
                elif position == "end":
                    cur.execute("""
                        SELECT chain_tools, occurrence_count, success_count
                        FROM tool_chains
                        WHERE chain_tools->>(jsonb_array_length(chain_tools) - 1) = %s
                        ORDER BY occurrence_count DESC
                        LIMIT %s
                    """, (tool_name, limit))
                else:
                    cur.execute("""
                        SELECT chain_tools, occurrence_count, success_count
                        FROM tool_chains
                        WHERE chain_tools::text LIKE %s
                        ORDER BY occurrence_count DESC
                        LIMIT %s
                    """, (f'%"{tool_name}"%', limit))

                chains = []
                for row in cur.fetchall():
                    success_rate = (row['success_count'] / row['occurrence_count'] * 100
                                   if row['occurrence_count'] > 0 else 0)
                    chains.append({
                        "chain": row['chain_tools'],
                        "occurrences": row['occurrence_count'],
                        "success_rate": round(success_rate, 1)
                    })

                return {
                    "success": True,
                    "tool": tool_name,
                    "position": position,
                    "chains": chains
                }

        except Exception as e:
            logger.error(f"Get chains for tool failed: {e}")
            return {"success": False, "error": str(e)}

    def record_chain_usage(
        self,
        chain: List[str],
        success: bool,
        duration_ms: int = None
    ) -> Dict[str, Any]:
        """Record a tool chain execution for learning."""
        try:
            if len(chain) < MIN_CHAIN_LENGTH:
                return {"success": True, "recorded": False, "reason": "Chain too short"}

            chain_hash = self._hash_chain(chain)

            with get_cursor() as cur:
                cur.execute("""
                    INSERT INTO tool_chains
                    (chain_hash, chain_tools, chain_length, occurrence_count,
                     success_count, avg_duration_ms, last_seen_at)
                    VALUES (%s, %s, %s, 1, %s, %s, NOW())
                    ON CONFLICT (chain_hash) DO UPDATE SET
                        occurrence_count = tool_chains.occurrence_count + 1,
                        success_count = tool_chains.success_count + %s,
                        avg_duration_ms = CASE
                            WHEN %s IS NOT NULL THEN
                                (COALESCE(tool_chains.avg_duration_ms, 0) *
                                 tool_chains.occurrence_count + %s) /
                                (tool_chains.occurrence_count + 1)
                            ELSE tool_chains.avg_duration_ms
                        END,
                        last_seen_at = NOW()
                """, (
                    chain_hash,
                    json.dumps(chain),
                    len(chain),
                    1 if success else 0,
                    duration_ms,
                    1 if success else 0,
                    duration_ms, duration_ms
                ))

            return {"success": True, "recorded": True, "chain_length": len(chain)}

        except Exception as e:
            logger.error(f"Record chain usage failed: {e}")
            return {"success": False, "error": str(e)}


# Singleton instance
_service: Optional[SmartToolChainService] = None


def get_smart_tool_chain_service() -> SmartToolChainService:
    """Get or create service instance."""
    global _service
    if _service is None:
        _service = SmartToolChainService()
    return _service
