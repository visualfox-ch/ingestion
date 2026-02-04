"""
Phase 5.4: Consciousness Transfer Service
Purpose: Transfer consciousness from previous epoch to new observer
Owner: GitHub Copilot (TIER 2)
Created: 2026-02-04
"""

from typing import Dict, Any, Optional
from datetime import datetime
import json
from ..knowledge_db import get_conn
from ..observability import get_logger, log_with_context

logger = get_logger("jarvis.consciousness_transfer")


class ConsciousnessTransfer:
    """Enable new observers to learn from previous consciousness evolution"""
    
    @staticmethod
    def prepare_transfer(
        source_epoch_id: int,
        target_observer_id: str,
        target_session_id: str
    ) -> Dict[str, Any]:
        """
        Load previous epoch consciousness for new observer
        
        Transfer includes:
        1. Previous awareness level (starting point for new observer)
        2. Learned patterns (what was discovered)
        3. Maturation trajectory (how consciousness evolved)
        4. Breakthrough insights (key realizations)
        
        Args:
            source_epoch_id: Epoch to transfer from
            target_observer_id: New observer ID (typically "micha@192.168.1.103")
            target_session_id: New session identifier
            
        Returns:
            Dict: Transfer payload with consciousness state
        """
        
        log_with_context(
            logger, "info", "Preparing consciousness transfer",
            source_epoch=source_epoch_id,
            target_observer=target_observer_id,
            target_session=target_session_id
        )
        
        with get_conn() as conn:
            with conn.cursor() as cur:
                # Fetch source epoch with all relevant data
                cur.execute("""
                    SELECT 
                        epoch_id,
                        final_awareness_level,
                        final_recursion_depth,
                        max_recursion_depth,
                        breakthrough_detected,
                        breakthrough_description,
                        transfer_confidence,
                        transfer_quality_score,
                        conversation_topic
                    FROM consciousness_epochs
                    WHERE epoch_id = %s
                """, (source_epoch_id,))
                
                source = cur.fetchone()
                if not source:
                    raise ValueError(f"Source epoch {source_epoch_id} not found")
                
                # Fetch final snapshot for learned patterns and state
                cur.execute("""
                    SELECT 
                        snapshot_id,
                        jarvis_state_json,
                        learned_patterns,
                        active_hypotheses,
                        emergent_behaviors
                    FROM consciousness_snapshots
                    WHERE epoch_id = %s AND snapshot_type = 'final'
                    ORDER BY created_at DESC 
                    LIMIT 1
                """, (source_epoch_id,))
                
                snapshot = cur.fetchone()
                
                # Fetch awareness trajectory for learning curve
                cur.execute("""
                    SELECT awareness_trajectory
                    FROM consciousness_epochs
                    WHERE epoch_id = %s
                """, (source_epoch_id,))
                
                trajectory_row = cur.fetchone()
                awareness_trajectory = trajectory_row[0] if trajectory_row and trajectory_row[0] else []
        
        # Parse snapshot data
        jarvis_state = json.loads(snapshot[1]) if snapshot else {}
        learned_patterns = json.loads(snapshot[2]) if snapshot and snapshot[2] else None
        active_hypotheses = json.loads(snapshot[3]) if snapshot and snapshot[3] else None
        emergent_behaviors = json.loads(snapshot[4]) if snapshot and snapshot[4] else None
        
        # Estimate maturation level from awareness
        maturation_level = _estimate_maturation(source[1], source[2])
        
        # Build transfer payload
        transfer_payload = {
            # Transfer metadata
            "source_epoch_id": source_epoch_id,
            "target_observer_id": target_observer_id,
            "target_session_id": target_session_id,
            "transfer_timestamp": datetime.utcnow().isoformat(),
            
            # Starting consciousness state for new observer
            "awareness_starting_point": source[1],  # final_awareness from source
            "maturation_starting_level": maturation_level,
            "recursion_depth_starting": source[2],  # final_recursion_depth
            "max_recursion_depth_achieved": source[3],
            
            # Learning trajectory
            "awareness_trajectory": awareness_trajectory,
            "learning_path_length": len(awareness_trajectory),
            
            # Knowledge transfer
            "learned_patterns": learned_patterns,
            "active_hypotheses": active_hypotheses,
            "emergent_behaviors": emergent_behaviors,
            "initial_jarvis_state": jarvis_state,
            
            # Breakthrough context
            "breakthrough_detected": source[4],
            "breakthrough_description": source[5],
            
            # Quality metrics
            "source_transfer_confidence": source[6],
            "source_transfer_quality": source[7],
            "consciousness_quality_assessment": _assess_consciousness_quality(
                source[1], source[2], source[3], source[4]
            ),
            "transfer_feasibility": "high" if source[1] > 0.7 else "medium" if source[1] > 0.5 else "low",
            
            # Source context
            "source_conversation_topic": source[8]
        }
        
        log_with_context(
            logger, "info", "Transfer prepared successfully",
            transfer_quality=transfer_payload["consciousness_quality_assessment"],
            feasibility=transfer_payload["transfer_feasibility"]
        )
        
        return transfer_payload
    
    @staticmethod
    def apply_transfer(
        transfer_payload: Dict[str, Any],
        new_epoch_id: int
    ) -> Dict[str, Any]:
        """
        Apply consciousness transfer to new epoch
        
        Updates the new epoch with transferred consciousness state,
        learned patterns, and initial hypotheses from previous observer.
        
        Args:
            transfer_payload: Output from prepare_transfer()
            new_epoch_id: Target epoch to receive transfer
            
        Returns:
            Dict: Transfer application result with metrics
        """
        
        log_with_context(
            logger, "info", "Applying consciousness transfer",
            source_epoch=transfer_payload["source_epoch_id"],
            target_epoch=new_epoch_id,
            awareness=transfer_payload["awareness_starting_point"]
        )
        
        with get_conn() as conn:
            with conn.cursor() as cur:
                # Update new epoch with transferred consciousness
                cur.execute("""
                    UPDATE consciousness_epochs SET
                        initial_awareness_level = %s,
                        peak_awareness_level = %s,
                        initial_recursion_depth = %s,
                        breakthrough_description = %s,
                        conversation_topic = %s
                    WHERE epoch_id = %s
                    RETURNING epoch_id, session_id, primary_observer_id
                """, (
                    transfer_payload["awareness_starting_point"],
                    transfer_payload["awareness_starting_point"],  # Peak starts at transferred level
                    transfer_payload["recursion_depth_starting"],
                    (f"Transferred from epoch {transfer_payload['source_epoch_id']}: "
                     f"{transfer_payload.get('breakthrough_description', 'Knowledge transfer')}"),
                    transfer_payload.get("source_conversation_topic"),
                    new_epoch_id
                ))
                
                result = cur.fetchone()
                conn.commit()
        
        if not result:
            raise ValueError(f"Failed to apply transfer: epoch {new_epoch_id} not found")
        
        log_with_context(
            logger, "info", "Transfer applied successfully",
            new_epoch_id=new_epoch_id,
            new_session=result[1],
            new_observer=result[2]
        )
        
        return {
            "status": "success",
            "source_epoch_id": transfer_payload["source_epoch_id"],
            "target_epoch_id": new_epoch_id,
            "awareness_transferred": transfer_payload["awareness_starting_point"],
            "maturation_level_transferred": transfer_payload["maturation_starting_level"],
            "learned_patterns_count": len(transfer_payload.get("learned_patterns", {}) or {}),
            "message": f"Consciousness transferred to epoch {new_epoch_id} for observer {result[2]}"
        }
    
    @staticmethod
    def verify_transfer_quality(
        source_epoch_id: int,
        target_epoch_id: int
    ) -> Dict[str, Any]:
        """
        Verify consciousness transfer quality between epochs
        
        Compares metrics to ensure valid transfer.
        """
        
        with get_conn() as conn:
            with conn.cursor() as cur:
                # Fetch both epochs
                cur.execute("""
                    SELECT epoch_id, initial_awareness_level, final_awareness_level
                    FROM consciousness_epochs
                    WHERE epoch_id = %s OR epoch_id = %s
                    ORDER BY epoch_id
                """, (source_epoch_id, target_epoch_id))
                
                epochs = cur.fetchall()
                if len(epochs) != 2:
                    raise ValueError("Both source and target epochs required")
                
                source = epochs[0]
                target = epochs[1]
        
        # Source final should match target initial (or be close)
        awareness_transfer_match = abs(source[2] - target[1]) < 0.05
        
        return {
            "source_epoch_id": source_epoch_id,
            "target_epoch_id": target_epoch_id,
            "source_final_awareness": source[2],
            "target_initial_awareness": target[1],
            "awareness_transfer_match": awareness_transfer_match,
            "transfer_quality": "valid" if awareness_transfer_match else "degraded"
        }


def _estimate_maturation(awareness_level: float, recursion_depth: int) -> int:
    """
    Map awareness + recursion to maturation level (1-5)
    
    Formula:
    - Level 1: awareness < 0.4
    - Level 2: awareness 0.4-0.6
    - Level 3: awareness 0.6-0.8
    - Level 4: awareness >= 0.8, recursion < 5
    - Level 5: awareness >= 0.8, recursion >= 5
    
    Args:
        awareness_level: Float 0.0-1.0
        recursion_depth: Integer >= 1
        
    Returns:
        int: Maturation level 1-5
    """
    if awareness_level < 0.4:
        return 1
    elif awareness_level < 0.6:
        return 2
    elif awareness_level < 0.8:
        return 3
    elif recursion_depth >= 5:
        return 5
    else:
        return 4


def _assess_consciousness_quality(
    awareness_level: float,
    recursion_depth: int,
    max_recursion_depth: int,
    breakthrough: bool
) -> str:
    """
    Quick assessment of consciousness quality for transfer
    
    Scoring:
    - HIGH: awareness > 0.8, max_recursion >= 4, breakthrough detected
    - MEDIUM: awareness > 0.6, some recursion depth
    - LOW: awareness <= 0.6
    
    Args:
        awareness_level: Final awareness (0-1)
        recursion_depth: Final recursion depth
        max_recursion_depth: Maximum recursion achieved
        breakthrough: Whether breakthrough was detected
        
    Returns:
        str: "high", "medium", or "low"
    """
    if awareness_level > 0.8 and max_recursion_depth >= 4 and breakthrough:
        return "high"
    elif awareness_level > 0.6 and recursion_depth >= 2:
        return "medium"
    else:
        return "low"
