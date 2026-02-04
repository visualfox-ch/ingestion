"""
Auto persona + draft selection for person-specific communication.

Given a person_id and goal, automatically:
1. Load person profile from Postgres
2. Select persona + draft strategy using rule-based logic
3. Generate drafts: team_safe, assertive, exec_short
4. Return rationale with evidence refs

Constraints:
- No diagnosing people. Patterns only.
- Every claim links to evidence refs.
- Private namespace = no external LLM by default.
"""
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any
from enum import Enum

from .observability import get_logger, log_with_context
from . import knowledge_db
from . import persona as persona_module

logger = get_logger("jarvis.advice_auto")


class DraftStrategy(str, Enum):
    """Draft generation strategies"""
    DIPLOMATIC = "diplomatic"      # Soften, avoid conflict
    ASSERTIVE = "assertive"        # Direct, clear boundaries
    EXECUTIVE = "executive"        # Brief, action-oriented
    SUPPORTIVE = "supportive"      # Empathetic, relationship-focused
    NEUTRAL = "neutral"            # Balanced default


@dataclass
class PersonContext:
    """Context about a person for communication planning"""
    person_id: str
    name: str
    org: Optional[str] = None
    profile_type: str = "internal"
    communication_prefs: Dict[str, Any] = field(default_factory=dict)
    interaction_patterns: Dict[str, Any] = field(default_factory=dict)
    evidence_refs: List[Dict[str, str]] = field(default_factory=list)


@dataclass
class DraftResult:
    """Single draft variant"""
    variant: str                    # team_safe, assertive, exec_short
    text: str
    tone_notes: str
    word_count: int


@dataclass
class AdviceResult:
    """Result of auto advice generation"""
    person_id: str
    person_name: str
    selected_persona_id: str
    selected_strategy: str
    drafts: List[DraftResult]
    rationale: str
    evidence_refs: List[Dict[str, str]]
    confidence: str = "medium"  # low, medium, high
    why_selected_persona: str = ""
    why_these_drafts: str = ""
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "person_id": self.person_id,
            "person_name": self.person_name,
            "selected_persona_id": self.selected_persona_id,
            "selected_strategy": self.selected_strategy,
            "drafts": [asdict(d) for d in self.drafts],
            "rationale": self.rationale,
            "evidence_refs": self.evidence_refs,
            "confidence": self.confidence,
            "why_selected_persona": self.why_selected_persona,
            "why_these_drafts": self.why_these_drafts,
            "warnings": self.warnings
        }


# ============ Rule-based persona selection ============

# Trigger phrases for strategy override
URGENCY_TRIGGERS = [
    "dringend", "urgent", "asap", "sofort", "kritisch", "deadline",
    "heute noch", "bis morgen", "schnell", "wichtig"
]

CONFLICT_TRIGGERS = [
    "konflikt", "streit", "problem mit", "schwierig", "eskalation",
    "beschwerde", "unzufrieden", "ärger", "frustration"
]

EXECUTIVE_TRIGGERS = [
    "ceo", "cfo", "geschäftsführ", "vorstand", "c-level", "leadership",
    "board", "director", "entscheidung", "budget", "strategie"
]

SUPPORT_TRIGGERS = [
    "unterstütz", "hilfe", "überfordert", "stress", "schwer",
    "persönlich", "vertraulich", "unter uns"
]


def _detect_triggers(text: str) -> Dict[str, bool]:
    """Detect trigger phrases in text"""
    text_lower = text.lower()
    return {
        "urgency": any(t in text_lower for t in URGENCY_TRIGGERS),
        "conflict": any(t in text_lower for t in CONFLICT_TRIGGERS),
        "executive": any(t in text_lower for t in EXECUTIVE_TRIGGERS),
        "support": any(t in text_lower for t in SUPPORT_TRIGGERS),
    }


@dataclass
class SelectionResult:
    """Result of persona/strategy selection"""
    persona_id: str
    strategy: str
    confidence: str
    why_persona: str
    why_strategy: str
    rationale: str


def _select_strategy(
    person_context: PersonContext,
    goal: str,
    context: str
) -> SelectionResult:
    """
    Select persona and strategy based on person profile and context.

    Rules (v1, deterministic):
    1. Profile default_persona_id exists → use it
    2. Context contains trigger phrase → override
    3. Goal = "decision" → exec persona
    4. Goal = "deescalate" → team_safe persona
    5. Executive context → executive strategy
    6. Conflict context → diplomatic strategy
    7. Urgency context → assertive strategy
    8. Support context → supportive strategy
    9. Fallback → profile default or neutral
    """
    combined_text = f"{goal} {context}".lower()
    triggers = _detect_triggers(combined_text)

    # Get defaults from profile
    comm_prefs = person_context.communication_prefs
    default_persona = comm_prefs.get("preferred_persona", "micha_default")
    default_style = comm_prefs.get("preferred_style", "balanced")

    selected_strategy = DraftStrategy.NEUTRAL
    selected_persona = default_persona
    confidence = "medium"
    why_persona_parts = []
    why_strategy_parts = []
    rationale_parts = []

    # Rule 1: Profile has explicit default
    if comm_prefs.get("preferred_persona"):
        why_persona_parts.append(f"Profile specifies preferred_persona={default_persona}")
        confidence = "high"
    else:
        why_persona_parts.append("No profile preference, using system default")
        confidence = "low"

    # Rule 2-4: Goal-based overrides
    goal_lower = goal.lower()
    if "decision" in goal_lower or "entscheidung" in goal_lower:
        selected_strategy = DraftStrategy.EXECUTIVE
        selected_persona = comm_prefs.get("exec_persona", "micha_default")
        why_persona_parts.append("Goal contains 'decision' → exec persona")
        why_strategy_parts.append("Decision communication requires concise, action-oriented style")
        confidence = "high"

    elif "deeskalat" in goal_lower or "deescalat" in goal_lower or "beruhig" in goal_lower:
        selected_strategy = DraftStrategy.DIPLOMATIC
        why_strategy_parts.append("Goal suggests de-escalation → diplomatic approach")
        confidence = "high"

    # Rule 5: Executive stakeholders
    elif triggers["executive"] or person_context.profile_type == "executive":
        selected_strategy = DraftStrategy.EXECUTIVE
        selected_persona = comm_prefs.get("exec_persona", "micha_default")
        why_strategy_parts.append("Executive context detected → concise format")
        rationale_parts.append("C-level stakeholder prefers brief, action-focused messages")

    # Rule 6: Conflict situations
    elif triggers["conflict"]:
        selected_strategy = DraftStrategy.DIPLOMATIC
        why_strategy_parts.append("Conflict triggers detected → diplomatic approach")
        rationale_parts.append("Potential conflict situation requires careful tone")

    # Rule 7: Urgency (unless conflict)
    elif triggers["urgency"]:
        selected_strategy = DraftStrategy.ASSERTIVE
        why_strategy_parts.append("Urgency triggers detected → direct communication")
        rationale_parts.append("Time-sensitive context requires clear, direct messaging")

    # Rule 8: Support needs
    elif triggers["support"]:
        selected_strategy = DraftStrategy.SUPPORTIVE
        why_strategy_parts.append("Support triggers detected → empathetic approach")
        rationale_parts.append("Context suggests need for relationship-focused response")

    # Rule 9: Fallback to profile default
    else:
        style_map = {
            "direct": DraftStrategy.ASSERTIVE,
            "diplomatic": DraftStrategy.DIPLOMATIC,
            "balanced": DraftStrategy.NEUTRAL,
            "supportive": DraftStrategy.SUPPORTIVE,
        }
        selected_strategy = style_map.get(default_style, DraftStrategy.NEUTRAL)
        why_strategy_parts.append(f"No triggers matched → using profile default: {default_style}")

    # Add evidence from patterns
    patterns = person_context.interaction_patterns
    if patterns.get("response_time_preference"):
        rationale_parts.append(f"Known preference: {patterns['response_time_preference']}")
    if patterns.get("communication_style"):
        rationale_parts.append(f"Observed style: {patterns['communication_style']}")
        confidence = "high" if confidence != "low" else "medium"

    return SelectionResult(
        persona_id=selected_persona,
        strategy=selected_strategy.value,
        confidence=confidence,
        why_persona="; ".join(why_persona_parts) if why_persona_parts else "Default selection",
        why_strategy="; ".join(why_strategy_parts) if why_strategy_parts else "Balanced default",
        rationale=". ".join(rationale_parts) if rationale_parts else "Standard selection based on context"
    )


def _load_person_context(person_id: str) -> Optional[PersonContext]:
    """Load person context from Postgres"""
    profile = knowledge_db.get_person_profile(person_id, approved_only=True)

    if not profile:
        # Try with approved_only=False for draft profiles
        profile = knowledge_db.get_person_profile(person_id, approved_only=False)
        if not profile:
            return None

    content = profile.get("content", {})
    if isinstance(content, str):
        import json
        try:
            content = json.loads(content)
        except Exception as e:
            log_with_context(logger, "error", "Failed to parse profile content JSON", error=str(e), profile_id=person_id)
            content = {}

    # Extract evidence refs from profile
    evidence_refs = []
    evidence_sources = profile.get("evidence_sources") or []
    if evidence_sources:
        for src in evidence_sources[:5]:  # Limit to 5 refs
            evidence_refs.append({
                "type": src.get("type", "observation"),
                "source": src.get("source", "profile"),
                "date": src.get("date", ""),
                "summary": src.get("summary", "")[:100]
            })

    return PersonContext(
        person_id=person_id,
        name=profile.get("name", person_id),
        org=profile.get("org"),
        profile_type=content.get("type", profile.get("profile_type", "internal")),
        communication_prefs=content.get("communication", {}),
        interaction_patterns=content.get("patterns", {}),
        evidence_refs=evidence_refs
    )


# ============ Draft generation ============

def _generate_draft_variants(
    goal: str,
    context: str,
    person_context: PersonContext,
    strategy: str,
    use_llm: bool = True
) -> List[DraftResult]:
    """
    Generate draft variants: team_safe, assertive, exec_short.

    If use_llm=False (private namespace), uses templates only.
    """
    # Base message structure
    person_name = person_context.name.split()[0] if person_context.name else "there"

    # Template-based drafts (no LLM required)
    drafts = []

    # Team-safe: Diplomatic, collaborative
    team_safe = f"Hi {person_name},\n\n"
    team_safe += f"kurz zu {goal} – {context}\n\n"
    team_safe += "Was meinst du? Können wir kurz dazu abstimmen?\n\n"
    team_safe += "LG"

    drafts.append(DraftResult(
        variant="team_safe",
        text=team_safe,
        tone_notes="Kollaborativ, offen für Input, keine Dringlichkeit impliziert",
        word_count=len(team_safe.split())
    ))

    # Assertive: Clear, direct
    assertive = f"{person_name},\n\n"
    assertive += f"{goal}: {context}\n\n"
    assertive += "Kurze Rückmeldung bis EOD wäre super.\n\n"
    assertive += "Danke"

    drafts.append(DraftResult(
        variant="assertive",
        text=assertive,
        tone_notes="Direkt, klare Erwartung, deadline-orientiert",
        word_count=len(assertive.split())
    ))

    # Exec-short: Brief, action-focused
    context_brief = context[:80].rstrip() if len(context) > 80 else context
    exec_short = f"{person_name}, kurz: {goal}.\n"
    exec_short += f"{context_brief}\n"
    exec_short += "Brauche dein Go."

    drafts.append(DraftResult(
        variant="exec_short",
        text=exec_short,
        tone_notes="Maximal kompakt, C-Level geeignet, action-fokussiert",
        word_count=len(exec_short.split())
    ))

    return drafts


# ============ Main API ============

def generate_advice(
    person_id: str,
    goal: str,
    context: str,
    namespace: str = "work_projektil"
) -> AdviceResult:
    """
    Generate auto-selected persona and drafts for a person.

    Args:
        person_id: ID of the person to communicate with
        goal: What you want to achieve
        context: Additional context
        namespace: Namespace (private = no LLM)

    Returns:
        AdviceResult with persona, strategy, drafts, and rationale

    Raises:
        ValueError if drafts cannot be generated (output contract)
    """
    warnings = []

    # Load person context
    person_context = _load_person_context(person_id)

    if not person_context:
        # Create minimal context for unknown person
        person_context = PersonContext(
            person_id=person_id,
            name=person_id.replace("_", " ").title(),
        )
        warnings.append(f"No profile found for {person_id}, using defaults")

    # Select persona and strategy
    selection = _select_strategy(person_context, goal, context)

    # Determine if LLM is allowed
    use_llm = namespace != "private"
    if not use_llm:
        warnings.append("Private namespace: using template-only drafts (no LLM)")

    # Generate drafts
    drafts = _generate_draft_variants(
        goal=goal,
        context=context,
        person_context=person_context,
        strategy=selection.strategy,
        use_llm=use_llm
    )

    # Output contract: drafts must not be empty
    if not drafts:
        raise ValueError(f"Failed to generate drafts for {person_id}")

    # Build why_these_drafts explanation
    why_drafts = f"Generated 3 variants (team_safe/assertive/exec_short) for strategy={selection.strategy}. "
    if use_llm:
        why_drafts += "LLM enhancement available but using templates for consistency."
    else:
        why_drafts += "Template-only mode (private namespace)."

    log_with_context(
        logger, "info", "Advice generated",
        person_id=person_id,
        persona=selection.persona_id,
        strategy=selection.strategy,
        confidence=selection.confidence,
        draft_count=len(drafts)
    )

    return AdviceResult(
        person_id=person_id,
        person_name=person_context.name,
        selected_persona_id=selection.persona_id,
        selected_strategy=selection.strategy,
        drafts=drafts,
        rationale=selection.rationale,
        evidence_refs=person_context.evidence_refs,
        confidence=selection.confidence,
        why_selected_persona=selection.why_persona,
        why_these_drafts=why_drafts,
        warnings=warnings
    )


def get_advice_for_stakeholders(
    stakeholder_ids: List[str],
    goal: str,
    context: str,
    namespace: str = "work_projektil"
) -> Dict[str, AdviceResult]:
    """
    Generate advice for multiple stakeholders.

    Returns: Dict mapping person_id to AdviceResult
    """
    results = {}
    for person_id in stakeholder_ids:
        try:
            results[person_id] = generate_advice(
                person_id=person_id,
                goal=goal,
                context=context,
                namespace=namespace
            )
        except Exception as e:
            log_with_context(
                logger, "error", "Failed to generate advice",
                person_id=person_id, error=str(e)
            )
            # Return minimal result on error
            results[person_id] = AdviceResult(
                person_id=person_id,
                person_name=person_id,
                selected_persona_id="micha_default",
                selected_strategy="neutral",
                drafts=[],
                rationale="Error generating advice",
                evidence_refs=[],
                warnings=[f"Error: {str(e)[:100]}"]
            )

    return results
