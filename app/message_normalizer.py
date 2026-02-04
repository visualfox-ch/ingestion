"""
Message Normalizer for Jarvis.

Provides a unified schema for messages from all sources (WhatsApp, Google Chat, Email, Telegram).
Enables consistent search, pattern detection, and analytics across channels.

Unified Message Schema:
    - id: str                    # Unique message ID (channel + hash)
    - channel: str               # Source channel (whatsapp, google_chat, email, telegram)
    - channel_id: str            # Conversation/thread ID
    - event_ts: str              # ISO timestamp of message
    - ingest_ts: str             # When ingested into system

    - sender_id: str             # Normalized person_id (if linked)
    - sender_name: str           # Display name
    - sender_raw: str            # Original sender string

    - recipient_id: str          # For email: normalized person_id
    - recipient_name: str        # For email: display name
    - recipient_raw: str         # For email: original recipient string

    - subject: str               # For email: subject line
    - text: str                  # Message content
    - text_normalized: str       # Cleaned/normalized text for search

    - language: str              # Detected language (de, en, etc.)
    - word_count: int            # Word count
    - char_count: int            # Character count

    - metadata: dict             # Channel-specific metadata
    - source_path: str           # Original file path
"""
import re
import hashlib
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict

from .observability import get_logger, log_with_context

logger = get_logger("jarvis.normalizer")


@dataclass
class NormalizedMessage:
    """Unified message schema across all channels."""

    # Identity
    id: str
    channel: str
    channel_id: str

    # Timestamps
    event_ts: str
    ingest_ts: str

    # Sender
    sender_id: Optional[str] = None  # Linked person_id
    sender_name: str = ""
    sender_raw: str = ""

    # Recipient (primarily for email)
    recipient_id: Optional[str] = None
    recipient_name: str = ""
    recipient_raw: str = ""

    # Content
    subject: str = ""
    text: str = ""
    text_normalized: str = ""

    # Metadata
    language: str = "de"  # Default German
    word_count: int = 0
    char_count: int = 0

    metadata: Optional[Dict[str, Any]] = None
    source_path: str = ""

    def to_dict(self) -> Dict:
        """Convert to dictionary for storage/API."""
        return asdict(self)


def _compute_message_id(channel: str, event_ts: str, sender: str, text_hash: str) -> str:
    """Generate unique message ID."""
    key = f"{channel}::{event_ts}::{sender}::{text_hash}"
    return hashlib.sha256(key.encode()).hexdigest()[:32]


def _normalize_text(text: str) -> str:
    """
    Normalize text for better search matching.

    - Lowercase
    - Collapse whitespace
    - Remove URLs (keep domain only)
    - Remove special characters but keep umlauts
    """
    if not text:
        return ""

    # Lowercase
    normalized = text.lower()

    # Replace URLs with domain only
    normalized = re.sub(
        r'https?://([^\s/]+)[^\s]*',
        r'[link:\1]',
        normalized
    )

    # Collapse multiple whitespace
    normalized = re.sub(r'\s+', ' ', normalized)

    # Keep alphanumeric, German umlauts, and basic punctuation
    normalized = re.sub(r'[^\w\säöüßÄÖÜ.,!?-]', '', normalized)

    return normalized.strip()


def _detect_language(text: str) -> str:
    """
    Simple language detection based on common words.
    Returns 'de' for German, 'en' for English.
    """
    if not text:
        return "de"

    text_lower = text.lower()

    # German indicators
    german_words = ['ich', 'und', 'der', 'die', 'das', 'ist', 'nicht', 'mit',
                   'für', 'auf', 'auch', 'noch', 'wir', 'aber', 'oder', 'wenn',
                   'schon', 'jetzt', 'danke', 'bitte', 'grüsse', 'liebe']

    # English indicators
    english_words = ['the', 'and', 'is', 'are', 'was', 'were', 'have', 'has',
                    'this', 'that', 'with', 'for', 'you', 'your', 'not', 'but',
                    'thanks', 'please', 'hello', 'dear']

    german_count = sum(1 for w in german_words if f' {w} ' in f' {text_lower} ')
    english_count = sum(1 for w in english_words if f' {w} ' in f' {text_lower} ')

    return "de" if german_count >= english_count else "en"


def _extract_sender_parts(sender_raw: str, channel: str) -> tuple[str, Optional[str]]:
    """
    Extract display name and email from sender string.

    Returns (display_name, email_address)
    """
    if not sender_raw:
        return ("unknown", None)

    # Email format: "Name <email@domain.com>" or just "email@domain.com"
    if channel == "email":
        from email.utils import parseaddr
        name, email_addr = parseaddr(sender_raw)
        if name:
            return (name.strip(), email_addr.lower() if email_addr else None)
        elif email_addr:
            # Use local part of email as name
            local = email_addr.split('@')[0]
            return (local, email_addr.lower())

    # For chat channels, sender is usually just the name
    return (sender_raw.strip(), None)


def normalize_whatsapp_message(msg: Dict, channel_id: str = "") -> NormalizedMessage:
    """Normalize a WhatsApp message to unified schema."""
    text = msg.get("text", "")
    sender_raw = msg.get("sender", "")
    event_ts = msg.get("event_ts", "")

    sender_name, _ = _extract_sender_parts(sender_raw, "whatsapp")
    text_hash = hashlib.md5(text.encode()).hexdigest()[:8]

    return NormalizedMessage(
        id=_compute_message_id("whatsapp", event_ts, sender_raw, text_hash),
        channel="whatsapp",
        channel_id=channel_id or msg.get("channel_id", ""),
        event_ts=event_ts,
        ingest_ts=msg.get("ingest_ts", ""),
        sender_name=sender_name,
        sender_raw=sender_raw,
        text=text,
        text_normalized=_normalize_text(text),
        language=_detect_language(text),
        word_count=len(text.split()) if text else 0,
        char_count=len(text),
        source_path=msg.get("source_path", ""),
        metadata={"original_channel": "whatsapp"}
    )


def normalize_google_chat_message(msg: Dict, channel_id: str = "") -> NormalizedMessage:
    """Normalize a Google Chat message to unified schema."""
    text = msg.get("text", "")
    sender_raw = msg.get("sender", "")
    event_ts = msg.get("event_ts", "")

    sender_name, sender_email = _extract_sender_parts(sender_raw, "google_chat")
    text_hash = hashlib.md5(text.encode()).hexdigest()[:8]

    metadata = {"original_channel": "google_chat"}
    if sender_email:
        metadata["sender_email"] = sender_email

    return NormalizedMessage(
        id=_compute_message_id("google_chat", event_ts, sender_raw, text_hash),
        channel="google_chat",
        channel_id=channel_id or msg.get("channel_id", ""),
        event_ts=event_ts,
        ingest_ts=msg.get("ingest_ts", ""),
        sender_name=sender_name,
        sender_raw=sender_raw,
        text=text,
        text_normalized=_normalize_text(text),
        language=_detect_language(text),
        word_count=len(text.split()) if text else 0,
        char_count=len(text),
        source_path=msg.get("source_path", ""),
        metadata=metadata
    )


def normalize_email_message(msg: Dict, channel_id: str = "") -> NormalizedMessage:
    """Normalize an email message to unified schema."""
    text = msg.get("text", "")
    sender_raw = msg.get("sender", "") or msg.get("sender_email", "")
    recipient_raw = msg.get("recipient", "")
    event_ts = msg.get("event_ts", "")
    subject = msg.get("subject", "")

    sender_name, sender_email = _extract_sender_parts(sender_raw, "email")
    recipient_name, recipient_email = _extract_sender_parts(recipient_raw, "email")

    text_hash = hashlib.md5(text.encode()).hexdigest()[:8]

    metadata = {
        "original_channel": "email",
        "email_id": msg.get("email_id", ""),
        "message_id": msg.get("message_id", "")
    }
    if sender_email:
        metadata["sender_email"] = sender_email
    if recipient_email:
        metadata["recipient_email"] = recipient_email

    return NormalizedMessage(
        id=_compute_message_id("email", event_ts, sender_raw, text_hash),
        channel="email",
        channel_id=channel_id or msg.get("channel_id", ""),
        event_ts=event_ts,
        ingest_ts=msg.get("ingest_ts", ""),
        sender_name=sender_name,
        sender_raw=sender_raw,
        recipient_name=recipient_name,
        recipient_raw=recipient_raw,
        subject=subject,
        text=text,
        text_normalized=_normalize_text(f"{subject} {text}"),  # Include subject in normalized
        language=_detect_language(text),
        word_count=len(text.split()) if text else 0,
        char_count=len(text),
        source_path=msg.get("source_path", ""),
        metadata=metadata
    )


def normalize_telegram_message(msg: Dict, channel_id: str = "") -> NormalizedMessage:
    """Normalize a Telegram message to unified schema."""
    text = msg.get("text", "") or msg.get("message", "")
    sender_raw = msg.get("sender", "") or msg.get("from", "") or msg.get("username", "")
    event_ts = msg.get("event_ts", "") or msg.get("date", "")

    sender_name, _ = _extract_sender_parts(sender_raw, "telegram")
    text_hash = hashlib.md5(text.encode()).hexdigest()[:8]

    return NormalizedMessage(
        id=_compute_message_id("telegram", event_ts, sender_raw, text_hash),
        channel="telegram",
        channel_id=channel_id or msg.get("chat_id", ""),
        event_ts=event_ts,
        ingest_ts=msg.get("ingest_ts", datetime.now().isoformat()),
        sender_name=sender_name,
        sender_raw=sender_raw,
        text=text,
        text_normalized=_normalize_text(text),
        language=_detect_language(text),
        word_count=len(text.split()) if text else 0,
        char_count=len(text),
        source_path=msg.get("source_path", ""),
        metadata={"original_channel": "telegram", "chat_id": msg.get("chat_id", "")}
    )


def normalize_message(msg: Dict, channel: str = None, channel_id: str = "") -> NormalizedMessage:
    """
    Auto-detect channel and normalize message.

    Args:
        msg: Raw message dict from any parser
        channel: Override channel detection
        channel_id: Override channel_id

    Returns:
        NormalizedMessage instance
    """
    # Detect channel if not specified
    detected_channel = channel or msg.get("channel", "")

    if detected_channel == "whatsapp":
        return normalize_whatsapp_message(msg, channel_id)
    elif detected_channel == "google_chat":
        return normalize_google_chat_message(msg, channel_id)
    elif detected_channel == "email":
        return normalize_email_message(msg, channel_id)
    elif detected_channel == "telegram":
        return normalize_telegram_message(msg, channel_id)
    else:
        # Fallback: use generic normalization
        log_with_context(logger, "warning", "Unknown channel, using generic normalization",
                        channel=detected_channel)
        return normalize_whatsapp_message(msg, channel_id)  # WhatsApp has minimal fields


def normalize_messages(messages: List[Dict], channel: str = None, channel_id: str = "") -> List[NormalizedMessage]:
    """Normalize a batch of messages."""
    return [normalize_message(msg, channel, channel_id) for msg in messages]


def link_sender_to_person(
    normalized: NormalizedMessage,
    person_id: str,
    is_recipient: bool = False
) -> NormalizedMessage:
    """
    Link a normalized message's sender or recipient to a person_id.

    Args:
        normalized: The normalized message
        person_id: The person_id to link
        is_recipient: If True, link recipient instead of sender

    Returns:
        Updated NormalizedMessage
    """
    if is_recipient:
        normalized.recipient_id = person_id
    else:
        normalized.sender_id = person_id
    return normalized


# ============ Analytics Helpers ============

def get_message_stats(messages: List[NormalizedMessage]) -> Dict:
    """
    Compute statistics for a batch of normalized messages.
    """
    if not messages:
        return {"count": 0}

    total_words = sum(m.word_count for m in messages)
    total_chars = sum(m.char_count for m in messages)

    # Count by channel
    by_channel = {}
    for m in messages:
        by_channel[m.channel] = by_channel.get(m.channel, 0) + 1

    # Count by language
    by_language = {}
    for m in messages:
        by_language[m.language] = by_language.get(m.language, 0) + 1

    # Count by sender
    by_sender = {}
    for m in messages:
        by_sender[m.sender_name] = by_sender.get(m.sender_name, 0) + 1

    # Top senders
    top_senders = sorted(by_sender.items(), key=lambda x: -x[1])[:10]

    return {
        "count": len(messages),
        "total_words": total_words,
        "total_chars": total_chars,
        "avg_words": total_words / len(messages),
        "avg_chars": total_chars / len(messages),
        "by_channel": by_channel,
        "by_language": by_language,
        "top_senders": dict(top_senders),
        "unique_senders": len(by_sender)
    }


def search_normalized(
    messages: List[NormalizedMessage],
    query: str,
    channel: str = None,
    sender: str = None,
    language: str = None,
    limit: int = 50
) -> List[NormalizedMessage]:
    """
    Simple search over normalized messages.

    For production use, rely on Qdrant/Meilisearch instead.
    This is for quick in-memory filtering.
    """
    query_lower = query.lower()
    results = []

    for m in messages:
        # Apply filters
        if channel and m.channel != channel:
            continue
        if sender and sender.lower() not in m.sender_name.lower():
            continue
        if language and m.language != language:
            continue

        # Search in normalized text
        if query_lower in m.text_normalized:
            results.append(m)
            if len(results) >= limit:
                break

    return results
