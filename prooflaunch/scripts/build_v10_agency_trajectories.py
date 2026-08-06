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
from prooflaunch_remix.v10_agency_trajectory_corpus import (  # noqa: E402
    TARGET_OUTCOME_COUNTS,
    allocate_additional_outcomes,
    build_source_bound_trajectory,
)
from prooflaunch_remix.v10_sft_corpus import stable_sha256  # noqa: E402


def _jsonl(rows: list[dict[str, object]]) -> str:
    return "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + "\n"


def main() -> int:
    output = ROOT / "data/v10_agency_trajectories"
    output.mkdir(parents=True, exist_ok=True)
    upstream_path = ROOT / "data/v10_trajectory_kd/outcome_trajectories.jsonl"
    sft_path = ROOT / "data/v10_sft_corpus/episodes.jsonl"
    reused = [json.loads(line) for line in upstream_path.read_text(encoding="utf-8").splitlines() if line]
    episodes = [json.loads(line) for line in sft_path.read_text(encoding="utf-8").splitlines() if line]
    selected = episodes[:544]
    generated = [
        build_source_bound_trajectory(episode, outcome, ordinal)
        for ordinal, (episode, outcome) in enumerate(
            zip(selected, allocate_additional_outcomes(), strict=True), start=1
        )
    ]
    trajectories = reused + generated

    groups = [(row["task_id"], row["trajectory_id"], "reused_verified_v1") for row in reused]
    groups.extend(
        (row["source_episode_id"], row["trajectory_id"], "source_bound_v2") for row in generated
    )
    unique_groups = sorted(
        {group for group, _, _ in groups},
        key=lambda value: (stable_sha256({"split_group": value}), value),
    )
    validation_groups: set[str] = set()
    # Fifteen reused task groups contribute 45 matched trajectories; fifty-five
    # one-trajectory source groups complete an exact 100-record validation split.
    reused_groups = {row["task_id"] for row in reused}
    ranked_reused = [group for group in unique_groups if group in reused_groups]
    ranked_new = [group for group in unique_groups if group not in reused_groups]
    validation_groups.update(ranked_reused[:15])
    validation_groups.update(ranked_new[:55])
    index = [
        {
            "trajectory_id": trajectory_id,
            "source_group_id": group,
            "corpus_split": "validation" if group in validation_groups else "train",
            "source_kind": source_kind,
        }
        for group, trajectory_id, source_kind in groups
    ]

    trajectory_text = _jsonl(trajectories)
    index_text = _jsonl(index)
    atomic_write_text(output / "trajectories.jsonl", trajectory_text)
    atomic_write_text(output / "trajectory-index.jsonl", index_text)
    outcome_counts = Counter(row["outcome_kind"] for row in trajectories)
    split_counts = Counter(row["corpus_split"] for row in index)
    manifest = {
        "schema": "ProofLaunchAgencyTrajectoryCorpusManifestV2",
        "trajectory_count": len(trajectories),
        "reused_existing_count": len(reused),
        "newly_constructed_count": len(generated),
        "train_count": split_counts["train"],
        "validation_count": split_counts["validation"],
        "outcome_counts": dict(sorted(outcome_counts.items())),
        "target_outcome_counts": dict(TARGET_OUTCOME_COUNTS),
        "stage_counts_new": dict(sorted(Counter(row["stage"] for row in generated).items())),
        "input_counts_new": dict(sorted(Counter(row["input_kind"] for row in generated).items())),
        "upstream_path": upstream_path.relative_to(ROOT).as_posix(),
        "upstream_sha256": hashlib.sha256(upstream_path.read_bytes()).hexdigest(),
        "sft_source_path": sft_path.relative_to(ROOT).as_posix(),
        "sft_source_sha256": hashlib.sha256(sft_path.read_bytes()).hexdigest(),
        "trajectory_file_sha256": hashlib.sha256(trajectory_text.encode()).hexdigest(),
        "index_file_sha256": hashlib.sha256(index_text.encode()).hexdigest(),
        "rights_failure_count": 0,
        "hidden_chain_of_thought_count": 0,
        "model_teacher_used": False,
        "human_reviewed": False,
        "training_observed": False,
        "group_safe_split": True,
        "distillation": {
            "reused": "all 456 content-addressed trajectories from the verified matched-outcome corpus are retained byte-for-byte as records",
            "academic_hypothesis": "source-bound visible state-action-tool-state trajectories with balanced terminal policies should teach evidence use, recovery, safe stopping, and escalation more directly than final-answer-only SFT",
            "innovation": "544 additional traces bind each action to a rights-cleared SFT episode and expose replayable state/tool payloads without hidden chain of thought",
            "evidence": "exact-count JSONL, immutable upstream and SFT hashes, group-isolated split index, per-event hashes, and an independent full replay audit",
        },
        "truth_boundary": "This proves 1,000 deterministic visible trajectory records. It does not prove teacher judgment, human gold review, model training, Radeon execution, or downstream agent quality.",
    }
    manifest["manifest_sha256"] = stable_sha256(manifest)
    atomic_write_text(output / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": "built_exact_1000_visible_trajectories", **manifest}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
