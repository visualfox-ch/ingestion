import pytest
import redis

from app import config as cfg
from app.agent_coordinator import Task, ParallelTaskQueue, FileCoordinator


REDIS_PREFIXES = ["jarvis:task:", "jarvis:lock:file:", "jarvis:task:queue", "jarvis:task:running", "jarvis:task:completed"]


def _get_redis_client():
    return redis.Redis(host=cfg.REDIS_HOST, port=cfg.REDIS_PORT, db=cfg.REDIS_DB, decode_responses=False)


def _redis_available(client: redis.Redis) -> bool:
    try:
        return client.ping()
    except Exception:
        return False


def _cleanup_redis(client: redis.Redis):
    for prefix in REDIS_PREFIXES:
        if prefix.endswith(":"):
            cursor = 0
            while True:
                cursor, keys = client.scan(cursor=cursor, match=f"{prefix}*", count=200)
                if keys:
                    client.delete(*keys)
                if cursor == 0:
                    break
        else:
            client.delete(prefix)


@pytest.fixture()
def redis_client():
    client = _get_redis_client()
    if not _redis_available(client):
        pytest.skip("Redis not available for agent coordinator tests")
    _cleanup_redis(client)
    yield client
    _cleanup_redis(client)


def test_single_task_execution(redis_client):
    queue = ParallelTaskQueue(redis_client, "agent-1")
    task = Task("copilot", "Fix classifier", ["app/query_classifier.py"], "normal")

    task_id = queue.submit_task(task)
    next_task = queue.get_next_task()

    assert next_task.task_id == task_id
    assert queue.get_status()["running"] == 1


def test_three_tasks_run_parallel(redis_client):
    queue = ParallelTaskQueue(redis_client, "agent-1")

    task1 = Task("copilot", "Task 1", ["file1.py"], "critical")
    task2 = Task("claude", "Task 2", ["file2.py"], "high")
    task3 = Task("copilot", "Task 3", ["file3.py"], "normal")

    queue.submit_task(task1)
    queue.submit_task(task2)
    queue.submit_task(task3)

    queue.get_next_task()
    queue.get_next_task()
    queue.get_next_task()

    assert queue.get_status()["running"] == 3
    assert queue.get_status()["agents_available"] == 0


def test_fourth_task_queued(redis_client):
    queue = ParallelTaskQueue(redis_client, "agent-1")

    for i in range(4):
        task = Task("copilot", f"Task {i}", [f"file{i}.py"], "normal")
        queue.submit_task(task)

    for _ in range(3):
        queue.get_next_task()

    fourth = queue.get_next_task()
    assert fourth is None
    assert queue.get_status()["queued"] == 1


def test_file_locking_prevents_concurrent_edit(redis_client):
    queue = ParallelTaskQueue(redis_client, "agent-1")

    task1 = Task("copilot", "Task 1", ["app/agent.py"], "critical")
    task2 = Task("claude", "Task 2", ["app/agent.py"], "normal")

    queue.submit_task(task1)
    queue.submit_task(task2)

    t1 = queue.get_next_task()
    t2 = queue.get_next_task()

    assert t1 is not None
    assert t2 is None
    assert queue.get_status()["running"] == 1
    assert queue.get_status()["queued"] == 1


def test_related_files_locked_together(redis_client):
    queue = ParallelTaskQueue(redis_client, "agent-1")

    task1 = Task("copilot", "Task 1", ["app/query_classifier.py"], "critical")
    task2 = Task("claude", "Task 2", ["app/agent.py"], "normal")

    queue.submit_task(task1)
    queue.submit_task(task2)

    t1 = queue.get_next_task()
    t2 = queue.get_next_task()

    assert t1 is not None
    assert t2 is None


def test_priority_queue(redis_client):
    queue = ParallelTaskQueue(redis_client, "agent-1")

    task_normal = Task("copilot", "Normal", ["file1.py"], "normal")
    task_critical = Task("claude", "Critical", ["file2.py"], "critical")

    queue.submit_task(task_normal)
    queue.submit_task(task_critical)

    next_task = queue.get_next_task()
    assert next_task.priority == "critical"


def test_lock_timeout(redis_client):
    coordinator = FileCoordinator(redis_client, "agent-1")
    task = Task("copilot", "Test", ["app/test.py"], "normal")

    coordinator.acquire_file_lock("app/test.py", task.task_id)
    ttl = redis_client.ttl("jarvis:lock:file:app/test.py")
    assert 3500 < ttl <= 3600


def test_task_completion_releases_locks(redis_client):
    queue = ParallelTaskQueue(redis_client, "agent-1")
    task = Task("copilot", "Test", ["app/agent.py"], "normal")

    queue.submit_task(task)
    started_task = queue.get_next_task()

    assert queue.get_status()["running"] == 1
    assert redis_client.exists("jarvis:lock:file:app/agent.py")

    queue.complete_task(started_task.task_id)

    assert queue.get_status()["running"] == 0
    assert not redis_client.exists("jarvis:lock:file:app/agent.py")
