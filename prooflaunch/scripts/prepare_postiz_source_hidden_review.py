#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from prooflaunch_remix.files import atomic_write_text, sha256_file


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-baselines-v1/pk-1cd7f6ecc915700e/postiz-raw-baseline.json"
OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-pk-postiz-v1/private"


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def hide_provider_tokens(value: Any) -> Any:
    if isinstance(value, list):
        return [hide_provider_tokens(item) for item in value]
    if isinstance(value, dict):
        return {
            key: hide_provider_tokens(item)
            for key, item in value.items()
            if key not in {"reference_product", "provider_version", "postiz_image_digest", "official_compose_revision"}
        }
    if not isinstance(value, str):
        return value
    return (
        value.replace("POSTIZ_", "CHANNEL_")
        .replace("postiz-", "scheduler-")
        .replace("Postiz", "the scheduler")
        .replace("postiz", "scheduler")
    )


def main() -> None:
    if OUTPUT.exists() and any(OUTPUT.iterdir()):
        raise FileExistsError(f"Refusing to overwrite: {OUTPUT}")
    OUTPUT.mkdir(parents=True, mode=0o700, exist_ok=True)
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    if source.get("schema") != "ProofLaunchPostizRawNamedBaselineV1":
        raise SystemExit("baseline schema drifted")
    observations = source["product_observations"]
    review = {
        "schema": "ProofLaunchSourceHiddenSchedulingExecutionRunV1",
        "frozen_task": (
            "Schedule one LinkedIn self-cross-examination, one 15-second vertical demonstration "
            "and one source-ready answer object, with human release and failure recovery."
        ),
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
        "runtime_boundary": {
            "local_only": True,
            "connected_integration_count": source["runtime"]["connected_integration_count"],
            "external_network_calls_during_baseline_execution": 0,
            "external_post_created": False,
            "api_key_persisted": False,
        },
        "authorization_boundary": source["authorization_boundary"],
        "integration_inventory": observations["integrations_inventory"],
        "same_brief_executions": hide_provider_tokens(observations["executions"]),
        "evaluation_boundary": source["evaluation_boundary"],
        "review_instructions": (
            "Judge only the observable schedule, channel-native request shapes, release controls, "
            "failure behavior and disclosed limitations. A blocked local request is not a publication result."
        ),
        "truth_boundary": (
            "This source-hidden artifact records one authorized local scheduler run against the frozen brief. "
            "It is not a human preference result, successful publication, market response, lift, virality, "
            "conversion, revenue or product superiority evidence."
        ),
    }
    review_path = OUTPUT / "review-asset-baseline.json"
    atomic_write_text(review_path, json.dumps(review, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    if "postiz" in review_path.read_text(encoding="utf-8").casefold():
        raise SystemExit("provider identity remained in source-hidden review artifact")
    receipt = {
        "schema": "ProofLaunchSourceHiddenTransformationReceiptV1",
        "source_sha256": sha256_file(SOURCE),
        "review_sha256": sha256_file(review_path),
        "transformation": (
            "remove provider/version labels and replace provider-prefixed template identifiers while "
            "preserving all four frozen request payloads, actual statuses, failure messages and limitations"
        ),
        "semantic_fields_removed": [
            "provider identity",
            "container image digest",
            "official compose revision",
        ],
        "source_roles_exposed": False,
        "content_preserved_except_provider_identity": True,
        "automatic_promotion_enabled": False,
    }
    receipt["content_sha256"] = hashlib.sha256(canonical(receipt)).hexdigest()
    atomic_write_text(
        OUTPUT / "anonymization-receipt.json",
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    print(
        json.dumps(
            {
                "review": str(review_path),
                "sha256": sha256_file(review_path),
                "content_sha256": receipt["content_sha256"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
