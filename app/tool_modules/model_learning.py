"""
Model Learning Tools for Jarvis.

These tools allow Jarvis to learn and optimize model selection:
- Add/modify task classification patterns
- Adjust model priorities
- Report model performance
- Get optimization recommendations
"""

import logging
from typing import Dict, Any, Optional, List
from app.postgres_state import get_conn
from psycopg2.extras import RealDictCursor
import json

logger = logging.getLogger(__name__)


def learn_task_pattern(
    task_type: str,
    pattern_text: str,
    pattern_type: str = 'keyword',
    language: str = 'both',
    confidence: float = 0.7,
    reason: str = ''
) -> Dict[str, Any]:
    """
    Learn a new pattern for task classification.

    Use this when you notice a query type that isn't being classified correctly.

    Args:
        task_type: The task category (code_generation, debugging, analysis, etc.)
        pattern_text: The pattern to match (keyword, phrase, or regex)
        pattern_type: 'keyword', 'phrase', or 'regex'
        language: 'de', 'en', or 'both'
        confidence: Initial confidence (0-1)
        reason: Why this pattern should be learned
    """
    valid_task_types = [
        'code_generation', 'code_review', 'debugging', 'math_reasoning',
        'analysis', 'creative_writing', 'planning', 'summarization',
        'translation', 'quick_question', 'general_chat', 'tool_execution'
    ]

    if task_type not in valid_task_types:
        return {'success': False, 'error': f'Invalid task_type. Must be one of: {valid_task_types}'}

    if pattern_type not in ['keyword', 'phrase', 'regex']:
        return {'success': False, 'error': 'pattern_type must be keyword, phrase, or regex'}

    if not 0 <= confidence <= 1:
        return {'success': False, 'error': 'confidence must be between 0 and 1'}

    try:
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Check if pattern already exists
                cur.execute("""
                    SELECT id, is_active, confidence FROM jarvis_task_patterns
                    WHERE task_type = %s AND pattern_text = %s
                """, (task_type, pattern_text))
                existing = cur.fetchone()

                if existing:
                    if existing['is_active']:
                        return {
                            'success': False,
                            'error': f'Pattern already exists with confidence {existing["confidence"]}'
                        }
                    else:
                        # Reactivate
                        cur.execute("""
                            UPDATE jarvis_task_patterns
                            SET is_active = TRUE, confidence = %s, updated_at = NOW(),
                                source = 'jarvis_override', notes = %s
                            WHERE id = %s
                        """, (confidence, reason, existing['id']))
                        action = 'reactivated'
                        pattern_id = existing['id']
                else:
                    # Insert new
                    cur.execute("""
                        INSERT INTO jarvis_task_patterns
                        (task_type, pattern_text, pattern_type, language, confidence,
                         source, created_by, notes)
                        VALUES (%s, %s, %s, %s, %s, 'jarvis', 'jarvis', %s)
                        RETURNING id
                    """, (task_type, pattern_text, pattern_type, language, confidence, reason))
                    pattern_id = cur.fetchone()['id']
                    action = 'created'

                # Log the learning
                cur.execute("""
                    INSERT INTO jarvis_pattern_learning_log
                    (action_type, table_name, record_id, new_value, reason, initiated_by, confidence)
                    VALUES ('pattern_added', 'jarvis_task_patterns', %s, %s, %s, 'jarvis', %s)
                """, (pattern_id, json.dumps({
                    'task_type': task_type,
                    'pattern_text': pattern_text,
                    'pattern_type': pattern_type
                }), reason, confidence))

            conn.commit()

        # Clear router cache
        try:
            from app.services.dynamic_model_router import get_dynamic_model_router
            get_dynamic_model_router()._clear_cache()
        except Exception:
            pass

        return {
            'success': True,
            'action': action,
            'pattern_id': pattern_id,
            'task_type': task_type,
            'pattern_text': pattern_text,
            'message': f'Pattern {action} for {task_type}'
        }

    except Exception as e:
        logger.error(f"Failed to learn pattern: {e}")
        return {'success': False, 'error': str(e)}


def adjust_model_priority(
    task_type: str,
    model_id: str,
    new_priority: int,
    reason: str,
    min_complexity: float = 0.0,
    max_complexity: float = 1.0
) -> Dict[str, Any]:
    """
    Adjust which model is preferred for a task type.

    Lower priority = higher preference (priority 1 is chosen first).

    Args:
        task_type: The task category
        model_id: The model to prioritize
        new_priority: New priority (1-100, lower = higher preference)
        reason: Why this adjustment is being made
        min_complexity: Minimum complexity for this mapping (0-1)
        max_complexity: Maximum complexity for this mapping (0-1)
    """
    try:
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Verify model exists
                cur.execute("SELECT 1 FROM jarvis_model_registry WHERE model_id = %s AND is_active = TRUE", (model_id,))
                if not cur.fetchone():
                    return {'success': False, 'error': f'Model {model_id} not found or inactive'}

                # Check existing mapping
                cur.execute("""
                    SELECT id, priority, jarvis_override FROM jarvis_task_model_mapping
                    WHERE task_type = %s AND model_id = %s
                """, (task_type, model_id))
                existing = cur.fetchone()

                old_priority = existing['priority'] if existing else None

                if existing:
                    cur.execute("""
                        UPDATE jarvis_task_model_mapping
                        SET priority = %s, min_complexity = %s, max_complexity = %s,
                            jarvis_override = TRUE, override_reason = %s, updated_at = NOW()
                        WHERE id = %s
                    """, (new_priority, min_complexity, max_complexity, reason, existing['id']))
                    mapping_id = existing['id']
                else:
                    cur.execute("""
                        INSERT INTO jarvis_task_model_mapping
                        (task_type, model_id, priority, min_complexity, max_complexity,
                         jarvis_override, override_reason)
                        VALUES (%s, %s, %s, %s, %s, TRUE, %s)
                        RETURNING id
                    """, (task_type, model_id, new_priority, min_complexity, max_complexity, reason))
                    mapping_id = cur.fetchone()['id']

                # Log the change
                cur.execute("""
                    INSERT INTO jarvis_pattern_learning_log
                    (action_type, table_name, record_id, old_value, new_value, reason, initiated_by)
                    VALUES ('priority_changed', 'jarvis_task_model_mapping', %s, %s, %s, %s, 'jarvis')
                """, (
                    mapping_id,
                    json.dumps({'priority': old_priority}) if old_priority else None,
                    json.dumps({'priority': new_priority, 'complexity_range': [min_complexity, max_complexity]}),
                    reason
                ))

            conn.commit()

        # Clear cache
        try:
            from app.services.dynamic_model_router import get_dynamic_model_router
            get_dynamic_model_router()._clear_cache()
        except Exception:
            pass

        return {
            'success': True,
            'task_type': task_type,
            'model_id': model_id,
            'old_priority': old_priority,
            'new_priority': new_priority,
            'complexity_range': [min_complexity, max_complexity],
            'message': f'Model {model_id} now has priority {new_priority} for {task_type}'
        }

    except Exception as e:
        logger.error(f"Failed to adjust priority: {e}")
        return {'success': False, 'error': str(e)}


def report_model_performance(
    model_id: str,
    task_type: str,
    quality_score: float,
    feedback: str = ''
) -> Dict[str, Any]:
    """
    Report that a model performed well or poorly for a specific task.

    This helps Jarvis learn which models work best for which tasks.

    Args:
        model_id: The model that was used
        task_type: The task type it was used for
        quality_score: Quality rating (0-1, where 1 is excellent)
        feedback: Optional text feedback about the performance
    """
    if not 0 <= quality_score <= 1:
        return {'success': False, 'error': 'quality_score must be between 0 and 1'}

    try:
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Update most recent usage log entry
                cur.execute("""
                    UPDATE jarvis_model_usage_log
                    SET quality_score = %s
                    WHERE id = (
                        SELECT id FROM jarvis_model_usage_log
                        WHERE model_id = %s AND task_type = %s
                        ORDER BY created_at DESC
                        LIMIT 1
                    )
                    RETURNING id
                """, (quality_score, model_id, task_type))
                updated = cur.fetchone()

                # Update model learning stats
                cur.execute("""
                    INSERT INTO jarvis_model_learning
                    (task_type, model_id, total_uses, avg_quality_score)
                    VALUES (%s, %s, 1, %s)
                    ON CONFLICT (task_type, model_id, context_type)
                    DO UPDATE SET
                        total_uses = jarvis_model_learning.total_uses + 1,
                        avg_quality_score = (
                            jarvis_model_learning.avg_quality_score * jarvis_model_learning.total_uses + %s
                        ) / (jarvis_model_learning.total_uses + 1),
                        last_updated = NOW()
                """, (task_type, model_id, quality_score, quality_score))

                # Update task mapping success rate
                if quality_score >= 0.7:
                    cur.execute("""
                        UPDATE jarvis_task_model_mapping
                        SET success_rate = (success_rate * times_used + 1) / (times_used + 1)
                        WHERE task_type = %s AND model_id = %s
                    """, (task_type, model_id))
                else:
                    cur.execute("""
                        UPDATE jarvis_task_model_mapping
                        SET success_rate = (success_rate * times_used) / (times_used + 1)
                        WHERE task_type = %s AND model_id = %s
                    """, (task_type, model_id))

                # Log feedback if provided
                if feedback:
                    cur.execute("""
                        INSERT INTO jarvis_pattern_learning_log
                        (action_type, table_name, new_value, reason, initiated_by, confidence)
                        VALUES ('performance_report', 'jarvis_model_learning', %s, %s, 'jarvis', %s)
                    """, (
                        json.dumps({'model_id': model_id, 'task_type': task_type, 'quality_score': quality_score}),
                        feedback,
                        quality_score
                    ))

            conn.commit()

        return {
            'success': True,
            'model_id': model_id,
            'task_type': task_type,
            'quality_score': quality_score,
            'updated_log': updated['id'] if updated else None,
            'message': f'Performance recorded: {model_id} scored {quality_score} for {task_type}'
        }

    except Exception as e:
        logger.error(f"Failed to report performance: {e}")
        return {'success': False, 'error': str(e)}


def get_model_recommendations(days: int = 30) -> Dict[str, Any]:
    """
    Get AI-driven recommendations for model selection optimization.

    Analyzes usage patterns and suggests improvements.

    Args:
        days: Number of days to analyze
    """
    try:
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                recommendations = []

                # 1. Find underperforming models by task
                cur.execute("""
                    SELECT
                        task_type,
                        model_id,
                        COUNT(*) as uses,
                        AVG(latency_ms) as avg_latency,
                        AVG(quality_score) as avg_quality,
                        SUM(cost_usd) as total_cost
                    FROM jarvis_model_usage_log
                    WHERE created_at > NOW() - INTERVAL '%s days'
                      AND quality_score IS NOT NULL
                    GROUP BY task_type, model_id
                    HAVING COUNT(*) >= 5
                    ORDER BY task_type, avg_quality DESC
                """, (days,))

                task_models = {}
                for row in cur.fetchall():
                    task = row['task_type']
                    if task not in task_models:
                        task_models[task] = []
                    task_models[task].append(row)

                for task, models in task_models.items():
                    if len(models) >= 2:
                        best = models[0]
                        worst = models[-1]
                        if best['avg_quality'] and worst['avg_quality']:
                            if float(best['avg_quality']) - float(worst['avg_quality']) > 0.2:
                                recommendations.append({
                                    'type': 'prefer_better_model',
                                    'task_type': task,
                                    'better_model': best['model_id'],
                                    'worse_model': worst['model_id'],
                                    'quality_diff': round(float(best['avg_quality']) - float(worst['avg_quality']), 2),
                                    'action': f"Consider prioritizing {best['model_id']} over {worst['model_id']} for {task}"
                                })

                # 2. Find expensive tasks that could use cheaper models
                cur.execute("""
                    SELECT
                        task_type,
                        model_id,
                        COUNT(*) as uses,
                        SUM(cost_usd) as total_cost,
                        AVG(quality_score) as avg_quality
                    FROM jarvis_model_usage_log
                    WHERE created_at > NOW() - INTERVAL '%s days'
                    GROUP BY task_type, model_id
                    ORDER BY total_cost DESC
                    LIMIT 10
                """, (days,))

                for row in cur.fetchall():
                    if row['avg_quality'] and float(row['avg_quality']) > 0.8 and float(row['total_cost']) > 0.10:
                        # High quality, high cost - could potentially use cheaper model
                        recommendations.append({
                            'type': 'cost_optimization',
                            'task_type': row['task_type'],
                            'current_model': row['model_id'],
                            'total_cost': round(float(row['total_cost']), 4),
                            'avg_quality': round(float(row['avg_quality']), 2),
                            'action': f"Task {row['task_type']} has high quality ({row['avg_quality']:.2f}) - could try cheaper model"
                        })

                # 3. Check for unused rules
                cur.execute("""
                    SELECT rule_name, rule_type, times_applied
                    FROM jarvis_selection_rules
                    WHERE is_active = TRUE AND times_applied = 0
                """)
                unused_rules = cur.fetchall()
                if unused_rules:
                    recommendations.append({
                        'type': 'unused_rules',
                        'rules': [r['rule_name'] for r in unused_rules],
                        'action': 'These rules have never been applied - consider reviewing conditions'
                    })

                # 4. Summary stats
                cur.execute("""
                    SELECT
                        COUNT(DISTINCT model_id) as models_used,
                        COUNT(DISTINCT task_type) as tasks_seen,
                        SUM(cost_usd) as total_cost,
                        COUNT(*) as total_requests
                    FROM jarvis_model_usage_log
                    WHERE created_at > NOW() - INTERVAL '%s days'
                """, (days,))
                summary = cur.fetchone()

                return {
                    'success': True,
                    'period_days': days,
                    'summary': {
                        'models_used': summary['models_used'] or 0,
                        'tasks_seen': summary['tasks_seen'] or 0,
                        'total_cost_usd': round(float(summary['total_cost'] or 0), 4),
                        'total_requests': summary['total_requests'] or 0,
                    },
                    'recommendations': recommendations,
                    'recommendation_count': len(recommendations)
                }

    except Exception as e:
        logger.error(f"Failed to get recommendations: {e}")
        return {'success': False, 'error': str(e)}


def disable_pattern(pattern_id: int, reason: str) -> Dict[str, Any]:
    """
    Disable a task pattern that isn't working well.

    Args:
        pattern_id: The pattern ID to disable
        reason: Why the pattern is being disabled
    """
    try:
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    UPDATE jarvis_task_patterns
                    SET is_active = FALSE, updated_at = NOW(), notes = COALESCE(notes, '') || ' | Disabled: ' || %s
                    WHERE id = %s
                    RETURNING task_type, pattern_text
                """, (reason, pattern_id))
                updated = cur.fetchone()

                if not updated:
                    return {'success': False, 'error': f'Pattern {pattern_id} not found'}

                # Log the change
                cur.execute("""
                    INSERT INTO jarvis_pattern_learning_log
                    (action_type, table_name, record_id, old_value, reason, initiated_by)
                    VALUES ('pattern_disabled', 'jarvis_task_patterns', %s, %s, %s, 'jarvis')
                """, (pattern_id, json.dumps(dict(updated)), reason))

            conn.commit()

        # Clear cache
        try:
            from app.services.dynamic_model_router import get_dynamic_model_router
            get_dynamic_model_router()._clear_cache()
        except Exception:
            pass

        return {
            'success': True,
            'pattern_id': pattern_id,
            'task_type': updated['task_type'],
            'pattern_text': updated['pattern_text'],
            'message': f'Pattern {pattern_id} disabled'
        }

    except Exception as e:
        logger.error(f"Failed to disable pattern: {e}")
        return {'success': False, 'error': str(e)}


def add_selection_rule(
    rule_name: str,
    rule_type: str,
    condition: Dict[str, Any],
    action_type: str,
    action_value: Dict[str, Any],
    priority: int = 50
) -> Dict[str, Any]:
    """
    Add a new model selection rule.

    Args:
        rule_name: Unique name for the rule
        rule_type: 'complexity_threshold', 'task_type_match', 'time_based'
        condition: JSON condition (e.g., {"complexity_max": 0.3})
        action_type: 'prefer_model', 'prefer_provider', 'set_cost_sensitivity'
        action_value: JSON action value
        priority: Rule priority (lower = higher priority)
    """
    valid_rule_types = ['complexity_threshold', 'task_type_match', 'time_based']
    valid_action_types = ['prefer_model', 'prefer_provider', 'set_cost_sensitivity', 'boost_capability']

    if rule_type not in valid_rule_types:
        return {'success': False, 'error': f'rule_type must be one of: {valid_rule_types}'}
    if action_type not in valid_action_types:
        return {'success': False, 'error': f'action_type must be one of: {valid_action_types}'}

    try:
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    INSERT INTO jarvis_selection_rules
                    (rule_name, rule_type, condition, action_type, action_value, priority)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (rule_name) DO UPDATE SET
                        rule_type = EXCLUDED.rule_type,
                        condition = EXCLUDED.condition,
                        action_type = EXCLUDED.action_type,
                        action_value = EXCLUDED.action_value,
                        priority = EXCLUDED.priority,
                        updated_at = NOW()
                    RETURNING id
                """, (rule_name, rule_type, json.dumps(condition), action_type, json.dumps(action_value), priority))
                rule_id = cur.fetchone()['id']

                # Log
                cur.execute("""
                    INSERT INTO jarvis_pattern_learning_log
                    (action_type, table_name, record_id, new_value, initiated_by)
                    VALUES ('rule_added', 'jarvis_selection_rules', %s, %s, 'jarvis')
                """, (rule_id, json.dumps({
                    'rule_name': rule_name,
                    'rule_type': rule_type,
                    'action_type': action_type
                })))

            conn.commit()

        # Clear cache
        try:
            from app.services.dynamic_model_router import get_dynamic_model_router
            get_dynamic_model_router()._clear_cache()
        except Exception:
            pass

        return {
            'success': True,
            'rule_id': rule_id,
            'rule_name': rule_name,
            'message': f'Rule {rule_name} added with priority {priority}'
        }

    except Exception as e:
        logger.error(f"Failed to add rule: {e}")
        return {'success': False, 'error': str(e)}


# Tool definitions for Jarvis
MODEL_LEARNING_TOOLS = [
    {
        "name": "learn_task_pattern",
        "description": "Learn a new pattern for task classification. Use when you notice a query type that isn't being classified correctly.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_type": {
                    "type": "string",
                    "description": "The task category",
                    "enum": ["code_generation", "code_review", "debugging", "math_reasoning",
                             "analysis", "creative_writing", "planning", "summarization",
                             "translation", "quick_question", "general_chat", "tool_execution"]
                },
                "pattern_text": {
                    "type": "string",
                    "description": "The pattern to match (keyword, phrase, or regex)"
                },
                "pattern_type": {
                    "type": "string",
                    "enum": ["keyword", "phrase", "regex"],
                    "description": "Type of pattern matching"
                },
                "language": {
                    "type": "string",
                    "enum": ["de", "en", "both"],
                    "description": "Language the pattern applies to"
                },
                "confidence": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                    "description": "Initial confidence (0-1)"
                },
                "reason": {
                    "type": "string",
                    "description": "Why this pattern should be learned"
                }
            },
            "required": ["task_type", "pattern_text", "reason"]
        }
    },
    {
        "name": "adjust_model_priority",
        "description": "Adjust which model is preferred for a task type based on experience. Lower priority = higher preference.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_type": {"type": "string", "description": "The task category"},
                "model_id": {"type": "string", "description": "The model to prioritize"},
                "new_priority": {"type": "integer", "minimum": 1, "maximum": 100, "description": "New priority (1=highest)"},
                "reason": {"type": "string", "description": "Why this adjustment is being made"},
                "min_complexity": {"type": "number", "description": "Min complexity for this mapping (0-1)"},
                "max_complexity": {"type": "number", "description": "Max complexity for this mapping (0-1)"}
            },
            "required": ["task_type", "model_id", "new_priority", "reason"]
        }
    },
    {
        "name": "report_model_performance",
        "description": "Report that a model performed well or poorly for a specific task. Helps learn which models work best.",
        "input_schema": {
            "type": "object",
            "properties": {
                "model_id": {"type": "string", "description": "The model that was used"},
                "task_type": {"type": "string", "description": "The task type it was used for"},
                "quality_score": {"type": "number", "minimum": 0, "maximum": 1, "description": "Quality rating (0-1)"},
                "feedback": {"type": "string", "description": "Optional text feedback"}
            },
            "required": ["model_id", "task_type", "quality_score"]
        }
    },
    {
        "name": "get_model_recommendations",
        "description": "Get AI-driven recommendations for model selection optimization based on usage patterns.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "default": 30, "description": "Number of days to analyze"}
            },
            "required": []
        }
    },
    {
        "name": "disable_pattern",
        "description": "Disable a task pattern that isn't working well.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern_id": {"type": "integer", "description": "The pattern ID to disable"},
                "reason": {"type": "string", "description": "Why the pattern is being disabled"}
            },
            "required": ["pattern_id", "reason"]
        }
    },
    {
        "name": "add_selection_rule",
        "description": "Add a new model selection rule for dynamic routing.",
        "input_schema": {
            "type": "object",
            "properties": {
                "rule_name": {"type": "string", "description": "Unique name for the rule"},
                "rule_type": {
                    "type": "string",
                    "enum": ["complexity_threshold", "task_type_match", "time_based"],
                    "description": "Type of rule"
                },
                "condition": {"type": "object", "description": "JSON condition object"},
                "action_type": {
                    "type": "string",
                    "enum": ["prefer_model", "prefer_provider", "set_cost_sensitivity", "boost_capability"],
                    "description": "Type of action"
                },
                "action_value": {"type": "object", "description": "JSON action value object"},
                "priority": {"type": "integer", "default": 50, "description": "Rule priority (lower = higher priority)"}
            },
            "required": ["rule_name", "rule_type", "condition", "action_type", "action_value"]
        }
    }
]
