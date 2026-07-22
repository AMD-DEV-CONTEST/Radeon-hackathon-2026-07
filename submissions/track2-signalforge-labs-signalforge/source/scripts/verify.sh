#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

# Workspace tests exercise the production static bundle. Build it before Go tests so a clean clone
# never inherits an untracked local web/dist directory as an accidental prerequisite.
(cd web && npm ci --no-audit --no-fund && npm run test && npm run build)

go test -race -count=1 ./...
go vet ./...
go test ./internal/casestore ./internal/permissions ./internal/resilience ./internal/workspace -count=1
python3 scripts/reference_finance.py
python3 -m unittest discover -s scripts/tests -p 'test_*.py'
python3 -m py_compile scripts/build_project_spec.py scripts/run_hardening_matrix.py
python3 scripts/run_hardening_matrix.py --check
jq -e '
  .schema_version == "signalforge/hardening-report/v1" and
  .matrix_id == "sprint12-adversarial-v1" and
  .status == "passed" and
  .cases == 26 and
  .severity_counts.critical == 22 and
  .severity_counts.high == 4 and
  .release_blockers == 0 and
  (.gates | length) == 11 and
  all(.gates[]; .status == "passed" and (.source_hashes | length) > 0)
' evidence/hardening-matrix.json >/dev/null
while IFS= read -r -d '' json_file; do
  jq empty "$json_file"
done < <(find contracts evidence fixtures configs -type f -name '*.json' -print0)

bash -n scripts/serve_llama_rocm.sh scripts/run_radeon_profile.sh scripts/verify_clean_startup.sh
python3 scripts/build_radeon_optimization_report.py --check
python3 scripts/render_radeon_optimization.py \
  --output "$tmp_dir/radeon-optimization.svg"
cmp evidence/radeon-optimization.svg "$tmp_dir/radeon-optimization.svg"

jq -e '
  .schema_version == "signalforge/radeon-optimization-decision/v1" and
  .accepted_improvements.launcher_contract_success_before == 0.875 and
  .accepted_improvements.launcher_contract_success_after == 1 and
  .accepted_improvements.long_context_capacity_before_tokens_per_slot == 8192 and
  .accepted_improvements.long_context_capacity_after_tokens_per_request == 32768 and
  .accepted_improvements.selected_vs_three_context_workers_end_to_end_improvement_percent >= 29 and
  .selected_configuration.flash_attention == "auto" and
  .selected_configuration.kv_cache == "unified_f16" and
  .selected_configuration.context_capacity_tokens == 32768 and
  .selected_configuration.server_slots == 4 and
  .selected_configuration.product_context_concurrency == 4 and
  .selected_configuration.continuous_batching == true and
  (.microbenchmarks | map(select(.profile_id == "baseline-unified-kv" and
    .decision == "selected_runtime" and .quality_gate.passed == true and
    .quality_gate.observations == 80)) | length) == 1 and
  (.microbenchmarks | map(select(.profile_id == "flash-on-kv-q8" and
    .decision == "rejected_quality_gate" and .quality_gate.passed == false)) | length) == 1 and
  (.golden_journeys | map(select(.profile_id == "golden-context-4-auto" and
    .decision == "selected_product_concurrency" and .run_status == "completed" and
    .semantic_passed == true and .semantic_checks_passed == 44 and
    .semantic_checks_total == 44 and .metrics.max_concurrent_context == 4)) | length) == 1 and
  (.golden_journeys | map(select(.profile_id == "golden-context-3-auto" and
    .decision == "rejected" and .semantic_passed == true and
    .semantic_checks_passed == 44)) | length) == 1 and
  (.golden_journeys | map(select(.profile_id == "golden-context-2" and
    .decision == "rejected_quality_gate" and .semantic_passed == false and
    .run_status == "failed")) | length) == 1
' evidence/radeon-optimization.json >/dev/null

go run ./cmd/signalforge-validate-replay \
  --input evidence/runs/sprint11/golden-context-4-auto/safe-replay.json

if find evidence/runs/sprint11 -type f \( -name 'private-report.json' -o -name '*.pid' \) \
  -print -quit | grep -q .; then
  echo "private Sprint 11 report or transient PID file found in public evidence" >&2
  exit 1
fi

jq -e '
  .schema_version == "signalforge/research-workspace/v1" and
  .status == "completed" and
  (.companies | length) == 2 and
  (.sections | length) == 8 and
  (.evidence | length) == 12 and
  (.calculations | length) == 18 and
  .execution.local_only == true and
  .execution.endpoint_scope == "loopback_only" and
  .metrics.evidence_coverage == 1
' fixtures/workspace/golden-case.json >/dev/null

go run ./cmd/signalforge-eval-workspace \
  --output "$tmp_dir/workspace-evaluation.json"
jq -e '
  .schema_version == "signalforge/workspace-evaluation/v1" and
  .mode == "fixture" and .local_only == true and
  .frontend.index_status == 200 and
  .frontend.index_bytes > 0 and
  .frontend.content_security_ready == true and
  .frontend.initial_case_ms < 1000 and
  .journey.start_status == 202 and
  .journey.time_to_first_progress_ms < 1000 and
  .journey.time_to_completed_case_ms < 2000 and
  .journey.streamed_events >= 21 and
  .journey.sections == 8 and
  .journey.evidence_items == 12 and
  .journey.calculation_receipts == 18 and
  .journey.private_fields_excluded == true
' "$tmp_dir/workspace-evaluation.json" >/dev/null

jq -e '
  .schema_version == "signalforge/workspace-evaluation/v1" and
  .mode == "fixture" and .local_only == true and
  .frontend.index_status == 200 and
  .frontend.content_security_ready == true and
  .frontend.initial_case_ms < 1000 and
  .journey.time_to_first_progress_ms < 1000 and
  .journey.time_to_completed_case_ms < 2000 and
  .journey.streamed_events >= 21 and
  .journey.sections == 8 and
  .journey.evidence_items == 12 and
  .journey.calculation_receipts == 18 and
  .journey.private_fields_excluded == true
' evidence/workspace-evaluation.json >/dev/null

go run ./cmd/signalforge-validate-replay \
  --input evidence/golden-safe-decision-replay.json
jq -e '
  .schema_version == "signalforge/safe-decision-replay/v1" and
  .status == "completed" and
  .local_only == true and
  .runtime.attested == true and
  .runtime.gpu_architecture == "gfx1100" and
  .runtime.rocm_version == "7.2.1" and
  .runtime.runtime == "llama.cpp" and
  .privacy.prompt_bodies_excluded == true and
  .privacy.response_bodies_excluded == true and
  .privacy.chain_of_thought_excluded == true and
  .privacy.failure_messages_excluded == true and
  (.failures | length) == 0 and
  .metrics.evidence_coverage == 1 and
  .metrics.released_claims > 0 and
  (.route_decisions | length) == 9 and
  ([.claim_dispositions[] | select(
    .origin == "source_extraction" and
    .disposition == "released" and
    (.approved_by | contains(["evidence-critic/v1", "risk-contrarian/v1"])) and
    (.released_sections | contains(["counterevidence", "invalidation_conditions"]))
  )] | length) >= 1
' evidence/golden-safe-decision-replay.json >/dev/null

go test ./internal/localagent \
  -run '^TestUnifiedFakeProviderChaosSuite$' -count=1
go test ./internal/orchestrator \
  -run '^TestRuntimeExecutesThreeGovernedFollowUpsWithScopeAndEvidenceLineage$' -count=1
replay_file_sha="$(sha256sum evidence/golden-safe-decision-replay.json | awk '{print $1}')"
semantic_evaluation_sha="$(sha256sum evidence/golden-semantic-evaluation.json | awk '{print $1}')"
semantic_rubric_sha="$(sha256sum fixtures/golden/semantic-rubric-v5.json | awk '{print $1}')"
jq -e \
  --arg replay_file_sha "$replay_file_sha" \
  --arg semantic_evaluation_sha "$semantic_evaluation_sha" \
  --arg semantic_rubric_sha "$semantic_rubric_sha" \
  --slurpfile replay evidence/golden-safe-decision-replay.json \
  --slurpfile semantic_eval evidence/golden-semantic-evaluation.json '
  .schema_version == "signalforge/golden-journey-scorecard/v1" and
  .source_replay.sha256 == $replay_file_sha and
  .source_replay.replay_id == $replay[0].replay_id and
  .source_replay.run_id == $replay[0].run_id and
  .runtime.local_only == $replay[0].local_only and
  .runtime.attested == $replay[0].runtime.attested and
  .runtime.gpu_architecture == $replay[0].runtime.gpu_architecture and
  .runtime.rocm_version == $replay[0].runtime.rocm_version and
  .quality.claims_supplied == ($replay[0].claim_dispositions | length) and
  .quality.claims_dispositioned == ($replay[0].claim_dispositions | length) and
  .quality.released_claims == $replay[0].metrics.released_claims and
  .quality.released_claims_with_authority == ([
    $replay[0].claim_dispositions[] | select(
      .disposition == "released" and
      (((.evidence_refs // []) | length) + ((.receipt_refs // []) | length) +
       ((.numerical_refs // []) | length) + ((.assumption_refs // []) | length) > 0)
    )
  ] | length) and
  .quality.released_claims_approved_by_both_reviewers == ([
    $replay[0].claim_dispositions[] | select(
      .disposition == "released" and
      (.approved_by | contains(["evidence-critic/v1", "risk-contrarian/v1"]))
    )
  ] | length) and
  .quality.evidence_coverage == $replay[0].metrics.evidence_coverage and
  .quality.external_answer_accuracy == "not_scored_against_external_ground_truth" and
  .quality.frozen_semantic_rubric.rubric_id == $semantic_eval[0].rubric_id and
  .quality.frozen_semantic_rubric.rubric_sha256 == $semantic_rubric_sha and
  .quality.frozen_semantic_rubric.evaluation_sha256 == $semantic_evaluation_sha and
  .quality.frozen_semantic_rubric.passed == true and
  .quality.frozen_semantic_rubric.passed_checks == 44 and
  .quality.frozen_semantic_rubric.total_checks == 44 and
  $semantic_eval[0].report_run_id == $replay[0].run_id and
  $semantic_eval[0].rubric_sha256 == $semantic_rubric_sha and
  $semantic_eval[0].passed == true and
  $semantic_eval[0].passed_checks == 44 and
  $semantic_eval[0].total_checks == 44 and
  .resilience.cases == 6 and .resilience.passed == 6 and
  .follow_up_continuity.cases == 3 and .follow_up_continuity.passed == 3 and
  .performance.end_to_end_duration_ms == $replay[0].metrics.end_to_end_duration_ms and
  .performance.model_calls == $replay[0].metrics.model_calls and
  .performance.ttft_p50_ms == $replay[0].metrics.ttft_p50_ms and
  .performance.ttft_p95_ms == $replay[0].metrics.ttft_p95_ms and
  .performance.completion_tokens_per_second == $replay[0].metrics.completion_tokens_per_second and
  .performance.max_concurrent_context == $replay[0].metrics.max_concurrent_context and
  .limitations.point_in_time_market_prices == "available_from_frozen_official_exchange_close_inputs" and
  .limitations.price_implied_multiples == "available_with_two_validated_peer_multiple_receipts" and
  .limitations.complete_sprint_08 == true
' evidence/golden-journey-scorecard.json >/dev/null

go run ./cmd/signalforge-calculate \
  --request fixtures/engine/margin-request.json \
  --output "$tmp_dir/calculation-result.json" \
  --receipt-store "$tmp_dir/receipts" \
  --code-commit verification-tree
jq -e '.receipt.status == "success" and .receipt.outputs[0].quantity.value == "0.25"' \
  "$tmp_dir/calculation-result.json" >/dev/null

go run ./cmd/signalforge-eval-architecture > "$tmp_dir/architecture-eval.json"
cmp evidence/architecture-eval.json "$tmp_dir/architecture-eval.json"

go run ./cmd/signalforge-eval-orchestration > "$tmp_dir/orchestration-eval.json"
cmp evidence/orchestration-eval.json "$tmp_dir/orchestration-eval.json"

go run ./cmd/signalforge-export-prompts > "$tmp_dir/role-prompts-v12.json"
cmp configs/prompts/role-prompts-v12.json "$tmp_dir/role-prompts-v12.json"

heldout_suite="fixtures/roles/held-out-v5-cases.json"
heldout_report="evidence/role-eval-gemma4-26b-q4-heldout-v2.json"
heldout_sha="$(sha256sum "$heldout_suite" | awk '{print $1}')"
jq -e --arg suite_sha "$heldout_sha" '
  .schema_version == "signalforge/role-evaluation-report/v1" and
  .suite_id == "role-held-out-v2" and
  .suite_sha256 == $suite_sha and
  .prompt_set_version == "signalforge-role-prompts/v5" and
  .model_id == "signalforge-gemma4-26b-q4" and
  .cases == 33 and
  .passed == 29 and
  .pass_rate >= 0.87 and
  .total_prompt_tokens > 0 and
  .total_completion_tokens > 0 and
  (.roles | length) == 11 and
  (all(.roles[]; .cases == 3 and .passed >= 1)) and
  ([.observations[] | select(.success == false)] | length) == 4
' "$heldout_report" >/dev/null

jq -e '
  .schema_version == "signalforge/role-evaluation-suite/v1" and
  .suite_id == "role-held-out-v2" and
  .prompt_set_version == "signalforge-role-prompts/v8" and
  (.cases | length) == 33
' fixtures/roles/held-out-cases.json >/dev/null

jq -e '
  .schema_version == "signalforge/role-evaluation-suite/v1" and
  .suite_id == "role-held-out-v2" and
  .prompt_set_version == "signalforge-role-prompts/v12" and
  (.cases | length) == 33
' fixtures/roles/held-out-v12-cases.json >/dev/null

current_suite_sha="$(sha256sum fixtures/roles/held-out-cases.json | awk '{print $1}')"
jq -e --arg suite_sha "$current_suite_sha" '
  .schema_version == "signalforge/role-evaluation-report/v1" and
  .suite_id == "role-held-out-v2" and
  .suite_sha256 == $suite_sha and
  .prompt_set_version == "signalforge-role-prompts/v8" and
  .model_id == "signalforge-gemma4-26b-q4" and
  .cases == 33 and
  .passed == 26 and
  ([.observations[] | select(.success == false)] | length) == 7
' evidence/role-eval-gemma4-26b-q4-heldout-v8-migration.json >/dev/null

jq -e '
  .schema_version == "signalforge/local-orchestration-evaluation/v1" and
  .model_id == "signalforge-gemma4-26b-q4" and
  .result.failure == null and
  .result.answer != null and
  (.result.answer.sections | map(.section_type) |
    contains(["business_overview", "evidence", "limitations"])) and
  (.result.trace.events | length) == 7 and
  ([.result.trace.events[] | select(.status == "failed")] | length) == 0 and
  .result.trace.max_concurrent_context == 1 and
  (.calls | map(.role_id)) == [
    "business-strategy/v1",
    "evidence-critic/v1",
    "final-research-analyst/v1"
  ] and
  (all(.calls[]; .error == null and .duration_ms > 0 and .duration_ms < 30000))
' evidence/local-orchestration-gemma4-26b-q4.json >/dev/null

for historical_report in evidence/role-eval-gemma4-26b-q4-prompt-v{1,2,3,4}.json; do
  jq -e '.schema_version == "signalforge/role-evaluation-report/v1"' \
    "$historical_report" >/dev/null
done

go run ./cmd/signalforge-eval-retrieval \
  --eval fixtures/retrieval/golden-eval.json \
  --vectors fixtures/retrieval/vectors/granite-embedding-97m-multilingual-r2.json \
  --output "$tmp_dir/retrieval-eval.json"
jq -e '
  (.methods[] | select(.method == "bm25/v1") | .metrics.complete_evidence_rate) == 1 and
  (.methods[] | select(.method == "cosine/v1") | .metrics.recall_at_k) >= 0.84 and
  ([.methods[].metrics.citation_correctness] | min) == 1
' "$tmp_dir/retrieval-eval.json" >/dev/null

go run ./cmd/signalforge-release-check \
  --root . \
  --claims evidence/public-claims.json

python3 scripts/audit_public_repo.py --check

go run ./cmd/signalforge-evidence \
  --repo . \
  --output "$tmp_dir/manifest.json" \
  --artifact evidence/architecture-eval.json \
  --artifact evidence/public-claims.json \
  --artifact fixtures/tier0-golden-cases.json

go run ./cmd/signalforge-evidence \
  --repo . \
  --check "$tmp_dir/manifest.json"

git diff --check
echo "SignalForge verification passed"
