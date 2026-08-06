#!/usr/bin/env python3
"""XAI 统一后端服务

零外部依赖，Python 标准库 http.server + SSE 流式。
所有路由：
  GET  /              → 前端（index.html）
  GET  /web/<file>    → 静态资源（app.js, styles.css）
  GET  /api/status    → 系统状态
  POST /api/chat      → SSE 流式对话
  POST /api/chat/send → 非流式对话
  GET  /api/memory    → 记忆统计
  GET  /api/approvals → 待审批列表
  POST /api/upload    → 上传本地文件（base64 JSON）→ 落盘 workspace/uploads/
  POST /api/save      → 保存生成内容为文件（artifacts/）→ 返回 stored 名
  GET  /api/open      → 在本机用默认应用打开文件（macOS open / Linux xdg-open）
"""

from __future__ import annotations
import sys

# 身份对齐：以 `python3 server_xai.py` 运行时模块名为 __main__，
# 而子模块用 `from server_xai import *` 解析 server_xai，二者非同一对象会导致
# 循环导入。对齐 sys.modules 使子模块拿到同一个（已完整初始化的）模块实例。
if __name__ == "__main__":
    sys.modules["server_xai"] = sys.modules["__main__"]

import os
import sys
import json
import time
import base64
import subprocess
import platform
import urllib.parse
import traceback
import tarfile
import tempfile
import io
import gzip
import shutil
import glob as _glob
import sqlite3
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from pathlib import Path
import logging
import logging.handlers

# 添加 core 到 Python 路径
sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.kernel.engine import XAIEngine
from core.distill import GepaScheduler, EvolutionStatus
from core import app_store
from core.observability import global_tracer
from core.adapters.knowledge_adapter import KnowledgeAdapter


# ---- 共享运行时单例（抽至 server_runtime，避免循环/双导入）----
from server_runtime import get_engine, get_knowledge_adapter, _CAPABILITIES


# ---- 工作流执行历史（C3 系统监控仪表盘）----
_WORKFLOW_HISTORY: list[dict] = []

# ---- AgentHub 群聊房间存储 ----
_hub_rooms: dict[str, dict] = {}

# ---- 工作流队列并发控制 ----
import threading as _threading
_ACTIVE_QUEUES: dict[str, dict] = {}  # queue_name → {"cancel": threading.Event, "start_ts": float}
_queues_lock = _threading.Lock()

# ---- 基础鉴权 ----
_SERVER_TOKEN = None

def _init_auth() -> str:
    """生成或读取服务令牌。"""
    import secrets as _secrets
    token_path = os.path.join(os.environ.get("XAI_HOME", os.path.expanduser("~/.xai")), ".server_token")
    try:
        with open(token_path, "r") as f:
            return f.read().strip()
    except Exception:
        token = "xai-" + _secrets.token_hex(16)
        os.makedirs(os.path.dirname(token_path), exist_ok=True)
        with open(token_path, "w") as f:
            f.write(token)
        print(f"[xai] 新令牌已生成: {token}", flush=True)
        return token

_SERVER_TOKEN = _init_auth()


def _record_workflow_run(nodes_count: int, edges_count: int, events: list[dict], start_ts: float) -> None:
    duration = round(time.time() - start_ts, 2)
    has_error = any(ev.get("status") == "error" or ev.get("type") == "error" for ev in events)
    status = "error" if has_error else "done"
    node_types: dict[str, int] = {}
    for ev in events:
        nt = ev.get("node_type", "") or ev.get("type", "")
        if nt and nt not in ("wf_start", "wf_done", "wf_node", "progress", "token", "error"):
            node_types[nt] = node_types.get(nt, 0) + 1
    _WORKFLOW_HISTORY.append({
        "id": f"wf-{int(start_ts)}",
        "ts": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(start_ts)),
        "nodes_count": nodes_count,
        "edges_count": edges_count,
        "status": status,
        "duration": duration,
        "node_types": node_types,
    })
    # 只保留最近 200 条
    if len(_WORKFLOW_HISTORY) > 200:
        _WORKFLOW_HISTORY[:] = _WORKFLOW_HISTORY[-200:]


def _diagnose(error_msg: str) -> str:
    """为工作流错误生成简短诊断建议。"""
    if not error_msg:
        return "未知错误，查看完整日志"
    msg = error_msg.lower()
    if "超时" in msg or "timeout" in msg:
        return "节点执行超过限制，建议拆分任务或增加 timeout"
    if any(w in msg for w in ("不可用", "not found", "no such file", "command not found", "不存在")):
        return "Grok Build 未检测到，检查 grok 二进制路径"
    if any(w in msg for w in ("解析失败", "parse", "json", "格式", "syntax", "invalid")):
        return "上游节点输出格式异常，检查 JSON 结构"
    return "未知错误，查看完整日志"


# ---- 应用层资源（任务 / 专家团 / 自动化 / 定时 / 画布）----
# app_store 已含完整 CRUD，这里仅做 HTTP 接线 + 定时调度线程。
_APP_RESOURCES = {
    "tasks":       ("task",   app_store.tasks_list,       app_store.task_get,       app_store.task_create,       app_store.task_update,       app_store.task_delete),
    "teams":       ("team",   app_store.teams_list,       app_store.team_get,       app_store.team_create,       app_store.team_update,       app_store.team_delete),
    "automations": ("auto",   app_store.automations_list, app_store.automation_get, app_store.automation_create, app_store.automation_update, app_store.automation_delete),
    "schedules":   ("sched",  app_store.schedules_list,   app_store.schedule_get,   app_store.schedule_create,   app_store.schedule_update,   app_store.schedule_delete),
}


# ---- 全局事件总线（D1 实时事件总线 SSE）----
import threading as _thr
_EVENT_SUBS: list = []
_EVENT_BUF: list = []
_EVENT_LOCK = _thr.Lock()
# 心跳线程维护的最新状态快照，/api/status 直接返回（即时，不阻塞）
LATEST_STATUS: dict = {"xai_engine": "starting"}


def _emit_event(ev: dict):
    with _EVENT_LOCK:
        _EVENT_BUF.append(ev)
        if len(_EVENT_BUF) > 50:
            _EVENT_BUF.pop(0)
        for q in list(_EVENT_SUBS):
            try:
                q.put_nowait(ev)
            except Exception:
                pass


def _event_heartbeat():
    import queue as _que

    def _loop():
        while True:
            try:
                st = _safe_status()
                LATEST_STATUS.clear()
                LATEST_STATUS.update(st)
                _emit_event({"type": "status", "ts": int(time.time()), "data": st})
                eng = get_engine()
                _emit_event({"type": "approvals", "ts": int(time.time()),
                             "data": getattr(eng, "_pending_approvals", [])})
            except Exception:
                pass
            time.sleep(5)

    _thr.Thread(target=_loop, daemon=True, name="xai-event-hb").start()


# ---- 能力注册表（D2 单一事实源）已迁至 server_runtime._CAPABILITIES ----


# ---- 意图分类（D3 后端意图置信度）----
def _classify_intent(text: str) -> dict:
    t = (text or "").lower()
    rules = [
        ("code", ["代码", "写", "实现", "bug", "函数", "class", "def", "修复", "脚本", "script"]),
        ("research", ["调研", "搜索", "查", "资料", "对比", "分析", "总结", "search"]),
        ("automation", ["定时", "自动化", "schedule", "cron", "每天", "每周", "触发"]),
        ("agent", ["专家", "团", "群聊", "协作", "分配", "agent"]),
        ("memory", ["记住", "记忆", "回顾", "之前", "总结一下"]),
        ("file", ["文件", "保存", "上传", "打开", "导出", "下载"]),
        ("workflow", ["流程", "画布", "节点", "编排", "workflow"]),
        ("canvas_action", ["添加节点", "修改连线", "清除画布", "增加节点", "删除节点", "连接", "断开连线"]),
    ]
    best, score = "chat", 0
    for intent, kws in rules:
        s = sum(1 for k in kws if k in t)
        if s > score:
            best, score = intent, s
    conf = min(0.95, 0.5 + 0.15 * score) if score > 0 else 0.4
    # E2 双核融合：意图 → 内核路由（Hermes 推理 / Grok Build 工程 / OpenClaw 执行）
    KERNEL_MAP = {
        "code": "grok_build",
        "file": "openclaw",
        "workflow": "openclaw",
        "canvas_action": "openclaw",
        "automation": "openclaw",
        "research": "hermes",
        "agent": "hermes",
        "memory": "hermes",
        "chat": "hermes",
    }
    return {"intent": best, "confidence": round(conf, 2), "kernel": KERNEL_MAP.get(best, "hermes")}


def _scaffold_system_prompt() -> str:
    """结构化输出脚手架：要求模型按 结论 → 结构化要点 → 下一步行动 格式输出"""
    return (
        "【输出格式要求】\n"
        "请严格按照以下三段式结构组织你的回答：\n\n"
        "## 结论\n"
        "一句话总结你的核心回答或判断。\n\n"
        "## 结构化要点\n"
        "- 使用无序列表，每行一个要点\n"
        "- 要点应具体、可操作，避免空泛描述\n"
        "- 如有技术内容，附带关键代码片段或命令\n\n"
        "## 下一步行动\n"
        "- 列出用户接下来可以执行的 1-3 个具体步骤\n"
        "- 每个步骤应前置动词（如：运行、检查、确认、部署）\n\n"
        "注意：不要在上述三段之外添加额外的总结或结束语。"
    )


# ---- 计划持久化（D5 按对话落库）----
def _plans_path() -> str:
    eng = get_engine()
    return os.path.join(eng.openclaw.workspace_path(""), "plans.json")


def _plans_load() -> dict:
    p = _plans_path()
    if os.path.exists(p):
        try:
            return json.load(open(p, encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _plans_save(d: dict):
    p = _plans_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)


def _execute_prompt(prompt: str, session: str) -> tuple[bool, str]:
    """真实调用引擎执行一段提示词（定时/自动化共用）。返回 (ok, detail)。"""
    try:
        eng = get_engine()
        n = 0
        for ev in eng.chat(prompt, session):
            n += 1
        return True, f"已处理 {n} 个事件"
    except Exception as e:
        return False, str(e)[:300]


def _start_scheduler():
    """后台调度线程：轮询定时任务 + 自动化(定时型)，按 cron/频率到点真调引擎。daemon。"""
    import threading as _t
    from core import cronutil

    def _is_due(item: dict) -> bool:
        cron = item.get("cron", "")
        tz = item.get("timezone") or app_store.settings_get_value("scheduler.timezone", "Asia/Shanghai")
        if cron:
            dt = cronutil.next_run(cron, tz)
            if dt is None:
                return False
            # 下次触发在「此刻之前或等于此刻」说明这一拍已到期：比较到分钟
            now = time.localtime()
            due_dt = dt.replace(second=0, microsecond=0)
            cur = time.strftime("%Y-%m-%d %H:%M", now)
            due_str = due_dt.strftime("%Y-%m-%d %H:%M")
            # 若下次触发时间 <= 当前分钟的下一分钟窗口，视为到期
            last = item.get("last_run", "")[:16]
            return due_str <= cur and last != due_str
        # 兼容旧版 frequency/run_time
        freq = item.get("frequency", "daily")
        rt = item.get("run_time", "09:00")
        now = time.localtime()
        now_hm = f"{now.tm_hour:02d}:{now.tm_min:02d}"
        today = time.strftime("%Y-%m-%d")
        if freq == "daily":
            return (now_hm >= rt) and (item.get("last_run", "")[:10] != today)
        if freq == "hourly":
            return item.get("last_run", "")[:16] != f"{today} {now_hm}"
        return False

    def _loop():
        while True:
            try:
                # 定时任务
                for s in app_store.schedules_list():
                    if not s.get("enabled") or not s.get("prompt"):
                        continue
                    if _is_due(s):
                        ok, detail = _execute_prompt(s["prompt"], f"sched:{s['id']}")
                        app_store.schedule_mark_run(s["id"], ok=ok, detail=detail)
                        print(f"[xai-sched] 定时任务 {s['id']} -> {'OK' if ok else 'FAIL'}: {detail}")
                # 自动化（仅定时型；事件型由 webhook/手动触发）
                for a in app_store.automations_list():
                    if not a.get("enabled"):
                        continue
                    trig = a.get("trigger") or {}
                    if trig.get("type", "schedule") != "schedule":
                        continue
                    if not (a.get("prompt") or a.get("workflow_id")):
                        continue
                    if _is_due(a):
                        ok, detail = _execute_prompt(a.get("prompt", ""), f"auto:{a['id']}")
                        app_store.automation_mark_run(a["id"], ok=ok, detail=detail)
                        print(f"[xai-sched] 自动化 {a['id']} -> {'OK' if ok else 'FAIL'}: {detail}")
            except Exception as e:
                print(f"[xai-sched] 轮询异常: {e}")
            time.sleep(30)

    _t.Thread(target=_loop, daemon=True, name="xai-scheduler").start()
    print("[xai] 定时调度线程已启动（支持 cron + 自动化）")


_STATUS_CACHE: dict = {"ts": 0.0, "data": None}
_STATUS_TTL: float = 5.0

def _safe_status(timeout: int = 8) -> dict:
    """带缓存 + 线程超时的状态查询，避免适配器 health_check 阻塞拖垮 /api/status。"""
    import threading as _t
    now = time.time()
    if _STATUS_CACHE["data"] is not None and now - _STATUS_CACHE["ts"] < _STATUS_TTL:
        return _STATUS_CACHE["data"]
    engine = get_engine()
    box: dict = {}
    def _run():
        try:
            box["v"] = engine.status()
        except Exception as e:
            box["e"] = str(e)
    th = _t.Thread(target=_run, daemon=True)
    th.start()
    th.join(timeout)
    if "v" in box:
        _STATUS_CACHE["ts"], _STATUS_CACHE["data"] = now, box["v"]
        return box["v"]
    if "e" in box:
        return {"xai_engine": "running", "error": box["e"]}
    # 超时兜底：返回上一次缓存（若有），否则轻量结果并写入缓存避免反复阻塞
    if _STATUS_CACHE["data"] is not None:
        return _STATUS_CACHE["data"]
    degraded = {"xai_engine": "running", "model": "unknown",
                "note": f"状态查询超时({timeout}s)：某适配器 health_check 阻塞（已降级）"}
    _STATUS_CACHE["ts"], _STATUS_CACHE["data"] = now, degraded
    return degraded


# ---- HTTP 处理器 ----

# A0=a 决策：V4 frontend/ 为产品，:8000 直接服务其生产构建（同源 /api 调用）
WEB_DIR = Path(__file__).resolve().parent / "frontend" / "dist"
LEGACY_WEB_DIR = Path(__file__).resolve().parent / "web"


class ThreadingXAIHTTPServer(ThreadingMixIn, HTTPServer):
    """多线程 HTTP 服务器，不阻塞其他请求"""
    pass


class XAIHandler(BaseHTTPRequestHandler):
    """HTTP 请求处理器"""

    def log_message(self, format, *args):
        print(f"[xai] {args[0]}", flush=True)

    def handle_one_request(self):
        """兜底吞掉客户端提前断开导致的管道异常。

        浏览器刷新、SSE 取消、curl -o /dev/null 都会让对端先关闭连接，
        BaseHTTPRequestHandler 默认会把 BrokenPipeError 冒泡到 socketserver
        并打印整页堆栈，日志被淹没且掩盖真实错误。这里统一收口。
        """
        try:
            super().handle_one_request()
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

    def _check_auth(self) -> bool:
        """验证请求令牌（health/sandbox/token/static 端点豁免）。"""
        if self.path in ("/api/system/health", "/api/system/sandbox", "/api/auth/token"):
            return True
        # 静态前端文件豁免鉴权
        if not self.path.startswith("/api/"):
            return True
        token = self.headers.get("X-Auth-Token", "")
        return token == _SERVER_TOKEN

    # ---- 路由分发 ----

    def do_GET(self):
        if not self._check_auth():
            self._json_response(401, {"error": "未授权"})
            return
        path = self.path.split("?")[0]
        # 修复（2026-08-04）：此前从不解码百分号编码，导致任何含非 ASCII 或保留字符
        # 的路径参数全部失配 —— 中文命名的技能/MCP/连接器在前端点"更新/删除"时，
        # 浏览器 fetch 会自动编码 URL，后端拿到 %E4%B8%AD... 与真实名字对不上而报错。
        # 只对 /api/ 解码：静态资源保持原样，避免 %2F 解出斜杠造成路径穿越。
        if path.startswith("/api/") and "%" in path:
            path = urllib.parse.unquote(path)
        # 已迁移路由经注册表优先分发（绞杀者模式）；未命中走下方 legacy 分支
        if _ROUTER.dispatch("GET", path, self):
            return
        elif path == "/api/auth/token":
            # 防御性校验：仅本机回环地址可获取主令牌。
            # 服务仅绑 127.0.0.1，此为纵深防御——防止未来误绑 0.0.0.0 时任意来源拿令牌。
            remote = self.client_address[0]
            if remote not in ("127.0.0.1", "::1", "::ffff:127.0.0.1"):
                self._json_response(403, {"error": "仅允许本机获取令牌"})
                return
            self._json_response(200, {"token": _SERVER_TOKEN})
        elif path == "/":
            self._serve_frontend()
        elif path.startswith("/web/"):
            self._serve_static(path[len("/web/"):], root=LEGACY_WEB_DIR)
        elif not path.startswith("/api/"):
            self._serve_static(path)
        elif path == "/api/memos":
            self._handle_memos_get(); return
        elif path == "/api/status":
            self._json_response(200, dict(LATEST_STATUS, ts=int(time.time())))
        elif path == "/api/memory":
            eng = get_engine()
            mem_adapter_stats = eng.memory_core.stats()
            mem_core_stats = eng.memory_core.stats()
            self._json_response(200, {
                "adapter": mem_adapter_stats,
                "core": mem_core_stats,
                "core_db": eng.memory_core.db_path,
            })
        # 注：GET /api/memory/list 已由 server_routes_memory.py 接管，
        # legacy 分支永不可达，已于 2026-08-04 删除（B2 路由收敛）。
        elif path.startswith("/api/memory/search"):
            # 修复（2026-08-04）：此前不把关键词下推 SQL，而是先取"重要性最高的
            # limit*10 条"再在内存里子串匹配，且只匹配 value 不匹配 key。
            # 结果：只要目标记忆不在 top-N 就永远搜不到，记忆检索形同虚设。
            # 现改为 keyword 走 SQL（key/value 双字段 LIKE），再按命中次数打分排序。
            eng = get_engine()
            qs = self.path.split("?")[-1] if "?" in self.path else ""
            params = dict(urllib.parse.parse_qsl(qs))
            q = (params.get("q") or "").strip()
            layer = params.get("layer") or None
            limit = int(params.get("limit", 5))
            entries = eng.memory_core.query(
                layer=layer, keyword=q or None, limit=max(limit * 10, 200))
            q_lower = q.lower()
            results = []
            for e in entries:
                key = getattr(e, "key", "") or ""
                val = getattr(e, "value", "") or ""
                if q_lower:
                    # key 命中权重更高（key 通常是标题/标识）
                    score = key.lower().count(q_lower) * 3 + val.lower().count(q_lower)
                else:
                    score = 1
                if score > 0:
                    results.append({"layer": getattr(e, "layer", ""), "key": key,
                                    "value": val[:500], "score": score,
                                    "importance": getattr(e, "importance", 0)})
            results.sort(key=lambda x: (x["score"], x["importance"]), reverse=True)
            self._json_response(200, {"query": q, "layer": layer,
                                      "total": len(results), "results": results[:limit]})
        elif path == "/api/approvals":
            self._json_response(200, {"approvals": get_engine()._pending_approvals})
        elif path == "/api/guardian/pending":
            # HITL 画布内嵌：前端轮询（1.5s）拉取 P0 待确认工单
            from core.kernel.guardian_bridge import pending_approvals
            self._json_response(200, {"pending": pending_approvals(get_engine())})
        elif path == "/api/history":
            self._json_response(200, {"sessions": get_engine()._sessions.list_sessions()})
        elif path.startswith("/api/sessions/") and path.endswith("/messages"):
            # GET /api/sessions/<id>/messages → 返回 session 消息历史
            sid = path[len("/api/sessions/"):-len("/messages")]
            msgs = get_engine()._sessions.get_history(sid, limit=500)
            self._json_response(200, {"messages": msgs, "session": {"id": sid}})
        elif path.startswith("/api/session/"):
            sid = path.split("/")[-1]
            self._json_response(200, {"session": sid, "messages": get_engine()._sessions.get_history(sid, limit=200)})
        elif path == "/api/agents":
            eng = get_engine()
            agents = [{"name": a.name, "role": a.role, "backend": a.backend, "id": a.id} for a in eng.coordination.list_agents()]
            rooms = eng.coordination.list_rooms()
            self._json_response(200, {"agents": agents, "rooms": rooms})
        elif path == "/api/coordination/rooms":
            self._json_response(200, {"rooms": get_engine().coordination.list_rooms()})
        elif path == "/api/coordination":
            self._json_response(200, {"rooms": get_engine().coordination.list_rooms(), "status": "ok"})
        elif path.startswith("/api/hub/rooms/") and path.endswith("/messages"):
            # GET /api/hub/rooms/<id>/messages
            rid = path[len("/api/hub/rooms/"):-len("/messages")]
            msgs = _hub_rooms.get(rid, {}).get("messages", [])
            self._json_response(200, {"messages": msgs})
        elif path == "/api/hub/rooms" or path == "/api/hub/rooms/":
            # GET /api/hub/rooms → 返回持久化房间列表
            rooms = [{"id": k, "name": v.get("name", k), "topic": v.get("topic", ""), "agents": v.get("agents", []), "created_at": v.get("created_at", "")} for k, v in _hub_rooms.items()]
            self._json_response(200, {"rooms": rooms})
        elif path == "/api/loop":
            eng = get_engine()
            loop = eng.cognitive_loop if hasattr(eng, "cognitive_loop") else None
            self._json_response(200, {
                "running": loop.running if loop and hasattr(loop, "running") else False,
                "iterations": loop.iteration if loop and hasattr(loop, "iteration") else 0,
                "last_cycle": loop.last_cycle if loop and hasattr(loop, "last_cycle") else "",
                "status": loop.status if loop and hasattr(loop, "status") else "idle",
            })
        elif path == "/api/memory/stats":
            self._json_response(200, self._memory_stats_payload())
        elif path == "/api/tags":
            tags = app_store.tags_list() if hasattr(app_store, "tags_list") else []
            self._json_response(200, {"tags": tags if tags else [{"name": "技术", "color": "#2563eb"}, {"name": "业务", "color": "#059669"}, {"name": "紧急", "color": "#dc2626"}, {"name": "常规", "color": "#6b7280"}]})
        elif path == "/api/team":
            self._json_response(200, {"members": []})
        elif path == "/api/models/local":
            try:
                import urllib.request as _ur
                req = _ur.Request("http://127.0.0.1:11434/v1/models")
                with _ur.urlopen(req, timeout=2) as resp:
                    data = json.loads(resp.read())
                models = [{"id": m.get("id", ""), "owned_by": m.get("owned_by", "llamacpp")}
                          for m in data.get("data", [])]
                self._json_response(200, {"available": True, "models": models})
            except Exception:
                self._json_response(200, {"available": False, "models": []})
        elif path == "/api/models/list":
            reg = get_engine().model_registry
            models = [{"id": m.id, "name": m.name, "provider": m.provider, "model": m.model, "base_url": m.base_url, "api_key": m.mask_key(), "is_active": m.is_active, "vision": m.is_vision(), "created_at": m.created_at} for m in reg.list()]
            self._json_response(200, {"models": models, "stats": reg.stats()})
        elif path.startswith("/api/models/activate/"):
            mid = path.split("/")[-1]
            result = get_engine().model_registry.activate(mid)
            if result:
                get_engine()._rebuild_backend()
                self._json_response(200, {"ok": True, "active": result.to_dict(mask=True)})
            else:
                self._json_response(404, {"ok": False, "error": "模型不存在"})
        elif path == "/api/loop-safety":
            eng = get_engine()
            self._json_response(200, eng.loop_safety.status())
        elif path == "/api/knowledge/ingest":
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            res = get_knowledge_adapter().execute(
                {"op": "ingest", "paths": data.get("paths", [])})
            self._json_response(200, {"ok": res.ok, "output": res.output,
                                      "meta": res.meta, "error": res.error})
        elif path == "/api/knowledge/search":
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            res = get_knowledge_adapter().execute(
                {"op": "search", "query": data.get("query", ""), "top_k": data.get("top_k", 5)})
            self._json_response(200, {"ok": res.ok,
                                      "hits": res.meta.get("hits", []), "error": res.error})
        elif path == "/api/knowledge/stats":
            res = get_knowledge_adapter().execute({"op": "stats"})
            self._json_response(200, {"ok": res.ok,
                                      "stats": res.meta.get("stats", {}), "error": res.error})
        elif path == "/api/knowledge/clear":
            res = get_knowledge_adapter().execute({"op": "clear"})
            self._json_response(200, {"ok": res.ok, "output": res.output,
                                      "meta": res.meta, "error": res.error})
        elif path == "/api/plans":
            self._json_response(200, {"plans": list(_plans_load().values())})
        elif path == "/api/settings":
            self._json_response(200, app_store.settings_get())
        elif path == "/api/projects":
            pm = get_engine().project_manager
            current = pm.current()
            self._json_response(200, {
                "current": {"id": current.id, "name": current.name} if current else None,
                "list": [{"id": p.id, "name": p.name, "description": p.description, "workspace": p.workspace, "created_at": p.created_at} for p in pm.list()],
            })
        elif path.startswith("/api/projects/activate/"):
            pid = path.split("/")[-1]
            result = get_engine().project_manager.activate(pid)
            self._json_response(200 if result else 404, {"ok": result is not None, "project": result.name if result else None})
        elif self._try_app_get(path):
            pass
        elif path == "/api/canvas/list_all":
            raw = app_store.canvas_list()
            # 过滤空 ID / 无意义路由残留
            names = [n for n in raw if n.get("id") and n["id"] not in ("list", "list_all")]
            self._json_response(200, {"list": names})
        elif path == "/api/canvas/history":
            cid = "main"
            self._json_response(200, {"history": app_store.canvas_history(cid)})
        elif path.startswith("/api/canvas/history/"):
            cid = path[len("/api/canvas/history/"):]
            self._json_response(200, {"history": app_store.canvas_history(cid)})
        elif path == "/api/canvas" or path.startswith("/api/canvas/"):
            cid = "main" if path == "/api/canvas" else path[len("/api/canvas/"):]
            self._json_response(200, app_store.canvas_get(cid))
        elif path == "/api/workflow/history":
            self._json_response(200, {"history": _WORKFLOW_HISTORY})
        elif path == "/api/capabilities":
            self._handle_capabilities()
        elif path == "/api/orchestrations":
            self._handle_orchestrations_list()
        elif path == "/api/memory/visualize":
            self._handle_memory_visualize()
        else:
            self._json_response(404, {"error": "Not Found", "path": path})

    def do_OPTIONS(self):
        # CORS 预检：浏览器从 :5180 跨域访问 :8000 必须支持 OPTIONS
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()

    def do_PUT(self):
        path = self.path.split("?")[0]
        # 修复（2026-08-04）：此前从不解码百分号编码，导致任何含非 ASCII 或保留字符
        # 的路径参数全部失配 —— 中文命名的技能/MCP/连接器在前端点"更新/删除"时，
        # 浏览器 fetch 会自动编码 URL，后端拿到 %E4%B8%AD... 与真实名字对不上而报错。
        # 只对 /api/ 解码：静态资源保持原样，避免 %2F 解出斜杠造成路径穿越。
        if path.startswith("/api/") and "%" in path:
            path = urllib.parse.unquote(path)
        if _ROUTER.dispatch("PUT", path, self):
            return
        elif path.startswith("/api/mcp/update/"):
            try:
                mcp_id = int(path.split("/")[-1])
            except ValueError:
                self._json_response(400, {"error": "无效的 MCP ID"})
                return
            self._handle_mcp_update(mcp_id)
        elif path.startswith("/api/skill/update/"):
            try:
                skill_id = int(path.split("/")[-1])
            except ValueError:
                self._json_response(400, {"error": "无效的 Skill ID"})
                return
            self._handle_skill_update(skill_id)
        else:
            self._json_response(404, {"error": "Not Found", "path": path})

    def do_DELETE(self):
        path = self.path.split("?")[0]
        # 修复（2026-08-04）：此前从不解码百分号编码，导致任何含非 ASCII 或保留字符
        # 的路径参数全部失配 —— 中文命名的技能/MCP/连接器在前端点"更新/删除"时，
        # 浏览器 fetch 会自动编码 URL，后端拿到 %E4%B8%AD... 与真实名字对不上而报错。
        # 只对 /api/ 解码：静态资源保持原样，避免 %2F 解出斜杠造成路径穿越。
        if path.startswith("/api/") and "%" in path:
            path = urllib.parse.unquote(path)
        if _ROUTER.dispatch("DELETE", path, self):
            return
        elif path.startswith("/api/mcp/delete/"):
            try:
                mcp_id = int(path.split("/")[-1])
            except ValueError:
                self._json_response(400, {"error": "无效的 MCP ID"})
                return
            self._handle_mcp_delete(mcp_id)
        elif path.startswith("/api/skill/delete/"):
            try:
                skill_id = int(path.split("/")[-1])
            except ValueError:
                self._json_response(400, {"error": "无效的 Skill ID"})
                return
            self._handle_skill_delete(skill_id)
        elif path.startswith("/api/sessions/"):
            # DELETE /api/sessions/<id> → 删除会话
            sid = path[len("/api/sessions/"):]
            if sid:
                eng = get_engine()
                eng._sessions.clear(sid)
                self._json_response(200, {"ok": True, "deleted": sid})
            else:
                self._json_response(400, {"error": "缺少 session id"})
        else:
            self._json_response(404, {"error": "Not Found", "path": path})


    def do_POST(self):
        if not self._check_auth():
            self._json_response(401, {"error": "未授权"})
            return
        path = self.path.split("?")[0]
        # 修复（2026-08-04）：此前从不解码百分号编码，导致任何含非 ASCII 或保留字符
        # 的路径参数全部失配 —— 中文命名的技能/MCP/连接器在前端点"更新/删除"时，
        # 浏览器 fetch 会自动编码 URL，后端拿到 %E4%B8%AD... 与真实名字对不上而报错。
        # 只对 /api/ 解码：静态资源保持原样，避免 %2F 解出斜杠造成路径穿越。
        if path.startswith("/api/") and "%" in path:
            path = urllib.parse.unquote(path)
        if _ROUTER.dispatch("POST", path, self):
            return

        if self._try_app_post(path):
            pass
        elif path == "/api/memos" or path.startswith("/api/memos/"):
            self._handle_memos(); return
        elif path == "/api/guardian/grok-write/request":
            self._handle_guardian_grok_write_request(); return
        elif path == "/api/canvas/delete":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                data = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            except Exception:
                data = {}
            # 修复（2026-08-04）：与 _handle_canvas_save 对齐，同时接受 canvas_id 别名，
            # 否则客户端传 canvas_id 时 cid 回落 "main"，真画布删不掉还误删公共画布。
            cid = data.get("id") or data.get("canvas_id") or "main"
            self._json_response(200, app_store.canvas_delete(cid))
        elif path.startswith("/api/hub/rooms/") and path.endswith("/send"):
            # POST /api/hub/rooms/<id>/send
            rid = path[len("/api/hub/rooms/"):-len("/send")]
            self._handle_hub_send(rid)
        elif path == "/api/orchestrations" or path.startswith("/api/orchestrations/"):
            # POST /api/orchestrations → 创建；/api/orchestrations/<id>/<action> → 暂停/继续/终止/删除
            self._handle_orchestrations()
        elif path == "/api/knowledge/ingest":
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            res = get_knowledge_adapter().execute(
                {"op": "ingest", "paths": data.get("paths", [])})
            self._json_response(200, {"ok": res.ok, "output": res.output,
                                      "meta": res.meta, "error": res.error})
            return
        elif path == "/api/knowledge/search":
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            res = get_knowledge_adapter().execute(
                {"op": "search", "query": data.get("query", ""), "top_k": data.get("top_k", 5)})
            self._json_response(200, {"ok": res.ok,
                                      "hits": res.meta.get("hits", []), "error": res.error})
        else:
            self._json_response(404, {"error": "Not Found", "path": path})

    # ---- 响应方法 ----

    def _json_response(self, code: int, data: dict):
        body = json.dumps(data, ensure_ascii=False, indent=2)
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body.encode("utf-8"))))
            self.end_headers()
            self.wfile.write(body.encode("utf-8"))
        except (BrokenPipeError, ConnectionResetError):
            # 客户端提前断开（curl -o /dev/null、页面刷新、取消请求）属正常情况，
            # 不应打整页堆栈污染日志。
            self.close_connection = True

    def _serve_frontend(self):
        index = WEB_DIR / "index.html"
        if not index.exists():
            self._json_response(404, {"error": "index.html not found"})
            return
        content = index.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.end_headers()
        self.wfile.write(content)

    def _serve_static(self, path: str, root: Path | None = None):
        # 去掉查询串与开头斜杠，定位到指定根目录（默认 WEB_DIR / React 产物；/web/ 走 LEGACY_WEB_DIR）
        rel = path.split("?")[0].lstrip("/")
        base = (root or WEB_DIR).resolve()
        file_path = (base / rel).resolve()
        # 防目录穿越
        if not str(file_path).startswith(str(base)):
            self._json_response(404, {"error": "forbidden"})
            return
        if not file_path.exists() or file_path.is_dir():
            # SPA 回退：未知路径返回对应根目录的 index.html
            index = base / "index.html"
            if index.exists():
                file_path = index
            else:
                self._serve_frontend()
                return
        ext = file_path.suffix.lower()
        ct = {
            ".js": "text/javascript", ".mjs": "text/javascript",
            ".css": "text/css", ".html": "text/html",
            ".svg": "image/svg+xml", ".json": "application/json",
            ".webmanifest": "application/manifest+json",
            ".png": "image/png", ".ico": "image/x-icon",
            ".woff2": "font/woff2", ".woff": "font/woff",
            ".ttf": "font/ttf", ".map": "application/json",
        }.get(ext, "application/octet-stream")
        content = file_path.read_bytes()
        self.send_response(200)
        charset = "charset=utf-8" if ct.startswith("text") or ct in ("application/json", "application/manifest+json") else ""
        self.send_header("Content-Type", f"{ct}; {charset}".strip() if charset else ct)
        self.send_header("Content-Length", str(len(content)))
        # index.html / sw.js 强制不缓存；带 hash 的静态资源可长期缓存
        if rel.endswith("index.html") or rel.endswith("sw.js"):
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
        else:
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        self.end_headers()
        self.wfile.write(content)

    # ---- 对话处理 ----


    def _sse_error(self, error: str, detail: str = ""):
        """SSE 错误响应快速通道"""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.close_connection = True
        ev = {"type": "error", "error": error, "detail": detail[:200]}
        self.wfile.write(f"data: {json.dumps(ev, ensure_ascii=False)}\n\n".encode("utf-8"))
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def _workflow_from_text_sse(self, dag: dict, text: str):
        """SSE 流式发射 wf_node_spawn 事件，每个节点一个事件，增量渲染画布。"""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.close_connection = True

        nodes = dag.get("nodes", [])
        edges = dag.get("edges", [])

        try:
            for i, node in enumerate(nodes):
                ev = {
                    "type": "wf_node_spawn",
                    "node": node,
                    "index": i,
                    "total": len(nodes),
                    "spawn_reason": f"对话生成: {text[:80]}",
                }
                self.wfile.write(
                    f"data: {json.dumps(ev, ensure_ascii=False)}\n\n".encode("utf-8")
                )
                self.wfile.flush()

            # 完结事件：携带完整 DAG 供前端验证
            done_ev = {
                "type": "wf_done",
                "dag": dag,
                "total_nodes": len(nodes),
                "total_edges": len(edges),
            }
            self.wfile.write(
                f"data: {json.dumps(done_ev, ensure_ascii=False)}\n\n".encode("utf-8")
            )
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass  # 客户端断开，停止发送


    # ---- 备忘录日历 (Memo Calendar) ----
    def _memos_data_path(self) -> str:
        data_dir = os.path.join(os.path.dirname(__file__), "xai-backend", "data")
        os.makedirs(data_dir, exist_ok=True)
        return os.path.join(data_dir, "memos.json")

    def _memos_load(self) -> list:
        p = self._memos_data_path()
        if not os.path.exists(p):
            return []
        try:
            d = json.loads(open(p, encoding="utf-8").read())
            return d if isinstance(d, list) else []
        except Exception:
            return []

    def _memos_save(self, items: list):
        with open(self._memos_data_path(), "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)

    def _handle_memos_get(self):
        try:
            self._json_response(200, {"memos": self._memos_load()})
        except Exception as e:
            self._json_response(500, {"error": f"读取备忘录失败: {e}"})

    def _handle_memos(self):
        """POST /api/memos(创建) /update(改) /delete(删)。"""
        try:
            length = int(self.headers.get("Content-Length", "0"))
            data = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except Exception:
            self._json_response(400, {"error": "无效 JSON 请求体"})
            return
        seg = self.path.split("/")
        sub = seg[-1] if len(seg) > 2 else ""
        if sub == "delete":
            mid = data.get("id")
            items = [m for m in self._memos_load() if m.get("id") != mid]
            self._memos_save(items)
            self._json_response(200, {"ok": True, "deleted": mid})
            return
        if sub == "update":
            mid = data.get("id")
            items = self._memos_load()
            found = False
            for m in items:
                if m.get("id") == mid:
                    m.update({k: v for k, v in data.items() if k != "id"})
                    found = True
            if not found:
                self._json_response(404, {"error": "备忘录不存在"})
                return
            self._memos_save(items)
            self._json_response(200, {"ok": True, "memo": next((m for m in items if m.get("id") == mid), None)})
            return
        # 创建
        mid = "MEMO-" + os.urandom(4).hex()
        memo = {k: v for k, v in data.items()}
        memo["id"] = mid
        if "created_at" not in memo:
            memo["created_at"] = int(time.time())
        items = self._memos_load()
        items.append(memo)
        self._memos_save(items)
        self._json_response(200, {"ok": True, "memo": memo})

    def _handle_guardian_grok_write_request(self):
        """POST /api/guardian/grok-write/request → 把 Grok Build 写操作转 Guardian 审批工单。

        请求体：{task, reason?}。返回 {ok, id, status}。GuardianCenter 通过
        /api/guardian/pending 拉到 type=grok_write 的工单进行批准/拒绝。
        """
        try:
            length = int(self.headers.get("Content-Length", "0"))
            data = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except Exception:
            self._json_response(400, {"error": "无效 JSON 请求体"})
            return
        eng = get_engine()
        if not eng:
            self._json_response(503, {"error": "引擎未初始化"})
            return
        task = (data.get("task") or "").strip()
        if not task:
            self._json_response(400, {"error": "缺少 task"})
            return
        from core.kernel.guardian_bridge import create_approval
        aid = create_approval(
            eng, "grok_write", task[:300],
            data.get("reason", "Grok Build 写操作需人工审批"),
            intent="grok_build",
        )
        self._json_response(200, {"ok": True, "id": aid, "status": "pending"})


    # ---- 文件：上传 / 保存 / 本地打开 ----

    def _resolve_workspace_file(self, name: str):
        """将 stored 名解析为 workspace 内绝对路径，越界或未提供则返回 None。

        兼容子目录：上传文件位于 uploads/，保存产物位于 artifacts/，
        因此依次尝试 name / uploads/name / artifacts/name，返回首个存在的合法路径。
        """
        if not name or ".." in name or name.startswith("/") or name.startswith("\\"):
            return None
        try:
            engine = get_engine()
            ws_root = Path(engine.openclaw.workspace_path("")).resolve()
            for cand in (name, "uploads/" + name, "artifacts/" + name):
                p = Path(engine.openclaw.workspace_path(cand)).resolve()
                if ws_root != p and ws_root not in p.parents:
                    continue
                if os.path.exists(p):
                    return str(p)
        except Exception:
            return None
        return None


    # ---- 应用层资源（任务 / 专家团 / 自动化 / 定时 / 画布）----

    def _try_app_get(self, path: str) -> bool:
        seg = path[len("/api/"):].split("/")
        name = seg[0]
        if name not in _APP_RESOURCES:
            return False
        _, list_fn, get_fn, _, _, _ = _APP_RESOURCES[name]
        if len(seg) == 1:
            self._json_response(200, {name: list_fn()})
        else:
            item = get_fn(seg[1])
            if item is None:
                self._json_response(404, {"error": "not found", "id": seg[1]})
            else:
                self._json_response(200, item)
        return True

    def _try_app_post(self, path: str) -> bool:
        seg = path[len("/api/"):].split("/")
        name = seg[0]
        if name not in _APP_RESOURCES:
            return False
        try:
            length = int(self.headers.get("Content-Length", "0"))
            data = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except Exception:
            self._json_response(400, {"error": "无效 JSON 请求体"})
            return True
        _, _, _, create_fn, update_fn, delete_fn = _APP_RESOURCES[name]
        if len(seg) == 1:
            self._json_response(200, create_fn(data))
        if seg[1] == "update":
            if update_fn is None:
                self._json_response(404, {"error": "该资源不支持 update"})
            else:
                item = update_fn(data.get("id"), data)
                self._json_response(200 if item else 404, item or {"error": "not found"})
        if seg[1] == "delete":
            self._json_response(200, {"ok": bool(delete_fn(data.get("id")))})
        else:
            self._json_response(404, {"error": "unknown subroute", "path": path})
        return True


    def _sse_response(self, engine: XAIEngine, text: str, session: str, attachments=None, kernel_override: str = "", vision_parts=None):
        """SSE 流式响应。

        关键：显式声明 Connection: close 并在响应结束后关闭连接。
        否则（keep-alive + 无 Content-Length）会让严格的流式客户端
        （urllib / 部分 HTTP 客户端）在读取完所有事件后继续等待 EOF 而挂起。
        浏览器（fetch + ReadableStream）与 curl 不受影响，但统一关闭更健壮。
        """
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.close_connection = True

        try:
            for ev in engine.chat(text, session, attachments=attachments, kernel_override=kernel_override, vision_parts=vision_parts):
                line = f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
                try:
                    self.wfile.write(line.encode("utf-8"))
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    break  # 客户端已断开，停止生成
            else:
                # 正常结束
                try:
                    self.wfile.write(b"data: [DONE]\n\n")
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
        except Exception as e:
            try:
                err = f"data: {json.dumps({'type': 'error', 'error': str(e)}, ensure_ascii=False)}\n\n"
                self.wfile.write(err.encode("utf-8"))
                self.wfile.flush()
            except Exception:
                pass

    # ---- Skills API (CRUD) ----

    def _skills_dir(self) -> Path:
        return Path(os.environ.get("XAI_HOME", os.path.expanduser("~/.xai"))) / "skills"


    def _handle_hub_send(self, room_id: str):
        """POST /api/hub/rooms/<id>/send → 发送群聊消息"""
        try:
            length = int(self.headers.get("Content-Length", "0"))
            data = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except Exception:
            self._json_response(400, {"error": "需要 JSON body"})
            return
        agent_name = (data.get("agent_name") or data.get("agent") or "system").strip()
        text = (data.get("text") or "").strip()
        if not text:
            self._json_response(400, {"error": "text 不能为空"})
            return
        if room_id not in _hub_rooms:
            self._json_response(404, {"error": f"房间 '{room_id}' 不存在"})
            return
        import uuid
        msg = {
            "id": f"msg:{uuid.uuid4().hex[:12]}",
            "room_id": room_id,
            "agent_name": agent_name,
            "text": text,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "mention": data.get("mention", ""),
        }
        _hub_rooms[room_id]["messages"].append(msg)
        self._json_response(200, {"ok": True, "msg": msg})


    # ---- MCP 管理平台 API (CRUD + Learn + Import) ----

    def _mcp_data_path(self) -> str:
        """MCP 配置数据文件路径。"""
        data_dir = os.path.join(os.path.dirname(__file__), "xai-backend", "data")
        os.makedirs(data_dir, exist_ok=True)
        return os.path.join(data_dir, "mcp_configs.json")

    def _mcp_load(self) -> list:
        path = self._mcp_data_path()
        if not os.path.exists(path):
            return []
        try:
            data = json.loads(open(path, encoding="utf-8").read())
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _mcp_save(self, configs: list):
        path = self._mcp_data_path()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(configs, f, ensure_ascii=False, indent=2)

    def _mcp_next_id(self, configs: list) -> int:
        return max([c.get("id", 0) for c in configs], default=0) + 1


    def _handle_mcp_update(self, mcp_id: int):
        """PUT /api/mcp/update/<id> — 更新指定 MCP 配置"""
        try:
            length = int(self.headers.get("Content-Length", "0"))
            data = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except Exception:
            self._json_response(400, {"error": "需要 JSON body"})
            return
        configs = self._mcp_load()
        for i, mcp in enumerate(configs):
            if mcp.get("id") == mcp_id:
                if "name" in data:
                    configs[i]["name"] = data["name"]
                if "type" in data:
                    configs[i]["type"] = data["type"]
                if "command" in data:
                    configs[i]["command"] = data["command"]
                if "url" in data:
                    configs[i]["url"] = data["url"]
                if "args" in data and isinstance(data["args"], list):
                    configs[i]["args"] = data["args"]
                if "env" in data and isinstance(data["env"], dict):
                    configs[i]["env"] = data["env"]
                if "enabled" in data:
                    configs[i]["enabled"] = data["enabled"]
                self._mcp_save(configs)
                self._json_response(200, {"ok": True, "mcp": configs[i]})
                return
        self._json_response(404, {"ok": False, "error": f"MCP {mcp_id} 不存在"})

    def _handle_mcp_delete(self, mcp_id: int):
        """DELETE /api/mcp/delete/<id> — 删除指定 MCP 配置"""
        configs = self._mcp_load()
        before = len(configs)
        configs = [c for c in configs if c.get("id") != mcp_id]
        if len(configs) == before:
            self._json_response(404, {"ok": False, "error": f"MCP {mcp_id} 不存在"})
            return
        self._mcp_save(configs)
        self._json_response(200, {"ok": True, "deleted_id": mcp_id})


    # ---- MCP Connectors API (CRUD) ----

    def _connectors_path(self) -> Path:
        return Path(os.environ.get("XAI_HOME", os.path.expanduser("~/.xai"))) / "connectors.json"

    def _connectors_load(self) -> list:
        path = self._connectors_path()
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _connectors_save(self, connectors: list):
        path = self._connectors_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(connectors, ensure_ascii=False, indent=2), encoding="utf-8")


    # ---- Skill 管理平台 API (CRUD + Learn + Import) ----

    def _skill_config_path(self) -> str:
        """Skill 配置数据文件路径。"""
        data_dir = os.path.join(os.path.dirname(__file__), "xai-backend", "data")
        os.makedirs(data_dir, exist_ok=True)
        return os.path.join(data_dir, "skill_configs.json")

    def _skill_load(self) -> list:
        path = self._skill_config_path()
        if not os.path.exists(path):
            return []
        try:
            data = json.loads(open(path, encoding="utf-8").read())
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _skill_save(self, configs: list):
        path = self._skill_config_path()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(configs, f, ensure_ascii=False, indent=2)

    def _skill_next_id(self, configs: list) -> int:
        return max([c.get("id", 0) for c in configs], default=0) + 1


    def _handle_skill_update(self, skill_id: int):
        """PUT /api/skill/update/<id> — 更新指定 Skill"""
        try:
            length = int(self.headers.get("Content-Length", "0"))
            data = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except Exception:
            self._json_response(400, {"error": "需要 JSON body"})
            return
        configs = self._skill_load()
        for i, sk in enumerate(configs):
            if sk.get("id") == skill_id:
                if "name" in data:
                    configs[i]["name"] = data["name"]
                if "description" in data:
                    configs[i]["description"] = data["description"]
                if "source_type" in data:
                    configs[i]["source_type"] = data["source_type"]
                if "source_url" in data:
                    configs[i]["source_url"] = data["source_url"]
                if "content" in data:
                    configs[i]["content"] = data["content"]
                if "enabled" in data:
                    configs[i]["enabled"] = data["enabled"]
                self._skill_save(configs)
                self._json_response(200, {"ok": True, "skill": configs[i]})
                return
        self._json_response(404, {"ok": False, "error": f"Skill {skill_id} 不存在"})

    def _handle_skill_delete(self, skill_id: int):
        """DELETE /api/skill/delete/<id> — 删除指定 Skill"""
        configs = self._skill_load()
        before = len(configs)
        configs = [c for c in configs if c.get("id") != skill_id]
        if len(configs) == before:
            self._json_response(404, {"ok": False, "error": f"Skill {skill_id} 不存在"})
            return
        self._skill_save(configs)
        self._json_response(200, {"ok": True, "deleted_id": skill_id})


    # ---- Chat Sessions API ----


    # ---- Dashboard API ----

    def _memory_stats_payload(self):
        """GET /api/memory/stats → 记忆统计（对齐前端 MemoryStatsData）"""
        eng = get_engine()
        core = eng.memory_core.stats()  # {layer: count}
        import random
        random.seed(42)  # 稳定伪随机用于可视化
        layers = {}
        for k, v in core.items():
            layers[k] = {
                "count": v,
                "hit_rate": round(random.uniform(0.6, 0.95), 2),
                "health": round(random.uniform(0.7, 1.0), 2),
                "capacity": max(v * 2, 100),
            }
        total = sum(core.values())
        # 生成趋势数据（最近 7 天，每天一个计数模拟）
        trends = {
            layer: [max(0, core.get(layer, 0) + random.randint(-5, 10)) for _ in range(7)]
            for layer in core
        }
        # 生成热力图数据（7 天 x 4 层）
        heatmap = {
            layer: [max(0, round(random.uniform(0.3, 1.0), 2)) for _ in range(7)]
            for layer in core
        }
        # 漏斗数据
        funnel = {
            "ingest": total + random.randint(5, 20),
            "process": total + random.randint(0, 10),
            "store": total,
            "recall": max(0, total - random.randint(0, 5)),
        }
        # 散点数据（每个 layer 生成 8-15 个数据点）
        scatter = {}
        for layer, v in core.items():
            num_points = min(15, max(8, v // 2))
            scatter[layer] = [
                {"age": random.randint(1, 90), "hit_rate": round(random.uniform(0.3, 0.95), 2)}
                for _ in range(num_points)
            ]
        return {
            "layers": layers,
            "summary": {
                "total_memories": total,
                "total_capacity": sum(d["capacity"] for d in layers.values()),
                "avg_hit_rate": round(
                    sum(d["hit_rate"] for d in layers.values()) / max(len(layers), 1), 2
                ),
                "last_updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
            },
            "trends": trends,
            "heatmap": heatmap,
            "funnel": funnel,
            "scatter": scatter,
        }

    # ---- 前后端打通：能力注册表 / 编排 / 记忆可视化 ----

    def _orchestrations_load(self):
        p = Path(__file__).resolve().parent / "xai-backend" / "data" / "orchestrations.json"
        if not p.exists():
            return []
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return []

    def _orchestrations_save(self, items):
        p = Path(__file__).resolve().parent / "xai-backend" / "data" / "orchestrations.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")

    def _handle_capabilities(self):
        """GET /api/capabilities → 聚合 agent/skill/tool 供能力注册表"""
        try:
            eng = get_engine()
            caps = []
            try:
                for a in eng.coordination.list_agents():
                    caps.append({
                        "id": a.id, "name": a.name, "type": "agent",
                        "status": "active", "description": a.role or "",
                        "meta": a.backend or "",
                    })
            except Exception:
                pass
            try:
                for f in sorted(self._skills_dir().glob("*_skill.json")):
                    try:
                        d = json.loads(f.read_text(encoding="utf-8"))
                        caps.append({
                            "id": "sk:" + f.stem.replace("_skill", ""),
                            "name": d.get("name", f.stem.replace("_skill", "")),
                            "type": "skill", "status": "active",
                            "description": d.get("trigger", ""),
                            "meta": d.get("source", "file"),
                        })
                    except Exception:
                        continue
            except Exception:
                pass
            try:
                for s in self._skill_load():
                    caps.append({
                        "id": "cfg:" + str(s.get("id", s.get("name", ""))),
                        "name": s.get("name", ""), "type": "skill",
                        "status": "active" if s.get("enabled", True) else "disabled",
                        "description": s.get("description", ""),
                        "meta": s.get("source_type", "config"),
                    })
            except Exception:
                pass
            try:
                for m in self._mcp_load():
                    caps.append({
                        "id": "mcp:" + str(m.get("id", m.get("name", ""))),
                        "name": m.get("name", ""), "type": "tool",
                        "status": "active" if m.get("enabled", True) else "disabled",
                        "description": m.get("type", "mcp"),
                        "meta": m.get("command") or m.get("url", ""),
                    })
            except Exception:
                pass
            try:
                for c in self._connectors_load():
                    caps.append({
                        "id": "conn:" + c.get("name", ""),
                        "name": c.get("name", ""), "type": "tool",
                        "status": "active",
                        "description": c.get("type", "connector"),
                        "meta": c.get("command") or c.get("url", ""),
                    })
            except Exception:
                pass
            self._json_response(200, {"capabilities": caps})
        except Exception as e:
            self._json_response(500, {"error": f"聚合能力失败: {e}"})

    def _handle_orchestrations_list(self):
        """GET /api/orchestrations → 编排列表"""
        try:
            self._json_response(200, {"orchestrations": self._orchestrations_load()})
        except Exception as e:
            self._json_response(500, {"error": f"读取编排失败: {e}"})

    def _handle_orchestrations(self):
        """POST /api/orchestrations[/<id>/<action>] → 创建/暂停/继续/终止/删除"""
        try:
            path = self.path.split("?")[0]
            if path.startswith("/api/") and "%" in path:
                path = urllib.parse.unquote(path)  # 编排 id 可能含中文，见 do_GET 处注释
            parts = [p for p in path.split("/") if p]
            # parts: ['api','orchestrations','<id>?','action?']
            if len(parts) >= 4 and parts[3] in ("pause", "resume", "terminate", "delete"):
                oid = parts[2]
                action = parts[3]
                items = self._orchestrations_load()
                if action == "delete":
                    items = [o for o in items if o.get("id") != oid]
                    self._orchestrations_save(items)
                    self._json_response(200, {"ok": True, "deleted": oid})
                    return
                for o in items:
                    if o.get("id") == oid:
                        o["status"] = {"pause": "paused", "resume": "running", "terminate": "error"}[action]
                self._orchestrations_save(items)
                self._json_response(200, {"ok": True, "orchestration": next((o for o in items if o.get("id") == oid), None)})
                return
            length = int(self.headers.get("Content-Length", "0"))
            data = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            name = (data.get("name") or "").strip()
            if not name:
                self._json_response(400, {"error": "name 不能为空"})
                return
            items = self._orchestrations_load()
            oid = "o" + str(int(time.time() * 1000))
            orch = {
                "id": oid, "name": name, "status": "running",
                "agentCount": int(data.get("agentCount", 1)),
                "totalSteps": int(data.get("totalSteps", 1)),
                "currentStep": 0,
                "startedAt": time.strftime("%Y-%m-%d %H:%M"),
            }
            items.append(orch)
            self._orchestrations_save(items)
            self._json_response(200, {"ok": True, "orchestration": orch})
        except Exception as e:
            self._json_response(500, {"error": f"编排操作失败: {e}"})

    def _handle_memory_visualize(self):
        """GET /api/memory/visualize → 雷达 + 知识关联图谱（真实派生）"""
        try:
            eng = get_engine()
            skills, mcps, connectors, agents = [], [], [], []
            try:
                skills = self._skill_load()
            except Exception:
                pass
            try:
                mcps = self._mcp_load()
            except Exception:
                pass
            try:
                connectors = self._connectors_load()
            except Exception:
                pass
            try:
                agents = eng.coordination.list_agents()
            except Exception:
                pass
            core = {}
            try:
                core = eng.memory_core.stats()
            except Exception:
                pass
            radar = [
                {"axis": "编码", "value": min(100, 40 + len(skills) * 6)},
                {"axis": "设计", "value": min(100, 40 + len(mcps) * 8)},
                {"axis": "架构", "value": min(100, 40 + max(len(agents), 1) * 10)},
                {"axis": "调试", "value": min(100, 40 + len(connectors) * 8)},
                {"axis": "文档", "value": min(100, 30 + core.get("doc", 0) * 2)},
                {"axis": "协作", "value": min(100, 40 + max(len(agents), 1) * 5)},
            ]
            nodes = [{"id": "xai", "label": "XAI", "group": "项目", "strength": 95}]
            for a in agents:
                nodes.append({"id": str(a.id), "label": a.name, "group": "后端", "strength": 80})
            for s in skills:
                nodes.append({"id": "skill:" + str(s.get("id", s.get("name", ""))), "label": s.get("name", ""), "group": "架构", "strength": 70})
            for m in mcps:
                nodes.append({"id": "mcp:" + str(m.get("id", m.get("name", ""))), "label": m.get("name", ""), "group": "项目", "strength": 75})
            links = [{"source": n["id"], "target": "xai", "weight": 0.7} for n in nodes if n["id"] != "xai"]
            self._json_response(200, {"radar": radar, "graph": {"nodes": nodes, "links": links}})
        except Exception as e:
            self._json_response(500, {"error": f"记忆可视化失败: {e}"})


    def _parse_multipart(self, content_type: str, body: bytes):
        """极简 multipart/form-data 解析，仅提取 file 字段的 name + bytes。"""
        if not content_type or "boundary=" not in content_type:
            return None, None
        boundary = content_type.split("boundary=")[-1].strip()
        if boundary.startswith('"') and boundary.endswith('"'):
            boundary = boundary[1:-1]
        boundary_bytes = boundary.encode("utf-8")
        parts = body.split(b"--" + boundary_bytes)
        for part in parts:
            if b"Content-Disposition" not in part:
                continue
            headers_end = part.find(b"\r\n\r\n")
            if headers_end == -1:
                continue
            headers_raw = part[:headers_end].decode("utf-8", errors="replace")
            if 'name="file"' not in headers_raw:
                continue
            # 提取 filename
            fname = "backup.tar.gz"
            for item in headers_raw.split(";"):
                item = item.strip()
                if item.startswith("filename="):
                    fname = item.split("=", 1)[1].strip().strip('"')
            content = part[headers_end + 4:]
            # strip trailing \r\n + boundary suffix
            if content.endswith(b"\r\n"):
                content = content[:-2]
            if content.endswith(b"\n"):
                content = content[:-1]
            if content.endswith(b"--"):
                content = content[:-2].rstrip(b"\r\n")
            return fname, content
        return None, None


    # ---- GEPA 自进化 API (B1) ----


# ---- 路由注册表（S5-1 绞杀者模式：新路由经注册表优先分发，未命中走 do_* legacy 分支）----
from server_router import Router
from server_routes_backup import register as _reg_backup
from server_routes_canvas import register as _reg_canvas
from server_routes_chat import register as _reg_chat
from server_routes_connectors import register as _reg_connectors
# (dead route removed: server_routes_dashboard.py deleted, no caller)  # noqa
from server_routes_distill import register as _reg_distill
from server_routes_files import register as _reg_files
from server_routes_gepa import register as _reg_gepa
from server_routes_gateway import register as _reg_gateway
from server_routes_grok import register as _reg_grok
from server_routes_hub import register as _reg_hub
from server_routes_intent import register as _reg_intent
from server_routes_io import register as _reg_io
from server_routes_mcp import register as _reg_mcp
from server_routes_memory import register as _reg_memory
from server_routes_misc import register as _reg_misc
from server_routes_models import register as _reg_models
from server_routes_plans import register as _reg_plans
from server_routes_projects import register as _reg_projects
from server_routes_sessions import register as _reg_sessions
from server_routes_settings import register as _reg_settings
# (dead route removed: server_routes_skill.py deleted, no caller)  # noqa
from server_routes_skills import register as _reg_skills
from server_routes_system import register as _reg_system
from server_routes_usage import register as _reg_usage
from server_routes_metrics import register as _reg_metrics
from server_routes_acceptance import register as _reg_acceptance
from server_routes_workflow import register as _reg_workflow
from server_routes_agent_room import register as _reg_agent_room

_ROUTER = Router()
_reg_backup(_ROUTER)
_reg_canvas(_ROUTER)
_reg_chat(_ROUTER)
_reg_connectors(_ROUTER)
# _reg_dashboard removed (dead /api/dashboard route)
_reg_distill(_ROUTER)
_reg_files(_ROUTER)
_reg_gepa(_ROUTER)
_reg_gateway(_ROUTER)
_reg_grok(_ROUTER)
_reg_hub(_ROUTER)
_reg_intent(_ROUTER)
_reg_io(_ROUTER)
_reg_mcp(_ROUTER)
_reg_memory(_ROUTER)
_reg_misc(_ROUTER)
_reg_models(_ROUTER)
_reg_plans(_ROUTER)
_reg_projects(_ROUTER)
_reg_sessions(_ROUTER)
_reg_settings(_ROUTER)
# _reg_skill removed (dead singular /api/skill/* route)
_reg_skills(_ROUTER)
_reg_system(_ROUTER)
_reg_usage(_ROUTER)
_reg_metrics(_ROUTER)
_reg_workflow(_ROUTER)
_reg_agent_room(_ROUTER)
_reg_acceptance(_ROUTER)


# ---- 启动 ----

import atexit
import fcntl
import signal
import socket

_PID_FILE = None


def _cleanup_pid():
    global _PID_FILE
    if _PID_FILE and os.path.exists(_PID_FILE):
        try:
            os.unlink(_PID_FILE)
        except OSError:
            pass


def _acquire_pid_lock(pid_dir: str) -> bool:
    """PID 文件锁，防止多实例互抢"""
    global _PID_FILE
    os.makedirs(pid_dir, exist_ok=True)
    _PID_FILE = os.path.join(pid_dir, "server.pid")
    try:
        # 尝试获取排他锁
        lock_fd = os.open(_PID_FILE, os.O_CREAT | os.O_RDWR)
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.write(lock_fd, f"{os.getpid()}\n".encode())
        atexit.register(_cleanup_pid)
        return True
    except (IOError, OSError):
        logging.getLogger("xai").error(f"已有实例在运行（{_PID_FILE}）。如需重启请先停止旧进程。")
        return False


def setup_logging(xai_home: str) -> logging.Logger:
    """配置 XAI 轮转日志：文件(~/.xai/logs/xai-server.log, 5MB×5 轮转) + stdout。"""
    log_dir = os.path.join(xai_home, "logs")
    os.makedirs(log_dir, exist_ok=True)
    logger = logging.getLogger("xai")
    if logger.handlers:  # 防重复添加（重载/测试时）
        return logger
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S"
    )
    rf = logging.handlers.RotatingFileHandler(
        os.path.join(log_dir, "xai-server.log"),
        maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8",
    )
    rf.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(rf)
    logger.addHandler(sh)
    return logger


def run_startup_selfcheck(xai_home: str, engine) -> bool:
    """启动自检：DB 可打开+完整性、关键路由模块可导入。返回 DB 是否健康。"""
    xai_log = logging.getLogger("xai")
    xai_log.info("=== 启动自检开始 ===")
    db_ok = True
    for name in ("app.db", "memory.db", "sessions.db", "knowledge.db", "projects.db"):
        p = os.path.join(xai_home, name)
        if not os.path.exists(p):
            xai_log.warning(f"自检: 数据库缺失 {name}（首次运行将自动创建）")
            continue
        try:
            c = sqlite3.connect(p)
            rows = c.execute("PRAGMA integrity_check").fetchall()
            c.close()
            if all(r[0] == "ok" for r in rows):
                xai_log.info(f"自检: DB OK {name}")
            else:
                db_ok = False
                xai_log.error(f"自检: DB 完整性失败 {name}")
        except Exception as e:
            db_ok = False
            xai_log.error(f"自检: DB 打开失败 {name}: {e}")
    for m in ("server_router", "server_routes_system", "server_routes_chat",
              "server_routes_models", "server_routes_backup", "server_routes_metrics"):
        try:
            __import__(m)
            xai_log.info(f"自检: 路由模块 OK {m}")
        except Exception as e:
            xai_log.error(f"自检: 路由模块导入失败 {m}: {e}")
    xai_log.info(f"=== 启动自检结束 (db_healthy={db_ok}) ===")
    return db_ok


def main():
    port = int(os.environ.get("XAI_PORT", "8000"))
    host = os.environ.get("XAI_HOST", "localhost")
    xai_home = os.environ.get("XAI_HOME", os.path.expanduser("~/.xai"))
    xai_log = setup_logging(xai_home)
    xai_log.info(f"XAI 启动中 host={host} port={port} home={xai_home}")

    # PID 文件互斥锁
    if not _acquire_pid_lock(xai_home):
        xai_log.error("已有实例在运行，退出")
        sys.exit(1)

    # 预热引擎
    engine = get_engine()

    # 启动自检（DB + 路由模块；模型就绪由下方 warmup 线程负责）
    run_startup_selfcheck(xai_home, engine)

    # 应用层持久化（任务/专家团/自动化/定时/画布）
    try:
        app_store.init_db()
        xai_log.info("app_store 已初始化")
    except Exception as e:
        xai_log.error(f"app_store 初始化失败: {e}")
    _start_scheduler()
    _event_heartbeat()

    # status() 预热采用非阻塞守护线程（不 join），
    # 让端口绑定和服务可用性不依赖引擎初始化速度（参考 5.3.3 prewarm 延迟优化）。
    import threading as _th

    def _warmup_status():
        try:
            st = engine.status()
            xai_log.info(f"状态预热: model={st.get('model')}, openclaw={st.get('openclaw',{}).get('meta',{})}")
        except Exception as e:
            xai_log.warning(f"状态检查跳过: {e}")

    _th.Thread(target=_warmup_status, daemon=True).start()

    # ── on-change 自动备份守护（参考 5.3.3 安全中心文件修改自动备份）──
    _watchdog_running = True

    def _backup_watchdog():
        """每 30s 检查关键配置文件，有修改立即触发备份。"""
        # 监控的关键文件清单
        watch_targets = {}
        for name in ("models.json", ".server_token"):
            p = os.path.join(xai_home, name)
            if os.path.exists(p):
                watch_targets[p] = os.path.getmtime(p)
        backup_script = os.path.join(os.path.dirname(__file__), "xai-backup.py")
        while _watchdog_running:
            time.sleep(30)
            try:
                any_changed = False
                for fp, last_mtime in list(watch_targets.items()):
                    if os.path.exists(fp):
                        mt = os.path.getmtime(fp)
                        if mt != last_mtime:
                            watch_targets[fp] = mt
                            any_changed = True
                            xai_log.info(f"watchdog: 检测到修改 {os.path.basename(fp)}，触发备份")
                    else:
                        # 文件被删除了，重新扫描
                        del watch_targets[fp]
                if any_changed and os.path.exists(backup_script):
                    xai_py = os.environ.get("XAI_PYTHON", sys.executable)
                    subprocess.run([xai_py, backup_script, "--watchdog"],
                                  capture_output=True, timeout=30)
            except Exception as e:
                xai_log.warning(f"watchdog 周期检查异常: {e}")

    _th.Thread(target=_backup_watchdog, daemon=True).start()
    xai_log.info("on-change 备份守护已启动（周期 30s）")

    # 带端口重用和优雅降级的服务器启动
    # 注意：不静默漂移端口（port+1）——单实例本地应用应在预期端口启动；
    # 端口被占用通常是上一次实例尚未退出，重试同一端口即可。
    max_retries = 10
    server = None
    for attempt in range(max_retries):
        try:
            server = ThreadingXAIHTTPServer((host, port), XAIHandler)
            server.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.timeout = 30  # 防止僵尸连接
            break
        except OSError as e:
            if attempt < max_retries - 1:
                xai_log.warning(f"端口 {port} 暂被占用，重试 ({attempt+1}/{max_retries})...")
                time.sleep(1)
            else:
                xai_log.error(f"无法绑定端口 {port}: {e}")
                _cleanup_pid()
                sys.exit(1)

    xai_log.info(f"服务已启动 → http://{host}:{port}")
    xai_log.info("按 Ctrl+C 停止")

    def graceful_shutdown(signum=None, frame=None):
        xai_log.info("正在关闭...")
        try:
            engine.memory.cleanup_expired()
            engine.memory.shutdown()
        except Exception:
            pass
        try:
            server.server_close()
        except Exception:
            pass
        _cleanup_pid()
        xai_log.info("已停止")
        sys.exit(0)

    signal.signal(signal.SIGINT, graceful_shutdown)
    signal.signal(signal.SIGTERM, graceful_shutdown)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        graceful_shutdown()


if __name__ == "__main__":
    main()
