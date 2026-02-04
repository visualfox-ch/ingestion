"""
Email parser for Jarvis ingestion pipeline.

Supports:
- .eml files (single email, RFC 822)
- .mbox files (multiple emails)
- JSON exports (e.g., from Gmail Takeout)
"""
import email
import json
import hashlib
import re
from email import policy
from email.utils import parseaddr, parsedate_to_datetime
from datetime import datetime
from typing import Dict, List, Optional
import mailbox


def _compute_email_id(from_addr: str, to_addr: str, subject: str, date: str) -> str:
    """Compute a deterministic ID for an email."""
    key = f"{from_addr}::{to_addr}::{subject}::{date}"
    return hashlib.sha256(key.encode()).hexdigest()[:32]


def _extract_email_body(msg) -> str:
    """Extract plain text body from email message."""
    body = ""

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition", ""))

            # Skip attachments
            if "attachment" in content_disposition:
                continue

            if content_type == "text/plain":
                try:
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        body = payload.decode(charset, errors="replace")
                        break
                except Exception:
                    continue
            elif content_type == "text/html" and not body:
                # Fall back to HTML if no plain text
                try:
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        html = payload.decode(charset, errors="replace")
                        # Strip HTML tags (basic)
                        body = re.sub(r'<[^>]+>', '', html)
                        body = re.sub(r'\s+', ' ', body).strip()
                except Exception:
                    continue
    else:
        try:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or "utf-8"
                body = payload.decode(charset, errors="replace")
        except Exception:
            body = str(msg.get_payload())

    return body.strip()


def _extract_channel_id(from_addr: str, to_addr: str, source_path: str) -> str:
    """
    Extract a unique channel ID for email thread tracking.
    Uses sender+recipient to group conversations.
    """
    import os

    # Normalize email addresses
    _, from_email = parseaddr(from_addr)
    _, to_email = parseaddr(to_addr)

    if from_email and to_email:
        # Sort to make it bidirectional (A->B same as B->A)
        participants = sorted([from_email.lower(), to_email.lower()])
        channel = "_".join(participants)
        # Hash if too long
        if len(channel) > 50:
            channel = hashlib.md5(channel.encode()).hexdigest()[:16]
        return f"email_{channel}"

    # Fallback to filename
    filename = os.path.basename(source_path).replace(".eml", "").replace(".mbox", "")
    normalized = re.sub(r'[^a-z0-9]+', '_', filename.lower()).strip('_')
    return f"email_{normalized}"


def parse_eml(content: str, source_path: str, ingest_ts: str) -> Dict:
    """
    Parse a single .eml file.

    Returns dict with channel, channel_id, source_path, and messages list.
    """
    msg = email.message_from_string(content, policy=policy.default)

    from_addr = msg.get("From", "")
    to_addr = msg.get("To", "")
    subject = msg.get("Subject", "(no subject)")
    date_str = msg.get("Date", "")
    message_id = msg.get("Message-ID", "")

    # Parse date
    event_ts = ""
    try:
        if date_str:
            dt = parsedate_to_datetime(date_str)
            event_ts = dt.isoformat()
    except Exception:
        event_ts = ingest_ts

    # Extract body
    body = _extract_email_body(msg)

    # Get sender name
    sender_name, sender_email = parseaddr(from_addr)
    sender = sender_name if sender_name else sender_email

    channel_id = _extract_channel_id(from_addr, to_addr, source_path)

    messages = [{
        "event_ts": event_ts,
        "ingest_ts": ingest_ts,
        "sender": sender,
        "sender_email": sender_email,
        "recipient": to_addr,
        "subject": subject,
        "text": body,
        "message_id": message_id,
        "source_path": source_path,
        "channel": "email",
        "email_id": _compute_email_id(from_addr, to_addr, subject, event_ts)
    }]

    return {
        "channel": "email",
        "channel_id": channel_id,
        "source_path": source_path,
        "messages": messages
    }


def parse_mbox(content: str, source_path: str, ingest_ts: str) -> Dict:
    """
    Parse an .mbox file containing multiple emails.

    Note: This writes to a temp file since mailbox needs a file path.
    """
    import tempfile
    import os

    messages = []
    channel_ids = set()

    # Write to temp file for mailbox parsing
    with tempfile.NamedTemporaryFile(mode='w', suffix='.mbox', delete=False) as f:
        f.write(content)
        temp_path = f.name

    try:
        mbox = mailbox.mbox(temp_path)

        for msg in mbox:
            from_addr = msg.get("From", "")
            to_addr = msg.get("To", "")
            subject = msg.get("Subject", "(no subject)")
            date_str = msg.get("Date", "")
            message_id = msg.get("Message-ID", "")

            # Parse date
            event_ts = ""
            try:
                if date_str:
                    dt = parsedate_to_datetime(date_str)
                    event_ts = dt.isoformat()
            except Exception:
                event_ts = ingest_ts

            # Extract body
            body = _extract_email_body(msg)

            if not body:
                continue

            # Get sender name
            sender_name, sender_email = parseaddr(from_addr)
            sender = sender_name if sender_name else sender_email

            channel_id = _extract_channel_id(from_addr, to_addr, source_path)
            channel_ids.add(channel_id)

            messages.append({
                "event_ts": event_ts,
                "ingest_ts": ingest_ts,
                "sender": sender,
                "sender_email": sender_email,
                "recipient": to_addr,
                "subject": subject,
                "text": body,
                "message_id": message_id,
                "source_path": source_path,
                "channel": "email",
                "email_id": _compute_email_id(from_addr, to_addr, subject, event_ts)
            })

        mbox.close()
    finally:
        os.unlink(temp_path)

    # Use first channel_id or derive from filename
    primary_channel_id = list(channel_ids)[0] if channel_ids else _extract_channel_id("", "", source_path)

    return {
        "channel": "email",
        "channel_id": primary_channel_id,
        "source_path": source_path,
        "messages": messages,
        "unique_threads": len(channel_ids)
    }


def parse_email_json(content: str, source_path: str, ingest_ts: str) -> Dict:
    """
    Parse JSON email export (e.g., from Gmail Takeout or custom export).

    Expected format:
    {
        "emails": [
            {
                "from": "sender@example.com",
                "to": "recipient@example.com",
                "subject": "...",
                "date": "2024-01-15T10:30:00Z",
                "body": "..."
            }
        ]
    }

    Or a list of email objects directly.
    """
    data = json.loads(content)

    # Handle both formats
    if isinstance(data, dict):
        emails = data.get("emails") or data.get("messages") or []
    elif isinstance(data, list):
        emails = data
    else:
        emails = []

    messages = []
    channel_ids = set()

    for em in emails:
        if not isinstance(em, dict):
            continue

        from_addr = em.get("from") or em.get("sender") or ""
        to_addr = em.get("to") or em.get("recipient") or ""
        subject = em.get("subject") or "(no subject)"
        date_str = em.get("date") or em.get("timestamp") or ""
        body = em.get("body") or em.get("text") or em.get("content") or ""
        message_id = em.get("message_id") or em.get("id") or ""

        if not body:
            continue

        # Parse date
        event_ts = ""
        try:
            if date_str:
                if "T" in date_str:
                    dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                    event_ts = dt.isoformat()
                else:
                    event_ts = date_str
        except Exception:
            event_ts = ingest_ts

        # Get sender name
        sender_name, sender_email = parseaddr(from_addr)
        sender = sender_name if sender_name else sender_email

        channel_id = _extract_channel_id(from_addr, to_addr, source_path)
        channel_ids.add(channel_id)

        messages.append({
            "event_ts": event_ts,
            "ingest_ts": ingest_ts,
            "sender": sender,
            "sender_email": sender_email,
            "recipient": to_addr,
            "subject": subject,
            "text": body,
            "message_id": message_id,
            "source_path": source_path,
            "channel": "email",
            "email_id": _compute_email_id(from_addr, to_addr, subject, event_ts)
        })

    primary_channel_id = list(channel_ids)[0] if channel_ids else _extract_channel_id("", "", source_path)

    return {
        "channel": "email",
        "channel_id": primary_channel_id,
        "source_path": source_path,
        "messages": messages,
        "unique_threads": len(channel_ids)
    }


def parse_email_file(content: str, source_path: str, ingest_ts: str) -> Dict:
    """
    Auto-detect email format and parse accordingly.
    """
    filename = source_path.lower()

    if filename.endswith(".json"):
        return parse_email_json(content, source_path, ingest_ts)
    elif filename.endswith(".mbox"):
        return parse_mbox(content, source_path, ingest_ts)
    elif filename.endswith(".eml"):
        return parse_eml(content, source_path, ingest_ts)
    else:
        # Try to auto-detect
        content_stripped = content.strip()
        if content_stripped.startswith("{") or content_stripped.startswith("["):
            return parse_email_json(content, source_path, ingest_ts)
        elif "From " in content[:100] and "\nFrom:" in content:
            return parse_mbox(content, source_path, ingest_ts)
        else:
            return parse_eml(content, source_path, ingest_ts)


def window_messages(messages: List[Dict], window_size: int = 5, step: int = 3, source_path: str = "") -> List[Dict]:
    """
    Create windows of email messages for embedding.
    Each window contains related emails (same thread or time proximity).
    """
    windows = []
    i = 0
    n = len(messages)

    while i < n:
        chunk_msgs = messages[i:i+window_size]
        if not chunk_msgs:
            break

        # Build window text with email context
        parts = []
        for m in chunk_msgs:
            header = f"From: {m['sender']}"
            if m.get('subject'):
                header += f" | Subject: {m['subject']}"
            parts.append(f"{header}\n{m['text']}")

        joined = "\n---\n".join(parts)
        ts_start = chunk_msgs[0].get("event_ts", "")
        ts_end = chunk_msgs[-1].get("event_ts", "")
        msg_count = len(chunk_msgs)

        # Compute deterministic window hash
        key = f"{source_path}::email::{ts_start}::{ts_end}::{msg_count}"
        window_hash = hashlib.sha256(key.encode()).hexdigest()[:32]

        windows.append({
            "text": joined,
            "event_ts_start": ts_start,
            "event_ts_end": ts_end,
            "message_count": msg_count,
            "window_hash": window_hash,
        })
        i += step

    return windows
