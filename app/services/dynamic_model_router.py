"""
Dynamic Model Router for Jarvis.

Phase 21+: Fully database-driven model selection.
All patterns, rules, and configurations are in the database,
allowing Jarvis to learn and optimize model selection over time.
"""

import os
import re
import logging
import time
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field
from enum import Enum
from app.postgres_state import get_conn
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

DEFAULT_OLLAMA_MODEL = os.environ.get("JARVIS_OLLAMA_DEFAULT_MODEL", "qwen2.5:7b-instruct")
DEFAULT_LOCAL_TASK_TYPES = {
    "general_chat",
    "cheap_local",
    "speed",
    "summarize",
    "rewrite",
    "brainstorm",
}


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
    specialties: List[str]
    max_tokens: int
    context_window: int
    efficiency_score: float = 0.5


@dataclass
class TaskPattern:
    """A pattern for classifying tasks."""
    id: int
    task_type: str
    pattern_text: str
    pattern_type: str  # 'keyword', 'regex', 'phrase'
    language: str
    confidence: float
    compiled_regex: Optional[re.Pattern] = None


@dataclass
class ComplexityPattern:
    """A pattern for detecting complexity."""
    id: int
    indicator_type: str  # 'high' or 'low'
    pattern_text: str
    weight: float
    compiled_regex: Optional[re.Pattern] = None


@dataclass
class SelectionRule:
    """A rule for model selection."""
    id: int
    rule_name: str
    rule_type: str
    condition: Dict[str, Any]
    action_type: str
    action_value: Dict[str, Any]
    priority: int


@dataclass
class ModelSelection:
    """Result of model selection."""
    model_id: str
    provider: Provider
    task_type: str
    complexity: float
    reason: str
    rules_applied: List[str] = field(default_factory=list)
    confidence: float = 0.7


class DynamicModelRouter:
    """
    Fully database-driven model router.

    All classification patterns, complexity indicators, and selection rules
    are stored in the database. Jarvis can modify these to optimize selection.
    """

    def __init__(self):
        # Caches with TTLs
        self._models_cache: Optional[Dict[str, ModelConfig]] = None
        self._patterns_cache: Optional[List[TaskPattern]] = None
        self._complexity_cache: Optional[List[ComplexityPattern]] = None
        self._rules_cache: Optional[List[SelectionRule]] = None
        self._cache_time: float = 0
        self._cache_ttl: float = 300  # 5 minutes

    def _is_cache_valid(self) -> bool:
        return time.time() - self._cache_time < self._cache_ttl

    def _clear_cache(self) -> None:
        """Clear all caches (call after DB updates)."""
        self._models_cache = None
        self._patterns_cache = None
        self._complexity_cache = None
        self._rules_cache = None
        self._cache_time = 0

    # ========== MODELS ==========

    def _get_models(self) -> Dict[str, ModelConfig]:
        """Load models from database with caching."""
        if self._models_cache and self._is_cache_valid():
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
                               max_tokens, context_window, specialties,
                               COALESCE(efficiency_score, 0.5) as efficiency_score
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
                            specialties=row['specialties'] or [],
                            max_tokens=row['max_tokens'],
                            context_window=row['context_window'],
                            efficiency_score=float(row['efficiency_score']),
                        )

            self._models_cache = models
            self._cache_time = time.time()
            logger.info(f"Loaded {len(models)} models from database")

        except Exception as e:
            logger.warning(f"Failed to load models from DB: {e}")
            # Minimal fallback
            models = self._get_fallback_models()
            self._models_cache = models

        return models

    def _get_fallback_models(self) -> Dict[str, ModelConfig]:
        """Fallback models if DB is unavailable."""
        return {
            DEFAULT_OLLAMA_MODEL: ModelConfig(
                model_id=DEFAULT_OLLAMA_MODEL,
                provider=Provider.OLLAMA,
                display_name='Ollama Local',
                cost_input_per_1m=0.0,
                cost_output_per_1m=0.0,
                capabilities={'reasoning': 0.62, 'coding': 0.58, 'creative': 0.64,
                              'analysis': 0.60, 'math': 0.52, 'speed': 0.92},
                specialties=['local', 'fast', 'cheap'],
                max_tokens=8192,
                context_window=32768,
            ),
            'gpt-4o-mini': ModelConfig(
                model_id='gpt-4o-mini',
                provider=Provider.OPENAI,
                display_name='GPT-4o Mini',
                cost_input_per_1m=0.15,
                cost_output_per_1m=0.60,
                capabilities={'reasoning': 0.7, 'coding': 0.65, 'creative': 0.7,
                              'analysis': 0.65, 'math': 0.6, 'speed': 0.95},
                specialties=['fast', 'cheap'],
                max_tokens=16384,
                context_window=128000,
            ),
            'claude-haiku-4-5-20251001': ModelConfig(
                model_id='claude-haiku-4-5-20251001',
                provider=Provider.ANTHROPIC,
                display_name='Claude Haiku 4.5',
                cost_input_per_1m=0.25,
                cost_output_per_1m=1.25,
                capabilities={'reasoning': 0.75, 'coding': 0.70, 'creative': 0.75,
                              'analysis': 0.70, 'math': 0.65, 'speed': 0.95},
                specialties=['fast', 'cheap'],
                max_tokens=8192,
                context_window=200000,
            ),
        }

    def _get_local_first_provider(
        self,
        task_type: str,
        complexity: float,
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Return a local-first provider preference when a task is latency or cost sensitive."""
        if os.environ.get("JARVIS_OLLAMA_LOCAL_ROUTING_ENABLED", "true").lower() not in {
            "1", "true", "yes", "on"
        }:
            return None

        raw_task_types = os.environ.get(
            "JARVIS_OLLAMA_LOCAL_TASK_TYPES",
            ",".join(sorted(DEFAULT_LOCAL_TASK_TYPES)),
        )
        local_task_types = {
            item.strip() for item in raw_task_types.split(",") if item.strip()
        } or DEFAULT_LOCAL_TASK_TYPES

        local_threshold_raw = os.environ.get("JARVIS_OLLAMA_LOCAL_MAX_COMPLEXITY", "0.55")
        try:
            local_threshold = float(local_threshold_raw)
        except ValueError:
            local_threshold = 0.55

        context = context or {}
        explicit_local = bool(context.get("prefer_local"))
        latency_sensitive = bool(context.get("latency_sensitive"))
        cost_sensitive = bool(context.get("cost_sensitive"))

        if complexity > local_threshold and not explicit_local:
            return None

        if explicit_local or latency_sensitive or cost_sensitive or task_type in local_task_types:
            return Provider.OLLAMA.value

        return None

    # ========== TASK PATTERNS ==========

    def _get_task_patterns(self) -> List[TaskPattern]:
        """Load task classification patterns from database."""
        if self._patterns_cache and self._is_cache_valid():
            return self._patterns_cache

        patterns = []
        try:
            with get_conn() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("""
                        SELECT id, task_type, pattern_text, pattern_type, language, confidence
                        FROM jarvis_task_patterns
                        WHERE is_active = TRUE
                        ORDER BY confidence DESC
                    """)

                    for row in cur.fetchall():
                        pattern = TaskPattern(
                            id=row['id'],
                            task_type=row['task_type'],
                            pattern_text=row['pattern_text'],
                            pattern_type=row['pattern_type'],
                            language=row['language'],
                            confidence=float(row['confidence']),
                        )

                        # Pre-compile regex patterns
                        if pattern.pattern_type == 'regex':
                            try:
                                pattern.compiled_regex = re.compile(
                                    pattern.pattern_text, re.IGNORECASE
                                )
                            except re.error as e:
                                logger.warning(f"Invalid regex pattern {pattern.id}: {e}")
                                continue

                        patterns.append(pattern)

            self._patterns_cache = patterns
            logger.debug(f"Loaded {len(patterns)} task patterns from database")

        except Exception as e:
            logger.warning(f"Failed to load task patterns: {e}")
            patterns = []

        return patterns

    # ========== COMPLEXITY PATTERNS ==========

    def _get_complexity_patterns(self) -> List[ComplexityPattern]:
        """Load complexity indicators from database."""
        if self._complexity_cache and self._is_cache_valid():
            return self._complexity_cache

        patterns = []
        try:
            with get_conn() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("""
                        SELECT id, indicator_type, pattern_text, weight
                        FROM jarvis_complexity_patterns
                        WHERE is_active = TRUE
                    """)

                    for row in cur.fetchall():
                        pattern = ComplexityPattern(
                            id=row['id'],
                            indicator_type=row['indicator_type'],
                            pattern_text=row['pattern_text'],
                            weight=float(row['weight']),
                        )

                        try:
                            pattern.compiled_regex = re.compile(
                                pattern.pattern_text, re.IGNORECASE
                            )
                        except re.error:
                            continue

                        patterns.append(pattern)

            self._complexity_cache = patterns
            logger.debug(f"Loaded {len(patterns)} complexity patterns")

        except Exception as e:
            logger.warning(f"Failed to load complexity patterns: {e}")

        return patterns

    # ========== SELECTION RULES ==========

    def _get_selection_rules(self) -> List[SelectionRule]:
        """Load selection rules from database."""
        if self._rules_cache and self._is_cache_valid():
            return self._rules_cache

        rules = []
        try:
            with get_conn() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("""
                        SELECT id, rule_name, rule_type, condition, action_type, action_value, priority
                        FROM jarvis_selection_rules
                        WHERE is_active = TRUE
                        ORDER BY priority ASC
                    """)

                    for row in cur.fetchall():
                        rules.append(SelectionRule(
                            id=row['id'],
                            rule_name=row['rule_name'],
                            rule_type=row['rule_type'],
                            condition=row['condition'],
                            action_type=row['action_type'],
                            action_value=row['action_value'],
                            priority=row['priority'],
                        ))

            self._rules_cache = rules
            logger.debug(f"Loaded {len(rules)} selection rules")

        except Exception as e:
            logger.warning(f"Failed to load selection rules: {e}")

        return rules

    # ========== CLASSIFICATION ==========

    def classify_task(self, query: str) -> Tuple[str, float, float]:
        """
        Classify query into task type with confidence and complexity.

        Returns: (task_type, confidence, complexity)
        """
        query_lower = query.lower()
        patterns = self._get_task_patterns()

        # Score each task type
        task_scores: Dict[str, Tuple[float, int]] = {}  # task_type -> (total_confidence, matches)

        for pattern in patterns:
            matched = False

            if pattern.pattern_type == 'keyword':
                if pattern.pattern_text.lower() in query_lower:
                    matched = True
            elif pattern.pattern_type == 'phrase':
                if pattern.pattern_text.lower() in query_lower:
                    matched = True
            elif pattern.pattern_type == 'regex' and pattern.compiled_regex:
                if pattern.compiled_regex.search(query_lower):
                    matched = True

            if matched:
                if pattern.task_type not in task_scores:
                    task_scores[pattern.task_type] = (0.0, 0)
                prev_conf, prev_count = task_scores[pattern.task_type]
                task_scores[pattern.task_type] = (prev_conf + pattern.confidence, prev_count + 1)

                # Record hit for learning
                self._record_pattern_hit(pattern.id)

        # Find best match
        if task_scores:
            best_task = max(task_scores.keys(),
                           key=lambda t: task_scores[t][0] / max(task_scores[t][1], 1))
            total_conf, matches = task_scores[best_task]
            confidence = min(1.0, total_conf / max(matches, 1))
        else:
            best_task = 'general_chat'
            confidence = 0.3

        # Calculate complexity
        complexity = self._calculate_complexity(query_lower)

        return best_task, confidence, complexity

    def _calculate_complexity(self, query_lower: str) -> float:
        """Calculate complexity score (0-1) based on patterns."""
        complexity = 0.5  # Default medium
        patterns = self._get_complexity_patterns()

        for pattern in patterns:
            if pattern.compiled_regex and pattern.compiled_regex.search(query_lower):
                if pattern.indicator_type == 'high':
                    complexity = min(1.0, complexity + pattern.weight)
                else:  # 'low'
                    complexity = max(0.0, complexity - pattern.weight)

        # Query length factor
        length = len(query_lower)
        if length > 500:
            complexity = min(1.0, complexity + 0.1)
        elif length < 30:
            complexity = max(0.0, complexity - 0.1)

        return round(complexity, 2)

    def _record_pattern_hit(self, pattern_id: int) -> None:
        """Record that a pattern was matched (async/fire-and-forget)."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE jarvis_task_patterns
                        SET hit_count = hit_count + 1, last_hit = NOW()
                        WHERE id = %s
                    """, (pattern_id,))
                conn.commit()
        except Exception:
            pass  # Non-critical

    # ========== MODEL SELECTION ==========

    def select_model(
        self,
        query: str,
        force_provider: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> ModelSelection:
        """
        Select the best model for a query.

        Uses database patterns, rules, and learning data.
        """
        # Classify the query
        task_type, classification_confidence, complexity = self.classify_task(query)
        models = self._get_models()
        rules = self._get_selection_rules()

        # Initialize selection state
        cost_sensitivity = 0.7  # Default
        preferred_provider: Optional[str] = force_provider
        preferred_models: List[str] = []
        capability_boosts: Dict[str, float] = {}
        rules_applied: List[str] = []

        if not preferred_provider:
            local_first_provider = self._get_local_first_provider(task_type, complexity, context)
            if local_first_provider:
                preferred_provider = local_first_provider
                rules_applied.append('local_first_capability_router')

        # Apply rules in priority order
        current_hour = datetime.now().hour
        for rule in rules:
            if not self._evaluate_rule_condition(rule, task_type, complexity, current_hour):
                continue

            rules_applied.append(rule.rule_name)
            self._record_rule_applied(rule.id)

            if rule.action_type == 'set_cost_sensitivity':
                cost_sensitivity = rule.action_value.get('value', cost_sensitivity)
            elif rule.action_type == 'prefer_provider' and not force_provider:
                preferred_provider = rule.action_value.get('provider')
            elif rule.action_type == 'prefer_model':
                preferred_models.extend(rule.action_value.get('models', []))
            elif rule.action_type == 'boost_capability':
                for cap, boost in rule.action_value.get('boosts', {}).items():
                    capability_boosts[cap] = capability_boosts.get(cap, 0) + boost

        # Select model based on rules and preferences
        selected_model_id = None
        reason = ""

        # First: Check preferred models
        for model_id in preferred_models:
            if model_id in models:
                config = models[model_id]
                if preferred_provider and config.provider.value != preferred_provider:
                    continue
                selected_model_id = model_id
                reason = f"Preferred model for {task_type}"
                break

        # Second: Try task-model mapping from DB
        if not selected_model_id:
            selected_model_id, reason = self._select_from_mapping(
                task_type, complexity, preferred_provider
            )

        # Third: Score-based selection
        if not selected_model_id:
            selected_model_id = self._select_by_score(
                task_type, complexity, cost_sensitivity,
                preferred_provider, capability_boosts
            )
            reason = f"Best score for {task_type} @ {complexity}"

        # Fallback
        if not selected_model_id or selected_model_id not in models:
            selected_model_id = self._get_default_model(preferred_provider)
            reason = f"Fallback: {preferred_provider or 'default'}"

        model_config = models.get(selected_model_id, list(models.values())[0])

        return ModelSelection(
            model_id=selected_model_id,
            provider=model_config.provider,
            task_type=task_type,
            complexity=complexity,
            reason=reason,
            rules_applied=rules_applied,
            confidence=classification_confidence,
        )

    def _evaluate_rule_condition(
        self,
        rule: SelectionRule,
        task_type: str,
        complexity: float,
        current_hour: int
    ) -> bool:
        """Evaluate if a rule's condition is met."""
        cond = rule.condition

        if rule.rule_type == 'complexity_threshold':
            min_c = cond.get('complexity_min', 0.0)
            max_c = cond.get('complexity_max', 1.0)
            return min_c <= complexity <= max_c

        elif rule.rule_type == 'task_type_match':
            task_types = cond.get('task_types', [])
            return task_type in task_types

        elif rule.rule_type == 'time_based':
            hour_start = cond.get('hour_start', 0)
            hour_end = cond.get('hour_end', 24)
            if hour_start > hour_end:  # Overnight range
                return current_hour >= hour_start or current_hour < hour_end
            return hour_start <= current_hour < hour_end

        return False

    def _record_rule_applied(self, rule_id: int) -> None:
        """Record that a rule was applied."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE jarvis_selection_rules
                        SET times_applied = times_applied + 1, last_applied = NOW()
                        WHERE id = %s
                    """, (rule_id,))
                conn.commit()
        except Exception:
            pass

    def _select_from_mapping(
        self,
        task_type: str,
        complexity: float,
        force_provider: Optional[str]
    ) -> Tuple[Optional[str], str]:
        """Select model from task-model mapping table."""
        try:
            with get_conn() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    query_sql = """
                        SELECT m.model_id, m.provider, tm.jarvis_override, tm.override_reason
                        FROM jarvis_task_model_mapping tm
                        JOIN jarvis_model_registry m ON tm.model_id = m.model_id
                        WHERE tm.task_type = %s
                          AND m.is_active = TRUE
                          AND %s >= tm.min_complexity
                          AND %s <= tm.max_complexity
                    """
                    params = [task_type, complexity, complexity]

                    if force_provider:
                        query_sql += " AND m.provider = %s"
                        params.append(force_provider)

                    query_sql += """
                        ORDER BY
                            tm.jarvis_override DESC,
                            tm.success_rate DESC,
                            tm.priority ASC
                        LIMIT 1
                    """

                    cur.execute(query_sql, params)
                    row = cur.fetchone()

                    if row:
                        if row['jarvis_override']:
                            reason = f"Jarvis override: {row['override_reason'] or 'optimized'}"
                        else:
                            reason = f"Task mapping: {task_type} @ {complexity}"
                        return row['model_id'], reason

        except Exception as e:
            logger.warning(f"Failed to query task mappings: {e}")

        return None, ""

    def _select_by_score(
        self,
        task_type: str,
        complexity: float,
        cost_sensitivity: float,
        force_provider: Optional[str],
        capability_boosts: Dict[str, float]
    ) -> str:
        """Select model by computing a score."""
        models = self._get_models()

        # Get task weights
        weights = self._get_task_weights(task_type)

        best_model = None
        best_score = -float('inf')

        for model_id, config in models.items():
            if force_provider and config.provider.value != force_provider:
                continue

            # Capability score
            cap_score = 0.0
            for cap_name, cap_weight in weights.items():
                cap_value = config.capabilities.get(cap_name, 0.5)
                boost = capability_boosts.get(cap_name, 0.0)
                cap_score += cap_weight * (cap_value + boost)

            # Cost penalty
            avg_cost = (config.cost_input_per_1m + config.cost_output_per_1m) / 2000
            cost_penalty = avg_cost * cost_sensitivity * 5

            # Efficiency bonus (from learning)
            efficiency_bonus = (config.efficiency_score - 0.5) * 0.2

            # Final score
            score = cap_score - cost_penalty + efficiency_bonus

            # High complexity: value capability more
            if complexity > 0.7:
                score = cap_score * 1.3 - cost_penalty * 0.5 + efficiency_bonus

            if score > best_score:
                best_score = score
                best_model = model_id

        return best_model or self._get_default_model(force_provider)

    def _get_task_weights(self, task_type: str) -> Dict[str, float]:
        """Get capability weights for a task type."""
        defaults = {
            'reasoning': 0.5, 'coding': 0.0, 'creative': 0.0,
            'analysis': 0.5, 'math': 0.0, 'speed': 0.5
        }

        try:
            with get_conn() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("""
                        SELECT weight_reasoning, weight_coding, weight_creative,
                               weight_analysis, weight_math, weight_speed
                        FROM jarvis_task_types
                        WHERE task_type = %s
                    """, (task_type,))
                    row = cur.fetchone()
                    if row:
                        return {
                            'reasoning': float(row['weight_reasoning']),
                            'coding': float(row['weight_coding']),
                            'creative': float(row['weight_creative']),
                            'analysis': float(row['weight_analysis']),
                            'math': float(row['weight_math']),
                            'speed': float(row['weight_speed']),
                        }
        except Exception:
            pass

        return defaults

    def _get_default_model(self, force_provider: Optional[str] = None) -> str:
        """Get the cheapest active model for a provider."""
        try:
            with get_conn() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    if force_provider:
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

        if force_provider == 'ollama':
            return DEFAULT_OLLAMA_MODEL
        if force_provider == 'anthropic':
            return 'claude-haiku-4-5-20251001'
        return 'gpt-4o-mini'

    # ========== USAGE LOGGING ==========

    def log_usage(
        self,
        model_id: str,
        task_type: str,
        query: str,
        latency_ms: int,
        input_tokens: int,
        output_tokens: int,
        success: bool = True,
        quality_score: Optional[float] = None,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None
    ) -> None:
        """Log model usage for learning."""
        try:
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
                    # Log to usage table
                    cur.execute("""
                        INSERT INTO jarvis_model_usage_log
                        (model_id, task_type, query_preview, latency_ms,
                         input_tokens, output_tokens, cost_usd, success,
                         quality_score, user_id, session_id)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        model_id, task_type, query[:200], latency_ms,
                        input_tokens, output_tokens, cost_usd, success,
                        quality_score, user_id, session_id
                    ))

                    # Update task mapping statistics
                    cur.execute("""
                        UPDATE jarvis_task_model_mapping
                        SET times_used = times_used + 1,
                            avg_latency_ms = (avg_latency_ms * times_used + %s) / (times_used + 1),
                            updated_at = NOW()
                        WHERE task_type = %s AND model_id = %s
                    """, (latency_ms, task_type, model_id))

                    # Update model total uses
                    cur.execute("""
                        UPDATE jarvis_model_registry
                        SET total_uses = COALESCE(total_uses, 0) + 1
                        WHERE model_id = %s
                    """, (model_id,))

                conn.commit()

        except Exception as e:
            logger.warning(f"Failed to log model usage: {e}")

    # ========== LEARNING & STATS ==========

    def get_usage_stats(self, days: int = 7) -> Dict[str, Any]:
        """Get usage statistics for analysis."""
        try:
            with get_conn() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    # Overall stats
                    cur.execute("""
                        SELECT
                            COUNT(*) as total_requests,
                            SUM(cost_usd) as total_cost,
                            AVG(latency_ms) as avg_latency,
                            AVG(CASE WHEN success THEN 1.0 ELSE 0.0 END) as success_rate
                        FROM jarvis_model_usage_log
                        WHERE created_at > NOW() - INTERVAL '%s days'
                    """, (days,))
                    overall = cur.fetchone()

                    # By model
                    cur.execute("""
                        SELECT
                            model_id,
                            COUNT(*) as calls,
                            SUM(cost_usd) as cost,
                            AVG(latency_ms) as avg_latency,
                            AVG(CASE WHEN success THEN 1.0 ELSE 0.0 END) as success_rate
                        FROM jarvis_model_usage_log
                        WHERE created_at > NOW() - INTERVAL '%s days'
                        GROUP BY model_id
                        ORDER BY calls DESC
                    """, (days,))
                    by_model = [dict(row) for row in cur.fetchall()]

                    # By task
                    cur.execute("""
                        SELECT
                            task_type,
                            COUNT(*) as calls,
                            SUM(cost_usd) as cost,
                            AVG(latency_ms) as avg_latency
                        FROM jarvis_model_usage_log
                        WHERE created_at > NOW() - INTERVAL '%s days'
                        GROUP BY task_type
                        ORDER BY calls DESC
                    """, (days,))
                    by_task = [dict(row) for row in cur.fetchall()]

                    # Most applied rules
                    cur.execute("""
                        SELECT rule_name, times_applied, last_applied
                        FROM jarvis_selection_rules
                        WHERE is_active = TRUE
                        ORDER BY times_applied DESC
                        LIMIT 10
                    """)
                    top_rules = [dict(row) for row in cur.fetchall()]

                    return {
                        'success': True,
                        'period_days': days,
                        'overall': {
                            'total_requests': overall['total_requests'] or 0,
                            'total_cost_usd': round(float(overall['total_cost'] or 0), 4),
                            'avg_latency_ms': round(float(overall['avg_latency'] or 0), 0),
                            'success_rate': round(float(overall['success_rate'] or 0), 3),
                        },
                        'by_model': by_model,
                        'by_task': by_task,
                        'top_rules': top_rules,
                    }

        except Exception as e:
            logger.warning(f"Failed to get usage stats: {e}")
            return {'success': False, 'error': str(e)}


# Singleton instance
_router: Optional[DynamicModelRouter] = None


def get_dynamic_model_router() -> DynamicModelRouter:
    """Get or create the dynamic model router singleton."""
    global _router
    if _router is None:
        _router = DynamicModelRouter()
    return _router
