import os
import hashlib
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, PointIdsList, Filter, FieldCondition, MatchValue

QDRANT_HOST = os.environ.get("QDRANT_HOST", "qdrant")
QDRANT_PORT = int(os.environ.get("QDRANT_PORT", "6333"))

_client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)


def _compute_content_hash(text: str) -> str:
    """
    Compute a hash of the text content for deduplication.
    Uses SHA256 truncated to 16 chars for compactness.
    """
    # Normalize whitespace to catch near-duplicates
    normalized = " ".join(text.split())
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def _make_point_id(source_path: str, chunk_index: int) -> str:
    """
    Generate deterministic point ID from source_path + chunk_index.
    This ensures re-ingesting the same file updates existing points
    instead of creating duplicates.
    """
    key = f"{source_path}::{chunk_index}"
    return hashlib.sha256(key.encode()).hexdigest()[:32]


def _check_existing_hashes(collection: str, content_hashes: list) -> set:
    """
    Check which content hashes already exist in the collection.
    Returns a set of existing hashes.
    """
    existing = set()

    for content_hash in content_hashes:
        try:
            # Search for points with this content_hash
            result = _client.scroll(
                collection_name=collection,
                scroll_filter=Filter(
                    must=[FieldCondition(key="content_hash", match=MatchValue(value=content_hash))]
                ),
                limit=1,
                with_payload=False,
                with_vectors=False
            )
            points, _ = result
            if points:
                existing.add(content_hash)
        except Exception:
            # Collection might not exist yet, or filter might fail
            pass

    return existing

def ensure_collection(name: str, dim: int):
    existing = [c.name for c in _client.get_collections().collections]
    if name not in existing:
        _client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=dim, distance=Distance.COSINE)
        )

def upsert_chunks(collection: str, chunks, embeddings, meta: dict, dedupe: bool = True, chunk_metadata: list = None):
    """
    Upsert chunks with embeddings into Qdrant collection.

    Args:
        collection: Collection name
        chunks: List of text chunks
        embeddings: List of embedding vectors
        meta: Metadata dict (source_path, namespace, doc_type, etc.)
        dedupe: If True, skip chunks with content_hash already in collection
        chunk_metadata: Optional list of per-chunk metadata dicts (e.g., window_hash, timestamps)
                       If provided, window_hash will be used for point IDs instead of sequential index.

    Returns:
        Dict with upsert stats (inserted, skipped)
    """
    if not chunks:
        return {"inserted": 0, "skipped": 0}

    dim = len(embeddings[0])
    ensure_collection(collection, dim)

    source_path = meta.get("source_path", "unknown")

    # Compute content hashes for all chunks
    content_hashes = [_compute_content_hash(text) for text in chunks]

    # Check which hashes already exist (if dedupe enabled)
    existing_hashes = set()
    if dedupe:
        existing_hashes = _check_existing_hashes(collection, content_hashes)

    points = []
    skipped = 0

    for i, (text, vec, content_hash) in enumerate(zip(chunks, embeddings, content_hashes)):
        # Skip if content already exists
        if dedupe and content_hash in existing_hashes:
            skipped += 1
            continue

        # Use window_hash for point ID if available (for chat windows)
        # This ensures same temporal window → same point ID → upsert overwrites
        if chunk_metadata and i < len(chunk_metadata) and chunk_metadata[i].get("window_hash"):
            point_id = chunk_metadata[i]["window_hash"]
        else:
            point_id = _make_point_id(source_path, i)

        # Build payload with chunk metadata if available
        payload = {
            **meta,
            "text": text,
            "chunk_index": i,
            "content_hash": content_hash  # Store hash for future lookups
        }

        # Add per-chunk metadata (timestamps, message_count, etc.)
        if chunk_metadata and i < len(chunk_metadata):
            for key in ["event_ts_start", "event_ts_end", "message_count", "window_hash"]:
                if key in chunk_metadata[i]:
                    payload[key] = chunk_metadata[i][key]

        points.append(PointStruct(
            id=point_id,
            vector=vec,
            payload=payload
        ))

    if points:
        _client.upsert(collection_name=collection, points=points)

    return {"inserted": len(points), "skipped": skipped}


def dedupe_collection(collection: str) -> dict:
    """
    Remove duplicate points in a collection.
    Keeps one point per (source_path, text) combination.
    Returns count of duplicates removed.
    """
    from qdrant_client.models import ScrollRequest

    # Scroll through all points
    all_points = []
    offset = None

    while True:
        result = _client.scroll(
            collection_name=collection,
            limit=1000,
            offset=offset,
            with_payload=True,
            with_vectors=False
        )
        points, next_offset = result
        all_points.extend(points)

        if next_offset is None or len(points) == 0:
            break
        offset = next_offset

    # Group by (source_path, text hash) to find duplicates
    seen = {}  # key -> point_id to keep
    duplicates = []  # point_ids to delete

    for point in all_points:
        payload = point.payload or {}
        source_path = payload.get("source_path", "")
        text = payload.get("text", "")

        # Create a key from source_path and text content
        key = f"{source_path}::{hashlib.md5(text.encode()).hexdigest()}"

        if key in seen:
            # This is a duplicate - mark for deletion
            duplicates.append(point.id)
        else:
            seen[key] = point.id

    # Delete duplicates in batches
    if duplicates:
        batch_size = 100
        for i in range(0, len(duplicates), batch_size):
            batch = duplicates[i:i + batch_size]
            _client.delete(
                collection_name=collection,
                points_selector=PointIdsList(points=batch)
            )

    return {
        "collection": collection,
        "total_points": len(all_points),
        "unique_points": len(seen),
        "duplicates_removed": len(duplicates)
    }
