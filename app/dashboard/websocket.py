# FastAPI WebSocket support for real-time dashboard updates
# Replaces Flask-SocketIO with native FastAPI WebSockets

import asyncio
import json
from datetime import datetime
from typing import Set, Dict, Any, Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from ..observability import get_logger

logger = get_logger("jarvis.dashboard.websocket")

router = APIRouter()


class ConnectionManager:
    """Manages WebSocket connections for real-time updates."""

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket):
        """Accept and register a new WebSocket connection."""
        await websocket.accept()
        async with self._lock:
            self.active_connections.add(websocket)
        logger.info(f"WebSocket connected. Total connections: {len(self.active_connections)}")

    async def disconnect(self, websocket: WebSocket):
        """Remove a WebSocket connection."""
        async with self._lock:
            self.active_connections.discard(websocket)
        logger.info(f"WebSocket disconnected. Total connections: {len(self.active_connections)}")

    async def broadcast(self, message: Dict[str, Any]):
        """Broadcast a message to all connected clients."""
        if not self.active_connections:
            return

        message_json = json.dumps(message)
        disconnected = set()

        async with self._lock:
            for connection in self.active_connections:
                try:
                    await connection.send_text(message_json)
                except Exception as e:
                    logger.warning(f"Failed to send to WebSocket: {e}")
                    disconnected.add(connection)

            # Clean up disconnected clients
            self.active_connections -= disconnected

    async def send_personal(self, websocket: WebSocket, message: Dict[str, Any]):
        """Send a message to a specific client."""
        try:
            await websocket.send_text(json.dumps(message))
        except Exception as e:
            logger.warning(f"Failed to send personal message: {e}")


# Global connection manager
manager = ConnectionManager()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    Main WebSocket endpoint for real-time dashboard updates.

    Clients can subscribe to different event types:
    - health: System health updates
    - tasks: Task status changes
    - alerts: Alert notifications
    - metrics: Performance metrics

    Message format:
    {
        "type": "subscribe" | "unsubscribe" | "ping",
        "channels": ["health", "tasks", "alerts", "metrics"]
    }
    """
    await manager.connect(websocket)

    # Send initial connection confirmation
    await manager.send_personal(websocket, {
        "type": "connected",
        "timestamp": datetime.utcnow().isoformat(),
        "message": "Connected to Jarvis Dashboard WebSocket"
    })

    try:
        while True:
            # Wait for messages from client
            data = await websocket.receive_text()

            try:
                message = json.loads(data)
                msg_type = message.get("type", "")

                if msg_type == "ping":
                    await manager.send_personal(websocket, {
                        "type": "pong",
                        "timestamp": datetime.utcnow().isoformat()
                    })

                elif msg_type == "subscribe":
                    channels = message.get("channels", [])
                    await manager.send_personal(websocket, {
                        "type": "subscribed",
                        "channels": channels,
                        "timestamp": datetime.utcnow().isoformat()
                    })

                elif msg_type == "request_health":
                    # On-demand health request
                    health = await _get_health_summary()
                    await manager.send_personal(websocket, {
                        "type": "health",
                        "data": health,
                        "timestamp": datetime.utcnow().isoformat()
                    })

                elif msg_type == "request_tasks":
                    # On-demand task status request
                    tasks = await _get_task_status()
                    await manager.send_personal(websocket, {
                        "type": "tasks",
                        "data": tasks,
                        "timestamp": datetime.utcnow().isoformat()
                    })

            except json.JSONDecodeError:
                await manager.send_personal(websocket, {
                    "type": "error",
                    "message": "Invalid JSON",
                    "timestamp": datetime.utcnow().isoformat()
                })

    except WebSocketDisconnect:
        await manager.disconnect(websocket)


async def _get_health_summary() -> Dict[str, Any]:
    """Get current health summary for WebSocket broadcast."""
    try:
        from ..routers.health_router import health_check
        return health_check()
    except Exception as e:
        logger.error(f"Failed to get health summary: {e}")
        return {"status": "error", "error": str(e)}


async def _get_task_status() -> Dict[str, Any]:
    """Get current task status from TASKS.md."""
    try:
        import re
        from pathlib import Path

        tasks_file = Path("/brain/system/docker/TASKS.md")
        if not tasks_file.exists():
            return {"tasks": [], "error": "TASKS.md not found"}

        content = tasks_file.read_text()

        # Parse P1 and P2 tasks
        tasks = []

        # Find P1 section
        p1_match = re.search(r'### P1.*?\n(.*?)(?=###|\Z)', content, re.DOTALL)
        if p1_match:
            for line in p1_match.group(1).split('\n'):
                if line.strip().startswith('- ['):
                    completed = '[x]' in line
                    task_text = re.sub(r'- \[.\] ', '', line.strip())
                    tasks.append({
                        "priority": "P1",
                        "task": task_text[:80],
                        "completed": completed
                    })

        # Find P2 section
        p2_match = re.search(r'### P2.*?\n(.*?)(?=##|\Z)', content, re.DOTALL)
        if p2_match:
            for line in p2_match.group(1).split('\n'):
                if line.strip().startswith('- ['):
                    completed = '[x]' in line
                    task_text = re.sub(r'- \[.\] ', '', line.strip())
                    tasks.append({
                        "priority": "P2",
                        "task": task_text[:80],
                        "completed": completed
                    })

        return {"tasks": tasks, "count": len(tasks)}

    except Exception as e:
        logger.error(f"Failed to get task status: {e}")
        return {"tasks": [], "error": str(e)}


# Broadcast functions for external use
async def broadcast_health_update(health_data: Dict[str, Any]):
    """Broadcast health update to all connected clients."""
    await manager.broadcast({
        "type": "health",
        "data": health_data,
        "timestamp": datetime.utcnow().isoformat()
    })


async def broadcast_alert(alert: str, level: str = "info"):
    """Broadcast an alert to all connected clients."""
    await manager.broadcast({
        "type": "alert",
        "data": {
            "message": alert,
            "level": level
        },
        "timestamp": datetime.utcnow().isoformat()
    })


async def broadcast_task_update(task_id: str, status: str, details: Optional[str] = None):
    """Broadcast task status update to all connected clients."""
    await manager.broadcast({
        "type": "task_update",
        "data": {
            "task_id": task_id,
            "status": status,
            "details": details
        },
        "timestamp": datetime.utcnow().isoformat()
    })


async def broadcast_metrics(metrics: Dict[str, Any]):
    """Broadcast performance metrics to all connected clients."""
    await manager.broadcast({
        "type": "metrics",
        "data": metrics,
        "timestamp": datetime.utcnow().isoformat()
    })


def get_connection_count() -> int:
    """Get the number of active WebSocket connections."""
    return len(manager.active_connections)
