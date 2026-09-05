"""Startup-compiled production M5 orchestration over deterministic policy services."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from langgraph.graph import END, START, StateGraph

from app.experience_asset.application.m5.context_loader import M5ContextLoader
from app.experience_asset.application.m5.contracts import ApprovalRequestV1, PrivacyActionV1
from app.experience_asset.application.m5.service import M5IsolatedService
from app.experience_asset.application.m5.workflow_contract import (
    M5_GRAPH_NODES,
    M5_TOPOLOGY_HASH,
    M5_WORKFLOW_VERSION,
    M5GraphState,
    M5GraphStateV1,
    validate_m5_graph_state,
)
from app.experience_asset.delivery.models import StoredRouteDraftV1
from app.experience_asset.domain.enums import PrivacyResolution, TerminalState
from app.experience_asset.domain.models import TerminalResultV1
from app.experience_asset.persistence.m5_store import M5Store
from app.experience_asset.policy.m5 import (
    PRIVACY_POLICY_VERSION,
    route_draft_binding_hash,
    route_matrix_hash,
)
from app.experience_asset.policy.privacy_text_detector import PRIVACY_TEXT_DETECTOR_VERSION


class M5ProductionGraph:
    """Coordinate M5 while checkpoints retain only IDs, hashes, and outcomes."""

    def __init__(
        self,
        *,
        context_loader: M5ContextLoader,
        store: M5Store,
        service: M5IsolatedService | None = None,
        draft_loader: Callable[[UUID], StoredRouteDraftV1] | None = None,
        code_commit: str = "UNCOMMITTED",
    ) -> None:
        self.context_loader = context_loader
        self.store = store
        self.service = service or M5IsolatedService()
        self.draft_loader = draft_loader
        self.code_commit = code_commit
        self._compiled: Any | None = None
        self.compile_count = 0
        self.last_state: M5GraphStateV1 | None = None

    def compile(self, checkpointer: Any) -> None:
        graph = StateGraph(M5GraphState)
        operations = {
            "load_m5_context": self._load,
            "evaluate_m5_routes": self._evaluate,
            "review_m5_privacy": self._review,
            "wait_m5_privacy_resolution": self._wait_privacy,
            "apply_m5_privacy_resolution": self._apply_resolution,
            "recompose_m5_context": self._recompose,
            "wait_m5_approval": self._wait_approval,
            "validate_m5_approval": self._validate_approval,
            "verify_m5_state": self._verify,
            "terminalize_m5_run": self._terminalize,
        }
        for name in M5_GRAPH_NODES:
            graph.add_node(name, self._validated_node(name, operations[name]))
        graph.add_edge(START, "load_m5_context")
        graph.add_conditional_edges(
            "load_m5_context",
            self._edge,
            {"ready": "evaluate_m5_routes", "not_ready_or_stale": "terminalize_m5_run"},
        )
        graph.add_conditional_edges(
            "evaluate_m5_routes",
            self._edge,
            {"evaluated": "review_m5_privacy", "safe_failure": "terminalize_m5_run"},
        )
        graph.add_conditional_edges(
            "review_m5_privacy",
            self._edge,
            {
                "open_findings": "wait_m5_privacy_resolution",
                "resolved_or_empty": "wait_m5_approval",
                "safe_failure": "terminalize_m5_run",
            },
        )
        graph.add_conditional_edges(
            "wait_m5_privacy_resolution",
            self._edge,
            {"user_action": "apply_m5_privacy_resolution", "pause": "terminalize_m5_run"},
        )
        graph.add_conditional_edges(
            "apply_m5_privacy_resolution",
            self._edge,
            {
                "recorded": "evaluate_m5_routes",
                "canonical_change": "recompose_m5_context",
                "denied": "terminalize_m5_run",
            },
        )
        graph.add_conditional_edges(
            "recompose_m5_context",
            self._edge,
            {"current": "evaluate_m5_routes", "stale_or_exhausted": "terminalize_m5_run"},
        )
        graph.add_conditional_edges(
            "wait_m5_approval",
            self._edge,
            {
                "no_final_draft": "verify_m5_state",
                "explicit_action": "validate_m5_approval",
                "pause": "terminalize_m5_run",
            },
        )
        graph.add_conditional_edges(
            "validate_m5_approval",
            self._edge,
            {"valid": "verify_m5_state", "denied_or_stale": "terminalize_m5_run"},
        )
        graph.add_conditional_edges(
            "verify_m5_state",
            self._edge,
            {"verified": "terminalize_m5_run", "safe_failure": "terminalize_m5_run"},
        )
        graph.add_edge("terminalize_m5_run", END)
        self._compiled = graph.compile(checkpointer=checkpointer)
        self.compile_count += 1

    async def run_evaluate(self, asset_id: UUID) -> M5GraphStateV1:
        return await self._run(asset_id, command_kind="EVALUATE")

    async def run_resolve(
        self, asset_id: UUID, *, finding_id: UUID, action: PrivacyActionV1
    ) -> M5GraphStateV1:
        return await self._run(
            asset_id,
            command_kind="RESOLVE",
            finding_id=finding_id,
            privacy_action=action.value,
        )

    async def run_approve(
        self,
        asset_id: UUID,
        *,
        route_draft_id: UUID,
        user_action: str,
        idempotency_key: str,
    ) -> M5GraphStateV1:
        return await self._run(
            asset_id,
            command_kind="APPROVE",
            route_draft_id=route_draft_id,
            user_action=user_action,
            idempotency_key=idempotency_key,
        )

    async def _run(
        self,
        asset_id: UUID,
        *,
        command_kind: str,
        finding_id: UUID | None = None,
        privacy_action: str | None = None,
        route_draft_id: UUID | None = None,
        user_action: str | None = None,
        idempotency_key: str | None = None,
    ) -> M5GraphStateV1:
        if self._compiled is None:
            raise RuntimeError("M5 graph must be compiled during application startup")
        loaded = self.context_loader.load(asset_id)
        run_id, command_id = uuid4(), uuid4()
        self.context_loader.repository.start_workflow_run(
            run_id=run_id,
            asset_id=asset_id,
            base_version_id=loaded.context.version_id,
            command_id=command_id,
            command=f"E6-M5-{command_kind.lower()}-langgraph",
            user_goal="Evaluate routes and privacy before an explicit draft approval.",
            allow_current_source_search=False,
            workflow_version=M5_WORKFLOW_VERSION,
            topology_hash=M5_TOPOLOGY_HASH,
            model_id="deterministic-m5-policy",
            model_config_hash=hashlib.sha256(M5_WORKFLOW_VERSION.encode()).hexdigest(),
            server_base_url="local://deterministic-m5-policy",
            code_commit=self.code_commit,
            started_at=datetime.now(UTC),
        )
        self.store.save_workflow_command(
            run_id=run_id,
            command_kind=command_kind,
            finding_id=finding_id,
            privacy_action=privacy_action,
            route_draft_id=route_draft_id,
            user_action=user_action,
            idempotency_key=idempotency_key,
        )
        initial = M5GraphStateV1(
            run_id=str(run_id),
            asset_id=str(asset_id),
            base_version_id=str(loaded.context.version_id),
            command_id=str(command_id),
            content_hash=loaded.content_hash,
            relation_projection_hash=loaded.context.relation.projection_hash,
            canonical_version_id=str(loaded.context.version_id),
        ).as_graph_state()
        try:
            result = await self._compiled.ainvoke(initial, self._config(run_id))
            await self._bind_trace_checkpoints(run_id)
        except BaseException as exc:
            self._finish_emergency(run_id, type(exc).__name__)
            if isinstance(exc, KeyboardInterrupt | SystemExit):
                raise
            raise
        self.last_state = validate_m5_graph_state(result)
        return self.last_state

    async def recover_incomplete_runs(self) -> None:
        for run_id in self.context_loader.repository.list_incomplete_workflow_run_ids(
            M5_WORKFLOW_VERSION
        ):
            try:
                snapshot = await self._compiled.aget_state(self._config(run_id))
                if not snapshot.values:
                    raise RuntimeError("missing M5 checkpoint")
                state = validate_m5_graph_state(snapshot.values)
                if not self._recovery_identity_matches(run_id, state):
                    raise RuntimeError("M5 recovery identity changed")
                if snapshot.next:
                    await self._compiled.ainvoke(None, self._config(run_id))
                elif self.context_loader.repository.get_terminal_result(run_id) is None:
                    raise RuntimeError("M5 graph ended without a terminal result")
                await self._bind_trace_checkpoints(run_id)
            except BaseException as exc:
                self._finish_emergency(run_id, type(exc).__name__)
                if isinstance(exc, KeyboardInterrupt | SystemExit):
                    raise

    def _recovery_identity_matches(self, run_id: UUID, state: M5GraphStateV1) -> bool:
        context = self.context_loader.repository.get_workflow_run_context(run_id)
        command = self.store.read_workflow_command(run_id)
        expected_command = f"E6-M5-{command['command_kind'].lower()}-langgraph"
        if (
            context["workflow_version"] != M5_WORKFLOW_VERSION
            or context["topology_hash"] != M5_TOPOLOGY_HASH
            or context["model_id"] != "deterministic-m5-policy"
            or context["model_config_hash"]
            != hashlib.sha256(M5_WORKFLOW_VERSION.encode()).hexdigest()
            or context["server_base_url"] != "local://deterministic-m5-policy"
            or context["code_commit"] != self.code_commit
            or str(context["asset_id"]) != state.asset_id
            or str(context["base_version_id"]) != state.base_version_id
            or str(context["command_id"]) != state.command_id
            or context["command"] != expected_command
            or state.canonical_version_id != state.base_version_id
        ):
            return False
        loaded = self.context_loader.load(UUID(state.asset_id))
        return (
            str(loaded.context.version_id) == state.base_version_id
            and loaded.content_hash == state.content_hash
            and loaded.context.relation.projection_hash == state.relation_projection_hash
        )

    @staticmethod
    def _edge(state: M5GraphState) -> str:
        return state["selected_edge"].split(":", 1)[-1]

    def _validated_node(self, node_name: str, operation):
        async def run(state: M5GraphState) -> M5GraphState:
            started = datetime.now(UTC)
            validated = validate_m5_graph_state(state)
            try:
                updated = validate_m5_graph_state((await operation(validated)).as_graph_state())
            except BaseException as exc:
                self._record_trace(
                    node_name,
                    validated,
                    selected_edge=None,
                    finding_codes=[type(exc).__name__],
                    terminal_state=TerminalState.INTERNAL_ERROR.value,
                    started=started,
                )
                raise
            self._record_trace(
                node_name,
                validated,
                selected_edge=updated.selected_edge,
                finding_codes=updated.finding_codes,
                terminal_state=updated.terminal_candidate or None,
                started=started,
                output_refs=[
                    value
                    for value in (
                        f"route-matrix:{updated.route_matrix_hash}"
                        if updated.route_matrix_hash
                        else None,
                        f"privacy-review:{updated.privacy_review_hash}"
                        if updated.privacy_review_hash
                        else None,
                        f"approval:{updated.approval_id}" if updated.approval_id else None,
                    )
                    if value is not None
                ],
            )
            return updated.as_graph_state()

        return run

    def _record_trace(
        self,
        node_name: str,
        state: M5GraphStateV1,
        *,
        selected_edge: str | None,
        finding_codes: list[str],
        terminal_state: str | None,
        started: datetime,
        output_refs: list[str] | None = None,
    ) -> None:
        self.context_loader.repository.record_workflow_trace(
            run_id=UUID(state.run_id),
            workflow_version=M5_WORKFLOW_VERSION,
            topology_hash=M5_TOPOLOGY_HASH,
            node_name=node_name,
            node_attempt=state.node_attempt,
            selected_edge=selected_edge,
            input_refs=[
                f"run:{state.run_id}",
                f"asset:{state.asset_id}",
                f"version:{state.base_version_id}",
            ],
            output_refs=output_refs or [],
            policy_outcome=None,
            tool_execution_status="NOT_EXECUTED",
            verification_outcome=(
                "VERIFIED"
                if node_name == "verify_m5_state" and selected_edge == "verify_m5_state:verified"
                else "REJECTED"
                if finding_codes
                else None
            ),
            terminal_state=terminal_state,
            finding_codes=finding_codes,
            started_at=started,
            finished_at=datetime.now(UTC),
        )

    async def _bind_trace_checkpoints(self, run_id: UUID) -> None:
        async for snapshot in self._compiled.aget_state_history(self._config(run_id)):
            values = snapshot.values
            if not values:
                continue
            node_name = str(values.get("last_node") or "")
            checkpoint_id = snapshot.config["configurable"].get("checkpoint_id")
            if node_name and checkpoint_id:
                self.context_loader.repository.bind_workflow_trace_checkpoint(
                    run_id=run_id,
                    node_name=node_name,
                    checkpoint_id=str(checkpoint_id),
                )

    @staticmethod
    def _config(run_id: UUID) -> dict[str, dict[str, str]]:
        return {"configurable": {"thread_id": str(run_id)}}

    def _finish_emergency(self, run_id: UUID, error_class: str) -> None:
        repository = self.context_loader.repository
        if repository.get_terminal_result(run_id) is not None:
            return
        context = repository.get_workflow_run_context(run_id)
        current = repository.get_current(UUID(str(context["asset_id"])))
        finished_at = datetime.now(UTC)
        started_at = datetime.fromisoformat(str(context["started_at"]))
        repository.finish_run_idempotent(
            TerminalResultV1(
                run_id=run_id,
                state=TerminalState.INTERNAL_ERROR,
                last_durable_version_id=current.version_id,
                retryable=False,
                safe_user_message="M5 stopped safely; no approval or export was granted.",
                internal_error_class=error_class,
                elapsed_ms=max(0, int((finished_at - started_at).total_seconds() * 1000)),
                model_call_count=0,
                recovery_action="Re-evaluate M5 from the current canonical version.",
                finished_at=finished_at,
            )
        )

    async def _load(self, state: M5GraphStateV1) -> M5GraphStateV1:
        loaded = self.context_loader.load(UUID(state.asset_id))
        stale = loaded.context.stale_reason()
        if (
            loaded.context.version_id != UUID(state.base_version_id)
            or loaded.content_hash != state.content_hash
            or loaded.context.relation.projection_hash != state.relation_projection_hash
        ):
            stale = "M5_INPUT_STALE"
        return state.model_copy(
            update={
                "last_node": "load_m5_context",
                "selected_edge": (
                    "load_m5_context:ready"
                    if stale is None
                    else "load_m5_context:not_ready_or_stale"
                ),
                "terminal_candidate": "" if stale is None else TerminalState.NEEDS_USER_INPUT.value,
                "finding_codes": [] if stale is None else [stale],
                "safe_message": "" if stale is None else "M5 input is not current and ready.",
            }
        )

    async def _evaluate(self, state: M5GraphStateV1) -> M5GraphStateV1:
        loaded = self.context_loader.load(UUID(state.asset_id))
        matrix = self.service.evaluate_routes(loaded.context)
        return state.model_copy(
            update={
                "last_node": "evaluate_m5_routes",
                "selected_edge": "evaluate_m5_routes:evaluated",
                "route_matrix_hash": route_matrix_hash(matrix),
            }
        )

    async def _review(self, state: M5GraphStateV1) -> M5GraphStateV1:
        loaded = self.context_loader.load(UUID(state.asset_id))
        run_id = UUID(state.run_id)
        existing = self.store.read_privacy_review(
            asset_id=UUID(state.asset_id),
            version_id=loaded.context.version_id,
            content_hash=loaded.content_hash,
        )
        review = (
            existing
            if existing is not None
            and existing.policy_version == PRIVACY_POLICY_VERSION
            and existing.detector_version == PRIVACY_TEXT_DETECTOR_VERSION
            else self.service.review_privacy(loaded.context, proposals=[], run_id=run_id)
        )
        matrix = self.service.evaluate_routes(loaded.context, privacy_review=review)
        changed = self.store.save_evaluation(
            review, matrix, content_hash=loaded.content_hash, run_id=run_id
        )
        if changed and existing is not None:
            self.store.mark_approvals_stale(
                asset_id=UUID(state.asset_id),
                reason="M5 policy outcome changed",
            )
        open_findings = [
            finding.category
            for finding in review.findings
            if finding.resolution is PrivacyResolution.OPEN
        ]
        return state.model_copy(
            update={
                "last_node": "review_m5_privacy",
                "selected_edge": (
                    "review_m5_privacy:open_findings"
                    if open_findings
                    else "review_m5_privacy:resolved_or_empty"
                ),
                "privacy_proposal_attempts": 1,
                "route_matrix_hash": route_matrix_hash(matrix),
                "privacy_review_hash": review.review_hash,
                "finding_codes": sorted(set(open_findings)),
            }
        )

    async def _wait_privacy(self, state: M5GraphStateV1) -> M5GraphStateV1:
        command = self.store.read_workflow_command(UUID(state.run_id))
        if command["command_kind"] == "RESOLVE":
            return state.model_copy(
                update={
                    "last_node": "wait_m5_privacy_resolution",
                    "selected_edge": "wait_m5_privacy_resolution:user_action",
                    "wait_reason": "",
                }
            )
        return state.model_copy(
            update={
                "last_node": "wait_m5_privacy_resolution",
                "selected_edge": "wait_m5_privacy_resolution:pause",
                "wait_reason": "PRIVACY_RESOLUTION_REQUIRED",
                "terminal_candidate": TerminalState.NEEDS_USER_INPUT.value,
                "safe_message": "Resolve privacy findings before approval.",
            }
        )

    async def _wait_approval(self, state: M5GraphStateV1) -> M5GraphStateV1:
        command = self.store.read_workflow_command(UUID(state.run_id))
        if command["command_kind"] == "APPROVE":
            return state.model_copy(
                update={
                    "last_node": "wait_m5_approval",
                    "selected_edge": "wait_m5_approval:explicit_action",
                    "wait_reason": "",
                }
            )
        return state.model_copy(
            update={
                "last_node": "wait_m5_approval",
                "selected_edge": "wait_m5_approval:pause",
                "wait_reason": "FINAL_DRAFT_REQUIRED",
                "terminal_candidate": TerminalState.NEEDS_USER_INPUT.value,
                "safe_message": "Create and review one final draft before approval.",
            }
        )

    async def _verify(self, state: M5GraphStateV1) -> M5GraphStateV1:
        return state.model_copy(
            update={
                "last_node": "verify_m5_state",
                "selected_edge": "verify_m5_state:verified",
                "terminal_candidate": TerminalState.SUCCEEDED.value,
                "safe_message": "Route readiness and privacy review were persisted.",
            }
        )

    async def _apply_resolution(self, state: M5GraphStateV1) -> M5GraphStateV1:
        run_id = UUID(state.run_id)
        command = self.store.read_workflow_command(run_id)
        loaded = self.context_loader.load(UUID(state.asset_id))
        review = self.store.read_privacy_review(
            asset_id=UUID(state.asset_id),
            version_id=loaded.context.version_id,
            content_hash=loaded.content_hash,
        )
        if review is None or command["finding_id"] is None or command["privacy_action"] is None:
            return state.model_copy(
                update={
                    "last_node": "apply_m5_privacy_resolution",
                    "selected_edge": "apply_m5_privacy_resolution:denied",
                    "terminal_candidate": TerminalState.NEEDS_USER_INPUT.value,
                    "finding_codes": ["PRIVACY_COMMAND_STALE"],
                    "safe_message": "Reload the current privacy review before resolving it.",
                }
            )
        action = PrivacyActionV1(command["privacy_action"])
        result = self.service.resolve_finding(
            loaded.context,
            review,
            finding_id=UUID(command["finding_id"]),
            action=action,
            run_id=run_id,
        )
        if result.requires_canonical_change:
            return state.model_copy(
                update={
                    "last_node": "apply_m5_privacy_resolution",
                    "selected_edge": "apply_m5_privacy_resolution:canonical_change",
                    "safe_message": (
                        "Edit the affected canonical statement to create a new version."
                    ),
                }
            )
        matrix = self.service.evaluate_routes(loaded.context, privacy_review=result.review)
        effect_key = f"m5:{run_id}:privacy:{command['finding_id']}:{action.value}"
        status, cached = self.context_loader.repository.claim_workflow_effect(
            effect_key=effect_key,
            run_id=run_id,
            node_name="apply_m5_privacy_resolution",
            node_attempt=state.node_attempt,
            started_at=datetime.now(UTC),
        )
        if status == "CLAIMED":
            self.store.save_evaluation(
                result.review, matrix, content_hash=loaded.content_hash, run_id=run_id
            )
            cached = {
                "privacy_review_hash": result.review.review_hash,
                "route_matrix_hash": route_matrix_hash(matrix),
            }
            self.context_loader.repository.complete_workflow_effect(
                effect_key=effect_key, result=cached, finished_at=datetime.now(UTC)
            )
        assert cached is not None
        return state.model_copy(
            update={
                "last_node": "apply_m5_privacy_resolution",
                "selected_edge": "apply_m5_privacy_resolution:recorded",
                **cached,
            }
        )

    async def _recompose(self, state: M5GraphStateV1) -> M5GraphStateV1:
        # Canonical edits belong to M1 and must append a new immutable version;
        # M5 never mutates text behind a privacy button.
        return state.model_copy(
            update={
                "last_node": "recompose_m5_context",
                "selected_edge": "recompose_m5_context:stale_or_exhausted",
                "terminal_candidate": TerminalState.NEEDS_USER_INPUT.value,
                "finding_codes": ["CANONICAL_CHANGE_REQUIRED"],
                "safe_message": (
                    "Open M1, edit the affected evidence, then rebuild M2-M4 and re-evaluate M5."
                ),
            }
        )

    async def _validate_approval(self, state: M5GraphStateV1) -> M5GraphStateV1:
        run_id = UUID(state.run_id)
        command = self.store.read_workflow_command(run_id)
        if self.draft_loader is None or command["route_draft_id"] is None:
            return self._approval_denied(state, "ROUTE_DRAFT_REQUIRED")
        loaded = self.context_loader.load(UUID(state.asset_id))
        review = self.store.read_privacy_review(
            asset_id=UUID(state.asset_id),
            version_id=loaded.context.version_id,
            content_hash=loaded.content_hash,
        )
        matrix = self.store.read_route_matrix(
            asset_id=UUID(state.asset_id),
            version_id=loaded.context.version_id,
            content_hash=loaded.content_hash,
        )
        if review is None or matrix is None:
            return self._approval_denied(state, "M5_EVALUATION_REQUIRED")
        draft = self.draft_loader(UUID(command["route_draft_id"]))
        if draft.asset_id != UUID(state.asset_id):
            return self._approval_denied(state, "ASSET_BINDING_MISMATCH")
        decision = next(item for item in matrix.decisions if item.route is draft.draft.route)
        binding_hash = route_draft_binding_hash(
            draft.draft,
            asset_content_hash=loaded.content_hash,
            relation_projection_hash=matrix.relation_projection_hash,
            route_decision=decision,
            renderer_input_hash=draft.renderer_input_identity,
        )
        request = ApprovalRequestV1(
            expected_asset_id=UUID(state.asset_id),
            expected_version_id=loaded.context.version_id,
            expected_content_hash=loaded.content_hash,
            route=draft.draft.route,
            language=draft.draft.language,
            expected_route_draft_hash=binding_hash,
            expected_privacy_review_hash=review.review_hash,
            user_action="APPROVE_SHAREABLE_EXPORT",
            idempotency_key=command["idempotency_key"] or str(state.command_id),
        )
        approval = self.service.approve(
            loaded.context,
            matrix,
            review,
            draft=draft.draft,
            renderer_input_hash=draft.renderer_input_identity,
            request=request,
            existing=self.store.list_approvals(
                asset_id=UUID(state.asset_id),
                version_id=loaded.context.version_id,
                content_hash=loaded.content_hash,
            ),
        )
        effect_key = f"m5:{run_id}:approval:{draft.draft.route_draft_id}"
        status, cached = self.context_loader.repository.claim_workflow_effect(
            effect_key=effect_key,
            run_id=run_id,
            node_name="validate_m5_approval",
            node_attempt=state.node_attempt,
            started_at=datetime.now(UTC),
        )
        if status == "CLAIMED":
            self.store.save_approval(
                approval,
                asset_id=UUID(state.asset_id),
                version_id=loaded.context.version_id,
                content_hash=loaded.content_hash,
                draft_id=draft.draft.route_draft_id,
                draft_binding_hash=draft.renderer_input_identity,
                matrix_hash=route_matrix_hash(matrix),
                run_id=run_id,
            )
            cached = {"approval_id": str(approval.approval_id)}
            self.context_loader.repository.complete_workflow_effect(
                effect_key=effect_key, result=cached, finished_at=datetime.now(UTC)
            )
        assert cached is not None
        return state.model_copy(
            update={
                "last_node": "validate_m5_approval",
                "selected_edge": "validate_m5_approval:valid",
                "approval_id": cached["approval_id"],
                "route_draft_binding_hash": binding_hash,
                "privacy_review_hash": review.review_hash,
                "route_matrix_hash": route_matrix_hash(matrix),
            }
        )

    @staticmethod
    def _approval_denied(state: M5GraphStateV1, code: str) -> M5GraphStateV1:
        return state.model_copy(
            update={
                "last_node": "validate_m5_approval",
                "selected_edge": "validate_m5_approval:denied_or_stale",
                "terminal_candidate": TerminalState.NEEDS_USER_INPUT.value,
                "finding_codes": [code],
                "safe_message": (
                    "Approval was denied because its exact binding is unavailable or stale."
                ),
            }
        )

    async def _terminalize(self, state: M5GraphStateV1) -> M5GraphStateV1:
        updated = state.model_copy(
            update={
                "last_node": "terminalize_m5_run",
                "selected_edge": "terminalize_m5_run:END",
            }
        )
        context = self.context_loader.repository.get_workflow_run_context(UUID(state.run_id))
        started_at = datetime.fromisoformat(str(context["started_at"]))
        finished_at = datetime.now(UTC)
        self.context_loader.repository.finish_run_idempotent(
            TerminalResultV1(
                run_id=UUID(state.run_id),
                state=TerminalState(updated.terminal_candidate or TerminalState.SUCCEEDED.value),
                last_durable_version_id=UUID(state.base_version_id),
                retryable=updated.retryable,
                safe_user_message=updated.safe_message or "M5 evaluation completed.",
                elapsed_ms=max(0, int((finished_at - started_at).total_seconds() * 1000)),
                model_call_count=0,
                recovery_action=(
                    "Resolve the visible finding or create a final draft."
                    if updated.terminal_candidate == TerminalState.NEEDS_USER_INPUT.value
                    else "No recovery required; continue to final draft review."
                ),
                finished_at=finished_at,
            )
        )
        return updated


__all__ = ["M5ProductionGraph"]
