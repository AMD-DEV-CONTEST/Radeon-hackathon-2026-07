from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import Any, Literal, TypedDict, cast

from langgraph.graph import END, START, StateGraph

from policyseal.agent.checkpoints import (
    CopilotCheckpointStore,
    CopilotThreadCheckpoint,
    CopilotTurnCheckpoint,
)
from policyseal.agent.schemas import ReviewIntent
from policyseal.agent.tools import (
    ReviewDecision,
    ReviewSnapshot,
    ReviewTools,
)
from policyseal.audit.chain import AuditChain
from policyseal.audit.models import AuditEventType
from policyseal.domain.enums import (
    Action,
    Channel,
    ContentCategory,
    Purpose,
    RecipientProfile,
)
from policyseal.domain.models import DisclosureContext


@dataclass(frozen=True, slots=True)
class ReviewCitation:
    location: str
    category: ContentCategory
    action: Action
    rule_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CopilotReply:
    thread_id: str
    task_id: str
    revision_id: str
    turn_number: int
    intent: ReviewIntent
    text: str
    citations: tuple[ReviewCitation, ...]
    simulation_id: str | None = None
    exception_draft_id: str | None = None
    model_dependent: bool = False


class _CopilotState(TypedDict, total=False):
    checkpoint: CopilotThreadCheckpoint
    message: str
    snapshot: ReviewSnapshot
    intent: ReviewIntent
    reply: CopilotReply


class ReviewCopilot:
    def __init__(
        self,
        tools: ReviewTools,
        *,
        checkpoints: CopilotCheckpointStore | None = None,
        audit_chain: AuditChain | None = None,
        policy_sha256: str | None = None,
    ) -> None:
        if (audit_chain is None) != (policy_sha256 is None):
            raise ValueError("Copilot audit chain and policy hash must be configured together")
        self.tools = tools
        self.checkpoints = checkpoints or CopilotCheckpointStore()
        self.audit_chain = audit_chain
        self.policy_sha256 = policy_sha256
        builder = StateGraph(_CopilotState)
        builder.add_node("load_task_context", self._load_context)
        builder.add_node("classify_controlled_intent", self._classify_intent)
        builder.add_node("explain_decision", self._explain)
        builder.add_node("simulate_what_if", self._simulate)
        builder.add_node("draft_exception", self._draft_exception)
        builder.add_node("save_redacted_checkpoint", self._save_checkpoint)
        builder.add_edge(START, "load_task_context")
        builder.add_edge("load_task_context", "classify_controlled_intent")
        builder.add_conditional_edges(
            "classify_controlled_intent",
            self._route_intent,
            {
                "explain_decision": "explain_decision",
                "simulate_what_if": "simulate_what_if",
                "draft_exception": "draft_exception",
            },
        )
        builder.add_edge("explain_decision", "save_redacted_checkpoint")
        builder.add_edge("simulate_what_if", "save_redacted_checkpoint")
        builder.add_edge("draft_exception", "save_redacted_checkpoint")
        builder.add_edge("save_redacted_checkpoint", END)
        self._graph: Any = builder.compile()

    def start_thread(
        self,
        task_id: str,
        revision_id: str,
        *,
        display_reference: str | None = None,
        thread_id: str | None = None,
    ) -> CopilotThreadCheckpoint:
        self.tools.snapshot(task_id, revision_id)
        return self.checkpoints.start(
            thread_id or f"copilot-{uuid.uuid4().hex}",
            task_id,
            revision_id,
            display_reference=display_reference,
        )

    def respond(self, thread_id: str, *, task_id: str, message: str) -> CopilotReply:
        if not message.strip() or len(message) > 1_000:
            raise ValueError("Copilot message must contain between 1 and 1000 characters")
        checkpoint = self.checkpoints.load(thread_id, task_id=task_id)
        result = cast(
            _CopilotState,
            self._graph.invoke({"checkpoint": checkpoint, "message": message}),
        )
        return result["reply"]

    def delete_task(self, task_id: str) -> None:
        self.tools.delete_task(task_id)
        self.checkpoints.delete_task(task_id)

    def _load_context(self, state: _CopilotState) -> dict[str, object]:
        checkpoint = state["checkpoint"]
        return {"snapshot": self.tools.snapshot(checkpoint.task_id, checkpoint.revision_id)}

    @staticmethod
    def _classify_intent(state: _CopilotState) -> dict[str, object]:
        message = state["message"].casefold()
        if "what if" in message or "what-if" in message:
            intent = ReviewIntent.SIMULATE
        elif "exception" in message or "ask the reviewer" in message:
            intent = ReviewIntent.DRAFT_EXCEPTION
        else:
            intent = ReviewIntent.EXPLAIN
        return {"intent": intent}

    @staticmethod
    def _route_intent(
        state: _CopilotState,
    ) -> Literal["explain_decision", "simulate_what_if", "draft_exception"]:
        if state["intent"] is ReviewIntent.SIMULATE:
            return "simulate_what_if"
        if state["intent"] is ReviewIntent.DRAFT_EXCEPTION:
            return "draft_exception"
        return "explain_decision"

    def _explain(self, state: _CopilotState) -> dict[str, object]:
        snapshot = state["snapshot"]
        decision = self._select_decision(snapshot.decisions, state["message"])
        checkpoint = state["checkpoint"]
        text = (
            f"{self._identity(checkpoint, snapshot)} "
            f"At {decision.location}, category {decision.category.value} has action "
            f"{decision.action.value}. {decision.reason} "
            f"Rules: {', '.join(decision.rule_ids)}. "
            f"Evidence: {', '.join(decision.evidence_ids)}."
        )
        return {
            "reply": self._reply(
                checkpoint,
                ReviewIntent.EXPLAIN,
                text,
                (decision,),
            )
        }

    def _simulate(self, state: _CopilotState) -> dict[str, object]:
        snapshot = state["snapshot"]
        checkpoint = state["checkpoint"]
        message = state["message"]
        target = self._select_decision(snapshot.decisions, message)
        decisions: tuple[ReviewDecision, ...]
        if "placeholder" in message.casefold():
            simulation_id = f"simulation-preview-{uuid.uuid4().hex}"
            decisions = (target,)
            context = snapshot.context
            status = snapshot.status.value
            detail = (
                "The safer placeholder is a simulation preview; it does not modify the formal "
                "revision. Applying it requires a new revision and another deterministic check."
            )
        else:
            proposed = self._proposed_context(snapshot.context, message)
            simulation = self.tools.simulate(snapshot.task_id, proposed)
            simulation_id = simulation.id
            decisions = simulation.decisions
            context = simulation.context
            status = simulation.status.value
            detail = (
                "This simulation does not modify the formal revision and cannot be exported. "
                "Confirming the change creates a new revision."
            )
        text = (
            f"{self._identity(checkpoint, snapshot)} Simulation preview: {detail} "
            f"Proposed context: {self._context(context)}. Result status: {status}. "
            f"Categories: {', '.join(self._unique(d.category.value for d in decisions))}. "
            f"Actions: {', '.join(self._unique(d.action.value for d in decisions))}. "
            f"Rules: {', '.join(self._unique(rule for d in decisions for rule in d.rule_ids))}. "
            "Evidence: "
            f"{', '.join(self._unique(item for d in decisions for item in d.evidence_ids))}."
        )
        return {
            "reply": self._reply(
                checkpoint,
                ReviewIntent.SIMULATE,
                text,
                decisions,
                simulation_id=simulation_id,
            )
        }

    def _draft_exception(self, state: _CopilotState) -> dict[str, object]:
        snapshot = state["snapshot"]
        checkpoint = state["checkpoint"]
        message = state["message"]
        decision = self._select_decision(snapshot.decisions, message)
        if decision.action is not Action.BLOCK and "EV-GEN-003" not in decision.evidence_ids:
            decision = replace(
                decision,
                evidence_ids=decision.evidence_ids + ("EV-GEN-003",),
            )
        draft = self.tools.create_exception_draft(snapshot, decision)
        lower = message.casefold()
        if decision.action is Action.BLOCK:
            detail = (
                "A Block cannot override policy. Change the channel and create a new revision "
                "before requesting review."
            )
        elif decision.category is ContentCategory.CREDENTIAL_SECRET:
            detail = (
                "This draft cannot unlock credential material; residual credential risk remains "
                "blocked."
            )
        elif decision.category is ContentCategory.BANK_PAYMENT:
            detail = "Payment access needs a new purpose and a separately evaluated revision."
        elif "row 7" in lower:
            detail = "The requested scope is row 7 and remains subject to policy approval."
        else:
            detail = "The requested scope remains subject to policy approval."
        text = (
            f"{self._identity(checkpoint, snapshot)} Exception draft: {detail} "
            f"It is bound to the exact revision, single use, and expiry controls. "
            "It remains local until a separate confirmed submission. "
            f"Location: {decision.location}; category: {decision.category.value}; action: "
            f"{decision.action.value}; rules: {', '.join(decision.rule_ids)}; evidence: "
            f"{', '.join(decision.evidence_ids)}."
        )
        return {
            "reply": self._reply(
                checkpoint,
                ReviewIntent.DRAFT_EXCEPTION,
                text,
                (decision,),
                exception_draft_id=draft.id,
            )
        }

    def _save_checkpoint(self, state: _CopilotState) -> dict[str, object]:
        checkpoint = state["checkpoint"]
        reply = state["reply"]
        self.checkpoints.append(
            checkpoint.thread_id,
            task_id=checkpoint.task_id,
            turn=CopilotTurnCheckpoint(
                turn_number=reply.turn_number,
                intent=reply.intent,
                response_text=reply.text,
                cited_locations=tuple(citation.location for citation in reply.citations),
                cited_rule_ids=self._unique(
                    rule for citation in reply.citations for rule in citation.rule_ids
                ),
                cited_evidence_ids=self._unique(
                    item for citation in reply.citations for item in citation.evidence_ids
                ),
            ),
        )
        if self.audit_chain is not None and self.policy_sha256 is not None:
            event = self.audit_chain.append(
                AuditEventType.COPILOT_USED,
                {
                    "intent": reply.intent.value,
                    "turn_count": reply.turn_number,
                    "rule_ids": self._unique(
                        rule for citation in reply.citations for rule in citation.rule_ids
                    ),
                    "evidence_ids": self._unique(
                        item for citation in reply.citations for item in citation.evidence_ids
                    ),
                },
                actor="system",
                task_id=reply.task_id,
                revision_id=reply.revision_id,
                policy_sha256=self.policy_sha256,
            )
            try:
                self.tools.repository.append_audit_event(event)
            except Exception:
                self.audit_chain._events.pop()  # noqa: SLF001
                raise
        return {}

    @staticmethod
    def _select_decision(
        decisions: tuple[ReviewDecision, ...],
        message: str,
    ) -> ReviewDecision:
        if not decisions:
            raise ValueError("evidence is insufficient because the revision has no decisions")
        lower = message.casefold()
        requested_category: ContentCategory | None = None
        if any(token in lower for token in ("bank", "account", "payment operations")):
            requested_category = ContentCategory.BANK_PAYMENT
        elif any(token in lower for token in ("hostname", "host ", "internal host")):
            requested_category = ContentCategory.INTERNAL_INFRASTRUCTURE
        elif any(token in lower for token in ("token", "credential", "password")):
            requested_category = ContentCategory.CREDENTIAL_SECRET
        elif any(token in lower for token in ("service level", "sla", "indemnity")):
            requested_category = ContentCategory.NONSTANDARD_OBLIGATION
        elif "score" in lower:
            requested_category = ContentCategory.SCORE_RANKING
        elif "approval comment" in lower:
            requested_category = ContentCategory.INTERNAL_OPINION_APPROVAL
        category_matches = tuple(
            decision for decision in decisions if decision.category is requested_category
        )
        if category_matches:
            return category_matches[0]
        if "row 7" in lower or "supplier b" in lower or "competitor" in lower:
            row_matches = tuple(
                decision
                for decision in decisions
                if decision.location.endswith("7")
                and decision.category is ContentCategory.SUPPLIER_IDENTITY
            )
            if row_matches:
                return row_matches[0]
        if "block" in lower or "whole task" in lower or "override" in lower:
            blocked = tuple(decision for decision in decisions if decision.action is Action.BLOCK)
            if blocked:
                return blocked[0]
        return decisions[0]

    @staticmethod
    def _proposed_context(base: DisclosureContext, message: str) -> DisclosureContext:
        lower = message.casefold()
        proposed = base
        if "annual financial audit" in lower:
            proposed = replace(proposed, purpose=Purpose.ANNUAL_FINANCIAL_AUDIT)
        if "personal email" in lower:
            proposed = replace(proposed, channel=Channel.PERSONAL_EMAIL)
        if "corporate email" in lower:
            proposed = replace(proposed, channel=Channel.CORPORATE_EMAIL)
        if "bidder a" in lower:
            proposed = replace(
                proposed,
                recipient=RecipientProfile.SUPPLIER_BIDDER_A,
                organization="supplier-a.example",
                recipient_id="bidder-a@corp.example",
                purpose=Purpose.SUPPLIER_BID_FEEDBACK,
                channel=Channel.CORPORATE_EMAIL,
            )
        return proposed

    @classmethod
    def _reply(
        cls,
        checkpoint: CopilotThreadCheckpoint,
        intent: ReviewIntent,
        text: str,
        decisions: tuple[ReviewDecision, ...],
        *,
        simulation_id: str | None = None,
        exception_draft_id: str | None = None,
    ) -> CopilotReply:
        return CopilotReply(
            thread_id=checkpoint.thread_id,
            task_id=checkpoint.task_id,
            revision_id=checkpoint.revision_id,
            turn_number=len(checkpoint.turns) + 1,
            intent=intent,
            text=text,
            citations=tuple(
                ReviewCitation(
                    decision.location,
                    decision.category,
                    decision.action,
                    decision.rule_ids,
                    decision.evidence_ids,
                )
                for decision in decisions
            ),
            simulation_id=simulation_id,
            exception_draft_id=exception_draft_id,
        )

    @staticmethod
    def _identity(
        checkpoint: CopilotThreadCheckpoint,
        snapshot: ReviewSnapshot,
    ) -> str:
        return (
            f"Reference {checkpoint.display_reference}; task {snapshot.task_id}; revision "
            f"{snapshot.revision_id}; context {ReviewCopilot._context(snapshot.context)}."
        )

    @staticmethod
    def _context(context: DisclosureContext) -> str:
        return (
            f"recipient={context.recipient.value}, organization={context.organization}, "
            f"purpose={context.purpose.value}, channel={context.channel.value}, "
            f"classification={context.classification.value}, policy={context.policy_version}"
        )

    @staticmethod
    def _unique(values: Iterable[str]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(values))


__all__ = ["CopilotReply", "ReviewCitation", "ReviewCopilot"]
