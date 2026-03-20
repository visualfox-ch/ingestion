from app.uncertainty_quantifier import UncertaintyQuantifier
import sqlite3


def _build_fixture_history():
    history = []

    # Overconfident cluster: confidence 0.9, ~48% accuracy (14/29)
    for i in range(29):
        history.append(
            {
                "timestamp": f"2026-03-20T00:00:{i:02d}",
                "confidence_score": 0.9,
                "was_correct": i < 14,
                "domain": "general",
                "metadata": {},
            }
        )

    # Underconfident cluster: confidence ~0.83, 100% accuracy
    for i in range(9):
        history.append(
            {
                "timestamp": f"2026-03-20T00:01:{i:02d}",
                "confidence_score": 0.8278,
                "was_correct": True,
                "domain": "general",
                "metadata": {},
            }
        )

    # Low-confidence cluster: confidence 0.45, 66.7% accuracy (2/3)
    for i in range(3):
        history.append(
            {
                "timestamp": f"2026-03-20T00:02:{i:02d}",
                "confidence_score": 0.45,
                "was_correct": i < 2,
                "domain": "general",
                "metadata": {},
            }
        )

    return history


def test_piecewise_calibration_reduces_ece(monkeypatch, tmp_path):
    history = _build_fixture_history()

    monkeypatch.setenv("JARVIS_CONFIDENCE_CALIBRATION_V1", "0")
    raw_quantifier = UncertaintyQuantifier(state_path=str(tmp_path / "raw"))
    raw_quantifier.history = history
    raw_ece = raw_quantifier.get_calibration_error()

    monkeypatch.setenv("JARVIS_CONFIDENCE_CALIBRATION_V1", "1")
    calibrated_quantifier = UncertaintyQuantifier(state_path=str(tmp_path / "calibrated"))
    calibrated_quantifier.history = history
    calibrated_ece = calibrated_quantifier.get_calibration_error()

    assert raw_ece is not None
    assert calibrated_ece is not None
    assert calibrated_ece < raw_ece


def test_already_calibrated_entries_are_not_double_calibrated(tmp_path):
    quantifier = UncertaintyQuantifier(state_path=str(tmp_path / "meta"))

    entry = {
        "confidence_score": 0.71,
        "was_correct": True,
        "domain": "general",
        "metadata": {"calibration_version": "piecewise_v1"},
    }

    assert quantifier._confidence_for_calibration_entry(entry) == 0.71


def test_calibration_report_exposes_diagnostics(monkeypatch, tmp_path):
    history = _build_fixture_history()

    monkeypatch.setenv("JARVIS_CONFIDENCE_CALIBRATION_V1", "1")
    quantifier = UncertaintyQuantifier(state_path=str(tmp_path / "diag"))
    quantifier.history = history

    report = quantifier.get_calibration_report()

    assert report["overall_ece"] is not None
    assert report["recent_ece_7d"] is not None
    assert report["recent_samples_7d"] == len(history)
    assert isinstance(report["bucket_diagnostics_lifetime"], list)
    assert isinstance(report["bucket_diagnostics_recent_7d"], list)
    assert "per_source_ece" in report
    assert isinstance(report["high_confidence_problem_buckets_recent_7d"], list)
    assert report["timestamp"].endswith("Z")


def test_calibration_report_hydrates_from_sqlite_when_history_empty(monkeypatch, tmp_path):
    state_db = tmp_path / "jarvis_state.db"
    conn = sqlite3.connect(str(state_db))
    conn.execute(
        """
        CREATE TABLE calibration_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            confidence REAL NOT NULL,
            actual_correct INTEGER NOT NULL,
            category TEXT,
            source_type TEXT
        )
        """
    )
    conn.execute(
        """
        INSERT INTO calibration_feedback (timestamp, confidence, actual_correct, category, source_type)
        VALUES ('2026-03-20T00:00:00', 0.91, 1, 'general', NULL)
        """
    )
    conn.execute(
        """
        INSERT INTO calibration_feedback (timestamp, confidence, actual_correct, category, source_type)
        VALUES ('2026-03-20T00:01:00', 0.91, 0, 'telegram_message_feedback', NULL)
        """
    )
    conn.commit()
    conn.close()

    monkeypatch.setenv("JARVIS_STATE_DB", str(state_db))
    quantifier = UncertaintyQuantifier(state_path=str(tmp_path / "calibration_file_state"))
    quantifier.history = []

    report = quantifier.get_calibration_report()

    assert report["total_samples"] == 2
    assert "message_feedback" in report["per_source_ece"]
    assert "legacy_unknown" in report["per_source_ece"]
    assert "unknown" not in report["per_source_ece"]
    assert report["timestamp"].endswith("Z")
