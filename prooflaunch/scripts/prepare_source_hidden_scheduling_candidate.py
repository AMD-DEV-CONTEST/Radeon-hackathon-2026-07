#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from prooflaunch_remix.files import atomic_write_text, sha256_file


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "artifacts/gtm-last-mile-pk-v1/postiz-dry-run-native-preview-v1/postiz-dry-run-requests.json"
OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/scheduling-source-hidden-candidate-v1"


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def hide_adapter_tokens(value: Any) -> Any:
    if isinstance(value, list):
        return [hide_adapter_tokens(item) for item in value]
    if isinstance(value, dict):
        return {
            ("scheduler_request" if key == "postiz_request" else key): hide_adapter_tokens(item)
            for key, item in value.items()
            if key not in {"adapter"}
        }
    if not isinstance(value, str):
        return value
    return (
        value.replace("POSTIZ_", "CHANNEL_")
        .replace("postiz-", "scheduler-")
        .replace("Postiz", "the scheduler")
        .replace("postiz", "scheduler")
        .replace("ProofLaunch Cortex-X", "The system")
        .replace("prooflaunch", "source-hidden-demo")
        .replace("ProofLaunch", "The system")
    )


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    target = OUTPUT / "scheduling-execution.json"
    receipt_path = OUTPUT / "receipt.json"
    if target.exists() or receipt_path.exists():
        raise FileExistsError(f"Refusing to overwrite: {OUTPUT}")
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    requests = source.get("requests")
    if not isinstance(requests, list) or len(requests) != 4:
        raise SystemExit("scheduling source drifted")
    normalized = hide_adapter_tokens(requests)
    artifact = {
        "schema": "SourceHiddenSameBriefSchedulingDeliveryV1",
        "frozen_task": (
            "Schedule one LinkedIn self-cross-examination, one 15-second vertical demonstration "
            "and one source-ready answer object, with human release and failure recovery."
        ),
        "campaign_thesis": (
            "One unsupported outcome claim is cross-examined on every surface. Each asset asks the audience "
            "to run the same five-witness test; no surface claims market effect."
        ),
        "timezone": source.get("timezone"),
        "quality_axes": [
            "native preview",
            "timezone correctness",
            "dependency planning",
            "approvals",
            "failure recovery",
            "frequency caps",
            "best-time evidence",
            "cross-network analytics",
        ],
        "schedule_delivery": normalized,
        "frequency_cap": {
            "maximum_campaign_posts_per_day": 1,
            "minimum_gap_hours": 24,
            "same_platform_repeat_gap_hours": 96,
            "stop_on_negative_or_ambiguous_release_signal": True,
        },
        "failure_recovery": {
            "unresolved_integration": "block release; retain draft and owner-visible error",
            "unresolved_media_url": "block video or carousel release; do not degrade to a broken post",
            "missing_named_human_approval": "keep request local and pending",
            "null_market_result": "publish no victory claim; retain the stop receipt",
        },
        "observed_evidence": {
            "native_preview_compiled": True,
            "timezone_explicit": True,
            "dependencies_declared": True,
            "named_human_approval_observed": False,
            "external_activation_executed": False,
            "best_time_evidence_observed": False,
            "cross_network_analytics_observed": False,
            "market_response_observed": False,
        },
        "review_instructions": (
            "Judge the schedule and request shapes as one delivery. Do not infer publication, preference, "
            "virality, conversion or revenue from a compiled dry run."
        ),
        "truth_boundary": (
            "This is a source-hidden local scheduling delivery with no external activation and no human result. "
            "It is not a product victory or market-effect claim."
        ),
    }
    artifact["content_sha256"] = hashlib.sha256(canonical(artifact)).hexdigest()
    atomic_write_text(target, json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    lowered = target.read_text(encoding="utf-8").casefold()
    if any(term in lowered for term in ("postiz", "prooflaunch", "challenger", "candidate")):
        raise SystemExit("source role or provider identity remained in scheduling review artifact")
    receipt = {
        "schema": "ProofLaunchSourceHiddenTransformationReceiptV1",
        "source_sha256": sha256_file(SOURCE),
        "review_sha256": sha256_file(target),
        "content_preserved_except_adapter_and_source_role_identity": True,
        "automatic_publish_enabled": False,
        "human_review_observed": False,
    }
    receipt["content_sha256"] = hashlib.sha256(canonical(receipt)).hexdigest()
    atomic_write_text(receipt_path, json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"artifact": str(target), "sha256": sha256_file(target)}, sort_keys=True))


if __name__ == "__main__":
    main()
