from __future__ import annotations

import uuid

import pytest

from app.services import knowledge_ingestion
from app.services.knowledge_sources import KnowledgeSource


def _source(title: str, version: str, file_path: str, subdomain: str = "fastapi_docs") -> KnowledgeSource:
    return KnowledgeSource(
        id=uuid.uuid4(),
        domain="web_docs",
        subdomain=subdomain,
        file_path=file_path,
        title=title,
        version=version,
        collection_name="jarvis_web_docs",
        owner="michael_bohl",
        channel="docs",
        language="en",
        quality="high",
        active=True,
        auto_reingest=True,
        last_ingested_at=None,
        last_chunk_count=None,
    )


@pytest.mark.asyncio
async def test_ingest_domain_skips_duplicate_title_version_in_same_run(monkeypatch):
    sources = [
        _source("FastAPI", "2026-03-20", "/brain/data/web_docs/fastapi/index.md"),
        _source("FastAPI", "2026-03-20", "/brain/data/web_docs/fastapi/tutorial.md"),
        _source("Advanced User Guide - FastAPI", "2026-03-20", "/brain/data/web_docs/fastapi/advanced.md"),
    ]

    monkeypatch.setattr(knowledge_ingestion, "get_active_sources", lambda domain: sources)
    monkeypatch.setattr(knowledge_ingestion, "get_qdrant_client", lambda: object())

    seen_titles: list[str] = []

    def fake_ingest(_qdrant, source):
        seen_titles.append(source.title)
        return {"status": "ingested", "title": source.title}

    monkeypatch.setattr(knowledge_ingestion, "ingest_knowledge_source", fake_ingest)

    results = await knowledge_ingestion.ingest_domain("web_docs")

    assert [r["status"] for r in results] == ["ingested", "skipped", "ingested"]
    assert seen_titles == ["FastAPI", "Advanced User Guide - FastAPI"]


@pytest.mark.asyncio
async def test_ingest_all_domains_applies_duplicate_guard_per_domain(monkeypatch):
    sources = [
        _source("Telegram APIs", "2026-03-20", "/brain/data/web_docs/telegram/a.md", subdomain="telegram_bot_api"),
        _source("Telegram APIs", "2026-03-20", "/brain/data/web_docs/telegram/b.md", subdomain="telegram_bot_api"),
    ]

    monkeypatch.setattr(knowledge_ingestion, "get_all_domains", lambda: ["web_docs"])
    monkeypatch.setattr(knowledge_ingestion, "get_active_sources", lambda domain: sources)
    monkeypatch.setattr(knowledge_ingestion, "get_qdrant_client", lambda: object())
    monkeypatch.setattr(
        knowledge_ingestion,
        "ingest_knowledge_source",
        lambda _qdrant, source: {"status": "ingested", "title": source.title},
    )

    results = await knowledge_ingestion.ingest_all_domains()

    assert "web_docs" in results
    assert [r["status"] for r in results["web_docs"]] == ["ingested", "skipped"]
