#!/usr/bin/env python3
"""bench.py — measure single-model VRAM + throughput on a realistic extraction prompt.

Usage:
  python scripts/bench.py <base_url> <model> [max_tokens]

Reads /persistent/learning-companion/data/sample_input.txt as the extraction source
if present, else uses a built-in sample. Prints JSON with timings + VRAM snapshot.
"""
import json, sys, time, urllib.request, subprocess

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000/v1"
MODEL = sys.argv[2] if len(sys.argv) > 2 else "Qwen2.5-14B-Instruct"
MAX_TOK = int(sys.argv[3]) if len(sys.argv) > 3 else 600

SAMPLE = (
    "分布式系统中的共识算法用于确保多个节点对同一状态达成一致。"
    "Paxos 是最早的共识协议之一，由 Leslie Lamport 提出。Raft 则通过强领导者简化了理解。"
    "Raft 将问题分解为领导者选举、日志复制、安全性保证和成员变更。"
    "在领导者选举中，每个节点有随机超时，超时后变为候选者并请求投票，获得多数选票者成为领导者。"
    "日志复制中，领导者将新日志条目发送给跟随者，多数确认后提交。安全性保证已提交的条目不会被覆盖。"
    "成员变更使用联合共识，新旧配置重叠以避免分裂。"
    "此外，快照压缩用于控制日志无限增长。投票期间节点会暂存新的日志条目。"
)

def gpu_vram_gb() -> float:
    try:
        out = subprocess.run(["rocm-smi", "--showmeminfo", "vram"], capture_output=True, text=True, timeout=10).stdout
        for line in out.splitlines():
            if "VRAM Total Used Memory" in line:
                return round(int(line.split(":")[-1].strip()) / 1e9, 2)
    except Exception:
        pass
    return -1.0

def call(stream):
    body = json.dumps({
        "model": MODEL,
        "messages": [
            {"role": "system", "content": "你是卡片抽取引擎。从用户材料中抽取 3-5 张学习卡片，每张包含：概念、要点、示例。输出 JSON 数组。"},
            {"role": "user", "content": "以下是待分析材料：\n---\n" + SAMPLE + "\n---\n请抽取卡片。"},
        ],
        "max_tokens": MAX_TOK,
        "temperature": 0.2,
        "stream": stream,
    }).encode()
    req = urllib.request.Request(BASE + "/chat/completions", data=body, headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=300) as r:
        data = json.loads(r.read())
    dt = time.time() - t0
    usage = data.get("usage", {})
    comp = usage.get("completion_tokens", 0)
    prompt = usage.get("prompt_tokens", 0)
    return {
        "model": MODEL, "prompt_tokens": prompt, "completion_tokens": comp,
        "latency_s": round(dt, 2), "tok_per_s": round(comp / dt, 2) if dt else 0,
        "ttfb_ms": None, "vram_used_gb": gpu_vram_gb(),
    }

if __name__ == "__main__":
    # warmup
    call(False)
    results = [call(False) for _ in range(3)]
    med = sorted(r["tok_per_s"] for r in results)[1]
    print(json.dumps({
        "runs": results,
        "median_tok_per_s": med,
        "note": "single-model baseline, batch=1, temperature=0.2",
    }, ensure_ascii=False, indent=2))
