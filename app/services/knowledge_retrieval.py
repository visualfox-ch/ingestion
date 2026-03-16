"""
Knowledge Retrieval Service - Unified Search

Sucht über alle Knowledge Bases hinweg oder gefiltert nach Domain.
Verwendet die Collections aus knowledge_sources Tabelle.
"""

from typing import Optional, List
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue

from ..embed import embed_texts
from ..observability import get_logger
from .knowledge_sources import get_all_domains, get_active_sources

logger = get_logger("jarvis.knowledge_retrieval")

QDRANT_HOST = "qdrant"
QDRANT_PORT = 6333


def get_qdrant_client() -> QdrantClient:
    return QdrantClient(url=f"http://{QDRANT_HOST}:{QDRANT_PORT}")


def get_collections_for_domain(domain: Optional[str] = None) -> List[str]:
    """
    Ermittelt die Qdrant Collections für eine Domain.
    Wenn domain=None, gibt alle aktiven Collections zurück.
    """
    if domain:
        sources = get_active_sources(domain)
        # Unique collections for this domain
        collections = list(set(s.collection_name for s in sources))
        return collections if collections else [f"jarvis_{domain}"]
    else:
        # All domains, all collections
        all_domains = get_all_domains()
        collections = set()
        for d in all_domains:
            sources = get_active_sources(d)
            for s in sources:
                collections.add(s.collection_name)
        return list(collections)


def search_knowledge(
    query: str,
    domain: Optional[str] = None,
    subdomain: Optional[str] = None,
    top_k: int = 10,
    min_score: float = 0.5
) -> List[dict]:
    """
    Unified search across knowledge bases.

    Args:
        query: Search query
        domain: Optional domain filter (e.g. "linkedin", "visualfox")
        subdomain: Optional subdomain filter (e.g. "strategy", "brand")
        top_k: Number of results per collection
        min_score: Minimum similarity score

    Returns:
        List of {text, score, metadata} sorted by score
    """
    client = get_qdrant_client()

    # Get query embedding
    embeddings = embed_texts([query])
    query_vector = embeddings[0]

    # Determine which collections to search
    collections = get_collections_for_domain(domain)

    if not collections:
        logger.warning(f"No collections found for domain: {domain}")
        return []

    all_results = []

    for collection_name in collections:
        try:
            # Build filter
            must_conditions = []

            if domain:
                must_conditions.append(
                    FieldCondition(key="domain", match=MatchValue(value=domain))
                )

            if subdomain:
                must_conditions.append(
                    FieldCondition(key="subdomain", match=MatchValue(value=subdomain))
                )

            search_filter = Filter(must=must_conditions) if must_conditions else None

            # Search
            result = client.query_points(
                collection_name=collection_name,
                query=query_vector,
                query_filter=search_filter,
                limit=top_k,
                score_threshold=min_score
            )

            for hit in result.points:
                all_results.append({
                    "text": hit.payload.get("text", ""),
                    "score": hit.score,
                    "metadata": {
                        k: v for k, v in hit.payload.items() if k != "text"
                    },
                    "collection": collection_name
                })

        except Exception as e:
            logger.warning(f"Search failed for collection {collection_name}: {e}")
            continue

    # Sort by score and take top_k overall
    all_results.sort(key=lambda x: x["score"], reverse=True)
    return all_results[:top_k]


def search_by_collection(
    query: str,
    collection_name: str,
    top_k: int = 10,
    min_score: float = 0.5,
    filter_conditions: Optional[List[dict]] = None
) -> List[dict]:
    """
    Direct search in a specific collection.
    """
    client = get_qdrant_client()

    embeddings = embed_texts([query])
    query_vector = embeddings[0]

    must_conditions = []
    if filter_conditions:
        for cond in filter_conditions:
            must_conditions.append(
                FieldCondition(key=cond["key"], match=MatchValue(value=cond["value"]))
            )

    search_filter = Filter(must=must_conditions) if must_conditions else None

    try:
        result = client.query_points(
            collection_name=collection_name,
            query=query_vector,
            query_filter=search_filter,
            limit=top_k,
            score_threshold=min_score
        )

        return [
            {
                "text": hit.payload.get("text", ""),
                "score": hit.score,
                "metadata": {
                    k: v for k, v in hit.payload.items() if k != "text"
                }
            }
            for hit in result.points
        ]

    except Exception as e:
        logger.error(f"Search failed: {e}")
        return []


# ============================================================================
# BACKWARD COMPATIBILITY - Legacy LinkedIn/visualfox wrappers
# Phase 2A: These wrap the unified search_knowledge() function
# TODO: Remove after migration to search_knowledge() is complete
# ============================================================================

def retrieve_linkedin_knowledge(
    query: str,
    top_k: int = 10,
    subdomain: str = None
) -> List[dict]:
    """
    DEPRECATED: Use search_knowledge(query, domain='linkedin_strategy') instead.

    Backward-compatible wrapper for legacy LinkedIn knowledge search.
    """
    logger.debug("retrieve_linkedin_knowledge called (legacy wrapper)")
    return search_knowledge(
        query=query,
        domain="linkedin_strategy",
        subdomain=subdomain,
        top_k=top_k,
        min_score=0.5
    )


def retrieve_visualfox_knowledge(
    query: str,
    top_k: int = 10,
    subdomain: str = None
) -> List[dict]:
    """
    DEPRECATED: Use search_knowledge(query, domain='visualfox_brand') instead.

    Backward-compatible wrapper for legacy visualfox knowledge search.
    """
    logger.debug("retrieve_visualfox_knowledge called (legacy wrapper)")
    return search_knowledge(
        query=query,
        domain="visualfox_brand",
        subdomain=subdomain,
        top_k=top_k,
        min_score=0.5
    )


# Tool schemas for backward compatibility
LINKEDIN_KNOWLEDGE_TOOL_SCHEMA = {
    "name": "search_linkedin_knowledge",
    "description": "Durchsucht die LinkedIn-Wissensbasis nach Strategie, Profil-Texten und Best Practices.",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Suchanfrage"
            },
            "subdomain": {
                "type": "string",
                "description": "Optional: Subdomain filter (z.B. 'profil', 'content')"
            },
            "top_k": {
                "type": "integer",
                "description": "Anzahl der Ergebnisse",
                "default": 8
            }
        },
        "required": ["query"]
    }
}

VISUALFOX_KNOWLEDGE_TOOL_SCHEMA = {
    "name": "search_visualfox_knowledge",
    "description": "Durchsucht die visualfox-Wissensbasis nach Brand Guidelines und Kommunikationsregeln.",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Suchanfrage"
            },
            "subdomain": {
                "type": "string",
                "description": "Optional: Subdomain filter (z.B. 'brand', 'voice')"
            },
            "top_k": {
                "type": "integer",
                "description": "Anzahl der Ergebnisse",
                "default": 8
            }
        },
        "required": ["query"]
    }
}


def handle_search_linkedin_knowledge(
    query: str,
    subdomain: str = None,
    top_k: int = 8,
    **kwargs
) -> dict:
    """Tool handler for LinkedIn knowledge search."""
    results = retrieve_linkedin_knowledge(query, top_k, subdomain)
    return {
        "found": len(results) > 0,
        "count": len(results),
        "results": [
            {
                "text": r["text"][:1000],
                "score": round(r["score"], 3),
                "section": r["metadata"].get("chunk_title", ""),
                "subdomain": r["metadata"].get("subdomain", "")
            }
            for r in results
        ]
    }


def handle_search_visualfox_knowledge(
    query: str,
    subdomain: str = None,
    top_k: int = 8,
    **kwargs
) -> dict:
    """Tool handler for visualfox knowledge search."""
    results = retrieve_visualfox_knowledge(query, top_k, subdomain)
    return {
        "found": len(results) > 0,
        "count": len(results),
        "results": [
            {
                "text": r["text"][:1000],
                "score": round(r["score"], 3),
                "section": r["metadata"].get("chunk_title", ""),
                "subdomain": r["metadata"].get("subdomain", "")
            }
            for r in results
        ]
    }
