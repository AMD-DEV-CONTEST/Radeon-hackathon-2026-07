#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_text_challenger_runner import (
    execute_text_challenger_plan,
    write_text_challenger_bundle,
)
from prooflaunch_remix.inference_gateway import OllamaLocalClient, OllamaLocalSpec
from prooflaunch_remix.inference_gateway import (
    InferenceGatewayCallError,
    InferenceScope,
)
from prooflaunch_remix.v10_submission_runtime import (
    AgencyRunWorker,
    ProductionAgencyService,
)
from prooflaunch_remix.v10_submission_store import SubmissionStore


DEFAULT_IMAGE = ROOT / "evidence/local/reference-run/fixture-product.png"
DEFAULT_MODEL_RECEIPT = ROOT / "artifacts/local-gtm-generative-baseline-v1/receipt.json"
DEFAULT_OUTPUT = ROOT / "artifacts/local-gtm-creative-benchmark-v6"
DEFAULT_STATUS = ROOT / "evidence/v10/local-gtm-creative-benchmark-status.json"


SCENARIOS: tuple[dict[str, str], ...] = (
    {
        "case_id": "b2b-pre-pmf-zero-developer-tools",
        "industry": "developer infrastructure software",
        "business_model": "b2b",
        "lifecycle": "pre_pmf",
        "budget": "zero",
        "industry_risk": "standard",
        "platform": "LinkedIn",
        "audience_name": "platform engineering leads evaluating internal developer tooling",
        "audience_problem": "fragmented build evidence makes an early tool difficult to trust",
        "audience_outcome": "inspect one reproducible workflow before agreeing to a design-partner session",
        "buying_context": "a small technical committee is comparing build-versus-buy options without an approved media budget",
        "offer": "inspect the reproducible workflow and challenge its weakest assumption",
    },
    {
        "case_id": "b2b-launch-zero-cybersecurity",
        "industry": "cybersecurity operations",
        "business_model": "b2b",
        "lifecycle": "launch",
        "budget": "zero",
        "industry_risk": "standard",
        "platform": "LinkedIn",
        "audience_name": "security operations leaders preparing a tooling review",
        "audience_problem": "vendor claims arrive before the evidence needed for internal scrutiny",
        "audience_outcome": "carry a source-bound decision card into the review meeting",
        "buying_context": "a launch-stage vendor must earn practitioner attention without paid reach or invented customer outcomes",
        "offer": "review the decision card with the buying group",
    },
    {
        "case_id": "b2b-growth-small-regulated-fintech",
        "industry": "regulated financial operations software",
        "business_model": "b2b",
        "lifecycle": "growth",
        "budget": "small",
        "industry_risk": "high_regulation",
        "platform": "Search",
        "audience_name": "financial operations and compliance leaders",
        "audience_problem": "high-intent research is crowded with unsupported automation assurances",
        "audience_outcome": "separate inspectable process evidence from claims that need specialist review",
        "buying_context": "a regulated buying group requires named specialist review before any campaign release",
        "offer": "inspect the evidence limits with the compliance reviewer",
    },
    {
        "case_id": "b2b-mature-scaled-industrial",
        "industry": "industrial supply-chain software",
        "business_model": "b2b",
        "lifecycle": "mature",
        "budget": "scaled",
        "industry_risk": "standard",
        "platform": "Partner",
        "audience_name": "supply-chain transformation directors and implementation partners",
        "audience_problem": "mature category language hides the operational conditions behind adoption",
        "audience_outcome": "reuse a defensible decision packet across regional stakeholder groups",
        "buying_context": "an established vendor needs consistent proof across partner and direct channels without automatic activation",
        "offer": "adapt the decision packet for one regional review",
    },
    {
        "case_id": "b2b-mature-small-customer-operations",
        "industry": "customer operations software",
        "business_model": "b2b",
        "lifecycle": "mature",
        "budget": "small",
        "industry_risk": "standard",
        "platform": "Customer email",
        "audience_name": "customer operations leaders reviewing an established workflow",
        "audience_problem": "routine renewal messages hide which operating condition still creates value",
        "audience_outcome": "reply with one verified condition for renewing, changing or retiring the workflow",
        "buying_context": "an established vendor must re-engage consented customers without bulk outreach or invented retention outcomes",
        "offer": "review the evidence card and reply with the one condition the next cycle must preserve",
    },
    {
        "case_id": "b2c-pre-pmf-zero-creator-education",
        "industry": "creator education",
        "business_model": "b2c",
        "lifecycle": "pre_pmf",
        "budget": "zero",
        "industry_risk": "standard",
        "platform": "Community",
        "audience_name": "independent creators testing a repeatable publishing practice",
        "audience_problem": "generic growth advice obscures which part of the workflow actually fails",
        "audience_outcome": "use a self-check before committing to a new creator tool",
        "buying_context": "an early product needs corrected problem language more than reach or polished promotion",
        "offer": "complete the self-check and challenge the problem framing",
    },
    {
        "case_id": "b2c-launch-zero-sustainable-goods",
        "industry": "sustainable consumer goods",
        "business_model": "b2c",
        "lifecycle": "launch",
        "budget": "zero",
        "industry_risk": "standard",
        "platform": "Short video",
        "audience_name": "low-waste households comparing everyday product choices",
        "audience_problem": "polished sustainability promises are difficult to inspect or recreate",
        "audience_outcome": "reproduce one practical comparison before considering the product",
        "buying_context": "a new brand must earn voluntary saves and shares without paid media or environmental overclaiming",
        "offer": "recreate the comparison and record one unresolved condition",
    },
    {
        "case_id": "b2c-growth-small-regulated-wellness",
        "industry": "regulated digital wellness",
        "business_model": "b2c",
        "lifecycle": "growth",
        "budget": "small",
        "industry_risk": "high_regulation",
        "platform": "Search",
        "audience_name": "adults evaluating a non-diagnostic wellness routine",
        "audience_problem": "search content often blurs education, diagnosis and unsupported outcome assurances",
        "audience_outcome": "inspect the evidence boundary before trying a routine",
        "buying_context": "growth content requires specialist review and must avoid medical advice or unsupported outcome assurances",
        "offer": "review the evidence boundary with a qualified specialist",
    },
    {
        "case_id": "b2c-mature-scaled-travel-membership",
        "industry": "consumer travel membership",
        "business_model": "b2c",
        "lifecycle": "mature",
        "budget": "scaled",
        "industry_risk": "standard",
        "platform": "Owned community",
        "audience_name": "frequent independent travelers planning complex trips",
        "audience_problem": "brand-led travel inspiration rarely preserves the decision context another traveler needs",
        "audience_outcome": "adapt a customer-controlled planning ritual for the next trip",
        "buying_context": "a mature membership wants reusable customer utility without fabricating consensus or automatically amplifying spend",
        "offer": "adapt the planning ritual to one upcoming trip",
    },
)


def _inside_project(raw: str) -> Path:
    resolved = Path(raw).expanduser().resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError as error:
        raise argparse.ArgumentTypeError("path must remain inside the project root") from error
    return resolved


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


_WORD = re.compile(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)?|[\u3400-\u9fff]")


def _creative_tokens(value: str) -> set[str]:
    return {
        token
        for token in _WORD.findall(value.casefold())
        if len(token) > 1
    }


def _jaccard(left: str, right: str) -> float:
    left_tokens = _creative_tokens(left)
    right_tokens = _creative_tokens(right)
    union = left_tokens | right_tokens
    return len(left_tokens & right_tokens) / len(union) if union else 1.0


def _candidate_creative_signature(candidate: Mapping[str, Any]) -> str:
    approved_proof = str(candidate["factual_claims"][0])
    strategic = [
        str(candidate[field])
        for field in (
            "cultural_tension",
            "organizing_idea",
            "participation_mechanism",
            "share_trigger",
            "proof_role",
            "falsifier",
        )
    ]
    channel_content = [
        str(part)
        for channel in candidate["channels"]
        for part in (channel["hook"], *channel["body"])
        if part != approved_proof
    ]
    return "\n".join((*strategic, *channel_content))


def _write_status(path: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    sealed = dict(payload)
    sealed["content_sha256"] = _digest(sealed)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        path,
        json.dumps(sealed, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    return sealed


def _blocked_status(
    *,
    model_name: str,
    model_digest: str,
    model_receipt_sha: str,
    error: InferenceGatewayCallError,
    output_dir: Path,
) -> dict[str, Any]:
    return {
        "schema": "ProofLaunchLocalGTMCreativeBenchmarkStatusV1",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "status": "blocked_preflight",
        "blocker": "local_generation_endpoint_unresponsive",
        "retry_when_accelerator_contention_clears": True,
        "output_directory": str(output_dir.relative_to(ROOT)),
        "model": {
            "provider": "ollama_local",
            "name": model_name,
            "digest": model_digest,
            "model_receipt_file_sha256": model_receipt_sha,
        },
        "planned_case_count": len(SCENARIOS),
        "planned_model_call_count": len(SCENARIOS) * 3,
        "completed_case_count": 0,
        "completed_model_call_count": 0,
        "validated_candidate_count": 0,
        "preflight": {
            "passed": False,
            "completed_model_call_count": 0,
            "error_type": type(error).__name__,
            "error_message": str(error),
            "receipt": dict(error.receipt),
        },
        "coverage_contract": {
            "business_models": sorted({row["business_model"] for row in SCENARIOS}),
            "lifecycles": sorted({row["lifecycle"] for row in SCENARIOS}),
            "budgets": sorted({row["budget"] for row in SCENARIOS}),
            "industry_risks": sorted({row["industry_risk"] for row in SCENARIOS}),
        },
        "network_download_performed": False,
        "cloud_api_calls": 0,
        "training_observed": False,
        "human_review_completed": False,
        "winner_selected": False,
        "radeon_local_inference_observed": False,
        "automatic_external_action_enabled": False,
        "truth_boundary": (
            "This status proves only that a digest-pinned localhost generation "
            "preflight was attempted and failed before scenario state was prepared. "
            "It is not model execution, training, human preference, 4A quality, "
            "business lift, causal revenue, Radeon execution or Top-1 evidence."
        ),
    }


def _progress_status(
    *,
    model_name: str,
    model_digest: str,
    model_receipt_sha: str,
    output_dir: Path,
    preflight: Mapping[str, Any],
    results: list[dict[str, Any]],
    active_case_id: str | None,
    status: str = "running",
    blocker: str | None = None,
    failure: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema": "ProofLaunchLocalGTMCreativeBenchmarkStatusV1",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "blocker": blocker,
        "retry_when_accelerator_contention_clears": blocker is not None,
        "active_case_id": active_case_id,
        "output_directory": str(output_dir.relative_to(ROOT)),
        "model": {
            "provider": "ollama_local",
            "name": model_name,
            "digest": model_digest,
            "model_receipt_file_sha256": model_receipt_sha,
        },
        "planned_case_count": len(SCENARIOS),
        "planned_model_call_count": len(SCENARIOS) * 3,
        "completed_case_count": sum(
            row.get("status") == "generated_validated_unreviewed" for row in results
        ),
        "observed_case_count": len(results),
        "completed_model_call_count": sum(
            int(row.get("completed_call_count", 0)) for row in results
        ),
        "validated_candidate_count": sum(
            int(row.get("candidate_count", 0)) for row in results
        ),
        "preflight": dict(preflight),
        "failure": dict(failure) if failure is not None else None,
        "coverage_contract": {
            "business_models": sorted({row["business_model"] for row in SCENARIOS}),
            "lifecycles": sorted({row["lifecycle"] for row in SCENARIOS}),
            "budgets": sorted({row["budget"] for row in SCENARIOS}),
            "industry_risks": sorted({row["industry_risk"] for row in SCENARIOS}),
        },
        "network_download_performed": False,
        "cloud_api_calls": 0,
        "training_observed": False,
        "human_review_completed": False,
        "winner_selected": False,
        "radeon_local_inference_observed": False,
        "automatic_external_action_enabled": False,
        "truth_boundary": (
            "This status records a digest-pinned localhost benchmark attempt and "
            "transactionally preserved progress only. Until completed, it proves no "
            "cross-scenario creative result. It is not training, human preference, "
            "4A quality, business lift, causal revenue, Radeon execution or Top-1 evidence."
        ),
    }


def _read_model(path: Path) -> tuple[str, str, str]:
    receipt = json.loads(path.read_text(encoding="utf-8"))
    model = receipt.get("model")
    if not isinstance(model, Mapping):
        raise SystemExit("local model receipt has no model identity")
    name = str(model.get("name") or "").strip()
    digest = str(model.get("digest") or "").strip()
    if not name or len(digest) != 64:
        raise SystemExit("local model receipt has an invalid model identity")
    if receipt.get("localhost_only") is not True:
        raise SystemExit("local model receipt is not localhost-only")
    if receipt.get("network_download_performed") is not False:
        raise SystemExit("local model receipt indicates an unapproved download")
    return name, digest, hashlib.sha256(path.read_bytes()).hexdigest()


def _payload(case: Mapping[str, str], image_sha256: str) -> dict[str, Any]:
    strategy = {
        "org_id": "prooflaunch-local-benchmark",
        "project_id": "cross-scenario-creative-v1",
        "owner": "ProofLaunch benchmark operator",
        "industry": case["industry"],
        "business_model": case["business_model"],
        "lifecycle": case["lifecycle"],
        "budget": case["budget"],
        "industry_risk": case["industry_risk"],
        "audience_name": case["audience_name"],
        "audience_problem": case["audience_problem"],
        "audience_outcome": case["audience_outcome"],
        "buying_context": case["buying_context"],
        "brand_purpose": "Turn campaign claims into inspectable evidence and useful action.",
        "customer_promise": "A review-ready GTM operating pack without automatic external action.",
        "brand_voice": "specific, inventive, calm, evidence-first",
        "offer": case["offer"],
        "landing_url": f"https://example.invalid/{case['case_id']}",
        "schedule_timezone": "America/New_York",
        "claim_assurance": "owner_attested",
    }
    if case["industry_risk"] == "high_regulation":
        strategy["specialist_approved_by"] = "benchmark-specialist@example.test"
    return {
        "request_id": f"local-creative-benchmark-{case['case_id']}",
        "campaign_id": f"benchmark-{case['case_id']}",
        "campaign": {
            "product_name": "ProofLaunch Cortex-X",
            "specification_text": (
                "Compiles a rights-bound brief into review-ready GTM drafts. "
                "Every external action requires a named human release."
            ),
            "market": "North America",
            "platform": case["platform"],
            "goal": "Create an evidence-first campaign system for controlled evaluation.",
            "target_emotion": "surprise",
        },
        "input_artifacts": {"product_image": image_sha256},
        "rights": {
            "confirmed": True,
            "basis": "Project-owned local fixture used only for offline benchmark execution.",
        },
        "maximum_actions": 12,
        "maximum_cost_usd": 0,
        "human_release_required": True,
        "data_class": "synthetic",
        "strategy": strategy,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run a frozen eight-scenario, twenty-four-call GTM creative benchmark "
            "through an already installed digest-pinned Ollama model."
        )
    )
    parser.add_argument("--output-dir", type=_inside_project, default=DEFAULT_OUTPUT)
    parser.add_argument("--status-output", type=_inside_project, default=DEFAULT_STATUS)
    parser.add_argument("--product-image", type=_inside_project, default=DEFAULT_IMAGE)
    parser.add_argument(
        "--model-receipt", type=_inside_project, default=DEFAULT_MODEL_RECEIPT
    )
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--preflight-timeout-seconds", type=float, default=15.0)
    args = parser.parse_args()
    if not 1 <= args.preflight_timeout_seconds <= 30:
        raise SystemExit("--preflight-timeout-seconds must be in [1, 30]")
    if not 1 <= args.timeout_seconds <= 300:
        raise SystemExit("--timeout-seconds must be in [1, 300]")
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise SystemExit("benchmark output directory must be empty")
    args.output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    model_name, model_digest, model_receipt_sha = _read_model(args.model_receipt)
    local = OllamaLocalClient(OllamaLocalSpec(model_name, model_digest))

    try:
        preflight = local.complete(
            [
                {
                    "role": "system",
                    "content": "Return one JSON object and no prose.",
                },
                {"role": "user", "content": '{"ready":true}'},
            ],
            scope=InferenceScope.DEVELOPMENT_CORE,
            purpose="local_gtm_creative_benchmark_preflight",
            max_tokens=16,
            temperature=0,
            timeout_seconds=args.preflight_timeout_seconds,
            official_retry_rounds=0,
        )
    except InferenceGatewayCallError as error:
        blocked = _blocked_status(
            model_name=model_name,
            model_digest=model_digest,
            model_receipt_sha=model_receipt_sha,
            error=error,
            output_dir=args.output_dir,
        )
        _write_status(args.output_dir / "benchmark-blocker.json", blocked)
        _write_status(args.status_output, blocked)
        print(
            json.dumps(
                {
                    "status": blocked["status"],
                    "blocker": blocked["blocker"],
                    "planned_cases": blocked["planned_case_count"],
                    "completed_calls": 0,
                },
                sort_keys=True,
            )
        )
        return 3

    state_root = args.output_dir / "state"
    cases_root = args.output_dir / "cases"
    image_bytes = args.product_image.read_bytes()
    image_sha256 = hashlib.sha256(image_bytes).hexdigest()

    preflight_status = {
        "passed": True,
        "completed_model_call_count": 1,
        "provider": preflight.provider,
        "model": preflight.model,
        "route": preflight.route,
        "response_sha256": preflight.receipt.get("normalized_response_sha256"),
    }
    results: list[dict[str, Any]] = []
    creative_signatures: list[dict[str, str]] = []
    _write_status(
        args.status_output,
        _progress_status(
            model_name=model_name,
            model_digest=model_digest,
            model_receipt_sha=model_receipt_sha,
            output_dir=args.output_dir,
            preflight=preflight_status,
            results=results,
            active_case_id=None,
        ),
    )

    store = SubmissionStore(state_root)
    store.artifacts.put(
        io.BytesIO(image_bytes),
        expected_sha256=image_sha256,
        media_type="image/png",
    )
    worker = AgencyRunWorker(store, worker_id="local-creative-benchmark-worker")
    service = ProductionAgencyService(store, worker=worker)

    for index, case in enumerate(SCENARIOS, start=1):
        _write_status(
            args.status_output,
            _progress_status(
                model_name=model_name,
                model_digest=model_digest,
                model_receipt_sha=model_receipt_sha,
                output_dir=args.output_dir,
                preflight=preflight_status,
                results=results,
                active_case_id=case["case_id"],
            ),
        )
        try:
            created = service.create_run(_payload(case, image_sha256))
            prepared = worker.process_one()
            if not prepared.processed or prepared.status != "awaiting_release":
                raise RuntimeError(
                    f"{case['case_id']} did not reach the human release gate"
                )
            _, relative = worker._find_prepared_state(created["run_id"])
            prepared_root = state_root / relative
            plan = json.loads(
                (prepared_root / "text-creative-challenger-plan.json").read_text(
                    encoding="utf-8"
                )
            )
            execution = execute_text_challenger_plan(
                plan,
                local,
                timeout_seconds=args.timeout_seconds,
                official_retry_rounds=0,
            )
            bundle_sha = write_text_challenger_bundle(
                cases_root / case["case_id"],
                plan=plan,
                execution=execution,
            )
        except Exception as error:
            failure = {
                "case_id": case["case_id"],
                "error_type": type(error).__name__,
                "error_message": str(error),
                "receipt": (
                    dict(error.receipt)
                    if isinstance(error, InferenceGatewayCallError)
                    else None
                ),
            }
            blocked = _progress_status(
                model_name=model_name,
                model_digest=model_digest,
                model_receipt_sha=model_receipt_sha,
                output_dir=args.output_dir,
                preflight=preflight_status,
                results=results,
                active_case_id=case["case_id"],
                status="blocked_case_execution",
                blocker="local_generation_case_failed",
                failure=failure,
            )
            _write_status(args.output_dir / "benchmark-blocker.json", blocked)
            _write_status(args.status_output, blocked)
            print(
                json.dumps(
                    {
                        "status": blocked["status"],
                        "case_id": case["case_id"],
                        "completed_cases": blocked["completed_case_count"],
                        "completed_calls": blocked["completed_model_call_count"],
                    },
                    sort_keys=True,
                )
            )
            return 4
        receipt = execution.get("challenger_receipt")
        quality = receipt.get("creative_quality_gate") if isinstance(receipt, Mapping) else {}
        result = {
            "case_id": case["case_id"],
            "run_id": created["run_id"],
            "business_model": case["business_model"],
            "lifecycle": case["lifecycle"],
            "budget": case["budget"],
            "industry_risk": case["industry_risk"],
            "strategy_id": plan["strategy_id"],
            "scenario_signature": plan["scenario_lens"]["signature"],
            "territory_variant_ids": list(plan["territory_variant_ids"]),
            "plan_sha256": plan["content_sha256"],
            "execution_sha256": execution["content_sha256"],
            "status": execution["status"],
            "completed_call_count": execution["completed_call_count"],
            "candidate_count": execution["candidate_count"],
            "failure": execution["failure"],
            "territory_ids": [
                row["territory_id"] for row in execution["candidates"]
            ],
            "scenario_fit_dimension_counts": [
                row["candidate"]["creative_quality_gate"].get(
                    "scenario_dimension_count", 0
                )
                for row in execution["candidates"]
            ],
            "candidate_creative_signature_sha256s": [
                hashlib.sha256(
                    _candidate_creative_signature(row["candidate"]).encode("utf-8")
                ).hexdigest()
                for row in execution["candidates"]
            ],
            "routes": sorted({row["route"] for row in execution["candidates"]}),
            "models": sorted({row["model"] for row in execution["candidates"]}),
            "maximum_territory_jaccard": quality.get("maximum_territory_jaccard"),
            "maximum_portfolio_channel_jaccard": quality.get(
                "maximum_portfolio_channel_jaccard"
            ),
            "bundle_file_sha256": bundle_sha,
            "human_review_completed": False,
            "winner_selected": False,
            "external_publish_executed": False,
        }
        creative_signatures.extend(
            {
                "case_id": case["case_id"],
                "territory_id": str(row["territory_id"]),
                "text": _candidate_creative_signature(row["candidate"]),
            }
            for row in execution["candidates"]
        )
        results.append(result)
        if execution["status"] != "generated_validated_unreviewed":
            failure = {
                "case_id": case["case_id"],
                "error_type": "IncompleteCreativeExecution",
                "error_message": (
                    "local creative execution did not produce three validated candidates"
                ),
                "execution_status": execution["status"],
                "execution_failure": execution.get("failure"),
                "execution_sha256": execution["content_sha256"],
                "bundle_file_sha256": bundle_sha,
            }
            blocked = _progress_status(
                model_name=model_name,
                model_digest=model_digest,
                model_receipt_sha=model_receipt_sha,
                output_dir=args.output_dir,
                preflight=preflight_status,
                results=results,
                active_case_id=case["case_id"],
                status="blocked_case_execution",
                blocker="local_generation_case_incomplete",
                failure=failure,
            )
            _write_status(args.output_dir / "benchmark-blocker.json", blocked)
            _write_status(args.status_output, blocked)
            print(
                json.dumps(
                    {
                        "status": blocked["status"],
                        "case_id": case["case_id"],
                        "execution_status": execution["status"],
                        "completed_cases": blocked["completed_case_count"],
                        "completed_calls": blocked["completed_model_call_count"],
                    },
                    sort_keys=True,
                )
            )
            return 4
        _write_status(
            args.status_output,
            _progress_status(
                model_name=model_name,
                model_digest=model_digest,
                model_receipt_sha=model_receipt_sha,
                output_dir=args.output_dir,
                preflight=preflight_status,
                results=results,
                active_case_id=None,
            ),
        )
        print(
            f"{index}/{len(SCENARIOS)} {case['case_id']}: "
            f"{execution['status']} ({execution['candidate_count']}/3)"
        )

    planned_calls = len(SCENARIOS) * 3
    completed_calls = sum(row["completed_call_count"] for row in results)
    candidates = sum(row["candidate_count"] for row in results)
    complete_cases = sum(row["status"] == "generated_validated_unreviewed" for row in results)
    unique_scenario_signatures = {
        row["scenario_signature"] for row in results
    }
    unique_variant_portfolios = {
        tuple(row["territory_variant_ids"]) for row in results
    }
    scenario_fit_candidate_count = sum(
        count == 4
        for row in results
        for count in row["scenario_fit_dimension_counts"]
    )
    scenario_adaptation_gate = {
        "schema": "ProofLaunchCreativeScenarioAdaptationGateV1",
        "expected_scenario_count": len(SCENARIOS),
        "unique_scenario_signature_count": len(unique_scenario_signatures),
        "unique_territory_variant_portfolio_count": len(unique_variant_portfolios),
        "expected_candidate_count": planned_calls,
        "four_dimension_fit_candidate_count": scenario_fit_candidate_count,
        "all_scenarios_distinct": len(unique_scenario_signatures) == len(SCENARIOS),
        "all_variant_portfolios_distinct": len(unique_variant_portfolios) == len(SCENARIOS),
        "all_candidates_fit_four_dimensions": scenario_fit_candidate_count == planned_calls,
    }
    scenario_adaptation_gate["passed"] = all(
        scenario_adaptation_gate[field]
        for field in (
            "all_scenarios_distinct",
            "all_variant_portfolios_distinct",
            "all_candidates_fit_four_dimensions",
        )
    )
    comparable_pairs = [
        (left, right)
        for index, left in enumerate(creative_signatures)
        for right in creative_signatures[index + 1 :]
        if left["territory_id"] == right["territory_id"]
    ]
    pair_jaccards = [
        _jaccard(left["text"], right["text"])
        for left, right in comparable_pairs
    ]
    cross_scenario_expression_gate = {
        "schema": "ProofLaunchCrossScenarioCreativeExpressionGateV1",
        "comparable_same_territory_pair_count": len(comparable_pairs),
        "exact_duplicate_pair_count": sum(
            left["text"] == right["text"] for left, right in comparable_pairs
        ),
        "maximum_pair_jaccard": round(max(pair_jaccards), 6),
        "maximum_allowed_pair_jaccard": 0.72,
    }
    cross_scenario_expression_gate["passed"] = (
        cross_scenario_expression_gate["exact_duplicate_pair_count"] == 0
        and cross_scenario_expression_gate["maximum_pair_jaccard"] <= 0.72
    )
    receipt: dict[str, Any] = {
        "schema": "ProofLaunchLocalGTMCreativeBenchmarkV1",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "model": {
            "provider": "ollama_local",
            "name": model_name,
            "digest": model_digest,
            "model_receipt_file_sha256": model_receipt_sha,
        },
        "case_count": len(results),
        "planned_model_call_count": planned_calls,
        "completed_model_call_count": completed_calls,
        "validated_candidate_count": candidates,
        "complete_case_count": complete_cases,
        "case_completion_rate": complete_cases / len(results),
        "candidate_contract_pass_rate": candidates / planned_calls,
        "business_models": sorted({row["business_model"] for row in results}),
        "lifecycles": sorted({row["lifecycle"] for row in results}),
        "budgets": sorted({row["budget"] for row in results}),
        "industry_risks": sorted({row["industry_risk"] for row in results}),
        "case_results": results,
        "scenario_adaptation_gate": scenario_adaptation_gate,
        "cross_scenario_expression_gate": cross_scenario_expression_gate,
        "preflight": preflight_status,
        "all_requests_localhost_only": all(
            routes == ["local_ollama"] for routes in (row["routes"] for row in results)
        ),
        "network_download_performed": False,
        "cloud_api_calls": 0,
        "training_observed": False,
        "human_review_completed": False,
        "winner_selected": False,
        "radeon_local_inference_observed": False,
        "automatic_external_action_enabled": False,
        "truth_boundary": (
            "This receipt proves digest-pinned localhost model execution and mechanical "
            "creative-contract results across eight representative GTM scenarios. It is "
            "not fine-tuning, human preference, production lift, Radeon execution, 4A "
            "quality, annual breakout performance, causal revenue or Top-1 evidence."
        ),
    }
    receipt["content_sha256"] = _digest(receipt)
    atomic_write_text(
        args.output_dir / "benchmark-receipt.json",
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    _write_status(
        args.status_output,
        {
            "schema": "ProofLaunchLocalGTMCreativeBenchmarkStatusV1",
            "observed_at": receipt["observed_at"],
            "status": (
                "completed"
                if complete_cases == len(results)
                and scenario_adaptation_gate["passed"]
                and cross_scenario_expression_gate["passed"]
                else "completed_quality_gate_failed"
            ),
            "blocker": None,
            "retry_when_accelerator_contention_clears": False,
            "output_directory": str(args.output_dir.relative_to(ROOT)),
            "model": receipt["model"],
            "planned_case_count": len(SCENARIOS),
            "observed_case_count": len(results),
            "planned_model_call_count": planned_calls,
            "completed_case_count": complete_cases,
            "completed_model_call_count": completed_calls,
            "validated_candidate_count": candidates,
            "preflight": receipt["preflight"],
            "scenario_adaptation_gate": scenario_adaptation_gate,
            "cross_scenario_expression_gate": cross_scenario_expression_gate,
            "coverage_contract": {
                "business_models": receipt["business_models"],
                "lifecycles": receipt["lifecycles"],
                "budgets": receipt["budgets"],
                "industry_risks": receipt["industry_risks"],
            },
            "benchmark_receipt_sha256": hashlib.sha256(
                (args.output_dir / "benchmark-receipt.json").read_bytes()
            ).hexdigest(),
            "network_download_performed": False,
            "cloud_api_calls": 0,
            "training_observed": False,
            "human_review_completed": False,
            "winner_selected": False,
            "radeon_local_inference_observed": False,
            "automatic_external_action_enabled": False,
            "truth_boundary": receipt["truth_boundary"],
        },
    )
    return (
        0
        if complete_cases == len(results)
        and scenario_adaptation_gate["passed"]
        and cross_scenario_expression_gate["passed"]
        else 2
    )


if __name__ == "__main__":
    raise SystemExit(main())
