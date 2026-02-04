"""
Prometheus metrics for Jarvis /agent endpoint.
Implements RED method (Rate, Errors, Duration).
"""

from prometheus_client import Counter, Histogram, Gauge
import time
from typing import Optional

# RED Method Metrics (https://prometheus.io/docs/practices/instrumentation/#red-method)

# Rate: Total number of requests
REQUEST_COUNT = Counter(
    'red_agent_requests_total',
    'Total agent requests',
    ['role', 'namespace']
)

# Duration: Request latency (seconds)
REQUEST_DURATION = Histogram(
    'red_agent_duration_seconds',
    'Agent request duration in seconds',
    ['role', 'namespace'],
    buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
)

# Errors: Request error rate
REQUEST_ERRORS = Counter(
    'red_agent_errors_total',
    'Total agent request errors',
    ['role', 'namespace', 'error_type']
)

# Circuit Breaker State (0=closed/normal, 1=open/disabled)
CIRCUIT_BREAKER_STATE = Gauge(
    'circuit_breaker_state',
    'Circuit breaker state (0=closed, 1=open)',
    ['service']
)

# Connection Pool Utilization (0-100%)
POOL_UTILIZATION = Gauge(
    'connection_pool_utilization',
    'Connection pool utilization percentage',
    ['pool_name']
)

# Token usage tracking
TOKENS_USED = Counter(
    'agent_tokens_used_total',
    'Total tokens consumed by agent',
    ['role', 'namespace', 'token_type']
)

# Tool execution metrics
TOOL_EXECUTIONS = Counter(
    'agent_tool_executions_total',
    'Total tool executions by agent',
    ['tool_name', 'status']
)

# Agentic loop metrics
AGENT_ROUNDS = Histogram(
    'agent_rounds_distribution',
    'Distribution of agent reasoning rounds',
    ['role', 'namespace'],
    buckets=(1, 3, 5, 10, 15)
)

# =============================================================================
# AUTONOMY METRICS (Phase B: minimal, measurable)
# =============================================================================

# Autonomous action lifecycle (created/approved/completed/expired/rejected/blocked)
AUTONOMOUS_ACTIONS_TOTAL = Counter(
    'jarvis_autonomous_actions_total',
    'Autonomy actions by tier and status',
    ['action', 'tier', 'status']
)

# Approval decisions for autonomy actions
AUTONOMOUS_APPROVAL_DECISIONS = Counter(
    'jarvis_autonomous_approval_decisions_total',
    'Approval decisions for autonomy actions',
    ['decision', 'tier']
)

# Approval latency for autonomy actions (seconds)
AUTONOMOUS_APPROVAL_LATENCY_SECONDS = Histogram(
    'jarvis_autonomous_approval_latency_seconds',
    'Time from request to approval decision (seconds)',
    ['decision', 'tier'],
    buckets=(5, 10, 30, 60, 120, 300, 600, 1200, 1800, 3600, 7200)
)

# Errors during autonomy action processing
AUTONOMOUS_ERRORS_TOTAL = Counter(
    'jarvis_autonomous_errors_total',
    'Autonomy action processing errors',
    ['action', 'stage', 'error_type']
)

# Rollbacks triggered by autonomy actions (hook when rollback exists)
AUTONOMOUS_ROLLBACKS_TOTAL = Counter(
    'jarvis_autonomous_rollbacks_total',
    'Autonomy rollbacks by reason',
    ['reason']
)


# =============================================================================
# FAST-PATH METRICS (T-020: Performance Optimization - Feb 3, 2026)
# Tracks query classification and fast-path effectiveness
# =============================================================================

# Query classification distribution
QUERY_CLASSIFICATION = Counter(
    'jarvis_query_classification_total',
    'Queries classified by complexity tier',
    ['tier']  # simple, standard, complex
)

# Fast-path counter (simple queries using fast-path)
FAST_PATH_TOTAL = Counter(
    'jarvis_fast_path_total',
    'Queries handled via fast-path (simple tier)',
    ['status']  # enabled, disabled, skipped
)

# Response latency by path (fast vs normal)
RESPONSE_LATENCY = Histogram(
    'jarvis_response_latency_seconds',
    'Response latency by execution path',
    ['path'],  # fast, normal
    buckets=[0.1, 0.3, 0.5, 1.0, 2.0, 5.0, 10.0]
)

# Tokens per query by tier
TOKENS_PER_QUERY = Histogram(
    'jarvis_tokens_per_query',
    'Token usage per query by tier',
    ['tier'],  # simple, standard, complex
    buckets=[50, 100, 250, 500, 1000, 2000, 4000, 8000]
)

# Classification accuracy (simple query that required tools indicates misclassification)
CLASSIFICATION_ACCURACY = Counter(
    'jarvis_classification_accuracy_total',
    'Classification accuracy tracking',
    ['classification', 'actual_outcome']  # simple/true, simple/false_positive, etc.
)


# =============================================================================
# FACETTE METRICS (Phase 1: Personality Tracking)
# Ready for T-005 facette_router to emit - Feb 3, 2026
# =============================================================================

# Facette usage tracking - which personality facets are activated
FACET_USAGE = Counter(
    'jarvis_facet_usage_total',
    'Number of times each personality facet was activated',
    ['facet']  # analytical, empathic, pragmatic, creative
)

# Facette blend ratio distribution - how facettes are mixed
FACET_BLEND_RATIO = Histogram(
    'jarvis_facet_blend_ratio',
    'Distribution of facet blend ratios (weight given to each facet)',
    ['facet'],
    buckets=[0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
)

# Dominant facette per request - which facet "won"
FACET_DOMINANT = Counter(
    'jarvis_facet_dominant_total',
    'Count of requests where each facet was dominant',
    ['facet', 'domain']  # analytical+engineering, empathic+coaching, etc.
)

# Facette transitions - how personality shifts between queries
FACET_TRANSITION = Counter(
    'jarvis_facet_transition_total',
    'Facette transitions between consecutive queries',
    ['from_facet', 'to_facet']
)


# =============================================================================
# FACETTE METRICS (Phase 2: Personality Tracking Expansion)
# Prometheus naming uses "facette" labels for detailed dashboards
# =============================================================================

FACETTE_ACTIVATION = Counter(
    'jarvis_facette_activation_total',
    'How many times each facette was activated',
    ['facette', 'domain']
)

FACETTE_BLEND_WEIGHTS = Histogram(
    'jarvis_facette_blend_weight',
    'Weight given to each facette (0-1.0)',
    ['facette'],
    buckets=[0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
)

FACETTE_DOMINANT = Counter(
    'jarvis_facette_dominant_total',
    'Which facette was dominant',
    ['facette', 'query_class']
)

FACETTE_TRANSITION = Counter(
    'jarvis_facette_transition_total',
    'Transitions from one facette to another',
    ['from_facette', 'to_facette']
)

FACETTE_USER_AFFINITY = Gauge(
    'jarvis_facette_user_affinity',
    'User preference for this facette (0-1)',
    ['facette', 'user_id']
)

FACETTE_EFFECTIVENESS = Counter(
    'jarvis_facette_effectiveness_total',
    'Success rate of this facette blend',
    ['facette', 'outcome']
)

FACETTE_EMOTION_CORRELATION = Histogram(
    'jarvis_facette_emotion_correlation',
    'Correlation between user emotion and selected facette',
    ['emotion', 'facette'],
    buckets=[0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
)


def record_facette_usage(
    facette_weights: dict,
    domain: str = "general",
    user_id: Optional[str] = None,
    query_class: Optional[str] = None
):
    """
    Record facette metrics for a single agent request.

    Call this from agent.py or facette_detector.py after detecting facettes.

    Args:
        facette_weights: Dict mapping facet name to weight (0.0-1.0)
                        e.g. {"Analytical": 0.4, "Empathic": 0.2, ...}
        domain: The detected domain context (engineering, coaching, etc.)
        user_id: Optional user id for affinity tracking (use sparingly)
        query_class: Optional query class (simple/standard/complex)
    """
    if not facette_weights:
        return

    # Record blend ratios for each facet
    for facet, weight in facette_weights.items():
        facet_lower = facet.lower()
        FACET_USAGE.labels(facet=facet_lower).inc()
        FACET_BLEND_RATIO.labels(facet=facet_lower).observe(weight)
        FACETTE_ACTIVATION.labels(facette=facet_lower, domain=domain.lower()).inc()
        FACETTE_BLEND_WEIGHTS.labels(facette=facet_lower).observe(weight)
        if user_id:
            FACETTE_USER_AFFINITY.labels(facette=facet_lower, user_id=user_id).set(weight)

    # Record dominant facet
    dominant = max(facette_weights.items(), key=lambda x: x[1])[0]
    dominant_lower = dominant.lower()
    FACET_DOMINANT.labels(facet=dominant_lower, domain=domain.lower()).inc()
    FACETTE_DOMINANT.labels(
        facette=dominant_lower,
        query_class=(query_class or "unknown").lower()
    ).inc()


def record_facette_transition(from_facette: str, to_facette: str):
    """Record transitions between facettes."""
    from_lower = from_facette.lower()
    to_lower = to_facette.lower()
    FACET_TRANSITION.labels(from_facet=from_lower, to_facet=to_lower).inc()
    FACETTE_TRANSITION.labels(from_facette=from_lower, to_facette=to_lower).inc()


def record_facette_effectiveness(facette: str, outcome: str):
    """Record success rate for a facette blend."""
    FACETTE_EFFECTIVENESS.labels(facette=facette.lower(), outcome=outcome).inc()


def record_facette_emotion_correlation(emotion: str, facette: str, correlation: float):
    """Record emotion to facette correlation value (0-1)."""
    FACETTE_EMOTION_CORRELATION.labels(
        emotion=emotion.lower(),
        facette=facette.lower()
    ).observe(correlation)


class MetricsContext:
    """Context manager for request metrics tracking."""
    
    def __init__(self, role: str = "default", namespace: str = "default"):
        self.role = role
        self.namespace = namespace
        self.start_time = None
    
    def __enter__(self):
        self.start_time = time.time()
        REQUEST_COUNT.labels(role=self.role, namespace=self.namespace).inc()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        duration = time.time() - self.start_time
        REQUEST_DURATION.labels(role=self.role, namespace=self.namespace).observe(duration)
        
        if exc_type is not None:
            error_type = exc_type.__name__
            REQUEST_ERRORS.labels(
                role=self.role,
                namespace=self.namespace,
                error_type=error_type
            ).inc()
            return False  # Re-raise the exception
        
        return True


def set_circuit_breaker_state(service: str, is_open: bool):
    """Update circuit breaker state (0=closed/normal, 1=open/disabled)."""
    CIRCUIT_BREAKER_STATE.labels(service=service).set(1 if is_open else 0)


def set_pool_utilization(pool_name: str, utilization_pct: float):
    """Update connection pool utilization percentage (0-100)."""
    POOL_UTILIZATION.labels(pool_name=pool_name).set(max(0, min(100, utilization_pct)))


def record_token_usage(role: str, namespace: str, input_tokens: int, output_tokens: int):
    """Record token usage for a request."""
    TOKENS_USED.labels(role=role, namespace=namespace, token_type='input').inc(input_tokens)
    TOKENS_USED.labels(role=role, namespace=namespace, token_type='output').inc(output_tokens)
    TOKENS_USED.labels(role=role, namespace=namespace, token_type='total').inc(input_tokens + output_tokens)


def record_tool_execution(tool_name: str, success: bool):
    """Record tool execution result."""
    status = 'success' if success else 'failure'
    TOOL_EXECUTIONS.labels(tool_name=tool_name, status=status).inc()


def record_agent_rounds(role: str, namespace: str, rounds: int):
    """Record number of agent reasoning rounds."""
    AGENT_ROUNDS.labels(role=role, namespace=namespace).observe(rounds)


# =============================================================================
# FAST-PATH HELPER FUNCTIONS (T-020 - Feb 3, 2026)
# =============================================================================

def record_query_classification(tier: str):
    """Record query classification (simple/standard/complex)."""
    QUERY_CLASSIFICATION.labels(tier=tier).inc()


def record_fast_path_status(status: str):
    """Record fast-path status (enabled/disabled/skipped)."""
    FAST_PATH_TOTAL.labels(status=status).inc()


def record_response_latency(path: str, latency_seconds: float):
    """Record response latency by path (fast/normal)."""
    RESPONSE_LATENCY.labels(path=path).observe(latency_seconds)


def record_tokens_per_query(tier: str, token_count: int):
    """Record token usage by query tier."""
    TOKENS_PER_QUERY.labels(tier=tier).observe(token_count)


def record_classification_accuracy(classification: str, outcome: str):
    """
    Record classification accuracy.
    
    Args:
        classification: The predicted class (simple/standard/complex)
        outcome: Whether it was correct (true/false_positive/false_negative)
    """
    CLASSIFICATION_ACCURACY.labels(
        classification=classification, 
        actual_outcome=outcome
    ).inc()


def record_tools_selected(query_class: str, tool_count: int):
    """
    Record number of tools selected for query class.
    
    Args:
        query_class: simple/standard/complex
        tool_count: Number of tools made available
    """
    # Use existing metrics - record via query tier token tracking
    # This indirectly tracks tool reduction since fewer tools = fewer tokens
    from .observability import get_logger, log_with_context
    log_with_context(
        get_logger("jarvis.metrics"),
        "debug",
        "Tools selected for query",
        query_class=query_class,
        tool_count=tool_count
    )
