"""P0-2: WorkflowExecutor 自动化回归测试。

测试 core/executor.py 的 WorkflowExecutor：
- 拓扑排序正确
- 并行层级分组合法（同层节点无直接依赖）
- 失败节点返回 error 状态
"""

import sys
import os

# 确保能 import core.executor（项目根目录是 /Users/Admin/Desktop/mask/xai/）
# 测试文件路径: tests/test_workflow.py，项目根目录为 ../.. 即 xai/
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import unittest
from unittest.mock import MagicMock, patch

from core.planner import DAGPlanner
from core.executor import WorkflowExecutor


class TestTopologicalSort(unittest.TestCase):
    """测试 DAGPlanner.plan 的拓扑排序正确性。"""

    def test_simple_linear_dag(self):
        """线性 DAG：A→B→C，每层一个节点。"""
        nodes = [
            {"id": "A", "type": "start", "label": "Start"},
            {"id": "B", "type": "tool", "label": "Tool"},
            {"id": "C", "type": "end", "label": "End"},
        ]
        edges = [
            {"source": "A", "target": "B"},
            {"source": "B", "target": "C"},
        ]
        levels = DAGPlanner.plan(nodes, edges)
        self.assertEqual(len(levels), 3)
        self.assertEqual(levels[0], ["A"])
        self.assertEqual(levels[1], ["B"])
        self.assertEqual(levels[2], ["C"])

    def test_diamond_dag(self):
        """菱形 DAG：A→B, A→C, B→D, C→D。A 第 1 层，B/C 第 2 层，D 第 3 层。"""
        nodes = [
            {"id": "A", "type": "start", "label": "A"},
            {"id": "B", "type": "tool", "label": "B"},
            {"id": "C", "type": "tool", "label": "C"},
            {"id": "D", "type": "end", "label": "D"},
        ]
        edges = [
            {"source": "A", "target": "B"},
            {"source": "A", "target": "C"},
            {"source": "B", "target": "D"},
            {"source": "C", "target": "D"},
        ]
        levels = DAGPlanner.plan(nodes, edges)
        self.assertEqual(len(levels), 3)
        self.assertEqual(levels[0], ["A"])
        self.assertEqual(set(levels[1]), {"B", "C"})
        self.assertEqual(levels[2], ["D"])

    def test_cycle_detection(self):
        """环路 DAG：A→B→A。应返回部分层级后停止。"""
        nodes = [
            {"id": "A", "type": "start", "label": "A"},
            {"id": "B", "type": "tool", "label": "B"},
        ]
        edges = [
            {"source": "A", "target": "B"},
            {"source": "B", "target": "A"},
        ]
        levels = DAGPlanner.plan(nodes, edges)
        # 存在环路时，levels 为空（没有任何节点入度为 0）
        self.assertEqual(levels, [])


class TestParallelLevelGrouping(unittest.TestCase):
    """测试并行层级分组合法性——同一层的节点间无直接依赖。"""

    def test_parallel_nodes_no_dependency(self):
        """A→B, A→C：B 和 C 在同一层，它们之间无依赖。"""
        nodes = [
            {"id": "A", "type": "start", "label": "A"},
            {"id": "B", "type": "tool", "label": "B"},
            {"id": "C", "type": "tool", "label": "C"},
        ]
        edges = [
            {"source": "A", "target": "B"},
            {"source": "A", "target": "C"},
        ]
        levels = DAGPlanner.plan(nodes, edges)
        self.assertEqual(len(levels), 2)
        self.assertEqual(levels[0], ["A"])
        # B 和 C 在同一层
        self.assertEqual(set(levels[1]), {"B", "C"})

        # 验证：同层节点间不存在直接边
        level_nodes = set(levels[1])
        for e in edges:
            s, t = e["source"], e["target"]
            # 不能两个都在同一层
            self.assertFalse(
                s in level_nodes and t in level_nodes,
                f"同层节点 {s}→{t} 不应有依赖",
            )

    def test_three_level_parallel_grouping(self):
        """三层 DAG：A→B, A→C, B→D, C→E, D→F, E→F。"""
        nodes = [
            {"id": "A", "type": "start", "label": "A"},
            {"id": "B", "type": "tool", "label": "B"},
            {"id": "C", "type": "tool", "label": "C"},
            {"id": "D", "type": "tool", "label": "D"},
            {"id": "E", "type": "tool", "label": "E"},
            {"id": "F", "type": "end", "label": "F"},
        ]
        edges = [
            {"source": "A", "target": "B"},
            {"source": "A", "target": "C"},
            {"source": "B", "target": "D"},
            {"source": "C", "target": "E"},
            {"source": "D", "target": "F"},
            {"source": "E", "target": "F"},
        ]
        levels = DAGPlanner.plan(nodes, edges)
        self.assertEqual(len(levels), 4)
        self.assertEqual(levels[0], ["A"])
        self.assertEqual(set(levels[1]), {"B", "C"})
        self.assertEqual(set(levels[2]), {"D", "E"})
        self.assertEqual(levels[3], ["F"])


class TestFailedNodeErrorStatus(unittest.TestCase):
    """测试失败节点返回 error 状态事件。"""

    def setUp(self):
        """构造 mock engine，核心 mock run_wf_node_with_timeout。"""
        self.mock_engine = MagicMock()
        # Mock 必要的属性，避免 AppStore 导入时副作用
        self.mock_engine._run_wf_node_with_timeout = MagicMock()

    def _make_generator(self, out=None, error=None):
        """构造一个模拟 run_wf_node_with_timeout 返回值的生成器。"""
        def _gen():
            if error:
                raise Exception(error)
            yield {"type": "wf_node", "status": "done"}
            return out

        return _gen

    @patch("core.executor.run_wf_node_with_timeout")
    def test_node_failure_yields_error_event(self, mock_run):
        """单节点失败：应 yield error 状态事件。"""
        mock_run.side_effect = Exception("模拟执行失败")

        nodes = [{"id": "n1", "type": "tool", "label": "FailingNode"}]
        edges = []

        executor = WorkflowExecutor(self.mock_engine)
        events = list(executor.run(nodes, edges))

        # 检查是否存在 error 事件
        error_events = [e for e in events if e.get("status") == "error"]
        self.assertGreaterEqual(len(error_events), 1, "应有至少一个 error 状态事件")
        # 验证 error 事件包含 node_id
        error_event = error_events[0]
        self.assertEqual(error_event.get("node_id"), "n1")
        self.assertIn("模拟执行失败", error_event.get("output", ""))

    @patch("core.executor.run_wf_node_with_timeout")
    def test_multi_node_partial_failure(self, mock_run):
        """多节点部分失败：成功节点 normal，失败节点 error。"""
        # 用 side_effect 模拟 n1 成功、n2 失败
        call_count = [0]

        def _side_effect(engine, ntype, config, upstream, label, timeout):
            call_count[0] += 1
            if call_count[0] == 1:
                # n1 成功
                def _gen():
                    yield {"type": "wf_node", "status": "done"}
                    return "n1 output"
                return _gen()
            else:
                # n2 失败
                def _gen():
                    raise Exception("n2 错误")
                return _gen()

        mock_run.side_effect = _side_effect

        nodes = [
            {"id": "n1", "type": "tool", "label": "Node1"},
            {"id": "n2", "type": "tool", "label": "Node2"},
        ]
        edges = []

        executor = WorkflowExecutor(self.mock_engine)
        events = list(executor.run(nodes, edges))

        # 按 node_id 分组
        n1_done = [e for e in events if e.get("node_id") == "n1" and e.get("status") == "done"]
        n2_error = [e for e in events if e.get("node_id") == "n2" and e.get("status") == "error"]

        self.assertEqual(len(n1_done), 1, "n1 应有 done 事件")
        self.assertEqual(len(n2_error), 1, "n2 应有 error 事件")
        self.assertIn("n2 错误", n2_error[0].get("output", ""))


if __name__ == "__main__":
    unittest.main()
