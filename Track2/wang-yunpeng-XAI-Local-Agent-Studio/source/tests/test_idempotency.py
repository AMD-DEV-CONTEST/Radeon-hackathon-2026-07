"""XAI 幂等 / 竞态 / 重启一致性测试（T3 · 六维验收·维度四 数据与状态）

覆盖三类「手抖 / 意外」场景，全部纯单测、无需联网或服务：
  1. 重启一致性：写入 → 关闭 → 新实例重开同库 → 仍能读回（crash/restart survival）
  2. 并发双写（不同 key）：多线程同时写，全部落盘、无丢失、无损坏
  3. 并发同 key 竞态：多线程写同 key，不死锁、不损坏（记忆为 INSERT 语义，不去重）
  4. 审批幂等：同一工单重复 resolve 只生效一次（already_resolved）
"""
from __future__ import annotations
import os
import sys
import tempfile
import threading
import shutil
import unittest
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.memory_core import MemoryCore
from core.kernel.guardian_bridge import create_approval, resolve_approval


class FakeEngine:
    """最小可用引擎桩：仅提供 Guardian 审批所需的三个属性。"""
    def __init__(self):
        self._approval_lock = threading.Lock()
        self._approval_counter = 0
        self._pending_approvals = {}


class TestMemoryRestartConsistency(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "mem.db")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_store_close_reopen_readback(self):
        mc = MemoryCore(self.db)
        mc.store("long_term", "project_x", "数字员工：一个大脑+三双手",
                 engine="xai", importance=0.9)
        mc._conn.close()  # 模拟进程退出 / 崩溃

        # 重启：新实例打开同一物理库
        mc2 = MemoryCore(self.db)
        e = mc2.get("long_term", "project_x")
        self.assertIsNotNone(e, "重启后记忆应可读回")
        self.assertEqual(e.value, "数字员工：一个大脑+三双手")
        self.assertEqual(e.importance, 0.9)


class TestMemoryConcurrency(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "mem.db")
        self.mc = MemoryCore(self.db)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_concurrent_distinct_keys_all_persisted(self):
        N = 50

        def w(i):
            self.mc.store("working", f"k{i}", f"v{i}")

        with ThreadPoolExecutor(max_workers=10) as ex:
            list(ex.map(w, range(N)))
        entries = self.mc.query(layer="working", limit=1000)
        self.assertEqual(len(entries), N, "并发写入应全部落盘，无丢失")

    def test_concurrent_same_key_no_deadlock(self):
        """记忆 store 是 INSERT 语义（不去重），并发同 key 不应死锁或损坏。"""
        N = 20

        def w(i):
            self.mc.store("working", "same", f"v{i}")

        with ThreadPoolExecutor(max_workers=10) as ex:
            list(ex.map(w, range(N)))  # 若死锁，这里会超时抛错
        entries = self.mc.query(layer="working", keyword="same", limit=1000)
        self.assertEqual(len(entries), N, "同 key 并发写：全部保留（INSERT 语义）")
        latest = self.mc.get("working", "same")
        self.assertIsNotNone(latest, "get 在并发写后仍能返回")


class TestApprovalIdempotency(unittest.TestCase):
    def test_resolve_twice_is_idempotent(self):
        eng = FakeEngine()
        aid = create_approval(eng, "grok_write", "写文件 /tmp/x", "测试")
        self.assertEqual(aid, "APR-0001")

        r1 = resolve_approval(eng, aid, human_ok=True, reason="确认")
        self.assertEqual(r1["status"], "approved")

        r2 = resolve_approval(eng, aid, human_ok=True, reason="再次提交")
        self.assertTrue(r2.get("already_resolved"), "重复 resolve 应标记为已处置")
        self.assertEqual(r2["status"], "approved", "状态不应被二次改变")

    def test_resolve_unknown_ticket(self):
        eng = FakeEngine()
        r = resolve_approval(eng, "APR-9999", human_ok=True)
        self.assertFalse(r["ok"], "未知工单应被拒绝而非静默放行")


if __name__ == "__main__":
    unittest.main()
