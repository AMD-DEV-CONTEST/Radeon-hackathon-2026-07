from __future__ import annotations

import hashlib
import json
from pathlib import Path

from prooflaunch_remix.top1_4a_training_gate import (
    Top1FourATrainingContract,
    UpstreamDataSource,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "config" / "cortex_x_v10_top1_4a_training_gate.json"


def source(
    source_id: str,
    repository: str,
    revision: str,
    license_id: str,
    permitted_use: str,
    mechanism: str,
    truth_boundary: str,
) -> UpstreamDataSource:
    return UpstreamDataSource(
        source_id=source_id,
        repository_url=f"https://github.com/{repository}",
        revision=revision,
        declared_data_license=license_id,
        permitted_use=permitted_use,
        asset_level_rights_verified=False,
        commercial_training_allowed=False,
        mechanism_to_reuse=mechanism,
        truth_boundary=truth_boundary,
    )


SOURCES = (
    source(
        "dolma",
        "allenai/dolma",
        "669f534823b08d266a8fff01f8a1c916a5a56576",
        "ODC-By dataset; Apache-2.0 toolkit",
        "method_only",
        "high-throughput tagging, mixing, filtering and deduplication",
        "Web-source rights remain asset-specific; reuse curation machinery only.",
    ),
    source(
        "fineweb-2",
        "huggingface/fineweb-2",
        "d0defb24f193bb9a5a11b8b14524a03c4858e1b6",
        "ODC-By dataset; Apache-2.0 code",
        "method_only",
        "multilingual data-quality filtering and reproducible ablations",
        "ODC-By metadata does not waive underlying page rights.",
    ),
    source(
        "dclm",
        "mlfoundations/dclm",
        "361714bdd60bb9b7f4b2d8354cebbf0dec0c329e",
        "MIT code; raw-pool rights are source-specific",
        "method_only",
        "reference JSON lineage, controlled data recipes and broad evaluation",
        "Use the competition methodology, not unreviewed Common Crawl assets.",
    ),
    source(
        "datatrove",
        "huggingface/datatrove",
        "5987417f95605cce581454fcff22305b3165bb3e",
        "Apache-2.0 code; input data licenses are independent",
        "method_only",
        "distributed filtering, exact/near deduplication and dataset statistics",
        "Tool license never grants rights to processed source content.",
    ),
    source(
        "llava-next",
        "LLaVA-VL/LLaVA-NeXT",
        "bce12e479bc4dfee2b9c50c88137b01ff51bd483",
        "Repository license plus component-specific data licenses",
        "method_only",
        "single/multi-image/video curriculum and global-batch invariance",
        "Composite training mixtures require per-component rights review.",
    ),
    source(
        "llava-onevision-2",
        "EvolvingLMMs-Lab/LLaVA-OneVision-1.5",
        "587797d9f495e380abd137d40923704f4844899c",
        "Repository and component-specific licenses",
        "method_only",
        "long-video, codec, spatial and tracking curriculum design",
        "Public release does not make every upstream asset commercial-training safe.",
    ),
    source(
        "q-instruct",
        "Q-Future/Q-Instruct",
        "2a78134356b829da873ceb905542dead1efa8f6c",
        "commercial use requires prior permission",
        "evaluation_only",
        "low-level visual quality tasks and perceptual degradation taxonomy",
        "No commercial training use without written permission.",
    ),
    source(
        "vila",
        "NVlabs/VILA",
        "0f1426e8da9181e6e6653e10bc15f62d515fa2f6",
        "Repository plus model/component-specific licenses",
        "method_only",
        "interleaved image-text and video instruction curriculum",
        "MMC4, COYO and instruction mixtures require independent rights checks.",
    ),
    source(
        "open-assistant",
        "LAION-AI/Open-Assistant",
        "f1e6ed9526f5817531f3ab85441a40b3671ddccb",
        "Repository/data terms require frozen dataset-card review",
        "method_only",
        "human preference trees, ranking and refusal/repair trajectories",
        "Conversation and model-output rights must be approved per release.",
    ),
    source(
        "osworld",
        "xlang-ai/OSWorld",
        "091f5ef1d5544bc74953c77875d5feb5bed30108",
        "Repository and task-asset specific terms",
        "evaluation_only",
        "real-computer agent evaluation and state-grounded task receipts",
        "Keep sealed for evaluation; never train on benchmark tasks.",
    ),
    source(
        "browsergym",
        "ServiceNow/BrowserGym",
        "9e779f087de9a65668b6974d11f9ce9816026e96",
        "Repository and benchmark-specific licenses",
        "evaluation_only",
        "browser-agent harness, action traces and reproducible environment control",
        "Benchmark tasks remain sealed; reuse harness interfaces only.",
    ),
    source(
        "crmarena",
        "SalesforceAIResearch/CRMArena",
        "a37d882c3a947f0330a907f513b90a7f08b9c532",
        "Repository and benchmark-specific terms",
        "evaluation_only",
        "CRM/GTM agent tasks, business state and outcome-oriented evaluation",
        "Use as a sealed GTM evaluation reference, not training material.",
    ),
)


def main() -> None:
    for item in SOURCES:
        failures = item.audit()
        if failures:
            raise SystemExit("; ".join(failures))
    payload = {
        "contract": Top1FourATrainingContract().to_dict(),
        "upstream_sources": [
            {
                **item.__dict__,
                "training_eligible_now": (
                    item.permitted_use == "training_candidate"
                    and item.asset_level_rights_verified
                    and item.commercial_training_allowed
                ),
            }
            for item in SOURCES
        ],
        "reference_cohort": {
            "agency_count": 10,
            "selection_policy": (
                "North-American agencies selected from date-pinned WARC Creative "
                "100, WARC Effective 100, One Show and Cannes Lions evidence; "
                "conflicts disclosed and campaign assets evaluation-only."
            ),
            "minimum_campaigns_per_agency": 30,
            "minimum_channels_per_agency": 5,
            "minimum_blind_comparisons_per_agency": 150,
            "claim_policy": (
                "Top-1 is forbidden until every agency clears pairwise "
                "non-inferiority and the pooled Wilson lower 95% exceeds 0.60."
            ),
        },
        "training_admission": {
            "default": "blocked",
            "current_reason": (
                "No asset-level rights-approved GTM training corpus or real "
                "multi-GPU Radeon evidence has been sealed."
            ),
            "teacher_corpus_training_eligible": False,
            "single_gpu_may_promote": False,
        },
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    payload["contract_sha256"] = hashlib.sha256(canonical).hexdigest()
    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(OUTPUT)


if __name__ == "__main__":
    main()

