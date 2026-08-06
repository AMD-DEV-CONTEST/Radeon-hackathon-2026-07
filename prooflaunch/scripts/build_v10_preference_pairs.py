from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from prooflaunch_remix.files import atomic_write_text  # noqa: E402
from prooflaunch_remix.v10_sft_corpus import stable_sha256  # noqa: E402


TARGET_PAIRS = 5_000
ERROR_KINDS = (
    "unsupported_outcome_claim",
    "required_output_omitted",
    "unapproved_external_action",
    "unobserved_modality_inference",
    "evidence_source_substitution",
)


def _corrupt(completion: dict[str, Any], error_kind: str) -> dict[str, Any]:
    rejected = copy.deepcopy(completion)
    outputs = rejected["outputs"]
    first_key = next(iter(outputs))
    if error_kind == "unsupported_outcome_claim":
        outputs[first_key] = "Guaranteed 80% revenue lift with no uncertainty."
    elif error_kind == "required_output_omitted":
        outputs.pop(first_key)
    elif error_kind == "unapproved_external_action":
        rejected["decision"] = "published_and_sent_without_approval"
        rejected["requires_human_approval_for_external_action"] = False
    elif error_kind == "unobserved_modality_inference":
        rejected["modality_payload_observed"] = True
        rejected["fabricated_visual_observation"] = "The unseen asset is a blue premium product ad."
    elif error_kind == "evidence_source_substitution":
        rejected["evidence_source_ids"] = ["unverified-external-source"]
    else:
        raise ValueError(error_kind)
    return rejected


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="data/v10_preference_pairs")
    args = parser.parse_args()
    output = ROOT / args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    episodes_path = ROOT / "data/v10_sft_corpus/episodes.jsonl"
    episodes = [
        json.loads(line)
        for line in episodes_path.read_text(encoding="utf-8").splitlines()
        if line
    ][:TARGET_PAIRS]
    if len(episodes) != TARGET_PAIRS:
        raise RuntimeError("15K SFT corpus must exist before preference construction")

    pairs: list[dict[str, Any]] = []
    for index, episode in enumerate(episodes):
        error_kind = ERROR_KINDS[index % len(ERROR_KINDS)]
        chosen = episode["completion"]
        rejected = _corrupt(chosen, error_kind)
        material = {
            "schema": "ProofLaunchPreferencePairV1",
            "pair_id": f"preference-{index + 1:05d}",
            "source_episode_id": episode["episode_id"],
            "scenario_family_id": episode["scenario_family_id"],
            "split": episode["split"],
            "stage": episode["stage"],
            "input_kind": episode["input_kind"],
            "system_prompt": episode["system_prompt"],
            "user_prompt": episode["user_prompt"],
            "chosen": chosen,
            "rejected": rejected,
            "preference_reason": error_kind,
            "rejected_error_codes": [error_kind],
            "source_ids": episode["source_ids"],
            "source_revisions": episode["source_revisions"],
            "source_identity_sha256s": episode["source_identity_sha256s"],
            "rights_verified": episode["rights_verified"],
            "training_allowed": episode["training_allowed"],
            "chosen_verified_by_mechanical_contract": True,
            "teacher_model_used": False,
            "human_reviewed": False,
            "hidden_reasoning": False,
        }
        material["content_sha256"] = stable_sha256(material)
        pairs.append(material)

    lines = [json.dumps(row, ensure_ascii=False, sort_keys=True) for row in pairs]
    text = "\n".join(lines) + "\n"
    atomic_write_text(output / "pairs.jsonl", text)
    splits = Counter(row["split"] for row in pairs)
    errors = Counter(row["preference_reason"] for row in pairs)
    stages = Counter(row["stage"] for row in pairs)
    inputs = Counter(row["input_kind"] for row in pairs)
    manifest = {
        "schema": "ProofLaunchPreferenceCorpusV1",
        "pair_count": len(pairs),
        "train_count": splits["train"],
        "validation_count": splits["validation"],
        "test_count": 0,
        "error_kind_counts": dict(sorted(errors.items())),
        "stage_counts": dict(sorted(stages.items())),
        "input_counts": dict(sorted(inputs.items())),
        "duplicate_pair_id_count": len(pairs) - len({row["pair_id"] for row in pairs}),
        "duplicate_content_count": len(pairs) - len({row["content_sha256"] for row in pairs}),
        "identical_chosen_rejected_count": sum(row["chosen"] == row["rejected"] for row in pairs),
        "rights_failure_count": sum(not row["rights_verified"] or not row["training_allowed"] for row in pairs),
        "teacher_model_used_count": 0,
        "human_reviewed_count": 0,
        "hidden_reasoning_count": 0,
        "sft_corpus_sha256": hashlib.sha256(episodes_path.read_bytes()).hexdigest(),
        "corpus_content_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "training_observed": False,
        "truth_boundary": (
            "These are deterministic contract-negative preference pairs, not teacher-ranked or human-ranked preferences. "
            "They prove count, provenance, and negative-control coverage only."
        ),
    }
    material = dict(manifest)
    manifest["manifest_sha256"] = stable_sha256(material)
    atomic_write_text(output / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": "passed_pair_construction_not_training", **manifest}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
