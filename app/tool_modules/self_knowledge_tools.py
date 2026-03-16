"""
Jarvis Self-Knowledge Tools - Tier 1 Evolution

Internal self-model that allows Jarvis to:
- Know his own architecture, capabilities, limits
- Track known issues and improvements
- Update self-knowledge based on observations
- Query his own structure for context-aware responses
"""

import os
import json
import logging
import requests
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Qdrant connection (REST API)
QDRANT_HOST = os.getenv("QDRANT_HOST", "qdrant")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
QDRANT_BASE = f"http://{QDRANT_HOST}:{QDRANT_PORT}"
COLLECTION_NAME = "jarvis_self_model"
VECTOR_SIZE = 384  # bge-small-en-v1.5

# Knowledge categories
CATEGORIES = [
    "architecture",      # System architecture, services, containers
    "capabilities",      # What Jarvis can do (tools, integrations)
    "limitations",       # Known limitations, constraints
    "configuration",     # Current config, settings, thresholds
    "known_issues",      # Bugs, problems, workarounds
    "improvements",      # Planned or suggested improvements
    "metrics",           # Performance baselines, SLOs
    "relationships",     # Integrations with external systems
]


def _ensure_collection() -> bool:
    """Ensure the self-model collection exists via REST API."""
    try:
        # Check if collection exists
        r = requests.get(f"{QDRANT_BASE}/collections/{COLLECTION_NAME}", timeout=10)
        if r.status_code == 200:
            return True

        # Create collection
        create_payload = {
            "vectors": {
                "size": VECTOR_SIZE,
                "distance": "Cosine"
            }
        }
        r = requests.put(
            f"{QDRANT_BASE}/collections/{COLLECTION_NAME}",
            json=create_payload,
            timeout=30
        )
        if r.status_code in [200, 201]:
            logger.info(f"Created collection: {COLLECTION_NAME}")
            # Seed initial knowledge
            _seed_initial_knowledge()
            return True
        else:
            logger.error(f"Failed to create collection: {r.text}")
            return False

    except Exception as e:
        logger.error(f"_ensure_collection error: {e}")
        return False


def _get_embedding(text: str) -> List[float]:
    """Get embedding for text using the shared embed function."""
    try:
        from ..embed import embed_texts
        embeddings = embed_texts([text])
        return embeddings[0] if embeddings else [0.0] * VECTOR_SIZE
    except Exception as e:
        logger.error(f"Embedding error: {e}")
        return [0.0] * VECTOR_SIZE


def _seed_initial_knowledge():
    """Seed the collection with initial self-knowledge via REST API."""
    initial_knowledge = [
        {
            "id": "arch_overview",
            "category": "architecture",
            "title": "Jarvis System Overview",
            "content": "Jarvis is a personal AI assistant running on a Synology NAS. Core components: FastAPI backend (port 18000), PostgreSQL, Qdrant, Meilisearch, Redis. Observability: Prometheus (19090), Loki (13100), Grafana (13000), Langfuse. Automation: n8n workflows (25678), Telegram bot integration.",
            "metadata": {"version": "1.0"}
        },
        {
            "id": "arch_containers",
            "category": "architecture",
            "title": "Docker Container Structure",
            "content": "Key containers: jarvis-ingestion (FastAPI), jarvis-postgres (PostgreSQL 15), jarvis-qdrant (Vector DB), jarvis-meilisearch (Full-text), jarvis-redis (Cache), jarvis-n8n (Workflows), jarvis-prometheus/loki/grafana (Observability), jarvis-langfuse (LLM tracing).",
            "metadata": {"container_count": 20}
        },
        {
            "id": "cap_tools",
            "category": "capabilities",
            "title": "Available Tool Categories",
            "content": "Tool categories: Knowledge & Search, Calendar, Communication (Email), Research (Perplexity/Tavily/DuckDuckGo), Monitoring (Prometheus/Loki), Self-Modification, Identity & Learning, Visualization (Diagrams/DALL-E).",
            "metadata": {"tool_count": 80}
        },
        {
            "id": "cap_llm",
            "category": "capabilities",
            "title": "LLM Providers",
            "content": "Available LLM providers: Anthropic Claude (primary: claude-sonnet-4, claude-opus-4), OpenAI (gpt-4o, gpt-4o-mini), Ollama (local). Model selection is automatic based on task complexity and cost.",
            "metadata": {"primary_model": "claude-sonnet-4-20250514"}
        },
        {
            "id": "limit_rate",
            "category": "limitations",
            "title": "Rate Limits",
            "content": "Known rate limits: Perplexity API (rate limited, auto-fallback to Tavily), Tavily API (400 char query limit), Anthropic API (token limits), Telegram (4096 char message limit).",
            "metadata": {}
        },
        {
            "id": "limit_context",
            "category": "limitations",
            "title": "Context Window Constraints",
            "content": "Context management: Claude Sonnet has 200k token context. System prompt + tools use ~15k tokens baseline. RAG results configurable (5-10 chunks default). Conversation history auto-summarized when approaching limits.",
            "metadata": {}
        },
        {
            "id": "config_proactivity",
            "category": "configuration",
            "title": "Proactivity Settings",
            "content": "Proactivity configuration: JARVIS_PROACTIVE_LEVEL=4 (1=silent, 5=aggressive), JARVIS_PROACTIVE_CONFIDENCE_THRESHOLD=0.5. Controls how often Jarvis offers unsolicited suggestions.",
            "metadata": {"level": 4, "threshold": 0.5}
        },
        {
            "id": "metrics_baseline",
            "category": "metrics",
            "title": "Performance Baselines",
            "content": "Normal operating parameters: API response <500ms (simple) to <5s (with tools), Error rate <1%, Memory ~40-50%, Tool success >95%, RAG retrieval <200ms.",
            "metadata": {}
        },
        {
            "id": "issue_tavily_length",
            "category": "known_issues",
            "title": "Tavily Query Length Issue",
            "content": "Issue: Tavily API rejects queries >400 characters. Workaround: Queries automatically truncated to first line, max 380 chars. Status: Mitigated in research_tools.py.",
            "metadata": {"severity": "low", "status": "mitigated"}
        },
    ]

    points = []
    for i, item in enumerate(initial_knowledge):
        embedding = _get_embedding(f"{item['title']} {item['content']}")
        points.append({
            "id": i + 1,
            "vector": embedding,
            "payload": {
                "knowledge_id": item["id"],
                "category": item["category"],
                "title": item["title"],
                "content": item["content"],
                "metadata": item.get("metadata", {}),
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
                "source": "initial_seed"
            }
        })

    if points:
        try:
            r = requests.put(
                f"{QDRANT_BASE}/collections/{COLLECTION_NAME}/points",
                json={"points": points},
                timeout=30
            )
            if r.status_code in [200, 201]:
                logger.info(f"Seeded {len(points)} initial knowledge items")
            else:
                logger.error(f"Failed to seed knowledge: {r.text}")
        except Exception as e:
            logger.error(f"Seed error: {e}")


def get_self_knowledge(
    category: Optional[str] = None,
    query: Optional[str] = None,
    limit: int = 5
) -> Dict[str, Any]:
    """
    Retrieve Jarvis's self-knowledge.

    Args:
        category: Filter by category (architecture, capabilities, limitations, etc.)
        query: Semantic search query
        limit: Max results to return

    Returns:
        Dict with matching knowledge items
    """
    try:
        _ensure_collection()

        # Build filter for Qdrant REST API
        qdrant_filter = None
        if category and category in CATEGORIES:
            qdrant_filter = {
                "must": [{"key": "category", "match": {"value": category}}]
            }

        if query:
            # Semantic search via REST
            embedding = _get_embedding(query)
            payload = {
                "vector": embedding,
                "limit": limit,
                "with_payload": True
            }
            if qdrant_filter:
                payload["filter"] = qdrant_filter

            r = requests.post(
                f"{QDRANT_BASE}/collections/{COLLECTION_NAME}/points/search",
                json=payload,
                timeout=30
            )
            if r.status_code != 200:
                return {"success": False, "error": f"Search failed: {r.text}"}

            data = r.json()
            results = data.get("result", [])
        else:
            # Scroll through category via REST
            payload = {"limit": limit, "with_payload": True}
            if qdrant_filter:
                payload["filter"] = qdrant_filter

            r = requests.post(
                f"{QDRANT_BASE}/collections/{COLLECTION_NAME}/points/scroll",
                json=payload,
                timeout=30
            )
            if r.status_code != 200:
                return {"success": False, "error": f"Scroll failed: {r.text}"}

            data = r.json()
            results = data.get("result", {}).get("points", [])

        items = []
        for hit in results:
            payload = hit.get("payload", {})
            items.append({
                "id": payload.get("knowledge_id"),
                "category": payload.get("category"),
                "title": payload.get("title"),
                "content": payload.get("content"),
                "metadata": payload.get("metadata", {}),
                "score": hit.get("score")
            })

        return {
            "success": True,
            "category": category,
            "query": query,
            "count": len(items),
            "items": items,
            "available_categories": CATEGORIES
        }

    except Exception as e:
        logger.error(f"get_self_knowledge error: {e}")
        return {"success": False, "error": str(e)}


def update_self_knowledge(
    knowledge_id: str,
    title: str,
    content: str,
    category: str,
    metadata: Optional[Dict[str, Any]] = None,
    source: str = "manual"
) -> Dict[str, Any]:
    """
    Update or create self-knowledge entry.

    Args:
        knowledge_id: Unique identifier (e.g., 'arch_overview', 'issue_xyz')
        title: Short title
        content: Detailed content
        category: One of the valid categories
        metadata: Additional structured data
        source: Who/what created this (manual, self_monitoring, observation)

    Returns:
        Dict with operation result
    """
    try:
        if category not in CATEGORIES:
            return {
                "success": False,
                "error": f"Invalid category. Must be one of: {CATEGORIES}"
            }

        _ensure_collection()

        # Check if exists via REST
        scroll_payload = {
            "filter": {"must": [{"key": "knowledge_id", "match": {"value": knowledge_id}}]},
            "limit": 1,
            "with_payload": True
        }
        r = requests.post(
            f"{QDRANT_BASE}/collections/{COLLECTION_NAME}/points/scroll",
            json=scroll_payload,
            timeout=30
        )
        existing = []
        if r.status_code == 200:
            data = r.json()
            existing = data.get("result", {}).get("points", [])

        # Generate embedding
        embedding = _get_embedding(f"{title} {content}")

        # Determine point ID
        if existing:
            point_id = existing[0]["id"]
            created_at = existing[0].get("payload", {}).get("created_at", datetime.now().isoformat())
        else:
            # Get max ID via scroll
            r = requests.post(
                f"{QDRANT_BASE}/collections/{COLLECTION_NAME}/points/scroll",
                json={"limit": 1000, "with_payload": False},
                timeout=30
            )
            all_ids = []
            if r.status_code == 200:
                points = r.json().get("result", {}).get("points", [])
                all_ids = [p["id"] for p in points if isinstance(p.get("id"), int)]
            point_id = max(all_ids, default=0) + 1
            created_at = datetime.now().isoformat()

        point = {
            "id": point_id,
            "vector": embedding,
            "payload": {
                "knowledge_id": knowledge_id,
                "category": category,
                "title": title,
                "content": content,
                "metadata": metadata or {},
                "created_at": created_at,
                "updated_at": datetime.now().isoformat(),
                "source": source
            }
        }

        r = requests.put(
            f"{QDRANT_BASE}/collections/{COLLECTION_NAME}/points",
            json={"points": [point]},
            timeout=30
        )

        if r.status_code not in [200, 201]:
            return {"success": False, "error": f"Upsert failed: {r.text}"}

        return {
            "success": True,
            "action": "updated" if existing else "created",
            "knowledge_id": knowledge_id,
            "category": category,
            "title": title
        }

    except Exception as e:
        logger.error(f"update_self_knowledge error: {e}")
        return {"success": False, "error": str(e)}


def query_architecture(
    component: Optional[str] = None,
    include_metrics: bool = False
) -> Dict[str, Any]:
    """
    Query Jarvis's architecture knowledge.

    Args:
        component: Specific component to query (e.g., 'qdrant', 'postgres', 'n8n')
        include_metrics: Include current metrics for components

    Returns:
        Dict with architecture information
    """
    try:
        # Get architecture knowledge
        arch_result = get_self_knowledge(category="architecture")
        cap_result = get_self_knowledge(category="capabilities")

        architecture = {
            "success": True,
            "timestamp": datetime.now().isoformat(),
            "overview": None,
            "components": [],
            "capabilities": []
        }

        # Extract overview
        for item in arch_result.get("items", []):
            if item["id"] == "arch_overview":
                architecture["overview"] = item["content"]
            elif component is None or component.lower() in item["content"].lower():
                architecture["components"].append({
                    "title": item["title"],
                    "content": item["content"]
                })

        # Add capabilities
        for item in cap_result.get("items", []):
            architecture["capabilities"].append({
                "title": item["title"],
                "content": item["content"]
            })

        # Optionally include live metrics
        if include_metrics:
            try:
                from .monitoring_tools import get_monitoring_status
                architecture["current_metrics"] = get_monitoring_status()
            except Exception as e:
                architecture["current_metrics"] = {"error": str(e)}

        return architecture

    except Exception as e:
        logger.error(f"query_architecture error: {e}")
        return {"success": False, "error": str(e)}


def get_known_issues(
    status: Optional[str] = None,
    severity: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get known issues and their status.

    Args:
        status: Filter by status (open, mitigated, resolved)
        severity: Filter by severity (low, medium, high, critical)

    Returns:
        Dict with known issues
    """
    try:
        result = get_self_knowledge(category="known_issues", limit=50)

        issues = []
        for item in result.get("items", []):
            meta = item.get("metadata", {})

            # Apply filters
            if status and meta.get("status") != status:
                continue
            if severity and meta.get("severity") != severity:
                continue

            issues.append({
                "id": item["id"],
                "title": item["title"],
                "content": item["content"],
                "severity": meta.get("severity", "unknown"),
                "status": meta.get("status", "unknown"),
                "updated": meta.get("updated")
            })

        return {
            "success": True,
            "count": len(issues),
            "issues": issues,
            "filters": {"status": status, "severity": severity}
        }

    except Exception as e:
        logger.error(f"get_known_issues error: {e}")
        return {"success": False, "error": str(e)}


def record_observation(
    observation_type: str,
    title: str,
    content: str,
    severity: str = "info",
    suggested_action: Optional[str] = None
) -> Dict[str, Any]:
    """
    Record a self-observation (used by monitoring agents).

    Args:
        observation_type: Type (anomaly, degradation, improvement_opportunity)
        title: Short description
        content: Detailed observation
        severity: info, warning, error, critical
        suggested_action: What should be done

    Returns:
        Dict with operation result
    """
    try:
        # Determine category based on type
        if observation_type in ["anomaly", "degradation", "error"]:
            category = "known_issues"
            status = "open"
        else:
            category = "improvements"
            status = "suggested"

        # Generate unique ID
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        knowledge_id = f"obs_{observation_type}_{timestamp}"

        result = update_self_knowledge(
            knowledge_id=knowledge_id,
            title=title,
            content=content,
            category=category,
            metadata={
                "observation_type": observation_type,
                "severity": severity,
                "status": status,
                "suggested_action": suggested_action,
                "recorded_at": datetime.now().isoformat()
            },
            source="self_monitoring"
        )

        return result

    except Exception as e:
        logger.error(f"record_observation error: {e}")
        return {"success": False, "error": str(e)}


# Tool definitions for Claude (JSON-serializable)
SELF_KNOWLEDGE_TOOLS = [
    {
        "name": "get_self_knowledge",
        "description": "Retrieve Jarvis's internal self-knowledge about architecture, capabilities, limitations, or known issues.",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": CATEGORIES,
                    "description": "Filter by knowledge category"
                },
                "query": {
                    "type": "string",
                    "description": "Semantic search query"
                },
                "limit": {
                    "type": "integer",
                    "default": 5,
                    "description": "Max results"
                }
            }
        }
    },
    {
        "name": "update_self_knowledge",
        "description": "Update or create a self-knowledge entry. Used to maintain Jarvis's internal model.",
        "input_schema": {
            "type": "object",
            "properties": {
                "knowledge_id": {
                    "type": "string",
                    "description": "Unique identifier (e.g., 'arch_overview', 'issue_xyz')"
                },
                "title": {"type": "string", "description": "Short title"},
                "content": {"type": "string", "description": "Detailed content"},
                "category": {
                    "type": "string",
                    "enum": CATEGORIES,
                    "description": "Knowledge category"
                },
                "metadata": {
                    "type": "object",
                    "description": "Additional structured data"
                }
            },
            "required": ["knowledge_id", "title", "content", "category"]
        }
    },
    {
        "name": "query_architecture",
        "description": "Query Jarvis's architecture - components, capabilities, and optionally current metrics.",
        "input_schema": {
            "type": "object",
            "properties": {
                "component": {
                    "type": "string",
                    "description": "Specific component to query (e.g., 'qdrant', 'postgres')"
                },
                "include_metrics": {
                    "type": "boolean",
                    "default": False,
                    "description": "Include current live metrics"
                }
            }
        }
    },
    {
        "name": "get_known_issues",
        "description": "Get known issues and their current status.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["open", "mitigated", "resolved"],
                    "description": "Filter by issue status"
                },
                "severity": {
                    "type": "string",
                    "enum": ["low", "medium", "high", "critical"],
                    "description": "Filter by severity"
                }
            }
        }
    },
    {
        "name": "record_observation",
        "description": "Record a self-observation from monitoring. Creates knowledge entries for issues or improvements.",
        "input_schema": {
            "type": "object",
            "properties": {
                "observation_type": {
                    "type": "string",
                    "enum": ["anomaly", "degradation", "error", "improvement_opportunity"],
                    "description": "Type of observation"
                },
                "title": {"type": "string", "description": "Short description"},
                "content": {"type": "string", "description": "Detailed observation"},
                "severity": {
                    "type": "string",
                    "enum": ["info", "warning", "error", "critical"],
                    "default": "info"
                },
                "suggested_action": {
                    "type": "string",
                    "description": "Recommended action"
                }
            },
            "required": ["observation_type", "title", "content"]
        }
    }
]
