#!/usr/bin/env python3
"""
Benchmark LLM — 检测本地 LLM 服务健康与性能。
用于 GPU Demo 环节展示真实推理指标。

用法:
    python3 scripts/benchmark_llm.py

环境变量:
    LLM_BASE_URL: LLM 服务地址（默认 http://localhost:8000/v1）
    LLM_MODEL: 模型名称（默认 local-model）
"""

import json
import os
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path


def check_llm_health(base_url: str) -> dict:
    """检查 LLM 服务是否可达，返回模型列表。"""
    url = f"{base_url}/models"
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            models = [m.get("id", "?") for m in data.get("data", [])]
            return {"reachable": True, "models": models, "error": None}
    except Exception as e:
        return {"reachable": False, "models": [], "error": str(e)}


def send_chat_completion(base_url: str, model: str, prompt: str) -> dict:
    """发送 chat completion 请求，返回响应和耗时。"""
    url = f"{base_url}/chat/completions"
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 512,
    }).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            elapsed = time.time() - start
            data = json.loads(resp.read().decode())
            content = data["choices"][0]["message"]["content"]
            return {
                "success": True,
                "elapsed_seconds": round(elapsed, 3),
                "output_chars": len(content),
                "content_preview": content[:200],
                "error": None,
            }
    except Exception as e:
        elapsed = time.time() - start
        return {
            "success": False,
            "elapsed_seconds": round(elapsed, 3),
            "output_chars": 0,
            "content_preview": "",
            "error": str(e),
        }


def main():
    base_url = os.getenv("LLM_BASE_URL", "http://localhost:8000/v1")
    model = os.getenv("LLM_MODEL", "local-model")
    started_at = datetime.now(timezone.utc).isoformat()

    print("=" * 60)
    print("   InventoryDoc Agent — LLM Benchmark")
    print("=" * 60)
    print(f"  LLM_BASE_URL : {base_url}")
    print(f"  LLM_MODEL    : {model}")
    print()

    # Step 1: 健康检查
    print(">>> [1/2] 检查 LLM 服务状态...")
    health = check_llm_health(base_url)
    if not health["reachable"]:
        print(f"  ❌ LLM 服务不可达: {health['error']}")
        print()
        print("  请确保 LLM 推理服务已启动，例如：")
        print("    - llama.cpp:  ./llama-server --host 0.0.0.0 --port 8000 -m model.gguf")
        print("    - vLLM:       vllm serve <模型名> --host 0.0.0.0 --port 8000")
        print()

        models = health["models"]
        finished_at = datetime.now(timezone.utc).isoformat()
        result = {
            "started_at": started_at,
            "finished_at": finished_at,
            "base_url": base_url,
            "requested_model": model,
            "selected_model": None,
            "models": models,
            "reachable": False,
            "error": health["error"],
            "benchmark": None,
        }
        output_dir = Path("data/output")
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "llm_benchmark.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"  结果已保存到 data/output/llm_benchmark.json")
        print("=" * 60)
        return

    models = health["models"]
    selected_model = models[0] if models else model
    print(f"  ✅ LLM 服务可达")
    print(f"  模型列表: {models}")
    print(f"  选定模型: {selected_model}")
    print()

    # Step 2: 推理基准
    print(">>> [2/2] 测试推理性能...")
    prompt = "用一句话说明库存审计 Agent 对于企业仓储管理的价值。"
    bench = send_chat_completion(base_url, model, prompt)

    if bench["success"]:
        elapsed = max(bench["elapsed_seconds"], 0.001)
        chars_per_sec = bench["output_chars"] / elapsed
        estimated_tokens = max(bench["output_chars"] / 1.8, 1)
        estimated_tokens_per_second = estimated_tokens / elapsed
        print(f"  ✅ 推理成功")
        print(f"  耗时              : {bench['elapsed_seconds']:.2f}s")
        print(f"  输出字符数        : {bench['output_chars']}")
        print(f"  速度              : {chars_per_sec:.0f} chars/s")
        print(f"  估算 Token 速度   : {estimated_tokens_per_second:.0f} tokens/s")
        print(f"  输出预览          : {bench['content_preview']}")
    else:
        chars_per_sec = 0
        estimated_tokens_per_second = 0
        print(f"  ❌ 推理失败: {bench['error']}")
    print()

    finished_at = datetime.now(timezone.utc).isoformat()

    # 保存结果
    result = {
        "started_at": started_at,
        "finished_at": finished_at,
        "base_url": base_url,
        "requested_model": model,
        "selected_model": selected_model,
        "models": models,
        "reachable": True,
        "error": None,
        "benchmark": {
            "prompt": prompt,
            "success": bench["success"],
            "elapsed_seconds": bench["elapsed_seconds"],
            "output_chars": bench["output_chars"],
            "chars_per_second": round(chars_per_sec, 1),
            "estimated_tokens_per_second": round(estimated_tokens_per_second, 1),
            "content_preview": bench["content_preview"][:200],
            "error": bench["error"],
        },
    }
    output_dir = Path("data/output")
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "llm_benchmark.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  结果已保存到 data/output/llm_benchmark.json")
    print("=" * 60)


if __name__ == "__main__":
    main()
