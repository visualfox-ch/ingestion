"""
Facette Detection for Unified Personality (Jarvis v2.13.0)

Implements Q2 Answer: Sentiment + Context Weight activation mechanism
for detecting which thinking style facettes are active in a query.

Architecture (Q1 Answer: Verschachtelt):
- Facettes = Meta-layer (thinking styles: Analytical/Empathic/Pragmatic/Creative)
- Domänes = Content-layer (expertise: Fitness/Coaching/Analysis/etc.)
- Each domain filtered through active facette blend

Author: GitHub Copilot
Created: 2026-02-03
Task: T-20260203-005 Phase 1 (Facette Detection)
"""

import re
from typing import Dict, List, Optional
from dataclasses import dataclass


@dataclass
class FacetteWeights:
    """Facette activation weights for a query"""
    analytical: float = 0.0
    empathic: float = 0.0
    pragmatic: float = 0.0
    creative: float = 0.0
    
    def normalize(self) -> "FacetteWeights":
        """Normalize weights to sum to 1.0"""
        total = self.analytical + self.empathic + self.pragmatic + self.creative
        if total == 0:
            # Default blend if no facettes detected
            return FacetteWeights(
                analytical=0.4,
                empathic=0.2,
                pragmatic=0.3,
                creative=0.1
            )
        return FacetteWeights(
            analytical=self.analytical / total,
            empathic=self.empathic / total,
            pragmatic=self.pragmatic / total,
            creative=self.creative / total
        )
    
    def to_dict(self) -> Dict[str, float]:
        """Convert to dict for JSON serialization"""
        return {
            "Analytical": round(self.analytical, 2),
            "Empathic": round(self.empathic, 2),
            "Pragmatic": round(self.pragmatic, 2),
            "Creative": round(self.creative, 2)
        }
    
    def dominant_facette(self) -> str:
        """Return the facette with highest weight"""
        weights = self.to_dict()
        return max(weights.items(), key=lambda x: x[1])[0]


class FacetteDetector:
    """
    Detects facette activation based on keywords and sentiment.
    
    Implementation of Jarvis Q2 Answer:
    - Keyword-based intent detection
    - Weighted blend (smooth transitions, not hard switches)
    """
    
    # Keyword patterns for each facette (Q2 Answer)
    ANALYTICAL_KEYWORDS = [
        r'\b(analyz|understand|explain|why|how does|metric|data|measure|track|optimize|breakdown|system)',
        r'\b(statistic|number|percentage|compare|evaluate|assess|logic|reason)',
    ]
    
    EMPATHIC_KEYWORDS = [
        r'\b(feel|emotion|stress|overwhelm|too much|energy|mood|tired|exhaust)',
        r'\b(struggle|difficult|hard|challenging|worry|concern|afraid|anxious)',
        r'\b(support|help me|understand me|listen|care)',
    ]
    
    PRAGMATIC_KEYWORDS = [
        r'\b(what should i|next step|action|do now|todo|task|priority|quick)',
        r'\b(simple|easy|fast|efficient|practical|just tell me|bottom line)',
        r'\b(fix|solve|implement|execute|deploy|ship)',
    ]
    
    CREATIVE_KEYWORDS = [
        r'\b(idea|brainstorm|creative|innovate|alternative|different|new approach)',
        r'\b(what if|could we|experiment|explore|try|imagine|vision)',
        r'\b(design|concept|prototype|draft)',
    ]
    
    def __init__(self):
        # Compile regex patterns for performance
        self.analytical_patterns = [re.compile(p, re.IGNORECASE) for p in self.ANALYTICAL_KEYWORDS]
        self.empathic_patterns = [re.compile(p, re.IGNORECASE) for p in self.EMPATHIC_KEYWORDS]
        self.pragmatic_patterns = [re.compile(p, re.IGNORECASE) for p in self.PRAGMATIC_KEYWORDS]
        self.creative_patterns = [re.compile(p, re.IGNORECASE) for p in self.CREATIVE_KEYWORDS]
    
    def detect(self, query: str, context: Optional[str] = None) -> FacetteWeights:
        """
        Detect facette activation for a query.
        
        Args:
            query: User's query text
            context: Optional context (previous messages, domain info)
            
        Returns:
            FacetteWeights with normalized weights (sum to 1.0)
        """
        text = query.lower()
        if context:
            text += " " + context.lower()
        
        weights = FacetteWeights()
        
        # Count keyword matches for each facette
        weights.analytical = self._count_matches(text, self.analytical_patterns)
        weights.empathic = self._count_matches(text, self.empathic_patterns)
        weights.pragmatic = self._count_matches(text, self.pragmatic_patterns)
        weights.creative = self._count_matches(text, self.creative_patterns)
        
        # Sentiment-based boosting (simple heuristics for now)
        weights = self._apply_sentiment_boost(text, weights)
        
        # Normalize to sum to 1.0
        return weights.normalize()
    
    def _count_matches(self, text: str, patterns: List[re.Pattern]) -> float:
        """Count total keyword matches for a facette"""
        count = 0.0
        for pattern in patterns:
            matches = pattern.findall(text)
            count += len(matches)
        return count
    
    def _apply_sentiment_boost(self, text: str, weights: FacetteWeights) -> FacetteWeights:
        """
        Apply sentiment-based boosting to facette weights.
        
        Heuristics (Q2 Answer):
        - Stress indicators → boost Empathic + Pragmatic
        - Question marks + confusion → boost Analytical
        - Exclamation + enthusiasm → boost Creative
        - Imperatives → boost Pragmatic
        """
        # Stress/overwhelm boost (Q2 example: stress → +Empathic +Pragmatic)
        if any(word in text for word in ["stress", "overwhelm", "too much", "can't handle"]):
            weights.empathic += 1.5
            weights.pragmatic += 1.0
        
        # Complex questions boost Analytical
        if text.count("?") >= 2 or "why" in text or "how does" in text:
            weights.analytical += 1.0
        
        # Enthusiasm/exploration boost Creative
        if text.count("!") >= 1 or "what if" in text or "could we" in text:
            weights.creative += 1.0
        
        # Action-oriented boost Pragmatic
        if any(text.startswith(word) for word in ["do ", "make ", "create ", "fix ", "update "]):
            weights.pragmatic += 1.5
        
        return weights
    
    def detect_domain(self, query: str) -> str:
        """
        Detect primary domain (content-layer) from query.
        
        Returns domain name or "general" if not detected.
        """
        text = query.lower()
        
        # Domain keywords (simple version - can be expanded)
        if any(word in text for word in ["training", "workout", "exercise", "fitness", "gym", "nutrition"]):
            return "Fitness"
        elif any(word in text for word in ["coaching", "career", "goal", "development", "mentor"]):
            return "Coaching"
        elif any(word in text for word in ["code", "bug", "deploy", "docker", "python", "api"]):
            return "Engineering"
        elif any(word in text for word in ["write", "document", "article", "content", "blog"]):
            return "Writing"
        elif any(word in text for word in ["research", "analyze", "study", "investigate"]):
            return "Analysis"
        else:
            return "General"


# Global singleton instance
_detector = None


def get_facette_detector() -> FacetteDetector:
    """Get or create the global FacetteDetector instance"""
    global _detector
    if _detector is None:
        _detector = FacetteDetector()
    return _detector
