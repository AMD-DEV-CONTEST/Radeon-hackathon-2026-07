-- Sprint 5: Lost-deal diagnosis with reason tree, evidence layers and human review.
-- Additive migration; safe to rerun.

-- A diagnosis session groups the analysis of one or more lost conversations.
CREATE TABLE IF NOT EXISTS diagnosis_sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id TEXT NOT NULL DEFAULT 'default',
  trigger_type TEXT NOT NULL CHECK (trigger_type IN ('manual', 'auto_batch', 'work_item')),
  status TEXT NOT NULL DEFAULT 'running'
    CHECK (status IN ('running', 'completed', 'failed', 'cancelled')),
  conversation_ids TEXT[] NOT NULL DEFAULT '{}',
  campaign_id TEXT,
  product_id TEXT,
  time_window_start TIMESTAMPTZ,
  time_window_end TIMESTAMPTZ,
  engine_version TEXT NOT NULL DEFAULT 'diagnosis-engine-v1.0',
  summary JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_by UUID REFERENCES profiles(id),
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Each finding is one reason hypothesis with layered evidence.
CREATE TABLE IF NOT EXISTS diagnosis_findings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id UUID NOT NULL REFERENCES diagnosis_sessions(id) ON DELETE CASCADE,
  tenant_id TEXT NOT NULL DEFAULT 'default',
  reason_category TEXT NOT NULL
    CHECK (reason_category IN (
      'traffic_quality', 'product_mismatch', 'price_objection',
      'trust_deficit', 'service_failure', 'inventory_fulfillment',
      'payment_followup', 'unknown'
    )),
  -- Layered output: fact -> inference -> confidence -> suggestion
  fact_statement TEXT NOT NULL,
  inference_statement TEXT,
  confidence TEXT NOT NULL DEFAULT 'low'
    CHECK (confidence IN ('high', 'medium', 'low', 'insufficient')),
  confidence_score NUMERIC(5,4) CHECK (confidence_score >= 0 AND confidence_score <= 1),
  counter_evidence TEXT,
  suggestion TEXT,
  suggestion_actionable BOOLEAN NOT NULL DEFAULT false,
  -- Evidence references
  evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
  -- Link to funnel stage where drop-off detected
  funnel_stage TEXT CHECK (funnel_stage IN ('traffic', 'conversation', 'cart', 'order', 'payment')),
  -- Linked entities
  conversation_id TEXT,
  product_id TEXT,
  campaign_id TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Human review of a diagnosis finding.
CREATE TABLE IF NOT EXISTS diagnosis_reviews (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  finding_id UUID NOT NULL REFERENCES diagnosis_findings(id) ON DELETE CASCADE,
  tenant_id TEXT NOT NULL DEFAULT 'default',
  reviewer_id UUID NOT NULL REFERENCES profiles(id),
  decision TEXT NOT NULL CHECK (decision IN ('accepted', 'modified', 'rejected')),
  modified_reason TEXT,
  rejection_reason TEXT,
  feedback_note TEXT,
  -- Feedback routing: where does the correction go?
  feedback_target TEXT CHECK (feedback_target IN ('rule', 'prompt', 'knowledge', 'model', 'none')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Work items generated from accepted diagnosis findings.
CREATE TABLE IF NOT EXISTS diagnosis_work_items (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  finding_id UUID NOT NULL REFERENCES diagnosis_findings(id) ON DELETE CASCADE,
  session_id UUID NOT NULL REFERENCES diagnosis_sessions(id) ON DELETE CASCADE,
  tenant_id TEXT NOT NULL DEFAULT 'default',
  title TEXT NOT NULL,
  description TEXT,
  assignee_id UUID REFERENCES profiles(id),
  status TEXT NOT NULL DEFAULT 'open'
    CHECK (status IN ('open', 'in_progress', 'done', 'cancelled')),
  priority TEXT NOT NULL DEFAULT 'medium' CHECK (priority IN ('high', 'medium', 'low')),
  sla_deadline TIMESTAMPTZ,
  closed_at TIMESTAMPTZ,
  close_evidence TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_diagnosis_sessions_tenant_status
  ON diagnosis_sessions(tenant_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_diagnosis_findings_session
  ON diagnosis_findings(session_id, reason_category);
CREATE INDEX IF NOT EXISTS idx_diagnosis_findings_tenant_category
  ON diagnosis_findings(tenant_id, reason_category, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_diagnosis_reviews_finding
  ON diagnosis_reviews(finding_id);
CREATE INDEX IF NOT EXISTS idx_diagnosis_work_items_session
  ON diagnosis_work_items(session_id, status);

-- RLS
ALTER TABLE diagnosis_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE diagnosis_findings ENABLE ROW LEVEL SECURITY;
ALTER TABLE diagnosis_reviews ENABLE ROW LEVEL SECURITY;
ALTER TABLE diagnosis_work_items ENABLE ROW LEVEL SECURITY;
