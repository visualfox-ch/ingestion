
# FastAPI endpoints for dashboard task status
from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()
@router.get("/tasks", response_class=JSONResponse)
async def get_tasks():
    tasks = [
        {"id": 12, "name": "API-Endpunkte", "status": "in-progress"},
        {"id": 13, "name": "Dashboard", "status": "in-progress"},
        {"id": 14, "name": "Plugin-System", "status": "not-started"},
        {"id": 15, "name": "Tests", "status": "not-started"},
        {"id": 16, "name": "Dokumentation", "status": "not-started"}
    ]
    return {"tasks": tasks}

@router.get("/alerts", response_class=JSONResponse)
async def get_alerts():
    alerts = [
        "Task 13: Dashboard Monitoring in-progress",
        "Task 12: API-Endpunkte running",
        # Add more alerts as needed
    ]
    return {"alerts": alerts}
