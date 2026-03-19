"""
Sandbox Tools - Python Code Execution & Dynamic Tool Creation

Extracted from tools.py as part of T006 Main/Tools Split.
"""

from typing import Dict, Any
from datetime import datetime
import json
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# TOOL DEFINITIONS
# =============================================================================

SANDBOX_TOOLS = [
    {
        "name": "request_python_sandbox",
        "description": "Request manual approval to run Jarvis-authored Python code in a sandbox. This does NOT execute code; it queues an approval request.",
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python code to execute (queued for approval)"
                },
                "reason": {
                    "type": "string",
                    "description": "Reason for execution (audit trail)"
                },
                "timeout_seconds": {
                    "type": "integer",
                    "description": "Execution timeout in seconds (max 60)",
                    "default": 30
                },
                "metadata": {
                    "type": "object",
                    "description": "Optional metadata for audit"
                }
            },
            "required": ["code"]
        }
    },
    {
        "name": "execute_python",
        "description": """Execute Python code YOU write directly in the sandbox.

ALLOWED IMPORTS: math, json, datetime, re, collections, itertools, statistics, csv, hashlib, base64, uuid, time, copy, textwrap

SAFE FILE ACCESS (auto-injected helpers):
- safe_read_file(path, max_lines=500) - Read files from /brain/system/, /brain/projects/, /brain/notes/
- safe_list_files(directory, pattern='*') - List files in allowed directories

EXAMPLE:
  content = safe_read_file('/brain/system/docker/TASKS.md')
  files = safe_list_files('/brain/system/ingestion/app', '*.py')

FORBIDDEN: direct open(), network, subprocess, exec/eval, os.system""",
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python code to execute. Must use print() for output. Use safe_read_file() for file access."
                },
                "reason": {
                    "type": "string",
                    "description": "Brief reason why this code is being executed (for audit)"
                }
            },
            "required": ["code", "reason"]
        }
    },
    {
        "name": "write_dynamic_tool",
        "description": "Create a new dynamic tool that Jarvis can use. Write Python code that becomes a callable tool. Tools go to sandbox first by default for safety review. Use this to extend your capabilities!",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Tool name in snake_case (e.g., 'my_custom_tool')"
                },
                "description": {
                    "type": "string",
                    "description": "What the tool does - be clear and concise"
                },
                "code": {
                    "type": "string",
                    "description": "Python code for the tool handler. Must return a dict. Receives **kwargs."
                },
                "parameters": {
                    "type": "object",
                    "description": "JSON schema for tool parameters (properties only)"
                },
                "category": {
                    "type": "string",
                    "description": "Tool category (memory, utility, analysis, custom)",
                    "default": "custom"
                },
                "sandbox": {
                    "type": "boolean",
                    "description": "If true, tool goes to sandbox first for review",
                    "default": True
                }
            },
            "required": ["name", "description", "code"]
        }
    },
    {
        "name": "promote_sandbox_tool",
        "description": "Promote a tool from sandbox to live production. Use after testing a tool created with write_dynamic_tool.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name of the sandbox tool to promote"
                }
            },
            "required": ["name"]
        }
    },
]


# =============================================================================
# TOOL IMPLEMENTATIONS
# =============================================================================

def tool_request_python_sandbox(**kwargs) -> Dict[str, Any]:
    """
    Queue a manual-approval request for running Jarvis-authored Python code.
    This does not execute code automatically.
    """
    try:
        from ..action_queue import create_action_request
        from ..tracing import get_current_user_id
        from ..observability import log_with_context

        code = kwargs.get("code")
        reason = kwargs.get("reason", "agent sandbox request")
        timeout_seconds = kwargs.get("timeout_seconds")
        metadata = kwargs.get("metadata") or {}

        if code is None or not str(code).strip():
            return {"error": "code is required"}

        user_id = get_current_user_id() or "jarvis_agent"

        action = create_action_request(
            action_name="python_sandbox_execute",
            description="Python sandbox execute",
            target="python_executor",
            context={
                "code": str(code),
                "timeout_seconds": timeout_seconds,
                "reason": reason,
                "metadata": metadata,
            },
            content_preview=str(code)[:400],
            user_id=str(user_id),
        )

        status = action.get("status")
        if status == "blocked":
            return {"status": "blocked", "action": action}

        if status == "pending":
            return {
                "status": "pending",
                "approval_required": True,
                "action_id": action.get("id"),
                "approve_endpoint": f"/jarvis/self/code-sandbox/actions/{action.get('id')}/approve",
            }

        return {
            "status": status,
            "approval_required": False,
            "action_id": action.get("id"),
            "execute_endpoint": f"/jarvis/self/code-sandbox/actions/{action.get('id')}/execute",
        }

    except Exception as e:
        logger.warning(f"Request Python sandbox failed: {e}")
        return {"error": str(e)}


def tool_execute_python(**kwargs) -> Dict[str, Any]:
    """
    Execute Python code written by Jarvis in the sandbox.
    For when Jarvis writes code himself (higher quality, uses API tokens).
    """
    try:
        from .. import python_executor
        from .. import metrics

        code = kwargs.get("code")
        reason = kwargs.get("reason", "agent execution")

        if code is None or not str(code).strip():
            return {"error": "code is required"}

        result = python_executor.execute_python(
            code=code,
            user_id="jarvis_agent",
            metadata={"reason": reason, "source": "agent_tool"},
        )

        metrics.inc("tool_execute_python")

        return {
            "status": result.status,
            "exec_id": result.exec_id,
            "output": result.stdout,
            "stderr": result.stderr if result.stderr else None,
            "exit_code": result.exit_code,
            "duration_ms": round(result.duration_ms, 2),
            "blocked_reason": result.blocked_reason,
            "artifacts": result.artifacts,
        }

    except Exception as e:
        logger.warning(f"Execute Python failed: {e}")
        return {"error": str(e)}


def tool_write_dynamic_tool(
    name: str = None,
    description: str = None,
    code: str = None,
    parameters: dict = None,
    category: str = "custom",
    sandbox: bool = True,
    **kwargs
) -> Dict[str, Any]:
    """
    Create a new dynamic tool that Jarvis can use.

    Args:
        name: Tool name (snake_case, e.g., 'my_custom_tool')
        description: What the tool does
        code: Python code for the tool handler function
        parameters: JSON schema for tool parameters
        category: Tool category (default: custom)
        sandbox: If True, tool goes to sandbox first (default: True)

    Returns:
        Status of tool creation
    """
    from ..observability import log_with_context
    from .. import metrics
    import re

    log_with_context(logger, "info", "Tool: write_dynamic_tool", name=name, category=category)
    metrics.inc("tool_write_dynamic_tool")

    if not name or not description or not code:
        return {"error": "name, description, and code are required"}

    try:
        from ..tool_loader import DynamicToolLoader, TOOLS_SANDBOX_DIR, TOOLS_DYNAMIC_DIR

        # Validate name format
        if not re.match(r'^[a-z][a-z0-9_]*$', name):
            return {"error": "name must be snake_case (lowercase, underscores allowed)"}

        # Security validation
        violations = DynamicToolLoader._validate_code(code, f"{name}.py")
        if violations:
            return {"error": "Security violations", "violations": violations}

        # Indent code properly (4 spaces for function body)
        indented_code = code.replace('\n', '\n    ')

        # Build tool file content
        tool_content = f'''"""
Dynamic Tool: {name}
Category: {category}
Description: {description}
Created: {datetime.utcnow().isoformat()}Z
"""
from typing import Dict, Any

TOOL_SCHEMA = {{
    "name": "{name}",
    "description": """{description}""",
    "input_schema": {{
        "type": "object",
        "properties": {json.dumps(parameters or {}, indent=8)},
        "required": []
    }}
}}

TOOL_CATEGORY = "{category}"

def tool_handler(**kwargs) -> Dict[str, Any]:
    """Tool handler function."""
    {indented_code}
'''

        # Write to appropriate directory
        target_dir = TOOLS_SANDBOX_DIR if sandbox else TOOLS_DYNAMIC_DIR
        target_dir.mkdir(parents=True, exist_ok=True)
        tool_file = target_dir / f"{name}.py"
        tool_file.write_text(tool_content)

        # If not sandbox, reload immediately
        if not sandbox:
            DynamicToolLoader.reload(name)

        return {
            "status": "created",
            "name": name,
            "location": "sandbox" if sandbox else "live",
            "path": str(tool_file),
            "next_step": "Use promote_sandbox_tool to make it live" if sandbox else "Tool is now available"
        }

    except Exception as e:
        logger.error(f"write_dynamic_tool failed: {e}")
        return {"error": str(e)}


def tool_promote_sandbox_tool(name: str = None, **kwargs) -> Dict[str, Any]:
    """
    Promote a tool from sandbox to live production.

    Args:
        name: Name of the sandbox tool to promote

    Returns:
        Status of promotion
    """
    from ..observability import log_with_context
    from .. import metrics

    log_with_context(logger, "info", "Tool: promote_sandbox_tool", name=name)
    metrics.inc("tool_promote_sandbox_tool")

    if not name:
        return {"error": "name is required"}

    try:
        from ..tool_loader import DynamicToolLoader, TOOLS_SANDBOX_DIR, TOOLS_DYNAMIC_DIR
        import shutil

        sandbox_file = TOOLS_SANDBOX_DIR / f"{name}.py"
        if not sandbox_file.exists():
            return {"error": f"Tool '{name}' not found in sandbox"}

        # Move to live directory
        live_file = TOOLS_DYNAMIC_DIR / f"{name}.py"
        shutil.move(str(sandbox_file), str(live_file))

        # Hot-reload the tool
        result = DynamicToolLoader.reload(name)

        return {
            "status": "promoted",
            "name": name,
            "path": str(live_file),
            "reload_result": result
        }

    except Exception as e:
        logger.error(f"promote_sandbox_tool failed: {e}")
        return {"error": str(e)}
