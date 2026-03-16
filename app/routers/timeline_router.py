"""
Timeline Router

Extracted from main.py - Timeline views for chronological analysis:
- Main timeline (GET/POST)
- Person timeline
- Topic timeline
- Project timeline
- Timeline overview
"""

import os
from fastapi import APIRouter
from pydantic import BaseModel
from datetime import datetime, timedelta
from typing import List, Dict

from ..observability import get_logger, log_with_context

logger = get_logger("jarvis.timeline")
router = APIRouter(prefix="/timeline", tags=["timeline"])

# Qdrant configuration
QDRANT_HOST = os.environ.get("QDRANT_HOST", "qdrant")
QDRANT_PORT = int(os.environ.get("QDRANT_PORT", "6333"))


# =============================================================================
# PYDANTIC MODELS
# =============================================================================

class TimelineRequest(BaseModel):
    namespace: str = "work_projektil"
    collection_suffix: str = ""
    query: str | None = None  # If provided, semantic search; else scroll
    channel: str | None = None  # Filter by channel
    doc_type: str | None = None  # Filter by doc_type
    person: str | None = None  # Filter by person (from or to)
    days: int | None = None  # Last N days only
    limit: int = 50
    min_score: float = 0.3  # Only used if query is provided


# =============================================================================
# MAIN TIMELINE
# =============================================================================

@router.get("")
def get_timeline(
    namespace: str = "work_projektil",
    collection_suffix: str = "",
    query: str | None = None,
    channel: str | None = None,
    doc_type: str | None = None,
    person: str | None = None,
    days: int | None = None,
    limit: int = 50,
    min_score: float = 0.3
):
    """
    Timeline endpoint: List chunks chronologically by event_ts.

    Supports:
    - Optional semantic search (query)
    - Filter by channel, doc_type, person
    - Time range filter (days)

    Returns chronologically sorted entries for "was war wann" analysis.
    """
    from qdrant_client import QdrantClient
    from qdrant_client.models import Filter, FieldCondition, MatchValue, Range

    client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
    collection = f"jarvis_{namespace}{collection_suffix}"

    # Build filter conditions
    must_conditions = []

    if channel:
        must_conditions.append(FieldCondition(key="channel", match=MatchValue(value=channel)))

    if doc_type:
        must_conditions.append(FieldCondition(key="doc_type", match=MatchValue(value=doc_type)))

    # Build filter object
    scroll_filter = None
    if must_conditions:
        scroll_filter = Filter(must=must_conditions)

    # Calculate date cutoff if days specified
    date_cutoff = None
    if days:
        date_cutoff = (datetime.now() - timedelta(days=days)).isoformat()

    results = []

    if query:
        # Semantic search mode
        from ..hybrid_search import hybrid_search
        search_results = hybrid_search(
            query=query,
            namespace=namespace,
            limit=limit,
            score_threshold=min_score
        )
        for r in search_results.get("results", []):
            event_ts = r.get("event_ts_start") or r.get("event_ts")
            if date_cutoff and event_ts and event_ts < date_cutoff:
                continue
            results.append({
                "event_ts": event_ts,
                "channel": r.get("channel"),
                "doc_type": r.get("doc_type"),
                "text": r.get("text", "")[:500],
                "score": r.get("score"),
                "chunk_id": r.get("chunk_id")
            })
    else:
        # Scroll mode - get recent entries
        try:
            scroll_result = client.scroll(
                collection_name=collection,
                scroll_filter=scroll_filter,
                limit=limit * 2,  # Get more to filter by date
                with_payload=True,
                with_vectors=False
            )

            for point in scroll_result[0]:
                payload = point.payload or {}
                event_ts = payload.get("event_ts_start") or payload.get("event_ts")
                if date_cutoff and event_ts and event_ts < date_cutoff:
                    continue
                results.append({
                    "event_ts": event_ts,
                    "channel": payload.get("channel"),
                    "doc_type": payload.get("doc_type"),
                    "text": payload.get("text", "")[:500],
                    "chunk_id": str(point.id)
                })
        except Exception as e:
            log_with_context(logger, "error", "Timeline scroll error", error=str(e))
            return {"error": str(e), "results": []}

    # Sort by event_ts descending
    results.sort(key=lambda x: x.get("event_ts") or "", reverse=True)
    results = results[:limit]

    # Extract unique values for facets
    channels_found = list(set(r.get("channel") for r in results if r.get("channel")))
    doc_types_found = list(set(r.get("doc_type") for r in results if r.get("doc_type")))

    # Date range
    if results:
        timestamps = [r.get("event_ts") for r in results if r.get("event_ts")]
        date_range = {
            "earliest": min(timestamps) if timestamps else None,
            "latest": max(timestamps) if timestamps else None
        }
    else:
        date_range = {"earliest": None, "latest": None}

    return {
        "count": len(results),
        "query_mode": "search" if query else "scroll",
        "filters": {
            "namespace": namespace,
            "channel": channel,
            "doc_type": doc_type,
            "days": days
        },
        "facets": {
            "channels": channels_found,
            "doc_types": doc_types_found,
            "date_range": date_range,
        },
        "results": results
    }


@router.post("")
def post_timeline(req: TimelineRequest):
    """POST version of timeline endpoint for complex queries"""
    return get_timeline(
        namespace=req.namespace,
        collection_suffix=req.collection_suffix,
        query=req.query,
        channel=req.channel,
        doc_type=req.doc_type,
        person=req.person,
        days=req.days,
        limit=req.limit,
        min_score=req.min_score
    )


# =============================================================================
# SPECIALIZED TIMELINE VIEWS
# =============================================================================

@router.get("/person/{person_id}")
def get_person_timeline(
    person_id: str,
    days: int = 90,
    limit: int = 50,
    include_messages: bool = True
):
    """
    Get timeline of events related to a person.

    Returns chronological list of:
    - Profile version changes
    - Knowledge items about the person
    - Message mentions (from Qdrant)
    - Decision references
    """
    from .. import knowledge_db, session_manager
    from ..hybrid_search import hybrid_search

    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    events = []

    # 1. Profile version history
    try:
        with knowledge_db.get_conn() as conn:
            cur = conn.cursor()

            # Get profile versions
            cur.execute("""
                SELECT pv.version_number, pv.content, pv.changed_by, pv.change_reason,
                       pv.change_type, pv.status, pv.created_at
                FROM person_profile_version pv
                JOIN person_profile p ON p.id = pv.profile_id
                WHERE p.person_id = %s AND pv.created_at > %s
                ORDER BY pv.created_at DESC
                LIMIT %s
            """, (person_id, cutoff, limit))

            for row in cur.fetchall():
                events.append({
                    "type": "profile_change",
                    "timestamp": row["created_at"].isoformat() if row["created_at"] else None,
                    "version": row["version_number"],
                    "change_type": row["change_type"],
                    "changed_by": row["changed_by"],
                    "reason": row["change_reason"],
                    "status": row["status"],
                    "content_preview": str(row["content"])[:200] if row["content"] else None
                })

            # 2. Knowledge items about this person
            cur.execute("""
                SELECT ki.id, ki.item_type, ki.status, ki.relevance_score,
                       kiv.content, kiv.confidence, kiv.created_at, kiv.created_by
                FROM knowledge_item ki
                JOIN knowledge_item_version kiv ON kiv.id = ki.current_version_id
                WHERE ki.subject_type = 'person' AND ki.subject_id = %s
                  AND kiv.created_at > %s
                ORDER BY kiv.created_at DESC
                LIMIT %s
            """, (person_id, cutoff, limit))

            for row in cur.fetchall():
                events.append({
                    "type": "knowledge_update",
                    "timestamp": row["created_at"].isoformat() if row["created_at"] else None,
                    "item_id": row["id"],
                    "item_type": row["item_type"],
                    "confidence": row["confidence"],
                    "created_by": row["created_by"],
                    "relevance": row["relevance_score"],
                    "content_preview": str(row["content"])[:200] if row["content"] else None
                })

            # 3. Decision references
            cur.execute("""
                SELECT id, title, decision_type, outcome, created_at
                FROM decision_log
                WHERE context::text ILIKE %s AND created_at > %s
                ORDER BY created_at DESC
                LIMIT %s
            """, (f'%{person_id}%', cutoff, limit // 2))

            for row in cur.fetchall():
                events.append({
                    "type": "decision",
                    "timestamp": row["created_at"].isoformat() if row["created_at"] else None,
                    "decision_id": row["id"],
                    "title": row["title"],
                    "decision_type": row["decision_type"],
                    "outcome": row["outcome"]
                })

    except Exception as e:
        log_with_context(logger, "error", "Timeline person DB error", error=str(e))

    # 4. Message mentions from Qdrant (if requested)
    if include_messages:
        try:
            # Search for messages mentioning this person
            search_results = hybrid_search(
                query=person_id.replace("_", " "),
                namespace="private",
                limit=limit // 2,
                score_threshold=0.3
            )
            for result in search_results.get("results", []):
                events.append({
                    "type": "message_mention",
                    "timestamp": result.get("event_ts_start") or result.get("event_ts"),
                    "channel": result.get("channel"),
                    "text_preview": result.get("text", "")[:150],
                    "score": result.get("score")
                })
        except Exception as e:
            log_with_context(logger, "warning", "Timeline person search error", error=str(e))

    # Sort by timestamp (newest first)
    events.sort(key=lambda x: x.get("timestamp") or "", reverse=True)

    return {
        "person_id": person_id,
        "days": days,
        "event_count": len(events),
        "events": events[:limit]
    }


@router.get("/topic/{topic}")
def get_topic_timeline(
    topic: str,
    days: int = 90,
    limit: int = 50,
    include_messages: bool = True,
    namespace: str = None
):
    """
    Get timeline of events related to a topic.

    Returns chronological list of:
    - Topic mentions from sessions
    - Knowledge items tagged with topic
    - Message mentions (from Qdrant)
    """
    from .. import session_manager
    from ..hybrid_search import hybrid_search

    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    events = []
    topic_lower = topic.lower()

    # 1. Topic mentions from session_manager (SQLite)
    try:
        conn = session_manager._get_conn()
        cursor = conn.execute("""
            SELECT session_id, user_id, mention_count, first_mentioned, last_mentioned, context_snippet
            FROM topic_mentions
            WHERE LOWER(topic) = ? AND last_mentioned > ?
            ORDER BY last_mentioned DESC
            LIMIT ?
        """, (topic_lower, cutoff, limit))

        for row in cursor.fetchall():
            events.append({
                "type": "topic_mention",
                "timestamp": row["last_mentioned"],
                "session_id": row["session_id"],
                "mention_count": row["mention_count"],
                "first_seen": row["first_mentioned"],
                "context": row["context_snippet"]
            })
        conn.close()
    except Exception as e:
        log_with_context(logger, "warning", "Timeline topic mentions error", error=str(e))

    # 2. Knowledge items mentioning this topic
    try:
        from .. import knowledge_db
        with knowledge_db.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT ki.id, ki.item_type, ki.subject_type, ki.subject_id,
                       kiv.content, kiv.confidence, kiv.created_at
                FROM knowledge_item ki
                JOIN knowledge_item_version kiv ON kiv.id = ki.current_version_id
                WHERE kiv.content::text ILIKE %s
                  AND kiv.created_at > %s
                  AND ki.status = 'active'
                ORDER BY kiv.created_at DESC
                LIMIT %s
            """, (f'%{topic}%', cutoff, limit))

            for row in cur.fetchall():
                events.append({
                    "type": "knowledge_item",
                    "timestamp": row["created_at"].isoformat() if row["created_at"] else None,
                    "item_id": row["id"],
                    "item_type": row["item_type"],
                    "subject": f"{row['subject_type']}:{row['subject_id']}" if row["subject_id"] else None,
                    "confidence": row["confidence"],
                    "content_preview": str(row["content"])[:200] if row["content"] else None
                })
    except Exception as e:
        log_with_context(logger, "warning", "Timeline topic knowledge error", error=str(e))

    # 3. Message mentions from Qdrant
    if include_messages:
        try:
            ns = namespace or "private"
            search_results = hybrid_search(
                query=topic,
                namespace=ns,
                limit=limit // 2,
                score_threshold=0.3
            )
            for result in search_results.get("results", []):
                events.append({
                    "type": "message",
                    "timestamp": result.get("event_ts_start") or result.get("event_ts"),
                    "channel": result.get("channel"),
                    "namespace": ns,
                    "text_preview": result.get("text", "")[:150],
                    "score": result.get("score")
                })
        except Exception as e:
            log_with_context(logger, "warning", "Timeline topic search error", error=str(e))

    # Sort by timestamp
    events.sort(key=lambda x: x.get("timestamp") or "", reverse=True)

    return {
        "topic": topic,
        "days": days,
        "event_count": len(events),
        "events": events[:limit]
    }


@router.get("/project/{project_id}")
def get_project_timeline(
    project_id: str,
    days: int = 90,
    limit: int = 50,
    include_messages: bool = True
):
    """
    Get timeline of events related to a project.

    Returns chronological list of:
    - Task updates
    - Knowledge items about the project
    - Decision references
    - Message mentions
    """
    from .. import knowledge_db
    from ..hybrid_search import hybrid_search

    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    events = []

    try:
        with knowledge_db.get_conn() as conn:
            cur = conn.cursor()

            # 1. Tasks for this project
            cur.execute("""
                SELECT t.id, t.title, t.status, t.priority, t.created_at, t.updated_at,
                       t.completed_at
                FROM tasks t
                JOIN projects p ON p.id = t.project_id
                WHERE p.project_id = %s AND t.updated_at > %s
                ORDER BY t.updated_at DESC
                LIMIT %s
            """, (project_id, cutoff, limit))

            for row in cur.fetchall():
                events.append({
                    "type": "task",
                    "timestamp": (row["updated_at"] or row["created_at"]).isoformat() if row["updated_at"] or row["created_at"] else None,
                    "task_id": row["id"],
                    "title": row["title"],
                    "status": row["status"],
                    "priority": row["priority"],
                    "completed": row["completed_at"].isoformat() if row["completed_at"] else None
                })

            # 2. Knowledge items about project
            cur.execute("""
                SELECT ki.id, ki.item_type, kiv.content, kiv.confidence, kiv.created_at
                FROM knowledge_item ki
                JOIN knowledge_item_version kiv ON kiv.id = ki.current_version_id
                WHERE ki.subject_type = 'project' AND ki.subject_id = %s
                  AND kiv.created_at > %s
                ORDER BY kiv.created_at DESC
                LIMIT %s
            """, (project_id, cutoff, limit // 2))

            for row in cur.fetchall():
                events.append({
                    "type": "knowledge",
                    "timestamp": row["created_at"].isoformat() if row["created_at"] else None,
                    "item_id": row["id"],
                    "item_type": row["item_type"],
                    "confidence": row["confidence"],
                    "content_preview": str(row["content"])[:200] if row["content"] else None
                })

            # 3. Decisions referencing project
            cur.execute("""
                SELECT id, title, decision_type, outcome, created_at
                FROM decision_log
                WHERE context::text ILIKE %s AND created_at > %s
                ORDER BY created_at DESC
                LIMIT %s
            """, (f'%{project_id}%', cutoff, limit // 2))

            for row in cur.fetchall():
                events.append({
                    "type": "decision",
                    "timestamp": row["created_at"].isoformat() if row["created_at"] else None,
                    "decision_id": row["id"],
                    "title": row["title"],
                    "decision_type": row["decision_type"],
                    "outcome": row["outcome"]
                })

    except Exception as e:
        log_with_context(logger, "error", "Timeline project DB error", error=str(e))

    # 4. Messages mentioning project
    if include_messages:
        try:
            search_results = hybrid_search(
                query=project_id.replace("_", " "),
                namespace="work_projektil",
                limit=limit // 2,
                score_threshold=0.3
            )
            for result in search_results.get("results", []):
                events.append({
                    "type": "message",
                    "timestamp": result.get("event_ts_start") or result.get("event_ts"),
                    "channel": result.get("channel"),
                    "text_preview": result.get("text", "")[:150],
                    "score": result.get("score")
                })
        except Exception as e:
            log_with_context(logger, "warning", "Timeline project search error", error=str(e))

    events.sort(key=lambda x: x.get("timestamp") or "", reverse=True)

    return {
        "project_id": project_id,
        "days": days,
        "event_count": len(events),
        "events": events[:limit]
    }


@router.get("/overview")
def get_timeline_overview(days: int = 30, limit: int = 100):
    """
    Get a unified timeline overview of all recent activity.

    Aggregates recent events across all entity types for a global view.
    """
    from .. import knowledge_db

    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    events = []

    try:
        with knowledge_db.get_conn() as conn:
            cur = conn.cursor()

            # Recent knowledge updates
            cur.execute("""
                SELECT ki.id, ki.item_type, ki.subject_type, ki.subject_id,
                       kiv.created_at, kiv.created_by, kiv.confidence
                FROM knowledge_item ki
                JOIN knowledge_item_version kiv ON kiv.id = ki.current_version_id
                WHERE kiv.created_at > %s AND ki.status = 'active'
                ORDER BY kiv.created_at DESC
                LIMIT %s
            """, (cutoff, limit // 3))

            for row in cur.fetchall():
                events.append({
                    "type": "knowledge",
                    "timestamp": row["created_at"].isoformat() if row["created_at"] else None,
                    "item_type": row["item_type"],
                    "subject": f"{row['subject_type']}:{row['subject_id']}" if row["subject_id"] else None,
                    "created_by": row["created_by"]
                })

            # Recent profile changes
            cur.execute("""
                SELECT p.person_id, p.name, pv.version_number, pv.change_type,
                       pv.changed_by, pv.created_at
                FROM person_profile_version pv
                JOIN person_profile p ON p.id = pv.profile_id
                WHERE pv.created_at > %s
                ORDER BY pv.created_at DESC
                LIMIT %s
            """, (cutoff, limit // 3))

            for row in cur.fetchall():
                events.append({
                    "type": "profile",
                    "timestamp": row["created_at"].isoformat() if row["created_at"] else None,
                    "person_id": row["person_id"],
                    "name": row["name"],
                    "change_type": row["change_type"],
                    "changed_by": row["changed_by"]
                })

            # Recent decisions
            cur.execute("""
                SELECT id, title, decision_type, outcome, created_at
                FROM decision_log
                WHERE created_at > %s
                ORDER BY created_at DESC
                LIMIT %s
            """, (cutoff, limit // 3))

            for row in cur.fetchall():
                events.append({
                    "type": "decision",
                    "timestamp": row["created_at"].isoformat() if row["created_at"] else None,
                    "decision_id": row["id"],
                    "title": row["title"],
                    "outcome": row["outcome"]
                })

    except Exception as e:
        log_with_context(logger, "error", "Timeline overview error", error=str(e))

    events.sort(key=lambda x: x.get("timestamp") or "", reverse=True)

    return {
        "days": days,
        "event_count": len(events),
        "events": events[:limit]
    }
