"""Integration hooks: audit logger -> persistent learn storage."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.execute_action.audit import get_audit_logger, ActionType
from app.persistent_learn import storage


def test_audit_logger_persists_to_persistent_learn(monkeypatch):
    calls = {"fact": 0, "decision": 0}

    def _mock_record_fact(**kwargs):
        calls["fact"] += 1
        return {"id": "fact", "status": "active", "created_at": "now", "expires_at": None}

    def _mock_record_decision_log(**kwargs):
        calls["decision"] += 1
        return {"id": "decision", "status": "active", "created_at": "now", "expires_at": None}

    monkeypatch.setattr(storage, "record_fact", _mock_record_fact)
    monkeypatch.setattr(storage, "record_decision_log", _mock_record_decision_log)

    logger = get_audit_logger()
    record = logger.log_action(
        request_id="req-1",
        requester_id="user-1",
        requester_email="user@example.com",
        action_type=ActionType.EMAIL_DRAFT,
        action_target="target@example.com",
        action_parameters={"namespace": "work_projektil"},
        dry_run=True,
    )

    logger.log_approval_decision(
        request_id=record.request_id,
        approved=True,
        decision_maker="user-1",
        reason="ok",
    )
    logger.log_execution(request_id=record.request_id, success=True)
    logger.log_rollback(request_id=record.request_id, reason="test")

    assert calls["decision"] == 1
    assert calls["fact"] >= 3
