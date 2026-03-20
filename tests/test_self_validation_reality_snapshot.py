"""T-RI-24: Tests for split continuity semantics in reality_check_snapshot.

Verifies that:
- continuity_memory_state reflects stored context quality (independent of recent activity)
- continuity_activity_recency captures 30-day session frequency
- memory.status correctly represents real continuity health, not just usage recency
"""
import sqlite3

from app.services.self_validation_service import SelfValidationService


def _make_state_db_with_contexts(path, context_count: int = 1, topic_count: int = 12) -> None:
    """Seed a state DB with the given number of contexts and topics for user_id=99."""
    conn = sqlite3.connect(str(path))
    conn.execute(
        """
        CREATE TABLE conversation_contexts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            user_id INTEGER,
            namespace TEXT DEFAULT 'work',
            start_time TEXT NOT NULL,
            end_time TEXT,
            message_count INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE topic_mentions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            user_id INTEGER,
            topic TEXT NOT NULL,
            first_mentioned TEXT NOT NULL,
            last_mentioned TEXT NOT NULL
        )
        """
    )
    # Insert contexts — all older than 30 days so activity recency is no_data
    for i in range(context_count):
        conn.execute(
            "INSERT INTO conversation_contexts (session_id, user_id, start_time, created_at) VALUES (?, ?, ?, ?)",
            (f"sess-{i}", 99, "2025-01-01T10:00:00", "2025-01-01T10:00:00"),
        )
    # Insert distinct topics
    for i in range(topic_count):
        conn.execute(
            "INSERT INTO topic_mentions (session_id, user_id, topic, first_mentioned, last_mentioned) VALUES (?, ?, ?, ?, ?)",
            ("sess-0", 99, f"topic-{i}", "2025-01-01T10:00:00", "2025-01-01T10:00:00"),
        )
    conn.commit()
    conn.close()


def _make_minimal_service_mocks(service, monkeypatch, user_id: int) -> None:
    """Patch out everything in reality_check_snapshot that we're NOT testing."""
    monkeypatch.setattr(service, "_most_recent_context_user_id", lambda: user_id)
    monkeypatch.setattr(service, "memory_diagnostics", lambda: {"status": "success"})
    monkeypatch.setattr(service, "_agency_metrics_snapshot", lambda hours=168: {})
    monkeypatch.setattr(service, "_pg_table_exists", lambda table_name: False)
    monkeypatch.setattr(service, "_resolve_action_queue_path", lambda: None)
    monkeypatch.setattr(
        service,
        "proactivity_score",
        lambda user_id=None, hours=168: {
            "status": "success",
            "hint_stats": {
                "shown": 0,
                "accepted": 0,
                "explicitly_rejected": 0,
                "completed_outcomes": 0,
                "acceptance_rate": None,
            },
            "proactivity_score": None,
            "sample_quality": {
                "completed_outcomes": 0,
                "min_completed_outcomes_for_judgement": 3,
                "is_small_sample": True,
            },
        },
    )

    class _FakeQuantifier:
        history = []

        def get_calibration_report(self):
            return {"overall_ece": None}

    import app.uncertainty_quantifier as _uq_mod

    monkeypatch.setattr(_uq_mod, "get_uncertainty_quantifier", lambda: _FakeQuantifier())


class TestContinuityMemoryStateThresholds:
    def test_memory_state_pass_when_contexts_and_many_topics(self):
        """contexts>=1 AND topics>=10 → pass."""
        svc = SelfValidationService()
        assert svc._assess_memory_state(context_count=1, topic_count=10) == "pass"
        assert svc._assess_memory_state(context_count=5, topic_count=15) == "pass"

    def test_memory_state_warn_when_contexts_but_few_topics(self):
        """contexts>=1 but topics<10 → warn."""
        svc = SelfValidationService()
        assert svc._assess_memory_state(context_count=1, topic_count=0) == "warn"
        assert svc._assess_memory_state(context_count=1, topic_count=9) == "warn"
        assert svc._assess_memory_state(context_count=3, topic_count=2) == "warn"

    def test_memory_state_fail_when_no_contexts(self):
        """No stored contexts → fail regardless of topics."""
        svc = SelfValidationService()
        assert svc._assess_memory_state(context_count=0, topic_count=0) == "fail"
        assert svc._assess_memory_state(context_count=0, topic_count=99) == "fail"


class TestSnapshotContinuitySplit:
    def test_memory_state_pass_and_activity_no_data_when_contexts_old(
        self, monkeypatch, tmp_path
    ):
        """When Jarvis has substantial memory but no recent sessions:
        - continuity_memory_state = pass (12 topics ≥ 10, 1 context)
        - continuity_activity_recency = no_data (no sessions in last 30 days)
        - memory.status must NOT be fail — it's warn at most (no_data triggers warn rule).
        """
        db_path = tmp_path / "jarvis_state.db"
        _make_state_db_with_contexts(db_path, context_count=1, topic_count=12)
        monkeypatch.setenv("JARVIS_STATE_DB", str(db_path))

        service = SelfValidationService()
        _make_minimal_service_mocks(service, monkeypatch, user_id=99)

        snapshot = service.reality_check_snapshot(hours=168, days=7, user_id=None)

        assert snapshot["status"] == "success"
        memory = snapshot["dimensions"]["memory"]
        mem_metrics = memory["metrics"]

        assert "continuity_memory_state" in mem_metrics, "Split metric missing: continuity_memory_state"
        assert "continuity_activity_recency" in mem_metrics, "Split metric missing: continuity_activity_recency"
        assert "continuity_score_percent" not in mem_metrics, "Old combined metric should be replaced"

        assert mem_metrics["continuity_memory_state"]["status"] == "pass"
        assert mem_metrics["continuity_memory_state"]["value"]["stored_contexts"] == 1
        assert mem_metrics["continuity_memory_state"]["value"]["tracked_topics"] == 12

        assert mem_metrics["continuity_activity_recency"]["status"] == "no_data"
        assert mem_metrics["continuity_activity_recency"]["value"] is None

        # memory.status = combine(pass, no_data, pass) → warn (no_data→warn rule)
        assert memory["status"] == "warn"

    def test_memory_state_fail_when_no_contexts(self, monkeypatch, tmp_path):
        """When no context exists at all: memory_state=fail, activity=no_data."""
        db_path = tmp_path / "jarvis_state.db"
        _make_state_db_with_contexts(db_path, context_count=0, topic_count=0)
        monkeypatch.setenv("JARVIS_STATE_DB", str(db_path))

        service = SelfValidationService()
        _make_minimal_service_mocks(service, monkeypatch, user_id=99)

        snapshot = service.reality_check_snapshot(hours=168, days=7, user_id=None)

        mem_metrics = snapshot["dimensions"]["memory"]["metrics"]
        assert mem_metrics["continuity_memory_state"]["status"] == "fail"
        assert mem_metrics["continuity_activity_recency"]["status"] == "no_data"

    def test_continuity_memory_state_in_continuity_endpoint_no_data_path(
        self, monkeypatch, tmp_path
    ):
        """continuity_memory_state is present in the no_data response from conversation_continuity_test."""
        db_path = tmp_path / "jarvis_state.db"
        _make_state_db_with_contexts(db_path, context_count=1, topic_count=12)
        monkeypatch.setenv("JARVIS_STATE_DB", str(db_path))

        service = SelfValidationService()
        result = service.conversation_continuity_test(user_id=99)

        # All sessions are from 2025-01-01 → outside the 30-day window → no_data
        assert result["status"] == "no_data"
        assert result["continuity_score_percent"] is None
        assert "continuity_memory_state" in result
        assert result["continuity_memory_state"] == "pass"  # 1 context, 12 topics ≥ 10

    def test_no_user_id_gives_no_data_for_both_metrics(self, monkeypatch, tmp_path):
        """When no user_id is resolvable, both continuity metrics are no_data."""
        db_path = tmp_path / "jarvis_state.db"
        monkeypatch.setenv("JARVIS_STATE_DB", str(db_path))

        service = SelfValidationService()
        _make_minimal_service_mocks(service, monkeypatch, user_id=None)
        monkeypatch.setattr(service, "_most_recent_context_user_id", lambda: None)

        snapshot = service.reality_check_snapshot(hours=168, days=7, user_id=None)

        mem_metrics = snapshot["dimensions"]["memory"]["metrics"]
        assert mem_metrics["continuity_memory_state"]["status"] == "no_data"
        assert mem_metrics["continuity_activity_recency"]["status"] == "no_data"
