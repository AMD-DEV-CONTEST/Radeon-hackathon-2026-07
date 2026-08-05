"""
测试: 模型优化器模块
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from modules.model_optimizer import (
    optimize_memory_for_gpu,
    get_gpu_memory_info,
    InferenceOptimizer,
    BenchmarkResult,
    run_benchmark,
    format_benchmark,
    suggest_optimizations,
    print_optimization_suggestions,
    compile_pipeline,
    quantize_model_to_fp16,
    quantize_model_to_int8,
)


class TestMemoryOptimization:
    def test_optimize_memory_for_gpu(self):
        """测试 GPU 显存优化"""
        result = optimize_memory_for_gpu()
        assert isinstance(result, bool)

    def test_get_gpu_memory_info(self):
        """测试获取 GPU 显存信息"""
        info = get_gpu_memory_info()
        assert isinstance(info, dict)
        if info:
            key = list(info.keys())[0]
            assert "total_gb" in info[key]
            assert "free_gb" in info[key]
            assert "usage_pct" in info[key]
            assert info[key]["total_gb"] > 0


class TestInferenceOptimizer:
    def test_default_optimizer(self):
        """测试默认优化器配置"""
        opt = InferenceOptimizer()
        assert opt.enable_attention_slicing is True
        assert opt.enable_vae_tiling is True
        assert opt.enable_sequential_cpu_offload is True
        assert opt.enable_tf32 is True
        assert opt.compile_unet is False

    def test_custom_optimizer(self):
        """测试自定义优化器配置"""
        opt = InferenceOptimizer(
            enable_attention_slicing=False,
            enable_vae_tiling=False,
            compile_unet=True,
        )
        assert opt.enable_attention_slicing is False
        assert opt.enable_vae_tiling is False
        assert opt.compile_unet is True


class TestBenchmarkResult:
    def test_benchmark_result_fields(self):
        """测试基准测试结果数据结构"""
        result = BenchmarkResult(
            model_name="SDXL",
            device="cuda",
            batch_size=1,
            avg_latency_ms=3500.0,
            min_latency_ms=3200.0,
            max_latency_ms=3800.0,
            throughput=0.28,
            memory_peak_gb=12.0,
            resolution="1024x1024",
        )
        assert result.model_name == "SDXL"
        assert result.avg_latency_ms == 3500.0
        assert result.min_latency_ms == 3200.0
        assert result.max_latency_ms == 3800.0
        assert result.throughput == 0.28
        assert result.memory_peak_gb == 12.0
        assert result.resolution == "1024x1024"

    def test_benchmark_result_device(self):
        """测试不同设备类型"""
        cpu_result = BenchmarkResult(
            model_name="SDXL", device="cpu", batch_size=1,
            avg_latency_ms=30000.0, min_latency_ms=28000.0,
            max_latency_ms=32000.0, throughput=0.03,
            memory_peak_gb=8.0, resolution="512x512",
        )
        cuda_result = BenchmarkResult(
            model_name="SDXL", device="cuda", batch_size=1,
            avg_latency_ms=3500.0, min_latency_ms=3200.0,
            max_latency_ms=3800.0, throughput=0.28,
            memory_peak_gb=12.0, resolution="1024x1024",
        )
        assert cpu_result.device == "cpu"
        assert cuda_result.device == "cuda"
        # GPU 应该比 CPU 快
        assert cuda_result.avg_latency_ms < cpu_result.avg_latency_ms


class TestFormatBenchmark:
    def test_format_benchmark_output(self):
        """测试格式化输出"""
        result = BenchmarkResult(
            model_name="SDXL-Test",
            device="cuda",
            batch_size=1,
            avg_latency_ms=3500.0,
            min_latency_ms=3200.0,
            max_latency_ms=3800.0,
            throughput=0.28,
            memory_peak_gb=12.0,
            resolution="1024x1024",
        )
        output = format_benchmark(result)
        assert isinstance(output, str)
        assert "SDXL" in output
        assert "cuda" in output
        assert "3500" in output
        assert "0.28" in output


class TestOptimizationSuggestions:
    def test_suggest_small_vram(self):
        """测试小显存（8GB）优化建议"""
        suggestions = suggest_optimizations(8.0)
        assert suggestions["enable_attention_slicing"] is True
        assert suggestions["enable_vae_tiling"] is True  # 8 < 16
        assert suggestions["enable_sequential_cpu_offload"] is True  # 8 < 10
        assert suggestions["use_fp16"] is True
        assert suggestions["max_resolution"] == "768x768"  # 8 >= 8

    def test_suggest_medium_vram(self):
        """测试中等显存（16GB）优化建议"""
        suggestions = suggest_optimizations(16.0)
        assert suggestions["enable_attention_slicing"] is True
        # 16 >= 16, 所以 vae_tiling = False
        assert suggestions["enable_vae_tiling"] is False
        # 16 >= 10, 所以 sequential_cpu_offload = False
        assert suggestions["enable_sequential_cpu_offload"] is False
        assert suggestions["max_resolution"] == "1024x1024"

    def test_suggest_large_vram(self):
        """测试大显存（24GB+）优化建议"""
        suggestions = suggest_optimizations(24.0)
        assert suggestions["max_resolution"] == "1536x1536"
        assert suggestions["compile_unet"] is True
        # 24GB 不需要 VAE Tiling
        assert suggestions["enable_vae_tiling"] is False

    def test_suggest_very_large_vram(self):
        """测试超大显存（48GB）优化建议"""
        suggestions = suggest_optimizations(48.0)
        assert suggestions["max_resolution"] == "1536x1536"
        assert suggestions["compile_unet"] is True
        assert suggestions["enable_vae_tiling"] is False
        assert suggestions["enable_sequential_cpu_offload"] is False

    def test_print_suggestions(self):
        """测试打印优化建议（不报错）"""
        try:
            print_optimization_suggestions()
        except Exception as e:
            pytest.fail(f"print_optimization_suggestions() 抛出异常: {e}")


class TestQuantization:
    def test_quantize_to_fp16(self):
        """测试 FP16 量化"""
        import torch
        model = torch.nn.Linear(10, 10)
        model.float()
        quantize_model_to_fp16(model)
        assert model.weight.dtype == torch.float16

    def test_quantize_to_int8_fallback(self):
        """测试 INT8 量化（无 bitsandbytes 时不应崩溃）"""
        import torch
        model = torch.nn.Linear(10, 10)
        try:
            quantize_model_to_int8(model)
        except Exception as e:
            pytest.fail(f"quantize_model_to_int8() 抛出异常: {e}")


class TestCompilePipeline:
    def test_compile_pipeline_no_unet(self):
        """测试编译无 UNet 的 pipeline"""
        class MockPipe:
            pass

        result = compile_pipeline(MockPipe())
        assert result is False

    def test_compile_pipeline_with_unet(self):
        """测试编译有 UNet 的 pipeline"""
        import torch

        class MockUnet(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.layers = torch.nn.Linear(10, 10)

        class MockPipe:
            def __init__(self):
                self.unet = MockUnet()

        # 仅测试不报错，不要求实际编译成功
        try:
            result = compile_pipeline(MockPipe(), mode="reduce-overhead")
            # 编译可能因环境失败，但不应该抛出异常
            assert isinstance(result, bool)
        except Exception as e:
            pytest.fail(f"compile_pipeline() 抛出异常: {e}")