#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_final_acceptance_matrix_v2 import compile_final_acceptance_matrix, verify_final_acceptance_matrix


ROOT = Path(__file__).resolve().parents[1]


def load(relative: str) -> dict:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def main() -> int:
    payload = compile_final_acceptance_matrix(
        load("evidence/v10/gtm-case-evidence-funnel-v2/coverage.json"),
        load("evidence/v10/gtm-named-product-pk-live-status-v1.json"),
        load("evidence/v10/gtm-lifecycle-closure-matrix-v1.json"),
        load("evidence/v10/gtm-100-todo-execution-ledger-v2.json"),
        production_gold_stress_pass_count=0,
        traceable_claim_count=0,
        total_claim_count=0,
    )
    verify_final_acceptance_matrix(payload)
    output = ROOT / "evidence/v10/gtm-final-acceptance-matrix-v2.json"
    atomic_write_text(output, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(output), "passed_gate_count": payload["passed_gate_count"], "required_gate_count": payload["required_gate_count"], "final_release_allowed": payload["final_release_allowed"], "content_sha256": payload["content_sha256"]}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__": raise SystemExit(main())
