"""LangGraph case orchestrator with SQLite checkpoint recovery."""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import re
import sqlite3
import time
from datetime import date
from pathlib import Path
from typing import Any, Callable

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from app.agents.intake import assess_business_intake
from app.agents.liability import LiabilityAgent
from app.agents.model_adapter import (
    AgentModelAdapter,
    DeterministicAgentModelAdapter,
)
from app.agents.vehicle_nature import VehicleNatureAgent
from app.evidence.workspace import CaseWorkspace
from app.graph.verifier import CaseVerifier
from app.memory.context_builder import ContextBuilder
from app.memory.service import bootstrap_case_memory
from app.memory.store import CaseMemoryStore
from app.rag.retrieval import HybridLegalRetriever
from app.rights.approval import HumanApprovalManager
from app.rights.deadline import DeadlineCalculator
from app.rights.delivery_date import DeliveryDateExtractor
from app.rights.evidence_gap import EvidenceGapPlanner
from app.rights.review_draft import ReviewApplicationDraftGenerator
from app.rights.task_planner import RightsTaskPlanner
from app.rules.compensation import CompensationRegimeRouter
from app.rules.repository import RuleRepository
from app.rules.vehicle import VehicleNatureRuleGuard
from app.schemas.business import LiabilityResult
from app.schemas.business import VehicleNatureResult
from app.schemas.legal import LegalCitation
from app.schemas.memory import CaseCapsule
from app.schemas.orchestration import CaseState, NodeResult, NodeStatus, utc_now
from app.schemas.rights import DeliveryDateStatus
from app.schemas.rights import (
    ApprovalDecision,
    HumanApprovalState,
    ReviewApplicationDraft,
)
from app.schemas.verification import PolicyGateDecision

NODE_TIMEOUTS = {
    "intake_complete": 10,
    "evidence_ready": 10,
    "legal_retrieval": 60,
    "vehicle_nature": 30,
    "liability": 30,
    "rights_workflow": 30,
    "verifier": 30,
    "human_approval": 10,
    "missing_evidence": 10,
    "missing_delivery_date": 10,
    "deadline_disputed": 10,
    "legal_conflict": 10,
    "low_confidence": 10,
    "policy_blocked": 10,
    "approval_pending": 10,
    "changes_requested": 10,
    "node_failed": 10,
}

NODE_PROGRESS = {
    "intake_complete": 0.10,
    "evidence_ready": 0.20,
    "legal_retrieval": 0.35,
    "vehicle_nature": 0.50,
    "liability": 0.65,
    "rights_workflow": 0.78,
    "missing_evidence": 0.78,
    "missing_delivery_date": 0.82,
    "deadline_disputed": 0.82,
    "legal_conflict": 0.78,
    "low_confidence": 0.78,
    "node_failed": 0.78,
    "verifier": 0.90,
    "policy_blocked": 0.94,
    "approval_pending": 0.94,
    "changes_requested": 1.0,
    "human_approval": 1.0,
}


class SchemaNodeError(ValueError):
    pass


def _stable_hash(state: dict[str, Any]) -> str:
    excluded = {
        "node_results",
        "current_node",
        "progress",
        "route",
        "warnings",
        "errors",
    }
    payload = {key: value for key, value in state.items() if key not in excluded}
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class CaseOrchestrator:
    def __init__(
        self,
        *,
        workspace: CaseWorkspace,
        retriever: HybridLegalRetriever,
        checkpoint_path: Path | str = Path("data/checkpoints/orchestrator.sqlite3"),
        model_adapter: AgentModelAdapter | None = None,
    ):
        self.workspace = workspace
        self.retriever = retriever
        self.model_adapter = model_adapter or DeterministicAgentModelAdapter()
        self.vehicle_agent = VehicleNatureAgent(model_adapter=self.model_adapter)
        self.liability_agent = LiabilityAgent(model_adapter=self.model_adapter)
        self.rules = RuleRepository()
        self.delivery_extractor = DeliveryDateExtractor()
        self.deadline_calculator = DeadlineCalculator(rules=self.rules)
        self.task_planner = RightsTaskPlanner()
        self.gap_planner = EvidenceGapPlanner()
        self.draft_generator = ReviewApplicationDraftGenerator()
        self.vehicle_rule_guard = VehicleNatureRuleGuard(self.rules)
        self.compensation_router = CompensationRegimeRouter(self.rules)
        self.checkpoint_path = Path(checkpoint_path)
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        self._checkpoint_connection = sqlite3.connect(
            self.checkpoint_path, check_same_thread=False
        )
        self._checkpointer = SqliteSaver(self._checkpoint_connection)

    def close(self) -> None:
        self._checkpoint_connection.close()

    def compile(self, *, interrupt_after: list[str] | None = None):
        graph = StateGraph(CaseState)
        workers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
            "intake_complete": self._intake_complete,
            "evidence_ready": self._evidence_ready,
            "legal_retrieval": self._legal_retrieval,
            "vehicle_nature": self._vehicle_nature,
            "liability": self._liability,
            "rights_workflow": self._rights_workflow,
            "verifier": self._verifier,
            "human_approval": self._human_approval,
            "missing_evidence": lambda state: self._branch(state, "missing_evidence"),
            "missing_delivery_date": lambda state: self._branch(
                state, "missing_delivery_date"
            ),
            "deadline_disputed": lambda state: self._branch(
                state, "deadline_disputed"
            ),
            "legal_conflict": lambda state: self._branch(state, "legal_conflict"),
            "low_confidence": lambda state: self._branch(state, "low_confidence"),
            "policy_blocked": lambda state: self._branch(state, "policy_blocked"),
            "approval_pending": lambda state: self._branch(
                state, "approval_pending"
            ),
            "changes_requested": lambda state: self._branch(
                state, "changes_requested"
            ),
            "node_failed": lambda state: self._branch(state, "node_failed"),
        }
        for name, worker in workers.items():
            graph.add_node(name, self._wrapped_node(name, worker))
        graph.add_edge(START, "intake_complete")
        graph.add_edge("intake_complete", "evidence_ready")
        graph.add_conditional_edges(
            "evidence_ready",
            self._route,
            {
                "legal_retrieval": "legal_retrieval",
                "missing_evidence": "missing_evidence",
                "node_failed": "node_failed",
            },
        )
        graph.add_conditional_edges(
            "legal_retrieval",
            self._route,
            {
                "vehicle_nature": "vehicle_nature",
                "legal_conflict": "legal_conflict",
                "node_failed": "node_failed",
            },
        )
        graph.add_conditional_edges(
            "vehicle_nature",
            self._route,
            {
                "liability": "liability",
                "low_confidence": "low_confidence",
                "node_failed": "node_failed",
            },
        )
        graph.add_conditional_edges(
            "liability",
            self._route,
            {
                "rights_workflow": "rights_workflow",
                "missing_evidence": "missing_evidence",
                "node_failed": "node_failed",
            },
        )
        graph.add_conditional_edges(
            "rights_workflow",
            self._route,
            {
                "verifier": "verifier",
                "missing_delivery_date": "missing_delivery_date",
                "deadline_disputed": "deadline_disputed",
                "node_failed": "node_failed",
            },
        )
        for branch in (
            "missing_evidence",
            "missing_delivery_date",
            "deadline_disputed",
            "legal_conflict",
            "low_confidence",
            "node_failed",
        ):
            graph.add_edge(branch, "verifier")
        graph.add_conditional_edges(
            "verifier",
            self._route,
            {
                "policy_blocked": "policy_blocked",
                "approval_pending": "approval_pending",
            },
        )
        graph.add_edge("policy_blocked", "human_approval")
        graph.add_edge("approval_pending", "human_approval")
        graph.add_conditional_edges(
            "human_approval",
            self._approval_route,
            {"complete": END, "changes_requested": "changes_requested"},
        )
        graph.add_edge("changes_requested", END)
        return graph.compile(
            checkpointer=self._checkpointer,
            interrupt_after=interrupt_after,
        )

    def run(
        self,
        case_id: str,
        *,
        thread_id: str | None = None,
        interrupt_after: str | None = None,
        simulate_json_error_at: str | None = None,
        simulate_failure_at: str | None = None,
    ) -> dict[str, Any]:
        selected_thread = thread_id or case_id
        initial: CaseState = {
            "case_id": case_id,
            "thread_id": selected_thread,
            "current_node": "pending",
            "progress": 0.0,
            "route": "intake_complete",
            "approval_status": "pending",
            "document_status": "draft",
            "interrupt_after": interrupt_after,
            "simulate_json_error_at": simulate_json_error_at,
            "simulate_failure_at": simulate_failure_at,
            "node_results": {},
            "legal_queries": [],
            "legal_citations": [],
            "blocking_issues": [],
            "missing_evidence": [],
            "warnings": [],
            "errors": [],
        }
        graph = self.compile(
            interrupt_after=[interrupt_after] if interrupt_after else None
        )
        return graph.invoke(initial, {"configurable": {"thread_id": selected_thread}})

    def resume(
        self, thread_id: str, *, interrupt_after: str | None = None
    ) -> dict[str, Any]:
        graph = self.compile(
            interrupt_after=[interrupt_after] if interrupt_after else None
        )
        return graph.invoke(None, {"configurable": {"thread_id": thread_id}})

    def state(self, thread_id: str) -> dict[str, Any]:
        """Return the complete persisted CaseState for service/view-model use."""

        graph = self.compile()
        snapshot = graph.get_state({"configurable": {"thread_id": thread_id}})
        return dict(snapshot.values or {})

    def status(self, thread_id: str) -> dict[str, Any]:
        graph = self.compile()
        snapshot = graph.get_state({"configurable": {"thread_id": thread_id}})
        values = dict(snapshot.values or {})
        return {
            "thread_id": thread_id,
            "case_id": values.get("case_id"),
            "current_node": values.get("current_node", "unknown"),
            "progress": values.get("progress", 0.0),
            "next": list(snapshot.next),
            "approval_status": values.get("approval_status"),
            "document_status": values.get("document_status"),
            "errors": values.get("errors", []),
            "recoverable": bool(snapshot.next),
            "node_results": values.get("node_results", {}),
            "delivery_date_result": values.get("delivery_date_result", {}),
            "deadlines": values.get("deadlines", []),
            "rights_tasks": values.get("rights_tasks", []),
            "evidence_collection_plan": values.get(
                "evidence_collection_plan", []
            ),
            "review_application_draft": values.get(
                "review_application_draft", {}
            ),
            "policy_gate": values.get("policy_gate", {}),
            "approval_state": values.get("approval_state", {}),
        }

    def retry_failed(self, thread_id: str) -> dict[str, Any]:
        """Fork from the checkpoint immediately before the latest failed node."""

        graph = self.compile()
        config = {"configurable": {"thread_id": thread_id}}
        current = graph.get_state(config)
        values = dict(current.values or {})
        failures = [
            name
            for name, result in values.get("node_results", {}).items()
            if result.get("status") == NodeStatus.FAILED.value
        ]
        if not failures:
            raise ValueError("Workflow has no failed node to retry.")
        failed_node = failures[-1]
        candidate = next(
            (
                snapshot
                for snapshot in graph.get_state_history(config)
                if failed_node in snapshot.next
            ),
            None,
        )
        if candidate is None:
            raise ValueError(
                f"No recoverable checkpoint exists before {failed_node}."
            )
        retry_config = graph.update_state(
            candidate.config,
            {
                "simulate_failure_at": None,
                "simulate_json_error_at": None,
                "errors": [],
                "route": failed_node,
            },
        )
        return graph.invoke(None, retry_config)

    def decide_approval(
        self,
        thread_id: str,
        *,
        decision: str,
        approver: str,
        comments: str = "",
    ) -> dict[str, Any]:
        graph = self.compile()
        config = {"configurable": {"thread_id": thread_id}}
        snapshot = graph.get_state(config)
        values = dict(snapshot.values or {})
        if not values:
            raise KeyError(thread_id)
        draft = ReviewApplicationDraft.model_validate(
            values["review_application_draft"]
        )
        approval = HumanApprovalState.model_validate(values["approval_state"])
        selected = ApprovalDecision(decision)
        if selected is ApprovalDecision.APPROVED:
            gate = values.get("policy_gate", {})
            if gate.get("decision") == PolicyGateDecision.BLOCK.value:
                raise ValueError("Policy Gate is blocked; this document cannot be approved.")
            if not draft.submittable_after_approval:
                raise ValueError(
                    "Draft has blocking fields or not-submittable reasons and "
                    "cannot be approved."
                )
        if (
            approval.document_version != draft.document_version
            or approval.inputs_hash != draft.inputs_hash
        ):
            raise ValueError("Approval state does not match the current document.")
        audit_event_id = self.workspace.store(values["case_id"]).audit(
            values["case_id"],
            "human_approval_decided",
            {
                "decision": selected.value,
                "comments": comments,
                "document_id": draft.document_id,
                "document_version": draft.document_version,
                "inputs_hash": draft.inputs_hash,
                "thread_id": thread_id,
            },
            approver,
        )
        decided = HumanApprovalManager.decide(
            approval,
            decision=selected,
            approver=approver,
            comments=comments,
            audit_event_id=audit_event_id,
            document_version=draft.document_version,
            inputs_hash=draft.inputs_hash,
        )
        graph.update_state(
            config,
            {
                "approval_status": selected.value,
                "approval_state": decided.model_dump(mode="json"),
                "document_status": (
                    "approved_for_manual_submission"
                    if selected is ApprovalDecision.APPROVED
                    else "draft"
                ),
                "human_action_required": selected is not ApprovalDecision.APPROVED,
            },
        )
        return self.status(thread_id)

    @staticmethod
    def _route(state: CaseState) -> str:
        return state.get("route", "node_failed")

    @staticmethod
    def _approval_route(state: CaseState) -> str:
        return (
            "changes_requested"
            if state.get("approval_status") == "changes_requested"
            else "complete"
        )

    def _wrapped_node(
        self,
        name: str,
        worker: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> Callable[[CaseState], dict[str, Any]]:
        def run(state: CaseState) -> dict[str, Any]:
            state_dict: dict[str, Any] = dict(state)
            started = utc_now()
            inputs_hash = _stable_hash(state_dict)
            warnings: list[str] = []
            errors: list[str] = []
            outputs: dict[str, Any] = {}
            retry_count = 0
            status = NodeStatus.SUCCEEDED
            started_monotonic = time.perf_counter()
            for attempt in range(2):
                try:
                    if state_dict.get("simulate_failure_at") == name:
                        raise RuntimeError(
                            f"simulated dependency unavailable at {name}"
                        )
                    if (
                        attempt == 0
                        and state_dict.get("simulate_json_error_at") == name
                    ):
                        raise SchemaNodeError("simulated malformed JSON/schema output")
                    with concurrent.futures.ThreadPoolExecutor(
                        max_workers=1
                    ) as executor:
                        future = executor.submit(worker, state_dict)
                        outputs = future.result(timeout=NODE_TIMEOUTS[name])
                    if not isinstance(outputs, dict):
                        raise SchemaNodeError("node output must be an object")
                    json.dumps(outputs, ensure_ascii=False, default=str)
                    warnings.extend(outputs.pop("warnings", []))
                    errors.extend(outputs.pop("errors", []))
                    break
                except (
                    SchemaNodeError,
                    ValidationError,
                    json.JSONDecodeError,
                ) as exc:
                    if attempt == 0:
                        retry_count = 1
                        warnings.append(
                            f"schema output repaired and retried once: {exc}"
                        )
                        continue
                    status = NodeStatus.FAILED
                    errors.append(f"{type(exc).__name__}: {exc}")
                    outputs = {"route": "node_failed"}
                except concurrent.futures.TimeoutError:
                    status = NodeStatus.FAILED
                    errors.append(
                        f"TimeoutError: {name} exceeded {NODE_TIMEOUTS[name]}s"
                    )
                    outputs = {"route": "node_failed"}
                    break
                except Exception as exc:
                    status = NodeStatus.FAILED
                    errors.append(f"{type(exc).__name__}: {exc}")
                    outputs = {"route": "node_failed"}
                    break
            finished = utc_now()
            duration_ms = round((time.perf_counter() - started_monotonic) * 1000, 3)
            result = NodeResult(
                status=status,
                started_at=started,
                finished_at=finished,
                inputs_hash=inputs_hash,
                outputs=outputs,
                warnings=warnings,
                errors=errors,
                retry_count=retry_count,
                metrics={
                    "duration_ms": duration_ms,
                    "timeout_seconds": NODE_TIMEOUTS[name],
                },
            )
            node_results = dict(state_dict.get("node_results", {}))
            node_results[name] = result.model_dump(mode="json")
            combined_warnings = list(state_dict.get("warnings", [])) + warnings
            combined_errors = list(state_dict.get("errors", [])) + errors
            case_id = state_dict.get("case_id")
            if case_id:
                self.workspace.store(case_id).audit(
                    case_id,
                    "workflow_node_executed",
                    {
                        "node": name,
                        "inputs_hash": inputs_hash,
                        "result": status.value,
                        "duration_ms": duration_ms,
                        "retry_count": retry_count,
                        "warning_count": len(warnings),
                        "error_count": len(errors),
                        "related_ids": {
                            "thread_id": state_dict.get("thread_id"),
                        },
                    },
                    name,
                )
            return {
                **outputs,
                "current_node": name,
                "progress": NODE_PROGRESS[name],
                "node_results": node_results,
                "warnings": combined_warnings,
                "errors": combined_errors,
            }

        return run

    def _intake_complete(self, state: dict[str, Any]) -> dict[str, Any]:
        store = self.workspace.store(state["case_id"])
        exported = store.export_case(state["case_id"])
        assessment = assess_business_intake(
            store.list_sources(state["case_id"]),
            exported["facts"],
            evidence_nodes=exported["evidence_nodes"],
            conflicts=exported["conflicts"],
        )
        store.audit(
            state["case_id"],
            "business_intake_completed",
            {
                "uploaded_count": len(assessment.uploaded_materials),
                "blocking_issues": [
                    item.model_dump(mode="json") for item in assessment.blocking_issues
                ],
                "route_hint": assessment.route_hint,
            },
            "case_intake_agent",
        )
        return {
            "route": "evidence_ready",
            "intake_assessment": assessment.to_dict(),
            "blocking_issues": [
                item.model_dump(mode="json") for item in assessment.blocking_issues
            ],
            "missing_evidence": [
                item.model_dump(mode="json")
                for item in assessment.missing_required_materials
            ],
        }

    def _evidence_ready(self, state: dict[str, Any]) -> dict[str, Any]:
        store = self.workspace.store(state["case_id"])
        nodes = store.list_nodes(state["case_id"])
        facts = store.list_facts(state["case_id"])
        route = "legal_retrieval" if nodes and facts else "missing_evidence"
        return {
            "route": route,
            "evidence_summary": {
                "node_count": len(nodes),
                "fact_count": len(facts),
                "high_cost_parser_reexecuted": False,
            },
        }

    def _legal_retrieval(self, state: dict[str, Any]) -> dict[str, Any]:
        queries = state.get("legal_queries") or [
            "事故责任如何依据行为原因力和过错严重程度确定",
            "机动车与非机动车事故赔偿路径以及交强险商业险顺序",
            "事故认定复核期限和重新鉴定期限",
            "两轮电动车车辆属性国家标准与司法认定",
            "路口信号灯 标志标线 让行义务 逆行 横穿 观察 制动 原因力",
        ]
        citations: dict[str, LegalCitation] = {}
        for query in queries:
            for citation in self.retriever.citations(query, top_k=4, candidate_k=10):
                citations[citation.source_id] = citation
        required_articles = {
            ("CN-RULE-ACCIDENT-PROCEDURE-2017", "第五十六条"),
            ("CN-RULE-ACCIDENT-PROCEDURE-2017", "第七十一条"),
            ("CN-RULE-ACCIDENT-PROCEDURE-2017", "第七十四条"),
            ("CN-RULE-ACCIDENT-PROCEDURE-2017", "第一百一十二条"),
            ("CN-LAW-RTSA-2021", "第七十六条"),
            ("CN-LAW-CIVIL-CODE-2020", "第一千二百一十三条"),
            ("CN-REG-CALI-2019", "第二十一条"),
        }
        for chunk in self.retriever.corpus.list_chunks(
            as_of=_extract_accident_date(
                self.workspace.store(state["case_id"]).list_facts(state["case_id"])
            )
            or date.today()
        ):
            if (chunk.document_id, chunk.article_no) in required_articles:
                citation = LegalCitation.from_chunk(chunk, retrieval_score=1.0)
                citations[citation.source_id] = citation
        route = "vehicle_nature" if citations else "legal_conflict"
        return {
            "route": route,
            "legal_queries": list(queries),
            "legal_citations": [
                item.model_dump(mode="json") for item in citations.values()
            ],
        }

    def _memory_context(
        self,
        state: dict[str, Any],
        task: str,
        node_name: str,
        *,
        top_k_facts: int = 8,
        top_k_citations: int = 4,
    ) -> tuple[CaseMemoryStore, CaseCapsule, dict[str, Any]]:
        memory, capsule = bootstrap_case_memory(self.workspace, state["case_id"])
        store = self.workspace.store(state["case_id"])
        evidence_facts = store.list_facts(state["case_id"])
        citations = [
            LegalCitation.model_validate(item)
            for item in state.get("legal_citations", [])
        ]
        context = ContextBuilder(memory).build(
            task=task,
            capsule=capsule,
            facts=evidence_facts,
            citations=citations,
            node_name=node_name,
            top_k_facts=top_k_facts,
            top_k_citations=top_k_citations,
            workflow_state=state,
            full_history=store.list_audit_events(state["case_id"]),
        )
        return memory, capsule, context.model_dump(mode="json")

    def _vehicle_nature(self, state: dict[str, Any]) -> dict[str, Any]:
        memory, capsule, context = self._memory_context(
            state,
            "判断两轮车辆法律属性、登记与技术参数证据",
            "vehicle_nature",
            top_k_facts=10,
            top_k_citations=8,
        )
        store = self.workspace.store(state["case_id"])
        exported = store.export_case(state["case_id"])
        facts = _facts_with_memory_status(memory, context["facts"])
        citations = [
            LegalCitation.model_validate(item)
            for item in context["citations"]
        ]
        result = self.vehicle_agent.run(
            facts=facts,
            legal_citations=citations,
            conflicts=exported["conflicts"],
            accident_date=_extract_accident_date(exported["facts"]),
        )
        output = result.model_dump(mode="json")
        compact = {
            "classification": result.classification.value,
            "confidence": result.confidence,
            "conclusion_status": result.conclusion_status,
            "warning": result.warning,
        }
        updated = capsule.model_copy(
            update={
                "vehicle_classification": output,
                "missing_evidence": [item.reason for item in result.missing_evidence],
                "citations": citations[:8],
                "last_updated_by": "vehicle_nature",
                "version": capsule.version + 1,
            }
        )
        memory.save_capsule(updated)
        memory.append_event(
            "vehicle_nature_completed",
            "vehicle_nature_agent",
            {
                "classification": result.classification.value,
                "confidence": result.confidence,
                "conclusion_status": result.conclusion_status,
                "supporting_fact_ids": [
                    item.fact_id for item in result.supporting_facts
                ],
                "ruleset_id": self.vehicle_agent.rule_engine.ruleset_id,
            },
        )
        store.audit(
            state["case_id"],
            "vehicle_nature_completed",
            {
                "classification": result.classification.value,
                "confidence": result.confidence,
                "fact_ids": [
                    item.fact_id
                    for item in [
                        *result.supporting_facts,
                        *result.contradicting_facts,
                    ]
                ],
                "law_ids": [item.source_id for item in result.legal_basis],
            },
            "vehicle_nature_agent",
        )
        return {
            "route": "liability",
            "vehicle_classification": compact,
            "vehicle_nature_result": output,
            "parameter_comparison": [
                item.model_dump(mode="json") for item in result.parameter_comparison
            ],
            "missing_evidence": [
                item.model_dump(mode="json") for item in result.missing_evidence
            ],
            "case_capsule": updated.model_dump(mode="json"),
            "context_metrics": {
                "before_tokens": context["before_token_count"],
                "after_tokens": context["after_token_count"],
            },
            "protected_fields_valid": True,
        }

    def _liability(self, state: dict[str, Any]) -> dict[str, Any]:
        memory, capsule, context = self._memory_context(
            state,
            "分析信号、让行、逆行、观察、制动等违法行为、原因力、事故责任与赔偿路径",
            "liability",
            top_k_facts=16,
            top_k_citations=12,
        )
        store = self.workspace.store(state["case_id"])
        exported = store.export_case(state["case_id"])
        facts = _facts_with_memory_status(memory, context["facts"])
        citations = [
            LegalCitation.model_validate(item)
            for item in context["citations"]
        ]
        vehicle_result = VehicleNatureResult.model_validate(
            state["vehicle_nature_result"]
        )
        result = self.liability_agent.run(
            facts=facts,
            legal_citations=citations,
            vehicle_nature=vehicle_result,
            conflicts=exported["conflicts"],
        )
        hypotheses = [
            item.model_dump(mode="json") for item in result.liability_hypotheses
        ]
        updated = capsule.model_copy(
            update={
                "liability_hypotheses": hypotheses,
                "missing_evidence": [item.reason for item in result.missing_evidence],
                "last_updated_by": "liability",
                "version": capsule.version + 1,
            }
        )
        memory.save_capsule(updated)
        memory.append_event(
            "liability_completed",
            "liability_agent",
            {
                "responsibility_probabilities": (result.responsibility_probabilities),
                "compensation_regime": result.compensation_regime.value,
                "unique_conclusion_blocked": (
                    result.uncertainty.unique_conclusion_blocked
                ),
            },
        )
        store.audit(
            state["case_id"],
            "liability_completed",
            {
                "hypotheses": [
                    {
                        "id": item.hypothesis_id,
                        "probability": item.probability,
                    }
                    for item in result.liability_hypotheses
                ],
                "evidence_ids": sorted(
                    {
                        evidence_id
                        for item in result.key_evidence
                        for evidence_id in item.evidence_ids
                    }
                ),
                "law_ids": [item.source_id for item in result.legal_basis],
            },
            "liability_agent",
        )
        payload = result.model_dump(mode="json")
        return {
            "route": "rights_workflow",
            "branch_reason": (
                "missing_evidence"
                if result.uncertainty.unique_conclusion_blocked
                else state.get("branch_reason", "")
            ),
            "liability_hypotheses": hypotheses,
            "liability_result": payload,
            "violation_matrix": payload["violation_matrix"],
            "causation_matrix": payload["causation_matrix"],
            "responsibility_probabilities": (payload["responsibility_probabilities"]),
            "accident_responsibility": payload["accident_responsibility"],
            "civil_compensation_allocation": (payload["civil_compensation_allocation"]),
            "insurance_payment_estimate": (payload["insurance_payment_estimate"]),
            "counterfactual_analysis": payload["counterfactual_analysis"],
            "missing_evidence": payload["missing_evidence"],
            "case_capsule": updated.model_dump(mode="json"),
            "context_metrics": {
                "before_tokens": context["before_token_count"],
                "after_tokens": context["after_token_count"],
            },
            "protected_fields_valid": True,
        }

    def _rights_workflow(self, state: dict[str, Any]) -> dict[str, Any]:
        memory, capsule, context = self._memory_context(
            state,
            "识别复核与重新鉴定期限，形成待人工批准任务",
            "rights_workflow",
            top_k_facts=14,
            top_k_citations=10,
        )
        store = self.workspace.store(state["case_id"])
        exported = store.export_case(state["case_id"])
        facts = _facts_with_memory_status(memory, context["facts"])
        sources = exported["sources"]
        nodes = exported["evidence_nodes"]
        delivery = self.delivery_extractor.extract(
            facts=[
                item
                for item in facts
                if not any(
                    keyword in str(item.get("statement", ""))
                    for keyword in ("鉴定意见送达", "检验报告送达")
                )
            ],
            evidence_nodes=nodes,
            sources=sources,
        )
        appraisal_delivery = self.delivery_extractor.extract(
            facts=[
                item
                for item in facts
                if any(
                    keyword in str(item.get("statement", ""))
                    for keyword in ("鉴定意见送达", "检验报告送达")
                )
            ],
            evidence_nodes=nodes,
            sources=sources,
        )
        citations = [
            LegalCitation.model_validate(item)
            for item in context["citations"]
        ]
        review_deadline = self.deadline_calculator.calculate(
            delivery=delivery,
            matter_type="accident_determination_review",
            rule_id="RULE-CN-DEADLINE-ACCIDENT-REVIEW-2017",
            legal_citations=citations,
        )
        deadlines = [review_deadline]
        if appraisal_delivery.status is not DeliveryDateStatus.MISSING:
            deadlines.append(
                self.deadline_calculator.calculate(
                    delivery=appraisal_delivery,
                    matter_type="appraisal_objection",
                    rule_id="RULE-CN-DEADLINE-APPRAISAL-OBJECTION-2017",
                    legal_citations=citations,
                )
            )
        vehicle_result = VehicleNatureResult.model_validate(
            state["vehicle_nature_result"]
        )
        liability_result = LiabilityResult.model_validate(state["liability_result"])
        vehicle_rule_assessment = self.vehicle_rule_guard.assess(vehicle_result)
        accident_date = _extract_accident_date(exported["facts"]) or date.today()
        compensation_route = self.compensation_router.route(
            vehicle_nature=vehicle_result,
            liability=liability_result,
            policy_and_loss_data={},
            as_of_date=accident_date,
            legal_citations=citations,
        )
        missing = [
            *state.get("missing_evidence", []),
            *[
                item.model_dump(mode="json")
                for item in vehicle_result.missing_evidence
            ],
            *[
                item.model_dump(mode="json")
                for item in liability_result.missing_evidence
            ],
        ]
        legal_issues: list[str] = []
        if self.rules.conflicts(as_of_date=accident_date):
            legal_issues.append("版本化规则存在冲突，需人工选择适用规则。")
        tasks = self.task_planner.plan(
            missing_evidence=missing,
            vehicle_result=vehicle_result,
            liability_result=liability_result,
            deadlines=deadlines,
            conflicts=exported["conflicts"],
            legal_issues=legal_issues,
        )
        gaps = self.gap_planner.plan(
            gaps=missing,
            deadlines=deadlines,
            counterfactuals=state.get("counterfactual_analysis", []),
        )
        draft = self.draft_generator.generate(
            case_id=state["case_id"],
            facts=facts,
            legal_citations=citations,
            delivery=delivery,
            applicant={},
            challenged_document={},
            missing_evidence=missing,
        )
        approval = HumanApprovalManager.pending_for(draft)
        updated = capsule.model_copy(
            update={
                "rights_deadlines": [
                    item.model_dump(mode="json") for item in deadlines
                ],
                "next_actions": [item.model_dump(mode="json") for item in tasks],
                "last_updated_by": "rights_workflow",
                "version": capsule.version + 1,
            }
        )
        memory.save_capsule(updated)
        store.audit(
            state["case_id"],
            "rights_workflow_completed",
            {
                "delivery_date_status": delivery.status.value,
                "deadline_ids": [item.deadline_id for item in deadlines],
                "task_ids": [item.task_id for item in tasks],
                "draft_id": draft.document_id,
                "document_version": draft.document_version,
                "inputs_hash": draft.inputs_hash,
            },
            "rights_workflow_agent",
        )
        route = "verifier"
        if delivery.status in {
            DeliveryDateStatus.MISSING,
            DeliveryDateStatus.WEAK_EVIDENCE,
        }:
            route = "missing_delivery_date"
        elif review_deadline.status.value == "disputed":
            route = "deadline_disputed"
        return {
            "route": route,
            "delivery_date_result": delivery.model_dump(mode="json"),
            "appraisal_delivery_date_result": appraisal_delivery.model_dump(
                mode="json"
            ),
            "deadlines": [item.model_dump(mode="json") for item in deadlines],
            "rights_tasks": [item.model_dump(mode="json") for item in tasks],
            "evidence_collection_plan": [
                item.model_dump(mode="json") for item in gaps
            ],
            "review_application_draft": draft.model_dump(mode="json"),
            "approval_state": approval.model_dump(mode="json"),
            "vehicle_rule_assessment": vehicle_rule_assessment,
            "compensation_route_result": compensation_route.model_dump(mode="json"),
            "civil_compensation_allocation": (
                compensation_route.civil_compensation_allocation
            ),
            "insurance_payment_estimate": (
                compensation_route.insurance_payment_estimate
            ),
            "case_capsule": updated.model_dump(mode="json"),
            "document_status": "draft",
            "approval_status": "pending",
            "context_metrics": {
                "before_tokens": context["before_token_count"],
                "after_tokens": context["after_token_count"],
            },
            "protected_fields_valid": True,
        }

    def _verifier(self, state: dict[str, Any]) -> dict[str, Any]:
        facts = self.workspace.store(state["case_id"]).list_facts(state["case_id"])
        verifier = CaseVerifier(
            self.workspace,
            self.retriever.corpus,
            as_of=_extract_accident_date(facts) or date.today(),
            rules=self.rules,
        )
        result = verifier.verify(state)
        gate = result["policy_gate"]
        risk_matches = result.get("components", {}).get("risk_language", {}).get(
            "matches", []
        )
        audit_event_id = self.workspace.store(state["case_id"]).audit(
            state["case_id"],
            "policy_gate_evaluated",
            {
                "decision": gate["decision"],
                "blocking_issue_count": len(gate["blocking_issues"]),
                "warning_count": len(gate["warnings"]),
                "risk_language_matches": [
                    {
                        "pattern_id": item.get("pattern_id"),
                        "action": item.get("action"),
                        "path": item.get("path"),
                    }
                    for item in risk_matches
                ],
                "required_actions": gate["required_actions"],
            },
            "verifier",
        )
        gate["audit_event_ids"] = sorted(
            set([*gate.get("audit_event_ids", []), audit_event_id])
        )
        result["policy_gate"] = gate
        return {
            "route": (
                "policy_blocked"
                if gate["decision"] == PolicyGateDecision.BLOCK.value
                else "approval_pending"
            ),
            "verifier_results": result,
            "policy_gate": gate,
            "document_status": "draft",
        }

    @staticmethod
    def _human_approval(state: dict[str, Any]) -> dict[str, Any]:
        return {
            "route": "complete",
            "approval_status": state.get("approval_status", "pending"),
            "document_status": "draft",
            "human_action_required": True,
            "approval_state": state.get("approval_state", {}),
        }

    @staticmethod
    def _branch(state: dict[str, Any], reason: str) -> dict[str, Any]:
        warning = {
            "missing_evidence": "证据不足，责任结论保持不确定并转人工补件。",
            "missing_delivery_date": "送达日期缺失或仅有弱证据，期限不得自动起算。",
            "deadline_disputed": "期限触发日期、规则或日历存在争议，需法律复核。",
            "legal_conflict": "法律引用缺失或冲突，禁止确定性法律结论。",
            "low_confidence": "车辆属性置信度过低，转人工核验。",
            "policy_blocked": "Policy Gate已阻断，外部提交不可用。",
            "approval_pending": "Policy Gate完成，等待人工审批，文书仍为draft。",
            "changes_requested": "审批人要求修改，原审批失效并返回pending。",
            "node_failed": "节点明确失败，可从最近成功检查点恢复。",
        }[reason]
        route = "human_approval" if reason in {
            "policy_blocked",
            "approval_pending",
        } else "verifier"
        return {
            "route": route,
            "branch_reason": state.get("branch_reason", "") or reason,
            "rights_branch_reason": (
                reason
                if reason in {"missing_delivery_date", "deadline_disputed"}
                else state.get("rights_branch_reason", "")
            ),
            "warnings": [warning],
            "document_status": "draft",
        }


def _extract_accident_date(facts: list[dict[str, Any]]) -> date | None:
    for fact in facts:
        text = " ".join(
            str(fact.get(key, "")) for key in ("statement", "predicate", "value")
        )
        if not any(keyword in text for keyword in ("事故日期", "事故时间", "事发时间")):
            continue
        match = re.search(r"(\d{4})[-年/](\d{1,2})[-月/](\d{1,2})日?", text)
        if match:
            try:
                return date(
                    int(match.group(1)),
                    int(match.group(2)),
                    int(match.group(3)),
                )
            except ValueError:
                continue
    return None


def _facts_with_memory_status(
    memory: CaseMemoryStore, facts: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Project append-only Fact Memory status into the shared fact payload."""

    projected = []
    for fact in facts:
        item = dict(fact)
        try:
            item["status"] = memory.fact_status(str(fact["fact_id"])).value
        except KeyError:
            # bootstrap_case_memory registers all current Evidence Graph facts;
            # this fallback remains fail-soft for a concurrent evidence append.
            item["status"] = str(fact.get("status", "unverified"))
        projected.append(item)
    return projected
