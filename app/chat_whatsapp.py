import re
import hashlib
from datetime import datetime, timezone
from typing import List, Dict, Optional


def _compute_window_hash(source_path: str, channel: str, ts_start: str, ts_end: str, message_count: int) -> str:
    """
    Compute a deterministic hash for a message window.
    This uniquely identifies a window by its temporal boundaries and source.
    """
    key = f"{source_path}::{channel}::{ts_start}::{ts_end}::{message_count}"
    return hashlib.sha256(key.encode()).hexdigest()[:32]

# Format B example:
# [08.02.25, 11:36:59] Name: message text

LINE_RE = re.compile(
    r"^\[(\d{2}\.\d{2}\.\d{2}),\s(\d{2}:\d{2}:\d{2})\]\s([^:]+):\s?(.*)$"
)

def parse_event_ts(date_str: str, time_str: str) -> str:
    # returns ISO string in local timezone-naive style; keep simple for v1
    dt = datetime.strptime(f"{date_str} {time_str}", "%d.%m.%y %H:%M:%S")
    return dt.isoformat()

def _extract_channel_id(source_path: str, text: str) -> str:
    """
    Extract a unique channel ID from WhatsApp export.

    WhatsApp exports are typically named like:
    - "WhatsApp Chat with Peter Müller.txt"
    - "WhatsApp-Chat mit Team.txt"
    - Or just the person/group name

    Falls back to a normalized filename if no pattern matches.
    """
    import os
    import re

    filename = os.path.basename(source_path).replace(".txt", "")

    # Try to extract chat name from common patterns
    patterns = [
        r"WhatsApp\s+Chat\s+(?:with|mit)\s+(.+)",  # English/German
        r"Chat\s+WhatsApp\s+(?:con|avec)\s+(.+)",  # Spanish/French
        r"^(.+?)\s*[-_]\s*WhatsApp",              # Name before WhatsApp
    ]

    for pattern in patterns:
        match = re.search(pattern, filename, re.IGNORECASE)
        if match:
            chat_name = match.group(1).strip()
            # Normalize: lowercase, replace spaces with underscores
            normalized = re.sub(r'[^a-z0-9äöüß]+', '_', chat_name.lower()).strip('_')
            return f"whatsapp_{normalized}"

    # Fallback: use normalized filename
    normalized = re.sub(r'[^a-z0-9äöüß]+', '_', filename.lower()).strip('_')
    return f"whatsapp_{normalized}"


def parse_whatsapp_text(text: str, source_path: str, ingest_ts: str) -> Dict:
    messages: List[Dict] = []
    current: Optional[Dict] = None

    # Extract unique channel ID for sync state tracking
    channel_id = _extract_channel_id(source_path, text)

    for raw in text.splitlines():
        m = LINE_RE.match(raw.strip())
        if m:
            # flush previous
            if current:
                messages.append(current)
            d, t, sender, msg = m.groups()
            current = {
                "event_ts": parse_event_ts(d, t),
                "ingest_ts": ingest_ts,
                "sender": sender.strip(),
                "text": msg.strip(),
                "source_path": source_path,
                "channel": "whatsapp",
            }
        else:
            # continuation line
            if current is not None:
                tail = raw.strip()
                if tail:
                    current["text"] += "\n" + tail

    if current:
        messages.append(current)

    return {
        "channel": "whatsapp",
        "channel_id": channel_id,
        "source_path": source_path,
        "messages": messages
    }

def window_messages(messages: List[Dict], window_size: int = 8, step: int = 6, source_path: str = "") -> List[Dict]:
    """
    Create overlapping windows of messages for embedding.

    Each window includes a deterministic hash for deduplication during re-ingestion.
    The hash is based on source_path, channel, timestamps, and message count -
    ensuring the same temporal window always gets the same ID.
    """
    windows: List[Dict] = []
    i = 0
    n = len(messages)
    channel = messages[0].get("channel", "whatsapp") if messages else "whatsapp"

    while i < n:
        chunk_msgs = messages[i:i+window_size]
        if not chunk_msgs:
            break
        joined = "\n".join([f'{m["sender"]}: {m["text"]}' for m in chunk_msgs])
        ts_start = chunk_msgs[0]["event_ts"]
        ts_end = chunk_msgs[-1]["event_ts"]
        msg_count = len(chunk_msgs)

        # Compute deterministic window hash for deduplication
        window_hash = _compute_window_hash(source_path, channel, ts_start, ts_end, msg_count)

        windows.append({
            "text": joined,
            "event_ts_start": ts_start,
            "event_ts_end": ts_end,
            "message_count": msg_count,
            "window_hash": window_hash,
        })
        i += step
    return windows
