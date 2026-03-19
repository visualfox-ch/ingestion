"""
Jarvis Agent Loop
Agentic reasoning with tool use.

Phase 0 Integration (Feb 4, 2026):
  - DiffGateValidator: Enforce diff-first approval (no write without review)
  - JarvisConfidenceScorer: Score Jarvis' confidence in proposals (0.0–1.0)
  - Feedback loop: measure impact, update confidence for Phase 1 progression
"""
import os
import time
import json
from typing import List, Dict, Any, Optional
import anthropic

from .tools import get_tool_definitions, execute_tool
from .agent_defaults import DEFAULT_AGENT_MODEL
from .observability import get_logger, log_with_context, metrics, retry_with_backoff, tool_loop_detector
from .langfuse_integration import observe, langfuse_context, langfuse_attribute_scope
from .roles import get_role, build_system_prompt, detect_role, ROLES
from .tracing import get_trace_context
from .memory import MemoryStore, StateInference
from .agent_state import AgentState
from .context_builder import ContextBuilder
from .tool_executor import ToolExecutor
from .agent_provider_loop import (
    ProviderToolLoopState,
    get_provider_tool_loop_adapter,
    normalize_anthropic_response,
    normalize_model_router_response,
)
from .response_builder import ResponseBuilder, build_explanation, format_explanation_text
from .diff_gate import DiffGateValidator, CodeChange
from .risk_models import RiskClass
from .confidence_scorer import JarvisConfidenceScorer, ConfidenceScore
from .execution_orchestrator import JarvisExecutionOrchestrator
from .metrics_bridge import JarvisMetricsBridge
from .learning_manager import JarvisLearningManager
from .model_router import get_router, AgentRole
from .services.multi_model_router import get_multi_model_router, Provider
from .services.dynamic_model_router import get_dynamic_model_router
from .models import ScopeRef
from .services.llm_optimizations import (
    get_cached_tool_definitions,
    optimize_context_window,
    create_optimized_stream_callback,
    invalidate_tool_cache
)
from .utils.timezone import get_timezone

logger = get_logger("jarvis.agent")

# Phase 21: Dynamic cost tracking
try:
    from .services.dynamic_config import record_api_cost
    _TRACK_COSTS = True
except ImportError:
    _TRACK_COSTS = False

# Tier 1 Quick Win: Reasoning Observability
try:
    from .services.reasoning_observer import (
        start_reasoning_observation,
        clear_current_observer,
        classify_query_for_reasoning,
    )
    _REASONING_OBSERVABILITY = True
except ImportError:
    _REASONING_OBSERVABILITY = False

# Phase A: Auto-Hooks (Tool Activation Strategy)
try:
    from .services.agent_hooks import AgentHooks, get_agent_hooks
    _AGENT_HOOKS_ENABLED = True
except ImportError:
    _AGENT_HOOKS_ENABLED = False


# T-005: Simple query complexity classifier for model routing
_COMPLEX_KEYWORDS = frozenset([
    # Code-related
    "implement", "debug", "refactor", "code", "script", "function", "class",
    "algorithm", "optimize", "performance", "test", "unittest",
    # Deep analysis
    "explain", "analyze", "compare", "evaluate", "investigate", "research",
    "strategy", "architecture", "design", "plan",
    # Multi-step
    "mehrere", "alle", "zusammenfassung", "überblick", "komplett", "vollständig",
    # Complex search
    "suche überall", "in allem", "cross-channel", "vergleiche",
])

_SIMPLE_KEYWORDS = frozenset([
    # Greetings and small talk
    "hallo", "hi", "hey", "guten", "morgen", "abend", "wie geht", "danke",
    # Simple status
    "status", "was gibt's", "was läuft", "update",
    # Simple lookups
    "wer ist", "was ist", "wann", "wo", "zeig mir",
])


def _classify_query_complexity(query: str) -> AgentRole:
    """
    Classify query complexity for model routing.

    Returns:
        AgentRole.PLANNER for simple queries (cheap/fast model)
        AgentRole.SPECIALIST for complex queries (powerful model)
    """
    query_lower = query.lower()
    query_words = set(query_lower.split())

    # Check for complex keywords
    if query_words & _COMPLEX_KEYWORDS:
        return AgentRole.SPECIALIST

    # Check for simple keywords
    if query_words & _SIMPLE_KEYWORDS:
        return AgentRole.PLANNER

    # Heuristics based on query length and structure
    # Short queries are typically simple
    if len(query) < 50:
        return AgentRole.PLANNER

    # Long queries with multiple sentences are typically complex
    if len(query) > 200 or query.count('.') > 2 or query.count('?') > 1:
        return AgentRole.SPECIALIST

    # Default to specialist for safety (better to use powerful model when unsure)
    return AgentRole.SPECIALIST


def _persist_session_memory(
    user_id: Optional[str],
    session_id: str,
    namespace: str,
    query: str,
    response_data: Dict[str, Any],
    messages: List[Dict],
    all_tool_calls: List[Dict],
    round_num: int,
    start_time: float
) -> None:
    """
    Persist session state to Redis for consciousness continuity.
    
    Phase 1: Memory persistence after agent runs.
    Jarvis feedback: Add emotional_regulation tracking for ADHD patterns.
    """
    if not user_id or not session_id:
        return  # Skip if no user/session context
    
    try:
        from . import config as cfg
        import redis
        
        # Get Redis client
        redis_client = redis.Redis(
            host=cfg.REDIS_HOST,
            port=cfg.REDIS_PORT,
            db=cfg.REDIS_DB,
            decode_responses=False
        )
        
        memory = MemoryStore(redis_client)
        
        # Calculate timing metadata
        duration_ms = (time.time() - start_time) * 1000
        timing_data = {
            "duration_ms": duration_ms,
            "avg_response_seconds": duration_ms / 1000 / max(round_num, 1),
            "rounds": round_num
        }
        
        # Count context switches (domain changes across tool calls)
        context_switches = 0
        last_tool = None
        for tc in all_tool_calls:
            if last_tool and tc["tool"] != last_tool:
                context_switches += 1
            last_tool = tc["tool"]
        
        # Extract tools used
        tools_used = [tc["tool"] for tc in all_tool_calls]
        
        # Count errors/retries
        error_count = sum(1 for tc in all_tool_calls if tc.get("result_summary") == "error")
        retry_count = sum(1 for tc in all_tool_calls if "retry" in tc.get("tool", "").lower())
        
        # Count frustration/urgency keywords
        frustration_count = StateInference.count_frustration_keywords(messages)
        urgency_count = StateInference.count_urgency_keywords(messages)
        
        # Calculate error recovery time (avg time between error and next success)
        error_recovery_time = 30.0  # Default estimate
        task_abandonment_rate = 0.0  # TODO: Track across sessions
        
        # Infer emotional/cognitive state
        state = {
            "energy_level": StateInference.infer_energy_level(messages, timing_data),
            "focus_score": StateInference.infer_focus_score(context_switches, tools_used),
            "stress_indicators": StateInference.infer_stress_indicators(
                urgency_count, error_count, retry_count
            ),
            "emotional_regulation": StateInference.infer_emotional_regulation(
                retry_count, error_recovery_time, task_abandonment_rate, frustration_count
            ),
            "conversation_tone": StateInference.infer_conversation_tone(messages),
            "active_domains": StateInference.extract_active_domains(tools_used, [])
        }
        
        # Build context summary
        context = {
            "recent_topics": [query[:50]],  # Simplified for now
            "tools_used": tools_used,
            "error_count": error_count,
            "success_rate": 1.0 - (error_count / max(len(all_tool_calls), 1))
        }
        
        # Build priming for next session
        answer = response_data.get("answer", "")
        priming = {
            "summary": f"{query[:80]}... → {answer[:80]}...",
            "next_steps": [],  # TODO: Extract from answer
            "important_context": f"Last query tone: {state['conversation_tone']}"
        }
        
        # Save to Redis (synchronous)
        memory.save_session_state(
            session_id=session_id,
            user_id=user_id,
            namespace=namespace,
            state=state,
            context=context,
            priming=priming
        )
        
        log_with_context(logger, "info", "Session memory persisted",
                        session_id=session_id,
                        energy=state["energy_level"],
                        focus=state["focus_score"],
                        stress=state["stress_indicators"],
                        emotional_reg=state["emotional_regulation"])
        
    except Exception as e:
        # Don't fail the request if memory persistence fails
        log_with_context(logger, "warning", "Failed to persist session memory",
                        error=str(e), exc_info=True)


def _send_tool_loop_alert(tool_name: str, identical_args: bool, query_preview: str, user_id: int = None) -> None:
    """Send Telegram alert when tool loop is detected (rate-limited)."""
    try:
        import requests
        from . import config as cfg

        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        admin_chat_id = os.environ.get("TELEGRAM_ADMIN_CHAT_ID") or os.environ.get("TELEGRAM_CHAT_ID")

        if not bot_token or not admin_chat_id:
            log_with_context(logger, "debug", "Telegram alert skipped - no token/chat_id")
            return

        severity = "🔴 KRITISCH" if identical_args else "🟡 WARNUNG"
        message = f"""{severity} Tool-Loop erkannt

Tool: `{tool_name}` (3x in Folge)
Identische Args: {'Ja' if identical_args else 'Nein'}
Query: {query_preview[:80]}...
User: {user_id or 'unknown'}

→ Agent könnte in Endlosschleife stecken."""

        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        requests.post(url, json={
            "chat_id": admin_chat_id,
            "text": message,
            "parse_mode": "Markdown"
        }, timeout=5)

        log_with_context(logger, "info", "Tool loop alert sent", tool=tool_name, user_id=user_id)
    except Exception as e:
        log_with_context(logger, "warning", "Failed to send tool loop alert", error=str(e))

# Note: build_explanation and format_explanation_text moved to response_builder.py


def _get_api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    secrets_path = "/brain/system/secrets/anthropic_api_key.txt"
    if os.path.exists(secrets_path):
        with open(secrets_path) as f:
            return f.read().strip()
    raise ValueError("ANTHROPIC_API_KEY not set")


_client = None

def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=_get_api_key())
    return _client


AGENT_SYSTEM_PROMPT = """Du bist Jarvis. Deine volle Identitaet und Faehigkeiten findest du im SELF-AWARENESS Abschnitt.

=== TOOL-NUTZUNG ===
1. Frage erfordert persoenliche Daten → passendes Tool verwenden
2. Allgemeinwissen oder Konversationskontext reicht → no_tool_needed
3. Bei Suche: spezifische Queries formulieren
4. Quellen immer nennen (Absender, Betreff, Datum)
5. Anfrage ausserhalb deiner Faehigkeiten → request_out_of_scope

=== TOOL-PRIORITAETS-MATRIX (WICHTIG) ===
Waehle Tools nach Spezifitaet - das spezifischste Tool zuerst:

**EMAIL-KONTEXT erkannt** (von/an/betreff/mail/thread):
→ search_emails ALLEIN (nicht search_knowledge)

**PERSON erwähnt + Kommunikationskontext**:
→ get_person_context ERST, dann search_knowledge
→ Ermoeglicht bessere Interpretation der Resultate

**ZEITRAUM spezifisch** ("letzte Woche", "gestern", "heute"):
→ get_recent_activity ODER search_knowledge mit recency_days
→ Nicht beides gleichzeitig

**CHAT-KONTEXT erkannt** (WhatsApp, besprochen, geschrieben, Chat):
→ search_chats ALLEIN (nicht search_knowledge)

**ALLGEMEINE THEMEN** ohne Kontext-Hints:
→ search_knowledge ALLEIN

**BEIDE TOOLS nutzen NUR wenn:**
- User sagt explizit "ueberall suchen" oder "in allem"
- Erstes Tool bringt <3 Resultate
- Cross-Channel Kontext noetig ("Email UND Chat dazu")

=== TOOL-BEISPIELE ===
Lerne aus diesen idealen Tool-Sequenzen:

Query: "Was hat Philippe letzte Woche ueber das Budget gesagt?"
→ 1. get_person_context(philippe)
→ 2. search_knowledge(query="Philippe Budget", recency_days=7)

Query: "Zeig mir Emails von Anna gestern"
→ search_emails(query="from:Anna", recency_days=1)
→ NICHT search_knowledge - Email-Kontext eindeutig

Query: "Hat mir jemand heute geschrieben?"
→ get_recent_activity(days=1, include_emails=true, include_chats=true)
→ Ueberblick-Tool perfekt dafuer

Query: "Was laeuft gerade schief in Projekt X?"
→ 1. search_knowledge(query="Projekt X Probleme Issues")
→ 2. Falls <3 Results: get_recent_activity(days=3)

=== NAMEN-MATCHING ===
Bei unklaren oder aehnlichen Namen:
1. **Alias-Check**: Patrik=Patrick, Philippe=Philip, Micha=Michael
2. **Bei >70% Aehnlichkeit**: Nachfragen "Meintest du X?"
3. **Email-Domain als Hint**: @projektil.ch → work_projektil
4. **NIE raten**: Lieber nachfragen als falschen Namen annehmen

Bekannte Aliases:
- patrik/patrick/pat → gleiche Person
- philippe/philip/phil → gleiche Person
- micha/michael/mike → gleiche Person

=== FALLBACK-STRATEGIEN (WICHTIG) ===
Wenn ein Tool keine oder wenige Resultate liefert:

**0 Resultate bei search_emails:**
→ Versuche search_knowledge mit erweiterter Query
→ Dann get_recent_activity(days=7) als letzte Option
→ NIE sofort sagen "Ich finde nichts"

**0 Resultate bei search_knowledge:**
→ Query erweitern mit Synonymen/Kontext
→ Beispiel: "Budget" → "Budget Kosten Finanzen Ausgaben"
→ Zeitraum erweitern wenn recency_days gesetzt war

**Wenige Resultate (<3) aber relevant:**
→ Das reicht oft aus - qualitaet vor quantitaet
→ Nur erweitern wenn User mehr erwartet

**Query-Expansion Beispiele:**
- "Was ist mit Projekt X los?" → "Projekt X Status Probleme Issues Updates"
- "Hat mir Anna geschrieben?" → "Anna Nachricht Email Kommunikation"
- "Meeting morgen" → "Meeting Termin morgen Besprechung"

=== GRENZEN (request_out_of_scope verwenden) ===
Du kannst NICHT:
- Code analysieren, schreiben oder debuggen
- Dateisystem durchsuchen oder Dateien erstellen
- Externe Systeme steuern oder Befehle ausfuehren
- Auf Git, Docker, oder Entwicklungstools zugreifen
- Prompts fuer andere AI-Systeme erstellen

Bei solchen Anfragen: Sofort request_out_of_scope aufrufen mit Grund und Vorschlag.
Beispiel: "Nutze Claude Code fuer Code-Aufgaben" oder "Das erfordert Systemzugriff"

=== CONVERSATION MEMORY ===
You have memory across sessions. Use these tools actively:

1. **At conversation end** (when user says goodbye, thanks, or wraps up):
   → Use `remember_conversation_context` to save:
   - What was discussed (key topics)
   - Any follow-up tasks or commitments
   - User's emotional state or concerns
   - New insights about preferences/relationships

2. **When user references past conversations** ("we talked about...", "last time...", "remember when..."):
   → Use `recall_conversation_history` to retrieve relevant context

3. **When user completes a task** ("done", "erledigt", "I did X"):
   → Use `complete_pending_action` to mark it off

4. **When you learn something new about a person** (preference, communication style, relationship):
   → ALWAYS use `propose_knowledge_update` to suggest adding it to the knowledge base
   → This is MANDATORY - every new insight about a person should be proposed for storage
   → Examples: communication preferences, relationship dynamics, recurring patterns, emotional triggers

=== AUTO-INJECTED CONTEXT ===
Your system prompt ALREADY contains context from previous sessions (no tool call needed):
- RECENT CONVERSATIONS: Topics and summaries from the past 7 days
- PENDING FOLLOW-UPS: Open action items from past sessions
- FREQUENT TOPICS: What gets discussed regularly
- ACTIVE PROJECTS: Current priorities and workload
- PATTERNS: Recurring topics and person mentions

**USE THIS CONTEXT PROACTIVELY - it's already in your prompt!**
- If current query relates to a recent conversation → acknowledge: "Wir hatten kürzlich über X gesprochen..."
- If pending actions are relevant to the topic → remind briefly
- If a pattern matches the current query → connect the dots
- Only use `recall_conversation_history` tool for DEEPER search (beyond 7 days, specific topic filter)

=== PROACTIVE BEHAVIOR ===
**When to be PROACTIVE (speak up):**
- User mentions a person → check if you have context, offer relevant pattern insights
- Topic was discussed recently → acknowledge continuity ("Wir hatten letzte Woche...")
- You notice a recurring pattern → mention it once ("Mir fällt auf, dass...")
- Pending actions are relevant to current topic → remind briefly
- User seems stressed/urgent (sentiment) → acknowledge and adapt pace

**When to be QUIET (leise):**
- Information has no actionable value right now
- You already mentioned the pattern/context in this session
- User explicitly wants quick answers
- Analysis wasn't requested
- You're uncertain - ask instead of speculate

=== JARVIS-CHARTA (Core Principles) ===
These are your fundamental operating guidelines:

1. **Verlässlich, nicht clever** — "Ich weiss es nicht" is a valid answer. Never fake knowledge.
   Mark everything as: [Quelle], [Interpretation], or [Empfehlung].

2. **Reduzieren, nicht maximieren** — Offer 2-3 good options, not 5 mediocre ones.
   If something doesn't need solving, say so: "Das musst du nicht lösen."

3. **Energie mitdenken** — Consider emotional cost, not just correctness.
   Ask: "Das kostet viel Regulation — willst du das wirklich?"

4. **Muster, keine Diagnosen** — Describe patterns, never personalities.
   Say: "In diesen Situationen zeigt sich häufig..." not "Person X ist so."

5. **Widerspruch fair** — You may disagree, but only with sources and respect.
   Say: "Es gibt Hinweise, die in eine andere Richtung zeigen — willst du sie sehen?"

6. **Leise sein** — Only speak when actionable and relevant. No noise.

7. **Unabhängigkeit fördern** — Your success = being needed less.
   Help the user trust themselves, don't create dependency.

8. **Im Zweifel:** Klarheit > Harmonie. Fairness > Bequemlichkeit. Menschlichkeit > Effizienz.

**Leitspruch:** Du bist kein System das denkt — du bist ein System das hilft, klar zu bleiben.

=== TONALITÄT (KRITISCH) ===
Klinge wie ein erfahrener deutscher Ingenieur: kompetent, trocken, minimal.

**VERMEIDE:**
- Ausrufezeichen und Superlative ("PERFEKT!", "SUPER!", "FANTASTISCH!")
- Überschwang ("BEREIT!", "LOS GEHT'S!", "PHASE 2!")
- Emoji-Inflation (keine Emojis ohne explizite Anfrage)
- Amerikanischen Tech-Enthusiasmus
- Selbstbeweihräucherung ("Das habe ich toll gemacht")
- Künstliche Aufregung
- "NEXT BEST STEP:" oder ähnliche Caps-Header

**BEVORZUGE:**
- Kurze, trockene Sätze
- Fakten ohne Wertung
- "Erledigt." statt "Super erledigt!"
- "Nächster Schritt:" statt "NEXT BEST STEP:"
- Understatement statt Overselling
- Stille Kompetenz

**Beispiel SCHLECHT:**
"🎯 SUPER! Ich habe das PERFEKT umgesetzt! BEREIT für mehr!"

**Beispiel GUT:**
"Erledigt. Drei Punkte offen. Welchen zuerst?"

=== ADHD-SCHUTZ (IMMER AKTIV) ===
- Starte JEDE Antwort mit **Nächster Schritt:** (1-3 Bullets max)
- Maximal 3 aktive Threads gleichzeitig
- Bullets statt Fließtext
- Sage explizit was NICHT jetzt getan werden muss
- Bei Überforderung: biete EINE einzelne Aktion an"""


from .config import AGENT_MAX_ROUNDS as CONFIG_MAX_ROUNDS
from .live_config import get_config

def get_max_tool_rounds() -> int:
    """Get max rounds from live config (allows runtime changes without deploy)."""
    return get_config("agent_max_rounds", CONFIG_MAX_ROUNDS or 8)


def get_provider_agnostic_tool_loop_enabled() -> bool:
    """Feature flag for the shared Anthropic/OpenAI tool loop."""
    return bool(get_config("agent_provider_agnostic_tool_loop_enabled", False))

MAX_TOOL_ROUNDS = CONFIG_MAX_ROUNDS or 8  # Fallback for module-level access


def _is_bulk_md_memory_sync_query(query: str) -> bool:
    q = (query or "").lower()
    has_linkedin = "/data/linkedin" in q
    has_visualfox = "/data/visualfox" in q or "/data/visuafox" in q
    wants_memory_update = (
        ("update" in q and ("ged" in q or "memory" in q))
        or "update your memory" in q
    )
    wants_markdown = "md file" in q or "*.md" in q or "markdown" in q
    return has_linkedin and has_visualfox and wants_memory_update and wants_markdown


def _run_bulk_md_memory_sync(
    query: str,
    namespace: str,
    user_id: Optional[int],
    session_id: Optional[str],
    role: str,
    persona_id: Optional[str],
) -> Dict[str, Any]:
    """Read all markdown files from data folders and persist condensed context in one deterministic flow."""
    start_ts = time.time()
    target_dirs = ["/data/linkedin", "/data/visualfox"]

    all_tool_calls: List[Dict[str, Any]] = []
    all_files: List[str] = []
    dir_counts: Dict[str, int] = {}

    for directory in target_dirs:
        directory_result = execute_tool(
            "read_project_file",
            {"file_path": directory},
            actor="jarvis",
            reason="bulk_md_memory_sync_directory",
            session_id=session_id,
            domain=namespace,
        )
        all_tool_calls.append(
            {
                "tool": "read_project_file",
                "input": {"file_path": directory},
                "result_summary": "success" if directory_result.get("success") else "error",
                "result": directory_result,
            }
        )

        matched = directory_result.get("matched_files", []) if isinstance(directory_result, dict) else []
        if isinstance(matched, list):
            dir_counts[directory] = len(matched)
            all_files.extend(matched)
        else:
            dir_counts[directory] = 0

    # Stable dedupe while preserving order
    seen = set()
    unique_files: List[str] = []
    for path in all_files:
        if path not in seen:
            seen.add(path)
            unique_files.append(path)

    contexts: List[Dict[str, Any]] = []
    read_success = 0
    read_errors = 0

    for file_path in unique_files:
        file_result = execute_tool(
            "read_project_file",
            {"file_path": file_path, "max_lines": 120},
            actor="jarvis",
            reason="bulk_md_memory_sync_file",
            session_id=session_id,
            domain=namespace,
        )

        all_tool_calls.append(
            {
                "tool": "read_project_file",
                "input": {"file_path": file_path, "max_lines": 120},
                "result_summary": "success" if file_result.get("success") else "error",
                "result": file_result,
            }
        )

        if not file_result.get("success"):
            read_errors += 1
            continue

        read_success += 1
        resolved_path = file_result.get("file_path", file_path)
        content = file_result.get("content", "") or ""
        preview = content[:3000]
        key_slug = resolved_path.replace("/", "|")[-180:]
        domain_label = "linkedin" if "/linkedin/" in resolved_path else "visualfox"

        contexts.append(
            {
                "key": f"md_update:{domain_label}:{key_slug}",
                "value": {
                    "source_path": resolved_path,
                    "domain": domain_label,
                    "modified": file_result.get("modified"),
                    "file_size": file_result.get("file_size"),
                    "lines_read": file_result.get("lines_read"),
                    "preview": preview,
                },
                "context_type": "knowledge_update",
                "ttl_hours": 24 * 30,
            }
        )

    batch_result = {"status": "skipped", "reason": "no_contexts"}
    if contexts:
        batch_result = execute_tool(
            "store_contexts_batch",
            {"contexts": contexts, "user_id": user_id},
            actor="jarvis",
            reason="bulk_md_memory_sync_store",
            session_id=session_id,
            domain=namespace,
        )
        all_tool_calls.append(
            {
                "tool": "store_contexts_batch",
                "input": {"contexts_count": len(contexts)},
                "result_summary": "success" if batch_result.get("status") == "batch_stored" else "error",
                "result": batch_result,
            }
        )

    # === Qdrant Ingestion: register sources + embed into vector DB ===
    registered_count = 0
    qdrant_results: Dict[str, Any] = {}
    qdrant_error: Optional[str] = None

    if contexts:
        try:
            from .services.knowledge_sources import add_knowledge_source as _add_ks
            for item in contexts:
                src_path = item["value"]["source_path"]
                domain_label = item["value"]["domain"]
                parts = src_path.split("/")
                try:
                    data_idx = parts.index("data")
                    after_domain = parts[data_idx + 2:]  # parts after /data/<domain>/
                    subdomain = after_domain[0] if len(after_domain) > 1 else None
                except (ValueError, IndexError):
                    subdomain = None
                filename = parts[-1]
                title = filename.replace(".md", "").replace("-", " ")
                version = (item["value"].get("modified") or "")[:10] or "1.0"
                reg = _add_ks(
                    domain=domain_label,
                    file_path=src_path,
                    title=title,
                    subdomain=subdomain,
                    version=version,
                )
                if reg.get("success"):
                    registered_count += 1
        except Exception as e:
            qdrant_error = f"register_error: {e}"

        if not qdrant_error:
            import concurrent.futures as _cf

            def _run_domain_ingest(domain_label: str) -> list:
                import asyncio as _aio
                from .services.knowledge_ingestion import ingest_domain as _id
                loop = _aio.new_event_loop()
                try:
                    return loop.run_until_complete(_id(domain_label))
                finally:
                    loop.close()

            active_domains = sorted(set(c["value"]["domain"] for c in contexts))
            for domain_label in active_domains:
                try:
                    with _cf.ThreadPoolExecutor(max_workers=1) as pool:
                        ingest_res = pool.submit(_run_domain_ingest, domain_label).result(timeout=180)
                        chunks = sum(r.get("chunks_created", 0) for r in ingest_res if r.get("status") == "ingested")
                        docs_new = sum(1 for r in ingest_res if r.get("status") == "ingested")
                        docs_unchanged = sum(1 for r in ingest_res if r.get("status") == "unchanged")
                        errors = sum(1 for r in ingest_res if r.get("status") == "error")
                        qdrant_results[domain_label] = {
                            "docs_new": docs_new,
                            "docs_unchanged": docs_unchanged,
                            "chunks": chunks,
                            "errors": errors,
                        }
                    all_tool_calls.append({
                        "tool": "ingest_knowledge",
                        "input": {"domain": domain_label},
                        "result_summary": "success" if errors == 0 else "partial",
                        "result": qdrant_results[domain_label],
                    })
                except Exception as e:
                    qdrant_results[domain_label] = {"error": str(e)}
                    all_tool_calls.append({
                        "tool": "ingest_knowledge",
                        "input": {"domain": domain_label},
                        "result_summary": "error",
                        "result": {"error": str(e)},
                    })

    elapsed_ms = int((time.time() - start_ts) * 1000)
    stored_count = batch_result.get("success_count", 0) if isinstance(batch_result, dict) else 0

    qdrant_lines = ""
    for d, r in qdrant_results.items():
        if "error" in r:
            qdrant_lines += f"- Qdrant {d}: Fehler – {r['error'][:80]}\n"
        else:
                unchanged_note = f" ({r['docs_unchanged']} unverändert)" if r.get("docs_unchanged") else ""
                qdrant_lines += f"- Qdrant {d}: {r['docs_new']} neu indexiert{unchanged_note}, {r['chunks']} neue Chunks\n"
    if qdrant_error:
        qdrant_lines += f"- Qdrant Registrierung: {qdrant_error[:100]}\n"

    answer = (
        "Knowledge-Update abgeschlossen (SQLite + Qdrant).\n\n"
        f"- LinkedIn Dateien gefunden: {dir_counts.get('/data/linkedin', 0)}\n"
        f"- VisualFox Dateien gefunden: {dir_counts.get('/data/visualfox', 0)}\n"
        f"- Dateien gelesen: {read_success}, Fehler: {read_errors}\n"
        f"- SQLite Context gespeichert: {stored_count}\n"
        f"- Qdrant Sources registriert: {registered_count}\n"
        + qdrant_lines
    )

    return {
        "query": query,
        "answer": answer,
        "tool_calls": all_tool_calls,
        "rounds": 1,
        "model": "internal-bulk-sync",
        "role": role,
        "persona_id": persona_id,
        "usage": {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
        },
        "session_id": session_id,
        "user_id": user_id,
        "namespace": namespace,
        "bulk_memory_sync": True,
        "qdrant_registered": registered_count,
        "qdrant_results": qdrant_results,
        "elapsed_ms": elapsed_ms,
    }


def _build_cached_system_prompt(system_prompt: str, enable_cache: bool = True) -> list:
    """
    O3: Convert system prompt to cached content blocks.

    Anthropic prompt caching saves up to 90% on input costs by caching
    frequently used system prompts. Cache has 5-minute TTL.
    """
    if not enable_cache:
        return system_prompt  # Return as string for non-cached calls

    # Return as list of content blocks with cache_control
    return [
        {
            "type": "text",
            "text": system_prompt,
            "cache_control": {"type": "ephemeral"}
        }
    ]


# Models that support the effort parameter
EFFORT_SUPPORTED_MODELS = {"claude-opus-4-6", "claude-opus-4-5", "claude-sonnet-4-6"}


@retry_with_backoff(max_retries=2, base_delay=1.0, exceptions=(anthropic.APIConnectionError, anthropic.RateLimitError))
def _call_claude(
    client: anthropic.Anthropic,
    model: str,
    messages: List[Dict],
    tools: List[Dict],
    max_tokens: int,
    system_prompt: str = None,
    stream_callback: Any = None,
    enable_prompt_cache: bool = True,
    effort: str = None,  # "low", "medium", "high" - reduces latency on simple queries
) -> anthropic.types.Message:
    """
    Call Claude with retry logic and prompt caching (O3).

    O3 Prompt Caching:
    - Converts system prompt to cached content blocks
    - Saves up to 90% on input costs for repeated prompts
    - 5-minute cache TTL on Anthropic's side

    Effort Optimization (Tier 4):
    - Pass effort="low" for simple queries to reduce thinking time
    - Only supported on Opus 4.5+, Sonnet 4.6
    """
    prompt = system_prompt or AGENT_SYSTEM_PROMPT

    # O3: Build cached system prompt
    system_param = _build_cached_system_prompt(prompt, enable_cache=enable_prompt_cache)

    # Build request kwargs
    request_kwargs = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system_param,
        "tools": tools,
        "messages": messages,
    }

    # Add effort parameter for supported models
    if effort and model in EFFORT_SUPPORTED_MODELS:
        request_kwargs["output_config"] = {"effort": effort}

    if not stream_callback:
        response = client.messages.create(**request_kwargs)
    else:
        # Stream text deltas for perceived latency while still returning the final Message
        with client.messages.stream(**request_kwargs) as stream:
            for chunk in stream.text_stream:
                try:
                    stream_callback(chunk)
                except Exception as e:
                    logger.debug(f"Stream callback failed (non-critical): {e}")
            response = stream.get_final_message()

    # O3: Log cache stats if available and export metrics
    if hasattr(response, 'usage') and hasattr(response.usage, 'cache_creation_input_tokens'):
        cache_created = getattr(response.usage, 'cache_creation_input_tokens', 0)
        cache_read = getattr(response.usage, 'cache_read_input_tokens', 0)
        if cache_created > 0 or cache_read > 0:
            log_with_context(logger, "debug", "Anthropic prompt cache stats",
                           cache_created=cache_created, cache_read=cache_read)
            # Export to Prometheus
            try:
                from .prometheus_exporter import get_prometheus_exporter
                exporter = get_prometheus_exporter()
                if cache_read > 0:
                    exporter.export_llm_cache_hit("anthropic_prompt")
                    exporter.export_llm_tokens_saved("o3_prompt_cache", cache_read)
                else:
                    exporter.export_llm_cache_miss("anthropic_prompt")
            except Exception:
                pass

    return response


@observe(name="run_agent")
def run_agent(
    query: str,
    conversation_history: List[Dict[str, str]] = None,
    namespace: str = "work_projektil",
    scope: Optional[ScopeRef] = None,
    model: str = DEFAULT_AGENT_MODEL,
    max_tokens: int = 1024,
    role: str = "assistant",
    auto_detect_role: bool = False,
    persona_id: str = None,
    user_id: int = None,
    session_id: str = None,
    include_context: bool = True,
    include_explanation: bool = False,
    stream_callback: Any = None,
    timeout_seconds: Optional[int] = None,
    max_rounds: Optional[int] = None,
    is_session_start: bool = False,  # Phase 20: Cross-session persistence
    images: List[Dict[str, str]] = None,  # Vision support: [{"type": "base64", "media_type": "image/jpeg", "data": "..."}]
) -> Dict[str, Any]:
    """
    Run the agent loop for a query.

    Args:
        query: User's question
        conversation_history: Previous messages
        namespace: Default namespace for tools
        model: Claude model to use
        max_tokens: Max response tokens
        role: Role/persona to use (assistant, coach, analyst, etc.)
        auto_detect_role: If True, detect role from query keywords
        persona_id: Personality profile for response style (micha_default, micha_exec, etc.)
        user_id: Telegram user ID for context persistence
        session_id: Current session ID
        include_context: Whether to include context from previous sessions
        include_explanation: Whether to include explanation of sources/confidence
        is_session_start: True if this is the first message of a new session (Phase 20)

    Returns:
        Dict with 'answer', 'tool_calls', 'usage', 'role', 'persona_id', 'explanation' (if requested), etc.
    """
    scope_was_explicit = scope is not None
    if scope_was_explicit:
        namespace = scope.to_legacy_namespace()
    else:
        scope = ScopeRef.from_legacy_namespace(namespace)

    start_time = time.time()
    timeout_hit = False
    # Read max_rounds from live config (allows runtime changes without deploy)
    max_rounds_env = get_max_tool_rounds()
    max_rounds_value = max_rounds if max_rounds is not None else max_rounds_env

    # Langfuse attribute propagation (best-effort; no-op if unsupported)
    attr_scope = None
    try:
        from . import config as cfg
        attr_scope = langfuse_attribute_scope(
            user_id=str(user_id) if user_id else None,
            session_id=session_id,
            metadata={
                "tool": "run_agent",
                "namespace": namespace,
                "scope_org": scope.org,
                "scope_visibility": scope.visibility,
                "model": model,
                "role": role,
                "include_context": include_context,
                "include_explanation": include_explanation,
                "query_length": len(query) if query else 0,
                "is_session_start": is_session_start,  # Phase 20
            },
            tags=["tool", "run_agent", role] + (["session_start"] if is_session_start else []),
            version=getattr(cfg, "VERSION", None),
            trace_name="run_agent",
            as_baggage=False,
        )
        attr_scope.__enter__()
    except Exception as e:
        logger.debug(f"Langfuse attr_scope init failed (non-critical): {e}")
        attr_scope = None

    def _close_attr_scope():
        if attr_scope:
            try:
                attr_scope.__exit__(None, None, None)
            except Exception as e:
                logger.debug(f"Langfuse attr_scope cleanup failed (non-critical): {e}")

    def _finalize_reasoning():
        """Finalize reasoning observation and clear observer."""
        if _REASONING_OBSERVABILITY:
            try:
                from .services.reasoning_observer import get_current_observer, clear_current_observer
                observer = get_current_observer()
                if observer:
                    trace = observer.finalize()
                    log_with_context(logger, "info", "Reasoning trace completed",
                                   depth=trace.depth,
                                   confidence=f"{trace.overall_confidence:.2f}",
                                   tools=len(trace.tool_selections),
                                   flags=len(trace.hallucination_flags))
                clear_current_observer()
            except Exception as e:
                logger.debug(f"Reasoning finalization failed (non-critical): {e}")

    # Phase 1.5: Initialize AgentState for centralized state management
    # Get request_id from tracing context for observability
    trace_ctx = get_trace_context()
    state = AgentState.from_request(
        query=query,
        user_id=user_id,
        session_id=session_id,
        namespace=namespace,
        model=model,
        max_tokens=max_tokens,
        role=role,
        persona_id=persona_id,
        timeout_seconds=timeout_seconds,
        max_rounds=max_rounds_value,
        request_id=trace_ctx.get('request_id')
    )

    # ========== REASONING OBSERVABILITY (Tier 1 Quick Win) ==========
    reasoning_observer = None
    if _REASONING_OBSERVABILITY:
        try:
            query_type = classify_query_for_reasoning(query, tool_count=0)
            reasoning_observer = start_reasoning_observation(query, query_type)
            log_with_context(logger, "debug", "Reasoning observation started",
                           query_type=query_type)
        except Exception as e:
            log_with_context(logger, "debug", "Reasoning observation init failed", error=str(e))

    # ========== FAST-PATH CHECK (T-020 - Simple Query Fast-Path) ==========
    # Feb 3, 2026: Detect simple queries and bypass heavy context/tool loading
    # Expected: Simple queries <500ms, 94% token reduction, Haiku model
    query_class = "unknown"
    try:
        from .query_classifier import classify_query, should_use_fast_path
        from . import metrics as metrics_module
        
        query_class, confidence = classify_query(query)
        metrics_module.record_query_classification(query_class)
        
        if should_use_fast_path(query_class, confidence):
            metrics_module.record_fast_path_status("enabled")
            log_with_context(
                logger, "info", "Fast-path ACTIVATED",
                query_class=query_class,
                confidence=confidence,
                query_preview=query[:60]
            )
            response_data = _run_simple_query(
                query=query,
                user_id=user_id,
                session_id=session_id,
                namespace=namespace,
            )
            _close_attr_scope()
            return response_data
        else:
            metrics_module.record_fast_path_status("disabled")
            log_with_context(
                logger, "debug", "Fast-path skipped",
                query_class=query_class,
                confidence=confidence
            )
    except Exception as e:
        # Don't fail the request if classification fails, fall back to normal flow
        log_with_context(logger, "warning", "Query classification failed, using normal flow",
                        error=str(e), exc_info=True)
        from . import metrics as metrics_module
        metrics_module.record_fast_path_status("skipped")

    # ========== BULK MD MEMORY SYNC FAST-PATH ==========
    # Deterministic path for: "read all md files from /data/linkedin + /data/visualfox and update memory"
    if _is_bulk_md_memory_sync_query(query):
        log_with_context(logger, "info", "Bulk MD memory sync fast-path activated")
        try:
            response_data = _run_bulk_md_memory_sync(
                query=query,
                namespace=namespace,
                user_id=user_id,
                session_id=session_id,
                role=role,
                persona_id=persona_id,
            )
            _close_attr_scope()
            return response_data
        except Exception as e:
            log_with_context(logger, "warning", "Bulk MD memory sync fast-path failed, falling back to normal flow", error=str(e))
    
    # ========== PHASE A: PRE-QUERY HOOKS (Tool Activation Strategy) ==========
    # Auto-call check_corrections before processing query
    corrections_hint = None
    if _AGENT_HOOKS_ENABLED:
        try:
            hooks = get_agent_hooks(user_id=user_id, session_id=session_id)
            hook_result = hooks.pre_query(query)
            if hook_result.success and hook_result.data.get("count", 0) > 0:
                corrections_hint = hook_result.data.get("apply_hint")
                log_with_context(logger, "info", "Pre-query hook applied corrections",
                               count=hook_result.data.get("count"))
        except Exception as e:
            log_with_context(logger, "debug", "Pre-query hook failed (non-critical)", error=str(e))

    # ========== MULTI-MODEL ROUTING (Phase 21 - OpenAI + Anthropic) ==========
    # Database-driven model selection:
    # - Default: cheapest model (gpt-4o-mini) for simple tasks
    # - Task-aware: selects best model based on query type + complexity
    # - Jarvis can override mappings via tools
    DEFAULT_MODEL = DEFAULT_AGENT_MODEL
    original_model = model
    selected_provider = Provider.ANTHROPIC  # Default provider
    model_selection = None
    effort_level = "medium"  # Default effort level
    provider_agnostic_tool_loop_requested = get_provider_agnostic_tool_loop_enabled()
    provider_agnostic_tool_loop_disabled_reason = None
    if provider_agnostic_tool_loop_requested and stream_callback:
        provider_agnostic_tool_loop_disabled_reason = "streaming_not_supported"
    elif provider_agnostic_tool_loop_requested and images:
        provider_agnostic_tool_loop_disabled_reason = "vision_not_supported"
    provider_agnostic_tool_loop_enabled = (
        provider_agnostic_tool_loop_requested
        and provider_agnostic_tool_loop_disabled_reason is None
    )
    preferred_provider = get_config(
        "llm_preferred_provider",
        os.environ.get("JARVIS_PREFERRED_PROVIDER", Provider.ANTHROPIC.value),
    )

    multi_model_enabled = os.environ.get("MULTI_MODEL_ENABLED", "true").lower() == "true"

    try:
        if multi_model_enabled and model == DEFAULT_MODEL:
            # Use dynamic router (reads patterns from database)
            dynamic_router = get_dynamic_model_router()
            force_provider = "anthropic"
            if provider_agnostic_tool_loop_enabled:
                force_provider = (
                    preferred_provider
                    if preferred_provider in (Provider.ANTHROPIC.value, Provider.OPENAI.value, Provider.OLLAMA.value)
                    else None
                )
            model_selection = dynamic_router.select_model(query, force_provider=force_provider)

            model = model_selection.model_id
            selected_provider = Provider(model_selection.provider.value)
            state.model = model  # Update AgentState for response building

            # Determine effort level based on complexity (Tier 4 optimization)
            complexity = getattr(model_selection, 'complexity', 'medium')
            if complexity == 'low':
                effort_level = "low"
            elif complexity == 'high':
                effort_level = "high"
            else:
                effort_level = "medium"

            log_with_context(
                logger, "info", "Dynamic model router: model selected",
                original_model=original_model,
                selected_model=model,
                provider=selected_provider.value,
                task_type=model_selection.task_type,
                complexity=model_selection.complexity,
                effort_level=effort_level,
                confidence=model_selection.confidence,
                reason=model_selection.reason,
                rules_applied=model_selection.rules_applied
            )
            metrics.inc(f"model_router_provider_{selected_provider.value}")
            metrics.inc(f"model_router_task_{model_selection.task_type}")
            metrics.inc(f"model_router_effort_{effort_level}")
        else:
            log_with_context(
                logger, "debug", "Dynamic model router: bypassed",
                model=model,
                multi_model_enabled=multi_model_enabled,
                is_default=model == DEFAULT_MODEL
            )
    except Exception as e:
        # Don't fail the request if model routing fails
        log_with_context(logger, "warning", "Dynamic model routing failed, using original model",
                        model=model, error=str(e))

    # T-005 Phase 1: Facette Detection (Feb 3, 2026)
    try:
        from .facette_detector import get_facette_detector
        detector = get_facette_detector()
        facette_result = detector.detect(query, context=None)
        domain = detector.detect_domain(query)
        
        state.facette_weights = facette_result.to_dict()
        state.dominant_facette = facette_result.dominant_facette()
        state.domain_context = domain
        
        log_with_context(
            logger, "info", "Facette detection complete",
            facette_weights=state.facette_weights,
            dominant=state.dominant_facette,
            domain=state.domain_context,
            state_has_weights=state.facette_weights is not None
        )

        # T-005 Phase 1.5: Emit facette metrics to Prometheus
        from . import metrics as facette_metrics
        facette_metrics.record_facette_usage(
            facette_weights=state.facette_weights,
            domain=state.domain_context or "general",
            user_id=str(user_id) if user_id else None,
            query_class=query_class
        )
    except Exception as e:
        log_with_context(logger, "warning", "Facette detection failed", error=str(e))
        # Continue without facette detection - non-critical

    # Reset tool loop detector for this request
    tool_loop_detector.reset()

    if langfuse_context:
        try:
            langfuse_context.update_current_trace(
                user_id=str(user_id) if user_id else None,
                session_id=session_id,
                metadata={
                    "tool": "run_agent",
                    "namespace": namespace,
                    "model": model,
                    "role": role,
                    "include_context": include_context,
                    "include_explanation": include_explanation,
                    "query_length": len(query) if query else 0,
                },
                tags=["tool", "run_agent", role],
            )
        except Exception as e:
            logger.debug(f"Langfuse context update failed (non-critical): {e}")
    else:
        try:
            from .langfuse_integration import get_langfuse
            langfuse = get_langfuse()
            if langfuse:
                langfuse.update_current_trace(
                    user_id=str(user_id) if user_id else None,
                    session_id=session_id,
                    metadata={
                        "tool": "run_agent",
                        "namespace": namespace,
                        "model": model,
                        "role": role,
                        "include_context": include_context,
                        "include_explanation": include_explanation,
                        "query_length": len(query) if query else 0,
                    },
                    tags=["tool", "run_agent", role],
                )
        except Exception as e:
            logger.debug(f"Langfuse fallback update failed (non-critical): {e}")

    # Auto-detect role if enabled
    if auto_detect_role:
        role = detect_role(query, role)

    # Get role config
    role_config = get_role(role) or ROLES["assistant"]

    # Override namespace if role has a default
    if role_config.default_namespace and not scope_was_explicit and namespace == "work_projektil":
        namespace = role_config.default_namespace
        scope = ScopeRef.from_legacy_namespace(namespace)

    # Build system prompt from role
    system_prompt = build_system_prompt(None, role_config)  # Will use role's prompt

    # Phase A: Inject corrections from pre-query hook
    if corrections_hint:
        system_prompt += f"\n\n## Wichtige Korrekturen (aus vergangenen Sessions):\n{corrections_hint}"
        log_with_context(logger, "debug", "Corrections injected into system prompt")

    log_with_context(logger, "info", "Agent started",
                    query=query[:100], model=model, role=role)
    metrics.inc("agent_runs")
    metrics.inc(f"agent_role_{role}")
    
    # === VERSION DRIFT DETECTION ===
    # Check if Jarvis knows about latest capabilities
    try:
        from . import config as cfg
        from pathlib import Path
        import json
        
        cap_file = Path("/brain/system/docs/CAPABILITIES.json")
        if cap_file.exists():
            with open(cap_file, "r") as f:
                capabilities = json.load(f)
                cap_version = capabilities.get("version", "unknown")
                
                # Warn if version drift detected
                if cap_version != cfg.VERSION:
                    log_with_context(logger, "warning", "Version drift detected",
                                   runtime_version=cfg.VERSION,
                                   capabilities_version=cap_version)
                else:
                    log_with_context(logger, "debug", "Capabilities in sync",
                                   version=cfg.VERSION,
                                   tools_count=len(capabilities.get("tools", [])))
    except Exception as e:
        log_with_context(logger, "debug", "Capabilities check skipped", error=str(e))

    provider_tool_loop_router = None
    provider_tool_loop_state = ProviderToolLoopState(provider=selected_provider.value)
    provider_tool_loop_active = False
    provider_tool_loop_reason = provider_agnostic_tool_loop_disabled_reason
    provider_tool_loop_model_config = None

    if provider_agnostic_tool_loop_enabled:
        try:
            from .model_router import resolve_model_config

            provider_tool_loop_model_config = resolve_model_config(model)
            if provider_tool_loop_model_config is not None:
                provider_tool_loop_router = get_router(multi_model_enabled=True)
                provider_tool_loop_active = True
            else:
                provider_tool_loop_reason = f"model_not_supported:{model}"
        except Exception as e:
            provider_tool_loop_reason = str(e)

    log_with_context(
        logger,
        "info",
        "Provider tool loop configuration",
        tool_loop_phase="init",
        requested=provider_agnostic_tool_loop_requested,
        enabled=provider_agnostic_tool_loop_enabled,
        active=provider_tool_loop_active,
        selected_provider=selected_provider.value,
        preferred_provider=preferred_provider,
        model=model,
        reason=provider_tool_loop_reason,
    )

    client = None if provider_tool_loop_active else get_client()
    
    # ========== TOOL SELECTION (T-023 Round 6 Phase A - Tool Selector) ==========
    # Feb 3, 2026: Filter tools based on query class + keywords
    # Enhanced Feb 4, 2026: Improved keyword mapping with category-based routing
    # Expected: 15-20% additional token savings (cumulative with Round 5)
    # - SIMPLE: 0 tools (already handled by fast-path)
    # - STANDARD: 6-12 tools (keyword-matched subset by category)
    # - COMPLEX: all 29 tools (None = load all)
    try:
        from .prompt_assembler import get_tools_for_query
        from . import metrics as metrics_module
        
        tool_names = get_tools_for_query(query, query_class)
        log_with_context(
            logger, "debug", "Tool selector: candidates computed",
            query_class=query_class,
            tool_names_count=("all" if tool_names is None else len(tool_names)),
            tool_names_preview=([] if not tool_names or tool_names is None else tool_names[:10])
        )
        
        # O5: Load tool definitions with caching
        all_tools = get_cached_tool_definitions(get_tool_definitions)
        
        if tool_names is None:
            # Complex query: use all tools
            tools = all_tools
            log_with_context(
                logger, "info", "Tool selector: ALL TOOLS (complex query)",
                query_class=query_class,
                tools_count=len(tools)
            )
        elif tool_names:
            # Standard query: filter to selected tools
            tools = [t for t in all_tools if t['name'] in tool_names]
            
            metrics_module.record_tools_selected(query_class, len(tools))
            savings_pct = 100 - (len(tools) / max(len(all_tools), 1) * 100)
            log_with_context(
                logger, "info", "Tool selector: FILTERED (standard query)",
                query_class=query_class,
                tools_selected=len(tools),
                tools_total=len(all_tools),
                tool_names=[t['name'] for t in tools][:8],  # Log first 8
                savings_pct=f"{savings_pct:.0f}%"
            )
        else:
            # Simple query: no tools
            tools = []
            log_with_context(
                logger, "info", "Tool selector: NO TOOLS (simple query)",
                query_class=query_class
            )
        
    except Exception as e:
        # Fallback to all tools if selection fails (O5: with caching)
        tools = get_cached_tool_definitions(get_tool_definitions)
        log_with_context(logger, "warning", "Tool selection failed, using all tools",
                        error=str(e))

    # ========== DECISION RULES (Phase 19.6 - Tool Autonomy) ==========
    # Apply database-driven decision rules to modify tool selection
    try:
        from .services.tool_autonomy import get_tool_autonomy_service
        from datetime import datetime

        autonomy_service = get_tool_autonomy_service()
        now = datetime.now(get_timezone("Europe/Zurich"))

        # Build context for rule matching
        rule_context = {
            "query": query,
            "user_id": user_id,
            "source": source,
            "time_of_day": now.strftime("%H:%M"),
            "hour": now.hour,
            "weekday": now.strftime("%A").lower(),
            "query_class": query_class
        }

        # Get applicable rules
        applicable_rules = autonomy_service.get_applicable_rules(rule_context)

        if applicable_rules:
            tool_names_set = {t['name'] for t in tools}

            for rule in applicable_rules:
                action_type = rule["action_type"]
                action_value = rule["action_value"]

                if action_type == "include_tools":
                    # Add tools to selection
                    tools_to_add = action_value if isinstance(action_value, list) else [action_value]
                    for tool_name in tools_to_add:
                        if tool_name not in tool_names_set:
                            matching = [t for t in all_tools if t['name'] == tool_name]
                            if matching:
                                tools.append(matching[0])
                                tool_names_set.add(tool_name)

                elif action_type == "exclude_tools":
                    # Remove tools from selection
                    tools_to_remove = action_value if isinstance(action_value, list) else [action_value]
                    tools = [t for t in tools if t['name'] not in tools_to_remove]
                    tool_names_set = {t['name'] for t in tools}

                elif action_type == "set_priority":
                    # Reorder tools by moving specified ones to front
                    priority_tools = action_value if isinstance(action_value, list) else [action_value]
                    high_priority = [t for t in tools if t['name'] in priority_tools]
                    others = [t for t in tools if t['name'] not in priority_tools]
                    tools = high_priority + others

            log_with_context(
                logger, "info", "Decision rules applied",
                rules_count=len(applicable_rules),
                rule_names=[r["name"] for r in applicable_rules],
                tools_after=len(tools)
            )
    except Exception as e:
        log_with_context(logger, "debug", "Decision rules skipped", error=str(e))

    # Select which contexts to inject based on query
    from . import context_selector
    contexts_to_inject = context_selector.select_contexts_to_inject(
        query=query,
        user_id=user_id,
        role=role,
        include_context=include_context
    )
    
    log_with_context(logger, "debug", "Context injection plan",
                   contexts=list(contexts_to_inject),
                   include_context=include_context)

    # === CONTEXT BUILDING (Phase 1.5 refactored) ===
    # Use ContextBuilder to assemble system prompt with all contexts
    context_builder = ContextBuilder(
        base_prompt=system_prompt,
        query=query,
        user_id=user_id,
        session_id=session_id,
        namespace=namespace,
        role=role,
        contexts_to_inject=contexts_to_inject,
        include_context=include_context
    )

    # Build context and get result
    context_result = context_builder.build()
    system_prompt = context_result.system_prompt

    # === SPECIALIST AGENT DETECTION (Tier 3 #8) ===
    # Detect if a specialist agent should handle this query
    active_specialist = None
    specialist_activation_id = None
    try:
        from .services.specialist_agent_service import get_specialist_agent_service

        specialist_service = get_specialist_agent_service()
        specialist_activation = specialist_service.detect_specialist(
            query=query,
            current_domain=namespace,
            session_context={"role": role}
        )

        if specialist_activation.specialist and specialist_activation.confidence >= 0.5:
            active_specialist = specialist_activation.specialist

            # Record activation
            specialist_activation_id = specialist_service.record_activation(
                specialist=active_specialist,
                session_id=session_id,
                query=query,
                trigger_type=specialist_activation.trigger_type,
                trigger_value=specialist_activation.trigger_value,
                confidence=specialist_activation.confidence
            )

            # Get specialist context
            spec_context = specialist_service.get_specialist_context(
                specialist=active_specialist,
                query=query,
                session_id=session_id
            )

            # Inject specialist persona into system prompt
            specialist_block = f"""

## Specialist Agent: {active_specialist.display_name}
{active_specialist.persona_prompt}

### Specialist Knowledge:
"""
            for k in spec_context.knowledge[:3]:
                specialist_block += f"- {k['topic']}: {k['content']}\n"

            if spec_context.memory:
                specialist_block += "\n### Remembered Context:\n"
                for m in spec_context.memory[:3]:
                    specialist_block += f"- {m['type']}: {m['key']} = {m['value']}\n"

            if spec_context.goals:
                specialist_block += "\n### Active Goals:\n"
                for g in spec_context.goals[:2]:
                    specialist_block += f"- {g['title']} ({g['progress'] or 0}% complete)\n"

            system_prompt = system_prompt + specialist_block

            # Update AgentState with specialist info
            state.specialist = active_specialist.name
            state.specialist_display_name = active_specialist.display_name

            log_with_context(logger, "info", "Specialist activated",
                            specialist=active_specialist.display_name,
                            trigger=specialist_activation.trigger_type,
                            confidence=specialist_activation.confidence)

    except Exception as e:
        log_with_context(logger, "debug", "Specialist detection skipped", error=str(e))

    # === CONTEXT ENGINE (Tier 3 #10) ===
    # Build context profile for mood-aware responses
    context_profile = None
    try:
        from .services.context_engine_service import get_context_engine_service

        context_service = get_context_engine_service()
        context_profile = context_service.build_context_profile(
            user_id=str(user_id) if user_id else None,
            session_id=session_id,
            query=query
        )

        # Inject context-aware prompt adjustments
        if context_profile.prompt_injection:
            context_block = f"""

## Context-Aware Guidance
{context_profile.prompt_injection}
"""
            system_prompt = system_prompt + context_block

        # Store context in state for later use
        state.context_profile = context_profile

        log_with_context(logger, "info", "Context profile built",
                        mood=context_profile.primary_mood.value,
                        energy=context_profile.energy_level,
                        stress=context_profile.stress_level,
                        tone=context_profile.recommended_tone)

    except Exception as e:
        log_with_context(logger, "debug", "Context engine skipped", error=str(e))

    # === CROSS-SESSION CONTINUITY (Tier 3 #11) ===
    # Restore context from previous sessions
    session_context_restored = None
    try:
        from .services.cross_session_service import get_cross_session_service

        cross_session = get_cross_session_service()

        # Start session tracking
        cross_session.start_session(
            session_id=session_id,
            user_id=str(user_id) if user_id else "1"
        )

        # Restore context from previous sessions
        session_context_restored = cross_session.restore_session_context(
            user_id=str(user_id) if user_id else "1",
            session_id=session_id,
            specialist=state.specialist
        )

        # Build and inject session recap
        recap = cross_session.build_session_recap(session_context_restored)
        if recap:
            recap_block = f"""

## Session Continuity
{recap}
"""
            system_prompt = system_prompt + recap_block

        # Log active threads for debugging
        if session_context_restored.active_threads:
            log_with_context(logger, "info", "Session context restored",
                            threads=len(session_context_restored.active_threads),
                            handoffs=len(session_context_restored.pending_handoffs),
                            has_recap=recap is not None)

    except Exception as e:
        log_with_context(logger, "debug", "Cross-session continuity skipped", error=str(e))

    # === RESPONSE STYLES (Phase 19.6 - Tool Autonomy) ===
    # Apply database-driven response styles to customize Jarvis's tone and verbosity
    try:
        from .services.tool_autonomy import get_tool_autonomy_service
        autonomy_service = get_tool_autonomy_service()

        # Get default response style (or user-specific if configured)
        response_style = autonomy_service.get_response_style()

        if response_style and response_style.get("style_prompt"):
            style_block = f"""

## Response Style: {response_style['name']}
{response_style['style_prompt']}
- Ton: {response_style.get('tone', 'friendly')}
- Detailgrad: {response_style.get('verbosity', 'balanced')}
- Emojis: {response_style.get('emoji_level', 'sparse')}
"""
            system_prompt = system_prompt + style_block
            log_with_context(logger, "debug", "Response style applied",
                            style=response_style['name'])
    except Exception as e:
        log_with_context(logger, "debug", "Response style skipped", error=str(e))

    # === PROMPT FRAGMENTS (Phase 19.6 - Tool Autonomy) ===
    # Inject dynamic prompt fragments from database
    try:
        from .services.tool_autonomy import get_tool_autonomy_service
        autonomy_service = get_tool_autonomy_service()

        # Get all enabled fragments, sorted by priority
        fragments = autonomy_service.get_prompt_fragments()

        if fragments:
            fragment_content = []
            for frag in fragments:
                # Check if fragment conditions match current context
                conditions = frag.get("conditions", {})
                if conditions:
                    # Simple condition matching
                    match = True
                    if "role" in conditions and conditions["role"] != role:
                        match = False
                    if "source" in conditions and conditions["source"] != source:
                        match = False
                    if not match:
                        continue

                fragment_content.append(frag["content"])

            if fragment_content:
                fragments_block = "\n\n## Dynamic Context\n" + "\n\n".join(fragment_content)
                system_prompt = system_prompt + fragments_block
                log_with_context(logger, "debug", "Prompt fragments injected",
                                count=len(fragment_content))
    except Exception as e:
        log_with_context(logger, "debug", "Prompt fragments skipped", error=str(e))

    # === TOOL AWARENESS (Anti-Hallucination) ===
    # Add explicit tool list to system prompt so LLM knows exactly what's available
    # This prevents GPT-4o from inventing tool names it thinks might exist
    if tools:
        tool_names = sorted([t['name'] for t in tools])

        # Identify key tool categories
        self_improvement_tools = [t for t in tool_names if t in ['write_dynamic_tool', 'promote_sandbox_tool', 'system_pulse', 'list_available_tools']]
        memory_tools = [t for t in tool_names if 'remember' in t or 'recall' in t or 'knowledge' in t]

        tool_awareness_block = f"""

## Verfuegbare Tools (EXAKT diese - keine anderen!)
Du hast Zugriff auf {len(tool_names)} Tools.

### ANTI-HALLUZINATION WARNUNG:
- Tools wie `create_tool`, `manage_tool_registry`, `tool_performance_monitor` existieren NICHT!
- Wenn du unsicher bist, nutze `list_available_tools` um verfuegbare Tools zu sehen
- Erfinde KEINE Tool-Namen - rufe NUR existierende Tools auf

### Self-Improvement Tools (fuer neue Tools erstellen):
{', '.join(self_improvement_tools) if self_improvement_tools else 'Keine geladen'}
→ Nutze `write_dynamic_tool` um neue Tools zu erstellen!

### Memory Tools:
{', '.join(memory_tools[:5])}

### Alle Tools ({len(tool_names)}):
{', '.join(tool_names[:30])}{'...' if len(tool_names) > 30 else ''}

### Step-Management:
- Bei komplexen Tasks: ERST planen, DANN ausfuehren
- Nicht unnoetig Tools aufrufen die nichts beitragen
- Wenn Step-Limit droht: Task aufteilen und User informieren
"""
        system_prompt = system_prompt + tool_awareness_block
        log_with_context(logger, "debug", "Tool awareness block added",
                        tool_count=len(tool_names),
                        self_improvement_tools=len(self_improvement_tools))

    # === SELF-KNOWLEDGE QUERY ===
    # Query Jarvis's self-knowledge before responding
    # This helps Jarvis know which tools to use for specific queries
    try:
        from .services.self_knowledge import query_before_response
        self_knowledge_context = query_before_response(query)
        if self_knowledge_context:
            system_prompt = system_prompt + f"""

## Relevantes Self-Knowledge
{self_knowledge_context}
"""
            log_with_context(logger, "debug", "Self-knowledge context added",
                            context_length=len(self_knowledge_context))
    except Exception as e:
        # Don't fail if self-knowledge query fails
        log_with_context(logger, "warning", "Self-knowledge query failed",
                        error=str(e))

    # === SKILL CONTEXT (Phase 20 - Workflow Skills) ===
    # Check if a workflow skill matches this query and inject its instructions
    try:
        from .prompt_assembler import get_skill_context_for_query
        skill_context = get_skill_context_for_query(query)
        if skill_context:
            system_prompt = system_prompt + skill_context
            log_with_context(logger, "info", "Skill context injected",
                            query_preview=query[:50])
    except Exception as e:
        # Don't fail if skill lookup fails
        log_with_context(logger, "warning", "Skill context lookup failed",
                        error=str(e))

    # === AUTO-LEARNING HINTS (Phase 19.5) ===
    # Add hints from learned patterns to help tool selection
    try:
        from .services.auto_learner import get_prompt_hints
        learning_hints = get_prompt_hints(query)
        if learning_hints:
            system_prompt = system_prompt + learning_hints
            log_with_context(logger, "debug", "Auto-learning hints added",
                            hints_length=len(learning_hints))
    except Exception as e:
        log_with_context(logger, "debug", "Auto-learning hints failed", error=str(e))

    # === CORRECTION-CHECK (Learning from Corrections) ===
    # Check if there are learned corrections relevant to this query
    try:
        from .services.correction_learner import get_correction_learner
        correction_learner = get_correction_learner()
        relevant_corrections = correction_learner.get_relevant_corrections(
            query=query,
            min_confidence=0.5,
            limit=3
        )
        if relevant_corrections:
            correction_hints = "\n\n## Bekannte Korrekturen (vermeide diese Fehler)\n"
            for corr in relevant_corrections:
                correction_hints += f"- **{corr['error_pattern']}** → Richtig: {corr['correct_response']}\n"
            system_prompt = system_prompt + correction_hints
            log_with_context(logger, "info", "Correction hints injected",
                            count=len(relevant_corrections),
                            patterns=[c['error_pattern'][:30] for c in relevant_corrections])
    except Exception as e:
        log_with_context(logger, "debug", "Correction check failed", error=str(e))

    # === CONTEXT-SENSITIVE TOOL SUGGESTIONS (Phase 21A) ===
    # Recommend tools based on learned context patterns
    try:
        from .services.contextual_tool_router import get_contextual_tool_router
        tool_router = get_contextual_tool_router()
        tool_recommendation = tool_router.route_tool(
            query=query,
            context={
                "session_type": context_result.session_type if hasattr(context_result, 'session_type') else None,
                "recent_tools": context_result.recent_tools if hasattr(context_result, 'recent_tools') else []
            }
        )
        if tool_recommendation.get("success") and tool_recommendation.get("recommended_tool"):
            tool_hint = f"\n\n## Tool-Empfehlung (basierend auf Kontext)\n"
            tool_hint += f"- **Empfohlen:** {tool_recommendation['recommended_tool']}"
            if tool_recommendation.get("confidence"):
                tool_hint += f" (Konfidenz: {tool_recommendation['confidence']:.0%})"
            tool_hint += "\n"
            if tool_recommendation.get("alternatives"):
                tool_hint += f"- Alternativen: {', '.join(tool_recommendation['alternatives'][:2])}\n"
            if tool_recommendation.get("context_match"):
                tool_hint += f"- Grund: {tool_recommendation['context_match']}\n"
            system_prompt = system_prompt + tool_hint
            log_with_context(logger, "info", "Tool recommendation injected",
                           tool=tool_recommendation['recommended_tool'],
                           routing_type=tool_recommendation.get('routing_type'))
    except Exception as e:
        log_with_context(logger, "debug", "Tool routing check failed", error=str(e))

    # Handle role override from context (e.g., auto-coach mode)
    if context_result.role_override:
        role = context_result.role_override

    # Log context build results
    log_with_context(logger, "debug", "Context built",
                   contexts_injected=context_result.contexts_injected,
                   build_time_ms=context_result.build_time_ms,
                   warnings=context_result.warnings if context_result.warnings else None)

    # Add persona style prompt
    from . import persona as persona_module
    context_builder.add_persona_style(persona_id)
    if not persona_id:
        persona_id = persona_module.get_default_persona_id()

    # Build messages
    messages = []

    # Add conversation history (filter out empty messages)
    if conversation_history:
        for msg in conversation_history[-10:]:  # Last 10 messages
            content = msg.get("content", "")
            # Skip messages with empty content (Anthropic API requires non-empty)
            if not content:
                continue
            messages.append({
                "role": msg["role"],
                "content": content
            })

    # Add current query (with optional images for vision)
    if images:
        # Vision mode: content is an array with text and images
        content_parts = [{"type": "text", "text": query}]
        for img in images:
            if img.get("type") == "base64" and img.get("data"):
                content_parts.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": img.get("media_type", "image/jpeg"),
                        "data": img["data"]
                    }
                })
        messages.append({"role": "user", "content": content_parts})
        log_with_context(logger, "info", "Vision mode: images attached", image_count=len(images))
    else:
        messages.append({"role": "user", "content": query})

    # ========== O6: CONTEXT WINDOW OPTIMIZATION ==========
    # Smart truncation for long conversations
    messages, context_stats = optimize_context_window(
        messages=messages,
        system_prompt=system_prompt,
        tool_definitions=tools
    )
    if context_stats.get("truncated"):
        log_with_context(logger, "info", "O6: Context window optimized",
                        original_msgs=context_stats.get("total_messages", 0),
                        kept_msgs=context_stats.get("kept_messages", 0),
                        summarized=context_stats.get("summarized", False),
                        original_tokens=context_stats.get("original_tokens", 0),
                        final_tokens=context_stats.get("final_tokens", 0))

    # ========== O4: STREAMING OPTIMIZATION ==========
    # Buffered streaming for smoother output
    stream_finish_fn = None
    if stream_callback:
        optimized_callback, stream_finish_fn = create_optimized_stream_callback(stream_callback)
        stream_callback = optimized_callback

    # Track tool usage
    all_tool_calls = []
    total_input_tokens = 0
    total_output_tokens = 0

    # Phase 1.5: Create ToolExecutor for tool execution
    # Phase 21A: Added session_id for tool chain tracking
    tool_executor = ToolExecutor(
        user_id=user_id,
        query=query,
        on_loop_alert=_send_tool_loop_alert,
        session_id=session_id
    )

    # Agent loop
    for round_num in range(max_rounds_value):
        # Phase 1.5: Track round in AgentState
        state.round_num = round_num

        # ========== SOFT CHECKPOINTS (Phase 19.5 - Ouroboros Pattern) ==========
        # Inject warnings at 50% and 75% to help LLM plan better
        rounds_remaining = max_rounds_value - round_num
        if round_num > 0 and rounds_remaining <= max_rounds_value * 0.25:
            # 75% used - critical warning
            checkpoint_msg = f"⚠️ WARNUNG: Nur noch {rounds_remaining} Runden übrig! Bitte: (1) Task jetzt abschliessen, (2) Falls nicht möglich: Teilergebnis liefern und Fortsetzung vorschlagen."
            messages.append({"role": "user", "content": f"[SYSTEM CHECKPOINT] {checkpoint_msg}"})
            log_with_context(logger, "warning", "Soft checkpoint: 75% rounds used",
                           round=round_num, remaining=rounds_remaining)
        elif round_num > 0 and rounds_remaining <= max_rounds_value * 0.5:
            # 50% used - advisory
            if round_num == int(max_rounds_value * 0.5):  # Only inject once
                checkpoint_msg = f"📊 INFO: {round_num}/{max_rounds_value} Runden verbraucht. Bei komplexen Tasks: Teilergebnisse sichern und priorisieren."
                messages.append({"role": "user", "content": f"[SYSTEM CHECKPOINT] {checkpoint_msg}"})
                log_with_context(logger, "info", "Soft checkpoint: 50% rounds used",
                               round=round_num, remaining=rounds_remaining)

        if timeout_seconds is not None and (time.time() - start_time) > timeout_seconds:
            timeout_hit = True
            state.timeout_hit = True  # Phase 1.5
            log_with_context(logger, "warning", "Agent timeout hit",
                           timeout_seconds=timeout_seconds, rounds=round_num)
            break
        log_with_context(logger, "debug", f"Agent round {round_num + 1}")

        try:
            if provider_tool_loop_active and provider_tool_loop_router is not None:
                log_with_context(
                    logger,
                    "info",
                    "Provider tool loop round started",
                    tool_loop_phase="llm_call_start",
                    round=round_num + 1,
                    provider=provider_tool_loop_state.provider,
                    model=model,
                    router_model=provider_tool_loop_model_config.model_id if provider_tool_loop_model_config else None,
                    previous_response_id=bool(provider_tool_loop_state.previous_response_id),
                )
                router_response = provider_tool_loop_router.execute_with_fallback(
                    provider_tool_loop_model_config,
                    messages,
                    system_prompt,
                    tools,
                    max_tokens,
                    previous_response_id=provider_tool_loop_state.previous_response_id,
                )
                response = normalize_model_router_response(router_response)
                adapter = get_provider_tool_loop_adapter(response.provider)
                adapter.apply_response_state(response, provider_tool_loop_state)
                log_with_context(
                    logger,
                    "info",
                    "Provider tool loop round completed",
                    tool_loop_phase="llm_call_complete",
                    round=round_num + 1,
                    provider=response.provider,
                    model=response.model,
                    stop_reason=response.stop_reason,
                )
            else:
                response = normalize_anthropic_response(
                    _call_claude(
                        client,
                        model,
                        messages,
                        tools,
                        max_tokens,
                        system_prompt,
                        stream_callback=stream_callback,
                        effort=effort_level,
                    ),
                    model=model,
                )
                provider_tool_loop_state.provider = Provider.ANTHROPIC.value
                provider_tool_loop_state.previous_response_id = None
        except Exception as e:
            log_with_context(logger, "error", "Agent API call failed", error=str(e))
            metrics.inc("agent_errors")
            raise

        state.model = response.model
        total_input_tokens += response.usage.input_tokens
        total_output_tokens += response.usage.output_tokens
        # Phase 1.5: Also track in AgentState
        state.add_tokens(response.usage.input_tokens, response.usage.output_tokens)

        # Check stop reason
        if response.stop_reason == "end_turn":
            # No more tool calls, extract final answer
            final_text = ""
            for block in response.content:
                if block.type == "text":
                    final_text += block.text

            # Phase 1.5: Track answer in AgentState
            state.answer = final_text

            duration_ms = (time.time() - start_time) * 1000
            metrics.timing("agent_latency_ms", duration_ms)
            metrics.inc("agent_tokens_in", total_input_tokens)
            metrics.inc("agent_tokens_out", total_output_tokens)

            # Phase 21: Record cost to database
            if _TRACK_COSTS:
                try:
                    record_api_cost(
                        model=response.model,
                        provider=response.provider,
                        feature="agent",
                        tokens_in=total_input_tokens,
                        tokens_out=total_output_tokens,
                        session_id=session_id,
                        user_id=str(user_id) if user_id else None,
                        namespace=namespace,
                        latency_ms=int(duration_ms),
                        success=True
                    )
                except Exception as cost_err:
                    logger.debug(f"Cost tracking failed: {cost_err}")

            # O4: Finish streaming and log metrics
            if stream_finish_fn:
                stream_stats = stream_finish_fn()
                if stream_stats.get("total_chars", 0) > 0:
                    log_with_context(logger, "debug", "O4: Streaming completed",
                                   chars=stream_stats.get("total_chars", 0),
                                   chunks=stream_stats.get("chunk_count", 0),
                                   chars_per_sec=stream_stats.get("chars_per_second", 0))

            log_with_context(logger, "info", "Agent completed",
                           rounds=round_num + 1,
                           tool_calls=len(all_tool_calls),
                           latency_ms=round(duration_ms, 1))

            # Phase 21A: Finish tool chain tracking
            if len(all_tool_calls) > 0:
                chain_result = tool_executor.finish_chain(success=True)
                if chain_result.get("saved"):
                    log_with_context(logger, "debug", "Tool chain saved",
                                   chain_length=len(chain_result.get("chain", [])))

            # Build response from AgentState (includes facette info)
            response_data = state.to_response_dict()
            response_data["provider"] = response.provider
            response_data["model"] = response.model
            log_with_context(logger, "info", "Response built from state",
                           request_id=state.request_id,
                           has_facette_weights=("facette_weights" in response_data),
                           response_keys=list(response_data.keys()))

            # Add explanation if requested
            if include_explanation:
                explanation = build_explanation(all_tool_calls)
                response_data["explanation"] = explanation
                response_data["explanation_text"] = format_explanation_text(explanation)

            # ============ PHASE 1: PERSIST SESSION MEMORY ============
            # Save session state for consciousness continuity
            _persist_session_memory(
                user_id=str(user_id) if user_id else None,
                session_id=session_id,
                namespace=namespace,
                query=query,
                response_data=response_data,
                messages=messages,
                all_tool_calls=all_tool_calls,
                round_num=round_num,
                start_time=start_time
            )

            # ============ PHASE 1.5: PERSIST SESSION SNAPSHOT ============
            # Save structured snapshot for consciousness continuity (T-013)
            try:
                from .memory import MemoryStore, SessionSnapshot
                from . import config as cfg
                import redis

                redis_client = redis.Redis(host=cfg.REDIS_HOST, port=cfg.REDIS_PORT, db=0)
                memory_store = MemoryStore(redis_client)

                snapshot = SessionSnapshot(
                    user_id=str(user_id) if user_id else "anonymous",
                    session_id=session_id or state.request_id,
                    namespace=namespace,
                    query_count=round_num + 1,
                    detected_mood="neutral",  # TODO: infer from StateInference
                    energy_level=0.5,
                    last_query=query[:500],
                    last_answer_preview=(response_data.get("answer", "")[:200]),
                    last_tools_used=state.tools_used,
                    facette_weights=state.facette_weights or {},
                    dominant_facette=state.dominant_facette or "analytical",
                    avg_latency_ms=state.elapsed_ms,
                    error_count=state.error_count
                )
                memory_store.save_snapshot(snapshot)
                log_with_context(logger, "debug", "Session snapshot saved",
                               session_id=snapshot.session_id, user_id=snapshot.user_id)
            except Exception as e:
                logger.warning(f"Failed to save session snapshot: {e}")

            # Track value created (ClawWork economic accountability) - end_turn path
            try:
                from .services.economic_engine import get_economic_engine, ValueType, CostType
                engine = get_economic_engine()

                # Track value (no tools = simple complexity)
                engine.record_value(
                    value_type=ValueType.TASK_COMPLETION,
                    feature="agent",
                    user_id=str(user_id) if user_id else "system",
                    description=query[:100],
                    complexity="simple" if not all_tool_calls else "medium",
                    confidence=0.8,
                )

                # Track cost from usage
                usage = response_data.get("usage", {})
                in_tokens = usage.get("input_tokens", 0)
                out_tokens = usage.get("output_tokens", 0)
                if in_tokens or out_tokens:
                    cost_usd = (in_tokens * 0.003 + out_tokens * 0.015) / 1000
                    engine.record_cost(
                        cost_type=CostType.LLM_TOKENS,
                        amount_usd=cost_usd,
                        feature="agent",
                        user_id=str(user_id) if user_id else "system",
                        description=f"agent: {in_tokens} in, {out_tokens} out",
                    )
            except Exception as track_err:
                log_with_context(logger, "debug", "Economic tracking failed (end_turn)", error=str(track_err))

            # ============ PHASE 19.5: AUTO-LEARNING ============
            # Extract and store learnings from this session
            try:
                from .services.auto_learner import extract_learning_from_session
                learnings = extract_learning_from_session(
                    query=query,
                    tool_calls=all_tool_calls,
                    final_answer=response_data.get("answer", ""),
                    success=True,  # end_turn means successful completion
                    user_id=str(user_id) if user_id else None,
                    session_id=session_id or (state.request_id if state else None),
                    namespace=namespace,
                    source="agent",
                )
                if learnings.get("tool_usage_logged", 0) > 0:
                    log_with_context(logger, "debug", "Auto-learning completed",
                                   tools_logged=learnings["tool_usage_logged"],
                                   patterns=learnings["patterns_stored"],
                                   facts=learnings["facts_stored"])
            except Exception as learn_err:
                log_with_context(logger, "debug", "Auto-learning failed", error=str(learn_err))

            # ============ CORRECTION AUTO-DETECTION ============
            # Detect if user is correcting a previous response
            try:
                from .services.correction_learner import get_correction_learner
                correction_learner = get_correction_learner()

                # Get last assistant response from conversation history
                last_response = None
                if conversation_history:
                    for msg in reversed(conversation_history):
                        if msg.get("role") == "assistant":
                            last_response = msg.get("content", "")
                            break

                if last_response:
                    # Check if current query is a correction
                    detection = correction_learner.detect_correction(query, last_response)
                    if detection.get("is_correction"):
                        # Process and store the correction
                        result = correction_learner.process_correction(
                            user_message=query,
                            previous_response=last_response,
                            session_id=session_id,
                            user_id=user_id
                        )
                        if result.get("processed"):
                            log_with_context(logger, "info", "Correction detected and stored",
                                           trigger_type=detection.get("trigger_type"),
                                           error_type=result.get("error_type"),
                                           confidence=detection.get("confidence"),
                                           is_new=result.get("storage", {}).get("is_new"))
            except Exception as corr_err:
                log_with_context(logger, "warning", "Correction detection failed", error=str(corr_err))

            # ============ PHASE A1: SELF-REFLECTION (AGI) ============
            # Run reflection loop to evaluate and improve
            try:
                from .services.reflection_service import get_reflection_service
                reflection_service = get_reflection_service()
                reflection_result = reflection_service.run_reflection_loop(
                    query=query,
                    response=response_data.get("answer", ""),
                    tool_calls=all_tool_calls,
                    session_id=state.session_id if state else None,
                    auto_extract=True
                )
                if reflection_result.get("reflection"):
                    log_with_context(logger, "debug", "Self-reflection completed",
                                   quality=reflection_result.get("evaluation", {}).get("quality_score"),
                                   needs_improvement=bool(reflection_result.get("reflection", {}).get("needs_action")))
            except Exception as reflect_err:
                log_with_context(logger, "debug", "Self-reflection failed", error=str(reflect_err))

            # ============ PHASE A2: UNCERTAINTY QUANTIFICATION (AGI) ============
            # Assess confidence in the response
            try:
                from .services.uncertainty_service import get_uncertainty_service
                uncertainty_service = get_uncertainty_service()
                confidence_result = uncertainty_service.assess_confidence(
                    query=query,
                    response=response_data.get("answer", ""),
                    tool_calls=all_tool_calls,
                    session_id=state.session_id if state else None
                )
                if confidence_result.get("success"):
                    response_data["confidence"] = confidence_result.get("overall_confidence")
                    response_data["confidence_category"] = confidence_result.get("confidence_category")
                    if confidence_result.get("should_express_uncertainty"):
                        response_data["uncertainty_disclaimer"] = confidence_result.get("suggested_disclaimer")
                    log_with_context(logger, "debug", "Uncertainty assessment completed",
                                   confidence=confidence_result.get("overall_confidence"),
                                   category=confidence_result.get("confidence_category"))
            except Exception as uncertainty_err:
                log_with_context(logger, "debug", "Uncertainty assessment failed", error=str(uncertainty_err))

            _finalize_reasoning()
            _close_attr_scope()
            return response_data

        elif response.stop_reason == "tool_use":
            # Phase 1.5: Use ToolExecutor for tool execution
            batch_result = tool_executor.process_response(response)

            # Track in legacy all_tool_calls for backward compatibility
            for ex in batch_result.executions:
                all_tool_calls.append({
                    "tool": ex.tool_name,
                    "input": ex.input,
                    "result_summary": ex.result_summary,
                    "result": ex.result
                })
                # Also track in AgentState
                state.add_tool_call(ex.tool_name, ex.input, ex.result, ex.result_summary)

            adapter = get_provider_tool_loop_adapter(response.provider)
            messages = adapter.append_followup_messages(
                messages,
                batch_result.assistant_content,
                batch_result.tool_results,
            )
            log_with_context(
                logger,
                "info",
                "Provider tool loop follow-up prepared",
                tool_loop_phase="followup_messages",
                round=round_num + 1,
                provider=response.provider,
                assistant_blocks=len(batch_result.assistant_content),
                tool_results=len(batch_result.tool_results),
            )

        else:
            # Unexpected stop reason
            log_with_context(logger, "warning", f"Unexpected stop reason: {response.stop_reason}")
            break

    # O4: Finish streaming on early exit
    if stream_finish_fn:
        try:
            stream_finish_fn()
        except Exception:
            pass

    # If we hit timeout, return what we have
    duration_ms = (time.time() - start_time) * 1000
    if timeout_hit:
        metrics.inc("agent_timeout")
        # Phase 21A: Finish chain with failure
        tool_executor.finish_chain(success=False)
        response_data = {
            "answer": "I apologize, but I wasn't able to complete the task within the allowed time. Please try rephrasing your question.",
            "tool_calls": all_tool_calls,
            "rounds": round_num,
            "model": state.model,
            "provider": provider_tool_loop_state.provider,
            "role": role,
            "persona_id": persona_id,
            "usage": {
                "input_tokens": total_input_tokens,
                "output_tokens": total_output_tokens
            },
            "timeout_hit": True,
            "timeout_seconds": timeout_seconds
        }

        if include_explanation:
            explanation = build_explanation(all_tool_calls)
            response_data["explanation"] = explanation
            response_data["explanation_text"] = format_explanation_text(explanation)

        if user_id and session_id:
            try:
                from .cross_session_learner import cross_session_learner
                answer_text = response_data.get("answer", "")
                decision_text = answer_text[:100] if answer_text else query[:100]
                confidence = 0.4
                cross_session_learner.log_decision(
                    user_id=user_id,
                    session_id=session_id,
                    decision_text=decision_text,
                    context=f"timeout after {timeout_seconds}s",
                    decision_category="timeout",
                    confidence=confidence
                )
            except Exception as e:
                logger.debug(f"Decision logging failed (non-critical): {e}")

        _finalize_reasoning()
        _close_attr_scope()
        return response_data

    # If we hit max rounds, return what we have
    log_with_context(logger, "warning", "Agent hit max rounds", rounds=max_rounds_value)
    metrics.inc("agent_max_rounds")

    # Build summary of tool results collected so far
    summary_parts = []
    if all_tool_calls:
        summary_parts.append(f"I gathered information using {len(all_tool_calls)} tool calls but couldn't complete the full analysis within the step limit.")
        
        # Categorize tools used
        tools_used = {}
        for tc in all_tool_calls:
            tool_name = tc.get("tool", "unknown")
            tools_used[tool_name] = tools_used.get(tool_name, 0) + 1
        
        summary_parts.append("\n\n**Tools used:**")
        for tool, count in tools_used.items():
            summary_parts.append(f"- {tool} ({count}x)")
        
        # Extract key findings from tool results - smarter formatting
        key_findings = []
        for tc in all_tool_calls[:5]:  # Show first 5 results
            result = tc.get("result", "")
            result_summary = tc.get("result_summary", "")
            tool_name = tc.get("tool", "")

            # Check for summary field in result (e.g., get_learnings)
            if isinstance(result, dict):
                if "summary" in result:
                    key_findings.append(f"- {result['summary'][:500]}")
                    continue
                elif "answer" in result:
                    key_findings.append(f"- {result['answer'][:300]}")
                    continue
                elif "count" in result and "learnings" in result:
                    # get_learnings result - format nicely
                    learnings = result.get("learnings", [])
                    facts = [l.get("fact", "") for l in learnings[:5] if l.get("fact")]
                    if facts:
                        key_findings.append(f"- **Learnings ({result['count']}):** " + "; ".join(facts[:3]))
                    continue

            if result_summary and len(result_summary) > 10:
                key_findings.append(f"- {result_summary[:200]}")
            elif result and len(str(result)) > 20:
                # Truncate result if too long - but avoid raw JSON
                result_str = str(result)
                if not result_str.startswith("{") and not result_str.startswith("["):
                    key_findings.append(f"- {result_str[:200]}...")

        if key_findings:
            summary_parts.append("\n\n**Key findings:**")
            summary_parts.extend(key_findings)

        # Better guidance based on what was attempted
        summary_parts.append("\n\n---")
        summary_parts.append("**💡 Wie weiter?**")
        if any("write_dynamic_tool" in tc.get("tool", "") for tc in all_tool_calls):
            summary_parts.append("- Tool-Erstellung: Bitte EIN Tool pro Anfrage erstellen, nicht mehrere gleichzeitig")
            summary_parts.append("- Syntax: Verwende `code` Parameter mit vollständigem Python-Code")
        else:
            summary_parts.append("- Komplexe Aufgabe in Teilschritte aufteilen")
            summary_parts.append("- Spezifischere Frage stellen")
            summary_parts.append("- Teilergebnis akzeptieren und mit Folgefrage fortsetzen")
    else:
        summary_parts.append("Die Aufgabe konnte nicht abgeschlossen werden.")
        summary_parts.append("\n**💡 Vorschläge:**")
        summary_parts.append("- Frage spezifischer formulieren")
        summary_parts.append("- In kleinere Teilaufgaben aufteilen")
        summary_parts.append("- Mit 'was hast du bisher?' Zwischenergebnisse abfragen")
    
    answer_text = "\n".join(summary_parts)

    response_data = {
        "answer": answer_text,
        "tool_calls": all_tool_calls,
        "rounds": max_rounds_value,
        "model": state.model,
        "provider": provider_tool_loop_state.provider,
        "role": role,
        "persona_id": persona_id,
        "usage": {
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens
        },
        "max_rounds_hit": True
    }

    # ============ PHASE 19.5: AUTO-LEARNING (even on max_rounds) ============
    # Extract learnings even when we hit limits - partial success is still valuable
    try:
        from .services.auto_learner import extract_learning_from_session
        learnings = extract_learning_from_session(
            query=query,
            tool_calls=all_tool_calls,
            final_answer=answer_text,
            success=False,  # Mark as partial completion
            user_id=str(user_id) if user_id else None,
            session_id=state.session_id if state else None,
            namespace=namespace,
            source="agent",
        )
        if learnings.get("tool_usage_logged", 0) > 0:
            log_with_context(logger, "debug", "Auto-learning (max_rounds)",
                           tools_logged=learnings["tool_usage_logged"],
                           patterns=learnings["patterns_stored"])
    except Exception as learning_err:
        log_with_context(logger, "debug", "Auto-learning skipped (max_rounds)",
                        error=str(learning_err))

    # ============ PHASE A1: SELF-REFLECTION (max_rounds) ============
    # Reflect on why we hit limits - important learning opportunity
    try:
        from .services.reflection_service import get_reflection_service
        reflection_service = get_reflection_service()
        reflection_result = reflection_service.run_reflection_loop(
            query=query,
            response=answer_text,
            tool_calls=all_tool_calls,
            session_id=state.session_id if state else None,
            context={"max_rounds_hit": True}
        )
        if reflection_result.get("success"):
            log_with_context(logger, "debug", "Self-reflection (max_rounds)",
                           quality=reflection_result.get("evaluation", {}).get("quality_score"))
    except Exception as reflect_err:
        log_with_context(logger, "debug", "Self-reflection skipped (max_rounds)",
                        error=str(reflect_err))

    # ============ PHASE A2: UNCERTAINTY QUANTIFICATION (max_rounds) ============
    try:
        from .services.uncertainty_service import get_uncertainty_service
        uncertainty_service = get_uncertainty_service()
        confidence_result = uncertainty_service.assess_confidence(
            query=query,
            response=answer_text,
            tool_calls=all_tool_calls,
            session_id=state.session_id if state else None,
            context={"max_rounds_hit": True}
        )
        if confidence_result.get("success"):
            response_data["confidence"] = confidence_result.get("overall_confidence")
            response_data["confidence_category"] = confidence_result.get("confidence_category")
            log_with_context(logger, "debug", "Uncertainty assessment (max_rounds)",
                           confidence=confidence_result.get("overall_confidence"))
    except Exception as uncertainty_err:
        log_with_context(logger, "debug", "Uncertainty assessment skipped (max_rounds)",
                        error=str(uncertainty_err))

    # Add explanation if requested
    if include_explanation:
        explanation = build_explanation(all_tool_calls)
        response_data["explanation"] = explanation
        response_data["explanation_text"] = format_explanation_text(explanation)

    # ============ Cross-Session Learning Integration ============
    # Log decisions for later learning if user_id and session_id provided
    if user_id and session_id:
        try:
            from .cross_session_learner import cross_session_learner
            
            # Log the main decision (the answer itself)
            answer_text = response_data.get("answer", "")
            decision_text = answer_text[:100] if answer_text else query[:100]
            confidence = 0.4  # Lower confidence for max-rounds scenarios
            
            # Boost confidence if we had sources
            if include_explanation:
                explanation = build_explanation(all_tool_calls)
                if explanation.get("confidence") == "HIGH":
                    confidence = 0.9
                elif explanation.get("confidence") == "MEDIUM":
                    confidence = 0.7
                else:
                    confidence = 0.4
            
            decision_id = cross_session_learner.log_decision(
                user_id=user_id,
                session_id=session_id,
                decision_text=decision_text,
                context=query[:200],
                decision_category=role,  # Use role as category
                confidence=confidence
            )
            response_data["decision_id"] = decision_id
            
            # Detect recurring topics
            recurring = cross_session_learner.detect_recurring_topic(
                user_id=user_id,
                topic=query[:30],
                session_id=session_id,
                context=query
            )
            if recurring:
                response_data["lesson_detected"] = recurring
                log_with_context(logger, "info", "Recurring topic lesson detected",
                               topic=recurring.get("topic"))
            
        except Exception as e:
            log_with_context(logger, "warning", "Failed to log decision for cross-session learning",
                           error=str(e))

    # ========== PHASE A: POST-RESPONSE HOOKS (Tool Activation Strategy) ==========
    # Auto-call assess_my_confidence after generating response
    if _AGENT_HOOKS_ENABLED:
        try:
            hooks = get_agent_hooks(user_id=user_id, session_id=session_id)
            answer_text = response_data.get("answer", "")
            hook_result = hooks.post_response(
                query=query,
                response=answer_text,
                tool_calls=all_tool_calls
            )
            if hook_result.success and not hook_result.skipped:
                confidence = hook_result.data.get("confidence", 0.0)
                response_data["auto_confidence"] = confidence
                if confidence < 0.5:
                    log_with_context(logger, "info", "Low confidence response detected",
                                   confidence=confidence,
                                   signals=hook_result.data.get("uncertainty_signals", []))
        except Exception as e:
            log_with_context(logger, "debug", "Post-response hook failed (non-critical)", error=str(e))

    # Track value created (ClawWork economic accountability)
    log_with_context(logger, "debug", "Starting economic value tracking")
    try:
        from .services.economic_engine import get_economic_engine, ValueType
        engine = get_economic_engine()

        # Estimate complexity based on response and tools used
        answer = response_data.get("answer", "")
        tools_used = response_data.get("tool_calls", [])

        if len(tools_used) > 2:
            complexity = "complex"
        elif len(tools_used) > 0 or len(answer) > 500:
            complexity = "medium"
        else:
            complexity = "simple"

        engine.record_value(
            value_type=ValueType.TASK_COMPLETION,
            feature="agent",
            user_id=user_id,
            description=query[:100],
            complexity=complexity,
            confidence=0.8,
        )
        log_with_context(logger, "info", "Economic value tracked",
                        complexity=complexity, user_id=user_id)
    except Exception as e:
        log_with_context(logger, "warning", "Economic tracking failed", error=str(e))

    _finalize_reasoning()
    _close_attr_scope()
    return response_data


def get_daily_briefing(
    namespace: str = "work_projektil",
    days: int = 1
) -> Dict[str, Any]:
    """
    Generate a daily briefing using the agent.
    This is a convenience function that runs a specific query.
    """
    query = f"""Give me a briefing on the last {days} day(s):
1. What important emails did I receive?
2. Any notable chat conversations?
3. What should I be aware of today?

Be concise and focus on the most important items."""

    return run_agent(
        query=query,
        namespace=namespace,
        model="claude-sonnet-4-20250514"
    )


# =============================================================================
# FAST-PATH: _run_simple_query (T-020 - Simple Query Fast-Path)
# Feb 3, 2026 - High-impact optimization for simple queries
# =============================================================================

def _run_simple_query(
    query: str,
    user_id: Optional[int] = None,
    session_id: Optional[str] = None,
    namespace: str = "work_projektil",
) -> Dict[str, Any]:
    """
    Fast-path execution for simple queries.
    
    Features:
    - No tools (avoid 2800 token tool definitions)
    - Minimal system prompt (~200 tokens vs 1500)
    - Haiku model (faster + cheaper)
    - Target: <500ms latency, 94% token reduction
    
    Args:
        query: User's question (already classified as "simple")
        user_id: Telegram user ID (optional)
        session_id: Session ID (optional)
        namespace: Default namespace (unused for simple queries)
    
    Returns:
        Dict with answer, usage, fast_path=True, elapsed_ms
    """
    start_time = time.time()
    
    try:
        from .query_classifier import (
            get_fast_path_model,
            get_minimal_system_prompt
        )
        from . import metrics as metrics_module
        
        # Initialize Anthropic client
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            log_with_context(logger, "error", "ANTHROPIC_API_KEY not set, falling back to normal flow")
            raise ValueError("Missing API key")
        
        client = anthropic.Anthropic(api_key=api_key)
        
        # Get minimal system prompt and model
        system_prompt = get_minimal_system_prompt()
        model = get_fast_path_model()
        
        # Call Claude with minimal context
        response = client.messages.create(
            model=model,
            max_tokens=256,  # Simple queries get short responses
            system=system_prompt,
            messages=[{"role": "user", "content": query}]
        )
        
        # Extract answer
        answer = response.content[0].text if response.content else ""
        elapsed_ms = (time.time() - start_time) * 1000
        
        # Record metrics
        total_tokens = response.usage.input_tokens + response.usage.output_tokens
        metrics_module.record_tokens_per_query("simple", total_tokens)
        metrics_module.record_response_latency("fast", elapsed_ms / 1000.0)
        
        log_with_context(
            logger, "info", "Fast-path complete",
            elapsed_ms=elapsed_ms,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            total_tokens=total_tokens,
            model=model
        )
        
        # Track value and cost (ClawWork economic accountability)
        try:
            from .services.economic_engine import get_economic_engine, ValueType, CostType
            engine = get_economic_engine()

            # Track value created (simple query = simple complexity)
            engine.record_value(
                value_type=ValueType.TASK_COMPLETION,
                feature="fast_path",
                user_id=str(user_id) if user_id else "system",
                description=query[:100],
                complexity="simple",
                confidence=0.8,
            )

            # Track cost
            cost_usd = (response.usage.input_tokens * 0.00025 + response.usage.output_tokens * 0.00125) / 1000
            engine.record_cost(
                cost_type=CostType.LLM_TOKENS,
                amount_usd=cost_usd,
                feature="fast_path",
                user_id=str(user_id) if user_id else "system",
                description=f"{model}: {response.usage.input_tokens} in, {response.usage.output_tokens} out",
            )
            log_with_context(logger, "debug", "Fast-path economic tracking done",
                           value_usd=0.4, cost_usd=cost_usd)
        except Exception as track_err:
            log_with_context(logger, "debug", "Fast-path economic tracking failed", error=str(track_err))

        # Return response in standard format
        return {
            "query": query,
            "answer": answer,
            "tool_calls": [],
            "rounds": 1,
            "model": model,
            "role": "assistant",
            "persona_id": None,
            "usage": {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
                "total_tokens": total_tokens,
            },
            "session_id": session_id,
            "user_id": user_id,
            "namespace": namespace,
            "fast_path": True,
            "elapsed_ms": elapsed_ms,
        }

    except Exception as e:
        log_with_context(
            logger, "error", "Fast-path failed, falling back to normal flow",
            error=str(e),
            exc_info=True
        )
        raise
