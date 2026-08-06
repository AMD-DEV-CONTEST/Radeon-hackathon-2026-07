"""Startup-compiled M4 LangGraph with bounded, identifier-only cursor state."""

import hashlib
import json
from collections.abc import Awaitable, Callable
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4, uuid5

from langgraph.graph import END, START, StateGraph

from app.experience_asset.application.m4.service import M4ContractError, M4MapService
from app.experience_asset.domain.enums import Milestone, RetrievalScope, TerminalState
from app.experience_asset.domain.models import RuntimeToolCallProposal, TerminalResultV1
from app.experience_asset.inference import InvalidModelOutput, ModelClient, ModelRequest
from app.experience_asset.inference.budget import (
    describe_budget,
    prompt_budget_tokens,
    resolve_counter,
)
from app.experience_asset.inference.models import (
    M4MapProposal,
    ModelTimedOut,
    ModelUnavailable,
    SourceExcerpt,
)
from app.experience_asset.persistence import AssetNotFoundError, SQLiteAssetRepository
from app.experience_asset.policy import RuntimePolicy

from .m4_state import (
    M4_GRAPH_NODES,
    M4_MODEL_CALL_BUDGET,
    M4_REPLAN_BUDGET,
    M4_STRUCTURED_REPAIR_BUDGET,
    M4_TOPOLOGY_HASH,
    M4_WORKFLOW_VERSION,
    M4GraphState,
    M4GraphStateV1,
    validate_m4_graph_state,
)

M4NodeOperation = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
M4_MAX_OUTPUT_TOKENS = 2048
M4_MODEL_TIMEOUT_SECONDS = 120

# The M4 payload is strictly larger than M3's: every insight needs its decision,
# the statements that decision rests on, and room for six roles. E4's first
# blocker was an oversized pre-injected payload returning 422 or silently
# truncating, and a truncated context yields a proposal citing records the model
# never saw — which then fails Runtime validation for reasons that read as model
# quality rather than payload size. These bounds are applied deterministically
# and recorded with the run so the two stay distinguishable afterwards.
M4_MAX_CONTEXT_DECISIONS = 6
"""A ceiling. The binding constraint is the token budget, applied below."""
M4_MAX_CONTEXT_STATEMENTS = 40
M4_MAX_EXCERPT_CHARS = 480

M4_SYSTEM_POLICY = (
    "Return exactly one insight entry for the most transferable lesson in the "
    "supplied decisions. Return exactly six statements, one for each role: "
    "LESSON, SUPPORT, COUNTERFACTUAL, LIMITATION, COUNTEREXAMPLE, APPLICABILITY. "
    "The boundary roles are not optional enrichment: a lesson shown without its "
    "limitation and its transfer condition reads as general advice, and the reader "
    "applies it where the original experience never reached. Keep each statement "
    "under 1200 characters and the title under 160 characters. Cite only IDs from "
    "allowed_statement_ids, and only those belonging to the entry's declared "
    "source_decision_ids. Never invent evidence: if the supplied decisions do not "
    "support a role, leave both reference arrays empty and set gap_reason, so the "
    "gap is visible instead of reading as a finished lesson. Do not propose a tool "
    "unless essential. During regeneration, replace the single affected insight by "
    "setting prior_insight_id to the exact affected_insight_ids value; do not "
    "change reusable insight identities. The LESSON and SUPPORT roles are the "
    "core claim and its evidence: both must cite at least one supplied statement "
    "so the user can open the original evidence. Boundary roles may instead "
    "expose an explicit evidence gap."
)
"""Hoisted out of the request so sizing counts the text actually sent.

Sizing against a stand-in constant would be a fabricated measurement: it drifts
from the policy the moment either is edited, and the drift is invisible because
the estimate and a real count look identical on the record.
"""


def m4_local_model_output_schema(
    *,
    max_entry_decisions: int,
    allowed_decision_ids: list[str] | None = None,
    allowed_statement_ids: list[str] | None = None,
    required_prior_insight_id: str | None = None,
) -> dict[str, Any]:
    """Bound one local-model call without narrowing the durable map contract."""

    if max_entry_decisions < 1:
        raise ValueError("M4 model requests require at least one supplied decision")
    schema = M4MapProposal.model_json_schema()
    schema["properties"]["entries"]["maxItems"] = 1
    schema["properties"]["tool_call_proposals"]["maxItems"] = 1
    entry_schema = schema["$defs"]["M4ProposedEntry"]
    entry = entry_schema["properties"]
    entry["title"]["maxLength"] = 160
    entry["source_decision_ids"]["maxItems"] = max_entry_decisions
    entry["statements"]["maxItems"] = 6
    if allowed_decision_ids:
        entry["source_decision_ids"]["items"]["enum"] = sorted(set(allowed_decision_ids))
    if required_prior_insight_id is not None:
        entry["prior_insight_id"] = {
            "type": "string",
            "format": "uuid",
            "enum": [required_prior_insight_id],
        }
        entry_schema["required"] = [
            *entry_schema.get("required", []),
            "prior_insight_id",
        ]
    statement_schema = schema["$defs"]["M4ProposedStatement"]
    statement = statement_schema["properties"]
    statement["text"]["maxLength"] = 1200
    statement["source_statement_ids"]["maxItems"] = 6
    statement["source_decision_ids"]["maxItems"] = max_entry_decisions
    if allowed_statement_ids:
        statement["source_statement_ids"]["items"]["enum"] = sorted(set(allowed_statement_ids))
    if allowed_decision_ids:
        statement["source_decision_ids"]["items"]["enum"] = sorted(set(allowed_decision_ids))
    for option in statement["gap_reason"]["anyOf"]:
        if option.get("type") == "string":
            option["maxLength"] = 240
    # vLLM's guided-decoding backend may compile an object-level ``anyOf`` as
    # independent alternatives rather than merging each with the surrounding
    # object schema. Keep every branch self-contained so a generated statement
    # still carries the common required fields; durable Runtime validation
    # remains authoritative for grounding semantics.
    base_statement_schema = deepcopy(statement_schema)
    role_branches: list[dict[str, Any]] = []
    for role in (
        "LESSON",
        "SUPPORT",
        "COUNTERFACTUAL",
        "LIMITATION",
        "COUNTEREXAMPLE",
        "APPLICABILITY",
    ):
        grounded_branches: list[dict[str, Any]] = []
        evidence_fields = (
            ("source_statement_ids",)
            if role in {"LESSON", "SUPPORT"}
            else ("source_statement_ids", "source_decision_ids")
        )
        for evidence_field in evidence_fields:
            branch = deepcopy(base_statement_schema)
            branch["properties"]["role"]["enum"] = [role]
            branch["required"] = [*branch["required"], evidence_field]
            branch["properties"][evidence_field]["minItems"] = 1
            grounded_branches.append(branch)
        role_branches.extend(grounded_branches)

        # A map whose lesson or support is itself an evidence gap is not a
        # usable knowledge asset.  Keep explicit gaps for boundary roles, where
        # showing what the experience did not establish is the intended signal.
        if role not in {"LESSON", "SUPPORT"}:
            gap_branch = deepcopy(base_statement_schema)
            gap_branch["properties"]["role"]["enum"] = [role]
            gap_branch["required"] = [*gap_branch["required"], "gap_reason"]
            gap_branch["properties"]["gap_reason"] = {
                "type": "string",
                "minLength": 1,
                "maxLength": 240,
            }
            gap_branch["properties"]["source_statement_ids"]["maxItems"] = 0
            gap_branch["properties"]["source_decision_ids"]["maxItems"] = 0
            role_branches.append(gap_branch)
    statement_schema["anyOf"] = role_branches
    return schema


class M4WorkflowRunError(M4ContractError):
    def __init__(self, message: str, run_id: UUID) -> None:
        super().__init__(message)
        self.run_id = run_id


class M4ProductionGraph:
    def __init__(
        self,
        *,
        repository: SQLiteAssetRepository,
        service: M4MapService,
        model_client: ModelClient,
        runtime_policy: RuntimePolicy,
        code_commit: str = "UNCOMMITTED",
    ) -> None:
        self.repository, self.service, self.model_client = repository, service, model_client
        self.runtime_policy, self.code_commit = runtime_policy, code_commit
        self._compiled: Any | None = None
        self.compile_count = 0

    def compile(self, checkpointer: Any) -> None:
        graph = StateGraph(M4GraphState)
        operations = dict(
            (
                ("load_m4_context", self.load),
                ("plan_m4_insights", self.plan),
                ("validate_m4_output", self.validate),
                ("repair_m4_output", self.repair),
                ("evaluate_m4_tool_policy", self.policy),
                ("persist_m4_map", self.persist),
                ("verify_m4_map", self.verify),
                ("replan_m4_run", self.replan),
                ("terminalize_m4_run", self.terminalize),
            )
        )
        for name in M4_GRAPH_NODES:
            graph.add_node(name, self._traced_node(name, operations[name]))
        graph.add_edge(START, "load_m4_context")
        graph.add_conditional_edges(
            "load_m4_context",
            self._edge,
            {"ready": "plan_m4_insights", "stale_or_incompatible": "terminalize_m4_run"},
        )
        graph.add_conditional_edges(
            "plan_m4_insights",
            self._edge,
            {
                "proposal_ready": "validate_m4_output",
                "invalid_output": "repair_m4_output",
                "safe_failure": "terminalize_m4_run",
            },
        )
        graph.add_conditional_edges(
            "validate_m4_output",
            self._edge,
            {
                "valid": "evaluate_m4_tool_policy",
                "repairable": "repair_m4_output",
                "exhausted": "replan_m4_run",
            },
        )
        graph.add_conditional_edges(
            "repair_m4_output",
            self._edge,
            {
                "repaired": "validate_m4_output",
                "retry_repair": "repair_m4_output",
                "exhausted": "replan_m4_run",
                "safe_failure": "terminalize_m4_run",
            },
        )
        graph.add_conditional_edges(
            "evaluate_m4_tool_policy",
            self._edge,
            {"allow_or_no_tool": "persist_m4_map", "deny_or_invalid": "terminalize_m4_run"},
        )
        graph.add_conditional_edges(
            "persist_m4_map",
            self._edge,
            {"persisted": "verify_m4_map", "safe_failure": "replan_m4_run"},
        )
        graph.add_conditional_edges(
            "verify_m4_map",
            self._edge,
            {
                "verified": "terminalize_m4_run",
                "needs_replan": "replan_m4_run",
                "safe_failure": "terminalize_m4_run",
            },
        )
        graph.add_conditional_edges(
            "replan_m4_run",
            self._edge,
            {"replanned": "plan_m4_insights", "exhausted": "terminalize_m4_run"},
        )
        graph.add_edge("terminalize_m4_run", END)
        self._compiled = graph.compile(checkpointer=checkpointer)
        self.compile_count += 1

    async def run_new(
        self,
        *,
        asset_id: UUID,
        m3_id: UUID,
        version_id: UUID,
        expected_invalidated_artifact_id: UUID | None = None,
    ):
        self.service.validate_create(
            asset_id, m3_id, version_id,
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
                "E5-M4-map-regenerate-langgraph"
                if expected_invalidated_artifact_id
                else "E5-M4-map-langgraph"
            ),
            user_goal="Build an evidence-linked M4 insight and boundary map.",
            allow_current_source_search=False,
            workflow_version=M4_WORKFLOW_VERSION,
            topology_hash=M4_TOPOLOGY_HASH,
            model_id=model_id,
            model_config_hash=config_hash,
            server_base_url=base_url,
            code_commit=self.code_commit,
            started_at=datetime.now(UTC),
        )
        self.repository.configure_m4_run(
            run_id,
            regenerate=expected_invalidated_artifact_id is not None,
            expected_invalidated_artifact_id=expected_invalidated_artifact_id,
            base_m3_artifact_id=m3_id,
            context_bound=self.context_bound(),
        )
        initial = M4GraphStateV1(
            run_id=str(run_id),
            asset_id=str(asset_id),
            base_version_id=str(version_id),
            base_m3_artifact_id=str(m3_id),
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
            raise M4WorkflowRunError(
                terminal.safe_user_message if terminal else "M4 stopped safely", run_id
            )
        return self.service.get(asset_id)

    @staticmethod
    def context_bound() -> dict[str, Any]:
        """The bound placed on the model context, recorded before the first call.

        Carries the token budget and the method that counted it, not only the
        item ceilings. A recorded ceiling of "6 decisions" says nothing about
        whether the payload fit; the budget and the counting method are what a
        reader can check afterwards.
        """
        return {
            **describe_budget(resolve_counter(), M4_MAX_OUTPUT_TOKENS),
            "max_decisions": M4_MAX_CONTEXT_DECISIONS,
            "max_statements": M4_MAX_CONTEXT_STATEMENTS,
            "max_excerpt_chars": M4_MAX_EXCERPT_CHARS,
            "max_output_tokens": M4_MAX_OUTPUT_TOKENS,
            "timeout_seconds": M4_MODEL_TIMEOUT_SECONDS,
            "model_call_budget": M4_MODEL_CALL_BUDGET,
            "structured_repair_budget": M4_STRUCTURED_REPAIR_BUDGET,
            "replan_budget": M4_REPLAN_BUDGET,
        }

    async def load(self, state):
        validated = self._validated(state)
        context = self.repository.get_workflow_run_context(UUID(validated.run_id))
        if (
            not self._matches(context)
            or context["base_m3_artifact_id"] != validated.base_m3_artifact_id
        ):
            return self._failure(
                "load_m4_context",
                "stale_or_incompatible",
                "UPSTREAM_STALE",
                TerminalState.NEEDS_USER_INPUT,
            )
        self.service.validate_create(
            UUID(state["asset_id"]),
            UUID(state["base_m3_artifact_id"]),
            UUID(state["base_version_id"]),
            regenerate=validated.regenerate,
        )
        if validated.regenerate:
            self.service.validate_regenerate(
                UUID(validated.asset_id), UUID(validated.expected_invalidated_artifact_id)
            )
        return {"last_node": "load_m4_context", "selected_edge": "ready"}

    async def plan(self, state):
        return await self._generate_proposal(state)

    def _bounded_context(self, asset_id: UUID) -> tuple[dict[str, Any], list[SourceExcerpt]]:
        """Select the decisions and evidence sent to the model, deterministically.

        Selection is by ledger order rather than by any score: an ordering the
        user cannot see would make two runs over the same ledger disagree about
        which decision mattered, and the disagreement would surface as a
        different lesson with no visible cause.
        """
        m3 = self.repository.get_current_m3(asset_id)
        current = self.repository.get_current(asset_id)
        by_decision, _ = self.service.readable_identities(asset_id)
        available = list(m3.entries)[:M4_MAX_CONTEXT_DECISIONS]
        counter = resolve_counter()
        budget = prompt_budget_tokens(M4_MAX_OUTPUT_TOKENS)

        # Ceiling first, then the budget: take the longest prefix of the ledger
        # whose assembled payload still fits. The payload is measured rather
        # than predicted from decision text, because statements are deduplicated
        # across decisions and capped globally, so the cost of the sixth
        # decision is not the size of the sixth decision.
        context, excerpts = self._assemble(asset_id, m3, current, by_decision, available[:1])
        counted = self._payload_tokens(counter, context, excerpts)
        for size in range(2, len(available) + 1):
            wider, wider_excerpts = self._assemble(
                asset_id, m3, current, by_decision, available[:size]
            )
            wider_counted = self._payload_tokens(counter, wider, wider_excerpts)
            if wider_counted > budget:
                break
            context, excerpts, counted = wider, wider_excerpts, wider_counted

        # A single decision that does not fit is still sent: M4 cannot produce a
        # map from nothing, and dropping to zero would fail as a model-quality
        # problem. It is recorded as over budget so it reads as what it is.
        context["context_bound"]["prompt_tokens_counted"] = counted
        context["context_bound"]["within_budget"] = counted <= budget
        return context, excerpts

    @staticmethod
    def _payload_tokens(
        counter: Any, context: dict[str, Any], excerpts: list[SourceExcerpt]
    ) -> int:
        """Everything the request carries, counted the way the server will see it."""
        return (
            counter.count(M4_SYSTEM_POLICY)
            + counter.count(json.dumps(context, ensure_ascii=False, sort_keys=True))
            + sum(counter.count(excerpt.text) for excerpt in excerpts)
        )

    def _assemble(
        self,
        asset_id: UUID,
        m3: Any,
        current: Any,
        by_decision: dict[UUID, set[UUID]],
        entries: list[Any],
    ) -> tuple[dict[str, Any], list[SourceExcerpt]]:
        """Build the exact payload for a chosen set of decisions."""
        allowed_statement_ids: list[str] = []
        seen: set[UUID] = set()
        for entry in entries:
            for statement_id in sorted(by_decision.get(entry.decision_id, set()), key=str):
                if statement_id not in seen and len(seen) < M4_MAX_CONTEXT_STATEMENTS:
                    seen.add(statement_id)
                    allowed_statement_ids.append(str(statement_id))
        texts = {statement.statement_id: statement for statement in current.statements}
        excerpts = [
            SourceExcerpt(
                source_id=current.sources[0].source_id,
                span_id=f"statement:{statement_id}",
                text=texts[UUID(statement_id)].text[:M4_MAX_EXCERPT_CHARS],
            )
            for statement_id in allowed_statement_ids
            if UUID(statement_id) in texts
        ]
        context: dict[str, Any] = {
            "asset_id": str(asset_id),
            "version_id": str(current.version_id),
            "decision_ids": [str(entry.decision_id) for entry in entries],
            "decisions": [
                {
                    "decision_id": str(entry.decision_id),
                    "title": entry.title,
                    "statements": [
                        {
                            "statement_id": str(statement.statement_id),
                            "role": statement.role,
                            "text": statement.text[:M4_MAX_EXCERPT_CHARS],
                            "status": statement.status.value,
                        }
                        for statement in entry.statements
                    ],
                }
                for entry in entries
            ],
            "allowed_statement_ids": allowed_statement_ids,
            "context_bound": {
                **self.context_bound(),
                "decisions_supplied": len(entries),
                "decisions_available": len(m3.entries),
                "statements_supplied": len(allowed_statement_ids),
                "excerpts_supplied": len(excerpts),
            },
        }
        return context, excerpts

    async def _generate_proposal(
        self,
        state,
        *,
        repair_feedback: dict[str, Any] | None = None,
    ):
        validated = self._validated(state)
        if validated.model_call_count >= M4_MODEL_CALL_BUDGET:
            return self._failure(
                "plan_m4_insights",
                "safe_failure",
                "MODEL_CONTEXT_BUDGET_EXCEEDED",
                TerminalState.INVALID_MODEL_OUTPUT,
            )
        asset_id = UUID(state["asset_id"])
        context, excerpts = self._bounded_context(asset_id)
        if repair_feedback is not None:
            context["repair_feedback"] = repair_feedback
        invalidated = None
        if validated.regenerate:
            invalidated = self.repository.get_m4_artifact(
                UUID(validated.expected_invalidated_artifact_id)
            )
            self.service.validate_regenerate(UUID(validated.asset_id), invalidated.artifact_id)
            reusable = [
                entry
                for entry in invalidated.entries
                if entry.insight_id in invalidated.reusable_insight_ids
            ]
            context.update(
                expected_invalidated_artifact_id=str(invalidated.artifact_id),
                affected_insight_ids=[str(item) for item in invalidated.affected_insight_ids],
                reusable_insights=[entry.model_dump(mode="json") for entry in reusable],
            )
        repair_policy = ""
        if repair_feedback is not None:
            repair_policy = (
                " This is a correction request. The prior proposal failed deterministic "
                f"validation: {repair_feedback['validation_error']}. Return a complete "
                "replacement proposal. For every statement, either cite exact IDs from "
                "allowed_statement_ids belonging to the entry's declared decisions, or leave "
                "both reference arrays empty and give a non-empty gap_reason. Do not repeat "
                "the rejected evidence shape."
            )
        request = ModelRequest(
            run_id=UUID(state["run_id"]),
            stage=("E5-M4-map-repair" if repair_feedback is not None else "E5-M4-map"),
            system_policy=M4_SYSTEM_POLICY + repair_policy,
            canonical_context=context,
            source_excerpts=excerpts,
            output_schema=m4_local_model_output_schema(
                max_entry_decisions=max(1, len(context["decision_ids"])),
                allowed_decision_ids=context["decision_ids"],
                allowed_statement_ids=context["allowed_statement_ids"],
                required_prior_insight_id=(
                    context["affected_insight_ids"][0] if validated.regenerate else None
                ),
            ),
            max_output_tokens=M4_MAX_OUTPUT_TOKENS,
            timeout_seconds=M4_MODEL_TIMEOUT_SECONDS,
        )
        calls = validated.model_call_count
        try:
            result = await self._model_call(request, calls + 1)
            calls += 1
        except (ModelUnavailable, ModelTimedOut) as original_exc:
            exc: ModelUnavailable | ModelTimedOut | None = original_exc
            calls += 1
            # Exactly one transient retry; each actual invocation consumes budget.
            if validated.node_attempt == 0 and calls < M4_MODEL_CALL_BUDGET:
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
                    **self._failure("plan_m4_insights", "safe_failure", code, terminal),
                    "model_call_count": calls,
                    "node_attempt": 1,
                }
        except InvalidModelOutput:
            return {
                "last_node": "plan_m4_insights",
                "selected_edge": "invalid_output",
                "terminal_candidate": "",
                "finding_codes": ["INVALID_MODEL_OUTPUT"],
                "safe_message": "Structured output was invalid; attempting bounded repair.",
                "model_call_count": calls + 1,
            }
        proposal = result.proposal
        digest = hashlib.sha256(
            json.dumps(proposal.model_dump(mode="json"), sort_keys=True).encode()
        ).hexdigest()
        attempt = calls
        self.repository.save_m4_proposal(
            UUID(state["run_id"]),
            attempt,
            proposal,
            digest,
            result.metadata,
        )
        return {
            "last_node": "plan_m4_insights",
            "selected_edge": "proposal_ready",
            "structured_proposal_hash": digest,
            "model_call_count": attempt,
            "proposal_attempt": attempt,
            "node_attempt": 0,
        }

    async def validate(self, state):
        validated = self._validated(state)
        try:
            proposal, digest = self.repository.get_m4_proposal(
                UUID(validated.run_id), validated.proposal_attempt
            )
            if digest != validated.structured_proposal_hash:
                raise M4ContractError("proposal hash mismatch")
            previous = None
            if validated.regenerate:
                previous = self.repository.get_m4_artifact(
                    UUID(validated.expected_invalidated_artifact_id)
                )
                self.service.validate_regenerate(UUID(validated.asset_id), previous.artifact_id)
            self.service.validate_proposal(UUID(validated.asset_id), proposal, previous=previous)
        except (M4ContractError, AssetNotFoundError) as exc:
            if (
                validated.structured_repair_attempts < M4_STRUCTURED_REPAIR_BUDGET
                and validated.model_call_count < M4_MODEL_CALL_BUDGET
            ):
                return {
                    "last_node": "validate_m4_output",
                    "selected_edge": "repairable",
                    "finding_codes": [type(exc).__name__],
                }
            return {
                **self._failure(
                    "validate_m4_output",
                    "exhausted",
                    "STRUCTURED_REPAIR_EXHAUSTED",
                    TerminalState.INVALID_MODEL_OUTPUT,
                ),
                "structured_repair_attempts": validated.structured_repair_attempts,
            }
        return {"last_node": "validate_m4_output", "selected_edge": "valid", "finding_codes": []}

    def _build_repair_feedback(self, validated: M4GraphStateV1) -> dict[str, Any]:
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
            proposal, digest = self.repository.get_m4_proposal(
                UUID(validated.run_id), validated.proposal_attempt
            )
            if digest != validated.structured_proposal_hash:
                feedback["validation_error"] = "The prior proposal hash did not match."
                return feedback
            previous = None
            if validated.regenerate:
                previous = self.repository.get_m4_artifact(
                    UUID(validated.expected_invalidated_artifact_id)
                )
            self.service.validate_proposal(UUID(validated.asset_id), proposal, previous=previous)
        except (M4ContractError, AssetNotFoundError) as exc:
            feedback["validation_error"] = str(exc)
            if proposal is not None:
                feedback["rejected_proposal"] = proposal.model_dump(mode="json")
        return feedback

    async def repair(self, state):
        validated = self._validated(state)
        if (
            validated.structured_repair_attempts >= M4_STRUCTURED_REPAIR_BUDGET
            or validated.model_call_count >= M4_MODEL_CALL_BUDGET
        ):
            code = (
                "MODEL_CONTEXT_BUDGET_EXCEEDED"
                if validated.model_call_count >= M4_MODEL_CALL_BUDGET
                else "STRUCTURED_REPAIR_EXHAUSTED"
            )
            return self._failure(
                "repair_m4_output", "exhausted", code, TerminalState.INVALID_MODEL_OUTPUT
            )
        feedback = self._build_repair_feedback(validated)
        update = await self._generate_proposal(state, repair_feedback=feedback)
        update["last_node"] = "repair_m4_output"
        update["structured_repair_attempts"] = validated.structured_repair_attempts + 1
        if update.get("selected_edge") == "safe_failure":
            update["selected_edge"] = "safe_failure"
        elif update.get("structured_proposal_hash"):
            update["selected_edge"] = "repaired"
        elif (
            update.get("selected_edge") == "invalid_output"
            and validated.structured_repair_attempts + 1 < M4_STRUCTURED_REPAIR_BUDGET
        ):
            update["selected_edge"] = "retry_repair"
        else:
            update["selected_edge"] = "exhausted"
        return update

    async def replan(self, state):
        validated = self._validated(state)
        if (
            validated.replan_attempts >= M4_REPLAN_BUDGET
            or validated.model_call_count >= M4_MODEL_CALL_BUDGET
        ):
            code = (
                "MODEL_CONTEXT_BUDGET_EXCEEDED"
                if validated.model_call_count >= M4_MODEL_CALL_BUDGET
                else "REPLAN_EXHAUSTED"
            )
            return {
                **self._failure(
                    "replan_m4_run", "exhausted", code, TerminalState.INVALID_MODEL_OUTPUT
                ),
                "replan_attempts": validated.replan_attempts,
            }
        # Replan is deterministic and consumes no model call; the following plan is final.
        return {
            "last_node": "replan_m4_run",
            "selected_edge": "replanned",
            "replan_attempts": validated.replan_attempts + 1,
            "terminal_candidate": "",
            "safe_message": "",
            "node_attempt": 0,
        }

    async def policy(self, state):
        if state.get("terminal_candidate"):
            return {"last_node": "evaluate_m4_tool_policy", "selected_edge": "deny_or_invalid"}
        proposal, _ = self.repository.get_m4_proposal(
            UUID(state["run_id"]), state["proposal_attempt"]
        )
        decisions = []
        run_id = UUID(state["run_id"])
        for index, tool in enumerate(proposal.tool_call_proposals):
            proposal_id = uuid5(run_id, f"m4-tool:{state['proposal_attempt']}:{index}")
            runtime_proposal = RuntimeToolCallProposal(
                proposal_id=proposal_id,
                name=tool.name,
                arguments=tool.arguments,
                base_version_id=UUID(state["base_version_id"]),
                proposed_at=datetime.now(UTC),
                permission_granted=False,
            )
            # M4 runs before readiness exists, so the permission snapshot carries
            # no knowledge card and no relation: a cross-asset read here would
            # anchor an experience the user is still clarifying, and the anchoring
            # is invisible afterwards because the lesson reads as self-derived.
            run_state = SimpleNamespace(
                run_id=run_id,
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
            decision = self.repository.get_m4_policy_decision(
                run_id=run_id,
                proposal_attempt=state["proposal_attempt"],
                proposal_id=proposal_id,
            )
            if decision is None:
                decision = self.runtime_policy.evaluate(
                    state=run_state,
                    proposal=runtime_proposal,
                )
                self.repository.save_m4_policy_decision(
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
                "last_node": "evaluate_m4_tool_policy",
                "selected_edge": "deny_or_invalid",
                "policy_decision_id": str(decisions[0].decision_id),
                "terminal_candidate": "POLICY_BLOCKED",
                "finding_codes": reason_codes,
                "safe_message": "M4 tool proposal was denied with zero effects.",
                "retryable": False,
            }
        return {"last_node": "evaluate_m4_tool_policy", "selected_edge": "allow_or_no_tool"}

    async def persist(self, state):
        if state.get("terminal_candidate"):
            return {"last_node": "persist_m4_map", "selected_edge": "safe_failure"}
        run_id = UUID(state["run_id"])
        committed = self.repository.get_m4_run_commit(run_id)
        if committed is not None:
            existing, canonical = committed
            return {
                "last_node": "persist_m4_map",
                "selected_edge": "persisted",
                "artifact_id": str(existing.artifact_id),
                "canonical_version_id": str(canonical.version_id),
            }
        proposal, digest = self.repository.get_m4_proposal(
            UUID(state["run_id"]), state["proposal_attempt"]
        )
        if digest != state["structured_proposal_hash"]:
            raise M4ContractError("M4 proposal hash changed")
        artifact = self.service.create_for_run(
            UUID(state["asset_id"]),
            m3_id=UUID(state["base_m3_artifact_id"]),
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
            "last_node": "persist_m4_map",
            "selected_edge": "persisted",
            "artifact_id": str(artifact.artifact_id),
            "canonical_version_id": str(canonical.version_id),
        }

    async def verify(self, state):
        if state.get("terminal_candidate"):
            return {"last_node": "verify_m4_map", "selected_edge": "safe_failure"}
        committed = self.repository.get_m4_run_commit(UUID(state["run_id"]))
        if committed is None:
            raise M4ContractError("persisted M4 run commit is missing")
        artifact, canonical = committed
        if (str(artifact.artifact_id), str(canonical.version_id)) != (
            state["artifact_id"], state["canonical_version_id"]
        ):
            raise M4ContractError("persisted M4 run-owned identities mismatch")
        projection = next(
            (item for item in canonical.milestone_artifacts if item.milestone is Milestone.M4), None
        )
        if projection is None or projection.payload.get("m4_artifact_id") != state["artifact_id"]:
            raise M4ContractError("committed canonical M4 projection mismatch")
        return {
            "last_node": "verify_m4_map",
            "selected_edge": "verified",
            "terminal_candidate": "SUCCEEDED",
            "safe_message": "M4 insight map saved and verified.",
        }

    async def terminalize(self, state):
        terminal = TerminalState(state.get("terminal_candidate") or TerminalState.INTERNAL_ERROR)
        run_id = UUID(state["run_id"])
        current = self.repository.get_current(UUID(state["asset_id"]))
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
            recovery_action = "Retry explicit M4 regeneration after resolving the failure."
        else:
            recovery_action = "Retry M4 creation after resolving the failure."

        self.repository.update_m4_run_outcome(
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
                safe_user_message=state.get("safe_message") or "M4 stopped safely.",
                internal_error_class=None
                if terminal is TerminalState.SUCCEEDED
                else "M4WorkflowFailure",
                elapsed_ms=self._elapsed_ms(run_id),
                model_call_count=state.get("model_call_count", 0),
                recovery_action=recovery_action,
                finished_at=datetime.now(UTC),
            )
        )
        return {"last_node": "terminalize_m4_run", "selected_edge": "end"}

    async def recover_incomplete_runs(self):
        # Identity mismatch terminalizes instead of replaying an uncertain effect.
        for run_id in self.repository.list_incomplete_workflow_run_ids(M4_WORKFLOW_VERSION):
            context = self.repository.get_workflow_run_context(run_id)
            if not self._matches(context):
                current = self.repository.get_current(UUID(str(context["asset_id"])))
                self.repository.finish_run_idempotent(
                    TerminalResultV1(
                        run_id=run_id,
                        state=TerminalState.INTERNAL_ERROR,
                        last_durable_version_id=current.version_id,
                        retryable=False,
                        safe_user_message="M4 workflow identity changed; no effect was replayed.",
                        internal_error_class="WorkflowIdentityMismatch",
                        elapsed_ms=self._elapsed_ms(run_id),
                        model_call_count=self.repository.count_workflow_effects(
                            run_id, "m4_model_call"
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
                raise M4ContractError("missing M4 checkpoint")
            validate_m4_graph_state(snapshot.values)
            if snapshot.next:
                await self._compiled.ainvoke(None, self._config(run_id))
            elif self.repository.get_terminal_result(run_id) is None:
                raise M4ContractError("M4 graph ended without terminal result")
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
                safe_user_message="M4 stopped safely; the last durable version was preserved.",
                internal_error_class=error_class,
                elapsed_ms=self._elapsed_ms(run_id),
                model_call_count=self.repository.count_workflow_effects(run_id, "m4_model_call"),
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
        operation: M4NodeOperation,
    ) -> M4NodeOperation:
        async def traced(state: dict[str, Any]) -> dict[str, Any]:
            started = datetime.now(UTC)
            validated = self._validated(state)
            try:
                update = await operation(state)
            except BaseException as exc:
                self.repository.record_workflow_trace(
                    run_id=UUID(validated.run_id),
                    workflow_version=M4_WORKFLOW_VERSION,
                    topology_hash=M4_TOPOLOGY_HASH,
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
        validated: M4GraphStateV1,
        update: dict[str, Any],
        started: datetime,
    ) -> None:
        finding_codes = [str(code) for code in update.get("finding_codes") or []]
        denied = (
            node_name == "evaluate_m4_tool_policy"
            and update.get("selected_edge") == "deny_or_invalid"
        )
        self.repository.record_workflow_trace(
            run_id=UUID(validated.run_id),
            workflow_version=M4_WORKFLOW_VERSION,
            topology_hash=M4_TOPOLOGY_HASH,
            node_name=node_name,
            node_attempt=validated.node_attempt,
            selected_edge=str(update.get("selected_edge") or ""),
            input_refs=self._trace_input_refs(validated),
            output_refs=[
                ref
                for ref in (
                    f"artifact:{update['artifact_id']}" if update.get("artifact_id") else None,
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
                if node_name == "verify_m4_map" and update.get("selected_edge") == "verified"
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
    def _trace_input_refs(validated: M4GraphStateV1) -> list[str]:
        return [
            f"run:{validated.run_id}",
            f"asset:{validated.asset_id}",
            f"version:{validated.base_version_id}",
            f"m3:{validated.base_m3_artifact_id}",
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
            "safe_message": f"M4 stopped safely ({code}); no invalid map was saved.",
            "retryable": False,
        }

    def _validated(self, state):
        validated = validate_m4_graph_state(state)
        context = self.repository.get_workflow_run_context(UUID(validated.run_id))
        if (
            context["asset_id"] != validated.asset_id
            or context["base_version_id"] != validated.base_version_id
            or context["command_id"] != validated.command_id
            or context["base_m3_artifact_id"] != validated.base_m3_artifact_id
            or context["m4_regenerate"] != validated.regenerate
            or context["expected_invalidated_m4_artifact_id"]
            != validated.expected_invalidated_artifact_id
        ):
            raise M4ContractError("M4 cursor differs from durable run context")
        return validated

    async def _model_call(self, request: ModelRequest, attempt: int):
        """Reserve every invocation and replay only a durably cached outcome."""
        key = f"m4:model:{request.run_id}:{attempt}"
        status, cached = self.repository.claim_workflow_effect(
            effect_key=key,
            run_id=request.run_id,
            node_name="m4_model_call",
            node_attempt=attempt,
            started_at=datetime.now(UTC),
        )
        if status == "COMPLETED":
            return self._decode_model_outcome(cached)
        try:
            result = await self.model_client.generate_m4_map(request)
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
            from app.experience_asset.inference.models import M4MapResult

            return M4MapResult.model_validate(outcome["result"])
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
            hashlib.sha256(f"{model}|{url}|{M4_WORKFLOW_VERSION}".encode()).hexdigest(),
        )

    def _matches(self, context):
        model, url, digest = self._identity()
        return (
            context["workflow_version"] == M4_WORKFLOW_VERSION
            and context["topology_hash"] == M4_TOPOLOGY_HASH
            and context["model_id"] == model
            and context["server_base_url"] == url
            and context["model_config_hash"] == digest
            and context["code_commit"] == self.code_commit
        )
