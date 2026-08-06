from __future__ import annotations

from datetime import datetime
from typing import ClassVar

from colorgraph.agent.creative_contracts import (
    AgentRunManifest,
    AgentState,
    ColorStrategy,
    CompiledCandidate,
    CreativeBrief,
    FailureCase,
    ManifestAssetEntry,
    ProjectContextPack,
    ProjectVisualThesis,
    ReadyResult,
    ReflectionPatch,
    RenderedCandidate,
    RetrievalBundle,
    SelectionDecision,
    SignedAgentAsset,
    TechnicalBaseline,
    VisualCritique,
    sign_agent_asset,
)


class AgentContractError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


class AgentRunLedger:
    """Append-only state machine for signed creative-agent assets."""

    _TRANSITIONS: ClassVar[dict[AgentState | None, frozenset[AgentState]]] = {
        None: frozenset({AgentState.EVIDENCE_READY}),
        AgentState.EVIDENCE_READY: frozenset({AgentState.INTERPRETED}),
        AgentState.INTERPRETED: frozenset({AgentState.RETRIEVED}),
        AgentState.RETRIEVED: frozenset({AgentState.STRATEGIZED}),
        AgentState.STRATEGIZED: frozenset({AgentState.COMPILED}),
        AgentState.COMPILED: frozenset({AgentState.RENDERED}),
        AgentState.RENDERED: frozenset({AgentState.CRITICIZED}),
        AgentState.CRITICIZED: frozenset({AgentState.SELECTED}),
        AgentState.SELECTED: frozenset({AgentState.REFINED, AgentState.READY}),
        AgentState.REFINED: frozenset({AgentState.READY}),
        AgentState.READY: frozenset(),
    }
    _PAYLOAD_TYPES: ClassVar[dict[AgentState, type]] = {
        AgentState.EVIDENCE_READY: ProjectContextPack,
        AgentState.INTERPRETED: ProjectVisualThesis,
        AgentState.RETRIEVED: RetrievalBundle,
        AgentState.STRATEGIZED: ColorStrategy,
        AgentState.COMPILED: CompiledCandidate,
        AgentState.RENDERED: RenderedCandidate,
        AgentState.CRITICIZED: VisualCritique,
        AgentState.SELECTED: SelectionDecision,
        AgentState.REFINED: ReflectionPatch,
        AgentState.READY: ReadyResult,
    }

    def __init__(
        self,
        *,
        run_id: str,
        project_id: str,
        graph_digest: str,
        technical_baseline: SignedAgentAsset,
    ) -> None:
        if technical_baseline.project_id != project_id:
            raise AgentContractError(
                "cross_project_baseline",
                "technical baseline belongs to a different project",
            )
        if not isinstance(
            technical_baseline.payload,
            TechnicalBaseline,
        ):
            raise AgentContractError(
                "invalid_baseline_type",
                "run baseline must contain TechnicalBaseline",
            )
        if (
            technical_baseline.input_digest != graph_digest
            or technical_baseline.payload.graph_digest != graph_digest
        ):
            raise AgentContractError(
                "stale_baseline",
                "technical baseline was not measured from the run graph",
            )
        self.run_id = run_id
        self.project_id = project_id
        self.graph_digest = graph_digest
        self.technical_baseline = technical_baseline
        self._assets: list[tuple[AgentState, SignedAgentAsset]] = []
        self._idempotency: dict[str, SignedAgentAsset] = {}
        self._failure_cases: list[SignedAgentAsset] = []
        self.created_at = technical_baseline.created_at

    @property
    def current_state(self) -> AgentState | None:
        return self._assets[-1][0] if self._assets else None

    @property
    def assets(self) -> tuple[tuple[AgentState, SignedAgentAsset], ...]:
        return tuple(self._assets)

    @property
    def failure_cases(self) -> tuple[SignedAgentAsset, ...]:
        return tuple(self._failure_cases)

    @property
    def last_asset(self) -> SignedAgentAsset:
        return self._assets[-1][1] if self._assets else self.technical_baseline

    @property
    def context(self) -> ProjectContextPack | None:
        if not self._assets:
            return None
        payload = self._assets[0][1].payload
        return payload if isinstance(payload, ProjectContextPack) else None

    def _expected_input_digest(self) -> str:
        return self.last_asset.sha256 if self._assets else self.graph_digest

    def _validate_record(
        self,
        stage: AgentState,
        asset: SignedAgentAsset,
        *,
        current_graph_digest: str,
    ) -> None:
        if current_graph_digest != self.graph_digest:
            raise AgentContractError(
                "stale_graph",
                "the current Grade Graph differs from the run baseline",
            )
        if asset.project_id != self.project_id:
            raise AgentContractError(
                "cross_project_asset",
                "agent asset belongs to a different project",
            )
        expected_type = self._PAYLOAD_TYPES[stage]
        if not isinstance(asset.payload, expected_type):
            raise AgentContractError(
                "wrong_payload_type",
                f"{stage.value} requires {expected_type.__name__}",
            )
        expected_parent = self.last_asset
        if (
            asset.parent_asset_id != expected_parent.asset_id
            or asset.parent_sha256 != expected_parent.sha256
        ):
            raise AgentContractError(
                "wrong_parent",
                "agent asset does not reference the exact signed upstream asset",
            )
        expected_input = self._expected_input_digest()
        if asset.input_digest != expected_input:
            raise AgentContractError(
                "stale_input_digest",
                "agent asset input digest does not match the signed upstream state",
            )
        context = self.context
        if context is not None:
            if asset.scene_id is not None and asset.scene_id not in context.allowed_scene_ids:
                raise AgentContractError(
                    "unauthorized_scene",
                    f"scene {asset.scene_id!r} is outside the context pack",
                )
            if asset.shot_id is not None and asset.shot_id not in context.allowed_shot_ids:
                raise AgentContractError(
                    "unauthorized_shot",
                    f"shot {asset.shot_id!r} is outside the context pack",
                )

    def _known_evidence_ids(self) -> set[str]:
        context = self.context
        return {item.evidence_id for item in context.evidence} if context is not None else set()

    def _validate_brief(
        self,
        brief: CreativeBrief,
        *,
        context: ProjectContextPack,
        evidence_ids: set[str],
    ) -> None:
        if brief.scene_id not in context.allowed_scene_ids:
            raise AgentContractError(
                "brief_scene_out_of_scope",
                f"brief scene {brief.scene_id!r} is outside the context pack",
            )
        referenced = {
            *brief.evidence_for,
            *brief.evidence_against,
            *(
                evidence_id
                for hierarchy in brief.visual_hierarchy
                for evidence_id in hierarchy.evidence_ids
            ),
        }
        unknown = referenced - evidence_ids
        if unknown:
            raise AgentContractError(
                "unknown_brief_evidence",
                f"brief references unknown evidence IDs: {sorted(unknown)}",
            )

    def _validate_payload(
        self,
        stage: AgentState,
        asset: SignedAgentAsset,
    ) -> None:
        payload = asset.payload
        context = self.context
        if stage == AgentState.EVIDENCE_READY:
            assert isinstance(payload, ProjectContextPack)
            if (
                payload.technical_baseline_asset_id != self.technical_baseline.asset_id
                or payload.technical_baseline_sha256 != self.technical_baseline.sha256
            ):
                raise AgentContractError(
                    "baseline_reference_mismatch",
                    "context pack does not reference the run baseline",
                )
            if payload.graph_digest != self.graph_digest:
                raise AgentContractError(
                    "stale_context",
                    "context pack graph digest differs from the run graph",
                )
            return
        if context is None:  # pragma: no cover - transition invariant
            raise AgentContractError(
                "missing_context",
                "run has no evidence-ready context pack",
            )
        evidence_ids = self._known_evidence_ids()
        if stage == AgentState.INTERPRETED:
            assert isinstance(payload, ProjectVisualThesis)
            referenced = {
                *payload.evidence_for,
                *payload.evidence_against,
            }
            unknown = referenced - evidence_ids
            if unknown:
                raise AgentContractError(
                    "unknown_thesis_evidence",
                    f"thesis references unknown evidence IDs: {sorted(unknown)}",
                )
            for brief in payload.briefs:
                self._validate_brief(
                    brief,
                    context=context,
                    evidence_ids=evidence_ids,
                )
        elif stage == AgentState.RETRIEVED:
            assert isinstance(payload, RetrievalBundle)
            thesis_asset = self._assets[-1][1]
            if (
                payload.thesis_asset_id != thesis_asset.asset_id
                or payload.thesis_sha256 != thesis_asset.sha256
            ):
                raise AgentContractError(
                    "thesis_reference_mismatch",
                    "retrieval bundle does not reference the interpreted thesis",
                )
            thesis = thesis_asset.payload
            assert isinstance(thesis, ProjectVisualThesis)
            known_briefs = {brief.brief_id for brief in thesis.briefs}
            unknown_briefs = {retrieval.brief_id for retrieval in payload.retrievals} - known_briefs
            if unknown_briefs:
                raise AgentContractError(
                    "unknown_retrieval_brief",
                    f"retrieval bundle references unknown briefs: {sorted(unknown_briefs)}",
                )
        elif stage == AgentState.STRATEGIZED:
            assert isinstance(payload, ColorStrategy)
            if (
                payload.technical_baseline_asset_id != self.technical_baseline.asset_id
                or payload.technical_baseline_sha256 != self.technical_baseline.sha256
            ):
                raise AgentContractError(
                    "strategy_baseline_mismatch",
                    "strategy does not reference the immutable baseline",
                )
            thesis_asset = self._assets[1][1]
            thesis = thesis_asset.payload
            assert isinstance(thesis, ProjectVisualThesis)
            known_briefs = {brief.brief_id for brief in thesis.briefs}
            if payload.brief_id not in known_briefs:
                raise AgentContractError(
                    "unknown_strategy_brief",
                    "strategy references an unknown creative brief",
                )
            for action in payload.actions:
                scope = action.scope
                if scope.project_id != self.project_id:
                    raise AgentContractError(
                        "cross_project_action",
                        "strategy action targets a different project",
                    )
                if scope.scene_id is not None and scope.scene_id not in context.allowed_scene_ids:
                    raise AgentContractError(
                        "action_scene_out_of_scope",
                        f"action targets unauthorized scene {scope.scene_id!r}",
                    )
                if scope.shot_id is not None and scope.shot_id not in context.allowed_shot_ids:
                    raise AgentContractError(
                        "action_shot_out_of_scope",
                        f"action targets unauthorized shot {scope.shot_id!r}",
                    )
                if action.serves_brief_id != payload.brief_id:
                    raise AgentContractError(
                        "action_brief_mismatch",
                        "strategy action does not serve its strategy brief",
                    )
                unknown = set(action.evidence_ids) - evidence_ids
                if unknown:
                    raise AgentContractError(
                        "unknown_action_evidence",
                        f"strategy action references unknown evidence IDs: {sorted(unknown)}",
                    )
        elif stage == AgentState.COMPILED:
            assert isinstance(payload, CompiledCandidate)
            if payload.source_graph_digest != self.graph_digest:
                raise AgentContractError(
                    "compiled_from_stale_graph",
                    "candidate compiler did not use the run baseline graph",
                )
        elif stage == AgentState.RENDERED:
            assert isinstance(payload, RenderedCandidate)
            compiled = self._assets[-1][1]
            if (
                payload.compiled_asset_id != compiled.asset_id
                or payload.compiled_sha256 != compiled.sha256
            ):
                raise AgentContractError(
                    "compiled_reference_mismatch",
                    "render does not reference the signed compiled candidate",
                )
        elif stage == AgentState.CRITICIZED:
            assert isinstance(payload, VisualCritique)
            rendered = self._assets[-1][1]
            if (
                payload.rendered_asset_id != rendered.asset_id
                or payload.rendered_sha256 != rendered.sha256
            ):
                raise AgentContractError(
                    "render_reference_mismatch",
                    "critique does not reference the signed render",
                )
            if (
                payload.technical_integrity_asset_id != self.technical_baseline.asset_id
                or payload.technical_integrity_sha256 != self.technical_baseline.sha256
            ):
                raise AgentContractError(
                    "critic_overrides_technical_integrity",
                    "critic must reference, not replace, deterministic integrity",
                )
        elif stage == AgentState.READY:
            assert isinstance(payload, ReadyResult)
            if not payload.current_graph_unchanged:
                raise AgentContractError(
                    "shadow_graph_mutated",
                    "ready result must not mutate the current graph before approval",
                )

    def submit(
        self,
        stage: AgentState,
        asset: SignedAgentAsset,
        *,
        idempotency_key: str,
        current_graph_digest: str,
    ) -> SignedAgentAsset:
        prior = self._idempotency.get(idempotency_key)
        if prior is not None:
            if prior.asset_id == asset.asset_id:
                return prior
            raise AgentContractError(
                "idempotency_conflict",
                "idempotency key was already used for different content",
            )
        allowed = self._TRANSITIONS[self.current_state]
        if stage not in allowed:
            expected = ", ".join(sorted(item.value for item in allowed)) or "none"
            raise AgentContractError(
                "invalid_transition",
                f"cannot submit {stage.value} after "
                f"{self.current_state.value if self.current_state else 'baseline'}; "
                f"expected {expected}",
            )
        self._validate_record(
            stage,
            asset,
            current_graph_digest=current_graph_digest,
        )
        self._validate_payload(stage, asset)
        self._assets.append((stage, asset))
        self._idempotency[idempotency_key] = asset
        return asset

    def issue_and_submit(
        self,
        stage: AgentState,
        payload: object,
        *,
        idempotency_key: str,
        current_graph_digest: str,
        prompt_version: str,
        model_id: str,
        model_revision: str,
        tool_versions: dict[str, str],
        scene_id: str | None = None,
        shot_id: str | None = None,
        created_at: datetime | None = None,
    ) -> SignedAgentAsset:
        expected_type = self._PAYLOAD_TYPES[stage]
        if not isinstance(payload, expected_type):
            raise AgentContractError(
                "wrong_payload_type",
                f"{stage.value} requires {expected_type.__name__}",
            )
        asset = sign_agent_asset(
            project_id=self.project_id,
            scene_id=scene_id,
            shot_id=shot_id,
            input_digest=self._expected_input_digest(),
            payload=payload,  # type: ignore[arg-type]
            prompt_version=prompt_version,
            model_id=model_id,
            model_revision=model_revision,
            tool_versions=tool_versions,
            parent=self.last_asset,
            created_at=created_at,
        )
        return self.submit(
            stage,
            asset,
            idempotency_key=idempotency_key,
            current_graph_digest=current_graph_digest,
        )

    def record_failure_case(
        self,
        payload: FailureCase,
        *,
        idempotency_key: str,
        prompt_version: str,
        model_id: str,
        model_revision: str,
        tool_versions: dict[str, str],
    ) -> SignedAgentAsset:
        prior = self._idempotency.get(idempotency_key)
        asset = sign_agent_asset(
            project_id=self.project_id,
            input_digest=self.last_asset.sha256,
            payload=payload,
            prompt_version=prompt_version,
            model_id=model_id,
            model_revision=model_revision,
            tool_versions=tool_versions,
            parent=self.last_asset,
        )
        if prior is not None:
            if prior.asset_id == asset.asset_id:
                return prior
            raise AgentContractError(
                "idempotency_conflict",
                "idempotency key was already used for different content",
            )
        self._failure_cases.append(asset)
        self._idempotency[idempotency_key] = asset
        return asset

    def manifest(self) -> AgentRunManifest:
        updated_at = (
            self._assets[-1][1].created_at if self._assets else self.technical_baseline.created_at
        )
        return AgentRunManifest(
            run_id=self.run_id,
            project_id=self.project_id,
            graph_digest=self.graph_digest,
            current_state=self.current_state,
            assets=[
                ManifestAssetEntry(
                    state=state,
                    asset_id=asset.asset_id,
                    asset_sha256=asset.sha256,
                    payload_schema_version=asset.payload.schema_version,
                    parent_asset_id=asset.parent_asset_id,
                )
                for state, asset in self._assets
            ],
            completed=self.current_state == AgentState.READY,
            created_at=self.created_at,
            updated_at=updated_at,
        )
