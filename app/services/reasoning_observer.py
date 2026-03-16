"""
Reasoning Observer Service - Tier 1 Quick Win

Provides observability into Jarvis's reasoning process:
- Tool selection rationale ("Why Tool X instead of Y?")
- Confidence scoring per response
- Reasoning path visibility
- Hallucination risk detection

This enables debugging of decision support tools and provides
foundation for more complex Tier 2 features.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from enum import Enum
import time

from ..observability import get_logger, log_with_context
from ..metrics import (
    record_reasoning_confidence,
    record_tool_selection_reason,
    record_reasoning_path,
    record_tool_alternative,
    record_hallucination_flag,
    record_reasoning_depth,
)

logger = get_logger("jarvis.reasoning_observer")


class SelectionReason(Enum):
    """Reasons why a tool might be selected."""
    KEYWORD_MATCH = "keyword_match"
    CONTEXT_RELEVANCE = "context_relevance"
    EXPLICIT_REQUEST = "explicit_request"
    HISTORICAL_SUCCESS = "historical_success"
    FALLBACK = "fallback"
    CHAINED = "chained"  # Part of a tool chain


class HallucinationRisk(Enum):
    """Types of hallucination risk flags."""
    NO_TOOL_DATA = "no_tool_data"
    LOW_CONFIDENCE = "low_confidence"
    UNVERIFIED_CLAIM = "unverified_claim"
    CONFLICTING_SOURCES = "conflicting_sources"
    OUTDATED_KNOWLEDGE = "outdated_knowledge"


@dataclass
class ToolSelectionEvent:
    """Records a tool selection decision."""
    tool_name: str
    reason: SelectionReason
    confidence: float
    alternatives_considered: List[str] = field(default_factory=list)
    rejection_reasons: Dict[str, str] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass
class ReasoningStep:
    """A single step in the reasoning path."""
    step_type: str  # tool_call, direct_response, context_lookup, knowledge_retrieval
    description: str
    outcome: str  # success, failure, skip
    confidence: float = 0.0
    duration_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ReasoningTrace:
    """Complete reasoning trace for a single query."""
    query: str
    query_type: str  # simple, complex, multi_tool
    steps: List[ReasoningStep] = field(default_factory=list)
    tool_selections: List[ToolSelectionEvent] = field(default_factory=list)
    overall_confidence: float = 0.0
    hallucination_flags: List[HallucinationRisk] = field(default_factory=list)
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None

    @property
    def duration_ms(self) -> float:
        if self.end_time:
            return (self.end_time - self.start_time) * 1000
        return 0.0

    @property
    def depth(self) -> int:
        return len(self.steps)


class ReasoningObserver:
    """
    Observes and records the reasoning process during agent execution.

    Usage:
        observer = ReasoningObserver(query="User query here")

        # Record tool selection
        observer.record_tool_selection(
            tool_name="search_knowledge",
            reason=SelectionReason.KEYWORD_MATCH,
            confidence=0.85,
            alternatives=["web_search", "memory_lookup"],
            rejection_reasons={"web_search": "no_internet_needed"}
        )

        # Record reasoning steps
        observer.add_step(
            step_type="tool_call",
            description="Searched knowledge base for fitness patterns",
            outcome="success",
            confidence=0.9
        )

        # Finalize and get trace
        trace = observer.finalize()
    """

    def __init__(self, query: str, query_type: str = "complex"):
        self.trace = ReasoningTrace(query=query, query_type=query_type)
        self._step_start: Optional[float] = None

    def record_tool_selection(
        self,
        tool_name: str,
        reason: SelectionReason,
        confidence: float,
        alternatives: Optional[List[str]] = None,
        rejection_reasons: Optional[Dict[str, str]] = None
    ):
        """Record a tool selection decision with rationale."""
        event = ToolSelectionEvent(
            tool_name=tool_name,
            reason=reason,
            confidence=confidence,
            alternatives_considered=alternatives or [],
            rejection_reasons=rejection_reasons or {}
        )
        self.trace.tool_selections.append(event)

        # Record metrics
        record_tool_selection_reason(tool_name, reason.value)
        record_reasoning_confidence("tool_selection", confidence)

        # Record alternatives
        for alt in (alternatives or []):
            rejection = (rejection_reasons or {}).get(alt, "not_best_match")
            record_tool_alternative(tool_name, alt, rejection)

        log_with_context(
            logger, "debug",
            f"Tool selected: {tool_name}",
            reason=reason.value,
            confidence=confidence,
            alternatives=alternatives,
        )

    def start_step(self):
        """Mark the start of a reasoning step (for timing)."""
        self._step_start = time.time()

    def add_step(
        self,
        step_type: str,
        description: str,
        outcome: str,
        confidence: float = 0.0,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Add a reasoning step to the trace."""
        duration_ms = 0.0
        if self._step_start:
            duration_ms = (time.time() - self._step_start) * 1000
            self._step_start = None

        step = ReasoningStep(
            step_type=step_type,
            description=description,
            outcome=outcome,
            confidence=confidence,
            duration_ms=duration_ms,
            metadata=metadata or {}
        )
        self.trace.steps.append(step)

        # Record metrics
        record_reasoning_path(step_type, outcome)
        if confidence > 0:
            record_reasoning_confidence("step", confidence)

    def flag_hallucination_risk(self, risk_type: HallucinationRisk, details: str = ""):
        """Flag a potential hallucination risk."""
        self.trace.hallucination_flags.append(risk_type)
        record_hallucination_flag(risk_type.value)

        log_with_context(
            logger, "warning",
            f"Hallucination risk flagged: {risk_type.value}",
            details=details,
            query=self.trace.query[:100]
        )

    def calculate_overall_confidence(self) -> float:
        """Calculate overall confidence from all steps and selections."""
        confidences = []

        # Tool selection confidences
        for sel in self.trace.tool_selections:
            confidences.append(sel.confidence)

        # Step confidences
        for step in self.trace.steps:
            if step.confidence > 0:
                confidences.append(step.confidence)

        if not confidences:
            return 0.5  # Default neutral confidence

        # Weighted average with penalty for hallucination flags
        avg_confidence = sum(confidences) / len(confidences)

        # Reduce confidence for each hallucination flag
        penalty = len(self.trace.hallucination_flags) * 0.1

        return max(0.0, min(1.0, avg_confidence - penalty))

    def finalize(self) -> ReasoningTrace:
        """Finalize the trace and record final metrics."""
        self.trace.end_time = time.time()
        self.trace.overall_confidence = self.calculate_overall_confidence()

        # Record final metrics
        record_reasoning_depth(self.trace.query_type, self.trace.depth)
        record_reasoning_confidence("overall", self.trace.overall_confidence)

        log_with_context(
            logger, "info",
            "Reasoning trace finalized",
            query_type=self.trace.query_type,
            depth=self.trace.depth,
            confidence=f"{self.trace.overall_confidence:.2f}",
            duration_ms=round(self.trace.duration_ms, 1),
            tool_count=len(self.trace.tool_selections),
            hallucination_flags=len(self.trace.hallucination_flags),
        )

        return self.trace

    def to_dict(self) -> Dict[str, Any]:
        """Export trace as dictionary for logging/storage."""
        return {
            "query": self.trace.query[:200],
            "query_type": self.trace.query_type,
            "depth": self.trace.depth,
            "overall_confidence": self.trace.overall_confidence,
            "duration_ms": self.trace.duration_ms,
            "tool_selections": [
                {
                    "tool": s.tool_name,
                    "reason": s.reason.value,
                    "confidence": s.confidence,
                    "alternatives": s.alternatives_considered,
                }
                for s in self.trace.tool_selections
            ],
            "steps": [
                {
                    "type": s.step_type,
                    "description": s.description[:100],
                    "outcome": s.outcome,
                    "confidence": s.confidence,
                }
                for s in self.trace.steps
            ],
            "hallucination_flags": [f.value for f in self.trace.hallucination_flags],
        }


# Singleton pattern for cross-module access
_current_observer: Optional[ReasoningObserver] = None


def start_reasoning_observation(query: str, query_type: str = "complex") -> ReasoningObserver:
    """Start a new reasoning observation session."""
    global _current_observer
    _current_observer = ReasoningObserver(query=query, query_type=query_type)
    return _current_observer


def get_current_observer() -> Optional[ReasoningObserver]:
    """Get the current reasoning observer (if any)."""
    return _current_observer


def clear_current_observer():
    """Clear the current observer after request completion."""
    global _current_observer
    _current_observer = None


def classify_query_for_reasoning(query: str, tool_count: int = 0) -> str:
    """Classify query type for reasoning metrics."""
    query_lower = query.lower()

    if tool_count > 2:
        return "multi_tool"

    # Simple queries
    simple_patterns = ["hallo", "hi", "danke", "status", "wie geht"]
    if any(p in query_lower for p in simple_patterns) and len(query) < 50:
        return "simple"

    # Complex indicators
    complex_patterns = ["vergleiche", "analysiere", "erkläre", "warum", "strategie"]
    if any(p in query_lower for p in complex_patterns):
        return "complex"

    return "standard"


def infer_selection_reason(
    tool_name: str,
    query: str,
    tool_keywords: Optional[List[str]] = None
) -> SelectionReason:
    """Infer why a tool was likely selected based on query analysis."""
    query_lower = query.lower()

    # Check for explicit tool mention
    if tool_name.lower() in query_lower:
        return SelectionReason.EXPLICIT_REQUEST

    # Check keyword matches
    if tool_keywords:
        for kw in tool_keywords:
            if kw.lower() in query_lower:
                return SelectionReason.KEYWORD_MATCH

    # Default to context relevance
    return SelectionReason.CONTEXT_RELEVANCE
