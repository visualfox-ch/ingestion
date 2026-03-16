"""
Memory Hierarchy Tools - Phase B1 (AGI Evolution)

Tools for Jarvis to manage tiered memory (MemGPT-style):
- Store and recall memories
- Promote/demote between tiers
- Manage working context
- Search with importance weighting

Based on Packer et al. (2023) MemGPT.
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def store_memory(
    content: str,
    memory_key: str = None,
    tier: str = "longterm",
    content_type: str = "text",
    source: str = None,
    domain: str = None,
    tags: List[str] = None,
    importance: float = 0.5,
    **kwargs
) -> Dict[str, Any]:
    """
    Store a memory in the hierarchy.

    Args:
        content: The memory content to store
        memory_key: Unique key (auto-generated if not provided)
        tier: Target tier (working, recall, longterm, archive)
        content_type: Type (text, summary, fact, episode)
        source: Where this came from
        domain: Domain/category
        tags: Tags for organization
        importance: Importance 0-1 (default: 0.5)

    Returns:
        Dict with memory info
    """
    try:
        from app.services.memory_hierarchy_service import get_memory_hierarchy_service

        service = get_memory_hierarchy_service()
        return service.store_memory(
            content=content,
            memory_key=memory_key,
            tier=tier,
            content_type=content_type,
            source=source,
            domain=domain,
            tags=tags,
            importance=importance
        )

    except Exception as e:
        logger.error(f"Store memory failed: {e}")
        return {"success": False, "error": str(e)}


def recall_memory(
    memory_key: str = None,
    memory_id: int = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Recall a specific memory by key or ID.

    Args:
        memory_key: The memory key
        memory_id: The memory ID

    Returns:
        Dict with memory content and metadata
    """
    try:
        from app.services.memory_hierarchy_service import get_memory_hierarchy_service

        service = get_memory_hierarchy_service()
        return service.recall_memory(
            memory_key=memory_key,
            memory_id=memory_id
        )

    except Exception as e:
        logger.error(f"Recall memory failed: {e}")
        return {"success": False, "error": str(e)}


def search_memories(
    query: str = None,
    domain: str = None,
    tier: str = None,
    tags: List[str] = None,
    min_importance: float = None,
    limit: int = 20,
    **kwargs
) -> Dict[str, Any]:
    """
    Search memories with importance-weighted ranking.

    Args:
        query: Search text
        domain: Filter by domain
        tier: Filter by tier
        tags: Filter by tags
        min_importance: Minimum importance threshold
        limit: Max results (default: 20)

    Returns:
        Dict with matching memories
    """
    try:
        from app.services.memory_hierarchy_service import get_memory_hierarchy_service

        service = get_memory_hierarchy_service()
        return service.search_memories(
            query=query,
            domain=domain,
            tier=tier,
            tags=tags,
            min_importance=min_importance,
            limit=limit
        )

    except Exception as e:
        logger.error(f"Search memories failed: {e}")
        return {"success": False, "error": str(e)}


def promote_to_working(
    memory_keys: List[str] = None,
    query: str = None,
    domain: str = None,
    limit: int = 5,
    **kwargs
) -> Dict[str, Any]:
    """
    Load memories into working context for active use.

    Args:
        memory_keys: Specific keys to load
        query: Search query to find memories
        domain: Domain to filter by
        limit: Max memories to load (default: 5)

    Returns:
        Dict with loaded memory keys
    """
    try:
        from app.services.memory_hierarchy_service import get_memory_hierarchy_service

        service = get_memory_hierarchy_service()
        return service.load_to_working(
            memory_keys=memory_keys,
            query=query,
            domain=domain,
            limit=limit
        )

    except Exception as e:
        logger.error(f"Promote to working failed: {e}")
        return {"success": False, "error": str(e)}


def get_working_context(
    max_items: int = 20,
    **kwargs
) -> Dict[str, Any]:
    """
    Get current working context - most relevant active memories.

    Args:
        max_items: Maximum items to return (default: 20)

    Returns:
        Dict with working context memories
    """
    try:
        from app.services.memory_hierarchy_service import get_memory_hierarchy_service

        service = get_memory_hierarchy_service()
        return service.get_working_context(max_items=max_items)

    except Exception as e:
        logger.error(f"Get working context failed: {e}")
        return {"success": False, "error": str(e)}


def clear_working_context(
    demote_to: str = "recall",
    **kwargs
) -> Dict[str, Any]:
    """
    Clear working context by demoting all items.

    Args:
        demote_to: Target tier (default: recall)

    Returns:
        Dict with cleared count
    """
    try:
        from app.services.memory_hierarchy_service import get_memory_hierarchy_service

        service = get_memory_hierarchy_service()
        return service.clear_working(demote_to=demote_to)

    except Exception as e:
        logger.error(f"Clear working context failed: {e}")
        return {"success": False, "error": str(e)}


def demote_memory(
    memory_key: str,
    target_tier: str = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Demote a memory to a lower tier.

    Args:
        memory_key: The memory to demote
        target_tier: Target tier (default: next tier down)

    Returns:
        Dict with confirmation
    """
    try:
        from app.services.memory_hierarchy_service import get_memory_hierarchy_service

        service = get_memory_hierarchy_service()
        return service.demote_memory(
            memory_key=memory_key,
            target_tier=target_tier
        )

    except Exception as e:
        logger.error(f"Demote memory failed: {e}")
        return {"success": False, "error": str(e)}


def archive_memory(
    memory_key: str,
    **kwargs
) -> Dict[str, Any]:
    """
    Archive a memory (move to archive tier).

    Args:
        memory_key: The memory to archive

    Returns:
        Dict with confirmation
    """
    try:
        from app.services.memory_hierarchy_service import get_memory_hierarchy_service

        service = get_memory_hierarchy_service()
        return service.demote_memory(
            memory_key=memory_key,
            target_tier="archive"
        )

    except Exception as e:
        logger.error(f"Archive memory failed: {e}")
        return {"success": False, "error": str(e)}


def run_memory_maintenance(
    **kwargs
) -> Dict[str, Any]:
    """
    Run memory maintenance: decay scores, auto-demote old memories.

    Should be called periodically.

    Returns:
        Dict with maintenance stats
    """
    try:
        from app.services.memory_hierarchy_service import get_memory_hierarchy_service

        service = get_memory_hierarchy_service()
        return service.run_memory_maintenance()

    except Exception as e:
        logger.error(f"Run memory maintenance failed: {e}")
        return {"success": False, "error": str(e)}


def get_memory_stats(
    **kwargs
) -> Dict[str, Any]:
    """
    Get statistics about the memory hierarchy.

    Returns:
        Dict with tier counts, averages, etc.
    """
    try:
        from app.services.memory_hierarchy_service import get_memory_hierarchy_service

        service = get_memory_hierarchy_service()
        return service.get_memory_stats()

    except Exception as e:
        logger.error(f"Get memory stats failed: {e}")
        return {"success": False, "error": str(e)}


def create_session_summary(
    session_id: str,
    **kwargs
) -> Dict[str, Any]:
    """
    Create a summary of a session's memories.

    Args:
        session_id: The session to summarize

    Returns:
        Dict with summary and key facts
    """
    try:
        from app.services.memory_hierarchy_service import get_memory_hierarchy_service

        service = get_memory_hierarchy_service()
        return service.create_session_summary(session_id=session_id)

    except Exception as e:
        logger.error(f"Create session summary failed: {e}")
        return {"success": False, "error": str(e)}


# Tool definitions for Claude
MEMORY_HIERARCHY_TOOLS = [
    {
        "name": "store_memory",
        "description": "Store a memory in the hierarchy. Use for important information to remember.",
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The memory content to store"
                },
                "memory_key": {
                    "type": "string",
                    "description": "Unique key (auto-generated if not provided)"
                },
                "tier": {
                    "type": "string",
                    "enum": ["working", "recall", "longterm", "archive"],
                    "description": "Target tier (default: longterm)"
                },
                "content_type": {
                    "type": "string",
                    "enum": ["text", "summary", "fact", "episode"],
                    "description": "Type of content"
                },
                "domain": {
                    "type": "string",
                    "description": "Domain/category"
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tags for organization"
                },
                "importance": {
                    "type": "number",
                    "description": "Importance 0-1 (default: 0.5)"
                }
            },
            "required": ["content"]
        }
    },
    {
        "name": "recall_memory",
        "description": "Recall a specific memory by key or ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "memory_key": {
                    "type": "string",
                    "description": "The memory key"
                },
                "memory_id": {
                    "type": "integer",
                    "description": "The memory ID"
                }
            }
        }
    },
    {
        "name": "search_memories",
        "description": "Search memories with importance-weighted ranking.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search text"
                },
                "domain": {
                    "type": "string",
                    "description": "Filter by domain"
                },
                "tier": {
                    "type": "string",
                    "enum": ["working", "recall", "longterm", "archive"],
                    "description": "Filter by tier"
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter by tags"
                },
                "min_importance": {
                    "type": "number",
                    "description": "Minimum importance threshold"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default: 20)"
                }
            }
        }
    },
    {
        "name": "promote_to_working",
        "description": "Load memories into working context for active use.",
        "input_schema": {
            "type": "object",
            "properties": {
                "memory_keys": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Specific keys to load"
                },
                "query": {
                    "type": "string",
                    "description": "Search query to find memories"
                },
                "domain": {
                    "type": "string",
                    "description": "Domain to filter by"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max memories to load (default: 5)"
                }
            }
        }
    },
    {
        "name": "get_working_context",
        "description": "Get current working context - most relevant active memories.",
        "input_schema": {
            "type": "object",
            "properties": {
                "max_items": {
                    "type": "integer",
                    "description": "Maximum items (default: 20)"
                }
            }
        }
    },
    {
        "name": "clear_working_context",
        "description": "Clear working context by demoting all items.",
        "input_schema": {
            "type": "object",
            "properties": {
                "demote_to": {
                    "type": "string",
                    "enum": ["recall", "longterm", "archive"],
                    "description": "Target tier (default: recall)"
                }
            }
        }
    },
    {
        "name": "demote_memory",
        "description": "Demote a memory to a lower tier (e.g., working → recall).",
        "input_schema": {
            "type": "object",
            "properties": {
                "memory_key": {
                    "type": "string",
                    "description": "The memory to demote"
                },
                "target_tier": {
                    "type": "string",
                    "enum": ["recall", "longterm", "archive"],
                    "description": "Target tier"
                }
            },
            "required": ["memory_key"]
        }
    },
    {
        "name": "archive_memory",
        "description": "Archive a memory (permanent storage).",
        "input_schema": {
            "type": "object",
            "properties": {
                "memory_key": {
                    "type": "string",
                    "description": "The memory to archive"
                }
            },
            "required": ["memory_key"]
        }
    },
    {
        "name": "run_memory_maintenance",
        "description": "Run memory maintenance: decay scores, auto-demote old memories.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "get_memory_stats",
        "description": "Get statistics about the memory hierarchy.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "create_session_summary",
        "description": "Create a summary of a session's memories.",
        "input_schema": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "The session to summarize"
                }
            },
            "required": ["session_id"]
        }
    }
]
