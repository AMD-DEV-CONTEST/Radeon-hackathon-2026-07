"""XAI 守卫桥接 —— 从 engine_xai.py 上帝类外移（Phase E）。

承载：
- create_approval(engine, ...)：创建待审批项（原子计数器 + 锁）
- guard_action(engine, text)：根据输入识别风险动作类型，供 Guardian 分级
- guard_for_coordination(engine, action)：CoordinationBus 的 Guardian 回调（P0/P1 转审批）

行为零变更：所有逻辑原样平移，仅 self -> engine。
"""

from __future__ import annotations

import time
from typing import Any, Dict, Tuple

from ..guardian import Action, RiskLevel, classify

# 高危操作关键词（命中即提升为 P0/P1 待审批，绝不静默放行）。
# 原属 engine_xai 类属性，Phase E 收敛到 guardian_bridge 作为本桥接的常量。
_DANGEROUS_PATTERNS = [
    "rm -rf", "rm -fr", "sudo rm", "mkfs", "format", "格式化",
    "force push", "强制推送", "git push --force", "git push -f",
    "del /f", "del /s", "rd /s", "rmdir /s",
    "drop table", "truncate table", "drop database",
]
_DELETE_PATTERNS = ["删除文件", "rm ", "del ", "rmdir ", "shutil.rmtree", "os.remove"]
_EXEC_PATTERNS = ["执行命令", "运行命令", "exec ", "bash ", "powershell", "sh -c"]
_NETWORK_PATTERNS = ["联网", "请求接口", "http://", "https://", "curl ", "fetch(", "访问网站"]


def create_approval(engine, action_type: str, action_detail: str, reason: str,
                    intent: str = "", session_id: str = "default") -> str:
    with engine._approval_lock:
        engine._approval_counter += 1
        aid = f"APR-{engine._approval_counter:04d}"
        engine._pending_approvals[aid] = {
            "type": action_type,
            "detail": action_detail,
            "intent": intent,
            "reason": reason,
            "status": "pending",
            "session": session_id,
        }
    return aid


def guard_action(engine, text: str) -> "Action":
    """根据用户输入内容识别风险动作类型，供 Guardian 分级。

    避免把一切聊天都当成 'general'（P2）而让 P0 闸门形同虚设；
    命中破坏性/删除/执行/网络等特征时升级对应风险等级。
    """
    t = text.lower()
    if any(p in t for p in _DANGEROUS_PATTERNS):
        return Action(kind="rm_rf", target=text[:200])
    if any(p in t for p in _DELETE_PATTERNS):
        return Action(kind="delete_file", target=text[:200])
    if any(p in t for p in _EXEC_PATTERNS):
        return Action(kind="run_command", target=text[:200])
    if any(p in t for p in _NETWORK_PATTERNS):
        return Action(kind="network", target=text[:200])
    return Action(kind="general", target=text[:200])


def guard_for_coordination(engine, action: dict) -> Tuple[bool, str]:
    """CoordinationBus 的 Guardian 回调：P0/P1 转审批。"""
    kind = action.get("kind", "")
    task = action.get("description", str(action))
    result = classify(Action(kind=kind or "general", target=task[:200]))
    if result.level == RiskLevel.P0:
        return False, f"P0高风险: {result.reason}"
    if result.level == RiskLevel.P1:
        return False, f"P1需审批: {result.reason}"
    return True, ""


def resolve_approval(engine, aid: str, human_ok: bool, reason: str = "") -> Dict[str, Any]:
    """人工审批处置（P0 闸门落地闭环）。

    对应前端画布 HITL 节点的「批准 / 拒绝 + 理由」。
    - human_ok=True  → 标记 approved，P0 放行（写 failure_correction? 否，仅放行记录）
    - human_ok=False → 标记 rejected，动作被拦截
    幂等：已处置的工单再次调用只返回原状态，不重复副作用。
    """
    with engine._approval_lock:
        item = engine._pending_approvals.get(aid)
        if item is None:
            return {"ok": False, "error": f"未知工单 {aid}", "id": aid}
        if item.get("status") != "pending":
            return {"ok": True, "id": aid, "status": item.get("status"),
                    "already_resolved": True}
        item["status"] = "approved" if human_ok else "rejected"
        item["resolved_at"] = time.time()
        item["resolution_reason"] = reason
        item["human_ok"] = human_ok
    # 放行后给引擎一个续跑钩子（若存在），让被挂起的任务继续
    hook = getattr(engine, "_on_approval_resolved", None)
    if callable(hook):
        try:
            hook(aid, human_ok, reason)
        except Exception:
            pass
    return {"ok": True, "id": aid, "status": item["status"],
            "type": item.get("type"), "detail": item.get("detail")}


def pending_approvals(engine) -> list:
    """返回待审批列表，并附带风险等级（供前端画布高亮）。"""
    out = []
    for aid, item in engine._pending_approvals.items():
        if item.get("status") != "pending":
            continue
        kind = item.get("type", "general")
        lvl = classify(Action(kind=kind, target=item.get("detail", "")[:200])).level
        out.append({
            "id": aid,
            "type": kind,
            "detail": item.get("detail", ""),
            "intent": item.get("intent", ""),
            "reason": item.get("reason", ""),
            "session": item.get("session", "default"),
            "level": int(lvl),
            "level_name": lvl.name,
            "status": item.get("status"),
        })
    return out
