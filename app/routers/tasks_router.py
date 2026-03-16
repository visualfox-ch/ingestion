"""
Tasks Router

Extracted from main.py - Task Management endpoints:
- List/filter tasks
- Today and week views
- Create/update/delete tasks
- Task notes
- Task statistics
"""

from fastapi import APIRouter
from typing import Optional

from ..observability import get_logger

logger = get_logger("jarvis.tasks")
router = APIRouter(prefix="/tasks", tags=["tasks"])


# =============================================================================
# LIST & VIEW ENDPOINTS
# =============================================================================

@router.get("")
def list_tasks(
    user_id: int,
    status: str = None,
    priority: str = None,
    context_tag: str = None,
    include_done: bool = False
):
    """List tasks with optional filters"""
    from .. import knowledge_db
    tasks = knowledge_db.get_tasks(
        user_id=user_id,
        status=status,
        priority=priority,
        context_tag=context_tag,
        include_done=include_done
    )
    return {"tasks": tasks, "count": len(tasks)}


@router.get("/today")
def get_today_tasks(user_id: int):
    """Get Today view (high priority + due today, max 5)"""
    from .. import knowledge_db
    tasks = knowledge_db.get_tasks_today(user_id)
    return {"tasks": tasks, "count": len(tasks), "view": "today"}


@router.get("/week")
def get_week_tasks(user_id: int):
    """Get tasks due in next 7 days"""
    from .. import knowledge_db
    tasks = knowledge_db.get_tasks_week(user_id)
    return {"tasks": tasks, "count": len(tasks), "view": "week"}


@router.get("/stats")
def get_task_stats(user_id: int):
    """Get task statistics"""
    from .. import knowledge_db
    return knowledge_db.get_task_stats(user_id)


@router.get("/{task_id}")
def get_task(task_id: int):
    """Get a single task"""
    from .. import knowledge_db
    task = knowledge_db.get_task(task_id)
    if not task:
        return {"error": "Task not found"}
    notes = knowledge_db.get_task_notes(task_id)
    return {"task": task, "notes": notes}


# =============================================================================
# CREATE/UPDATE/DELETE ENDPOINTS
# =============================================================================

@router.post("")
def create_task(
    user_id: int,
    title: str,
    priority: str = "normal",
    due_date: str = None,
    context_tag: str = "jarvis"
):
    """Create a new task"""
    from .. import knowledge_db
    task = knowledge_db.create_task(
        user_id=user_id,
        title=title,
        priority=priority,
        due_date=due_date,
        context_tag=context_tag
    )
    if task:
        return {"success": True, "task": task}
    return {"success": False, "error": "Failed to create task"}


@router.put("/{task_id}")
def update_task(task_id: int, title: str = None, priority: str = None,
                due_date: str = None, context_tag: str = None, status: str = None):
    """Update a task"""
    from .. import knowledge_db
    updates = {}
    if title:
        updates["title"] = title
    if priority:
        updates["priority"] = priority
    if due_date:
        updates["due_date"] = due_date
    if context_tag:
        updates["context_tag"] = context_tag
    if status:
        updates["status"] = status

    success = knowledge_db.update_task(task_id, updates)
    return {"success": success}


@router.put("/{task_id}/status")
def update_task_status(task_id: int, status: str):
    """Quick status update"""
    from .. import knowledge_db
    success = knowledge_db.update_task_status(task_id, status)
    return {"success": success, "status": status}


@router.delete("/{task_id}")
def delete_task(task_id: int):
    """Delete a task"""
    from .. import knowledge_db
    success = knowledge_db.delete_task(task_id)
    return {"success": success}


@router.post("/{task_id}/notes")
def add_task_note(task_id: int, note: str):
    """Add a note to a task"""
    from .. import knowledge_db
    note_id = knowledge_db.add_task_note(task_id, note)
    if note_id:
        return {"success": True, "note_id": note_id}
    return {"success": False, "error": "Failed to add note"}
