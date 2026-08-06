#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_seven_case_batch_admission_v2 import compile_seven_case_batch_admission, verify_seven_case_batch_admission


ROOT = Path(__file__).resolve().parents[1]
SPECS = (("EmailOctopus", "emailoctopus"), ("Buffer", "buffer"), ("Flodesk", "flodesk"), ("Post Bridge", "postbridge"), ("Parqet", "parqet"), ("Spendbase", "spendbase"), ("Barn2", "barn2"))


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def main() -> int:
    parser = argparse.ArgumentParser(description="Atomically admit seven named-reviewed 10/11 GTM cases.")
    parser.add_argument("--intake", type=Path, required=True)
    parser.add_argument("--registry", type=Path, default=ROOT / "data/gtm_case_funnel_v2/admitted-candidates.json")
    parser.add_argument("--receipt", type=Path, default=ROOT / "evidence/v10/gtm-seven-case-batch-admission-v2.json")
    args = parser.parse_args()
    if args.registry.exists():
        registry = _load(args.registry); unsigned = dict(registry); supplied = unsigned.pop("content_sha256", None)
        if registry.get("schema") != "ProofLaunchGTMAdmittedCandidateRegistryV2" or supplied != _digest(unsigned):
            raise SystemExit("admitted candidate registry seal is invalid")
    else:
        registry = {"schema": "ProofLaunchGTMAdmittedCandidateRegistryV2", "candidate_count": 0, "formal_candidate_quota_credit": 0, "candidates": []}
    ledger = _load(ROOT / "evidence/v10/gtm-all-subvertical-unified-review-ledger-v2.json")
    dossiers = {company: _load(ROOT / f"evidence/v10/gtm-{slug}-admission-dossier-v2.json") for company, slug in SPECS}
    proposals = {company: _load(ROOT / f"evidence/v10/gtm-{slug}-named-review-proposal-v2.json") for company, slug in SPECS}
    batch = compile_seven_case_batch_admission(_load(args.intake), ledger, dossiers, proposals, registry["candidates"])
    verify_seven_case_batch_admission(batch)
    candidates = [*registry["candidates"], *(row["candidate"] for row in batch["admissions"])]
    updated = {"schema": "ProofLaunchGTMAdmittedCandidateRegistryV2", "candidate_count": len(candidates), "formal_candidate_quota_credit": sum(row.get("quota_credit") == 1 for row in candidates), "candidates": candidates}
    updated["content_sha256"] = _digest(updated)
    args.registry.parent.mkdir(parents=True, exist_ok=True); args.receipt.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(args.registry, json.dumps(updated, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    atomic_write_text(args.receipt, json.dumps(batch, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"receipt": str(args.receipt), "registry": str(args.registry), "newly_admitted": 7, "formal_candidate_quota_credit": updated["formal_candidate_quota_credit"], "reviewer_names": batch["reviewer_names"]}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
