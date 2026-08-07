# -*- coding: utf-8 -*-
"""磐石（Radeon-Assistant）模型能力基准测试。

复用 inference.engine.InferenceEngine 与 agent.prompts 中的「磐石」硬件研发
system prompt，对模型在三大典型场景下的能力做可复现的自动化测试：

  1. 知识检索（芯片参数问答，无 RAG 的通用知识基线）
  2. 日志分析（串口日志异常定位）
  3. 代码生成（SystemVerilog Testbench）
  4. 工程计算（分压电阻求值）

测量指标：
  - 生成速度（tokens/s，与 README / spec 的口径一致：总 token 数 / 总耗时）
  - 首字延迟（若引擎支持流式则记录，否则以总耗时近似）
  - 显存占用（torch.cuda.memory_reserved，ROCm 下即 HIP 显存）
  - 关键词命中率（自动评分代理，非人工判分；用于横向对比 7B/14B/32B）

输出：
  - 终端打印 Markdown 汇总表
  - docs/benchmark_<model>.md   人类可读结果
  - docs/benchmark_<model>.json 机器可读结果（便于后续拼选型对比表）

用法（在 Radeon Cloud / Linux + AMD GPU 终端，项目根目录下）：
    python scripts/benchmark.py --model qwen2.5-14b
    python scripts/benchmark.py --model qwen2.5-7b
    python scripts/benchmark.py --model qwen2.5-32b

注意：本机（Windows 桌面，无 AMD GPU / ROCm）无法运行，必须在 ROCm 环境执行。
"""

import os
import sys
import time
import json
import argparse

# ---------------------------------------------------------------------------
# ROCm 环境变量：必须在 import torch / vllm 之前设置（与 engine.py 保持一致）
# ---------------------------------------------------------------------------
os.environ.setdefault("HSA_OVERRIDE_GFX_VERSION", "11.0.0")
os.environ.setdefault("PYTORCH_ROCM_ARCH", "gfx1100")
os.environ.setdefault("HIP_VISIBLE_DEVICES", "0")
os.environ.setdefault("HSA_ENABLE_SDMA", "0")
os.environ.setdefault("VLLM_WORKER_MULTIPROC_METHOD", "spawn")
# glibc 2.35 (Ubuntu 22.04) 兼容 + flash-attn ROCm 启用（与 app.py / scripts/serve.py 一致）
os.environ.setdefault("FLASH_ATTENTION_TRITON_AMD_ENABLE", "TRUE")
os.environ.setdefault(
    "PYTHONPATH",
    os.path.join(sys.prefix, "lib", "python3.14", "site-packages",
                 "_rocm_sdk_core", "share", "amd_smi"),
)

# 把项目根目录加入 sys.path，使 `inference` / `agent` 可被导入
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from inference.engine import InferenceEngine, InferenceConfig
from agent.prompts import get_system_prompt


MODEL_DIR_MAP = {
    "qwen2.5-7b": "./models/Qwen2.5-7B-Instruct",
    "qwen2.5-14b": "./models/Qwen2.5-14B-Instruct",
    "qwen2.5-32b": "./models/Qwen2.5-32B-Instruct",
}

# 测试集：每条含 id / 场景 / 问题 / 期望关键词（小写匹配）
# 关键词用于自动评分代理，命中率仅作横向对比参考，不代表人工判分准确率。
TEST_CASES = [
    {
        "id": "T1",
        "scene": "知识检索",
        "prompt": "STM32H7 系列 MCU 的 SPI 外设最高支持到多少 MHz 的时钟频率？请给出具体数值和单位，并说明以哪份文档为准。",
        "keywords": ["mhz", "spi", "datasheet", "参考手册"],
    },
    {
        "id": "T2",
        "scene": "参数比对",
        "prompt": "请比较 STM32F1 系列与 STM32H7 系列在 CPU 主频上的差异，给出具体数值。",
        "keywords": ["mhz", "f1", "h7", "主频"],
    },
    {
        "id": "T3",
        "scene": "日志分析",
        "prompt": (
            "以下是某设备串口日志片段，请找出其中的异常，指出异常发生的位置/帧号，"
            "并给出可能原因：\n"
            "UART0: boot ok\n"
            "UART0: sensor init pass\n"
            "UART0: frame 41 recv 0xAB len=8\n"
            "UART0: ERROR: checksum mismatch at frame 42\n"
            "UART0: frame 43 recv 0x3C len=8\n"
            "UART0: WARNING: retry timeout on frame 42\n"
        ),
        "keywords": ["checksum", "frame 42", "异常", "重传", "retry"],
    },
    {
        "id": "T4",
        "scene": "代码生成",
        "prompt": (
            "请为一个 UART 接收模块（8N1，波特率 115200，时钟 50MHz）生成一段 "
            "SystemVerilog testbench，要求包含时钟生成、复位、以及基本的接收数据检查逻辑。"
        ),
        "keywords": ["module", "testbench", "initial", "@(posedge", "115200"],
    },
    {
        "id": "T5",
        "scene": "工程计算",
        "prompt": (
            "用 3.3V 供电，目标将分压点稳定到 1.8V，支路总电流 1mA，"
            "求上分压电阻和下分压电阻的阻值，并给出单位和计算过程。"
        ),
        "keywords": ["ω", "kω", "1.5", "1.8"],
    },
]


def measure_vram_bytes():
    """尝试读取 ROCm(HIP) 显存占用，失败返回 None。"""
    try:
        import torch
        if hasattr(torch, "cuda") and torch.cuda.is_available():
            return torch.cuda.memory_reserved(0)
    except Exception:
        pass
    return None


def score_keywords(text: str, keywords) -> float:
    """返回命中关键词比例（0~1）。"""
    low = text.lower()
    if not keywords:
        return 1.0
    hit = sum(1 for kw in keywords if kw.lower() in low)
    return hit / len(keywords)


def run_benchmark(model_name: str):
    model_path = MODEL_DIR_MAP.get(model_name, model_name)
    if not os.path.exists(model_path):
        raise SystemExit(
            f"模型未找到: {model_path}\n"
            f"请先下载: python scripts/download_model.py --model {model_name}"
        )

    print(f"[*] 加载模型 {model_name} @ {model_path} ...")
    cfg = InferenceConfig(
        model_path=model_path,
        n_ctx=8192,
        temperature=0.0,      # 基准测试用贪心解码，保证可复现
        max_tokens=2048,
        dtype="float16",
        gpu_memory_utilization=0.90,
        tensor_parallel_size=1,
        pipeline_parallel_size=1,
    )
    engine = InferenceEngine(cfg)
    tokenizer = engine.tokenizer
    system_prompt = get_system_prompt("hardware")

    vram_before = measure_vram_bytes()

    results = []
    total_tok = 0
    total_time = 0.0

    for case in TEST_CASES:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": case["prompt"]},
        ]
        t0 = time.perf_counter()
        out = engine.chat_completion(messages, temperature=0.0, max_tokens=2048)
        dt = time.perf_counter() - t0

        n_tok = len(tokenizer.encode(out)) if tokenizer else 0
        tps = n_tok / dt if dt > 0 else 0.0
        score = score_keywords(out, case["keywords"])

        total_tok += n_tok
        total_time += dt
        results.append({
            "id": case["id"],
            "scene": case["scene"],
            "time_s": round(dt, 2),
            "tokens": n_tok,
            "tokens_per_s": round(tps, 1),
            "keyword_hit": round(score, 2),
            "output_preview": out[:160].replace("\n", " "),
        })
        print(f"  [{case['id']}] {case['scene']:<6} {n_tok:>4} tok  {tps:>6.1f} tok/s  "
              f"命中 {score*100:>5.0f}%  {case['id']}")

    vram_after = measure_vram_bytes()
    avg_tps = total_tok / total_time if total_time > 0 else 0.0
    avg_hit = sum(r["keyword_hit"] for r in results) / len(results)

    summary = {
        "model": model_name,
        "model_path": model_path,
        "dtype": cfg.dtype,
        "avg_tokens_per_s": round(avg_tps, 1),
        "total_tokens": total_tok,
        "total_time_s": round(total_time, 2),
        "avg_keyword_hit": round(avg_hit, 2),
        "vram_reserved_gb": round(vram_after / (1024 ** 3), 1) if vram_after else None,
        "vram_before_gb": round(vram_before / (1024 ** 3), 1) if vram_before else None,
        "dataset": [{"id": c["id"], "scene": c["scene"], "keywords": c["keywords"]} for c in TEST_CASES],
        "results": results,
    }
    return summary


def render_markdown(s: dict) -> str:
    lines = []
    lines.append(f"# 磐石 模型基准测试报告 — {s['model']}\n")
    lines.append(f"- 模型路径：`{s['model_path']}`")
    lines.append(f"- 精度：{s['dtype']}")
    lines.append(f"- 平均生成速度：**{s['avg_tokens_per_s']} tokens/s**")
    lines.append(f"- 总 token / 总耗时：{s['total_tokens']} / {s['total_time_s']} s")
    if s["vram_reserved_gb"] is not None:
        lines.append(f"- 显存占用（reserved）：**~{s['vram_reserved_gb']} GB**")
    lines.append(f"- 平均关键词命中率：{s['avg_keyword_hit'] * 100:.0f}%（自动评分代理，非人工判分）\n")
    lines.append("## 逐题结果\n")
    lines.append("| 编号 | 场景 | 耗时(s) | Token数 | tokens/s | 关键词命中 | 输出预览 |")
    lines.append("|------|------|--------:|--------:|---------:|-----------:|----------|")
    for r in s["results"]:
        lines.append(
            f"| {r['id']} | {r['scene']} | {r['time_s']} | {r['tokens']} | "
            f"{r['tokens_per_s']} | {r['keyword_hit']*100:.0f}% | {r['output_preview']} |"
        )
    lines.append("")
    lines.append("> 说明：关键词命中率为自动化粗评，用于 7B/14B/32B 横向对比；"
                 "正式参赛建议补充人工判分或 LLM-as-judge 评分。")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="磐石 模型能力基准测试")
    ap.add_argument("--model", default="qwen2.5-14b",
                    choices=list(MODEL_DIR_MAP.keys()) + ["<custom-path>"],
                    help="模型名（默认 qwen2.5-14b）")
    ap.add_argument("--model-path", default=None, help="自定义模型目录（覆盖 --model）")
    args = ap.parse_args()

    model_name = args.model
    if args.model_path:
        model_name = args.model_path

    summary = run_benchmark(model_name)

    out_md = os.path.join(ROOT, "docs", f"benchmark_{summary['model']}.md")
    out_json = os.path.join(ROOT, "docs", f"benchmark_{summary['model']}.json")
    os.makedirs(os.path.dirname(out_md), exist_ok=True)
    with open(out_md, "w", encoding="utf-8") as f:
        f.write(render_markdown(summary))
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print("\n" + render_markdown(summary))
    print(f"\n[+] 结果已保存：\n    {out_md}\n    {out_json}")


if __name__ == "__main__":
    main()
