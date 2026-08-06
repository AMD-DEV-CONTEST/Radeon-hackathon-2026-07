#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_case_collection_orchestrator_v2 import (
    compile_case_collection_orchestrator,
    verify_case_collection_orchestrator,
)


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    standard = json.loads((ROOT / "evidence/v10/gtm-case-evidence-funnel-v2/standard.json").read_text(encoding="utf-8"))
    coverage = json.loads((ROOT / "evidence/v10/gtm-case-evidence-funnel-v2/coverage.json").read_text(encoding="utf-8"))
    oss = json.loads((ROOT / "evidence/v10/gtm-social-oss-adapter-landscape-v5.json").read_text(encoding="utf-8"))
    payload = compile_case_collection_orchestrator(standard, coverage, oss)
    verify_case_collection_orchestrator(payload)
    output = ROOT / "evidence/v10/gtm-case-collection-orchestrator-v2.json"
    atomic_write_text(output, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "output": str(output), "workstream_count": payload["workstream_count"], "case_slot_count": payload["case_slot_count"],
        "collection_job_count": payload["collection_job_count"], "wave_slot_counts": payload["wave_slot_counts"],
        "wave_job_counts": payload["wave_job_counts"], "content_sha256": payload["content_sha256"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
