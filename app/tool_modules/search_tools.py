"""
Search Tools.

Knowledge base search, email search, chat search, web search.
Extracted from tools.py (Phase S2).
"""
from typing import Dict, Any, List
from datetime import datetime, timedelta
import math
import re
import requests

from ..observability import get_logger, log_with_context, metrics
from ..langfuse_integration import observe, langfuse_context
from ..embed import embed_texts
from ..errors import (
    JarvisException, ErrorCode, wrap_external_error,
    internal_error, qdrant_unavailable
)

logger = get_logger("jarvis.tools.search")

# Import constants from parent
import os
QDRANT_BASE = os.getenv("QDRANT_BASE", "http://qdrant:6333")
RERANK_ALPHA = float(os.getenv("JARVIS_RERANK_ALPHA", "0.7"))
LEXICAL_RERANK_ENABLED = os.getenv("JARVIS_LEXICAL_RERANK", "true").lower() in ("1", "true", "yes", "on")
RECENCY_WEIGHT = float(os.getenv("JARVIS_RECENCY_WEIGHT", "0.15"))
RECENCY_HALF_LIFE_DAYS = float(os.getenv("JARVIS_RECENCY_HALF_LIFE_DAYS", "30"))


def _core_tools():
    from .. import tools as core_tools
    return core_tools


def expand_query_with_name_variants(query: str) -> str:
    return _core_tools().expand_query_with_name_variants(query)


def expand_namespaces(namespace: str) -> List[str]:
    return _core_tools().expand_namespaces(namespace)


def comms_origin_namespaces(namespace: str) -> List[str]:
    return _core_tools().comms_origin_namespaces(namespace)


def _comms_namespace() -> str:
    return _core_tools().COMMS_NAMESPACE


def _comms_collection() -> str:
    return _core_tools().COMMS_COLLECTION


def _tokenize(text: str) -> List[str]:
    if not text:
        return []
    return [t for t in re.split(r"[^a-zA-Z0-9äöüÄÖÜß]+", text.lower()) if len(t) > 2]


def _lexical_score(query: str, text: str, source_path: str = "") -> float:
    """
    Lightweight lexical score for hybrid reranking.
    Uses token overlap + bigram match + filename/path hints.
    """
    q_tokens = _tokenize(query)
    if not q_tokens:
        return 0.0

    text_lower = (text or "").lower()
    tokens = set(_tokenize(text))
    match_count = sum(1 for t in q_tokens if t in tokens)
    token_score = match_count / max(len(q_tokens), 1)

    bigrams = list(zip(q_tokens, q_tokens[1:]))
    bigram_hits = 0
    for a, b in bigrams:
        if f"{a} {b}" in text_lower:
            bigram_hits += 1
    bigram_score = (bigram_hits / max(len(bigrams), 1)) if bigrams else 0.0

    phrase_boost = 0.15 if query.lower() in text_lower else 0.0

    path_lower = (source_path or "").lower()
    path_boost = 0.0
    for t in q_tokens:
        if t in path_lower:
            path_boost = 0.1
            break

    score = (token_score * 0.65) + (bigram_score * 0.2) + phrase_boost + path_boost
    return min(1.0, round(score, 4))


def _recency_score(ts: str) -> float:
    if not ts:
        return 0.5
    try:
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        dt = datetime.fromisoformat(ts)
    except Exception:
        return 0.5
    days_ago = (datetime.now(tz=dt.tzinfo) - dt).total_seconds() / 86400.0
    if days_ago <= 0:
        return 1.0
    decay = math.log(2) / max(RECENCY_HALF_LIFE_DAYS, 1.0)
    score = math.exp(-decay * days_ago)
    return max(0.1, round(score, 4))


def _search_qdrant(
    query: str,
    collection: str,
    limit: int = 5,
    filters: Dict = None,
    recency_days: int = None
) -> List[Dict]:
    """
    Core search function against Qdrant.

    Returns:
        List of search results

    Raises:
        JarvisException: On connection errors or service unavailability
    """
    try:
        q_vec = embed_texts([query])[0]

        search_limit = limit * 4 if LEXICAL_RERANK_ENABLED else limit
        payload = {
            "vector": q_vec,
            "limit": search_limit * 2 if recency_days else search_limit,  # fetch more if filtering
            "with_payload": True,
            # HNSW search optimization: lower ef = faster but less accurate
            # Default is 128, using 64 for ~40% speed improvement with minimal accuracy loss
            "params": {
                "hnsw_ef": 64,
                "exact": False  # Use approximate search for speed
            }
        }

        if filters:
            must = []
            for key, value in filters.items():
                must.append({"key": key, "match": {"value": value}})
            if must:
                payload["filter"] = {"must": must}

        r = requests.post(
            f"{QDRANT_BASE}/collections/{collection}/points/search",
            json=payload,
            timeout=30,
        )

        if r.status_code == 404:
            # Collection doesn't exist - expected for new namespaces
            log_with_context(logger, "debug", "Collection not found (expected)",
                           collection=collection)
            return []

        if r.status_code == 503:
            log_with_context(logger, "warning", "Qdrant temporarily unavailable",
                           collection=collection)
            raise JarvisException(
                code=ErrorCode.QDRANT_UNAVAILABLE,
                message="Vector search temporarily unavailable",
                status_code=503,
                details={"collection": collection},
                recoverable=True,
                retry_after=10,
                hint="Qdrant service is overloaded, try again shortly"
            )

        r.raise_for_status()

        results = []
        for hit in r.json().get("result", []):
            pl = hit.get("payload", {}) or {}

            # Apply recency filter
            if recency_days:
                cutoff = (datetime.now() - timedelta(days=recency_days)).isoformat()
                ts = pl.get("event_ts") or pl.get("ingest_ts") or ""
                if ts and ts < cutoff:
                    continue

            text_full = pl.get("text", "") or ""
            event_ts = pl.get("event_ts") or pl.get("ingest_ts")
            vector_score = hit.get("score") or 0.0
            lexical_score = _lexical_score(query, text_full, pl.get("source_path"))
            recency_score = _recency_score(event_ts)

            # Hybrid score: vector + lexical (decay applied later)
            hybrid_score = (RERANK_ALPHA * vector_score) + ((1 - RERANK_ALPHA) * lexical_score)

            # Apply recency decay weight (best-practice)
            if RECENCY_WEIGHT > 0:
                hybrid_score = hybrid_score * ((1 - RECENCY_WEIGHT) + (RECENCY_WEIGHT * recency_score))

            results.append({
                "score": vector_score,
                "hybrid_score": round(hybrid_score, 6),
                "lexical_score": lexical_score,
                "recency_score": recency_score,
                "text": text_full[:500],  # Truncate for context
                "source_path": pl.get("source_path"),
                "doc_type": pl.get("doc_type"),
                "channel": pl.get("channel"),
                "label": pl.get("label"),
                "labels": pl.get("labels"),
                "event_ts": event_ts,
            })

        # Rerank by hybrid score if enabled; otherwise keep vector score
        if LEXICAL_RERANK_ENABLED:
            results.sort(key=lambda x: x.get("hybrid_score", 0), reverse=True)
        else:
            results.sort(key=lambda x: x.get("score", 0), reverse=True)

        return results[:limit]

    except JarvisException:
        raise  # Re-raise our own exceptions
    except requests.Timeout as e:
        log_with_context(logger, "error", "Qdrant search timeout",
                        error=str(e), collection=collection)
        raise JarvisException(
            code=ErrorCode.TIMEOUT,
            message="Vector search timed out",
            status_code=504,
            details={"collection": collection, "query_length": len(query)},
            recoverable=True,
            retry_after=15,
            hint="Search query may be too complex, try simpler terms"
        )
    except requests.ConnectionError as e:
        log_with_context(logger, "error", "Qdrant connection error",
                        error=str(e), collection=collection)
        raise qdrant_unavailable({"collection": collection, "error": str(e)[:100]})
    except requests.HTTPError as e:
        log_with_context(logger, "error", "Qdrant HTTP error",
                        error=str(e), collection=collection, status=e.response.status_code if e.response else None)
        raise JarvisException(
            code=ErrorCode.QDRANT_ERROR,
            message=f"Vector search failed: {str(e)[:100]}",
            status_code=502,
            details={"collection": collection},
            recoverable=True,
            retry_after=10
        )
    except Exception as e:
        log_with_context(logger, "error", "Qdrant search unexpected error",
                        error=str(e), collection=collection, error_type=type(e).__name__)
        raise wrap_external_error(e, service="qdrant_search")


@observe(name="tool_search_knowledge")
def tool_search_knowledge(
    query: str,
    namespace: str = "private",
    limit: int = 5,
    recency_days: int = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Search across all knowledge (emails + chats).

    Uses resilient search pattern: if some collections fail, returns partial results
    with error info. Only raises JarvisException if ALL collections fail.
    """
    # Expand query with name variants for fuzzy matching
    expanded_query = expand_query_with_name_variants(query)
    query_changed = expanded_query != query

    log_with_context(logger, "info", "Tool: search_knowledge",
                    query=query, expanded_query=expanded_query if query_changed else None,
                    namespace=namespace)
    metrics.inc("tool_search_knowledge")

    if langfuse_context:
        try:
            langfuse_context.update_current_trace(
                metadata={
                    "tool": "search_knowledge",
                    "namespace": namespace,
                    "limit": limit,
                    "recency_days": recency_days,
                    "query_length": len(query) if query else 0,
                    "query_expanded": query_changed,
                },
                tags=["tool", "search_knowledge"],
            )
        except Exception:
            pass

    all_results = []
    errors = []
    collections_searched = 0
    collections_failed = 0

    # Handle namespace aliases (work/all)
    namespaces = [] if namespace == _comms_namespace() else expand_namespaces(namespace)

    for ns in namespaces:
        # Search main collection (emails, docs)
        try:
            collections_searched += 1
            results = _search_qdrant(
                query=expanded_query,
                collection=f"jarvis_{ns}",
                limit=limit,
                recency_days=recency_days
            )
            all_results.extend(results)
        except JarvisException as e:
            collections_failed += 1
            errors.append({"collection": f"jarvis_{ns}", "error": e.error.message})
            log_with_context(logger, "warning", "Partial search failure",
                           collection=f"jarvis_{ns}", error=e.error.message)

    # Search unified comms collection (chats)
    for ns in comms_origin_namespaces(namespace):
        try:
            collections_searched += 1
            results = _search_qdrant(
                query=expanded_query,
                collection=_comms_collection(),
                limit=limit,
                recency_days=recency_days,
                filters={"origin_namespace": ns}
            )
            all_results.extend(results)
        except JarvisException as e:
            collections_failed += 1
            errors.append({"collection": _comms_collection(), "error": e.error.message})
            log_with_context(logger, "warning", "Partial search failure",
                           collection=_comms_collection(), error=e.error.message)

    # If ALL collections failed, raise exception
    if collections_failed == collections_searched and collections_searched > 0:
        log_with_context(logger, "error", "All collections failed",
                        query=query[:50], errors=errors)
        raise JarvisException(
            code=ErrorCode.QDRANT_UNAVAILABLE,
            message="Knowledge search failed - all vector collections unavailable",
            status_code=503,
            details={"errors": errors, "query": query[:50]},
            recoverable=True,
            retry_after=30,
            hint="Qdrant may be down or overloaded. Try again in a moment."
        )

    # Sort by score and dedupe
    all_results.sort(key=lambda x: x.get("score", 0), reverse=True)

    seen_paths = set()
    unique_results = []
    for r in all_results:
        path = r.get("source_path", "")
        if path not in seen_paths:
            seen_paths.add(path)
            unique_results.append(r)
        if len(unique_results) >= limit:
            break

    result = {
        "results": unique_results,
        "count": len(unique_results),
        "query": query,
        "ranking": "hybrid" if LEXICAL_RERANK_ENABLED else "vector"
    }
    if query_changed:
        result["expanded_query"] = expanded_query
        result["name_variants_applied"] = True

    # Include partial failure info if some collections failed
    if errors:
        result["partial_failure"] = True
        result["search_errors"] = errors
        result["collections_searched"] = collections_searched - collections_failed
        result["collections_failed"] = collections_failed

    return result


def tool_search_emails(
    query: str,
    namespace: str = "private",
    label: str = None,
    recency_days: int = None,
    limit: int = 5,
    **kwargs
) -> Dict[str, Any]:
    """Search emails specifically"""
    # Expand query with name variants for fuzzy matching
    expanded_query = expand_query_with_name_variants(query)
    query_changed = expanded_query != query

    log_with_context(logger, "info", "Tool: search_emails",
                    query=query, expanded_query=expanded_query if query_changed else None,
                    namespace=namespace, label=label)
    metrics.inc("tool_search_emails")

    filters = {"doc_type": "email"}
    if label:
        filters["label"] = label

    all_results = []
    for ns in expand_namespaces(namespace):
        results = _search_qdrant(
            query=expanded_query,
            collection=f"jarvis_{ns}",
            limit=limit,
            filters=filters,
            recency_days=recency_days
        )
        all_results.extend(results)

    all_results.sort(key=lambda x: x.get("score", 0), reverse=True)
    results = all_results[:limit]

    result = {
        "results": results,
        "count": len(results),
        "query": query,
        "label_filter": label
    }
    if query_changed:
        result["expanded_query"] = expanded_query
        result["name_variants_applied"] = True
    return result


def tool_search_chats(
    query: str,
    namespace: str = "private",
    channel: str = None,
    recency_days: int = None,
    limit: int = 5,
    **kwargs
) -> Dict[str, Any]:
    """Search chat messages"""
    # Expand query with name variants for fuzzy matching
    expanded_query = expand_query_with_name_variants(query)
    query_changed = expanded_query != query

    log_with_context(logger, "info", "Tool: search_chats",
                    query=query, expanded_query=expanded_query if query_changed else None,
                    namespace=namespace, channel=channel)
    metrics.inc("tool_search_chats")

    filters = {"doc_type": "chat_window"}
    if channel:
        filters["channel"] = channel

    all_results = []
    for ns in comms_origin_namespaces(namespace):
        results = _search_qdrant(
            query=expanded_query,
            collection=_comms_collection(),
            limit=limit,
            filters=filters,
            recency_days=recency_days
        )
        all_results.extend(results)

    all_results.sort(key=lambda x: x.get("score", 0), reverse=True)
    results = all_results[:limit]

    result = {
        "results": results,
        "count": len(results),
        "query": query,
        "channel_filter": channel
    }
    if query_changed:
        result["expanded_query"] = expanded_query
        result["name_variants_applied"] = True
    return result


def tool_get_recent_activity(
    days: int = 1,
    namespace: str = "private",
    include_emails: bool = True,
    include_chats: bool = True,
    **kwargs
) -> Dict[str, Any]:
    """Get recent activity summary"""
    log_with_context(logger, "info", "Tool: get_recent_activity",
                    days=days, namespace=namespace)
    metrics.inc("tool_get_recent_activity")

    # Use a generic query to get recent items
    results = {
        "period_days": days,
        "namespace": namespace,
        "emails": [],
        "chats": []
    }

    namespaces = expand_namespaces(namespace)

    if include_emails:
        email_results = []
        for ns in namespaces:
            email_results.extend(_search_qdrant(
                query="email message communication update",  # Generic query
                collection=f"jarvis_{ns}",
                limit=10,
                filters={"doc_type": "email"},
                recency_days=days
            ))
        email_results.sort(key=lambda x: x.get("event_ts") or "", reverse=True)
        results["emails"] = email_results[:10]
        results["email_count"] = len(results["emails"])

    if include_chats:
        chat_results = []
        for ns in comms_origin_namespaces(namespace):
            chat_results.extend(_search_qdrant(
                query="chat conversation message discussion",
                collection=_comms_collection(),
                limit=10,
                filters={"origin_namespace": ns},
                recency_days=days
            ))
        chat_results.sort(key=lambda x: x.get("event_ts") or "", reverse=True)
        results["chats"] = chat_results[:10]
        results["chat_count"] = len(results["chats"])

    return results


def tool_web_search(
    query: str = None,
    num_results: int = 5,
    detailed: bool = False,
    **kwargs
) -> Dict[str, Any]:
    """
    Search the web using Perplexity (primary) or DuckDuckGo (fallback).
    Perplexity provides AI-powered search with source citations.

    Raises:
        JarvisException: On network or API errors with structured error info
    """
    # Support both 'query' parameter and positional
    if query is None:
        query = kwargs.get("query", "")

    if not query:
        return {"error": "query is required"}

    log_with_context(logger, "info", "Tool: web_search", query=query, detailed=detailed)
    metrics.inc("tool_web_search")

    # Try Perplexity first (better results with citations)
    try:
        from .subagents.perplexity_agent import PerplexityAgent, PERPLEXITY_MODELS
        import asyncio

        agent = PerplexityAgent()
        if agent.api_key:
            from .subagents import SubAgentTask

            task = SubAgentTask(
                task_id=SubAgentTask.generate_id("web"),
                agent_id="perplexity",
                instructions=query,
                created_at=datetime.now().isoformat(),
            )

            if detailed:
                agent.default_model = PERPLEXITY_MODELS["huge"]

            # Run async in sync context
            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(agent.execute(task))
            finally:
                loop.close()

            if result.status == "completed":
                metrics.inc("tool_web_search_perplexity")
                return {
                    "query": query,
                    "answer": result.result,
                    "source": "perplexity",
                    "model": result.model_used,
                    "execution_time_ms": round(result.execution_time_ms, 2),
                }
    except ImportError:
        pass
    except Exception as e:
        log_with_context(logger, "warning", "Perplexity search failed, falling back to DuckDuckGo", error=str(e))

    # Fallback to DuckDuckGo
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

        metrics.inc("tool_web_search_duckduckgo")
        return {
            "query": query,
            "results": results,
            "count": len(results),
            "source": "duckduckgo"
        }
    except ImportError:
        raise JarvisException(
            code=ErrorCode.SERVICE_UNAVAILABLE,
            message="Web search not available (no Perplexity key and duckduckgo-search not installed)",
            status_code=503,
            details={"query": query},
            recoverable=False,
            hint="Set PERPLEXITY_API_KEY or install duckduckgo-search"
        )
    except requests.Timeout as e:
        log_with_context(logger, "error", "Web search timeout", error=str(e))
        raise JarvisException(
            code=ErrorCode.TIMEOUT,
            message="Web search timed out",
            status_code=504,
            details={"query": query},
            recoverable=True,
            retry_after=10,
            hint="Try a simpler query or try again"
        )
    except Exception as e:
        error_msg = str(e)
        log_with_context(logger, "error", "Web search failed",
                        error=error_msg, error_type=type(e).__name__)

        if "rate" in error_msg.lower() or "429" in error_msg:
            raise JarvisException(
                code=ErrorCode.RATE_LIMIT_EXCEEDED,
                message="Web search rate limited",
                status_code=429,
                details={"query": query},
                recoverable=True,
                retry_after=60,
                hint="Rate limit - wait before retrying"
            )
        else:
            raise wrap_external_error(e, service="web_search")

def tool_propose_knowledge_update(
    update_type: str,
    subject_id: str,
    insight: str,
    confidence: str = "medium",
    evidence_source: str = None,
    evidence_note: str = None,
    **kwargs
) -> Dict[str, Any]:
    """Propose a knowledge update for human review"""
    log_with_context(logger, "info", "Tool: propose_knowledge_update",
                    update_type=update_type, subject_id=subject_id)
    metrics.inc("tool_propose_knowledge_update")

    try:
        from .. import knowledge_db

        if not knowledge_db.is_available():
            return {
                "status": "unavailable",
                "message": "Knowledge layer not available. Insight noted but not persisted."
            }

        # Build evidence sources
        evidence_sources = []
        if evidence_source:
            evidence_sources.append({
                "source_path": evidence_source,
                "note": evidence_note or "",
                "timestamp": datetime.now().isoformat()
            })

        # Determine subject type
        if update_type == "person_insight":
            subject_type = "person"
        elif update_type == "persona_adjustment":
            subject_type = "persona"
        else:
            subject_type = "general"

        # Propose the insight
        insight_id = knowledge_db.propose_insight(
            insight_type=update_type,
            subject_type=subject_type,
            subject_id=subject_id,
            insight_text=insight,
            confidence=confidence,
            evidence_sources=evidence_sources,
            proposed_by="jarvis"
        )

        if not insight_id:
            return {"status": "error", "message": "Failed to create insight"}

        # Add to review queue
        queue_id = knowledge_db.add_to_review_queue(
            item_type="insight",
            item_id=insight_id,
            summary=f"Jarvis {update_type} for {subject_id}: {insight[:100]}...",
            requested_by="jarvis",
            priority="normal",
            evidence_summary=evidence_note
        )

        return {
            "status": "proposed",
            "insight_id": insight_id,
            "queue_id": queue_id,
            "message": f"Proposed {update_type} for {subject_id}. Awaiting human review."
        }

    except Exception as e:
        log_with_context(logger, "error", "Failed to propose knowledge update", error=str(e))
        return {"status": "error", "message": str(e)}
