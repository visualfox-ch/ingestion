"""
Tests for SessionState model

Validates session creation, message management, and context retrieval.
"""

import pytest
from datetime import datetime, timedelta

from app.session_state import (
    Message,
    SessionState,
    SessionConfig,
    DEFAULT_SESSION_CONFIG,
)


class TestMessage:
    """Test Message model."""

    def test_message_creation(self):
        """Create a message with basic fields."""
        msg = Message(
            role="user",
            content="Hello, how are you?",
            timestamp=datetime.utcnow(),
        )
        assert msg.role == "user"
        assert msg.content == "Hello, how are you?"
        assert msg.metadata == {}

    def test_message_with_metadata(self):
        """Create message with metadata."""
        meta = {"intent": "greeting", "confidence": 0.95}
        msg = Message(
            role="assistant",
            content="I'm doing great!",
            timestamp=datetime.utcnow(),
            metadata=meta,
        )
        assert msg.metadata == meta


class TestSessionState:
    """Test SessionState model."""

    def test_session_creation(self):
        """Create a new session."""
        session = SessionState(user_id="user123")
        
        assert session.user_id == "user123"
        assert session.session_id is not None
        assert len(session.session_id) > 0
        assert session.conversation_history == []
        assert session.facette_weights == {}

    def test_session_is_expired(self):
        """Test session expiration logic."""
        session = SessionState(user_id="user123")
        
        # Not expired (no expires_at)
        assert not session.is_expired()
        
        # Set future expiration
        session.expires_at = datetime.utcnow() + timedelta(hours=1)
        assert not session.is_expired()
        
        # Set past expiration
        session.expires_at = datetime.utcnow() - timedelta(hours=1)
        assert session.is_expired()

    def test_update_activity(self):
        """Test activity timestamp update."""
        session = SessionState(user_id="user123")
        old_activity = session.last_activity
        
        # Wait a bit and update
        import time
        time.sleep(0.01)
        session.update_activity()
        
        assert session.last_activity > old_activity

    def test_add_message(self):
        """Test adding messages to conversation."""
        session = SessionState(user_id="user123")
        
        session.add_message("user", "What time is it?")
        assert len(session.conversation_history) == 1
        assert session.conversation_history[0].role == "user"
        assert session.conversation_history[0].content == "What time is it?"
        
        session.add_message("assistant", "It's 3 PM")
        assert len(session.conversation_history) == 2
        assert session.conversation_history[1].role == "assistant"

    def test_add_message_with_metadata(self):
        """Test adding message with metadata."""
        session = SessionState(user_id="user123")
        meta = {"intent": "time_query"}
        
        session.add_message("user", "What time is it?", metadata=meta)
        assert session.conversation_history[0].metadata == meta

    def test_get_conversation_context(self):
        """Test conversation context generation."""
        session = SessionState(user_id="user123")
        
        # Empty context
        context = session.get_conversation_context()
        assert "No prior conversation context" in context
        
        # With messages
        session.add_message("user", "Hello")
        session.add_message("assistant", "Hi there!")
        context = session.get_conversation_context()
        
        assert "Previous conversation context" in context
        assert "USER:" in context
        assert "ASSISTANT:" in context

    def test_get_facette_restoration_hint(self):
        """Test facette weight hint generation."""
        session = SessionState(user_id="user123")
        
        # No weights
        hint = session.get_facette_restoration_hint()
        assert "No prior personality data" in hint
        
        # With weights
        session.facette_weights = {
            "technical": 0.8,
            "casual": 0.3,
            "verbose": 0.6,
        }
        hint = session.get_facette_restoration_hint()
        
        assert "Known user personality insights" in hint
        assert "technical" in hint
        assert "0.80" in hint

    def test_to_persistence_dict(self):
        """Test conversion to persistence dict."""
        session = SessionState(
            user_id="user123",
            facette_weights={"technical": 0.8},
        )
        session.add_message("user", "Hello")
        
        data = session.to_persistence_dict()
        
        assert data["user_id"] == "user123"
        assert data["session_id"] == session.session_id
        assert len(data["conversation_history"]) == 1
        assert data["facette_weights"]["technical"] == 0.8

    def test_from_persistence_dict(self):
        """Test reconstruction from persistence dict."""
        # Create original session
        original = SessionState(user_id="user123")
        original.add_message("user", "Test message")
        original.facette_weights = {"technical": 0.8}
        
        # Convert to dict and reconstruct
        data = original.to_persistence_dict()
        restored = SessionState.from_persistence_dict(data)
        
        assert restored.user_id == original.user_id
        assert restored.session_id == original.session_id
        assert len(restored.conversation_history) == 1
        assert restored.conversation_history[0].content == "Test message"
        assert restored.facette_weights["technical"] == 0.8

    def test_session_config(self):
        """Test SessionConfig defaults."""
        config = SessionConfig()
        
        assert config.inactivity_ttl_hours == 24
        assert config.max_messages_per_session == 1000
        assert config.max_sessions_per_user == 50
        assert config.archive_after_days == 30
        assert config.auto_cleanup_enabled is True

    def test_session_config_custom(self):
        """Test SessionConfig customization."""
        config = SessionConfig(
            inactivity_ttl_hours=12,
            max_messages_per_session=500,
        )
        
        assert config.inactivity_ttl_hours == 12
        assert config.max_messages_per_session == 500
        assert config.max_sessions_per_user == 50  # Default


class TestSessionIntegration:
    """Integration tests for complete session workflow."""

    def test_full_session_lifecycle(self):
        """Test complete session: create → add messages → persist → restore."""
        # Create session
        session = SessionState(user_id="user_abc", metadata={"source": "web"})
        
        # Add conversation
        session.add_message("user", "What's the weather?")
        session.add_message("assistant", "It's sunny today")
        session.add_message("user", "Great! What about tomorrow?")
        session.add_message("assistant", "Rainy with chance of showers")
        
        # Add context
        session.facette_weights = {
            "casual": 0.7,
            "detailed": 0.5,
        }
        session.learned_facts_ids = [1, 2, 3]
        
        # Persist
        data = session.to_persistence_dict()
        
        # Verify persistence dict
        assert data["user_id"] == "user_abc"
        assert len(data["conversation_history"]) == 4
        assert data["metadata"]["source"] == "web"
        
        # Restore
        restored = SessionState.from_persistence_dict(data)
        
        # Verify restoration
        assert restored.user_id == "user_abc"
        assert restored.session_id == session.session_id
        assert len(restored.conversation_history) == 4
        assert restored.conversation_history[0].content == "What's the weather?"
        assert restored.facette_weights["casual"] == 0.7
        assert restored.learned_facts_ids == [1, 2, 3]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
