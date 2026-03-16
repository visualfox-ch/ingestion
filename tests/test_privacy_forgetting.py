import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_delete_fact():
    # Add a fact
    resp = client.post("/memory/facts", params={"fact": "test fact", "category": "testcat"})
    assert resp.status_code == 200
    fact_id = resp.json()["fact_id"]
    # Delete the fact
    del_resp = client.delete(f"/memory/facts/{fact_id}")
    assert del_resp.status_code == 200
    assert del_resp.json()["deleted"] is True


def test_bulk_delete_facts():
    # Add two facts in a category
    for i in range(2):
        client.post("/memory/facts", params={"fact": f"bulk fact {i}", "category": "bulkcat"})
    # Bulk delete by category
    del_resp = client.delete("/memory/facts", params={"category": "bulkcat"})
    assert del_resp.status_code == 200
    assert del_resp.json()["deleted"] >= 2


def test_delete_entity():
    # Add an entity
    from app import memory_store
    entity_id = memory_store.add_entity("Test Entity", "testtype")
    # Delete the entity
    del_resp = client.delete(f"/memory/entities/{entity_id}")
    assert del_resp.status_code == 200
    assert del_resp.json()["deleted"] is True


def test_bulk_delete_entities():
    # Add two entities of a type
    from app import memory_store
    for i in range(2):
        memory_store.add_entity(f"Bulk Entity {i}", "bulktype")
    # Bulk delete by type
    del_resp = client.delete("/memory/entities", params={"entity_type": "bulktype"})
    assert del_resp.status_code == 200
    assert del_resp.json()["deleted"] >= 2
