"""
Database migration for n8n Workflow Reliability Tracking (Phase 2)

Adds comprehensive workflow execution tracking, health metrics, and SLA monitoring.

Schema:
- n8n_workflow_executions: Individual execution records with status and timing
- n8n_workflow_health: Current health snapshot for each workflow
- n8n_error_handlers: Error routing and recovery configurations
- v_n8n_sla_metrics: Materialized view for SLA compliance tracking
- v_n8n_failure_analysis: Failure pattern detection for improvement
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

def upgrade():
    # n8n_workflow_executions - Detailed execution records
    op.create_table(
        'n8n_workflow_executions',
        sa.Column('execution_id', sa.String(255), nullable=False, primary_key=True),
        sa.Column('workflow_id', sa.String(255), nullable=False, index=True),
        sa.Column('audit_id', sa.String(255), nullable=True, index=True),  # Link to approval audit trail
        sa.Column('status', sa.String(50), nullable=False),  # success, failed, timeout, rate_limited, permanent_error, retrying
        sa.Column('execution_time_ms', sa.Float, nullable=False),
        sa.Column('error', sa.Text, nullable=True),
        sa.Column('retry_count', sa.Integer, default=0),
        sa.Column('triggered_error_handler', sa.Boolean, default=False),
        sa.Column('recorded_at', sa.DateTime(timezone=True), server_default=sa.func.now(), index=True),
        sa.Index('idx_n8n_workflow_executions_workflow_id', 'workflow_id'),
        sa.Index('idx_n8n_workflow_executions_audit_id', 'audit_id'),
        sa.Index('idx_n8n_workflow_executions_status', 'status'),
        sa.Index('idx_n8n_workflow_executions_recorded_at', 'recorded_at')
    )

    # n8n_workflow_health - Current health status snapshot
    op.create_table(
        'n8n_workflow_health',
        sa.Column('workflow_id', sa.String(255), nullable=False, primary_key=True),
        sa.Column('health_status', sa.String(50), nullable=False),  # up, degraded, down
        sa.Column('response_time_ms', sa.Float, nullable=True),
        sa.Column('last_execution_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('success_rate_24h', sa.Float, nullable=True),  # 0.0-1.0
        sa.Column('error_rate_24h', sa.Float, nullable=True),
        sa.Column('avg_execution_ms', sa.Float, nullable=True),
        sa.Column('p95_execution_ms', sa.Float, nullable=True),
        sa.Column('total_failures_24h', sa.Integer, default=0),
        sa.Column('total_timeouts_24h', sa.Integer, default=0),
        sa.Column('consecutive_failures', sa.Integer, default=0),
        sa.Column('last_error', sa.Text, nullable=True),
        sa.Column('last_checked_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), index=True),
        sa.Index('idx_n8n_workflow_health_status', 'health_status'),
        sa.Index('idx_n8n_workflow_health_updated_at', 'updated_at')
    )

    # n8n_error_handlers - Error routing and recovery policies
    op.create_table(
        'n8n_error_handlers',
        sa.Column('handler_id', sa.String(255), nullable=False, primary_key=True),
        sa.Column('workflow_id', sa.String(255), nullable=False, index=True),
        sa.Column('error_type', sa.String(100), nullable=False),  # rate_limited, timeout, 4xx, 5xx, permanent
        sa.Column('handler_action', sa.String(50), nullable=False),  # retry, alert, escalate, ignore
        sa.Column('retry_max_attempts', sa.Integer, default=3),
        sa.Column('retry_backoff_ms', sa.Integer, default=1000),
        sa.Column('escalate_to_channel', sa.String(100), nullable=True),  # telegram, slack, etc
        sa.Column('audit_trail_enabled', sa.Boolean, default=True),
        sa.Column('enabled', sa.Boolean, default=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Index('idx_n8n_error_handlers_workflow_id', 'workflow_id'),
        sa.Index('idx_n8n_error_handlers_error_type', 'error_type')
    )

    # n8n_workflow_reliability_config - SLA and reliability settings per workflow
    op.create_table(
        'n8n_workflow_reliability_config',
        sa.Column('workflow_id', sa.String(255), nullable=False, primary_key=True),
        sa.Column('workflow_name', sa.String(255), nullable=False),
        sa.Column('tier', sa.String(50), nullable=False),  # critical, standard, best_effort
        sa.Column('success_rate_target', sa.Float, nullable=False, default=0.95),  # 0.0-1.0
        sa.Column('max_response_time_ms', sa.Integer, nullable=False, default=30000),
        sa.Column('max_retries', sa.Integer, nullable=False, default=3),
        sa.Column('alert_on_failure', sa.Boolean, default=True),
        sa.Column('require_audit_trail', sa.Boolean, default=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Index('idx_n8n_workflow_config_tier', 'tier'),
        sa.Index('idx_n8n_workflow_config_updated_at', 'updated_at')
    )

    # Materialized View: v_n8n_sla_metrics - SLA compliance tracking
    op.execute("""
    CREATE MATERIALIZED VIEW v_n8n_sla_metrics AS
    SELECT
        we.workflow_id,
        wrc.workflow_name,
        wrc.tier,
        COUNT(*) FILTER (WHERE we.status = 'success') as successful_executions,
        COUNT(*) as total_executions,
        ROUND(
            COUNT(*) FILTER (WHERE we.status = 'success')::numeric / 
            NULLIF(COUNT(*), 0),
            4
        ) as success_rate_actual,
        wrc.success_rate_target,
        ROUND(AVG(we.execution_time_ms)::numeric, 2) as avg_execution_ms,
        ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY we.execution_time_ms)::numeric, 2) as p95_execution_ms,
        MAX(we.execution_time_ms) as max_execution_ms,
        COUNT(*) FILTER (WHERE we.status = 'failed') as failed_count,
        COUNT(*) FILTER (WHERE we.status = 'timeout') as timeout_count,
        COUNT(*) FILTER (WHERE we.status = 'rate_limited') as rate_limited_count,
        CASE 
            WHEN COUNT(*) FILTER (WHERE we.status = 'success')::numeric / NULLIF(COUNT(*), 0) >= wrc.success_rate_target
            THEN true
            ELSE false
        END as sla_met,
        DATE(we.recorded_at) as metric_date,
        NOW() as last_updated
    FROM n8n_workflow_executions we
    LEFT JOIN n8n_workflow_reliability_config wrc ON we.workflow_id = wrc.workflow_id
    WHERE we.recorded_at > NOW() - INTERVAL '24 hours'
    GROUP BY we.workflow_id, wrc.workflow_name, wrc.tier, wrc.success_rate_target, DATE(we.recorded_at)
    WITH DATA;

    CREATE INDEX idx_v_n8n_sla_metrics_workflow_id ON v_n8n_sla_metrics (workflow_id);
    CREATE INDEX idx_v_n8n_sla_metrics_sla_met ON v_n8n_sla_metrics (sla_met);
    """)

    # Materialized View: v_n8n_failure_analysis - Failure pattern detection
    op.execute("""
    CREATE MATERIALIZED VIEW v_n8n_failure_analysis AS
    SELECT
        we.workflow_id,
        wrc.workflow_name,
        we.status,
        COUNT(*) as failure_count,
        ROUND(AVG(we.execution_time_ms)::numeric, 2) as avg_time_failed_ms,
        MAX(we.retry_count) as max_retries_used,
        SUBSTRING(we.error, 1, 100) as error_summary,
        DATE(we.recorded_at) as failure_date,
        NOW() as analyzed_at
    FROM n8n_workflow_executions we
    LEFT JOIN n8n_workflow_reliability_config wrc ON we.workflow_id = wrc.workflow_id
    WHERE we.status IN ('failed', 'timeout', 'permanent_error', 'rate_limited')
    AND we.recorded_at > NOW() - INTERVAL '7 days'
    GROUP BY we.workflow_id, wrc.workflow_name, we.status, SUBSTRING(we.error, 1, 100), DATE(we.recorded_at)
    ORDER BY failure_count DESC
    WITH DATA;

    CREATE INDEX idx_v_n8n_failure_analysis_workflow_id ON v_n8n_failure_analysis (workflow_id);
    CREATE INDEX idx_v_n8n_failure_analysis_status ON v_n8n_failure_analysis (status);
    """)


def downgrade():
    op.execute("DROP MATERIALIZED VIEW IF EXISTS v_n8n_failure_analysis")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS v_n8n_sla_metrics")
    op.drop_table('n8n_workflow_reliability_config')
    op.drop_table('n8n_error_handlers')
    op.drop_table('n8n_workflow_health')
    op.drop_table('n8n_workflow_executions')
