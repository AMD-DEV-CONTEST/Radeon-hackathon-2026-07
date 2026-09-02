"""Agent 协作室（Buzz 多 Agent 同室协作）单元测试（离线、mock 模型后端）。

验证：
- 房间 CRUD（创建 / 列表 / 获取 / 删除 / 重置），持久化 JSON。
- 多 Agent 一轮：各 Agent 依次发言、彼此可见（build on each other），transcript 累积。
- 单 Agent 异常不阻断其他 Agent。
"""

import os
import sys
import json
import tempfile
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.agent_room import AgentRoomManager, AgentRoom, AgentDef, run_agent_room


class _FakeBackend:
    """按 Agent 顺序返回确定化回复，便于断言「彼此可见」。"""
    def __init__(self):
        self.calls = []

    def stream_complete(self, prompt, messages=None, max_tokens=900, **kw):
        self.calls.append(messages)
        # 末条 user 提示中含当前 Agent 名；这里简单基于 messages 长度区分
        # 真实场景由模型生成；测试只验证调用次数与历史拼接结构。
        # 返回固定片段
        yield "观点"


class TestAgentRoomManager(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "agent_rooms.json")
        self.mgr = AgentRoomManager(store_path=self.path)

    def test_create_list_get_delete(self):
        room = self.mgr.create_room("规划室", [
            {"name": "架构师", "role": "架构", "system_prompt": "关注可扩展性"},
            {"name": "产品经理", "role": "产品", "system_prompt": "关注用户价值"},
        ])
        self.assertEqual(len(room.agents), 2)
        self.assertEqual(len(self.mgr.list_rooms()), 1)
        got = self.mgr.get_room(room.id)
        self.assertIsNotNone(got)
        self.assertTrue(self.mgr.delete_room(room.id))
        self.assertEqual(len(self.mgr.list_rooms()), 0)

    def test_persist_roundtrip(self):
        room = self.mgr.create_room("R", [{"name": "A", "role": "x"}])
        # 新 manager 读取同一文件应能看到
        m2 = AgentRoomManager(store_path=self.path)
        self.assertEqual(len(m2.list_rooms()), 1)
        self.assertEqual(m2.get_room(room.id).name, "R")

    def test_reset(self):
        room = self.mgr.create_room("R", [{"name": "A", "role": "x"}])
        room.transcript.append({"speaker": "A", "role": "x", "text": "hi"})
        self.mgr._persist()
        self.assertTrue(self.mgr.clear_transcript(room.id))
        self.assertEqual(len(self.mgr.get_room(room.id).transcript), 0)


class TestRunAgentRoom(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "agent_rooms.json")
        self.mgr = AgentRoomManager(store_path=self.path)
        self.room = self.mgr.create_room("协作室", [
            {"name": "架构师", "role": "架构", "system_prompt": "关注可扩展性"},
            {"name": "测试", "role": "QA", "system_prompt": "关注边界"},
        ])
        self.backend = _FakeBackend()
        self.engine = MagicMock()
        self.engine._backend = self.backend
        self.engine.record_backend_usage = MagicMock()

    def test_multi_agent_turn_builds_on_each_other(self):
        evs = list(run_agent_room(self.engine, self.room, "如何设计登录？", self.mgr))
        # 2 个 agent_start + 2 个 agent_message + 1 done = 5
        starts = [e for e in evs if e["type"] == "agent_start"]
        msgs = [e for e in evs if e["type"] == "agent_message"]
        self.assertEqual(len(starts), 2)
        self.assertEqual(len(msgs), 2)
        self.assertTrue(any(e["type"] == "done" for e in evs))
        # 第二次调用应把第一次 Agent 的发言作为 assistant 历史传入
        # messages 列表结构：system + (prior agents as assistant) + final user
        # 第一个 Agent：1 个 user 轮；第二个 Agent：1 个 assistant 历史 + 1 个 user 轮
        first_msgs = self.backend.calls[0]
        second_msgs = self.backend.calls[1]
        # 第二个 Agent 的历史应包含第一个 Agent 的发言
        assistant_hist = [m for m in second_msgs[1:-1] if m["role"] == "assistant"]
        self.assertEqual(len(assistant_hist), 1)
        self.assertIn("架构师", assistant_hist[0]["content"])
        # transcript 累积了 user + 2 agent
        self.assertEqual(len(self.room.transcript), 3)
        # 持久化落盘
        reloaded = AgentRoomManager(store_path=self.path).get_room(self.room.id)
        self.assertEqual(len(reloaded.transcript), 3)

    def test_agent_failure_isolated(self):
        def _boom(prompt, messages=None, max_tokens=900, **kw):
            raise RuntimeError("model down")
            yield ""  # unreachable
        self.backend.stream_complete = _boom
        evs = list(run_agent_room(self.engine, self.room, "hi"))
        msgs = [e for e in evs if e["type"] == "agent_message"]
        # 即使异常，每个 Agent 仍产出一条（含异常说明），不该崩溃
        self.assertEqual(len(msgs), 2)
        self.assertTrue(any("推理异常" in m["text"] for m in msgs))


if __name__ == "__main__":
    unittest.main()
