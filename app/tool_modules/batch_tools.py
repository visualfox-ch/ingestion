"""
Batch API Tools (Phase O1).

Multi-Provider Batch Processing for Cost Optimization.
OpenAI: 50% discount, Anthropic: 50% (+ caching → 90%)

Tools:
- submit_batch_job: Create and submit a batch job
- get_batch_status: Check status of a batch job
- retrieve_batch_results: Get results when completed
- list_batch_jobs: List recent batch jobs
- cancel_batch_job: Cancel a pending/in-progress job
"""

import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# Tool Definitions
# =============================================================================

BATCH_TOOLS = [
    {
        "name": "submit_batch_job",
        "description": "Submit a batch job for async processing with 50% cost savings. Use for bulk operations like embeddings, classifications, or summarizations that don't need immediate results.",
        "parameters": {
            "type": "object",
            "properties": {
                "provider": {
                    "type": "string",
                    "enum": ["openai", "anthropic"],
                    "description": "Which provider to use"
                },
                "model": {
                    "type": "string",
                    "description": "Model to use (e.g. 'gpt-4o-mini', 'claude-haiku-4-5')"
                },
                "job_type": {
                    "type": "string",
                    "enum": ["embedding", "classification", "summarization", "verification", "custom"],
                    "description": "Type of batch operation"
                },
                "requests": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "List of requests. Each needs 'custom_id' and provider-specific params (OpenAI: messages, Anthropic: messages+max_tokens)"
                },
                "description": {
                    "type": "string",
                    "description": "Human-readable description of the batch job"
                }
            },
            "required": ["provider", "model", "job_type", "requests"]
        },
        "category": "batch"
    },
    {
        "name": "get_batch_status",
        "description": "Check the status of a batch job. Returns status, progress, and time remaining.",
        "parameters": {
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "string",
                    "description": "The batch job ID (starts with 'batch_')"
                }
            },
            "required": ["job_id"]
        },
        "category": "batch"
    },
    {
        "name": "retrieve_batch_results",
        "description": "Retrieve results of a completed batch job. Only works when status is 'completed'.",
        "parameters": {
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "string",
                    "description": "The batch job ID"
                }
            },
            "required": ["job_id"]
        },
        "category": "batch"
    },
    {
        "name": "list_batch_jobs",
        "description": "List recent batch jobs with their status.",
        "parameters": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["pending", "uploading", "submitted", "in_progress", "completed", "failed", "expired", "cancelled", "all"],
                    "description": "Filter by status (default: 'all')"
                },
                "provider": {
                    "type": "string",
                    "enum": ["openai", "anthropic", "all"],
                    "description": "Filter by provider (default: 'all')"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max jobs to return (default: 20)"
                }
            },
            "required": []
        },
        "category": "batch"
    },
    {
        "name": "cancel_batch_job",
        "description": "Cancel a batch job that hasn't completed yet.",
        "parameters": {
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "string",
                    "description": "The batch job ID to cancel"
                }
            },
            "required": ["job_id"]
        },
        "category": "batch"
    },
    {
        "name": "get_batch_stats",
        "description": "Get batch processing statistics - total jobs, costs, savings by provider.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        },
        "category": "batch"
    },
    {
        "name": "queue_batch_task",
        "description": "Queue a task for batch processing. Tasks are collected and processed together for 50% cost savings.",
        "parameters": {
            "type": "object",
            "properties": {
                "task_type": {
                    "type": "string",
                    "enum": ["learning_extract", "pattern_detect", "summarization", "classification", "custom"],
                    "description": "Type of task to queue"
                },
                "payload": {
                    "type": "object",
                    "description": "Task-specific data. For custom: include 'messages' array"
                },
                "priority": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 10,
                    "description": "Priority 1-10 (higher = more urgent, default 5)"
                }
            },
            "required": ["task_type", "payload"]
        },
        "category": "batch"
    },
    {
        "name": "process_batch_queue",
        "description": "Process all queued tasks of a given type as a batch. Automatically called by scheduler, but can be triggered manually.",
        "parameters": {
            "type": "object",
            "properties": {
                "task_type": {
                    "type": "string",
                    "description": "Type of tasks to process"
                },
                "model": {
                    "type": "string",
                    "description": "Model to use (default: claude-haiku-4-5)"
                },
                "max_batch_size": {
                    "type": "integer",
                    "description": "Max tasks per batch (default: 50)"
                }
            },
            "required": ["task_type"]
        },
        "category": "batch"
    },
    {
        "name": "get_batch_queue_status",
        "description": "Get summary of all queued tasks waiting for batch processing.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        },
        "category": "batch"
    }
]


# =============================================================================
# Tool Handlers
# =============================================================================

def submit_batch_job(
    provider: str,
    model: str,
    job_type: str,
    requests: List[Dict],
    description: Optional[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """Create and submit a batch job."""
    try:
        from app.services.batch_processor import get_batch_processor
        processor = get_batch_processor()

        # Create job
        result = processor.create_job(
            provider=provider,
            model=model,
            job_type=job_type,
            requests=requests,
            description=description
        )

        if not result.get("success"):
            return result

        job_id = result["job_id"]

        # Submit to provider
        submit_result = processor.submit_job(job_id)

        return {
            "success": True,
            "job_id": job_id,
            "provider": provider,
            "model": model,
            "request_count": len(requests),
            "status": submit_result.get("status", "submitted"),
            "provider_batch_id": submit_result.get("provider_batch_id"),
            "message": f"Batch job {job_id} submitted to {provider}. Check status with get_batch_status. Results available within 24h."
        }
    except Exception as e:
        logger.error(f"submit_batch_job failed: {e}")
        return {"success": False, "error": str(e)}


def get_batch_status(job_id: str, **kwargs) -> Dict[str, Any]:
    """Get status of a batch job."""
    try:
        from app.services.batch_processor import get_batch_processor
        processor = get_batch_processor()

        result = processor.get_status(job_id)

        if result.get("error"):
            return {"success": False, "error": result["error"]}

        return {
            "success": True,
            **result
        }
    except Exception as e:
        logger.error(f"get_batch_status failed: {e}")
        return {"success": False, "error": str(e)}


def retrieve_batch_results(job_id: str, **kwargs) -> Dict[str, Any]:
    """Retrieve results of a completed batch job."""
    try:
        from app.services.batch_processor import get_batch_processor
        processor = get_batch_processor()

        result = processor.get_results(job_id)

        if result.get("error"):
            return {"success": False, "error": result["error"]}

        return {
            "success": True,
            **result,
            "message": f"Retrieved {result.get('result_count', 0)} results. Errors: {result.get('error_count', 0)}"
        }
    except Exception as e:
        logger.error(f"retrieve_batch_results failed: {e}")
        return {"success": False, "error": str(e)}


def list_batch_jobs(
    status: str = "all",
    provider: str = "all",
    limit: int = 20,
    **kwargs
) -> Dict[str, Any]:
    """List batch jobs."""
    try:
        from app.services.batch_processor import get_batch_processor
        processor = get_batch_processor()

        jobs = processor.list_jobs(
            status=None if status == "all" else status,
            provider=None if provider == "all" else provider,
            limit=limit
        )

        return {
            "success": True,
            "count": len(jobs),
            "jobs": jobs
        }
    except Exception as e:
        logger.error(f"list_batch_jobs failed: {e}")
        return {"success": False, "error": str(e)}


def cancel_batch_job(job_id: str, **kwargs) -> Dict[str, Any]:
    """Cancel a batch job."""
    try:
        from app.services.batch_processor import get_batch_processor
        processor = get_batch_processor()

        result = processor.cancel_job(job_id)

        return {
            "success": True,
            **result,
            "message": f"Batch job {job_id} cancelled."
        }
    except Exception as e:
        logger.error(f"cancel_batch_job failed: {e}")
        return {"success": False, "error": str(e)}


def get_batch_stats(**kwargs) -> Dict[str, Any]:
    """Get batch processing statistics."""
    try:
        from app.services.batch_processor import get_batch_processor
        processor = get_batch_processor()

        return processor.get_stats()
    except Exception as e:
        logger.error(f"get_batch_stats failed: {e}")
        return {"success": False, "error": str(e)}


def queue_batch_task(
    task_type: str,
    payload: Dict,
    priority: int = 5,
    **kwargs
) -> Dict[str, Any]:
    """Queue a task for batch processing."""
    try:
        from app.services.batch_processor import get_batch_processor
        processor = get_batch_processor()

        return processor.queue_task(task_type, payload, priority)
    except Exception as e:
        logger.error(f"queue_batch_task failed: {e}")
        return {"success": False, "error": str(e)}


def process_batch_queue(
    task_type: str,
    model: str = "claude-haiku-4-5",
    max_batch_size: int = 50,
    **kwargs
) -> Dict[str, Any]:
    """Process queued tasks as a batch."""
    try:
        from app.services.batch_processor import get_batch_processor
        processor = get_batch_processor()

        return processor.process_queue(task_type, model, max_batch_size)
    except Exception as e:
        logger.error(f"process_batch_queue failed: {e}")
        return {"success": False, "error": str(e)}


def get_batch_queue_status(**kwargs) -> Dict[str, Any]:
    """Get batch queue summary."""
    try:
        from app.services.batch_processor import get_batch_processor
        processor = get_batch_processor()

        return processor.get_queue_status()
    except Exception as e:
        logger.error(f"get_batch_queue_status failed: {e}")
        return {"success": False, "error": str(e)}


def get_batch_tools() -> List[Dict]:
    """Get all batch tool definitions."""
    return BATCH_TOOLS
