"""
Model Management Tools for Jarvis.

These tools allow Jarvis to autonomously manage the model registry
and optimize model selection based on experience.
"""

import logging
from typing import Dict, Any, Optional, List
from app.postgres_state import get_conn
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)


def list_available_models() -> Dict[str, Any]:
    """
    List all available models with their capabilities and costs.

    Returns a summary of all active models that Jarvis can use.
    """
    try:
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT
                        model_id, provider, display_name,
                        cost_input_per_1m, cost_output_per_1m,
                        cap_reasoning, cap_coding, cap_creative,
                        cap_analysis, cap_math, cap_speed,
                        max_tokens, context_window,
                        is_default, notes
                    FROM jarvis_model_registry
                    WHERE is_active = TRUE
                    ORDER BY
                        cost_input_per_1m + cost_output_per_1m ASC
                """)

                models = []
                for row in cur.fetchall():
                    avg_cost = (float(row['cost_input_per_1m']) + float(row['cost_output_per_1m'])) / 2
                    models.append({
                        'model_id': row['model_id'],
                        'provider': row['provider'],
                        'display_name': row['display_name'],
                        'avg_cost_per_1m': round(avg_cost, 2),
                        'is_default': row['is_default'],
                        'best_for': _get_best_capabilities(row),
                        'notes': row['notes'],
                    })

                return {
                    'success': True,
                    'models': models,
                    'total_active': len(models),
                }

    except Exception as e:
        logger.error(f"Failed to list models: {e}")
        return {'success': False, 'error': str(e)}


def _get_best_capabilities(row: Dict) -> List[str]:
    """Get the top capabilities for a model."""
    caps = {
        'reasoning': float(row['cap_reasoning']),
        'coding': float(row['cap_coding']),
        'creative': float(row['cap_creative']),
        'analysis': float(row['cap_analysis']),
        'math': float(row['cap_math']),
        'speed': float(row['cap_speed']),
    }
    # Return capabilities above 0.8
    return [k for k, v in sorted(caps.items(), key=lambda x: -x[1]) if v >= 0.8]


def get_model_details(model_id: str) -> Dict[str, Any]:
    """
    Get detailed information about a specific model.

    Args:
        model_id: The model identifier (e.g., 'gpt-4o-mini', 'claude-sonnet-4-20250514')
    """
    try:
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT * FROM jarvis_model_registry
                    WHERE model_id = %s
                """, (model_id,))

                row = cur.fetchone()
                if not row:
                    return {'success': False, 'error': f'Model {model_id} not found'}

                # Get usage stats
                cur.execute("""
                    SELECT
                        COUNT(*) as total_uses,
                        SUM(cost_usd) as total_cost,
                        AVG(latency_ms) as avg_latency,
                        AVG(CASE WHEN success THEN 1 ELSE 0 END) as success_rate
                    FROM jarvis_model_usage_log
                    WHERE model_id = %s
                    AND created_at > NOW() - INTERVAL '30 days'
                """, (model_id,))

                stats = cur.fetchone()

                return {
                    'success': True,
                    'model': dict(row),
                    'usage_30d': {
                        'total_uses': stats['total_uses'] or 0,
                        'total_cost_usd': round(float(stats['total_cost'] or 0), 4),
                        'avg_latency_ms': round(float(stats['avg_latency'] or 0), 0),
                        'success_rate': round(float(stats['success_rate'] or 0), 3),
                    }
                }

    except Exception as e:
        logger.error(f"Failed to get model details: {e}")
        return {'success': False, 'error': str(e)}


def update_model_settings(
    model_id: str,
    is_active: Optional[bool] = None,
    is_default: Optional[bool] = None,
    notes: Optional[str] = None,
    cap_reasoning: Optional[float] = None,
    cap_coding: Optional[float] = None,
    cap_creative: Optional[float] = None,
    cap_analysis: Optional[float] = None,
    cap_math: Optional[float] = None,
    cap_speed: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Update settings for a model.

    Jarvis can use this to:
    - Deactivate underperforming models
    - Set a new default model
    - Adjust capability scores based on experience
    """
    try:
        updates = []
        params = []

        if is_active is not None:
            updates.append("is_active = %s")
            params.append(is_active)

        if is_default is not None:
            updates.append("is_default = %s")
            params.append(is_default)

        if notes is not None:
            updates.append("notes = %s")
            params.append(notes)

        for cap_name in ['reasoning', 'coding', 'creative', 'analysis', 'math', 'speed']:
            cap_value = locals().get(f'cap_{cap_name}')
            if cap_value is not None:
                if not 0 <= cap_value <= 1:
                    return {'success': False, 'error': f'cap_{cap_name} must be between 0 and 1'}
                updates.append(f"cap_{cap_name} = %s")
                params.append(cap_value)

        if not updates:
            return {'success': False, 'error': 'No updates provided'}

        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(model_id)

        with get_conn() as conn:
            with conn.cursor() as cur:
                # If setting as default, unset others first
                if is_default:
                    cur.execute("UPDATE jarvis_model_registry SET is_default = FALSE")

                cur.execute(f"""
                    UPDATE jarvis_model_registry
                    SET {', '.join(updates)}
                    WHERE model_id = %s
                """, params)

                if cur.rowcount == 0:
                    return {'success': False, 'error': f'Model {model_id} not found'}

            conn.commit()

        return {
            'success': True,
            'model_id': model_id,
            'updates_applied': len(updates) - 1,  # -1 for updated_at
        }

    except Exception as e:
        logger.error(f"Failed to update model: {e}")
        return {'success': False, 'error': str(e)}


def override_task_model(
    task_type: str,
    model_id: str,
    reason: str,
    min_complexity: float = 0.0,
    max_complexity: float = 1.0,
) -> Dict[str, Any]:
    """
    Override the model selection for a task type.

    Jarvis can use this to optimize model selection based on experience.
    The override takes priority over the default mapping.

    Args:
        task_type: The task type (e.g., 'code_generation', 'quick_question')
        model_id: The model to use for this task
        reason: Why this override is being applied
        min_complexity: Minimum complexity level for this override (0-1)
        max_complexity: Maximum complexity level for this override (0-1)
    """
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                # Check if model exists
                cur.execute("SELECT 1 FROM jarvis_model_registry WHERE model_id = %s AND is_active = TRUE", (model_id,))
                if not cur.fetchone():
                    return {'success': False, 'error': f'Model {model_id} not found or inactive'}

                # Check if task type exists
                cur.execute("SELECT 1 FROM jarvis_task_types WHERE task_type = %s", (task_type,))
                if not cur.fetchone():
                    return {'success': False, 'error': f'Task type {task_type} not found'}

                # Insert or update the mapping
                cur.execute("""
                    INSERT INTO jarvis_task_model_mapping
                    (task_type, model_id, priority, min_complexity, max_complexity,
                     jarvis_override, override_reason)
                    VALUES (%s, %s, 0, %s, %s, TRUE, %s)
                    ON CONFLICT (task_type, model_id)
                    DO UPDATE SET
                        priority = 0,
                        min_complexity = EXCLUDED.min_complexity,
                        max_complexity = EXCLUDED.max_complexity,
                        jarvis_override = TRUE,
                        override_reason = EXCLUDED.override_reason,
                        updated_at = CURRENT_TIMESTAMP
                """, (task_type, model_id, min_complexity, max_complexity, reason))

            conn.commit()

        return {
            'success': True,
            'task_type': task_type,
            'model_id': model_id,
            'reason': reason,
            'complexity_range': [min_complexity, max_complexity],
        }

    except Exception as e:
        logger.error(f"Failed to override task model: {e}")
        return {'success': False, 'error': str(e)}


def get_model_usage_stats(days: int = 7) -> Dict[str, Any]:
    """
    Get model usage statistics for the past N days.

    Jarvis can use this to analyze which models are performing well
    and optimize the configuration.
    """
    try:
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Overall stats
                cur.execute("""
                    SELECT
                        COUNT(*) as total_requests,
                        SUM(cost_usd) as total_cost,
                        AVG(latency_ms) as avg_latency,
                        AVG(CASE WHEN success THEN 1 ELSE 0 END) as success_rate
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
                        AVG(CASE WHEN success THEN 1 ELSE 0 END) as success_rate
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

                # Cost savings estimate (vs always using most expensive)
                cur.execute("""
                    SELECT
                        l.model_id,
                        l.input_tokens,
                        l.output_tokens,
                        m.cost_input_per_1m,
                        m.cost_output_per_1m
                    FROM jarvis_model_usage_log l
                    JOIN jarvis_model_registry m ON l.model_id = m.model_id
                    WHERE l.created_at > NOW() - INTERVAL '%s days'
                """, (days,))

                actual_cost = 0
                expensive_cost = 0
                for row in cur.fetchall():
                    actual_cost += (row['input_tokens'] / 1_000_000 * float(row['cost_input_per_1m']) +
                                   row['output_tokens'] / 1_000_000 * float(row['cost_output_per_1m']))
                    # If we used opus for everything
                    expensive_cost += (row['input_tokens'] / 1_000_000 * 15.0 +
                                      row['output_tokens'] / 1_000_000 * 75.0)

                savings = expensive_cost - actual_cost

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
                    'cost_savings': {
                        'actual_cost': round(actual_cost, 4),
                        'if_always_opus': round(expensive_cost, 4),
                        'savings_usd': round(savings, 4),
                        'savings_percent': round(savings / expensive_cost * 100, 1) if expensive_cost > 0 else 0,
                    }
                }

    except Exception as e:
        logger.error(f"Failed to get usage stats: {e}")
        return {'success': False, 'error': str(e)}


def list_task_types() -> Dict[str, Any]:
    """
    List all task types and their current model mappings.
    """
    try:
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT
                        t.task_type,
                        t.description,
                        t.cost_sensitivity,
                        ARRAY_AGG(
                            tm.model_id ORDER BY tm.priority
                        ) FILTER (WHERE tm.model_id IS NOT NULL) as models,
                        BOOL_OR(tm.jarvis_override) as has_override
                    FROM jarvis_task_types t
                    LEFT JOIN jarvis_task_model_mapping tm ON t.task_type = tm.task_type
                    GROUP BY t.task_type, t.description, t.cost_sensitivity
                    ORDER BY t.task_type
                """)

                tasks = [dict(row) for row in cur.fetchall()]

                return {
                    'success': True,
                    'task_types': tasks,
                    'total': len(tasks),
                }

    except Exception as e:
        logger.error(f"Failed to list task types: {e}")
        return {'success': False, 'error': str(e)}


def add_model(
    model_id: str,
    provider: str,
    display_name: str,
    cost_input_per_1m: float,
    cost_output_per_1m: float,
    cap_reasoning: float = 0.5,
    cap_coding: float = 0.5,
    cap_creative: float = 0.5,
    cap_analysis: float = 0.5,
    cap_math: float = 0.5,
    cap_speed: float = 0.5,
    max_tokens: int = 4096,
    context_window: int = 128000,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Add a new model to the registry.

    Jarvis can use this to add newly released models.
    """
    if provider not in ['openai', 'anthropic']:
        return {'success': False, 'error': 'Provider must be openai or anthropic'}

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO jarvis_model_registry
                    (model_id, provider, display_name, cost_input_per_1m, cost_output_per_1m,
                     cap_reasoning, cap_coding, cap_creative, cap_analysis, cap_math, cap_speed,
                     max_tokens, context_window, notes)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (model_id) DO UPDATE SET
                        cost_input_per_1m = EXCLUDED.cost_input_per_1m,
                        cost_output_per_1m = EXCLUDED.cost_output_per_1m,
                        updated_at = CURRENT_TIMESTAMP
                """, (
                    model_id, provider, display_name, cost_input_per_1m, cost_output_per_1m,
                    cap_reasoning, cap_coding, cap_creative, cap_analysis, cap_math, cap_speed,
                    max_tokens, context_window, notes
                ))
            conn.commit()

        return {
            'success': True,
            'model_id': model_id,
            'provider': provider,
            'message': f'Model {display_name} added successfully'
        }

    except Exception as e:
        logger.error(f"Failed to add model: {e}")
        return {'success': False, 'error': str(e)}


# Tool definitions for Jarvis
MODEL_MANAGEMENT_TOOLS = [
    {
        "name": "list_available_models",
        "description": "List all available AI models with their costs and capabilities. Use this to see what models are available for routing.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "get_model_details",
        "description": "Get detailed information about a specific model including usage statistics.",
        "input_schema": {
            "type": "object",
            "properties": {
                "model_id": {
                    "type": "string",
                    "description": "The model identifier (e.g., 'gpt-4o-mini', 'claude-sonnet-4-20250514')"
                }
            },
            "required": ["model_id"]
        }
    },
    {
        "name": "update_model_settings",
        "description": "Update settings for a model - activate/deactivate, set as default, or adjust capability scores based on experience.",
        "input_schema": {
            "type": "object",
            "properties": {
                "model_id": {"type": "string", "description": "The model to update"},
                "is_active": {"type": "boolean", "description": "Whether the model should be available for use"},
                "is_default": {"type": "boolean", "description": "Set as the default model (cheapest for simple tasks)"},
                "notes": {"type": "string", "description": "Notes about the model"},
                "cap_reasoning": {"type": "number", "description": "Reasoning capability score (0-1)"},
                "cap_coding": {"type": "number", "description": "Coding capability score (0-1)"},
                "cap_creative": {"type": "number", "description": "Creative capability score (0-1)"},
                "cap_analysis": {"type": "number", "description": "Analysis capability score (0-1)"},
                "cap_math": {"type": "number", "description": "Math capability score (0-1)"},
                "cap_speed": {"type": "number", "description": "Speed score (0-1, higher is faster)"},
            },
            "required": ["model_id"]
        }
    },
    {
        "name": "override_task_model",
        "description": "Override which model is used for a specific task type. Use this to optimize based on experience.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_type": {
                    "type": "string",
                    "description": "Task type (e.g., 'code_generation', 'quick_question', 'math_reasoning')",
                    "enum": ["general_chat", "quick_question", "code_generation", "code_review",
                            "debugging", "analysis", "creative_writing", "math_reasoning",
                            "planning", "summarization", "translation", "tool_execution"]
                },
                "model_id": {"type": "string", "description": "The model to use for this task"},
                "reason": {"type": "string", "description": "Why this override is being applied"},
                "min_complexity": {"type": "number", "description": "Minimum complexity (0-1) for this override"},
                "max_complexity": {"type": "number", "description": "Maximum complexity (0-1) for this override"},
            },
            "required": ["task_type", "model_id", "reason"]
        }
    },
    {
        "name": "get_model_usage_stats",
        "description": "Get model usage statistics and cost analysis. Use this to analyze performance and optimize routing.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "Number of days to analyze (default: 7)"}
            },
            "required": []
        }
    },
    {
        "name": "list_task_types",
        "description": "List all task types and their current model mappings.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "add_model",
        "description": "Add a new model to the registry (e.g., when a new model is released).",
        "input_schema": {
            "type": "object",
            "properties": {
                "model_id": {"type": "string", "description": "The model identifier"},
                "provider": {"type": "string", "enum": ["openai", "anthropic"], "description": "Model provider"},
                "display_name": {"type": "string", "description": "Human-readable name"},
                "cost_input_per_1m": {"type": "number", "description": "Cost per 1M input tokens in USD"},
                "cost_output_per_1m": {"type": "number", "description": "Cost per 1M output tokens in USD"},
                "cap_reasoning": {"type": "number", "description": "Reasoning capability (0-1)"},
                "cap_coding": {"type": "number", "description": "Coding capability (0-1)"},
                "cap_creative": {"type": "number", "description": "Creative capability (0-1)"},
                "cap_analysis": {"type": "number", "description": "Analysis capability (0-1)"},
                "cap_math": {"type": "number", "description": "Math capability (0-1)"},
                "cap_speed": {"type": "number", "description": "Speed score (0-1)"},
                "max_tokens": {"type": "integer", "description": "Maximum output tokens"},
                "context_window": {"type": "integer", "description": "Context window size"},
                "notes": {"type": "string", "description": "Notes about the model"},
            },
            "required": ["model_id", "provider", "display_name", "cost_input_per_1m", "cost_output_per_1m"]
        }
    },
]
