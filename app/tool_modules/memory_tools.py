"""
Memory Tools.

Fact storage, conversation context, person context.
Extracted from tools.py (Phase S4).
"""
from typing import Dict, Any, List, Optional
from datetime import datetime
import json
import os

from ..observability import get_logger, log_with_context, metrics
from ..langfuse_integration import observe, langfuse_context
from ..errors import JarvisException, ErrorCode, internal_error, wrap_external_error

logger = get_logger("jarvis.tools.memory")


def tool_remember_fact(
    fact: str,
    category: str,
    initial_trust_score: float = 0.0,
    source: str = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Store a fact about the user with graduated trust.

    Trust Score Guidelines:
    - 0.0: Inferred or uncertain facts
    - 0.3: User mentioned explicitly
    - 0.5: User confirmed when asked
    - 0.7: Repeatedly validated or critical info

    Facts with trust_score >= 0.5 AND access_count >= 5 become
    candidates for migration to permanent config/YAML storage.

    Raises:
        JarvisException: On database errors with structured error info
    """
    log_with_context(logger, "info", "Tool: remember_fact",
                    category=category, trust_score=initial_trust_score, source=source)
    metrics.inc("tool_remember_fact")

    try:
        from .. import memory_store
        fact_id = memory_store.add_fact(
            fact=fact,
            category=category,
            source=source,
            initial_trust_score=initial_trust_score
        )

        # Determine trust level description
        if initial_trust_score >= 0.7:
            trust_level = "high (validated)"
        elif initial_trust_score >= 0.5:
            trust_level = "medium (confirmed)"
        elif initial_trust_score >= 0.3:
            trust_level = "low (explicit)"
        else:
            trust_level = "minimal (inferred)"

        return {
            "status": "remembered",
            "fact": fact,
            "category": category,
            "fact_id": fact_id,
            "trust_score": initial_trust_score,
            "trust_level": trust_level,
            "source": source,
            "note": "Trust score increases with each access (+0.1). Migration candidate at trust >= 0.5 and access >= 5."
        }
    except Exception as e:
        error_msg = str(e)
        log_with_context(logger, "error", "Remember fact failed",
                        error=error_msg, category=category, error_type=type(e).__name__)

        # Check for common SQLite errors
        if "database is locked" in error_msg.lower():
            raise JarvisException(
                code=ErrorCode.POSTGRES_ERROR,  # Reusing for DB errors
                message="Memory database is temporarily locked",
                status_code=503,
                details={"category": category, "fact_preview": fact[:50]},
                recoverable=True,
                retry_after=5,
                hint="Another operation is using the database, try again shortly"
            )
        elif "disk" in error_msg.lower() or "full" in error_msg.lower():
            raise JarvisException(
                code=ErrorCode.INTERNAL_ERROR,
                message="Memory storage full or unavailable",
                status_code=507,
                details={"category": category},
                recoverable=False,
                hint="Check disk space on the system"
            )
        else:
            raise wrap_external_error(e, service="memory_store")


@observe(name="tool_recall_facts")
def tool_recall_facts(
    category: str = None,
    query: str = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Recall stored facts.

    Raises:
        JarvisException: On database errors with structured error info
    """
    log_with_context(logger, "info", "Tool: recall_facts", category=category, query=query)
    metrics.inc("tool_recall_facts")

    if langfuse_context:
        try:
            langfuse_context.update_current_trace(
                metadata={
                    "tool": "recall_facts",
                    "category": category,
                    "query_length": len(query) if query else 0,
                },
                tags=["tool", "recall_facts"],
            )
        except Exception:
            pass

    try:
        from .. import memory_store
        facts = memory_store.get_facts(category=category, query=query)

        return {
            "facts": facts,
            "count": len(facts),
            "category_filter": category,
            "query_filter": query
        }
    except Exception as e:
        error_msg = str(e)
        log_with_context(logger, "error", "Recall facts failed",
                        error=error_msg, category=category, error_type=type(e).__name__)

        # Check for common SQLite errors
        if "database is locked" in error_msg.lower():
            raise JarvisException(
                code=ErrorCode.POSTGRES_ERROR,
                message="Memory database is temporarily locked",
                status_code=503,
                details={"category": category, "query": query},
                recoverable=True,
                retry_after=5,
                hint="Another operation is using the database, try again shortly"
            )
        elif "corrupt" in error_msg.lower() or "malformed" in error_msg.lower():
            raise JarvisException(
                code=ErrorCode.INTERNAL_ERROR,
                message="Memory database may be corrupted",
                status_code=500,
                details={"category": category},
                recoverable=False,
                hint="Database maintenance may be required"
            )
        else:
            raise wrap_external_error(e, service="memory_store")


# NOTE: tool_no_tool_needed and tool_request_out_of_scope removed (T-020)
# Canonical definitions are in utility_tools.py


# ============ Context Persistence Tools ============

def tool_remember_conversation_context(
    session_summary: str,
    key_topics: List[str],
    pending_actions: List[str] = None,
    emotional_context: str = None,
    relationship_insights: str = None,
    session_id: str = None,
    user_id: int = None,
    namespace: str = "private",
    **kwargs
) -> Dict[str, Any]:
    """Store conversation context for future sessions"""
    log_with_context(logger, "info", "Tool: remember_conversation_context",
                    topics=len(key_topics), pending=len(pending_actions or []))
    metrics.inc("tool_remember_conversation_context")

    from .. import session_manager

    # Build emotional indicators
    emotional_indicators = {}
    if emotional_context:
        emotional_indicators["note"] = emotional_context

    # Build relationship updates
    relationship_updates = {}
    if relationship_insights:
        relationship_updates["insight"] = relationship_insights

    context = session_manager.ConversationContext(
        session_id=session_id or f"ctx_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        user_id=user_id or 0,
        start_time=datetime.now().isoformat(timespec="seconds"),
        conversation_summary=session_summary,
        key_topics=key_topics or [],
        pending_actions=pending_actions or [],
        emotional_indicators=emotional_indicators,
        relationship_updates=relationship_updates,
        namespace=namespace,
        message_count=kwargs.get("message_count", 0)
    )

    context_id = session_manager.save_conversation_context(context)

    return {
        "status": "context_saved",
        "context_id": context_id,
        "session_id": context.session_id,
        "topics_saved": len(key_topics),
        "pending_actions_saved": len(pending_actions or []),
        "summary": session_summary[:100] + "..." if len(session_summary) > 100 else session_summary
    }


def tool_recall_conversation_history(
    days_back: int = 7,
    topic_filter: str = None,
    include_pending_actions: bool = True,
    user_id: int = None,
    namespace: str = None,
    **kwargs
) -> Dict[str, Any]:
    """Retrieve relevant conversation context from previous sessions"""
    log_with_context(logger, "info", "Tool: recall_conversation_history",
                    days_back=days_back, topic_filter=topic_filter)
    metrics.inc("tool_recall_conversation_history")

    from .. import session_manager

    # Get conversation history
    history = session_manager.get_conversation_history(
        user_id=user_id,
        days_back=days_back,
        topic_filter=topic_filter,
        namespace=namespace,
        limit=10
    )

    # Get pending actions if requested
    pending = []
    if include_pending_actions:
        pending = session_manager.get_pending_actions(user_id=user_id, limit=10)

    # Get frequent topics
    frequent_topics = session_manager.get_recent_topics(
        user_id=user_id,
        days_back=days_back,
        limit=5
    )

    # Format for agent consumption
    formatted_history = []
    total_messages = 0
    auto_captured_sessions = 0
    for ctx in history:
        msg_count = ctx.get("message_count", 0)
        total_messages += msg_count
        source = ctx.get("source", "conversation_contexts")
        if source in ("session_messages", "enriched"):
            auto_captured_sessions += 1
        # Use end_time (most recent activity) for display, fall back to start_time
        display_date = ctx.get("end_time") or ctx.get("start_time") or ""
        formatted_history.append({
            "date": display_date[:10] if display_date else "unknown",
            "last_activity": display_date[:16] if display_date else "unknown",
            "started": ctx.get("start_time", "")[:10] if ctx.get("start_time") else "unknown",
            "summary": ctx.get("conversation_summary", ""),
            "topics": ctx.get("key_topics", []),
            "pending": ctx.get("pending_actions", []),
            "mood": ctx.get("emotional_indicators", {}).get("dominant", "neutral"),
            "message_count": msg_count,
            "source": source
        })

    # Build explicit diagnosis message for Jarvis
    if total_messages > 10:
        diagnosis = f"MEMORY OK: {total_messages} Nachrichten in {len(formatted_history)} Session(s) der letzten {days_back} Tage. Auto-Persist funktioniert."
    elif total_messages > 0:
        diagnosis = f"MEMORY SPARSE: Nur {total_messages} Nachrichten gefunden. Auto-Persist aktiv aber wenig Daten."
    else:
        diagnosis = "MEMORY EMPTY: Keine Conversation-Daten gefunden. Auto-Persist prüfen."

    return {
        "diagnosis": diagnosis,
        "conversations": formatted_history,
        "conversation_count": len(formatted_history),
        "total_messages": total_messages,
        "auto_captured_sessions": auto_captured_sessions,
        "memory_status": "healthy" if total_messages > 5 else "sparse",
        "pending_actions": [
            {"id": p["id"], "action": p["action_text"], "date": p["created_at"][:10]}
            for p in pending
        ],
        "pending_count": len(pending),
        "frequent_topics": [
            {"topic": t["topic"], "mentions": t["total_mentions"]}
            for t in frequent_topics
        ],
        "days_searched": days_back,
        "topic_filter": topic_filter
    }


def tool_get_person_context(person_id: str, **kwargs) -> Dict[str, Any]:
    """Get person profile from knowledge layer with JSON fallback"""
    log_with_context(logger, "info", "Tool: get_person_context", person_id=person_id)
    metrics.inc("tool_get_person_context")

    # Try knowledge layer first
    try:
        from .. import knowledge_db

        if knowledge_db.is_available():
            profile = knowledge_db.get_person_profile(person_id)
            if profile and profile.get("content"):
                return {
                    "person_id": person_id,
                    "source": "knowledge_layer",
                    "profile": profile["content"],
                    "version": profile.get("version_number"),
                    "status": "found"
                }
    except Exception as e:
        log_with_context(logger, "warning", "Knowledge layer lookup failed",
                        person_id=person_id, error=str(e))

    # Fallback to JSON file
    try:
        from pathlib import Path
        import json

        BRAIN_ROOT = Path(os.environ.get("BRAIN_ROOT", "/brain"))
        profile_path = BRAIN_ROOT / "system" / "profiles" / "persons" / f"{person_id}.json"

        if profile_path.exists():
            with open(profile_path, "r", encoding="utf-8") as f:
                content = json.load(f)
            return {
                "person_id": person_id,
                "source": "json_file",
                "profile": content,
                "status": "found"
            }
    except Exception as e:
        log_with_context(logger, "warning", "JSON profile lookup failed",
                        person_id=person_id, error=str(e))

    return {
        "person_id": person_id,
        "source": "none",
        "profile": None,
        "status": "not_found",
        "message": f"No profile found for {person_id}"
    }


# ============ Project Management Tools ============

# Global user_id for project tools (set by telegram handler)
_current_user_id = None

def tool_recall_with_timeframe(
    query: str = None,
    timeframe: str = "week",
    include_patterns: bool = True,
    include_emotional_context: bool = True,
    **kwargs
) -> Dict[str, Any]:
    """
    Recall context and patterns from a specific timeframe.

    Enhanced memory recall that includes:
    - Conversation patterns over time
    - Emotional trends
    - Recurring topics
    - Cross-session insights

    Args:
        query: Optional search query to filter memories
        timeframe: Time period (today, yesterday, week, month, quarter)
        include_patterns: Include detected patterns and recurring themes
        include_emotional_context: Include emotional/mood patterns

    Returns:
        Memories, patterns, and insights from the specified timeframe
    """
    log_with_context(logger, "info", "Tool: recall_with_timeframe", timeframe=timeframe)
    metrics.inc("tool_recall_with_timeframe")

    try:
        from datetime import datetime, timedelta

        # Calculate date range
        now = datetime.now()
        if timeframe == "today":
            start_date = now.replace(hour=0, minute=0, second=0)
        elif timeframe == "yesterday":
            start_date = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0)
        elif timeframe == "week":
            start_date = now - timedelta(days=7)
        elif timeframe == "month":
            start_date = now - timedelta(days=30)
        elif timeframe == "quarter":
            start_date = now - timedelta(days=90)
        else:
            start_date = now - timedelta(days=7)

        result = {
            "timeframe": timeframe,
            "start_date": start_date.isoformat(),
            "end_date": now.isoformat(),
            "memories": [],
            "patterns": [],
            "emotional_context": None
        }

        # Get conversations from timeframe
        from .postgres_state import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                # Get conversation summaries
                cur.execute("""
                    SELECT key, value, category, updated_at
                    FROM jarvis_context
                    WHERE updated_at >= %s
                    AND category IN ('conversation', 'session', 'topic')
                    ORDER BY updated_at DESC
                    LIMIT 50
                """, (start_date,))
                rows = cur.fetchall()

                result["memories"] = [
                    {
                        "key": r["key"],
                        "summary": r["value"][:200] if r["value"] else "",
                        "category": r["category"],
                        "timestamp": r["updated_at"].isoformat() if r["updated_at"] else None
                    }
                    for r in rows
                ]

                # Get patterns if requested
                if include_patterns:
                    cur.execute("""
                        SELECT key, value, confidence
                        FROM jarvis_context
                        WHERE category = 'pattern'
                        AND updated_at >= %s
                        ORDER BY confidence DESC
                        LIMIT 10
                    """, (start_date,))
                    pattern_rows = cur.fetchall()

                    result["patterns"] = [
                        {
                            "pattern": r["key"],
                            "description": r["value"][:150] if r["value"] else "",
                            "confidence": r["confidence"]
                        }
                        for r in pattern_rows
                    ]

                # Get emotional context if requested
                if include_emotional_context:
                    cur.execute("""
                        SELECT value, updated_at
                        FROM jarvis_context
                        WHERE category = 'emotional_state'
                        AND updated_at >= %s
                        ORDER BY updated_at DESC
                        LIMIT 5
                    """, (start_date,))
                    emotion_rows = cur.fetchall()

                    if emotion_rows:
                        result["emotional_context"] = {
                            "recent_states": [r["value"] for r in emotion_rows],
                            "trend": "Analyzing emotional patterns..."
                        }

        # Add cross-session insight
        result["insight"] = f"Gefunden: {len(result['memories'])} Memories, {len(result['patterns'])} Patterns aus den letzten {timeframe}"

        return result

    except Exception as e:
        log_with_context(logger, "error", "recall_with_timeframe failed", error=str(e))
        return {"error": str(e)}

