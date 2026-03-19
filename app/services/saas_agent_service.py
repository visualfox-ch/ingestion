"""
SaaS Agent Service (SaaSJarvis) - Phase 22A-10

Revenue- und Product-Ops specialist:
- review_funnel_metrics: Funnel KPIs over time (conversion rates, MRR, churn)
- prioritize_growth_experiments: ICE-scored experiment backlog
- summarize_icp_signals: ICP signals from feedback, support, churn data
- review_pricing_hypotheses: Pricing hypothesis tracking and validation
"""

from dataclasses import dataclass
from typing import Dict, List, Any, Optional
from datetime import datetime, date, timedelta
import json

from ..observability import get_logger, log_with_context
from ..postgres_state import get_conn

logger = get_logger("jarvis.saas_agent")


class SaaSAgentService:
    """
    SaaSJarvis - Revenue and Product-Ops Specialist.

    Provides:
    - Funnel metric tracking and trend review
    - Growth experiment backlog with ICE scoring
    - ICP signal aggregation from multiple sources
    - Pricing hypothesis lifecycle management
    """

    def __init__(self):
        self._ensure_schema()

    def _ensure_schema(self):
        """Run migration 135 if tables do not exist."""
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT EXISTS (SELECT FROM information_schema.tables "
                        "WHERE table_name = 'jarvis_saas_experiments')"
                    )
                    if not cur.fetchone()[0]:
                        migration_path = (
                            "/brain/system/ingestion/migrations/135_saas_agent.sql"
                        )
                        try:
                            with open(migration_path, "r") as f:
                                cur.execute(f.read())
                            conn.commit()
                            log_with_context(logger, "info", "SaaS agent tables created")
                        except Exception as e:
                            log_with_context(
                                logger, "debug",
                                "SaaS migration file not found", error=str(e)
                            )
        except Exception as e:
            log_with_context(logger, "debug", "SaaS schema check failed", error=str(e))

    # =========================================================================
    # 1. Funnel Metrics
    # =========================================================================

    def review_funnel_metrics(
        self,
        days: int = 30,
        stage: Optional[str] = None,
        source: Optional[str] = None,
        user_id: str = "1",
        metrics: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Review funnel KPIs, optionally recording new data points first.

        Args:
            days: Look-back window in days
            stage: Filter to specific funnel stage (visitor, signup, activated, paying, retained)
            source: Filter to acquisition source
            user_id: Owner
            metrics: Optional list of new metric dicts to record before review
                     Each: {stage, metric_name, metric_value, source?, notes?}
        """
        try:
            since = date.today() - timedelta(days=days)

            with get_conn() as conn:
                with conn.cursor() as cur:
                    # Record new metrics if provided
                    if metrics:
                        for m in metrics:
                            cur.execute(
                                """
                                INSERT INTO jarvis_saas_funnel
                                  (user_id, recorded_date, source, stage, metric_name,
                                   metric_value, unit, notes)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                                ON CONFLICT (recorded_date, source, stage, metric_name)
                                DO UPDATE SET
                                    metric_value = EXCLUDED.metric_value,
                                    notes = EXCLUDED.notes
                                """,
                                (
                                    user_id,
                                    m.get("recorded_date", date.today().isoformat()),
                                    m.get("source", "manual"),
                                    m.get("stage"),
                                    m.get("metric_name"),
                                    m.get("metric_value"),
                                    m.get("unit", "count"),
                                    m.get("notes"),
                                ),
                            )
                        conn.commit()

                    # Query funnel data
                    query = """
                        SELECT recorded_date, source, stage, metric_name,
                               metric_value, unit
                        FROM jarvis_saas_funnel
                        WHERE user_id = %s AND recorded_date >= %s
                    """
                    params: list = [user_id, since]

                    if stage:
                        query += " AND stage = %s"
                        params.append(stage)
                    if source:
                        query += " AND source = %s"
                        params.append(source)

                    query += " ORDER BY recorded_date DESC, stage, metric_name"

                    cur.execute(query, tuple(params))
                    rows = cur.fetchall()

            # Group by metric for trend analysis
            by_metric: Dict[str, list] = {}
            for row in rows:
                key = f"{row[3]}"  # metric_name
                if key not in by_metric:
                    by_metric[key] = []
                by_metric[key].append(
                    {
                        "date": row[0].isoformat() if row[0] else None,
                        "source": row[1],
                        "stage": row[2],
                        "value": float(row[4]),
                        "unit": row[5],
                    }
                )

            # Simple trend per metric (latest vs oldest in window)
            trends = {}
            for metric_name, entries in by_metric.items():
                if len(entries) >= 2:
                    latest = entries[0]["value"]
                    oldest = entries[-1]["value"]
                    if oldest != 0:
                        delta_pct = round((latest - oldest) / abs(oldest) * 100, 1)
                        trends[metric_name] = {
                            "delta_pct": delta_pct,
                            "direction": "up" if delta_pct > 0 else "down" if delta_pct < 0 else "flat",
                        }

            summary_lines = []
            for k, t in trends.items():
                arrow = "↑" if t["direction"] == "up" else "↓" if t["direction"] == "down" else "→"
                summary_lines.append(f"{k}: {arrow} {t['delta_pct']:+.1f}% ({days}d)")

            return {
                "success": True,
                "window_days": days,
                "total_data_points": len(rows),
                "metrics": by_metric,
                "trends": trends,
                "summary": "; ".join(summary_lines) if summary_lines else "Keine Funnel-Daten im Zeitraum",
            }

        except Exception as e:
            log_with_context(logger, "error", "Funnel review failed", error=str(e))
            return {"success": False, "error": str(e)}

    # =========================================================================
    # 2. Growth Experiments
    # =========================================================================

    def prioritize_growth_experiments(
        self,
        status_filter: Optional[str] = None,
        category_filter: Optional[str] = None,
        user_id: str = "1",
        new_experiments: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Score and rank growth experiments by ICE score.

        Args:
            status_filter: idea | planned | running | paused | done | cancelled
            category_filter: acquisition | activation | retention | revenue | referral
            user_id: Owner
            new_experiments: Optional experiments to add before prioritizing
                             Each: {title, hypothesis?, category?, impact_score?,
                                    effort_score?, confidence_score?, target_metric?,
                                    status?}
        """
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    # Add new experiments if provided
                    if new_experiments:
                        for exp in new_experiments:
                            cur.execute(
                                """
                                INSERT INTO jarvis_saas_experiments
                                  (user_id, title, hypothesis, category,
                                   impact_score, effort_score, confidence_score,
                                   target_metric, status)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                                """,
                                (
                                    user_id,
                                    exp["title"],
                                    exp.get("hypothesis"),
                                    exp.get("category", "activation"),
                                    exp.get("impact_score", 50),
                                    exp.get("effort_score", 50),
                                    exp.get("confidence_score", 50),
                                    exp.get("target_metric"),
                                    exp.get("status", "idea"),
                                ),
                            )
                        conn.commit()

                    # Query experiments
                    query = """
                        SELECT id, title, hypothesis, category, status,
                               impact_score, effort_score, confidence_score,
                               ice_score, target_metric, target_delta, actual_delta,
                               outcome, learnings, started_at, ended_at
                        FROM jarvis_saas_experiments
                        WHERE user_id = %s
                    """
                    params: list = [user_id]

                    if status_filter:
                        query += " AND status = %s"
                        params.append(status_filter)
                    else:
                        query += " AND status NOT IN ('done', 'cancelled')"

                    if category_filter:
                        query += " AND category = %s"
                        params.append(category_filter)

                    query += " ORDER BY ice_score DESC LIMIT 20"
                    cur.execute(query, tuple(params))
                    rows = cur.fetchall()

            experiments = []
            for row in rows:
                experiments.append(
                    {
                        "id": row[0],
                        "title": row[1],
                        "hypothesis": row[2],
                        "category": row[3],
                        "status": row[4],
                        "impact": row[5],
                        "effort": row[6],
                        "confidence": row[7],
                        "ice_score": float(row[8]) if row[8] else None,
                        "target_metric": row[9],
                        "target_delta": float(row[10]) if row[10] else None,
                        "actual_delta": float(row[11]) if row[11] else None,
                        "outcome": row[12],
                        "learnings": row[13],
                    }
                )

            running = [e for e in experiments if e["status"] == "running"]
            top_ideas = [e for e in experiments if e["status"] in ("idea", "planned")][:5]

            return {
                "success": True,
                "total": len(experiments),
                "running": running,
                "top_prioritized": top_ideas,
                "all": experiments,
                "summary": (
                    f"{len(running)} laufend, {len(top_ideas)} top ideas (nach ICE-Score)"
                ),
            }

        except Exception as e:
            log_with_context(logger, "error", "Experiment prioritization failed", error=str(e))
            return {"success": False, "error": str(e)}

    # =========================================================================
    # 3. ICP Signals
    # =========================================================================

    def summarize_icp_signals(
        self,
        days: int = 90,
        signal_type: Optional[str] = None,
        segment: Optional[str] = None,
        user_id: str = "1",
        new_signals: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Aggregate and summarize ICP signals.

        Args:
            days: Look-back window
            signal_type: feedback | support | churn | expansion | interview
            segment: Customer segment filter
            user_id: Owner
            new_signals: Optional signals to record before summarizing
                         Each: {signal_type, signal_summary, source?, customer_segment?,
                                verbatim_quote?, sentiment?, icp_fit_score?, tags?}
        """
        try:
            since = date.today() - timedelta(days=days)

            with get_conn() as conn:
                with conn.cursor() as cur:
                    if new_signals:
                        for s in new_signals:
                            cur.execute(
                                """
                                INSERT INTO jarvis_saas_icp_notes
                                  (user_id, signal_type, source, customer_segment,
                                   signal_summary, verbatim_quote, sentiment,
                                   icp_fit_score, tags, recorded_at)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                                """,
                                (
                                    user_id,
                                    s["signal_type"],
                                    s.get("source", "manual"),
                                    s.get("customer_segment"),
                                    s["signal_summary"],
                                    s.get("verbatim_quote"),
                                    s.get("sentiment", "neutral"),
                                    s.get("icp_fit_score"),
                                    json.dumps(s.get("tags", [])),
                                    s.get("recorded_at", date.today().isoformat()),
                                ),
                            )
                        conn.commit()

                    query = """
                        SELECT id, signal_type, source, customer_segment,
                               signal_summary, verbatim_quote, sentiment,
                               icp_fit_score, tags, recorded_at
                        FROM jarvis_saas_icp_notes
                        WHERE user_id = %s AND recorded_at >= %s
                    """
                    params: list = [user_id, since]

                    if signal_type:
                        query += " AND signal_type = %s"
                        params.append(signal_type)
                    if segment:
                        query += " AND customer_segment = %s"
                        params.append(segment)

                    query += " ORDER BY recorded_at DESC LIMIT 50"
                    cur.execute(query, tuple(params))
                    rows = cur.fetchall()

            signals = []
            sentiment_counts: Dict[str, int] = {"positive": 0, "negative": 0, "neutral": 0}
            by_type: Dict[str, int] = {}

            for row in rows:
                sentiment = row[6] or "neutral"
                sentiment_counts[sentiment] = sentiment_counts.get(sentiment, 0) + 1
                stype = row[1]
                by_type[stype] = by_type.get(stype, 0) + 1
                signals.append(
                    {
                        "id": row[0],
                        "type": stype,
                        "source": row[2],
                        "segment": row[3],
                        "summary": row[4],
                        "quote": row[5],
                        "sentiment": sentiment,
                        "icp_fit": row[7],
                        "date": row[9].isoformat() if row[9] else None,
                    }
                )

            # High-ICP signals
            high_fit = [s for s in signals if s.get("icp_fit") and s["icp_fit"] >= 75]

            summary_parts = [f"{len(signals)} Signale ({days}d)"]
            if by_type:
                summary_parts.append(
                    "Typen: " + ", ".join(f"{k}={v}" for k, v in by_type.items())
                )
            if sentiment_counts:
                pos = sentiment_counts.get("positive", 0)
                neg = sentiment_counts.get("negative", 0)
                summary_parts.append(f"Sentiment: +{pos}/-{neg}")
            if high_fit:
                summary_parts.append(f"{len(high_fit)} High-ICP-Fit Signale")

            return {
                "success": True,
                "total_signals": len(signals),
                "by_type": by_type,
                "sentiment": sentiment_counts,
                "high_icp_fit_signals": high_fit[:5],
                "recent_signals": signals[:10],
                "summary": ". ".join(summary_parts),
            }

        except Exception as e:
            log_with_context(logger, "error", "ICP summarization failed", error=str(e))
            return {"success": False, "error": str(e)}

    # =========================================================================
    # 4. Pricing Hypotheses
    # =========================================================================

    def review_pricing_hypotheses(
        self,
        status_filter: Optional[str] = None,
        user_id: str = "1",
        new_hypotheses: Optional[List[Dict[str, Any]]] = None,
        update_hypothesis: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Track and evaluate pricing hypotheses.

        Args:
            status_filter: idea | researching | validating | validated | rejected
            user_id: Owner
            new_hypotheses: Hypotheses to add. Each: {title, description?,
                            model_type?, target_segment?, current_price?,
                            proposed_price?, hypothesis?, validation_method?}
            update_hypothesis: {id, status?, confidence_score?, evidence?,
                                 notes?, mrr_impact_estimate?, outcome?}
        """
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    if new_hypotheses:
                        for h in new_hypotheses:
                            cur.execute(
                                """
                                INSERT INTO jarvis_saas_pricing_hypotheses
                                  (user_id, title, description, model_type,
                                   target_segment, current_price, proposed_price,
                                   currency, interval, hypothesis, validation_method,
                                   confidence_score, mrr_impact_estimate)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                                """,
                                (
                                    user_id,
                                    h["title"],
                                    h.get("description"),
                                    h.get("model_type", "flat"),
                                    h.get("target_segment"),
                                    h.get("current_price"),
                                    h.get("proposed_price"),
                                    h.get("currency", "EUR"),
                                    h.get("interval", "monthly"),
                                    h.get("hypothesis"),
                                    h.get("validation_method"),
                                    h.get("confidence_score", 30),
                                    h.get("mrr_impact_estimate"),
                                ),
                            )
                        conn.commit()

                    if update_hypothesis:
                        hyp_id = update_hypothesis.pop("id", None)
                        if hyp_id:
                            set_parts = []
                            vals = []
                            allowed = {
                                "status", "confidence_score", "notes",
                                "mrr_impact_estimate", "churn_impact_estimate",
                            }
                            for field in allowed:
                                if field in update_hypothesis:
                                    set_parts.append(f"{field} = %s")
                                    vals.append(update_hypothesis[field])
                            if "evidence" in update_hypothesis:
                                set_parts.append(
                                    "evidence = evidence || %s::jsonb"
                                )
                                vals.append(
                                    json.dumps(update_hypothesis["evidence"])
                                )
                            if set_parts:
                                set_parts.append("updated_at = NOW()")
                                vals.append(hyp_id)
                                cur.execute(
                                    f"UPDATE jarvis_saas_pricing_hypotheses "
                                    f"SET {', '.join(set_parts)} WHERE id = %s",
                                    tuple(vals),
                                )
                                conn.commit()

                    query = """
                        SELECT id, title, description, model_type, status,
                               target_segment, current_price, proposed_price,
                               currency, interval, hypothesis, validation_method,
                               confidence_score, mrr_impact_estimate,
                               churn_impact_estimate, notes, created_at
                        FROM jarvis_saas_pricing_hypotheses
                        WHERE user_id = %s
                    """
                    params: list = [user_id]

                    if status_filter:
                        query += " AND status = %s"
                        params.append(status_filter)
                    else:
                        query += " AND status NOT IN ('rejected')"

                    query += " ORDER BY confidence_score DESC, created_at DESC LIMIT 20"
                    cur.execute(query, tuple(params))
                    rows = cur.fetchall()

            hypotheses = []
            for row in rows:
                hypotheses.append(
                    {
                        "id": row[0],
                        "title": row[1],
                        "description": row[2],
                        "model_type": row[3],
                        "status": row[4],
                        "target_segment": row[5],
                        "current_price": float(row[6]) if row[6] else None,
                        "proposed_price": float(row[7]) if row[7] else None,
                        "currency": row[8],
                        "interval": row[9],
                        "hypothesis": row[10],
                        "validation_method": row[11],
                        "confidence_score": row[12],
                        "mrr_impact_estimate": float(row[13]) if row[13] else None,
                        "churn_impact_estimate": float(row[14]) if row[14] else None,
                        "notes": row[15],
                    }
                )

            active = [h for h in hypotheses if h["status"] in ("validating", "researching")]
            ideas = [h for h in hypotheses if h["status"] == "idea"]
            validated = [h for h in hypotheses if h["status"] == "validated"]

            return {
                "success": True,
                "total": len(hypotheses),
                "active_validation": active,
                "ideas": ideas,
                "validated": validated,
                "all": hypotheses,
                "summary": (
                    f"{len(active)} in Validierung, "
                    f"{len(ideas)} Ideen, "
                    f"{len(validated)} validiert"
                ),
            }

        except Exception as e:
            log_with_context(logger, "error", "Pricing hypothesis review failed", error=str(e))
            return {"success": False, "error": str(e)}


# Module-level singleton
_service: Optional[SaaSAgentService] = None


def get_saas_agent_service() -> SaaSAgentService:
    global _service
    if _service is None:
        _service = SaaSAgentService()
    return _service
