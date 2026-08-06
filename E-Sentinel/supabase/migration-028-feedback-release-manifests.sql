-- Contest feedback lifecycle and immutable release manifests. Additive only.
CREATE TABLE IF NOT EXISTS feedback_records (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id TEXT NOT NULL,
  source_trace_id TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('captured','triaged','accepted','rejected','change_drafted','regression_running','approved','released','verified')),
  reason_code TEXT CHECK (reason_code IN ('RULE_MISSING','RULE_CONFLICT','RETRIEVAL_MISS','PROMPT_DEFECT','MODEL_JUDGMENT_ERROR','EVIDENCE_EXTRACTION_ERROR','LABEL_DISPUTE','DATA_QUALITY')),
  rejection_reason TEXT,
  owner_id UUID REFERENCES profiles(id),
  linked_dataset_items TEXT[] NOT NULL DEFAULT '{}',
  regression_passed BOOLEAN NOT NULL DEFAULT false,
  approved_by UUID REFERENCES profiles(id),
  release_id TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK ((status <> 'rejected') OR rejection_reason IS NOT NULL),
  CHECK ((status NOT IN ('approved','released','verified')) OR (regression_passed AND cardinality(linked_dataset_items) > 0)),
  CHECK ((status NOT IN ('released','verified')) OR approved_by IS NOT NULL),
  CHECK ((status <> 'verified') OR release_id IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS release_manifests (
  release_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  commit_sha TEXT NOT NULL,
  deployment_id TEXT NOT NULL,
  model TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  rule_set_version TEXT NOT NULL,
  dataset_version TEXT NOT NULL,
  schema_version TEXT NOT NULL,
  evaluation_report TEXT NOT NULL,
  regression_passed BOOLEAN NOT NULL CHECK (regression_passed),
  approved_by UUID REFERENCES profiles(id),
  released_at TIMESTAMPTZ NOT NULL,
  integrity_hash TEXT NOT NULL UNIQUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE feedback_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE release_manifests ENABLE ROW LEVEL SECURITY;
CREATE INDEX IF NOT EXISTS idx_feedback_records_tenant_status ON feedback_records(tenant_id, status, updated_at DESC);

CREATE TABLE IF NOT EXISTS feedback_transition_history (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  feedback_id UUID NOT NULL REFERENCES feedback_records(id) ON DELETE CASCADE,
  from_status TEXT,
  to_status TEXT NOT NULL,
  actor_id UUID REFERENCES profiles(id),
  occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION enforce_feedback_transition()
RETURNS TRIGGER AS $$
BEGIN
  IF NEW.status <> OLD.status AND NOT (
    (OLD.status = 'captured' AND NEW.status = 'triaged') OR
    (OLD.status = 'triaged' AND NEW.status IN ('accepted', 'rejected')) OR
    (OLD.status = 'accepted' AND NEW.status = 'change_drafted') OR
    (OLD.status = 'change_drafted' AND NEW.status = 'regression_running') OR
    (OLD.status = 'regression_running' AND NEW.status = 'approved') OR
    (OLD.status = 'approved' AND NEW.status = 'released') OR
    (OLD.status = 'released' AND NEW.status = 'verified')
  ) THEN
    RAISE EXCEPTION 'invalid feedback transition: % -> %', OLD.status, NEW.status;
  END IF;
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION record_feedback_transition()
RETURNS TRIGGER AS $$
BEGIN
  IF NEW.status <> OLD.status THEN
    INSERT INTO feedback_transition_history (feedback_id, from_status, to_status, actor_id)
    VALUES (NEW.id, OLD.status, NEW.status, NEW.owner_id);
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS feedback_transition_guard ON feedback_records;
CREATE TRIGGER feedback_transition_guard BEFORE UPDATE ON feedback_records
  FOR EACH ROW EXECUTE FUNCTION enforce_feedback_transition();
DROP TRIGGER IF EXISTS feedback_transition_audit ON feedback_records;
CREATE TRIGGER feedback_transition_audit AFTER UPDATE ON feedback_records
  FOR EACH ROW EXECUTE FUNCTION record_feedback_transition();

CREATE OR REPLACE FUNCTION reject_release_manifest_mutation()
RETURNS TRIGGER AS $$
BEGIN
  RAISE EXCEPTION 'release manifests are immutable; create a new manifest instead';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS release_manifest_immutable ON release_manifests;
CREATE TRIGGER release_manifest_immutable BEFORE UPDATE OR DELETE ON release_manifests
  FOR EACH ROW EXECUTE FUNCTION reject_release_manifest_mutation();
