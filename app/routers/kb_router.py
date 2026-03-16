"""
Knowledge Base Router - DB-gesteuerte Dokument-Ingestion

Prefix: /kb (um Konflikt mit /knowledge zu vermeiden)
Ersetzt hardcoded linkedin/visualfox Config mit DB-gesteuerter Verwaltung.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List

from ..services.knowledge_sources import (
    list_knowledge_sources,
    add_knowledge_source,
    remove_knowledge_source,
    bump_version,
    get_all_domains
)
from ..services.knowledge_ingestion import (
    ingest_domain,
    ingest_all_domains
)
from ..services.knowledge_retrieval import search_knowledge


router = APIRouter(prefix="/kb", tags=["Knowledge Base (Documents)"])


# ============================================================================
# Request/Response Models
# ============================================================================

class AddSourceRequest(BaseModel):
    domain: str
    file_path: str
    title: str
    subdomain: Optional[str] = None
    version: str = "1.0"
    collection_name: Optional[str] = None
    owner: str = "michael_bohl"
    channel: Optional[str] = None
    language: str = "de"
    quality: str = "high"
    auto_reingest: bool = False


class SearchRequest(BaseModel):
    query: str
    domain: Optional[str] = None
    subdomain: Optional[str] = None
    top_k: int = 8


class IngestRequest(BaseModel):
    domain: Optional[str] = None


# ============================================================================
# Source Management Endpoints
# ============================================================================

@router.get("/sources")
async def get_sources(domain: Optional[str] = None, include_inactive: bool = False):
    """Listet alle Knowledge Sources."""
    sources = list_knowledge_sources(domain, include_inactive)
    return {
        "count": len(sources),
        "sources": sources
    }


@router.post("/sources")
async def add_source(request: AddSourceRequest):
    """Fügt eine neue Knowledge Source hinzu."""
    result = add_knowledge_source(
        domain=request.domain,
        file_path=request.file_path,
        title=request.title,
        subdomain=request.subdomain,
        version=request.version,
        collection_name=request.collection_name,
        owner=request.owner,
        channel=request.channel,
        language=request.language,
        quality=request.quality,
        auto_reingest=request.auto_reingest
    )

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))

    return result


@router.delete("/sources/{source_id}")
async def delete_source(source_id: str, hard_delete: bool = False):
    """Entfernt eine Knowledge Source."""
    result = remove_knowledge_source(
        domain="",
        source_id=source_id,
        hard_delete=hard_delete
    )

    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("error"))

    return result


@router.post("/sources/{source_id}/bump-version")
async def bump_source_version(source_id: str, version: Optional[str] = None):
    """Erhöht die Version einer Source (triggert Re-Indexing)."""
    result = bump_version(source_id, version)

    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("error"))

    return result


@router.get("/domains")
async def get_domains():
    """Listet alle aktiven Domains."""
    domains = get_all_domains()
    return {"domains": domains}


# ============================================================================
# Ingestion Endpoints
# ============================================================================

@router.post("/ingest")
async def ingest_all():
    """Ingestet alle aktiven Knowledge Sources."""
    try:
        results = await ingest_all_domains()
        total_chunks = 0
        total_docs = 0

        for domain_name, domain_results in results.items():
            for r in domain_results:
                if r.get("status") == "ingested":
                    total_chunks += r.get("chunks_created", 0)
                    total_docs += 1

        return {
            "status": "completed",
            "results": results,
            "summary": {
                "domains": len(results),
                "documents_ingested": total_docs,
                "total_chunks": total_chunks
            }
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ingest/{domain}")
async def ingest_single_domain(domain: str):
    """Ingestet alle Sources einer Domain."""
    try:
        results = await ingest_domain(domain)
        total_chunks = sum(
            r.get("chunks_created", 0)
            for r in results
            if r.get("status") == "ingested"
        )

        return {
            "status": "completed",
            "domain": domain,
            "results": results,
            "summary": {
                "documents": len(results),
                "chunks_created": total_chunks
            }
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Search Endpoints
# ============================================================================

@router.post("/search")
async def search(request: SearchRequest):
    """Durchsucht die Knowledge Base."""
    try:
        results = search_knowledge(
            query=request.query,
            domain=request.domain,
            subdomain=request.subdomain,
            top_k=request.top_k
        )

        return {
            "found": len(results) > 0,
            "count": len(results),
            "results": [
                {
                    "text": r["text"][:1000],
                    "score": round(r["score"], 3),
                    "section": r["metadata"].get("chunk_title", ""),
                    "domain": r["metadata"].get("domain", ""),
                    "subdomain": r["metadata"].get("subdomain", "")
                }
                for r in results
            ]
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/search/{domain}")
async def search_domain(domain: str, q: str, top_k: int = 8):
    """Quick search in einer Domain."""
    try:
        results = search_knowledge(
            query=q,
            domain=domain,
            top_k=top_k
        )

        return {
            "found": len(results) > 0,
            "count": len(results),
            "results": [
                {
                    "text": r["text"][:1000],
                    "score": round(r["score"], 3),
                    "section": r["metadata"].get("chunk_title", "")
                }
                for r in results
            ]
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Stats Endpoint
# ============================================================================

@router.get("/stats")
async def get_stats():
    """Statistiken über alle Knowledge Bases."""
    from ..services.knowledge_ingestion import get_qdrant_client

    sources = list_knowledge_sources(include_inactive=False)
    domains = get_all_domains()

    by_domain = {}
    for s in sources:
        d = s["domain"]
        if d not in by_domain:
            by_domain[d] = {"documents": 0, "chunks": 0, "collection": s["collection"]}
        by_domain[d]["documents"] += 1
        by_domain[d]["chunks"] += s.get("chunks") or 0

    try:
        qdrant = get_qdrant_client()
        for domain_name, stats in by_domain.items():
            try:
                collection_info = qdrant.get_collection(stats["collection"])
                stats["qdrant_points"] = collection_info.points_count
            except Exception:
                stats["qdrant_points"] = None
    except Exception:
        pass

    return {
        "domains": domains,
        "total_sources": len(sources),
        "by_domain": by_domain
    }
