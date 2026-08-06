from __future__ import annotations

import hashlib
import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text, sha256_file


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-baselines-v1/pk-a4c174c3c49ad019/mem0-raw-baseline.json"
OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-pk-mem0-v2/private"


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def main() -> None:
    if OUTPUT.exists() and any(OUTPUT.iterdir()):
        raise FileExistsError(f"Refusing to overwrite: {OUTPUT}")
    OUTPUT.mkdir(parents=True, mode=0o700)
    payload = json.loads(SOURCE.read_text(encoding="utf-8"))
    if payload.get("schema") != "ProofLaunchMem0NamedProductRawRunV1":
        raise SystemExit("baseline schema drifted")
    payload["schema"] = "ProofLaunchSourceHiddenMemoryExecutionRunV1"
    review = OUTPUT / "review-asset-baseline.json"
    atomic_write_text(review, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    if "mem0" in review.read_text(encoding="utf-8").casefold():
        raise SystemExit("provider identity remained in source-hidden review artifact")
    receipt = {
        "schema": "ProofLaunchSourceHiddenTransformationReceiptV1",
        "source_sha256": sha256_file(SOURCE),
        "review_sha256": sha256_file(review),
        "transformation": "replace_provider_identifying_top_level_schema_only",
        "semantic_fields_removed": [],
        "source_roles_exposed": False,
        "content_preserved_except_provider_identity": True,
        "automatic_promotion_enabled": False,
    }
    receipt["content_sha256"] = hashlib.sha256(canonical(receipt)).hexdigest()
    atomic_write_text(OUTPUT / "anonymization-receipt.json", json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"review": str(review), "sha256": sha256_file(review), "content_sha256": receipt["content_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
