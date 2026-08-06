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
from prooflaunch_remix.v10_sft_corpus import SFTEpisode, stable_sha256, verify_sft_summary  # noqa: E402


def main() -> int:
    corpus_path = ROOT / "data/v10_sft_corpus/episodes.jsonl"
    manifest_path = ROOT / "data/v10_sft_corpus/manifest.json"
    rows = [json.loads(line) for line in corpus_path.read_text(encoding="utf-8").splitlines() if line]
    failures: list[str] = []
    for index, row in enumerate(rows):
        try:
            SFTEpisode(**row)
        except Exception as error:
            failures.append(f"row_{index}:{error}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    try:
        verify_sft_summary(manifest)
    except Exception as error:
        failures.append(f"manifest:{error}")
    stage_counts = Counter(row["stage"] for row in rows)
    input_counts = Counter(row["input_kind"] for row in rows)
    split_counts = Counter(row["split"] for row in rows)
    checks = {
        "episode_count": len(rows),
        "train_count": split_counts["train"],
        "validation_count": split_counts["validation"],
        "test_split_count": split_counts["test"],
        "stage_counts": dict(sorted(stage_counts.items())),
        "input_counts": dict(sorted(input_counts.items())),
        "duplicate_episode_count": len(rows) - len({row["episode_id"] for row in rows}),
        "duplicate_content_count": len(rows) - len({row["content_sha256"] for row in rows}),
        "rights_failure_count": sum(not row["rights_verified"] or not row["training_allowed"] for row in rows),
        "model_generated_count": sum(row["model_generated"] for row in rows),
        "hidden_reasoning_count": sum(row["hidden_reasoning"] for row in rows),
        "external_side_effect_count": sum(row["external_side_effect"] for row in rows),
    }
    for key, value in checks.items():
        if key in manifest and manifest[key] != value:
            failures.append(f"manifest_recount_mismatch:{key}")
    corpus_sha = hashlib.sha256(corpus_path.read_bytes()).hexdigest()
    if corpus_sha != manifest["corpus_content_sha256"]:
        failures.append("corpus_hash_mismatch")
    manifest_material = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    if stable_sha256(manifest_material) != manifest["manifest_sha256"]:
        failures.append("manifest_hash_mismatch")
    report = {
        "schema": "ProofLaunchSFTIndependentAuditV1",
        "status": "passed_independent_audit_not_training" if not failures else "failed",
        **checks,
        "maximum_provider_share": manifest["maximum_provider_share"],
        "all_records_revalidated": not failures,
        "corpus_content_sha256": corpus_sha,
        "manifest_sha256": manifest["manifest_sha256"],
        "failure_count": len(failures),
        "failures": failures,
        "training_observed": False,
        "adapter_observed": False,
    }
    output = ROOT / "evidence/v10/sft-corpus-15k-independent-audit.json"
    atomic_write_text(output, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
