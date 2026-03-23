from __future__ import annotations

"""
Knowledge Ingestion Service - DB-gesteuerte Version

Liest Konfiguration aus knowledge_sources Tabelle.
Unterstützt beliebige Domains ohne Code-Änderung.
"""

import asyncio
import hashlib
import re
import uuid
from pathlib import Path
from typing import Optional, List
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor

# Thread pool for non-blocking ingestion (keeps API responsive)
_ingestion_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ingest_")

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance, VectorParams, PointStruct, PointIdsList
)

from ..postgres_state import get_cursor, get_dict_cursor
from ..embed import embed_texts
from ..observability import get_logger
from .knowledge_sources import (
    get_active_sources,
    get_all_domains,
    update_ingestion_status,
    KnowledgeSource
)

logger = get_logger("jarvis.knowledge_ingestion")


# ============================================================================
# Konfiguration (minimal - nur Engine-Parameter)
# ============================================================================

QDRANT_HOST = "qdrant"
QDRANT_PORT = 6333
EMBEDDING_DIM = 384

CHUNK_MAX_SIZE = 1000
CHUNK_OVERLAP = 120


# ============================================================================
# Datenstrukturen
# ============================================================================

@dataclass
class Chunk:
    id: uuid.UUID
    text: str
    chunk_index: int
    chunk_title: str
    metadata: dict = field(default_factory=dict)


# ============================================================================
# Chunking-Logik (Engine - ändert sich selten)
# ============================================================================

def chunk_markdown_by_headings(
    content: str,
    max_size: int = CHUNK_MAX_SIZE,
    overlap: int = CHUNK_OVERLAP
) -> list[tuple[str, str]]:
    """
    Zerlegt Markdown in Chunks entlang von Überschriften.
    Returns: Liste von (chunk_title, chunk_text)
    """
    heading_pattern = re.compile(r'^(#{1,4})\s+(.+)$', re.MULTILINE)

    chunks = []
    current_title = "Einleitung"
    current_text = []

    lines = content.split('\n')

    for line in lines:
        heading_match = heading_pattern.match(line)

        if heading_match:
            if current_text:
                text = '\n'.join(current_text).strip()
                if text:
                    sub_chunks = _split_large_chunk(text, current_title, max_size, overlap)
                    chunks.extend(sub_chunks)

            current_title = heading_match.group(2).strip()
            current_text = [line]
        else:
            current_text.append(line)

    if current_text:
        text = '\n'.join(current_text).strip()
        if text:
            sub_chunks = _split_large_chunk(text, current_title, max_size, overlap)
            chunks.extend(sub_chunks)

    return chunks


def _split_large_chunk(
    text: str,
    title: str,
    max_size: int,
    overlap: int
) -> list[tuple[str, str]]:
    """Teilt zu große Chunks mit Overlap."""
    if len(text) <= max_size:
        return [(title, text)]

    chunks = []
    start = 0
    part = 1

    while start < len(text):
        end = start + max_size

        if end < len(text):
            for sep in ['\n\n', '\n', '. ', ', ']:
                last_sep = text.rfind(sep, start + max_size // 2, end)
                if last_sep != -1:
                    end = last_sep + len(sep)
                    break

        chunk_text = text[start:end].strip()
        chunk_title = f"{title} (Teil {part})" if part > 1 else title

        if chunk_text:
            chunks.append((chunk_title, chunk_text))

        start = end - overlap
        part += 1

    return chunks


# ============================================================================
# Qdrant Client
# ============================================================================

def get_qdrant_client() -> QdrantClient:
    return QdrantClient(url=f"http://{QDRANT_HOST}:{QDRANT_PORT}")


def ensure_collection(client: QdrantClient, collection_name: str):
    """Erstellt Collection falls nicht vorhanden."""
    collections = [c.name for c in client.get_collections().collections]

    if collection_name not in collections:
        client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(
                size=EMBEDDING_DIM,
                distance=Distance.COSINE
            )
        )
        logger.info(f"Created Qdrant collection: {collection_name}")


# ============================================================================
# PostgreSQL-Integration
# ============================================================================

def upsert_document(
    title: str,
    content: str,
    source: KnowledgeSource
) -> tuple[uuid.UUID, bool]:
    """
    Fügt Dokument ein oder aktualisiert es (basierend auf title + version).
    Returns: (document_id, is_changed)
    """
    content_hash = hashlib.sha256(content.encode()).hexdigest()[:32]

    with get_dict_cursor() as cur:
        cur.execute(
            """
            SELECT id, content_hash FROM documents
            WHERE title = %s AND version = %s
            """,
            (title, source.version)
        )
        existing = cur.fetchone()

        if existing:
            if existing['content_hash'] == content_hash:
                return existing['id'], False

            cur.execute(
                """
                UPDATE documents SET
                    content = %s,
                    content_hash = %s,
                    updated_at = now()
                WHERE id = %s
                """,
                (content, content_hash, existing['id'])
            )
            return existing['id'], True

        doc_id = uuid.uuid4()
        cur.execute(
            """
            INSERT INTO documents (id, title, content, source, owner, domain, subdomain,
                                   channel, language, quality, version, content_hash)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (str(doc_id), title, content,
             "internal_markdown", source.owner, source.domain, source.subdomain,
             source.channel, source.language, source.quality, source.version,
             content_hash)
        )
        return doc_id, True


def delete_document_chunks(document_id: uuid.UUID) -> list[str]:
    """Löscht Chunk-Tracking und gibt Qdrant-Point-IDs zurück."""
    with get_dict_cursor() as cur:
        cur.execute(
            "SELECT qdrant_point_id FROM document_chunks WHERE document_id = %s",
            (str(document_id),)
        )
        rows = cur.fetchall()
        point_ids = [str(row['qdrant_point_id']) for row in rows]

        cur.execute(
            "DELETE FROM document_chunks WHERE document_id = %s",
            (str(document_id),)
        )

    return point_ids


def save_chunk_tracking(document_id: uuid.UUID, chunks: list[Chunk]):
    """Speichert Chunk-Tracking für spätere Idempotenz."""
    with get_cursor() as cur:
        for chunk in chunks:
            cur.execute(
                """
                INSERT INTO document_chunks (document_id, chunk_index, chunk_title, qdrant_point_id)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (document_id, chunk_index)
                DO UPDATE SET chunk_title = EXCLUDED.chunk_title, qdrant_point_id = EXCLUDED.qdrant_point_id
                """,
                (str(document_id), chunk.chunk_index, chunk.chunk_title, str(chunk.id))
            )


def delete_points_by_ids(client: QdrantClient, collection_name: str, point_ids: list[str]):
    """Löscht spezifische Punkte aus Qdrant."""
    if not point_ids:
        return

    client.delete(
        collection_name=collection_name,
        points_selector=PointIdsList(points=point_ids)
    )


# ============================================================================
# Haupt-Ingestion (generisch für alle Domains)
# ============================================================================

def ingest_knowledge_source(
    qdrant: QdrantClient,
    source: KnowledgeSource
) -> dict:
    """
    Vollständige Ingestion einer Knowledge Source.
    Idempotent: Aktualisiert bei Änderungen, überspringt bei gleichem Hash.
    """
    path = Path(source.file_path)
    if not path.exists():
        error_msg = f"File not found: {source.file_path}"
        update_ingestion_status(source.id, 0, error_msg)
        return {"status": "error", "message": error_msg, "title": source.title}

    content = path.read_text(encoding='utf-8')

    # 1. PostgreSQL: Dokument upserten
    doc_id, is_changed = upsert_document(source.title, content, source)

    if not is_changed:
        return {
            "status": "unchanged",
            "document_id": str(doc_id),
            "title": source.title,
            "message": "Document unchanged, skipping re-ingestion"
        }

    # 2. Collection sicherstellen
    ensure_collection(qdrant, source.collection_name)

    # 3. Alte Chunks löschen (falls vorhanden)
    old_point_ids = delete_document_chunks(doc_id)
    delete_points_by_ids(qdrant, source.collection_name, old_point_ids)

    # 4. Neues Chunking
    raw_chunks = chunk_markdown_by_headings(content)

    chunks = []
    for idx, (chunk_title, chunk_text) in enumerate(raw_chunks):
        chunk = Chunk(
            id=uuid.uuid4(),
            text=chunk_text,
            chunk_index=idx,
            chunk_title=chunk_title,
            metadata={
                "source": "internal_markdown",
                "owner": source.owner,
                "domain": source.domain,
                "subdomain": source.subdomain,
                "channel": source.channel,
                "language": source.language,
                "quality": source.quality,
                "version": source.version,
                "title": source.title,
                "document_id": str(doc_id),
            }
        )
        chunks.append(chunk)

    # 5. Qdrant: Embeddings + Speichern
    if chunks:
        texts = [c.text for c in chunks]
        embeddings = embed_texts(texts)

        points = []
        for chunk, embedding in zip(chunks, embeddings):
            points.append(PointStruct(
                id=str(chunk.id),
                vector=embedding,
                payload={
                    "text": chunk.text,
                    "chunk_index": chunk.chunk_index,
                    "chunk_title": chunk.chunk_title,
                    **chunk.metadata
                }
            ))

        qdrant.upsert(
            collection_name=source.collection_name,
            points=points
        )

    # 6. Chunk-Tracking speichern
    save_chunk_tracking(doc_id, chunks)

    # 7. Status in knowledge_sources updaten
    update_ingestion_status(source.id, len(chunks))

    logger.info(f"Ingested: {source.domain}/{source.subdomain} - {source.title} ({len(chunks)} chunks)")

    return {
        "status": "ingested",
        "document_id": str(doc_id),
        "chunks_created": len(chunks),
        "title": source.title,
        "domain": source.domain,
        "subdomain": source.subdomain,
        "version": source.version,
        "collection": source.collection_name
    }


async def ingest_domain(domain: str) -> list[dict]:
    """Ingestet alle aktiven Sources einer Domain.

    Runs heavy embedding work in thread pool to keep API responsive.
    """
    sources = get_active_sources(domain)
    if not sources:
        return [{"status": "error", "message": f"No active sources for domain '{domain}'"}]

    qdrant = get_qdrant_client()
    results = []
    loop = asyncio.get_event_loop()

    for source in sources:
        # Run blocking ingestion in thread pool
        result = await loop.run_in_executor(
            _ingestion_executor,
            ingest_knowledge_source,
            qdrant,
            source
        )
        results.append(result)

    return results


async def ingest_all_domains() -> dict:
    """Ingestet alle aktiven Sources aller Domains.

    Runs heavy embedding work in thread pool to keep API responsive.
    """
    domains = get_all_domains()
    qdrant = get_qdrant_client()
    loop = asyncio.get_event_loop()

    results = {}
    for domain in domains:
        sources = get_active_sources(domain)
        domain_results = []

        for source in sources:
            # Run blocking ingestion in thread pool
            result = await loop.run_in_executor(
                _ingestion_executor,
                ingest_knowledge_source,
                qdrant,
                source
            )
            domain_results.append(result)

        results[domain] = domain_results

    return results
