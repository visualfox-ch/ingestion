"""
Tests for CK02 Causal Event Schema v2

Tests all v2 enhancements:
- Priority 1: Causal links (typed relationships)
- Priority 2: Outcome quality metrics
- Priority 3: Integration fields (task_id, git_commit_hash, etc.)
- Priority 4: Temporal features (duration, end_timestamp)
- New endpoints: /causal/chain, /causal/counterfactual
"""

import pytest
from datetime import datetime, timezone
from uuid import uuid4

from app.models.causal_event import CausalEventCreate, CausalLink


class TestCausalEventV2Schema:
    """Test v2 Pydantic models."""
    
    def test_causal_link_creation(self):
        """Test CausalLink model."""
        link = CausalLink(
            target_event_id=str(uuid4()),
            link_type="causes",
            strength=0.95,
            inference_method="git_diff"
        )
        assert link.link_type == "causes"
        assert link.strength == 0.95
        assert link.inference_method == "git_diff"
    
    def test_causal_link_strength_validation(self):
        """Test strength score must be 0.0-1.0."""
        with pytest.raises(ValueError):
            CausalLink(
                target_event_id=str(uuid4()),
                link_type="causes",
                strength=1.5  # Invalid
            )
    
    def test_event_with_causal_links(self):
        """Test event creation with causal links."""
        event = CausalEventCreate(
            event_type="decision",
            actor="codex",
            description="Test decision",
            causal_links=[
                CausalLink(
                    target_event_id=str(uuid4()),
                    link_type="causes",
                    strength=0.9
                ),
                CausalLink(
                    target_event_id=str(uuid4()),
                    link_type="enables",
                    strength=0.7
                )
            ]
        )
        assert len(event.causal_links) == 2
        assert event.causal_links[0].link_type == "causes"
    
    def test_event_with_outcome_quality_metrics(self):
        """Test outcome quality fields."""
        event = CausalEventCreate(
            event_type="outcome",
            actor="system",
            description="Build completed",
            outcome="Build successful, 8s",
            outcome_success=True,
            outcome_quality_score=0.92,
            expected_outcome="Build < 10s",
            deviation_score=0.0
        )
        assert event.outcome_success is True
        assert event.outcome_quality_score == 0.92
        assert event.deviation_score == 0.0
    
    def test_event_with_integration_fields(self):
        """Test integration fields (task_id, git_commit, etc.)."""
        event = CausalEventCreate(
            event_type="action",
            actor="codex",
            description="Applied migration",
            task_id="T-20260205-101",
            git_commit_hash="abc123def456",
            proposal_id="PROP-2026-02-05-001",
            phase="Phase 19.5B"
        )
        assert event.task_id == "T-20260205-101"
        assert event.git_commit_hash == "abc123def456"
        assert event.proposal_id == "PROP-2026-02-05-001"
        assert event.phase == "Phase 19.5B"
    
    def test_event_with_temporal_features(self):
        """Test duration and end_timestamp."""
        now = datetime.now(timezone.utc)
        event = CausalEventCreate(
            event_type="action",
            actor="system",
            description="Long-running build",
            duration_seconds=135.5,
            timestamp=now,
            end_timestamp=now
        )
        assert event.duration_seconds == 135.5
        assert event.end_timestamp == now
    
    def test_event_normalization_with_v2_fields(self):
        """Test normalize() still works with v2 fields."""
        event = CausalEventCreate(
            event_type="decision",
            actor="codex",
            description="Test",
            outcome_quality_score=0.8,
            task_id="T-123"
        )
        normalized = event.normalize()
        assert normalized.event_id is not None  # Auto-generated
        assert normalized.timestamp is not None  # Auto-generated
        assert normalized.outcome_quality_score == 0.8
        assert normalized.task_id == "T-123"


class TestCausalEventV2API:
    """Test v2 API endpoints (requires running server)."""
    
    def test_create_event_with_v2_fields(self, client):
        """Test POST /causal/events with v2 fields."""
        response = client.post("/causal/events", json={
            "event_type": "decision",
            "actor": "codex",
            "description": "Test v2 event",
            "task_id": "T-20260205-TEST",
            "outcome_success": True,
            "outcome_quality_score": 0.9,
            "causal_links": [
                {
                    "target_event_id": str(uuid4()),
                    "link_type": "causes",
                    "strength": 0.85
                }
            ]
        })
        assert response.status_code == 201 or response.status_code == 200
        data = response.json()
        assert data["status"] == "created"
        assert data["event"]["task_id"] == "T-20260205-TEST"
    
    def test_list_events_with_v2_filters(self, client):
        """Test GET /causal/events with v2 query params."""
        # Filter by task_id
        response = client.get("/causal/events?task_id=T-20260205-TEST")
        assert response.status_code == 200
        data = response.json()
        assert "events" in data
        assert "total" in data
        
        # Filter by outcome_success
        response = client.get("/causal/events?outcome_success=true")
        assert response.status_code == 200
        
        # Filter by min_quality_score
        response = client.get("/causal/events?min_quality_score=0.8")
        assert response.status_code == 200
        
        # Filter by phase
        response = client.get("/causal/events?phase=Phase%2019.5B")
        assert response.status_code == 200
    
    def test_causal_chain_endpoint(self, client):
        """Test GET /causal/chain."""
        # Create two events with causal link
        event1_response = client.post("/causal/events", json={
            "event_type": "decision",
            "actor": "codex",
            "description": "Decision A"
        })
        event1_id = event1_response.json()["event"]["event_id"]
        
        event2_response = client.post("/causal/events", json={
            "event_type": "outcome",
            "actor": "system",
            "description": "Outcome B",
            "causal_links": [
                {
                    "target_event_id": event1_id,
                    "link_type": "caused_by",
                    "strength": 0.9
                }
            ]
        })
        
        # Query chain
        response = client.get(f"/causal/chain?from_event_id={event1_id}")
        assert response.status_code == 200
        data = response.json()
        assert "chain" in data
        assert "total_strength" in data
        assert "path_length" in data
        assert len(data["chain"]) >= 1
    
    def test_causal_chain_with_link_types_filter(self, client):
        """Test /causal/chain with link_types filter."""
        event_id = str(uuid4())
        response = client.get(
            f"/causal/chain?from_event_id={event_id}&link_types=causes,enables"
        )
        assert response.status_code == 200
        data = response.json()
        assert "chain" in data
    
    def test_counterfactual_endpoint(self, client):
        """Test POST /causal/counterfactual."""
        # Create an event
        event_response = client.post("/causal/events", json={
            "event_type": "decision",
            "actor": "codex",
            "description": "Decision to test",
            "outcome": "Test outcome"
        })
        event_id = event_response.json()["event"]["event_id"]
        
        # Analyze counterfactual
        response = client.post("/causal/counterfactual", json={
            "event_id": event_id,
            "hypothetical_action": "remove"
        })
        assert response.status_code == 200
        data = response.json()
        assert "original_outcome" in data
        assert "counterfactual_outcome" in data
        assert "impact_score" in data
        assert "affected_events" in data
        assert "confidence" in data
    
    def test_counterfactual_replace_action(self, client):
        """Test counterfactual with 'replace' action."""
        event_id = str(uuid4())
        response = client.post("/causal/counterfactual", json={
            "event_id": event_id,
            "hypothetical_action": "replace",
            "replacement_description": "Use different approach"
        })
        # Should work even if event doesn't exist (returns error gracefully)
        assert response.status_code in [200, 404]
    
    def test_counterfactual_invalid_action(self, client):
        """Test counterfactual with invalid action."""
        response = client.post("/causal/counterfactual", json={
            "event_id": str(uuid4()),
            "hypothetical_action": "invalid"
        })
        assert response.status_code == 400


class TestCausalEventV2Integration:
    """Integration tests for v2 features."""
    
    def test_full_causal_workflow(self, client):
        """
        Test complete workflow:
        1. Create decision event
        2. Create action event linked to decision
        3. Create outcome event with quality metrics
        4. Query causal chain
        5. Analyze counterfactual
        """
        # Step 1: Decision
        decision_response = client.post("/causal/events", json={
            "event_type": "decision",
            "actor": "codex",
            "description": "Decided to use BuildKit",
            "task_id": "T-20260205-WORKFLOW",
            "phase": "Ops Optimization"
        })
        assert decision_response.status_code in [200, 201]
        decision_id = decision_response.json()["event"]["event_id"]
        
        # Step 2: Action
        action_response = client.post("/causal/events", json={
            "event_type": "action",
            "actor": "copilot",
            "description": "Applied BuildKit to docker build",
            "task_id": "T-20260205-WORKFLOW",
            "git_commit_hash": "abc123",
            "causal_links": [
                {
                    "target_event_id": decision_id,
                    "link_type": "caused_by",
                    "strength": 0.95,
                    "inference_method": "manual"
                }
            ]
        })
        assert action_response.status_code in [200, 201]
        action_id = action_response.json()["event"]["event_id"]
        
        # Step 3: Outcome
        outcome_response = client.post("/causal/events", json={
            "event_type": "outcome",
            "actor": "system",
            "description": "Build completed in 8 seconds",
            "task_id": "T-20260205-WORKFLOW",
            "outcome": "Build successful, time: 8s",
            "outcome_success": True,
            "outcome_quality_score": 0.92,
            "expected_outcome": "Build < 10s",
            "deviation_score": 0.0,
            "duration_seconds": 8.0,
            "causal_links": [
                {
                    "target_event_id": action_id,
                    "link_type": "caused_by",
                    "strength": 0.9
                }
            ]
        })
        assert outcome_response.status_code in [200, 201]
        
        # Step 4: Query chain
        chain_response = client.get(f"/causal/chain?from_event_id={decision_id}&max_depth=5")
        assert chain_response.status_code == 200
        chain_data = chain_response.json()
        assert len(chain_data["chain"]) >= 1
        
        # Step 5: Counterfactual
        cf_response = client.post("/causal/counterfactual", json={
            "event_id": decision_id,
            "hypothetical_action": "remove"
        })
        assert cf_response.status_code == 200
        cf_data = cf_response.json()
        assert cf_data["impact_score"] >= 0.0


# Pytest fixtures

@pytest.fixture
def client():
    """FastAPI test client (requires TestClient to be set up)."""
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
