"""
Test suite for diff_gate.py

Phase 0 tests (Feb 4, 2026):
  - Verify diff gate validation (forbidden paths, size limits)
  - Test Telegram card format
  - Test approval result immutability
"""

import pytest
import asyncio
from app.diff_gate import (
    DiffGateValidator,
    CodeChange,
    RiskClass,
    ApprovalRequest,
    ApprovalResult
)


class TestDiffGateValidator:
    """Tests for DiffGateValidator"""
    
    def test_validate_trivial_change(self):
        """Trivial change should pass validation."""
        
        gate = DiffGateValidator()
        
        change = CodeChange(
            id="change_1",
            file_path="ingestion/app/config.py",
            change_type="config",
            diff_preview="- timeout = 30\n+ timeout = 60",
            full_diff="--- a/ingestion/app/config.py\n+++ b/ingestion/app/config.py\n- timeout = 30\n+ timeout = 60",
            risk_class=RiskClass.R0,
            description="Update timeout",
            line_count=5
        )
        
        validation = gate._validate_change(change)
        
        assert validation["valid"] is True
        assert validation["reason"] is None
    
    def test_validate_forbidden_path_env(self):
        """Changes to .env should be rejected."""
        
        gate = DiffGateValidator()
        
        change = CodeChange(
            id="change_2",
            file_path=".env",
            change_type="config",
            diff_preview="",
            full_diff="",
            risk_class=RiskClass.R0,
            description="Update .env",
            line_count=2
        )
        
        validation = gate._validate_change(change)
        
        assert validation["valid"] is False
        assert ".env" in validation["reason"]
    
    def test_validate_forbidden_path_secrets(self):
        """Changes to secrets file should be rejected."""
        
        gate = DiffGateValidator()
        
        change = CodeChange(
            id="change_3",
            file_path="ingestion/app/secrets/db_password.txt",
            change_type="config",
            diff_preview="",
            full_diff="",
            risk_class=RiskClass.R0,
            description="Update secret",
            line_count=1
        )
        
        validation = gate._validate_change(change)
        
        assert validation["valid"] is False
        assert "forbidden" in validation["reason"].lower()
    
    def test_validate_forbidden_path_docker(self):
        """Changes to Docker config should be rejected."""
        
        gate = DiffGateValidator()
        
        change = CodeChange(
            id="change_4",
            file_path="docker-compose.yml",
            change_type="config",
            diff_preview="",
            full_diff="",
            risk_class=RiskClass.R0,
            description="Update docker-compose",
            line_count=10
        )
        
        validation = gate._validate_change(change)
        
        assert validation["valid"] is False
        assert "docker-compose" in validation["reason"].lower()
    
    def test_validate_too_large_change(self):
        """Changes >500 lines should be rejected."""
        
        gate = DiffGateValidator()
        
        change = CodeChange(
            id="change_5",
            file_path="ingestion/app/agent.py",
            change_type="refactor",
            diff_preview="",
            full_diff="",
            risk_class=RiskClass.R1,
            description="Large refactor",
            line_count=600
        )
        
        validation = gate._validate_change(change)
        
        assert validation["valid"] is False
        assert "too large" in validation["reason"].lower()
    
    def test_build_approval_card_format(self):
        """Test Telegram approval card format."""
        
        gate = DiffGateValidator()
        
        change = CodeChange(
            id="change_6",
            file_path="ingestion/app/config.py",
            change_type="config",
            diff_preview="- timeout = 30\n+ timeout = 60",
            full_diff="full diff here",
            risk_class=RiskClass.R0,
            description="Update timeout value",
            line_count=5
        )
        
        card = gate._build_approval_card(
            change=change,
            request_id="req_12345",
            confidence_score=0.85
        )
        
        # Card should have required fields
        assert "request_id" in card
        assert card["request_id"] == "req_12345"
        assert "text" in card
        assert "buttons" in card
        
        # Text should include change details
        assert "Approval Required" in card["text"]
        assert "config.py" in card["text"]
        assert "0.85" in card["text"]
        
        # Buttons should be present
        assert len(card["buttons"]) == 3
        assert any("Approve" in btn["label"] for btn in card["buttons"])
        assert any("Reject" in btn["label"] for btn in card["buttons"])
    
    def test_approval_result_audit_trail(self):
        """ApprovalResult should have immutable audit trail."""
        
        result = ApprovalResult(
            request_id="req_67890",
            approved=True,
            approver="user_12345",
            feedback="Looks good",
            audit_hash="sha256_hash_here"
        )
        
        assert result.request_id == "req_67890"
        assert result.approved is True
        assert result.approver == "user_12345"
        assert result.audit_hash == "sha256_hash_here"
    
    def test_risk_class_enum(self):
        """Test RiskClass enum values."""
        
        assert RiskClass.R0.value == "R0"
        assert RiskClass.R1.value == "R1"
        assert RiskClass.R2.value == "R2"
        assert RiskClass.R3.value == "R3"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
