"""
Notification Service Module

Phase 16.4B: Proactive Notification System
Handles sending, rate limiting, and tracking of notifications across channels.
"""

from typing import Optional, List, Dict, Any
from datetime import datetime, time
import json
import uuid
import requests

from .observability import get_logger
from .db_safety import safe_list_query, safe_write_query

logger = get_logger("jarvis.notifications")


# =============================================================================
# CONFIGURATION
# =============================================================================

TELEGRAM_BOT_TOKEN = None  # Will be loaded from config
TELEGRAM_CHAT_ID = None    # Will be loaded from config

# Channel handlers
CHANNEL_HANDLERS = {
    'telegram': 'send_telegram_notification',
    'email': 'send_email_notification',
    'dashboard': 'send_dashboard_notification',
}


# =============================================================================
# TEMPLATE RENDERING
# =============================================================================

def render_template(template: str, context: Dict[str, Any]) -> str:
    """
    Render a notification template with context variables.

    Simple {variable} replacement.
    """
    if not template:
        return ""

    result = template
    for key, value in context.items():
        result = result.replace(f"{{{key}}}", str(value) if value else "")

    return result


async def get_template(template_key: str) -> Optional[Dict[str, Any]]:
    """
    Get a notification template by key.
    """
    try:
        with safe_list_query('notification_templates') as cur:
            cur.execute("""
                SELECT template_key, name, telegram_template, email_subject_template,
                       email_body_template, dashboard_template, default_priority
                FROM notification_templates
                WHERE template_key = %s AND is_active = true
            """, (template_key,))
            row = cur.fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.error(f"Failed to get template {template_key}: {e}")
        return None


# =============================================================================
# RATE LIMITING
# =============================================================================

async def check_rate_limit(user_id: str, channel: str, priority: int = 3) -> tuple[bool, Optional[str]]:
    """
    Check if notification can be sent based on rate limits.

    Returns:
        (allowed: bool, skip_reason: Optional[str])

    Priority 1 (urgent) bypasses rate limits.
    """
    # Urgent notifications bypass rate limits
    if priority == 1:
        return True, None

    try:
        with safe_list_query('user_notification_preferences') as cur:
            # Check using the database function
            cur.execute("""
                SELECT check_notification_rate_limit(%s, %s) as allowed
            """, (user_id, channel))
            result = cur.fetchone()

            if result and result['allowed']:
                return True, None

            # Determine why it was blocked
            cur.execute("""
                SELECT quiet_hours_enabled, quiet_hours_start, quiet_hours_end,
                       max_notifications_per_hour, max_notifications_per_day
                FROM user_notification_preferences
                WHERE user_id = %s
            """, (user_id,))
            prefs = cur.fetchone()

            if prefs:
                current_time = datetime.now().time()
                if prefs['quiet_hours_enabled']:
                    start = prefs['quiet_hours_start']
                    end = prefs['quiet_hours_end']
                    if start < end:
                        if start <= current_time <= end:
                            return False, 'quiet_hours'
                    else:
                        if current_time >= start or current_time <= end:
                            return False, 'quiet_hours'

            return False, 'rate_limit'

    except Exception as e:
        logger.error(f"Rate limit check failed: {e}")
        # Allow on error to prevent blocking notifications
        return True, None


async def check_duplicate(user_id: str, event_type: str, event_id: str, window_minutes: int = 30) -> Optional[str]:
    """
    Check if a similar notification was sent recently.

    Returns the ID of the duplicate notification if found.
    """
    try:
        with safe_list_query('notification_log') as cur:
            cur.execute("""
                SELECT id FROM notification_log
                WHERE user_id = %s
                  AND event_type = %s
                  AND event_id = %s
                  AND status = 'sent'
                  AND created_at > NOW() - INTERVAL '%s minutes'
                ORDER BY created_at DESC
                LIMIT 1
            """, (user_id, event_type, event_id, window_minutes))
            row = cur.fetchone()
            return str(row['id']) if row else None
    except Exception as e:
        logger.error(f"Duplicate check failed: {e}")
        return None


# =============================================================================
# CHANNEL HANDLERS
# =============================================================================

async def send_telegram_notification(
    user_id: str,
    title: str,
    body: str,
    action_buttons: List[Dict] = None,
    context: Dict = None,
    notification_id: str = None
) -> bool:
    """
    Send notification via Telegram.

    Returns True if sent successfully.
    """
    try:
        # Build message
        message = title
        if body:
            message = f"{title}\n\n{body}"

        # Build request payload
        payload = {
            "message": message,
            "parse_mode": "Markdown"
        }

        # Include notification_id for inline button generation
        if notification_id:
            payload["notification_id"] = notification_id
            payload["event_type"] = context.get('event_type') if context else None

        # Or use custom action buttons
        elif action_buttons:
            keyboard = []
            for btn in action_buttons:
                keyboard.append([{
                    "text": btn.get('label', 'Action'),
                    "callback_data": f"notification:{btn.get('action', 'noop')}:{context.get('event_id', '')}"
                }])
            payload["reply_markup"] = {"inline_keyboard": keyboard}

        # Use Jarvis API to send (it has Telegram integration)
        response = requests.post(
            "http://localhost:18000/notify/telegram",
            json=payload,
            timeout=10
        )

        return response.status_code == 200

    except Exception as e:
        logger.error(f"Telegram notification failed: {e}")
        return False


async def send_email_notification(
    user_id: str,
    title: str,
    body: str,
    subject: str = None,
    context: Dict = None
) -> bool:
    """
    Send notification via Email.

    Returns True if sent successfully.
    """
    try:
        # Use n8n webhook for email sending
        response = requests.post(
            "http://192.168.1.103:25678/webhook/send-email",
            json={
                "to": context.get('email', 'michael@projektil.ch'),
                "subject": subject or title,
                "body": body,
                "is_html": True
            },
            timeout=30
        )

        return response.status_code == 200

    except Exception as e:
        logger.error(f"Email notification failed: {e}")
        return False


async def send_dashboard_notification(
    user_id: str,
    title: str,
    body: str,
    action_buttons: List[Dict] = None,
    context: Dict = None
) -> bool:
    """
    Store notification for dashboard display.

    Dashboard will poll /notifications/pending to get these.
    """
    # Already stored in notification_log, just return True
    return True


# =============================================================================
# MAIN SEND FUNCTION
# =============================================================================

async def send_notification(
    user_id: str,
    event_type: str,
    event_id: str,
    context: Dict[str, Any] = None,
    priority: int = 3,
    channels: List[str] = None
) -> Dict[str, Any]:
    """
    Send a notification to a user.

    Args:
        user_id: User identifier
        event_type: Type of event (matches template_key)
        event_id: ID of the triggering object
        context: Data for template rendering
        priority: 1=urgent, 2=high, 3=normal, 4=low
        channels: Override channels (default: from user preferences)

    Returns:
        {status, channels_sent, notification_ids, skipped}
    """
    context = context or {}
    result = {
        "status": "sent",
        "channels_sent": [],
        "notification_ids": [],
        "skipped": []
    }

    try:
        # Get template
        template = await get_template(event_type)
        if not template:
            logger.warning(f"No template found for event type: {event_type}")
            template = {
                "telegram_template": "{title}\n\n{body}",
                "email_subject_template": "{title}",
                "email_body_template": "{body}",
                "dashboard_template": "{title}",
                "default_priority": priority
            }

        # Get user preferences
        prefs = await get_user_preferences(user_id)

        # Determine channels
        if channels is None:
            channels = []
            if prefs.get('telegram_enabled', True):
                channels.append('telegram')
            if prefs.get('email_enabled', True) and priority <= 2:
                channels.append('email')
            if prefs.get('dashboard_enabled', True):
                channels.append('dashboard')

        # Check for duplicate
        duplicate_id = await check_duplicate(user_id, event_type, event_id)

        for channel in channels:
            notification_id = str(uuid.uuid4())

            # Check rate limit
            allowed, skip_reason = await check_rate_limit(user_id, channel, priority)

            if not allowed:
                # Log as skipped
                await log_notification(
                    notification_id=notification_id,
                    user_id=user_id,
                    event_type=event_type,
                    event_id=event_id,
                    channel=channel,
                    title=context.get('title', event_type),
                    body=context.get('body', ''),
                    status='skipped',
                    skip_reason=skip_reason,
                    priority=priority
                )
                result["skipped"].append({"channel": channel, "reason": skip_reason})
                continue

            if duplicate_id:
                # Log as duplicate
                await log_notification(
                    notification_id=notification_id,
                    user_id=user_id,
                    event_type=event_type,
                    event_id=event_id,
                    channel=channel,
                    title=context.get('title', event_type),
                    body=context.get('body', ''),
                    status='skipped',
                    skip_reason='duplicate',
                    is_duplicate=True,
                    duplicate_of=duplicate_id,
                    priority=priority
                )
                result["skipped"].append({"channel": channel, "reason": "duplicate"})
                continue

            # Render content
            if channel == 'telegram':
                title = render_template(template.get('telegram_template', '{title}'), context)
                body = ""
            elif channel == 'email':
                title = render_template(template.get('email_subject_template', '{title}'), context)
                body = render_template(template.get('email_body_template', '{body}'), context)
            else:
                title = render_template(template.get('dashboard_template', '{title}'), context)
                body = context.get('body', '')

            # Build action buttons
            action_buttons = context.get('action_buttons', [])

            # Send notification
            success = False
            if channel == 'telegram':
                success = await send_telegram_notification(
                    user_id, title, body, action_buttons,
                    {**context, 'event_id': event_id, 'event_type': event_type},
                    notification_id=notification_id
                )
            elif channel == 'email':
                success = await send_email_notification(user_id, title, body, title, context)
            elif channel == 'dashboard':
                success = await send_dashboard_notification(user_id, title, body, action_buttons, context)

            # Log result
            status = 'sent' if success else 'failed'
            await log_notification(
                notification_id=notification_id,
                user_id=user_id,
                event_type=event_type,
                event_id=event_id,
                channel=channel,
                title=title,
                body=body,
                status=status,
                action_buttons=action_buttons,
                priority=priority
            )

            if success:
                result["channels_sent"].append(channel)
                result["notification_ids"].append(notification_id)
            else:
                result["skipped"].append({"channel": channel, "reason": "send_failed"})

        if not result["channels_sent"]:
            result["status"] = "skipped"

        return result

    except Exception as e:
        logger.error(f"Failed to send notification: {e}")
        return {"status": "error", "error": str(e)}


# =============================================================================
# DATABASE OPERATIONS
# =============================================================================

async def log_notification(
    notification_id: str,
    user_id: str,
    event_type: str,
    event_id: str,
    channel: str,
    title: str,
    body: str,
    status: str,
    action_buttons: List[Dict] = None,
    skip_reason: str = None,
    is_duplicate: bool = False,
    duplicate_of: str = None,
    priority: int = 3
) -> bool:
    """
    Log notification to database.
    """
    try:
        with safe_write_query('notification_log') as cur:
            cur.execute("""
                INSERT INTO notification_log (
                    id, user_id, event_type, event_id, channel,
                    title, body, action_buttons, status, priority,
                    skip_reason, is_duplicate, duplicate_of,
                    sent_at
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    CASE WHEN %s = 'sent' THEN NOW() ELSE NULL END
                )
            """, (
                notification_id, user_id, event_type, event_id, channel,
                title, body, json.dumps(action_buttons) if action_buttons else None, status, priority,
                skip_reason, is_duplicate, duplicate_of,
                status
            ))
            return True
    except Exception as e:
        logger.error(f"Failed to log notification: {e}")
        return False


async def get_pending_notifications(user_id: str = None, limit: int = 20) -> List[Dict[str, Any]]:
    """
    Get unread dashboard notifications.
    """
    try:
        with safe_list_query('notification_log') as cur:
            if user_id:
                cur.execute("""
                    SELECT id, event_type, event_id, title, body, action_buttons,
                           priority, created_at
                    FROM notification_log
                    WHERE user_id = %s
                      AND channel = 'dashboard'
                      AND status = 'sent'
                      AND read_at IS NULL
                    ORDER BY priority ASC, created_at DESC
                    LIMIT %s
                """, (user_id, limit))
            else:
                cur.execute("""
                    SELECT id, user_id, event_type, event_id, title, body, action_buttons,
                           priority, created_at
                    FROM notification_log
                    WHERE channel = 'dashboard'
                      AND status = 'sent'
                      AND read_at IS NULL
                    ORDER BY priority ASC, created_at DESC
                    LIMIT %s
                """, (limit,))

            rows = cur.fetchall()
            return [
                {
                    "id": str(row["id"]),
                    "user_id": row.get("user_id"),
                    "type": row["event_type"],
                    "event_id": row["event_id"],
                    "title": row["title"],
                    "body": row["body"],
                    "action_buttons": json.loads(row["action_buttons"]) if row["action_buttons"] else [],
                    "priority": row["priority"],
                    "created_at": row["created_at"].isoformat() if row["created_at"] else None
                }
                for row in rows
            ]
    except Exception as e:
        logger.error(f"Failed to get pending notifications: {e}")
        return []


async def mark_notification_read(notification_id: str) -> bool:
    """
    Mark a notification as read.
    """
    try:
        with safe_write_query('notification_log') as cur:
            cur.execute("""
                UPDATE notification_log
                SET read_at = NOW(), status = 'read'
                WHERE id = %s
            """, (notification_id,))
            return cur.rowcount > 0
    except Exception as e:
        logger.error(f"Failed to mark notification read: {e}")
        return False


async def snooze_notification(
    notification_id: str,
    user_id: str = "micha",
    snooze_hours: int = 2
) -> Optional[str]:
    """
    Snooze a notification and create a follow-up reminder.

    Phase 16.4E: Snooze → Follow-up
    Returns the follow-up notification ID if successful.
    """
    from datetime import timedelta

    try:
        # 1. Get original notification details
        original = None
        with safe_list_query('notification_log') as cur:
            cur.execute("""
                SELECT event_type, title, body, channel
                FROM notification_log
                WHERE id = %s
            """, (notification_id,))
            original = cur.fetchone()

        if not original:
            logger.warning(f"Notification {notification_id} not found for snooze")
            return None

        # 2. Mark original as snoozed
        with safe_write_query('notification_log') as cur:
            cur.execute("""
                UPDATE notification_log
                SET status = 'snoozed', read_at = NOW()
                WHERE id = %s
            """, (notification_id,))

        # 3. Create follow-up notification
        # Store scheduled time in title prefix for now
        followup_id = str(uuid.uuid4())
        scheduled_at = datetime.utcnow() + timedelta(hours=snooze_hours)
        followup_title = f"⏰ Erinnerung: {original['title'] or 'Snoozed notification'}"
        followup_body = f"[Geplant für: {scheduled_at.strftime('%Y-%m-%d %H:%M')} UTC]\n\n{original['body'] or ''}"

        with safe_write_query('notification_log') as cur:
            cur.execute("""
                INSERT INTO notification_log (
                    id, user_id, event_type, title, body,
                    channel, status
                ) VALUES (%s, %s, %s, %s, %s, %s, 'pending')
            """, (
                followup_id,
                user_id,
                'snoozed_followup',
                followup_title,
                followup_body,
                original['channel'] or 'telegram'
            ))

        logger.info(f"Created follow-up {followup_id} for snoozed notification {notification_id}")
        return followup_id

    except Exception as e:
        logger.error(f"Failed to snooze notification: {e}")
        return None


async def get_user_preferences(user_id: str) -> Dict[str, Any]:
    """
    Get user notification preferences.
    """
    try:
        with safe_list_query('user_notification_preferences') as cur:
            cur.execute("""
                SELECT * FROM user_notification_preferences
                WHERE user_id = %s
            """, (user_id,))
            row = cur.fetchone()
            if row:
                return dict(row)
            else:
                # Return defaults
                return {
                    "telegram_enabled": True,
                    "email_enabled": True,
                    "dashboard_enabled": True,
                    "quiet_hours_enabled": False
                }
    except Exception as e:
        logger.error(f"Failed to get user preferences: {e}")
        return {}


async def update_user_preferences(user_id: str, **kwargs) -> bool:
    """
    Update user notification preferences.
    """
    try:
        # Build update query dynamically
        allowed_fields = [
            'telegram_enabled', 'email_enabled', 'dashboard_enabled', 'push_enabled',
            'max_notifications_per_hour', 'max_notifications_per_day',
            'quiet_hours_enabled', 'quiet_hours_start', 'quiet_hours_end',
            'remediation_alerts', 'followup_reminders', 'vip_notifications',
            'digest_enabled', 'digest_frequency', 'digest_time'
        ]

        updates = {k: v for k, v in kwargs.items() if k in allowed_fields and v is not None}

        if not updates:
            return True

        set_clause = ", ".join([f"{k} = %s" for k in updates.keys()])
        values = list(updates.values()) + [user_id]

        with safe_write_query('user_notification_preferences') as cur:
            cur.execute(f"""
                INSERT INTO user_notification_preferences (user_id, {', '.join(updates.keys())})
                VALUES (%s, {', '.join(['%s'] * len(updates))})
                ON CONFLICT (user_id) DO UPDATE SET {set_clause}, updated_at = NOW()
            """, [user_id] + list(updates.values()) + list(updates.values()))
            return True

    except Exception as e:
        logger.error(f"Failed to update user preferences: {e}")
        return False


# =============================================================================
# NOTIFICATION STATS
# =============================================================================

async def get_notification_stats(user_id: str = None, days: int = 7) -> Dict[str, Any]:
    """
    Get notification statistics.
    """
    try:
        with safe_list_query('notification_log') as cur:
            # Total sent
            if user_id:
                cur.execute("""
                    SELECT
                        COUNT(*) FILTER (WHERE status = 'sent') as total_sent,
                        COUNT(*) FILTER (WHERE status = 'read') as total_read,
                        COUNT(*) FILTER (WHERE status = 'skipped') as total_skipped,
                        COUNT(*) FILTER (WHERE status = 'failed') as total_failed
                    FROM notification_log
                    WHERE user_id = %s
                      AND created_at > NOW() - INTERVAL '%s days'
                """, (user_id, days))
            else:
                cur.execute("""
                    SELECT
                        COUNT(*) FILTER (WHERE status = 'sent') as total_sent,
                        COUNT(*) FILTER (WHERE status = 'read') as total_read,
                        COUNT(*) FILTER (WHERE status = 'skipped') as total_skipped,
                        COUNT(*) FILTER (WHERE status = 'failed') as total_failed
                    FROM notification_log
                    WHERE created_at > NOW() - INTERVAL '%s days'
                """, (days,))

            stats = cur.fetchone()

            # By channel
            cur.execute("""
                SELECT channel, COUNT(*) as count
                FROM notification_log
                WHERE status = 'sent'
                  AND created_at > NOW() - INTERVAL '%s days'
                GROUP BY channel
            """, (days,))
            by_channel = {row['channel']: row['count'] for row in cur.fetchall()}

            return {
                "total_sent": stats['total_sent'] or 0,
                "total_read": stats['total_read'] or 0,
                "total_skipped": stats['total_skipped'] or 0,
                "total_failed": stats['total_failed'] or 0,
                "read_rate": (stats['total_read'] / stats['total_sent'] * 100) if stats['total_sent'] else 0,
                "by_channel": by_channel,
                "period_days": days
            }

    except Exception as e:
        logger.error(f"Failed to get notification stats: {e}")
        return {}
