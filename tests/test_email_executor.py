"""
Tests for Email Executor — Jarvis' First Real Action!

Tests:
- Email send success (mocked SMTP)
- Email send failures (SMTP errors, validation errors)
- Configuration validation
- Integration with execute_action workflow

Author: GitHub Copilot
Date: Feb 5, 2026
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock
import aiosmtplib

from app.execute_action.executors.email_executor import (
    execute_email_send,
    validate_email_config,
)


class TestEmailExecutor:
    """Test email executor functionality."""
    
    @pytest.mark.asyncio
    @patch("app.execute_action.executors.email_executor.aiosmtplib.SMTP")
    @patch.dict("os.environ", {
        "SMTP_HOST": "smtp.test.com",
        "SMTP_PORT": "587",
        "SMTP_USER": "test@test.com",
        "SMTP_PASSWORD": "testpass",
        "SMTP_FROM": "jarvis@test.com",
    })
    async def test_email_send_success(self, mock_smtp_class):
        """Test successful email send."""
        # Mock SMTP client
        mock_smtp = AsyncMock()
        mock_smtp_class.return_value.__aenter__.return_value = mock_smtp
        
        # Execute email send
        success, error = await execute_email_send(
            target="recipient@test.com",
            params={
                "subject": "Test Email",
                "body": "This is a test message",
            }
        )
        
        # Verify success
        assert success is True
        assert error is None
        
        # Verify SMTP was called
        mock_smtp.login.assert_called_once()
        mock_smtp.send_message.assert_called_once()
    
    @pytest.mark.asyncio
    @patch("app.execute_action.executors.email_executor.aiosmtplib.SMTP")
    @patch.dict("os.environ", {
        "SMTP_HOST": "smtp.test.com",
        "SMTP_USER": "test@test.com",
        "SMTP_PASSWORD": "testpass",
    })
    async def test_email_send_html(self, mock_smtp_class):
        """Test HTML email send."""
        mock_smtp = AsyncMock()
        mock_smtp_class.return_value.__aenter__.return_value = mock_smtp
        
        success, error = await execute_email_send(
            target="recipient@test.com",
            params={
                "subject": "HTML Email",
                "body": "<h1>Hello</h1><p>This is HTML</p>",
                "html": "true",
            }
        )
        
        assert success is True
        assert error is None
    
    @pytest.mark.asyncio
    async def test_email_send_missing_config(self):
        """Test email send without SMTP config."""
        with patch.dict("os.environ", {}, clear=True):
            # Force reload to pick up empty env
            import importlib
            import app.execute_action.executors.email_executor as email_module
            importlib.reload(email_module)
            
            success, error = await email_module.execute_email_send(
                target="test@test.com",
                params={"subject": "Test", "body": "Test"}
            )
            
            assert success is False
            assert "not configured" in error.lower()
    
    @pytest.mark.asyncio
    @patch.dict("os.environ", {
        "SMTP_USER": "test@test.com",
        "SMTP_PASSWORD": "testpass",
    })
    async def test_email_send_missing_subject(self):
        """Test email send without subject."""
        success, error = await execute_email_send(
            target="recipient@test.com",
            params={"body": "Test message"}
        )
        
        assert success is False
        assert "subject" in error.lower()
    
    @pytest.mark.asyncio
    @patch.dict("os.environ", {
        "SMTP_USER": "test@test.com",
        "SMTP_PASSWORD": "testpass",
    })
    async def test_email_send_missing_body(self):
        """Test email send without body."""
        success, error = await execute_email_send(
            target="recipient@test.com",
            params={"subject": "Test"}
        )
        
        assert success is False
        assert "body" in error.lower()
    
    @pytest.mark.asyncio
    @patch.dict("os.environ", {
        "SMTP_USER": "test@test.com",
        "SMTP_PASSWORD": "testpass",
    })
    async def test_email_send_invalid_recipient(self):
        """Test email send with invalid recipient."""
        success, error = await execute_email_send(
            target="not-an-email",
            params={"subject": "Test", "body": "Test"}
        )
        
        assert success is False
        assert "invalid" in error.lower()
    
    @pytest.mark.asyncio
    @patch("app.execute_action.executors.email_executor.aiosmtplib.SMTP")
    @patch.dict("os.environ", {
        "SMTP_USER": "test@test.com",
        "SMTP_PASSWORD": "testpass",
    })
    async def test_email_send_smtp_error(self, mock_smtp_class):
        """Test email send with SMTP error."""
        mock_smtp = AsyncMock()
        mock_smtp.send_message.side_effect = aiosmtplib.SMTPException("Connection failed")
        mock_smtp_class.return_value.__aenter__.return_value = mock_smtp
        
        success, error = await execute_email_send(
            target="recipient@test.com",
            params={"subject": "Test", "body": "Test"}
        )
        
        assert success is False
        assert "smtp error" in error.lower()
    
    @patch.dict("os.environ", {
        "SMTP_HOST": "smtp.test.com",
        "SMTP_PORT": "587",
        "SMTP_USER": "test@test.com",
        "SMTP_PASSWORD": "testpass",
    })
    def test_validate_email_config_success(self):
        """Test email config validation (valid config)."""
        import importlib
        import app.execute_action.executors.email_executor as email_module
        importlib.reload(email_module)
        
        valid, error = email_module.validate_email_config()
        assert valid is True
        assert error is None
    
    @patch.dict("os.environ", {}, clear=True)
    def test_validate_email_config_missing_host(self):
        """Test email config validation (missing SMTP_HOST)."""
        import importlib
        import app.execute_action.executors.email_executor as email_module
        importlib.reload(email_module)
        
        valid, error = email_module.validate_email_config()
        assert valid is False
        assert "smtp_user" in error.lower() or "smtp_host" in error.lower()


class TestEmailExecutorIntegration:
    """Integration tests with execute_action router."""
    
    @pytest.mark.asyncio
    @patch("app.execute_action.executors.email_executor.aiosmtplib.SMTP")
    @patch.dict("os.environ", {
        "SMTP_USER": "test@test.com",
        "SMTP_PASSWORD": "testpass",
    })
    async def test_execute_router_email_send(self, mock_smtp_class):
        """Test email send through execute_router."""
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from app.execute_action import router as execute_router
        from app.execute_action import (
            get_audit_logger,
            get_denylist_engine,
            get_rate_limiter,
            get_approval_engine,
        )
        
        # Mock SMTP
        mock_smtp = AsyncMock()
        mock_smtp_class.return_value.__aenter__.return_value = mock_smtp
        
        # Create test app
        app = FastAPI()
        app.include_router(execute_router)
        
        # Initialize singletons
        get_audit_logger()
        get_denylist_engine()
        get_rate_limiter()
        get_approval_engine()
        
        client = TestClient(app)
        
        # Submit email send action (manual approval required)
        response = client.post("/api/execute/action", json={
            "action_type": "email_send",
            "action_target": "micha@test.com",
            "action_parameters": {
                "subject": "Test from Jarvis",
                "body": "Integration test email"
            },
        })
        
        # Should be pending approval
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "pending"
        assert data["approval_needed"] is True
        
        request_id = data["request_id"]
        
        # Approve action
        response = client.post("/api/execute/approve", json={
            "request_id": request_id,
            "approved": True,
            "reason": "Test approval"
        })
        
        # Should execute successfully
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "executed"
        
        # Verify SMTP was called
        mock_smtp.send_message.assert_called_once()
