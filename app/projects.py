"""
Active Projects Tracking
Manages user's current projects and priorities for context injection.
"""
import sqlite3
import json
from datetime import datetime
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict
from pathlib import Path

from .observability import get_logger

logger = get_logger("jarvis.projects")

# Use same database as session_manager
DB_PATH = Path("/brain/system/state/jarvis_state.db")


@dataclass
class Project:
    """Active project with priority and context"""
    id: str
    name: str
    description: str
    priority: int  # 1=high, 2=medium, 3=low
    status: str  # active, paused, completed
    context: str  # Additional notes/context
    created_at: str
    updated_at: str
    user_id: int


def _get_db() -> sqlite3.Connection:
    """Get database connection, create table if needed"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # Create projects table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS active_projects (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            description TEXT,
            priority INTEGER DEFAULT 2,
            status TEXT DEFAULT 'active',
            context TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_projects_user ON active_projects(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_projects_status ON active_projects(status)")
    conn.commit()
    return conn


def add_project(
    user_id: int,
    name: str,
    description: str = "",
    priority: int = 2,
    context: str = ""
) -> Project:
    """Add a new active project"""
    conn = _get_db()
    now = datetime.now().isoformat()
    project_id = f"proj_{user_id}_{int(datetime.now().timestamp())}"

    conn.execute("""
        INSERT INTO active_projects (id, user_id, name, description, priority, status, context, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?)
    """, (project_id, user_id, name, description, priority, context, now, now))
    conn.commit()
    conn.close()

    logger.info(f"Project added: {name} (priority {priority})")

    return Project(
        id=project_id,
        name=name,
        description=description,
        priority=priority,
        status="active",
        context=context,
        created_at=now,
        updated_at=now,
        user_id=user_id
    )


def get_active_projects(user_id: int, include_paused: bool = False) -> List[Project]:
    """Get all active projects for a user, sorted by priority"""
    conn = _get_db()

    if include_paused:
        status_filter = "('active', 'paused')"
    else:
        status_filter = "('active')"

    rows = conn.execute(f"""
        SELECT * FROM active_projects
        WHERE user_id = ? AND status IN {status_filter}
        ORDER BY priority ASC, updated_at DESC
    """, (user_id,)).fetchall()
    conn.close()

    return [Project(**dict(row)) for row in rows]


def update_project(
    project_id: str,
    name: str = None,
    description: str = None,
    priority: int = None,
    status: str = None,
    context: str = None
) -> bool:
    """Update a project"""
    conn = _get_db()

    updates = []
    values = []

    if name is not None:
        updates.append("name = ?")
        values.append(name)
    if description is not None:
        updates.append("description = ?")
        values.append(description)
    if priority is not None:
        updates.append("priority = ?")
        values.append(priority)
    if status is not None:
        updates.append("status = ?")
        values.append(status)
    if context is not None:
        updates.append("context = ?")
        values.append(context)

    if not updates:
        return False

    updates.append("updated_at = ?")
    values.append(datetime.now().isoformat())
    values.append(project_id)

    conn.execute(f"""
        UPDATE active_projects SET {', '.join(updates)} WHERE id = ?
    """, values)
    conn.commit()
    conn.close()

    logger.info(f"Project updated: {project_id}")
    return True


def complete_project(project_id: str) -> bool:
    """Mark a project as completed"""
    return update_project(project_id, status="completed")


def pause_project(project_id: str) -> bool:
    """Pause a project"""
    return update_project(project_id, status="paused")


def resume_project(project_id: str) -> bool:
    """Resume a paused project"""
    return update_project(project_id, status="active")


def delete_project(project_id: str) -> bool:
    """Delete a project"""
    conn = _get_db()
    conn.execute("DELETE FROM active_projects WHERE id = ?", (project_id,))
    conn.commit()
    affected = conn.total_changes
    conn.close()
    return affected > 0


def build_projects_context(user_id: int) -> Optional[str]:
    """Build context string for injection into agent prompt"""
    projects = get_active_projects(user_id, include_paused=True)

    if not projects:
        return None

    priority_labels = {1: "HIGH", 2: "MEDIUM", 3: "LOW"}

    lines = ["=== ACTIVE PROJECTS ==="]

    active = [p for p in projects if p.status == "active"]
    paused = [p for p in projects if p.status == "paused"]

    if active:
        lines.append("**Current Focus:**")
        for p in active:
            prio = priority_labels.get(p.priority, "MEDIUM")
            lines.append(f"- [{prio}] {p.name}: {p.description}")
            if p.context:
                lines.append(f"  Context: {p.context}")

    if paused:
        lines.append("\n**On Hold:**")
        for p in paused:
            lines.append(f"- {p.name} (paused)")

    lines.append("\nUse this context to prioritize recommendations and understand current workload.")

    return "\n".join(lines)


# Tool functions for agent
def tool_add_project(user_id: int, name: str, description: str = "", priority: int = 2) -> Dict[str, Any]:
    """Tool: Add a new project"""
    project = add_project(user_id, name, description, priority)
    return {
        "success": True,
        "project": asdict(project),
        "message": f"Project '{name}' added with priority {priority}"
    }


def tool_list_projects(user_id: int) -> Dict[str, Any]:
    """Tool: List all active projects"""
    projects = get_active_projects(user_id, include_paused=True)
    return {
        "count": len(projects),
        "projects": [asdict(p) for p in projects]
    }


def tool_update_project_status(project_id: str, status: str) -> Dict[str, Any]:
    """Tool: Update project status (active/paused/completed)"""
    if status == "completed":
        success = complete_project(project_id)
    elif status == "paused":
        success = pause_project(project_id)
    elif status == "active":
        success = resume_project(project_id)
    else:
        return {"success": False, "error": f"Invalid status: {status}"}

    return {"success": success, "new_status": status}
