"""
Data Import Router
Phase 19.3: Unified import endpoints for chat, email, and knowledge

Provides simple endpoints to import:
- Telegram chat history
- WhatsApp chat exports
- Google Chat exports
- Email (Gmail API or files)
- Personal knowledge/facts
"""

import os
import hashlib
from datetime import datetime
from typing import List, Optional, Dict, Any
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, UploadFile, File, BackgroundTasks
from pydantic import BaseModel, Field

from ..observability import get_logger, log_with_context

logger = get_logger("jarvis.data_import")
router = APIRouter(prefix="/import", tags=["data-import"])


# =============================================================================
# Request/Response Models
# =============================================================================

class ImportResult(BaseModel):
    """Result of an import operation."""
    status: str
    source: str
    items_found: int = 0
    items_imported: int = 0
    items_skipped: int = 0
    errors: List[str] = []
    details: Dict[str, Any] = {}


class PersonalFactRequest(BaseModel):
    """Request to add a personal fact."""
    category: str = Field(..., description="Category: identity, adhd, work, communication, technical, project")
    fact: str = Field(..., description="The fact to remember")
    confidence: float = Field(0.9, ge=0, le=1)
    source: str = Field("user", description="Source of the fact")


# =============================================================================
# PERSONAL KNOWLEDGE ENDPOINTS
# =============================================================================

@router.post("/personal-knowledge/seed", response_model=ImportResult)
async def seed_personal_knowledge():
    """
    Seed initial personal knowledge about Micha.

    This populates facts about ADHD preferences, communication style,
    work context, and other personal information.
    """
    try:
        from ..services.personal_knowledge_seeder import seed_all

        results = seed_all()

        memory_stats = results.get("memory_store", {})
        qdrant_stats = results.get("qdrant", {})

        return ImportResult(
            status="completed",
            source="personal_knowledge_seeder",
            items_found=len(results.get("memory_store", {}).get("added", 0)) +
                       len(results.get("memory_store", {}).get("skipped", 0)),
            items_imported=memory_stats.get("added", 0),
            items_skipped=memory_stats.get("skipped", 0),
            details={
                "memory_store": memory_stats,
                "qdrant": qdrant_stats,
            }
        )

    except Exception as e:
        logger.error(f"Personal knowledge seeding failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/personal-knowledge/fact", response_model=ImportResult)
async def add_personal_fact(request: PersonalFactRequest):
    """
    Add a single personal fact.

    Categories: identity, adhd, work, communication, technical, project
    """
    try:
        from ..services.personal_knowledge_seeder import add_custom_fact

        success = add_custom_fact(
            category=request.category,
            fact=request.fact,
            confidence=request.confidence,
            source=request.source
        )

        return ImportResult(
            status="completed" if success else "failed",
            source="user_input",
            items_found=1,
            items_imported=1 if success else 0,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/personal-knowledge/facts")
async def list_personal_facts(category: Optional[str] = None, limit: int = 50):
    """
    List all personal facts, optionally filtered by category.
    """
    try:
        from .. import memory_store

        facts = memory_store.get_facts(category=category, limit=limit)

        return {
            "facts": facts,
            "count": len(facts),
            "category_filter": category,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# TELEGRAM IMPORT ENDPOINTS
# =============================================================================

@router.post("/telegram/folder", response_model=ImportResult)
async def import_telegram_folder(
    folder_path: str = Query(..., description="Path to Telegram export folder"),
    namespace: str = Query("private", description="Namespace: private, work_projektil, work_visualfox"),
    background_tasks: BackgroundTasks = None
):
    """
    Import Telegram chat history from an export folder.

    Telegram Desktop export creates folders with result.json files.
    This endpoint parses all chats and imports them to Qdrant.
    """
    try:
        from ..chat_telegram import parse_telegram_folder, window_messages, get_chat_summary
        from ..embed import embed_texts
        from ..qdrant_upsert import upsert_points

        # Parse all Telegram exports
        messages = parse_telegram_folder(folder_path)

        if not messages:
            return ImportResult(
                status="completed",
                source="telegram",
                items_found=0,
                details={"message": "No messages found in folder"}
            )

        summary = get_chat_summary(messages)

        # Create windows and embed
        windows = list(window_messages(messages, window_size=10, overlap=8))

        if not windows:
            return ImportResult(
                status="completed",
                source="telegram",
                items_found=len(messages),
                items_imported=0,
                details={"summary": summary}
            )

        # Embed texts
        texts = [w["text"] for w in windows]
        embeddings = embed_texts(texts)

        # Create points for Qdrant
        points = []
        for window, embedding in zip(windows, embeddings):
            point_id = hash(window["content_hash"]) & 0x7FFFFFFFFFFFFFFF

            points.append({
                "id": point_id,
                "vector": embedding,
                "payload": {
                    "text": window["text"],
                    "doc_type": "chat_window",
                    "channel": f"telegram:{window['chat_name']}",
                    "chat_type": window["chat_type"],
                    "message_count": window["message_count"],
                    "content_hash": window["content_hash"],
                    "event_ts": window["first_timestamp"],
                    "created_at": datetime.utcnow().isoformat(),
                }
            })

        # Upsert to Qdrant
        collection = f"jarvis_{namespace}"
        upsert_points(collection, points)

        return ImportResult(
            status="completed",
            source="telegram",
            items_found=len(messages),
            items_imported=len(points),
            details={
                "summary": summary,
                "windows_created": len(windows),
                "collection": collection,
            }
        )

    except Exception as e:
        logger.error(f"Telegram import failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# WHATSAPP IMPORT ENDPOINTS
# =============================================================================

@router.post("/whatsapp/file", response_model=ImportResult)
async def import_whatsapp_file(
    file_path: str = Query(..., description="Path to WhatsApp export .txt file"),
    namespace: str = Query("private", description="Namespace")
):
    """
    Import a single WhatsApp chat export file.

    WhatsApp exports are .txt files with format:
    [DD.MM.YY, HH:MM:SS] Name: message
    """
    try:
        from ..chat_whatsapp import parse_whatsapp_file, window_messages
        from ..embed import embed_texts
        from ..qdrant_upsert import upsert_points

        messages = parse_whatsapp_file(file_path)

        if not messages:
            return ImportResult(
                status="completed",
                source="whatsapp",
                items_found=0,
            )

        windows = list(window_messages(messages))
        texts = [w["text"] for w in windows]
        embeddings = embed_texts(texts)

        points = []
        for window, embedding in zip(windows, embeddings):
            point_id = hash(window["content_hash"]) & 0x7FFFFFFFFFFFFFFF
            points.append({
                "id": point_id,
                "vector": embedding,
                "payload": {
                    "text": window["text"],
                    "doc_type": "chat_window",
                    "channel": f"whatsapp:{window.get('channel', 'unknown')}",
                    "content_hash": window["content_hash"],
                    "event_ts": window.get("first_timestamp", ""),
                    "created_at": datetime.utcnow().isoformat(),
                }
            })

        collection = f"jarvis_{namespace}"
        upsert_points(collection, points)

        return ImportResult(
            status="completed",
            source="whatsapp",
            items_found=len(messages),
            items_imported=len(points),
            details={"collection": collection}
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/whatsapp/folder", response_model=ImportResult)
async def import_whatsapp_folder(
    folder_path: str = Query(..., description="Path to folder with WhatsApp .txt exports"),
    namespace: str = Query("private", description="Namespace")
):
    """
    Import all WhatsApp exports from a folder.
    """
    try:
        from ..chat_whatsapp import parse_whatsapp_file, window_messages
        from ..embed import embed_texts
        from ..qdrant_upsert import upsert_points

        folder = Path(folder_path)
        if not folder.exists():
            raise HTTPException(status_code=404, detail=f"Folder not found: {folder_path}")

        all_messages = []
        files_processed = 0

        for txt_file in folder.glob("*.txt"):
            try:
                messages = parse_whatsapp_file(str(txt_file))
                all_messages.extend(messages)
                files_processed += 1
            except Exception as e:
                logger.warning(f"Failed to parse {txt_file}: {e}")

        if not all_messages:
            return ImportResult(
                status="completed",
                source="whatsapp",
                items_found=0,
                details={"files_processed": files_processed}
            )

        windows = list(window_messages(all_messages))
        texts = [w["text"] for w in windows]
        embeddings = embed_texts(texts)

        points = []
        for window, embedding in zip(windows, embeddings):
            point_id = hash(window["content_hash"]) & 0x7FFFFFFFFFFFFFFF
            points.append({
                "id": point_id,
                "vector": embedding,
                "payload": {
                    "text": window["text"],
                    "doc_type": "chat_window",
                    "channel": f"whatsapp:{window.get('channel', 'unknown')}",
                    "content_hash": window["content_hash"],
                    "event_ts": window.get("first_timestamp", ""),
                    "created_at": datetime.utcnow().isoformat(),
                }
            })

        collection = f"jarvis_{namespace}"
        upsert_points(collection, points)

        return ImportResult(
            status="completed",
            source="whatsapp",
            items_found=len(all_messages),
            items_imported=len(points),
            details={
                "files_processed": files_processed,
                "collection": collection
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# GOOGLE CHAT IMPORT ENDPOINTS
# =============================================================================

@router.post("/google-chat/folder", response_model=ImportResult)
async def import_google_chat_folder(
    folder_path: str = Query(..., description="Path to Google Chat JSON export folder"),
    namespace: str = Query("private", description="Namespace")
):
    """
    Import Google Chat history from JSON export.

    Google Takeout exports JSON files for each chat space.
    """
    try:
        from ..chat_google import parse_gchat_folder, window_messages
        from ..embed import embed_texts
        from ..qdrant_upsert import upsert_points

        messages = parse_gchat_folder(folder_path)

        if not messages:
            return ImportResult(
                status="completed",
                source="google_chat",
                items_found=0,
            )

        windows = list(window_messages(messages))
        texts = [w["text"] for w in windows]
        embeddings = embed_texts(texts)

        points = []
        for window, embedding in zip(windows, embeddings):
            point_id = hash(window["content_hash"]) & 0x7FFFFFFFFFFFFFFF
            points.append({
                "id": point_id,
                "vector": embedding,
                "payload": {
                    "text": window["text"],
                    "doc_type": "chat_window",
                    "channel": f"gchat:{window.get('space_id', 'unknown')}",
                    "content_hash": window["content_hash"],
                    "event_ts": window.get("first_timestamp", ""),
                    "created_at": datetime.utcnow().isoformat(),
                }
            })

        collection = f"jarvis_{namespace}"
        upsert_points(collection, points)

        return ImportResult(
            status="completed",
            source="google_chat",
            items_found=len(messages),
            items_imported=len(points),
            details={"collection": collection}
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# EMAIL IMPORT ENDPOINTS
# =============================================================================

@router.post("/email/files", response_model=ImportResult)
async def import_email_files(
    folder_path: str = Query(..., description="Path to folder with .eml or .mbox files"),
    namespace: str = Query("private", description="Namespace"),
    label: str = Query("inbox", description="Email label: inbox, sent, archive")
):
    """
    Import emails from .eml or .mbox files.

    Supports:
    - .eml files (single email)
    - .mbox files (multiple emails)
    """
    try:
        from ..email_parser import parse_email_file, window_messages
        from ..embed import embed_texts
        from ..qdrant_upsert import upsert_points

        folder = Path(folder_path)
        if not folder.exists():
            raise HTTPException(status_code=404, detail=f"Folder not found: {folder_path}")

        all_emails = []
        files_processed = 0
        errors = []

        # Parse .eml files
        for eml_file in folder.glob("*.eml"):
            try:
                emails = parse_email_file(str(eml_file))
                all_emails.extend(emails)
                files_processed += 1
            except Exception as e:
                errors.append(f"{eml_file.name}: {str(e)}")

        # Parse .mbox files
        for mbox_file in folder.glob("*.mbox"):
            try:
                emails = parse_email_file(str(mbox_file))
                all_emails.extend(emails)
                files_processed += 1
            except Exception as e:
                errors.append(f"{mbox_file.name}: {str(e)}")

        if not all_emails:
            return ImportResult(
                status="completed",
                source="email_files",
                items_found=0,
                errors=errors,
                details={"files_processed": files_processed}
            )

        # Create windows and embed
        windows = list(window_messages(all_emails))
        texts = [w["text"] for w in windows]
        embeddings = embed_texts(texts)

        points = []
        for window, embedding in zip(windows, embeddings):
            point_id = hash(window["content_hash"]) & 0x7FFFFFFFFFFFFFFF
            points.append({
                "id": point_id,
                "vector": embedding,
                "payload": {
                    "text": window["text"],
                    "doc_type": "email",
                    "label": label,
                    "subject": window.get("subject", ""),
                    "from_addr": window.get("from_addr", ""),
                    "content_hash": window["content_hash"],
                    "event_ts": window.get("date", ""),
                    "created_at": datetime.utcnow().isoformat(),
                }
            })

        collection = f"jarvis_{namespace}"
        upsert_points(collection, points)

        return ImportResult(
            status="completed",
            source="email_files",
            items_found=len(all_emails),
            items_imported=len(points),
            errors=errors,
            details={
                "files_processed": files_processed,
                "collection": collection,
                "label": label
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/email/gmail/status")
async def gmail_status():
    """
    Check Gmail API connection status.

    Returns whether Gmail credentials are configured and working.
    """
    try:
        # Check if n8n Gmail workflow is configured
        import aiohttp

        n8n_url = os.environ.get("N8N_BASE_URL", "http://192.168.1.103:25678")

        return {
            "status": "configured",
            "method": "n8n_workflow",
            "n8n_url": n8n_url,
            "workflow_ids": {
                "daily_sync": "jarvis_gmail_daily_sync",
                "gateway": "jarvis_gmail_gateway",
            },
            "setup_instructions": """
Gmail is synced via n8n workflows. To configure:

1. Go to n8n at http://192.168.1.103:25678
2. Open 'Gmail PROJEKTIL' credential
3. Set up OAuth2 with Google Cloud Console:
   - Create OAuth2 credentials
   - Add redirect URI: http://192.168.1.103:25678/rest/oauth2-credential/callback
   - Enable Gmail API in Google Cloud Console
4. Activate the jarvis_gmail_daily_sync workflow

Or trigger manual sync:
POST /n8n/gmail/sync?namespace=private
            """,
        }

    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }


@router.post("/email/gmail/sync", response_model=ImportResult)
async def sync_gmail(
    namespace: str = Query("private", description="Namespace"),
    max_emails: int = Query(50, description="Max emails to fetch")
):
    """
    Trigger Gmail sync via n8n workflow.

    Requires Gmail OAuth2 credentials in n8n.
    """
    try:
        import aiohttp

        n8n_base = os.environ.get("N8N_BASE_URL", "http://192.168.1.103:25678")
        webhook_url = f"{n8n_base}/webhook/jarvis-gmail-sync"

        async with aiohttp.ClientSession() as session:
            async with session.post(
                webhook_url,
                json={"namespace": namespace, "max_emails": max_emails},
                timeout=aiohttp.ClientTimeout(total=120)
            ) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    return ImportResult(
                        status="completed",
                        source="gmail_api",
                        items_found=result.get("fetched", 0),
                        items_imported=result.get("stored", 0),
                        items_skipped=result.get("skipped", 0),
                        details=result
                    )
                else:
                    error_text = await resp.text()
                    raise HTTPException(
                        status_code=resp.status,
                        detail=f"n8n webhook failed: {error_text}"
                    )

    except aiohttp.ClientError as e:
        raise HTTPException(
            status_code=503,
            detail=f"Could not connect to n8n: {str(e)}. Is the workflow active?"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# IMPORT STATUS & STATS
# =============================================================================

@router.get("/stats")
async def import_stats():
    """
    Get statistics about imported data across all sources.
    """
    try:
        import qdrant_client
        from qdrant_client.http import models

        client = qdrant_client.QdrantClient(
            host=os.environ.get("QDRANT_HOST", "qdrant"),
            port=int(os.environ.get("QDRANT_PORT", 6333))
        )

        stats = {}

        for collection in ["jarvis_private", "jarvis_work", "jarvis_comms"]:
            try:
                info = client.get_collection(collection)
                stats[collection] = {
                    "total_points": info.points_count,
                }

                # Count by doc_type
                for doc_type in ["email", "chat_window", "personal_fact"]:
                    result = client.count(
                        collection_name=collection,
                        count_filter=models.Filter(
                            must=[models.FieldCondition(
                                key="doc_type",
                                match=models.MatchValue(value=doc_type)
                            )]
                        )
                    )
                    stats[collection][doc_type] = result.count

            except Exception as e:
                stats[collection] = {"error": str(e)}

        # Memory store stats
        try:
            from .. import memory_store
            facts = memory_store.get_facts(limit=1000)
            categories = {}
            for f in facts:
                cat = f.get("category", "unknown")
                categories[cat] = categories.get(cat, 0) + 1

            stats["memory_store"] = {
                "total_facts": len(facts),
                "by_category": categories,
            }
        except Exception as e:
            stats["memory_store"] = {"error": str(e)}

        return stats

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
