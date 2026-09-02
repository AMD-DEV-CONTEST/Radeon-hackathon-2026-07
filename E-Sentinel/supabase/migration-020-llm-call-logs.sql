-- Persisted LLM observability and cost ledger seed.
CREATE TABLE IF NOT EXISTS llm_call_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  endpoint TEXT NOT NULL,
  model TEXT NOT NULL,
  tokens_used INTEGER NOT NULL DEFAULT 0,
  cost_estimate NUMERIC(12, 6) NOT NULL DEFAULT 0,
  success BOOLEAN NOT NULL DEFAULT false,
  cached BOOLEAN NOT NULL DEFAULT false,
  response_time_ms INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_llm_call_logs_created_at
  ON llm_call_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_llm_call_logs_model_created_at
  ON llm_call_logs(model, created_at DESC);

ALTER TABLE llm_call_logs ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
  CREATE POLICY "LLM call logs require an authenticated user" ON llm_call_logs
    FOR SELECT USING (auth.uid() IS NOT NULL);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
