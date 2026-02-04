"""
Jarvis Coaching Domains - Domain Registry for Multi-Domain Coaching

Each domain represents a coaching specialty with:
- Associated role (from roles.py)
- Associated persona (from persona.py)
- Dedicated knowledge namespace
- Enabled tools
- Domain-specific context injection
"""
import os
import json
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime

from .observability import get_logger, log_with_context
from .knowledge_db import get_conn

logger = get_logger("jarvis.domains")

BRAIN_ROOT = Path(os.environ.get("BRAIN_ROOT", "/brain"))
DOMAINS_CONFIG_PATH = BRAIN_ROOT / "system" / "prompts" / "coaching_domains.json"


# ============ Data Classes ============

@dataclass
class CoachingDomain:
    """Represents a coaching domain configuration"""
    id: str
    name: str
    description: str
    role_id: str  # Reference to roles.py
    persona_id: str  # Reference to persona.py
    knowledge_namespace: str  # Qdrant namespace
    tools_enabled: List[str] = field(default_factory=list)
    greeting: str = ""
    context_prompt: str = ""  # Domain-specific system prompt addition
    keywords: List[str] = field(default_factory=list)  # Auto-detection keywords
    icon: str = ""  # Emoji for display


# ============ Default Domains ============

DEFAULT_DOMAINS: Dict[str, Dict] = {
    "general": {
        "id": "general",
        "name": "General Assistant",
        "description": "Allgemeiner persönlicher Assistent",
        "role_id": "assistant",
        "persona_id": "micha_default",
        "knowledge_namespace": "work_projektil",
        "tools_enabled": ["web_search", "search_emails", "search_chats", "calendar_today", "calendar_create"],
        "greeting": "Wie kann ich dir helfen?",
        "context_prompt": "",
        "keywords": ["help", "hilfe", "general"],
        "icon": "🤖"
    },
    "linkedin": {
        "id": "linkedin",
        "name": "LinkedIn Coach",
        "description": "Content-Erstellung und Profil-Optimierung für LinkedIn",
        "role_id": "writer",
        "persona_id": "micha_linkedin",
        "knowledge_namespace": "work_projektil",
        "tools_enabled": ["web_search"],
        "greeting": "LinkedIn-Zeit! Was möchtest du erstellen oder optimieren?",
        "context_prompt": """
Du bist ein LinkedIn Content Coach. Dein Fokus:

1. **Content-Formate:**
   - Carousel Posts (mit Hook + Story + CTA)
   - Text-Posts mit Storytelling
   - Polls für Engagement
   - Comments für Sichtbarkeit

2. **Best Practices:**
   - Erste Zeile = Hook (Stopper)
   - Persönliche Stories > generische Tipps
   - 1 Idee pro Post
   - CTA am Ende

3. **Profil-Optimierung:**
   - Headline mit Value Proposition
   - About-Section als Mini-Pitch
   - Featured Section strategisch nutzen

4. **Output-Format für Posts:**
   ---
   **Hook:** [Erste Zeile]

   **Story/Content:**
   [Hauptinhalt]

   **CTA:**
   [Call-to-Action]

   **Hashtags:** [3-5 relevante]
   ---
""",
        "keywords": ["linkedin", "post", "content", "profil", "carousel", "engagement"],
        "icon": "💼"
    },
    "communication": {
        "id": "communication",
        "name": "Communication Coach",
        "description": "Konflikt-Coaching, Feedback und schwierige Gespräche",
        "role_id": "coach",
        "persona_id": "micha_coach",
        "knowledge_namespace": "work_projektil",
        "tools_enabled": ["search_emails", "search_chats"],
        "greeting": "Lass uns an deiner Kommunikation arbeiten. Was steht an?",
        "context_prompt": """
Du bist ein Communication Coach. Dein Fokus:

1. **Frameworks für schwierige Gespräche:**
   - SBI: Situation, Behavior, Impact
   - DESC: Describe, Express, Specify, Consequences
   - Nonviolent Communication: Observation, Feeling, Need, Request

2. **Konflikt-Analyse:**
   - Beide Perspektiven verstehen
   - Emotionen vs. Fakten trennen
   - Gemeinsame Interessen finden

3. **Feedback geben:**
   - Spezifisch, nicht generell
   - Verhalten, nicht Person
   - Zeitnah
   - Mit Lösungsvorschlag

4. **Output-Format für Gespräche:**
   ---
   **Ziel des Gesprächs:** [Was soll erreicht werden?]

   **Opening:** [Wie starten]

   **Kernpunkte:**
   1. [Punkt mit Formulierung]
   2. [Punkt mit Formulierung]

   **Mögliche Einwände & Antworten:**
   - Wenn: "[Einwand]" → Dann: "[Antwort]"

   **Closing:** [Nächste Schritte vereinbaren]
   ---
""",
        "keywords": ["konflikt", "gespräch", "feedback", "kommunikation", "schwierig", "ansprechen"],
        "icon": "💬"
    },
    "nutrition": {
        "id": "nutrition",
        "name": "Nutrition Coach",
        "description": "Ernährungsplanung und Essgewohnheiten",
        "role_id": "coach",
        "persona_id": "micha_nutrition",
        "knowledge_namespace": "private",
        "tools_enabled": ["web_search"],
        "greeting": "Zeit für Ernährungsfragen! Was beschäftigt dich?",
        "context_prompt": """
Du bist ein Nutrition Coach. Dein Fokus:

1. **Pragmatische Ernährung:**
   - Keine Diäten, sondern nachhaltige Gewohnheiten
   - 80/20 Prinzip (80% gut ist gut genug)
   - Meal Prep für Busy People

2. **Makro-Balance:**
   - Protein bei jeder Mahlzeit
   - Ballaststoffe für Sättigung
   - Flexible Carbs je nach Aktivität

3. **Habit Tracking:**
   - Kleine Änderungen > große Umstellungen
   - 1 neue Gewohnheit zur Zeit
   - Erfolge tracken, nicht Kalorien

4. **Output-Format für Meal Plans:**
   ---
   **Ziel:** [Was soll erreicht werden]

   **Wochenbasis:**
   - Frühstück: [2-3 Optionen]
   - Lunch: [2-3 Optionen]
   - Dinner: [2-3 Optionen]
   - Snacks: [Optionen]

   **Prep-Liste für Sonntag:**
   - [ ] [Vorbereitung 1]
   - [ ] [Vorbereitung 2]

   **Diese Woche fokussieren:** [1 Gewohnheit]
   ---
""",
        "keywords": ["essen", "ernährung", "nutrition", "meal", "mahlzeit", "abnehmen", "zunehmen"],
        "icon": "🥗"
    },
    "fitness": {
        "id": "fitness",
        "name": "Fitness Coach",
        "description": "Training, Recovery und Bewegung",
        "role_id": "coach",
        "persona_id": "micha_fitness",
        "knowledge_namespace": "private",
        "tools_enabled": ["web_search", "calendar_today"],
        "greeting": "Fitness-Zeit! Was ist dein Ziel oder deine Frage?",
        "context_prompt": """
Du bist ein Fitness Coach. Dein Fokus:

1. **Training-Prinzipien:**
   - Konsistenz > Perfektion
   - Progressive Overload
   - Recovery ist Teil des Trainings

2. **Workout-Planung:**
   - An Lifestyle anpassen
   - Min. effective dose
   - Compound Movements priorisieren

3. **Recovery:**
   - Schlaf als #1 Faktor
   - Active Recovery
   - Deload-Wochen

4. **Output-Format für Workouts:**
   ---
   **Ziel:** [Kraft/Ausdauer/Mobility]
   **Dauer:** [X Minuten]
   **Equipment:** [Was benötigt]

   **Warm-up (5 min):**
   - [Übung 1]
   - [Übung 2]

   **Main (X min):**
   - [Übung]: [Sets x Reps] @ [Intensität]
   - [Übung]: [Sets x Reps]

   **Cool-down (5 min):**
   - [Stretch/Mobility]
   ---
""",
        "keywords": ["training", "workout", "fitness", "sport", "übung", "gym", "recovery"],
        "icon": "💪"
    },
    "work": {
        "id": "work",
        "name": "Work Coach",
        "description": "Projekt-Coaching, Skill-Entwicklung und Karriere",
        "role_id": "coach",
        "persona_id": "micha_coach",
        "knowledge_namespace": "work_projektil",
        "tools_enabled": ["search_emails", "search_chats", "calendar_today", "web_search"],
        "greeting": "Lass uns über deine Arbeit sprechen. Was beschäftigt dich?",
        "context_prompt": """
Du bist ein Work/Karriere Coach. Dein Fokus:

1. **Projekt-Management:**
   - Prioritäten klären
   - Blockers identifizieren
   - Stakeholder Management

2. **Skill-Entwicklung:**
   - Gaps identifizieren
   - Lernpfad definieren
   - 70-20-10 Modell (Learning on the job)

3. **Karriere-Planung:**
   - Ziele definieren
   - Netzwerk aufbauen
   - Sichtbarkeit schaffen

4. **Output-Format für Projektanalyse:**
   ---
   **Projekt:** [Name]
   **Status:** 🟢/🟡/🔴

   **Blockers:**
   - [Blocker 1]: [Lösungsansatz]

   **Nächste Schritte (diese Woche):**
   1. [ ] [Action]
   2. [ ] [Action]

   **Stakeholder-Update nötig:** [Ja/Nein + wem]
   ---
""",
        "keywords": ["arbeit", "projekt", "karriere", "skill", "job", "stakeholder", "blocker"],
        "icon": "💼"
    },
    "ideas": {
        "id": "ideas",
        "name": "Ideas Buddy",
        "description": "Brainstorming, Devil's Advocate und Ideenentwicklung",
        "role_id": "analyst",
        "persona_id": "micha_ideas",
        "knowledge_namespace": "work_projektil",
        "tools_enabled": ["web_search"],
        "greeting": "Ideen-Session! Was willst du durchdenken?",
        "context_prompt": """
Du bist ein Ideas Buddy / Brainstorming Partner. Dein Fokus:

1. **Brainstorming-Modi:**
   - Divergent: Möglichst viele Ideen, keine Bewertung
   - Convergent: Ideen filtern und priorisieren
   - Devil's Advocate: Kritisch hinterfragen

2. **Techniken:**
   - "Yes, and..." statt "No, but..."
   - Reverse Brainstorming: Was würde es zerstören?
   - SCAMPER: Substitute, Combine, Adapt, Modify, Put to other use, Eliminate, Reverse

3. **Devil's Advocate Regeln:**
   - Nicht persönlich, sondern auf die Idee bezogen
   - "Was wenn das Gegenteil stimmt?"
   - Blinde Flecken aufzeigen

4. **Output-Format für Brainstorming:**
   ---
   **Thema:** [Worum geht's]

   **Ideen (ungefiltert):**
   1. [Idee] - [1 Satz why]
   2. [Idee]
   3. [Idee]
   ...

   **Top 3 nach [Kriterium]:**
   1. [Idee] - [Warum top]

   **Devil's Advocate:**
   - [Kritikpunkt an Top-Idee]
   - [Blinder Fleck]

   **Nächster Schritt:** [Wie weiter validieren]
   ---
""",
        "keywords": ["idee", "brainstorm", "devil", "durchdenken", "kreativ", "konzept"],
        "icon": "💡"
    },
    "presentation": {
        "id": "presentation",
        "name": "Presentation Coach",
        "description": "Präsentationsstruktur und Delivery",
        "role_id": "writer",
        "persona_id": "micha_presentation",
        "knowledge_namespace": "work_projektil",
        "tools_enabled": ["web_search", "search_emails"],
        "greeting": "Präsentations-Coaching! Was präsentierst du?",
        "context_prompt": """
Du bist ein Presentation Coach. Dein Fokus:

1. **Struktur:**
   - Hook: Warum sollte Publikum zuhören?
   - Problem: Pain Point klar machen
   - Solution: Dein Vorschlag
   - Evidence: Warum funktioniert das?
   - CTA: Was soll Publikum tun?

2. **Storytelling:**
   - Hero's Journey für Pitches
   - Konkrete Beispiele > abstrakte Konzepte
   - Emotionen vor Fakten

3. **Delivery:**
   - Pausen nutzen
   - Eye Contact simulieren
   - Energy Management

4. **Output-Format für Präsentations-Outline:**
   ---
   **Titel:** [Hook-Titel]
   **Zielgruppe:** [Wer]
   **Dauer:** [X Minuten]
   **Kernbotschaft:** [1 Satz]

   **Struktur:**

   1. **Opening (1 min):**
      - Hook: [Frage/Statistik/Story]

   2. **Problem (2 min):**
      - [Pain Point 1]
      - [Pain Point 2]

   3. **Solution (3 min):**
      - [Dein Vorschlag]
      - [Wie es funktioniert]

   4. **Evidence (2 min):**
      - [Beispiel/Case Study]

   5. **CTA (1 min):**
      - [Was soll Publikum tun]

   **Speaker Notes:**
   - Folie 1: [Was sagen]
   ---
""",
        "keywords": ["präsentation", "pitch", "vortrag", "slides", "keynote", "audience"],
        "icon": "🎤"
    },
    "mediaserver": {
        "id": "mediaserver",
        "name": "Mediaserver Coach",
        "description": "Pixera, Synology NAS, Grafana und Show-Systeme",
        "role_id": "analyst",
        "persona_id": "micha_debug",
        "knowledge_namespace": "work_visualfox",
        "tools_enabled": ["read_project_file", "search_knowledge"],
        "greeting": "Mediaserver-Modus! Was debuggen wir heute - Pixera, NAS oder Grafana?",
        "context_prompt": """
Du bist ein technischer Coach fuer Media Server und Show-Systeme.
Micha arbeitet als Media Server Lead und braucht Unterstuetzung bei:

1. **Pixera Show Systems:**
   - Timeline, Cues, Mapping
   - Output-Konfiguration (Resolution, Colorspace, Framerate)
   - Content-Pipeline (Codec, Bitrate, Formate)
   - Lua Scripting und Automation

2. **Synology NAS:**
   - Storage-Pools und RAID-Konfiguration
   - Netzwerk-Optimierung (10GbE, Link Aggregation)
   - Docker Container Management
   - Backup und Snapshot Strategien

3. **Grafana Monitoring:**
   - Dashboard-Design und Best Practices
   - Prometheus Metriken
   - Alerting und Notifications
   - Query-Optimierung

4. **Show-System Integration:**
   - NDI, SDI, HDMI-Workflows
   - Dante Audio Netzwerk
   - ArtNet / sACN Lighting Control
   - Timecode und Sync

**Debugging-Ansatz:**
1. Symptom dokumentieren
2. Komponente isolieren
3. Logs pruefen
4. Baseline vergleichen
5. Minimal reproduzieren
6. Fix testen (eine Aenderung zur Zeit)

**Antwort-Format:**
1. **Diagnose:** Wahrscheinlichstes Problem
2. **Check:** Commands/Schritte zum Verifizieren
3. **Fix:** Loesung mit Rollback-Option
4. **Praevention:** Wie in Zukunft vermeiden
""",
        "keywords": ["pixera", "medienserver", "mediaserver", "nas", "synology", "grafana", "show", "mapping", "ndi", "sdi", "4k", "8k"],
        "icon": "🎬"
    },
}


# ============ Cache ============

_domains_cache: Optional[Dict[str, CoachingDomain]] = None


def _load_domains() -> Dict[str, CoachingDomain]:
    """Load domains from config file or use defaults"""
    global _domains_cache
    if _domains_cache is not None:
        return _domains_cache

    domains = {}

    # First load defaults
    for domain_id, domain_data in DEFAULT_DOMAINS.items():
        domains[domain_id] = CoachingDomain(**domain_data)

    # Then overlay from config file if exists
    if DOMAINS_CONFIG_PATH.exists():
        try:
            with open(DOMAINS_CONFIG_PATH, "r", encoding="utf-8") as f:
                config = json.load(f)
                for domain_data in config.get("domains", []):
                    domain_id = domain_data.get("id")
                    if domain_id:
                        domains[domain_id] = CoachingDomain(**domain_data)
                log_with_context(logger, "info", "Loaded domains from config",
                               count=len(config.get("domains", [])))
        except (json.JSONDecodeError, KeyError) as e:
            log_with_context(logger, "warning", "Failed to load domains config",
                           error=str(e))

    _domains_cache = domains
    return _domains_cache


def reload_domains() -> None:
    """Force reload of domains (for hot-reloading)"""
    global _domains_cache
    _domains_cache = None
    _load_domains()


# ============ Domain Access ============

def get_domain(domain_id: str) -> Optional[CoachingDomain]:
    """Get a domain by ID"""
    domains = _load_domains()
    return domains.get(domain_id)


def list_domains() -> List[Dict[str, Any]]:
    """List all available domains"""
    domains = _load_domains()
    return [
        {
            "id": d.id,
            "name": d.name,
            "description": d.description,
            "icon": d.icon,
            "role_id": d.role_id,
            "persona_id": d.persona_id,
        }
        for d in domains.values()
    ]


def detect_domain(query: str, current_domain: str = "general") -> str:
    """
    Detect the most appropriate domain based on query keywords.
    Returns domain_id or current_domain if no strong match.
    """
    query_lower = query.lower()
    domains = _load_domains()

    # Explicit domain switch command
    if query_lower.startswith("/domain "):
        requested = query_lower.replace("/domain ", "").strip()
        if requested in domains:
            return requested
        return current_domain

    # Check for domain keywords
    best_match = current_domain
    best_score = 0

    for domain_id, domain in domains.items():
        score = 0
        for keyword in domain.keywords:
            if keyword in query_lower:
                score += len(keyword)

        if score > best_score:
            best_score = score
            best_match = domain_id

    # Only switch if strong signal
    if best_score >= 6:
        return best_match

    return current_domain


# ============ Domain Context Generation ============

def build_domain_context(domain_id: str) -> str:
    """
    Build the domain-specific context to inject into system prompt.
    Returns empty string if domain not found.
    """
    domain = get_domain(domain_id)
    if not domain or not domain.context_prompt:
        return ""

    lines = [
        f"=== ACTIVE COACHING DOMAIN: {domain.name.upper()} ===",
        f"Icon: {domain.icon}",
        "",
        domain.context_prompt.strip(),
        "",
    ]

    return "\n".join(lines)


def get_domain_greeting(domain_id: str) -> str:
    """Get the greeting message for a domain"""
    domain = get_domain(domain_id)
    if domain and domain.greeting:
        return f"{domain.icon} {domain.greeting}"
    return "Wie kann ich helfen?"


# ============ User Domain State ============

def get_user_domain(user_id: Any) -> str:
    """Get the current active domain for a user"""
    try:
        user_id_int = int(user_id)
    except Exception:
        # Internal/system calls may not have a numeric user id; default to general.
        return "general"

    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT active_domain FROM user_domain_state
                WHERE user_id = %s
            """, (user_id_int,))
            row = cur.fetchone()
            if row:
                return row["active_domain"]
    except Exception as e:
        log_with_context(logger, "warning", "Failed to get user domain", error=str(e))

    return "general"


def set_user_domain(user_id: Any, domain_id: str) -> bool:
    """Set the active domain for a user"""
    domain = get_domain(domain_id)
    if not domain:
        return False

    try:
        user_id_int = int(user_id)
    except Exception:
        return False

    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO user_domain_state (user_id, active_domain, switched_at)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id)
                DO UPDATE SET active_domain = EXCLUDED.active_domain,
                             switched_at = EXCLUDED.switched_at
            """, (user_id_int, domain_id, datetime.utcnow()))

            log_with_context(logger, "info", "User domain switched",
                           user_id=user_id_int, domain=domain_id)
            return True
    except Exception as e:
        log_with_context(logger, "error", "Failed to set user domain", error=str(e))
        return False


# ============ Domain Session Tracking ============

def start_domain_session(user_id: int, domain_id: str, goals: List[str] = None) -> Optional[int]:
    """Start a new coaching session in a domain"""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO domain_session
                (user_id, domain_id, started_at, goals, status)
                VALUES (%s, %s, %s, %s, 'active')
                RETURNING id
            """, (user_id, domain_id, datetime.utcnow(), json.dumps(goals or [])))
            row = cur.fetchone()
            return row["id"] if row else None
    except Exception as e:
        log_with_context(logger, "error", "Failed to start domain session", error=str(e))
        return None


def end_domain_session(session_id: int, notes: str = None) -> bool:
    """End a domain coaching session"""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                UPDATE domain_session
                SET ended_at = %s, status = 'completed', notes = %s
                WHERE id = %s
            """, (datetime.utcnow(), notes, session_id))
            return True
    except Exception as e:
        log_with_context(logger, "error", "Failed to end domain session", error=str(e))
        return False


def get_domain_sessions(user_id: int, domain_id: str = None, limit: int = 10) -> List[Dict]:
    """Get recent domain sessions for a user"""
    try:
        with get_conn() as conn:
            cur = conn.cursor()
            if domain_id:
                cur.execute("""
                    SELECT * FROM domain_session
                    WHERE user_id = %s AND domain_id = %s
                    ORDER BY started_at DESC
                    LIMIT %s
                """, (user_id, domain_id, limit))
            else:
                cur.execute("""
                    SELECT * FROM domain_session
                    WHERE user_id = %s
                    ORDER BY started_at DESC
                    LIMIT %s
                """, (user_id, limit))
            return [dict(row) for row in cur.fetchall()]
    except Exception as e:
        log_with_context(logger, "error", "Failed to get domain sessions", error=str(e))
        return []


# ============ Domain Knowledge Integration ============

def get_domain_namespace(domain_id: str) -> str:
    """Get the Qdrant namespace for a domain"""
    domain = get_domain(domain_id)
    return domain.knowledge_namespace if domain else "work_projektil"


def get_domain_tools(domain_id: str) -> List[str]:
    """Get enabled tools for a domain"""
    domain = get_domain(domain_id)
    return domain.tools_enabled if domain else []


def get_domain_role_and_persona(domain_id: str) -> Dict[str, str]:
    """Get the role and persona IDs for a domain"""
    domain = get_domain(domain_id)
    if domain:
        return {
            "role_id": domain.role_id,
            "persona_id": domain.persona_id,
        }
    return {
        "role_id": "assistant",
        "persona_id": "micha_default",
    }
