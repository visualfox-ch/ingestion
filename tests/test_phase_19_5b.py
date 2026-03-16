"""End-to-end tests for Phase 19.5B: State & Persistence."""

import pytest
from datetime import datetime
from app.session_state import SessionState, Message


class TestSessionState:
    """Test SessionState model functionality."""
    
    def test_session_creation(self):
        """Test creating a new session."""
        session = SessionState(user_id="test_user")
        
        assert session.user_id == "test_user"
        assert len(session.session_id) > 0
        assert session.created_at is not None
        assert session.conversation_history == []
        assert session.facette_weights == {}
    
    def test_add_message(self):
        """Test adding messages to session."""
        session = SessionState(user_id="test_user")
        
        session.add_message("user", "Hello")
        assert len(session.conversation_history) == 1
        
        msg = session.conversation_history[0]
        assert msg.role == "user"
        assert msg.content == "Hello"
        
        session.add_message("assistant", "Hi there!")
        assert len(session.conversation_history) == 2
    
    def test_update_facettes(self):
        """Test updating facette weights."""
        session = SessionState(user_id="test_user")

        weights = {"technical": 0.8, "casual": 0.2}
        session.facette_weights.update(weights)

        assert session.facette_weights["technical"] == 0.8
        assert session.facette_weights["casual"] == 0.2
    
    def test_conversation_context_generation(self):
        """Test generating conversation context."""
        session = SessionState(user_id="test_user")
        
        # No messages
        context = session.get_conversation_context()
        assert "No prior conversation" in context
        
        # With messages
        session.add_message("user", "First question")
        session.add_message("assistant", "First answer")
        context = session.get_conversation_context(max_messages=2)
        
        assert "Previous conversation context" in context
        assert "USER: First question" in context
        assert "ASSISTANT: First answer" in context
    
    def test_facette_restoration_hint(self):
        """Test generating facette restoration hints."""
        session = SessionState(user_id="test_user")

        # No facettes
        hint = session.get_facette_restoration_hint()
        assert "No prior personality" in hint

        # With facettes
        session.facette_weights.update({
            "technical": 0.9,
            "casual": 0.3,
            "formal": 0.1
        })
        hint = session.get_facette_restoration_hint()

        assert "Known user personality" in hint
        assert "technical: 0.90" in hint
    
    def test_session_serialization(self):
        """Test session can be serialized to dict."""
        session = SessionState(user_id="test_user")
        session.add_message("user", "Test")

        data = session.to_persistence_dict()

        assert data["user_id"] == "test_user"
        assert data["session_id"] == session.session_id
        assert len(data["conversation_history"]) == 1


class TestSessionStore:
    """Test SessionStore (persistence layer)."""

    @pytest.mark.integration
    @pytest.mark.requires_db
    def test_session_store_initialization(self):
        """Test session store can be initialized."""
        from app.session_store import get_session_store

        store = get_session_store()
        assert store is not None

    @pytest.mark.integration
    @pytest.mark.requires_db
    def test_save_and_load_session(self):
        """Test saving and loading a session."""
        from app.session_store import SessionStore
        import os

        # Skip if no DB available
        if not os.environ.get("POSTGRES_HOST"):
            pytest.skip("No database connection available")

        store = SessionStore()
        session = SessionState(user_id="test_user")
        session.add_message("user", "Test message")

        # Save (requires DB connection)
        session_id = store.save_session(session)
        assert session_id == session.session_id

        # Load
        loaded = store.load_session(session_id)
        # Note: Currently returns None (placeholder), full DB implementation follows


class TestContextInjection:
    """Test context injection middleware."""
    
    def test_context_injection_imports(self):
        """Test context injection module imports."""
        from app.context_injection import (
            ContextInjectionMiddleware,
            get_session_from_request,
            get_session_id_from_request,
            mark_session_updated
        )
        
        assert ContextInjectionMiddleware is not None
        assert get_session_from_request is not None


# Integration tests
class TestPhase19_5B_Integration:
    """Integration tests for Phase 19.5B."""
    
    def test_full_session_lifecycle(self):
        """Test complete session lifecycle."""
        # 1. Create session
        session = SessionState(user_id="integration_test")
        assert session.user_id == "integration_test"

        # 2. Add messages
        session.add_message("user", "What's the weather?")
        session.add_message("assistant", "I don't have weather data.")
        assert len(session.conversation_history) == 2

        # 3. Update facettes
        session.facette_weights.update({"helpfulness": 0.5})
        assert "helpfulness" in session.facette_weights

        # 4. Serialize
        data = session.to_persistence_dict()
        assert data["user_id"] == "integration_test"
        assert len(data["conversation_history"]) == 2

        # 5. Could deserialize from data
        # (Full deserialization requires DB layer)
    
    def test_session_state_immutability(self):
        """Test that session updates are tracked."""
        session = SessionState(user_id="test")
        original_time = session.last_activity
        
        # Update should change timestamp
        session.add_message("user", "Hello")
        assert session.last_activity > original_time


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
