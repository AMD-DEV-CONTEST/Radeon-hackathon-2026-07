from __future__ import annotations

import hashlib
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image
from test_creative_compiler import (
    BASELINE_ASSET_ID,
    BASELINE_ASSET_SHA,
    _baseline,
    _cards,
    _graph,
    _policy,
    _strategy,
)
from test_creative_retrieval import _sha

from colorgraph.agent.creative_compiler import (
    MANDATORY_COMPILER_QC_CHECKS,
    CompilationPolicy,
    OperationCardRegistry,
    compile_color_strategy,
)
from colorgraph.agent.creative_contracts import (
    AdjustmentDirection,
    ColorLanguageCue,
    ColorProperty,
    ContextBudget,
    CreativeBrief,
    CreativeDirection,
    EvidenceKind,
    EvidenceReference,
    ProjectContextPack,
    VisualHierarchyItem,
)
from colorgraph.agent.creative_search import (
    BudgetedCandidateSearchRunner,
    CandidateAttemptStatus,
    CandidateSearchBudget,
    CandidateSearchStatus,
    CandidateSearchStore,
    DeterministicSearchHardGates,
    LocalCandidateFrameRenderer,
    RenderedSearchSample,
    SearchCandidateInput,
    SearchHardGateCheck,
    SearchQCEvaluation,
    select_candidate_samples,
)
from colorgraph.devices import TorchComputeBackend
from colorgraph.domain.grade_graph import (
    ColorSpace,
    GradeGraph,
    MaskAsset,
    MediaInfo,
    SpatialKind,
    TimeRange,
)
from colorgraph.grading.looks import graph_digest
from colorgraph.services.graph_builder import build_initial_graph


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _context(graph: GradeGraph) -> ProjectContextPack:
    return ProjectContextPack(
        technical_baseline_asset_id=BASELINE_ASSET_ID,
        technical_baseline_sha256=BASELINE_ASSET_SHA,
        graph_digest=graph_digest(graph),
        evidence_bundle_schema_version="colorgraph.agent-evidence-bundle/v1",
        evidence_bundle_digest=_sha("search-evidence"),
        allowed_scene_ids=["scene_001"],
        allowed_shot_ids=["shot_001"],
        evidence=[
            EvidenceReference(
                evidence_id="frame:001",
                kind=EvidenceKind.FRAME,
                digest=_sha("frame-001"),
                summary="A restrained lake and sky frame with visible highlight detail.",
                frame_index=125,
                scene_id="scene_001",
                shot_id="shot_001",
            ),
            EvidenceReference(
                evidence_id="measurement:001",
                kind=EvidenceKind.MEASUREMENT,
                digest=_sha("measurement-001"),
                summary="The source is finite and retains highlight structure.",
                scene_id="scene_001",
                shot_id="shot_001",
            ),
        ],
        budget=ContextBudget(
            maximum_images=8,
            maximum_image_edge=960,
            maximum_audio_seconds=0,
            maximum_tokens=8_000,
            maximum_context_bytes=8_000_000,
        ),
        omitted_evidence_ids=[],
    )


def _brief(
    direction: CreativeDirection,
    *,
    scene_id: str = "scene_001",
) -> CreativeBrief:
    brief_id = (
        f"brief:{direction.value}"
        if scene_id == "scene_001"
        else f"brief:{scene_id}:{direction.value}"
    )
    return CreativeBrief(
        brief_id=brief_id,
        scene_id=scene_id,
        direction=direction,
        interpretation=f"A grounded {direction.value} reading of the source scene.",
        evidence_for=["frame:001"],
        evidence_against=["measurement:001"],
        emotional_target=f"{direction.value} attention",
        visual_hierarchy=[
            VisualHierarchyItem(
                target=f"target-{direction.value}",
                priority=1,
                rationale="The lake reflection is the cited visual anchor.",
                evidence_ids=["frame:001"],
            )
        ],
        possible_color_language=[
            ColorLanguageCue(
                target=f"target-{direction.value}",
                property=ColorProperty.CONTRAST,
                direction=AdjustmentDirection.CONTEXT_DEPENDENT,
                minimum_strength=0,
                maximum_strength=0.3,
                rationale="Keep the direction bounded by source evidence.",
            )
        ],
        cliche_risks=["Avoid a generic landscape preset."],
        confidence=0.7,
        uncertainties=[],
        failure_conditions=["The reflection loses structure."],
    )


def _strategies_and_inputs(
    graph: GradeGraph,
    *,
    compiled_variants: int = 0,
) -> tuple[list[SearchCandidateInput], dict[str, list]]:
    inputs: list[SearchCandidateInput] = []
    compiled_by_brief: dict[str, list] = {}
    for direction in CreativeDirection:
        brief = _brief(direction)
        base = _strategy()
        actions = [
            action.model_copy(
                update={"serves_brief_id": brief.brief_id}
            )
            for action in base.actions
        ]
        strategy = base.model_copy(
            update={
                "strategy_id": f"strategy:{direction.value}",
                "brief_id": brief.brief_id,
                "actions": actions,
            }
        )
        compilation = compile_color_strategy(
            strategy,
            source_graph=graph,
            expected_source_graph_digest=graph_digest(graph),
            technical_baseline=_baseline(graph),
            baseline_asset_id=BASELINE_ASSET_ID,
            baseline_asset_sha256=BASELINE_ASSET_SHA,
            registry=OperationCardRegistry(_cards()),
            policy=CompilationPolicy(
                maximum_variants=compiled_variants,
                variation_fraction=0.25,
                non_waivable_qc_checks=sorted(MANDATORY_COMPILER_QC_CHECKS),
            ),
        )
        compiled_by_brief[brief.brief_id] = list(compilation.candidates)
        inputs.append(
            SearchCandidateInput(
                brief=brief,
                strategy=strategy,
                compiled=compilation.candidates[0],
            )
        )
    return inputs, compiled_by_brief


def _multi_scene_graph() -> GradeGraph:
    graph = build_initial_graph(
        project_id="project:test",
        project_name="Multi Scene Search",
        media=MediaInfo(
            path="source.mp4",
            duration_seconds=10,
            width=640,
            height=360,
            fps=25,
            frame_count=250,
            codec="h264",
            input_color_space=ColorSpace.BT709_OETF,
        ),
        shot_ranges=[
            TimeRange(start_seconds=0, end_seconds=5),
            TimeRange(start_seconds=5, end_seconds=10),
        ],
        representative_frames=[Path("shot-1.jpg"), Path("shot-2.jpg")],
        scene_groups=[[0], [1]],
    )
    payload = graph.model_dump(mode="python")
    payload["masks"] = [
        MaskAsset(
            id="mask:sky",
            kind=SpatialKind.SEMANTIC,
            target="sky",
            path="masks/sky",
            frame_count=250,
        ).model_dump(mode="python")
    ]
    return GradeGraph.model_validate(payload)


def _multi_scene_context(graph: GradeGraph) -> ProjectContextPack:
    evidence = []
    for index in range(2):
        scene_id = f"scene_{index + 1:03d}"
        shot_id = f"shot_{index + 1:03d}"
        evidence.extend(
            [
                EvidenceReference(
                    evidence_id=f"frame:{index + 1:03d}",
                    kind=EvidenceKind.FRAME,
                    digest=_sha(f"frame-{index}"),
                    summary=f"Representative evidence for {scene_id}.",
                    frame_index=50 + index * 125,
                    scene_id=scene_id,
                    shot_id=shot_id,
                ),
                EvidenceReference(
                    evidence_id=f"measurement:{index + 1:03d}",
                    kind=EvidenceKind.MEASUREMENT,
                    digest=_sha(f"measurement-{index}"),
                    summary=f"Finite source measurements for {scene_id}.",
                    scene_id=scene_id,
                    shot_id=shot_id,
                ),
            ]
        )
    return ProjectContextPack(
        technical_baseline_asset_id=BASELINE_ASSET_ID,
        technical_baseline_sha256=BASELINE_ASSET_SHA,
        graph_digest=graph_digest(graph),
        evidence_bundle_schema_version="colorgraph.agent-evidence-bundle/v1",
        evidence_bundle_digest=_sha("multi-scene-evidence"),
        allowed_scene_ids=["scene_001", "scene_002"],
        allowed_shot_ids=["shot_001", "shot_002"],
        evidence=evidence,
        budget=ContextBudget(
            maximum_images=12,
            maximum_image_edge=960,
            maximum_audio_seconds=0,
            maximum_tokens=12_000,
            maximum_context_bytes=12_000_000,
        ),
        omitted_evidence_ids=[],
    )


def _multi_scene_inputs(graph: GradeGraph) -> list[SearchCandidateInput]:
    inputs = []
    for scene_index in range(2):
        scene_id = f"scene_{scene_index + 1:03d}"
        for direction in CreativeDirection:
            brief = _brief(direction, scene_id=scene_id)
            base = _strategy()
            actions = [
                action.model_copy(
                    update={
                        "serves_brief_id": brief.brief_id,
                        "scope": action.scope.model_copy(
                            update={"scene_id": scene_id}
                        ),
                    }
                )
                for action in base.actions
            ]
            strategy = base.model_copy(
                update={
                    "strategy_id": f"strategy:{scene_id}:{direction.value}",
                    "brief_id": brief.brief_id,
                    "actions": actions,
                }
            )
            compiled = compile_color_strategy(
                strategy,
                source_graph=graph,
                expected_source_graph_digest=graph_digest(graph),
                technical_baseline=_baseline(graph),
                baseline_asset_id=BASELINE_ASSET_ID,
                baseline_asset_sha256=BASELINE_ASSET_SHA,
                registry=OperationCardRegistry(_cards()),
                policy=_policy(maximum_variants=0),
            ).candidates[0]
            inputs.append(
                SearchCandidateInput(
                    brief=brief,
                    strategy=strategy,
                    compiled=compiled,
                )
            )
    return inputs


class _FakeRenderer:
    renderer_version = "fake-colorgraph-renderer/v1"

    def __init__(self, *, fail_directions: set[CreativeDirection] | None = None) -> None:
        self.fail_directions = fail_directions or set()
        self.calls = 0
        self.candidate_ids: list[str] = []

    def render(
        self,
        *,
        candidate,
        current_graph,
        samples,
        output_dir,
    ):
        del current_graph
        self.calls += 1
        self.candidate_ids.append(candidate.compiled.contract.candidate_id)
        if candidate.brief.direction in self.fail_directions:
            raise RuntimeError(f"synthetic failure for {candidate.brief.direction.value}")
        output_dir.mkdir(parents=True, exist_ok=True)
        direction_offset = {
            CreativeDirection.FAITHFUL: 0,
            CreativeDirection.AMPLIFIED: 10,
            CreativeDirection.COUNTERPOINT: -10,
        }[candidate.brief.direction]
        rendered = []
        for sample in samples:
            stem = f"{sample.frame_index:08d}"
            source_path = output_dir / f"{stem}-source.png"
            current_path = output_dir / f"{stem}-current.png"
            candidate_path = output_dir / f"{stem}-candidate.png"
            Image.new("RGB", (32, 18), (100, 110, 120)).save(source_path)
            Image.new("RGB", (32, 18), (105, 115, 125)).save(current_path)
            value = 115 + direction_offset
            Image.new("RGB", (32, 18), (value, value + 5, value + 10)).save(
                candidate_path
            )
            rendered.append(
                RenderedSearchSample(
                    frame_index=sample.frame_index,
                    time_seconds=sample.time_seconds,
                    source_path=str(source_path.resolve()),
                    source_sha256=_digest(source_path),
                    current_path=str(current_path.resolve()),
                    current_sha256=_digest(current_path),
                    candidate_path=str(candidate_path.resolve()),
                    candidate_sha256=_digest(candidate_path),
                    width=32,
                    height=18,
                )
            )
        return rendered


class _DirectionalQC:
    def __init__(self, hard_fail: set[CreativeDirection] | None = None) -> None:
        self.hard_fail = hard_fail or set()

    def evaluate(self, *, candidate, samples, required_check_ids):
        passed = candidate.brief.direction not in self.hard_fail
        checks = [
            SearchHardGateCheck(
                check_id=check_id,
                passed=passed,
                observed=0 if passed else 1,
                threshold=0,
                detail=(
                    "Synthetic hard gate passed."
                    if passed
                    else "Synthetic hard gate failed."
                ),
                frame_indices=[item.frame_index for item in samples],
            )
            for check_id in required_check_ids
        ]
        return SearchQCEvaluation(
            hard_passed=passed,
            checks=checks,
            required_check_ids=required_check_ids,
            technical_margin=1 if passed else 0,
        )


def _budget(
    *,
    frames: int = 20,
    calls: int = 10,
    cost: float = 10,
    refinements: int = 1,
) -> CandidateSearchBudget:
    return CandidateSearchBudget(
        maximum_model_calls=calls,
        maximum_rendered_frames=frames,
        maximum_wall_seconds=60,
        maximum_cost_usd=cost,
        maximum_refinements=refinements,
    )


def test_search_renders_three_directions_persists_assets_and_is_idempotent(
    tmp_path: Path,
) -> None:
    graph = _graph()
    inputs, _ = _strategies_and_inputs(graph)
    source_before = graph.model_dump(mode="json")
    renderer = _FakeRenderer()
    store = CandidateSearchStore(tmp_path / "search")
    runner = BudgetedCandidateSearchRunner(
        renderer=renderer,
        qc_evaluator=DeterministicSearchHardGates(),
        store=store,
    )

    first = runner.run(
        run_id="run:complete",
        context=_context(graph),
        current_graph=graph,
        candidates=inputs,
        budget=_budget(frames=9),
    )
    second = runner.run(
        run_id="run:complete",
        context=_context(graph),
        current_graph=graph,
        candidates=inputs,
        budget=_budget(frames=9),
    )

    assert first.state.status == CandidateSearchStatus.COMPLETE
    assert len(first.state.candidates) == 3
    assert len(first.survivors) == 3
    assert first.state.preferred_candidate_id is not None
    assert first.state.runner_up_candidate_id is not None
    assert first.state.selection_status == "provisional-no-critic"
    assert first.state.usage.rendered_frames == 9
    assert renderer.calls == 3
    assert second.state == first.state
    assert graph.model_dump(mode="json") == source_before
    for record in first.state.candidates:
        assert Path(record.graph_path).is_file()
        assert Path(record.undo_graph_path).is_file()
        assert Path(record.contract_path).is_file()
        assert len(record.samples) == 3


def test_cancelled_search_resumes_without_repeating_completed_candidates(
    tmp_path: Path,
) -> None:
    graph = _graph()
    inputs, _ = _strategies_and_inputs(graph)
    renderer = _FakeRenderer()
    runner = BudgetedCandidateSearchRunner(
        renderer=renderer,
        qc_evaluator=_DirectionalQC(),
        store=CandidateSearchStore(tmp_path / "search"),
    )

    cancelled = runner.run(
        run_id="run:resume",
        context=_context(graph),
        current_graph=graph,
        candidates=inputs,
        budget=_budget(frames=9),
        cancel_check=lambda: renderer.calls >= 1,
    )
    resumed = runner.run(
        run_id="run:resume",
        context=_context(graph),
        current_graph=graph,
        candidates=inputs,
        budget=_budget(frames=9),
    )

    assert cancelled.state.status == CandidateSearchStatus.CANCELLED
    assert len(cancelled.state.candidates) == 1
    assert resumed.state.status == CandidateSearchStatus.COMPLETE
    assert len(resumed.state.candidates) == 3
    assert renderer.calls == 3
    assert resumed.state.usage.rendered_frames == 9


def test_multi_scene_search_resumes_and_reruns_idempotently(
    tmp_path: Path,
) -> None:
    graph = _multi_scene_graph()
    context = _multi_scene_context(graph)
    inputs = _multi_scene_inputs(graph)
    renderer = _FakeRenderer()
    runner = BudgetedCandidateSearchRunner(
        renderer=renderer,
        qc_evaluator=_DirectionalQC(),
        store=CandidateSearchStore(tmp_path / "multi-search"),
    )

    interrupted = runner.run(
        run_id="run:multi-scene",
        context=context,
        current_graph=graph,
        candidates=inputs,
        budget=_budget(frames=18),
        cancel_check=lambda: renderer.calls >= 2,
    )
    resumed = runner.run(
        run_id="run:multi-scene",
        context=context,
        current_graph=graph,
        candidates=inputs,
        budget=_budget(frames=18),
    )
    idempotent = runner.run(
        run_id="run:multi-scene",
        context=context,
        current_graph=graph,
        candidates=inputs,
        budget=_budget(frames=18),
    )

    assert interrupted.state.status == CandidateSearchStatus.CANCELLED
    assert len(interrupted.state.candidates) == 2
    assert resumed.state.status == CandidateSearchStatus.COMPLETE
    assert len(resumed.state.candidates) == 6
    assert {item.scene_id for item in resumed.state.candidates} == {
        "scene_001",
        "scene_002",
    }
    assert renderer.calls == 6
    assert idempotent.state == resumed.state


def test_render_model_and_cost_budgets_hold_on_success_and_failure(
    tmp_path: Path,
) -> None:
    graph = _graph()
    inputs, _ = _strategies_and_inputs(graph)
    budgeted_inputs = [
        SearchCandidateInput(
            brief=item.brief,
            strategy=item.strategy,
            compiled=item.compiled,
            model_calls=1,
            model_cost_usd=0.2,
        )
        for item in inputs
    ]
    renderer = _FakeRenderer(
        fail_directions={
            CreativeDirection.FAITHFUL,
            CreativeDirection.AMPLIFIED,
            CreativeDirection.COUNTERPOINT,
        }
    )
    runner = BudgetedCandidateSearchRunner(
        renderer=renderer,
        qc_evaluator=_DirectionalQC(),
        store=CandidateSearchStore(tmp_path / "failure-search"),
    )

    exhausted = runner.run(
        run_id="run:budget",
        context=_context(graph),
        current_graph=graph,
        candidates=budgeted_inputs,
        budget=_budget(frames=7, calls=2, cost=0.4),
    )

    assert exhausted.state.status == CandidateSearchStatus.BUDGET_EXHAUSTED
    assert len(exhausted.state.candidates) == 2
    assert all(
        item.status == CandidateAttemptStatus.RENDER_FAILED
        for item in exhausted.state.candidates
    )
    assert exhausted.state.usage.rendered_frames == 6
    assert exhausted.state.usage.model_calls == 2
    assert exhausted.state.usage.cost_usd == pytest.approx(0.4)
    assert renderer.calls == 2


def test_wall_budget_stops_after_the_first_indivisible_render_overrun(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _graph()
    inputs, _ = _strategies_and_inputs(graph)
    clock = [0.0]
    renderer = _FakeRenderer()
    original_render = renderer.render

    def slow_render(**kwargs):
        rendered = original_render(**kwargs)
        clock[0] += 2
        return rendered

    monkeypatch.setattr(
        "colorgraph.agent.creative_search.time.perf_counter",
        lambda: clock[0],
    )
    monkeypatch.setattr(renderer, "render", slow_render)
    runner = BudgetedCandidateSearchRunner(
        renderer=renderer,
        qc_evaluator=_DirectionalQC(),
        store=CandidateSearchStore(tmp_path / "wall-search"),
    )

    result = runner.run(
        run_id="run:wall",
        context=_context(graph),
        current_graph=graph,
        candidates=inputs,
        budget=CandidateSearchBudget(
            maximum_model_calls=10,
            maximum_rendered_frames=9,
            maximum_wall_seconds=1,
            maximum_cost_usd=10,
            maximum_refinements=1,
        ),
    )

    assert result.state.status == CandidateSearchStatus.BUDGET_EXHAUSTED
    assert renderer.calls == 1
    assert len(result.state.candidates) == 1
    assert result.state.usage.wall_seconds == 2


def test_non_waivable_qc_failure_is_preserved_and_never_compensated(
    tmp_path: Path,
) -> None:
    graph = _graph()
    inputs, _ = _strategies_and_inputs(graph)
    runner = BudgetedCandidateSearchRunner(
        renderer=_FakeRenderer(),
        qc_evaluator=_DirectionalQC({CreativeDirection.AMPLIFIED}),
        store=CandidateSearchStore(tmp_path / "qc-search"),
    )

    result = runner.run(
        run_id="run:qc",
        context=_context(graph),
        current_graph=graph,
        candidates=inputs,
        budget=_budget(frames=9),
        ranker=lambda records: list(
            reversed([item.candidate_id for item in records])
        ),
    )
    failed = next(
        item
        for item in result.state.candidates
        if item.direction == CreativeDirection.AMPLIFIED
    )

    assert failed.status == CandidateAttemptStatus.HARD_FAIL
    assert failed.candidate_id not in result.state.survivor_candidate_ids
    assert failed.qc is not None
    assert all(not item.passed for item in failed.qc.checks)
    assert len(result.survivors) == 2
    assert result.state.selection_status == "external-ranked-hard-pass"


def test_one_refinement_is_allowed_and_preserves_parent_direction(
    tmp_path: Path,
) -> None:
    graph = _graph()
    base, compiled = _strategies_and_inputs(graph, compiled_variants=1)
    amplified = next(
        item for item in base if item.brief.direction == CreativeDirection.AMPLIFIED
    )
    refinement = SearchCandidateInput(
        brief=amplified.brief,
        strategy=amplified.strategy,
        compiled=compiled[amplified.brief.brief_id][1],
        is_refinement=True,
        parent_candidate_id=amplified.compiled.contract.candidate_id,
    )
    runner = BudgetedCandidateSearchRunner(
        renderer=_FakeRenderer(),
        qc_evaluator=_DirectionalQC(),
        store=CandidateSearchStore(tmp_path / "refinement-search"),
    )

    result = runner.run(
        run_id="run:refinement",
        context=_context(graph),
        current_graph=graph,
        candidates=[*base, refinement],
        budget=_budget(frames=12, refinements=1),
    )

    assert result.state.status == CandidateSearchStatus.COMPLETE
    assert len(result.state.candidates) == 4
    assert result.state.usage.refinements == 1
    refined_record = next(item for item in result.state.candidates if item.is_refinement)
    assert refined_record.parent_candidate_id == amplified.compiled.contract.candidate_id
    with pytest.raises(ValueError, match="refinement budget"):
        runner.run(
            run_id="run:no-refinement",
            context=_context(graph),
            current_graph=graph,
            candidates=[*base, refinement],
            budget=_budget(frames=12, refinements=0),
        )


def test_plan_validation_rejects_missing_direction_and_stale_resume(
    tmp_path: Path,
) -> None:
    graph = _graph()
    inputs, _ = _strategies_and_inputs(graph)
    store = CandidateSearchStore(tmp_path / "plan-search")
    runner = BudgetedCandidateSearchRunner(
        renderer=_FakeRenderer(),
        qc_evaluator=_DirectionalQC(),
        store=store,
    )

    with pytest.raises(ValueError, match="one nominal candidate"):
        runner.run(
            run_id="run:missing",
            context=_context(graph),
            current_graph=graph,
            candidates=inputs[:2],
            budget=_budget(),
        )

    runner.run(
        run_id="run:bound",
        context=_context(graph),
        current_graph=graph,
        candidates=inputs,
        budget=_budget(frames=9),
    )
    changed_context = _context(graph).model_copy(
        update={"evidence_bundle_digest": _sha("changed-evidence")}
    )
    with pytest.raises(ValueError, match="another plan"):
        runner.run(
            run_id="run:bound",
            context=changed_context,
            current_graph=graph,
            candidates=inputs,
            budget=_budget(frames=9),
        )
    with pytest.raises(ValueError, match="another plan"):
        runner.run(
            run_id="run:bound",
            context=_context(graph),
            current_graph=graph,
            candidates=inputs,
            budget=_budget(frames=10),
        )


def test_corrupt_or_missing_cache_assets_are_not_reused(tmp_path: Path) -> None:
    graph = _graph()
    inputs, _ = _strategies_and_inputs(graph)
    store = CandidateSearchStore(tmp_path / "cache-search")
    renderer = _FakeRenderer()
    runner = BudgetedCandidateSearchRunner(
        renderer=renderer,
        qc_evaluator=_DirectionalQC(),
        store=store,
    )
    result = runner.run(
        run_id="run:cache",
        context=_context(graph),
        current_graph=graph,
        candidates=inputs,
        budget=_budget(frames=12),
    )
    record = result.state.candidates[0]
    assert store.load_render_cache("run:cache", record.cache_key) is not None

    Path(record.samples[0].candidate_path).write_bytes(b"corrupt")

    assert store.load_render_cache("run:cache", record.cache_key) is None
    repaired = runner.run(
        run_id="run:cache",
        context=_context(graph),
        current_graph=graph,
        candidates=inputs,
        budget=_budget(frames=12),
    )

    assert repaired.state.status == CandidateSearchStatus.COMPLETE
    assert renderer.calls == 4
    assert repaired.state.usage.rendered_frames == 12
    assert repaired.state.usage.candidate_attempts == 4
    assert len(repaired.state.candidates) == 3
    repaired_record = next(
        item
        for item in repaired.state.candidates
        if item.candidate_id == record.candidate_id
    )
    assert repaired_record.cache_hit is False
    assert store.load_render_cache(
        "run:cache",
        repaired_record.cache_key,
    ) == repaired_record.samples


def _write_video(path: Path) -> None:
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"MJPG"),
        10,
        (64, 36),
    )
    if not writer.isOpened():
        raise RuntimeError("OpenCV MJPEG writer is unavailable")
    try:
        for index in range(20):
            gradient = np.linspace(30, 210, 64, dtype=np.uint8)
            frame = np.broadcast_to(gradient, (36, 64))
            rgb = np.stack(
                (
                    np.roll(frame, index % 4, axis=1),
                    frame,
                    np.flip(frame, axis=1),
                ),
                axis=2,
            )
            writer.write(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    finally:
        writer.release()


def test_local_renderer_uses_real_source_frames_and_colorgraph_engine(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.avi"
    _write_video(source)
    graph = build_initial_graph(
        project_id="project:test",
        project_name="Local Search Render",
        media=MediaInfo(
            path=str(source),
            duration_seconds=2,
            width=64,
            height=36,
            fps=10,
            frame_count=20,
            codec="mjpeg",
            input_color_space=ColorSpace.BT709_OETF,
        ),
        shot_ranges=[TimeRange(start_seconds=0, end_seconds=2)],
        representative_frames=[Path("shot.jpg")],
        scene_groups=[[0]],
    )
    base = _strategy()
    tone_only = base.model_copy(update={"actions": [base.actions[0]]})
    card = _cards()[0]
    compiled = compile_color_strategy(
        tone_only,
        source_graph=graph,
        expected_source_graph_digest=graph_digest(graph),
        technical_baseline=_baseline(graph),
        baseline_asset_id=BASELINE_ASSET_ID,
        baseline_asset_sha256=BASELINE_ASSET_SHA,
        registry=OperationCardRegistry([card]),
        policy=_policy(maximum_variants=0),
    ).candidates[0]
    candidate = SearchCandidateInput(
        brief=_brief(CreativeDirection.AMPLIFIED),
        strategy=tone_only,
        compiled=compiled,
    )
    # The production renderer is exercised directly here; the full runner's
    # three-direction and budget behavior is covered by the deterministic fake.
    renderer = LocalCandidateFrameRenderer(
        source=source,
        backend=TorchComputeBackend("cpu"),
        maximum_width=64,
    )
    context = _context(graph).model_copy(
        update={
            "evidence": [
                _context(graph).evidence[0].model_copy(
                    update={"frame_index": 10}
                ),
                _context(graph).evidence[1],
            ]
        }
    )
    samples = select_candidate_samples(
        scene_id="scene_001",
        context=context,
        graph=graph,
        maximum_samples=1,
    )
    rendered = renderer.render(
        candidate=candidate,
        current_graph=graph,
        samples=samples,
        output_dir=tmp_path / "rendered",
    )

    assert len(rendered) == 1
    assert Path(rendered[0].source_path).is_file()
    assert Path(rendered[0].current_path).is_file()
    assert Path(rendered[0].candidate_path).is_file()
    assert rendered[0].source_sha256 != rendered[0].candidate_sha256
    assert rendered[0].unclamped_finite_invalid == 0
    raw_gate = DeterministicSearchHardGates().evaluate(
        candidate=candidate,
        samples=[
            rendered[0].model_copy(
                update={"unclamped_output_outside_ratio": 0.25}
            )
        ],
        required_check_ids=["legal_output_gamut"],
    )
    assert raw_gate.hard_passed is False
    assert raw_gate.checks[0].observed == 0.25

    first_input_digest = renderer.input_digest(graph)
    source.write_bytes(source.read_bytes() + b"\0")
    assert renderer.input_digest(graph) != first_input_digest
