"""
Gate B: Permission Matrix hardening - Database schema migration.
Creates tables for permission decision tracking and audit correlation.
"""

from datetime import datetime

def up(db_connection):
    """Create permission matrix tables."""
    with db_connection.cursor() as cur:
        # Permission audit log - tracks all permission checks
        cur.execute("""
        CREATE TABLE IF NOT EXISTS permission_audit (
            id SERIAL PRIMARY KEY,
            actor TEXT NOT NULL,
            action TEXT NOT NULL,
            result VARCHAR(50) NOT NULL DEFAULT 'unknown',
            tier VARCHAR(50),
            risk_level VARCHAR(20),
            context JSONB,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE INDEX idx_permission_audit_actor ON permission_audit(actor);
        CREATE INDEX idx_permission_audit_action ON permission_audit(action);
        CREATE INDEX idx_permission_audit_created ON permission_audit(created_at);
        """)
        
        # Permission decision log - links to approval decisions
        cur.execute("""
        CREATE TABLE IF NOT EXISTS permission_decision_log (
            id SERIAL PRIMARY KEY,
            audit_id TEXT NOT NULL REFERENCES approval_audit_log(audit_id) ON DELETE CASCADE,
            permission_tier VARCHAR(50),
            risk_level VARCHAR(20),
            user_role VARCHAR(50),
            decision VARCHAR(20) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE INDEX idx_permission_decision_audit_id ON permission_decision_log(audit_id);
        CREATE INDEX idx_permission_decision_decision ON permission_decision_log(decision);
        """)
        
        # User roles - extends existing users table
        cur.execute("""
        CREATE TABLE IF NOT EXISTS user_roles (
            user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            role VARCHAR(50) NOT NULL DEFAULT 'user',
            assigned_by INTEGER REFERENCES users(id),
            assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE INDEX idx_user_roles_role ON user_roles(role);
        """)
        
        # Time-based permission overrides (admin can temporarily override restrictions)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS permission_overrides (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            action TEXT NOT NULL,
            override_reason TEXT,
            approved_by INTEGER REFERENCES users(id),
            valid_from TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            valid_until TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE INDEX idx_permission_overrides_user ON permission_overrides(user_id);
        CREATE INDEX idx_permission_overrides_action ON permission_overrides(action);
        CREATE INDEX idx_permission_overrides_valid ON permission_overrides(valid_from, valid_until);
        """)
        
        # Rate limiting cache (per user/action)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS permission_rate_limit (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            action TEXT NOT NULL,
            count_in_window INTEGER DEFAULT 0,
            window_start TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            reset_at TIMESTAMP,
            UNIQUE(user_id, action)
        );
        
        CREATE INDEX idx_permission_rate_limit_reset ON permission_rate_limit(reset_at);
        """)
        
        # Role-action mapping cache (for performance)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS role_action_cache (
            id SERIAL PRIMARY KEY,
            role VARCHAR(50) NOT NULL,
            action TEXT NOT NULL,
            allowed_tier VARCHAR(50) NOT NULL,
            description TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(role, action)
        );
        
        CREATE INDEX idx_role_action_cache_role ON role_action_cache(role);
        CREATE INDEX idx_role_action_cache_action ON role_action_cache(action);
        """)
        
        # View: Permission decision SLA tracking
        cur.execute("""
        DROP VIEW IF EXISTS v_permission_decision_sla CASCADE;
        
        CREATE VIEW v_permission_decision_sla AS
        SELECT
            pdl.id,
            pdl.audit_id,
            pdl.permission_tier,
            pdl.risk_level,
            pdl.decision,
            pdl.created_at,
            aal.approval_status,
            EXTRACT(EPOCH FROM (aal.decided_at - aal.created_at))::INTEGER as decision_seconds,
            CASE
                WHEN pdl.risk_level = 'critical' THEN 300
                WHEN pdl.risk_level = 'high' THEN 600
                ELSE 900
            END as sla_seconds,
            EXTRACT(EPOCH FROM (aal.decided_at - aal.created_at))::INTEGER <= 
                CASE
                    WHEN pdl.risk_level = 'critical' THEN 300
                    WHEN pdl.risk_level = 'high' THEN 600
                    ELSE 900
                END as sla_met
        FROM permission_decision_log pdl
        LEFT JOIN approval_audit_log aal ON pdl.audit_id = aal.audit_id
        WHERE pdl.created_at >= NOW() - INTERVAL '90 days';
        """)
        
        # View: Risk-based approval escalation report
        cur.execute("""
        DROP VIEW IF EXISTS v_risk_escalation_report CASCADE;
        
        CREATE VIEW v_risk_escalation_report AS
        SELECT
            pdl.permission_tier,
            pdl.risk_level,
            COUNT(*) as count,
            COUNT(CASE WHEN pdl.decision = 'approved' THEN 1 END) as approved,
            COUNT(CASE WHEN pdl.decision = 'rejected' THEN 1 END) as rejected,
            ROUND(100.0 * COUNT(CASE WHEN pdl.decision = 'approved' THEN 1 END) / COUNT(*), 2) as approval_rate
        FROM permission_decision_log pdl
        WHERE pdl.created_at >= NOW() - INTERVAL '7 days'
        GROUP BY pdl.permission_tier, pdl.risk_level
        ORDER BY pdl.risk_level DESC, count DESC;
        """)
        
        db_connection.commit()
        print("✅ Gate B: Permission matrix tables created successfully")

def down(db_connection):
    """Rollback permission matrix tables."""
    with db_connection.cursor() as cur:
        # Drop in reverse order (handle dependencies)
        cur.execute("DROP VIEW IF EXISTS v_risk_escalation_report CASCADE;")
        cur.execute("DROP VIEW IF EXISTS v_permission_decision_sla CASCADE;")
        cur.execute("DROP TABLE IF EXISTS role_action_cache CASCADE;")
        cur.execute("DROP TABLE IF EXISTS permission_rate_limit CASCADE;")
        cur.execute("DROP TABLE IF EXISTS permission_overrides CASCADE;")
        cur.execute("DROP TABLE IF EXISTS user_roles CASCADE;")
        cur.execute("DROP TABLE IF EXISTS permission_decision_log CASCADE;")
        cur.execute("DROP TABLE IF EXISTS permission_audit CASCADE;")
        
        db_connection.commit()
        print("✅ Gate B: Permission matrix tables rolled back")
