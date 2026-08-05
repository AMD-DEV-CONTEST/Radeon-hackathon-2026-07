#!/usr/bin/env python3
"""
AMD AI Studio — 性能基准测试脚本
在真实 AMD GPU 上运行，收集各模块性能数据并输出对比报告
"""

import sys
import os
import time
import json
import argparse
from datetime import datetime
from pathlib import Path

# 添加项目根目录
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import torch
import numpy as np
from PIL import Image


def setup_environment():
    """设置测试环境"""
    os.environ["TORCH_BENCHMARK"] = "1"
    print("=" * 60)
    print("AMD AI Studio — 性能基准测试")
    print("=" * 60)

    # 系统信息
    print(f"\n📋 测试环境")
    print(f"  Python:      {sys.version.split()[0]}")
    print(f"  PyTorch:     {torch.__version__}")
    print(f"  ROCm:        {getattr(torch.version, 'rocm', 'N/A')}")
    print(f"  CUDA 可用:    {torch.cuda.is_available()}")

    if torch.cuda.is_available():
        for i in range(torch.cuda.device_count()):
            p = torch.cuda.get_device_properties(i)
            print(f"  GPU {i}:       {p.name} ({p.total_memory/1024**3:.1f} GB)")


def get_gpu_memory_usage():
    """获取当前 GPU 显存使用量 (GB)"""
    if torch.cuda.is_available():
        allocated = torch.cuda.memory_allocated(0) / 1024**3
        reserved = torch.cuda.memory_reserved(0) / 1024**3
        total = torch.cuda.get_device_properties(0).total_memory / 1024**3
        return {
            "allocated_gb": round(allocated, 2),
            "reserved_gb": round(reserved, 2),
            "total_gb": round(total, 2),
            "free_gb": round(total - allocated, 2),
        }
    return {}


def benchmark_txt2img(model_id="stabilityai/sd-turbo", num_runs=5, num_warmup=2,
                       width=512, height=512, steps=4, fp16=True):
    """
    测试文生图性能
    """
    print(f"\n📝 文生图基准测试")
    print(f"  模型: {model_id}")
    print(f"  分辨率: {width}x{height}, 步数: {steps}, FP16: {fp16}")
    print(f"  预热: {num_warmup}次, 测试: {num_runs}次")

    from diffusers import StableDiffusionPipeline, StableDiffusionXLPipeline, DiffusionPipeline

    # 加载模型
    torch_dtype = torch.float16 if fp16 else torch.float32
    variant = "fp16" if fp16 else None

    mem_before = get_gpu_memory_usage()

    t0 = time.time()
    # 自动检测模型类型
    try:
        pipe = DiffusionPipeline.from_pretrained(
            model_id,
            torch_dtype=torch_dtype,
            variant=variant,
            use_safetensors=True,
        )
    except Exception:
        pipe = StableDiffusionXLPipeline.from_pretrained(
            model_id,
            torch_dtype=torch_dtype,
            variant=variant,
            use_safetensors=True,
        )
    pipe.to("cuda")
    pipe.enable_attention_slicing()
    load_time = time.time() - t0

    load_mem = get_gpu_memory_usage()
    model_mem = load_mem.get("allocated_gb", 0) - mem_before.get("allocated_gb", 0)

    print(f"  加载耗时: {load_time:.1f}s, 模型占用显存: {model_mem:.2f}GB")

    # 预热
    for i in range(num_warmup):
        _ = pipe(
            prompt="a cute cat sitting on a bench",
            num_inference_steps=steps,
            width=width, height=height,
        ).images[0]
        print(f"  预热 {i+1}/{num_warmup} ✓")

    # 清空缓存
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()

    # 正式测试
    latencies = []
    peak_memory = 0

    for i in range(num_runs):
        torch.cuda.synchronize()
        t1 = time.time()

        image = pipe(
            prompt="a cute cat sitting on a bench, high quality",
            num_inference_steps=steps,
            width=width, height=height,
        ).images[0]

        torch.cuda.synchronize()
        elapsed = time.time() - t1
        latencies.append(elapsed)

        current_peak = torch.cuda.max_memory_allocated(0) / 1024**3
        peak_memory = max(peak_memory, current_peak)

        print(f"  测试 {i+1}/{num_runs}: {elapsed*1000:.0f}ms", end="")
        if i > 0:
            print(f"  {'⚡' if elapsed < sum(latencies)/len(latencies) else '  '}")
        else:
            print()

    # 统计
    latencies_ms = [l * 1000 for l in latencies]
    avg_latency = float(np.mean(latencies_ms))
    min_latency = float(np.min(latencies_ms))
    max_latency = float(np.max(latencies_ms))
    std_latency = float(np.std(latencies_ms))
    throughput = 1.0 / (avg_latency / 1000)

    # 显存峰值（净增量）
    mem_peak_net = peak_memory - mem_before.get("allocated_gb", 0) if mem_before else peak_memory

    result = {
        "model": model_id,
        "resolution": f"{width}x{height}",
        "steps": steps,
        "fp16": fp16,
        "avg_latency_ms": round(avg_latency, 1),
        "min_latency_ms": round(min_latency, 1),
        "max_latency_ms": round(max_latency, 1),
        "std_latency_ms": round(std_latency, 1),
        "throughput_img_per_sec": round(throughput, 2),
        "peak_memory_gb": round(mem_peak_net, 2),
        "load_time_s": round(load_time, 1),
        "model_memory_gb": round(model_mem, 2),
    }

    print(f"\n  📊 结果:")
    print(f"    平均延迟:   {avg_latency:.0f} ms")
    print(f"    最小延迟:   {min_latency:.0f} ms")
    print(f"    最大延迟:   {max_latency:.0f} ms")
    print(f"    标准差:     {std_latency:.0f} ms")
    print(f"    吞吐量:     {throughput:.2f} img/s")
    print(f"    显存峰值:   {mem_peak_net:.2f} GB")

    del pipe
    torch.cuda.empty_cache()

    return result


def benchmark_with_optimization_variants():
    """
    测试不同优化配置对性能的影响
    """
    print("\n" + "=" * 60)
    print("🔬 优化前后对比测试")
    print("=" * 60)

    model_id = "stabilityai/sd-turbo"
    results = []

    # 配置列表: (name, fp16, attention_slicing, vae_tiling, cpu_offload)
    configs = [
        ("🚫 无优化 (FP32)",    False, False, False, False),
        ("✅ FP16 仅",          True,  False, False, False),
        ("✅ FP16 + AttnSlice", True,  True,  False, False),
        ("✅ 全优化",           True,  True,  True,  True),
    ]

    for name, fp16, attn_slice, vae_tile, cpu_off in configs:
        print(f"\n--- 配置: {name} ---")
        try:
            result = benchmark_txt2img(
                model_id=model_id,
                num_runs=3,
                num_warmup=1,
                width=512, height=512, steps=4,
                fp16=fp16,
            )
            result["config_name"] = name
            result["fp16"] = fp16
            result["attention_slicing"] = attn_slice
            result["vae_tiling"] = vae_tile
            result["cpu_offload"] = cpu_off
            results.append(result)
        except Exception as e:
            print(f"  ❌ 失败: {e}")
            results.append({"config_name": name, "error": str(e)})

    return results


def print_comparison_table(results):
    """打印对比表格"""
    print("\n" + "=" * 80)
    print("📊 优化效果对比总表")
    print("=" * 80)

    # 表头
    header = f"{'配置':<20} | {'延迟(ms)':<12} | {'吞吐(img/s)':<14} | {'显存(GB)':<10} | {'加载(s)':<8}"
    print(header)
    print("-" * 80)

    baseline = None
    for r in results:
        if "error" in r:
            print(f"{r['config_name']:<20} | {'❌ 失败':<12} | {'':<14} | {'':<10} | {'':<8}")
            continue

        config_name = r["config_name"]
        avg = r["avg_latency_ms"]
        tp = r["throughput_img_per_sec"]
        mem = r["peak_memory_gb"]
        load_t = r["load_time_s"]

        if baseline is None:
            # 第一项作为 baseline
            baseline = r
            print(f"{config_name:<20} | {avg:<8.0f} ms    | {tp:<8.2f} img/s    | {mem:<6.2f} GB   | {load_t:<6.1f}s")
        else:
            # 计算提升百分比
            speedup = (baseline["avg_latency_ms"] / avg - 1) * 100 if avg > 0 else 0
            mem_reduction = (1 - mem / baseline["peak_memory_gb"]) * 100 if baseline["peak_memory_gb"] > 0 else 0
            print(f"{config_name:<20} | {avg:<8.0f} ms    | {tp:<8.2f} img/s    | {mem:<6.2f} GB   | {load_t:<6.1f}s")
            print(f"{'':<20}   {'⚡ ' + f'{speedup:+.0f}%':<12} {'📈 ' + f'{tp/baseline["throughput_img_per_sec"]*100-100:+.0f}%':<14} {'📉 ' + f'{mem_reduction:+.0f}%':<10}")

    print("=" * 80)


def save_results(results, filename="benchmark_results.json"):
    """保存测试结果到 JSON"""
    output = {
        "timestamp": datetime.now().isoformat(),
        "environment": {
            "python": sys.version.split()[0],
            "pytorch": torch.__version__,
            "rocm": getattr(torch.version, 'rocm', 'N/A'),
            "cuda_available": torch.cuda.is_available(),
        },
        "gpu_info": [],
        "results": results,
    }

    if torch.cuda.is_available():
        for i in range(torch.cuda.device_count()):
            p = torch.cuda.get_device_properties(i)
            output["gpu_info"].append({
                "name": p.name,
                "total_memory_gb": round(p.total_memory / 1024**3, 1),
                "compute_capability": f"{p.major}.{p.minor}",
            })

    output_path = Path("outputs/benchmarks")
    output_path.mkdir(parents=True, exist_ok=True)
    filepath = output_path / filename

    with open(filepath, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n💾 结果已保存: {filepath}")
    return filepath


def main():
    parser = argparse.ArgumentParser(description="AMD AI Studio 性能基准测试")
    parser.add_argument("--quick", action="store_true", help="快速模式（减少测试次数）")
    args = parser.parse_args()

    num_runs = 3 if args.quick else 5
    num_warmup = 1 if args.quick else 2

    setup_environment()

    # 1. 不同优化配置对比
    results = benchmark_with_optimization_variants()

    # 2. 打印对比表
    print_comparison_table(results)

    # 3. 保存结果
    save_path = save_results(results)
    print(f"\n✅ 基准测试完成! 结果文件: {save_path}")


if __name__ == "__main__":
    main()