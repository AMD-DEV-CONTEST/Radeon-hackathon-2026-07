from __future__ import annotations

from agent_factory.trace_system.projector import TraceProjector
from agent_factory.trace_system.schema import RepairTracePack, TraceTimelineItem


class TraceDiagnostics:
    """Derive repair-oriented packs from trace projections."""

    def __init__(self, projector: TraceProjector) -> None:
        self.projector = projector

    def build_repair_pack(self, trace_id: str) -> RepairTracePack:
        projection = self.projector.project(trace_id)
        failed = projection.errors[-1] if projection.errors else None
        timeline = projection.timeline
        failure_category = _failure_category(failed.event_type if failed else "", failed.payload if failed else {})
        return RepairTracePack(
            trace_id=projection.manifest.trace_id,
            run_id=projection.manifest.run_id,
            status=projection.manifest.status,
            failed_node=failed.node_id if failed else None,
            failed_span_id=failed.span_id if failed else None,
            failure_category=failure_category,
            error_chain=projection.errors[-10:],
            recent_events=_recent_events(timeline, failed.record_id if failed else None),
            tool_events=_events_with_prefix(timeline, ("tool_", "tool.", "shell.", "mcp.", "skill.")),
            model_events=_events_with_prefix(timeline, ("model_", "model.")),
            context_events=_events_with_prefix(timeline, ("context_", "context.")),
            references=projection.references,
            suspected_root_causes=_suspected_root_causes(failure_category, failed.payload if failed else {}),
            repair_targets=_repair_targets(failure_category),
        )


def _recent_events(timeline: list[TraceTimelineItem], failed_record_id: str | None) -> list[TraceTimelineItem]:
    if not failed_record_id:
        return timeline[-20:]
    index = next((idx for idx, item in enumerate(timeline) if item.record_id == failed_record_id), len(timeline) - 1)
    start = max(0, index - 15)
    end = min(len(timeline), index + 5)
    return timeline[start:end]


def _events_with_prefix(timeline: list[TraceTimelineItem], prefixes: tuple[str, ...]) -> list[TraceTimelineItem]:
    return [
        item
        for item in timeline
        if item.event_type.startswith(prefixes)
        or (item.span_kind is not None and item.span_kind.startswith(prefixes))
    ][-20:]


def _failure_category(event_type: str, payload: dict) -> str | None:
    text = " ".join(str(value) for value in [event_type, payload.get("error"), payload.get("message"), payload.get("where")]).lower()
    if not text.strip():
        return None
    if "schema" in text or "invalid_arguments" in text or "pydantic" in text:
        return "tool_argument_schema_error"
    if "tool" in text and ("failed" in text or "execution" in text):
        return "tool_execution_error"
    if "timeout" in text:
        return "timeout"
    if "context" in text and ("token" in text or "overflow" in text):
        return "context_budget_error"
    if "model" in text or "badrequest" in text or "provider" in text:
        return "model_call_error"
    if "sandbox" in text or "local runtime" in text:
        return "sandbox_runtime_error"
    if "memory" in text:
        return "memory_system_error"
    if "knowledge" in text:
        return "knowledge_system_error"
    if "scheduler" in text:
        return "scheduler_system_error"
    return "runtime_error"


def _suspected_root_causes(category: str | None, payload: dict) -> list[str]:
    if category is None:
        return []
    causes = {
        "tool_argument_schema_error": ["模型生成的工具参数不符合 ToolSpec input_schema。"],
        "tool_execution_error": ["工具 entrypoint 执行失败或 ToolExecutionGateway 返回失败 observation。"],
        "timeout": ["运行请求、节点执行、工具执行或外部服务调用超过配置超时。"],
        "context_budget_error": ["上下文组装或压缩策略没有把模型输入控制在预算内。"],
        "model_call_error": ["模型 provider 拒绝请求、返回非法消息结构或模型配置不可用。"],
        "sandbox_runtime_error": ["本地逻辑隔离、工作区、secret 或依赖初始化失败。"],
        "memory_system_error": ["跨会话记忆检索、注入或后台写入失败。"],
        "knowledge_system_error": ["知识源准备、索引、检索或读取失败。"],
        "scheduler_system_error": ["定时任务触发、执行、总结或失败策略处理异常。"],
        "runtime_error": ["RuntimeKernel 图执行或节点状态合并失败。"],
    }
    result = list(causes.get(category, []))
    where = payload.get("where")
    if where:
        result.append(f"错误位置: {where}")
    return result


def _repair_targets(category: str | None) -> list[str]:
    targets = {
        "tool_argument_schema_error": ["tool_schema", "tool_prompting", "tool_argument_repair_loop"],
        "tool_execution_error": ["tool_entrypoint", "tool_resources", "tool_risk_policy"],
        "timeout": ["runtime_request_policy", "tool_timeout_policy", "external_service_health"],
        "context_budget_error": ["context_policy", "compression_policy", "context_source_limits"],
        "model_call_error": ["model_contract", "model_adapter", "message_protocol"],
        "sandbox_runtime_error": ["runtime_local", "dependencies_contract", "local_runtime"],
        "memory_system_error": ["context_policy", "memory_store", "memory_injection"],
        "knowledge_system_error": ["knowledge_runtime", "knowledge_catalog", "knowledge_ingestion"],
        "scheduler_system_error": ["scheduler_contract", "scheduler_job", "scheduler_executor"],
        "runtime_error": ["runtime_kernel", "node_implementation", "runtime_state"],
    }
    return list(targets.get(category or "", []))
