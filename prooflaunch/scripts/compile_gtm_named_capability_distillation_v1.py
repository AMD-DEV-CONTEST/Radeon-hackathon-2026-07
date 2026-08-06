#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_named_capability_distillation import compile_named_capability_distillation


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "evidence/v10/gtm-concrete-product-effect-pk-ledger-v1.json"
OUTPUT = ROOT / "evidence/v10/gtm-named-capability-distillation-v1.json"


def main() -> None:
    payload = compile_named_capability_distillation(json.loads(SOURCE.read_text(encoding="utf-8")))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(OUTPUT, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "output": str(OUTPUT), "category_count": payload["category_count"],
        "capability_atom_count": payload["capability_atom_count"],
        "completed_named_product_comparison_count": payload["completed_named_product_comparison_count"],
        "content_sha256": payload["content_sha256"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
