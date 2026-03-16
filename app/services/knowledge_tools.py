"""
Knowledge Management Tools für Jarvis

Ermöglicht Jarvis, Knowledge Sources selbst zu verwalten:
- Sources hinzufügen/entfernen
- Ingestion triggern
- Status prüfen
"""

from typing import Optional
from .knowledge_sources import (
    add_knowledge_source,
    remove_knowledge_source,
    list_knowledge_sources,
    bump_version,
    get_all_domains
)
from .knowledge_ingestion import ingest_domain, ingest_all_domains
from .knowledge_retrieval import search_knowledge
import asyncio


# ============================================================================
# Tool Handlers
# ============================================================================

def handle_manage_knowledge_sources(
    action: str,
    domain: Optional[str] = None,
    file_path: Optional[str] = None,
    title: Optional[str] = None,
    subdomain: Optional[str] = None,
    version: Optional[str] = None,
    source_id: Optional[str] = None,
    include_inactive: bool = False
) -> dict:
    """
    Verwaltet Knowledge Sources.

    Actions:
        - list: Zeigt alle Sources (optional gefiltert nach domain)
        - add: Fügt neue Source hinzu
        - remove: Deaktiviert eine Source
        - delete: Löscht eine Source permanent
        - bump_version: Erhöht Version (triggert Re-Indexing)
        - domains: Zeigt alle aktiven Domains
    """
    if action == "list":
        sources = list_knowledge_sources(domain, include_inactive)
        return {
            "action": "list",
            "count": len(sources),
            "sources": sources
        }

    elif action == "domains":
        domains = get_all_domains()
        return {
            "action": "domains",
            "domains": domains
        }

    elif action == "add":
        if not all([domain, file_path, title]):
            return {
                "error": "Für 'add' werden domain, file_path und title benötigt"
            }
        return add_knowledge_source(
            domain=domain,
            file_path=file_path,
            title=title,
            subdomain=subdomain,
            version=version or "1.0"
        )

    elif action == "remove":
        if not domain or (not file_path and not source_id):
            return {
                "error": "Für 'remove' werden domain und (file_path oder source_id) benötigt"
            }
        return remove_knowledge_source(
            domain=domain,
            file_path=file_path,
            source_id=source_id,
            hard_delete=False
        )

    elif action == "delete":
        if not domain or (not file_path and not source_id):
            return {
                "error": "Für 'delete' werden domain und (file_path oder source_id) benötigt"
            }
        return remove_knowledge_source(
            domain=domain,
            file_path=file_path,
            source_id=source_id,
            hard_delete=True
        )

    elif action == "bump_version":
        if not source_id:
            return {
                "error": "Für 'bump_version' wird source_id benötigt"
            }
        return bump_version(source_id, version)

    else:
        return {
            "error": f"Unbekannte action: {action}",
            "valid_actions": ["list", "add", "remove", "delete", "bump_version", "domains"]
        }


def handle_ingest_knowledge(
    domain: Optional[str] = None,
    ingest_all: bool = False
) -> dict:
    """
    Triggert Knowledge Ingestion.

    Args:
        domain: Spezifische Domain ingesten (z.B. "linkedin", "visualfox")
        ingest_all: Wenn True, alle Domains ingesten
    """
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    if ingest_all or not domain:
        results = loop.run_until_complete(ingest_all_domains())
        total_chunks = 0
        total_docs = 0

        for domain_name, domain_results in results.items():
            for r in domain_results:
                if r.get("status") == "ingested":
                    total_chunks += r.get("chunks_created", 0)
                    total_docs += 1

        return {
            "action": "ingest_all",
            "results": results,
            "summary": {
                "domains": len(results),
                "documents_ingested": total_docs,
                "total_chunks": total_chunks
            }
        }
    else:
        results = loop.run_until_complete(ingest_domain(domain))
        total_chunks = sum(r.get("chunks_created", 0) for r in results if r.get("status") == "ingested")

        return {
            "action": "ingest_domain",
            "domain": domain,
            "results": results,
            "summary": {
                "documents": len(results),
                "chunks_created": total_chunks
            }
        }


def handle_search_knowledge(
    query: str,
    domain: Optional[str] = None,
    subdomain: Optional[str] = None,
    top_k: int = 8
) -> dict:
    """
    Durchsucht Knowledge Bases.

    Args:
        query: Suchanfrage
        domain: Optional Domain-Filter (z.B. "linkedin", "visualfox")
        subdomain: Optional Subdomain-Filter
        top_k: Anzahl Ergebnisse
    """
    results = search_knowledge(
        query=query,
        domain=domain,
        subdomain=subdomain,
        top_k=top_k
    )

    if not results:
        return {
            "found": False,
            "message": "Keine relevanten Informationen gefunden."
        }

    return {
        "found": True,
        "count": len(results),
        "results": [
            {
                "text": r["text"][:800],
                "score": round(r["score"], 3),
                "section": r["metadata"].get("chunk_title", ""),
                "domain": r["metadata"].get("domain", ""),
                "subdomain": r["metadata"].get("subdomain", "")
            }
            for r in results
        ]
    }


# ============================================================================
# Tool Schemas für TOOL_REGISTRY
# ============================================================================

MANAGE_KNOWLEDGE_SOURCES_SCHEMA = {
    "name": "manage_knowledge_sources",
    "description": "Verwaltet Knowledge Sources (Dateien für die Wissensbasis). Actions: list (zeige alle), add (neue Source), remove (deaktivieren), delete (permanent löschen), bump_version (für Re-Indexing), domains (zeige alle Domains).",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "add", "remove", "delete", "bump_version", "domains"],
                "description": "Aktion: list, add, remove, delete, bump_version, domains"
            },
            "domain": {
                "type": "string",
                "description": "Domain (z.B. 'linkedin', 'visualfox', 'pixera')"
            },
            "file_path": {
                "type": "string",
                "description": "Dateipfad im Container (muss mit /brain/ beginnen)"
            },
            "title": {
                "type": "string",
                "description": "Anzeigename für das Dokument"
            },
            "subdomain": {
                "type": "string",
                "description": "Unterkategorie (z.B. 'strategy', 'brand')"
            },
            "version": {
                "type": "string",
                "description": "Version (z.B. '2026-03-14')"
            },
            "source_id": {
                "type": "string",
                "description": "UUID der Source (für remove/delete/bump_version)"
            },
            "include_inactive": {
                "type": "boolean",
                "default": False,
                "description": "Bei list: auch inaktive Sources anzeigen"
            }
        },
        "required": ["action"]
    }
}

INGEST_KNOWLEDGE_SCHEMA = {
    "name": "ingest_knowledge",
    "description": "Triggert die Ingestion von Knowledge Sources in die Wissensbasis (Qdrant). Kann eine spezifische Domain oder alle Domains ingesten.",
    "input_schema": {
        "type": "object",
        "properties": {
            "domain": {
                "type": "string",
                "description": "Spezifische Domain ingesten (z.B. 'linkedin', 'visualfox')"
            },
            "ingest_all": {
                "type": "boolean",
                "default": False,
                "description": "Wenn true, alle Domains ingesten"
            }
        },
        "required": []
    }
}

SEARCH_KNOWLEDGE_SCHEMA = {
    "name": "search_knowledge_base",
    "description": "Durchsucht alle Knowledge Bases nach relevantem Wissen. Kann optional nach Domain/Subdomain gefiltert werden.",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Suchanfrage in natürlicher Sprache"
            },
            "domain": {
                "type": "string",
                "description": "Optional: Filter nach Domain (z.B. 'linkedin', 'visualfox')"
            },
            "subdomain": {
                "type": "string",
                "description": "Optional: Filter nach Subdomain (z.B. 'strategy', 'brand')"
            },
            "top_k": {
                "type": "integer",
                "default": 8,
                "description": "Anzahl der Top-Ergebnisse"
            }
        },
        "required": ["query"]
    }
}
