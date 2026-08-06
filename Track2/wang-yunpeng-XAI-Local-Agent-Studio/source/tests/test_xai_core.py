"""XAI 核心引擎单元测试（stdlib unittest，无需联网/装包）。

覆盖：Guardian 风险分级、Reason 思考协议/预算、Meta Brier校准/L8审计、
Runner 断点续跑、KB 检索、Orchestrator 编排、Distill 蒸馏、ControlLoop 单向环。
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import (
    StubBackend, Action, RiskLevel, approve,
    thinking_budget, multi_trajectory, Budget,
    BrierCalibrator, L8Auditor,
    Runner, StepResult,
    KnowledgeBase,
    Orchestrator, Node,
    Distiller, SkillSpec,
    ControlLoop,
)


class TestGuardian(unittest.TestCase):
    def test_p0_blocked_auto(self):
        a = Action("delete_file", "/important/main.rs")
        r = approve(a, auto_mode=True)
        self.assertEqual(r.level, RiskLevel.P0)
        self.assertFalse(r.allowed)  # 自动模式 P0 拦截

    def test_p0_override(self):
        a = Action("delete_file", "/important/main.rs")
        r = approve(a, auto_mode=True, override=True)
        self.assertTrue(r.allowed)

    def test_p1_pass(self):
        a = Action("network", "https://api.x.com")
        r = approve(a, auto_mode=True)
        self.assertEqual(r.level, RiskLevel.P1)
        self.assertTrue(r.allowed)

    def test_p2_pass(self):
        a = Action("read_file", "note.md")
        r = approve(a, auto_mode=True)
        self.assertEqual(r.level, RiskLevel.P2)
        self.assertTrue(r.allowed)


class TestReason(unittest.TestCase):
    def test_budget_scales(self):
        self.assertEqual(thinking_budget("算 1+1"), Budget.INSTANT)
        self.assertIn(thinking_budget("请设计系统架构并重构根因分析权衡"),
                      (Budget.HIGH, Budget.EXTRA))

    def test_multi_trajectory_vote(self):
        # StubBackend 每次返回相同文本 → 众数即该文本
        backend = StubBackend(default_conf=0.8)
        winner, trajs = multi_trajectory(backend, "task", n=3)
        self.assertEqual(len(trajs), 3)
        self.assertTrue(winner.startswith("[stub-answer]"))


class TestMeta(unittest.TestCase):
    def test_brier_calibration_adjusts(self):
        c = BrierCalibrator()
        # 模型总报 0.9，但实际只成功 0.5 → 校准应下调
        for _ in range(20):
            c.update(0.9, 0.5)
        self.assertLess(c.calibrate(0.9), 0.9)
        self.assertAlmostEqual(c.calibrate(0.9), 0.5, delta=0.1)

    def test_brier_score_low_when_calibrated(self):
        c = BrierCalibrator()
        for _ in range(20):
            c.update(0.9, 0.9)  # 准确自报
        self.assertLess(c.brier_score(), 0.05)

    def test_l8_audit_action_safety(self):
        aud = L8Auditor()
        # P0 动作未授权 → 动作安全维度 fail
        dims = aud.audit(data_present=True, logic_consistent=True,
                         no_hallucination=True, action=Action("delete_file", "x"),
                         auto_mode=True)
        self.assertFalse(aud.all_pass(dims))
        # 无动作 → 全过
        dims2 = aud.audit(data_present=True, logic_consistent=True, no_hallucination=True)
        self.assertTrue(aud.all_pass(dims2))


class TestRunner(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.sp = os.path.join(self.tmp, "state.json")

    def _gate(self, res: StepResult) -> bool:
        return "ok" in res.output

    def test_step_and_resume(self):
        r = Runner(self.sp)
        r.plan("建站点", ["写HTML", "写CSS", "部署"])
        # 第一步失败（质量门不过）→ 不前进
        res = r.step(lambda m: "fail", self._gate)
        self.assertFalse(res.passed)
        self.assertEqual(r.state.current, 0)
        # 第二步成功
        res = r.step(lambda m: "ok", self._gate)
        self.assertTrue(res.passed)
        self.assertEqual(r.state.current, 1)
        # 模拟崩溃后 resume
        r2 = Runner(self.sp)
        self.assertTrue(r2.resume())
        self.assertEqual(r2.state.current, 1)
        r2.step(lambda m: "ok", self._gate)
        self.assertEqual(r2.state.current, 2)


class TestKB(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        with open(os.path.join(self.tmp, "a.md"), "w", encoding="utf-8") as f:
            f.write("元认知层负责置信校准与失败溯源回滚，是模型无关的认知控制环。")
        with open(os.path.join(self.tmp, "b.md"), "w", encoding="utf-8") as f:
            f.write("画布工作流让不同模型按特质协同完成复杂任务。")

    def test_ingest_and_query(self):
        kb = KnowledgeBase()
        n = kb.ingest([self.tmp])
        self.assertGreater(n, 0)
        res = kb.query("元认知 置信校准", top_k=1)
        self.assertTrue(res)
        self.assertIn("元认知", res[0][0].text)


class TestOrchestrator(unittest.TestCase):
    def test_topo_and_pipeline(self):
        o = Orchestrator(mode="pipeline")
        o.graph.add(Node("a", "agent", depends_on=[]))
        o.graph.add(Node("b", "model", depends_on=["a"]))
        o.graph.add(Node("c", "kb", depends_on=["b"]))
        order = o.topo_order()
        self.assertEqual(order, ["a", "b", "c"])
        outs = o.run_pipeline(lambda n, ctx: f"out_{n.id}")
        self.assertEqual(outs["c"], "out_c")

    def test_collaborative(self):
        o = Orchestrator(mode="collaborative")
        tx = o.run_collaborative("主题X", ["研究员", "工程师"],
                                 lambda ag, t, hist: f"{ag}的观点", rounds=1)
        self.assertEqual(len(tx), 2)


class TestDistill(unittest.TestCase):
    def test_distill_registers_when_verified(self):
        d = Distiller(StubBackend())
        gap = d.self_assess_gap(["写文件"], ["置信校准", "失败溯源"])
        self.assertIn("置信校准", gap)
        ok = d.distill_topic("置信校准", verifier=lambda s: len(s.body) > 0)
        self.assertTrue(ok)
        self.assertEqual(len(d.library), 1)

    def test_distill_rejects_unverified(self):
        d = Distiller(StubBackend())
        ok = d.distill_topic("x", verifier=lambda s: False)
        self.assertFalse(ok)
        self.assertEqual(len(d.library), 0)


class TestControlLoop(unittest.TestCase):
    def test_p0_action_blocked(self):
        cl = ControlLoop(StubBackend(), auto_mode=True)
        res = cl.act("任务", action=Action("delete_file", "x"), execute_fn=lambda a: "executed")
        self.assertFalse(res.allowed)
        self.assertFalse(res.audit_passed)  # 动作安全 fail

    def test_p2_action_allowed_and_observe(self):
        cl = ControlLoop(StubBackend(), auto_mode=True)
        res = cl.act("任务", action=Action("read_file", "x"), execute_fn=lambda a: "read-done")
        self.assertTrue(res.allowed)
        self.assertTrue(res.audit_passed)
        # observe 更新了校准器
        self.assertGreater(cl.calibrator.count[cl.calibrator._bin(res.calibrated_confidence)], 0)

    def test_single_direction_no_recursion(self):
        # 控制环只走一遍，不触发新 reason 循环（C1 已解）
        cl = ControlLoop(StubBackend())
        res = cl.act("简单任务")
        self.assertIsNotNone(res.answer)


if __name__ == "__main__":
    unittest.main()
