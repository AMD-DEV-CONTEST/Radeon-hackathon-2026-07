-- Quality loop hardening. Existing governance tables are created in migration-018.
-- Keep one evaluation per report and rule version so retries cannot create duplicate
-- findings or work items for the same QA decision.
CREATE UNIQUE INDEX IF NOT EXISTS idx_evaluations_report_rule
  ON evaluations(tenant_id, subject_type, subject_id, rule_version);

CREATE INDEX IF NOT EXISTS idx_findings_evaluation_status
  ON findings(evaluation_id, review_status);

CREATE INDEX IF NOT EXISTS idx_approvals_subject_decision
  ON approvals(tenant_id, subject_type, subject_id, decision);
