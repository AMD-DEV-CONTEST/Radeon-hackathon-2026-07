from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

from colorgraph.agent import (
    CreativeProviderRuntime,
    CreativeRole,
    LocalSceneAnalyzer,
    RuntimeBudget,
    RuntimePolicy,
    build_provider_shadow_request,
    calibrate_vlm_shadow_file,
    color_features_from_analyses,
    configured_creative_provider,
    group_consecutive_shots,
    run_provider_shadow,
)
from colorgraph.agent.creative_corpus import load_creative_knowledge_corpus
from colorgraph.agent.creative_provider import (
    JsonlProviderAuditSink,
    ProviderBoundary,
    ProviderImage,
    ProviderResponseCache,
)
from colorgraph.config import settings
from colorgraph.devices import TorchComputeBackend
from colorgraph.domain.grade_graph import ColorSpace
from colorgraph.evaluation import (
    REQUIRED_PROFILES,
    REQUIRED_THERMAL_STATES,
    REQUIRED_VARIANTS,
    CreativeRuntimeSafetySnapshot,
    assemble_creative_production_evaluation,
    audit_amd_demo_benchmark_file,
    audit_creative_ablation_matrix_file,
    audit_creative_ablation_seed_file,
    audit_creative_agent_readiness_file,
    audit_creative_critic_calibration_file,
    audit_formal_model_sources_file,
    audit_gold_set,
    audit_research_watch_file,
    audit_vos_platform_prerequisites,
    bind_autoshot_runtime_to_shot_bundle_file,
    bind_transnetv2_runtime_to_shot_bundle_file,
    capture_autoshot_runtime_observation,
    capture_cutie_runtime_observation,
    capture_sam2_runtime_observation,
    capture_sea_raft_runtime_observation,
    capture_semantic_runtime_observation,
    capture_shot_model_observations_file,
    capture_transnetv2_runtime_observation,
    capture_vlm_runtime_observation,
    create_annotation_work_pack,
    create_creative_review_freeze,
    evaluate_creative_agent_file,
    evaluate_observations,
    evaluate_semantic_shadow_file,
    evaluate_shot_shadow_file,
    evaluate_vos_shadow_file,
    generate_sam2_mask_asset,
    generate_tracked_mask_asset_bundle,
    inspect_source_registry,
    load_gold_set_manifest,
    run_amd_demo_benchmark,
    run_amd_full_pipeline,
    run_precision_gate,
    run_production_benchmark,
    source_registry_status,
    validate_gold_set_files,
)
from colorgraph.grading.ocio_pipeline import ocio_pipeline_metadata
from colorgraph.grading.video import VideoRenderer
from colorgraph.media.color_analysis import analyze_video_color
from colorgraph.media.probe import VideoFrameTiming, probe_media
from colorgraph.media.representative_frames import (
    embedding_candidate_paths,
    extract_representative_candidates,
    materialize_representatives,
    quality_representative_sources,
    representative_metadata,
    select_cosine_medoids,
)
from colorgraph.media.shots import detect_shot_ranges
from colorgraph.quality import analyze_video_quality
from colorgraph.services.graph_builder import build_initial_graph
from colorgraph.services.mask_nodes import ensure_default_mask_nodes
from colorgraph.storage import ProjectStore
from colorgraph.vision import (
    DepthMaskProvider,
    OfficialVideoDepthAnythingRunner,
    OneFormerSemanticMaskProvider,
    SemanticMaskProvider,
    VideoMaskGenerator,
    audit_video_depth_installation,
    inference_cache_stats,
    run_video_depth_shadow,
)
from colorgraph.vision.video_depth_shadow import write_video_depth_shadow_report


def _version(binary: str) -> str:
    completed = subprocess.run(
        [binary, "-version"],
        capture_output=True,
        text=True,
        check=False,
    )
    return (completed.stdout or completed.stderr).splitlines()[0]


def _doctor(_: argparse.Namespace) -> int:
    backend = TorchComputeBackend(settings.device_preference)
    payload = {
        "device": backend.info.model_dump(mode="json"),
        "ffmpeg": _version(settings.ffmpeg_binary),
        "ffprobe": _version(settings.ffprobe_binary),
        "color_management": ocio_pipeline_metadata(
            ColorSpace.BT709_OETF,
            source_log_profile=None,
            output_space=ColorSpace.REC1886,
        ),
        "directories": {
            "data": str(settings.data_dir),
            "models": str(settings.models_dir),
        },
        "inference_cache": inference_cache_stats(),
        "inference_cache_policy": {
            "model_cache_max_entries": settings.model_cache_max_entries,
            "model_budget_mb": settings.model_vram_budget_mb,
            "embedding_cache_max_entries": settings.embedding_cache_max_entries,
            "model_budget_scope": "estimated parameters and buffers",
        },
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _analyze(arguments: argparse.Namespace) -> int:
    source = Path(arguments.video).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    store = ProjectStore()
    project = store.create(arguments.name or source.stem)
    copied = store.copy_source(project, source)
    media = probe_media(copied)
    ranges = detect_shot_ranges(copied)
    color = analyze_video_color(copied, ranges)
    candidate_sets = extract_representative_candidates(
        copied,
        ranges,
        project.frames_dir,
        fps=media.fps,
    )
    representative_sources = quality_representative_sources(candidate_sets)
    frames = materialize_representatives(candidate_sets, representative_sources)
    frame_metadata = representative_metadata(
        candidate_sets,
        representative_sources,
        method="quality_filtered_temporal_fallback",
    )
    scene_analyses = []
    scene_grouping = None
    scene_analyzer = None
    if not arguments.skip_scene_model:
        scene_analyzer = LocalSceneAnalyzer(TorchComputeBackend(settings.device_preference))
        embedding_paths, _ = embedding_candidate_paths(candidate_sets)
        candidate_embeddings = scene_analyzer.embed_images(embedding_paths)
        selection = select_cosine_medoids(candidate_sets, candidate_embeddings)
        frames = materialize_representatives(candidate_sets, selection.source_paths)
        frame_metadata = selection.metadata
        scene_analyses = [scene_analyzer.analyze(frame) for frame in frames]
        scene_grouping = group_consecutive_shots(
            selection.shot_embeddings,
            scene_analyses,
            color_features=color_features_from_analyses(color),
        )
    graph = build_initial_graph(
        project_id=project.id,
        project_name=arguments.name or source.stem,
        media=media,
        shot_ranges=ranges,
        representative_frames=frames,
        representative_frame_metadata=frame_metadata,
        color_analyses=color,
        scene_analyses=scene_analyses,
        scene_groups=(scene_grouping.shot_groups if scene_grouping is not None else None),
        scene_grouping_metadata=(
            scene_grouping.model_dump(mode="json") if scene_grouping is not None else None
        ),
    )
    if arguments.with_masks:
        if scene_analyzer is not None:
            scene_analyzer.release_model()
        backend = TorchComputeBackend(settings.device_preference)
        mask_result = VideoMaskGenerator(
            SemanticMaskProvider(backend),
            DepthMaskProvider(backend),
        ).generate(copied, graph, project.masks_dir)
        graph = ensure_default_mask_nodes(mask_result.graph)
    store.save_graph(project, graph)
    print(
        json.dumps(
            {
                "project_id": project.id,
                "project_root": str(project.root),
                "shots": len(graph.shots),
                "nodes": len(graph.nodes),
                "masks": len(graph.masks),
                "graph": str(project.graph_path),
                "inference_cache": inference_cache_stats(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _render(arguments: argparse.Namespace) -> int:
    store = ProjectStore()
    project = store.get(arguments.project_id)
    graph = store.load_graph(arguments.project_id)
    source = store.resolve_source(project)
    destination = (
        Path(arguments.output).resolve() if arguments.output else project.outputs_dir / "graded.mp4"
    )
    backend = TorchComputeBackend(settings.device_preference)
    validated_timings = None
    if arguments.validated_cfr:
        media = probe_media(source)
        frame_duration = 1.0 / media.fps
        validated_timings = [
            VideoFrameTiming(
                pts_seconds=index * frame_duration,
                duration_seconds=frame_duration,
            )
            for index in range(media.frame_count)
        ]
    last_progress = -1

    def report_progress(completed: int, total: int) -> None:
        nonlocal last_progress
        percent = round(completed / max(total, 1) * 100)
        if percent < last_progress + 2 and completed != total:
            return
        last_progress = percent
        print(f"render {percent}% ({completed}/{total})", flush=True)

    result = VideoRenderer(backend).render(
        source,
        destination,
        graph,
        batch_size=arguments.batch_size,
        bit_depth=arguments.bit_depth,
        progress=report_progress,
        validated_source_timings=validated_timings,
    )
    report = analyze_video_quality(source, destination, graph=graph)
    report_path = destination.with_name("quality_report.json")
    report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "render": asdict(result),
                "quality_score": report.score,
                "hard_checks_passed": report.hard_checks_passed,
                "quality_report": str(report_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _evaluate(arguments: argparse.Namespace) -> int:
    report = evaluate_observations(
        arguments.manifest,
        arguments.observations,
        arguments.output,
        dataset_root=arguments.root,
        gold_audit_path=arguments.gold_audit,
        gate_policy_path=arguments.gate_policy,
        require_passed_gold=arguments.require_passed_gold,
    )
    print(
        json.dumps(
            {
                "report": str(Path(arguments.output).resolve()),
                "schema_version": report.schema_version,
                "manifest_id": report.manifest_id,
                "metric_sections": sorted(report.metrics),
                "gates": report.gates,
                "all_gates_passed": all(report.gates.values()),
                "evidence_status": report.evidence_status,
                "release_eligible": report.release_eligible,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if all(report.gates.values()) else 2


def _gold_validate(arguments: argparse.Namespace) -> int:
    manifest_path = Path(arguments.manifest).resolve()
    manifest = load_gold_set_manifest(manifest_path)
    validate_gold_set_files(
        manifest,
        Path(arguments.root).resolve() if arguments.root else manifest_path.parent,
    )
    print(
        json.dumps(
            {
                "manifest_id": manifest.id,
                "version": manifest.version,
                "items": len(manifest.items),
                "test_items": sum(item.split.value == "test" for item in manifest.items),
                "status": "valid",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _gold_audit(arguments: argparse.Namespace) -> int:
    manifest_path = Path(arguments.manifest).resolve()
    manifest = load_gold_set_manifest(manifest_path)
    validate_gold_set_files(
        manifest,
        Path(arguments.root).resolve() if arguments.root else manifest_path.parent,
    )
    report = audit_gold_set(manifest)
    if arguments.output:
        destination = Path(arguments.output).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            report.model_dump_json(indent=2),
            encoding="utf-8",
        )
    print(report.model_dump_json(indent=2))
    return 0 if report.passed else 2


def _gold_source_status(arguments: argparse.Namespace) -> int:
    status = source_registry_status(
        arguments.registry,
        root=arguments.root,
    )
    print(status.model_dump_json(indent=2))
    return 0 if status.ready_for_annotation else 2


def _gold_source_inspect(arguments: argparse.Namespace) -> int:
    report = inspect_source_registry(
        arguments.registry,
        arguments.output,
        root=arguments.root,
    )
    print(
        json.dumps(
            {
                "report": str(Path(arguments.output).resolve()),
                "schema_version": report.schema_version,
                "source_groups": report.total_source_groups,
                "draft_shots": report.total_draft_shots,
                "annotation_status": ("pending_independent_human_annotation"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _gold_annotation_pack(arguments: argparse.Namespace) -> int:
    pack = create_annotation_work_pack(
        arguments.inspection,
        arguments.output,
        root=arguments.root,
    )
    print(
        json.dumps(
            {
                "pack": str(Path(arguments.output).resolve()),
                "schema_version": pack.schema_version,
                "source_groups": len(pack.items),
                "frames": sum(item.frame_count for item in pack.items),
                "status": pack.status,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _creative_agent_evaluation(arguments: argparse.Namespace) -> int:
    report = evaluate_creative_agent_file(arguments.input, arguments.output)
    print(
        json.dumps(
            {
                "report": str(Path(arguments.output).resolve()),
                "schema_version": report.schema_version,
                "evidence_class": report.evidence_class.value,
                "test_items": report.test_items,
                "reviewers": report.reviewer_count,
                "preference_ci95_low": (report.full_vs_rule_preference.ci95_low),
                "release_status": report.release_status,
                "failed_gates": [name for name, passed in report.gates.items() if not passed],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report.release_status == "eligible_default" else 2


def _creative_ablation_audit(arguments: argparse.Namespace) -> int:
    audit = audit_creative_ablation_seed_file(
        arguments.input,
        arguments.output,
    )
    print(
        json.dumps(
            {
                "report": str(Path(arguments.output).resolve()),
                "schema_version": audit.schema_version,
                "variant": audit.variant.value,
                "checked_artifacts": audit.checked_artifacts,
                "execution_protocol_valid": audit.execution_protocol_valid,
                "technical_evidence_passed": audit.passed,
                "formal_review_freeze": audit.formal_review_freeze,
                "formal_release_eligible": audit.formal_release_eligible,
                "issues": audit.issues,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if audit.passed else 2


def _creative_ablation_matrix_audit(arguments: argparse.Namespace) -> int:
    audit = audit_creative_ablation_matrix_file(
        arguments.input,
        arguments.output,
    )
    print(
        json.dumps(
            {
                "report": str(Path(arguments.output).resolve()),
                "schema_version": audit.schema_version,
                "checked_seed_manifests": audit.checked_seed_manifests,
                "passed_seed_manifests": audit.passed_seed_manifests,
                "unique_test_items": audit.unique_test_items,
                "required_test_items": audit.required_test_items,
                "complete_test_items": audit.complete_test_items,
                "technical_evidence_integrity_passed": (
                    audit.technical_evidence_integrity_passed
                ),
                "technical_matrix_complete": audit.technical_matrix_complete,
                "formal_review_freeze": audit.formal_review_freeze,
                "formal_release_eligible": audit.formal_release_eligible,
                "blockers": audit.blockers,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if audit.passed else 2


def _creative_review_freeze(arguments: argparse.Namespace) -> int:
    manifest = create_creative_review_freeze(
        arguments.draft,
        arguments.panel,
        arguments.output_dir,
    )
    print(
        json.dumps(
            {
                "manifest": str(
                    Path(arguments.output_dir).resolve()
                    / "creative-review-freeze.json"
                ),
                "schema_version": manifest.schema_version,
                "freeze_id": manifest.freeze_id,
                "reviewers": len(manifest.assignments),
                "pairs_per_reviewer": len(
                    manifest.assignments[0].answer_key
                ),
                "status": manifest.status,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _creative_review_assemble(arguments: argparse.Namespace) -> int:
    bundle = assemble_creative_production_evaluation(
        arguments.freeze,
        arguments.submission,
        arguments.output,
    )
    print(
        json.dumps(
            {
                "bundle": str(Path(arguments.output).resolve()),
                "schema_version": bundle.schema_version,
                "evaluation_id": bundle.evaluation_id,
                "dataset_version": bundle.dataset_version,
                "reviewers": len(bundle.reviewers),
                "reviews": len(bundle.reviews),
                "evidence_class": bundle.evidence_class.value,
                "next_command": (
                    f"colorgraph creative-agent-eval --input "
                    f"{Path(arguments.output).resolve()} --output "
                    f"{Path(arguments.output).resolve().with_name('evaluation-report.json')}"
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _creative_critic_calibrate(arguments: argparse.Namespace) -> int:
    audit = audit_creative_critic_calibration_file(
        arguments.input,
        arguments.output,
    )
    print(
        json.dumps(
            {
                "report": str(Path(arguments.output).resolve()),
                "schema_version": audit.schema_version,
                "calibration_id": audit.calibration_id,
                "qualified_reviewers": audit.qualified_reviewer_count,
                "checked_reports": audit.checked_report_count,
                "independent_records": audit.independent_record_count,
                "self_evaluation_records": (
                    audit.self_evaluation_record_count
                ),
                "evidence_integrity_passed": (
                    audit.evidence_integrity_passed
                ),
                "calibration_authorized": audit.calibration_authorized,
                "issues": audit.issues,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if audit.calibration_authorized else 2


def _creative_agent_readiness(arguments: argparse.Namespace) -> int:
    ollama_selected = settings.enable_ollama_creative_provider
    provider_feature_enabled = (
        settings.enable_openai_creative_provider or ollama_selected
    )
    runtime = CreativeRuntimeSafetySnapshot(
        network_enabled=settings.creative_network_enabled,
        provider_feature_enabled=provider_feature_enabled,
        provider_model_configured=bool(
            (
                settings.ollama_creative_model
                if ollama_selected
                else settings.openai_creative_model
            ).strip()
        ),
        provider_image_input_declared=(
            settings.ollama_creative_image_input
            if ollama_selected
            else settings.openai_creative_image_input
        ),
        provider_strict_output_declared=(
            settings.ollama_creative_strict_structured_output
            if ollama_selected
            else settings.openai_creative_strict_structured_output
        ),
        provider_maximum_context_tokens=(
            settings.ollama_creative_max_context_tokens
            if ollama_selected
            else settings.openai_creative_max_context_tokens
        ),
        provider_maximum_images=(
            settings.ollama_creative_max_images
            if ollama_selected
            else settings.openai_creative_max_images
        ),
        credential_present=(
            ollama_selected or bool(os.getenv("OPENAI_API_KEY"))
        ),
        knowledge_corpus_feature_enabled=(
            settings.enable_creative_knowledge_corpus
        ),
        knowledge_corpus_path_configured=bool(
            settings.creative_knowledge_corpus_path.strip()
        ),
        critic_calibration_feature_enabled=(
            settings.enable_creative_critic_calibration
        ),
        critic_calibration_path_configured=bool(
            settings.creative_critic_calibration_path.strip()
        ),
        current_runtime_fail_closed=(
            not settings.creative_network_enabled
            and not provider_feature_enabled
        ),
    )
    report = audit_creative_agent_readiness_file(
        output_path=arguments.output,
        runtime=runtime,
        provider_shadow_path=arguments.provider_shadow_report,
        corpus_path=(
            arguments.corpus
            or settings.creative_knowledge_corpus_path
            or None
        ),
        critic_calibration_path=(
            arguments.critic_calibration
            or settings.creative_critic_calibration_path
            or None
        ),
        evaluation_bundle_path=arguments.evaluation_bundle,
    )
    print(
        json.dumps(
            {
                "report": str(Path(arguments.output).resolve()),
                "all_tasks_eligible_to_archive": (
                    report.all_tasks_eligible_to_archive
                ),
                "task_gates": {
                    task_id: gate.eligible_to_archive
                    for task_id, gate in report.task_gates.items()
                },
                "blockers": report.blockers,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report.all_tasks_eligible_to_archive else 2


def _precision_gate(arguments: argparse.Namespace) -> int:
    report = run_precision_gate(
        arguments.output,
        expected_runtime=arguments.require_runtime,
        repeats=arguments.repeats,
    )
    print(
        json.dumps(
            {
                "report": str(Path(arguments.output).resolve()),
                "schema_version": report.schema_version,
                "runtime": report.hardware.runtime,
                "device": report.hardware.name,
                "master_passed": report.master.passed,
                "preview_passed": report.preview.passed,
                "determinism_passed": report.determinism.passed,
                "status": report.status,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report.status == "passed" else 2


def _production_benchmark(arguments: argparse.Namespace) -> int:
    last_percent: dict[str, int] = {}

    def report_progress(case_key: str, completed: int, total: int) -> None:
        percent = round(completed / max(total, 1) * 100)
        previous = last_percent.get(case_key, -5)
        if percent < previous + 5 and completed != total:
            return
        last_percent[case_key] = percent
        print(
            f"benchmark {case_key} {percent}% ({completed}/{total})",
            flush=True,
        )

    report = run_production_benchmark(
        project_id=arguments.project_id,
        output=arguments.output,
        variants=arguments.variants,
        profiles=arguments.profiles,
        thermal_states=arguments.thermal_states,
        start_seconds=arguments.start_seconds,
        end_seconds=arguments.end_seconds,
        batch_size=arguments.batch_size,
        hash_source=arguments.hash_source,
        quality_checks=arguments.quality_checks,
        resume=arguments.resume,
        progress=report_progress,
    )
    print(
        json.dumps(
            {
                "report": str(Path(arguments.output).resolve()),
                "status": report.status,
                "run_id": report.run_id,
                "completed_coverage": len(report.completed_coverage),
                "required_coverage": len(report.required_coverage),
                "blocked_coverage": report.blocked_coverage,
                "failed_coverage": report.failed_coverage,
                "missing_coverage": report.missing_coverage,
                "production_claim_allowed": report.production_claim_allowed,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report.production_claim_allowed else 2


def _amd_demo_benchmark(arguments: argparse.Namespace) -> int:
    last_percent: dict[str, int] = {}

    def report_progress(case_key: str, completed: int, total: int) -> None:
        percent = round(completed / max(total, 1) * 100)
        previous = last_percent.get(case_key, -5)
        if percent < previous + 5 and completed != total:
            return
        last_percent[case_key] = percent
        print(
            f"amd-demo {case_key} {percent}% ({completed}/{total})",
            flush=True,
        )

    report, digest = run_amd_demo_benchmark(
        project_id=arguments.project_id,
        source_manifest=arguments.source_manifest,
        benchmark_output=arguments.benchmark_output,
        output=arguments.output,
        batch_size=arguments.batch_size,
        progress=report_progress,
    )
    print(
        json.dumps(
            {
                "report": str(Path(arguments.output).resolve()),
                "report_sha256": digest,
                "sha256_sidecar": report.audit_sha256_sidecar_path,
                "status": report.status,
                "gate_passed": report.gate_passed,
                "blockers": report.blockers,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report.gate_passed else 2


def _amd_demo_benchmark_audit(arguments: argparse.Namespace) -> int:
    report, digest = audit_amd_demo_benchmark_file(
        source_manifest=arguments.source_manifest,
        benchmark_report=arguments.benchmark_report,
        output=arguments.output,
    )
    print(
        json.dumps(
            {
                "report": str(Path(arguments.output).resolve()),
                "report_sha256": digest,
                "sha256_sidecar": report.audit_sha256_sidecar_path,
                "status": report.status,
                "gate_passed": report.gate_passed,
                "blockers": report.blockers,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report.gate_passed else 2


def _amd_full_pipeline(arguments: argparse.Namespace) -> int:
    report, digest = run_amd_full_pipeline(
        project_id=arguments.project_id,
        source_manifest=arguments.source_manifest,
        precision_report=arguments.precision_report,
        output_dir=arguments.output_dir,
        output=arguments.output,
        batch_size=arguments.batch_size,
        ollama_server_log=arguments.ollama_server_log,
    )
    print(
        json.dumps(
            {
                "report": str(Path(arguments.output).resolve()),
                "report_sha256": digest,
                "sha256_sidecar": report.report_sha256_sidecar_path,
                "status": report.status,
                "gate_passed": report.gate_passed,
                "device": report.hardware.name,
                "ollama_backend": report.ollama.backend.accelerator_library,
                "final_render": report.final_render.output_path,
                "final_render_sha256": report.final_render.output_sha256,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _research_watch_audit(arguments: argparse.Namespace) -> int:
    report = audit_research_watch_file(arguments.manifest, arguments.output)
    print(
        json.dumps(
            {
                "report": str(Path(arguments.output).resolve()),
                "schema_version": report.schema_version,
                "registry_integrity_passed": report.registry_integrity_passed,
                "watch_candidates": report.watch_candidates,
                "eligible_candidates": report.eligible_candidates,
                "promoted_candidates": report.promoted_candidates,
                "invalid_candidates": report.invalid_candidates,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report.registry_integrity_passed else 2


def _formal_model_source_audit(arguments: argparse.Namespace) -> int:
    report = audit_formal_model_sources_file(
        arguments.manifest,
        arguments.output,
    )
    print(
        json.dumps(
            {
                "report": str(Path(arguments.output).resolve()),
                "schema_version": report.schema_version,
                "registry_integrity_passed": report.registry_integrity_passed,
                "license_cleared_candidates": (report.license_cleared_candidates),
                "runtime_ready_candidates": report.runtime_ready_candidates,
                "missing_candidates": report.missing_candidates,
                "unexpected_candidates": report.unexpected_candidates,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report.registry_integrity_passed else 2


def _creative_corpus_audit(arguments: argparse.Namespace) -> int:
    loaded = load_creative_knowledge_corpus(arguments.input)
    destination = Path(arguments.output).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(loaded.audit.model_dump_json(indent=2), encoding="utf-8")
    temporary.replace(destination)
    print(
        json.dumps(
            {
                "report": str(destination),
                "schema_version": loaded.audit.schema_version,
                "corpus_id": loaded.audit.corpus_id,
                "corpus_version": loaded.audit.corpus_version,
                "source_count": loaded.audit.source_count,
                "card_count": loaded.audit.card_count,
                "passed": loaded.audit.passed,
                "issues": loaded.audit.issues,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if loaded.audit.passed else 2


def _shot_shadow_evaluation(arguments: argparse.Namespace) -> int:
    report = evaluate_shot_shadow_file(arguments.input, arguments.output)
    print(
        json.dumps(
            {
                "report": str(Path(arguments.output).resolve()),
                "schema_version": report.schema_version,
                "status": report.status,
                "release_status": report.release_status,
                "recommended_candidate": report.recommended_candidate,
                "missing_models": report.missing_models,
                "failed_gates": [name for name, passed in report.gates.items() if not passed],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report.release_status == "eligible_default_candidate" else 2


def _shot_shadow_observation(arguments: argparse.Namespace) -> int:
    media_paths: dict[str, str] = {}
    for binding in arguments.media:
        item_id, separator, path = binding.partition("=")
        if not separator or not item_id.strip() or not path.strip():
            raise ValueError(
                "--media values must use the form ITEM_ID=PATH"
            )
        item_id = item_id.strip()
        if item_id in media_paths:
            raise ValueError(f"duplicate --media binding for {item_id}")
        media_paths[item_id] = path.strip()
    bundle = capture_shot_model_observations_file(
        arguments.input,
        arguments.output,
        model_id=arguments.model,
        media_paths=media_paths,
    )
    run = next(item for item in bundle.runs if item.model_id == arguments.model)
    print(
        json.dumps(
            {
                "bundle": str(Path(arguments.output).resolve()),
                "schema_version": bundle.schema_version,
                "model_id": run.model_id,
                "status": run.status,
                "observations": len(run.observations),
                "predicted_boundaries": {
                    item.item_id: item.predicted_boundaries
                    for item in run.observations
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _transnetv2_shadow_observation(
    arguments: argparse.Namespace,
) -> int:
    observation = capture_transnetv2_runtime_observation(
        arguments.source_registry,
        arguments.repository,
        arguments.checkpoint,
        arguments.parity_checkpoint,
        arguments.video,
        arguments.predictions_output,
        arguments.output,
        threshold=arguments.threshold,
        media_origin=arguments.media_origin,
    )
    bound_bundle = None
    if arguments.bundle_input or arguments.bundle_output or arguments.item_id:
        if not (
            arguments.bundle_input
            and arguments.bundle_output
            and arguments.item_id
        ):
            raise ValueError(
                "--bundle-input, --bundle-output, and --item-id must be "
                "provided together"
            )
        bound_bundle = bind_transnetv2_runtime_to_shot_bundle_file(
            arguments.bundle_input,
            arguments.output,
            arguments.bundle_output,
            item_id=arguments.item_id,
        )
    print(
        json.dumps(
            {
                "report": str(Path(arguments.output).resolve()),
                "predictions": observation.output_path,
                "schema_version": observation.schema_version,
                "status": observation.status,
                "code_revision": observation.resolved_code_revision,
                "checkpoint_sha256": (
                    observation.checkpoint_state_sha256
                ),
                "mirror_state_parity": (
                    observation.independent_mirror_state_parity_verified
                ),
                "frames": observation.frame_count,
                "predicted_boundaries": (
                    observation.predicted_boundaries
                ),
                "bundle": (
                    str(Path(arguments.bundle_output).resolve())
                    if bound_bundle is not None
                    else None
                ),
                "inference_fps": observation.inference_fps,
                "cold_processing_fps": observation.cold_processing_fps,
                "peak_gpu_memory_mb": observation.peak_gpu_memory_mb,
                "blocker": observation.blocker,
                "error": observation.error,
                "gold_quality_claim_authorized": False,
                "production_default_authorized": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if observation.status == "completed" else 2


def _autoshot_shadow_observation(
    arguments: argparse.Namespace,
) -> int:
    observation = capture_autoshot_runtime_observation(
        arguments.source_registry,
        arguments.repository,
        arguments.checkpoint,
        arguments.video,
        arguments.predictions_output,
        arguments.output,
        threshold=arguments.threshold,
        media_origin=arguments.media_origin,
    )
    bound_bundle = None
    if arguments.bundle_input or arguments.bundle_output or arguments.item_id:
        if not (
            arguments.bundle_input
            and arguments.bundle_output
            and arguments.item_id
        ):
            raise ValueError(
                "--bundle-input, --bundle-output, and --item-id must be "
                "provided together"
            )
        bound_bundle = bind_autoshot_runtime_to_shot_bundle_file(
            arguments.bundle_input,
            arguments.output,
            arguments.bundle_output,
            item_id=arguments.item_id,
        )
    print(
        json.dumps(
            {
                "report": str(Path(arguments.output).resolve()),
                "predictions": observation.output_path,
                "schema_version": observation.schema_version,
                "status": observation.status,
                "code_revision": observation.resolved_code_revision,
                "checkpoint_sha256": (
                    observation.checkpoint_state_sha256
                ),
                "checkpoint_source_is_mutable": True,
                "project_authorization_id": (
                    observation.project_authorization_id
                ),
                "frames": observation.frame_count,
                "predicted_boundaries": (
                    observation.predicted_boundaries
                ),
                "bundle": (
                    str(Path(arguments.bundle_output).resolve())
                    if bound_bundle is not None
                    else None
                ),
                "inference_fps": observation.inference_fps,
                "cold_processing_fps": observation.cold_processing_fps,
                "peak_gpu_memory_mb": observation.peak_gpu_memory_mb,
                "blocker": observation.blocker,
                "error": observation.error,
                "gold_quality_claim_authorized": False,
                "production_default_authorized": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if observation.status == "completed" else 2


def _vlm_shadow_calibration(arguments: argparse.Namespace) -> int:
    calibration = calibrate_vlm_shadow_file(arguments.input, arguments.output)
    print(
        json.dumps(
            {
                "report": str(Path(arguments.output).resolve()),
                "schema_version": calibration.schema_version,
                "status": calibration.status,
                "model_id": calibration.model_id,
                "model_revision": calibration.model_revision,
                "temperature": calibration.temperature,
                "label_threshold_count": len(calibration.label_thresholds),
                "ood_balanced_accuracy": calibration.ood_balanced_accuracy,
                "default_model_authorized": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _vlm_shadow_observation(arguments: argparse.Namespace) -> int:
    observation = capture_vlm_runtime_observation(
        arguments.calibration,
        arguments.label_source,
        arguments.frame,
        arguments.output,
    )
    print(
        json.dumps(
            {
                "report": str(Path(arguments.output).resolve()),
                "schema_version": observation.schema_version,
                "status": observation.status,
                "model_id": observation.model_id,
                "model_revision": observation.model_revision,
                "local_files_only": observation.local_files_only,
                "runtime": observation.runtime,
                "frames": len(observation.requested_frames),
                "processing_fps": observation.processing_fps,
                "peak_gpu_memory_mb": observation.peak_gpu_memory_mb,
                "blocker": observation.blocker,
                "error": observation.error,
                "default_model_authorized": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if observation.status == "completed" else 2


def _semantic_shadow_evaluation(arguments: argparse.Namespace) -> int:
    report = evaluate_semantic_shadow_file(arguments.input, arguments.output)
    print(
        json.dumps(
            {
                "report": str(Path(arguments.output).resolve()),
                "schema_version": report.schema_version,
                "status": report.status,
                "release_status": report.release_status,
                "recommended_candidate": report.recommended_candidate,
                "missing_models": report.missing_models,
                "failed_gates": [name for name, passed in report.gates.items() if not passed],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report.release_status == "eligible_default_candidate" else 2


def _semantic_shadow_observation(arguments: argparse.Namespace) -> int:
    observation = capture_semantic_runtime_observation(
        arguments.source_registry,
        arguments.candidate,
        arguments.frame,
        arguments.output,
    )
    print(
        json.dumps(
            {
                "report": str(Path(arguments.output).resolve()),
                "schema_version": observation.schema_version,
                "status": observation.status,
                "candidate_id": observation.candidate_id,
                "model_id": observation.model_id,
                "requested_model_revision": (
                    observation.requested_model_revision
                ),
                "resolved_model_revision": (
                    observation.resolved_model_revision
                ),
                "checkpoint_sha256": observation.checkpoint_sha256,
                "local_files_only": observation.local_files_only,
                "runtime": observation.runtime,
                "frames": len(observation.requested_frames),
                "processing_fps": observation.processing_fps,
                "peak_gpu_memory_mb": observation.peak_gpu_memory_mb,
                "blocker": observation.blocker,
                "error": observation.error,
                "gold_quality_claim_authorized": False,
                "commercial_default_authorized": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if observation.status == "completed" else 2


def _sam2_shadow_observation(arguments: argparse.Namespace) -> int:
    observation = capture_sam2_runtime_observation(
        arguments.source_registry,
        arguments.repository,
        arguments.video,
        arguments.masks_output,
        arguments.output,
        semantic_candidate_id=arguments.semantic_candidate,
        semantic_target=arguments.semantic_target,
        maximum_frames=arguments.maximum_frames,
        media_origin=arguments.media_origin,
        parent_source_path=arguments.parent_source,
        source_start_seconds=arguments.source_start_seconds,
    )
    print(
        json.dumps(
            {
                "report": str(Path(arguments.output).resolve()),
                "masks": observation.masks_path,
                "schema_version": observation.schema_version,
                "status": observation.status,
                "model_id": observation.sam_model_id,
                "model_revision": observation.resolved_sam_revision,
                "checkpoint_sha256": (
                    observation.sam_checkpoint_state_sha256
                ),
                "semantic_anchor_model": (
                    observation.semantic_model_id
                ),
                "semantic_anchor_target": observation.semantic_target,
                "frames": observation.decoded_frame_count,
                "propagation_fps": observation.propagation_fps,
                "cold_processing_fps": observation.cold_processing_fps,
                "peak_gpu_memory_mb": observation.peak_gpu_memory_mb,
                "memory_growth_mb": observation.memory_growth_mb,
                "blocker": observation.blocker,
                "error": observation.error,
                "gold_quality_claim_authorized": False,
                "production_default_authorized": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if observation.status == "completed" else 2


def _sam2_mask_asset(arguments: argparse.Namespace) -> int:
    store = ProjectStore()
    project = store.get(arguments.project_id)
    graph = store.load_graph(arguments.project_id)
    source = store.resolve_source(project)

    def report_progress(completed: int, total: int, label: str) -> None:
        print(
            f"{label}: {completed}/{total}",
            file=sys.stderr,
            flush=True,
        )

    result = generate_sam2_mask_asset(
        arguments.source_registry,
        arguments.repository,
        source,
        graph,
        arguments.output_root,
        arguments.output,
        semantic_candidate_id=arguments.semantic_candidate,
        target=arguments.target,
        asset_id=arguments.asset_id,
        maximum_edge=arguments.maximum_edge,
        window_frames=arguments.window_frames,
        storage_bit_depth=arguments.storage_bit_depth,
        retain_mask_sequence=arguments.retain_mask_sequence,
        progress=report_progress,
    )
    if arguments.install:
        store.save_graph(project, result.graph)
    observation = result.observation
    print(
        json.dumps(
            {
                "report": str(Path(arguments.output).resolve()),
                "mask_video": observation.mask_video_path,
                "schema_version": observation.schema_version,
                "status": observation.status,
                "project_id": observation.project_id,
                "asset_id": observation.asset_id,
                "target": observation.target,
                "frames": observation.frame_count,
                "windows": observation.window_count,
                "propagation_fps": observation.propagation_fps,
                "peak_gpu_memory_mb": observation.peak_gpu_memory_mb,
                "memory_growth_mb": (
                    observation.maximum_memory_growth_mb
                ),
                "installed_into_project": arguments.install,
                "gold_quality_claim_authorized": False,
                "production_default_authorized": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _tracked_mask_assets(arguments: argparse.Namespace) -> int:
    store = ProjectStore()
    project = store.get(arguments.project_id)
    graph = store.load_graph(arguments.project_id)
    source = store.resolve_source(project)
    backend = TorchComputeBackend(settings.device_preference)
    semantic_type = (
        OneFormerSemanticMaskProvider
        if arguments.semantic_provider == "oneformer"
        else SemanticMaskProvider
    )
    semantic = semantic_type(
        backend,
        model_id=arguments.semantic_model,
        model_revision=arguments.semantic_revision,
        local_files_only=True,
    )
    depth = DepthMaskProvider(
        backend,
        model_id=arguments.depth_model,
        model_revision=arguments.depth_revision,
        local_files_only=True,
    )

    def report_progress(completed: int, total: int, label: str) -> None:
        print(
            f"{label}: {completed}/{total}",
            file=sys.stderr,
            flush=True,
        )

    result = generate_tracked_mask_asset_bundle(
        source,
        graph,
        arguments.output_root,
        arguments.output,
        semantic_provider=semantic,
        depth_provider=depth,
        semantic_model_revision=arguments.semantic_revision,
        depth_model_revision=arguments.depth_revision,
        targets=arguments.targets,
        inference_interval_seconds=arguments.inference_interval_seconds,
        maximum_edge=arguments.maximum_edge,
        storage_bit_depth=arguments.storage_bit_depth,
        retain_mask_sequence=arguments.retain_mask_sequence,
        progress=report_progress,
    )
    if arguments.install:
        store.save_graph(project, result.graph)
    observation = result.observation
    print(
        json.dumps(
            {
                "report": str(Path(arguments.output).resolve()),
                "schema_version": observation.schema_version,
                "status": observation.status,
                "project_id": observation.project_id,
                "frames": observation.frame_count,
                "inference_frames": observation.inference_frames,
                "assets": [
                    {
                        "asset_id": asset.asset_id,
                        "provider": asset.provider,
                        "model_revision": asset.model_revision,
                        "checkpoint_sha256": asset.checkpoint_sha256,
                        "video_sha256": asset.video_sha256,
                    }
                    for asset in observation.assets
                ],
                "elapsed_seconds": observation.elapsed_seconds,
                "installed_into_project": arguments.install,
                "gold_quality_claim_authorized": False,
                "production_default_authorized": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _sea_raft_shadow_observation(arguments: argparse.Namespace) -> int:
    observation = capture_sea_raft_runtime_observation(
        arguments.source_registry,
        arguments.repository,
        arguments.snapshot,
        arguments.torch_home,
        arguments.video,
        arguments.flow_output,
        arguments.output,
        maximum_pairs=arguments.maximum_pairs,
        media_origin=arguments.media_origin,
        parent_source_path=arguments.parent_source,
        source_start_seconds=arguments.source_start_seconds,
    )
    print(
        json.dumps(
            {
                "report": str(Path(arguments.output).resolve()),
                "flow_output": observation.output_path,
                "schema_version": observation.schema_version,
                "status": observation.status,
                "model_id": observation.model_id,
                "model_revision": observation.resolved_model_revision,
                "checkpoint_sha256": (
                    observation.checkpoint_state_sha256
                ),
                "pairs": observation.processed_pair_count,
                "pair_fps": observation.pair_fps,
                "peak_gpu_memory_mb": observation.peak_gpu_memory_mb,
                "memory_growth_mb": observation.memory_growth_mb,
                "reports_native_uncertainty": (
                    observation.status == "completed"
                ),
                "reports_fb_occlusion": (
                    observation.status == "completed"
                ),
                "blocker": observation.blocker,
                "error": observation.error,
                "gold_quality_claim_authorized": False,
                "production_default_authorized": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if observation.status == "completed" else 2


def _cutie_shadow_observation(arguments: argparse.Namespace) -> int:
    observation = capture_cutie_runtime_observation(
        arguments.source_registry,
        arguments.repository,
        arguments.video,
        arguments.masks_output,
        arguments.output,
        semantic_candidate_id=arguments.semantic_candidate,
        semantic_target=arguments.semantic_target,
        maximum_frames=arguments.maximum_frames,
        maximum_internal_size=arguments.maximum_internal_size,
        media_origin=arguments.media_origin,
        parent_source_path=arguments.parent_source,
        source_start_seconds=arguments.source_start_seconds,
    )
    print(
        json.dumps(
            {
                "report": str(Path(arguments.output).resolve()),
                "masks": observation.masks_path,
                "schema_version": observation.schema_version,
                "status": observation.status,
                "code_revision": observation.resolved_code_revision,
                "checkpoint_sha256": (
                    observation.checkpoint_state_sha256
                ),
                "semantic_anchor_model": observation.semantic_model_id,
                "semantic_anchor_target": observation.semantic_target,
                "frames": observation.decoded_frame_count,
                "propagation_fps": observation.propagation_fps,
                "cold_processing_fps": observation.cold_processing_fps,
                "peak_gpu_memory_mb": observation.peak_gpu_memory_mb,
                "memory_growth_mb": observation.memory_growth_mb,
                "mean_adjacent_binary_iou": (
                    observation.mean_adjacent_binary_iou
                ),
                "weights_license_review_complete": (
                    observation.weights_license_review_complete
                ),
                "blocker": observation.blocker,
                "error": observation.error,
                "gold_quality_claim_authorized": False,
                "production_default_authorized": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if observation.status == "completed" else 2


def _vos_shadow_evaluation(arguments: argparse.Namespace) -> int:
    report = evaluate_vos_shadow_file(arguments.input, arguments.output)
    print(
        json.dumps(
            {
                "report": str(Path(arguments.output).resolve()),
                "schema_version": report.schema_version,
                "status": report.status,
                "release_status": report.release_status,
                "eligible_candidates": report.eligible_candidates,
                "recommended_primary": report.recommended_primary,
                "recommended_vos_fallback": report.recommended_vos_fallback,
                "recommended_flow_fallback": report.recommended_flow_fallback,
                "missing_models": report.missing_models,
                "failed_gates": [name for name, passed in report.gates.items() if not passed],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report.release_status == "eligible_candidates" else 2


def _vos_platform_audit(arguments: argparse.Namespace) -> int:
    report = audit_vos_platform_prerequisites(
        arguments.output,
        wsl_distribution=arguments.wsl_distribution,
        timeout_seconds=arguments.timeout_seconds,
    )
    print(
        json.dumps(
            {
                "report": str(Path(arguments.output).resolve()),
                "schema_version": report.schema_version,
                "status": report.status,
                "matrix_documented": report.matrix_documented,
                "wsl_cuda_prerequisites_passed": (report.wsl_cuda_prerequisites_passed),
                "model_runtime_authorized": report.model_runtime_authorized,
                "blockers": report.blockers,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report.wsl_cuda_prerequisites_passed else 2


def _depth_shadow_audit(arguments: argparse.Namespace) -> int:
    audit = audit_video_depth_installation(
        arguments.repository,
        arguments.checkpoint,
    )
    payload = audit.model_dump(mode="json")
    if arguments.output:
        destination = Path(arguments.output).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if audit.available else 2


def _depth_shadow(arguments: argparse.Namespace) -> int:
    source = Path(arguments.video).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    ranges = detect_shot_ranges(source)
    runner = OfficialVideoDepthAnythingRunner(
        arguments.repository,
        arguments.checkpoint,
        python_executable=arguments.python,
    )
    result = run_video_depth_shadow(
        source,
        ranges,
        arguments.output,
        runner,
    )
    report_path = arguments.report or str(
        Path(arguments.output).resolve().with_suffix(".report.json")
    )
    write_video_depth_shadow_report(result, report_path)
    print(
        json.dumps(
            {
                **result.model_dump(mode="json"),
                "report_path": str(Path(report_path).resolve()),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _provider_image(path_value: str, *, detail: str) -> ProviderImage:
    path = Path(path_value).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    media_types = {
        ".gif": "image/gif",
        ".jpeg": "image/jpeg",
        ".jpg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }
    media_type = media_types.get(path.suffix.lower())
    if media_type is None:
        raise ValueError(f"unsupported provider image type: {path.suffix or '<none>'}")
    content = path.read_bytes()
    return ProviderImage(
        asset_id=f"shadow-frame:{path.name}",
        sha256=hashlib.sha256(content).hexdigest(),
        media_type=media_type,
        content=content,
        detail=detail,
    )


def _creative_provider_shadow(arguments: argparse.Namespace) -> int:
    provider = configured_creative_provider(
        settings,
        api_key_getter=lambda: os.getenv("OPENAI_API_KEY"),
    )
    if provider.capabilities.maximum_context_tokens <= 0:
        raise ValueError(
            "the selected creative provider context limit must be configured"
        )
    if provider.capabilities.maximum_images < 0:
        raise ValueError(
            "the selected creative provider image limit must be non-negative"
        )
    cloud_active = (
        provider.boundary != ProviderBoundary.LOCAL
        and settings.creative_network_enabled
        and settings.enable_openai_creative_provider
    )
    if cloud_active and not arguments.confirm_cloud_run:
        raise ValueError("--confirm-cloud-run is required before a real provider shadow request")

    prompt_path = Path(arguments.prompt_file).resolve()
    if not prompt_path.is_file():
        raise FileNotFoundError(prompt_path)
    prompt_bytes = prompt_path.read_bytes()
    prompt = prompt_bytes.decode("utf-8")
    images = tuple(_provider_image(path, detail=arguments.image_detail) for path in arguments.image)
    destination = Path(arguments.output).resolve()
    audit_path = destination.with_suffix(destination.suffix + ".audit.jsonl")
    runtime = CreativeProviderRuntime(
        {role: provider for role in CreativeRole},
        policy=RuntimePolicy(
            network_enabled=settings.creative_network_enabled,
            cloud_provider_enabled=settings.enable_openai_creative_provider,
            timeout_seconds=arguments.timeout,
            maximum_retries=arguments.maximum_retries,
            maximum_concurrency=1,
            requests_per_minute=arguments.requests_per_minute,
        ),
        budget=RuntimeBudget(
            maximum_provider_attempts=arguments.maximum_retries + 1,
            maximum_input_tokens=arguments.input_token_budget,
            maximum_output_tokens=arguments.output_token_budget,
            maximum_cost_usd=arguments.maximum_cost_usd,
        ),
        cache=ProviderResponseCache(settings.cache_dir / "creative-provider"),
        audit_sink=JsonlProviderAuditSink(audit_path),
    )
    request = build_provider_shadow_request(
        scene_id=arguments.scene_id,
        role=CreativeRole(arguments.role),
        prompt=prompt,
        prompt_version=arguments.prompt_version,
        input_asset_digests=(hashlib.sha256(prompt_bytes).hexdigest(),),
        images=images,
        max_output_tokens=arguments.max_output_tokens,
        estimated_input_tokens=arguments.estimated_input_tokens,
        cloud_upload_consent=arguments.consent_cloud_upload,
    )
    report = asyncio.run(
        run_provider_shadow(
            runtime,
            scene_id=arguments.scene_id,
            request=request,
        )
    )
    payload = report.model_dump(mode="json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if report.status == "completed" else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="colorgraph",
        description="Local temporal-spatial landscape video grading",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    doctor = subparsers.add_parser("doctor", help="inspect local runtime")
    doctor.set_defaults(handler=_doctor)

    analyze = subparsers.add_parser("analyze", help="create a project")
    analyze.add_argument("video")
    analyze.add_argument("--name")
    analyze.add_argument("--with-masks", action="store_true")
    analyze.add_argument("--skip-scene-model", action="store_true")
    analyze.set_defaults(handler=_analyze)

    render = subparsers.add_parser("render", help="render an analyzed project")
    render.add_argument("project_id")
    render.add_argument("--output")
    render.add_argument("--batch-size", type=int, default=4)
    render.add_argument("--bit-depth", type=int, choices=(8, 10), default=10)
    render.add_argument(
        "--validated-cfr",
        action="store_true",
        help="reuse synthesized CFR timings after the source has been independently validated",
    )
    render.set_defaults(handler=_render)

    evaluate = subparsers.add_parser(
        "evaluate",
        help="run the versioned unified Gold Set evaluation",
    )
    evaluate.add_argument("manifest")
    evaluate.add_argument("observations")
    evaluate.add_argument("--output", required=True)
    evaluate.add_argument(
        "--root",
        help="dataset root; defaults to the manifest directory",
    )
    evaluate.add_argument(
        "--gold-audit",
        help="fresh colorgraph.gold-set-audit/v1 report to reproduce and bind",
    )
    evaluate.add_argument(
        "--gate-policy",
        help=(
            "calibration-only colorgraph.gold-gate-policy/v1 artifact "
            "whose gates must exactly match the evaluation"
        ),
    )
    evaluate.add_argument(
        "--require-passed-gold",
        action="store_true",
        help=(
            "reject unless the audit passes and every metric section exactly "
            "covers its qualified frozen test materials"
        ),
    )
    evaluate.set_defaults(handler=_evaluate)

    gold_validate = subparsers.add_parser(
        "gold-validate",
        help="verify Gold Set paths, split policy and checksums",
    )
    gold_validate.add_argument("manifest")
    gold_validate.add_argument("--root")
    gold_validate.set_defaults(handler=_gold_validate)

    gold_audit = subparsers.add_parser(
        "gold-audit",
        help="audit real-media quotas, human truth and content coverage",
    )
    gold_audit.add_argument("manifest")
    gold_audit.add_argument("--root")
    gold_audit.add_argument("--output")
    gold_audit.set_defaults(handler=_gold_audit)

    gold_source_status = subparsers.add_parser(
        "gold-source-status",
        help="validate a licensed source registry and inspect local downloads",
    )
    gold_source_status.add_argument("registry")
    gold_source_status.add_argument("--root")
    gold_source_status.set_defaults(handler=_gold_source_status)

    gold_source_inspect = subparsers.add_parser(
        "gold-source-inspect",
        help="hash and probe downloaded sources and create unreviewed shot drafts",
    )
    gold_source_inspect.add_argument("registry")
    gold_source_inspect.add_argument("--root")
    gold_source_inspect.add_argument("--output", required=True)
    gold_source_inspect.set_defaults(handler=_gold_source_inspect)

    gold_annotation_pack = subparsers.add_parser(
        "gold-annotation-pack",
        help="freeze frame-accurate work orders for independent human annotation",
    )
    gold_annotation_pack.add_argument("inspection")
    gold_annotation_pack.add_argument("--root")
    gold_annotation_pack.add_argument("--output", required=True)
    gold_annotation_pack.set_defaults(handler=_gold_annotation_pack)

    creative_agent_evaluation = subparsers.add_parser(
        "creative-agent-eval",
        help=(
            "evaluate frozen expert comparisons and keep the Agent in Shadow "
            "unless every release gate passes"
        ),
    )
    creative_agent_evaluation.add_argument("--input", required=True)
    creative_agent_evaluation.add_argument("--output", required=True)
    creative_agent_evaluation.set_defaults(handler=_creative_agent_evaluation)

    creative_ablation_audit = subparsers.add_parser(
        "creative-ablation-audit",
        help=(
            "verify stage-by-stage content binding for a technical ablation "
            "seed without treating it as Gold, expert, or release evidence"
        ),
    )
    creative_ablation_audit.add_argument("--input", required=True)
    creative_ablation_audit.add_argument("--output", required=True)
    creative_ablation_audit.set_defaults(handler=_creative_ablation_audit)

    creative_ablation_matrix_audit = subparsers.add_parser(
        "creative-ablation-matrix-audit",
        help=(
            "verify at least ten frozen items with all eight content-bound "
            "ablation variants while keeping formal review and release disabled"
        ),
    )
    creative_ablation_matrix_audit.add_argument("--input", required=True)
    creative_ablation_matrix_audit.add_argument("--output", required=True)
    creative_ablation_matrix_audit.set_defaults(
        handler=_creative_ablation_matrix_audit
    )

    creative_review_freeze = subparsers.add_parser(
        "creative-review-freeze",
        help=(
            "freeze authorized media/candidates and create separately randomized "
            "blind assignments for at least three independent experts"
        ),
    )
    creative_review_freeze.add_argument("--draft", required=True)
    creative_review_freeze.add_argument("--panel", required=True)
    creative_review_freeze.add_argument("--output-dir", required=True)
    creative_review_freeze.set_defaults(handler=_creative_review_freeze)

    creative_review_assemble = subparsers.add_parser(
        "creative-review-assemble",
        help=(
            "verify every frozen assignment and expert submission, then assemble "
            "a content-bound production evaluation bundle"
        ),
    )
    creative_review_assemble.add_argument("--freeze", required=True)
    creative_review_assemble.add_argument(
        "--submission",
        action="append",
        required=True,
        help="repeat once for every frozen reviewer",
    )
    creative_review_assemble.add_argument("--output", required=True)
    creative_review_assemble.set_defaults(handler=_creative_review_assemble)

    creative_critic_calibrate = subparsers.add_parser(
        "creative-critic-calibrate",
        help=(
            "derive the Critic expert-correlation gate from content-bound "
            "production reviews and frozen blind Critic reports"
        ),
    )
    creative_critic_calibrate.add_argument("--input", required=True)
    creative_critic_calibrate.add_argument("--output", required=True)
    creative_critic_calibrate.set_defaults(
        handler=_creative_critic_calibrate
    )

    creative_agent_readiness = subparsers.add_parser(
        "creative-agent-readiness",
        help=(
            "audit the real-provider, authorized-corpus, frozen-expert, "
            "Critic-calibration, and release evidence for the five remaining "
            "creative Agent tasks without changing rollout configuration"
        ),
    )
    creative_agent_readiness.add_argument("--provider-shadow-report")
    creative_agent_readiness.add_argument("--corpus")
    creative_agent_readiness.add_argument("--critic-calibration")
    creative_agent_readiness.add_argument("--evaluation-bundle")
    creative_agent_readiness.add_argument("--output", required=True)
    creative_agent_readiness.set_defaults(
        handler=_creative_agent_readiness
    )

    precision_gate = subparsers.add_parser(
        "precision-gate",
        help="compare CPU and CUDA/ROCm color output and write an evidence report",
    )
    precision_gate.add_argument(
        "--require-runtime",
        required=True,
        choices=("cuda", "rocm"),
    )
    precision_gate.add_argument("--output", required=True)
    precision_gate.add_argument("--repeats", type=int, default=3)
    precision_gate.set_defaults(handler=_precision_gate)

    production_benchmark = subparsers.add_parser(
        "production-benchmark",
        help=(
            "run the fail-closed real 1080p/4K cold/warm production matrix; "
            "partial coverage never authorizes a production claim"
        ),
    )
    production_benchmark.add_argument("project_id")
    production_benchmark.add_argument("--output", required=True)
    production_benchmark.add_argument(
        "--variants",
        nargs="+",
        choices=REQUIRED_VARIANTS,
        default=list(REQUIRED_VARIANTS),
    )
    production_benchmark.add_argument(
        "--profiles",
        nargs="+",
        choices=REQUIRED_PROFILES,
        default=list(REQUIRED_PROFILES),
    )
    production_benchmark.add_argument(
        "--thermal-states",
        nargs="+",
        choices=REQUIRED_THERMAL_STATES,
        default=list(REQUIRED_THERMAL_STATES),
    )
    production_benchmark.add_argument("--start-seconds", type=float, default=0)
    production_benchmark.add_argument("--end-seconds", type=float)
    production_benchmark.add_argument("--batch-size", type=int, default=4)
    production_benchmark.add_argument("--hash-source", action="store_true")
    production_benchmark.add_argument(
        "--quality-checks",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    production_benchmark.add_argument(
        "--resume",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    production_benchmark.set_defaults(handler=_production_benchmark)

    amd_demo_benchmark = subparsers.add_parser(
        "amd-demo-benchmark",
        help=(
            "run the exact two-row 1080p warm Demo gate on a supported "
            "AMD Radeon/ROCm host and write a hashed fail-closed audit"
        ),
    )
    amd_demo_benchmark.add_argument("project_id")
    amd_demo_benchmark.add_argument("--source-manifest", required=True)
    amd_demo_benchmark.add_argument("--benchmark-output", required=True)
    amd_demo_benchmark.add_argument("--output", required=True)
    amd_demo_benchmark.add_argument("--batch-size", type=int, default=4)
    amd_demo_benchmark.set_defaults(handler=_amd_demo_benchmark)

    amd_demo_benchmark_audit = subparsers.add_parser(
        "amd-demo-benchmark-audit",
        help=(
            "audit an existing exact two-row benchmark; CUDA/CPU reports "
            "remain engineering-preflight-only"
        ),
    )
    amd_demo_benchmark_audit.add_argument("--source-manifest", required=True)
    amd_demo_benchmark_audit.add_argument("--benchmark-report", required=True)
    amd_demo_benchmark_audit.add_argument("--output", required=True)
    amd_demo_benchmark_audit.set_defaults(handler=_amd_demo_benchmark_audit)

    amd_full_pipeline = subparsers.add_parser(
        "amd-full-pipeline",
        help=(
            "run the fail-closed ROCm AI, pinned Ollama Qwen3.5 VLM, "
            "AMD Demo benchmark, Main10 AMF render, and hard-QA gate"
        ),
    )
    amd_full_pipeline.add_argument("project_id")
    amd_full_pipeline.add_argument("--source-manifest", required=True)
    amd_full_pipeline.add_argument("--precision-report", required=True)
    amd_full_pipeline.add_argument("--output-dir", required=True)
    amd_full_pipeline.add_argument("--output", required=True)
    amd_full_pipeline.add_argument("--batch-size", type=int, default=4)
    amd_full_pipeline.add_argument("--ollama-server-log")
    amd_full_pipeline.set_defaults(handler=_amd_full_pipeline)

    research_watch_audit = subparsers.add_parser(
        "research-watch-audit",
        help=(
            "audit the versioned research watchlist; candidates remain blocked until "
            "license, reproducibility, 16 GB, Windows/ROCm, and Gold Set gates pass"
        ),
    )
    research_watch_audit.add_argument("--manifest", required=True)
    research_watch_audit.add_argument("--output", required=True)
    research_watch_audit.set_defaults(handler=_research_watch_audit)

    formal_model_source_audit = subparsers.add_parser(
        "formal-model-source-audit",
        help=(
            "audit immutable official sources and commercial/distribution "
            "licenses separately from installed checkpoint/runtime readiness"
        ),
    )
    formal_model_source_audit.add_argument("--manifest", required=True)
    formal_model_source_audit.add_argument("--output", required=True)
    formal_model_source_audit.set_defaults(handler=_formal_model_source_audit)

    creative_corpus_audit = subparsers.add_parser(
        "creative-corpus-audit",
        help=(
            "audit content hashes, rights evidence, human approvals, route coverage, "
            "and template diversity before a creative corpus can enter local RAG"
        ),
    )
    creative_corpus_audit.add_argument("--input", required=True)
    creative_corpus_audit.add_argument("--output", required=True)
    creative_corpus_audit.set_defaults(handler=_creative_corpus_audit)

    shot_shadow_evaluation = subparsers.add_parser(
        "shot-shadow-eval",
        help=(
            "compare current/PySceneDetect/TransNetV2/AutoShot by transition type; "
            "engineering fixtures and incomplete model rows remain shadow-only"
        ),
    )
    shot_shadow_evaluation.add_argument("--input", required=True)
    shot_shadow_evaluation.add_argument("--output", required=True)
    shot_shadow_evaluation.set_defaults(handler=_shot_shadow_evaluation)

    shot_shadow_observation = subparsers.add_parser(
        "shot-shadow-observe",
        help=(
            "capture measured current-detector or PySceneDetect CPU observations "
            "after exact media SHA/frame/FPS verification"
        ),
    )
    shot_shadow_observation.add_argument("--input", required=True)
    shot_shadow_observation.add_argument("--output", required=True)
    shot_shadow_observation.add_argument(
        "--model",
        required=True,
        choices=("current_detector", "pyscenedetect_adaptive"),
    )
    shot_shadow_observation.add_argument(
        "--media",
        action="append",
        required=True,
        metavar="ITEM_ID=PATH",
        help="repeat once per evaluation item",
    )
    shot_shadow_observation.set_defaults(handler=_shot_shadow_observation)

    transnetv2_shadow_observation = subparsers.add_parser(
        "transnetv2-shadow-observe",
        help=(
            "run exact-revision TransNetV2 with two independently packaged "
            "checkpoint states and persist real local runtime evidence"
        ),
    )
    transnetv2_shadow_observation.add_argument("video")
    transnetv2_shadow_observation.add_argument(
        "--source-registry",
        required=True,
    )
    transnetv2_shadow_observation.add_argument(
        "--repository",
        required=True,
    )
    transnetv2_shadow_observation.add_argument(
        "--checkpoint",
        required=True,
    )
    transnetv2_shadow_observation.add_argument(
        "--parity-checkpoint",
        required=True,
    )
    transnetv2_shadow_observation.add_argument(
        "--predictions-output",
        required=True,
    )
    transnetv2_shadow_observation.add_argument("--output", required=True)
    transnetv2_shadow_observation.add_argument(
        "--threshold",
        type=float,
        default=0.5,
    )
    transnetv2_shadow_observation.add_argument(
        "--media-origin",
        choices=(
            "camera_original",
            "licensed_stock",
            "published_dataset",
            "procedural",
        ),
        default="procedural",
    )
    transnetv2_shadow_observation.add_argument("--bundle-input")
    transnetv2_shadow_observation.add_argument("--bundle-output")
    transnetv2_shadow_observation.add_argument("--item-id")
    transnetv2_shadow_observation.set_defaults(
        handler=_transnetv2_shadow_observation
    )

    autoshot_shadow_observation = subparsers.add_parser(
        "autoshot-shadow-observe",
        help=(
            "run the exact AutoShot code revision with a locally frozen "
            "official-share checkpoint and persist real runtime evidence"
        ),
    )
    autoshot_shadow_observation.add_argument("video")
    autoshot_shadow_observation.add_argument(
        "--source-registry",
        required=True,
    )
    autoshot_shadow_observation.add_argument(
        "--repository",
        required=True,
    )
    autoshot_shadow_observation.add_argument(
        "--checkpoint",
        required=True,
    )
    autoshot_shadow_observation.add_argument(
        "--predictions-output",
        required=True,
    )
    autoshot_shadow_observation.add_argument("--output", required=True)
    autoshot_shadow_observation.add_argument(
        "--threshold",
        type=float,
        default=0.296,
    )
    autoshot_shadow_observation.add_argument(
        "--media-origin",
        choices=(
            "camera_original",
            "licensed_stock",
            "published_dataset",
            "procedural",
        ),
        default="procedural",
    )
    autoshot_shadow_observation.add_argument("--bundle-input")
    autoshot_shadow_observation.add_argument("--bundle-output")
    autoshot_shadow_observation.add_argument("--item-id")
    autoshot_shadow_observation.set_defaults(
        handler=_autoshot_shadow_observation
    )

    vlm_shadow_calibration = subparsers.add_parser(
        "vlm-shadow-calibrate",
        help=(
            "fit SigLIP2 shadow temperature, per-label, and OOD thresholds from "
            "a calibration-only split without authorizing a default-model change"
        ),
    )
    vlm_shadow_calibration.add_argument("--input", required=True)
    vlm_shadow_calibration.add_argument("--output", required=True)
    vlm_shadow_calibration.set_defaults(handler=_vlm_shadow_calibration)

    vlm_shadow_observation = subparsers.add_parser(
        "vlm-shadow-observe",
        help=(
            "run a frozen SigLIP2 calibration against local cached weights "
            "only; completed and blocked runtime observations are both saved"
        ),
    )
    vlm_shadow_observation.add_argument("--calibration", required=True)
    vlm_shadow_observation.add_argument(
        "--label-source",
        required=True,
        help="the calibration input that freezes labels and prompts",
    )
    vlm_shadow_observation.add_argument(
        "--frame",
        action="append",
        required=True,
        help="repeat for every representative frame",
    )
    vlm_shadow_observation.add_argument("--output", required=True)
    vlm_shadow_observation.set_defaults(handler=_vlm_shadow_observation)

    semantic_shadow_evaluation = subparsers.add_parser(
        "semantic-shadow-eval",
        help=(
            "compare current SegFormer-B0, SegFormer-B5, and OneFormer by "
            "key-class IoU/Boundary-F, temporal stability, speed, VRAM, and license"
        ),
    )
    semantic_shadow_evaluation.add_argument("--input", required=True)
    semantic_shadow_evaluation.add_argument("--output", required=True)
    semantic_shadow_evaluation.set_defaults(handler=_semantic_shadow_evaluation)

    semantic_shadow_observation = subparsers.add_parser(
        "semantic-shadow-observe",
        help=(
            "run a frozen semantic baseline/candidate against local cached "
            "weights only and persist completed or blocked runtime evidence"
        ),
    )
    semantic_shadow_observation.add_argument(
        "--source-registry",
        required=True,
    )
    semantic_shadow_observation.add_argument(
        "--candidate",
        required=True,
        choices=(
            "current_segformer_b0",
            "segformer_b5",
            "oneformer_ade20k_swin_large",
        ),
    )
    semantic_shadow_observation.add_argument(
        "--frame",
        action="append",
        required=True,
        help="repeat for every representative frame",
    )
    semantic_shadow_observation.add_argument("--output", required=True)
    semantic_shadow_observation.set_defaults(
        handler=_semantic_shadow_observation
    )

    sam2_shadow_observation = subparsers.add_parser(
        "sam2-shadow-observe",
        help=(
            "run exact-revision SAM 2.1 video propagation from a real "
            "semantic anchor using local cached weights only"
        ),
    )
    sam2_shadow_observation.add_argument("video")
    sam2_shadow_observation.add_argument(
        "--source-registry",
        required=True,
    )
    sam2_shadow_observation.add_argument("--repository", required=True)
    sam2_shadow_observation.add_argument("--masks-output", required=True)
    sam2_shadow_observation.add_argument("--output", required=True)
    sam2_shadow_observation.add_argument(
        "--semantic-candidate",
        choices=(
            "current_segformer_b0",
            "segformer_b5",
            "oneformer_ade20k_swin_large",
        ),
        default="oneformer_ade20k_swin_large",
    )
    sam2_shadow_observation.add_argument(
        "--semantic-target",
        default="mountain",
    )
    sam2_shadow_observation.add_argument(
        "--maximum-frames",
        type=int,
        default=120,
    )
    sam2_shadow_observation.add_argument(
        "--media-origin",
        choices=(
            "camera_original",
            "camera_original_derived_clip",
            "licensed_stock",
            "published_dataset",
            "procedural",
        ),
        default="procedural",
    )
    sam2_shadow_observation.add_argument("--parent-source")
    sam2_shadow_observation.add_argument(
        "--source-start-seconds",
        type=float,
    )
    sam2_shadow_observation.set_defaults(
        handler=_sam2_shadow_observation
    )

    sam2_mask_asset = subparsers.add_parser(
        "sam2-mask-asset",
        help=(
            "generate a bounded-memory, windowed SAM 2.1 FFV1 mask asset "
            "for a complete project source; Gold/default claims remain false"
        ),
    )
    sam2_mask_asset.add_argument("project_id")
    sam2_mask_asset.add_argument(
        "--source-registry",
        required=True,
    )
    sam2_mask_asset.add_argument("--repository", required=True)
    sam2_mask_asset.add_argument("--output-root", required=True)
    sam2_mask_asset.add_argument("--output", required=True)
    sam2_mask_asset.add_argument(
        "--semantic-candidate",
        choices=(
            "current_segformer_b0",
            "segformer_b5",
            "oneformer_ade20k_swin_large",
        ),
        default="oneformer_ade20k_swin_large",
    )
    sam2_mask_asset.add_argument("--target", default="mountain")
    sam2_mask_asset.add_argument(
        "--asset-id",
        default="mask_sam21_mountain",
    )
    sam2_mask_asset.add_argument(
        "--maximum-edge",
        type=int,
        default=640,
    )
    sam2_mask_asset.add_argument(
        "--window-frames",
        type=int,
        default=30,
    )
    sam2_mask_asset.add_argument(
        "--storage-bit-depth",
        type=int,
        choices=(8, 16),
        default=8,
    )
    sam2_mask_asset.add_argument(
        "--retain-mask-sequence",
        action=argparse.BooleanOptionalAction,
        default=False,
    )
    sam2_mask_asset.add_argument(
        "--install",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="persist the generated asset in the project's Grade Graph",
    )
    sam2_mask_asset.set_defaults(handler=_sam2_mask_asset)

    tracked_mask_assets = subparsers.add_parser(
        "tracked-mask-assets",
        help=(
            "generate full-source Farneback-tracked semantic/depth assets "
            "with frozen model revisions and checkpoint provenance"
        ),
    )
    tracked_mask_assets.add_argument("project_id")
    tracked_mask_assets.add_argument("--output-root", required=True)
    tracked_mask_assets.add_argument("--output", required=True)
    tracked_mask_assets.add_argument(
        "--semantic-provider",
        choices=("segformer", "oneformer"),
        default="oneformer",
    )
    tracked_mask_assets.add_argument(
        "--semantic-model",
        default="shi-labs/oneformer_ade20k_swin_large",
    )
    tracked_mask_assets.add_argument(
        "--semantic-revision",
        default="4a5bac8e64f82681a12db2e151a4c2f4ce6092b2",
    )
    tracked_mask_assets.add_argument(
        "--depth-model",
        default="depth-anything/Depth-Anything-V2-Small-hf",
    )
    tracked_mask_assets.add_argument(
        "--depth-revision",
        default="5426e4f0f36572d16453bbda7a8389317b1bef99",
    )
    tracked_mask_assets.add_argument(
        "--targets",
        nargs="+",
        default=[
            "sky",
            "vegetation",
            "water",
            "mountain",
            "depth_far",
        ],
    )
    tracked_mask_assets.add_argument(
        "--inference-interval-seconds",
        type=float,
        default=1.5,
    )
    tracked_mask_assets.add_argument(
        "--maximum-edge",
        type=int,
        default=640,
    )
    tracked_mask_assets.add_argument(
        "--storage-bit-depth",
        type=int,
        choices=(8, 16),
        default=16,
    )
    tracked_mask_assets.add_argument(
        "--retain-mask-sequence",
        action=argparse.BooleanOptionalAction,
        default=False,
    )
    tracked_mask_assets.add_argument(
        "--install",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="persist generated assets in the project's Grade Graph",
    )
    tracked_mask_assets.set_defaults(handler=_tracked_mask_assets)

    cutie_shadow_observation = subparsers.add_parser(
        "cutie-shadow-observe",
        help=(
            "run exact-revision Cutie propagation from a real semantic "
            "anchor using project-local weights only"
        ),
    )
    cutie_shadow_observation.add_argument("video")
    cutie_shadow_observation.add_argument(
        "--source-registry",
        required=True,
    )
    cutie_shadow_observation.add_argument("--repository", required=True)
    cutie_shadow_observation.add_argument(
        "--masks-output",
        required=True,
    )
    cutie_shadow_observation.add_argument("--output", required=True)
    cutie_shadow_observation.add_argument(
        "--semantic-candidate",
        choices=(
            "current_segformer_b0",
            "segformer_b5",
            "oneformer_ade20k_swin_large",
        ),
        default="oneformer_ade20k_swin_large",
    )
    cutie_shadow_observation.add_argument(
        "--semantic-target",
        default="mountain",
    )
    cutie_shadow_observation.add_argument(
        "--maximum-frames",
        type=int,
        default=120,
    )
    cutie_shadow_observation.add_argument(
        "--maximum-internal-size",
        type=int,
        default=480,
    )
    cutie_shadow_observation.add_argument(
        "--media-origin",
        choices=(
            "camera_original",
            "camera_original_derived_clip",
            "licensed_stock",
            "published_dataset",
            "procedural",
        ),
        default="procedural",
    )
    cutie_shadow_observation.add_argument("--parent-source")
    cutie_shadow_observation.add_argument(
        "--source-start-seconds",
        type=float,
    )
    cutie_shadow_observation.set_defaults(
        handler=_cutie_shadow_observation
    )

    sea_raft_shadow_observation = subparsers.add_parser(
        "sea-raft-shadow-observe",
        help=(
            "run exact-revision SEA-RAFT locally and persist optical flow, "
            "native uncertainty, and forward/backward occlusion evidence"
        ),
    )
    sea_raft_shadow_observation.add_argument("video")
    sea_raft_shadow_observation.add_argument(
        "--source-registry",
        required=True,
    )
    sea_raft_shadow_observation.add_argument("--repository", required=True)
    sea_raft_shadow_observation.add_argument("--snapshot", required=True)
    sea_raft_shadow_observation.add_argument("--torch-home", required=True)
    sea_raft_shadow_observation.add_argument(
        "--flow-output",
        required=True,
    )
    sea_raft_shadow_observation.add_argument("--output", required=True)
    sea_raft_shadow_observation.add_argument(
        "--maximum-pairs",
        type=int,
        default=120,
    )
    sea_raft_shadow_observation.add_argument(
        "--media-origin",
        choices=(
            "camera_original",
            "camera_original_derived_clip",
            "licensed_stock",
            "published_dataset",
            "procedural",
        ),
        default="procedural",
    )
    sea_raft_shadow_observation.add_argument("--parent-source")
    sea_raft_shadow_observation.add_argument(
        "--source-start-seconds",
        type=float,
    )
    sea_raft_shadow_observation.set_defaults(
        handler=_sea_raft_shadow_observation
    )

    vos_shadow_evaluation = subparsers.add_parser(
        "vos-shadow-eval",
        help=(
            "compare Farneback, SAM 2.1/3.1, Cutie, and SEA-RAFT on frozen "
            "failure modes, temporal/boundary quality, licenses, platforms, and VRAM"
        ),
    )
    vos_shadow_evaluation.add_argument("--input", required=True)
    vos_shadow_evaluation.add_argument("--output", required=True)
    vos_shadow_evaluation.set_defaults(handler=_vos_shadow_evaluation)

    vos_platform_audit = subparsers.add_parser(
        "vos-platform-audit",
        help=(
            "audit Windows/WSL2/Linux CPU/CUDA/ROCm host prerequisites "
            "without claiming model runtime compatibility"
        ),
    )
    vos_platform_audit.add_argument("--output", required=True)
    vos_platform_audit.add_argument("--wsl-distribution")
    vos_platform_audit.add_argument(
        "--timeout-seconds",
        type=float,
        default=10,
    )
    vos_platform_audit.set_defaults(handler=_vos_platform_audit)

    depth_shadow_audit = subparsers.add_parser(
        "depth-shadow-audit",
        help="verify the frozen Apache-2.0 Video Depth Anything Small installation",
    )
    depth_shadow_audit.add_argument("--repository", required=True)
    depth_shadow_audit.add_argument("--checkpoint", required=True)
    depth_shadow_audit.add_argument("--output")
    depth_shadow_audit.set_defaults(handler=_depth_shadow_audit)

    depth_shadow = subparsers.add_parser(
        "depth-shadow",
        help="run shot-scoped Video Depth Anything Small without changing default masks",
    )
    depth_shadow.add_argument("video")
    depth_shadow.add_argument("--repository", required=True)
    depth_shadow.add_argument("--checkpoint", required=True)
    depth_shadow.add_argument("--python", default=sys.executable)
    depth_shadow.add_argument("--output", required=True)
    depth_shadow.add_argument("--report")
    depth_shadow.set_defaults(handler=_depth_shadow)

    provider_shadow = subparsers.add_parser(
        "creative-provider-shadow",
        help="run a transport-only scene probe without mutating the Grade Graph",
    )
    provider_shadow.add_argument("--scene-id", required=True)
    provider_shadow.add_argument(
        "--role",
        choices=tuple(role.value for role in CreativeRole),
        default=CreativeRole.DIRECTOR.value,
    )
    provider_shadow.add_argument("--prompt-file", required=True)
    provider_shadow.add_argument("--prompt-version", required=True)
    provider_shadow.add_argument("--image", action="append", default=[])
    provider_shadow.add_argument(
        "--image-detail",
        choices=("low", "high", "original", "auto"),
        default="low",
    )
    provider_shadow.add_argument("--estimated-input-tokens", type=int, required=True)
    provider_shadow.add_argument("--max-output-tokens", type=int, default=1_024)
    provider_shadow.add_argument("--input-token-budget", type=int, default=200_000)
    provider_shadow.add_argument("--output-token-budget", type=int, default=8_192)
    provider_shadow.add_argument("--maximum-cost-usd", type=float, default=1)
    provider_shadow.add_argument("--timeout", type=float, default=60)
    provider_shadow.add_argument("--maximum-retries", type=int, default=2)
    provider_shadow.add_argument("--requests-per-minute", type=int, default=10)
    provider_shadow.add_argument("--consent-cloud-upload", action="store_true")
    provider_shadow.add_argument("--confirm-cloud-run", action="store_true")
    provider_shadow.add_argument("--output", required=True)
    provider_shadow.set_defaults(handler=_creative_provider_shadow)
    return parser


def main() -> None:
    settings.ensure_directories()
    arguments = build_parser().parse_args()
    try:
        exit_code = arguments.handler(arguments)
    except Exception as exc:
        raise SystemExit(f"ColorGraph failed: {exc}") from exc
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
