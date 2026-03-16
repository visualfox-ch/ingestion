from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()

@router.get("/services", response_class=JSONResponse)
def get_services():
    services = [
        {"name": "Qdrant", "status": "healthy", "version": "1.16.3", "config": "host: qdrant:6333"},
        {"name": "Postgres", "status": "healthy", "version": "15.8", "config": "db: jarvis"},
        {"name": "Meilisearch", "status": "healthy", "version": "1.34.3", "config": "host: meilisearch:7700"},
        {"name": "n8n", "status": "healthy", "version": "1.121.0", "config": "host: n8n:5678"}
    ]
    return {"services": services}

