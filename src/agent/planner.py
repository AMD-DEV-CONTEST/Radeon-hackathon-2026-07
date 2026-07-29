"""Richer multi-step planners for the six Track-2 application modes."""

from __future__ import annotations


def build_task_plan(user_query: str) -> list[str]:
    plan = ["Clarify user goal and constraints"]

    if any(k in user_query for k in ["工作流", "流程", "自动化", "checklist", "清单", "办理"]):
        plan += ["Select workflow template", "Execute tool-backed steps", "Return checklist deliverable"]

    if any(k in user_query for k in ["政策", "规定", "文档", "知识", "faq", "请假", "vpn", "许可证", "涉密"]):
        plan += ["Search private knowledge base (RAG)", "Ground answer on evidence"]

    if any(k in user_query for k in ["文件", "列表", "读取", "代码", "仓库", "readme", "脚本", "ROCm", "技能"]):
        plan += ["Inspect local files / skills", "Produce developer guidance or scaffold"]

    if any(k in user_query for k in ["记住", "笔记", "备忘", "偏好", "回忆"]):
        plan += ["Update or recall session memory"]

    if any(k in user_query for k in ["副驾驶", "合规", "企业", "发到微信"]):
        plan += ["Apply enterprise policy + privacy guard"]

    if any(k in user_query for k in ["计划", "步骤", "总结", "汇报", "执行任务"]):
        plan += ["Produce structured multi-step output"]

    if any(k in user_query for k in ["多代理", "协作", "orchestr", "自动路由"]):
        plan += ["Route via multi-agent orchestrator"]

    plan.append("Return final private answer")
    seen: set[str] = set()
    out: list[str] = []
    for step in plan:
        if step not in seen:
            seen.add(step)
            out.append(step)
    return out


def detect_intent(user_query: str) -> str:
    """Route hint for multi-agent orchestrator."""
    text = user_query
    q = user_query.lower()
    if any(k in text for k in ["工作流", "流程", "自动化", "办理请假", "入职IT", "安全自检", "开发交接"]):
        return "workflow"
    if any(k in text for k in ["技能", "脚手架", "生成项目", "scaffold", "创建项目", "运行技能"]):
        return "skill"
    if any(k in text for k in ["记住", "笔记", "备忘", "偏好", "回忆我", "我喜欢", "我的笔记"]):
        return "memory"
    if any(k in text for k in ["副驾驶", "合规", "发到微信", "企业政策"]):
        return "rag"  # enterprise enrichment applied when mode/orchestrator selects it
    if any(k in text for k in ["代码", "仓库", "readme", "脚本", "开发", "commit", "依赖", "ROCm", "rocm"]):
        return "developer"
    if any(k in text for k in ["政策", "规定", "faq", "请假", "vpn", "知识库", "文档", "许可证", "涉密", "远程"]):
        return "rag"
    if any(k in q for k in ["who are you", "你是谁", "中文", "英文", "详细"]):
        return "general"
    return "rag"
