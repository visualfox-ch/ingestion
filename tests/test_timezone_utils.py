from datetime import datetime, timedelta, timezone

from app.utils import timezone as timezone_utils


def test_get_timezone_falls_back_for_central_europe(monkeypatch) -> None:
    monkeypatch.setattr(timezone_utils, "_ZoneInfoFactory", None)

    tz = timezone_utils.get_timezone("Europe/Zurich")
    winter = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc).astimezone(tz)
    summer = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc).astimezone(tz)

    assert winter.utcoffset() == timedelta(hours=1)
    assert summer.utcoffset() == timedelta(hours=2)


def test_parse_to_zurich_converts_utc_input() -> None:
    parsed = timezone_utils.parse_to_zurich("2026-03-16T14:00:00Z")

    assert parsed is not None
    assert parsed.tzinfo is not None
    assert parsed.hour in {15, 16}
