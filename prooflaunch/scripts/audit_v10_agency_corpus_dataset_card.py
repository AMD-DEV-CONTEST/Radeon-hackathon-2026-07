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


def main() -> int:
    card_path = ROOT / "data/v10_agency_corpus_v2/dataset-card.json"
    markdown_path = ROOT / "docs/AGENCY_CORPUS_V2_DATASET_CARD.md"
    card = json.loads(card_path.read_text(encoding="utf-8"))
    failures: list[str] = []
    material = dict(card)
    digest = material.pop("card_sha256")
    if digest != stable_sha256(material):
        failures.append("card_content_hash")
    for component in card["components"]:
        path = ROOT / component["manifest_path"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != component["manifest_file_sha256"]:
            failures.append(f"component_hash:{component['name']}")
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if manifest[component["primary_count_key"]] != component["primary_count"]:
            failures.append(f"component_count:{component['name']}")
    expected_counts = {
        "source_records": 2_000,
        "cpt_tokens": 15_000_000,
        "sft_episodes": 15_000,
        "preference_pairs": 5_000,
        "region_preference_pairs": 2_000,
        "visible_trajectories": 1_000,
        "repair_episodes": 500,
        "gold_brief_candidates": 300,
        "gold_campaign_candidates": 150,
        "planned_human_reviews": 2_250,
        "observed_human_reviews": 0,
    }
    if card["headline_counts"] != expected_counts:
        failures.append("headline_counts")
    human = card["human_evaluation"]
    if human["submitted_review_count"] != 0 or human["mean_score"] is not None or human["promotion_passed"]:
        failures.append("human_truth_boundary")
    runtime = card["training_and_runtime"]
    if any(runtime[key] for key in ("training_observed", "adapter_observed", "multi_gpu_observed", "radeon_inference_observed")):
        failures.append("runtime_truth_boundary")
    markdown = markdown_path.read_text(encoding="utf-8")
    for phrase in ("Observed human reviews | 0", "Current human mean is `null`", "not frozen for training promotion", digest):
        if phrase not in markdown:
            failures.append(f"markdown_disclosure:{phrase}")
    report = {
        "schema": "ProofLaunchAgencyCorpusV2DatasetCardAuditV1",
        "status": "passed_published_pre_release_card_not_frozen" if not failures else "failed",
        "component_count": len(card["components"]),
        "headline_counts": card["headline_counts"],
        "all_component_hashes_recomputed": not any(item.startswith("component_hash") for item in failures),
        "human_reviews_observed": human["submitted_review_count"],
        "human_mean_score": human["mean_score"],
        "training_observed": runtime["training_observed"],
        "radeon_inference_observed": runtime["radeon_inference_observed"],
        "corpus_frozen": False,
        "failure_count": len(failures),
        "failures": failures,
        "card_sha256": digest,
        "markdown_sha256": hashlib.sha256(markdown_path.read_bytes()).hexdigest(),
    }
    output = ROOT / "evidence/v10/agency-corpus-v2-dataset-card-audit.json"
    atomic_write_text(output, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
