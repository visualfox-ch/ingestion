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
from .models import ScopeRef
from .domain_separation import get_default_scope

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
from .routers.dashboard_router import router as dashboard_router
from .routers.notifications_router import router as notifications_router
from .routers.memory_router import router as memory_router
from .routers.memory_metrics_router import router as memory_metrics_router
from .routers.memory_feedback_router import router as memory_feedback_router
from .routers.workflow_router import router as workflow_router
from .routers.scan_router import router as scan_router
from . import rag_regression
from .routers.feature_flags_router import router as feature_flags_router
from .routers.knowledge_router import router as knowledge_router
from .routers.feedback_router import router as feedback_router
from .routers.self_router import router as self_router
from .learning_routes import router as learning_routes_router
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
from .routers.phase2_gate_router import router as phase2_gate_router
from .routers.skill_router import router as skill_router
from .routers.workflow_skill_router import router as workflow_skill_router
from .routers.voice_router import router as voice_router
from .routers.cost_router import router as cost_router
from .routers.discord_import_router import router as discord_import_router
from .routers.whatsapp_router import router as whatsapp_router
from .routers.discord_bot_router import router as discord_bot_router
from .routers.clawwork_router import router as clawwork_router
from .routers.memory_intelligence_router import router as memory_intelligence_router

from .routers.memory_maintenance_router import router as memory_maintenance_router
from .routers.memory_alerting_router import router as memory_alerting_router
from .routers.optimization_router import router as optimization_router
from .routers.n8n_router import router as n8n_router
from .routers.admin_router import router as admin_router
from .routers.remediation_router import router as remediation_router
from .routers.salience_router import router as salience_router
from .routers.tasks_router import router as tasks_router
from .routers.user_router import router as user_router
from .routers.code_router import router as code_router
from .routers.connectors_router import router as connectors_router
from .routers.prompts_router import router as prompts_router
from .routers.prompts_router import blueprints_router, ab_tests_router
from .routers.actions_router import router as actions_router
from .routers.timeline_router import router as timeline_router
from .routers.projects_router import router as projects_router
from .routers.calendar_router import router as calendar_router
from .routers.ssh_router import router as ssh_router
from .routers.search_router import router as search_router
from .routers.entities_router import router as entities_router
from .routers.self_validation_router import router as self_validation_router
from .routers.data_import_router import router as data_import_router
from .routers.dynamic_config_router import router as dynamic_config_router
from .routers.config_router import router as config_router
from .routers.sandbox_router import router as sandbox_router
from .routers.learning_router import router as learning_router
from .routers.tool_registry_router import router as tool_registry_router
from .routers.prompt_fragments_router import router as prompt_fragments_router
from .routers.autonomy_dashboard_router import router as autonomy_dashboard_router
from .routers.linkedin_knowledge_router import (
    router as linkedin_knowledge_router,
    visualfox_router,
    knowledge_router as linkedin_knowledge_combined_router
)
from .routers.kb_router import router as kb_router

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
app.include_router(dashboard_router)
app.include_router(notifications_router)
app.include_router(workflow_router)
app.include_router(memory_router)
app.include_router(memory_metrics_router)
app.include_router(memory_feedback_router)
app.include_router(scan_router)
app.include_router(feature_flags_router)
app.include_router(knowledge_router)
app.include_router(feedback_router)
app.include_router(self_router)
app.include_router(learning_routes_router)
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
app.include_router(phase2_gate_router)
app.include_router(skill_router)
app.include_router(workflow_skill_router)
app.include_router(voice_router)
app.include_router(cost_router)
app.include_router(discord_import_router)
app.include_router(whatsapp_router)
app.include_router(discord_bot_router)
app.include_router(clawwork_router)

app.include_router(memory_intelligence_router)
app.include_router(memory_maintenance_router)
app.include_router(memory_alerting_router)
app.include_router(data_import_router)
app.include_router(optimization_router)
app.include_router(n8n_router)
app.include_router(admin_router)
app.include_router(remediation_router)
app.include_router(salience_router)
app.include_router(tasks_router)
app.include_router(user_router)
app.include_router(code_router)
app.include_router(connectors_router)
app.include_router(prompts_router)
app.include_router(blueprints_router)
app.include_router(ab_tests_router)
app.include_router(actions_router)
app.include_router(timeline_router)
app.include_router(projects_router)
app.include_router(calendar_router)
app.include_router(ssh_router)
app.include_router(search_router)
app.include_router(entities_router)
app.include_router(self_validation_router)
app.include_router(config_router)
app.include_router(dynamic_config_router)  # Phase 21: Dynamic configs
app.include_router(sandbox_router)
app.include_router(learning_router)
app.include_router(tool_registry_router)
app.include_router(prompt_fragments_router)
app.include_router(autonomy_dashboard_router)  # Phase 19.6: Autonomy Dashboard
app.include_router(linkedin_knowledge_router)  # LinkedIn Knowledge Base (legacy)
app.include_router(visualfox_router)  # visualfox Knowledge Base (legacy)
app.include_router(linkedin_knowledge_combined_router)  # Combined Knowledge Base (legacy)
app.include_router(kb_router)  # DB-gesteuerte Knowledge Base (neu)

# =============================================================================
# MEMORY PROFILING ENDPOINT (PRE-Sprint Task C - Copilot)
# =============================================================================
@app.get("/monitoring/memory")
async def memory_stats():
    """
    Memory profiling endpoint for leak detection.
    Returns top memory allocations + GC stats.
    """
    try:
        import tracemalloc
        import psutil
        import gc
        
        # Get process handle
        process = psutil.Process()
        
        # Trigger garbage collection
        gc.collect()
        
        # Take memory snapshot
        if not tracemalloc.is_tracing():
            tracemalloc.start()
        
        snapshot = tracemalloc.take_snapshot()
        top_stats = snapshot.statistics('lineno')
        
        return {
            "timestamp": datetime.now(pytz.UTC).isoformat(),
            "memory": {
                "rss_mb": round(process.memory_info().rss / 1024 / 1024, 2),
                "vms_mb": round(process.memory_info().vms / 1024 / 1024, 2),
                "percent": round(process.memory_percent(), 2)
            },
            "top_10_allocations": [
                {
                    "file": str(stat.traceback).split('", ')[0].replace('<traceback at 0x', '').strip('"'),
                    "size_mb": round(stat.size / 1024 / 1024, 2),
                    "size_kb": round(stat.size / 1024, 2),
                    "count": stat.count
                }
                for stat in top_stats[:10]
            ],
            "gc_stats": {
                "collections": gc.get_count(),
                "garbage": len(gc.garbage),
                "thresholds": gc.get_threshold()
            },
            "total_allocated_mb": round(sum(stat.size for stat in top_stats) / 1024 / 1024, 2)
        }
    except Exception as e:
        logger.error(f"Memory profiling error: {e}", exc_info=True)
        return {
            "error": str(e),
            "message": "Memory profiling unavailable"
        }

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

def now_iso() -> str:
    """Return current UTC timestamp in ISO8601 format with Z suffix."""
    return datetime.utcnow().isoformat() + "Z"

# =============================================================================
# /agent request model + helpers (stability)
# =============================================================================
class AgentRequest(BaseModel):
    query: str
    namespace: Optional[str] = None      # Deprecated: use scope instead
    scope: Optional[ScopeRef] = None    # New: replaces namespace
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
    is_session_start: bool = False  # Phase 20: Triggers full context loading
    # Vision support (Jarvis Wish)
    images: Optional[List[Dict[str, str]]] = None  # [{"type": "base64", "media_type": "image/jpeg", "data": "..."}]

    def get_scope(self) -> ScopeRef:
        """Return scope, falling back to legacy namespace or channel defaults."""
        if self.scope is not None:
            return self.scope

        if self.namespace is not None and str(self.namespace).strip():
            return ScopeRef.from_legacy_namespace(self.namespace)

        default_scope = get_default_scope(self.source or "api")
        return ScopeRef(
            org=default_scope.get("org", "projektil"),
            visibility=default_scope.get("visibility", "internal"),
            owner=default_scope.get("owner", "michael_bohl"),
        )

    def get_namespace(self) -> str:
        """Return the effective legacy namespace for backward-compatible code paths."""
        return self.get_scope().to_legacy_namespace()


class PhaseCompleteRequest(BaseModel):
    phase: Optional[str] = None
    flush: bool = True
    metadata: Optional[Dict[str, Any]] = None


def _validate_agent_request(req: "AgentRequest") -> Optional[str]:
    if req.scope is None and req.namespace is not None and not str(req.namespace).strip():
        return "namespace or scope is required"

    resolved_namespace = req.get_namespace()
    if not req.query or not str(req.query).strip():
        return "query is required"
    if len(req.query) > 20000:
        return "query too large"
    if not resolved_namespace or not str(resolved_namespace).strip():
        return "namespace or scope is required"
    if len(resolved_namespace) > 100:
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
    import tracemalloc

    # Enable tracemalloc for memory profiling endpoint
    if not tracemalloc.is_tracing():
        tracemalloc.start()
        logger.info("Memory profiling (tracemalloc) enabled")

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

    # Phase 19.5: Initialize tool registry from code
    try:
        from .services.tool_registry import sync_tools_from_code
        from .tools import get_tool_definitions
        result = sync_tools_from_code(get_tool_definitions())
        logger.info(f"Tool registry synced: {result.get('synced', 0)} synced, {result.get('new_tools', 0)} new")
    except Exception as e:
        logger.warning(f"Failed to sync tool registry: {e}")

    # Phase 19.5: Initialize prompt fragments
    try:
        from .services.prompt_fragments import init_default_fragments
        result = init_default_fragments()
        logger.info(f"Prompt fragments initialized: {result.get('inserted', 0)} new")
    except Exception as e:
        logger.warning(f"Failed to init prompt fragments: {e}")

    # Phase 19.6: Sync Tool Autonomy DB from code definitions
    try:
        from .services.tool_autonomy import get_tool_autonomy_service
        from .tools import TOOL_DEFINITIONS
        autonomy_service = get_tool_autonomy_service()
        sync_result = autonomy_service.sync_tools_from_code(TOOL_DEFINITIONS)
        logger.info(f"Tool Autonomy sync: {sync_result.get('count', 0)} tools synced")
    except Exception as e:
        logger.warning(f"Failed to sync Tool Autonomy: {e}")

    # Initialize LLM optimization metrics exporter (O1-O6)
    try:
        from .prometheus_exporter import get_prometheus_exporter
        exporter = get_prometheus_exporter()
        logger.info("LLM optimization metrics exporter initialized")
    except Exception as e:
        logger.warning(f"Failed to init LLM metrics exporter: {e}")

    start_bot_background()
    start_scheduler()

    # Phase 19.1: Start auto session persist background cleanup
    try:
        from .services.auto_session_persist import get_auto_session_persist
        auto_persist = get_auto_session_persist()
        auto_persist.start_background_cleanup(interval_minutes=10)
        logger.info("Auto session persist background cleanup started")
    except Exception as e:
        logger.warning(f"Failed to start auto session persist: {e}")

    # Phase 19.2: Start auto context summarizer background sync
    try:
        from .services.auto_context_summarizer import get_auto_context_summarizer
        auto_summarizer = get_auto_context_summarizer()
        auto_summarizer.start_background_sync(interval_minutes=30)
        logger.info("Auto context summarizer background sync started")
    except Exception as e:
        logger.warning(f"Failed to start auto context summarizer: {e}")

    # Phase 19.4: Start memory lifecycle background jobs (consolidation, pattern detection)
    try:
        from .services.memory_lifecycle import get_memory_lifecycle_service
        memory_lifecycle = get_memory_lifecycle_service()
        memory_lifecycle.start_background_jobs(consolidation_interval_hours=24)
        logger.info("Memory lifecycle background jobs started")
    except Exception as e:
        logger.warning(f"Failed to start memory lifecycle service: {e}")

    # Send minimal restart notification to Telegram
    try:
        # Check for latest update note
        update_note = ""
        try:
            update_file = "/brain/system/data/LATEST_UPDATE.txt"
            import os
            if os.path.exists(update_file):
                with open(update_file, "r") as f:
                    update_note = f.read().strip()
        except Exception:
            pass

        # Build message
        msg = "👋 Bin zurück, Micha."
        if update_note:
            msg += f"\n\n→ {update_note}"

        send_alert(msg, level="info")
        logger.info("Startup alert sent")
    except Exception as e:
        logger.warning(f"Failed to send startup alert: {e}")


# Health endpoints moved to routers/health_router.py

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
# /metrics, /metrics/system, /metrics/scientific moved to routers/metrics_router.py


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


# Coach OS profile endpoints moved to routers/memory_router.py


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
def ingest_email_embeddings(namespace: Optional[str] = None, limit_files: int = 100, skip_existing: bool = True):
    if namespace is None or not str(namespace).strip():
        default_scope = get_default_scope("api")
        namespace = ScopeRef(
            org=default_scope.get("org", "projektil"),
            visibility=default_scope.get("visibility", "internal"),
            owner=default_scope.get("owner", "michael_bohl"),
        ).to_legacy_namespace()
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
    request_scope = req.get_scope()
    request_namespace = req.get_namespace()
    metrics.REQUEST_COUNT.labels(role=req.role or "default", namespace=request_namespace).inc()

    try:
        # Guardrails
        validation_error = _validate_agent_request(req)
        if validation_error:
            log_with_context(logger, "warning", "Agent request rejected", error=validation_error)
            metrics.REQUEST_ERRORS.labels(
                role=req.role or "default",
                namespace=request_namespace,
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
                    state_db.create_session(session_id, request_namespace)
                    conversation_history = state_db.get_conversation_history(session_id, limit=10)

                    result = agent.run_agent(
                        query=req.query,
                        conversation_history=conversation_history,
                        namespace=request_namespace,
                        scope=request_scope,
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
                        is_session_start=req.is_session_start,  # Phase 20
                        images=req.images,  # Vision support
                    )

                    uncertainty = _derive_agent_uncertainty(result.get("tool_calls", []))
                    _record_latest_agent_uncertainty(req.query, uncertainty)

                    # Metrics: Record token usage and agent rounds
                    metrics.record_token_usage(
                        role=req.role or "default",
                        namespace=request_namespace,
                        input_tokens=result["usage"]["input_tokens"],
                        output_tokens=result["usage"]["output_tokens"]
                    )
                    metrics.record_agent_rounds(
                        role=req.role or "default",
                        namespace=request_namespace,
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
                        "bulk_memory_sync": result.get("bulk_memory_sync", False),
                        "qdrant_registered": result.get("qdrant_registered"),
                        "qdrant_results": result.get("qdrant_results", {}),
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
        state_db.create_session(session_id, request_namespace)

        # Load conversation history
        conversation_history = state_db.get_conversation_history(session_id, limit=10)

        # Run agent
        result = agent.run_agent(
            query=req.query,
            conversation_history=conversation_history,
            namespace=request_namespace,
            scope=request_scope,
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
            max_rounds=config.AGENT_MAX_ROUNDS,
            is_session_start=req.is_session_start,  # Phase 20: Cross-session persistence
            images=req.images,  # Vision support
        )

        uncertainty = _derive_agent_uncertainty(result.get("tool_calls", []))
        _record_latest_agent_uncertainty(req.query, uncertainty)

        # Metrics: Record token usage and agent rounds
        metrics.record_token_usage(
            role=req.role or "default",
            namespace=request_namespace,
            input_tokens=result["usage"]["input_tokens"],
            output_tokens=result["usage"]["output_tokens"]
        )
        metrics.record_agent_rounds(
            role=req.role or "default",
            namespace=request_namespace,
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
            "bulk_memory_sync": result.get("bulk_memory_sync", False),
            "qdrant_registered": result.get("qdrant_registered"),
            "qdrant_results": result.get("qdrant_results", {}),
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
        metrics.REQUEST_DURATION.labels(role=req.role or "default", namespace=request_namespace).observe(duration)

        return response

    except HTTPException:
        # Record duration and re-raise HTTP exceptions
        duration = time.time() - start_time
        metrics.REQUEST_DURATION.labels(role=req.role or "default", namespace=request_namespace).observe(duration)
        raise
    except Exception as e:
        # Record error and duration
        duration = time.time() - start_time
        metrics.REQUEST_DURATION.labels(role=req.role or "default", namespace=request_namespace).observe(duration)
        metrics.REQUEST_ERRORS.labels(
            role=req.role or "default",
            namespace=request_namespace,
            error_type=type(e).__name__
        ).inc()
        raise


@app.get("/agent/uncertainty/latest")
def get_agent_uncertainty_latest():
    """Return the latest uncertainty snapshot for UI polling."""
    return _latest_agent_uncertainty



@app.get("/briefing")
def get_briefing(namespace: Optional[str] = None, days: int = 1):
    """Get a daily briefing using the agent"""
    if namespace is None or not str(namespace).strip():
        default_scope = get_default_scope("api")
        namespace = ScopeRef(
            org=default_scope.get("org", "projektil"),
            visibility=default_scope.get("visibility", "internal"),
            owner=default_scope.get("owner", "michael_bohl"),
        ).to_legacy_namespace()
    result = agent.get_daily_briefing(namespace=namespace, days=days)
    return result


@app.get("/roles")
def list_roles():
    """List available agent roles/personas"""
    from .roles import list_roles as get_roles
    return {"roles": get_roles()}



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
# n8n Integration moved to routers/n8n_router.py


# SendEmailRequest and /n8n/gmail moved to routers/n8n_router.py


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
    namespace: Optional[str] = None


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
    namespace = req.namespace
    if not namespace:
        default_scope = get_default_scope("api")
        namespace = ScopeRef(
            org=default_scope.get("org", "projektil"),
            visibility=default_scope.get("visibility", "internal"),
            owner=default_scope.get("owner", "michael_bohl"),
        ).to_legacy_namespace()
    return n8n_client.trigger_drive_sync(
        folder_id=req.folder_id,
        limit=req.limit,
        namespace=namespace
    )


@app.get("/n8n/drive/status")
def n8n_drive_status():
    """Get Google Drive sync status and capabilities."""
    from . import n8n_client
    return n8n_client.get_drive_sync_status()


class GmailSyncRequest(BaseModel):
    limit: int = 50
    batch_size: int = 50  # Dynamic batching: starts at 50, reduces on rate limits
    namespace: Optional[str] = None
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

    namespace = req.namespace
    if not namespace:
        default_scope = get_default_scope("api")
        namespace = ScopeRef(
            org=default_scope.get("org", "projektil"),
            visibility=default_scope.get("visibility", "internal"),
            owner=default_scope.get("owner", "michael_bohl"),
        ).to_legacy_namespace()

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
        email_dir = PARSED_DIR / namespace / "email" / "inbox"
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
                    namespace,
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
    namespace: Optional[str] = None,
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
    if namespace is None or not str(namespace).strip():
        default_scope = get_default_scope("api")
        namespace = ScopeRef(
            org=default_scope.get("org", "projektil"),
            visibility=default_scope.get("visibility", "internal"),
            owner=default_scope.get("owner", "michael_bohl"),
        ).to_legacy_namespace()
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


# NOTE: Admin endpoints migrated to routers/admin_router.py (11 endpoints)
# - /admin/migrate/sqlite, /admin/migrate/connectors, /admin/init-schema
# - /admin/state/postgres, /admin/reset, /admin/data-inventory
# - /admin/import/personas, /admin/import/modes, /admin/import/policies
# - /admin/capabilities, /admin/refresh


# ============ CRUD Endpoints for Personas/Modes/Policies ============
# NOTE: All admin endpoints moved to routers/admin_router.py (11 endpoints total)
# Removed: /admin/migrate/sqlite, /admin/migrate/connectors, /admin/init-schema
# Removed: /admin/state/postgres, /admin/reset, /admin/data-inventory
# Removed: /admin/import/personas, /admin/import/modes, /admin/import/policies
# Removed: /admin/capabilities, /admin/refresh


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
    namespace: Optional[str] = None


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

    namespace = doc.namespace
    if not namespace:
        default_scope = get_default_scope("api")
        namespace = ScopeRef(
            org=default_scope.get("org", "projektil"),
            visibility=default_scope.get("visibility", "internal"),
            owner=default_scope.get("owner", "michael_bohl"),
        ).to_legacy_namespace()

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
        "namespace": namespace,
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
                        collection=f"jarvis_{namespace}",
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
                        collection=f"jarvis_{namespace}",
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
    namespace: Optional[str] = None,
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
    if namespace is None or not str(namespace).strip():
        default_scope = get_default_scope("api")
        namespace = ScopeRef(
            org=default_scope.get("org", "projektil"),
            visibility=default_scope.get("visibility", "internal"),
            owner=default_scope.get("owner", "michael_bohl"),
        ).to_legacy_namespace()
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
    namespace: Optional[str] = None,
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
    if namespace is None or not str(namespace).strip():
        default_scope = get_default_scope("api")
        namespace = ScopeRef(
            org=default_scope.get("org", "projektil"),
            visibility=default_scope.get("visibility", "internal"),
            owner=default_scope.get("owner", "michael_bohl"),
        ).to_legacy_namespace()
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


# n8n Workflow Management moved to routers/n8n_router.py


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


# n8n Reliability Contract moved to routers/n8n_router.py


# ============ Phase 18.3: Self-Improvement Endpoints ============









# /metrics/prometheus duplicate removed - see line ~953 for the comprehensive version


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
