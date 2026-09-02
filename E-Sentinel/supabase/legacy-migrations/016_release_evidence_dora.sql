-- Sprint 8: Release Evidence & DORA Metrics Tables
-- Tracks release decisions, approvals, rollback drills, and DORA metrics

-- ============================================================================
-- Release Evidence Table
-- ============================================================================

CREATE TABLE IF NOT EXISTS release_evidences (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id TEXT NOT NULL,

  -- Version references
  commit_sha TEXT NOT NULL,
  build_id TEXT,
  schema_version TEXT,
  rule_version TEXT,
  prompt_version TEXT,
  model_version TEXT,

  -- Associated artifacts
  issue_ids TEXT[],
  pr_ids TEXT[],
  adr_refs TEXT[],

  -- Gate checks
  required_checks JSONB DEFAULT '{}',
  checks_passed BOOLEAN DEFAULT false,
  checks_failed JSONB DEFAULT '[]',

  -- Approval
  approver_id TEXT,
  approver_name TEXT,
  approval_reason TEXT,
  approved_at TIMESTAMPTZ,

  -- Feature flags & targeting
  feature_flags JSONB DEFAULT '[]',
  target_cohort TEXT,
  target_percentage INTEGER DEFAULT 0,

  -- Canary & observation
  canary_stages JSONB DEFAULT '[]',
  canary_current_stage TEXT,
  observation_metrics JSONB DEFAULT '{}',
  observation_started_at TIMESTAMPTZ,
  observation_ended_at TIMESTAMPTZ,

  -- Rollback
  rollback_triggered BOOLEAN DEFAULT false,
  rollback_reason TEXT,
  rollback_method TEXT,
  rollback_executed_at TIMESTAMPTZ,
  rollback_executed_by TEXT,

  -- Final status
  status TEXT NOT NULL DEFAULT 'pending',
  final_conclusion TEXT,

  -- Trace
  correlation_id TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_release_evidences_tenant ON release_evidences(tenant_id);
CREATE INDEX IF NOT EXISTS idx_release_evidences_status ON release_evidences(status);
CREATE INDEX IF NOT EXISTS idx_release_evidences_created ON release_evidences(created_at DESC);

-- ============================================================================
-- DORA Metrics Table
-- ============================================================================

CREATE TABLE IF NOT EXISTS dora_metrics (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id TEXT NOT NULL,
  recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  recording_period TEXT NOT NULL, -- 'daily', 'weekly', 'monthly'

  -- Lead Time (time from commit to production)
  change_lead_time_p50_hours DECIMAL(10, 2),
  change_lead_time_p95_hours DECIMAL(10, 2),
  change_lead_time_avg_hours DECIMAL(10, 2),

  -- Deployment Frequency
  deployment_count INTEGER DEFAULT 0,
  deployment_frequency_per_day DECIMAL(10, 4),

  -- Change Fail Rate
  failed_deployments INTEGER DEFAULT 0,
  total_deployments INTEGER DEFAULT 0,
  change_fail_rate DECIMAL(5, 4), -- 0.0 to 1.0

  -- Recovery Time (MTTR)
  recovery_time_p50_minutes DECIMAL(10, 2),
  recovery_time_p95_minutes DECIMAL(10, 2),
  recovery_time_avg_minutes DECIMAL(10, 2),

  -- Deployment Rework Rate
  rework_deployments INTEGER DEFAULT 0,
  rework_rate DECIMAL(5, 4),

  -- Context
  application_name TEXT,
  environment TEXT,

  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dora_metrics_tenant ON dora_metrics(tenant_id);
CREATE INDEX IF NOT EXISTS idx_dora_metrics_period ON dora_metrics(recording_period);
CREATE INDEX IF NOT EXISTS idx_dora_metrics_recorded ON dora_metrics(recorded_at DESC);

-- ============================================================================
-- Rollback Drill Records
-- ============================================================================

CREATE TABLE IF NOT EXISTS rollback_drills (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id TEXT NOT NULL,

  -- Drill context
  drill_name TEXT NOT NULL,
  drill_type TEXT NOT NULL, -- 'scheduled', 'random', 'release_based'
  triggered_by TEXT NOT NULL,

  -- Execution
  started_at TIMESTAMPTZ NOT NULL,
  completed_at TIMESTAMPTZ,
  duration_seconds INTEGER,

  -- Result
  success BOOLEAN,
  failure_reason TEXT,
  missing_steps TEXT[],

  -- Evidence
  release_evidence_id UUID REFERENCES release_evidences(id),
  notes TEXT,

  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_rollback_drills_tenant ON rollback_drills(tenant_id);
CREATE INDEX IF NOT EXISTS idx_rollback_drills_success ON rollback_drills(success);
CREATE INDEX IF NOT EXISTS idx_rollback_drills_started ON rollback_drills(started_at DESC);

-- ============================================================================
-- Comments
-- ============================================================================

COMMENT ON TABLE release_evidences IS 'Sprint 8: 发布证据记录，包含版本、审批、Gate检查、金丝雀阶段和回滚信息';
COMMENT ON TABLE dora_metrics IS 'Sprint 8: DORA 软件交付指标，包含 Lead Time、部署频率、失败率、恢复时间';
COMMENT ON TABLE rollback_drills IS 'Sprint 8: 回滚演练记录，每个 Release 至少一次演练';