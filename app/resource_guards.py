"""
Resource guards (load shedding) for Jarvis ingestion.

Goal: fail fast under resource pressure (RAM/disk) to prevent cascading failures.
This is intentionally minimal and human-friendly (returns actionable error payloads).
"""

from __future__ import annotations

import os
import shutil
import time
from typing import Any, Dict, Tuple

import psutil

from . import config
from .observability import get_logger, log_with_context, metrics

logger = get_logger("jarvis.resource_guard")


def _disk_percent(path: str) -> float:
    try:
        usage = shutil.disk_usage(path)
        if usage.total <= 0:
            return 0.0
        return (usage.used / usage.total) * 100.0
    except Exception:
        return 0.0


def get_resource_snapshot() -> Dict[str, Any]:
    mem = psutil.virtual_memory()
    mem_percent = float(mem.percent)

    # Prefer the persistent mount if present (NAS bind mount)
    disk_path = "/brain" if os.path.exists("/brain") else "/"
    disk_percent = float(_disk_percent(disk_path))

    return {
        "memory_percent": round(mem_percent, 2),
        "disk_path": disk_path,
        "disk_percent": round(disk_percent, 2),
        "thresholds": {
            "mem_reject_percent": config.RESOURCE_GUARD_MEM_REJECT_PERCENT,
            "disk_reject_percent": config.RESOURCE_GUARD_DISK_REJECT_PERCENT,
        },
    }


def should_reject_request(path: str) -> Tuple[bool, Dict[str, Any]]:
    """
    Decide whether to reject a request with 503 due to resource pressure.

    Returns:
        (reject, payload)
    """
    if not config.RESOURCE_GUARD_ENABLED:
        return False, {}

    snap = get_resource_snapshot()
    mem_p = float(snap["memory_percent"])
    disk_p = float(snap["disk_percent"])

    reasons = []
    if mem_p >= float(config.RESOURCE_GUARD_MEM_REJECT_PERCENT):
        reasons.append("memory_high")
    if disk_p >= float(config.RESOURCE_GUARD_DISK_REJECT_PERCENT):
        reasons.append("disk_high")

    if not reasons:
        return False, snap

    metrics.inc("resource_guard_reject_total")
    for r in reasons:
        metrics.inc(f"resource_guard_reject_{r}")

    log_with_context(
        logger,
        "warning",
        "Resource guard rejecting request",
        path=path,
        reasons=reasons,
        memory_percent=snap["memory_percent"],
        disk_percent=snap["disk_percent"],
    )

    return True, {
        "error": "RESOURCE_GUARD",
        "status": "degraded",
        "reasons": reasons,
        "resources": snap,
        "hint": "Retry later or reduce load; check Grafana/Prometheus if this persists.",
        "retry_after_seconds": 30,
    }
