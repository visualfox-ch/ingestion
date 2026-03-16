from typing import List, Dict, Any
from app.models.memory_fact import MemoryFact

class ConfidenceScorer:
    """Berechnet Confidence-Score und Unsicherheitsbewertung für Recalls."""
    def score(self, fact: MemoryFact, retrieval_score: float = 1.0) -> float:
        # Basis: fact.confidence (0.0-1.0)
        score = fact.confidence
        # Bonus für hohe Retrieval-Relevanz
        score += 0.2 * retrieval_score
        # Penalty für alte oder selten genutzte Fakten
        if fact.hygiene_metadata.get("last_accessed_days", 0) > 30:
            score -= 0.1
        if fact.hygiene_metadata.get("access_count", 1) < 2:
            score -= 0.05
        # Schutz für explizite User-Fakten
        if fact.source == "user_explicit":
            score += 0.1
        return max(0.0, min(score, 1.0))

    def annotate_facts(self, facts: List[MemoryFact], retrieval_scores: Dict[str, float]) -> None:
        for fact in facts:
            conf = self.score(fact, retrieval_scores.get(fact.id, 1.0))
            fact.hygiene_metadata["confidence_score"] = conf
            fact.hygiene_metadata["uncertainty"] = 1.0 - conf
