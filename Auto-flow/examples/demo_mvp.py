"""AutoFlow MVP 完整链路演示脚本 (Mock 后端，无需浏览器/API key)。

演示流程:
1. MockPlanner 生成任务计划
2. ComputerUseAgent + MockBackend 首次执行并录制
3. BundleCompiler 编译 Bundle
4. SkillRegistry 注册 + 语义检索
5. ReplayEngine 零模型回放 (注入参数)
6. 模拟 Halt -> RepairAgent 诊断 -> 生成 v2 Bundle

运行: python examples/demo_mvp.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Windows 控制台默认 GBK，强制 UTF-8 输出避免 UnicodeEncodeError
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

os.environ.setdefault(
    "AUTOFLOW_HOME",
    str(Path(__file__).resolve().parents[1] / ".demo"),
)

from autoflow.capture.agent import ComputerUseAgent
from autoflow.capture.mock import MockBackend
from autoflow.compiler import BundleCompiler
from autoflow.models import Recording
from autoflow.planner import MockPlanner
from autoflow.registry import SkillRegistry
from autoflow.replay import ReplayEngine
from autoflow.repair import RepairAgent


def step(title: str) -> None:
    print("\n" + "=" * 60)
    print(f"▶ {title}")
    print("=" * 60)


def main() -> None:
    # ---------- 1. 规划 ----------
    step("1. 自然语言 -> TaskPlan (LLM/Mock 规划)")
    planner = MockPlanner()
    plan = planner.plan("在表单中填写内容并提交")
    print(f"任务: {plan.goal}")
    print(f"步骤数: {len(plan.steps)}")
    for s in plan.steps:
        print(f"  [{s.step_index}] {s.action.value}: {s.description} (risk={s.risk_level.value})")

    # ---------- 2. 执行 + 录制 ----------
    step("2. 首次执行 + 录制 (Computer Use Agent)")
    recording = Recording(recording_id="rec_demo", app_name="demo", backend="web")
    agent = ComputerUseAgent(backend=MockBackend(), recording=recording)
    plan = agent.execute(plan, params={"note_content": "常规检查"})
    print(f"录制事件数: {len(recording.events)}")
    print("录制的动作事件:")
    for e in recording.events:
        if e.kind == "action":
            print(f"  [{e.data['step_index']}] {e.data['action']}: {e.data['description']}")

    # ---------- 3. 编译 ----------
    step("3. 录制 + 语义标注 -> 编译 Bundle")
    compiler = BundleCompiler()
    bundle = compiler.compile(recording, plan, version=1)
    print(f"Bundle v1 生成: {bundle.task_id}")
    print(f"步骤数: {len(bundle.steps)}")
    for s in bundle.steps:
        ladder = ", ".join(e.value for e in s.resolution_ladder)
        print(f"  [{s.index}] {s.description} | ladder={ladder} | slots={s.slots}")

    # ---------- 4. 注册 ----------
    step("4. 注册到 Skill Registry")
    registry = SkillRegistry()
    task_id = registry.register(bundle, tags=["demo", "表单"])
    print(f"已注册: {task_id}")
    matches = registry.find("表单提交")
    print(f"语义检索 '表单提交' -> {matches}")

    # ---------- 5. 零模型回放 ----------
    step("5. 零模型确定性 Replay (注入参数)")
    engine = ReplayEngine(backend=MockBackend())
    result = engine.replay(bundle, params={"note_content": "复查血压"})
    print(f"执行状态: {result.status}")
    for s in result.steps:
        print(f"  [{s.index}] {s.status} (evidence={s.evidence_used.value if s.evidence_used else '-'})")
    print(f"Receipt: {result.receipt}")
    registry.record_run(task_id, result.status)

    # ---------- 6. 碰壁修复 ----------
    step("6. 模拟 Halt -> AI 诊断 -> 版本化修复")
    halt_report = {
        "task_id": bundle.task_id,
        "goal": bundle.goal,
        "failed_step": 2,
        "reason": "提交按钮定位失败 (演示用)",
        "evidence_used": "structural",
    }
    repair = RepairAgent()
    diag = repair.diagnose(halt_report, bundle)
    print(f"诊断根因: {diag['root_cause']}")
    print(f"修复策略: {diag['strategy']}")
    new_bundle = repair.apply(bundle, diag)
    registry.register(new_bundle)
    print(f"已生成 v{new_bundle.version}: {new_bundle.task_id}")

    # ---------- 7. 统计 ----------
    step("7. 执行统计与成本对比")
    stats = registry.stats(task_id)
    print(f"执行次数: {stats['count']}")
    print(f"成功率: {stats['success_rate']}")
    print(f"零模型执行成本: ${stats['replay_cost_per_run']}")
    print(f"对比全程 AI 执行节省: ${stats['total_saved']}")

    print("\n✅ MVP 全链路演示完成!")


if __name__ == "__main__":
    main()
