"""XAI 双模编辑器 + 元认知读侧 + HITL 契约回归测试。

覆盖 lane B / lane C 后端改动：
- failure_correction 读写闭环（写侧 record_failure → 读侧 query 按层召回 → 注入上下文）
- HITL 审批后端（create_approval → pending_approvals → resolve_approval 闭环）

全部离线可跑，不依赖网络 / 模型。
"""

import json
import threading

from core.memory_core import MemoryCore
from core.kernel.guardian_bridge import (
    create_approval,
    resolve_approval,
    pending_approvals,
)


class _FakeEngine:
    """最小化引擎桩，仅提供 guardian_bridge 所需的挂起审批状态。"""

    def __init__(self):
        self._pending_approvals = {}
        self._approval_counter = 0
        self._approval_lock = threading.Lock()


def test_failure_correction_read_write_loop(tmp_path):
    """lane C 验证：failure_correction 写入后能被读侧按层召回（闭环打通）。"""
    core = MemoryCore(db_path=str(tmp_path / "fc_loop.db"))
    core.record_failure(
        "删除旧备份脚本", "rm 触发了 P0 拦截", "先备份再删", engine="xai"
    )
    rows = core.query(layer="failure_correction", limit=3)
    assert len(rows) == 1
    d = json.loads(rows[0].value)
    assert d["task"] == "删除旧备份脚本"
    assert d["error"] == "rm 触发了 P0 拦截"
    assert d["correction"] == "先备份再删"


def test_failure_correction_injected_into_context(tmp_path):
    """模拟 retrieve_memory_context 的失败段落生成（不依赖 engine 对象）。"""
    core = MemoryCore(db_path=str(tmp_path / "fc_ctx.db"))
    core.record_failure("执行危险命令", "timeout", "加超时隔离", engine="xai")
    fc = core.query(layer="failure_correction", limit=3)
    items = []
    for e in fc:
        d = json.loads(e.value)
        items.append(
            f"- [任务] {d.get('task', '')} → [错误] {d.get('error', '')} "
            f"→ [纠正] {d.get('correction', '')}"
        )
    assert any("执行危险命令" in it for it in items)


def test_hitl_create_pending_resolve_loop():
    """lane B 验证：创建工单 → 出现在 pending → 审批通过 → 移出 pending。"""
    eng = _FakeEngine()
    aid = create_approval(eng, "rm_rf", "rm -rf /tmp/x", "疑似破坏性操作")
    assert aid in eng._pending_approvals
    pending = pending_approvals(eng)
    assert len(pending) == 1
    assert pending[0]["id"] == aid
    assert "level" in pending[0]  # 前端画布高亮依赖 level 字段
    res = resolve_approval(eng, aid, human_ok=True, reason="已确认安全")
    assert res["ok"] is True
    assert res["status"] == "approved"
    assert pending_approvals(eng) == []  # 已处置不再出现在 pending


def test_hitl_reject_and_idempotent():
    """拒绝路径 + 幂等：reject 后状态 rejected；重复 resolve 返回 already_resolved。"""
    eng = _FakeEngine()
    aid = create_approval(eng, "delete_file", "删除 /a/b.txt", "清理")
    r1 = resolve_approval(eng, aid, human_ok=False, reason="暂不删除")
    assert r1["status"] == "rejected"
    r2 = resolve_approval(eng, aid, human_ok=True, reason="改主意了")
    assert r2["ok"] is True
    assert r2.get("already_resolved") is True
    assert r2["status"] == "rejected"  # 幂等，不被覆盖


def test_hitl_resolve_unknown():
    """未知工单返回 ok=False，不抛异常。"""
    eng = _FakeEngine()
    res = resolve_approval(eng, "APR-9999", human_ok=True)
    assert res["ok"] is False
