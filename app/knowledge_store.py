"""
Knowledge Store - CRUD + Versioning for Knowledge Items

Handles mutable knowledge with:
- Versioned content (never delete, always version)
- Relevance scoring for memory hygiene
- HITL-safe propose/approve workflow
"""
import json
import uuid
from typing import Dict, List, Optional, Any
from datetime import datetime

from .knowledge_db import get_conn
from .observability import get_logger, log_with_context

logger = get_logger("jarvis.knowledge_store")


# ============ Meilisearch Sync Helper ============

def _sync_to_meilisearch(item: Dict) -> None:
    """
    Sync a knowledge item to Meilisearch for keyword search.
    Non-blocking - failures are logged but don't affect the main operation.
    """
    try:
        from . import meilisearch_client
        meilisearch_client.index_knowledge_item(item)
    except ImportError:
        pass  # Meilisearch not available
    except Exception as e:
        log_with_context(logger, "warning", "Meilisearch sync failed",
                        item_id=item.get("id"), error=str(e))


# ============ Knowledge Item Types ============

ITEM_TYPES = {
    "pattern": "Observed behavioral pattern",
    "fact": "Verified factual information",
    "preference": "User or person preference",
    "relationship_note": "Note about a relationship dynamic",
    "context": "Contextual information (time-bound)",
    "insight": "Derived insight from evidence"
}

VALID_NAMESPACES = ["private", "work_projektil", "work_visualfox", "shared"]
VALID_STATUSES = ["active", "archived", "disputed"]
VALID_CONFIDENCE = ["low", "medium", "high"]


# ============ CRUD Operations ============

def create_knowledge_item(
    item_type: str,
    namespace: str,
    content: Dict[str, Any],
    subject_type: str = None,
    subject_id: str = None,
    confidence: str = "medium",
    evidence_refs: List[Dict] = None,
    created_by: str = "system",
    change_reason: str = None
) -> Optional[Dict]:
    """
    Create a new knowledge item with initial version.

    Args:
        item_type: pattern, fact, preference, relationship_note, context, insight
        namespace: private, work_projektil, work_visualfox, shared
        content: JSONB content of the knowledge
        subject_type: person, org, project, self
        subject_id: ID of the subject
        confidence: low, medium, high
        evidence_refs: List of evidence references
        created_by: Who created this
        change_reason: Why this was created

    Returns:
        Created knowledge item with version info
    """
    if item_type not in ITEM_TYPES:
        log_with_context(logger, "warning", "Invalid item_type", item_type=item_type)
        return None

    if namespace not in VALID_NAMESPACES:
        log_with_context(logger, "warning", "Invalid namespace", namespace=namespace)
        return None

    if confidence not in VALID_CONFIDENCE:
        confidence = "medium"

    try:
        with get_conn() as conn:
            cur = conn.cursor()

            # Create the knowledge item
            cur.execute("""
                INSERT INTO knowledge_item
                (item_type, namespace, subject_type, subject_id, status, relevance_score)
                VALUES (%s, %s, %s, %s, 'active', 1.0)
                RETURNING id
            """, (item_type, namespace, subject_type, subject_id))

            item_id = cur.fetchone()["id"]

            # Create initial version
            cur.execute("""
                INSERT INTO knowledge_item_version
                (item_id, version_number, content, confidence, evidence_refs, created_by, change_reason)
                VALUES (%s, 1, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                item_id,
                json.dumps(content),
                confidence,
                json.dumps(evidence_refs) if evidence_refs else None,
                created_by,
                change_reason
            ))

            version_id = cur.fetchone()["id"]

            # Update item with current version
            cur.execute("""
                UPDATE knowledge_item
                SET current_version_id = %s, updated_at = NOW()
                WHERE id = %s
            """, (version_id, item_id))

            log_with_context(logger, "info", "Knowledge item created",
                           item_id=item_id, item_type=item_type, namespace=namespace)

            item = get_knowledge_item(item_id)

            # Sync to Meilisearch for keyword search
            if item:
                _sync_to_meilisearch(item)

            return item

    except Exception as e:
        log_with_context(logger, "error", "Failed to create knowledge item", error=str(e))
        return None


def get_knowledge_item(item_id: int) -> Optional[Dict]:
    """Get a knowledge item with its current version"""
    try:
        with get_conn() as conn:
            cur = conn.cursor()

            cur.execute("""
                SELECT ki.*,
                       kiv.version_number, kiv.content, kiv.confidence,
                       kiv.evidence_refs, kiv.created_by as version_created_by,
                       kiv.created_at as version_created_at, kiv.change_reason
                FROM knowledge_item ki
                LEFT JOIN knowledge_item_version kiv ON ki.current_version_id = kiv.id
                WHERE ki.id = %s
            """, (item_id,))

            row = cur.fetchone()
            if not row:
                return None

            return dict(row)

    except Exception as e:
        log_with_context(logger, "error", "Failed to get knowledge item",
                        item_id=item_id, error=str(e))
        return None


def get_knowledge_items(
    namespace: str = None,
    item_type: str = None,
    subject_type: str = None,
    subject_id: str = None,
    status: str = "active",
    min_relevance: float = 0.0,
    limit: int = 50
) -> List[Dict]:
    """
    Query knowledge items with filters.

    Args:
        namespace: Filter by namespace
        item_type: Filter by type
        subject_type: Filter by subject type
        subject_id: Filter by subject ID
        status: Filter by status (default: active)
        min_relevance: Minimum relevance score
        limit: Max results

    Returns:
        List of knowledge items
    """
    try:
        with get_conn() as conn:
            cur = conn.cursor()

            conditions = ["ki.relevance_score >= %s"]
            params = [min_relevance]

            if namespace:
                conditions.append("ki.namespace = %s")
                params.append(namespace)

            if item_type:
                conditions.append("ki.item_type = %s")
                params.append(item_type)

            if subject_type:
                conditions.append("ki.subject_type = %s")
                params.append(subject_type)

            if subject_id:
                conditions.append("ki.subject_id = %s")
                params.append(subject_id)

            if status:
                conditions.append("ki.status = %s")
                params.append(status)

            params.append(limit)

            cur.execute(f"""
                SELECT ki.*,
                       kiv.version_number, kiv.content, kiv.confidence,
                       kiv.evidence_refs, kiv.created_by as version_created_by
                FROM knowledge_item ki
                LEFT JOIN knowledge_item_version kiv ON ki.current_version_id = kiv.id
                WHERE {" AND ".join(conditions)}
                ORDER BY ki.relevance_score DESC, ki.last_seen_at DESC
                LIMIT %s
            """, params)

            return [dict(row) for row in cur.fetchall()]

    except Exception as e:
        log_with_context(logger, "error", "Failed to query knowledge items", error=str(e))
        return []


def update_knowledge_item(
    item_id: int,
    content: Dict[str, Any],
    confidence: str = None,
    evidence_refs: List[Dict] = None,
    changed_by: str = "system",
    change_reason: str = None
) -> Optional[Dict]:
    """
    Update a knowledge item by creating a new version.
    Never modifies existing versions.

    Returns:
        Updated knowledge item
    """
    try:
        with get_conn() as conn:
            cur = conn.cursor()

            # Get current version number
            cur.execute("""
                SELECT COALESCE(MAX(version_number), 0) as max_version
                FROM knowledge_item_version
                WHERE item_id = %s
            """, (item_id,))

            max_version = cur.fetchone()["max_version"]
            new_version = max_version + 1

            # Get current confidence if not specified
            if not confidence:
                cur.execute("""
                    SELECT kiv.confidence
                    FROM knowledge_item ki
                    JOIN knowledge_item_version kiv ON ki.current_version_id = kiv.id
                    WHERE ki.id = %s
                """, (item_id,))
                row = cur.fetchone()
                confidence = row["confidence"] if row else "medium"

            # Create new version
            cur.execute("""
                INSERT INTO knowledge_item_version
                (item_id, version_number, content, confidence, evidence_refs, created_by, change_reason)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                item_id,
                new_version,
                json.dumps(content),
                confidence,
                json.dumps(evidence_refs) if evidence_refs else None,
                changed_by,
                change_reason
            ))

            version_id = cur.fetchone()["id"]

            # Update item
            cur.execute("""
                UPDATE knowledge_item
                SET current_version_id = %s, updated_at = NOW()
                WHERE id = %s
            """, (version_id, item_id))

            log_with_context(logger, "info", "Knowledge item updated",
                           item_id=item_id, version=new_version)

            item = get_knowledge_item(item_id)

            # Sync to Meilisearch for keyword search
            if item:
                _sync_to_meilisearch(item)

            return item

    except Exception as e:
        log_with_context(logger, "error", "Failed to update knowledge item",
                        item_id=item_id, error=str(e))
        return None


def get_item_versions(item_id: int, limit: int = 10) -> List[Dict]:
    """Get version history for a knowledge item"""
    try:
        with get_conn() as conn:
            cur = conn.cursor()

            cur.execute("""
                SELECT * FROM knowledge_item_version
                WHERE item_id = %s
                ORDER BY version_number DESC
                LIMIT %s
            """, (item_id, limit))

            return [dict(row) for row in cur.fetchall()]

    except Exception as e:
        log_with_context(logger, "error", "Failed to get item versions",
                        item_id=item_id, error=str(e))
        return []


# ============ Stats ============

def get_knowledge_stats(namespace: str = None) -> Dict:
    """Get statistics about knowledge items"""
    try:
        with get_conn() as conn:
            cur = conn.cursor()

            namespace_filter = "WHERE namespace = %s" if namespace else ""
            params = (namespace,) if namespace else ()

            cur.execute(f"""
                SELECT
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE status = 'active') as active,
                    COUNT(*) FILTER (WHERE status = 'archived') as archived,
                    COUNT(*) FILTER (WHERE status = 'disputed') as disputed,
                    COUNT(*) FILTER (WHERE relevance_score < 0.3) as low_relevance,
                    AVG(relevance_score) as avg_relevance
                FROM knowledge_item
                {namespace_filter}
            """, params)

            row = cur.fetchone()
            stats = dict(row) if row else {}

            # Add review queue count
            cur.execute("SELECT COUNT(*) as pending FROM review_queue WHERE status = 'pending'")
            stats["pending_reviews"] = cur.fetchone()["pending"]

            return stats

    except Exception as e:
        log_with_context(logger, "error", "Failed to get knowledge stats", error=str(e))
        return {}
