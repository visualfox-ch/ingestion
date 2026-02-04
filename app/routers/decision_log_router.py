from datetime import datetime
from typing import Optional, List
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from ..observability import get_logger, log_with_context
from ..tracing import get_current_user_id
from ..knowledge_db import get_conn


logger = get_logger("jarvis.routers.decision_log")

router = APIRouter(
    prefix="/decision-log",
    tags=["decision-log"],
    responses={400: {"description": "Invalid request"}, 500: {"description": "Internal error"}},
)


class DecisionLogCreate(BaseModel):
    title: str = Field(..., min_length=3)
    owner: Optional[str] = None
    context: str = Field(..., min_length=3)
    rationale: str = Field(..., min_length=3)
    impact: Optional[str] = None
    risk: str = Field(..., pattern="^(low|medium|high)$")
    tags: Optional[List[str]] = None
    approval_id: Optional[str] = None
    source_doc: Optional[str] = None


@router.post("")
def create_decision(entry: DecisionLogCreate, request: Request = None):
    owner = entry.owner or get_current_user_id() or "unknown"
    if not entry.owner and owner == "unknown":
        raise HTTPException(status_code=400, detail="owner is required")

    decision_id = str(uuid4())
    log_with_context(
        logger,
        "info",
        "Decision log create",
        decision_id=decision_id,
        owner=owner,
        risk=entry.risk,
        source_doc=entry.source_doc,
    )

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO decision_log (
                      id, decision_id, title, owner, context, rationale, impact, risk, tags, approval_id, source_doc
                    )
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    RETURNING *
                    """,
                    (
                        decision_id,
                        decision_id,
                        entry.title,
                        owner,
                        entry.context,
                        entry.rationale,
                        entry.impact,
                        entry.risk,
                        entry.tags,
                        entry.approval_id,
                        entry.source_doc,
                    ),
                )
                row = cur.fetchone()
        return {"data": row, "request_id": getattr(request.state, "request_id", None) if request else None}
    except Exception as exc:
        log_with_context(logger, "error", "Decision log create failed", error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to create decision log entry")


@router.get("")
def list_decisions(
    owner: Optional[str] = None,
    tag: Optional[str] = None,
    risk: Optional[str] = Query(None, pattern="^(low|medium|high)$"),
    from_ts: Optional[str] = None,
    to_ts: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    request: Request = None,
):
    filters = ["1=1"]
    params = []

    if owner:
        filters.append("owner = %s")
        params.append(owner)
    if risk:
        filters.append("risk = %s")
        params.append(risk)
    if tag:
        filters.append("tags @> ARRAY[%s]")
        params.append(tag)
    if from_ts:
        try:
            datetime.fromisoformat(from_ts.replace("Z", "+00:00"))
        except Exception:
            raise HTTPException(status_code=400, detail="from must be ISO timestamp")
        filters.append("created_at >= %s")
        params.append(from_ts)
    if to_ts:
        try:
            datetime.fromisoformat(to_ts.replace("Z", "+00:00"))
        except Exception:
            raise HTTPException(status_code=400, detail="to must be ISO timestamp")
        filters.append("created_at <= %s")
        params.append(to_ts)

    sql = f"SELECT * FROM decision_log WHERE {' AND '.join(filters)} ORDER BY created_at DESC LIMIT %s"
    params.append(limit)

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, tuple(params))
                rows = cur.fetchall()
        return {"data": rows, "count": len(rows), "request_id": getattr(request.state, "request_id", None) if request else None}
    except Exception as exc:
        log_with_context(logger, "error", "Decision log list failed", error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to list decision logs")


@router.get("/{decision_id}")
def get_decision(decision_id: str, request: Request = None):
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM decision_log WHERE id = %s", (decision_id,))
                row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Decision not found")
        return {"data": row, "request_id": getattr(request.state, "request_id", None) if request else None}
    except HTTPException:
        raise
    except Exception as exc:
        log_with_context(logger, "error", "Decision log get failed", error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to fetch decision log entry")
