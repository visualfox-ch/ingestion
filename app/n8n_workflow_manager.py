"""
n8n Workflow Manager - Create and manage n8n workflows via API

This module provides functionality to create, update, and manage n8n workflows
programmatically using the n8n REST API.
"""
import os
import json
import requests
from typing import Dict, Any, List, Optional
from datetime import datetime

from .observability import get_logger, log_with_context

logger = get_logger("jarvis.n8n_workflows")

# n8n API Configuration
N8N_HOST = os.environ.get("N8N_HOST", "n8n")  # Docker DNS (internal)
N8N_PORT = int(os.environ.get("N8N_PORT", "5678"))  # Internal port
N8N_API_BASE = f"http://{N8N_HOST}:{N8N_PORT}/api/v1"
N8N_API_KEY = os.environ.get("N8N_API_KEY", "")  # Set this in environment
N8N_TIMEOUT = int(os.environ.get("N8N_TIMEOUT", "30"))


class N8NWorkflowManager:
    """Manages n8n workflows via REST API."""

    def __init__(self):
        self.headers = {
            "X-N8N-API-KEY": N8N_API_KEY,
            "Content-Type": "application/json",
        }
        if not N8N_API_KEY:
            log_with_context(logger, "warning", "No N8N_API_KEY configured")

    def _request(self, method: str, endpoint: str, data: Dict = None, params: Dict = None) -> Dict[str, Any]:
        """Make a request to n8n API."""
        url = f"{N8N_API_BASE}{endpoint}"

        try:
            response = requests.request(
                method=method,
                url=url,
                headers=self.headers,
                json=data,
                params=params,
                timeout=N8N_TIMEOUT
            )
            response.raise_for_status()
            return response.json() if response.text else {}

        except requests.HTTPError as e:
            error_msg = f"HTTP {e.response.status_code}: {e.response.text}"
            log_with_context(logger, "error", "n8n API request failed",
                           endpoint=endpoint, error=error_msg)
            return {"error": error_msg, "success": False}
        except Exception as e:
            log_with_context(logger, "error", "n8n API request error",
                           endpoint=endpoint, error=str(e))
            return {"error": str(e), "success": False}

    # ============ Workflow Management ============

    def list_workflows(self, active_only: bool = False) -> List[Dict[str, Any]]:
        """List all workflows."""
        result = self._request("GET", "/workflows")
        
        if "error" in result:
            return []

        workflows = result.get("data", [])
        
        if active_only:
            workflows = [w for w in workflows if w.get("active", False)]

        return workflows

    def get_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """Get a specific workflow by ID."""
        return self._request("GET", f"/workflows/{workflow_id}")

    def create_workflow(self, workflow_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a new workflow.

        Args:
            workflow_data: Complete workflow definition including nodes and connections

        Returns:
            Created workflow data or error
        """
        # Ensure required fields
        if "name" not in workflow_data:
            workflow_data["name"] = f"Jarvis Workflow {datetime.now().strftime('%Y%m%d_%H%M%S')}"

        if "nodes" not in workflow_data:
            workflow_data["nodes"] = []

        if "connections" not in workflow_data:
            workflow_data["connections"] = {}

        # n8n API treats `active` as read-only on create; never send it
        workflow_data.pop("active", None)

        result = self._request("POST", "/workflows", workflow_data)

        if "error" not in result:
            log_with_context(logger, "info", "Workflow created",
                           workflow_id=result.get("id"),
                           name=workflow_data["name"])

        return result

    def update_workflow(self, workflow_id: str, workflow_data: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing workflow."""
        # n8n API uses PUT for workflow updates
        result = self._request("PUT", f"/workflows/{workflow_id}", workflow_data)

        if "error" not in result:
            log_with_context(logger, "info", "Workflow updated",
                           workflow_id=workflow_id)

        return result

    def activate_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """Activate a workflow using the dedicated activation endpoint."""
        # n8n API v1 has dedicated endpoints for activation
        result = self._request("POST", f"/workflows/{workflow_id}/activate")

        if "error" not in result:
            log_with_context(logger, "info", "Workflow activated",
                           workflow_id=workflow_id)

        return result

    def deactivate_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """Deactivate a workflow using the dedicated deactivation endpoint."""
        result = self._request("POST", f"/workflows/{workflow_id}/deactivate")

        if "error" not in result:
            log_with_context(logger, "info", "Workflow deactivated",
                           workflow_id=workflow_id)

        return result

    def delete_workflow(self, workflow_id: str) -> Dict[str, Any]:
        """Delete a workflow."""
        result = self._request("DELETE", f"/workflows/{workflow_id}")

        if "error" not in result:
            log_with_context(logger, "info", "Workflow deleted",
                           workflow_id=workflow_id)

        return result

    def execute_workflow(self, workflow_id: str, data: Dict = None) -> Dict[str, Any]:
        """
        Execute a workflow manually.

        Args:
            workflow_id: ID of workflow to execute
            data: Optional input data for the workflow

        Returns:
            Execution result
        """
        body = {"workflowData": data} if data else {}
        return self._request("POST", f"/workflows/{workflow_id}/execute", body)

    def list_executions(
        self,
        workflow_id: Optional[str] = None,
        limit: int = 20,
        status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """List executions (optionally filtered by workflow ID)."""
        params: Dict[str, Any] = {"limit": limit}
        if workflow_id:
            params["workflowId"] = workflow_id
        if status:
            params["status"] = status

        result = self._request("GET", "/executions", params=params)
        if "error" in result:
            return []
        return result.get("data", []) if isinstance(result, dict) else []

    def get_last_execution(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """Get the last execution for a workflow."""
        executions = self.list_executions(workflow_id=workflow_id, limit=1)
        return executions[0] if executions else None

    # ============ Workflow Audit Helpers ============

    def audit_workflow(self, workflow: Dict[str, Any]) -> Dict[str, Any]:
        """Audit a workflow for basic reliability patterns."""
        nodes = workflow.get("nodes", []) or []
        node_types = {n.get("type") for n in nodes}
        retry_enabled = any(n.get("parameters", {}).get("retryOnFail") for n in nodes)

        audit = {
            "workflow_id": workflow.get("id"),
            "name": workflow.get("name"),
            "active": workflow.get("active", False),
            "patterns": {
                "error_trigger": "n8n-nodes-base.errorTrigger" in node_types,
                "retry_on_fail": bool(retry_enabled),
                "rate_limit": "n8n-nodes-base.rateLimit" in node_types,
                "wait_backoff": "n8n-nodes-base.wait" in node_types
            }
        }

        return audit

    def audit_workflows(self) -> List[Dict[str, Any]]:
        """Audit all workflows and return summary list."""
        workflows = self.list_workflows()
        return [self.audit_workflow(w) for w in workflows]

    def _find_workflow_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Find a workflow by exact name."""
        for workflow in self.list_workflows():
            if workflow.get("name") == name:
                return workflow
        return None

    def create_error_handler_workflow(self, name: str = "Jarvis Error Handler") -> Dict[str, Any]:
        """Create a global error handler workflow (Error Trigger -> Telegram alert)."""
        workflow = {
            "name": name,
            "nodes": [
                {
                    "id": "error_trigger",
                    "name": "Error Trigger",
                    "type": "n8n-nodes-base.errorTrigger",
                    "typeVersion": 1,
                    "position": [250, 300],
                    "parameters": {}
                },
                {
                    "id": "format_alert",
                    "name": "Format Alert",
                    "type": "n8n-nodes-base.set",
                    "typeVersion": 1,
                    "position": [450, 300],
                    "parameters": {
                        "values": {
                            "json": {
                                "message": "={{ 'n8n workflow failed: ' + ($json.error?.message || $json.error || 'unknown error') }}",
                                "level": "error"
                            }
                        },
                        "options": {}
                    }
                },
                {
                    "id": "send_alert",
                    "name": "Send Telegram Alert",
                    "type": "n8n-nodes-base.httpRequest",
                    "typeVersion": 3,
                    "position": [650, 300],
                    "parameters": {
                        "method": "POST",
                        "url": "http://ingestion:8000/telegram/send_alert",
                        "sendBody": True,
                        "bodyType": "json",
                        "jsonBody": "={{ $json }}"
                    }
                }
            ],
            "connections": {
                "error_trigger": {
                    "main": [
                        [{"node": "format_alert", "type": "main", "index": 0}]
                    ]
                },
                "format_alert": {
                    "main": [
                        [{"node": "send_alert", "type": "main", "index": 0}]
                    ]
                }
            }
        }

        return self.create_workflow(workflow)

    def ensure_error_handler_workflow(self) -> Optional[str]:
        """Ensure the global error handler exists and return its workflow ID."""
        existing = self._find_workflow_by_name("Jarvis Error Handler")
        if existing:
            return existing.get("id")

        created = self.create_error_handler_workflow()
        return created.get("id") if isinstance(created, dict) else None

    def apply_error_workflow_to_all(self, error_workflow_id: str) -> Dict[str, Any]:
        """Apply error workflow setting to all workflows except the error handler itself."""
        workflows = self.list_workflows()
        updated = 0
        skipped = 0
        errors = 0
        error_samples: List[Dict[str, Any]] = []

        for workflow in workflows:
            workflow_id = workflow.get("id")
            if not workflow_id or workflow_id == error_workflow_id:
                skipped += 1
                continue

            full_workflow = self.get_workflow(workflow_id)
            if not isinstance(full_workflow, dict) or full_workflow.get("error"):
                errors += 1
                if len(error_samples) < 5:
                    error_samples.append({
                        "workflow_id": workflow_id,
                        "error": full_workflow.get("error") if isinstance(full_workflow, dict) else "unknown"
                    })
                continue

            settings = dict(full_workflow.get("settings") or {})
            settings["errorWorkflow"] = error_workflow_id

            payload = {
                "name": full_workflow.get("name"),
                "nodes": full_workflow.get("nodes", []),
                "connections": full_workflow.get("connections", {}),
                "settings": settings,
                "staticData": full_workflow.get("staticData"),
                "meta": full_workflow.get("meta"),
                "pinData": full_workflow.get("pinData")
            }

            result = self.update_workflow(workflow_id, payload)
            if isinstance(result, dict) and result.get("error"):
                errors += 1
                if len(error_samples) < 5:
                    error_samples.append({
                        "workflow_id": workflow_id,
                        "error": result.get("error")
                    })
            else:
                updated += 1

        return {
            "error_workflow_id": error_workflow_id,
            "updated": updated,
            "skipped": skipped,
            "errors": errors,
            "error_samples": error_samples,
            "total": len(workflows)
        }

    # ============ Jarvis-specific Workflows ============

    def create_jarvis_webhook_workflow(
        self,
        name: str,
        webhook_path: str,
        target_url: str,
        method: str = "POST"
    ) -> Dict[str, Any]:
        """
        Create a simple webhook → HTTP request workflow.

        Args:
            name: Workflow name
            webhook_path: Path for the webhook (e.g., "jarvis-ingest")
            target_url: URL to forward the webhook data to
            method: HTTP method for the target

        Returns:
            Created workflow
        """
        workflow = {
            "name": name,
            "active": False,
            "nodes": [
                {
                    "id": "webhook",
                    "name": "Webhook",
                    "type": "n8n-nodes-base.webhook",
                    "typeVersion": 1,
                    "position": [250, 300],
                    "parameters": {
                        "path": webhook_path,
                        "responseMode": "responseNode",
                        "options": {}
                    }
                },
                {
                    "id": "http_request",
                    "name": "HTTP Request",
                    "type": "n8n-nodes-base.httpRequest",
                    "typeVersion": 3,
                    "position": [450, 300],
                    "parameters": {
                        "method": method,
                        "url": target_url,
                        "sendBody": True,
                        "bodyType": "json",
                        "jsonBody": "={{ $json }}"
                    }
                },
                {
                    "id": "response",
                    "name": "Respond to Webhook",
                    "type": "n8n-nodes-base.respondToWebhook",
                    "typeVersion": 1,
                    "position": [650, 300],
                    "parameters": {
                        "respondWith": "json",
                        "responseBody": '={{ $json }}',
                        "options": {}
                    }
                }
            ],
            "connections": {
                "webhook": {
                    "main": [
                        [{"node": "http_request", "type": "main", "index": 0}]
                    ]
                },
                "http_request": {
                    "main": [
                        [{"node": "response", "type": "main", "index": 0}]
                    ]
                }
            }
        }

        return self.create_workflow(workflow)

    def create_scheduled_jarvis_task(
        self,
        name: str,
        cron_expression: str,
        jarvis_endpoint: str,
        task_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Create a scheduled task that calls a Jarvis endpoint.

        Args:
            name: Workflow name
            cron_expression: Cron expression (e.g., "0 9 * * 1" for Monday 9am)
            jarvis_endpoint: Jarvis API endpoint to call
            task_data: Data to send to the endpoint

        Returns:
            Created workflow
        """
        workflow = {
            "name": name,
            "active": False,
            "nodes": [
                {
                    "id": "cron",
                    "name": "Cron",
                    "type": "n8n-nodes-base.cron",
                    "typeVersion": 1,
                    "position": [250, 300],
                    "parameters": {
                        "cronExpression": cron_expression
                    }
                },
                {
                    "id": "set_data",
                    "name": "Set Task Data",
                    "type": "n8n-nodes-base.set",
                    "typeVersion": 1,
                    "position": [450, 300],
                    "parameters": {
                        "values": {
                            "json": task_data
                        },
                        "options": {}
                    }
                },
                {
                    "id": "jarvis_api",
                    "name": "Call Jarvis",
                    "type": "n8n-nodes-base.httpRequest",
                    "typeVersion": 3,
                    "position": [650, 300],
                    "parameters": {
                        "method": "POST",
                        "url": f"http://ingestion:8000{jarvis_endpoint}",
                        "sendBody": True,
                        "bodyType": "json",
                        "jsonBody": "={{ $json }}"
                    }
                }
            ],
            "connections": {
                "cron": {
                    "main": [
                        [{"node": "set_data", "type": "main", "index": 0}]
                    ]
                },
                "set_data": {
                    "main": [
                        [{"node": "jarvis_api", "type": "main", "index": 0}]
                    ]
                }
            }
        }

        return self.create_workflow(workflow)

    def create_email_to_jarvis_workflow(self) -> Dict[str, Any]:
        """
        Create workflow: Gmail → Parse → Jarvis ingestion.

        Returns:
            Created workflow
        """
        workflow = {
            "name": "Email to Jarvis",
            "active": False,
            "nodes": [
                {
                    "id": "gmail_trigger",
                    "name": "Gmail Trigger",
                    "type": "n8n-nodes-base.gmailTrigger",
                    "typeVersion": 1,
                    "position": [250, 300],
                    "credentials": {
                        "gmailOAuth2": {
                            "id": "1",  # Needs to be configured in n8n
                            "name": "Gmail Projektil"
                        }
                    },
                    "parameters": {
                        "pollTimes": {
                            "item": [
                                {"mode": "everyMinute"}
                            ]
                        },
                        "simple": False,
                        "filters": {}
                    }
                },
                {
                    "id": "extract_data",
                    "name": "Extract Email Data",
                    "type": "n8n-nodes-base.set",
                    "typeVersion": 1,
                    "position": [450, 300],
                    "parameters": {
                        "values": {
                            "json": {
                                "email_id": "={{ $json.id }}",
                                "from": "={{ $json.from.value[0].address }}",
                                "subject": "={{ $json.subject }}",
                                "body": "={{ $json.text }}",
                                "date": "={{ $json.date }}",
                                "namespace": "work_projektil"
                            }
                        }
                    }
                },
                {
                    "id": "ingest_to_jarvis",
                    "name": "Send to Jarvis",
                    "type": "n8n-nodes-base.httpRequest",
                    "typeVersion": 3,
                    "position": [650, 300],
                    "parameters": {
                        "method": "POST",
                        "url": "http://ingestion:8000/ingest/email",
                        "sendBody": True,
                        "bodyType": "json",
                        "jsonBody": "={{ $json }}"
                    }
                }
            ],
            "connections": {
                "gmail_trigger": {
                    "main": [
                        [{"node": "extract_data", "type": "main", "index": 0}]
                    ]
                },
                "extract_data": {
                    "main": [
                        [{"node": "ingest_to_jarvis", "type": "main", "index": 0}]
                    ]
                }
            }
        }

        return self.create_workflow(workflow)


# ============ Convenience Functions ============

def get_workflow_templates() -> Dict[str, Any]:
    """Get available Jarvis workflow templates."""
    return {
        "webhook_forwarder": {
            "description": "Simple webhook that forwards data to another endpoint",
            "params": ["name", "webhook_path", "target_url", "method"]
        },
        "scheduled_task": {
            "description": "Scheduled task that calls Jarvis API",
            "params": ["name", "cron_expression", "jarvis_endpoint", "task_data"]
        },
        "email_ingestion": {
            "description": "Gmail trigger that sends emails to Jarvis",
            "params": []  # Uses predefined configuration
        },
        "drive_sync": {
            "description": "Periodic Google Drive synchronization",
            "params": ["folder_id", "sync_interval"]
        },
        "weekly_briefing": {
            "description": "Weekly summary generation and delivery",
            "params": ["delivery_time", "recipients"]
        }
    }


def create_workflow_from_template(
    template_name: str,
    params: Dict[str, Any]
) -> Dict[str, Any]:
    """Create a workflow from a template."""
    manager = N8NWorkflowManager()

    if template_name == "webhook_forwarder":
        return manager.create_jarvis_webhook_workflow(**params)

    elif template_name == "scheduled_task":
        return manager.create_scheduled_jarvis_task(**params)

    elif template_name == "email_ingestion":
        return manager.create_email_to_jarvis_workflow()

    else:
        return {
            "error": f"Unknown template: {template_name}",
            "available": list(get_workflow_templates().keys())
        }


def get_n8n_workflow_status() -> Dict[str, Any]:
    """Get status of n8n workflow management capability."""
    manager = N8NWorkflowManager()

    try:
        workflows = manager.list_workflows()
        active_count = sum(1 for w in workflows if w.get("active", False))

        return {
            "available": True,
            "api_configured": bool(N8N_API_KEY),
            "base_url": N8N_API_BASE,
            "workflows": {
                "total": len(workflows),
                "active": active_count
            },
            "templates": get_workflow_templates()
        }
    except Exception as e:
        return {
            "available": False,
            "error": str(e),
            "api_configured": bool(N8N_API_KEY)
        }