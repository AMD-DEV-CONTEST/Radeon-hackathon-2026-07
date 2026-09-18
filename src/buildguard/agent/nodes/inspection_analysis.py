"""Post-vision planning that keeps model routing and risk scores deterministic."""

from __future__ import annotations

import json

from buildguard.agent.state import AgentState, InspectionAnalysisDecision
from buildguard.llm.base import ChatMessage, LocalLLMBackend
from buildguard.schemas.agent import PlanStep, TaskPlan


def _labels(state: AgentState) -> list[str]:
    return sorted(
        {
            detection.label
            for inspection in state["inspection_results"]
            for detection in inspection.detections
        }
    )


def analyze_inspection(
    state: AgentState,
    backend: LocalLLMBackend,
) -> dict[str, object]:
    """Let the LLM decide evidence needs from facts, never detector selection or scores."""

    labels = _labels(state)
    summaries = [
        {
            "source_path": str(inspection.source_path),
            "detections": [
                {
                    "label": item.label,
                    "confidence": item.confidence,
                    "source_model": item.source_model,
                    "requires_review": item.confidence < 0.65,
                }
                for item in inspection.detections
            ],
        }
        for inspection in state["inspection_results"]
    ]
    prompt = (
        "This is an inspection analysis request. Decide whether the verified visual "
        "findings require a local construction-standards search and whether bounded "
        "session history is useful for recurrence. Build a concise Chinese RAG query "
        "from the supplied canonical detection labels. Never select or guess a vision "
        "model, change confidence, or assign a risk score. Return JSON only.\n"
        f"User query: {state['user_query']}\n"
        f"Requested action: {state['requested_action'] or 'auto'}\n"
        f"Canonical labels: {json.dumps(labels, ensure_ascii=False)}\n"
        f"Visual facts: {json.dumps(summaries, ensure_ascii=False, separators=(',', ':'))[:12000]}"
    )
    decision = backend.structured_chat(
        [ChatMessage(role="user", content=prompt)],
        InspectionAnalysisDecision,
        thinking=bool(labels),
        profile="structured_plan",
    )
    if not labels:
        decision = decision.model_copy(
            update={"search_standards": False, "standards_query": None}
        )
    elif decision.search_standards and not (decision.standards_query or "").strip():
        decision = decision.model_copy(
            update={"standards_query": "施工安全规范 " + " ".join(labels)}
        )

    steps: list[PlanStep] = []
    if decision.search_standards and decision.standards_query:
        steps.append(
            PlanStep(
                step_id="standards",
                description="根据视觉缺陷类别检索本地施工规范",
                tool_name="search_construction_standards",
                arguments={"query": decision.standards_query, "top_k": 5},
            )
        )
    if decision.query_history:
        steps.append(
            PlanStep(
                step_id="history",
                description="查询当前会话中的历史巡检与重复事件",
                tool_name="query_task_history",
                arguments={
                    "session_id": "$session.id",
                    "limit": decision.history_limit,
                },
            )
        )

    trace = [*state["performance_trace"], *getattr(backend, "metrics_history", [])[-1:]]
    if steps:
        return {
            "inspection_analysis": decision,
            "plan": TaskPlan(goal="补充巡检依据与历史上下文", steps=steps),
            "plan_phase": "inspection_enrichment",
            "current_step": 0,
            "errors": [],
            "status": "running",
            "performance_trace": trace,
        }
    return {
        "inspection_analysis": decision,
        **build_risk_plan(state),
        "performance_trace": trace,
    }


def build_risk_plan(state: AgentState) -> dict[str, object]:
    """Create the deterministic scoring call after optional retrieval completes."""

    return {
        "plan": TaskPlan(
            goal="对视觉检测结果执行确定性风险评分",
            steps=[
                PlanStep(
                    step_id="risk",
                    description="使用不可由 LLM 修改的风险策略计算分数",
                    tool_name="assess_risk",
                    arguments={
                        "inspection_results": "$state.inspection_results",
                        "retrieved_evidence": "$state.retrieved_evidence",
                    },
                )
            ],
        ),
        "plan_phase": "risk",
        "current_step": 0,
        "errors": [],
        "status": "running",
    }
