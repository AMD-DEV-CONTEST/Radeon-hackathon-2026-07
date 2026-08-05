import json, os, sys, time, urllib.request

URL = "http://127.0.0.1:8080/v1/chat/completions"
KEY = os.getenv("LLM_API_KEY", "")
HEADERS = {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}

PAD = ("In a large-scale Hadoop cluster, the NameNode maintains the entire filesystem namespace "
       "and regulates access to files by clients. When a DataNode fails to send heartbeat signals "
       "within the configured timeout interval, the NameNode marks that node as dead and initiates "
       "replication of its blocks to other live DataNodes to maintain the configured replication factor. "
       "Common causes of DataNode heartbeat loss include network partition, excessive garbage collection "
       "pauses in the JVM, disk failures, and resource contention from co-located workloads. ")

target = int(sys.argv[1]) if len(sys.argv) > 1 else 4000
gen_n  = int(sys.argv[2]) if len(sys.argv) > 2 else 256

repeats = max(1, target // 80)
prompt = PAD * repeats + "\n\nBased on the above context, briefly summarize in one sentence what causes DataNode heartbeat loss. "
body = json.dumps({
    "model": "Qwopus3.6-27B",
    "messages": [{"role": "user", "content": prompt}],
    "max_tokens": gen_n, "stream": False, "temperature": 0.3,
}).encode()
t0 = time.time()
req = urllib.request.Request(URL, data=body, headers=HEADERS)
resp = urllib.request.urlopen(req, timeout=1200)
data = json.loads(resp.read())
wall = time.time() - t0
t = data.get("timings", {})
u = data.get("usage", {})
pt = u.get("prompt_tokens", 0)
print(f"ctx={pt:6d} | gen_t/s={t.get('predicted_per_second',0):6.1f} | "
      f"prompt_t/s={t.get('prompt_per_second',0):7.1f} | TTFT={t.get('prompt_ms',0)/1000:.2f}s | "
      f"wall={wall:.1f}s | gen_tokens={u.get('completion_tokens')}")
