#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from prooflaunch_remix.files import atomic_write_text
from prooflaunch_remix.v10_brand_memory_benchmark import (
    build_memory_card,
    run_memory_only_benchmark,
    run_streaming_benchmark,
)
from prooflaunch_remix.v10_brand_memory_retrieval import RetrievalMode


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/v10_brand_memory"
AUDIT = ROOT / "evidence/v10/brand-memory-runtime-audit.json"
CARD = ROOT / "evidence/v10/memory-card.json"


def normalize(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): normalize(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [normalize(item) for item in value]
    return value


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        path,
        json.dumps(normalize(payload), ensure_ascii=False, indent=2) + "\n",
    )


def main() -> int:
    seed_manifest = DATA / "manifest.json"
    if not seed_manifest.is_file():
        raise SystemExit("run build_v10_brand_memory_seed.py first")
    benchmark = run_memory_only_benchmark()
    streaming = run_streaming_benchmark()
    card = build_memory_card(benchmark, streaming)
    by_mode = {item.mode: item for item in benchmark.mode_metrics}
    hybrid = by_mode[RetrievalMode.HYBRID]
    vector_only = by_mode[RetrievalMode.VECTOR_ONLY]
    no_memory = by_mode[RetrievalMode.NO_MEMORY]

    benchmark_path = DATA / "memory_only_benchmark.json"
    streaming_path = DATA / "streaming_benchmark.json"
    ablation_path = DATA / "retrieval_ablations.json"
    write_json(
        benchmark_path,
        {
            **asdict(benchmark),
            "content_sha256": benchmark.content_sha256,
        },
    )
    write_json(
        streaming_path,
        {
            **asdict(streaming),
            "content_sha256": streaming.content_sha256,
        },
    )
    write_json(
        ablation_path,
        {
            "schema": "ProofLaunchMemoryRetrievalAblationsV1",
            "hybrid": asdict(hybrid),
            "vector_only": asdict(vector_only),
            "no_memory": asdict(no_memory),
            "trained_model_ablation_observed": False,
            "conclusion": (
                "On the controlled project-owned fixtures only, scoped hybrid "
                "retrieval completes all cases while vector-only and no-memory do not."
            ),
            "truth_boundary": (
                "This is an executable information-path ablation, not a trained-model "
                "or external benchmark comparison."
            ),
        },
    )
    write_json(CARD, card)

    checks = {
        "exact_12_memory_only_cases": benchmark.case_count == 12,
        "raw_inputs_are_unavailable_to_answerer": (
            benchmark.memory_only and not benchmark.raw_input_available_to_answerer
        ),
        "all_six_retrieval_modes_executed": {
            item.mode for item in benchmark.mode_metrics
        }
        == set(RetrievalMode),
        "hybrid_retrieval_precision_at_least_0_97": (
            hybrid.retrieval_precision >= 0.97
        ),
        "hybrid_stale_recall_is_zero": hybrid.stale_recall == 0.0,
        "hybrid_context_saving_is_positive": (
            hybrid.mean_context_saving_rate > 0.0
        ),
        "hybrid_cross_campaign_transfer_is_complete": (
            hybrid.cross_campaign_transfer_rate == 1.0
        ),
        "hybrid_brand_contamination_is_zero": (
            hybrid.brand_contamination_rate == 0.0
        ),
        "vector_only_ablation_is_inferior": (
            hybrid.complete_case_rate > vector_only.complete_case_rate
            and vector_only.brand_contamination_rate > 0.0
        ),
        "no_memory_ablation_is_inferior": (
            hybrid.complete_case_rate > no_memory.complete_case_rate
            and no_memory.retrieved_count == 0
        ),
        "streaming_revision_expiry_conflict_rollback_pass": all(
            (
                streaming.old_revision_excluded_after_update,
                streaming.expired_fact_excluded,
                streaming.conflict_winner_retrieved,
                streaming.conflict_loser_quarantined,
                streaming.rollback_restored_prior_revision,
                streaming.event_chain_valid,
            )
        ),
        "memory_card_is_frozen_content_addressed": (
            card["frozen"] is True and len(str(card["content_sha256"])) == 64
        ),
        "trained_and_hardware_quality_remain_unclaimed": (
            card["trained_model_metrics"] is None
            and card["observed_neural_embedding_inference"] is False
            and card["radeon_execution_receipt"] is None
            and card["promotion_eligible"] is False
        ),
        "three_primary_reuse_sources_are_bound": len(card["reuse_or_justify"]) == 3,
    }
    evidence_paths = (
        seed_manifest,
        benchmark_path,
        streaming_path,
        ablation_path,
        CARD,
        ROOT / "src/prooflaunch_remix/v10_brand_memory.py",
        ROOT / "src/prooflaunch_remix/v10_brand_memory_retrieval.py",
        ROOT / "src/prooflaunch_remix/v10_brand_memory_benchmark.py",
        ROOT / "tests/test_v10_brand_memory.py",
        ROOT / "tests/test_v10_brand_memory_runtime.py",
    )
    files = {
        path.name: {
            "path": str(path.relative_to(ROOT)),
            "sha256": sha256(path),
            "bytes": path.stat().st_size,
        }
        for path in evidence_paths
    }
    audit = {
        "schema": "ProofLaunchBrandGenomeMemoryRuntimeAuditV1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": (
            "passed_as_mechanical_brand_genome_v1_not_model_quality"
            if all(checks.values())
            else "failed"
        ),
        "brand_genome_v1_frozen": all(checks.values()),
        "checks": checks,
        "metrics": {
            "case_count": benchmark.case_count,
            "hybrid_retrieval_precision": hybrid.retrieval_precision,
            "hybrid_stale_recall": hybrid.stale_recall,
            "hybrid_mean_context_saving_rate": hybrid.mean_context_saving_rate,
            "hybrid_cross_campaign_transfer_rate": (
                hybrid.cross_campaign_transfer_rate
            ),
            "hybrid_brand_contamination_rate": hybrid.brand_contamination_rate,
            "vector_only_complete_case_rate": vector_only.complete_case_rate,
            "no_memory_complete_case_rate": no_memory.complete_case_rate,
        },
        "files": files,
        "research_sources": card["reuse_or_justify"],
        "observed_neural_embedding_inference": False,
        "trained_retriever_or_memory_policy": False,
        "external_memory_benchmark_runs": 0,
        "human_4a_evaluations": 0,
        "radeon_execution_receipts": 0,
        "promotion_eligible": False,
        "truth_boundary": card["truth_boundary"],
    }
    write_json(AUDIT, audit)
    if not all(checks.values()):
        raise SystemExit("Brand Genome runtime checks failed")
    print(
        json.dumps(
            {
                "status": audit["status"],
                "cases": benchmark.case_count,
                "hybrid_precision": hybrid.retrieval_precision,
                "stale_recall": hybrid.stale_recall,
                "context_saving": hybrid.mean_context_saving_rate,
                "cross_campaign_transfer": hybrid.cross_campaign_transfer_rate,
                "brand_contamination": hybrid.brand_contamination_rate,
                "memory_card_sha256": card["content_sha256"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
