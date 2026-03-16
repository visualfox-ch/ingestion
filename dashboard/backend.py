# FastAPI WebSocket/REST backend for Jarvis Dashboard
# Provides endpoints for task status, alerts, and live updates

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from fastapi.responses import JSONResponse
from typing import List, Dict, Any
from starlette.websockets import WebSocketState
from .task_status import get_all_task_status, get_alerts
from app.api.auth import get_current_user  # Reuse existing auth

router = APIRouter()

# In-memory connection manager for WebSocket clients
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: Dict[str, Any]):
        for connection in self.active_connections:
            if connection.application_state == WebSocketState.CONNECTED:
                await connection.send_json(message)

manager = ConnectionManager()

@router.get("/dashboard/tasks", response_class=JSONResponse)
async def dashboard_tasks(user=Depends(get_current_user)):
    """Return current status of all tasks."""
    return get_all_task_status()

@router.get("/dashboard/alerts", response_class=JSONResponse)
async def dashboard_alerts(user=Depends(get_current_user)):
    """Return current alerts/errors."""
    return get_alerts()

@router.websocket("/dashboard/ws")
async def dashboard_ws(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()  # Optionally handle pings
            # No-op: dashboard is push-only for now
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# Example: function to push updates (to be called by task/alert logic)
async def push_dashboard_update(event: Dict[str, Any]):
    await manager.broadcast(event)
