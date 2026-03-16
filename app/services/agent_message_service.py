"""
Agent Message Service - Tier 3 #9

Standardized inter-agent communication protocol.
Enables specialists to:
- Send messages to each other
- Share context during handoffs
- Request information from other agents
- Broadcast notifications

Message Types:
- request: Ask another agent for info/action
- response: Reply to a request
- notification: One-way informational message
- broadcast: Message to all agents
- handoff: Transfer context between specialists
- context_share: Share relevant context
"""

import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from enum import Enum
import json

from ..observability import get_logger, log_with_context
from ..postgres_state import get_conn

logger = get_logger("jarvis.agent_message")


class MessageType(str, Enum):
    REQUEST = "request"
    RESPONSE = "response"
    NOTIFICATION = "notification"
    BROADCAST = "broadcast"
    HANDOFF = "handoff"
    CONTEXT_SHARE = "context_share"


class MessageStatus(str, Enum):
    PENDING = "pending"
    DELIVERED = "delivered"
    READ = "read"
    PROCESSED = "processed"
    EXPIRED = "expired"
    FAILED = "failed"


class MessagePriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class MessageIntent(str, Enum):
    REQUEST_INFO = "request_info"
    DELEGATE_TASK = "delegate_task"
    SHARE_CONTEXT = "share_context"
    ASK_QUESTION = "ask_question"
    PROVIDE_ANSWER = "provide_answer"
    NOTIFICATION = "notification"


@dataclass
class AgentMessage:
    """A message between agents."""
    message_id: str
    from_agent: str
    to_agent: Optional[str]
    message_type: MessageType
    subject: str
    content: Dict[str, Any]
    priority: MessagePriority = MessagePriority.NORMAL
    status: MessageStatus = MessageStatus.PENDING
    reply_to_id: Optional[str] = None
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    related_query: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None


@dataclass
class MessageContent:
    """Structured message content."""
    intent: MessageIntent
    payload: Dict[str, Any]
    expected_response: str = "none"  # required, optional, none
    timeout_seconds: int = 30


class AgentMessageService:
    """
    Service for inter-agent communication.

    Provides:
    - Message sending/receiving
    - Channel management
    - Message templating
    - Async queue processing
    """

    def __init__(self):
        self._ensure_tables()

    def _ensure_tables(self):
        """Ensure message tables exist."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT EXISTS (
                            SELECT FROM information_schema.tables
                            WHERE table_name = 'jarvis_agent_messages'
                        )
                    """)
                    if not cur.fetchone()[0]:
                        log_with_context(logger, "info", "Agent message tables not found, will be created on first use")
        except Exception as e:
            log_with_context(logger, "debug", "Message tables check failed", error=str(e))

    def send_message(
        self,
        from_agent: str,
        to_agent: Optional[str],
        message_type: str,
        subject: str,
        content: Dict[str, Any],
        priority: str = "normal",
        reply_to_id: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        related_query: Optional[str] = None,
        expires_in_seconds: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Send a message from one agent to another.

        Args:
            from_agent: Sending agent (jarvis, fit, work, comm)
            to_agent: Receiving agent (None for broadcast)
            message_type: Type of message
            subject: Brief description
            content: Structured content with intent and payload
            priority: Message priority
            reply_to_id: If replying to another message
            session_id: Current session
            user_id: Current user
            related_query: Original user query if relevant
            expires_in_seconds: Auto-expire after N seconds
            metadata: Additional metadata

        Returns:
            Dict with message_id and status
        """
        try:
            # Check if channel is allowed
            if to_agent and not self._is_channel_allowed(from_agent, to_agent, message_type):
                return {
                    "success": False,
                    "error": f"Channel {from_agent} -> {to_agent} not allowed for {message_type}"
                }

            message_id = f"msg_{uuid.uuid4().hex[:12]}"
            expires_at = None
            if expires_in_seconds:
                expires_at = datetime.now() + timedelta(seconds=expires_in_seconds)

            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO jarvis_agent_messages
                        (message_id, from_agent, to_agent, reply_to_id, message_type,
                         subject, content, priority, session_id, user_id, related_query,
                         expires_at, metadata)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                    """, (
                        message_id, from_agent, to_agent, reply_to_id, message_type,
                        subject, json.dumps(content), priority, session_id, user_id,
                        related_query, expires_at, json.dumps(metadata or {})
                    ))
                    db_id = cur.fetchone()["id"]

                    # Update channel stats
                    if to_agent:
                        cur.execute("""
                            UPDATE jarvis_agent_channels
                            SET messages_sent = messages_sent + 1,
                                last_message_at = NOW()
                            WHERE from_agent = %s AND to_agent = %s
                        """, (from_agent, to_agent))

                    conn.commit()

                    log_with_context(logger, "info", "Agent message sent",
                                    message_id=message_id,
                                    from_agent=from_agent,
                                    to_agent=to_agent or "broadcast",
                                    type=message_type)

                    return {
                        "success": True,
                        "message_id": message_id,
                        "db_id": db_id,
                        "from": from_agent,
                        "to": to_agent or "broadcast",
                        "type": message_type
                    }

        except Exception as e:
            log_with_context(logger, "error", "Failed to send agent message", error=str(e))
            return {"success": False, "error": str(e)}

    def _is_channel_allowed(self, from_agent: str, to_agent: str, message_type: str) -> bool:
        """Check if this channel allows this message type."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT allowed_message_types, enabled
                        FROM jarvis_agent_channels
                        WHERE (from_agent = %s AND to_agent = %s)
                           OR (bidirectional = TRUE AND from_agent = %s AND to_agent = %s)
                        LIMIT 1
                    """, (from_agent, to_agent, to_agent, from_agent))

                    row = cur.fetchone()
                    if not row:
                        # No explicit channel = allow by default
                        return True

                    if not row["enabled"]:
                        return False

                    allowed = row["allowed_message_types"] or []
                    return message_type in allowed

        except Exception as e:
            log_with_context(logger, "debug", "Channel check failed", error=str(e))
            return True  # Allow if can't check

    def get_messages(
        self,
        agent: str,
        status: Optional[str] = None,
        message_type: Optional[str] = None,
        limit: int = 20,
        include_broadcast: bool = True
    ) -> Dict[str, Any]:
        """
        Get messages for an agent.

        Args:
            agent: The agent to get messages for
            status: Filter by status
            message_type: Filter by type
            limit: Max messages to return
            include_broadcast: Include broadcast messages

        Returns:
            Dict with messages list
        """
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    query = """
                        SELECT message_id, from_agent, to_agent, reply_to_id,
                               message_type, subject, content, priority, status,
                               session_id, related_query, metadata, created_at, expires_at
                        FROM jarvis_agent_messages
                        WHERE (to_agent = %s OR (to_agent IS NULL AND %s))
                          AND (expires_at IS NULL OR expires_at > NOW())
                    """
                    params = [agent, include_broadcast]

                    if status:
                        query += " AND status = %s"
                        params.append(status)

                    if message_type:
                        query += " AND message_type = %s"
                        params.append(message_type)

                    query += " ORDER BY CASE priority WHEN 'urgent' THEN 1 WHEN 'high' THEN 2 WHEN 'normal' THEN 3 ELSE 4 END, created_at DESC LIMIT %s"
                    params.append(limit)

                    cur.execute(query, params)

                    messages = []
                    for row in cur.fetchall():
                        messages.append({
                            "message_id": row["message_id"],
                            "from": row["from_agent"],
                            "to": row["to_agent"],
                            "reply_to": row["reply_to_id"],
                            "type": row["message_type"],
                            "subject": row["subject"],
                            "content": row["content"],
                            "priority": row["priority"],
                            "status": row["status"],
                            "session_id": row["session_id"],
                            "query": row["related_query"],
                            "created_at": row["created_at"].isoformat() if row["created_at"] else None
                        })

                    return {
                        "success": True,
                        "agent": agent,
                        "messages": messages,
                        "count": len(messages)
                    }

        except Exception as e:
            log_with_context(logger, "error", "Failed to get messages", error=str(e))
            return {"success": False, "error": str(e)}

    def mark_message(
        self,
        message_id: str,
        status: str,
        agent: Optional[str] = None
    ) -> Dict[str, Any]:
        """Mark a message with a new status."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    # Build update based on status
                    timestamp_field = None
                    if status == "delivered":
                        timestamp_field = "delivered_at"
                    elif status == "read":
                        timestamp_field = "read_at"
                    elif status == "processed":
                        timestamp_field = "processed_at"

                    if timestamp_field:
                        cur.execute(f"""
                            UPDATE jarvis_agent_messages
                            SET status = %s, {timestamp_field} = NOW(), updated_at = NOW()
                            WHERE message_id = %s
                        """, (status, message_id))
                    else:
                        cur.execute("""
                            UPDATE jarvis_agent_messages
                            SET status = %s, updated_at = NOW()
                            WHERE message_id = %s
                        """, (status, message_id))

                    conn.commit()

                    return {
                        "success": True,
                        "message_id": message_id,
                        "status": status
                    }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def reply_to_message(
        self,
        original_message_id: str,
        from_agent: str,
        content: Dict[str, Any],
        subject: Optional[str] = None
    ) -> Dict[str, Any]:
        """Reply to a message."""
        try:
            # Get original message
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT from_agent, subject, session_id, user_id, related_query
                        FROM jarvis_agent_messages
                        WHERE message_id = %s
                    """, (original_message_id,))

                    original = cur.fetchone()
                    if not original:
                        return {"success": False, "error": "Original message not found"}

                    # Mark original as processed
                    cur.execute("""
                        UPDATE jarvis_agent_messages
                        SET status = 'processed', processed_at = NOW()
                        WHERE message_id = %s
                    """, (original_message_id,))
                    conn.commit()

            # Send reply
            return self.send_message(
                from_agent=from_agent,
                to_agent=original["from_agent"],
                message_type="response",
                subject=subject or f"Re: {original['subject']}",
                content=content,
                reply_to_id=original_message_id,
                session_id=original["session_id"],
                user_id=original["user_id"],
                related_query=original["related_query"]
            )

        except Exception as e:
            return {"success": False, "error": str(e)}

    def broadcast_message(
        self,
        from_agent: str,
        subject: str,
        content: Dict[str, Any],
        priority: str = "normal",
        session_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Broadcast a message to all agents."""
        return self.send_message(
            from_agent=from_agent,
            to_agent=None,  # None = broadcast
            message_type="broadcast",
            subject=subject,
            content=content,
            priority=priority,
            session_id=session_id
        )

    def handoff_context(
        self,
        from_specialist: str,
        to_specialist: str,
        context_summary: str,
        relevant_facts: List[str],
        user_mood: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Handoff context from one specialist to another.

        Used when switching between FitJarvis, WorkJarvis, CommJarvis.
        """
        content = {
            "intent": "share_context",
            "payload": {
                "previous_specialist": from_specialist,
                "context_summary": context_summary,
                "relevant_facts": relevant_facts,
                "user_mood": user_mood,
                "handoff_reason": "user_topic_change"
            },
            "expected_response": "none"
        }

        return self.send_message(
            from_agent=from_specialist,
            to_agent=to_specialist,
            message_type="handoff",
            subject=f"Kontext-Übergabe von {from_specialist.title()}Jarvis",
            content=content,
            priority="high",
            session_id=session_id,
            user_id=user_id
        )

    def request_info(
        self,
        from_agent: str,
        to_agent: str,
        info_type: str,
        parameters: Dict[str, Any],
        timeout_seconds: int = 30,
        session_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Request information from another agent."""
        content = {
            "intent": "request_info",
            "payload": {
                "info_type": info_type,
                **parameters
            },
            "expected_response": "required",
            "timeout_seconds": timeout_seconds
        }

        return self.send_message(
            from_agent=from_agent,
            to_agent=to_agent,
            message_type="request",
            subject=f"Info-Anfrage: {info_type}",
            content=content,
            priority="high",
            session_id=session_id,
            expires_in_seconds=timeout_seconds * 2
        )

    def get_pending_requests(self, agent: str) -> Dict[str, Any]:
        """Get pending requests for an agent."""
        return self.get_messages(
            agent=agent,
            status="pending",
            message_type="request"
        )

    def get_message_stats(self, agent: Optional[str] = None) -> Dict[str, Any]:
        """Get messaging statistics."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    if agent:
                        cur.execute("""
                            SELECT
                                COUNT(*) FILTER (WHERE from_agent = %s) as sent,
                                COUNT(*) FILTER (WHERE to_agent = %s) as received,
                                COUNT(*) FILTER (WHERE to_agent = %s AND status = 'pending') as pending,
                                COUNT(*) FILTER (WHERE message_type = 'request' AND to_agent = %s AND status = 'pending') as pending_requests
                            FROM jarvis_agent_messages
                            WHERE from_agent = %s OR to_agent = %s
                        """, (agent, agent, agent, agent, agent, agent))
                    else:
                        cur.execute("""
                            SELECT
                                COUNT(*) as total,
                                COUNT(*) FILTER (WHERE status = 'pending') as pending,
                                COUNT(*) FILTER (WHERE status = 'processed') as processed,
                                COUNT(*) FILTER (WHERE message_type = 'request') as requests,
                                COUNT(*) FILTER (WHERE message_type = 'handoff') as handoffs
                            FROM jarvis_agent_messages
                        """)

                    row = cur.fetchone()

                    return {
                        "success": True,
                        "agent": agent,
                        "stats": dict(row) if row else {}
                    }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_templates(self, from_agent: Optional[str] = None) -> Dict[str, Any]:
        """Get available message templates."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    query = """
                        SELECT template_name, description, from_agent_pattern,
                               to_agent_pattern, message_type, subject_template,
                               content_template, use_count
                        FROM jarvis_message_templates
                    """
                    params = []

                    if from_agent:
                        query += " WHERE from_agent_pattern = %s OR from_agent_pattern IS NULL"
                        params.append(from_agent)

                    query += " ORDER BY use_count DESC"
                    cur.execute(query, params)

                    templates = []
                    for row in cur.fetchall():
                        templates.append({
                            "name": row["template_name"],
                            "description": row["description"],
                            "from": row["from_agent_pattern"],
                            "to": row["to_agent_pattern"],
                            "type": row["message_type"],
                            "subject": row["subject_template"],
                            "uses": row["use_count"]
                        })

                    return {
                        "success": True,
                        "templates": templates,
                        "count": len(templates)
                    }

        except Exception as e:
            return {"success": False, "error": str(e)}


# Singleton
_service: Optional[AgentMessageService] = None


def get_agent_message_service() -> AgentMessageService:
    """Get or create agent message service singleton."""
    global _service
    if _service is None:
        _service = AgentMessageService()
    return _service
