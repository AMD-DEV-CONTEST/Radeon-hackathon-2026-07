import json, os, time, urllib.request

URL = "http://127.0.0.1:8080/v1/chat/completions"
KEY = os.getenv("LLM_API_KEY", "")
HEADERS = {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}

def bench(label, prompt, max_tokens=2048):
    body = json.dumps({
        "model": "Qwopus3.6-27B",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "stream": False,
        "temperature": 0.7,
    }).encode()
    t0 = time.time()
    req = urllib.request.Request(URL, data=body, headers=HEADERS)
    resp = urllib.request.urlopen(req, timeout=600)
    data = json.loads(resp.read())
    wall = time.time() - t0
    t = data.get("timings", {})
    u = data.get("usage", {})
    print(f"\n===== {label} =====")
    print(f"  prompt_tokens     : {u.get('prompt_tokens')}")
    print(f"  cached_tokens     : {u.get('prompt_tokens_details',{}).get('cached_tokens')}")
    print(f"  completion_tokens : {u.get('completion_tokens')}")
    print(f"  prompt t/s        : {t.get('prompt_per_second',0):.1f}")
    print(f"  generate t/s      : {t.get('predicted_per_second',0):.1f}")
    print(f"  wall time         : {wall:.1f}s")
    print(f"  TTFT              : {t.get('prompt_ms',0)/1000:.2f}s")

# Test 1: short prompt, long generation
bench("短prompt长生成(2048)",
      "请详细分析Hadoop集群NameNode RPC延迟飙高的原因，从网络、磁盘IO、JVM GC、堆内存、文件数、客户端连接数、DataNode心跳等维度逐一展开，每个维度给出排查步骤和修复建议，写成完整技术报告。",
      max_tokens=2048)

# Test 2: short prompt, even longer
bench("短prompt长生成(4096)",
      "写一份大数据平台运维手册，覆盖HDFS、YARN、Hive、HBase四大组件的常见故障、排查方法、修复步骤和预防措施，每个组件至少5个故障场景。",
      max_tokens=4096)
