#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from prooflaunch_remix.files import atomic_write_text  # noqa: E402


OUTPUT = ROOT / "evidence/v10/local-gtm-creative-effect-audit-v1.json"
CANONICAL_STATUS = ROOT / "evidence/v10/local-gtm-creative-benchmark-status.json"
VERSIONS = (8, 9, 10, 11)
FINAL_VERSION = 11


def canonical(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verified_payload(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    supplied = payload.get("content_sha256")
    unsigned = dict(payload)
    unsigned.pop("content_sha256", None)
    if supplied != digest(unsigned):
        raise SystemExit(f"content digest mismatch: {path.relative_to(ROOT)}")
    return payload


def main() -> int:
    benchmark_rows: list[dict[str, Any]] = []
    source_files: dict[str, str] = {}
    model_digests: set[str] = set()
    for version in VERSIONS:
        receipt_path = (
            ROOT
            / f"artifacts/local-gtm-creative-benchmark-v{version}/benchmark-receipt.json"
        )
        status_path = (
            ROOT / f"evidence/v10/local-gtm-creative-benchmark-status-v{version}.json"
        )
        receipt = verified_payload(receipt_path)
        status = verified_payload(status_path)
        model_digests.add(str(receipt["model"]["digest"]))
        for path in (receipt_path, status_path):
            source_files[path.relative_to(ROOT).as_posix()] = sha256_file(path)
        benchmark_rows.append(
            {
                "version": version,
                "status": status["status"],
                "receipt_content_sha256": receipt["content_sha256"],
                "completed_model_call_count": receipt["completed_model_call_count"],
                "validated_candidate_count": receipt["validated_candidate_count"],
                "scenario_adaptation_passed": receipt["scenario_adaptation_gate"][
                    "passed"
                ],
                "maximum_cross_scenario_pair_jaccard": receipt[
                    "cross_scenario_expression_gate"
                ]["maximum_pair_jaccard"],
                "cross_scenario_expression_passed": receipt[
                    "cross_scenario_expression_gate"
                ]["passed"],
                "human_review_completed": receipt["human_review_completed"],
                "winner_selected": receipt["winner_selected"],
                "cloud_api_calls": receipt["cloud_api_calls"],
                "all_requests_localhost_only": receipt[
                    "all_requests_localhost_only"
                ],
            }
        )

    final_root = ROOT / f"artifacts/local-gtm-creative-benchmark-v{FINAL_VERSION}/cases"
    native_marker_counts: Counter[int] = Counter()
    native_markers: Counter[str] = Counter()
    channel_types: Counter[str] = Counter()
    execution_count = 0
    candidate_count = 0
    all_execution_boundaries_preserved = True
    for execution_path in sorted(
        final_root.glob("*/text-creative-challenger-execution.json")
    ):
        execution = verified_payload(execution_path)
        execution_count += 1
        source_files[execution_path.relative_to(ROOT).as_posix()] = sha256_file(
            execution_path
        )
        candidate_count += int(execution["candidate_count"])
        all_execution_boundaries_preserved = (
            all_execution_boundaries_preserved
            and execution["winner_selected"] is False
            and execution["blind_review_completed"] is False
            and execution["external_publish_executed"] is False
        )
        for row in execution["candidates"]:
            candidate = row["candidate"]
            gate = candidate["creative_quality_gate"]
            native_marker_counts[int(gate["channel_native_marker_count"])] += 1
            native_markers.update(
                str(marker)
                for marker in gate["channel_native_markers"]
                if marker is not None
            )
            channel_types.update(
                str(channel["channel"]) for channel in candidate["channels"]
            )

    by_version = {row["version"]: row for row in benchmark_rows}
    v8_max = float(by_version[8]["maximum_cross_scenario_pair_jaccard"])
    final_max = float(
        by_version[FINAL_VERSION]["maximum_cross_scenario_pair_jaccard"]
    )
    final_gate = {
        "schema": "ProofLaunchLocalCreativeEffectGateV1",
        "expected_case_count": 9,
        "observed_case_count": execution_count,
        "expected_candidate_count": 27,
        "observed_candidate_count": candidate_count,
        "expected_channel_draft_count": 54,
        "observed_channel_draft_count": sum(native_markers.values()),
        "covered_channel_type_count": len(channel_types),
        "channel_types": sorted(channel_types),
        "all_candidates_have_two_native_markers": native_marker_counts == {2: 27},
        "all_four_dimension_scenario_gates_pass": by_version[FINAL_VERSION][
            "scenario_adaptation_passed"
        ],
        "cross_scenario_expression_gate_passed": by_version[FINAL_VERSION][
            "cross_scenario_expression_passed"
        ],
        "maximum_cross_scenario_pair_jaccard": final_max,
        "maximum_allowed_pair_jaccard": 0.72,
        "v8_to_final_jaccard_reduction": round(v8_max - final_max, 6),
        "exact_human_preference_observed": False,
        "all_execution_boundaries_preserved": all_execution_boundaries_preserved,
    }
    final_gate["passed"] = (
        execution_count == 9
        and candidate_count == 27
        and sum(native_markers.values()) == 54
        and len(channel_types) == 12
        and final_gate["all_candidates_have_two_native_markers"]
        and final_gate["all_four_dimension_scenario_gates_pass"]
        and final_gate["cross_scenario_expression_gate_passed"]
        and final_max <= 0.72
        and final_gate["v8_to_final_jaccard_reduction"] > 0
        and all_execution_boundaries_preserved
        and len(model_digests) == 1
        and all(row["all_requests_localhost_only"] for row in benchmark_rows)
        and all(row["cloud_api_calls"] == 0 for row in benchmark_rows)
        and not any(row["human_review_completed"] for row in benchmark_rows)
        and not any(row["winner_selected"] for row in benchmark_rows)
    )
    payload: dict[str, Any] = {
        "schema": "ProofLaunchLocalGTMCreativeEffectAuditV1",
        "status": "passed_mechanical_effect_gates_human_effect_unproven"
        if final_gate["passed"]
        else "failed",
        "model": {
            "provider": "ollama_local",
            "name": "qwen2.5-coder:1.5b",
            "digest": next(iter(model_digests)) if len(model_digests) == 1 else None,
        },
        "improvement_chain": benchmark_rows,
        "final_gate": final_gate,
        "native_marker_distribution": dict(sorted(native_markers.items())),
        "source_file_sha256": dict(sorted(source_files.items())),
        "network_download_performed": False,
        "cloud_api_calls": 0,
        "human_review_completed": False,
        "winner_selected": False,
        "radeon_local_inference_observed": False,
        "truth_boundary": (
            "This audit proves digest-pinned localhost execution, four-dimensional "
            "scenario binding, channel-native marker coverage, and a preregistered "
            "cross-scenario lexical-diversity threshold over eight synthetic cases. "
            "It does not prove human creative preference, 4A quality, production "
            "traffic, lift, virality, conversion, revenue, model training, or Radeon execution."
        ),
    }
    payload["content_sha256"] = digest(payload)
    atomic_write_text(
        OUTPUT,
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    final_status_path = (
        ROOT
        / f"evidence/v10/local-gtm-creative-benchmark-status-v{FINAL_VERSION}.json"
    )
    final_status = verified_payload(final_status_path)
    atomic_write_text(
        CANONICAL_STATUS,
        json.dumps(final_status, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    print(
        json.dumps(
            {
                "output": OUTPUT.relative_to(ROOT).as_posix(),
                "status": payload["status"],
                "maximum_pair_jaccard": final_max,
                "jaccard_reduction": final_gate["v8_to_final_jaccard_reduction"],
                "channel_type_count": len(channel_types),
                "channel_draft_count": sum(native_markers.values()),
            },
            sort_keys=True,
        )
    )
    return 0 if final_gate["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
