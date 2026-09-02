-- Sprint 8: Release evidence table for governed deployments.
-- The release-evidence API (/api/qa/release-evidence) referenced release_evidences
-- but no migration ever created it — this fills the gap so the panel returns
-- real rows instead of a missing-table error.
-- Additive migration; safe to rerun.
CREATE TABLE IF NOT EXISTS release_evidences (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id TEXT NOT NULL DEFAULT 'default',
  commit_sha TEXT NOT NULL,
  build_id TEXT,
  schema_version TEXT,
  rule_version TEXT,
  prompt_version TEXT,
  model_version TEXT,
  issue_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
  pr_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
  adr_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
  required_checks JSONB NOT NULL DEFAULT '{}'::jsonb,
  checks_passed BOOLEAN NOT NULL DEFAULT false,
  checks_failed JSONB NOT NULL DEFAULT '[]'::jsonb,
  status TEXT NOT NULL DEFAULT 'pending',
  feature_flags JSONB NOT NULL DEFAULT '[]'::jsonb,
  target_cohort TEXT,
  target_percentage NUMERIC(5,2) NOT NULL DEFAULT 0,
  correlation_id TEXT,
  approver_id UUID REFERENCES profiles(id),
  approver_name TEXT,
  approval_reason TEXT,
  approved_at TIMESTAMPTZ,
  canary_current_stage TEXT,
  observation_metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
  observation_started_at TIMESTAMPTZ,
  observation_ended_at TIMESTAMPTZ,
  rollback_triggered BOOLEAN NOT NULL DEFAULT false,
  rollback_reason TEXT,
  rollback_method TEXT,
  rollback_executed_at TIMESTAMPTZ,
  rollback_executed_by UUID,
  final_conclusion TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_release_evidences_tenant_status
  ON release_evidences(tenant_id, status, created_at DESC);
ALTER TABLE release_evidences ENABLE ROW LEVEL SECURITY;
DO $$
BEGIN
  CREATE POLICY "Release evidences readable by all authenticated"
    ON release_evidences FOR SELECT USING (auth.uid() IS NOT NULL);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
DO $$
BEGIN
  CREATE POLICY "Release evidences writable by service_role"
    ON release_evidences FOR ALL USING (auth.role() = 'service_role');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
