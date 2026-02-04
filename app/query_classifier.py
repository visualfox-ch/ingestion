"""
Query Classifier - Fast-Path Detection for Simple Queries

Detects query complexity to enable fast-path optimization:
- Simple queries: No tools, minimal context, Haiku model, <500ms target
- Standard queries: Reduced tools, selective context, Sonnet-4, <2s target
- Complex queries: Full context, all tools, Sonnet-4, <5s target

Classification is regex-based for zero latency overhead.
"""
from typing import Tuple
import re
from .observability import get_logger, log_with_context

logger = get_logger("jarvis.query_classifier")


# Simple query patterns - no tools needed, minimal context
SIMPLE_PATTERNS = [
    # Greetings
    r"^(hi|hallo|hey|guten\s+(morgen|tag|abend)|moin|guten\s+nacht)[\s!?.]*$",
    # Status checks / small talk
    r"^(wie\s+(geht'?s?|geht\s+es)|alles\s+klar|was\s+geht|wie\s+isch)[\s?!.]*$",
    # Time/date simple queries
    r"^(wie\s+sp[aä]t|welcher\s+tag|datum\s+heute|uhrzeit)[\s?!.]*$",
    # Simple acknowledgments
    r"^(danke|ok|okay|alles\s+klar|verstanden|gut|super|jo)[\s!.]*$",
    # Quick yes/no
    r"^(ja|nein|ja?|nee?)[\s?!.]*$",
    # Very short greetings
    r"^(guten\s+morgen|gutes?\s+tag|abend|nacht|yo|hey)[\s!?]*$",
]

# Keywords indicating complex queries (need full tools + context)
COMPLEX_INDICATORS = [
    # Analysis
    "analysiere", "vergleiche", "finde alle", "evaluiere",
    "bewerte", "beurteile", "untersuche", "prüfe", "teste",
    # Explanation
    "erkläre", "warum", "wie funktioniert", "zusammenfassung",
    "erklär", "erklär mir", "versteh ich nicht",
    # Code/Creation
    "code", "schreibe", "generiere", "erstelle", "programmiere",
    "script", "funktion", "klasse", "import", "package",
    # Communication
    "email", "schreib", "antworte", "nachricht", "telegram",
    # Multi-step/Complex
    "projekt", "datei", "dokument", "speichern", "laden",
    "kalender", "termin", "angebot", "verkauf", "marketing",
    # Numbers/Analysis
    "prozent", "statistik", "trend", "ausreißer", "anomalie",
]

# Keywords for standard queries (selective context + reduced tools)
STANDARD_INDICATORS = [
    # Calendar/Schedule
    "termin", "meeting", "kalender", "heute", "morgen", "diese woche",
    "zeitplan", "uhrzeit", "wann", "appointment",
    # Email/Messages
    "email", "mail", "nachricht", "wer hat geschrieben", "inbox",
    "wer", "von wem", "letzte", "recent",
    # Quick searches
    "suche", "suche nach", "find", "wo ist", "zeig mir", "liste",
    # Briefing
    "briefing", "was steht an", "überblick", "agenda",
    # Status
    "status", "wie weit", "fertig", "erledigt", "offen",
]


def classify_query(query: str) -> Tuple[str, float]:
    """
    Classify query complexity using regex patterns.
    
    Returns:
        Tuple of (classification, confidence)
        - "simple": Fast-path candidate (no tools, minimal context)
        - "standard": Normal agent flow (reduced tools, selective context)
        - "complex": Full agent flow (all tools, full context)
    """
    if not query or not isinstance(query, str):
        return ("standard", 0.5)
    
    query_lower = query.lower().strip()
    
    # Check simple patterns first (highest priority)
    for pattern in SIMPLE_PATTERNS:
        if re.match(pattern, query_lower, re.IGNORECASE):
            log_with_context(
                logger, "debug", "Query classified as SIMPLE",
                pattern=pattern, confidence=0.95
            )
            return ("simple", 0.95)
    
    # Check for explicit complex indicators
    complex_score = 0.0
    for indicator in COMPLEX_INDICATORS:
        if indicator in query_lower:
            complex_score += 0.15
    
    if complex_score >= 0.3:
        log_with_context(
            logger, "debug", "Query classified as COMPLEX",
            indicator_score=complex_score, confidence=0.85
        )
        return ("complex", 0.85)
    
    # Check for standard indicators
    standard_score = 0.0
    for indicator in STANDARD_INDICATORS:
        if indicator in query_lower:
            standard_score += 0.1
    
    if standard_score >= 0.2:
        log_with_context(
            logger, "debug", "Query classified as STANDARD",
            indicator_score=standard_score, confidence=0.75
        )
        return ("standard", 0.75)
    
    # Short queries without complex indicators -> likely simple
    word_count = len(query_lower.split())
    if word_count <= 5 and "?" not in query_lower and "!" not in query_lower:
        confidence = 0.7 - (word_count * 0.05)  # Decay confidence slightly per word
        log_with_context(
            logger, "debug", "Query classified as SIMPLE (short)",
            word_count=word_count, confidence=confidence
        )
        return ("simple", confidence)
    
    # Default to standard if uncertain
    log_with_context(
        logger, "debug", "Query classified as STANDARD (default)",
        confidence=0.6
    )
    return ("standard", 0.6)


def get_fast_path_model() -> str:
    """Return the model to use for simple queries (fast + cheap)."""
    return "claude-3-5-haiku-20241022"


def get_standard_model() -> str:
    """Return the model to use for standard queries (balanced)."""
    return "claude-sonnet-4-20250514"


def get_minimal_system_prompt() -> str:
    """Return minimal system prompt for simple queries (~200 tokens)."""
    return """Du bist Jarvis, Michas persönlicher Assistent.

KERNFÄHIGKEITEN:
- Kurze, freundliche Antworten
- Einfache Fragen beantworten
- Grüße und Bestätigungen

ANTWORTSTIL:
- Kurz und freundlich (1-2 Sätze max)
- Echt, nicht formell
- Wenn unsicher: "Das weiß ich nicht genau."

KEINE Tools verfügbar für simple Queries."""


def get_minimal_tools() -> list:
    """Return minimal tool set for simple queries (none)."""
    return []


def get_reduced_tools() -> list:
    """
    Return reduced tool set for standard queries.
    Include only ~8-10 most common tools based on usage patterns.
    
    Tools selected based on:
    - High frequency of use (search, calendar, recent activity)
    - Low latency (no code generation, no complex analysis)
    - User-facing value (information retrieval, communication)
    """
    return [
        "search_knowledge",          # Most used: knowledge retrieval
        "get_calendar_events",       # High value: schedule awareness
        "get_recent_activity",       # High value: activity summary
        "get_person_context",        # Useful: person information
        "recall_conversation_history",  # Continuity
        "recall_facts",              # User preference retrieval
        "get_gmail_messages",        # Communication
        "proactive_hint",            # Coaching hints
        "no_tool_needed",            # Explicit no-op
    ]


def get_complex_tools() -> list:
    """
    Return full tool set for complex queries.
    Includes all 29 tools for maximum capability.
    """
    # Return all tool names - will be filtered by get_tool_definitions()
    return None  # None means "all tools"


def should_use_fast_path(query_class: str, confidence: float) -> bool:
    """
    Determine if we should use fast-path based on classification.
    
    Fast-path enabled if:
    - Query is "simple" and confidence >= 0.8
    - This avoids false positives
    """
    threshold = 0.8
    try:
        from .config_manager import get_config_manager
        config = get_config_manager()
        threshold = float(config.get("classifier:confidence_threshold", 0.8))
    except Exception:
        threshold = 0.8

    if query_class == "simple" and confidence >= threshold:
        log_with_context(
            logger, "info", "Fast-path ENABLED",
            query_class=query_class, confidence=confidence, threshold=threshold
        )
        return True
    
    log_with_context(
        logger, "debug", "Fast-path DISABLED",
        query_class=query_class, confidence=confidence, threshold=threshold
    )
    return False
