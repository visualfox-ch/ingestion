from datetime import datetime, timedelta, timezone

from app import n8n_client
from app.routers import n8n_router


def test_n8n_calendar_events_alias_filters_by_hours_window(monkeypatch):
    now = datetime.now(timezone.utc)

    in_window_start = (now + timedelta(hours=2)).isoformat().replace("+00:00", "Z")
    in_window_end = (now + timedelta(hours=3)).isoformat().replace("+00:00", "Z")
    out_window_start = (now + timedelta(hours=30)).isoformat().replace("+00:00", "Z")
    out_window_end = (now + timedelta(hours=31)).isoformat().replace("+00:00", "Z")

    sample_events = [
        {
            "id": "evt_in",
            "account": "projektil",
            "summary": "In window",
            "start": in_window_start,
            "end": in_window_end,
        },
        {
            "id": "evt_out",
            "account": "projektil",
            "summary": "Out window",
            "start": out_window_start,
            "end": out_window_end,
        },
    ]

    monkeypatch.setattr(n8n_client, "get_calendar_events", lambda timeframe, account: sample_events)
    monkeypatch.setattr(
        n8n_client,
        "format_events_for_briefing",
        lambda events, include_date=True: f"{len(events)} event(s)",
    )

    response = n8n_router.n8n_calendar_events(hours=24, account="projektil")

    assert response["hours"] == 24
    assert response["count"] == 1
    assert response["events"][0]["id"] == "evt_in"
    assert response["formatted"] == "1 event(s)"


def test_n8n_calendar_events_alias_clamps_hours(monkeypatch):
    monkeypatch.setattr(n8n_client, "get_calendar_events", lambda timeframe, account: [])
    monkeypatch.setattr(
        n8n_client,
        "format_events_for_briefing",
        lambda events, include_date=True: "",
    )

    response_low = n8n_router.n8n_calendar_events(hours=0, account="all")
    response_high = n8n_router.n8n_calendar_events(hours=999, account="all")

    assert response_low["hours"] == 1
    assert response_high["hours"] == 168


def test_n8n_calendar_events_alias_records_usage_metric(monkeypatch):
    class _FakeMetric:
        def __init__(self):
            self.account = None
            self.incremented = 0

        def labels(self, account):
            self.account = account
            return self

        def inc(self):
            self.incremented += 1

    fake_metric = _FakeMetric()

    monkeypatch.setattr(
        n8n_router,
        "CALENDAR_EVENTS_ALIAS_REQUESTS_TOTAL",
        fake_metric,
    )
    monkeypatch.setattr(n8n_client, "get_calendar_events", lambda timeframe, account: [])
    monkeypatch.setattr(
        n8n_client,
        "format_events_for_briefing",
        lambda events, include_date=True: "",
    )

    response = n8n_router.n8n_calendar_events(hours=24, account="visualfox")

    assert response["account"] == "visualfox"
    assert fake_metric.account == "visualfox"
    assert fake_metric.incremented == 1
