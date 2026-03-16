"""
Citation Tools (Phase S1).

Anti-Halluzination Layer: Tools for managing fact citations and verification.

Tools:
- cite_fact: Add a citation to a fact
- get_fact_citations: Get citations for a fact
- verify_fact: Mark a fact as verified
- get_verification_status: Check verification status
- request_fact_verification: Queue fact for manual review
- get_unverified_facts: List facts needing verification
- register_citation_source: Add/update a trusted source
- get_citation_stats: Get citation statistics
"""

import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)


# =============================================================================
# Tool Definitions
# =============================================================================

CITATION_TOOLS = [
    {
        "name": "cite_fact",
        "description": "Add a citation (source URL) to a fact. This links a fact to a verifiable source, improving its credibility. Use after research confirms a fact.",
        "parameters": {
            "type": "object",
            "properties": {
                "fact_id": {
                    "type": "string",
                    "description": "The ID of the fact to cite"
                },
                "url": {
                    "type": "string",
                    "description": "The source URL"
                },
                "title": {
                    "type": "string",
                    "description": "Title of the source (optional)"
                },
                "excerpt": {
                    "type": "string",
                    "description": "Relevant excerpt from the source (optional)"
                },
                "relevance_score": {
                    "type": "number",
                    "description": "How relevant is this source (0.0-1.0, default 0.5)"
                },
                "supports_fact": {
                    "type": "boolean",
                    "description": "Does this source support (true) or contradict (false) the fact? Default true"
                }
            },
            "required": ["fact_id", "url"]
        },
        "category": "citation"
    },
    {
        "name": "get_fact_citations",
        "description": "Get all citations (sources) for a specific fact. Shows URLs, trust scores, and whether sources support or contradict the fact.",
        "parameters": {
            "type": "object",
            "properties": {
                "fact_id": {
                    "type": "string",
                    "description": "The ID of the fact"
                }
            },
            "required": ["fact_id"]
        },
        "category": "citation"
    },
    {
        "name": "verify_fact",
        "description": "Manually mark a fact as verified. Use when you have confirmed the fact through reliable sources or user confirmation.",
        "parameters": {
            "type": "object",
            "properties": {
                "fact_id": {
                    "type": "string",
                    "description": "The ID of the fact to verify"
                },
                "verified_by": {
                    "type": "string",
                    "description": "Who verified it (e.g., 'user', 'jarvis', 'research')"
                }
            },
            "required": ["fact_id"]
        },
        "category": "citation"
    },
    {
        "name": "get_verification_status",
        "description": "Get the verification status of a fact. Shows if it's unverified, partially_verified, verified, or contradicted, plus citation counts.",
        "parameters": {
            "type": "object",
            "properties": {
                "fact_id": {
                    "type": "string",
                    "description": "The ID of the fact"
                }
            },
            "required": ["fact_id"]
        },
        "category": "citation"
    },
    {
        "name": "request_fact_verification",
        "description": "Queue a fact for manual verification. Use when a fact is important but unverified, or when there are conflicting sources.",
        "parameters": {
            "type": "object",
            "properties": {
                "fact_id": {
                    "type": "string",
                    "description": "The ID of the fact"
                },
                "reason": {
                    "type": "string",
                    "description": "Why verification is needed"
                },
                "priority": {
                    "type": "integer",
                    "description": "Priority level (higher = more urgent, default 0)"
                }
            },
            "required": ["fact_id"]
        },
        "category": "citation"
    },
    {
        "name": "get_unverified_facts",
        "description": "List facts that lack verification. Use to identify which facts need sources or confirmation.",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum number to return (default 20)"
                },
                "min_confidence": {
                    "type": "number",
                    "description": "Minimum confidence threshold (default 0.5)"
                }
            },
            "required": []
        },
        "category": "citation"
    },
    {
        "name": "get_conflicting_facts",
        "description": "List facts with conflicting citations. These facts have sources that contradict each other and need review.",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum number to return (default 20)"
                }
            },
            "required": []
        },
        "category": "citation"
    },
    {
        "name": "register_citation_source",
        "description": "Register or update a citation source with trust settings. Use to mark domains as trusted or adjust trust scores.",
        "parameters": {
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "The domain (e.g., 'wikipedia.org')"
                },
                "display_name": {
                    "type": "string",
                    "description": "Human-readable name (e.g., 'Wikipedia')"
                },
                "trust_score": {
                    "type": "number",
                    "description": "Trust level 0.0-1.0 (default 0.5)"
                },
                "source_type": {
                    "type": "string",
                    "enum": ["web", "academic", "official", "news", "social", "internal"],
                    "description": "Type of source"
                },
                "is_trusted": {
                    "type": "boolean",
                    "description": "Mark as trusted source (default false)"
                }
            },
            "required": ["domain"]
        },
        "category": "citation"
    },
    {
        "name": "get_citation_stats",
        "description": "Get overall citation statistics. Shows verification rates, source counts, and pending verifications.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        },
        "category": "citation"
    },
    {
        "name": "search_citations",
        "description": "Search citations by URL, title, or fact content. Find specific sources or facts.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results (default 20)"
                }
            },
            "required": ["query"]
        },
        "category": "citation"
    }
]


# =============================================================================
# Tool Handlers
# =============================================================================

def cite_fact(
    fact_id: str,
    url: str,
    title: str = None,
    excerpt: str = None,
    relevance_score: float = 0.5,
    supports_fact: bool = True,
    **kwargs
) -> Dict[str, Any]:
    """Add a citation to a fact."""
    try:
        from app.services.citation_service import get_citation_service
        service = get_citation_service()

        citation, new_status = service.add_citation(
            fact_id=fact_id,
            url=url,
            title=title,
            excerpt=excerpt,
            relevance_score=relevance_score,
            supports_fact=supports_fact,
            created_by="jarvis"
        )

        return {
            "success": True,
            "citation_id": citation.id,
            "fact_id": fact_id,
            "source_domain": citation.source_domain,
            "new_verification_status": new_status,
            "message": f"Citation added from {citation.source_domain}. Fact is now {new_status}."
        }
    except Exception as e:
        logger.error(f"cite_fact failed: {e}")
        return {"success": False, "error": str(e)}


def get_fact_citations(fact_id: str, **kwargs) -> Dict[str, Any]:
    """Get citations for a fact."""
    try:
        from app.services.citation_service import get_citation_service
        service = get_citation_service()

        citations = service.get_citations(fact_id)

        return {
            "fact_id": fact_id,
            "citation_count": len(citations),
            "citations": [
                {
                    "id": c.id,
                    "url": c.url,
                    "title": c.title,
                    "excerpt": c.excerpt,
                    "source_domain": c.source_domain,
                    "trust_score": c.source_trust,
                    "relevance_score": c.relevance_score,
                    "supports_fact": c.supports_fact,
                    "access_date": c.access_date.isoformat() if c.access_date else None
                }
                for c in citations
            ]
        }
    except Exception as e:
        logger.error(f"get_fact_citations failed: {e}")
        return {"error": str(e)}


def verify_fact(fact_id: str, verified_by: str = "jarvis", **kwargs) -> Dict[str, Any]:
    """Mark a fact as verified."""
    try:
        from app.services.citation_service import get_citation_service
        service = get_citation_service()

        status = service.mark_verified(fact_id, verified_by)

        return {
            "success": True,
            "fact_id": fact_id,
            "verification_status": status,
            "verified_by": verified_by,
            "message": f"Fact {fact_id} marked as verified by {verified_by}."
        }
    except Exception as e:
        logger.error(f"verify_fact failed: {e}")
        return {"success": False, "error": str(e)}


def get_verification_status(fact_id: str, **kwargs) -> Dict[str, Any]:
    """Get verification status of a fact."""
    try:
        from app.services.citation_service import get_citation_service
        service = get_citation_service()
        return service.get_verification_status(fact_id)
    except Exception as e:
        logger.error(f"get_verification_status failed: {e}")
        return {"error": str(e)}


def request_fact_verification(
    fact_id: str,
    reason: str = None,
    priority: int = 0,
    **kwargs
) -> Dict[str, Any]:
    """Queue fact for manual verification."""
    try:
        from app.services.citation_service import get_citation_service
        service = get_citation_service()

        request_id = service.request_verification(
            fact_id=fact_id,
            reason=reason,
            priority=priority
        )

        return {
            "success": True,
            "request_id": request_id,
            "fact_id": fact_id,
            "message": "Fact queued for manual verification."
        }
    except Exception as e:
        logger.error(f"request_fact_verification failed: {e}")
        return {"success": False, "error": str(e)}


def get_unverified_facts(
    limit: int = 20,
    min_confidence: float = 0.5,
    **kwargs
) -> Dict[str, Any]:
    """List unverified facts."""
    try:
        from app.services.citation_service import get_citation_service
        service = get_citation_service()

        facts = service.get_unverified_facts(limit=limit, min_confidence=min_confidence)

        return {
            "count": len(facts),
            "facts": facts
        }
    except Exception as e:
        logger.error(f"get_unverified_facts failed: {e}")
        return {"error": str(e)}


def get_conflicting_facts(limit: int = 20, **kwargs) -> Dict[str, Any]:
    """List facts with conflicting citations."""
    try:
        from app.services.citation_service import get_citation_service
        service = get_citation_service()

        facts = service.get_conflicting_facts(limit=limit)

        return {
            "count": len(facts),
            "facts": facts,
            "message": f"Found {len(facts)} facts with conflicting sources. These need manual review."
        }
    except Exception as e:
        logger.error(f"get_conflicting_facts failed: {e}")
        return {"error": str(e)}


def register_citation_source(
    domain: str,
    display_name: str = None,
    trust_score: float = 0.5,
    source_type: str = "web",
    is_trusted: bool = False,
    **kwargs
) -> Dict[str, Any]:
    """Register or update a citation source."""
    try:
        from app.services.citation_service import get_citation_service
        service = get_citation_service()

        source = service.register_source(
            domain=domain,
            display_name=display_name,
            trust_score=trust_score,
            source_type=source_type,
            is_trusted=is_trusted
        )

        return {
            "success": True,
            "source_id": source.id,
            "domain": source.domain,
            "trust_score": source.trust_score,
            "is_trusted": source.is_trusted,
            "message": f"Source {source.domain} registered with trust score {source.trust_score}."
        }
    except Exception as e:
        logger.error(f"register_citation_source failed: {e}")
        return {"success": False, "error": str(e)}


def get_citation_stats(**kwargs) -> Dict[str, Any]:
    """Get citation statistics."""
    try:
        from app.services.citation_service import get_citation_service
        service = get_citation_service()
        return service.get_citation_stats()
    except Exception as e:
        logger.error(f"get_citation_stats failed: {e}")
        return {"error": str(e)}


def search_citations(query: str, limit: int = 20, **kwargs) -> Dict[str, Any]:
    """Search citations."""
    try:
        from app.services.citation_service import get_citation_service
        service = get_citation_service()

        results = service.search_citations(query=query, limit=limit)

        return {
            "query": query,
            "count": len(results),
            "results": results
        }
    except Exception as e:
        logger.error(f"search_citations failed: {e}")
        return {"error": str(e)}


def get_citation_tools() -> List[Dict]:
    """Get all citation tool definitions."""
    return CITATION_TOOLS
