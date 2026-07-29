"""Multi-agent system covering all six Track-2 example applications.

1) Personal productivity assistant
2) Enterprise copiloting
3) Workflow automation agent
4) Local RAG knowledge assistant
5) Developer productivity agent
6) Multi-agent orchestration (this module)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.agent.agent import AgentResult, PrivateAgent
from src.agent.domain_packs import detect_pack, list_packs
from src.agent.planner import build_task_plan, detect_intent
from src.agent.task_executor import execute_practical_task
from src.agent.tools import ToolRegistry
from src.agent.workflow import list_workflows, match_workflow, run_workflow
from src.apps.modes import get_app_mode, list_app_modes
from src.privacy.guard import is_exfiltration_request, privacy_block_message


@dataclass
class OrchestratedResult(AgentResult):
    route: str = "general"
    plan: list[str] = field(default_factory=list)
    specialist: str = "PrivateAgent"
    app_mode: str = "multi"


class MultiAgentOrchestrator:
    """Routes requests to specialist agents for the six application modes."""

    def __init__(self, agent: PrivateAgent, tools: ToolRegistry) -> None:
        self.agent = agent
        self.tools = tools

    def _auto_route(self, user_query: str) -> str:
        from src.agent.workflow_builder import wants_build, wants_export

        if any(k in user_query for k in ["图文", "解析图片", "识别图片", "OCR", "读图", "这张图"]):
            return "vision"
        if wants_build(user_query) or wants_export(user_query):
            return "workflow"
        wf_id = match_workflow(user_query)
        if wf_id or any(k in user_query for k in ["工作流", "自动化流程"]):
            return "workflow"
        if any(k in user_query for k in ["执行任务", "帮我完成", "生成任务报告"]):
            return "task"
        intent = detect_intent(user_query)
        if intent == "memory":
            return "productivity"
        if intent in {"rag", "general", "developer", "skill", "workflow"}:
            # Map enterprise-ish queries
            if any(k in user_query for k in ["副驾驶", "合规", "发到微信", "涉密", "企业"]):
                return "enterprise"
            return intent
        return "rag"

    def run(self, user_query: str, mode: str | None = None) -> OrchestratedResult:
        """mode: chat|productivity|enterprise|workflow|rag|developer|multi|None(auto)."""
        plan = build_task_plan(user_query)
        forced = (mode or "").strip().lower()
        if forced in {"chat", "default", "对话"}:
            return self._run_chat(user_query, plan)
        if forced in {"vision", "图文", "图文解析", "ocr"}:
            return self._run_vision(user_query, plan)
        if forced in {"", "multi", "auto", "none"}:
            # multi-agent local config from requirement
            if any(k in user_query for k in ["多代理", "路由", "编排", "自动分流"]):
                configured = self._maybe_app_config(
                    user_query, "multi", plan, "MultiAgentOrchestrator"
                )
                if configured:
                    return configured
            route = self._auto_route(user_query)
            app_mode = "multi"
        else:
            route = self._mode_to_route(forced)
            app_mode = forced

        # Global privacy gate for enterprise-sensitive asks
        if is_exfiltration_request(user_query):
            msg = privacy_block_message()
            self.agent.memory.append_history("user", user_query)
            self.agent.memory.append_history("assistant", msg)
            return OrchestratedResult(
                answer=msg,
                used_tools=["privacy_guard", "orchestrator:enterprise"],
                route="enterprise",
                plan=plan,
                specialist="EnterpriseCopilot",
                app_mode="enterprise",
                pack="security",
            )

        if route == "workflow":
            return self._run_workflow(user_query, plan, app_mode)
        if route == "vision":
            return self._run_vision(user_query, plan)
        if route == "productivity":
            return self._run_productivity(user_query, plan, app_mode)
        if route == "enterprise":
            return self._run_enterprise(user_query, plan, app_mode)
        if route == "developer":
            return self._run_developer(user_query, plan, app_mode)
        if route == "skill":
            return self._run_skill(user_query, plan, app_mode)
        if route == "task":
            return self._run_task(user_query, plan, app_mode)
        # rag / general
        return self._run_rag(user_query, plan, app_mode, route=route)

    def _mode_to_route(self, mode: str) -> str:
        return {
            "chat": "chat",
            "vision": "vision",
            "productivity": "productivity",
            "enterprise": "enterprise",
            "workflow": "workflow",
            "rag": "rag",
            "developer": "developer",
            "multi": "rag",
        }.get(mode, "rag")

    def _run_chat(self, user_query: str, plan: list[str]) -> OrchestratedResult:
        result = self.agent.chat(user_query)
        return self._wrap(
            result,
            used=["orchestrator:chat"] + list(result.used_tools),
            route="chat",
            plan=plan,
            specialist="ChatAssistant",
            app_mode="chat",
        )

    def _run_vision(self, user_query: str, plan: list[str]) -> OrchestratedResult:
        """Parse latest/named image then answer with OCR text as context."""
        name = ""
        for token in user_query.replace("，", " ").replace(",", " ").split():
            if any(token.lower().endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff")):
                name = token
                break
        args = {"name": name} if name else {}
        ocr = self.tools.run("parse_image", args).output
        used = ["orchestrator:vision", "parse_image"]
        enriched = (
            f"{user_query}\n\n[image_ocr]\n{ocr}\n\n"
            "请基于以上本地 OCR 结果，用**一段通顺中文**回答（不要罗列引擎名、坐标、尺寸等技术字段）。\n"
            "写法参考：「这是一张××的照片/证件，上面有××信息：……」\n"
            "要求：说明这是什么图，再概括关键文字信息；不要编造 OCR 中没有的内容；"
            "若文字不清请直接说明。"
        )
        result = self.agent.chat(enriched)
        return self._wrap(
            result,
            answer=result.answer,
            used=used + list(result.used_tools),
            route="vision",
            plan=plan,
            specialist="VisionParseAgent",
            app_mode="vision",
        )

    def _wrap(
        self,
        result: AgentResult | None,
        *,
        answer: str | None = None,
        used: list[str],
        route: str,
        plan: list[str],
        specialist: str,
        app_mode: str,
        steps=None,
        pack: str | None = None,
    ) -> OrchestratedResult:
        return OrchestratedResult(
            answer=answer if answer is not None else (result.answer if result else ""),
            steps=steps if steps is not None else (result.steps if result else []),
            used_tools=used,
            route=route,
            plan=plan,
            specialist=specialist,
            app_mode=app_mode,
            pack=pack if pack is not None else (result.pack if result else None),
        )

    def _run_workflow(self, user_query: str, plan: list[str], app_mode: str) -> OrchestratedResult:
        from src.agent.workflow_builder import (
            build_and_summarize,
            parse_export_id,
            wants_build,
            wants_export,
        )
        from src.agent.workflow_export import export_all_formats_text

        used: list[str] = ["orchestrator:workflow"]
        if wants_build(user_query):
            llm = getattr(self.agent, "llm", None)
            answer = build_and_summarize(user_query, llm=llm)
            used += ["build_workflow", "export_workflow"]
            self.agent.memory.append_history("user", user_query)
            self.agent.memory.append_history("assistant", answer)
            return self._wrap(
                None,
                answer=answer,
                used=used,
                route="workflow",
                plan=plan,
                specialist="WorkflowAutomationAgent",
                app_mode=app_mode if app_mode != "multi" else "workflow",
            )
        if wants_export(user_query):
            wid = parse_export_id(user_query) or match_workflow(user_query) or "leave_request"
            answer = export_all_formats_text(wid)
            used += ["export_workflow", f"workflow:{wid}"]
            self.agent.memory.append_history("user", user_query)
            self.agent.memory.append_history("assistant", answer)
            return self._wrap(
                None,
                answer=answer,
                used=used,
                route="workflow",
                plan=plan,
                specialist="WorkflowAutomationAgent",
                app_mode=app_mode if app_mode != "multi" else "workflow",
            )

        wf_id = match_workflow(user_query) or "leave_request"
        wf = run_workflow(self.tools, wf_id)
        used += [f"workflow:{wf_id}"] + [s.name for s in wf.steps]
        self.agent.memory.append_history("user", user_query)
        self.agent.memory.append_history("assistant", wf.summary)
        return self._wrap(
            None,
            answer=wf.summary,
            used=used,
            route="workflow",
            plan=plan,
            specialist="WorkflowAutomationAgent",
            app_mode=app_mode if app_mode != "multi" else "workflow",
        )

    def _maybe_app_config(self, user_query: str, app: str, plan: list[str], specialist: str) -> OrchestratedResult | None:
        from src.apps.app_builder import build_for_app, wants_app_config

        if not wants_app_config(user_query):
            return None
        # Avoid treating normal questions as config unless explicit
        if not any(k in user_query for k in ["配置", "生成配置", "自动配置", "setup", "configure", "初始化", "搭建"]):
            return None
        result = build_for_app(app, user_query)
        self.agent.memory.append_history("user", user_query)
        self.agent.memory.append_history("assistant", result.summary)
        return self._wrap(
            None,
            answer=result.summary,
            used=[f"orchestrator:{app}", "build_app_config"],
            route=app,
            plan=plan,
            specialist=specialist,
            app_mode=app,
        )

    def _run_productivity(self, user_query: str, plan: list[str], app_mode: str) -> OrchestratedResult:
        configured = self._maybe_app_config(user_query, "productivity", plan, "PersonalProductivityAgent")
        if configured:
            return configured
        # Explicit memory ops for practical productivity
        if any(k in user_query for k in ["记住", "备忘", "笔记"]):
            note = user_query
            for prefix in ("记住", "备忘", "笔记", "：", ":"):
                note = note.replace(prefix, " ")
            note = note.strip() or user_query
            if "喜欢" in user_query or "偏好" in user_query:
                self.tools.run("save_fact", {"fact": note})
                used_pre = ["save_fact"]
            else:
                self.tools.run("write_note", {"note": note})
                used_pre = ["write_note"]
            recalled = self.tools.run("recall_memory", {}).output
            result = self.agent.run(user_query)
            answer = f"{result.answer}\n\n——\n已写入本地记忆。当前记忆摘要：\n{recalled[:600]}"
            return self._wrap(
                result,
                answer=answer,
                used=["orchestrator:productivity"] + used_pre + ["recall_memory"] + list(result.used_tools),
                route="productivity",
                plan=plan,
                specialist="PersonalProductivityAgent",
                app_mode=app_mode if app_mode != "multi" else "productivity",
            )

        recalled = self.tools.run("recall_memory", {}).output
        result = self.agent.run(user_query)
        answer = result.answer
        if any(k in user_query for k in ["回忆", "偏好", "我的笔记"]):
            answer = f"{answer}\n\n（本地记忆）\n{recalled[:800]}"
        return self._wrap(
            result,
            answer=answer,
            used=["orchestrator:productivity", "recall_memory"] + list(result.used_tools),
            route="productivity",
            plan=plan,
            specialist="PersonalProductivityAgent",
            app_mode=app_mode if app_mode != "multi" else "productivity",
        )

    def _run_enterprise(self, user_query: str, plan: list[str], app_mode: str) -> OrchestratedResult:
        configured = self._maybe_app_config(user_query, "enterprise", plan, "EnterpriseCopilot")
        if configured:
            return configured
        pack = detect_pack(user_query)
        # Force security grounding prompt into agent via query annotation
        enriched = (
            user_query
            + "\n\n[enterprise_copilot]\n"
            + "以企业副驾驶身份回答：给出可执行步骤、责任角色、风险提示；严禁建议外发机密到公网。"
        )
        if pack:
            enriched += f"\n[domain_pack]={pack}"
        result = self.agent.run(enriched)
        footer = f"\n\n——\n企业副驾驶 · 领域包: {pack or 'auto'}"
        return self._wrap(
            result,
            answer=result.answer + footer,
            used=["orchestrator:enterprise"] + list(result.used_tools),
            route="enterprise",
            plan=plan,
            specialist="EnterpriseCopilot",
            app_mode=app_mode if app_mode != "multi" else "enterprise",
            pack=pack or result.pack,
        )

    def _run_rag(self, user_query: str, plan: list[str], app_mode: str, route: str = "rag") -> OrchestratedResult:
        if route == "rag":
            configured = self._maybe_app_config(user_query, "rag", plan, "RAGKnowledgeAssistant")
            if configured:
                return configured
        result = self.agent.run(user_query)
        specialist = "RAGKnowledgeAssistant" if route == "rag" else "PrivateAgent"
        return self._wrap(
            result,
            used=[f"orchestrator:{route}"] + list(result.used_tools),
            route=route,
            plan=plan,
            specialist=specialist,
            app_mode=app_mode if app_mode != "multi" else "rag",
        )

    def _run_developer(self, user_query: str, plan: list[str], app_mode: str) -> OrchestratedResult:
        configured = self._maybe_app_config(user_query, "developer", plan, "DeveloperProductivityAgent")
        if configured:
            return configured
        # Skill run by id mention
        if "scaffold_" in user_query or "运行技能" in user_query:
            return self._run_skill(user_query, plan, app_mode)

        files = self.tools.run("list_files", {}).output
        stats = self.tools.run("kb_stats", {}).output
        skills = self.tools.run("list_skills", {}).output
        enriched = (
            user_query
            + f"\n\n[developer_context]\nfiles={files}\n{stats}\n"
            + "可用技能（可生成真实项目）：\n"
            + skills
            + "\n结合 ROCm/本地推理与仓库约定回答。"
        )
        result = self.agent.run(enriched)
        return self._wrap(
            result,
            used=["orchestrator:developer", "list_files", "kb_stats", "list_skills"] + list(result.used_tools),
            route="developer",
            plan=plan,
            specialist="DeveloperProductivityAgent",
            app_mode=app_mode if app_mode != "multi" else "developer",
        )

    def _run_skill(self, user_query: str, plan: list[str], app_mode: str) -> OrchestratedResult:
        listed = self.tools.run("list_skills", {}).output
        skill_id = ""
        for line in listed.splitlines():
            if line.startswith("- ") and ":" in line:
                sid = line[2:].split(":", 1)[0].strip()
                if sid and sid in user_query:
                    skill_id = sid
                    break
        if skill_id:
            out = self.tools.run("run_skill", {"skill_id": skill_id}).output
            used = ["orchestrator:developer", "run_skill", skill_id]
        else:
            out = "请指定技能 ID，或在 Notebook 技能下拉框运行。\n" + listed
            used = ["orchestrator:developer", "list_skills"]
        self.agent.memory.append_history("user", user_query)
        self.agent.memory.append_history("assistant", out)
        return self._wrap(
            None,
            answer=out,
            used=used,
            route="developer",
            plan=plan,
            specialist="DeveloperProductivityAgent",
            app_mode=app_mode if app_mode != "multi" else "developer",
        )

    def _run_task(self, user_query: str, plan: list[str], app_mode: str) -> OrchestratedResult:
        exe = execute_practical_task(self.tools, user_query)
        self.agent.memory.append_history("user", user_query)
        self.agent.memory.append_history("assistant", exe.deliverable)
        return self._wrap(
            None,
            answer=exe.deliverable,
            used=["orchestrator:task"] + exe.actions,
            route="task",
            plan=exe.plan or plan,
            specialist="TaskExecutor",
            app_mode=app_mode,
        )

    def help_text(self) -> str:
        return "\n\n".join(
            [
                list_app_modes(),
                "Routes: chat | productivity | enterprise | workflow | rag | developer | multi | task",
                list_workflows(),
                list_packs(),
            ]
        )
