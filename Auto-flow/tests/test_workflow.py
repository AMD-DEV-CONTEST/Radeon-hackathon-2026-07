"""端到端核心链路测试 (使用 Mock 后端，无需浏览器)。

链路: MockPlanner -> ComputerUseAgent(MockBackend) 执行录制
      -> BundleCompiler 编译 -> ReplayEngine 回放
      -> SkillRegistry 注册/检索/统计
"""

import os
from pathlib import Path

import pytest

os.environ["AUTOFLOW_HOME"] = str(Path(__file__).resolve().parents[1] / ".qa-runtime" / "workflow-tests")

from autoflow.capture.agent import ComputerUseAgent  # noqa: E402
from autoflow.capture.mock import MockBackend  # noqa: E402
from autoflow.compiler import BundleCompiler  # noqa: E402
from autoflow.models import Recording  # noqa: E402
from autoflow.planner import MockPlanner  # noqa: E402
from autoflow.registry import SkillRegistry  # noqa: E402
from autoflow.replay import ReplayEngine  # noqa: E402


def test_full_workflow():
    # 1. 规划
    planner = MockPlanner()
    plan = planner.plan("在表单中填写内容并提交")
    assert len(plan.steps) >= 3

    # 2. 执行 + 录制
    recording = Recording(recording_id="rec_test", app_name="demo", backend="web")
    agent = ComputerUseAgent(backend=MockBackend(), recording=recording)
    plan = agent.execute(plan, params={"note_content": "hello"})
    assert any(e.kind == "action" for e in recording.events)
    assert recording.events[0].kind == "frame"

    # 3. 编译
    compiler = BundleCompiler()
    bundle = compiler.compile(recording, plan, version=1)
    assert len(bundle.steps) == len(plan.steps)
    assert all(b.resolution_ladder for b in bundle.steps)

    # 4. 注册
    registry = SkillRegistry()
    task_id = registry.register(bundle, tags=["demo"])
    assert registry.get(task_id) is not None
    assert registry.find("表单提交")  # 关键词命中

    # 5. 回放 (零模型)
    engine = ReplayEngine(backend=MockBackend())
    result = engine.replay(bundle, params={"note_content": "world"})
    assert result.status == "success"
    assert all(s.status == "success" for s in result.steps)
    assert result.receipt is not None

    # 6. 统计
    registry.record_run(task_id, "success")
    stats = registry.stats(task_id)
    assert stats["success"] >= 1


def test_replay_halt_on_missing_element():
    """定位失败应触发 Halt 而非猜测。"""
    from autoflow.models import Bundle, BundleStep, EvidenceType, StepEvidence

    bundle = Bundle(
        task_id="task_missing",
        goal="定位失败测试",
        steps=[
            BundleStep(
                index=0,
                action={"type": "click"},
                description="点击不存在的按钮",
                evidence=StepEvidence(structural={"semantic_hint": "不存在的按钮"}),
                resolution_ladder=[EvidenceType.STRUCTURAL],
            )
        ],
    )
    engine = ReplayEngine(backend=MockBackend())
    result = engine.replay(bundle)
    assert result.status == "halted"
    assert result.halt_report["failed_step"] == 0


def test_repair_versioning():
    """修复应生成 vN+1 Bundle。"""
    from autoflow.repair import RepairAgent

    registry = SkillRegistry()
    bundle = registry.get("task_missing") or _make_bundle()
    agent = RepairAgent()
    diag = agent.diagnose(
        {"failed_step": 0, "reason": "定位失败", "evidence_used": "structural"},
        bundle,
    )
    assert diag["strategy"] in ("A", "B", "C", "D")
    new_bundle = agent.apply(bundle, diag)
    assert new_bundle.version == bundle.version + 1


def _make_bundle():
    from autoflow.models import Bundle, BundleStep, EvidenceType, StepEvidence

    return Bundle(
        task_id="task_repair",
        goal="修复测试",
        steps=[
            BundleStep(
                index=0,
                action={"type": "click"},
                description="点击提交",
                evidence=StepEvidence(structural={"semantic_hint": "提交按钮"}),
                resolution_ladder=[EvidenceType.STRUCTURAL],
                risk={"level": "high", "reversible": False},
            )
        ],
    )
