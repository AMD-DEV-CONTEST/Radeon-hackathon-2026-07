from __future__ import annotations

from dataclasses import dataclass, field
import os
from typing import Any, Callable, Literal, Mapping

from langgraph.types import interrupt
from pydantic import BaseModel, ConfigDict, Field

from agent_factory.exception_details import exception_leaf_messages, exception_summary
from agent_factory.tooling.execution_context import (
    RuntimeToolExecutionCancelled,
    current_tool_approval_override,
    current_tool_call,
    current_tool_event_sink,
    current_tool_runtime_resource_overrides,
    current_runtime_run_control,
    execute_with_runtime_cancellation,
)
from agent_factory.tooling.output_store import (
    ToolOutputPolicy,
    ToolOutputProjection,
    ToolOutputStore,
    default_tool_output_policy,
    project_tool_output,
)
from agent_factory.tooling.builtins.resource_set.resource_set import (
    RESOURCE_SET_STORE_KEY,
    ResourceSetStore,
    auto_record_path,
)
from agent_factory.models import get_compression_model
from agent_factory.tooling.approval_policy import (
    ToolApprovalPolicyConfig,
    default_tool_approval_policy,
    tool_approval_effective_risk_level,
    tool_approval_policy_action,
)
from agent_factory.tooling.resource_context import build_tool_resource_context
from agent_factory.tooling.redaction import redact_json_pointer_paths
from agent_factory.tooling.risk import ToolRiskEvaluator, call_llm_risk_evaluator, merge_risk_results
from agent_factory.tooling.schema_compiler import CompiledJsonSchema
from agent_factory.tooling.spec import ToolObservation, ToolRiskContext, ToolRiskResult, ToolSpec
from agent_factory.tooling.envelope import unpack_tool_envelope
from agent_factory.tooling.runtime_resources import merge_runtime_resource, resolve_resource_selector


ToolApprovalAction = Literal["approve", "deny", "revise"]
ToolApprovalHandler = Callable[[ToolSpec, dict[str, Any], ToolRiskResult], "ToolApprovalDecision"]
TRUST_TOOL_ACTIONS = {"trust", "trust_tool", "always_allow", "no_approval", "无需审批"}


class ToolResourceRequiredError(RuntimeError):
    def __init__(self, resource_ids: list[str]) -> None:
        normalized = list(dict.fromkeys(item.strip() for item in resource_ids if item.strip()))
        self.resource_ids = normalized
        super().__init__(f"required runtime resources are not configured: {', '.join(normalized)}")


class ToolApprovalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: ToolApprovalAction
    revision_guidance: str = ""


class ToolApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_call_id: str
    tool_name: str
    args: dict[str, Any] = Field(default_factory=dict)
    summary: str
    risk_level: str
    risk_reasons: list[str] = Field(default_factory=list)
    risk_facts: dict[str, Any] = Field(default_factory=dict)


class ToolApprovalTrustStore:
    def __init__(self) -> None:
        self._trusted_tool_ids: set[str] = set()

    def trust_tool(self, tool_id: str) -> None:
        self._trusted_tool_ids.add(tool_id)

    def is_trusted(self, tool_id: str) -> bool:
        return tool_id in self._trusted_tool_ids


DEFAULT_TOOL_APPROVAL_TRUST_STORE = ToolApprovalTrustStore()


@dataclass(slots=True)
class ToolExecutionGateway:
    spec: ToolSpec
    input_schema: CompiledJsonSchema
    output_schema: CompiledJsonSchema
    entrypoint: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]
    global_resources: Mapping[str, Any]
    resource_resolver: Any | None = None
    hard_risk_evaluator: ToolRiskEvaluator | None = None
    llm_risk_prompt: str | None = None
    approval_handler: ToolApprovalHandler | None = None
    approval_policy: ToolApprovalPolicyConfig = field(default_factory=default_tool_approval_policy)
    max_revisions: int = 5
    output_store: ToolOutputStore | None = None
    output_policy: ToolOutputPolicy = field(default_factory=default_tool_output_policy)

    def execute(
        self,
        arguments: dict[str, Any],
        *,
        tool_call_id: str | None = None,
        revision_count: int = 0,
    ) -> dict[str, Any]:
        if revision_count >= self.max_revisions:
            return self._observation(
                "execution_failed",
                f"Tool revision limit exceeded: {self.max_revisions}",
                tool_call_id=tool_call_id,
                arguments=arguments,
                retryable=False,
                errors=[f"max revisions exceeded: {self.max_revisions}"],
            )
        input_errors = self.input_schema.errors_for(arguments)
        if input_errors:
            return self._observation(
                "invalid_arguments",
                "Tool arguments failed schema validation.",
                tool_call_id=tool_call_id,
                arguments=arguments,
                errors=input_errors,
                user_instruction=self.spec.schema_error_guidance or None,
            )
        try:
            tool_resources = self._resolve_resources()
        except ToolResourceRequiredError as exc:
            return self._observation(
                "resource_required",
                f"Required runtime resources are not configured: {', '.join(exc.resource_ids)}",
                tool_call_id=tool_call_id,
                arguments=arguments,
                retryable=False,
                errors=[str(exc)],
                evidence={"resource_ids": exc.resource_ids},
            )
        except Exception as exc:
            return self._observation(
                "execution_failed",
                f"Tool resource resolution failed: {type(exc).__name__}: {exc}",
                tool_call_id=tool_call_id,
                arguments=arguments,
                errors=[f"{type(exc).__name__}: {exc}"],
            )
        risk_context_resources = build_tool_resource_context(tool_resources)
        arguments, risk = self._evaluate_risk(arguments, risk_context_resources)
        approval = self._approval(arguments, risk)
        if approval.action == "deny":
            denial_guidance = approval.revision_guidance or _risk_guidance(risk)
            return self._observation(
                "denied",
                f"Tool call denied: {denial_guidance}" if denial_guidance else "Tool call denied by approval policy or human review.",
                tool_call_id=tool_call_id,
                arguments=arguments,
                user_instruction=denial_guidance or None,
                errors=risk.reasons,
            )
        if approval.action == "revise":
            return self._observation(
                "revision_requested",
                "Human requested argument revision before execution.",
                tool_call_id=tool_call_id,
                arguments=arguments,
                user_instruction=approval.revision_guidance or "Please regenerate the tool call.",
            )
        self._emit_execution_started(arguments=arguments, risk=risk, tool_call_id=tool_call_id)
        try:
            output = execute_with_runtime_cancellation(
                lambda: self.entrypoint(arguments=arguments, resources=tool_resources)
            )
        except RuntimeToolExecutionCancelled as exc:
            return self._observation(
                "cancelled",
                str(exc),
                tool_call_id=tool_call_id,
                arguments=arguments,
                retryable=False,
                errors=[str(exc)],
            )
        except Exception as exc:
            errors = exception_leaf_messages(exc)
            return self._observation(
                "execution_failed",
                f"Tool execution failed: {exception_summary(exc)}",
                tool_call_id=tool_call_id,
                arguments=arguments,
                errors=errors,
            )
        if not isinstance(output, dict):
            return self._observation(
                "invalid_output",
                "Tool entrypoint must return a tool execution envelope.",
                tool_call_id=tool_call_id,
                arguments=arguments,
                output={"value": output},
                execution_status="failed",
                contract_status="invalid",
                errors=["output is not a dict"],
            )
        try:
            envelope = unpack_tool_envelope(output)
        except Exception as exc:
            return self._observation(
                "invalid_output",
                f"Tool entrypoint returned an invalid execution envelope: {type(exc).__name__}: {exc}",
                tool_call_id=tool_call_id,
                arguments=arguments,
                output=output,
                execution_status="failed",
                contract_status="invalid",
                errors=[f"{type(exc).__name__}: {exc}"],
            )
        if envelope.execution_status == "failed":
            return self._observation(
                "execution_failed",
                envelope.summary or f"Tool execution failed: {envelope.error}",
                tool_call_id=tool_call_id,
                arguments=arguments,
                output=envelope.output,
                evidence=envelope.evidence,
                execution_status="failed",
                contract_status="valid",
                retryable=envelope.retryable,
                errors=[envelope.error],
            )
        output = envelope.output
        evidence = envelope.evidence
        summary = envelope.summary
        output_errors = self.output_schema.errors_for(output)
        if output_errors:
            return self._observation(
                "invalid_output",
                "Tool output failed schema validation.",
                tool_call_id=tool_call_id,
                arguments=arguments,
                output=output,
                evidence=evidence,
                execution_status="completed",
                contract_status="invalid",
                errors=output_errors,
            )
        # Auto-record explored paths in the resource set
        resource_set_store = self.global_resources.get(RESOURCE_SET_STORE_KEY)
        if isinstance(resource_set_store, ResourceSetStore):
            auto_record_path(resource_set_store, self.spec.id, arguments)
        projection = (
            ToolOutputProjection(output=output)
            if self.spec.output_projection == "passthrough"
            else project_tool_output(
                output=output,
                tool_id=self.spec.id,
                tool_call_id=tool_call_id,
                arguments=self._public_arguments(arguments),
                store=self.output_store,
                policy=self.output_policy,
                compression_model=(
                    None
                    if _runtime_stop_requested()
                    else get_compression_model()
                ),
                compression_config=self.spec.output_compression,
            )
        )
        return self._observation(
            "completed",
            projection.output_summary or summary or "Tool execution completed.",
            tool_call_id=tool_call_id,
            arguments=arguments,
            output=projection.output,
            output_ref=projection.output_ref,
            output_summary=projection.output_summary,
            output_truncated=projection.output_truncated,
            evidence=evidence,
            execution_status="completed",
            contract_status="valid",
            retryable=False,
        )

    def approval_request(self, arguments: dict[str, Any], *, tool_call_id: str | None = None) -> dict[str, Any] | None:
        """Return the human approval request this call would need, without executing it."""
        if self.approval_handler is not None:
            return None
        if DEFAULT_TOOL_APPROVAL_TRUST_STORE.is_trusted(self.spec.id):
            return None
        input_errors = self.input_schema.errors_for(arguments)
        if input_errors:
            return None
        try:
            tool_resources = self._resolve_resources()
        except Exception:
            return None
        risk_context_resources = build_tool_resource_context(tool_resources)
        normalized_arguments, risk = self._evaluate_risk(arguments, risk_context_resources)
        if tool_approval_policy_action(spec=self.spec, risk=risk, policy=self.approval_policy) != "ask":
            return None
        effective_risk_level = tool_approval_effective_risk_level(
            spec=self.spec,
            risk=risk,
            policy=self.approval_policy,
        )
        return ToolApprovalRequest(
            tool_call_id=tool_call_id or "",
            tool_name=self.spec.id,
            args=self._public_arguments(normalized_arguments),
            summary=self.spec.id,
            risk_level=effective_risk_level,
            risk_reasons=risk.reasons,
            risk_facts=risk.facts,
        ).model_dump(mode="json")

    def _evaluate_risk(
        self,
        arguments: dict[str, Any],
        risk_context_resources: dict[str, Any],
    ) -> tuple[dict[str, Any], ToolRiskResult]:
        context = ToolRiskContext(
            tool_id=self.spec.id,
            base_risk_level=self.spec.risk_level,
            arguments=arguments,
            resources=risk_context_resources,
            tool_call=_current_tool_call_context(self.spec.id),
        ).model_dump(mode="json")
        results: list[ToolRiskResult] = []
        if self.hard_risk_evaluator is not None:
            try:
                raw_result = self.hard_risk_evaluator(arguments, context)
                hard_result = raw_result if isinstance(raw_result, ToolRiskResult) else ToolRiskResult.model_validate(raw_result)
            except Exception as exc:
                hard_result = ToolRiskResult(
                    action="uncertain",
                    risk_level=self.spec.risk_level,
                    reasons=[f"hard risk evaluator failed: {type(exc).__name__}: {exc}"],
                )
            results.append(hard_result)
            if hard_result.normalized_arguments is not None:
                arguments = hard_result.normalized_arguments
            if hard_result.action == "deny":
                return arguments, hard_result
        llm_config = self.spec.risk_evaluator
        should_call_llm = bool(
            self.llm_risk_prompt
            and llm_config.llm_mode != "disabled"
            and (
                llm_config.llm_mode == "always"
                or any(result.action == "uncertain" for result in results)
                or not results
            )
        )
        if should_call_llm:
            try:
                results.append(
                    call_llm_risk_evaluator(
                        tool_id=self.spec.id,
                        base_risk_level=self.spec.risk_level,
                        prompt=self.llm_risk_prompt or "",
                        arguments=arguments,
                        context=context,
                        hard_result=results[-1] if results else None,
                    )
                )
            except Exception as exc:
                results.append(
                    ToolRiskResult(
                        action="uncertain",
                        risk_level=self.spec.risk_level,
                        reasons=[f"llm risk evaluator failed: {type(exc).__name__}: {exc}"],
                    )
                )
        return arguments, merge_risk_results(results, base_risk_level=self.spec.risk_level)

    def _approval(self, arguments: dict[str, Any], risk: ToolRiskResult) -> ToolApprovalDecision:
        policy_action = tool_approval_policy_action(spec=self.spec, risk=risk, policy=self.approval_policy)
        if policy_action == "deny":
            return ToolApprovalDecision(action="deny", revision_guidance=_risk_guidance(risk))
        if policy_action == "allow":
            return ToolApprovalDecision(action="approve")
        if current_tool_approval_override() is not None:
            return ToolApprovalDecision(action="approve")
        if DEFAULT_TOOL_APPROVAL_TRUST_STORE.is_trusted(self.spec.id):
            return ToolApprovalDecision(action="approve")
        handler = self.approval_handler or default_interrupt_approval
        effective_risk_level = tool_approval_effective_risk_level(
            spec=self.spec,
            risk=risk,
            policy=self.approval_policy,
        )
        if effective_risk_level != risk.risk_level:
            risk = risk.model_copy(update={"risk_level": effective_risk_level})
        return handler(self.spec, self._public_arguments(arguments), risk)

    def _resolve_resources(self) -> dict[str, Any]:
        resources: dict[str, Any] = {}
        missing: list[str] = []
        for local_name, selector in self.spec.resources.items():
            try:
                resources[local_name] = self._resolve_resource_selector(selector)
            except KeyError as exc:
                detail = str(exc).strip("'")
                if detail.startswith("resource_required:"):
                    missing.append(detail.partition(":")[2].strip())
                else:
                    missing.append(selector.split(".", 1)[0])
                continue
        if missing:
            raise ToolResourceRequiredError(missing)
        return resources

    def _resolve_resource_selector(self, selector: str) -> Any:
        if self.resource_resolver is not None and self.resource_resolver.owns(selector):
            try:
                return self.resource_resolver.resolve_selector(selector)
            except Exception as exc:
                message = str(exc)
                if message.startswith("resource_required:") or "not declared by package" in message:
                    raise KeyError(message) from exc
                raise
        base_missing = False
        try:
            base = resolve_resource_selector(self.global_resources, selector)
        except KeyError:
            base = None
            base_missing = True
        overrides = current_tool_runtime_resource_overrides()
        try:
            override = resolve_resource_selector(overrides, selector)
        except KeyError:
            if base_missing:
                raise KeyError(selector)
            return base
        if base_missing:
            return override
        return merge_runtime_resource(base, override)

    def _emit_execution_started(
        self,
        *,
        arguments: dict[str, Any],
        risk: ToolRiskResult,
        tool_call_id: str | None,
    ) -> None:
        sink = current_tool_event_sink()
        if sink is None:
            return
        sink(
            {
                "event_type": "tool_started",
                "tool_id": self.spec.id,
                "tool_call_id": tool_call_id or "",
                "arguments": self._public_arguments(arguments),
                "status": "running",
                "risk_level": risk.risk_level,
                "risk_reasons": risk.reasons,
            }
        )

    def _observation(
        self,
        status,
        message: str,
        *,
        tool_call_id: str | None,
        arguments: dict[str, Any],
        user_instruction: str | None = None,
        retryable: bool = True,
        output: dict[str, Any] | None = None,
        output_ref: dict[str, Any] | None = None,
        output_summary: str | None = None,
        output_truncated: bool = False,
        evidence: dict[str, Any] | None = None,
        execution_status: str = "failed",
        contract_status: str = "valid",
        errors: list[str] | None = None,
    ) -> dict[str, Any]:
        return ToolObservation(
            status=status,
            tool_id=self.spec.id,
            tool_call_id=tool_call_id,
            message=message,
            user_instruction=user_instruction,
            retryable=retryable,
            arguments=self._public_arguments(arguments),
            output=output,
            output_ref=output_ref,
            output_summary=output_summary,
            output_truncated=output_truncated,
            evidence=evidence or {},
            execution_status=execution_status,  # type: ignore[arg-type]
            contract_status=contract_status,  # type: ignore[arg-type]
            errors=errors or [],
        ).model_dump(mode="json")

    def _public_arguments(self, arguments: dict[str, Any]) -> dict[str, Any]:
        redacted = redact_json_pointer_paths(arguments, self.spec.sensitive_argument_paths)
        return redacted if isinstance(redacted, dict) else {}


def _runtime_stop_requested() -> bool:
    control = current_runtime_run_control()
    return bool(control is not None and getattr(control, "drain_requested", False))


def default_tool_max_revisions() -> int:
    raw = os.getenv("AGENTFACTORY_TOOL_MAX_REVISIONS", "5").strip()
    try:
        value = int(raw)
    except ValueError:
        return 5
    return max(value, 1)


def _risk_guidance(risk: ToolRiskResult) -> str:
    return "\n".join(risk.reasons).strip()


def _current_tool_call_context(tool_id: str) -> dict[str, Any]:
    current = current_tool_call()
    if current is None or current.tool_id != tool_id:
        return {}
    return {
        "tool_id": current.tool_id,
        "tool_call_id": current.tool_call_id,
        "origin_node_id": current.origin_node_id,
        "origin_impl": current.origin_impl,
    }


def default_interrupt_approval(spec: ToolSpec, arguments: dict[str, Any], risk: ToolRiskResult) -> ToolApprovalDecision:
    current = current_tool_call()
    decision = interrupt(
        {
            "type": "tool_approval",
            "message": "检测到需要人工确认的工具调用，请确认执行、拒绝、信任该工具，或输入审查意见让模型重写工具调用。",
            "choices": {"approve": "-y", "deny": "-n", "trust_tool": "-t", "revise": "custom"},
            "requests": [
                {
                    "tool_call_id": current.tool_call_id if current is not None and current.tool_id == spec.id else "",
                    "tool_name": spec.id,
                    "args": arguments,
                    "summary": spec.id,
                    "risk_level": risk.risk_level or spec.risk_level,
                    "risk_reasons": risk.reasons,
                    "risk_facts": risk.facts,
                }
            ],
        }
    )
    if _is_trust_tool(decision):
        DEFAULT_TOOL_APPROVAL_TRUST_STORE.trust_tool(spec.id)
        return ToolApprovalDecision(action="approve")
    return parse_approval_decision(decision)


def parse_approval_decision(decision: Any) -> ToolApprovalDecision:
    if _is_trust_tool(decision):
        return ToolApprovalDecision(action="approve")
    if _is_approved(decision):
        return ToolApprovalDecision(action="approve")
    if isinstance(decision, dict):
        action = str(decision.get("action") or decision.get("choice") or "").strip().lower()
        if action in {"revise", "retry", "custom", "edit", "rewrite"}:
            return ToolApprovalDecision(action="revise", revision_guidance=_revision_guidance(decision))
    if isinstance(decision, str) and decision.strip().lower() in {"revise", "retry", "custom", "edit", "rewrite"}:
        return ToolApprovalDecision(action="revise", revision_guidance=decision.strip())
    return ToolApprovalDecision(action="deny", revision_guidance=_revision_guidance(decision))


def _is_approved(decision: Any) -> bool:
    if isinstance(decision, bool):
        return decision
    if isinstance(decision, str):
        return decision.strip().lower() in {"-y", "y", "yes", "true", "approve", "approved"}
    if isinstance(decision, dict):
        value = decision.get("approved", decision.get("approve", decision.get("choice")))
        return _is_approved(value)
    return False


def _is_trust_tool(decision: Any) -> bool:
    if isinstance(decision, str):
        return decision.strip().lower() in TRUST_TOOL_ACTIONS or decision.strip().lower() in {"-t", "t", "trust me"}
    if isinstance(decision, dict):
        action = str(decision.get("action") or decision.get("choice") or "").strip().lower()
        if action in TRUST_TOOL_ACTIONS:
            return True
        return bool(decision.get("trust_tool") or decision.get("no_approval"))
    return False


def _revision_guidance(decision: Any) -> str:
    if isinstance(decision, str):
        return decision.strip()
    if isinstance(decision, dict):
        for key in ("revision_guidance", "guidance", "input_text", "message"):
            value = decision.get(key)
            if value:
                return str(value).strip()
    return ""
