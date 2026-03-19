"""
Jarvis Self-Knowledge Service

Stores and retrieves Jarvis's knowledge about itself in Qdrant.
This enables Jarvis to learn about his own capabilities without
hardcoding everything in the source code.

Collection: jarvis_self_knowledge (384 dims, cosine similarity)

Document types:
- tool_usage: How and when to use specific tools
- capability: What Jarvis can do
- limitation: What Jarvis cannot do
- pattern: Common query patterns and responses
- learning: Things Jarvis learned over time
"""

import json
import hashlib
from typing import Dict, List, Any, Optional
from datetime import datetime

from ..qdrant_upsert import ensure_collection, _client
from ..embed import embed_texts
from ..observability import get_logger, log_with_context, metrics

logger = get_logger("jarvis.self_knowledge")

COLLECTION_NAME = "jarvis_self_knowledge"
VECTOR_DIM = 384


def init_collection():
    """Initialize the self-knowledge collection if it doesn't exist."""
    try:
        ensure_collection(COLLECTION_NAME, VECTOR_DIM)
        log_with_context(logger, "info", "Self-knowledge collection initialized",
                        collection=COLLECTION_NAME)
        return True
    except Exception as e:
        log_with_context(logger, "error", "Failed to init self-knowledge collection",
                        error=str(e))
        return False


def _make_id(doc_type: str, key: str) -> str:
    """Generate deterministic ID from doc_type + key."""
    combined = f"{doc_type}::{key}"
    return hashlib.sha256(combined.encode()).hexdigest()[:32]


def store_knowledge(
    doc_type: str,
    key: str,
    content: str,
    metadata: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Store a piece of self-knowledge.

    Args:
        doc_type: Type of knowledge (tool_usage, capability, limitation, pattern, learning)
        key: Unique identifier within doc_type (e.g., tool name)
        content: The knowledge content (will be embedded)
        metadata: Additional metadata

    Returns:
        Dict with success status
    """
    try:
        ensure_collection(COLLECTION_NAME, VECTOR_DIM)

        # Create embedding
        embeddings = embed_texts([content])
        if not embeddings:
            return {"success": False, "error": "Failed to create embedding"}

        vector = embeddings[0]
        point_id = _make_id(doc_type, key)

        # Build payload
        payload = {
            "doc_type": doc_type,
            "key": key,
            "content": content,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        }
        if metadata:
            payload["metadata"] = metadata

        # Upsert to Qdrant
        from qdrant_client.models import PointStruct
        _client.upsert(
            collection_name=COLLECTION_NAME,
            points=[PointStruct(
                id=point_id,
                vector=vector,
                payload=payload
            )]
        )

        log_with_context(logger, "info", "Stored self-knowledge",
                        doc_type=doc_type, key=key)
        metrics.inc("self_knowledge_stored")

        return {"success": True, "id": point_id, "doc_type": doc_type, "key": key}

    except Exception as e:
        log_with_context(logger, "error", "Failed to store self-knowledge",
                        doc_type=doc_type, key=key, error=str(e))
        return {"success": False, "error": str(e)}


def query_knowledge(
    query: str,
    doc_type: Optional[str] = None,
    limit: int = 5,
    score_threshold: float = 0.3  # Lowered from 0.5 for better recall
) -> List[Dict[str, Any]]:
    """
    Query self-knowledge semantically.

    Args:
        query: Natural language query
        doc_type: Filter by doc_type (optional)
        limit: Max results
        score_threshold: Minimum similarity score

    Returns:
        List of matching knowledge entries
    """
    try:
        # Check if collection exists
        collections = [c.name for c in _client.get_collections().collections]
        if COLLECTION_NAME not in collections:
            log_with_context(logger, "warning", "Self-knowledge collection not found")
            return []

        # Create query embedding
        embeddings = embed_texts([query])
        if not embeddings:
            return []

        query_vector = embeddings[0]

        # Build filter if doc_type specified
        import os
        import requests
        QDRANT_HOST = os.environ.get("QDRANT_HOST", "qdrant")
        QDRANT_PORT = int(os.environ.get("QDRANT_PORT", "6333"))
        QDRANT_BASE = f"http://{QDRANT_HOST}:{QDRANT_PORT}"

        qdrant_filter = None
        if doc_type:
            qdrant_filter = {
                "must": [{"key": "doc_type", "match": {"value": doc_type}}]
            }

        # Search via REST API
        payload = {
            "vector": query_vector,
            "limit": limit,
            "with_payload": True,
            "score_threshold": score_threshold
        }
        if qdrant_filter:
            payload["filter"] = qdrant_filter

        r = requests.post(
            f"{QDRANT_BASE}/collections/{COLLECTION_NAME}/points/search",
            json=payload,
            timeout=30
        )

        if r.status_code != 200:
            log_with_context(logger, "error", "Qdrant search failed", status=r.status_code)
            return []

        results = r.json().get("result", [])
        metrics.inc("self_knowledge_queries")

        # Format results
        formatted = []
        for hit in results:
            payload_data = hit.get("payload", {})
            formatted.append({
                "score": hit.get("score"),
                "doc_type": payload_data.get("doc_type"),
                "key": payload_data.get("key"),
                "content": payload_data.get("content"),
                "metadata": payload_data.get("metadata"),
            })

        log_with_context(logger, "debug", "Self-knowledge query",
                        query=query[:50], results=len(formatted))

        return formatted

    except Exception as e:
        log_with_context(logger, "error", "Failed to query self-knowledge",
                        query=query[:50], error=str(e))
        return []


def get_tool_knowledge(tool_name: str) -> Optional[Dict[str, Any]]:
    """Get knowledge about a specific tool by name."""
    results = query_knowledge(
        query=f"tool {tool_name}",
        doc_type="tool_usage",
        limit=1,
        score_threshold=0.7
    )
    return results[0] if results else None


def populate_initial_knowledge() -> Dict[str, Any]:
    """
    Populate initial self-knowledge about tools and capabilities.
    Call this once to bootstrap Jarvis's self-awareness.
    """
    init_collection()

    stored = 0
    errors = 0

    # Tool usage knowledge
    tool_knowledge = [
        {
            "key": "self_introspection_tools",
            "content": """Tools: read_my_source_files, read_project_file, list_tasks
Zweck: Eigenen Code und aktuelle Aufgaben lesen.
KEYWORDS: code lesen, source code, eigenen code, tasks, aufgaben, todo

WANN NUTZEN:
- User fragt nach deinem Code -> read_my_source_files() oder read_project_file(file_path="...")
- User fragt nach konkreter Datei -> read_project_file(file_path="...")
- User fragt nach Tasks/Aufgaben -> list_tasks()

BEISPIELE:
"Lies deinen Code" -> read_my_source_files()
"Zeig mir deinen Source Code" -> read_my_source_files()
"Zeig mir app/agent.py" -> read_project_file(file_path="app/agent.py")
"Zeig mir deine Tasks" -> list_tasks()
"Was sind deine Aufgaben?" -> list_tasks()

WICHTIG: Du KANNST deinen eigenen Code und deine Tasks lesen. Nutze diese Tools.
""",
            "metadata": {"priority": "high", "category": "introspection"}
        },
        {
            "key": "list_available_tools",
            "content": """Tool: list_available_tools
Zweck: Liste alle verfügbaren Tools auf.

WANN NUTZEN:
- User fragt "Welche Tools hast du?"
- User fragt nach deinen Fähigkeiten
- Du bist unsicher welche Tools existieren
- Vor dem Aufrufen eines unbekannten Tools

BEISPIELE:
"Was kannst du alles?" → list_available_tools()
"Welche Tools gibt es?" → list_available_tools()
""",
            "metadata": {"priority": "high", "category": "introspection"}
        },
        {
            "key": "search_knowledge",
            "content": """Tool: search_knowledge
Zweck: Suche in Michas Wissensbasis (Emails, Chats, Dokumente).

WANN NUTZEN:
- User fragt nach Informationen über Personen, Projekte, Events
- User will etwas nachschlagen aus vergangenen Konversationen
- Semantische Suche nach Themen

BEISPIELE:
"Was weißt du über Projekt X?" → search_knowledge(query="Projekt X")
"Wer ist Person Y?" → search_knowledge(query="Person Y")
""",
            "metadata": {"priority": "high", "category": "knowledge"}
        },
        {
            "key": "recall_facts",
            "content": """Tool: recall_facts
Zweck: Rufe gespeicherte Fakten über den User ab.

WANN NUTZEN:
- User fragt nach seinen Präferenzen
- Du brauchst Kontext über den User
- User fragt "Weißt du noch...?"

BEISPIELE:
"Was sind meine Präferenzen?" → recall_facts()
"Kennst du mich?" → recall_facts()
""",
            "metadata": {"priority": "medium", "category": "memory"}
        },
        {
            "key": "introspect_capabilities",
            "content": """Tool: introspect_capabilities
Zweck: Zeige Jarvis Capability-Metadaten aus kanonischen Dateien.

WANN NUTZEN:
- User fragt nach einer Übersicht deiner Fähigkeiten
- Du brauchst technische Details über deine Capabilities
- ABER: Für Code-Lesen nutze lieber read_my_source_files oder read_project_file!

HINWEIS: Dieses Tool zeigt Metadaten, nicht den eigentlichen Code.
Für Code -> read_my_source_files() oder read_project_file(file_path="...")
""",
            "metadata": {"priority": "medium", "category": "introspection"}
        },
    ]

    for item in tool_knowledge:
        result = store_knowledge(
            doc_type="tool_usage",
            key=item["key"],
            content=item["content"],
            metadata=item.get("metadata")
        )
        if result.get("success"):
            stored += 1
        else:
            errors += 1

    # Capability knowledge
    capabilities = [
        {
            "key": "code_reading",
            "content": """Capability: Code-Lesen
Jarvis KANN seinen eigenen Code lesen!

Tools: read_my_source_files, read_project_file

WICHTIG: Wenn User nach Code fragt, NICHT sagen "Ich kann meinen Code nicht lesen".
Stattdessen: read_my_source_files() oder read_project_file(file_path="...") aufrufen.
""",
            "metadata": {"verified": True}
        },
        {
            "key": "task_reading",
            "content": """Capability: Tasks-Lesen
Jarvis KANN seine aktuellen Tasks lesen!

Tool: list_tasks()

WICHTIG: Wenn User nach Tasks fragt, dieses Tool nutzen.
""",
            "metadata": {"verified": True}
        },
    ]

    for item in capabilities:
        result = store_knowledge(
            doc_type="capability",
            key=item["key"],
            content=item["content"],
            metadata=item.get("metadata")
        )
        if result.get("success"):
            stored += 1
        else:
            errors += 1

    # Limitations
    limitations = [
        {
            "key": "no_internet_browsing",
            "content": """Limitation: Kein direktes Internet-Browsing
Jarvis kann NICHT direkt Webseiten besuchen.
Alternative: web_search Tool für Suchergebnisse nutzen.
""",
            "metadata": {}
        },
    ]

    for item in limitations:
        result = store_knowledge(
            doc_type="limitation",
            key=item["key"],
            content=item["content"],
            metadata=item.get("metadata")
        )
        if result.get("success"):
            stored += 1
        else:
            errors += 1

    log_with_context(logger, "info", "Initial self-knowledge populated",
                    stored=stored, errors=errors)

    return {
        "success": errors == 0,
        "stored": stored,
        "errors": errors
    }


def query_before_response(query: str) -> Optional[str]:
    """
    Query self-knowledge before generating a response.
    Returns relevant context to inject into the response.

    This is the main hook to be called from agent.py.
    """
    query_lower = query.lower()
    context_parts = []

    # === KEYWORD-BASED DIRECT INJECTION ===
    # For critical capabilities, inject knowledge directly based on keywords
    # This ensures Jarvis knows about his capabilities even if semantic search fails

    code_keywords = ["code", "agent", "source", "implementation", "wie funktionierst", "deinen code", "eigenen code"]
    task_keywords = ["task", "aufgabe", "todo", "was musst du", "deine tasks", "aktuellen tasks"]
    tool_keywords = ["tool", "fähigkeit", "capability", "was kannst du", "welche tools"]

    if any(kw in query_lower for kw in code_keywords):
        context_parts.append("""[WICHTIG - Code-Zugriff]
Du KANNST deinen eigenen Code lesen!
Tools: read_my_source_files() oder read_project_file(file_path="...")
NICHT sagen "Ich kann meinen Code nicht lesen" - stattdessen das Tool aufrufen!""")

    if any(kw in query_lower for kw in task_keywords):
        context_parts.append("""[WICHTIG - Task-Zugriff]
Du KANNST deine aktuellen Tasks lesen!
Tool: list_tasks()
NICHT sagen "Ich habe keine Task-Liste" - stattdessen das Tool aufrufen!""")

    if any(kw in query_lower for kw in tool_keywords):
        context_parts.append("""[WICHTIG - Tool-Liste]
Du KANNST deine verfügbaren Tools auflisten!
Tool: list_available_tools()
    Für Details zu Implementierungen: read_my_source_files() oder read_project_file(file_path="...")""")

    # === SEMANTIC SEARCH ===
    # Also query semantically for additional context
    results = query_knowledge(
        query=query,
        limit=3,
        score_threshold=0.35
    )

    for r in results:
        if r["score"] >= 0.4:
            context_parts.append(f"[Self-Knowledge ({r['doc_type']}/{r['key']}, score={r['score']:.2f})]\n{r['content']}")

    if context_parts:
        return "\n\n".join(context_parts)

    return None
