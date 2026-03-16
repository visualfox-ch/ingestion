"""
Telegram Chat History Parser

Parses Telegram JSON export format (from Telegram Desktop > Export Chat History).
Supports:
- Individual chats
- Group chats
- Channels
- Media metadata (photos, videos, documents)
"""

import json
import hashlib
from datetime import datetime
from typing import List, Dict, Any, Optional, Iterator
from pathlib import Path

from .observability import get_logger, log_with_context

logger = get_logger("jarvis.chat_telegram")


def parse_telegram_json(file_path: str) -> List[Dict[str, Any]]:
    """
    Parse a Telegram JSON export file.

    Args:
        file_path: Path to result.json from Telegram export

    Returns:
        List of message dicts with: sender, text, timestamp, message_id, media_type
    """
    messages = []

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Get chat metadata
        chat_name = data.get("name", "Unknown Chat")
        chat_type = data.get("type", "personal_chat")  # personal_chat, private_group, public_channel, etc.
        chat_id = data.get("id", 0)

        log_with_context(logger, "info", "Parsing Telegram export",
                        chat_name=chat_name, chat_type=chat_type)

        for msg in data.get("messages", []):
            # Skip service messages (joins, leaves, etc.)
            if msg.get("type") != "message":
                continue

            # Extract sender
            sender = msg.get("from", msg.get("actor", "Unknown"))
            if isinstance(sender, dict):
                sender = sender.get("name", "Unknown")

            # Extract text - can be string or list of text entities
            text_raw = msg.get("text", "")
            if isinstance(text_raw, list):
                # Handle formatted text (bold, links, etc.)
                text_parts = []
                for part in text_raw:
                    if isinstance(part, str):
                        text_parts.append(part)
                    elif isinstance(part, dict):
                        text_parts.append(part.get("text", ""))
                text = "".join(text_parts)
            else:
                text = str(text_raw)

            # Skip empty messages (media-only with no caption)
            if not text.strip():
                # Check if it's media
                media_type = msg.get("media_type")
                if media_type:
                    text = f"[{media_type}]"
                else:
                    continue

            # Parse timestamp
            date_str = msg.get("date", "")
            try:
                timestamp = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            except:
                timestamp = datetime.now()

            # Extract media info if present
            media_type = msg.get("media_type")
            file_name = msg.get("file", msg.get("photo", ""))
            if isinstance(file_name, dict):
                file_name = file_name.get("file_name", "")

            messages.append({
                "sender": sender,
                "text": text.strip(),
                "timestamp": timestamp.isoformat(),
                "message_id": msg.get("id", 0),
                "chat_name": chat_name,
                "chat_type": chat_type,
                "chat_id": chat_id,
                "media_type": media_type,
                "file_name": file_name if file_name else None,
                "reply_to": msg.get("reply_to_message_id"),
                "forwarded_from": msg.get("forwarded_from"),
            })

        log_with_context(logger, "info", "Telegram parsing complete",
                        messages_parsed=len(messages))

    except Exception as e:
        log_with_context(logger, "error", "Failed to parse Telegram export",
                        file_path=file_path, error=str(e))

    return messages


def window_messages(
    messages: List[Dict[str, Any]],
    window_size: int = 10,
    overlap: int = 8
) -> Iterator[Dict[str, Any]]:
    """
    Create overlapping windows of messages for embedding.

    Args:
        messages: Parsed messages (sorted by timestamp)
        window_size: Number of messages per window
        overlap: Number of messages to overlap between windows

    Yields:
        Window dicts with combined text and metadata
    """
    if not messages:
        return

    # Sort by timestamp
    sorted_msgs = sorted(messages, key=lambda x: x.get("timestamp", ""))

    step = window_size - overlap
    if step < 1:
        step = 1

    for i in range(0, len(sorted_msgs), step):
        window = sorted_msgs[i:i + window_size]
        if not window:
            continue

        # Build combined text
        lines = []
        for msg in window:
            sender = msg.get("sender", "?")
            text = msg.get("text", "")
            media = f" [{msg['media_type']}]" if msg.get("media_type") else ""
            lines.append(f"{sender}: {text}{media}")

        combined_text = "\n".join(lines)

        # Create content hash for deduplication
        content_hash = hashlib.sha256(combined_text.encode()).hexdigest()[:16]

        # Get time range
        first_ts = window[0].get("timestamp", "")
        last_ts = window[-1].get("timestamp", "")

        yield {
            "text": combined_text,
            "content_hash": content_hash,
            "chat_name": window[0].get("chat_name", "Unknown"),
            "chat_type": window[0].get("chat_type", "personal_chat"),
            "chat_id": window[0].get("chat_id", 0),
            "message_count": len(window),
            "first_timestamp": first_ts,
            "last_timestamp": last_ts,
            "window_index": i // step,
        }


def parse_telegram_folder(folder_path: str) -> List[Dict[str, Any]]:
    """
    Parse all Telegram exports in a folder.

    Telegram exports create a folder per chat with result.json inside.

    Args:
        folder_path: Path to folder containing Telegram export directories

    Returns:
        List of all parsed messages from all chats
    """
    all_messages = []
    folder = Path(folder_path)

    if not folder.exists():
        log_with_context(logger, "warning", "Telegram folder not found", path=folder_path)
        return all_messages

    # Look for result.json files
    for json_file in folder.rglob("result.json"):
        try:
            messages = parse_telegram_json(str(json_file))
            all_messages.extend(messages)
            log_with_context(logger, "debug", "Parsed Telegram export",
                           file=str(json_file), messages=len(messages))
        except Exception as e:
            log_with_context(logger, "error", "Failed to parse Telegram file",
                           file=str(json_file), error=str(e))

    log_with_context(logger, "info", "Telegram folder parsing complete",
                    total_messages=len(all_messages))

    return all_messages


def get_chat_summary(messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Generate a summary of parsed chat messages.

    Returns stats about the chat(s).
    """
    if not messages:
        return {"message_count": 0}

    senders = set()
    chats = set()
    timestamps = []

    for msg in messages:
        senders.add(msg.get("sender", "Unknown"))
        chats.add(msg.get("chat_name", "Unknown"))
        ts = msg.get("timestamp")
        if ts:
            timestamps.append(ts)

    timestamps.sort()

    return {
        "message_count": len(messages),
        "unique_senders": len(senders),
        "unique_chats": len(chats),
        "senders": list(senders)[:10],  # Top 10
        "chats": list(chats),
        "first_message": timestamps[0] if timestamps else None,
        "last_message": timestamps[-1] if timestamps else None,
    }
