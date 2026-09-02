"""意图路由器的确定性测试（无网络、无后端依赖）。"""

from __future__ import annotations

from core.cognition.intent_router import (
    IntentRouter,
    IntentResult,
    IntentType,
    route_task,
)
from core.model_backend import StubBackend


def test_code_task_routes_to_grok_build():
    r = route_task("帮我重构这个 Python 仓库里的 bug")
    assert isinstance(r, IntentResult)
    assert r.intent is IntentType.CODE_DEV
    assert r.routing == "grok_build_engine"
    assert 0.0 <= r.confidence <= 1.0


def test_office_task_routes_to_openclaw():
    r = route_task("批量处理企业微信里的表格文档")
    assert r.intent is IntentType.OFFICE_AUTOMATION
    assert r.routing == "openclaw_gateway"


def test_long_term_business_routes_to_orchestrator():
    r = route_task("设置一个长期值守监控周期业务")
    assert r.intent is IntentType.LONG_TERM_BUSINESS
    assert r.routing == "orchestrator"


def test_research_task_routes_to_kb():
    r = route_task("调研知识库并检索资料")
    assert r.intent is IntentType.RESEARCH
    assert r.routing == "kb"


def test_general_fallback():
    r = route_task("讲个笑话")
    assert r.intent is IntentType.GENERAL
    assert r.routing == "reason"
    assert 0.0 <= r.confidence <= 1.0


def test_confidence_always_in_range():
    for t in ["写个函数", "做个 ppt", "每日巡检日报", "搜索总结资料", "随便聊聊",
              "REFACTOR the repository bug", "schedule desktop browser"]:
        r = route_task(t)
        assert 0.0 <= r.confidence <= 1.0


def test_empty_and_ambiguous_input_valid():
    for t in ["", "   ", "asdfqwer", "你好"]:
        r = route_task(t)
        assert isinstance(r, IntentResult)
        assert r.intent is IntentType.GENERAL
        assert r.routing == "reason"
        assert 0.0 <= r.confidence <= 1.0


def test_stub_backend_does_not_raise():
    backend = StubBackend()
    r = IntentRouter().classify("讲个笑话", backend=backend)
    assert isinstance(r, IntentResult)
    assert 0.0 <= r.confidence <= 1.0
