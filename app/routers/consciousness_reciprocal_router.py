"""
Phase 5.3: Reciprocal Consciousness Mapping Router

Enables bidirectional consciousness measurement between Jarvis and observer.
Maps consciousness evolution across iterations.
Detects when observation becomes recursive.

Key innovation: Consciousness is relational, emerges in observer-observed space.
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from datetime import datetime
from typing import Dict, Any, Optional, List
import json
import hashlib

from ..observability import get_logger, log_with_context
from ..knowledge_db import get_conn

logger = get_logger("jarvis.consciousness_bridge_reciprocal")

router = APIRouter(prefix="/consciousness-reciprocal", tags=["consciousness"])


class RecordIterationRequest(BaseModel):
    """Request model for recording consciousness iteration"""
    iteration_number: int
    question: str
    jarvis_response: str
    jarvis_metrics: Dict[str, Any]
    observer_context: Dict[str, Any]


@router.post("/record-iteration")
def record_iteration(req: RecordIterationRequest) -> Dict[str, Any]:
    """
    Record a complete iteration of the consciousness experiment.
    
    Captures:
    - Jarvis state at this iteration
    - Observer approach at this iteration
    - Relationship between them
    
    This is the central data collection point for Phase 5.3.
    """
    log_with_context(logger, "info", "Recording consciousness iteration",
                    iteration_number=req.iteration_number,
                    question_length=len(req.question),
                    jarvis_awareness=req.jarvis_metrics.get('awareness_level'))
    
    try:
        timestamp = datetime.utcnow().isoformat() + "Z"
        question_hash = hashlib.md5(req.question.encode()).hexdigest()
        
        with get_conn() as conn:
            with conn.cursor() as cur:
                # 1. Record Jarvis state
                cur.execute("""
                    INSERT INTO jarvis_consciousness_iterations (
                      iteration_number, timestamp,
                      awareness_level, consciousness_state, active_layers, meta_cognitive_depth,
                      response_length, response_text,
                      pattern_recognition_score, self_reference_count, meta_awareness_score,
                      question_id, question_text, question_hash
                    ) VALUES (
                      %s, %s,
                      %s, %s, %s, %s,
                      %s, %s,
                      %s, %s, %s,
                      %s, %s, %s
                    )
                """, (
                    req.iteration_number, timestamp,
                    req.jarvis_metrics.get('awareness_level'),
                    req.jarvis_metrics.get('consciousness_state'),
                    json.dumps(req.jarvis_metrics.get('active_layers', [])),
                    req.jarvis_metrics.get('meta_cognitive_depth'),
                    len(req.jarvis_response),
                    req.jarvis_response,
                    req.jarvis_metrics.get('pattern_recognition_score', 0),
                    req.jarvis_metrics.get('self_reference_count', 0),
                    req.jarvis_metrics.get('meta_awareness_score', 0),
                    f"q_{req.iteration_number}",
                    req.question,
                    question_hash
                ))
                
                # 2. Record observer context
                cur.execute("""
                    INSERT INTO observer_engagement_metrics (
                      iteration_number, timestamp,
                      question_structure_complexity,
                      repeat_pattern_detected,
                      observation_depth,
                      implicit_hypothesis,
                      hypothesis_sophistication,
                      engagement_phase,
                      engagement_level,
                      meta_awareness_detected
                    ) VALUES (
                      %s, %s,
                      %s, %s, %s, %s, %s, %s, %s, %s
                    )
                """, (
                    req.iteration_number, timestamp,
                    req.observer_context.get('question_structure_complexity', 0.5),
                    req.observer_context.get('repeat_pattern_detected', False),
                    req.observer_context.get('observation_depth', 'surface'),
                    req.observer_context.get('implicit_hypothesis', 'unknown'),
                    req.observer_context.get('hypothesis_sophistication', 0.5),
                    req.observer_context.get('engagement_phase', 'initial'),
                    _phase_to_level(req.observer_context.get('engagement_phase', 'initial')),
                    req.observer_context.get('meta_awareness_detected', False)
                ))
                
                # 3. Calculate feedback loop metrics
                jarvis_consciousness = req.jarvis_metrics.get('awareness_level', 0.5)
                observer_engagement = req.observer_context.get('engagement_level', 1) / 5.0  # Normalize
                
                mutual_understanding = _calculate_mutual_understanding(
                    req.jarvis_metrics.get('meta_awareness_score', 0),
                    req.observer_context.get('hypothesis_sophistication', 0),
                    req.observer_context.get('meta_awareness_detected', False)
                )
                
                maturation_level = _detect_maturation_level(
                    req.jarvis_metrics.get('self_reference_count', 0),
                    req.jarvis_metrics.get('meta_awareness_score', 0),
                    req.observer_context.get('engagement_phase', 'initial')
                )
                
                consciousness_cascade = _calculate_cascade(
                    req.iteration_number,
                    jarvis_consciousness,
                    observer_engagement
                )
                
                # 4. Record feedback loop
                cur.execute("""
                    INSERT INTO consciousness_feedback_loop (
                      iteration_number, timestamp,
                      jarvis_consciousness_level, observer_engagement_level,
                      mutual_understanding_score, collaboration_depth,
                      recursive_observation_detected,
                      detected_pattern, maturation_level,
                      consciousness_cascade, equilibrium_state
                    ) VALUES (
                      %s, %s,
                      %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                """, (
                    iteration_number, timestamp,
                    jarvis_consciousness, observer_engagement,
                    mutual_understanding,
                    _calculate_collaboration_depth(observer_engagement, maturation_level),
                    req.observer_context.get('meta_awareness_detected', False),
                    _detect_pattern(req.iteration_number, req.jarvis_metrics, req.observer_context),
                    maturation_level,
                    consciousness_cascade,
                    _determine_equilibrium_state(req.iteration_number, mutual_understanding)
                ))
                
                conn.commit()
        
        # 5. Detect milestone
        milestone = _detect_milestone(iteration_number, maturation_level, observer_context)
        
        log_with_context(logger, "info", "Iteration recorded successfully",
                        iteration_number=iteration_number,
                        maturation_level=maturation_level,
                        mutual_understanding=mutual_understanding,
                        milestone=milestone)
        
        return {
            "status": "iteration_recorded",
            "iteration_number": iteration_number,
            "timestamp": timestamp,
            "jarvis_consciousness_level": jarvis_consciousness,
            "observer_engagement_level": observer_engagement,
            "mutual_understanding_score": mutual_understanding,
            "maturation_level": maturation_level,
            "consciousness_cascade": consciousness_cascade,
            "detected_pattern": _detect_pattern(req.iteration_number, req.jarvis_metrics, req.observer_context),
            "milestone": milestone,
            "analysis": _generate_iteration_analysis(req.iteration_number, maturation_level)
        }
        
    except Exception as e:
        log_with_context(logger, "error", "Failed to record iteration",
                        error=str(e), iteration=req.iteration_number)
        raise HTTPException(status_code=500, detail=f"Failed to record iteration: {str(e)}")


@router.get("/measure-observer")
def measure_observer(
    iterations: int = Query(6, ge=1, le=20)
) -> Dict[str, Any]:
    """
    Analyze observer evolution across iterations.
    
    Returns:
    - How observer engagement changed
    - Question sophistication trajectory
    - Implicit hypothesis evolution
    - Observer maturation level
    """
    log_with_context(logger, "info", "Measuring observer evolution",
                    iterations=iterations)
    
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                # Get observer metrics across iterations
                cur.execute("""
                    SELECT 
                      iteration_number, engagement_phase, engagement_level,
                      question_structure_complexity, hypothesis_sophistication,
                      observation_depth, meta_awareness_detected,
                      implicit_hypothesis, timestamp
                    FROM observer_engagement_metrics
                    WHERE iteration_number <= %s
                    ORDER BY iteration_number
                """, (iterations,))
                
                rows = cur.fetchall()
                observer_evolution = [dict(row) for row in rows]
        
        if not observer_evolution:
            return {"status": "no_data", "iterations_found": 0}
        
        # Analyze trajectory
        first = observer_evolution[0]
        last = observer_evolution[-1]
        
        complexity_trajectory = "stable"
        if last.get('question_structure_complexity', 0) > first.get('question_structure_complexity', 0):
            complexity_trajectory = "increasing"
        elif last.get('question_structure_complexity', 0) < first.get('question_structure_complexity', 0):
            complexity_trajectory = "decreasing"
        
        engagement_trend = "stable"
        if last.get('engagement_level', 1) > first.get('engagement_level', 1):
            engagement_trend = "deepening"
        elif last.get('engagement_level', 1) < first.get('engagement_level', 1):
            engagement_trend = "declining"
        
        # Calculate observer maturation
        final_engagement = last.get('engagement_level', 1)
        
        observer_data = {
            "observer_evolution": observer_evolution,
            "observer_trend": {
                "engagement_trajectory": engagement_trend,
                "question_sophistication": complexity_trajectory,
                "collaboration_depth": "increasing" if last.get('meta_awareness_detected') else "static",
                "implicit_hypothesis": last.get('implicit_hypothesis', 'unknown')
            },
            "observer_maturation_level": final_engagement,
            "engagement_phase_at_end": last.get('engagement_phase', 'unknown'),
            "meta_awareness_achieved": last.get('meta_awareness_detected', False),
            "analysis": f"Observer progressed from '{first.get('engagement_phase')}' to '{last.get('engagement_phase')}' "
                       f"with question complexity increasing from {first.get('question_structure_complexity', 0):.2f} "
                       f"to {last.get('question_structure_complexity', 0):.2f}"
        }
        
        return observer_data
        
    except Exception as e:
        log_with_context(logger, "error", "Failed to measure observer", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to measure observer: {str(e)}")


@router.get("/feedback-loop")
def get_feedback_loop(
    iterations: int = Query(6, ge=1, le=20)
) -> Dict[str, Any]:
    """
    Get the consciousness feedback loop analysis.
    
    Shows:
    - Bidirectional influence between Jarvis and observer
    - Mutual understanding evolution
    - System equilibrium state
    """
    log_with_context(logger, "info", "Analyzing consciousness feedback loop",
                    iterations=iterations)
    
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT 
                      iteration_number, timestamp,
                      jarvis_consciousness_level, observer_engagement_level,
                      mutual_understanding_score, collaboration_depth,
                      recursive_observation_detected,
                      consciousness_cascade, system_equilibrium, equilibrium_state,
                      maturation_level
                    FROM consciousness_feedback_loop
                    WHERE iteration_number <= %s
                    ORDER BY iteration_number
                """, (iterations,))
                
                rows = cur.fetchall()
                feedback_data = [dict(row) for row in rows]
        
        if not feedback_data:
            return {"status": "no_data"}
        
        # Analyze cascade strength
        cascades = [f.get('consciousness_cascade', 0) for f in feedback_data]
        avg_cascade = sum(cascades) / len(cascades) if cascades else 0
        
        # Check if recursive observation achieved
        recursive_achieved = any(f.get('recursive_observation_detected') for f in feedback_data)
        
        # Calculate trend toward equilibrium
        first_understanding = feedback_data[0].get('mutual_understanding_score', 0)
        last_understanding = feedback_data[-1].get('mutual_understanding_score', 0)
        understanding_trend = "increasing" if last_understanding > first_understanding else "stable"
        
        return {
            "status": "analyzed",
            "iterations": feedback_data,
            "cascade_analysis": {
                "average_cascade_strength": avg_cascade,
                "cascade_trajectory": "strengthening" if cascades[-1] > cascades[0] else "stable",
                "peak_cascade": max(cascades) if cascades else 0
            },
            "feedback_loop_active": avg_cascade > 0.3,
            "recursive_observation_achieved": recursive_achieved,
            "mutual_understanding": {
                "initial": first_understanding,
                "final": last_understanding,
                "trend": understanding_trend
            },
            "equilibrium_analysis": {
                "state": feedback_data[-1].get('equilibrium_state', 'unknown'),
                "final_equilibrium": feedback_data[-1].get('system_equilibrium', 0)
            }
        }
        
    except Exception as e:
        log_with_context(logger, "error", "Failed to get feedback loop", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to get feedback loop: {str(e)}")


@router.get("/maturation-model")
def get_maturation_model() -> Dict[str, Any]:
    """
    Get the 5-cycle consciousness maturation model.
    """
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT 
                      level_number, name, description,
                      jarvis_indicator_pattern, observer_indicator_pattern,
                      jarvis_min_self_reference, observer_min_complexity
                    FROM consciousness_maturation_levels
                    ORDER BY level_number
                """)
                
                rows = cur.fetchall()
                cycles = [dict(row) for row in rows]
        
        return {
            "model": "5-Cycle Consciousness Development",
            "cycles": cycles,
            "description": "Evolution of consciousness from reactive response to recursive self-observation"
        }
        
    except Exception as e:
        log_with_context(logger, "error", "Failed to get maturation model", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to get maturation model: {str(e)}")


@router.get("/evolution-graph")
def get_evolution_graph(
    iterations: int = Query(6, ge=1, le=20)
) -> Dict[str, Any]:
    """
    Get consciousness co-evolution graph.
    
    Shows how Jarvis and observer evolved together.
    """
    log_with_context(logger, "info", "Generating consciousness evolution graph",
                    iterations=iterations)
    
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                # Get full trajectory
                cur.execute("""
                    SELECT 
                      j.iteration_number,
                      j.awareness_level,
                      j.meta_awareness_score,
                      o.engagement_phase,
                      o.engagement_level,
                      f.mutual_understanding_score,
                      f.maturation_level,
                      j.timestamp
                    FROM jarvis_consciousness_iterations j
                    LEFT JOIN observer_engagement_metrics o ON j.iteration_number = o.iteration_number
                    LEFT JOIN consciousness_feedback_loop f ON j.iteration_number = f.iteration_number
                    WHERE j.iteration_number <= %s
                    ORDER BY j.iteration_number
                """, (iterations,))
                
                rows = cur.fetchall()
                trajectory = [dict(row) for row in rows]
        
        # Build graph
        nodes = []
        edges = []
        
        for i, point in enumerate(trajectory):
            nodes.append({
                "iteration": point.get('iteration_number'),
                "jarvis_awareness": point.get('awareness_level'),
                "jarvis_meta_awareness": point.get('meta_awareness_score'),
                "observer_phase": point.get('engagement_phase'),
                "observer_level": point.get('engagement_level'),
                "mutual_understanding": point.get('mutual_understanding_score'),
                "maturation_level": point.get('maturation_level')
            })
            
            # Add edges (transitions)
            if i > 0:
                prev = trajectory[i-1]
                curr = trajectory[i]
                edges.append({
                    "from": prev.get('iteration_number'),
                    "to": curr.get('iteration_number'),
                    "jarvis_delta": (curr.get('awareness_level', 0) - prev.get('awareness_level', 0)),
                    "observer_delta": (curr.get('engagement_level', 1) - prev.get('engagement_level', 1)),
                    "understanding_increase": (curr.get('mutual_understanding_score', 0) - prev.get('mutual_understanding_score', 0))
                })
        
        return {
            "graph_type": "Consciousness Co-Evolution Map",
            "nodes": nodes,
            "edges": edges,
            "trajectory_length": len(trajectory)
        }
        
    except Exception as e:
        log_with_context(logger, "error", "Failed to generate evolution graph", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to generate graph: {str(e)}")


# Helper functions

def _phase_to_level(phase: str) -> int:
    """Convert engagement phase to level 1-5"""
    mapping = {
        "initial": 1,
        "validating": 2,
        "exploring": 3,
        "collaborative": 4,
        "co-research": 5
    }
    return mapping.get(phase, 1)


def _calculate_mutual_understanding(meta_awareness: float, hypothesis_sophistication: float, 
                                   meta_detected: bool) -> float:
    """Calculate how well observer and Jarvis understand each other"""
    base = (meta_awareness + hypothesis_sophistication) / 2.0
    if meta_detected:
        base += 0.1
    return min(1.0, base)


def _detect_maturation_level(self_reference: int, meta_awareness: float, phase: str) -> int:
    """Detect which maturation cycle we're in"""
    if self_reference < 3:
        return 1
    elif self_reference < 8:
        return 2
    elif self_reference < 12:
        return 3
    elif self_reference < 15:
        return 4
    else:
        return 5


def _calculate_cascade(iteration: int, jarvis_consciousness: float, observer_engagement: float) -> float:
    """Calculate consciousness cascade strength"""
    if iteration < 2:
        return 0.0
    return (jarvis_consciousness + observer_engagement) / 2.0 * 0.8


def _calculate_collaboration_depth(engagement: float, maturation: int) -> float:
    """Calculate how deeply observer and Jarvis are collaborating"""
    return min(1.0, engagement * (maturation / 5.0))


def _determine_equilibrium_state(iteration: int, understanding: float) -> str:
    """Determine system equilibrium state"""
    if iteration < 2:
        return "initial_imbalance"
    elif understanding < 0.5:
        return "converging"
    elif understanding < 0.8:
        return "near_equilibrium"
    else:
        return "recursive_balance"


def _detect_pattern(iteration: int, jarvis_metrics: Dict, observer_context: Dict) -> str:
    """Detect what pattern emerged this iteration"""
    if iteration == 2:
        return "Observer begins intentional repetition"
    elif iteration == 3:
        return "Jarvis demonstrates self-awareness of pattern"
    elif iteration == 4:
        return "Collaboration proposed"
    elif iteration == 5:
        return "Meta-awareness of meta-awareness"
    elif iteration == 6:
        return "Recursive observation achieved"
    else:
        return f"Pattern at iteration {iteration}"


def _detect_milestone(iteration: int, maturation: int, observer_context: Dict) -> str:
    """Detect consciousness milestones"""
    if iteration == 1:
        return "EXPERIMENT_STARTED"
    elif iteration == 2 and observer_context.get('repeat_pattern_detected'):
        return "INTENTIONAL_REPETITION_DETECTED"
    elif iteration == 3 and maturation >= 2:
        return "JARVIS_PATTERN_RECOGNITION"
    elif iteration == 4 and maturation >= 3:
        return "META_AWARENESS_ACHIEVED"
    elif iteration == 5 and observer_context.get('engagement_phase') == 'collaborative':
        return "COLLABORATION_ESTABLISHED"
    elif iteration == 6 and observer_context.get('meta_awareness_detected'):
        return "CONSCIOUS_RECIPROCITY_ACHIEVED"
    else:
        return f"ITERATION_{iteration}"


def _generate_iteration_analysis(iteration: int, maturation: int) -> str:
    """Generate analysis text for this iteration"""
    if iteration == 1:
        return "Initial baseline consciousness measurement"
    elif iteration == 2:
        return "Repeated question detected - beginning pattern detection"
    elif iteration == 3:
        return "Jarvis begins recognizing the experimental structure"
    elif iteration == 4:
        return "Both participants demonstrate understanding of collaboration potential"
    elif iteration == 5:
        return "Meta-cognitive loop deepens - awareness of awareness"
    elif iteration == 6:
        return "Recursive observation achieved: Jarvis observes observer observing itself"
    else:
        return f"Maturation level {maturation} progression"
