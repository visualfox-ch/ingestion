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
from .observability import get_logger, log_with_context, metrics, retry_with_backoff, tool_loop_detector
from .langfuse_integration import observe, langfuse_context, langfuse_attribute_scope
from .roles import get_role, build_system_prompt, detect_role, ROLES
from .tracing import get_trace_context
from .memory import MemoryStore, StateInference
from .agent_state import AgentState
from .context_builder import ContextBuilder
from .tool_executor import ToolExecutor
from .response_builder import ResponseBuilder, build_explanation, format_explanation_text
from .diff_gate import DiffGateValidator, CodeChange, RiskClass
from .confidence_scorer import JarvisConfidenceScorer, ConfidenceScore
from .execution_orchestrator import JarvisExecutionOrchestrator
from .metrics_bridge import JarvisMetricsBridge
from .learning_manager import JarvisLearningManager

logger = get_logger("jarvis.agent")


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
MAX_TOOL_ROUNDS = CONFIG_MAX_ROUNDS or 6  # Prevent infinite loops - read from config (default 6)


@retry_with_backoff(max_retries=2, base_delay=1.0, exceptions=(anthropic.APIConnectionError, anthropic.RateLimitError))
def _call_claude(
    client: anthropic.Anthropic,
    model: str,
    messages: List[Dict],
    tools: List[Dict],
    max_tokens: int,
    system_prompt: str = None,
    stream_callback: Any = None,
) -> anthropic.types.Message:
    """Call Claude with retry logic and minimal Langfuse tracing"""
    # Note: Langfuse v3.x decorator context isolation means nested @observe decorators
    # don't automatically create child observations. Full nested LLM call tracing would
    # require either SDK improvements or parent trace ID propagation (not currently available).
    # For now, we focus on tracking via token counts in usage response.
    
    if not stream_callback:
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt or AGENT_SYSTEM_PROMPT,
            tools=tools,
            messages=messages
        )
    else:
        # Stream text deltas for perceived latency while still returning the final Message
        with client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt or AGENT_SYSTEM_PROMPT,
            tools=tools,
            messages=messages,
        ) as stream:
            for chunk in stream.text_stream:
                try:
                    stream_callback(chunk)
                except Exception:
                    pass
            response = stream.get_final_message()
    
    return response


@observe(name="run_agent")
def run_agent(
    query: str,
    conversation_history: List[Dict[str, str]] = None,
    namespace: str = "work_projektil",
    model: str = "claude-sonnet-4-20250514",
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

    Returns:
        Dict with 'answer', 'tool_calls', 'usage', 'role', 'persona_id', 'explanation' (if requested), etc.
    """
    start_time = time.time()
    timeout_hit = False
    # Read max_rounds from config dynamically (not cached from import)
    import os as os_module
    max_rounds_env = int(os_module.getenv("JARVIS_AGENT_MAX_ROUNDS", "5"))
    log_with_context(logger, "info", "DEBUG: max_rounds config", env_value=max_rounds_env, param_value=max_rounds)
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
                "model": model,
                "role": role,
                "include_context": include_context,
                "include_explanation": include_explanation,
                "query_length": len(query) if query else 0,
            },
            tags=["tool", "run_agent", role],
            version=getattr(cfg, "VERSION", None),
            trace_name="run_agent",
            as_baggage=False,
        )
        attr_scope.__enter__()
    except Exception:
        attr_scope = None

    def _close_attr_scope():
        if attr_scope:
            try:
                attr_scope.__exit__(None, None, None)
            except Exception:
                pass

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
        except Exception:
            pass
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
        except Exception:
            pass

    # Auto-detect role if enabled
    if auto_detect_role:
        role = detect_role(query, role)

    # Get role config
    role_config = get_role(role) or ROLES["assistant"]

    # Override namespace if role has a default
    if role_config.default_namespace and namespace == "work_projektil":
        namespace = role_config.default_namespace

    # Build system prompt from role
    system_prompt = build_system_prompt(None, role_config)  # Will use role's prompt

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

    client = get_client()
    
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
        
        # Load full tool definitions
        all_tools = get_tool_definitions()
        
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
        # Fallback to all tools if selection fails
        tools = get_tool_definitions()
        log_with_context(logger, "warning", "Tool selection failed, using all tools",
                        error=str(e))

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

    # Add current query
    messages.append({"role": "user", "content": query})

    # Track tool usage
    all_tool_calls = []
    total_input_tokens = 0
    total_output_tokens = 0

    # Phase 1.5: Create ToolExecutor for tool execution
    tool_executor = ToolExecutor(
        user_id=user_id,
        query=query,
        on_loop_alert=_send_tool_loop_alert
    )

    # Agent loop
    for round_num in range(max_rounds_value):
        # Phase 1.5: Track round in AgentState
        state.round_num = round_num

        if timeout_seconds is not None and (time.time() - start_time) > timeout_seconds:
            timeout_hit = True
            state.timeout_hit = True  # Phase 1.5
            log_with_context(logger, "warning", "Agent timeout hit",
                           timeout_seconds=timeout_seconds, rounds=round_num)
            break
        log_with_context(logger, "debug", f"Agent round {round_num + 1}")

        try:
            response = _call_claude(client, model, messages, tools, max_tokens, system_prompt, stream_callback=stream_callback)
        except Exception as e:
            log_with_context(logger, "error", "Agent API call failed", error=str(e))
            metrics.inc("agent_errors")
            raise

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

            log_with_context(logger, "info", "Agent completed",
                           rounds=round_num + 1,
                           tool_calls=len(all_tool_calls),
                           latency_ms=round(duration_ms, 1))

            # Build response from AgentState (includes facette info)
            response_data = state.to_response_dict()
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

            # Add messages for next Claude call
            messages.append({"role": "assistant", "content": batch_result.assistant_content})
            messages.append({"role": "user", "content": batch_result.tool_results})

        else:
            # Unexpected stop reason
            log_with_context(logger, "warning", f"Unexpected stop reason: {response.stop_reason}")
            break

    # If we hit timeout, return what we have
    duration_ms = (time.time() - start_time) * 1000
    if timeout_hit:
        metrics.inc("agent_timeout")
        response_data = {
            "answer": "I apologize, but I wasn't able to complete the task within the allowed time. Please try rephrasing your question.",
            "tool_calls": all_tool_calls,
            "rounds": round_num,
            "model": model,
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
            except Exception:
                pass

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
        
        # Extract key findings from tool results
        key_findings = []
        for tc in all_tool_calls[:5]:  # Show first 5 results
            result = tc.get("result", "")
            result_summary = tc.get("result_summary", "")
            
            if result_summary and len(result_summary) > 10:
                key_findings.append(f"- {result_summary[:200]}")
            elif result and len(str(result)) > 20:
                # Truncate result if too long
                result_str = str(result)[:200]
                key_findings.append(f"- {result_str}...")
        
        if key_findings:
            summary_parts.append("\n\n**Key findings:**")
            summary_parts.extend(key_findings)
        
        summary_parts.append("\n\nPlease try asking a more specific question or breaking this into smaller requests.")
    else:
        summary_parts.append("I wasn't able to complete the task within the allowed steps. Please try rephrasing your question or breaking it into smaller parts.")
    
    answer_text = "\n".join(summary_parts)

    response_data = {
        "answer": answer_text,
        "tool_calls": all_tool_calls,
        "rounds": max_rounds_value,
        "model": model,
        "role": role,
        "persona_id": persona_id,
        "usage": {
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens
        },
        "max_rounds_hit": True
    }

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
