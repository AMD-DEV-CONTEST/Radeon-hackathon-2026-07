"""workflow_bridge 的确定性单元测试（stdlib unittest，零外部依赖）。"""

from __future__ import annotations

import os
import sys
import unittest

# 确保 core 包可导入（从 xai 目录或 tests 目录运行均可）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.workflow_bridge import execute_workflow, topo_order  # noqa: E402


class TopoOrderTest(unittest.TestCase):
    """拓扑排序：正常 DAG 与成环回退。"""

    def test_topo_order_simple_dag(self):
        nodes = [
            {"id": "n1", "kind": "kb"},
            {"id": "n2", "kind": "model_router"},
            {"id": "n3", "kind": "reflect"},
        ]
        edges = [
            {"source": "n1", "target": "n2"},
            {"source": "n2", "target": "n3"},
        ]
        order = topo_order(nodes, edges)
        self.assertLess(order.index("n1"), order.index("n2"))
        self.assertLess(order.index("n2"), order.index("n3"))
        self.assertEqual(set(order), {"n1", "n2", "n3"})

    def test_topo_order_cycle_fallback(self):
        """环 n1->n2->n3->n1 必须回退到输入顺序且不死循环。"""
        nodes = [{"id": "n1"}, {"id": "n2"}, {"id": "n3"}]
        edges = [
            {"source": "n1", "target": "n2"},
            {"source": "n2", "target": "n3"},
            {"source": "n3", "target": "n1"},
        ]
        self.assertEqual(topo_order(nodes, edges), ["n1", "n2", "n3"])


class ExecuteWorkflowTest(unittest.TestCase):
    """画布工作流执行：各节点类型的行为契约。"""

    def test_execute_workflow_end_to_end_ok_true(self):
        workflow = {
            "nodes": [
                {"id": "a", "kind": "kb", "label": "本地知识检索"},
                {"id": "b", "kind": "model_router", "label": "模型路由"},
                {"id": "c", "kind": "intent_router", "label": "帮我总结资料"},
                {"id": "d", "kind": "reflect", "label": "反思校准"},
                {"id": "e", "kind": "hermes", "label": "记忆"},
                {"id": "f", "kind": "code", "label": "生成脚本"},
            ],
            "edges": [
                {"source": "a", "target": "b"},
                {"source": "b", "target": "c"},
                {"source": "c", "target": "d"},
                {"source": "d", "target": "e"},
                {"source": "e", "target": "f"},
            ],
        }
        res = execute_workflow(workflow, backend=None)
        self.assertTrue(res["ok"])
        self.assertEqual(res["order"], ["a", "b", "c", "d", "e", "f"])

    def test_kb_node_records_recall_hit(self):
        workflow = {
            "nodes": [{"id": "kb1", "kind": "kb", "label": "本地知识库 检索 RAG"}],
            "edges": [],
        }
        res = execute_workflow(workflow, backend=None)
        detail = res["per_node"]["kb1"]["detail"]
        self.assertGreaterEqual(detail["hits"], 1)
        self.assertGreaterEqual(detail["indexed_chunks"], 1)
        self.assertEqual(res["per_node"]["kb1"]["status"], "done")

    def test_human_node_blocked_when_guardian_auto_false(self):
        workflow = {
            "nodes": [{"id": "h", "kind": "human", "label": "人工审批删除"}],
            "edges": [],
        }
        res = execute_workflow(workflow, backend=None, guardian_auto=False)
        node = res["per_node"]["h"]
        self.assertEqual(node["status"], "blocked")
        self.assertFalse(node["detail"]["allowed"])
        self.assertEqual(node["detail"]["action"], "delete_file")
        self.assertFalse(res["ok"])

    def test_reflect_node_calibrated_confidence_in_range(self):
        workflow = {
            "nodes": [{"id": "r", "kind": "reflect", "label": "反思校准"}],
            "edges": [],
        }
        detail = execute_workflow(workflow, backend=None)["per_node"]["r"]["detail"]
        c = detail["calibrated_confidence"]
        self.assertIsInstance(c, float)
        self.assertGreaterEqual(c, 0.0)
        self.assertLessEqual(c, 1.0)
        self.assertTrue(detail["audit_passed"])

    def test_intent_router_node_code_label_routes_grok_build(self):
        workflow = {
            "nodes": [
                {"id": "i", "kind": "intent_router", "label": "帮我重构这段 Python 代码"}
            ],
            "edges": [],
        }
        detail = execute_workflow(workflow, backend=None)["per_node"]["i"]["detail"]
        self.assertEqual(detail["routed_engine"], "grok_build_engine")
        self.assertEqual(detail["intent"], "code_dev")

    def test_per_node_keys_match_node_ids(self):
        workflow = {
            "nodes": [
                {"id": "x", "kind": "agent"},
                {"id": "y", "kind": "skill"},
                {"id": "z", "kind": "scheduler"},
            ],
            "edges": [],
        }
        res = execute_workflow(workflow, backend=None)
        self.assertEqual(set(res["per_node"].keys()), {"x", "y", "z"})
        for _nid, v in res["per_node"].items():
            self.assertEqual(set(v.keys()), {"kind", "label", "status", "detail"})


if __name__ == "__main__":
    unittest.main()
