from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()

@router.get("/incidents", response_class=JSONResponse)
def get_incidents():
    incidents = [
        {"id": 1, "type": "Service", "status": "ok", "timestamp": "2026-02-08T20:15:14", "details": "All healthy"},
        {"id": 2, "type": "Database", "status": "warning", "timestamp": "2026-02-08T19:55:10", "details": "Postgres slow"},
        {"id": 3, "type": "API", "status": "critical", "timestamp": "2026-02-08T19:30:01", "details": "Health fetch failed"}
    ]
    return {"incidents": incidents}

