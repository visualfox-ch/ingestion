"""
Communication Agent Service (CommJarvis) - Phase 22A-06

Domain-specific service for communication and relationship management:
- Inbox triage and prioritization
- Response drafting with context
- Relationship tracking
- Followup scheduling
"""

from dataclasses import dataclass
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta, date
import json

from ..observability import get_logger, log_with_context
from ..postgres_state import get_conn

logger = get_logger("jarvis.comm_agent")


class CommAgentService:
    """
    CommJarvis - Communication and Relationship Specialist.

    Provides:
    - Inbox triage (prioritize messages)
    - Response drafting with relationship context
    - Relationship tracking and CRM-lite
    - Followup scheduling and reminders
    """

    def __init__(self):
        pass

    # =========================================================================
    # Inbox Triage
    # =========================================================================

    def triage_inbox(
        self,
        messages: List[Dict[str, Any]] = None,
        source: str = None,
        show_triaged: bool = False,
        limit: int = 20,
        user_id: str = "1"
    ) -> Dict[str, Any]:
        """
        Triage inbox messages by priority.

        Args:
            messages: New messages to add and triage
            source: Filter by source (gmail, telegram, etc.)
            show_triaged: Include already triaged items
            limit: Max items to return
        """
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    # Add new messages if provided
                    if messages:
                        for msg in messages:
                            priority, category, action = self._calculate_priority(cur, msg, user_id)
                            cur.execute("""
                                INSERT INTO jarvis_inbox_items
                                (user_id, source, message_id, sender_name, sender_email,
                                 subject, preview, priority, category, suggested_action,
                                 requires_response, received_at)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                                ON CONFLICT DO NOTHING
                            """, (
                                user_id,
                                msg.get("source", "email"),
                                msg.get("message_id"),
                                msg.get("sender_name"),
                                msg.get("sender_email"),
                                msg.get("subject"),
                                msg.get("preview", "")[:500],
                                priority,
                                category,
                                action,
                                action in ["reply_now", "reply_later"],
                                msg.get("received_at", datetime.now())
                            ))
                        conn.commit()

                    # Query inbox
                    query = """
                        SELECT id, source, sender_name, sender_email, subject, preview,
                               priority, category, suggested_action, requires_response,
                               received_at, triaged
                        FROM jarvis_inbox_items
                        WHERE user_id = %s AND NOT acted_on
                    """
                    params = [user_id]

                    if source:
                        query += " AND source = %s"
                        params.append(source)

                    if not show_triaged:
                        query += " AND NOT triaged"

                    query += " ORDER BY priority DESC, received_at DESC LIMIT %s"
                    params.append(limit)

                    cur.execute(query, tuple(params))

                    items = []
                    urgent = []
                    needs_reply = []

                    for row in cur.fetchall():
                        item = {
                            "id": row[0],
                            "source": row[1],
                            "sender": row[2],
                            "email": row[3],
                            "subject": row[4],
                            "preview": row[5][:100] + "..." if row[5] and len(row[5]) > 100 else row[5],
                            "priority": row[6],
                            "category": row[7],
                            "action": row[8],
                            "needs_reply": row[9],
                            "received": row[10].strftime("%Y-%m-%d %H:%M") if row[10] else None,
                            "triaged": row[11]
                        }
                        items.append(item)

                        if row[7] == "urgent":
                            urgent.append(item)
                        if row[9]:
                            needs_reply.append(item)

                    # Summary
                    cur.execute("""
                        SELECT category, COUNT(*) FROM jarvis_inbox_items
                        WHERE user_id = %s AND NOT acted_on
                        GROUP BY category
                    """, (user_id,))
                    by_category = {r[0]: r[1] for r in cur.fetchall()}

                    return {
                        "success": True,
                        "items": items,
                        "urgent": urgent[:5],
                        "needs_reply": needs_reply[:5],
                        "by_category": by_category,
                        "total": len(items),
                        "message": f"{len(urgent)} urgent, {len(needs_reply)} need reply"
                    }

        except Exception as e:
            log_with_context(logger, "error", "Inbox triage failed", error=str(e))
            return {"success": False, "error": str(e)}

    def _calculate_priority(
        self,
        cur,
        msg: Dict[str, Any],
        user_id: str
    ) -> tuple:
        """Calculate priority, category, and suggested action."""
        priority = 50
        category = "normal"
        action = "archive"

        sender_email = msg.get("sender_email", "").lower()
        subject = (msg.get("subject") or "").lower()
        preview = (msg.get("preview") or "").lower()

        # Check if from known important contact
        cur.execute("""
            SELECT importance, relationship_type FROM jarvis_relationships
            WHERE user_id = %s AND LOWER(contact_email) = %s
        """, (user_id, sender_email))
        relationship = cur.fetchone()

        if relationship:
            priority += relationship[0] // 2  # Add up to 50 based on importance
            if relationship[1] in ["client", "family", "mentor"]:
                priority += 20

        # Keyword analysis
        urgent_words = ["urgent", "asap", "immediately", "critical", "emergency", "deadline"]
        important_words = ["important", "priority", "attention", "action required"]
        fyi_words = ["fyi", "newsletter", "update", "digest", "weekly", "monthly"]

        text = f"{subject} {preview}"

        if any(w in text for w in urgent_words):
            priority += 30
            category = "urgent"
            action = "reply_now"
        elif any(w in text for w in important_words):
            priority += 20
            category = "important"
            action = "reply_later"
        elif any(w in text for w in fyi_words):
            priority -= 20
            category = "fyi"
            action = "archive"

        # Question detection
        if "?" in subject or "?" in preview[:200]:
            action = "reply_later" if action == "archive" else action

        priority = max(1, min(100, priority))

        return priority, category, action

    # =========================================================================
    # Response Drafting
    # =========================================================================

    def draft_response(
        self,
        to: str,
        context: str,
        tone: str = "friendly",
        include_greeting: bool = True,
        include_signature: bool = True,
        max_length: int = None,
        inbox_item_id: int = None,
        user_id: str = "1"
    ) -> Dict[str, Any]:
        """
        Draft a response with context awareness.

        Args:
            to: Recipient name or email
            context: What to respond about
            tone: formal, friendly, brief, detailed
            include_greeting: Add greeting
            include_signature: Add signature
            max_length: Max words
            inbox_item_id: Link to inbox item
        """
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    # Get relationship context
                    relationship_context = None
                    cur.execute("""
                        SELECT contact_name, relationship_type, company, role,
                               last_contact_date, notes
                        FROM jarvis_relationships
                        WHERE user_id = %s AND (
                            LOWER(contact_name) LIKE %s OR
                            LOWER(contact_email) LIKE %s
                        )
                        LIMIT 1
                    """, (user_id, f"%{to.lower()}%", f"%{to.lower()}%"))
                    rel = cur.fetchone()

                    if rel:
                        relationship_context = {
                            "name": rel[0],
                            "type": rel[1],
                            "company": rel[2],
                            "role": rel[3],
                            "last_contact": rel[4].isoformat() if rel[4] else None,
                            "notes": rel[5]
                        }

                    # Get recent interactions
                    recent_interactions = []
                    if rel:
                        cur.execute("""
                            SELECT interaction_type, subject, summary, interaction_date
                            FROM jarvis_interactions
                            WHERE user_id = %s AND contact_name ILIKE %s
                            ORDER BY interaction_date DESC LIMIT 3
                        """, (user_id, f"%{rel[0]}%"))
                        recent_interactions = [
                            {"type": r[0], "subject": r[1], "summary": r[2],
                             "date": r[3].strftime("%Y-%m-%d") if r[3] else None}
                            for r in cur.fetchall()
                        ]

                    # Build draft components
                    greeting = self._get_greeting(to, tone, relationship_context)
                    body = self._draft_body(context, tone, max_length)
                    signature = self._get_signature(tone) if include_signature else ""

                    draft = ""
                    if include_greeting:
                        draft += greeting + "\n\n"
                    draft += body
                    if signature:
                        draft += "\n\n" + signature

                    # Save draft
                    cur.execute("""
                        INSERT INTO jarvis_response_drafts
                        (user_id, inbox_item_id, recipient_name, channel, draft_content,
                         tone, context_used)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                    """, (
                        user_id,
                        inbox_item_id,
                        to,
                        "email",
                        draft,
                        tone,
                        json.dumps({
                            "relationship": relationship_context,
                            "recent_interactions": len(recent_interactions),
                            "context_provided": context[:100]
                        })
                    ))
                    draft_id = cur.fetchone()[0]
                    conn.commit()

                    return {
                        "success": True,
                        "draft_id": draft_id,
                        "to": to,
                        "draft": draft,
                        "tone": tone,
                        "relationship_context": relationship_context,
                        "recent_interactions": recent_interactions,
                        "word_count": len(draft.split()),
                        "message": f"Draft created for {to}"
                    }

        except Exception as e:
            log_with_context(logger, "error", "Draft failed", error=str(e))
            return {"success": False, "error": str(e)}

    def _get_greeting(self, name: str, tone: str, rel_context: Dict = None) -> str:
        """Generate appropriate greeting."""
        first_name = name.split()[0] if name else "there"

        if tone == "formal":
            if rel_context and rel_context.get("type") == "client":
                return f"Dear {name},"
            return f"Hello {name},"
        elif tone == "brief":
            return f"Hi {first_name},"
        else:  # friendly
            return f"Hey {first_name},"

    def _draft_body(self, context: str, tone: str, max_length: int = None) -> str:
        """Generate response body based on context."""
        # This is a placeholder - in real impl, this would use LLM
        body = context

        if max_length:
            words = body.split()
            if len(words) > max_length:
                body = " ".join(words[:max_length]) + "..."

        return body

    def _get_signature(self, tone: str) -> str:
        """Get appropriate signature."""
        if tone == "formal":
            return "Best regards,\nMicha"
        elif tone == "brief":
            return "- Micha"
        else:
            return "Cheers,\nMicha"

    # =========================================================================
    # Relationship Tracking
    # =========================================================================

    def track_relationship(
        self,
        action: str = "get",
        contact_name: str = None,
        contact_email: str = None,
        relationship_type: str = None,
        company: str = None,
        importance: int = None,
        notes: str = None,
        tags: List[str] = None,
        user_id: str = "1"
    ) -> Dict[str, Any]:
        """
        Track and manage relationships.

        Args:
            action: "add", "update", "get", "list", "search"
            contact_name: Contact's name
            contact_email: Contact's email
            relationship_type: friend, family, colleague, client, mentor, acquaintance
            company: Company name
            importance: 1-100 importance score
            notes: Notes about the relationship
            tags: Tags for categorization
        """
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    if action == "add":
                        cur.execute("""
                            INSERT INTO jarvis_relationships
                            (user_id, contact_name, contact_email, relationship_type,
                             company, importance, notes, tags)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (user_id, contact_email) DO UPDATE SET
                                contact_name = EXCLUDED.contact_name,
                                relationship_type = COALESCE(EXCLUDED.relationship_type, jarvis_relationships.relationship_type),
                                company = COALESCE(EXCLUDED.company, jarvis_relationships.company),
                                importance = COALESCE(EXCLUDED.importance, jarvis_relationships.importance),
                                notes = COALESCE(EXCLUDED.notes, jarvis_relationships.notes),
                                updated_at = NOW()
                            RETURNING id
                        """, (
                            user_id, contact_name, contact_email, relationship_type,
                            company, importance or 50, notes, json.dumps(tags or [])
                        ))
                        rel_id = cur.fetchone()[0]
                        conn.commit()

                        return {
                            "success": True,
                            "relationship_id": rel_id,
                            "contact": contact_name,
                            "message": f"Relationship with {contact_name} saved"
                        }

                    elif action == "get":
                        cur.execute("""
                            SELECT id, contact_name, contact_email, relationship_type,
                                   company, role, importance, last_contact_date,
                                   next_followup_date, notes, tags
                            FROM jarvis_relationships
                            WHERE user_id = %s AND (
                                contact_name ILIKE %s OR contact_email ILIKE %s
                            )
                            LIMIT 1
                        """, (user_id, f"%{contact_name}%", f"%{contact_name}%"))
                        row = cur.fetchone()

                        if not row:
                            return {"success": False, "error": f"Contact '{contact_name}' not found"}

                        # Get interaction count
                        cur.execute("""
                            SELECT COUNT(*) FROM jarvis_interactions
                            WHERE relationship_id = %s
                        """, (row[0],))
                        interaction_count = cur.fetchone()[0]

                        return {
                            "success": True,
                            "contact": {
                                "id": row[0],
                                "name": row[1],
                                "email": row[2],
                                "type": row[3],
                                "company": row[4],
                                "role": row[5],
                                "importance": row[6],
                                "last_contact": row[7].isoformat() if row[7] else None,
                                "next_followup": row[8].isoformat() if row[8] else None,
                                "notes": row[9],
                                "tags": row[10],
                                "interactions": interaction_count
                            }
                        }

                    elif action == "list":
                        cur.execute("""
                            SELECT id, contact_name, relationship_type, company,
                                   importance, last_contact_date
                            FROM jarvis_relationships
                            WHERE user_id = %s
                            ORDER BY importance DESC, last_contact_date DESC NULLS LAST
                            LIMIT 50
                        """, (user_id,))

                        contacts = [
                            {
                                "id": r[0],
                                "name": r[1],
                                "type": r[2],
                                "company": r[3],
                                "importance": r[4],
                                "last_contact": r[5].isoformat() if r[5] else None
                            }
                            for r in cur.fetchall()
                        ]

                        return {
                            "success": True,
                            "contacts": contacts,
                            "count": len(contacts)
                        }

                    elif action == "search":
                        cur.execute("""
                            SELECT id, contact_name, contact_email, relationship_type, company
                            FROM jarvis_relationships
                            WHERE user_id = %s AND (
                                contact_name ILIKE %s OR
                                contact_email ILIKE %s OR
                                company ILIKE %s OR
                                notes ILIKE %s
                            )
                            LIMIT 20
                        """, (user_id, f"%{contact_name}%", f"%{contact_name}%",
                              f"%{contact_name}%", f"%{contact_name}%"))

                        results = [
                            {"id": r[0], "name": r[1], "email": r[2], "type": r[3], "company": r[4]}
                            for r in cur.fetchall()
                        ]

                        return {"success": True, "results": results, "count": len(results)}

        except Exception as e:
            log_with_context(logger, "error", "Relationship tracking failed", error=str(e))
            return {"success": False, "error": str(e)}

    # =========================================================================
    # Followup Scheduling
    # =========================================================================

    def schedule_followup(
        self,
        contact_name: str,
        reason: str,
        due_date: str,
        followup_type: str = "check_in",
        channel: str = "email",
        draft_message: str = None,
        priority: int = 50,
        user_id: str = "1"
    ) -> Dict[str, Any]:
        """
        Schedule a followup with a contact.

        Args:
            contact_name: Who to follow up with
            reason: Why following up
            due_date: When (YYYY-MM-DD)
            followup_type: check_in, thank_you, request, reminder, birthday
            channel: email, call, message
            draft_message: Optional draft message
            priority: 1-100
        """
        try:
            due = datetime.strptime(due_date, "%Y-%m-%d").date()

            with get_conn() as conn:
                with conn.cursor() as cur:
                    # Find relationship
                    cur.execute("""
                        SELECT id FROM jarvis_relationships
                        WHERE user_id = %s AND contact_name ILIKE %s
                        LIMIT 1
                    """, (user_id, f"%{contact_name}%"))
                    rel = cur.fetchone()
                    relationship_id = rel[0] if rel else None

                    # Create followup
                    cur.execute("""
                        INSERT INTO jarvis_followups
                        (user_id, relationship_id, contact_name, reason, followup_type,
                         due_date, channel, draft_message, priority)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                    """, (
                        user_id, relationship_id, contact_name, reason, followup_type,
                        due, channel, draft_message, priority
                    ))
                    followup_id = cur.fetchone()[0]

                    # Update relationship next_followup_date
                    if relationship_id:
                        cur.execute("""
                            UPDATE jarvis_relationships
                            SET next_followup_date = LEAST(next_followup_date, %s)
                            WHERE id = %s
                        """, (due, relationship_id))

                    conn.commit()

                    days_until = (due - date.today()).days

                    return {
                        "success": True,
                        "followup_id": followup_id,
                        "contact": contact_name,
                        "due_date": due_date,
                        "days_until": days_until,
                        "type": followup_type,
                        "channel": channel,
                        "message": f"Followup scheduled: {contact_name} on {due_date} ({days_until} days)"
                    }

        except Exception as e:
            log_with_context(logger, "error", "Followup scheduling failed", error=str(e))
            return {"success": False, "error": str(e)}

    def get_pending_followups(self, days_ahead: int = 7, user_id: str = "1") -> Dict[str, Any]:
        """Get pending followups."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT id, contact_name, reason, followup_type, due_date,
                               channel, priority
                        FROM jarvis_followups
                        WHERE user_id = %s AND status = 'pending'
                          AND due_date <= CURRENT_DATE + %s
                        ORDER BY due_date, priority DESC
                    """, (user_id, days_ahead))

                    followups = []
                    overdue = []
                    today = date.today()

                    for row in cur.fetchall():
                        f = {
                            "id": row[0],
                            "contact": row[1],
                            "reason": row[2],
                            "type": row[3],
                            "due_date": row[4].isoformat(),
                            "channel": row[5],
                            "priority": row[6],
                            "days_until": (row[4] - today).days
                        }
                        followups.append(f)
                        if row[4] < today:
                            overdue.append(f)

                    return {
                        "success": True,
                        "followups": followups,
                        "overdue": overdue,
                        "total": len(followups),
                        "overdue_count": len(overdue)
                    }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_comm_stats(self, period: str = "week", user_id: str = "1") -> Dict[str, Any]:
        """Get communication statistics."""
        try:
            days = {"today": 1, "week": 7, "month": 30}.get(period, 7)

            with get_conn() as conn:
                with conn.cursor() as cur:
                    # Interaction stats
                    cur.execute("""
                        SELECT COUNT(*),
                               COUNT(*) FILTER (WHERE direction = 'outbound'),
                               COUNT(*) FILTER (WHERE direction = 'inbound')
                        FROM jarvis_interactions
                        WHERE user_id = %s AND interaction_date > NOW() - INTERVAL '%s days'
                    """, (user_id, days))
                    interactions = cur.fetchone()

                    # Inbox stats
                    cur.execute("""
                        SELECT COUNT(*) FILTER (WHERE NOT acted_on),
                               COUNT(*) FILTER (WHERE requires_response AND NOT acted_on)
                        FROM jarvis_inbox_items
                        WHERE user_id = %s
                    """, (user_id,))
                    inbox = cur.fetchone()

                    # Relationship stats
                    cur.execute("""
                        SELECT COUNT(*),
                               COUNT(*) FILTER (WHERE last_contact_date > CURRENT_DATE - 30)
                        FROM jarvis_relationships
                        WHERE user_id = %s
                    """, (user_id,))
                    relationships = cur.fetchone()

                    # Pending followups
                    cur.execute("""
                        SELECT COUNT(*) FROM jarvis_followups
                        WHERE user_id = %s AND status = 'pending'
                    """, (user_id,))
                    pending = cur.fetchone()[0]

                    return {
                        "success": True,
                        "period": period,
                        "interactions": {
                            "total": interactions[0],
                            "outbound": interactions[1],
                            "inbound": interactions[2]
                        },
                        "inbox": {
                            "unprocessed": inbox[0],
                            "needs_reply": inbox[1]
                        },
                        "relationships": {
                            "total": relationships[0],
                            "active_last_30d": relationships[1]
                        },
                        "pending_followups": pending
                    }

        except Exception as e:
            return {"success": False, "error": str(e)}


# Singleton
_service: Optional[CommAgentService] = None


def get_comm_agent_service() -> CommAgentService:
    """Get or create comm agent service singleton."""
    global _service
    if _service is None:
        _service = CommAgentService()
    return _service
