"""ForgeArena Performance Benchmark on AMD Radeon GPU"""
import json, urllib.request, time, sys

LLM_URL = "http://localhost:8000/v1/chat/completions"
MODEL = "/root/.cache/modelscope/models/qwen--Qwen2.5-7B-Instruct/snapshots/master"

def call_llm(prompt, max_tokens=300, temp=0.7):
    data = json.dumps({"model": MODEL, "messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens, "temperature": temp}).encode()
    req = urllib.request.Request(LLM_URL, data=data, headers={"Content-Type": "application/json"})
    t0 = time.time()
    resp = urllib.request.urlopen(req, timeout=120)
    result = json.loads(resp.read())
    elapsed = time.time() - t0
    output = result["choices"][0]["message"]["content"]
    return elapsed, len(output), len(output) / elapsed

print("=" * 60)
print("AMD Radeon GPU Benchmark — Qwen2.5-7B + vLLM")
print("=" * 60)
print()

# 1. Single token throughput (streaming equivalent)
print("--- Test 1: Single request throughput ---")
prompts = [
    "用一句话说明AI芯片市场现状。",
    "Bill Seung的投资风格是什么？",
    "SK Hynix在HBM市场的地位如何？",
    "2026年半导体周期处于什么位置？",
]

times = []
for p in prompts:
    t, chars, tps = call_llm(p, max_tokens=150, temp=0.3)
    times.append(t)
    print(f"  Prompt: {p[:30]}... | {t:.2f}s | {tps:.1f} chars/s")

avg_time = sum(times) / len(times)
print(f"  Average: {avg_time:.2f}s per call")
print()

# 2. Throughput with longer output
print("--- Test 2: Longer generation (300 tokens) ---")
long_prompt = "请详细分析未来五年AI产业的投资机会，列出3个主要方向并说明理由。"
t, chars, tps = call_llm(long_prompt, max_tokens=300, temp=0.7)
print(f"  Time: {t:.2f}s, Output: {chars} chars, Speed: {tps:.1f} chars/s")
print()

# 3. Full pipeline simulation (4 calls like do_analyze)
print("--- Test 3: Full pipeline (4 calls) ---")
pipeline_prompts = [
    "你是稳健顾问。Bill Seung最近建仓了什么方向？一句话判断加理由。",
    "你是机会顾问。Bill Seung最近建仓了什么方向？一句话判断加理由。",
    "你是探索顾问。Bill Seung最近建仓了什么方向？一句话判断加理由。",
    "基于以上三位顾问的分析，请生成结构化决策报告（JSON格式）。"
]

pipeline_t0 = time.time()
for i, p in enumerate(pipeline_prompts):
    t, chars, tps = call_llm(p, max_tokens=200 if i < 3 else 400, temp=0.3 if i == 3 else 0.7)
    print(f"  Call {i+1}: {t:.2f}s, {chars} chars, {tps:.1f} chars/s")

pipeline_total = time.time() - pipeline_t0
print(f"  Pipeline total: {pipeline_total:.2f}s")
print()

# 4. Memory usage
print("--- Test 4: GPU Memory ---")
try:
    import subprocess
    result = subprocess.run(["rocm-smi", "--showmeminfo"], capture_output=True, text=True, timeout=5)
    for line in result.stdout.split("\n"):
        if "VRAM" in line or "vram" in line.lower() or "Total" in line or "Used" in line:
            print(f"  {line.strip()}")
except:
    print("  (rocm-smi not available)")

print()
print("=" * 60)
print("Benchmark Complete")
print("=" * 60)
