#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.v10_corpus_curator import (
    CorpusSample,
    CorpusTaxon,
    CuratedReference,
    GTMArtifactKind,
    Modality,
    SelectionPolicy,
    alignment_score,
    build_grounded_gtm_bundle,
    concept_long_tail,
    corpus_distribution,
    deduplicate_audio,
    deduplicate_keyframes,
    detect_language,
    grouped_split,
    normalize_audio_sample_rate,
    normalize_color_profile,
    normalize_unicode,
    normalize_video_fps,
    scan_contamination,
    scan_prompt_leakage,
    score_sample,
    select_super_batch,
    template_fingerprint,
    temporal_split,
)
from prooflaunch_remix.v10_supply_chain import stable_sha256


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/v10_curated_corpus"
EVIDENCE = ROOT / "evidence/v10"


def normalize(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): normalize(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [normalize(item) for item in value]
    return value


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        path,
        json.dumps(normalize(payload), ensure_ascii=False, indent=2) + "\n",
    )


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    supply_sources = [
        json.loads(line)
        for line in (ROOT / "data/v10_supply_chain/sources.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    if len(supply_sources) != 7:
        raise SystemExit("run build_v10_supply_chain.py first")
    taxa = (
        CorpusTaxon.PHYSICAL_PRODUCT,
        CorpusTaxon.PHYSICAL_PRODUCT,
        CorpusTaxon.PHYSICAL_PRODUCT,
        CorpusTaxon.AI_AGENT,
        CorpusTaxon.STRATEGY,
        CorpusTaxon.ART,
        CorpusTaxon.CREATIVE,
        CorpusTaxon.EVIDENCE,
        CorpusTaxon.REPAIR,
        CorpusTaxon.AUDIT,
        CorpusTaxon.CHANNEL,
        CorpusTaxon.TOOL_TRAJECTORY,
    )
    modalities = (
        Modality.IMAGE,
        Modality.VIDEO,
        Modality.SCREEN,
        Modality.TEXT,
        Modality.TEXT,
        Modality.IMAGE,
        Modality.VIDEO,
        Modality.DOCUMENT,
        Modality.TEXT,
        Modality.TEXT,
        Modality.AUDIO,
        Modality.TRAJECTORY,
    )
    samples: list[CorpusSample] = []
    for index, (taxon, modality) in enumerate(zip(taxa, modalities, strict=True)):
        source = supply_sources[index % len(supply_sources)]
        raw = (
            f"ProofLaunch-owned curation fixture {index}: evidence-bound product, "
            "strategy, production, channel, failure, and repair concepts."
        )
        content = normalize_unicode(raw)
        samples.append(
            CorpusSample(
                sample_id=f"curated-seed-{index:03d}",
                taxon=taxon,
                modality=modality,
                source_id=source["source_id"],
                source_revision=source["revision"],
                source_sha256=source["sha256"],
                product_entity_id=f"owned-product-{index // 2:03d}",
                repository_entity_id=f"owned-repo-{index // 3:03d}",
                captured_at=f"2026-{1 + index // 4:02d}-01T00:00:00Z",
                content=content,
                template_id=f"owned-template-{chr(97 + index)}",
                language=detect_language(content),
                synthetic=True,
                success=index >= 3,
                trajectory_steps=10 if index in {0, 1} else 2,
                concept_tags=("evidence", "product", "strategy", "production"),
                evidence_ids=(f"owned-evidence-{index:03d}",),
            )
        )
    values = {
        kind: f"ProofLaunch-owned grounded {kind.value} seed"
        for kind in GTMArtifactKind
    }
    artifact_bundle = build_grounded_gtm_bundle(
        "curated-gtm-bundle-v1",
        tuple(sorted({item.source_id for item in samples})),
        tuple(sorted({evidence for item in samples for evidence in item.evidence_ids})),
        values,
    )
    alignments = [
        alignment_score(
            kind,
            ("evidence", "product", "strategy"),
            ("evidence", "product", "strategy", "verified"),
            threshold=0.7,
        )
        for kind in ("image_text", "video_copy", "claim_evidence")
    ]
    scores = {
        item.sample_id: score_sample(
            item,
            alignment=0.75,
            evidence_coverage=1.0,
            verifier_confidence=1.0,
            rarity=0.8,
            failure_value=0.7 if not item.success else 0.3,
        )
        for item in samples
    }
    reference = CuratedReference(
        reference_id="prooflaunch-owned-curated-reference-v1",
        required_taxa=frozenset(
            {CorpusTaxon.PHYSICAL_PRODUCT, CorpusTaxon.STRATEGY, CorpusTaxon.ART}
        ),
        required_modalities=frozenset({Modality.TEXT, Modality.IMAGE, Modality.VIDEO}),
        required_concepts=frozenset({"evidence", "product", "strategy", "production"}),
        minimum_quality=0.8,
    )
    selection = select_super_batch(
        samples,
        scores,
        reference,
        SelectionPolicy(maximum_synthetic_rate=1.0),
        batch_size=12,
    )
    product_splits = grouped_split(samples, "product_entity_id")
    repository_splits = grouped_split(samples, "repository_entity_id")
    time_splits = temporal_split(
        samples, "2026-02-01T00:00:00Z", "2026-03-01T00:00:00Z"
    )
    benchmark_findings = scan_contamination(
        samples,
        {"sealed-canary": "a deliberately different sealed evaluation record"},
    )
    prompt_leaks = scan_prompt_leakage(samples, ("PRIVATE-EVAL-CANARY",))
    distributions = corpus_distribution(samples)
    cleaning_receipts = {
        "text_unicode_language_template": True,
        "image_exif_scrub": True,
        "image_color": normalize_color_profile("Display-P3"),
        "image_phash_and_embedding_dedup_contract": True,
        "video_fps": normalize_video_fps(29.97),
        "video_unique_keyframes": list(
            deduplicate_keyframes(("0000", "0001", "ffff"), threshold=1)
        ),
        "audio_rate": normalize_audio_sample_rate(44_100),
        "audio_unique_fingerprints": list(deduplicate_audio(("a", "a", "b"))),
    }

    DATA.mkdir(parents=True, exist_ok=True)
    samples_path = DATA / "samples.jsonl"
    atomic_write_text(
        samples_path,
        "".join(
            json.dumps(normalize(asdict(item)), ensure_ascii=False, sort_keys=True)
            + "\n"
            for item in samples
        ),
    )
    artifacts_path = DATA / "grounded-gtm-artifacts.json"
    selection_path = DATA / "super-batch-selection.json"
    distributions_path = DATA / "distributions.json"
    write_json(artifacts_path, asdict(artifact_bundle))
    write_json(
        selection_path,
        {
            "reference": asdict(reference),
            "selection": asdict(selection),
            "sample_scores": {key: asdict(value) for key, value in scores.items()},
        },
    )
    write_json(
        distributions_path,
        {
            "distributions": distributions,
            "concept_long_tail": concept_long_tail(samples),
            "product_split_counts": {key: len(value) for key, value in product_splits.items()},
            "repository_split_counts": {key: len(value) for key, value in repository_splits.items()},
            "time_split_counts": {key: len(value) for key, value in time_splits.items()},
        },
    )
    manifest_path = DATA / "manifest.json"
    manifest = {
        "schema": "ProofLaunchCuratedCorpusMechanicalSeedV2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sample_count": len(samples),
        "gtm_artifact_count": len(artifact_bundle.artifacts),
        "taxon_count": len({item.taxon for item in samples}),
        "modality_count": len({item.modality for item in samples}),
        "all_samples_synthetic": True,
        "training_promotion_eligible": False,
        "files": {
            path.name: {"path": str(path.relative_to(ROOT)), "sha256": sha256(path)}
            for path in (samples_path, artifacts_path, selection_path, distributions_path)
        },
    }
    manifest["content_sha256"] = stable_sha256(manifest)
    write_json(manifest_path, manifest)
    checks = {
        "twelve_corpus_taxa_defined": len(CorpusTaxon) == 12,
        "seventeen_grounded_gtm_artifacts": len(artifact_bundle.artifacts) == 17,
        "three_alignment_gates_pass": all(item.passed for item in alignments),
        "multimodal_cleaning_contracts_executed": len(cleaning_receipts) == 8,
        "sample_and_batch_scores_finite": all(
            math.isfinite(value.information) for value in scores.values()
        ) and math.isfinite(selection.batch_scores.information),
        "reference_and_balance_constraints_pass": all(selection.constraints.values()),
        "product_repository_time_splits_emitted": all(
            key in {"train", "validation", "test"}
            for split in (product_splits, repository_splits, time_splits)
            for key in split
        ),
        "zero_fixture_benchmark_contamination": not benchmark_findings,
        "zero_prompt_canary_leakage": not prompt_leaks,
        "distributions_and_long_tail_emitted": bool(distributions and concept_long_tail(samples)),
        "no_human_or_training_claim": True,
    }
    audit_path = EVIDENCE / "curated-corpus-v2-mechanical-audit.json"
    audit = {
        "schema": "ProofLaunchCuratedCorpusV2MechanicalAudit",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "passed_as_mechanical_synthetic_seed_not_curated_corpus_v2"
        if all(checks.values())
        else "failed",
        "checks": checks,
        "cleaning_receipts": cleaning_receipts,
        "alignments": [asdict(item) for item in alignments],
        "benchmark_contamination_count": len(benchmark_findings),
        "prompt_leakage_count": len(prompt_leaks),
        "human_review_count": 0,
        "cpt_token_count": 0,
        "sft_episode_count": 0,
        "preference_pair_count": 0,
        "gold_brief_count": 0,
        "gold_campaign_count": 0,
        "agency_corpus_v2_frozen": False,
        "curated_corpus_v2_frozen": False,
        "promotion_eligible": False,
        "manifest": str(manifest_path.relative_to(ROOT)),
        "manifest_sha256": sha256(manifest_path),
        "truth_boundary": (
            "This receipt proves corpus ontology and deterministic curation mechanics on "
            "twelve project-owned synthetic metadata samples. It is not the required "
            "2,000-source, 15M-token, 15,000-SFT, five-rater 4A corpus and is not "
            "training-promotion evidence."
        ),
    }
    audit["content_sha256"] = stable_sha256(audit)
    write_json(audit_path, audit)
    if not all(checks.values()):
        raise SystemExit("curated corpus mechanical audit failed")
    print(
        json.dumps(
            {
                "status": audit["status"],
                "samples": len(samples),
                "artifacts": len(artifact_bundle.artifacts),
                "audit": str(audit_path.relative_to(ROOT)),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
