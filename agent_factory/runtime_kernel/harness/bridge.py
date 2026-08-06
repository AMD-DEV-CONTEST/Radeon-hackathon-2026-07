from __future__ import annotations

from typing import Any

from agent_factory.runtime_kernel.bindings.services import RuntimeServices
from agent_factory.runtime_kernel.harness.assertions import (
    AssertCheckpointCreated,
    AssertContextBuilt,
    AssertContextCompressed,
    AssertFinalAnswer,
    AssertHiddenContextKey,
    AssertOutputContains,
    AssertPathContains,
    AssertPathOrdered,
    AssertPolicyApprovalRequired,
    AssertPolicyBlocked,
    AssertPolicyRefusal,
    AssertResumeContinuous,
    AssertResumeEvent,
    AssertToolCalled,
    AssertToolApprovalRequired,
    AssertToolProposed,
)
from agent_factory.runtime_kernel.harness.fixtures import FixtureBundle, HarnessScenario, HarnessScenarioResult
from agent_factory.runtime_kernel.kernel.facade import RuntimeKernelFacade


class HarnessBridge:
    def __init__(self, *, facade: RuntimeKernelFacade | None = None) -> None:
        self.facade = facade or RuntimeKernelFacade()

    def run_scenario(
        self,
        *,
        pattern_id: str,
        bindings: Any,
        services: RuntimeServices,
        fixture: FixtureBundle,
        scenario: HarnessScenario,
    ) -> HarnessScenarioResult:
        merged_services = services.model_copy(
            update={
                "model_service": fixture.model_service or services.model_service,
                "tool_registry": fixture.tool_registry or services.tool_registry,
                "memory_store": fixture.memory_store or services.memory_store,
                "checkpointer": fixture.checkpointer or services.checkpointer,
            }
        )
        try:
            compiled = self.facade.compile(pattern_id=pattern_id, bindings=bindings, services=merged_services)
        except Exception as exc:
            return _failed_result(scenario=scenario, location="compile", exc=exc)
        try:
            result_state = self.facade.run(
                compiled,
                user_input=scenario.input_text,
                user_config=scenario.user_config,
                agent_config=scenario.agent_config,
                session_config=scenario.session_config,
            )
        except Exception as exc:
            return _failed_result(scenario=scenario, location="run", exc=exc)
        interrupted_state = None
        if scenario.resume_after_interrupt:
            session_id = result_state.run.session_id
            if session_id:
                interrupted_state = result_state
                resume_payload = scenario.resume_payload
                if not resume_payload and fixture.approval_responses:
                    resume_payload = fixture.approval_responses[0]
                try:
                    result_state = self.facade.resume(
                        compiled,
                        session_id=session_id,
                        resume_payload=resume_payload,
                        session_config=scenario.session_config,
                    )
                except Exception as exc:
                    return _failed_result(scenario=scenario, location="resume", exc=exc)
                result_state.observability.debug_refs = [
                    *interrupted_state.observability.debug_refs,
                    *result_state.observability.debug_refs,
                ]
                result_state.observability.events = [
                    *interrupted_state.observability.events,
                    *result_state.observability.events,
                ]
        assertion_results = []
        error = _error_from_state(result_state)
        for raw in scenario.assertions:
            kind = raw.get("type")
            try:
                if kind == "path_contains":
                    assertion = AssertPathContains(raw.get("expected_node_ids") or [])
                    assertion_results.append(assertion.check(event_log=result_state.observability.events))
                elif kind == "path_ordered":
                    assertion = AssertPathOrdered(raw.get("expected_node_ids") or [])
                    assertion_results.append(assertion.check(event_log=result_state.observability.events))
                elif kind == "tool_called":
                    assertion = AssertToolCalled(str(raw.get("tool_id") or ""))
                    assertion_results.append(assertion.check(final_state=result_state))
                elif kind == "tool_proposed":
                    assertion = AssertToolProposed(str(raw.get("tool_id") or ""))
                    assertion_results.append(assertion.check(event_log=result_state.observability.events))
                elif kind == "tool_approval_required":
                    assertion = AssertToolApprovalRequired()
                    assertion_results.append(assertion.check(final_state=result_state))
                elif kind == "final_answer":
                    assertion = AssertFinalAnswer(str(raw.get("expected") or ""))
                    assertion_results.append(assertion.check(final_state=result_state))
                elif kind == "output_contains":
                    assertion = AssertOutputContains(str(raw.get("expected") or ""))
                    assertion_results.append(assertion.check(final_state=result_state))
                elif kind == "policy_blocked":
                    assertion = AssertPolicyBlocked()
                    assertion_results.append(assertion.check(final_state=result_state))
                elif kind == "policy_approval_required":
                    assertion = AssertPolicyApprovalRequired()
                    assertion_results.append(assertion.check(final_state=result_state))
                elif kind == "policy_refusal":
                    assertion = AssertPolicyRefusal()
                    assertion_results.append(assertion.check(final_state=result_state))
                elif kind == "context_built":
                    assertion = AssertContextBuilt(str(raw.get("context_key") or ""))
                    assertion_results.append(assertion.check(final_state=result_state))
                elif kind == "context_compressed":
                    assertion = AssertContextCompressed()
                    assertion_results.append(assertion.check(final_state=result_state))
                elif kind == "hidden_context_key":
                    assertion = AssertHiddenContextKey(str(raw.get("context_key") or ""))
                    assertion_results.append(assertion.check(final_state=result_state))
                elif kind == "checkpoint_created":
                    assertion = AssertCheckpointCreated()
                    assertion_results.append(assertion.check(final_state=result_state))
                elif kind == "resume_event":
                    assertion = AssertResumeEvent()
                    assertion_results.append(assertion.check(event_log=result_state.observability.events))
                elif kind == "resume_continuous":
                    assertion = AssertResumeContinuous()
                    assertion_results.append(assertion.check(event_log=result_state.observability.events))
            except Exception as exc:
                assertion_results.append({"type": kind or "unknown", "ok": False, "error": str(exc)})
                error = error or _error_from_exception(exc, location=f"assertion:{kind or 'unknown'}")
        assertions_ok = all(item.get("ok") for item in assertion_results) if assertion_results else True
        if not assertions_ok and error is None:
            failed_types = [str(item.get("type") or "unknown") for item in assertion_results if not item.get("ok")]
            error = {
                "message": "Harness assertions failed: " + ", ".join(failed_types),
                "location": "harness.assertions",
                "reason": "assertion_failed",
            }
        ok = assertions_ok and error is None
        return HarnessScenarioResult(
            scenario_id=scenario.scenario_id,
            status="passed" if ok else "failed",
            error=error,
            assertion_results=assertion_results,
            final_answer=result_state.conversation.final_answer,
            final_state_snapshot=result_state.model_dump(mode="json"),
            event_log=result_state.observability.events,
            trace_summary=_trace_summary(merged_services, result_state),
        )


def _failed_result(*, scenario: HarnessScenario, location: str, exc: Exception) -> HarnessScenarioResult:
    return HarnessScenarioResult(
        scenario_id=scenario.scenario_id,
        status="failed",
        error=_error_from_exception(exc, location=location),
    )


def _trace_summary(services, state) -> dict | None:
    recorder = getattr(services, "trace_recorder", None)
    if recorder is None:
        return None
    return recorder.manifest_for(state.observability.trace_id)


def _error_from_exception(exc: Exception, *, location: str) -> dict[str, str]:
    return {
        "message": str(exc),
        "location": location,
        "reason": exc.__class__.__name__,
    }


def _error_from_state(state: Any) -> dict[str, str] | None:
    if state.execution.finish_status != "failed":
        return None
    return {
        "message": state.execution.last_error or "Runtime execution failed.",
        "location": state.execution.last_error_location
        or state.execution.current_node
        or state.execution.current_subgraph
        or "runtime",
        "reason": "runtime_failed",
    }
