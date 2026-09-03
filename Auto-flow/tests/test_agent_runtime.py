import time

import pytest

from autoflow.agent_runtime import AgentRuntime, AgentSession
from autoflow.agent_tools import ComputerToolbox


class FakePlanner:
    available = True

    def __init__(self, decisions):
        self.decisions = iter(decisions)

    def next_action(self, goal, observation, history, tools):
        assert goal
        assert observation["ok"]
        assert any(item["name"] == "finish" for item in tools)
        return next(self.decisions)


class FakeToolbox:
    def __init__(self, risks=None):
        self.risks = risks or {}
        self.executed = []

    def schema(self):
        return [
            {"name": "observe", "description": "observe", "risk": "low", "parameters": {}},
            {"name": "type_text", "description": "type", "risk": "medium", "parameters": {}},
            {"name": "finish", "description": "finish", "risk": "low", "parameters": {}},
        ]

    def risk_for(self, action, arguments, observation=None):
        return self.risks.get(action, "low")

    def goal_authorizes(self, goal, action, arguments, observation=None):
        return False

    def execute(self, action, arguments):
        self.executed.append((action, arguments))
        if action == "observe":
            return {"ok": True, "active_window": "Test", "elements": []}
        return {"ok": True, "message": arguments.get("message", "done")}


def wait_for(runtime, session_id, status):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        value = runtime.get(session_id)
        if value["status"] == status:
            return value
        time.sleep(0.01)
    raise AssertionError(f"session did not reach {status}: {runtime.get(session_id)}")


def test_agent_observes_acts_and_finishes():
    planner = FakePlanner([
        {"summary": "检查完成", "action": "observe", "arguments": {}},
        {"summary": "结束", "action": "finish", "arguments": {"message": "目标完成"}},
    ])
    toolbox = FakeToolbox()
    runtime = AgentRuntime(planner, toolbox)
    session_id = runtime.start("完成测试任务")["id"]
    result = wait_for(runtime, session_id, "completed")
    assert result["message"] == "目标完成"
    assert result["step"] == 2


def test_agent_returns_a_user_facing_completion_report():
    class ReportingPlanner(FakePlanner):
        def final_response(self, goal, observation, history, proposed):
            assert goal == "创建并保存结果文件"
            assert observation["active_window"] == "Test"
            assert history[-1]["action"] == "finish"
            assert proposed == "完成"
            return "已经创建结果文件并保存到 D:\\输出\\结果.txt，可以直接打开查看。"

    planner = ReportingPlanner([
        {"summary": "结束", "action": "finish", "arguments": {"message": "完成"}},
    ])
    runtime = AgentRuntime(planner, FakeToolbox())
    session_id = runtime.start("创建并保存结果文件")["id"]
    result = wait_for(runtime, session_id, "completed")

    assert result["message"] == "已经创建结果文件并保存到 D:\\输出\\结果.txt，可以直接打开查看。"


def test_control_panel_interruption_restores_the_real_work_window():
    class InterferenceToolbox(FakeToolbox):
        def __init__(self):
            super().__init__()
            self.observations = iter([
                {"ok": True, "active_window": "记事本", "windows": []},
            ])
            self.focused = []

        def schema(self):
            return [
                {"name": "observe", "description": "observe", "risk": "low", "parameters": {}},
                {"name": "focus_window", "description": "focus", "risk": "low", "parameters": {}},
                {"name": "wait", "description": "wait", "risk": "low", "parameters": {}},
                {"name": "finish", "description": "finish", "risk": "low", "parameters": {}},
            ]

        def execute(self, action, arguments):
            self.executed.append((action, arguments))
            if action == "observe":
                if arguments.get("title") == "记事本":
                    return {"ok": True, "active_window": "记事本", "foreground_window": "任务中心 · AutoFlow", "background_observation": True, "windows": []}
                return next(self.observations)
            if action == "focus_window":
                self.focused.append(arguments["title"])
            return {"ok": True, "message": arguments.get("message", "done")}

    class InterferencePlanner:
        available = True

        def __init__(self):
            self.calls = 0

        def next_action(self, goal, observation, history, tools):
            self.calls += 1
            assert "AutoFlow" not in observation["active_window"]
            if self.calls == 1:
                return {"summary": "等待目标应用", "action": "wait", "arguments": {"seconds": 1}}
            assert observation["execution_mode"] == "background_preferred"
            return {"summary": "结束", "action": "finish", "arguments": {"message": "记事本任务已经完成。"}}

    toolbox = InterferenceToolbox()
    runtime = AgentRuntime(InterferencePlanner(), toolbox)
    result = wait_for(runtime, runtime.start("操作记事本")["id"], "completed")

    assert result["message"] == "记事本任务已经完成。"
    assert toolbox.focused == ["AutoFlow"]
    assert ("observe", {"title": "记事本"}) in toolbox.executed


def test_type_text_can_write_directly_to_a_background_control():
    class EditableControl:
        def __init__(self):
            self.value = ""

        def set_edit_text(self, value):
            self.value = value

    class ElementObserver:
        def __init__(self):
            self.control = EditableControl()

        def element(self, element_id):
            assert element_id == "e007"
            return self.control

    observer = ElementObserver()
    toolbox = ComputerToolbox(observer=observer)
    result = toolbox.execute("type_text", {"element_id": "e007", "text": "后台内容", "replace": True})

    assert observer.control.value == "后台内容"
    assert result["background"] is True


def test_background_only_click_never_falls_back_to_real_mouse():
    class ForegroundOnlyControl:
        clicked = False

        def invoke(self):
            raise RuntimeError("no invoke")

        def select(self):
            raise RuntimeError("no select")

        def toggle(self):
            raise RuntimeError("no toggle")

        def click_input(self):
            self.clicked = True

    class ElementObserver:
        def __init__(self):
            self.control = ForegroundOnlyControl()

        def element(self, element_id):
            return self.control

    observer = ElementObserver()
    toolbox = ComputerToolbox(observer=observer)

    with pytest.raises(RuntimeError, match="不支持静默点击"):
        toolbox.execute("click_element", {"element_id": "e003", "_background_only": True})
    assert observer.control.clicked is False


def test_invalid_model_action_is_retried_once():
    class RetryPlanner:
        available = True

        def __init__(self):
            self.calls = 0

        def next_action(self, goal, observation, history, tools):
            self.calls += 1
            if self.calls == 1:
                return {"summary": "不完整", "action": "", "arguments": {}}
            assert "上一次决定无效" in observation["planner_retry"]
            return {"summary": "结束", "action": "finish", "arguments": {"message": "自动恢复后完成。"}}

    planner = RetryPlanner()
    runtime = AgentRuntime(planner, FakeToolbox())
    result = wait_for(runtime, runtime.start("测试自动恢复")["id"], "completed")

    assert planner.calls == 2
    assert result["message"] == "自动恢复后完成。"


def test_medium_risk_action_waits_for_confirmation():
    planner = FakePlanner([
        {"summary": "输入内容", "action": "type_text", "arguments": {"text": "hello"}},
        {"summary": "结束", "action": "finish", "arguments": {"message": "完成"}},
    ])
    toolbox = FakeToolbox({"type_text": "medium"})
    runtime = AgentRuntime(planner, toolbox)
    session_id = runtime.start("输入文字", autonomous=False)["id"]
    waiting = wait_for(runtime, session_id, "awaiting_confirmation")
    assert waiting["pending_action"]["action"] == "type_text"
    assert not any(action == "type_text" for action, _ in toolbox.executed)
    runtime.confirm(session_id, True)
    wait_for(runtime, session_id, "completed")
    assert any(action == "type_text" for action, _ in toolbox.executed)


def test_dangerous_element_is_promoted_to_high_risk():
    toolbox = ComputerToolbox()
    observation = {"elements": [{"id": "e004", "name": "发送消息"}]}
    assert toolbox.risk_for("click_element", {"element_id": "e004"}, observation) == "high"


def test_agent_can_resume_after_user_input():
    planner = FakePlanner([
        {"summary": "询问名称", "action": "ask_user", "arguments": {"message": "请输入名称"}},
        {"summary": "结束", "action": "finish", "arguments": {"message": "已经继续完成"}},
    ])
    toolbox = FakeToolbox()
    toolbox.schema = lambda: [
        {"name": "observe", "description": "observe", "risk": "low", "parameters": {}},
        {"name": "ask_user", "description": "ask", "risk": "low", "parameters": {}},
        {"name": "finish", "description": "finish", "risk": "low", "parameters": {}},
    ]
    runtime = AgentRuntime(planner, toolbox)
    session_id = runtime.start("需要补充信息的任务")["id"]
    wait_for(runtime, session_id, "needs_input")
    with pytest.raises(RuntimeError, match="已经有一个 Agent"):
        runtime.start("不能并发启动的任务")
    runtime.provide_input(session_id, "测试名称")
    result = wait_for(runtime, session_id, "completed")
    assert result["message"] == "已经继续完成"
    assert any(item["action"] == "user_input" for item in result["history"])


def test_stopping_a_task_waiting_for_input_releases_agent_slot():
    planner = FakePlanner([
        {"summary": "询问信息", "action": "ask_user", "arguments": {"message": "请输入名称"}},
        {"summary": "结束第二个任务", "action": "finish", "arguments": {"message": "第二个任务完成"}},
    ])
    toolbox = FakeToolbox()
    toolbox.schema = lambda: [
        {"name": "observe", "description": "observe", "risk": "low", "parameters": {}},
        {"name": "ask_user", "description": "ask", "risk": "low", "parameters": {}},
        {"name": "finish", "description": "finish", "risk": "low", "parameters": {}},
    ]
    runtime = AgentRuntime(planner, toolbox)
    first_id = runtime.start("等待输入的任务")["id"]
    wait_for(runtime, first_id, "needs_input")
    assert runtime.stop(first_id)["status"] == "stopped"
    second_id = runtime.start("第二个任务")["id"]
    assert wait_for(runtime, second_id, "completed")["message"] == "第二个任务完成"


def test_background_key_failure_focuses_target_then_restores_user_window():
    class FallbackToolbox(FakeToolbox):
        def schema(self):
            return [
                {"name": "focus_window", "description": "focus", "risk": "low", "parameters": {}},
                {"name": "press_keys", "description": "keys", "risk": "medium", "parameters": {}},
            ]

        def execute(self, action, arguments):
            self.executed.append((action, dict(arguments)))
            if action == "press_keys" and arguments.get("_background_only"):
                raise RuntimeError("后台消息被拒绝")
            return {"ok": True, "message": "ok"}

    toolbox = FallbackToolbox()
    runtime = AgentRuntime(FakePlanner([]), toolbox)
    session = AgentSession(id="agent_test", goal="保存", silent=True, _work_window="记事本")
    result = runtime._execute_action(session, "press_keys", {"keys": "ctrl+s"}, {"foreground_window": "任务中心 · AutoFlow"})

    assert result["ok"] is True
    assert toolbox.executed == [
        ("press_keys", {"keys": "ctrl+s", "_background_only": True, "window_title": "记事本"}),
        ("focus_window", {"title": "记事本"}),
        ("press_keys", {"keys": "ctrl+s"}),
        ("focus_window", {"title": "任务中心 · AutoFlow"}),
    ]


def test_powershell_authorization_rejects_compound_or_extra_targets():
    toolbox = ComputerToolbox()
    goal = r"删除 C:\temp\old.txt"

    assert toolbox.goal_authorizes(goal, "run_powershell", {"command": r"Remove-Item 'C:\temp\old.txt'"}) is True
    assert toolbox.goal_authorizes(goal, "run_powershell", {"command": r"Remove-Item 'C:\temp\old.txt'; Get-Process"}) is False
    assert toolbox.goal_authorizes(goal, "run_powershell", {"command": r"Remove-Item 'C:\temp\old.txt','C:\private\data.txt'"}) is False
    assert toolbox.risk_for("press_keys", {"keys": "alt+f4"}) == "high"


def test_autonomous_mode_runs_medium_risk_without_confirmation():
    planner = FakePlanner([
        {"summary": "输入内容", "action": "type_text", "arguments": {"text": "hello"}},
        {"summary": "结束", "action": "finish", "arguments": {"message": "完成"}},
    ])
    toolbox = FakeToolbox({"type_text": "medium"})
    runtime = AgentRuntime(planner, toolbox)
    session_id = runtime.start("输入 hello", autonomous=True)["id"]
    wait_for(runtime, session_id, "completed")
    assert any(action == "type_text" for action, _ in toolbox.executed)


def test_autonomous_mode_blocks_unrequested_high_risk_action():
    planner = FakePlanner([
        {"summary": "危险动作", "action": "type_text", "arguments": {"text": "unexpected"}},
        {"summary": "结束", "action": "finish", "arguments": {"message": "安全结束"}},
    ])
    toolbox = FakeToolbox({"type_text": "high"})
    runtime = AgentRuntime(planner, toolbox)
    session_id = runtime.start("查看状态", autonomous=True)["id"]
    result = wait_for(runtime, session_id, "completed")
    assert any(item["status"] == "blocked" for item in result["history"])
    assert not any(action == "type_text" for action, _ in toolbox.executed)
