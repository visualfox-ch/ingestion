"""
ContextBuilder: Extracted context injection for the Jarvis agent loop.

Phase 1.5 Refactoring - Step 2: Extract system prompt assembly from run_agent().
This class encapsulates all context injection logic.

Goals:
- Reduce run_agent complexity by isolating context building
- Make context injection testable and configurable
- Prepare for dynamic context selection based on query type
- Token budget enforcement (Feb 4, 2026)
"""
import json
import time
from dataclasses import dataclass, field
from typing import Dict, List, Set, Optional, Any
from datetime import datetime

from .observability import get_logger, log_with_context
from .token_budget import TokenBudgetManager, ComponentType, BudgetReport

logger = get_logger("jarvis.context_builder")


@dataclass
class ContextBuildResult:
    """Result of context building."""
    system_prompt: str
    contexts_injected: List[str] = field(default_factory=list)
    role_override: Optional[str] = None  # If context forces role change
    warnings: List[str] = field(default_factory=list)
    build_time_ms: float = 0.0
    budget_report: Optional[BudgetReport] = None  # Token budget enforcement report


class ContextBuilder:
    """
    Builds the system prompt with selective context injection.

    Usage:
        builder = ContextBuilder(
            base_prompt=AGENT_SYSTEM_PROMPT,
            query=query,
            user_id=user_id,
            session_id=session_id,
            role=role,
            contexts_to_inject={"self_awareness", "entity", "session"}
        )
        result = builder.build()
        system_prompt = result.system_prompt
    """

    def __init__(
        self,
        base_prompt: str,
        query: str,
        user_id: Optional[int] = None,
        session_id: Optional[str] = None,
        namespace: str = "work_projektil",
        role: str = "assistant",
        contexts_to_inject: Optional[Set[str]] = None,
        include_context: bool = True,
        query_class: str = "standard",  # Query complexity tier (simple/standard/complex)
        enable_budget: bool = True,  # Enable token budgeting
        total_budget: int = 100000  # Max tokens for entire prompt
    ):
        self.base_prompt = base_prompt or ""
        self.query = query
        self.user_id = user_id
        self.session_id = session_id
        self.namespace = namespace
        self.role = role
        self.contexts_to_inject = contexts_to_inject or set()
        self.include_context = include_context
        self.query_class = query_class
        self.enable_budget = enable_budget

        # Build state
        self._prompt_parts: List[str] = []  # Will be managed by budget manager
        self._injected: List[str] = []
        self._warnings: List[str] = []
        self._role_override: Optional[str] = None

        # Token budget manager (Feb 4, 2026)
        self._budget = TokenBudgetManager(total_budget=total_budget) if enable_budget else None
        
        # Add base prompt to budget with highest priority
        if self.base_prompt and self._budget:
            self._budget.allocate(ComponentType.SYSTEM, self.base_prompt, priority=1)

    def build(self) -> ContextBuildResult:
        """Build the complete system prompt with all requested contexts."""
        start_time = time.time()

        # T-021: Apply query-class filtering before context injection (Feb 3, 2026)
        self._apply_query_class_filtering()

        # Always inject date/time (lightweight)
        self._inject_datetime()

        # Session memory from Redis
        if self.session_id and self.user_id:
            self._inject_session_memory()

        # Selective context injection based on contexts_to_inject
        if "self_awareness" in self.contexts_to_inject:
            self._inject_self_awareness()

        if "coaching" in self.contexts_to_inject and self.user_id:
            self._inject_coaching()

        if "entity" in self.contexts_to_inject:
            self._inject_entity()

        if "sentiment" in self.contexts_to_inject:
            self._inject_sentiment()

        if "overwhelm" in self.contexts_to_inject and self.user_id:
            self._inject_overwhelm()

        if "patterns" in self.contexts_to_inject and self.user_id:
            self._inject_patterns()

        if "coach_os" in self.contexts_to_inject and self.user_id:
            self._inject_coach_os()

        if "session" in self.contexts_to_inject and self.user_id:
            self._inject_session_context()

        # Thread limit check (part of overwhelm handling)
        if "overwhelm" in self.contexts_to_inject and self.user_id:
            self._inject_thread_limit()

        # Enforce token budget if enabled
        budget_report = None
        if self._budget:
            self._budget.enforce()
            budget_report = self._budget.get_report()
            
            # Log budget metrics
            log_with_context(
                logger, "info" if budget_report.over_budget else "debug",
                "Token budget report",
                total_used=budget_report.total_used,
                total_budget=budget_report.total_budget,
                over_budget=budget_report.over_budget,
                trimmed_count=len(budget_report.trimmed)
            )
            
            # Add budget warnings to context warnings
            self._warnings.extend(budget_report.warnings)
            
            # Assemble final prompt from budget-managed components
            final_content = self._budget.get_final_content()
            self._prompt_parts = []
            for comp_type in [ComponentType.SYSTEM, ComponentType.MEMORY, ComponentType.RETRIEVAL]:
                if comp_type in final_content:
                    self._prompt_parts.extend(final_content[comp_type])
        
        build_time_ms = (time.time() - start_time) * 1000

        return ContextBuildResult(
            system_prompt="\n\n".join(self._prompt_parts) if self._prompt_parts else self.base_prompt,
            contexts_injected=self._injected,
            role_override=self._role_override,
            warnings=self._warnings,
            build_time_ms=build_time_ms,
            budget_report=budget_report
        )

    def _inject_datetime(self) -> None:
        """Inject current date/time context (always, lightweight)."""
        now = datetime.now()
        date_context = f"""=== CURRENT TIME CONTEXT ===
Today: {now.strftime('%A, %d. %B %Y')} (Week {now.isocalendar()[1]})
Time: {now.strftime('%H:%M')} Uhr"""
        
        if self._budget:
            self._budget.allocate(ComponentType.SYSTEM, date_context, priority=2)
        else:
            self._prompt_parts.append(date_context)
        
        self._injected.append("datetime")

    def _inject_session_memory(self) -> None:
        """Inject session memory from Redis for continuity."""
        try:
            import redis as redis_module
            from . import config as cfg
            from .memory import MemoryStore

            redis_client = redis_module.Redis(
                host=cfg.REDIS_HOST,
                port=cfg.REDIS_PORT,
                db=cfg.REDIS_DB,
                decode_responses=False,
                socket_timeout=0.5,
                socket_connect_timeout=0.5,
                retry_on_timeout=False,
                health_check_interval=30
            )
            memory = MemoryStore(redis_client)
            prev_session = memory.get_session_state(self.session_id)

            if prev_session:
                state = prev_session.get("state", {})
                priming = prev_session.get("priming", {})

                memory_context = f"""=== SESSION CONTINUITY ===
Last session: {prev_session.get('created_at', 'unknown')}
Energy: {state.get('energy_level', '?')}/10 | Focus: {state.get('focus_score', '?')}/10 | Stress: {state.get('stress_indicators', '?')}/10
Emotional regulation: {state.get('emotional_regulation', '?')}/10
Conversation tone: {state.get('conversation_tone', 'neutral')}

{priming.get('important_context', '')}

Previous: {priming.get('summary', '')[:200]}"""

                if self._budget:
                    self._budget.allocate(ComponentType.MEMORY, memory_context, priority=3)
                else:
                    self._prompt_parts.append(memory_context)
                
                self._injected.append("session_memory")
                log_with_context(logger, "debug", "Session memory injected",
                               session_id=self.session_id,
                               energy=state.get('energy_level'))

        except Exception as e:
            self._warnings.append(f"session_memory: {str(e)}")
            log_with_context(logger, "debug", "Session memory skipped", error=str(e))

    def _inject_self_awareness(self) -> None:
        """Inject self-awareness context about capabilities."""
        try:
            from . import prompt_assembler
            self_awareness = prompt_assembler.load_self_awareness_context(condensed=True)
            if self_awareness:
                context = f"=== SELF-AWARENESS ===\n{self_awareness}"
                if self._budget:
                    self._budget.allocate(ComponentType.SYSTEM, context, priority=4)
                else:
                    self._prompt_parts.append(context)
                self._injected.append("self_awareness")
                log_with_context(logger, "debug", "Self-awareness injected")
        except Exception as e:
            self._warnings.append(f"self_awareness: {str(e)}")

    def _inject_coaching(self) -> None:
        """Inject coaching domain context."""
        try:
            from . import coaching_domains
            from .domains import get_domain_impl, DomainContext

            active_domain = coaching_domains.get_user_domain(self.user_id)
            if active_domain and active_domain != "general":
                domain_impl = get_domain_impl(active_domain)
                if domain_impl:
                    user_profile = self._get_user_profile()
                    ctx = DomainContext(
                        user_id=self.user_id,
                        domain_id=active_domain,
                        user_profile=user_profile or {}
                    )
                    domain_context = domain_impl.build_context(ctx)
                else:
                    domain_context = coaching_domains.build_domain_context(active_domain)

                if domain_context:
                    if self._budget:
                        self._budget.allocate(ComponentType.RETRIEVAL, domain_context, priority=5)
                    else:
                        self._prompt_parts.append(domain_context)
                    self._injected.append("coaching")
                    log_with_context(logger, "debug", "Coaching context injected",
                                   domain=active_domain)
        except Exception as e:
            self._warnings.append(f"coaching: {str(e)}")

    def _inject_entity(self) -> None:
        """Inject entity context for people/projects mentioned."""
        try:
            from . import entity_extractor
            entities = entity_extractor.extract_entities(
                text=self.query,
                user_id=self.user_id,
                known_only=False
            )
            if entities.entities:
                entity_prompt = entity_extractor.build_entity_context(entities)
                if entity_prompt:
                    if self._budget:
                        self._budget.allocate(ComponentType.RETRIEVAL, entity_prompt, priority=6)
                    else:
                        self._prompt_parts.append(entity_prompt)
                    self._injected.append("entity")
                    log_with_context(logger, "debug", "Entity context injected",
                                   people=entities.person_count,
                                   projects=entities.project_count)
        except Exception as e:
            self._warnings.append(f"entity: {str(e)}")

    def _inject_sentiment(self) -> None:
        """Inject sentiment analysis context."""
        try:
            from . import sentiment_analyzer
            sentiment = sentiment_analyzer.analyze_sentiment(self.query)
            if sentiment.alert_level != "none":
                sentiment_prompt = sentiment_analyzer.get_sentiment_context(sentiment)
                if self._budget:
                    self._budget.allocate(ComponentType.RETRIEVAL, sentiment_prompt, priority=7)
                else:
                    self._prompt_parts.append(sentiment_prompt)
                self._injected.append("sentiment")
                log_with_context(logger, "debug", "Sentiment context injected",
                               dominant=sentiment.dominant, alert_level=sentiment.alert_level)
        except Exception as e:
            self._warnings.append(f"sentiment: {str(e)}")

    def _inject_overwhelm(self) -> None:
        """Inject overwhelm detection and auto-coach mode."""
        try:
            from . import session_manager
            stress_score = 0.5
            frustration_score = 0.3

            overwhelm_state = session_manager.check_overwhelm_state(
                user_id=self.user_id,
                stress_score=stress_score,
                frustration_score=frustration_score
            )

            if overwhelm_state.get("level") == "severe":
                self._role_override = "coach"
                auto_coach_prompt = """=== AUTO-COACH MODUS AKTIVIERT ===
WICHTIG: Schwerer Overwhelm erkannt. Du MUSST im Coach-Modus antworten.
Regeln:
1. NUR 1 konkrete Aktion anbieten
2. Maximal 3 kurze Sätze
3. Validierung + eine Option"""
                if self._budget:
                    self._budget.allocate(ComponentType.SYSTEM, auto_coach_prompt, priority=2)
                else:
                    self._prompt_parts.append(auto_coach_prompt)
                self._injected.append("overwhelm_auto_coach")
                log_with_context(logger, "info", "Auto-coach mode activated (overwhelm)",
                               user_id=self.user_id, level=overwhelm_state.get("level"))
        except Exception as e:
            self._warnings.append(f"overwhelm: {str(e)}")

    def _inject_patterns(self) -> None:
        """Inject pattern detection context for recurring topics."""
        try:
            from . import pattern_detector
            patterns = pattern_detector.get_relevant_patterns(
                user_id=self.user_id,
                current_query=self.query,
                days=30
            )
            if patterns:
                pattern_prompt = pattern_detector.build_pattern_context(patterns)
                self._prompt_parts.append(pattern_prompt)
                self._injected.append("patterns")
                log_with_context(logger, "debug", "Pattern context injected",
                               pattern_count=len(patterns))
        except Exception as e:
            self._warnings.append(f"patterns: {str(e)}")

    def _inject_coach_os(self) -> None:
        """Inject Coach OS context (lightweight, always if user_id)."""
        try:
            from . import knowledge_db
            coaching = knowledge_db.get_coaching_context(telegram_id=self.user_id)
            if coaching.get("profile"):
                mode = coaching.get("coaching_mode", "coach")
                coach_parts = [f"=== MODE: {mode.upper()} ==="]

                if coaching.get("adhd_contracts"):
                    coach_parts.append("ADHD: " + ", ".join(coaching["adhd_contracts"][:2]))

                if len(coach_parts) > 1:
                    coach_prompt = "\n".join(coach_parts)
                    self._prompt_parts.append(coach_prompt)
                    self._injected.append("coach_os")
                    log_with_context(logger, "debug", "Coach OS context injected", mode=mode)
        except Exception as e:
            self._warnings.append(f"coach_os: {str(e)}")

    def _inject_session_context(self) -> None:
        """Inject multi-turn session context."""
        try:
            from . import session_manager
            context_prompt = session_manager.build_context_prompt(
                user_id=self.user_id,
                current_query=self.query,
                days_back=7,
                include_pending=True
            )
            if context_prompt:
                self._prompt_parts.append(context_prompt)
                self._injected.append("session")
                log_with_context(logger, "debug", "Session context injected",
                               user_id=self.user_id, context_length=len(context_prompt))
        except Exception as e:
            self._warnings.append(f"session: {str(e)}")

    def _inject_thread_limit(self) -> None:
        """Check and inject thread limit warnings."""
        try:
            from . import session_manager
            user_profile = self._get_user_profile()
            max_threads = 3
            if user_profile:
                max_threads = user_profile.get("work_prefs", {}).get("max_parallel_threads", 3)

            thread_status = session_manager.check_thread_limit(self.user_id, max_threads=max_threads)

            if thread_status.get("exceeded"):
                thread_prompt = f"=== THREAD LIMIT ===\nActive: {thread_status['active_count']}, Max: {max_threads}"
                self._prompt_parts.append(thread_prompt)
                self._injected.append("thread_limit")
                log_with_context(logger, "warning", "Thread limit exceeded",
                               user_id=self.user_id,
                               active=thread_status['active_count'],
                               max=max_threads)
        except Exception as e:
            self._warnings.append(f"thread_limit: {str(e)}")

    def _get_user_profile(self) -> Optional[Dict[str, Any]]:
        """Get user profile from knowledge DB."""
        try:
            from . import knowledge_db
            profile_data = knowledge_db.get_person_profile("micha", approved_only=False)
            if profile_data and profile_data.get("content"):
                if isinstance(profile_data["content"], str):
                    return json.loads(profile_data["content"])
                return profile_data["content"]
        except Exception:
            pass
        return None

    def _should_inject_calendar_context(self) -> bool:
        """
        T-021: Selective Context Injection
        Only inject calendar context for schedule-related queries.
        """
        schedule_keywords = [
            "termin", "meeting", "kalender", "heute", "morgen", "diese woche",
            "zeitplan", "uhrzeit", "wann", "appointment", "termin", "zeitslot",
            "verfügbar", "verfügbarkeit", "zeitfenster"
        ]
        query_lower = self.query.lower()
        return any(kw in query_lower for kw in schedule_keywords)

    def _should_inject_email_context(self) -> bool:
        """
        T-021: Selective Context Injection
        Only inject email/recent activity context for communication queries.
        """
        email_keywords = [
            "email", "mail", "nachricht", "wer hat", "von wem", "inbox",
            "wer", "wrote", "geschrieben", "letzte", "recent", "message",
            "chat", "telegram", "whatsapp"
        ]
        query_lower = self.query.lower()
        return any(kw in query_lower for kw in email_keywords)

    def _should_inject_knowledge_context(self) -> bool:
        """
        T-021: Selective Context Injection
        Only inject knowledge base context for search/info queries or complex queries.
        """
        knowledge_keywords = [
            "suche", "find", "wo ist", "zeig mir", "liste", "info", "wissen",
            "wie", "was ist", "erklär", "dokumentation", "anleitung"
        ]
        query_lower = self.query.lower()
        has_keyword = any(kw in query_lower for kw in knowledge_keywords)
        return has_keyword or self.query_class == "complex"

    def _apply_query_class_filtering(self) -> None:
        """
        T-021: Selective Context Injection - Nov 3, 2026
        Filter context injection based on query class (simple/standard/complex).
        Reduces token overhead for simple and standard queries.
        """
        if not self.include_context:
            return

        # For simple queries: minimal context only (datetime)
        if self.query_class == "simple":
            # Already injected: datetime
            # Skip: session_memory, coaching, entity, sentiment, patterns, etc.
            log_with_context(
                logger, "debug",
                "Query class SIMPLE: limiting context injection",
                skip_email=True, skip_calendar=True, skip_knowledge=True
            )
            return

        # For standard queries: selective context based on keywords
        if self.query_class == "standard":
            # Only inject if relevant
            if "entity" in self.contexts_to_inject and not self._should_inject_knowledge_context():
                self.contexts_to_inject.discard("entity")
            
            # Note: Calendar and email injection is already conditional
            # This just makes it more explicit

        # For complex queries: include all requested contexts (default behavior)
        # No filtering applied

    def add_persona_style(self, persona_id: Optional[str]) -> None:
        """Add persona style prompt (called separately after build)."""
        if not persona_id:
            return

        try:
            from . import persona as persona_module
            style_prompt = persona_module.generate_style_prompt(persona_id)
            if style_prompt:
                self._prompt_parts.append(style_prompt)
                self._injected.append("persona_style")
        except Exception as e:
            self._warnings.append(f"persona_style: {str(e)}")
