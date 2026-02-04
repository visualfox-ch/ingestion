"""
Jarvis Learning Manager (Feedback Loop)

Purpose:
  Close the loop: deployment result → update confidence scorer → improve future proposals
  
Flow:
  1. Deployment completes (success or failure)
  2. Impact measured (metrics delta)
  3. Evaluate outcome (was it worth it?)
  4. Update ConfidenceScorer feedback history
  5. Check phase readiness (ready for Phase 1?)
  6. Log learning event (audit trail)

Learning Cycle:
  Deploy Write → Measure Impact → Update Confidence → Better Proposals
  
Phase Progression (Automatic):
  Phase 0 (manual): Collect 10-15 success/failure examples
  Phase 1 (conditional): Ready when avg confidence trend ↑ (0.68 → 0.72+)
  Phase 2 (autonomous): Ready when success rate >85%

References:
  - JarvisConfidenceScorer.update_feedback()
  - JARVIS_IMPLEMENTATION_ROADMAP_FEB4.md (Learning loop)
  - AUTONOMOUS_WRITE_SAFETY_BASELINE.md (Feedback requirements)
"""

from typing import Dict, Optional, Any
from datetime import datetime
import logging
import json

logger = logging.getLogger("jarvis.learning_manager")


class JarvisLearningManager:
    """
    Manage feedback loop: deployments → confidence improvement → phase progression.
    
    Automatically:
    - Updates ConfidenceScorer with deployment outcomes
    - Tracks learning trends (is Jarvis getting better?)
    - Signals phase readiness (ready for Phase 1 auto-approval?)
    - Maintains immutable learning log
    """
    
    def __init__(
        self,
        confidence_scorer=None,
        audit_log=None,
        logger=None,
        phase_0_target_writes: int = 15,
        phase1_confidence_threshold: float = 0.72
    ):
        """
        Args:
            confidence_scorer: JarvisConfidenceScorer instance
            audit_log: Immutable audit log backend
            logger: Logger instance
            phase_0_target_writes: Target number of writes for Phase 0 (default 15)
            phase1_confidence_threshold: Avg confidence needed for Phase 1 (default 0.72)
        """
        self.confidence_scorer = confidence_scorer
        self.audit_log = audit_log
        self.logger = logger or logging.getLogger(__name__)
        self.phase_0_target_writes = phase_0_target_writes
        self.phase1_confidence_threshold = phase1_confidence_threshold
    
    async def process_deployment_result(
        self,
        change,
        impact: Optional[Dict[str, float]],
        approval
    ) -> Dict[str, Any]:
        """
        Process deployment result and update confidence.
        
        Args:
            change: CodeChange object
            impact: Impact metrics from MetricsBridge
                {
                    "embedding_quality_delta": 0.05,
                    "search_latency_delta": -12.3,
                    "tokens_delta": -0.08,
                    "success": True
                }
            approval: Approval object (contains original confidence score)
        
        Returns:
            {
                "success": True,
                "original_confidence": 0.82,
                "new_confidence": 0.85,
                "confidence_delta": 0.03,
                "was_deployment_successful": True,
                "phase_readiness": {
                    "current_phase": 0,
                    "ready_for_phase_1": False,
                    "reason": "Only 2/15 writes completed"
                }
            }
        """
        
        try:
            # Step 1: Evaluate outcome
            was_success = self._evaluate_deployment_success(impact)
            
            self.logger.info(
                "Deployment outcome evaluated",
                extra={
                    "change_id": change.id,
                    "was_success": was_success,
                    "impact": impact
                }
            )
            
            # Step 2: Update confidence scorer
            if self.confidence_scorer:
                original_confidence = approval.change.confidence_score if hasattr(approval.change, 'confidence_score') else None
                
                self.confidence_scorer.update_feedback(
                    change_type=change.change_type,
                    success=was_success,
                    details={
                        "relevance_delta": impact.get("embedding_quality_delta", 0) if impact else 0,
                        "latency_delta": impact.get("search_latency_delta", 0) if impact else 0,
                        "tokens_delta": impact.get("tokens_delta", 0) if impact else 0,
                        "impact_quality": impact.get("success", False) if impact else False
                    }
                )
                
                # Get updated confidence history
                feedback_history = self.confidence_scorer.feedback_history
            else:
                original_confidence = None
                feedback_history = {}
            
            # Step 3: Check phase readiness
            phase_readiness = await self._check_phase_readiness(feedback_history)
            
            # Step 4: Log learning event
            learning_log = {
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "change_id": change.id,
                "approval_id": approval.request_id,
                "change_type": change.change_type,
                "was_deployment_successful": was_success,
                "impact": impact,
                "original_confidence": original_confidence,
                "feedback_history": feedback_history,
                "phase_readiness": phase_readiness
            }
            
            if self.audit_log:
                await self.audit_log.record_learning(learning_log)
            
            self.logger.info(
                "Learning event recorded",
                extra={
                    "change_id": change.id,
                    "was_success": was_success,
                    "phase_readiness": phase_readiness
                }
            )
            
            return learning_log
        
        except Exception as e:
            self.logger.error(
                f"Error processing deployment result: {e}",
                extra={"change_id": change.id, "error": str(e)}
            )
            
            return {
                "success": False,
                "error": str(e)
            }
    
    def _evaluate_deployment_success(self, impact: Optional[Dict[str, float]]) -> bool:
        """
        Determine if deployment was successful.
        
        Success criteria:
          - No negative impact on relevance (embedding_quality_delta >= -0.01)
          - No major latency regression (search_latency_delta <= 50ms)
          - Overall positive or neutral impact
        
        Args:
            impact: Impact dict from MetricsBridge
        
        Returns:
            True if deployment met success criteria
        """
        
        if not impact or not impact.get("success"):
            return False
        
        # Check relevance didn't drop more than 1%
        rel_pct = impact.get("embedding_quality_pct", 0)
        if rel_pct < -1:
            self.logger.warning(f"Relevance dropped {rel_pct}%")
            return False
        
        # Check latency didn't degrade significantly
        lat_delta = impact.get("search_latency_delta", 0)
        if lat_delta > 50:  # More than 50ms slower
            self.logger.warning(f"Latency degraded {lat_delta}ms")
            return False
        
        # Overall: positive if at least one metric improved
        rel_improved = rel_pct > 0
        lat_improved = lat_delta < -5  # 5ms or more faster
        tokens_improved = impact.get("tokens_pct", 0) < -2  # 2% or more efficient
        
        success = rel_improved or lat_improved or tokens_improved
        
        self.logger.info(
            "Deployment success criteria evaluated",
            extra={
                "relevance_improved": rel_improved,
                "latency_improved": lat_improved,
                "tokens_improved": tokens_improved,
                "overall_success": success
            }
        )
        
        return success
    
    async def _check_phase_readiness(self, feedback_history: Dict) -> Dict[str, Any]:
        """
        Check if ready to progress to next phase.
        
        Phase 0 → Phase 1: Needs:
          - 15+ total writes attempted
          - 85%+ success rate
          - Confidence trend upward
        
        Args:
            feedback_history: Updated feedback from ConfidenceScorer
        
        Returns:
            {
                "current_phase": 0,
                "ready_for_phase_1": False,
                "reason": "Only 2/15 writes completed",
                "progress": {
                    "writes_completed": 2,
                    "writes_target": 15,
                    "success_rate": 1.0,
                    "avg_confidence": 0.68,
                    "confidence_trend": "stable"
                }
            }
        """
        
        # Calculate aggregates from feedback history
        total_writes = 0
        total_successes = 0
        confidence_scores = []
        
        for change_type, record in feedback_history.items():
            total_writes += record.get("n_samples", 0)
            total_successes += record.get("successes", 0)
            
            # Approximate confidence based on success rate
            success_rate = record.get("success_rate", 0.5)
            confidence_scores.append(success_rate)
        
        success_rate = total_successes / max(1, total_writes)
        avg_confidence = sum(confidence_scores) / max(1, len(confidence_scores))
        
        # Trend: compare to phase0_target / 2 as "halfway"
        confidence_trend = "improving" if avg_confidence > 0.70 else "stable"
        
        # Check readiness
        writes_done = total_writes >= self.phase_0_target_writes
        success_ok = success_rate >= 0.85
        confidence_ok = avg_confidence >= self.phase1_confidence_threshold
        
        ready_for_phase_1 = writes_done and success_ok and confidence_ok
        
        if not ready_for_phase_1:
            if not writes_done:
                reason = f"Only {total_writes}/{self.phase_0_target_writes} writes completed"
            elif not success_ok:
                reason = f"Success rate {success_rate*100:.1f}% < 85% needed"
            else:
                reason = f"Confidence {avg_confidence:.2f} < {self.phase1_confidence_threshold} needed"
        else:
            reason = "All criteria met for Phase 1 progression"
        
        readiness = {
            "current_phase": 0,
            "ready_for_phase_1": ready_for_phase_1,
            "reason": reason,
            "progress": {
                "writes_completed": total_writes,
                "writes_target": self.phase_0_target_writes,
                "success_rate": round(success_rate, 3),
                "avg_confidence": round(avg_confidence, 3),
                "confidence_trend": confidence_trend,
                "milestones": {
                    "writes_target_met": writes_done,
                    "success_rate_met": success_ok,
                    "confidence_threshold_met": confidence_ok
                }
            }
        }
        
        self.logger.info(
            "Phase readiness check complete",
            extra=readiness
        )
        
        return readiness
    
    async def get_learning_summary(self, feedback_history: Dict) -> Dict[str, Any]:
        """
        Get comprehensive learning summary for user report.
        
        Returns:
            {
                "period": "2026-02-04 to 2026-02-09",
                "writes_total": 12,
                "writes_successful": 10,
                "success_rate": 0.833,
                "improvements": {
                    "embedding_model_switch": {"success_rate": 0.90, "n": 10},
                    "token_optimization": {"success_rate": 0.75, "n": 4}
                },
                "insights": "Embedding changes are most reliable..."
            }
        """
        
        summary = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "total_writes": 0,
            "total_successes": 0,
            "success_rate": 0,
            "by_type": {},
            "top_patterns": []
        }
        
        # Aggregate by type
        for change_type, record in feedback_history.items():
            n_samples = record.get("n_samples", 0)
            successes = record.get("successes", 0)
            success_rate = record.get("success_rate", 0)
            
            summary["total_writes"] += n_samples
            summary["total_successes"] += successes
            
            summary["by_type"][change_type] = {
                "samples": n_samples,
                "success_rate": round(success_rate, 3),
                "trend": "reliable" if success_rate > 0.85 else "variable"
            }
        
        # Calculate overall success rate
        if summary["total_writes"] > 0:
            summary["success_rate"] = round(
                summary["total_successes"] / summary["total_writes"],
                3
            )
        
        # Find top patterns (highest success rate)
        summary["top_patterns"] = sorted(
            [
                (change_type, record["success_rate"])
                for change_type, record in feedback_history.items()
            ],
            key=lambda x: x[1],
            reverse=True
        )[:3]
        
        return summary
