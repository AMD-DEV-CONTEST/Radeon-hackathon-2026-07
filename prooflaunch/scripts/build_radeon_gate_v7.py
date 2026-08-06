#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "notebooks" / "prooflaunch_radeon_gate_v6.ipynb"
DESTINATION = ROOT / "notebooks" / "prooflaunch_radeon_gate_v7.ipynb"


def source_of(cell: dict) -> str:
    source = cell.get("source", [])
    return "".join(source) if isinstance(source, list) else str(source)


def set_source(cell: dict, value: str) -> None:
    cell["source"] = value.splitlines(keepends=True)


def main() -> None:
    notebook = json.loads(SOURCE.read_text(encoding="utf-8"))
    for cell in notebook["cells"]:
        set_source(
            cell,
            source_of(cell)
            .replace("Radeon Gate V6", "Radeon Gate V7")
            .replace("ProofLaunchRadeonGateV6", "ProofLaunchRadeonGateV7")
            .replace("multimodal-v6", "multimodal-v7")
            .replace("radeon-v6", "radeon-v7")
            .replace("prooflaunch-radeon-v6", "prooflaunch-radeon-v7")
            .replace("gate_v6", "gate_v7")
            .replace("This V6 path", "This V7 path")
            .replace("V6 delivery cell", "V7 delivery cell"),
        )

    runtime_markdown = notebook["cells"][6]
    set_source(
        runtime_markdown,
        """## 3. Fail closed on the local AMD Radeon runtime

Before any heavy model is loaded, V7.4 writes a machine-readable
`ProofLaunchRadeonPreflightV2` report. The gate checks ROCm/HIP, VRAM, free
disk, every required Python dependency, executable FFmpeg, the local Gemma
base plus safe LoRA and frozen multimodal-retention evidence, all seven
external Hugging Face specialists against a release-locked repository,
40-character commit, license record, and exact cached revision, and—when
present—the exact 30 × 3 × 5 manifest plus every product and baseline source
hash. Processor and weight loaders receive the same immutable revision.

A missing cache is advisory while downloads are allowed and blocking under
`local_files_only` or `--strict-cache`. All other failed requirements block
the expensive matrix before it can produce misleading partial evidence.
""",
    )

    runtime_code = notebook["cells"][7]
    set_source(
        runtime_code,
        """import torch

runtime = {
    "torch_version": torch.__version__,
    "hip_version": getattr(torch.version, "hip", None),
    "gpu_available": torch.cuda.is_available(),
    "gpu_count": torch.cuda.device_count(),
    "device_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
    "total_vram_bytes": (
        torch.cuda.get_device_properties(0).total_memory
        if torch.cuda.is_available() else 0
    ),
}
print(json.dumps(runtime, indent=2))
assert runtime["gpu_available"], "AMD Radeon GPU is not available"
assert runtime["hip_version"], "PyTorch does not report a ROCm/HIP runtime"

from prooflaunch_remix.model_registry import RadeonModelRouter
from prooflaunch_remix.radeon_preflight import (
    PREFLIGHT_SCHEMA,
    run_radeon_preflight,
    write_preflight_report,
)

available_vram_gb = runtime["total_vram_bytes"] / (1024 ** 3)
execution_plan = RadeonModelRouter().report(
    available_vram_gb=available_vram_gb,
    roles=(
        "vision_language_audit",
        "open_set_detection",
        "affect_critic",
        "image_generation",
        "image_text_scoring",
        "video_generation",
        "temporal_segmentation",
        "audio_text_scoring",
    ),
    include_candidates=True,
)
print(json.dumps(execution_plan, indent=2))

benchmark_dir = multimodal_run_dir / "competition-2x"
manifest_candidate = benchmark_dir / "manifest.json"
preflight_report = run_radeon_preflight(
    settings_path=repo / "config" / "radeon_matrix_adapter.json",
    manifest_path=manifest_candidate if manifest_candidate.exists() else None,
    strict_cache=False,
    minimum_vram_gb=16.0,
    minimum_free_disk_gb=40.0,
)
preflight_output = repo / "evidence" / "radeon" / "radeon-preflight.json"
write_preflight_report(preflight_report, preflight_output)
print(json.dumps(preflight_report, indent=2, sort_keys=True))
assert preflight_report["schema"] == PREFLIGHT_SCHEMA
assert preflight_report["passed"], {
    check["check_id"]: check["details"]
    for check in preflight_report["checks"]
    if check["status"] == "blocked"
}
""",
    )

    gate_markdown = notebook["cells"][26]
    set_source(
        gate_markdown,
        """## 5G. Compile the frozen 30 × 3 × 5 evidence and apply all 20 bars

One successful fixture is evidence of operability, not benchmark quality.
V7 refuses hand-entered percentages. Certification requires:

- an immutable 450-case manifest created from 30 permitted product hashes;
- exactly one ProofLaunch and one baseline JSONL row for every case;
- at least 30 full audio-video cases, one per product;
- five-seed perceptual diversity without product-identity drift; and
- randomized candidate-hash reviews from at least five blinded raters.

The V7.4 matrix runner executes nine phase-batched passes so exactly one heavy
model is resident at a time. It atomically checkpoints each activity, re-hashes
successful artifacts and sidecars on resume, revalidates frozen input bytes,
retries only declared transient faults twice, and emits explicit failure rows.
Optional immutable-index shards are merged only after exact disjoint coverage
is proven. The bundled production factory routes Qwen3-VL, GroundingDINO,
multimodal-safe Gemma 4, SDXL, SigLIP2, LTX-Video, SAM2, and CLAP locally.

Every result row binds the still, required video, and per-case gate report by
relative locator plus SHA-256. Append-only journals fsync each completed case
and resume from the first missing manifest ID. The compiler re-hashes every
artifact, resolves A/B hashes after review, derives every rate, and aborts on
missing/duplicate cases, manifest drift, non-blind rows, copied seeds, unknown
outputs, or artifact tampering. The templates are in `docs/`; no benchmark
result is prefilled.
""",
    )

    gate_code = notebook["cells"][27]
    set_source(
        gate_code,
        """from prooflaunch_remix.competition_benchmark import (
    BaselineCaseJournal,
    COMPILED_EVIDENCE_SCHEMA,
    CompetitionCaseJournal,
    compile_competition_evidence,
)
from prooflaunch_remix.benchmark_runner import (
    PHASE_ORDER,
    RUN_CHECKPOINT_SCHEMA,
)
from prooflaunch_remix.radeon_matrix_adapter import create_adapter
from prooflaunch_remix.radeon_preflight import PREFLIGHT_SCHEMA
from prooflaunch_remix.quality_contract import QualityTier, contract_for

contract = contract_for(QualityTier.COMPETITION_2X)
assert len(contract.metrics) == 20
assert len(PHASE_ORDER) == 9
assert preflight_report["schema"] == PREFLIGHT_SCHEMA
assert preflight_report["passed"]
adapter_identity = create_adapter().identity()
assert adapter_identity["system_kind"] == "prooflaunch"
assert adapter_identity["uses_closed_online_api"] is False
assert adapter_identity["model_supply_chain_schema"] == "ProofLaunchModelSupplyChainV1"
assert len(adapter_identity["model_supply_chain"]) == 7
assert all(
    "@" in model_ref
    for role, model_ref in adapter_identity["model_refs"].items()
    if role != "gemma"
)

# A plausible hand-entered aggregate must fail because it has no case-level
# compiler provenance.
uncompiled_fixture = {
    "product_count": 30,
    "aspect_ratio_count": 3,
    "seeds_per_product": 5,
    "video_case_count": 30,
    "human_raters": 5,
    "repair_budget_max": 2,
    "unsupported_claim_count": 0,
    "locator_coverage": 1.0,
    "image_identity_pass_rate": 1.0,
    "preencode_video_identity_pass_rate": 1.0,
    "encoded_video_identity_pass_rate": 1.0,
    "audio_video_alignment_pass_rate": 1.0,
    "cross_media_pass_rate": 1.0,
    "completion_rate": 1.0,
    "crash_rate": 0.0,
    "seed_diversity_group_pass_rate": 1.0,
    "baseline_completion_rate_gap": 0.0,
    "publish_preferred_count": 150,
    "publish_comparison_count": 150,
}
assert not contract.evaluate(uncompiled_fixture).passed

benchmark_dir = multimodal_run_dir / "competition-2x"
manifest_path = benchmark_dir / "manifest.json"
results_path = benchmark_dir / "prooflaunch-results.jsonl"
baseline_path = benchmark_dir / "baseline-results.jsonl"
human_path = benchmark_dir / "human-comparisons.csv"
required_paths = (manifest_path, results_path, baseline_path, human_path)

if manifest_path.exists():
    proof_journal = CompetitionCaseJournal(manifest_path, results_path)
    baseline_journal = BaselineCaseJournal(manifest_path, baseline_path)
    run_checkpoints = sorted(benchmark_dir.glob("run-checkpoint*.json"))
    checkpoint_summaries = []
    for checkpoint_path in run_checkpoints:
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        assert checkpoint["schema"] == RUN_CHECKPOINT_SCHEMA
        checkpoint_summaries.append(
            {
                "path": str(checkpoint_path),
                "phase_states": checkpoint.get("phase_states", {}),
                "activity_count": len(checkpoint.get("activities", {})),
            }
        )
    print(
        "durable matrix progress:",
        {
            "prooflaunch_recorded": proof_journal.recorded_count,
            "prooflaunch_pending": len(proof_journal.pending_cases),
            "baseline_pending": len(baseline_journal.pending_cases),
            "runner_checkpoints": checkpoint_summaries,
        },
    )

if all(path.exists() for path in required_paths):
    compiled = compile_competition_evidence(
        manifest_path=manifest_path,
        results_path=results_path,
        baseline_results_path=baseline_path,
        human_comparisons_path=human_path,
    )
    assert compiled["schema"] == COMPILED_EVIDENCE_SCHEMA
    assert compiled["benchmark_case_count"] == 450
    assert compiled["video_case_count"] >= 30
    report = contract.evaluate(compiled)
    (benchmark_dir / "competition-2x-evidence.json").write_text(
        json.dumps(compiled, indent=2, sort_keys=True) + "\\n",
        encoding="utf-8",
    )
    (benchmark_dir / "competition-2x-report.json").write_text(
        json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\\n",
        encoding="utf-8",
    )
    assert report.passed, report.to_dict()
    print("competition-2X V7 benchmark: PASS (20/20)")
else:
    missing = [str(path) for path in required_paths if not path.exists()]
    print("competition-2X V7 benchmark: BLOCKED")
    print("Missing measured inputs:", json.dumps(missing, indent=2))
    print(
        "Build the manifest, then run scripts/run_competition_2x_matrix.py "
        "with --adapter "
        "prooflaunch_remix.radeon_matrix_adapter:create_adapter; "
        "do not replace missing case-level evidence with aggregate percentages."
    )
""",
    )

    handoff = notebook["cells"][28]
    set_source(
        handoff,
        source_of(handoff).replace(
            "Complete the 30-product / three-ratio / five-seed benchmark, "
            "blinded human comparison",
            "Complete the compiler-verified 450-case still benchmark, at least "
            "30 audio-video cases, same-case baseline, blinded candidate-hash "
            "comparison",
        ),
    )

    metadata = notebook.setdefault("metadata", {}).setdefault("prooflaunch", {})
    metadata.update(
        {
            "schema": "ProofLaunchRadeonGateV7",
            "benchmarkCompilerSchema": "ProofLaunchCompetition2XCompiledEvidenceV2",
            "benchmarkCaseCount": 450,
            "requiredVideoCaseCount": 30,
            "qualityMetricCount": 20,
            "rawAggregateCertificationAllowed": False,
            "sameCaseBaselineRequired": True,
            "blindCandidateHashReviewRequired": True,
            "seedDiversityRequired": True,
            "resumableCaseJournalRequired": True,
            "matrixRunnerSchema": "ProofLaunchCompetition2XRunCheckpointV1",
            "matrixRunnerVersion": "0.9.0",
            "phaseCount": 9,
            "specialistPhaseOrder": [
                "prepare_products",
                "understand_products",
                "ground_products",
                "plan_products",
                "generate_stills",
                "audit_stills",
                "generate_videos",
                "track_videos",
                "audit_videos",
            ],
            "phaseBatchedMatrixExecution": True,
            "boundedTransientRetries": 2,
            "verifiedShardMerge": True,
            "artifactHashBindingRequired": True,
            "preflightSchema": "ProofLaunchRadeonPreflightV2",
            "preflightVersion": "2.0.0",
            "preflightRequired": True,
            "modelSupplyChainSchema": "ProofLaunchModelSupplyChainV1",
            "immutableExternalModelRevisions": 7,
            "exactRevisionCacheRequired": True,
            "processorWeightRevisionParityRequired": True,
            "minimumVramGb": 16,
            "minimumFreeDiskGb": 40,
            "manifestSourceHashPreflightRequired": True,
        }
    )
    DESTINATION.write_text(
        json.dumps(notebook, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )
    print(DESTINATION)


if __name__ == "__main__":
    main()
