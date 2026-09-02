"""统一记忆池（痛点1）与权限分级（痛点3）的测试。"""

import os
import tempfile

from core import (
    MemorySystem, UnifiedMemoryPool,
    PermissionTier, PermissionPolicy, needs_secondary_confirmation, guard,
    Action, ApprovalQueue,
)


# ---------------- 统一记忆池 ----------------
def test_unified_pool_alias():
    assert UnifiedMemoryPool is MemorySystem


def test_engine_tag_isolation():
    m = MemorySystem(workspace=tempfile.mkdtemp())
    m.add_short("用 OpenClaw 控制桌面", engine="openclaw")
    m.add_short("用 Grok Build 重构仓库", engine="grok_build")
    # 指定引擎只看本引擎
    assert m.recall_short("桌面", engine="openclaw")
    assert not m.recall_short("桌面", engine="grok_build")
    # 跨引擎（engine=None）全局共享
    cross = m.recall("桌面", engine=None)
    assert any("OpenClaw" in t for t in cross)


def test_query_cross_engine_returns_tags():
    m = MemorySystem(workspace=tempfile.mkdtemp())
    m.add_short("企业微信发消息", engine="openclaw")
    m.add_short("扫描漏洞", engine="grok_build")
    hits = m.query_cross_engine("漏洞")
    assert hits and hits[0][0] == "grok_build"


def test_engines_set():
    m = MemorySystem(workspace=tempfile.mkdtemp())
    m.add_short("a", engine="hermes")
    m.add_medium("b", engine="orchestrator")
    assert {"hermes", "orchestrator"} <= m.engines()


def test_consolidate_still_passes_text():
    m = MemorySystem(workspace=tempfile.mkdtemp())
    m.add_short("重要事实：项目用Grok底座")
    promoted = m.consolidate(lambda t: 1.0 if "Grok" in t else 0.0)
    assert promoted  # persist_long 返回路径


# ---------------- 权限分级（痛点3） ----------------
def test_permission_insufficient_tier():
    pol = PermissionPolicy()
    res = guard(Action(kind="delete_file"), permission=pol, tier=PermissionTier.VIEWER)
    assert res.allowed is False
    assert "权限不足" in res.reason


def test_secondary_confirm_delete_blocked():
    assert needs_secondary_confirmation(Action(kind="delete_file")) is True
    assert needs_secondary_confirmation(Action(kind="rm_rf", target="/x")) is True
    res = guard(Action(kind="delete_file"), tier=PermissionTier.ADMIN)
    assert res.allowed is False
    assert "二次确认" in res.reason


def test_secondary_confirm_queue():
    q = ApprovalQueue()
    res = guard(Action(kind="force_push"), tier=PermissionTier.ADMIN, queue=q)
    assert res.allowed is False and q.pending()


def test_secondary_confirm_pass_with_human_ok():
    res = guard(Action(kind="delete_file"), tier=PermissionTier.ADMIN, human_ok=True)
    assert res.allowed is True


def test_system_scope_command_needs_confirm():
    assert needs_secondary_confirmation(Action(kind="run_command", scope="system")) is True
    res = guard(Action(kind="run_command", scope="system"), tier=PermissionTier.OPERATOR)
    assert res.allowed is False
