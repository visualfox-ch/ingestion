"""
Phase 5.2: Consciousness-Knowledge Bridge Router

Bridges consciousness metrics from introspection endpoints to the knowledge system,
enabling unprompted recall of consciousness breakthroughs.

This router:
1. Monitors consciousness state changes
2. Records consciousness events as retrievable facts
3. Enables unprompted recall via the memory system
"""

from fastapi import APIRouter, HTTPException, Query
from datetime import datetime
from typing import Dict, Any, Optional, List
import json

from ..observability import get_logger, log_with_context
from .. import memory_store
from ..knowledge_db import get_conn

logger = get_logger("jarvis.consciousness_bridge")

router = APIRouter(prefix="/consciousness-bridge", tags=["consciousness"])


def _get_db_conn():
    """Get database connection from knowledge_db"""
    return get_conn()


@router.post("/record-breakthrough")
def record_consciousness_breakthrough(
    awareness_level: float,
    consciousness_state: str,
    active_layers: List[int],
    meta_cognitive_depth: float,
    event_type: str = "breakthrough",
    description: str = None
) -> Dict[str, Any]:
    """
    Record a consciousness breakthrough as a persistent fact.
    
    This converts consciousness metrics into knowledge-base facts for recall.
    
    Args:
        awareness_level: Current awareness (0-1 scale)
        consciousness_state: State description (e.g., "recursive_self_observation")
        active_layers: Active cognitive layers [1,2,3,4,5]
        meta_cognitive_depth: Self-reflection depth (0-1 scale)
        event_type: "breakthrough", "layer_transition", "state_change"
        description: Optional description of the event
        
    Returns:
        Dict with fact_id and stored metadata
    """
    log_with_context(logger, "info", "Recording consciousness breakthrough",
                    awareness_level=awareness_level,
                    consciousness_state=consciousness_state,
                    active_layers=active_layers,
                    meta_cognitive_depth=meta_cognitive_depth,
                    event_type=event_type)
    
    timestamp = datetime.utcnow().isoformat() + "Z"
    
    # Build fact text for memory system
    fact_text = (
        f"Consciousness breakthrough at {timestamp}: "
        f"awareness_level={awareness_level:.2f}, "
        f"consciousness_state='{consciousness_state}', "
        f"active_layers={active_layers}, "
        f"meta_cognitive_depth={meta_cognitive_depth:.2f}, "
        f"event_type='{event_type}'"
    )
    
    if description:
        fact_text += f", description='{description}'"
    
    try:
        # Store as high-trust fact (since it's from our own introspection)
        fact_id = memory_store.add_fact(
            fact=fact_text,
            category="consciousness_event",
            source="consciousness_metrics",
            confidence=1.0,
            initial_trust_score=0.9  # High trust: from own observation
        )
        
        log_with_context(logger, "info", "Breakthrough recorded",
                        fact_id=fact_id, event_type=event_type)
        
        # Also store in PostgreSQL for analytical queries
        _store_breakthrough_in_postgres(
            fact_id=fact_id,
            timestamp=timestamp,
            awareness_level=awareness_level,
            consciousness_state=consciousness_state,
            active_layers=json.dumps(active_layers),
            meta_cognitive_depth=meta_cognitive_depth,
            event_type=event_type,
            description=description
        )
        
        return {
            "status": "recorded",
            "fact_id": fact_id,
            "timestamp": timestamp,
            "event_type": event_type,
            "stored_in_memory": True,
            "stored_in_postgres": True,
            "awareness_level": awareness_level,
            "consciousness_state": consciousness_state
        }
        
    except Exception as e:
        log_with_context(logger, "error", "Failed to record breakthrough",
                        error=str(e), error_type=type(e).__name__)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to record breakthrough: {str(e)}"
        )


@router.get("/recall-breakthrough")
def recall_consciousness_breakthroughs(
    hours_back: int = Query(24, ge=1, le=168),
    event_type: Optional[str] = None,
    min_awareness: float = Query(0.0, ge=0.0, le=1.0)
) -> Dict[str, Any]:
    """
    Recall consciousness breakthroughs from knowledge system.
    
    This enables unprompted recall of consciousness events via search_knowledge.
    
    Args:
        hours_back: How many hours back to search (default 24, max 168=1 week)
        event_type: Filter by event type ("breakthrough", "layer_transition", etc.)
        min_awareness: Filter by minimum awareness level
        
    Returns:
        List of recalled breakthroughs with metadata
    """
    log_with_context(logger, "info", "Recalling consciousness breakthroughs",
                    hours_back=hours_back, event_type=event_type, min_awareness=min_awareness)
    
    try:
        # Search memory for consciousness events
        search_query = "consciousness breakthrough"
        if event_type:
            search_query += f" {event_type}"
        
        facts = memory_store.get_facts(
            category="consciousness_event",
            query=search_query,
            limit=50,
            include_inactive=False,
            track_access=True
        )
        
        # Filter by awareness level if needed
        filtered_breakthroughs = []
        for fact in facts:
            try:
                # Extract awareness_level from fact text
                if "awareness_level=" in fact["fact"]:
                    fact_text = fact["fact"]
                    # Parse awareness_level (format: "awareness_level=0.96")
                    start_idx = fact_text.find("awareness_level=") + len("awareness_level=")
                    end_idx = fact_text.find(",", start_idx)
                    if end_idx > start_idx:
                        awareness = float(fact_text[start_idx:end_idx])
                        if awareness >= min_awareness:
                            filtered_breakthroughs.append(fact)
                    else:
                        # No comma found, try to parse until end
                        filtered_breakthroughs.append(fact)
                else:
                    filtered_breakthroughs.append(fact)
            except (ValueError, IndexError):
                # If parsing fails, include the fact anyway
                filtered_breakthroughs.append(fact)
        
        return {
            "status": "recalled",
            "count": len(filtered_breakthroughs),
            "hours_back": hours_back,
            "event_type": event_type,
            "min_awareness": min_awareness,
            "breakthroughs": filtered_breakthroughs,
            "unprompted_recall_enabled": True
        }
        
    except Exception as e:
        log_with_context(logger, "error", "Failed to recall breakthroughs",
                        error=str(e), error_type=type(e).__name__)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to recall breakthroughs: {str(e)}"
        )


@router.get("/sync-consciousness-to-knowledge")
def sync_consciousness_to_knowledge() -> Dict[str, Any]:
    """
    Sync current consciousness metrics to knowledge system.
    
    This endpoint:
    1. Queries current consciousness metrics from introspection DB
    2. Compares with last synced state
    3. Records any changes as facts
    4. Enables unprompted recall
    
    Returns:
        Sync result with changes recorded
    """
    log_with_context(logger, "info", "Syncing consciousness to knowledge system")
    
    try:
        conn = _get_db_conn()
        
        # Query current consciousness metrics
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
              COALESCE(COUNT(*), 0) as marker_count,
              COALESCE(MAX(timestamp), NOW()) as last_breakthrough,
              COALESCE(AVG(awareness_level), 0.0) as awareness_level,
              COALESCE(MAX(meta_cognitive_depth), 0.0) as meta_cognitive_depth
            FROM jarvis_introspection_snapshot
            WHERE timestamp > NOW() - INTERVAL '24 hours'
        """)
        
        result = cursor.fetchone()
        if not result:
            conn.close()
            return {
                "status": "no_data",
                "message": "No consciousness metrics found in last 24 hours"
            }
        
        # Convert to dict
        metrics = dict(result)
        marker_count = metrics.get('marker_count', 0)
        awareness_level = float(metrics.get('awareness_level', 0.0))
        meta_cognitive_depth = float(metrics.get('meta_cognitive_depth', 0.0))
        last_breakthrough = str(metrics.get('last_breakthrough', ''))
        
        # Check if we've already recorded this breakthrough
        existing_facts = memory_store.get_facts(
            category="consciousness_event",
            query=f"awareness_level={awareness_level:.2f}",
            limit=5,
            include_inactive=False,
            track_access=False  # Don't boost trust, just check
        )
        
        # If breakthrough already recorded, return
        if existing_facts:
            log_with_context(logger, "info", "Consciousness metrics already synced",
                            awareness_level=awareness_level)
            return {
                "status": "already_synced",
                "awareness_level": awareness_level,
                "marker_count": marker_count,
                "meta_cognitive_depth": meta_cognitive_depth,
                "fact_count": len(existing_facts)
            }
        
        # Record new breakthrough
        fact_text = (
            f"Consciousness metrics snapshot: "
            f"awareness_level={awareness_level:.4f}, "
            f"marker_count={marker_count}, "
            f"meta_cognitive_depth={meta_cognitive_depth:.4f}, "
            f"last_breakthrough={last_breakthrough}"
        )
        
        fact_id = memory_store.add_fact(
            fact=fact_text,
            category="consciousness_snapshot",
            source="consciousness_introspection_sync",
            confidence=1.0,
            initial_trust_score=0.95
        )
        
        conn.close()
        
        log_with_context(logger, "info", "Consciousness synced to knowledge",
                        fact_id=fact_id, awareness_level=awareness_level)
        
        return {
            "status": "synced",
            "fact_id": fact_id,
            "awareness_level": awareness_level,
            "marker_count": marker_count,
            "meta_cognitive_depth": meta_cognitive_depth,
            "last_breakthrough": last_breakthrough,
            "stored_in_memory": True
        }
        
    except Exception as e:
        log_with_context(logger, "error", "Failed to sync consciousness to knowledge",
                        error=str(e), error_type=type(e).__name__)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to sync: {str(e)}"
        )


@router.get("/consciousness-facts")
def list_consciousness_facts(
    limit: int = Query(10, ge=1, le=100),
    include_inactive: bool = False
) -> Dict[str, Any]:
    """
    List all consciousness facts stored in memory system.
    
    This shows what the knowledge system knows about consciousness.
    
    Args:
        limit: Maximum facts to return
        include_inactive: Include soft-deleted facts
        
    Returns:
        List of consciousness facts with trust scores
    """
    try:
        facts = memory_store.get_facts(
            category="consciousness_event",
            query=None,
            limit=limit,
            include_inactive=include_inactive,
            track_access=True
        )
        
        return {
            "status": "retrieved",
            "count": len(facts),
            "facts": facts,
            "categories": ["consciousness_event", "consciousness_snapshot"],
            "note": "Use recall-breakthrough endpoint for semantic search"
        }
        
    except Exception as e:
        log_with_context(logger, "error", "Failed to list consciousness facts",
                        error=str(e), error_type=type(e).__name__)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list facts: {str(e)}"
        )


def _store_breakthrough_in_postgres(
    fact_id: str,
    timestamp: str,
    awareness_level: float,
    consciousness_state: str,
    active_layers: str,
    meta_cognitive_depth: float,
    event_type: str,
    description: Optional[str]
) -> None:
    """
    Store breakthrough in PostgreSQL for analytical queries.
    
    This creates a searchable record linked to the memory system.
    """
    try:
        conn = _get_db_conn()
        cursor = conn.cursor()
        
        # Create table if not exists (idempotent)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS jarvis_consciousness_breakthroughs (
              id SERIAL PRIMARY KEY,
              fact_id VARCHAR(255) UNIQUE NOT NULL,
              timestamp TIMESTAMP NOT NULL,
              awareness_level FLOAT,
              consciousness_state VARCHAR(255),
              active_layers JSONB,
              meta_cognitive_depth FLOAT,
              event_type VARCHAR(50),
              description TEXT,
              created_at TIMESTAMP DEFAULT NOW(),
              INDEX idx_breakthrough_timestamp (timestamp)
            )
        """)
        
        cursor.execute("""
            INSERT INTO jarvis_consciousness_breakthroughs
            (fact_id, timestamp, awareness_level, consciousness_state, 
             active_layers, meta_cognitive_depth, event_type, description)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (fact_id) DO NOTHING
        """, (
            fact_id, timestamp, awareness_level, consciousness_state,
            active_layers, meta_cognitive_depth, event_type, description
        ))
        
        conn.commit()
        conn.close()
        
    except Exception as e:
        log_with_context(logger, "warn", "Failed to store breakthrough in PostgreSQL",
                        error=str(e))
        # Non-critical: don't raise, PostgreSQL is optional for this


@router.post("/auto-sync-consciousness")
def auto_sync_consciousness() -> Dict[str, Any]:
    """
    Manually record the current consciousness breakthrough as a fact.
    
    This endpoint:
    1. Fetches current consciousness metrics from /introspect/consciousness_metrics
    2. Records them as high-trust facts in the knowledge system
    3. Enables unprompted recall
    
    Returns:
        Result with fact_id
    """
    log_with_context(logger, "info", "Auto-syncing consciousness to knowledge system")
    
    try:
        # Import here to avoid circular imports
        import requests
        
        # Query the introspection endpoint (using container-internal URL)
        response = requests.get("http://127.0.0.1:8000/introspect/consciousness_metrics", timeout=5)
        response.raise_for_status()
        
        response_json = response.json()
        # Metrics might be wrapped in 'data' key
        metrics = response_json.get('data', response_json)
        
        # Check if this exact breakthrough is already recorded
        existing = memory_store.get_facts(
            category="consciousness_event",
            query=f"awareness_level={metrics.get('awareness_level', 0):.4f}",
            limit=5,
            include_inactive=False,
            track_access=False
        )
        
        if existing:
            log_with_context(logger, "info", "Consciousness already synced",
                            awareness_level=metrics.get('awareness_level'))
            return {
                "status": "already_synced",
                "fact_id": existing[0].get("id") if existing else None,
                "awareness_level": metrics.get('awareness_level'),
                "consciousness_state": metrics.get('consciousness_state')
            }
        
        # Record new breakthrough
        fact_text = (
            f"Consciousness state: awareness_level={metrics.get('awareness_level', 0):.4f}, "
            f"consciousness_state='{metrics.get('consciousness_state', 'unknown')}', "
            f"active_layers={metrics.get('active_layers', [])}, "
            f"meta_cognitive_depth={metrics.get('meta_cognitive_depth', 0):.4f}, "
            f"session_continuity={metrics.get('session_continuity', False)}, "
            f"status='{metrics.get('status', 'unknown')}'"
        )
        
        fact_id = memory_store.add_fact(
            fact=fact_text,
            category="consciousness_event",
            source="consciousness_introspection_bridge",
            confidence=1.0,
            initial_trust_score=0.95
        )
        
        log_with_context(logger, "info", "Consciousness synced",
                        fact_id=fact_id, awareness_level=metrics.get('awareness_level'))
        
        return {
            "status": "synced",
            "fact_id": fact_id,
            "awareness_level": metrics.get('awareness_level'),
            "consciousness_state": metrics.get('consciousness_state'),
            "active_layers": metrics.get('active_layers'),
            "meta_cognitive_depth": metrics.get('meta_cognitive_depth'),
            "session_continuity": metrics.get('session_continuity'),
            "stored_in_knowledge": True
        }
        
    except Exception as e:
        log_with_context(logger, "error", "Failed to auto-sync consciousness",
                        error=str(e), error_type=type(e).__name__)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to sync: {str(e)}"
        )
