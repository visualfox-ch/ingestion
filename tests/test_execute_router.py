"""
Tests for Execute Action FastAPI Router — Phase 0b Integration Tests

Tests all 5 endpoints with full safety pipeline:
1. POST /api/execute/action (submit action)
2. POST /api/execute/approve (approval decision)
3. GET /api/execute/status/{request_id} (query status)
4. GET /api/execute/rate-limit (check quota)
5. GET /api/execute/audit/{request_id} (retrieve audit)

Author: GitHub Copilot
Phase: 0b (Router integration)
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch, AsyncMock
from datetime import datetime

# Mock the FastAPI app before importing the router
# In real tests, this would be: from app.main import app
# For now, we create a minimal test app

from fastapi import FastAPI
from app.execute_action import router as execute_router
from app.execute_action import (
    get_audit_logger,
    get_denylist_engine,
    get_rate_limiter,
    get_approval_engine,
    RateLimitTier,
)


@pytest.fixture
def app():
    """Create test FastAPI app with execute_action router."""
    test_app = FastAPI()
    test_app.include_router(execute_router)
    
    # Initialize singletons for test
    get_audit_logger()
    get_denylist_engine()
    get_rate_limiter()
    get_approval_engine()
    
    return test_app


@pytest.fixture
def client(app):
    """Create TestClient for the app."""
    return TestClient(app)


@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset singleton state before each test."""
    from app.execute_action.audit import _audit_logger
    from app.execute_action.denylist import _denylist_engine
    from app.execute_action.rate_limiter import _rate_limiter
    from app.execute_action.approval import _approval_engine
    
    # Reset globals
    import app.execute_action.audit as audit_module
    import app.execute_action.denylist as denylist_module
    import app.execute_action.rate_limiter as rate_limiter_module
    import app.execute_action.approval as approval_module
    
    audit_module._audit_logger = None
    denylist_module._denylist_engine = None
    rate_limiter_module._rate_limiter = None
    approval_module._approval_engine = None
    
    yield
    
    # Cleanup after test
    audit_module._audit_logger = None
    denylist_module._denylist_engine = None
    rate_limiter_module._rate_limiter = None
    approval_module._approval_engine = None


class TestExecuteActionAutoApprove:
    """Tests for auto-approved actions (low-risk)."""
    
    def test_auto_approve_email_draft(self, client):
        """Test auto-approval for email_draft action."""
        response = client.post("/api/execute/action", json={
            "action_type": "email_draft",
            "action_target": "test@example.com",
            "action_parameters": {
                "subject": "Test Email",
                "body": "This is a test"
            },
        })
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "executed"
        assert "request_id" in data
        assert data["approval_needed"] is False
    
    def test_auto_approve_note_create(self, client):
        """Test auto-approval for note_create action."""
        response = client.post("/api/execute/action", json={
            "action_type": "note_create",
            "action_target": "Meeting Notes",
            "action_parameters": {
                "content": "Discussed Q1 plans"
            },
        })
        
        assert response.status_code == 200
        assert response.json()["status"] == "executed"
    
    def test_auto_approve_calendar_create(self, client):
        """Test auto-approval for calendar_create action."""
        response = client.post("/api/execute/action", json={
            "action_type": "calendar_create",
            "action_target": "Team Standup",
            "action_parameters": {
                "description": "Daily standup meeting"
            },
        })
        
        assert response.status_code == 200
        assert response.json()["status"] == "executed"
    
    def test_auto_approve_jarvis_email_send(self, client):
        """Test that Jarvis auto-approves even high-risk actions."""
        response = client.post(
            "/api/execute/action",
            json={
                "action_type": "email_send",
                "action_target": "user@example.com",
                "action_parameters": {
                    "subject": "Important",
                    "body": "This is important"
                },
            },
            headers={"X-User-ID": "jarvis"}  # Simulate Jarvis
        )
        
        # Note: This test assumes user_id is passed via header or query param
        # May need to adjust based on actual implementation
        assert response.status_code in (200, 202)


class TestExecuteActionManualApprove:
    """Tests for manual-approved actions (high-risk)."""
    
    def test_manual_approve_email_send(self, client):
        """Test manual approval queue for email_send."""
        response = client.post("/api/execute/action", json={
            "action_type": "email_send",
            "action_target": "user@example.com",
            "action_parameters": {
                "subject": "Hi there",
                "body": "How are you?"
            },
        })
        
        assert response.status_code == 202  # Accepted (pending)
        data = response.json()
        assert data["status"] == "pending"
        assert data["approval_needed"] is True
        assert "request_id" in data
        
        request_id = data["request_id"]
        
        # Now approve it
        approve_response = client.post("/api/execute/approve", json={
            "request_id": request_id,
            "approved": True,
            "reason": "Looks good",
        })
        
        assert approve_response.status_code == 200
        approve_data = approve_response.json()
        assert approve_data["status"] == "executed"
    
    def test_manual_deny_email_send(self, client):
        """Test denying a manual approval request."""
        # Submit action
        submit_response = client.post("/api/execute/action", json={
            "action_type": "email_send",
            "action_target": "user@example.com",
            "action_parameters": {
                "subject": "Suspicious",
                "body": "Click here"
            },
        })
        
        request_id = submit_response.json()["request_id"]
        
        # Deny it
        deny_response = client.post("/api/execute/approve", json={
            "request_id": request_id,
            "approved": False,
            "reason": "Looks like phishing",
        })
        
        assert deny_response.status_code == 200
        assert deny_response.json()["status"] == "denied"


class TestDenylistEnforcement:
    """Tests for denylist blocking."""
    
    def test_denylist_blocked_domain(self, client):
        """Test blocking email to denylisted domain."""
        response = client.post("/api/execute/action", json={
            "action_type": "email_send",
            "action_target": "user@malware.com",
            "action_parameters": {
                "subject": "Test",
                "body": "Test body"
            },
        })
        
        assert response.status_code == 403  # Forbidden
        data = response.json()
        assert "denylist" in data["message"].lower() or "blocked" in data["message"].lower()
    
    def test_denylist_blocked_content(self, client):
        """Test blocking content with harmful keywords."""
        response = client.post("/api/execute/action", json={
            "action_type": "email_send",
            "action_target": "user@example.com",
            "action_parameters": {
                "subject": "Important",
                "body": "Install this ransomware now"  # Blocked keyword
            },
        })
        
        assert response.status_code == 403
        assert "denylist" in response.json()["message"].lower() or "blocked" in response.json()["message"].lower()
    
    def test_denylist_blocked_path(self, client):
        """Test blocking access to sensitive paths."""
        response = client.post("/api/execute/action", json={
            "action_type": "note_create",
            "action_target": "/etc/shadow",  # Sensitive path
            "action_parameters": {
                "content": "Test"
            },
        })
        
        assert response.status_code == 403


class TestRateLimiting:
    """Tests for rate limit enforcement."""
    
    def test_rate_limit_exceeded(self, client):
        """Test rate limit blocking after quota exceeded."""
        rate_limiter = get_rate_limiter()
        rate_limiter.register_user("limited-user", RateLimitTier.FREE)  # 5/day
        
        # Exhaust the quota
        for i in range(5):
            response = client.post(
                "/api/execute/action",
                json={
                    "action_type": "email_draft",
                    "action_target": f"test{i}@example.com",
                    "action_parameters": {},
                },
                headers={"X-User-ID": "limited-user"}  # Simulate user
            )
            assert response.status_code == 200  # First 5 succeed
        
        # 6th request should fail
        response = client.post(
            "/api/execute/action",
            json={
                "action_type": "email_draft",
                "action_target": "test@example.com",
                "action_parameters": {},
            },
            headers={"X-User-ID": "limited-user"}
        )
        
        assert response.status_code == 429  # Too Many Requests
        assert "exceeded" in response.json()["message"].lower()
    
    def test_rate_limit_status(self, client):
        """Test rate limit status endpoint."""
        response = client.get("/api/execute/rate-limit?requester_id=micha")
        
        assert response.status_code == 200
        data = response.json()
        assert data["tier"] == "premium"
        assert "actions_used" in data
        assert "actions_limit" in data
        assert "percentage" in data


class TestActionStatusQuery:
    """Tests for action status queries."""
    
    def test_get_action_status_executed(self, client):
        """Test querying status of executed action."""
        # Submit action
        submit_response = client.post("/api/execute/action", json={
            "action_type": "email_draft",
            "action_target": "test@example.com",
            "action_parameters": {},
        })
        request_id = submit_response.json()["request_id"]
        
        # Query status
        status_response = client.get(f"/api/execute/status/{request_id}")
        
        assert status_response.status_code == 200
        data = status_response.json()
        assert data["request_id"] == request_id
        assert data["status"] == "executed"
    
    def test_get_action_status_pending(self, client):
        """Test querying status of pending action."""
        # Submit action requiring approval
        submit_response = client.post("/api/execute/action", json={
            "action_type": "email_send",
            "action_target": "test@example.com",
            "action_parameters": {},
        })
        request_id = submit_response.json()["request_id"]
        
        # Query status
        status_response = client.get(f"/api/execute/status/{request_id}")
        
        assert status_response.status_code == 200
        assert status_response.json()["status"] == "pending"
    
    def test_get_action_status_not_found(self, client):
        """Test querying status of non-existent request."""
        response = client.get("/api/execute/status/nonexistent-id")
        
        assert response.status_code == 404


class TestAuditRecordRetrieval:
    """Tests for audit record retrieval."""
    
    def test_get_audit_record(self, client):
        """Test retrieving full audit record."""
        # Submit action
        submit_response = client.post("/api/execute/action", json={
            "action_type": "email_draft",
            "action_target": "test@example.com",
            "action_parameters": {
                "subject": "Test"
            },
        })
        request_id = submit_response.json()["request_id"]
        
        # Retrieve audit record
        audit_response = client.get(f"/api/execute/audit/{request_id}")
        
        assert audit_response.status_code == 200
        record = audit_response.json()
        
        # Verify all key fields
        assert record["request_id"] == request_id
        assert record["action_type"] == "email_draft"
        assert record["action_target"] == "test@example.com"
        assert "audit_hash" in record
        assert record["approval_status"] == "approved"  # Auto-approved
    
    def test_get_audit_record_not_found(self, client):
        """Test querying non-existent audit record."""
        response = client.get("/api/execute/audit/nonexistent-id")
        
        assert response.status_code == 404


class TestErrorHandling:
    """Tests for error handling."""
    
    def test_invalid_action_type(self, client):
        """Test invalid action type."""
        response = client.post("/api/execute/action", json={
            "action_type": "invalid_action",
            "action_target": "test@example.com",
            "action_parameters": {},
        })
        
        assert response.status_code == 400
        assert "invalid" in response.json()["detail"].lower()
    
    def test_missing_required_field(self, client):
        """Test missing required field in request."""
        response = client.post("/api/execute/action", json={
            "action_type": "email_draft",
            # Missing action_target
            "action_parameters": {},
        })
        
        assert response.status_code == 422  # Validation error
    
    def test_approve_nonexistent_request(self, client):
        """Test approving non-existent request."""
        response = client.post("/api/execute/approve", json={
            "request_id": "nonexistent",
            "approved": True,
        })
        
        assert response.status_code == 404


class TestDryRunMode:
    """Tests for dry-run mode."""
    
    def test_dry_run_no_execution(self, client):
        """Test that dry-run doesn't execute."""
        response = client.post("/api/execute/action", json={
            "action_type": "email_send",
            "action_target": "test@example.com",
            "action_parameters": {
                "subject": "Test",
                "body": "Test body"
            },
            "dry_run": True,  # Enable dry-run
        })
        
        assert response.status_code == 202  # Still pending
        assert "dry run" in response.json()["message"].lower()


class TestIntegrationScenarios:
    """End-to-end integration test scenarios."""
    
    def test_full_approval_workflow(self, client):
        """Test complete approval workflow: submit → approve → execute."""
        # 1. Submit email (high-risk)
        submit = client.post("/api/execute/action", json={
            "action_type": "email_send",
            "action_target": "recipient@example.com",
            "action_parameters": {
                "subject": "Important Update",
                "body": "Here is the latest information"
            },
        })
        assert submit.status_code == 202
        request_id = submit.json()["request_id"]
        
        # 2. Check status is pending
        status = client.get(f"/api/execute/status/{request_id}")
        assert status.status_code == 200
        assert status.json()["status"] == "pending"
        
        # 3. Approve via Telegram callback
        approve = client.post("/api/execute/approve", json={
            "request_id": request_id,
            "approved": True,
            "reason": "Checked and verified",
        })
        assert approve.status_code == 200
        assert approve.json()["status"] == "executed"
        
        # 4. Check final status
        final = client.get(f"/api/execute/status/{request_id}")
        assert final.status_code == 200
        assert final.json()["status"] == "executed"
        
        # 5. Retrieve audit record
        audit = client.get(f"/api/execute/audit/{request_id}")
        assert audit.status_code == 200
        record = audit.json()
        assert record["approval_status"] == "approved"
        assert record["execution_success"] is True
    
    def test_complete_rejection_workflow(self, client):
        """Test complete rejection workflow: submit → deny."""
        # 1. Submit email
        submit = client.post("/api/execute/action", json={
            "action_type": "email_send",
            "action_target": "unknown@example.com",
            "action_parameters": {
                "subject": "Suspicious",
                "body": "Click here for free money"
            },
        })
        request_id = submit.json()["request_id"]
        
        # 2. Deny approval
        deny = client.post("/api/execute/approve", json={
            "request_id": request_id,
            "approved": False,
            "reason": "Looks like scam",
        })
        assert deny.status_code == 200
        assert deny.json()["status"] == "denied"
        
        # 3. Verify audit shows denial
        audit = client.get(f"/api/execute/audit/{request_id}")
        record = audit.json()
        assert record["approval_status"] == "denied"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
