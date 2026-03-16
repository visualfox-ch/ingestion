"""
RAG Maintenance Tools - Tier 2 #6 Jarvis Evolution

Self-maintenance for RAG system:
- Duplicate detection and cleanup
- Re-indexing triggers
- Collection health analysis
- Embedding drift detection
- Stale document cleanup
"""

import os
import json
import logging
import hashlib
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
import requests
from collections import defaultdict

logger = logging.getLogger(__name__)

# Configuration - use Docker network hostname
QDRANT_HOST = os.getenv("QDRANT_HOST", "qdrant")
QDRANT_PORT = os.getenv("QDRANT_PORT", "6333")
QDRANT_URL = os.getenv("QDRANT_URL", f"http://{QDRANT_HOST}:{QDRANT_PORT}")
STATE_PATH = "/brain/system/state/rag_maintenance_state.json"

# Maintenance thresholds
DUPLICATE_SIMILARITY_THRESHOLD = 0.98  # Very similar = likely duplicate
STALE_DAYS_THRESHOLD = 180  # 6 months without access
COLLECTION_SIZE_WARNING = 100000  # Warn if > 100k docs


def _load_state() -> Dict[str, Any]:
    """Load maintenance state from file."""
    try:
        if os.path.exists(STATE_PATH):
            with open(STATE_PATH, "r") as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load state: {e}")

    return {
        "last_maintenance": None,
        "maintenance_history": [],
        "duplicate_candidates": [],
        "stale_candidates": [],
        "statistics": {
            "total_maintenance_runs": 0,
            "duplicates_found": 0,
            "duplicates_cleaned": 0,
            "reindexes_triggered": 0
        }
    }


def _save_state(state: Dict[str, Any]) -> None:
    """Save maintenance state to file."""
    try:
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        with open(STATE_PATH, "w") as f:
            json.dump(state, f, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to save state: {e}")


def _qdrant_request(method: str, endpoint: str, data: dict = None) -> Dict[str, Any]:
    """Make a request to Qdrant REST API."""
    url = f"{QDRANT_URL}{endpoint}"
    try:
        if method == "GET":
            response = requests.get(url, timeout=30)
        elif method == "POST":
            response = requests.post(url, json=data, timeout=60)
        elif method == "DELETE":
            response = requests.delete(url, json=data, timeout=30)
        else:
            return {"error": f"Unknown method: {method}"}

        if response.status_code in [200, 201]:
            return response.json()
        else:
            return {"error": f"HTTP {response.status_code}: {response.text[:200]}"}
    except requests.exceptions.RequestException as e:
        return {"error": str(e)}


def get_collection_health(
    collection_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Analyze health of RAG collections.

    Args:
        collection_name: Specific collection or None for all

    Returns:
        Dict with health metrics for collections
    """
    result = {
        "timestamp": datetime.now().isoformat(),
        "collections": {},
        "overall_health": "healthy",
        "issues": [],
        "recommendations": []
    }

    # Get all collections
    collections_response = _qdrant_request("GET", "/collections")
    if "error" in collections_response:
        result["error"] = collections_response["error"]
        result["overall_health"] = "error"
        return result

    collections = collections_response.get("result", {}).get("collections", [])

    if collection_name:
        collections = [c for c in collections if c.get("name") == collection_name]

    for coll in collections:
        name = coll.get("name")

        # Get collection info
        info_response = _qdrant_request("GET", f"/collections/{name}")
        if "error" in info_response:
            result["collections"][name] = {"error": info_response["error"]}
            continue

        info = info_response.get("result", {})
        points_count = info.get("points_count", 0)
        vectors_count = info.get("vectors_count", 0)
        indexed_vectors = info.get("indexed_vectors_count", 0)
        status = info.get("status", "unknown")

        # Calculate health metrics
        health = "healthy"
        coll_issues = []

        # Check indexing status
        if vectors_count > 0 and indexed_vectors < vectors_count * 0.9:
            health = "degraded"
            coll_issues.append(f"Only {indexed_vectors}/{vectors_count} vectors indexed")

        # Check size
        if points_count > COLLECTION_SIZE_WARNING:
            coll_issues.append(f"Large collection: {points_count} documents")

        # Check status
        if status != "green":
            health = "warning" if status == "yellow" else "degraded"
            coll_issues.append(f"Collection status: {status}")

        result["collections"][name] = {
            "points_count": points_count,
            "vectors_count": vectors_count,
            "indexed_vectors": indexed_vectors,
            "status": status,
            "health": health,
            "issues": coll_issues
        }

        if coll_issues:
            result["issues"].extend([f"{name}: {i}" for i in coll_issues])

    # Overall health
    if any(c.get("health") == "degraded" for c in result["collections"].values()):
        result["overall_health"] = "degraded"
    elif any(c.get("health") == "warning" for c in result["collections"].values()):
        result["overall_health"] = "warning"

    # Recommendations
    if result["issues"]:
        result["recommendations"].append("Review collections with issues")

    total_points = sum(
        c.get("points_count", 0) for c in result["collections"].values()
    )
    if total_points > 500000:
        result["recommendations"].append(
            "Consider archiving old data - total points exceed 500k"
        )

    return result


def find_duplicates(
    collection_name: str,
    sample_size: int = 100,
    similarity_threshold: float = 0.98
) -> Dict[str, Any]:
    """
    Find potential duplicate documents in a collection.

    Args:
        collection_name: Collection to analyze
        sample_size: Number of documents to sample for comparison
        similarity_threshold: Similarity score threshold for duplicates (0-1)

    Returns:
        Dict with duplicate candidates and their similarity scores
    """
    state = _load_state()

    result = {
        "timestamp": datetime.now().isoformat(),
        "collection": collection_name,
        "sample_size": sample_size,
        "threshold": similarity_threshold,
        "duplicates_found": [],
        "total_checked": 0,
        "duplicate_groups": 0
    }

    # Get sample points
    scroll_response = _qdrant_request(
        "POST",
        f"/collections/{collection_name}/points/scroll",
        {
            "limit": sample_size,
            "with_payload": True,
            "with_vector": True
        }
    )

    if "error" in scroll_response:
        result["error"] = scroll_response["error"]
        return result

    points = scroll_response.get("result", {}).get("points", [])
    result["total_checked"] = len(points)

    if len(points) < 2:
        result["message"] = "Not enough points for comparison"
        return result

    # Compare each point to others (O(n^2) but limited by sample_size)
    duplicate_groups = defaultdict(list)
    checked_pairs = set()

    for i, point_a in enumerate(points):
        vector_a = point_a.get("vector")
        if not vector_a:
            continue

        # Search for similar vectors
        search_response = _qdrant_request(
            "POST",
            f"/collections/{collection_name}/points/search",
            {
                "vector": vector_a,
                "limit": 5,
                "with_payload": True,
                "score_threshold": similarity_threshold
            }
        )

        if "error" in search_response:
            continue

        matches = search_response.get("result", [])

        for match in matches:
            match_id = match.get("id")
            score = match.get("score", 0)

            # Skip self-match
            if match_id == point_a.get("id"):
                continue

            # Skip already checked pairs
            pair_key = tuple(sorted([str(point_a.get("id")), str(match_id)]))
            if pair_key in checked_pairs:
                continue
            checked_pairs.add(pair_key)

            # Record duplicate candidate
            if score >= similarity_threshold:
                payload_a = point_a.get("payload", {})
                payload_b = match.get("payload", {})

                duplicate_info = {
                    "point_a": {
                        "id": point_a.get("id"),
                        "title": payload_a.get("title", payload_a.get("name", "Unknown")),
                        "source": payload_a.get("source", "Unknown")
                    },
                    "point_b": {
                        "id": match_id,
                        "title": payload_b.get("title", payload_b.get("name", "Unknown")),
                        "source": payload_b.get("source", "Unknown")
                    },
                    "similarity_score": round(score, 4)
                }

                result["duplicates_found"].append(duplicate_info)

                # Group by point_a
                group_key = str(point_a.get("id"))
                duplicate_groups[group_key].append(match_id)

    result["duplicate_groups"] = len(duplicate_groups)

    # Update state
    state["duplicate_candidates"] = result["duplicates_found"][:50]  # Keep top 50
    state["statistics"]["duplicates_found"] += len(result["duplicates_found"])
    _save_state(state)

    return result


def cleanup_duplicates(
    collection_name: str,
    duplicate_ids: List[str],
    dry_run: bool = True
) -> Dict[str, Any]:
    """
    Remove duplicate documents from a collection.

    Args:
        collection_name: Collection to clean
        duplicate_ids: List of point IDs to remove
        dry_run: If True, only report what would be deleted

    Returns:
        Dict with cleanup results
    """
    state = _load_state()

    result = {
        "timestamp": datetime.now().isoformat(),
        "collection": collection_name,
        "dry_run": dry_run,
        "ids_to_delete": duplicate_ids,
        "deleted_count": 0,
        "errors": []
    }

    if dry_run:
        result["message"] = f"Dry run: Would delete {len(duplicate_ids)} points"
        return result

    # Delete points
    delete_response = _qdrant_request(
        "POST",
        f"/collections/{collection_name}/points/delete",
        {
            "points": duplicate_ids
        }
    )

    if "error" in delete_response:
        result["errors"].append(delete_response["error"])
    else:
        result["deleted_count"] = len(duplicate_ids)
        state["statistics"]["duplicates_cleaned"] += len(duplicate_ids)
        _save_state(state)

    return result


def analyze_embedding_drift(
    collection_name: str,
    reference_query: str = "test query for embedding analysis"
) -> Dict[str, Any]:
    """
    Analyze if embeddings in collection might be outdated or inconsistent.

    Checks embedding dimensions and performs sanity checks.

    Args:
        collection_name: Collection to analyze
        reference_query: Query to generate reference embedding

    Returns:
        Dict with drift analysis results
    """
    result = {
        "timestamp": datetime.now().isoformat(),
        "collection": collection_name,
        "drift_detected": False,
        "issues": [],
        "recommendations": []
    }

    # Get collection info
    info_response = _qdrant_request("GET", f"/collections/{collection_name}")
    if "error" in info_response:
        result["error"] = info_response["error"]
        return result

    config = info_response.get("result", {}).get("config", {})
    params = config.get("params", {})
    vectors_config = params.get("vectors", {})

    # Check vector dimensions
    if isinstance(vectors_config, dict) and "size" in vectors_config:
        dimension = vectors_config.get("size")
    else:
        dimension = vectors_config.get("size") if vectors_config else None

    result["vector_dimension"] = dimension

    # Get sample vectors to check consistency
    scroll_response = _qdrant_request(
        "POST",
        f"/collections/{collection_name}/points/scroll",
        {
            "limit": 10,
            "with_vector": True
        }
    )

    if "error" not in scroll_response:
        points = scroll_response.get("result", {}).get("points", [])
        dimensions_found = set()

        for point in points:
            vector = point.get("vector")
            if isinstance(vector, list):
                dimensions_found.add(len(vector))

        if len(dimensions_found) > 1:
            result["drift_detected"] = True
            result["issues"].append(
                f"Inconsistent vector dimensions found: {dimensions_found}"
            )
            result["recommendations"].append(
                "Re-index collection with consistent embedding model"
            )

    # Check for very old indexed_vectors vs points_count mismatch
    info = info_response.get("result", {})
    points_count = info.get("points_count", 0)
    indexed_count = info.get("indexed_vectors_count", 0)

    if points_count > 0 and indexed_count < points_count * 0.5:
        result["drift_detected"] = True
        result["issues"].append(
            f"Low index coverage: {indexed_count}/{points_count} vectors indexed"
        )
        result["recommendations"].append("Trigger re-indexing")

    return result


def trigger_reindex(
    collection_name: str,
    force: bool = False
) -> Dict[str, Any]:
    """
    Trigger re-indexing of a collection.

    Args:
        collection_name: Collection to reindex
        force: Force reindex even if not needed

    Returns:
        Dict with reindex trigger result
    """
    state = _load_state()

    result = {
        "timestamp": datetime.now().isoformat(),
        "collection": collection_name,
        "triggered": False,
        "message": ""
    }

    # Check if reindex is needed
    if not force:
        health = get_collection_health(collection_name)
        coll_health = health.get("collections", {}).get(collection_name, {})

        if coll_health.get("health") == "healthy":
            result["message"] = "Collection is healthy, reindex not needed"
            return result

    # Trigger reindex by updating collection params
    # This forces Qdrant to rebuild indexes
    update_response = _qdrant_request(
        "PATCH",
        f"/collections/{collection_name}",
        {
            "optimizers_config": {
                "indexing_threshold": 10000  # Trigger optimization
            }
        }
    )

    if "error" in update_response:
        result["error"] = update_response["error"]
    else:
        result["triggered"] = True
        result["message"] = "Reindex triggered successfully"
        state["statistics"]["reindexes_triggered"] += 1
        _save_state(state)

    return result


def get_maintenance_status() -> Dict[str, Any]:
    """
    Get current RAG maintenance status and statistics.

    Returns:
        Dict with maintenance statistics and recommendations
    """
    state = _load_state()

    # Get overall health
    health = get_collection_health()

    return {
        "timestamp": datetime.now().isoformat(),
        "last_maintenance": state.get("last_maintenance"),
        "statistics": state.get("statistics", {}),
        "pending_duplicates": len(state.get("duplicate_candidates", [])),
        "overall_health": health.get("overall_health", "unknown"),
        "collection_count": len(health.get("collections", {})),
        "total_issues": len(health.get("issues", [])),
        "recommendations": health.get("recommendations", [])
    }


def run_maintenance(
    auto_cleanup: bool = False,
    collections: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Run full RAG maintenance cycle.

    Args:
        auto_cleanup: Automatically cleanup found duplicates
        collections: Specific collections to maintain (None = all)

    Returns:
        Dict with maintenance results
    """
    state = _load_state()
    state["statistics"]["total_maintenance_runs"] += 1

    result = {
        "timestamp": datetime.now().isoformat(),
        "collections_checked": [],
        "duplicates_found": 0,
        "duplicates_cleaned": 0,
        "issues_found": [],
        "actions_taken": [],
        "recommendations": []
    }

    # Get collections to check
    health = get_collection_health()
    all_collections = list(health.get("collections", {}).keys())

    if collections:
        check_collections = [c for c in collections if c in all_collections]
    else:
        check_collections = all_collections

    result["collections_checked"] = check_collections

    # Check each collection
    for coll_name in check_collections:
        coll_health = health["collections"].get(coll_name, {})

        # Record issues
        if coll_health.get("issues"):
            result["issues_found"].extend(
                [f"{coll_name}: {i}" for i in coll_health["issues"]]
            )

        # Find duplicates (sample-based)
        dup_result = find_duplicates(coll_name, sample_size=50)
        dups_found = len(dup_result.get("duplicates_found", []))
        result["duplicates_found"] += dups_found

        if dups_found > 0:
            result["actions_taken"].append(
                f"Found {dups_found} potential duplicates in {coll_name}"
            )

            if auto_cleanup and dups_found > 0:
                # Get IDs to cleanup (keep first, delete duplicates)
                ids_to_delete = []
                for dup in dup_result["duplicates_found"]:
                    ids_to_delete.append(dup["point_b"]["id"])

                if ids_to_delete:
                    cleanup_result = cleanup_duplicates(
                        coll_name,
                        ids_to_delete,
                        dry_run=False
                    )
                    result["duplicates_cleaned"] += cleanup_result.get("deleted_count", 0)
                    result["actions_taken"].append(
                        f"Cleaned {cleanup_result.get('deleted_count', 0)} duplicates from {coll_name}"
                    )

        # Check for drift
        drift_result = analyze_embedding_drift(coll_name)
        if drift_result.get("drift_detected"):
            result["issues_found"].append(f"{coll_name}: Embedding drift detected")
            result["recommendations"].extend(drift_result.get("recommendations", []))

    # Update state
    state["last_maintenance"] = datetime.now().isoformat()
    state["maintenance_history"].append({
        "timestamp": result["timestamp"],
        "collections": len(check_collections),
        "duplicates_found": result["duplicates_found"],
        "duplicates_cleaned": result["duplicates_cleaned"],
        "issues": len(result["issues_found"])
    })
    state["maintenance_history"] = state["maintenance_history"][-50:]  # Keep last 50
    _save_state(state)

    # Generate recommendations
    if result["duplicates_found"] > 10:
        result["recommendations"].append(
            "High duplicate count - consider enabling auto_cleanup"
        )

    if not result["issues_found"] and not result["duplicates_found"]:
        result["summary"] = "All collections healthy, no issues found"
    else:
        result["summary"] = (
            f"Found {len(result['issues_found'])} issues, "
            f"{result['duplicates_found']} duplicates"
        )

    return result


# Tool definitions for registration
RAG_MAINTENANCE_TOOLS = [
    {
        "name": "get_collection_health",
        "description": "Analyze health of RAG collections including indexing status and size.",
        "input_schema": {
            "type": "object",
            "properties": {
                "collection_name": {
                    "type": "string",
                    "description": "Specific collection to check, or omit for all"
                }
            }
        }
    },
    {
        "name": "find_duplicates",
        "description": "Find potential duplicate documents in a Qdrant collection.",
        "input_schema": {
            "type": "object",
            "properties": {
                "collection_name": {
                    "type": "string",
                    "description": "Collection to analyze"
                },
                "sample_size": {
                    "type": "integer",
                    "default": 100,
                    "description": "Number of documents to sample"
                },
                "similarity_threshold": {
                    "type": "number",
                    "default": 0.98,
                    "description": "Similarity threshold for duplicates (0-1)"
                }
            },
            "required": ["collection_name"]
        }
    },
    {
        "name": "cleanup_duplicates",
        "description": "Remove duplicate documents from a collection. Use dry_run=true to preview.",
        "input_schema": {
            "type": "object",
            "properties": {
                "collection_name": {
                    "type": "string",
                    "description": "Collection to clean"
                },
                "duplicate_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of point IDs to remove"
                },
                "dry_run": {
                    "type": "boolean",
                    "default": True,
                    "description": "If true, only report what would be deleted"
                }
            },
            "required": ["collection_name", "duplicate_ids"]
        }
    },
    {
        "name": "analyze_embedding_drift",
        "description": "Check if embeddings in a collection might be outdated or inconsistent.",
        "input_schema": {
            "type": "object",
            "properties": {
                "collection_name": {
                    "type": "string",
                    "description": "Collection to analyze"
                }
            },
            "required": ["collection_name"]
        }
    },
    {
        "name": "trigger_reindex",
        "description": "Trigger re-indexing of a Qdrant collection.",
        "input_schema": {
            "type": "object",
            "properties": {
                "collection_name": {
                    "type": "string",
                    "description": "Collection to reindex"
                },
                "force": {
                    "type": "boolean",
                    "default": False,
                    "description": "Force reindex even if not needed"
                }
            },
            "required": ["collection_name"]
        }
    },
    {
        "name": "get_maintenance_status",
        "description": "Get current RAG maintenance status and statistics.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "run_maintenance",
        "description": "Run full RAG maintenance cycle - health check, duplicate detection, drift analysis.",
        "input_schema": {
            "type": "object",
            "properties": {
                "auto_cleanup": {
                    "type": "boolean",
                    "default": False,
                    "description": "Automatically cleanup found duplicates"
                },
                "collections": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Specific collections to maintain (omit for all)"
                }
            }
        }
    }
]
