#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.gtm_emailoctopus_candidate_admission_v2 import (
    compile_emailoctopus_candidate_admission,
    verify_emailoctopus_candidate_admission,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = ROOT / "data/gtm_case_funnel_v2/admitted-candidates.json"
DEFAULT_RECEIPT = ROOT / "evidence/v10/gtm-emailoctopus-case-candidate-admission-v2.json"


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _registry(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema": "ProofLaunchGTMAdmittedCandidateRegistryV2",
            "candidate_count": 0,
            "formal_candidate_quota_credit": 0,
            "candidates": [],
        }
    payload = _load(path)
    unsigned = dict(payload)
    supplied = unsigned.pop("content_sha256", None)
    if supplied != _digest(unsigned) or payload.get("schema") != "ProofLaunchGTMAdmittedCandidateRegistryV2":
        raise SystemExit("admitted candidate registry seal is invalid")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Strictly admit one named-reviewed EmailOctopus CaseCandidateV2 episode.")
    parser.add_argument("--intake", type=Path, required=True, help="Downloaded named-review intake JSON")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    args = parser.parse_args()
    registry = _registry(args.registry)
    admission = compile_emailoctopus_candidate_admission(
        _load(args.intake),
        _load(ROOT / "evidence/v10/gtm-all-subvertical-unified-review-ledger-v2.json"),
        _load(ROOT / "evidence/v10/gtm-emailoctopus-admission-dossier-v2.json"),
        _load(ROOT / "evidence/v10/gtm-emailoctopus-named-review-proposal-v2.json"),
        registry["candidates"],
    )
    verify_emailoctopus_candidate_admission(admission)
    candidates = [*registry["candidates"], admission["candidate"]]
    updated = {
        "schema": "ProofLaunchGTMAdmittedCandidateRegistryV2",
        "candidate_count": len(candidates),
        "formal_candidate_quota_credit": sum(int(row.get("quota_credit") == 1) for row in candidates),
        "candidates": candidates,
    }
    updated["content_sha256"] = _digest(updated)
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.registry.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(args.receipt, json.dumps(admission, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    atomic_write_text(args.registry, json.dumps(updated, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({
        "receipt": str(args.receipt),
        "registry": str(args.registry),
        "admitted_candidate_count": 1,
        "formal_candidate_quota_credit": updated["formal_candidate_quota_credit"],
        "reviewer_name": admission["reviewer_name"],
        "content_sha256": admission["content_sha256"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
