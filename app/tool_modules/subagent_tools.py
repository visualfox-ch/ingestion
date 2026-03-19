"""
Subagent Tools - Multi-Agent Delegation Framework

Extracted from tools.py as part of T006 Main/Tools Split.
"""

from typing import Dict, Any
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# TOOL DEFINITIONS
# =============================================================================

SUBAGENT_TOOLS = [
    {
        "name": "delegate_to_subagent",
        "description": "Delegate a task to a specialized sub-agent. Each agent has different strengths:\n- ollama: Local LLM (free, fast) - for summaries, formatting, simple tasks\n- openai: GPT-4o (vision, reasoning) - for complex analysis, images\n- anthropic: Claude (long context) - for code review, deep analysis\n- perplexity: Web search - for current info, research, fact-checking\nReturns task_id for async tracking or result if sync=true.",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "enum": ["ollama", "openai", "anthropic", "perplexity"],
                    "description": "Sub-agent: ollama (local), openai (GPT-4), anthropic (Claude), perplexity (web search)",
                    "default": "ollama"
                },
                "instructions": {
                    "type": "string",
                    "description": "Clear task instructions for the sub-agent"
                },
                "input_text": {
                    "type": "string",
                    "description": "Input text for the task"
                },
                "context": {
                    "type": "string",
                    "description": "Additional context"
                },
                "tools": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tools to enable for the sub-agent"
                },
                "sync": {
                    "type": "boolean",
                    "description": "Wait for result (true) or return task_id (false)",
                    "default": False
                }
            },
            "required": ["instructions"]
        }
    },
    {
        "name": "get_subagent_result",
        "description": "Get the result of a delegated sub-agent task. Use after delegate_to_subagent with sync=false.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Sub-agent task ID"
                }
            },
            "required": ["task_id"]
        }
    },
    {
        "name": "list_subagents",
        "description": "List available sub-agents and their capabilities.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
]


# =============================================================================
# TOOL IMPLEMENTATIONS
# =============================================================================

def tool_delegate_to_subagent(**kwargs) -> Dict[str, Any]:
    """
    Delegate a task to a sub-agent with tool access.
    Sub-agents can use tools like search_kb, read_file, calculate, etc.
    """
    try:
        from ..subagents import get_registry, SubAgentTask
        from ..observability import log_with_context
        from .. import metrics
        import asyncio

        agent_id = kwargs.get("agent_id", "ollama")
        instructions = kwargs.get("instructions")
        input_text = kwargs.get("input_text")
        context = kwargs.get("context")
        tools = kwargs.get("tools", [])
        sync = kwargs.get("sync", False)

        log_with_context(
            logger,
            "info",
            "Delegating task to subagent",
            agent_id=agent_id,
            sync=sync,
            tools_enabled=tools,
        )

        if not instructions:
            return {"error": "instructions is required"}

        registry = get_registry()
        agent = registry.get(agent_id)

        if not agent:
            return {"error": f"Agent not found: {agent_id}"}

        # Create task
        task = SubAgentTask(
            task_id=SubAgentTask.generate_id(agent_id),
            agent_id=agent_id,
            instructions=instructions,
            created_at=datetime.now().isoformat(),
            input_text=input_text,
            context=context,
            tools_enabled=tools,
        )

        metrics.inc("tool_delegate_to_subagent")

        if sync:
            # Synchronous execution
            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(agent.execute(task))
            finally:
                loop.close()

            return {
                "status": result.status,
                "task_id": result.task_id,
                "result": result.result,
                "error": result.error,
                "tool_calls": len(result.tool_calls_made),
                "execution_time_ms": round(result.execution_time_ms, 2),
                "model_used": result.model_used,
            }
        else:
            # Async - save to queue
            from ..routers.subagent_router import _save_task, SUBAGENT_QUEUE_PENDING

            _save_task(task, SUBAGENT_QUEUE_PENDING)

            return {
                "status": "queued",
                "task_id": task.task_id,
                "agent_id": agent_id,
                "tools_enabled": tools,
                "message": "Task queued. Use get_subagent_result to check status."
            }

    except ImportError:
        return {"error": "Sub-agent framework not available"}
    except Exception as e:
        logger.warning(f"Delegate to subagent failed: {e}")
        return {"error": str(e)}


def tool_get_subagent_result(**kwargs) -> Dict[str, Any]:
    """
    Get the result of a delegated sub-agent task.
    """
    try:
        from ..routers.subagent_router import _load_task
        from .. import metrics

        task_id = kwargs.get("task_id")
        if not task_id:
            return {"error": "task_id is required"}

        task = _load_task(task_id)
        if not task:
            return {"error": f"Task not found: {task_id}"}

        metrics.inc("tool_get_subagent_result")

        return {
            "task_id": task.task_id,
            "agent_id": task.agent_id,
            "status": task.status.value,
            "result": task.result,
            "error": task.error,
            "tool_calls_made": task.tool_calls_made,
            "execution_time_ms": task.execution_time_ms,
            "created_at": task.created_at,
            "completed_at": task.completed_at,
        }

    except ImportError:
        return {"error": "Sub-agent framework not available"}
    except Exception as e:
        logger.warning(f"Get subagent result failed: {e}")
        return {"error": str(e)}


def tool_list_subagents(**kwargs) -> Dict[str, Any]:
    """
    List available sub-agents and their tools.
    """
    try:
        from ..subagents import get_registry
        from .. import metrics

        registry = get_registry()
        agents = registry.list_agents()

        metrics.inc("tool_list_subagents")

        return {
            "agents": agents,
            "count": len(agents),
        }

    except ImportError:
        return {"error": "Sub-agent framework not available"}
    except Exception as e:
        logger.warning(f"List subagents failed: {e}")
        return {"error": str(e)}
