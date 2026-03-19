"""Timezone utilities for user-facing timestamps without hard third-party deps."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone, tzinfo
from typing import Optional

try:
    from zoneinfo import ZoneInfo as _ZoneInfoFactory
except ImportError:  # pragma: no cover - exercised on Python < 3.9
    try:
        from backports.zoneinfo import ZoneInfo as _ZoneInfoFactory
    except ImportError:  # pragma: no cover - exercised on lean host environments
        _ZoneInfoFactory = None


def _last_weekday_of_month(year: int, month: int, weekday: int) -> int:
    if month == 12:
        next_month = datetime(year + 1, 1, 1)
    else:
        next_month = datetime(year, month + 1, 1)
    candidate = next_month - timedelta(days=1)
    while candidate.weekday() != weekday:
        candidate -= timedelta(days=1)
    return candidate.day


class _CentralEuropeFallbackTZ(tzinfo):
    """Simple DST-aware fallback for Zurich/Berlin style CET/CEST time."""

    def __init__(self, zone_name: str):
        self.zone_name = zone_name

    def _dst_window(self, year: int) -> tuple[datetime, datetime]:
        start_day = _last_weekday_of_month(year, 3, 6)
        end_day = _last_weekday_of_month(year, 10, 6)
        # CET/CEST transitions expressed in local wall time.
        start = datetime(year, 3, start_day, 2, 0, 0)
        end = datetime(year, 10, end_day, 3, 0, 0)
        return start, end

    def _is_dst_local(self, naive_local: datetime) -> bool:
        start, end = self._dst_window(naive_local.year)
        return start <= naive_local < end

    def utcoffset(self, dt: Optional[datetime]) -> timedelta:
        return timedelta(hours=1) + self.dst(dt)

    def dst(self, dt: Optional[datetime]) -> timedelta:
        if dt is None:
            return timedelta(0)
        naive_local = dt.replace(tzinfo=None)
        return timedelta(hours=1) if self._is_dst_local(naive_local) else timedelta(0)

    def tzname(self, dt: Optional[datetime]) -> str:
        return "CEST" if self.dst(dt) else "CET"

    def fromutc(self, dt: datetime) -> datetime:
        if dt.tzinfo is not self:
            raise ValueError("fromutc: dt.tzinfo is not self")
        naive_utc = dt.replace(tzinfo=None)
        local_candidate = naive_utc + timedelta(hours=1)
        if self._is_dst_local(local_candidate):
            local_candidate = naive_utc + timedelta(hours=2)
        return local_candidate.replace(tzinfo=self)


_CENTRAL_EUROPE_FALLBACK = _CentralEuropeFallbackTZ("Europe/Zurich")
_FALLBACK_TIMEZONES = {
    "UTC": timezone.utc,
    "Etc/UTC": timezone.utc,
    "Europe/Zurich": _CENTRAL_EUROPE_FALLBACK,
    "Europe/Berlin": _CENTRAL_EUROPE_FALLBACK,
}


def get_timezone(name: str) -> tzinfo:
    """Return a tzinfo object without requiring backports on lean hosts."""
    if _ZoneInfoFactory is not None:
        return _ZoneInfoFactory(name)

    fallback = _FALLBACK_TIMEZONES.get(name)
    if fallback is not None:
        return fallback

    raise LookupError(f"Unsupported timezone without zoneinfo support: {name}")


ZURICH_TZ = get_timezone("Europe/Zurich")


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
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(ZURICH_TZ)


def to_zurich_iso(ts_value: str) -> str:
    """Convert ISO timestamp to Zurich ISO string (if parseable)."""
    parsed = parse_to_zurich(ts_value)
    return parsed.isoformat() if parsed else ts_value
