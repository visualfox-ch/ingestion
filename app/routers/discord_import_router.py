"""
Discord Import API Router

REST endpoints for importing and searching Discord exports.
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/discord", tags=["discord"])


# =============================================================================
# Request/Response Models
# =============================================================================


class ImportResultResponse(BaseModel):
    """Import result response."""
    file_path: str
    success: bool
    messages_imported: int
    messages_skipped: int
    server_name: str
    channel_name: str
    error: Optional[str]
    duration_ms: float


class SearchResultResponse(BaseModel):
    """Search result response."""
    score: float
    message_id: str
    content: str
    author: str
    channel: str
    server: str
    timestamp: Optional[str]


class StatsResponse(BaseModel):
    """Discord stats response."""
    collection: str
    total_messages: int
    vectors_count: int
    status: str


class FileInfoResponse(BaseModel):
    """Import file info."""
    name: str
    path: str
    size_bytes: int
    modified: str


class HealthResponse(BaseModel):
    """Service health."""
    status: str
    import_dir: str
    files_available: int
    messages_indexed: int


# =============================================================================
# Endpoints
# =============================================================================


@router.get("/health", response_model=HealthResponse)
async def discord_health():
    """Check Discord import service health."""
    try:
        from ..services.discord_importer import get_discord_importer

        importer = get_discord_importer()
        files = importer.list_import_files()
        stats = await importer.get_stats()

        return HealthResponse(
            status="healthy",
            import_dir=str(importer._import_dir),
            files_available=len(files),
            messages_indexed=stats.get("total_messages", 0),
        )

    except Exception as e:
        logger.error(f"Discord health check failed: {e}")
        return HealthResponse(
            status="error",
            import_dir="",
            files_available=0,
            messages_indexed=0,
        )


@router.get("/stats", response_model=StatsResponse)
async def get_stats():
    """Get Discord indexing statistics."""
    try:
        from ..services.discord_importer import get_discord_importer

        importer = get_discord_importer()
        stats = await importer.get_stats()

        if "error" in stats:
            raise HTTPException(status_code=500, detail=stats["error"])

        return StatsResponse(**stats)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/files", response_model=List[FileInfoResponse])
async def list_import_files():
    """List available import files."""
    try:
        from ..services.discord_importer import get_discord_importer

        importer = get_discord_importer()
        files = importer.list_import_files()

        return [FileInfoResponse(**f) for f in files]

    except Exception as e:
        logger.error(f"Failed to list files: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/import", response_model=ImportResultResponse)
async def import_file(file_path: str):
    """
    Import a Discord export file.

    The file should be a JSON export from DiscordChatExporter.
    """
    try:
        from ..services.discord_importer import get_discord_importer

        importer = get_discord_importer()
        result = await importer.import_file(file_path)

        return ImportResultResponse(**result.to_dict())

    except Exception as e:
        logger.error(f"Import failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/import-all", response_model=List[ImportResultResponse])
async def import_all_files(directory: Optional[str] = None):
    """
    Import all JSON files from a directory.

    Uses default import directory if not specified.
    """
    try:
        from ..services.discord_importer import get_discord_importer

        importer = get_discord_importer()
        results = await importer.import_directory(directory)

        return [ImportResultResponse(**r.to_dict()) for r in results]

    except Exception as e:
        logger.error(f"Import all failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/upload")
async def upload_and_import(file: UploadFile = File(...)):
    """
    Upload a Discord export JSON and import it.
    """
    try:
        from ..services.discord_importer import get_discord_importer
        import aiofiles
        from pathlib import Path

        if not file.filename.endswith(".json"):
            raise HTTPException(status_code=400, detail="File must be a JSON export")

        importer = get_discord_importer()

        # Save uploaded file
        save_path = importer._import_dir / file.filename
        async with aiofiles.open(save_path, "wb") as f:
            content = await file.read()
            await f.write(content)

        # Import the file
        result = await importer.import_file(save_path)

        return ImportResultResponse(**result.to_dict())

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Upload failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/search", response_model=List[SearchResultResponse])
async def search_messages(
    q: str = Query(..., min_length=2, description="Search query"),
    limit: int = Query(20, ge=1, le=100, description="Max results"),
    server: Optional[str] = Query(None, description="Filter by server name"),
    channel: Optional[str] = Query(None, description="Filter by channel name"),
    author: Optional[str] = Query(None, description="Filter by author name"),
):
    """
    Search Discord messages.

    Performs semantic search across all indexed Discord messages.
    """
    try:
        from ..services.discord_importer import get_discord_importer

        importer = get_discord_importer()
        results = await importer.search(
            query=q,
            limit=limit,
            server_name=server,
            channel_name=channel,
            author_name=author,
        )

        return [SearchResultResponse(**r) for r in results]

    except Exception as e:
        logger.error(f"Search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
