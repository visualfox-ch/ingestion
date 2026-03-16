"""
Tests for Execute Action Phase 0a (Core Safety Infrastructure)

Tests:
- Audit logging (immutable records, 25+ fields)
- Denylist enforcement (4-layer checks)
- Rate limiting (5 tiers, daily reset)
- Approval workflow (auto/manual strategy)

Author: GitHub Copilot
"""

import pytest
from datetime import datetime, timedelta
import asyncio

from app.execute_action import (
    AuditLogger, ActionType, ApprovalStatus,
    DenylistEngine, DenylistCategory,
    RateLimiter, RateLimitTier,
    ApprovalEngine, ApprovalStrategy,
)


# ============================================================================
# Audit Logger Tests
# ============================================================================

class TestAuditLogger:
    """Test AuditLogger functionality."""
    
    def test_log_action_creates_record(self):
        """Test that logging an action creates an immutable record."""
        logger = AuditLogger()
        
        record = logger.log_action(
            request_id="req-123",
            requester_id="micha",
            requester_email="micha@example.com",
            action_type=ActionType.EMAIL_SEND,
            action_target="user@example.com",
            action_parameters={"subject": "Test", "body": "Body"},
        )
        
        assert record.request_id == "req-123"
        assert record.action_type == ActionType.EMAIL_SEND
        assert record.approval_status == ApprovalStatus.PENDING
        assert record.audit_hash is not None
    
    def test_log_denylist_hit(self):
        """Test denylist hit logging."""
        logger = AuditLogger()
        
        record = logger.log_action(
            request_id="req-123",
            requester_id="micha",
            requester_email="micha@example.com",
            action_type=ActionType.EMAIL_SEND,
            action_target="user@example.com",
            action_parameters={},
        )
        
        logger.log_denylist_hit("req-123", "Domain is denied", "medium")
        
        updated = logger.get_record("req-123")
        assert updated.denylist_match is True
        assert updated.denylist_reason == "Domain is denied"
    
    def test_log_rate_limit_hit(self):
        """Test rate limit hit logging."""
        logger = AuditLogger()
        
        logger.log_action(
            request_id="req-123",
            requester_id="micha",
            requester_email="micha@example.com",
            action_type=ActionType.EMAIL_SEND,
            action_target="user@example.com",
            action_parameters={},
        )
        
        logger.log_rate_limit_hit("req-123", "free")
        
        updated = logger.get_record("req-123")
        assert updated.rate_limit_hit is True
        assert updated.rate_limit_tier == "free"
    
    def test_log_approval_decision(self):
        """Test approval decision logging."""
        logger = AuditLogger()
        
        logger.log_action(
            request_id="req-123",
            requester_id="micha",
            requester_email="micha@example.com",
            action_type=ActionType.EMAIL_SEND,
            action_target="user@example.com",
            action_parameters={},
        )
        
        logger.log_approval_decision(
            request_id="req-123",
            approved=True,
            decision_maker="micha",
            reason="User approved via Telegram"
        )
        
        updated = logger.get_record("req-123")
        assert updated.approval_status == ApprovalStatus.APPROVED
        assert updated.approval_decision_maker == "micha"
    
    def test_log_execution(self):
        """Test execution outcome logging."""
        logger = AuditLogger()
        
        logger.log_action(
            request_id="req-123",
            requester_id="micha",
            requester_email="micha@example.com",
            action_type=ActionType.EMAIL_SEND,
            action_target="user@example.com",
            action_parameters={},
        )
        
        logger.log_execution("req-123", success=True)
        
        updated = logger.get_record("req-123")
        assert updated.execution_attempted is True
        assert updated.execution_success is True
    
    def test_get_records_by_requester(self):
        """Test retrieving records by requester."""
        logger = AuditLogger()
        
        for i in range(3):
            logger.log_action(
                request_id=f"req-{i}",
                requester_id="micha",
                requester_email="micha@example.com",
                action_type=ActionType.EMAIL_SEND,
                action_target=f"user{i}@example.com",
                action_parameters={},
            )
        
        records = logger.get_records_by_requester("micha", hours=24)
        assert len(records) == 3
    
    def test_get_pending_approvals(self):
        """Test retrieving pending approvals."""
        logger = AuditLogger()
        
        logger.log_action(
            request_id="req-1",
            requester_id="micha",
            requester_email="micha@example.com",
            action_type=ActionType.EMAIL_SEND,
            action_target="user@example.com",
            action_parameters={},
        )
        
        logger.log_action(
            request_id="req-2",
            requester_id="micha",
            requester_email="micha@example.com",
            action_type=ActionType.EMAIL_SEND,
            action_target="user2@example.com",
            action_parameters={},
        )
        
        logger.log_approval_decision("req-2", approved=True, decision_maker="micha")
        
        pending = logger.get_pending_approvals()
        assert len(pending) == 1
        assert pending[0].request_id == "req-1"
    
    def test_get_stats(self):
        """Test audit statistics."""
        logger = AuditLogger()
        
        logger.log_action(
            request_id="req-1",
            requester_id="micha",
            requester_email="micha@example.com",
            action_type=ActionType.EMAIL_SEND,
            action_target="user@example.com",
            action_parameters={},
        )
        
        logger.log_denylist_hit("req-1", "Domain denied")
        
        stats = logger.get_stats(hours=24)
        assert stats["total_actions"] == 1
        assert stats["denylist_hits"] == 1


# ============================================================================
# Denylist Engine Tests
# ============================================================================

class TestDenylistEngine:
    """Test DenylistEngine functionality."""
    
    def test_domain_denylist_exact_match(self):
        """Test exact domain match."""
        engine = DenylistEngine()
        
        allowed, reason = engine.check_domain("malware.com")
        assert not allowed
        assert "malware.com" in reason
    
    def test_domain_denylist_subdomain_match(self):
        """Test subdomain match."""
        engine = DenylistEngine()
        
        allowed, reason = engine.check_domain("evil.malware.com")
        assert not allowed
        assert "subdomain" in reason.lower()
    
    def test_domain_allowed(self):
        """Test allowed domain."""
        engine = DenylistEngine()
        
        allowed, reason = engine.check_domain("gmail.com")
        assert allowed
        assert reason is None
    
    def test_content_denylist_match(self):
        """Test content keyword match."""
        engine = DenylistEngine()
        
        allowed, reason = engine.check_content("This is a ransomware attack")
        assert not allowed
        assert "ransomware" in reason.lower()
    
    def test_content_case_insensitive(self):
        """Test content check is case-insensitive."""
        engine = DenylistEngine()
        
        allowed, reason = engine.check_content("This is a RANSOMWARE attack")
        assert not allowed
    
    def test_path_denylist_match(self):
        """Test path denylist."""
        engine = DenylistEngine()
        
        allowed, reason = engine.check_path("/etc/shadow")
        assert not allowed
    
    def test_check_email_send_comprehensive(self):
        """Test comprehensive email_send check."""
        engine = DenylistEngine()
        
        # Check allowed email
        allowed, reason = engine.check_email_send(
            recipient="user@gmail.com",
            subject="Hello",
            body="This is a test email"
        )
        assert allowed
        
        # Check denied domain
        allowed, reason = engine.check_email_send(
            recipient="user@malware.com",
            subject="Phishing",
            body="Click here"
        )
        assert not allowed
    
    def test_denylist_stats(self):
        """Test denylist statistics."""
        engine = DenylistEngine()
        stats = engine.get_stats()
        
        assert stats["domain_count"] > 0
        assert stats["content_count"] > 0
        assert stats["path_count"] > 0


# ============================================================================
# Rate Limiter Tests
# ============================================================================

class TestRateLimiter:
    """Test RateLimiter functionality."""
    
    def test_register_user_default_tier(self):
        """Test registering a user with default tier."""
        limiter = RateLimiter()
        limiter.register_user("test-user")
        
        usage = limiter.get_usage("test-user")
        assert usage["tier"] == "basic"
    
    def test_register_user_custom_tier(self):
        """Test registering a user with custom tier."""
        limiter = RateLimiter()
        limiter.register_user("test-user", RateLimitTier.FREE)
        
        usage = limiter.get_usage("test-user")
        assert usage["tier"] == "free"
    
    def test_check_rate_limit_allowed(self):
        """Test rate limit check passes initially."""
        limiter = RateLimiter()
        limiter.register_user("test-user", RateLimitTier.FREE)
        
        allowed, reason = limiter.check_rate_limit("test-user")
        assert allowed
        assert reason is None
    
    def test_check_rate_limit_exceeded(self):
        """Test rate limit exceeded."""
        limiter = RateLimiter()
        limiter.register_user("test-user", RateLimitTier.FREE)  # 5/day
        
        # Record 5 actions
        for i in range(5):
            limiter.record_action("test-user")
        
        # 6th should fail
        allowed, reason = limiter.check_rate_limit("test-user")
        assert not allowed
        assert "exceeded" in reason.lower()
    
    def test_unlimited_tier(self):
        """Test unlimited tier has no limits."""
        limiter = RateLimiter()
        limiter.set_tier("admin", RateLimitTier.UNLIMITED)
        
        # Record 1000 actions
        for i in range(1000):
            limiter.record_action("admin")
        
        allowed, reason = limiter.check_rate_limit("admin")
        assert allowed
    
    def test_jarvis_unlimited(self):
        """Test that Jarvis has unlimited tier."""
        limiter = RateLimiter()
        
        usage = limiter.get_usage("jarvis")
        assert usage["status"] == "unlimited"
    
    def test_usage_percentage(self):
        """Test usage percentage calculation."""
        limiter = RateLimiter()
        limiter.register_user("test-user", RateLimitTier.FREE)  # 5/day
        
        limiter.record_action("test-user")
        usage = limiter.get_usage("test-user")
        
        assert usage["percentage"] == 20  # 1/5 = 20%
    
    def test_global_stats(self):
        """Test global statistics."""
        limiter = RateLimiter()
        limiter.register_user("user1", RateLimitTier.FREE)
        limiter.register_user("user2", RateLimitTier.BASIC)
        
        stats = limiter.get_global_stats()
        
        assert stats["total_users"] >= 2
        assert "users_by_tier" in stats


# ============================================================================
# Approval Engine Tests
# ============================================================================

class TestApprovalEngine:
    """Test ApprovalEngine functionality."""
    
    def test_determine_strategy_jarvis_auto(self):
        """Test that Jarvis actions are auto-approved."""
        engine = ApprovalEngine()
        
        strategy = engine.determine_strategy(
            requester_id="jarvis",
            action_type="email_send",
            risk_reasons=[],
        )
        
        assert strategy == ApprovalStrategy.AUTO_APPROVE
    
    def test_determine_strategy_low_risk_auto(self):
        """Test that low-risk actions are auto-approved."""
        engine = ApprovalEngine()
        
        strategy = engine.determine_strategy(
            requester_id="micha",
            action_type="email_draft",
            risk_reasons=[],
        )
        
        assert strategy == ApprovalStrategy.AUTO_APPROVE
    
    def test_determine_strategy_high_risk_manual(self):
        """Test that high-risk actions require manual approval."""
        engine = ApprovalEngine()
        
        strategy = engine.determine_strategy(
            requester_id="micha",
            action_type="email_send",
            risk_reasons=[],
        )
        
        assert strategy == ApprovalStrategy.MANUAL_APPROVAL
    
    @pytest.mark.asyncio
    async def test_request_approval_pending(self):
        """Test requesting approval creates pending entry."""
        engine = ApprovalEngine()
        
        approval_req = await engine.request_approval(
            request_id="req-123",
            requester_id="micha",
            action_type="email_send",
            action_target="user@example.com",
            action_parameters={"subject": "Test"},
        )
        
        assert approval_req.request_id == "req-123"
        assert approval_req.decision is None
        assert engine.get_pending_count() == 1
    
    def test_submit_approval_decision_approved(self):
        """Test submitting approval decision (approved)."""
        engine = ApprovalEngine()
        
        # Create pending approval
        asyncio.run(engine.request_approval(
            request_id="req-123",
            requester_id="micha",
            action_type="email_send",
            action_target="user@example.com",
            action_parameters={},
        ))
        
        # Submit approval
        success = engine.submit_approval_decision(
            request_id="req-123",
            decision_maker="micha",
            approved=True,
            reason="Looks good"
        )
        
        assert success
        assert engine.is_approved("req-123")
    
    def test_submit_approval_decision_denied(self):
        """Test submitting approval decision (denied)."""
        engine = ApprovalEngine()
        
        # Create pending approval
        asyncio.run(engine.request_approval(
            request_id="req-123",
            requester_id="micha",
            action_type="email_send",
            action_target="user@example.com",
            action_parameters={},
        ))
        
        # Submit denial
        success = engine.submit_approval_decision(
            request_id="req-123",
            decision_maker="micha",
            approved=False,
            reason="Too risky"
        )
        
        assert success
        assert engine.is_denied("req-123")
    
    def test_approval_timeout(self):
        """Test approval timeout after 24 hours."""
        engine = ApprovalEngine()
        engine.approval_timeout_hours = 0  # Immediate timeout for testing
        
        # Create pending approval
        asyncio.run(engine.request_approval(
            request_id="req-123",
            requester_id="micha",
            action_type="email_send",
            action_target="user@example.com",
            action_parameters={},
        ))
        
        # Try to get approval (should be expired)
        approval_req = engine.get_pending_approval("req-123")
        assert approval_req.decision == "timeout"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
