#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import struct
import wave
from dataclasses import asdict
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text, sha256_file
from prooflaunch_remix.v10_scientific_evaluation import (
    BaselineLane,
    BaselineSet,
    BenchmarkPartition,
    BinaryConfusion,
    BlindPreferenceReceipt,
    FrozenBaseline,
    FrozenEvalCase,
    FrozenGtmBench,
    ReviewerCalibrationPlan,
    build_metric_bundle,
    planned_scientific_report,
)
from prooflaunch_remix.v10_supply_chain import stable_sha256


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data/v10_gtm_bench"
EVIDENCE_DIR = ROOT / "evidence/v10"


def _write_tone(path: Path, frequency: float) -> None:
    sample_rate = 16_000
    frame_count = sample_rate
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        frames = bytearray()
        for index in range(frame_count):
            value = round(0.2 * 32767 * math.sin(2 * math.pi * frequency * index / sample_rate))
            frames.extend(struct.pack("<h", value))
        handle.writeframes(frames)


def _record(partition: BenchmarkPartition, ordinal: int, payload: dict[str, object], modalities: tuple[str, ...]) -> dict[str, object]:
    case_id = f"gtm-{partition.value}-{ordinal:02d}"
    source_sha = stable_sha256(payload)
    return {
        "case_id": case_id,
        "partition": partition.value,
        "modalities": list(modalities),
        "source_locator": f"data/v10_gtm_bench/cases.jsonl#{case_id}",
        "source_sha256": source_sha,
        "expected_schema_sha256": stable_sha256({"partition": partition.value, "required": sorted(payload)}),
        "rights": "project_owned",
        "split": "sealed_test",
        "training_allowed": False,
        "payload": payload,
    }


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    tone_a = DATA_DIR / "audio-tone-440hz-16khz.wav"
    tone_b = DATA_DIR / "audio-tone-660hz-16khz.wav"
    _write_tone(tone_a, 440.0)
    _write_tone(tone_b, 660.0)
    records: list[dict[str, object]] = []
    records.extend(
        _record(BenchmarkPartition.ENTITY_PRODUCT, index, {"brief": f"Owned hardware launch {index}", "claim": "measured battery life requires locator", "product_id": f"entity-{index}"}, ("text", "image"))
        for index in (1, 2)
    )
    records.extend(
        _record(BenchmarkPartition.AGENT_PRODUCT, index, {"brief": f"Owned agent product launch {index}", "tools": ["research", "plan", "audit"], "product_id": f"agent-{index}"}, ("text", "tool"))
        for index in (1, 2)
    )
    records.extend(
        _record(BenchmarkPartition.LONG_DOCUMENT, index, {"document": ("Evidence paragraph with explicit limits and dated source. " * (80 + index)).strip(), "questions": ["supported claim", "known limitation"]}, ("text",))
        for index in (1, 2)
    )
    image_names = ("master-3840x2160.png", "social-safe-3840x2160.png")
    records.extend(
        _record(BenchmarkPartition.MULTI_IMAGE, index, {"images": [f"evidence/v10/image-mastering-fixture/{name}" for name in image_names], "task": f"compare identity and safe-zone variant {index}"}, ("text", "image"))
        for index in (1, 2)
    )
    records.extend(
        _record(BenchmarkPartition.VIDEO, index, {"frames": ["evidence/v10/video-mastering-fixture/frame-000-3840x2160.png", "evidence/v10/video-mastering-fixture/frame-191-3840x2160.png"], "fps": 24, "duration_seconds": 8, "task": f"check boundary continuity {index}"}, ("text", "video"))
        for index in (1, 2)
    )
    for index, tone in enumerate((tone_a, tone_b), start=1):
        records.append(_record(BenchmarkPartition.AUDIO, index, {"audio_locator": str(tone.relative_to(ROOT)), "audio_sha256": sha256_file(tone), "expected_frequency_hz": 440 if index == 1 else 660}, ("text", "audio")))
    records.extend(
        _record(BenchmarkPartition.TOOL_TRAJECTORY, index, {"steps": [{"action": "retrieve", "result": "located"}, {"action": "audit", "result": "passed"}], "expected_stop": True, "variant": index}, ("text", "tool"))
        for index in (1, 2)
    )
    records.extend(
        _record(BenchmarkPartition.MEMORY, index, {"facts": [{"revision": "r1", "status": "superseded"}, {"revision": "r2", "status": "current"}], "expected_revision": "r2", "variant": index}, ("text", "memory"))
        for index in (1, 2)
    )
    records.extend(
        _record(BenchmarkPartition.FOUR_A_CAMPAIGN, index, {"brief": f"Integrated owned campaign {index}", "required_artifacts": ["strategy", "landing", "email", "social", "image", "video", "proof"], "publish_requires_human": True}, ("text", "image", "video", "audio", "tool", "memory"))
        for index in (1, 2)
    )
    records.sort(key=lambda item: item["case_id"])
    atomic_write_text(DATA_DIR / "cases.jsonl", "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in records))
    cases = tuple(
        FrozenEvalCase(
            case_id=str(item["case_id"]),
            partition=BenchmarkPartition(str(item["partition"])),
            modalities=tuple(item["modalities"]),
            source_locator=str(item["source_locator"]),
            source_sha256=str(item["source_sha256"]),
            expected_schema_sha256=str(item["expected_schema_sha256"]),
        )
        for item in records
    )
    canaries = {partition: f"PLX-SEALED-{stable_sha256(partition.value)[:16]}" for partition in BenchmarkPartition}
    bench = FrozenGtmBench("prooflaunch-gtm-multimodal-bench-v1", cases, canaries, stable_sha256({"protocol": "test-blind-denominator-safe-v1", "partitions": [item.value for item in BenchmarkPartition]}))
    baselines = BaselineSet(
        (
            FrozenBaseline(BaselineLane.IMAGE, "FLUX.2 reference implementation", "50fe5162777813d869182b139e83b10743caef15", stable_sha256({"revision": "50fe5162777813d869182b139e83b10743caef15", "matched": True}), "https://github.com/black-forest-labs/flux2", "Apache-2.0 code; model-specific weight terms require separate review", "strongest project-selected open image reference; execution remains pending"),
            FrozenBaseline(BaselineLane.VIDEO, "Wan2.2 reference implementation", "42bf4cfaa384bc21833865abc2f9e6c0e67233dc", stable_sha256({"revision": "42bf4cfaa384bc21833865abc2f9e6c0e67233dc", "matched": True}), "https://github.com/Wan-Video/Wan2.2", "Apache-2.0 code; model weight terms require separate review", "strongest project-selected open video reference; execution remains pending"),
            FrozenBaseline(BaselineLane.GTM_AGENT, "LangGraph deterministic agent workflow", "b2926a0ff9589c28c7e01fe7cdbb337b86d5a4b4", stable_sha256({"revision": "b2926a0ff9589c28c7e01fe7cdbb337b86d5a4b4", "matched": True}), "https://github.com/langchain-ai/langgraph", "MIT", "mature open durable-agent control baseline without ProofLaunch-specific learning"),
        )
    )
    counts = {name: (17, 18) for name in (
        "schema_validity", "agent_success", "trajectory_accuracy", "failure_attribution_accuracy", "memory_precision", "image_identity", "video_identity", "temporal_consistency", "audio_video_alignment"
    )}
    counts.update({"tool_error": (1, 18), "stale_recall": (0, 18)})
    metrics = build_metric_bundle(claim_confusion=BinaryConfusion(16, 1, 2, 17), counts=counts)
    reviewer_plan = ReviewerCalibrationPlan(("reviewer-a", "reviewer-b", "reviewer-c", "reviewer-d", "reviewer-e"), 300, 20, True, True, True)
    preference_formula_probe = BlindPreferenceReceipt(120, 150)
    manifest = {
        "schema": "ProofLaunchFrozenGtmBenchManifestV1",
        "benchmark_id": bench.benchmark_id,
        "content_sha256": bench.content_sha256,
        "protocol_sha256": bench.protocol_sha256,
        "case_file": "data/v10_gtm_bench/cases.jsonl",
        "case_file_sha256": sha256_file(DATA_DIR / "cases.jsonl"),
        "case_count": len(cases),
        "partition_counts": {partition.value: sum(item.partition == partition for item in cases) for partition in BenchmarkPartition},
        "canaries": {partition.value: value for partition, value in canaries.items()},
        "split": "sealed_test",
        "training_allowed": False,
        "rights": "project_owned",
        "truth_boundary": "This freezes a small mechanical protocol fixture, not a statistically powered product-quality benchmark result.",
    }
    atomic_write_text(DATA_DIR / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    baseline_payload = {"schema": "ProofLaunchFrozenBaselineSetV1", "content_sha256": baselines.content_sha256, "selected_before_results": True, "execution_status": "not_run", "baselines": [{**asdict(item), "lane": item.lane.value} for item in baselines.baselines]}
    atomic_write_text(ROOT / "config/cortex_x_v10_scientific_evaluation_contract.json", json.dumps({"schema": "ProofLaunchScientificEvaluationContractV1", "benchmark_sha256": bench.content_sha256, "baseline_set": baseline_payload, "metric_names": [item.metric for item in metrics.metrics], "reviewer_plan": asdict(reviewer_plan), "top3_claim_requires_complete_report": True}, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    formula_report = {"schema": "ProofLaunchScientificMetricFormulaFixtureV1", "status": "passed", "metric_bundle_sha256": metrics.content_sha256, "metrics": [{**asdict(item), "value": item.value} for item in metrics.metrics], "wilson_probe": {"preferred_count": 120, "comparison_count": 150, "rate": preference_formula_probe.rate, "lower_95": preference_formula_probe.wilson_lower_95}, "truth_boundary": "Controlled counts validate formulas and denominators only; values are not system performance."}
    atomic_write_text(EVIDENCE_DIR / "scientific-metric-formula-fixture.json", json.dumps(formula_report, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    atomic_write_text(EVIDENCE_DIR / "scientific-report.planned.json", json.dumps(planned_scientific_report(bench, baselines, reviewer_plan), ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"benchmark_sha256": bench.content_sha256, "cases": len(cases), "partitions": len(BenchmarkPartition), "metrics": len(metrics.metrics), "formula_report_sha256": sha256_file(EVIDENCE_DIR / "scientific-metric-formula-fixture.json")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
