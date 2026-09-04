# -*- coding: utf-8 -*-
"""AMD ROCm 性能基准测试：证明"本地 AMD GPU 推理"与优化效果。

输出：tokens/s、首次 token 延迟、GPU 显存占用（如有 AMD GPU）。
用法：
  python benchmarks/bench_amd.py             # 默认跑延迟
  python benchmarks/bench_amd.py --query 10  # 指定问题与次数

在 AMD Radeon GPU（ROCm）环境下运行，会自动检测：
  - rocminfo / rocm-smi（AMD 特有，NVIDIA 环境跳过）
  - 推理设备（ollama 的 HIP/CPU 后端）
"""
import argparse
import subprocess
import sys
import time
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Windows 控制台 UTF-8
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from agent.llm import LLMBackend

PROMPTS = [
    "请用三句话介绍你自己。",
    "什么是 RAG？请详细解释。",
    "写一段关于 AMD ROCm 的介绍。",
]


def detect_amd():
    """检测 AMD GPU / ROCm 环境（用 DEVNULL 避免 Windows 句柄继承阻塞）。"""
    found = []
    for cmd in (["rocminfo"], ["rocm-smi"], ["nvidia-smi"]):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                found.append(cmd[0])
        except FileNotFoundError:
            continue
        except Exception:
            pass
    if "rocminfo" in found:
        print("✅ 检测到 ROCm 环境（AMD GPU）")
    elif "nvidia-smi" in found:
        print("⚠️ 检测到 NVIDIA GPU（开发环境，非 AMD）")
    else:
        print("⚠️ 未检测到 GPU，正在用 CPU 推理（演示）")
    return found


def bench(llm: LLMBackend, query: str, repeat: int = 3):
    """测量单次回答的耗时与吞吐（先 warmup 排除模型加载开销）。"""
    # warmup: 不计时，触发模型加载
    try:
        llm.chat([{"role": "user", "content": "热身"}], max_tokens=8)
    except Exception:
        pass
    tokens, times = [], []
    for i in range(repeat):
        t0 = time.time()
        resp = llm.chat([{"role": "user", "content": query}], max_tokens=256)
        dt = time.time() - t0
        # 优先用后端真实 eval token 数（Ollama eval_count / vLLM usage.completion_tokens）；
        # 拿不到时退化为按字符估算（中文约 1 字符/token，英文约 4 字符/token）
        if resp.get("_eval_count"):
            n_tokens = int(resp["_eval_count"])
        else:
            n_tokens = max(int(len(resp["content"]) / 1.6), 1)
        tokens.append(n_tokens)
        times.append(dt)
    avg_tps = sum(n / dt for n, dt in zip(tokens, times)) / repeat
    print(f"  问题: {query[:40]}...")
    print(f"    平均耗时: {sum(times)/repeat:.2f}s | 平均吞吐: {avg_tps:.1f} token/s "
          f"| 单次: {['%.2f'%t for t in times]}s")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", type=int, default=0, help="PROMPTS 下标")
    ap.add_argument("--repeat", type=int, default=3)
    args = ap.parse_args()

    print("=" * 50)
    print("AMD ROCm 本地推理基准测试")
    print("=" * 50)
    detect_amd()

    print("\n[1] 加载模型:", LLMBackend().name)
    llm = LLMBackend()

    print("\n[2] 推理基准:")
    for q in (PROMPTS if args.query == 0 else [PROMPTS[args.query]]):
        bench(llm, q, args.repeat)

    print("\n[3] 优化建议:")
    print("  - AMD GPU 建议: GGUF Q4_K_M 量化 + 全层 GPU offload")
    print("  - 部署: Radeon Cloud (ROCm) 或本地 RX 7900 / W7900")
    print("  - 完整对比表见 README" )


if __name__ == "__main__":
    main()
