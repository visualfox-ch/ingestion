"""
Agent Registry & Lifecycle Service - Phase 22A-02

Central registry for all specialist agents with lifecycle management:
- Agent registration/deregistration
- Lifecycle states: registered → initializing → active → paused → stopped → error
- Health checks per agent
- Runtime configuration updates
- Agent dependencies and coordination
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from enum import Enum
import json

from ..observability import get_logger, log_with_context
from ..postgres_state import get_conn

logger = get_logger("jarvis.agent_registry")


class AgentState(str, Enum):
    """Lifecycle states for agents."""
    REGISTERED = "registered"      # Agent defined but not started
    INITIALIZING = "initializing"  # Agent starting up
    ACTIVE = "active"              # Agent ready for requests
    PAUSED = "paused"              # Agent temporarily disabled
    STOPPED = "stopped"            # Agent cleanly shut down
    ERROR = "error"                # Agent in error state
    MAINTENANCE = "maintenance"    # Agent under maintenance


@dataclass
class AgentHealth:
    """Health status for an agent."""
    agent_id: str
    state: AgentState
    healthy: bool
    last_check: datetime
    error_count: int
    last_error: Optional[str]
    avg_response_ms: Optional[float]
    uptime_pct: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "state": self.state.value,
            "healthy": self.healthy,
            "last_check": self.last_check.isoformat() if self.last_check else None,
            "error_count": self.error_count,
            "last_error": self.last_error,
            "avg_response_ms": self.avg_response_ms,
            "uptime_pct": round(self.uptime_pct, 2)
        }


@dataclass
class RegisteredAgent:
    """Full agent registration info."""
    id: int
    agent_id: str
    domain: str
    display_name: str
    tools: List[str]
    identity_extension: Dict[str, Any]
    memory_namespace: str
    confidence_threshold: float
    state: AgentState
    dependencies: List[str]
    activation_count: int
    last_activated_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    health: Optional[AgentHealth] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "domain": self.domain,
            "display_name": self.display_name,
            "tools": self.tools,
            "identity_extension": self.identity_extension,
            "memory_namespace": self.memory_namespace,
            "confidence_threshold": self.confidence_threshold,
            "state": self.state.value,
            "dependencies": self.dependencies,
            "activation_count": self.activation_count,
            "last_activated_at": self.last_activated_at.isoformat() if self.last_activated_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "health": self.health.to_dict() if self.health else None
        }


class AgentRegistryService:
    """
    Central registry for all specialist agents.

    Manages:
    - Agent registration and discovery
    - Lifecycle transitions (start, stop, pause, resume)
    - Health monitoring
    - Configuration updates
    - Dependency resolution
    """

    def __init__(self):
        self._agents_cache: Dict[str, RegisteredAgent] = {}
        self._cache_time: Optional[datetime] = None
        self._cache_ttl = timedelta(minutes=2)
        self._health_cache: Dict[str, AgentHealth] = {}
        self._ensure_schema()

    def _ensure_schema(self):
        """Ensure registry schema has all required columns."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    # Add state column if not exists
                    cur.execute("""
                        DO $$
                        BEGIN
                            IF NOT EXISTS (
                                SELECT 1 FROM information_schema.columns
                                WHERE table_name = 'jarvis_specialist_agents' AND column_name = 'state'
                            ) THEN
                                ALTER TABLE jarvis_specialist_agents ADD COLUMN state VARCHAR(20) DEFAULT 'active';
                            END IF;

                            IF NOT EXISTS (
                                SELECT 1 FROM information_schema.columns
                                WHERE table_name = 'jarvis_specialist_agents' AND column_name = 'dependencies'
                            ) THEN
                                ALTER TABLE jarvis_specialist_agents ADD COLUMN dependencies JSONB DEFAULT '[]';
                            END IF;

                            IF NOT EXISTS (
                                SELECT 1 FROM information_schema.columns
                                WHERE table_name = 'jarvis_specialist_agents' AND column_name = 'error_count'
                            ) THEN
                                ALTER TABLE jarvis_specialist_agents ADD COLUMN error_count INTEGER DEFAULT 0;
                            END IF;

                            IF NOT EXISTS (
                                SELECT 1 FROM information_schema.columns
                                WHERE table_name = 'jarvis_specialist_agents' AND column_name = 'last_error'
                            ) THEN
                                ALTER TABLE jarvis_specialist_agents ADD COLUMN last_error TEXT;
                            END IF;

                            IF NOT EXISTS (
                                SELECT 1 FROM information_schema.columns
                                WHERE table_name = 'jarvis_specialist_agents' AND column_name = 'last_health_check'
                            ) THEN
                                ALTER TABLE jarvis_specialist_agents ADD COLUMN last_health_check TIMESTAMP;
                            END IF;
                        END $$
                    """)
                    conn.commit()
        except Exception as e:
            log_with_context(logger, "warning", "Schema update failed", error=str(e))

    def _load_agents(self, force: bool = False) -> Dict[str, RegisteredAgent]:
        """Load all registered agents with caching."""
        now = datetime.now()

        if not force and self._cache_time and (now - self._cache_time) < self._cache_ttl:
            return self._agents_cache

        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT id, agent_id, domain, display_name, tools,
                               identity_extension, memory_namespace, confidence_threshold,
                               COALESCE(state, 'active') as state,
                               COALESCE(dependencies, '[]'::jsonb) as dependencies,
                               activation_count, last_activated_at,
                               created_at, updated_at,
                               COALESCE(error_count, 0) as error_count,
                               last_error, last_health_check
                        FROM jarvis_specialist_agents
                        ORDER BY domain, agent_id
                    """)

                    self._agents_cache = {}
                    for row in cur.fetchall():
                        state = AgentState(row["state"]) if row["state"] else AgentState.ACTIVE

                        # Build health from cached or current data
                        health = AgentHealth(
                            agent_id=row["agent_id"],
                            state=state,
                            healthy=state == AgentState.ACTIVE and row["error_count"] < 3,
                            last_check=row["last_health_check"] or now,
                            error_count=row["error_count"],
                            last_error=row["last_error"],
                            avg_response_ms=None,  # Will be populated from metrics
                            uptime_pct=100.0 if state == AgentState.ACTIVE else 0.0
                        )

                        agent = RegisteredAgent(
                            id=row["id"],
                            agent_id=row["agent_id"],
                            domain=row["domain"],
                            display_name=row["display_name"] or row["agent_id"],
                            tools=row["tools"] or [],
                            identity_extension=row["identity_extension"] or {},
                            memory_namespace=row["memory_namespace"] or row["domain"],
                            confidence_threshold=row["confidence_threshold"] or 0.7,
                            state=state,
                            dependencies=row["dependencies"] or [],
                            activation_count=row["activation_count"] or 0,
                            last_activated_at=row["last_activated_at"],
                            created_at=row["created_at"],
                            updated_at=row["updated_at"],
                            health=health
                        )
                        self._agents_cache[agent.agent_id] = agent

                    self._cache_time = now

        except Exception as e:
            log_with_context(logger, "error", "Failed to load agents", error=str(e))

        return self._agents_cache

    # =========================================================================
    # Registration
    # =========================================================================

    def register_agent(
        self,
        agent_id: str,
        domain: str,
        display_name: Optional[str] = None,
        tools: Optional[List[str]] = None,
        identity_extension: Optional[Dict[str, Any]] = None,
        memory_namespace: Optional[str] = None,
        confidence_threshold: float = 0.7,
        dependencies: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Register a new specialist agent.

        Args:
            agent_id: Unique identifier (e.g., 'fit_jarvis')
            domain: Primary domain (e.g., 'fitness')
            display_name: Human-readable name
            tools: List of tool names this agent can use
            identity_extension: Persona/style configuration
            memory_namespace: Memory isolation namespace
            confidence_threshold: Minimum confidence for activation
            dependencies: Other agent_ids this agent depends on

        Returns:
            Registration result with agent details
        """
        try:
            # Validate dependencies exist
            if dependencies:
                existing = self._load_agents()
                missing = [d for d in dependencies if d not in existing]
                if missing:
                    return {
                        "success": False,
                        "error": f"Missing dependencies: {missing}"
                    }

            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO jarvis_specialist_agents
                        (agent_id, domain, display_name, tools, identity_extension,
                         memory_namespace, confidence_threshold, state, dependencies)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (agent_id) DO UPDATE SET
                            domain = EXCLUDED.domain,
                            display_name = EXCLUDED.display_name,
                            tools = EXCLUDED.tools,
                            identity_extension = EXCLUDED.identity_extension,
                            memory_namespace = EXCLUDED.memory_namespace,
                            confidence_threshold = EXCLUDED.confidence_threshold,
                            dependencies = EXCLUDED.dependencies,
                            updated_at = NOW()
                        RETURNING id
                    """, (
                        agent_id,
                        domain,
                        display_name or agent_id,
                        json.dumps(tools or []),
                        json.dumps(identity_extension or {}),
                        memory_namespace or domain,
                        confidence_threshold,
                        AgentState.REGISTERED.value,
                        json.dumps(dependencies or [])
                    ))
                    agent_db_id = cur.fetchone()["id"]
                    conn.commit()

                    # Invalidate cache
                    self._cache_time = None

                    log_with_context(logger, "info", "Agent registered",
                                   agent_id=agent_id, domain=domain)

                    return {
                        "success": True,
                        "agent_id": agent_id,
                        "db_id": agent_db_id,
                        "state": AgentState.REGISTERED.value,
                        "message": f"Agent {agent_id} registered successfully"
                    }

        except Exception as e:
            log_with_context(logger, "error", "Registration failed",
                           agent_id=agent_id, error=str(e))
            return {"success": False, "error": str(e)}

    def deregister_agent(self, agent_id: str, force: bool = False) -> Dict[str, Any]:
        """
        Remove an agent from the registry.

        Args:
            agent_id: Agent to remove
            force: Remove even if other agents depend on it
        """
        try:
            agents = self._load_agents()

            if agent_id not in agents:
                return {"success": False, "error": f"Agent {agent_id} not found"}

            # Check dependents
            if not force:
                dependents = [
                    a.agent_id for a in agents.values()
                    if agent_id in a.dependencies
                ]
                if dependents:
                    return {
                        "success": False,
                        "error": f"Cannot deregister: agents {dependents} depend on {agent_id}"
                    }

            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        DELETE FROM jarvis_specialist_agents
                        WHERE agent_id = %s
                    """, (agent_id,))
                    conn.commit()

                    self._cache_time = None

                    return {
                        "success": True,
                        "agent_id": agent_id,
                        "message": f"Agent {agent_id} deregistered"
                    }

        except Exception as e:
            return {"success": False, "error": str(e)}

    # =========================================================================
    # Lifecycle Management
    # =========================================================================

    def _transition_state(
        self,
        agent_id: str,
        new_state: AgentState,
        reason: Optional[str] = None
    ) -> Dict[str, Any]:
        """Internal state transition with validation."""
        agents = self._load_agents()

        if agent_id not in agents:
            return {"success": False, "error": f"Agent {agent_id} not found"}

        agent = agents[agent_id]
        old_state = agent.state

        # Valid transitions
        valid_transitions = {
            AgentState.REGISTERED: [AgentState.INITIALIZING, AgentState.STOPPED],
            AgentState.INITIALIZING: [AgentState.ACTIVE, AgentState.ERROR],
            AgentState.ACTIVE: [AgentState.PAUSED, AgentState.STOPPED, AgentState.ERROR, AgentState.MAINTENANCE],
            AgentState.PAUSED: [AgentState.ACTIVE, AgentState.STOPPED],
            AgentState.STOPPED: [AgentState.REGISTERED, AgentState.INITIALIZING],
            AgentState.ERROR: [AgentState.STOPPED, AgentState.INITIALIZING],
            AgentState.MAINTENANCE: [AgentState.ACTIVE, AgentState.STOPPED]
        }

        if new_state not in valid_transitions.get(old_state, []):
            return {
                "success": False,
                "error": f"Invalid transition: {old_state.value} → {new_state.value}"
            }

        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    if new_state == AgentState.ERROR and reason:
                        cur.execute("""
                            UPDATE jarvis_specialist_agents
                            SET state = %s, last_error = %s,
                                error_count = error_count + 1, updated_at = NOW()
                            WHERE agent_id = %s
                        """, (new_state.value, reason, agent_id))
                    else:
                        cur.execute("""
                            UPDATE jarvis_specialist_agents
                            SET state = %s, updated_at = NOW()
                            WHERE agent_id = %s
                        """, (new_state.value, agent_id))
                    conn.commit()

                    self._cache_time = None

                    log_with_context(logger, "info", "Agent state changed",
                                   agent_id=agent_id,
                                   old_state=old_state.value,
                                   new_state=new_state.value)

                    return {
                        "success": True,
                        "agent_id": agent_id,
                        "old_state": old_state.value,
                        "new_state": new_state.value
                    }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def start_agent(self, agent_id: str) -> Dict[str, Any]:
        """
        Start an agent (registered/stopped → initializing → active).
        Also starts dependencies first.
        """
        agents = self._load_agents()

        if agent_id not in agents:
            return {"success": False, "error": f"Agent {agent_id} not found"}

        agent = agents[agent_id]

        # Start dependencies first
        started_deps = []
        for dep_id in agent.dependencies:
            if dep_id in agents:
                dep = agents[dep_id]
                if dep.state != AgentState.ACTIVE:
                    dep_result = self.start_agent(dep_id)
                    if dep_result.get("success"):
                        started_deps.append(dep_id)
                    else:
                        return {
                            "success": False,
                            "error": f"Failed to start dependency {dep_id}: {dep_result.get('error')}"
                        }

        # Transition through states
        if agent.state in [AgentState.REGISTERED, AgentState.STOPPED]:
            self._transition_state(agent_id, AgentState.INITIALIZING)

        # Simulate initialization (in real impl, this would load resources)
        result = self._transition_state(agent_id, AgentState.ACTIVE)

        if result.get("success"):
            result["started_dependencies"] = started_deps
            result["message"] = f"Agent {agent_id} is now active"

        return result

    def stop_agent(self, agent_id: str, stop_dependents: bool = False) -> Dict[str, Any]:
        """
        Stop an agent (active/paused → stopped).

        Args:
            agent_id: Agent to stop
            stop_dependents: Also stop agents that depend on this one
        """
        agents = self._load_agents()

        if agent_id not in agents:
            return {"success": False, "error": f"Agent {agent_id} not found"}

        # Find dependents
        dependents = [
            a.agent_id for a in agents.values()
            if agent_id in a.dependencies and a.state == AgentState.ACTIVE
        ]

        if dependents and not stop_dependents:
            return {
                "success": False,
                "error": f"Cannot stop: active dependents {dependents}. Use stop_dependents=True"
            }

        # Stop dependents first
        stopped_deps = []
        for dep_id in dependents:
            result = self.stop_agent(dep_id, stop_dependents=True)
            if result.get("success"):
                stopped_deps.append(dep_id)

        result = self._transition_state(agent_id, AgentState.STOPPED)

        if result.get("success"):
            result["stopped_dependents"] = stopped_deps
            result["message"] = f"Agent {agent_id} stopped"

        return result

    def pause_agent(self, agent_id: str) -> Dict[str, Any]:
        """Pause an active agent (won't receive new requests)."""
        return self._transition_state(agent_id, AgentState.PAUSED)

    def resume_agent(self, agent_id: str) -> Dict[str, Any]:
        """Resume a paused agent."""
        return self._transition_state(agent_id, AgentState.ACTIVE)

    def set_maintenance(self, agent_id: str, reason: Optional[str] = None) -> Dict[str, Any]:
        """Put agent in maintenance mode."""
        result = self._transition_state(agent_id, AgentState.MAINTENANCE)
        if result.get("success") and reason:
            result["reason"] = reason
        return result

    def report_error(self, agent_id: str, error: str) -> Dict[str, Any]:
        """Report an error for an agent."""
        return self._transition_state(agent_id, AgentState.ERROR, reason=error)

    def reset_agent(self, agent_id: str) -> Dict[str, Any]:
        """Reset an agent from error state (stop → start)."""
        agents = self._load_agents()

        if agent_id not in agents:
            return {"success": False, "error": f"Agent {agent_id} not found"}

        agent = agents[agent_id]

        if agent.state != AgentState.ERROR:
            return {
                "success": False,
                "error": f"Agent not in error state (current: {agent.state.value})"
            }

        # Clear error count and restart
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE jarvis_specialist_agents
                        SET error_count = 0, last_error = NULL, state = %s, updated_at = NOW()
                        WHERE agent_id = %s
                    """, (AgentState.STOPPED.value, agent_id))
                    conn.commit()

            self._cache_time = None
            return self.start_agent(agent_id)

        except Exception as e:
            return {"success": False, "error": str(e)}

    # =========================================================================
    # Health & Discovery
    # =========================================================================

    def get_agent(self, agent_id: str) -> Optional[RegisteredAgent]:
        """Get a specific agent."""
        agents = self._load_agents()
        return agents.get(agent_id)

    def list_agents(
        self,
        domain: Optional[str] = None,
        state: Optional[AgentState] = None,
        include_inactive: bool = False
    ) -> List[RegisteredAgent]:
        """List registered agents with optional filtering."""
        agents = self._load_agents()
        result = list(agents.values())

        if domain:
            result = [a for a in result if a.domain == domain]

        if state:
            result = [a for a in result if a.state == state]
        elif not include_inactive:
            result = [a for a in result if a.state in [AgentState.ACTIVE, AgentState.PAUSED]]

        return result

    def get_active_agents(self) -> List[RegisteredAgent]:
        """Get all active agents."""
        return self.list_agents(state=AgentState.ACTIVE)

    def health_check(self, agent_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Run health check on one or all agents.

        Returns health status with:
        - State
        - Error count
        - Last error
        - Dependencies status
        """
        agents = self._load_agents(force=True)

        if agent_id:
            if agent_id not in agents:
                return {"success": False, "error": f"Agent {agent_id} not found"}

            agent = agents[agent_id]

            # Check dependencies
            dep_status = {}
            for dep_id in agent.dependencies:
                if dep_id in agents:
                    dep = agents[dep_id]
                    dep_status[dep_id] = {
                        "state": dep.state.value,
                        "healthy": dep.state == AgentState.ACTIVE
                    }
                else:
                    dep_status[dep_id] = {"state": "missing", "healthy": False}

            all_deps_healthy = all(d["healthy"] for d in dep_status.values())

            # Update health check timestamp
            try:
                with get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            UPDATE jarvis_specialist_agents
                            SET last_health_check = NOW()
                            WHERE agent_id = %s
                        """, (agent_id,))
                        conn.commit()
            except:
                pass

            return {
                "success": True,
                "agent_id": agent_id,
                "state": agent.state.value,
                "healthy": agent.state == AgentState.ACTIVE and all_deps_healthy,
                "error_count": agent.health.error_count if agent.health else 0,
                "last_error": agent.health.last_error if agent.health else None,
                "dependencies": dep_status,
                "dependencies_healthy": all_deps_healthy,
                "last_activated": agent.last_activated_at.isoformat() if agent.last_activated_at else None
            }
        else:
            # Check all agents
            results = []
            healthy_count = 0

            for aid, agent in agents.items():
                check = self.health_check(aid)
                results.append({
                    "agent_id": aid,
                    "healthy": check.get("healthy", False),
                    "state": agent.state.value
                })
                if check.get("healthy"):
                    healthy_count += 1

            return {
                "success": True,
                "total": len(agents),
                "healthy": healthy_count,
                "unhealthy": len(agents) - healthy_count,
                "agents": results
            }

    def update_config(
        self,
        agent_id: str,
        tools: Optional[List[str]] = None,
        identity_extension: Optional[Dict[str, Any]] = None,
        confidence_threshold: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Update agent configuration at runtime.

        Changes take effect after cache refresh (2 minutes) or force reload.
        """
        agents = self._load_agents()

        if agent_id not in agents:
            return {"success": False, "error": f"Agent {agent_id} not found"}

        updates = []
        params = []

        if tools is not None:
            updates.append("tools = %s")
            params.append(json.dumps(tools))

        if identity_extension is not None:
            updates.append("identity_extension = %s")
            params.append(json.dumps(identity_extension))

        if confidence_threshold is not None:
            updates.append("confidence_threshold = %s")
            params.append(confidence_threshold)

        if not updates:
            return {"success": False, "error": "No updates provided"}

        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    query = f"""
                        UPDATE jarvis_specialist_agents
                        SET {', '.join(updates)}, updated_at = NOW()
                        WHERE agent_id = %s
                    """
                    params.append(agent_id)
                    cur.execute(query, tuple(params))
                    conn.commit()

                    self._cache_time = None

                    return {
                        "success": True,
                        "agent_id": agent_id,
                        "updated_fields": [u.split(" = ")[0] for u in updates],
                        "message": "Configuration updated"
                    }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_registry_stats(self) -> Dict[str, Any]:
        """Get overall registry statistics."""
        agents = self._load_agents()

        by_state = {}
        by_domain = {}

        for agent in agents.values():
            state = agent.state.value
            by_state[state] = by_state.get(state, 0) + 1

            domain = agent.domain
            by_domain[domain] = by_domain.get(domain, 0) + 1

        total_activations = sum(a.activation_count for a in agents.values())

        return {
            "success": True,
            "total_agents": len(agents),
            "by_state": by_state,
            "by_domain": by_domain,
            "total_activations": total_activations,
            "agents": [
                {
                    "agent_id": a.agent_id,
                    "domain": a.domain,
                    "state": a.state.value,
                    "activations": a.activation_count
                }
                for a in sorted(agents.values(), key=lambda x: -x.activation_count)
            ]
        }


# Singleton
_service: Optional[AgentRegistryService] = None


def get_agent_registry_service() -> AgentRegistryService:
    """Get or create agent registry service singleton."""
    global _service
    if _service is None:
        _service = AgentRegistryService()
    return _service
