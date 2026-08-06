#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text, sha256_file
from prooflaunch_remix.v10_submission_flows import build_flow_preflight


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "evidence/v10/submission-flow-preflight.json"


def main() -> int:
    report = build_flow_preflight()
    atomic_write_text(OUTPUT, json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(OUTPUT), "sha256": sha256_file(OUTPUT), "canonical_complete_count": 0}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
