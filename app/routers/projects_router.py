"""
Projects Router

Extracted from main.py - Project Management endpoints:
- List projects
- Add project
- Update project status
- Delete project
- Get projects context
"""

from fastapi import APIRouter

from ..observability import get_logger

logger = get_logger("jarvis.projects")
router = APIRouter(prefix="/projects", tags=["projects"])


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get("")
def list_projects(user_id: int):
    """List all active projects for a user"""
    from .. import projects
    return projects.tool_list_projects(user_id)


@router.post("")
def add_project(user_id: int, name: str, description: str = "", priority: int = 2):
    """Add a new project"""
    from .. import projects
    return projects.tool_add_project(user_id, name, description, priority)


@router.put("/{project_id}/status")
def update_project_status(project_id: str, status: str):
    """Update project status (active/paused/completed)"""
    from .. import projects
    return projects.tool_update_project_status(project_id, status)


@router.delete("/{project_id}")
def delete_project(project_id: str):
    """Delete a project"""
    from .. import projects
    success = projects.delete_project(project_id)
    return {"success": success}


@router.get("/context")
def get_projects_context(user_id: int):
    """Get projects context string for prompt injection"""
    from .. import projects
    context = projects.build_projects_context(user_id)
    return {"context": context}
