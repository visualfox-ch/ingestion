"""
Message Queue Service - Phase 22B-02

Async message passing between agents using Postgres as queue backend:
- Queue-based message delivery
- Priority ordering
- Retry logic with backoff
- Dead letter queue for failed messages
- Consumer groups for parallel processing

Architecture:
    Producer (Agent A)
        |
        v
    [Message Queue] (Postgres table)
        |
        +---> [Consumer 1] --> Agent B
        |
        +---> [Consumer 2] --> Agent C
        |
        +---> [Dead Letter Queue] (failed messages)
"""

from dataclasses import dataclass
from typing import Dict, List, Any, Optional, Callable
from datetime import datetime, timedelta
from enum import Enum
import json
import time
import uuid

from ..observability import get_logger, log_with_context
from ..postgres_state import get_conn

logger = get_logger("jarvis.message_queue")


class QueuePriority(int, Enum):
    """Queue priority levels (lower = higher priority)."""
    URGENT = 1
    HIGH = 2
    NORMAL = 3
    LOW = 4
    BATCH = 5


class MessageState(str, Enum):
    """Message states in the queue."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    DEAD = "dead"  # Moved to dead letter queue


@dataclass
class QueueMessage:
    """A message in the queue."""
    id: int
    message_id: str
    queue_name: str
    payload: Dict[str, Any]
    priority: QueuePriority
    state: MessageState
    retry_count: int
    max_retries: int
    created_at: datetime
    scheduled_at: Optional[datetime]
    processed_at: Optional[datetime]
    error: Optional[str]


class MessageQueueService:
    """
    Async message queue for inter-agent communication.

    Features:
    - Multiple named queues
    - Priority-based ordering
    - Visibility timeout (processing lock)
    - Automatic retries with exponential backoff
    - Dead letter queue
    - Scheduled messages
    """

    def __init__(self):
        self._ensure_tables()
        self._handlers: Dict[str, Callable] = {}

    def _ensure_tables(self):
        """Ensure queue tables exist."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS jarvis_message_queue (
                            id SERIAL PRIMARY KEY,
                            message_id VARCHAR(50) UNIQUE NOT NULL,
                            queue_name VARCHAR(50) NOT NULL,
                            payload JSONB NOT NULL,
                            priority INTEGER DEFAULT 3,
                            state VARCHAR(20) DEFAULT 'pending',
                            retry_count INTEGER DEFAULT 0,
                            max_retries INTEGER DEFAULT 3,
                            visibility_timeout TIMESTAMP,
                            scheduled_at TIMESTAMP,
                            processed_at TIMESTAMP,
                            error TEXT,
                            created_at TIMESTAMP DEFAULT NOW(),
                            updated_at TIMESTAMP DEFAULT NOW()
                        )
                    """)

                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS jarvis_dead_letter_queue (
                            id SERIAL PRIMARY KEY,
                            original_message_id VARCHAR(50),
                            queue_name VARCHAR(50),
                            payload JSONB,
                            error TEXT,
                            retry_count INTEGER,
                            original_created_at TIMESTAMP,
                            moved_at TIMESTAMP DEFAULT NOW()
                        )
                    """)

                    cur.execute("""
                        CREATE INDEX IF NOT EXISTS idx_mq_queue_state
                        ON jarvis_message_queue(queue_name, state, priority, scheduled_at)
                    """)

                    cur.execute("""
                        CREATE INDEX IF NOT EXISTS idx_mq_visibility
                        ON jarvis_message_queue(visibility_timeout)
                        WHERE state = 'processing'
                    """)

                    conn.commit()
        except Exception as e:
            log_with_context(logger, "debug", "Table creation failed", error=str(e))

    def enqueue(
        self,
        queue_name: str,
        payload: Dict[str, Any],
        priority: str = "normal",
        delay_seconds: int = 0,
        max_retries: int = 3
    ) -> Dict[str, Any]:
        """
        Add a message to the queue.

        Args:
            queue_name: Target queue (e.g., "fit_jarvis", "work_jarvis")
            payload: Message content
            priority: urgent, high, normal, low, batch
            delay_seconds: Delay before message becomes visible
            max_retries: Max retry attempts on failure

        Returns:
            Dict with message_id
        """
        try:
            message_id = f"q_{uuid.uuid4().hex[:12]}"
            priority_val = getattr(QueuePriority, priority.upper(), QueuePriority.NORMAL).value

            scheduled_at = None
            if delay_seconds > 0:
                scheduled_at = datetime.now() + timedelta(seconds=delay_seconds)

            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO jarvis_message_queue
                        (message_id, queue_name, payload, priority, max_retries, scheduled_at)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        RETURNING id
                    """, (
                        message_id, queue_name, json.dumps(payload),
                        priority_val, max_retries, scheduled_at
                    ))
                    db_id = cur.fetchone()["id"]
                    conn.commit()

                    log_with_context(logger, "info", "Message enqueued",
                                    message_id=message_id, queue=queue_name)

                    return {
                        "success": True,
                        "message_id": message_id,
                        "queue": queue_name,
                        "priority": priority,
                        "scheduled_at": scheduled_at.isoformat() if scheduled_at else None
                    }

        except Exception as e:
            log_with_context(logger, "error", "Enqueue failed", error=str(e))
            return {"success": False, "error": str(e)}

    def dequeue(
        self,
        queue_name: str,
        visibility_timeout_seconds: int = 30,
        limit: int = 1
    ) -> Dict[str, Any]:
        """
        Get messages from queue for processing.

        Uses SELECT FOR UPDATE SKIP LOCKED for concurrent access.
        Messages are locked for visibility_timeout_seconds.

        Args:
            queue_name: Queue to read from
            visibility_timeout_seconds: Lock duration
            limit: Max messages to fetch

        Returns:
            Dict with messages list
        """
        try:
            visibility_timeout = datetime.now() + timedelta(seconds=visibility_timeout_seconds)

            with get_conn() as conn:
                with conn.cursor() as cur:
                    # Select and lock available messages
                    cur.execute("""
                        UPDATE jarvis_message_queue
                        SET state = 'processing',
                            visibility_timeout = %s,
                            updated_at = NOW()
                        WHERE id IN (
                            SELECT id FROM jarvis_message_queue
                            WHERE queue_name = %s
                              AND state = 'pending'
                              AND (scheduled_at IS NULL OR scheduled_at <= NOW())
                            ORDER BY priority ASC, created_at ASC
                            LIMIT %s
                            FOR UPDATE SKIP LOCKED
                        )
                        RETURNING id, message_id, payload, priority, retry_count, created_at
                    """, (visibility_timeout, queue_name, limit))

                    rows = cur.fetchall()
                    conn.commit()

                    messages = [
                        {
                            "id": row["id"],
                            "message_id": row["message_id"],
                            "payload": row["payload"],
                            "priority": row["priority"],
                            "retry_count": row["retry_count"],
                            "created_at": row["created_at"].isoformat()
                        }
                        for row in rows
                    ]

                    return {
                        "success": True,
                        "queue": queue_name,
                        "messages": messages,
                        "count": len(messages)
                    }

        except Exception as e:
            log_with_context(logger, "error", "Dequeue failed", error=str(e))
            return {"success": False, "error": str(e)}

    def ack(self, message_id: str) -> Dict[str, Any]:
        """
        Acknowledge successful processing.

        Removes message from queue.
        """
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE jarvis_message_queue
                        SET state = 'completed',
                            processed_at = NOW(),
                            updated_at = NOW()
                        WHERE message_id = %s AND state = 'processing'
                        RETURNING id
                    """, (message_id,))

                    row = cur.fetchone()
                    conn.commit()

                    if row:
                        return {"success": True, "message_id": message_id, "state": "completed"}
                    return {"success": False, "error": "Message not found or not processing"}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def nack(
        self,
        message_id: str,
        error: str = None,
        retry: bool = True
    ) -> Dict[str, Any]:
        """
        Negative acknowledge - processing failed.

        If retry=True and retries remaining, requeue with backoff.
        Otherwise move to dead letter queue.
        """
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    # Get current message state
                    cur.execute("""
                        SELECT id, queue_name, payload, retry_count, max_retries, created_at
                        FROM jarvis_message_queue
                        WHERE message_id = %s AND state = 'processing'
                    """, (message_id,))

                    row = cur.fetchone()
                    if not row:
                        return {"success": False, "error": "Message not found"}

                    new_retry_count = row["retry_count"] + 1

                    if retry and new_retry_count < row["max_retries"]:
                        # Requeue with exponential backoff
                        backoff_seconds = min(300, 2 ** new_retry_count * 5)
                        scheduled_at = datetime.now() + timedelta(seconds=backoff_seconds)

                        cur.execute("""
                            UPDATE jarvis_message_queue
                            SET state = 'pending',
                                retry_count = %s,
                                scheduled_at = %s,
                                visibility_timeout = NULL,
                                error = %s,
                                updated_at = NOW()
                            WHERE message_id = %s
                        """, (new_retry_count, scheduled_at, error, message_id))

                        conn.commit()
                        return {
                            "success": True,
                            "message_id": message_id,
                            "action": "requeued",
                            "retry_count": new_retry_count,
                            "next_attempt": scheduled_at.isoformat()
                        }
                    else:
                        # Move to dead letter queue
                        cur.execute("""
                            INSERT INTO jarvis_dead_letter_queue
                            (original_message_id, queue_name, payload, error, retry_count, original_created_at)
                            VALUES (%s, %s, %s, %s, %s, %s)
                        """, (
                            message_id, row["queue_name"], json.dumps(row["payload"]),
                            error, new_retry_count, row["created_at"]
                        ))

                        cur.execute("""
                            UPDATE jarvis_message_queue
                            SET state = 'dead', error = %s, updated_at = NOW()
                            WHERE message_id = %s
                        """, (error, message_id))

                        conn.commit()
                        return {
                            "success": True,
                            "message_id": message_id,
                            "action": "dead_letter",
                            "retry_count": new_retry_count
                        }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def release_stale(self, timeout_minutes: int = 5) -> Dict[str, Any]:
        """
        Release messages stuck in processing state.

        Called periodically to handle crashed consumers.
        """
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE jarvis_message_queue
                        SET state = 'pending',
                            visibility_timeout = NULL,
                            updated_at = NOW()
                        WHERE state = 'processing'
                          AND visibility_timeout < NOW() - INTERVAL '%s minutes'
                        RETURNING message_id
                    """, (timeout_minutes,))

                    released = [row["message_id"] for row in cur.fetchall()]
                    conn.commit()

                    return {
                        "success": True,
                        "released_count": len(released),
                        "message_ids": released
                    }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_queue_stats(self, queue_name: Optional[str] = None) -> Dict[str, Any]:
        """Get queue statistics."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    if queue_name:
                        cur.execute("""
                            SELECT
                                state,
                                COUNT(*) as count,
                                AVG(EXTRACT(EPOCH FROM (NOW() - created_at))) as avg_age_seconds
                            FROM jarvis_message_queue
                            WHERE queue_name = %s
                            GROUP BY state
                        """, (queue_name,))
                    else:
                        cur.execute("""
                            SELECT
                                queue_name,
                                state,
                                COUNT(*) as count
                            FROM jarvis_message_queue
                            GROUP BY queue_name, state
                        """)

                    rows = cur.fetchall()

                    # Get dead letter count
                    if queue_name:
                        cur.execute("""
                            SELECT COUNT(*) as dlq_count
                            FROM jarvis_dead_letter_queue
                            WHERE queue_name = %s
                        """, (queue_name,))
                    else:
                        cur.execute("SELECT COUNT(*) as dlq_count FROM jarvis_dead_letter_queue")

                    dlq_count = cur.fetchone()["dlq_count"]

                    if queue_name:
                        stats = {row["state"]: row["count"] for row in rows}
                        return {
                            "success": True,
                            "queue": queue_name,
                            "pending": stats.get("pending", 0),
                            "processing": stats.get("processing", 0),
                            "completed": stats.get("completed", 0),
                            "failed": stats.get("failed", 0),
                            "dead_letter": dlq_count
                        }
                    else:
                        by_queue: Dict[str, Dict] = {}
                        for row in rows:
                            q = row["queue_name"]
                            if q not in by_queue:
                                by_queue[q] = {}
                            by_queue[q][row["state"]] = row["count"]

                        return {
                            "success": True,
                            "queues": by_queue,
                            "total_dead_letter": dlq_count
                        }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def purge_completed(self, older_than_hours: int = 24) -> Dict[str, Any]:
        """Purge completed messages older than specified hours."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        DELETE FROM jarvis_message_queue
                        WHERE state = 'completed'
                          AND processed_at < NOW() - INTERVAL '%s hours'
                        RETURNING id
                    """, (older_than_hours,))

                    deleted = cur.rowcount
                    conn.commit()

                    return {
                        "success": True,
                        "deleted_count": deleted
                    }

        except Exception as e:
            return {"success": False, "error": str(e)}


# Singleton
_service: Optional[MessageQueueService] = None


def get_message_queue_service() -> MessageQueueService:
    """Get or create message queue service singleton."""
    global _service
    if _service is None:
        _service = MessageQueueService()
    return _service
