import pytest
from datetime import datetime, timedelta
from app.models.memory_fact import MemoryFact
from app.memory.retrieval import MemoryRetrievalEngine
from app.memory.tagging import TaggingEngine
from app.memory.confidence import ConfidenceScorer

def make_fact(id, key, value, confidence=0.7, source="user_explicit", days_ago=0, tags=None):
    now = datetime.utcnow()
    return MemoryFact(
        id=id,
        user_id="user1",
        namespace="work",
        key=key,
        value=value,
        confidence=confidence,
        source=source,
        created_at=now - timedelta(days=days_ago),
        updated_at=now - timedelta(days=days_ago),
        tags=tags or [],
        hygiene_metadata={"last_accessed_days": days_ago, "access_count": 3}
    )

def test_retrieval_scoring():
    facts = [
        make_fact("f1", "project", "Project Apollo", 0.9, days_ago=1),
        make_fact("f2", "meeting", "Meeting with Alice Smith", 0.6, days_ago=10),
        make_fact("f3", "deadline", "2026-03-01", 0.8, days_ago=2),
    ]
    engine = MemoryRetrievalEngine(facts)
    query = {"key": "project", "namespace": "work", "tags": ["topic:project"]}
    results = engine.retrieve(query, min_score=0.3)
    assert results[0].key == "project"
    assert len(results) == 3

def test_auto_tagging():
    fact = make_fact("f4", "meeting", "Meeting with Bob Miller on 2026-03-01", 0.7)
    TaggingEngine().tag_facts([fact])
    assert any(t.startswith("person:") for t in fact.tags)
    assert any(t.startswith("date:") for t in fact.tags)
    assert "ns:work" in fact.tags

def test_confidence_scoring():
    fact = make_fact("f5", "deadline", "2026-03-01", 0.8, days_ago=40)
    scorer = ConfidenceScorer()
    scorer.annotate_facts([fact], {"f5": 0.9})
    assert 0.0 <= fact.hygiene_metadata["confidence_score"] <= 1.0
    assert 0.0 <= fact.hygiene_metadata["uncertainty"] <= 1.0
    # Penalty für alte Fakten
    assert fact.hygiene_metadata["confidence_score"] < 0.9
