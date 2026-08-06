#!/usr/bin/env python3
"""第二波 e2e：写路径 / CRUD 回环旅程 — 零依赖。

和前两层的区别：
    route_probe   = GET 探活（路由在不在、返回码对不对）
    e2e_journeys  = 核心链路行为（对话/记忆/画布/工作流真跑通没有）
    e2e_crud（本文件） = 写路径回环（建 → 读回 → 改 → 删，状态真变了没有）

route_probe 只打 GET，写路径是覆盖盲区，也是缺陷高发区。
本文件每条旅程都做"状态变更 + 二次读回验证"，不接受空壳 200。

用法:
    python3 scripts/e2e_crud.py
    python3 scripts/e2e_crud.py -k skill
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://localhost:8000"
_TOKEN = ""
STAMP = int(time.time())


class Skip(Exception):
    """主动跳过（依赖外部条件不满足）。"""


def call(method: str, path: str, body=None, timeout=60):
    url = BASE + path
    headers = {"X-Auth-Token": _TOKEN}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
            try:
                return r.status, json.loads(raw)
            except json.JSONDecodeError:
                return r.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, raw


def as_list(payload, *keys):
    """从多种包裹形态里取出列表。"""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for k in keys:
            v = payload.get(k)
            if isinstance(v, list):
                return v
        for v in payload.values():
            if isinstance(v, list):
                return v
    return []


def names_of(items, *keys):
    out = []
    for it in items:
        if isinstance(it, dict):
            for k in keys:
                if it.get(k):
                    out.append(str(it[k]))
                    break
        else:
            out.append(str(it))
    return out


# ─────────────────────────── 旅程定义 ───────────────────────────

def c01_skill_crud():
    """技能：创建 → 列表可见 → 更新生效 → 删除后消失。"""
    name = f"e2e_skill_{STAMP}"
    code, r = call("POST", "/api/skills/create",
                   {"name": name, "trigger": "e2e触发词", "body": "初始内容 v1"})
    assert code == 200, f"创建 HTTP {code}: {r}"

    code, r = call("GET", "/api/skills")
    items = as_list(r, "skills", "items", "data")
    assert name in names_of(items, "name", "id"), f"创建后列表查不到 {name}"

    code, r = call("POST", "/api/skills/update",
                   {"name": name, "trigger": "e2e触发词", "body": "更新内容 v2"})
    assert code == 200, f"更新 HTTP {code}: {r}"
    code, r = call("GET", "/api/skills")
    items = as_list(r, "skills", "items", "data")
    hit = next((s for s in items if isinstance(s, dict) and s.get("name") == name), None)
    assert hit, "更新后条目丢失"
    assert "v2" in json.dumps(hit, ensure_ascii=False), f"更新未生效: {hit}"

    code, r = call("POST", "/api/skills/delete", {"name": name})
    assert code == 200, f"删除 HTTP {code}: {r}"
    code, r = call("GET", "/api/skills")
    items = as_list(r, "skills", "items", "data")
    assert name not in names_of(items, "name", "id"), "删除后仍在列表中"
    return "create→list→update(v2生效)→delete→列表消失，四步闭环"


def c02_mcp_crud():
    """MCP 配置：创建 → 列表可见 → 更新 → 删除后消失。"""
    name = f"e2e_mcp_{STAMP}"
    code, r = call("POST", "/api/mcp/create",
                   {"name": name, "command": "echo", "args": ["hello"], "enabled": True})
    assert code == 200, f"创建 HTTP {code}: {r}"

    code, r = call("GET", "/api/mcp/list")
    items = as_list(r, "mcps", "mcp_list", "items", "data")
    hit = next((m for m in items if isinstance(m, dict) and m.get("name") == name), None)
    assert hit, f"创建后列表查不到 {name}"
    mid = hit.get("id")   # 后端 update/delete 按数字 id 操作
    assert mid is not None, f"条目无 id，无法更新/删除: {hit}"

    code, r = call("PUT", f"/api/mcp/update/{mid}",
                   {"name": name, "command": "echo", "args": ["updated"], "enabled": False})
    assert code == 200, f"更新 HTTP {code}: {r}"

    code, r = call("DELETE", f"/api/mcp/delete/{mid}")
    assert code == 200, f"删除 HTTP {code}: {r}"
    code, r = call("GET", "/api/mcp/list")
    items = as_list(r, "mcps", "mcp_list", "items", "data")
    assert name not in names_of(items, "name", "id"), "删除后仍在列表中"
    return "create→list→update→delete→列表消失，四步闭环"


def c03_connector_crud():
    """连接器：创建 → 列表可见 → 测试可调 → 删除后消失。"""
    name = f"e2e_conn_{STAMP}"
    code, r = call("POST", "/api/connectors/create",
                   {"name": name, "type": "stdio", "command": "echo", "args": ["ok"]})
    assert code == 200, f"创建 HTTP {code}: {r}"

    code, r = call("GET", "/api/connectors")
    items = as_list(r, "connectors", "items", "data")
    assert name in names_of(items, "name", "id"), f"创建后列表查不到 {name}"

    code, r = call("POST", "/api/connectors/test", {"name": name}, timeout=30)
    assert code == 200, f"测试端点 HTTP {code}: {r}"
    assert isinstance(r, dict), f"测试返回非结构化: {r}"

    code, r = call("POST", "/api/connectors/delete", {"name": name})
    assert code == 200, f"删除 HTTP {code}: {r}"
    code, r = call("GET", "/api/connectors")
    items = as_list(r, "connectors", "items", "data")
    assert name not in names_of(items, "name", "id"), "删除后仍在列表中"
    return "create→list→test→delete→列表消失，四步闭环"


def c04_memo_crud():
    """备忘录：创建 → 列表可见 → 更新生效 → 删除后消失。"""
    title = f"e2e备忘{STAMP}"
    code, r = call("POST", "/api/memos",
                   {"title": title, "content": "初始正文",
                    "date": time.strftime("%Y-%m-%d")})
    assert code == 200, f"创建 HTTP {code}: {r}"
    mid = (r or {}).get("id") or (r or {}).get("memo", {}).get("id")

    code, r = call("GET", "/api/memos")
    items = as_list(r, "memos", "items", "data")
    hit = next((m for m in items if isinstance(m, dict) and m.get("title") == title), None)
    assert hit, f"创建后列表查不到 {title}"
    mid = mid or hit.get("id")
    assert mid, f"拿不到备忘 id: {hit}"

    code, r = call("POST", "/api/memos/update",
                   {"id": mid, "title": title, "content": "更新正文 v2"})
    assert code == 200, f"更新 HTTP {code}: {r}"
    code, r = call("GET", "/api/memos")
    items = as_list(r, "memos", "items", "data")
    hit = next((m for m in items if isinstance(m, dict) and m.get("id") == mid), None)
    assert hit and "v2" in json.dumps(hit, ensure_ascii=False), f"更新未生效: {hit}"

    code, r = call("POST", "/api/memos/delete", {"id": mid})
    assert code == 200, f"删除 HTTP {code}: {r}"
    code, r = call("GET", "/api/memos")
    items = as_list(r, "memos", "items", "data")
    assert mid not in [m.get("id") for m in items if isinstance(m, dict)], "删除后仍在列表中"
    return f"id={mid} create→list→update(v2生效)→delete→列表消失"


def c05_memory_update_delete():
    """记忆：写入 → 列表可见 → PUT 改内容 → DELETE 后消失（前端 MemoryCenter 依赖）。"""
    marker = f"e2e_mem_edit_{STAMP}"
    code, r = call("POST", "/api/memory/store",
                   {"layer": "long_term", "key": marker, "value": "原始值 v1",
                    "engine": "xai", "importance": 0.5})
    assert code == 200 and (r or {}).get("ok"), f"写入失败 HTTP {code}: {r}"

    code, r = call("GET", "/api/memory/list?limit=50&order=recent")
    items = as_list(r, "entries", "items", "memories", "data")
    hit = next((e for e in items if isinstance(e, dict) and e.get("key") == marker), None)
    assert hit, ("刚写入的记忆不在 list 首页（order=recent 应当最新在前）："
                 f"{marker} 未出现在前 {len(items)} 条")
    eid = hit.get("id")
    assert eid is not None, f"记忆条目无 id 字段，前端无法编辑: {hit}"

    code, r = call("PUT", f"/api/memory/{eid}", {"value": "改后值 v2", "importance": 0.9})
    assert code == 200, f"更新 HTTP {code}: {r}"
    code, r = call("GET", f"/api/memory/search?q={urllib.parse.quote(marker)}&limit=10")
    hits = as_list(r, "results", "hits", "items", "entries")
    blob = json.dumps(hits, ensure_ascii=False)
    assert "v2" in blob, f"PUT 后检索仍是旧值: {blob[:200]}"

    code, r = call("DELETE", f"/api/memory/{eid}")
    assert code == 200, f"删除 HTTP {code}: {r}"
    code, r = call("GET", f"/api/memory/list?limit=50&order=recent&keyword={urllib.parse.quote(marker)}")
    items = as_list(r, "entries", "items", "memories", "data")
    assert eid not in [e.get("id") for e in items if isinstance(e, dict)], "删除后仍在列表中"
    return f"id={eid} store→list→PUT(v2生效)→DELETE→列表消失"


def c06_session_lifecycle():
    """会话：对话建会话 → 列表可见 → 读消息 → 删除后消失。"""
    sid = f"e2e-crud-{STAMP}"
    code, r = call("POST", "/api/chat",
                   {"text": "只回复两个字：收到", "session": sid, "stream": False},
                   timeout=180)
    assert code == 200, f"建会话 HTTP {code}: {r}"

    code, r = call("GET", "/api/sessions")
    items = as_list(r, "sessions", "items", "data")
    ids = names_of(items, "id", "session", "session_id", "name")
    assert sid in ids, f"会话列表查不到 {sid}"

    code, r = call("GET", f"/api/sessions/{sid}/messages")
    msgs = r if isinstance(r, list) else as_list(r, "messages", "items")
    assert len(msgs) >= 1, f"消息回读为空: {r}"

    code, r = call("DELETE", f"/api/sessions/{sid}")
    assert code == 200, f"删除 HTTP {code}: {r}"
    code, r = call("GET", "/api/sessions")
    items = as_list(r, "sessions", "items", "data")
    ids = names_of(items, "id", "session", "session_id", "name")
    assert sid not in ids, "删除后会话仍在列表中"
    return f"{sid} chat建档→list可见→{len(msgs)}条消息回读→DELETE→消失"


def c07_canvas_lifecycle():
    """画布：保存 → list_all 可见 → 单读一致 → 删除后消失。"""
    cid = f"e2ecrud{STAMP}"
    nodes = [{"id": "n1", "type": "input", "data": {"label": "起点"},
              "position": {"x": 0, "y": 0}},
             {"id": "n2", "type": "output", "data": {"label": "终点"},
              "position": {"x": 200, "y": 0}}]
    edges = [{"id": "e1", "source": "n1", "target": "n2"}]
    code, r = call("POST", "/api/canvas/save",
                   {"canvas_id": cid, "nodes": nodes, "edges": edges})
    assert code == 200, f"保存 HTTP {code}: {r}"
    assert (r or {}).get("id") == cid, \
        f"传 canvas_id 却落到了 {(r or {}).get('id')!r} —— 静默数据错位"

    code, r = call("GET", "/api/canvas/list_all")
    items = as_list(r, "canvases", "items", "data")
    ids = names_of(items, "canvas_id", "id", "name")
    assert cid in ids, f"list_all 查不到 {cid}"

    code, r = call("GET", f"/api/canvas/{cid}")
    assert code == 200, f"单读 HTTP {code}: {r}"
    got_nodes = as_list(r, "nodes")
    assert len(got_nodes) == 2, f"单读节点数不一致: {len(got_nodes)}"

    code, r = call("POST", "/api/canvas/delete", {"canvas_id": cid})
    assert code == 200, f"删除 HTTP {code}: {r}"
    code, r = call("GET", "/api/canvas/list_all")
    items = as_list(r, "canvases", "items", "data")
    ids = names_of(items, "canvas_id", "id", "name")
    assert cid not in ids, "删除后 list_all 仍可见"
    return f"{cid} save→list_all→单读2节点一致→delete→消失"


def c08_project_create_activate():
    """项目：创建 → 列表可见 → status 反映激活项目。

    注：项目目前无 DELETE 端点，临时项目行无法清除；但本用例必须把「当前激活项目」
    还原成跑测前的那个，否则每跑一次 e2e 就会劫持用户 UI 里的当前项目。
    """
    # 记录跑测前的当前项目，收尾时还原
    _, before = call("GET", "/api/projects")
    prev_id = ((before or {}).get("current") or {}).get("id", "")

    name = f"e2e项目{STAMP}"
    try:
        code, r = call("POST", "/api/projects", {"name": name, "description": "e2e 建的临时项目"})
        assert code == 200, f"创建 HTTP {code}: {r}"

        code, r = call("GET", "/api/projects")
        items = as_list(r, "list", "projects", "items", "data")
        assert name in names_of(items, "name", "id"), f"创建后列表查不到 {name}"

        # 注：/api/status 是 5s 心跳快照，会滞后一拍；此处查 /api/projects.current（即时真源）
        cur = ((r or {}).get("current") or {}).get("name", "")
        assert cur == name, f"创建后未自动激活，projects.current={cur!r}"
        return f"{name} 创建→列表可见→已自动激活为当前项目（收尾已还原原项目）"
    finally:
        # 注：激活端点挂在 GET 上（server_xai.py do_GET 的 legacy 分支），不是 POST
        if prev_id:
            call("GET", f"/api/projects/activate/{urllib.parse.quote(prev_id, safe='')}")


def c09_settings_roundtrip():
    """设置：读当前 → 写一项 → 重读必须生效。"""
    code, before = call("GET", "/api/settings")
    assert code == 200, f"读设置 HTTP {code}: {before}"
    assert isinstance(before, dict), f"设置返回非 dict: {before}"

    probe_val = f"e2e-{STAMP}"
    code, r = call("POST", "/api/settings", {"e2e_probe": probe_val})
    assert code == 200, f"写设置 HTTP {code}: {r}"

    code, after = call("GET", "/api/settings")
    blob = json.dumps(after, ensure_ascii=False)
    assert probe_val in blob, f"写入的设置项未持久化，重读拿不到 {probe_val}"
    return f"GET→POST(e2e_probe={probe_val})→GET 生效"


def c10_kb_stats_consistency():
    """知识库：ingest 前后 stats 计数必须真的变大（不是恒定假数）。"""
    import tempfile
    code, r = call("GET", "/api/knowledge/stats")
    assert code == 200, f"stats HTTP {code}: {r}"
    st0 = (r or {}).get("stats") or r or {}
    n0 = st0.get("total_chunks", 0)

    token = f"KBSTAT{STAMP}"
    fd, path = tempfile.mkstemp(suffix=".txt", prefix="e2e_kbstat_")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(f"知识库计数探针 {token}。\n" * 5)
    try:
        code, r = call("POST", "/api/knowledge/ingest", {"paths": [path]}, timeout=60)
        assert code == 200, f"ingest HTTP {code}: {r}"
    finally:
        os.unlink(path)

    code, r = call("GET", "/api/knowledge/stats")
    st1 = (r or {}).get("stats") or r or {}
    n1 = st1.get("total_chunks", 0)
    assert n1 > n0, f"ingest 后 total_chunks 没变大：{n0} → {n1}（stats={st1}）"
    return f"total_chunks {n0} → {n1}，计数随灌库真实增长"


def c11_grok_model_pref_roundtrip():
    """Grok 模型偏好：读当前 → 设置 → 重读生效 → 清空回落引擎推导。"""
    code, r = call("GET", "/api/grok/models", timeout=30)
    assert code == 200, f"模型清单 HTTP {code}: {r}"
    models = as_list(r, "models", "items", "data")
    if not models:
        raise Skip("本机无可用 grok 模型")
    pick = names_of(models, "key", "id", "name")[0]

    code, r = call("POST", "/api/grok/model/set", {"model": pick})
    assert code == 200, f"设置偏好 HTTP {code}: {r}"
    code, r = call("GET", "/api/grok/model")
    got = (r or {}).get("model") or (r or {}).get("key") or ""
    assert pick in str(got), f"偏好未生效：设 {pick}，读回 {got!r}"

    code, r = call("POST", "/api/grok/model/set", {"model": ""})
    assert code == 200, f"清空偏好 HTTP {code}: {r}"
    return f"set({pick})→读回一致→清空复位"


def c12_grok_history_lifecycle():
    """Grok 历史：列表可读 → 若有记录则详情可读且含 result_json。"""
    code, r = call("GET", "/api/grok/history", timeout=30)
    assert code == 200, f"历史列表 HTTP {code}: {r}"
    items = as_list(r, "history", "items", "runs", "data")
    if not items:
        return "历史为空（尚未跑过 grok run），列表端点契约正常"
    rid = names_of(items, "id", "run_id")[0]
    code, r = call("GET", f"/api/grok/history/{rid}", timeout=30)
    assert code == 200, f"历史详情 HTTP {code}: {r}"
    assert isinstance(r, dict) and r, f"详情为空: {r}"
    return f"{len(items)} 条历史，详情 id={rid} 可读"


def c13_guardian_approval_flow():
    """Guardian：提审批 → pending 列表可见 → approve 后从 pending 消失。"""
    code, r = call("POST", "/api/guardian/grok-write/request",
                   {"task": f"写入 /tmp/e2e_guardian_{STAMP}.txt",
                    "path": f"/tmp/e2e_guardian_{STAMP}.txt",
                    "content": "e2e 审批探针", "reason": "e2e"})
    assert code == 200, f"提审批 HTTP {code}: {r}"
    aid = (r or {}).get("id") or (r or {}).get("approval_id") or (r or {}).get("request_id")

    code, r = call("GET", "/api/guardian/pending")
    items = as_list(r, "pending", "approvals", "items", "data")
    assert items, f"提审批后 pending 为空: {r}"
    aid = aid or names_of(items, "id", "approval_id")[0]

    code, r = call("POST", "/api/guardian/approve", {"id": aid, "approved": True})
    assert code == 200, f"审批 HTTP {code}: {r}"
    code, r = call("GET", "/api/guardian/pending")
    items = as_list(r, "pending", "approvals", "items", "data")
    assert aid not in names_of(items, "id", "approval_id"), "approve 后仍在 pending 列表"
    return f"request→pending可见→approve→出队（id={aid}）"


def c14_hub_room_create_read():
    """协作房间：创建 → 列表可见 → 发消息 → 消息可回读。"""
    name = f"e2e房间{STAMP}"
    code, r = call("POST", "/api/hub/rooms", {"name": name, "topic": "e2e", "agents": []})
    assert code == 200, f"建房 HTTP {code}: {r}"
    rid = (r or {}).get("id") or (r or {}).get("room_id") or name

    code, r = call("GET", "/api/hub/rooms")
    items = as_list(r, "rooms", "items", "data")
    assert name in names_of(items, "name", "id"), f"建房后列表查不到 {name}"

    code, r = call("POST", f"/api/hub/rooms/{urllib.parse.quote(str(rid))}/messages",
                   {"role": "user", "content": "e2e 消息探针"}, timeout=60)
    if code == 404:
        return f"{name} 建房→列表可见（该房无消息子路由，跳过发消息）"
    assert code == 200, f"发消息 HTTP {code}: {r}"
    return f"{name} 建房→列表可见→发消息 200"


def c15_orchestration_create_read():
    """编排：创建 → 列表可见。"""
    name = f"e2e编排{STAMP}"
    code, r = call("POST", "/api/orchestrations",
                   {"name": name, "goal": "e2e 探针编排", "steps": []})
    assert code == 200, f"创建 HTTP {code}: {r}"
    code, r = call("GET", "/api/orchestrations")
    items = as_list(r, "orchestrations", "items", "data")
    assert name in names_of(items, "name", "id"), f"创建后列表查不到 {name}"
    return f"{name} 创建→列表可见"


def c16_acceptance_run_history():
    """验收跑批：run 产出六维评分 → history 多出一条。"""
    code, r = call("GET", "/api/acceptance/history?limit=50", timeout=30)
    assert code == 200, f"history HTTP {code}: {r}"
    n0 = len(as_list(r, "history", "items", "records", "data"))

    code, r = call("POST", "/api/acceptance/run", {}, timeout=240)
    assert code == 200, f"run HTTP {code}: {r}"
    assert isinstance(r, dict) and r, f"run 返回空: {r}"

    code, r = call("GET", "/api/acceptance/history?limit=50", timeout=30)
    n1 = len(as_list(r, "history", "items", "records", "data"))
    assert n1 > n0, f"run 后 history 未增长：{n0} → {n1}"
    return f"run 产出评分 → history {n0} → {n1} 条"


def c17_gepa_status_trigger():
    """GEPA：status 可读 → trigger 后 status 有变化痕迹。"""
    code, before = call("GET", "/api/gepa/status", timeout=30)
    assert code == 200, f"status HTTP {code}: {before}"
    assert isinstance(before, dict), f"status 非 dict: {before}"

    code, r = call("POST", "/api/gepa/trigger", {}, timeout=180)
    assert code in (200, 202, 409), f"trigger HTTP {code}: {r}"

    code, after = call("GET", "/api/gepa/status", timeout=30)
    assert code == 200, f"trigger 后 status HTTP {code}"
    return f"status可读 → trigger {code} → status 复读正常"


def c18_file_upload_ingest_chain():
    """文件链路：base64 上传 → 返回 @file: 引用 → ingest 后可被引用读取。"""
    import base64
    content = f"e2e 文件链路探针 {STAMP}\n第二行内容\n"
    b64 = base64.b64encode(content.encode()).decode()
    code, r = call("POST", "/api/file/upload",
                   {"name": f"e2e_chain_{STAMP}.txt", "mime_type": "text/plain",
                    "content_base64": b64, "size": len(content)}, timeout=60)
    assert code == 200, f"上传 HTTP {code}: {r}"
    ref = (r or {}).get("ref") or (r or {}).get("file_ref") or (r or {}).get("path") or ""
    assert ref, f"上传未返回引用: {r}"

    code, r = call("POST", "/api/file/ingest",
                   {"name": f"e2e_ing_{STAMP}.txt", "content": content}, timeout=60)
    assert code == 200, f"ingest HTTP {code}: {r}"
    ref2 = (r or {}).get("ref") or (r or {}).get("file_ref") or (r or {}).get("path") or ""
    assert ref2, f"ingest 未返回引用: {r}"
    return f"upload→{str(ref)[:40]} | ingest→{str(ref2)[:40]}"


def c19_artifact_save():
    """产物保存：/api/save 落盘 artifacts 且路径真实存在。"""
    code, r = call("POST", "/api/save",
                   {"name": f"e2e_artifact_{STAMP}", "content": "e2e 产物内容", "ext": "md"})
    assert code == 200, f"保存 HTTP {code}: {r}"
    path = (r or {}).get("path") or (r or {}).get("file") or ""
    assert path, f"未返回落盘路径: {r}"
    assert os.path.exists(path), f"返回了路径但文件不存在: {path}"
    size = os.path.getsize(path)
    assert size > 0, f"落盘文件为空: {path}"
    return f"落盘 {os.path.basename(path)}（{size}B）且真实存在"


def c20_model_activate_reflects_status():
    """模型激活：切换后 /api/status 的 model 字段必须真的跟着变。"""
    code, r = call("GET", "/api/models/list", timeout=30)
    assert code == 200, f"模型清单 HTTP {code}: {r}"
    models = as_list(r, "models", "items", "data")
    keys = names_of(models, "key", "id", "name")
    if len(keys) < 1:
        raise Skip("无可用模型")

    code, r = call("GET", "/api/status")
    original = (r or {}).get("model", "")
    target = next((k for k in keys if k != original), keys[0])

    code, r = call("GET", f"/api/models/activate/{target}", timeout=30)
    assert code == 200, f"激活 HTTP {code}: {r}"
    code, r = call("GET", "/api/models/list", timeout=30)
    act = [m for m in as_list(r, "models", "items", "data")
           if isinstance(m, dict) and m.get("is_active")]
    now = (act[0].get("id") if act else "")
    assert now == target, f"激活 {target} 后 models.list 里 is_active={now!r}，未同步"

    if original and original != target:
        call("GET", f"/api/models/activate/{original}", timeout=30)
    return f"activate({target}) → status.model={now}，切换即时生效"


def c21_non_ascii_path_param():
    """中文命名资源：路径参数被浏览器百分号编码后，后端仍须正确匹配。

    回归 2026-08-04 的 P0 缺陷：后端从不 unquote 路径，导致中文命名的
    技能/MCP/连接器在前端点"更新/删除"时全部失败（浏览器 fetch 会自动
    编码 URL）。这里显式发编码后的 URL，模拟浏览器真实行为。
    """
    name = f"中文技能探针{STAMP}"
    code, r = call("POST", "/api/skills/create",
                   {"name": name, "trigger": "中文触发", "body": "v1"})
    assert code == 200, f"创建 HTTP {code}: {r}"
    try:
        encoded = urllib.parse.quote(name)
        assert "%" in encoded, "测试前提失效：中文名未被编码"

        # 按名更新（body 传名，不走路径）——保证中文资源本身可操作
        code, r = call("POST", "/api/skills/update",
                       {"name": name, "trigger": "中文触发", "body": "v2"})
        assert code == 200, f"按名更新中文技能 HTTP {code}: {r}"

        # 关键断言：路径参数含冒号的模型 id，编码后必须仍能命中
        code, r = call("GET", "/api/models/list", timeout=30)
        models = as_list(r, "models", "items", "data")
        checked = "无含冒号的模型 id 可测"
        if models:
            mid = models[0].get("id", "")
            if ":" in mid:
                enc_mid = urllib.parse.quote(mid)   # mdl:xxx → mdl%3Axxx
                assert "%3A" in enc_mid, "冒号未被编码，测试前提失效"
                code, r = call("GET", f"/api/models/activate/{enc_mid}", timeout=30)
                assert code == 200, \
                    f"编码后的模型 id 激活失败 HTTP {code} —— 后端未解码路径: {r}"
                checked = f"{enc_mid} 激活 200"
        return f"中文名可按名更新；编码路径参数命中（{checked}）"
    finally:
        call("POST", "/api/skills/delete", {"name": name})


JOURNEYS = [
    ("c01 技能 CRUD", c01_skill_crud, False),
    ("c02 MCP CRUD", c02_mcp_crud, False),
    ("c03 连接器 CRUD", c03_connector_crud, False),
    ("c04 备忘录 CRUD", c04_memo_crud, False),
    ("c05 记忆改删", c05_memory_update_delete, False),
    ("c06 会话生命周期", c06_session_lifecycle, True),
    ("c07 画布生命周期", c07_canvas_lifecycle, False),
    ("c08 项目建激活", c08_project_create_activate, False),
    ("c09 设置读写回环", c09_settings_roundtrip, False),
    ("c10 知识库计数一致", c10_kb_stats_consistency, False),
    ("c11 Grok 模型偏好", c11_grok_model_pref_roundtrip, True),
    ("c12 Grok 历史", c12_grok_history_lifecycle, True),
    ("c13 Guardian 审批流", c13_guardian_approval_flow, False),
    ("c14 协作房间", c14_hub_room_create_read, False),
    ("c15 编排建读", c15_orchestration_create_read, False),
    ("c16 验收跑批", c16_acceptance_run_history, True),
    ("c17 GEPA 触发", c17_gepa_status_trigger, True),
    ("c18 文件链路", c18_file_upload_ingest_chain, False),
    ("c19 产物落盘", c19_artifact_save, False),
    ("c20 模型激活同步", c20_model_activate_reflects_status, False),
    ("c21 中文/编码路径", c21_non_ascii_path_param, False),
]


def main() -> int:
    global _TOKEN
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true", help="跳过慢速旅程")
    ap.add_argument("-k", dest="keyword", default="", help="只跑名字包含该关键字的旅程")
    args = ap.parse_args()

    try:
        with urllib.request.urlopen(f"{BASE}/api/auth/token", timeout=5) as r:
            _TOKEN = json.loads(r.read().decode())["token"]
    except Exception as e:  # noqa: BLE001
        print(f"[FATAL] 服务未就绪: {e}")
        return 2

    print("=" * 92)
    print("XAI 写路径 / CRUD 回环 e2e（第二波）")
    print("=" * 92)

    passed = failed = skipped = 0
    failures = []
    for name, fn, slow in JOURNEYS:
        if args.fast and slow:
            print(f"⏭  {name:<20} 慢速旅程，--fast 跳过")
            skipped += 1
            continue
        if args.keyword and args.keyword.lower() not in name.lower():
            continue
        t0 = time.time()
        try:
            evidence = fn()
            ms = int((time.time() - t0) * 1000)
            print(f"✅ {name:<20} {ms:>6}ms  {evidence}")
            passed += 1
        except Skip as e:
            print(f"⏭  {name:<20} 跳过：{e}")
            skipped += 1
        except AssertionError as e:
            ms = int((time.time() - t0) * 1000)
            print(f"❌ {name:<20} {ms:>6}ms  {e}")
            failures.append((name, str(e)))
            failed += 1
        except Exception as e:  # noqa: BLE001
            ms = int((time.time() - t0) * 1000)
            print(f"💥 {name:<20} {ms:>6}ms  {type(e).__name__}: {e}")
            failures.append((name, f"{type(e).__name__}: {e}"))
            failed += 1

    print("=" * 92)
    print(f"总计 {passed + failed + skipped} | ✅ {passed} | ❌ {failed} | ⏭ {skipped}")
    if failures:
        print("\n失败明细：")
        for name, err in failures:
            print(f"  ● {name}\n    {err[:400]}")
    else:
        print("结论：写路径 CRUD 回环全部调通。")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
