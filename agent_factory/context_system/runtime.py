from __future__ import annotations

from time import perf_counter
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agent_factory.context_system.assembly import assemble_context_frame
from agent_factory.context_system.compression import maybe_compress_messages
from agent_factory.context_system.events import emit_context_event
from agent_factory.context_system.schema import (
    ContextCandidate,
    ContextContractConfig,
    ContextInjectionReport,
    ContextPolicy,
    ContextQuery,
    ContextRetrievalReport,
    LLMContextFrame,
)
from agent_factory.context_system.sources import ContextSource, ContextSourceRuntime, default_context_sources
from agent_factory.context_system.token_counter import (
    ModelContextLimits,
    TokenCountResult,
    count_messages_tokens,
    context_limits_with_overrides,
    model_context_limits as resolve_model_context_limits,
)
from agent_factory.context_system.token_estimation import estimate_text_tokens


class ContextPreparationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    state: Any
    messages: list[Any] = Field(default_factory=list)
    frame: LLMContextFrame | None = None
    messages_changed: bool = False
    retrieval_report: ContextRetrievalReport
    injection_report: ContextInjectionReport


class ContextSystemRuntime:
    def __init__(
        self,
        *,
        config: ContextContractConfig | None = None,
        sources: dict[str, ContextSource] | None = None,
    ) -> None:
        self.config = config or ContextContractConfig()
        self.sources = sources or default_context_sources()

    def prepare_before_model_call(
        self,
        *,
        state: Any,
        node_id: str,
        impl: str,
        messages: list[Any],
        services: Any = None,
        resources: dict[str, Any] | None = None,
        enable_dynamic_evidence: bool = True,
    ) -> ContextPreparationResult:
        if not self.config.enabled:
            retrieval_report = ContextRetrievalReport(status="skipped", node_id=node_id)
            injection_report = ContextInjectionReport(status="skipped", node_id=node_id)
            return ContextPreparationResult(
                state=state,
                messages=list(messages),
                retrieval_report=retrieval_report,
                injection_report=injection_report,
            )
        policy = self.config.default_policy
        active_limits = self.model_context_limits(
            services=services,
            state=state,
            model_role="main",
        )
        compression_policy = policy.compression.model_copy(
            update={"trigger_token_threshold": active_limits.compression_trigger_tokens}
        )
        working_messages = list(messages)
        working_state = state
        measured_count = count_messages_tokens(working_messages, services=services)
        effective_count = _effective_context_token_count(
            state=working_state,
            measured_count=measured_count,
        )
        compression_messages, compression_report = maybe_compress_messages(
            messages=working_messages,
            policy=compression_policy,
            node_id=node_id,
            token_counter=lambda items: count_messages_tokens(items, services=services),
            trigger_count=effective_count,
            on_start=lambda report: emit_context_event(
                services=services,
                state=working_state,
                event_type="context_compression_started",
                node_id=node_id,
                payload=report.model_dump(mode="json"),
            ),
        )
        compression_event_type = {
            "completed": "context_compression_completed",
            "failed": "context_compression_failed",
            "skipped": "context_compression_skipped",
        }.get(compression_report.status, "context_compression_skipped")
        emit_context_event(
            services=services,
            state=working_state,
            event_type=compression_event_type,
            node_id=node_id,
            payload=compression_report.model_dump(mode="json"),
        )
        if compression_report.status == "failed":
            raise RuntimeError(compression_report.error or "context compression failed")
        messages_changed = compression_messages != working_messages
        working_messages = compression_messages
        if not enable_dynamic_evidence:
            retrieval_report = ContextRetrievalReport(status="skipped", node_id=node_id)
            injection_report = ContextInjectionReport(status="skipped", node_id=node_id)
            skip_payload = {"reason": "dynamic_evidence_disabled_for_node"}
            emit_context_event(
                services=services,
                state=working_state,
                event_type="context_retrieval_completed",
                node_id=node_id,
                payload={**retrieval_report.model_dump(mode="json"), **skip_payload},
            )
            emit_context_event(
                services=services,
                state=working_state,
                event_type="context_assembly_completed",
                node_id=node_id,
                payload={**injection_report.model_dump(mode="json"), **skip_payload},
            )
            emit_context_event(
                services=services,
                state=working_state,
                event_type="context_injection_completed",
                node_id=node_id,
                payload={**injection_report.model_dump(mode="json"), **skip_payload},
            )
            return ContextPreparationResult(
                state=working_state,
                messages=working_messages,
                messages_changed=messages_changed,
                retrieval_report=retrieval_report,
                injection_report=injection_report,
            )
        reused_frame = _reusable_turn_evidence_frame(state=working_state, node_id=node_id)
        if reused_frame is not None:
            retrieval_report = ContextRetrievalReport(status="skipped", node_id=node_id)
            retrieval_report.selected_count = len(reused_frame.items)
            retrieval_report.token_estimate = reused_frame.token_estimate
            injection_report = ContextInjectionReport(
                status="completed" if reused_frame.text else "skipped",
                node_id=node_id,
                item_count=len(reused_frame.items),
                token_estimate=reused_frame.token_estimate,
            )
            updated = _state_with_turn_evidence(
                state=working_state,
                node_id=node_id,
                frame=reused_frame,
            )
            emit_context_event(
                services=services,
                state=updated,
                event_type="context_retrieval_completed",
                node_id=node_id,
                payload={**retrieval_report.model_dump(mode="json"), "reuse": True},
            )
            emit_context_event(
                services=services,
                state=updated,
                event_type="context_assembly_completed",
                node_id=node_id,
                payload={**injection_report.model_dump(mode="json"), "reuse": True},
            )
            emit_context_event(
                services=services,
                state=updated,
                event_type="context_injection_completed",
                node_id=node_id,
                payload={**injection_report.model_dump(mode="json"), "reuse": True},
            )
            return ContextPreparationResult(
                state=updated,
                messages=working_messages,
                frame=reused_frame,
                messages_changed=messages_changed,
                retrieval_report=retrieval_report,
                injection_report=injection_report,
            )
        query = self._query_for_state(state=working_state, node_id=node_id, impl=impl, messages=working_messages)
        candidates, retrieval_report = self._retrieve(
            query=query,
            policy=policy,
            runtime_context=ContextSourceRuntime(
                state=working_state,
                messages=working_messages,
                services=services,
                resources=resources or {},
            ),
        )
        frame = assemble_context_frame(
            node_id=node_id,
            query=query,
            candidates=candidates,
            policy=policy.assembly_policy(),
        )
        retrieval_report.selected_count = len(frame.items)
        retrieval_report.token_estimate = frame.token_estimate
        injection_report = ContextInjectionReport(
            status="completed",
            node_id=node_id,
            item_count=len(frame.items),
            token_estimate=frame.token_estimate,
        )
        updated = _state_with_turn_evidence(state=working_state, node_id=node_id, frame=frame)
        emit_context_event(
            services=services,
            state=updated,
            event_type="context_retrieval_completed",
            node_id=node_id,
            payload=retrieval_report.model_dump(mode="json"),
        )
        emit_context_event(
            services=services,
            state=updated,
            event_type="context_assembly_completed",
            node_id=node_id,
            payload=injection_report.model_dump(mode="json"),
        )
        emit_context_event(
            services=services,
            state=updated,
            event_type="context_injection_completed",
            node_id=node_id,
            payload=injection_report.model_dump(mode="json"),
        )
        return ContextPreparationResult(
            state=updated,
            messages=working_messages,
            frame=frame,
            messages_changed=messages_changed,
            retrieval_report=retrieval_report,
            injection_report=injection_report,
        )

    def prepare_factory_values(
        self,
        *,
        stage_id: str,
        values: dict[str, Any],
        services: Any = None,
    ) -> dict[str, Any]:
        if not self.config.enabled:
            return values
        query = ContextQuery(
            node_id=stage_id,
            impl="factory.model_call",
            user_input=str(values.get("user_input") or values.get("requirement") or ""),
            text=_factory_query_text(stage_id=stage_id, values=values),
        )
        policy = self.config.default_policy
        candidates, retrieval_report = self._retrieve(
            query=query,
            policy=policy,
            runtime_context=ContextSourceRuntime(
                services=services,
                factory_values=values,
            ),
        )
        frame = assemble_context_frame(
            node_id=stage_id,
            query=query,
            candidates=candidates,
            policy=policy.assembly_policy(),
        )
        retrieval_report.selected_count = len(frame.items)
        retrieval_report.token_estimate = frame.token_estimate
        injection_report = ContextInjectionReport(
            status="completed" if frame.text else "skipped",
            node_id=stage_id,
            item_count=len(frame.items),
            token_estimate=frame.token_estimate,
        )
        event_sink = getattr(services, "context_event_sink", None)
        emit_context_event(
            services=services,
            state=None,
            event_type="context_retrieval_completed",
            node_id=stage_id,
            payload=retrieval_report.model_dump(mode="json"),
            event_sink=event_sink,
        )
        emit_context_event(
            services=services,
            state=None,
            event_type="context_assembly_completed",
            node_id=stage_id,
            payload=injection_report.model_dump(mode="json"),
            event_sink=event_sink,
        )
        emit_context_event(
            services=services,
            state=None,
            event_type="context_injection_completed",
            node_id=stage_id,
            payload=injection_report.model_dump(mode="json"),
            event_sink=event_sink,
        )
        if not frame.text:
            return values
        return {
            **values,
            "context_frame": frame.model_dump(mode="json"),
            "factory_operating_context": (
                str(values.get("factory_operating_context") or "")
                + "\n\n"
                + frame.text
                + "\nUse this context only when it is directly relevant."
            ).strip(),
        }

    def _retrieve(
        self,
        *,
        query: ContextQuery,
        policy: ContextPolicy,
        runtime_context: ContextSourceRuntime,
    ) -> tuple[list[ContextCandidate], ContextRetrievalReport]:
        started = perf_counter()
        memory_policy = policy.cross_session_memory
        if not memory_policy.enabled or not memory_policy.injection_enabled:
            return [], ContextRetrievalReport(status="skipped", node_id=query.node_id)
        candidates: list[ContextCandidate] = []
        source_counts: dict[str, int] = {}
        try:
            for source_id in ("cross_session_memory",):
                source = self.sources.get(source_id)
                if source is None:
                    continue
                items = [
                    item
                    for item in source.retrieve(query=query, runtime_context=runtime_context)
                    if item.score >= memory_policy.min_score
                ]
                source_counts[source_id] = len(items)
                candidates.extend(items)
                if len(candidates) >= memory_policy.max_candidates:
                    candidates = candidates[: memory_policy.max_candidates]
                    break
            return (
                candidates,
                ContextRetrievalReport(
                    status="completed",
                    node_id=query.node_id,
                    source_counts=source_counts,
                    candidate_count=len(candidates),
                    token_estimate=sum(item.token_estimate for item in candidates),
                    duration_ms=int((perf_counter() - started) * 1000),
                ),
            )
        except Exception as exc:
            return (
                [],
                ContextRetrievalReport(
                    status="failed",
                    node_id=query.node_id,
                    source_counts=source_counts,
                    error=f"{type(exc).__name__}: {exc}",
                    duration_ms=int((perf_counter() - started) * 1000),
                ),
            )

    def _query_for_state(self, *, state: Any, node_id: str, impl: str, messages: list[Any]) -> ContextQuery:
        user_input = str(getattr(getattr(state, "conversation", None), "current_user_input", "") or "")
        chunks = [user_input]
        for message in messages[-4:]:
            content = getattr(message, "content", "")
            if content:
                chunks.append(str(content))
        text = "\n".join(chunk for chunk in chunks if chunk.strip())
        return ContextQuery(node_id=node_id, impl=impl, user_input=user_input or None, text=text)

    def model_context_limits(
        self,
        *,
        services: Any = None,
        state: Any = None,
        model_role: str = "main",
    ) -> ModelContextLimits:
        compression = self.config.default_policy.compression
        return context_limits_with_overrides(
            resolve_model_context_limits(
                services=services,
                state=state,
                model_role=model_role,
            ),
            context_window_tokens=self.config.context_window_tokens,
            compression_trigger_tokens=compression.trigger_token_threshold,
        )


def default_context_runtime(config: ContextContractConfig | None = None) -> ContextSystemRuntime:
    return ContextSystemRuntime(config=config or ContextContractConfig())


def _reusable_turn_evidence_frame(*, state: Any, node_id: str) -> LLMContextFrame | None:
    model_context = getattr(getattr(state, "context", None), "model_context", {}) or {}
    evidence = model_context.get("runtime_turn_evidence") if isinstance(model_context, dict) else None
    if not isinstance(evidence, dict):
        return None
    if evidence.get("run_id") != getattr(getattr(state, "run", None), "run_id", None):
        return None
    if evidence.get("current_user_input") != getattr(getattr(state, "conversation", None), "current_user_input", None):
        return None
    entries = evidence.get("entries")
    if not isinstance(entries, dict):
        return None
    entry = entries.get(node_id)
    if not isinstance(entry, dict):
        return None
    frame = entry.get("frame")
    if not isinstance(frame, dict):
        return None
    return LLMContextFrame.model_validate(frame)


def _state_with_turn_evidence(*, state: Any, node_id: str, frame: LLMContextFrame) -> Any:
    updated = state.model_copy(deep=True)
    frame_payload = frame.model_dump(mode="json")
    model_context = dict(updated.context.model_context)
    evidence = dict(model_context.get("runtime_turn_evidence") or {})
    entries = dict(evidence.get("entries") or {})
    entries[node_id] = {
        "node_id": node_id,
        "frame": frame_payload,
    }
    evidence = {
        "version": "runtime_turn_evidence.v0",
        "run_id": updated.run.run_id,
        "current_user_input": updated.conversation.current_user_input,
        "entries": entries,
    }
    updated.context.model_context = {
        **model_context,
        "llm_context_frame": frame_payload,
        node_id: frame_payload,
        "runtime_turn_evidence": evidence,
    }
    updated.context.assembly_log.append(f"system_context_prepare:{node_id}")
    return updated


def _effective_context_token_count(
    *,
    state: Any,
    measured_count: TokenCountResult,
) -> TokenCountResult:
    budget = dict(getattr(getattr(state, "context", None), "token_budget", {}) or {})
    value = (
        budget.get("last_provider_context_tokens_after_call")
        or budget.get("last_provider_total_tokens")
        or budget.get("last_provider_input_tokens")
    )
    if not isinstance(value, int) and not isinstance(value, float):
        return measured_count
    token_count = int(value)
    if token_count <= 0:
        return measured_count
    return TokenCountResult(
        token_count=token_count,
        method="previous_provider_usage_after_call",
        model_role=str(budget.get("last_provider_model_role") or measured_count.model_role or "main"),
    )


def _factory_query_text(*, stage_id: str, values: dict[str, Any]) -> str:
    chunks = [stage_id]
    for key in ("user_input", "requirement", "requirement_brief", "refined_requirement", "messages"):
        value = values.get(key)
        if value:
            chunks.append(str(value))
    return "\n".join(chunks)
