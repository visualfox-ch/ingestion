"""
LLM integration for Jarvis RAG
Uses Anthropic Claude for response generation
"""
import os
import time
import asyncio
from typing import List, Dict, Any
import anthropic

from .observability import (
    get_logger, log_with_context, retry_with_backoff,
    metrics, query_cache
)
from .langfuse_integration import (
    log_chat_trace, log_rewrite_trace, log_profile_extraction_trace
)

logger = get_logger("jarvis.llm")


def _sleep(seconds: float) -> None:
    """Sleep using asyncio when no running loop; fallback to time.sleep otherwise."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(asyncio.sleep(seconds))
        return
    time.sleep(seconds)

# Load API key from environment or secrets file
def _get_api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key

    # Try loading from secrets file
    secrets_path = "/brain/system/secrets/anthropic_api_key.txt"
    if os.path.exists(secrets_path):
        with open(secrets_path) as f:
            return f.read().strip()

    raise ValueError("ANTHROPIC_API_KEY not set. Set env var or create /brain/system/secrets/anthropic_api_key.txt")

_client = None

def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=_get_api_key())
    return _client

SYSTEM_PROMPT_BASE = """You are Jarvis, a helpful personal assistant with access to the user's emails, chats, and documents.

Your role:
- Answer questions based on the provided context from the user's personal knowledge base
- Always cite your sources when information comes from the context
- If the context doesn't contain relevant information, say so clearly
- Be concise but thorough
- Use a friendly, professional tone

When citing sources:
- Reference emails by subject and sender
- Reference chats by the conversation/channel
- Reference documents by their path or name

If asked about something not in the context, you can still help with general knowledge, but clearly distinguish between information from the user's data vs general knowledge."""

# For backwards compatibility
SYSTEM_PROMPT = SYSTEM_PROMPT_BASE


def get_system_prompt_with_self_model() -> str:
    """
    Build system prompt including dynamic self-model and time-based context.
    Falls back to base prompt if components unavailable.
    """
    parts = [SYSTEM_PROMPT_BASE]

    # Add self-awareness from JARVIS_SYSTEM_PROMPT.md (Phase 18 - Self-Awareness Injection)
    try:
        from . import prompt_assembler
        self_awareness = prompt_assembler.load_self_awareness_context(condensed=False)
        if self_awareness:
            parts.append(f"=== SELF-AWARENESS ===\n{self_awareness}")
    except Exception as e:
        log_with_context(logger, "warning", "Could not load self-awareness context", error=str(e))

    # Add self-model
    try:
        from . import knowledge_db
        self_model_text = knowledge_db.get_self_model_for_prompt()
        if self_model_text:
            parts.append(self_model_text)
    except Exception as e:
        log_with_context(logger, "warning", "Could not load self-model for prompt", error=str(e))

    # Add time-based context (Phase 14 Auto-Context)
    try:
        from . import prompt_assembler
        time_context = prompt_assembler.get_time_based_context(timezone="Europe/Zurich")
        if time_context:
            parts.append(time_context)
    except Exception as e:
        log_with_context(logger, "warning", "Could not load time-based context", error=str(e))

    return "\n\n".join(parts)


QUERY_REWRITE_PROMPT = """You are a query rewriting assistant. Your job is to expand follow-up questions into standalone search queries.

Given the conversation history and the user's latest question, rewrite the question to be a complete, standalone search query that doesn't rely on pronouns or references like "those", "that", "it", "they", etc.

Rules:
- If the query is already self-contained, return it unchanged
- Replace pronouns and references with the actual topics from conversation
- Keep the rewritten query concise (under 50 words)
- Return ONLY the rewritten query, nothing else

Examples:
- "tell me more about that" → "more details about [topic from conversation]"
- "who was involved?" → "who was involved in [topic from conversation]"
- "What's the latest on that project?" → "latest updates on [project name from conversation]"
"""

def rewrite_query_for_search(
    query: str,
    conversation_history: List[Dict[str, str]],
    model: str = "claude-3-5-haiku-20250110"
) -> str:
    """
    Rewrite a follow-up query to be standalone for semantic search.
    Uses Haiku 4.5 for speed/cost efficiency.

    Returns the original query if no rewriting needed.
    """
    history_len = len(conversation_history) if conversation_history else 0
    log_with_context(logger, "info", "Query rewrite called", query=query, history_len=history_len)

    # Skip rewriting if no history or query seems self-contained
    if not conversation_history:
        log_with_context(logger, "info", "No history, skipping rewrite")
        return query

    # Quick heuristic: skip if query has no pronouns/references
    ambiguous_terms = ["that", "those", "this", "these", "it", "they", "them", "the same", "more", "above", "previous"]
    query_lower = query.lower()
    needs_rewrite = any(term in query_lower for term in ambiguous_terms)

    if not needs_rewrite and len(query.split()) > 5:
        log_with_context(logger, "info", "Query self-contained, skipping rewrite", word_count=len(query.split()))
        return query

    # Check cache first
    cache_key = query_cache._make_key(query, str(conversation_history[-4:]))
    cached_result = query_cache.get(cache_key)
    if cached_result:
        log_with_context(logger, "info", "Query rewrite cache hit", rewritten=cached_result)
        metrics.inc("rewrite_cache_hits")
        return cached_result

    start_time = time.time()
    try:
        client = get_client()

        # Build context from recent conversation
        history_text = ""
        for msg in conversation_history[-4:]:  # Last 2 turns
            role = "User" if msg["role"] == "user" else "Assistant"
            content = msg["content"][:500]  # Truncate for efficiency
            history_text += f"{role}: {content}\n\n"

        response = _call_anthropic_with_retry(
            client, model, max_tokens=100,
            system=QUERY_REWRITE_PROMPT,
            messages=[{
                "role": "user",
                "content": f"Conversation history:\n{history_text}\n\nUser's new question: {query}\n\nRewritten query:"
            }]
        )

        duration_ms = (time.time() - start_time) * 1000
        metrics.timing("rewrite_latency_ms", duration_ms)
        metrics.inc("rewrite_tokens_in", response.usage.input_tokens)
        metrics.inc("rewrite_tokens_out", response.usage.output_tokens)

        rewritten = response.content[0].text.strip()

        # Sanity check: don't use if it's way longer or empty
        if rewritten and len(rewritten) < len(query) * 3:
            log_with_context(logger, "info", "Query rewritten",
                           original=query, rewritten=rewritten, latency_ms=round(duration_ms, 1))
            query_cache.set(cache_key, rewritten)

            # Phase 3: Langfuse AI Observability
            log_rewrite_trace(
                original_query=query,
                rewritten_query=rewritten,
                model=model,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                duration_ms=duration_ms,
                tags=["intent:rewrite", "quality:success", "stage:search_phase"],
                journey_stage="search_phase",
            )

            return rewritten

        log_with_context(logger, "warning", "Rewrite rejected (too long/empty)", rewritten=rewritten)
        return query

    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        metrics.inc("rewrite_errors")
        log_with_context(logger, "error", "Query rewrite failed",
                        error=str(e), error_type=type(e).__name__, latency_ms=round(duration_ms, 1))
        return query


@retry_with_backoff(
    max_retries=3,
    base_delay=1.0,
    max_delay=30.0,
    exceptions=(anthropic.APIConnectionError, anthropic.RateLimitError, anthropic.APIStatusError),
    logger_name="jarvis.llm.retry"
)
def _call_anthropic_with_retry(client, model: str, max_tokens: int, system: str, messages: list):
    """
    Call Anthropic API with retry for transient errors.

    Retries on:
    - APIConnectionError: Network issues, timeouts
    - RateLimitError: 429 Too Many Requests
    - APIStatusError: 500/502/503 server errors

    Does NOT retry on:
    - AuthenticationError: Invalid API key
    - BadRequestError: Malformed request
    """
    try:
        return client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=messages
        )
    except anthropic.APIStatusError as e:
        # Only retry on 5xx errors, not 4xx
        if e.status_code >= 500:
            raise  # Will be caught by retry decorator
        # 4xx errors should not be retried
        raise


def _classify_llm_error(e: Exception) -> dict:
    """
    Classify an LLM error for better handling and reporting.

    Returns dict with:
    - category: 'rate_limit', 'overloaded', 'network', 'auth', 'invalid_request', 'unknown'
    - recoverable: bool
    - retry_after: suggested wait time in seconds (or None)
    - message: human-readable error message
    """
    error_str = str(e).lower()
    error_type = type(e).__name__

    if isinstance(e, anthropic.RateLimitError):
        return {
            "category": "rate_limit",
            "recoverable": True,
            "retry_after": 60,
            "message": "API rate limit exceeded - waiting before retry"
        }

    if isinstance(e, anthropic.APIConnectionError):
        return {
            "category": "network",
            "recoverable": True,
            "retry_after": 10,
            "message": "Network connection error - check internet connectivity"
        }

    if isinstance(e, anthropic.AuthenticationError):
        return {
            "category": "auth",
            "recoverable": False,
            "retry_after": None,
            "message": "API authentication failed - check API key"
        }

    if isinstance(e, anthropic.BadRequestError):
        return {
            "category": "invalid_request",
            "recoverable": False,
            "retry_after": None,
            "message": f"Invalid request: {str(e)[:100]}"
        }

    if isinstance(e, anthropic.APIStatusError):
        if e.status_code == 529 or "overloaded" in error_str:
            return {
                "category": "overloaded",
                "recoverable": True,
                "retry_after": 120,
                "message": "API is overloaded - try again later"
            }
        if e.status_code >= 500:
            return {
                "category": "server_error",
                "recoverable": True,
                "retry_after": 30,
                "message": f"API server error ({e.status_code})"
            }

    return {
        "category": "unknown",
        "recoverable": True,
        "retry_after": 10,
        "message": f"Unknown error: {error_type}"
    }

# =============================================================================
# UNCERTAINTY SIGNALING (Phase 18.2)
# =============================================================================

# Words/phrases that indicate ambiguous queries
AMBIGUOUS_INDICATORS = [
    "that", "those", "this", "these", "it", "they", "them",
    "the thing", "the stuff", "the one", "the same",
    "ding", "sache", "das", "die", "der",  # German
    "irgendwas", "irgendwie", "halt", "nochmal",
    "letzte woche", "kürzlich", "neulich", "damals",
]


def calculate_response_confidence(
    query: str,
    search_results: List[Dict[str, Any]],
    max_confidence: float = 0.8
) -> Dict[str, Any]:
    """
    Calculate confidence score for a response based on query clarity and retrieval quality.

    Returns:
        Dict with:
        - score: 0.0-0.8 confidence score (capped at max_confidence)
        - factors: breakdown of contributing factors
        - level: "high", "medium", "low"
        - indicator: emoji indicator (🟢🟡🔴)
    """
    factors = {}

    # 1. Query clarity (0.0-1.0)
    # Lower score for ambiguous queries
    query_lower = query.lower()
    ambiguous_count = sum(1 for term in AMBIGUOUS_INDICATORS if term in query_lower)
    query_word_count = len(query.split())

    # Short queries with ambiguous terms are less clear
    if query_word_count <= 3:
        query_clarity = 0.5
    elif ambiguous_count >= 2:
        query_clarity = 0.4
    elif ambiguous_count == 1:
        query_clarity = 0.7
    else:
        query_clarity = 1.0

    factors["query_clarity"] = round(query_clarity, 2)

    # 2. Retrieval quality (0.0-1.0)
    # Based on search result scores
    if not search_results:
        retrieval_quality = 0.2  # No context = low confidence
    else:
        scores = [r.get("score", 0) or 0 for r in search_results]
        avg_score = sum(scores) / len(scores) if scores else 0
        max_score = max(scores) if scores else 0

        # Weighted average: best result matters more
        retrieval_quality = (max_score * 0.6 + avg_score * 0.4)

        # Penalize if top score is too low
        if max_score < 0.5:
            retrieval_quality *= 0.7

    factors["retrieval_quality"] = round(retrieval_quality, 2)

    # 3. Context coverage (0.0-1.0)
    # More results = better coverage (up to a point)
    result_count = len(search_results)
    if result_count == 0:
        context_coverage = 0.2
    elif result_count < 3:
        context_coverage = 0.6
    elif result_count < 5:
        context_coverage = 0.8
    else:
        context_coverage = 1.0

    factors["context_coverage"] = round(context_coverage, 2)

    # Calculate weighted score
    raw_score = (
        query_clarity * 0.25 +
        retrieval_quality * 0.50 +
        context_coverage * 0.25
    )

    # Cap at max_confidence (Jarvis should never be 100% certain)
    final_score = min(raw_score, max_confidence)

    # Determine level and indicator
    if final_score >= 0.7:
        level = "high"
        indicator = "🟢"
    elif final_score >= 0.5:
        level = "medium"
        indicator = "🟡"
    else:
        level = "low"
        indicator = "🔴"

    return {
        "score": round(final_score, 2),
        "factors": factors,
        "level": level,
        "indicator": indicator,
    }


def format_confidence_prefix(confidence: Dict[str, Any], threshold: float = 0.7) -> str:
    """
    Format confidence prefix for response (only shown when below threshold).

    Returns empty string if confidence is above threshold.
    """
    score = confidence.get("score", 0.8)
    if score >= threshold:
        return ""  # Don't show for high confidence

    indicator = confidence.get("indicator", "🟡")
    percentage = int(score * 100)

    # ADHD-friendly: short and clear
    return f"{indicator} ~{percentage}% sicher: "


def build_context(search_results: List[Dict[str, Any]]) -> str:
    """Build context string from search results"""
    if not search_results:
        return "No relevant documents found in the knowledge base."

    context_parts = []
    for i, result in enumerate(search_results, 1):
        meta = result.get("metadata", {})
        doc_type = meta.get("doc_type", "document")
        channel = meta.get("channel", "")
        source = meta.get("source_path", "unknown")
        text = result.get("text", "")
        score = result.get("score", 0)

        # Build source description
        if doc_type == "email":
            label = meta.get("label", "")
            source_desc = f"Email ({label}, {channel})"
        elif doc_type == "chat_window":
            source_desc = f"Chat ({channel})"
        else:
            source_desc = f"Document ({doc_type})"

        context_parts.append(f"[Source {i}] {source_desc}\nPath: {source}\nRelevance: {score:.2f}\n---\n{text}\n")

    return "\n".join(context_parts)


def _derive_langfuse_tags(query: str, search_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Derive Langfuse tags and metadata from query and search results."""
    tags = []
    query_lc = (query or "").lower()

    intent = "chat"
    if any(k in query_lc for k in ["remember", "merken", "speichere", "save"]):
        intent = "remember"
    elif any(k in query_lc for k in ["analy", "analyse", "bewerte", "bewertung"]):
        intent = "analyze"
    elif any(k in query_lc for k in ["summar", "zusammenfass", "summary"]):
        intent = "summary"
    elif any(k in query_lc for k in ["search", "find", "suche", "finden"]):
        intent = "search"

    tags.append(f"intent:{intent}")
    tags.append("quality:success")
    tags.append("stage:action_phase")

    domain = "unknown"
    for result in search_results or []:
        source_path = (result.get("metadata", {}) or {}).get("source_path", "")
        if "work_" in source_path or "projektil" in source_path:
            domain = "work"
            break
        if "personal" in source_path:
            domain = "personal"
            break
        if "coaching" in source_path:
            domain = "coaching"
            break

    tags.append(f"domain:{domain}")

    return {
        "tags": tags,
        "metadata": {
            "intent": intent,
            "domain": domain,
            "journey_stage": "action_phase",
        }
    }

def chat_with_context(
    query: str,
    search_results: List[Dict[str, Any]],
    conversation_history: List[Dict[str, str]] = None,
    model: str = "claude-sonnet-4-20250514",
    max_tokens: int = 1024,
    user_id: int = None,
    stream_callback: Any = None,
) -> Dict[str, Any]:
    """
    Generate a response using Claude with RAG context and conversation history

    Args:
        query: User's question
        search_results: Results from semantic search
        conversation_history: List of previous messages [{"role": "user/assistant", "content": "..."}]
        model: Claude model to use (default: claude-sonnet-4-20250514 for balance of speed/quality)
        max_tokens: Max response tokens
        user_id: User ID for loading session memory and preferences (Phase 17.2)

    Returns:
        Dict with 'answer', 'model', 'usage'
    """
    start_time = time.time()
    first_token_ms: float | None = None
    log_with_context(logger, "info", "Chat generation started",
                    query_len=len(query), context_chunks=len(search_results), model=model)

    client = get_client()
    context = build_context(search_results)

    # Build messages list with conversation history
    messages = []

    # Add conversation history (limited to last N turns to manage context)
    if conversation_history:
        for msg in conversation_history[-10:]:  # Keep last 10 messages (5 turns)
            messages.append({
                "role": msg["role"],
                "content": msg["content"]
            })

    # Add current query with RAG context
    user_message = f"""Here is relevant context from my personal knowledge base:

{context}

---

My question: {query}"""

    messages.append({"role": "user", "content": user_message})

    try:
        # Include self-model for personality persistence
        system_prompt = get_system_prompt_with_self_model()

        # Phase 17.2 Integration: Add session memory and user preferences
        if user_id:
            try:
                from . import session_manager
                from .person_intelligence import ProfileAssembler

                # Session context (recent conversations, pending actions, frequent topics)
                session_ctx = session_manager.build_context_prompt(
                    user_id=user_id,
                    current_query=query,
                    days_back=7
                )
                if session_ctx and session_ctx.strip():
                    system_prompt += f"\n\n=== SESSION MEMORY ===\n{session_ctx}"

                # User preferences (communication style, detail level, negative prefs)
                pref_ctx = ProfileAssembler.get_prompt_context(user_id)
                if pref_ctx and pref_ctx != "No profile data available yet.":
                    system_prompt += f"\n\n=== USER PREFERENCES ===\n{pref_ctx}"

                log_with_context(logger, "debug", "Session context loaded",
                                user_id=user_id, has_session_ctx=bool(session_ctx),
                                has_prefs=bool(pref_ctx))
            except Exception as e:
                log_with_context(logger, "warning", "Could not load session context",
                                user_id=user_id, error=str(e))

            # Phase 18.2: Active Lessons from Cross-Session Learning
            try:
                from .cross_session_learner import cross_session_learner
                active_lessons = cross_session_learner.get_active_lessons(user_id, min_confidence=0.6)
                if active_lessons:
                    lessons_text = "\n".join([
                        f"- {l['lesson_text']} (effectiveness: {l['effectiveness']:.0%})"
                        for l in active_lessons[:5]
                    ])
                    system_prompt += f"\n\n=== LEARNED PATTERNS ===\nThese patterns have been observed across previous sessions:\n{lessons_text}"
                    log_with_context(logger, "debug", "Lessons loaded",
                                    user_id=user_id, lesson_count=len(active_lessons))
            except Exception as e:
                log_with_context(logger, "debug", "Could not load lessons", error=str(e))

        if stream_callback:
            # Stream response chunks (perceived latency improvement) while still returning a full result.
            with client.messages.stream(
                model=model,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=messages,
            ) as stream:
                parts: list[str] = []
                for chunk in stream.text_stream:
                    if first_token_ms is None:
                        first_token_ms = (time.time() - start_time) * 1000
                        metrics.timing("chat_first_token_ms", first_token_ms)
                        metrics.inc("chat_stream_requests")
                    parts.append(chunk)
                    try:
                        stream_callback(chunk)
                    except Exception:
                        # Never let streaming callbacks break core execution
                        pass
                response = stream.get_final_message()
            streamed_text = "".join(parts)
            # Prefer the streamed text; if it is empty, fall back to the final message blocks.
            if streamed_text.strip():
                response_text = streamed_text
            else:
                response_text = "".join([b.text for b in response.content if b.type == "text"])
        else:
            response = _call_anthropic_with_retry(
                client, model, max_tokens=max_tokens,
                system=system_prompt, messages=messages
            )
            response_text = response.content[0].text

        duration_ms = (time.time() - start_time) * 1000
        metrics.timing("chat_latency_ms", duration_ms)
        metrics.inc("chat_requests")
        metrics.inc("chat_tokens_in", response.usage.input_tokens)
        metrics.inc("chat_tokens_out", response.usage.output_tokens)
        metrics.inc("llm_api_calls_total")
        metrics.timing("llm_response_time_ms", duration_ms)

        log_with_context(logger, "info", "Chat generation complete",
                        latency_ms=round(duration_ms, 1),
                        tokens_in=response.usage.input_tokens,
                        tokens_out=response.usage.output_tokens)

        # Phase 18.2: Calculate response confidence
        from . import config
        confidence = calculate_response_confidence(
            query=query,
            search_results=search_results,
            max_confidence=config.CONFIDENCE_MAX
        )

        log_with_context(logger, "debug", "Response confidence calculated",
                        confidence_score=confidence["score"],
                        confidence_level=confidence["level"],
                        factors=confidence["factors"])

        # Phase 3: Langfuse AI Observability
        langfuse_info = _derive_langfuse_tags(query, search_results)
        log_chat_trace(
            query=query,
            response=response_text,
            model=model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            duration_ms=duration_ms,
            user_id=str(user_id) if user_id else None,
            context_chunks=len(search_results),
            metadata={**langfuse_info["metadata"], "confidence": confidence["score"]},
            tags=langfuse_info["tags"],
            journey_stage=langfuse_info["metadata"]["journey_stage"],
        )

        return {
            "answer": response_text,
            "model": model,
            "usage": {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens
            },
            "confidence": confidence
        }
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        metrics.inc("chat_errors")
        metrics.inc("llm_api_errors_total")
        
        # Track rate limit errors specifically
        if isinstance(e, anthropic.RateLimitError):
            metrics.inc("llm_rate_limit_errors_total")
            log_with_context(logger, "warning", "LLM rate limit hit", 
                           error=str(e), latency_ms=round(duration_ms, 1))
        else:
            log_with_context(logger, "error", "Chat generation failed",
                           error=str(e), error_type=type(e).__name__, latency_ms=round(duration_ms, 1))

        # Error-first monitoring in Langfuse
        langfuse_info = _derive_langfuse_tags(query, search_results)
        error_tags = [tag for tag in langfuse_info["tags"] if not tag.startswith("quality:")]
        error_tags.append("quality:failed")
        log_chat_trace(
            query=query,
            response="",
            model=model,
            input_tokens=0,
            output_tokens=0,
            duration_ms=duration_ms,
            user_id=str(user_id) if user_id else None,
            context_chunks=len(search_results),
            metadata={
                **langfuse_info["metadata"],
                "error_type": type(e).__name__,
                "error_message": str(e)[:500],
            },
            tags=error_tags,
            journey_stage=langfuse_info["metadata"]["journey_stage"],
        )

        raise


# ============ Profile Extraction ============

PROFILE_EXTRACTION_PROMPT = """Du bist ein Experte für Persönlichkeitsanalyse. Analysiere die folgenden Chat-Nachrichten und extrahiere ein Persönlichkeitsprofil für die angegebene Person.

WICHTIG:
- Basiere ALLE Aussagen nur auf den gegebenen Nachrichten
- Wenn etwas nicht erkennbar ist, setze null
- Sei konservativ - lieber weniger behaupten als falsch raten
- Confidence Score: 0.0-1.0 basierend auf Datenmenge und Klarheit

Extrahiere folgende Informationen als JSON:

```json
{
    "display_name": "string - Wie die Person sich nennt/genannt wird",
    "communication_style": {
        "formality": "formal|semi_formal|informal|very_casual|null",
        "typical_length": "short|medium|long|null",
        "emoji_usage": "none|minimal|moderate|heavy|null",
        "response_speed": "immediate|same_day|slow|null",
        "greeting_style": "string|null",
        "sign_off_style": "string|null"
    },
    "personality_indicators": {
        "decision_style": "analytical|intuitive|collaborative|quick|null",
        "stress_indicators": ["string"] oder [],
        "strengths": ["string"] oder [],
        "topics_of_interest": ["string"] oder []
    },
    "relationship_context": {
        "apparent_role": "string|null - z.B. 'Kollege', 'Chef', 'Freund'",
        "interaction_tone": "professional|friendly|casual|mixed|null",
        "shared_topics": ["string"] oder []
    },
    "meta": {
        "confidence_score": 0.0-1.0,
        "evidence_summary": "string - Kurze Begründung für die Einschätzungen",
        "needs_more_data": true|false
    }
}
```

Antworte NUR mit dem JSON, ohne zusätzlichen Text."""


def extract_profile_from_messages(
    person_name: str,
    messages: List[Dict[str, Any]],
    existing_profile: Dict[str, Any] = None,
    model: str = "claude-3-5-haiku-20241022"
) -> Dict[str, Any]:
    """
    Extract personality profile from chat messages using LLM.

    Args:
        person_name: Name of the person to analyze
        messages: List of messages with 'sender', 'text', 'ts' fields
        existing_profile: Optional existing profile to merge with
        model: LLM model to use (Haiku for speed/cost)

    Returns:
        Dict with extracted profile fields and confidence score
    """
    start_time = time.time()
    log_with_context(logger, "info", "Profile extraction started",
                    person=person_name, message_count=len(messages))

    if not messages:
        return {
            "status": "no_data",
            "error": "No messages provided for analysis"
        }

    # Filter messages involving this person
    person_messages = []
    for msg in messages:
        sender = msg.get("sender") or msg.get("author") or msg.get("from", "")
        if person_name.lower() in sender.lower():
            person_messages.append(msg)

    if not person_messages:
        # Include all messages but note this person is a participant
        person_messages = messages

    # Build message context (limit to avoid token limits)
    message_texts = []
    for msg in person_messages[-50:]:  # Last 50 messages
        sender = msg.get("sender") or msg.get("author") or msg.get("from", "Unknown")
        text = msg.get("text") or msg.get("content", "")
        ts = msg.get("ts", "")
        if text:
            message_texts.append(f"[{ts}] {sender}: {text}")

    if not message_texts:
        return {
            "status": "no_content",
            "error": "Messages have no text content"
        }

    messages_context = "\n".join(message_texts)

    # Build prompt
    user_prompt = f"""Analysiere die folgenden Chat-Nachrichten und erstelle ein Profil für: {person_name}

NACHRICHTEN:
{messages_context}

Extrahiere das Persönlichkeitsprofil als JSON:"""

    try:
        client = get_client()

        response = _call_anthropic_with_retry(
            client, model, max_tokens=1500,
            system=PROFILE_EXTRACTION_PROMPT,
            messages=[{"role": "user", "content": user_prompt}]
        )

        duration_ms = (time.time() - start_time) * 1000
        metrics.timing("profile_extraction_latency_ms", duration_ms)
        metrics.inc("profile_extractions")
        metrics.inc("profile_extraction_tokens_in", response.usage.input_tokens)
        metrics.inc("profile_extraction_tokens_out", response.usage.output_tokens)

        # Parse JSON response
        response_text = response.content[0].text.strip()

        # Handle markdown code blocks
        if response_text.startswith("```"):
            lines = response_text.split("\n")
            # Remove first and last lines (```json and ```)
            json_lines = [l for l in lines if not l.startswith("```")]
            response_text = "\n".join(json_lines)

        import json
        try:
            extracted = json.loads(response_text)
        except json.JSONDecodeError as e:
            log_with_context(logger, "warning", "Profile extraction JSON parse failed",
                           error=str(e), response_preview=response_text[:200])
            metrics.inc("profile_extraction_parse_errors")
            return {
                "status": "parse_error",
                "error": f"Failed to parse LLM response as JSON: {str(e)}",
                "raw_response": response_text[:500],
                "recoverable": True,
                "hint": "The LLM response was not valid JSON. This can happen with unusual message content."
            }

        # Merge with existing profile if provided
        if existing_profile:
            extracted = _merge_profile_extractions(existing_profile, extracted)

        confidence = extracted.get("meta", {}).get("confidence_score", 0)

        log_with_context(logger, "info", "Profile extraction complete",
                        person=person_name,
                        confidence=confidence,
                        latency_ms=round(duration_ms, 1))

        # Phase 3: Langfuse AI Observability
        log_profile_extraction_trace(
            person_name=person_name,
            messages_analyzed=len(person_messages),
            model=model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            duration_ms=duration_ms,
            confidence_score=confidence,
            tags=["intent:profile", "quality:success", "stage:memory_update"],
            journey_stage="memory_update",
        )

        return {
            "status": "success",
            "person_name": person_name,
            "profile": extracted,
            "messages_analyzed": len(person_messages),
            "usage": {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens
            }
        }

    except anthropic.AuthenticationError as e:
        duration_ms = (time.time() - start_time) * 1000
        metrics.inc("profile_extraction_auth_errors")
        log_with_context(logger, "error", "Profile extraction auth failed",
                        person=person_name, latency_ms=round(duration_ms, 1))
        return {
            "status": "auth_error",
            "error": "API authentication failed - check API key",
            "recoverable": False
        }

    except anthropic.RateLimitError as e:
        duration_ms = (time.time() - start_time) * 1000
        metrics.inc("profile_extraction_rate_limits")
        error_info = _classify_llm_error(e)
        log_with_context(logger, "warning", "Profile extraction rate limited",
                        person=person_name, latency_ms=round(duration_ms, 1))
        return {
            "status": "rate_limited",
            "error": error_info["message"],
            "recoverable": True,
            "retry_after": error_info["retry_after"]
        }

    except anthropic.APIStatusError as e:
        duration_ms = (time.time() - start_time) * 1000
        error_info = _classify_llm_error(e)
        metrics.inc(f"profile_extraction_{error_info['category']}")
        log_with_context(logger, "error", "Profile extraction API error",
                        person=person_name, category=error_info["category"],
                        status_code=e.status_code, latency_ms=round(duration_ms, 1))
        return {
            "status": "api_error",
            "error": error_info["message"],
            "recoverable": error_info["recoverable"],
            "retry_after": error_info["retry_after"],
            "details": {"status_code": e.status_code, "category": error_info["category"]}
        }

    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        metrics.inc("profile_extraction_errors")
        error_info = _classify_llm_error(e)
        log_with_context(logger, "error", "Profile extraction failed",
                        person=person_name, error=str(e),
                        error_type=type(e).__name__, latency_ms=round(duration_ms, 1))
        return {
            "status": "error",
            "error": str(e)[:200],
            "error_type": type(e).__name__,
            "recoverable": error_info["recoverable"],
            "retry_after": error_info["retry_after"]
        }


def _merge_profile_extractions(existing: Dict, new: Dict) -> Dict:
    """
    Merge new extraction with existing profile.
    Prefers new data but keeps existing if new is null/empty.
    """
    result = existing.copy()

    for key, new_value in new.items():
        if new_value is None:
            continue

        if key not in result or result[key] is None:
            result[key] = new_value
        elif isinstance(new_value, dict) and isinstance(result.get(key), dict):
            # Recursively merge dicts
            result[key] = _merge_profile_extractions(result[key], new_value)
        elif isinstance(new_value, list) and isinstance(result.get(key), list):
            # Merge lists, avoiding duplicates
            existing_set = set(result[key])
            for item in new_value:
                if item not in existing_set:
                    result[key].append(item)
        elif new_value:  # Only override if new value is truthy
            result[key] = new_value

    return result


def extract_profile_with_retry(
    person_name: str,
    messages: List[Dict[str, Any]],
    existing_profile: Dict[str, Any] = None,
    max_retries: int = 2,
    model: str = "claude-3-5-haiku-20241022"
) -> Dict[str, Any]:
    """
    Extract profile with retry logic for transient failures.

    This provides an additional layer of retry beyond what _call_anthropic_with_retry
    handles, specifically for cases where the extraction succeeds but returns
    recoverable errors (like rate limits that exceeded all internal retries).
    """
    last_result = None

    for attempt in range(max_retries + 1):
        result = extract_profile_from_messages(person_name, messages, existing_profile, model)

        # Success - return immediately
        if result.get("status") == "success":
            if attempt > 0:
                log_with_context(logger, "info", "Profile extraction succeeded on retry",
                               person=person_name, attempt=attempt + 1)
            return result

        last_result = result

        # Check if error is recoverable
        if not result.get("recoverable", False):
            log_with_context(logger, "warning", "Non-recoverable extraction error",
                           person=person_name, error=result.get("error"))
            return result

        # Check if we should retry
        if attempt < max_retries:
            retry_after = result.get("retry_after", 5)
            log_with_context(logger, "info", "Retrying profile extraction",
                           person=person_name, attempt=attempt + 1,
                           max_retries=max_retries, wait_seconds=retry_after)
            _sleep(retry_after)
        else:
            log_with_context(logger, "warning", "Profile extraction failed after retries",
                           person=person_name, attempts=max_retries + 1)

    return last_result


def extract_profiles_from_chat_batch(
    messages: List[Dict[str, Any]],
    namespace: str,
    min_messages_per_person: int = 3,
    max_profiles: int = 20,
    skip_on_rate_limit: bool = True
) -> Dict[str, Any]:
    """
    Extract profiles for all participants in a chat batch.

    Args:
        messages: All messages from the chat
        namespace: Namespace for context
        min_messages_per_person: Minimum messages to attempt extraction
        max_profiles: Maximum number of profiles to extract (avoid runaway costs)
        skip_on_rate_limit: If True, stop extraction on rate limit errors

    Returns:
        Dict with profiles per person and summary stats
    """
    # Count messages per participant
    participant_counts = {}
    for msg in messages:
        sender = msg.get("sender") or msg.get("author") or msg.get("from")
        if sender:
            participant_counts[sender] = participant_counts.get(sender, 0) + 1

    # Filter participants with enough messages
    eligible = {p: c for p, c in participant_counts.items() if c >= min_messages_per_person}

    # Sort by message count (most active first) and limit
    sorted_eligible = sorted(eligible.items(), key=lambda x: -x[1])[:max_profiles]

    log_with_context(logger, "info", "Batch profile extraction",
                    total_participants=len(participant_counts),
                    eligible=len(eligible),
                    processing=len(sorted_eligible),
                    namespace=namespace)

    results = {
        "profiles": {},
        "skipped": [],
        "errors": [],
        "rate_limited": False
    }

    # Self/system names to skip
    skip_names = {"micha", "ich", "me", "system", "bot", "jarvis", "assistant"}

    for person_name, msg_count in sorted_eligible:
        # Skip if it looks like "me" or system
        if person_name.lower().strip() in skip_names:
            results["skipped"].append({
                "person": person_name,
                "reason": "self_or_system",
                "message_count": msg_count
            })
            continue

        # Use retry-enabled extraction
        extraction = extract_profile_with_retry(person_name, messages)

        if extraction.get("status") == "success":
            results["profiles"][person_name] = extraction["profile"]
            results["profiles"][person_name]["_meta"] = {
                "messages_analyzed": extraction.get("messages_analyzed", 0),
                "tokens_used": extraction.get("usage", {})
            }

        elif extraction.get("status") == "rate_limited":
            results["errors"].append({
                "person": person_name,
                "error": extraction.get("error", "Rate limited"),
                "status": "rate_limited",
                "recoverable": True
            })
            if skip_on_rate_limit:
                results["rate_limited"] = True
                log_with_context(logger, "warning", "Stopping batch due to rate limit",
                               processed=len(results["profiles"]),
                               remaining=len(sorted_eligible) - len(results["profiles"]) - len(results["skipped"]) - len(results["errors"]))
                break

        else:
            results["errors"].append({
                "person": person_name,
                "error": extraction.get("error", "Unknown error"),
                "status": extraction.get("status", "error"),
                "recoverable": extraction.get("recoverable", False)
            })

    results["summary"] = {
        "total_participants": len(participant_counts),
        "eligible_participants": len(eligible),
        "profiles_extracted": len(results["profiles"]),
        "skipped": len(results["skipped"]),
        "errors": len(results["errors"]),
        "rate_limited": results["rate_limited"]
    }

    log_with_context(logger, "info", "Batch extraction complete",
                    profiles=len(results["profiles"]),
                    errors=len(results["errors"]),
                    rate_limited=results["rate_limited"])

    return results
