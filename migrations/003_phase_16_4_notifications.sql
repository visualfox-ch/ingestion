-- Phase 16.4B: Notification System Tables
-- Migration: 003_phase_16_4_notifications.sql
-- Created: 2026-02-01
-- Author: Claude Code

-- =============================================================================
-- NOTIFICATION TEMPLATES
-- =============================================================================

CREATE TABLE IF NOT EXISTS notification_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Template identification
    template_key VARCHAR(100) UNIQUE NOT NULL,  -- 'remediation_pending', 'followup_overdue', etc
    name VARCHAR(200) NOT NULL,
    description TEXT,

    -- Channel-specific content
    telegram_template TEXT,        -- Telegram message format
    email_subject_template TEXT,   -- Email subject line
    email_body_template TEXT,      -- Email body (HTML)
    dashboard_template TEXT,       -- Dashboard notification format

    -- Configuration
    default_priority INT DEFAULT 3,  -- 1=urgent, 2=high, 3=normal, 4=low
    is_active BOOLEAN DEFAULT true,

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- =============================================================================
-- NOTIFICATION HISTORY/LOG
-- =============================================================================

CREATE TABLE IF NOT EXISTS notification_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Recipient
    user_id VARCHAR(100) NOT NULL,

    -- Event reference
    event_type VARCHAR(100) NOT NULL,   -- 'remediation_pending', 'followup_overdue', etc
    event_id VARCHAR(100),              -- ID of the triggering object

    -- Delivery info
    channel VARCHAR(50) NOT NULL,       -- 'telegram', 'email', 'dashboard', 'push'
    template_key VARCHAR(100),          -- Reference to template used

    -- Content (rendered)
    title VARCHAR(500),
    body TEXT,
    action_buttons JSONB,               -- [{label: 'Approve', action: 'approve', data: {...}}]

    -- Status tracking
    status VARCHAR(50) DEFAULT 'pending',  -- 'pending', 'sent', 'delivered', 'read', 'failed', 'skipped'
    priority INT DEFAULT 3,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    sent_at TIMESTAMPTZ,
    delivered_at TIMESTAMPTZ,
    read_at TIMESTAMPTZ,

    -- Error tracking
    error_message TEXT,
    retry_count INT DEFAULT 0,

    -- Rate limiting
    is_duplicate BOOLEAN DEFAULT false,
    duplicate_of UUID REFERENCES notification_log(id),
    skip_reason VARCHAR(100)            -- 'rate_limit', 'quiet_hours', 'duplicate', 'disabled'
);

-- =============================================================================
-- USER NOTIFICATION PREFERENCES
-- =============================================================================

CREATE TABLE IF NOT EXISTS user_notification_preferences (
    user_id VARCHAR(100) PRIMARY KEY,

    -- Channel preferences
    telegram_enabled BOOLEAN DEFAULT true,
    email_enabled BOOLEAN DEFAULT true,
    dashboard_enabled BOOLEAN DEFAULT true,
    push_enabled BOOLEAN DEFAULT false,

    -- Rate limiting
    max_notifications_per_hour INT DEFAULT 10,
    max_notifications_per_day INT DEFAULT 50,

    -- Quiet hours (no notifications)
    quiet_hours_enabled BOOLEAN DEFAULT false,
    quiet_hours_start TIME DEFAULT '22:00',
    quiet_hours_end TIME DEFAULT '07:00',
    timezone VARCHAR(50) DEFAULT 'Europe/Zurich',

    -- Event-specific preferences
    remediation_alerts BOOLEAN DEFAULT true,
    followup_reminders BOOLEAN DEFAULT true,
    vip_notifications BOOLEAN DEFAULT true,
    system_alerts BOOLEAN DEFAULT true,

    -- Digest preferences
    digest_enabled BOOLEAN DEFAULT false,
    digest_frequency VARCHAR(20) DEFAULT 'daily',  -- 'daily', 'weekly'
    digest_time TIME DEFAULT '08:00',

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- =============================================================================
-- INDEXES FOR PERFORMANCE
-- =============================================================================

-- Notification log indexes
CREATE INDEX IF NOT EXISTS idx_notification_log_user ON notification_log(user_id);
CREATE INDEX IF NOT EXISTS idx_notification_log_event ON notification_log(event_id);
CREATE INDEX IF NOT EXISTS idx_notification_log_status ON notification_log(status);
CREATE INDEX IF NOT EXISTS idx_notification_log_created ON notification_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_notification_log_channel ON notification_log(channel);
CREATE INDEX IF NOT EXISTS idx_notification_log_user_status ON notification_log(user_id, status);

-- Template indexes
CREATE INDEX IF NOT EXISTS idx_notification_templates_key ON notification_templates(template_key);
CREATE INDEX IF NOT EXISTS idx_notification_templates_active ON notification_templates(is_active);

-- =============================================================================
-- INSERT DEFAULT TEMPLATES
-- =============================================================================

INSERT INTO notification_templates (template_key, name, description, telegram_template, email_subject_template, email_body_template, dashboard_template, default_priority)
VALUES
    (
        'remediation_pending',
        'Remediation Pending Approval',
        'Notification when a remediation action needs approval',
        E'⚠️ *Remediation Required*\n\n{issue_type}: {issue_description}\n\nAction: {remediation_type}\nTier: {tier}\n\n[Approve] [Reject] [Details]',
        '⚠️ Remediation Required: {issue_type}',
        E'<h2>Remediation Action Needed</h2>\n<p><strong>Issue:</strong> {issue_description}</p>\n<p><strong>Recommended Action:</strong> {remediation_type}</p>\n<p><strong>Tier:</strong> {tier}</p>\n<p><a href="{approve_url}">Approve</a> | <a href="{reject_url}">Reject</a></p>',
        '{issue_type}: {issue_description}',
        2
    ),
    (
        'remediation_executed',
        'Remediation Executed',
        'Notification when a remediation action completes',
        E'✅ *Remediation Complete*\n\n{remediation_type} executed successfully.\n\nResult: {result_summary}',
        '✅ Remediation Complete: {remediation_type}',
        E'<h2>Remediation Executed Successfully</h2>\n<p><strong>Action:</strong> {remediation_type}</p>\n<p><strong>Result:</strong> {result_summary}</p>',
        'Remediation {remediation_type} completed',
        3
    ),
    (
        'followup_overdue',
        'Follow-up Overdue',
        'Reminder when a follow-up action is overdue',
        E'📌 *Follow-up Reminder*\n\nRemember: {action_name} with {person_name}\nIt''s been {days_overdue} days...\n\n[Mark Done] [Reschedule] [Dismiss]',
        '📌 Follow-up Overdue: {person_name}',
        E'<h2>Follow-up Reminder</h2>\n<p><strong>Action:</strong> {action_name}</p>\n<p><strong>Person:</strong> {person_name}</p>\n<p><strong>Overdue by:</strong> {days_overdue} days</p>',
        'Follow-up with {person_name} overdue',
        3
    ),
    (
        'vip_replied',
        'VIP Email Reply',
        'Notification when a VIP contact replies',
        E'✉️ *{person_name} replied*\n\nSubject: {original_subject}\n\n{message_preview}...\n\n[Open] [Mark Read]',
        '✉️ VIP Reply: {person_name}',
        E'<h2>VIP Email Reply</h2>\n<p><strong>From:</strong> {person_name}</p>\n<p><strong>Subject:</strong> {original_subject}</p>\n<p>{message_preview}...</p>',
        '{person_name} replied to {original_subject}',
        2
    ),
    (
        'system_alert',
        'System Alert',
        'Critical system notifications',
        E'🚨 *System Alert*\n\n{alert_type}: {alert_message}\n\nSeverity: {severity}',
        '🚨 System Alert: {alert_type}',
        E'<h2>System Alert</h2>\n<p><strong>Type:</strong> {alert_type}</p>\n<p><strong>Message:</strong> {alert_message}</p>\n<p><strong>Severity:</strong> {severity}</p>',
        'System: {alert_type}',
        1
    )
ON CONFLICT (template_key) DO NOTHING;

-- =============================================================================
-- INSERT DEFAULT USER PREFERENCES (for Micha)
-- =============================================================================

INSERT INTO user_notification_preferences (user_id, telegram_enabled, email_enabled, quiet_hours_enabled, quiet_hours_start, quiet_hours_end)
VALUES ('micha', true, true, true, '22:00', '07:00')
ON CONFLICT (user_id) DO NOTHING;

-- =============================================================================
-- HELPER FUNCTION: Check Rate Limit
-- =============================================================================

CREATE OR REPLACE FUNCTION check_notification_rate_limit(
    p_user_id VARCHAR(100),
    p_channel VARCHAR(50)
) RETURNS BOOLEAN AS $$
DECLARE
    v_prefs user_notification_preferences%ROWTYPE;
    v_count_hour INT;
    v_count_day INT;
    v_current_time TIME;
BEGIN
    -- Get user preferences
    SELECT * INTO v_prefs FROM user_notification_preferences WHERE user_id = p_user_id;

    -- If no preferences, allow (but log warning)
    IF NOT FOUND THEN
        RETURN true;
    END IF;

    -- Check quiet hours
    v_current_time := CURRENT_TIME;
    IF v_prefs.quiet_hours_enabled THEN
        IF v_prefs.quiet_hours_start < v_prefs.quiet_hours_end THEN
            -- Same day range (e.g., 09:00 - 17:00)
            IF v_current_time BETWEEN v_prefs.quiet_hours_start AND v_prefs.quiet_hours_end THEN
                RETURN false;
            END IF;
        ELSE
            -- Overnight range (e.g., 22:00 - 07:00)
            IF v_current_time >= v_prefs.quiet_hours_start OR v_current_time <= v_prefs.quiet_hours_end THEN
                RETURN false;
            END IF;
        END IF;
    END IF;

    -- Check hourly limit
    SELECT COUNT(*) INTO v_count_hour
    FROM notification_log
    WHERE user_id = p_user_id
      AND channel = p_channel
      AND status = 'sent'
      AND created_at > NOW() - INTERVAL '1 hour';

    IF v_count_hour >= v_prefs.max_notifications_per_hour THEN
        RETURN false;
    END IF;

    -- Check daily limit
    SELECT COUNT(*) INTO v_count_day
    FROM notification_log
    WHERE user_id = p_user_id
      AND channel = p_channel
      AND status = 'sent'
      AND created_at > NOW() - INTERVAL '1 day';

    IF v_count_day >= v_prefs.max_notifications_per_day THEN
        RETURN false;
    END IF;

    RETURN true;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- MIGRATION COMPLETE
-- =============================================================================

-- Add comment for tracking
COMMENT ON TABLE notification_templates IS 'Phase 16.4B: Notification message templates';
COMMENT ON TABLE notification_log IS 'Phase 16.4B: Notification delivery history and tracking';
COMMENT ON TABLE user_notification_preferences IS 'Phase 16.4B: User notification settings and rate limits';
