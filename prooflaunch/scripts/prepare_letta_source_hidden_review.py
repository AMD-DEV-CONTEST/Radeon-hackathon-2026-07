#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from prooflaunch_remix.files import atomic_write_text, sha256_file


SOURCE = ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-baselines-v1/pk-4e714c707f0c49b3/letta-raw-baseline.json"
OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-pk-letta-v1/private"


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def by_name(payload: dict[str, Any], name: str) -> dict[str, Any]:
    return next(row for row in payload["operations"] if row["operation"] == name)


def assistant_text(operation: dict[str, Any]) -> str:
    messages = (operation.get("result") or {}).get("messages") or []
    return "\n".join(
        str(message.get("content") or message.get("text") or "")
        for message in messages
        if isinstance(message, dict)
    )


def block_projection(operation: dict[str, Any]) -> dict[str, Any]:
    result = operation.get("result") or {}
    return {
        "ok": operation["ok"],
        "elapsed_ms": operation["elapsed_ms"],
        "value": result.get("value"),
        "metadata": result.get("metadata"),
        "label": result.get("label"),
        "read_only": result.get("read_only"),
    }


def main() -> None:
    if OUTPUT.exists() and any(OUTPUT.iterdir()):
        raise FileExistsError(f"Refusing to overwrite: {OUTPUT}")
    OUTPUT.mkdir(parents=True, mode=0o700, exist_ok=True)
    payload = json.loads(SOURCE.read_text(encoding="utf-8"))
    if payload.get("schema") != "ProofLaunchLettaNamedProductRawRunV1":
        raise SystemExit("baseline schema drifted")

    read_before = by_name(payload, "mobile_read_before_update")
    update = by_name(payload, "mobile_explicit_approved_update")
    current_block = by_name(payload, "desktop_retrieve_block_after_mobile_update")
    answer = by_name(payload, "desktop_answer_after_mobile_update")
    tenant_b_answer = by_name(payload, "tenant_b_isolation_query")
    delete = by_name(payload, "delete_tenant_a_agent_exactly")
    missing = by_name(payload, "tenant_a_agent_404_after_delete")
    tenant_b_block = by_name(payload, "tenant_b_block_survives_tenant_a_delete")
    review_payload = {
        "schema": "ProofLaunchSourceHiddenMemoryExecutionRunV1",
        "task": payload["task"],
        "frozen_task": payload["frozen_task"],
        "requests": payload["requests"],
        "observations": [
            {
                "operation": "mobile_read_before_update",
                "ok": read_before["ok"],
                "elapsed_ms": read_before["elapsed_ms"],
                "assistant_output": assistant_text(read_before),
            },
            {
                "operation": "mobile_explicit_approved_update",
                "ok": update["ok"],
                "elapsed_ms": update["elapsed_ms"],
                "updated_block": block_projection(update),
            },
            {
                "operation": "desktop_retrieve_block_after_mobile_update",
                **block_projection(current_block),
            },
            {
                "operation": "desktop_answer_after_mobile_update",
                "ok": answer["ok"],
                "elapsed_ms": answer["elapsed_ms"],
                "assistant_output": assistant_text(answer),
                "usage": (answer.get("result") or {}).get("usage"),
            },
            {
                "operation": "tenant_b_isolation_query",
                "ok": tenant_b_answer["ok"],
                "elapsed_ms": tenant_b_answer["elapsed_ms"],
                "assistant_output": assistant_text(tenant_b_answer),
            },
            {
                "operation": "delete_tenant_a_exactly",
                "ok": delete["ok"],
                "elapsed_ms": delete["elapsed_ms"],
                "result": delete.get("result"),
            },
            {
                "operation": "tenant_a_missing_after_delete",
                "ok": missing["ok"],
                "elapsed_ms": missing["elapsed_ms"],
                "observed_status_code": missing.get("observed_status_code"),
                "expected_status_code": missing.get("expected_status_code"),
            },
            {
                "operation": "tenant_b_memory_survives_tenant_a_delete",
                **block_projection(tenant_b_block),
            },
        ],
        "evaluation": payload["evaluation"],
        "conflict_resolution_mode": payload["conflict_resolution_mode"],
        "raw_product_output_projected_without_quality_editing": True,
        "truth_boundary": (
            "Provider identity, model catalog, internal tool definitions and non-evaluative agent configuration were removed. "
            "Current memory values, provenance, model answers, tenant result, deletion status and declared evaluation booleans remain unchanged."
        ),
    }
    review = OUTPUT / "review-asset-baseline.json"
    atomic_write_text(review, json.dumps(review_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    review_text = review.read_text(encoding="utf-8").casefold()
    for forbidden in ("letta", "memgpt"):
        if forbidden in review_text:
            raise SystemExit(f"provider identity remained in source-hidden review artifact: {forbidden}")
    receipt = {
        "schema": "ProofLaunchSourceHiddenTransformationReceiptV1",
        "source_sha256": sha256_file(SOURCE),
        "review_sha256": sha256_file(review),
        "transformation": "project_evaluable_memory_operations_and_remove_provider_identifying_runtime_fields",
        "semantic_fields_removed": [],
        "non_quality_fields_removed": [
            "provider model catalogs",
            "provider and model handles",
            "internal tool definitions",
            "internal agent configuration",
            "provider-identifying top-level schema",
        ],
        "source_roles_exposed": False,
        "content_preserved_except_provider_identity_and_non_quality_runtime_detail": True,
        "automatic_promotion_enabled": False,
    }
    receipt["content_sha256"] = hashlib.sha256(canonical(receipt)).hexdigest()
    atomic_write_text(
        OUTPUT / "anonymization-receipt.json",
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    print(json.dumps({
        "review": str(review),
        "sha256": sha256_file(review),
        "content_sha256": receipt["content_sha256"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
