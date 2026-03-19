"""
Specialist Agent Service - Tier 3 #8

Domain-specific specialist agents for Jarvis:
- FitJarvis: Fitness, health, nutrition
- WorkJarvis: Productivity, projects, professional tasks
- CommJarvis: Communication, relationships, social

Provides:
- Specialist detection from query
- Specialist configuration loading
- Context injection for specialists
- Activation tracking
- Cross-session memory per specialist
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timedelta
import hashlib
import re
import json

from ..observability import get_logger, log_with_context
from ..postgres_state import get_conn

logger = get_logger("jarvis.specialist_agent")


@dataclass
class Specialist:
    """A specialist agent configuration."""
    id: int
    name: str
    display_name: str
    description: str

    # Detection
    keywords: List[str]
    domains: List[str]

    # Persona
    persona_prompt: str
    tone: str
    emoji_level: str
    verbosity: str

    # Tools
    preferred_tools: List[str]
    excluded_tools: List[str]
    tool_weights: Dict[str, float]

    # Context
    context_injections: List[str]
    knowledge_domains: List[str]

    # Model
    preferred_model: Optional[str]
    fallback_model: Optional[str]
    max_tokens: int

    # Behavior
    proactive_hints: bool
    remember_context: bool

    # Status
    enabled: bool
    priority: int


@dataclass
class SpecialistActivation:
    """Result of specialist detection."""
    specialist: Optional[Specialist]
    confidence: float
    trigger_type: str  # keyword, domain, explicit, context, none
    trigger_value: str
    reasoning: str


@dataclass
class SpecialistContext:
    """Context package for specialist execution."""
    specialist: Specialist
    persona_prompt: str
    preferred_tools: List[str]
    tool_weights: Dict[str, float]
    knowledge: List[Dict[str, Any]]
    memory: List[Dict[str, Any]]
    goals: List[Dict[str, Any]]


class SpecialistAgentService:
    """
    Manages domain-specific specialist agents.

    Detects when a specialist should be activated based on:
    - Keywords in query
    - Domain context
    - Explicit request ("FitJarvis" mention)
    - Contextual signals (time of day, recent topics)
    """

    def __init__(self):
        self._specialists_cache: Dict[str, Specialist] = {}
        self._cache_time: Optional[datetime] = None
        self._cache_ttl = timedelta(minutes=5)
        self._ensure_tables()

    def _ensure_tables(self):
        """Ensure specialist tables exist."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    # Check if main table exists
                    cur.execute("""
                        SELECT EXISTS (
                            SELECT FROM information_schema.tables
                            WHERE table_name = 'jarvis_specialists'
                        )
                    """)
                    if not cur.fetchone()[0]:
                        # Run migration
                        migration_path = "/brain/system/ingestion/migrations/110_specialist_agents.sql"
                        try:
                            with open(migration_path, "r") as f:
                                cur.execute(f.read())
                            conn.commit()
                            log_with_context(logger, "info", "Specialist tables created")
                        except Exception as e:
                            log_with_context(logger, "debug", "Migration file not found, creating tables inline", error=str(e))
                            self._create_tables_inline(cur)
                            conn.commit()
        except Exception as e:
            log_with_context(logger, "debug", "Specialist tables check failed", error=str(e))

    def _create_tables_inline(self, cur):
        """Create tables inline if migration not available."""
        cur.execute("""
            CREATE TABLE IF NOT EXISTS jarvis_specialists (
                id SERIAL PRIMARY KEY,
                name VARCHAR(50) NOT NULL UNIQUE,
                display_name VARCHAR(100) NOT NULL,
                description TEXT,
                keywords JSONB DEFAULT '[]'::jsonb,
                domains JSONB DEFAULT '[]'::jsonb,
                persona_prompt TEXT,
                tone VARCHAR(50) DEFAULT 'friendly',
                emoji_level VARCHAR(20) DEFAULT 'moderate',
                verbosity VARCHAR(20) DEFAULT 'concise',
                preferred_tools JSONB DEFAULT '[]'::jsonb,
                excluded_tools JSONB DEFAULT '[]'::jsonb,
                tool_weights JSONB DEFAULT '{}'::jsonb,
                context_injections JSONB DEFAULT '[]'::jsonb,
                knowledge_domains JSONB DEFAULT '[]'::jsonb,
                preferred_model VARCHAR(100),
                fallback_model VARCHAR(100),
                max_tokens INTEGER DEFAULT 2000,
                proactive_hints BOOLEAN DEFAULT TRUE,
                remember_context BOOLEAN DEFAULT TRUE,
                enabled BOOLEAN DEFAULT TRUE,
                priority INTEGER DEFAULT 100,
                activation_count INTEGER DEFAULT 0,
                success_rate REAL DEFAULT 0.5,
                avg_satisfaction REAL,
                last_activated_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS jarvis_specialist_activations (
                id SERIAL PRIMARY KEY,
                specialist_id INTEGER,
                specialist_name VARCHAR(50) NOT NULL,
                session_id VARCHAR(100),
                query_hash VARCHAR(32),
                trigger_type VARCHAR(50),
                trigger_value TEXT,
                confidence REAL DEFAULT 1.0,
                tools_used JSONB DEFAULT '[]'::jsonb,
                tokens_used INTEGER,
                duration_ms INTEGER,
                success BOOLEAN,
                user_feedback VARCHAR(20),
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS jarvis_specialist_knowledge (
                id SERIAL PRIMARY KEY,
                specialist_id INTEGER,
                specialist_name VARCHAR(50) NOT NULL,
                topic VARCHAR(200) NOT NULL,
                content TEXT NOT NULL,
                content_type VARCHAR(50) DEFAULT 'fact',
                keywords JSONB DEFAULT '[]'::jsonb,
                priority INTEGER DEFAULT 100,
                use_count INTEGER DEFAULT 0,
                last_used_at TIMESTAMP,
                enabled BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS jarvis_specialist_memory (
                id SERIAL PRIMARY KEY,
                specialist_id INTEGER,
                specialist_name VARCHAR(50) NOT NULL,
                memory_type VARCHAR(50) NOT NULL,
                key VARCHAR(200) NOT NULL,
                value JSONB NOT NULL,
                related_session_id VARCHAR(100),
                confidence REAL DEFAULT 0.8,
                expires_at TIMESTAMP,
                use_count INTEGER DEFAULT 0,
                last_used_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(specialist_name, memory_type, key)
            )
        """)

    def _load_specialists(self, force: bool = False) -> Dict[str, Specialist]:
        """Load specialists from database with caching."""
        now = datetime.now()

        if not force and self._cache_time and (now - self._cache_time) < self._cache_ttl:
            return self._specialists_cache

        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT id, name, display_name, description,
                               keywords, domains, persona_prompt, tone,
                               emoji_level, verbosity, preferred_tools,
                               excluded_tools, tool_weights, context_injections,
                               knowledge_domains, preferred_model, fallback_model,
                               max_tokens, proactive_hints, remember_context,
                               enabled, priority
                        FROM jarvis_specialists
                        WHERE enabled = TRUE
                        ORDER BY priority ASC
                    """)

                    self._specialists_cache = {}
                    for row in cur.fetchall():
                        spec = Specialist(
                            id=row["id"],
                            name=row["name"],
                            display_name=row["display_name"],
                            description=row["description"] or "",
                            keywords=row["keywords"] or [],
                            domains=row["domains"] or [],
                            persona_prompt=row["persona_prompt"] or "",
                            tone=row["tone"] or "friendly",
                            emoji_level=row["emoji_level"] or "moderate",
                            verbosity=row["verbosity"] or "concise",
                            preferred_tools=row["preferred_tools"] or [],
                            excluded_tools=row["excluded_tools"] or [],
                            tool_weights=row["tool_weights"] or {},
                            context_injections=row["context_injections"] or [],
                            knowledge_domains=row["knowledge_domains"] or [],
                            preferred_model=row["preferred_model"],
                            fallback_model=row["fallback_model"],
                            max_tokens=row["max_tokens"] or 2000,
                            proactive_hints=row["proactive_hints"],
                            remember_context=row["remember_context"],
                            enabled=row["enabled"],
                            priority=row["priority"]
                        )
                        self._specialists_cache[spec.name] = spec

                    self._cache_time = now

        except Exception as e:
            log_with_context(logger, "debug", "Failed to load specialists", error=str(e))

        return self._specialists_cache

    def detect_specialist(
        self,
        query: str,
        current_domain: Optional[str] = None,
        session_context: Optional[Dict[str, Any]] = None
    ) -> SpecialistActivation:
        """
        Detect which specialist (if any) should handle this query.

        Detection priority:
        1. Explicit mention ("FitJarvis", "WorkJarvis")
        2. Strong keyword match (multiple keywords)
        3. Domain context match
        4. Weak keyword match (single keyword)
        5. No specialist (general Jarvis)
        """
        specialists = self._load_specialists()
        if not specialists:
            return SpecialistActivation(
                specialist=None,
                confidence=0.0,
                trigger_type="none",
                trigger_value="",
                reasoning="No specialists configured"
            )

        query_lower = query.lower()

        # 1. Check explicit mention
        for name, spec in specialists.items():
            if spec.display_name.lower() in query_lower or f"@{name}" in query_lower:
                return SpecialistActivation(
                    specialist=spec,
                    confidence=1.0,
                    trigger_type="explicit",
                    trigger_value=spec.display_name,
                    reasoning=f"Explicit mention of {spec.display_name}"
                )

        # 2. Keyword matching
        keyword_scores: Dict[str, Tuple[int, List[str]]] = {}
        for name, spec in specialists.items():
            matches = []
            for keyword in spec.keywords:
                if keyword.lower() in query_lower:
                    matches.append(keyword)
            if matches:
                keyword_scores[name] = (len(matches), matches)

        # Strong keyword match (2+ keywords)
        if keyword_scores:
            best_name = max(keyword_scores.keys(), key=lambda n: keyword_scores[n][0])
            count, matches = keyword_scores[best_name]

            if count >= 2:
                spec = specialists[best_name]
                return SpecialistActivation(
                    specialist=spec,
                    confidence=min(0.9, 0.5 + count * 0.15),
                    trigger_type="keyword",
                    trigger_value=", ".join(matches[:3]),
                    reasoning=f"Strong keyword match: {', '.join(matches[:3])}"
                )

        # 3. Domain context match
        if current_domain:
            for name, spec in specialists.items():
                if current_domain in spec.domains:
                    return SpecialistActivation(
                        specialist=spec,
                        confidence=0.7,
                        trigger_type="domain",
                        trigger_value=current_domain,
                        reasoning=f"Domain context: {current_domain}"
                    )

        # 4. Weak keyword match (single keyword, lower confidence)
        if keyword_scores:
            best_name = max(keyword_scores.keys(), key=lambda n: keyword_scores[n][0])
            count, matches = keyword_scores[best_name]

            if count == 1:
                spec = specialists[best_name]
                return SpecialistActivation(
                    specialist=spec,
                    confidence=0.5,
                    trigger_type="keyword",
                    trigger_value=matches[0],
                    reasoning=f"Weak keyword match: {matches[0]}"
                )

        # 5. No specialist
        return SpecialistActivation(
            specialist=None,
            confidence=0.0,
            trigger_type="none",
            trigger_value="",
            reasoning="No specialist match - using general Jarvis"
        )

    def get_specialist(self, name: str) -> Optional[Specialist]:
        """Get a specific specialist by name."""
        specialists = self._load_specialists()
        return specialists.get(name)

    def get_all_specialists(self) -> List[Specialist]:
        """Get all enabled specialists."""
        specialists = self._load_specialists()
        return list(specialists.values())

    def get_specialist_context(
        self,
        specialist: Specialist,
        query: str,
        session_id: Optional[str] = None
    ) -> SpecialistContext:
        """
        Build complete context package for specialist execution.

        Includes:
        - Persona prompt
        - Preferred tools with weights
        - Relevant knowledge entries
        - Cross-session memory
        - Active goals (for FitJarvis)
        """
        knowledge = self._get_specialist_knowledge(specialist.name, query)
        memory = self._get_specialist_memory(specialist.name)
        goals = self._get_specialist_goals(specialist.name) if specialist.name == "fit" else []

        return SpecialistContext(
            specialist=specialist,
            persona_prompt=specialist.persona_prompt,
            preferred_tools=specialist.preferred_tools,
            tool_weights=specialist.tool_weights,
            knowledge=knowledge,
            memory=memory,
            goals=goals
        )

    def _get_specialist_knowledge(
        self,
        specialist_name: str,
        query: str,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """Get relevant knowledge entries for specialist."""
        try:
            # Extract keywords from query
            words = re.findall(r'\b[a-zäöüß]+\b', query.lower())
            keywords = [w for w in words if len(w) > 2]

            with get_conn() as conn:
                with conn.cursor() as cur:
                    if keywords:
                        # Match by keywords
                        cur.execute("""
                            SELECT topic, content, content_type, priority
                            FROM jarvis_specialist_knowledge
                            WHERE specialist_name = %s
                              AND enabled = TRUE
                              AND (keywords ?| %s OR topic ILIKE ANY(%s))
                            ORDER BY priority ASC
                            LIMIT %s
                        """, (
                            specialist_name,
                            keywords,
                            [f"%{k}%" for k in keywords[:5]],
                            limit
                        ))
                    else:
                        # Get highest priority entries
                        cur.execute("""
                            SELECT topic, content, content_type, priority
                            FROM jarvis_specialist_knowledge
                            WHERE specialist_name = %s AND enabled = TRUE
                            ORDER BY priority ASC
                            LIMIT %s
                        """, (specialist_name, limit))

                    return [
                        {
                            "topic": row["topic"],
                            "content": row["content"],
                            "type": row["content_type"]
                        }
                        for row in cur.fetchall()
                    ]

        except Exception as e:
            log_with_context(logger, "debug", "Knowledge retrieval failed", error=str(e))
            return []

    def _get_specialist_memory(
        self,
        specialist_name: str,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Get cross-session memory for specialist."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT memory_type, key, value, confidence
                        FROM jarvis_specialist_memory
                        WHERE specialist_name = %s
                          AND (expires_at IS NULL OR expires_at > NOW())
                        ORDER BY use_count DESC, updated_at DESC
                        LIMIT %s
                    """, (specialist_name, limit))

                    return [
                        {
                            "type": row["memory_type"],
                            "key": row["key"],
                            "value": row["value"],
                            "confidence": row["confidence"]
                        }
                        for row in cur.fetchall()
                    ]

        except Exception as e:
            log_with_context(logger, "debug", "Memory retrieval failed", error=str(e))
            return []

    def _get_specialist_goals(self, specialist_name: str) -> List[Dict[str, Any]]:
        """Get active goals relevant to specialist (mainly for FitJarvis)."""
        try:
            # Map specialist to goal categories
            category_map = {
                "fit": ["fitness", "health", "weight", "sport"],
                "work": ["work", "career", "productivity", "project"],
                "comm": ["social", "relationships", "networking"],
                "saas": ["saas", "revenue", "growth", "product"]
            }

            categories = category_map.get(specialist_name, [])
            if not categories:
                return []

            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT title, description, status, target_date, progress_percentage
                        FROM jarvis_goals
                        WHERE status = 'active'
                          AND category = ANY(%s)
                        ORDER BY target_date ASC NULLS LAST
                        LIMIT 5
                    """, (categories,))

                    return [
                        {
                            "title": row["title"],
                            "description": row["description"],
                            "status": row["status"],
                            "target_date": row["target_date"].isoformat() if row["target_date"] else None,
                            "progress": row["progress_percentage"]
                        }
                        for row in cur.fetchall()
                    ]

        except Exception as e:
            log_with_context(logger, "debug", "Goals retrieval failed", error=str(e))
            return []

    def record_activation(
        self,
        specialist: Specialist,
        session_id: Optional[str],
        query: str,
        trigger_type: str,
        trigger_value: str,
        confidence: float
    ) -> int:
        """Record a specialist activation."""
        try:
            query_hash = hashlib.md5(query.encode()).hexdigest()[:16]

            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO jarvis_specialist_activations
                        (specialist_id, specialist_name, session_id, query_hash,
                         trigger_type, trigger_value, confidence)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                    """, (
                        specialist.id, specialist.name, session_id,
                        query_hash, trigger_type, trigger_value, confidence
                    ))
                    activation_id = cur.fetchone()["id"]

                    # Update activation count
                    cur.execute("""
                        UPDATE jarvis_specialists
                        SET activation_count = activation_count + 1,
                            last_activated_at = NOW()
                        WHERE id = %s
                    """, (specialist.id,))

                    conn.commit()
                    return activation_id

        except Exception as e:
            log_with_context(logger, "debug", "Activation recording failed", error=str(e))
            return 0

    def complete_activation(
        self,
        activation_id: int,
        tools_used: List[str],
        tokens_used: int,
        duration_ms: int,
        success: bool
    ):
        """Complete an activation record with execution details."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE jarvis_specialist_activations
                        SET tools_used = %s,
                            tokens_used = %s,
                            duration_ms = %s,
                            success = %s
                        WHERE id = %s
                    """, (
                        json.dumps(tools_used),
                        tokens_used,
                        duration_ms,
                        success,
                        activation_id
                    ))
                    conn.commit()

        except Exception as e:
            log_with_context(logger, "debug", "Activation completion failed", error=str(e))

    def save_memory(
        self,
        specialist_name: str,
        memory_type: str,
        key: str,
        value: Any,
        confidence: float = 0.8,
        expires_days: Optional[int] = None,
        session_id: Optional[str] = None
    ):
        """Save a memory entry for a specialist."""
        try:
            expires_at = None
            if expires_days:
                expires_at = datetime.now() + timedelta(days=expires_days)

            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO jarvis_specialist_memory
                        (specialist_name, memory_type, key, value, confidence, expires_at, related_session_id)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (specialist_name, memory_type, key)
                        DO UPDATE SET
                            value = EXCLUDED.value,
                            confidence = EXCLUDED.confidence,
                            expires_at = EXCLUDED.expires_at,
                            use_count = jarvis_specialist_memory.use_count + 1,
                            updated_at = NOW()
                    """, (
                        specialist_name, memory_type, key,
                        json.dumps(value) if not isinstance(value, str) else value,
                        confidence, expires_at, session_id
                    ))
                    conn.commit()

        except Exception as e:
            log_with_context(logger, "debug", "Memory save failed", error=str(e))

    def get_specialist_stats(self, specialist_name: Optional[str] = None) -> Dict[str, Any]:
        """Get statistics for specialists."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    if specialist_name:
                        cur.execute("""
                            SELECT
                                s.name,
                                s.display_name,
                                s.activation_count,
                                s.success_rate,
                                s.last_activated_at,
                                COUNT(a.id) FILTER (WHERE a.created_at > NOW() - INTERVAL '7 days') as activations_7d,
                                AVG(a.duration_ms) FILTER (WHERE a.created_at > NOW() - INTERVAL '7 days') as avg_duration_7d
                            FROM jarvis_specialists s
                            LEFT JOIN jarvis_specialist_activations a ON s.name = a.specialist_name
                            WHERE s.name = %s
                            GROUP BY s.id
                        """, (specialist_name,))
                        row = cur.fetchone()
                        if row:
                            return {
                                "success": True,
                                "specialist": row["name"],
                                "display_name": row["display_name"],
                                "total_activations": row["activation_count"],
                                "success_rate": round(row["success_rate"] or 0, 2),
                                "last_activated": row["last_activated_at"].isoformat() if row["last_activated_at"] else None,
                                "activations_7d": row["activations_7d"],
                                "avg_duration_7d": round(row["avg_duration_7d"] or 0)
                            }
                    else:
                        cur.execute("""
                            SELECT
                                s.name,
                                s.display_name,
                                s.activation_count,
                                s.success_rate,
                                s.last_activated_at
                            FROM jarvis_specialists s
                            WHERE s.enabled = TRUE
                            ORDER BY s.activation_count DESC
                        """)
                        specialists = []
                        for row in cur.fetchall():
                            specialists.append({
                                "name": row["name"],
                                "display_name": row["display_name"],
                                "activations": row["activation_count"],
                                "success_rate": round(row["success_rate"] or 0, 2),
                                "last_used": row["last_activated_at"].isoformat() if row["last_activated_at"] else None
                            })

                        return {
                            "success": True,
                            "specialists": specialists,
                            "count": len(specialists)
                        }

        except Exception as e:
            return {"success": False, "error": str(e)}

        return {"success": False, "error": "Not found"}


# Singleton
_service: Optional[SpecialistAgentService] = None


def get_specialist_agent_service() -> SpecialistAgentService:
    """Get or create specialist agent service singleton."""
    global _service
    if _service is None:
        _service = SpecialistAgentService()
    return _service
