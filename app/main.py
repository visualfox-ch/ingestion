from fastapi import FastAPI, Request, Depends, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import os
import hashlib
import shutil
import uuid
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import requests
import json
import time
from datetime import datetime
import pytz
from concurrent.futures import ThreadPoolExecutor, as_completed

from .embed import embed_texts
from .rate_limiter import rate_limit_dependency, get_rate_limit_stats, get_tier_for_endpoint
from .observability import get_logger, log_with_context
from .tracing import set_request_context, get_trace_context, generate_request_id, generate_trace_id, get_current_user_id

logger = get_logger("jarvis.main")
from .errors import register_exception_handlers, JarvisException, ErrorCode, wrap_external_error
from .qdrant_upsert import upsert_chunks, dedupe_collection
from .chat_whatsapp import parse_whatsapp_text, window_messages as wa_window_messages
from .chat_google import parse_google_chat_json, window_messages as gchat_window_messages
from . import email_parser
from . import state_db
from . import llm
from . import agent
from . import ssh_client
from . import n8n_workflow_manager
from .emotion_tracker import emotion_tracker

# Frequently used modules - imported at top-level to avoid repeated lazy imports
from . import knowledge_db
from . import postgres_state
from . import n8n_client
from . import session_manager
from . import meilisearch_client
from . import sentiment_analyzer
from . import entity_extractor
from . import prompt_assembler
from . import hybrid_search
from .pattern_tracker import pattern_tracker
from . import config
from . import metrics
from .auth import auth_dependency, is_public_endpoint, is_auth_enabled, get_auth_status
from .state import global_state
from .routers.health_router import router as health_router
from .routers.metrics_router import router as metrics_router
from .routers.notifications_router import router as notifications_router
from .routers.memory_router import router as memory_router
from .routers.workflow_router import router as workflow_router
from .routers.scan_router import router as scan_router
from . import rag_regression
from .routers.feature_flags_router import router as feature_flags_router
from .routers.knowledge_router import router as knowledge_router
from .routers.feedback_router import router as feedback_router
from .routers.self_router import router as self_router
from .learning_routes import router as learning_router
from .routers.hot_config_router import router as hot_config_router
from .routers.facette_router import router as facette_router
from .routers.gate_b import router as gate_b_router
from .routers.self_modification_router import router as self_modification_router
from .routers.introspection_router import router as introspection_router
from .routers.consciousness_bridge_router import router as consciousness_bridge_router
from .routers.consciousness_reciprocal_router import router as consciousness_reciprocal_router
from .routers.consciousness_transfer_router import router as consciousness_transfer_router
from .routers.observer_field_router import router as observer_field_router
from .routers.consciousness_temporal_router import router as consciousness_temporal_router
from .routers.decision_log_router import router as decision_log_router

app = FastAPI()

# =============================================================================
# Service endpoints / env (shared constants)
# =============================================================================
QDRANT_HOST = os.environ.get("QDRANT_HOST", "qdrant")
QDRANT_PORT = int(os.environ.get("QDRANT_PORT", "6333"))
QDRANT_BASE = f"http://{QDRANT_HOST}:{QDRANT_PORT}"

def compute_confidence(search_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Lightweight heuristic confidence for /answer and /answer_llm.
    Based on number of sources and their vector similarity scores.
    """
    scores: List[float] = []
    for r in search_results or []:
        try:
            scores.append(float(r.get("score", 0.0)))
        except Exception:
            continue

    if not scores:
        return {
            "confidence_score": 0.2,
            "confidence_level": "none",
            "source_count": 0,
            "max_score": 0.0,
            "avg_score": 0.0,
        }

    max_score = max(scores)
    avg_score = sum(scores) / len(scores)
    count_bonus = min(0.15, 0.05 * (len(scores) - 1))
    confidence_score = max(0.0, min(0.95, max_score + count_bonus))

    if confidence_score >= 0.75:
        level = "high"
    elif confidence_score >= 0.55:
        level = "medium"
    elif confidence_score >= 0.35:
        level = "low"
    else:
        level = "none"

    return {
        "confidence_score": round(confidence_score, 3),
        "confidence_level": level,
        "source_count": len(scores),
        "max_score": round(max_score, 3),
        "avg_score": round(avg_score, 3),
    }

# Routers
app.include_router(health_router)
app.include_router(metrics_router)
app.include_router(notifications_router)
app.include_router(workflow_router)
app.include_router(memory_router)
app.include_router(scan_router)
app.include_router(feature_flags_router)
app.include_router(knowledge_router)
app.include_router(feedback_router)
app.include_router(self_router)
app.include_router(learning_router)
app.include_router(hot_config_router)
app.include_router(facette_router)
app.include_router(gate_b_router)
app.include_router(self_modification_router)
app.include_router(introspection_router)
app.include_router(consciousness_bridge_router)
app.include_router(consciousness_reciprocal_router)
app.include_router(consciousness_transfer_router)
app.include_router(observer_field_router)
app.include_router(consciousness_temporal_router)
app.include_router(decision_log_router)

# =============================================================================
# PHASE 18.2: AGENT UNCERTAINTY SNAPSHOT (UI MVP)
# =============================================================================
_latest_agent_uncertainty: Dict[str, Any] = {
    "updated_at": None,
    "query_preview": None,
    "confidence_score": None,
    "confidence_level": "unknown",
    "source_quality": "none",
    "source_count": 0,
    "tool_calls": 0,
    "uncertainty_reasons": [],
    "suggested_alternatives": []
}

# =============================================================================
# File System Constants (Ingestion)
# =============================================================================
RAW_DIR = Path("/brain/raw") if Path("/brain/raw").exists() else Path("/volume1/BRAIN/raw")
PARSED_DIR = Path("/brain/parsed") if Path("/brain/parsed").exists() else Path("/volume1/BRAIN/parsed")

def chunk_text(text: str, max_chars: int = 2000, overlap: int = 200) -> List[str]:
    """Split text into overlapping chunks."""
    if len(text) <= max_chars:
        return [text]
    
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        chunks.append(text[start:end])
        start = end - overlap if end < len(text) else end
    return chunks

def iter_txt_files(directory: Path):
    """Iterate over txt/md files in directory recursively."""
    if not directory.exists():
        return
    for item in directory.rglob("*"):
        if item.is_file() and item.suffix in (".txt", ".md"):
            yield item

# =============================================================================
# /agent request model + helpers (stability)
# =============================================================================
class AgentRequest(BaseModel):
    query: str
    namespace: str = "work_projektil"
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    model: Optional[str] = None
    max_tokens: int = 1024
    role: str = "assistant"
    auto_detect_role: bool = True
    persona_id: Optional[str] = None
    include_explanation: bool = False
    stream: bool = False
    source: str = "api"


class PhaseCompleteRequest(BaseModel):
    phase: Optional[str] = None
    flush: bool = True
    metadata: Optional[Dict[str, Any]] = None


def _validate_agent_request(req: "AgentRequest") -> Optional[str]:
    if not req.query or not str(req.query).strip():
        return "query is required"
    if len(req.query) > 20000:
        return "query too large"
    if not req.namespace or not str(req.namespace).strip():
        return "namespace is required"
    if len(req.namespace) > 100:
        return "namespace too large"
    if req.max_tokens is not None and (req.max_tokens < 64 or req.max_tokens > 16384):
        return "max_tokens out of range"
    return None


def _get_request_user_id(request: Request, explicit_user_id: Optional[str]) -> str:
    if explicit_user_id:
        return str(explicit_user_id)
    # Prefer tracing context (falls back internally).
    try:
        current = get_current_user_id()
        if current:
            return str(current)
    except Exception:
        pass
    # Fallback to header if present.
    try:
        hdr = request.headers.get("x-user-id")
        if hdr:
            return str(hdr)
    except Exception:
        pass
    # Default to a numeric sentinel to avoid DB type errors (many tables use INTEGER user_id).
    return "0"


def _derive_agent_uncertainty(tool_calls: List[Dict[str, Any]]) -> Dict[str, Any]:
    source_count = 0
    for call in tool_calls or []:
        sources = call.get("sources") if isinstance(call, dict) else None
        if isinstance(sources, list):
            source_count += len(sources)

    # Minimal heuristic: more sources/tooling → higher confidence.
    if source_count >= 3:
        confidence_score = 0.75
        confidence_level = "medium"
        source_quality = "mixed"
    elif source_count >= 1:
        confidence_score = 0.6
        confidence_level = "low"
        source_quality = "some"
    else:
        confidence_score = 0.45
        confidence_level = "low"
        source_quality = "none"

    return {
        "confidence_score": confidence_score,
        "confidence_level": confidence_level,
        "source_quality": source_quality,
        "source_count": source_count,
        "uncertainty_reasons": [],
        "suggested_alternatives": [],
    }


def _record_latest_agent_uncertainty(query: str, uncertainty: Dict[str, Any]) -> None:
    _latest_agent_uncertainty["updated_at"] = datetime.utcnow().isoformat() + "Z"
    _latest_agent_uncertainty["query_preview"] = (query or "")[:120]
    _latest_agent_uncertainty["confidence_score"] = uncertainty.get("confidence_score")
    _latest_agent_uncertainty["confidence_level"] = uncertainty.get("confidence_level", "unknown")
    _latest_agent_uncertainty["source_quality"] = uncertainty.get("source_quality", "none")
    _latest_agent_uncertainty["source_count"] = uncertainty.get("source_count", 0)
    _latest_agent_uncertainty["tool_calls"] = uncertainty.get("tool_calls", 0)
    _latest_agent_uncertainty["uncertainty_reasons"] = uncertainty.get("uncertainty_reasons", [])
    _latest_agent_uncertainty["suggested_alternatives"] = uncertainty.get("suggested_alternatives", [])

# =============================================================================
# SHUTDOWN HANDLERS (P1 STABILITY)
# =============================================================================
@app.on_event("shutdown")
async def shutdown_handler():
    """Close DB pools on shutdown to prevent connection leaks"""
    try:
        postgres_state.close_pool()
    except Exception as e:
        logger.warning("Failed to close postgres_state pool", extra={"error": str(e)})
    try:
        knowledge_db.close_pool()
    except Exception as e:
        logger.warning("Failed to close knowledge_db pool", extra={"error": str(e)})

# =============================================================================
# PHASE 16.3B: STATIC FILES FOR DASHBOARD
# =============================================================================
# Mount static files directory for dashboard assets
try:
    app.mount("/static", StaticFiles(directory="app/static"), name="static")
except (RuntimeError, OSError, ValueError) as e:
    try:
        app.mount("/static", StaticFiles(directory="static"), name="static")
    except (RuntimeError, OSError, ValueError) as inner_e:
        logger.warning(
            "Could not mount static files directory",
            extra={"error": str(e), "fallback_error": str(inner_e)}
        )

# =============================================================================
# PHASE 16.3: REQUEST ID MIDDLEWARE
# =============================================================================
@app.middleware("http")
async def add_request_id_middleware(request: Request, call_next):
    # Extract or generate trace context
    trace_id = request.headers.get('X-Trace-ID', generate_trace_id())
    request_id = request.headers.get('X-Request-ID', generate_request_id())
    correlation_id = request.headers.get('X-Correlation-ID', request_id)
    # Default to numeric sentinel to avoid DB type errors (many tables use INTEGER user_id).
    user_id = request.headers.get('X-User-ID', '0')
    
    # Set context variables for distributed tracing
    set_request_context(
        request_id=request_id,
        trace_id=trace_id,
        correlation_id=correlation_id,
        user_id=user_id,
    )
    
    # Add to request state for downstream use
    request.state.request_id = request_id
    request.state.trace_id = trace_id
    request.state.correlation_id = correlation_id
    request.state.user_id = user_id
    
    # Process request
    response = await call_next(request)
    
    # Add trace headers to response
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Trace-ID"] = trace_id
    response.headers["X-Correlation-ID"] = correlation_id
    return response

# ============ Phase 2: Distributed Tracing (merged with request ID middleware)


# ============ Pattern Tracking (for Jarvis self-optimization) ============

@app.post("/patterns/track")
def track_pattern(
    user_id: int,
    topic: str,
    context: str
):
    """
    Track a topic mention and get proactive response if threshold reached.
    Used by Jarvis to detect recurring topics and respond proactively.
    """
    try:
        from .pattern_tracker import pattern_tracker
        response = pattern_tracker.track_topic(user_id, topic, context)
        return {
            "status": "tracked",
            "proactive_response": response
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


@app.get("/patterns/user/{user_id}")
def get_user_patterns(user_id: int, days: int = 30):
    """
    Get all tracked patterns for a user.
    Shows which topics have been mentioned repeatedly.
    """
    try:
        from .pattern_tracker import pattern_tracker
        patterns = pattern_tracker.get_user_patterns(user_id, days)
        return {
            "patterns": patterns,
            "count": len(patterns)
        }
    except Exception as e:
        return {"error": str(e)}


@app.post("/patterns/reset")
def reset_pattern(user_id: int, topic: str):
    """
    Reset a pattern after it's been addressed.
    Prevents Jarvis from repeatedly mentioning resolved topics.
    """
    try:
        from .pattern_tracker import pattern_tracker
        pattern_tracker.reset_pattern(user_id, topic)
        return {"status": "reset", "topic": topic}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ============ Feature Flags Status (Read-Only) ============

@app.get("/feature-flags")
def get_feature_flags_status(auth: bool = Depends(auth_dependency)):
    """Read-only feature flag status for monitoring and debugging."""
    return {
        "enabled": config.FEATURE_FLAGS_ENABLED,
        "source": config.FEATURE_FLAGS_SOURCE,
        "defaults": config.FEATURE_FLAGS_DEFAULTS,
    }


# ============ Emotion Tracking Endpoints ============

# Pydantic models for emotion tracking
class EmotionTrackRequest(BaseModel):
    user_id: int
    text: Optional[str] = None
    emotion: Optional[str] = None
    intensity: Optional[float] = None
    context: Optional[str] = None

class InterventionFeedbackRequest(BaseModel):
    user_id: int
    intervention_type: str
    accepted: bool
    notes: Optional[str] = None

@app.post("/emotions/track")
def track_emotion(request: EmotionTrackRequest):
    """
    Track emotion with minimal input - Jarvis: "nur das Nötigste"
    Either provide text for auto-detection or explicit emotion.
    """
    try:
        # Handle optional text parameter
        kwargs = {
            "user_id": request.user_id,
            "context": request.context
        }
        
        if request.text:
            kwargs["text"] = request.text
        else:
            # If no text provided, use empty string for now
            kwargs["text"] = ""
            
        if request.emotion:
            kwargs["manual_emotion"] = request.emotion
            
        if request.intensity:
            kwargs["manual_intensity"] = request.intensity
            
        result = emotion_tracker.track_emotion(**kwargs)
        
        return {
            "status": "tracked",
            "emotion": result["emotion"],
            "intensity": result["intensity"],
            "intervention": result.get("intervention")
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


@app.get("/emotions/patterns/{user_id}")
def get_emotion_patterns(user_id: int, days: int = 7):
    """
    Get emotion patterns and insights - Jarvis: "weekly trends"
    Shows emotional state distribution and actionable insights.
    """
    try:
        patterns = emotion_tracker.get_emotion_patterns(
            user_id=user_id,
            days=days
        )
        return patterns
    except Exception as e:
        import traceback
        return {"error": str(e), "traceback": traceback.format_exc()}


@app.post("/emotions/intervention/feedback")
def track_intervention_feedback(request: InterventionFeedbackRequest):
    """
    Track if intervention was helpful - Jarvis: "learn from feedback"
    Helps improve future intervention timing and content.
    """
    try:
        emotion_tracker.track_intervention_result(
            user_id=request.user_id,
            intervention_type=request.intervention_type,
            accepted=request.accepted,
            notes=request.notes
        )
        return {"status": "feedback tracked", "accepted": accepted}
    except Exception as e:
        return {"status": "error", "error": str(e)}
    """Check backup directory and recent backups."""
    try:
        # Check backup directory
        result = ssh_client.execute_command("ls -la /brain/backup/*.sql 2>/dev/null | tail -5")
        
        if result["success"]:
            backups = []
            for line in result["stdout"].strip().split("\n"):
                if line and ".sql" in line:
                    parts = line.split()
                    if len(parts) >= 9:
                        backups.append({
                            "file": parts[-1],
                            "size": parts[4],
                            "date": f"{parts[5]} {parts[6]} {parts[7]}"
                        })
            
            return {
                "success": True,
                "recent_backups": backups,
                "backup_dir": "/brain/backup"
            }
        else:
            return {"success": False, "error": "No backups found or directory not accessible"}
            
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============ Rate Limiting Middleware ============

@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """Apply rate limiting and add rate limit headers to responses."""
    # Skip guards for health/metrics and other public endpoints.
    path = request.url.path
    if path.startswith("/health") or path.startswith("/metrics") or path in ["/rate_limits"]:
        return await call_next(request)

    # Resource guard (load shedding): fail fast under memory/disk pressure.
    try:
        from .resource_guards import should_reject_request
        reject, payload = should_reject_request(path)
        if reject:
            return JSONResponse(
                status_code=503,
                content=payload,
                headers={"Retry-After": str(payload.get("retry_after_seconds", 30))}
            )
    except Exception:
        # Guard should never take down the API
        pass

    # Apply rate limit check
    try:
        await rate_limit_dependency(request)
    except Exception as e:
        # If it's an HTTPException (rate limit exceeded), re-raise
        from fastapi import HTTPException
        if isinstance(e, HTTPException):
            return JSONResponse(
                status_code=e.status_code,
                content=e.detail,
                headers=dict(e.headers) if e.headers else {}
            )
        raise

    # Process request
    response = await call_next(request)

    # Add rate limit headers if info available
    if hasattr(request.state, "rate_limit_info"):
        info = request.state.rate_limit_info
        response.headers["X-RateLimit-Limit"] = str(info.get("minute_limit", 0))
        response.headers["X-RateLimit-Remaining"] = str(info.get("remaining_minute", 0))
        response.headers["X-RateLimit-Tier"] = info.get("tier", "unknown")

    return response


# ============ Register Exception Handlers ============
register_exception_handlers(app)


# Start background services on startup
@app.on_event("startup")
def startup_event():
    """Start background services on FastAPI startup"""
    from .telegram_bot import start_bot_background, send_alert
    from .scheduler import start_scheduler
    from .embed import get_model
    from .prompt_assembler import get_prompt_version

    # Preload embedding model to avoid cold-start latency on first search
    logger.info("Preloading embedding model...")
    get_model()
    logger.info("Embedding model loaded")

    # Initialize cross-session learning database tables
    try:
        from .cross_session_learner import cross_session_learner
        cross_session_learner._init_tables()
        logger.info("Cross-session learning system initialized")
    except Exception as e:
        logger.error(f"Failed to initialize cross-session learning: {e}")

    # Initialize feature flags schema (Phase 18.3)
    try:
        from .feature_flags import init_feature_flags_schema
        init_feature_flags_schema()
        logger.info("Feature flags schema initialized")
    except Exception as e:
        logger.error(f"Failed to initialize feature flags: {e}")

    # Initialize permission matrix (Phase 18.4 - Gate A)
    try:
        from . import permissions as perm_module
        perm_module.init_permissions()
        logger.info("Permission matrix initialized (Gate A)")
    except Exception as e:
        logger.error(f"Failed to initialize permission matrix: {e}")

    start_bot_background()
    start_scheduler()

    # Send restart notification to Telegram
    try:
        version = get_prompt_version()
        send_alert(
            f"🔄 *Jarvis neu gestartet*\n\n"
            f"Prompt Version: *{version}*\n"
            f"Zeit: {datetime.now().strftime('%H:%M:%S')}\n\n"
            f"_Nutze /refresh um Capabilities zu pruefen_",
            level="info"
        )
        logger.info(f"Startup alert sent, prompt version: {version}")
    except Exception as e:
        logger.warning(f"Failed to send startup alert: {e}")

    # Check for mature facts ready for migration (Auto-Flagging v2.2)
    try:
        from . import memory_store
        mature_facts = memory_store.get_mature_facts(
            min_trust_score=0.5,
            min_access_count=5,
            min_age_days=7
        )
        if mature_facts:
            fact_list = "\n".join([
                f"• _{f['category']}_: {f['fact'][:50]}... (trust: {f['trust_score']:.1f})"
                for f in mature_facts[:5]  # Show max 5
            ])
            more_text = f"\n\n+{len(mature_facts) - 5} weitere..." if len(mature_facts) > 5 else ""
            send_alert(
                f"📚 *{len(mature_facts)} Facts bereit zur Migration*\n\n"
                f"{fact_list}{more_text}\n\n"
                f"_Claude Code kann diese in Config/YAML migrieren_",
                level="info"
            )
            logger.info(f"Flagged {len(mature_facts)} mature facts for migration")
    except Exception as e:
        logger.warning(f"Failed to check mature facts: {e}")


# ============ Health Check Endpoint ============

@app.get("/health")
def health_check():
    """
    Comprehensive health check for all Jarvis services.
    Returns status of each component and overall system health.
    """
    import time
    from datetime import datetime as dt
    start = time.time()
    checks = {}
    overall_healthy = True

    # 1. Qdrant check
    try:
        from qdrant_client import QdrantClient
        qdrant_host = os.environ.get("QDRANT_HOST", "qdrant")
        qdrant_port = int(os.environ.get("QDRANT_PORT", "6333"))
        client = QdrantClient(host=qdrant_host, port=qdrant_port, timeout=5)
        collections = client.get_collections()
        checks["qdrant"] = {
            "status": "healthy",
            "collections": len(collections.collections),
            "host": f"{qdrant_host}:{qdrant_port}"
        }
    except Exception as e:
        checks["qdrant"] = {"status": "unhealthy", "error": str(e)}
        overall_healthy = False

    # 2. Postgres check (Knowledge Layer)
    try:
        from . import knowledge_db
        if knowledge_db.is_available():
            checks["postgres"] = {"status": "healthy", "database": "jarvis"}
        else:
            checks["postgres"] = {"status": "unhealthy", "error": "Connection failed"}
            overall_healthy = False
    except Exception as e:
        checks["postgres"] = {"status": "unhealthy", "error": str(e)}
        overall_healthy = False

    # 3. SQLite state database check
    try:
        from . import state_db
        # Quick test - get session count
        sessions = state_db.list_sessions(limit=1)
        checks["sqlite"] = {"status": "healthy", "database": "jarvis_state.db"}
    except Exception as e:
        checks["sqlite"] = {"status": "unhealthy", "error": str(e)}
        overall_healthy = False

    # 4. Meilisearch check (keyword search)
    try:
        from . import meilisearch_client
        meili_health = meilisearch_client.health_check()
        if meili_health.get("status") == "healthy":
            checks["meilisearch"] = meili_health
        else:
            checks["meilisearch"] = meili_health
            # Don't fail overall - Meilisearch is optional
    except Exception as e:
        checks["meilisearch"] = {"status": "unavailable", "error": str(e)}

    # 5. Anthropic API check (just config, not actual call)
    try:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            secrets_path = "/brain/system/secrets/anthropic_api_key.txt"
            if os.path.exists(secrets_path):
                api_key = "configured_via_file"
        if api_key:
            checks["anthropic_api"] = {"status": "healthy", "configured": True}
        else:
            checks["anthropic_api"] = {"status": "warning", "configured": False}
    except Exception as e:
        checks["anthropic_api"] = {"status": "unhealthy", "error": str(e)}

    # 6. Telegram bot check
    try:
        from .telegram_bot import get_bot_status
        bot_status = get_bot_status()
        checks["telegram_bot"] = bot_status
    except Exception as e:
        checks["telegram_bot"] = {"status": "unknown", "error": str(e)}

    # 7. Scheduler check
    try:
        from .scheduler import get_scheduler_status
        scheduler_status = get_scheduler_status()
        checks["scheduler"] = scheduler_status
    except Exception as e:
        checks["scheduler"] = {"status": "unknown", "error": str(e)}

    # 8. n8n Gateway check (Google API)
    try:
        from .n8n_client import is_n8n_available, N8N_HOST, N8N_PORT
        if is_n8n_available():
            checks["n8n_gateway"] = {
                "status": "healthy",
                "host": f"{N8N_HOST}:{N8N_PORT}",
                "services": ["calendar", "gmail"]
            }
        else:
            checks["n8n_gateway"] = {
                "status": "unavailable",
                "host": f"{N8N_HOST}:{N8N_PORT}"
            }
            # Don't fail overall - proactive layer might still work
    except Exception as e:
        checks["n8n_gateway"] = {"status": "unknown", "error": str(e)}

    # 9. Embedding model check
    try:
        from .embed import get_model, MODEL_NAME
        model = get_model()
        checks["embedding_model"] = {
            "status": "healthy",
            "model": MODEL_NAME,
            "loaded": model is not None
        }
    except Exception as e:
        checks["embedding_model"] = {"status": "unhealthy", "error": str(e)}
        overall_healthy = False

    # 10. Follow-up tracking check
    try:
        from . import state_db
        stats = state_db.get_followup_stats()
        overdue = stats.get("overdue", 0)
        checks["followups"] = {
            "status": "warning" if overdue > 0 else "healthy",
            "total": stats.get("total", 0),
            "pending": stats.get("pending", 0),
            "overdue": overdue
        }
    except Exception as e:
        checks["followups"] = {"status": "unknown", "error": str(e)}

    # 11. Resource snapshot (does not fail overall; used for visibility + load shedding decisions)
    try:
        from .resource_guards import get_resource_snapshot
        snap = get_resource_snapshot()
        mem_p = float(snap.get("memory_percent", 0))
        disk_p = float(snap.get("disk_percent", 0))
        mem_thr = float(snap.get("thresholds", {}).get("mem_reject_percent", 0))
        disk_thr = float(snap.get("thresholds", {}).get("disk_reject_percent", 0))
        checks["resources"] = {
            "status": "warning" if (mem_p >= mem_thr or disk_p >= disk_thr) else "healthy",
            **snap,
        }
    except Exception as e:
        checks["resources"] = {"status": "unknown", "error": str(e)}

    duration_ms = (time.time() - start) * 1000

    return {
        "status": "healthy" if overall_healthy else "degraded",
        "timestamp": dt.now().isoformat(),
        "duration_ms": round(duration_ms, 2),
        "checks": checks,
        "summary": {
            "total_checks": len(checks),
            "healthy": sum(1 for c in checks.values() if c.get("status") == "healthy"),
            "warning": sum(1 for c in checks.values() if c.get("status") == "warning"),
            "unhealthy": sum(1 for c in checks.values() if c.get("status") == "unhealthy"),
        }
    }


@app.get("/health/quick")
def health_quick():
    """Quick health check - just returns OK if API is running"""
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


@app.get("/health/detailed")
def health_detailed():
    """
    Enhanced health check with actionable metrics.
    Includes latency measurements, resource usage, and recommendations.
    """
    try:
        from .health_checks import get_health_status
        return get_health_status()
    except ImportError as e:
        # Fallback to simple version without psutil
        try:
            from .health_checks_simple import get_simple_health_status
            result = get_simple_health_status()
            result["warning"] = "Using simplified health check (psutil not available)"
            return result
        except Exception as fallback_e:
            return {"error": f"Both health check versions failed: {str(e)} / {str(fallback_e)}", "status": "error"}
    except Exception as e:
        return {"error": f"Health check failed: {str(e)}", "status": "error"}


@app.get("/dashboard")
def health_dashboard():
    """
    Visual health dashboard with 4 tiles: API, DB, Search, Overall.
    Auto-refreshes every 30 seconds.
    """
    from fastapi.templating import Jinja2Templates
    from fastapi.responses import HTMLResponse
    
    # Get health data
    health_data = health_check()
    
    # Calculate component statuses
    def get_status_class(check):
        status = check.get("status", "unknown")
        if status == "healthy":
            return "healthy", "✓", "Healthy"
        elif status in ["degraded", "warning"]:
            return "degraded", "⚠", "Degraded"
        else:
            return "unhealthy", "✗", "Unhealthy"
    
    # API Status
    api_checks = sum(1 for c in health_data["checks"].values() if c.get("status") == "healthy")
    total_checks = len(health_data["checks"])
    if api_checks == total_checks:
        api_status, api_icon, api_text = "healthy", "✓", "All Systems OK"
    elif api_checks > total_checks / 2:
        api_status, api_icon, api_text = "degraded", "⚠", "Partial Service"
    else:
        api_status, api_icon, api_text = "unhealthy", "✗", "Service Down"
    
    # DB Status
    postgres_check = health_data["checks"].get("postgres", {})
    sqlite_check = health_data["checks"].get("sqlite", {})
    postgres_status = postgres_check.get("status", "unknown")
    sqlite_status = sqlite_check.get("status", "unknown")
    
    if postgres_status == "healthy" and sqlite_status == "healthy":
        db_status, db_icon, db_text = "healthy", "✓", "Databases OK"
    elif postgres_status == "healthy" or sqlite_status == "healthy":
        db_status, db_icon, db_text = "degraded", "⚠", "Partial DB"
    else:
        db_status, db_icon, db_text = "unhealthy", "✗", "DB Down"
    
    # Search Status
    qdrant_check = health_data["checks"].get("qdrant", {})
    meili_check = health_data["checks"].get("meilisearch", {})
    qdrant_status = qdrant_check.get("status", "unknown")
    meili_status = meili_check.get("status", "unknown")
    
    if qdrant_status == "healthy" and meili_status in ["healthy", "unavailable"]:
        search_status, search_icon, search_text = "healthy", "✓", "Search OK"
    elif qdrant_status == "healthy":
        search_status, search_icon, search_text = "degraded", "⚠", "Partial Search"
    else:
        search_status, search_icon, search_text = "unhealthy", "✗", "Search Down"
    
    # LLM Status
    llm_check = health_data["checks"].get("llm_providers", {})
    anthropic_status = llm_check.get("anthropic", {}).get("status", "unknown") if isinstance(llm_check, dict) else "unknown"
    openai_status = llm_check.get("openai", {}).get("status", "unknown") if isinstance(llm_check, dict) else "unknown"
    
    if anthropic_status == "healthy" and openai_status == "healthy":
        llm_status, llm_icon, llm_text = "healthy", "✓", "LLM OK"
    elif anthropic_status == "healthy" or openai_status == "healthy":
        llm_status, llm_icon, llm_text = "degraded", "⚠", "Partial LLM"
    else:
        llm_status, llm_icon, llm_text = "unhealthy", "✗", "LLM Down"
    
    # Overall Status
    overall_status = health_data.get("status", "unhealthy")
    if overall_status == "healthy":
        overall_icon, overall_title, overall_subtitle = "✓", "System Healthy", "All services operational"
    elif overall_status == "degraded":
        overall_icon, overall_title, overall_subtitle = "⚠", "System Degraded", "Some services unavailable"
    else:
        overall_icon, overall_title, overall_subtitle = "✗", "System Down", "Critical services offline"
    
    # Render template
    templates = Jinja2Templates(directory="app/templates")
    
    context = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC"),
        "api_status": api_status,
        "api_icon": api_icon,
        "api_text": api_text,
        "api_latency": f"{health_data.get('duration_ms', 0):.0f}ms",
        "api_checks": f"{api_checks}/{total_checks}",
        
        "db_status": db_status,
        "db_icon": db_icon,
        "db_text": db_text,
        "postgres_status": postgres_status.title(),
        "sqlite_status": sqlite_status.title(),
        
        "search_status": search_status,
        "search_icon": search_icon,
        "search_text": search_text,
        "qdrant_status": qdrant_status.title(),
        "meili_status": meili_status.title(),
        
        "llm_status": llm_status,
        "llm_icon": llm_icon,
        "llm_text": llm_text,
        "anthropic_status": anthropic_status.title(),
        "openai_status": openai_status.title(),
        
        "overall_status": overall_status,
        "overall_icon": overall_icon,
        "overall_title": overall_title,
        "overall_subtitle": overall_subtitle,
        
        "healthy_count": health_data["summary"]["healthy"],
        "total_checks": total_checks,
        "duration_ms": int(health_data.get("duration_ms", 0)),
    }
    
    # Read template
    template_path = Path("app/templates/dashboard.html")
    if not template_path.exists():
        return HTMLResponse(
            content=f"<h1>Dashboard template not found</h1><p>Expected: {template_path}</p>",
            status_code=500
        )
    
    html_content = template_path.read_text()
    
    # Simple template substitution
    for key, value in context.items():
        html_content = html_content.replace(f"{{{{ {key} }}}}", str(value))
    
    return HTMLResponse(content=html_content)


# ============ Self-Reflect Endpoint ============


@app.get("/metrics")
def get_metrics():
    """Get runtime metrics for observability"""
    from .observability import metrics, embedding_cache, query_cache
    return {
        "metrics": metrics.get_stats(),
        "caches": {
            "embedding": embedding_cache.stats(),
            "query_rewrite": query_cache.stats()
        }
    }


@app.get("/metrics/system")
def get_system_metrics():
    """
    System resource metrics for Jarvis components.

    Returns RAM, CPU, Disk usage for quick health checks.
    Detailed metrics available via Prometheus/Grafana (cAdvisor, Node Exporter).
    """
    import subprocess
    import os

    result = {
        "process": {},
        "containers": [],
        "disk": {},
        "source_tracking": {}
    }

    # Process memory (this container)
    try:
        import resource
        rusage = resource.getrusage(resource.RUSAGE_SELF)
        result["process"] = {
            "memory_mb": round(rusage.ru_maxrss / 1024, 2),  # macOS: bytes, Linux: KB
            "user_time_s": round(rusage.ru_utime, 2),
            "system_time_s": round(rusage.ru_stime, 2)
        }
    except Exception as e:
        result["process"] = {"error": str(e)}

    # Docker stats via docker CLI (if available)
    try:
        docker_cmd = "docker stats --no-stream --format '{{.Name}},{{.CPUPerc}},{{.MemUsage}},{{.MemPerc}}' 2>/dev/null || true"
        proc = subprocess.run(docker_cmd, shell=True, capture_output=True, text=True, timeout=10)
        if proc.stdout.strip():
            containers = []
            for line in proc.stdout.strip().split('\n'):
                parts = line.split(',')
                if len(parts) >= 4:
                    containers.append({
                        "name": parts[0],
                        "cpu": parts[1],
                        "memory": parts[2],
                        "memory_percent": parts[3]
                    })
            result["containers"] = containers
    except Exception as e:
        result["containers"] = {"error": str(e)}

    # Disk usage for BRAIN volume
    try:
        brain_root = os.environ.get("BRAIN_ROOT", "/brain")
        if os.path.exists(brain_root):
            stat = os.statvfs(brain_root)
            total_gb = (stat.f_blocks * stat.f_frsize) / (1024**3)
            free_gb = (stat.f_bavail * stat.f_frsize) / (1024**3)
            used_gb = total_gb - free_gb
            result["disk"] = {
                "path": brain_root,
                "total_gb": round(total_gb, 2),
                "used_gb": round(used_gb, 2),
                "free_gb": round(free_gb, 2),
                "used_percent": round((used_gb / total_gb) * 100, 1) if total_gb > 0 else 0
            }
    except Exception as e:
        result["disk"] = {"error": str(e)}

    # Source tracking stats (messages by source)
    try:
        from .postgres_state import get_cursor
        with get_cursor() as cur:
            cur.execute("""
                SELECT source, COUNT(*) as count
                FROM message
                WHERE source IS NOT NULL
                GROUP BY source
                ORDER BY count DESC
            """)
            rows = cur.fetchall()
            result["source_tracking"] = {row["source"]: row["count"] for row in rows}

            # Total messages
            cur.execute("SELECT COUNT(*) as total FROM message")
            result["source_tracking"]["_total_messages"] = cur.fetchone()["total"]

            # Messages without source (legacy)
            cur.execute("SELECT COUNT(*) as legacy FROM message WHERE source IS NULL")
            result["source_tracking"]["_legacy_no_source"] = cur.fetchone()["legacy"]
    except Exception as e:
        result["source_tracking"] = {"error": str(e)}

    return result


@app.get("/metrics/scientific")
def get_scientific_metrics():
    """
    Comprehensive scientific metrics for Jarvis system health.

    Based on industry best practices and academic research on:
    - Information Retrieval (NDCG, MRR thresholds)
    - Memory Systems (decay rates, retention curves)
    - Conversational AI (coherence, grounding metrics)
    - System Reliability (SLO-based thresholds)

    Thresholds derived from:
    - Google SRE Workbook (reliability targets)
    - ACL/EMNLP papers on RAG evaluation
    - Cognitive psychology research on memory retention

    Returns:
        Categorized metrics with health scores and recommendations
    """
    from datetime import datetime, timedelta
    from . import memory_store
    from .observability import metrics as obs_metrics

    now = datetime.now()
    result = {
        "generated_at": now.isoformat(),
        "categories": {},
        "overall_health": 0.0,
        "recommendations": []
    }

    # ==========================================================================
    # 1. MEMORY HEALTH METRICS
    # ==========================================================================
    # Based on Ebbinghaus forgetting curve research and spaced repetition studies
    try:
        memory_stats = memory_store.get_memory_stats()
        trust_dist = memory_store.get_trust_distribution()

        total_facts = memory_stats.get("facts_total", 0)
        high_trust = trust_dist.get("high", 0)
        medium_trust = trust_dist.get("medium", 0)
        low_trust = trust_dist.get("low", 0)
        minimal_trust = trust_dist.get("minimal", 0)

        # Healthy distribution: ~20% high, ~40% medium, ~30% low, ~10% minimal
        # Based on power law distribution in knowledge graphs
        high_ratio = high_trust / total_facts if total_facts > 0 else 0
        medium_ratio = medium_trust / total_facts if total_facts > 0 else 0
        low_ratio = low_trust / total_facts if total_facts > 0 else 0

        # Health score: penalize extreme imbalances
        memory_health = 1.0
        if high_ratio > 0.5:  # Too many high-trust facts → not enough pruning
            memory_health -= 0.2
        if minimal_trust / total_facts > 0.3 if total_facts > 0 else False:  # Too many decayed
            memory_health -= 0.3
        if total_facts < 50:  # Sparse memory
            memory_health -= 0.2

        result["categories"]["memory"] = {
            "health_score": max(0, min(1, memory_health)),
            "metrics": {
                "total_facts": total_facts,
                "trust_distribution": trust_dist,
                "high_trust_ratio": round(high_ratio, 3),
                "memory_age_days": memory_stats.get("oldest_fact_days", 0)
            },
            "thresholds": {
                "optimal_high_trust_ratio": "0.15-0.25 (power law)",
                "max_decayed_ratio": 0.30,
                "min_facts_for_utility": 50
            }
        }
    except Exception as e:
        result["categories"]["memory"] = {"error": str(e), "health_score": 0}

    # ==========================================================================
    # 2. KNOWLEDGE LAYER METRICS
    # ==========================================================================
    # Based on knowledge graph quality metrics (completeness, consistency)
    try:
        profiles = knowledge_db.get_all_person_profiles(status="active")
        pending_reviews = 0
        total_versions = 0

        for p in profiles[:100]:  # Sample for performance
            versions = knowledge_db.get_profile_versions(p["person_id"], status="proposed")
            pending_reviews += len(versions)
            total_versions += 1

        # Knowledge freshness: profiles updated in last 30 days
        fresh_profiles = 0
        for p in profiles:
            full = knowledge_db.get_person_profile(p["person_id"])
            if full:
                updated = full.get("updated_at", "")
                if updated:
                    try:
                        update_date = datetime.fromisoformat(updated.replace("Z", "+00:00"))
                        if (now - update_date.replace(tzinfo=None)).days < 30:
                            fresh_profiles += 1
                    except (ValueError, TypeError) as e:
                        logger.debug("Failed to parse profile updated_at", extra={"error": str(e)})

        profile_count = len(profiles)
        freshness_ratio = fresh_profiles / profile_count if profile_count > 0 else 0

        # Review queue health: pending items should be processed within 7 days
        knowledge_health = 1.0
        if pending_reviews > 10:
            knowledge_health -= 0.2
            result["recommendations"].append(f"Process {pending_reviews} pending profile reviews")
        if freshness_ratio < 0.3:
            knowledge_health -= 0.2
            result["recommendations"].append("Knowledge becoming stale - update person profiles")

        result["categories"]["knowledge"] = {
            "health_score": max(0, min(1, knowledge_health)),
            "metrics": {
                "active_profiles": profile_count,
                "pending_reviews": pending_reviews,
                "fresh_profiles_30d": fresh_profiles,
                "freshness_ratio": round(freshness_ratio, 3)
            },
            "thresholds": {
                "max_pending_reviews": 10,
                "min_freshness_ratio": 0.30,
                "review_sla_days": 7
            }
        }
    except Exception as e:
        result["categories"]["knowledge"] = {"error": str(e), "health_score": 0}

    # ==========================================================================
    # 3. SEARCH QUALITY METRICS
    # ==========================================================================
    # Based on NDCG@10 and MRR research from TREC evaluations
    try:
        from .observability import embedding_cache, query_cache

        # Get cache stats from observability
        embed_stats = embedding_cache.stats()
        query_stats = query_cache.stats()

        embed_hit_ratio = embed_stats.get("hit_ratio", 0)
        query_hit_ratio = query_stats.get("hit_ratio", 0)
        combined_hit_ratio = (embed_hit_ratio + query_hit_ratio) / 2

        # Get search latency from runtime metrics if available
        runtime_stats = obs_metrics.get_stats()
        timings = runtime_stats.get("timings", {})
        search_timing = timings.get("hybrid_search", timings.get("search", {}))
        avg_latency_ms = search_timing.get("avg_ms", 0) if search_timing else 0
        p99_latency_ms = search_timing.get("p99_ms", 0) if search_timing else 0

        # Search health based on industry benchmarks
        # Google: p50 < 200ms, p99 < 1000ms for search
        search_health = 1.0
        if p99_latency_ms > 1000:
            search_health -= 0.3
            result["recommendations"].append(f"Search p99 latency high ({p99_latency_ms:.0f}ms) - check Qdrant/Meilisearch")
        elif avg_latency_ms > 500:
            search_health -= 0.15
        if combined_hit_ratio < 0.2:
            search_health -= 0.1

        result["categories"]["search"] = {
            "health_score": max(0, min(1, search_health)),
            "metrics": {
                "embedding_cache_hit_ratio": round(embed_hit_ratio, 3),
                "query_cache_hit_ratio": round(query_hit_ratio, 3),
                "avg_latency_ms": round(avg_latency_ms, 2),
                "p99_latency_ms": round(p99_latency_ms, 2),
                "cache_entries": embed_stats.get("size", 0) + query_stats.get("size", 0)
            },
            "thresholds": {
                "target_latency_p50_ms": 200,
                "target_latency_p99_ms": 1000,
                "min_cache_hit_ratio": 0.20
            }
        }
    except Exception as e:
        result["categories"]["search"] = {"error": str(e), "health_score": 0}

    # ==========================================================================
    # 4. STAGING PIPELINE METRICS
    # ==========================================================================
    # Based on queue theory (Little's Law) and CI/CD best practices
    try:
        staging_stats = postgres_state.get_profile_staging_stats()

        pending = staging_stats.get("pending", 0)
        approved = staging_stats.get("approved", 0)
        rejected = staging_stats.get("rejected", 0)
        total = pending + approved + rejected + staging_stats.get("merged", 0)

        approval_rate = approved / (approved + rejected) if (approved + rejected) > 0 else 1.0

        staging_health = 1.0
        if pending > 20:
            staging_health -= 0.3
            result["recommendations"].append(f"{pending} profiles pending approval - review queue")
        if approval_rate < 0.5 and (approved + rejected) > 5:
            staging_health -= 0.2
            result["recommendations"].append(f"Low approval rate ({approval_rate:.0%}) - check profile quality")

        result["categories"]["staging_pipeline"] = {
            "health_score": max(0, min(1, staging_health)),
            "metrics": {
                "pending_count": pending,
                "approval_rate": round(approval_rate, 3),
                "total_processed": total,
                "queue_depth": pending
            },
            "thresholds": {
                "max_pending": 20,
                "min_approval_rate": 0.50,
                "processing_sla_hours": 24
            }
        }
    except Exception as e:
        result["categories"]["staging_pipeline"] = {"error": str(e), "health_score": 0}

    # ==========================================================================
    # 5. RUNTIME METRICS
    # ==========================================================================
    # Based on Google SRE golden signals (latency, traffic, errors, saturation)
    try:
        runtime_stats = obs_metrics.get_stats()
        counters = runtime_stats.get("counters", {})

        # Calculate error rate from counters
        total_requests = counters.get("requests_total", 0)
        errors = counters.get("errors_total", counters.get("error_count", 0))
        error_rate = errors / total_requests if total_requests > 0 else 0

        # Calculate requests per minute from uptime
        uptime_seconds = runtime_stats.get("uptime_seconds", 1)
        requests_per_min = (total_requests / uptime_seconds) * 60 if uptime_seconds > 0 else 0

        runtime_health = 1.0
        # SLO: 99.9% success rate (0.1% error budget)
        if error_rate > 0.01:  # > 1% errors
            runtime_health -= 0.4
            result["recommendations"].append(f"Error rate {error_rate:.1%} exceeds 1% threshold")
        elif error_rate > 0.001:  # > 0.1% errors
            runtime_health -= 0.2

        result["categories"]["runtime"] = {
            "health_score": max(0, min(1, runtime_health)),
            "metrics": {
                "error_rate": round(error_rate, 4),
                "total_requests": total_requests,
                "total_errors": errors,
                "requests_per_minute": round(requests_per_min, 2),
                "uptime_seconds": round(uptime_seconds, 0)
            },
            "thresholds": {
                "slo_success_rate": 0.999,
                "error_budget_monthly": 0.001,
                "max_error_rate_critical": 0.01
            }
        }
    except Exception as e:
        result["categories"]["runtime"] = {"error": str(e), "health_score": 0}

    # ==========================================================================
    # OVERALL HEALTH (weighted average)
    # ==========================================================================
    # Weights based on user-facing impact
    weights = {
        "memory": 0.20,      # Core capability
        "knowledge": 0.25,   # User profiles = personalization
        "search": 0.25,      # Primary interaction
        "staging_pipeline": 0.10,  # Admin workflow
        "runtime": 0.20      # System reliability
    }

    total_weight = 0
    weighted_sum = 0
    for category, weight in weights.items():
        if category in result["categories"]:
            score = result["categories"][category].get("health_score", 0)
            weighted_sum += score * weight
            total_weight += weight

    result["overall_health"] = round(weighted_sum / total_weight, 3) if total_weight > 0 else 0

    # Health status label
    if result["overall_health"] >= 0.9:
        result["status"] = "healthy"
    elif result["overall_health"] >= 0.7:
        result["status"] = "degraded"
    elif result["overall_health"] >= 0.5:
        result["status"] = "warning"
    else:
        result["status"] = "critical"

    return result


# ============ Phase 16.1: Prometheus Metrics ============

from prometheus_client import Gauge

# Define Jarvis-specific gauges for Prometheus metrics
_jarvis_knowledge_items = Gauge(
    "jarvis_knowledge_items_total",
    "Total knowledge items in the system"
)
_jarvis_style_profiles = Gauge(
    "jarvis_style_profiles_total",
    "Total learned user communication styles"
)
_jarvis_preference_confidence_avg = Gauge(
    "jarvis_preference_confidence_avg",
    "Average preference confidence across users"
)
_jarvis_preference_confidence_p95 = Gauge(
    "jarvis_preference_confidence_p95",
    "P95 percentile confidence distribution"
)
_jarvis_preference_confidence_min = Gauge(
    "jarvis_preference_confidence_min",
    "Minimum confidence bound"
)
_jarvis_preference_confidence_max = Gauge(
    "jarvis_preference_confidence_max",
    "Maximum confidence bound"
)
_jarvis_context_preferences = Gauge(
    "jarvis_context_preferences_total",
    "Total context-aware preferences learned"
)
_jarvis_anomalies_detected = Gauge(
    "jarvis_anomalies_detected_total",
    "Anomaly detection counter by severity",
    ["severity"]
)

@app.get("/metrics/prometheus")
def get_prometheus_metrics():
    """
    Prometheus-format metrics endpoint for monitoring.

    Phase 16.1: Exposes key Jarvis metrics in OpenMetrics format.

    Uses GLOBAL persistent metrics registry so counters accumulate
    across requests (updated by metrics_middleware).

    Metrics exposed (with SLI/SLO alignment):
    - jarvis_requests_total: Total API requests by endpoint [SLI: Availability]
    - jarvis_request_duration_seconds: Request latency histogram [SLI: Latency/Performance]
    - jarvis_knowledge_items_total: Total knowledge items in system
    - jarvis_preference_confidence_avg: Average preference confidence across users [refactored: no high-cardinality]
    - jarvis_preference_confidence_p95: P95 percentile confidence distribution
    - jarvis_preference_confidence_min/max: Min/max confidence bounds
    - jarvis_anomalies_detected_total: Anomaly detection counter by severity
    - jarvis_style_profiles_total: Total learned user communication styles
    - jarvis_context_preferences_total: Total context-aware preferences learned
    - jarvis_search_latency_seconds: Average vector search latency
    
    CARDINALITY NOTES:
    - Removed user_id labels from preference metrics to prevent cardinality explosion
    - Use aggregate percentiles (avg, p95, min, max) instead of per-user timeseries
    - Keep endpoint/method/status labels in counters (bounded to ~20-50 values)
    """
    from fastapi.responses import PlainTextResponse
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    from .observability import metrics as obs_metrics
    from . import memory_store
    from .postgres_state import get_cursor

    # === Update gauge values from current state ===
    try:
        # Get knowledge item count using efficient stats query
        stats = memory_store.get_memory_stats()
        _jarvis_knowledge_items.set(stats.get("facts_total", 0))
    except Exception as e:
        log_with_context(logger, "debug", f"Failed to update knowledge items metric: {e}")

    try:
        # Get Phase 17.2 preference metrics from database
        with get_cursor() as cur:
            # Style profiles count
            cur.execute("SELECT COUNT(*) FROM user_communication_profiles")
            row = cur.fetchone()
            _jarvis_style_profiles.set(row[0] if row else 0)

            # Preference confidence distribution (no high-cardinality user_id labels)
            cur.execute("SELECT confidence FROM user_communication_profiles ORDER BY confidence")
            rows = cur.fetchall()
            if rows:
                confidences = [row['confidence'] for row in rows]
                # Calculate aggregate percentiles instead of per-user metrics
                _jarvis_preference_confidence_avg.set(sum(confidences) / len(confidences))
                sorted_conf = sorted(confidences)
                p95_idx = int(len(confidences) * 0.95)
                _jarvis_preference_confidence_p95.set(sorted_conf[p95_idx] if p95_idx < len(sorted_conf) else sorted_conf[-1])
                _jarvis_preference_confidence_min.set(min(confidences))
                _jarvis_preference_confidence_max.set(max(confidences))
            else:
                _jarvis_preference_confidence_avg.set(0)
                _jarvis_preference_confidence_p95.set(0)
                _jarvis_preference_confidence_min.set(0)
                _jarvis_preference_confidence_max.set(0)

            # Context preferences count
            cur.execute("SELECT COUNT(*) FROM user_context_preferences")
            row = cur.fetchone()
            _jarvis_context_preferences.set(row[0] if row else 0)

            # Anomalies by severity
            cur.execute("""
                SELECT severity, COUNT(*) as cnt
                FROM user_anomaly_log
                WHERE status = 'open'
                GROUP BY severity
            """)
            for row in cur.fetchall():
                _jarvis_anomalies_detected.labels(severity=row['severity']).set(row['cnt'])
    except Exception as e:
        log_with_context(logger, "debug", f"Failed to update gauge metrics from database: {e}")

    # Generate Prometheus format output from GLOBAL registry
    output = generate_latest()

    try:
        from .connection_pool_metrics import export_all_pool_metrics
        pool_metrics_text = export_all_pool_metrics()
        if pool_metrics_text:
            output = output + pool_metrics_text.encode("utf-8")
    except Exception:
        pass

    # Add tool loop detection metrics (Phase 18.1)
    try:
        from .observability import tool_loop_detector
        tool_loop_metrics = tool_loop_detector.get_prometheus_metrics()
        if tool_loop_metrics:
            output = output + b"\n" + tool_loop_metrics.encode("utf-8")
    except Exception:
        pass

    return PlainTextResponse(content=output, media_type=CONTENT_TYPE_LATEST)


# =============================================================================
# PHASE 16.2: METRICS-DRIVEN OPTIMIZATION RECOMMENDATIONS
# =============================================================================

class RecommendationResponse(BaseModel):
    """API response for optimization recommendation"""
    id: str
    timestamp: str
    category: str
    severity: str
    title: str
    description: str
    metric_name: str
    current_value: float
    threshold: float
    action: str
    impact: str
    effort: str


@app.get("/optimize/analyze", response_model=Dict[str, Any])
async def analyze_metrics():
    """
    Analyze all metrics and return optimization recommendations.
    
    Returns recommendations grouped by severity level:
    - critical: Immediate action required
    - warning: Should address in short term
    - info: Good to know
    """
    from .metrics_analyzer import get_metrics_analyzer, SeverityLevel, CategoryType
    
    analyzer = get_metrics_analyzer()
    recommendations = await analyzer.analyze_all()
    
    # Group by severity
    by_severity = {
        "critical": [r for r in recommendations if r.severity == SeverityLevel.CRITICAL],
        "warning": [r for r in recommendations if r.severity == SeverityLevel.WARNING],
        "info": [r for r in recommendations if r.severity == SeverityLevel.INFO]
    }
    
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "total_recommendations": len(recommendations),
        "by_severity": {
            level: [
                {
                    "id": r.id,
                    "timestamp": r.timestamp,
                    "category": r.category.value,
                    "severity": r.severity.value,
                    "title": r.title,
                    "description": r.description,
                    "metric_name": r.metric_name,
                    "current_value": r.current_value,
                    "threshold": r.threshold,
                    "action": r.action,
                    "impact": r.impact,
                    "effort": r.effort
                }
                for r in recs
            ]
            for level, recs in by_severity.items()
        }
    }


@app.get("/optimize/latency", response_model=List[RecommendationResponse])
async def get_latency_optimization():
    """Get performance optimization recommendations for latency issues"""
    from .metrics_analyzer import get_metrics_analyzer
    
    analyzer = get_metrics_analyzer()
    recommendations = await analyzer.analyze_latency()
    
    return [
        {
            "id": r.id,
            "timestamp": r.timestamp,
            "category": r.category.value,
            "severity": r.severity.value,
            "title": r.title,
            "description": r.description,
            "metric_name": r.metric_name,
            "current_value": r.current_value,
            "threshold": r.threshold,
            "action": r.action,
            "impact": r.impact,
            "effort": r.effort
        }
        for r in recommendations
    ]


@app.get("/optimize/reliability", response_model=List[RecommendationResponse])
async def get_reliability_optimization():
    """Get reliability optimization recommendations for error rates"""
    from .metrics_analyzer import get_metrics_analyzer
    
    analyzer = get_metrics_analyzer()
    recommendations = await analyzer.analyze_reliability()
    
    return [
        {
            "id": r.id,
            "timestamp": r.timestamp,
            "category": r.category.value,
            "severity": r.severity.value,
            "title": r.title,
            "description": r.description,
            "metric_name": r.metric_name,
            "current_value": r.current_value,
            "threshold": r.threshold,
            "action": r.action,
            "impact": r.impact,
            "effort": r.effort
        }
        for r in recommendations
    ]


@app.get("/optimize/resources", response_model=List[RecommendationResponse])
async def get_resource_optimization():
    """Get resource optimization recommendations for memory/CPU issues"""
    from .metrics_analyzer import get_metrics_analyzer
    
    analyzer = get_metrics_analyzer()
    recommendations = await analyzer.analyze_resources()
    
    return [
        {
            "id": r.id,
            "timestamp": r.timestamp,
            "category": r.category.value,
            "severity": r.severity.value,
            "title": r.title,
            "description": r.description,
            "metric_name": r.metric_name,
            "current_value": r.current_value,
            "threshold": r.threshold,
            "action": r.action,
            "impact": r.impact,
            "effort": r.effort
        }
        for r in recommendations
    ]


@app.get("/optimize/quality", response_model=List[RecommendationResponse])
async def get_quality_optimization():
    """Get quality optimization recommendations for preference learning"""
    from .metrics_analyzer import get_metrics_analyzer
    
    analyzer = get_metrics_analyzer()
    recommendations = await analyzer.analyze_quality()
    
    return [
        {
            "id": r.id,
            "timestamp": r.timestamp,
            "category": r.category.value,
            "severity": r.severity.value,
            "title": r.title,
            "description": r.description,
            "metric_name": r.metric_name,
            "current_value": r.current_value,
            "threshold": r.threshold,
            "action": r.action,
            "impact": r.impact,
            "effort": r.effort
        }
        for r in recommendations
    ]


# =============================================================================
# PHASE 16.2: OPTIMIZATION COACHING ENDPOINTS
# =============================================================================

@app.get("/coach/optimize", response_model=Dict[str, Any])
async def get_optimization_coaching():
    """
    Get comprehensive optimization coaching for the system.
    
    Provides structured coaching on:
    - Critical issues requiring immediate attention
    - Warnings to address in near term
    - Informational suggestions for long-term improvement
    """
    from .optimization_coach import get_optimization_coach
    
    coach = get_optimization_coach()
    return await coach.get_optimization_guidance()


@app.get("/coach/performance", response_model=Dict[str, Any])
async def get_performance_coaching():
    """Get coaching specific to API performance and latency"""
    from .optimization_coach import get_optimization_coach
    
    coach = get_optimization_coach()
    return await coach.get_performance_coaching()


@app.get("/coach/reliability", response_model=Dict[str, Any])
async def get_reliability_coaching():
    """Get coaching specific to system reliability and error rates"""
    from .optimization_coach import get_optimization_coach
    
    coach = get_optimization_coach()
    return await coach.get_reliability_coaching()


@app.get("/coach/resources", response_model=Dict[str, Any])
async def get_resource_coaching():
    """Get coaching specific to memory and resource optimization"""
    from .optimization_coach import get_optimization_coach
    
    coach = get_optimization_coach()
    return await coach.get_resource_coaching()


@app.get("/coach/learning", response_model=Dict[str, Any])
async def get_learning_coaching():
    """Get coaching specific to preference learning and model quality"""
    from .optimization_coach import get_optimization_coach
    
    coach = get_optimization_coach()
    return await coach.get_learning_coaching()


# =============================================================================
# JARVIS CAPABILITIES & INFORMATION
# =============================================================================

@app.get("/info/capabilities", response_model=Dict[str, Any])
async def get_jarvis_capabilities():
    """
    Get information about Jarvis' current capabilities and features.
    
    Includes:
    - Metrics analysis (Phase 16.2)
    - Optimization coaching
    - SLI/SLO monitoring
    - Self-awareness features
    """
    return {
        "system": "Jarvis",
        "version": "Phase 16.2",
        "timestamp": datetime.utcnow().isoformat(),
        "capabilities": {
            "self_awareness": {
                "enabled": True,
                "description": "System monitors itself via Prometheus metrics",
                "endpoints": [
                    "/metrics/prometheus - Export metrics in Prometheus format",
                    "/info/metrics - System metric summary",
                    "/info/observability - Product-grade observability view"
                ]
            },
            "diagnostics": {
                "enabled": True,
                "description": "Automatic problem detection and severity assessment",
                "categories": [
                    "performance - P95/P99 latency analysis",
                    "reliability - Error rate and SLO burn rate tracking",
                    "resources - Memory and CPU utilization",
                    "quality - Preference confidence and anomaly detection",
                    "learning - User profile growth and trends"
                ],
                "endpoints": [
                    "/optimize/analyze - All recommendations",
                    "/optimize/latency - Performance recommendations",
                    "/optimize/reliability - Reliability recommendations",
                    "/optimize/resources - Resource recommendations",
                    "/optimize/quality - Quality recommendations"
                ]
            },
            "coaching": {
                "enabled": True,
                "description": "Human-readable optimization guidance with impact assessment",
                "endpoints": [
                    "/coach/optimize - System-wide coaching overview",
                    "/coach/performance - Performance optimization guidance",
                    "/coach/reliability - Reliability improvement guidance",
                    "/coach/resources - Resource optimization guidance",
                    "/coach/learning - Learning quality guidance"
                ]
            },
            "slo_monitoring": {
                "enabled": True,
                "description": "Service Level Objective tracking and burn rate calculation",
                "targets": {
                    "availability": "99% (7.2h error budget per month)",
                    "latency_p95": "< 1.0s",
                    "latency_p99": "< 2.5s",
                    "preference_confidence": "Continuous growth"
                },
                "endpoints": [
                    "Prometheus at http://localhost:19090",
                    "Grafana dashboards at http://localhost:13000"
                ]
            },
            "alert_rules": {
                "enabled": True,
                "count": 11,
                "description": "Automated alert rules for SLO violations",
                "examples": [
                    "HighErrorRateCritical - 5xx > 5%",
                    "HighLatencyP99 - > 2.5s",
                    "DependencyDown - Service unreachable",
                    "ErrorBudgetBurnRate1h - High burn rate detected"
                ]
            }
        },
        "recent_activities": {
            "phase_16_2_deployment": "2026-02-01T07:17:00Z",
            "metrics_analyzer_deployed": True,
            "optimization_coach_deployed": True,
            "coaching_endpoints_active": 5,
            "optimization_endpoints_active": 5
        },
        "next_steps": {
            "phase_16_3": "Automated remediation and playbook execution",
            "phase_16_4": "Predictive coaching with trend forecasting",
            "phase_17": "Integration of coaching insights with user interactions"
        }
    }


@app.get("/info/metrics", response_model=Dict[str, Any])
async def get_jarvis_metrics_summary():
    """
    Get a quick summary of Jarvis' current metrics state.
    
    Useful for dashboards and status checks.
    """
    from .metrics_analyzer import get_metrics_analyzer
    
    analyzer = get_metrics_analyzer()
    
    # Run analysis to get current state
    recommendations = await analyzer.analyze_all()
    
    # Count by severity
    critical = [r for r in recommendations if r.severity.value == "critical"]
    warnings = [r for r in recommendations if r.severity.value == "warning"]
    info = [r for r in recommendations if r.severity.value == "info"]
    
    # Get specific metrics
    p99_latency = await analyzer.query_metric(
        'histogram_quantile(0.99, sum(rate(jarvis_request_duration_seconds_bucket[5m])) by (le))'
    )
    error_rate = await analyzer.query_metric(
        '100 * (sum(rate(jarvis_requests_total{status=~"5.."}[5m])) / clamp_min(sum(rate(jarvis_requests_total[5m])), 1e-9))'
    )
    
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "health_status": "critical" if critical else ("warning" if warnings else "healthy"),
        "issues": {
            "critical": len(critical),
            "warnings": len(warnings),
            "info": len(info)
        },
        "key_metrics": {
            "latency_p99_seconds": round(p99_latency["value"], 3) if p99_latency else None,
            "latency_slo": "2.5s",
            "error_rate_percent": round(error_rate["value"], 2) if error_rate else None,
            "error_rate_slo": "< 1%"
        },
        "system_readiness": {
            "self_aware": True,
            "self_diagnosing": True,
            "self_coaching": True,
            "self_improving": True
        }
    }


@app.get("/info/observability", response_model=Dict[str, Any])
async def get_observability_product_view():
    """
    Product-grade observability summary.

    Designed for humans: where to look, what to trust, and how to debug.
    """
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "status": "active",
        "product_feature": {
            "goal": "Trace-first debugging + cost/latency awareness",
            "principle": "Traces are ground truth; metrics guide actions",
        },
        "where_to_view": {
            "metrics_summary": "/info/metrics",
            "prometheus": "/metrics/prometheus",
            "observability_summary": "/metrics/observability-summary",
            "rag_metrics": "/metrics/rag",
            "llm_metrics": "/metrics/llm",
        },
        "tracing": {
            "enabled": config.LANGFUSE_ENABLED,
            "provider": "langfuse",
            "url": config.LANGFUSE_HOST,
        },
        "slo_targets": {
            "availability": "99%",
            "latency_p95": "< 1.0s",
            "latency_p99": "< 2.5s",
            "error_rate": "< 1%",
        },
        "debug_playbook": [
            "Check /info/metrics for health status",
            "Inspect traces in Langfuse for high latency or failures",
            "Review /metrics/rag for retrieval quality drift",
            "Use /metrics/llm for model latency/cost anomalies",
        ],
    }


# =============================================================================
# RAG Regression (Nightly MVP)
# =============================================================================

@app.get("/rag/regression/latest", response_model=Dict[str, Any])
def get_rag_regression_latest(auth: bool = Depends(auth_dependency)):
    """Get latest RAG regression report (read-only)."""
    report = rag_regression.get_latest_rag_regression()
    if not report:
        return {"status": "not_found", "timestamp": datetime.utcnow().isoformat()}
    return report


@app.post("/rag/regression/run", response_model=Dict[str, Any])
def run_rag_regression_now(auth: bool = Depends(auth_dependency)):
    """Run RAG regression on-demand."""
    return rag_regression.run_rag_regression()


@app.post("/notify/phase-deployment", response_model=Dict[str, str])
async def notify_phase_deployment(phase: str, features: List[str] = None):
    """
    Notify Jarvis of a new phase deployment or feature activation.
    
    Used to inform the system of new capabilities for self-awareness.
    """
    message = f"Phase {phase} deployed"
    if features:
        message += f" with features: {', '.join(features)}"
    
    log_with_context(
        logger, "info", message,
        phase=phase,
        features=features or []
    )
    
    return {
        "status": "acknowledged",
        "message": f"Jarvis is now aware of {message}",
        "timestamp": datetime.utcnow().isoformat()
    }


@app.post("/notify/telegram", response_model=Dict[str, Any])
async def send_telegram_notification_endpoint(request: Dict[str, Any]):
    """
    Send a notification via Telegram.

    Phase 16.4B: Internal endpoint for notification service.

    Request body:
        message: The message text
        reply_markup: Optional inline keyboard markup
        parse_mode: Optional parse mode (Markdown, HTML)
        notification_id: Optional ID for inline button generation
        event_type: Optional event type for button style
    """
    import requests as http_requests
    from .telegram_bot import TELEGRAM_TOKEN, ALLOWED_USER_IDS

    try:
        message = request.get("message", "")
        reply_markup = request.get("reply_markup")
        parse_mode = request.get("parse_mode", "Markdown")
        notification_id = request.get("notification_id")
        event_type = request.get("event_type")

        if not message:
            return {"status": "error", "error": "No message provided"}

        if not TELEGRAM_TOKEN:
            return {"status": "error", "error": "Telegram bot not configured"}

        # Build payload
        payload = {
            "text": message,
            "parse_mode": parse_mode
        }

        # Build keyboard if notification_id provided
        if reply_markup:
            payload["reply_markup"] = reply_markup
        elif notification_id:
            # Build inline buttons based on event type
            if event_type == "remediation_pending":
                buttons = [
                    [
                        {"text": "✅ Genehmigen", "callback_data": f"notification:approve:{notification_id}"},
                        {"text": "🚫 Ablehnen", "callback_data": f"notification:reject:{notification_id}"},
                    ],
                    [
                        {"text": "ℹ️ Details", "callback_data": f"notification:details:{notification_id}"},
                    ]
                ]
            elif event_type == "followup_overdue":
                buttons = [
                    [
                        {"text": "✅ Erledigt", "callback_data": f"notification:read:{notification_id}"},
                        {"text": "⏰ Später", "callback_data": f"notification:snooze:{notification_id}"},
                    ],
                    [
                        {"text": "🗑️ Verwerfen", "callback_data": f"notification:dismiss:{notification_id}"},
                    ]
                ]
            else:
                buttons = [
                    [
                        {"text": "✓ Gelesen", "callback_data": f"notification:read:{notification_id}"},
                        {"text": "🗑️ Verwerfen", "callback_data": f"notification:dismiss:{notification_id}"},
                    ]
                ]
            payload["reply_markup"] = {"inline_keyboard": buttons}

        # Send to all allowed users
        success = False
        sent_to = []
        for user_id in ALLOWED_USER_IDS:
            try:
                payload["chat_id"] = user_id
                response = http_requests.post(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                    json=payload,
                    timeout=10
                )
                if response.status_code == 200:
                    success = True
                    sent_to.append(user_id)
            except Exception as e:
                logger.warning(f"Failed to send to {user_id}: {e}")

        if success:
            return {
                "status": "sent",
                "sent_to": sent_to,
                "timestamp": datetime.utcnow().isoformat()
            }
        else:
            return {
                "status": "error",
                "error": "Failed to send to any user"
            }

    except Exception as e:
        logger.error(f"Failed to send Telegram notification: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


# =============================================================================
# PHASE 16.3: AUTOMATED REMEDIATION API
# =============================================================================

from . import remediation_manager
from .schemas.remediation_schemas import (
    ApprovalDecisionRequest,
    RejectionDecisionRequest,
)

@app.get("/remediate/pending", response_model=Dict[str, Any])
async def get_pending_remediations():
    """
    Get all pending remediations awaiting approval.
    
    Returns list of Tier 2/3 playbooks that need human review.
    """
    try:
        pending = remediation_manager.get_pending_approvals()
        return {
            "status": "success",
            "count": len(pending),
            "pending_approvals": pending,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Failed to get pending remediations: {e}")
        return {
            "status": "error",
            "error": str(e),
            "pending_approvals": []
        }


@app.get("/remediate/recent", response_model=Dict[str, Any])
async def get_recent_remediations(days: int = 7):
    """
    Get recent remediation history.
    
    Args:
        days: Number of days to look back (default: 7)
    """
    try:
        recent = remediation_manager.get_recent_remediations(days=days)
        return {
            "status": "success",
            "count": len(recent),
            "remediations": recent,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Failed to get recent remediations: {e}")
        return {
            "status": "error",
            "error": str(e),
            "remediations": []
        }


@app.get("/remediate/stats", response_model=Dict[str, Any])
async def get_remediation_stats():
    """
    Get remediation success rates and statistics.
    
    Shows performance of each playbook type.
    """
    try:
        stats = remediation_manager.get_success_rates()
        return {
            "status": "success",
            "playbook_stats": stats,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Failed to get remediation stats: {e}")
        return {
            "status": "error",
            "error": str(e),
            "playbook_stats": []
        }


# Note: ApprovalDecisionRequest imported from .schemas.remediation_schemas
# Provides validation: user_id alphanumeric, reason max 500 chars, optional idempotency_key

@app.post("/remediate/{remediation_id}/approve", response_model=Dict[str, Any])
async def approve_remediation_endpoint(
    remediation_id: str,
    req: ApprovalDecisionRequest,
    request: Request
):
    """
    Approve a pending remediation with validated input.

    Args:
        remediation_id: Unique ID of remediation (e.g., rem-20260201-001)
        req: ApprovalDecisionRequest with user_id, optional reason, optional idempotency_key

    Validation (via Pydantic):
        - user_id: 3-100 chars, alphanumeric with @._-
        - reason: max 500 chars, stripped
        - idempotency_key: valid UUID v4 if provided
    """
    request_id = getattr(request.state, 'request_id', 'unknown')

    try:
        success = remediation_manager.approve_remediation(
            remediation_id=remediation_id,
            approved_by=req.user_id,
            reason=req.reason
        )

        if success:
            logger.info(
                f"Remediation approved via API",
                extra={
                    "request_id": request_id,
                    "remediation_id": remediation_id,
                    "user_id": req.user_id
                }
            )
            return {
                "status": "success",
                "action": "approved",
                "remediation_id": remediation_id,
                "by": req.user_id,
                "reason": req.reason,
                "timestamp": datetime.utcnow().isoformat(),
                "request_id": request_id
            }
        else:
            return {
                "status": "error",
                "error": "Remediation not found or already processed",
                "remediation_id": remediation_id,
                "request_id": request_id
            }
    except Exception as e:
        logger.error(
            f"Failed to approve remediation",
            extra={
                "request_id": request_id,
                "remediation_id": remediation_id,
                "error": str(e)
            }
        )
        return {
            "status": "error",
            "error": str(e),
            "remediation_id": remediation_id,
            "request_id": request_id
        }


# Note: RejectionDecisionRequest imported from .schemas.remediation_schemas
# Provides validation: user_id alphanumeric, reason required (5-500 chars)

@app.post("/remediate/{remediation_id}/reject", response_model=Dict[str, Any])
async def reject_remediation_endpoint(
    remediation_id: str,
    req: RejectionDecisionRequest,
    request: Request
):
    """
    Reject a pending remediation with validated input.

    Args:
        remediation_id: Unique ID of remediation
        req: RejectionDecisionRequest with user_id, reason (required), optional idempotency_key

    Validation (via Pydantic):
        - user_id: 3-100 chars, alphanumeric with @._-
        - reason: 5-500 chars, required, stripped
        - idempotency_key: valid UUID v4 if provided
    """
    request_id = getattr(request.state, 'request_id', 'unknown')

    try:
        success = remediation_manager.reject_remediation(
            remediation_id=remediation_id,
            rejected_by=req.user_id,
            reason=req.reason
        )

        if success:
            logger.info(
                f"Remediation rejected via API",
                extra={
                    "request_id": request_id,
                    "remediation_id": remediation_id,
                    "user_id": req.user_id
                }
            )
            return {
                "status": "success",
                "action": "rejected",
                "remediation_id": remediation_id,
                "by": req.user_id,
                "reason": req.reason,
                "timestamp": datetime.utcnow().isoformat(),
                "request_id": request_id
            }
        else:
            return {
                "status": "error",
                "error": "Remediation not found or already processed",
                "remediation_id": remediation_id,
                "request_id": request_id
            }
    except Exception as e:
        logger.error(
            f"Failed to reject remediation",
            extra={
                "request_id": request_id,
                "remediation_id": remediation_id,
                "error": str(e)
            }
        )
        return {
            "status": "error",
            "error": str(e),
            "remediation_id": remediation_id,
            "request_id": request_id
        }


# =============================================================================
# PHASE 16.3C: PLAYBOOK EXECUTION ENDPOINTS
# =============================================================================

class ExecuteRemediationRequest(BaseModel):
    """Request body for executing a remediation playbook."""
    dry_run: bool = False


class PlaybookStatusUpdate(BaseModel):
    """Status update from n8n playbook execution."""
    status: str  # "completed", "failed", "rolled_back"
    execution_result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    duration_seconds: Optional[float] = None


# n8n webhook URLs for each playbook
N8N_PLAYBOOK_WEBHOOKS = {
    "service_restart": "http://192.168.1.103:25678/webhook/service-restart",
    "log_archival": "http://192.168.1.103:25678/webhook/log-archival",
    "connection_pool_reset": "http://192.168.1.103:25678/webhook/connection-reset",
    "cache_invalidation": "http://192.168.1.103:25678/webhook/cache-invalidation",
    "index_optimization": "http://192.168.1.103:25678/webhook/index-optimization",
}


@app.post("/remediate/{remediation_id}/execute", response_model=Dict[str, Any])
async def execute_remediation_endpoint(
    remediation_id: str,
    req: ExecuteRemediationRequest,
    request: Request
):
    """
    Execute an approved remediation playbook.

    Phase 16.3C: Triggers n8n workflow for the remediation.

    Args:
        remediation_id: Unique ID of remediation
        req: ExecuteRemediationRequest with dry_run flag

    Returns:
        Execution status and workflow ID
    """
    request_id = getattr(request.state, 'request_id', 'unknown')

    try:
        # Get remediation details
        remediation = remediation_manager.get_remediation(remediation_id)

        if not remediation:
            return JSONResponse(
                status_code=404,
                content={
                    "status": "error",
                    "error": "Remediation not found",
                    "remediation_id": remediation_id,
                    "request_id": request_id
                }
            )

        # Check if approved (Tier-2) or auto-approved (Tier-1)
        if remediation.get("status") not in ["approved", "auto_approved"]:
            return JSONResponse(
                status_code=400,
                content={
                    "status": "error",
                    "error": f"Remediation not approved. Current status: {remediation.get('status')}",
                    "remediation_id": remediation_id,
                    "request_id": request_id
                }
            )

        playbook_type = remediation.get("playbook_type", "unknown")
        webhook_url = N8N_PLAYBOOK_WEBHOOKS.get(playbook_type)

        if not webhook_url:
            return JSONResponse(
                status_code=400,
                content={
                    "status": "error",
                    "error": f"Unknown playbook type: {playbook_type}",
                    "remediation_id": remediation_id,
                    "request_id": request_id
                }
            )

        # Prepare payload for n8n
        payload = {
            "remediation_id": remediation_id,
            "playbook_type": playbook_type,
            "trigger_reason": remediation.get("trigger_reason", "Manual execution"),
            "params": remediation.get("params", {}),
            "dry_run": req.dry_run,
            "callback_url": f"http://jarvis-ingestion:18000/remediate/{remediation_id}/status",
            "request_id": request_id
        }

        if req.dry_run:
            # Dry run - don't actually call n8n
            logger.info(
                f"Dry run for remediation",
                extra={
                    "request_id": request_id,
                    "remediation_id": remediation_id,
                    "playbook_type": playbook_type
                }
            )
            return {
                "status": "dry_run",
                "remediation_id": remediation_id,
                "playbook_type": playbook_type,
                "would_call": webhook_url,
                "payload": payload,
                "request_id": request_id
            }

        # Call n8n webhook
        try:
            response = requests.post(
                webhook_url,
                json=payload,
                timeout=30,
                headers={"Content-Type": "application/json"}
            )

            if response.status_code == 200:
                # Update remediation status to executing
                remediation_manager.update_status(remediation_id, "executing")

                logger.info(
                    f"Remediation execution started",
                    extra={
                        "request_id": request_id,
                        "remediation_id": remediation_id,
                        "playbook_type": playbook_type
                    }
                )

                return {
                    "status": "executing",
                    "remediation_id": remediation_id,
                    "playbook_type": playbook_type,
                    "workflow_id": response.json().get("executionId", "unknown"),
                    "started_at": datetime.utcnow().isoformat(),
                    "request_id": request_id
                }
            else:
                logger.error(
                    f"n8n webhook failed",
                    extra={
                        "request_id": request_id,
                        "remediation_id": remediation_id,
                        "status_code": response.status_code,
                        "response": response.text[:500]
                    }
                )
                return JSONResponse(
                    status_code=502,
                    content={
                        "status": "error",
                        "error": f"n8n webhook returned {response.status_code}",
                        "remediation_id": remediation_id,
                        "request_id": request_id
                    }
                )

        except requests.exceptions.Timeout:
            return JSONResponse(
                status_code=504,
                content={
                    "status": "error",
                    "error": "n8n webhook timed out",
                    "remediation_id": remediation_id,
                    "request_id": request_id
                }
            )
        except requests.exceptions.ConnectionError:
            return JSONResponse(
                status_code=503,
                content={
                    "status": "error",
                    "error": "Cannot connect to n8n",
                    "remediation_id": remediation_id,
                    "request_id": request_id
                }
            )

    except Exception as e:
        logger.error(
            f"Failed to execute remediation",
            extra={
                "request_id": request_id,
                "remediation_id": remediation_id,
                "error": str(e)
            }
        )
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "error": str(e),
                "remediation_id": remediation_id,
                "request_id": request_id
            }
        )


@app.post("/remediate/{remediation_id}/status", response_model=Dict[str, Any])
async def update_remediation_status_endpoint(
    remediation_id: str,
    update: PlaybookStatusUpdate,
    request: Request
):
    """
    Receive status update from n8n playbook execution.

    Phase 16.3C: Callback endpoint for n8n workflows.

    Args:
        remediation_id: Unique ID of remediation
        update: PlaybookStatusUpdate with execution result
    """
    request_id = getattr(request.state, 'request_id', 'unknown')

    try:
        # Update remediation status in database
        success = remediation_manager.update_execution_result(
            remediation_id=remediation_id,
            status=update.status,
            execution_result=update.execution_result,
            error=update.error,
            duration_seconds=update.duration_seconds
        )

        if success:
            logger.info(
                f"Remediation status updated",
                extra={
                    "request_id": request_id,
                    "remediation_id": remediation_id,
                    "status": update.status,
                    "duration": update.duration_seconds
                }
            )
            return {
                "status": "success",
                "remediation_id": remediation_id,
                "new_status": update.status,
                "timestamp": datetime.utcnow().isoformat(),
                "request_id": request_id
            }
        else:
            return {
                "status": "error",
                "error": "Remediation not found",
                "remediation_id": remediation_id,
                "request_id": request_id
            }

    except Exception as e:
        logger.error(
            f"Failed to update remediation status",
            extra={
                "request_id": request_id,
                "remediation_id": remediation_id,
                "error": str(e)
            }
        )
        return {
            "status": "error",
            "error": str(e),
            "remediation_id": remediation_id,
            "request_id": request_id
        }


# =============================================================================
# PHASE 16.3C: INTERNAL POOL MANAGEMENT ENDPOINTS
# (moved to routers/health_router.py)
# =============================================================================


@app.get("/internal/pool/health", response_model=Dict[str, Any])
async def check_pool_health(request: Request):
    """
    Check health of core dependencies (Postgres, Qdrant, Meilisearch).

    Used for pre/post checks in playbooks.
    """
    import os
    import time

    request_id = getattr(request.state, 'request_id', 'unknown')

    health: Dict[str, Any] = {
        "postgres": {"status": "unknown"},
        "qdrant": {"status": "unknown"},
        "meilisearch": {"status": "unknown"},
    }

    # PostgreSQL
    try:
        t0 = time.time()
        with postgres_state.get_cursor() as cur:
            cur.execute("SELECT 1")
        health["postgres"] = {"status": "healthy", "latency_ms": round((time.time() - t0) * 1000, 2)}
    except Exception as e:
        health["postgres"] = {"status": "unhealthy", "error": str(e)}

    # Qdrant
    try:
        from qdrant_client import QdrantClient
        qdrant_host = os.environ.get("QDRANT_HOST", "qdrant")
        qdrant_port = int(os.environ.get("QDRANT_PORT", "6333"))
        t0 = time.time()
        client = QdrantClient(host=qdrant_host, port=qdrant_port)
        client.get_collections()
        health["qdrant"] = {"status": "healthy", "latency_ms": round((time.time() - t0) * 1000, 2), "host": f"{qdrant_host}:{qdrant_port}"}
    except Exception as e:
        health["qdrant"] = {"status": "unhealthy", "error": str(e)}

    # Meilisearch
    try:
        import meilisearch
        meili_host = os.environ.get("MEILI_HOST", "meilisearch")
        meili_port = int(os.environ.get("MEILI_PORT", "7700"))
        t0 = time.time()
        client = meilisearch.Client(f"http://{meili_host}:{meili_port}")
        client.health()
        health["meilisearch"] = {"status": "healthy", "latency_ms": round((time.time() - t0) * 1000, 2), "host": f"{meili_host}:{meili_port}"}
    except Exception as e:
        health["meilisearch"] = {"status": "unhealthy", "error": str(e)}

    all_healthy = all(h.get("status") == "healthy" for h in health.values())

    return {
        "status": "healthy" if all_healthy else "degraded",
        "pools": health,
        "draining": global_state.get_pool_draining(),
        "timestamp": datetime.utcnow().isoformat(),
        "request_id": request_id,
    }


# =============================================================================
# PHASE 16.4B: NOTIFICATION SYSTEM
# =============================================================================

from . import notification_service


class SendNotificationRequest(BaseModel):
    """Request body for sending a notification."""
    user_id: str
    event_type: str
    event_id: str
    context: Optional[Dict[str, Any]] = None
    priority: int = 3
    channels: Optional[List[str]] = None


class UpdatePreferencesRequest(BaseModel):
    """Request body for updating notification preferences."""
    telegram_enabled: Optional[bool] = None
    email_enabled: Optional[bool] = None
    dashboard_enabled: Optional[bool] = None
    quiet_hours_enabled: Optional[bool] = None
    quiet_hours_start: Optional[str] = None
    quiet_hours_end: Optional[str] = None
    max_notifications_per_hour: Optional[int] = None
    max_notifications_per_day: Optional[int] = None


@app.post("/notifications/send", response_model=Dict[str, Any])
async def send_notification_endpoint(
    req: SendNotificationRequest,
    request: Request
):
    """
    Send a notification to a user.

    Phase 16.4B: Internal endpoint for triggering notifications.

    Args:
        req: SendNotificationRequest with user_id, event_type, event_id, context

    Returns:
        {status, channels_sent, notification_ids, skipped}
    """
    request_id = getattr(request.state, 'request_id', 'unknown')

    try:
        result = await notification_service.send_notification(
            user_id=req.user_id,
            event_type=req.event_type,
            event_id=req.event_id,
            context=req.context,
            priority=req.priority,
            channels=req.channels
        )

        logger.info(
            f"Notification sent",
            extra={
                "request_id": request_id,
                "user_id": req.user_id,
                "event_type": req.event_type,
                "channels": result.get("channels_sent", [])
            }
        )

        return {
            **result,
            "request_id": request_id
        }

    except Exception as e:
        logger.error(
            f"Failed to send notification",
            extra={
                "request_id": request_id,
                "error": str(e)
            }
        )
        return {
            "status": "error",
            "error": str(e),
            "request_id": request_id
        }


@app.get("/notifications/pending", response_model=Dict[str, Any])
async def get_pending_notifications_endpoint(
    user_id: Optional[str] = None,
    limit: int = 20,
    request: Request = None
):
    """
    Get pending (unread) notifications for dashboard display.

    Phase 16.4B: Used by dashboard to show notification badge and list.
    """
    request_id = getattr(request.state, 'request_id', 'unknown') if request else 'unknown'

    try:
        notifications = await notification_service.get_pending_notifications(
            user_id=user_id,
            limit=limit
        )

        return {
            "status": "success",
            "count": len(notifications),
            "notifications": notifications,
            "request_id": request_id
        }

    except Exception as e:
        logger.error(f"Failed to get pending notifications: {e}")
        return {
            "status": "error",
            "error": str(e),
            "notifications": [],
            "request_id": request_id
        }


@app.post("/notifications/{notification_id}/read", response_model=Dict[str, Any])
async def mark_notification_read_endpoint(
    notification_id: str,
    request: Request
):
    """
    Mark a notification as read.

    Phase 16.4B: Called when user views/acknowledges a notification.
    """
    request_id = getattr(request.state, 'request_id', 'unknown')

    try:
        success = await notification_service.mark_notification_read(notification_id)

        if success:
            return {
                "status": "success",
                "notification_id": notification_id,
                "timestamp": datetime.utcnow().isoformat(),
                "request_id": request_id
            }
        else:
            return {
                "status": "error",
                "error": "Notification not found",
                "notification_id": notification_id,
                "request_id": request_id
            }

    except Exception as e:
        logger.error(f"Failed to mark notification read: {e}")
        return {
            "status": "error",
            "error": str(e),
            "request_id": request_id
        }


@app.get("/notifications/stats", response_model=Dict[str, Any])
async def get_notification_stats_endpoint(
    user_id: Optional[str] = None,
    days: int = 7,
    request: Request = None
):
    """
    Get notification statistics.

    Phase 16.4B: Dashboard metrics for notification performance.
    """
    request_id = getattr(request.state, 'request_id', 'unknown') if request else 'unknown'

    try:
        stats = await notification_service.get_notification_stats(
            user_id=user_id,
            days=days
        )

        return {
            "status": "success",
            **stats,
            "request_id": request_id
        }

    except Exception as e:
        logger.error(f"Failed to get notification stats: {e}")
        return {
            "status": "error",
            "error": str(e),
            "request_id": request_id
        }


@app.get("/user/notification-preferences", response_model=Dict[str, Any])
async def get_user_preferences_endpoint(
    user_id: str = "micha",
    request: Request = None
):
    """
    Get user notification preferences.

    Phase 16.4B: Settings page data.
    """
    request_id = getattr(request.state, 'request_id', 'unknown') if request else 'unknown'

    try:
        prefs = await notification_service.get_user_preferences(user_id)

        return {
            "status": "success",
            "user_id": user_id,
            "preferences": prefs,
            "request_id": request_id
        }

    except Exception as e:
        logger.error(f"Failed to get user preferences: {e}")
        return {
            "status": "error",
            "error": str(e),
            "request_id": request_id
        }


@app.put("/user/notification-preferences", response_model=Dict[str, Any])
async def update_user_preferences_endpoint(
    req: UpdatePreferencesRequest,
    user_id: str = "micha",
    request: Request = None
):
    """
    Update user notification preferences.

    Phase 16.4B: Settings page update.
    """
    request_id = getattr(request.state, 'request_id', 'unknown') if request else 'unknown'

    try:
        success = await notification_service.update_user_preferences(
            user_id=user_id,
            telegram_enabled=req.telegram_enabled,
            email_enabled=req.email_enabled,
            dashboard_enabled=req.dashboard_enabled,
            quiet_hours_enabled=req.quiet_hours_enabled,
            quiet_hours_start=req.quiet_hours_start,
            quiet_hours_end=req.quiet_hours_end,
            max_notifications_per_hour=req.max_notifications_per_hour,
            max_notifications_per_day=req.max_notifications_per_day
        )

        if success:
            return {
                "status": "success",
                "message": "Preferences updated",
                "request_id": request_id
            }
        else:
            return {
                "status": "error",
                "error": "Failed to update preferences",
                "request_id": request_id
            }

    except Exception as e:
        logger.error(f"Failed to update user preferences: {e}")
        return {
            "status": "error",
            "error": str(e),
            "request_id": request_id
        }


# =============================================================================
# PHASE 16.4A: FEEDBACK LOOP SYSTEM
# =============================================================================
# PHASE 21: CODE WRITING TOOLS
# =============================================================================

@app.post("/code/confidence", response_model=Dict[str, Any])
async def calculate_confidence_endpoint(
    req: Dict[str, Any],
    request: Request = None
):
    """
    Calculate confidence score for an action.

    Phase 21: Jarvis Self-Programming - Confidence Scoring
    """
    request_id = getattr(request.state, 'request_id', 'unknown') if request else 'unknown'

    try:
        result = code_writing_service.calculate_confidence(req)
        result["request_id"] = request_id
        return result

    except Exception as e:
        logger.error(f"Failed to calculate confidence: {e}")
        return {
            "status": "error",
            "error": str(e),
            "request_id": request_id
        }


@app.post("/code/propose", response_model=Dict[str, Any])
async def propose_code_change_endpoint(
    req: Dict[str, Any],
    request: Request = None
):
    """
    Propose a code change for human review.

    Phase 21: Jarvis Self-Programming - Code Change Proposal
    """
    request_id = getattr(request.state, 'request_id', 'unknown') if request else 'unknown'

    try:
        result = await code_writing_service.propose_code_change(
            file_path=req.get("file_path"),
            change_type=req.get("change_type"),
            description=req.get("description", ""),
            code_snippet=req.get("code_snippet"),
            line_start=req.get("line_start"),
            line_end=req.get("line_end"),
            justification=req.get("justification"),
            context=req.get("context", {})
        )
        result["request_id"] = request_id
        return result

    except Exception as e:
        logger.error(f"Failed to propose code change: {e}")
        return {
            "status": "error",
            "error": str(e),
            "request_id": request_id
        }


@app.get("/code/changes", response_model=Dict[str, Any])
async def get_staged_changes_endpoint(
    status: Optional[str] = None,
    request: Request = None
):
    """
    Get all staged code changes.

    Phase 21: Jarvis Self-Programming - List Changes
    """
    request_id = getattr(request.state, 'request_id', 'unknown') if request else 'unknown'

    try:
        changes = await code_writing_service.get_staged_changes(status)
        return {
            "status": "success",
            "changes": changes,
            "count": len(changes),
            "request_id": request_id
        }

    except Exception as e:
        logger.error(f"Failed to get staged changes: {e}")
        return {
            "status": "error",
            "error": str(e),
            "request_id": request_id
        }


@app.get("/code/changes/{change_id}", response_model=Dict[str, Any])
async def get_change_endpoint(
    change_id: str,
    request: Request = None
):
    """
    Get a specific code change by ID.

    Phase 21: Jarvis Self-Programming - Get Change Details
    """
    request_id = getattr(request.state, 'request_id', 'unknown') if request else 'unknown'

    try:
        change = await code_writing_service.get_change_by_id(change_id)
        if change:
            return {
                "status": "success",
                "change": change,
                "request_id": request_id
            }
        else:
            return {
                "status": "error",
                "error": f"Change {change_id} not found",
                "request_id": request_id
            }

    except Exception as e:
        logger.error(f"Failed to get change: {e}")
        return {
            "status": "error",
            "error": str(e),
            "request_id": request_id
        }


@app.post("/code/changes/{change_id}/approve", response_model=Dict[str, Any])
async def approve_change_endpoint(
    change_id: str,
    request: Request = None
):
    """
    Approve a staged code change.

    Phase 21: Jarvis Self-Programming - Approve Change
    """
    request_id = getattr(request.state, 'request_id', 'unknown') if request else 'unknown'

    try:
        result = await code_writing_service.approve_change(change_id)
        result["request_id"] = request_id
        return result

    except Exception as e:
        logger.error(f"Failed to approve change: {e}")
        return {
            "status": "error",
            "error": str(e),
            "request_id": request_id
        }


@app.post("/code/changes/{change_id}/reject", response_model=Dict[str, Any])
async def reject_change_endpoint(
    change_id: str,
    req: Dict[str, Any] = None,
    request: Request = None
):
    """
    Reject a staged code change.

    Phase 21: Jarvis Self-Programming - Reject Change
    """
    request_id = getattr(request.state, 'request_id', 'unknown') if request else 'unknown'
    reason = req.get("reason", "") if req else ""

    try:
        result = await code_writing_service.reject_change(change_id, reason)
        result["request_id"] = request_id
        return result

    except Exception as e:
        logger.error(f"Failed to reject change: {e}")
        return {
            "status": "error",
            "error": str(e),
            "request_id": request_id
        }


@app.post("/code/changes/{change_id}/apply", response_model=Dict[str, Any])
async def apply_change_endpoint(
    change_id: str,
    request: Request = None
):
    """
    Apply an approved code change to the file.

    Phase 21: Jarvis Self-Programming - Apply Change
    """
    request_id = getattr(request.state, 'request_id', 'unknown') if request else 'unknown'

    try:
        result = await code_writing_service.apply_change(change_id)
        result["request_id"] = request_id
        return result

    except Exception as e:
        logger.error(f"Failed to apply change: {e}")
        return {
            "status": "error",
            "error": str(e),
            "request_id": request_id
        }


@app.post("/code/changes/{change_id}/rollback", response_model=Dict[str, Any])
async def rollback_change_endpoint(
    change_id: str,
    request: Request = None
):
    """
    Rollback an applied code change.

    Phase 21: Jarvis Self-Programming - Rollback Change
    """
    request_id = getattr(request.state, 'request_id', 'unknown') if request else 'unknown'

    try:
        result = await code_writing_service.rollback_change(change_id)
        result["request_id"] = request_id
        return result

    except Exception as e:
        logger.error(f"Failed to rollback change: {e}")
        return {
            "status": "error",
            "error": str(e),
            "request_id": request_id
        }


@app.get("/code/dashboard", response_model=Dict[str, Any])
async def code_writing_dashboard_endpoint(
    request: Request = None
):
    """
    Get code writing activity dashboard.

    Phase 21: Jarvis Self-Programming - Code Writing Dashboard
    """
    request_id = getattr(request.state, 'request_id', 'unknown') if request else 'unknown'

    try:
        result = await code_writing_service.get_code_writing_dashboard()
        result["request_id"] = request_id
        return result

    except Exception as e:
        logger.error(f"Failed to get code writing dashboard: {e}")
        return {
            "status": "error",
            "error": str(e),
            "request_id": request_id
        }


# =============================================================================
# PHASE 16.3B: DASHBOARD UI ROUTES
# =============================================================================

@app.get("/dashboard")
async def serve_dashboard():
    """
    Serve the remediation dashboard HTML page.

    The dashboard provides:
    - Pending approvals list with auto-refresh
    - Approve/Reject buttons
    - Metrics summary
    - Recent activity feed
    """
    import os
    # Try different paths to find the static directory
    possible_paths = [
        "app/static/dashboard.html",
        "static/dashboard.html",
        "/app/app/static/dashboard.html",  # Docker container path
    ]

    for path in possible_paths:
        if os.path.exists(path):
            return FileResponse(path, media_type="text/html")

    return JSONResponse(
        status_code=404,
        content={"error": "Dashboard not found", "searched_paths": possible_paths}
    )


@app.post("/dashboard/api/approve/{remediation_id}")
async def dashboard_approve(remediation_id: str, request: Request):
    """
    Proxy endpoint for dashboard approval - no API key required.

    This endpoint allows the dashboard to approve remediations without
    exposing the API key to the client-side JavaScript.
    """
    request_id = getattr(request.state, 'request_id', 'unknown')

    try:
        body = await request.json()
        user_id = body.get('user_id', 'dashboard_user')
        reason = body.get('reason', 'Approved via dashboard')

        success = remediation_manager.approve_remediation(
            remediation_id=remediation_id,
            approved_by=user_id,
            reason=reason
        )

        if success:
            logger.info(
                f"Remediation approved via dashboard",
                extra={
                    "request_id": request_id,
                    "remediation_id": remediation_id,
                    "user_id": user_id,
                    "source": "dashboard"
                }
            )
            return {
                "status": "success",
                "action": "approved",
                "remediation_id": remediation_id,
                "by": user_id,
                "reason": reason,
                "timestamp": datetime.utcnow().isoformat(),
                "request_id": request_id
            }
        else:
            return JSONResponse(
                status_code=404,
                content={
                    "status": "error",
                    "error": "Remediation not found or already processed",
                    "remediation_id": remediation_id,
                    "request_id": request_id
                }
            )
    except Exception as e:
        logger.error(
            f"Dashboard approval failed",
            extra={
                "request_id": request_id,
                "remediation_id": remediation_id,
                "error": str(e)
            }
        )
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "error": str(e),
                "remediation_id": remediation_id,
                "request_id": request_id
            }
        )


@app.post("/dashboard/api/reject/{remediation_id}")
async def dashboard_reject(remediation_id: str, request: Request):
    """
    Proxy endpoint for dashboard rejection - no API key required.

    This endpoint allows the dashboard to reject remediations without
    exposing the API key to the client-side JavaScript.
    """
    request_id = getattr(request.state, 'request_id', 'unknown')

    try:
        body = await request.json()
        user_id = body.get('user_id', 'dashboard_user')
        reason = body.get('reason', 'Rejected via dashboard')

        # Ensure reason is provided for rejections
        if not reason or len(reason.strip()) < 3:
            return JSONResponse(
                status_code=422,
                content={
                    "status": "error",
                    "error": "Reason is required for rejection (min 3 chars)",
                    "request_id": request_id
                }
            )

        success = remediation_manager.reject_remediation(
            remediation_id=remediation_id,
            rejected_by=user_id,
            reason=reason
        )

        if success:
            logger.info(
                f"Remediation rejected via dashboard",
                extra={
                    "request_id": request_id,
                    "remediation_id": remediation_id,
                    "user_id": user_id,
                    "source": "dashboard"
                }
            )
            return {
                "status": "success",
                "action": "rejected",
                "remediation_id": remediation_id,
                "by": user_id,
                "reason": reason,
                "timestamp": datetime.utcnow().isoformat(),
                "request_id": request_id
            }
        else:
            return JSONResponse(
                status_code=404,
                content={
                    "status": "error",
                    "error": "Remediation not found or already processed",
                    "remediation_id": remediation_id,
                    "request_id": request_id
                }
            )
    except Exception as e:
        logger.error(
            f"Dashboard rejection failed",
            extra={
                "request_id": request_id,
                "remediation_id": remediation_id,
                "error": str(e)
            }
        )
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "error": str(e),
                "remediation_id": remediation_id,
                "request_id": request_id
            }
        )


@app.get("/rate_limits")
def get_rate_limits():
    """Get rate limiter statistics and configuration"""
    from .rate_limiter import RATE_LIMITS, ENDPOINT_TIERS
    return {
        "stats": get_rate_limit_stats(),
        "tiers": {name: {"requests_per_minute": cfg.requests_per_minute, "requests_per_hour": cfg.requests_per_hour}
                  for name, cfg in RATE_LIMITS.items()},
        "endpoint_tiers": ENDPOINT_TIERS
    }

@app.post("/ingest_txt")
def ingest_txt(limit_files: int = 200):
    files = []
    for ns in ["private", "work_projektil", "work_visualfox"]:
        ns_dir = RAW_DIR / ns
        if ns_dir.exists():
            files.extend(list(iter_txt_files(ns_dir)))

    files = files[:limit_files]
    total_chunks = 0

    for f in files:
        rel = f.relative_to(RAW_DIR)
        ns = rel.parts[0]
        out_path = PARSED_DIR / rel
        out_path.parent.mkdir(parents=True, exist_ok=True)

        text = f.read_text(errors="ignore")
        out_path.write_text(text)

        chunks = chunk_text(text)
        embeddings = embed_texts(chunks)

        upsert_chunks(
            collection=f"jarvis_{ns}",
            chunks=chunks,
            embeddings=embeddings,
            meta={
                "source_path": str(rel),
                "namespace": ns,
                "doc_type": "txt",
            }
        )
        total_chunks += len(chunks)

    return {"files_ingested": len(files), "chunks_upserted": total_chunks}

# Phase 16.4: Auto-Learning Helper (sync version for sync endpoints)
def _log_interaction_quality_sync(
    session_id: str,
    query: str,
    response_length: int,
    sources_count: int,
    namespace: str
):
    """
    Log implicit interaction quality signals for learning.
    Minimal, transparent, non-blocking via thread.
    """
    import threading

    def _do_log():
        try:
            from .db_safety import safe_write_query
            with safe_write_query('interaction_quality') as cur:
                cur.execute("""
                    INSERT INTO interaction_quality (
                        session_id, response_length, query_type, namespace,
                        inferred_satisfaction
                    ) VALUES (%s, %s, %s, %s, %s)
                """, (session_id, response_length, "chat", namespace, 0.5))
            log_with_context(logger, "debug", "Interaction quality logged",
                            session_id=session_id, response_length=response_length)
        except Exception as e:
            log_with_context(logger, "debug", "Interaction quality log failed", error=str(e))

    # Run in background thread to not block response
    threading.Thread(target=_do_log, daemon=True).start()


# /chat endpoint removed (legacy RAG, use context_router)

@app.get("/sessions")
def list_sessions(namespace: Optional[str] = None, limit: int = 20):
    """List recent conversation sessions"""
    sessions = state_db.list_sessions(namespace=namespace, limit=limit)
    return {"sessions": sessions}

@app.get("/sessions/{session_id}")
def get_session(session_id: str, limit: int = 50):
    """Get conversation history for a session"""
    session_info = state_db.get_session_info(session_id)
    if not session_info:
        return {"error": "Session not found"}, 404

    messages = state_db.get_conversation_history(session_id, limit=limit)
    return {
        "session": session_info,
        "messages": messages
    }


# === Context Persistence Endpoints ===

@app.get("/context/history")
def get_context_history(
    user_id: int = None,
    days_back: int = 7,
    topic: str = None,
    namespace: str = None,
    limit: int = 10
):
    """Get conversation context history for a user"""
    from . import session_manager
    contexts = session_manager.get_conversation_history(
        user_id=user_id,
        days_back=days_back,
        topic_filter=topic,
        namespace=namespace,
        limit=limit
    )
    return {"contexts": contexts, "count": len(contexts)}


@app.get("/context/pending")
def get_pending_actions(user_id: int = None, include_completed: bool = False, limit: int = 20):
    """Get pending actions/follow-ups from past conversations"""
    from . import session_manager
    actions = session_manager.get_pending_actions(
        user_id=user_id,
        include_completed=include_completed,
        limit=limit
    )
    return {"pending_actions": actions, "count": len(actions)}


@app.get("/context/topics")
def get_frequent_topics(user_id: int = None, days_back: int = 30, limit: int = 10):
    """Get frequently discussed topics"""
    from . import session_manager
    topics = session_manager.get_recent_topics(
        user_id=user_id,
        days_back=days_back,
        limit=limit
    )
    return {"topics": topics, "count": len(topics)}


@app.post("/context/complete/{action_id}")
def complete_action(action_id: int):
    """Mark a pending action as completed"""
    from . import session_manager
    success = session_manager.complete_action(action_id)
    if success:
        return {"status": "completed", "action_id": action_id}
    return {"error": "Action not found"}, 404


# === Pattern Recognition Endpoints ===

@app.get("/patterns")
def get_patterns(user_id: int = None, days: int = 30):
    """Get all detected patterns for a user"""
    from . import pattern_detector
    stats = pattern_detector.get_pattern_stats(user_id=user_id, days=days)
    return stats


@app.get("/patterns/topics")
def get_pattern_topics(user_id: int = None, min_count: int = 1, days: int = 30):
    """Get recurring topic patterns"""
    from . import pattern_detector
    patterns = pattern_detector.detect_recurring_topics(
        user_id=user_id,
        min_count=min_count,
        days=days
    )
    return {
        "patterns": [p.to_dict() for p in patterns],
        "count": len(patterns)
    }


@app.get("/patterns/persons")
def get_pattern_persons(user_id: int = None, days: int = 30):
    """Get person-related patterns"""
    from . import pattern_detector
    patterns = pattern_detector.detect_person_patterns(user_id=user_id, days=days)
    return {
        "patterns": [p.to_dict() for p in patterns],
        "count": len(patterns)
    }


@app.get("/patterns/relevant")
def get_relevant_patterns(user_id: int = None, query: str = None, days: int = 30):
    """Get patterns relevant to a specific query"""
    from . import pattern_detector
    patterns = pattern_detector.get_relevant_patterns(
        user_id=user_id,
        current_query=query,
        days=days
    )
    return {
        "patterns": [p.to_dict() for p in patterns],
        "count": len(patterns),
        "context": pattern_detector.build_pattern_context(patterns) if patterns else ""
    }


# === Sentiment Analysis Endpoints ===

@app.get("/sentiment/analyze")
def analyze_sentiment_endpoint(text: str):
    """Analyze sentiment of a text message"""
    from . import sentiment_analyzer
    result = sentiment_analyzer.analyze_sentiment(text)
    return result.to_dict()


@app.get("/sentiment/history")
def get_sentiment_history(user_id: int = None, days: int = 7, limit: int = 20):
    """Get sentiment history from conversation contexts"""
    from . import session_manager
    contexts = session_manager.get_conversation_history(
        user_id=user_id,
        days_back=days,
        limit=limit
    )
    # Extract emotional indicators from each context
    history = []
    for ctx in contexts:
        if ctx.get("emotional_indicators"):
            history.append({
                "session_id": ctx.get("session_id"),
                "timestamp": ctx.get("start_time"),
                "emotional_indicators": ctx.get("emotional_indicators"),
                "summary": ctx.get("conversation_summary", "")[:100]
            })
    return {"history": history, "count": len(history)}


# ============ Meilisearch Keyword Search Endpoints ============

@app.get("/search/keyword")
def search_keyword(
    query: str,
    namespace: str = None,
    item_type: str = None,
    limit: int = 20
):
    """
    Keyword search for knowledge items using Meilisearch.
    Typo-tolerant, fast, complements semantic search.

    Args:
        query: Search query
        namespace: Filter by namespace (private, work_projektil, etc.)
        item_type: Filter by item type (pattern, fact, preference, etc.)
        limit: Max results (default 20)
    """
    from . import meilisearch_client
    results = meilisearch_client.search_knowledge(
        query=query,
        namespace=namespace,
        item_type=item_type,
        limit=limit
    )
    return {
        "query": query,
        "count": len(results),
        "results": results
    }


@app.get("/search/documents")
def search_documents(
    query: str,
    namespace: str = None,
    doc_type: str = None,
    limit: int = 20
):
    """
    Keyword search for documents using Meilisearch.
    Find documents by title, path, or content preview.
    """
    from . import meilisearch_client
    results = meilisearch_client.search_documents(
        query=query,
        namespace=namespace,
        doc_type=doc_type,
        limit=limit
    )
    return {
        "query": query,
        "count": len(results),
        "results": results
    }


@app.post("/search/meilisearch/setup")
def setup_meilisearch():
    """
    Initialize Meilisearch indexes with proper configuration.
    Run once on first setup or when reconfiguring.
    """
    from . import meilisearch_client
    result = meilisearch_client.setup_indexes()
    return {"status": "configured", "indexes": result}


@app.get("/search/meilisearch/stats")
def meilisearch_stats():
    """Get Meilisearch index statistics."""
    from . import meilisearch_client
    return meilisearch_client.get_index_stats()


@app.post("/search/meilisearch/sync")
def sync_knowledge_to_meilisearch():
    """
    Bulk sync all knowledge items to Meilisearch.
    Run once for initial sync or after data recovery.
    """
    from . import meilisearch_client
    from . import knowledge_store

    # Get all active knowledge items
    items = knowledge_store.get_knowledge_items(
        status="active",
        min_relevance=0.0,
        limit=10000
    )

    result = meilisearch_client.bulk_index_knowledge(items)
    return {
        "status": "synced",
        "items_found": len(items),
        "indexed": result.get("indexed", 0),
        "task_uid": result.get("task_uid")
    }


# ============ Hybrid Search Endpoints ============

@app.get("/search/hybrid")
def search_hybrid(
    query: str,
    namespace: str = None,
    limit: int = 20,
    semantic_weight: float = 0.5,
    keyword_weight: float = 0.5
):
    """
    Hybrid search combining semantic (Qdrant) and keyword (Meilisearch).

    Uses Reciprocal Rank Fusion (RRF) to merge results from both systems.

    Args:
        query: Search query
        namespace: Filter by namespace
        limit: Max results (default 20)
        semantic_weight: Weight for semantic search (0.0-1.0, default 0.5)
        keyword_weight: Weight for keyword search (0.0-1.0, default 0.5)

    Returns:
        Fused results with source info (semantic, keyword, or both)
    """
    from . import hybrid_search

    results = hybrid_search.hybrid_search_simple(
        query=query,
        namespace=namespace,
        limit=limit
    )

    # Count sources
    both = sum(1 for r in results if r.get("source") == "both")
    semantic_only = sum(1 for r in results if r.get("source") == "semantic")
    keyword_only = sum(1 for r in results if r.get("source") == "keyword")

    return {
        "query": query,
        "count": len(results),
        "sources": {
            "both": both,
            "semantic_only": semantic_only,
            "keyword_only": keyword_only
        },
        "results": results
    }


# ============ Dynamic Prompt Fragment Endpoints ============

@app.get("/prompts/fragments")
def list_prompt_fragments(
    user_id: int = None,
    namespace: str = None,
    category: str = None,
    status: str = "approved"
):
    """List prompt fragments with optional filters"""
    from . import knowledge_db

    fragments = knowledge_db.get_prompt_fragments(
        category=category,
        user_id=user_id,
        namespace=namespace,
        status=status,
        include_global=True
    )

    return {
        "count": len(fragments),
        "fragments": [
            {
                "fragment_id": f["fragment_id"],
                "category": f["category"],
                "content": f["content"],
                "priority": f["priority"],
                "status": f["status"],
                "trigger_condition": f.get("trigger_condition"),
                "learned_from": f.get("learned_from"),
                "created_at": str(f.get("created_at", ""))
            }
            for f in fragments
        ]
    }


@app.post("/prompts/fragments")
def create_prompt_fragment(
    category: str,
    content: str,
    priority: int = 50,
    user_id: int = None,
    namespace: str = None,
    trigger_condition: dict = None,
    auto_approve: bool = False
):
    """Create a new prompt fragment"""
    from . import knowledge_db

    status = "approved" if auto_approve else "draft"

    db_id = knowledge_db.create_prompt_fragment(
        category=category,
        content=content,
        trigger_condition=trigger_condition,
        priority=priority,
        user_id=user_id,
        namespace=namespace,
        status=status,
        learned_from="api",
        created_by=f"api:user_{user_id}" if user_id else "api"
    )

    if db_id:
        # Get the created fragment
        with knowledge_db.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT fragment_id FROM prompt_fragment WHERE id = %s", (db_id,))
            row = cur.fetchone()
            fragment_id = row["fragment_id"] if row else None

        return {
            "success": True,
            "fragment_id": fragment_id,
            "status": status
        }

    return {"success": False, "error": "Failed to create fragment"}


@app.post("/prompts/fragments/{fragment_id}/approve")
def approve_fragment(fragment_id: str, approved_by: str = "api"):
    """Approve a draft fragment"""
    from . import knowledge_db

    success = knowledge_db.approve_prompt_fragment(fragment_id, approved_by)
    return {"success": success}


@app.post("/prompts/fragments/{fragment_id}/disable")
def disable_fragment(fragment_id: str, disabled_by: str = "api"):
    """Disable a fragment"""
    from . import knowledge_db

    success = knowledge_db.disable_prompt_fragment(fragment_id, disabled_by)
    return {"success": success}


@app.delete("/prompts/fragments/{fragment_id}")
def delete_fragment(fragment_id: str):
    """Delete a draft fragment (approved fragments can only be disabled)"""
    from . import knowledge_db

    success = knowledge_db.delete_prompt_fragment(fragment_id)
    return {"success": success}


@app.post("/prompts/remember")
def remember_instruction(
    instruction: str,
    user_id: int = None,
    namespace: str = None,
    auto_approve: bool = True
):
    """
    Learn from natural language instruction.

    Examples:
    - "Merke dir: ich mag kurze Antworten"
    - "Bei Stress: sei empathischer"
    - "Ich bevorzuge Bullet Points"
    """
    from . import prompt_assembler

    fragment_id = prompt_assembler.create_learning_fragment(
        user_input=instruction,
        user_id=user_id,
        namespace=namespace,
        auto_approve=auto_approve
    )

    if fragment_id:
        return {
            "success": True,
            "fragment_id": fragment_id,
            "instruction": instruction
        }

    return {
        "success": False,
        "error": "Could not parse instruction. Try: 'Merke dir: ...' or 'Bei Stress: ...'"
    }


@app.get("/prompts/summary")
def get_prompts_summary(user_id: int = None, namespace: str = None):
    """Get summary of active prompt fragments for a user"""
    from . import prompt_assembler

    return prompt_assembler.get_active_fragments_summary(
        user_id=user_id,
        namespace=namespace
    )


@app.get("/prompts/assembled")
def get_assembled_prompt(
    user_id: int = None,
    namespace: str = None,
    query: str = "Test query"
):
    """Preview the assembled system prompt"""
    from . import prompt_assembler
    from . import sentiment_analyzer

    sentiment = sentiment_analyzer.analyze_sentiment(query)

    assembled = prompt_assembler.assemble_system_prompt(
        user_id=user_id,
        namespace=namespace,
        sentiment_result=sentiment.to_dict(),
        include_dynamic=True
    )

    return {
        "fixed_length": assembled.fixed_length,
        "dynamic_length": assembled.dynamic_length,
        "fragment_count": assembled.fragment_count,
        "fragment_ids": assembled.fragment_ids,
        "warnings": assembled.warnings,
        "full_prompt_preview": assembled.full_prompt[:2000] + "..." if len(assembled.full_prompt) > 2000 else assembled.full_prompt
    }


# Coach OS profile endpoints moved to routers/memory_router.py


# ============ Task Management Endpoints ============

@app.get("/tasks")
def list_tasks(
    user_id: int,
    status: str = None,
    priority: str = None,
    context_tag: str = None,
    include_done: bool = False
):
    """List tasks with optional filters"""
    from . import knowledge_db
    tasks = knowledge_db.get_tasks(
        user_id=user_id,
        status=status,
        priority=priority,
        context_tag=context_tag,
        include_done=include_done
    )
    return {"tasks": tasks, "count": len(tasks)}


@app.get("/tasks/today")
def get_today_tasks(user_id: int):
    """Get Today view (high priority + due today, max 5)"""
    from . import knowledge_db
    tasks = knowledge_db.get_tasks_today(user_id)
    return {"tasks": tasks, "count": len(tasks), "view": "today"}


@app.get("/tasks/week")
def get_week_tasks(user_id: int):
    """Get tasks due in next 7 days"""
    from . import knowledge_db
    tasks = knowledge_db.get_tasks_week(user_id)
    return {"tasks": tasks, "count": len(tasks), "view": "week"}


@app.get("/tasks/stats")
def get_task_stats(user_id: int):
    """Get task statistics"""
    from . import knowledge_db
    return knowledge_db.get_task_stats(user_id)


@app.get("/tasks/{task_id}")
def get_task(task_id: int):
    """Get a single task"""
    from . import knowledge_db
    task = knowledge_db.get_task(task_id)
    if not task:
        return {"error": "Task not found"}
    notes = knowledge_db.get_task_notes(task_id)
    return {"task": task, "notes": notes}


@app.post("/tasks")
def create_task(
    user_id: int,
    title: str,
    priority: str = "normal",
    due_date: str = None,
    context_tag: str = "jarvis"
):
    """Create a new task"""
    from . import knowledge_db
    task = knowledge_db.create_task(
        user_id=user_id,
        title=title,
        priority=priority,
        due_date=due_date,
        context_tag=context_tag
    )
    if task:
        return {"success": True, "task": task}
    return {"success": False, "error": "Failed to create task"}


@app.put("/tasks/{task_id}")
def update_task(task_id: int, title: str = None, priority: str = None,
                due_date: str = None, context_tag: str = None, status: str = None):
    """Update a task"""
    from . import knowledge_db
    updates = {}
    if title: updates["title"] = title
    if priority: updates["priority"] = priority
    if due_date: updates["due_date"] = due_date
    if context_tag: updates["context_tag"] = context_tag
    if status: updates["status"] = status

    success = knowledge_db.update_task(task_id, updates)
    return {"success": success}


@app.put("/tasks/{task_id}/status")
def update_task_status(task_id: int, status: str):
    """Quick status update"""
    from . import knowledge_db
    success = knowledge_db.update_task_status(task_id, status)
    return {"success": success, "status": status}


@app.delete("/tasks/{task_id}")
def delete_task(task_id: int):
    """Delete a task"""
    from . import knowledge_db
    success = knowledge_db.delete_task(task_id)
    return {"success": success}


@app.post("/tasks/{task_id}/notes")
def add_task_note(task_id: int, note: str):
    """Add a note to a task"""
    from . import knowledge_db
    note_id = knowledge_db.add_task_note(task_id, note)
    if note_id:
        return {"success": True, "note_id": note_id}
    return {"success": False, "error": "Failed to add note"}


# ============ Project Management Endpoints ============

@app.get("/projects")
def list_projects(user_id: int):
    """List all active projects for a user"""
    from . import projects
    return projects.tool_list_projects(user_id)


@app.post("/projects")
def add_project(user_id: int, name: str, description: str = "", priority: int = 2):
    """Add a new project"""
    from . import projects
    return projects.tool_add_project(user_id, name, description, priority)


@app.put("/projects/{project_id}/status")
def update_project_status(project_id: str, status: str):
    """Update project status (active/paused/completed)"""
    from . import projects
    return projects.tool_update_project_status(project_id, status)


@app.delete("/projects/{project_id}")
def delete_project(project_id: str):
    """Delete a project"""
    from . import projects
    success = projects.delete_project(project_id)
    return {"success": success}


@app.get("/projects/context")
def get_projects_context(user_id: int):
    """Get projects context string for prompt injection"""
    from . import projects
    context = projects.build_projects_context(user_id)
    return {"context": context}


# ============ Entity Extraction Endpoints ============

@app.get("/entities/extract")
def extract_entities_endpoint(
    text: str,
    user_id: int = None,
    people: bool = True,
    projects: bool = True,
    dates: bool = True,
    orgs: bool = True,
    known_only: bool = False
):
    """Extract entities (people, projects, dates) from text"""
    from . import entity_extractor
    result = entity_extractor.extract_entities(
        text=text,
        user_id=user_id,
        extract_people_flag=people,
        extract_projects_flag=projects,
        extract_dates_flag=dates,
        extract_orgs_flag=orgs,
        known_only=known_only
    )
    return result.to_dict()


@app.get("/entities/people")
def extract_people_endpoint(text: str, known_only: bool = False):
    """Extract only people from text"""
    from . import entity_extractor
    entities = entity_extractor.extract_people(text, known_only=known_only)
    return {
        "entities": [e.__dict__ for e in entities],
        "count": len(entities)
    }


@app.get("/entities/dates")
def extract_dates_endpoint(text: str):
    """Extract only dates/times from text"""
    from . import entity_extractor
    entities = entity_extractor.extract_dates(text)
    return {
        "entities": [e.__dict__ for e in entities],
        "count": len(entities)
    }


def ingest_whatsapp_namespace(ns: str, limit_files: int = 50, window_size: int = 8, step: int = 6, skip_existing: bool = True):
    ingest_ts = now_iso()
    inbox = RAW_DIR / ns / "inbox" / "chats"
    processed = inbox / "_processed"
    parsed_out = PARSED_DIR / ns / "comms"
    parsed_out.mkdir(parents=True, exist_ok=True)
    processed.mkdir(parents=True, exist_ok=True)

    if not inbox.exists():
        return {"namespace": ns, "files_ingested": 0, "windows_upserted": 0, "skipped": 0}

    files = [p for p in inbox.glob("*.txt") if p.is_file()]
    files = files[:limit_files]

    total_windows = 0
    files_ingested = 0
    skipped = 0

    for f in files:
        rel_source = f.relative_to(RAW_DIR)
        source_path = str(rel_source)

        # Check if already ingested
        if skip_existing and state_db.is_already_ingested(source_path, "whatsapp"):
            skipped += 1
            continue

        try:
            raw_text = f.read_text(errors="ignore")

            parsed = parse_whatsapp_text(raw_text, source_path=source_path, ingest_ts=ingest_ts)
            msgs = parsed["messages"]

            out_file = parsed_out / (f.stem + ".jsonl")
            with out_file.open("w", encoding="utf-8") as w:
                for m in msgs:
                    w.write(json.dumps(m, ensure_ascii=False) + "\n")

            windows = wa_window_messages(msgs, window_size=window_size, step=step, source_path=source_path)
            window_count = 0
            if windows:
                window_texts = [w["text"] for w in windows]
                embeddings = embed_texts(window_texts)
                # Pass window metadata for deterministic point IDs (dedupe on re-ingest)
                upsert_chunks(
                    collection=f"jarvis_{ns}_comms",
                    chunks=window_texts,
                    embeddings=embeddings,
                    meta={
                        "namespace": ns,
                        "doc_type": "chat_window",
                        "channel": "whatsapp",
                        "source_path": source_path,
                        "ingest_ts": ingest_ts,
                        "event_ts_start": windows[0]["event_ts_start"],
                        "event_ts_end": windows[-1]["event_ts_end"],
                        "window_size": window_size,
                        "step": step,
                    },
                    chunk_metadata=windows  # Each window has window_hash for deterministic IDs
                )
                window_count = len(windows)
                total_windows += window_count

            (processed / f.name).parent.mkdir(parents=True, exist_ok=True)
            f.rename(processed / f.name)
            files_ingested += 1

            # Record success
            state_db.record_ingest(
                source_path=source_path,
                namespace=ns,
                ingest_type="whatsapp",
                ingest_ts=ingest_ts,
                chunks_upserted=window_count,
                status="success"
            )

        except Exception as e:
            # Record error (but don't move file)
            state_db.record_ingest(
                source_path=source_path,
                namespace=ns,
                ingest_type="whatsapp",
                ingest_ts=ingest_ts,
                chunks_upserted=0,
                status="error",
                error_msg=str(e)
            )
            continue

    return {"namespace": ns, "files_ingested": files_ingested, "windows_upserted": total_windows, "skipped": skipped}

@app.post("/ingest_whatsapp_private")
def ingest_whatsapp_private(limit_files: int = 50, skip_existing: bool = True):
    return ingest_whatsapp_namespace("private", limit_files=limit_files, skip_existing=skip_existing)

@app.post("/ingest_whatsapp_work_projektil")
def ingest_whatsapp_work_projektil(limit_files: int = 50, skip_existing: bool = True):
    return ingest_whatsapp_namespace("work_projektil", limit_files=limit_files, skip_existing=skip_existing)

def ingest_gchat_namespace(ns: str, limit_files: int = 50, window_size: int = 10, step: int = 8, skip_existing: bool = True):
    ingest_ts = now_iso()
    inbox = RAW_DIR / ns / "inbox" / "gchat"
    processed = inbox / "_processed"
    parsed_out = PARSED_DIR / ns / "comms_gchat"
    parsed_out.mkdir(parents=True, exist_ok=True)
    processed.mkdir(parents=True, exist_ok=True)

    if not inbox.exists():
        return {"namespace": ns, "files_ingested": 0, "windows_upserted": 0, "skipped": 0}

    files = [p for p in inbox.glob("*.json") if p.is_file()]
    files = files[:limit_files]

    total_windows = 0
    files_ingested = 0
    skipped = 0

    for f in files:
        rel_source = f.relative_to(RAW_DIR)
        source_path = str(rel_source)

        # Check if already ingested
        if skip_existing and state_db.is_already_ingested(source_path, "gchat"):
            skipped += 1
            continue

        try:
            raw_text = f.read_text(errors="ignore")

            parsed = parse_google_chat_json(raw_text, source_path=source_path, ingest_ts=ingest_ts)
            msgs = parsed["messages"]

            out_file = parsed_out / (f.stem + ".jsonl")
            with out_file.open("w", encoding="utf-8") as w:
                for m in msgs:
                    w.write(json.dumps(m, ensure_ascii=False) + "\n")

            windows = gchat_window_messages(msgs, window_size=window_size, step=step, source_path=source_path)
            window_count = 0
            if windows:
                window_texts = [w["text"] for w in windows]
                embeddings = embed_texts(window_texts)
                # Pass window metadata for deterministic point IDs (dedupe on re-ingest)
                upsert_chunks(
                    collection=f"jarvis_{ns}_comms",
                    chunks=window_texts,
                    embeddings=embeddings,
                    meta={
                        "namespace": ns,
                        "doc_type": "chat_window",
                        "channel": "google_chat",
                        "source_path": source_path,
                        "ingest_ts": ingest_ts,
                        "event_ts_start": windows[0]["event_ts_start"],
                        "event_ts_end": windows[-1]["event_ts_end"],
                        "window_size": window_size,
                        "step": step,
                    },
                    chunk_metadata=windows  # Each window has window_hash for deterministic IDs
                )
                window_count = len(windows)
                total_windows += window_count

            (processed / f.name).parent.mkdir(parents=True, exist_ok=True)
            f.rename(processed / f.name)
            files_ingested += 1

            # Record success
            state_db.record_ingest(
                source_path=source_path,
                namespace=ns,
                ingest_type="gchat",
                ingest_ts=ingest_ts,
                chunks_upserted=window_count,
                status="success"
            )

        except Exception as e:
            # Record error (but don't move file)
            state_db.record_ingest(
                source_path=source_path,
                namespace=ns,
                ingest_type="gchat",
                ingest_ts=ingest_ts,
                chunks_upserted=0,
                status="error",
                error_msg=str(e)
            )
            continue

    return {"namespace": ns, "files_ingested": files_ingested, "windows_upserted": total_windows, "skipped": skipped}

@app.post("/ingest_gchat_private")
def ingest_gchat_private(limit_files: int = 50, skip_existing: bool = True):
    return ingest_gchat_namespace("private", limit_files=limit_files, skip_existing=skip_existing)

@app.post("/ingest_gchat_work_projektil")
def ingest_gchat_work_projektil(limit_files: int = 50, skip_existing: bool = True):
    return ingest_gchat_namespace("work_projektil", limit_files=limit_files, skip_existing=skip_existing)


# NOTE: Gmail and Drive ingestion endpoints removed - use n8n workflows instead
# See /n8n/calendar and /n8n/gmail for Google API access via n8n


def ingest_email_embeddings_namespace(ns: str, limit_files: int = 100, skip_existing: bool = True):
    """
    Embeds already-parsed email .txt files from /brain/parsed/<ns>/email/{inbox,sent}/
    Upserts to jarvis_<ns> collection with doc_type=email, channel=gmail

    Args:
        ns: Namespace (e.g. "work_projektil", "private")
        limit_files: Max files to process
        skip_existing: Skip files already successfully ingested (default: True)
    """
    ingest_ts = now_iso()
    email_dir = PARSED_DIR / ns / "email"

    if not email_dir.exists():
        return {"namespace": ns, "files_embedded": 0, "chunks_upserted": 0, "skipped": 0}

    # collect .txt files from inbox and sent subdirs
    files = []
    for label_dir in ["inbox", "sent"]:
        label_path = email_dir / label_dir
        if label_path.exists():
            files.extend(list(label_path.glob("*.txt")))

    files = files[:limit_files]
    total_chunks = 0
    files_embedded = 0
    skipped = 0

    for f in files:
        # Build source_path pointing to raw JSON file
        # f is like: /brain/parsed/<ns>/email/inbox/msg123.txt
        # source should be: <ns>/email/inbox/msg123.json
        rel_parts = f.relative_to(PARSED_DIR).parts
        source_path = str(Path(*rel_parts[:-1]) / f"{f.stem}.json")

        # Check if already ingested
        if skip_existing and state_db.is_already_ingested(source_path, "email_embeddings"):
            skipped += 1
            continue

        try:
            text = f.read_text(errors="ignore")

            # extract label from path (inbox or sent)
            label = f.parent.name  # "inbox" or "sent"
            message_id = f.stem  # filename without .txt

            # Extract event_ts from parsed text (line like "event_ts: 2024-01-15T...")
            import re
            event_ts_match = re.search(r'^event_ts:\s*(.+)$', text, re.MULTILINE)
            event_ts = event_ts_match.group(1).strip() if event_ts_match else None

            # chunk with larger size for emails (vs chat windows)
            chunks = chunk_text(text, max_chars=config.EMAIL_CHUNK_MAX_CHARS, overlap=config.EMAIL_CHUNK_OVERLAP)
            embeddings = embed_texts(chunks)

            upsert_chunks(
                collection=f"jarvis_{ns}",
                chunks=chunks,
                embeddings=embeddings,
                meta={
                    "namespace": ns,
                    "doc_type": "email",
                    "channel": "gmail",
                    "source_path": source_path,
                    "label": label,
                    "message_id": message_id,
                    "ingest_ts": ingest_ts,
                    "event_ts": event_ts,  # Actual email date
                }
            )

            chunk_count = len(chunks)
            total_chunks += chunk_count
            files_embedded += 1

            # Record success
            state_db.record_ingest(
                source_path=source_path,
                namespace=ns,
                ingest_type="email_embeddings",
                ingest_ts=ingest_ts,
                chunks_upserted=chunk_count,
                status="success"
            )

        except Exception as e:
            # Record error
            state_db.record_ingest(
                source_path=source_path,
                namespace=ns,
                ingest_type="email_embeddings",
                ingest_ts=ingest_ts,
                chunks_upserted=0,
                status="error",
                error_msg=str(e)
            )
            # Continue processing other files
            continue

    return {
        "namespace": ns,
        "files_embedded": files_embedded,
        "chunks_upserted": total_chunks,
        "skipped": skipped
    }

@app.post("/ingest_email_embeddings")
def ingest_email_embeddings(namespace: str = "work_projektil", limit_files: int = 100, skip_existing: bool = True):
    return ingest_email_embeddings_namespace(namespace, limit_files=limit_files, skip_existing=skip_existing)

@app.get("/ingest_history")
def ingest_history(
    namespace: Optional[str] = None,
    ingest_type: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100
):
    """Query ingest history with optional filters"""
    return {"history": state_db.get_ingest_history(namespace, ingest_type, status, limit)}

@app.get("/ingest_status")
def ingest_status():
    """Get aggregate ingest stats for health monitoring"""
    return state_db.get_ingest_stats()

# /stats moved to routers/health_router.py

@app.post("/dedupe/{namespace}")
def dedupe_namespace(namespace: str, include_comms: bool = True):
    """
    Remove duplicate points from collections for a namespace.
    Keeps one point per (source_path, text) combination.
    """
    results = {}

    # Main collection
    main_collection = f"jarvis_{namespace}"
    try:
        results["main"] = dedupe_collection(main_collection)
    except Exception as e:
        results["main"] = {"error": str(e)}

    # Comms collection
    if include_comms:
        comms_collection = f"jarvis_{namespace}_comms"
        try:
            results["comms"] = dedupe_collection(comms_collection)
        except Exception as e:
            results["comms"] = {"error": str(e)}

    return results


@app.get("/collection_stats/{namespace}")
def collection_stats(namespace: str, include_comms: bool = True):
    """
    Get collection statistics including content_hash coverage.
    Useful for monitoring dedupe effectiveness.
    """
    from qdrant_client import QdrantClient

    client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
    results = {}

    collections = [f"jarvis_{namespace}"]
    if include_comms:
        collections.append(f"jarvis_{namespace}_comms")

    for coll_name in collections:
        try:
            # Get collection info
            info = client.get_collection(coll_name)
            total_points = info.points_count

            # Sample to check content_hash coverage
            sample_result = client.scroll(
                collection_name=coll_name,
                limit=100,
                with_payload=True,
                with_vectors=False
            )
            sample_points, _ = sample_result

            with_hash = sum(1 for p in sample_points if p.payload and p.payload.get("content_hash"))
            unique_hashes = len(set(p.payload.get("content_hash") for p in sample_points if p.payload and p.payload.get("content_hash")))

            coll_key = "main" if "_comms" not in coll_name else "comms"
            results[coll_key] = {
                "collection": coll_name,
                "total_points": total_points,
                "sample_size": len(sample_points),
                "with_content_hash": with_hash,
                "unique_hashes_in_sample": unique_hashes,
                "hash_coverage_pct": round(with_hash / len(sample_points) * 100, 1) if sample_points else 0
            }

        except Exception as e:
            coll_key = "main" if "_comms" not in coll_name else "comms"
            results[coll_key] = {"error": str(e)}

    return results


@app.post("/agent")
def agent_chat(req: AgentRequest, request: Request):
    """
    Agentic chat endpoint.
    Uses tool-calling to search and reason before responding.
    Supports conversation memory via session_id.
    """
    import uuid
    import time
    
    # Metrics: Start timer and increment request counter
    start_time = time.time()
    metrics.REQUEST_COUNT.labels(role=req.role or "default", namespace=req.namespace).inc()

    try:
        # Guardrails
        validation_error = _validate_agent_request(req)
        if validation_error:
            log_with_context(logger, "warning", "Agent request rejected", error=validation_error)
            metrics.REQUEST_ERRORS.labels(
                role=req.role or "default",
                namespace=req.namespace,
                error_type="ValidationError"
            ).inc()
            raise HTTPException(status_code=400, detail=validation_error)

        request_user_id = _get_request_user_id(request, req.user_id)

        # Streaming mode (SSE): stream LLM text chunks while agent runs.
        if req.stream:
            import queue
            import threading
            from fastapi.responses import StreamingResponse

            q: "queue.Queue[object]" = queue.Queue(maxsize=2000)
            done_sentinel = object()

            def on_delta(chunk: str):
                try:
                    q.put_nowait(("delta", chunk))
                except Exception:
                    # Drop if backpressured; this is a UX feature, not correctness-critical
                    pass

            def worker():
                try:
                    import uuid as _uuid
                    session_id = req.session_id or str(_uuid.uuid4())[:8]
                    state_db.create_session(session_id, req.namespace)
                    conversation_history = state_db.get_conversation_history(session_id, limit=10)

                    result = agent.run_agent(
                        query=req.query,
                        conversation_history=conversation_history,
                        namespace=req.namespace,
                        model=req.model or "claude-sonnet-4-20250514",
                        max_tokens=req.max_tokens,
                        role=req.role,
                        auto_detect_role=req.auto_detect_role,
                        persona_id=req.persona_id,
                        user_id=request_user_id,
                        session_id=session_id,
                        include_context=True,
                        include_explanation=req.include_explanation,
                        stream_callback=on_delta,
                        timeout_seconds=config.AGENT_TIMEOUT_SECONDS,
                        max_rounds=config.AGENT_MAX_ROUNDS,
                    )

                    uncertainty = _derive_agent_uncertainty(result.get("tool_calls", []))
                    _record_latest_agent_uncertainty(req.query, uncertainty)

                    # Metrics: Record token usage and agent rounds
                    metrics.record_token_usage(
                        role=req.role or "default",
                        namespace=req.namespace,
                        input_tokens=result["usage"]["input_tokens"],
                        output_tokens=result["usage"]["output_tokens"]
                    )
                    metrics.record_agent_rounds(
                        role=req.role or "default",
                        namespace=req.namespace,
                        rounds=result.get("rounds", 1)
                    )

                    # Store messages in conversation history
                    state_db.add_message(session_id, "user", req.query, source=req.source)
                    state_db.add_message(
                        session_id,
                        "assistant",
                        result["answer"],
                        tokens_in=result["usage"]["input_tokens"],
                        tokens_out=result["usage"]["output_tokens"],
                        sources=None,
                        source=req.source,
                    )

                    # Auto-generate title
                    session_info = state_db.get_session_info(session_id)
                    if session_info and not session_info.get("title") and session_info.get("message_count", 0) <= 2:
                        title = req.query[:50] + "..." if len(req.query) > 50 else req.query
                        state_db.update_session_title(session_id, title)

                    q.put(("done", {
                        "session_id": session_id,
                        "model": result.get("model"),
                        "usage": result.get("usage"),
                        "rounds": result.get("rounds"),
                        "tool_calls": result.get("tool_calls", []),
                        "confidence_score": uncertainty.get("confidence_score"),
                        "confidence_level": uncertainty.get("confidence_level"),
                        "source_quality": uncertainty.get("source_quality"),
                        "source_count": uncertainty.get("source_count"),
                        "uncertainty_reasons": uncertainty.get("uncertainty_reasons", []),
                        "suggested_alternatives": uncertainty.get("suggested_alternatives", [])
                    }))
                except Exception as e:
                    q.put(("error", str(e)[:300]))
                finally:
                    q.put(done_sentinel)

            threading.Thread(target=worker, daemon=True).start()

            def event_stream():
                yield "event: meta\ndata: {\"stream\": true, \"endpoint\": \"/agent\"}\n\n"
                while True:
                    item = q.get()
                    if item is done_sentinel:
                        break
                    kind, payload = item
                    if kind == "delta":
                        data = json.dumps({"text": payload}, ensure_ascii=False)
                        yield f"event: delta\ndata: {data}\n\n"
                    elif kind == "done":
                        data = json.dumps(payload, ensure_ascii=False)
                        yield f"event: done\ndata: {data}\n\n"
                    elif kind == "error":
                        data = json.dumps({"error": payload}, ensure_ascii=False)
                        yield f"event: error\ndata: {data}\n\n"
                        break

            return StreamingResponse(event_stream(), media_type="text/event-stream")

        # Handle session
        session_id = req.session_id
        if not session_id:
            session_id = str(uuid.uuid4())[:8]

        # Ensure session exists
        state_db.create_session(session_id, req.namespace)

        # Load conversation history
        conversation_history = state_db.get_conversation_history(session_id, limit=10)

        # Run agent
        result = agent.run_agent(
            query=req.query,
            conversation_history=conversation_history,
            namespace=req.namespace,
            model=req.model or "claude-sonnet-4-20250514",
            max_tokens=req.max_tokens,
            role=req.role,
            auto_detect_role=req.auto_detect_role,
            persona_id=req.persona_id,
            user_id=request_user_id,
            session_id=session_id,
            include_context=True,
            include_explanation=req.include_explanation,
            timeout_seconds=config.AGENT_TIMEOUT_SECONDS,
            max_rounds=config.AGENT_MAX_ROUNDS
        )

        uncertainty = _derive_agent_uncertainty(result.get("tool_calls", []))
        _record_latest_agent_uncertainty(req.query, uncertainty)

        # Metrics: Record token usage and agent rounds
        metrics.record_token_usage(
            role=req.role or "default",
            namespace=req.namespace,
            input_tokens=result["usage"]["input_tokens"],
            output_tokens=result["usage"]["output_tokens"]
        )
        metrics.record_agent_rounds(
            role=req.role or "default",
            namespace=req.namespace,
            rounds=result.get("rounds", 1)
        )

        # Build source list from tool calls
        sources = []
        for tc in result.get("tool_calls", []):
            if tc.get("tool") in ("search_knowledge", "search_emails", "search_chats"):
                sources.append({
                    "tool": tc["tool"],
                    "query": tc.get("input", {}).get("query", ""),
                    "result_summary": tc.get("result_summary", "")
                })

        # Store messages in conversation history
        state_db.add_message(session_id, "user", req.query, source=req.source)
        state_db.add_message(
            session_id,
            "assistant",
            result["answer"],
            tokens_in=result["usage"]["input_tokens"],
            tokens_out=result["usage"]["output_tokens"],
            sources=[json.dumps(s) for s in sources] if sources else None,
            source=req.source
        )

        # Auto-generate title
        session_info = state_db.get_session_info(session_id)
        if session_info and not session_info.get("title") and session_info.get("message_count", 0) <= 2:
            title = req.query[:50] + "..." if len(req.query) > 50 else req.query
            state_db.update_session_title(session_id, title)

        response = {
            "query": req.query,
            "answer": result["answer"],
            "tool_calls": result.get("tool_calls", []),
            "rounds": result.get("rounds", 1),
            "model": result["model"],
            "role": result.get("role", "assistant"),
            "persona_id": result.get("persona_id"),
            "usage": result["usage"],
            "session_id": session_id,
            "confidence_score": uncertainty.get("confidence_score"),
            "confidence_level": uncertainty.get("confidence_level"),
            "source_quality": uncertainty.get("source_quality"),
            "source_count": uncertainty.get("source_count"),
            "uncertainty_reasons": uncertainty.get("uncertainty_reasons", []),
            "suggested_alternatives": uncertainty.get("suggested_alternatives", []),
        }

        # Include explanation if requested
        if req.include_explanation and "explanation" in result:
            response["explanation"] = result["explanation"]
            response["explanation_text"] = result.get("explanation_text", "")

        # Metrics: Record duration (success path)
        duration = time.time() - start_time
        metrics.REQUEST_DURATION.labels(role=req.role or "default", namespace=req.namespace).observe(duration)

        return response

    except HTTPException:
        # Record duration and re-raise HTTP exceptions
        duration = time.time() - start_time
        metrics.REQUEST_DURATION.labels(role=req.role or "default", namespace=req.namespace).observe(duration)
        raise
    except Exception as e:
        # Record error and duration
        duration = time.time() - start_time
        metrics.REQUEST_DURATION.labels(role=req.role or "default", namespace=req.namespace).observe(duration)
        metrics.REQUEST_ERRORS.labels(
            role=req.role or "default",
            namespace=req.namespace,
            error_type=type(e).__name__
        ).inc()
        raise


@app.get("/agent/uncertainty/latest")
def get_agent_uncertainty_latest():
    """Return the latest uncertainty snapshot for UI polling."""
    return _latest_agent_uncertainty


@app.post("/learning/decision")
def log_decision(
    user_id: int,
    session_id: str,
    decision_text: str,
    context: str = "",
    category: str = "general",
    confidence: float = 0.5
):
    """Log a decision Jarvis made for cross-session learning."""
    try:
        from .cross_session_learner import cross_session_learner
        decision_id = cross_session_learner.log_decision(
            user_id=user_id,
            session_id=session_id,
            decision_text=decision_text,
            context=context,
            decision_category=category,
            confidence=confidence
        )
        return {
            "status": "logged",
            "decision_id": decision_id,
            "user_id": user_id,
            "session_id": session_id
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


@app.post("/learning/outcome")
def record_outcome(
    decision_id: str,
    outcome: str,
    feedback_score: float = None
):
    """Record the outcome of a decision and feedback (1-5 scale)."""
    try:
        from .cross_session_learner import cross_session_learner
        result = cross_session_learner.record_decision_outcome(
            decision_id=decision_id,
            outcome=outcome,
            feedback_score=feedback_score
        )
        return result
    except Exception as e:
        return {"status": "error", "error": str(e)}


@app.get("/learning/lessons")
def get_lessons(user_id: int, min_confidence: float = 0.5):
    """Get all active lessons learned from this user's sessions."""
    try:
        from .cross_session_learner import cross_session_learner
        lessons = cross_session_learner.get_active_lessons(
            user_id=user_id,
            min_confidence=min_confidence
        )
        return {
            "user_id": user_id,
            "lessons_count": len(lessons),
            "lessons": lessons
        }
    except Exception as e:
        return {"error": str(e), "user_id": user_id}


@app.get("/learning/insights")
def get_insights(user_id: int, days: int = 30):
    """Analyze decision quality and learning progress over time."""
    try:
        from .cross_session_learner import cross_session_learner
        insights = cross_session_learner.get_decision_insights(
            user_id=user_id,
            days=days
        )
        return {
            "user_id": user_id,
            **insights
        }
    except Exception as e:
        return {"error": str(e), "user_id": user_id}


@app.get("/briefing")
def get_briefing(namespace: str = "work_projektil", days: int = 1):
    """Get a daily briefing using the agent"""
    result = agent.get_daily_briefing(namespace=namespace, days=days)
    return result


@app.get("/roles")
def list_roles():
    """List available agent roles/personas"""
    from .roles import list_roles as get_roles
    return {"roles": get_roles()}


@app.get("/memory/stats")
def memory_stats():
    """Get memory store statistics"""
    from . import memory_store
    return memory_store.get_memory_stats()


@app.get("/memory/facts")
def get_facts(category: Optional[str] = None, query: Optional[str] = None, limit: int = 50):
    """List stored facts with optional filters"""
    from . import memory_store
    facts = memory_store.get_facts(category=category, query=query, limit=limit)
    return {"facts": facts, "count": len(facts)}


@app.post("/memory/facts")
def add_fact(fact: str, category: str):
    """Add a new fact to memory"""
    from . import memory_store
    fact_id = memory_store.add_fact(fact, category)
    return {"fact_id": fact_id, "status": "stored"}


@app.get("/memory/entities")
def get_entities(entity_type: Optional[str] = None, limit: int = 50):
    """List stored entities"""
    from . import memory_store
    entities = memory_store.get_entities(entity_type=entity_type, limit=limit)
    return {"entities": entities, "count": len(entities)}


@app.post("/memory/facts/decay")
def decay_facts_endpoint(
    min_days: int = 14,
    decay_rate: float = 0.05,
    limit: int = 100,
    dry_run: bool = False
):
    """
    Apply time-based decay to facts that haven't been accessed recently.

    Facts that haven't been accessed in `min_days` days will have their
    trust_score reduced using exponential decay (half-life ~60 days).

    This helps maintain memory hygiene by naturally deprioritizing
    unused facts while keeping frequently accessed ones.

    Args:
        min_days: Only decay facts not accessed for this many days (default 14)
        decay_rate: Decay rate per day (default 0.05 = ~60 day half-life)
        limit: Max facts to process per call (default 100)
        dry_run: If true, show what would change without updating (default false)

    Returns:
        Stats about decayed facts including details of changes
    """
    from . import memory_store
    result = memory_store.decay_facts(
        min_days_since_accessed=min_days,
        decay_rate=decay_rate,
        limit=limit,
        dry_run=dry_run
    )
    return result


@app.get("/memory/facts/mature")
def get_mature_facts_endpoint(
    min_trust: float = 0.5,
    min_access_count: int = 5,
    min_age_days: int = 7,
    limit: int = 50
):
    """
    Get facts that are mature enough for migration to permanent config.

    Mature facts meet all criteria:
    - Trust score >= min_trust (default 0.5)
    - Access count >= min_access_count (default 5)
    - Age >= min_age_days (default 7)

    These facts have proven their value through repeated use and are
    candidates for migration to YAML configs or permanent storage.

    Returns:
        List of mature facts with their trust scores and access counts
    """
    from . import memory_store
    facts = memory_store.get_mature_facts(
        min_trust_score=min_trust,
        min_access_count=min_access_count,
        min_age_days=min_age_days
    )
    # Apply limit after fetching
    facts = facts[:limit]
    return {
        "mature_facts": facts,
        "count": len(facts),
        "criteria": {
            "min_trust": min_trust,
            "min_access_count": min_access_count,
            "min_age_days": min_age_days
        }
    }


@app.get("/memory/trust-distribution")
def get_trust_distribution():
    """
    Get distribution of trust scores across all active facts.

    Useful for monitoring memory health:
    - high (>= 0.7): Well-proven facts, migration candidates
    - medium (0.4-0.7): Established facts with good usage
    - low (0.1-0.4): Less certain facts, may need reinforcement
    - minimal (< 0.1): New or decayed facts

    Returns:
        Distribution counts and total facts
    """
    from . import memory_store
    distribution = memory_store.get_trust_score_distribution()
    return {"distribution": distribution}


@app.post("/memory/threads/migrate")
def migrate_thread_state():
    """
    Migrate thread_state from SQLite to PostgreSQL active_context_buffer.

    Phase 12.2: One-time migration to consolidate thread state.

    Returns:
        Migration stats: {migrated, skipped, errors}
    """
    from . import session_manager
    result = session_manager.migrate_thread_state_to_postgres()
    return result


@app.get("/context/threads")
def get_context_threads(
    user_id: int = None,
    status: str = None,
    include_closed: bool = False
):
    """
    Get thread states for a user from the consolidated PostgreSQL store.

    Phase 12.2: Unified API for thread management.

    Args:
        user_id: Telegram user ID (default: all users)
        status: Filter by status (open, paused, closed)
        include_closed: Include completed/closed threads

    Returns:
        List of thread states
    """
    from . import session_manager

    if user_id:
        threads = session_manager.get_thread_states(user_id, status=status, include_closed=include_closed)
    else:
        # Get all threads (admin view)
        from . import postgres_state
        with postgres_state.get_cursor() as cur:
            query = "SELECT * FROM active_context_buffer"
            if status:
                pg_status = session_manager._status_to_postgres(status)
                query += f" WHERE status = '{pg_status}'"
            elif not include_closed:
                query += " WHERE status NOT IN ('completed', 'evicted')"
            query += " ORDER BY last_touched_at DESC LIMIT 50"
            cur.execute(query)
            threads = [dict(row) for row in cur.fetchall()]

    return {"threads": threads, "count": len(threads)}


# ============ Decision Outcome & Salience (Phase 12.3) ============

from pydantic import BaseModel, Field

class DecisionOutcomeRequest(BaseModel):
    decision_id: str
    outcome_rating: int = Field(ge=1, le=10)
    knowledge_item_ids: List[str] = []
    outcome_notes: Optional[str] = None
    decision_context: Optional[str] = None
    decision_type: str = "general"
    user_id: Optional[int] = None


@app.post("/decisions/outcome")
def record_decision_outcome_endpoint(request: DecisionOutcomeRequest):
    """
    Record the outcome of a decision that used knowledge items.

    Phase 12.3: Salience signals for outcome-based reinforcement.

    Args (JSON body):
        decision_id: Unique identifier for the decision
        outcome_rating: 1-10 rating (1=very negative, 10=very positive)
        knowledge_item_ids: List of knowledge item IDs that contributed
        outcome_notes: Optional notes about the outcome
        decision_context: Context of what was decided
        decision_type: Type (meeting, email, task, etc.)
        user_id: User who made the decision

    Returns:
        Created outcome record with salience update stats
    """
    from . import postgres_state
    result = postgres_state.record_decision_outcome(
        decision_id=request.decision_id,
        outcome_rating=request.outcome_rating,
        knowledge_item_ids=request.knowledge_item_ids,
        outcome_notes=request.outcome_notes,
        decision_context=request.decision_context,
        decision_type=request.decision_type,
        user_id=request.user_id
    )
    return result


# IMPORTANT: More specific routes must come BEFORE generic path parameter routes
@app.get("/salience/stats")
def get_salience_stats():
    """
    Get aggregate salience statistics.

    Phase 12.3: Monitor outcome-based learning health.

    Returns:
        Stats about salience data across all items
    """
    from . import postgres_state
    return postgres_state.get_salience_stats()


@app.get("/salience/correlation")
def get_salience_correlation():
    """
    Analyze correlation between salience scores and actual decision outcomes.

    Phase 15.5: Validate salience accuracy against real-world usage.

    Returns:
        Correlation analysis with sample size, Pearson coefficient,
        high-salience accuracy, and calibration recommendations.
    """
    from . import postgres_state

    # Get items with outcome data
    with postgres_state.get_cursor() as cur:
        cur.execute("""
            SELECT
                knowledge_item_id,
                salience_score,
                decision_impact,
                goal_relevance,
                surprise_factor,
                positive_outcomes,
                negative_outcomes,
                (positive_outcomes - negative_outcomes) as net_outcome
            FROM knowledge_salience
            WHERE positive_outcomes > 0 OR negative_outcomes > 0
        """)
        items = [dict(row) for row in cur.fetchall()]

    if len(items) < 5:
        return {
            "status": "insufficient_data",
            "sample_size": len(items),
            "message": "Need at least 5 items with outcome data for analysis",
            "recommendation": "Record more decision outcomes via /decision-outcome endpoint"
        }

    # Calculate statistics
    salience_scores = [i['salience_score'] or 0 for i in items]
    net_outcomes = [i['net_outcome'] or 0 for i in items]

    # Basic statistics without numpy
    n = len(salience_scores)
    mean_salience = sum(salience_scores) / n
    mean_outcome = sum(net_outcomes) / n

    # Pearson correlation (manual calculation)
    numerator = sum((s - mean_salience) * (o - mean_outcome)
                   for s, o in zip(salience_scores, net_outcomes))
    denom_salience = sum((s - mean_salience) ** 2 for s in salience_scores) ** 0.5
    denom_outcome = sum((o - mean_outcome) ** 2 for o in net_outcomes) ** 0.5

    if denom_salience > 0 and denom_outcome > 0:
        correlation = numerator / (denom_salience * denom_outcome)
    else:
        correlation = 0.0

    # High-salience accuracy: % of high-salience items (>0.6) with positive outcomes
    high_salience_items = [i for i in items if (i['salience_score'] or 0) >= 0.6]
    if high_salience_items:
        high_salience_positive = sum(1 for i in high_salience_items if (i['net_outcome'] or 0) > 0)
        high_salience_accuracy = high_salience_positive / len(high_salience_items)
    else:
        high_salience_accuracy = None

    # Interpretation
    if correlation > 0.7:
        interpretation = "Strong positive correlation - salience predicts outcomes well"
    elif correlation > 0.4:
        interpretation = "Moderate correlation - salience is useful but could improve"
    elif correlation > 0.1:
        interpretation = "Weak correlation - salience needs recalibration"
    elif correlation > -0.1:
        interpretation = "No correlation - salience formula may need revision"
    else:
        interpretation = "Negative correlation - salience is inversely related to outcomes"

    # Generate recommendations
    recommendations = []
    if correlation < 0.4:
        recommendations.append("Consider adjusting decision_impact weight (currently 35%)")
    if high_salience_accuracy and high_salience_accuracy < 0.8:
        recommendations.append(f"High-salience accuracy is {high_salience_accuracy:.0%}, target is 90%+")
    if mean_salience < 0.3:
        recommendations.append("Average salience is low - check if decay is too aggressive")
    if n < 20:
        recommendations.append("Collect more decision outcomes for reliable analysis")

    return {
        "status": "ok",
        "sample_size": n,
        "correlation": round(correlation, 4),
        "interpretation": interpretation,
        "statistics": {
            "mean_salience": round(mean_salience, 4),
            "mean_net_outcome": round(mean_outcome, 4),
            "high_salience_count": len(high_salience_items),
            "high_salience_accuracy": round(high_salience_accuracy, 4) if high_salience_accuracy else None
        },
        "recommendations": recommendations if recommendations else ["Salience calibration looks good"],
        "formula": "0.35*decision_impact + 0.30*goal_relevance + 0.20*surprise_factor + 0.075 (baseline)"
    }


@app.get("/salience/high")
def get_high_salience_items(
    limit: int = 20,
    min_salience: float = 0.3
):
    """
    Get knowledge items with high salience scores.

    Phase 12.3: Find knowledge that has led to good decisions.

    Args:
        limit: Max items to return
        min_salience: Minimum salience score

    Returns:
        List of high-salience knowledge items
    """
    from . import postgres_state
    items = postgres_state.get_high_salience_items(limit=limit, min_salience=min_salience)
    return {"items": items, "count": len(items)}


@app.post("/salience/goal-relevance")
def update_goal_relevance_endpoint(
    knowledge_item_id: str,
    goal_relevance: float,
    goal_id: str = None
):
    """
    Update goal relevance for a knowledge item.

    Phase 12.3: Link knowledge to active goals.

    Args:
        knowledge_item_id: ID of the knowledge item
        goal_relevance: Relevance score (0.0-1.0)
        goal_id: Optional goal ID for tracking

    Returns:
        Success status
    """
    from . import postgres_state
    success = postgres_state.update_goal_relevance(
        knowledge_item_id=knowledge_item_id,
        goal_relevance=goal_relevance,
        goal_id=goal_id
    )
    return {"success": success, "knowledge_item_id": knowledge_item_id}


# This route MUST come AFTER the specific /salience/* routes above
@app.get("/salience/{knowledge_item_id}")
def get_salience(knowledge_item_id: str):
    """
    Get salience data for a specific knowledge item.

    Phase 12.3: View decision impact, goal relevance, surprise factor.

    Returns:
        Salience breakdown for the item
    """
    from . import postgres_state
    salience = postgres_state.get_knowledge_salience(knowledge_item_id)
    if not salience:
        return {"error": "No salience data found", "knowledge_item_id": knowledge_item_id}
    return salience


@app.post("/salience/decay")
def decay_salience_endpoint(dry_run: bool = True):
    """
    Apply time-based decay to old knowledge items (PostgreSQL salience).

    Phase 12.3: Automatic memory hygiene with 60-day half-life.

    Args:
        dry_run: If true, only show what would be decayed without making changes

    Returns:
        List of facts that were/would be decayed
    """
    from . import postgres_state
    from datetime import datetime, timedelta

    # Get items older than 60 days with salience > 0.1
    cutoff_date = datetime.now() - timedelta(days=60)

    with postgres_state.get_cursor() as cur:
        cur.execute("""
            SELECT ks.knowledge_item_id, ks.salience_score, ks.updated_at,
                   EXTRACT(EPOCH FROM (NOW() - ks.updated_at)) / 86400 as age_days
            FROM knowledge_salience ks
            WHERE ks.updated_at < %s AND ks.salience_score > 0.1
            ORDER BY ks.salience_score ASC
            LIMIT 100
        """, (cutoff_date,))
        old_items = [dict(row) for row in cur.fetchall()]

        if not dry_run:
            # Apply decay: salience_score *= exp(-age_days / 60)
            # This gives 60-day half-life
            import math
            for item in old_items:
                age_days = item["age_days"]
                decay_factor = math.exp(-age_days / 60.0)
                new_salience = max(0.1, item["salience_score"] * decay_factor)

                cur.execute("""
                    UPDATE knowledge_salience
                    SET salience_score = %s, updated_at = NOW()
                    WHERE knowledge_item_id = %s
                """, (new_salience, item["knowledge_item_id"]))

                item["new_salience"] = round(new_salience, 3)
                item["decay_factor"] = round(decay_factor, 3)

    return {
        "dry_run": dry_run,
        "items_affected": len(old_items),
        "items": old_items[:20]  # Limit output to first 20
    }


# ============ n8n Integration (Google API Gateway) ============
# All Google API access (Calendar, Gmail, Drive) via n8n webhooks
# n8n handles OAuth - no direct Google SDK needed

@app.get("/n8n/status")
def n8n_status():
    """Get n8n connection status"""
    from . import n8n_client
    return n8n_client.get_n8n_status()


@app.get("/n8n/calendar")
def n8n_calendar(
    timeframe: str = "week",
    account: str = "all"
):
    """
    Get calendar events with filtering.

    Args:
        timeframe: today, tomorrow, week, all (default: week)
        account: all, visualfox, projektil (default: all)
    """
    from . import n8n_client
    events = n8n_client.get_calendar_events(timeframe=timeframe, account=account)
    include_date = timeframe in ("week", "all")
    return {
        "events": events,
        "count": len(events),
        "timeframe": timeframe,
        "account": account,
        "formatted": n8n_client.format_events_for_briefing(events, include_date=include_date)
    }


@app.get("/n8n/calendar/today")
def n8n_calendar_today():
    """Get today's calendar events from all accounts"""
    from . import n8n_client
    events = n8n_client.get_today_events()
    return {
        "events": events,
        "count": len(events),
        "timeframe": "today",
        "formatted": n8n_client.format_events_for_briefing(events)
    }


@app.get("/n8n/calendar/tomorrow")
def n8n_calendar_tomorrow():
    """Get tomorrow's calendar events from all accounts"""
    from . import n8n_client
    events = n8n_client.get_tomorrow_events()
    return {
        "events": events,
        "count": len(events),
        "timeframe": "tomorrow",
        "formatted": n8n_client.format_events_for_briefing(events)
    }


@app.get("/n8n/calendar/week")
def n8n_calendar_week():
    """Get this week's calendar events from all accounts"""
    from . import n8n_client
    events = n8n_client.get_week_events()
    return {
        "events": events,
        "count": len(events),
        "timeframe": "week",
        "formatted": n8n_client.format_events_for_briefing(events, include_date=True)
    }


@app.get("/n8n/gmail/projektil")
def n8n_gmail_projektil(limit: int = 10):
    """Get recent emails from Projektil Gmail account via n8n"""
    from . import n8n_client
    emails = n8n_client.get_gmail_projektil(limit=limit)
    return {
        "emails": emails,
        "count": len(emails),
        "account": "projektil",
        "formatted": n8n_client.format_emails_for_briefing(emails)
    }


# ============ n8n WRITE Operations ============

class CalendarEventRequest(BaseModel):
    summary: str
    start: str  # ISO 8601 format
    end: str    # ISO 8601 format
    account: str = "projektil"  # projektil or visualfox
    description: str = ""
    location: str = ""
    attendees: List[str] = []


@app.post("/n8n/calendar")
def n8n_create_calendar_event(req: CalendarEventRequest):
    """
    Create a calendar event via n8n.

    Body:
    - summary: Event title (required)
    - start: ISO 8601 datetime (required)
    - end: ISO 8601 datetime (required)
    - account: "projektil" or "visualfox" (default: projektil)
    - description: Event description
    - location: Event location
    - attendees: List of email addresses
    """
    from . import n8n_client
    result = n8n_client.create_calendar_event(
        summary=req.summary,
        start=req.start,
        end=req.end,
        account=req.account,
        description=req.description,
        location=req.location,
        attendees=req.attendees if req.attendees else None
    )
    return result


# ============ Calendar Suggestions (Phase 20.1) ============

class CalendarSuggestionRequest(BaseModel):
    """Request model for calendar event suggestions."""
    summary: str
    start: str  # ISO 8601 format
    end: str    # ISO 8601 format
    account: str = "projektil"  # projektil or visualfox
    description: str = ""
    location: str = ""
    reason: str = ""  # Why this event is being suggested


class CalendarRescheduleRequest(BaseModel):
    """Request model for rescheduling suggestions."""
    event_id: str  # ID of the event to reschedule
    account: str = "projektil"
    new_start: str  # ISO 8601 format
    new_end: str    # ISO 8601 format
    reason: str = ""  # Why rescheduling is suggested


@app.get("/calendar/conflicts")
def get_calendar_conflicts(
    timeframe: str = "week",
    account: str = "all"
):
    """
    Detect calendar conflicts (overlapping events).

    Args:
        timeframe: today, tomorrow, week (default: week)
        account: all, visualfox, projektil (default: all)

    Returns:
        List of conflict pairs with event details
    """
    from . import n8n_client
    from datetime import datetime

    events = n8n_client.get_calendar_events(timeframe=timeframe, account=account)

    # Sort events by start time
    def parse_time(event):
        start = event.get("start", {})
        if isinstance(start, str):
            return start
        return start.get("dateTime") or start.get("date") or ""

    events_sorted = sorted(events, key=parse_time)

    conflicts = []
    for i, event1 in enumerate(events_sorted):
        for event2 in events_sorted[i+1:]:
            # Get start/end times
            e1_start = parse_time(event1)
            e1_end = event1.get("end", {})
            if isinstance(e1_end, dict):
                e1_end = e1_end.get("dateTime") or e1_end.get("date") or ""

            e2_start = parse_time(event2)
            e2_end = event2.get("end", {})
            if isinstance(e2_end, dict):
                e2_end = e2_end.get("dateTime") or e2_end.get("date") or ""

            # Check for overlap
            if e1_end > e2_start:
                conflicts.append({
                    "event1": {
                        "id": event1.get("id"),
                        "summary": event1.get("summary"),
                        "start": e1_start,
                        "end": e1_end,
                        "account": event1.get("account")
                    },
                    "event2": {
                        "id": event2.get("id"),
                        "summary": event2.get("summary"),
                        "start": e2_start,
                        "end": e2_end,
                        "account": event2.get("account")
                    },
                    "overlap_minutes": _calculate_overlap(e1_start, e1_end, e2_start, e2_end)
                })

    return {
        "conflicts": conflicts,
        "count": len(conflicts),
        "timeframe": timeframe,
        "account": account
    }


def _calculate_overlap(e1_start: str, e1_end: str, e2_start: str, e2_end: str) -> int:
    """Calculate overlap duration in minutes."""
    from datetime import datetime
    try:
        # Parse ISO 8601
        e1_end_dt = datetime.fromisoformat(e1_end.replace("Z", "+00:00"))
        e2_start_dt = datetime.fromisoformat(e2_start.replace("Z", "+00:00"))
        e2_end_dt = datetime.fromisoformat(e2_end.replace("Z", "+00:00"))

        overlap_start = max(datetime.fromisoformat(e1_start.replace("Z", "+00:00")), e2_start_dt)
        overlap_end = min(e1_end_dt, e2_end_dt)

        if overlap_end > overlap_start:
            return int((overlap_end - overlap_start).total_seconds() / 60)
    except Exception:
        pass
    return 0


@app.post("/calendar/suggest-event")
def suggest_calendar_event(req: CalendarSuggestionRequest):
    """
    Suggest creating a new calendar event (HITL - requires approval).

    This endpoint:
    1. Validates the suggestion
    2. Creates an action request for approval
    3. Sends Telegram notification with approve/reject buttons
    4. Returns action_id for tracking

    ⚠️ CRITICAL: Does NOT create the event directly!
    Event creation only happens after explicit user approval.

    Body:
    - summary: Event title (required)
    - start: ISO 8601 datetime (required)
    - end: ISO 8601 datetime (required)
    - account: "projektil" or "visualfox" (default: projektil)
    - description: Event description
    - location: Event location
    - reason: Why this event is being suggested
    """
    from .telegram_bot import request_action_approval
    from datetime import datetime

    # Validate times
    try:
        start_dt = datetime.fromisoformat(req.start.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(req.end.replace("Z", "+00:00"))
        if end_dt <= start_dt:
            raise HTTPException(status_code=400, detail="End time must be after start time")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid datetime format: {e}")

    # Format for human-readable display
    start_fmt = start_dt.strftime("%d.%m.%Y %H:%M")
    end_fmt = end_dt.strftime("%H:%M")
    duration = int((end_dt - start_dt).total_seconds() / 60)

    # Create approval request
    description = f"📅 Neuen Termin erstellen:\n\n"
    description += f"**{req.summary}**\n"
    description += f"📆 {start_fmt} - {end_fmt} ({duration} Min)\n"
    description += f"📁 Kalender: {req.account}\n"
    if req.location:
        description += f"📍 {req.location}\n"
    if req.reason:
        description += f"\n💡 Grund: {req.reason}"

    result = request_action_approval(
        action_name="calendar_suggest_event",
        description=description,
        target=f"calendar:{req.account}",
        context={
            "type": "calendar_create",
            "summary": req.summary,
            "start": req.start,
            "end": req.end,
            "account": req.account,
            "description": req.description,
            "location": req.location,
            "reason": req.reason
        },
        urgent=False
    )

    return {
        "status": "pending_approval" if result.get("status") == "pending" else result.get("status"),
        "action_id": result.get("id"),
        "message": "Suggestion sent to Telegram for approval" if result.get("status") == "pending" else result.get("result", {}).get("error", "Unknown status"),
        "expires_at": result.get("expires_at"),
        "suggestion": {
            "summary": req.summary,
            "start": req.start,
            "end": req.end,
            "account": req.account
        }
    }


@app.post("/calendar/suggest-reschedule")
def suggest_calendar_reschedule(req: CalendarRescheduleRequest):
    """
    Suggest rescheduling an existing calendar event (HITL - requires approval).

    This endpoint:
    1. Fetches the original event
    2. Validates the new times
    3. Creates an action request for approval
    4. Sends Telegram notification with approve/reject buttons
    5. Returns action_id for tracking

    ⚠️ CRITICAL: Does NOT modify the event directly!
    Modification only happens after explicit user approval.

    Body:
    - event_id: ID of the event to reschedule (required)
    - account: "projektil" or "visualfox" (default: projektil)
    - new_start: New ISO 8601 start datetime (required)
    - new_end: New ISO 8601 end datetime (required)
    - reason: Why rescheduling is suggested
    """
    from .telegram_bot import request_action_approval
    from . import n8n_client
    from datetime import datetime

    # Validate times
    try:
        new_start_dt = datetime.fromisoformat(req.new_start.replace("Z", "+00:00"))
        new_end_dt = datetime.fromisoformat(req.new_end.replace("Z", "+00:00"))
        if new_end_dt <= new_start_dt:
            raise HTTPException(status_code=400, detail="End time must be after start time")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid datetime format: {e}")

    # Try to find the original event
    events = n8n_client.get_calendar_events(timeframe="all", account=req.account)
    original_event = None
    for event in events:
        if event.get("id") == req.event_id:
            original_event = event
            break

    event_summary = original_event.get("summary", "Unbekannter Termin") if original_event else f"Event {req.event_id}"

    # Format for human-readable display
    new_start_fmt = new_start_dt.strftime("%d.%m.%Y %H:%M")
    new_end_fmt = new_end_dt.strftime("%H:%M")
    duration = int((new_end_dt - new_start_dt).total_seconds() / 60)

    # Get original times for comparison
    original_start = ""
    if original_event:
        orig_start = original_event.get("start", {})
        if isinstance(orig_start, dict):
            original_start = orig_start.get("dateTime", orig_start.get("date", ""))
        else:
            original_start = orig_start
        try:
            orig_dt = datetime.fromisoformat(original_start.replace("Z", "+00:00"))
            original_start = orig_dt.strftime("%d.%m.%Y %H:%M")
        except Exception:
            pass

    # Create approval request
    description = f"🔄 Termin verschieben:\n\n"
    description += f"**{event_summary}**\n"
    if original_start:
        description += f"📆 Alt: {original_start}\n"
    description += f"📆 Neu: {new_start_fmt} - {new_end_fmt} ({duration} Min)\n"
    description += f"📁 Kalender: {req.account}\n"
    if req.reason:
        description += f"\n💡 Grund: {req.reason}"

    result = request_action_approval(
        action_name="calendar_suggest_reschedule",
        description=description,
        target=f"calendar:{req.account}:{req.event_id}",
        context={
            "type": "calendar_reschedule",
            "event_id": req.event_id,
            "account": req.account,
            "new_start": req.new_start,
            "new_end": req.new_end,
            "original_summary": event_summary,
            "original_start": original_start,
            "reason": req.reason
        },
        urgent=False
    )

    return {
        "status": "pending_approval" if result.get("status") == "pending" else result.get("status"),
        "action_id": result.get("id"),
        "message": "Reschedule suggestion sent to Telegram for approval" if result.get("status") == "pending" else result.get("result", {}).get("error", "Unknown status"),
        "expires_at": result.get("expires_at"),
        "suggestion": {
            "event_id": req.event_id,
            "original_summary": event_summary,
            "new_start": req.new_start,
            "new_end": req.new_end,
            "account": req.account
        }
    }


@app.post("/calendar/execute-approved/{action_id}")
def execute_approved_calendar_action(action_id: str):
    """
    Execute an approved calendar action.

    This endpoint is called after an action is approved (via Telegram or API).
    It performs the actual calendar modification.

    ⚠️ Only works for approved actions!
    """
    from . import action_queue, n8n_client

    action = action_queue.get_action(action_id)
    if not action:
        raise HTTPException(status_code=404, detail="Action not found")

    if action.get("status") != "approved":
        raise HTTPException(
            status_code=400,
            detail=f"Action is not approved (status: {action.get('status')})"
        )

    context = action.get("context", {})
    action_type = context.get("type")

    if action_type == "calendar_create":
        # Create new event
        result = n8n_client.create_calendar_event(
            summary=context.get("summary"),
            start=context.get("start"),
            end=context.get("end"),
            account=context.get("account", "projektil"),
            description=context.get("description", ""),
            location=context.get("location", "")
        )

        # Mark action as completed
        action_queue.mark_action_completed(action_id, result=result)

        return {
            "status": "executed",
            "action_type": "calendar_create",
            "result": result
        }

    elif action_type == "calendar_reschedule":
        # Note: Rescheduling requires updating an existing event
        # This would need n8n to support event updates
        # For now, we return a message that manual action is needed

        action_queue.mark_action_completed(action_id, result={
            "status": "manual_action_required",
            "message": "Event rescheduling requires manual update via Google Calendar",
            "event_id": context.get("event_id"),
            "new_start": context.get("new_start"),
            "new_end": context.get("new_end")
        })

        return {
            "status": "manual_action_required",
            "action_type": "calendar_reschedule",
            "message": "Please update the event manually in Google Calendar",
            "details": {
                "event_id": context.get("event_id"),
                "new_start": context.get("new_start"),
                "new_end": context.get("new_end")
            }
        }

    else:
        raise HTTPException(status_code=400, detail=f"Unknown action type: {action_type}")


@app.get("/calendar/suggestions/pending")
def get_pending_calendar_suggestions():
    """
    Get all pending calendar suggestions waiting for approval.
    """
    from . import action_queue

    all_pending = action_queue.get_pending_actions()
    calendar_pending = [
        a for a in all_pending
        if a.get("action") in ["calendar_suggest_event", "calendar_suggest_reschedule"]
    ]

    return {
        "count": len(calendar_pending),
        "suggestions": calendar_pending
    }


@app.get("/calendar/suggestions/history")
def get_calendar_suggestion_history(limit: int = 20):
    """
    Get history of calendar suggestions (approved, rejected, expired).
    """
    from . import action_queue
    from pathlib import Path
    import json

    history = []
    queue_base = Path(action_queue.ACTION_QUEUE_BASE)

    for status_dir in ["approved", "rejected", "expired", "completed"]:
        dir_path = queue_base / status_dir
        if not dir_path.exists():
            continue

        for file_path in dir_path.glob("*.json"):
            try:
                with open(file_path) as f:
                    action = json.load(f)
                    if action.get("action") in ["calendar_suggest_event", "calendar_suggest_reschedule"]:
                        history.append(action)
            except Exception:
                continue

    # Sort by created_at descending
    history.sort(key=lambda x: x.get("created_at", ""), reverse=True)

    return {
        "count": len(history[:limit]),
        "total": len(history),
        "history": history[:limit]
    }


class SendEmailRequest(BaseModel):
    to: str
    subject: str
    body: str
    cc: str = ""
    bcc: str = ""


@app.post("/n8n/gmail")
def n8n_send_email(req: SendEmailRequest):
    """
    Send an email via n8n (Projektil Gmail account).

    Note: Only Projektil has Gmail. Visualfox has no Gmail.

    Body:
    - to: Recipient email (required)
    - subject: Email subject (required)
    - body: Email body - plain text or HTML (required)
    - cc: CC recipients (comma-separated)
    - bcc: BCC recipients (comma-separated)
    """
    from . import n8n_client
    result = n8n_client.send_email(
        to=req.to,
        subject=req.subject,
        body=req.body,
        cc=req.cc,
        bcc=req.bcc
    )
    return result


# ============ Email Draft Reply (Phase 20.2) ============

class EmailDraftReplyRequest(BaseModel):
    """Request model for email reply draft generation."""
    intent: str  # What you want to say: accept, decline, clarify, follow_up, etc.
    context: str = ""  # Additional context
    tone: str = "auto"  # auto, formal, friendly, direct, diplomatic
    include_original: bool = False  # Include quoted original in reply
    model: str = "claude-sonnet-4-20250514"


def _check_draft_rate_limit() -> tuple[bool, int]:
    """Check if draft rate limit (3/day) is reached. Returns (allowed, remaining)."""
    from datetime import datetime

    state = global_state.get_draft_state()
    draft_counts = state.get("counts", {})
    draft_reset_date = state.get("reset_date", "")

    today = datetime.now().strftime("%Y-%m-%d")

    # Reset counter on new day
    if draft_reset_date != today:
        global_state.reset_draft_counts(today)
        draft_counts = {}

    current_count = draft_counts.get("total", 0)
    remaining = 3 - current_count

    return remaining > 0, max(0, remaining)


def _increment_draft_count():
    """Increment the daily draft counter."""
    global_state.increment_draft_count("total")


@app.get("/email/drafts/remaining")
def get_draft_remaining():
    """Get remaining email drafts for today (max 3/day)."""
    allowed, remaining = _check_draft_rate_limit()
    return {
        "allowed": allowed,
        "remaining": remaining,
        "limit": 3,
        "reset": "midnight local time"
    }


@app.post("/email/draft-reply/{email_id}")
def draft_email_reply(email_id: str, req: EmailDraftReplyRequest):
    """
    Generate a reply draft for a specific email (DRAFT ONLY - NO AUTO-SEND).

    ⚠️ CRITICAL SAFEGUARD: This endpoint ONLY generates drafts.
    - NO auto-send capability
    - User must manually review and send
    - Max 3 drafts per day (rate limit)
    - Confidence threshold >= 0.8 required

    Args:
        email_id: The Gmail message ID to reply to

    Body:
        intent: What you want to say (accept, decline, clarify, follow_up, inform, etc.)
        context: Additional context for the reply
        tone: auto, formal, friendly, direct, diplomatic
        include_original: Whether to include quoted original in reply
        model: Claude model to use

    Returns:
        Draft email with subject, body, and metadata.
        The draft is NOT sent - user must copy/paste or use Gmail directly.
    """
    import anthropic
    from .agent import get_client
    from . import n8n_client

    # 1. Check rate limit
    allowed, remaining = _check_draft_rate_limit()
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Daily draft limit reached (3/day). Try again tomorrow."
        )

    # 2. Fetch the original email
    emails = n8n_client.get_gmail_projektil(limit=50)
    original_email = None
    for email in emails:
        if email.get("id") == email_id or email.get("thread_id") == email_id:
            original_email = email
            break

    if not original_email:
        raise HTTPException(
            status_code=404,
            detail=f"Email with ID '{email_id}' not found in recent messages"
        )

    # 3. Extract email info
    sender = original_email.get("from", "")
    sender_email = ""
    sender_name = sender

    # Parse "Name <email@example.com>" format
    if "<" in sender and ">" in sender:
        import re
        match = re.match(r"(.+?)\s*<(.+?)>", sender)
        if match:
            sender_name = match.group(1).strip().strip('"')
            sender_email = match.group(2).strip()
    else:
        sender_email = sender

    original_subject = original_email.get("subject", "(Kein Betreff)")
    original_snippet = original_email.get("snippet", "")
    original_date = original_email.get("date", "")

    # 4. Look up person profile
    profile = None
    profile_context = ""
    person_id = None

    # Try to find by email
    if sender_email:
        profiles = knowledge_db.get_all_person_profiles(status="active")
        for p in profiles:
            content = p.get("content", {}) or {}
            p_email = content.get("email", "").lower()
            if p_email and p_email == sender_email.lower():
                profile = knowledge_db.get_person_profile(p["person_id"])
                person_id = p["person_id"]
                break

    # Build profile context
    if profile:
        content = profile.get("content", {}) or {}
        name = content.get("name", sender_name)
        org = content.get("org", "")
        comm = content.get("communication", {})
        relationship = content.get("relationship", {})

        preferred_style = comm.get("preferred_style", [])
        response_prefs = comm.get("response_preferences", {})
        likes = response_prefs.get("likes", [])
        dislikes = response_prefs.get("dislikes", [])

        dos = [d.get("text") for d in content.get("do", []) if d.get("text")]
        donts = [d.get("text") for d in content.get("dont", []) if d.get("text")]

        profile_context = f"""
## Absender-Profil: {name}
- Organisation: {org}
- Beziehung zu Micha: {relationship.get('role_relation_to_micha', 'Kontakt')} (Trust: {relationship.get('trust_level', 'medium')})
- Bevorzugter Stil: {', '.join(preferred_style) if preferred_style else 'nicht spezifiziert'}
- Mag: {', '.join(likes) if likes else '-'}
- Mag nicht: {', '.join(dislikes) if dislikes else '-'}

## Kommunikations-Empfehlungen
DO: {', '.join(dos[:3]) if dos else '(keine spezifischen)'}
DON'T: {', '.join(donts[:3]) if donts else '(keine spezifischen)'}
"""
    else:
        profile_context = f"## Absender: {sender_name} <{sender_email}>\n(Kein Profil vorhanden - verwende neutralen professionellen Stil)"

    # 5. Determine tone
    tone_instruction = ""
    if req.tone == "auto" and profile:
        content = profile.get("content", {}) or {}
        comm = content.get("communication", {})
        preferred_style = comm.get("preferred_style", [])
        if "short" in preferred_style or "konkret" in preferred_style:
            tone_instruction = "Stil: Kurz und konkret. Keine langen Einleitungen."
        elif "friendly" in preferred_style:
            tone_instruction = "Stil: Freundlich und warm, aber professionell."
        elif "formal" in preferred_style:
            tone_instruction = "Stil: Formell und respektvoll."
        else:
            tone_instruction = "Stil: Professionell und klar."
    elif req.tone == "formal":
        tone_instruction = "Stil: Formell und geschäftsmäßig."
    elif req.tone == "friendly":
        tone_instruction = "Stil: Freundlich und warm."
    elif req.tone == "direct":
        tone_instruction = "Stil: Direkt und auf den Punkt."
    elif req.tone == "diplomatic":
        tone_instruction = "Stil: Diplomatisch und gesichtswahrend."
    else:
        tone_instruction = "Stil: Professionell und klar."

    # 6. Build prompt
    system_prompt = f"""Du bist Michas E-Mail-Assistent. Generiere eine Antwort auf die folgende Email.

{profile_context}

{tone_instruction}

## Original-Email
Von: {sender}
Betreff: {original_subject}
Datum: {original_date}

Inhalt (Snippet): {original_snippet}

## Regeln
- Schreibe als Micha (michael@projektil.ch)
- Intent der Antwort: {req.intent}
- Passe Stil an das Profil an (wenn vorhanden)
- Halte dich kurz - Micha mag keine langen Emails
- Beginne NICHT mit "Sehr geehrte/r" wenn das Profil informellen Stil bevorzugt
- Betreff: Verwende "Re: {original_subject}" oder passe an falls nötig

## Output Format (JSON)
{{
  "subject": "Betreff der Antwort",
  "body": "Der Email-Text (ohne Zitat der Original-Email)",
  "confidence": 0.0-1.0,
  "tone_used": "welcher Ton verwendet wurde",
  "reasoning": "kurze Begründung für den gewählten Ansatz"
}}
"""

    user_message = f"""Generiere eine Antwort auf diese Email.

Intent: {req.intent}
{f"Zusätzlicher Kontext: {req.context}" if req.context else ""}

Erstelle einen passenden Email-Entwurf."""

    # 7. Call Claude
    client = get_client()

    try:
        response = client.messages.create(
            model=req.model,
            max_tokens=1000,
            messages=[{"role": "user", "content": user_message}],
            system=system_prompt,
        )

        llm_response = ""
        for block in response.content:
            if block.type == "text":
                llm_response += block.text

        # Parse JSON response
        try:
            json_text = llm_response
            if "```json" in json_text:
                json_text = json_text.split("```json")[1].split("```")[0]
            elif "```" in json_text:
                json_text = json_text.split("```")[1].split("```")[0]

            result = json.loads(json_text.strip())
        except json.JSONDecodeError:
            return {
                "status": "error",
                "error": "JSON parsing failed",
                "raw_response": llm_response
            }

        # Check confidence threshold
        confidence = result.get("confidence", 0.5)
        if confidence < 0.8:
            return {
                "status": "low_confidence",
                "message": f"Confidence ({confidence:.2f}) below threshold (0.8). Draft may need manual adjustment.",
                "draft": result,
                "original_email": {
                    "id": email_id,
                    "from": sender,
                    "subject": original_subject
                }
            }

        # Success - increment rate limit counter
        _increment_draft_count()
        _, remaining = _check_draft_rate_limit()

        return {
            "status": "ok",
            "message": "⚠️ DRAFT ONLY - Review and send manually via Gmail",
            "draft": {
                "to": sender_email or sender,
                "subject": result.get("subject", f"Re: {original_subject}"),
                "body": result.get("body", ""),
                "confidence": confidence,
                "tone_used": result.get("tone_used", req.tone),
                "reasoning": result.get("reasoning", "")
            },
            "original_email": {
                "id": email_id,
                "thread_id": original_email.get("thread_id"),
                "from": sender,
                "subject": original_subject,
                "date": original_date
            },
            "person_profile": {
                "found": profile is not None,
                "person_id": person_id
            },
            "rate_limit": {
                "drafts_remaining": remaining,
                "limit": 3
            }
        }

    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }


@app.get("/email/drafts/history")
def get_draft_history(limit: int = 10):
    """
    Get history of generated email drafts (for audit).

    Note: Drafts are stored in memory only for the current session.
    For persistent audit, consider storing in PostgreSQL.
    """
    draft_counts = global_state.get_draft_state().get("counts", {})
    return {
        "message": "Draft history not yet implemented - drafts are session-only",
        "today_count": draft_counts.get("total", 0),
        "today_limit": 3,
        "today_remaining": max(0, 3 - draft_counts.get("total", 0))
    }


class DriveSyncRequest(BaseModel):
    folder_id: Optional[str] = None
    limit: int = 50
    namespace: str = "work_projektil"


@app.post("/n8n/drive/sync")
def n8n_drive_sync(req: DriveSyncRequest):
    """
    Trigger Google Drive sync via n8n.

    This workflow:
    1. Lists files in the specified folder (or all accessible)
    2. Downloads/exports content (Docs→text, Sheets→CSV, etc.)
    3. Ingests each file into Jarvis (Qdrant + embeddings)

    Body:
    - folder_id: Optional folder ID to sync (omit for all accessible)
    - limit: Max files to process (default: 50)
    - namespace: Target namespace (default: work_projektil)

    Note: Requires Google Drive OAuth credentials in n8n.
    """
    from . import n8n_client
    return n8n_client.trigger_drive_sync(
        folder_id=req.folder_id,
        limit=req.limit,
        namespace=req.namespace
    )


@app.get("/n8n/drive/status")
def n8n_drive_status():
    """Get Google Drive sync status and capabilities."""
    from . import n8n_client
    return n8n_client.get_drive_sync_status()


class GmailSyncRequest(BaseModel):
    limit: int = 50
    batch_size: int = 50  # Dynamic batching: starts at 50, reduces on rate limits
    namespace: str = "work_projektil"
    days_back: int = 7
    ingest: bool = True


@app.post("/n8n/gmail/sync")
def n8n_gmail_sync(req: GmailSyncRequest):
    """
    Fetch recent emails from Gmail and optionally ingest them.

    This endpoint:
    1. Fetches emails via n8n (Projektil account) with rate limit handling
    2. Uses dynamic batching (50 → 20 → 10) on rate limits
    3. Stores them as parsed .txt files in /brain/parsed/<ns>/email/inbox/
    4. Optionally triggers embedding ingestion

    Body:
    - limit: Max emails to fetch (default: 50)
    - batch_size: Initial batch size (default: 50, reduces on rate limits)
    - namespace: Target namespace (default: work_projektil)
    - days_back: How many days back to fetch (default: 7)
    - ingest: Whether to trigger embedding after fetch (default: True)

    Returns sync statistics including rate limit events.
    """
    from . import n8n_client
    from datetime import datetime
    import hashlib

    results = {
        "fetched": 0,
        "stored": 0,
        "skipped": 0,
        "errors": [],
        "ingested": False,
        "rate_limit_events": 0,
        "final_batch_size": req.batch_size
    }

    batch_size = req.batch_size
    all_emails = []
    max_rate_limit_retries = 3  # How many times to reduce batch size

    try:
        # Fetch emails with rate limit handling and dynamic batching
        rate_limit_retries = 0

        while len(all_emails) < req.limit and rate_limit_retries < max_rate_limit_retries:
            remaining = req.limit - len(all_emails)
            current_batch = min(batch_size, remaining)

            fetch_result = n8n_client.get_gmail_projektil_with_retry(limit=current_batch)

            # Check for rate limit exhaustion
            if fetch_result.get("exhausted"):
                results["rate_limit_events"] += 1
                rate_limit_retries += 1
                # Reduce batch size: 50 → 20 → 10
                old_batch = batch_size
                batch_size = max(10, batch_size // 2)
                if batch_size < old_batch:
                    log_with_context(logger, "warning", "Gmail rate limit: reducing batch size",
                        old_size=old_batch, new_size=batch_size, retry=rate_limit_retries)
                    results["final_batch_size"] = batch_size
                    continue
                else:
                    # Already at minimum batch size
                    results["errors"].append("Rate limit exceeded at minimum batch size")
                    break

            # Track rate limit events even if recovered
            if fetch_result.get("rate_limited"):
                results["rate_limit_events"] += 1

            # Handle fetch errors
            if fetch_result.get("error") and not fetch_result.get("rate_limited"):
                results["errors"].append(f"Fetch error: {fetch_result['error'][:100]}")
                break

            # Collect emails
            batch_emails = fetch_result.get("emails", [])
            if not batch_emails:
                break  # No more emails to fetch

            all_emails.extend(batch_emails)

            # If we got fewer than requested, we've reached the end
            if len(batch_emails) < current_batch:
                break

        emails = all_emails
        results["fetched"] = len(emails)

        if not emails:
            return results

        # Setup output directory
        email_dir = PARSED_DIR / req.namespace / "email" / "inbox"
        email_dir.mkdir(parents=True, exist_ok=True)

        # Store each email as a text file
        for email in emails:
            try:
                # Generate a stable ID from message ID or content hash
                msg_id = email.get("id") or email.get("messageId")
                if not msg_id:
                    # Fallback: hash from subject + from + date
                    content = f"{email.get('subject', '')}{email.get('from', '')}{email.get('date', '')}"
                    msg_id = hashlib.md5(content.encode()).hexdigest()[:16]

                # Check if already exists
                file_path = email_dir / f"{msg_id}.txt"
                if file_path.exists():
                    results["skipped"] += 1
                    continue

                # Parse email to text format
                from_addr = email.get("from", "Unknown")
                to_addr = email.get("to", "Unknown")
                subject = email.get("subject", "(kein Betreff)")
                date = email.get("date") or email.get("internalDate", "")
                snippet = email.get("snippet", "")
                body = email.get("text") or email.get("body", "") or snippet

                # Format as structured text
                text_content = f"""From: {from_addr}
To: {to_addr}
Subject: {subject}
event_ts: {date}

{body}
"""
                # Write to file
                file_path.write_text(text_content, encoding="utf-8")
                results["stored"] += 1

            except Exception as e:
                results["errors"].append(f"Email {msg_id[:8]}: {str(e)[:50]}")

        # Trigger embedding ingestion if requested
        if req.ingest and results["stored"] > 0:
            try:
                ingest_result = ingest_email_embeddings_namespace(
                    req.namespace,
                    limit_files=results["stored"] + 10,
                    skip_existing=True
                )
                results["ingested"] = True
                results["ingest_result"] = ingest_result
            except Exception as e:
                results["errors"].append(f"Ingest failed: {str(e)[:100]}")

    except Exception as e:
        results["errors"].append(f"Fetch failed: {str(e)[:100]}")

    return results


# Scheduler and Telegram endpoints moved to routers/notifications_router.py


# /telegram/status moved to routers/health_router.py


# ============ Action Queue API (Intent-Approval-Execution) ============

class ActionRequest(BaseModel):
    action: str  # Action type (e.g., "knowledge_write", "calendar_modify")
    description: str  # Human-readable description
    target: str | None = None  # Target file/resource path
    context: dict | None = None  # Additional context
    urgent: bool = False  # Mark as urgent for shorter timeout


@app.post("/actions/request")
def request_action(req: ActionRequest):
    """
    Request approval for an action through the Intent-Approval-Execution system.

    This is the main entry point for Jarvis to request permission to perform actions.
    Based on the action's tier, it will either:
    - Execute immediately (Tier 1: Autonomous)
    - Execute and notify (Tier 2: Notify)
    - Queue for approval (Tier 3a/3b: Approve)
    - Block the request (Tier 4: Forbidden)

    Returns:
        Action request with status indicating if approval is needed
    """
    from .telegram_bot import request_action_approval

    result = request_action_approval(
        action_name=req.action,
        description=req.description,
        target=req.target,
        context=req.context,
        urgent=req.urgent
    )

    return result


@app.get("/actions/pending")
def get_pending_actions():
    """
    Get all pending action requests waiting for approval.

    Returns:
        List of pending actions with their details
    """
    from . import action_queue

    pending = action_queue.get_pending_actions()
    return {
        "count": len(pending),
        "actions": pending
    }


@app.get("/actions/{action_id}")
def get_action_status(action_id: str):
    """
    Get the status of a specific action request.

    Returns:
        Action details including current status
    """
    from . import action_queue

    action = action_queue.get_action(action_id)
    if not action:
        raise HTTPException(status_code=404, detail="Action not found")

    return action


@app.post("/actions/{action_id}/approve")
def approve_action_endpoint(action_id: str):
    """
    Approve a pending action request.

    This endpoint is typically called by the user via Telegram buttons,
    but can also be called directly via API.

    Returns:
        Updated action with approved status
    """
    from . import action_queue

    result = action_queue.approve_action(action_id, approved_by="api")
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    return result


@app.post("/actions/{action_id}/reject")
def reject_action_endpoint(action_id: str, reason: str = None):
    """
    Reject a pending action request.

    Args:
        reason: Optional reason for rejection

    Returns:
        Updated action with rejected status
    """
    from . import action_queue

    result = action_queue.reject_action(action_id, rejected_by="api", reason=reason)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    return result


@app.post("/actions/check-expired")
def check_expired_actions():
    """
    Check for and process expired action requests.

    This endpoint can be called periodically (e.g., via n8n cron)
    to clean up expired pending actions.

    Returns:
        List of actions that were marked as expired
    """
    from . import action_queue

    expired = action_queue.check_expired_actions()
    return {
        "expired_count": len(expired),
        "actions": expired
    }


@app.get("/actions/permissions/{action_name}")
def check_action_permission(action_name: str):
    """
    Check the permission tier for a specific action type.

    This is useful for Jarvis to know beforehand if an action
    will require approval.

    Returns:
        Permission tier and requirements for the action
    """
    from . import action_queue

    tier = action_queue.get_action_tier(action_name)
    permissions = action_queue.load_permissions()
    tier_config = permissions.get("tiers", {}).get(tier.value, {})

    return {
        "action": action_name,
        "tier": tier.value,
        "tier_config": tier_config,
        "is_allowed": tier != action_queue.ActionTier.FORBIDDEN,
        "requires_approval": tier in [
            action_queue.ActionTier.APPROVE_STANDARD,
            action_queue.ActionTier.APPROVE_CRITICAL
        ]
    }


# ============ Style Preview ============

class StylePreviewRequest(BaseModel):
    persona_id: str
    text: str


@app.get("/personas")
def list_personas():
    """List available personality profiles"""
    from . import persona
    return {"personas": persona.list_personas()}


@app.post("/render_style_preview")
def render_style_preview(req: StylePreviewRequest):
    """
    Preview how a persona would format text.
    This is a simple template wrapper, not LLM-generated.
    """
    from . import persona
    preview = persona.apply_style_wrapper(req.persona_id, req.text)
    style_prompt = persona.generate_style_prompt(req.persona_id)
    return {
        "persona_id": req.persona_id,
        "preview": preview,
        "style_prompt": style_prompt
    }


class AnswerRequest(BaseModel):
    question: str
    namespace: str = "private"
    collection_suffix: str = ""  # "" or "_comms"
    mode: str = "analyst"  # coach, mirror, analyst, exec, debug
    limit: int = 8
    # Optional filters (passed to search)
    channel: str | None = None
    doc_type: str | None = None
    min_score: float | None = None
    source_path_contains: str | None = None


class AnswerLLMRequest(AnswerRequest):
    model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 1024
    persona_id: str | None = None  # Optional persona for style


@app.get("/modes")
def list_modes():
    """List available answering modes"""
    from . import answer
    return {"modes": answer.list_modes()}


@app.post("/answer")
def answer_question(req: AnswerRequest):
    """
    Structured answer endpoint (deterministic, no LLM).
    Returns answer skeleton with citations and next steps.
    """
    from . import answer
    from .embed import embed_texts

    # Get mode config
    mode = answer.get_mode(req.mode)
    if not mode:
        mode = answer.get_mode(answer.get_default_mode())

    # Build collection name
    collection = f"jarvis_{req.namespace}{req.collection_suffix}"

    # Perform search
    q_vec = embed_texts([req.question])[0]

    # Build filter
    must = []
    if req.channel:
        must.append({"key": "channel", "match": {"value": req.channel}})
    if req.doc_type:
        must.append({"key": "doc_type", "match": {"value": req.doc_type}})

    payload = {
        "vector": q_vec,
        "limit": req.limit,
        "with_payload": True,
    }
    if must:
        payload["filter"] = {"must": must}

    # Search Qdrant
    try:
        r = requests.post(
            f"{QDRANT_BASE}/collections/{collection}/points/search",
            json=payload,
            timeout=30,
        )
        if r.status_code == 404:
            search_results = []
        elif r.status_code == 503:
            search_results = []
        else:
            r.raise_for_status()
            search_results = []
            for hit in r.json().get("result", []):
                pl = hit.get("payload", {}) or {}
                score = hit.get("score", 0)

                # Apply min_score filter
                if req.min_score and score < req.min_score:
                    continue

                # Apply source_path_contains filter
                sp = pl.get("source_path", "")
                if req.source_path_contains and req.source_path_contains not in sp:
                    continue

                search_results.append({
                    "source_path": sp,
                    "text": pl.get("text", ""),
                    "score": score,
                    "channel": pl.get("channel"),
                    "doc_type": pl.get("doc_type"),
                    "ingest_ts": pl.get("ingest_ts"),
                    "event_ts_start": pl.get("event_ts_start"),
                    "event_ts_end": pl.get("event_ts_end"),
                })
    except requests.exceptions.RequestException:
        search_results = []

    # Build sources pack
    sources_pack = answer.build_sources_pack(
        search_results=search_results,
        query=req.question,
        namespace=req.namespace,
        collection=collection,
    )

    # Generate deterministic answer
    result = answer.generate_deterministic_answer(
        sources_pack=sources_pack,
        mode=mode,
        question=req.question,
    )

    return result


@app.post("/answer_llm")
def answer_question_llm(req: AnswerLLMRequest):
    """
    LLM-powered answer endpoint.
    Uses sources + mode template to generate response via Claude.
    Requires citations and honest uncertainty.
    """
    from . import answer
    from . import persona as persona_module
    from .embed import embed_texts
    import anthropic

    # Get mode config
    mode = answer.get_mode(req.mode)
    if not mode:
        mode = answer.get_mode(answer.get_default_mode())

    # Build collection name
    collection = f"jarvis_{req.namespace}{req.collection_suffix}"

    # Perform search (same as /answer)
    q_vec = embed_texts([req.question])[0]

    must = []
    if req.channel:
        must.append({"key": "channel", "match": {"value": req.channel}})
    if req.doc_type:
        must.append({"key": "doc_type", "match": {"value": req.doc_type}})

    payload = {
        "vector": q_vec,
        "limit": req.limit,
        "with_payload": True,
    }
    if must:
        payload["filter"] = {"must": must}

    try:
        r = requests.post(
            f"{QDRANT_BASE}/collections/{collection}/points/search",
            json=payload,
            timeout=30,
        )
        if r.status_code in (404, 503):
            search_results = []
        else:
            r.raise_for_status()
            search_results = []
            for hit in r.json().get("result", []):
                pl = hit.get("payload", {}) or {}
                score = hit.get("score", 0)

                if req.min_score and score < req.min_score:
                    continue

                sp = pl.get("source_path", "")
                if req.source_path_contains and req.source_path_contains not in sp:
                    continue

                search_results.append({
                    "source_path": sp,
                    "text": pl.get("text", ""),
                    "score": score,
                    "channel": pl.get("channel"),
                    "doc_type": pl.get("doc_type"),
                    "ingest_ts": pl.get("ingest_ts"),
                    "event_ts_start": pl.get("event_ts_start"),
                    "event_ts_end": pl.get("event_ts_end"),
                })
    except requests.exceptions.RequestException:
        search_results = []

    # Build sources pack
    sources_pack = answer.build_sources_pack(
        search_results=search_results,
        query=req.question,
        namespace=req.namespace,
        collection=collection,
    )

    # If no sources, return refusal
    if sources_pack.is_empty:
        return {
            "status": "no_data",
            "mode": mode.id,
            "answer": mode.unknown_response,
            "confidence": compute_confidence([]),
            "sources_pack": sources_pack.to_dict(),
        }

    # Generate LLM prompt
    llm_prompt = answer.generate_llm_prompt(
        sources_pack=sources_pack,
        mode=mode,
        question=req.question,
    )

    # Add persona style if specified
    system_prompt = llm_prompt
    if req.persona_id:
        style_prompt = persona_module.generate_style_prompt(req.persona_id)
        if style_prompt:
            system_prompt = f"{llm_prompt}\n\n{style_prompt}"

    # Call Claude
    from .agent import get_client
    client = get_client()

    try:
        response = client.messages.create(
            model=req.model,
            max_tokens=req.max_tokens,
            messages=[{"role": "user", "content": req.question}],
            system=system_prompt,
        )

        llm_answer = ""
        for block in response.content:
            if block.type == "text":
                llm_answer += block.text

        # Compute confidence from sources
        confidence = compute_confidence(search_results)

        return {
            "status": "ok",
            "mode": mode.id,
            "mode_name": mode.name,
            "answer": llm_answer,
            "confidence": confidence,
            "persona_id": req.persona_id,
            "model": req.model,
            "usage": {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            },
            "sources_pack": sources_pack.to_dict(),
        }

    except anthropic.APIError as e:
        return {
            "status": "error",
            "mode": mode.id,
            "error": str(e),
            "confidence": compute_confidence(search_results),
            "sources_pack": sources_pack.to_dict(),
        }


class TimelineRequest(BaseModel):
    """Request model for timeline queries"""
    namespace: str = "work_projektil"
    collection_suffix: str = ""  # "" or "_comms"
    query: str | None = None  # Optional semantic search query
    channel: str | None = None  # e.g. "whatsapp", "google_chat", "gmail"
    doc_type: str | None = None  # e.g. "chat_window", "email"
    person: str | None = None  # Filter by source_path containing person name
    days: int | None = None  # Last N days only
    limit: int = 50
    min_score: float = 0.3  # Only used if query is provided


@app.get("/timeline")
def get_timeline(
    namespace: str = "work_projektil",
    collection_suffix: str = "",
    query: str | None = None,
    channel: str | None = None,
    doc_type: str | None = None,
    person: str | None = None,
    days: int | None = None,
    limit: int = 50,
    min_score: float = 0.3
):
    """
    Timeline endpoint: List chunks chronologically by event_ts.

    Supports:
    - Optional semantic search (query)
    - Filter by channel, doc_type, person
    - Time range filter (days)

    Returns chronologically sorted entries for "was war wann" analysis.
    """
    from qdrant_client import QdrantClient
    from qdrant_client.models import Filter, FieldCondition, MatchValue, Range
    from datetime import timedelta

    client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
    collection = f"jarvis_{namespace}{collection_suffix}"

    # Build filter conditions
    must_conditions = []

    if channel:
        must_conditions.append(FieldCondition(key="channel", match=MatchValue(value=channel)))

    if doc_type:
        must_conditions.append(FieldCondition(key="doc_type", match=MatchValue(value=doc_type)))

    # Build filter object
    scroll_filter = None
    if must_conditions:
        scroll_filter = Filter(must=must_conditions)

    # Calculate date cutoff if days specified
    date_cutoff = None
    tz_zurich = pytz.timezone("Europe/Zurich")

    def _parse_event_ts(ts_value: str) -> Optional[datetime]:
        if not ts_value:
            return None
        try:
            parsed = datetime.fromisoformat(ts_value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=pytz.UTC)
        return parsed.astimezone(tz_zurich)

    def _to_zurich_iso(ts_value: str) -> str:
        parsed = _parse_event_ts(ts_value)
        return parsed.isoformat() if parsed else ts_value

    date_cutoff_dt = None
    if days:
        date_cutoff_dt = datetime.now(tz_zurich) - timedelta(days=days)

    entries = []

    try:
        if query:
            # Semantic search mode: search + sort by event_ts
            q_vec = embed_texts([query])[0]

            # Build payload for search
            search_payload = {
                "vector": q_vec,
                "limit": limit * 2,  # Fetch more to account for filtering
                "with_payload": True,
            }

            if must_conditions:
                search_payload["filter"] = {
                    "must": [
                        {"key": c.key, "match": {"value": c.match.value}}
                        for c in must_conditions
                    ]
                }

            r = requests.post(
                f"{QDRANT_BASE}/collections/{collection}/points/search",
                json=search_payload,
                timeout=30,
            )

            if r.status_code == 404:
                return {"entries": [], "count": 0, "collection": collection, "error": "Collection not found"}

            r.raise_for_status()

            for hit in r.json().get("result", []):
                score = hit.get("score", 0)
                if score < min_score:
                    continue

                pl = hit.get("payload", {}) or {}

                # Get event timestamp (prefer event_ts_start, fall back to event_ts or ingest_ts)
                event_ts_raw = pl.get("event_ts_start") or pl.get("event_ts") or pl.get("ingest_ts") or ""
                event_dt = _parse_event_ts(event_ts_raw)
                event_ts = _to_zurich_iso(event_ts_raw)

                # Apply date filter
                if date_cutoff_dt and event_dt and event_dt < date_cutoff_dt:
                    continue

                # Apply person filter (source_path contains)
                source_path = pl.get("source_path", "")
                if person and person.lower() not in source_path.lower():
                    continue

                entries.append({
                    "event_ts": event_ts,
                    "event_ts_end": _to_zurich_iso(pl.get("event_ts_end") or ""),
                    "source_path": source_path,
                    "channel": pl.get("channel"),
                    "doc_type": pl.get("doc_type"),
                    "text": pl.get("text", "")[:500],  # Truncate for overview
                    "score": round(score, 3),
                    "_event_dt": event_dt,
                })

        else:
            # Scroll mode: fetch all and sort by event_ts
            all_points = []
            offset = None

            while len(all_points) < limit * 2:
                result = client.scroll(
                    collection_name=collection,
                    scroll_filter=scroll_filter,
                    limit=min(500, limit * 2 - len(all_points)),
                    offset=offset,
                    with_payload=True,
                    with_vectors=False
                )
                points, next_offset = result

                if not points:
                    break

                all_points.extend(points)

                if next_offset is None:
                    break
                offset = next_offset

            # Process points
            for point in all_points:
                pl = point.payload or {}

                # Get event timestamp
                event_ts_raw = pl.get("event_ts_start") or pl.get("event_ts") or pl.get("ingest_ts") or ""
                event_dt = _parse_event_ts(event_ts_raw)
                event_ts = _to_zurich_iso(event_ts_raw)

                # Apply date filter
                if date_cutoff_dt and event_dt and event_dt < date_cutoff_dt:
                    continue

                # Apply person filter
                source_path = pl.get("source_path", "")
                if person and person.lower() not in source_path.lower():
                    continue

                entries.append({
                    "event_ts": event_ts,
                    "event_ts_end": _to_zurich_iso(pl.get("event_ts_end") or ""),
                    "source_path": source_path,
                    "channel": pl.get("channel"),
                    "doc_type": pl.get("doc_type"),
                    "text": pl.get("text", "")[:500],
                    "score": None,
                    "_event_dt": event_dt,
                })

    except Exception as e:
        return {"entries": [], "count": 0, "collection": collection, "error": str(e)}

    # Sort by event_ts (ascending = chronological)
    entries.sort(key=lambda x: x.get("_event_dt") or datetime.min.replace(tzinfo=tz_zurich))

    # Apply limit
    entries = entries[:limit]

    for entry in entries:
        entry.pop("_event_dt", None)

    # Build summary stats
    channels_found = list(set(e.get("channel") for e in entries if e.get("channel")))
    doc_types_found = list(set(e.get("doc_type") for e in entries if e.get("doc_type")))

    date_range = None
    if entries:
        first_ts = entries[0].get("event_ts", "")
        last_ts = entries[-1].get("event_ts", "")
        if first_ts and last_ts:
            date_range = {
                "start": first_ts[:10] if len(first_ts) >= 10 else first_ts,
                "end": last_ts[:10] if len(last_ts) >= 10 else last_ts,
            }

    return {
        "entries": entries,
        "count": len(entries),
        "collection": collection,
        "filters_applied": {
            "query": query,
            "channel": channel,
            "doc_type": doc_type,
            "person": person,
            "days": days,
        },
        "summary": {
            "channels": channels_found,
            "doc_types": doc_types_found,
            "date_range": date_range,
        }
    }


@app.post("/timeline")
def post_timeline(req: TimelineRequest):
    """POST version of timeline endpoint for complex queries"""
    return get_timeline(
        namespace=req.namespace,
        collection_suffix=req.collection_suffix,
        query=req.query,
        channel=req.channel,
        doc_type=req.doc_type,
        person=req.person,
        days=req.days,
        limit=req.limit,
        min_score=req.min_score
    )


# ============ Connector State Endpoints ============

@app.get("/connectors")
def list_connectors():
    """List all connector states with health summary"""
    from . import connector_state
    return {"connectors": connector_state.list_connectors()}


@app.get("/connectors/{connector_id}")
def get_connector(connector_id: str):
    """Get detailed connector state"""
    from . import connector_state
    summary = connector_state.get_connector_summary(connector_id)
    if not summary:
        return {"error": "Connector not found"}, 404
    return summary


class ConnectorCreateRequest(BaseModel):
    connector_type: str  # gmail, whatsapp, gchat, calendar
    namespace: str = "work_projektil"
    config: dict = {}


@app.post("/connectors/{connector_id}")
def create_connector(connector_id: str, req: ConnectorCreateRequest):
    """Create or update a connector state"""
    from . import connector_state

    state = connector_state.get_or_create_state(
        connector_id=connector_id,
        connector_type=req.connector_type,
        namespace=req.namespace
    )

    if req.config:
        connector_state.update_config(connector_id, req.config)

    return connector_state.get_connector_summary(connector_id)


@app.post("/connectors/{connector_id}/enable")
def enable_connector(connector_id: str):
    """Enable a connector"""
    from . import connector_state
    success = connector_state.set_enabled(connector_id, True)
    if not success:
        return {"error": "Connector not found"}, 404
    return {"status": "enabled", "connector_id": connector_id}


@app.post("/connectors/{connector_id}/disable")
def disable_connector(connector_id: str):
    """Disable a connector"""
    from . import connector_state
    success = connector_state.set_enabled(connector_id, False)
    if not success:
        return {"error": "Connector not found"}, 404
    return {"status": "disabled", "connector_id": connector_id}


@app.post("/connectors/{connector_id}/reset_errors")
def reset_connector_errors(connector_id: str):
    """Reset error counters for a connector"""
    from . import connector_state
    success = connector_state.reset_errors(connector_id)
    if not success:
        return {"error": "Connector not found"}, 404
    return {"status": "errors_reset", "connector_id": connector_id}


class ConnectorConfigRequest(BaseModel):
    config: dict


@app.patch("/connectors/{connector_id}/config")
def update_connector_config(connector_id: str, req: ConnectorConfigRequest):
    """Update connector configuration"""
    from . import connector_state
    success = connector_state.update_config(connector_id, req.config)
    if not success:
        return {"error": "Connector not found"}, 404
    return connector_state.get_connector_summary(connector_id)


# ============ Mirror Preview Endpoint ============

class MirrorRequest(BaseModel):
    """Request model for message mirror/preview"""
    person_id: str  # ID of person profile (e.g., "patrik", "philippe")
    goal: str  # Communication goal: inform, grenze_setzen, deeskalieren, klären, etc.
    draft: str  # The draft message to transform
    context: str | None = None  # Optional context about the situation
    model: str = "claude-sonnet-4-20250514"


class DraftEmailRequest(BaseModel):
    """Request model for email draft generation with person context"""
    recipient: str  # Person ID or name to search for
    topic: str  # What the email is about
    context: str | None = None  # Additional context (situation, background)
    tone: str = "auto"  # auto, formal, friendly, direct, diplomatic
    include_greeting: bool = True
    include_closing: bool = True
    model: str = "claude-sonnet-4-20250514"


def load_person_profile(person_id: str) -> dict | None:
    """Load person profile from /brain/system/profiles/persons/{person_id}.json"""
    profile_path = BRAIN_ROOT / "system" / "profiles" / "persons" / f"{person_id}.json"
    if not profile_path.exists():
        return None
    try:
        with open(profile_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def build_mirror_prompt(profile: dict, goal: str, draft: str, context: str | None) -> str:
    """Build the system prompt for message mirroring based on person profile"""

    # Extract relevant profile info
    name = profile.get("name", "Person")
    comm = profile.get("communication", {})
    preferred_style = comm.get("preferred_style", [])
    likes = comm.get("response_preferences", {}).get("likes", [])
    dislikes = comm.get("response_preferences", {}).get("dislikes", [])

    dos = [d.get("text") for d in profile.get("do", []) if d.get("text")]
    donts = [d.get("text") for d in profile.get("dont", []) if d.get("text")]

    relationship = profile.get("relationship", {})
    role = relationship.get("role_relation_to_micha", "colleague")
    trust = relationship.get("trust_level", "medium")

    deesc = profile.get("conflict_deescalation", {})
    best_moves = deesc.get("best_moves", [])
    no_go = deesc.get("no_go_moves", [])

    prompt = f"""Du bist ein Kommunikations-Coach, der Micha hilft, Nachrichten für {name} zu optimieren.

## Ziel der Nachricht
{goal}

## Profil: {name}
- Beziehung zu Micha: {role} (Trust: {trust})
- Bevorzugter Stil: {', '.join(preferred_style) if preferred_style else 'nicht spezifiziert'}
- Mag: {', '.join(likes) if likes else '-'}
- Mag nicht: {', '.join(dislikes) if dislikes else '-'}

## Empfehlungen für {name}
DO:
{chr(10).join('- ' + d for d in dos) if dos else '- (keine spezifischen)'}

DON'T:
{chr(10).join('- ' + d for d in donts) if donts else '- (keine spezifischen)'}

## Bei Konflikten
Gute Moves: {', '.join(best_moves) if best_moves else '-'}
No-Go: {', '.join(no_go) if no_go else '-'}

{f"## Kontext{chr(10)}{context}" if context else ""}

## Deine Aufgabe
Transformiere den Draft in 3 Varianten:

1. **team_safe**: Diplomatisch, gesichtswahrend, kollegial
2. **klar_bestimmt**: Direkt, sachlich, mit klarer Grenze
3. **exec_kurz**: Maximal kurz, nur das Wesentliche

Für jede Variante:
- Halte dich an {name}s bevorzugten Stil
- Beachte die DO/DON'T Empfehlungen
- Erkläre kurz (1 Satz), warum diese Variante für {name} funktioniert

Antworte als JSON:
{{
  "variants": [
    {{"style": "team_safe", "text": "...", "note": "..."}},
    {{"style": "klar_bestimmt", "text": "...", "note": "..."}},
    {{"style": "exec_kurz", "text": "...", "note": "..."}}
  ],
  "recommendation": "team_safe|klar_bestimmt|exec_kurz",
  "recommendation_reason": "..."
}}"""

    return prompt


@app.post("/mirror")
def mirror_message(req: MirrorRequest):
    """
    Mirror Preview: Transform a draft message for a specific person.

    Generates 3 variants based on the person's profile:
    - team_safe: Diplomatic, face-saving
    - klar_bestimmt: Clear, direct with boundaries
    - exec_kurz: Ultra-short, essential only

    Uses person profiles from /brain/system/profiles/persons/
    """
    import anthropic

    # Load person profile
    profile = load_person_profile(req.person_id)
    if not profile:
        return {
            "status": "error",
            "error": f"Person profile not found: {req.person_id}",
            "available_profiles": _list_available_profiles()
        }

    # Build prompt
    system_prompt = build_mirror_prompt(profile, req.goal, req.draft, req.context)

    # Call Claude
    from .agent import get_client
    client = get_client()

    try:
        response = client.messages.create(
            model=req.model,
            max_tokens=1500,
            messages=[{"role": "user", "content": f"Draft-Nachricht:\n\n{req.draft}"}],
            system=system_prompt,
        )

        llm_response = ""
        for block in response.content:
            if block.type == "text":
                llm_response += block.text

        # Parse JSON response
        try:
            # Extract JSON from response (handle markdown code blocks)
            json_text = llm_response
            if "```json" in json_text:
                json_text = json_text.split("```json")[1].split("```")[0]
            elif "```" in json_text:
                json_text = json_text.split("```")[1].split("```")[0]

            result = json.loads(json_text.strip())
        except json.JSONDecodeError:
            # Return raw response if JSON parsing fails
            result = {"raw_response": llm_response, "parse_error": True}

        return {
            "status": "ok",
            "person_id": req.person_id,
            "person_name": profile.get("name"),
            "goal": req.goal,
            "original_draft": req.draft,
            "variants": result.get("variants", []),
            "recommendation": result.get("recommendation"),
            "recommendation_reason": result.get("recommendation_reason"),
            "person_context": {
                "trust_level": profile.get("relationship", {}).get("trust_level"),
                "preferred_style": profile.get("communication", {}).get("preferred_style", []),
                "role": profile.get("relationship", {}).get("role_relation_to_micha"),
            },
            "model": req.model,
            "usage": {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            }
        }

    except anthropic.APIError as e:
        return {
            "status": "error",
            "error": str(e),
            "person_id": req.person_id,
        }


def _list_available_profiles() -> list:
    """List available person profile IDs"""
    profiles_dir = BRAIN_ROOT / "system" / "profiles" / "persons"
    if not profiles_dir.exists():
        return []
    return [p.stem for p in profiles_dir.glob("*.json")]


@app.get("/mirror/profiles")
def list_mirror_profiles():
    """List available person profiles for mirror endpoint"""
    profiles_dir = BRAIN_ROOT / "system" / "profiles" / "persons"
    if not profiles_dir.exists():
        return {"profiles": []}

    profiles = []
    for p in profiles_dir.glob("*.json"):
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
                profiles.append({
                    "id": p.stem,
                    "name": data.get("name"),
                    "org": data.get("org"),
                    "role": data.get("relationship", {}).get("role_relation_to_micha"),
                    "trust_level": data.get("relationship", {}).get("trust_level"),
                    "status": data.get("status", "active"),
                })
        except (json.JSONDecodeError, IOError):
            continue

    return {"profiles": profiles}


# ============ Knowledge Layer Endpoints (MOVED TO routers/knowledge_router.py) ============
    insight_text: str
    confidence: str = "medium"
    evidence_sources: list = None


class ReviewDecision(BaseModel):
    action: str  # 'approve' or 'reject'
    resolution_note: str = None



# ============ Consolidation (Nightly Knowledge Generation) ============

@app.post("/consolidate/run")
def run_consolidation_job(
    namespace: str = "work_projektil",
    days: int = 7,
    min_person_mentions: int = 3,
    min_topic_mentions: int = 2,
    dry_run: bool = False
):
    """
    Run consolidation to generate knowledge proposals from recent evidence.

    This is the "sleep-like" consolidation that:
    1. Collects new evidence since last consolidation
    2. Extracts patterns (person mentions, recurring topics)
    3. Generates knowledge proposals
    4. Submits to review queue (HITL)

    Use dry_run=true to preview without creating proposals.
    """
    from . import consolidation

    result = consolidation.run_consolidation(
        namespace=namespace,
        days=days,
        min_person_mentions=min_person_mentions,
        min_topic_mentions=min_topic_mentions,
        dry_run=dry_run
    )
    return result


@app.get("/consolidate/stats")
def get_consolidation_stats():
    """Get consolidation statistics for all namespaces"""
    from . import consolidation

    stats = consolidation.get_consolidation_stats()
    return stats


@app.get("/consolidate/status/{namespace}")
def get_consolidation_status(namespace: str):
    """Get consolidation status for a specific namespace"""
    from . import consolidation

    last_ts = consolidation.get_last_consolidation_ts(namespace)
    stats = consolidation.get_consolidation_stats()
    ns_stats = stats.get("namespaces", {}).get(namespace, {})

    return {
        "namespace": namespace,
        "last_consolidation": last_ts.isoformat() if last_ts else None,
        "run_count": ns_stats.get("run_count", 0),
        "total_proposals": ns_stats.get("total_proposals", 0)
    }


# ============ Relevance Engine (Decay/Reinforce/Archive) ============

@app.post("/relevance/decay/batch")
def decay_batch_items(
    namespace: str = None,
    item_type: str = None,
    min_days_since_seen: int = 7,
    limit: int = 100
):
    """Apply decay to multiple items that haven't been seen recently"""
    from . import relevance_engine

    result = relevance_engine.decay_batch(
        namespace=namespace,
        item_type=item_type,
        min_days_since_seen=min_days_since_seen,
        limit=limit
    )
    return {"status": "processed", "result": result}


@app.post("/relevance/decay/{item_id}")
def decay_single_item(item_id: int, reason: str = None):
    """Apply time-based decay to a single knowledge item"""
    from . import relevance_engine

    result = relevance_engine.decay_item(item_id, reason=reason)
    if result:
        return {"status": "decayed", "result": result}
    return {"status": "error", "message": "Failed to decay item or item not found"}


@app.post("/relevance/reinforce/{item_id}")
def reinforce_item(item_id: int, boost: float = None, reason: str = None):
    """Reinforce a knowledge item (increase relevance when confirmed/used)"""
    from . import relevance_engine

    result = relevance_engine.reinforce_item(item_id, boost=boost, reason=reason)
    if result:
        return {"status": "reinforced", "result": result}
    return {"status": "error", "message": "Failed to reinforce item"}


@app.post("/relevance/seen/{item_id}")
def mark_item_seen(item_id: int):
    """Mark an item as seen (updates last_seen_at without changing relevance)"""
    from . import relevance_engine

    success = relevance_engine.mark_seen(item_id)
    return {"status": "marked" if success else "error", "item_id": item_id}


@app.post("/relevance/archive/{item_id}")
def archive_item(item_id: int, reason: str = None):
    """Archive a knowledge item (status change, no deletion)"""
    from . import relevance_engine

    result = relevance_engine.archive_item(item_id, reason=reason)
    if result:
        return {"status": "processed", "result": result}
    return {"status": "error", "message": "Failed to archive item"}


@app.post("/relevance/unarchive/{item_id}")
def unarchive_item(item_id: int, new_relevance: float = 0.5):
    """Restore an archived item to active status"""
    from . import relevance_engine

    result = relevance_engine.unarchive_item(item_id, new_relevance=new_relevance)
    if result:
        return {"status": "unarchived", "result": result}
    return {"status": "error", "message": "Failed to unarchive item"}


@app.get("/relevance/candidates")
def get_archive_candidates(namespace: str = None, threshold: float = None, limit: int = 20):
    """Get items that are candidates for archiving (below relevance threshold)"""
    from . import relevance_engine

    candidates = relevance_engine.get_archive_candidates(
        namespace=namespace,
        threshold=threshold,
        limit=limit
    )
    return {"candidates": candidates, "count": len(candidates)}


@app.get("/relevance/distribution")
def get_relevance_distribution(namespace: str = None):
    """Get distribution of relevance scores across items"""
    from . import relevance_engine

    dist = relevance_engine.get_relevance_distribution(namespace=namespace)
    return {"distribution": dist}


# ============ Salience Engine (Phase 11: Outcome-based Reinforcement) ============

@app.post("/salience/init")
def init_salience_columns():
    """Add salience columns to knowledge_item table (safe migration)"""
    from . import knowledge_db

    success = knowledge_db.add_salience_columns()
    return {"status": "success" if success else "error"}


@app.post("/salience/decay/batch")
def decay_salience_batch(decay_rate: float = 0.05, min_salience: float = 0.1):
    """
    Apply time-based decay to salience components.

    Decays goal_relevance and surprise_factor (novelty wears off).
    decision_impact is NOT decayed (learning persists).

    Call daily via n8n cron.
    """
    from . import knowledge_db

    result = knowledge_db.decay_salience_batch(decay_rate=decay_rate, min_salience=min_salience)
    return {"status": "processed", "result": result}


@app.post("/salience/update/{item_id}")
def update_item_salience(
    item_id: int,
    decision_impact: float = None,
    goal_relevance: float = None,
    surprise_factor: float = None
):
    """
    Update salience components for a knowledge item.

    Pass only the components you want to update. Omitted components keep their current value.
    Salience score is automatically recomputed.
    """
    from . import knowledge_db

    result = knowledge_db.update_knowledge_salience(
        item_id=item_id,
        decision_impact=decision_impact,
        goal_relevance=goal_relevance,
        surprise_factor=surprise_factor
    )
    if result:
        return {"status": "updated", "item": result}
    return {"status": "error", "message": "Failed to update salience or item not found"}


@app.post("/salience/reinforce/{item_id}")
def reinforce_from_decision_outcome(
    item_id: int,
    outcome_rating: int,
    was_used: bool = True
):
    """
    Reinforce salience based on decision outcome.

    Called when knowledge was used in a decision with a measurable outcome.
    - Positive outcomes (7-10) increase decision_impact
    - Negative outcomes (1-4) decrease decision_impact

    Args:
        item_id: Knowledge item ID
        outcome_rating: 1-10 rating of the decision outcome
        was_used: Whether this knowledge was actually used (default True)
    """
    from . import knowledge_db

    result = knowledge_db.reinforce_from_decision(
        item_id=item_id,
        outcome_rating=outcome_rating,
        was_used=was_used
    )
    if result:
        return {"status": "reinforced", "item": result}
    return {"status": "skipped" if not was_used else "error"}


@app.post("/salience/goal/{item_id}")
def set_item_goal_relevance(item_id: int, goal_id: str, relevance: float):
    """
    Set goal relevance for a knowledge item.

    Call when linking knowledge to active goals/priorities.
    Higher relevance = knowledge is more important for current objectives.
    """
    from . import knowledge_db

    result = knowledge_db.set_goal_relevance(item_id, goal_id, relevance)
    if result:
        return {"status": "updated", "item": result}
    return {"status": "error", "message": "Failed to set goal relevance"}


@app.post("/salience/surprising/{item_id}")
def mark_item_surprising(item_id: int, surprise_level: float = 0.8):
    """
    Mark a knowledge item as surprising/novel.

    Surprise factor decays over time (daily decay batch).
    Use when discovering unexpected information.
    """
    from . import knowledge_db

    result = knowledge_db.mark_as_surprising(item_id, surprise_level)
    if result:
        return {"status": "marked", "item": result}
    return {"status": "error", "message": "Failed to mark as surprising"}


# ============ Self-Model / Consolidation (Personality Persistence) ============







@app.post("/consolidate")
def run_consolidation(model_id: str = "default"):
    """
    Run consolidation job to update self-model from recent interactions.

    Analyzes last 7 days of conversations for:
    - User patterns and preferences
    - Performance indicators (what worked, what didn't)
    - Creates a snapshot if significant changes detected
    """
    from . import knowledge_db

    result = knowledge_db.consolidate_self_model(model_id)
    return result




# ============ Domain Separation ============

@app.get("/domain/config")
def get_domain_config():
    """Get current domain separation configuration"""
    from . import domain_separation

    return domain_separation.get_config()


@app.get("/domain/allowed")
def get_allowed_collections_endpoint(namespace: str):
    """Get allowed collections for a namespace"""
    from . import domain_separation

    if not domain_separation.validate_namespace(namespace):
        return {"error": f"Invalid namespace: {namespace}", "namespace": namespace}

    collections = domain_separation.get_allowed_collections(namespace)
    return {"namespace": namespace, "allowed_collections": collections}


@app.get("/domain/check")
def check_domain_access(
    source_namespace: str,
    target_namespace: str,
    operation: str = "read"
):
    """Check if access is allowed between namespaces"""
    from . import domain_separation

    result = domain_separation.check_access(
        source_namespace=source_namespace,
        target_namespace=target_namespace,
        access_type=operation
    )
    return result


# ============ Email Pattern Learning ============

class EmailInteractionRequest(BaseModel):
    email_id: str
    direction: str  # 'inbound' or 'outbound'
    contact_email: str
    timestamp: str  # ISO format
    thread_id: str | None = None
    contact_name: str | None = None
    subject: str | None = None
    response_to_id: str | None = None


@app.post("/email_patterns/record")
def record_email_for_patterns(req: EmailInteractionRequest):
    """
    Record an email interaction for pattern learning.
    Call this when emails are ingested or sent.
    """
    from . import state_db

    result = state_db.record_email_interaction(
        email_id=req.email_id,
        direction=req.direction,
        contact_email=req.contact_email,
        timestamp=req.timestamp,
        thread_id=req.thread_id,
        contact_name=req.contact_name,
        subject=req.subject,
        response_to_id=req.response_to_id
    )
    return {"success": True, "recorded": result}


@app.get("/email_patterns/predict/{contact_email:path}")
def predict_email_response(contact_email: str):
    """
    Predict when a contact is likely to respond.
    Use this to determine optimal follow-up timing.
    """
    from . import state_db

    prediction = state_db.predict_response_time(contact_email)
    return prediction


@app.get("/email_patterns/contact/{contact_email:path}")
def get_contact_email_pattern(contact_email: str):
    """Get learned email patterns for a specific contact"""
    from . import state_db

    pattern = state_db.get_contact_pattern(contact_email)
    if pattern:
        return {"found": True, "pattern": pattern}
    return {"found": False, "contact": contact_email}


@app.get("/email_patterns/contacts")
def list_email_patterns(
    min_interactions: int = 3,
    order_by: str = "last_interaction",
    limit: int = 50
):
    """
    List all contacts with learned patterns.

    order_by: 'last_interaction', 'avg_response', 'total_emails'
    """
    from . import state_db

    patterns = state_db.list_contact_patterns(
        min_interactions=min_interactions,
        order_by=order_by,
        limit=limit
    )
    return {"contacts": patterns, "count": len(patterns)}


@app.get("/email_patterns/stats")
def get_email_pattern_statistics():
    """Get overall email pattern statistics"""
    from . import state_db

    stats = state_db.get_email_pattern_stats()
    return stats


# ============ Conflict Detection (Phase 9) ============

class FactRequest(BaseModel):
    entity_type: str  # 'person', 'project', 'company', 'event'
    entity_id: str
    attribute: str
    value: str
    source_type: str
    source_id: str | None = None
    source_date: str | None = None
    confidence: float = 1.0


@app.post("/facts")
def record_fact_endpoint(req: FactRequest):
    """
    Record a fact about an entity. Automatically detects conflicts.

    Example: Record that "Philippe's title is CEO" from email xyz.
    If another source says "Philippe's title is Director", a conflict is created.
    """
    from . import state_db

    result = state_db.record_fact(
        entity_type=req.entity_type,
        entity_id=req.entity_id,
        attribute=req.attribute,
        value=req.value,
        source_type=req.source_type,
        source_id=req.source_id,
        source_date=req.source_date,
        confidence=req.confidence
    )
    return result


@app.get("/facts/{entity_type}/{entity_id}")
def get_entity_facts(
    entity_type: str,
    entity_id: str,
    attribute: str = None,
    current_only: bool = True
):
    """Get all facts for an entity, optionally filtered by attribute."""
    from . import state_db

    facts = state_db.get_facts_for_entity(
        entity_type=entity_type,
        entity_id=entity_id,
        attribute=attribute,
        current_only=current_only
    )
    return {"entity_type": entity_type, "entity_id": entity_id, "facts": facts}


@app.get("/facts/{entity_type}/{entity_id}/truth")
def get_entity_current_truth(entity_type: str, entity_id: str):
    """
    Get the current truth for an entity - one value per attribute.
    Uses: resolved conflicts > highest confidence > newest source.
    """
    from . import state_db

    truth = state_db.get_current_truth(entity_type, entity_id)
    return truth


@app.get("/conflicts")
def list_conflicts_endpoint(
    status: str = "open",
    entity_type: str = None,
    limit: int = 50
):
    """
    List detected conflicts.

    status: 'open', 'resolved', 'ignored', or None for all
    """
    from . import state_db

    conflicts = state_db.list_conflicts(
        status=status,
        entity_type=entity_type,
        limit=limit
    )
    return {"conflicts": conflicts, "count": len(conflicts)}


@app.get("/conflicts/stats")
def get_conflict_statistics():
    """Get conflict detection statistics."""
    from . import state_db

    stats = state_db.get_conflict_stats()
    return stats


class ConflictResolutionRequest(BaseModel):
    resolution: str  # The correct value
    resolved_by: str = "user"  # 'user', 'auto', 'newer_wins'


@app.post("/conflicts/{conflict_id}/resolve")
def resolve_conflict_endpoint(conflict_id: int, req: ConflictResolutionRequest):
    """Resolve a conflict by choosing the correct value."""
    from . import state_db

    success = state_db.resolve_conflict(
        conflict_id=conflict_id,
        resolution=req.resolution,
        resolved_by=req.resolved_by
    )

    if success:
        return {"success": True, "conflict_id": conflict_id, "resolution": req.resolution}
    return {"success": False, "error": "Conflict not found"}


@app.post("/conflicts/{conflict_id}/ignore")
def ignore_conflict_endpoint(conflict_id: int):
    """Mark a conflict as ignored (not a real conflict)."""
    from . import state_db

    success = state_db.ignore_conflict(conflict_id)

    if success:
        return {"success": True, "conflict_id": conflict_id, "status": "ignored"}
    return {"success": False, "error": "Conflict not found"}


# ============ State Migration (Phase 11: SQLite/JSON → Postgres) ============

@app.post("/admin/migrate/sqlite")
def migrate_sqlite_to_postgres(
    sqlite_path: str = "/brain/index/ingest_state.db"
):
    """
    Migrate state data from SQLite to PostgreSQL.

    This migrates:
    - ingest_log → ingest_event
    - conversations
    - telegram_users

    Safe to run multiple times (uses upserts).
    """
    from . import postgres_state

    try:
        result = postgres_state.migrate_from_sqlite(sqlite_path)
        return {"status": "success", "migrated": result}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@app.post("/admin/migrate/connectors")
def migrate_connectors_to_postgres(
    state_dir: str = "/brain/system/state/connectors"
):
    """
    Migrate connector state from JSON files to PostgreSQL.

    Safe to run multiple times (uses upserts).
    """
    from . import postgres_state

    try:
        result = postgres_state.migrate_connector_json(state_dir)
        return {"status": "success", "migrated": result}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@app.post("/admin/init-schema")
def init_knowledge_schema():
    """Initialize/update knowledge database schema including all new tables."""
    from . import knowledge_db
    try:
        knowledge_db.init_schema()
        return {"status": "success", "message": "Schema initialized"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@app.get("/admin/state/postgres")
def get_postgres_state_stats():
    """Get statistics about the PostgreSQL state tables."""
    from . import postgres_state

    try:
        with postgres_state.get_cursor() as cur:
            stats = {}

            # Count records in each table
            tables = ["connector_state", "ingest_event", "conversation", "message",
                     "telegram_user", "working_state"]

            for table in tables:
                try:
                    cur.execute(f"SELECT COUNT(*) as count FROM {table}")
                    stats[table] = cur.fetchone()["count"]
                except Exception:
                    stats[table] = "table_not_found"

            # Get connectors summary
            cur.execute("""
                SELECT connector_type, COUNT(*) as count,
                       SUM(CASE WHEN consecutive_errors = 0 THEN 1 ELSE 0 END) as healthy
                FROM connector_state
                GROUP BY connector_type
            """)
            stats["connectors_by_type"] = [dict(row) for row in cur.fetchall()]

            # Get ingest summary
            cur.execute("""
                SELECT ingest_type, COUNT(*) as count,
                       COUNT(*) FILTER (WHERE status = 'success') as success,
                       COUNT(*) FILTER (WHERE status = 'error') as error
                FROM ingest_event
                GROUP BY ingest_type
            """)
            stats["ingest_by_type"] = [dict(row) for row in cur.fetchall()]

        return {"status": "success", "stats": stats}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ============ Admin: Clean Reset ============

class ResetOptions(BaseModel):
    """Options for resetting Jarvis to clean state"""
    clear_uploads: bool = True
    clear_profiles: bool = False  # Careful - deletes all person profiles!
    clear_self_model: bool = True
    clear_context_buffer: bool = True
    clear_qdrant: bool = False  # Careful - deletes all vector embeddings!
    dry_run: bool = True  # Preview what would be deleted


@app.post("/admin/reset")
def admin_reset(options: ResetOptions):
    """
    Reset Jarvis to a clean state.

    CAREFUL: This deletes data! Use dry_run=true first to preview.

    Options:
    - clear_uploads: Remove all upload queue entries and files
    - clear_profiles: Remove all person profiles (DANGEROUS)
    - clear_self_model: Reset self-model to neutral state
    - clear_context_buffer: Clear active context buffer
    - clear_qdrant: Clear all vector collections (DANGEROUS)
    - dry_run: If True, only preview what would be deleted
    """
    from . import knowledge_db, postgres_state

    results = {
        "dry_run": options.dry_run,
        "actions": []
    }

    # 1. Upload Queue
    if options.clear_uploads:
        uploads = knowledge_db.get_upload_queue(limit=1000)
        results["actions"].append({
            "target": "upload_queue",
            "count": len(uploads),
            "items": [{"id": str(u["id"]), "filename": u["filename"]} for u in uploads[:10]],
            "truncated": len(uploads) > 10
        })

        if not options.dry_run:
            with knowledge_db.get_conn() as conn:
                cur = conn.cursor()
                cur.execute("DELETE FROM upload_queue")
                # Also clean up files
                import shutil
                upload_dir = Path("/brain/uploads/incoming")
                if upload_dir.exists():
                    for subdir in upload_dir.iterdir():
                        if subdir.is_dir():
                            for f in subdir.glob("*"):
                                f.unlink()

    # 2. Person Profiles
    if options.clear_profiles:
        profiles = knowledge_db.get_all_person_profiles()
        results["actions"].append({
            "target": "person_profiles",
            "count": len(profiles),
            "items": [{"id": p["person_id"], "name": p["name"]} for p in profiles],
            "warning": "This deletes ALL person profiles!"
        })

        if not options.dry_run:
            with knowledge_db.get_conn() as conn:
                cur = conn.cursor()
                cur.execute("DELETE FROM person_profile_version")
                cur.execute("DELETE FROM person_profile")

    # 3. Self-Model
    if options.clear_self_model:
        current_model = knowledge_db.get_self_model()
        results["actions"].append({
            "target": "self_model",
            "current_strengths": current_model.get("strengths", []) if current_model else [],
            "current_weaknesses": current_model.get("weaknesses", []) if current_model else [],
            "action": "Reset to neutral state"
        })

        if not options.dry_run:
            with knowledge_db.get_conn() as conn:
                cur = conn.cursor()
                cur.execute("""
                    UPDATE jarvis_self_model SET
                        strengths = '[]'::jsonb,
                        weaknesses = '[]'::jsonb,
                        wishes = '[]'::jsonb,
                        user_patterns = '{}'::jsonb,
                        user_preferences = '{}'::jsonb,
                        current_feeling = 'Frisch initialisiert, bereit fuer echte Daten',
                        confidence_level = 0.3,
                        total_sessions = 0,
                        successful_interactions = 0,
                        frustrating_moments = 0,
                        updated_at = NOW()
                    WHERE id = 'default'
                """)

    # 4. Context Buffer
    if options.clear_context_buffer:
        buffer = postgres_state.get_active_buffer()
        stats = postgres_state.get_buffer_stats()
        results["actions"].append({
            "target": "context_buffer",
            "active_threads": len(buffer),
            "total_by_status": stats.get("by_status", {})
        })

        if not options.dry_run:
            postgres_state.clear_buffer(keep_completed=False)

    # 5. Qdrant Collections
    if options.clear_qdrant:
        try:
            from qdrant_client import QdrantClient
            import os
            qdrant_host = os.environ.get("QDRANT_HOST", "qdrant")
            qdrant_port = int(os.environ.get("QDRANT_PORT", "6333"))
            client = QdrantClient(host=qdrant_host, port=qdrant_port, timeout=10)
            collections = client.get_collections()

            results["actions"].append({
                "target": "qdrant",
                "collections": [c.name for c in collections.collections],
                "warning": "This deletes ALL vector embeddings!"
            })

            if not options.dry_run:
                for coll in collections.collections:
                    # Don't delete, just clear points
                    try:
                        client.delete(
                            collection_name=coll.name,
                            points_selector={"filter": {}}
                        )
                    except Exception:
                        pass  # Collection might be empty
        except Exception as e:
            results["actions"].append({
                "target": "qdrant",
                "error": str(e)
            })

    if options.dry_run:
        results["message"] = "DRY RUN - No changes made. Set dry_run=false to execute."
    else:
        results["message"] = "Reset completed. Jarvis is now in a clean state."

    return results


@app.get("/admin/data-inventory")
def get_data_inventory():
    """
    Get a complete inventory of all data stored in Jarvis.
    Useful for understanding what exists before reset.
    """
    from . import knowledge_db, postgres_state
    import os

    inventory = {
        "knowledge_layer": {},
        "state_layer": {},
        "vector_store": {},
        "file_system": {}
    }

    # Knowledge Layer (Postgres)
    try:
        with knowledge_db.get_conn() as conn:
            cur = conn.cursor()

            # Person profiles
            cur.execute("SELECT COUNT(*) as count FROM person_profile")
            inventory["knowledge_layer"]["person_profiles"] = cur.fetchone()["count"]

            # Profile versions
            cur.execute("SELECT COUNT(*) as count FROM person_profile_version")
            inventory["knowledge_layer"]["profile_versions"] = cur.fetchone()["count"]

            # Uploads
            cur.execute("SELECT status, COUNT(*) as count FROM upload_queue GROUP BY status")
            inventory["knowledge_layer"]["uploads"] = {row["status"]: row["count"] for row in cur.fetchall()}

            # Sync states
            cur.execute("SELECT COUNT(*) as count FROM chat_sync_state")
            inventory["knowledge_layer"]["sync_states"] = cur.fetchone()["count"]

            # Self-model
            model = knowledge_db.get_self_model()
            if model:
                inventory["knowledge_layer"]["self_model"] = {
                    "strengths_count": len(model.get("strengths", [])),
                    "weaknesses_count": len(model.get("weaknesses", [])),
                    "wishes_count": len(model.get("wishes", [])),
                    "sessions": model.get("total_sessions", 0),
                    "last_updated": str(model.get("updated_at", "never"))
                }
    except Exception as e:
        inventory["knowledge_layer"]["error"] = str(e)

    # State Layer (Postgres)
    try:
        with postgres_state.get_cursor() as cur:
            cur.execute("SELECT COUNT(*) as count FROM connector_state")
            inventory["state_layer"]["connectors"] = cur.fetchone()["count"]

            cur.execute("SELECT COUNT(*) as count FROM conversation")
            inventory["state_layer"]["conversations"] = cur.fetchone()["count"]

            cur.execute("SELECT COUNT(*) as count FROM message")
            inventory["state_layer"]["messages"] = cur.fetchone()["count"]

            cur.execute("SELECT status, COUNT(*) as count FROM active_context_buffer GROUP BY status")
            inventory["state_layer"]["context_buffer"] = {row["status"]: row["count"] for row in cur.fetchall()}
    except Exception as e:
        inventory["state_layer"]["error"] = str(e)

    # Vector Store (Qdrant)
    try:
        from qdrant_client import QdrantClient
        qdrant_host = os.environ.get("QDRANT_HOST", "qdrant")
        qdrant_port = int(os.environ.get("QDRANT_PORT", "6333"))
        client = QdrantClient(host=qdrant_host, port=qdrant_port, timeout=10)
        collections = client.get_collections()

        inventory["vector_store"]["collections"] = {}
        for coll in collections.collections:
            try:
                info = client.get_collection(coll.name)
                inventory["vector_store"]["collections"][coll.name] = {
                    "vectors_count": info.vectors_count,
                    "points_count": info.points_count
                }
            except Exception:
                inventory["vector_store"]["collections"][coll.name] = "error"
    except Exception as e:
        inventory["vector_store"]["error"] = str(e)

    # File System
    try:
        upload_dir = Path("/brain/uploads/incoming")
        if upload_dir.exists():
            file_count = 0
            for subdir in upload_dir.iterdir():
                if subdir.is_dir():
                    file_count += len(list(subdir.glob("*")))
            inventory["file_system"]["upload_files"] = file_count

        # Secrets (just count, not content)
        secrets_dir = Path("/brain/system/secrets")
        if secrets_dir.exists():
            inventory["file_system"]["secrets_files"] = len(list(secrets_dir.glob("*")))
    except Exception as e:
        inventory["file_system"]["error"] = str(e)

    return inventory


# ============ Admin: Import Configuration ============

@app.post("/admin/import/personas")
def import_personas(file_path: str = "/brain/system/prompts/persona_profiles.json"):
    """
    Import personas from JSON file into database.
    File format: {"personas": [...]}
    """
    from . import knowledge_db

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        personas = data.get("personas", [])
        imported = []
        errors = []

        for p in personas:
            try:
                result = knowledge_db.upsert_persona(
                    persona_id=p.get("id"),
                    name=p.get("name"),
                    intent=p.get("intent"),
                    tone=p.get("tone"),
                    format_config=p.get("format"),
                    requirements=p.get("requirements"),
                    forbidden=p.get("forbidden"),
                    example=p.get("one_liner_example")
                )
                if result:
                    imported.append(p.get("id"))
            except Exception as e:
                errors.append({"id": p.get("id"), "error": str(e)})

        return {
            "status": "success",
            "imported": imported,
            "count": len(imported),
            "errors": errors,
            "source_file": file_path
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


@app.post("/admin/import/modes")
def import_modes(file_path: str = "/brain/system/prompts/modes.json"):
    """
    Import modes from JSON file into database.
    File format: {"modes": {...}}
    """
    from . import knowledge_db

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        modes = data.get("modes", {})
        default_mode = data.get("default_mode", "analyst")
        imported = []
        errors = []

        for mode_id, m in modes.items():
            try:
                result = knowledge_db.upsert_mode(
                    mode_id=mode_id,
                    name=m.get("name"),
                    purpose=m.get("purpose"),
                    output_contract=m.get("output_contract"),
                    tone=m.get("tone"),
                    forbidden=m.get("forbidden"),
                    citation_style=m.get("citation_style"),
                    unknown_response=m.get("unknown_response"),
                    is_default=(mode_id == default_mode)
                )
                if result:
                    imported.append(mode_id)
            except Exception as e:
                errors.append({"id": mode_id, "error": str(e)})

        return {
            "status": "success",
            "imported": imported,
            "count": len(imported),
            "default_mode": default_mode,
            "errors": errors,
            "source_file": file_path
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


@app.get("/admin/capabilities")
def get_capabilities():
    """
    Get current Jarvis capabilities (tools, features, version).
    Used for self-introspection and dynamic capability discovery.
    """
    try:
        from pathlib import Path
        import json
        
        # Try to load CAPABILITIES.json
        cap_file = Path("/brain/system/docs/CAPABILITIES.json")
        if cap_file.exists():
            with open(cap_file, "r") as f:
                capabilities = json.load(f)
                capabilities["source"] = "capabilities_json"
                return capabilities
        
        # Fallback: Generate runtime capabilities
        from . import tools
        from . import config
        
        tool_names = [name for name in dir(tools) if name.startswith("tool_")]
        
        return {
            "version": config.VERSION,
            "build_timestamp": config.BUILD_TIMESTAMP,
            "tools": [{"name": name, "status": "active"} for name in tool_names],
            "features": {
                "session_memory": {"enabled": True, "ttl_days": 30},
                "cross_session_learning": {"enabled": True},
                "proactive_hints": {"enabled": config.PROACTIVE_LEVEL > 1}
            },
            "source": "runtime_fallback"
        }
    except Exception as e:
        return {"error": str(e), "version": "unknown"}


@app.post("/admin/refresh")
def refresh_capabilities():
    """
    Refresh capabilities cache (post-deploy hook).
    Triggers reload of CAPABILITIES.json and clears any cached state.
    """
    try:
        from pathlib import Path
        import json
        
        cap_file = Path("/brain/system/docs/CAPABILITIES.json")
        
        if cap_file.exists():
            # Validate JSON
            with open(cap_file, "r") as f:
                capabilities = json.load(f)
            
            log_with_context(logger, "info", "Capabilities refreshed",
                           version=capabilities.get("version"),
                           tools_count=len(capabilities.get("tools", [])))
            
            return {
                "status": "success",
                "version": capabilities.get("version"),
                "tools_count": len(capabilities.get("tools", [])),
                "timestamp": capabilities.get("build_timestamp")
            }
        else:
            return {
                "status": "warning",
                "message": "CAPABILITIES.json not found, using runtime fallback"
            }
    except Exception as e:
        log_with_context(logger, "error", "Failed to refresh capabilities", error=str(e))
        return {"status": "error", "error": str(e)}


@app.post("/admin/import/policies")
def import_policies(policy_dir: str = "/brain/system/policies"):
    """
    Import policies from markdown files into database.
    Each .md file becomes a policy.
    """
    from . import knowledge_db
    import re

    try:
        policy_path = Path(policy_dir)
        if not policy_path.exists():
            return {"status": "error", "error": f"Directory not found: {policy_dir}"}

        imported = []
        errors = []

        # Priority mapping based on filename
        priority_map = {
            "JARVIS_SYSTEM_PROMPT": 1000,
            "JARVIS_SELF": 900,
            "GOVERNANCE": 800,
            "COACH_OS": 700,
            "TASK_SYSTEM": 600
        }

        # Category mapping based on filename
        category_map = {
            "JARVIS_SYSTEM_PROMPT": "system",
            "JARVIS_SELF": "self",
            "GOVERNANCE": "governance",
            "COACH_OS": "coaching",
            "TASK_SYSTEM": "tasks"
        }

        for md_file in policy_path.glob("*.md"):
            try:
                policy_id = md_file.stem.lower().replace("_", "-")
                name = md_file.stem.replace("_", " ").title()

                with open(md_file, "r", encoding="utf-8") as f:
                    content = f.read()

                # Get priority and category from mapping
                base_name = md_file.stem
                priority = priority_map.get(base_name, 100)
                category = category_map.get(base_name, "general")

                result = knowledge_db.upsert_policy(
                    policy_id=policy_id,
                    name=name,
                    content=content,
                    category=category,
                    priority=priority,
                    inject_in_prompt=True
                )
                if result:
                    imported.append(policy_id)
            except Exception as e:
                errors.append({"file": str(md_file), "error": str(e)})

        return {
            "status": "success",
            "imported": imported,
            "count": len(imported),
            "errors": errors,
            "source_dir": policy_dir
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ============ CRUD Endpoints for Personas/Modes/Policies ============

@app.get("/personas")
def list_personas(active_only: bool = True):
    """List all personas."""
    from . import knowledge_db
    personas = knowledge_db.get_all_personas(active_only=active_only)
    return {"personas": personas, "count": len(personas)}


@app.get("/personas/{persona_id}")
def get_persona(persona_id: str):
    """Get a single persona."""
    from . import knowledge_db
    persona = knowledge_db.get_persona(persona_id)
    if not persona:
        return {"error": "Persona not found"}
    return {"persona": persona}


@app.get("/modes")
def list_modes(active_only: bool = True):
    """List all modes."""
    from . import knowledge_db
    modes = knowledge_db.get_all_modes(active_only=active_only)
    return {"modes": modes, "count": len(modes)}


@app.get("/modes/{mode_id}")
def get_mode(mode_id: str):
    """Get a single mode."""
    from . import knowledge_db
    mode = knowledge_db.get_mode(mode_id)
    if not mode:
        return {"error": "Mode not found"}
    return {"mode": mode}


@app.get("/policies")
def list_policies(category: str = None, active_only: bool = True):
    """List all policies, optionally filtered by category."""
    from . import knowledge_db
    policies = knowledge_db.get_all_policies(category=category, active_only=active_only)
    return {"policies": policies, "count": len(policies)}


@app.get("/policies/{policy_id}")
def get_policy_by_id(policy_id: str):
    """Get a single policy."""
    from . import knowledge_db
    policy = knowledge_db.get_policy(policy_id)
    if not policy:
        return {"error": "Policy not found"}
    return {"policy": policy}


# ============ User Profile (Micha) ============

@app.get("/user/profile")
def get_user_profile_endpoint(profile_id: str = "micha"):
    """
    Get the comprehensive user profile.
    Much richer than external person profiles.
    """
    from . import knowledge_db
    profile = knowledge_db.get_jarvis_user_profile(profile_id)
    if not profile:
        profile = knowledge_db.ensure_user_profile(profile_id)
    return {"profile": profile}


@app.get("/user/profile/for-prompt")
def get_user_profile_for_prompt_endpoint(profile_id: str = "micha"):
    """Get user profile formatted for prompt injection."""
    from . import knowledge_db
    prompt_text = knowledge_db.get_user_profile_for_prompt(profile_id)
    return {"prompt_injection": prompt_text, "length": len(prompt_text)}


class UpdateUserProfileRequest(BaseModel):
    """Request for updating user profile"""
    display_name: str | None = None
    roles: List[str] | None = None
    communication_prefs: dict | None = None
    work_prefs: dict | None = None
    adhd_patterns: dict | None = None
    boundaries: dict | None = None
    what_works: List[str] | None = None
    what_fails: List[str] | None = None


@app.post("/user/profile")
def update_user_profile_endpoint(req: UpdateUserProfileRequest, profile_id: str = "micha"):
    """
    Update user profile fields.
    JSONB fields are merged with existing data.
    """
    from . import knowledge_db

    result = knowledge_db.update_user_profile(
        profile_id=profile_id,
        display_name=req.display_name,
        roles=req.roles,
        communication_prefs=req.communication_prefs,
        work_prefs=req.work_prefs,
        adhd_patterns=req.adhd_patterns,
        boundaries=req.boundaries,
        what_works=req.what_works,
        what_fails=req.what_fails
    )

    if not result:
        return {"status": "error", "message": "Failed to update profile"}
    return {"status": "updated", "profile": result}


class AddGoalRequest(BaseModel):
    """Request for adding a goal"""
    title: str
    priority: int = 3
    deadline: str | None = None
    namespace: str | None = None
    goal_type: str = "current"  # "current" or "long_term"


@app.post("/user/goals")
def add_user_goal_endpoint(req: AddGoalRequest, profile_id: str = "micha"):
    """Add a goal to the user profile."""
    from . import knowledge_db

    goal = knowledge_db.add_user_goal(
        title=req.title,
        priority=req.priority,
        deadline=req.deadline,
        namespace=req.namespace,
        goal_type=req.goal_type,
        profile_id=profile_id
    )
    return {"status": "added", "goal": goal}


@app.post("/user/goals/{goal_id}/complete")
def complete_user_goal_endpoint(goal_id: str, profile_id: str = "micha"):
    """Mark a goal as completed."""
    from . import knowledge_db

    success = knowledge_db.complete_user_goal(goal_id, profile_id)
    if success:
        return {"status": "completed", "goal_id": goal_id}
    return {"status": "error", "message": "Goal not found or already completed"}


@app.get("/user/goals")
def list_user_goals(profile_id: str = "micha"):
    """List current user goals."""
    from . import knowledge_db

    profile = knowledge_db.get_jarvis_user_profile(profile_id)
    if not profile:
        return {"current_goals": [], "long_term_goals": []}

    return {
        "current_goals": profile.get("current_goals", []),
        "long_term_goals": profile.get("long_term_goals", [])
    }


@app.post("/user/profile/snapshot")
def create_user_snapshot(profile_id: str = "micha", reason: str = "manual"):
    """Create a snapshot of the current user profile."""
    from . import knowledge_db

    snapshot_id = knowledge_db.create_user_profile_snapshot(profile_id, reason)
    if snapshot_id:
        return {"status": "created", "snapshot_id": snapshot_id}
    return {"status": "error", "message": "Failed to create snapshot"}


# ============ Timeline Views (P3: History per topic/person/project) ============

@app.get("/timeline/person/{person_id}")
def get_person_timeline(
    person_id: str,
    days: int = 90,
    limit: int = 50,
    include_messages: bool = True
):
    """
    Get timeline of events related to a person.

    Returns chronological list of:
    - Profile version changes
    - Knowledge items about the person
    - Message mentions (from Qdrant)
    - Decision references
    """
    from datetime import datetime, timedelta
    from . import knowledge_db, session_manager
    from .hybrid_search import hybrid_search

    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    events = []

    # 1. Profile version history
    try:
        with knowledge_db.get_conn() as conn:
            cur = conn.cursor()

            # Get profile versions
            cur.execute("""
                SELECT pv.version_number, pv.content, pv.changed_by, pv.change_reason,
                       pv.change_type, pv.status, pv.created_at
                FROM person_profile_version pv
                JOIN person_profile p ON p.id = pv.profile_id
                WHERE p.person_id = %s AND pv.created_at > %s
                ORDER BY pv.created_at DESC
                LIMIT %s
            """, (person_id, cutoff, limit))

            for row in cur.fetchall():
                events.append({
                    "type": "profile_change",
                    "timestamp": row["created_at"].isoformat() if row["created_at"] else None,
                    "version": row["version_number"],
                    "change_type": row["change_type"],
                    "changed_by": row["changed_by"],
                    "reason": row["change_reason"],
                    "status": row["status"],
                    "content_preview": str(row["content"])[:200] if row["content"] else None
                })

            # 2. Knowledge items about this person
            cur.execute("""
                SELECT ki.id, ki.item_type, ki.status, ki.relevance_score,
                       kiv.content, kiv.confidence, kiv.created_at, kiv.created_by
                FROM knowledge_item ki
                JOIN knowledge_item_version kiv ON kiv.id = ki.current_version_id
                WHERE ki.subject_type = 'person' AND ki.subject_id = %s
                  AND kiv.created_at > %s
                ORDER BY kiv.created_at DESC
                LIMIT %s
            """, (person_id, cutoff, limit))

            for row in cur.fetchall():
                events.append({
                    "type": "knowledge_update",
                    "timestamp": row["created_at"].isoformat() if row["created_at"] else None,
                    "item_id": row["id"],
                    "item_type": row["item_type"],
                    "confidence": row["confidence"],
                    "created_by": row["created_by"],
                    "relevance": row["relevance_score"],
                    "content_preview": str(row["content"])[:200] if row["content"] else None
                })

            # 3. Decision references
            cur.execute("""
                SELECT id, title, decision_type, outcome, created_at
                FROM decision_log
                WHERE context::text ILIKE %s AND created_at > %s
                ORDER BY created_at DESC
                LIMIT %s
            """, (f'%{person_id}%', cutoff, limit // 2))

            for row in cur.fetchall():
                events.append({
                    "type": "decision",
                    "timestamp": row["created_at"].isoformat() if row["created_at"] else None,
                    "decision_id": row["id"],
                    "title": row["title"],
                    "decision_type": row["decision_type"],
                    "outcome": row["outcome"]
                })

    except Exception as e:
        log_with_context(logger, "error", "Timeline person DB error", error=str(e))

    # 4. Message mentions from Qdrant (if requested)
    if include_messages:
        try:
            # Search for messages mentioning this person
            search_results = hybrid_search(
                query=person_id.replace("_", " "),
                namespace="private",
                limit=limit // 2,
                score_threshold=0.3
            )
            for result in search_results.get("results", []):
                events.append({
                    "type": "message_mention",
                    "timestamp": result.get("event_ts_start") or result.get("event_ts"),
                    "channel": result.get("channel"),
                    "text_preview": result.get("text", "")[:150],
                    "score": result.get("score")
                })
        except Exception as e:
            log_with_context(logger, "warning", "Timeline person search error", error=str(e))

    # Sort by timestamp (newest first)
    events.sort(key=lambda x: x.get("timestamp") or "", reverse=True)

    return {
        "person_id": person_id,
        "days": days,
        "event_count": len(events),
        "events": events[:limit]
    }


@app.get("/timeline/topic/{topic}")
def get_topic_timeline(
    topic: str,
    days: int = 90,
    limit: int = 50,
    include_messages: bool = True,
    namespace: str = None
):
    """
    Get timeline of events related to a topic.

    Returns chronological list of:
    - Topic mentions from sessions
    - Knowledge items tagged with topic
    - Message mentions (from Qdrant)
    """
    from datetime import datetime, timedelta
    from . import session_manager
    from .hybrid_search import hybrid_search

    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    events = []
    topic_lower = topic.lower()

    # 1. Topic mentions from session_manager (SQLite)
    try:
        conn = session_manager._get_conn()
        cursor = conn.execute("""
            SELECT session_id, user_id, mention_count, first_mentioned, last_mentioned, context_snippet
            FROM topic_mentions
            WHERE LOWER(topic) = ? AND last_mentioned > ?
            ORDER BY last_mentioned DESC
            LIMIT ?
        """, (topic_lower, cutoff, limit))

        for row in cursor.fetchall():
            events.append({
                "type": "topic_mention",
                "timestamp": row["last_mentioned"],
                "session_id": row["session_id"],
                "mention_count": row["mention_count"],
                "first_seen": row["first_mentioned"],
                "context": row["context_snippet"]
            })
        conn.close()
    except Exception as e:
        log_with_context(logger, "warning", "Timeline topic mentions error", error=str(e))

    # 2. Knowledge items mentioning this topic
    try:
        from . import knowledge_db
        with knowledge_db.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT ki.id, ki.item_type, ki.subject_type, ki.subject_id,
                       kiv.content, kiv.confidence, kiv.created_at
                FROM knowledge_item ki
                JOIN knowledge_item_version kiv ON kiv.id = ki.current_version_id
                WHERE kiv.content::text ILIKE %s
                  AND kiv.created_at > %s
                  AND ki.status = 'active'
                ORDER BY kiv.created_at DESC
                LIMIT %s
            """, (f'%{topic}%', cutoff, limit))

            for row in cur.fetchall():
                events.append({
                    "type": "knowledge_item",
                    "timestamp": row["created_at"].isoformat() if row["created_at"] else None,
                    "item_id": row["id"],
                    "item_type": row["item_type"],
                    "subject": f"{row['subject_type']}:{row['subject_id']}" if row["subject_id"] else None,
                    "confidence": row["confidence"],
                    "content_preview": str(row["content"])[:200] if row["content"] else None
                })
    except Exception as e:
        log_with_context(logger, "warning", "Timeline topic knowledge error", error=str(e))

    # 3. Message mentions from Qdrant
    if include_messages:
        try:
            ns = namespace or "private"
            search_results = hybrid_search(
                query=topic,
                namespace=ns,
                limit=limit // 2,
                score_threshold=0.3
            )
            for result in search_results.get("results", []):
                events.append({
                    "type": "message",
                    "timestamp": result.get("event_ts_start") or result.get("event_ts"),
                    "channel": result.get("channel"),
                    "namespace": ns,
                    "text_preview": result.get("text", "")[:150],
                    "score": result.get("score")
                })
        except Exception as e:
            log_with_context(logger, "warning", "Timeline topic search error", error=str(e))

    # Sort by timestamp
    events.sort(key=lambda x: x.get("timestamp") or "", reverse=True)

    return {
        "topic": topic,
        "days": days,
        "event_count": len(events),
        "events": events[:limit]
    }


@app.get("/timeline/project/{project_id}")
def get_project_timeline(
    project_id: str,
    days: int = 90,
    limit: int = 50,
    include_messages: bool = True
):
    """
    Get timeline of events related to a project.

    Returns chronological list of:
    - Task updates
    - Knowledge items about the project
    - Decision references
    - Message mentions
    """
    from datetime import datetime, timedelta
    from . import knowledge_db
    from .hybrid_search import hybrid_search

    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    events = []

    try:
        with knowledge_db.get_conn() as conn:
            cur = conn.cursor()

            # 1. Tasks for this project
            cur.execute("""
                SELECT t.id, t.title, t.status, t.priority, t.created_at, t.updated_at,
                       t.completed_at
                FROM tasks t
                JOIN projects p ON p.id = t.project_id
                WHERE p.project_id = %s AND t.updated_at > %s
                ORDER BY t.updated_at DESC
                LIMIT %s
            """, (project_id, cutoff, limit))

            for row in cur.fetchall():
                events.append({
                    "type": "task",
                    "timestamp": (row["updated_at"] or row["created_at"]).isoformat() if row["updated_at"] or row["created_at"] else None,
                    "task_id": row["id"],
                    "title": row["title"],
                    "status": row["status"],
                    "priority": row["priority"],
                    "completed": row["completed_at"].isoformat() if row["completed_at"] else None
                })

            # 2. Knowledge items about project
            cur.execute("""
                SELECT ki.id, ki.item_type, kiv.content, kiv.confidence, kiv.created_at
                FROM knowledge_item ki
                JOIN knowledge_item_version kiv ON kiv.id = ki.current_version_id
                WHERE ki.subject_type = 'project' AND ki.subject_id = %s
                  AND kiv.created_at > %s
                ORDER BY kiv.created_at DESC
                LIMIT %s
            """, (project_id, cutoff, limit // 2))

            for row in cur.fetchall():
                events.append({
                    "type": "knowledge",
                    "timestamp": row["created_at"].isoformat() if row["created_at"] else None,
                    "item_id": row["id"],
                    "item_type": row["item_type"],
                    "confidence": row["confidence"],
                    "content_preview": str(row["content"])[:200] if row["content"] else None
                })

            # 3. Decisions referencing project
            cur.execute("""
                SELECT id, title, decision_type, outcome, created_at
                FROM decision_log
                WHERE context::text ILIKE %s AND created_at > %s
                ORDER BY created_at DESC
                LIMIT %s
            """, (f'%{project_id}%', cutoff, limit // 2))

            for row in cur.fetchall():
                events.append({
                    "type": "decision",
                    "timestamp": row["created_at"].isoformat() if row["created_at"] else None,
                    "decision_id": row["id"],
                    "title": row["title"],
                    "decision_type": row["decision_type"],
                    "outcome": row["outcome"]
                })

    except Exception as e:
        log_with_context(logger, "error", "Timeline project DB error", error=str(e))

    # 4. Messages mentioning project
    if include_messages:
        try:
            search_results = hybrid_search(
                query=project_id.replace("_", " "),
                namespace="work_projektil",
                limit=limit // 2,
                score_threshold=0.3
            )
            for result in search_results.get("results", []):
                events.append({
                    "type": "message",
                    "timestamp": result.get("event_ts_start") or result.get("event_ts"),
                    "channel": result.get("channel"),
                    "text_preview": result.get("text", "")[:150],
                    "score": result.get("score")
                })
        except Exception as e:
            log_with_context(logger, "warning", "Timeline project search error", error=str(e))

    events.sort(key=lambda x: x.get("timestamp") or "", reverse=True)

    return {
        "project_id": project_id,
        "days": days,
        "event_count": len(events),
        "events": events[:limit]
    }


@app.get("/timeline/overview")
def get_timeline_overview(days: int = 30, limit: int = 100):
    """
    Get a unified timeline overview of all recent activity.

    Aggregates recent events across all entity types for a global view.
    """
    from datetime import datetime, timedelta
    from . import knowledge_db

    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    events = []

    try:
        with knowledge_db.get_conn() as conn:
            cur = conn.cursor()

            # Recent knowledge updates
            cur.execute("""
                SELECT ki.id, ki.item_type, ki.subject_type, ki.subject_id,
                       kiv.created_at, kiv.created_by, kiv.confidence
                FROM knowledge_item ki
                JOIN knowledge_item_version kiv ON kiv.id = ki.current_version_id
                WHERE kiv.created_at > %s AND ki.status = 'active'
                ORDER BY kiv.created_at DESC
                LIMIT %s
            """, (cutoff, limit // 3))

            for row in cur.fetchall():
                events.append({
                    "type": "knowledge",
                    "timestamp": row["created_at"].isoformat() if row["created_at"] else None,
                    "item_type": row["item_type"],
                    "subject": f"{row['subject_type']}:{row['subject_id']}" if row["subject_id"] else None,
                    "created_by": row["created_by"]
                })

            # Recent profile changes
            cur.execute("""
                SELECT p.person_id, p.name, pv.version_number, pv.change_type,
                       pv.changed_by, pv.created_at
                FROM person_profile_version pv
                JOIN person_profile p ON p.id = pv.profile_id
                WHERE pv.created_at > %s
                ORDER BY pv.created_at DESC
                LIMIT %s
            """, (cutoff, limit // 3))

            for row in cur.fetchall():
                events.append({
                    "type": "profile",
                    "timestamp": row["created_at"].isoformat() if row["created_at"] else None,
                    "person_id": row["person_id"],
                    "name": row["name"],
                    "change_type": row["change_type"],
                    "changed_by": row["changed_by"]
                })

            # Recent decisions
            cur.execute("""
                SELECT id, title, decision_type, outcome, created_at
                FROM decision_log
                WHERE created_at > %s
                ORDER BY created_at DESC
                LIMIT %s
            """, (cutoff, limit // 3))

            for row in cur.fetchall():
                events.append({
                    "type": "decision",
                    "timestamp": row["created_at"].isoformat() if row["created_at"] else None,
                    "decision_id": row["id"],
                    "title": row["title"],
                    "outcome": row["outcome"]
                })

    except Exception as e:
        log_with_context(logger, "error", "Timeline overview error", error=str(e))

    events.sort(key=lambda x: x.get("timestamp") or "", reverse=True)

    return {
        "days": days,
        "event_count": len(events),
        "events": events[:limit]
    }


# ============ Prompt Blueprints (P3: Versioned Templates with A/B Testing) ============

class BlueprintCreate(BaseModel):
    blueprint_id: str
    name: str
    use_case: str  # briefing, email, decision, coaching, analysis
    template: str
    description: Optional[str] = None
    variables_schema: Optional[List[Dict]] = None
    is_default: bool = False


class BlueprintUpdate(BaseModel):
    template: Optional[str] = None
    variables_schema: Optional[List[Dict]] = None
    change_reason: Optional[str] = None


class BlueprintRender(BaseModel):
    variables: Dict[str, Any]


@app.post("/blueprints")
def create_blueprint(req: BlueprintCreate):
    """
    Create a new prompt blueprint.

    Blueprints are versioned prompt templates for specific use cases.

    Example:
    ```json
    {
        "blueprint_id": "morning_briefing_v1",
        "name": "Morning Briefing",
        "use_case": "briefing",
        "template": "Guten Morgen {{user_name}}!\\n\\n## Kalender\\n{{calendar_events}}\\n\\n## Prioritaeten\\n{{priorities}}",
        "variables_schema": [
            {"name": "user_name", "type": "string", "required": true, "default": "Micha"},
            {"name": "calendar_events", "type": "string", "required": true},
            {"name": "priorities", "type": "string", "required": false, "default": "Keine expliziten Prioritaeten"}
        ],
        "is_default": true
    }
    ```
    """
    from . import knowledge_db

    result = knowledge_db.create_blueprint(
        blueprint_id=req.blueprint_id,
        name=req.name,
        use_case=req.use_case,
        template=req.template,
        description=req.description,
        variables_schema=req.variables_schema,
        is_default=req.is_default,
        created_by="api"
    )

    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("error"))

    return result


@app.get("/blueprints")
def list_blueprints(use_case: str = None, status: str = "active"):
    """
    List all blueprints.

    Query params:
    - use_case: Filter by use case (briefing, email, decision, coaching, analysis)
    - status: Filter by status (draft, active, deprecated, archived)
    """
    from . import knowledge_db
    return knowledge_db.list_blueprints(use_case=use_case, status=status)


@app.get("/blueprints/{blueprint_id}")
def get_blueprint(blueprint_id: str):
    """Get a specific blueprint by ID."""
    from . import knowledge_db

    blueprint = knowledge_db.get_blueprint(blueprint_id=blueprint_id)
    if not blueprint:
        raise HTTPException(status_code=404, detail="Blueprint not found")
    return blueprint


@app.get("/blueprints/default/{use_case}")
def get_default_blueprint(use_case: str):
    """Get the default blueprint for a use case."""
    from . import knowledge_db

    blueprint = knowledge_db.get_blueprint(use_case=use_case, get_default=True)
    if not blueprint:
        raise HTTPException(status_code=404, detail=f"No default blueprint for use_case: {use_case}")
    return blueprint


@app.put("/blueprints/{blueprint_id}")
def update_blueprint(blueprint_id: str, req: BlueprintUpdate):
    """
    Update a blueprint (creates a new version).

    Only provided fields will be updated.
    """
    from . import knowledge_db

    result = knowledge_db.update_blueprint(
        blueprint_id=blueprint_id,
        template=req.template,
        variables_schema=req.variables_schema,
        change_reason=req.change_reason,
        changed_by="api"
    )

    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("error"))

    return result


@app.get("/blueprints/{blueprint_id}/versions")
def get_blueprint_versions(blueprint_id: str, limit: int = 10):
    """Get version history for a blueprint."""
    from . import knowledge_db
    return knowledge_db.get_blueprint_versions(blueprint_id, limit=limit)


@app.post("/blueprints/{blueprint_id}/render")
def render_blueprint(blueprint_id: str, req: BlueprintRender):
    """
    Render a blueprint template with provided variables.

    Returns the fully rendered prompt string.

    Example:
    ```json
    {
        "variables": {
            "user_name": "Micha",
            "calendar_events": "09:00 Standup\\n14:00 Client Call",
            "priorities": "1. Deploy v2.0\\n2. Review PR"
        }
    }
    ```
    """
    from . import knowledge_db

    result = knowledge_db.render_blueprint(blueprint_id, req.variables)
    if result is None:
        raise HTTPException(status_code=404, detail="Blueprint not found or render failed")

    # Log usage
    knowledge_db.log_blueprint_usage(
        blueprint_id=blueprint_id,
        variables_provided=req.variables
    )

    return {"rendered": result}


# ============ A/B Testing for Blueprints ============

class ABTestCreate(BaseModel):
    test_id: str
    name: str
    blueprint_id: str
    variant_a_version: int
    variant_b_version: int
    success_metric: str = "user_rating"  # user_rating, task_completion, response_quality
    description: Optional[str] = None
    traffic_split: float = 0.5  # Percentage to variant B
    min_samples: int = 30
    confidence_threshold: float = 0.95


class ABTestResult(BaseModel):
    quality_score: Optional[float] = None
    task_completed: Optional[bool] = None
    tokens_used: Optional[int] = None
    response_time_ms: Optional[int] = None
    feedback_type: Optional[str] = None  # thumbs_up, thumbs_down, explicit_rating
    feedback_text: Optional[str] = None
    conversation_id: Optional[str] = None
    message_id: Optional[str] = None


@app.post("/ab-tests")
def create_ab_test(req: ABTestCreate):
    """
    Create a new A/B test for a blueprint.

    Tests two versions of a blueprint against each other.
    Users are deterministically assigned to variants based on their ID.

    Example:
    ```json
    {
        "test_id": "briefing_tone_test_2026",
        "name": "Morning Briefing Tone Test",
        "blueprint_id": "morning_briefing_v1",
        "variant_a_version": 1,
        "variant_b_version": 2,
        "success_metric": "user_rating",
        "traffic_split": 0.5,
        "min_samples": 30
    }
    ```
    """
    from . import knowledge_db

    result = knowledge_db.create_ab_test(
        test_id=req.test_id,
        name=req.name,
        blueprint_id=req.blueprint_id,
        variant_a_version=req.variant_a_version,
        variant_b_version=req.variant_b_version,
        success_metric=req.success_metric,
        description=req.description,
        traffic_split=req.traffic_split,
        min_samples=req.min_samples,
        confidence_threshold=req.confidence_threshold,
        created_by="api"
    )

    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("error"))

    return result


@app.get("/ab-tests")
def list_ab_tests(status: str = None, blueprint_id: str = None):
    """
    List A/B tests.

    Query params:
    - status: Filter by status (draft, running, paused, completed, cancelled)
    - blueprint_id: Filter by blueprint
    """
    from . import knowledge_db
    return knowledge_db.list_ab_tests(status=status, blueprint_id=blueprint_id)


@app.get("/ab-tests/{test_id}")
def get_ab_test(test_id: str):
    """Get A/B test details and statistics."""
    from . import knowledge_db

    stats = knowledge_db.get_ab_test_stats(test_id)
    if stats.get("status") == "error":
        raise HTTPException(status_code=404, detail=stats.get("error"))
    return stats


@app.post("/ab-tests/{test_id}/start")
def start_ab_test(test_id: str):
    """Start an A/B test (change status from draft to running)."""
    from . import knowledge_db

    result = knowledge_db.start_ab_test(test_id)
    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@app.get("/ab-tests/{test_id}/variant/{user_id}")
def get_ab_test_variant(test_id: str, user_id: str):
    """
    Get the variant assignment for a user.

    Returns which variant (A or B) the user should see.
    Assignment is deterministic based on user_id hash.
    """
    from . import knowledge_db

    variant = knowledge_db.get_ab_test_variant(test_id, user_id)
    if variant is None:
        raise HTTPException(status_code=404, detail="Test not found or not running")
    return {"test_id": test_id, "user_id": user_id, "variant": variant}


@app.post("/ab-tests/{test_id}/result/{user_id}")
def record_ab_test_result(test_id: str, user_id: str, req: ABTestResult):
    """
    Record a result for an A/B test interaction.

    Call this after using a blueprint to record outcome metrics.

    Example:
    ```json
    {
        "quality_score": 0.8,
        "task_completed": true,
        "feedback_type": "thumbs_up"
    }
    ```
    """
    from . import knowledge_db

    success = knowledge_db.record_ab_result(
        test_id=test_id,
        user_id=user_id,
        quality_score=req.quality_score,
        task_completed=req.task_completed,
        tokens_used=req.tokens_used,
        response_time_ms=req.response_time_ms,
        feedback_type=req.feedback_type,
        feedback_text=req.feedback_text,
        conversation_id=req.conversation_id,
        message_id=req.message_id
    )

    if not success:
        raise HTTPException(status_code=400, detail="Failed to record result")
    return {"status": "recorded"}


@app.post("/ab-tests/{test_id}/complete")
def complete_ab_test(test_id: str, winner: str = None, notes: str = None):
    """
    Complete an A/B test and declare a winner.

    If winner is not provided, it will be determined automatically
    based on statistical significance.

    Query params:
    - winner: Force winner (A or B), or omit for automatic determination
    - notes: Conclusion notes
    """
    from . import knowledge_db

    result = knowledge_db.complete_ab_test(test_id, winner=winner, notes=notes)
    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@app.get("/ab-tests/{test_id}/stats")
def get_ab_test_stats(test_id: str):
    """Get detailed statistics for an A/B test."""
    from . import knowledge_db

    stats = knowledge_db.get_ab_test_stats(test_id)
    if stats.get("status") == "error":
        raise HTTPException(status_code=404, detail=stats.get("error"))
    return stats


# ============ Message Normalization (Unified Schema) ============

class NormalizeRequest(BaseModel):
    messages: List[Dict]
    channel: Optional[str] = None
    channel_id: Optional[str] = None


@app.post("/normalize/messages")
def normalize_messages_endpoint(req: NormalizeRequest):
    """
    Normalize messages from any channel to unified schema.

    Accepts raw messages from WhatsApp, Google Chat, Email, or Telegram
    and returns normalized messages with consistent fields.

    Example:
    ```json
    {
        "messages": [
            {"channel": "whatsapp", "sender": "Peter", "text": "Hallo!", "event_ts": "2026-01-31T10:00:00"}
        ],
        "channel": "whatsapp"
    }
    ```

    Returns list of normalized messages with:
    - Unique ID
    - Normalized text for search
    - Language detection
    - Word/char counts
    - Sender/recipient extraction
    """
    from .message_normalizer import normalize_messages

    normalized = normalize_messages(
        req.messages,
        channel=req.channel,
        channel_id=req.channel_id or ""
    )

    return {
        "count": len(normalized),
        "messages": [m.to_dict() for m in normalized]
    }


@app.post("/normalize/single")
def normalize_single_message(msg: Dict, channel: str = None):
    """
    Normalize a single message.

    Useful for real-time normalization of incoming messages.
    """
    from .message_normalizer import normalize_message

    normalized = normalize_message(msg, channel=channel)
    return normalized.to_dict()


@app.post("/normalize/stats")
def get_normalized_stats(req: NormalizeRequest):
    """
    Get statistics for a batch of messages.

    Returns:
    - Total count, words, chars
    - Breakdown by channel
    - Breakdown by language
    - Top senders
    """
    from .message_normalizer import normalize_messages, get_message_stats

    normalized = normalize_messages(
        req.messages,
        channel=req.channel,
        channel_id=req.channel_id or ""
    )

    stats = get_message_stats(normalized)
    return stats


@app.get("/normalize/schema")
def get_normalization_schema():
    """
    Get the unified message schema documentation.

    Returns field descriptions for the normalized message format.
    """
    return {
        "schema": {
            "id": "Unique message ID (channel + hash)",
            "channel": "Source channel (whatsapp, google_chat, email, telegram)",
            "channel_id": "Conversation/thread ID",
            "event_ts": "ISO timestamp of message",
            "ingest_ts": "When ingested into system",
            "sender_id": "Normalized person_id (if linked)",
            "sender_name": "Display name",
            "sender_raw": "Original sender string",
            "recipient_id": "For email: normalized person_id",
            "recipient_name": "For email: display name",
            "recipient_raw": "For email: original recipient string",
            "subject": "For email: subject line",
            "text": "Message content",
            "text_normalized": "Cleaned/normalized text for search",
            "language": "Detected language (de, en)",
            "word_count": "Word count",
            "char_count": "Character count",
            "metadata": "Channel-specific metadata",
            "source_path": "Original file path"
        },
        "channels": ["whatsapp", "google_chat", "email", "telegram"],
        "languages": ["de", "en"],
        "normalization_rules": [
            "Lowercase text",
            "Collapse whitespace",
            "Replace URLs with [link:domain]",
            "Keep alphanumeric, German umlauts, basic punctuation"
        ]
    }


@app.post("/normalize/detect-language")
def detect_language_endpoint(text: str):
    """
    Detect language of a text snippet.

    Returns 'de' for German or 'en' for English based on common word patterns.
    """
    from .message_normalizer import _detect_language

    language = _detect_language(text)
    return {"text_preview": text[:100], "language": language}


@app.post("/normalize/search")
def search_normalized_endpoint(
    messages: List[Dict],
    query: str,
    channel: str = None,
    sender: str = None,
    language: str = None,
    limit: int = 50
):
    """
    Search over normalized messages (in-memory).

    For production, use Qdrant/Meilisearch instead.
    This is for quick filtering of small message batches.
    """
    from .message_normalizer import normalize_messages, search_normalized

    normalized = normalize_messages(messages)
    results = search_normalized(
        normalized,
        query=query,
        channel=channel,
        sender=sender,
        language=language,
        limit=limit
    )

    return {
        "query": query,
        "count": len(results),
        "results": [m.to_dict() for m in results]
    }


# ============ Google Drive Ingestion (via n8n) ============

class DriveDocumentIngest(BaseModel):
    """Document from Google Drive for ingestion."""
    file_id: str
    name: str
    mime_type: str
    doc_type: str  # doc, sheet, slides, pdf, text, other
    text_content: str
    web_link: Optional[str] = None
    owner: Optional[str] = None
    modified_at: Optional[str] = None
    parents: Optional[str] = None  # JSON string of parent folder IDs
    namespace: str = "work_projektil"


@app.post("/ingest/drive")
def ingest_drive_document(doc: DriveDocumentIngest):
    """
    Ingest a Google Drive document (called by n8n workflow).

    This endpoint receives document content from n8n's Drive sync workflow,
    generates embeddings, and stores in Qdrant + Postgres.

    Args:
        doc: Document metadata and content from n8n

    Returns:
        Ingestion result with document ID and status
    """
    from datetime import datetime
    import hashlib

    # Skip empty documents
    if not doc.text_content or len(doc.text_content.strip()) < 10:
        return {
            "status": "skipped",
            "file_id": doc.file_id,
            "name": doc.name,
            "reason": "Empty or too short content"
        }

    # Generate document hash for deduplication
    content_hash = hashlib.sha256(doc.text_content.encode()).hexdigest()[:16]
    doc_id = f"drive_{doc.file_id}_{content_hash}"

    # Parse parents if provided
    parent_folders = []
    if doc.parents:
        try:
            import json
            parent_folders = json.loads(doc.parents)
        except (TypeError, json.JSONDecodeError) as e:
            logger.debug("Failed to parse drive document parents", extra={"error": str(e)})

    # Prepare metadata for Qdrant
    metadata = {
        "doc_type": "drive_document",
        "drive_file_id": doc.file_id,
        "drive_doc_type": doc.doc_type,
        "name": doc.name,
        "mime_type": doc.mime_type,
        "web_link": doc.web_link or "",
        "owner": doc.owner or "",
        "parent_folders": parent_folders,
        "namespace": doc.namespace,
        "modified_at": doc.modified_at or "",
        "ingested_at": datetime.now().isoformat(),
        "content_hash": content_hash,
        "char_count": len(doc.text_content),
        "word_count": len(doc.text_content.split()),
    }

    # Generate embedding and store in Qdrant
    try:
        from . import llm

        # For large documents, chunk the content
        max_chunk_size = 8000  # characters
        text = doc.text_content.strip()

        if len(text) > max_chunk_size:
            # Split into chunks with overlap
            chunks = []
            chunk_size = max_chunk_size
            overlap = 500
            start = 0
            chunk_idx = 0

            while start < len(text):
                end = min(start + chunk_size, len(text))
                chunk_text = text[start:end]
                chunks.append({
                    "text": chunk_text,
                    "chunk_index": chunk_idx,
                    "start_char": start,
                    "end_char": end
                })
                start = end - overlap
                chunk_idx += 1

            # Store each chunk
            stored_chunks = []
            for chunk in chunks:
                chunk_id = f"{doc_id}_chunk{chunk['chunk_index']}"
                chunk_metadata = {
                    **metadata,
                    "chunk_index": chunk["chunk_index"],
                    "total_chunks": len(chunks),
                    "start_char": chunk["start_char"],
                    "end_char": chunk["end_char"]
                }

                embedding = llm.get_embedding(chunk["text"])
                if embedding:
                    upsert_result = upsert_vectors(
                        collection=f"jarvis_{doc.namespace}",
                        vectors=[embedding],
                        payloads=[{**chunk_metadata, "text": chunk["text"]}],
                        ids=[chunk_id]
                    )
                    stored_chunks.append(chunk_id)

            log_with_context(logger, "info", "Drive document ingested (chunked)",
                           file_id=doc.file_id, name=doc.name, chunks=len(chunks))

            return {
                "status": "ingested",
                "file_id": doc.file_id,
                "name": doc.name,
                "doc_id": doc_id,
                "chunks": len(stored_chunks),
                "total_chars": len(text)
            }
        else:
            # Single chunk - store directly
            embedding = llm.get_embedding(text)
            if embedding:
                upsert_result = upsert_vectors(
                    collection=f"jarvis_{doc.namespace}",
                    vectors=[embedding],
                    payloads=[{**metadata, "text": text}],
                    ids=[doc_id]
                )

                log_with_context(logger, "info", "Drive document ingested",
                               file_id=doc.file_id, name=doc.name)

                return {
                    "status": "ingested",
                    "file_id": doc.file_id,
                    "name": doc.name,
                    "doc_id": doc_id,
                    "chunks": 1,
                    "total_chars": len(text)
                }
            else:
                return {
                    "status": "error",
                    "file_id": doc.file_id,
                    "name": doc.name,
                    "error": "Failed to generate embedding"
                }

    except Exception as e:
        log_with_context(logger, "error", "Drive document ingestion failed",
                        file_id=doc.file_id, error=str(e))
        return {
            "status": "error",
            "file_id": doc.file_id,
            "name": doc.name,
            "error": str(e)
        }


@app.get("/drive/documents")
def list_drive_documents(
    namespace: str = "work_projektil",
    doc_type: str = None,
    limit: int = 50
):
    """
    List ingested Drive documents from Qdrant.

    Args:
        namespace: Which namespace to search
        doc_type: Filter by doc_type (doc, sheet, slides, pdf, text)
        limit: Maximum results
    """
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Filter, FieldCondition, MatchValue

        client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
        collection = f"jarvis_{namespace}"

        # Build filter
        must_conditions = [
            FieldCondition(key="doc_type", match=MatchValue(value="drive_document"))
        ]
        if doc_type:
            must_conditions.append(
                FieldCondition(key="drive_doc_type", match=MatchValue(value=doc_type))
            )

        # Scroll through documents (no vector search, just list)
        results = client.scroll(
            collection_name=collection,
            scroll_filter=Filter(must=must_conditions),
            limit=limit,
            with_payload=True,
            with_vectors=False
        )

        documents = []
        seen_files = set()

        for point in results[0]:
            payload = point.payload
            file_id = payload.get("drive_file_id", "")

            # Deduplicate by file_id (in case of chunks)
            if file_id and file_id not in seen_files:
                seen_files.add(file_id)
                documents.append({
                    "file_id": file_id,
                    "name": payload.get("name", ""),
                    "doc_type": payload.get("drive_doc_type", ""),
                    "web_link": payload.get("web_link", ""),
                    "owner": payload.get("owner", ""),
                    "modified_at": payload.get("modified_at", ""),
                    "ingested_at": payload.get("ingested_at", ""),
                    "char_count": payload.get("char_count", 0),
                    "chunks": payload.get("total_chunks", 1)
                })

        return {
            "namespace": namespace,
            "count": len(documents),
            "documents": documents
        }

    except Exception as e:
        log_with_context(logger, "error", "Failed to list drive documents", error=str(e))
        return {"error": str(e), "documents": []}


@app.get("/drive/search")
def search_drive_documents(
    query: str,
    namespace: str = "work_projektil",
    doc_type: str = None,
    limit: int = 10
):
    """
    Semantic search over ingested Drive documents.

    Args:
        query: Search query
        namespace: Which namespace to search
        doc_type: Filter by doc_type
        limit: Maximum results
    """
    try:
        from . import llm
        from qdrant_client import QdrantClient
        from qdrant_client.models import Filter, FieldCondition, MatchValue

        # Generate query embedding
        query_embedding = llm.get_embedding(query)
        if not query_embedding:
            return {"error": "Failed to generate query embedding", "results": []}

        client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
        collection = f"jarvis_{namespace}"

        # Build filter
        must_conditions = [
            FieldCondition(key="doc_type", match=MatchValue(value="drive_document"))
        ]
        if doc_type:
            must_conditions.append(
                FieldCondition(key="drive_doc_type", match=MatchValue(value=doc_type))
            )

        # Search
        search_results = client.search(
            collection_name=collection,
            query_vector=query_embedding,
            query_filter=Filter(must=must_conditions),
            limit=limit,
            with_payload=True
        )

        results = []
        for hit in search_results:
            payload = hit.payload
            results.append({
                "score": hit.score,
                "file_id": payload.get("drive_file_id", ""),
                "name": payload.get("name", ""),
                "doc_type": payload.get("drive_doc_type", ""),
                "web_link": payload.get("web_link", ""),
                "text_preview": payload.get("text", "")[:300] + "..." if len(payload.get("text", "")) > 300 else payload.get("text", ""),
                "chunk_index": payload.get("chunk_index"),
                "total_chunks": payload.get("total_chunks", 1)
            })

        return {
            "query": query,
            "namespace": namespace,
            "count": len(results),
            "results": results
        }

    except Exception as e:
        log_with_context(logger, "error", "Drive search failed", error=str(e))
        return {"error": str(e), "results": []}


# ============ System Capability Update API ============

class CapabilityUpdateRequest(BaseModel):
    """Request body for capability update notifications."""
    update_type: str  # capability, feature, fix, behavior
    title: str
    description: str
    version: str = None
    expires_hours: int = 168  # 7 days default


@app.post("/system/capability-update")
def add_capability_update(request: CapabilityUpdateRequest):
    """
    Notify Jarvis about a new capability or system update.

    Used by Claude Code to push updates that Jarvis should know about immediately.
    Updates are injected into agent prompts for 7 days (configurable).

    Example usage (from Claude Code):
        curl -X POST http://jarvis-nas:5001/system/capability-update \
          -H "Content-Type: application/json" \
          -d '{"update_type": "feature", "title": "File Upload via Telegram",
               "description": "Jarvis kann jetzt Dateien via Telegram empfangen und verarbeiten."}'
    """
    from . import postgres_state

    # Validate update_type
    valid_types = ["capability", "feature", "fix", "behavior"]
    if request.update_type not in valid_types:
        return {
            "status": "error",
            "error": f"Invalid update_type. Must be one of: {valid_types}"
        }

    try:
        update_id = postgres_state.add_capability_update(
            update_type=request.update_type,
            title=request.title,
            description=request.description,
            source="claude_code",
            version=request.version,
            expires_hours=request.expires_hours
        )

        # Send Telegram alert about the update
        try:
            from .telegram_bot import send_alert
            type_emoji = {
                "capability": "🆕",
                "feature": "✨",
                "fix": "🔧",
                "behavior": "📝"
            }.get(request.update_type, "📌")

            send_alert(
                f"{type_emoji} *Neues System-Update*\n\n"
                f"**{request.title}**\n"
                f"{request.description}\n\n"
                f"_Typ: {request.update_type}_",
                level="info"
            )
        except Exception as e:
            log_with_context(logger, "warning", "Failed to send update alert", error=str(e))

        return {
            "status": "success",
            "update_id": update_id,
            "message": f"Capability update '{request.title}' added and will be active for {request.expires_hours} hours"
        }

    except Exception as e:
        log_with_context(logger, "error", "Failed to add capability update", error=str(e))
        return {"status": "error", "error": str(e)}


@app.get("/system/capability-updates")
def get_capability_updates(hours: int = 168, limit: int = 10):
    """
    Get recent capability updates.

    Returns updates from the last N hours (default 7 days).
    """
    from . import postgres_state

    try:
        updates = postgres_state.get_recent_capability_updates(
            hours=hours,
            limit=limit
        )

        return {
            "status": "success",
            "count": len(updates),
            "updates": updates
        }

    except Exception as e:
        log_with_context(logger, "error", "Failed to get capability updates", error=str(e))
        return {"status": "error", "error": str(e), "updates": []}


@app.delete("/system/capability-updates/expired")
def clear_expired_updates():
    """Remove expired capability updates from the database."""
    from . import postgres_state

    try:
        deleted = postgres_state.clear_expired_capability_updates()
        return {"status": "success", "deleted": deleted}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ============ Document Export Endpoints ============

@app.get("/export/list")
def list_exports(limit: int = 20):
    """List recent document exports."""
    from . import document_generator

    try:
        exports = document_generator.list_exports(limit=limit)
        return {"status": "success", "exports": exports}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@app.get("/export/{filename}")
def get_export_file(filename: str):
    """Get an exported document by filename."""
    from . import document_generator
    from fastapi.responses import FileResponse

    try:
        file_path = document_generator.EXPORTS_PATH / filename
        if not file_path.exists():
            return {"status": "error", "error": "File not found"}

        return FileResponse(
            path=str(file_path),
            filename=filename,
            media_type="application/octet-stream"
        )
    except Exception as e:
        return {"status": "error", "error": str(e)}


@app.post("/export/generate")
def generate_document(
    doc_type: str,
    format: str = "md",
    content: dict = None
):
    """
    Generate a document from a template.

    doc_type: email, meeting, linkedin, progress, presentation
    format: md, txt, html, pdf, docx
    content: Document content (varies by type)
    """
    from . import document_generator

    try:
        doc = document_generator.quick_generate(
            doc_type=doc_type,
            content=content or {},
            format=format
        )

        return {
            "status": "success",
            "filename": doc.filename,
            "format": doc.format,
            "path": doc.path,
            "size_bytes": doc.size_bytes
        }
    except ValueError as e:
        return {"status": "error", "error": str(e)}
    except ImportError as e:
        return {"status": "error", "error": f"Missing dependency: {str(e)}"}
    except Exception as e:
        log_with_context(logger, "error", "Document generation failed", error=str(e))
        return {"status": "error", "error": str(e)}


@app.post("/export/weekly-summary")
def generate_weekly_summary(
    user_id: int,
    period: str = "week",
    domains: list = None
):
    """
    Generate a weekly summary report for n8n workflow.

    Called by jarvis_scheduled_exports.json
    """
    from . import document_generator
    from . import session_manager
    from datetime import datetime, timedelta

    try:
        # Gather data from the past week
        now = datetime.now()
        week_start = now - timedelta(days=7)

        # Get domain sessions for the week (if domain tracking is active)
        # For now, create a simple summary based on available data

        achievements = []
        challenges = []
        next_steps = []

        # Try to get some data from sessions
        try:
            messages = session_manager.get_recent_messages(user_id, limit=100)
            if messages:
                achievements.append(f"Completed {len(messages)} conversations with Jarvis")
        except Exception:
            pass

        if not achievements:
            # No data for summary
            return {
                "status": "success",
                "success": False,
                "message": "No activity data for weekly summary"
            }

        # Generate the report
        doc = document_generator.quick_generate(
            doc_type="progress",
            content={
                "title": f"Weekly Summary - {now.strftime('%d.%m.%Y')}",
                "period": f"{week_start.strftime('%d.%m')} - {now.strftime('%d.%m.%Y')}",
                "domain": ", ".join(domains) if domains else "All",
                "achievements": achievements,
                "challenges": challenges if challenges else ["No challenges recorded"],
                "next_steps": next_steps if next_steps else ["Continue tracking progress"],
                "metrics": {}
            },
            format="md"
        )

        return {
            "status": "success",
            "success": True,
            "title": f"Weekly Summary - {now.strftime('%d.%m.%Y')}",
            "file_path": doc.path,
            "filename": doc.filename
        }

    except Exception as e:
        log_with_context(logger, "error", "Weekly summary failed", error=str(e))
        return {"status": "error", "success": False, "error": str(e)}


# ============ Coaching Domains API ============

@app.get("/domains")
def list_coaching_domains():
    """List all available coaching domains."""
    from . import coaching_domains

    try:
        domains = coaching_domains.list_domains()
        return {"status": "success", "domains": domains}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@app.get("/domains/{domain_id}")
def get_coaching_domain(domain_id: str):
    """Get details for a specific coaching domain."""
    from . import coaching_domains

    try:
        domain = coaching_domains.get_domain(domain_id)
        if not domain:
            return {"status": "error", "error": "Domain not found"}

        return {
            "status": "success",
            "domain": {
                "id": domain.id,
                "name": domain.name,
                "description": domain.description,
                "role_id": domain.role_id,
                "persona_id": domain.persona_id,
                "namespace": domain.knowledge_namespace,
                "tools": domain.tools_enabled,
                "greeting": domain.greeting,
                "icon": domain.icon
            }
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


@app.get("/domains/user/{user_id}")
def get_user_domain(user_id: int):
    """Get the active domain for a user."""
    from . import coaching_domains

    try:
        active_domain = coaching_domains.get_user_domain(user_id)
        domain = coaching_domains.get_domain(active_domain)

        return {
            "status": "success",
            "active_domain": active_domain,
            "domain_name": domain.name if domain else "Unknown",
            "domain_icon": domain.icon if domain else ""
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


@app.post("/domains/user/{user_id}/switch")
def switch_user_domain(user_id: int, domain_id: str):
    """Switch the active domain for a user."""
    from . import coaching_domains

    try:
        success = coaching_domains.set_user_domain(user_id, domain_id)
        if not success:
            return {"status": "error", "error": "Failed to switch domain"}

        domain = coaching_domains.get_domain(domain_id)
        greeting = coaching_domains.get_domain_greeting(domain_id)

        return {
            "status": "success",
            "domain_id": domain_id,
            "domain_name": domain.name if domain else domain_id,
            "greeting": greeting
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ============ Async Coaching API ============

@app.get("/async/pending")
def get_pending_async_interactions(user_id: int = None):
    """Get pending async coaching interactions (for n8n workflow)."""
    try:
        from . import async_coach
        interactions = async_coach.get_pending_interactions(user_id=user_id)
        return {"interactions": interactions}
    except Exception as e:
        return {"interactions": [], "error": str(e)}


@app.post("/async/executed/{interaction_id}")
def mark_interaction_executed(interaction_id: int):
    """Mark an async interaction as executed (for n8n workflow)."""
    try:
        from . import async_coach
        success = async_coach.mark_executed(interaction_id, result={"via": "n8n"})
        return {"status": "success" if success else "failed", "id": interaction_id}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@app.post("/async/skip/{interaction_id}")
def skip_interaction(interaction_id: int, reason: str = "manual"):
    """Skip an async interaction."""
    try:
        from . import async_coach
        success = async_coach.mark_skipped(interaction_id, reason=reason)
        return {"status": "success" if success else "failed", "id": interaction_id}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@app.get("/async/upcoming/{user_id}")
def get_upcoming_interactions(user_id: int, hours: int = 24):
    """Get upcoming scheduled interactions for a user."""
    try:
        from . import async_coach
        interactions = async_coach.get_upcoming_interactions(user_id, hours=hours)
        return {"interactions": interactions}
    except Exception as e:
        return {"interactions": [], "error": str(e)}


# ============ Learning & Cross-Domain API ============

@app.get("/learning/weekly-digest")
def get_weekly_learning_digest(user_id: int = 1465947014):
    """Generate weekly learning digest (for n8n workflow)."""
    try:
        from . import cross_domain_learner
        digest = cross_domain_learner.generate_weekly_learning_digest(user_id)
        return digest
    except Exception as e:
        return {"insights": [], "synergies": [], "recommendations": [], "error": str(e)}


@app.get("/digest/weekly")
def get_consolidated_weekly_digest(user_id: int = 1465947014, days: int = 7):
    """
    Consolidated Weekly Digest for Telegram (Phase 18.1).

    Combines:
    - Session statistics (from cross-session learning)
    - Migration candidates (top 5)
    - Message feedback stats (👍👎🤔 buttons)
    - Tool loop detection stats
    - System health summary
    """
    from datetime import datetime

    result = {
        "generated_at": datetime.now().isoformat(),
        "period_days": days,
        "sessions": {},
        "feedback": {},
        "suggestions": {},  # Phase 18 - Outcome Tracking
        "tool_loops": {},
        "migration_candidates": [],
        "health": {},
        "formatted_message": ""
    }

    # 1. Session Statistics (from postgres_state)
    try:
        from . import postgres_state
        stats = postgres_state.get_session_learning_stats()
        result["sessions"] = {
            "total": stats.get("total_sessions", 0),
            "facts_extracted": stats.get("total_facts_extracted", 0),
            "sessions_last_7_days": stats.get("sessions_last_7_days", 0),
            "by_source": stats.get("by_source", {})
        }
    except Exception as e:
        result["sessions"] = {"error": str(e), "total": 0}

    # 2. Message Feedback Stats (from Telegram buttons)
    try:
        from . import state_db
        feedback_stats = state_db.get_message_feedback_stats(user_id=user_id, days=days)
        result["feedback"] = {
            "total": feedback_stats.get("total", 0),
            "by_rating": feedback_stats.get("by_rating", {}),
            "satisfaction_score": feedback_stats.get("satisfaction_score", 0)
        }
    except Exception as e:
        result["feedback"] = {"error": str(e), "total": 0}

    # 3. Tool Loop Stats (from observability)
    try:
        from .observability import tool_loop_detector
        result["tool_loops"] = {
            "total_detected": tool_loop_detector.loops_total
        }
    except Exception as e:
        result["tool_loops"] = {"error": str(e), "total_detected": 0}

    # 4. Migration Candidates (top 5)
    try:
        from . import postgres_state
        candidates = postgres_state.get_migration_candidates(limit=5)
        result["migration_candidates"] = candidates[:5] if candidates else []
    except Exception as e:
        result["migration_candidates"] = []

    # 5. Health Summary
    try:
        from .routers.health_router import health_check
        health_data = health_check()
        result["health"] = {
            "status": health_data.get("status", "unknown"),
            "healthy_count": health_data.get("summary", {}).get("healthy", 0),
            "total_checks": health_data.get("summary", {}).get("total_checks", 0)
        }
    except Exception as e:
        result["health"] = {"status": "unknown", "error": str(e)}

    # 6. Suggestion Outcome Stats (Phase 18 - Outcome Tracking System)
    try:
        from .cross_session_learner import cross_session_learner
        suggestion_stats = cross_session_learner.get_suggestion_stats(user_id=user_id, days=days)
        top_suggestions = cross_session_learner.get_top_working_suggestions(user_id=user_id, limit=3)
        result["suggestions"] = {
            "total": suggestion_stats.get("total_suggestions", 0),
            "outcomes_recorded": suggestion_stats.get("outcomes_recorded", 0),
            "by_outcome": suggestion_stats.get("by_outcome", {}),
            "effectiveness_rate": suggestion_stats.get("effectiveness_rate", 0),
            "top_working": top_suggestions
        }
    except Exception as e:
        result["suggestions"] = {"error": str(e), "total": 0}

    # 7. Format Telegram Message (ADHD-friendly)
    msg_parts = ["*📊 Jarvis Weekly Digest*", f"_Woche {datetime.now().strftime('%W')} • {datetime.now().strftime('%d.%m.%Y')}_", ""]

    # Sessions
    sessions = result["sessions"]
    msg_parts.append(f"*Sessions:* {sessions.get('sessions_last_7_days', sessions.get('total', 0))} | *Facts:* {sessions.get('facts_extracted', 0)}")

    # Feedback
    fb = result["feedback"]
    if fb.get("total", 0) > 0:
        by_rating = fb.get("by_rating", {})
        good = by_rating.get("good", 0)
        ok = by_rating.get("ok", 0)
        bad = by_rating.get("bad", 0)
        score = fb.get("satisfaction_score") or 0
        msg_parts.append(f"*Feedback:* 👍{good} 🤔{ok} 👎{bad} (Score: {score:.0%})")

    # Suggestions (Phase 18 - Outcome Tracking)
    sugg = result.get("suggestions", {})
    if sugg.get("total", 0) > 0:
        by_outcome = sugg.get("by_outcome", {})
        worked = by_outcome.get("worked", 0)
        partially = by_outcome.get("partially", 0)
        didnt = by_outcome.get("didnt_work", 0)
        eff_rate = sugg.get("effectiveness_rate", 0)
        msg_parts.append(f"*Vorschläge:* ✅{worked} 🔄{partially} ❌{didnt} (Effektiv: {eff_rate:.0f}%)")

        # Show top working suggestions if any
        top_working = sugg.get("top_working", [])
        if top_working:
            msg_parts.append("")
            msg_parts.append("*💡 Das hat geholfen:*")
            for s in top_working[:2]:
                text = (s.get("suggestion_text") or "")[:50]
                msg_parts.append(f"  • _{text}..._")

    # Tool Loops
    loops = result["tool_loops"].get("total_detected", 0)
    if loops > 0:
        msg_parts.append(f"*⚠️ Tool-Loops:* {loops} erkannt")

    # Health
    health = result["health"]
    health_emoji = "✅" if health.get("status") == "healthy" else "⚠️"
    msg_parts.append(f"*System:* {health_emoji} {health.get('healthy_count', 0)}/{health.get('total_checks', 0)} healthy")

    # Migration Candidates
    candidates = result["migration_candidates"]
    if candidates:
        msg_parts.append("")
        msg_parts.append(f"*🎯 Migration-Kandidaten ({len(candidates)}):*")
        for i, c in enumerate(candidates[:3], 1):
            content = (c.get("content") or "")[:60]
            msg_parts.append(f"  {i}. _{content}..._")

    msg_parts.append("")
    msg_parts.append("_Gute Woche!_")

    result["formatted_message"] = "\n".join(msg_parts)

    return result


@app.get("/learning/effectiveness/{user_id}")
def get_effectiveness_insights(user_id: int, days: int = 30):
    """Get coaching effectiveness insights."""
    try:
        from . import feedback_tracker
        insights = feedback_tracker.generate_effectiveness_insights(user_id, days=days)
        return insights
    except Exception as e:
        return {"error": str(e)}


@app.get("/learning/correlations/{user_id}")
def get_domain_correlations(user_id: int, days: int = 30):
    """Get cross-domain correlations for a user."""
    try:
        from . import cross_domain_learner
        correlations = cross_domain_learner.calculate_domain_correlations(user_id, days=days)
        return {
            "correlations": [
                {
                    "domain_a": c.domain_a,
                    "domain_b": c.domain_b,
                    "type": c.correlation_type,
                    "strength": c.strength,
                    "description": c.description
                }
                for c in correlations
            ]
        }
    except Exception as e:
        return {"correlations": [], "error": str(e)}


@app.get("/learning/synergies/{user_id}")
def get_synergies(user_id: int):
    """Get domain synergies for a user."""
    try:
        from . import cross_domain_learner
        synergies = cross_domain_learner.get_domain_synergies(user_id)
        conflicts = cross_domain_learner.get_domain_conflicts(user_id)
        return {"synergies": synergies, "conflicts": conflicts}
    except Exception as e:
        return {"synergies": [], "conflicts": [], "error": str(e)}


@app.post("/learning/detect-patterns")
def detect_cross_domain_patterns(user_id: int = 1465947014, days: int = 7):
    """
    Proactively detect cross-domain patterns and notify user.
    Called by n8n workflow for daily pattern analysis.
    Returns patterns that warrant user notification.
    """
    try:
        from . import cross_domain_learner
        from . import knowledge_db

        # Detect patterns
        patterns = cross_domain_learner.detect_patterns(user_id, days=days)

        # Filter for significant patterns (confidence > 0.6)
        significant = [p for p in patterns if p.get("confidence", 0) > 0.6]

        # Check for new insights not yet delivered
        undelivered = []
        for pattern in significant:
            # Check if this pattern was already sent recently
            with knowledge_db.get_conn() as conn:
                cur = conn.cursor()
                cur.execute("""
                    SELECT id FROM cross_domain_insight
                    WHERE user_id = %s
                    AND insight_type = %s
                    AND source_domain = %s
                    AND created_at > NOW() - INTERVAL '3 days'
                """, (user_id, pattern.get("type"), pattern.get("source_domain")))
                if not cur.fetchone():
                    undelivered.append(pattern)
                    # Store as delivered
                    cur.execute("""
                        INSERT INTO cross_domain_insight
                        (user_id, source_domain, target_domain, insight_type, content, confidence)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, (
                        user_id,
                        pattern.get("source_domain", "unknown"),
                        pattern.get("target_domain"),
                        pattern.get("type", "pattern"),
                        pattern.get("description", ""),
                        pattern.get("confidence", 0.5)
                    ))
                conn.commit()

        # Generate notification message if patterns found
        notification = None
        if undelivered:
            messages = []
            for p in undelivered[:3]:  # Max 3 patterns
                messages.append(f"• {p.get('description', 'Pattern erkannt')}")
            notification = {
                "should_notify": True,
                "title": "🔍 Cross-Domain Muster erkannt",
                "message": "\n".join(messages),
                "pattern_count": len(undelivered)
            }
        else:
            notification = {"should_notify": False, "pattern_count": 0}

        return {
            "patterns_detected": len(patterns),
            "significant_patterns": len(significant),
            "new_patterns": len(undelivered),
            "notification": notification,
            "patterns": undelivered
        }
    except Exception as e:
        log_with_context(logger, "error", "Pattern detection failed", error=str(e))
        return {"error": str(e), "notification": {"should_notify": False}}


# ============ Goals API (for n8n) ============

@app.get("/goals/active")
def get_active_goals(user_id: int = 1465947014):
    """Get active domain goals for a user (for n8n workflow)."""
    try:
        from . import knowledge_db
        with knowledge_db.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, user_id, domain_id, goal_title, target_date,
                       progress_pct, milestones, status, created_at
                FROM domain_goal
                WHERE user_id = %s AND status = 'active'
                ORDER BY target_date ASC NULLS LAST
            """, (user_id,))
            goals = [dict(row) for row in cur.fetchall()]
            return {"goals": goals}
    except Exception as e:
        return {"goals": [], "error": str(e)}


class CreateGoalRequest(BaseModel):
    user_id: int
    domain_id: str
    goal_title: str
    target_date: str | None = None
    milestones: list | None = None


@app.post("/goals/create")
def create_domain_goal(req: CreateGoalRequest):
    """Create a new domain goal."""
    try:
        from . import knowledge_db
        from datetime import datetime
        with knowledge_db.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO domain_goal
                (user_id, domain_id, goal_title, target_date, progress_pct, milestones, status, created_at)
                VALUES (%s, %s, %s, %s, 0, %s, 'active', %s)
                RETURNING id
            """, (
                req.user_id,
                req.domain_id,
                req.goal_title,
                req.target_date,
                json.dumps(req.milestones or []),
                datetime.utcnow()
            ))
            row = cur.fetchone()
            return {"status": "created", "goal_id": row["id"] if row else None}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@app.post("/goals/{goal_id}/progress")
def update_goal_progress(goal_id: int, progress_pct: int, notes: str = None):
    """Update goal progress."""
    try:
        from . import knowledge_db
        with knowledge_db.get_conn() as conn:
            cur = conn.cursor()
            cur.execute("""
                UPDATE domain_goal
                SET progress_pct = %s
                WHERE id = %s
            """, (progress_pct, goal_id))

            if progress_pct >= 100:
                cur.execute("""
                    UPDATE domain_goal SET status = 'completed' WHERE id = %s
                """, (goal_id,))

            return {"status": "updated", "goal_id": goal_id, "progress": progress_pct}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ============ Competency API ============

@app.get("/competencies/{user_id}")
def get_user_competencies(user_id: int, domain_id: str = None):
    """Get competencies for a user."""
    try:
        from . import competency_model
        competencies = competency_model.get_user_competencies(user_id, domain_id=domain_id)
        return {"competencies": competencies}
    except Exception as e:
        return {"competencies": [], "error": str(e)}


@app.get("/competencies/{user_id}/gaps")
def get_skill_gaps(user_id: int, domain_id: str = None):
    """Get skill gaps for a user."""
    try:
        from . import competency_model
        gaps = competency_model.get_skill_gaps(user_id, domain_id=domain_id)
        return {"gaps": gaps}
    except Exception as e:
        return {"gaps": [], "error": str(e)}


@app.post("/competencies/{user_id}/update")
def update_competency(
    user_id: int,
    domain_id: str,
    competency_name: str,
    new_level: int,
    evidence: str = None
):
    """Update a user's competency level."""
    try:
        from . import competency_model
        success = competency_model.update_competency(
            user_id=user_id,
            domain_id=domain_id,
            competency_name=competency_name,
            new_level=new_level,
            evidence=evidence
        )
        return {"status": "success" if success else "failed"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ============ SSH Management API ============

@app.post("/ssh/execute")
def execute_ssh_command(
    command: str,
    sudo: bool = False,
    rate_limit: Any = Depends(rate_limit_dependency)
):
    """Execute a command on the NAS via SSH."""
    try:
        result = ssh_client.execute_command(command, sudo)
        return result
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "stdout": "",
            "stderr": "",
            "exit_code": -1
        }


@app.post("/ssh/script")
def execute_ssh_script(
    script_content: str,
    interpreter: str = "bash",
    rate_limit: Any = Depends(rate_limit_dependency)
):
    """Execute a script on the NAS via SSH."""
    try:
        with ssh_client.SSHClient() as ssh:
            result = ssh.execute_script(script_content, interpreter)
        return result
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "stdout": "",
            "stderr": "",
            "exit_code": -1
        }


@app.get("/ssh/status")
def get_ssh_status(rate_limit: Any = Depends(rate_limit_dependency)):
    """Get system status via SSH."""
    try:
        return ssh_client.get_system_status()
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/ssh/docker")
def get_docker_status_ssh(rate_limit: Any = Depends(rate_limit_dependency)):
    """Get Docker container status via SSH."""
    try:
        return ssh_client.get_docker_status()
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/ssh/restart/{service_name}")
def restart_service_ssh(
    service_name: str,
    rate_limit: Any = Depends(rate_limit_dependency)
):
    """Restart a Jarvis service via SSH."""
    try:
        return ssh_client.restart_jarvis_service(service_name)
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/ssh/logs/{service_name}")
def get_service_logs_ssh(
    service_name: str,
    lines: int = 50,
    rate_limit: Any = Depends(rate_limit_dependency)
):
    """Get service logs via SSH."""
    try:
        return ssh_client.tail_service_logs(service_name, lines)
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============ n8n Workflow Management API ============

@app.get("/n8n/workflows")
def list_n8n_workflows(
    active_only: bool = False,
    rate_limit: Any = Depends(rate_limit_dependency)
):
    """List all n8n workflows."""
    manager = n8n_workflow_manager.N8NWorkflowManager()
    workflows = manager.list_workflows(active_only)
    return {"workflows": workflows}


@app.get("/n8n/workflows/{workflow_id}")
def get_n8n_workflow(
    workflow_id: str,
    rate_limit: Any = Depends(rate_limit_dependency)
):
    """Get a specific n8n workflow."""
    manager = n8n_workflow_manager.N8NWorkflowManager()
    return manager.get_workflow(workflow_id)


class CreateWorkflowRequest(BaseModel):
    workflow_data: Dict[str, Any]


@app.post("/n8n/workflows")
def create_n8n_workflow(
    req: CreateWorkflowRequest,
    rate_limit: Any = Depends(rate_limit_dependency)
):
    """Create a new n8n workflow."""
    manager = n8n_workflow_manager.N8NWorkflowManager()
    return manager.create_workflow(req.workflow_data)


class UpdateWorkflowRequest(BaseModel):
    workflow_data: Dict[str, Any]


@app.patch("/n8n/workflows/{workflow_id}")
def update_n8n_workflow(
    workflow_id: str,
    req: UpdateWorkflowRequest,
    rate_limit: Any = Depends(rate_limit_dependency)
):
    """Update an n8n workflow."""
    manager = n8n_workflow_manager.N8NWorkflowManager()
    return manager.update_workflow(workflow_id, req.workflow_data)


@app.post("/n8n/workflows/{workflow_id}/activate")
def activate_n8n_workflow(
    workflow_id: str,
    rate_limit: Any = Depends(rate_limit_dependency)
):
    """Activate an n8n workflow."""
    manager = n8n_workflow_manager.N8NWorkflowManager()
    return manager.activate_workflow(workflow_id)


@app.post("/n8n/workflows/{workflow_id}/deactivate")
def deactivate_n8n_workflow(
    workflow_id: str,
    rate_limit: Any = Depends(rate_limit_dependency)
):
    """Deactivate an n8n workflow."""
    manager = n8n_workflow_manager.N8NWorkflowManager()
    return manager.deactivate_workflow(workflow_id)


@app.delete("/n8n/workflows/{workflow_id}")
def delete_n8n_workflow(
    workflow_id: str,
    rate_limit: Any = Depends(rate_limit_dependency)
):
    """Delete an n8n workflow."""
    manager = n8n_workflow_manager.N8NWorkflowManager()
    return manager.delete_workflow(workflow_id)


class ExecuteWorkflowRequest(BaseModel):
    data: Dict[str, Any] = None


@app.post("/n8n/workflows/{workflow_id}/execute")
def execute_n8n_workflow(
    workflow_id: str,
    req: ExecuteWorkflowRequest = None,
    rate_limit: Any = Depends(rate_limit_dependency)
):
    """Execute an n8n workflow manually."""
    manager = n8n_workflow_manager.N8NWorkflowManager()
    data = req.data if req else None
    return manager.execute_workflow(workflow_id, data)


@app.get("/n8n/templates")
def get_workflow_templates(rate_limit: Any = Depends(rate_limit_dependency)):
    """Get available workflow templates."""
    return n8n_workflow_manager.get_workflow_templates()


class CreateFromTemplateRequest(BaseModel):
    template_name: str
    params: Dict[str, Any]


@app.post("/n8n/templates/create")
def create_from_template(
    req: CreateFromTemplateRequest,
    rate_limit: Any = Depends(rate_limit_dependency)
):
    """Create a workflow from a template."""
    return n8n_workflow_manager.create_workflow_from_template(
        req.template_name,
        req.params
    )


@app.get("/n8n/workflow/status")
def get_n8n_workflow_status(rate_limit: Any = Depends(rate_limit_dependency)):
    """Get n8n workflow management status."""
    return n8n_workflow_manager.get_n8n_workflow_status()


# ============ Phase 18: Cross-AI Learning Endpoints ============

class SessionLearningRequest(BaseModel):
    """Request model for submitting AI session learnings"""
    session_id: str
    source: str  # claude_code, copilot, cursor, other
    summary: str | None = None
    files_modified: List[str] | None = None
    learnings: List[dict] | None = None  # [{fact, category, confidence}]
    code_changes: dict | None = None  # {added_lines, removed_lines, files}
    duration_minutes: int | None = None


class MigrationApprovalRequest(BaseModel):
    """Request model for approving a fact migration"""
    fact_id: str  # SQLite fact ID (hash-based)
    target_file: str
    action: str = "approve"  # approve, reject, defer
    notes: str | None = None


@app.post("/learning/session")
def submit_session_learning(req: SessionLearningRequest):
    """
    Submit an AI session learning record.

    Called by Claude Code, Copilot, or other AI tools after a session.
    Jarvis will extract facts and learnings automatically.

    Example:
    {
        "session_id": "cc_2026-02-02_14-30",
        "source": "claude_code",
        "summary": "Implemented Cross-AI Learning Pipeline for Phase 18",
        "files_modified": ["app/main.py", "app/postgres_state.py"],
        "learnings": [
            {"fact": "Jarvis can learn from Claude Code sessions", "category": "capability", "confidence": 0.9},
            {"fact": "Migration candidates are prioritized by trust*0.4 + access*0.3", "category": "algorithm", "confidence": 0.95}
        ],
        "code_changes": {"added_lines": 250, "removed_lines": 10, "files": 2},
        "duration_minutes": 45
    }
    """
    from . import postgres_state, memory_store

    # Validate source
    valid_sources = ["claude_code", "copilot", "cursor", "other", "telegram", "n8n"]
    if req.source not in valid_sources:
        return {
            "status": "error",
            "error": f"Invalid source. Must be one of: {valid_sources}"
        }

    # Save the session learning
    result = postgres_state.save_session_learning(
        session_id=req.session_id,
        source=req.source,
        summary=req.summary,
        files_modified=req.files_modified,
        learnings=req.learnings,
        code_changes=req.code_changes,
        duration_minutes=req.duration_minutes
    )

    # If learnings were provided, also save them as facts
    facts_created = 0
    if req.learnings:
        for learning in req.learnings:
            if learning.get("fact"):
                try:
                    # Store as a fact in memory with source tracking
                    memory_store.add_fact(
                        fact=learning["fact"],
                        category=learning.get("category", "learned"),
                        source=f"ai_session:{req.source}",
                        confidence=learning.get("confidence", 0.7),
                        initial_trust_score=0.3  # User explicitly provided
                    )
                    facts_created += 1
                except Exception as e:
                    log_with_context(logger, "warning", "Failed to store learning as fact",
                                    fact=learning["fact"][:50], error=str(e))

    # Mark as processed if we extracted facts
    if facts_created > 0:
        postgres_state.mark_session_processed(req.session_id, facts_created)

    log_with_context(logger, "info", "Session learning submitted",
                    session_id=req.session_id, source=req.source,
                    facts_created=facts_created)

    return {
        "status": "ok",
        "session_id": req.session_id,
        "source": req.source,
        "created_at": result.get("created_at"),
        "learnings_received": len(req.learnings or []),
        "facts_created": facts_created,
        "message": f"Session recorded. {facts_created} facts extracted and stored."
    }


@app.get("/learning/sessions")
def list_session_learnings(
    source: str = None,
    processed: bool = None,
    limit: int = 50
):
    """
    List AI session learning records.

    Args:
        source: Filter by source (claude_code, copilot, etc.)
        processed: Filter by processed status (true/false)
        limit: Max results (default 50)
    """
    from . import postgres_state

    sessions = postgres_state.list_session_learnings(
        source=source,
        processed=processed,
        limit=limit
    )

    return {
        "sessions": sessions,
        "count": len(sessions),
        "filters": {
            "source": source,
            "processed": processed
        }
    }


@app.get("/learning/sessions/{session_id}")
def get_session_learning(session_id: str):
    """Get a specific session learning record."""
    from . import postgres_state

    session = postgres_state.get_session_learning(session_id)

    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    return session


@app.get("/learning/migration-candidates")
def get_migration_candidates(limit: int = 10, min_priority: str = "medium"):
    """
    Get facts that are candidates for migration to permanent code.

    These are high-trust, frequently-accessed facts that Jarvis suggests
    should be "graduated" from dynamic memory to static configuration.

    Priority levels:
    - critical: priority >= 0.8 (immediate migration recommended)
    - high: priority >= 0.6 (should migrate soon)
    - medium: priority >= 0.4 (consider for migration)

    Returns candidates sorted by priority score.
    """
    from . import postgres_state

    candidates = postgres_state.get_migration_candidates(limit=limit)

    # Filter by minimum priority if specified
    priority_thresholds = {"critical": 0.8, "high": 0.6, "medium": 0.4}
    min_score = priority_thresholds.get(min_priority, 0.4)

    filtered = [c for c in candidates if c.get("priority_score", 0) >= min_score]

    # Group by category
    by_category = {"critical": [], "high": [], "medium": []}
    for c in filtered:
        cat = c.get("priority_category", "medium")
        by_category[cat].append(c)

    return {
        "candidates": filtered,
        "count": len(filtered),
        "by_category": {k: len(v) for k, v in by_category.items()},
        "min_priority": min_priority,
        "message": f"{len(filtered)} facts ready for migration review"
    }


@app.post("/learning/approve-migration")
def approve_migration(req: MigrationApprovalRequest):
    """
    Approve, reject, or defer a fact migration.

    When approved, generates the migration code snippet for the target file.

    Actions:
    - approve: Generate code snippet, mark fact as migrated
    - reject: Remove from migration candidates (lower trust score)
    - defer: Keep for later review (no change)
    """
    # Get fact from migration candidates to verify it exists
    from . import postgres_state
    candidates = postgres_state.get_migration_candidates(limit=100)
    fact = next((c for c in candidates if c.get("id") == req.fact_id), None)

    if not fact:
        # Try to find in all facts
        facts = memory_store.get_facts(limit=100, track_access=False)
        fact = next((f for f in facts if f.get("id") == req.fact_id), None)

    if not fact:
        raise HTTPException(status_code=404, detail=f"Fact {req.fact_id} not found")

    result = {
        "fact_id": req.fact_id,
        "action": req.action,
        "target_file": req.target_file
    }

    if req.action == "approve":
        # Generate migration snippet based on target file type
        content = fact.get("content") or fact.get("fact", "")
        fact_type = fact.get("fact_type") or fact.get("category", "general")

        if req.target_file.endswith(".yaml"):
            snippet = _generate_yaml_snippet(fact_type, content)
        elif req.target_file.endswith(".py"):
            snippet = _generate_python_snippet(fact_type, content)
        elif req.target_file.endswith(".md"):
            snippet = _generate_markdown_snippet(fact_type, content)
        else:
            snippet = f"# {fact_type}\n{content}"

        result["snippet"] = snippet
        result["message"] = f"Migration approved. Add this to {req.target_file}"

        # Mark fact as migrated
        try:
            memory_store.mark_fact_migrated(req.fact_id, req.target_file)
        except Exception as e:
            log_with_context(logger, "warning", "Failed to mark fact as migrated",
                           fact_id=req.fact_id, error=str(e))

    elif req.action == "reject":
        # Lower trust score for rejected facts
        try:
            memory_store.reduce_trust(req.fact_id, amount=0.2)
        except Exception as e:
            log_with_context(logger, "warning", "Failed to reduce trust",
                           fact_id=req.fact_id, error=str(e))
        result["message"] = "Fact rejected for migration. Trust score reduced."

    elif req.action == "defer":
        result["message"] = "Migration deferred. Will appear in next review."

    log_with_context(logger, "info", "Migration action taken",
                    fact_id=req.fact_id, action=req.action,
                    target=req.target_file)

    return result


def _generate_yaml_snippet(fact_type: str, content: str) -> str:
    """Generate YAML snippet for migration."""
    # Clean content for YAML
    safe_content = content.replace('"', '\\"')
    return f"""# {fact_type} (migrated from Jarvis memory)
{fact_type.lower().replace(' ', '_')}:
  value: "{safe_content}"
  source: "jarvis_memory_migration"
  migrated_at: "{datetime.now().strftime('%Y-%m-%d')}"
"""


def _generate_python_snippet(fact_type: str, content: str) -> str:
    """Generate Python snippet for migration."""
    var_name = fact_type.upper().replace(" ", "_").replace("-", "_")
    safe_content = content.replace('"', '\\"')
    return f'''# {fact_type} (migrated from Jarvis memory)
{var_name} = "{safe_content}"
'''


def _generate_markdown_snippet(fact_type: str, content: str) -> str:
    """Generate Markdown snippet for migration."""
    return f"""### {fact_type}

{content}

_Migrated from Jarvis memory on {datetime.now().strftime('%Y-%m-%d')}_
"""


@app.get("/learning/stats")
def get_learning_stats():
    """
    Get statistics about Cross-AI Learning.

    Includes:
    - Sessions by source
    - Facts extracted
    - Migration candidates
    """
    from . import postgres_state

    session_stats = postgres_state.get_session_learning_stats()

    # Get migration candidate counts
    candidates = postgres_state.get_migration_candidates(limit=100)
    migration_stats = {
        "critical": len([c for c in candidates if c.get("priority_category") == "critical"]),
        "high": len([c for c in candidates if c.get("priority_category") == "high"]),
        "medium": len([c for c in candidates if c.get("priority_category") == "medium"])
    }

    return {
        "sessions": session_stats,
        "migration_candidates": migration_stats,
        "total_migration_ready": sum(migration_stats.values()),
        "summary": f"{session_stats.get('total_sessions', 0)} sessions, "
                   f"{session_stats.get('total_facts_extracted', 0)} facts extracted, "
                   f"{sum(migration_stats.values())} ready for migration"
    }


# ============ Phase 18.4: Permission Matrix Endpoints (Gate A) ============

@app.get("/permissions/list")
def list_permissions(tier: Optional[str] = None):
    """
    List all permissions in the system.

    Optional filter by tier: autonomous, notify, approve_standard, approve_critical, forbidden
    """
    from . import permissions as perm_module

    try:
        all_perms = perm_module.list_permissions()

        if tier:
            all_perms = [p for p in all_perms if p.get("tier") == tier]

        # Get tier stats
        tier_stats = perm_module.get_tier_stats()

        return {
            "permissions": all_perms,
            "count": len(all_perms),
            "tier_stats": tier_stats,
            "filter_applied": tier
        }
    except Exception as e:
        logger.error(f"Failed to list permissions: {e}")
        return {"error": str(e), "permissions": []}


@app.get("/permissions/check")
def check_permission(action: str, actor: str = "jarvis", context: Optional[str] = None):
    """
    Check if an action is permitted.

    Returns the permission result including tier, whether approval is needed, etc.
    """
    from . import permissions as perm_module

    ctx = {}
    if context:
        try:
            import json
            ctx = json.loads(context)
        except Exception as e:
            logger.exception(f"Failed to parse context JSON: {e}", extra={
                "trace_id": get_trace_context().get("trace_id", "unknown"),
                "context_raw": str(context)[:500]  # Limit length to avoid noise
            })
            ctx = {"raw": context}

    result = perm_module.check_permission(action, actor, ctx)

    return result


@app.post("/permissions/reload")
def reload_permissions():
    """
    Reload permissions from YAML file into database.

    Use after updating jarvis_permissions.yaml.
    """
    from . import permissions as perm_module

    try:
        # Load and sync
        yaml_path = "/brain/system/policies/jarvis_permissions.yaml"
        permissions_data = perm_module.load_permissions_from_yaml(yaml_path)

        if not permissions_data:
            return {"success": False, "error": "Failed to load YAML file"}

        perm_module.sync_permissions_to_db(permissions_data)

        # Return current stats
        tier_stats = perm_module.get_tier_stats()

        return {
            "success": True,
            "message": "Permissions reloaded from YAML",
            "tier_stats": tier_stats,
            "total_permissions": sum(tier_stats.values())
        }
    except Exception as e:
        logger.error(f"Failed to reload permissions: {e}")
        return {"success": False, "error": str(e)}


@app.get("/permissions/audit")
def get_permission_audit(
    action: Optional[str] = None,
    actor: Optional[str] = None,
    limit: int = 50
):
    """
    View permission audit log.

    Optional filters by action and/or actor.
    """
    from . import permissions as perm_module

    try:
        audit_log = perm_module.list_audit_log(
            action=action,
            actor=actor,
            limit=min(limit, 500)  # Cap at 500
        )

        return {
            "audit_log": audit_log,
            "count": len(audit_log),
            "filters": {
                "action": action,
                "actor": actor,
                "limit": limit
            }
        }
    except Exception as e:
        logger.error(f"Failed to get audit log: {e}")
        return {"error": str(e), "audit_log": []}


@app.get("/permissions/path/check")
def check_path_permission(path: str, operation: str = "read"):
    """
    Check if a filesystem path is allowed for Jarvis operations.

    Operations: read, write, execute
    """
    from . import permissions as perm_module

    result = perm_module.check_path_permission(path, operation)

    return result


@app.get("/permissions/tiers")
def get_permission_tiers():
    """
    Get overview of permission tiers and their meanings.
    """
    from . import permissions as perm_module

    tier_stats = perm_module.get_tier_stats()

    tiers_info = {
        "autonomous": {
            "description": "Can act without asking",
            "requires_approval": False,
            "notify_user": False,
            "count": tier_stats.get("autonomous", 0)
        },
        "notify": {
            "description": "Can act but must inform user",
            "requires_approval": False,
            "notify_user": True,
            "count": tier_stats.get("notify", 0)
        },
        "approve_standard": {
            "description": "Must get user approval first (normal priority)",
            "requires_approval": True,
            "notify_user": True,
            "count": tier_stats.get("approve_standard", 0)
        },
        "approve_critical": {
            "description": "Must get explicit user approval (critical action)",
            "requires_approval": True,
            "notify_user": True,
            "count": tier_stats.get("approve_critical", 0)
        },
        "forbidden": {
            "description": "Never allowed under any circumstances",
            "requires_approval": False,
            "notify_user": False,
            "count": tier_stats.get("forbidden", 0)
        }
    }

    return {
        "tiers": tiers_info,
        "total_permissions": sum(tier_stats.values()),
        "gate": "A",
        "gate_name": "More tools (read-only) ok"
    }


# ============ Gate A: Tool Audit Trail ============

@app.get("/tools/audit")
def get_tool_audit(
    tool_name: str = None,
    trace_id: str = None,
    actor: str = None,
    success: bool = None,
    limit: int = 50
):
    """
    Get tool execution audit trail.

    Gate A requirement: Every tool execution is logged for traceability.

    Query params:
    - tool_name: Filter by specific tool
    - trace_id: Filter by trace/correlation ID
    - actor: Filter by actor (who triggered the tool)
    - success: Filter by success status (true/false)
    - limit: Max records to return (default 50)
    """
    try:
        from .postgres_state import get_cursor

        conditions = []
        params = []

        if tool_name:
            conditions.append("tool_name = %s")
            params.append(tool_name)
        if trace_id:
            conditions.append("trace_id = %s")
            params.append(trace_id)
        if actor:
            conditions.append("actor = %s")
            params.append(actor)
        if success is not None:
            conditions.append("success = %s")
            params.append(success)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)

        with get_cursor() as cur:
            cur.execute(f"""
                SELECT audit_id, trace_id, actor, tool_name, tool_input, tool_output,
                       reason, duration_ms, success, error_message, created_at
                FROM tool_audit
                {where_clause}
                ORDER BY created_at DESC
                LIMIT %s
            """, params)
            rows = cur.fetchall()

        return {
            "audit_log": [
                {
                    **dict(row),
                    "created_at": row["created_at"].isoformat() if row["created_at"] else None
                }
                for row in rows
            ],
            "count": len(rows),
            "filters": {
                "tool_name": tool_name,
                "trace_id": trace_id,
                "actor": actor,
                "success": success
            }
        }
    except Exception as e:
        logger.error(f"Failed to get tool audit: {e}")
        return {"error": str(e), "audit_log": []}


@app.get("/tools/audit/stats")
def get_tool_audit_stats():
    """
    Get tool execution statistics.

    Returns counts by tool, success rates, and average durations.
    """
    try:
        from .postgres_state import get_cursor

        with get_cursor() as cur:
            # Stats by tool
            cur.execute("""
                SELECT
                    tool_name,
                    COUNT(*) as total_calls,
                    SUM(CASE WHEN success THEN 1 ELSE 0 END) as successful,
                    SUM(CASE WHEN NOT success THEN 1 ELSE 0 END) as failed,
                    ROUND(AVG(duration_ms)::numeric, 2) as avg_duration_ms
                FROM tool_audit
                GROUP BY tool_name
                ORDER BY total_calls DESC
            """)
            by_tool = cur.fetchall()

            # Overall stats
            cur.execute("""
                SELECT
                    COUNT(*) as total_executions,
                    SUM(CASE WHEN success THEN 1 ELSE 0 END) as successful,
                    SUM(CASE WHEN NOT success THEN 1 ELSE 0 END) as failed,
                    ROUND(AVG(duration_ms)::numeric, 2) as avg_duration_ms
                FROM tool_audit
            """)
            overall = cur.fetchone()

        return {
            "overall": dict(overall) if overall else {},
            "by_tool": [dict(row) for row in by_tool],
            "gate": "A",
            "description": "Tool execution audit statistics"
        }
    except Exception as e:
        logger.error(f"Failed to get tool audit stats: {e}")
        return {"error": str(e)}


# ============ Gate A: n8n Reliability Contract ============

@app.get("/n8n/contract")
def get_n8n_contract():
    """
    Get n8n Reliability Contract overview.

    Shows SLA compliance for all tracked workflows by tier.
    """
    from . import n8n_reliability as n8n_rel

    return n8n_rel.get_contract_overview()


@app.get("/n8n/contract/workflow/{workflow_name}")
def get_workflow_contract(workflow_name: str, days: int = 7):
    """
    Check SLA compliance for a specific workflow.

    Args:
        workflow_name: Name of the workflow
        days: Number of days to check (default 7)
    """
    from . import n8n_reliability as n8n_rel

    return n8n_rel.check_workflow_compliance(workflow_name, days)


@app.get("/n8n/dead-letter")
def get_dead_letter_queue(status: str = None, limit: int = 50):
    """
    Get dead letter queue items.

    Args:
        status: Filter by status (pending, retrying, resolved, abandoned)
        limit: Max items to return
    """
    from .postgres_state import get_cursor

    try:
        conditions = []
        params = []

        if status:
            conditions.append("status = %s")
            params.append(status)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)

        with get_cursor() as cur:
            cur.execute(f"""
                SELECT * FROM n8n_dead_letter
                {where_clause}
                ORDER BY created_at DESC
                LIMIT %s
            """, params)
            rows = cur.fetchall()

        return {
            "items": [
                {
                    **dict(row),
                    "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                    "resolved_at": row["resolved_at"].isoformat() if row.get("resolved_at") else None
                }
                for row in rows
            ],
            "count": len(rows),
            "filter": {"status": status}
        }
    except Exception as e:
        logger.error(f"Failed to get dead letter queue: {e}")
        return {"error": str(e), "items": []}


@app.get("/n8n/dead-letter/stats")
def get_dead_letter_stats():
    """Get dead letter queue statistics."""
    from . import n8n_reliability as n8n_rel

    return n8n_rel.get_dead_letter_stats()


@app.post("/n8n/dead-letter/resolve/{dl_id}")
def resolve_dead_letter_item(dl_id: int, success: bool = True):
    """
    Mark a dead letter item as resolved or abandoned.

    Args:
        dl_id: Dead letter item ID
        success: True for resolved, False for abandoned
    """
    from . import n8n_reliability as n8n_rel

    result = n8n_rel.resolve_dead_letter(dl_id, success)
    return {
        "dl_id": dl_id,
        "resolved": result,
        "status": "resolved" if success else "abandoned"
    }


@app.get("/n8n/sla-tiers")
def get_sla_tiers():
    """Get SLA tier definitions."""
    from . import n8n_reliability as n8n_rel
    from dataclasses import asdict

    return {
        "tiers": {
            tier: asdict(sla)
            for tier, sla in n8n_rel.SLA_TIERS.items()
        },
        "workflow_assignments": n8n_rel.WORKFLOW_TIERS,
        "description": "n8n Reliability Contract SLA definitions"
    }


# ============ Phase 18.3: Self-Improvement Endpoints ============









# ============ Prometheus Metrics Endpoint ============

@app.get("/metrics/prometheus")
def prometheus_metrics():
    """
    Prometheus metrics endpoint (text/plain format).
    Implements RED method metrics for /agent endpoint.
    
    Metrics exposed:
    - red_agent_requests_total: Total number of agent requests
    - red_agent_duration_seconds: Request latency histogram
    - red_agent_errors_total: Total request errors by type
    - circuit_breaker_state: Circuit breaker status (0=closed, 1=open)
    - connection_pool_utilization: Database pool utilization percentage
    - agent_tokens_used_total: Total tokens consumed
    - agent_tool_executions_total: Tool execution counts
    - agent_rounds_distribution: Agent loop rounds histogram
    
    Returns: Plain text Prometheus exposition format (version 0.0.4)
    """
    from prometheus_client import CollectorRegistry, generate_latest, REGISTRY
    from fastapi.responses import Response
    
    # Generate Prometheus metrics in text format
    metrics_output = generate_latest(REGISTRY)
    
    return Response(
        content=metrics_output,
        media_type="text/plain; version=0.0.4; charset=utf-8"
    )


# ============ Stresstest Utilities ============

@app.post("/stresstest/phase/complete")
def complete_stresstest_phase(request: PhaseCompleteRequest):
    """
    Mark a stresstest phase as complete and flush Langfuse traces.

    Use this between phases to ensure traces are persisted.
    """
    from .langfuse_integration import flush_traces, get_langfuse_status

    phase = request.phase or "unknown"
    langfuse_status = get_langfuse_status()
    traces_flushed = False
    flush_error = None

    if request.flush:
        if langfuse_status.get("connected"):
            try:
                flush_traces()
                traces_flushed = True
            except Exception as e:
                flush_error = str(e)
        else:
            flush_error = "Langfuse not connected"

    log_with_context(
        logger,
        "info",
        "Stresstest phase completed",
        phase=phase,
        traces_flushed=traces_flushed,
        langfuse_connected=langfuse_status.get("connected"),
    )

    response = {
        "status": "phase_complete",
        "phase": phase,
        "traces_flushed": traces_flushed,
        "langfuse": langfuse_status,
    }
    if request.metadata:
        response["metadata"] = request.metadata
    if flush_error:
        response["flush_error"] = flush_error

    return response


# ============ Maintenance & Combined Features ============

@app.post("/maintenance/check_and_restart")
def check_and_restart_unhealthy_containers(rate_limit: Any = Depends(rate_limit_dependency)):
    """Check Docker containers and restart unhealthy ones."""
    try:
        # Get container status
        status_result = ssh_client.execute_command("docker ps --format '{{.Names}}:{{.Status}}'")
        
        if not status_result["success"]:
            return {"success": False, "error": "Failed to get container status"}
        
        restarted = []
        errors = []
        
        for line in status_result["stdout"].strip().split("\n"):
            if ":" in line:
                name, status = line.split(":", 1)
                if "unhealthy" in status.lower() and "jarvis-core" in name:
                    # Extract service name
                    service = name.replace("jarvis-core-", "").replace("-1", "")
                    restart_result = ssh_client.restart_jarvis_service(service)
                    
                    if restart_result["success"]:
                        restarted.append(service)
                    else:
                        errors.append(f"{service}: {restart_result.get('error')}")
        
        return {
            "success": True,
            "restarted": restarted,
            "errors": errors,
            "checked_at": datetime.now().isoformat()
        }
        
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/maintenance/backup_status")
def get_backup_status(rate_limit: Any = Depends(rate_limit_dependency)):
    """Check backup directory and recent backups."""
    try:
        # Check backup directory
        result = ssh_client.execute_command("ls -la /brain/backup/*.sql 2>/dev/null | tail -5")
        
        if result["success"]:
            backups = []
            for line in result["stdout"].strip().split("\n"):
                if line and ".sql" in line:
                    parts = line.split()
                    if len(parts) >= 9:
                        backups.append({
                            "file": parts[-1],
                            "size": parts[4],
                            "date": f"{parts[5]} {parts[6]} {parts[7]}"
                        })
            
            return {
                "success": True,
                "recent_backups": backups,
                "backup_dir": "/brain/backup"
            }
        else:
            return {"success": False, "error": "No backups found or directory not accessible"}
            
    except Exception as e:
        return {"success": False, "error": str(e)}
    """Update a user's competency level."""
    try:
        from . import competency_model
        success = competency_model.update_competency(
            user_id=user_id,
            domain_id=domain_id,
            competency_name=competency_name,
            new_level=new_level,
            evidence=evidence
        )
        return {"status": "success" if success else "failed"}
    except Exception as e:
        return {"status": "error", "error": str(e)}
