"""
Auto-Refactoring Tools (Tier 4 #15).

Automated Code Quality and Refactoring:
- Analyze codebase for quality issues
- Generate prioritized refactoring suggestions
- Track refactoring progress
- Get detailed file-level analysis

Tools:
- analyze_code_quality: Full codebase analysis
- get_refactoring_suggestions: Get prioritized suggestions
- get_file_issues: Issues for specific file
- update_refactor_status: Mark suggestions as done/skipped
- get_refactor_stats: Overall statistics
"""

import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# Tool Definitions
# =============================================================================

AUTO_REFACTOR_TOOLS = [
    {
        "name": "analyze_code_quality",
        "description": "Analyze the Jarvis codebase for code quality issues like complexity, duplication, and maintainability problems. Returns prioritized issues.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to analyze (default: /brain/system/ingestion/app)"
                },
                "exclude_patterns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Patterns to exclude (default: __pycache__, migrations, tests)"
                }
            },
            "required": []
        },
        "category": "auto_refactor"
    },
    {
        "name": "get_refactoring_suggestions",
        "description": "Generate prioritized refactoring suggestions based on detected issues. Suggestions are ranked by impact/effort ratio.",
        "parameters": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": ["complexity", "maintainability", "architecture", "style"],
                    "description": "Filter by category"
                },
                "max_suggestions": {
                    "type": "integer",
                    "description": "Max suggestions to return (default: 10)"
                }
            },
            "required": []
        },
        "category": "auto_refactor"
    },
    {
        "name": "get_file_issues",
        "description": "Get all code quality issues for a specific file.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "File path (can be partial, e.g., 'agent.py')"
                }
            },
            "required": ["file_path"]
        },
        "category": "auto_refactor"
    },
    {
        "name": "update_refactor_status",
        "description": "Update the status of a refactoring suggestion (mark as completed, in_progress, or skipped).",
        "parameters": {
            "type": "object",
            "properties": {
                "suggestion_id": {
                    "type": "string",
                    "description": "The suggestion ID to update"
                },
                "status": {
                    "type": "string",
                    "enum": ["in_progress", "completed", "skipped"],
                    "description": "New status"
                },
                "notes": {
                    "type": "string",
                    "description": "Optional notes about the refactoring"
                }
            },
            "required": ["suggestion_id", "status"]
        },
        "category": "auto_refactor"
    },
    {
        "name": "get_refactor_stats",
        "description": "Get overall refactoring statistics - active issues, completed suggestions, effort estimates.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        },
        "category": "auto_refactor"
    },
    {
        "name": "analyze_single_file",
        "description": "Analyze a single Python file for code quality issues. More detailed than get_file_issues.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Full path to the Python file"
                }
            },
            "required": ["file_path"]
        },
        "category": "auto_refactor"
    },
    {
        "name": "get_complexity_hotspots",
        "description": "Get the most complex functions/classes in the codebase that need attention.",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Number of hotspots to return (default: 10)"
                }
            },
            "required": []
        },
        "category": "auto_refactor"
    },
    {
        "name": "generate_refactor_plan",
        "description": "Generate a detailed refactoring plan for a specific suggestion with step-by-step instructions.",
        "parameters": {
            "type": "object",
            "properties": {
                "suggestion_id": {
                    "type": "string",
                    "description": "The suggestion ID to generate a plan for"
                }
            },
            "required": ["suggestion_id"]
        },
        "category": "auto_refactor"
    }
]


# =============================================================================
# Tool Handlers
# =============================================================================

def analyze_code_quality(
    path: str = None,
    exclude_patterns: List[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """Analyze codebase for code quality issues."""
    try:
        from app.services.auto_refactor_service import get_auto_refactor_service
        service = get_auto_refactor_service()

        result = service.analyze_codebase(path, exclude_patterns)

        if result.get("success"):
            # Also generate suggestions
            suggestions = service.generate_suggestions(max_suggestions=5)
            result["top_suggestions"] = suggestions.get("suggestions", [])[:3]

        return result
    except Exception as e:
        logger.error(f"analyze_code_quality failed: {e}")
        return {"success": False, "error": str(e)}


def get_refactoring_suggestions(
    category: str = None,
    max_suggestions: int = 10,
    **kwargs
) -> Dict[str, Any]:
    """Get prioritized refactoring suggestions."""
    try:
        from app.services.auto_refactor_service import get_auto_refactor_service
        service = get_auto_refactor_service()

        # First generate fresh suggestions
        service.generate_suggestions(max_suggestions)

        # Then get them
        return service.get_pending_suggestions(category, max_suggestions)
    except Exception as e:
        logger.error(f"get_refactoring_suggestions failed: {e}")
        return {"success": False, "error": str(e)}


def get_file_issues(file_path: str, **kwargs) -> Dict[str, Any]:
    """Get issues for a specific file."""
    try:
        from app.services.auto_refactor_service import get_auto_refactor_service
        service = get_auto_refactor_service()

        return service.get_file_issues(file_path)
    except Exception as e:
        logger.error(f"get_file_issues failed: {e}")
        return {"success": False, "error": str(e)}


def update_refactor_status(
    suggestion_id: str,
    status: str,
    notes: str = None,
    **kwargs
) -> Dict[str, Any]:
    """Update refactoring suggestion status."""
    try:
        from app.services.auto_refactor_service import get_auto_refactor_service
        service = get_auto_refactor_service()

        return service.update_suggestion_status(suggestion_id, status, notes)
    except Exception as e:
        logger.error(f"update_refactor_status failed: {e}")
        return {"success": False, "error": str(e)}


def get_refactor_stats(**kwargs) -> Dict[str, Any]:
    """Get refactoring statistics."""
    try:
        from app.services.auto_refactor_service import get_auto_refactor_service
        service = get_auto_refactor_service()

        return service.get_refactoring_stats()
    except Exception as e:
        logger.error(f"get_refactor_stats failed: {e}")
        return {"success": False, "error": str(e)}


def analyze_single_file(file_path: str, **kwargs) -> Dict[str, Any]:
    """Analyze a single Python file."""
    try:
        from app.services.auto_refactor_service import get_auto_refactor_service, CodeIssue
        from dataclasses import asdict
        service = get_auto_refactor_service()

        issues = service.analyze_file(file_path)

        return {
            "success": True,
            "file": file_path,
            "issues_found": len(issues),
            "issues": [asdict(i) for i in issues],
            "total_effort_hours": sum(i.effort_hours for i in issues),
            "summary": {
                "by_type": {},
                "by_severity": {}
            }
        }
    except Exception as e:
        logger.error(f"analyze_single_file failed: {e}")
        return {"success": False, "error": str(e)}


def get_complexity_hotspots(limit: int = 10, **kwargs) -> Dict[str, Any]:
    """Get the most complex code hotspots."""
    try:
        from app.postgres_state import get_cursor

        with get_cursor() as cur:
            cur.execute("""
                SELECT file_path, line_start, line_end, description,
                       suggestion, effort_hours, impact_score
                FROM refactor_issues
                WHERE issue_type = 'complexity' AND is_active = true
                ORDER BY impact_score DESC, effort_hours ASC
                LIMIT %s
            """, (limit,))

            hotspots = [{
                "file": row['file_path'],
                "lines": f"{row['line_start']}-{row['line_end']}",
                "description": row['description'],
                "suggestion": row['suggestion'],
                "effort": row['effort_hours'],
                "impact": row['impact_score']
            } for row in cur.fetchall()]

            return {
                "success": True,
                "hotspots": hotspots,
                "count": len(hotspots)
            }
    except Exception as e:
        logger.error(f"get_complexity_hotspots failed: {e}")
        return {"success": False, "error": str(e)}


def generate_refactor_plan(suggestion_id: str, **kwargs) -> Dict[str, Any]:
    """Generate detailed refactoring plan for a suggestion."""
    try:
        from app.postgres_state import get_cursor
        import json

        with get_cursor() as cur:
            cur.execute("""
                SELECT title, description, issues, estimated_hours,
                       risk_level, category
                FROM refactor_suggestions
                WHERE id = %s
            """, (suggestion_id,))

            row = cur.fetchone()
            if not row:
                return {"success": False, "error": "Suggestion not found"}

            issues = row['issues'] if isinstance(row['issues'], list) else json.loads(row['issues'])

            # Generate step-by-step plan
            steps = []
            step_num = 1

            # Pre-work
            steps.append({
                "step": step_num,
                "action": "Create feature branch",
                "command": f"git checkout -b refactor/{suggestion_id}",
                "notes": "Always work on a branch for refactoring"
            })
            step_num += 1

            # For each issue
            for issue in issues[:5]:  # Max 5 detailed steps
                steps.append({
                    "step": step_num,
                    "action": f"Fix: {issue.get('description', 'Issue')[:50]}",
                    "file": issue.get('file_path', 'Unknown'),
                    "lines": f"{issue.get('line_start', '?')}-{issue.get('line_end', '?')}",
                    "suggestion": issue.get('suggestion', 'Apply best practices'),
                    "effort": f"{issue.get('effort_hours', 1)}h"
                })
                step_num += 1

            # Post-work
            steps.append({
                "step": step_num,
                "action": "Run tests",
                "command": "pytest tests/ -v",
                "notes": "Verify no regressions"
            })
            step_num += 1

            steps.append({
                "step": step_num,
                "action": "Deploy and verify",
                "command": "bash build-ingestion-fast.sh",
                "notes": "Check health endpoint after deploy"
            })

            return {
                "success": True,
                "suggestion_id": suggestion_id,
                "title": row['title'],
                "estimated_hours": row['estimated_hours'],
                "risk_level": row['risk_level'],
                "steps": steps,
                "rollback_plan": "git checkout HEAD -- <files> && bash build-ingestion-fast.sh"
            }
    except Exception as e:
        logger.error(f"generate_refactor_plan failed: {e}")
        return {"success": False, "error": str(e)}


def get_auto_refactor_tools() -> List[Dict]:
    """Get all auto-refactor tool definitions."""
    return AUTO_REFACTOR_TOOLS
