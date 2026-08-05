#!/usr/bin/env python3
"""
AMD AI Studio — Krea-2-Turbo-zishi 基准测试脚本

按 ModelScope / Hugging Face 官方推荐方式调优并测试：
  - 管道: Krea2Pipeline (Krea-2-Turbo-zishi 紫狮风格 LoRA)
  - 数据类型: bfloat16
  - 推理步数: 8 (Turbo 甜点值)
  - 引导尺度: 0.0 (Turbo 推荐设为 0)
  - 分辨率: 1024x1024
  - 优化: enable_attention_slicing() + enable_memory_efficient_attention()

测试流程:
  1. 预热 2 轮（让 CUDA kernel / cuDNN 完成自动调优）
  2. 正式测试 5 轮，每轮记录延迟 / 吞吐 / 显存峰值
  3. 生成 6 张紫狮风格样图保存到 outputs/benchmarks/assets/
  4. 输出 JSON 到 outputs/benchmarks/krea_zishi_benchmark.json

用法:
  python scripts/benchmark_krea_zishi.py
  python scripts/benchmark_krea_zishi.py --steps 8 --rounds 5 --warmup 2
"""

import os
import sys
import time
import json
import argparse
from datetime import datetime
from pathlib import Path

# 添加项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

import torch
from PIL import Image

# ============================================================
# 配置
# ============================================================
OUTPUT_DIR = Path("outputs/benchmarks")
ASSETS_DIR = OUTPUT_DIR / "assets"
JSON_PATH = OUTPUT_DIR / "krea_zishi_benchmark.json"

# 紫狮风格提示词（6 张样图）
SAMPLE_PROMPTS = [
    "a majestic lion in traditional Chinese ink wash painting style, golden mane flowing, mystical purple aura, ancient temple background",
    "紫狮神兽，中国传统水墨画风格，鬃毛飘逸，紫色神光环绕，古刹背景，4K",
    "a fierce lion warrior in Chinese mythology, purple energy mane, ceremonial armor, dramatic lighting, masterpiece",
    "紫狮守护神，宫殿石阶，祥云缭绕，紫色雷电鬃毛，写实摄影质感，8K",
    "a regal lion king seated on a jade throne, purple imperial aura, Chinese dragon motifs, cinematic composition",
    "紫狮踏云，东方神话，紫金鬃毛，云雾翻腾，国风水墨，超高清",
]

# 默认参数（官方推荐）
DEFAULT_STEPS = 8
DEFAULT_GUIDANCE = 0.0
DEFAULT_WIDTH = 1024
DEFAULT_HEIGHT = 1024
DEFAULT_WARMUP = 2
DEFAULT_ROUNDS = 5


def parse_args():
    p = argparse.ArgumentParser(description="Krea-2-Turbo-zishi 基准测试")
    p.add_argument("--steps", type=int, default=DEFAULT_STEPS, help="推理步数 (默认 8)")
    p.add_argument("--guidance", type=float, default=DEFAULT_GUIDANCE, help="引导尺度 (默认 0.0)")
    p.add_argument("--width", type=int, default=DEFAULT_WIDTH, help="输出宽度")
    p.add_argument("--height", type=int, default=DEFAULT_HEIGHT, help="输出高度")
    p.add_argument("--warmup", type=int, default=DEFAULT_WARMUP, help="预热轮数")
    p.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS, help="正式测试轮数")
    return p.parse_args()


def get_system_info():
    """收集系统信息"""
    info = {
        "timestamp": datetime.now().isoformat(),
        "python": sys.version.split()[0],
        "torch": torch.__version__,
        "cuda_available": torch.cuda.is_available(),
    }
    if torch.cuda.is_available():
        info["gpu"] = torch.cuda.get_device_name(0)
        info["gpu_count"] = torch.cuda.device_count()
        info["vram_total_gb"] = round(torch.cuda.get_device_properties(0).total_memory / 1024**3, 1)
    if hasattr(torch.version, "hip") and torch.version.hip:
        info["rocm"] = torch.version.hip
    try:
        import diffusers
        info["diffusers"] = diffusers.__version__
    except Exception:
        info["diffusers"] = "unknown"
    try:
        import transformers
        info["transformers"] = transformers.__version__
    except Exception:
        info["transformers"] = "unknown"
    return info


def load_pipeline():
    """按官方推荐方式加载 Krea-2-Turbo-zishi 管道

    优先尝试 Krea2Pipeline（diffusers >= 0.34），
    回退到 DiffusionPipeline 自动检测（与 model_loader.py 一致）。
    """
    print("\n[1/4] 加载 Krea-2-Turbo-zishi 管道...")

    # 优先 Krea2Pipeline
    pipe = None
    try:
        from diffusers import Krea2Pipeline
        print("  使用 Krea2Pipeline (diffusers 原生)")
        pipe = Krea2Pipeline.from_pretrained(
            "krea/Krea-2-Turbo",
            torch_dtype=torch.bfloat16,
        ).to("cuda")
    except Exception as e:
        print(f"  Krea2Pipeline 不可用 ({type(e).__name__}: {str(e)[:80]})")
        print("  回退到 DiffusionPipeline 自动检测...")
        from diffusers import DiffusionPipeline
        pipe = DiffusionPipeline.from_pretrained(
            "krea/Krea-2-Turbo",
            torch_dtype=torch.bfloat16,
            use_safetensors=True,
        ).to("cuda")

    # 官方推荐优化
    try:
        pipe.enable_attention_slicing()
        print("  ✅ enable_attention_slicing()")
    except Exception:
        print("  ⚠️ enable_attention_slicing() 不支持")
    try:
        pipe.enable_memory_efficient_attention()
        print("  ✅ enable_memory_efficient_attention()")
    except Exception:
        print("  ⚠️ enable_memory_efficient_attention() 不支持")

    return pipe


def generate_one(pipe, prompt, args, seed=42):
    """生成单张图像，返回 (image, latency_s, peak_vram_gb)"""
    torch.cuda.reset_peak_memory_stats()
    generator = torch.Generator(device="cuda").manual_seed(seed)

    t0 = time.time()
    with torch.inference_mode():
        result = pipe(
            prompt=prompt,
            num_inference_steps=args.steps,
            guidance_scale=args.guidance,
            width=args.width,
            height=args.height,
            generator=generator,
        )
    latency = time.time() - t0
    image = result.images[0]
    peak_vram = torch.cuda.max_memory_allocated(0) / 1024**3

    return image, latency, peak_vram


def warmup(pipe, args):
    """预热：让 CUDA kernel / cuDNN 完成自动调优"""
    print(f"\n[2/4] 预热 {args.warmup} 轮...")
    warmup_prompt = "a simple test image, purple lion style"
    for i in range(args.warmup):
        t0 = time.time()
        _ = generate_one(pipe, warmup_prompt, args, seed=100 + i)
        print(f"  预热 {i + 1}/{args.warmup}: {time.time() - t0:.2f}s")


def benchmark(pipe, args):
    """正式基准测试"""
    print(f"\n[3/4] 正式基准测试 {args.rounds} 轮 (steps={args.steps}, guidance={args.guidance})...")
    latencies = []
    throughputs = []
    peak_vrams = []

    bench_prompt = "a majestic purple lion in Chinese ink wash painting, 4K, masterpiece"
    for i in range(args.rounds):
        image, latency, peak_vram = generate_one(pipe, bench_prompt, args, seed=42 + i)
        throughput = 1.0 / latency
        latencies.append(latency)
        throughputs.append(throughput)
        peak_vrams.append(peak_vram)
        print(f"  轮次 {i + 1}/{args.rounds}: {latency:.3f}s | {throughput:.2f} img/s | 峰值显存 {peak_vram:.2f}GB")

    avg_latency = sum(latencies) / len(latencies)
    avg_throughput = sum(throughputs) / len(throughputs)
    avg_peak_vram = sum(peak_vrams) / len(peak_vrams)
    min_latency = min(latencies)
    max_latency = max(latencies)

    print(f"\n  📊 平均延迟: {avg_latency:.3f}s")
    print(f"  📊 平均吞吐: {avg_throughput:.2f} img/s")
    print(f"  📊 平均峰值显存: {avg_peak_vram:.2f}GB")
    print(f"  📊 延迟范围: {min_latency:.3f}s ~ {max_latency:.3f}s")

    return {
        "latency_avg_s": round(avg_latency, 3),
        "latency_min_s": round(min_latency, 3),
        "latency_max_s": round(max_latency, 3),
        "throughput_avg_img_per_s": round(avg_throughput, 2),
        "peak_vram_avg_gb": round(avg_peak_vram, 2),
        "latencies": [round(l, 3) for l in latencies],
        "peak_vrams": [round(v, 2) for v in peak_vrams],
    }


def generate_samples(pipe, args):
    """生成 6 张紫狮风格样图保存到 assets/"""
    print(f"\n[4/4] 生成 {len(SAMPLE_PROMPTS)} 张紫狮风格样图...")

    # 确保输出目录存在
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    saved_paths = []
    for i, prompt in enumerate(SAMPLE_PROMPTS):
        image, latency, _ = generate_one(pipe, prompt, args, seed=200 + i)
        fname = f"krea_zishi_sample_{i + 1}.png"
        fpath = ASSETS_DIR / fname
        image.save(str(fpath))
        saved_paths.append(str(fpath))
        print(f"  样图 {i + 1}/{len(SAMPLE_PROMPTS)}: {fname} ({latency:.2f}s)")

    return saved_paths


def main():
    args = parse_args()

    print("=" * 60)
    print("AMD AI Studio — Krea-2-Turbo-zishi 基准测试")
    print("=" * 60)

    # 收集系统信息
    sys_info = get_system_info()
    print(f"\n环境: Python {sys_info['python']} | PyTorch {sys_info['torch']}")
    if torch.cuda.is_available():
        print(f"GPU: {sys_info['gpu']} | 显存: {sys_info['vram_total_gb']}GB")
    if "rocm" in sys_info:
        print(f"ROCm: {sys_info['rocm']}")

    # 加载管道
    pipe = load_pipeline()

    # 预热
    warmup(pipe, args)

    # 正式基准测试
    bench_result = benchmark(pipe, args)

    # 生成样图
    sample_paths = generate_samples(pipe, args)

    # 汇总结果
    output = {
        "model": "Krea-2-Turbo-zishi",
        "model_source": "krea/Krea-2-Turbo + jonathanfu/Krea-2-Turbo-zishi LoRA",
        "config": {
            "num_inference_steps": args.steps,
            "guidance_scale": args.guidance,
            "width": args.width,
            "height": args.height,
            "dtype": "bfloat16",
            "optimizations": ["enable_attention_slicing", "enable_memory_efficient_attention"],
        },
        "system": sys_info,
        "result": bench_result,
        "samples": [
            {"index": i + 1, "prompt": SAMPLE_PROMPTS[i], "path": sample_paths[i]}
            for i in range(len(sample_paths))
        ],
        "notes": [
            "按官方推荐: num_inference_steps=8, guidance_scale=0.0, bfloat16",
            "预热 2 轮后正式测试 5 轮取平均",
            "优化: enable_attention_slicing + enable_memory_efficient_attention",
        ],
    }

    # 写入 JSON
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    JSON_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ JSON 结果已保存: {JSON_PATH}")
    print(f"✅ 样图已保存: {ASSETS_DIR}/krea_zishi_sample_*.png")

    print("\n" + "=" * 60)
    print("基准测试完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
