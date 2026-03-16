"""
Dashboard package shim.

Defines mount_dashboard and keeps legacy dashboard endpoints compatible.
"""
import os

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import api
from . import api_incidents
from . import api_services
from . import websocket


def mount_dashboard(app) -> None:
    router = APIRouter()

    base_dir = os.path.abspath(os.path.dirname(__file__))
    templates_dir = os.path.join(base_dir, "templates")
    dashboard_dir = os.path.join(base_dir, "static")
    incidents_html = os.path.join(templates_dir, "incidents", "incidents.html")
    services_html = os.path.join(templates_dir, "services", "services.html")
    asana_html = os.path.join(templates_dir, "asana_credentials.html")
    classic_dashboard = os.path.join(base_dir, "..", "static", "dashboard.html")

    # Serve classic dashboard by default; fallback to React UI if missing.
    @router.get("/dashboard", include_in_schema=False)
    async def _dashboard():
        index_html = os.path.join(dashboard_dir, "index.html")
        if os.path.exists(classic_dashboard):
            return FileResponse(classic_dashboard, media_type="text/html")
        return FileResponse(index_html, media_type="text/html")

    @router.get("/dashboard/incidents", include_in_schema=False)
    async def _incidents():
        return FileResponse(incidents_html, media_type="text/html")

    @router.get("/dashboard/services", include_in_schema=False)
    async def _services():
        return FileResponse(services_html, media_type="text/html")

    @router.get("/dashboard/asana-credentials", include_in_schema=False)
    async def _asana_credentials():
        return FileResponse(asana_html, media_type="text/html")

    app.mount("/dashboard/static", StaticFiles(directory=dashboard_dir), name="dashboard-static")
    app.include_router(router)
    app.include_router(api.router, prefix="/dashboard")
    app.include_router(websocket.router, prefix="/dashboard")
    app.include_router(api_incidents.router, prefix="/dashboard/api")
    app.include_router(api_services.router, prefix="/dashboard/api")

    # Legacy API routes for classic dashboard compatibility.
    legacy_router = APIRouter()

    @legacy_router.get("/api/task-status")
    async def legacy_task_status():
        data = await api.get_tasks()
        return JSONResponse(data)

    @legacy_router.get("/api/alerts")
    async def legacy_alerts():
        data = await api.get_alerts()
        return JSONResponse(data)

    app.include_router(legacy_router)
