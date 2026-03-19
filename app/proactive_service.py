"""
Proactive Intervention Service for Jarvis

Tracks proactive suggestions, hints, and reminders that Jarvis makes,
along with user responses (accepted, ignored, rejected).

This enables measuring how effective Jarvis's proactive behavior is
and helps optimize intervention timing and content.
"""
import time
from datetime import datetime
from typing import Dict, Any, List, Optional
from enum import Enum
from dataclasses import dataclass

from .observability import get_logger, log_with_context

logger = get_logger("jarvis.proactive")


class InterventionType(str, Enum):
    """Types of proactive interventions."""
    HINT = "hint"           # Subtle suggestion
    SUGGESTION = "suggestion"  # Direct recommendation
    REMINDER = "reminder"    # Time-based reminder
    WARNING = "warning"      # Caution about something
    INSIGHT = "insight"      # Proactive information sharing


class UserResponse(str, Enum):
    """How the user responded to an intervention."""
    ACCEPTED = "accepted"    # User acted on the suggestion
    IGNORED = "ignored"      # User didn't respond
    REJECTED = "rejected"    # User explicitly declined
    EXPIRED = "expired"      # Hint timed out without user action (system-closed)
    PENDING = "pending"      # Waiting for response


@dataclass
class Intervention:
    """A proactive intervention record."""
    id: str
    intervention_type: InterventionType
    content: str
    context: str
    created_at: datetime
    user_response: UserResponse = UserResponse.PENDING
    response_at: Optional[datetime] = None
    metadata: Dict[str, Any] = None


class ProactiveMetrics:
    """
    Tracks proactive intervention metrics for observability.
    """

    def __init__(self):
        self._start_time = time.time()

        # Counters by type
        self._interventions_total: Dict[str, int] = {}
        self._responses: Dict[str, Dict[str, int]] = {}  # type -> response -> count

        # Response times
        self._response_times: Dict[str, List[float]] = {}  # type -> list of seconds

        # Recent interventions for tracking
        self._pending: Dict[str, Intervention] = {}  # id -> intervention

    def record_intervention(
        self,
        intervention_id: str,
        intervention_type: str,
        content: str,
        context: str = "",
        metadata: Dict[str, Any] = None
    ):
        """Record a new proactive intervention."""
        itype = intervention_type.lower()

        # Initialize counters if needed
        if itype not in self._interventions_total:
            self._interventions_total[itype] = 0
            self._responses[itype] = {r.value: 0 for r in UserResponse}
            self._response_times[itype] = []

        self._interventions_total[itype] += 1

        # Store for later response tracking
        intervention = Intervention(
            id=intervention_id,
            intervention_type=InterventionType(itype) if itype in [e.value for e in InterventionType] else InterventionType.HINT,
            content=content,
            context=context,
            created_at=datetime.utcnow(),
            metadata=metadata or {}
        )
        self._pending[intervention_id] = intervention

        log_with_context(
            logger, "debug", "Proactive intervention recorded",
            intervention_id=intervention_id,
            type=itype
        )

    def record_response(
        self,
        intervention_id: str,
        response: str
    ):
        """Record user response to an intervention."""
        if intervention_id not in self._pending:
            log_with_context(
                logger, "warning", "Response for unknown intervention",
                intervention_id=intervention_id
            )
            return

        intervention = self._pending[intervention_id]
        itype = intervention.intervention_type.value
        response_lower = response.lower()

        # Record response
        if response_lower in [r.value for r in UserResponse]:
            self._responses[itype][response_lower] += 1

            # Calculate response time
            response_time = (datetime.utcnow() - intervention.created_at).total_seconds()
            self._response_times[itype].append(response_time)

            # Keep only last 500 response times
            if len(self._response_times[itype]) > 500:
                self._response_times[itype] = self._response_times[itype][-500:]

        # Remove from pending
        del self._pending[intervention_id]

        log_with_context(
            logger, "debug", "Proactive response recorded",
            intervention_id=intervention_id,
            response=response_lower,
            response_time_s=response_time if 'response_time' in dir() else None
        )

    def get_stats(self) -> Dict[str, Any]:
        """Get proactive intervention statistics."""
        stats = {
            "uptime_seconds": time.time() - self._start_time,
            "pending_count": len(self._pending),
            "by_type": {},
            "totals": {
                "interventions": sum(self._interventions_total.values()),
                "accepted": sum(r.get("accepted", 0) for r in self._responses.values()),
                "ignored": sum(r.get("ignored", 0) for r in self._responses.values()),
                "rejected": sum(r.get("rejected", 0) for r in self._responses.values()),
                "expired": sum(r.get("expired", 0) for r in self._responses.values()),
            }
        }

        # Calculate acceptance rate
        total_responses = (
            stats["totals"]["accepted"] +
            stats["totals"]["ignored"] +
            stats["totals"]["rejected"]
        )
        if total_responses > 0:
            stats["totals"]["acceptance_rate"] = stats["totals"]["accepted"] / total_responses
        else:
            stats["totals"]["acceptance_rate"] = None

        # Per-type stats
        for itype in self._interventions_total:
            type_stats = {
                "interventions": self._interventions_total[itype],
                "responses": self._responses.get(itype, {}),
            }

            # Calculate acceptance rate per type
            type_responses = self._responses.get(itype, {})
            type_total = sum(v for k, v in type_responses.items() if k != "pending")
            if type_total > 0:
                type_stats["acceptance_rate"] = type_responses.get("accepted", 0) / type_total

            # Response time stats
            times = self._response_times.get(itype, [])
            if times:
                sorted_times = sorted(times)
                type_stats["response_time"] = {
                    "avg_s": sum(times) / len(times),
                    "p50_s": sorted_times[len(sorted_times) // 2],
                    "p95_s": sorted_times[int(len(sorted_times) * 0.95)] if len(sorted_times) > 1 else sorted_times[0],
                }

            stats["by_type"][itype] = type_stats

        return stats

    def get_prometheus_metrics(self) -> str:
        """Export metrics in Prometheus format."""
        lines = []

        # Intervention counters
        lines.append("# HELP jarvis_proactive_interventions_total Total proactive interventions by type")
        lines.append("# TYPE jarvis_proactive_interventions_total counter")
        for itype, count in self._interventions_total.items():
            lines.append(f'jarvis_proactive_interventions_total{{type="{itype}"}} {count}')

        # Response counters
        lines.append("\n# HELP jarvis_proactive_responses_total User responses to interventions")
        lines.append("# TYPE jarvis_proactive_responses_total counter")
        for itype, responses in self._responses.items():
            for response, count in responses.items():
                lines.append(f'jarvis_proactive_responses_total{{type="{itype}",response="{response}"}} {count}')

        # Acceptance rate gauge
        lines.append("\n# HELP jarvis_proactive_acceptance_rate Acceptance rate of proactive interventions")
        lines.append("# TYPE jarvis_proactive_acceptance_rate gauge")
        for itype, responses in self._responses.items():
            total = sum(v for k, v in responses.items() if k != "pending")
            if total > 0:
                rate = responses.get("accepted", 0) / total
                lines.append(f'jarvis_proactive_acceptance_rate{{type="{itype}"}} {rate:.4f}')

        # Pending count
        lines.append("\n# HELP jarvis_proactive_pending_count Number of interventions awaiting response")
        lines.append("# TYPE jarvis_proactive_pending_count gauge")
        lines.append(f"jarvis_proactive_pending_count {len(self._pending)}")

        return "\n".join(lines)


# Global instance
proactive_metrics = ProactiveMetrics()


# ============ Convenience Functions ============

def track_intervention(
    intervention_type: str,
    content: str,
    context: str = "",
    metadata: Dict[str, Any] = None
) -> str:
    """
    Track a proactive intervention.

    Returns intervention_id for later response tracking.
    """
    import uuid
    intervention_id = f"pi_{uuid.uuid4().hex[:12]}"

    proactive_metrics.record_intervention(
        intervention_id=intervention_id,
        intervention_type=intervention_type,
        content=content,
        context=context,
        metadata=metadata
    )

    return intervention_id


def track_response(intervention_id: str, response: str):
    """Track user response to a proactive intervention."""
    proactive_metrics.record_response(intervention_id, response)


def get_proactive_stats() -> Dict[str, Any]:
    """Get proactive intervention statistics."""
    return proactive_metrics.get_stats()


def get_proactive_prometheus() -> str:
    """Get proactive metrics in Prometheus format."""
    return proactive_metrics.get_prometheus_metrics()
