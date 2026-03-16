import pytest

from app.entity_privacy_filter import filter_entity_contexts
from app.entity_aware_response_builder import build_entity_response_payload
from app.entity_context_loader import EntityContext
from app.entity_extractor import ExtractedEntity


class DummyContextResult:
    def __init__(self, contexts, cache_hits=0, total_load_time_ms=12.5, errors=None):
        self.contexts = contexts
        self.cache_hits = cache_hits
        self.total_load_time_ms = total_load_time_ms
        self.errors = errors or []


class DummyExtraction:
    def __init__(self, entities):
        self.entities = entities


def _entity(entity_type, name, confidence=0.8):
    return ExtractedEntity(
        entity_type=entity_type,
        value=name,
        normalized=name,
        start_pos=0,
        end_pos=len(name),
        confidence=confidence,
    )


def test_privacy_filter_redacts_high_sensitivity():
    entity = _entity("person", "Alice", confidence=0.9)
    ctx = EntityContext(
        entity=entity,
        context_type="person",
        summary="password: secret",
        details={"note": "password: secret"},
        source="test",
        freshness="live",
        load_time_ms=1.0,
    )

    result = filter_entity_contexts([ctx], clearance="PUBLIC")
    assert result.contexts[0].get("redacted") is True
    assert result.redactions


def test_entity_payload_shapes():
    entity = _entity("person", "Alice", confidence=0.85)
    ctx = EntityContext(
        entity=entity,
        context_type="person",
        summary="Alice (Acme)",
        details={"org": "Acme"},
        source="knowledge_layer",
        freshness="live",
        load_time_ms=2.0,
    )

    extraction = DummyExtraction([entity])
    context_result = DummyContextResult([ctx], cache_hits=1, total_load_time_ms=8.2)

    payload = build_entity_response_payload(
        answer="Hello",
        extraction_result=extraction,
        context_result=context_result,
        clearance="INTERNAL",
    )

    assert payload is not None
    assert "compact_text_blocks" in payload
    assert "chip_labels" in payload
    assert payload["chip_labels"][0]["label"].lower() == "alice"
    assert payload["meta"]["entity_count"] == 1
