"""
Ollama Task Delegation Module

Enables Jarvis to queue tasks for local Ollama execution.
Tasks are stored as JSON files and processed asynchronously.
"""
import json
import os
import uuid
from pathlib import Path
from datetime import datetime
from enum import Enum
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, Optional, List

from .observability import get_logger, log_with_context

logger = get_logger("jarvis.ollama_delegation")

# Queue directories (on mounted volume for persistence)
BRAIN_ROOT = Path(os.environ.get("BRAIN_ROOT", "/brain"))
QUEUE_BASE = BRAIN_ROOT / "system" / "ollama-queue"
QUEUE_PENDING = QUEUE_BASE / "pending"
QUEUE_PROCESSING = QUEUE_BASE / "processing"
QUEUE_COMPLETED = QUEUE_BASE / "completed"
QUEUE_FAILED = QUEUE_BASE / "failed"

# Ensure directories exist
for queue_dir in [QUEUE_PENDING, QUEUE_PROCESSING, QUEUE_COMPLETED, QUEUE_FAILED]:
    queue_dir.mkdir(parents=True, exist_ok=True)


class TaskType(Enum):
    """Types of tasks that can be delegated to Ollama."""
    SUMMARIZE = "summarize"
    TRANSLATE = "translate"
    ANALYZE = "analyze"
    EXTRACT = "extract"
    GENERATE = "generate"
    CODE_REVIEW = "code_review"
    REWRITE = "rewrite"
    CUSTOM = "custom"


class TaskStatus(Enum):
    """Task execution status."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class OllamaTask:
    """Represents a task to be executed by Ollama."""
    task_id: str
    task_type: TaskType
    instructions: str
    input_text: Optional[str] = None
    input_path: Optional[str] = None
    output_path: Optional[str] = None
    model: str = "llama3.2"
    max_tokens: int = 1000
    temperature: float = 0.3
    language: str = "de"
    output_format: str = "text"
    callback_url: Optional[str] = None
    status: TaskStatus = TaskStatus.PENDING
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    result: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["task_type"] = self.task_type.value
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OllamaTask":
        data["task_type"] = TaskType(data["task_type"])
        data["status"] = TaskStatus(data["status"])
        return cls(**data)


def create_task(
    task_type: TaskType,
    instructions: str,
    input_text: Optional[str] = None,
    input_path: Optional[str] = None,
    output_path: Optional[str] = None,
    model: str = None,
    max_tokens: int = 1000,
    temperature: float = 0.3,
    language: str = "de",
    output_format: str = "text",
    callback_url: Optional[str] = None
) -> OllamaTask:
    """
    Create and queue a new Ollama task.

    Args:
        task_type: Type of task (summarize, translate, etc.)
        instructions: Specific instructions for the task
        input_text: Text to process (if not using file)
        input_path: Path to input file (alternative to input_text)
        output_path: Path to write result (optional)
        model: Ollama model to use (default: llama3.2)
        max_tokens: Maximum tokens in response
        temperature: Generation temperature (0.0-1.0)
        language: Output language (default: de)
        output_format: Output format (text, json, markdown)
        callback_url: URL to POST result when complete

    Returns:
        OllamaTask object with task_id
    """
    task_id = f"ollama_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"

    # Default model based on task type
    if model is None:
        model = "llama3.2"

    task = OllamaTask(
        task_id=task_id,
        task_type=task_type,
        instructions=instructions,
        input_text=input_text,
        input_path=input_path,
        output_path=output_path,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        language=language,
        output_format=output_format,
        callback_url=callback_url
    )

    # Write to pending queue
    task_file = QUEUE_PENDING / f"{task_id}.json"
    with open(task_file, "w") as f:
        json.dump(task.to_dict(), f, indent=2)

    log_with_context(logger, "info", "Ollama task created",
                    task_id=task_id, task_type=task_type.value, model=model)

    return task


def get_task_status(task_id: str) -> Optional[Dict[str, Any]]:
    """
    Get the current status of a task.

    Searches across all queue directories.
    """
    for queue_dir, status in [
        (QUEUE_PENDING, "pending"),
        (QUEUE_PROCESSING, "processing"),
        (QUEUE_COMPLETED, "completed"),
        (QUEUE_FAILED, "failed")
    ]:
        task_file = queue_dir / f"{task_id}.json"
        if task_file.exists():
            try:
                with open(task_file) as f:
                    data = json.load(f)
                data["queue"] = status
                return data
            except Exception as e:
                log_with_context(logger, "warning", "Failed to read task file",
                               task_id=task_id, error=str(e))
                return None

    return None


def cancel_task(task_id: str) -> bool:
    """
    Cancel a pending task.

    Only works for tasks in PENDING state.
    """
    task_file = QUEUE_PENDING / f"{task_id}.json"
    if not task_file.exists():
        return False

    try:
        with open(task_file) as f:
            data = json.load(f)

        data["status"] = TaskStatus.CANCELLED.value
        data["completed_at"] = datetime.utcnow().isoformat() + "Z"

        # Move to failed queue
        failed_file = QUEUE_FAILED / f"{task_id}.json"
        with open(failed_file, "w") as f:
            json.dump(data, f, indent=2)

        task_file.unlink()
        log_with_context(logger, "info", "Task cancelled", task_id=task_id)
        return True

    except Exception as e:
        log_with_context(logger, "error", "Failed to cancel task",
                        task_id=task_id, error=str(e))
        return False


def list_tasks(status: str = None, limit: int = 20) -> List[Dict[str, Any]]:
    """
    List tasks, optionally filtered by status.
    """
    tasks = []

    queues = {
        "pending": QUEUE_PENDING,
        "processing": QUEUE_PROCESSING,
        "completed": QUEUE_COMPLETED,
        "failed": QUEUE_FAILED
    }

    if status and status in queues:
        search_queues = {status: queues[status]}
    else:
        search_queues = queues

    for queue_status, queue_dir in search_queues.items():
        for task_file in sorted(queue_dir.glob("*.json"),
                               key=lambda p: p.stat().st_mtime,
                               reverse=True)[:limit]:
            try:
                with open(task_file) as f:
                    data = json.load(f)
                data["queue"] = queue_status
                tasks.append(data)
            except Exception:
                continue

    return tasks[:limit]


def get_callback_result(task_id: str) -> Optional[Dict[str, Any]]:
    """
    Get the result for a completed task (for callback handling).
    """
    task_file = QUEUE_COMPLETED / f"{task_id}.json"
    if not task_file.exists():
        return None

    try:
        with open(task_file) as f:
            return json.load(f)
    except Exception:
        return None


# Initialize queues on import
log_with_context(logger, "info", "Ollama delegation module initialized",
                queue_base=str(QUEUE_BASE))
