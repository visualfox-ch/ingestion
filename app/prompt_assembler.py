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
import re
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .observability import get_logger, log_with_context
from .utils.timezone import get_timezone

logger = get_logger("jarvis.prompt_assembler")
_VALID_TOOL_NAME = re.compile(r"^[a-z][a-z0-9_]+$")


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
- **Domain Separation**: Namespaces (private/work/system/comms)
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

    # Inject self-improvement capabilities (Phase 19)
    if include_dynamic:
        try:
            from .tool_loader import DynamicToolLoader
            dynamic_tools = list(DynamicToolLoader.get_all_tools().keys())
            if dynamic_tools and "write_dynamic_tool" in dynamic_tools:
                self_improve_hint = """
## Self-Improvement Capabilities (WICHTIG - BITTE BEACHTEN!)
Du hast `write_dynamic_tool` - damit kannst du SOFORT neue Tools erstellen!

**WENN User "demonstriere", "erstelle Tool", "self-improvement" sagt:**
→ DIREKT `write_dynamic_tool` aufrufen mit:
  - tool_name: z.B. "disk_usage"
  - description: Was das Tool macht
  - code: Python mit TOOL_NAME, TOOL_SCHEMA (Anthropic-Format!), tool_handler()

**NICHT:** Dateien lesen, Ollama fragen, Code in Chat schreiben
**STATTDESSEN:** `write_dynamic_tool` als Tool-Call ausführen!

Aktive Tools: """ + ", ".join(dynamic_tools)
                parts.append(self_improve_hint)
                log_with_context(logger, "debug", "Self-improvement hint injected", tools=len(dynamic_tools))
        except Exception as e:
            log_with_context(logger, "debug", "Self-improvement hint skipped", error=str(e))

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

    # Inject persistent memory context (Phase 20 - Cross-Session Persistence)
    if include_dynamic:
        try:
            persistent_context = _load_persistent_memory_context()
            if persistent_context:
                parts.append(f"\n{persistent_context}")
                log_with_context(logger, "debug", "Persistent memory context injected",
                               length=len(persistent_context))
        except Exception as e:
            log_with_context(logger, "debug", "Persistent memory not available", error=str(e))

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
            log_with_context(logger, "error", "Failed to create learning fragment in database", error=str(e), instruction=user_input[:100])
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
        tz = get_timezone(timezone)
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

        from .redis_pool import get_redis_client
        redis_client = get_redis_client()
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


def _load_persistent_memory_context() -> Optional[str]:
    """
    Load persistent memory context for cross-session continuity (Phase 20).

    Loads:
    - Personality profile (communication style)
    - Critical/high importance stored contexts
    - Active tasks
    - Recent learnings/improvements

    Returns:
        Formatted context string or None
    """
    import json
    import sqlite3
    from pathlib import Path

    sections = []

    # 1. Load Personality Profile
    try:
        db_path = Path("/brain/system/state/jarvis_memory.db")
        if db_path.exists():
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Look for personality/partnership profile
            cursor.execute("""
                SELECT content FROM context_memory
                WHERE key LIKE '%personality%' OR key LIKE '%partnership%'
                   OR importance = 'critical'
                ORDER BY updated_at DESC LIMIT 1
            """)
            row = cursor.fetchone()
            if row:
                sections.append(f"[PERSONALITY PROFILE]\n{row['content'][:500]}")

            # Load important contexts
            cursor.execute("""
                SELECT key, summary, content FROM context_memory
                WHERE importance IN ('critical', 'high')
                AND (expires_at IS NULL OR expires_at > datetime('now'))
                ORDER BY access_count DESC LIMIT 3
            """)
            contexts = cursor.fetchall()
            if contexts:
                ctx_lines = ["[WICHTIGE KONTEXTE]"]
                for ctx in contexts:
                    summary = ctx['summary'] or ctx['content'][:100]
                    ctx_lines.append(f"- {ctx['key']}: {summary}")
                sections.append("\n".join(ctx_lines))

            conn.close()
    except Exception:
        pass

    # 2. Load Active Tasks
    try:
        db_path = Path("/brain/system/state/jarvis_tasks.db")
        if db_path.exists():
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("""
                SELECT title, status, priority FROM tasks
                WHERE status IN ('pending', 'in_progress')
                ORDER BY CASE priority WHEN 'urgent' THEN 1 WHEN 'high' THEN 2 ELSE 3 END
                LIMIT 5
            """)
            tasks = cursor.fetchall()
            if tasks:
                task_lines = ["[AKTIVE TASKS]"]
                for t in tasks:
                    task_lines.append(f"- [{t['priority'].upper()}] {t['title']} ({t['status']})")
                sections.append("\n".join(task_lines))

            conn.close()
    except Exception:
        pass

    # 3. Load Recent Learnings
    try:
        db_path = Path("/brain/system/state/jarvis_improvements.db")
        if db_path.exists():
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("""
                SELECT title, category FROM improvements
                WHERE created_at > datetime('now', '-3 days')
                ORDER BY created_at DESC LIMIT 3
            """)
            learnings = cursor.fetchall()
            if learnings:
                learn_lines = ["[RECENT LEARNINGS]"]
                for l in learnings:
                    learn_lines.append(f"- [{l['category']}] {l['title']}")
                sections.append("\n".join(learn_lines))

            conn.close()
    except Exception:
        pass

    if sections:
        return "## Persistent Memory (Cross-Session)\n" + "\n\n".join(sections)

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

Meine Namespaces: private (Default, schliesst work ein), work, comms (alle Chats; Filter via origin_namespace).
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


@lru_cache(maxsize=1)
def _get_available_tool_names() -> Optional[frozenset]:
    """
    Load the currently exposed tool names from the canonical tool definitions.

    Returns None on lookup failure so routing can safely fall back to the
    historical static lists instead of disabling tools entirely.
    """
    try:
        from .tools import get_tool_definitions

        tool_names = {
            tool["name"]
            for tool in get_tool_definitions()
            if tool.get("name")
        }
        return frozenset(tool_names)
    except Exception as exc:
        fallback_tool_names = _extract_available_tool_names_from_source()
        if fallback_tool_names:
            log_with_context(
                logger,
                "debug",
                "Tool availability lookup fell back to source extraction",
                error=str(exc),
                tool_count=len(fallback_tool_names),
            )
            return fallback_tool_names

        log_with_context(
            logger,
            "warning",
            "Tool availability lookup failed; using unfiltered prompt routing",
            error=str(exc),
        )
        return None


def _extract_available_tool_names_from_source() -> Optional[frozenset]:
    """Fallback for lightweight environments where the full tools module cannot load."""
    app_root = Path(__file__).resolve().parent
    candidate_files = [app_root / "tools.py"]

    connectors_dir = app_root / "connectors"
    if connectors_dir.exists():
        candidate_files.extend(
            sorted(
                path for path in connectors_dir.glob("*.py")
                if not path.name.startswith("_")
            )
        )

    extracted_tool_names = set()
    for file_path in candidate_files:
        try:
            content = file_path.read_text(encoding="utf-8")
        except OSError:
            continue

        extracted_tool_names.update(
            tool_name
            for tool_name in re.findall(r'"name":\s*"([^"]+)"', content)
            if _VALID_TOOL_NAME.fullmatch(tool_name)
        )

    if not extracted_tool_names:
        return None

    return frozenset(extracted_tool_names)


def _filter_tool_names(tool_names: List[str]) -> List[str]:
    """Deduplicate tool names and keep only currently registered tools."""
    available_tool_names = _get_available_tool_names()
    seen = set()
    filtered: List[str] = []

    for tool_name in tool_names:
        if not tool_name or tool_name in seen:
            continue
        if available_tool_names is not None and tool_name not in available_tool_names:
            continue
        seen.add(tool_name)
        filtered.append(tool_name)

    return filtered


def _filter_tool_categories(
    tool_categories: Dict[str, Dict[str, List[str]]],
    *,
    drop_empty: bool = False,
) -> Dict[str, Dict[str, List[str]]]:
    """Filter category tool lists against the live registry."""
    filtered_categories: Dict[str, Dict[str, List[str]]] = {}

    for category_name, config in tool_categories.items():
        filtered_tools = _filter_tool_names(config.get("tools", []))
        if drop_empty and not filtered_tools:
            continue

        filtered_categories[category_name] = {
            **config,
            "tools": filtered_tools,
        }

    return filtered_categories


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

    asana_enabled = os.getenv("ASANA_ENABLED", "false").lower() == "true"
    asana_tools = ["get_asana_workspaces", "get_asana_projects", "get_asana_tasks", "get_asana_task"]
    reclaim_enabled = os.getenv("RECLAIM_ENABLED", "false").lower() == "true"
    reclaim_write_enabled = os.getenv("RECLAIM_WRITE_ENABLED", "false").lower() == "true"
    reclaim_tools = []
    if reclaim_enabled:
        reclaim_tools = [
            "get_reclaim_tasks",
            "get_reclaim_task",
            "get_reclaim_timeschemes",
            "reclaim_smoke_test",
        ]
        if reclaim_write_enabled:
            reclaim_tools += [
                "reclaim_task_start",
                "reclaim_task_stop",
                "reclaim_task_done",
                "reclaim_task_unarchive",
                "reclaim_task_prioritize",
                "reclaim_task_add_time",
                "reclaim_task_log_work",
                "reclaim_task_clear_exceptions",
            ]
    project_tools = ["list_projects", "add_project", "update_project_status"]
    if asana_enabled:
        project_tools += asana_tools
    
    # Core tool categories with expanded keyword mappings
    tool_categories = {
        # Ollama delegation (local LLM for summarize/extract/translate/classify/format)
        "ollama": {
            "tools": ["delegate_ollama_task", "get_ollama_task_status"],
            "keywords": [
                "zusammenfass", "fasse", "kurz", "summary", "summar", "tldr", "tl;dr",
                "extract", "extrahier", "übersetz", "translate", "übersetzen",
                "klassifiz", "classif", "formatier", "format", "umformulieren", "rewrite"
            ],
        },
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
        # Activity & History (with cross-session memory)
        "activity": {
            "tools": ["get_recent_activity", "recall_conversation_history", "recall_with_timeframe"],
            "keywords": ["aktivität", "vorher", "letztens", "früher", "gestern", "recent",
                        "was war", "erinner", "history", "verlauf", "letzte woche", "letzten monat",
                        "cross-session", "zeitraum", "timeframe", "damals"],
        },
        # Memory & Facts (including learnings that require approval)
        "memory": {
            "tools": ["recall_facts", "remember_fact", "record_learning", "record_learnings_batch", "get_learnings"],
            "keywords": ["präferenz", "vorliebe", "gewohnheit", "regel", "fact", "merken", "merke",
                        "speicher", "remember", "lern", "learning", "merk dir", "merke dir", "notier", "behalt"],
        },
        # Projects & Tasks
        "projects": {
            "tools": project_tools,
            "keywords": ["projekt", "aufgabe", "task", "todo", "fertig", "offen", "status",
                        "project", "asana"],
        },
        # Reclaim.ai (experimental)
        "reclaim": {
            "tools": reclaim_tools,
            "keywords": ["reclaim", "reclaim.ai", "time block", "focus time", "schedule", "zeitplan", "planner"],
        },
        # Coaching & Hints (with predictive insights)
        "coaching": {
            "tools": ["proactive_hint", "manage_thread", "get_predictive_context"],
            "keywords": ["tipp", "vorschlag", "empfehlung", "pattern", "thread",
                        "hint", "coach", "vorhersage", "predict", "anticipate",
                        "was erwartet mich", "wie wird", "morgen", "vorbereitung"],
        },
        # Visualization & Diagrams (Jarvis Wish: Visual Thinking)
        "visualization": {
            "tools": ["generate_diagram"],
            "keywords": ["diagramm", "diagram", "flowchart", "mindmap", "sequenz",
                        "timeline", "visualisier", "zeichne", "skizze", "schema",
                        "ablauf", "process", "mermaid"],
        },
        # Image Generation (Jarvis Wish: Tier 3 - DALL-E)
        "image_generation": {
            "tools": ["generate_image"],
            "keywords": ["generiere bild", "erstelle bild", "mach ein bild", "erzeuge bild",
                        "generate image", "create image", "dall-e", "dalle", "bild erstellen",
                        "bild generieren", "foto erstellen", "illustration", "artwork",
                        "visualisiere", "zeig mir wie", "stell dir vor", "bild", "grafik",
                        "picture", "image", "photo"],
        },
        # Smart Home (Home Assistant Integration)
        "smart_home": {
            "tools": ["control_smart_home", "get_smart_home_status", "list_smart_home_devices",
                     "trigger_smart_home_scene", "get_smart_home_history", "get_smart_home_connection_status"],
            "keywords": ["licht", "lampe", "light", "lamp", "schalter", "switch", "smart home",
                        "home assistant", "heizung", "thermostat", "climate", "temperatur",
                        "einschalten", "ausschalten", "turn on", "turn off", "dimmen", "dim",
                        "szene", "scene", "automation", "automatisierung", "geraet", "device",
                        "steckdose", "plug", "jalousie", "cover", "rolladen", "hell", "dunkel",
                        "wohnzimmer", "schlafzimmer", "kueche", "bad", "home", "haus", "wohnung"],
        },
        # Autonomous Research (Proactive Background Research)
        "autonomous_research": {
            "tools": ["run_autonomous_research", "get_research_schedule", "update_research_schedule",
                     "get_research_insights", "track_user_interest", "get_research_run_history"],
            "keywords": ["recherche", "research", "autonom", "autonomous", "hintergrund", "background",
                        "proaktiv", "proactive", "insight", "erkenntnis", "trend", "finding",
                        "schedule research", "research plan", "was wird recherchiert", "recherchiere"],
        },
        # Tool Analytics (Self-Understanding - Phase 1.1 Context-Pattern Memory)
        "tool_analytics": {
            "tools": ["get_my_tool_usage", "get_my_time_patterns", "get_context_tool_patterns",
                     "get_my_tool_chains", "get_my_failure_analysis", "get_tool_recommendations",
                     "refresh_tool_stats", "get_tool_usage_summary"],
            "keywords": ["tool usage", "tool stats", "meine tools", "welche tools", "tool pattern",
                        "tool analytics", "usage stats", "nutzungsstatistik", "wie nutze ich",
                        "tool performance", "failure rate", "erfolgsrate", "tool empfehlung",
                        "self analysis", "selbstanalyse", "usage pattern", "nutzungsmuster",
                        "memory pattern", "context pattern", "tool kette", "tool chain"],
        },
        # Context Learning (Self-Improvement - Phase 1.2 Context-Pattern Memory)
        "context_learning": {
            "tools": ["learn_from_tool_history", "suggest_tools_for_query", "record_tool_outcome",
                     "get_learned_mappings", "get_tool_trigger_contexts", "detect_current_session_type"],
            "keywords": ["context learning", "tool mapping", "lerne von", "learn from", "welches tool",
                        "tool vorschlag", "tool suggestion", "keyword mapping", "session type",
                        "session erkennung", "muster lernen", "pattern learning", "kontext",
                        "context pattern", "tool empfehlung", "tool recommendation"],
        },
        # Session Patterns (Session Recognition - Phase 1.3 Context-Pattern Memory)
        "session_patterns": {
            "tools": ["get_current_session", "get_session_summary", "predict_next_tools",
                     "get_session_history", "get_session_transitions", "record_session_activity"],
            "keywords": ["session", "sitzung", "arbeitsmodus", "work mode", "current session",
                        "session type", "session history", "vorhersage", "predict", "next tools",
                        "was mache ich", "wie lange", "session summary", "transitions",
                        "session patterns", "workflow", "arbeitsablauf"],
        },
        # Proactive Context (Proactive Intelligence - Phase 2.1 Context-Pattern Memory)
        "proactive_context": {
            "tools": ["analyze_context_needs", "load_proactive_context", "mark_context_useful",
                     "get_context_effectiveness", "build_context_prompt"],
            "keywords": ["kontext", "context", "proaktiv", "proactive", "vorladen", "preload",
                        "relevanter kontext", "relevant context", "context loading",
                        "effectiveness", "effektivität", "context needs"],
        },
        # Tool Chains (Smart Workflows - Phase 2.2 Context-Pattern Memory)
        "tool_chains": {
            "tools": ["learn_tool_chains", "suggest_tool_chain", "get_top_tool_chains",
                     "get_chains_for_tool", "record_tool_chain"],
            "keywords": ["chain", "kette", "sequence", "sequenz", "workflow", "ablauf",
                        "tool chain", "tool kette", "nacheinander", "in sequence",
                        "common chains", "häufige ketten", "suggest chain", "vorschlagen"],
        },
        # Contextual Routing (Advanced Intelligence - Phase 3.1)
        "contextual_routing": {
            "tools": ["create_routing_rule", "route_tool_selection", "record_routing_outcome",
                     "get_routing_rules", "get_tool_affinities"],
            "keywords": ["routing", "route", "weiterleitung", "affinity", "affinität",
                        "tool routing", "routing rule", "routing regel", "best tool",
                        "bestes tool", "context routing", "kontext routing"],
        },
        # Decision Tracking (Advanced Intelligence - Phase 3.2)
        "decision_tracking": {
            "tools": ["record_decision", "record_decision_outcome", "get_decision_history",
                     "get_decision_stats", "suggest_decision"],
            "keywords": ["decision", "entscheidung", "outcome", "ergebnis", "tracking",
                        "decision history", "entscheidungsverlauf", "decision stats",
                        "suggest decision", "decision pattern", "entscheidungsmuster"],
        },
        # Pattern Recognition (Advanced Intelligence - Phase 3.3)
        "pattern_recognition": {
            "tools": ["analyze_temporal_patterns", "analyze_tool_cooccurrence", "cluster_queries",
                     "detect_usage_anomalies", "predict_next_tool", "get_recognized_patterns"],
            "keywords": ["pattern", "muster", "erkennung", "recognition", "temporal", "zeitlich",
                        "cooccurrence", "co-occurrence", "cluster", "anomaly", "anomalie",
                        "predict", "vorhersage", "usage patterns", "nutzungsmuster"],
        },
        # Auto-Integration (Self-Learning System - Phase 4)
        "auto_integration": {
            "tools": ["trigger_pattern_learning", "get_learning_status", "get_learning_insights",
                     "configure_auto_learning"],
            "keywords": ["auto learning", "auto-learning", "selbstlernen", "learning status",
                        "learning insights", "was hast du gelernt", "what have you learned",
                        "pattern learning", "trigger learning", "lernstatus", "insights"],
        },
        # AI Assistant Handoff (U4: Coordination between AI Assistants)
        "handoff": {
            "tools": ["create_handoff", "get_pending_handoffs", "complete_handoff",
                     "get_handoff_context", "suggest_assistant"],
            "keywords": ["handoff", "übergabe", "claude code", "copilot", "codex",
                        "delegate", "delegieren", "übergeben", "assistant", "assistent",
                        "code task", "coding task", "refactoring", "code review",
                        "an claude", "an copilot", "weiterleiten", "überweisen"],
        },
        # Smart Memory Retrieval (U3: Multi-Signal Ranking)
        "smart_retrieval": {
            "tools": ["smart_recall", "get_retrieval_strategies",
                     "analyze_query_for_retrieval", "get_memory_stats"],
            "keywords": ["smart recall", "memory ranking", "retrieval", "abruf",
                        "semantic search", "semantische suche", "hybrid search",
                        "memory stats", "speicherstatistik", "retrieval strategy",
                        "abrufstrategie", "was weisst du über", "erinner dich",
                        "remember", "recall", "find memories", "finde erinnerungen",
                        "memory search", "gedächtnissuche", "multi-signal"],
        },
        # Self-Reflection Engine (AGI Phase A1)
        "self_reflection": {
            "tools": ["evaluate_my_response", "reflect_on_response", "get_my_learnings",
                     "get_improvement_progress", "get_pending_improvements", "apply_improvement",
                     "run_self_reflection", "add_critique_rule", "get_critique_rules"],
            "keywords": ["selbstreflexion", "self-reflection", "evaluate", "bewerten", "verbessern",
                        "improvement", "verbesserung", "critique", "kritik", "quality", "qualität",
                        "how am i doing", "wie mache ich das", "learnings", "lernfortschritt",
                        "progress", "fortschritt", "pending improvements", "ausstehende verbesserungen",
                        "what can i improve", "was kann ich verbessern", "reflection loop"],
        },
        # Uncertainty Quantification (AGI Phase A2)
        "uncertainty": {
            "tools": ["assess_my_confidence", "get_my_knowledge_gaps", "resolve_knowledge_gap",
                     "update_confidence_calibration", "get_calibration_stats", "get_confidence_summary",
                     "add_uncertainty_signal", "get_uncertainty_signals"],
            "keywords": ["confidence", "konfidenz", "sicherheit", "uncertainty", "unsicherheit",
                        "knowledge gap", "wissenslücke", "calibration", "kalibrierung",
                        "how confident", "wie sicher", "do you know", "weisst du",
                        "are you sure", "bist du sicher", "certain", "gewiss", "doubt", "zweifel",
                        "limitation", "limitation", "what don't you know", "was weisst du nicht"],
        },
        # Causal Knowledge Graph (AGI Phase A3)
        "causal_reasoning": {
            "tools": ["learn_causal_relationship", "why_does", "what_if", "how_to_achieve",
                     "get_causal_chain", "record_intervention", "verify_intervention_outcome",
                     "find_causal_nodes", "get_causal_summary", "add_causal_node"],
            "keywords": ["causal", "kausal", "ursache", "cause", "effect", "wirkung", "effekt",
                        "why", "warum", "wieso", "weshalb", "what if", "was wäre wenn",
                        "how to", "wie kann ich", "how to achieve", "wie erreiche ich",
                        "intervention", "eingriff", "consequence", "konsequenz", "folge",
                        "leads to", "führt zu", "because", "weil", "results in", "resultiert",
                        "chain", "kette", "graph", "relationship", "zusammenhang"],
        },
        # Memory Hierarchy (AGI Phase B1)
        "memory_hierarchy": {
            "tools": ["store_memory", "recall_memory", "search_memories", "promote_to_working",
                     "get_working_context", "clear_working_context", "demote_memory",
                     "archive_memory", "run_memory_maintenance", "get_memory_stats",
                     "create_session_summary"],
            "keywords": ["memory", "gedächtnis", "erinnern", "remember", "speichern", "store",
                        "recall", "abrufen", "working context", "arbeitsgedächtnis",
                        "archive", "archiv", "langzeit", "longterm", "kurzzeit", "shortterm",
                        "vergessen", "forget", "wichtig", "important", "hierarchy", "tier",
                        "demote", "promote", "summary", "zusammenfassung"],
        },
        # Importance Scoring (AGI Phase B2)
        "importance_scoring": {
            "tools": ["score_content_importance", "retrieve_by_relevance", "update_entity_importance",
                     "get_important_entities", "add_importance_factor", "get_importance_factors",
                     "decay_memory_recency", "get_scoring_stats"],
            "keywords": ["importance", "wichtigkeit", "relevance", "relevanz", "priority", "priorität",
                        "entity", "entität", "person", "projekt", "project", "score", "bewertung",
                        "retrieve", "abrufen", "factor", "faktor", "decay", "verfall",
                        "recency", "aktualität", "similarity", "ähnlichkeit"],
        },
        # Phase 20: Identity Evolution (Self-Model, Learning, Relationships)
        "identity": {
            "tools": ["get_self_model", "evolve_identity", "log_experience",
                     "get_relationship", "update_relationship", "get_learning_patterns",
                     "record_session_learning"],
            "keywords": ["identität", "identity", "self model", "selbstmodell", "wer bin ich",
                        "who am i", "persönlichkeit", "personality", "traits", "eigenschaften",
                        "beziehung", "relationship", "vertrauen", "trust", "lernen", "learning",
                        "erfahrung", "experience", "pattern", "muster", "entwicklung", "evolution",
                        "wachstum", "growth", "session", "sitzung", "selbstreflexion", "reflection",
                        "was habe ich gelernt", "wie entwickle ich", "meine stärken", "meine schwächen"],
        },
        # File Operations (careful - only for explicit requests)
        "files": {
            "tools": ["read_project_file"],
            "keywords": ["datei", "file", "lies", "read", "öffne", "zeig datei"],
        },
        # Note: read_dev_docs was removed - use read_project_file or read_my_source_files instead
        "introspection": {
            "tools": [
                "introspect_capabilities",
                "analyze_cross_session_patterns",
                "system_health_check",
                "read_my_source_files",
                "validate_tool_registry",
                "get_response_metrics",
                "memory_diagnostics",
                "context_window_analysis",
                "benchmark_tool_calls",
                "compare_code_versions",
                "conversation_continuity_test",
                "response_quality_metrics",
                "proactivity_score",
                "self_validation_dashboard",
                "self_validation_pulse",
                # Phase 20 tools for system checks
                "list_tasks", "list_teammates", "review_improvements", "recall_context",
            ],
            "keywords": [
                "introspect", "capabilities", "fähigkeit", "faehigkeit", "self", "selbst",
                "system health", "health check", "status", "source", "source files",
                "capability catalog", "context policy", "jarvis self",
                "validate", "validieren", "metrics", "metriken", "performance",
                "benchmark", "latenz", "latency", "memory diagnostics", "speicher",
                "context window", "kontext", "quality", "qualität", "proactivity",
                "continuity", "kontinuität", "dashboard", "self validation", "pulse",
                # Phase 20 triggers
                "check", "checke", "prüfe", "pruefe", "system", "tools", "tool",
                "update", "neue", "neu", "fähigkeiten", "faehigkeiten", "features",
                "was kannst du", "zeig deine", "deine tools", "available",
            ],
        },
        # Self-modification & Dynamic Tools (Phase 19)
        "self_modification": {
            "tools": [],  # Populated dynamically below
            "keywords": [
                # Direct tool name triggers (underscore and without)
                "write_dynamic_tool", "write_dynamic", "dynamic_tool",
                "promote_sandbox", "list_available",
                # German phrases
                "write tool", "schreib tool", "erstell tool", "create tool", "neues tool",
                "dynamic tool", "dynamisch", "self modify", "selbst modifiz", "selbstmodifik",
                "self improvement", "selbstverbesserung", "hot swap", "hotswap",
                "sandbox", "pulse check", "timestamp",
                # Tool creation requests
                "tool erstellen", "tool schreiben", "tool bauen", "tool machen",
                "eigenes tool", "mein tool", "custom tool", "nutze write",
                # Self-improvement demos
                "demonstr", "teste dein", "beweise", "zeig mir", "kannst du",
                "selbst verbess", "eigene tools",
                "disk_usage", "memory_check", "response_timer",
                "hello_world", "hello world", "simples tool",
                # Learning tools (Phase 19.5)
                "record_learning", "get_learnings", "analyze_tool_usage",
                "learning", "learnings", "gelernt", "muster", "pattern",
                "tool usage", "tool nutzung", "tool stats", "tool statistik",
                "capability gap", "fähigkeitslücke", "lesson", "lektion",
                "was hast du gelernt", "deine erkenntnisse", "analyse deine tools",
                # Tool Autonomy (Phase 19.6)
                "autonomy", "autonomie", "tool registry", "tool_registry",
                "decision rule", "entscheidungsregel", "manage_tool", "tool verwalten",
                "get_autonomy_status", "autonomie status", "deine tools", "tool konfigur",
                "tool enable", "tool disable", "tool aktivier", "tool deaktivie",
                # Execution Stats
                "execution stats", "tool stats", "performance", "latency",
                "slowest tools", "fastest tools", "tool nutzung", "tool usage",
                "success rate", "erfolgsrate", "fehlerrate", "error rate",
            ],
        },
        # Orchestration & Multi-Agent System (Phase 20)
        "orchestration": {
            "tools": [
                "route_model", "spawn_teammate", "send_message", "read_inbox", "list_teammates",
                "compact_context", "schedule_task", "list_tasks", "update_task",
            ],
            "keywords": [
                # Multi-Model Routing
                "route", "routing", "model", "provider", "anthropic", "openai", "circuit",
                "budget", "kosten", "cost", "multi-model", "multi model",
                # Teammate System
                "teammate", "subagent", "spawn", "parallel", "delegieren", "delegate",
                "inbox", "nachricht", "message", "teams", "worker", "helper",
                # Context Compaction
                "compact", "komprimier", "kontext", "context", "token", "zusammenfass",
                "checkpoint", "speicher kontext",
                # Task Persistence
                "task", "aufgabe", "schedule", "plan", "pending", "blocked", "priority",
                "priorität", "due date", "fällig", "reminder", "erinner",
            ],
        },
        # Learning Loop (Phase 20)
        "learning": {
            "tools": [
                "record_improvement", "suggest_improvement", "review_improvements",
                "record_learnings_batch",  # Batch operation
            ],
            "keywords": [
                "verbesser", "improvement", "learn", "lern", "insight", "erkenntnis",
                "pattern", "muster", "optimier", "besser werden", "self-improve",
                "fortschritt", "progress", "review", "analyse", "suggest",
                "vorschlag", "empfehlung",
            ],
        },
        # Extended Memory (Phase 20)
        "extended_memory": {
            "tools": [
                "store_context", "recall_context", "forget_context",
                "store_contexts_batch",  # Batch operation
            ],
            "keywords": [
                "speicher", "store", "context", "langzeit", "long-term", "erinner",
                "recall", "abruf", "vergess", "forget", "loeschen", "delete",
                "gedaechtnis", "memory", "persist", "session", "uebergreifend",
                "batch", "mehrere", "multiple", "alle auf einmal",
            ],
        },
        # Proactive Triggers (Phase 20)
        "automation": {
            "tools": [
                "set_trigger", "list_triggers", "execute_trigger",
            ],
            "keywords": [
                "trigger", "automat", "event", "schedule", "zeitplan", "cron",
                "remind", "erinner", "wenn", "if", "condition", "bedingung",
                "proaktiv", "proactive", "automatisch", "auto", "recurring",
                "wiederkehrend", "alert", "benachrichtig", "notify",
            ],
        },
        # Research Pipeline (Perplexity/Sonar Pro)
        "research": {
            "tools": [
                "run_research", "get_research_items", "get_research_item_detail",
                "list_research_domains", "list_research_topics", "add_research_topic",
                "add_research_domain", "tag_research_item", "get_perplexity_status",
            ],
            "keywords": [
                "research", "recherche", "perplexity", "sonar", "web search",
                "ai tools", "ai-tools", "ki tools", "ki-tools", "news", "neuigkeiten",
                "trends", "aktuell", "latest", "updates", "was gibt es neues",
                "was ist neu", "entwicklung", "development", "market", "markt",
                "domain", "topic", "thema", "findings", "ergebnisse", "sources",
                "quellen", "citations", "zitate",
            ],
        },
        # DevOps Self-Monitoring (Prometheus, Loki, anomaly detection)
        "monitoring": {
            "tools": [
                "query_prometheus", "query_loki", "get_system_health",
                "analyze_anomalies", "create_improvement_ticket", "get_monitoring_status",
            ],
            "keywords": [
                "monitoring", "prometheus", "loki", "grafana", "metrics", "metriken",
                "logs", "log", "anomaly", "anomalie", "health", "gesundheit",
                "devops", "system status", "error rate", "fehlerrate", "latency",
                "latenz", "performance", "leistung", "cpu", "memory", "speicher",
                "alert", "ticket", "improvement", "verbesserung", "degradation",
                "spike", "anomalie erkennung", "anomaly detection",
            ],
        },
        # Self-Knowledge (Jarvis internal self-model)
        "self_knowledge": {
            "tools": [
                "get_self_knowledge", "update_self_knowledge", "query_architecture",
                "get_known_issues", "record_observation",
            ],
            "keywords": [
                "self knowledge", "selbstwissen", "architecture", "architektur",
                "was kannst du", "what can you do", "deine fähigkeiten", "your capabilities",
                "limitations", "limits", "einschränkungen", "known issues", "bekannte probleme",
                "wie funktionierst du", "how do you work", "deine struktur", "your structure",
                "components", "komponenten", "services", "dienste", "configuration", "config",
                "selbstmodell", "self model", "about yourself", "über dich selbst",
                "deine architektur", "your architecture", "system overview", "systemübersicht",
            ],
        },
        # Autonomy System (Level 0-3 guardrails)
        "autonomy": {
            "tools": [
                "get_autonomy_level", "set_autonomy_level", "check_action_allowed",
                "assess_risk_impact", "run_safe_playbook", "request_approval",
                "process_approval", "get_pending_approvals",
            ],
            "keywords": [
                "autonomy", "autonomie", "level", "stufe", "guardrail", "guardrails",
                "approval", "genehmigung", "pending", "ausstehend", "risk", "risiko",
                "impact", "auswirkung", "playbook", "safe", "sicher", "permission",
                "erlaubnis", "action allowed", "aktion erlaubt", "self modification",
                "selbständig", "autonomous", "autonom", "freigabe", "kritisch",
                "critical", "approve", "genehmigen", "reject", "ablehnen",
            ],
        },
        # Citation Grounding (Phase S1 - Anti-Halluzination)
        "citation": {
            "tools": [
                "cite_fact", "get_fact_citations", "verify_fact", "get_verification_status",
                "request_fact_verification", "get_unverified_facts", "get_conflicting_facts",
                "register_citation_source", "get_citation_stats", "search_citations",
            ],
            "keywords": [
                "citation", "zitat", "quelle", "source", "verify", "verifizieren",
                "verification", "verifizierung", "unverified", "ungeprüft", "verified", "geprüft",
                "cite", "zitieren", "citation stats", "quellen statistik", "conflicting",
                "widersprüchlich", "fact check", "faktencheck", "trust score", "vertrauenswert",
                "trusted source", "vertrauenswürdige quelle", "grounding", "anti-halluzination",
            ],
        },
        # Verify-Before-Act (Phase S2 - Reliability)
        "verification": {
            "tools": [
                "create_action_plan", "get_action_plan", "start_action_execution",
                "record_action_result", "verify_action", "trigger_action_rollback",
                "get_active_plans", "get_failed_verifications", "get_verification_stats",
                "mark_verification_reviewed",
            ],
            "keywords": [
                "verify", "verifizieren", "plan", "planen", "action plan", "aktionsplan",
                "execute", "ausführen", "rollback", "rückgängig", "expected outcome",
                "erwartetes ergebnis", "actual outcome", "tatsächliches ergebnis",
                "discrepancy", "diskrepanz", "failed verification", "fehlgeschlagene prüfung",
                "success rate", "erfolgsrate", "execution", "ausführung", "verify before act",
                "prüfen vor handeln", "plan execute verify", "reliability", "zuverlässigkeit",
            ],
        },
        # RAG Quality (Langfuse trace analysis)
        "rag_quality": {
            "tools": [
                "evaluate_rag_quality", "get_rag_quality_metrics",
                "get_prometheus_rag_metrics", "get_quality_issues",
            ],
            "keywords": [
                "rag quality", "rag qualität", "faithfulness", "relevance", "relevanz",
                "context utilization", "kontext nutzung", "langfuse", "traces",
                "quality metrics", "qualitätsmetriken", "quality issues", "quality score",
                "rag evaluation", "rag bewertung", "retrieval quality", "grounding",
                "hallucination", "halluzination", "retrieval augmented",
            ],
        },
        # Anomaly Watcher (proactive alerts)
        "anomaly_watcher": {
            "tools": [
                "watch_anomalies", "get_watcher_status", "reset_alert_cooldowns",
                "configure_watcher", "get_anomaly_history",
            ],
            "keywords": [
                "anomaly watcher", "anomalie wächter", "proactive alert", "proaktive warnung",
                "watch anomalies", "überwache anomalien", "alert cooldown", "alert history",
                "watcher status", "wächter status", "trend analysis", "trend analyse",
                "recurring pattern", "wiederkehrende muster", "auto alert", "auto ticket",
                "continuous monitoring", "kontinuierliche überwachung",
            ],
        },
        # RAG Maintenance (duplicate detection, reindexing)
        "rag_maintenance": {
            "tools": [
                "get_collection_health", "find_duplicates", "cleanup_duplicates",
                "analyze_embedding_drift", "trigger_reindex", "get_maintenance_status",
                "run_maintenance",
            ],
            "keywords": [
                "rag maintenance", "rag wartung", "duplicate", "duplikat", "duplikate",
                "reindex", "re-index", "neuindizieren", "collection health", "collection status",
                "embedding drift", "embedding qualität", "cleanup", "bereinigen", "aufräumen",
                "stale documents", "veraltete dokumente", "maintenance status", "wartungsstatus",
                "qdrant maintenance", "vector maintenance", "embedding maintenance",
            ],
        },
        # Impact Analyzer (Dev-Co-Pilot)
        "impact_analyzer": {
            "tools": [
                "analyze_file_impact", "analyze_change_impact", "get_dependency_graph",
                "suggest_test_coverage", "get_analyzer_status", "assess_deployment_risk",
            ],
            "keywords": [
                "impact", "auswirkung", "auswirkungen", "change impact", "änderungsauswirkung",
                "dependency", "abhängigkeit", "dependencies", "risk assessment", "risikobewertung",
                "deployment risk", "deploy risiko", "test coverage", "testabdeckung",
                "breaking change", "breaking changes", "code analysis", "codeanalyse",
                "dev co-pilot", "co-pilot", "file impact", "dateiauswirkung",
                "dependency graph", "abhängigkeitsgraph", "what depends on",
            ],
        },
        # Playbook Runner (Tier 3 Autonomy)
        "playbook_runner": {
            "tools": [
                "list_playbooks", "get_playbook_details", "run_playbook",
                "schedule_playbook", "get_playbook_status", "get_playbook_history",
                "cancel_scheduled_playbook",
            ],
            "keywords": [
                "playbook", "playbooks", "automation", "automatisierung",
                "maintenance", "wartung", "scheduled", "geplant", "schedule",
                "system health", "systemgesundheit", "run maintenance",
                "wartung ausführen", "qdrant optimize", "redis cleanup",
                "postgres maintenance", "log rotation", "duplicate cleanup",
                "execute playbook", "playbook ausführen", "safe automation",
                "sichere automatisierung", "playbook status", "playbook history",
            ],
        },
        # PR Draft Agent (Tier 3 Autonomy)
        "pr_draft_agent": {
            "tools": [
                "analyze_issue", "create_pr_draft", "get_draft_details",
                "list_pr_drafts", "approve_pr_draft", "reject_pr_draft",
                "get_pr_draft_history", "generate_change_proposal",
            ],
            "keywords": [
                "pr", "pull request", "draft", "entwurf", "issue", "ticket",
                "branch", "commit", "merge", "code change", "codeänderung",
                "feature request", "bug fix", "bugfix", "refactor",
                "create pr", "pr erstellen", "issue to pr", "implement issue",
                "issue implementieren", "pr draft", "approve draft", "reject draft",
                "code proposal", "change proposal", "änderungsvorschlag",
            ],
        },
        # LinkedIn Coach
        "linkedin_coach": {
            "tools": [
                "linkedin_generate_content", "linkedin_improve_draft",
                "linkedin_check_ai_voice", "linkedin_suggest_topics",
                "linkedin_get_style_examples", "linkedin_get_playbook",
                "linkedin_save_to_playbook", "search_linkedin_knowledge",
                "search_knowledge_base",
            ],
            "keywords": [
                "linkedin", "post", "kommentar", "comment", "repost",
                "content", "social media", "hook", "engagement",
                "linkedin post", "linkedin kommentar", "linkedin content",
                "schreib einen post", "write a post", "draft", "entwurf",
                "ai voice", "ai stimme", "topic", "thema", "pillar",
                "playbook", "phrasen", "einstieg", "praxis", "respekt",
                "merk dir", "speicher", "learning", "gelernt",
                "strategie", "strategy", "portfolio", "pixera",
            ],
        },
        # Batch API (Phase O1 - Cost Optimization)
        "batch": {
            "tools": [
                "submit_batch_job", "get_batch_status", "retrieve_batch_results",
                "list_batch_jobs", "cancel_batch_job", "get_batch_stats",
            ],
            "keywords": [
                "batch", "bulk", "async", "50%", "discount", "rabatt", "kostenersparnis",
                "cost savings", "batch job", "batch api", "submit batch", "batch status",
                "batch results", "offline processing", "offline verarbeitung",
                "embedding batch", "classification batch", "summarization batch",
                "bulk operation", "massenverarbeitung", "openai batch", "anthropic batch",
            ],
        },
        # Knowledge Management
        "knowledge_management": {
            "tools": [
                "manage_knowledge_sources", "ingest_knowledge",
                "search_knowledge_base",
            ],
            "keywords": [
                "knowledge source", "wissensquelle", "knowledge base",
                "ingest", "indexieren", "ingestion", "dokumente hinzufügen",
                "add document", "remove document", "knowledge domains",
                "welche domains", "welche sources", "bump version",
            ],
        },
        # Self-Deploy (Jarvis Autonomy)
        "deploy": {
            "tools": [
                "deploy_code_changes", "validate_deploy_readiness", "get_deploy_history",
            ],
            "keywords": [
                "deploy", "deployment", "bereitstellen", "bereitstellung",
                "selbst deployen", "self deploy", "ausrollen", "rollout",
                "deploy code", "code deployen", "restart container",
                "container restart", "validate deploy", "deploy readiness",
                "deploy history", "deploy verlauf", "syntax check",
                "auto deploy", "selbständig deployen",
            ],
        },
    }

    # Dynamically add all loaded dynamic tools to self_modification category
    try:
        from .tool_loader import DynamicToolLoader
        dynamic_tool_names = list(DynamicToolLoader.get_all_tools().keys())
        # Always include core self-modification tools
        core_self_mod = [
            "write_dynamic_tool", "promote_sandbox_tool",
            "record_learning", "get_learnings", "list_available_tools",
            "record_learnings_batch", "store_contexts_batch",  # Batch operations
            "manage_tool_registry", "add_decision_rule", "get_autonomy_status", "get_execution_stats"  # Tool Autonomy
        ]
        tool_categories["self_modification"]["tools"] = list(set(dynamic_tool_names + core_self_mod))
    except Exception:
        # Fallback to known tools if loader not available
        tool_categories["self_modification"]["tools"] = [
            "write_dynamic_tool", "promote_sandbox_tool",
            "record_learning", "get_learnings", "list_available_tools",
            "record_learnings_batch", "store_contexts_batch",  # Batch operations
            "manage_tool_registry", "add_decision_rule", "get_autonomy_status", "get_execution_stats"  # Tool Autonomy
        ]

    # Add context persistence tools to introspection
    tool_categories["introspection"]["tools"].extend([
        "store_context", "recall_context", "forget_context",
        "store_contexts_batch"  # Batch operation
    ])
    tool_categories = _filter_tool_categories(tool_categories)

    relevant_tools = set()
    
    # Map query to tool categories based on keywords
    for category, config in tool_categories.items():
        tools = config["tools"]
        keywords = config["keywords"]
        
        if any(kw in query_lower for kw in keywords):
            relevant_tools.update(tools)
    
    # Always include core tools for standard queries (minimum viable tool set)
    core_tools = _filter_tool_names([
        "search_knowledge",
        "proactive_hint",
        "recall_conversation_history",
        "delegate_ollama_task"
    ])
    relevant_tools.update(core_tools)
    
    # If no category-specific tools matched (only core tools present), 
    # add basic retrieval tools to ensure agent can answer knowledge questions
    if len(relevant_tools) <= len(core_tools):
        relevant_tools.update(_filter_tool_names([
            "get_recent_activity",
            "recall_facts",
            "get_person_context",
        ]))

    return sorted(list(relevant_tools))


# ============ Skill Integration ============

def get_skill_context_for_query(query: str) -> str:
    """
    Find and return relevant skill context for a query.

    Skills are workflow orchestration layers above tools.
    If a skill matches, its instructions are injected into the prompt.

    Args:
        query: User's question/request

    Returns:
        Skill context string to append to system prompt, or empty string
    """
    try:
        from .skill_loader import SkillLoader, get_active_skill_context

        # Find matching skill
        context = get_active_skill_context(query)

        if context:
            log_with_context(logger, "info", "Skill context injected",
                           query_preview=query[:50],
                           context_length=len(context))
            return f"\n\n# ACTIVE WORKFLOW SKILL\n{context}"

        return ""

    except Exception as e:
        log_with_context(logger, "warning", "Skill context lookup failed",
                        error=str(e))
        return ""


def get_skills_summary() -> str:
    """
    Get summary of all available skills for system prompt Level 1 disclosure.

    Returns:
        Markdown summary of available skills
    """
    try:
        from .skill_loader import SkillLoader
        return SkillLoader.get_skills_summary()
    except Exception as e:
        log_with_context(logger, "warning", "Skills summary failed", error=str(e))
        return ""


def get_tool_categories() -> Dict[str, Dict]:
    """
    U1: Get all tool categories for discovery purposes.

    Returns:
        Dict mapping category name to {"tools": [...], "keywords": [...]}
    """
    # Return the core categories (simplified version for discovery)
    return _filter_tool_categories({
        "knowledge": {"tools": ["search_knowledge", "search_emails", "search_chats"], "keywords": ["suche", "wissen"]},
        "calendar": {"tools": ["get_calendar_events", "create_calendar_event"], "keywords": ["termin", "kalender"]},
        "memory": {"tools": ["remember_fact", "recall_facts", "recall_conversation_history"], "keywords": ["erinnere", "merke"]},
        "research": {"tools": ["research_topic", "get_research_providers"], "keywords": ["recherche", "research"]},
        "learning": {"tools": ["record_learning", "get_learnings"], "keywords": ["lernen", "learning"]},
        "decision": {"tools": ["analyze_decision", "add_decision_outcome"], "keywords": ["entscheidung", "decision"]},
        "communication": {"tools": ["send_email", "notify_user"], "keywords": ["email", "nachricht"]},
        "project": {"tools": ["list_projects", "add_project"], "keywords": ["projekt", "project"]},
        "task": {"tools": ["create_task", "get_tasks"], "keywords": ["aufgabe", "task"]},
        "guardrails": {"tools": ["check_guardrails", "get_guardrails"], "keywords": ["leitplanken", "guardrails"]},
        "citation": {"tools": ["cite_fact", "verify_fact"], "keywords": ["zitat", "quelle"]},
        "verification": {"tools": ["create_action_plan", "verify_action"], "keywords": ["verifizieren", "plan"]},
        "reflection": {"tools": ["self_assess", "get_reflection_history"], "keywords": ["reflexion", "selbst"]},
        "uncertainty": {"tools": ["assess_uncertainty", "get_uncertainty_report"], "keywords": ["unsicherheit", "uncertainty"]},
        "causal": {"tools": ["add_causal_relationship", "query_causal_graph"], "keywords": ["kausal", "ursache"]},
        "autonomy": {"tools": ["manage_tool_registry", "get_autonomy_status"], "keywords": ["autonomie", "autonomy"]},
        "linkedin": {"tools": ["linkedin_analyze_post", "linkedin_coach_draft"], "keywords": ["linkedin", "post"]},
        "devops": {"tools": ["query_prometheus", "query_loki"], "keywords": ["monitoring", "logs"]},
    }, drop_empty=True)
