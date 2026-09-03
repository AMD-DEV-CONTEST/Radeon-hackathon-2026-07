"""Observe-think-act-verify runtime for general computer tasks."""

from __future__ import annotations

import os
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from autoflow.agent_tools import ComputerToolbox


class AgentPlanner(Protocol):
    @property
    def available(self) -> bool: ...
    def next_action(self, goal: str, observation: dict[str, Any], history: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]: ...
    def final_response(self, goal: str, observation: dict[str, Any], history: list[dict[str, Any]], proposed: str) -> str: ...


@dataclass
class AgentSession:
    id: str
    goal: str
    status: str = "running"
    message: str = "正在观察电脑…"
    step: int = 0
    max_steps: int = 20
    autonomous: bool = True
    silent: bool = True
    history: list[dict[str, Any]] = field(default_factory=list)
    pending_action: dict[str, Any] | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    _confirmation: threading.Event = field(default_factory=threading.Event, repr=False)
    _stop: threading.Event = field(default_factory=threading.Event, repr=False)
    _approved: bool = False
    _work_window: str = ""

    def public(self) -> dict[str, Any]:
        return {"id": self.id, "goal": self.goal, "status": self.status, "message": self.message, "step": self.step, "max_steps": self.max_steps, "autonomous": self.autonomous, "silent": self.silent, "history": self.history[-30:], "pending_action": self.pending_action, "created_at": self.created_at, "updated_at": self.updated_at}


class AgentRuntime:
    def __init__(self, planner: AgentPlanner, toolbox: ComputerToolbox | None = None) -> None:
        self.planner = planner
        self.toolbox = toolbox or ComputerToolbox()
        self.sessions: dict[str, AgentSession] = {}
        self._lock = threading.RLock()
        self._agent_lock = threading.Lock()
        self._active_session_id: str | None = None

    def start(self, goal: str, max_steps: int = 20, autonomous: bool = True, silent: bool = True) -> dict[str, Any]:
        goal = goal.strip()
        if not goal:
            raise ValueError("请告诉我需要完成什么任务。")
        if not self.planner.available:
            raise RuntimeError('通用 Agent 需要先连接 DeepSeek。请点击右上角"AI 设置"。')
        if not self._agent_lock.acquire(blocking=False):
            raise RuntimeError("已经有一个 Agent 正在运行，请等待它完成或先停止。")
        try:
            session = AgentSession(id=f"agent_{uuid.uuid4().hex[:12]}", goal=goal, max_steps=max(3, min(int(max_steps), 40)), autonomous=bool(autonomous), silent=bool(silent))
            with self._lock:
                self.sessions[session.id] = session
                self._active_session_id = session.id
            threading.Thread(target=self._run, args=(session,), daemon=True).start()
        except Exception:
            self._agent_lock.release()
            raise
        return session.public()

    def get(self, session_id: str) -> dict[str, Any]:
        return self._get(session_id).public()

    def confirm(self, session_id: str, approved: bool) -> dict[str, Any]:
        session = self._get(session_id)
        if session.status != "awaiting_confirmation":
            raise ValueError("当前没有等待确认的操作。")
        session._approved = bool(approved)
        session._confirmation.set()
        return session.public()

    def stop(self, session_id: str) -> dict[str, Any]:
        session = self._get(session_id)
        with self._lock:
            waiting_for_input = session.status == "needs_input"
            session._stop.set()
            session._confirmation.set()
            session.status = "stopped" if waiting_for_input else "stopping"
            session.message = "任务已停止。" if waiting_for_input else "正在安全停止…"
            self._touch(session)
        if waiting_for_input:
            self._release_agent_slot(session)
        return session.public()

    def provide_input(self, session_id: str, answer: str) -> dict[str, Any]:
        session = self._get(session_id)
        answer = answer.strip()
        if not answer:
            raise ValueError("请输入要补充的信息。")
        with self._lock:
            if session.status != "needs_input":
                raise ValueError("当前任务没有等待补充信息。")
            if self._active_session_id != session.id or not self._agent_lock.locked():
                raise RuntimeError("任务执行锁已失效，请重新开始这次任务。")
            session.history.append({"step": session.step, "summary": "用户补充了必要信息", "action": "user_input", "arguments": {}, "risk": "low", "status": "success", "result": {"answer": answer[:4000]}})
            session.status = "running"
            session.message = "已收到，正在继续任务…"
            self._touch(session)
        threading.Thread(target=self._run, args=(session,), daemon=True).start()
        return session.public()

    def _get(self, session_id: str) -> AgentSession:
        with self._lock:
            session = self.sessions.get(session_id)
        if session is None:
            raise ValueError("找不到这次 Agent 任务。")
        return session

    def _run(self, session: AgentSession) -> None:
        pythoncom = None
        try:
            if os.name == "nt":
                try:
                    import pythoncom as _pythoncom

                    pythoncom = _pythoncom
                    pythoncom.CoInitialize()
                except ImportError:
                    pythoncom = None
            observation = self._observe_work_window(session)
            while session.step < session.max_steps and not session._stop.is_set():
                session.step += 1
                session.message = f"正在思考第 {session.step} 步…"
                self._touch(session)
                recent = session.history[-2:]
                if len(recent) == 2 and all(item.get("status") in {"failed", "blocked", "rejected"} for item in recent):
                    same_action = recent[0].get("action") == recent[1].get("action")
                    same_arguments = recent[0].get("arguments") == recent[1].get("arguments")
                    if same_action and same_arguments:
                        observation["recovery_guidance"] = "相同动作已经连续失败两次，禁止原样重试；请重新观察并选择不同方案。"
                decision = self._next_decision(session, observation)
                action = str(decision.get("action", ""))
                arguments = decision.get("arguments") if isinstance(decision.get("arguments"), dict) else {}
                entry = {"step": session.step, "summary": str(decision.get("summary", "正在执行下一步"))[:300], "action": action, "arguments": arguments, "status": "planned"}
                session.history.append(entry)
                risk = self.toolbox.risk_for(action, arguments, observation)
                entry["risk"] = risk
                if risk == "high" and session.autonomous and not self.toolbox.goal_authorizes(session.goal, action, arguments, observation):
                    result = {"ok": False, "blocked": True, "error": "该高风险操作没有在原始目标中明确授权，已自动阻止。"}
                    entry["status"] = "blocked"
                    entry["result"] = result
                    observation = self._observe_work_window(session)
                    observation["last_action_result"] = result
                    session.message = "已阻止一个超出原始目标的高风险动作，正在寻找安全方案…"
                    self._touch(session)
                    continue
                if not session.autonomous and risk in {"medium", "high"}:
                    session.pending_action = {"action": action, "arguments": arguments, "risk": risk, "summary": entry["summary"]}
                    session.status = "awaiting_confirmation"
                    session.message = "需要你确认后才能继续。"
                    session._approved = False
                    session._confirmation.clear()
                    self._touch(session)
                    session._confirmation.wait()
                    session.pending_action = None
                    if session._stop.is_set():
                        break
                    if not session._approved:
                        entry["status"] = "rejected"
                        observation = {"ok": True, "message": "用户拒绝了这个操作。"}
                        session.status = "running"
                        continue
                    session.status = "running"
                session.message = f"正在执行：{entry['summary']}"
                self._touch(session)
                try:
                    result = self._execute_action(session, action, arguments, observation)
                    entry["status"] = "success"
                    entry["result"] = result
                except Exception as exc:
                    result = {"ok": False, "error": str(exc)}
                    entry["status"] = "failed"
                    entry["result"] = result
                if action == "finish":
                    session.status = "completed"
                    proposed = str(result.get("message", "任务完成。"))
                    reporter = getattr(self.planner, "final_response", None)
                    if callable(reporter):
                        try:
                            proposed = str(reporter(session.goal, observation, session.history, proposed)).strip() or proposed
                        except Exception:
                            pass
                    session.message = proposed
                    self._touch(session)
                    return
                if action == "ask_user":
                    session.status = "needs_input"
                    session.message = str(result.get("message", "需要更多信息。"))
                    self._touch(session)
                    return
                observation = self._observe_work_window(session)
                observation["last_action_result"] = result
                self._touch(session)
            if session._stop.is_set():
                session.status = "stopped"
                session.message = "任务已停止。"
            else:
                session.status = "failed"
                session.message = f"已达到 {session.max_steps} 步上限，任务仍未完成。"
        except Exception as exc:
            session.status = "failed"
            session.message = f"Agent 运行失败：{exc}"
        finally:
            if session.status in {"completed", "failed", "stopped", "needs_input"}:
                self._focus_control_panel()
            if pythoncom is not None:
                pythoncom.CoUninitialize()
            if session.status != "needs_input":
                self._release_agent_slot(session)
            self._touch(session)

    def _next_decision(self, session: AgentSession, observation: dict[str, Any]) -> dict[str, Any]:
        """Retry one malformed planner response instead of failing the whole task."""
        allowed = {item["name"] for item in self.toolbox.schema()}
        last_error = "模型没有返回可执行动作。"
        for attempt in range(2):
            try:
                decision = self.planner.next_action(session.goal, observation, session.history, self.toolbox.schema())
                action = str(decision.get("action", ""))
                arguments = decision.get("arguments")
                if action in allowed and isinstance(arguments, dict):
                    return decision
                last_error = f"返回的工具“{action or '空'}”不可执行"
            except Exception as exc:
                last_error = str(exc)
            if attempt == 0:
                observation["planner_retry"] = f"上一次决定无效：{last_error}。请重新检查当前窗口并只返回一个合法工具动作。"
                session.message = "模型的上一步决定不完整，正在自动重新判断…"
                self._touch(session)
        raise RuntimeError(f"模型连续两次没有给出可执行动作：{last_error}")

    def _observe_work_window(self, session: AgentSession) -> dict[str, Any]:
        """Keep the control panel from replacing the real task window."""
        if session.silent and session._work_window:
            try:
                background = self.toolbox.execute("observe", {"title": session._work_window})
                if not background.get("ok", False):
                    raise RuntimeError(str(background.get("error", "无法读取后台窗口")))
                background["execution_mode"] = "background_preferred"
                background["background_guidance"] = "正在后台观察任务窗口。优先使用 element_id 控件和带 element_id 的 type_text，避免坐标与全局快捷键。"
                return background
            except Exception as exc:
                observation = self.toolbox.execute("observe", {})
                observation["background_notice"] = f"原后台窗口暂时不可用：{exc}。请从 windows 中重新找到任务应用。"
                return observation
        observation = self.toolbox.execute("observe", {})
        active = str(observation.get("active_window", "")).strip()
        if active and not self._is_control_panel(active):
            session._work_window = active
            return observation
        if session.silent:
            observation["execution_mode"] = "background_preferred"
            observation["control_panel_notice"] = "当前是 AutoFlow 控制页。首次找到任务应用后，后续将直接在后台观察和操作它。"
            return observation
        if not active or not session._work_window or "focus_window" not in {item["name"] for item in self.toolbox.schema()}:
            if self._is_control_panel(active):
                observation["control_panel_notice"] = "当前是 AutoFlow 控制页，不是任务目标。请从可见窗口中选择与用户目标相关的应用。"
            return observation
        # Non-silent mode: AutoFlow is foreground but a known work window can be restored.
        observation["autoflow_notice"] = "AutoFlow 当前在前台，请使用 focus_window 切回任务应用继续执行。"
        return observation

    def _execute_action(self, session: AgentSession, action: str, arguments: dict[str, Any], observation: dict[str, Any]) -> dict[str, Any]:
        """Use background-safe UIA actions first and focus only for keyboard/coordinate fallbacks."""
        if action == "focus_window":
            result = self.toolbox.execute(action, arguments)
            session._work_window = str(arguments.get("title", "")).strip() or session._work_window
            return result
        if action == "open":
            result = self.toolbox.execute(action, arguments)
            session._work_window = ""
            return result
        requires_foreground = action in {"click_at", "click_element", "press_keys", "type_text"}
        background_control_action = action in {"click_element", "press_keys"} or (action == "type_text" and bool(str(arguments.get("element_id", "")).strip()))
        if session.silent and background_control_action:
            background_arguments = dict(arguments)
            background_arguments["_background_only"] = True
            if session._work_window:
                background_arguments["window_title"] = session._work_window
            try:
                return self.toolbox.execute(action, background_arguments)
            except RuntimeError:
                # Background path failed (e.g. PostMessage rejected); fall through to foreground.
                pass
        if not session.silent or not requires_foreground or not session._work_window or "focus_window" not in {item["name"] for item in self.toolbox.schema()}:
            return self.toolbox.execute(action, arguments)
        foreground = str(observation.get("foreground_window", "")).strip()
        restore_window = foreground if foreground and foreground.casefold() != session._work_window.casefold() else ""
        self.toolbox.execute("focus_window", {"title": session._work_window})
        try:
            return self.toolbox.execute(action, arguments)
        finally:
            if restore_window:
                try:
                    self.toolbox.execute("focus_window", {"title": restore_window})
                except Exception:
                    pass

    def _release_agent_slot(self, session: AgentSession) -> None:
        """Release the single-agent slot exactly once for its owning session."""
        should_release = False
        with self._lock:
            if self._active_session_id == session.id:
                self._active_session_id = None
                should_release = True
        if should_release and self._agent_lock.locked():
            self._agent_lock.release()

    def _focus_control_panel(self) -> None:
        if "focus_window" not in {item["name"] for item in self.toolbox.schema()}:
            return
        try:
            self.toolbox.execute("focus_window", {"title": "AutoFlow"})
        except Exception:
            pass

    @staticmethod
    def _is_control_panel(title: str) -> bool:
        return "autoflow" in title.casefold()

    @staticmethod
    def _touch(session: AgentSession) -> None:
        session.updated_at = datetime.now(timezone.utc).isoformat()
