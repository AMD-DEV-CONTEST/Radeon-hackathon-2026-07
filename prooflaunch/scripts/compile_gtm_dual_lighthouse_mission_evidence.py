#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from prooflaunch_remix.files import atomic_write_text  # noqa: E402
from prooflaunch_remix.gtm_text_challenger_runner import (  # noqa: E402
    verify_text_blind_review_bundle,
)
from prooflaunch_remix.v10_submission_store import SubmissionStore  # noqa: E402


MISSION_ROOTS = {
    "b2b": ROOT / "artifacts/aug3-local-first-b2b-mission-v1",
    "b2c": ROOT / "artifacts/aug3-local-first-b2c-mission-v1",
}
DEFAULT_OUTPUT = ROOT / "evidence/v10/gtm-dual-lighthouse-local-mission-v1.json"
SCHEMA = "ProofLaunchGTMDualLighthouseLocalMissionV1"


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SystemExit(f"expected JSON object: {path}")
    return value


def _verify_seal(payload: Mapping[str, Any], *, label: str) -> None:
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if supplied != _digest(unsigned):
        raise SystemExit(f"{label} content seal is invalid")


def _mission_row(scenario: str, root: Path) -> dict[str, Any]:
    receipt_path = root / "mission-receipt.json"
    receipt = _load(receipt_path)
    _verify_seal(receipt, label=f"{scenario} mission receipt")
    if receipt.get("schema") != "ProofLaunchAug3LocalFirstGTMEmployeeMissionV1":
        raise SystemExit(f"{scenario} mission schema drifted")
    if receipt.get("scenario") != scenario:
        raise SystemExit(f"{scenario} mission scenario binding drifted")
    challenger = receipt.get("text_challenger")
    if not isinstance(challenger, Mapping):
        raise SystemExit(f"{scenario} mission lacks text challenger evidence")
    if (
        receipt.get("status")
        != "awaiting_named_human_blind_review_with_critic_contract_failure"
        or receipt.get("graph_loop_harness_executed") is not True
        or receipt.get("human_release_gate_reached") is not True
        or receipt.get("human_release_approved") is not False
        or receipt.get("external_publish_executed") is not False
        or challenger.get("candidate_contract_passed") is not True
        or challenger.get("candidate_count") != 3
        or challenger.get("blind_pair_count") != 6
        or challenger.get("human_review_task_count") != 30
        or challenger.get("critic_contract_failure_degraded_to_human_review_only") is not True
        or challenger.get("critic_contract_failure_treated_as_quality_pass") is not False
        or challenger.get("craft_quality_advisory_passed") is not False
    ):
        raise SystemExit(f"{scenario} mission truth boundary drifted")

    packet_root = root / "local-text-challenger"
    public_path = packet_root / "text-creative-blind-review-public.json"
    private_path = packet_root / "text-creative-blind-review-private.json"
    public = _load(public_path)
    private = _load(private_path)
    verify_text_blind_review_bundle(public, private)
    file_hashes = challenger.get("bundle_file_sha256")
    if not isinstance(file_hashes, Mapping):
        raise SystemExit(f"{scenario} mission bundle hash map is missing")
    for name, expected in file_hashes.items():
        path = packet_root / str(name)
        if not path.is_file() or _file_sha(path) != expected:
            raise SystemExit(f"{scenario} mission bundle file drifted: {name}")
    if (
        public.get("candidate_identity_exposed") is not False
        or public.get("provider_identity_exposed") is not False
        or public.get("blind_review_completed") is not False
        or public.get("winner_selected") is not False
        or public.get("external_publish_executed") is not False
    ):
        raise SystemExit(f"{scenario} public blind packet leaked authority")
    store = SubmissionStore(root / "state")
    if not store.verify_event_chain(str(receipt["run_id"])):
        raise SystemExit(f"{scenario} mission event chain is invalid")
    event_count = len(store.events_after(str(receipt["run_id"]), limit=5000))
    return {
        "scenario": scenario,
        "mission_receipt_path": receipt_path.relative_to(ROOT).as_posix(),
        "mission_receipt_file_sha256": _file_sha(receipt_path),
        "mission_content_sha256": receipt["content_sha256"],
        "run_id": receipt["run_id"],
        "event_chain_verified": True,
        "event_count": event_count,
        "local_model": receipt["local_model"],
        "candidate_count": challenger["candidate_count"],
        "candidate_generation_call_count": challenger["completed_call_count"],
        "craft_critic_call_count": challenger["craft_quality_call_count"],
        "craft_quality_advisory_passed": False,
        "critic_contract_failure_degraded_to_human_review_only": True,
        "critic_contract_failure_treated_as_quality_pass": False,
        "blind_pair_count": public["pair_count"],
        "human_review_task_count": public["review_task_count"],
        "submitted_human_review_count": 0,
        "public_packet_content_sha256": public["content_sha256"],
        "private_mapping_content_sha256": private["content_sha256"],
        "human_release_gate_reached": True,
        "human_release_approved": False,
        "external_publish_executed": False,
    }


def compile_evidence() -> dict[str, Any]:
    rows = [_mission_row(scenario, root) for scenario, root in MISSION_ROOTS.items()]
    model_digests = {row["local_model"]["digest"] for row in rows}
    if len(model_digests) != 1:
        raise SystemExit("dual lighthouse missions did not use one frozen local model")
    payload = {
        "schema": SCHEMA,
        "scenario_count": 2,
        "scenarios": ["b2b", "b2c"],
        "missions": rows,
        "verified_event_chain_count": sum(row["event_chain_verified"] for row in rows),
        "candidate_count": sum(row["candidate_count"] for row in rows),
        "candidate_generation_call_count": sum(row["candidate_generation_call_count"] for row in rows),
        "craft_critic_call_count": sum(row["craft_critic_call_count"] for row in rows),
        "craft_quality_advisory_pass_count": 0,
        "critic_contract_failure_mission_count": 2,
        "critic_contract_failure_treated_as_quality_pass_count": 0,
        "blind_pair_count": sum(row["blind_pair_count"] for row in rows),
        "human_review_task_count": sum(row["human_review_task_count"] for row in rows),
        "submitted_human_review_count": 0,
        "human_release_gate_reached_count": 2,
        "human_release_approved_count": 0,
        "external_publish_executed_count": 0,
        "cloud_api_call_count": 0,
        "radeon_local_inference_observed_count": 0,
        "last_mile_execution_quality_proven": False,
        "named_product_pk_completed_count": 0,
        "production_effect_observed_count": 0,
        "causal_revenue_effect_proven_count": 0,
        "launch_state": "local_dual_mission_ready_for_human_review_quality_unproven",
        "truth_boundary": "This evidence proves two hash-bound local Graph/Loop/Harness missions reached source-hidden human review with six contract-valid candidates. The 1.5B critic contract failed and was not counted as a quality pass. Zero human preferences, releases, named-product wins, production effects or revenue effects are present.",
    }
    payload["content_sha256"] = _digest(payload)
    return payload


def verify_evidence(payload: Mapping[str, Any]) -> None:
    if payload.get("schema") != SCHEMA:
        raise SystemExit("dual lighthouse evidence schema drifted")
    _verify_seal(payload, label="dual lighthouse evidence")
    if (
        payload.get("scenario_count") != 2
        or payload.get("candidate_count") != 6
        or payload.get("blind_pair_count") != 12
        or payload.get("human_review_task_count") != 60
        or payload.get("submitted_human_review_count") != 0
        or payload.get("critic_contract_failure_treated_as_quality_pass_count") != 0
        or payload.get("last_mile_execution_quality_proven") is not False
        or payload.get("external_publish_executed_count") != 0
        or payload.get("named_product_pk_completed_count") != 0
        or payload.get("production_effect_observed_count") != 0
    ):
        raise SystemExit("dual lighthouse evidence truth boundary drifted")


def main() -> None:
    parser = argparse.ArgumentParser(description="Compile B2B+B2C local GTM mission evidence.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = compile_evidence()
    verify_evidence(payload)
    atomic_write_text(args.output.resolve(), json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({
        "output": str(args.output.resolve()),
        "candidate_count": payload["candidate_count"],
        "blind_pair_count": payload["blind_pair_count"],
        "human_review_task_count": payload["human_review_task_count"],
        "submitted_human_review_count": payload["submitted_human_review_count"],
        "content_sha256": payload["content_sha256"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
