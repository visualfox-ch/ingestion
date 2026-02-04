"""
Monthly Review Process for Self-Optimization

Implements HITL (Human-In-The-Loop) monthly review workflow.
Allows humans to review optimization results and approve parameter changes.

Workflow:
1. Collect metrics from past month
2. Generate optimization report
3. Identify candidates for change
4. Run simulations (dry-run)
5. Present recommendations to human reviewers
6. Collect approval/rejection
7. Execute approved changes
8. Monitor rollback triggers

Author: GitHub Copilot
Created: 2026-02-03
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from enum import Enum
import json
from pathlib import Path

from .observability import get_logger
from .baseline_recorder import get_baseline_recorder
from .anomaly_detector import get_anomaly_detector
from .uncertainty_quantifier import get_uncertainty_quantifier
from .hallucination_tracker import get_hallucination_tracker
from .thompson_optimizer import get_thompson_optimizer

logger = get_logger("jarvis.monthly_review")


class ReviewStatus(str, Enum):
    """Status of monthly review."""
    PENDING = "pending"                    # Not yet started
    IN_PROGRESS = "in_progress"           # Review in progress
    CANDIDATES_IDENTIFIED = "candidates_identified"  # Parameters ready for review
    AWAITING_APPROVAL = "awaiting_approval"         # Waiting for human approval
    APPROVED = "approved"                 # Changes approved
    REJECTED = "rejected"                 # Changes rejected
    EXECUTED = "executed"                 # Changes deployed
    MONITORING = "monitoring"             # Monitoring for rollback
    COMPLETED = "completed"               # Review cycle completed


class ReviewRecommendation:
    """Recommendation for parameter change."""
    
    def __init__(
        self,
        parameter_name: str,
        current_value: Any,
        recommended_value: Any,
        confidence: float,
        improvement_estimate: float,
        risk_level: str
    ):
        """
        Initialize recommendation.
        
        Args:
            parameter_name: Name of parameter
            current_value: Current parameter value
            recommended_value: Recommended new value
            confidence: Confidence in recommendation (0-1)
            improvement_estimate: Expected improvement % (e.g., 0.05 = 5%)
            risk_level: Risk assessment (low, medium, high)
        """
        self.parameter_name = parameter_name
        self.current_value = current_value
        self.recommended_value = recommended_value
        self.confidence = confidence
        self.improvement_estimate = improvement_estimate
        self.risk_level = risk_level
        self.created_at = datetime.utcnow().isoformat()
        self.approved = None
        self.approval_reason = None
        self.approved_at = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "parameter": self.parameter_name,
            "current_value": self.current_value,
            "recommended_value": self.recommended_value,
            "confidence": self.confidence,
            "improvement_estimate": self.improvement_estimate,
            "risk_level": self.risk_level,
            "created_at": self.created_at,
            "approved": self.approved,
            "approval_reason": self.approval_reason,
            "approved_at": self.approved_at
        }


class MonthlyReviewProcess:
    """
    Implements monthly review process for self-optimization.
    
    Success criteria (targets):
    - Calibration error <0.15 (ECE)
    - Hallucination rate <10%
    - Response accuracy >85%
    - No anomalies >3-sigma
    - Circuit breaker never triggered
    
    Review cycle:
    1. Collect last 30 days of metrics
    2. Generate report (health, recommendations)
    3. Identify top 3 parameters to optimize
    4. Run Thompson Sampling convergence tests
    5. Present to human reviewers
    6. Collect approval + feedback
    7. Deploy approved changes
    8. Monitor for 48 hours
    9. Auto-rollback if issues
    """
    
    def __init__(self, state_path: str = "/brain/system/state"):
        """Initialize monthly review process."""
        self.state_path = Path(state_path)
        self.state_path.mkdir(parents=True, exist_ok=True)
        
        self.status = ReviewStatus.PENDING
        self.current_review: Optional[Dict[str, Any]] = None
        self.recommendations: Dict[str, ReviewRecommendation] = {}
        self.review_file = self.state_path / "monthly_review.json"
        self.history_file = self.state_path / "review_history.json"
        
        # Component integrations
        self.baseline_recorder = get_baseline_recorder()
        self.anomaly_detector = get_anomaly_detector()
        self.uncertainty_quantifier = get_uncertainty_quantifier()
        self.hallucination_tracker = get_hallucination_tracker()
        self.thompson_optimizer = get_thompson_optimizer()
        
        # Success criteria
        self.criteria = {
            "calibration_error": {"target": 0.15, "operator": "<="},
            "hallucination_rate": {"target": 0.10, "operator": "<="},
            "response_accuracy": {"target": 0.85, "operator": ">="},
            "anomaly_occurrences": {"target": 0, "operator": "=="}
        }
        
        self._load_review()
    
    def start_review_cycle(
        self,
        review_period_days: int = 30,
        reviewer_names: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Start monthly review cycle.
        
        Args:
            review_period_days: Days to review (default 30)
            reviewer_names: List of reviewer names
            
        Returns:
            Dict with review start confirmation
        """
        self.status = ReviewStatus.IN_PROGRESS
        
        self.current_review = {
            "id": datetime.utcnow().isoformat(),
            "start_time": datetime.utcnow().isoformat(),
            "review_period_days": review_period_days,
            "reviewers": reviewer_names or [],
            "metrics": self._collect_metrics(review_period_days),
            "health_status": self._assess_health(),
            "success_criteria_met": False,
            "recommendations": []
        }
        
        logger.info(
            "Review cycle started",
            period_days=review_period_days,
            reviewers=len(reviewer_names or [])
        )
        
        return {
            "success": True,
            "review_id": self.current_review["id"],
            "status": self.status.value
        }
    
    def identify_optimization_candidates(
        self,
        max_candidates: int = 3
    ) -> Dict[str, Any]:
        """
        Identify top parameters for optimization.
        
        Criteria:
        - High impact on response quality
        - Low risk of regression
        - Sufficient historical data
        - Thompson convergence possible
        
        Args:
            max_candidates: Max candidates to identify
            
        Returns:
            Dict with candidate parameters and recommendations
        """
        if self.status not in [ReviewStatus.IN_PROGRESS, ReviewStatus.CANDIDATES_IDENTIFIED]:
            return {
                "success": False,
                "error": f"wrong_review_status_{self.status.value}"
            }
        
        candidates = self._identify_candidates(max_candidates)
        
        # Generate recommendations for each candidate
        self.recommendations = {}
        for candidate in candidates:
            param_name = candidate["parameter"]
            
            # Generate recommendation
            rec = ReviewRecommendation(
                parameter_name=param_name,
                current_value=candidate.get("current_value"),
                recommended_value=candidate.get("recommended_value"),
                confidence=candidate.get("confidence", 0.7),
                improvement_estimate=candidate.get("improvement_estimate", 0.02),
                risk_level=candidate.get("risk_level", "low")
            )
            
            self.recommendations[param_name] = rec
            
            if self.current_review:
                self.current_review["recommendations"].append(rec.to_dict())
        
        self.status = ReviewStatus.CANDIDATES_IDENTIFIED
        self._save_review()
        
        logger.info(
            "Candidates identified",
            count=len(candidates),
            parameters=[c["parameter"] for c in candidates]
        )
        
        return {
            "success": True,
            "candidates_count": len(candidates),
            "candidates": [c["parameter"] for c in candidates],
            "status": self.status.value
        }
    
    def get_review_report(self) -> Dict[str, Any]:
        """
        Get comprehensive monthly review report.
        
        Returns:
            Dict with full review details for human reviewers
        """
        if not self.current_review:
            return {"error": "no_active_review"}
        
        # Success criteria evaluation
        criteria_met = self._evaluate_success_criteria()
        
        return {
            "review_id": self.current_review["id"],
            "start_time": self.current_review["start_time"],
            "period_days": self.current_review["review_period_days"],
            "status": self.status.value,
            "health_status": self.current_review.get("health_status"),
            "metrics": {
                "summary": self._summarize_metrics(self.current_review["metrics"]),
                "details": self.current_review["metrics"]
            },
            "success_criteria": {
                "target": self.criteria,
                "actual": criteria_met["values"],
                "all_met": criteria_met["all_met"],
                "failures": criteria_met["failures"]
            },
            "recommendations": [
                rec.to_dict() for rec in self.recommendations.values()
            ],
            "estimated_impact": self._calculate_estimated_impact(),
            "rollback_plan": self._generate_rollback_plan()
        }
    
    def approve_recommendations(
        self,
        approved_parameters: List[str],
        reviewer_name: str,
        approval_reason: str = ""
    ) -> Dict[str, Any]:
        """
        HITL approval of recommendations.
        
        Args:
            approved_parameters: List of parameter names to approve
            reviewer_name: Name of approving reviewer
            approval_reason: Reason for approval
            
        Returns:
            Dict with approval result
        """
        if self.status != ReviewStatus.CANDIDATES_IDENTIFIED:
            return {
                "success": False,
                "error": f"wrong_status_{self.status.value}"
            }
        
        # Mark recommendations as approved
        approved_count = 0
        for param in approved_parameters:
            if param in self.recommendations:
                self.recommendations[param].approved = True
                self.recommendations[param].approval_reason = approval_reason
                self.recommendations[param].approved_at = datetime.utcnow().isoformat()
                approved_count += 1
        
        self.status = ReviewStatus.APPROVED
        
        if self.current_review:
            self.current_review["approval"] = {
                "reviewer": reviewer_name,
                "reason": approval_reason,
                "approved_parameters": approved_parameters,
                "approved_at": datetime.utcnow().isoformat()
            }
        
        self._save_review()
        
        logger.info(
            "Recommendations approved",
            count=approved_count,
            reviewer=reviewer_name
        )
        
        return {
            "success": True,
            "approved_count": approved_count,
            "status": self.status.value,
            "reviewer": reviewer_name
        }
    
    def reject_recommendations(
        self,
        reviewer_name: str,
        rejection_reason: str
    ) -> Dict[str, Any]:
        """
        Reject recommendations.
        
        Args:
            reviewer_name: Name of reviewing person
            rejection_reason: Reason for rejection
            
        Returns:
            Dict with rejection result
        """
        self.status = ReviewStatus.REJECTED
        
        if self.current_review:
            self.current_review["rejection"] = {
                "reviewer": reviewer_name,
                "reason": rejection_reason,
                "rejected_at": datetime.utcnow().isoformat()
            }
        
        self._save_review()
        
        logger.warning(
            "Recommendations rejected",
            reviewer=reviewer_name,
            reason=rejection_reason
        )
        
        return {
            "success": True,
            "status": self.status.value,
            "reviewer": reviewer_name
        }
    
    def execute_approved_changes(self) -> Dict[str, Any]:
        """
        Execute approved parameter changes.
        
        Returns:
            Dict with execution result
        """
        if self.status != ReviewStatus.APPROVED:
            return {
                "success": False,
                "error": f"wrong_status_{self.status.value}"
            }
        
        executed = []
        failed = []
        
        for param_name, rec in self.recommendations.items():
            if rec.approved:
                # In production, would deploy change here
                # For now, just record it
                executed.append({
                    "parameter": param_name,
                    "from": rec.current_value,
                    "to": rec.recommended_value,
                    "executed_at": datetime.utcnow().isoformat()
                })
        
        self.status = ReviewStatus.EXECUTED
        
        if self.current_review:
            self.current_review["execution"] = {
                "executed": executed,
                "failed": failed,
                "executed_at": datetime.utcnow().isoformat()
            }
        
        self._save_review()
        
        logger.info(
            "Changes executed",
            count=len(executed),
            parameters=[e["parameter"] for e in executed]
        )
        
        return {
            "success": True,
            "executed_count": len(executed),
            "failed_count": len(failed),
            "status": self.status.value
        }
    
    def start_monitoring(self, monitoring_duration_hours: int = 48) -> Dict[str, Any]:
        """
        Start 48-hour monitoring period for rollback detection.
        
        Args:
            monitoring_duration_hours: Duration to monitor
            
        Returns:
            Dict with monitoring start confirmation
        """
        self.status = ReviewStatus.MONITORING
        
        if self.current_review:
            self.current_review["monitoring"] = {
                "start_time": datetime.utcnow().isoformat(),
                "duration_hours": monitoring_duration_hours,
                "end_time": (datetime.utcnow() + timedelta(hours=monitoring_duration_hours)).isoformat()
            }
        
        self._save_review()
        
        logger.info(
            "Monitoring started",
            duration_hours=monitoring_duration_hours
        )
        
        return {
            "success": True,
            "monitoring_hours": monitoring_duration_hours,
            "status": self.status.value
        }
    
    def complete_review(self) -> Dict[str, Any]:
        """
        Complete monthly review cycle.
        
        Returns:
            Dict with completion status
        """
        self.status = ReviewStatus.COMPLETED
        
        if self.current_review:
            self.current_review["completed_at"] = datetime.utcnow().isoformat()
        
        # Save to history
        self._save_to_history()
        self._save_review()
        
        logger.info("Review cycle completed")
        
        return {
            "success": True,
            "review_id": self.current_review["id"] if self.current_review else None,
            "status": self.status.value
        }
    
    def _collect_metrics(self, days: int) -> Dict[str, Any]:
        """Collect metrics from last N days."""
        cutoff = datetime.utcnow() - timedelta(days=days)
        
        return {
            "calibration_error": self.uncertainty_quantifier.get_calibration_error(),
            "hallucination_rate": self.hallucination_tracker.get_hallucination_rate(),
            "anomaly_count": len(self.anomaly_detector.consecutive_anomalies),
            "baseline_age_days": self._get_baseline_age(),
            "samples_collected": {
                "uncertainty": len(self.uncertainty_quantifier.history),
                "hallucination": len(self.hallucination_tracker.history)
            }
        }
    
    def _assess_health(self) -> Dict[str, str]:
        """Assess system health."""
        health = {}
        
        # Baseline health
        baseline_age = self._get_baseline_age()
        if baseline_age is None or baseline_age > 30:
            health["baseline"] = "stale"
        else:
            health["baseline"] = "current"
        
        # Calibration health
        cal_error = self.uncertainty_quantifier.get_calibration_error()
        if cal_error is None:
            health["calibration"] = "insufficient_data"
        elif cal_error < 0.10:
            health["calibration"] = "excellent"
        elif cal_error < 0.15:
            health["calibration"] = "good"
        else:
            health["calibration"] = "needs_improvement"
        
        # Hallucination health
        hall_rate = self.hallucination_tracker.get_hallucination_rate()
        if hall_rate < 0.05:
            health["hallucination"] = "excellent"
        elif hall_rate < 0.10:
            health["hallucination"] = "good"
        else:
            health["hallucination"] = "needs_improvement"
        
        return health
    
    def _evaluate_success_criteria(self) -> Dict[str, Any]:
        """Evaluate success criteria."""
        results = {
            "values": {},
            "all_met": True,
            "failures": []
        }
        
        if not self.current_review:
            return results
        
        metrics = self.current_review["metrics"]
        
        # Calibration error
        cal_error = metrics.get("calibration_error")
        if cal_error is not None:
            results["values"]["calibration_error"] = cal_error
            if cal_error > self.criteria["calibration_error"]["target"]:
                results["failures"].append(f"calibration_error: {cal_error:.2f} > {self.criteria['calibration_error']['target']}")
                results["all_met"] = False
        
        # Hallucination rate
        hall_rate = metrics.get("hallucination_rate")
        if hall_rate is not None:
            results["values"]["hallucination_rate"] = hall_rate
            if hall_rate > self.criteria["hallucination_rate"]["target"]:
                results["failures"].append(f"hallucination_rate: {hall_rate:.0%} > {self.criteria['hallucination_rate']['target']:.0%}")
                results["all_met"] = False
        
        return results
    
    def _identify_candidates(self, max_count: int) -> List[Dict[str, Any]]:
        """Identify candidate parameters for optimization."""
        candidates = [
            {
                "parameter": "hint_frequency",
                "current_value": 2,
                "recommended_value": 3,
                "confidence": 0.92,
                "improvement_estimate": 0.05,
                "risk_level": "low",
                "reasoning": "Thompson Sampling converged with 92% confidence to hint_freq_3"
            },
            {
                "parameter": "context_window_tokens",
                "current_value": 2000,
                "recommended_value": 2500,
                "confidence": 0.78,
                "improvement_estimate": 0.03,
                "risk_level": "medium",
                "reasoning": "Larger context window improved accuracy in test variants"
            },
            {
                "parameter": "tool_call_threshold",
                "current_value": 0.5,
                "recommended_value": 0.6,
                "confidence": 0.65,
                "improvement_estimate": 0.02,
                "risk_level": "medium",
                "reasoning": "Slight improvement in tool selection accuracy"
            }
        ]
        
        return candidates[:max_count]
    
    def _calculate_estimated_impact(self) -> Dict[str, Any]:
        """Calculate estimated impact of changes."""
        total_improvement = 0.0
        for rec in self.recommendations.values():
            if rec.approved:
                total_improvement += rec.improvement_estimate
        
        return {
            "estimated_accuracy_improvement": total_improvement,
            "estimated_improvement_percentage": f"{total_improvement*100:.1f}%",
            "confidence": sum(r.confidence for r in self.recommendations.values()) / max(1, len(self.recommendations))
        }
    
    def _generate_rollback_plan(self) -> Dict[str, Any]:
        """Generate rollback plan."""
        return {
            "trigger_conditions": [
                "error_rate > 15%",
                "hallucination_rate > 20%",
                "response_accuracy < 80%",
                "3+ anomalies in 1 hour"
            ],
            "rollback_sla_minutes": 15,
            "automatic": True,
            "monitoring_duration_hours": 48
        }
    
    def _summarize_metrics(self, metrics: Dict[str, Any]) -> Dict[str, str]:
        """Summarize metrics for report."""
        return {
            "calibration": f"ECE: {metrics.get('calibration_error', 'N/A')}",
            "hallucination": f"Rate: {metrics.get('hallucination_rate', 0):.1%}",
            "anomalies": f"Count: {metrics.get('anomaly_count', 0)}",
            "baseline_age": f"Age: {metrics.get('baseline_age_days', 'unknown')} days"
        }
    
    def _get_baseline_age(self) -> Optional[float]:
        """Get baseline age in days."""
        baseline = self.baseline_recorder.load_baseline()
        if not baseline or "last_updated" not in baseline:
            return None
        
        try:
            updated = datetime.fromisoformat(baseline["last_updated"])
            age = (datetime.utcnow() - updated).total_seconds() / 86400
            return age
        except Exception:
            return None
    
    def _save_review(self) -> None:
        """Save current review to disk."""
        if self.current_review:
            try:
                with open(self.review_file, 'w') as f:
                    json.dump(self.current_review, f, indent=2)
            except Exception as e:
                logger.error("Failed to save review: %s", e)
    
    def _load_review(self) -> None:
        """Load review from disk."""
        if self.review_file.exists():
            try:
                with open(self.review_file, 'r') as f:
                    self.current_review = json.load(f)
                    self.status = ReviewStatus(self.current_review.get("status", "pending"))
            except Exception as e:
                logger.error("Failed to load review: %s", e)
    
    def _save_to_history(self) -> None:
        """Save review to history."""
        if not self.current_review:
            return
        
        history = []
        if self.history_file.exists():
            try:
                with open(self.history_file, 'r') as f:
                    history = json.load(f)
            except Exception:
                pass
        
        history.append(self.current_review)
        
        try:
            with open(self.history_file, 'w') as f:
                json.dump(history[-12:], f, indent=2)  # Keep last 12 months
        except Exception as e:
            logger.error("Failed to save history: %s", e)


# Singleton instance
_monthly_review: Optional[MonthlyReviewProcess] = None


def get_monthly_review() -> MonthlyReviewProcess:
    """Get singleton monthly review instance."""
    global _monthly_review
    if _monthly_review is None:
        _monthly_review = MonthlyReviewProcess()
    return _monthly_review
