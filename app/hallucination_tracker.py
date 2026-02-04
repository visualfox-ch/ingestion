"""
Hallucination Tracker for Self-Optimization

Detects and tracks unverified claims in LLM responses.
Enforces Evidence-Contract principle: cite sources for factual claims.

Research Foundation:
- Ji, Z. et al. (2023). "Survey of Hallucination in Natural Language Generation."
  ACM Computing Surveys 55(12):1-38.
- Manakul, P. et al. (2023). "SelfCheckGPT: Zero-Resource Black-Box Hallucination 
  Detection for Generative Large Language Models." arXiv:2303.08896.

Hallucination Types:
1. Factoid: Incorrect facts (dates, names, numbers)
2. Unverified: Claims without source attribution
3. Conflicting: Internal contradictions in response
4. Out-of-scope: Claims beyond available context

Target: <10% hallucination rate

Author: GitHub Copilot
Created: 2026-02-03
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Set
from enum import Enum
import json
import re
from pathlib import Path

from .observability import get_logger

logger = get_logger("jarvis.hallucination_tracker")


class HallucinationType(str, Enum):
    """Types of hallucination."""
    FACTOID = "factoid"              # Incorrect facts
    UNVERIFIED = "unverified"        # Claims without sources
    CONFLICTING = "conflicting"      # Internal contradictions
    OUT_OF_SCOPE = "out_of_scope"    # Beyond available context
    NONE = "none"                     # No hallucination detected


class HallucinationSeverity(str, Enum):
    """Hallucination severity levels."""
    LOW = "low"           # Minor issue, doesn't affect answer quality
    MEDIUM = "medium"     # Moderate issue, some impact on quality
    HIGH = "high"         # Serious issue, significantly affects quality
    CRITICAL = "critical" # Answer is largely incorrect


class HallucinationTracker:
    """
    Track and detect hallucinations in LLM responses.
    
    Detection methods:
    1. Evidence-Contract enforcement: Check for source citations
    2. Pattern matching: Detect unsupported factual claims
    3. Consistency checking: Find internal contradictions
    4. Context boundary: Verify claims are within retrieved context
    
    Metrics tracked:
    - hallucination_rate: % of responses with hallucinations
    - unverified_claim_rate: % with unsupported factual claims
    - avg_severity: Average hallucination severity
    - per_type_rate: Breakdown by hallucination type
    """
    
    def __init__(self, state_path: str = "/brain/system/state"):
        """Initialize hallucination tracker."""
        self.state_path = Path(state_path)
        self.state_path.mkdir(parents=True, exist_ok=True)
        
        self.history_file = self.state_path / "hallucination_history.json"
        self.history: List[Dict] = []
        self._load_history()
        
        # Patterns that indicate factual claims (require sources)
        self.factual_claim_patterns = [
            r"according to",
            r"research shows",
            r"studies indicate",
            r"evidence suggests",
            r"data reveals",
            r"statistics show",
            r"in \d{4}",  # Years
            r"\d+%",      # Percentages
            r"\d+ percent",
            r"the .+ algorithm",
            r"the .+ method",
            r"defined as",
            r"is known as"
        ]
        
        # Evidence indicators (good - shows sourcing)
        self.evidence_indicators = [
            r"source:",
            r"from:",
            r"\[.+\]\(.+\)",  # Markdown links
            r"file:",
            r"document:",
            r"per ",
            r"via ",
            r"citing "
        ]
    
    def check_response(
        self,
        response_text: str,
        retrieved_context: Optional[List[str]] = None,
        tool_calls_made: Optional[List[str]] = None,
        domain: str = "general"
    ) -> Dict[str, Any]:
        """
        Check response for hallucinations.
        
        Args:
            response_text: The response text to check
            retrieved_context: Optional list of retrieved context chunks
            tool_calls_made: Optional list of tool names called
            domain: Domain category
            
        Returns:
            Dict with structure:
            {
                "has_hallucination": bool,
                "hallucination_type": HallucinationType,
                "severity": HallucinationSeverity,
                "unverified_claims": List[str],
                "evidence_score": float (0-1),
                "details": str,
                "recommendations": List[str]
            }
        """
        unverified_claims = []
        has_evidence = False
        severity = HallucinationSeverity.LOW
        hallucination_type = HallucinationType.NONE
        recommendations = []
        
        # Check 1: Evidence-Contract compliance
        factual_claims = self._find_factual_claims(response_text)
        evidence_found = self._find_evidence_indicators(response_text)
        
        if factual_claims and not evidence_found:
            # Factual claims without evidence = unverified hallucination
            unverified_claims = factual_claims
            hallucination_type = HallucinationType.UNVERIFIED
            severity = HallucinationSeverity.MEDIUM
            recommendations.append("add_source_citations")
            recommendations.append("use_search_knowledge_before_defining")
        
        # Check 2: Context boundary (if context provided)
        if retrieved_context:
            out_of_scope = self._check_context_boundary(
                response_text,
                retrieved_context
            )
            if out_of_scope:
                hallucination_type = HallucinationType.OUT_OF_SCOPE
                severity = HallucinationSeverity.HIGH
                recommendations.append("verify_claims_in_context")
        
        # Check 3: Internal consistency
        contradictions = self._find_contradictions(response_text)
        if contradictions:
            hallucination_type = HallucinationType.CONFLICTING
            severity = HallucinationSeverity.HIGH
            recommendations.append("resolve_contradictions")
        
        # Calculate evidence score (0-1)
        # Higher = better evidence/sourcing
        if evidence_found:
            evidence_score = min(1.0, len(evidence_found) / max(1, len(factual_claims)))
            has_evidence = True
        else:
            evidence_score = 0.0 if factual_claims else 1.0  # No claims = no problem
        
        has_hallucination = hallucination_type != HallucinationType.NONE
        
        result = {
            "has_hallucination": has_hallucination,
            "hallucination_type": hallucination_type,
            "severity": severity,
            "unverified_claims_count": len(unverified_claims),
            "unverified_claims": unverified_claims[:5],  # Limit to first 5
            "evidence_score": evidence_score,
            "factual_claims_count": len(factual_claims),
            "evidence_found_count": len(evidence_found),
            "details": self._build_details(
                hallucination_type,
                len(factual_claims),
                len(evidence_found),
                len(unverified_claims)
            ),
            "recommendations": recommendations,
            "domain": domain,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        if has_hallucination:
            logger.warning(
                "Hallucination detected (type=%s, severity=%s, unverified_count=%s, domain=%s)",
                hallucination_type.value,
                severity.value,
                len(unverified_claims),
                domain,
            )
        else:
            logger.info(
                "No hallucination detected (evidence_score=%s, domain=%s)",
                evidence_score,
                domain,
            )
        
        return result
    
    def _find_factual_claims(self, text: str) -> List[str]:
        """
        Find sentences containing factual claims that require sources.
        
        Args:
            text: Response text
            
        Returns:
            List of sentences with factual claims
        """
        claims = []
        sentences = text.split('.')
        
        for sentence in sentences:
            for pattern in self.factual_claim_patterns:
                if re.search(pattern, sentence.lower()):
                    claims.append(sentence.strip())
                    break
        
        return claims
    
    def _find_evidence_indicators(self, text: str) -> List[str]:
        """
        Find evidence/source indicators in text.
        
        Args:
            text: Response text
            
        Returns:
            List of evidence indicators found
        """
        indicators = []
        
        for pattern in self.evidence_indicators:
            matches = re.findall(pattern, text.lower())
            indicators.extend(matches)
        
        return indicators
    
    def _check_context_boundary(
        self,
        response_text: str,
        retrieved_context: List[str]
    ) -> bool:
        """
        Check if response makes claims beyond retrieved context.
        
        Simple heuristic: If response contains many unique terms
        not in context, it may be out of scope.
        
        Args:
            response_text: Response text
            retrieved_context: Retrieved context chunks
            
        Returns:
            True if likely out of scope
        """
        # Extract key terms from response (simple word extraction)
        response_words = set(re.findall(r'\b[a-z]{4,}\b', response_text.lower()))
        
        # Extract key terms from context
        context_text = ' '.join(retrieved_context)
        context_words = set(re.findall(r'\b[a-z]{4,}\b', context_text.lower()))
        
        # Calculate overlap
        unique_in_response = response_words - context_words
        overlap_ratio = len(response_words & context_words) / max(1, len(response_words))
        
        # If <30% overlap, likely out of scope
        return overlap_ratio < 0.3 and len(unique_in_response) > 10
    
    def _find_contradictions(self, text: str) -> List[str]:
        """
        Find potential internal contradictions.
        
        Simple heuristic: Look for contradictory phrases in same response.
        
        Args:
            text: Response text
            
        Returns:
            List of potential contradictions
        """
        contradictions = []
        text_lower = text.lower()
        
        # Common contradiction patterns
        contradiction_pairs = [
            ("is", "is not"),
            ("should", "should not"),
            ("will", "will not"),
            ("can", "cannot"),
            ("does", "does not")
        ]
        
        for positive, negative in contradiction_pairs:
            if positive in text_lower and negative in text_lower:
                contradictions.append(f"{positive}_vs_{negative}")
        
        return contradictions
    
    def _build_details(
        self,
        hallucination_type: HallucinationType,
        claims_count: int,
        evidence_count: int,
        unverified_count: int
    ) -> str:
        """Build human-readable details string."""
        if hallucination_type == HallucinationType.NONE:
            if claims_count == 0:
                return "no_factual_claims_made"
            else:
                return f"{claims_count}_claims_all_sourced"
        
        if hallucination_type == HallucinationType.UNVERIFIED:
            return f"{unverified_count}_unverified_claims_of_{claims_count}_total"
        
        return f"hallucination_type_{hallucination_type.value}"
    
    def record_hallucination(
        self,
        has_hallucination: bool,
        hallucination_type: HallucinationType,
        severity: HallucinationSeverity,
        domain: str = "general",
        metadata: Optional[Dict] = None
    ) -> None:
        """
        Record hallucination detection result.
        
        Args:
            has_hallucination: Whether hallucination was detected
            hallucination_type: Type of hallucination
            severity: Severity level
            domain: Domain category
            metadata: Optional metadata
        """
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "has_hallucination": has_hallucination,
            "hallucination_type": hallucination_type.value,
            "severity": severity.value,
            "domain": domain,
            "metadata": metadata or {}
        }
        
        self.history.append(entry)
        
        # Limit history size
        if len(self.history) > 10000:
            self.history = self.history[-10000:]
        
        self._save_history()
    
    def get_hallucination_rate(
        self,
        domain: Optional[str] = None,
        time_window_hours: Optional[int] = None
    ) -> float:
        """
        Calculate hallucination rate.
        
        Args:
            domain: Optional domain filter
            time_window_hours: Optional time window (last N hours)
            
        Returns:
            Hallucination rate (0-1)
        """
        # Filter history
        relevant = self.history
        
        if domain:
            relevant = [h for h in relevant if h["domain"] == domain]
        
        if time_window_hours:
            cutoff = datetime.utcnow() - timedelta(hours=time_window_hours)
            relevant = [
                h for h in relevant
                if datetime.fromisoformat(h["timestamp"]) > cutoff
            ]
        
        if not relevant:
            return 0.0
        
        hallucination_count = sum(1 for h in relevant if h["has_hallucination"])
        return hallucination_count / len(relevant)
    
    def get_metrics_report(self) -> Dict[str, Any]:
        """
        Get comprehensive hallucination metrics.
        
        Returns:
            Dict with metrics
        """
        overall_rate = self.get_hallucination_rate()
        
        # Per-domain rates
        domains = set(h["domain"] for h in self.history)
        per_domain_rate = {}
        for domain in domains:
            rate = self.get_hallucination_rate(domain)
            per_domain_rate[domain] = rate
        
        # Per-type breakdown
        type_counts = {}
        for h in self.history:
            if h["has_hallucination"]:
                h_type = h["hallucination_type"]
                type_counts[h_type] = type_counts.get(h_type, 0) + 1
        
        # Recent trend (last 24h)
        recent_rate = self.get_hallucination_rate(time_window_hours=24)
        
        return {
            "overall_hallucination_rate": overall_rate,
            "recent_24h_rate": recent_rate,
            "per_domain_rate": per_domain_rate,
            "per_type_counts": type_counts,
            "total_samples": len(self.history),
            "quality_assessment": "good" if overall_rate < 0.10 else "needs_improvement",
            "timestamp": datetime.utcnow().isoformat()
        }
    
    def _load_history(self) -> None:
        """Load history from disk."""
        if self.history_file.exists():
            try:
                with open(self.history_file, 'r') as f:
                    data = json.load(f)
                    self.history = data.get("history", [])
                logger.info("Hallucination history loaded (samples=%s)", len(self.history))
            except Exception as e:
                logger.error("Failed to load hallucination history: %s", e)
                self.history = []
        else:
            self.history = []
    
    def _save_history(self) -> None:
        """Save history to disk."""
        try:
            data = {
                "history": self.history,
                "last_updated": datetime.utcnow().isoformat()
            }
            with open(self.history_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error("Failed to save hallucination history: %s", e)


# Singleton instance
_hallucination_tracker: Optional[HallucinationTracker] = None


def get_hallucination_tracker() -> HallucinationTracker:
    """Get singleton hallucination tracker instance."""
    global _hallucination_tracker
    if _hallucination_tracker is None:
        _hallucination_tracker = HallucinationTracker()
    return _hallucination_tracker
