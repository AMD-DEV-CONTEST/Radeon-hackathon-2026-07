#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import secrets
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
    build_text_blind_review_bundle,
    write_text_challenger_bundle,
)


DEFAULT_BENCHMARK = (
    ROOT / "artifacts/local-gtm-creative-benchmark-v11/benchmark-receipt.json"
)
DEFAULT_OUTPUT = (
    ROOT / "artifacts/local-gtm-creative-benchmark-v11/portfolio-blind-review-v2"
)
DEFAULT_STATUS = ROOT / "evidence/v10/local-gtm-portfolio-blind-review-status.json"


def _inside_project(raw: str) -> Path:
    path = Path(raw).expanduser().resolve()
    try:
        path.relative_to(ROOT.resolve())
    except ValueError as error:
        raise argparse.ArgumentTypeError("path must remain inside the project root") from error
    return path


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: Mapping[str, Any], *, private: bool) -> str:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    atomic_write_text(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    path.chmod(0o600 if private else 0o644)
    return _file_sha(path)


def _verify_benchmark(receipt: Mapping[str, Any]) -> None:
    if receipt.get("schema") != "ProofLaunchLocalGTMCreativeBenchmarkV1":
        raise SystemExit("benchmark receipt schema is invalid")
    supplied = receipt.get("content_sha256")
    unsigned = dict(receipt)
    unsigned.pop("content_sha256", None)
    if supplied != _digest(unsigned):
        raise SystemExit("benchmark receipt content digest is invalid")
    if not (
        receipt.get("case_count") == 9
        and receipt.get("complete_case_count") == 9
        and receipt.get("completed_model_call_count") == 27
        and receipt.get("validated_candidate_count") == 27
        and receipt.get("all_requests_localhost_only") is True
        and receipt.get("cloud_api_calls") == 0
        and receipt.get("human_review_completed") is False
    ):
        raise SystemExit("benchmark is not eligible for portfolio blind-review compilation")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compile nine local GTM cases into 54 blinded pairs and 270 empty "
            "five-human review assignments."
        )
    )
    parser.add_argument("--benchmark", type=_inside_project, default=DEFAULT_BENCHMARK)
    parser.add_argument("--output-dir", type=_inside_project, default=DEFAULT_OUTPUT)
    parser.add_argument("--status-output", type=_inside_project, default=DEFAULT_STATUS)
    args = parser.parse_args()
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise SystemExit("portfolio blind-review output directory must be empty")
    args.output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

    benchmark = json.loads(args.benchmark.read_text(encoding="utf-8"))
    _verify_benchmark(benchmark)
    benchmark_root = args.benchmark.parent
    state_root = benchmark_root / "state/runs"
    case_rows: list[dict[str, Any]] = []
    private_rows: list[dict[str, Any]] = []

    for result in benchmark["case_results"]:
        case_id = str(result["case_id"])
        run_id = str(result["run_id"])
        source_root = benchmark_root / "cases" / case_id
        plan = json.loads(
            (source_root / "text-creative-challenger-plan.json").read_text(
                encoding="utf-8"
            )
        )
        execution = json.loads(
            (source_root / "text-creative-challenger-execution.json").read_text(
                encoding="utf-8"
            )
        )
        prepared_roots = sorted((state_root / run_id).glob("prepare-*/channel-copy.json"))
        if len(prepared_roots) != 1:
            raise SystemExit(f"{case_id} has no unique prepared channel baseline")
        channel_copy = json.loads(prepared_roots[0].read_text(encoding="utf-8"))
        bundle = build_text_blind_review_bundle(
            plan,
            execution,
            channel_copy,
            randomization_secret=secrets.token_hex(32),
            reviewer_count=5,
        )
        case_root = args.output_dir / "cases" / case_id
        files = write_text_challenger_bundle(
            case_root,
            plan=plan,
            execution=execution,
            public_packet=bundle["public_packet"],
            private_mapping=bundle["private_mapping"],
        )
        public_path = case_root / "text-creative-blind-review-public.json"
        private_path = case_root / "text-creative-blind-review-private.json"
        case_rows.append(
            {
                "case_id": case_id,
                "run_id": run_id,
                "business_model": result["business_model"],
                "lifecycle": result["lifecycle"],
                "budget": result["budget"],
                "industry_risk": result["industry_risk"],
                "public_packet_path": str(public_path.relative_to(args.output_dir)),
                "public_packet_file_sha256": files[
                    "text-creative-blind-review-public.json"
                ],
                "public_packet_content_sha256": bundle["public_packet"][
                    "content_sha256"
                ],
                "pair_count": bundle["public_packet"]["pair_count"],
                "reviewer_count": bundle["public_packet"]["reviewer_count"],
                "expected_review_count": bundle["public_packet"][
                    "review_task_count"
                ],
                "candidate_identity_exposed": False,
                "provider_identity_exposed": False,
                "submitted_review_count": 0,
                "review_complete": False,
                "winner_selected": False,
            }
        )
        private_rows.append(
            {
                "case_id": case_id,
                "private_mapping_path": str(private_path.relative_to(args.output_dir)),
                "private_mapping_file_sha256": files[
                    "text-creative-blind-review-private.json"
                ],
                "private_mapping_content_sha256": bundle["private_mapping"][
                    "content_sha256"
                ],
                "public_packet_content_sha256": bundle["public_packet"][
                    "content_sha256"
                ],
            }
        )

    public: dict[str, Any] = {
        "schema": "ProofLaunchLocalGTMPortfolioBlindReviewPacketV1",
        "compiled_at": datetime.now(timezone.utc).isoformat(),
        "benchmark_receipt_content_sha256": benchmark["content_sha256"],
        "benchmark_receipt_file_sha256": _file_sha(args.benchmark),
        "case_count": len(case_rows),
        "pair_count": sum(row["pair_count"] for row in case_rows),
        "reviewer_slot_count": 5,
        "expected_review_count": sum(
            row["expected_review_count"] for row in case_rows
        ),
        "review_tasks_per_slot": sum(row["pair_count"] for row in case_rows),
        "cases": case_rows,
        "coverage": {
            "business_models": sorted({row["business_model"] for row in case_rows}),
            "lifecycles": sorted({row["lifecycle"] for row in case_rows}),
            "budgets": sorted({row["budget"] for row in case_rows}),
            "industry_risks": sorted({row["industry_risk"] for row in case_rows}),
        },
        "portfolio_promotion_gate": {
            "all_270_reviews_required": True,
            "all_9_case_aggregates_required": True,
            "minimum_case_recommendations": 7,
            "minimum_b2b_case_recommendations": 4,
            "minimum_b2c_case_recommendations": 3,
            "minimum_zero_budget_case_recommendations": 3,
            "required_high_regulation_case_recommendations": 2,
            "per_case_minimum_eligible_comparisons_per_territory": 8,
            "per_case_minimum_preference_rate": 0.60,
            "per_case_wilson_lower_95_must_exceed": 0.50,
            "per_case_critical_failure_count_must_equal": 0,
        },
        "submitted_review_count": 0,
        "review_complete": False,
        "portfolio_promotion_passed": False,
        "human_preference_observed": False,
        "candidate_identity_exposed": False,
        "provider_identity_exposed": False,
        "private_mapping_exposed": False,
        "automatic_scoring_executed": False,
        "winner_selected": False,
        "external_publish_executed": False,
        "truth_boundary": (
            "This packet proves nine content-bound blind-review queues were compiled "
            "from the completed local benchmark. It contains 54 randomized pairs and "
            "270 empty five-human assignments, not submitted reviews, human preference, "
            "a winner, 4A quality, publication, lift, revenue or Top-1 evidence."
        ),
    }
    public["content_sha256"] = _digest(public)
    public_path = args.output_dir / "portfolio-blind-review-public.json"
    public_file_sha = _write_json(public_path, public, private=False)

    private: dict[str, Any] = {
        "schema": "ProofLaunchLocalGTMPortfolioBlindReviewPrivateManifestV1",
        "public_packet_content_sha256": public["content_sha256"],
        "public_packet_file_sha256": public_file_sha,
        "case_count": len(private_rows),
        "cases": private_rows,
        "randomization_secrets_persisted": False,
        "private_mapping_exposed": False,
        "review_complete": False,
        "winner_selected": False,
        "external_publish_executed": False,
    }
    private["content_sha256"] = _digest(private)
    private_path = args.output_dir / "portfolio-blind-review-private.json"
    private_file_sha = _write_json(private_path, private, private=True)

    status: dict[str, Any] = {
        "schema": "ProofLaunchLocalGTMPortfolioBlindReviewStatusV1",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "status": "awaiting_270_named_human_reviews",
        "public_packet_content_sha256": public["content_sha256"],
        "public_packet_file_sha256": public_file_sha,
        "private_manifest_content_sha256": private["content_sha256"],
        "private_manifest_file_sha256": private_file_sha,
        "case_count": public["case_count"],
        "pair_count": public["pair_count"],
        "reviewer_slot_count": public["reviewer_slot_count"],
        "expected_review_count": public["expected_review_count"],
        "submitted_review_count": 0,
        "review_complete": False,
        "portfolio_promotion_passed": False,
        "human_preference_observed": False,
        "winner_selected": False,
        "external_publish_executed": False,
        "truth_boundary": public["truth_boundary"],
    }
    status["content_sha256"] = _digest(status)
    _write_json(args.status_output, status, private=False)
    print(
        json.dumps(
            {
                "status": status["status"],
                "case_count": status["case_count"],
                "pair_count": status["pair_count"],
                "expected_review_count": status["expected_review_count"],
                "output": str(args.output_dir),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
