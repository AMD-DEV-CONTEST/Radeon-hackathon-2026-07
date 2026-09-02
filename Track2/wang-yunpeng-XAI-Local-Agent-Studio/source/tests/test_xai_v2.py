"""XAI v2 吸收层测试：model_router / skills / memory / guardian扩展 / distill.gepa / control_loop A2UI。

运行：python -m pytest tests/test_xai_v2.py -q
"""

import os
import tempfile

from core import (
    ModelRouter, ModelProfile,
    SkillRegistry, Skill,
    MemorySystem,
    GovernancePolicy, ApprovalQueue, before_tool_call, Action, RiskLevel,
    Distiller, GepaEvolver, SkillSpec,
    ControlLoop, StubBackend, A2UIEvent,
)


# ---- model_router ----
def test_router_picks_highest_score():
    r = ModelRouter()
    r.register(ModelProfile("cheap", "x", capability=0.5, cost_per_1k=0.001, latency_ms=200))
    r.register(ModelProfile("strong", "x", capability=0.95, cost_per_1k=0.05, latency_ms=1500))
    # 要求高能力 -> 选 strong
    assert r.route(require_capability=0.9) == "strong"


def test_router_respects_cost_cap():
    r = ModelRouter()
    r.register(ModelProfile("a", "x", capability=0.9, cost_per_1k=0.1, latency_ms=200))
    r.register(ModelProfile("b", "x", capability=0.8, cost_per_1k=0.001, latency_ms=200))
    # 成本上限极低 -> 只能选 b
    assert r.route(max_cost=0.01) == "b"


def test_router_fallback():
    r = ModelRouter()
    r.register(ModelProfile("primary", "x", capability=0.9))
    r.register(ModelProfile("backup", "x", capability=0.7))
    fb = r.fallback("primary", RuntimeError("boom"))
    assert fb == "backup"


# ---- skills ----
def test_skill_priority_workspace_over_bundled():
    reg = SkillRegistry()
    reg.register_skill(Skill(name="s", level0="bundled", source="bundled"), source="bundled")
    reg.register_skill(Skill(name="s", level0="workspace", source="workspace"), source="workspace")
    assert reg.resolve("s").source == "workspace"


def test_skill_progressive_disclosure():
    sk = Skill(name="k", level0="摘要", level1="完整步骤", level2="边界case")
    assert "摘要" in sk.disclosure(0)
    assert "完整步骤" in sk.disclosure(1)
    assert "边界case" in sk.disclosure(2)


def test_skill_load_from_markdown(tmp_path):
    md = tmp_path / "demo.md"
    md.write_text(
        "---\nname: demo\nuser-invocable: true\ndisable-model-invocation: false\n---\n"
        "摘要部分\n<!-- L1 -->\n完整步骤\n<!-- L2 -->\n边界case",
        encoding="utf-8",
    )
    reg = SkillRegistry()
    sk = reg.load_from_markdown(str(md), source="workspace")
    assert sk.name == "demo"
    assert "摘要" in sk.level0
    assert "完整步骤" in sk.level1
    assert "边界case" in sk.level2


def test_skill_match_level0():
    reg = SkillRegistry()
    reg.register_skill(Skill(name="pdf", level0="处理PDF文件"), source="bundled")
    reg.register_skill(Skill(name="csv", level0="处理表格数据"), source="bundled")
    hits = reg.match_level0("如何解析PDF文档")
    assert hits and hits[0].name == "pdf"


# ---- memory ----
def test_memory_short_recall():
    m = MemorySystem(workspace=tempfile.mkdtemp())
    m.add_short("用户偏好使用Python写脚本")
    m.add_short("今天天气晴")
    rec = m.recall_short("Python脚本", k=1)
    assert any("Python" in r for r in rec)


def test_memory_consolidate(tmp_path):
    ws = tempfile.mkdtemp()
    m = MemorySystem(workspace=ws, short_capacity=10)
    m.add_short("重要事实：项目用Grok底座")
    promoted = m.consolidate(lambda t: 1.0 if "Grok" in t else 0.0)
    assert promoted
    assert "Grok" in m.read_long()


# ---- guardian 扩展 ----
def test_governance_blocks_tool():
    pol = GovernancePolicy(allowed_tools={"read_file"})
    res = before_tool_call(Action(kind="run_command"), policy=pol)
    assert res.allowed is False
    assert "治理" in res.reason


def test_p0_enqueues_when_queue():
    q = ApprovalQueue()
    res = before_tool_call(Action(kind="delete_file", target="/x"), auto_mode=False, queue=q)
    assert res.allowed is False
    assert q.pending()  # 已入队
    # 人工确认后放行
    tid = q.pending()[0]
    ok = q.resolve(tid, human_ok=True)
    assert ok.allowed is True


def test_p0_auto_mode_rejected():
    res = before_tool_call(Action(kind="delete_file"), auto_mode=True)
    assert res.allowed is False


# ---- distill.gepa ----
def test_gepa_picks_best_variant():
    backend = StubBackend()
    evo = GepaEvolver(backend)
    # eval_fn 给更长的 variant 更高分（stub 返回确定文本，长度随迭代稳定）
    trace = evo.evolve_skill("基线技能文本", eval_fn=lambda v: float(len(v)), iterations=4)
    assert trace.best  # 选出了最优
    assert trace.constraint_ok


# ---- control_loop A2UI ----
def test_control_loop_emits_a2ui_events():
    events: list[A2UIEvent] = []
    loop = ControlLoop(StubBackend(), emitter=lambda e: events.append(e))
    loop.act("请分析架构", emit=True)
    types = [e.type for e in events]
    assert "thinking" in types
    assert "done" in types
    # 危险动作触发 interrupt
    events.clear()
    loop.act("执行删除", action=Action(kind="delete_file"), emit=True)
    assert any(e.type == "interrupt" for e in events)


def test_full_pipeline_with_distill_and_skill():
    """端到端：蒸馏出一个 skill 并注册，技能库非空。"""
    d = Distiller(StubBackend())
    ok = d.distill_topic("代码审查", verifier=lambda s: len(s.body) > 0)
    assert ok
    assert len(d.library) == 1
