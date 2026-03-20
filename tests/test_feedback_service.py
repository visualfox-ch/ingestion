import pytest

from app import feedback_service


class _FakeWriteCursor:
    def __init__(self):
        self.query = None
        self.params = None

    def execute(self, query, params=None):
        self.query = query
        self.params = params

    def fetchone(self):
        return {"id": 123}


class _FakeWriteCtx:
    def __init__(self, cursor):
        self._cursor = cursor

    def __enter__(self):
        return self._cursor

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeListCursor:
    def __init__(self):
        self.query = None
        self.params = None

    def execute(self, query, params=None):
        self.query = query
        self.params = params

    def fetchall(self):
        return []


class _FakeListCtx:
    def __init__(self, cursor):
        self._cursor = cursor

    def __enter__(self):
        return self._cursor

    def __exit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_submit_feedback_persists_user_id(monkeypatch):
    cursor = _FakeWriteCursor()

    write_cursors = {
        "user_profile": _FakeWriteCursor(),
        "user_feedback": cursor,
    }

    monkeypatch.setattr(
        feedback_service,
        "safe_write_query",
        lambda table: _FakeWriteCtx(write_cursors[table]),
    )

    async def _noop_trigger(**kwargs):
        return False

    monkeypatch.setattr(feedback_service, "_check_and_trigger_improvement", _noop_trigger)

    feedback_id = await feedback_service.submit_feedback(
        user_id="1465947014",
        feedback_type="general",
        rating=2,
        thumbs_up=False,
        feedback_text="test",
    )

    assert feedback_id == "123"
    assert "INSERT INTO user_feedback" in cursor.query
    assert "user_id" in cursor.query
    assert write_cursors["user_profile"].params == (1465947014,)
    assert cursor.params[0] == 123


@pytest.mark.asyncio
async def test_get_recent_feedback_filters_by_user_id(monkeypatch):
    cursor = _FakeListCursor()
    monkeypatch.setattr(feedback_service, "safe_list_query", lambda _table: _FakeListCtx(cursor))

    await feedback_service.get_recent_feedback(user_id="1465947014", limit=10)

    assert "user_id::TEXT" in cursor.query
    assert cursor.params[0] == "1465947014"
    assert cursor.params[1] == "1465947014"
    assert cursor.params[-1] == 10


@pytest.mark.asyncio
async def test_get_feedback_summary_supports_tuple_rows(monkeypatch):
    class _TupleCursor:
        def __init__(self):
            self.query = None
            self.params = None

        def execute(self, query, params=None):
            self.query = query
            self.params = params

        def fetchone(self):
            return (3, 4.0, 2, 1, ["learning-proof", "actionability"])

    cursor = _TupleCursor()
    monkeypatch.setattr(feedback_service, "safe_list_query", lambda _table: _FakeListCtx(cursor))

    result = await feedback_service.get_feedback_summary(user_id="1465947014", days=30)

    assert result["total_feedback"] == 3
    assert result["avg_rating"] == 4.0
    assert result["positive_count"] == 2
    assert result["negative_count"] == 1
    assert result["top_tags"] == ["learning-proof", "actionability"]
