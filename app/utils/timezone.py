"""Timezone utilities for user-facing timestamps."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import pytz

ZURICH_TZ = pytz.timezone("Europe/Zurich")


def now_zurich_iso() -> str:
    """Return current Zurich time as ISO string with offset."""
    return datetime.now(ZURICH_TZ).isoformat()


def parse_to_zurich(ts_value: str) -> Optional[datetime]:
    """Parse ISO timestamp and convert to Zurich timezone."""
    if not ts_value:
        return None
    try:
        parsed = datetime.fromisoformat(ts_value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=pytz.UTC)
    return parsed.astimezone(ZURICH_TZ)


def to_zurich_iso(ts_value: str) -> str:
    """Convert ISO timestamp to Zurich ISO string (if parseable)."""
    parsed = parse_to_zurich(ts_value)
    return parsed.isoformat() if parsed else ts_value
