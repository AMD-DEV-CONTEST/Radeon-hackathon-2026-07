"""XAI 系统面路由（补 B1/B2/B3/B5 缺口）。

S5-1 绞杀者模式：handler 签名 fn(h)，h 即 XAIHandler。
共享单例经 server_xai import *（惰性，bootstrap 在文件末尾，循环导入安全）+ server_runtime。

路由：
  GET /api/system/health    → 引擎健康摘要（豁免鉴权，L386 已在 bypass 名单）
  GET /api/system/sandbox   → 当前硬沙箱策略（豁免鉴权）
  GET /api/system/errors    → 系统级错误追踪（鉴权，前端 ErrorPanel 用）
  GET /api/system/status    → /api/status 的别名（兼容 xai-frontend 契约）
  GET /api/system/changelog → 最近版本变更（git log 最近 10 条）
"""
from __future__ import annotations
import platform
import shutil
import subprocess
import time
import os
from server_xai import *   # 共享单例 / 辅助（惰性导入，安全）
from server_runtime import get_engine

_BOOT_TS = int(time.time())
_SYSTEM_ERRORS: list[dict] = []   # 轻量错误环形缓冲（扩展点，供 adapter/executor 调用 record_system_error）
_ERROR_CAP = 200


def record_system_error(component: str, etype: str, message: str, trace_id: str = "") -> None:
    """扩展点：在关键执行路径捕获异常时调用，写入环形缓冲，供 /api/system/errors 展示。"""
    _SYSTEM_ERRORS.append({
        "ts": int(time.time()),
        "component": component,
        "type": etype,
        "message": message,
        "trace_id": trace_id,
    })
    if len(_SYSTEM_ERRORS) > _ERROR_CAP:
        _SYSTEM_ERRORS[:] = _SYSTEM_ERRORS[-_ERROR_CAP:]


def _sandbox_chain() -> list[str]:
    """检测当前系统可用的硬沙箱后端（四级自动回退链）。"""
    chain = []
    for name in ("nsjail", "firejail", "sandbox-exec"):
        if shutil.which(name):
            chain.append(name)
    return chain


def _handle_system_health(h):
    eng = get_engine()
    healthy = bool(getattr(eng, "xai_engine", None) or (LATEST_STATUS.get("xai_engine") == "running"))
    h._json_response(200, {
        "healthy": healthy,
        "ts": int(time.time()),
        **dict(LATEST_STATUS),
    })


def _handle_system_sandbox(h):
    chain = _sandbox_chain()
    h._json_response(200, {
        "os": platform.system(),
        "available_backends": chain,
        "policy": "hard-sandbox: nsjail > firejail > macOS sandbox-exec > setrlimit 四级自动回退",
        "effective": (chain[0] if chain else "setrlimit"),
        "note": "只读策略报告，不实际执行代码沙箱隔离。系统执行路径由 action_bus.run_hardened 在引擎内单独管理。",
    })


def _handle_system_errors(h):
    h._json_response(200, {
        "count": len(_SYSTEM_ERRORS),
        "tracked_since": _BOOT_TS,
        "errors": list(_SYSTEM_ERRORS),
    })


def _handle_system_status(h):
    # /api/status 的别名，兼容 xai-frontend 契约
    h._json_response(200, dict(LATEST_STATUS, ts=int(time.time())))


def _handle_system_changelog(h):
    """GET /api/system/changelog → 返回最近 10 条 git 提交记录。"""
    try:
        # 进程 cwd 或脚本所在目录作为 git 仓库根
        repo_dir = os.environ.get("XAI_REPO_DIR", os.path.expanduser("~/Desktop/mask/xai"))
        r = subprocess.run(
            ["git", "-C", repo_dir, "log", "--oneline", "-10", "--format=%h %s (%ai)"],
            capture_output=True, text=True, timeout=5,
        )
        commits = [line.strip() for line in r.stdout.strip().split("\n") if line.strip()]
        if not commits:
            commits = ["(无 git 记录)"]
        h._json_response(200, {"commits": commits, "total": len(commits)})
    except Exception as e:
        h._json_response(200, {"commits": [f"(无法读取 git: {e})"], "total": 0})


def register(router) -> None:
    router.add("GET", "/api/system/health", _handle_system_health)
    router.add("GET", "/api/system/sandbox", _handle_system_sandbox)
    router.add("GET", "/api/system/errors", _handle_system_errors)
    router.add("GET", "/api/system/status", _handle_system_status)
    router.add("GET", "/api/system/changelog", _handle_system_changelog)
