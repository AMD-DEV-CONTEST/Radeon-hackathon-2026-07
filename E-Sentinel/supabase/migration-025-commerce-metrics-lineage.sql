-- Sprint 3 metric snapshots and minimal Dataset -> Job -> Run lineage.
-- This migration is additive and safe to rerun after migration-024.

CREATE TABLE IF NOT EXISTS lineage_datasets (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  name TEXT NOT NULL,
  source_type TEXT NOT NULL,
  schema_version TEXT NOT NULL,
  data_class TEXT NOT NULL DEFAULT 'internal'
    CHECK (data_class IN ('public', 'internal', 'sensitive', 'restricted')),
  owner_id UUID REFERENCES profiles(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS lineage_jobs (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  dataset_id TEXT NOT NULL REFERENCES lineage_datasets(id),
  name TEXT NOT NULL,
  definition_version TEXT NOT NULL,
  owner_id UUID REFERENCES profiles(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS lineage_runs (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  job_id TEXT NOT NULL REFERENCES lineage_jobs(id),
  status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'degraded', 'failed')),
  started_at TIMESTAMPTZ NOT NULL,
  finished_at TIMESTAMPTZ,
  input_count INTEGER NOT NULL DEFAULT 0,
  output_count INTEGER NOT NULL DEFAULT 0,
  error_class TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS metric_snapshots (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id TEXT NOT NULL,
  metric_key TEXT NOT NULL,
  value NUMERIC,
  unit TEXT NOT NULL CHECK (unit IN ('count', 'currency', 'ratio')),
  definition_version TEXT NOT NULL,
  dimensions JSONB NOT NULL DEFAULT '{}'::jsonb,
  source_dataset_id TEXT NOT NULL REFERENCES lineage_datasets(id),
  source_job_id TEXT NOT NULL REFERENCES lineage_jobs(id),
  source_run_id TEXT NOT NULL REFERENCES lineage_runs(id),
  window_start TIMESTAMPTZ NOT NULL,
  window_end TIMESTAMPTZ NOT NULL,
  attribution_window TEXT NOT NULL,
  currency TEXT,
  timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
  freshness_at TIMESTAMPTZ,
  quality_status TEXT NOT NULL CHECK (quality_status IN ('complete', 'stale', 'degraded', 'missing')),
  missing_reason TEXT,
  owner_id UUID REFERENCES profiles(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_metric_snapshots_tenant_key_time
  ON metric_snapshots(tenant_id, metric_key, window_end DESC);
CREATE INDEX IF NOT EXISTS idx_metric_snapshots_lineage
  ON metric_snapshots(source_dataset_id, source_job_id, source_run_id);

ALTER TABLE lineage_datasets ENABLE ROW LEVEL SECURITY;
ALTER TABLE lineage_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE lineage_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE metric_snapshots ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
  CREATE POLICY "Lineage datasets require matching tenant" ON lineage_datasets
    FOR SELECT USING (auth.uid() IS NOT NULL AND tenant_id = COALESCE(auth.jwt() ->> 'tenant_id', auth.jwt() -> 'app_metadata' ->> 'tenant_id'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
  CREATE POLICY "Lineage jobs require matching tenant" ON lineage_jobs
    FOR SELECT USING (auth.uid() IS NOT NULL AND tenant_id = COALESCE(auth.jwt() ->> 'tenant_id', auth.jwt() -> 'app_metadata' ->> 'tenant_id'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
  CREATE POLICY "Lineage runs require matching tenant" ON lineage_runs
    FOR SELECT USING (auth.uid() IS NOT NULL AND tenant_id = COALESCE(auth.jwt() ->> 'tenant_id', auth.jwt() -> 'app_metadata' ->> 'tenant_id'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
  CREATE POLICY "Metric snapshots require matching tenant" ON metric_snapshots
    FOR SELECT USING (auth.uid() IS NOT NULL AND tenant_id = COALESCE(auth.jwt() ->> 'tenant_id', auth.jwt() -> 'app_metadata' ->> 'tenant_id'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
