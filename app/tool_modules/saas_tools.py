"""
SaaS Agent Tools (Phase 22A-10) — T-20260319-006

Revenue- und Product-Ops tools for SaaSJarvis:
- saas_review_funnel_metrics: Funnel KPIs mit Trend-Analyse
- saas_prioritize_growth_experiments: ICE-scored Experiment Backlog
- saas_summarize_icp_signals: ICP Signale aggregiert
- saas_review_pricing_hypotheses: Pricing Hypothesen Lifecycle
"""

from typing import Dict, Any, List, Optional
import json
import logging

logger = logging.getLogger("jarvis.tools.saas")

try:
    from ..logging_utils import log_with_context
    from .. import metrics
except ImportError:
    def log_with_context(logger, level, msg, **kwargs):
        getattr(logger, level)(f"{msg} {kwargs}")

    class metrics:
        @staticmethod
        def inc(name): pass


# ============ Tool Definitions ============

SAAS_TOOLS = [
    {
        "name": "saas_review_funnel_metrics",
        "description": (
            "Review SaaS funnel KPIs (conversion rates, MRR, churn, CAC, LTV) "
            "over a time window. Optionally record new data points. Returns "
            "trend analysis per metric with direction and delta percentage. "
            "Use to monitor revenue health and funnel performance."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Look-back window in days (default: 30)",
                    "default": 30,
                },
                "stage": {
                    "type": "string",
                    "description": "Filter to specific funnel stage: visitor, signup, activated, paying, retained",
                },
                "source": {
                    "type": "string",
                    "description": "Filter to acquisition source: organic, paid, referral, direct",
                },
                "metrics": {
                    "type": "array",
                    "description": "Optional new data points to record. Each: {stage, metric_name, metric_value, source?, unit?, notes?, recorded_date?}",
                    "items": {"type": "object"},
                },
            },
        },
    },
    {
        "name": "saas_prioritize_growth_experiments",
        "description": (
            "Score and rank growth experiments by ICE score (Impact × Confidence / Effort). "
            "Shows running experiments and top-prioritized ideas. "
            "Optionally add new experiments to the backlog. "
            "Categories: acquisition, activation, retention, revenue, referral."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "status_filter": {
                    "type": "string",
                    "description": "Filter by status: idea, planned, running, paused, done, cancelled. Default: all active (not done/cancelled)",
                },
                "category_filter": {
                    "type": "string",
                    "description": "Filter by category: acquisition, activation, retention, revenue, referral",
                },
                "new_experiments": {
                    "type": "array",
                    "description": "Optional new experiments to add. Each: {title, hypothesis?, category?, impact_score?, effort_score?, confidence_score?, target_metric?, status?}",
                    "items": {"type": "object"},
                },
            },
        },
    },
    {
        "name": "saas_summarize_icp_signals",
        "description": (
            "Aggregate and summarize ICP (Ideal Customer Profile) signals "
            "from feedback, support tickets, churn events, expansion signals, and interviews. "
            "Returns segment patterns and signal strengths. "
            "Optionally record new signals."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Look-back window in days (default: 90)",
                    "default": 90,
                },
                "signal_type": {
                    "type": "string",
                    "description": "Filter by type: feedback, support, churn, expansion, interview",
                },
                "segment": {
                    "type": "string",
                    "description": "Customer segment to filter by",
                },
                "new_signals": {
                    "type": "array",
                    "description": "Optional new signals to record. Each: {signal_type, segment?, content, sentiment?, pain_point?, job_to_be_done?, source?}",
                    "items": {"type": "object"},
                },
            },
        },
    },
    {
        "name": "saas_review_pricing_hypotheses",
        "description": (
            "Track and validate pricing hypotheses. Review active, validated, "
            "and failed hypotheses with evidence. "
            "Optionally add new hypotheses or update outcomes. "
            "Use for pricing strategy decisions and A/B test tracking."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "status_filter": {
                    "type": "string",
                    "description": "Filter by status: active, validated, invalidated, testing",
                },
                "new_hypotheses": {
                    "type": "array",
                    "description": "Optional new hypotheses to add. Each: {title, hypothesis, pricing_element?, expected_impact?, test_method?}",
                    "items": {"type": "object"},
                },
            },
        },
    },
]


# ============ Tool Implementations ============

def _to_int(value: Any, default: int) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_list_of_dicts(value: Any) -> Optional[List[Dict[str, Any]]]:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except Exception:
            return None
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        return None
    normalized: List[Dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            normalized.append(item)
    return normalized


def _inc_metric(name: str) -> None:
    increment = getattr(metrics, "inc", None)
    if callable(increment):
        try:
            increment(name)
        except Exception:
            pass

def saas_review_funnel_metrics(
    days: int = 30,
    stage: Optional[str] = None,
    source: Optional[str] = None,
    metrics_data: Optional[List[Dict[str, Any]]] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Review SaaS funnel KPIs with trend analysis."""
    metrics_data = metrics_data or kwargs.get("metrics")
    days = _to_int(days, 30)
    metrics_data = _normalize_list_of_dicts(metrics_data)
    log_with_context(logger, "info", "Tool: saas_review_funnel_metrics", days=days)
    _inc_metric("tool_saas_review_funnel_metrics")
    try:
        from ..services.saas_agent_service import get_saas_agent_service
        svc = get_saas_agent_service()
        return svc.review_funnel_metrics(
            days=days,
            stage=stage,
            source=source,
            metrics=metrics_data,
        )
    except Exception as e:
        log_with_context(logger, "error", "saas_review_funnel_metrics failed", error=str(e))
        return {"success": False, "error": str(e)}


def saas_prioritize_growth_experiments(
    status_filter: Optional[str] = None,
    category_filter: Optional[str] = None,
    new_experiments: Optional[List[Dict[str, Any]]] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Score and rank growth experiments by ICE score."""
    new_experiments = _normalize_list_of_dicts(
        new_experiments if new_experiments is not None else kwargs.get("new_experiments")
    )
    log_with_context(logger, "info", "Tool: saas_prioritize_growth_experiments")
    _inc_metric("tool_saas_prioritize_growth_experiments")
    try:
        from ..services.saas_agent_service import get_saas_agent_service
        svc = get_saas_agent_service()
        return svc.prioritize_growth_experiments(
            status_filter=status_filter,
            category_filter=category_filter,
            new_experiments=new_experiments,
        )
    except Exception as e:
        log_with_context(logger, "error", "saas_prioritize_growth_experiments failed", error=str(e))
        return {"success": False, "error": str(e)}


def saas_summarize_icp_signals(
    days: int = 90,
    signal_type: Optional[str] = None,
    segment: Optional[str] = None,
    new_signals: Optional[List[Dict[str, Any]]] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Aggregate and summarize ICP signals."""
    days = _to_int(days, 90)
    new_signals = _normalize_list_of_dicts(
        new_signals if new_signals is not None else kwargs.get("new_signals")
    )
    if new_signals:
        remapped: List[Dict[str, Any]] = []
        for signal in new_signals:
            signal_type_val = signal.get("signal_type") or signal.get("type")
            summary_val = signal.get("signal_summary") or signal.get("content")
            if not signal_type_val or not summary_val:
                continue
            remapped.append(
                {
                    "signal_type": signal_type_val,
                    "signal_summary": summary_val,
                    "source": signal.get("source", "manual"),
                    "customer_segment": signal.get("customer_segment") or signal.get("segment"),
                    "verbatim_quote": signal.get("verbatim_quote") or signal.get("quote"),
                    "sentiment": signal.get("sentiment", "neutral"),
                    "icp_fit_score": signal.get("icp_fit_score") or signal.get("strength"),
                    "tags": signal.get("tags", []),
                    "recorded_at": signal.get("recorded_at"),
                }
            )
        new_signals = remapped or None
    log_with_context(logger, "info", "Tool: saas_summarize_icp_signals", days=days)
    _inc_metric("tool_saas_summarize_icp_signals")
    try:
        from ..services.saas_agent_service import get_saas_agent_service
        svc = get_saas_agent_service()
        return svc.summarize_icp_signals(
            days=days,
            signal_type=signal_type,
            segment=segment,
            new_signals=new_signals,
        )
    except Exception as e:
        log_with_context(logger, "error", "saas_summarize_icp_signals failed", error=str(e))
        return {"success": False, "error": str(e)}


def saas_review_pricing_hypotheses(
    status_filter: Optional[str] = None,
    new_hypotheses: Optional[List[Dict[str, Any]]] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Track and validate pricing hypotheses."""
    new_hypotheses = _normalize_list_of_dicts(
        new_hypotheses if new_hypotheses is not None else kwargs.get("new_hypotheses")
    )
    if new_hypotheses:
        remapped_hypotheses: List[Dict[str, Any]] = []
        for hypothesis in new_hypotheses:
            title = hypothesis.get("title") or hypothesis.get("hypothesis")
            if not title:
                continue
            remapped_hypotheses.append(
                {
                    "title": title,
                    "description": hypothesis.get("description"),
                    "model_type": hypothesis.get("model_type"),
                    "target_segment": hypothesis.get("target_segment") or hypothesis.get("segment"),
                    "current_price": hypothesis.get("current_price"),
                    "proposed_price": hypothesis.get("proposed_price"),
                    "currency": hypothesis.get("currency"),
                    "interval": hypothesis.get("interval"),
                    "hypothesis": hypothesis.get("hypothesis"),
                    "validation_method": hypothesis.get("validation_method") or hypothesis.get("test_method"),
                    "confidence_score": hypothesis.get("confidence_score"),
                    "mrr_impact_estimate": hypothesis.get("mrr_impact_estimate"),
                }
            )
        new_hypotheses = remapped_hypotheses or None
    log_with_context(logger, "info", "Tool: saas_review_pricing_hypotheses")
    _inc_metric("tool_saas_review_pricing_hypotheses")
    try:
        from ..services.saas_agent_service import get_saas_agent_service
        svc = get_saas_agent_service()
        return svc.review_pricing_hypotheses(
            status_filter=status_filter,
            new_hypotheses=new_hypotheses,
        )
    except Exception as e:
        log_with_context(logger, "error", "saas_review_pricing_hypotheses failed", error=str(e))
        return {"success": False, "error": str(e)}
