"""
Jarvis Session Manager
Handles conversation context persistence across sessions.
Enables Jarvis to remember what was discussed and follow up intelligently.
"""
import json
import sqlite3
import os
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field, asdict
import hashlib

from .observability import get_logger, log_with_context

logger = get_logger("jarvis.session")

DB_PATH = os.environ.get("JARVIS_STATE_DB", "/brain/system/state/jarvis_state.db")


def _get_conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@dataclass
class ConversationContext:
    """Represents the context of a conversation session"""
    session_id: str
    user_id: int
    start_time: str
    end_time: Optional[str] = None
    conversation_summary: str = ""
    key_topics: List[str] = field(default_factory=list)
    pending_actions: List[str] = field(default_factory=list)
    emotional_indicators: Dict[str, Any] = field(default_factory=dict)
    relationship_updates: Dict[str, Any] = field(default_factory=dict)
    namespace: str = "work_projektil"
    message_count: int = 0
    # --- Best Practice Additions ---
    entity_mentions: List[str] = field(default_factory=list)
    timeline_anchors: List[str] = field(default_factory=list)
    document_references: List[str] = field(default_factory=list)
    previous_session_id: Optional[str] = None
    related_sessions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConversationContext":
        return cls(**data)


def init_context_tables():
    """Initialize conversation context tables"""
    conn = _get_conn()

    # Conversation contexts - stores session summaries
    conn.execute("""
        CREATE TABLE IF NOT EXISTS conversation_contexts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            user_id INTEGER,
            namespace TEXT DEFAULT 'work_projektil',
            start_time TEXT NOT NULL,
            end_time TEXT,
            conversation_summary TEXT,
            key_topics TEXT,
            pending_actions TEXT,
            emotional_indicators TEXT,
            relationship_updates TEXT,
            message_count INTEGER DEFAULT 0,
            entity_mentions TEXT,
            timeline_anchors TEXT,
            document_references TEXT,
            previous_session_id TEXT,
            related_sessions TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(session_id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_context_user ON conversation_contexts(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_context_start ON conversation_contexts(start_time DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_context_namespace ON conversation_contexts(namespace)")

    # Pending actions tracking - for follow-ups
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pending_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            user_id INTEGER,
            action_text TEXT NOT NULL,
            context TEXT,
            created_at TEXT NOT NULL,
            due_date TEXT,
            completed_at TEXT,
            completed INTEGER DEFAULT 0,
            priority TEXT DEFAULT 'normal',
            FOREIGN KEY (session_id) REFERENCES conversation_contexts(session_id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pending_user ON pending_actions(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pending_completed ON pending_actions(completed)")

    # Topic tracking - for continuity
    conn.execute("""
        CREATE TABLE IF NOT EXISTS topic_mentions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            user_id INTEGER,
            topic TEXT NOT NULL,
            mention_count INTEGER DEFAULT 1,
            first_mentioned TEXT NOT NULL,
            last_mentioned TEXT NOT NULL,
            context_snippet TEXT,
            FOREIGN KEY (session_id) REFERENCES conversation_contexts(session_id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_topic_user ON topic_mentions(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_topic_name ON topic_mentions(topic)")

    # Thread state tracking - for ADHD thread management
    conn.execute("""
        CREATE TABLE IF NOT EXISTS thread_state (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            topic TEXT NOT NULL,
            status TEXT DEFAULT 'open',  -- open, closed, paused
            opened_at TEXT NOT NULL,
            closed_at TEXT,
            paused_at TEXT,
            session_id TEXT,
            last_activity TEXT,
            priority TEXT DEFAULT 'normal',  -- low, normal, high
            notes TEXT,
            UNIQUE(user_id, topic)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_thread_user ON thread_state(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_thread_status ON thread_state(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_thread_activity ON thread_state(last_activity DESC)")

    conn.commit()
    conn.close()
    log_with_context(logger, "info", "Context tables initialized")



def save_conversation_context(context: ConversationContext) -> int:
    """
    Save conversation context at end of session.
    Returns the context ID.
    """
    now = datetime.now().isoformat(timespec="seconds")
    conn = _get_conn()

    cursor = conn.execute("""
        INSERT INTO conversation_contexts (
            session_id, user_id, namespace, start_time, end_time,
            conversation_summary, key_topics, pending_actions,
            emotional_indicators, relationship_updates, message_count,
            entity_mentions, timeline_anchors, document_references,
            previous_session_id, related_sessions, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(session_id) DO UPDATE SET
            end_time = excluded.end_time,
            conversation_summary = excluded.conversation_summary,
            key_topics = excluded.key_topics,
            pending_actions = excluded.pending_actions,
            emotional_indicators = excluded.emotional_indicators,
            relationship_updates = excluded.relationship_updates,
            message_count = excluded.message_count,
            entity_mentions = excluded.entity_mentions,
            timeline_anchors = excluded.timeline_anchors,
            document_references = excluded.document_references,
            previous_session_id = excluded.previous_session_id,
            related_sessions = excluded.related_sessions
    """, (
        context.session_id,
        context.user_id,
        context.namespace,
        context.start_time,
        context.end_time or now,
        context.conversation_summary,
        json.dumps(context.key_topics),
        json.dumps(context.pending_actions),
        json.dumps(context.emotional_indicators),
        json.dumps(context.relationship_updates),
        context.message_count,
        json.dumps(context.entity_mentions),
        json.dumps(context.timeline_anchors),
        json.dumps(context.document_references),
        context.previous_session_id,
        json.dumps(context.related_sessions),
        now
    ))

    context_id = cursor.lastrowid
    conn.commit()

    # Also save pending actions to separate table for easy tracking
    for action in context.pending_actions:
        conn.execute("""
            INSERT OR IGNORE INTO pending_actions (session_id, user_id, action_text, created_at)
            VALUES (?, ?, ?, ?)
        """, (context.session_id, context.user_id, action, now))

    # Track topics
    for topic in context.key_topics:
        _update_topic_mention(conn, context.session_id, context.user_id, topic, now)

    conn.commit()
    conn.close()

    log_with_context(logger, "info", "Conversation context saved",
                    session_id=context.session_id, topics=len(context.key_topics),
                    pending_actions=len(context.pending_actions))

    return context_id


def _update_topic_mention(conn, session_id: str, user_id: int, topic: str, timestamp: str):
    """Update or create topic mention record"""
    cursor = conn.execute("""
        SELECT id, mention_count FROM topic_mentions
        WHERE user_id = ? AND topic = ?
    """, (user_id, topic.lower()))
    existing = cursor.fetchone()

    if existing:
        conn.execute("""
            UPDATE topic_mentions
            SET mention_count = mention_count + 1, last_mentioned = ?, session_id = ?
            WHERE id = ?
        """, (timestamp, session_id, existing["id"]))
    else:
        conn.execute("""
            INSERT INTO topic_mentions (session_id, user_id, topic, first_mentioned, last_mentioned)
            VALUES (?, ?, ?, ?, ?)
        """, (session_id, user_id, topic.lower(), timestamp, timestamp))


def get_conversation_history(
    user_id: int = None,
    days_back: int = 7,
    topic_filter: str = None,
    namespace: str = None,
    limit: int = 10
) -> List[Dict[str, Any]]:
    """
    Retrieve relevant conversation contexts from previous sessions.

    Phase 19.2: Now prioritizes session_messages for recent activity,
    then enriches with conversation_contexts for summaries.

    Args:
        user_id: Filter by user
        days_back: How many days to look back
        topic_filter: Filter by specific topic
        namespace: Filter by namespace
        limit: Max results

    Returns:
        List of conversation context dicts with parsed JSON fields
    """
    conn = _get_conn()
    cutoff = (datetime.now() - timedelta(days=days_back)).isoformat()

    # Phase 19.2: First get recently ACTIVE sessions from session_messages
    # This catches sessions that were reused but have old start_time in conversation_contexts
    recent_session_ids = set()
    session_msg_data = {}
    try:
        sm_query = """
            SELECT session_id,
                   COUNT(*) as msg_count,
                   MIN(timestamp) as first_msg,
                   MAX(timestamp) as last_msg
            FROM session_messages
            WHERE timestamp > ?
        """
        sm_params = [cutoff]
        if user_id:
            sm_query += " AND user_id = ?"
            sm_params.append(user_id)
        sm_query += " GROUP BY session_id ORDER BY MAX(timestamp) DESC LIMIT ?"
        sm_params.append(limit * 2)  # Get more to allow merging

        cursor = conn.execute(sm_query, sm_params)
        for row in cursor.fetchall():
            sid = row[0]
            recent_session_ids.add(sid)
            session_msg_data[sid] = {
                "msg_count": row[1],
                "first_msg": row[2],
                "last_msg": row[3]
            }
    except Exception:
        pass  # session_messages table might not exist

    # Now query conversation_contexts - include sessions that are recently active
    # even if their start_time is old
    query = """
        SELECT * FROM conversation_contexts
        WHERE (start_time > ? OR session_id IN ({}))
    """.format(",".join(["?" for _ in recent_session_ids]) if recent_session_ids else "'__none__'")
    params = [cutoff] + list(recent_session_ids)

    if user_id:
        query += " AND user_id = ?"
        params.append(user_id)

    if namespace:
        query += " AND namespace = ?"
        params.append(namespace)

    if topic_filter:
        query += " AND key_topics LIKE ?"
        params.append(f"%{topic_filter.lower()}%")

    query += " ORDER BY start_time DESC LIMIT ?"
    params.append(limit)

    cursor = conn.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    results = []
    for row in rows:
        d = dict(row)
        # Parse JSON fields (extended for best practice fields)
        d["key_topics"] = json.loads(d.get("key_topics") or "[]")
        d["pending_actions"] = json.loads(d.get("pending_actions") or "[]")
        d["emotional_indicators"] = json.loads(d.get("emotional_indicators") or "{}")
        d["relationship_updates"] = json.loads(d.get("relationship_updates") or "{}")
        d["entity_mentions"] = json.loads(d.get("entity_mentions") or "[]")
        d["timeline_anchors"] = json.loads(d.get("timeline_anchors") or "[]")
        d["document_references"] = json.loads(d.get("document_references") or "[]")
        d["related_sessions"] = json.loads(d.get("related_sessions") or "[]")
        # previous_session_id bleibt String/None
        results.append(d)

    # Phase 19.1: Enrich with auto-persisted session_messages
    try:
        from .services.auto_session_persist import get_auto_session_persist
        persist = get_auto_session_persist()

        # Get recent messages from auto-persist (None = all users)
        recent_messages = persist.get_recent_messages(
            user_id=user_id,  # None is ok - will return all users
            limit=100,
            hours=days_back * 24
        )

        # Group messages by session_id
        session_msg_counts = {}
        session_msg_groups = {}
        for msg in recent_messages:
            sid = msg.get("session_id")
            if sid:
                session_msg_counts[sid] = session_msg_counts.get(sid, 0) + 1
                if sid not in session_msg_groups:
                    session_msg_groups[sid] = []
                session_msg_groups[sid].append(msg)

        # Update existing results with session_messages data
        sessions_seen = set()
        for r in results:
            sid = r.get("session_id")
            if sid and sid in session_msg_counts:
                # Update message_count from session_messages (more accurate)
                r["message_count"] = session_msg_counts[sid]
                r["source"] = "enriched"  # conversation_contexts + session_messages
                # Update timestamps if session_messages has newer data
                if sid in session_msg_groups:
                    msgs = session_msg_groups[sid]
                    if msgs:
                        # Use newest timestamp from session_messages
                        newest_ts = max(m.get("timestamp", "") for m in msgs)
                        oldest_ts = min(m.get("timestamp", "") for m in msgs)
                        # If session_messages is more recent, update timestamps
                        if newest_ts > (r.get("end_time") or ""):
                            r["end_time"] = newest_ts
                        if oldest_ts and (not r.get("start_time") or oldest_ts < r.get("start_time", "")):
                            r["start_time"] = oldest_ts
                sessions_seen.add(sid)
            elif sid:
                sessions_seen.add(sid)

        # Add new sessions that only exist in session_messages
        if len(results) < limit:
            for sid, messages in list(session_msg_groups.items())[:limit - len(results)]:
                if sid in sessions_seen or not messages:
                    continue
                # Build a summary from the messages
                user_msgs = [m["content"][:200] for m in messages if m.get("role") == "user"]
                summary = " | ".join(user_msgs[:3]) if user_msgs else "No summary"

                results.append({
                    "session_id": sid,
                    "start_time": messages[-1].get("timestamp", ""),
                    "end_time": messages[0].get("timestamp", ""),
                    "conversation_summary": f"[Auto-captured] {summary}",
                    "key_topics": [],
                    "pending_actions": [],
                    "emotional_indicators": {},
                    "relationship_updates": {},
                    "message_count": len(messages),
                    "source": "session_messages"
                })
    except Exception as e:
        # Don't fail if auto-persist isn't available
        pass

    return results


def get_pending_actions(
    user_id: int = None,
    include_completed: bool = False,
    limit: int = 20
) -> List[Dict[str, Any]]:
    """Get pending actions/tasks from past conversations"""
    conn = _get_conn()

    query = "SELECT * FROM pending_actions WHERE 1=1"
    params = []

    if user_id:
        query += " AND user_id = ?"
        params.append(user_id)

    if not include_completed:
        query += " AND completed = 0"

    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    cursor = conn.execute(query, params)
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()

    return rows


def complete_action(action_id: int) -> bool:
    """Mark a pending action as completed"""
    now = datetime.now().isoformat(timespec="seconds")
    conn = _get_conn()
    cursor = conn.execute("""
        UPDATE pending_actions
        SET completed = 1, completed_at = ?
        WHERE id = ?
    """, (now, action_id))
    conn.commit()
    affected = cursor.rowcount
    conn.close()
    return affected > 0


def get_recent_topics(
    user_id: int = None,
    days_back: int = 30,
    limit: int = 10
) -> List[Dict[str, Any]]:
    """Get frequently discussed topics"""
    conn = _get_conn()

    cutoff = (datetime.now() - timedelta(days=days_back)).isoformat()

    query = """
        SELECT topic, SUM(mention_count) as total_mentions,
               MAX(last_mentioned) as last_mentioned,
               MIN(first_mentioned) as first_mentioned
        FROM topic_mentions
        WHERE last_mentioned > ?
    """
    params = [cutoff]

    if user_id:
        query += " AND user_id = ?"
        params.append(user_id)

    query += " GROUP BY topic ORDER BY total_mentions DESC, last_mentioned DESC LIMIT ?"
    params.append(limit)

    cursor = conn.execute(query, params)
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()

    return rows


def extract_context_from_messages(
    messages: List[Dict[str, Any]],
    session_id: str,
    user_id: int = None,
    namespace: str = "work_projektil"
) -> ConversationContext:
    """
    Automatically extract conversation context from message history.

    Analyzes messages to extract:
    - Main topics discussed
    - Pending actions/follow-ups
    - Emotional indicators
    - Relationship updates

    Args:
        messages: List of message dicts with 'role' and 'content'
        session_id: Current session ID
        user_id: Telegram user ID
        namespace: Current namespace

    Returns:
        ConversationContext with extracted information
    """
    if not messages:
        return ConversationContext(
            session_id=session_id,
            user_id=user_id,
            start_time=datetime.now().isoformat(timespec="seconds"),
            namespace=namespace
        )

    # Extract basic info
    start_time = messages[0].get("timestamp", datetime.now().isoformat(timespec="seconds"))
    end_time = messages[-1].get("timestamp", datetime.now().isoformat(timespec="seconds"))
    message_count = len(messages)

    # Concatenate user messages for analysis
    user_messages = [m["content"] for m in messages if m.get("role") == "user"]
    assistant_messages = [m["content"] for m in messages if m.get("role") == "assistant"]

    all_text = " ".join(user_messages + assistant_messages).lower()

    # Extract topics (simple keyword extraction)
    topics = _extract_topics(all_text)

    # Extract pending actions (look for patterns)
    pending = _extract_pending_actions(user_messages, assistant_messages)

    # Extract emotional indicators
    emotional = _extract_emotional_indicators(user_messages)

    # Generate summary (simplified - in production would use LLM)
    summary = _generate_simple_summary(user_messages, topics)

    return ConversationContext(
        session_id=session_id,
        user_id=user_id,
        start_time=start_time,
        end_time=end_time,
        conversation_summary=summary,
        key_topics=topics,
        pending_actions=pending,
        emotional_indicators=emotional,
        relationship_updates={},
        namespace=namespace,
        message_count=message_count
    )


def _extract_topics(text: str) -> List[str]:
    """Extract key topics from text using simple heuristics"""
    # Common project/work terms to look for
    topic_patterns = [
        # Projects
        ("projekt", "project"),
        ("api", "API"),
        ("meeting", "meeting"),
        ("deadline", "deadline"),
        ("review", "review"),
        ("budget", "budget"),
        ("release", "release"),
        ("deployment", "deployment"),
        # People patterns (simplified)
        ("mit ", "collaboration"),  # "mit X besprochen"
        # Technical
        ("bug", "bugfix"),
        ("feature", "feature"),
        ("test", "testing"),
        # Personal
        ("termin", "appointment"),
        ("urlaub", "vacation"),
        ("krank", "sick"),
    ]

    topics = []
    for pattern, topic in topic_patterns:
        if pattern in text:
            if topic not in topics:
                topics.append(topic)

    # Also extract capitalized words that might be project/person names
    import re
    capitalized = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', text)
    for word in capitalized[:5]:  # Limit to prevent noise
        if len(word) > 2 and word.lower() not in ["ich", "sie", "wir", "der", "die", "das"]:
            if word not in topics:
                topics.append(word)

    return topics[:10]  # Limit topics


def _extract_pending_actions(user_msgs: List[str], assistant_msgs: List[str]) -> List[str]:
    """Extract pending actions from conversation"""
    pending = []

    # Patterns that indicate follow-up needed
    action_indicators = [
        "ich werde", "i will", "i'll",
        "ich muss", "i need to", "i have to",
        "muss noch", "need to",
        "checken", "check",
        "schauen", "look into",
        "erinnere mich", "remind me",
        "nicht vergessen", "don't forget",
        "todo", "to-do",
        "später", "later",
        "morgen", "tomorrow",
        "nächste woche", "next week",
    ]

    for msg in user_msgs:
        msg_lower = msg.lower()
        for indicator in action_indicators:
            if indicator in msg_lower:
                # Extract the sentence containing the indicator
                sentences = msg.split(".")
                for sentence in sentences:
                    if indicator in sentence.lower() and len(sentence) > 10:
                        action = sentence.strip()[:200]  # Limit length
                        if action and action not in pending:
                            pending.append(action)
                            break

    return pending[:5]  # Limit to 5 actions


def _extract_emotional_indicators(user_msgs: List[str]) -> Dict[str, Any]:
    """Extract emotional context from user messages"""
    all_text = " ".join(user_msgs).lower()

    indicators = {
        "urgency": 0,
        "stress": 0,
        "positive": 0,
        "negative": 0,
    }

    # Urgency indicators
    urgency_words = ["dringend", "urgent", "asap", "sofort", "schnell", "wichtig", "critical"]
    for word in urgency_words:
        if word in all_text:
            indicators["urgency"] += 1

    # Stress indicators
    stress_words = ["stress", "überlastet", "overwhelmed", "zu viel", "problem", "schwierig"]
    for word in stress_words:
        if word in all_text:
            indicators["stress"] += 1

    # Positive indicators
    positive_words = ["super", "toll", "great", "excellent", "happy", "freue", "gut"]
    for word in positive_words:
        if word in all_text:
            indicators["positive"] += 1

    # Negative indicators
    negative_words = ["schlecht", "bad", "frustrated", "ärger", "nervig", "annoying"]
    for word in negative_words:
        if word in all_text:
            indicators["negative"] += 1

    # Determine dominant mood
    max_indicator = max(indicators.items(), key=lambda x: x[1])
    if max_indicator[1] > 0:
        indicators["dominant"] = max_indicator[0]
    else:
        indicators["dominant"] = "neutral"

    return indicators


def _generate_simple_summary(user_msgs: List[str], topics: List[str]) -> str:
    """Generate a simple conversation summary"""
    if not user_msgs:
        return "No conversation recorded."

    # Take first and last user message as context
    first_msg = user_msgs[0][:100] if user_msgs else ""
    last_msg = user_msgs[-1][:100] if len(user_msgs) > 1 else ""

    topic_str = ", ".join(topics[:3]) if topics else "general discussion"

    summary = f"Conversation about {topic_str}."
    if first_msg:
        summary += f" Started with: '{first_msg}...'"
    if last_msg and last_msg != first_msg:
        summary += f" Ended with: '{last_msg}...'"

    return summary[:500]  # Limit summary length


def build_context_prompt(
    user_id: int,
    current_query: str,
    days_back: int = 7,
    include_pending: bool = True
) -> str:
    """
    Build a context prompt to prepend to agent system prompt.
    Includes relevant past conversations and pending actions.

    Returns a formatted string with context information.
    """
    sections = []

    # Get recent conversations
    recent = get_conversation_history(user_id=user_id, days_back=days_back, limit=5)

    if recent:
        sections.append("=== RECENT CONVERSATIONS ===")
        for ctx in recent[:3]:
            # Use end_time (most recent activity) for display, fall back to start_time
            display_date = ctx.get("end_time") or ctx.get("start_time") or ""
            date_str = display_date[:10] if display_date else "unknown"
            topics = ", ".join(ctx.get("key_topics", [])[:3])
            summary = ctx.get("conversation_summary", "")[:200]
            msg_count = ctx.get("message_count", 0)
            sections.append(f"[{date_str}] ({msg_count} msgs) Topics: {topics}")
            if summary:
                sections.append(f"  Summary: {summary}")

    # Add recent message snippets for immediate context (Phase 19.3)
    try:
        from .services.auto_session_persist import get_auto_session_persist
        persist = get_auto_session_persist()
        recent_msgs = persist.get_recent_messages(user_id=user_id, limit=6, hours=24)
        if recent_msgs:
            sections.append("\n=== LETZTE NACHRICHTEN (24h) ===")
            for msg in recent_msgs[:6]:
                role = "User" if msg.get("role") == "user" else "Jarvis"
                content = msg.get("content", "")[:100]
                ts = msg.get("timestamp", "")[:16]
                sections.append(f"[{ts}] {role}: {content}...")
    except Exception:
        pass  # Fallback gracefully if auto_session_persist not available

    # Get pending actions
    if include_pending:
        pending = get_pending_actions(user_id=user_id, limit=5)
        if pending:
            sections.append("\n=== PENDING FOLLOW-UPS ===")
            for action in pending:
                date_str = action["created_at"][:10] if action.get("created_at") else ""
                sections.append(f"- [{date_str}] {action['action_text'][:100]}")

    # Get frequent topics
    topics = get_recent_topics(user_id=user_id, days_back=30, limit=5)
    if topics:
        sections.append("\n=== FREQUENT TOPICS ===")
        topic_list = [f"{t['topic']} ({t['total_mentions']}x)" for t in topics]
        sections.append(", ".join(topic_list))

    if sections:
        return "\n".join(sections)

    return ""


# ============ Thread State Management ============
# Phase 12.2: Consolidated into PostgreSQL active_context_buffer
# These functions maintain backward compatibility while using postgres_state.py

from . import postgres_state

def _priority_text_to_int(priority: str) -> int:
    """Convert text priority to integer (1-5)"""
    return {"low": 1, "normal": 3, "high": 5}.get(priority, 3)

def _priority_int_to_text(priority: int) -> str:
    """Convert integer priority to text"""
    if priority <= 1:
        return "low"
    elif priority >= 5:
        return "high"
    return "normal"

def _status_to_postgres(status: str) -> str:
    """Convert SQLite status to PostgreSQL status"""
    return {"open": "active", "closed": "completed", "paused": "paused"}.get(status, status)

def _status_from_postgres(status: str) -> str:
    """Convert PostgreSQL status to SQLite-compatible status"""
    return {"active": "open", "completed": "closed", "paused": "paused", "evicted": "closed"}.get(status, status)

def _make_thread_id(user_id: int, topic: str) -> str:
    """Create composite thread ID from user_id and topic"""
    return f"user_{user_id}_{topic.lower().replace(' ', '_')}"


def open_thread(
    user_id: int,
    topic: str,
    session_id: str = None,
    priority: str = "normal"
) -> Dict[str, Any]:
    """
    Open a new thread or reopen a closed/paused one.
    Phase 12.2: Now uses PostgreSQL active_context_buffer.

    Args:
        user_id: Telegram user ID
        topic: Topic name (normalized)
        session_id: Current session ID
        priority: low, normal, high

    Returns:
        Thread state dict
    """
    thread_id = _make_thread_id(user_id, topic)
    priority_int = _priority_text_to_int(priority)

    # Check if thread already exists
    existing = postgres_state.get_buffer_thread(thread_id)

    if existing and existing.get("status") in ("active", "paused", "evicted"):
        # Resume existing thread
        result = postgres_state.resume_context_thread(thread_id, priority=priority_int)
        action = "reopened"
    else:
        # Create new thread
        result = postgres_state.add_context_thread(
            thread_id=thread_id,
            title=topic,
            state_id=f"user_{user_id}",
            context_summary=f"Session: {session_id}" if session_id else None,
            priority=priority_int,
            thread_type="conversation",
            metadata={"user_id": user_id, "session_id": session_id}
        )
        action = "opened"

    log_with_context(logger, "info", f"Thread {action}", user_id=user_id, topic=topic)

    return {"topic": topic, "status": "open", "action": action}


def close_thread(
    user_id: int,
    topic: str,
    notes: str = None
) -> Dict[str, Any]:
    """
    Close a thread (mark as completed).
    Phase 12.2: Now uses PostgreSQL active_context_buffer.

    Args:
        user_id: Telegram user ID
        topic: Topic name
        notes: Optional closing notes

    Returns:
        Result dict
    """
    thread_id = _make_thread_id(user_id, topic)
    result = postgres_state.complete_context_thread(thread_id, completion_note=notes)

    if result:
        log_with_context(logger, "info", "Thread closed", user_id=user_id, topic=topic)
        return {"topic": topic, "status": "closed", "success": True}
    else:
        return {"topic": topic, "status": "not_found", "success": False}


def pause_thread(
    user_id: int,
    topic: str
) -> Dict[str, Any]:
    """
    Pause a thread (temporarily set aside).
    Phase 12.2: Now uses PostgreSQL active_context_buffer.

    Args:
        user_id: Telegram user ID
        topic: Topic name

    Returns:
        Result dict
    """
    thread_id = _make_thread_id(user_id, topic)
    result = postgres_state.pause_context_thread(thread_id, reason="User paused")

    if result:
        log_with_context(logger, "info", "Thread paused", user_id=user_id, topic=topic)
        return {"topic": topic, "status": "paused", "success": True}
    else:
        return {"topic": topic, "status": "not_found", "success": False}


def get_thread_states(
    user_id: int,
    status: str = None,
    include_closed: bool = False
) -> List[Dict[str, Any]]:
    """
    Get all threads for a user with their states.
    Phase 12.2: Now uses PostgreSQL active_context_buffer.

    Args:
        user_id: Telegram user ID
        status: Filter by status (open, paused, closed) or None for all
        include_closed: Include closed threads (default: False)

    Returns:
        List of thread state dicts (with SQLite-compatible field names)
    """
    state_id = f"user_{user_id}"

    # Map status filter to PostgreSQL
    pg_status = _status_to_postgres(status) if status else None

    with postgres_state.get_cursor() as cur:
        query = """
            SELECT id, title, priority, status, context_summary,
                   added_at, last_touched_at, completed_at, metadata
            FROM active_context_buffer
            WHERE state_id = %s
        """
        params = [state_id]

        if pg_status:
            query += " AND status = %s"
            params.append(pg_status)
        elif not include_closed:
            query += " AND status NOT IN ('completed', 'evicted')"

        query += " ORDER BY last_touched_at DESC"

        cur.execute(query, params)
        rows = cur.fetchall()

    # Convert to SQLite-compatible format
    threads = []
    for row in rows:
        threads.append({
            "id": row["id"],
            "user_id": user_id,
            "topic": row["title"],
            "status": _status_from_postgres(row["status"]),
            "opened_at": str(row["added_at"]) if row["added_at"] else None,
            "closed_at": str(row["completed_at"]) if row["completed_at"] else None,
            "last_activity": str(row["last_touched_at"]) if row["last_touched_at"] else None,
            "priority": _priority_int_to_text(row["priority"] or 3),
            "notes": row["context_summary"]
        })

    return threads


def update_thread_activity(
    user_id: int,
    topic: str
) -> bool:
    """
    Update last_activity timestamp for a thread.
    Phase 12.2: Now uses PostgreSQL active_context_buffer.
    Called when user mentions an existing topic.

    Args:
        user_id: Telegram user ID
        topic: Topic name

    Returns:
        True if thread was updated, False if not found
    """
    thread_id = _make_thread_id(user_id, topic)
    result = postgres_state.touch_context_thread(thread_id)
    return result is not None


def sync_threads_from_topics(
    user_id: int,
    current_topics: List[str],
    session_id: str = None
) -> Dict[str, Any]:
    """
    Synchronize thread states with detected topics from a message.
    Phase 12.2: Now uses PostgreSQL active_context_buffer.

    - Opens new threads for new topics
    - Updates activity for existing topics
    - Does NOT auto-close threads (user must explicitly close)

    Args:
        user_id: Telegram user ID
        current_topics: List of topics detected in current message
        session_id: Current session ID

    Returns:
        Sync result with opened/updated counts
    """
    opened = []
    updated = []

    for topic in current_topics:
        # Normalize topic (lowercase, trim)
        topic = topic.lower().strip()
        if not topic or len(topic) < 2:
            continue

        thread_id = _make_thread_id(user_id, topic)

        # Check if thread exists
        existing = postgres_state.get_buffer_thread(thread_id)

        if existing:
            if existing["status"] == "active":
                # Update activity
                postgres_state.touch_context_thread(thread_id)
                updated.append(topic)
            else:
                # Reopen closed/paused/evicted thread
                open_thread(user_id, topic, session_id)
                opened.append(topic)
        else:
            # New thread
            open_thread(user_id, topic, session_id)
            opened.append(topic)

    return {
        "opened": opened,
        "updated": updated,
        "total_synced": len(opened) + len(updated)
    }


def get_active_threads(
    user_id: int,
    days_back: int = 7,
    min_mentions: int = 2
) -> List[str]:
    """
    Get currently active conversation threads for a user.
    Phase 12.2: Now uses PostgreSQL active_context_buffer.

    Primary: Uses active_context_buffer (active threads)
    Fallback: Uses topic_mentions if no active threads

    Args:
        user_id: Telegram user ID
        days_back: How far back to look for active threads (fallback only)
        min_mentions: Minimum mentions to count as active (fallback only)

    Returns:
        List of active topic names
    """
    state_id = f"user_{user_id}"

    # Primary: Get from active_context_buffer (active threads)
    with postgres_state.get_cursor() as cur:
        cur.execute("""
            SELECT title FROM active_context_buffer
            WHERE state_id = %s AND status = 'active'
            ORDER BY last_touched_at DESC
            LIMIT 10
        """, (state_id,))
        topics = [row["title"] for row in cur.fetchall()]

    # Fallback: If no active threads, use SQLite topic_mentions
    if not topics:
        conn = _get_conn()
        cutoff = (datetime.now() - timedelta(days=days_back)).isoformat()
        cursor = conn.execute("""
            SELECT topic, SUM(mention_count) as total
            FROM topic_mentions
            WHERE user_id = ?
              AND last_mentioned > ?
            GROUP BY topic
            HAVING total >= ?
            ORDER BY last_mentioned DESC
            LIMIT 10
        """, (user_id, cutoff, min_mentions))

        topics = [row["topic"] for row in cursor.fetchall()]
        conn.close()

    return topics


def check_thread_limit(
    user_id: int,
    max_threads: int = 3,
    days_back: int = 7
) -> Dict[str, Any]:
    """
    Check if user has exceeded their max parallel threads limit.
    Phase 12.2: Now uses PostgreSQL active_context_buffer.

    Args:
        user_id: Telegram user ID
        max_threads: Maximum allowed parallel threads (from person profile)
        days_back: How far back to look for active threads

    Returns:
        Dict with:
        - exceeded: bool - whether limit is exceeded
        - active_count: int - number of active (open) threads
        - paused_count: int - number of paused threads
        - max_threads: int - the limit
        - active_topics: list - names of active topics
        - paused_topics: list - names of paused topics
    """
    state_id = f"user_{user_id}"

    # Get from PostgreSQL active_context_buffer
    with postgres_state.get_cursor() as cur:
        # Active threads
        cur.execute("""
            SELECT title FROM active_context_buffer
            WHERE state_id = %s AND status = 'active'
            ORDER BY priority DESC, last_touched_at DESC
        """, (state_id,))
        active_topics = [row["title"] for row in cur.fetchall()]

        # Paused threads
        cur.execute("""
            SELECT title FROM active_context_buffer
            WHERE state_id = %s AND status = 'paused'
            ORDER BY priority DESC, last_touched_at DESC
        """, (state_id,))
        paused_topics = [row["title"] for row in cur.fetchall()]

    # Fallback if no active_context_buffer entries
    if not active_topics and not paused_topics:
        active_topics = get_active_threads(user_id, days_back=days_back, min_mentions=2)

    return {
        "exceeded": len(active_topics) >= max_threads,
        "active_count": len(active_topics),
        "paused_count": len(paused_topics),
        "max_threads": max_threads,
        "active_topics": active_topics[:max_threads + 2],
        "paused_topics": paused_topics[:3]
    }


def build_thread_enforcement_prompt(
    user_id: int,
    person_profile: Dict = None
) -> str:
    """
    Build a prompt section for thread enforcement if limit is exceeded.

    Checks the user's max_parallel_threads setting from their person profile
    and compares against active threads. Returns a warning prompt if exceeded.

    Args:
        user_id: Telegram user ID
        person_profile: Optional pre-loaded person profile with work_prefs

    Returns:
        Warning prompt string, or empty string if within limits
    """
    # Get max_threads from profile (default: 3)
    max_threads = 3
    if person_profile:
        work_prefs = person_profile.get("work_prefs", {})
        max_threads = work_prefs.get("max_parallel_threads", 3)

    # Check current thread status
    status = check_thread_limit(user_id, max_threads=max_threads)

    if not status["exceeded"]:
        return ""

    # Build warning prompt
    topics_str = ", ".join(status["active_topics"][:3])

    prompt_lines = [
        "=== THREAD-LIMIT WARNUNG ===",
        f"Nutzer hat aktuell {status['active_count']} aktive Themen (Max: {status['max_threads']}):",
        topics_str,
        ""
    ]

    # Add paused threads info if any
    if status.get("paused_topics"):
        paused_str = ", ".join(status["paused_topics"])
        prompt_lines.append(f"Pausierte Themen: {paused_str}")
        prompt_lines.append("")

    prompt_lines.extend([
        "ADHD-Schutz: Bevor du ein neues Thema anfaengst, frage:",
        f'"Du hast gerade {status["active_count"]} offene Themen. Willst du eins abschliessen oder pausieren?"',
        "",
        "Optionen anbieten:",
        "- [Aktuelles Thema fortsetzen]",
        "- [Thema X abschliessen] → schliesse Thread",
        "- [Thema X pausieren] → setze Thread auf Pause"
    ])

    if status.get("paused_topics"):
        prompt_lines.append(f"- [Pausiertes Thema wieder aufnehmen: {status['paused_topics'][0]}]")

    prompt_lines.append("\nNicht blockieren - nur Awareness schaffen.")

    return "\n".join(prompt_lines)


def get_message_frequency(
    user_id: int,
    minutes_back: int = 60
) -> Dict[str, Any]:
    """
    Get message frequency statistics for a user.

    Args:
        user_id: Telegram user ID
        minutes_back: How far back to look (default: 60 minutes)

    Returns:
        Dict with:
        - count: number of messages in timeframe
        - per_hour: messages per hour rate
        - avg_length: average message length
    """
    conn = _get_conn()
    cutoff = (datetime.now() - timedelta(minutes=minutes_back)).isoformat()

    # Count messages from conversation_contexts
    cursor = conn.execute("""
        SELECT COUNT(*) as count,
               SUM(message_count) as total_messages
        FROM conversation_contexts
        WHERE user_id = ?
          AND start_time > ?
    """, (user_id, cutoff))

    row = cursor.fetchone()
    conn.close()

    total_messages = row["total_messages"] or 0

    # Calculate per-hour rate
    per_hour = (total_messages / minutes_back) * 60 if minutes_back > 0 else 0

    return {
        "count": total_messages,
        "per_hour": round(per_hour, 1),
        "minutes_checked": minutes_back
    }


def check_overwhelm_state(
    user_id: int,
    stress_score: float = 0.0,
    frustration_score: float = 0.0,
    messages_per_hour_threshold: float = 5.0
) -> Dict[str, Any]:
    """
    Check if user is in an overwhelmed state.

    Combines:
    - Stress/frustration from sentiment analysis
    - Message frequency (high rate = possible overwhelm)
    - Active thread count

    Args:
        user_id: Telegram user ID
        stress_score: Current stress score (0-1) from sentiment
        frustration_score: Current frustration score (0-1) from sentiment
        messages_per_hour_threshold: Threshold for "high" message rate

    Returns:
        Dict with:
        - overwhelmed: bool - overall overwhelm state
        - level: str - none, mild, severe
        - factors: list - what contributed to the assessment
        - recommendation: str - suggested action
    """
    factors = []
    score = 0

    # Factor 1: Stress keywords (weight: 2)
    if stress_score >= 0.7:
        factors.append("hoher Stress erkannt")
        score += 2
    elif stress_score >= 0.4:
        factors.append("mittlerer Stress")
        score += 1

    # Factor 2: Frustration keywords (weight: 1.5)
    if frustration_score >= 0.7:
        factors.append("hohe Frustration erkannt")
        score += 1.5
    elif frustration_score >= 0.4:
        factors.append("Frustration erkannt")
        score += 0.75

    # Factor 3: Message frequency (weight: 1)
    msg_freq = get_message_frequency(user_id, minutes_back=60)
    if msg_freq["per_hour"] >= messages_per_hour_threshold:
        factors.append(f"hohe Nachrichtenrate ({msg_freq['per_hour']}/h)")
        score += 1
    elif msg_freq["per_hour"] >= messages_per_hour_threshold * 0.6:
        factors.append(f"erhoehte Nachrichtenrate ({msg_freq['per_hour']}/h)")
        score += 0.5

    # Factor 4: Active threads (weight: 0.5)
    thread_status = check_thread_limit(user_id, max_threads=3)
    if thread_status["exceeded"]:
        factors.append(f"{thread_status['active_count']} aktive Themen")
        score += 0.5

    # Determine level
    if score >= 3:
        level = "severe"
        recommendation = "COACH-MODUS: Nur 1 Aktion anbieten. Kurze Saetze. Empathisch bestaetigen."
    elif score >= 1.5:
        level = "mild"
        recommendation = "Strukturierte Antwort. Max 3 Punkte. Klare naechste Schritte."
    else:
        level = "none"
        recommendation = ""

    return {
        "overwhelmed": score >= 1.5,
        "level": level,
        "score": round(score, 1),
        "factors": factors,
        "message_rate": msg_freq["per_hour"],
        "recommendation": recommendation
    }


def build_overwhelm_prompt(
    user_id: int,
    stress_score: float = 0.0,
    frustration_score: float = 0.0
) -> str:
    """
    Build a prompt section for overwhelm handling.

    Only returns content if user is in overwhelmed state.

    Args:
        user_id: Telegram user ID
        stress_score: From sentiment analysis
        frustration_score: From sentiment analysis

    Returns:
        Prompt string for system injection, or empty string
    """
    state = check_overwhelm_state(
        user_id=user_id,
        stress_score=stress_score,
        frustration_score=frustration_score
    )

    if not state["overwhelmed"]:
        return ""

    factors_str = ", ".join(state["factors"])

    if state["level"] == "severe":
        return f"""=== OVERWHELM ERKANNT (SCHWER) ===
Faktoren: {factors_str}

WICHTIG - Antworte im NOTFALL-COACH-MODUS:
1. Beginne mit empathischer Bestaetigung ("Ich sehe, dass gerade viel los ist")
2. Biete NUR EINE konkrete Aktion an
3. Kurze Saetze (max 10 Worte)
4. Keine Listen mit mehr als 3 Punkten
5. Frage: "Was ist jetzt das Wichtigste?"

Ziel: Ruhe schaffen, nicht Information liefern."""

    else:  # mild
        return f"""=== OVERWHELM ERKANNT (MILD) ===
Faktoren: {factors_str}

Passe deine Antwort an:
- Strukturiert und uebersichtlich
- Max 3 Hauptpunkte
- Klarer naechster Schritt am Ende
- Vermeide lange Erklaerungen"""


# ============ Migration Functions ============

def migrate_thread_state_to_postgres() -> Dict[str, int]:
    """
    Migrate thread_state from SQLite to PostgreSQL active_context_buffer.

    Phase 12.2: One-time migration function.

    Returns:
        Dict with migration stats: {migrated: int, skipped: int, errors: int}
    """
    conn = _get_conn()
    cursor = conn.execute("SELECT * FROM thread_state")
    rows = cursor.fetchall()
    conn.close()

    migrated = 0
    skipped = 0
    errors = 0

    for row in rows:
        try:
            user_id = row["user_id"]
            topic = row["topic"]
            thread_id = _make_thread_id(user_id, topic)

            # Check if already migrated
            existing = postgres_state.get_buffer_thread(thread_id)
            if existing:
                skipped += 1
                continue

            # Map status
            status = _status_to_postgres(row["status"])

            # Map priority
            priority_text = row["priority"] or "normal"
            priority = _priority_text_to_int(priority_text)

            # Parse timestamps
            added_at = row["opened_at"] or datetime.now().isoformat()

            with postgres_state.get_cursor() as cur:
                cur.execute("""
                    INSERT INTO active_context_buffer
                    (id, state_id, title, context_summary, priority, status,
                     thread_type, metadata, added_at, last_touched_at, completed_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                """, (
                    thread_id,
                    f"user_{user_id}",
                    topic,
                    row["notes"],
                    priority,
                    status,
                    "conversation",
                    json.dumps({"user_id": user_id, "session_id": row["session_id"], "migrated_from": "sqlite"}),
                    added_at,
                    row["last_activity"] or added_at,
                    row["closed_at"]
                ))

            migrated += 1

        except Exception as e:
            log_with_context(logger, "warning", "Thread migration failed",
                           topic=row.get("topic"), error=str(e))
            errors += 1

    log_with_context(logger, "info", "Thread state migration completed",
                    migrated=migrated, skipped=skipped, errors=errors)

    return {"migrated": migrated, "skipped": skipped, "errors": errors}


# Initialize tables on import
init_context_tables()
