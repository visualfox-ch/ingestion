import json
import time
from datetime import datetime
from typing import List, Optional, Dict, Any
from uuid import uuid4

import redis

from .observability import get_logger
from . import config as cfg

logger = get_logger("jarvis.agent_coordinator")


class Task:
    """Represents a coding task."""

    def __init__(self, agent_type: str, description: str, files: List[str], priority: str = "normal"):
        self.task_id = str(uuid4())
        self.agent_type = agent_type
        self.description = description
        self.files_to_edit = files
        self.priority = priority
        self.status = "pending"
        self.created_at = datetime.utcnow().isoformat()

    def get_files_to_edit(self) -> List[str]:
        return self.files_to_edit

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "agent_type": self.agent_type,
            "description": self.description,
            "files": self.files_to_edit,
            "priority": self.priority,
            "status": self.status,
            "created_at": self.created_at,
        }


class FileCoordinator:
    """Prevents file conflicts between parallel agents."""

    FILE_LOCK_TIMEOUT = 3600

    FILE_DEPENDENCIES = {
        "app/query_classifier.py": [
            "app/agent.py",
            "tests/test_query_classifier.py"
        ],
        "app/agent.py": [
            "app/query_classifier.py",
            "app/context_builder.py",
            "app/metrics.py",
            "app/prompt_assembler.py"
        ],
        "app/context_builder.py": [
            "app/agent.py",
            "app/prompt_assembler.py"
        ],
        "app/prompt_assembler.py": [
            "app/agent.py",
            "app/context_builder.py"
        ],
        "app/metrics.py": [
            "app/agent.py"
        ],
        "app/config_manager.py": [
            "app/agent.py",
            "app/query_classifier.py"
        ],
    }

    def __init__(self, redis_client: redis.Redis, agent_id: str):
        self.redis = redis_client
        self.agent_id = agent_id

    def acquire_file_lock(self, file_path: str, task_id: str) -> bool:
        """Try to acquire lock on a file."""
        lock_key = f"jarvis:lock:file:{file_path}"
        lock_data = {
            "agent_id": self.agent_id,
            "task_id": task_id,
            "acquired_at": datetime.utcnow().isoformat(),
            "file_path": file_path
        }

        result = self.redis.set(
            lock_key,
            json.dumps(lock_data),
            nx=True,
            ex=self.FILE_LOCK_TIMEOUT
        )

        if result:
            logger.info(f"Lock acquired: {file_path} for task {task_id}")
            return True

        existing = self.redis.get(lock_key)
        existing_lock = json.loads(existing or "{}")
        logger.warning(
            "Lock denied: %s (owned by %s task %s)",
            file_path,
            existing_lock.get("agent_id"),
            existing_lock.get("task_id")
        )
        return False

    def release_file_lock(self, file_path: str) -> bool:
        """Release lock on a file."""
        lock_key = f"jarvis:lock:file:{file_path}"
        lock_data = json.loads(self.redis.get(lock_key) or "{}")

        if lock_data.get("agent_id") == self.agent_id:
            self.redis.delete(lock_key)
            logger.info(f"Lock released: {file_path}")
            return True

        logger.warning("Cannot release lock on %s (owned by other agent)", file_path)
        return False

    def get_related_files(self, primary_file: str) -> List[str]:
        """Get files that should NOT be edited in parallel."""
        return self.FILE_DEPENDENCIES.get(primary_file, [])

    def can_edit_file(self, file_path: str) -> bool:
        """Check if file is available for editing."""
        lock_key = f"jarvis:lock:file:{file_path}"
        lock_data = self.redis.get(lock_key)

        if lock_data is None:
            return True

        lock_data = json.loads(lock_data)
        return lock_data.get("agent_id") == self.agent_id

    def acquire_all_locks(self, task: Task) -> bool:
        """Try to acquire locks for all task files."""
        files_to_lock = []
        files_to_lock.extend(task.get_files_to_edit())

        for file_path in task.get_files_to_edit():
            files_to_lock.extend(self.get_related_files(file_path))

        files_to_lock = list(set(files_to_lock))

        acquired = []
        for file_path in files_to_lock:
            if self.acquire_file_lock(file_path, task.task_id):
                acquired.append(file_path)
            else:
                for locked in acquired:
                    self.release_file_lock(locked)
                return False

        return True

    def release_all_locks(self, task: Task) -> None:
        """Release all locks for a task."""
        files_to_unlock = []
        files_to_unlock.extend(task.get_files_to_edit())
        for file_path in task.get_files_to_edit():
            files_to_unlock.extend(self.get_related_files(file_path))

        for file_path in set(files_to_unlock):
            self.release_file_lock(file_path)


class ParallelTaskQueue:
    """Orchestrates max 3 concurrent coding agents."""

    MAX_CONCURRENT = 3

    def __init__(self, redis_client: redis.Redis, agent_id: str):
        self.redis = redis_client
        self.agent_id = agent_id
        self.coordinator = FileCoordinator(redis_client, agent_id)

    def submit_task(self, task: Task) -> str:
        """Submit a new task."""
        self.redis.hset(
            f"jarvis:task:{task.task_id}",
            mapping={
                k: json.dumps(v) if not isinstance(v, (str, int, float)) else str(v)
                for k, v in task.to_dict().items()
            }
        )

        priority_score = self._get_priority_score(task.priority)
        self.redis.zadd("jarvis:task:queue", {task.task_id: priority_score})

        logger.info("Task %s submitted (%s, %s)", task.task_id, task.agent_type, task.priority)
        return task.task_id

    def get_next_task(self) -> Optional[Task]:
        """Get next task ready to run."""
        running_count = self.redis.zcard("jarvis:task:running")
        if running_count >= self.MAX_CONCURRENT:
            logger.debug("Max agents running (%s), waiting...", running_count)
            return None

        pending_tasks = self.redis.zrange("jarvis:task:queue", 0, 9, withscores=False)

        for task_id in pending_tasks:
            task_id = self._normalize_task_id(task_id)
            task = self._load_task(task_id)
            if task is None:
                continue

            if self.coordinator.acquire_all_locks(task):
                self.redis.zrem("jarvis:task:queue", task_id)
                self.redis.zadd("jarvis:task:running", {task_id: time.time()})
                logger.info("Task %s started (locks acquired)", task_id)
                return task

        logger.debug("No task ready (all files locked or no pending)")
        return None

    def complete_task(self, task_id: str, success: bool = True) -> None:
        """Mark task complete and release locks."""
        task_id = self._normalize_task_id(task_id)
        task = self._load_task(task_id)
        if task is None:
            return

        self.coordinator.release_all_locks(task)
        self.redis.zrem("jarvis:task:running", task_id)
        self.redis.zadd("jarvis:task:completed", {task_id: time.time()})

        status = "success" if success else "failed"
        self.redis.hset(f"jarvis:task:{task_id}", "status", status)

        logger.info("Task %s completed (%s)", task_id, status)

    def get_status(self) -> Dict[str, Any]:
        """Get queue status."""
        return {
            "queued": self.redis.zcard("jarvis:task:queue"),
            "running": self.redis.zcard("jarvis:task:running"),
            "completed": self.redis.zcard("jarvis:task:completed"),
            "max_concurrent": self.MAX_CONCURRENT,
            "agents_available": self.MAX_CONCURRENT - self.redis.zcard("jarvis:task:running"),
            "timestamp": datetime.utcnow().isoformat()
        }

    def _get_priority_score(self, priority: str) -> float:
        scores = {
            "critical": 0,
            "high": 1,
            "normal": 2,
            "low": 3
        }
        return scores.get(priority, 2)

    def _normalize_task_id(self, task_id: Any) -> str:
        if isinstance(task_id, bytes):
            return task_id.decode("utf-8")
        return str(task_id)

    def _load_task(self, task_id: str) -> Optional[Task]:
        task_id = self._normalize_task_id(task_id)
        task_data = self.redis.hgetall(f"jarvis:task:{task_id}")
        if not task_data:
            return None

        task = Task(
            agent_type=task_data.get(b"agent_type", b"").decode("utf-8"),
            description=task_data.get(b"description", b"").decode("utf-8"),
            files=json.loads(task_data.get(b"files", b"[]")),
            priority=task_data.get(b"priority", b"normal").decode("utf-8")
        )
        task.task_id = task_data.get(b"task_id", b"").decode("utf-8")
        task.status = task_data.get(b"status", b"pending").decode("utf-8")
        return task


def get_agent_coordinator(agent_id: str) -> ParallelTaskQueue:
    redis_client = redis.Redis(
        host=cfg.REDIS_HOST,
        port=cfg.REDIS_PORT,
        db=cfg.REDIS_DB,
        decode_responses=False
    )
    return ParallelTaskQueue(redis_client, agent_id)
