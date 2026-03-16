#!/usr/bin/env python3
"""
Audit Grafana dashboards for Prometheus metrics that return no data.

Usage:
  python scripts/audit_grafana_no_data.py --metrics-file logs/prometheus_metrics.json \
    --dashboards monitoring/grafana/provisioning/dashboards/json \
    --out logs/grafana_no_data_report_YYYYMMDD.md
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Dict, Iterable, List, Set


PROMQL_FUNCTIONS = {
    "sum", "avg", "min", "max", "count", "count_values",
    "rate", "irate", "increase", "delta", "idelta", "deriv",
    "sum_over_time", "avg_over_time", "min_over_time", "max_over_time",
    "stddev_over_time", "stdvar_over_time", "quantile_over_time",
    "histogram_quantile", "predict_linear",
    "topk", "bottomk", "sort", "sort_desc",
    "abs", "clamp_max", "clamp_min", "ceil", "floor", "round",
    "label_replace", "label_join",
    "vector", "scalar", "time",
    "day_of_week", "day_of_month", "days_in_month", "hour", "minute",
    "month", "year",
}

PROMQL_KEYWORDS = {
    "by", "without", "on", "ignoring", "group_left", "group_right",
    "bool", "and", "or", "unless", "offset",
}

LABEL_TOKENS = {
    "le", "status", "source", "tool", "tier", "model", "error_type",
    "decision", "facette", "mailbox", "owner", "sensitivity",
    "domain", "visibility", "channel", "priority", "sentiment",
    "classification", "reminder_type", "mem_metric", "path",
    "points", "search", "e", "feedback_type", "action_type", "type",
}


def load_metrics(path: Path) -> Set[str]:
    data = json.loads(path.read_text())
    if isinstance(data, dict) and data.get("data"):
        metrics = data["data"]
    else:
        metrics = data
    if not isinstance(metrics, list):
        raise ValueError("metrics file must contain a JSON array or {data:[...]}")
    return set(metrics)


def iter_dashboard_paths(root: Path) -> Iterable[Path]:
    for path in sorted(root.glob("*.json")):
        if path.is_file():
            yield path


def extract_metrics(expr: str) -> Set[str]:
    expr = expr or ""
    # Strip label selectors and range selectors to avoid label tokens like status/le
    expr = re.sub(r"\{[^}]*\}", "", expr)
    expr = re.sub(r"\[[^\]]*\]", "", expr)
    tokens = re.findall(r"[a-zA-Z_:][a-zA-Z0-9_:]*", expr)
    metrics = set()
    for token in tokens:
        if token in PROMQL_FUNCTIONS or token in PROMQL_KEYWORDS:
            continue
        if token.startswith("__"):
            continue
        if token in LABEL_TOKENS:
            continue
        # Drop label names (heuristic: next token likely comparator)
        metrics.add(token)
    return metrics


def collect_dashboard_metrics(dashboard: Dict) -> Dict[str, Set[str]]:
    panel_metrics: Dict[str, Set[str]] = {}
    panels = dashboard.get("panels", [])
    for panel in panels:
        title = panel.get("title", "(untitled)")
        targets = panel.get("targets", [])
        expr_metrics: Set[str] = set()
        for target in targets:
            expr = target.get("expr")
            if expr:
                expr_metrics |= extract_metrics(expr)
        if expr_metrics:
            panel_metrics[title] = expr_metrics
    return panel_metrics


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metrics-file", required=True)
    parser.add_argument("--dashboards", default="monitoring/grafana/provisioning/dashboards/json")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    metrics = load_metrics(Path(args.metrics_file))
    dashboard_dir = Path(args.dashboards)
    report: List[str] = []
    total_missing = 0

    report.append("# Grafana No-Data Audit")
    report.append("")
    report.append(f"- Dashboards: `{dashboard_dir}`")
    report.append(f"- Metrics loaded: `{len(metrics)}`")
    report.append("")

    for dash_path in iter_dashboard_paths(dashboard_dir):
        dashboard = json.loads(dash_path.read_text())
        panel_metrics = collect_dashboard_metrics(dashboard)
        missing_panels = {}
        for title, used_metrics in panel_metrics.items():
            missing = sorted(m for m in used_metrics if m not in metrics)
            if missing:
                missing_panels[title] = missing

        if missing_panels:
            report.append(f"## {dashboard.get('title', dash_path.name)}")
            for title, missing in missing_panels.items():
                report.append(f"- **{title}**: {', '.join(missing)}")
                total_missing += len(missing)
            report.append("")

    if total_missing == 0:
        report.append("✅ No missing metrics detected.")
    else:
        report.append(f"**Total missing metric references:** {total_missing}")

    Path(args.out).write_text("\n".join(report))
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
