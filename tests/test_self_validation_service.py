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
