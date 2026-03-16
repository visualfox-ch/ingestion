"""
Context Selection for Agent Prompts
Determines which context modules to inject based on query analysis.
Replaces blanket context injection with selective, query-aware loading.
"""

import re
from typing import Set, Dict, Any


def detect_emotional_keywords(query: str) -> bool:
    """Detect if query has emotional/overwhelm indicators."""
    emotional_patterns = [
        r'\b(überwältigt|frustriert|gestresst|überfordert|müde|erschöpft|ängstlich|besorgt)\b',
        r'\b(zu viel|nicht schaffbar|unmöglich|hoffnungslos)\b',
        r'\b(hilf mir|ich kann nicht|was soll ich|nicht mehr)\b',
    ]
    query_lower = query.lower()
    return any(re.search(pattern, query_lower, re.IGNORECASE) for pattern in emotional_patterns)


def detect_coaching_needed(query: str, role: str) -> bool:
    """Detect if query needs coaching/emotional support context."""
    if role == "coach":
        return True
    
    coaching_patterns = [
        r'\b(sollte ich|wie gehe|mein ziel|fortschritt|feedback|motivation)\b',
        r'\b(besser|verbessern|arbeiten|produktiv|fokus|energie)\b',
        r'[?！]\s*$',  # Ends with question or exclamation
    ]
    query_lower = query.lower()
    return any(re.search(pattern, query_lower, re.IGNORECASE) for pattern in coaching_patterns)


def detect_entity_needed(query: str) -> bool:
    """Detect if query mentions people, projects, or dates."""
    entity_patterns = [
        r'\b(Philippe|Patrik|Micha|Michael|Emma|Roman|Anna)\b',  # Known names
        r'\b(projekt|task|thema|issue)\b',
        r'\b(letzte woche|gestern|morgen|heute|nächste woche|in (der|einer))\b',
    ]
    query_lower = query.lower()
    return any(re.search(pattern, query_lower, re.IGNORECASE) for pattern in entity_patterns)


def detect_pattern_needed(query: str) -> bool:
    """Detect if query is about recurring topics or patterns."""
    pattern_keywords = [
        r'\b(wiederholt|immer|regelmäßig|oft|muster|pattern|trend)\b',
        r'\b(wie oft|wie viele|statistik|analyze|überblick)\b',
    ]
    query_lower = query.lower()
    return any(re.search(pattern, query_lower, re.IGNORECASE) for pattern in pattern_keywords)


def detect_self_awareness_needed(query: str) -> bool:
    """Detect if query asks about Jarvis capabilities/limitations."""
    capability_patterns = [
        r'\b(kannst du|können|fähig|möglich|nicht möglich|tool|command|endpoint|api)\b',
        r'\b(was ist|was sind|welche|übersicht|feature|funktion)\b',
        r'\b(self-awareness|meta|jarvis|myself|myself|wer bin ich|beschreib dich)\b',
    ]
    query_lower = query.lower()
    return any(re.search(pattern, query_lower, re.IGNORECASE) for pattern in capability_patterns)


def select_contexts_to_inject(
    query: str,
    user_id: int = None,
    role: str = "assistant",
    include_context: bool = True
) -> Set[str]:
    """
    Determine which context modules to inject based on query analysis.
    
    Returns set of module names to inject:
    - "self_awareness": Jarvis capabilities & self-understanding
    - "coaching": Emotional support & coaching mode
    - "entity": Person/project/date entity context
    - "patterns": Recurring topic analysis
    - "sentiment": Emotional state detection
    - "overwhelm": Overwhelm state check
    - "coach_os": Coach OS (mode, contracts, preferences)
    """
    if not include_context or not user_id:
        return set()

    contexts: Set[str] = set()

    # Always inject: basic coaching style (lightweight)
    contexts.add("coach_os")

    # Always inject: session/conversation history for continuity (Phase 19)
    # This ensures Jarvis remembers past conversations automatically
    contexts.add("session")
    
    # Selective injection based on query analysis
    if detect_self_awareness_needed(query):
        contexts.add("self_awareness")
    
    if detect_coaching_needed(query, role):
        contexts.add("coaching")
        contexts.add("sentiment")
        contexts.add("overwhelm")
    
    if detect_entity_needed(query):
        contexts.add("entity")
    
    if detect_pattern_needed(query):
        contexts.add("patterns")
    
    return contexts


def should_use_minimal_system_prompt(query: str) -> bool:
    """
    Check if query is simple enough to use minimal system prompt.
    Simple queries: greetings, short questions, no context needed.
    """
    if len(query) > 100:
        return False
    
    simple_patterns = [
        r'^(hi|hello|hallo|hey|guten morgen|guten tag|was ist möglich)\b',
        r'^(ja|nein|ok|danke|thanks)$',
        r'\b(help|hilfe|wie|what is)\b.*[?]$',
    ]
    
    query_lower = query.lower().strip()
    return any(re.match(pattern, query_lower, re.IGNORECASE) for pattern in simple_patterns)
