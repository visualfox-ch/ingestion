"""
Agent Delegation Service - Phase 22A-09

Enables Jarvis core to delegate subtasks to specialist agents:
- Task decomposition and delegation
- Context handoff to specialists
- Result collection and integration
- Delegation tracking and learning

Flow:
    Complex Query
        |
        v
    [Jarvis Core]
        |
        v
    [Task Decomposer] --> subtasks with domain tags
        |
        v
    [Delegation Manager]
        |
        +---> delegate(subtask_1) --> [FitJarvis]
        |
        +---> delegate(subtask_2) --> [WorkJarvis]
        |
        +---> delegate(subtask_3) --> [CommJarvis]
        |
        v
    [Result Collector]
        |
        v
    [Integrated Response]
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from enum import Enum
import json
import time

from ..observability import get_logger, log_with_context
from ..postgres_state import get_conn

logger = get_logger("jarvis.delegation")


class DelegationStatus(str, Enum):
    """Status of a delegation."""
    PENDING = "pending"
    ACCEPTED = "accepted"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"
    TIMEOUT = "timeout"


class DelegationPriority(str, Enum):
    """Priority levels for delegations."""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


@dataclass
class Subtask:
    """A subtask to delegate."""
    id: str
    description: str
    target_agent: str
    context: Dict[str, Any] = field(default_factory=dict)
    priority: DelegationPriority = DelegationPriority.NORMAL
    timeout_ms: int = 30000
    depends_on: List[str] = field(default_factory=list)


@dataclass
class DelegationResult:
    """Result from a delegated task."""
    subtask_id: str
    agent_name: str
    status: DelegationStatus
    result: Optional[str] = None
    confidence: float = 0.0
    execution_time_ms: int = 0
    error: Optional[str] = None


@dataclass
class DelegationSession:
    """A delegation session with multiple subtasks."""
    id: int
    original_query: str
    subtasks: List[Subtask]
    results: List[DelegationResult] = field(default_factory=list)
    integrated_response: Optional[str] = None
    status: str = "active"


class AgentDelegationService:
    """
    Manages task delegation from Jarvis core to specialist agents.

    Features:
    - Task decomposition into subtasks
    - Delegation to appropriate specialists
    - Dependency handling between subtasks
    - Result integration
    """

    def __init__(self):
        self._ensure_tables()

    def _ensure_tables(self):
        """Ensure delegation tables exist."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS jarvis_delegation_sessions (
                            id SERIAL PRIMARY KEY,
                            original_query TEXT,
                            subtask_count INTEGER DEFAULT 0,
                            completed_count INTEGER DEFAULT 0,
                            integrated_response TEXT,
                            status VARCHAR(30) DEFAULT 'active',
                            total_time_ms INTEGER,
                            created_at TIMESTAMP DEFAULT NOW(),
                            completed_at TIMESTAMP
                        )
                    """)

                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS jarvis_delegations (
                            id SERIAL PRIMARY KEY,
                            session_id INTEGER REFERENCES jarvis_delegation_sessions(id),
                            subtask_id VARCHAR(50) NOT NULL,
                            description TEXT,
                            target_agent VARCHAR(50) NOT NULL,
                            context JSONB DEFAULT '{}',
                            priority VARCHAR(20) DEFAULT 'normal',
                            depends_on JSONB DEFAULT '[]',
                            status VARCHAR(30) DEFAULT 'pending',
                            result TEXT,
                            confidence REAL,
                            execution_time_ms INTEGER,
                            error TEXT,
                            created_at TIMESTAMP DEFAULT NOW(),
                            completed_at TIMESTAMP
                        )
                    """)

                    cur.execute("""
                        CREATE INDEX IF NOT EXISTS idx_delegations_session
                        ON jarvis_delegations(session_id)
                    """)

                    cur.execute("""
                        CREATE INDEX IF NOT EXISTS idx_delegations_status
                        ON jarvis_delegations(status)
                    """)

                    cur.execute("""
                        CREATE INDEX IF NOT EXISTS idx_delegations_agent
                        ON jarvis_delegations(target_agent)
                    """)

                    conn.commit()
        except Exception as e:
            log_with_context(logger, "debug", "Table creation failed", error=str(e))

    def decompose_task(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None
    ) -> List[Subtask]:
        """
        Decompose a complex query into subtasks for delegation.

        Uses domain detection to identify which specialists should handle parts.
        """
        from .agent_routing_service import get_agent_routing_service

        context = context or {}
        subtasks = []

        # Get routing decision to understand domain involvement
        routing_service = get_agent_routing_service()
        classification = routing_service.classify_intent(query, context)

        # Check which domains are relevant (confidence > 0.3)
        relevant_domains = [
            (domain, score)
            for domain, score in classification.confidence_scores.items()
            if score >= 0.3 and domain != "general"
        ]

        # Sort by confidence
        relevant_domains.sort(key=lambda x: x[1], reverse=True)

        if not relevant_domains:
            # No clear domain - return single task for core
            return [Subtask(
                id="task_core",
                description=query,
                target_agent="jarvis_core",
                context=context,
                priority=DelegationPriority.NORMAL
            )]

        # Create subtasks for each relevant domain
        agent_map = {
            "fitness": "fit_jarvis",
            "work": "work_jarvis",
            "communication": "comm_jarvis"
        }

        for i, (domain, confidence) in enumerate(relevant_domains):
            agent = agent_map.get(domain, "jarvis_core")

            # Adjust priority based on confidence
            if confidence >= 0.7:
                priority = DelegationPriority.HIGH
            elif confidence >= 0.5:
                priority = DelegationPriority.NORMAL
            else:
                priority = DelegationPriority.LOW

            subtask = Subtask(
                id=f"task_{domain}_{i}",
                description=f"[{domain.upper()}] {query}",
                target_agent=agent,
                context={
                    **context,
                    "domain": domain,
                    "confidence": confidence,
                    "is_primary": i == 0
                },
                priority=priority
            )
            subtasks.append(subtask)

        return subtasks

    def create_delegation_session(
        self,
        query: str,
        subtasks: List[Subtask]
    ) -> int:
        """Create a new delegation session."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO jarvis_delegation_sessions
                        (original_query, subtask_count, status)
                        VALUES (%s, %s, 'active')
                        RETURNING id
                    """, (query, len(subtasks)))
                    session_id = cur.fetchone()["id"]

                    # Insert subtasks
                    for subtask in subtasks:
                        cur.execute("""
                            INSERT INTO jarvis_delegations
                            (session_id, subtask_id, description, target_agent,
                             context, priority, depends_on, status)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending')
                        """, (
                            session_id,
                            subtask.id,
                            subtask.description,
                            subtask.target_agent,
                            json.dumps(subtask.context),
                            subtask.priority.value,
                            json.dumps(subtask.depends_on)
                        ))

                    conn.commit()
                    return session_id

        except Exception as e:
            log_with_context(logger, "error", "Session creation failed", error=str(e))
            return 0

    def delegate_task(
        self,
        session_id: int,
        subtask_id: str
    ) -> Dict[str, Any]:
        """
        Delegate a specific subtask to its target agent.

        Returns the delegation result.
        """
        start_time = time.time()

        try:
            # Get subtask details
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT subtask_id, description, target_agent, context, priority
                        FROM jarvis_delegations
                        WHERE session_id = %s AND subtask_id = %s
                    """, (session_id, subtask_id))
                    row = cur.fetchone()

                    if not row:
                        return {"success": False, "error": "Subtask not found"}

                    # Mark as in progress
                    cur.execute("""
                        UPDATE jarvis_delegations
                        SET status = 'in_progress'
                        WHERE session_id = %s AND subtask_id = %s
                    """, (session_id, subtask_id))
                    conn.commit()

            target_agent = row["target_agent"]
            description = row["description"]
            context = row["context"] or {}

            # Execute delegation (simulate agent response for now)
            result = self._execute_agent_task(target_agent, description, context)

            execution_time = int((time.time() - start_time) * 1000)

            # Update delegation record
            status = DelegationStatus.COMPLETED if result.get("success") else DelegationStatus.FAILED

            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE jarvis_delegations
                        SET status = %s,
                            result = %s,
                            confidence = %s,
                            execution_time_ms = %s,
                            error = %s,
                            completed_at = NOW()
                        WHERE session_id = %s AND subtask_id = %s
                    """, (
                        status.value,
                        result.get("content"),
                        result.get("confidence", 0.0),
                        execution_time,
                        result.get("error"),
                        session_id,
                        subtask_id
                    ))

                    # Update session completed count
                    cur.execute("""
                        UPDATE jarvis_delegation_sessions
                        SET completed_count = (
                            SELECT COUNT(*) FROM jarvis_delegations
                            WHERE session_id = %s AND status IN ('completed', 'failed')
                        )
                        WHERE id = %s
                    """, (session_id, session_id))

                    conn.commit()

            return {
                "success": result.get("success", False),
                "subtask_id": subtask_id,
                "agent": target_agent,
                "status": status.value,
                "content": result.get("content"),
                "confidence": result.get("confidence", 0.0),
                "execution_time_ms": execution_time
            }

        except Exception as e:
            log_with_context(logger, "error", "Delegation failed", error=str(e))
            return {"success": False, "error": str(e)}

    def _execute_agent_task(
        self,
        agent_name: str,
        task: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute a task via the target agent."""
        # This is a placeholder - in production this would invoke the actual agent
        # For now, return a simulated response

        domain = context.get("domain", "general")
        is_primary = context.get("is_primary", False)

        return {
            "success": True,
            "content": f"[{agent_name}] Processed: {task[:100]}...",
            "confidence": 0.7 if is_primary else 0.5,
            "tools_used": []
        }

    def delegate_all(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Decompose and delegate all subtasks for a query.

        This is the main entry point for delegation.
        """
        start_time = time.time()
        context = context or {}

        # Decompose into subtasks
        subtasks = self.decompose_task(query, context)

        if not subtasks:
            return {
                "success": False,
                "error": "Could not decompose task"
            }

        # Create session
        session_id = self.create_delegation_session(query, subtasks)
        if session_id == 0:
            return {"success": False, "error": "Could not create session"}

        # Delegate each subtask
        results = []
        for subtask in subtasks:
            result = self.delegate_task(session_id, subtask.id)
            results.append(result)

        # Integrate results
        integrated = self._integrate_results(results)

        total_time = int((time.time() - start_time) * 1000)

        # Complete session
        self._complete_session(session_id, integrated, total_time)

        return {
            "success": True,
            "session_id": session_id,
            "subtasks_count": len(subtasks),
            "delegations": results,
            "integrated_response": integrated,
            "total_time_ms": total_time
        }

    def _integrate_results(self, results: List[Dict[str, Any]]) -> str:
        """Integrate results from multiple delegations."""
        successful = [r for r in results if r.get("success")]

        if not successful:
            return "All delegations failed."

        if len(successful) == 1:
            return successful[0].get("content", "")

        # Sort by confidence
        successful.sort(key=lambda r: r.get("confidence", 0), reverse=True)

        # Primary result + supporting info
        primary = successful[0]
        response = primary.get("content", "")

        if len(successful) > 1:
            support = [
                f"[{r.get('agent')}]: {r.get('content', '')[:80]}..."
                for r in successful[1:3]
                if r.get("confidence", 0) >= 0.4
            ]
            if support:
                response += "\n\n**Supporting context:**\n" + "\n".join(support)

        return response

    def _complete_session(
        self,
        session_id: int,
        integrated: str,
        total_time: int
    ):
        """Mark session as completed."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE jarvis_delegation_sessions
                        SET status = 'completed',
                            integrated_response = %s,
                            total_time_ms = %s,
                            completed_at = NOW()
                        WHERE id = %s
                    """, (integrated, total_time, session_id))
                    conn.commit()
        except Exception as e:
            log_with_context(logger, "debug", "Session completion failed", error=str(e))

    def get_session_status(self, session_id: int) -> Dict[str, Any]:
        """Get status of a delegation session."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT id, original_query, subtask_count, completed_count,
                               integrated_response, status, total_time_ms,
                               created_at, completed_at
                        FROM jarvis_delegation_sessions
                        WHERE id = %s
                    """, (session_id,))
                    session = cur.fetchone()

                    if not session:
                        return {"success": False, "error": "Session not found"}

                    cur.execute("""
                        SELECT subtask_id, target_agent, status, confidence,
                               execution_time_ms, error
                        FROM jarvis_delegations
                        WHERE session_id = %s
                        ORDER BY created_at
                    """, (session_id,))
                    delegations = cur.fetchall()

                    return {
                        "success": True,
                        "session_id": session_id,
                        "status": session["status"],
                        "subtask_count": session["subtask_count"],
                        "completed_count": session["completed_count"],
                        "delegations": [
                            {
                                "subtask_id": d["subtask_id"],
                                "agent": d["target_agent"],
                                "status": d["status"],
                                "confidence": d["confidence"],
                                "time_ms": d["execution_time_ms"]
                            }
                            for d in delegations
                        ],
                        "integrated_response": session["integrated_response"],
                        "total_time_ms": session["total_time_ms"]
                    }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_delegation_stats(self, days: int = 7) -> Dict[str, Any]:
        """Get delegation statistics."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    # Session stats
                    cur.execute("""
                        SELECT
                            COUNT(*) as total_sessions,
                            SUM(subtask_count) as total_subtasks,
                            AVG(total_time_ms) as avg_time,
                            SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed
                        FROM jarvis_delegation_sessions
                        WHERE created_at > NOW() - INTERVAL '%s days'
                    """, (days,))
                    session_stats = cur.fetchone()

                    # By agent stats
                    cur.execute("""
                        SELECT
                            target_agent,
                            COUNT(*) as count,
                            AVG(confidence) as avg_confidence,
                            AVG(execution_time_ms) as avg_time
                        FROM jarvis_delegations
                        WHERE created_at > NOW() - INTERVAL '%s days'
                        GROUP BY target_agent
                    """, (days,))
                    by_agent = {
                        row["target_agent"]: {
                            "count": row["count"],
                            "avg_confidence": round(row["avg_confidence"] or 0, 2),
                            "avg_time_ms": round(row["avg_time"] or 0)
                        }
                        for row in cur.fetchall()
                    }

                    return {
                        "success": True,
                        "period_days": days,
                        "total_sessions": session_stats["total_sessions"] or 0,
                        "total_subtasks": session_stats["total_subtasks"] or 0,
                        "completed_sessions": session_stats["completed"] or 0,
                        "avg_time_ms": round(session_stats["avg_time"] or 0),
                        "by_agent": by_agent
                    }

        except Exception as e:
            return {"success": False, "error": str(e)}


# Singleton
_service: Optional[AgentDelegationService] = None


def get_agent_delegation_service() -> AgentDelegationService:
    """Get or create agent delegation service singleton."""
    global _service
    if _service is None:
        _service = AgentDelegationService()
    return _service
