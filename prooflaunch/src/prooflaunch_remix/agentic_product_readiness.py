from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .tool_execution_sandbox import validate_tool_sandbox_receipt


SCHEMA = "ProofLaunchAgenticProductReadinessAuditV1"
STATUS_VALUES = {"pass", "gap", "not_applicable"}


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _evidence(root: Path, relative: str, locator: str) -> dict[str, str]:
    path = (root / relative).resolve(strict=True)
    path.relative_to(root.resolve(strict=True))
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"readiness evidence must be a real file: {relative}")
    content = path.read_text(encoding="utf-8")
    if locator not in content:
        raise ValueError(f"readiness evidence locator is missing: {relative}::{locator}")
    return {
        "path": relative,
        "file_sha256": _file_digest(path),
        "locator": locator,
    }


def compile_agentic_product_readiness(
    project_root: str | Path,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Compile the 12-point production audit from inspectable repository evidence.

    A green local regression is deliberately insufficient to turn unmeasured
    production properties into passes. Missing sandboxing, deployed guardrail
    telemetry, real human judge calibration, and deployment CI remain explicit gaps.
    """

    root = Path(project_root).resolve(strict=True)
    lifecycle = json.loads(
        (root / "evidence/v10/gtm-lifecycle-closure-matrix-v1.json").read_text(
            encoding="utf-8"
        )
    )
    if not (
        lifecycle.get("named_failure_mode_count", 0) >= 5
        and lifecycle.get("minimum_cases_per_failure_mode", 0) >= 50
    ):
        raise ValueError("named GTM failure-mode eval coverage is insufficient")

    judge_queue_relative = "evidence/v10/local-judge-calibration-queue-status.json"
    judge_queue = json.loads((root / judge_queue_relative).read_text(encoding="utf-8"))
    judge_unsigned = dict(judge_queue)
    judge_digest = judge_unsigned.pop("content_sha256", None)
    if not (
        judge_queue.get("schema") == "ProofLaunchLocalGovernanceJudgeQueueV1"
        and judge_digest == _digest(judge_unsigned)
        and judge_queue.get("observed_model_call_count") == 100
        and judge_queue.get("judge_prediction_positive_count", 0) >= 40
        and judge_queue.get("judge_prediction_negative_count", 0) >= 40
        and judge_queue.get("expected_human_label_count") == 300
        and judge_queue.get("real_human_label_count") == 0
        and judge_queue.get("judge_calibrated") is False
    ):
        raise ValueError("local judge calibration queue evidence is invalid")

    sandbox_relative = "evidence/v10/tool-execution-sandbox-v1.json"
    sandbox_path = root / sandbox_relative
    sandbox_passed = False
    if sandbox_path.is_file():
        sandbox_receipt = json.loads(sandbox_path.read_text(encoding="utf-8"))
        validate_tool_sandbox_receipt(sandbox_receipt)
        sandbox_passed = True

    items: list[dict[str, Any]] = [
        {
            "id": "PR-01",
            "name": "Typical context utilization stays below measured thresholds",
            "status": "pass",
            "evidence": [
                _evidence(
                    root,
                    "evidence/v10/gtm-context-quality-v1.json",
                    '"context_utilization_gate_passed": true',
                )
            ],
            "finding": "Twenty-four observed frozen local creative calls seal exact prompt-token usage: median 2.80% and p95 2.91% of the 32,768-token model context. This pass is bounded to that route.",
            "closure": None,
        },
        {
            "id": "PR-02",
            "name": "Run state is externalized and recoverable",
            "status": "pass",
            "evidence": [
                _evidence(
                    root,
                    "tests/test_v10_submission_runtime.py",
                    "test_store_and_worker_restart_resume_prepared_and_queued_release",
                ),
                _evidence(
                    root,
                    "src/prooflaunch_remix/v10_submission_store.py",
                    "CREATE TABLE IF NOT EXISTS events",
                ),
            ],
            "finding": "SQLite state, leased jobs, artifacts, approvals, and hash-chained events survive worker/store restart.",
            "closure": None,
        },
        {
            "id": "PR-03",
            "name": "Long-session compaction preserves critical GTM state",
            "status": "pass",
            "evidence": [
                _evidence(
                    root,
                    "evidence/v10/gtm-context-quality-v1.json",
                    '"long_session_compaction_gate_passed": true',
                )
            ],
            "finding": "Twenty-four frozen 60-message replays preserve the canonical claim, rights, budget, audience, and approval state while excluding archived injection and contact canaries.",
            "closure": None,
        },
        {
            "id": "PR-04",
            "name": "Consequential actions require explicit human approval",
            "status": "pass",
            "evidence": [
                _evidence(
                    root,
                    "tests/test_v10_submission_runtime.py",
                    "test_real_png_cas_prepare_stops_at_preview_without_bundle_then_releases",
                ),
                _evidence(
                    root,
                    "src/prooflaunch_remix/v10_submission_runtime.py",
                    "authenticated_approver",
                ),
            ],
            "finding": "Release pauses at a content-bound preview; approval records actor, decision, reason, and immutable event evidence.",
            "closure": None,
        },
        {
            "id": "PR-05",
            "name": "Permissions and tenant boundaries are enforced below the model",
            "status": "pass",
            "evidence": [
                _evidence(
                    root,
                    "tests/test_v10_submission_production_api.py",
                    "test_tenant_principal_blocks_run_artifact_memory_cache_and_injection_bleed",
                ),
                _evidence(
                    root,
                    "src/prooflaunch_remix/v10_submission_store.py",
                    "event tenant_id disagrees with the run tenant",
                ),
            ],
            "finding": "Authenticated tenant identity scopes runs, artifacts, memory, caches, events, and jobs; model-supplied tenant drift fails closed.",
            "closure": None,
        },
        {
            "id": "PR-06",
            "name": "Tool execution is isolated from the host and network",
            "status": "pass" if sandbox_passed else "gap",
            "evidence": (
                [
                    _evidence(root, sandbox_relative, '"passed": true'),
                    _evidence(
                        root,
                        "scripts/run_tool_sandbox_proof.py",
                        '"--network", "none"',
                    ),
                    _evidence(
                        root,
                        "src/prooflaunch_remix/tool_execution_sandbox.py",
                        '"persisted_in_receipt": False',
                    ),
                ]
                if sandbox_passed
                else [
                    _evidence(
                        root,
                        "docs/product/GTM_TENANT_ISOLATION_V1.md",
                        "single-node",
                    )
                ]
            ),
            "finding": (
                "An observed Docker job ran as non-root with no network, read-only root, all capabilities dropped, no-new-privileges, CPU/memory/PID limits, one writable workspace, and read-only code/secret mounts. Behavioral probes blocked root and parent-directory writes, DNS and direct TCP egress; the tool-boundary secret entered neither environment, job context, nor receipt. This pass is bounded to the reviewed adapter."
                if sandbox_passed
                else "The local prototype scopes files and same-origin requests, but the production worker is not proven inside an isolated container/VM with an enforced outbound allowlist."
            ),
            "closure": (
                None
                if sandbox_passed
                else "Run workers in a locked container/VM, inject secrets only at tool boundaries, and prove denied egress and filesystem escape."
            ),
        },
        {
            "id": "PR-07",
            "name": "Durable pause, resume, retry, and lease recovery work",
            "status": "pass",
            "evidence": [
                _evidence(
                    root,
                    "tests/test_v10_submission_store.py",
                    "test_expired_lease_can_be_reclaimed_and_stale_worker_cannot_finish",
                ),
                _evidence(
                    root,
                    "tests/test_v10_submission_runtime.py",
                    "test_store_and_worker_restart_resume_prepared_and_queued_release",
                ),
            ],
            "finding": "Leases prevent duplicate work, stale workers cannot commit, and a restarted worker resumes the human-wait/release path.",
            "closure": None,
        },
        {
            "id": "PR-08",
            "name": "Structured outputs and critical transitions validate by schema",
            "status": "pass",
            "evidence": [
                _evidence(
                    root,
                    "tests/test_v10_submission_runtime.py",
                    "test_strategy_artifact_tampering_fails_before_recording_human_release",
                ),
                _evidence(
                    root,
                    "tests/test_v10_submission_runtime.py",
                    "test_campaign_workspace_tampering_fails_preview_and_human_release",
                ),
            ],
            "finding": "Typed contracts and content hashes reject malformed or tampered strategy/workspace artifacts before release.",
            "closure": None,
        },
        {
            "id": "PR-09",
            "name": "Input and output guardrails run on representative traffic",
            "status": "gap",
            "evidence": [
                _evidence(
                    root,
                    "evidence/v10/production-guardrail-eval-v1.json",
                    '"guardrail_gate_passed": true',
                ),
                _evidence(
                    root,
                    "tests/test_v10_submission_production_api.py",
                    "test_api_guardrail_blocks_injection_and_exposes_content_free_metrics",
                ),
                _evidence(
                    root,
                    "src/prooflaunch_remix/production_guardrails.py",
                    "raw_content_retained",
                ),
            ],
            "finding": "A versioned 250-case suite records 100% synthetic attack recall, zero synthetic false blocks, and a wired HTTP input/output ledger with no raw-content retention. Deployed real-traffic hit, false-block, and escape rates remain unobserved.",
            "closure": "Deploy the instrumented boundary, review sampled false blocks with humans, and seal real-traffic hit and escape metrics before production promotion.",
        },
        {
            "id": "PR-10",
            "name": "Top failure modes each have at least 50 representative eval cases",
            "status": "pass",
            "evidence": [
                _evidence(
                    root,
                    "evidence/v10/gtm-lifecycle-closure-matrix-v1.json",
                    '"named_failure_mode_count": 5',
                )
            ],
            "finding": f"Five named GTM failure modes have at least {lifecycle['minimum_cases_per_failure_mode']} synthetic representative cases each; this is regression evidence, not production effect.",
            "closure": None,
        },
        {
            "id": "PR-11",
            "name": "LLM judges are calibrated against at least 100 human labels",
            "status": "gap",
            "evidence": [
                _evidence(
                    root,
                    "docs/product/GTM_HUMAN_JUDGE_CALIBRATION_V1.md",
                    "Both must be strictly greater than 0.80",
                ),
                _evidence(
                    root,
                    "src/prooflaunch_remix/gtm_judge_calibration.py",
                    "judge calibration requires between 100 and 500 distinct cases",
                ),
                _evidence(
                    root,
                    "tests/test_gtm_judge_calibration.py",
                    "test_exact_point_eight_tpr_is_not_calibrated",
                ),
                _evidence(
                    root,
                    "tests/test_v10_submission_ui.py",
                    "Submit immutable calibration label",
                ),
                _evidence(
                    root,
                    judge_queue_relative,
                    '"observed_model_call_count": 100',
                ),
            ],
            "finding": "A real digest-pinned localhost model has produced 100 independent, balanced predictions; the production protocol froze the matching 100-case/300-label blinded queue with three of five reviewers per case, and the same-origin review console now collects token-bound immutable PASS/FAIL labels without exposing model predictions or other labels. The queue still has zero qualifying human calibration labels, so no TPR/TNR or judge-calibration claim exists.",
            "closure": "Recruit five independent named humans, complete all 300 labels for the first 100-case frozen queue, adjudicate disagreements, and retain the signed aggregate before permitting judge-based promotion.",
        },
        {
            "id": "PR-12",
            "name": "CI blocks regressions and production traces have retention",
            "status": "gap",
            "evidence": [
                _evidence(
                    root,
                    "tests/test_v10_submission_store.py",
                    "test_append_event_is_concurrently_sequenced_and_hash_chained",
                ),
                _evidence(
                    root,
                    "scripts/compile_aug3_product_readiness.py",
                    '"product_critical_regression": tests',
                ),
                _evidence(
                    root,
                    ".github/workflows/quality.yml",
                    "retention-days: 30",
                ),
                _evidence(
                    root,
                    "evidence/v10/production-trace-retention-v1.json",
                    '"retention_days": 90',
                ),
                _evidence(
                    root,
                    "tests/test_v10_submission_production_api.py",
                    "test_every_valid_http_request_emits_content_free_retained_trace",
                ),
            ],
            "finding": "A pull-request/push CI workflow runs the full Python suite, control-plane eval, trace-retention smoke proof, readiness audit and web build while retaining CI evidence for 30 days. Every valid request handled by the reviewed HTTP boundary now emits a content-free, tenant-hashed, restart-verifiable trace under a 90-day contract. Remote required-check enforcement and 100% deployed production trace retention remain unobserved.",
            "closure": "Enable the workflow as a protected required check, capture a successful remote run, deploy the instrumented HTTP boundary, and verify its trace count against 100% of load-balancer requests across the 90-day retention window.",
        },
    ]
    passed = sum(item["status"] == "pass" for item in items)
    gaps = sum(item["status"] == "gap" for item in items)
    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "generated_at": generated_at
        or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "audit_item_count": len(items),
        "passed_item_count": passed,
        "gap_item_count": gaps,
        "not_applicable_item_count": len(items) - passed - gaps,
        "launch_decision": "local_governed_demo_ready_enterprise_production_not_ready",
        "items": items,
        "truth_boundary": (
            f"This audit proves {passed} repository-level production controls and identifies {gaps} explicit gaps. "
            "It does not prove 4A preference, Top-1 standing, Radeon execution, external publication, "
            "causal lift, revenue, enterprise isolation, or production readiness."
        ),
    }
    receipt["content_sha256"] = _digest(receipt)
    validate_agentic_product_readiness(receipt, root)
    return receipt


def validate_agentic_product_readiness(
    receipt: Mapping[str, Any], project_root: str | Path
) -> None:
    root = Path(project_root).resolve(strict=True)
    if receipt.get("schema") != SCHEMA:
        raise ValueError("agentic readiness schema is invalid")
    unsigned = dict(receipt)
    supplied = unsigned.pop("content_sha256", None)
    if supplied != _digest(unsigned):
        raise ValueError("agentic readiness content digest is invalid")
    items = receipt.get("items")
    if not isinstance(items, list) or len(items) != 12:
        raise ValueError("agentic readiness must contain exactly 12 items")
    ids = [item.get("id") for item in items if isinstance(item, Mapping)]
    if ids != [f"PR-{index:02d}" for index in range(1, 13)]:
        raise ValueError("agentic readiness item identities are invalid")
    statuses = [item.get("status") for item in items]
    if any(status not in STATUS_VALUES for status in statuses):
        raise ValueError("agentic readiness item status is invalid")
    if receipt.get("passed_item_count") != statuses.count("pass"):
        raise ValueError("agentic readiness pass count drifted")
    if receipt.get("gap_item_count") != statuses.count("gap"):
        raise ValueError("agentic readiness gap count drifted")
    for item in items:
        evidence = item.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            raise ValueError("every readiness item requires evidence")
        for record in evidence:
            path = (root / str(record.get("path") or "")).resolve(strict=True)
            path.relative_to(root)
            if path.is_symlink() or not path.is_file():
                raise ValueError("readiness evidence path is invalid")
            if record.get("file_sha256") != _file_digest(path):
                raise ValueError("readiness evidence digest drifted")
            if str(record.get("locator") or "") not in path.read_text(encoding="utf-8"):
                raise ValueError("readiness evidence locator drifted")


__all__ = [
    "SCHEMA",
    "compile_agentic_product_readiness",
    "validate_agentic_product_readiness",
]
