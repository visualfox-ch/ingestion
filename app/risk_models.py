"""
Risk Models - Shared risk classification enums and types

Purpose:
  Centralized risk definitions to avoid circular imports between
  diff_gate.py and approval_auto.py.

References:
  - NIST Risk Management Framework (simplified)
  - APPROVAL_WORKFLOW_SPEC.md
"""

from enum import Enum


class RiskClass(Enum):
    """NIST-aligned risk classification (simplified for code changes)."""
    R0 = "R0"  # Low-risk: config, docs, optimization
    R1 = "R1"  # Medium: small feature, refactor
    R2 = "R2"  # High: critical path, API change
    R3 = "R3"  # Escalate: security, breaking change
