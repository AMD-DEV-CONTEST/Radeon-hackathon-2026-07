from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from prooflaunch_remix.files import atomic_write_text  # noqa: E402
from prooflaunch_remix.v10_sft_corpus import stable_sha256  # noqa: E402


REQUIRED_AUDITS = (
    ("cpt", "evidence/v10/cpt-corpus-independent-recount.json", "passed_independent_recount_not_training"),
    ("sft", "evidence/v10/sft-corpus-15k-independent-audit.json", "passed_independent_audit_not_training"),
    ("preference", "evidence/v10/preference-pairs-5k-independent-audit.json", "passed_independent_audit_not_training"),
    ("region", "evidence/v10/region-preferences-2k-independent-audit.json", "passed_independent_recount_not_training"),
    ("trajectory", "evidence/v10/agency-trajectories-1000-independent-replay.json", "passed_exact_1000_visible_replay_not_training"),
    ("repair", "evidence/v10/repair-episodes-500-independent-audit.json", "passed_exact_500_repair_records_not_training"),
    ("gold_candidates", "evidence/v10/gold-candidates-independent-audit.json", "passed_pre_review_candidates_not_human_gold"),
    ("dataset_card", "evidence/v10/agency-corpus-v2-dataset-card-audit.json", "passed_published_pre_release_card_not_frozen"),
)


def main() -> int:
    output_dir = ROOT / "data/v10_agency_corpus_v2"
    output_dir.mkdir(parents=True, exist_ok=True)
    audit_rows = []
    blockers: list[str] = []
    for name, relative_path, expected_status in REQUIRED_AUDITS:
        path = ROOT / relative_path
        report = json.loads(path.read_text(encoding="utf-8"))
        passed = report.get("status") == expected_status and report.get("failure_count", 0) == 0
        audit_rows.append(
            {
                "name": name,
                "path": relative_path,
                "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "status": report.get("status"),
                "passed": passed,
            }
        )
        if not passed:
            blockers.append(f"audit:{name}")
    human_path = ROOT / "evidence/v10/gold-five-human-review-gate.json"
    human = json.loads(human_path.read_text(encoding="utf-8"))
    human_requirements = {
        "five_distinct_human_reviewers": human.get("reviewer_identity_count") == 5,
        "all_2250_reviews_complete": human.get("submitted_review_count") == 2_250,
        "all_450_cases_complete": human.get("completed_case_count") == 450,
        "mean_at_least_4_7": isinstance(human.get("mean_score"), (int, float)) and human["mean_score"] >= 4.7,
        "human_promotion_passed": human.get("promotion_passed") is True,
    }
    blockers.extend(name for name, passed in human_requirements.items() if not passed)
    frozen = not blockers
    gate = {
        "schema": "ProofLaunchAgencyCorpusV2FreezeGateV1",
        "status": "passed_agency_corpus_v2_frozen" if frozen else "not_frozen_pending_required_evidence",
        "frozen": frozen,
        "component_audits": audit_rows,
        "human_review_path": human_path.relative_to(ROOT).as_posix(),
        "human_review_file_sha256": hashlib.sha256(human_path.read_bytes()).hexdigest(),
        "human_requirements": human_requirements,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "training_observed": False,
        "radeon_inference_observed": False,
        "truth_boundary": "Agency Corpus V2 freezes only after every component audit and the complete five-human Gold gate pass; missing reviews cannot be waived by code or model ratings.",
    }
    gate["gate_sha256"] = stable_sha256(gate)
    atomic_write_text(output_dir / "freeze-gate.json", json.dumps(gate, ensure_ascii=False, indent=2) + "\n")
    freeze_manifest = output_dir / "freeze-manifest.json"
    if frozen:
        manifest = {
            "schema": "ProofLaunchAgencyCorpusV2FrozenManifestV1",
            "version": "2.0.0",
            "freeze_gate_sha256": gate["gate_sha256"],
            "component_audits": audit_rows,
            "human_review_file_sha256": gate["human_review_file_sha256"],
            "training_observed": False,
            "radeon_inference_observed": False,
        }
        manifest["manifest_sha256"] = stable_sha256(manifest)
        atomic_write_text(freeze_manifest, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    elif freeze_manifest.exists():
        raise RuntimeError("stale freeze manifest exists while fail-closed gate is open")
    print(json.dumps(gate, ensure_ascii=False))
    return 0 if frozen else 2


if __name__ == "__main__":
    raise SystemExit(main())
