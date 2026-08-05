"""
模型优化工具 — 量化、编译、显存优化、推理加速
"""

import logging
import time
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass, field

import torch
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)


# ============================================================
# 显存优化
# ============================================================
def optimize_memory_for_gpu():
    """针对 AMD GPU 的显存优化"""
    try:
        # TF32 加速
        torch.backends.cuda.matmul.allow_tf32 = True
        if hasattr(torch.backends, "cudnn"):
            torch.backends.cudnn.allow_tf32 = True
            torch.backends.cudnn.benchmark = True

        # 设置 PyTorch 内存分配策略
        if hasattr(torch.cuda, "set_per_process_memory_fraction"):
            # 限制 PyTorch 最多使用 90% 显存
            torch.cuda.set_per_process_memory_fraction(0.9)

        logger.info("显存优化已应用")
        return True
    except Exception as e:
        logger.warning(f"显存优化失败: {e}")
        return False


def get_gpu_memory_info() -> Dict[str, float]:
    """获取 GPU 显存信息（GB）"""
    info = {}
    try:
        if torch.cuda.is_available():
            for i in range(torch.cuda.device_count()):
                total = torch.cuda.get_device_properties(i).total_memory / 1024**3
                allocated = torch.cuda.memory_allocated(i) / 1024**3
                reserved = torch.cuda.memory_reserved(i) / 1024**3
                free = total - allocated
                info[f"gpu_{i}"] = {
                    "total_gb": round(total, 2),
                    "allocated_gb": round(allocated, 2),
                    "reserved_gb": round(reserved, 2),
                    "free_gb": round(free, 2),
                    "usage_pct": round(allocated / total * 100, 1),
                }
    except Exception:
        pass
    return info


# ============================================================
# 推理优化
# ============================================================
@dataclass
class InferenceOptimizer:
    """推理优化器 — 管理和应用各种优化策略"""

    enable_attention_slicing: bool = True
    enable_vae_tiling: bool = True
    enable_vae_slicing: bool = True
    enable_model_cpu_offload: bool = False
    enable_sequential_cpu_offload: bool = True
    enable_tf32: bool = True
    compile_unet: bool = False  # torch.compile 实验性
    use_quantized_vae: bool = False

    def apply_to_pipeline(self, pipe) -> None:
        """将优化应用到 Diffusers pipeline"""
        if self.enable_attention_slicing:
            pipe.enable_attention_slicing()
            logger.info("✅ Attention Slicing 已启用")

        if self.enable_vae_tiling:
            pipe.enable_vae_tiling()
            logger.info("✅ VAE Tiling 已启用（支持大分辨率）")

        if self.enable_vae_slicing:
            pipe.enable_vae_slicing()
            logger.info("✅ VAE Slicing 已启用（降低显存峰值）")

        if self.enable_sequential_cpu_offload:
            pipe.enable_sequential_cpu_offload()
            logger.info("✅ Sequential CPU Offload 已启用")
        elif self.enable_model_cpu_offload:
            pipe.enable_model_cpu_offload()
            logger.info("✅ Model CPU Offload 已启用")

        if self.enable_tf32:
            optimize_memory_for_gpu()

        if self.compile_unet and hasattr(pipe, "unet"):
            try:
                pipe.unet = torch.compile(
                    pipe.unet, mode="reduce-overhead", fullgraph=True
                )
                logger.info("✅ UNet torch.compile 已启用")
            except Exception as e:
                logger.warning(f"UNet 编译失败: {e}")

        if self.use_quantized_vae and hasattr(pipe, "vae"):
            logger.info("ℹ️ 量化 VAE 需要额外安装，跳过")


# ============================================================
# 性能基准测试
# ============================================================
@dataclass
class BenchmarkResult:
    """基准测试结果"""
    model_name: str
    device: str
    batch_size: int
    avg_latency_ms: float
    min_latency_ms: float
    max_latency_ms: float
    throughput: float  # images/sec
    memory_peak_gb: float
    resolution: str


def run_benchmark(
    pipeline_fn: Callable,
    prompt: str = "a cat sitting on a bench",
    num_runs: int = 5,
    num_warmup: int = 2,
    width: int = 1024,
    height: int = 1024,
    **kwargs,
) -> BenchmarkResult:
    """
    对 pipeline 进行性能基准测试
    返回延迟、吞吐量、显存等信息
    """
    latencies = []

    # Warmup
    logger.info(f"预热 {num_warmup} 次...")
    for _ in range(num_warmup):
        pipeline_fn(prompt=prompt, width=width, height=height, **kwargs)

    # 记录初始显存
    mem_before = 0
    try:
        if torch.cuda.is_available():
            mem_before = torch.cuda.memory_allocated()
    except Exception:
        pass

    # 正式测试
    logger.info(f"基准测试 {num_runs} 次...")
    for i in range(num_runs):
        start = time.time()
        pipeline_fn(prompt=prompt, width=width, height=height, **kwargs)
        end = time.time()
        latency_ms = (end - start) * 1000
        latencies.append(latency_ms)
        logger.info(f"  第 {i+1} 次: {latency_ms:.1f}ms")

    # 记录峰值显存
    mem_peak_gb = 0
    try:
        if torch.cuda.is_available():
            mem_peak = torch.cuda.max_memory_allocated()
            mem_peak_gb = (mem_peak - mem_before) / 1024**3
    except Exception:
        pass

    avg_latency = float(np.mean(latencies))
    min_latency = float(np.min(latencies))
    max_latency = float(np.max(latencies))
    throughput = 1000.0 / avg_latency if avg_latency > 0 else 0

    return BenchmarkResult(
        model_name=kwargs.get("model_name", "unknown"),
        device="cuda" if torch.cuda.is_available() else "cpu",
        batch_size=1,
        avg_latency_ms=round(avg_latency, 1),
        min_latency_ms=round(min_latency, 1),
        max_latency_ms=round(max_latency, 1),
        throughput=round(throughput, 2),
        memory_peak_gb=round(mem_peak_gb, 2),
        resolution=f"{width}x{height}",
    )


def format_benchmark(result: BenchmarkResult) -> str:
    """格式化基准测试结果"""
    lines = [
        "=" * 50,
        f"📊 基准测试结果: {result.model_name}",
        "=" * 50,
        f"  设备:        {result.device}",
        f"  分辨率:      {result.resolution}",
        f"  平均延迟:    {result.avg_latency_ms} ms",
        f"  最小延迟:    {result.min_latency_ms} ms",
        f"  最大延迟:    {result.max_latency_ms} ms",
        f"  吞吐量:      {result.throughput} images/sec",
        f"  显存峰值:    {result.memory_peak_gb} GB",
        "=" * 50,
    ]
    return "\n".join(lines)


# ============================================================
# 模型量化工具
# ============================================================
def quantize_model_to_fp16(model) -> None:
    """将模型转换为 FP16"""
    model.half()
    logger.info("模型已转换为 FP16")


def quantize_model_to_int8(model) -> None:
    """将模型转换为 INT8（需要 bitsandbytes）"""
    try:
        import bitsandbytes as bnb
        # 仅对线性层量化
        for name, module in model.named_modules():
            if isinstance(module, torch.nn.Linear):
                module.weight.data = bnb.nn.Int8Params(
                    module.weight.data, requires_grad=False
                )
        logger.info("模型已转换为 INT8 (bitsandbytes)")
    except ImportError:
        logger.warning("bitsandbytes 未安装，无法 INT8 量化")


# ============================================================
# 模型编译加速
# ============================================================
def compile_pipeline(pipe, mode: str = "reduce-overhead") -> bool:
    """使用 torch.compile 编译 pipeline 的 UNet 部分"""
    if not hasattr(pipe, "unet"):
        logger.warning("pipeline 没有 UNet，无法编译")
        return False

    try:
        pipe.unet = torch.compile(
            pipe.unet,
            mode=mode,
            fullgraph=True,
            dynamic=False,
        )
        logger.info(f"UNet 已编译 (mode={mode})")
        return True
    except Exception as e:
        logger.warning(f"编译失败: {e}")
        return False


# ============================================================
# 自动优化建议
# ============================================================
def suggest_optimizations(vram_gb: float) -> Dict[str, Any]:
    """根据显存大小自动推荐优化参数"""
    suggestions = {
        "enable_attention_slicing": True,
        "enable_vae_tiling": vram_gb < 16,
        "enable_vae_slicing": vram_gb < 12,
        "enable_sequential_cpu_offload": vram_gb < 10,
        "compile_unet": False,
        "use_fp16": True,
        "max_resolution": "1024x1024" if vram_gb >= 16 else "768x768" if vram_gb >= 8 else "512x512",
    }

    if vram_gb >= 24:
        suggestions["max_resolution"] = "1536x1536"
        suggestions["compile_unet"] = True

    return suggestions


def print_optimization_suggestions():
    """打印优化建议"""
    info = get_gpu_memory_info()
    for gpu_id, mem in info.items():
        print(f"\n🔧 GPU {gpu_id} 优化建议 ({mem['total_gb']} GB 显存):")
        suggestions = suggest_optimizations(mem["total_gb"])
        for k, v in suggestions.items():
            print(f"  {k}: {v}")