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
from prooflaunch_remix.v10_repair_corpus import REPAIR_FAMILIES, build_repair_episode  # noqa: E402


def main() -> int:
    root = ROOT / "data/v10_repair_corpus"
    records = [json.loads(line) for line in (root / "repair-episodes.jsonl").read_text(encoding="utf-8").splitlines() if line]
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    sources = [json.loads(line) for line in (ROOT / manifest["source_path"]).read_text(encoding="utf-8").splitlines() if line]
    failures: list[str] = []
    for index, (record, source) in enumerate(zip(records, sources[:500], strict=True), start=1):
        rebuilt = build_repair_episode(source, index)
        if rebuilt != record:
            failures.append(f"rebuild:{record.get('repair_episode_id', index)}")
        if not record["verification"]["passed"] or record["hidden_chain_of_thought_present"]:
            failures.append(f"contract:{record['repair_episode_id']}")
    observed = {
        "repair_episode_count": len(records),
        "train_count": sum(row["split"] == "train" for row in records),
        "validation_count": sum(row["split"] == "validation" for row in records),
        "failure_family_counts": dict(sorted(Counter(row["failure_family"] for row in records).items())),
        "duplicate_id_count": len(records) - len({row["repair_episode_id"] for row in records}),
        "duplicate_content_count": len(records) - len({row["content_sha256"] for row in records}),
    }
    expected = {
        "repair_episode_count": 500,
        "train_count": 450,
        "validation_count": 50,
        "failure_family_counts": {key: 50 for key in sorted(REPAIR_FAMILIES)},
        "duplicate_id_count": 0,
        "duplicate_content_count": 0,
    }
    for key, value in expected.items():
        if observed[key] != value or manifest.get(key) != value:
            failures.append(f"recount:{key}")
    corpus_path = root / "repair-episodes.jsonl"
    if hashlib.sha256(corpus_path.read_bytes()).hexdigest() != manifest["corpus_sha256"]:
        failures.append("corpus_hash")
    report = {
        "schema": "ProofLaunchRepairEpisodeIndependentAuditV1",
        "status": "passed_exact_500_repair_records_not_training" if not failures else "failed",
        **observed,
        "all_records_independently_reconstructed": not failures,
        "rights_failure_count": sum(not row["rights_verified"] for row in records),
        "hidden_chain_of_thought_count": sum(row["hidden_chain_of_thought_present"] for row in records),
        "teacher_model_used": False,
        "human_reviewed": False,
        "training_observed": False,
        "failure_count": len(failures),
        "failures": failures[:100],
        "manifest_sha256": manifest["manifest_sha256"],
    }
    output = ROOT / "evidence/v10/repair-episodes-500-independent-audit.json"
    atomic_write_text(output, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
