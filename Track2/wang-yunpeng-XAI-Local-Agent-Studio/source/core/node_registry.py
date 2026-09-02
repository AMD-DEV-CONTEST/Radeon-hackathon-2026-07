"""XAI V2 节点类型注册表

将 run_wf_node 中 if-else 分发改为 dict dispatch：
  - 键为节点类型（ntype），值为 core/kernel/workflow.py 中的处理函数名。
  - workflow.run_wf_node 通过 globals()[handler_name] 动态调用。
  - 未知类型回退到 wf_node_chat（走 LLM 推理）。

Phase D：处理器已从 engine_xai.py 上帝类外移到 core/kernel/workflow.py。
"""

from __future__ import annotations

# 节点类型 → 处理函数名（core/kernel/workflow.py 中的模块函数）
NODE_HANDLER_MAP: dict[str, str] = {
    # 直通类节点（不涉及 LLM）
    "input":          "wf_node_input",
    "scan":           "wf_node_scan",
    "mcp":            "wf_node_mcp",
    "exec":           "wf_node_exec",
    "file":           "wf_node_exec",
    "git":            "wf_node_exec",
    "batch":          "wf_node_batch",
    "agent_dispatch": "wf_node_agent_dispatch",

    # 循环节点（先尝试 JSON 数组，回退 LLM）
    "loop":           "wf_node_loop",
    "subflow":        "wf_node_loop",

    # 真实执行节点（每个有专属 handler）
    "kb":             "wf_node_kb",
    "memory":         "wf_node_kb",          # 记忆节点 = KB 检索
    "grok_build":     "wf_node_grok_build",
    "intent_router":  "wf_node_intent_router",
    "react":          "wf_node_react",
    "reflect":        "wf_node_react",         # 元认知 = ReAct 校准
    "agent":          "wf_node_agent",
    "human":          "wf_node_human",
    "code":           "wf_node_code",
    "skill":          "wf_node_skill",
    "output":         "wf_node_output",
    "openclaw":       "wf_node_openclaw",       # 真实 shell/文件/桌面执行

    # LLM 推理类节点（共用同一个 fallback）
    "chat":           "wf_node_chat",
    "router":         "wf_node_chat",
    "condition":      "wf_node_chat",
    "system":         "wf_node_chat",

    # 思考画布节点（认知类，仍用 chat handler 包装）
    "hermes":         "wf_node_chat",
    "scheduler":      "wf_node_chat",
    "model_router":   "wf_node_chat",
    "reduce":         "wf_node_chat",
    "concept":        "wf_node_chat",
    "reasoning":      "wf_node_chat",
    "architecture":   "wf_node_chat",
    "dependency":     "wf_node_chat",
    "file_ref":       "wf_node_chat",
}

