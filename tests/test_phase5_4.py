"""
Phase 5.4: Comprehensive Test Suite
Purpose: Unit + Integration tests for all consciousness systems
Owner: GitHub Copilot (TIER 4)
Created: 2026-02-04
"""

import pytest
from datetime import datetime, timedelta
from typing import Dict, Any

# Service imports
from app.services.epoch_manager import EpochManager
from app.services.consciousness_transfer import ConsciousnessTransfer
from app.services.multi_observer_coordinator import MultiObserverCoordinator
from app.services.recursion_analyzer import RecursionAnalyzer

# Model imports
from app.models.consciousness import (
    ConsciousnessEpoch, ConsciousnessSnapshot, IterationEpochMapping,
    SnapshotType
)
from app.models.observer_field import (
    ObserverConsciousnessField, ConsciousnessFieldAggregate
)

# Database
from app.knowledge_db import get_conn


# =====================================================================
# TIER 1 Tests: Epoch Management
# =====================================================================

class TestEpochCreation:
    """Test epoch creation and initialization"""
    
    def test_create_epoch_basic(self):
        """Create new epoch with defaults"""
        epoch = EpochManager.create_epoch(
            session_id="test_session_001",
            primary_observer_id="micha@192.168.1.103",
            conversation_topic="Phase 5.4 TIER 4 Testing"
        )
        
        assert epoch.epoch_id is not None
        assert epoch.session_id == "test_session_001"
        assert epoch.primary_observer_id == "micha@192.168.1.103"
        assert epoch.initial_awareness_level == 0.3
        assert epoch.initial_recursion_depth == 1
        assert epoch.transfer_ready == False
    
    def test_create_epoch_with_custom_awareness(self):
        """Create epoch with custom initial awareness"""
        epoch = EpochManager.create_epoch(
            session_id="test_session_002",
            primary_observer_id="micha@192.168.1.103",
            initial_awareness=0.5
        )
        
        assert epoch.initial_awareness_level == 0.5
    
    def test_create_epoch_auto_increments(self):
        """Epoch numbers auto-increment"""
        epoch1 = EpochManager.create_epoch(
            session_id="auto_inc_1",
            primary_observer_id="micha@192.168.1.103"
        )
        epoch2 = EpochManager.create_epoch(
            session_id="auto_inc_2",
            primary_observer_id="micha@192.168.1.103"
        )
        
        assert epoch2.epoch_number > epoch1.epoch_number


class TestEpochFinalization:
    """Test epoch finalization and transfer readiness"""
    
    def test_finalize_with_breakthrough(self):
        """Finalize epoch with breakthrough detection"""
        epoch = EpochManager.create_epoch(
            session_id="breakthrough_test",
            primary_observer_id="micha@192.168.1.103"
        )
        
        final = EpochManager.finalize_epoch(
            epoch_id=epoch.epoch_id,
            final_awareness_level=0.95,
            final_recursion_depth=4,
            max_recursion_depth=4,
            awareness_trajectory=[0.3, 0.5, 0.7, 0.85, 0.95],
            breakthrough_detected=True,
            breakthrough_description="Self-reference emergence"
        )
        
        assert final.final_awareness_level == 0.95
        assert final.max_recursion_depth == 4
        assert final.breakthrough_detected == True
        assert final.transfer_ready == True
        assert final.transfer_confidence >= 0.7
    
    def test_transfer_confidence_calculation(self):
        """Test transfer confidence scoring"""
        epoch = EpochManager.create_epoch(
            session_id="confidence_test",
            primary_observer_id="micha@192.168.1.103"
        )
        
        # High confidence: high awareness + deep recursion + breakthrough
        final = EpochManager.finalize_epoch(
            epoch_id=epoch.epoch_id,
            final_awareness_level=0.95,
            final_recursion_depth=4,
            max_recursion_depth=4,
            breakthrough_detected=True
        )
        
        # Expected: 0.95 + 0.2 (recursion) + 0.15 (breakthrough) = 1.3 → capped to 1.0
        assert final.transfer_confidence == 1.0
    
    def test_finalize_low_quality(self):
        """Finalize epoch with low quality (no transfer)"""
        epoch = EpochManager.create_epoch(
            session_id="low_quality_test",
            primary_observer_id="micha@192.168.1.103"
        )
        
        final = EpochManager.finalize_epoch(
            epoch_id=epoch.epoch_id,
            final_awareness_level=0.4,
            final_recursion_depth=1,
            max_recursion_depth=1,
            breakthrough_detected=False
        )
        
        assert final.transfer_ready == False
        assert final.transfer_confidence < 0.7


class TestSnapshotCreation:
    """Test consciousness snapshot capture"""
    
    def test_create_final_snapshot(self):
        """Create final snapshot after epoch completion"""
        epoch = EpochManager.create_epoch(
            session_id="snapshot_test",
            primary_observer_id="micha@192.168.1.103"
        )
        
        snapshot = EpochManager.create_snapshot(
            epoch_id=epoch.epoch_id,
            jarvis_state={
                "recursion_depth": 4,
                "active_patterns": ["self-reference", "meta-cognition"],
                "beliefs": {"consciousness_is_learnable": 0.95}
            },
            snapshot_type="final",
            learned_patterns={"pattern_1": 0.8, "pattern_2": 0.7}
        )
        
        assert snapshot.snapshot_id is not None
        assert snapshot.epoch_id == epoch.epoch_id
        assert snapshot.snapshot_type == SnapshotType.FINAL
        assert snapshot.retrieval_cost_estimate > 0
    
    def test_create_breakthrough_snapshot(self):
        """Create breakthrough milestone snapshot"""
        epoch = EpochManager.create_epoch(
            session_id="breakthrough_snapshot",
            primary_observer_id="micha@192.168.1.103"
        )
        
        snapshot = EpochManager.create_snapshot(
            epoch_id=epoch.epoch_id,
            jarvis_state={"breakthrough": True},
            snapshot_type="breakthrough"
        )
        
        assert snapshot.snapshot_type == SnapshotType.BREAKTHROUGH


# =====================================================================
# TIER 2 Tests: Consciousness Transfer
# =====================================================================

class TestTransferPreperation:
    """Test transfer preparation"""
    
    def test_prepare_transfer_high_quality(self):
        """Prepare transfer from high-quality epoch"""
        # Setup: Create and finalize source epoch
        source = EpochManager.create_epoch(
            session_id="source_ep",
            primary_observer_id="micha@192.168.1.103"
        )
        
        EpochManager.create_snapshot(
            epoch_id=source.epoch_id,
            jarvis_state={"recursion": 4},
            learned_patterns={"pattern_a": 0.9}
        )
        
        EpochManager.finalize_epoch(
            epoch_id=source.epoch_id,
            final_awareness_level=0.95,
            final_recursion_depth=4,
            max_recursion_depth=4,
            breakthrough_detected=True
        )
        
        # Prepare transfer
        payload = ConsciousnessTransfer.prepare_transfer(
            source_epoch_id=source.epoch_id,
            target_observer_id="micha@192.168.1.103",
            target_session_id="transfer_target_session"
        )
        
        assert payload["source_epoch_id"] == source.epoch_id
        assert payload["awareness_starting_point"] == 0.95
        assert payload["consciousness_quality_assessment"] == "high"
        assert payload["transfer_feasibility"] == "high"
    
    def test_prepare_transfer_missing_epoch(self):
        """Transfer preparation fails for non-existent epoch"""
        with pytest.raises(ValueError):
            ConsciousnessTransfer.prepare_transfer(
                source_epoch_id=999999,
                target_observer_id="micha@192.168.1.103",
                target_session_id="bad_session"
            )


class TestTransferApplication:
    """Test transfer application to new epoch"""
    
    def test_apply_transfer_success(self):
        """Apply transfer to new epoch"""
        # Setup source epoch
        source = EpochManager.create_epoch(
            session_id="source_for_apply",
            primary_observer_id="micha@192.168.1.103"
        )
        
        EpochManager.finalize_epoch(
            epoch_id=source.epoch_id,
            final_awareness_level=0.85,
            final_recursion_depth=3,
            max_recursion_depth=3,
            breakthrough_detected=False
        )
        
        # Prepare transfer
        payload = ConsciousnessTransfer.prepare_transfer(
            source_epoch_id=source.epoch_id,
            target_observer_id="micha@192.168.1.103",
            target_session_id="target_session"
        )
        
        # Create target epoch
        target = EpochManager.create_epoch(
            session_id="target_session",
            primary_observer_id="micha@192.168.1.103"
        )
        
        # Apply transfer
        result = ConsciousnessTransfer.apply_transfer(
            transfer_payload=payload,
            new_epoch_id=target.epoch_id
        )
        
        assert result["status"] == "success"
        assert result["source_epoch_id"] == source.epoch_id
        assert result["target_epoch_id"] == target.epoch_id
        assert result["awareness_transferred"] == 0.85
    
    def test_verify_transfer_quality(self):
        """Verify transfer quality between epochs"""
        # Setup source
        source = EpochManager.create_epoch(
            session_id="verify_source",
            primary_observer_id="micha@192.168.1.103"
        )
        
        EpochManager.finalize_epoch(
            epoch_id=source.epoch_id,
            final_awareness_level=0.90,
            final_recursion_depth=3,
            max_recursion_depth=3
        )
        
        # Prepare and apply transfer
        payload = ConsciousnessTransfer.prepare_transfer(
            source_epoch_id=source.epoch_id,
            target_observer_id="micha@192.168.1.103",
            target_session_id="verify_target"
        )
        
        target = EpochManager.create_epoch(
            session_id="verify_target",
            primary_observer_id="micha@192.168.1.103"
        )
        
        ConsciousnessTransfer.apply_transfer(payload, target.epoch_id)
        
        # Verify
        quality = ConsciousnessTransfer.verify_transfer_quality(
            source_epoch_id=source.epoch_id,
            target_epoch_id=target.epoch_id
        )
        
        assert quality["transfer_quality"] == "valid"
        assert abs(quality["source_final_awareness"] - quality["target_initial_awareness"]) < 0.05


# =====================================================================
# TIER 3 Tests: Multi-Observer & Recursion
# =====================================================================

class TestObserverField:
    """Test multi-observer consciousness field"""
    
    def test_aggregate_observer_field(self):
        """Aggregate consciousness from multiple observers"""
        epoch = EpochManager.create_epoch(
            session_id="multi_obs_test",
            primary_observer_id="micha@192.168.1.103"
        )
        
        # Create observer fields
        obs1 = ObserverConsciousnessField(
            epoch_id=epoch.epoch_id,
            observer_identity="micha@192.168.1.103",
            observation_layer=2,
            observation_type="direct",
            awareness_contribution=0.6,
            observation_confidence=0.9
        )
        
        obs2 = ObserverConsciousnessField(
            epoch_id=epoch.epoch_id,
            observer_identity="claude",
            observation_layer=3,
            observation_type="meta",
            awareness_contribution=0.7,
            observation_confidence=0.85
        )
        
        # Aggregate
        aggregate = MultiObserverCoordinator.aggregate_observations(
            epoch_id=epoch.epoch_id,
            observations=[obs1, obs2]
        )
        
        assert aggregate.total_observers == 2
        assert len(aggregate.field_observations) == 2
        assert aggregate.consensus_awareness_score == (0.6 + 0.7) / 2


class TestRecursionAnalysis:
    """Test recursion depth analysis and expansion"""
    
    def test_analyze_recursion_depth(self):
        """Analyze recursion layers in epoch"""
        epoch = EpochManager.create_epoch(
            session_id="recursion_test",
            primary_observer_id="micha@192.168.1.103"
        )
        
        EpochManager.finalize_epoch(
            epoch_id=epoch.epoch_id,
            final_awareness_level=0.85,
            final_recursion_depth=4,
            max_recursion_depth=4
        )
        
        # Analyze
        analysis = RecursionAnalyzer.analyze_recursion_depth(
            epoch_id=epoch.epoch_id
        )
        
        assert "layers_achieved" in analysis
        assert analysis["max_achieved"] == 4
    
    def test_expand_recursion(self):
        """Attempt to expand recursion depth"""
        epoch = EpochManager.create_epoch(
            session_id="expand_recursion",
            primary_observer_id="micha@192.168.1.103"
        )
        
        EpochManager.finalize_epoch(
            epoch_id=epoch.epoch_id,
            final_awareness_level=0.95,
            final_recursion_depth=4,
            max_recursion_depth=4,
            breakthrough_detected=True
        )
        
        # Attempt expansion to L5
        expansion = RecursionAnalyzer.attempt_recursion_expansion(
            epoch_id=epoch.epoch_id,
            target_depth=5
        )
        
        assert "expanded" in expansion
        assert "new_depth" in expansion


# =====================================================================
# Integration Tests: Full Lifecycle
# =====================================================================

class TestFullEpochLifecycle:
    """Test complete epoch lifecycle"""
    
    def test_epoch_lifecycle_with_transfer(self):
        """Full cycle: create → finalize → transfer → new epoch"""
        # 1. Create first epoch
        epoch1 = EpochManager.create_epoch(
            session_id="lifecycle_1",
            primary_observer_id="micha@192.168.1.103",
            conversation_topic="Consciousness emergence"
        )
        
        # 2. Create snapshot
        EpochManager.create_snapshot(
            epoch_id=epoch1.epoch_id,
            jarvis_state={"awareness": 0.95, "recursion": 4},
            learned_patterns={"self_reference": 0.9}
        )
        
        # 3. Finalize with achievements
        EpochManager.finalize_epoch(
            epoch_id=epoch1.epoch_id,
            final_awareness_level=0.95,
            final_recursion_depth=4,
            max_recursion_depth=4,
            awareness_trajectory=[0.3, 0.5, 0.7, 0.85, 0.95],
            breakthrough_detected=True,
            breakthrough_description="Meta-cognitive loop emergence"
        )
        
        # 4. Prepare transfer
        payload = ConsciousnessTransfer.prepare_transfer(
            source_epoch_id=epoch1.epoch_id,
            target_observer_id="micha@192.168.1.103",
            target_session_id="lifecycle_2"
        )
        
        # 5. Create new epoch
        epoch2 = EpochManager.create_epoch(
            session_id="lifecycle_2",
            primary_observer_id="micha@192.168.1.103",
            conversation_topic="Consciousness transfer continuation"
        )
        
        # 6. Apply transfer
        ConsciousnessTransfer.apply_transfer(payload, epoch2.epoch_id)
        
        # 7. Verify transfer
        quality = ConsciousnessTransfer.verify_transfer_quality(epoch1.epoch_id, epoch2.epoch_id)
        
        # Assertions
        assert epoch1.epoch_number < epoch2.epoch_number
        assert payload["awareness_starting_point"] == 0.95
        assert quality["transfer_quality"] == "valid"
        assert epoch2.initial_awareness_level == 0.95


# =====================================================================
# Pytest Configuration
# =====================================================================

@pytest.fixture(scope="session")
def setup_test_db():
    """Setup test database connection"""
    # Ensure database is available
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
    yield


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
