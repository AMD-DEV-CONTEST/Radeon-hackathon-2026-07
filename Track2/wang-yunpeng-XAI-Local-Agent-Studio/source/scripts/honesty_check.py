#!/usr/bin/env python3
"""XAI 能力诚实度审计 + KB 检索评估脚本。

运行：cd ~/Desktop/mask/xai && python3 scripts/honesty_check.py

检查项：
1. NODE_HANDLER_MAP 所有映射均有真实 handler（无无效 fallback）
2. KB dense_available 与实际 embeddings 端点对齐
3. gateway/status 声明的 real_tools 与 engine.openclaw._tools 一致
4. KB 检索基线评估（同义改述召回率）
"""

import json
import sys
import time
import urllib.request as _ur
import os

JSON_MODE = "--json" in sys.argv
if JSON_MODE:
    import io
    _REAL_STDOUT = sys.stdout
    sys.stdout = io.StringIO()

_RESULTS = []

BASE = "http://127.0.0.1:8000"
TOKEN = os.environ.get("XAI_TOKEN", "")

if not TOKEN:
    try:
        with open(os.path.expanduser("~/.xai/.server_token")) as f:
            TOKEN = f.read().strip()
    except Exception:
        TOKEN = os.environ.get("XAI_TOKEN", "")

def _api(path, method="GET", body=None):
    req = _ur.Request(f"{BASE}{path}", data=body,
                       headers={"X-Auth-Token": TOKEN, "Content-Type": "application/json"})
    try:
        with _ur.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read())
    except Exception as e:
        return 0, {"error": str(e)}

def check(name, ok, detail=""):
    status = "PASS" if ok else "FAIL"
    _RESULTS.append({"name": name, "status": status, "detail": detail})
    if not JSON_MODE:
        print(f"  [{status}] {name}" + (f" - {detail}" if detail else ""))

print("=" * 60)
print("XAI 诚实度审计")
print("=" * 60)

# 1. NODE_HANDLER_MAP 完整性
print("\n1. Node handler map integrity")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core.node_registry import NODE_HANDLER_MAP
from core.kernel import workflow as wf_mod
from core.kernel.workflow import wf_node_chat  # fallback

missing = []
for ntype, hname in NODE_HANDLER_MAP.items():
    if hname == "wf_node_chat":
        continue  # explicit fallback OK
    handler = getattr(wf_mod, hname, None)
    if handler is None or not callable(handler):
        missing.append((ntype, hname))

check("no missing handlers", len(missing) == 0,
      f"{len(missing)} gaps: {missing}" if missing else "all mapped")
if missing:
    for ntype, hname in missing:
        print(f"    [{ntype}] → {hname} NOT FOUND in workflow.py")
        _RESULTS.append({"name": f"handler[{ntype}]", "status": "FAIL", "detail": f"{hname} NOT FOUND in workflow.py"})

# Special: openclaw must NOT map to wf_node_chat or wf_node_mcp
oc_handler = NODE_HANDLER_MAP.get("openclaw", "")
check("openclaw node wired to real handler", oc_handler == "wf_node_openclaw",
      f"current: {oc_handler} (should be wf_node_openclaw)")

# 2. KB dense availability
print("\n2. KB / embeddings alignment")
status, kb_stats = _api("/api/knowledge/stats")
if status == 200 and kb_stats.get("ok"):
    stats = kb_stats.get("stats", {})
    dense_ok = stats.get("dense_available", False)
    count = stats.get("total_chunks", 0)
    sources = stats.get("sources", 0)
    check("dense_available=true", dense_ok, f"{count} chunks, {sources} sources")

    # Test real embedding call
    _, search_res = _api("/api/knowledge/search",
                         method="POST",
                         body=json.dumps({"query": "系统自检怎么跑"}).encode())
    hit_count = len(search_res.get("hits", [])) if search_res.get("ok") else 0
    check("KB search returns hits", hit_count > 0, f"{hit_count} hits")
    if hit_count:
        top_score = search_res["hits"][0]["score"]
        check("dense scoring works (top score > 0.5)", top_score > 0.5,
              f"top score={top_score:.4f}")
else:
    check("KB stats endpoint alive", False, str(kb_stats.get("error", "no response")))

# 3. Gateway status honesty
print("\n3. Gateway / engine capability honesty")
status, gw = _api("/api/gateway/status")
if status == 200 and gw.get("ok"):
    real_tools = gw.get("real_tools", [])
    simulated = gw.get("simulated", True)
    cap_status = gw.get("capability_status", {})

    check("gateway reports real tools", len(real_tools) > 0,
          f"{len(real_tools)} real: {real_tools}")
    check("shell capability = real", cap_status.get("shell") == "real",
          f"shell={cap_status.get('shell')}")
    check("exec tool listed", "exec" in real_tools,
          f"tools: {real_tools[:4]}...")

    # Gateway simulated_capabilities should NOT include shell
    sim_caps = gw.get("simulated_capabilities", [])
    check("simulated list excludes real ones", "shell" not in sim_caps,
          f"simulated={sim_caps}")
else:
    check("gateway status alive", False, str(gw))

# 4. Sandbox honesty
print("\n4. Sandbox endpoint honesty")
status, sb = _api("/api/system/sandbox")
if status == 200:
    note = sb.get("note", "")
    check("sandbox has honesty note", len(note) > 10, f"note={note[:60]}...")
    check("effective sandbox exists", bool(sb.get("effective")),
          f"effective={sb.get('effective')}")
else:
    check("sandbox alive", False, str(sb))

# 5. Query rewrite recall (basic KB eval)
print("\n5. KB retrieval recall (paraphrase test)")
test_queries = [
    ("grok 登录不上怎么办", "grok 认证失败怎么处理"),
    ("怎么查看系统健康状态", "系统体检命令是什么"),
    ("记忆怎么按项目分开", "切换项目记忆会不会串"),
]
recalls = []
for original, paraphrase in test_queries:
    _, r1 = _api("/api/knowledge/search", method="POST",
                 body=json.dumps({"query": original}).encode())
    _, r2 = _api("/api/knowledge/search", method="POST",
                 body=json.dumps({"query": paraphrase}).encode())
    h1 = [h.get("source","") for h in r1.get("hits",[]) if r1.get("ok")]
    h2 = [h.get("source","") for h in r2.get("hits",[]) if r2.get("ok")]
    common = len(set(h1[:3]) & set(h2[:3]))
    recalls.append(common)
    check(f"  {original[:20]}...  /  {paraphrase[:20]}...", common >= 1,
          f"overlap={common}/3")

avg_recall = sum(recalls) / max(len(recalls), 1)
check("avg recall@3 >= 0.5", avg_recall >= 0.5,
      f"avg={avg_recall:.2f} (target ≥ 0.5)")

print("\n" + "=" * 60)
print("审计完成。")
print("=" * 60)

if JSON_MODE:
    sys.stdout = _REAL_STDOUT
    fails = sum(1 for c in _RESULTS if c["status"] != "PASS")
    json.dump({
        "tool": "honesty_check",
        "ts": int(time.time()),
        "ok": fails == 0,
        "summary": {"total": len(_RESULTS), "pass": len(_RESULTS) - fails, "fail": fails},
        "checks": _RESULTS,
    }, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    sys.exit(0)
