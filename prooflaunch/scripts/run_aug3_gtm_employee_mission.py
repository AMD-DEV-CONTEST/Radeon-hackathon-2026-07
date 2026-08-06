#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import io
import json
import secrets
import sys
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from prooflaunch_remix.gtm_text_challenger_runner import (
    build_text_blind_review_bundle,
    execute_text_challenger_plan,
    execute_text_craft_quality_loop,
    write_text_challenger_bundle,
)
from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.inference_gateway import OllamaLocalClient, OllamaLocalSpec
from prooflaunch_remix.v10_submission_runtime import AgencyRunWorker, ProductionAgencyService
from prooflaunch_remix.v10_submission_store import SubmissionStore


DEFAULT_IMAGE = ROOT / "evidence/local/reference-run/fixture-product.png"
DEFAULT_MODEL_RECEIPT = ROOT / "artifacts/local-gtm-generative-baseline-v1/receipt.json"


def _inside_project(path: str) -> Path:
    resolved = Path(path).expanduser().resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError as error:
        raise argparse.ArgumentTypeError("path must remain inside the project root") from error
    return resolved


def _timeout_seconds(value: str) -> float:
    try:
        seconds = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("timeout must be numeric") from error
    if not 1 <= seconds <= 120:
        raise argparse.ArgumentTypeError("timeout must be in [1, 120] seconds")
    return seconds


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _mission_status(
    execution: Mapping[str, Any],
    craft_quality: Mapping[str, Any] | None,
    blind: Mapping[str, Any] | None,
) -> str:
    if blind is not None:
        if craft_quality is not None and craft_quality.get("all_territories_advisory_pass") is not True:
            return "awaiting_named_human_blind_review_with_critic_contract_failure"
        return "awaiting_named_human_blind_review"
    if execution.get("status") != "generated_validated_unreviewed":
        return "blocked_local_candidate_contract"
    if craft_quality is not None and craft_quality.get("all_territories_advisory_pass") is not True:
        return "blocked_local_craft_critic_contract"
    return "blocked_blind_review_bundle_contract"


def _critic_failure_allows_human_review_only(
    craft_quality: Mapping[str, Any] | None,
) -> bool:
    """Keep evaluation available without converting malformed critic output into a pass."""

    if not craft_quality or craft_quality.get("all_territories_advisory_pass") is True:
        return False
    records = craft_quality.get("records")
    if not isinstance(records, list) or len(records) != 3:
        return False
    contract_failure_observed = False
    for row in records:
        if not isinstance(row, Mapping):
            return False
        if row.get("status") in {
            "advisory_pass_pending_human_review",
            "repaired_advisory_pass_pending_human_review",
        }:
            continue
        if row.get("status") != "blocked_review_failure":
            return False
        failure = row.get("failure")
        if not isinstance(failure, Mapping) or failure.get("error_code") != "craft_review_failed":
            return False
        contract_failure_observed = True
        reviews = [
            *row.get("initial_reviews", []),
            *row.get("post_repair_reviews", []),
        ]
        if any(
            isinstance(review, Mapping)
            and isinstance(review.get("review"), Mapping)
            and review["review"].get("decision") == "block"
            for review in reviews
        ):
            return False
    return contract_failure_observed


def _craft_failure_summary(craft_quality: Mapping[str, Any] | None) -> dict[str, Any]:
    records = craft_quality.get("records", []) if craft_quality else []
    failures = [
        row.get("failure")
        for row in records
        if isinstance(row, Mapping) and isinstance(row.get("failure"), Mapping)
    ]
    return {
        "failure_count": len(failures),
        "error_codes": sorted({str(row.get("error_code") or "unknown") for row in failures}),
        "failed_work_order_ids": sorted({str(row.get("work_order_id") or "unknown") for row in failures}),
    }


def _read_model(receipt_path: Path) -> tuple[str, str, str]:
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
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
    return name, digest, hashlib.sha256(receipt_path.read_bytes()).hexdigest()


def _launch_payload(image_sha256: str, *, scenario: str = "b2b") -> dict[str, Any]:
    if scenario == "b2c":
        return {
            "request_id": "aug3-local-first-b2c-mission-v1",
            "campaign_id": "fold-and-fill-zero-budget-b2c-v1",
            "campaign": {
                "product_name": "Fold & Fill Ratio One",
                "specification_text": (
                    "Synthetic capability reference: one sealed 30 mL sample is intended "
                    "to be diluted with 270 mL water in a reusable 300 mL bottle; "
                    "formulation, cleaning performance, material compatibility, environmental "
                    "impact, safety, shipment availability, and commercial outcome are unverified."
                ),
                "market": "North America",
                "platform": "TikTok",
                "goal": (
                    "Earn qualified packaging-comprehension study participation through a "
                    "zero-paid-media, claim-disciplined product demonstration."
                ),
                "target_emotion": "surprise",
            },
            "input_artifacts": {"product_image": image_sha256},
            "rights": {
                "confirmed": True,
                "basis": "Project-owned local fixture used only for synthetic ProofLaunch validation.",
            },
            "maximum_actions": 12,
            "maximum_cost_usd": 0,
            "human_release_required": True,
            "data_class": "internal",
            "strategy": {
                "org_id": "prooflaunch",
                "project_id": "fold-fill-b2c-aug3",
                "owner": "ProofLaunch project operator",
                "industry": "DTC home-care concept",
                "business_model": "b2c",
                "lifecycle": "growth",
                "budget": "zero",
                "industry_risk": "standard",
                "audience_name": "design-conscious home-care shoppers",
                "audience_problem": (
                    "vague concentration, performance and sustainability language makes "
                    "a product concept difficult to inspect or trust"
                ),
                "audience_outcome": (
                    "understand the declared sample ratio and every unverified boundary before "
                    "deciding whether to join a packaging-comprehension study"
                ),
                "buying_context": (
                    "a shopper sees a concentrated refill concept in short-form social content "
                    "but has no verified performance, safety or environmental evidence"
                ),
                "brand_purpose": "Make the product fact and the unknowns equally visible.",
                "customer_promise": (
                    "A transparent synthetic packaging walkthrough without purchase, use or "
                    "performance pressure."
                ),
                "brand_voice": "visually specific, candid, lightly playful, evidence-first",
                "offer": (
                    "join a packaging-comprehension study for a sealed synthetic sample reference; "
                    "do not purchase, mix or use the sample"
                ),
                "landing_url": "https://example.invalid/fold-fill-packaging-study",
                "schedule_timezone": "America/New_York",
                "claim_assurance": "owner_attested",
            },
        }
    if scenario != "b2b":
        raise ValueError("scenario must be b2b or b2c")
    return {
        "request_id": "aug3-local-first-mission-v1",
        "campaign_id": "prooflaunch-zero-budget-b2b-v1",
        "campaign": {
            "product_name": "ProofLaunch Cortex-X",
            "specification_text": (
                "Compiles a rights-bound brief into review-ready GTM assets. "
                "External release requires human approval."
            ),
            "market": "North America",
            "platform": "LinkedIn",
            "goal": (
                "Earn qualified design-partner conversations with a zero-paid-media, "
                "evidence-first launch while preserving human release control."
            ),
            "target_emotion": "surprise",
        },
        "input_artifacts": {"product_image": image_sha256},
        "rights": {
            "confirmed": True,
            "basis": "Project-owned local fixture generated for ProofLaunch validation.",
        },
        "maximum_actions": 12,
        "maximum_cost_usd": 0,
        "human_release_required": True,
        "data_class": "internal",
        "strategy": {
            "org_id": "prooflaunch",
            "project_id": "cortex-x-aug3",
            "owner": "ProofLaunch project operator",
            "industry": "B2B AI software",
            "business_model": "b2b",
            "lifecycle": "launch",
            "budget": "zero",
            "industry_risk": "standard",
            "audience_name": "GTM leaders and founder-led growth teams",
            "audience_problem": (
                "fragmented strategy, content, approval and measurement tools create slow, "
                "unverifiable execution"
            ),
            "audience_outcome": (
                "move from a rights-bound brief to review-ready GTM artifacts with a single "
                "traceable operating record"
            ),
            "buying_context": (
                "a design partner needs a demonstrable local-first workflow before adopting "
                "an autonomous GTM employee"
            ),
            "brand_purpose": (
                "Turn marketing claims into inspectable evidence and safe, useful action."
            ),
            "customer_promise": (
                "A complete review-ready GTM operating pack without automatic publishing."
            ),
            "brand_voice": "specific, inventive, calm, evidence-first",
            "offer": "review the end-to-end evidence pack and join the design-partner cohort",
            "landing_url": "https://example.invalid/prooflaunch-design-partner",
            "schedule_timezone": "America/New_York",
            "claim_assurance": "owner_attested",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Execute one persistent local-first GTM employee mission from brief through "
            "Graph/Loop/Harness preparation and model-generated blind-review staging."
        )
    )
    parser.add_argument("--output-dir", required=True, type=_inside_project)
    parser.add_argument("--product-image", type=_inside_project, default=DEFAULT_IMAGE)
    parser.add_argument(
        "--model-receipt", type=_inside_project, default=DEFAULT_MODEL_RECEIPT
    )
    parser.add_argument("--timeout-seconds", type=_timeout_seconds, default=120.0)
    parser.add_argument("--scenario", choices=("b2b", "b2c"), default="b2b")
    parser.add_argument(
        "--skip-craft-quality-loop",
        action="store_true",
        help="Skip specialist review/repair/re-review before human blind review.",
    )
    args = parser.parse_args()

    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise SystemExit("mission output directory must be empty")
    args.output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    state_root = args.output_dir / "state"
    challenger_root = args.output_dir / "local-text-challenger"
    image_bytes = args.product_image.read_bytes()
    image_sha256 = hashlib.sha256(image_bytes).hexdigest()

    store = SubmissionStore(state_root)
    store.artifacts.put(
        io.BytesIO(image_bytes),
        expected_sha256=image_sha256,
        media_type="image/png",
    )
    worker = AgencyRunWorker(store, worker_id="aug3-local-first-worker")
    service = ProductionAgencyService(store, worker=worker)
    created = service.create_run(_launch_payload(image_sha256, scenario=args.scenario))
    prepared_result = worker.process_one()
    prepared_snapshot = service.snapshot(created["run_id"])
    if (
        not prepared_result.processed
        or prepared_result.status != "awaiting_release"
        or prepared_snapshot.get("status") != "awaiting_release"
    ):
        raise SystemExit("GTM employee preparation did not reach the human release gate")

    preview = service.preview(created["run_id"])
    _, relative = worker._find_prepared_state(created["run_id"])
    prepared_root = state_root / relative
    plan_path = prepared_root / "text-creative-challenger-plan.json"
    channel_copy_path = prepared_root / "channel-copy.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    channel_copy = json.loads(channel_copy_path.read_text(encoding="utf-8"))

    model_name, model_digest, model_receipt_file_sha256 = _read_model(
        args.model_receipt
    )
    local = OllamaLocalClient(OllamaLocalSpec(model_name, model_digest))
    execution = execute_text_challenger_plan(
        plan,
        local,
        timeout_seconds=args.timeout_seconds,
        official_retry_rounds=0,
    )
    craft_quality = None
    human_review_execution = execution
    if (
        execution["status"] == "generated_validated_unreviewed"
        and not args.skip_craft_quality_loop
    ):
        craft_quality = execute_text_craft_quality_loop(
            plan,
            execution,
            local,
            timeout_seconds=args.timeout_seconds,
            official_retry_rounds=0,
        )
        if craft_quality["all_territories_advisory_pass"]:
            human_review_execution = craft_quality["human_review_execution"]
        elif _critic_failure_allows_human_review_only(craft_quality):
            human_review_execution = execution
    blind = None
    critic_failure_human_review_only = _critic_failure_allows_human_review_only(
        craft_quality
    )
    if (
        execution["status"] == "generated_validated_unreviewed"
        and (
            craft_quality is None
            or craft_quality["all_territories_advisory_pass"]
            or critic_failure_human_review_only
        )
    ):
        blind = build_text_blind_review_bundle(
            plan,
            human_review_execution,
            channel_copy,
            randomization_secret=secrets.token_hex(32),
        )
    bundle_hashes = write_text_challenger_bundle(
        challenger_root,
        plan=plan,
        execution=human_review_execution,
        public_packet=blind["public_packet"] if blind else None,
        private_mapping=blind["private_mapping"] if blind else None,
    )
    if craft_quality is not None:
        atomic_write_text(
            challenger_root / "text-craft-quality-execution.json",
            json.dumps(craft_quality, ensure_ascii=False, indent=2, sort_keys=True),
        )
        bundle_hashes["text-craft-quality-execution.json"] = hashlib.sha256(
            (challenger_root / "text-craft-quality-execution.json").read_bytes()
        ).hexdigest()

    strategy_artifacts = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(prepared_root.glob("*.json"))
    }
    receipt: dict[str, Any] = {
        "schema": "ProofLaunchAug3LocalFirstGTMEmployeeMissionV1",
        "scenario": args.scenario,
        "status": _mission_status(execution, craft_quality, blind),
        "run_id": created["run_id"],
        "production_state_root": str(state_root.relative_to(ROOT)),
        "prepared_artifact_root": str(prepared_root.relative_to(ROOT)),
        "product_image_sha256": image_sha256,
        "preview_digest": preview["preview_digest"],
        "strategy_artifact_sha256": strategy_artifacts,
        "local_model": {
            "provider": "ollama_local",
            "name": model_name,
            "digest": model_digest,
            "receipt_file_sha256": model_receipt_file_sha256,
        },
        "text_challenger": {
            "status": execution["status"],
            "candidate_contract_passed": execution["status"] == "generated_validated_unreviewed",
            "completed_call_count": execution["completed_call_count"],
            "candidate_count": execution["candidate_count"],
            "execution_sha256": execution["content_sha256"],
            "craft_quality_execution_sha256": (
                craft_quality["content_sha256"] if craft_quality else None
            ),
            "craft_quality_call_count": (
                craft_quality["craft_quality_call_count"] if craft_quality else 0
            ),
            "craft_quality_advisory_passed": bool(
                craft_quality and craft_quality["all_territories_advisory_pass"]
            ),
            "craft_quality_failure_summary": _craft_failure_summary(craft_quality),
            "critic_contract_failure_degraded_to_human_review_only": (
                critic_failure_human_review_only
            ),
            "critic_contract_failure_treated_as_quality_pass": False,
            "bundle_file_sha256": bundle_hashes,
            "blind_pair_count": blind["public_packet"]["pair_count"] if blind else 0,
            "human_review_task_count": (
                blind["public_packet"]["review_task_count"] if blind else 0
            ),
            "human_review_staged": blind is not None,
        },
        "graph_loop_harness_executed": True,
        "human_release_gate_reached": True,
        "human_release_approved": False,
        "blind_review_completed": False,
        "winner_selected": False,
        "external_publish_executed": False,
        "network_download_performed": False,
        "cloud_api_calls": 0,
        "radeon_local_inference_observed": False,
        "truth_boundary": (
            "This receipt distinguishes candidate-contract success, model-assisted craft-critic "
            "success and blind-review staging. A blocked critic does not erase a validated candidate, "
            "and a malformed critic may only degrade to source-hidden human review, never to a "
            "quality pass or release. A validated candidate does not prove craft quality. Nothing here proves Radeon "
            "execution, human preference, publication, causal lift or revenue."
        ),
    }
    receipt["content_sha256"] = _digest(receipt)
    receipt_path = args.output_dir / "mission-receipt.json"
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    receipt_path.chmod(0o600)
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if blind is not None else 2


if __name__ == "__main__":
    raise SystemExit(main())
