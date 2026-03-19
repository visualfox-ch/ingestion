"""
Audit Trail Module (Gate A Compliance)

Immutable record of all approval decisions with cryptographic proof.
- Every approval decision logged with audit hash
- 7-year retention (compliance)
- Rollback-proof (git revert after audit check)

Policy: AUTONOMOUS_WRITE_SAFETY_BASELINE.md
"""

import hashlib
import json
import uuid
from datetime import datetime, timedelta
from typing import Dict, Optional, List, Any
from dataclasses import dataclass, asdict
import logging

from .observability import get_logger, log_with_context
from .db_safety import safe_write_query, safe_list_query
from .tracing import get_trace_context

logger = get_logger("jarvis.audit_trail")


@dataclass
class AuditRecord:
    """Immutable audit trail entry for approval decisions."""
    audit_id: str
    request_id: str  # Links to action_request
    change_id: str  # Change identifier
    decision: str  # "approved" | "rejected" | "requested_changes"
    approver_id: int  # User ID of approver
    approver_name: str  # Human name
    risk_class: str  # R0 | R1 | R2 | R3
    diff_hash: str  # SHA256 of the code diff
    diff_preview: str  # First 500 chars of diff
    decision_rationale: str  # Approver's reason
    decision_timestamp: str  # ISO 8601 UTC
    sla_seconds: int  # Time from request to decision
    sla_met: bool  # True if within 900s (15 min business hours)
    audit_hash: str  # SHA256(audit_id + decision + timestamp + approver + diff_hash)
    created_at: str  # DB insertion timestamp


class AuditTrail:
    """
    Gate A compliance: Immutable audit trail for code modification approvals.
    """

    SCHEMA_SQL = """
    CREATE TABLE IF NOT EXISTS approval_audit_log (
        audit_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        request_id VARCHAR(255) NOT NULL UNIQUE,
        change_id VARCHAR(255) NOT NULL,
        decision VARCHAR(50) NOT NULL CHECK (decision IN ('approved', 'rejected', 'requested_changes')),
        approver_id INTEGER NOT NULL,
        approver_name VARCHAR(255),
        risk_class VARCHAR(10) NOT NULL CHECK (risk_class IN ('R0', 'R1', 'R2', 'R3')),
        diff_hash VARCHAR(64) NOT NULL,
        diff_preview TEXT,
        decision_rationale TEXT,
        decision_timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
        sla_seconds INTEGER NOT NULL,
        sla_met BOOLEAN NOT NULL,
        audit_hash VARCHAR(64) NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,

        -- Constraints for immutability
        CONSTRAINT audit_hash_immutable UNIQUE (audit_hash)
    );

    CREATE INDEX IF NOT EXISTS idx_approval_audit_log_request_id
        ON approval_audit_log (request_id);
    CREATE INDEX IF NOT EXISTS idx_approval_audit_log_approver_id
        ON approval_audit_log (approver_id);
    CREATE INDEX IF NOT EXISTS idx_approval_audit_log_decision_timestamp
        ON approval_audit_log (decision_timestamp DESC);
    CREATE INDEX IF NOT EXISTS idx_approval_audit_log_audit_hash
        ON approval_audit_log (audit_hash);
    CREATE INDEX IF NOT EXISTS idx_approval_audit_log_risk_class
        ON approval_audit_log (risk_class);
    
    -- Audit retention view (7 years per compliance requirement)
    CREATE OR REPLACE VIEW approval_audit_log_retention AS
    SELECT * FROM approval_audit_log
    WHERE created_at >= CURRENT_TIMESTAMP - INTERVAL '7 years'
    AND created_at <= CURRENT_TIMESTAMP;
    
    -- SLA tracking materialized view (15 min business hours)
    CREATE MATERIALIZED VIEW IF NOT EXISTS approval_sla_breaches AS
    SELECT
        audit_id,
        request_id,
        approver_id,
        approver_name,
        risk_class,
        decision_timestamp,
        sla_seconds,
        sla_met,
        CASE
            WHEN sla_seconds > 900 THEN 'SLA_BREACH'
            WHEN sla_seconds > 600 THEN 'APPROACHING_SLA'
            ELSE 'HEALTHY'
        END as sla_status
    FROM approval_audit_log
    WHERE created_at >= CURRENT_TIMESTAMP - INTERVAL '90 days'
    AND sla_met = false;
    
    -- Auto-refresh materialized view on demand
    -- (Application will call REFRESH MATERIALIZED VIEW approval_sla_breaches)
    """

    @staticmethod
    def ensure_schema() -> bool:
        """Ensure audit trail table exists in PostgreSQL."""
        try:
            with safe_write_query("approval_audit_log") as cur:
                cur.execute(AuditTrail.SCHEMA_SQL)
            log_with_context(logger, "info", "Audit trail schema initialized")
            return True
        except Exception as e:
            log_with_context(logger, "error", "Failed to initialize audit trail schema", error=str(e))
            return False

    @staticmethod
    def _calculate_audit_hash(audit_id: str, decision: str, timestamp: str, approver_id: int, diff_hash: str) -> str:
        """
        Calculate SHA256 audit hash.
        Immutable proof: audit_id + decision + timestamp + approver + diff_hash
        """
        data = f"{audit_id}:{decision}:{timestamp}:{approver_id}:{diff_hash}"
        return hashlib.sha256(data.encode()).hexdigest()

    @staticmethod
    def record_decision(
        request_id: str,
        change_id: str,
        decision: str,  # "approved" | "rejected" | "requested_changes"
        approver_id: int,
        approver_name: str,
        risk_class: str,
        diff_hash: str,
        diff_preview: str,
        decision_rationale: str,
        decision_timestamp: datetime,
        sla_seconds: int,
        sla_met: bool
    ) -> Optional[str]:
        """
        Record an approval decision to the immutable audit trail.
        
        Returns: audit_id if successful, None otherwise
        """
        try:
            # Generate unique audit ID
            audit_id = str(uuid.uuid4())
            
            # Timestamp in ISO 8601 UTC
            timestamp_iso = decision_timestamp.isoformat()
            
            # Calculate audit hash
            audit_hash = AuditTrail._calculate_audit_hash(
                audit_id, decision, timestamp_iso, approver_id, diff_hash
            )
            
            # Build insert statement
            insert_sql = """
            INSERT INTO approval_audit_log (
                audit_id,
                request_id,
                change_id,
                decision,
                approver_id,
                approver_name,
                risk_class,
                diff_hash,
                diff_preview,
                decision_rationale,
                decision_timestamp,
                sla_seconds,
                sla_met,
                audit_hash
            ) VALUES (
                %(audit_id)s,
                %(request_id)s,
                %(change_id)s,
                %(decision)s,
                %(approver_id)s,
                %(approver_name)s,
                %(risk_class)s,
                %(diff_hash)s,
                %(diff_preview)s,
                %(decision_rationale)s,
                %(decision_timestamp)s,
                %(sla_seconds)s,
                %(sla_met)s,
                %(audit_hash)s
            )
            RETURNING audit_id;
            """
            
            params = {
                "audit_id": audit_id,
                "request_id": request_id,
                "change_id": change_id,
                "decision": decision,
                "approver_id": approver_id,
                "approver_name": approver_name,
                "risk_class": risk_class,
                "diff_hash": diff_hash,
                "diff_preview": diff_preview[:500] if diff_preview else "",
                "decision_rationale": decision_rationale or "",
                "decision_timestamp": timestamp_iso,
                "sla_seconds": sla_seconds,
                "sla_met": sla_met,
                "audit_hash": audit_hash
            }
            
            with safe_write_query("approval_audit_log") as cur:
                cur.execute(insert_sql, params)
                result = cur.fetchone()
            
            # Log success
            log_with_context(
                logger, "info",
                "Approval decision recorded to audit trail",
                audit_id=audit_id,
                request_id=request_id,
                decision=decision,
                risk_class=risk_class,
                sla_met=sla_met
            )
            
            return audit_id
            
        except Exception as e:
            log_with_context(
                logger, "error",
                "Failed to record audit decision",
                error=str(e),
                request_id=request_id
            )
            return None

    @staticmethod
    def get_decision(audit_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve an audit record by audit_id."""
        try:
            query = "SELECT * FROM approval_audit_log WHERE audit_id = %(audit_id)s;"
            with safe_list_query("approval_audit_log") as cur:
                cur.execute(query, {"audit_id": audit_id})
                results = cur.fetchall()
            
            if results and len(results) > 0:
                return dict(results[0])
            return None
        except Exception as e:
            log_with_context(logger, "error", "Failed to retrieve audit record", error=str(e), audit_id=audit_id)
            return None

    @staticmethod
    def verify_audit_hash(audit_id: str) -> bool:
        """
        Verify that an audit record's hash is intact (immutability check).
        Returns True if hash is valid, False if tampered or not found.
        """
        try:
            record = AuditTrail.get_decision(audit_id)
            if not record:
                return False
            
            # Recalculate hash from stored fields
            expected_hash = AuditTrail._calculate_audit_hash(
                str(record["audit_id"]),
                record["decision"],
                record["decision_timestamp"].isoformat() if isinstance(record["decision_timestamp"], datetime) else record["decision_timestamp"],
                record["approver_id"],
                record["diff_hash"]
            )
            
            # Compare with stored hash
            is_valid = expected_hash == record["audit_hash"]
            
            if not is_valid:
                log_with_context(
                    logger, "error",
                    "Audit hash verification FAILED (possible tampering)",
                    audit_id=audit_id
                )
            
            return is_valid
        except Exception as e:
            log_with_context(logger, "error", "Audit hash verification error", error=str(e), audit_id=audit_id)
            return False

    @staticmethod
    def get_sla_breaches(days_back: int = 90) -> List[Dict[str, Any]]:
        """Get all approval decisions that breached SLA in last N days."""
        try:
            query = """
            SELECT audit_id, request_id, approver_id, approver_name, risk_class,
                   decision_timestamp, sla_seconds, sla_met
            FROM approval_audit_log
            WHERE created_at >= CURRENT_TIMESTAMP - INTERVAL '%s days'
            AND sla_met = false
            ORDER BY decision_timestamp DESC;
            """ % days_back
            
            with safe_list_query("approval_audit_log") as cur:
                cur.execute(query)
                results = cur.fetchall()
            return [dict(r) for r in results] if results else []
        except Exception as e:
            log_with_context(logger, "error", "Failed to retrieve SLA breaches", error=str(e))
            return []

    @staticmethod
    def get_approver_stats(approver_id: int, days_back: int = 30) -> Dict[str, Any]:
        """Get approval statistics for an approver."""
        try:
            query = """
            SELECT
                COUNT(*) as total_approvals,
                SUM(CASE WHEN decision = 'approved' THEN 1 ELSE 0 END) as approved_count,
                SUM(CASE WHEN decision = 'rejected' THEN 1 ELSE 0 END) as rejected_count,
                SUM(CASE WHEN decision = 'requested_changes' THEN 1 ELSE 0 END) as changes_requested_count,
                AVG(sla_seconds) as avg_sla_seconds,
                SUM(CASE WHEN sla_met = true THEN 1 ELSE 0 END) as sla_met_count,
                MAX(decision_timestamp) as last_decision_at
            FROM approval_audit_log
            WHERE approver_id = %(approver_id)s
            AND created_at >= CURRENT_TIMESTAMP - INTERVAL '%s days';
            """ % days_back
            
            with safe_list_query("approval_audit_log") as cur:
                cur.execute(query, {"approver_id": approver_id})
                results = cur.fetchall()
            return dict(results[0]) if results and len(results) > 0 else {}
        except Exception as e:
            log_with_context(logger, "error", "Failed to get approver stats", error=str(e), approver_id=approver_id)
            return {}


# Initialize schema on module load
AuditTrail.ensure_schema()
