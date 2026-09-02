-- Governance foundation: role compatibility, evidence events, evaluations,
-- findings, approvals and work items. Safe to run repeatedly.

ALTER TABLE profiles DROP CONSTRAINT IF EXISTS profiles_role_check;
ALTER TABLE profiles ADD CONSTRAINT profiles_role_check
  CHECK (role IN ('agent', 'team_lead', 'operator', 'admin', 'viewer'));

ALTER TABLE profiles ADD COLUMN IF NOT EXISTS tenant_id TEXT;
CREATE INDEX IF NOT EXISTS idx_profiles_tenant_team ON profiles(tenant_id, team_id);

CREATE TABLE IF NOT EXISTS evidence_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id TEXT NOT NULL UNIQUE,
  schema_version TEXT NOT NULL DEFAULT '1.0',
  tenant_id TEXT NOT NULL,
  team_id TEXT,
  source TEXT NOT NULL,
  event_type TEXT NOT NULL,
  occurred_at TIMESTAMPTZ NOT NULL,
  actor_id TEXT NOT NULL,
  actor_type TEXT NOT NULL CHECK (actor_type IN ('user', 'service', 'system')),
  actor_name TEXT,
  correlation_id TEXT NOT NULL,
  payload_ref TEXT,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  processing_status TEXT NOT NULL DEFAULT 'received'
    CHECK (processing_status IN ('received', 'processing', 'processed', 'failed')),
  processing_log JSONB NOT NULL DEFAULT '[]'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_evidence_events_tenant_time
  ON evidence_events(tenant_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_evidence_events_correlation
  ON evidence_events(correlation_id);
CREATE INDEX IF NOT EXISTS idx_evidence_events_type
  ON evidence_events(source, event_type, occurred_at DESC);

CREATE TABLE IF NOT EXISTS evaluations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id TEXT NOT NULL,
  team_id TEXT,
  subject_type TEXT NOT NULL,
  subject_id TEXT NOT NULL,
  event_id UUID REFERENCES evidence_events(id),
  rule_version TEXT NOT NULL,
  model_version TEXT,
  score NUMERIC,
  risk TEXT NOT NULL CHECK (risk IN ('low', 'medium', 'high', 'critical')),
  explanations JSONB NOT NULL DEFAULT '{}'::jsonb,
  evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
  decision TEXT NOT NULL DEFAULT 'review'
    CHECK (decision IN ('pass', 'review', 'block', 'override')),
  correlation_id TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS findings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id TEXT NOT NULL,
  evaluation_id UUID NOT NULL REFERENCES evaluations(id) ON DELETE CASCADE,
  severity TEXT NOT NULL CHECK (severity IN ('info', 'minor', 'major', 'critical')),
  category TEXT NOT NULL,
  evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
  decision TEXT NOT NULL DEFAULT 'open'
    CHECK (decision IN ('open', 'accepted', 'rejected', 'waived')),
  review_status TEXT NOT NULL DEFAULT 'pending'
    CHECK (review_status IN ('pending', 'approved', 'overturned', 'closed')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS approvals (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id TEXT NOT NULL,
  action_type TEXT NOT NULL,
  subject_type TEXT NOT NULL,
  subject_id TEXT NOT NULL,
  approver_id UUID REFERENCES profiles(id),
  decision TEXT NOT NULL CHECK (decision IN ('pending', 'approved', 'rejected', 'expired')),
  reason TEXT,
  expires_at TIMESTAMPTZ,
  correlation_id TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  decided_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS governance_work_items (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id TEXT NOT NULL,
  team_id TEXT,
  source_finding_id UUID REFERENCES findings(id),
  source_type TEXT NOT NULL CHECK (source_type IN ('event', 'evaluation', 'finding', 'manual')),
  source_id TEXT NOT NULL,
  title TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  owner_id UUID REFERENCES profiles(id),
  priority TEXT NOT NULL DEFAULT 'medium' CHECK (priority IN ('low', 'medium', 'high', 'critical')),
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'in_progress', 'blocked', 'resolved', 'closed')),
  sla_at TIMESTAMPTZ,
  close_evidence JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  closed_at TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_governance_work_items_source
  ON governance_work_items(tenant_id, source_type, source_id);

ALTER TABLE evidence_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE evaluations ENABLE ROW LEVEL SECURITY;
ALTER TABLE findings ENABLE ROW LEVEL SECURITY;
ALTER TABLE approvals ENABLE ROW LEVEL SECURITY;
ALTER TABLE governance_work_items ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
  CREATE POLICY "Governance events require matching tenant" ON evidence_events
    FOR SELECT USING (auth.uid() IS NOT NULL AND tenant_id = COALESCE(auth.jwt() ->> 'tenant_id', auth.jwt() -> 'app_metadata' ->> 'tenant_id'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
  CREATE POLICY "Governance evaluations require matching tenant" ON evaluations
    FOR SELECT USING (auth.uid() IS NOT NULL AND tenant_id = COALESCE(auth.jwt() ->> 'tenant_id', auth.jwt() -> 'app_metadata' ->> 'tenant_id'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
  CREATE POLICY "Governance findings require matching tenant" ON findings
    FOR SELECT USING (auth.uid() IS NOT NULL AND tenant_id = COALESCE(auth.jwt() ->> 'tenant_id', auth.jwt() -> 'app_metadata' ->> 'tenant_id'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
  CREATE POLICY "Governance approvals require matching tenant" ON approvals
    FOR SELECT USING (auth.uid() IS NOT NULL AND tenant_id = COALESCE(auth.jwt() ->> 'tenant_id', auth.jwt() -> 'app_metadata' ->> 'tenant_id'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
  CREATE POLICY "Governance work items require matching tenant" ON governance_work_items
    FOR SELECT USING (auth.uid() IS NOT NULL AND tenant_id = COALESCE(auth.jwt() ->> 'tenant_id', auth.jwt() -> 'app_metadata' ->> 'tenant_id'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
