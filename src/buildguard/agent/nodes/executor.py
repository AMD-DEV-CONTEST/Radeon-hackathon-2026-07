"""Registered tool execution node."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from buildguard.agent.state import AgentState
from buildguard.rag.schemas import DocumentChunk
from buildguard.schemas.common import new_id
from buildguard.schemas.rag import RetrievedEvidence
from buildguard.schemas.tools import ToolCallResult
from buildguard.schemas.vision import InspectionResult, RiskAssessment
from buildguard.security.advanced.control_plan import (
    ControlPlanDraft,
    ControlPlanFreezer,
    ControlStepDraft,
)
from buildguard.security.advanced.taint import TaintTrace, derived_labeled_data
from buildguard.security.advanced.trust_labels import (
    LabeledData,
    Provenance,
    TrustLabel,
)
from buildguard.vision.routing.schemas import RoutingDecision
from buildguard.vision.schemas import EvidenceRecord

Tool = Callable[[dict[str, Any]], dict[str, Any]]
LOGGER = logging.getLogger(__name__)


def _resolve(value: Any, state: AgentState, outputs: dict[str, dict[str, Any]]) -> Any:
    return _resolve_labeled(value, state, outputs).value


def _labeled(
    value: Any,
    label: TrustLabel,
    *,
    source_id: str,
    source_kind: str,
) -> LabeledData:
    return LabeledData(
        value=value,
        label=label,
        provenance=Provenance(source_id=source_id, source_kind=source_kind),
    )


def _resolve_labeled(
    value: Any,
    state: AgentState,
    outputs: dict[str, dict[str, Any]],
) -> LabeledData:
    if value == "$user.query":
        return _labeled(
            state["user_query"],
            TrustLabel.TRUSTED_USER_INSTRUCTION,
            source_id=state["task_id"],
            source_kind="user_instruction",
        )
    if value == "$session.id":
        return _labeled(
            state["session_id"],
            TrustLabel.TRUSTED_POLICY,
            source_id=state["session_id"],
            source_kind="session_policy",
        )
    if value == "$attachments.images":
        return _labeled(
            [str(path) for path in state["image_paths"]],
            TrustLabel.TRUSTED_USER_INSTRUCTION,
            source_id=state["task_id"],
            source_kind="user_attachment",
        )
    if value == "$state.inspection_results":
        return _labeled(
            [item.model_dump(mode="json") for item in state["inspection_results"]],
            TrustLabel.UNTRUSTED_TOOL_OUTPUT,
            source_id=state["task_id"],
            source_kind="verified_visual_state",
        )
    if value == "$state.retrieved_evidence":
        return _labeled(
            [item.model_dump(mode="json") for item in state["retrieved_evidence"]],
            TrustLabel.UNTRUSTED_TOOL_OUTPUT,
            source_id=state["task_id"],
            source_kind="retrieved_evidence_state",
        )
    if isinstance(value, str) and value.startswith("$steps."):
        parts = value.split(".")
        current: Any = outputs[parts[1]]
        for key in parts[3:]:
            current = current[key]
        return _labeled(
            current,
            TrustLabel.UNTRUSTED_TOOL_OUTPUT,
            source_id=parts[1],
            source_kind="tool_output",
        )
    if isinstance(value, dict):
        resolved = {
            key: _resolve_labeled(item, state, outputs)
            for key, item in value.items()
        }
        if resolved:
            return derived_labeled_data(
                {key: item.value for key, item in resolved.items()},
                *resolved.values(),
            )
    if isinstance(value, list):
        resolved_items = [_resolve_labeled(item, state, outputs) for item in value]
        if resolved_items:
            return derived_labeled_data(
                [item.value for item in resolved_items],
                *resolved_items,
            )
    return _labeled(
        value,
        (
            TrustLabel.TRUSTED_CONFIRMATION
            if state["confirmation_granted"]
            else TrustLabel.UNTRUSTED_MODEL_OUTPUT
        ),
        source_id=state["task_id"],
        source_kind=("confirmed_plan" if state["confirmation_granted"] else "model_plan"),
    )


def _freeze_plan(state: AgentState, tools: dict[str, Tool]) -> tuple[ControlPlanFreezer, Any]:
    plan = state["plan"]
    if plan is None:
        raise ValueError("Cannot freeze an empty plan")
    freezer = ControlPlanFreezer(set(tools))
    draft = ControlPlanDraft(
        task_id=state["task_id"],
        steps=[
            ControlStepDraft(
                step_id=step.step_id,
                tool_name=step.tool_name or "invalid",
                data_parameters=tuple(step.arguments),
                depends_on=tuple(step.depends_on),
            )
            for step in plan.steps
        ],
    )
    frozen = freezer.freeze(
        draft,
        [
            _labeled(
                "registered-agent-tool-policy",
                TrustLabel.TRUSTED_POLICY,
                source_id="buildguard-agent-executor",
                source_kind="static_policy",
            )
        ],
    )
    return freezer, frozen


def execute_tools(state: AgentState, tools: dict[str, Tool]) -> dict[str, object]:
    plan = state["plan"]
    if plan is None:
        return {"errors": ["Cannot execute without a plan"], "status": "safe_failure"}
    try:
        freezer, frozen_plan = _freeze_plan(state, tools)
    except Exception as exc:
        return {
            "errors": [f"Control plan rejected: {exc}"],
            "status": "safe_failure",
        }
    results = list(state["tool_results"])
    outputs: dict[str, dict[str, Any]] = {}
    errors = list(state["errors"])
    inspections = list(state["inspection_results"])
    evidence = list(state["retrieved_evidence"])
    chunks = list(state.get("retrieved_chunks", []))
    visual_evidence = list(state.get("visual_evidence", []))
    routing_decisions = list(state.get("routing_decisions", []))
    evidence_status = state.get("evidence_status", "not_requested")
    tool_chain = list(state.get("tool_chain", []))
    risks = list(state["risk_results"])
    report_path = state["report_path"]
    for index, step in enumerate(plan.steps):
        started = time.perf_counter()
        try:
            if step.tool_name is None or step.tool_name not in tools:
                raise KeyError(f"Tool implementation unavailable: {step.tool_name}")
            tool_chain.append(step.tool_name)
            bindings: dict[str, LabeledData | TaintTrace] = {
                parameter: _resolve_labeled(value, state, outputs)
                for parameter, value in step.arguments.items()
            }
            bound = freezer.bind_step(frozen_plan, step.step_id, bindings)
            arguments = bound.arguments
            secure_invoke = getattr(tools, "invoke", None)
            result: ToolCallResult | None = None
            if callable(secure_invoke):
                result = secure_invoke(
                    step.tool_name,
                    arguments,
                    session_id=state["session_id"],
                    task_id=state["task_id"],
                    confirmed=state["confirmation_granted"],
                )
                if not result.success:
                    raise RuntimeError(result.error or "Tool execution failed")
                output = result.output or {}
            else:
                output = tools[step.tool_name](arguments)
            outputs[step.step_id] = output
            results.append(
                result
                or ToolCallResult(
                    call_id=new_id(),
                    success=True,
                    output=output,
                    duration_ms=(time.perf_counter() - started) * 1000,
                )
            )
            raw_inspection = output.get("inspection")
            if isinstance(raw_inspection, dict):
                inspections.append(InspectionResult.model_validate(raw_inspection))
            for item in output.get("results", []):
                if isinstance(item, dict) and isinstance(item.get("inspection"), dict):
                    inspections.append(InspectionResult.model_validate(item["inspection"]))
                if isinstance(item, dict):
                    for raw_evidence in item.get("evidence", []):
                        if isinstance(raw_evidence, dict):
                            visual_evidence.append(
                                EvidenceRecord.model_validate(raw_evidence)
                            )
                    raw_summary = item.get("summary")
            for frame in output.get("frame_results", []):
                if isinstance(frame, dict) and isinstance(frame.get("inspection"), dict):
                    inspections.append(InspectionResult.model_validate(frame["inspection"]))
            for raw_evidence in output.get("evidence", []):
                if isinstance(raw_evidence, dict):
                    visual_evidence.append(EvidenceRecord.model_validate(raw_evidence))
            raw_summary = output.get("summary")
            if isinstance(raw_summary, dict):
                for raw_decision in raw_summary.get("routing_decisions", []):
                    if isinstance(raw_decision, dict):
                        routing_decisions.append(
                            RoutingDecision.model_validate(raw_decision)
                        )
            raw_chunks = output.get("chunks", [])
            scores = output.get("scores", [])
            for chunk_index, item in enumerate(raw_chunks):
                if not isinstance(item, dict):
                    continue
                try:
                    chunks.append(DocumentChunk.model_validate(item))
                except Exception as exc:
                    LOGGER.debug("Ignoring non-document RAG chunk: %s", exc)
                normalized = {
                    "document_id": item.get("document_id")
                    or item.get("document_checksum"),
                    "chunk_id": item.get("chunk_id"),
                    "content": item.get("content"),
                    "score": item.get(
                        "score",
                        scores[chunk_index] if chunk_index < len(scores) else 0,
                    ),
                    "source": item.get("source") or item.get("source_path"),
                    "metadata": {
                        key: value
                        for key, value in {
                            "document_name": item.get("document_name"),
                            "page": item.get("page"),
                            "article": item.get("article"),
                        }.items()
                        if isinstance(value, (str, int, float, bool))
                    },
                }
                try:
                    evidence.append(RetrievedEvidence.model_validate(normalized))
                except Exception as exc:
                    LOGGER.debug("Ignoring non-evidence RAG chunk: %s", exc)
                    continue
            if output.get("evidence_status") in {
                "sufficient",
                "insufficient_evidence",
            }:
                evidence_status = output["evidence_status"]
            raw_assessment = output.get("assessment")
            raw_assessments = output.get("assessments", [])
            if isinstance(raw_assessment, dict) and not raw_assessments:
                risks.append(RiskAssessment.model_validate(raw_assessment))
            for raw_assessment in raw_assessments:
                if isinstance(raw_assessment, dict):
                    risks.append(RiskAssessment.model_validate(raw_assessment))
            if isinstance(output.get("report_path"), str):
                report_path = output["report_path"]
        except Exception as exc:
            message = f"Step {step.step_id} failed: {exc}"
            errors.append(message)
            results.append(
                ToolCallResult(
                    call_id=new_id(),
                    success=False,
                    error=message,
                    duration_ms=(time.perf_counter() - started) * 1000,
                )
            )
            return {
                "tool_results": results,
                "errors": errors,
                "current_step": index,
                "inspection_results": inspections,
                "retrieved_evidence": evidence,
                "retrieved_chunks": chunks,
                "visual_evidence": visual_evidence,
                "routing_decisions": routing_decisions,
                "evidence_status": evidence_status,
                "tool_chain": tool_chain,
                "risk_results": risks,
                "report_path": report_path,
                "status": "running",
            }
    return {
        "tool_results": results,
        "errors": errors,
        "current_step": len(plan.steps),
        "inspection_results": inspections,
        "retrieved_evidence": evidence,
        "retrieved_chunks": chunks,
        "visual_evidence": visual_evidence,
        "routing_decisions": routing_decisions,
        "evidence_status": evidence_status,
        "tool_chain": tool_chain,
        "risk_results": risks,
        "report_path": report_path,
        "status": "running",
    }
