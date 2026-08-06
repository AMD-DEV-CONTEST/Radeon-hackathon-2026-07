-- Daily reports are keyed by report type and period to make retries harmless.
CREATE UNIQUE INDEX IF NOT EXISTS idx_robot_reports_daily_period
  ON robot_reports(report_type, period_start)
  WHERE report_type = 'daily';
