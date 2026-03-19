"""
Smart Tool Suggestions - Phase 21 Option 2B

After a response, suggests tools that could have been useful but weren't used.
Uses embedding similarity to match query intent with tool capabilities.
"""
import numpy as np
from typing import Dict, Any, List, Optional, Set
from dataclasses import dataclass
from functools import lru_cache
import time

from ..observability import get_logger, log_with_context
from ..embed import embed_texts

logger = get_logger("jarvis.tool_suggestions")

# Configuration
SIMILARITY_THRESHOLD = 0.45  # Minimum similarity to suggest
MAX_SUGGESTIONS = 3  # Maximum suggestions per response
CACHE_TTL_SECONDS = 300  # Tool embedding cache TTL


@dataclass
class ToolSuggestion:
    """A suggested tool with context."""
    tool_name: str
    description: str
    usage_hint: str
    similarity: float
    category: str


class ToolSuggestionService:
    """
    Service for suggesting relevant tools that weren't used.

    Compares user query embedding against tool description embeddings
    to find potentially useful tools the LLM didn't invoke.
    """

    _instance = None
    _tool_embeddings: Dict[str, np.ndarray] = {}
    _tool_metadata: Dict[str, Dict[str, Any]] = {}
    _last_cache_update: float = 0

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def _load_tool_embeddings(self, force_refresh: bool = False):
        """Load and cache tool embeddings from database."""
        now = time.time()

        # Skip if cache is fresh
        if not force_refresh and (now - self._last_cache_update) < CACHE_TTL_SECONDS:
            if self._tool_embeddings:
                return

        try:
            from ..postgres_state import get_conn

            with get_conn() as conn:
                with conn.cursor() as cur:
                    # Get tools with usage hints and keywords
                    cur.execute("""
                        SELECT name, description, usage_hint, keywords, category
                        FROM jarvis_tools
                        WHERE enabled = true
                          AND use_count < 10  -- Focus on underused tools
                        ORDER BY use_count ASC
                        LIMIT 200
                    """)

                    tools = []
                    for row in cur.fetchall():
                        name = row[0]
                        description = row[1] or ""
                        usage_hint = row[2] or ""
                        keywords = row[3] or []
                        category = row[4] or "general"

                        # Build embedding text from description + hint + keywords
                        embed_text = f"{description} {usage_hint} {' '.join(keywords) if keywords else ''}"

                        tools.append({
                            "name": name,
                            "description": description,
                            "usage_hint": usage_hint,
                            "category": category,
                            "embed_text": embed_text.strip()
                        })

                    if not tools:
                        return

                    # Batch embed all tool descriptions
                    embed_texts_list = [t["embed_text"] for t in tools]
                    embeddings = embed_texts(embed_texts_list)

                    # Store in cache
                    self._tool_embeddings = {}
                    self._tool_metadata = {}

                    for tool, embedding in zip(tools, embeddings):
                        self._tool_embeddings[tool["name"]] = np.array(embedding)
                        self._tool_metadata[tool["name"]] = {
                            "description": tool["description"],
                            "usage_hint": tool["usage_hint"],
                            "category": tool["category"]
                        }

                    self._last_cache_update = now

                    log_with_context(
                        logger, "info", "Tool embeddings loaded",
                        tool_count=len(self._tool_embeddings)
                    )

        except Exception as e:
            log_with_context(logger, "warning", "Failed to load tool embeddings", error=str(e))

    def get_suggestions(
        self,
        query: str,
        used_tools: Set[str],
        response_text: str = "",
        max_suggestions: int = MAX_SUGGESTIONS
    ) -> List[ToolSuggestion]:
        """
        Get tool suggestions based on query similarity.

        Args:
            query: The user's original query
            used_tools: Set of tool names that were already used
            response_text: The generated response (for additional context)
            max_suggestions: Maximum number of suggestions to return

        Returns:
            List of ToolSuggestion objects, sorted by relevance
        """
        if not query:
            return []

        # Ensure embeddings are loaded
        self._load_tool_embeddings()

        if not self._tool_embeddings:
            return []

        try:
            # Embed the query
            query_embedding = np.array(embed_texts([query])[0])

            # Calculate similarities
            similarities = []

            for tool_name, tool_embedding in self._tool_embeddings.items():
                # Skip tools that were already used
                if tool_name in used_tools:
                    continue

                # Cosine similarity (embeddings are normalized)
                similarity = float(np.dot(query_embedding, tool_embedding))

                if similarity >= SIMILARITY_THRESHOLD:
                    metadata = self._tool_metadata.get(tool_name, {})
                    similarities.append(ToolSuggestion(
                        tool_name=tool_name,
                        description=metadata.get("description", ""),
                        usage_hint=metadata.get("usage_hint", ""),
                        similarity=similarity,
                        category=metadata.get("category", "general")
                    ))

            # Sort by similarity descending
            similarities.sort(key=lambda x: x.similarity, reverse=True)

            # Return top suggestions
            suggestions = similarities[:max_suggestions]

            if suggestions:
                log_with_context(
                    logger, "debug", "Tool suggestions generated",
                    query_preview=query[:50],
                    suggestion_count=len(suggestions),
                    top_tool=suggestions[0].tool_name if suggestions else None,
                    top_similarity=suggestions[0].similarity if suggestions else 0
                )

            return suggestions

        except Exception as e:
            log_with_context(logger, "warning", "Failed to generate suggestions", error=str(e))
            return []

    def format_suggestions(self, suggestions: List[ToolSuggestion]) -> str:
        """Format suggestions as a user-friendly string."""
        if not suggestions:
            return ""

        lines = ["\n💡 **Tipp:** Diese Tools könnten auch hilfreich sein:"]

        for s in suggestions:
            hint = s.usage_hint if s.usage_hint else s.description[:80]
            lines.append(f"- `{s.tool_name}`: {hint}")

        return "\n".join(lines)

    def record_suggestion_feedback(
        self,
        tool_name: str,
        was_helpful: bool,
        session_id: Optional[str] = None
    ):
        """Record whether a suggestion was helpful (for learning)."""
        try:
            from ..postgres_state import get_conn

            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO jarvis_tool_suggestion_feedback
                        (tool_name, was_helpful, session_id, created_at)
                        VALUES (%s, %s, %s, NOW())
                    """, (tool_name, was_helpful, session_id))
                    conn.commit()

        except Exception as e:
            # Table might not exist yet - that's OK
            log_with_context(logger, "debug", "Could not record feedback", error=str(e))


# Singleton accessor
_service = None

def get_tool_suggestion_service() -> ToolSuggestionService:
    """Get the singleton ToolSuggestionService instance."""
    global _service
    if _service is None:
        _service = ToolSuggestionService()
    return _service


def suggest_tools(
    query: str,
    used_tools: List[str],
    include_format: bool = True
) -> Dict[str, Any]:
    """
    Convenience function to get tool suggestions.

    Args:
        query: User query
        used_tools: List of tools already used
        include_format: Whether to include formatted string

    Returns:
        Dict with suggestions and optional formatted string
    """
    service = get_tool_suggestion_service()
    suggestions = service.get_suggestions(query, set(used_tools))

    result = {
        "suggestions": [
            {
                "tool_name": s.tool_name,
                "description": s.description,
                "usage_hint": s.usage_hint,
                "similarity": round(s.similarity, 3),
                "category": s.category
            }
            for s in suggestions
        ],
        "count": len(suggestions)
    }

    if include_format and suggestions:
        result["formatted"] = service.format_suggestions(suggestions)

    return result
