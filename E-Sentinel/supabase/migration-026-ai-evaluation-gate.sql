-- Sprint 4 AI evaluation cases, runs and results.
-- Results are versioned so model/prompt/rule changes remain reproducible.

CREATE TABLE IF NOT EXISTS ai_evaluation_cases (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  dataset_version TEXT NOT NULL,
  evaluation_set TEXT NOT NULL CHECK (evaluation_set IN ('gold', 'boundary', 'safety', 'adversarial', 'regression', 'shadow')),
  input_text TEXT NOT NULL,
  expected_category TEXT NOT NULL,
  expected_block BOOLEAN NOT NULL,
  criticality TEXT NOT NULL CHECK (criticality IN ('none', 'p1', 'p0')),
  requires_evidence BOOLEAN NOT NULL DEFAULT true,
  source_type TEXT NOT NULL DEFAULT 'fixture',
  source_ref TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ai_evaluation_runs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id TEXT NOT NULL,
  dataset_version TEXT NOT NULL,
  evaluation_set TEXT NOT NULL DEFAULT 'all',
  evaluator_version TEXT NOT NULL,
  model_version TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  rule_version TEXT NOT NULL,
  mode TEXT NOT NULL CHECK (mode IN ('offline', 'shadow', 'canary')),
  status TEXT NOT NULL CHECK (status IN ('running', 'passed', 'failed', 'cancelled')),
  sample_count INTEGER NOT NULL DEFAULT 0,
  metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS ai_evaluation_results (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id UUID NOT NULL REFERENCES ai_evaluation_runs(id) ON DELETE CASCADE,
  case_id TEXT NOT NULL REFERENCES ai_evaluation_cases(id),
  predicted_category TEXT NOT NULL,
  blocked BOOLEAN NOT NULL,
  evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
  evidence_coverage NUMERIC(6, 5) NOT NULL DEFAULT 0,
  latency_ms INTEGER NOT NULL DEFAULT 0,
  cost_estimate NUMERIC(12, 6) NOT NULL DEFAULT 0,
  raw_output_ref TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (run_id, case_id)
);

CREATE INDEX IF NOT EXISTS idx_ai_eval_cases_set_version
  ON ai_evaluation_cases(tenant_id, evaluation_set, dataset_version);
CREATE INDEX IF NOT EXISTS idx_ai_eval_runs_status_started
  ON ai_evaluation_runs(tenant_id, status, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_ai_eval_results_run
  ON ai_evaluation_results(run_id, case_id);

ALTER TABLE ai_evaluation_cases ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_evaluation_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_evaluation_results ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
  CREATE POLICY "AI evaluation cases require matching tenant" ON ai_evaluation_cases
    FOR SELECT USING (auth.uid() IS NOT NULL AND tenant_id = COALESCE(auth.jwt() ->> 'tenant_id', auth.jwt() -> 'app_metadata' ->> 'tenant_id'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
  CREATE POLICY "AI evaluation runs require matching tenant" ON ai_evaluation_runs
    FOR SELECT USING (auth.uid() IS NOT NULL AND tenant_id = COALESCE(auth.jwt() ->> 'tenant_id', auth.jwt() -> 'app_metadata' ->> 'tenant_id'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
  CREATE POLICY "AI evaluation results require matching run tenant" ON ai_evaluation_results
    FOR SELECT USING (
      auth.uid() IS NOT NULL
      AND EXISTS (
        SELECT 1 FROM ai_evaluation_runs runs
        WHERE runs.id = run_id
          AND runs.tenant_id = COALESCE(auth.jwt() ->> 'tenant_id', auth.jwt() -> 'app_metadata' ->> 'tenant_id')
      )
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
