"""
Knowledge Tools — API Context Pack access for Jarvis agents

Provides curated, version-pinned API context packs for coding agents:
- list_api_context_packs: list available packs with optional filter
- read_api_context_pack: read a specific pack section (content, annotations, snapshot)
- search_api_context_packs: keyword search across all packs

Packs live in docs/knowledge/api_context/<provider>/<doc_slug>/<lang>/.
"""

from typing import Dict, Any, List, Optional
import logging

logger = logging.getLogger("jarvis.tools.knowledge")

try:
    from ..logging_utils import log_with_context
except ImportError:
    def log_with_context(logger, level, msg, **kwargs):
        getattr(logger, level)(f"{msg} {kwargs}")


# ============ Tool Definitions ============

KNOWLEDGE_TOOLS = [
    {
        "name": "list_api_context_packs",
        "description": (
            "List all available API context packs. Each pack contains curated, "
            "version-pinned API knowledge with Jarvis-specific annotations and gotchas. "
            "Available packs include: anthropic/messages-api, openai/responses-api, "
            "n8n/workflows-api, fastapi/reference, elevenlabs/tts, googleworkspace/cli. "
            "Use this tool to discover what API context is available before reading."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "provider": {
                    "type": "string",
                    "description": "Filter by provider name (e.g. 'anthropic', 'openai', 'n8n', 'fastapi')",
                },
                "language": {
                    "type": "string",
                    "description": "Filter by language (e.g. 'py', 'shell')",
                },
            },
            "required": [],
        },
    },
    {
        "name": "read_api_context_pack",
        "description": (
            "Read a specific API context pack. Returns curated API documentation "
            "with Jarvis-specific gotchas, verified patterns, and local annotations. "
            "Prefer 'snapshot' (default) for a complete merged view, or 'annotations' "
            "for just the Jarvis-specific gotchas. Use this before writing code that "
            "calls an external API to avoid known failure modes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "provider": {
                    "type": "string",
                    "description": "Provider name, e.g. 'anthropic', 'openai', 'n8n', 'fastapi', 'elevenlabs'",
                },
                "doc_slug": {
                    "type": "string",
                    "description": "Document slug, e.g. 'messages-api', 'responses-api', 'workflows-api', 'reference', 'tts'",
                },
                "language": {
                    "type": "string",
                    "description": "Language variant: 'py' (default) or 'shell'",
                    "default": "py",
                },
                "section": {
                    "type": "string",
                    "description": "Section to read: 'snapshot' (full merged, default), 'content' (curated docs), 'annotations' (Jarvis gotchas), 'manifest' (metadata), 'all'",
                    "default": "snapshot",
                },
            },
            "required": ["provider", "doc_slug"],
        },
    },
    {
        "name": "search_api_context_packs",
        "description": (
            "Search across all API context packs by keyword. Returns ranked results "
            "with excerpts showing where the match was found. Use this when you know "
            "what API concept you're looking for but not which provider/pack. "
            "Example queries: 'tool_use stop_reason', 'webhook respond immediately', "
            "'system prompt multi-turn', 'asyncpg positional params'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query — keywords or short phrase to find in API context packs",
                },
                "provider": {
                    "type": "string",
                    "description": "Optional: restrict search to a specific provider",
                },
                "language": {
                    "type": "string",
                    "description": "Optional: restrict search to a specific language ('py', 'shell')",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default: 5)",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    },
]


# ============ Tool Implementations ============

def tool_list_api_context_packs(
    provider: Optional[str] = None,
    language: Optional[str] = None,
) -> Dict[str, Any]:
    try:
        from ..services.api_context_packs import list_api_context_packs
        packs = list_api_context_packs(provider=provider, language=language)
        log_with_context(logger, "info", "list_api_context_packs", count=len(packs))
        return {"success": True, "count": len(packs), "packs": packs}
    except Exception as e:
        log_with_context(logger, "error", "list_api_context_packs failed", error=str(e))
        return {"success": False, "error": str(e)}


def tool_read_api_context_pack(
    provider: str,
    doc_slug: str,
    language: str = "py",
    section: str = "snapshot",
) -> Dict[str, Any]:
    try:
        from ..services.api_context_packs import read_api_context_pack
        result = read_api_context_pack(
            provider=provider, doc_slug=doc_slug, language=language, section=section
        )
        log_with_context(
            logger, "info", "read_api_context_pack",
            provider=provider, doc_slug=doc_slug, section=section,
            success=result.get("success"),
        )
        return result
    except Exception as e:
        log_with_context(logger, "error", "read_api_context_pack failed", error=str(e))
        return {"success": False, "error": str(e)}


def tool_search_api_context_packs(
    query: str,
    provider: Optional[str] = None,
    language: Optional[str] = None,
    limit: int = 5,
) -> Dict[str, Any]:
    try:
        from ..services.api_context_packs import search_api_context_packs
        result = search_api_context_packs(
            query=query, provider=provider, language=language, limit=limit
        )
        log_with_context(
            logger, "info", "search_api_context_packs",
            query=query, count=result.get("count", 0),
        )
        return result
    except Exception as e:
        log_with_context(logger, "error", "search_api_context_packs failed", error=str(e))
        return {"success": False, "error": str(e)}
