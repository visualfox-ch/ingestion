"""
Ollama Tools - Local LLM Delegation & Execution

Extracted from tools.py as part of T006 Main/Tools Split.
"""

from typing import Dict, Any
import json
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# TOOL DEFINITIONS
# =============================================================================

OLLAMA_TOOLS = [
    {
        "name": "delegate_ollama_task",
        "description": "Delegate a task to local Ollama via the queue. Use for summarization, extraction, translation, classification, formatting, or simple generation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_type": {
                    "type": "string",
                    "enum": ["summarize", "extract", "translate", "classify", "generate", "analyze", "format"],
                    "description": "Type of task to run on Ollama"
                },
                "instructions": {
                    "type": "string",
                    "description": "Clear instructions for the task"
                },
                "input_text": {
                    "type": "string",
                    "description": "Direct text input (mutually exclusive with input_path)"
                },
                "input_path": {
                    "type": "string",
                    "description": "Path to input file (mutually exclusive with input_text)"
                },
                "output_path": {
                    "type": "string",
                    "description": "Optional path to write the result"
                },
                "model": {
                    "type": "string",
                    "description": "Preferred Ollama model (optional)"
                },
                "max_tokens": {
                    "type": "integer",
                    "description": "Max tokens for the response",
                    "default": 1000
                },
                "temperature": {
                    "type": "number",
                    "description": "Sampling temperature",
                    "default": 0.3
                },
                "language": {
                    "type": "string",
                    "description": "Output language",
                    "default": "de"
                },
                "output_format": {
                    "type": "string",
                    "enum": ["text", "json", "markdown"],
                    "default": "text"
                },
                "callback_url": {
                    "type": "string",
                    "description": "Optional callback URL for async notification"
                }
            },
            "required": ["task_type", "instructions"]
        }
    },
    {
        "name": "get_ollama_task_status",
        "description": "Get status for a queued Ollama task by task_id.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Ollama task ID"
                }
            },
            "required": ["task_id"]
        }
    },
    {
        "name": "get_ollama_queue_status",
        "description": "Get a summary of pending and processing Ollama tasks.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Max tasks to return per queue",
                    "default": 10
                }
            }
        }
    },
    {
        "name": "cancel_ollama_task",
        "description": "Cancel a queued Ollama task if it is still pending.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Ollama task id to cancel"
                }
            },
            "required": ["task_id"]
        }
    },
    {
        "name": "get_ollama_callback_result",
        "description": "Get the result of a completed async Ollama task. Use after delegate_ollama_task to retrieve the result once the task has been processed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Ollama task ID to get result for"
                },
                "recent_only": {
                    "type": "boolean",
                    "description": "If true and no task_id provided, return recent callbacks"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max number of recent callbacks to return",
                    "default": 10
                }
            }
        }
    },
    {
        "name": "ask_ollama",
        "description": "Ask local Ollama LLM a question and get an answer. SAVES API TOKENS! Use as sub-assistant for: summarization, translation, text analysis, format conversion, simple Q&A, classification. Ollama runs locally and is FREE.",
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "The question or task for Ollama. Be clear and specific."
                },
                "task_type": {
                    "type": "string",
                    "enum": ["summarize", "translate", "analyze", "classify", "format", "generate", "extract"],
                    "description": "Type of task (helps select best model)",
                    "default": "analyze"
                },
                "system_prompt": {
                    "type": "string",
                    "description": "Optional custom system prompt to override default assistant behavior"
                },
                "max_tokens": {
                    "type": "integer",
                    "description": "Max response tokens (default: 1500)"
                }
            },
            "required": ["prompt"]
        }
    },
    {
        "name": "ollama_python",
        "description": "Generate and execute Python code via local Ollama. SAVES API TOKENS by using local LLM for code generation. Use this for calculations, data processing, analysis, formatting, or any task that can be solved with Python code.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_description": {
                    "type": "string",
                    "description": "Natural language description of what to compute or do. Be specific about expected output format."
                },
                "context": {
                    "type": "string",
                    "description": "Optional additional context or data to use in the code"
                },
                "model": {
                    "type": "string",
                    "description": "Specific Ollama model (default: auto-select best coding model)"
                }
            },
            "required": ["task_description"]
        }
    },
]


# =============================================================================
# TOOL IMPLEMENTATIONS
# =============================================================================

def tool_delegate_ollama_task(**kwargs) -> Dict[str, Any]:
    """Queue a task for local Ollama execution."""
    try:
        from .. import ollama_delegation
        from ..observability import log_with_context
        from .. import metrics

        task_type = kwargs.get("task_type")
        instructions = kwargs.get("instructions")
        input_text = kwargs.get("input_text")
        input_path = kwargs.get("input_path")
        output_path = kwargs.get("output_path")
        model = kwargs.get("model")
        max_tokens = kwargs.get("max_tokens", 1000)
        temperature = kwargs.get("temperature", 0.3)
        language = kwargs.get("language", "de")
        output_format = kwargs.get("output_format", "text")
        callback_url = kwargs.get("callback_url")

        log_with_context(
            logger,
            "info",
            "Delegating task to Ollama",
            task_type=task_type,
            model=model,
        )

        task = ollama_delegation.create_task(
            task_type=ollama_delegation.TaskType(task_type),
            instructions=instructions,
            input_text=input_text,
            input_path=input_path,
            output_path=output_path,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            language=language,
            output_format=output_format,
            callback_url=callback_url,
        )

        metrics.inc("tool_delegate_ollama_task")
        return {
            "status": "queued",
            "task_id": task.task_id,
            "task_type": task.task_type.value,
            "model": task.model,
        }
    except Exception as e:
        logger.warning(f"Ollama delegation failed: {e}")
        return {"error": str(e)}


def tool_get_ollama_task_status(**kwargs) -> Dict[str, Any]:
    """Return status for a queued Ollama task."""
    try:
        from .. import ollama_delegation
        from .. import metrics

        task_id = kwargs.get("task_id")
        status = ollama_delegation.get_task_status(task_id)
        metrics.inc("tool_get_ollama_task_status")
        if not status:
            return {"error": "task_not_found"}
        return status
    except Exception as e:
        logger.warning(f"Ollama status failed: {e}")
        return {"error": str(e)}


def tool_get_ollama_queue_status(**kwargs) -> Dict[str, Any]:
    """Return a summary of pending and processing Ollama tasks."""
    try:
        from ..ollama_delegation import QUEUE_PENDING, QUEUE_PROCESSING
        from .. import metrics

        limit = kwargs.get("limit", 10)
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = 10
        limit = max(1, min(limit, 50))

        pending_files = sorted(QUEUE_PENDING.glob("*.json"), key=lambda p: p.stat().st_mtime)
        processing_files = sorted(QUEUE_PROCESSING.glob("*.json"), key=lambda p: p.stat().st_mtime)

        pending_tasks = []
        for p in pending_files[:limit]:
            try:
                with open(p) as f:
                    data = json.load(f)
                pending_tasks.append({
                    "task_id": data.get("task_id"),
                    "task_type": data.get("task_type"),
                    "created_at": data.get("created_at"),
                })
            except Exception:
                continue

        processing_tasks = []
        for p in processing_files[:limit]:
            try:
                with open(p) as f:
                    data = json.load(f)
                processing_tasks.append({
                    "task_id": data.get("task_id"),
                    "task_type": data.get("task_type"),
                    "started_at": data.get("started_at"),
                })
            except Exception:
                continue

        metrics.inc("tool_get_ollama_queue_status")
        return {
            "pending_count": len(pending_files),
            "processing_count": len(processing_files),
            "pending_tasks": pending_tasks,
            "processing_tasks": processing_tasks,
        }
    except Exception as e:
        logger.warning(f"Ollama queue status failed: {e}")
        return {"error": str(e)}


def tool_cancel_ollama_task(**kwargs) -> Dict[str, Any]:
    """Cancel an Ollama task if it is still pending."""
    try:
        from ..ollama_delegation import QUEUE_PENDING, OllamaTask, TaskStatus
        from .. import metrics

        task_id = kwargs.get("task_id")
        if not task_id:
            return {"error": "task_id is required"}

        task = OllamaTask.load(task_id)
        if not task:
            return {"error": "task_not_found", "task_id": task_id}

        if task.status != TaskStatus.PENDING:
            return {
                "status": "not_cancelable",
                "task_id": task_id,
                "current_status": task.status.value,
            }

        pending_path = QUEUE_PENDING / f"{task_id}.json"
        if pending_path.exists():
            pending_path.unlink()
            metrics.inc("tool_cancel_ollama_task")
            return {"status": "canceled", "task_id": task_id}

        return {"status": "not_found", "task_id": task_id}
    except Exception as e:
        logger.warning(f"Ollama cancel failed: {e}")
        return {"error": str(e)}


def tool_get_ollama_callback_result(**kwargs) -> Dict[str, Any]:
    """Get result of a completed async Ollama task."""
    try:
        from ..routers.ollama_callback_router import CALLBACK_HISTORY, CALLBACK_STORE
        from .. import metrics

        task_id = kwargs.get("task_id")
        recent_only = kwargs.get("recent_only", False)
        limit = kwargs.get("limit", 10)

        if task_id:
            # Look for specific task
            for cb in CALLBACK_HISTORY:
                if cb["task_id"] == task_id:
                    metrics.inc("tool_get_ollama_callback_result")
                    return {"found": True, "callback": cb, "source": "memory"}

            # Check file store
            callback_file = CALLBACK_STORE / f"{task_id}.json"
            if callback_file.exists():
                with open(callback_file) as f:
                    metrics.inc("tool_get_ollama_callback_result")
                    return {"found": True, "callback": json.load(f), "source": "file"}

            return {"found": False, "task_id": task_id}

        elif recent_only:
            # Return recent callbacks
            metrics.inc("tool_get_ollama_callback_result")
            return {
                "recent_callbacks": CALLBACK_HISTORY[:limit],
                "count": len(CALLBACK_HISTORY[:limit])
            }

        return {"error": "Provide task_id or set recent_only=true"}

    except Exception as e:
        logger.warning(f"Get callback result failed: {e}")
        return {"error": str(e)}


def tool_ask_ollama(**kwargs) -> Dict[str, Any]:
    """
    Ask Ollama a question and get an answer.
    Jarvis's free local sub-assistant for simple tasks.
    """
    try:
        from .. import ollama_python_bridge
        from .. import metrics

        prompt = kwargs.get("prompt")
        if not prompt:
            return {"error": "prompt is required"}

        task_type = kwargs.get("task_type", "analyze")
        system_prompt = kwargs.get("system_prompt")
        max_tokens = kwargs.get("max_tokens")

        result = ollama_python_bridge.ask_ollama(
            prompt=prompt,
            task_type=task_type,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
        )

        metrics.inc("tool_ask_ollama")

        if result.status == "success":
            return {
                "status": "success",
                "answer": result.answer,
                "model_used": result.model_used,
                "duration_ms": round(result.duration_ms, 1),
                "tokens": {
                    "prompt": result.prompt_tokens,
                    "response": result.response_tokens,
                }
            }
        else:
            return {
                "status": result.status,
                "error": result.error,
                "model_used": result.model_used,
                "duration_ms": round(result.duration_ms, 1),
            }

    except Exception as e:
        logger.error(f"ask_ollama failed: {e}")
        return {"error": str(e)}


def tool_ollama_python(**kwargs) -> Dict[str, Any]:
    """
    Generate and execute Python code via local Ollama.
    Saves API tokens by using local LLM for code generation.
    """
    try:
        from .. import ollama_python_bridge
        from .. import metrics

        task_description = kwargs.get("task_description")
        context = kwargs.get("context")
        model = kwargs.get("model")

        if not task_description:
            return {"error": "task_description is required"}

        result = ollama_python_bridge.generate_and_execute_python(
            task_description=task_description,
            context=context,
            model=model,
            user_id="jarvis_agent",
        )

        metrics.inc("tool_ollama_python")

        # Build response
        response = {
            "status": result.status,
            "model_used": result.model_used,
            "generation_time_ms": round(result.generation_time_ms, 2),
            "total_time_ms": round(result.total_time_ms, 2),
        }

        if result.generated_code:
            response["generated_code"] = result.generated_code

        if result.validation_error:
            response["validation_error"] = result.validation_error

        if result.exec_result:
            response["output"] = result.exec_result.get("stdout", "")
            if result.exec_result.get("stderr"):
                response["stderr"] = result.exec_result["stderr"]
            response["exec_id"] = result.exec_result.get("exec_id")

        return response

    except Exception as e:
        logger.warning(f"Ollama Python failed: {e}")
        return {"error": str(e)}
