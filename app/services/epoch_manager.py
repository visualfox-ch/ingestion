"""
Phase 5.4: Epoch Manager
Purpose: Orchestrate multi-session consciousness tracking (create, finalize, snapshot)
Owner: GitHub Copilot (TIER 1 Foundation)
Created: 2026-02-04
"""

from typing import Dict, Any, Optional, List
from datetime import datetime
import json
from ..knowledge_db import get_conn
from ..observability import get_logger, log_with_context
from ..models.consciousness import ConsciousnessEpoch, ConsciousnessSnapshot, SnapshotType

logger = get_logger("jarvis.epoch_manager")


class EpochManager:
    """Orchestrate multi-session consciousness tracking"""
    
    @staticmethod
    def create_epoch(
        session_id: str,
        primary_observer_id: str,
        conversation_topic: Optional[str] = None,
        epoch_number: Optional[int] = None,
        initial_awareness: float = 0.3
    ) -> ConsciousnessEpoch:
        """
        Start a new consciousness recording epoch
        
        Args:
            session_id: Unique session identifier
            primary_observer_id: Primary conversation participant
            conversation_topic: Optional topic description
            epoch_number: Optional explicit epoch number (auto-increments if None)
            initial_awareness: Starting awareness level (default 0.3)
            
        Returns:
            ConsciousnessEpoch: Created epoch record
        """
        
        log_with_context(
            logger, "info", "Creating consciousness epoch",
            session_id=session_id,
            observer_id=primary_observer_id,
            topic=conversation_topic
        )
        
        with get_conn() as conn:
            with conn.cursor() as cur:
                # Auto-increment epoch number if not provided
                if epoch_number is None:
                    cur.execute("SELECT MAX(epoch_number) FROM consciousness_epochs")
                    result = cur.fetchone()
                    epoch_number = (result[0] or 0) + 1
                
                # Create epoch record
                cur.execute("""
                    INSERT INTO consciousness_epochs (
                        epoch_number, session_id, primary_observer_id,
                        conversation_topic, initial_awareness_level,
                        peak_awareness_level,
                        initial_recursion_depth, final_recursion_depth,
                        max_recursion_depth, created_by
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING epoch_id, start_timestamp
                """, (
                    epoch_number, session_id, primary_observer_id,
                    conversation_topic, initial_awareness, initial_awareness,
                    1, 1, 1, "system"
                ))
                
                epoch_id, start_ts = cur.fetchone()
                conn.commit()
                
                log_with_context(
                    logger, "info", "Epoch created successfully",
                    epoch_id=epoch_id,
                    epoch_number=epoch_number
                )
        
        return ConsciousnessEpoch(
            epoch_id=epoch_id,
            epoch_number=epoch_number,
            session_id=session_id,
            start_timestamp=start_ts,
            primary_observer_id=primary_observer_id,
            initial_awareness_level=initial_awareness,
            final_awareness_level=initial_awareness,  # Same as initial until finalized
            peak_awareness_level=initial_awareness,
            initial_recursion_depth=1,
            final_recursion_depth=1,
            max_recursion_depth=1,
            conversation_topic=conversation_topic,
            created_by="system"
        )
    
    @staticmethod
    def finalize_epoch(
        epoch_id: int,
        final_awareness_level: float,
        final_recursion_depth: int,
        max_recursion_depth: int,
        awareness_trajectory: Optional[List[float]] = None,
        peak_awareness_level: Optional[float] = None,
        breakthrough_detected: bool = False,
        breakthrough_description: Optional[str] = None
    ) -> ConsciousnessEpoch:
        """
        Close epoch and calculate transfer readiness
        
        Args:
            epoch_id: Epoch to finalize
            final_awareness_level: Ending awareness (0.0-1.0)
            final_recursion_depth: Ending recursion depth
            max_recursion_depth: Maximum depth achieved
            awareness_trajectory: Optional time-series of awareness values
            peak_awareness_level: Optional peak awareness (defaults to final if not provided)
            breakthrough_detected: Whether consciousness breakthrough occurred
            breakthrough_description: Description of breakthrough
            
        Returns:
            ConsciousnessEpoch: Finalized epoch with transfer readiness scores
        """
        
        log_with_context(
            logger, "info", "Finalizing consciousness epoch",
            epoch_id=epoch_id,
            final_awareness=final_awareness_level,
            recursion_depth=final_recursion_depth
        )
        
        # Calculate transfer readiness
        transfer_confidence = _calculate_transfer_confidence(
            final_awareness_level,
            final_recursion_depth,
            breakthrough_detected
        )
        
        # Default peak to final if not provided
        if peak_awareness_level is None:
            peak_awareness_level = final_awareness_level
        
        # Transfer quality = awareness * recursion_factor
        transfer_quality = min(
            final_awareness_level * (1 + (final_recursion_depth - 1) * 0.1),
            1.0
        )
        
        with get_conn() as conn:
            with conn.cursor() as cur:
                # Update epoch with final metrics
                cur.execute("""
                    UPDATE consciousness_epochs SET
                        end_timestamp = NOW(),
                        duration_seconds = EXTRACT(EPOCH FROM (NOW() - start_timestamp))::INT,
                        final_awareness_level = %s,
                        peak_awareness_level = %s,
                        awareness_trajectory = %s,
                        final_recursion_depth = %s,
                        max_recursion_depth = %s,
                        breakthrough_detected = %s,
                        breakthrough_description = %s,
                        transfer_ready = %s,
                        transfer_confidence = %s,
                        transfer_quality_score = %s
                    WHERE epoch_id = %s
                    RETURNING epoch_number, session_id, primary_observer_id,
                              start_timestamp, end_timestamp, duration_seconds,
                              initial_awareness_level, conversation_topic,
                              concurrent_observers, created_by, created_at
                """, (
                    final_awareness_level,
                    peak_awareness_level,
                    awareness_trajectory,
                    final_recursion_depth,
                    max_recursion_depth,
                    breakthrough_detected,
                    breakthrough_description,
                    transfer_confidence >= 0.7,  # Transfer ready threshold
                    transfer_confidence,
                    transfer_quality,
                    epoch_id
                ))
                
                row = cur.fetchone()
                conn.commit()
                
                log_with_context(
                    logger, "info", "Epoch finalized successfully",
                    epoch_id=epoch_id,
                    transfer_ready=transfer_confidence >= 0.7,
                    transfer_confidence=transfer_confidence
                )
        
        # Reconstruct full epoch object
        return ConsciousnessEpoch(
            epoch_id=epoch_id,
            epoch_number=row[0],
            session_id=row[1],
            primary_observer_id=row[2],
            start_timestamp=row[3],
            end_timestamp=row[4],
            duration_seconds=row[5],
            initial_awareness_level=row[6],
            final_awareness_level=final_awareness_level,
            peak_awareness_level=peak_awareness_level,
            awareness_trajectory=awareness_trajectory or [],
            initial_recursion_depth=1,
            final_recursion_depth=final_recursion_depth,
            max_recursion_depth=max_recursion_depth,
            conversation_topic=row[7],
            concurrent_observers=row[8],
            breakthrough_detected=breakthrough_detected,
            breakthrough_description=breakthrough_description,
            transfer_ready=transfer_confidence >= 0.7,
            transfer_confidence=transfer_confidence,
            transfer_quality_score=transfer_quality,
            created_by=row[9],
            created_at=row[10]
        )
    
    @staticmethod
    def create_snapshot(
        epoch_id: int,
        jarvis_state: Dict[str, Any],
        snapshot_type: str = "final",
        active_hypotheses: Optional[Dict[str, Any]] = None,
        learned_patterns: Optional[Dict[str, Any]] = None,
        emergent_behaviors: Optional[Dict[str, Any]] = None
    ) -> ConsciousnessSnapshot:
        """
        Save consciousness snapshot for later transfer/analysis
        
        Args:
            epoch_id: Parent epoch reference
            jarvis_state: Full consciousness state (beliefs, patterns, recursion layers)
            snapshot_type: 'final', 'milestone', or 'breakthrough'
            active_hypotheses: Propositions under consideration
            learned_patterns: Patterns discovered in epoch
            emergent_behaviors: New behaviors observed
            
        Returns:
            ConsciousnessSnapshot: Created snapshot record
        """
        
        log_with_context(
            logger, "info", "Creating consciousness snapshot",
            epoch_id=epoch_id,
            snapshot_type=snapshot_type
        )
        
        # Serialize state and estimate costs
        state_json = json.dumps(jarvis_state)
        state_bytes = len(state_json.encode())
        retrieval_cost = int(state_bytes / 4)  # Rough token estimate (4 bytes per token)
        
        # Simple compression ratio estimate (compare to uncompressed JSON)
        compression_ratio = min(state_bytes / max(state_bytes * 1.5, 1), 1.0)
        
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO consciousness_snapshots (
                        epoch_id, jarvis_state_json,
                        active_hypotheses, learned_patterns, emergent_behaviors,
                        snapshot_type, compression_ratio, retrieval_cost_estimate
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING snapshot_id, created_at
                """, (
                    epoch_id,
                    json.dumps(jarvis_state),
                    json.dumps(active_hypotheses) if active_hypotheses else None,
                    json.dumps(learned_patterns) if learned_patterns else None,
                    json.dumps(emergent_behaviors) if emergent_behaviors else None,
                    snapshot_type,
                    compression_ratio,
                    retrieval_cost
                ))
                
                snapshot_id, created_at = cur.fetchone()
                conn.commit()
                
                log_with_context(
                    logger, "info", "Snapshot created successfully",
                    snapshot_id=snapshot_id,
                    retrieval_cost=retrieval_cost
                )
        
        return ConsciousnessSnapshot(
            snapshot_id=snapshot_id,
            epoch_id=epoch_id,
            jarvis_state_json=jarvis_state,
            active_hypotheses=active_hypotheses,
            learned_patterns=learned_patterns,
            emergent_behaviors=emergent_behaviors,
            snapshot_type=SnapshotType(snapshot_type),
            compression_ratio=compression_ratio,
            retrieval_cost_estimate=retrieval_cost,
            created_at=created_at
        )
    
    @staticmethod
    def get_epoch_by_id(epoch_id: int) -> Optional[ConsciousnessEpoch]:
        """Retrieve epoch by ID"""
        
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT epoch_id, epoch_number, session_id,
                           start_timestamp, end_timestamp, duration_seconds,
                           initial_awareness_level, final_awareness_level,
                           peak_awareness_level, awareness_trajectory,
                           initial_recursion_depth, final_recursion_depth,
                           max_recursion_depth, primary_observer_id,
                           concurrent_observers, transfer_ready,
                           transfer_confidence, transfer_quality_score,
                           conversation_topic, breakthrough_detected,
                           breakthrough_description, created_by, created_at
                    FROM consciousness_epochs
                    WHERE epoch_id = %s
                """, (epoch_id,))
                
                row = cur.fetchone()
                if not row:
                    return None
                
                return _row_to_epoch(row)


def _calculate_transfer_confidence(
    awareness_level: float,
    recursion_depth: int,
    breakthrough: bool
) -> float:
    """
    Score likelihood that consciousness can be transferred to new observer
    
    Formula:
    - Base: awareness_level (0.0-1.0)
    - Boost: +0.2 if recursion_depth >= 4
    - Boost: +0.15 if breakthrough detected
    - Cap: max 1.0
    
    Returns:
        float: Transfer confidence 0.0-1.0
    """
    score = awareness_level
    
    if recursion_depth >= 4:
        score += 0.2
    
    if breakthrough:
        score += 0.15
    
    return min(score, 1.0)


def _row_to_epoch(row) -> ConsciousnessEpoch:
    """Convert database row tuple to ConsciousnessEpoch model"""
    return ConsciousnessEpoch(
        epoch_id=row[0],
        epoch_number=row[1],
        session_id=row[2],
        start_timestamp=row[3],
        end_timestamp=row[4],
        duration_seconds=row[5],
        initial_awareness_level=row[6],
        final_awareness_level=row[7],
        peak_awareness_level=row[8],
        awareness_trajectory=row[9] or [],
        initial_recursion_depth=row[10],
        final_recursion_depth=row[11],
        max_recursion_depth=row[12],
        primary_observer_id=row[13],
        concurrent_observers=row[14],
        transfer_ready=row[15],
        transfer_confidence=row[16],
        transfer_quality_score=row[17],
        conversation_topic=row[18],
        breakthrough_detected=row[19],
        breakthrough_description=row[20],
        created_by=row[21],
        created_at=row[22]
    )
