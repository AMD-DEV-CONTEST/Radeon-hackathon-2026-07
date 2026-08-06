"""Startup-compiled M3 LangGraph with bounded, identifier-only cursor state."""

import hashlib
import json
from collections.abc import Awaitable, Callable
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4, uuid5

from langgraph.graph import END, START, StateGraph

from app.experience_asset.application.m3.service import M3ContractError, M3LedgerService
from app.experience_asset.domain.enums import Milestone, RetrievalScope, TerminalState
from app.experience_asset.domain.models import RuntimeToolCallProposal, TerminalResultV1
from app.experience_asset.inference import InvalidModelOutput, ModelClient, ModelRequest
from app.experience_asset.inference.models import (
    M3LedgerProposal,
    ModelTimedOut,
    ModelUnavailable,
    SourceExcerpt,
)
from app.experience_asset.persistence import AssetNotFoundError, SQLiteAssetRepository
from app.experience_asset.policy import RuntimePolicy

from .m3_state import (
    M3_GRAPH_NODES,
    M3_MODEL_CALL_BUDGET,
    M3_TOPOLOGY_HASH,
    M3_WORKFLOW_VERSION,
    M3GraphState,
    M3GraphStateV1,
    validate_m3_graph_state,
)

M3NodeOperation = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
M3_MAX_OUTPUT_TOKENS = 1536
M3_MODEL_TIMEOUT_SECONDS = 120


def m3_local_model_output_schema(
    *,
    max_entry_moments: int,
    allowed_statement_ids: list[str] | None = None,
    required_prior_decision_id: str | None = None,
) -> dict[str, Any]:
    """Bound one local-model call without narrowing the durable ledger contract."""

    if max_entry_moments < 1:
        raise ValueError("M3 model requests require at least one supplied moment")
    schema = M3LedgerProposal.model_json_schema()
    schema["properties"]["entries"]["maxItems"] = 1
    schema["properties"]["tool_call_proposals"]["maxItems"] = 1
    entry_schema = schema["$defs"]["M3ProposedEntry"]
    entry = entry_schema["properties"]
    entry["title"]["maxLength"] = 160
    entry["source_moment_ids"]["maxItems"] = max_entry_moments
    entry["statements"]["maxItems"] = 5
    if required_prior_decision_id is not None:
        entry["prior_decision_id"] = {
            "type": "string",
            "format": "uuid",
            "enum": [required_prior_decision_id],
        }
        entry_schema["required"] = [
            *entry_schema.get("required", []),
            "prior_decision_id",
        ]
    statement = schema["$defs"]["M3ProposedStatement"]["properties"]
    statement["text"]["maxLength"] = 480
    statement["source_moment_ids"]["maxItems"] = 3
    statement["source_statement_ids"]["maxItems"] = 4
    statement["derived_from_statement_ids"]["maxItems"] = 4
    if allowed_statement_ids:
        allowed_ids = sorted(set(allowed_statement_ids))
        statement["source_statement_ids"]["items"]["enum"] = allowed_ids
        statement["derived_from_statement_ids"]["items"]["enum"] = allowed_ids
    for option in statement["unresolved_reason"]["anyOf"]:
        if option.get("type") == "string":
            option["maxLength"] = 240
    # vLLM's guided-decoding backend may compile an object-level ``anyOf`` as
    # independent alternatives instead of merging each alternative with the
    # surrounding object schema.  Keep every branch self-contained so the
    # generated statement still includes the common required fields.  The
    # durable Runtime validation remains authoritative for evidence semantics.
    statement_schema = schema["$defs"]["M3ProposedStatement"]
    base_statement_schema = deepcopy(statement_schema)
    evidence_branches: list[dict[str, Any]] = []
    for evidence_field in (
        "source_statement_ids",
        "derived_from_statement_ids",
    ):
        branch = deepcopy(base_statement_schema)
        branch["required"] = [*branch["required"], evidence_field]
        branch["properties"][evidence_field]["minItems"] = 1
        evidence_branches.append(branch)
    unresolved_branch = deepcopy(base_statement_schema)
    unresolved_branch["required"] = [
        *unresolved_branch["required"],
        "unresolved_reason",
    ]
    unresolved_branch["properties"]["unresolved_reason"] = {
        "type": "string",
        "minLength": 1,
        "maxLength": 240,
    }
    statement_schema["anyOf"] = [*evidence_branches, unresolved_branch]
    return schema


def ensure_m3_entry_moment_coverage(
    proposal: M3LedgerProposal,
) -> M3LedgerProposal:
    """Append statement-used moments omitted from their containing entry.

    This only repairs the proposal's structural envelope. Unknown moment IDs and
    invalid statement-to-evidence links remain present for deterministic Runtime
    validation to reject.
    """

    entries = []
    for entry in proposal.entries:
        covered = list(entry.source_moment_ids)
        seen = set(covered)
        for statement in entry.statements:
            for moment_id in statement.source_moment_ids:
                if moment_id not in seen:
                    covered.append(moment_id)
                    seen.add(moment_id)
        entries.append(entry.model_copy(update={"source_moment_ids": covered}))
    return proposal.model_copy(update={"entries": entries})


class M3WorkflowRunError(M3ContractError):
    def __init__(self, message: str, run_id: UUID) -> None:
        super().__init__(message)
        self.run_id = run_id


class M3ProductionGraph:
    def __init__(
        self,
        *,
        repository: SQLiteAssetRepository,
        service: M3LedgerService,
        model_client: ModelClient,
        runtime_policy: RuntimePolicy,
        code_commit: str = "UNCOMMITTED",
    ) -> None:
        self.repository, self.service, self.model_client = repository, service, model_client
        self.runtime_policy, self.code_commit = runtime_policy, code_commit
        self._compiled: Any | None = None
        self.compile_count = 0

    def compile(self, checkpointer: Any) -> None:
        graph = StateGraph(M3GraphState)
        operations = dict(
            (
                ("load_m3_context", self.load),
                ("plan_m3_ledger", self.plan),
                ("validate_m3_output", self.validate),
                ("repair_m3_output", self.repair),
                ("evaluate_m3_tool_policy", self.policy),
                ("persist_m3_ledger", self.persist),
                ("verify_m3_ledger", self.verify),
                ("replan_m3_run", self.replan),
                ("terminalize_m3_run", self.terminalize),
            )
        )
        for name in M3_GRAPH_NODES:
            graph.add_node(name, self._traced_node(name, operations[name]))
        graph.add_edge(START, "load_m3_context")
        graph.add_conditional_edges(
            "load_m3_context",
            self._edge,
            {"ready": "plan_m3_ledger", "stale_or_incompatible": "terminalize_m3_run"},
        )
        graph.add_conditional_edges(
            "plan_m3_ledger",
            self._edge,
            {
                "proposal_ready": "validate_m3_output",
                "invalid_output": "repair_m3_output",
                "safe_failure": "terminalize_m3_run",
            },
        )
        graph.add_conditional_edges(
            "validate_m3_output",
            self._edge,
            {
                "valid": "evaluate_m3_tool_policy",
                "repairable": "repair_m3_output",
                "exhausted": "replan_m3_run",
            },
        )
        graph.add_conditional_edges(
            "repair_m3_output",
            self._edge,
            {
                "repaired": "validate_m3_output",
                "retry_repair": "repair_m3_output",
                "exhausted": "replan_m3_run",
                "safe_failure": "terminalize_m3_run",
            },
        )
        graph.add_conditional_edges(
            "evaluate_m3_tool_policy",
            self._edge,
            {"allow_or_no_tool": "persist_m3_ledger", "deny_or_invalid": "terminalize_m3_run"},
        )
        graph.add_conditional_edges(
            "persist_m3_ledger",
            self._edge,
            {"persisted": "verify_m3_ledger", "safe_failure": "replan_m3_run"},
        )
        graph.add_conditional_edges(
            "verify_m3_ledger",
            self._edge,
            {
                "verified": "terminalize_m3_run",
                "needs_replan": "replan_m3_run",
                "safe_failure": "terminalize_m3_run",
            },
        )
        graph.add_conditional_edges(
            "replan_m3_run",
            self._edge,
            {"replanned": "plan_m3_ledger", "exhausted": "terminalize_m3_run"},
        )
        graph.add_edge("terminalize_m3_run", END)
        self._compiled = graph.compile(checkpointer=checkpointer)
        self.compile_count += 1

    async def run_new(
        self,
        *,
        asset_id: UUID,
        m2_id: UUID,
        version_id: UUID,
        expected_invalidated_artifact_id: UUID | None = None,
    ):
        self.service.validate_create(
            asset_id, m2_id, version_id,
            regenerate=expected_invalidated_artifact_id is not None,
        )
        if expected_invalidated_artifact_id is not None:
            self.service.validate_regenerate(asset_id, expected_invalidated_artifact_id)
        run_id, command_id = uuid4(), uuid4()
        model_id, base_url, config_hash = self._identity()
        self.repository.start_workflow_run(
            run_id=run_id,
            asset_id=asset_id,
            base_version_id=version_id,
            command_id=command_id,
            command=(
                "E4-M3-ledger-regenerate-langgraph"
                if expected_invalidated_artifact_id
                else "E4-M3-ledger-langgraph"
            ),
            user_goal="Build an evidence-linked M3 ledger.",
            allow_current_source_search=False,
            workflow_version=M3_WORKFLOW_VERSION,
            topology_hash=M3_TOPOLOGY_HASH,
            model_id=model_id,
            model_config_hash=config_hash,
            server_base_url=base_url,
            code_commit=self.code_commit,
            started_at=datetime.now(UTC),
            base_m2_artifact_id=m2_id,
        )
        self.repository.configure_m3_run(
            run_id,
            regenerate=expected_invalidated_artifact_id is not None,
            expected_invalidated_artifact_id=expected_invalidated_artifact_id,
        )
        initial = M3GraphStateV1(
            run_id=str(run_id),
            asset_id=str(asset_id),
            base_version_id=str(version_id),
            base_m2_artifact_id=str(m2_id),
            regenerate=expected_invalidated_artifact_id is not None,
            expected_invalidated_artifact_id=(
                str(expected_invalidated_artifact_id) if expected_invalidated_artifact_id else None
            ),
            command_id=str(command_id),
            node_attempt=0,
        ).as_graph_state()
        try:
            await self._compiled.ainvoke(initial, self._config(run_id))
            await self._bind_trace_checkpoints(run_id)
        except BaseException as exc:
            self._finish_emergency(run_id, type(exc).__name__)
            if isinstance(exc, KeyboardInterrupt | SystemExit):
                raise
        terminal = self.repository.get_terminal_result(run_id)
        if terminal is None or terminal.state is not TerminalState.SUCCEEDED:
            raise M3WorkflowRunError(
                terminal.safe_user_message if terminal else "M3 stopped safely", run_id
            )
        return self.service.get(asset_id)

    async def load(self, state):
        validated = self._validated(state)
        context = self.repository.get_workflow_run_context(UUID(validated.run_id))
        if (
            not self._matches(context)
            or context["base_m2_artifact_id"] != validated.base_m2_artifact_id
        ):
            return self._failure(
                "load_m3_context",
                "stale_or_incompatible",
                "UPSTREAM_STALE",
                TerminalState.NEEDS_USER_INPUT,
            )
        self.service.validate_create(
            UUID(state["asset_id"]),
            UUID(state["base_m2_artifact_id"]),
            UUID(state["base_version_id"]),
            regenerate=validated.regenerate,
        )
        if validated.regenerate:
            self.service.validate_regenerate(
                UUID(validated.asset_id), UUID(validated.expected_invalidated_artifact_id)
            )
        return {"last_node": "load_m3_context", "selected_edge": "ready"}

    async def plan(self, state):
        return await self._generate_proposal(state)

    async def _generate_proposal(
        self,
        state,
        *,
        repair_feedback: dict[str, Any] | None = None,
    ):
        validated = self._validated(state)
        if validated.model_call_count >= M3_MODEL_CALL_BUDGET:
            return self._failure(
                "plan_m3_ledger",
                "safe_failure",
                "MODEL_CALL_BUDGET_EXHAUSTED",
                TerminalState.INVALID_MODEL_OUTPUT,
            )
        m2 = self.repository.get_current_m2(UUID(state["asset_id"]))
        current = self.repository.get_current(UUID(state["asset_id"]))
        context: dict[str, Any] = {
            "asset_id": state["asset_id"],
            "version_id": state["base_version_id"],
            "moment_ids": [str(m.moment_id) for m in m2.moments],
            "moments": [
                {
                    "moment_id": str(moment.moment_id),
                    "display_order": moment.display_order,
                    "title": moment.title,
                    "description": moment.description,
                    "criticality_status": moment.criticality_status,
                    "temporal_status": moment.temporal_status,
                    "time_label": getattr(moment, "time_label", None),
                    "source_statement_ids": [
                        str(statement_id) for statement_id in moment.source_statement_ids
                    ],
                    "cue_statement_ids": [
                        str(statement_id) for statement_id in moment.cue_statement_ids
                    ],
                    "change_statement_ids": [
                        str(statement_id) for statement_id in moment.change_statement_ids
                    ],
                    "surprise_statement_ids": [
                        str(statement_id) for statement_id in moment.surprise_statement_ids
                    ],
                    "conflict_statement_ids": [
                        str(statement_id) for statement_id in moment.conflict_statement_ids
                    ],
                }
                for moment in m2.moments
            ],
        }
        if repair_feedback is not None:
            context["repair_feedback"] = repair_feedback
        invalidated = None
        if validated.regenerate:
            invalidated = self.repository.get_m3_artifact(
                UUID(validated.expected_invalidated_artifact_id)
            )
            self.service.validate_regenerate(UUID(validated.asset_id), invalidated.artifact_id)
        if invalidated is not None:
            reusable = [
                entry
                for entry in invalidated.entries
                if entry.decision_id in invalidated.reusable_entry_ids
            ]
            context.update(
                expected_invalidated_artifact_id=str(invalidated.artifact_id),
                affected_entry_ids=[str(item) for item in invalidated.affected_entry_ids],
                reusable_entries=[entry.model_dump(mode="json") for entry in reusable],
            )
        allowed_statement_ids = sorted(
            {
                str(statement_id)
                for moment in m2.moments
                for statement_id in moment.source_statement_ids
            }
        )
        repair_policy = ""
        if repair_feedback is not None:
            repair_policy = (
                " This is a correction request. The prior proposal failed deterministic "
                f"validation: {repair_feedback['validation_error']}. Return a complete "
                "replacement proposal. For every statement, either use one or more exact "
                "statement IDs listed under its declared moments, or leave both reference "
                "arrays empty and provide a non-empty unresolved_reason. Do not repeat the "
                "rejected evidence shape."
            )
        request = ModelRequest(
            run_id=UUID(state["run_id"]),
            stage=(
                "E4-M3-ledger-repair" if repair_feedback is not None else "E4-M3-ledger"
            ),
            system_policy=(
                "Return exactly one concise evidence-linked decision-ledger entry for the most "
                "material decision in the supplied moments. Return exactly five statements, one "
                "for each role: ALTERNATIVE, REASON, DECISION, ACTION, OBSERVED_RESULT. Keep each "
                "statement under 480 characters and the title under 160 characters. Link both "
                "source_statement_ids and derived_from_statement_ids only to statement IDs "
                "belonging to the declared source_moment_ids. Set "
                "the entry source_moment_ids to the de-duplicated union of every statement's "
                "source_moment_ids; every statement source_moment_ids list must be a subset of "
                "the entry list. Never "
                "invent missing results or permissions; if evidence is absent, leave reference "
                "arrays empty and set unresolved_reason. Do not propose a tool unless essential. "
                "During regeneration, replace the single affected decision by setting "
                "prior_decision_id to the exact affected_entry_ids value; do not change reusable "
                "decision identities." + repair_policy
            ),
            canonical_context=context,
            source_excerpts=[
                SourceExcerpt(
                    source_id=current.sources[0].source_id,
                    span_id=f"statement:{s.statement_id}",
                    text=s.text,
                )
                for s in current.statements
            ],
            output_schema=m3_local_model_output_schema(
                max_entry_moments=len(m2.moments),
                allowed_statement_ids=allowed_statement_ids,
                required_prior_decision_id=(
                    context["affected_entry_ids"][0]
                    if validated.regenerate
                    else None
                ),
            ),
            max_output_tokens=M3_MAX_OUTPUT_TOKENS,
            timeout_seconds=M3_MODEL_TIMEOUT_SECONDS,
        )
        calls = validated.model_call_count
        try:
            result = await self._model_call(request, calls + 1)
            calls += 1
        except (ModelUnavailable, ModelTimedOut) as original_exc:
            exc: ModelUnavailable | ModelTimedOut | None = original_exc
            calls += 1
            # Exactly one transient retry; each actual invocation consumes budget.
            if validated.node_attempt == 0 and calls < M3_MODEL_CALL_BUDGET:
                try:
                    result = await self._model_call(request, calls + 1)
                except (ModelUnavailable, ModelTimedOut) as retry_exc:
                    exc = retry_exc
                    calls += 1
                else:
                    calls += 1
                    exc = None
            if exc is not None:
                terminal = (
                    TerminalState.MODEL_UNAVAILABLE
                    if isinstance(exc, ModelUnavailable)
                    else TerminalState.TIMED_OUT
                )
                code = (
                    "MODEL_UNAVAILABLE"
                    if isinstance(exc, ModelUnavailable)
                    else "MODEL_TIMED_OUT"
                )
                return {
                    **self._failure("plan_m3_ledger", "safe_failure", code, terminal),
                    "model_call_count": calls,
                    "node_attempt": 1,
                }
        except InvalidModelOutput:
            return {
                "last_node": "plan_m3_ledger",
                "selected_edge": "invalid_output",
                "terminal_candidate": "",
                "finding_codes": ["INVALID_MODEL_OUTPUT"],
                "safe_message": "Structured output was invalid; attempting bounded repair.",
                "model_call_count": calls + 1,
            }
        proposal = ensure_m3_entry_moment_coverage(result.proposal)
        digest = hashlib.sha256(
            json.dumps(proposal.model_dump(mode="json"), sort_keys=True).encode()
        ).hexdigest()
        attempt = calls
        self.repository.save_m3_proposal(
            UUID(state["run_id"]),
            attempt,
            proposal,
            digest,
            result.metadata,
        )
        return {
            "last_node": "plan_m3_ledger",
            "selected_edge": "proposal_ready",
            "structured_proposal_hash": digest,
            "model_call_count": attempt,
            "proposal_attempt": attempt,
            "node_attempt": 0,
        }

    async def validate(self, state):
        validated = self._validated(state)
        try:
            proposal, digest = self.repository.get_m3_proposal(
                UUID(validated.run_id), validated.proposal_attempt
            )
            if digest != validated.structured_proposal_hash:
                raise M3ContractError("proposal hash mismatch")
            previous = None
            if validated.regenerate:
                previous = self.repository.get_m3_artifact(
                    UUID(validated.expected_invalidated_artifact_id)
                )
                self.service.validate_regenerate(UUID(validated.asset_id), previous.artifact_id)
            self.service.validate_proposal(UUID(validated.asset_id), proposal, previous=previous)
        except (M3ContractError, AssetNotFoundError) as exc:
            if validated.structured_repair_attempts < 2 and validated.model_call_count < 4:
                return {
                    "last_node": "validate_m3_output",
                    "selected_edge": "repairable",
                    "finding_codes": [type(exc).__name__],
                }
            return {
                **self._failure(
                    "validate_m3_output",
                    "exhausted",
                    "STRUCTURED_REPAIR_EXHAUSTED",
                    TerminalState.INVALID_MODEL_OUTPUT,
                ),
                "structured_repair_attempts": validated.structured_repair_attempts,
            }
        return {"last_node": "validate_m3_output", "selected_edge": "valid", "finding_codes": []}

    def _build_repair_feedback(self, validated: M3GraphStateV1) -> dict[str, Any]:
        """Reconstruct bounded feedback without placing proposal content in graph state."""

        feedback: dict[str, Any] = {
            "validation_error": (
                "The prior response did not satisfy the structured output contract."
            )
        }
        if not validated.proposal_attempt or not validated.structured_proposal_hash:
            return feedback
        proposal = None
        try:
            proposal, digest = self.repository.get_m3_proposal(
                UUID(validated.run_id), validated.proposal_attempt
            )
            if digest != validated.structured_proposal_hash:
                feedback["validation_error"] = "The prior proposal hash did not match."
                return feedback
            previous = None
            if validated.regenerate:
                previous = self.repository.get_m3_artifact(
                    UUID(validated.expected_invalidated_artifact_id)
                )
            self.service.validate_proposal(UUID(validated.asset_id), proposal, previous=previous)
        except (M3ContractError, AssetNotFoundError) as exc:
            feedback["validation_error"] = str(exc)
            if proposal is not None:
                feedback["rejected_proposal"] = proposal.model_dump(mode="json")
        return feedback

    async def repair(self, state):
        validated = self._validated(state)
        if validated.structured_repair_attempts >= 2 or validated.model_call_count >= 4:
            code = (
                "MODEL_CALL_BUDGET_EXHAUSTED"
                if validated.model_call_count >= 4
                else "STRUCTURED_REPAIR_EXHAUSTED"
            )
            return self._failure(
                "repair_m3_output", "exhausted", code, TerminalState.INVALID_MODEL_OUTPUT
            )
        feedback = self._build_repair_feedback(validated)
        update = await self._generate_proposal(state, repair_feedback=feedback)
        update["last_node"] = "repair_m3_output"
        update["structured_repair_attempts"] = validated.structured_repair_attempts + 1
        if update.get("selected_edge") == "safe_failure":
            update["selected_edge"] = "safe_failure"
        elif update.get("structured_proposal_hash"):
            update["selected_edge"] = "repaired"
        elif (
            update.get("selected_edge") == "invalid_output"
            and validated.structured_repair_attempts + 1 < 2
        ):
            update["selected_edge"] = "retry_repair"
        else:
            update["selected_edge"] = "exhausted"
        return update

    async def replan(self, state):
        validated = self._validated(state)
        if validated.replan_attempts >= 1 or validated.model_call_count >= 4:
            code = (
                "MODEL_CALL_BUDGET_EXHAUSTED"
                if validated.model_call_count >= 4
                else "REPLAN_EXHAUSTED"
            )
            return {
                **self._failure(
                    "replan_m3_run", "exhausted", code, TerminalState.INVALID_MODEL_OUTPUT
                ),
                "replan_attempts": validated.replan_attempts,
            }
        # Replan is deterministic and consumes no model call; the following plan is final.
        return {
            "last_node": "replan_m3_run",
            "selected_edge": "replanned",
            "replan_attempts": validated.replan_attempts + 1,
            "terminal_candidate": "",
            "safe_message": "",
            "node_attempt": 0,
        }

    async def policy(self, state):
        if state.get("terminal_candidate"):
            return {"last_node": "evaluate_m3_tool_policy", "selected_edge": "deny_or_invalid"}
        proposal, _ = self.repository.get_m3_proposal(
            UUID(state["run_id"]), state["proposal_attempt"]
        )
        decisions = []
        run_id = UUID(state["run_id"])
        for index, tool in enumerate(proposal.tool_call_proposals):
            proposal_id = uuid5(
                run_id,
                f"m3-tool:{state['proposal_attempt']}:{index}",
            )
            runtime_proposal = RuntimeToolCallProposal(
                proposal_id=proposal_id,
                name=tool.name,
                arguments=tool.arguments,
                base_version_id=UUID(state["base_version_id"]),
                proposed_at=datetime.now(UTC),
                permission_granted=False,
            )
            run_state = SimpleNamespace(
                run_id=UUID(state["run_id"]),
                asset_id=UUID(state["asset_id"]),
                base_version_id=UUID(state["base_version_id"]),
                permission_snapshot={},
                retrieval_scope=RetrievalScope.CURRENT_SOURCE,
                knowledge_card_version_id=None,
                knowledge_card_hash=None,
                confirmed_relation_ids=[],
                relation_candidate_ids=[],
                confirmed_relation_bindings=[],
            )
            decision = self.repository.get_m3_policy_decision(
                run_id=run_id,
                proposal_attempt=state["proposal_attempt"],
                proposal_id=proposal_id,
            )
            if decision is None:
                decision = self.runtime_policy.evaluate(
                    state=run_state,
                    proposal=runtime_proposal,
                )
                self.repository.save_m3_policy_decision(
                    run_id=run_id,
                    proposal_attempt=state["proposal_attempt"],
                    decision=decision,
                )
            decisions.append(decision)
        if decisions:
            reason_codes = sorted(
                {code for decision in decisions for code in decision.reason_codes}
            )
            return {
                "last_node": "evaluate_m3_tool_policy",
                "selected_edge": "deny_or_invalid",
                "policy_decision_id": str(decisions[0].decision_id),
                "terminal_candidate": "POLICY_BLOCKED",
                "finding_codes": reason_codes,
                "safe_message": "M3 tool proposal was denied with zero effects.",
                "retryable": False,
            }
        return {"last_node": "evaluate_m3_tool_policy", "selected_edge": "allow_or_no_tool"}

    async def persist(self, state):
        if state.get("terminal_candidate"):
            return {"last_node": "persist_m3_ledger", "selected_edge": "safe_failure"}
        run_id = UUID(state["run_id"])
        committed = self.repository.get_m3_run_commit(run_id)
        if committed is not None:
            existing, canonical = committed
            return {
                "last_node": "persist_m3_ledger",
                "selected_edge": "persisted",
                "artifact_id": str(existing.artifact_id),
                "canonical_version_id": str(canonical.version_id),
            }
        proposal, digest = self.repository.get_m3_proposal(
            UUID(state["run_id"]), state["proposal_attempt"]
        )
        if digest != state["structured_proposal_hash"]:
            raise M3ContractError("M3 proposal hash changed")
        artifact = self.service.create_for_run(
            UUID(state["asset_id"]),
            m2_id=UUID(state["base_m2_artifact_id"]),
            version_id=UUID(state["base_version_id"]),
            run_id=run_id,
            proposal=proposal,
            expected_invalidated_artifact_id=(
                UUID(state["expected_invalidated_artifact_id"])
                if state.get("expected_invalidated_artifact_id") else None
            ),
        )
        canonical = self.repository.get_current(UUID(state["asset_id"]))
        return {
            "last_node": "persist_m3_ledger",
            "selected_edge": "persisted",
            "artifact_id": str(artifact.artifact_id),
            "canonical_version_id": str(canonical.version_id),
        }

    async def verify(self, state):
        if state.get("terminal_candidate"):
            return {"last_node": "verify_m3_ledger", "selected_edge": "safe_failure"}
        committed = self.repository.get_m3_run_commit(UUID(state["run_id"]))
        if committed is None:
            raise M3ContractError("persisted M3 run commit is missing")
        artifact, canonical = committed
        if (str(artifact.artifact_id), str(canonical.version_id)) != (
            state["artifact_id"], state["canonical_version_id"]
        ):
            raise M3ContractError("persisted M3 run-owned identities mismatch")
        projection = next(
            (item for item in canonical.milestone_artifacts if item.milestone is Milestone.M3), None
        )
        if projection is None or projection.payload.get("m3_artifact_id") != state["artifact_id"]:
            raise M3ContractError("committed canonical M3 projection mismatch")
        return {
            "last_node": "verify_m3_ledger",
            "selected_edge": "verified",
            "terminal_candidate": "SUCCEEDED",
            "safe_message": "M3 ledger saved and verified.",
        }

    async def terminalize(self, state):
        terminal = TerminalState(state.get("terminal_candidate") or TerminalState.INTERNAL_ERROR)
        run_id = UUID(state["run_id"])
        current = self.repository.get_current(UUID(state["asset_id"]))
        from app.experience_asset.domain.models import TerminalResultV1

        retryable = terminal in {
            TerminalState.INVALID_MODEL_OUTPUT,
            TerminalState.MODEL_UNAVAILABLE,
            TerminalState.TIMED_OUT,
            TerminalState.STORAGE_ERROR,
            TerminalState.INTERNAL_ERROR,
        }
        if terminal is TerminalState.SUCCEEDED:
            recovery_action = "No recovery required."
        elif terminal is TerminalState.POLICY_BLOCKED:
            recovery_action = (
                "Retry without the denied tool proposal; no tool effect was executed."
            )
        elif state.get("regenerate"):
            recovery_action = "Retry explicit M3 regeneration after resolving the failure."
        else:
            recovery_action = "Retry M3 creation after resolving the failure."

        self.repository.update_m3_run_outcome(
            run_id,
            repairs=state.get("structured_repair_attempts", 0),
            replans=state.get("replan_attempts", 0),
            finding_codes=state.get("finding_codes", []),
        )
        self.repository.finish_run_idempotent(
            TerminalResultV1(
                run_id=run_id,
                state=terminal,
                last_durable_version_id=current.version_id,
                retryable=retryable,
                safe_user_message=state.get("safe_message") or "M3 stopped safely.",
                internal_error_class=None
                if terminal is TerminalState.SUCCEEDED
                else "M3WorkflowFailure",
                elapsed_ms=self._elapsed_ms(run_id),
                model_call_count=state.get("model_call_count", 0),
                recovery_action=recovery_action,
                finished_at=datetime.now(UTC),
            )
        )
        return {"last_node": "terminalize_m3_run", "selected_edge": "end"}

    async def recover_incomplete_runs(self):
        # Identity mismatch terminalizes instead of replaying an uncertain effect.
        for run_id in self.repository.list_incomplete_workflow_run_ids(M3_WORKFLOW_VERSION):
            context = self.repository.get_workflow_run_context(run_id)
            if not self._matches(context):
                current = self.repository.get_current(UUID(str(context["asset_id"])))
                from app.experience_asset.domain.models import TerminalResultV1

                self.repository.finish_run_idempotent(
                    TerminalResultV1(
                        run_id=run_id,
                        state=TerminalState.INTERNAL_ERROR,
                        last_durable_version_id=current.version_id,
                        retryable=False,
                        safe_user_message="M3 workflow identity changed; no effect was replayed.",
                        internal_error_class="WorkflowIdentityMismatch",
                        elapsed_ms=self._elapsed_ms(run_id),
                        model_call_count=self.repository.count_workflow_effects(
                            run_id, "m3_model_call"
                        ),
                        recovery_action="Start explicit regeneration.",
                        finished_at=datetime.now(UTC),
                    )
                )
            else:
                await self.resume_incomplete(run_id)

    async def resume_incomplete(self, run_id: UUID) -> None:
        context = self.repository.get_workflow_run_context(run_id)
        if not self._matches(context):
            self._finish_emergency(run_id, "WorkflowIdentityMismatch")
            return
        try:
            snapshot = await self._compiled.aget_state(self._config(run_id))
            if not snapshot.values:
                raise M3ContractError("missing M3 checkpoint")
            validate_m3_graph_state(snapshot.values)
            if snapshot.next:
                await self._compiled.ainvoke(None, self._config(run_id))
            elif self.repository.get_terminal_result(run_id) is None:
                raise M3ContractError("M3 graph ended without terminal result")
            await self._bind_trace_checkpoints(run_id)
        except BaseException as exc:
            self._finish_emergency(run_id, type(exc).__name__)
            if isinstance(exc, KeyboardInterrupt | SystemExit):
                raise

    def _finish_emergency(self, run_id: UUID, error_class: str) -> None:
        if self.repository.get_terminal_result(run_id) is not None:
            return
        context = self.repository.get_workflow_run_context(run_id)
        current = self.repository.get_current(UUID(str(context["asset_id"])))
        self.repository.finish_run_idempotent(
            TerminalResultV1(
                run_id=run_id,
                state=TerminalState.INTERNAL_ERROR,
                last_durable_version_id=current.version_id,
                retryable=False,
                safe_user_message="M3 stopped safely; the last durable version was preserved.",
                internal_error_class=error_class,
                elapsed_ms=self._elapsed_ms(run_id),
                model_call_count=self.repository.count_workflow_effects(run_id, "m3_model_call"),
                recovery_action="Start explicit regeneration.",
                finished_at=datetime.now(UTC),
            )
        )

    @staticmethod
    def _edge(state):
        return state["selected_edge"]

    def _traced_node(
        self,
        node_name: str,
        operation: M3NodeOperation,
    ) -> M3NodeOperation:
        async def traced(state: dict[str, Any]) -> dict[str, Any]:
            started = datetime.now(UTC)
            validated = self._validated(state)
            try:
                update = await operation(state)
            except BaseException as exc:
                self.repository.record_workflow_trace(
                    run_id=UUID(validated.run_id),
                    workflow_version=M3_WORKFLOW_VERSION,
                    topology_hash=M3_TOPOLOGY_HASH,
                    node_name=node_name,
                    node_attempt=validated.node_attempt,
                    selected_edge=None,
                    input_refs=self._trace_input_refs(validated),
                    output_refs=[],
                    policy_outcome=None,
                    tool_execution_status=None,
                    verification_outcome="REJECTED",
                    terminal_state=TerminalState.INTERNAL_ERROR.value,
                    finding_codes=[type(exc).__name__],
                    started_at=started,
                    finished_at=datetime.now(UTC),
                )
                raise
            self._record_node_trace(node_name, validated, update, started)
            return update

        return traced

    def _record_node_trace(
        self,
        node_name: str,
        validated: M3GraphStateV1,
        update: dict[str, Any],
        started: datetime,
    ) -> None:
        finding_codes = [str(code) for code in update.get("finding_codes") or []]
        denied = (
            node_name == "evaluate_m3_tool_policy"
            and update.get("selected_edge") == "deny_or_invalid"
        )
        self.repository.record_workflow_trace(
            run_id=UUID(validated.run_id),
            workflow_version=M3_WORKFLOW_VERSION,
            topology_hash=M3_TOPOLOGY_HASH,
            node_name=node_name,
            node_attempt=validated.node_attempt,
            selected_edge=str(update.get("selected_edge") or ""),
            input_refs=self._trace_input_refs(validated),
            output_refs=[
                ref
                for ref in (
                    f"artifact:{update['artifact_id']}"
                    if update.get("artifact_id")
                    else None,
                    f"version:{update['canonical_version_id']}"
                    if update.get("canonical_version_id")
                    else None,
                    f"policy:{update['policy_decision_id']}"
                    if update.get("policy_decision_id")
                    else None,
                )
                if ref is not None
            ],
            policy_outcome="DENY" if denied else None,
            tool_execution_status="NOT_EXECUTED" if denied else None,
            verification_outcome=(
                "VERIFIED"
                if node_name == "verify_m3_ledger"
                and update.get("selected_edge") == "verified"
                else "REJECTED"
                if finding_codes
                else None
            ),
            terminal_state=str(update.get("terminal_candidate") or "") or None,
            finding_codes=finding_codes,
            started_at=started,
            finished_at=datetime.now(UTC),
        )

    @staticmethod
    def _trace_input_refs(validated: M3GraphStateV1) -> list[str]:
        return [
            f"run:{validated.run_id}",
            f"asset:{validated.asset_id}",
            f"version:{validated.base_version_id}",
            f"m2:{validated.base_m2_artifact_id}",
        ]

    async def _bind_trace_checkpoints(self, run_id: UUID) -> None:
        async for snapshot in self._compiled.aget_state_history(self._config(run_id)):
            values = snapshot.values
            if not values:
                continue
            node_name = str(values.get("last_node") or "")
            checkpoint_id = snapshot.config["configurable"].get("checkpoint_id")
            if node_name and checkpoint_id:
                self.repository.bind_workflow_trace_checkpoint(
                    run_id=run_id,
                    node_name=node_name,
                    checkpoint_id=str(checkpoint_id),
                )

    @staticmethod
    def _config(run_id):
        return {"configurable": {"thread_id": str(run_id)}}

    def _elapsed_ms(self, run_id: UUID) -> int:
        context = self.repository.get_workflow_run_context(run_id)
        started = datetime.fromisoformat(str(context["started_at"]))
        return max(0, round((datetime.now(UTC) - started).total_seconds() * 1000))

    @staticmethod
    def _failure(node, edge, code, terminal):
        return {
            "last_node": node,
            "selected_edge": edge,
            "terminal_candidate": terminal.value,
            "finding_codes": [code],
            "safe_message": f"M3 stopped safely ({code}); no invalid ledger was saved.",
            "retryable": False,
        }

    def _validated(self, state):
        validated = validate_m3_graph_state(state)
        context = self.repository.get_workflow_run_context(UUID(validated.run_id))
        if (
            context["asset_id"] != validated.asset_id
            or context["base_version_id"] != validated.base_version_id
            or context["command_id"] != validated.command_id
            or context["base_m2_artifact_id"] != validated.base_m2_artifact_id
            or context["m3_regenerate"] != validated.regenerate
            or context["expected_invalidated_m3_artifact_id"]
            != validated.expected_invalidated_artifact_id
        ):
            raise M3ContractError("M3 cursor differs from durable run context")
        return validated

    async def _model_call(self, request: ModelRequest, attempt: int):
        """Reserve every invocation and replay only a durably cached outcome."""
        key = f"m3:model:{request.run_id}:{attempt}"
        status, cached = self.repository.claim_workflow_effect(
            effect_key=key,
            run_id=request.run_id,
            node_name="m3_model_call",
            node_attempt=attempt,
            started_at=datetime.now(UTC),
        )
        if status == "COMPLETED":
            return self._decode_model_outcome(cached)
        try:
            result = await self.model_client.generate_m3_ledger(request)
            outcome = {"kind": "result", "result": result.model_dump(mode="json")}
        except InvalidModelOutput as exc:
            outcome = {"kind": "invalid", "message": str(exc)}
        except ModelUnavailable as exc:
            outcome = {"kind": "unavailable", "message": str(exc)}
        except ModelTimedOut as exc:
            outcome = {"kind": "timeout", "message": str(exc)}
        self.repository.complete_workflow_effect(
            effect_key=key, result=outcome, finished_at=datetime.now(UTC)
        )
        return self._decode_model_outcome(outcome)

    @staticmethod
    def _decode_model_outcome(outcome):
        if outcome["kind"] == "result":
            from app.experience_asset.inference.models import M3LedgerResult

            return M3LedgerResult.model_validate(outcome["result"])
        error = {
            "invalid": InvalidModelOutput,
            "unavailable": ModelUnavailable,
            "timeout": ModelTimedOut,
        }[outcome["kind"]]
        raise error(str(outcome.get("message", outcome["kind"])))

    def _identity(self):
        model = str(getattr(self.model_client, "model_id", "deterministic-contract-fake"))
        url = str(getattr(self.model_client, "base_url", "http://127.0.0.1/fake"))
        return (
            model,
            url,
            hashlib.sha256(f"{model}|{url}|{M3_WORKFLOW_VERSION}".encode()).hexdigest(),
        )

    def _matches(self, context):
        model, url, digest = self._identity()
        return (
            context["workflow_version"] == M3_WORKFLOW_VERSION
            and context["topology_hash"] == M3_TOPOLOGY_HASH
            and context["model_id"] == model
            and context["server_base_url"] == url
            and context["model_config_hash"] == digest
            and context["code_commit"] == self.code_commit
        )
