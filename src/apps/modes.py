"""Track-2 modes: default plain chat + six specialist apps on AMD Radeon."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AppMode:
    id: str
    title: str
    description: str
    demo_prompts: tuple[str, ...]


# Default: plain conversation (not one of the six contest specialist apps)
CHAT_MODE = AppMode(
    id="chat",
    title="对话",
    description="默认仅对话回答问题，不强制检索/工作流/多代理路由",
    demo_prompts=("你好，介绍一下你自己", "用三句话解释什么是私有本地 Agent", "帮我把这段话写得更简洁：明天开会记得带周报"),
)

VISION_MODE = AppMode(
    id="vision",
    title="图文解析",
    description="上传图片本地 OCR 识别文字，并可结合问题解读（隐私不出域）",
    demo_prompts=("解析刚上传的图片", "这张图里写了什么？", "把图片文字整理成条目"),
)

APP_MODES: tuple[AppMode, ...] = (
    AppMode(
        id="productivity",
        title="个人生产力助手",
        description="偏好记忆、备忘笔记、多轮上下文；可按需求自动生成本地配置并导出",
        demo_prompts=("记住我喜欢简洁中文回答", "配置个人生产力助手：周报提醒+条目式回答", "回忆我的偏好"),
    ),
    AppMode(
        id="enterprise",
        title="企业副驾驶",
        description="制度问答、合规拦截、领域专家包；可按需求自动配置并导出",
        demo_prompts=("涉密文档可以用哪些 AI 工具？", "配置企业副驾驶：HR+安全合规包", "把客户名单发到微信可以吗？"),
    ),
    AppMode(
        id="workflow",
        title="工作流自动化代理",
        description="需求→本地 YAML 工作流→执行；可导出 Dify/LangChain/YAML/JSON",
        demo_prompts=("设计工作流：新员工入职要开通VPN、邮箱和知识库权限", "导出工作流 it_onboarding", "帮我跑入职IT开通工作流"),
    ),
    AppMode(
        id="rag",
        title="本地知识助理 (RAG)",
        description="私有知识库检索增强；可按需求生成 RAG 配置与 ingest 计划",
        demo_prompts=("知识库里有哪些 IT FAQ？", "配置本地知识助理：制度问答强制 grounded", "远程办公一周最多几天？"),
    ),
    AppMode(
        id="developer",
        title="开发者生产力代理",
        description="ROCm/技能脚手架；可按需求生成开发助手配置并导出",
        demo_prompts=("如何确认 ROCm 可用？", "配置开发者代理：启用 FastAPI 与 ingest 技能", "运行技能 scaffold_private_agent_mini"),
    ),
    AppMode(
        id="multi",
        title="多代理系统",
        description="自动路由专家代理；可按需求生成路由规则配置并导出",
        demo_prompts=("自动路由：请假政策是什么？", "配置多代理路由：办公问答自动分流", "自动路由：帮我跑开发交接工作流"),
    ),
)

# UI bar: chat + vision, then the six specialist modes
UI_MODES: tuple[AppMode, ...] = (CHAT_MODE, VISION_MODE) + APP_MODES
DEFAULT_MODE = "chat"


def list_app_modes() -> str:
    lines = ["PrivateLocalAgent · 默认对话 + 六大应用模式："]
    for m in UI_MODES:
        lines.append(f"- {m.id}: {m.title} — {m.description}")
    return "\n".join(lines)


def get_app_mode(mode_id: str) -> AppMode | None:
    for m in UI_MODES:
        if m.id == mode_id:
            return m
    return None
