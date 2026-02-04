"""
Meilisearch Client - Keyword Search Integration

Provides fast, typo-tolerant keyword search for:
- Knowledge Items (content, subject)
- Documents (path, title)
- Chat messages (text search)

Complements Qdrant's semantic vector search.
"""
import os
from typing import Dict, List, Optional, Any
from meilisearch import Client

from .observability import get_logger, log_with_context

logger = get_logger("jarvis.meilisearch")

# Configuration from environment
MEILI_HOST = os.environ.get("MEILI_HOST", "meilisearch")
MEILI_PORT = int(os.environ.get("MEILI_PORT", "7700"))
MEILI_MASTER_KEY = os.environ.get("MEILI_MASTER_KEY", None)

# Index names
INDEX_KNOWLEDGE = "knowledge_items"
INDEX_DOCUMENTS = "documents"

# Global client instance
_client: Optional[Client] = None


def get_client() -> Client:
    """Get or create Meilisearch client instance."""
    global _client
    if _client is None:
        url = f"http://{MEILI_HOST}:{MEILI_PORT}"
        _client = Client(url, MEILI_MASTER_KEY)
        log_with_context(logger, "info", "Meilisearch client initialized", url=url)
    return _client


def health_check() -> Dict:
    """Check Meilisearch health status."""
    try:
        client = get_client()
        health = client.health()
        return {
            "status": "healthy",
            "meilisearch": health,
            "host": f"{MEILI_HOST}:{MEILI_PORT}"
        }
    except Exception as e:
        log_with_context(logger, "error", "Meilisearch health check failed", error=str(e))
        return {"status": "unhealthy", "error": str(e)}


# ============ Index Setup ============

def setup_indexes() -> Dict:
    """
    Create and configure indexes with appropriate settings.
    Call once on startup or when indexes need reconfiguration.
    """
    client = get_client()
    results = {}

    # Knowledge Items Index
    try:
        index = client.index(INDEX_KNOWLEDGE)

        # Update searchable attributes
        index.update_searchable_attributes([
            "content_text",      # Main searchable content
            "subject_id",        # Person/project name
            "item_type",         # pattern, fact, preference, etc.
            "namespace"          # For filtering
        ])

        # Update filterable attributes
        index.update_filterable_attributes([
            "namespace",
            "item_type",
            "subject_type",
            "status",
            "relevance_score"
        ])

        # Update sortable attributes
        index.update_sortable_attributes([
            "relevance_score",
            "updated_at"
        ])

        results[INDEX_KNOWLEDGE] = {"status": "configured"}
        log_with_context(logger, "info", "Knowledge index configured")

    except Exception as e:
        results[INDEX_KNOWLEDGE] = {"status": "error", "error": str(e)}
        log_with_context(logger, "error", "Failed to configure knowledge index", error=str(e))

    # Documents Index
    try:
        index = client.index(INDEX_DOCUMENTS)

        index.update_searchable_attributes([
            "title",
            "path",
            "content_preview",
            "doc_type"
        ])

        index.update_filterable_attributes([
            "namespace",
            "doc_type",
            "source"
        ])

        results[INDEX_DOCUMENTS] = {"status": "configured"}
        log_with_context(logger, "info", "Documents index configured")

    except Exception as e:
        results[INDEX_DOCUMENTS] = {"status": "error", "error": str(e)}
        log_with_context(logger, "error", "Failed to configure documents index", error=str(e))

    return results


# ============ Knowledge Items ============

def index_knowledge_item(item: Dict) -> bool:
    """
    Index a knowledge item in Meilisearch.

    Args:
        item: Knowledge item dict with id, item_type, namespace, content, etc.

    Returns:
        True if indexed successfully
    """
    try:
        client = get_client()
        index = client.index(INDEX_KNOWLEDGE)

        # Extract searchable text from content JSON
        content = item.get("content", {})
        if isinstance(content, str):
            import json
            try:
                content = json.loads(content)
            except Exception as e:
                log_with_context(logger, "error", "Failed to parse content JSON for indexing", error=str(e), item_id=item.get("id"))
                content = {"text": content}

        # Build document for Meilisearch
        doc = {
            "id": str(item["id"]),
            "item_type": item.get("item_type", ""),
            "namespace": item.get("namespace", ""),
            "subject_type": item.get("subject_type", ""),
            "subject_id": item.get("subject_id", ""),
            "status": item.get("status", "active"),
            "relevance_score": float(item.get("relevance_score", 1.0)),
            "updated_at": str(item.get("updated_at", "")),
            # Flatten content for search
            "content_text": _flatten_content(content)
        }

        index.add_documents([doc], primary_key="id")
        log_with_context(logger, "debug", "Knowledge item indexed", item_id=item["id"])
        return True

    except Exception as e:
        log_with_context(logger, "error", "Failed to index knowledge item",
                        item_id=item.get("id"), error=str(e))
        return False


def delete_knowledge_item(item_id: int) -> bool:
    """Remove a knowledge item from the index."""
    try:
        client = get_client()
        index = client.index(INDEX_KNOWLEDGE)
        index.delete_document(str(item_id))
        return True
    except Exception as e:
        log_with_context(logger, "error", "Failed to delete from index",
                        item_id=item_id, error=str(e))
        return False


def search_knowledge(
    query: str,
    namespace: str = None,
    item_type: str = None,
    limit: int = 20
) -> List[Dict]:
    """
    Search knowledge items by keyword.

    Args:
        query: Search query (typo-tolerant)
        namespace: Filter by namespace
        item_type: Filter by item type
        limit: Max results

    Returns:
        List of matching items with highlights
    """
    try:
        client = get_client()
        index = client.index(INDEX_KNOWLEDGE)

        # Build filter
        filters = []
        if namespace:
            filters.append(f'namespace = "{namespace}"')
        if item_type:
            filters.append(f'item_type = "{item_type}"')

        filter_str = " AND ".join(filters) if filters else None

        # Search
        results = index.search(
            query,
            {
                "limit": limit,
                "filter": filter_str,
                "attributesToHighlight": ["content_text"],
                "highlightPreTag": "**",
                "highlightPostTag": "**"
            }
        )

        return results.get("hits", [])

    except Exception as e:
        log_with_context(logger, "error", "Knowledge search failed",
                        query=query, error=str(e))
        return []


# ============ Documents ============

def index_document(doc: Dict) -> bool:
    """
    Index a document for keyword search.

    Args:
        doc: Dict with path, title, content_preview, namespace, doc_type
    """
    try:
        client = get_client()
        index = client.index(INDEX_DOCUMENTS)

        meili_doc = {
            "id": doc.get("id") or doc.get("path", "").replace("/", "_"),
            "path": doc.get("path", ""),
            "title": doc.get("title", ""),
            "content_preview": doc.get("content_preview", "")[:500],
            "namespace": doc.get("namespace", "shared"),
            "doc_type": doc.get("doc_type", ""),
            "source": doc.get("source", "")
        }

        index.add_documents([meili_doc], primary_key="id")
        return True

    except Exception as e:
        log_with_context(logger, "error", "Failed to index document",
                        path=doc.get("path"), error=str(e))
        return False


def search_documents(
    query: str,
    namespace: str = None,
    doc_type: str = None,
    limit: int = 20
) -> List[Dict]:
    """Search documents by keyword."""
    try:
        client = get_client()
        index = client.index(INDEX_DOCUMENTS)

        filters = []
        if namespace:
            filters.append(f'namespace = "{namespace}"')
        if doc_type:
            filters.append(f'doc_type = "{doc_type}"')

        filter_str = " AND ".join(filters) if filters else None

        results = index.search(
            query,
            {
                "limit": limit,
                "filter": filter_str,
                "attributesToHighlight": ["title", "content_preview"],
                "highlightPreTag": "**",
                "highlightPostTag": "**"
            }
        )

        return results.get("hits", [])

    except Exception as e:
        log_with_context(logger, "error", "Document search failed",
                        query=query, error=str(e))
        return []


# ============ Bulk Operations ============

def bulk_index_knowledge(items: List[Dict]) -> Dict:
    """
    Bulk index multiple knowledge items.

    Returns:
        Stats about the indexing operation
    """
    try:
        client = get_client()
        index = client.index(INDEX_KNOWLEDGE)

        docs = []
        for item in items:
            content = item.get("content", {})
            if isinstance(content, str):
                import json
                try:
                    content = json.loads(content)
                except Exception as e:
                    log_with_context(logger, "error", "Failed to parse content JSON for bulk indexing", error=str(e), item_id=item.get("id"))
                    content = {"text": content}

            docs.append({
                "id": str(item["id"]),
                "item_type": item.get("item_type", ""),
                "namespace": item.get("namespace", ""),
                "subject_type": item.get("subject_type", ""),
                "subject_id": item.get("subject_id", ""),
                "status": item.get("status", "active"),
                "relevance_score": float(item.get("relevance_score", 1.0)),
                "updated_at": str(item.get("updated_at", "")),
                "content_text": _flatten_content(content)
            })

        if docs:
            task = index.add_documents(docs, primary_key="id")
            log_with_context(logger, "info", "Bulk indexed knowledge items",
                           count=len(docs), task_uid=task.task_uid)
            return {"indexed": len(docs), "task_uid": task.task_uid}

        return {"indexed": 0}

    except Exception as e:
        log_with_context(logger, "error", "Bulk indexing failed", error=str(e))
        return {"indexed": 0, "error": str(e)}


def get_index_stats() -> Dict:
    """Get stats for all indexes."""
    try:
        client = get_client()
        stats = {}

        for index_name in [INDEX_KNOWLEDGE, INDEX_DOCUMENTS]:
            try:
                index = client.index(index_name)
                index_stats = index.get_stats()
                stats[index_name] = {
                    "numberOfDocuments": index_stats.number_of_documents,
                    "isIndexing": index_stats.is_indexing
                }
            except Exception as e:
                stats[index_name] = {"error": str(e)}

        return stats

    except Exception as e:
        return {"error": str(e)}


# ============ Helpers ============

def _flatten_content(content: Dict) -> str:
    """
    Flatten a content dict into searchable text.
    Handles nested structures.
    """
    if isinstance(content, str):
        return content

    parts = []

    for key, value in content.items():
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    parts.append(_flatten_content(item))
        elif isinstance(value, dict):
            parts.append(_flatten_content(value))

    return " ".join(parts)
