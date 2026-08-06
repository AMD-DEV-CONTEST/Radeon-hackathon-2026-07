from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from colorgraph.agent.creative_contracts import (
    AdjustmentDirection,
    AgentState,
    BriefRetrieval,
    ColorLanguageCue,
    ColorPipelineFacts,
    ColorProperty,
    ColorStrategy,
    CompiledCandidate,
    ContextBudget,
    ContrastCharacter,
    CreativeBrief,
    CreativeDirection,
    CritiqueDimension,
    CritiqueScore,
    DiagnosticSeverity,
    EvidenceKind,
    EvidenceReference,
    GraphChange,
    MeasurementFact,
    MetricUnit,
    PaletteCharacter,
    ProjectContextPack,
    ProjectVisualThesis,
    ProtectedAttribute,
    ReadyResult,
    RenderedCandidate,
    RenderedFrameEvidence,
    RetrievalBundle,
    RetrievalRoute,
    SelectionDecision,
    SignedAgentAsset,
    StrategyAction,
    StrategyOperation,
    StrategyParameter,
    StrategyScope,
    TechnicalBaseline,
    TechnicalDiagnostic,
    TechnicalMetric,
    VisualCritique,
    VisualHierarchyItem,
    sign_agent_asset,
)
from colorgraph.agent.creative_runtime import AgentContractError, AgentRunLedger
from colorgraph.agent.creative_store import CreativeAssetStore

PROJECT_ID = "project:creative-contract"
GRAPH_DIGEST = hashlib.sha256(b"graph").hexdigest()
NOW = datetime(2026, 7, 29, 8, tzinfo=UTC)


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _baseline_payload() -> TechnicalBaseline:
    return TechnicalBaseline(
        graph_digest=GRAPH_DIGEST,
        color_pipeline=ColorPipelineFacts(
            input_color_space="bt709_oetf",
            working_color_space="acescg",
            output_color_space="rec1886",
            renderer_version="colorgraph.renderer/v3",
            input_transform_digest=_sha("input-transform"),
            output_transform_digest=_sha("output-transform"),
            information_already_clipped=False,
        ),
        measurements=[
            MeasurementFact(
                metric=TechnicalMetric.EXPOSURE_EV,
                value=0.1,
                unit=MetricUnit.EV,
                uncertainty=0.05,
                valid_sample_ratio=0.9,
                evidence_ids=["frame:001"],
            )
        ],
        diagnostics=[
            TechnicalDiagnostic(
                diagnostic_id="diagnostic:exposure",
                severity=DiagnosticSeverity.INFO,
                metric=TechnicalMetric.EXPOSURE_EV,
                observed=0.1,
                threshold=None,
                detail="Exposure is inside the conservative baseline range.",
                evidence_ids=["frame:001"],
            )
        ],
        immutable_fact_ids=["fact:input-space", "fact:output-space"],
    )


def _baseline_asset(project_id: str = PROJECT_ID) -> SignedAgentAsset:
    return sign_agent_asset(
        project_id=project_id,
        input_digest=GRAPH_DIGEST,
        payload=_baseline_payload(),
        prompt_version="deterministic-baseline/v1",
        model_id="deterministic",
        model_revision="v1",
        tool_versions={"colorgraph": "v1"},
        created_at=NOW,
    )


def _context(baseline: SignedAgentAsset) -> ProjectContextPack:
    return ProjectContextPack(
        technical_baseline_asset_id=baseline.asset_id,
        technical_baseline_sha256=baseline.sha256,
        graph_digest=GRAPH_DIGEST,
        evidence_bundle_schema_version="colorgraph.agent-evidence-bundle/v1",
        evidence_bundle_digest=_sha("evidence-bundle"),
        allowed_scene_ids=["scene:001"],
        allowed_shot_ids=["shot:001", "shot:002"],
        evidence=[
            EvidenceReference(
                evidence_id="frame:001",
                kind=EvidenceKind.FRAME,
                digest=_sha("frame-1"),
                summary="Representative frame showing the primary lake and sky.",
                frame_index=12,
            )
        ],
        budget=ContextBudget(
            maximum_images=12,
            maximum_image_edge=1024,
            maximum_audio_seconds=30.0,
            maximum_tokens=8_000,
            maximum_context_bytes=8_000_000,
        ),
        omitted_evidence_ids=[],
    )


def _brief(direction: CreativeDirection) -> CreativeBrief:
    return CreativeBrief(
        brief_id=f"brief:{direction.value}",
        scene_id="scene:001",
        direction=direction,
        interpretation=f"{direction.value} interpretation grounded in the lake frame.",
        evidence_for=["frame:001"],
        evidence_against=["frame:001"],
        emotional_target="Quiet attention without turning the scene into a preset.",
        visual_hierarchy=[
            VisualHierarchyItem(
                target="lake",
                priority=1,
                rationale="The reflection is the strongest spatial anchor.",
                evidence_ids=["frame:001"],
            )
        ],
        possible_color_language=[
            ColorLanguageCue(
                target="global",
                property=ColorProperty.CONTRAST,
                direction=AdjustmentDirection.PRESERVE,
                minimum_strength=0.0,
                maximum_strength=0.25,
                rationale="Retain the source atmosphere while preserving detail.",
            )
        ],
        cliche_risks=["Avoid a generic teal landscape treatment."],
        confidence=0.7,
        uncertainties=["Author intent is not explicitly supplied."],
        failure_conditions=["The lake reflection loses separation from the sky."],
    )


def _thesis() -> ProjectVisualThesis:
    return ProjectVisualThesis(
        thesis_id="thesis:001",
        project_interpretation="A restrained study of stillness and changing light.",
        palette_character=PaletteCharacter.SOURCE_FAITHFUL,
        contrast_character=ContrastCharacter.NATURAL,
        shared_protections=[
            ProtectedAttribute.COLOR_PIPELINE,
            ProtectedAttribute.HIGHLIGHT_DETAIL,
        ],
        evidence_for=["frame:001"],
        evidence_against=["frame:001"],
        confidence=0.72,
        uncertainties=["No explicit user-authored visual thesis is available."],
        briefs=[_brief(direction) for direction in CreativeDirection],
    )


def _retrieval(thesis_asset: SignedAgentAsset) -> RetrievalBundle:
    return RetrievalBundle(
        thesis_asset_id=thesis_asset.asset_id,
        thesis_sha256=thesis_asset.sha256,
        retrievals=[
            BriefRetrieval(
                brief_id=f"brief:{direction.value}",
                query=f"{direction.value} evidence-aware landscape alternatives",
                route=route,
                results=[],
                low_relevance_rejected=True,
            )
            for direction in CreativeDirection
            for route in RetrievalRoute
        ],
        index_version="possibilities/v1",
        empty_bundle_reason="The deterministic contract fixture has no knowledge index.",
    )


def _strategy(
    baseline: SignedAgentAsset,
    *,
    project_id: str = PROJECT_ID,
    scene_id: str = "scene:001",
) -> ColorStrategy:
    return ColorStrategy(
        strategy_id="strategy:faithful",
        brief_id="brief:faithful",
        technical_baseline_asset_id=baseline.asset_id,
        technical_baseline_sha256=baseline.sha256,
        common_language="Preserve neutral highlights and use restrained separation.",
        actions=[
            StrategyAction(
                action_id="action:contrast",
                operation=StrategyOperation.LOOK,
                scope=StrategyScope(
                    project_id=project_id,
                    scene_id=scene_id,
                ),
                parameters=[
                    StrategyParameter(
                        name="contrast",
                        unit="normalized",
                        minimum=0.0,
                        nominal=0.1,
                        maximum=0.2,
                    )
                ],
                serves_brief_id="brief:faithful",
                evidence_ids=["frame:001"],
                protected_attributes=[ProtectedAttribute.HIGHLIGHT_DETAIL],
                rationale="A small contrast range supports the visual hierarchy.",
            )
        ],
        alternatives_not_selected=[
            "A warm split was not selected because the evidence is ambiguous."
        ],
        continuity_constraints=[ProtectedAttribute.PROJECT_CONTINUITY],
        failure_conditions=["Highlights clip or the lake loses structure."],
    )


def _ledger() -> AgentRunLedger:
    return AgentRunLedger(
        run_id="run:001",
        project_id=PROJECT_ID,
        graph_digest=GRAPH_DIGEST,
        technical_baseline=_baseline_asset(),
    )


def _issue(
    ledger: AgentRunLedger,
    stage: AgentState,
    payload: object,
    key: str,
    *,
    created_at: datetime = NOW,
) -> SignedAgentAsset:
    return ledger.issue_and_submit(
        stage,
        payload,
        idempotency_key=key,
        current_graph_digest=GRAPH_DIGEST,
        prompt_version="fixture-prompt/v1",
        model_id="fixture-model",
        model_revision="revision:1",
        tool_versions={"colorgraph": "v1"},
        created_at=created_at,
    )


def _through_retrieved() -> tuple[AgentRunLedger, SignedAgentAsset]:
    ledger = _ledger()
    _issue(
        ledger,
        AgentState.EVIDENCE_READY,
        _context(ledger.technical_baseline),
        "evidence",
    )
    thesis_asset = _issue(
        ledger,
        AgentState.INTERPRETED,
        _thesis(),
        "interpret",
    )
    retrieval_asset = _issue(
        ledger,
        AgentState.RETRIEVED,
        _retrieval(thesis_asset),
        "retrieve",
    )
    return ledger, retrieval_asset


def test_signed_contracts_round_trip_through_the_complete_state_machine() -> None:
    ledger, _ = _through_retrieved()
    strategy_asset = _issue(
        ledger,
        AgentState.STRATEGIZED,
        _strategy(ledger.technical_baseline),
        "strategy",
    )
    compiled_asset = _issue(
        ledger,
        AgentState.COMPILED,
        CompiledCandidate(
            candidate_id="candidate:faithful",
            strategy_id="strategy:faithful",
            source_graph_digest=GRAPH_DIGEST,
            compiled_graph_digest=_sha("compiled-graph"),
            undo_graph_digest=GRAPH_DIGEST,
            graph_changes=[
                GraphChange(
                    action_id="action:contrast",
                    node_id="look:scene:001",
                    operation="update",
                    parameter="contrast",
                    before_value=0.0,
                    after_value=0.1,
                )
            ],
            operation_card_versions={"look": "v1"},
            compiler_version="compiler/v1",
            validation_passed=True,
        ),
        "compile",
    )
    rendered_asset = _issue(
        ledger,
        AgentState.RENDERED,
        RenderedCandidate(
            candidate_id="candidate:faithful",
            compiled_asset_id=compiled_asset.asset_id,
            compiled_sha256=compiled_asset.sha256,
            renderer_version="colorgraph.renderer/v3",
            frames=[
                RenderedFrameEvidence(
                    frame_index=12,
                    time_seconds=0.48,
                    output_digest=_sha("rendered-frame"),
                    width=640,
                    height=360,
                    hard_checks_passed=True,
                    failed_check_ids=[],
                )
            ],
            render_manifest_digest=_sha("render-manifest"),
        ),
        "render",
    )
    critique_asset = _issue(
        ledger,
        AgentState.CRITICIZED,
        VisualCritique(
            candidate_id="candidate:faithful",
            rendered_asset_id=rendered_asset.asset_id,
            rendered_sha256=rendered_asset.sha256,
            blind_order_digest=_sha("blind-order"),
            position_swap_consistent=True,
            technical_integrity_asset_id=ledger.technical_baseline.asset_id,
            technical_integrity_sha256=ledger.technical_baseline.sha256,
            scores=[
                CritiqueScore(
                    dimension=dimension,
                    score=0.7,
                    confidence=0.8,
                    evidence_ids=["frame:001"],
                    counterevidence_ids=["frame:001"],
                    concise_reason=f"{dimension.value} is supported with uncertainty.",
                )
                for dimension in CritiqueDimension
            ],
        ),
        "critic",
    )
    assert strategy_asset.parent_asset_id is not None
    assert critique_asset.parent_asset_id == rendered_asset.asset_id
    _issue(
        ledger,
        AgentState.SELECTED,
        SelectionDecision(
            selected_candidate_id="candidate:faithful",
            runner_up_candidate_id="candidate:counterpoint",
            pareto_candidate_ids=[
                "candidate:faithful",
                "candidate:counterpoint",
            ],
            gate_trace=[
                "delivery",
                "intent",
                "temporal",
                "preference",
            ],
            selection_digest=_sha("selection"),
        ),
        "select",
    )
    ready_asset = _issue(
        ledger,
        AgentState.READY,
        ReadyResult(
            selected_candidate_id="candidate:faithful",
            selected_graph_digest=_sha("compiled-graph"),
            runner_up_candidate_id="candidate:counterpoint",
            ready_for_user_review=True,
            current_graph_unchanged=True,
        ),
        "ready",
    )

    assert ledger.current_state == AgentState.READY
    assert ledger.manifest().completed is True
    assert len(ledger.manifest().assets) == 9
    for _, asset in ledger.assets:
        assert SignedAgentAsset.model_validate_json(asset.model_dump_json()) == asset
    assert SignedAgentAsset.model_validate_json(
        ready_asset.model_dump_json()
    ) == ready_asset
    manifest = ledger.manifest()
    assert type(manifest).model_validate_json(manifest.model_dump_json()) == manifest


@pytest.mark.parametrize("mutation", ["missing", "extra"])
def test_creative_brief_rejects_missing_and_extra_fields(mutation: str) -> None:
    payload = _brief(CreativeDirection.FAITHFUL).model_dump(mode="python")
    if mutation == "missing":
        payload.pop("interpretation")
    else:
        payload["hidden_reasoning"] = "must not be accepted"

    with pytest.raises(ValidationError):
        CreativeBrief.model_validate(payload)


def test_signed_asset_rejects_tampering() -> None:
    asset = _baseline_asset()
    payload = asset.model_dump(mode="json")
    payload["model_revision"] = "revision:tampered"

    with pytest.raises(ValidationError, match="signature mismatch"):
        SignedAgentAsset.model_validate_json(json.dumps(payload))


def test_ledger_rejects_stale_cross_project_skip_and_duplicate_submissions() -> None:
    ledger = _ledger()
    context = _context(ledger.technical_baseline)
    context_asset = sign_agent_asset(
        project_id=PROJECT_ID,
        input_digest=GRAPH_DIGEST,
        payload=context,
        prompt_version="fixture/v1",
        model_id="fixture",
        model_revision="v1",
        tool_versions={"colorgraph": "v1"},
        parent=ledger.technical_baseline,
        created_at=NOW,
    )
    with pytest.raises(AgentContractError, match="differs"):
        ledger.submit(
            AgentState.EVIDENCE_READY,
            context_asset,
            idempotency_key="stale",
            current_graph_digest=_sha("new-graph"),
        )

    cross_project_asset = sign_agent_asset(
        project_id="project:other",
        input_digest=GRAPH_DIGEST,
        payload=context,
        prompt_version="fixture/v1",
        model_id="fixture",
        model_revision="v1",
        tool_versions={"colorgraph": "v1"},
        parent=ledger.technical_baseline,
        created_at=NOW,
    )
    with pytest.raises(AgentContractError) as cross_project:
        ledger.submit(
            AgentState.EVIDENCE_READY,
            cross_project_asset,
            idempotency_key="cross-project",
            current_graph_digest=GRAPH_DIGEST,
        )
    assert cross_project.value.code == "cross_project_asset"

    accepted = ledger.submit(
        AgentState.EVIDENCE_READY,
        context_asset,
        idempotency_key="evidence",
        current_graph_digest=GRAPH_DIGEST,
    )
    assert (
        ledger.submit(
            AgentState.EVIDENCE_READY,
            context_asset,
            idempotency_key="evidence",
            current_graph_digest=GRAPH_DIGEST,
        )
        is accepted
    )
    with pytest.raises(AgentContractError) as duplicate:
        ledger.submit(
            AgentState.EVIDENCE_READY,
            context_asset,
            idempotency_key="duplicate",
            current_graph_digest=GRAPH_DIGEST,
        )
    assert duplicate.value.code == "invalid_transition"

    retrieval = RetrievalBundle(
        thesis_asset_id="asset:missing",
        thesis_sha256=_sha("missing"),
        retrievals=[
            BriefRetrieval(
                brief_id="brief:faithful",
                query="query",
                route=route,
                results=[],
                low_relevance_rejected=True,
            )
            for route in RetrievalRoute
        ],
        index_version="v1",
        empty_bundle_reason="fixture",
    )
    with pytest.raises(AgentContractError) as skipped:
        _issue(
            ledger,
            AgentState.RETRIEVED,
            retrieval,
            "skip-interpretation",
        )
    assert skipped.value.code == "invalid_transition"


def test_ledger_rejects_out_of_scope_strategy_action() -> None:
    ledger, _ = _through_retrieved()

    with pytest.raises(AgentContractError) as rejected:
        _issue(
            ledger,
            AgentState.STRATEGIZED,
            _strategy(
                ledger.technical_baseline,
                scene_id="scene:outside",
            ),
            "strategy-outside",
            created_at=NOW + timedelta(seconds=1),
        )

    assert rejected.value.code == "action_scene_out_of_scope"
    assert ledger.current_state == AgentState.RETRIEVED


def test_asset_store_persists_and_verifies_append_only_run(
    tmp_path,
) -> None:
    ledger = _ledger()
    _issue(
        ledger,
        AgentState.EVIDENCE_READY,
        _context(ledger.technical_baseline),
        "evidence",
    )
    _issue(
        ledger,
        AgentState.INTERPRETED,
        _thesis(),
        "interpret",
    )
    store = CreativeAssetStore(tmp_path / "agent-runs")

    manifest_path = store.persist_ledger(ledger)

    assert manifest_path.is_file()
    assert store.load_baseline(PROJECT_ID, "run:001") == ledger.technical_baseline
    assert store.load_assets(PROJECT_ID, "run:001") == [
        asset for _, asset in ledger.assets
    ]
    assert store.verify_run(PROJECT_ID, "run:001") == ledger.manifest()

    first_asset_path = sorted(
        (manifest_path.parent / "assets").glob("*.json")
    )[0]
    tampered = json.loads(first_asset_path.read_text(encoding="utf-8"))
    tampered["model_revision"] = "tampered"
    first_asset_path.write_text(
        json.dumps(tampered),
        encoding="utf-8",
    )
    with pytest.raises(ValidationError, match="signature mismatch"):
        store.verify_run(PROJECT_ID, "run:001")
