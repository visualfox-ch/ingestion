"""
Jarvis Sentiment Analyzer
Detects mood, urgency, and stress in user messages for proactive response adjustment.
Includes mode detection for automatic persona switching suggestions.
"""
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field, asdict

from .observability import get_logger, log_with_context

logger = get_logger("jarvis.sentiment")


# ============ Mode Detection ============

# Available modes from COACH_OS.md
AVAILABLE_MODES = {
    "coach": "Emotional containment, clarifying reflection, small safe next step",
    "analyst": "Systemic view, tradeoffs, risks, dependencies",
    "exec": "Decisions, next actions, minimal text",
    "debug": "Deterministic reasoning, commands, code, checks",
    "mirror": "I-statements, de-escalation drafts, relationship-aware language"
}

# Keywords that trigger mode suggestions
MODE_KEYWORDS = {
    "debug": {
        "high": [
            "bug", "error", "fehler", "exception", "traceback", "stack trace",
            "nicht funktioniert", "geht nicht", "kaputt", "crashed", "crash",
            "code", "script", "funktion", "function", "variable", "syntax"
        ],
        "medium": [
            "log", "output", "terminal", "console", "command", "befehl",
            "docker", "container", "api", "endpoint", "request", "response"
        ]
    },
    "mirror": {
        "high": [
            "email", "mail", "nachricht schreiben", "antworten auf",
            "konflikt", "conflict", "streit", "diskussion", "meeting",
            "chef", "kollege", "kollegin", "team", "kunde", "client"
        ],
        "medium": [
            "kommunikation", "gespräch", "gespraech", "feedback", "formulieren",
            "diplomatisch", "höflich", "hoeflich", "professionell", "antwort"
        ]
    },
    "analyst": {
        "high": [
            "analyse", "analysis", "strategie", "strategy", "vergleich",
            "optionen", "options", "vor- und nachteile", "pros cons",
            "bewerten", "evaluate", "entscheidung", "decision"
        ],
        "medium": [
            "risiko", "risk", "trade-off", "tradeoff", "abwägen", "abwaegen",
            "langfristig", "long-term", "architektur", "architecture"
        ]
    },
    "exec": {
        "high": [
            "was soll ich tun", "next step", "nächster schritt", "naechster schritt",
            "action", "todo", "aufgabe", "priorität", "prioritaet", "priority", "jetzt"
        ],
        "medium": [
            "plan", "timeline", "deadline", "owner", "verantwortlich"
        ]
    },
    "coach": {
        "high": [
            "überfordert", "ueberfordert", "overwhelmed", "hilfe", "support", "nicht mehr",
            "zu viel", "burnout", "stress", "angst", "unsicher", "verzweifelt"
        ],
        "medium": [
            "motivation", "energy", "energie", "müde", "muede", "erschöpft", "erschoepft",
            "fokus", "focus", "konzentration"
        ]
    }
}

# Sentiment → Mode mapping (fallback when no keywords match)
SENTIMENT_MODE_MAP = {
    "stress": "coach",
    "frustration": "coach",  # coach first, debug if technical
    "urgency": "exec",
    "positive": None,  # keep current mode
    "neutral": None
}


# Extended keyword lists for sentiment detection
SENTIMENT_KEYWORDS = {
    "urgency": {
        "high": [
            "dringend", "urgent", "asap", "sofort", "kritisch", "critical",
            "notfall", "emergency", "jetzt", "immediately", "schnellstens",
            "hoechste prioritaet", "top priority", "deadline heute", "muss heute"
        ],
        "medium": [
            "wichtig", "priority", "bald", "zeitnah", "schnell", "priorisieren",
            "nicht vergessen", "reminder", "today", "diese woche"
        ]
    },
    "stress": {
        "high": [
            "ueberfordert", "overwhelmed", "burnout", "am limit", "nicht mehr",
            "zu viel", "kann nicht mehr", "am ende", "kollaps", "zusammenbruch",
            "hilfe", "verzweifelt", "desperate", "panic"
        ],
        "medium": [
            "stress", "anstrengend", "muede", "erschoepft", "schwierig",
            "kompliziert", "chaotisch", "unuebersichtlich", "viel zu tun"
        ]
    },
    "frustration": {
        "high": [
            "schon wieder", "immer noch", "zum xten mal", "nervt", "aergert",
            "frustriert", "satt", "reicht", "genug", "unfassbar",
            "unglaublich", "was soll das", "unmoeglich", "katastrophe"
        ],
        "medium": [
            "problem", "issue", "nicht funktioniert", "geht nicht", "kaputt",
            "fehler", "bug", "haengt", "langsam", "umstaendlich"
        ]
    },
    "positive": {
        "high": [
            "super", "fantastisch", "excellent", "perfekt", "love", "begeistert",
            "genial", "brilliant", "awesome", "amazing", "wunderbar", "hervorragend"
        ],
        "medium": [
            "gut", "nice", "danke", "toll", "freue", "happy", "schoen",
            "funktioniert", "klappt", "erledigt", "geschafft", "prima"
        ]
    }
}

# Response recommendations based on sentiment
RESPONSE_RECOMMENDATIONS = {
    "urgency": {
        "high": "Priorisiere diese Anfrage. Biete konkrete, sofort umsetzbare Schritte an. Keine langen Erklaerungen.",
        "medium": "Behandle als wichtig. Biete klare naechste Schritte an."
    },
    "stress": {
        "high": "Zeige Verstaendnis. Biete Unterstuetzung an. Zerlege komplexe Aufgaben in kleine Schritte. Frage ob du helfen kannst zu priorisieren.",
        "medium": "Antworte ruhig und strukturiert. Hilf bei der Organisation."
    },
    "frustration": {
        "high": "Anerkenne das Problem direkt. Fokussiere auf Loesungen, nicht Erklaerungen. Vermeide Rechtfertigungen.",
        "medium": "Biete konstruktive Hilfe an. Schlage Alternativen vor."
    },
    "positive": {
        "high": "Teile die Freude kurz. Dann weiter zur Sache.",
        "medium": "Bestaetigung, dann weiter."
    }
}


@dataclass
class ModeRecommendation:
    """Recommendation for mode switch"""
    suggested_mode: Optional[str] = None  # coach, analyst, exec, debug, mirror
    confidence: float = 0.0               # 0.0 - 1.0
    reason: str = ""                      # Why this mode is suggested
    keywords_matched: List[str] = field(default_factory=list)
    requires_confirmation: bool = True    # HITL: ask before switching

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SentimentResult:
    """Result of sentiment analysis"""
    urgency_score: float = 0.0      # 0.0 - 1.0
    stress_score: float = 0.0
    frustration_score: float = 0.0
    positive_score: float = 0.0
    dominant: str = "neutral"       # urgency, stress, frustration, positive, neutral
    alert_level: str = "none"       # none, low, medium, high
    keywords_found: List[str] = field(default_factory=list)
    recommendation: str = ""
    mode_suggestion: Optional[ModeRecommendation] = None  # Mode switch suggestion

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        if self.mode_suggestion:
            d["mode_suggestion"] = self.mode_suggestion.to_dict()
        return d


def _calculate_score(text: str, keywords: Dict[str, List[str]]) -> tuple:
    """Calculate sentiment score and find matching keywords"""
    text_lower = text.lower()
    found_keywords = []
    score = 0.0

    # Check high-priority keywords (weight: 1.0)
    for keyword in keywords.get("high", []):
        if keyword in text_lower:
            score += 1.0
            found_keywords.append(keyword)

    # Check medium-priority keywords (weight: 0.5)
    for keyword in keywords.get("medium", []):
        if keyword in text_lower:
            score += 0.5
            found_keywords.append(keyword)

    # Normalize score to 0-1 range (cap at 1.0)
    normalized_score = min(1.0, score / 3.0)

    return normalized_score, found_keywords


def analyze_sentiment(text: str) -> SentimentResult:
    """
    Analyze sentiment of a single message.

    Args:
        text: The message text to analyze

    Returns:
        SentimentResult with scores and recommendations
    """
    if not text or not text.strip():
        return SentimentResult()

    all_keywords = []

    # Calculate scores for each sentiment type
    urgency_score, urgency_kw = _calculate_score(text, SENTIMENT_KEYWORDS["urgency"])
    stress_score, stress_kw = _calculate_score(text, SENTIMENT_KEYWORDS["stress"])
    frustration_score, frustration_kw = _calculate_score(text, SENTIMENT_KEYWORDS["frustration"])
    positive_score, positive_kw = _calculate_score(text, SENTIMENT_KEYWORDS["positive"])

    all_keywords = urgency_kw + stress_kw + frustration_kw + positive_kw

    # Determine dominant sentiment
    scores = {
        "urgency": urgency_score,
        "stress": stress_score,
        "frustration": frustration_score,
        "positive": positive_score
    }

    max_score = max(scores.values())
    if max_score > 0:
        dominant = max(scores.items(), key=lambda x: x[1])[0]
    else:
        dominant = "neutral"

    # Determine alert level
    if max_score >= 0.7:
        alert_level = "high"
    elif max_score >= 0.4:
        alert_level = "medium"
    elif max_score > 0:
        alert_level = "low"
    else:
        alert_level = "none"

    # Get recommendation
    recommendation = ""
    if dominant != "neutral" and alert_level in ["high", "medium"]:
        level = "high" if alert_level == "high" else "medium"
        recommendation = RESPONSE_RECOMMENDATIONS.get(dominant, {}).get(level, "")

    result = SentimentResult(
        urgency_score=round(urgency_score, 2),
        stress_score=round(stress_score, 2),
        frustration_score=round(frustration_score, 2),
        positive_score=round(positive_score, 2),
        dominant=dominant,
        alert_level=alert_level,
        keywords_found=all_keywords,
        recommendation=recommendation,
        mode_suggestion=None  # Will be set below
    )

    # Get mode suggestion based on text and sentiment
    mode_suggestion = get_suggested_mode(text, sentiment=result)
    result.mode_suggestion = mode_suggestion

    if alert_level != "none":
        log_with_context(logger, "debug", "Sentiment detected",
                        dominant=dominant, alert_level=alert_level,
                        keywords=len(all_keywords),
                        mode_suggestion=mode_suggestion.suggested_mode if mode_suggestion else None)

    return result


def analyze_conversation_sentiment(messages: List[str]) -> SentimentResult:
    """
    Aggregate sentiment across multiple messages.

    Args:
        messages: List of message texts

    Returns:
        Aggregated SentimentResult
    """
    if not messages:
        return SentimentResult()

    # Analyze each message and aggregate
    total_urgency = 0.0
    total_stress = 0.0
    total_frustration = 0.0
    total_positive = 0.0
    all_keywords = []

    for msg in messages:
        result = analyze_sentiment(msg)
        total_urgency += result.urgency_score
        total_stress += result.stress_score
        total_frustration += result.frustration_score
        total_positive += result.positive_score
        all_keywords.extend(result.keywords_found)

    n = len(messages)
    avg_urgency = total_urgency / n
    avg_stress = total_stress / n
    avg_frustration = total_frustration / n
    avg_positive = total_positive / n

    # Determine dominant
    scores = {
        "urgency": avg_urgency,
        "stress": avg_stress,
        "frustration": avg_frustration,
        "positive": avg_positive
    }

    max_score = max(scores.values())
    dominant = max(scores.items(), key=lambda x: x[1])[0] if max_score > 0 else "neutral"

    # Alert level based on average
    if max_score >= 0.5:
        alert_level = "high"
    elif max_score >= 0.25:
        alert_level = "medium"
    elif max_score > 0:
        alert_level = "low"
    else:
        alert_level = "none"

    # Get recommendation
    recommendation = ""
    if dominant != "neutral" and alert_level in ["high", "medium"]:
        level = "high" if alert_level == "high" else "medium"
        recommendation = RESPONSE_RECOMMENDATIONS.get(dominant, {}).get(level, "")

    return SentimentResult(
        urgency_score=round(avg_urgency, 2),
        stress_score=round(avg_stress, 2),
        frustration_score=round(avg_frustration, 2),
        positive_score=round(avg_positive, 2),
        dominant=dominant,
        alert_level=alert_level,
        keywords_found=list(set(all_keywords)),  # Dedupe
        recommendation=recommendation
    )


def get_sentiment_context(result: SentimentResult, include_mode: bool = True) -> str:
    """
    Format sentiment as a context string for the agent system prompt.

    Args:
        result: SentimentResult to format
        include_mode: Whether to include mode suggestion

    Returns:
        Formatted string for injection into system prompt
    """
    if result.alert_level == "none" and not result.mode_suggestion:
        return ""

    lines = []

    # Sentiment section
    if result.alert_level != "none":
        lines.append("=== SENTIMENT ALERT ===")

        # Map German labels
        sentiment_labels = {
            "urgency": "DRINGLICHKEIT",
            "stress": "STRESS",
            "frustration": "FRUSTRATION",
            "positive": "POSITIV"
        }

        label = sentiment_labels.get(result.dominant, result.dominant.upper())
        lines.append(f"Erkannte Stimmung: {label} ({result.alert_level})")

        if result.keywords_found:
            keywords_str = ", ".join(f'"{kw}"' for kw in result.keywords_found[:5])
            lines.append(f"Keywords: {keywords_str}")

        if result.recommendation:
            lines.append(f"Empfehlung: {result.recommendation}")

    # Mode suggestion section
    if include_mode and result.mode_suggestion and result.mode_suggestion.suggested_mode:
        ms = result.mode_suggestion
        if lines:
            lines.append("")  # Empty line separator

        mode_labels = {
            "coach": "COACH",
            "debug": "DEBUG",
            "analyst": "ANALYST",
            "exec": "EXEC",
            "mirror": "MIRROR"
        }

        mode_label = mode_labels.get(ms.suggested_mode, ms.suggested_mode.upper())
        lines.append(f"=== MODE SUGGESTION: {mode_label} ===")

        if ms.reason:
            lines.append(f"Grund: {ms.reason}")

        if ms.requires_confirmation:
            lines.append("Aktion: Frage den Nutzer ob er den Modus wechseln moechte.")
        else:
            lines.append("Aktion: Wechsle direkt in diesen Modus (hohe Konfidenz).")

    return "\n".join(lines)


def should_alert(result: SentimentResult) -> bool:
    """
    Check if sentiment warrants proactive intervention.

    Returns True for high urgency, stress, or frustration.
    """
    if result.alert_level == "high":
        return True
    if result.alert_level == "medium" and result.dominant in ["urgency", "stress"]:
        return True
    return False


# ============ Mode Detection Functions ============

def _calculate_mode_score(text: str, keywords: Dict[str, List[str]]) -> tuple:
    """Calculate mode relevance score and find matching keywords"""
    text_lower = text.lower()
    found_keywords = []
    score = 0.0

    # Check high-priority keywords (weight: 1.0)
    for keyword in keywords.get("high", []):
        if keyword in text_lower:
            score += 1.0
            found_keywords.append(keyword)

    # Check medium-priority keywords (weight: 0.5)
    for keyword in keywords.get("medium", []):
        if keyword in text_lower:
            score += 0.5
            found_keywords.append(keyword)

    return score, found_keywords


def get_suggested_mode(
    text: str,
    sentiment: SentimentResult = None,
    current_mode: str = None
) -> Optional[ModeRecommendation]:
    """
    Suggest a mode based on message content and sentiment.

    Args:
        text: The message text to analyze
        sentiment: Optional pre-computed sentiment result
        current_mode: Current active mode (won't suggest same mode)

    Returns:
        ModeRecommendation or None if no switch needed
    """
    if not text or not text.strip():
        return None

    # Calculate mode scores
    mode_scores = {}
    mode_keywords = {}

    for mode, keywords in MODE_KEYWORDS.items():
        score, found = _calculate_mode_score(text, keywords)
        if score > 0:
            mode_scores[mode] = score
            mode_keywords[mode] = found

    # Find best matching mode
    best_mode = None
    best_score = 0.0
    best_keywords = []

    if mode_scores:
        best_mode = max(mode_scores.items(), key=lambda x: x[1])[0]
        best_score = mode_scores[best_mode]
        best_keywords = mode_keywords.get(best_mode, [])

    # Fallback to sentiment-based mode if no keyword match
    if not best_mode and sentiment and sentiment.dominant != "neutral":
        fallback_mode = SENTIMENT_MODE_MAP.get(sentiment.dominant)
        if fallback_mode:
            best_mode = fallback_mode
            best_score = sentiment.urgency_score + sentiment.stress_score
            best_keywords = []

    # Don't suggest if same as current mode
    if best_mode == current_mode:
        return None

    # Only suggest if confidence is high enough
    confidence = min(1.0, best_score / 2.0)  # Normalize
    if confidence < 0.3:
        return None

    # Build reason
    reason = _build_mode_reason(best_mode, sentiment, best_keywords)

    # Determine if confirmation is required
    # High confidence + high stress/urgency can auto-switch
    requires_confirmation = True
    if confidence >= 0.8 and sentiment:
        if sentiment.alert_level == "high" and sentiment.dominant in ["stress", "urgency"]:
            requires_confirmation = False  # Auto-switch for urgent/stressed users

    return ModeRecommendation(
        suggested_mode=best_mode,
        confidence=round(confidence, 2),
        reason=reason,
        keywords_matched=best_keywords,
        requires_confirmation=requires_confirmation
    )


def _build_mode_reason(mode: str, sentiment: SentimentResult, keywords: List[str]) -> str:
    """Build a human-readable reason for mode suggestion"""
    reasons = {
        "coach": "Ich sehe Anzeichen von Stress oder Ueberforderung.",
        "debug": "Das klingt nach einem technischen Problem.",
        "analyst": "Das erfordert eine systematische Analyse.",
        "exec": "Hier braucht es konkrete naechste Schritte.",
        "mirror": "Das betrifft Kommunikation oder Beziehungen."
    }

    base_reason = reasons.get(mode, "")

    if keywords:
        keyword_str = ", ".join(f'"{k}"' for k in keywords[:3])
        base_reason += f" (Keywords: {keyword_str})"

    return base_reason


def get_mode_switch_prompt(recommendation: ModeRecommendation, current_mode: str = None) -> str:
    """
    Generate a user-facing prompt for mode switch confirmation.

    Args:
        recommendation: The mode recommendation
        current_mode: Current mode name

    Returns:
        Formatted string to show user
    """
    if not recommendation or not recommendation.suggested_mode:
        return ""

    mode_labels = {
        "coach": "Coach-Modus (empathisch, strukturierend)",
        "debug": "Debug-Modus (technisch, systematisch)",
        "analyst": "Analyst-Modus (Risiken, Trade-offs)",
        "exec": "Exec-Modus (Entscheidungen, Aktionen)",
        "mirror": "Mirror-Modus (Kommunikation, Beziehungen)"
    }

    suggested_label = mode_labels.get(recommendation.suggested_mode, recommendation.suggested_mode)

    lines = []
    if recommendation.reason:
        lines.append(recommendation.reason)

    lines.append(f"Soll ich in den {suggested_label} wechseln?")

    return " ".join(lines)


def should_suggest_mode_switch(
    result: SentimentResult,
    current_mode: str = None
) -> bool:
    """
    Quick check if a mode switch should be suggested.

    Returns True if there's a meaningful mode suggestion
    different from current mode.
    """
    if not result.mode_suggestion:
        return False

    suggestion = result.mode_suggestion
    if suggestion.suggested_mode == current_mode:
        return False

    if suggestion.confidence < 0.3:
        return False

    return True
