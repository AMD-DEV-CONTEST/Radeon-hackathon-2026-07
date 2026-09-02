#!/usr/bin/env bash
set -euo pipefail

# Deterministic fresh-project deployment. Run from the repository root after
# `supabase link --project-ref <new-project-ref>` and `supabase login`.
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

command -v supabase >/dev/null 2>&1 || {
  echo "supabase CLI is required" >&2
  exit 1
}

if ! supabase projects list --output json >/dev/null 2>&1; then
  echo "Supabase CLI is not logged in; run: supabase login" >&2
  exit 1
fi

run_sql() {
  local file="$1"
  echo "[supabase] applying ${file}"
  supabase db query --linked --file "$ROOT_DIR/$file"
}

# schema.sql is the only base schema file. Published 011 and 016 are skipped:
# their replacements below fix the UUID FK and PostgreSQL 17 tsvector issues.
FULL_FILES=(
  supabase/schema.sql
  supabase/migration-003-ecommerce-ops.sql
  supabase/migration-rag-shadow.sql
  supabase/migration-004-industry-benchmarks.sql
  supabase/migration-004-rbac-audit.sql
  supabase/migration-005-correction-samples.sql
  supabase/migrations/005_add_pipeline_submissions.sql
  supabase/migrations/006_add_pipeline_jobs.sql
  supabase/migrations/007_add_feishu_raw_events.sql
  supabase/migration-008-state-machine-compat.sql
  supabase/migration-006-knowledge-loop.sql
  supabase/migration-007-effect-tracking.sql
  supabase/migration-008-knowledge-effect-tracking.sql
  supabase/migration-009-compliance.sql
  supabase/migration-010-system-config.sql
  supabase/migration-011-intent-accuracy.sql
  supabase/migration-011-platform-credentials-compat.sql
  supabase/migration-012-shadow-replies.sql
  supabase/migration-012-work-orders.sql
  supabase/migration-013-payment-reminders.sql
  supabase/migration-013-real-replies.sql
  supabase/migration-014-production-deploy.sql
  supabase/migrations/012_bot_commands.sql
  supabase/migration-013-personality-engine-compat.sql
  supabase/migrations/014_prompt_bot_model_knowledge.sql
  supabase/migrations/015_add_prompt_activation.sql
  supabase/migrations/011_performance_indexes.sql
  supabase/migration-015-unresolved-questions.sql
  supabase/migration-016-hybrid-search-compat.sql
  supabase/migration-017-unresolved-fts.sql
  supabase/migration-018-governance-foundation.sql
  supabase/migration-019-reply-quality-loop.sql
  supabase/migration-020-llm-call-logs.sql
  supabase/migration-021-cron-idempotency.sql
  supabase/migration-022-tenant-foundation.sql
  supabase/migration-023-quality-loop-hardening.sql
  supabase/migration-024-evidence-event-contract.sql
  supabase/migration-025-commerce-metrics-lineage.sql
  supabase/migration-026-ai-evaluation-gate.sql
  supabase/migration-027-diagnosis.sql
  supabase/migration-028-feedback-release-manifests.sql
  supabase/migrations/016_release_evidence_dora.sql
  supabase/migration-029-tenant-rls-hardening.sql
  supabase/migration-030-tenant-rls-verification.sql
  supabase/migration-031-tenant-rls-force.sql
)

# Existing projects may already contain the historical non-idempotent policies.
# Reconcile them with forward-only, idempotent files instead of re-running old
# CREATE POLICY statements. This also makes a partially completed deployment
# recoverable after the first failed step.
RECONCILE_FILES=(
  supabase/migration-rag-shadow.sql
  supabase/migrations/005_add_pipeline_submissions.sql
  supabase/migrations/006_add_pipeline_jobs.sql
  supabase/migrations/007_add_feishu_raw_events.sql
  supabase/migration-008-state-machine-compat.sql
  supabase/migrations/012_bot_commands.sql
  supabase/migration-013-personality-engine-compat.sql
  supabase/migrations/016_release_evidence_dora.sql
  supabase/migration-011-platform-credentials-compat.sql
  supabase/migration-016-hybrid-search-compat.sql
  supabase/migration-029-tenant-rls-hardening.sql
  supabase/migration-030-tenant-rls-verification.sql
  supabase/migration-031-tenant-rls-force.sql
)

DEPLOYMENT_MODE="full initialization"
if supabase db query --linked "SELECT to_regclass('public.profiles') IS NOT NULL AS exists;" 2>/dev/null | grep -q '"exists": true'; then
  FILES=("${RECONCILE_FILES[@]}")
  DEPLOYMENT_MODE="forward-only reconciliation"
  echo "[supabase] existing project detected; running forward-only reconciliation"
else
  FILES=("${FULL_FILES[@]}")
  echo "[supabase] empty project detected; running full initialization"
fi

for file in "${FILES[@]}"; do
  [[ -f "$ROOT_DIR/$file" ]] || {
    echo "missing migration: $file" >&2
    exit 1
  }
  run_sql "$file"
done

echo "Supabase ${DEPLOYMENT_MODE} completed."
