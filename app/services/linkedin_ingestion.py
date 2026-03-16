"""
LinkedIn Knowledge Base Ingestion Pipeline
Importiert Markdown-Dateien in PostgreSQL + Qdrant
"""

import hashlib
import re
import uuid
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance, VectorParams, PointStruct,
    Filter, FieldCondition, MatchValue
)

from ..postgres_state import get_cursor
from ..embed import embed_texts


# ============================================================================
# Konfiguration (LEGACY - wird durch knowledge_sources DB-Tabelle ersetzt)
# ============================================================================

# DEPRECATED: Diese hardcoded Config wird durch die Tabelle `knowledge_sources`
# ersetzt. Nutze stattdessen:
#   - API: POST /kb/sources (neue Source hinzufügen)
#   - Tool: manage_knowledge_sources (Jarvis-Tool)
#   - Service: knowledge_sources.py, knowledge_ingestion.py (DB-gesteuert)
#
# Diese Config bleibt für Backward-Compatibility der alten /linkedin/* Endpoints.
LINKEDIN_DOCS_CONFIG = [
    {
        "file_path": "/brain/system/data/linkedin/strategie/LinkedIn-Strategie-Micha-Bohl.md",
        "title": "LinkedIn-Strategie Michael Bohl 2026",
        "subdomain": "strategy",
        "version": "2026-03-14-v2",
    },
    {
        "file_path": "/brain/system/data/linkedin/content-plan/Portfolio-Aufbauplan-Micha-Bohl.md",
        "title": "Portfolio-Aufbauplan Michael Bohl 2026",
        "subdomain": "portfolio",
        "version": "2026-03-14-v2",
    },
    {
        "file_path": "/brain/system/data/linkedin/LinkedIn-Strategie-Overview-2026.md",
        "title": "LinkedIn-Strategie Overview 2026",
        "subdomain": "overview",
        "version": "2026-03-14",
    },
    {
        "file_path": "/brain/system/data/linkedin/content-plan/Sora-Prompt-LinkedIn-Banner-Micha.md",
        "title": "Sora Prompt LinkedIn Banner",
        "subdomain": "assets",
        "version": "2026-03-14",
    },
]

VISUALFOX_DOCS_CONFIG = [
    {
        "file_path": "/brain/system/data/visualfox/Brand-System-visualfox-2026.md",
        "title": "visualfox 2.0 Brand System Overview",
        "subdomain": "brand",
        "version": "2026-03-14",
    },
]

QDRANT_COLLECTION = "jarvis_linkedin"
QDRANT_COLLECTION_VISUALFOX = "jarvis_visualfox"
QDRANT_HOST = "qdrant"
QDRANT_PORT = 6333
EMBEDDING_DIM = 384

CHUNK_MAX_SIZE = 1000
CHUNK_OVERLAP = 120


# ============================================================================
# Datenstrukturen
# ============================================================================

@dataclass
class DocumentMetadata:
    source: str = "internal_markdown"
    owner: str = "michael_bohl"
    domain: str = "linkedin_strategy"
    subdomain: str = ""
    channel: str = "linkedin"
    language: str = "de"
    quality: str = "high"
    version: str = ""
    title: str = ""


@dataclass
class Chunk:
    id: uuid.UUID
    text: str
    chunk_index: int
    chunk_title: str
    metadata: dict = field(default_factory=dict)


# ============================================================================
# Chunking-Logik
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
# PostgreSQL-Integration
# ============================================================================

def upsert_document(
    title: str,
    content: str,
    metadata: DocumentMetadata
) -> tuple[uuid.UUID, bool]:
    """
    Fügt Dokument ein oder aktualisiert es (basierend auf title + version).
    Returns: (document_id, is_changed)
    """
    content_hash = hashlib.sha256(content.encode()).hexdigest()[:32]

    with get_cursor() as cur:
        # Prüfen ob bereits vorhanden
        cur.execute(
            """
            SELECT id, content_hash FROM documents
            WHERE title = %s AND version = %s
            """,
            (title, metadata.version)
        )
        existing = cur.fetchone()

        if existing:
            if existing['content_hash'] == content_hash:
                return existing['id'], False

            # Update
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

        # Insert
        doc_id = uuid.uuid4()
        cur.execute(
            """
            INSERT INTO documents (id, title, content, source, owner, domain, subdomain,
                                   channel, language, quality, version, content_hash)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (str(doc_id), title, content,
             metadata.source, metadata.owner, metadata.domain, metadata.subdomain,
             metadata.channel, metadata.language, metadata.quality, metadata.version,
             content_hash)
        )
        return doc_id, True


def delete_document_chunks(document_id: uuid.UUID) -> list[str]:
    """Löscht Chunk-Tracking und gibt Qdrant-Point-IDs zurück."""
    with get_cursor() as cur:
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


# ============================================================================
# Qdrant-Integration
# ============================================================================

def get_qdrant_client() -> QdrantClient:
    return QdrantClient(url=f"http://{QDRANT_HOST}:{QDRANT_PORT}")


def ensure_collection(client: QdrantClient):
    """Erstellt Collection falls nicht vorhanden."""
    collections = [c.name for c in client.get_collections().collections]

    if QDRANT_COLLECTION not in collections:
        client.create_collection(
            collection_name=QDRANT_COLLECTION,
            vectors_config=VectorParams(
                size=EMBEDDING_DIM,
                distance=Distance.COSINE
            )
        )


def delete_points_by_ids(client: QdrantClient, point_ids: list[str]):
    """Löscht spezifische Punkte aus Qdrant."""
    if not point_ids:
        return

    client.delete(
        collection_name=QDRANT_COLLECTION,
        points_selector={"points": point_ids}
    )


def ingest_chunks_to_qdrant(client: QdrantClient, chunks: list[Chunk]):
    """Embeddings erzeugen und in Qdrant speichern."""
    if not chunks:
        return

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

    client.upsert(
        collection_name=QDRANT_COLLECTION,
        points=points
    )


# ============================================================================
# Haupt-Ingestion-Pipeline
# ============================================================================

def ingest_linkedin_document(
    qdrant: QdrantClient,
    file_path: str,
    title: str,
    subdomain: str,
    version: str
) -> dict:
    """
    Vollständige Ingestion eines LinkedIn-Dokuments.
    Idempotent: Aktualisiert bei Änderungen, überspringt bei gleichem Hash.
    """
    path = Path(file_path)
    if not path.exists():
        return {"status": "error", "message": f"File not found: {file_path}"}

    content = path.read_text(encoding='utf-8')

    metadata = DocumentMetadata(
        subdomain=subdomain,
        version=version,
        title=title
    )

    # 1. PostgreSQL: Dokument upserten
    doc_id, is_changed = upsert_document(title, content, metadata)

    if not is_changed:
        return {
            "status": "unchanged",
            "document_id": str(doc_id),
            "message": "Document unchanged, skipping re-ingestion"
        }

    # 2. Alte Chunks löschen (falls vorhanden)
    old_point_ids = delete_document_chunks(doc_id)
    delete_points_by_ids(qdrant, old_point_ids)

    # 3. Neues Chunking
    raw_chunks = chunk_markdown_by_headings(content)

    chunks = []
    for idx, (chunk_title, chunk_text) in enumerate(raw_chunks):
        chunk = Chunk(
            id=uuid.uuid4(),
            text=chunk_text,
            chunk_index=idx,
            chunk_title=chunk_title,
            metadata={
                "source": metadata.source,
                "owner": metadata.owner,
                "domain": metadata.domain,
                "subdomain": metadata.subdomain,
                "channel": metadata.channel,
                "language": metadata.language,
                "quality": metadata.quality,
                "version": metadata.version,
                "title": metadata.title,
                "document_id": str(doc_id),
            }
        )
        chunks.append(chunk)

    # 4. Qdrant: Embeddings + Speichern
    ingest_chunks_to_qdrant(qdrant, chunks)

    # 5. Chunk-Tracking speichern
    save_chunk_tracking(doc_id, chunks)

    return {
        "status": "ingested",
        "document_id": str(doc_id),
        "chunks_created": len(chunks),
        "title": title,
        "version": version
    }


async def ingest_all_linkedin_documents() -> list[dict]:
    """Ingestion aller konfigurierten LinkedIn-Dokumente."""
    qdrant = get_qdrant_client()
    ensure_collection(qdrant)

    results = []
    for doc_config in LINKEDIN_DOCS_CONFIG:
        result = ingest_linkedin_document(
            qdrant=qdrant,
            file_path=doc_config["file_path"],
            title=doc_config["title"],
            subdomain=doc_config["subdomain"],
            version=doc_config["version"]
        )
        results.append(result)

    return results


def ensure_collection_for(client: QdrantClient, collection_name: str):
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


def ingest_visualfox_document(
    qdrant: QdrantClient,
    file_path: str,
    title: str,
    subdomain: str,
    version: str
) -> dict:
    """
    Vollständige Ingestion eines visualfox-Dokuments.
    """
    path = Path(file_path)
    if not path.exists():
        return {"status": "error", "message": f"File not found: {file_path}"}

    content = path.read_text(encoding='utf-8')

    metadata = DocumentMetadata(
        source="internal_markdown",
        owner="michael_bohl",
        domain="visualfox_brand",
        subdomain=subdomain,
        channel="brand",
        language="de",
        quality="high",
        version=version,
        title=title
    )

    # 1. PostgreSQL: Dokument upserten
    doc_id, is_changed = upsert_document(title, content, metadata)

    if not is_changed:
        return {
            "status": "unchanged",
            "document_id": str(doc_id),
            "message": "Document unchanged, skipping re-ingestion"
        }

    # 2. Alte Chunks löschen (falls vorhanden)
    old_point_ids = delete_document_chunks(doc_id)
    if old_point_ids:
        client = get_qdrant_client()
        delete_points_by_ids(client, old_point_ids)

    # 3. Neues Chunking
    raw_chunks = chunk_markdown_by_headings(content)

    chunks = []
    for idx, (chunk_title, chunk_text) in enumerate(raw_chunks):
        chunk = Chunk(
            id=uuid.uuid4(),
            text=chunk_text,
            chunk_index=idx,
            chunk_title=chunk_title,
            metadata={
                "source": metadata.source,
                "owner": metadata.owner,
                "domain": metadata.domain,
                "subdomain": metadata.subdomain,
                "channel": metadata.channel,
                "language": metadata.language,
                "quality": metadata.quality,
                "version": metadata.version,
                "title": metadata.title,
                "document_id": str(doc_id),
            }
        )
        chunks.append(chunk)

    # 4. Qdrant: Embeddings + Speichern (in visualfox collection)
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
            collection_name=QDRANT_COLLECTION_VISUALFOX,
            points=points
        )

    # 5. Chunk-Tracking speichern
    save_chunk_tracking(doc_id, chunks)

    return {
        "status": "ingested",
        "document_id": str(doc_id),
        "chunks_created": len(chunks),
        "title": title,
        "version": version
    }


async def ingest_all_visualfox_documents() -> list[dict]:
    """Ingestion aller konfigurierten visualfox-Dokumente."""
    qdrant = get_qdrant_client()
    ensure_collection_for(qdrant, QDRANT_COLLECTION_VISUALFOX)

    results = []
    for doc_config in VISUALFOX_DOCS_CONFIG:
        result = ingest_visualfox_document(
            qdrant=qdrant,
            file_path=doc_config["file_path"],
            title=doc_config["title"],
            subdomain=doc_config["subdomain"],
            version=doc_config["version"]
        )
        results.append(result)

    return results


async def ingest_all_knowledge_bases() -> dict:
    """Ingestion aller Knowledge Bases (LinkedIn + visualfox)."""
    linkedin_results = await ingest_all_linkedin_documents()
    visualfox_results = await ingest_all_visualfox_documents()

    return {
        "linkedin": linkedin_results,
        "visualfox": visualfox_results
    }
