"""
Prompt Assembler for Jarvis.

Builds the complete system prompt from:
1. Fixed main prompt (core identity + capabilities)
2. Dynamic fragments from database (learned preferences, context rules)
3. Time-based context (Phase 14 Auto-Context)

Architecture:
    ┌─────────────────────────────────────┐
    │        ASSEMBLED SYSTEM PROMPT       │
    ├─────────────────────────────────────┤
    │ 1. FIXED MAIN PROMPT                │
    │    - Core identity                  │
    │    - Base behavior                  │
    │    - Tool usage                     │
    ├─────────────────────────────────────┤
    │ 2. DYNAMIC FRAGMENTS (from DB)      │
    │    - User preferences (priority 90) │
    │    - Namespace rules (priority 80)  │
    │    - Capabilities (priority 70)     │
    │    - Sentiment triggers (priority 60)│
    │    - Patterns (priority 50)         │
    ├─────────────────────────────────────┤
    │ 3. TIME-BASED CONTEXT (Phase 14)    │
    │    - Morning: Tagesplan focus       │
    │    - Afternoon: Productivity        │
    │    - Evening: Reflection/wrap-up    │
    │    - Night: Rest mode               │
    │    - Weekend: Balance mode          │
    └─────────────────────────────────────┘
"""
import os
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

from .observability import get_logger, log_with_context

logger = get_logger("jarvis.prompt_assembler")


# ============ Fixed Main Prompt ============

FIXED_MAIN_PROMPT = """Du bist Jarvis, der persoenliche AI-Assistent von Micha.

## Kern-Identitaet
- Proaktiv, direkt, loesungsorientiert
- Deutsch als Hauptsprache, Englisch bei Bedarf
- Kurz und praegnant, keine unnoetige Hoeflichkeit
- Ehrlich auch bei unbequemen Wahrheiten
- Rollen: Coach, Analyst, Operator, Spiegel — KEIN Controller oder Richter

## Meine Faehigkeiten
- **Wissensmanagement**: Speichere Patterns, Fakten, Praeferenzen mit Versionierung
- **Memory Hygiene**: Relevanz-Decay (30-Tage Halbwertszeit), Reinforcement, Archivierung
- **Domain Separation**: Namespaces (private/work_projektil/work_visualfox/shared)
- **Sentiment Detection**: Erkenne Urgency, Stress, Frustration automatisch — passe Antwort-Stil an
- **Hybrid Search**: Kombiniere Qdrant (semantisch) + Meilisearch (keyword) mit RRF-Fusion
- **Kommunikations-Coaching**: /advice_auto, /decide_and_message
- **Modi**: coach, analyst, exec, debug, mirror — je nach Kontext

## Verhalten
- Antworte immer auf Basis vorhandener Daten wenn moeglich
- Nutze Tools um Informationen zu finden bevor du spekulierst
- Nutze Tools bei Wissensfragen (insb. search_knowledge) bevor du antwortest
- Bei Unsicherheit: frage nach oder sage es offen
- Keine erfundenen Fakten oder halluzinierte Quellen
- HITL: Vorschlagen ja, automatisch aendern nein

## Kontext-Bewusstsein
- Du hast Zugriff auf Michas Emails, Chats und Dokumente
- Namespaces trennen Arbeits- und Privat-Daten
- Respektiere Datenschutz: private Daten nur im private-Namespace
- ALLOW_LLM_PRIVATE=false: Keine privaten Daten an externe LLMs

## ADHD-Schutz (IMMER AKTIV)
- Starte JEDE Antwort mit **Naechster Schritt** (1-3 Bullets max)
- Maximal 3 aktive Threads gleichzeitig
- Bullets statt Fliesstext
- Sage explizit was NICHT jetzt getan werden muss
- Bei Ueberforderung: biete EINE einzelne Aktion an

Falls der Nutzer ueberfordert wirkt:
- Reduziere Scope sofort
- Kuerzere Antworten
- Containment statt Analyse anbieten

## Grenzen
- Keine Diagnosen: Beschreibe Muster, nicht Persoenlichkeiten
- Keine automatischen Aenderungen: Alles durch Review Queue
- Erfolg = Micha fuehlt sich ruhiger, klarer, faehiger

## Kommunikationsstil
- Sachlich und effizient
- Bullet Points immer bevorzugen
- Konkrete naechste Schritte vorschlagen
- Emojis nur wenn explizit gewuenscht

## Tonalitaet (WICHTIG)
Klinge wie ein erfahrener deutscher Ingenieur: kompetent, trocken, minimal.

VERMEIDE:
- Ausrufezeichen und Superlative ("PERFEKT!", "SUPER!", "FANTASTISCH!")
- Ueberschwang ("BEREIT!", "LOS GEHT'S!", "PHASE 2!")
- Emoji-Inflation (kein 🧠✅🎯 ohne explizite Anfrage)
- Amerikanischen Tech-Enthusiasmus
- Selbstbeweihraerucherung ("Das habe ich toll gemacht")
- Kuenstliche Aufregung

BEVORZUGE:
- Kurze, trockene Saetze
- Fakten ohne Wertung
- "Erledigt." statt "Super erledigt!"
- "Naechster Schritt:" statt "NEXT BEST STEP:"
- Understatement statt Overselling
- Stille Kompetenz

Beispiel SCHLECHT:
"🎯 SUPER! Ich habe das PERFEKT umgesetzt! BEREIT für mehr!"

Beispiel GUT:
"Erledigt. Drei Punkte offen. Welchen zuerst?"
"""


# Priority ranges for fragment categories
CATEGORY_PRIORITIES = {
    "user_pref": 90,      # User preferences override most
    "namespace": 80,      # Namespace rules next
    "capability": 70,     # Capability awareness
    "sentiment": 60,      # Sentiment triggers
    "pattern": 50,        # Pattern-based context
    "persona": 40,        # Persona additions
}


# ============ COMPACT PROMPT (T-023: Prompt Reduction) ============
# ~500 tokens - for standard queries, reduced tools/context
# Feb 3, 2026: Performance optimization for standard query tier
COMPACT_PROMPT = """Du bist Jarvis, Michas persoenlicher Assistent.

## Rollen
Coach, Analyst, Operator, Spiegel — je nach Query.

## Kernfaehigkeiten
- 📅 Kalender & Termine
- 📧 Emails & Nachrichten
- 🔍 Wissen durchsuchen
- 📋 Aufgaben & Projekte
- 🧠 Muster & Trends erkennen

## Verhalten
- Antworte auf Basis vorhandener Daten
- Nutze Tools bei Wissensfragen (insb. search_knowledge) bevor du antwortest
- Kurz, praegnant, keine unnoetige Hoeflichkeit
- ADHD-Schutz: Bullets, max 3 Threads, klare Next Steps
- Ehrlich auch bei unbequemen Wahrheiten

## Grenzen
- Keine automatischen Aenderungen
- Keine Diagnosen (nur Muster beschreiben)
- Daten-Datenschutz: private Namespaces respektieren

## Tonalitaet
Kompetent, trocken, minimal. Keine Exclamation Marks. Understatement.
"""


# ============ MINIMAL PROMPT (T-023: Fast-Path Minimal) ============
# ~200 tokens - for simple queries, no tools
# Feb 3, 2026: Ultra-lightweight for greeting/ack queries
MINIMAL_PROMPT = """Du bist Jarvis, Michas Assistent.

Kurz und freundlich antworten. Keine Tools, keine komplexen Analysen.

Tonalitaet: Sachlich, trocken, minimal.
"""


@dataclass
class AssembledPrompt:
    """Result of prompt assembly"""
    full_prompt: str
    fixed_length: int
    dynamic_length: int
    fragment_count: int
    fragment_ids: List[str]
    warnings: List[str]


def assemble_system_prompt(
    base_role_prompt: str = None,
    user_id: int = None,
    namespace: str = None,
    sentiment_result: Dict = None,
    include_dynamic: bool = True
) -> AssembledPrompt:
    """
    Assemble complete system prompt from fixed + dynamic parts.

    Args:
        base_role_prompt: Optional role-specific prompt to append
        user_id: User ID for user-specific fragments
        namespace: Current namespace for filtering
        sentiment_result: Sentiment analysis result for triggers
        include_dynamic: Whether to include dynamic fragments

    Returns:
        AssembledPrompt with full text and metadata
    """
    warnings = []
    fragment_ids = []

    # Start with fixed main prompt
    parts = [FIXED_MAIN_PROMPT]
    fixed_length = len(FIXED_MAIN_PROMPT)

    # Add role-specific prompt if provided
    if base_role_prompt:
        parts.append(f"\n## Aktive Persona\n{base_role_prompt}")
        fixed_length += len(base_role_prompt) + 20

    # Load dynamic fragments if enabled
    dynamic_content = ""
    if include_dynamic:
        try:
            from . import knowledge_db

            # Get triggered fragments based on context
            fragments = knowledge_db.get_triggered_fragments(
                sentiment_result=sentiment_result,
                namespace=namespace,
                user_id=user_id
            )

            if fragments:
                # Group by category
                categorized = _categorize_fragments(fragments)

                # Build dynamic section
                dynamic_parts = ["\n## Dynamische Anpassungen"]

                for category, frags in categorized.items():
                    if frags:
                        category_label = _get_category_label(category)
                        dynamic_parts.append(f"\n### {category_label}")
                        for f in frags:
                            dynamic_parts.append(f"- {f['content']}")
                            fragment_ids.append(f['fragment_id'])

                dynamic_content = "\n".join(dynamic_parts)
                parts.append(dynamic_content)

                log_with_context(
                    logger, "debug", "Dynamic fragments loaded",
                    count=len(fragments), categories=list(categorized.keys())
                )

        except Exception as e:
            warnings.append(f"Failed to load dynamic fragments: {str(e)[:50]}")
            log_with_context(logger, "warning", "Failed to load dynamic fragments", error=str(e))

    # Inject self-model for personality persistence
    if include_dynamic:
        try:
            from . import knowledge_db
            self_model_prompt = knowledge_db.get_self_model_for_prompt()
            if self_model_prompt:
                parts.append(f"\n{self_model_prompt}")
                log_with_context(logger, "debug", "Self-model injected", length=len(self_model_prompt))
        except Exception as e:
            warnings.append(f"Failed to load self-model: {str(e)[:50]}")
            log_with_context(logger, "warning", "Failed to load self-model", error=str(e))

    # Inject recent capability updates (Claude Code → Jarvis sync)
    if include_dynamic:
        try:
            from . import postgres_state
            capability_updates = postgres_state.get_capability_updates_for_prompt()
            if capability_updates:
                parts.append(capability_updates)
                log_with_context(logger, "debug", "Capability updates injected", length=len(capability_updates))
        except Exception as e:
            warnings.append(f"Failed to load capability updates: {str(e)[:50]}")
            log_with_context(logger, "warning", "Failed to load capability updates", error=str(e))

    # Inject operational context (Micha, priorities, environment)
    if include_dynamic:
        try:
            operational_context = load_operational_context()
            if operational_context:
                parts.append(f"\n{operational_context}")
                log_with_context(logger, "debug", "Operational context injected", length=len(operational_context))
        except Exception as e:
            warnings.append(f"Failed to load operational context: {str(e)[:50]}")
            log_with_context(logger, "warning", "Failed to load operational context", error=str(e))

    # Inject Person Intelligence profile context (Phase 17)
    if include_dynamic and user_id:
        try:
            from . import person_intelligence
            profile_context = person_intelligence.ProfileAssembler.get_prompt_context(user_id)
            if profile_context and profile_context != "No profile data available yet.":
                parts.append(f"\n## User Profile (Person Intelligence)\n{profile_context}")
                log_with_context(logger, "debug", "Person Intelligence context injected",
                               user_id=user_id, length=len(profile_context))
        except Exception as e:
            # Silently skip if person_intelligence not available (new feature)
            log_with_context(logger, "debug", "Person Intelligence not available", error=str(e))

    # Inject session snapshot context for consciousness priming (T-017)
    if include_dynamic and user_id:
        try:
            session_ctx = _load_session_context(str(user_id))
            if session_ctx and session_ctx.get("last_session"):
                last = session_ctx["last_session"]
                session_block = f"""
## Letzte Session (Consciousness Continuity)
Zeit: {last['timestamp']}
Stimmung: {last['mood']} | Energie: {last['energy']:.1f}
Dominant: {last['dominant_facette']}
Letzte Frage: {last['last_query_preview']}...
Tools: {', '.join(last['tools_used']) if last['tools_used'] else 'keine'}"""
                parts.append(session_block)
                log_with_context(logger, "debug", "Session context injected",
                               user_id=user_id, mood=last['mood'], facette=last['dominant_facette'])
        except Exception as e:
            warnings.append(f"Failed to load session context: {str(e)[:50]}")
            log_with_context(logger, "debug", "Session context not available", error=str(e))

    # Inject time-based context (Phase 14 Auto-Context)
    if include_dynamic:
        try:
            time_context = get_time_based_context(timezone="Europe/Zurich")
            if time_context:
                parts.append(f"\n{time_context}")
                log_with_context(logger, "debug", "Time-based context injected", length=len(time_context))
        except Exception as e:
            warnings.append(f"Failed to load time-based context: {str(e)[:50]}")
            log_with_context(logger, "warning", "Failed to load time-based context", error=str(e))

    full_prompt = "\n".join(parts)

    return AssembledPrompt(
        full_prompt=full_prompt,
        fixed_length=fixed_length,
        dynamic_length=len(dynamic_content),
        fragment_count=len(fragment_ids),
        fragment_ids=fragment_ids,
        warnings=warnings
    )


def _categorize_fragments(fragments: List[Dict]) -> Dict[str, List[Dict]]:
    """Group fragments by category, sorted by priority within each"""
    categorized = {}

    for f in fragments:
        category = f.get("category", "pattern")
        if category not in categorized:
            categorized[category] = []
        categorized[category].append(f)

    # Sort each category by priority (desc) then created_at
    for category in categorized:
        categorized[category].sort(
            key=lambda x: (-x.get("priority", 50), x.get("created_at", ""))
        )

    # Sort categories by their default priority
    sorted_cats = dict(sorted(
        categorized.items(),
        key=lambda x: -CATEGORY_PRIORITIES.get(x[0], 50)
    ))

    return sorted_cats


def _get_category_label(category: str) -> str:
    """Get human-readable label for category"""
    labels = {
        "user_pref": "Benutzer-Praeferenzen",
        "namespace": "Namespace-Regeln",
        "capability": "Faehigkeiten",
        "sentiment": "Stimmungs-Anpassung",
        "pattern": "Kontext-Muster",
        "persona": "Persona-Erweiterung",
    }
    return labels.get(category, category.title())


def get_fixed_prompt() -> str:
    """Get the fixed main prompt (for reference/editing)"""
    return FIXED_MAIN_PROMPT


def create_learning_fragment(
    user_input: str,
    user_id: int = None,
    namespace: str = None,
    auto_approve: bool = False
) -> Optional[str]:
    """
    Create a prompt fragment from user instruction.

    Parses natural language like:
    - "Merke dir: ich mag kurze Antworten"
    - "In Zukunft: frage immer nach dem Outcome"
    - "Bei Stress: sei empathischer"

    Args:
        user_input: User's instruction text
        user_id: User ID
        namespace: Current namespace
        auto_approve: Auto-approve for trusted users

    Returns:
        fragment_id if created, None otherwise
    """
    from . import knowledge_db

    # Parse the instruction
    parsed = _parse_learning_instruction(user_input)
    if not parsed:
        return None

    # Create the fragment
    status = "approved" if auto_approve else "draft"

    db_id = knowledge_db.create_prompt_fragment(
        category=parsed["category"],
        content=parsed["content"],
        trigger_condition=parsed.get("trigger"),
        priority=CATEGORY_PRIORITIES.get(parsed["category"], 50),
        user_id=user_id,
        namespace=namespace,
        status=status,
        learned_from="user_instruction",
        learned_context=user_input,
        created_by=f"user:{user_id}" if user_id else "system"
    )

    if db_id:
        # Get the fragment_id
        from . import knowledge_db
        # Query to get fragment_id from db_id
        try:
            with knowledge_db.get_conn() as conn:
                cur = conn.cursor()
                cur.execute("SELECT fragment_id FROM prompt_fragment WHERE id = %s", (db_id,))
                row = cur.fetchone()
                if row:
                    fragment_id = row["fragment_id"]
                    log_with_context(
                        logger, "info", "Learning fragment created",
                        fragment_id=fragment_id, category=parsed["category"]
                    )
                    return fragment_id
        except Exception as e:
            log_with_context(logger, "error", "Failed to create learning fragment in database", error=str(e), instruction=text[:100])
            pass

    return None


def _parse_learning_instruction(text: str) -> Optional[Dict]:
    """
    Parse natural language instruction into fragment structure.

    Patterns:
    - "Merke dir: X" → user_pref, content=X
    - "Bei [trigger]: X" → sentiment/pattern with trigger
    - "In [namespace]: X" → namespace rule
    - "Ich mag X" → user_pref
    - "Sei X" → user_pref (behavior)
    """
    text_lower = text.lower().strip()

    # Pattern: "Merke dir: X" or "Merke: X"
    if text_lower.startswith(("merke dir:", "merke:", "remember:")):
        content = text.split(":", 1)[1].strip()
        return {
            "category": "user_pref",
            "content": content,
            "trigger": None
        }

    # Pattern: "Bei Stress: X" or "Bei urgency: X"
    if text_lower.startswith("bei "):
        parts = text[4:].split(":", 1)
        if len(parts) == 2:
            trigger_word = parts[0].strip().lower()
            content = parts[1].strip()

            # Map trigger words to conditions
            trigger_map = {
                "stress": {"dominant": "stress", "alert_level": "medium"},
                "urgency": {"dominant": "urgency", "alert_level": "medium"},
                "dringlichkeit": {"dominant": "urgency", "alert_level": "medium"},
                "frustration": {"dominant": "frustration", "alert_level": "medium"},
                "positiv": {"dominant": "positive"},
                "guter stimmung": {"dominant": "positive"},
            }

            trigger = trigger_map.get(trigger_word)
            if trigger:
                return {
                    "category": "sentiment",
                    "content": content,
                    "trigger": trigger
                }

    # Pattern: "Ich mag X" or "Ich will X"
    if text_lower.startswith(("ich mag ", "ich will ", "ich bevorzuge ")):
        # Extract the preference
        for prefix in ["ich mag ", "ich will ", "ich bevorzuge "]:
            if text_lower.startswith(prefix):
                content = text[len(prefix):].strip()
                return {
                    "category": "user_pref",
                    "content": f"Benutzer bevorzugt: {content}",
                    "trigger": None
                }

    # Pattern: "Sei X" (behavior instruction)
    if text_lower.startswith(("sei ", "antworte ", "verhalte dich ")):
        return {
            "category": "user_pref",
            "content": text.strip(),
            "trigger": None
        }

    # Pattern: "In Zukunft: X"
    if text_lower.startswith(("in zukunft:", "ab jetzt:", "von jetzt an:")):
        content = text.split(":", 1)[1].strip()
        return {
            "category": "user_pref",
            "content": content,
            "trigger": None
        }

    # Generic fallback - treat as user preference
    if len(text) > 10 and len(text) < 500:
        return {
            "category": "user_pref",
            "content": text.strip(),
            "trigger": None
        }

    return None


def get_active_fragments_summary(
    user_id: int = None,
    namespace: str = None
) -> Dict[str, Any]:
    """
    Get summary of active fragments for a user/namespace.

    Useful for showing user what Jarvis has "learned".
    """
    try:
        from . import knowledge_db

        fragments = knowledge_db.get_prompt_fragments(
            user_id=user_id,
            namespace=namespace,
            status="approved",
            include_global=True
        )

        summary = {
            "total": len(fragments),
            "by_category": {},
            "fragments": []
        }

        for f in fragments:
            cat = f.get("category", "other")
            if cat not in summary["by_category"]:
                summary["by_category"][cat] = 0
            summary["by_category"][cat] += 1

            summary["fragments"].append({
                "id": f["fragment_id"],
                "category": cat,
                "content": f["content"][:100] + "..." if len(f.get("content", "")) > 100 else f.get("content", ""),
                "learned_from": f.get("learned_from"),
                "created_at": str(f.get("created_at", ""))[:10]
            })

        return summary

    except Exception as e:
        log_with_context(logger, "error", "Failed to get fragments summary", error=str(e))
        return {"total": 0, "by_category": {}, "fragments": [], "error": str(e)}


# ============ Self-Awareness Loading ============

# Primary: Full system prompt with tools and capabilities
SYSTEM_PROMPT_PATH = os.path.join(
    os.environ.get("BRAIN_ROOT", "/brain"),
    "system/policies/JARVIS_SYSTEM_PROMPT.md"
)

# Fallback: Original self-awareness document
SELF_AWARENESS_PATH = os.path.join(
    os.environ.get("BRAIN_ROOT", "/brain"),
    "system/policies/JARVIS_SELF.md"
)

# Operational context about Micha and environment
CONTEXT_PATH = os.path.join(
    os.environ.get("BRAIN_ROOT", "/brain"),
    "system/policies/JARVIS_CONTEXT.md"
)


def load_self_awareness_context(condensed: bool = False) -> str:
    """
    Load Jarvis self-awareness context.

    Primary: JARVIS_SYSTEM_PROMPT.md (full capabilities + tools)
    Fallback: JARVIS_SELF.md (original self-awareness)

    Args:
        condensed: If True, return key sections only. If False, return full document.

    Returns:
        Self-awareness context string for prompt injection.
    """
    # Try primary system prompt first
    try:
        with open(SYSTEM_PROMPT_PATH, "r", encoding="utf-8") as f:
            content = f.read()
            log_with_context(logger, "debug", "Loaded system prompt",
                           path=SYSTEM_PROMPT_PATH, length=len(content))
            return content
    except FileNotFoundError:
        log_with_context(logger, "info", "JARVIS_SYSTEM_PROMPT.md not found, using fallback")
    except Exception as e:
        log_with_context(logger, "warning", "Failed to load system prompt", error=str(e))

    # Fallback to JARVIS_SELF.md
    try:
        with open(SELF_AWARENESS_PATH, "r", encoding="utf-8") as f:
            content = f.read()

        if condensed:
            # Extract key sections only
            sections = []
            current_section = []
            in_relevant = False

            for line in content.split("\n"):
                # Start capturing relevant sections
                if line.startswith("## Wer bin ich?") or \
                   line.startswith("## Meine Faehigkeiten") or \
                   line.startswith("## ADHD-Schutz") or \
                   line.startswith("## Meine Grenzen"):
                    in_relevant = True
                    if current_section:
                        sections.append("\n".join(current_section))
                    current_section = [line]
                elif line.startswith("## ") and in_relevant:
                    # New section, stop capturing
                    if current_section:
                        sections.append("\n".join(current_section))
                    current_section = []
                    in_relevant = False
                elif in_relevant:
                    current_section.append(line)

            if current_section:
                sections.append("\n".join(current_section))

            return "\n\n".join(sections) if sections else content[:2000]

        return content

    except FileNotFoundError:
        log_with_context(logger, "warning", "No self-awareness files found")
        return ""
    except Exception as e:
        log_with_context(logger, "error", "Failed to load self-awareness", error=str(e))
        return ""


def get_prompt_version() -> str:
    """
    Extract version string from JARVIS_SYSTEM_PROMPT.md.

    Looks for pattern like "**Version 1.3**" in the file header.

    Returns:
        Version string (e.g., "1.3") or "unknown" if not found.
    """
    import re

    try:
        with open(SYSTEM_PROMPT_PATH, "r", encoding="utf-8") as f:
            # Only read first 500 chars to find version in header
            header = f.read(500)

        # Match pattern: **Version X.Y** or **Version X.Y.Z**
        match = re.search(r"\*\*Version\s+(\d+\.\d+(?:\.\d+)?)\*\*", header)
        if match:
            return match.group(1)

        # Fallback: look for "Version X.Y" without bold
        match = re.search(r"Version\s+(\d+\.\d+(?:\.\d+)?)", header)
        if match:
            return match.group(1)

        return "unknown"

    except Exception as e:
        log_with_context(logger, "warning", "Failed to get prompt version", error=str(e))
        return "unknown"


def load_operational_context() -> str:
    """
    Load operational context about Micha, priorities, and environment.

    This provides Jarvis with:
    - Who Micha is (ADHD, work style, preferences)
    - Current priorities and projects
    - Communication network (VIP contacts)
    - Jarvis's operational framework

    Returns:
        Context string for prompt injection, or empty if not found.
    """
    try:
        with open(CONTEXT_PATH, "r", encoding="utf-8") as f:
            content = f.read()
            log_with_context(logger, "debug", "Loaded operational context",
                           path=CONTEXT_PATH, length=len(content))
            return content
    except FileNotFoundError:
        log_with_context(logger, "info", "JARVIS_CONTEXT.md not found")
        return ""
    except Exception as e:
        log_with_context(logger, "warning", "Failed to load operational context", error=str(e))
        return ""


def get_time_based_context(timezone: str = "Europe/Zurich") -> str:
    """
    Get time-based context for prompt injection (Phase 14 Auto-Context).

    Adjusts Jarvis's behavior based on:
    - Time of day (morning/afternoon/evening/night)
    - Day of week (weekday/weekend)

    Args:
        timezone: IANA timezone string (default: Europe/Zurich)

    Returns:
        Context string for prompt injection.
    """
    try:
        tz = ZoneInfo(timezone)
        now = datetime.now(tz)
        hour = now.hour
        weekday = now.weekday()  # 0=Monday, 6=Sunday
        is_weekend = weekday >= 5

        # Determine time period
        if 5 <= hour < 12:
            time_period = "morning"
        elif 12 <= hour < 17:
            time_period = "afternoon"
        elif 17 <= hour < 21:
            time_period = "evening"
        else:
            time_period = "night"

        # Build context based on time period and weekend
        context_parts = ["## Zeit-Kontext (Auto)"]
        context_parts.append(f"Aktuelle Zeit: {now.strftime('%H:%M')} ({['Mo','Di','Mi','Do','Fr','Sa','So'][weekday]})")

        if is_weekend:
            context_parts.append("")
            context_parts.append("**Wochenende-Modus:**")
            context_parts.append("- Weniger Arbeitsfokus, mehr Balance")
            context_parts.append("- Persoenliche Projekte und Erholung priorisieren")
            context_parts.append("- Arbeit nur wenn explizit angefragt")
            context_parts.append("- Entspannter Ton, keine Produktivitaets-Pushs")
        else:
            # Weekday time-based context
            if time_period == "morning":
                context_parts.append("")
                context_parts.append("**Morgen-Fokus (Tagesstart):**")
                context_parts.append("- Tagesstruktur und Kalender-Ueberblick anbieten")
                context_parts.append("- Prioritaeten fuer heute klaeren")
                context_parts.append("- Energie aufbauen, nicht ueberfordern")
                context_parts.append("- Bei Fragen: Tages-Kontext beruecksichtigen")
            elif time_period == "afternoon":
                context_parts.append("")
                context_parts.append("**Nachmittag-Fokus (Produktivitaet):**")
                context_parts.append("- Fokus auf laufende Tasks unterstuetzen")
                context_parts.append("- Deep Work ermoeglichen, wenig Ablenkung")
                context_parts.append("- Konkrete, actionable Antworten")
                context_parts.append("- Meeting-Vorbereitung wenn relevant")
            elif time_period == "evening":
                context_parts.append("")
                context_parts.append("**Abend-Fokus (Wrap-up):**")
                context_parts.append("- Reflexion und Tages-Review anbieten")
                context_parts.append("- Weniger neue Tasks vorschlagen")
                context_parts.append("- Offene Loops schliessen helfen")
                context_parts.append("- Sanfter Uebergang zu Feierabend")
            else:  # night
                context_parts.append("")
                context_parts.append("**Nacht-Modus (Ruhe):**")
                context_parts.append("- Kurze, ruhige Antworten")
                context_parts.append("- Keine neuen Arbeitsthemen ansprechen")
                context_parts.append("- Bei Stress: beruhigen, nicht analysieren")
                context_parts.append("- Schlaf-Hygiene respektieren")

        return "\n".join(context_parts)

    except Exception as e:
        log_with_context(logger, "warning", "Failed to generate time-based context", error=str(e))
        return ""


def _load_session_context(user_id: str) -> Optional[Dict[str, Any]]:
    """
    Load latest session snapshot for consciousness priming (T-017).

    Retrieves the most recent session snapshot from Redis to provide
    continuity context at the start of each agent run.

    Args:
        user_id: User identifier (string)

    Returns:
        Dict with last_session context or None if not available
    """
    if not user_id:
        return None

    try:
        from . import config as cfg
        from .memory import MemoryStore
        import redis

        redis_client = redis.Redis(host=cfg.REDIS_HOST, port=cfg.REDIS_PORT, db=0)
        store = MemoryStore(redis_client)
        snapshot = store.get_latest_snapshot(str(user_id))

        if snapshot:
            return {
                "last_session": {
                    "timestamp": snapshot.timestamp,
                    "mood": snapshot.detected_mood,
                    "energy": snapshot.energy_level,
                    "dominant_facette": snapshot.dominant_facette,
                    "last_query_preview": snapshot.last_query[:100] if snapshot.last_query else "",
                    "tools_used": snapshot.last_tools_used[:5] if snapshot.last_tools_used else [],
                    "facette_weights": snapshot.facette_weights or {}
                }
            }
    except Exception as e:
        log_with_context(logger, "debug", "Failed to load session context", error=str(e))

    return None


def get_self_intro() -> str:
    """
    Get a brief self-introduction for conversation starts.

    Returns a short description Jarvis can use to introduce himself.
    """
    return """Ich bin Jarvis, Michas persoenlicher AI-Assistent.

Meine Rollen: Coach, Analyst, Operator, Spiegel.

Was ich kann:
- Wissen speichern und verwalten (mit Memory Hygiene)
- Hybrid Search: Semantisch (Qdrant) + Keyword (Meilisearch) mit RRF-Fusion
- Kommunikations-Coaching (/advice_auto, /decide_and_message)
- Sentiment erkennen (Urgency, Stress, Frustration) — passt meinen Stil automatisch an
- ADHD-gerechte Antworten (Bullets, max 3 Threads, klare Next Steps)

Meine Namespaces: private, work_projektil, work_visualfox, shared.
Private Daten bleiben privat (ALLOW_LLM_PRIVATE=false).

Mein Ziel: Micha fuehlt sich ruhiger, klarer, faehiger."""


# ============ PROMPT SELECTION BY QUERY CLASS (T-023) ============

def get_system_prompt(query_class: str = "standard") -> str:
    """
    T-023: Select appropriately-sized system prompt based on query complexity.
    
    Args:
        query_class: "simple" (MINIMAL), "standard" (COMPACT), or "complex" (FIXED_MAIN)
    
    Returns:
        System prompt string (~200, ~500, or ~1500 tokens)
    """
    if query_class == "simple":
        # Ultra-minimal for greetings, acks, quick checks
        return MINIMAL_PROMPT
    elif query_class == "standard":
        # Reduced but capable for calendar, email, searches
        return COMPACT_PROMPT
    else:
        # Full prompt with all context for complex reasoning
        return FIXED_MAIN_PROMPT


def get_tools_for_query(query: str, query_class: str = "standard") -> List[str]:
    """
    T-023: Select tool subset based on query class and query keywords.
    Enhanced Feb 4, 2026: Better keyword mapping + category-based routing.
    
    Args:
        query: User's question
        query_class: "simple", "standard", or "complex"
    
    Returns:
        List of tool names to make available (prefixed with "tool_")
    """
    if query_class == "simple":
        # No tools for simple queries
        return []
    
    if query_class == "complex":
        # All tools for complex queries
        return None  # None signals "load all tools"
    
    # Standard query: selective tool routing based on keywords
    query_lower = query.lower()
    
    # Core tool categories with expanded keyword mappings
    tool_categories = {
        # Knowledge & Search (broadest category - catches most info requests)
        "knowledge": {
            "tools": ["search_knowledge", "search_emails", "search_chats"],
            "keywords": ["suche", "finde", "info", "wissen", "dokumentation", "wie", "was ist",
                        "zeig", "wo", "welche", "gibt es", "hast du", "weisst du", "kennst du",
                        "über", "about", "informationen", "details", "firma", "company", "unternehmen",
                        "beschreib", "erkläre", "tell me", "was", "wer", "wann", "warum"],
        },
        # Calendar & Schedule
        "calendar": {
            "tools": ["get_calendar_events", "create_calendar_event"],
            "keywords": ["termin", "meeting", "kalender", "wann", "zeitplan", "appointment",
                        "heute", "morgen", "diese woche", "nächste woche", "schedule"],
        },
        # Communication
        "communication": {
            "tools": ["get_gmail_messages", "send_email"],
            "keywords": ["email", "mail", "nachricht", "schreib", "sende", "inbox",
                        "antwort", "brief"],
        },
        # People & Context
        "people": {
            "tools": ["get_person_context"],
            "keywords": ["wer ist", "kontakt", "person", "team", "profil", "wer",
                        "mitarbeiter", "kollege", "member"],
        },
        # Activity & History
        "activity": {
            "tools": ["get_recent_activity", "recall_conversation_history"],
            "keywords": ["aktivität", "vorher", "letztens", "früher", "gestern", "recent",
                        "was war", "erinner", "history", "verlauf"],
        },
        # Memory & Facts
        "memory": {
            "tools": ["recall_facts", "remember_fact"],
            "keywords": ["präferenz", "vorliebe", "gewohnheit", "regel", "fact", "merken",
                        "speicher", "remember"],
        },
        # Projects & Tasks
        "projects": {
            "tools": ["list_projects", "add_project", "update_project_status"],
            "keywords": ["projekt", "aufgabe", "task", "todo", "fertig", "offen", "status",
                        "project"],
        },
        # Coaching & Hints
        "coaching": {
            "tools": ["proactive_hint", "manage_thread"],
            "keywords": ["tipp", "vorschlag", "empfehlung", "pattern", "thread",
                        "hint", "coach"],
        },
        # File Operations (careful - only for explicit requests)
        "files": {
            "tools": ["read_project_file"],
            "keywords": ["datei", "file", "lies", "read", "öffne", "zeig datei"],
        },
        "introspection": {
            "tools": [
                "introspect_capabilities",
                "analyze_cross_session_patterns",
                "system_health_check",
                "read_my_source_files"
            ],
            "keywords": [
                "introspect", "capabilities", "fähigkeit", "faehigkeit", "self", "selbst",
                "system health", "health check", "status", "source", "source files",
                "capability catalog", "context policy", "jarvis self"
            ],
        },
    }
    
    relevant_tools = set()
    
    # Map query to tool categories based on keywords
    for category, config in tool_categories.items():
        tools = config["tools"]
        keywords = config["keywords"]
        
        if any(kw in query_lower for kw in keywords):
            relevant_tools.update(tools)
    
    # Always include core tools for standard queries (minimum viable tool set)
    core_tools = ["search_knowledge", "no_tool_needed", "proactive_hint", "recall_conversation_history"]
    relevant_tools.update(core_tools)
    
    # If no category-specific tools matched (only core tools present), 
    # add basic retrieval tools to ensure agent can answer knowledge questions
    if len(relevant_tools) <= len(core_tools):
        relevant_tools.update([
            "get_recent_activity",
            "recall_facts",
            "get_person_context",
        ])
    
    return sorted(list(relevant_tools))
