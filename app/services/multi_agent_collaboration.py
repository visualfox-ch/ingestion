"""
Multi-Agent Collaboration Service - Phase 22A-08

Enables multiple specialist agents to collaborate on complex tasks:
- Parallel agent execution
- Result aggregation and synthesis
- Cross-agent context sharing
- Collaboration tracking and learning
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Callable
from datetime import datetime
from enum import Enum
import asyncio
import json
import time

from ..observability import get_logger, log_with_context
from ..postgres_state import get_conn

logger = get_logger("jarvis.multi_agent")


class CollaborationType(str, Enum):
    """Types of multi-agent collaboration."""
    PARALLEL = "parallel"      # All agents work independently, results merged
    SEQUENTIAL = "sequential"  # Agents build on each other's output
    PRIMARY_SECONDARY = "primary_secondary"  # One leads, others support


@dataclass
class AgentResult:
    """Result from a single agent."""
    agent_name: str
    success: bool
    content: str
    confidence: float
    tools_used: List[str] = field(default_factory=list)
    execution_time_ms: int = 0
    error: Optional[str] = None


class MultiAgentCollaborationService:
    """
    Coordinates multi-agent collaboration on complex tasks.
    """

    def __init__(self):
        self._ensure_tables()
        self._agent_handlers: Dict[str, Callable] = {}

    def _ensure_tables(self):
        """Ensure collaboration tables exist."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS jarvis_collaborations (
                            id SERIAL PRIMARY KEY,
                            collaboration_type VARCHAR(30) NOT NULL,
                            agents JSONB NOT NULL,
                            original_query TEXT,
                            synthesized_response TEXT,
                            total_time_ms INTEGER,
                            success BOOLEAN DEFAULT TRUE,
                            created_at TIMESTAMP DEFAULT NOW(),
                            completed_at TIMESTAMP
                        )
                    """)

                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS jarvis_collaboration_results (
                            id SERIAL PRIMARY KEY,
                            collaboration_id INTEGER REFERENCES jarvis_collaborations(id),
                            agent_name VARCHAR(50) NOT NULL,
                            success BOOLEAN DEFAULT TRUE,
                            content TEXT,
                            confidence REAL,
                            tools_used JSONB DEFAULT '[]',
                            execution_time_ms INTEGER,
                            error TEXT,
                            created_at TIMESTAMP DEFAULT NOW()
                        )
                    """)

                    cur.execute("""
                        CREATE INDEX IF NOT EXISTS idx_collaborations_type
                        ON jarvis_collaborations(collaboration_type)
                    """)

                    conn.commit()
        except Exception as e:
            log_with_context(logger, "debug", "Table creation failed", error=str(e))

    def register_agent_handler(self, agent_name: str, handler: Callable):
        """Register a handler function for an agent."""
        self._agent_handlers[agent_name] = handler

    async def execute_collaboration(
        self,
        query: str,
        agents: List[str],
        collaboration_type: CollaborationType = CollaborationType.PARALLEL,
        context: Optional[Dict[str, Any]] = None,
        timeout_ms: int = 60000
    ) -> Dict[str, Any]:
        """Execute a multi-agent collaboration."""
        start_time = time.time()
        context = context or {}

        collab_id = self._create_collaboration(query, agents, collaboration_type)

        try:
            if collaboration_type == CollaborationType.PARALLEL:
                results = await self._execute_parallel(query, agents, context, timeout_ms)
            elif collaboration_type == CollaborationType.SEQUENTIAL:
                results = await self._execute_sequential(query, agents, context, timeout_ms)
            else:
                results = await self._execute_primary_secondary(query, agents, context, timeout_ms)

            for result in results:
                self._store_result(collab_id, result)

            synthesized = self._synthesize_results(results, collaboration_type)
            total_time = int((time.time() - start_time) * 1000)
            self._complete_collaboration(collab_id, synthesized, total_time, True)

            return {
                "success": True,
                "collaboration_id": collab_id,
                "collaboration_type": collaboration_type.value,
                "agents_involved": agents,
                "synthesized_response": synthesized,
                "agent_results": [
                    {
                        "agent": r.agent_name,
                        "success": r.success,
                        "confidence": r.confidence,
                        "time_ms": r.execution_time_ms
                    }
                    for r in results
                ],
                "total_time_ms": total_time
            }

        except Exception as e:
            total_time = int((time.time() - start_time) * 1000)
            self._complete_collaboration(collab_id, None, total_time, False)
            return {"success": False, "error": str(e), "total_time_ms": total_time}

    async def _execute_parallel(
        self, query: str, agents: List[str], context: Dict[str, Any], timeout_ms: int
    ) -> List[AgentResult]:
        """Execute all agents in parallel."""
        tasks = [
            self._execute_agent(agent, query, context, timeout_ms // len(agents))
            for agent in agents
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        return [
            r if isinstance(r, AgentResult) else AgentResult(
                agent_name=agents[i], success=False, content="", confidence=0.0, error=str(r)
            )
            for i, r in enumerate(results)
        ]

    async def _execute_sequential(
        self, query: str, agents: List[str], context: Dict[str, Any], timeout_ms: int
    ) -> List[AgentResult]:
        """Execute agents sequentially, each building on previous."""
        results = []
        accumulated = dict(context)

        for agent in agents:
            result = await self._execute_agent(agent, query, accumulated, timeout_ms // len(agents))
            results.append(result)
            if result.success:
                accumulated[f"from_{agent}"] = {"content": result.content, "confidence": result.confidence}

        return results

    async def _execute_primary_secondary(
        self, query: str, agents: List[str], context: Dict[str, Any], timeout_ms: int
    ) -> List[AgentResult]:
        """Execute primary agent first, then secondaries."""
        if not agents:
            return []

        results = []
        primary_result = await self._execute_agent(agents[0], query, context, timeout_ms // 2)
        results.append(primary_result)

        if primary_result.success and len(agents) > 1:
            support_ctx = dict(context)
            support_ctx["primary_response"] = {"agent": agents[0], "content": primary_result.content}

            secondary_tasks = [
                self._execute_agent(agent, query, support_ctx, timeout_ms // 4)
                for agent in agents[1:]
            ]
            secondary_results = await asyncio.gather(*secondary_tasks, return_exceptions=True)

            for i, r in enumerate(secondary_results):
                if isinstance(r, AgentResult):
                    results.append(r)
                else:
                    results.append(AgentResult(
                        agent_name=agents[1 + i], success=False, content="", confidence=0.0, error=str(r)
                    ))

        return results

    async def _execute_agent(
        self, agent_name: str, query: str, context: Dict[str, Any], timeout_ms: int
    ) -> AgentResult:
        """Execute a single agent."""
        start = time.time()

        if agent_name in self._agent_handlers:
            try:
                handler = self._agent_handlers[agent_name]
                result = await asyncio.wait_for(handler(query, context), timeout=timeout_ms / 1000)
                return AgentResult(
                    agent_name=agent_name,
                    success=True,
                    content=result.get("content", str(result)),
                    confidence=result.get("confidence", 0.7),
                    tools_used=result.get("tools_used", []),
                    execution_time_ms=int((time.time() - start) * 1000)
                )
            except Exception as e:
                return AgentResult(
                    agent_name=agent_name, success=False, content="", confidence=0.0,
                    error=str(e), execution_time_ms=int((time.time() - start) * 1000)
                )
        else:
            # Placeholder response
            return AgentResult(
                agent_name=agent_name, success=True,
                content=f"[{agent_name}] processed: {query[:50]}...",
                confidence=0.6, execution_time_ms=int((time.time() - start) * 1000)
            )

    def _synthesize_results(self, results: List[AgentResult], collab_type: CollaborationType) -> str:
        """Synthesize results from multiple agents."""
        successful = [r for r in results if r.success]
        if not successful:
            return "No successful agent responses."
        if len(successful) == 1:
            return successful[0].content

        successful.sort(key=lambda r: r.confidence, reverse=True)

        if collab_type == CollaborationType.PRIMARY_SECONDARY:
            primary = successful[0].content
            support = [f"[{r.agent_name}]: {r.content[:100]}" for r in successful[1:2] if r.confidence >= 0.5]
            if support:
                primary += "\n\n**Additional:** " + " | ".join(support)
            return primary
        else:
            return successful[0].content

    def _create_collaboration(self, query: str, agents: List[str], collab_type: CollaborationType) -> int:
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO jarvis_collaborations (collaboration_type, agents, original_query)
                        VALUES (%s, %s, %s) RETURNING id
                    """, (collab_type.value, json.dumps(agents), query))
                    collab_id = cur.fetchone()["id"]
                    conn.commit()
                    return collab_id
        except Exception:
            return 0

    def _store_result(self, collab_id: int, result: AgentResult):
        if collab_id == 0:
            return
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO jarvis_collaboration_results
                        (collaboration_id, agent_name, success, content, confidence, tools_used, execution_time_ms, error)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """, (collab_id, result.agent_name, result.success, result.content,
                          result.confidence, json.dumps(result.tools_used), result.execution_time_ms, result.error))
                    conn.commit()
        except Exception:
            pass

    def _complete_collaboration(self, collab_id: int, synthesized: Optional[str], total_time: int, success: bool):
        if collab_id == 0:
            return
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE jarvis_collaborations
                        SET synthesized_response = %s, total_time_ms = %s, success = %s, completed_at = NOW()
                        WHERE id = %s
                    """, (synthesized, total_time, success, collab_id))
                    conn.commit()
        except Exception:
            pass

    def get_collaboration_stats(self, days: int = 7) -> Dict[str, Any]:
        """Get collaboration statistics."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT collaboration_type, COUNT(*) as count,
                               AVG(total_time_ms) as avg_time,
                               SUM(CASE WHEN success THEN 1 ELSE 0 END) as successes
                        FROM jarvis_collaborations
                        WHERE created_at > NOW() - INTERVAL '%s days'
                        GROUP BY collaboration_type
                    """, (days,))
                    rows = cur.fetchall()
                    by_type = {
                        row["collaboration_type"]: {
                            "count": row["count"],
                            "avg_time_ms": round(row["avg_time"] or 0),
                            "success_rate": round(row["successes"] / row["count"] * 100) if row["count"] else 0
                        }
                        for row in rows
                    }
                    return {"success": True, "period_days": days, "by_type": by_type}
        except Exception as e:
            return {"success": False, "error": str(e)}


def execute_collaboration_sync(
    query: str, agents: List[str],
    collaboration_type: CollaborationType = CollaborationType.PARALLEL,
    context: Optional[Dict[str, Any]] = None, timeout_ms: int = 60000
) -> Dict[str, Any]:
    """Synchronous wrapper for collaboration execution."""
    service = get_multi_agent_collaboration_service()
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(
            service.execute_collaboration(query, agents, collaboration_type, context, timeout_ms)
        )
    finally:
        loop.close()


_service: Optional[MultiAgentCollaborationService] = None


def get_multi_agent_collaboration_service() -> MultiAgentCollaborationService:
    global _service
    if _service is None:
        _service = MultiAgentCollaborationService()
    return _service
