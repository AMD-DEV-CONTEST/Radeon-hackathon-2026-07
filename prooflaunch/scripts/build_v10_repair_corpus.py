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
from prooflaunch_remix.v10_repair_corpus import build_repair_episode  # noqa: E402
from prooflaunch_remix.v10_sft_corpus import stable_sha256  # noqa: E402


def main() -> int:
    source_path = ROOT / "data/v10_sft_corpus/episodes.jsonl"
    output = ROOT / "data/v10_repair_corpus"
    output.mkdir(parents=True, exist_ok=True)
    sources = [json.loads(line) for line in source_path.read_text(encoding="utf-8").splitlines() if line]
    records = [build_repair_episode(source, index) for index, source in enumerate(sources[:500], start=1)]
    text = "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in records) + "\n"
    atomic_write_text(output / "repair-episodes.jsonl", text)
    manifest = {
        "schema": "ProofLaunchRepairEpisodeCorpusManifestV1",
        "repair_episode_count": len(records),
        "train_count": sum(row["split"] == "train" for row in records),
        "validation_count": sum(row["split"] == "validation" for row in records),
        "failure_family_counts": dict(sorted(Counter(row["failure_family"] for row in records).items())),
        "stage_counts": dict(sorted(Counter(row["stage"] for row in records).items())),
        "input_counts": dict(sorted(Counter(row["input_kind"] for row in records).items())),
        "source_path": source_path.relative_to(ROOT).as_posix(),
        "source_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
        "corpus_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "duplicate_id_count": len(records) - len({row["repair_episode_id"] for row in records}),
        "duplicate_content_count": len(records) - len({row["content_sha256"] for row in records}),
        "rights_failure_count": 0,
        "hidden_chain_of_thought_count": 0,
        "teacher_model_used": False,
        "human_reviewed": False,
        "training_observed": False,
        "distillation": {
            "reused": "the first 500 immutable rights-cleared SFT episodes and their stage-required completions",
            "academic_hypothesis": "explicit fault localization followed by minimal verified repair should outperform undifferentiated clean-only imitation on recovery behavior",
            "innovation": "ten balanced GTM contract failures are represented as counterfactual codes without copying forbidden content or hidden reasoning",
            "evidence": "source/content hashes, exact 450/50 split, per-family balance, and independent reconstruction audit",
        },
        "truth_boundary": "This proves 500 deterministic repair training records; it does not prove model-generated critiques, human gold review, training, or improved recovery rate.",
    }
    manifest["manifest_sha256"] = stable_sha256(manifest)
    atomic_write_text(output / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": "built_exact_500_repair_episodes", **manifest}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
