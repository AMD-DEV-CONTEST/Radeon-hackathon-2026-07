"""V4 内核：纯辅助类与常量（Task #193 Phase A）。

从 engine_xai.py 上帝类外移，零业务逻辑依赖：
- SlashCommand / SLASH_COMMANDS：斜杠命令元数据（名称/别名/描述/用法）
- INTENT_TYPES / Intent：意图类型枚举与意图数据类
- _AdapterResultShim：openclaw CLI 调用超时/失败时的兜底结果对象
"""

from dataclasses import dataclass, field
from typing import List


@dataclass
class SlashCommand:
    name: str
    aliases: List[str] = field(default_factory=list)
    description: str = ""
    usage: str = ""


SLASH_COMMANDS = {
    "skill": SlashCommand("skill", aliases=["s"], description="管理技能（加载/列出/注册）", usage="/skill [list|load|register] <名称>"),
    "mcp": SlashCommand("mcp", aliases=["m"], description="管理 MCP 连接", usage="/mcp [list|connect|tools] <服务器>"),
    "task": SlashCommand("task", aliases=["t"], description="创建并执行任务", usage="/task <任务描述>"),
    "automate": SlashCommand("automate", aliases=["auto", "cron"], description="设置定时自动化", usage="/automate <cron表达式> <命令>"),
    "remember": SlashCommand("remember", aliases=["mem"], description="记住一条信息", usage="/remember <内容>"),
    "recall": SlashCommand("recall", aliases=["r"], description="检索记忆", usage="/recall <关键词>"),
    "scan": SlashCommand("scan", aliases=["audit"], description="安全漏洞扫描", usage="/scan <文件路径>"),
    "evolve": SlashCommand("evolve", aliases=["evo"], description="Darwinian 技能进化", usage="/evolve [技能名]"),
    "models": SlashCommand("models", aliases=["ml"], description="列出可用 AI 模型", usage="/models"),
    "channels": SlashCommand("channels", aliases=["ch"], description="消息渠道管理", usage="/channels [list|status]"),
    "status": SlashCommand("status", aliases=["st"], description="查看系统状态", usage="/status"),
    "diagnose": SlashCommand("diagnose", aliases=["health", "体检", "自检"], description="系统全面自检", usage="/diagnose"),
    "clear": SlashCommand("clear", aliases=["new"], description="清空当前会话历史", usage="/clear"),
    "help": SlashCommand("help", aliases=["h", "?"], description="显示帮助", usage="/help [命令]"),
    "approve": SlashCommand("approve", aliases=["yes"], description="批准待审批操作", usage="/approve <审批ID>"),
    "reject": SlashCommand("reject", aliases=["no"], description="拒绝待审批操作", usage="/reject <审批ID>"),
    "loop": SlashCommand("loop", aliases=["think"], description="启用认知控制环深度思考", usage="/loop <任务>"),
    # V4 命令
    "plan": SlashCommand("plan", aliases=["p"], description="[V4] Planner: 目标→步骤→Agent分配", usage="/plan <任务目标>"),
}


# ---- 意图类型 ----

INTENT_TYPES = [
    "code_dev",       # 代码开发 → Grok Build / Hermes 代码工具
    "research",       # 研究分析 → Hermes 推理
    "office",         # 办公操作 → OpenClaw 桌面/文件
    "browser",        # 浏览器操作 → 真实联网搜索
    "automation",     # 自动化 → OpenClaw cron
    "memory",         # 记忆操作 → MemOS
    "skill_manage",   # 技能管理 → Hermes 技能系统
    "mcp_manage",     # MCP 管理 → OpenClaw MCP 插件
    "system",         # 系统管理 → 自处理
    "general",        # 通用对话 → Hermes 推理
]


@dataclass
class Intent:
    type: str
    confidence: float
    rationale: str
    sub_intents: List[str] = field(default_factory=list)


class _AdapterResultShim:
    """openclaw CLI 调用超时/失败时的兜底结果对象，模拟 AdapterResult.ok/meta/error。"""
    def __init__(self, ok: bool = False, error: str = "", meta: dict = None):
        self.ok = ok
        self.error = error
        self.meta = meta or {}
