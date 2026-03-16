"""
Research Tools for Jarvis.

Enables Jarvis to execute research via multiple providers:
- Perplexity/Sonar Pro (AI-powered search with citations)
- Tavily (fast web search API)
- DuckDuckGo (free fallback)
"""

import logging
import uuid
import os
from typing import Dict, Any, List, Optional
from datetime import datetime
import json

from app.postgres_state import get_conn

logger = logging.getLogger(__name__)

# Provider priorities for auto-selection
PROVIDER_PRIORITY = ["perplexity", "tavily", "duckduckgo"]


def _get_available_providers() -> List[Dict[str, Any]]:
    """Check which research providers are available."""
    providers = []

    # Check Perplexity
    if os.environ.get("PERPLEXITY_API_KEY"):
        providers.append({
            "name": "perplexity",
            "available": True,
            "quality": "high",
            "description": "AI-powered search with citations"
        })

    # Check Tavily
    if os.environ.get("TAVILY_API_KEY"):
        providers.append({
            "name": "tavily",
            "available": True,
            "quality": "medium",
            "description": "Fast web search API"
        })

    # DuckDuckGo is always available (no API key needed)
    providers.append({
        "name": "duckduckgo",
        "available": True,
        "quality": "basic",
        "description": "Free web search fallback"
    })

    return providers


def _select_provider(preferred: Optional[str] = None) -> str:
    """Select the best available provider."""
    available = _get_available_providers()
    available_names = [p["name"] for p in available]

    # If preferred provider is specified and available, use it
    if preferred and preferred in available_names:
        return preferred

    # Otherwise select by priority
    for provider in PROVIDER_PRIORITY:
        if provider in available_names:
            return provider

    return "duckduckgo"  # Always available


def run_research(
    domain: str,
    topics: Optional[List[str]] = None,
    context: Optional[str] = None,
    provider: Optional[str] = None
) -> Dict[str, Any]:
    """
    Execute research for a domain using available search providers.

    Args:
        domain: Domain name (e.g., 'ai_tools')
        topics: Optional specific topics to research (default: all active topics)
        context: Additional context for the research queries
        provider: Preferred provider ('perplexity', 'tavily', 'duckduckgo', or None for auto)

    Returns:
        Research session results with items found
    """
    try:
        # Select provider
        selected_provider = _select_provider(provider)
        logger.info(f"Research using provider: {selected_provider}")

        # Load domain config
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """SELECT id, name, display_name, prompt_template, search_recency_filter,
                          default_model, max_tokens, temperature
                   FROM research_domains WHERE name = %s AND is_active = TRUE""",
                (domain,)
            )
            domain_row = cur.fetchone()
            if not domain_row:
                return {"success": False, "error": f"Domain '{domain}' not found or inactive"}

            domain_id = domain_row["id"]
            prompt_template = domain_row["prompt_template"]
            recency = domain_row["search_recency_filter"] or "week"
            model = domain_row["default_model"] or "sonar-pro"
            max_tokens = domain_row["max_tokens"] or 4096

            # Load topics
            if topics:
                cur.execute(
                    """SELECT id, name, context, query_template, search_recency_filter
                       FROM research_topics
                       WHERE domain_id = %s AND name = ANY(%s) AND is_active = TRUE""",
                    (domain_id, topics)
                )
            else:
                cur.execute(
                    """SELECT id, name, context, query_template, search_recency_filter
                       FROM research_topics
                       WHERE domain_id = %s AND is_active = TRUE
                       ORDER BY priority DESC LIMIT 5""",
                    (domain_id,)
                )
            topic_rows = cur.fetchall()

            if not topic_rows:
                return {"success": False, "error": "No active topics found"}

        # Create research session
        session_id = str(uuid.uuid4())
        results = []
        errors = []

        # Research each topic
        for topic in topic_rows:
            try:
                result = _research_single_topic(
                    provider=selected_provider,
                    domain_id=domain_id,
                    topic=topic,
                    prompt_template=prompt_template,
                    recency=topic["search_recency_filter"] or recency,
                    model=model,
                    max_tokens=max_tokens,
                    extra_context=context,
                    session_id=session_id
                )
                if result:
                    results.append(result)
            except Exception as e:
                logger.error(f"Research failed for topic {topic['name']}: {e}")
                errors.append({"topic": topic["name"], "error": str(e)})

        # Update domain last_research_at
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE research_domains SET last_research_at = NOW() WHERE id = %s",
                (domain_id,)
            )
            conn.commit()

        return {
            "success": True,
            "session_id": session_id,
            "domain": domain,
            "provider": selected_provider,
            "topics_researched": len(results),
            "items_created": len(results),
            "errors": len(errors),
            "results": [
                {"topic": r["topic"], "title": r["title"], "sources": r["source_count"], "provider": r.get("provider")}
                for r in results
            ],
            "error_details": errors if errors else None
        }

    except Exception as e:
        logger.error(f"run_research failed: {e}")
        return {"success": False, "error": str(e)}


def _research_single_topic(
    provider: str,
    domain_id: int,
    topic: Dict,
    prompt_template: str,
    recency: str,
    model: str,
    max_tokens: int,
    extra_context: Optional[str],
    session_id: str
) -> Optional[Dict]:
    """Research a single topic using the specified provider and store results."""
    import httpx

    # Build query
    template = topic.get("query_template") or prompt_template
    topic_context = topic.get("context") or ""
    if extra_context:
        topic_context = f"{topic_context} {extra_context}".strip()

    query = template.format(
        topic=topic["name"],
        context=topic_context or "General research",
        recency=recency,
        date=datetime.now().strftime("%Y-%m-%d")
    )

    # Call appropriate provider
    if provider == "perplexity":
        content, sources, model_used = _call_perplexity(query, model, max_tokens, recency)
    elif provider == "tavily":
        content, sources, model_used = _call_tavily(query, max_tokens)
    else:  # duckduckgo
        content, sources, model_used = _call_duckduckgo(query)

    # Generate title and summary
    title = f"{topic['name']} Research - {datetime.now().strftime('%Y-%m-%d')}"
    summary = content[:500] + "..." if len(content) > 500 else content

    # Store in database
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO research_items
               (domain_id, topic_id, title, summary, content, sources, source_count,
                query_used, model_used, research_session_id, confidence_score, status)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               RETURNING id""",
            (
                domain_id,
                topic["id"],
                title,
                summary,
                content,
                json.dumps(sources),
                len(sources),
                query,
                model_used,
                session_id,  # Already a string, no UUID conversion needed
                _calculate_confidence(provider, len(sources)),
                "new"
            )
        )
        item_id = cur.fetchone()["id"]

        # Update topic stats
        cur.execute(
            """UPDATE research_topics
               SET last_researched_at = NOW(), research_count = research_count + 1
               WHERE id = %s""",
            (topic["id"],)
        )
        conn.commit()

    return {
        "item_id": item_id,
        "topic": topic["name"],
        "title": title,
        "source_count": len(sources),
        "provider": provider
    }


def _calculate_confidence(provider: str, source_count: int) -> float:
    """Calculate confidence score based on provider and source count."""
    base_scores = {
        "perplexity": 0.8,  # AI-powered, high quality
        "tavily": 0.7,     # Good structured data
        "duckduckgo": 0.5  # Basic web search
    }
    base = base_scores.get(provider, 0.5)

    # Boost for more sources
    if source_count >= 5:
        base += 0.1
    elif source_count >= 3:
        base += 0.05

    return min(base, 1.0)


def _call_perplexity(query: str, model: str, max_tokens: int, recency: str) -> tuple:
    """Call Perplexity API and return (content, sources, model_used)."""
    import httpx

    api_key = os.environ.get("PERPLEXITY_API_KEY")
    if not api_key:
        raise ValueError("PERPLEXITY_API_KEY not configured")

    response = httpx.post(
        "https://api.perplexity.ai/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [{"role": "user", "content": query}],
            "max_tokens": max_tokens,
            "temperature": 0.2,
            "return_citations": True,
            "search_recency_filter": recency,
        },
        timeout=60.0
    )
    response.raise_for_status()
    data = response.json()

    # Extract content and citations
    content = ""
    if data.get("choices"):
        content = data["choices"][0].get("message", {}).get("content", "")

    citations = data.get("citations", [])
    sources = [{"url": url, "index": i + 1} for i, url in enumerate(citations)]

    return content, sources, f"perplexity:{model}"


def _call_tavily(query: str, max_tokens: int = 4096) -> tuple:
    """Call Tavily API and return (content, sources, model_used)."""
    import httpx

    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        raise ValueError("TAVILY_API_KEY not configured")

    # Tavily has 400 char limit - truncate if needed
    if len(query) > 380:
        # Keep first line (topic) + truncate
        lines = query.split('\n')
        query = lines[0][:380] if lines else query[:380]

    response = httpx.post(
        "https://api.tavily.com/search",
        headers={
            "Content-Type": "application/json",
        },
        json={
            "api_key": api_key,
            "query": query,
            "search_depth": "basic",  # "advanced" requires paid tier
            "include_answer": True,
            "include_raw_content": False,
            "max_results": 10,
        },
        timeout=30.0
    )
    response.raise_for_status()
    data = response.json()

    # Tavily returns an answer and results
    answer = data.get("answer", "")
    results = data.get("results", [])

    # Build content from answer + result summaries
    content_parts = []
    if answer:
        content_parts.append(f"**Summary:** {answer}\n")

    for i, r in enumerate(results[:5], 1):
        title = r.get("title", "")
        snippet = r.get("content", "")[:300]
        content_parts.append(f"\n{i}. **{title}**\n{snippet}")

    content = "\n".join(content_parts)

    # Build sources
    sources = [
        {"url": r.get("url", ""), "title": r.get("title", ""), "index": i + 1}
        for i, r in enumerate(results)
    ]

    return content, sources, "tavily:basic"


def _call_duckduckgo(query: str, num_results: int = 10) -> tuple:
    """Call DuckDuckGo and return (content, sources, model_used)."""
    try:
        from duckduckgo_search import DDGS

        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=num_results):
                results.append({
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", "")
                })

        # Build content from results
        content_parts = []
        for i, r in enumerate(results, 1):
            content_parts.append(f"{i}. **{r['title']}**\n{r['snippet']}\n")

        content = "\n".join(content_parts)

        # Build sources
        sources = [
            {"url": r["url"], "title": r["title"], "index": i + 1}
            for i, r in enumerate(results)
        ]

        return content, sources, "duckduckgo"

    except ImportError:
        raise ValueError("duckduckgo-search package not installed")
    except Exception as e:
        logger.error(f"DuckDuckGo search failed: {e}")
        raise


def get_research_items(
    domain: Optional[str] = None,
    topic: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 10
) -> Dict[str, Any]:
    """Get recent research items."""
    try:
        limit = min(limit, 50)
        with get_conn() as conn:
            cur = conn.cursor()
            query = """
                SELECT
                    i.id, i.title, i.summary, i.created_at::text,
                    i.status, i.confidence_score, i.source_count,
                    d.name as domain_name, t.name as topic_name
                FROM research_items i
                JOIN research_domains d ON d.id = i.domain_id
                LEFT JOIN research_topics t ON t.id = i.topic_id
                WHERE 1=1
            """
            params = []

            if domain:
                query += " AND d.name = %s"
                params.append(domain)
            if topic:
                query += " AND t.name = %s"
                params.append(topic)
            if status:
                query += " AND i.status = %s"
                params.append(status)

            query += " ORDER BY i.created_at DESC LIMIT %s"
            params.append(limit)

            cur.execute(query, params)
            rows = cur.fetchall()

            items = []
            for row in rows:
                summary = row.get("summary") or ""
                items.append({
                    "id": row["id"],
                    "title": row["title"],
                    "summary": summary[:300] + "..." if len(summary) > 300 else summary,
                    "domain": row["domain_name"],
                    "topic": row["topic_name"],
                    "status": row["status"],
                    "confidence": float(row["confidence_score"]) if row.get("confidence_score") else None,
                    "sources": row["source_count"],
                    "created_at": row["created_at"],
                })

            return {"success": True, "count": len(items), "items": items}

    except Exception as e:
        logger.error(f"Failed to get research items: {e}")
        return {"success": False, "error": str(e)}


def get_research_item_detail(item_id: int) -> Dict[str, Any]:
    """Get full details of a research item."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT i.*, d.name as domain_name, d.display_name as domain_display,
                       t.name as topic_name
                FROM research_items i
                JOIN research_domains d ON d.id = i.domain_id
                LEFT JOIN research_topics t ON t.id = i.topic_id
                WHERE i.id = %s
                """,
                (item_id,)
            )
            row = cur.fetchone()

            if not row:
                return {"success": False, "error": f"Item {item_id} not found"}

            cur.execute(
                """
                SELECT rt.name, rt.category
                FROM research_item_tags it
                JOIN research_tags rt ON rt.id = it.tag_id
                WHERE it.item_id = %s
                """,
                (item_id,)
            )
            tags = cur.fetchall()

            sources = []
            if row.get("sources"):
                try:
                    sources = json.loads(row["sources"]) if isinstance(row["sources"], str) else row["sources"]
                except:
                    pass

            return {
                "success": True,
                "item": {
                    "id": row["id"],
                    "title": row["title"],
                    "summary": row["summary"],
                    "content": row["content"],
                    "domain": row["domain_name"],
                    "topic": row["topic_name"],
                    "status": row["status"],
                    "confidence": float(row["confidence_score"]) if row.get("confidence_score") else None,
                    "sources": sources,
                    "structured_data": row.get("structured_data"),
                    "query_used": row.get("query_used"),
                    "model_used": row.get("model_used"),
                    "created_at": str(row["created_at"]) if row.get("created_at") else None,
                    "tags": [{"name": t[0], "category": t[1]} for t in tags],
                }
            }

    except Exception as e:
        logger.error(f"Failed to get research item detail: {e}")
        return {"success": False, "error": str(e)}


def list_research_domains() -> Dict[str, Any]:
    """List all available research domains with statistics."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM v_research_domain_stats ORDER BY is_active DESC, item_count DESC")
            rows = cur.fetchall()

            domains = []
            for row in rows:
                # row is RealDictRow, access directly
                domains.append({
                    "id": row["id"],
                    "name": row["name"],
                    "display_name": row["display_name"],
                    "is_active": row["is_active"],
                    "topic_count": row["topic_count"],
                    "item_count": row["item_count"],
                    "report_count": row["report_count"],
                    "last_research": str(row["last_research_at"]) if row.get("last_research_at") else None,
                    "latest_item": str(row["latest_item_at"]) if row.get("latest_item_at") else None,
                })

            return {"success": True, "domains": domains}

    except Exception as e:
        logger.error(f"Failed to list research domains: {e}")
        return {"success": False, "error": str(e)}


def list_research_topics(domain: str) -> Dict[str, Any]:
    """List all topics for a research domain."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, display_name FROM research_domains WHERE name = %s", (domain,))
            domain_row = cur.fetchone()
            if not domain_row:
                return {"success": False, "error": f"Domain '{domain}' not found"}

            domain_id = domain_row["id"]
            display_name = domain_row["display_name"]

            cur.execute(
                """
                SELECT id, name, context, priority, is_active, last_researched_at, research_count
                FROM research_topics WHERE domain_id = %s ORDER BY priority DESC, name
                """,
                (domain_id,)
            )
            rows = cur.fetchall()

            topics = []
            for row in rows:
                topics.append({
                    "id": row["id"],
                    "name": row["name"],
                    "context": row["context"],
                    "priority": row["priority"],
                    "is_active": row["is_active"],
                    "last_researched": str(row["last_researched_at"]) if row.get("last_researched_at") else None,
                    "research_count": row["research_count"],
                })

            return {"success": True, "domain": domain, "domain_display": display_name, "topics": topics}

    except Exception as e:
        logger.error(f"Failed to list research topics: {e}")
        return {"success": False, "error": str(e)}


def add_research_topic(
    domain: str,
    name: str,
    context: Optional[str] = None,
    priority: int = 5
) -> Dict[str, Any]:
    """Add a new topic to a research domain."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM research_domains WHERE name = %s", (domain,))
            domain_row = cur.fetchone()
            if not domain_row:
                return {"success": False, "error": f"Domain '{domain}' not found"}

            domain_id = domain_row["id"]

            cur.execute("SELECT id FROM research_topics WHERE domain_id = %s AND name = %s", (domain_id, name))
            if cur.fetchone():
                return {"success": False, "error": f"Topic '{name}' already exists"}

            cur.execute(
                "INSERT INTO research_topics (domain_id, name, context, priority) VALUES (%s, %s, %s, %s) RETURNING id",
                (domain_id, name, context, priority)
            )
            result = cur.fetchone()
            topic_id = result["id"]
            conn.commit()

            return {"success": True, "topic_id": topic_id, "domain": domain, "name": name, "priority": priority}

    except Exception as e:
        logger.error(f"Failed to add research topic: {e}")
        return {"success": False, "error": str(e)}


def add_research_domain(
    name: str,
    display_name: str,
    description: str,
    prompt_template: str,
    search_recency: str = "week",
    priority: int = 5
) -> Dict[str, Any]:
    """Create a new research domain."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM research_domains WHERE name = %s", (name,))
            if cur.fetchone():
                return {"success": False, "error": f"Domain '{name}' already exists"}

            cur.execute(
                """
                INSERT INTO research_domains (name, display_name, description, prompt_template, search_recency_filter, priority)
                VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
                """,
                (name, display_name, description, prompt_template, search_recency, priority)
            )
            result = cur.fetchone()
            domain_id = result["id"]
            conn.commit()

            return {"success": True, "domain_id": domain_id, "name": name, "display_name": display_name}

    except Exception as e:
        logger.error(f"Failed to add research domain: {e}")
        return {"success": False, "error": str(e)}


def tag_research_item(item_id: int, tags: List[str]) -> Dict[str, Any]:
    """Add tags to a research item."""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM research_items WHERE id = %s", (item_id,))
            if not cur.fetchone():
                return {"success": False, "error": f"Item {item_id} not found"}

            added = []
            for tag_name in tags:
                cur.execute("SELECT id FROM research_tags WHERE name = %s", (tag_name,))
                tag_row = cur.fetchone()
                if tag_row:
                    tag_id = tag_row["id"]
                else:
                    cur.execute("INSERT INTO research_tags (name) VALUES (%s) RETURNING id", (tag_name,))
                    result = cur.fetchone()
                    tag_id = result["id"]

                cur.execute(
                    "INSERT INTO research_item_tags (item_id, tag_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (item_id, tag_id)
                )
                added.append(tag_name)

            conn.commit()
            return {"success": True, "item_id": item_id, "tags_added": added}

    except Exception as e:
        logger.error(f"Failed to tag research item: {e}")
        return {"success": False, "error": str(e)}


def get_perplexity_status() -> Dict[str, Any]:
    """Get Perplexity API status and rate limit info."""
    try:
        from app.services.perplexity_client import get_perplexity_client
        client = get_perplexity_client()
        status = client.rate_limit_status

        return {
            "success": True,
            "api_key_configured": bool(client.api_key),
            "default_model": client.config.default_model,
            "rate_limits": {
                "minute_remaining": status["minute_remaining"],
                "daily_remaining": status["daily_remaining"],
                "rpm_limit": client.config.rate_limit_rpm,
                "daily_limit": client.config.rate_limit_daily,
            },
            "config": {
                "max_concurrent": client.config.max_concurrent,
                "retry_attempts": client.config.retry_attempts,
            }
        }

    except Exception as e:
        logger.error(f"Failed to get Perplexity status: {e}")
        return {"success": False, "error": str(e)}


def get_research_providers() -> Dict[str, Any]:
    """Get available research providers and their status."""
    try:
        providers = _get_available_providers()
        selected = _select_provider()

        return {
            "success": True,
            "providers": providers,
            "default_provider": selected,
            "provider_priority": PROVIDER_PRIORITY
        }

    except Exception as e:
        logger.error(f"Failed to get research providers: {e}")
        return {"success": False, "error": str(e)}


# Tool definitions for registration
RESEARCH_TOOLS = [
    {
        "name": "run_research",
        "description": "Execute research for a domain using available providers (Perplexity, Tavily, or DuckDuckGo). Returns findings from web search with sources.",
        "input_schema": {
            "type": "object",
            "properties": {
                "domain": {"type": "string", "description": "Domain name (e.g., 'ai_tools')"},
                "topics": {"type": "array", "items": {"type": "string"}, "description": "Specific topics (optional)"},
                "context": {"type": "string", "description": "Additional context"},
                "provider": {
                    "type": "string",
                    "enum": ["perplexity", "tavily", "duckduckgo"],
                    "description": "Search provider (default: auto-select best available)"
                }
            },
            "required": ["domain"]
        }
    },
    {
        "name": "get_research_items",
        "description": "Get recent research items. Filter by domain, topic, or status.",
        "input_schema": {
            "type": "object",
            "properties": {
                "domain": {"type": "string"},
                "topic": {"type": "string"},
                "status": {"type": "string", "enum": ["new", "reviewed", "archived", "flagged"]},
                "limit": {"type": "integer", "default": 10, "maximum": 50}
            }
        }
    },
    {
        "name": "get_research_item_detail",
        "description": "Get full details of a research item including content and sources.",
        "input_schema": {
            "type": "object",
            "properties": {"item_id": {"type": "integer"}},
            "required": ["item_id"]
        }
    },
    {
        "name": "list_research_domains",
        "description": "List all research domains with statistics (topic count, item count, last research).",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "list_research_topics",
        "description": "List all topics for a research domain.",
        "input_schema": {
            "type": "object",
            "properties": {"domain": {"type": "string"}},
            "required": ["domain"]
        }
    },
    {
        "name": "add_research_topic",
        "description": "Add a new topic to a research domain.",
        "input_schema": {
            "type": "object",
            "properties": {
                "domain": {"type": "string"},
                "name": {"type": "string"},
                "context": {"type": "string"},
                "priority": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5}
            },
            "required": ["domain", "name"]
        }
    },
    {
        "name": "add_research_domain",
        "description": "Create a new research domain with prompt template.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "display_name": {"type": "string"},
                "description": {"type": "string"},
                "prompt_template": {"type": "string"},
                "search_recency": {"type": "string", "enum": ["day", "week", "month", "year"], "default": "week"},
                "priority": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5}
            },
            "required": ["name", "display_name", "description", "prompt_template"]
        }
    },
    {
        "name": "tag_research_item",
        "description": "Add tags to a research item.",
        "input_schema": {
            "type": "object",
            "properties": {
                "item_id": {"type": "integer"},
                "tags": {"type": "array", "items": {"type": "string"}}
            },
            "required": ["item_id", "tags"]
        }
    },
    {
        "name": "get_perplexity_status",
        "description": "Get Perplexity API status and rate limits.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "get_research_providers",
        "description": "Get available research providers (Perplexity, Tavily, DuckDuckGo) and their status.",
        "input_schema": {"type": "object", "properties": {}}
    }
]
