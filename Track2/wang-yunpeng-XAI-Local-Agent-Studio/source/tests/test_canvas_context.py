"""Canvas-as-Context 序列化器单元测试（离线、无副作用）。

验证 core.canvas.context.build_canvas_context：
- 无画布 / 空画布 → 返回空串（不注入）
- 正常画布 → 序列化节点 + 连线
- 超预算 → 截断（保留结构，跳过冗长细节），不撑爆上下文
"""

import sys
import os
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.canvas.context import build_canvas_context, _est_tokens


def _fake_canvas(nodes, edges):
    return {"id": "sessX", "nodes": nodes, "edges": edges, "version": 1}


class TestCanvasContext(unittest.TestCase):
    def test_no_canvas_returns_empty(self):
        with patch("core.canvas.context.canvas_peek", return_value=None):
            self.assertEqual(build_canvas_context("sessX"), "")

    def test_empty_nodes_returns_empty(self):
        with patch("core.canvas.context.canvas_peek", return_value=_fake_canvas([], [])):
            self.assertEqual(build_canvas_context("sessX"), "")

    def test_serializes_nodes_and_edges(self):
        nodes = [
            {"id": "n1", "data": {"label": "调研竞品", "nodeType": "agent", "status": "done"}},
            {"id": "n2", "data": {"label": "写方案", "nodeType": "tool", "status": "running"}},
        ]
        edges = [{"source": "n1", "target": "n2"}]
        with patch("core.canvas.context.canvas_peek", return_value=_fake_canvas(nodes, edges)):
            ctx = build_canvas_context("sessX")
        self.assertIn("共享画布 sessX", ctx)
        self.assertIn("调研竞品", ctx)
        self.assertIn("写方案", ctx)
        self.assertIn("n1 → n2", ctx)
        self.assertIn("状态=done", ctx)
        self.assertIn("状态=running", ctx)

    def test_budget_truncation(self):
        # 制造一个超预算的大画布（大量长标签节点）
        big = [{"id": f"n{i}", "data": {"label": "x" * 200, "nodeType": "agent"}} for i in range(50)]
        with patch("core.canvas.context.canvas_peek", return_value=_fake_canvas(big, [])):
            ctx = build_canvas_context("sessX", budget_tokens=200)
        self.assertTrue(len(ctx) > 0)
        # 预算保护：截断说明出现，且不会把 50 个节点全塞进去
        self.assertIn("省略部分节点", ctx)
        self.assertLess(_est_tokens(ctx), 200 + 50)  # 截断后明显低于预算余量

    def test_budget_small_still_keeps_header(self):
        nodes = [{"id": "n1", "data": {"label": "任务A", "nodeType": "agent"}}]
        with patch("core.canvas.context.canvas_peek", return_value=_fake_canvas(nodes, [])):
            ctx = build_canvas_context("sessX", budget_tokens=10)
        self.assertIn("共享画布 sessX", ctx)


if __name__ == "__main__":
    unittest.main()
