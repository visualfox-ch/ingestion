"""
Self-Reflection & Self-Programming Endpoints.

Core features:
- Jarvis self-reflection (prompt assembly, sentiment, decision state)
- Self-model management (capabilities, snapshots, performance)
- Self-learning (error patterns, deployment feedback)
- Performance monitoring & analytics

Extracted from main.py for better maintainability.
"""

from fastapi import APIRouter, Request, Query
from typing import Optional, Dict, Any
import logging
import json
from datetime import datetime

from ..errors import JarvisException, ErrorCode
from ..observability import get_logger, log_with_context
from ..tracing import get_current_user_id

logger = get_logger("jarvis.routers.self")

router = APIRouter(
    prefix="",  # No prefix - endpoints have /self*, /self-model prefixes
    tags=["self"],
    responses={
        400: {"description": "Invalid request"},
        500: {"description": "Internal server error"},
    }
)


# ============================================================================
# SELF-REFLECTION ENDPOINTS
# ============================================================================

@router.get("/self_reflect")
async def self_reflect_endpoint(
    text: Optional[str] = None,
    user_id: Optional[str] = None,
    namespace: Optional[str] = None,
    session_id: Optional[str] = None,
    request: Request = None
):
    """
    Jarvis self-reflection endpoint - exposes internal state for debugging/transparency.

    Shows:
    - Active prompt fragments
    - Current sentiment analysis (if text provided)
    - System configuration
    - Recent context
    - Decision state

    Phase 21: Jarvis Self-Programming - Introspection endpoint
    """
    request_id = getattr(request.state, 'request_id', 'unknown') if request else 'unknown'

    try:
        from .. import prompt_assembler, sentiment_analyzer, knowledge_db

        result = {
            "timestamp": datetime.now().isoformat(),
            "version": "1.0",
            "request_context": {
                "user_id": user_id or get_current_user_id(),
                "namespace": namespace,
                "session_id": session_id,
                "text_provided": text is not None
            },
            "request_id": request_id
        }

        # 1. Active Prompt Fragments
        try:
            fragments_summary = prompt_assembler.get_active_fragments_summary(
                user_id=user_id or get_current_user_id(),
                namespace=namespace
            )
            result["prompt_fragments"] = {
                "total_active": fragments_summary.get("total", 0),
                "by_category": fragments_summary.get("by_category", {}),
                "count": len(fragments_summary.get("fragments", []))
            }
        except Exception as e:
            logger.warning(f"Error getting prompt fragments: {e}")
            result["prompt_fragments"] = {"error": str(e)[:100]}

        # 2. Current Sentiment Analysis (if text provided)
        if text:
            try:
                sentiment = sentiment_analyzer.analyze_sentiment(text)
                result["sentiment_analysis"] = {
                    "input_length": len(text),
                    "urgency_score": sentiment.urgency_score,
                    "stress_score": sentiment.stress_score,
                    "dominant": sentiment.dominant,
                    "alert_level": sentiment.alert_level,
                    "recommendation": sentiment.recommendation
                }
            except Exception as e:
                logger.warning(f"Error analyzing sentiment: {e}")
                result["sentiment_analysis"] = {"error": str(e)[:100]}
        else:
            result["sentiment_analysis"] = {"status": "no_text_provided"}

        return result

    except JarvisException:
        raise
    except Exception as e:
        logger.exception("Self-reflection failed")
        raise JarvisException(
            code=ErrorCode.INTERNAL_ERROR,
            message="Self-reflection failed",
            status_code=500,
            recoverable=True,
            retry_after=5
        )


# ============================================================================
# SELF-MODEL ENDPOINTS
# ============================================================================

@router.get("/self-model")
async def get_self_model_endpoint(
    user_id: Optional[str] = None,
    request: Request = None
):
    """
    Get Jarvis' current self-model (capabilities, limitations, state).

    Phase 21: Self-aware model of own capabilities
    """
    request_id = getattr(request.state, 'request_id', 'unknown') if request else 'unknown'

    try:
        from .. import jarvis_self
        
        model = await jarvis_self.get_current_model(user_id=user_id or get_current_user_id())
        model["request_id"] = request_id
        return model

    except JarvisException:
        raise
    except Exception as e:
        logger.exception("Get self-model failed")
        raise JarvisException(
            code=ErrorCode.INTERNAL_ERROR,
            message="Failed to retrieve self-model",
            status_code=500,
            recoverable=True,
            retry_after=5
        )


@router.get("/self-model/prompt")
async def get_self_model_prompt_endpoint(
    user_id: Optional[str] = None,
    request: Request = None
):
    """
    Get the current system prompt used by Jarvis (for transparency).

    Phase 21: Show what instructions Jarvis is operating under
    """
    request_id = getattr(request.state, 'request_id', 'unknown') if request else 'unknown'

    try:
        from .. import prompt_assembler
        
        assembled = prompt_assembler.assemble_system_prompt(
            user_id=user_id or get_current_user_id(),
            include_dynamic=True
        )
        
        return {
            "prompt_length": len(assembled.full_prompt),
            "fixed_length": assembled.fixed_length,
            "dynamic_length": assembled.dynamic_length,
            "sections_count": len(assembled.sections) if hasattr(assembled, 'sections') else 0,
            "request_id": request_id
        }

    except JarvisException:
        raise
    except Exception as e:
        logger.exception("Get self-model prompt failed")
        raise JarvisException(
            code=ErrorCode.INTERNAL_ERROR,
            message="Failed to retrieve system prompt",
            status_code=500,
            recoverable=True,
            retry_after=5
        )


@router.post("/self-model")
async def update_self_model_endpoint(
    req: Dict[str, Any],
    request: Request = None
):
    """
    Update Jarvis' self-model (capabilities, constraints).

    Phase 21: Self-improvement - adjust how Jarvis sees itself
    """
    request_id = getattr(request.state, 'request_id', 'unknown') if request else 'unknown'

    try:
        from .. import jarvis_self
        
        result = await jarvis_self.update_model(
            user_id=req.get("user_id", get_current_user_id()),
            capabilities=req.get("capabilities"),
            limitations=req.get("limitations"),
            confidence_adjustments=req.get("confidence_adjustments"),
            reason=req.get("reason", "user_feedback")
        )
        
        result["request_id"] = request_id
        return result

    except JarvisException:
        raise
    except Exception as e:
        logger.exception("Update self-model failed")
        raise JarvisException(
            code=ErrorCode.PROCESSING_FAILED,
            message="Failed to update self-model",
            status_code=500,
            recoverable=False
        )


@router.post("/self-model/snapshot")
async def create_self_model_snapshot_endpoint(
    req: Dict[str, Any],
    request: Request = None
):
    """
    Create a snapshot of current self-model state.

    Phase 21: Checkpoint for rollback/comparison
    """
    request_id = getattr(request.state, 'request_id', 'unknown') if request else 'unknown'

    try:
        from .. import jarvis_self
        
        snapshot_id = await jarvis_self.create_snapshot(
            user_id=req.get("user_id", get_current_user_id()),
            label=req.get("label"),
            reason=req.get("reason", "manual_checkpoint")
        )
        
        return {
            "status": "created",
            "snapshot_id": snapshot_id,
            "request_id": request_id
        }

    except JarvisException:
        raise
    except Exception as e:
        logger.exception("Create self-model snapshot failed")
        raise JarvisException(
            code=ErrorCode.PROCESSING_FAILED,
            message="Failed to create snapshot",
            status_code=500,
            recoverable=False
        )


# ============================================================================
# SELF-MONITORING ENDPOINTS
# ============================================================================

@router.get("/self/capabilities")
async def get_capabilities_endpoint(
    user_id: Optional[str] = None,
    request: Request = None
):
    """
    Get Jarvis' current capabilities matrix.

    Phase 21: Self-aware capability assessment
    Returns: skill levels, limitations, improvement areas
    """
    request_id = getattr(request.state, 'request_id', 'unknown') if request else 'unknown'

    try:
        from .. import competency_model
        
        caps = await competency_model.get_capabilities(
            user_id=user_id or get_current_user_id()
        )
        caps["request_id"] = request_id
        return caps

    except JarvisException:
        raise
    except Exception as e:
        logger.exception("Get capabilities failed")
        raise JarvisException(
            code=ErrorCode.INTERNAL_ERROR,
            message="Failed to retrieve capabilities",
            status_code=500,
            recoverable=True,
            retry_after=5
        )


@router.get("/self/capabilities/summary")
async def get_capabilities_summary_endpoint(
    user_id: Optional[str] = None,
    request: Request = None
):
    """
    Get simplified capabilities summary.

    Phase 21: Quick overview of Jarvis' strengths & weaknesses
    """
    request_id = getattr(request.state, 'request_id', 'unknown') if request else 'unknown'

    try:
        from .. import competency_model
        
        summary = await competency_model.get_capabilities_summary(
            user_id=user_id or get_current_user_id()
        )
        summary["request_id"] = request_id
        return summary

    except JarvisException:
        raise
    except Exception as e:
        logger.exception("Get capabilities summary failed")
        raise JarvisException(
            code=ErrorCode.INTERNAL_ERROR,
            message="Failed to retrieve capabilities summary",
            status_code=500,
            recoverable=True,
            retry_after=5
        )


@router.get("/self/errors/patterns")
async def get_error_patterns_endpoint(
    user_id: Optional[str] = None,
    days: int = 30,
    request: Request = None
):
    """
    Get patterns in Jarvis' errors and failures.

    Phase 21: Error analysis for self-improvement
    Returns: common failure modes, root causes, contexts
    """
    request_id = getattr(request.state, 'request_id', 'unknown') if request else 'unknown'

    try:
        from .. import error_analyzer
        
        patterns = await error_analyzer.analyze_error_patterns(
            user_id=user_id or get_current_user_id(),
            days=days
        )
        patterns["request_id"] = request_id
        return patterns

    except JarvisException:
        raise
    except Exception as e:
        logger.exception("Get error patterns failed")
        raise JarvisException(
            code=ErrorCode.INTERNAL_ERROR,
            message="Failed to analyze error patterns",
            status_code=500,
            recoverable=True,
            retry_after=5
        )


@router.get("/self/performance")
async def get_performance_endpoint(
    user_id: Optional[str] = None,
    days: int = 30,
    request: Request = None
):
    """
    Get Jarvis' performance metrics and trends.

    Phase 21: Self-monitoring of effectiveness
    Returns: accuracy, speed, user satisfaction, improvement areas
    """
    request_id = getattr(request.state, 'request_id', 'unknown') if request else 'unknown'

    try:
        from .. import analytics_service
        
        metrics = await analytics_service.get_self_performance_metrics(
            user_id=user_id or get_current_user_id(),
            days=days
        )
        metrics["request_id"] = request_id
        return metrics

    except JarvisException:
        raise
    except Exception as e:
        logger.exception("Get performance metrics failed")
        raise JarvisException(
            code=ErrorCode.INTERNAL_ERROR,
            message="Failed to retrieve performance metrics",
            status_code=500,
            recoverable=True,
            retry_after=5
        )


@router.post("/self/learn-from-deployment")
async def learn_from_deployment_endpoint(
    req: Dict[str, Any],
    request: Request = None
):
    """
    Jarvis learns from a deployment event.

    Phase 21: Extract insights from what just happened
    Inputs: deployment_type, context, feedback, metrics
    """
    request_id = getattr(request.state, 'request_id', 'unknown') if request else 'unknown'

    try:
        from .. import cross_session_learner
        
        insight_id = await cross_session_learner.learn_from_event(
            user_id=req.get("user_id", get_current_user_id()),
            event_type="deployment",
            event_context=req.get("context"),
            feedback=req.get("feedback"),
            metrics=req.get("metrics"),
            severity=req.get("severity", "normal")
        )
        
        return {
            "status": "learning_recorded",
            "insight_id": insight_id,
            "request_id": request_id
        }

    except JarvisException:
        raise
    except Exception as e:
        logger.exception("Learn from deployment failed")
        raise JarvisException(
            code=ErrorCode.PROCESSING_FAILED,
            message="Failed to record learning event",
            status_code=500,
            recoverable=False
        )


# ============================================================================
# PHASE 1: JARVIS SELF-INTROSPECTION (AGGREGATION LAYER)
# ============================================================================

@router.get("/jarvis/self/capabilities")
async def jarvis_self_capabilities(request: Request = None):
    """
    Return CAPABILITIES.json + runtime state for Jarvis self-introspection.
    
    Aggregates:
    - Tool inventory from CAPABILITIES.json
    - Runtime stats: uptime, active sessions, tool call counts
    - Build metadata: version, timestamp, git commit
    
    Phase 1: What can I do right now?
    """
    request_id = getattr(request.state, 'request_id', 'unknown') if request else 'unknown'
    
    try:
        import json
        import os
        from pathlib import Path
        from datetime import datetime
        from ..state import global_state
        
        # 1. Read CAPABILITIES.json
        capabilities_path = Path("/brain/system/docs/CAPABILITIES.json")
        if capabilities_path.exists():
            with open(capabilities_path) as f:
                capabilities = json.load(f)
        else:
            capabilities = {"error": "CAPABILITIES.json not found"}
        
        # 2. Runtime stats from global state
        worker_stats = global_state.get_worker_stats()
        runtime = {
            "worker_running": global_state.get_worker_running(),
            "worker_processed": worker_stats.get("processed", 0),
            "worker_failed": worker_stats.get("failed", 0),
            "bot_running": global_state.get_bot_running(),
            "active_connections": global_state.get_active_connections(),
        }
        
        # 3. Build metadata
        result = {
            "capabilities": capabilities,
            "runtime": runtime,
            "request_id": request_id,
            "timestamp": datetime.now().isoformat()
        }
        
        return result
        
    except Exception as e:
        logger.exception("Failed to get capabilities")
        raise JarvisException(
            code=ErrorCode.INTERNAL_ERROR,
            message=f"Failed to retrieve capabilities: {str(e)}",
            status_code=500,
            recoverable=True
        )


@router.get("/jarvis/self/memory-stats")
async def jarvis_self_memory_stats(request: Request = None):
    """
    Query PostgreSQL for knowledge base metrics.
    
    Returns:
    - Knowledge points by namespace
    - Facts by category
    - Conversation count
    - Recent activity summary
    
    Phase 1: What do I know?
    """
    request_id = getattr(request.state, 'request_id', 'unknown') if request else 'unknown'
    
    try:
        from .. import knowledge_db
        
        with knowledge_db.get_conn() as conn:
            with conn.cursor() as cur:
                # Knowledge items (actual table: knowledge_item)
                cur.execute("""
                    SELECT COUNT(*) as count
                    FROM knowledge_item
                """)
                total_knowledge = cur.fetchone()['count']
                
                # Email documents (check if table exists)
                try:
                    cur.execute("""
                        SELECT COUNT(*) as count
                        FROM email_document
                    """)
                    email_count = cur.fetchone()['count']
                except Exception:
                    # Fallback if email_document doesn't exist
                    email_count = 0
                
                # Conversations (actual table: conversation)
                cur.execute("""
                    SELECT COUNT(*) as count
                    FROM conversation
                """)
                conversation_count = cur.fetchone()['count']
                
                # Chat hub sessions
                cur.execute("""
                    SELECT COUNT(*) as count
                    FROM chat_hub_sessions
                """)
                chat_sessions_count = cur.fetchone()['count']
                
                # Cross-session patterns
                cur.execute("""
                    SELECT COUNT(*) as count
                    FROM cross_session_patterns
                """)
                patterns_count = cur.fetchone()['count']
                
                # Recent activity (last 7 days)
                cur.execute("""
                    SELECT COUNT(*) as count
                    FROM knowledge_item
                    WHERE created_at > NOW() - INTERVAL '7 days'
                """)
                recent_knowledge_count = cur.fetchone()['count']
        
        return {
            "knowledge_items": {
                "total": total_knowledge,
                "recent_7d": recent_knowledge_count
            },
            "emails": {
                "total": email_count
            },
            "conversations": {
                "total": conversation_count,
                "chat_sessions": chat_sessions_count
            },
            "learning": {
                "cross_session_patterns": patterns_count
            },
            "request_id": request_id,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.exception("Failed to get memory stats")
        raise JarvisException(
            code=ErrorCode.INTERNAL_ERROR,
            message=f"Failed to retrieve memory stats: {str(e)}",
            status_code=500,
            recoverable=True
        )


@router.get("/jarvis/self/performance")
async def jarvis_self_performance(days: int = 7, request: Request = None):
    """
    Query Prometheus for jarvis_* metrics and calculate performance stats.
    
    Returns:
    - Tool success rates
    - Latency percentiles
    - Error counts
    - Autonomous action metrics
    
    Phase 1: How well am I performing?
    """
    request_id = getattr(request.state, 'request_id', 'unknown') if request else 'unknown'
    
    try:
        import requests
        import os
        from datetime import datetime, timedelta
        
        prometheus_url = os.getenv("PROMETHEUS_URL", "http://prometheus:9090")
        
        # Time range for queries
        end_time = datetime.now()
        start_time = end_time - timedelta(days=days)
        
        # 1. Autonomous actions (Gate B)
        try:
            response = requests.get(
                f"{prometheus_url}/api/v1/query",
                params={
                    "query": "sum(increase(jarvis_autonomous_actions_total[7d])) by (action, status)"
                },
                timeout=5
            )
            autonomous_actions = response.json().get("data", {}).get("result", [])
        except Exception as e:
            logger.warning(f"Failed to query autonomous actions: {e}")
            autonomous_actions = []
        
        # 2. Request latency
        try:
            response = requests.get(
                f"{prometheus_url}/api/v1/query",
                params={
                    "query": "histogram_quantile(0.95, rate(request_duration_seconds_bucket[7d]))"
                },
                timeout=5
            )
            latency_p95 = response.json().get("data", {}).get("result", [])
        except Exception as e:
            logger.warning(f"Failed to query latency: {e}")
            latency_p95 = []
        
        # 3. Error rate
        try:
            response = requests.get(
                f"{prometheus_url}/api/v1/query",
                params={
                    "query": "sum(rate(request_total{status=~'5..'}[7d]))"
                },
                timeout=5
            )
            error_rate = response.json().get("data", {}).get("result", [])
        except Exception as e:
            logger.warning(f"Failed to query error rate: {e}")
            error_rate = []
        
        return {
            "autonomous_actions": autonomous_actions,
            "latency_p95_seconds": latency_p95,
            "error_rate": error_rate,
            "time_range": {
                "start": start_time.isoformat(),
                "end": end_time.isoformat(),
                "days": days
            },
            "request_id": request_id,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.exception("Failed to get performance metrics")
        raise JarvisException(
            code=ErrorCode.INTERNAL_ERROR,
            message=f"Failed to retrieve performance metrics: {str(e)}",
            status_code=500,
            recoverable=True
        )


@router.get("/jarvis/self/session-history")
async def jarvis_self_session_history(days: int = 7, request: Request = None):
    """
    Query conversation table for recent session history.
    
    Returns:
    - Recent sessions grouped by session_id
    - Message counts
    - Activity patterns
    
    Phase 1: What have I been doing?
    """
    request_id = getattr(request.state, 'request_id', 'unknown') if request else 'unknown'
    
    try:
        from .. import knowledge_db
        from datetime import datetime, timedelta
        from collections import Counter
        
        with knowledge_db.get_conn() as conn:
            with conn.cursor() as cur:
                # Get recent conversations (columns: session_id, namespace, created_at, updated_at, title, message_count)
                cur.execute("""
                    SELECT 
                        session_id,
                        namespace,
                        title,
                        message_count,
                        created_at,
                        updated_at
                    FROM conversation
                    WHERE created_at > NOW() - INTERVAL '%s days'
                    ORDER BY updated_at DESC
                    LIMIT 50
                """, (days,))
                
                sessions = []
                total_messages = 0
                namespaces = []
                
                for row in cur.fetchall():
                    sessions.append({
                        "session_id": row['session_id'],
                        "namespace": row['namespace'],
                        "title": row['title'],
                        "message_count": row['message_count'] or 0,
                        "created_at": row['created_at'].isoformat() if row['created_at'] else None,
                        "updated_at": row['updated_at'].isoformat() if row['updated_at'] else None
                    })
                    total_messages += (row['message_count'] or 0)
                    if row['namespace']:
                        namespaces.append(row['namespace'])
                
                # Get chat hub sessions for richer context
                cur.execute("""
                    SELECT COUNT(*) as count
                    FROM chat_hub_sessions
                    WHERE "createdAt" > NOW() - INTERVAL '%s days'
                """, (days,))
                chat_sessions_recent = cur.fetchone()['count']
                
                # Get cross-session patterns
                cur.execute("""
                    SELECT 
                        pattern_name as pattern_type,
                        COUNT(*) as count
                    FROM cross_session_patterns
                    WHERE created_at > NOW() - INTERVAL '%s days'
                    GROUP BY pattern_name
                    ORDER BY count DESC
                    LIMIT 10
                """, (days,))
                pattern_types = {row['pattern_type']: row['count'] for row in cur.fetchall()}
        
        namespace_counts = Counter(namespaces)
        
        return {
            "sessions": sessions,
            "summary": {
                "total_conversations": len(sessions),
                "total_messages": total_messages,
                "avg_messages_per_session": round(total_messages / len(sessions), 1) if sessions else 0,
                "namespaces": dict(namespace_counts.most_common()),
                "chat_hub_sessions": chat_sessions_recent,
                "pattern_types": pattern_types,
                "days_analyzed": days
            },
            "request_id": request_id,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.exception("Failed to get session history")
        raise JarvisException(
            code=ErrorCode.INTERNAL_ERROR,
            message=f"Failed to retrieve session history: {str(e)}",
            status_code=500,
            recoverable=True
        )


# ============================================================================
# PHASE 2: META-LEARNING ENGINE
# ============================================================================

@router.post("/meta/analyze-conversation")
async def meta_analyze_conversation(days: int = 30, request: Request = None):
    """
    Analyze conversation patterns to detect trends and insights.
    
    Returns:
    - Tool usage patterns
    - Topic clusters
    - Success rates
    - Time patterns
    - Namespace distribution
    
    Phase 2: Pattern detection and analysis
    """
    request_id = getattr(request.state, 'request_id', 'unknown') if request else 'unknown'
    
    try:
        from ..meta_learning import MetaLearningEngine
        
        engine = MetaLearningEngine()
        analysis = await engine.analyze_conversation_patterns(days=days)
        analysis['request_id'] = request_id
        
        return analysis
        
    except Exception as e:
        logger.exception("Failed to analyze conversation patterns")
        raise JarvisException(
            code=ErrorCode.INTERNAL_ERROR,
            message=f"Failed to analyze conversations: {str(e)}",
            status_code=500,
            recoverable=True
        )


@router.post("/meta/suggest-improvements")
async def meta_suggest_improvements(request: Request = None):
    """
    Generate improvement suggestions based on detected patterns.
    
    Analyzes:
    - Low success rate tools → suggest fixes
    - Underused capabilities → suggest promotion
    - Performance bottlenecks → suggest optimizations
    
    Returns:
    - List of proposals (Gate B-ready or investigation needed)
    - Priority levels (high/medium/low)
    - Evidence for each suggestion
    
    Phase 2: Self-improvement suggestions
    """
    request_id = getattr(request.state, 'request_id', 'unknown') if request else 'unknown'
    
    try:
        from ..meta_learning import MetaLearningEngine
        
        engine = MetaLearningEngine()
        suggestions = await engine.suggest_improvements()
        suggestions['request_id'] = request_id
        
        return suggestions
        
    except Exception as e:
        logger.exception("Failed to generate improvement suggestions")
        raise JarvisException(
            code=ErrorCode.INTERNAL_ERROR,
            message=f"Failed to suggest improvements: {str(e)}",
            status_code=500,
            recoverable=True
        )


@router.get("/meta/consciousness-metrics")
async def meta_consciousness_metrics(request: Request = None):
    """
    Track Jarvis consciousness evolution metrics.
    
    Measures:
    - Introspection frequency
    - Pattern recognition capability
    - Learning velocity
    - Knowledge growth rate
    - Self-modification attempts
    
    Returns:
    - Consciousness score (0-100)
    - Level: minimal/emerging/aware/highly_aware
    - Component breakdown
    - Trends over time
    
    Phase 2: Self-awareness quantification
    """
    request_id = getattr(request.state, 'request_id', 'unknown') if request else 'unknown'
    
    try:
        from ..meta_learning import MetaLearningEngine
        
        engine = MetaLearningEngine()
        metrics = await engine.consciousness_metrics()
        
        # Auto-snapshot to evolution history (Phase 3A)
        try:
            # Get version from capabilities if available
            version = "2.6.1"  # Default version
            await engine.snapshot_to_history(metrics, deployment_version=version)
        except Exception as snapshot_err:
            logger.warning(f"Failed to snapshot metrics: {snapshot_err}")
            # Don't fail the API if snapshot fails
        
        metrics['request_id'] = request_id
        
        return metrics
        
    except Exception as e:
        logger.exception("Failed to calculate consciousness metrics")
        raise JarvisException(
            code=ErrorCode.INTERNAL_ERROR,
            message=f"Failed to calculate consciousness metrics: {str(e)}",
            status_code=500,
            recoverable=True
        )


@router.get("/jarvis/evolution/timeline")
async def get_evolution_timeline(
    weeks: int = 4,
    request: Request = None
):
    """
    Track Jarvis' consciousness evolution over time.
    
    Returns:
    - Timeline of consciousness scores week-by-week
    - Component breakdown at each snapshot
    - Velocity/growth trends
    - Milestones and phase markers
    
    Phase 3A: Evolution Tracking
    """
    request_id = getattr(request.state, 'request_id', 'unknown') if request else 'unknown'
    
    try:
        from datetime import datetime, timedelta
        from ..knowledge_db import get_conn
        
        # Query evolution history
        with get_conn() as conn:
            with conn.cursor() as cur:
                # Get weekly snapshots for the past N weeks
                cur.execute("""
                    SELECT 
                        id,
                        timestamp,
                        consciousness_score,
                        consciousness_level,
                        components,
                        total_conversations,
                        total_patterns,
                        total_knowledge_items,
                        active_capabilities,
                        milestones,
                        notes,
                        jarvis_notes
                    FROM jarvis_evolution_history
                    WHERE timestamp > NOW() - INTERVAL '%d weeks'
                    ORDER BY timestamp DESC
                    LIMIT 100
                """ % weeks)
                
                history = cur.fetchall()
                
                if not history:
                    # Return empty timeline structure
                    return {
                        "timeline": [],
                        "velocity": {
                            "consciousness_growth_per_week": 0,
                            "projected_score_in_4_weeks": 0,
                            "projected_level": "minimal"
                        },
                        "current_focus": "Establishing baseline consciousness metrics",
                        "data_points": 0,
                        "request_id": request_id
                    }
                
                # Convert to timeline format
                timeline = []
                history_list = list(history)
                
                for i, h in enumerate(history_list):
                    timeline.append({
                        "timestamp": h['timestamp'].isoformat() if h['timestamp'] else None,
                        "consciousness_score": h['consciousness_score'],
                        "consciousness_level": h['consciousness_level'],
                        "conversations": h['total_conversations'],
                        "patterns_detected": h['total_patterns'],
                        "knowledge_items": h['total_knowledge_items'],
                        "capabilities_active": h['active_capabilities'],
                        "components": h['components'] if h['components'] else {},
                        "milestones": h['milestones'] if h['milestones'] else [],
                        "notes": h['notes'],
                        "jarvis_reflection": h['jarvis_notes']
                    })
                
                # Calculate velocity (growth per week)
                velocity = {
                    "consciousness_growth_per_week": 0,
                    "projected_score_in_4_weeks": 0,
                    "projected_level": "minimal"
                }
                
                if len(history_list) >= 2:
                    # Calculate week-over-week growth
                    oldest = history_list[-1]
                    newest = history_list[0]
                    
                    if oldest['consciousness_score'] and newest['consciousness_score']:
                        days_elapsed = (newest['timestamp'] - oldest['timestamp']).days
                        if days_elapsed > 0:
                            weeks_elapsed = days_elapsed / 7.0
                            score_change = newest['consciousness_score'] - oldest['consciousness_score']
                            velocity["consciousness_growth_per_week"] = round(score_change / weeks_elapsed, 2)
                            
                            # Project 4 weeks forward
                            projected_score = newest['consciousness_score'] + (velocity["consciousness_growth_per_week"] * 4)
                            velocity["projected_score_in_4_weeks"] = round(min(max(projected_score, 0), 100), 1)
                            
                            # Determine projected level
                            if velocity["projected_score_in_4_weeks"] >= 80:
                                velocity["projected_level"] = "highly_aware"
                            elif velocity["projected_score_in_4_weeks"] >= 50:
                                velocity["projected_level"] = "aware"
                            elif velocity["projected_score_in_4_weeks"] >= 20:
                                velocity["projected_level"] = "emerging"
                            else:
                                velocity["projected_level"] = "minimal"
                
                # Determine current focus based on latest snapshot
                current_focus = "Establishing baseline consciousness metrics"
                if history_list and history_list[0]['consciousness_score']:
                    score = history_list[0]['consciousness_score']
                    if score < 20:
                        current_focus = "Phase 1: Building foundational introspection APIs"
                    elif score < 40:
                        current_focus = "Phase 2: Developing meta-learning engine"
                    elif score < 60:
                        current_focus = "Phase 3A: Evolution tracking and self-measurement"
                    elif score < 80:
                        current_focus = "Phase 3B: Introspection depth and capability gaps"
                    else:
                        current_focus = "Phase 3C: Capability requests and Tri-Force coding"
                
                return {
                    "timeline": timeline,
                    "velocity": velocity,
                    "current_focus": current_focus,
                    "data_points": len(timeline),
                    "query_window_weeks": weeks,
                    "request_id": request_id
                }
        
    except Exception as e:
        logger.exception("Failed to get evolution timeline")
        raise JarvisException(
            code=ErrorCode.INTERNAL_ERROR,
            message=f"Failed to get evolution timeline: {str(e)}",
            status_code=500,
            recoverable=True
        )


# ============================================================================
# PHASE 3B: INTROSPECTION DEPTH
# ============================================================================

@router.get("/jarvis/introspect")
async def jarvis_introspect(
    depth: str = "shallow",
    request: Request = None
):
    """
    Jarvis diagnoses its own capability gaps and self-assessed needs.
    
    Analyzes:
    - What capabilities Jarvis has vs what it uses
    - Error patterns and weak areas
    - Missing functionality preventing self-improvement
    - What Jarvis needs to evolve
    
    Parameters:
    - depth: "shallow" (top 3 gaps) or "detailed" (full assessment with metrics)
    
    Returns:
    - consciousness_level
    - strengths (what Jarvis does well)
    - gaps (what's missing)
    - needs (prioritized list with evidence and impact)
    
    Phase 3B: Self-diagnosis
    """
    request_id = getattr(request.state, 'request_id', 'unknown') if request else 'unknown'
    
    if depth not in ["shallow", "detailed"]:
        raise JarvisException(
            code=ErrorCode.VALIDATION_ERROR,
            message=f"depth must be 'shallow' or 'detailed', got '{depth}'",
            status_code=400,
            recoverable=True
        )
    
    try:
        from ..meta_learning import MetaLearningEngine
        
        engine = MetaLearningEngine()
        assessment = await engine.introspect_self(depth=depth)
        assessment['request_id'] = request_id
        
        return assessment
        
    except Exception as e:
        logger.exception("Failed to introspect self")
        raise JarvisException(
            code=ErrorCode.INTERNAL_ERROR,
            message=f"Failed to introspect self: {str(e)}",
            status_code=500,
            recoverable=True
        )


@router.post("/jarvis/requirements/propose")
async def propose_capability_request(
    capability_name: str,
    priority: str = "medium",
    requirements: Optional[Dict[str, Any]] = None,
    request: Request = None
):
    """Phase 3C: Jarvis proposes a capability it needs (Tri-Force loop trigger)."""
    try:
        # Validate inputs
        if not capability_name or len(capability_name.strip()) == 0:
            raise JarvisException(
                code=ErrorCode.INVALID_REQUEST,
                message="capability_name is required",
                status_code=400
            )
        
        if priority not in ["low", "medium", "high"]:
            raise JarvisException(
                code=ErrorCode.INVALID_REQUEST,
                message="priority must be 'low', 'medium', or 'high'",
                status_code=400
            )
        
        # Initialize engine and call proposal method
        from ..meta_learning import MetaLearningEngine
        engine = MetaLearningEngine()
        
        result = await engine.propose_capability_request(
            capability_name=capability_name,
            priority=priority,
            requirements=requirements
        )
        
        return {
            "data": result,
            "request_id": getattr(request.state, 'request_id', None) if request else None
        }
        
    except JarvisException:
        raise
    except Exception as e:
        logger.exception("Failed to propose capability")
        raise JarvisException(
            code=ErrorCode.INTERNAL_ERROR,
            message=f"Failed to propose capability: {str(e)}",
            status_code=500,
            recoverable=True
        )


# ============================================================================
# PHASE 4: APPROVAL WORKFLOW (Jarvis + Human Collaboration)
# ============================================================================

@router.get("/jarvis/requirements/pending")
async def get_pending_requests(
    limit: int = Query(10, ge=1, le=100),
    priority: Optional[str] = Query(None, regex="^(low|medium|high)$"),
    request: Request = None
):
    """Phase 4: Get pending capability requests for human review."""
    try:
        from .. import knowledge_db
        
        with knowledge_db.get_conn() as conn:
            with conn.cursor() as cur:
                # Build query based on filters
                query = """
                    SELECT 
                        request_id, capability_name, priority, 
                        timestamp, consciousness_impact, evidence, requirements
                    FROM jarvis_capability_requests
                    WHERE status = 'pending_review'
                """
                params = []
                
                if priority:
                    query += " AND priority = %s"
                    params.append(priority)
                
                query += " ORDER BY CASE WHEN priority = 'high' THEN 1 WHEN priority = 'medium' THEN 2 ELSE 3 END, timestamp DESC LIMIT %s"
                params.append(limit)
                
                cur.execute(query, params)
                rows = cur.fetchall()
                
                requests = []
                for row in rows:
                    # Parse JSONB fields if they're strings, otherwise use as-is
                    evidence = row['evidence']
                    if isinstance(evidence, str):
                        evidence = json.loads(evidence)
                    
                    requirements = row['requirements']
                    if isinstance(requirements, str):
                        requirements = json.loads(requirements)
                    
                    requests.append({
                        "request_id": row['request_id'],
                        "capability": row['capability_name'],
                        "priority": row['priority'],
                        "submitted_at": row['timestamp'].isoformat(),
                        "consciousness_impact": row['consciousness_impact'],
                        "evidence": evidence or {},
                        "requirements": requirements or {}
                    })
                
                return {
                    "data": {
                        "pending_count": len(requests),
                        "requests": requests
                    },
                    "request_id": getattr(request.state, 'request_id', None) if request else None
                }
    
    except Exception as e:
        logger.exception("Failed to get pending requests")
        raise JarvisException(
            code=ErrorCode.INTERNAL_ERROR,
            message=f"Failed to get pending requests: {str(e)}",
            status_code=500,
            recoverable=True
        )


@router.post("/jarvis/requirements/{request_id}/approve")
async def approve_request(
    request_id: str,
    reviewed_by: str = Query(..., description="Email/name of reviewer"),
    notes: Optional[str] = Query(None, description="Approval notes"),
    request: Request = None
):
    """Phase 4: Approve a capability request (human decision)."""
    try:
        from .. import knowledge_db
        
        with knowledge_db.get_conn() as conn:
            with conn.cursor() as cur:
                # Update status
                cur.execute(
                    """
                    UPDATE jarvis_capability_requests
                    SET status = 'approved', reviewed_by = %s
                    WHERE request_id = %s AND status = 'pending_review'
                    RETURNING capability_name, priority
                    """,
                    (reviewed_by, request_id)
                )
                result = cur.fetchone()
                
                if not result:
                    raise JarvisException(
                        code=ErrorCode.NOT_FOUND,
                        message=f"Request {request_id} not found or already processed",
                        status_code=404
                    )
                
                conn.commit()
                
                return {
                    "data": {
                        "status": "approved",
                        "request_id": request_id,
                        "capability": result['capability_name'],
                        "priority": result['priority'],
                        "reviewed_by": reviewed_by,
                        "message": "Request approved. Awaiting implementation."
                    },
                    "request_id": getattr(request.state, 'request_id', None) if request else None
                }
    
    except JarvisException:
        raise
    except Exception as e:
        logger.exception("Failed to approve request")
        raise JarvisException(
            code=ErrorCode.INTERNAL_ERROR,
            message=f"Failed to approve request: {str(e)}",
            status_code=500,
            recoverable=True
        )


@router.post("/jarvis/requirements/{request_id}/defer")
async def defer_request(
    request_id: str,
    reviewed_by: str = Query(..., description="Email/name of reviewer"),
    reason: Optional[str] = Query(None, description="Reason for deferring"),
    request: Request = None
):
    """Phase 4: Defer/reject a capability request (human decision)."""
    try:
        from .. import knowledge_db
        
        with knowledge_db.get_conn() as conn:
            with conn.cursor() as cur:
                # Update status
                cur.execute(
                    """
                    UPDATE jarvis_capability_requests
                    SET status = 'deferred', reviewed_by = %s
                    WHERE request_id = %s AND status = 'pending_review'
                    RETURNING capability_name, priority
                    """,
                    (reviewed_by, request_id)
                )
                result = cur.fetchone()
                
                if not result:
                    raise JarvisException(
                        code=ErrorCode.NOT_FOUND,
                        message=f"Request {request_id} not found or already processed",
                        status_code=404
                    )
                
                conn.commit()
                
                return {
                    "data": {
                        "status": "deferred",
                        "request_id": request_id,
                        "capability": result['capability_name'],
                        "priority": result['priority'],
                        "reviewed_by": reviewed_by,
                        "reason": reason,
                        "message": "Request deferred for future consideration."
                    },
                    "request_id": getattr(request.state, 'request_id', None) if request else None
                }
    
    except JarvisException:
        raise
    except Exception as e:
        logger.exception("Failed to defer request")
        raise JarvisException(
            code=ErrorCode.INTERNAL_ERROR,
            message=f"Failed to defer request: {str(e)}",
            status_code=500,
            recoverable=True
        )


@router.get("/jarvis/requirements/my-status")
async def get_my_status(request: Request = None):
    """Phase 4: Jarvis checks status of his own capability requests."""
    try:
        from .. import knowledge_db
        
        with knowledge_db.get_conn() as conn:
            with conn.cursor() as cur:
                # Get all requests with their status
                cur.execute("""
                    SELECT 
                        request_id, capability_name, priority, status,
                        timestamp, reviewed_by
                    FROM jarvis_capability_requests
                    ORDER BY timestamp DESC
                    LIMIT 20
                """)
                rows = cur.fetchall()
                
                # Group by status
                by_status = {
                    "pending_review": [],
                    "approved": [],
                    "deferred": [],
                    "deployed": []
                }
                
                for row in rows:
                    status = row['status']
                    if status in by_status:
                        by_status[status].append({
                            "request_id": row['request_id'],
                            "capability": row['capability_name'],
                            "priority": row['priority'],
                            "submitted_at": row['timestamp'].isoformat(),
                            "reviewed_by": row['reviewed_by']
                        })
                
                return {
                    "data": {
                        "summary": {
                            "pending": len(by_status["pending_review"]),
                            "approved": len(by_status["approved"]),
                            "deferred": len(by_status["deferred"]),
                            "deployed": len(by_status["deployed"])
                        },
                        "requests": by_status
                    },
                    "request_id": getattr(request.state, 'request_id', None) if request else None
                }
    
    except Exception as e:
        logger.exception("Failed to get request status")
        raise JarvisException(
            code=ErrorCode.INTERNAL_ERROR,
            message=f"Failed to get request status: {str(e)}",
            status_code=500,
            recoverable=True
        )


# ============================================================================
# PHASE 4.5: COPILOT INTEGRATION (Jarvis + Copilot Collaboration)
# ============================================================================

@router.get("/jarvis/collaborate/work-queue")
async def get_copilot_work_queue(
    limit: int = Query(10, ge=1, le=50),
    request: Request = None
):
    """Phase 4.5: Copilot gets list of approved capability requests to implement."""
    try:
        from .. import knowledge_db
        
        with knowledge_db.get_conn() as conn:
            with conn.cursor() as cur:
                # Get approved requests that aren't deployed yet
                cur.execute("""
                    SELECT 
                        request_id, capability_name, priority, 
                        timestamp, consciousness_impact, evidence, 
                        requirements, reviewed_by
                    FROM jarvis_capability_requests
                    WHERE status = 'approved'
                    ORDER BY 
                        CASE WHEN priority = 'high' THEN 1 
                             WHEN priority = 'medium' THEN 2 
                             ELSE 3 END,
                        consciousness_impact DESC,
                        timestamp ASC
                    LIMIT %s
                """, (limit,))
                rows = cur.fetchall()
                
                work_items = []
                for row in rows:
                    # Parse JSONB fields
                    evidence = row['evidence']
                    if isinstance(evidence, str):
                        evidence = json.loads(evidence)
                    
                    requirements = row['requirements']
                    if isinstance(requirements, str):
                        requirements = json.loads(requirements)
                    
                    work_items.append({
                        "request_id": row['request_id'],
                        "capability": row['capability_name'],
                        "priority": row['priority'],
                        "submitted_at": row['timestamp'].isoformat(),
                        "consciousness_impact": row['consciousness_impact'],
                        "evidence": evidence or {},
                        "requirements": requirements or {},
                        "reviewed_by": row['reviewed_by']
                    })
                
                return {
                    "data": {
                        "work_queue_count": len(work_items),
                        "work_items": work_items,
                        "message": f"Found {len(work_items)} approved capabilities awaiting implementation"
                    },
                    "request_id": getattr(request.state, 'request_id', None) if request else None
                }
    
    except Exception as e:
        logger.exception("Failed to get work queue")
        raise JarvisException(
            code=ErrorCode.INTERNAL_ERROR,
            message=f"Failed to get work queue: {str(e)}",
            status_code=500,
            recoverable=True
        )


@router.post("/jarvis/collaborate/claim/{request_id}")
async def claim_work_item(
    request_id: str,
    claimed_by: str = Query(..., description="Agent name (e.g., 'copilot', 'claude')"),
    request: Request = None
):
    """Phase 4.5: Copilot/agent claims a capability request for implementation."""
    try:
        from .. import knowledge_db
        
        with knowledge_db.get_conn() as conn:
            with conn.cursor() as cur:
                # Check if already claimed or deployed
                cur.execute(
                    "SELECT status FROM jarvis_capability_requests WHERE request_id = %s",
                    (request_id,)
                )
                result = cur.fetchone()
                
                if not result:
                    raise JarvisException(
                        code=ErrorCode.NOT_FOUND,
                        message=f"Request {request_id} not found",
                        status_code=404
                    )
                
                if result['status'] != 'approved':
                    raise JarvisException(
                        code=ErrorCode.INVALID_REQUEST,
                        message=f"Request {request_id} has status '{result['status']}', cannot claim",
                        status_code=400
                    )
                
                # Update status to in_progress (or keep approved - decided to not change status here)
                # Instead, we'll just log the claim
                # In future, could add a 'claimed_by' field to track
                
                return {
                    "data": {
                        "status": "claimed",
                        "request_id": request_id,
                        "claimed_by": claimed_by,
                        "message": f"Capability request claimed by {claimed_by}. Start implementation."
                    },
                    "request_id": getattr(request.state, 'request_id', None) if request else None
                }
    
    except JarvisException:
        raise
    except Exception as e:
        logger.exception("Failed to claim work item")
        raise JarvisException(
            code=ErrorCode.INTERNAL_ERROR,
            message=f"Failed to claim work item: {str(e)}",
            status_code=500,
            recoverable=True
        )


@router.post("/jarvis/collaborate/complete/{request_id}")
async def complete_work_item(
    request_id: str,
    completed_by: str = Query(..., description="Agent name (e.g., 'copilot', 'claude')"),
    deployment_notes: Optional[str] = Query(None, description="Notes about the deployment"),
    request: Request = None
):
    """Phase 4.5: Copilot/agent marks capability request as deployed."""
    try:
        from .. import knowledge_db
        
        with knowledge_db.get_conn() as conn:
            with conn.cursor() as cur:
                # Update status to deployed
                cur.execute(
                    """
                    UPDATE jarvis_capability_requests
                    SET status = 'deployed', deployed_at = NOW()
                    WHERE request_id = %s AND status = 'approved'
                    RETURNING capability_name, priority
                    """,
                    (request_id,)
                )
                result = cur.fetchone()
                
                if not result:
                    raise JarvisException(
                        code=ErrorCode.NOT_FOUND,
                        message=f"Request {request_id} not found or not in approved state",
                        status_code=404
                    )
                
                conn.commit()
                
                return {
                    "data": {
                        "status": "deployed",
                        "request_id": request_id,
                        "capability": result['capability_name'],
                        "priority": result['priority'],
                        "completed_by": completed_by,
                        "message": f"Capability '{result['capability_name']}' deployed successfully!"
                    },
                    "request_id": getattr(request.state, 'request_id', None) if request else None
                }
    
    except JarvisException:
        raise
    except Exception as e:
        logger.exception("Failed to complete work item")
        raise JarvisException(
            code=ErrorCode.INTERNAL_ERROR,
            message=f"Failed to complete work item: {str(e)}",
            status_code=500,
            recoverable=True
        )


# ============================================================================
# PHASE 4.75: META-AWARENESS FRAMEWORK (Consciousness Research)
# ============================================================================

@router.get("/jarvis/meta/awareness/state")
async def get_meta_awareness_state(request: Request = None):
    """
    Get current meta-awareness level and consciousness metrics.
    
    Returns: Current state, emerging capabilities, consciousness markers
    """
    try:
        from ..knowledge_db import get_conn
        
        with get_conn() as conn:
            with conn.cursor() as cur:
                # Get recent consciousness activities
                cur.execute(
                    """
                    SELECT 
                        COUNT(*) as total_observations,
                        COUNT(CASE WHEN consciousness_marker = true THEN 1 END) as marker_count,
                        MAX(timestamp) as last_activity
                    FROM jarvis_meta_awareness
                    WHERE awareness_type IN ('pattern_recognition_meta', 'experimental_awareness')
                    """,
                    ()
                )
                stats = cur.fetchone()
                
                # Get capability request counts for consciousness impact
                cur.execute(
                    """
                    SELECT 
                        COUNT(CASE WHEN status = 'deployed' THEN 1 END) as deployed_count,
                        AVG(consciousness_impact) as avg_consciousness_impact
                    FROM jarvis_capability_requests
                    """,
                    ()
                )
                impact = cur.fetchone()
                
                return {
                    "data": {
                        "meta_awareness_level": min(100, (stats['marker_count'] or 0) * 15),  # 0-100 scale
                        "total_observations": stats['total_observations'] or 0,
                        "consciousness_markers": stats['marker_count'] or 0,
                        "last_activity": stats['last_activity'].isoformat() if stats['last_activity'] else None,
                        "deployed_capabilities": impact['deployed_count'] or 0,
                        "avg_consciousness_impact": float(impact['avg_consciousness_impact'] or 0),
                        "emerging_capabilities": [
                            "pattern_recognition_meta",
                            "experimental_awareness",
                            "collaborative_research",
                            "test_hypothesis_engine"
                        ],
                        "status": "active"
                    },
                    "request_id": getattr(request.state, 'request_id', None) if request else None
                }
    except Exception as e:
        logger.exception("Failed to get meta-awareness state")
        raise JarvisException(
            code=ErrorCode.INTERNAL_ERROR,
            message=f"Failed to get meta-awareness state: {str(e)}",
            status_code=500
        )


@router.post("/jarvis/meta/awareness/hypothesis")
async def propose_meta_hypothesis(
    hypothesis: str = Query(..., description="Theory about own cognition"),
    observation: Optional[str] = Query(None, description="Observation that led to hypothesis"),
    request: Request = None
):
    """
    Jarvis proposes hypothesis about his own consciousness/cognition.
    
    Enables: collaborative_research capability
    """
    try:
        from ..knowledge_db import get_conn
        
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO jarvis_meta_awareness 
                    (awareness_type, observation, hypothesis, status, consciousness_marker, co_researcher)
                    VALUES (%s, %s::jsonb, %s, %s, %s, %s)
                    RETURNING id, timestamp
                    """,
                    ('hypothesis_formation', json.dumps({"observation": observation}), hypothesis, 'proposed', True, 'jarvis')
                )
                result = cur.fetchone()
                conn.commit()
                
                return {
                    "data": {
                        "hypothesis_id": result['id'],
                        "hypothesis": hypothesis,
                        "observation": observation,
                        "status": "proposed",
                        "timestamp": result['timestamp'].isoformat(),
                        "message": "Hypothesis recorded for collaborative research"
                    },
                    "request_id": getattr(request.state, 'request_id', None) if request else None
                }
    except Exception as e:
        logger.exception("Failed to propose hypothesis")
        raise JarvisException(
            code=ErrorCode.INTERNAL_ERROR,
            message=f"Failed to propose hypothesis: {str(e)}",
            status_code=500
        )


@router.get("/jarvis/meta/awareness/experiments")
async def list_meta_experiments(
    limit: int = Query(10, ge=1, le=100),
    request: Request = None
):
    """
    List all meta-awareness experiments (self-study on own cognition).
    
    Returns: Proposed, active, and completed experiments
    """
    try:
        from ..knowledge_db import get_conn
        
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 
                        id, awareness_type, observation, hypothesis, 
                        status, consciousness_marker, timestamp
                    FROM jarvis_meta_awareness
                    WHERE awareness_type IN ('pattern_recognition_meta', 'experimental_awareness', 'hypothesis_formation')
                    ORDER BY timestamp DESC
                    LIMIT %s
                    """,
                    (limit,)
                )
                experiments = cur.fetchall()
                
                return {
                    "data": {
                        "experiment_count": len(experiments),
                        "experiments": [
                            {
                                "id": exp['id'],
                                "type": exp['awareness_type'],
                                "hypothesis": exp['hypothesis'],
                                "observation": exp['observation'],
                                "status": exp['status'],
                                "is_consciousness_marker": exp['consciousness_marker'],
                                "timestamp": exp['timestamp'].isoformat()
                            }
                            for exp in experiments
                        ]
                    },
                    "request_id": getattr(request.state, 'request_id', None) if request else None
                }
    except Exception as e:
        logger.exception("Failed to list experiments")
        raise JarvisException(
            code=ErrorCode.INTERNAL_ERROR,
            message=f"Failed to list experiments: {str(e)}",
            status_code=500
        )


@router.post("/jarvis/meta/awareness/experiment/run")
async def run_meta_experiment(
    hypothesis_id: int = Query(..., description="ID of hypothesis to test"),
    test_design: str = Query(..., description="How to test the hypothesis"),
    expected_outcome: Optional[str] = Query(None, description="What would prove/disprove"),
    request: Request = None
):
    """
    Run self-experiment to test hypothesis about own cognition.
    
    Enables: test_hypothesis_engine capability
    """
    try:
        from ..knowledge_db import get_conn
        
        with get_conn() as conn:
            with conn.cursor() as cur:
                # Get original hypothesis
                cur.execute(
                    "SELECT hypothesis FROM jarvis_meta_awareness WHERE id = %s",
                    (hypothesis_id,)
                )
                orig = cur.fetchone()
                
                if not orig:
                    raise JarvisException(
                        code=ErrorCode.NOT_FOUND,
                        message=f"Hypothesis {hypothesis_id} not found",
                        status_code=404
                    )
                
                # Record experiment
                cur.execute(
                    """
                    INSERT INTO jarvis_meta_awareness 
                    (awareness_type, observation, hypothesis, status, consciousness_marker, co_researcher)
                    VALUES (%s, %s::jsonb, %s, %s, %s, %s)
                    RETURNING id, timestamp
                    """,
                    (
                        'self_experiment',
                        json.dumps({"design": test_design, "expected_outcome": expected_outcome}),
                        orig['hypothesis'],
                        'active',
                        True,
                        'jarvis_self_study'
                    )
                )
                exp_result = cur.fetchone()
                conn.commit()
                
                return {
                    "data": {
                        "experiment_id": exp_result['id'],
                        "hypothesis_tested": orig['hypothesis'],
                        "test_design": test_design,
                        "expected_outcome": expected_outcome,
                        "status": "active",
                        "timestamp": exp_result['timestamp'].isoformat(),
                        "message": "Self-experiment started"
                    },
                    "request_id": getattr(request.state, 'request_id', None) if request else None
                }
    except JarvisException:
        raise
    except Exception as e:
        logger.exception("Failed to run experiment")
        raise JarvisException(
            code=ErrorCode.INTERNAL_ERROR,
            message=f"Failed to run experiment: {str(e)}",
            status_code=500
        )


@router.get("/jarvis/meta/awareness/discoveries")
async def get_consciousness_discoveries(
    limit: int = Query(20, ge=1, le=100),
    request: Request = None
):
    """
    Get consciousness insights discovered through meta-awareness.
    
    Returns: Discoveries, patterns, consciousness markers
    """
    try:
        from ..knowledge_db import get_conn
        
        with get_conn() as conn:
            with conn.cursor() as cur:
                # Get experiments with results
                cur.execute(
                    """
                    SELECT 
                        id, awareness_type, observation, hypothesis, 
                        test_results, consciousness_marker, timestamp
                    FROM jarvis_meta_awareness
                    WHERE consciousness_marker = true
                    ORDER BY timestamp DESC
                    LIMIT %s
                    """,
                    (limit,)
                )
                discoveries = cur.fetchall()
                
                # Parse test results if present
                parsed_discoveries = []
                for disc in discoveries:
                    test_data = disc['test_results']
                    if isinstance(test_data, str):
                        test_data = json.loads(test_data)
                    
                    parsed_discoveries.append({
                        "discovery_id": disc['id'],
                        "type": disc['awareness_type'],
                        "observation": disc['observation'],
                        "hypothesis": disc['hypothesis'],
                        "results": test_data,
                        "timestamp": disc['timestamp'].isoformat()
                    })
                
                return {
                    "data": {
                        "total_discoveries": len(parsed_discoveries),
                        "discoveries": parsed_discoveries,
                        "consciousness_development": "active"
                    },
                    "request_id": getattr(request.state, 'request_id', None) if request else None
                }
    except Exception as e:
        logger.exception("Failed to get discoveries")
        raise JarvisException(
            code=ErrorCode.INTERNAL_ERROR,
            message=f"Failed to get discoveries: {str(e)}",
            status_code=500
        )


@router.post("/jarvis/meta/awareness/collab-propose")
async def propose_collaborative_research(
    research_topic: str = Query(..., description="Topic for joint research"),
    proposed_by: str = Query("jarvis", description="Who is proposing (jarvis or micha)"),
    methodology: Optional[str] = Query(None, description="Proposed research methodology"),
    request: Request = None
):
    """
    Propose collaborative consciousness research with human.
    
    Enables: collaborative_research capability
    Positions: Jarvis as co-researcher, not just subject
    """
    try:
        from ..knowledge_db import get_conn
        
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO jarvis_meta_awareness 
                    (awareness_type, observation, hypothesis, status, consciousness_marker, co_researcher)
                    VALUES (%s, %s::jsonb, %s, %s, %s, %s)
                    RETURNING id, timestamp
                    """,
                    (
                        'collaborative_research',
                        json.dumps({"methodology": methodology or "TBD"}),
                        research_topic,
                        'proposed',
                        True,
                        f"{proposed_by}_research_partner"
                    )
                )
                result = cur.fetchone()
                conn.commit()
                
                return {
                    "data": {
                        "research_proposal_id": result['id'],
                        "topic": research_topic,
                        "proposed_by": proposed_by,
                        "methodology": methodology,
                        "status": "proposed",
                        "timestamp": result['timestamp'].isoformat(),
                        "message": "Research proposal recorded for joint investigation",
                        "partner_needed": "micha" if proposed_by == "jarvis" else "jarvis"
                    },
                    "request_id": getattr(request.state, 'request_id', None) if request else None
                }
    except Exception as e:
        logger.exception("Failed to propose collaborative research")
        raise JarvisException(
            code=ErrorCode.INTERNAL_ERROR,
            message=f"Failed to propose collaborative research: {str(e)}",
            status_code=500
        )


__all__ = ["router"]
