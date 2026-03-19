"""
Agent Context Isolation Service - Phase 22A-03

Provides isolated execution contexts for specialist agents:
- Memory namespace isolation (each agent has private memory)
- Tool scope restrictions (agents only access their allowed tools)
- Session context separation (per-agent conversation state)
- Cross-agent data boundaries (controlled sharing)
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Set
from datetime import datetime, timedelta
from enum import Enum
import json
import hashlib

from ..observability import get_logger, log_with_context
from ..postgres_state import get_conn

logger = get_logger("jarvis.agent_context_isolation")


class SharingPolicy(str, Enum):
    """Data sharing policies between agents."""
    PRIVATE = "private"          # Only this agent can access
    DOMAIN_SHARED = "domain"     # Agents in same domain can access
    CROSS_DOMAIN = "cross"       # All agents can access (with permission)
    PUBLIC = "public"            # Fully shared, no restrictions


@dataclass
class IsolatedContext:
    """Isolated execution context for an agent."""
    agent_id: str
    session_id: str
    memory_namespace: str
    allowed_tools: Set[str]
    blocked_tools: Set[str]
    context_data: Dict[str, Any]
    shared_data: Dict[str, Any]  # Data from other agents (with permission)
    created_at: datetime
    expires_at: Optional[datetime]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "session_id": self.session_id,
            "memory_namespace": self.memory_namespace,
            "allowed_tools": list(self.allowed_tools),
            "blocked_tools": list(self.blocked_tools),
            "context_keys": list(self.context_data.keys()),
            "shared_data_sources": list(self.shared_data.keys()),
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None
        }


@dataclass
class ContextBoundary:
    """Defines boundaries for cross-agent data access."""
    source_agent: str
    target_agent: str
    data_types: List[str]  # What types of data can be shared
    direction: str  # "read", "write", "both"
    requires_approval: bool
    created_at: datetime


class AgentContextIsolationService:
    """
    Manages isolated contexts for specialist agents.

    Key features:
    - Memory namespaces: Each agent stores/retrieves from isolated namespace
    - Tool scoping: Agents can only invoke tools in their allowed set
    - Context separation: Session context doesn't leak between agents
    - Controlled sharing: Explicit boundaries for cross-agent data access
    """

    def __init__(self):
        self._active_contexts: Dict[str, IsolatedContext] = {}
        self._boundaries: Dict[str, List[ContextBoundary]] = {}
        self._ensure_tables()

    def _ensure_tables(self):
        """Ensure isolation tables exist."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    # Agent context storage
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS jarvis_agent_contexts (
                            id SERIAL PRIMARY KEY,
                            agent_id VARCHAR(50) NOT NULL,
                            session_id VARCHAR(100) NOT NULL,
                            context_key VARCHAR(100) NOT NULL,
                            context_value JSONB NOT NULL,
                            sharing_policy VARCHAR(20) DEFAULT 'private',
                            expires_at TIMESTAMP,
                            created_at TIMESTAMP DEFAULT NOW(),
                            updated_at TIMESTAMP DEFAULT NOW(),
                            UNIQUE(agent_id, session_id, context_key)
                        )
                    """)

                    cur.execute("""
                        CREATE INDEX IF NOT EXISTS idx_agent_contexts_agent_session
                        ON jarvis_agent_contexts(agent_id, session_id)
                    """)

                    cur.execute("""
                        CREATE INDEX IF NOT EXISTS idx_agent_contexts_sharing
                        ON jarvis_agent_contexts(sharing_policy) WHERE sharing_policy != 'private'
                    """)

                    # Cross-agent boundaries
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS jarvis_agent_boundaries (
                            id SERIAL PRIMARY KEY,
                            source_agent VARCHAR(50) NOT NULL,
                            target_agent VARCHAR(50) NOT NULL,
                            data_types JSONB DEFAULT '[]',
                            direction VARCHAR(10) DEFAULT 'read',
                            requires_approval BOOLEAN DEFAULT TRUE,
                            active BOOLEAN DEFAULT TRUE,
                            created_at TIMESTAMP DEFAULT NOW(),
                            UNIQUE(source_agent, target_agent)
                        )
                    """)

                    # Isolated memory per agent
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS jarvis_agent_memory (
                            id SERIAL PRIMARY KEY,
                            agent_id VARCHAR(50) NOT NULL,
                            namespace VARCHAR(100) NOT NULL,
                            memory_key VARCHAR(200) NOT NULL,
                            memory_value JSONB NOT NULL,
                            memory_type VARCHAR(50) DEFAULT 'fact',
                            confidence FLOAT DEFAULT 0.8,
                            access_count INTEGER DEFAULT 0,
                            sharing_policy VARCHAR(20) DEFAULT 'private',
                            expires_at TIMESTAMP,
                            created_at TIMESTAMP DEFAULT NOW(),
                            updated_at TIMESTAMP DEFAULT NOW(),
                            UNIQUE(agent_id, namespace, memory_key)
                        )
                    """)

                    cur.execute("""
                        CREATE INDEX IF NOT EXISTS idx_agent_memory_namespace
                        ON jarvis_agent_memory(agent_id, namespace)
                    """)

                    conn.commit()
        except Exception as e:
            log_with_context(logger, "warning", "Table creation failed", error=str(e))

    # =========================================================================
    # Context Management
    # =========================================================================

    def create_context(
        self,
        agent_id: str,
        session_id: str,
        allowed_tools: List[str] = None,
        blocked_tools: List[str] = None,
        initial_context: Dict[str, Any] = None,
        ttl_minutes: int = 60
    ) -> IsolatedContext:
        """
        Create an isolated execution context for an agent.

        Args:
            agent_id: The specialist agent ID
            session_id: Current session/conversation ID
            allowed_tools: Explicit list of allowed tools (whitelist)
            blocked_tools: Tools to block (blacklist, applied after whitelist)
            initial_context: Starting context data
            ttl_minutes: Context lifetime in minutes
        """
        # Get agent's default tools from registry
        default_tools = self._get_agent_tools(agent_id)

        # Apply tool restrictions
        tools = set(allowed_tools) if allowed_tools else set(default_tools)
        blocked = set(blocked_tools) if blocked_tools else set()

        # Get memory namespace
        namespace = self._get_memory_namespace(agent_id)

        context = IsolatedContext(
            agent_id=agent_id,
            session_id=session_id,
            memory_namespace=namespace,
            allowed_tools=tools - blocked,
            blocked_tools=blocked,
            context_data=initial_context or {},
            shared_data={},
            created_at=datetime.now(),
            expires_at=datetime.now() + timedelta(minutes=ttl_minutes) if ttl_minutes else None
        )

        # Load shared data from other agents (if boundaries allow)
        context.shared_data = self._load_shared_data(agent_id, session_id)

        # Cache active context
        context_key = f"{agent_id}:{session_id}"
        self._active_contexts[context_key] = context

        log_with_context(logger, "info", "Context created",
                        agent_id=agent_id, session_id=session_id,
                        tools_count=len(context.allowed_tools))

        return context

    def get_context(self, agent_id: str, session_id: str) -> Optional[IsolatedContext]:
        """Get active context for an agent session."""
        context_key = f"{agent_id}:{session_id}"

        if context_key in self._active_contexts:
            context = self._active_contexts[context_key]
            # Check expiration
            if context.expires_at and datetime.now() > context.expires_at:
                del self._active_contexts[context_key]
                return None
            return context

        # Try to restore from database
        return self._restore_context(agent_id, session_id)

    def update_context(
        self,
        agent_id: str,
        session_id: str,
        key: str,
        value: Any,
        sharing_policy: SharingPolicy = SharingPolicy.PRIVATE
    ) -> Dict[str, Any]:
        """Update a value in the agent's context."""
        context = self.get_context(agent_id, session_id)
        if not context:
            return {"success": False, "error": "No active context"}

        # Update in-memory
        context.context_data[key] = value

        # Persist to database
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO jarvis_agent_contexts
                        (agent_id, session_id, context_key, context_value, sharing_policy)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (agent_id, session_id, context_key)
                        DO UPDATE SET context_value = EXCLUDED.context_value,
                                      sharing_policy = EXCLUDED.sharing_policy,
                                      updated_at = NOW()
                    """, (agent_id, session_id, key, json.dumps(value), sharing_policy.value))
                    conn.commit()

            return {"success": True, "key": key, "sharing": sharing_policy.value}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def destroy_context(self, agent_id: str, session_id: str) -> Dict[str, Any]:
        """Destroy an agent's context (end of session)."""
        context_key = f"{agent_id}:{session_id}"

        if context_key in self._active_contexts:
            del self._active_contexts[context_key]

        # Optionally archive context data
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    # Mark context entries as expired
                    cur.execute("""
                        UPDATE jarvis_agent_contexts
                        SET expires_at = NOW()
                        WHERE agent_id = %s AND session_id = %s
                    """, (agent_id, session_id))
                    conn.commit()

            return {"success": True, "agent_id": agent_id, "session_id": session_id}

        except Exception as e:
            return {"success": False, "error": str(e)}

    # =========================================================================
    # Tool Scope Enforcement
    # =========================================================================

    def can_use_tool(self, agent_id: str, session_id: str, tool_name: str) -> bool:
        """Check if an agent is allowed to use a specific tool."""
        context = self.get_context(agent_id, session_id)
        if not context:
            # No context = no restrictions (fallback mode)
            return True

        # Check blocked first
        if tool_name in context.blocked_tools:
            log_with_context(logger, "warning", "Tool blocked",
                           agent_id=agent_id, tool=tool_name)
            return False

        # Check allowed (empty = all allowed)
        if context.allowed_tools and tool_name not in context.allowed_tools:
            log_with_context(logger, "warning", "Tool not in whitelist",
                           agent_id=agent_id, tool=tool_name)
            return False

        return True

    def filter_tools(
        self,
        agent_id: str,
        session_id: str,
        available_tools: List[str]
    ) -> List[str]:
        """Filter available tools based on agent's context."""
        context = self.get_context(agent_id, session_id)
        if not context:
            return available_tools

        filtered = []
        for tool in available_tools:
            if tool not in context.blocked_tools:
                if not context.allowed_tools or tool in context.allowed_tools:
                    filtered.append(tool)

        return filtered

    # =========================================================================
    # Memory Isolation
    # =========================================================================

    def store_memory(
        self,
        agent_id: str,
        key: str,
        value: Any,
        memory_type: str = "fact",
        confidence: float = 0.8,
        sharing_policy: SharingPolicy = SharingPolicy.PRIVATE,
        expires_days: int = None
    ) -> Dict[str, Any]:
        """Store a memory in the agent's isolated namespace."""
        namespace = self._get_memory_namespace(agent_id)

        expires_at = None
        if expires_days:
            expires_at = datetime.now() + timedelta(days=expires_days)

        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO jarvis_agent_memory
                        (agent_id, namespace, memory_key, memory_value, memory_type,
                         confidence, sharing_policy, expires_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (agent_id, namespace, memory_key)
                        DO UPDATE SET
                            memory_value = EXCLUDED.memory_value,
                            memory_type = EXCLUDED.memory_type,
                            confidence = EXCLUDED.confidence,
                            sharing_policy = EXCLUDED.sharing_policy,
                            expires_at = EXCLUDED.expires_at,
                            access_count = jarvis_agent_memory.access_count + 1,
                            updated_at = NOW()
                        RETURNING id
                    """, (
                        agent_id, namespace, key, json.dumps(value),
                        memory_type, confidence, sharing_policy.value, expires_at
                    ))
                    memory_id = cur.fetchone()[0]
                    conn.commit()

                    return {
                        "success": True,
                        "memory_id": memory_id,
                        "agent_id": agent_id,
                        "namespace": namespace,
                        "key": key
                    }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def recall_memory(
        self,
        agent_id: str,
        key: str = None,
        memory_type: str = None,
        include_shared: bool = False,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Recall memories from the agent's namespace."""
        namespace = self._get_memory_namespace(agent_id)

        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    if key:
                        # Exact key lookup
                        cur.execute("""
                            SELECT memory_key, memory_value, memory_type, confidence, updated_at
                            FROM jarvis_agent_memory
                            WHERE agent_id = %s AND namespace = %s AND memory_key = %s
                              AND (expires_at IS NULL OR expires_at > NOW())
                        """, (agent_id, namespace, key))
                    else:
                        # List memories
                        query = """
                            SELECT memory_key, memory_value, memory_type, confidence, updated_at
                            FROM jarvis_agent_memory
                            WHERE agent_id = %s AND namespace = %s
                              AND (expires_at IS NULL OR expires_at > NOW())
                        """
                        params = [agent_id, namespace]

                        if memory_type:
                            query += " AND memory_type = %s"
                            params.append(memory_type)

                        query += " ORDER BY updated_at DESC LIMIT %s"
                        params.append(limit)

                        cur.execute(query, tuple(params))

                    memories = []
                    for row in cur.fetchall():
                        memories.append({
                            "key": row[0],
                            "value": row[1],
                            "type": row[2],
                            "confidence": row[3],
                            "updated_at": row[4].isoformat() if row[4] else None,
                            "source": agent_id
                        })

                    # Include shared memories if requested
                    if include_shared:
                        shared = self._get_shared_memories(agent_id, limit=5)
                        memories.extend(shared)

                    # Update access count
                    if memories:
                        cur.execute("""
                            UPDATE jarvis_agent_memory
                            SET access_count = access_count + 1
                            WHERE agent_id = %s AND namespace = %s
                              AND memory_key = ANY(%s)
                        """, (agent_id, namespace, [m["key"] for m in memories if m["source"] == agent_id]))
                        conn.commit()

                    return memories

        except Exception as e:
            log_with_context(logger, "error", "Memory recall failed", error=str(e))
            return []

    # =========================================================================
    # Cross-Agent Boundaries
    # =========================================================================

    def set_boundary(
        self,
        source_agent: str,
        target_agent: str,
        data_types: List[str],
        direction: str = "read",
        requires_approval: bool = True
    ) -> Dict[str, Any]:
        """Set a data sharing boundary between agents."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO jarvis_agent_boundaries
                        (source_agent, target_agent, data_types, direction, requires_approval)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (source_agent, target_agent)
                        DO UPDATE SET
                            data_types = EXCLUDED.data_types,
                            direction = EXCLUDED.direction,
                            requires_approval = EXCLUDED.requires_approval
                    """, (source_agent, target_agent, json.dumps(data_types), direction, requires_approval))
                    conn.commit()

                    return {
                        "success": True,
                        "source": source_agent,
                        "target": target_agent,
                        "direction": direction
                    }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_boundaries(self, agent_id: str) -> Dict[str, Any]:
        """Get all boundaries for an agent (both directions)."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT source_agent, target_agent, data_types, direction, requires_approval
                        FROM jarvis_agent_boundaries
                        WHERE (source_agent = %s OR target_agent = %s) AND active = TRUE
                    """, (agent_id, agent_id))

                    can_read_from = []
                    can_write_to = []

                    for row in cur.fetchall():
                        boundary = {
                            "agent": row[0] if row[1] == agent_id else row[1],
                            "data_types": row[2],
                            "requires_approval": row[4]
                        }
                        if row[0] == agent_id and row[3] in ["write", "both"]:
                            can_write_to.append(boundary)
                        if row[1] == agent_id and row[3] in ["read", "both"]:
                            can_read_from.append(boundary)

                    return {
                        "success": True,
                        "agent_id": agent_id,
                        "can_read_from": can_read_from,
                        "can_write_to": can_write_to
                    }

        except Exception as e:
            return {"success": False, "error": str(e)}

    # =========================================================================
    # Private Helpers
    # =========================================================================

    def _get_agent_tools(self, agent_id: str) -> List[str]:
        """Get default tools for an agent from registry."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT tools FROM jarvis_specialist_agents
                        WHERE agent_id = %s
                    """, (agent_id,))
                    row = cur.fetchone()
                    if row and row[0]:
                        return row[0]
        except:
            pass
        return []

    def _get_memory_namespace(self, agent_id: str) -> str:
        """Get memory namespace for an agent."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT memory_namespace FROM jarvis_specialist_agents
                        WHERE agent_id = %s
                    """, (agent_id,))
                    row = cur.fetchone()
                    if row and row[0]:
                        return row[0]
        except:
            pass
        return agent_id  # Fallback to agent_id as namespace

    def _load_shared_data(self, agent_id: str, session_id: str) -> Dict[str, Any]:
        """Load data shared by other agents (respecting boundaries)."""
        shared = {}
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    # Get agents that share data with us
                    cur.execute("""
                        SELECT b.source_agent, b.data_types
                        FROM jarvis_agent_boundaries b
                        WHERE b.target_agent = %s AND b.active = TRUE
                          AND b.direction IN ('read', 'both')
                    """, (agent_id,))

                    for row in cur.fetchall():
                        source_agent = row[0]
                        data_types = row[1] or []

                        # Get shared context from source agent
                        cur.execute("""
                            SELECT context_key, context_value
                            FROM jarvis_agent_contexts
                            WHERE agent_id = %s
                              AND sharing_policy IN ('domain', 'cross', 'public')
                              AND (expires_at IS NULL OR expires_at > NOW())
                            LIMIT 10
                        """, (source_agent,))

                        for ctx_row in cur.fetchall():
                            shared[f"{source_agent}:{ctx_row[0]}"] = ctx_row[1]

        except Exception as e:
            log_with_context(logger, "debug", "Shared data load failed", error=str(e))

        return shared

    def _get_shared_memories(self, agent_id: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Get memories shared by other agents."""
        memories = []
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    # Get boundaries
                    cur.execute("""
                        SELECT source_agent FROM jarvis_agent_boundaries
                        WHERE target_agent = %s AND active = TRUE
                          AND direction IN ('read', 'both')
                    """, (agent_id,))
                    source_agents = [row[0] for row in cur.fetchall()]

                    if source_agents:
                        cur.execute("""
                            SELECT agent_id, memory_key, memory_value, memory_type, confidence
                            FROM jarvis_agent_memory
                            WHERE agent_id = ANY(%s)
                              AND sharing_policy IN ('domain', 'cross', 'public')
                              AND (expires_at IS NULL OR expires_at > NOW())
                            ORDER BY updated_at DESC
                            LIMIT %s
                        """, (source_agents, limit))

                        for row in cur.fetchall():
                            memories.append({
                                "source": row[0],
                                "key": row[1],
                                "value": row[2],
                                "type": row[3],
                                "confidence": row[4]
                            })

        except Exception as e:
            log_with_context(logger, "debug", "Shared memories load failed", error=str(e))

        return memories

    def _restore_context(self, agent_id: str, session_id: str) -> Optional[IsolatedContext]:
        """Restore context from database."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT context_key, context_value
                        FROM jarvis_agent_contexts
                        WHERE agent_id = %s AND session_id = %s
                          AND (expires_at IS NULL OR expires_at > NOW())
                    """, (agent_id, session_id))

                    context_data = {}
                    for row in cur.fetchall():
                        context_data[row[0]] = row[1]

                    if context_data:
                        return self.create_context(
                            agent_id=agent_id,
                            session_id=session_id,
                            initial_context=context_data
                        )

        except Exception as e:
            log_with_context(logger, "debug", "Context restore failed", error=str(e))

        return None

    def get_isolation_stats(self) -> Dict[str, Any]:
        """Get statistics about context isolation."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    # Active contexts
                    cur.execute("""
                        SELECT agent_id, COUNT(DISTINCT session_id), COUNT(*)
                        FROM jarvis_agent_contexts
                        WHERE expires_at IS NULL OR expires_at > NOW()
                        GROUP BY agent_id
                    """)
                    context_stats = {row[0]: {"sessions": row[1], "entries": row[2]} for row in cur.fetchall()}

                    # Memory stats
                    cur.execute("""
                        SELECT agent_id, namespace, COUNT(*), SUM(access_count)
                        FROM jarvis_agent_memory
                        WHERE expires_at IS NULL OR expires_at > NOW()
                        GROUP BY agent_id, namespace
                    """)
                    memory_stats = {}
                    for row in cur.fetchall():
                        memory_stats[row[0]] = {
                            "namespace": row[1],
                            "memories": row[2],
                            "total_accesses": row[3] or 0
                        }

                    # Boundaries
                    cur.execute("""
                        SELECT COUNT(*) FROM jarvis_agent_boundaries WHERE active = TRUE
                    """)
                    boundary_count = cur.fetchone()[0]

                    return {
                        "success": True,
                        "active_in_memory": len(self._active_contexts),
                        "context_stats": context_stats,
                        "memory_stats": memory_stats,
                        "active_boundaries": boundary_count
                    }

        except Exception as e:
            return {"success": False, "error": str(e)}


# Singleton
_service: Optional[AgentContextIsolationService] = None


def get_agent_context_isolation_service() -> AgentContextIsolationService:
    """Get or create context isolation service singleton."""
    global _service
    if _service is None:
        _service = AgentContextIsolationService()
    return _service
