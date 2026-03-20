"""
Phase 1: Conditional Auto-Approval - Database schema migration.
Creates tables for confidence scoring and auto-approval decision tracking.
"""

from datetime import datetime

def up(db_connection):
    """Create Phase 1 auto-approval tables."""
    with db_connection.cursor() as cur:
        # Confidence score log - tracks scoring decisions
        cur.execute("""
        CREATE TABLE IF NOT EXISTS confidence_score_log (
            id SERIAL PRIMARY KEY,
            change_id TEXT NOT NULL,
            audit_id TEXT NOT NULL REFERENCES approval_audit_log(audit_id) ON DELETE CASCADE,
            confidence_score NUMERIC(3, 2) CHECK (confidence_score >= 0 AND confidence_score <= 1),
            components JSONB,
            reasoning JSONB,
            auto_approved BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE INDEX idx_confidence_score_change_id ON confidence_score_log(change_id);
        CREATE INDEX idx_confidence_score_audit_id ON confidence_score_log(audit_id);
        CREATE INDEX idx_confidence_score_auto ON confidence_score_log(auto_approved);
        CREATE INDEX idx_confidence_score_created ON confidence_score_log(created_at);
        """)
        
        # Auto approval decisions - tracks what was auto-approved
        cur.execute("""
        CREATE TABLE IF NOT EXISTS auto_approval_decisions (
            id SERIAL PRIMARY KEY,
            change_id TEXT NOT NULL UNIQUE,
            audit_id TEXT NOT NULL REFERENCES approval_audit_log(audit_id) ON DELETE CASCADE,
            risk_level VARCHAR(20) NOT NULL,
            confidence_score NUMERIC(3, 2) NOT NULL,
            user_role VARCHAR(50) NOT NULL,
            decision VARCHAR(20) NOT NULL CHECK (decision IN ('auto_approved', 'manual_required', 'queued')),
            decision_reason TEXT,
            executed BOOLEAN DEFAULT FALSE,
            execution_success BOOLEAN,
            execution_error TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            executed_at TIMESTAMP
        );
        
        CREATE INDEX idx_auto_approval_decision ON auto_approval_decisions(decision);
        CREATE INDEX idx_auto_approval_executed ON auto_approval_decisions(executed);
        CREATE INDEX idx_auto_approval_created ON auto_approval_decisions(created_at);
        """)
        
        # False positive tracking for confidence model tuning
        cur.execute("""
        CREATE TABLE IF NOT EXISTS confidence_false_positives (
            id SERIAL PRIMARY KEY,
            auto_approval_id INTEGER NOT NULL REFERENCES auto_approval_decisions(id) ON DELETE CASCADE,
            change_id TEXT NOT NULL,
            audit_id TEXT NOT NULL,
            confidence_score NUMERIC(3, 2),
            expected_behavior TEXT,
            actual_behavior TEXT,
            impact VARCHAR(20) CHECK (impact IN ('minor', 'moderate', 'critical')),
            reported_by INTEGER REFERENCES users(id),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE INDEX idx_false_positive_auto_approval ON confidence_false_positives(auto_approval_id);
        CREATE INDEX idx_false_positive_impact ON confidence_false_positives(impact);
        """)
        
        # View: Auto-approval effectiveness metrics
        cur.execute("""
        DROP VIEW IF EXISTS v_auto_approval_effectiveness CASCADE;
        
        CREATE VIEW v_auto_approval_effectiveness AS
        SELECT
            DATE(aad.created_at) as date,
            COUNT(*) as total_auto_approvals,
            COUNT(CASE WHEN aad.executed = true THEN 1 END) as executed,
            COUNT(CASE WHEN aad.executed = true AND aad.execution_success = true THEN 1 END) as successful,
            COUNT(CASE WHEN cfp.id IS NOT NULL THEN 1 END) as false_positives,
            ROUND(
                100.0 * COUNT(CASE WHEN aad.executed = true AND aad.execution_success = true THEN 1 END) /
                NULLIF(COUNT(CASE WHEN aad.executed = true THEN 1 END), 0),
                2
            ) as success_rate,
            ROUND(
                100.0 * COUNT(CASE WHEN cfp.id IS NOT NULL THEN 1 END) /
                NULLIF(COUNT(*), 0),
                2
            ) as false_positive_rate
        FROM auto_approval_decisions aad
        LEFT JOIN confidence_false_positives cfp ON aad.id = cfp.auto_approval_id
        WHERE aad.created_at >= NOW() - INTERVAL '90 days'
        GROUP BY DATE(aad.created_at)
        ORDER BY DATE(aad.created_at) DESC;
        """)
        
        # View: Confidence score distribution by risk level
        cur.execute("""
        DROP VIEW IF EXISTS v_confidence_distribution CASCADE;
        
        CREATE VIEW v_confidence_distribution AS
        SELECT
            aad.risk_level,
            ROUND(csl.confidence_score::NUMERIC, 1) as score_bucket,
            COUNT(*) as count,
            COUNT(CASE WHEN aad.executed = true AND aad.execution_success = true THEN 1 END) as successes,
            ROUND(
                100.0 * COUNT(CASE WHEN aad.executed = true AND aad.execution_success = true THEN 1 END) /
                NULLIF(COUNT(*), 0),
                2
            ) as success_rate
        FROM auto_approval_decisions aad
        LEFT JOIN confidence_score_log csl ON aad.audit_id = csl.audit_id
        WHERE aad.created_at >= NOW() - INTERVAL '30 days'
        GROUP BY aad.risk_level, ROUND(csl.confidence_score::NUMERIC, 1)
        ORDER BY aad.risk_level, score_bucket DESC;
        """)
        
        db_connection.commit()
        print("✅ Phase 1: Auto-approval tables created successfully")

def down(db_connection):
    """Rollback Phase 1 auto-approval tables."""
    with db_connection.cursor() as cur:
        cur.execute("DROP VIEW IF EXISTS v_confidence_distribution CASCADE;")
        cur.execute("DROP VIEW IF EXISTS v_auto_approval_effectiveness CASCADE;")
        cur.execute("DROP TABLE IF EXISTS confidence_false_positives CASCADE;")
        cur.execute("DROP TABLE IF EXISTS auto_approval_decisions CASCADE;")
        cur.execute("DROP TABLE IF EXISTS confidence_score_log CASCADE;")
        
        db_connection.commit()
        print("✅ Phase 1: Auto-approval tables rolled back")
