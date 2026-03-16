# Add this to your FastAPI app to mount the dashboard
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from .dashboard import backend as dashboard_backend


def mount_dashboard(app: FastAPI):
    # Mount REST/WebSocket API
    app.include_router(dashboard_backend.router)
    # Serve static dashboard UI
    app.mount("/dashboard", StaticFiles(directory="dashboard", html=True), name="dashboard")
