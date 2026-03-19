import sqlite3

from app.services.self_validation_service import SelfValidationService


def _create_state_db(path) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE conversation_contexts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            user_id INTEGER,
            namespace TEXT DEFAULT 'work_projektil',
            start_time TEXT NOT NULL,
            end_time TEXT,
            conversation_summary TEXT,
            key_topics TEXT,
            pending_actions TEXT,
            emotional_indicators TEXT,
            relationship_updates TEXT,
            message_count INTEGER DEFAULT 0,
            entity_mentions TEXT,
            timeline_anchors TEXT,
            document_references TEXT,
            previous_session_id TEXT,
            related_sessions TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            attribute TEXT NOT NULL,
            value TEXT NOT NULL,
            source_type TEXT NOT NULL,
            source_id TEXT,
            source_date TEXT,
            confidence REAL DEFAULT 1.0,
            created_at TEXT NOT NULL,
            is_current BOOLEAN DEFAULT 1,
            superseded_by INTEGER
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE session_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL
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
            mention_count INTEGER DEFAULT 1,
            first_mentioned TEXT NOT NULL,
            last_mentioned TEXT NOT NULL,
            context_snippet TEXT
        )
        """
    )

    conn.executemany(
        """
        INSERT INTO conversation_contexts (
            session_id, user_id, namespace, start_time, end_time, message_count, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ("session-a", 42, "work", "2026-03-07T09:00:00", "2026-03-07T09:30:00", 6, "2026-03-07T09:30:00"),
            ("session-b", 42, "work", "2026-03-08T10:00:00", "2026-03-08T10:15:00", 4, "2026-03-08T10:15:00"),
        ],
    )
    conn.executemany(
        """
        INSERT INTO facts (
            entity_type, entity_id, attribute, value, source_type, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            ("person", "42", "timezone", "Europe/Zurich", "manual", "2026-03-07T09:31:00"),
            ("project", "jarvis", "phase", "19", "manual", "2026-03-08T10:16:00"),
        ],
    )
    conn.executemany(
        "INSERT INTO session_messages (session_id, role, content) VALUES (?, ?, ?)",
        [
            ("session-a", "user", "hello"),
            ("session-a", "assistant", "hi"),
            ("session-b", "user", "check metrics"),
        ],
    )
    conn.executemany(
        """
        INSERT INTO topic_mentions (
            session_id, user_id, topic, first_mentioned, last_mentioned
        ) VALUES (?, ?, ?, ?, ?)
        """,
        [
            ("session-a", 42, "self-validation", "2026-03-07T09:05:00", "2026-03-07T09:20:00"),
            ("session-b", 42, "deploy", "2026-03-08T10:05:00", "2026-03-08T10:10:00"),
        ],
    )
    conn.commit()
    conn.close()


def test_memory_diagnostics_reads_real_state_schema(monkeypatch, tmp_path):
    state_db = tmp_path / "jarvis_state.db"
    _create_state_db(state_db)
    monkeypatch.setenv("JARVIS_STATE_DB", str(state_db))

    service = SelfValidationService()
    result = service.memory_diagnostics()

    assert result["status"] == "success"
    assert result["conversation_contexts"]["total_contexts"] == 2
    assert result["facts"]["total_facts"] == 2
    assert result["auto_session_persist"]["enabled"] is True
    assert result["recent_contexts"][0]["session_id"] == "session-b"


def test_continuity_uses_sqlite_contexts_and_topics(monkeypatch, tmp_path):
    state_db = tmp_path / "jarvis_state.db"
    _create_state_db(state_db)
    monkeypatch.setenv("JARVIS_STATE_DB", str(state_db))

    service = SelfValidationService()
    result = service.conversation_continuity_test(user_id=42)

    assert result["status"] == "success"
    assert result["stored_contexts"] == 2
    assert result["tracked_topics"] == 2
    assert result["active_days"] == 2


def test_quality_score_uses_stddev_output_tokens_key():
    service = SelfValidationService()
    score = service._calculate_quality_score(
        feedback={"avg_rating": 4.5},
        tool_success=95.0,
        consistency={"avg_output_tokens": 200.0, "stddev_output_tokens": 20.0},
    )

    assert score == 92.0


def test_proactivity_score_returns_no_data_without_table(monkeypatch):
    service = SelfValidationService()
    monkeypatch.setattr(service, "_pg_table_exists", lambda table_name: False)

    result = service.proactivity_score()

    assert result["status"] == "no_data"


def test_reality_check_marks_proactive_warn_for_small_samples(monkeypatch):
    service = SelfValidationService()

    monkeypatch.setattr(service, "_most_recent_context_user_id", lambda: None)
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
                "shown": 1,
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

    snapshot = service.reality_check_snapshot(hours=168, days=7, user_id=None)

    proactive_metrics = snapshot["dimensions"]["proactive"]["metrics"]
    assert proactive_metrics["proactivity_acceptance_rate"]["status"] == "warn"
    assert proactive_metrics["proactivity_score"]["status"] == "warn"


# =============================================================================
# T-RI-06 Tests: agency P95, proactive SQLite, calibration feedback
# =============================================================================

import json
import os
import tempfile
from datetime import datetime, timedelta


def _write_action_queue_file(path, created_offset_sec, decision_offset_sec, status="approved"):
    """Helper: write an action queue JSON file to the given path."""
    now = datetime.now()
    created_at = (now - timedelta(seconds=created_offset_sec)).isoformat() + "Z"
    ts_key = f"{status}_at"
    decision_at = (now - timedelta(seconds=decision_offset_sec)).isoformat() + "Z"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump({"created_at": created_at, ts_key: decision_at, "action": "test"}, f)


def test_agency_p95_from_action_queue(monkeypatch, tmp_path):
    """P95 approval latency is read correctly from action queue JSON files."""
    aq_base = tmp_path / "action_queue"
    # Three approved records: latencies 60s, 120s, 600s
    # _percentile: sorted=[60,120,600], idx=int(2*0.95)=1 → 120s
    for i, latency in enumerate([60, 120, 600]):
        _write_action_queue_file(
            str(aq_base / "approved" / f"rec{i}.json"),
            created_offset_sec=3600 + latency,
            decision_offset_sec=3600,
        )

    monkeypatch.setenv("ACTION_QUEUE_PATH", str(aq_base))
    service = SelfValidationService()
    snapshot = service._agency_metrics_snapshot(hours=48)

    p95 = snapshot["approval_p95_seconds"]
    assert p95 is not None
    # sorted [60,120,600], idx = int(2*0.95) = 1 → 120s
    assert p95 == 120.0
    assert snapshot["autonomy_rollback_rate"] is None  # no Prometheus data in unit test


def test_proactive_snapshot_saves_and_reads_from_sqlite(monkeypatch, tmp_path):
    """_save_proactive_snapshot writes to SQLite; reality_check uses it as fallback."""
    db_path = tmp_path / "jarvis_state.db"
    monkeypatch.setenv("JARVIS_STATE_DB", str(db_path))

    service = SelfValidationService()
    # Directly call the save helper
    service._save_proactive_snapshot(acceptance_rate=42.0, score=58.5, user_id=None)

    # Verify it was persisted
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT acceptance_rate, proactivity_score FROM proactive_snapshots ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()

    assert row is not None
    assert abs(row["acceptance_rate"] - 42.0) < 0.01
    assert abs(row["proactivity_score"] - 58.5) < 0.01


def test_calibration_feedback_saves_to_sqlite(monkeypatch, tmp_path):
    """save_calibration_feedback writes a row to calibration_feedback table."""
    db_path = tmp_path / "jarvis_state.db"
    monkeypatch.setenv("JARVIS_STATE_DB", str(db_path))

    service = SelfValidationService()
    result = service.save_calibration_feedback(confidence=0.8, actual_correct=True, category="intent")

    assert result["status"] == "success"

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT confidence, actual_correct, category FROM calibration_feedback LIMIT 1").fetchone()
    conn.close()

    assert row is not None
    assert abs(row["confidence"] - 0.8) < 0.01
    assert row["actual_correct"] == 1
    assert row["category"] == "intent"


def test_calibration_ece_computed_from_sqlite(monkeypatch, tmp_path):
    """ECE is computed from calibration_feedback SQLite rows when quantifier has no history."""
    db_path = tmp_path / "jarvis_state.db"
    monkeypatch.setenv("JARVIS_STATE_DB", str(db_path))

    service = SelfValidationService()
    # Insert calibration entries: high confidence but only half correct → non-zero ECE
    for _ in range(5):
        service.save_calibration_feedback(confidence=0.9, actual_correct=True, category="test")
    for _ in range(5):
        service.save_calibration_feedback(confidence=0.9, actual_correct=False, category="test")

    # Patch uncertainty_quantifier module-level function (imported inside method body)
    class _FakeQuantifier:
        history = []
        def get_calibration_report(self):
            return {"overall_ece": None}

    import app.uncertainty_quantifier as _uq_mod
    monkeypatch.setattr(_uq_mod, "get_uncertainty_quantifier", lambda: _FakeQuantifier())
    monkeypatch.setattr(service, "_pg_table_exists", lambda t: False)
    monkeypatch.setattr(service, "_resolve_action_queue_path", lambda: None)

    result = service.reality_check_snapshot(hours=168, days=7, user_id=None)

    assert result["status"] == "success"
    cal_metrics = result["dimensions"]["calibration"]["metrics"]
    ece = cal_metrics["calibration_ece"]["value"]
    # 10 samples at confidence=0.9, 50% correct → ECE ≈ |0.5 - 0.95| * 1.0 = 0.45
    assert ece is not None
    assert ece > 0.0

