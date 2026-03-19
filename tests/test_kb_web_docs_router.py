import httpx
import pytest
from fastapi import FastAPI

from app.routers import kb_router


def _build_client():
    app = FastAPI()
    app.include_router(kb_router.router)
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


@pytest.mark.asyncio
async def test_kb_web_docs_snapshot_rejects_non_brain_output_path():
    async with _build_client() as client:
        response = await client.post(
            "/kb/web-docs/snapshot",
            json={
                "domain": "web_docs",
                "subdomain": "scrapling_docs",
                "start_urls": ["https://scrapling.readthedocs.io/en/latest/Introduction/index.html"],
                "allowed_domains": ["scrapling.readthedocs.io"],
                "output_path": "/tmp/not-allowed",
            },
        )

    assert response.status_code == 400
    assert "output_path must start with /brain/" in response.json()["detail"]


@pytest.mark.asyncio
async def test_kb_web_docs_snapshot_runs_registers_and_ingests(monkeypatch):

    snapshot_result = {
        "status": "completed",
        "backend": "requests",
        "count": 1,
        "output_path": "/brain/knowledge/web/scrapling",
        "files": [
            {
                "url": "https://scrapling.readthedocs.io/en/latest/Introduction/index.html",
                "title": "Scrapling Introduction",
                "file_path": "/brain/knowledge/web/scrapling/index-html.md",
                "content_type": "text/html",
            }
        ],
        "domain": "web_docs",
        "subdomain": "scrapling_docs",
    }

    add_source_calls = []

    def fake_run(config, fetcher=None):
        assert config.domain == "web_docs"
        return snapshot_result

    def fake_add_source(**kwargs):
        add_source_calls.append(kwargs)
        return {"success": True, "id": "source-1"}

    async def fake_ingest_domain(domain: str):
        assert domain == "web_docs"
        return [{"status": "ingested", "title": "Scrapling Introduction", "chunks_created": 3}]

    monkeypatch.setattr(kb_router, "run_web_docs_snapshot", fake_run)
    monkeypatch.setattr(kb_router, "add_knowledge_source", fake_add_source)
    monkeypatch.setattr(kb_router, "ingest_domain", fake_ingest_domain)

    async with _build_client() as client:
        response = await client.post(
            "/kb/web-docs/snapshot",
            json={
                "domain": "web_docs",
                "subdomain": "scrapling_docs",
                "start_urls": ["https://scrapling.readthedocs.io/en/latest/Introduction/index.html"],
                "allowed_domains": ["scrapling.readthedocs.io"],
                "output_path": "/brain/knowledge/web/scrapling",
                "auto_register": True,
                "auto_ingest": True,
                "owner": "michael_bohl",
                "channel": "docs",
                "language": "en",
                "quality": "high",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["snapshot"]["backend"] == "requests"
    assert payload["registered_sources"] == 1
    assert payload["ingest_results"][0]["status"] == "ingested"
    assert add_source_calls[0]["domain"] == "web_docs"
    assert add_source_calls[0]["subdomain"] == "scrapling_docs"
    assert add_source_calls[0]["file_path"] == "/brain/knowledge/web/scrapling/index-html.md"
