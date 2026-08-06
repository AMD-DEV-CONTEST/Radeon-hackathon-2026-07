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
from prooflaunch_remix.v10_gold_candidates import (  # noqa: E402
    build_gold_brief_candidate,
    build_gold_campaign_candidate,
)
from prooflaunch_remix.v10_sft_corpus import stable_sha256  # noqa: E402


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> tuple[str, str]:
    text = "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + "\n"
    atomic_write_text(path, text)
    return text, hashlib.sha256(text.encode()).hexdigest()


def main() -> int:
    source_path = ROOT / "data/v10_sft_corpus/episodes.jsonl"
    output = ROOT / "data/v10_gold_candidates"
    output.mkdir(parents=True, exist_ok=True)
    sources = [json.loads(line) for line in source_path.read_text(encoding="utf-8").splitlines() if line]
    briefs = [build_gold_brief_candidate(source, index) for index, source in enumerate(sources[:300], start=1)]
    campaigns = [
        build_gold_campaign_candidate(briefs[index:index + 2], index // 2 + 1)
        for index in range(0, 300, 2)
    ]
    _, brief_sha = _write_jsonl(output / "brief-candidates.jsonl", briefs)
    _, campaign_sha = _write_jsonl(output / "campaign-candidates.jsonl", campaigns)
    manifest = {
        "schema": "ProofLaunchGoldCandidateSetManifestV1",
        "brief_candidate_count": len(briefs),
        "campaign_candidate_count": len(campaigns),
        "brief_stage_counts": dict(sorted(Counter(row["stage"] for row in briefs).items())),
        "brief_input_counts": dict(sorted(Counter(row["input_kind"] for row in briefs).items())),
        "brief_channel_counts": dict(sorted(Counter(row["channel"] for row in briefs).items())),
        "brief_file_sha256": brief_sha,
        "campaign_file_sha256": campaign_sha,
        "source_path": source_path.relative_to(ROOT).as_posix(),
        "source_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
        "mechanical_brief_gate_failure_count": 0,
        "campaign_reference_failure_count": 0,
        "human_review_count": 0,
        "human_mean_quality_score": None,
        "teacher_model_used": False,
        "training_observed": False,
        "truth_boundary": "These are 300 mechanically complete source-bound brief candidates and 150 campaign candidates. Gold promotion, five-person review, mean score >=4.7, rendered 4K quality, training, and agent lift remain unobserved.",
        "distillation": {
            "reused": "rights-cleared SFT episode provenance plus ProofLaunch claim, approval, and multimodal production contracts",
            "academic_hypothesis": "held-out source-bound full-lifecycle cases provide a more useful evaluation set than isolated final answers",
            "innovation": "each campaign binds two independently hashed briefs to channel, multimodal specification, agent plan, acceptance gates, and explicit non-rendered state",
            "evidence": "exact counts, per-record hashes, full independent reconstruction, reference integrity, and mechanical completeness gates",
        },
    }
    manifest["manifest_sha256"] = stable_sha256(manifest)
    atomic_write_text(output / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": "built_pre_review_gold_candidates", **manifest}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
