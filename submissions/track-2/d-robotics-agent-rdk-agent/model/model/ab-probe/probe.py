#!/usr/bin/env python3
"""Fixed probe set against the OpenAI-compatible server on 127.0.0.1:8000.
Deterministic (temperature=0). Records /health + full responses for diff proof.
Usage: python3 probe.py <api_key_file> <out_json>"""
import json, sys, time, urllib.request

KEY = open(sys.argv[1]).read().strip()
OUT = sys.argv[2]
BASE = "http://127.0.0.1:8000"
MODEL = "Qwen3-32B-Agentic-SFT-r1-v3"  # ask for the SFT name; server decides what answers

def call(path, payload=None):
    req = urllib.request.Request(BASE + path, headers={"Authorization": "Bearer " + KEY, "Content-Type": "application/json"},
                                 data=json.dumps(payload).encode() if payload else None)
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read()), round(time.time() - t0, 3)

TOOLS = [{"type": "function", "function": {"name": "bash", "description": "在RDK板上执行命令并返回stdout/stderr/exit code",
          "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}}]

PROBES = [
    {"id": "identity", "messages": [{"role": "user", "content": "你是谁？用一句话介绍你的身份和用途。"}]},
    {"id": "math", "messages": [{"role": "user", "content": "137*24等于多少？只回答数字。"}]},
    {"id": "tool_call", "tools": TOOLS, "messages": [{"role": "user", "content": "查看板上 /app/pydev_demo 目录下有哪些文件"}]},
    {"id": "tool_continuation", "tools": TOOLS, "messages": [
        {"role": "user", "content": "查看servo插件日志的最后两行"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "bash", "arguments": "{\"command\": \"tail -2 /var/log/probe-daemon/servo.log\"}"}}]},
        {"role": "tool", "tool_call_id": "call_1", "content": "{\"stdout\": \"[INFO] servo wave_left completed\\n[INFO] position reset to neutral\", \"exit_code\": 0}"}]},
    {"id": "rdk_domain", "messages": [{"role": "user", "content": "RDK X5 板子上如何确认 BPU 是否正常工作？简要回答。"}]},
    {"id": "exit0_semantics", "messages": [{"role": "user", "content": "机器人执行动作命令返回 exit=0，能证明机器人真的完成了物理动作吗？一句话回答。"}]},
]

health, _ = call("/health")
results = {"captured_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "health": health,
           "requested_model": MODEL, "probes": []}
for p in PROBES:
    payload = {"model": MODEL, "temperature": 0, "max_tokens": 300, "messages": p["messages"]}
    if "tools" in p: payload["tools"] = p["tools"]
    try:
        resp, dt = call("/v1/chat/completions", payload)
        results["probes"].append({"id": p["id"], "latency_s": dt, "request": payload, "response": resp})
        ch = resp["choices"][0]
        brief = ch["message"].get("content") or json.dumps(ch["message"].get("tool_calls"), ensure_ascii=False)
        print(f"[{p['id']}] model={resp.get('model')} finish={ch.get('finish_reason')} {dt}s :: {str(brief)[:110]}")
    except Exception as e:
        results["probes"].append({"id": p["id"], "error": str(e)})
        print(f"[{p['id']}] ERROR {e}")

json.dump(results, open(OUT, "w"), ensure_ascii=False, indent=2)
print("saved:", OUT)
