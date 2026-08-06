"""XAI 后端共享运行时单例（中性模块，避免循环导入 / 双实例）。

server_xai.py 与路由模块（server_routes_*.py）共用本模块的引擎 / 知识库适配器 / 能力注册表单例，
确保无论作为 __main__ 还是被 import 为模块，都指向同一实例（同一记忆库、同一适配器）。
"""
from __future__ import annotations

import os

from core.kernel.engine import XAIEngine
from core.adapters.knowledge_adapter import KnowledgeAdapter

# ---- 全局引擎实例（单例）----
_engine: XAIEngine | None = None


def get_engine() -> XAIEngine:
    global _engine
    if _engine is None:
        xai_home = os.environ.get("XAI_HOME", os.path.expanduser("~/.xai"))
        xai_ws = os.environ.get("XAI_WORKSPACE", os.path.join(xai_home, "workspace"))
        _engine = XAIEngine(workspace=xai_ws, memory_home=xai_home)
        print(f"[xai] 引擎已启动, workspace={xai_ws}")
    return _engine


# ---- 知识管道适配器单例（S3 防腐层）----
_kb_adapter: KnowledgeAdapter | None = None


def get_knowledge_adapter() -> KnowledgeAdapter:
    global _kb_adapter
    if _kb_adapter is None:
        _kb_adapter = KnowledgeAdapter()
    return _kb_adapter


# ---- 能力注册表（D2 单一事实源）----
_CAPABILITIES = [
    {"kind": "agent", "label": "数字员工", "color": "#2563eb", "module": "Orchestrator", "backend_type": "chat", "group": "内核", "desc": "多智能体编排与对话"},
    {"kind": "model_router", "label": "模型路由", "color": "#7c3aed", "module": "Router", "backend_type": "router", "group": "内核", "desc": "按任务选模型"},
    {"kind": "intent_router", "label": "意图路由", "color": "#db2777", "module": "Router", "backend_type": "router", "group": "内核", "desc": "意图分类分发"},
    {"kind": "skill", "label": "技能", "color": "#0891b2", "module": "Skill", "backend_type": "skill", "group": "内核", "desc": "技能调用"},
    {"kind": "mcp", "label": "MCP", "color": "#059669", "module": "OpenClaw", "backend_type": "mcp", "group": "执行", "desc": "MCP 工具接入"},
    {"kind": "kb", "label": "知识库", "color": "#ca8a04", "module": "Memory", "backend_type": "chat", "group": "记忆", "desc": "知识检索"},
    {"kind": "human", "label": "人工审批", "color": "#dc2626", "module": "Guardian", "backend_type": "condition", "group": "治理", "desc": "人工确认闸门"},
    {"kind": "reflect", "label": "元认知", "color": "#65a30d", "module": "ControlLoop", "backend_type": "react", "group": "认知", "desc": "自我反思与学习"},
    {"kind": "code", "label": "代码工程", "color": "#ea580c", "module": "GrokBuild", "backend_type": "exec", "group": "工程", "desc": "代码生成与修改"},
    {"kind": "condition", "label": "条件", "color": "#475569", "module": "ControlFlow", "backend_type": "condition", "group": "流控", "desc": "条件分支"},
    {"kind": "subflow", "label": "子流", "color": "#0d9488", "module": "ControlFlow", "backend_type": "loop", "group": "流控", "desc": "子流程循环"},
    {"kind": "openclaw", "label": "OpenClaw", "color": "#16a34a", "module": "Substrate", "backend_type": "exec", "group": "执行", "desc": "本机执行网关"},
    {"kind": "grok_build", "label": "Grok Build", "color": "#0284c7", "module": "GrokBuild", "backend_type": "exec", "group": "工程", "desc": "工程子代理"},
    {"kind": "hermes", "label": "Hermes", "color": "#9333ea", "module": "Hermes", "backend_type": "chat", "group": "内核", "desc": "通用推理自进化"},
    {"kind": "scheduler", "label": "调度中台", "color": "#b45309", "module": "Scheduler", "backend_type": "output", "group": "调度", "desc": "定时与自动化"},
]
