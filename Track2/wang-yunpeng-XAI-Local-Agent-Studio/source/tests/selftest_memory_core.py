"""memory_core 接线自测"""
import sys, os, json, urllib.request
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from core.memory_core import default_core

PASS = FAIL = 0
def ok(n, c, d=""):
    global PASS, FAIL
    print(["  ❌","  ✅"][c], n, (f" | {d}" if d else ""))
    PASS += c; FAIL += not c

print("\n=== memory_core 接线自测 ===\n")

# API endpoint
resp = urllib.request.urlopen("http://localhost:8000/api/memory", timeout=5)
j = json.loads(resp.read())
ok("API 返回 200 正确格式", "core" in j and "adapter" in j and "core_db" in j, list(j.keys()))
ok("core_db → memory.db", j["core_db"].endswith("memory.db"))

# DB operations
mc = default_core()
eid = mc.store("working", "test:ping", "验证值", engine="xai", importance=0.5)
ok("store", eid > 0)
e = mc.get("working", "test:ping")
ok("get", e and e.value == "验证值")
ok("engine 标签 xai", e and e.engine == "xai")
mc.update(eid, value="已更新", importance=0.8)
u = mc.get("working", "test:ping")
ok("update 值", u and u.value == "已更新")
ok("update importance", u and abs(u.importance - 0.8) < 0.01)
ok("query engine=xai", len(mc.query(engine="xai", limit=20)) >= 1)
ok("recall 关键词", len(mc.recall("验证", 5)) >= 1)

# Cross-engine
aid = mc.store("anchor", "test:multi", "多引擎", engine="grok_build", importance=0.7)
ok("store engine=grok_build", aid > 0)
gb = mc.query(engine="grok_build", limit=5)
ok("query engine=grok_build", len(gb) >= 1)
ok("engine 不混淆", all(e2.engine == "grok_build" for e2 in gb))

# Stats
layers = mc.stats()
ok("stats >=2 layers", len(layers) >= 2, str(layers))

# Cleanup
mc._conn.execute("DELETE FROM memory WHERE key LIKE 'test:%'")
mc._conn.commit()
ok("清理完成", mc.get("working", "test:ping") is None)

print(f"\nPhase 1 Step 1 结果: {PASS}/{PASS+FAIL} 通过\n")
