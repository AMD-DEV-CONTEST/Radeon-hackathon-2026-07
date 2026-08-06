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


COMPONENTS = (
    ("source_bundle", "data/v10_source_bundle/manifest.json", "source_count"),
    ("cpt", "data/v10_cpt_corpus/manifest.json", "target_tokens"),
    ("sft", "data/v10_sft_corpus/manifest.json", "episode_count"),
    ("preference", "data/v10_preference_pairs/manifest.json", "pair_count"),
    ("region_preference", "data/v10_region_preferences/manifest.json", "pair_count"),
    ("trajectory", "data/v10_agency_trajectories/manifest.json", "trajectory_count"),
    ("repair", "data/v10_repair_corpus/manifest.json", "repair_episode_count"),
    ("gold_candidate", "data/v10_gold_candidates/manifest.json", "brief_candidate_count"),
    ("human_review_packet", "data/v10_gold_human_review/manifest.json", "assignment_count"),
)


def main() -> int:
    components = []
    for name, relative_path, count_key in COMPONENTS:
        path = ROOT / relative_path
        manifest = json.loads(path.read_text(encoding="utf-8"))
        components.append(
            {
                "name": name,
                "manifest_path": relative_path,
                "manifest_file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "manifest_content_sha256": manifest.get("manifest_sha256", manifest.get("content_sha256")),
                "primary_count_key": count_key,
                "primary_count": manifest[count_key],
                "training_observed": bool(manifest.get("training_observed", False)),
                "human_reviewed": bool(manifest.get("human_reviewed", False)),
                "truth_boundary": manifest.get("truth_boundary"),
            }
        )
    human_gate_path = ROOT / "evidence/v10/gold-five-human-review-gate.json"
    human_gate = json.loads(human_gate_path.read_text(encoding="utf-8"))
    card = {
        "schema": "ProofLaunchAgencyCorpusV2DatasetCard",
        "card_version": "2.0.0-pre-human-gold",
        "publication_status": "published_local_pre_release",
        "dataset_name": "ProofLaunch Agency Corpus V2",
        "language": ["en"],
        "modalities": ["text_metadata", "image_assets", "visible_agent_trajectories"],
        "components": components,
        "headline_counts": {
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
            "observed_human_reviews": human_gate["submitted_review_count"],
        },
        "intended_uses": [
            "rights-aware continued pretraining experiments after a separate runtime gate",
            "source-bound GTM instruction tuning and visible trajectory research",
            "contract-negative preference and repair training",
            "held-out human evaluation after five independent reviewers complete the sealed packet",
        ],
        "out_of_scope_uses": [
            "training on provider output without explicit output-training rights",
            "copying public agency campaigns or protected creative assets",
            "autonomous publication, ad spend, outreach, or legal approval",
            "using pre-review candidates as evidence of 4A quality or business lift",
            "claiming Radeon execution or adapter quality from corpus construction",
        ],
        "rights_and_provenance": {
            "asset_level_source_records": True,
            "source_revisions_and_identity_hashes": True,
            "provider_concentration_gate": 0.40,
            "trademark_hold_is_fail_closed": True,
            "provider_model_outputs_in_training_set": False,
            "public_4a_campaign_assets_in_training_set": False,
            "legal_advice_provided": False,
        },
        "privacy_and_safety": {
            "private_personal_data_intentionally_collected": False,
            "hidden_chain_of_thought_allowed": False,
            "external_side_effect_examples_positive": False,
            "human_approval_required_for_external_actions": True,
            "unobserved_media_payloads_must_remain_unknown": True,
        },
        "splits_and_leakage": {
            "sft_train_validation": [13_500, 1_500],
            "trajectory_train_validation": [900, 100],
            "repair_train_validation": [450, 50],
            "group_isolation_required": True,
            "gold_candidates_held_out_until_review": True,
            "benchmark_and_prompt_leakage_scans": "mechanical_contract_present",
        },
        "known_limitations": [
            "Most multimodal SFT records bind metadata but do not materialize or inspect media payloads.",
            "Region preferences are entropy/edge/exposure crops, not teacher or human aesthetics.",
            "Gold candidates are structurally complete but have zero observed human reviews.",
            "No completed training run, adapter, multi-GPU receipt, Radeon inference receipt, or downstream uplift is represented.",
            "English-first coverage is not evidence of global cultural or market quality.",
        ],
        "human_evaluation": {
            "gate_path": human_gate_path.relative_to(ROOT).as_posix(),
            "gate_file_sha256": hashlib.sha256(human_gate_path.read_bytes()).hexdigest(),
            "status": human_gate["status"],
            "submitted_review_count": human_gate["submitted_review_count"],
            "expected_review_count": human_gate["expected_review_count"],
            "mean_score": human_gate["mean_score"],
            "promotion_passed": human_gate["promotion_passed"],
        },
        "training_and_runtime": {
            "corpus_construction_observed": True,
            "training_observed": False,
            "adapter_observed": False,
            "multi_gpu_observed": False,
            "radeon_inference_observed": False,
            "competition_core_eligibility_decided": False,
        },
        "maintenance": {
            "immutable_component_hashes": True,
            "deletion_and_opt_out_supported_by_supply_chain_contract": True,
            "new_component_requires_card_revision": True,
            "freeze_requires_human_gold_and_runtime_gates": True,
        },
        "citation": "ProofLaunch Agency Corpus V2, pre-human-gold local release, 2026-07-31.",
        "truth_boundary": "Publication of this Dataset Card proves disclosure and component binding, not final corpus promotion, training, 4A quality, five-person review, or Radeon execution.",
    }
    card["card_sha256"] = stable_sha256(card)
    json_path = ROOT / "data/v10_agency_corpus_v2/dataset-card.json"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(json_path, json.dumps(card, ensure_ascii=False, indent=2) + "\n")

    counts = card["headline_counts"]
    markdown = f"""# ProofLaunch Agency Corpus V2 — Dataset Card

Version: `2.0.0-pre-human-gold`  
Status: **Published locally as a pre-release; not frozen for training promotion.**

## What is actually present

| Component | Observed count |
|---|---:|
| Rights-bound source records | {counts['source_records']:,} |
| CPT tokens | {counts['cpt_tokens']:,} |
| SFT episodes | {counts['sft_episodes']:,} |
| Contract-negative preference pairs | {counts['preference_pairs']:,} |
| Mechanical region preference pairs | {counts['region_preference_pairs']:,} |
| Visible source-bound trajectories | {counts['visible_trajectories']:,} |
| Repair episodes | {counts['repair_episodes']:,} |
| Gold brief candidates | {counts['gold_brief_candidates']:,} |
| Gold campaign candidates | {counts['gold_campaign_candidates']:,} |
| Planned five-person reviews | {counts['planned_human_reviews']:,} |
| Observed human reviews | {counts['observed_human_reviews']:,} |

## Promotion boundary

The 300 briefs and 150 campaigns are candidates only. Five independent human reviewers must complete all 2,250 assignments. Promotion requires overall mean >= 4.7, every dimension mean >= 4.5, publishable rate >= 95%, exact case/hash binding, and no imputed ratings. Current human mean is `null`.

## Rights and provenance

Every admitted training record is source- and revision-bound. Trademark holds fail closed. Provider model outputs and public 4A campaign assets are excluded from the training corpus unless separate output/asset rights are proven. This card is not legal advice.

## Intended use

- rights-aware CPT/SFT and visible trajectory research after separate runtime admission;
- source-bound GTM instruction, preference, and repair experiments;
- held-out five-person evaluation after the review packet is completed.

## Prohibited or unsupported use

- copying protected agency work, autonomous publication/spend/outreach, or claims of 4A/business parity;
- treating metadata-only multimodal examples as observed image/audio/video content;
- claiming training, adapter lift, multi-GPU performance, or Radeon execution from these files.

## Known limitations

- Media payloads are unobserved in most SFT records.
- Region preferences are mechanical crop scores, not aesthetic judgments.
- Human review count is zero; rendered 4K quality and business outcomes are unobserved.
- Coverage is English-first and does not establish global cultural adequacy.

## Reproducibility

The machine-readable card at `data/v10_agency_corpus_v2/dataset-card.json` binds every component manifest, the five-human review gate, counts, limitations, and SHA-256 values. Card SHA-256: `{card['card_sha256']}`.

## Truth boundary

{card['truth_boundary']}
"""
    atomic_write_text(ROOT / "docs/AGENCY_CORPUS_V2_DATASET_CARD.md", markdown)
    print(json.dumps({"status": "dataset_card_published_local_pre_release", "card_sha256": card["card_sha256"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
