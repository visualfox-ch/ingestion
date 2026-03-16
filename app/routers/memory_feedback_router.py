"""
Memory Feedback API – produktiv
"""
from fastapi import APIRouter, Request
from pydantic import BaseModel
from datetime import datetime
from typing import List
import logging
import os

router = APIRouter()
logger = logging.getLogger("jarvis.memory_feedback")

FEEDBACK_LOG = os.environ.get("MEMORY_FEEDBACK_LOG", "/tmp/memory_feedback.log")

class MemoryFeedback(BaseModel):
    user_id: str
    operation: str  # recall|tagging|retrieval|confidence
    success: bool
    comment: str = ""
    timestamp: datetime = datetime.utcnow()

@router.post("/memory/feedback")
def submit_feedback(feedback: MemoryFeedback, request: Request = None):
    """Persistiert Feedback zu Memory-Operationen (Datei-Log, später DB)."""
    entry = feedback.dict()
    entry["ip"] = request.client.host if request else None
    try:
        with open(FEEDBACK_LOG, "a") as f:
            f.write(str(entry) + "\n")
        logger.info(f"Feedback received: {entry}")
        return {"status": "received", "feedback": entry}
    except Exception as e:
        logger.error(f"Failed to persist feedback: {e}")
        return {"status": "error", "error": str(e)}

@router.get("/memory/feedback/stats")
def feedback_stats() -> dict:
    """Einfache Auswertung: Zähle Feedback nach Typ und Erfolg."""
    stats = {}
    try:
        with open(FEEDBACK_LOG, "r") as f:
            for line in f:
                try:
                    entry = eval(line.strip())
                    op = entry.get("operation", "unknown")
                    success = entry.get("success", False)
                    stats.setdefault(op, {"success": 0, "fail": 0})
                    if success:
                        stats[op]["success"] += 1
                    else:
                        stats[op]["fail"] += 1
                except Exception:
                    continue
        return {"status": "ok", "stats": stats}
    except Exception as e:
        return {"status": "error", "error": str(e)}
