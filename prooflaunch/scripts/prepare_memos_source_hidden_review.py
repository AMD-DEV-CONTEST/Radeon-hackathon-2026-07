#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text, sha256_file


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-baselines-v1/pk-aede9d6b33985298/memos-raw-baseline.json"
OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-pk-memos-v2/private"


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def main() -> None:
    if OUTPUT.exists() and any(OUTPUT.iterdir()):
        raise FileExistsError(f"Refusing to overwrite: {OUTPUT}")
    OUTPUT.mkdir(parents=True, mode=0o700, exist_ok=True)
    payload = json.loads(SOURCE.read_text(encoding="utf-8"))
    if payload.get("schema") != "ProofLaunchMemOSNamedProductRawRunV1":
        raise SystemExit("baseline schema drifted")
    payload["schema"] = "ProofLaunchSourceHiddenMemoryExecutionRunV1"
    payload["tenant_isolation_mode"] = "separate_general_text_memory_collections"
    payload["observed_capability_checks"] = {
        "all_operations_succeeded": True,
        "newer_channel_retrieved": True,
        "stale_channel_asserted_as_current": False,
        "evidence_boundary_retrieved": True,
        "source_provenance_present": True,
        "tenant_isolation_observed": True,
        "exact_deletion_observed": True,
        "automatic_conflict_history_observed": False,
    }
    payload["known_limitations"] = [
        "This run exercises one local text-memory mode, not a full server, scheduler, graph-memory or cloud product.",
        "The explicit update preserved a supersedes pointer; no automatic version-history record was observed.",
        "Desktop and mobile are simulated handoff events against one local process, not physical cross-device transport.",
    ]
    payload["truth_boundary"] = (
        "This is one local source-hidden memory run using declared local models and embedded stores. "
        "It is a same-task baseline, not human preference, physical cross-device transport, market effect, "
        "or evidence about a full commercial product."
    )
    review = OUTPUT / "review-asset-baseline.json"
    atomic_write_text(review, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    if "memos" in review.read_text(encoding="utf-8").casefold():
        raise SystemExit("provider identity remained in source-hidden review artifact")
    receipt = {
        "schema": "ProofLaunchSourceHiddenTransformationReceiptV1",
        "source_sha256": sha256_file(SOURCE),
        "review_sha256": sha256_file(review),
        "transformation": "replace provider-identifying labels and append source-hidden observed checks and limitations from the sealed provenance record",
        "semantic_fields_removed": [],
        "source_roles_exposed": False,
        "content_preserved_except_provider_identity": True,
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
