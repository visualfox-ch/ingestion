from datetime import datetime, timedelta, timezone

from app import scheduler


def test_pre_meeting_message_contains_context_and_metadata():
    event = {
        "id": "evt-1",
        "account": "visualfox",
        "summary": "Client Sync",
        "location": "Zoom",
        "start": (datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat(),
    }
    start_dt = scheduler._parse_event_start(event["start"])

    msg = scheduler._format_pre_meeting_message(
        event=event,
        start_dt=start_dt,
        minutes_left=20,
        context_lines=["- notes.md: Last open topic about budget"],
    )

    assert "Meeting-Hinweis" in msg
    assert "visualfox" in msg
    assert "Client Sync" in msg
    assert "Ort: Zoom" in msg
    assert "Relevanter Kontext" in msg


def test_send_pre_meeting_suggestions_sends_once_and_persists_dedup(monkeypatch):
    monkeypatch.setattr(scheduler, "PRE_MEETING_PUSH_ENABLED", True)
    monkeypatch.setattr(scheduler, "PRE_MEETING_LOOKAHEAD_MINUTES", 30)

    now = datetime.now(timezone.utc)
    event = {
        "id": "evt-42",
        "account": "projektil",
        "summary": "Roadmap Sync",
        "start": (now + timedelta(minutes=10)).isoformat().replace("+00:00", "Z"),
        "all_day": False,
    }

    class _FakeStateDb:
        @staticmethod
        def get_all_telegram_users():
            return [{"user_id": 1234, "namespace": "work_projektil"}]

    class _FakeN8N:
        @staticmethod
        def get_calendar_events(timeframe="today", account="all"):
            return [event]

    monkeypatch.setattr(scheduler, "_load_pre_meeting_state", lambda: {})

    saved_state = {}

    def _save_state(state):
        saved_state.update(state)

    monkeypatch.setattr(scheduler, "_save_pre_meeting_state", _save_state)
    monkeypatch.setattr(scheduler, "_fetch_pre_meeting_context_lines", lambda event, namespace: ["- context"])

    sent_messages = []

    def _send(chat_id, text):
        sent_messages.append((chat_id, text))

    monkeypatch.setattr(scheduler, "_send_telegram_message", _send)
    monkeypatch.setattr(scheduler, "_get_pre_meeting_dependencies", lambda: (_FakeStateDb, _FakeN8N))

    scheduler.send_pre_meeting_suggestions()

    assert len(sent_messages) == 1
    assert sent_messages[0][0] == 1234
    assert "Roadmap Sync" in sent_messages[0][1]
    assert saved_state


def test_send_pre_meeting_suggestions_skips_duplicate(monkeypatch):
    monkeypatch.setattr(scheduler, "PRE_MEETING_PUSH_ENABLED", True)
    monkeypatch.setattr(scheduler, "PRE_MEETING_LOOKAHEAD_MINUTES", 30)

    now = datetime.now(timezone.utc)
    start = (now + timedelta(minutes=15)).isoformat().replace("+00:00", "Z")
    event = {
        "id": "evt-dup",
        "account": "visualfox",
        "summary": "Duplicate Check",
        "start": start,
        "all_day": False,
    }
    start_dt = scheduler._parse_event_start(start)
    dedup_key = scheduler._build_pre_meeting_key(777, event, start_dt)

    class _FakeStateDb:
        @staticmethod
        def get_all_telegram_users():
            return [{"user_id": 777, "namespace": "work_projektil"}]

    class _FakeN8N:
        @staticmethod
        def get_calendar_events(timeframe="today", account="all"):
            return [event]

    monkeypatch.setattr(
        scheduler,
        "_load_pre_meeting_state",
        lambda: {dedup_key: datetime.now(timezone.utc).timestamp()},
    )
    monkeypatch.setattr(scheduler, "_save_pre_meeting_state", lambda state: None)
    monkeypatch.setattr(scheduler, "_fetch_pre_meeting_context_lines", lambda event, namespace: [])

    sent_messages = []
    monkeypatch.setattr(scheduler, "_send_telegram_message", lambda chat_id, text: sent_messages.append((chat_id, text)))
    monkeypatch.setattr(scheduler, "_get_pre_meeting_dependencies", lambda: (_FakeStateDb, _FakeN8N))

    scheduler.send_pre_meeting_suggestions()

    assert sent_messages == []
