"""
Multi-Provider Model Router for Jarvis.

Phase 21: Autonomous Model Selection
- Supports OpenAI + Anthropic
- Database-driven configuration (Jarvis can modify)
- Task-based model selection with complexity awareness
- Learning from usage patterns
"""

import logging
import re
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass
from enum import Enum
from app.postgres_state import get_conn
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)


class Provider(Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    OLLAMA = "ollama"


@dataclass
class ModelConfig:
    """Configuration for a model."""
    model_id: str
    provider: Provider
    display_name: str
    cost_input_per_1m: float
    cost_output_per_1m: float
    capabilities: Dict[str, float]
    max_tokens: int
    context_window: int


@dataclass
class ModelSelection:
    """Result of model selection."""
    model_id: str
    provider: Provider
    task_type: str
    complexity: float
    reason: str


class MultiModelRouter:
    """
    Database-driven multi-provider model router.

    Jarvis can modify the model registry and task mappings
    to optimize model selection based on experience.
    """

    # Task classification patterns
    TASK_PATTERNS = {
        'code_generation': [
            r'\b(write|create|generate|implement|build|schreibe|erstelle|generiere|implementiere)\b.*\b(code|function|class|script|program|funktion|klasse|skript)\b',
            r'\b(python|javascript|typescript|rust|go)\b.*\b(code|function|funktion)\b',
        ],
        'code_review': [
            r'\b(review|check|improve|refactor|optimize)\b.*\b(code|function|class)\b',
            r'\bcode\s*review\b',
        ],
        'debugging': [
            r'\b(debug|fix|error|bug|issue|problem|broken)\b',
            r'\b(doesn\'t|does not|won\'t|will not)\s*work\b',
        ],
        'math_reasoning': [
            r'\b(calculate|compute|solve|prove|equation|formula)\b',
            r'\b(math|mathematical|algebra|calculus)\b',
            r'\d+\s*[\+\-\*\/\^]\s*\d+',
        ],
        'analysis': [
            r'\b(analyze|analyse|evaluate|assess|compare|analysiere|analysieren|auswerten|bewerten|vergleichen)\b',
            r'\b(data|statistics|metrics|trends|daten|statistik|metriken|performance|bericht|report)\b',
        ],
        'creative_writing': [
            r'\b(write|create)\b.*\b(story|poem|essay|article)\b',
            r'\b(creative|imaginative|fictional)\b',
        ],
        'planning': [
            r'\b(plan|strategy|roadmap|schedule|timeline)\b',
            r'\b(how\s+should|what\s+steps)\b',
        ],
        'summarization': [
            r'\b(summarize|summarise|summary|tldr|brief)\b',
            r'\b(key\s+points|main\s+points)\b',
        ],
        'translation': [
            r'\b(translate|translation|übersetze)\b',
            r'\b(to\s+english|to\s+german|auf\s+deutsch)\b',
        ],
        'quick_question': [
            r'^(what|who|when|where|why|how)\s+(is|are|was|were|do|does|did)\b',
            r'\?$',
        ],
        'general_chat': [
            r'^(hi|hello|hey|hallo|guten\s+tag|guten\s+morgen|good\s+morning)[\s\!\.\,]*$',
            r'^(thanks|thank\s+you|danke)[\s\!\.\,]*$',
            r'^(bye|goodbye|tschüss|ciao)[\s\!\.\,]*$',
            r'^wie\s+geht.*\?*$',
        ],
    }

    # Complexity indicators
    COMPLEXITY_HIGH = [
        r'\b(complex|complicated|difficult|advanced|sophisticated|komplex|kompliziert|schwierig|umfangreich)\b',
        r'\b(multiple|several|various|mehrere|verschiedene)\b.*\b(files|functions|systems|dateien|funktionen|systeme)\b',
        r'\b(architecture|infrastructure|deployment|architektur|infrastruktur)\b',
        r'\b(security|authentication|encryption|sicherheit|authentifizierung)\b',
        r'\b(analysiere|analyse|bericht|report|grafik|chart|woche|monat)\b',
    ]

    COMPLEXITY_LOW = [
        r'\b(simple|basic|easy|quick|short|einfach|kurz|schnell)\b',
        r'\b(just|only|single|nur|einzeln)\b',
        r'^.{0,40}$',  # Very short queries
    ]

    def __init__(self):
        self._models_cache: Optional[Dict[str, ModelConfig]] = None
        self._cache_time: float = 0
        self._cache_ttl: float = 300  # 5 minutes

    def _get_models(self) -> Dict[str, ModelConfig]:
        """Load models from database with caching."""
        import time
        now = time.time()

        if self._models_cache and (now - self._cache_time) < self._cache_ttl:
            return self._models_cache

        models = {}
        try:
            with get_conn() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("""
                        SELECT model_id, provider, display_name,
                               cost_input_per_1m, cost_output_per_1m,
                               cap_reasoning, cap_coding, cap_creative,
                               cap_analysis, cap_math, cap_speed,
                               max_tokens, context_window
                        FROM jarvis_model_registry
                        WHERE is_active = TRUE
                    """)

                    for row in cur.fetchall():
                        models[row['model_id']] = ModelConfig(
                            model_id=row['model_id'],
                            provider=Provider(row['provider']),
                            display_name=row['display_name'],
                            cost_input_per_1m=float(row['cost_input_per_1m']),
                            cost_output_per_1m=float(row['cost_output_per_1m']),
                            capabilities={
                                'reasoning': float(row['cap_reasoning']),
                                'coding': float(row['cap_coding']),
                                'creative': float(row['cap_creative']),
                                'analysis': float(row['cap_analysis']),
                                'math': float(row['cap_math']),
                                'speed': float(row['cap_speed']),
                            },
                            max_tokens=row['max_tokens'],
                            context_window=row['context_window'],
                        )

            self._models_cache = models
            self._cache_time = now
            logger.info(f"Loaded {len(models)} models from database")

        except Exception as e:
            logger.warning(f"Failed to load models from DB, using defaults: {e}")
            # Fallback to minimal defaults
            models = {
                'gpt-4o-mini': ModelConfig(
                    model_id='gpt-4o-mini',
                    provider=Provider.OPENAI,
                    display_name='GPT-4o Mini',
                    cost_input_per_1m=0.15,
                    cost_output_per_1m=0.60,
                    capabilities={'reasoning': 0.7, 'coding': 0.65, 'creative': 0.7,
                                  'analysis': 0.65, 'math': 0.6, 'speed': 0.95},
                    max_tokens=16384,
                    context_window=128000,
                ),
            }
            self._models_cache = models

        return models

    def _get_default_model(self, force_provider: Optional[str] = None) -> str:
        """Get the default model from database."""
        try:
            with get_conn() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    if force_provider:
                        # Get cheapest model for the forced provider
                        cur.execute("""
                            SELECT model_id FROM jarvis_model_registry
                            WHERE provider = %s AND is_active = TRUE
                            ORDER BY (cost_input_per_1m + cost_output_per_1m) ASC
                            LIMIT 1
                        """, (force_provider,))
                    else:
                        cur.execute("""
                            SELECT model_id FROM jarvis_model_registry
                            WHERE is_default = TRUE AND is_active = TRUE
                            LIMIT 1
                        """)
                    row = cur.fetchone()
                    if row:
                        return row['model_id']
        except Exception as e:
            logger.warning(f"Failed to get default model: {e}")

        # Provider-specific fallbacks
        if force_provider == 'anthropic':
            return 'claude-haiku-4-5-20251001'
        return 'gpt-4o-mini'

    def classify_task(self, query: str) -> Tuple[str, float]:
        """
        Classify query into task type and estimate complexity.

        Returns: (task_type, complexity 0-1)
        """
        query_lower = query.lower()

        # Find matching task type
        task_scores = {}
        for task_type, patterns in self.TASK_PATTERNS.items():
            score = 0
            for pattern in patterns:
                if re.search(pattern, query_lower, re.IGNORECASE):
                    score += 1
            if score > 0:
                task_scores[task_type] = score

        # Get best match or default
        if task_scores:
            task_type = max(task_scores, key=task_scores.get)
        else:
            task_type = 'general_chat'

        # Estimate complexity
        complexity = 0.5  # Default medium

        # Check for high complexity indicators
        for pattern in self.COMPLEXITY_HIGH:
            if re.search(pattern, query_lower, re.IGNORECASE):
                complexity = min(1.0, complexity + 0.2)

        # Check for low complexity indicators
        for pattern in self.COMPLEXITY_LOW:
            if re.search(pattern, query_lower, re.IGNORECASE):
                complexity = max(0.0, complexity - 0.2)

        # Query length as factor
        if len(query) > 500:
            complexity = min(1.0, complexity + 0.1)
        elif len(query) < 50:
            complexity = max(0.0, complexity - 0.1)

        return task_type, round(complexity, 2)

    def select_model(self, query: str, force_provider: Optional[str] = None) -> ModelSelection:
        """
        Select the best model for a query.

        Uses database configuration and can be modified by Jarvis.
        """
        task_type, complexity = self.classify_task(query)
        models = self._get_models()

        # Try to get mapping from database
        selected_model_id = None
        reason = ""

        try:
            with get_conn() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    # Get mappings for this task type
                    query_sql = """
                        SELECT m.model_id, m.provider, tm.priority, tm.min_complexity, tm.max_complexity,
                               tm.success_rate, tm.jarvis_override, tm.override_reason
                        FROM jarvis_task_model_mapping tm
                        JOIN jarvis_model_registry m ON tm.model_id = m.model_id
                        WHERE tm.task_type = %s
                          AND m.is_active = TRUE
                          AND %s >= tm.min_complexity
                          AND %s <= tm.max_complexity
                        ORDER BY
                            tm.jarvis_override DESC,  -- Jarvis overrides first
                            tm.priority ASC           -- Then by priority
                    """

                    cur.execute(query_sql, (task_type, complexity, complexity))
                    rows = cur.fetchall()

                    for row in rows:
                        # Filter by provider if forced
                        if force_provider and row['provider'] != force_provider:
                            continue

                        selected_model_id = row['model_id']
                        if row['jarvis_override']:
                            reason = f"Jarvis override: {row['override_reason'] or 'optimized'}"
                        else:
                            reason = f"Task mapping: {task_type} @ complexity {complexity}"
                        break

        except Exception as e:
            logger.warning(f"Failed to query task mappings: {e}")

        # Fallback: select cheapest model for low complexity, best-fit for high
        if not selected_model_id:
            if complexity <= 0.3:
                # Use cheapest active model for the provider
                selected_model_id = self._get_default_model(force_provider)
                reason = f"Default: low complexity, cheapest {force_provider or 'any'} model"
            else:
                # Use best capability match
                selected_model_id = self._select_by_capability(task_type, complexity, force_provider)
                reason = f"Capability match: {task_type}"

        # Get model config
        model_config = models.get(selected_model_id)
        if not model_config:
            # Ultimate fallback - respect provider preference
            if force_provider == 'anthropic':
                selected_model_id = 'claude-haiku-4-5-20251001'
            else:
                selected_model_id = 'gpt-4o-mini'
            model_config = models.get(selected_model_id, list(models.values())[0])
            reason = f"Fallback: {force_provider or 'default'} model"

        return ModelSelection(
            model_id=selected_model_id,
            provider=model_config.provider,
            task_type=task_type,
            complexity=complexity,
            reason=reason,
        )

    def _select_by_capability(self, task_type: str, complexity: float,
                              force_provider: Optional[str] = None) -> str:
        """Select model by best capability match."""
        models = self._get_models()

        # Get task weights from database
        weights = {
            'reasoning': 0.5, 'coding': 0.0, 'creative': 0.0,
            'analysis': 0.5, 'math': 0.0, 'speed': 0.5
        }
        cost_sensitivity = 0.7

        try:
            with get_conn() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("""
                        SELECT weight_reasoning, weight_coding, weight_creative,
                               weight_analysis, weight_math, weight_speed, cost_sensitivity
                        FROM jarvis_task_types
                        WHERE task_type = %s
                    """, (task_type,))
                    row = cur.fetchone()
                    if row:
                        weights = {
                            'reasoning': float(row['weight_reasoning']),
                            'coding': float(row['weight_coding']),
                            'creative': float(row['weight_creative']),
                            'analysis': float(row['weight_analysis']),
                            'math': float(row['weight_math']),
                            'speed': float(row['weight_speed']),
                        }
                        cost_sensitivity = float(row['cost_sensitivity'])
        except Exception as e:
            logger.debug(f"Failed to get task weights: {e}")

        # Score each model
        best_model = None
        best_score = -1

        for model_id, config in models.items():
            if force_provider and config.provider.value != force_provider:
                continue

            # Capability score (weighted)
            cap_score = sum(
                weights.get(cap, 0) * config.capabilities.get(cap, 0.5)
                for cap in weights
            )

            # Cost penalty (normalized, lower is better)
            # Average cost per 1K tokens
            avg_cost = (config.cost_input_per_1m + config.cost_output_per_1m) / 2000
            cost_penalty = avg_cost * cost_sensitivity * 10  # Scale factor

            # Final score
            score = cap_score - cost_penalty

            # Boost for high complexity
            if complexity > 0.7:
                # Prefer more capable models even if expensive
                score = cap_score * 1.5 - cost_penalty * 0.5

            if score > best_score:
                best_score = score
                best_model = model_id

        return best_model or self._get_default_model()

    def log_usage(self, model_id: str, task_type: str, query: str,
                  latency_ms: int, input_tokens: int, output_tokens: int,
                  success: bool = True, user_id: Optional[str] = None,
                  session_id: Optional[str] = None) -> None:
        """Log model usage for learning."""
        try:
            # Get model config for cost calculation
            models = self._get_models()
            model_config = models.get(model_id)

            cost_usd = 0.0
            if model_config:
                cost_usd = (
                    (input_tokens / 1_000_000) * model_config.cost_input_per_1m +
                    (output_tokens / 1_000_000) * model_config.cost_output_per_1m
                )

            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO jarvis_model_usage_log
                        (model_id, task_type, query_preview, latency_ms,
                         input_tokens, output_tokens, cost_usd, success,
                         user_id, session_id)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        model_id, task_type, query[:200], latency_ms,
                        input_tokens, output_tokens, cost_usd, success,
                        user_id, session_id
                    ))

                    # Update mapping statistics
                    cur.execute("""
                        UPDATE jarvis_task_model_mapping
                        SET times_used = times_used + 1,
                            avg_latency_ms = (avg_latency_ms * times_used + %s) / (times_used + 1),
                            updated_at = CURRENT_TIMESTAMP
                        WHERE task_type = %s AND model_id = %s
                    """, (latency_ms, task_type, model_id))

                conn.commit()

        except Exception as e:
            logger.warning(f"Failed to log model usage: {e}")

    def get_usage_stats(self, days: int = 7) -> Dict[str, Any]:
        """Get usage statistics for analysis."""
        try:
            with get_conn() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("""
                        SELECT
                            model_id,
                            COUNT(*) as total_calls,
                            SUM(cost_usd) as total_cost,
                            AVG(latency_ms) as avg_latency,
                            AVG(CASE WHEN success THEN 1 ELSE 0 END) as success_rate
                        FROM jarvis_model_usage_log
                        WHERE created_at > NOW() - INTERVAL '%s days'
                        GROUP BY model_id
                        ORDER BY total_calls DESC
                    """, (days,))

                    by_model = {row['model_id']: dict(row) for row in cur.fetchall()}

                    cur.execute("""
                        SELECT
                            task_type,
                            COUNT(*) as total_calls,
                            SUM(cost_usd) as total_cost
                        FROM jarvis_model_usage_log
                        WHERE created_at > NOW() - INTERVAL '%s days'
                        GROUP BY task_type
                        ORDER BY total_calls DESC
                    """, (days,))

                    by_task = {row['task_type']: dict(row) for row in cur.fetchall()}

                    return {
                        'by_model': by_model,
                        'by_task': by_task,
                        'days': days,
                    }

        except Exception as e:
            logger.warning(f"Failed to get usage stats: {e}")
            return {'error': str(e)}


# Singleton instance
_router: Optional[MultiModelRouter] = None


def get_multi_model_router() -> MultiModelRouter:
    """Get or create the multi-model router singleton."""
    global _router
    if _router is None:
        _router = MultiModelRouter()
    return _router
