import json
import hashlib
from datetime import datetime
from typing import Dict, List, Optional


def _compute_window_hash(source_path: str, channel: str, ts_start: str, ts_end: str, message_count: int) -> str:
    """
    Compute a deterministic hash for a message window.
    This uniquely identifies a window by its temporal boundaries and source.
    """
    key = f"{source_path}::{channel}::{ts_start}::{ts_end}::{message_count}"
    return hashlib.sha256(key.encode()).hexdigest()[:32]

def _iso_from_any(ts: Optional[str]) -> Optional[str]:
    if not ts:
        return None
    ts = ts.strip()
    try:
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        dt = datetime.fromisoformat(ts)
        return dt.isoformat()
    except Exception:
        return None

def _extract_sender(m: Dict) -> str:
    creator = m.get("creator") or m.get("sender") or {}
    return (creator.get("name") or creator.get("displayName") or creator.get("email") or "unknown").strip()

def _extract_text(m: Dict) -> str:
    t = m.get("text")
    if isinstance(t, str) and t.strip():
        return t.strip()
    ft = m.get("formattedText")
    if isinstance(ft, str) and ft.strip():
        return ft.strip()

    segments = m.get("textSegments") or m.get("segments")
    if isinstance(segments, list):
        parts = []
        for s in segments:
            if isinstance(s, dict):
                st = s.get("text")
                if isinstance(st, str) and st.strip():
                    parts.append(st.strip())
        if parts:
            return "\n".join(parts)

    return ""

def _extract_channel_id(data: Dict, source_path: str) -> str:
    """
    Extract a unique channel/conversation ID from Google Chat export data.

    Tries multiple fields that might contain a unique identifier:
    - space.name (e.g., "spaces/ABC123")
    - roomId / room_id
    - conversationId / conversation_id
    - name (top-level space/room name)

    Falls back to a hash of the source_path if no ID found.
    """
    if isinstance(data, dict):
        # Try space.name (Google Takeout format)
        space = data.get("space") or data.get("Space")
        if isinstance(space, dict):
            space_name = space.get("name") or space.get("displayName")
            if space_name:
                return f"gchat_{space_name.replace('spaces/', '')}"

        # Try direct IDs
        for key in ["roomId", "room_id", "conversationId", "conversation_id", "spaceId", "space_id"]:
            if data.get(key):
                return f"gchat_{data[key]}"

        # Try top-level name
        if data.get("name") and isinstance(data.get("name"), str):
            # Filter out message names like "spaces/X/messages/Y"
            name = data["name"]
            if not "/messages/" in name:
                return f"gchat_{name.replace('spaces/', '')}"

    # Fallback: use source path hash (stable per file)
    import os
    filename = os.path.basename(source_path).replace(".json", "").replace(" ", "_")
    return f"gchat_{filename}"


def parse_google_chat_json(raw: str, source_path: str, ingest_ts: str) -> Dict:
    data = json.loads(raw)

    # Extract unique channel ID for sync state tracking
    channel_id = _extract_channel_id(data, source_path)

    msgs_raw = None
    if isinstance(data, dict):
        msgs_raw = data.get("messages")
    if msgs_raw is None and isinstance(data, list):
        msgs_raw = data

    messages: List[Dict] = []
    if isinstance(msgs_raw, list):
        for m in msgs_raw:
            if not isinstance(m, dict):
                continue

            ts = _iso_from_any(m.get("createTime") or m.get("createdDate") or m.get("timestamp") or m.get("time"))
            sender = _extract_sender(m)
            text = _extract_text(m)

            if not text:
                continue

            messages.append({
                "event_ts": ts or "",
                "ingest_ts": ingest_ts,
                "sender": sender,
                "text": text,
                "source_path": source_path,
                "channel": "google_chat",
            })

    return {"channel": "google_chat", "channel_id": channel_id, "source_path": source_path, "messages": messages}

def window_messages(messages: List[Dict], window_size: int = 10, step: int = 8, source_path: str = "") -> List[Dict]:
    """
    Create overlapping windows of messages for embedding.

    Each window includes a deterministic hash for deduplication during re-ingestion.
    The hash is based on source_path, channel, timestamps, and message count -
    ensuring the same temporal window always gets the same ID.
    """
    windows: List[Dict] = []
    i = 0
    n = len(messages)
    channel = messages[0].get("channel", "google_chat") if messages else "google_chat"

    while i < n:
        chunk_msgs = messages[i:i+window_size]
        if not chunk_msgs:
            break
        joined = "\n".join([f'{m["sender"]}: {m["text"]}' for m in chunk_msgs])
        ts_start = chunk_msgs[0].get("event_ts", "")
        ts_end = chunk_msgs[-1].get("event_ts", "")
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
