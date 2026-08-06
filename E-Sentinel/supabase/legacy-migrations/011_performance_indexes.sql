-- ============================================================
-- Migration: 011 — Performance indexes for E-Sentinel
-- ============================================================

-- performance indexes for E-Sentinel
CREATE INDEX IF NOT EXISTS idx_bot_chat_sessions_created ON bot_chat_sessions(created_at);
CREATE INDEX IF NOT EXISTS idx_bot_chat_sessions_platform ON bot_chat_sessions(platform_id);
CREATE INDEX IF NOT EXISTS idx_quality_reports_created ON quality_reports(created_at);
CREATE INDEX IF NOT EXISTS idx_quality_reports_risk ON quality_reports(risk_level);
CREATE INDEX IF NOT EXISTS idx_work_orders_assignee ON work_orders(assigned_to);
CREATE INDEX IF NOT EXISTS idx_work_orders_status ON work_orders(status);
CREATE INDEX IF NOT EXISTS idx_compliance_rules_active ON compliance_rules(is_active);
CREATE INDEX IF NOT EXISTS idx_audit_logs_action_created ON audit_logs(action, created_at);
CREATE INDEX IF NOT EXISTS idx_profiles_feishu_id ON profiles(feishu_open_id);
