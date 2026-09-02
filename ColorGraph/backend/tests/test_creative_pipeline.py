from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from test_creative_corpus import _write_corpus
from test_creative_evidence import (
    _budget as _evidence_budget,
)
from test_creative_evidence import (
    _cross_scene_graph,
    _write_evidence_video,
)

from colorgraph.agent.creative_contracts import (
    CritiqueDimension,
    ProjectContextPack,
    ProjectVisualThesis,
    canonical_sha256,
)
from colorgraph.agent.creative_corpus import (
    LoadedCreativeKnowledgeCorpus,
    load_creative_knowledge_corpus,
)
from colorgraph.agent.creative_critic import (
    BlindCandidateAssessment,
    BlindCriticRegion,
    BlindDimensionScore,
    BlindLabel,
    BlindPairwiseCriticOutput,
    BlindVisualEvidence,
    CalibrationPreference,
    CreativeModelIdentity,
    CriticCalibrationGate,
    CriticExpertCalibrationRecord,
    CriticModelRelationship,
    build_critic_calibration_gate,
)
from colorgraph.agent.creative_evidence import build_project_evidence_pack
from colorgraph.agent.creative_pipeline import (
    OfflineCreativePipelineRunner,
    OfflineCreativeRunRequest,
    build_offline_color_strategies,
    build_offline_visual_thesis,
)
from colorgraph.agent.creative_provider import (
    CreativeModelProvider,
    CreativeModelRequest,
    CreativeProviderRuntime,
    CreativeRole,
    ProviderBoundary,
    ProviderCapabilities,
    ProviderResponseCache,
    ProviderUsage,
    RawProviderResponse,
    RuntimeBudget,
    RuntimePolicy,
    provider_runtime_configuration_digest,
)
from colorgraph.agent.creative_retrieval import (
    CreativeKnowledgeIndex,
    RetrievalFilterContext,
    retrieve_creative_possibilities,
)
from colorgraph.agent.creative_search import (
    CandidateSearchBudget,
    CandidateSearchStatus,
    LocalCandidateFrameRenderer,
)
from colorgraph.agent.creative_strategy import (
    ColorGraphCapabilityCatalog,
    audit_color_strategy_set,
)
from colorgraph.agent.creative_ui import (
    AgentUIControlAction,
    AgentUIRunStatus,
    AgentUIStage,
    AgentUIStore,
)
from colorgraph.agent.operation_catalog import (
    build_renderer_capability_catalog,
)
from colorgraph.devices import TorchComputeBackend
from colorgraph.grading.looks import graph_digest

FIXED_TIME = datetime(2026, 7, 30, 7, tzinfo=UTC)


def _request(
    project_id: str,
    *,
    run_id: str,
    knowledge_corpus: LoadedCreativeKnowledgeCorpus | None = None,
    provider_runtime: CreativeProviderRuntime | None = None,
    critic_calibration_gate: CriticCalibrationGate | None = None,
    reflection_shadow_enabled: bool = False,
) -> OfflineCreativeRunRequest:
    return OfflineCreativeRunRequest(
        project_id=project_id,
        run_id=run_id,
        user_intent="Keep the sequence restrained.",
        created_at=FIXED_TIME,
        provider_shadow_enabled=provider_runtime is not None,
        reflection_shadow_enabled=reflection_shadow_enabled,
        provider_configuration_sha256=(
            provider_runtime_configuration_digest(provider_runtime)
            if provider_runtime is not None
            else None
        ),
        critic_calibration_sha256=(
            canonical_sha256(critic_calibration_gate)
            if critic_calibration_gate is not None
            else None
        ),
        knowledge_corpus_id=(
            knowledge_corpus.audit.corpus_id
            if knowledge_corpus is not None
            else None
        ),
        knowledge_corpus_version=(
            knowledge_corpus.audit.corpus_version
            if knowledge_corpus is not None
            else None
        ),
        knowledge_corpus_sha256=(
            knowledge_corpus.audit.corpus_sha256
            if knowledge_corpus is not None
            else None
        ),
        context_budget=_evidence_budget(),
        search_budget=CandidateSearchBudget(
            maximum_model_calls=(
                2 if reflection_shadow_enabled else 0
            ),
            maximum_rendered_frames=18,
            maximum_wall_seconds=60,
            maximum_cost_usd=0,
            maximum_refinements=(
                1 if reflection_shadow_enabled else 0
            ),
        ),
        maximum_pipeline_wall_seconds=120,
    )


def _project(tmp_path: Path):
    root = tmp_path / "creative-evidence"
    root.mkdir()
    source = root / "source.avi"
    _write_evidence_video(source)
    return root, source, _cross_scene_graph(source)


class _PipelineProvider(CreativeModelProvider):
    def __init__(
        self,
        graph,
        *,
        provider_id: str = "pipeline-provider",
        model_id: str = "pipeline-multimodal",
    ) -> None:
        self.provider_id = provider_id
        self.model_id = model_id
        self.model_revision = "frozen-test-v1"
        self.boundary = ProviderBoundary.LOCAL
        self.capabilities = ProviderCapabilities(
            image_input=True,
            strict_structured_output=True,
            maximum_context_tokens=300_000,
            maximum_images=64,
            batch_requests=True,
        )
        self.graph = graph
        self.context: ProjectContextPack | None = None
        self.thesis: ProjectVisualThesis | None = None
        self.calls = 0

    @staticmethod
    def _critic_output(payload: dict[str, Any]) -> BlindPairwiseCriticOutput:
        interpretations = {
            BlindLabel(item["label"]): item["brief"]["interpretation"]
            for item in payload["candidates"]
        }
        preferred = min(interpretations, key=lambda label: interpretations[label])
        manifest_by_label = {
            label: [
                item
                for item in payload["asset_manifest"]
                if item["label"] == label.value
            ]
            for label in BlindLabel
        }
        assessments: list[BlindCandidateAssessment] = []
        for label in BlindLabel:
            candidate_evidence = next(
                item["evidence_id"]
                for item in manifest_by_label[label]
                if item["role"] == "candidate"
            )
            source_evidence = next(
                item["evidence_id"]
                for item in manifest_by_label[label]
                if item["role"] == "source"
            )
            scores: list[BlindDimensionScore] = []
            for dimension in CritiqueDimension:
                score = (
                    0.2
                    if dimension == CritiqueDimension.OVERGRADING_RISK
                    and label == preferred
                    else 0.3
                    if dimension == CritiqueDimension.OVERGRADING_RISK
                    else 0.75
                    if label == preferred
                    else 0.55
                )
                scores.append(
                    BlindDimensionScore(
                        dimension=dimension,
                        score=score,
                        confidence=0.8,
                        evidence=[
                            BlindVisualEvidence(
                                evidence_id=candidate_evidence,
                                region=BlindCriticRegion(
                                    x=0,
                                    y=0,
                                    width=1,
                                    height=1,
                                ),
                                observation=(
                                    "The candidate preserves a coherent relationship "
                                    "between the central landscape and its surroundings."
                                ),
                            )
                        ],
                        counterevidence=[
                            BlindVisualEvidence(
                                evidence_id=source_evidence,
                                region=BlindCriticRegion(
                                    x=0,
                                    y=0,
                                    width=1,
                                    height=1,
                                ),
                                observation=(
                                    "The source leaves ambiguity around the same "
                                    "frame-region relationship."
                                ),
                            )
                        ],
                        concise_reason=(
                            "The cited frame regions support this dimension "
                            "without overriding deterministic QC."
                        ),
                    )
                )
            assessments.append(
                BlindCandidateAssessment(label=label, scores=scores)
            )
        candidate_ids = [
            next(
                item["evidence_id"]
                for item in manifest_by_label[label]
                if item["role"] == "candidate"
            )
            for label in BlindLabel
        ]
        return BlindPairwiseCriticOutput(
            assessments=assessments,
            preferred_label=preferred.value,
            preference_confidence=0.8,
            pairwise_evidence_ids=candidate_ids,
            pairwise_reason=(
                "The selected interpretation is more coherent with its cited "
                "frame-region evidence while preserving the declared constraints."
            ),
        )

    async def generate(
        self,
        request: CreativeModelRequest[Any],
        *,
        strict_schema: dict[str, Any],
    ) -> RawProviderResponse:
        assert strict_schema["type"] == "object"
        self.calls += 1
        payload = json.loads(request.prompt)
        if request.role == CreativeRole.DIRECTOR:
            self.context = ProjectContextPack.model_validate_json(
                json.dumps(payload["project_context_pack"])
            )
            self.thesis = build_offline_visual_thesis(
                context=self.context,
                graph=self.graph,
                user_intent=payload["user_intent"],
            )
            output = self.thesis
        elif request.role == CreativeRole.STRATEGIST:
            assert self.context is not None and self.thesis is not None
            catalog = ColorGraphCapabilityCatalog.model_validate_json(
                json.dumps(payload["capability_catalog"])
            )
            strategies = build_offline_color_strategies(
                thesis=self.thesis,
                context=self.context,
                baseline_asset_id=payload["technical_baseline_asset_id"],
                baseline_asset_sha256=(
                    payload["technical_baseline_asset_sha256"]
                ),
                retrieval_asset_sha256=(
                    payload["required_output_bindings"][
                        "retrieval_bundle_sha256"
                    ]
                ),
                catalog=catalog,
            )
            brief_id = payload["frozen_brief"]["brief_id"]
            output = next(
                item for item in strategies if item.brief_id == brief_id
            )
        elif request.role == CreativeRole.CRITIC:
            output = self._critic_output(payload)
        else:  # pragma: no cover - enum is exhaustive
            raise AssertionError(request.role)
        return RawProviderResponse(
            text=output.model_dump_json(),
            usage=ProviderUsage(
                input_tokens=100,
                output_tokens=100,
                total_tokens=200,
                estimated_cost_usd=0,
            ),
            response_id=f"pipeline-response-{self.calls}",
            model_revision=self.model_revision,
        )


def _pipeline_calibration_gate() -> CriticCalibrationGate:
    director_identity = CreativeModelIdentity(
        provider_id="pipeline-provider",
        model_id="pipeline-multimodal",
        model_revision="frozen-test-v1",
        prompt_version="closed-book-director/v3",
    )
    critic_identity = CreativeModelIdentity(
        provider_id="pipeline-critic-provider",
        model_id="pipeline-critic-multimodal",
        model_revision="frozen-test-v1",
        prompt_version="blind-visual-critic/v3",
    )
    records = [
        CriticExpertCalibrationRecord(
            record_id=f"{relationship.value}:{index}",
            pair_id=f"pair:{relationship.value}:{index}",
            source_id=f"source:{relationship.value}:{index}",
            model_relationship=relationship,
            critic_preference=(
                CalibrationPreference.LEFT
                if index % 2 == 0
                else CalibrationPreference.RIGHT
            ),
            expert_preference=(
                CalibrationPreference.LEFT
                if index % 2 == 0
                else CalibrationPreference.RIGHT
            ),
            position_swap_consistent=True,
            shortcut_violation=False,
            unsupported_evidence=False,
        )
        for relationship in CriticModelRelationship
        for index in range(24)
    ]
    return build_critic_calibration_gate(
        records,
        deployment_critic_identity=critic_identity,
        director_identity=director_identity,
    )


def test_offline_thesis_and_strategies_remain_typed_and_audited(
    tmp_path: Path,
) -> None:
    root, source, graph = _project(tmp_path)
    backend = TorchComputeBackend("cpu")
    evidence = build_project_evidence_pack(
        source=source,
        graph=graph,
        output_root=root / "evidence-only",
        backend=backend,
        budget=_evidence_budget(),
        created_at=FIXED_TIME,
    )
    thesis = build_offline_visual_thesis(
        context=evidence.context_pack,
        graph=graph,
        user_intent="Keep the sequence restrained.",
    )
    assert len(thesis.briefs) == 6
    assert {
        brief.direction.value for brief in thesis.briefs
    } == {"faithful", "amplified", "counterpoint"}

    catalog = build_renderer_capability_catalog(graph)
    index = CreativeKnowledgeIndex("offline-empty-index/v1")
    thesis_sha = canonical_sha256(thesis)
    retrieval_result = retrieve_creative_possibilities(
        thesis=thesis,
        thesis_asset_id=f"thesis:{thesis_sha[:20]}",
        thesis_sha256=thesis_sha,
        context=evidence.context_pack,
        index=index,
        filters=RetrievalFilterContext(
            media_type="video",
            color_domain=graph.working_color_space.value,
            scope="scene",
            available_capabilities=[
                item.capability_id for item in catalog.capabilities
            ],
            allowed_rights=["internal-authorized"],
            required_protections=list(thesis.shared_protections),
        ),
    )
    retrieval_sha = canonical_sha256(retrieval_result.bundle)
    strategies = build_offline_color_strategies(
        thesis=thesis,
        context=evidence.context_pack,
        baseline_asset_id=evidence.technical_baseline.asset_id,
        baseline_asset_sha256=evidence.technical_baseline.sha256,
        retrieval_asset_sha256=retrieval_sha,
        catalog=catalog,
    )
    audit = audit_color_strategy_set(
        strategies,
        briefs=thesis.briefs,
        thesis=thesis,
        retrieval=retrieval_result.bundle,
        retrieval_asset_sha256=retrieval_sha,
        context=evidence.context_pack,
        baseline=evidence.technical_baseline.payload,
        baseline_asset_id=evidence.technical_baseline.asset_id,
        baseline_asset_sha256=evidence.technical_baseline.sha256,
        catalog=catalog,
    )

    assert audit.valid is True
    assert len(strategies) == 6
    assert audit.structurally_distinct_pairs == audit.pair_count
    assert graph_digest(graph) == evidence.context_pack.graph_digest


def test_offline_pipeline_renders_real_multi_scene_candidates_without_graph_write(
    tmp_path: Path,
) -> None:
    root, source, graph = _project(tmp_path)
    original_digest = graph_digest(graph)
    request = _request(graph.project_id, run_id="run:complete")
    runner = OfflineCreativePipelineRunner(
        project_root=root,
        source=source,
        graph=graph,
        backend=TorchComputeBackend("cpu"),
        request=request,
    )
    runner.initialize()
    result = runner.run()

    assert result.cancelled is False
    assert result.search is not None
    assert result.search.state.status == CandidateSearchStatus.COMPLETE
    assert result.snapshot.status == AgentUIRunStatus.OFFLINE_FALLBACK
    assert result.snapshot.stage == AgentUIStage.READY
    assert result.snapshot.progress == 100
    assert result.snapshot.skipped_stages == [
        AgentUIStage.CRITICIZING,
        AgentUIStage.REFINING,
    ]
    assert len(result.snapshot.scenes) == 2
    assert all(len(scene.directions) == 3 for scene in result.snapshot.scenes)
    assert result.snapshot.selection.preferred_candidate_id is not None
    assert result.snapshot.selection.runner_up_candidate_id is not None
    assert result.snapshot.selection.requires_user_confirmation is True
    assert result.snapshot.current_graph_unchanged is True
    assert graph_digest(graph) == original_digest
    assert (root / "creative-agent" / "application-manifest.json").is_file()
    assert (runner.run_root / "pipeline-result.json").is_file()
    assert all(
        Path(sample.candidate_path).is_file()
        for record in result.search.state.candidates
        for sample in record.samples
    )


def test_offline_pipeline_uses_only_an_audited_content_bound_corpus(
    tmp_path: Path,
) -> None:
    corpus_path = _write_corpus(tmp_path / "corpus")
    knowledge_corpus = load_creative_knowledge_corpus(corpus_path)
    assert knowledge_corpus.index is not None
    root, source, graph = _project(tmp_path)
    request = _request(
        graph.project_id,
        run_id="run:authorized-corpus",
        knowledge_corpus=knowledge_corpus,
    )
    runner = OfflineCreativePipelineRunner(
        project_root=root,
        source=source,
        graph=graph,
        backend=TorchComputeBackend("cpu"),
        request=request,
        knowledge_index=knowledge_corpus.index,
        knowledge_corpus_audit=knowledge_corpus.audit,
    )
    runner.initialize()

    result = runner.run()

    assert result.cancelled is False
    corpus_audit_path = runner.run_root / "knowledge-corpus-audit.json"
    retrieval_audit_path = runner.run_root / "retrieval-audit.json"
    assert corpus_audit_path.is_file()
    retrieval_audit = json.loads(retrieval_audit_path.read_text(encoding="utf-8"))
    assert retrieval_audit["index_version"] == "creative-corpus-test:v1"
    assert all(
        len(route["hard_filters"]) == 6
        for route in retrieval_audit["route_audits"]
    )
    assert not any(
        "rights" in record["reasons"]
        for route in retrieval_audit["route_audits"]
        for record in route["hard_filters"]
    )


def test_provider_shadow_runs_director_strategists_and_blind_critic_without_graph_write(
    tmp_path: Path,
) -> None:
    root, source, graph = _project(tmp_path)
    original_digest = graph_digest(graph)
    provider = _PipelineProvider(graph)
    runtime = CreativeProviderRuntime(
        {role: provider for role in CreativeRole},
        policy=RuntimePolicy(
            network_enabled=False,
            cloud_provider_enabled=False,
            maximum_retries=0,
            maximum_concurrency=4,
            requests_per_minute=100,
        ),
        budget=RuntimeBudget(
            maximum_provider_attempts=20,
            maximum_input_tokens=200_000,
            maximum_output_tokens=200_000,
            maximum_cost_usd=1,
        ),
        cache=ProviderResponseCache(tmp_path / "provider-cache"),
    )
    request = _request(
        graph.project_id,
        run_id="run:provider-shadow",
        provider_runtime=runtime,
    )
    runner = OfflineCreativePipelineRunner(
        project_root=root,
        source=source,
        graph=graph,
        backend=TorchComputeBackend("cpu"),
        request=request,
        provider_runtime=runtime,
    )
    runner.initialize()

    result = runner.run()

    assert result.cancelled is False
    assert result.snapshot.status == AgentUIRunStatus.READY_FOR_REVIEW
    assert result.snapshot.skipped_stages == [AgentUIStage.REFINING]
    assert result.snapshot.provider.provider_id == "pipeline-provider"
    assert result.snapshot.provider.boundary == "local"
    assert graph_digest(graph) == original_digest
    assert provider.calls == 11
    director = json.loads(
        (runner.run_root / "director-provider-result.json").read_text(
            encoding="utf-8"
        )
    )
    strategists = json.loads(
        (runner.run_root / "strategist-provider-results.json").read_text(
            encoding="utf-8"
        )
    )
    critics = json.loads(
        (runner.run_root / "critic-provider-results.json").read_text(
            encoding="utf-8"
        )
    )
    pipeline = json.loads(
        (runner.run_root / "pipeline-result.json").read_text(encoding="utf-8")
    )
    assert director["status"] == "completed"
    assert strategists["provider_successes"] == 6
    assert critics["expected_pairs"] == critics["completed_pairs"] == 2
    assert pipeline["provider_pipeline_complete"] is True
    assert pipeline["critic_calibration_authorized"] is False
    assert any(
        direction.critique
        for scene in result.snapshot.scenes
        for direction in scene.directions
    )


def test_calibrated_opt_in_pipeline_executes_one_bounded_reflection_without_graph_write(
    tmp_path: Path,
) -> None:
    root, source, graph = _project(tmp_path)
    original_digest = graph_digest(graph)
    provider = _PipelineProvider(graph)
    critic_provider = _PipelineProvider(
        graph,
        provider_id="pipeline-critic-provider",
        model_id="pipeline-critic-multimodal",
    )
    runtime = CreativeProviderRuntime(
        {
            CreativeRole.DIRECTOR: provider,
            CreativeRole.STRATEGIST: provider,
            CreativeRole.CRITIC: critic_provider,
        },
        policy=RuntimePolicy(
            network_enabled=False,
            cloud_provider_enabled=False,
            maximum_retries=0,
            maximum_concurrency=4,
            requests_per_minute=100,
        ),
        budget=RuntimeBudget(
            maximum_provider_attempts=24,
            maximum_input_tokens=300_000,
            maximum_output_tokens=300_000,
            maximum_cost_usd=1,
        ),
        cache=ProviderResponseCache(tmp_path / "reflection-provider-cache"),
    )
    calibration = _pipeline_calibration_gate()
    request = _request(
        graph.project_id,
        run_id="run:provider-reflection-shadow",
        provider_runtime=runtime,
        critic_calibration_gate=calibration,
        reflection_shadow_enabled=True,
    )
    runner = OfflineCreativePipelineRunner(
        project_root=root,
        source=source,
        graph=graph,
        backend=TorchComputeBackend("cpu"),
        request=request,
        provider_runtime=runtime,
        critic_calibration_gate=calibration,
    )
    runner.initialize()

    result = runner.run()

    reflection = json.loads(
        (runner.run_root / "reflection-results.json").read_text(
            encoding="utf-8"
        )
    )
    pipeline = json.loads(
        (runner.run_root / "pipeline-result.json").read_text(encoding="utf-8")
    )
    assert result.cancelled is False
    assert result.snapshot.status == AgentUIRunStatus.READY_FOR_REVIEW
    assert result.snapshot.skipped_stages == []
    assert graph_digest(graph) == original_digest
    assert provider.calls + critic_provider.calls == 13
    assert critic_provider.calls == 6
    assert reflection["requested"] is True
    assert reflection["stage_executed"] is True
    assert reflection["completed"] is True
    assert reflection["current_graph_unchanged"] is True
    assert pipeline["provider_pipeline_complete"] is True
    assert pipeline["provider_requested_path_complete"] is True
    assert pipeline["reflection_requested"] is True
    assert pipeline["reflection_stage_executed"] is True
    assert pipeline["reflection_completed"] is True
    assert pipeline["current_graph_unchanged"] is True


def test_uncalibrated_reflection_shadow_executes_for_manual_review_but_cannot_auto_select(
    tmp_path: Path,
) -> None:
    root, source, graph = _project(tmp_path)
    original_digest = graph_digest(graph)
    provider = _PipelineProvider(graph)
    runtime = CreativeProviderRuntime(
        {role: provider for role in CreativeRole},
        policy=RuntimePolicy(
            network_enabled=False,
            cloud_provider_enabled=False,
            maximum_retries=0,
            maximum_concurrency=4,
            requests_per_minute=100,
        ),
        budget=RuntimeBudget(
            maximum_provider_attempts=24,
            maximum_input_tokens=300_000,
            maximum_output_tokens=300_000,
            maximum_cost_usd=1,
        ),
        cache=ProviderResponseCache(
            tmp_path / "uncalibrated-reflection-provider-cache"
        ),
    )
    request = _request(
        graph.project_id,
        run_id="run:uncalibrated-reflection-shadow",
        provider_runtime=runtime,
        reflection_shadow_enabled=True,
    )
    runner = OfflineCreativePipelineRunner(
        project_root=root,
        source=source,
        graph=graph,
        backend=TorchComputeBackend("cpu"),
        request=request,
        provider_runtime=runtime,
    )
    runner.initialize()

    result = runner.run()

    reflection = json.loads(
        (runner.run_root / "reflection-results.json").read_text(
            encoding="utf-8"
        )
    )
    pipeline = json.loads(
        (runner.run_root / "pipeline-result.json").read_text(encoding="utf-8")
    )
    assert result.snapshot.status == AgentUIRunStatus.READY_FOR_REVIEW
    assert result.snapshot.selection.automatic_selection_allowed is False
    assert result.snapshot.selection.requires_user_confirmation is True
    assert graph_digest(graph) == original_digest
    assert provider.calls == 13
    assert reflection["stage_executed"] is True
    assert reflection["completed"] is True
    assert reflection["automatic_selection_allowed"] is False
    assert reflection["requires_user_confirmation"] is True
    assert reflection["release_effect"] == "none_shadow_only"
    assert pipeline["critic_calibration_authorized"] is False
    assert pipeline["reflection_automatic_selection_allowed"] is False
    assert pipeline["user_confirmation_required"] is True
    assert pipeline["current_graph_unchanged"] is True


class _CancelAfterFirstRender:
    def __init__(
        self,
        delegate: LocalCandidateFrameRenderer,
        ui_store: AgentUIStore,
    ) -> None:
        self.delegate = delegate
        self.ui_store = ui_store
        self.renderer_version = delegate.renderer_version
        self.calls = 0
        self.cancel_once = True

    def render(self, **kwargs):
        rendered = self.delegate.render(**kwargs)
        self.calls += 1
        if self.cancel_once:
            self.cancel_once = False
            snapshot = self.ui_store.load_snapshot()
            assert snapshot is not None
            self.ui_store.request_control(
                AgentUIControlAction.CANCEL,
                expected_revision=snapshot.snapshot_revision,
                requested_at=FIXED_TIME,
            )
        return rendered


def test_offline_pipeline_cancel_and_resume_reuse_persisted_candidates(
    tmp_path: Path,
) -> None:
    root, source, graph = _project(tmp_path)
    request = _request(graph.project_id, run_id="run:resume")
    backend = TorchComputeBackend("cpu")
    ui_store = AgentUIStore(root)
    renderer = _CancelAfterFirstRender(
        LocalCandidateFrameRenderer(
            source=source,
            backend=backend,
            maximum_width=256,
        ),
        ui_store,
    )
    first_runner = OfflineCreativePipelineRunner(
        project_root=root,
        source=source,
        graph=graph,
        backend=backend,
        request=request,
        ui_store=ui_store,
        renderer=renderer,
    )
    first_runner.initialize()
    cancelled = first_runner.run()

    assert cancelled.cancelled is True
    assert cancelled.snapshot.status == AgentUIRunStatus.CANCELLED
    assert cancelled.search is not None
    assert len(cancelled.search.state.candidates) == 1
    assert renderer.calls == 1

    resumed_request = OfflineCreativePipelineRunner.load_request(
        root,
        request.run_id,
    )
    ui_store.request_control(
        AgentUIControlAction.RESUME,
        expected_revision=cancelled.snapshot.snapshot_revision,
        requested_at=FIXED_TIME,
    )
    resumed = OfflineCreativePipelineRunner(
        project_root=root,
        source=source,
        graph=graph,
        backend=backend,
        request=resumed_request,
        ui_store=ui_store,
        renderer=renderer,
    ).run()

    assert resumed.cancelled is False
    assert resumed.snapshot.status == AgentUIRunStatus.OFFLINE_FALLBACK
    assert resumed.search is not None
    assert len(resumed.search.state.candidates) == 6
    assert resumed.search.state.usage.cache_hits == 0
    assert renderer.calls == 6
