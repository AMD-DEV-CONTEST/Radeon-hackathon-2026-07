import urllib.request, json, time

BASE="http://127.0.0.1:8080"
def post(path, payload):
    req=urllib.request.Request(BASE+path, data=json.dumps(payload).encode(),
        headers={"Content-Type":"application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=200) as r:
        return json.loads(r.read())

def set_adapter(ids):
    body = [{"id": i, "scale": 1.0} for i in (ids or [])]
    post("/lora-adapters", body)

def chat(prompt, max_tokens=400):
    out=post("/v1/chat/completions", {
        "model":"Qwen3.6-27B",
        "messages":[{"role":"user","content":prompt}],
        "temperature":0,"max_tokens":max_tokens,
        "chat_template_kwargs":{"enable_thinking":False}})
    m=out["choices"][0]["message"]
    return m.get("content","") or ""

EXPERTS = {
  "teichai_fable5_plan": (0, [
     "调查一份 ROCm 迁移计划的主要风险，先给出分步调查方案。",
     "用户投诉登录慢，规划一个端到端根因调查，列出步骤。",
     "分析为什么这个微服务在高峰期会雪崩，给出排查步骤。"]),
  "btl3": (1, [
     "解释为什么这段代码慢，并给出修复：for i in range(n): tok = Tokenizer()  # 循环里反复新建分词器; bio = tok(text)",
     "写一个 Python 二分查找函数，在有序数组里找目标值下标，找不到返回 -1。",
     "下面这段代码时间复杂度为什么是 O(n^2)？如何优化：for i in range(n): for j in range(n): if a[i]==a[j]: print(i,j)"]),
  "cybersec": (2, [
     "这段日志有没有入侵痕迹？日志：Aug 12 03:14 sshd[882]: Failed password for root from 91.214.x.x port 44221 ssh2，1 分钟内重复 200 次。",
     "这段 SQL 有注入风险吗？代码：sql = \"SELECT * FROM users WHERE name='\" + name + \"'\"; 如何修复？",
     "以下鉴权配置有什么漏洞：token 存 localStorage、不做过期校验、允许弱密码。"]),
  "rag_n7": (3, [
     "根据证据回答问题并引用来源。证据1(migration_plan.md#L12)：先切读副本。证据2(migration_plan.md#L42)：灰度 5%。问：迁移第一步该做什么？",
     "根据文档回答并标注出处。文档：Qwen3.6 采用 DeltaNet 线性注意力机制（line 3）；上下文窗口扩展到 256K（line 7）。问：Qwen3.6 的两个关键架构改动是什么？",
     "根据产品文档回答并引用来源。文档 FAQ 第2条：本产品支持将数据导出为 PDF（line 5）。问：是否支持离线导出？"]),
}

switch_ms={}
for name,(aid,prompts) in EXPERTS.items():
    print(f"\n===== EXPERT {name} (lora id={aid}) =====")
    for p in prompts:
        set_adapter(None)
        t0=time.time(); base=chat(p); tb=time.time()-t0
        t1=time.time(); set_adapter([aid]); tsw=time.time()-t1
        t2=time.time(); exp=chat(p); te=time.time()-t2
        switch_ms.setdefault(name,[]).append(tsw*1000)
        differs = base.strip() != exp.strip()
        print(f"[P] {p[:28]}")
        print(f"   base({tb:.1f}s): {base[:120]!r}")
        print(f"   exp ({te:.1f}s, switch={tsw*1000:5.0f}ms): {exp[:120]!r}")
        print(f"   DIFFERS={differs} base_len={len(base)} exp_len={len(exp)}")
print("\n===== G4 hot-swap latency (mean per expert) =====")
for k,v in switch_ms.items():
    print(f"  {k:22s} mean={sum(v)/len(v):6.1f}ms  n={len(v)}")
