"""LangGraph orchestration for the local BuildGuard agent."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from buildguard.agent.nodes.executor import Tool, execute_tools
from buildguard.agent.nodes.inspection_analysis import analyze_inspection, build_risk_plan
from buildguard.agent.nodes.intent import classify_intent
from buildguard.agent.nodes.memory import retrieve_memory
from buildguard.agent.nodes.memory_save import save_memory
from buildguard.agent.nodes.permission import check_permission
from buildguard.agent.nodes.planner import generate_plan
from buildguard.agent.nodes.replan import replan
from buildguard.agent.nodes.response import (
    generate_response,
    safe_failure,
    wait_for_confirmation,
)
from buildguard.agent.nodes.verifier import verify_result
from buildguard.agent.state import AgentState, InspectionAnalysisDecision, IntentResult
from buildguard.config import AgentConfig
from buildguard.llm.base import LocalLLMBackend
from buildguard.llm.token_metrics import TokenMetrics
from buildguard.rag.advanced.answer_grounding import AnswerGrounder, GroundingResult
from buildguard.rag.schemas import DocumentChunk
from buildguard.schemas.agent import AgentMessage, TaskPlan
from buildguard.schemas.rag import RetrievedEvidence
from buildguard.schemas.tools import ToolCallResult
from buildguard.schemas.vision import InspectionResult, RiskAssessment
from buildguard.storage.memory import LongTermMemory
from buildguard.vision.routing.schemas import RoutingDecision
from buildguard.vision.schemas import EvidenceRecord


def _echo(arguments: dict[str, Any]) -> dict[str, Any]:
    return {"text": str(arguments.get("text", ""))}


def _inspect(arguments: dict[str, Any]) -> dict[str, Any]:
    return {"status": "mock-inspection", "source": str(arguments.get("text", ""))}


def _search(arguments: dict[str, Any]) -> dict[str, Any]:
    return {"matches": [], "query": str(arguments.get("text", ""))}


class BuildGuardAgent:
    """Reusable graph runner with bounded in-process session/task state."""

    def __init__(
        self,
        backend: LocalLLMBackend,
        config: AgentConfig,
        tools: dict[str, Tool] | None = None,
        memory: LongTermMemory | None = None,
        answer_grounder: AnswerGrounder | None = None,
    ) -> None:
        self.backend = backend
        self.config = config
        self.tools = tools or {
            "echo": _echo,
            "inspect_image": _inspect,
            "search_memory": _search,
        }
        missing = set(config.registered_tools) - set(self.tools)
        if missing:
            raise ValueError(f"Registered tools lack implementations: {sorted(missing)}")
        self.memories: dict[str, list[AgentMessage]] = {}
        self.tasks: dict[str, AgentState] = {}
        self.memory = memory
        self.answer_grounder = answer_grounder
        self.graph = self._build_graph()

    def _build_graph(self) -> Any:
        graph = StateGraph(AgentState)
        graph.add_node("intent_classify", self._classify_intent)
        graph.add_node("memory_retrieve", lambda state: retrieve_memory(state, self.memories))
        graph.add_node(
            "plan_generate",
            self._generate_plan,
        )
        graph.add_node("permission_check", lambda state: check_permission(state, self.config))
        graph.add_node("tool_execute", lambda state: execute_tools(state, self.tools))
        graph.add_node("inspection_analyze", self._analyze_inspection)
        graph.add_node("risk_plan", build_risk_plan)
        graph.add_node("result_verify", self._verify_result)
        graph.add_node("replan", self._replan)
        graph.add_node("response_generate", self._generate_response)
        graph.add_node("memory_save", lambda state: save_memory(state, self.memories))
        graph.add_node("safe_failure", safe_failure)
        graph.add_node("wait_for_confirmation", wait_for_confirmation)
        graph.add_edge(START, "intent_classify")
        graph.add_conditional_edges(
            "intent_classify",
            lambda state: "fail" if state["status"] == "safe_failure" else "continue",
            {"continue": "memory_retrieve", "fail": "safe_failure"},
        )
        graph.add_edge("memory_retrieve", "plan_generate")
        graph.add_edge("plan_generate", "permission_check")
        graph.add_conditional_edges(
            "permission_check",
            self._after_permission,
            {
                "execute": "tool_execute",
                "wait": "wait_for_confirmation",
                "fail": "safe_failure",
            },
        )
        graph.add_conditional_edges(
            "tool_execute",
            self._after_tool_execute,
            {
                "analyze": "inspection_analyze",
                "risk": "risk_plan",
                "verify": "result_verify",
            },
        )
        graph.add_edge("inspection_analyze", "permission_check")
        graph.add_edge("risk_plan", "permission_check")
        graph.add_conditional_edges(
            "result_verify",
            self._after_verify,
            {"respond": "response_generate", "replan": "replan", "fail": "safe_failure"},
        )
        graph.add_edge("replan", "permission_check")
        graph.add_edge("response_generate", "memory_save")
        graph.add_edge("safe_failure", "memory_save")
        graph.add_edge("wait_for_confirmation", END)
        graph.add_edge("memory_save", END)
        return graph.compile()

    def _classify_intent(self, state: AgentState) -> dict[str, object]:
        try:
            return classify_intent(state, self.backend)
        except Exception as exc:
            return {
                "errors": [f"Intent classification failed safely: {exc}"],
                "status": "safe_failure",
            }

    def _generate_plan(self, state: AgentState) -> dict[str, object]:
        try:
            metadata = getattr(self.tools, "planner_metadata", None)
            return generate_plan(
                state,
                self.backend,
                self.config,
                tool_metadata=metadata() if callable(metadata) else None,
            )
        except Exception as exc:
            return {"plan": None, "errors": [str(exc)], "status": "safe_failure"}

    def _replan(self, state: AgentState) -> dict[str, object]:
        try:
            metadata = getattr(self.tools, "planner_metadata", None)
            return replan(
                state,
                self.backend,
                self.config,
                tool_metadata=metadata() if callable(metadata) else None,
            )
        except Exception as exc:
            return {
                "errors": [*state["errors"], str(exc)],
                "retry_count": state["retry_count"] + 1,
                "status": "safe_failure",
            }

    def _verify_result(self, state: AgentState) -> dict[str, object]:
        try:
            return verify_result(state, self.backend)
        except Exception as exc:
            return {
                "errors": [*state["errors"], f"Result verification failed safely: {exc}"],
                "status": "safe_failure",
            }

    def _analyze_inspection(self, state: AgentState) -> dict[str, object]:
        try:
            return analyze_inspection(state, self.backend)
        except Exception as exc:
            return {
                "errors": [
                    *state["errors"],
                    f"Post-inspection analysis failed safely: {exc}",
                ],
                "status": "safe_failure",
            }

    def _generate_response(self, state: AgentState) -> dict[str, object]:
        try:
            return generate_response(state, self.backend, self.answer_grounder)
        except Exception as exc:
            return {
                "errors": [*state["errors"], f"Response generation failed safely: {exc}"],
                "final_response": f"Safe failure: response generation failed: {exc}",
                "status": "safe_failure",
            }

    @staticmethod
    def _after_permission(state: AgentState) -> str:
        if state["status"] == "WAIT_FOR_CONFIRMATION":
            return "wait"
        if state["status"] == "safe_failure":
            return "fail"
        return "execute"

    def _after_verify(self, state: AgentState) -> str:
        if state["status"] == "verified":
            return "respond"
        if (
            state["status"] == "recoverable_error"
            and state["retry_count"] < self.config.max_replans
        ):
            return "replan"
        return "fail"

    @staticmethod
    def _after_tool_execute(state: AgentState) -> str:
        plan = state["plan"]
        current_count = len(plan.steps) if plan is not None else 0
        current = state["tool_results"][-current_count:] if current_count else []
        if not current or any(not item.success for item in current):
            return "verify"
        if state["plan_phase"] == "visual":
            return "analyze"
        if state["plan_phase"] == "inspection_enrichment":
            return "risk"
        return "verify"

    def chat(
        self,
        user_query: str,
        session_id: str | None = None,
        *,
        task_id: str | None = None,
        requested_action: str | None = None,
        image_paths: list[Path] | None = None,
    ) -> AgentState:
        resolved_session_id = session_id or str(uuid4())
        resolved_task_id = task_id or str(uuid4())
        if self.memory is not None:
            self.memory.ensure_session(
                resolved_session_id,
                self.memory.title_from_message(user_query, resolved_session_id),
            )
            self.memories[resolved_session_id] = [
                AgentMessage(
                    id=item["id"],
                    created_at=item["created_at"],
                    session_id=resolved_session_id,
                    role=item["role"],
                    content=item["content"],
                    metadata={
                        key: value
                        for key, value in item["metadata"].items()
                        if isinstance(value, (str, int, float, bool))
                    },
                )
                for item in self.memory.list_messages(resolved_session_id)
            ]
            stored = self.memory.create_task(
                resolved_session_id,
                "Agent 对话任务",
                user_query,
                task_id=resolved_task_id,
                status="running",
            )
            resolved_task_id = stored.id
        state: AgentState = {
            "session_id": resolved_session_id,
            "task_id": resolved_task_id,
            "user_query": user_query,
            "requested_action": requested_action,
            "action": requested_action or ("inspect" if image_paths else "auto"),
            "image_paths": [Path(item).resolve() for item in (image_paths or [])],
            "intent": None,
            "inspection_analysis": None,
            "plan": None,
            "plan_phase": "general",
            "current_step": 0,
            "retry_count": 0,
            "tool_results": [],
            "inspection_results": [],
            "retrieved_evidence": [],
            "retrieved_chunks": [],
            "visual_evidence": [],
            "routing_decisions": [],
            "evidence_status": "not_requested",
            "tool_chain": [],
            "new_inference_count": 0,
            "reused_inspection_count": 0,
            "max_risk": "low",
            "grounding_result": None,
            "risk_results": [],
            "pending_confirmation": None,
            # Supplying bounded uploaded paths in the same inspection request is
            # explicit authorization for those read/visualization operations only.
            "confirmation_granted": bool(image_paths),
            "confirmation_denied": False,
            "errors": [],
            "final_response": None,
            "report_path": None,
            "performance_trace": [],
            "memory_messages": [],
            "status": "pending",
        }
        result = cast(AgentState, self.graph.invoke(state))
        result["new_inference_count"] = len(result["inspection_results"])
        result["max_risk"] = self._max_risk(result["risk_results"])
        self.tasks[result["task_id"]] = result
        self._persist_state(result, include_user=True)
        return result

    def confirm(self, task_id: str, approved: bool) -> AgentState:
        if task_id not in self.tasks:
            restored = self._restore_state(task_id)
            if restored is None:
                raise KeyError(f"Task not found: {task_id}")
            self.tasks[task_id] = restored
        previous = self.tasks[task_id]
        if previous["status"] != "WAIT_FOR_CONFIRMATION":
            raise ValueError("Task is not waiting for confirmation")
        resumed = dict(previous)
        resumed["confirmation_granted"] = approved
        resumed["confirmation_denied"] = not approved
        resumed["pending_confirmation"] = None
        update = check_permission(resumed, self.config)  # type: ignore[arg-type]
        resumed.update(update)
        if resumed["status"] == "running":
            resumed.update(execute_tools(resumed, self.tools))  # type: ignore[arg-type]
            # A confirmed visual batch must rejoin the same post-vision Agent
            # stages as a non-confirmed single-image request.
            while resumed.get("status") == "running":
                route = self._after_tool_execute(cast(AgentState, resumed))
                if route == "analyze":
                    resumed.update(self._analyze_inspection(cast(AgentState, resumed)))
                elif route == "risk":
                    resumed.update(build_risk_plan(cast(AgentState, resumed)))
                else:
                    break
                resumed.update(
                    check_permission(resumed, self.config)  # type: ignore[arg-type]
                )
                if resumed.get("status") != "running":
                    break
                resumed.update(execute_tools(resumed, self.tools))  # type: ignore[arg-type]
            if resumed.get("status") != "running":
                resumed.update(safe_failure(resumed))  # type: ignore[arg-type]
                resumed.update(save_memory(resumed, self.memories))  # type: ignore[arg-type]
                early_result = cast(AgentState, resumed)
                self.tasks[task_id] = early_result
                self._persist_state(early_result, include_user=False)
                return early_result
            verification_update = verify_result(
                resumed,  # type: ignore[arg-type]
                self.backend,
            )
            resumed.update(verification_update)
            if verification_update.get("status") == "verified":
                resumed.update(
                    generate_response(
                        cast(AgentState, resumed),
                        self.backend,
                        self.answer_grounder,
                    )
                )
            else:
                resumed.update(safe_failure(resumed))  # type: ignore[arg-type]
        else:
            resumed.update(safe_failure(resumed))  # type: ignore[arg-type]
        resumed.update(save_memory(resumed, self.memories))  # type: ignore[arg-type]
        result = cast(AgentState, resumed)
        result["new_inference_count"] = len(result["inspection_results"])
        result["max_risk"] = self._max_risk(result["risk_results"])
        self.tasks[task_id] = result
        self._persist_state(result, include_user=False)
        return result

    def get_task(self, task_id: str) -> AgentState | None:
        return self.tasks.get(task_id) or self._restore_state(task_id)

    @staticmethod
    def _max_risk(risks: list[RiskAssessment]) -> str:
        order = {"info": 0, "low": 1, "normal": 2, "medium": 3, "high": 4, "critical": 5}
        return max(
            (item.severity.value for item in risks),
            key=lambda item: order.get(item, 0),
            default="low",
        )

    @staticmethod
    def _state_payload(state: AgentState) -> dict[str, Any]:
        def dump(value: Any) -> Any:
            if hasattr(value, "model_dump"):
                return value.model_dump(mode="json")
            if isinstance(value, Path):
                return str(value)
            if isinstance(value, list):
                return [dump(item) for item in value]
            if isinstance(value, dict):
                return {key: dump(item) for key, item in value.items()}
            return value

        return {key: dump(value) for key, value in state.items()}

    def _persist_state(self, state: AgentState, *, include_user: bool) -> None:
        if self.memory is None:
            return
        database_status = (
            "WAIT_FOR_CONFIRMATION"
            if state["status"] == "WAIT_FOR_CONFIRMATION"
            else "failed"
            if state["status"] == "safe_failure"
            else "completed"
        )
        payload = self._state_payload(state)
        persisted = {
            "agent_state": payload,
            "action": state["action"],
            "inspections": payload["inspection_results"],
            "risks": payload["risk_results"],
            "retrieved_chunks": payload["retrieved_chunks"],
            "visual_evidence": payload["visual_evidence"],
            "routing_decisions": payload["routing_decisions"],
            "evidence_status": state["evidence_status"],
            "max_risk": state["max_risk"],
            "new_inference_count": state["new_inference_count"],
            "reused_inspection_count": state["reused_inspection_count"],
            "tool_chain": state["tool_chain"],
            "report_path": state["report_path"],
        }
        self.memory.update_task(
            state["task_id"],
            status=database_status,
            result=persisted,
        )
        if database_status == "completed" and state["inspection_results"]:
            for index, inspection in enumerate(state["inspection_results"]):
                risks = (
                    [state["risk_results"][index]]
                    if index < len(state["risk_results"])
                    else []
                )
                self.memory.save_inspection(
                    state["session_id"],
                    inspection.model_copy(update={"risks": risks}),
                    risks,
                )
        if include_user:
            self.memory.add_message(
                state["session_id"],
                "user",
                state["user_query"],
                {"task_id": state["task_id"]},
            )
        if state["final_response"]:
            self.memory.add_message(
                state["session_id"],
                "assistant",
                state["final_response"],
                {"task_id": state["task_id"]},
            )

    def _restore_state(self, task_id: str) -> AgentState | None:
        if self.memory is None:
            return None
        stored = self.memory.get_task(task_id)
        if stored is None or "agent_state" not in stored.result:
            return None
        raw = stored.result["agent_state"]
        if not isinstance(raw, dict):
            return None
        restored: AgentState = {
            **raw,
            "requested_action": raw.get("requested_action"),
            "action": str(raw.get("action", "auto")),
            "image_paths": [Path(item) for item in raw.get("image_paths", [])],
            "intent": (
                IntentResult.model_validate(raw["intent"])
                if raw.get("intent") is not None
                else None
            ),
            "inspection_analysis": (
                InspectionAnalysisDecision.model_validate(raw["inspection_analysis"])
                if raw.get("inspection_analysis") is not None
                else None
            ),
            "plan": (TaskPlan.model_validate(raw["plan"]) if raw.get("plan") is not None else None),
            "plan_phase": raw.get("plan_phase", "general"),
            "tool_results": [
                ToolCallResult.model_validate(item) for item in raw.get("tool_results", [])
            ],
            "inspection_results": [
                InspectionResult.model_validate(item) for item in raw.get("inspection_results", [])
            ],
            "retrieved_evidence": [
                RetrievedEvidence.model_validate(item) for item in raw.get("retrieved_evidence", [])
            ],
            "retrieved_chunks": [
                DocumentChunk.model_validate(item) for item in raw.get("retrieved_chunks", [])
            ],
            "visual_evidence": [
                EvidenceRecord.model_validate(item) for item in raw.get("visual_evidence", [])
            ],
            "routing_decisions": [
                RoutingDecision.model_validate(item)
                for item in raw.get("routing_decisions", [])
            ],
            "evidence_status": raw.get("evidence_status", "not_requested"),
            "tool_chain": [str(item) for item in raw.get("tool_chain", [])],
            "new_inference_count": int(raw.get("new_inference_count", 0)),
            "reused_inspection_count": int(raw.get("reused_inspection_count", 0)),
            "max_risk": str(raw.get("max_risk", "low")),
            "grounding_result": (
                GroundingResult.model_validate(raw["grounding_result"])
                if raw.get("grounding_result") is not None
                else None
            ),
            "risk_results": [
                RiskAssessment.model_validate(item) for item in raw.get("risk_results", [])
            ],
            "performance_trace": [
                TokenMetrics.model_validate(item) for item in raw.get("performance_trace", [])
            ],
            "memory_messages": [
                AgentMessage.model_validate(item) for item in raw.get("memory_messages", [])
            ],
        }  # type: ignore[typeddict-item]
        return restored
