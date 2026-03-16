"""
Tests for Session Persistence Layer

Validates database operations for session storage and retrieval.
"""

import pytest
from datetime import datetime, timedelta

from app.session_state import SessionState, SessionConfig
from app.session_persistence import SessionRepository


class TestSessionRepository:
    """Test SessionRepository database operations."""

    @pytest.fixture
    def repo(self):
        """Create repository instance for tests."""
        return SessionRepository(SessionConfig())

    @pytest.fixture
    def sample_session(self):
        """Create a sample session for testing."""
        session = SessionState(user_id="user_test_123")
        session.add_message("user", "Hello, what's the weather?")
        session.add_message("assistant", "It's sunny and warm today!")
        session.facette_weights = {"casual": 0.7, "technical": 0.3}
        session.learned_facts_ids = [1, 2, 3]
        return session

    @pytest.mark.asyncio
    async def test_create_session(self, repo, sample_session):
        """Test creating and saving a session."""
        # Note: This test would need a real DB connection in production
        # For now, we test the logic
        assert sample_session.session_id is not None
        assert sample_session.user_id == "user_test_123"
        assert len(sample_session.conversation_history) == 2

    @pytest.mark.asyncio
    async def test_session_expiration(self, repo):
        """Test session expiration logic."""
        session = SessionState(user_id="user123")
        
        # Not expired (no expires_at)
        assert not session.is_expired()
        
        # Set expiration in future
        session.expires_at = datetime.utcnow() + timedelta(hours=1)
        assert not session.is_expired()
        
        # Set expiration in past
        session.expires_at = datetime.utcnow() - timedelta(hours=1)
        assert session.is_expired()

    @pytest.mark.asyncio
    async def test_session_config(self):
        """Test session configuration."""
        config = SessionConfig(
            inactivity_ttl_hours=12,
            max_messages_per_session=500,
        )
        
        assert config.inactivity_ttl_hours == 12
        assert config.max_messages_per_session == 500
        assert config.max_sessions_per_user == 50

    def test_session_serialization(self, sample_session):
        """Test session to/from persistence dict."""
        # Serialize
        data = sample_session.to_persistence_dict()
        
        assert data["user_id"] == "user_test_123"
        assert len(data["conversation_history"]) == 2
        assert data["facette_weights"]["casual"] == 0.7
        
        # Deserialize
        restored = SessionState.from_persistence_dict(data)
        
        assert restored.user_id == sample_session.user_id
        assert restored.session_id == sample_session.session_id
        assert len(restored.conversation_history) == 2
        assert restored.conversation_history[0].content == "Hello, what's the weather?"

    def test_conversation_context_generation(self, sample_session):
        """Test conversation context generation for prompt injection."""
        context = sample_session.get_conversation_context(max_messages=10)
        
        assert "Previous conversation context" in context
        assert "USER:" in context
        assert "ASSISTANT:" in context
        assert "Hello" in context or "weather" in context

    def test_facette_restoration_hint(self, sample_session):
        """Test facette weight restoration hint."""
        hint = sample_session.get_facette_restoration_hint()
        
        assert "Known user personality insights" in hint
        assert "casual" in hint
        assert "0.70" in hint

    def test_repository_config_defaults(self):
        """Test repository uses correct default config."""
        repo = SessionRepository()
        
        assert repo.config.inactivity_ttl_hours == 24
        assert repo.config.max_sessions_per_user == 50


class TestSessionLifecycle:
    """Integration tests for complete session lifecycle."""

    def test_full_session_lifecycle(self):
        """Test complete session workflow."""
        # Create
        session = SessionState(
            user_id="user_integration_test",
            metadata={"source": "api"},
        )
        
        assert session.session_id is not None
        
        # Add conversation
        session.add_message("user", "What time is it?")
        session.add_message("assistant", "It's 3 PM")
        session.add_message("user", "Thanks!")
        
        assert len(session.conversation_history) == 3
        
        # Set context
        session.facette_weights = {
            "friendly": 0.8,
            "formal": 0.2,
        }
        session.learned_facts_ids = [10, 20, 30]
        
        # Serialize
        data = session.to_persistence_dict()
        
        # Deserialize
        restored = SessionState.from_persistence_dict(data)
        
        # Verify
        assert restored.session_id == session.session_id
        assert restored.user_id == session.user_id
        assert len(restored.conversation_history) == 3
        assert restored.facette_weights["friendly"] == 0.8
        assert restored.learned_facts_ids == [10, 20, 30]

    def test_session_activity_tracking(self):
        """Test session activity tracking."""
        session = SessionState(user_id="user_activity_test")
        
        original_activity = session.last_activity
        
        # Simulate delay and activity
        import time
        time.sleep(0.01)
        session.update_activity()
        
        assert session.last_activity > original_activity

    def test_multiple_sessions_isolation(self):
        """Test that multiple sessions maintain separate context."""
        session1 = SessionState(user_id="user1")
        session2 = SessionState(user_id="user2")
        
        # Add different messages
        session1.add_message("user", "Session 1 message")
        session2.add_message("user", "Session 2 message")
        
        # Verify isolation
        assert session1.conversation_history[0].content != session2.conversation_history[0].content
        assert session1.session_id != session2.session_id
        assert session1.user_id != session2.user_id


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
