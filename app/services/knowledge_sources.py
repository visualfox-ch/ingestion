"""
Knowledge Sources Service - DB-gesteuerte Konfiguration

Ersetzt hardcoded Config-Listen durch DB-Lookups.
Jarvis kann selbst Knowledge Sources hinzufügen/ändern.
"""

from typing import Optional, List
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import uuid

from ..postgres_state import get_cursor, get_dict_cursor
from ..observability import get_logger

logger = get_logger("jarvis.knowledge_sources")


@dataclass
class KnowledgeSource:
    """Repräsentiert eine Knowledge Source aus der DB."""
    id: uuid.UUID
    domain: str
    subdomain: Optional[str]
    file_path: str
    title: str
    version: str
    collection_name: str
    owner: str
    channel: Optional[str]
    language: str
    quality: str
    active: bool
    auto_reingest: bool
    last_ingested_at: Optional[datetime]
    last_chunk_count: Optional[int]
    content_hash: Optional[str] = None


def get_collection_name(domain: str, explicit_name: Optional[str] = None) -> str:
    """Generiert Collection-Name: explizit oder auto."""
    if explicit_name:
        return explicit_name
    return f"jarvis_{domain}"


def get_active_sources(domain: Optional[str] = None) -> List[KnowledgeSource]:
    """
    Holt alle aktiven Knowledge Sources aus der DB.

    Args:
        domain: Optional Filter nach Domain (z.B. "linkedin", "visualfox")

    Returns:
        Liste von KnowledgeSource Objekten
    """
    with get_dict_cursor() as cur:
        if domain:
            cur.execute(
                """
                SELECT id, domain, subdomain, file_path, title, version,
                       collection_name, owner, channel, language, quality,
                       active, auto_reingest, last_ingested_at, last_chunk_count,
                       content_hash
                FROM knowledge_sources
                WHERE active = true AND domain = %s
                ORDER BY subdomain, title
                """,
                (domain,)
            )
        else:
            cur.execute(
                """
                SELECT id, domain, subdomain, file_path, title, version,
                       collection_name, owner, channel, language, quality,
                       active, auto_reingest, last_ingested_at, last_chunk_count,
                       content_hash
                FROM knowledge_sources
                WHERE active = true
                ORDER BY domain, subdomain, title
                """
            )

        rows = cur.fetchall()

    sources = []
    for row in rows:
        sources.append(KnowledgeSource(
            id=row['id'],
            domain=row['domain'],
            subdomain=row['subdomain'],
            file_path=row['file_path'],
            title=row['title'],
            version=row['version'],
            collection_name=get_collection_name(row['domain'], row['collection_name']),
            owner=row['owner'] or 'michael_bohl',
            channel=row['channel'],
            language=row['language'] or 'de',
            quality=row['quality'] or 'high',
            active=row['active'],
            auto_reingest=row['auto_reingest'] or False,
            last_ingested_at=row['last_ingested_at'],
            last_chunk_count=row['last_chunk_count'],
            content_hash=row.get('content_hash')
        ))

    return sources


def get_all_domains() -> List[str]:
    """Gibt alle aktiven Domains zurück."""
    with get_dict_cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT domain FROM knowledge_sources
            WHERE active = true
            ORDER BY domain
            """
        )
        return [row['domain'] for row in cur.fetchall()]


def get_source_by_id(source_id: str) -> Optional[KnowledgeSource]:
    """Holt eine Knowledge Source anhand ihrer ID."""
    with get_dict_cursor() as cur:
        cur.execute(
            """
            SELECT id, domain, subdomain, file_path, title, version,
                   collection_name, owner, channel, language, quality,
                   active, auto_reingest, last_ingested_at, last_chunk_count,
                   content_hash
            FROM knowledge_sources
            WHERE id = %s
            """,
            (source_id,)
        )
        row = cur.fetchone()

    if not row:
        return None

    return KnowledgeSource(
        id=row['id'],
        domain=row['domain'],
        subdomain=row['subdomain'],
        file_path=row['file_path'],
        title=row['title'],
        version=row['version'],
        collection_name=get_collection_name(row['domain'], row['collection_name']),
        owner=row['owner'] or 'michael_bohl',
        channel=row['channel'],
        language=row['language'] or 'de',
        quality=row['quality'] or 'high',
        active=row['active'],
        auto_reingest=row['auto_reingest'] or False,
        last_ingested_at=row['last_ingested_at'],
        last_chunk_count=row['last_chunk_count'],
        content_hash=row.get('content_hash')
    )


def add_knowledge_source(
    domain: str,
    file_path: str,
    title: str,
    subdomain: Optional[str] = None,
    version: str = "1.0",
    collection_name: Optional[str] = None,
    owner: str = "michael_bohl",
    channel: Optional[str] = None,
    language: str = "de",
    quality: str = "high",
    auto_reingest: bool = False
) -> dict:
    """
    Fügt eine neue Knowledge Source hinzu.

    Returns:
        Dict mit id und status
    """
    # Validierung: Datei muss existieren (im Container-Pfad)
    # Hinweis: Wir prüfen nur das Format, nicht die Existenz (läuft im Container)
    if not file_path.startswith("/brain/"):
        return {
            "success": False,
            "error": "file_path muss mit /brain/ beginnen (Container-Mount)"
        }

    source_id = uuid.uuid4()
    actual_collection = collection_name or f"jarvis_{domain}"

    try:
        with get_dict_cursor() as cur:
            cur.execute(
                """
                INSERT INTO knowledge_sources
                    (id, domain, subdomain, file_path, title, version,
                     collection_name, owner, channel, language, quality, auto_reingest)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (domain, file_path)
                DO UPDATE SET
                    title = EXCLUDED.title,
                    subdomain = EXCLUDED.subdomain,
                    version = EXCLUDED.version,
                    collection_name = EXCLUDED.collection_name,
                    owner = EXCLUDED.owner,
                    channel = EXCLUDED.channel,
                    language = EXCLUDED.language,
                    quality = EXCLUDED.quality,
                    auto_reingest = EXCLUDED.auto_reingest,
                    active = true,
                    updated_at = now()
                RETURNING id
                """,
                (str(source_id), domain, subdomain, file_path, title, version,
                 actual_collection, owner, channel, language, quality, auto_reingest)
            )
            result = cur.fetchone()
            actual_id = result['id'] if result else source_id

        logger.info(f"Knowledge source added/updated: {domain}/{subdomain} - {title}")

        return {
            "success": True,
            "id": str(actual_id),
            "domain": domain,
            "subdomain": subdomain,
            "title": title,
            "collection": actual_collection,
            "message": f"Knowledge source '{title}' hinzugefügt. Nutze /knowledge/ingest-all oder ingest für Domain '{domain}' um zu indexieren."
        }

    except Exception as e:
        logger.error(f"Failed to add knowledge source: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def remove_knowledge_source(
    domain: str,
    file_path: Optional[str] = None,
    source_id: Optional[str] = None,
    hard_delete: bool = False
) -> dict:
    """
    Entfernt eine Knowledge Source (soft oder hard delete).

    Args:
        domain: Domain der Source
        file_path: Pfad der Datei (alternativ zu source_id)
        source_id: UUID der Source (alternativ zu file_path)
        hard_delete: Wenn True, wird der Eintrag gelöscht statt deaktiviert
    """
    try:
        with get_dict_cursor() as cur:
            if hard_delete:
                if source_id:
                    cur.execute(
                        "DELETE FROM knowledge_sources WHERE id = %s RETURNING title",
                        (source_id,)
                    )
                else:
                    cur.execute(
                        "DELETE FROM knowledge_sources WHERE domain = %s AND file_path = %s RETURNING title",
                        (domain, file_path)
                    )
            else:
                if source_id:
                    cur.execute(
                        "UPDATE knowledge_sources SET active = false, updated_at = now() WHERE id = %s RETURNING title",
                        (source_id,)
                    )
                else:
                    cur.execute(
                        "UPDATE knowledge_sources SET active = false, updated_at = now() WHERE domain = %s AND file_path = %s RETURNING title",
                        (domain, file_path)
                    )

            result = cur.fetchone()

        if result:
            action = "gelöscht" if hard_delete else "deaktiviert"
            return {
                "success": True,
                "title": result['title'],
                "message": f"Knowledge source '{result['title']}' {action}."
            }
        else:
            return {
                "success": False,
                "error": "Knowledge source nicht gefunden"
            }

    except Exception as e:
        logger.error(f"Failed to remove knowledge source: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def update_ingestion_status(
    source_id: uuid.UUID,
    chunk_count: int,
    error: Optional[str] = None,
    content_hash: Optional[str] = None
):
    """Aktualisiert den Ingestion-Status einer Source."""
    with get_dict_cursor() as cur:
        if error:
            cur.execute(
                """
                UPDATE knowledge_sources SET
                    last_ingested_at = now(),
                    last_error = %s,
                    updated_at = now()
                WHERE id = %s
                """,
                (error, str(source_id))
            )
        else:
            cur.execute(
                """
                UPDATE knowledge_sources SET
                    last_ingested_at = now(),
                    last_chunk_count = %s,
                    last_error = NULL,
                    content_hash = COALESCE(%s, content_hash),
                    updated_at = now()
                WHERE id = %s
                """,
                (chunk_count, content_hash, str(source_id))
            )


def list_knowledge_sources(
    domain: Optional[str] = None,
    include_inactive: bool = False
) -> List[dict]:
    """
    Listet Knowledge Sources für Anzeige/Tool-Output.
    """
    with get_dict_cursor() as cur:
        query = """
            SELECT id, domain, subdomain, file_path, title, version,
                   collection_name, active, last_ingested_at, last_chunk_count, last_error
            FROM knowledge_sources
        """
        params = []

        conditions = []
        if domain:
            conditions.append("domain = %s")
            params.append(domain)
        if not include_inactive:
            conditions.append("active = true")

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY domain, subdomain, title"

        cur.execute(query, params)
        rows = cur.fetchall()

    return [
        {
            "id": str(row['id']),
            "domain": row['domain'],
            "subdomain": row['subdomain'],
            "file_path": row['file_path'],
            "title": row['title'],
            "version": row['version'],
            "collection": row['collection_name'] or f"jarvis_{row['domain']}",
            "active": row['active'],
            "last_ingested": row['last_ingested_at'].isoformat() if row['last_ingested_at'] else None,
            "chunks": row['last_chunk_count'],
            "error": row['last_error']
        }
        for row in rows
    ]


def bump_version(source_id: str, new_version: Optional[str] = None) -> dict:
    """
    Erhöht die Version einer Knowledge Source.
    Triggert bei nächster Ingestion ein Re-Indexing.
    """
    if new_version is None:
        # Auto-generate: YYYY-MM-DD
        new_version = datetime.now().strftime("%Y-%m-%d")

    try:
        with get_dict_cursor() as cur:
            cur.execute(
                """
                UPDATE knowledge_sources SET
                    version = %s,
                    updated_at = now()
                WHERE id = %s
                RETURNING title, version
                """,
                (new_version, source_id)
            )
            result = cur.fetchone()

        if result:
            return {
                "success": True,
                "title": result['title'],
                "new_version": result['version'],
                "message": f"Version auf '{new_version}' erhöht. Nächste Ingestion wird neu indexieren."
            }
        else:
            return {
                "success": False,
                "error": "Knowledge source nicht gefunden"
            }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }
