"""
API-Endpoints für LinkedIn & visualfox Knowledge Base
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from ..services.linkedin_ingestion import (
    ingest_all_linkedin_documents,
    ingest_all_visualfox_documents,
    ingest_all_knowledge_bases,
    get_qdrant_client,
    ensure_collection,
    LINKEDIN_DOCS_CONFIG,
    VISUALFOX_DOCS_CONFIG,
    QDRANT_COLLECTION,
    QDRANT_COLLECTION_VISUALFOX
)
# Phase 2A: Use unified knowledge_retrieval (backward-compat wrappers)
from ..services.knowledge_retrieval import (
    retrieve_linkedin_knowledge,
    retrieve_visualfox_knowledge
)
from ..postgres_state import get_cursor


router = APIRouter(prefix="/linkedin", tags=["LinkedIn Knowledge"])
visualfox_router = APIRouter(prefix="/visualfox", tags=["visualfox Knowledge"])
knowledge_router = APIRouter(prefix="/knowledge", tags=["Knowledge Base"])


class SearchRequest(BaseModel):
    query: str
    subdomain: Optional[str] = None
    top_k: int = 8


class IngestResponse(BaseModel):
    status: str
    documents: list


class SearchResponse(BaseModel):
    found: bool
    count: int
    results: list


@router.post("/ingest", response_model=IngestResponse)
async def ingest_linkedin_docs():
    """Importiert/aktualisiert alle LinkedIn-Dokumente."""
    try:
        results = await ingest_all_linkedin_documents()
        return IngestResponse(
            status="completed",
            documents=results
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/search", response_model=SearchResponse)
async def search_linkedin_knowledge(request: SearchRequest):
    """Durchsucht die LinkedIn-Wissensbasis."""
    try:
        results = retrieve_linkedin_knowledge(
            query=request.query,
            top_k=request.top_k,
            subdomain=request.subdomain
        )

        return SearchResponse(
            found=len(results) > 0,
            count=len(results),
            results=[
                {
                    "text": r["text"][:1000],
                    "score": round(r["score"], 3),
                    "section": r["metadata"].get("chunk_title", ""),
                    "subdomain": r["metadata"].get("subdomain", "")
                }
                for r in results
            ]
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_linkedin_stats():
    """Statistiken zur LinkedIn Knowledge Base."""
    try:
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT title, version, subdomain, created_at, updated_at,
                       LENGTH(content) as content_length
                FROM documents
                WHERE domain = 'linkedin_strategy'
                ORDER BY updated_at DESC
                """
            )
            docs = cur.fetchall()

        qdrant = get_qdrant_client()
        try:
            collection_info = qdrant.get_collection(collection_name=QDRANT_COLLECTION)
            chunk_count = collection_info.points_count
        except Exception:
            chunk_count = 0

        return {
            "documents": [
                {
                    "title": d["title"],
                    "version": d["version"],
                    "subdomain": d["subdomain"],
                    "content_length": d["content_length"],
                    "updated_at": d["updated_at"].isoformat() if d["updated_at"] else None
                }
                for d in docs
            ],
            "total_chunks": chunk_count,
            "collection": QDRANT_COLLECTION
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/config")
async def get_linkedin_config():
    """Zeigt die aktuelle Konfiguration."""
    return {
        "documents": [
            {
                "title": doc["title"],
                "subdomain": doc["subdomain"],
                "version": doc["version"],
                "file_path": doc["file_path"]
            }
            for doc in LINKEDIN_DOCS_CONFIG
        ],
        "collection": QDRANT_COLLECTION
    }


# ============================================================================
# visualfox Endpoints
# ============================================================================

@visualfox_router.post("/ingest")
async def ingest_visualfox_docs():
    """Importiert/aktualisiert alle visualfox-Dokumente."""
    try:
        results = await ingest_all_visualfox_documents()
        return {
            "status": "completed",
            "documents": results
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@visualfox_router.post("/search")
async def search_visualfox_knowledge(request: SearchRequest):
    """Durchsucht die visualfox-Wissensbasis."""
    try:
        results = retrieve_visualfox_knowledge(
            query=request.query,
            top_k=request.top_k,
            subdomain=request.subdomain
        )

        return SearchResponse(
            found=len(results) > 0,
            count=len(results),
            results=[
                {
                    "text": r["text"][:1000],
                    "score": round(r["score"], 3),
                    "section": r["metadata"].get("chunk_title", ""),
                    "subdomain": r["metadata"].get("subdomain", "")
                }
                for r in results
            ]
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@visualfox_router.get("/config")
async def get_visualfox_config():
    """Zeigt die aktuelle visualfox Konfiguration."""
    return {
        "documents": [
            {
                "title": doc["title"],
                "subdomain": doc["subdomain"],
                "version": doc["version"],
                "file_path": doc["file_path"]
            }
            for doc in VISUALFOX_DOCS_CONFIG
        ],
        "collection": QDRANT_COLLECTION_VISUALFOX
    }


# ============================================================================
# Combined Knowledge Base Endpoint
# ============================================================================

@knowledge_router.post("/ingest-all")
async def ingest_all_knowledge():
    """Importiert alle Knowledge Bases (LinkedIn + visualfox)."""
    try:
        results = await ingest_all_knowledge_bases()
        return {
            "status": "completed",
            "results": results
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
