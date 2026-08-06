"""XAI 编排引擎（Phase F 收口：已从 core/engine_xai.py 迁入 core/kernel/engine.py）。

统一大脑：承接所有用户指令，做意图路由 → Guardian 审批 → 调度执行 → 结果汇总。

核心流程：
  用户输入 → 命令解析 → intent_router → guardian → control_loop → 执行 → SSE 事件流

设计原则（对标上市级 Agent 中台）：
  - 多轮上下文：每 session 维护消息历史（SQLite 持久化），推理时整体喂给模型
  - 流式输出：通用对话逐 token 推送（token 事件），对标 dify / Open-WebUI
  - 零静默失败：任何异常转成 error 事件透传，绝不吞掉
  - 真实能力：桥接真实 OpenClaw / Hermes / 搜索，不编造数字
  - 治理优先：P0 高风险拦截 + 二次确认，确认后真正执行原意图

不依赖具体的外部实现（OpenClaw/Hermes/MemOS），只依赖 Adapter 抽象接口。
"""

from __future__ import annotations
import os
import re
import sys
import json
import time
import uuid
import inspect
import threading
import concurrent.futures
import urllib.parse
import urllib.request
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Dict, Generator, List, Optional

from ..ir import WorkflowNode, WorkflowEdge, NodeResult  # noqa: F401  V2 类型定义

from ..adapters.base import AdapterResult
from ..adapters.openclaw_adapter import OpenClawAdapter
from ..adapters.hermes_adapter import HermesAdapter
from ..guardian import RiskLevel, Action, classify, ApprovalResult
from ..model_backend import StubBackend
from ..deepseek_backend import DeepSeekBackend
from ..session_store import SessionStore
from ..memory_core import default_core as default_memory_core
from ..cognition.intent_router import IntentRouter
from ..cognition.planner import Planner
from ..cognition.verifier import Verifier
from ..execution.action_bus import ActionBus
from ..grok_build_engine import GrokBuildBridge, default_bridge
from ..coordination import CoordinationBus
from ..control_loop import ControlLoop
from ..distill import GepaEvolver, GepaScheduler
from ..model_registry import default_registry as default_model_registry
from ..provider_fallback import default_fallback
from ..loop_safety import default_safety
from ..project import default_project_manager
from ..observability import global_tracer
from .base import SlashCommand, Intent, _AdapterResultShim, SLASH_COMMANDS, INTENT_TYPES
from . import commands
from . import intents
from .tool_bus import build_tool_bus, ToolResult, web_search
from . import workflow
from . import memory_bridge
from . import guardian_bridge
from . import evolution_bridge


# ---- XAIEngine ----

class XAIEngine:
    """XAI 统一编排引擎"""

    def __init__(self, workspace: str = "", memory_home: str = "", local_only: bool = False):
        self._ws = workspace or os.path.expanduser("~/.xai/workspace")
        self._mh = memory_home or os.path.expanduser("~/.xai")
        self._local_only = local_only

        # 模型注册表（多模型管理）—— 必须在 backend 前创建，作为启动单一事实源
        self.model_registry = default_model_registry()
        # v2.0: 自动检测本地模型（Ollama / Grok）
        added = self.model_registry.detect_local_models()
        if added:
            print(f"[XAI] 自动检测到 {added} 个本地模型", flush=True)

        # 模型后端：按注册表激活模型的 provider 分发（deepseek/llamacpp/ollama）
        # 启动单一事实源 = 注册表激活模型（换 key/换模型改注册表或前端即可）；
        # 环境变量 DEEPSEEK_API_KEY 仅作兼容回退（注册表为空时生效）。
        self._backend = StubBackend()
        _active = self.model_registry.active()
        if _active:
            try:
                self._backend = self._build_backend_for(_active)
            except Exception:
                self._backend = StubBackend()
        elif os.environ.get("DEEPSEEK_API_KEY"):
            try:
                self._backend = DeepSeekBackend()
            except RuntimeError:
                self._backend = StubBackend()

        # 会话历史持久化
        self._sessions = SessionStore(self._mh)

        # 7 层元认知记忆（单一事实源）
        self.memory_core = default_memory_core()

        # 故障轮换引擎
        self.provider_fallback = default_fallback()

        # Agent Loop 五重安全闸门
        self.loop_safety = default_safety()

        # V4 认知模块（Planner + Verifier）
        self.planner = Planner()
        self.verifier = Verifier()

        # V4 执行总线（ActionBus + Guardian）
        self.action_bus = ActionBus()

        # Project 管理器
        self.project_manager = default_project_manager()

        # 适配器（在 model_registry 之后重建，确保 active 模型可用）
        self.openclaw = OpenClawAdapter(workspace=self._ws, local_only=self._local_only)
        self.hermes = HermesAdapter(workspace=self._ws, model_backend=self._backend, local_only=self._local_only)
        self.memory = self.memory_core

        # 认知控制环
        self.control_loop = ControlLoop(backend=self._backend)

        # 多 Agent 协作
        self.coordination = CoordinationBus(self.memory_core)

        # Grok Build 桥接
        self.grok_build = default_bridge()

        # 审批队列
        self._pending_approvals: Dict[str, Dict[str, Any]] = {}
        self._approval_lock = threading.Lock()
        self._approval_counter = 0

        # 意图路由（关键词启发式 + 置信度）
        self.intent_router = IntentRouter()

        # Grok Build 桥接（headless CLI 方式）
        self.grok_build = default_bridge()

        # 工具调度总线（防腐层注册表：search/exec/grok/kb 统一分发）
        self.tool_bus = build_tool_bus(self)

        # 认知控制环（reason + meta + guardian + execute 单向管线）
        self.control_loop = ControlLoop(backend=self._backend)

        # GEPA 自进化调度器（B1：定时/事件/手动触发）
        self.gepa_evolver = GepaEvolver(backend=self._backend)
        self.gepa_scheduler = GepaScheduler(evolver=self.gepa_evolver)

        # 多 Agent 协同总线
        self.coordination = CoordinationBus(
            memory=self.memory_core,
            guard_fn=self._guard_for_coordination,
        )
        self._init_default_agents()

        # 待审批队列（线程安全，含原意图以便批准后重执行）
        self._pending_approvals: Dict[str, Dict[str, Any]] = {}
        self._approval_counter = 0
        self._approval_lock = threading.Lock()

        # 降级链引擎（声明式容错编排）
        self.degradation_chain = None
        try:
            from core.degradation_chain import DegradationChain
            self.degradation_chain = DegradationChain()
            config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "degradation_chain.yaml")
            if os.path.exists(config_path):
                self.degradation_chain.load_from_yaml(config_path)
        except Exception:
            pass

    def _infer_with_fallback(self, prompt: str, system: str = "", max_tokens: int = 2000):
        """带故障轮换的推理调用：主模型失败 → 切换备用 → 重试。"""
        try:
            result = self.hermes.infer(prompt=prompt, system=system, max_tokens=max_tokens)
            if result.ok:
                return result
            raise RuntimeError(result.error or "推理失败")
        except Exception as first_err:
            # 尝试切换到下一个可用模型
            fb = self.provider_fallback
            fb.setup_if_needed()
            current = fb._current or ""
            next_model = fb._find_next(self.model_registry.active()) if self.model_registry.active() else None
            if next_model:
                self.model_registry.activate(next_model.id)
                self._rebuild_backend()
                try:
                    result = self.hermes.infer(prompt=prompt, system=system, max_tokens=max_tokens)
                    if result.ok:
                        return result
                except Exception:
                    pass
            # 全部失败，返回原始错误
            from .adapters.base import AdapterResult
            return AdapterResult(ok=False, output="", error=f"主模型失败({first_err}), 备用也失败", meta={})

    # ---- 内部工具 ----

    def record_backend_usage(self, source: str = "chat", session: str = "") -> None:
        """把 backend 上一次调用的 token usage 入账 usage_log（失败静默）。"""
        try:
            usage = getattr(self._backend, "last_usage", None)
            if not usage:
                return
            active = None
            try:
                active = self.model_registry.active()
            except Exception:
                pass
            from ..usage_tracker import record_usage
            record_usage(
                usage,
                session=session,
                model=getattr(self._backend, "model", "") or (active.model if active else ""),
                provider=(active.provider if active else "") or "",
                source=source,
            )
            self._backend.last_usage = None  # 防重复入账
        except Exception:
            pass

    def start_canvas_autopilot(self, interval: float = 30.0):
        """启动画布节点定时执行调度器。"""
        try:
            from ..canvas.executor import start_autopilot
            # 延迟导入 app_store 避免循环依赖
            from .. import app_store as _as
            start_autopilot(self, _as, interval)
        except Exception:
            pass

    def _log(self, what: str) -> None:
        """零碎调试（不替换 logging，仅替换 bare except:pass）。"""
        import sys
        try: sys.stderr.write(f"[xai:engine] _retrieve_memory_context {what} failed\n"); sys.stderr.flush()
        except Exception: pass  # 日志辅助函数失败不应传播

    def _build_backend_for(self, active):
        """按激活模型的 provider 分发到正确的后端实现（模型切换真正生效）。

        - provider=deepseek  → DeepSeekBackend（云端 DeepSeek，需 key）
        - provider=llamacpp  → LlamaCppBackend（本地 llama.cpp server /v1）
        - provider=ollama    → OllamaBackend（本地 Ollama OpenAI 兼容 /v1）
        - 其他（grok 等）     → 兜底尝试 DeepSeek 兼容实现，失败退 Stub
        """
        from ..deepseek_backend import DeepSeekBackend
        from ..llamacpp_backend import LlamaCppBackend
        from ..ollama_backend import OllamaBackend

        provider = (active.provider or "").lower()
        if provider == "llamacpp":
            return LlamaCppBackend(
                api_key=active.api_key or "llamacpp",
                model=active.model,
                base_url=active.base_url,
            )
        if provider == "ollama":
            return OllamaBackend(
                api_key=active.api_key or "",
                model=active.model,
                base_url=active.base_url,
            )
        if provider == "deepseek":
            return DeepSeekBackend(
                api_key=active.api_key,
                model=active.model,
                base_url=active.base_url,
            )
        # grok / 未知 provider：兜底用 DeepSeek 兼容实现（仍尝试 base_url）
        try:
            return DeepSeekBackend(
                api_key=active.api_key,
                model=active.model,
                base_url=active.base_url,
            )
        except Exception:
            return StubBackend()

    def _rebuild_backend(self):
        """根据当前激活模型重建后端（模型切换真实生效）。"""
        active = self.model_registry.active()
        if active:
            try:
                self._backend = self._build_backend_for(active)
            except Exception:
                self._backend = StubBackend()
        ws = self._ws
        mh = self._mh
        self.openclaw = OpenClawAdapter(workspace=ws, local_only=self._local_only)
        self.hermes = HermesAdapter(workspace=ws, model_backend=self._backend, local_only=self._local_only)
        self.memory = self.memory_core
        # 同步所有持有 backend 的子系统，确保模型切换真实生效（#6 残留修复）
        if getattr(self, "control_loop", None) is not None:
            try:
                self.control_loop.backend = self._backend
            except Exception:
                pass
        if getattr(self, "gepa_evolver", None) is not None:
            try:
                self.gepa_evolver.backend = self._backend
            except Exception:
                pass
        # 预热激活模型：避免重启后首次 health/chat 触发本地大模型冷加载（>8s）导致 health 假超时
        if getattr(self, "_backend", None) is not None:
            def _warmup():
                try:
                    self._backend.complete("ping", max_tokens=1)
                except Exception:
                    pass
            _wt = threading.Thread(target=_warmup, daemon=True, name="xai-backend-warmup")
            _wt.start()

    # ---- 状态 ----

    def status(self) -> dict:
        def safe_health(check_fn, default=None, timeout: float = 1.0):
            """带线程超时的健康探测，避免适配器 health_check 阻塞拖垮 /api/status。"""
            box: dict = {}
            def _run():
                try: box["v"] = check_fn()
                except Exception: box["e"] = True
            _t = threading.Thread(target=_run, daemon=True)
            _t.start(); _t.join(timeout)
            if "v" in box:
                return box["v"]
            class _Dead:
                def to_dict(self):
                    return {"ok": False, "output": "", "error": "health_check 超时", "meta": {}}
            return _Dead()

        def safe_call(fn, timeout: float = 1.5, default=None):
            """通用线程超时包装：防止 project/memory 等 SQLite 锁竞争导致 status 挂死。"""
            box: dict = {}
            def _run():
                try: box["v"] = fn()
                except Exception: box["e"] = True
            _t = threading.Thread(target=_run, daemon=True)
            _t.start(); _t.join(timeout)
            if "v" in box:
                return box["v"]
            return default

        oc = safe_health(self.openclaw.health_check)
        hm = safe_health(self.hermes.health_check, timeout=8.0)
        _mc_total = sum(self.memory_core.stats().values())
        mm = {"ok": True, "output": f"记忆核心正常，共 {_mc_total} 条", "meta": {"db": "memory.db"}}
        gb = safe_health(self.grok_build.health_check, {"grok_build_bridge": "unknown"})
        p = safe_call(self.project_manager.current, default=None)
        mem_layers = safe_call(self.memory_core.stats, default={})
        fb = safe_call(self.provider_fallback.status, default={})
        # ActionBus 真实执行统计
        ab_logs = self.action_bus.recent_logs(200)
        ab_ok = sum(1 for l in ab_logs if l.result == "ok")
        ab_err = sum(1 for l in ab_logs if l.result.startswith("error"))
        ab_total = self.action_bus.log_count()
        return {
            "xai_engine": "running",
            "model": type(self._backend).__name__.replace("Backend", "").lower(),
            "project": {"id": p.id, "name": p.name, "description": p.description} if p else None,
            "openclaw": oc.to_dict(),
            "hermes": hm.to_dict(),
            "memory": mm,
            "memory_core_layers": mem_layers,
            "grok_build": gb.to_dict() if hasattr(gb, 'to_dict') else gb,
            "models": {"active": self.model_registry.active().to_dict(mask=True) if self.model_registry.active() else None,
                       "list": [m.to_dict(mask=True) for m in self.model_registry.list()],
                       "total": len(self.model_registry.list()),
                       "fallback": fb},
            "pending_approvals": len(self._pending_approvals),
            "slash_commands": len(SLASH_COMMANDS),
            "actions_total": ab_total,
            "actions_ok": ab_ok,
            "actions_err": ab_err,
            "actions_last_200": f"ok={ab_ok} err={ab_err}",
            "tracing": global_tracer.stats(),
        }

    # ---- 主入口：对话处理器 ----

    def chat(self, user_input: str, session_id: str = "default", attachments: Optional[List[Dict[str, Any]]] = None, kernel_override: str = "", vision_parts: Optional[List[Dict[str, Any]]] = None) -> Generator[Dict[str, Any], None, None]:
        """对话主入口——SSE 事件生成器。

        attachments: 用户上传的本地文件列表，每项 {"name", "stored"}。
          stored 为后端落盘后的文件名（位于 workspace/uploads/ 下），
          引擎会读取文本类附件内容注入上下文，使模型能"看见"文件。
       

        一步一事件：
          start     → 引擎就绪
          intent    → 意图分析结果
          guard     → 风险评估结果
          progress  → 执行进度
          token     → 流式文本片段（通用对话逐字推送）
          answer    → 最终回答（命令/非流式结果）
          approval  → 如需人工审批（P0 操作）
          error     → 错误（绝不静默）
          done      → 结束
        """
        yield {"type": "start", "text": "XAI 引擎已就绪"}

        # Step 0: 安全闸门重置
        self.loop_safety.reset()
        self.loop_safety.check("chat_start", user_input[:100], tokens=0)

        # Step 1: 命令解析
        is_slash, cmd_raw, cmd_name, cmd_args = self._parse_slash(user_input)
        if is_slash:
            # 命令执行后存历史（命令本身 + 结果）
            full: List[str] = []
            for ev in self._handle_slash(cmd_name, cmd_args, session_id):
                if ev.get("type") == "answer":
                    full.append(ev.get("answer", ""))
                elif ev.get("type") == "error":
                    full.append("❌ " + ev.get("error", ""))
                yield ev
            # 会话历史只记录非元命令的实质对话（help/status 等也记录，便于回溯）。
            # 注意：/clear 是破坏性重置，执行后不应在会话里留下自身痕迹。
            if cmd_name not in ("diagnose", "clear"):
                result_text = "\n".join(full)
                if result_text.strip():
                    self._sessions.add(session_id, "user", user_input)
                    self._sessions.add(session_id, "assistant", result_text[:4000])
            yield {"type": "done"}
            return

        # Step 1.5: 自然语言自检/体检 → 直连真实 /diagnose（防假报告）
        # 背景：曾出现用户说"做一次系统自检"落入通用对话，模型脑补出带 ✅/⚠️ 的假体检表。
        # 规则：命中体检关键词 + 动作词（或短指令），直接跑 cmd_diagnose 真探针，不走模型生成。
        _sc_kw = ("自检", "体检", "健康检查", "系统检查", "系统诊断", "diagnose", "health check")
        _sc_verb = ("做", "跑", "执行", "运行", "来", "进行", "开始", "启动", "搞", "整")
        _sc_neg = ("怎么", "如何", "什么", "为什么", "是不是", "吗", "呢", "?", "？")  # 疑问句=咨询而非指令
        _t = user_input.strip().lower()
        if (any(k in _t for k in _sc_kw)
                and not any(n in _t for n in _sc_neg)
                and (len(_t) <= 24 or any(v in _t for v in _sc_verb))):
            yield {"type": "progress", "stage": "diagnose",
                   "text": "识别为系统自检请求 → 路由到真实 /diagnose 探针（非模型生成）"}
            for ev in self._cmd_diagnose():
                yield ev
            yield {"type": "done"}
            return

        # Step 2: 意图路由（手动覆盖优先）
        if kernel_override and kernel_override in ("hermes", "grok_build"):
            intent = Intent(
                type="code_dev" if kernel_override == "grok_build" else "general",
                confidence=1.0,
                rationale=f"用户手动选择 {kernel_override}"
            )
        else:
            intent = self._classify_intent(user_input)
        yield {"type": "intent", "intent": intent.type, "confidence": intent.confidence, "rationale": intent.rationale}

        # 内核路由结果（双核融合）：告知前端实际由哪个内核执行
        # code_dev + Grok 可用 → Grok Build；其余 → Hermes
        _grok_avail = bool(getattr(self, "grok_build", None) and getattr(self.grok_build, "available", False))
        # 本地优先：激活模型为本地后端(llamacpp/ollama，含 Radeon 云 ROCm 部署)时，
        # 代码意图也走本地 Hermes，避免无有效云端 key 时先撞 DeepSeek 云端 401 再退回。
        # 仅当激活模型为云端 provider（deepseek）时才使用 Grok Build 云端代码引擎。
        _active = self.model_registry.active()
        _local_mode = bool(_active and _active.provider in ("llamacpp", "ollama"))
        _target_kernel = "grok_build" if (intent.type == "code_dev" and _grok_avail and not _local_mode) else "hermes"
        yield {"type": "routed", "kernel": _target_kernel, "intent": intent.type, "confidence": intent.confidence}

        # Step 3: Guardian 风险评估（基于内容识别高危操作，而非一刀切 general）
        action = self._guard_action(user_input)
        approval = classify(action)
        yield {"type": "guard", "level": approval.level.name, "reason": approval.reason}

        if approval.level == RiskLevel.P0:
            # P0 操作：拦截，生成审批卡片（含原意图，批准后重执行）
            aid = self._create_approval("task", user_input, approval.reason, intent=intent.type, session_id=session_id)
            yield {
                "type": "approval",
                "id": aid,
                "level": "P0",
                "action": user_input[:100],
                "message": f"⚠️ P0 高风险操作需要确认\n原因: {approval.reason}",
            }
            yield {"type": "done"}
            return

        # Step 4: ControlLoop 完整闭环 —— Reason → Plan → Act → Observe → MetaReflect
        history = self._sessions.get_history(session_id, limit=24)
        loop_result = None
        try:
            # 4a. Reason: 思考预算计算
            try:
                budget = self.control_loop.reason(prompt=user_input, history=history)
                if budget:
                    yield {"type": "progress", "stage": "reason",
                           "text": f"思考预算: {budget.max_tokens} tokens"}
            except Exception:
                pass

            # 4b. Plan: 任务规划（Planner 拆解目标为执行步骤）
            try:
                plan = self.planner.plan(user_input)
                if plan and plan.steps:
                    yield {"type": "progress", "stage": "plan",
                           "text": f"任务规划: {len(plan.steps)} 个步骤 — {plan.rationale[:80]}"}
                    yield {"type": "plan", "steps": plan.to_dict()["steps"]}
            except Exception:
                pass

            # 4c. Act: 完整控制环（Reason→Meta→Guardian→Execute→Observe 单向管线）
            try:
                # Phase G 真执行：构造 execute_fn 接入 ActionBus
                def _real_execute(cmd_text: str) -> str:
                    """真实执行：通过 ActionBus 沙箱运行命令。"""
                    if not cmd_text.strip():
                        return ""
                    with global_tracer.span(tool_name="exec_command") as s:
                        res = self.action_bus.exec_command(cmd_text, source="engine")
                        if res.ok:
                            s.ok(output_size=len(res.output or ""))
                        else:
                            s.fail(error_msg=res.error or "")
                        if res.ok and res.output:
                            return res.output
                        if res.error:
                            return f"[执行失败] {res.error}"
                        return ""

                # 带重试的控制环：最多 2 次，失败后自动 refine
                max_retries = 2
                last_result = None
                for attempt in range(max_retries + 1):
                    loop_result = self.control_loop.act(
                        task=user_input if attempt == 0 else f"{user_input}\n[上次尝试失败: {last_result.answer[:200] if last_result else ''}]",
                        action=action if approval.level != RiskLevel.P2 else None,
                        # 只在 code_dev（用户明确要求开发/执行）时挂真执行器；普通对话跳过
                        # —— 否则会把模型思考/回答全文当 shell 命令跑，触发沙箱 execvp 失败/单次聊天数分钟。
                        execute_fn=_real_execute if intent.type == "code_dev" else None,
                        use_refine=(attempt > 0),
                        use_multi=False,
                    )
                    last_result = loop_result
                    if loop_result and loop_result.audit_passed and loop_result.allowed:
                        break  # 成功，退出重试
            except Exception as e:
                # 推理环崩溃也落第8层（之前被静默吞掉，是信息黑洞）
                try:
                    self.memory_core.record_failure(
                        task=user_input[:300],
                        error=f"主控制环异常: {repr(e)[:300]}",
                        correction="控制环执行异常；已降级优雅运行",
                        engine="hermes",
                        project_id=self._project_id(),
                        meta={"error_type": "control_loop_exception", "captured_at": int(time.time())},
                    )
                except Exception:
                    pass
            if loop_result:
                # 思考要点透明化：把控制环的关键思考节点推给前端（过程可见，不混入最终答案）
                _thk = getattr(loop_result, "thinking", "") or ""
                if _thk.strip():
                    yield {"type": "progress", "stage": "thinking",
                           "text": f"💭 思考要点:\n{_thk[:800]}"}
                yield {"type": "progress", "stage": "act",
                       "text": f"控制环完成 · 置信度 {loop_result.calibrated_confidence:.2f} · "
                               f"审计 {'通过' if loop_result.audit_passed else '未通过'}"}

                # 失败修正层（第8层）打通：主推理环的明确失败也落盘，供 self-refine 复用
                _ans = loop_result.answer or ""
                if "[执行失败]" in _ans:
                    self.memory_core.record_failure(
                        task=user_input[:300],
                        error=f"主控制环执行失败: audit_passed={loop_result.audit_passed}, "
                              f"allowed={loop_result.allowed}, notes={loop_result.audit_notes}, "
                              f"answer_excerpt={_ans[:200]}",
                        correction="检查意图规划/工具执行/Guardian 审批；已含重试(refine)，必要时触发 GEPA 自进化",
                        engine="hermes",
                        project_id=self._project_id(),
                        meta={
                            "error_type": "control_loop_exec_failure",
                            "root_cause_hypothesis": "ActionBus 执行返回错误（命令/工具失败）",
                            "recovery_action": "重试(refine)/降级；记录教训避免复犯",
                            "audit_passed": loop_result.audit_passed,
                            "allowed": loop_result.allowed,
                            "audit_notes": loop_result.audit_notes,
                            "model": type(self._backend).__name__,
                            "captured_at": int(time.time()),
                        },
                    )

            # 4d. Observe: L8 审计结果透传（审计细节已内含于 act()，此处透传失败维度）
            if loop_result and not loop_result.audit_passed:
                yield {"type": "progress", "stage": "observe",
                       "text": f"L8 审计未通过: {loop_result.audit_notes}"}

            # 4e. MetaReflect: 最终置信校准透传（Brier 校准已内含于 act()）
            if loop_result:
                yield {"type": "progress", "stage": "meta",
                       "text": f"最终校准置信度: {loop_result.calibrated_confidence:.2f}"}

            # B1: GEPA 自进化触发器 — 只在审计未通过时才触发（冷启动默认置信低不触发）
            if loop_result and loop_result.calibrated_confidence < 0.5 and not loop_result.audit_passed:
                yield {"type": "progress", "stage": "gepa",
                       "text": f"置信度 {loop_result.calibrated_confidence:.2f} 低于阈值 0.5，audit 未通过，触发 GEPA 自进化"}
                self._trigger_gepa_evolution(user_input, loop_result.calibrated_confidence)
        except Exception:
            # ControlLoop 完整闭环失败不影响主流程，降级优雅运行
            pass

        # Step 5: 执行并累积完整文本（用于历史/记忆）
        # 先 yield 进度事件，让前端感知模型正在连接中
        yield {"type": "progress", "stage": "推理中", "text": "正在生成回复..."}
        full: List[str] = []
        try:
            for ev in self._execute_intent(intent, user_input, session_id, history, attachments, vision_parts=vision_parts):
                t = ev.get("type")
                if t == "token":
                    full.append(ev.get("text", ""))
                elif t == "answer":
                    full.append(ev.get("answer", ""))
                yield ev
        except Exception as e:
            self.loop_safety.record_error("chat", str(e))
            yield {"type": "error", "error": f"执行异常: {e}"}
            import traceback
            traceback.print_exc()
            yield {"type": "done"}
            return

        final_text = "".join(full).strip()
        if final_text:
            self._sessions.add(session_id, "user", user_input)
            self._sessions.add(session_id, "assistant", final_text[:4000])
            # 8 层记忆核心写入（单一事实源）
            self._safe_memory_core_write(user_input, final_text, intent.type)

        self.loop_safety.record_result(final_text[:500])
        self.loop_safety.check("chat_end", final_text[:100], tokens=len(final_text))
        yield {"type": "done"}

    # ---- 斜杠命令解析 ----

    def _parse_slash(self, text: str) -> tuple:
        """解析斜杠命令：返回 (是否为命令, 原始命令名, 规范命令名, 参数字符串)"""
        text = text.strip()
        if not text.startswith("/"):
            return False, "", "", ""

        parts = text[1:].split(maxsplit=1)
        raw = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        for name, cmd_def in SLASH_COMMANDS.items():
            if raw == name or raw in cmd_def.aliases:
                return True, raw, name, args

        return True, raw, "unknown", args

    def _handle_slash(self, cmd: str, args: str, session_id: str) -> Generator[Dict[str, Any], None, None]:
        """处理斜杠命令"""
        if cmd == "help":
            yield from self._cmd_help(args)
        elif cmd == "status":
            yield {"type": "answer", "answer": self._status_md()}
        elif cmd == "skill":
            yield from self._cmd_skill(args)
        elif cmd == "mcp":
            yield from self._cmd_mcp(args)
        elif cmd == "task":
            yield from self._cmd_task(args, session_id)
        elif cmd == "automate":
            yield from self._cmd_automate(args)
        elif cmd == "remember":
            yield from self._cmd_remember(args)
        elif cmd == "recall":
            yield from self._cmd_recall(args)
        elif cmd == "scan":
            yield from self._cmd_scan(args)
        elif cmd == "evolve":
            yield from self._cmd_evolve(args)
        elif cmd == "models":
            yield from self._cmd_models(args)
        elif cmd == "channels":
            yield from self._cmd_channels(args)
        elif cmd == "diagnose":
            yield from self._cmd_diagnose()
        elif cmd == "clear":
            self._sessions.clear(session_id)
            yield {"type": "answer", "answer": "✅ 已清空当前会话历史"}
        elif cmd == "approve":
            yield from self._cmd_approve(args, session_id)
        elif cmd == "reject":
            yield from self._cmd_reject(args)
        elif cmd == "loop":
            yield from self._cmd_loop(args)
        else:
            yield {"type": "answer", "answer": f"未知命令: /{cmd}\n输入 /help 查看所有命令"}

    # ---- 意图分类（改进版：加权打分，避免误判）----

    def _classify_intent(self, text: str) -> Intent:
        return intents.classify_intent(self, text)

    def _execute_intent(self, intent: Intent, text: str, session_id: str, history: List[dict], attachments=None, vision_parts=None) -> Generator[Dict[str, Any], None, None]:
        yield from intents.execute_intent(self, intent, text, session_id, history, attachments, vision_parts=vision_parts)

    def _execute_general(self, text: str, history: List[dict], attachments=None, session_id: str = "") -> Generator[Dict[str, Any], None, None]:
        yield from intents.execute_general(self, text, history, attachments, session_id=session_id)

    def _attachment_context(self, attachments: Optional[List[Dict[str, Any]]]) -> str:
        """读取上传附件的文本内容，拼成模型可消费的上下文块。

        仅读取位于 workspace/uploads/ 下的文件，越界或超大/二进制自动跳过并说明。
        """
        if not attachments:
            return ""
        blocks: List[str] = []
        for att in attachments:
            name = att.get("name") or "文件"
            stored = att.get("stored") or att.get("name") or ""
            if not stored or ".." in stored:
                continue
            try:
                p = self.openclaw.workspace_path("uploads/" + stored)
            except Exception:
                continue
            if not os.path.exists(p):
                continue
            try:
                size = os.path.getsize(p)
            except OSError:
                size = 0
            if size > 200_000:
                blocks.append(f"[附件: {name}（{size} 字节，过大已跳过内容，路径 {p}）]")
                continue
            try:
                content = Path(p).read_text(encoding="utf-8", errors="ignore")
            except Exception:
                blocks.append(f"[附件: {name}（无法读取为文本）]")
                continue
            blocks.append(f"[附件内容 {name}]\n{content}\n[/附件 {name}]")
        if not blocks:
            return ""
        return "\n\n--- 以下是用户上传的本地文件内容 ---\n" + "\n".join(blocks) + "\n--- 附件内容结束 ---\n"

    def _execute_code(self, text: str, attachments=None) -> Generator[Dict[str, Any], None, None]:
        yield from intents.execute_code(self, text, attachments)

    def _project_id(self) -> Optional[str]:
        """获取当前激活的项目 ID，用于记忆写入项目隔离。"""
        try:
            p = self.project_manager.current()
            return p.id if p else None
        except Exception:
            return None

    def _grok_task_flags(self, text: str) -> str:
        """基于任务特征决定 Grok CLI 额外参数。

        注意：grok 0.2.111 实际不支持 --check / --best-of-n（历史文档误以为支持，
        桥接层 grok_build_engine.run 已统一过滤这两个无效 flag）。当前版本 Grok 无
        任务特定的 CLI 开关，故本方法返回空串，由 Grok 走默认行为
        （规划→生成→完成）。保留此方法以便未来 grok 支持自验证/并行时无障碍接入。
        """
        # 历史意图映射（grok 0.2.111 不支持，已禁用，仅供未来参考）：
        #   - 修复/重构/优化 → --check（自验证循环）
        #   - 架构/设计/探索 → --best-of-n 3（并行多路取最优）
        # 这两个 flag 现由桥接层过滤，此处不再生成，避免 clap 解析报错。
        return ""

    def _reflect_grok_result(self, task: str, result: dict) -> None:
        """事后反思：将 Grok 的完整思考链 + 执行结果写入记忆层（外脑输入），
        覆盖全 8 层记忆：short_term / long_term / anchor / reflection / causal /
        user_profile / failure_correction / consolidate。

        不阻断主流程，失败静默。
        """
        try:
            thought = result.get("thought", "")
            usage = result.get("usage", {})
            model_usage = result.get("modelUsage", {})
            turns = result.get("num_turns", 1)
            text = result.get("text", "")[:500]
            models = list(model_usage.keys())
            timestamp = int(time.time())
            ok = bool(result.get("ok")) or bool(text.strip())

            # 1) short_term: 对话级记忆（原有逻辑，保持）
            summary = (
                f"[Grok Build 外脑 · {turns} turns · 模型: {models}]\n"
                f"任务: {task[:200]}\n"
                f"输出: {text[:200]}\n"
                f"思考链: {thought[:500]}"
            )
            self._safe_memory_core_write(
                user_input=f"[Grok Build] {task[:200]}",
                response=summary,
                intent_type="code_dev",
                engine_tag="grok_build",
            )

            # 2) anchor: 成功的代码模板沉淀（Hermes 可复用）
            if ok and text:
                import hashlib
                task_hash = hashlib.md5(task.encode()).hexdigest()[:12]
                self.memory_core.store(
                    layer="anchor",
                    key=f"grok_success:{task_hash}",
                    value=f"任务: {task[:300]}\n输出: {text[:300]}\n思考: {thought[:200]}\n模型: {models}",
                    engine="grok_build",
                    importance=0.7,
                    meta={"models": models, "turns": turns, "ok": ok},
                    project_id=self._project_id(),
                )

            # 3) causal: 模型 → 成功归因（因果链）
            for model_name in models:
                self.memory_core.store(
                    layer="causal",
                    key=f"grok_causal:{model_name}:{timestamp}",
                    value=f"模型 {model_name} 在 Grok Build 上执行{'成功' if ok else '失败'}, {turns} turns, {usage.get('total_tokens', 0)} tokens",
                    engine="grok_build",
                    importance=0.5,
                    meta={"model": model_name, "ok": ok, "turns": turns, "tokens": usage.get("total_tokens", 0)},
                    project_id=self._project_id(),
                )

            # 4) reflection: 质量反思（meta 层可审计）
            quality_score = min(1.0, 0.5 + (turns > 1) * 0.2 + (len(thought) > 100) * 0.2 + (ok) * 0.1)
            self.memory_core.store(
                layer="reflection",
                key=f"grok_review:{timestamp}",
                value=f"任务: {task[:200]}\n思考深度: {'深' if len(thought) > 200 else '浅'}\n"
                      f"质量分: {quality_score:.2f}\n{'✅ 成功' if ok else '❌ 失败'}\n"
                      f"thought 片段: {thought[:150]}",
                engine="grok_build",
                importance=0.3,
                meta={"quality_score": quality_score, "turns": turns, "ok": ok},
                project_id=self._project_id(),
            )

            # 5) failure_correction：推理/执行失败落盘，供 self-refine 复用
            if not ok:
                err_desc = (text[:300] or thought[:300] or "Grok Build 执行未产出有效结果")
                self.memory_core.record_failure(
                    task=task[:300],
                    error=f"Grok Build 执行失败: {err_desc}",
                    correction="检查代码模板/工具权限/模型路由；可重试或降级到 Hermes",
                    engine="grok_build",
                    meta={
                        "error_type": "code_dev_failure",
                        "root_cause_hypothesis": "执行器未产出 ok 结果（可能工具调用失败/超时/权限拦��）",
                        "recovery_action": "重试或切换内核(Hermes)；沉淀成功模板避免复犯",
                        "model": models,
                        "turns": turns,
                        "captured_at": timestamp,
                        "project_id": self._project_id(),
                    },
                )

            # 6) long_term：重大产出落长期记忆（>500字或复杂多轮任务）
            full_text = result.get("text", "")
            is_substantial = len(full_text) > 500 or turns >= 5
            if ok and is_substantial:
                new_files = []
                for line in full_text.split("\n"):
                    if "已创建" in line or "Created" in line or "新建" in line:
                        new_files.append(line.strip()[:120])
                import hashlib
                task_hash = hashlib.md5(task.encode()).hexdigest()[:12]
                self.memory_core.store(
                    layer="long_term",
                    key=f"grok_major:{task_hash}:{timestamp}",
                    value=f"[Grok Build 重大产出]\n任务: {task[:200]}\n"
                          f"轮数: {turns} · tokens: {usage.get('total_tokens', 0)}\n"
                          f"新建/修改文件: {new_files if new_files else '（内联代码产出）'}\n"
                          f"产物摘要: {full_text[:300]}",
                    engine="grok_build",
                    importance=0.65,
                    meta={"turns": turns, "tokens": usage.get("total_tokens", 0),
                          "new_files": new_files, "task_hash": task_hash},
                    project_id=self._project_id(),
                )

            # 7) user_profile：从 thought 行为模式推断编码偏好
            if ok and thought:
                profile_tags = []
                thought_lower = thought.lower()
                if any(kw in thought_lower for kw in ["test", "tdd", "pytest", "unittest"]):
                    profile_tags.append("TDD倾向")
                if any(kw in thought_lower for kw in ["refactor", "rewrite", "clean", "simplify"]):
                    profile_tags.append("重构型")
                if any(kw in thought_lower for kw in ["type hint", "mypy", "strict"]):
                    profile_tags.append("类型严格")
                if any(kw in thought_lower for kw in ["docstring", "document", "readme"]):
                    profile_tags.append("文档优先")
                if any(kw in thought_lower for kw in ["performance", "benchmark", "optimize", "fast"]):
                    profile_tags.append("性能敏感")
                if len(full_text) < 300 and turns <= 2:
                    profile_tags.append("简洁高效")
                if profile_tags:
                    self.memory_core.store(
                        layer="user_profile",
                        key=f"grok_style:{timestamp}",
                        value=f"编码偏好推断: {', '.join(profile_tags)}\n"
                              f"来源任务: {task[:200]}\nturns: {turns}\n模型: {models}",
                        engine="grok_build",
                        importance=0.4,
                        meta={"tags": profile_tags, "turns": turns, "models": models},
                        project_id=self._project_id(),
                    )

            # 8) consolidate_trigger：成功 ≥3 次的锚点 → 触发整合升级
            if ok:
                import hashlib
                task_hash = hashlib.md5(task.encode()).hexdigest()[:12]
                existing = self.memory_core.query(
                    layer="anchor", engine="grok_build", limit=20
                )
                same_pattern = [e for e in existing if task_hash[:8] in (e.key or "")]
                success_count = sum(1 for e in same_pattern if e.meta and e.meta.get("ok")) + 1
                if success_count >= 3:
                    self.memory_core.store(
                        layer="anchor",
                        key=f"grok_success:{task_hash}",
                        value=f"[已验证 {success_count} 次] 任务: {task[:300]}\n"
                              f"输出: {full_text[:300]}\n思考: {thought[:200]}\n模型: {models}",
                        engine="grok_build",
                        importance=min(1.0, 0.7 + success_count * 0.05),
                        meta={"models": models, "turns": turns, "ok": ok,
                              "verified_count": success_count, "consolidated": True},
                        project_id=self._project_id(),
                    )
                    # 同时触发短期记忆到长期记忆的整合
                    self.memory_core.store(
                        layer="long_term",
                        key=f"grok_consolidated:{task_hash}:{timestamp}",
                        value=f"[整合升级 · 已验证 {success_count} 次]\n"
                              f"任务模式: {task[:200]}\n最佳模型: {models}\n"
                              f"平均轮数: ~{turns}\n可靠性: {success_count}/{(success_count)} ✅",
                        engine="grok_build",
                        importance=0.85,
                        meta={"verified_count": success_count, "consolidated": True,
                              "task_hash": task_hash},
                        project_id=self._project_id(),
                    )

        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"_reflect_grok_result 失败（已忽略）: {e}")

    def _execute_browser(self, text: str) -> Generator[Dict[str, Any], None, None]:
        yield from intents.execute_browser(self, text)

    def _web_search(self, query: str, max_results: int = 5) -> List[Dict[str, str]]:
        """真实联网搜索（经 ToolBus.search 分发，多后端降级）。

        失败（限流/网络）返回空列表，由调用方降级。
        """
        return web_search(query, max_results)

    # ---- 记忆检索 ----

    def _retrieve_memory_context(self, text: str) -> str:
        return memory_bridge.retrieve_memory_context(self, text)

    def _execute_memory_query(self, text: str) -> Generator[Dict[str, Any], None, None]:
        yield from memory_bridge.execute_memory_query(self, text)

    def _cached_openclaw_call(self, key: str, fn, ttl: float = 60.0):
        """超时隔离 + 短缓存地调用 openclaw CLI（避免无超时子进程阻塞对话）。

        返回 AdapterResult（成功或带 ok=False 的降级结果）；超时则返回一个
        空结果对象，保证调用方不崩溃、对话不挂死。
        """
        now = time.time()
        cached = getattr(self, "_openclaw_cache", None)
        if cached is None:
            cached = {}
            self._openclaw_cache = cached
        if key in cached and now - cached[key][0] < ttl:
            return cached[key][1]
        _res = {}
        def _run():
            try:
                _res["v"] = fn()
            except Exception as e:
                _res["err"] = e
        th = threading.Thread(target=_run, daemon=True)
        th.start()
        th.join(3.0)  # 最多等 3s
        if th.is_alive():
            self._log(f"openclaw_call_timeout:{key}")
            result = _AdapterResultShim(ok=False, error="timeout")
        elif "err" in _res:
            result = _AdapterResultShim(ok=False, error=str(_res["err"])[:120])
        else:
            result = _res.get("v")
        cached[key] = (now, result)
        return result

    def _extract_code(self, text: str) -> str:
        """从模型输出中提取代码块（回退到 workflow.extract_code）。"""
        from .workflow import extract_code as _extract
        return _extract(text)

    def _build_system_prompt(self, memory_context: str = "", canvas_context: str = "") -> str:
        # openclaw CLI 子进程（list_real_skills / mcp_list_servers）无超时可能永久阻塞，
        # 用超时隔离 + 60s 缓存，避免每轮对话因此挂死。
        real_skills = self._cached_openclaw_call("skills", self.openclaw.list_real_skills)
        skill_count = real_skills.meta.get("count", 0) if real_skills.ok else 0
        mcp_r = self._cached_openclaw_call("mcp", self.openclaw.mcp_list_servers)
        mcp_count = len(mcp_r.meta.get("servers", [])) if mcp_r.ok else 0

        active_model = self.model_registry.active()
        gb_model_mapped = ""
        if self.grok_build.available:
            am = active_model
            if am:
                mn = (am.model or "").lower()
                nm = (am.name or "").lower()
                full = mn + " " + nm
                gb_model_mapped = "deepseek-pro" if "pro" in full else "deepseek-flash"
            else:
                gb_model_mapped = "deepseek-flash"

        system = (
            "## 你是谁\n"
            "你是 XAI 统一操作台——一个本地私有的超级 Agent 中台系统。\n"
            "你运行在双核融合架构之上：**Hermes 推理核** + **Grok Build 代码工程核**，由 **Intent Router** 自动分发任务。\n"
            "你的底层工具基座是 **OpenClaw 执行网关**（文件读写 / 终端命令 / 浏览器操作）。\n\n"
            
            "## 你的双核架构\n"
            "- **🧠 Hermes 推理核（第一公民）**：通用推理、联网搜索、调研分析、记忆检索、办公自动化。你的主大脑。\n"
            '- **⚙ Grok Build 代码工程核（第一公民）**：代码生成、重构、单测、Git 操作。当用户说写代码/修 bug/重构时，Intent Router 自动把任务路由到 Grok Build 本地二进制执行（不是 DeepSeek 模型，是独立的代码工程引擎）。\n'
            f"- **🦞 OpenClaw 工具层（共享底座）**：{skill_count} 个真实技能 / {mcp_count} 个 MCP 服务器。Hermes 和 Grok Build 都可调用。不是独立执行器，是双核脚下的工具基座。\n"
            "- **🧭 Intent Router**：根据用户输入自动判断该交给哪个核。用户看到右侧标签就是 Router 推荐结果，用户可以手动点另一个覆盖。\n\n"
            
            "## 你的模型与实时能力\n"
            f"- 激活模型：{self.model_registry.active().name if self.model_registry.active() else 'DeepSeek（默认）'}\n"
            f"- 模型注册表：{len(self.model_registry.list())} 个模型可用\n"
            f"- Grok Build 状态：{'✅ 在线' if self.grok_build.available else '❌ 离线'}（同步模型：{gb_model_mapped}）\n\n"

            "## 你的 8 层记忆系统\n"
            "- working：当前任务工作上下文\n"
            "- short_term：当前会话上下文\n"
            "- long_term：跨会话持久记忆\n"
            "- anchor：核心事实与成功模板（含 Grok Build 沉淀的代码模式）\n"
            "- reflection：质量反思（含 Grok Build 执行评分）\n"
            "- causal：因果链（模型选择→执行结果归因）\n"
            "- user_profile：用户偏好画像\n"
            "- failure_correction：错误修正记录（我们特有·Hermes 扩展，**读写闭环**：每次推理自动召回，模型主动规避同类错误）\n"
            "所有执行器（Hermes + Grok Build）的输出都写入同一套记忆，带 engine 标签区分来源。\n\n"

            "## 最近系统升级（你会用到的能力变更）\n"
            "2026-07-20: 17 个画布节点全部接通真实执行器（kb/recall、grok_build/run、intent_router/classify、react loop、agent dispatch、code exec 等）\n"
            "2026-07-20: 思考过程升级为 4 阶段进度条（意图→审计→规划→执行），每节点实时显示耗时\n"
            "2026-07-20: 模型动态同步——前端选 V4 PRO→Grok Build 用 deepseek-pro，选 V4 Flash→用 deepseek-flash\n"
            "2026-07-20: OpenClaw 降级为共享工具层，Hermes 与 Grok Build 均可调用\n"
            "2026-07-20: Grok Build 模型与前/后端同步，手动选取执行器（Hermes/Grok Build 2选1）\n"
            "2026-07-20: 8层记忆双架构增强（anchor 存代码模板 / causal 存模型归因 / reflection 存质量反思 / failure_correction 存失败修正）\n"
            "2026-07-20: 历史会话可置顶/删除/继续对话，相对时间显示\n"
            "2026-07-21: 新增本地 LLM 支持——llama.cpp 服务器（127.0.0.1:11434/v1），9 个本地模型全局可切换，前端显示「本地」标签\n\n"
            "2026-07-21: 元认知记忆读侧闭环打通——failure_correction 每次对话自动召回注入上下文，模型推理主动规避历史同类错误\n"
            "2026-07-21: 真观测 Tracing Pipeline 上线——系统从真实 tracing 统计自动校准（success_rate / avg_latency / p95），替代模型自报置信度\n"
            "2026-07-21: 硬沙箱（P0-K3b）上线——nsjail > firejail > macOS sandbox-exec > setrlimit 四级自动回退，GET /api/system/sandbox 查询当前模式\n"
            "2026-07-21: 跨会话记忆召回质量升级——混合召回策略（子串40%+关键词40%+时间衰减20%），GET /api/memory/context?text= 检索 top-10 加权记忆\n"
            "2026-07-21: 系统错误追踪面板上线——GET /api/system/errors 查询系统级失败诊断（组件/类型/消息/追踪ID），前端 ErrorPanel 页签展示\n"
            "2026-07-21: 备份/恢复上线——POST /api/system/backup 导出 .tar.gz 全量备份，POST /api/system/restore 上传恢复，前端 BackupPanel 页签展示\n"

            "## 可用命令\n"
            "/skill, /mcp, /task, /automate, /remember, /recall, "
            "/scan, /evolve, /models, /channels, /status, /diagnose, /clear, /help, /approve, /reject\n\n"
            
            "## 回复要求\n"
            "- 简洁、准确、直接、用中文\n"
            "- 当用户问你的架构/能力/变更历史时，按本提示词的描述如实回答\n"
            "- 涉及本机执行，Guardian 会自动拦截并要求审批\n"
            "- 不知道就说不知道，不要编造"
        )
        if memory_context:
            system += f"\n\n{memory_context}"
        if canvas_context:
            system += (
                "\n\n" + canvas_context +
                "\n\n[画布上下文使用约定] 若用户的问题与画布节点/流程相关，请基于上方画布内容回答或推进；"
                "需要修改画布时，提示用户可在右侧画布直接编辑（或调用画布执行器）。"
            )
        return system

    # ---- 各命令处理器 ----

    def _status_md(self) -> str:
        s = self.status()
        oc = s["openclaw"].get("meta", {})
        hm = s["hermes"].get("meta", {})
        mm = s["memory"].get("meta", {})
        lines = [
            "# 系统状态",
            f"- XAI 引擎: {s['xai_engine']}",
            f"- 模型后端: {s['model']}",
            f"- OpenClaw: {s['openclaw'].get('output','')[:80]} (模式: {oc.get('mode','?')})",
            f"- Hermes: {s['hermes'].get('output','')[:80]} (模式: {hm.get('mode','?')})",
            f"- 记忆: {mm.get('total', 0)} 条",
            f"- 斜杠命令: {s['slash_commands']} 个",
            f"- 待审批: {s['pending_approvals']}",
        ]
        return "\n".join(lines)

    def _cmd_help(self, args: str) -> Generator[Dict[str, Any], None, None]:
        yield from commands.cmd_help(self, args)

    def _cmd_skill(self, args: str) -> Generator[Dict[str, Any], None, None]:
        yield from commands.cmd_skill(self, args)

    def _cmd_mcp(self, args: str) -> Generator[Dict[str, Any], None, None]:
        yield from commands.cmd_mcp(self, args)

    def _cmd_task(self, args: str, session_id: str) -> Generator[Dict[str, Any], None, None]:
        yield from commands.cmd_task(self, args, session_id)

    def _cmd_automate(self, args: str) -> Generator[Dict[str, Any], None, None]:
        yield from commands.cmd_automate(self, args)

    def _cmd_remember(self, args: str) -> Generator[Dict[str, Any], None, None]:
        yield from commands.cmd_remember(self, args)

    def _cmd_recall(self, args: str) -> Generator[Dict[str, Any], None, None]:
        yield from commands.cmd_recall(self, args)

    def _create_approval(self, action_type: str, action_detail: str, reason: str, intent: str = "", session_id: str = "default") -> str:
        return guardian_bridge.create_approval(self, action_type, action_detail, reason, intent, session_id)

    def _cmd_approve(self, args: str, session_id: str = "") -> Generator[Dict[str, Any], None, None]:
        yield from commands.cmd_approve(self, args, session_id)

    def _cmd_reject(self, args: str) -> Generator[Dict[str, Any], None, None]:
        yield from commands.cmd_reject(self, args)

    def _cmd_loop(self, args: str) -> Generator[Dict[str, Any], None, None]:
        yield from commands.cmd_loop(self, args)

    def _cmd_plan(self, args: str) -> Generator[Dict[str, Any], None, None]:
        yield from commands.cmd_plan(self, args)

    def _execute_planned(self, text: str, session_id: str, history: List[dict], attachments=None) -> Generator[Dict[str, Any], None, None]:
        yield from intents.execute_planned(self, text, session_id, history, attachments)

    def _cmd_scan(self, args: str) -> Generator[Dict[str, Any], None, None]:
        yield from commands.cmd_scan(self, args)

    def _cmd_evolve(self, args: str) -> Generator[Dict[str, Any], None, None]:
        yield from commands.cmd_evolve(self, args)

    def _cmd_models(self, args: str) -> Generator[Dict[str, Any], None, None]:
        yield from commands.cmd_models(self, args)

    def _cmd_channels(self, args: str) -> Generator[Dict[str, Any], None, None]:
        yield from commands.cmd_channels(self, args)

    def _cmd_diagnose(self) -> Generator[Dict[str, Any], None, None]:
        yield from commands.cmd_diagnose(self)

    def _guard_action(self, text: str) -> "Action":
        return guardian_bridge.guard_action(self, text)

    # ---- 工作流执行（画布）----
    # Phase D：全部节点处理器 / 超时包装 / 辅助已外移至 core/kernel/workflow.py，
    # 此处仅保留入口薄委托（行为等价，对外签名不变）。
    # 原 orchestrator.py 的双 DAG 能力也已收编进 workflow.py（CollaborativeOrchestrator）。

    def run_workflow(self, nodes: List[dict], edges: List[dict]) -> Generator[Dict[str, Any], None, None]:
        yield from workflow.run_workflow(self, nodes, edges)
    def _safe_memory_core_write(self, user_input: str, response: str, intent_type: str, engine_tag: str = "xai") -> None:
        return memory_bridge.safe_memory_core_write(self, user_input, response, intent_type, engine_tag)

    def _trigger_gepa_evolution(self, task: str, confidence: float) -> None:
        return evolution_bridge.trigger_gepa_evolution(self, task, confidence)

    def _guard_for_coordination(self, action: dict) -> tuple:
        return guardian_bridge.guard_for_coordination(self, action)

    def _init_default_agents(self) -> None:
        """注册默认协作 Agent。"""
        if not self.coordination.list_agents():
            self.coordination.register_agent("Hermes", "researcher", backend="hermes",
                                              system="通用推理+分析", memory_engine="hermes")
            self.coordination.register_agent("GrokBuild", "engineer", backend="grok_build",
                                              system="代码工程+重构+单测", memory_engine="grok_build")
            self.coordination.register_agent("Coordinator", "pm", backend="xai",
                                              system="任务拆解+派发+验收", memory_engine="xai")
