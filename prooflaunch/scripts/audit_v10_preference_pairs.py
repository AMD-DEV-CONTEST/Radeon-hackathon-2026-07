from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from prooflaunch_remix.files import atomic_write_text  # noqa: E402
from prooflaunch_remix.v10_sft_corpus import stable_sha256  # noqa: E402


def main() -> int:
    corpus = ROOT / "data/v10_preference_pairs/pairs.jsonl"
    manifest_path = ROOT / "data/v10_preference_pairs/manifest.json"
    rows = [json.loads(line) for line in corpus.read_text(encoding="utf-8").splitlines() if line]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    errors = Counter(row["preference_reason"] for row in rows)
    failures: list[str] = []
    expected = {
        "pair_count": 5_000,
        "train_count": 4_500,
        "validation_count": 500,
        "test_count": 0,
        "duplicate_pair_id_count": 0,
        "duplicate_content_count": 0,
        "identical_chosen_rejected_count": 0,
        "rights_failure_count": 0,
        "teacher_model_used_count": 0,
        "human_reviewed_count": 0,
        "hidden_reasoning_count": 0,
    }
    observed = {
        "pair_count": len(rows),
        "train_count": sum(row["split"] == "train" for row in rows),
        "validation_count": sum(row["split"] == "validation" for row in rows),
        "test_count": sum(row["split"] == "test" for row in rows),
        "duplicate_pair_id_count": len(rows) - len({row["pair_id"] for row in rows}),
        "duplicate_content_count": len(rows) - len({row["content_sha256"] for row in rows}),
        "identical_chosen_rejected_count": sum(row["chosen"] == row["rejected"] for row in rows),
        "rights_failure_count": sum(not row["rights_verified"] or not row["training_allowed"] for row in rows),
        "teacher_model_used_count": sum(row["teacher_model_used"] for row in rows),
        "human_reviewed_count": sum(row["human_reviewed"] for row in rows),
        "hidden_reasoning_count": sum(row["hidden_reasoning"] for row in rows),
    }
    for key, value in expected.items():
        if observed[key] != value or manifest.get(key) != value:
            failures.append(f"{key}:expected={value}:observed={observed[key]}:manifest={manifest.get(key)}")
    if set(errors.values()) != {1_000} or len(errors) != 5:
        failures.append("error_kind_distribution_not_exact_5x1000")
    if any(stable_sha256({k: v for k, v in row.items() if k != "content_sha256"}) != row["content_sha256"] for row in rows):
        failures.append("record_hash_mismatch")
    corpus_sha = hashlib.sha256(corpus.read_bytes()).hexdigest()
    if corpus_sha != manifest["corpus_content_sha256"]:
        failures.append("corpus_hash_mismatch")
    manifest_material = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    if stable_sha256(manifest_material) != manifest["manifest_sha256"]:
        failures.append("manifest_hash_mismatch")
    report = {
        "schema": "ProofLaunchPreferenceIndependentAuditV1",
        "status": "passed_independent_audit_not_training" if not failures else "failed",
        **observed,
        "error_kind_counts": dict(sorted(errors.items())),
        "stage_count": len({row["stage"] for row in rows}),
        "input_kind_count": len({row["input_kind"] for row in rows}),
        "corpus_content_sha256": corpus_sha,
        "manifest_sha256": manifest["manifest_sha256"],
        "failure_count": len(failures),
        "failures": failures,
        "training_observed": False,
    }
    output = ROOT / "evidence/v10/preference-pairs-5k-independent-audit.json"
    atomic_write_text(output, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
