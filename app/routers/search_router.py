"""
Search Router

Extracted from main.py - Search endpoints:
- Keyword search (Meilisearch)
- Document search
- Meilisearch setup/stats/sync
- Hybrid search (semantic + keyword)
"""

from fastapi import APIRouter

from ..observability import get_logger

logger = get_logger("jarvis.search")
router = APIRouter(prefix="/search", tags=["search"])


# =============================================================================
# MEILISEARCH KEYWORD SEARCH
# =============================================================================

@router.get("/keyword")
def search_keyword(
    query: str,
    namespace: str = None,
    item_type: str = None,
    limit: int = 20
):
    """
    Keyword search for knowledge items using Meilisearch.
    Typo-tolerant, fast, complements semantic search.

    Args:
        query: Search query
        namespace: Filter by namespace (private, work_projektil, etc.)
        item_type: Filter by item type (pattern, fact, preference, etc.)
        limit: Max results (default 20)
    """
    from .. import meilisearch_client
    results = meilisearch_client.search_knowledge(
        query=query,
        namespace=namespace,
        item_type=item_type,
        limit=limit
    )
    return {
        "query": query,
        "count": len(results),
        "results": results
    }


@router.get("/documents")
def search_documents(
    query: str,
    namespace: str = None,
    doc_type: str = None,
    limit: int = 20
):
    """
    Keyword search for documents using Meilisearch.
    Find documents by title, path, or content preview.
    """
    from .. import meilisearch_client
    results = meilisearch_client.search_documents(
        query=query,
        namespace=namespace,
        doc_type=doc_type,
        limit=limit
    )
    return {
        "query": query,
        "count": len(results),
        "results": results
    }


# =============================================================================
# MEILISEARCH MANAGEMENT
# =============================================================================

@router.post("/meilisearch/setup")
def setup_meilisearch():
    """
    Initialize Meilisearch indexes with proper configuration.
    Run once on first setup or when reconfiguring.
    """
    from .. import meilisearch_client
    result = meilisearch_client.setup_indexes()
    return {"status": "configured", "indexes": result}


@router.get("/meilisearch/stats")
def meilisearch_stats():
    """Get Meilisearch index statistics."""
    from .. import meilisearch_client
    return meilisearch_client.get_index_stats()


@router.post("/meilisearch/sync")
def sync_knowledge_to_meilisearch():
    """
    Bulk sync all knowledge items to Meilisearch.
    Run once for initial sync or after data recovery.
    """
    from .. import meilisearch_client
    from .. import knowledge_store

    # Get all active knowledge items
    items = knowledge_store.get_knowledge_items(
        status="active",
        min_relevance=0.0,
        limit=10000
    )

    result = meilisearch_client.bulk_index_knowledge(items)
    return {
        "status": "synced",
        "items_found": len(items),
        "indexed": result.get("indexed", 0),
        "task_uid": result.get("task_uid")
    }


# =============================================================================
# HYBRID SEARCH
# =============================================================================

@router.get("/hybrid")
def search_hybrid(
    query: str,
    namespace: str = None,
    limit: int = 20,
    semantic_weight: float = 0.5,
    keyword_weight: float = 0.5
):
    """
    Hybrid search combining semantic (Qdrant) and keyword (Meilisearch).

    Uses Reciprocal Rank Fusion (RRF) to merge results from both systems.

    Args:
        query: Search query
        namespace: Filter by namespace
        limit: Max results (default 20)
        semantic_weight: Weight for semantic search (0.0-1.0, default 0.5)
        keyword_weight: Weight for keyword search (0.0-1.0, default 0.5)

    Returns:
        Fused results with source info (semantic, keyword, or both)
    """
    from .. import hybrid_search

    results = hybrid_search.hybrid_search_simple(
        query=query,
        namespace=namespace,
        limit=limit
    )

    # Count sources
    both = sum(1 for r in results if r.get("source") == "both")
    semantic_only = sum(1 for r in results if r.get("source") == "semantic")
    keyword_only = sum(1 for r in results if r.get("source") == "keyword")

    return {
        "query": query,
        "count": len(results),
        "sources": {
            "both": both,
            "semantic_only": semantic_only,
            "keyword_only": keyword_only
        },
        "results": results
    }
