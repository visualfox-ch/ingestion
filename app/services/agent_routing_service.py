"""
Agent Routing Service - Phase 22A-07

Intent-based routing of queries to specialist agents:
- Intent classification with confidence scores per domain
- Single-agent routing (confidence > 0.8)
- Multi-agent routing (overlapping domains)
- Fallback to Jarvis core (no clear domain)
- Response aggregation for multi-agent queries

Architecture:
    User Query
        |
        v
    [Intent Classifier] --> confidence scores per domain
        |
        v
    [Agent Router]
        |--- Single agent (confidence > 0.8)
        |--- Multi-agent (overlapping domains)
        |--- Jarvis core (no clear domain)
        v
    [Specialist Agent(s)] <--> [Shared Knowledge Pool]
        |
        v
    [Response Aggregator]
        |
        v
    User Response
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timedelta
from enum import Enum
import re
import json

from ..observability import get_logger, log_with_context
from ..postgres_state import get_conn

logger = get_logger("jarvis.agent_routing")


class AgentDomain(str, Enum):
    """Supported agent domains."""
    FITNESS = "fitness"
    WORK = "work"
    COMMUNICATION = "communication"
    SAAS = "saas"
    GENERAL = "general"


@dataclass
class IntentClassification:
    """Result of intent classification."""
    primary_domain: AgentDomain
    confidence_scores: Dict[str, float]
    detected_intents: List[str]
    keywords_matched: Dict[str, List[str]]
    requires_multi_agent: bool
    reasoning: str


@dataclass
class RoutingDecision:
    """Decision on how to route a query."""
    strategy: str  # single, multi, core
    primary_agent: Optional[str]
    secondary_agents: List[str]
    confidence: float
    intent_classification: IntentClassification
    context_hints: Dict[str, Any]


@dataclass
class AgentResponse:
    """Response from an agent."""
    agent_name: str
    domain: str
    content: str
    confidence: float
    tools_used: List[str]
    execution_time_ms: int
    success: bool
    error: Optional[str] = None


@dataclass
class AggregatedResponse:
    """Aggregated response from multiple agents."""
    primary_response: str
    agent_contributions: List[Dict[str, Any]]
    total_agents: int
    total_execution_time_ms: int
    aggregation_strategy: str


# Domain-specific intent patterns
INTENT_PATTERNS = {
    AgentDomain.FITNESS: {
        "keywords": [
            "workout", "exercise", "training", "gym", "fitness", "sport",
            "run", "running", "laufen", "joggen", "swim", "schwimmen",
            "bike", "cycling", "radfahren", "weights", "gewichte",
            "cardio", "strength", "kraft", "muscle", "muskel",
            "calories", "kalorien", "nutrition", "ernährung", "diet",
            "protein", "carbs", "fett", "fat", "macro", "makros",
            "health", "gesundheit", "weight", "gewicht", "bmi",
            "steps", "schritte", "sleep", "schlaf", "recovery", "erholung",
            "stretch", "dehnen", "yoga", "pilates", "hiit",
            "squat", "deadlift", "bench", "push-up", "pull-up",
            "kilometer", "km", "meter", "wiederholungen", "sets", "reps"
        ],
        "intent_phrases": [
            r"log.*workout", r"track.*exercise", r"how many.*calories",
            r"fitness.*trend", r"exercise.*suggest", r"workout.*plan",
            r"traini(ng|ert)", r"sport.*gemacht", r"gelaufen",
            r"wie viel.*protein", r"kalorie.*getrackt"
        ],
        "context_signals": ["recent_workout", "fitness_goal_active", "morning_routine"]
    },
    AgentDomain.WORK: {
        "keywords": [
            "task", "aufgabe", "project", "projekt", "work", "arbeit",
            "meeting", "deadline", "frist", "priority", "priorität",
            "focus", "fokus", "pomodoro", "productivity", "produktivität",
            "schedule", "zeitplan", "calendar", "kalender", "termin",
            "email", "message", "report", "bericht", "document",
            "code", "programming", "entwicklung", "deploy", "release",
            "bug", "feature", "sprint", "backlog", "jira", "asana",
            "client", "kunde", "presentation", "präsentation",
            "estimate", "schätzung", "hours", "stunden", "billable",
            "review", "feedback", "collaboration", "zusammenarbeit"
        ],
        "intent_phrases": [
            r"prioritize.*task", r"estimate.*time", r"focus.*session",
            r"what.*work.*today", r"pending.*task", r"deadline.*coming",
            r"arbeiten.*an", r"projekt.*status", r"was.*erledigen",
            r"wie lange.*dauern", r"meeting.*schedule"
        ],
        "context_signals": ["work_hours", "active_project", "upcoming_deadline"]
    },
    AgentDomain.COMMUNICATION: {
        "keywords": [
            "email", "message", "nachricht", "inbox", "postfach",
            "reply", "antwort", "respond", "contact", "kontakt",
            "relationship", "beziehung", "network", "netzwerk",
            "followup", "follow-up", "nachfassen", "check-in",
            "meeting", "call", "anruf", "phone", "telefon",
            "linkedin", "telegram", "whatsapp", "slack", "teams",
            "colleague", "kollege", "friend", "freund", "client",
            "birthday", "geburtstag", "reminder", "erinnerung",
            "draft", "entwurf", "template", "vorlage", "tone",
            "formal", "casual", "professional", "freundlich"
        ],
        "intent_phrases": [
            r"draft.*email", r"reply.*message", r"who.*contact",
            r"follow.*up.*with", r"relationship.*with", r"inbox.*triage",
            r"wem.*schreiben", r"nachricht.*an", r"email.*beantworten",
            r"kontakt.*pflegen", r"geburtstag.*von"
        ],
        "context_signals": ["pending_messages", "relationship_followup", "recent_contact"]
    },
    AgentDomain.SAAS: {
        "keywords": [
            "saas", "revenue", "umsatz", "funnel", "conversion", "churn",
            "retention", "mrr", "arr", "ltv", "cac", "pricing", "preis",
            "experiment", "growth", "wachstum", "icp", "customer", "segment",
            "onboarding", "activation", "subscription", "abo", "trial",
            "freemium", "upgrade", "downgrade", "cancellation", "paywall",
            "nps", "csat", "cohort", "tier", "feature", "product-led",
            "go-to-market", "gtm", "product", "produkt"
        ],
        "intent_phrases": [
            r"review.*funnel", r"funnel.*metriken", r"growth.*experiment",
            r"icp.*signal", r"pricing.*hypothes", r"churn.*analyse",
            r"retention.*rate", r"mrr.*trend", r"experiment.*priorisier",
            r"saas.*metric", r"produkt.*wachstum"
        ],
        "context_signals": ["saas_review", "revenue_check", "experiment_backlog"]
    }
}

# Agent name mapping
DOMAIN_TO_AGENT = {
    AgentDomain.FITNESS: "fit_jarvis",
    AgentDomain.WORK: "work_jarvis",
    AgentDomain.COMMUNICATION: "comm_jarvis",
    AgentDomain.SAAS: "saas_jarvis",
    AgentDomain.GENERAL: "jarvis_core"
}


class IntentClassifier:
    """
    Classifies user queries into domains with confidence scores.

    Uses:
    - Keyword matching (weighted by density)
    - Intent phrase matching (regex patterns)
    - Context signals (time of day, recent activity)
    - Explicit agent mentions
    """

    def __init__(self):
        self._compile_patterns()

    def _compile_patterns(self):
        """Pre-compile regex patterns for performance."""
        self._compiled_patterns: Dict[AgentDomain, List[re.Pattern]] = {}
        for domain, config in INTENT_PATTERNS.items():
            self._compiled_patterns[domain] = [
                re.compile(pattern, re.IGNORECASE)
                for pattern in config.get("intent_phrases", [])
            ]

    def classify(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None
    ) -> IntentClassification:
        """
        Classify a query into domains with confidence scores.

        Returns confidence scores for each domain (0.0 - 1.0).
        """
        query_lower = query.lower()
        context = context or {}

        scores: Dict[str, float] = {}
        keywords_matched: Dict[str, List[str]] = {}
        detected_intents: List[str] = []

        # Check for explicit agent mentions first
        explicit_agent = self._check_explicit_mention(query_lower)
        if explicit_agent:
            for domain in AgentDomain:
                if domain == explicit_agent:
                    scores[domain.value] = 1.0
                else:
                    scores[domain.value] = 0.0

            return IntentClassification(
                primary_domain=explicit_agent,
                confidence_scores=scores,
                detected_intents=["explicit_mention"],
                keywords_matched={explicit_agent.value: ["explicit"]},
                requires_multi_agent=False,
                reasoning=f"Explicit mention of {DOMAIN_TO_AGENT.get(explicit_agent, 'agent')}"
            )

        # Calculate scores for each domain
        for domain, config in INTENT_PATTERNS.items():
            score = 0.0
            matched_keywords = []

            # Keyword matching (0.0 - 0.6)
            keywords = config.get("keywords", [])
            for keyword in keywords:
                if keyword.lower() in query_lower:
                    matched_keywords.append(keyword)

            if keywords:
                keyword_density = len(matched_keywords) / len(keywords)
                keyword_score = min(0.6, keyword_density * 3)  # Cap at 0.6
                score += keyword_score

            # Intent phrase matching (0.0 - 0.3)
            patterns = self._compiled_patterns.get(domain, [])
            pattern_matches = 0
            for pattern in patterns:
                if pattern.search(query):
                    pattern_matches += 1
                    detected_intents.append(f"{domain.value}:{pattern.pattern}")

            if patterns:
                pattern_score = min(0.3, pattern_matches * 0.15)
                score += pattern_score

            # Context signals (0.0 - 0.1)
            context_signals = config.get("context_signals", [])
            context_matches = sum(1 for s in context_signals if context.get(s))
            if context_signals:
                context_score = min(0.1, context_matches * 0.05)
                score += context_score

            scores[domain.value] = round(min(1.0, score), 3)
            if matched_keywords:
                keywords_matched[domain.value] = matched_keywords

        # Add general domain score (inverse of specialization)
        max_specialist_score = max(
            scores.get(d.value, 0) for d in AgentDomain if d != AgentDomain.GENERAL
        )
        scores[AgentDomain.GENERAL.value] = round(
            max(0.0, 0.5 - max_specialist_score * 0.5), 3
        )

        # Determine primary domain
        primary = max(scores.keys(), key=lambda k: scores[k])
        primary_domain = AgentDomain(primary)

        # Check for multi-agent need (multiple domains > 0.4)
        high_confidence_domains = [
            d for d, s in scores.items()
            if s >= 0.4 and d != AgentDomain.GENERAL.value
        ]
        requires_multi = len(high_confidence_domains) > 1

        # Generate reasoning
        if max(scores.values()) < 0.3:
            reasoning = "No strong domain match - routing to general Jarvis"
        elif requires_multi:
            reasoning = f"Multi-domain query: {', '.join(high_confidence_domains)}"
        else:
            top_keywords = keywords_matched.get(primary, [])[:3]
            reasoning = f"Primary domain: {primary} (keywords: {', '.join(top_keywords)})"

        return IntentClassification(
            primary_domain=primary_domain,
            confidence_scores=scores,
            detected_intents=detected_intents[:5],  # Limit for readability
            keywords_matched=keywords_matched,
            requires_multi_agent=requires_multi,
            reasoning=reasoning
        )

    def _check_explicit_mention(self, query_lower: str) -> Optional[AgentDomain]:
        """Check for explicit agent mention."""
        explicit_patterns = {
            AgentDomain.FITNESS: ["fitjarvis", "fit jarvis", "@fit", "fitness agent"],
            AgentDomain.WORK: ["workjarvis", "work jarvis", "@work", "work agent"],
            AgentDomain.COMMUNICATION: ["commjarvis", "comm jarvis", "@comm", "communication agent"],
            AgentDomain.SAAS: ["saasjarvis", "saas jarvis", "@saas", "saas agent", "revenue agent"]
        }

        for domain, patterns in explicit_patterns.items():
            for pattern in patterns:
                if pattern in query_lower:
                    return domain

        return None


class AgentRouter:
    """
    Routes queries to appropriate specialist agents.

    Routing strategies:
    - Single: One agent handles the query (confidence > 0.8)
    - Multi: Multiple agents contribute (overlapping domains)
    - Core: Jarvis core handles (no clear domain)
    """

    def __init__(self, classifier: IntentClassifier = None):
        self.classifier = classifier or IntentClassifier()
        self._ensure_tables()

    def _ensure_tables(self):
        """Ensure routing tables exist."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS jarvis_routing_decisions (
                            id SERIAL PRIMARY KEY,
                            query_hash VARCHAR(32),
                            strategy VARCHAR(20),
                            primary_agent VARCHAR(50),
                            secondary_agents JSONB DEFAULT '[]',
                            confidence REAL,
                            intent_scores JSONB,
                            routing_time_ms INTEGER,
                            created_at TIMESTAMP DEFAULT NOW()
                        )
                    """)

                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS jarvis_routing_outcomes (
                            id SERIAL PRIMARY KEY,
                            routing_id INTEGER REFERENCES jarvis_routing_decisions(id),
                            agents_executed JSONB,
                            total_time_ms INTEGER,
                            success BOOLEAN,
                            user_satisfaction VARCHAR(20),
                            error_message TEXT,
                            created_at TIMESTAMP DEFAULT NOW()
                        )
                    """)

                    cur.execute("""
                        CREATE INDEX IF NOT EXISTS idx_routing_decisions_strategy
                        ON jarvis_routing_decisions(strategy)
                    """)

                    cur.execute("""
                        CREATE INDEX IF NOT EXISTS idx_routing_decisions_agent
                        ON jarvis_routing_decisions(primary_agent)
                    """)

                    conn.commit()
        except Exception as e:
            log_with_context(logger, "debug", "Table creation failed", error=str(e))

    def route(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
        force_agent: Optional[str] = None
    ) -> RoutingDecision:
        """
        Route a query to the appropriate agent(s).

        Args:
            query: User query
            context: Optional context (session, time, recent activity)
            force_agent: Override routing to specific agent

        Returns:
            RoutingDecision with strategy and agent assignment
        """
        import time
        start = time.time()

        # Force routing if specified
        if force_agent:
            return RoutingDecision(
                strategy="forced",
                primary_agent=force_agent,
                secondary_agents=[],
                confidence=1.0,
                intent_classification=IntentClassification(
                    primary_domain=AgentDomain.GENERAL,
                    confidence_scores={},
                    detected_intents=["forced"],
                    keywords_matched={},
                    requires_multi_agent=False,
                    reasoning=f"Forced routing to {force_agent}"
                ),
                context_hints={"forced": True}
            )

        # Classify intent
        classification = self.classifier.classify(query, context)

        # Determine routing strategy
        primary_confidence = classification.confidence_scores.get(
            classification.primary_domain.value, 0
        )

        if primary_confidence >= 0.8:
            # High confidence - single agent
            strategy = "single"
            primary_agent = DOMAIN_TO_AGENT.get(
                classification.primary_domain, "jarvis_core"
            )
            secondary_agents = []

        elif classification.requires_multi_agent:
            # Multiple domains with significant confidence
            strategy = "multi"
            primary_agent = DOMAIN_TO_AGENT.get(
                classification.primary_domain, "jarvis_core"
            )

            # Get secondary agents with confidence > 0.4
            secondary_agents = []
            for domain_str, score in classification.confidence_scores.items():
                if score >= 0.4 and domain_str != classification.primary_domain.value:
                    try:
                        domain = AgentDomain(domain_str)
                        if domain != AgentDomain.GENERAL:
                            secondary_agents.append(DOMAIN_TO_AGENT.get(domain))
                    except ValueError:
                        continue

        elif primary_confidence >= 0.3:
            # Moderate confidence - single agent with context
            strategy = "single"
            primary_agent = DOMAIN_TO_AGENT.get(
                classification.primary_domain, "jarvis_core"
            )
            secondary_agents = []

        else:
            # Low confidence - use core Jarvis
            strategy = "core"
            primary_agent = "jarvis_core"
            secondary_agents = []

        # Build context hints
        context_hints = self._build_context_hints(
            classification, context or {}
        )

        routing_time = int((time.time() - start) * 1000)

        decision = RoutingDecision(
            strategy=strategy,
            primary_agent=primary_agent,
            secondary_agents=secondary_agents,
            confidence=primary_confidence,
            intent_classification=classification,
            context_hints=context_hints
        )

        # Record decision
        self._record_decision(query, decision, routing_time)

        return decision

    def _build_context_hints(
        self,
        classification: IntentClassification,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Build context hints for agent execution."""
        hints = {
            "detected_intents": classification.detected_intents,
            "keyword_density": sum(
                len(kw) for kw in classification.keywords_matched.values()
            ),
            "multi_domain": classification.requires_multi_agent
        }

        # Add relevant context
        if context.get("session_id"):
            hints["session_continuity"] = True
        if context.get("recent_agent"):
            hints["previous_agent"] = context["recent_agent"]
        if context.get("time_of_day"):
            hints["time_context"] = context["time_of_day"]

        return hints

    def _record_decision(
        self,
        query: str,
        decision: RoutingDecision,
        routing_time_ms: int
    ):
        """Record routing decision for analytics."""
        try:
            import hashlib
            query_hash = hashlib.md5(query.encode()).hexdigest()[:16]

            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO jarvis_routing_decisions
                        (query_hash, strategy, primary_agent, secondary_agents,
                         confidence, intent_scores, routing_time_ms)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """, (
                        query_hash,
                        decision.strategy,
                        decision.primary_agent,
                        json.dumps(decision.secondary_agents),
                        decision.confidence,
                        json.dumps(decision.intent_classification.confidence_scores),
                        routing_time_ms
                    ))
                    conn.commit()
        except Exception as e:
            log_with_context(logger, "debug", "Decision recording failed", error=str(e))


class ResponseAggregator:
    """
    Aggregates responses from multiple agents.

    Strategies:
    - Sequential: Primary first, enrich with secondary
    - Parallel: All agents contribute equally
    - Weighted: Based on confidence scores
    """

    def aggregate(
        self,
        responses: List[AgentResponse],
        strategy: str = "weighted"
    ) -> AggregatedResponse:
        """
        Aggregate multiple agent responses into a unified response.

        Args:
            responses: List of agent responses
            strategy: Aggregation strategy (sequential, parallel, weighted)

        Returns:
            AggregatedResponse with unified content
        """
        if not responses:
            return AggregatedResponse(
                primary_response="No agent responses received.",
                agent_contributions=[],
                total_agents=0,
                total_execution_time_ms=0,
                aggregation_strategy=strategy
            )

        if len(responses) == 1:
            r = responses[0]
            return AggregatedResponse(
                primary_response=r.content,
                agent_contributions=[{
                    "agent": r.agent_name,
                    "domain": r.domain,
                    "confidence": r.confidence,
                    "content": r.content
                }],
                total_agents=1,
                total_execution_time_ms=r.execution_time_ms,
                aggregation_strategy="single"
            )

        # Sort by confidence for weighted strategy
        sorted_responses = sorted(
            responses, key=lambda r: r.confidence, reverse=True
        )

        # Build aggregated response
        if strategy == "sequential":
            primary = sorted_responses[0]
            secondary_content = "\n\n".join(
                f"[{r.agent_name}]: {r.content}"
                for r in sorted_responses[1:]
                if r.success
            )
            full_response = primary.content
            if secondary_content:
                full_response += f"\n\n---\nAdditional context:\n{secondary_content}"

        elif strategy == "parallel":
            full_response = "\n\n".join(
                f"**{r.agent_name}**:\n{r.content}"
                for r in sorted_responses
                if r.success
            )

        else:  # weighted
            primary = sorted_responses[0]

            # Extract unique insights from secondary responses
            secondary_insights = []
            for r in sorted_responses[1:]:
                if r.success and r.confidence >= 0.4:
                    # Add only if content is substantially different
                    if r.content not in primary.content:
                        secondary_insights.append(
                            f"({r.agent_name}: {self._extract_key_insight(r.content)})"
                        )

            full_response = primary.content
            if secondary_insights:
                full_response += "\n\n" + " ".join(secondary_insights)

        contributions = [
            {
                "agent": r.agent_name,
                "domain": r.domain,
                "confidence": r.confidence,
                "success": r.success,
                "time_ms": r.execution_time_ms
            }
            for r in responses
        ]

        total_time = sum(r.execution_time_ms for r in responses)

        return AggregatedResponse(
            primary_response=full_response,
            agent_contributions=contributions,
            total_agents=len(responses),
            total_execution_time_ms=total_time,
            aggregation_strategy=strategy
        )

    def _extract_key_insight(self, content: str, max_chars: int = 100) -> str:
        """Extract key insight from content."""
        # Get first sentence or truncate
        if "." in content[:max_chars]:
            return content[:content.index(".") + 1]
        return content[:max_chars] + "..." if len(content) > max_chars else content


class AgentRoutingService:
    """
    Main service for intent-based agent routing.

    Combines:
    - Intent classification
    - Agent routing
    - Response aggregation
    """

    def __init__(self):
        self.classifier = IntentClassifier()
        self.router = AgentRouter(self.classifier)
        self.aggregator = ResponseAggregator()

    def route_query(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
        force_agent: Optional[str] = None
    ) -> RoutingDecision:
        """Route a query to appropriate agent(s)."""
        return self.router.route(query, context, force_agent)

    def classify_intent(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None
    ) -> IntentClassification:
        """Classify query intent without routing."""
        return self.classifier.classify(query, context)

    def aggregate_responses(
        self,
        responses: List[AgentResponse],
        strategy: str = "weighted"
    ) -> AggregatedResponse:
        """Aggregate multiple agent responses."""
        return self.aggregator.aggregate(responses, strategy)

    def get_routing_stats(
        self,
        days: int = 7
    ) -> Dict[str, Any]:
        """Get routing statistics."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT
                            strategy,
                            primary_agent,
                            COUNT(*) as count,
                            AVG(confidence) as avg_confidence,
                            AVG(routing_time_ms) as avg_routing_time
                        FROM jarvis_routing_decisions
                        WHERE created_at > NOW() - INTERVAL '%s days'
                        GROUP BY strategy, primary_agent
                        ORDER BY count DESC
                    """, (days,))

                    rows = cur.fetchall()

                    stats_by_strategy: Dict[str, int] = {}
                    stats_by_agent: Dict[str, int] = {}

                    for row in rows:
                        strategy = row["strategy"]
                        agent = row["primary_agent"]
                        count = row["count"]

                        stats_by_strategy[strategy] = stats_by_strategy.get(strategy, 0) + count
                        stats_by_agent[agent] = stats_by_agent.get(agent, 0) + count

                    # Get total count
                    cur.execute("""
                        SELECT COUNT(*) as total
                        FROM jarvis_routing_decisions
                        WHERE created_at > NOW() - INTERVAL '%s days'
                    """, (days,))
                    total = cur.fetchone()["total"]

                    return {
                        "success": True,
                        "period_days": days,
                        "total_routes": total,
                        "by_strategy": stats_by_strategy,
                        "by_agent": stats_by_agent,
                        "avg_confidence": round(
                            sum(r["avg_confidence"] * r["count"] for r in rows) / total
                            if total > 0 else 0, 3
                        ),
                        "avg_routing_time_ms": round(
                            sum(r["avg_routing_time"] * r["count"] for r in rows) / total
                            if total > 0 else 0, 1
                        )
                    }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def test_routing(self, queries: List[str]) -> List[Dict[str, Any]]:
        """Test routing for multiple queries (for debugging)."""
        results = []
        for query in queries:
            decision = self.route_query(query)
            results.append({
                "query": query[:50] + "..." if len(query) > 50 else query,
                "strategy": decision.strategy,
                "primary_agent": decision.primary_agent,
                "confidence": decision.confidence,
                "reasoning": decision.intent_classification.reasoning
            })
        return results


# Singleton
_service: Optional[AgentRoutingService] = None


def get_agent_routing_service() -> AgentRoutingService:
    """Get or create agent routing service singleton."""
    global _service
    if _service is None:
        _service = AgentRoutingService()
    return _service
