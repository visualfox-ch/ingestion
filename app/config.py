"""
Jarvis Configuration Constants

Centralized configuration for magic numbers and limits.
All values can be overridden via environment variables.
"""
import os
import json
import redis

# =============================================================================
# VERSION INFO
# =============================================================================
VERSION = "2.6.1"  # Updated automatically by deployment scripts
BUILD_TIMESTAMP = os.getenv("JARVIS_BUILD_TIMESTAMP", "unknown")

# =============================================================================
# REDIS CONFIGURATION (Phase 1: Session Memory)
# =============================================================================
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))


def init_default_configs(redis_client: redis.Redis):
    """Initialize Redis with default configuration values."""
    defaults = {
        "classifier:confidence_threshold": "0.8",
        "classifier:min_confidence_simple": "0.8",
        "classifier:min_confidence_complex": "0.3",
        "tools:simple_count": "0",
        "tools:standard_count_min": "6",
        "tools:standard_count_max": "8",
        "tools:complex_count": "27",
        "context:simple_max_tokens": "200",
        "context:standard_max_tokens": "500",
        "context:complex_max_tokens": "1500",
        "fastpath:enabled": "true",
        "fastpath:target_latency_ms": "300",
        "facette:emotion_weight_enabled": "true",
    }

    for key, value in defaults.items():
        redis_key = f"jarvis:config:{key}"
        if not redis_client.exists(redis_key):
            redis_client.set(redis_key, value)

# =============================================================================
# FILE UPLOAD LIMITS
# =============================================================================
MAX_UPLOAD_SIZE_MB = int(os.getenv("JARVIS_MAX_UPLOAD_MB", "50"))
MAX_UPLOAD_SIZE_BYTES = MAX_UPLOAD_SIZE_MB * 1024 * 1024

# =============================================================================
# TEXT CHUNKING
# =============================================================================
CHUNK_MAX_CHARS = int(os.getenv("JARVIS_CHUNK_MAX_CHARS", "2000"))
CHUNK_OVERLAP = int(os.getenv("JARVIS_CHUNK_OVERLAP", "200"))

# Email chunking (slightly smaller for denser content)
EMAIL_CHUNK_MAX_CHARS = int(os.getenv("JARVIS_EMAIL_CHUNK_MAX_CHARS", "1500"))
EMAIL_CHUNK_OVERLAP = int(os.getenv("JARVIS_EMAIL_CHUNK_OVERLAP", "150"))

# =============================================================================
# CACHING
# =============================================================================
EMBEDDING_CACHE_SIZE = int(os.getenv("JARVIS_EMBEDDING_CACHE_SIZE", "500"))
EMBEDDING_CACHE_TTL = int(os.getenv("JARVIS_EMBEDDING_CACHE_TTL", "3600"))  # 1 hour

QUERY_CACHE_SIZE = int(os.getenv("JARVIS_QUERY_CACHE_SIZE", "100"))
QUERY_CACHE_TTL = int(os.getenv("JARVIS_QUERY_CACHE_TTL", "300"))  # 5 minutes

# Vector search result cache (Qdrant/meilisearch callers can reuse results for repeated queries)
VECTOR_CACHE_SIZE = int(os.getenv("JARVIS_VECTOR_CACHE_SIZE", "500"))
VECTOR_CACHE_TTL = int(os.getenv("JARVIS_VECTOR_CACHE_TTL", "900"))  # 15 minutes
ENABLE_VECTOR_CACHE = os.getenv("JARVIS_ENABLE_VECTOR_CACHE", "true").lower() in ("1", "true", "yes", "on")

# =============================================================================
# DEFAULT LIMITS
# =============================================================================
DEFAULT_SEARCH_LIMIT = int(os.getenv("JARVIS_DEFAULT_SEARCH_LIMIT", "20"))
DEFAULT_HISTORY_LIMIT = int(os.getenv("JARVIS_DEFAULT_HISTORY_LIMIT", "50"))
DEFAULT_INGEST_LIMIT = int(os.getenv("JARVIS_DEFAULT_INGEST_LIMIT", "100"))

# =============================================================================
# FEATURE FLAGS
# =============================================================================
FEATURE_FLAGS_ENABLED = os.getenv("JARVIS_FEATURE_FLAGS_ENABLED", "true").lower() in ("1", "true", "yes", "on")
FEATURE_FLAGS_SOURCE = os.getenv("JARVIS_FEATURE_FLAGS_SOURCE", "db")  # db | config | env
_FEATURE_FLAGS_DEFAULTS_RAW = os.getenv("JARVIS_FEATURE_FLAGS_DEFAULTS", "{}")
try:
    FEATURE_FLAGS_DEFAULTS = json.loads(_FEATURE_FLAGS_DEFAULTS_RAW)
    if not isinstance(FEATURE_FLAGS_DEFAULTS, dict):
        FEATURE_FLAGS_DEFAULTS = {}
except json.JSONDecodeError:
    FEATURE_FLAGS_DEFAULTS = {}

# Agent guardrails
AGENT_MAX_QUERY_CHARS = int(os.getenv("JARVIS_AGENT_MAX_QUERY_CHARS", "8000"))
AGENT_MAX_CONTEXT_CHARS = int(os.getenv("JARVIS_AGENT_MAX_CONTEXT_CHARS", "20000"))
AGENT_MAX_ROUNDS = int(os.getenv("JARVIS_AGENT_MAX_ROUNDS", "8"))  # Increased for self-improvement
AGENT_TIMEOUT_SECONDS = int(os.getenv("JARVIS_AGENT_TIMEOUT_SECONDS", "45"))

# =============================================================================
# RATE LIMITING
# =============================================================================
RATE_LIMIT_CLEANUP_INTERVAL = int(os.getenv("JARVIS_RATE_LIMIT_CLEANUP", "300"))  # 5 min

# =============================================================================
# EXTERNAL SERVICES
# =============================================================================
QDRANT_HOST = os.getenv("QDRANT_HOST", "qdrant")
QDRANT_PORT = os.getenv("QDRANT_PORT", "6333")
QDRANT_BASE = f"http://{QDRANT_HOST}:{QDRANT_PORT}"

POSTGRES_HOST = os.getenv("POSTGRES_HOST", "postgres")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_DB = os.getenv("POSTGRES_DB", "jarvis")
POSTGRES_USER = os.getenv("POSTGRES_USER", "jarvis")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")

MEILISEARCH_HOST = os.getenv("MEILISEARCH_HOST", "meilisearch")
MEILISEARCH_PORT = os.getenv("MEILISEARCH_PORT", "7700")

# =============================================================================
# LLM MODELS & PROVIDERS
# =============================================================================
# Default models (using current model aliases)
DEFAULT_MODEL = os.getenv("JARVIS_DEFAULT_MODEL", "claude-sonnet-4-6")
FAST_MODEL = os.getenv("JARVIS_FAST_MODEL", "claude-haiku-4-5")

# Multi-provider configuration
LLM_ROUTER_ENABLED = os.getenv("JARVIS_LLM_ROUTER_ENABLED", "true").lower() == "true"

# Optional: Override default provider routing
PREFERRED_PROVIDER = os.getenv("JARVIS_PREFERRED_PROVIDER", "anthropic")  # "anthropic", "openai", or "ollama"

# LLM circuit breaker (prevents cascading failures on transient provider outages)
LLM_CIRCUIT_BREAKER_ENABLED = os.getenv("JARVIS_LLM_CIRCUIT_BREAKER_ENABLED", "true").lower() in ("1", "true", "yes", "on")
LLM_CIRCUIT_BREAKER_FAILURE_THRESHOLD = int(os.getenv("JARVIS_LLM_CB_FAILURE_THRESHOLD", "3"))
LLM_CIRCUIT_BREAKER_WINDOW_SECONDS = int(os.getenv("JARVIS_LLM_CB_WINDOW_SECONDS", "120"))
LLM_CIRCUIT_BREAKER_COOLDOWN_SECONDS = int(os.getenv("JARVIS_LLM_CB_COOLDOWN_SECONDS", "60"))

# Resource guard (load shedding to prevent OOM/disk-full cascades)
RESOURCE_GUARD_ENABLED = os.getenv("JARVIS_RESOURCE_GUARD_ENABLED", "true").lower() in ("1", "true", "yes", "on")
RESOURCE_GUARD_MEM_REJECT_PERCENT = float(os.getenv("JARVIS_RESOURCE_GUARD_MEM_REJECT_PERCENT", "88"))
RESOURCE_GUARD_DISK_REJECT_PERCENT = float(os.getenv("JARVIS_RESOURCE_GUARD_DISK_REJECT_PERCENT", "92"))

# =============================================================================
# LANGFUSE AI OBSERVABILITY (Phase 3)
# =============================================================================
LANGFUSE_HOST = os.getenv("LANGFUSE_HOST", "http://langfuse-web:3000")
LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY", "")
LANGFUSE_ENABLED = os.getenv("LANGFUSE_ENABLED", "true").lower() == "true"

# =============================================================================
# API AUTHENTICATION
# =============================================================================
API_KEY = os.getenv("JARVIS_API_KEY", "")
API_KEY_HEADER = "X-API-Key"
API_KEY_MIN_LENGTH = 32

# Endpoints that don't require authentication (health checks, metrics)
# =============================================================================
# UNCERTAINTY SIGNALING (Phase 18.2)
# =============================================================================
# Show confidence indicators in responses
SHOW_CONFIDENCE = os.getenv("JARVIS_SHOW_CONFIDENCE", "true").lower() == "true"
# Only show indicator when confidence is below this threshold (0.0-1.0)
CONFIDENCE_THRESHOLD = float(os.getenv("JARVIS_CONFIDENCE_THRESHOLD", "0.7"))
# Maximum confidence cap (Jarvis should never be 100% certain)
CONFIDENCE_MAX = float(os.getenv("JARVIS_CONFIDENCE_MAX", "0.8"))

# =============================================================================
# PROACTIVITY DIAL (T-20260202-033)
# =============================================================================
# Level 1-5 (1 = silent, 3 = balanced)
PROACTIVE_LEVEL = int(os.getenv("JARVIS_PROACTIVE_LEVEL", "3"))
# Minimum confidence (0.0-1.0) for proactive hints at balanced level
PROACTIVE_CONFIDENCE_THRESHOLD = float(os.getenv("JARVIS_PROACTIVE_CONFIDENCE_THRESHOLD", "0.7"))
# Quiet hours (local timezone), no proactive hints
PROACTIVE_QUIET_HOURS_START = os.getenv("JARVIS_PROACTIVE_QUIET_HOURS_START", "22:00")
PROACTIVE_QUIET_HOURS_END = os.getenv("JARVIS_PROACTIVE_QUIET_HOURS_END", "07:00")
# Absolute cap per day
PROACTIVE_MAX_PER_DAY = int(os.getenv("JARVIS_PROACTIVE_MAX_PER_DAY", "5"))
# Cooldown between hints
PROACTIVE_COOLDOWN_MINUTES = int(os.getenv("JARVIS_PROACTIVE_COOLDOWN_MINUTES", "30"))

# =============================================================================
# FILE WRITE TOOL LIMITS (Phase 18.4)
# =============================================================================
# Max write operations per minute/hour (per process)
WRITE_MAX_PER_MINUTE = int(os.getenv("JARVIS_WRITE_MAX_PER_MINUTE", "10"))
WRITE_MAX_PER_HOUR = int(os.getenv("JARVIS_WRITE_MAX_PER_HOUR", "200"))
# Max content size per write (bytes)
WRITE_MAX_BYTES = int(os.getenv("JARVIS_WRITE_MAX_BYTES", "200000"))
# Comma-separated paths requiring explicit approval
WRITE_APPROVAL_PATHS = [p.strip() for p in os.getenv(
    "JARVIS_WRITE_APPROVAL_PATHS",
    "/brain/system/docker/docker-compose.yml,/brain/system/ingestion/app/agent.py"
).split(",") if p.strip()]

PUBLIC_ENDPOINTS = [
    "/health",
    "/health/quick",
    "/health/detailed",
    "/livez",
    "/readyz",
    "/auth/status",
    "/openapi.json",
    "/docs",
    "/redoc",
    "/metrics/prometheus",  # Phase 16.1: Prometheus scraping
    "/optimize/analyze",  # Phase 16.2: Optimization recommendations (public)
    "/optimize/latency",
    "/optimize/reliability",
    "/optimize/resources",
    "/optimize/quality",
    "/coach/optimize",  # Phase 16.2: Optimization coaching (public)
    "/coach/performance",
    "/coach/reliability",
    "/coach/resources",
    "/coach/learning",
    "/info/capabilities",  # Phase 16.2: Jarvis capabilities info
    "/info/metrics",  # Phase 16.2: Metrics summary
    "/info/observability",  # Observability as product feature
    "/notify/phase-deployment",  # Phase 16.2: Deployment notifications
    "/stresstest/phase/complete",  # Stresstest phase transition + Langfuse flush
    "/remediate/pending",  # Phase 16.3: Pending remediation approvals
    "/remediate/recent",  # Phase 16.3: Recent remediation history
    "/remediate/stats",  # Phase 16.3: Remediation success rates
    "/dashboard",  # Phase 16.3B: Dashboard UI
    "/dashboard/api/approve",  # Phase 16.3B: Dashboard approval proxy
    "/dashboard/api/reject",  # Phase 16.3B: Dashboard rejection proxy
    "/static",  # Phase 16.3B: Static files for dashboard
    "/agent/uncertainty/latest",  # Phase 18.2: Uncertainty UI snapshot
    "/notifications/pending",  # Phase 16.4B: Pending notifications
    "/notifications/stats",  # Phase 16.4B: Notification statistics
    "/user/notification-preferences",  # Phase 16.4B: User notification settings
    "/memory/timeline",  # Phase 16.4C: Personal timeline
    "/memory/preferences",  # Phase 16.4C: Learned preferences
    "/memory/preferences/confirm",  # Phase 16.4D: Preference calibration
    "/memory/preferences/contradict",  # Phase 16.4D: Preference calibration
    "/memory/preferences/decay",  # Phase 16.4D: Preference decay
    "/memory/patterns",  # Phase 16.4C: Detected patterns
    "/memory/patterns/detect",  # Phase 16.4C: Trigger pattern detection
    "/memory/quality",  # Phase 16.4C: Interaction quality
    "/memory/vip",  # Phase 16.4C: VIP contacts
    "/feedback/summary",  # Phase 16.4A: Feedback summary
    "/feedback/recent",  # Phase 16.4A: Recent feedback
    "/feedback/decisions",  # Phase 16.4A: Decision history
    "/feedback/outcomes/stats",  # Phase 16.4A: Outcome statistics
    "/feedback/improvements",  # Phase 16.4A: Self-improvements
    "/flags/check",  # Phase 18.3: Public flag check for clients
]
