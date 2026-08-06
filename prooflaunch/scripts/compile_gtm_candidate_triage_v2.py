#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_candidate_triage_v2 import compile_candidate_triage, verify_candidate_triage


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    corpus = json.loads((ROOT / "data/gtm_case_funnel_v2/candidates.json").read_text(encoding="utf-8"))
    standard = json.loads((ROOT / "evidence/v10/gtm-case-evidence-funnel-v2/standard.json").read_text(encoding="utf-8"))
    payload = compile_candidate_triage(
        corpus["candidates"],
        subvertical_ids=[row["subvertical_id"] for row in standard["subverticals"]],
    )
    verify_candidate_triage(payload)
    output = ROOT / "evidence/v10/gtm-candidate-triage-v2.json"
    atomic_write_text(output, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "output": str(output),
        "candidate_score_count": payload["candidate_score_count"],
        "subvertical_count": payload["subvertical_count"],
        "ready_subvertical_count": payload["ready_subvertical_count"],
        "content_sha256": payload["content_sha256"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
