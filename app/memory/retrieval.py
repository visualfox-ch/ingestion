from typing import List, Dict, Any
from datetime import datetime
from app.models.memory_fact import MemoryFact


class MemoryRetrievalEngine:
    """Retrieval-Engine für MemoryFacts mit Scoring und Priorisierung."""
    def __init__(self, facts: List[MemoryFact]):
        self.facts = facts

    def score_fact(self, query: Dict[str, Any], fact: MemoryFact) -> float:
        score = 0.0
        if query.get("key") == fact.key:
            score += 0.4
        if query.get("namespace") == fact.namespace:
            score += 0.2
        age_days = (datetime.utcnow() - fact.updated_at).days
        score += max(0.1, 0.3 - 0.01 * age_days)
        if query.get("tags") and set(query["tags"]).intersection(set(fact.tags)):
            score += 0.2
        score += 0.2 * fact.confidence
        return min(score, 1.0)

    def retrieve(self, query: Dict[str, Any], min_score: float = 0.5) -> List[MemoryFact]:
        scored = [
            (fact, self.score_fact(query, fact))
            for fact in self.facts
        ]
        filtered = [fact for fact, score in scored if score >= min_score]
        sorted_facts = sorted(filtered, key=lambda f: self.score_fact(query, f), reverse=True)
        return sorted_facts


# --- NEU: Semantische Suche via Qdrant ---
from app.embed import embed_texts
from qdrant_client import QdrantClient
from app.models.memory_fact import MemoryFact
import os

class QdrantSemanticRetrievalEngine:
    """Semantische Memory-Retrieval-Engine mit Vektor-Suche via Qdrant."""
    def __init__(self, collection: str = "memory_facts", host: str = None, port: int = None):
        self.collection = collection
        self.host = host or os.environ.get("QDRANT_HOST", "qdrant")
        self.port = port or int(os.environ.get("QDRANT_PORT", "6333"))
        self.client = QdrantClient(host=self.host, port=self.port)

    def semantic_search(self, query_text: str, top_k: int = 10, namespace: str = None) -> list:
        query_vec = embed_texts([query_text])[0]
        search_filter = None
        if namespace:
            from qdrant_client.models import Filter, FieldCondition, MatchValue
            search_filter = Filter(must=[FieldCondition(key="namespace", match=MatchValue(value=namespace))])
        hits = self.client.search(
            collection_name=self.collection,
            query_vector=query_vec,
            limit=top_k,
            query_filter=search_filter,
            with_payload=True
        )
        results = []
        for hit in hits:
            payload = hit.payload or {}
            # Rekonstruiere MemoryFact aus Payload (vereinfachte Version)
            mf = MemoryFact(
                id=payload.get("id", str(hit.id)),
                user_id=payload.get("user_id", "unknown"),
                namespace=payload.get("namespace", "default"),
                key=payload.get("key", ""),
                value=payload.get("text", ""),
                confidence=payload.get("confidence", 0.5),
                source=payload.get("source", "qdrant"),
                created_at=payload.get("created_at", datetime.utcnow()),
                updated_at=payload.get("updated_at", datetime.utcnow()),
                expires_at=None,
                status=payload.get("status", "active"),
                tags=payload.get("tags", []),
                hygiene_metadata=payload.get("hygiene_metadata", {})
            )
            results.append({"score": hit.score, "fact": mf})
        return results
