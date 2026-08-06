#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_postbridge_candidate_admission_v2 import compile_postbridge_candidate_admission, verify_postbridge_candidate_admission


ROOT = Path(__file__).resolve().parents[1]


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def main() -> int:
    parser = argparse.ArgumentParser(description="Strictly admit one named-reviewed Post Bridge CaseCandidateV2 episode.")
    parser.add_argument("--intake", type=Path, required=True)
    parser.add_argument("--registry", type=Path, default=ROOT / "data/gtm_case_funnel_v2/admitted-candidates.json")
    parser.add_argument("--receipt", type=Path, default=ROOT / "evidence/v10/gtm-postbridge-case-candidate-admission-v2.json")
    args = parser.parse_args()
    if args.registry.exists():
        registry = _load(args.registry)
        unsigned = dict(registry)
        supplied = unsigned.pop("content_sha256", None)
        if registry.get("schema") != "ProofLaunchGTMAdmittedCandidateRegistryV2" or supplied != _digest(unsigned):
            raise SystemExit("admitted candidate registry seal is invalid")
    else:
        registry = {"schema": "ProofLaunchGTMAdmittedCandidateRegistryV2", "candidate_count": 0, "formal_candidate_quota_credit": 0, "candidates": []}
    admission = compile_postbridge_candidate_admission(_load(args.intake), _load(ROOT / "evidence/v10/gtm-all-subvertical-unified-review-ledger-v2.json"), _load(ROOT / "evidence/v10/gtm-postbridge-admission-dossier-v2.json"), _load(ROOT / "evidence/v10/gtm-postbridge-named-review-proposal-v2.json"), registry["candidates"])
    verify_postbridge_candidate_admission(admission)
    candidates = [*registry["candidates"], admission["candidate"]]
    updated = {"schema": "ProofLaunchGTMAdmittedCandidateRegistryV2", "candidate_count": len(candidates), "formal_candidate_quota_credit": sum(row.get("quota_credit") == 1 for row in candidates), "candidates": candidates}
    updated["content_sha256"] = _digest(updated)
    args.registry.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(args.registry, json.dumps(updated, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    atomic_write_text(args.receipt, json.dumps(admission, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"receipt": str(args.receipt), "registry": str(args.registry), "formal_candidate_quota_credit": updated["formal_candidate_quota_credit"], "reviewer_name": admission["reviewer_name"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
