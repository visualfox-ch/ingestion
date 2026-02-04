"""
Jarvis Confidence Scorer (Phase 0 → Phase 3)

Purpose:
  Score Jarvis' confidence in its own code proposals (0.0 - 1.0).
  Used to determine approval path in Phase 0 (manual) → Phase 3 (autonomous).

Design:
  - 4 factors (complexity, change_type, test_coverage, track_record)
  - Weighted sum (0.25 each)
  - Immutable audit hash for every decision
  - Feedback loop: success_rate improves confidence

Safety:
  - Phase 0: ALL changes require manual approval, confidence shown for context
  - Phase 1: Confidence >= 0.85 + R0 risk = conditional auto-approve
  - Phase 2: Confidence >= 0.90 + R0 risk = auto-approve
  - Phase 3: Confidence-driven with veto override

References:
  - AUTONOMOUS_WRITE_SAFETY_BASELINE.md (Tier 1/2 approvals)
  - JARVIS_ACCESS_LEVELS.md (Level 3/4 autonomy)
  - GATE_A_CHECKLIST.md (Confidence scoring as requirement)
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional, Any
from datetime import datetime
import hashlib
import json
import logging
from pathlib import Path

logger = logging.getLogger("jarvis.confidence_scorer")


class ConfidenceLevel(Enum):
    """Human-readable confidence bands."""
    VERY_LOW = "very_low"      # 0.0–0.25: "I'm unsure"
    LOW = "low"                # 0.25–0.50: "Minor confidence"
    MEDIUM = "medium"          # 0.50–0.75: "Reasonably sure"
    HIGH = "high"              # 0.75–0.90: "High confidence"
    VERY_HIGH = "very_high"    # 0.90–1.0: "Very confident"

    @classmethod
    def from_score(cls, score: float) -> "ConfidenceLevel":
        """Map numeric score to level."""
        if score < 0.25:
            return cls.VERY_LOW
        elif score < 0.50:
            return cls.LOW
        elif score < 0.75:
            return cls.MEDIUM
        elif score < 0.90:
            return cls.HIGH
        else:
            return cls.VERY_HIGH


@dataclass
class CodeChange:
    """Proposed code change (Jarvis → Approval Gate)."""
    id: str
    file_path: str
    change_type: str  # "config", "optimization", "refactor", "feature", "docs"
    line_count: int
    description: str
    risk_class: str  # "R0" (auto), "R1" (notify), "R2" (approval), "R3" (escalate)
    diff_preview: str  # First ~500 chars of diff
    tests_updated: bool
    
    # Optional: references to related changes
    related_changes: list = field(default_factory=list)


@dataclass
class ConfidenceScore:
    """Jarvis' self-assessment for a code change."""
    overall: float  # 0.0–1.0
    level: ConfidenceLevel
    factors: Dict[str, float]  # breakdown of 4 factors
    reasoning: str  # Short explanation
    audit_hash: str  # Immutable reference (SHA256)
    timestamp: str  # ISO 8601 UTC
    phase: int  # Which phase does this enable? (0, 1, 2, 3)
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to JSON-safe dict."""
        return {
            "overall": round(self.overall, 3),
            "level": self.level.value,
            "factors": {k: round(v, 3) for k, v in self.factors.items()},
            "reasoning": self.reasoning,
            "audit_hash": self.audit_hash,
            "timestamp": self.timestamp,
            "phase": self.phase
        }


class JarvisConfidenceScorer:
    """
    Score Jarvis' confidence in proposed code changes.
    
    Phase 0: Show confidence but require manual approval (build trust).
    Phase 1: Auto-approve high-confidence + R0 (conditional).
    Phase 2: Auto-approve very-high-confidence + R0 (autonomous).
    Phase 3: Autonomous with veto (you override if needed).
    """
    
    def __init__(self, feedback_history: Optional[Dict[str, Any]] = None):
        """
        Args:
            feedback_history: {
                "embedding_model_switch": {
                    "success_rate": 0.95,
                    "n_samples": 20,
                    "last_applied": "2026-02-03T15:30:00Z"
                },
                "token_optimization": {
                    "success_rate": 0.88,
                    "n_samples": 15,
                    "last_applied": "2026-02-02T10:15:00Z"
                }
            }
        """
        self.feedback_history = feedback_history or {}
    
    def score(
        self,
        change: CodeChange,
        current_phase: int = 0
    ) -> ConfidenceScore:
        """
        Calculate Jarvis' confidence in a code change.
        
        Args:
            change: The proposed code change.
            current_phase: Current autonomy phase (0–3).
        
        Returns:
            ConfidenceScore with immutable audit hash.
        """
        
        # Compute 4 factors (each 0.0–1.0)
        complexity_score = self._score_complexity(change)
        type_score = self._score_change_type(change)
        test_score = self._score_test_coverage(change)
        track_record = self._score_track_record(change)
        
        # Weighted sum: 0.25 per factor
        overall = (
            0.25 * complexity_score
            + 0.25 * type_score
            + 0.25 * test_score
            + 0.25 * track_record
        )
        
        # Determine confidence level
        level = ConfidenceLevel.from_score(overall)
        
        # Build reasoning
        reasoning = self._build_reasoning(
            change=change,
            complexity=complexity_score,
            type_score=type_score,
            test_score=test_score,
            track_record=track_record
        )
        
        # Create immutable audit hash
        audit_hash = self._create_audit_hash(
            change_id=change.id,
            file_path=change.file_path,
            overall=overall,
            factors={
                "complexity": complexity_score,
                "type": type_score,
                "tests": test_score,
                "track_record": track_record
            }
        )
        
        # Determine phase enablement
        phase = self._determine_phase(overall, change.risk_class)
        
        return ConfidenceScore(
            overall=round(overall, 3),
            level=level,
            factors={
                "complexity": round(complexity_score, 3),
                "type": round(type_score, 3),
                "tests": round(test_score, 3),
                "track_record": round(track_record, 3)
            },
            reasoning=reasoning,
            audit_hash=audit_hash,
            timestamp=datetime.utcnow().isoformat() + "Z",
            phase=phase
        )
    
    def _score_complexity(self, change: CodeChange) -> float:
        """
        Lower lines changed + simpler logic = higher score.
        
        Heuristic:
          1–10 lines: 0.90 (trivial)
          11–50 lines: 0.75 (small)
          51–200 lines: 0.50 (medium)
          200+ lines: 0.20 (large, risky)
        """
        lines = change.line_count
        
        if lines <= 10:
            return 0.90
        elif lines <= 50:
            return 0.75
        elif lines <= 200:
            return 0.50
        else:
            # Large changes are risky; lower confidence
            return max(0.20, 1.0 - (lines / 1000))
    
    def _score_change_type(self, change: CodeChange) -> float:
        """
        Score based on change type and historical patterns.
        
        Known patterns (from feedback_history) get boost.
        Common safe patterns: configs, optimizations.
        Risky patterns: architecture, breaking changes.
        """
        
        # Check: have we done this exact change before?
        pattern_key = f"{change.file_path}:{change.change_type}"
        
        if pattern_key in self.feedback_history:
            # Known pattern with history
            return 0.85
        
        # Map change types to baseline scores
        type_scores = {
            "config": 0.80,          # Config is usually safe
            "optimization": 0.75,    # Optimization is medium risk
            "docs": 0.95,            # Docs are very safe
            "refactor": 0.50,        # Refactoring is tricky
            "feature": 0.45,         # Features are risky
            "bugfix": 0.70,          # Bugfixes vary
        }
        
        return type_scores.get(change.change_type, 0.40)
    
    def _score_test_coverage(self, change: CodeChange) -> float:
        """
        Score based on test coverage for modified file.
        
        Heuristic:
          - Tests updated: +0.25 bonus
          - Tests exist for file: 0.80 base
          - No tests: 0.40 base
        """
        
        base_score = 0.80 if Path(change.file_path).exists() else 0.40
        
        if change.tests_updated:
            return min(0.95, base_score + 0.25)
        
        return base_score
    
    def _score_track_record(self, change: CodeChange) -> float:
        """
        Score based on success rate of similar changes.
        
        If no history: return 0.50 (neutral).
        If history exists: return min(0.95, success_rate).
        
        Rationale: Never assume 100% confidence (cap at 0.95).
        """
        
        change_key = change.change_type
        
        if change_key not in self.feedback_history:
            # Unknown category: neutral confidence
            return 0.50
        
        record = self.feedback_history[change_key]
        success_rate = record.get("success_rate", 0.50)
        
        # Cap at 0.95 (always leave room for error)
        return min(0.95, success_rate)
    
    def _build_reasoning(
        self,
        change: CodeChange,
        complexity: float,
        type_score: float,
        test_score: float,
        track_record: float
    ) -> str:
        """
        Build human-readable reasoning for confidence score.
        
        Example:
          "Medium complexity (50 lines), known optimization pattern (0.75),
           tests exist (0.80), good track record (0.88) → overall 0.81 (HIGH)."
        """
        
        complexity_desc = {
            0.90: "trivial (1–10 lines)",
            0.75: "small (11–50 lines)",
            0.50: "medium (51–200 lines)",
            0.20: "large (200+ lines)"
        }
        
        comp_label = min(complexity_desc, key=lambda k: abs(k - complexity))
        
        parts = [
            f"Complexity: {complexity_desc[comp_label]} ({complexity:.2f})",
            f"Type: {change.change_type} ({type_score:.2f})",
            f"Tests: {'updated' if change.tests_updated else 'not updated'} ({test_score:.2f})",
            f"History: {track_record:.2f}"
        ]
        
        return " → ".join(parts)
    
    def _create_audit_hash(
        self,
        change_id: str,
        file_path: str,
        overall: float,
        factors: Dict[str, float]
    ) -> str:
        """
        Create immutable audit hash for this scoring decision.
        
        Purpose: Prove that this confidence score was computed
        deterministically at this moment. Prevents tampering.
        """
        
        audit_data = {
            "change_id": change_id,
            "file_path": file_path,
            "overall": overall,
            "factors": factors,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        json_str = json.dumps(audit_data, sort_keys=True)
        hash_obj = hashlib.sha256(json_str.encode("utf-8"))
        
        return hash_obj.hexdigest()
    
    def _determine_phase(self, overall: float, risk_class: str) -> int:
        """
        Determine which phase(s) this change enables.
        
        Phase 0: Always manual approval (build trust).
        Phase 1: Auto-approve if 0.85+ confidence + R0.
        Phase 2: Auto-approve if 0.90+ confidence + R0.
        Phase 3: Autonomous with veto.
        
        Returns:
            Max phase this change can reach.
        """
        
        # R1/R2/R3 always need higher approval, regardless of confidence
        if risk_class in ["R2", "R3"]:
            return 0  # Must be manual even if high confidence
        
        if risk_class == "R1":
            if overall >= 0.85:
                return 1  # Conditional auto-approve
            return 0
        
        # R0 (low-risk)
        if overall >= 0.90:
            return 2  # Can auto-approve
        elif overall >= 0.85:
            return 1  # Conditional auto-approve
        else:
            return 0  # Manual approval
    
    def update_feedback(self, change_type: str, success: bool, details: Optional[Dict] = None) -> None:
        """
        Update feedback history based on deployment result.
        
        Called after a change is deployed + measured.
        Improves future confidence scores via track_record factor.
        
        Args:
            change_type: Type of change that was deployed.
            success: Did it achieve intended goal?
            details: Optional metrics (latency improvement %, tokens saved, etc).
        """
        
        if change_type not in self.feedback_history:
            self.feedback_history[change_type] = {
                "success_rate": 0.5,
                "n_samples": 0,
                "successes": 0,
                "failures": 0,
                "last_updated": None
            }
        
        record = self.feedback_history[change_type]
        
        # Update counters
        record["n_samples"] += 1
        if success:
            record["successes"] = record.get("successes", 0) + 1
        else:
            record["failures"] = record.get("failures", 0) + 1
        
        # Recalculate success rate
        record["success_rate"] = (
            record.get("successes", 0) / max(1, record["n_samples"])
        )
        
        # Track last update
        record["last_updated"] = datetime.utcnow().isoformat() + "Z"
        
        logger.info(
            f"Updated feedback: {change_type}",
            extra={
                "change_type": change_type,
                "success": success,
                "success_rate": record["success_rate"],
                "n_samples": record["n_samples"]
            }
        )
