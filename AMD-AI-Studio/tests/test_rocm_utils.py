"""
测试: ROCm 工具模块
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from modules.rocm_utils import (
    is_rocm_available,
    get_rocm_version,
    get_gpu_info,
    get_gpu_status,
    get_optimal_device,
    optimize_memory,
    clear_gpu_cache,
    format_gpu_info,
)


class TestRocmDetection:
    def test_is_rocm_available(self):
        """测试 ROCm 是否可用"""
        result = is_rocm_available()
        # 在有 AMD GPU 的环境应返回 True
        assert isinstance(result, bool)

    def test_get_rocm_version(self):
        """测试获取 ROCm 版本"""
        version = get_rocm_version()
        # 版本号应为字符串或 None
        assert version is None or isinstance(version, str)
        if version:
            assert len(version) > 0

    def test_get_gpu_info(self):
        """测试获取 GPU 信息"""
        gpus = get_gpu_info()
        assert isinstance(gpus, list)
        if gpus:
            gpu = gpus[0]
            assert "id" in gpu
            assert "name" in gpu
            assert "vram" in gpu

    def test_get_gpu_status(self):
        """测试获取 GPU 实时状态"""
        status = get_gpu_status()
        assert isinstance(status, dict)

    def test_get_optimal_device(self):
        """测试最优设备检测"""
        device = get_optimal_device()
        assert device in ("cuda", "cpu")
        # 在有 AMD GPU 的环境应返回 "cuda"
        if is_rocm_available():
            assert device == "cuda"


class TestGpuOptimization:
    def test_optimize_memory(self):
        """测试内存优化（不报错即可）"""
        try:
            optimize_memory()
        except Exception as e:
            pytest.fail(f"optimize_memory() 抛出异常: {e}")

    def test_clear_gpu_cache(self):
        """测试清理 GPU 缓存（不报错即可）"""
        try:
            clear_gpu_cache()
        except Exception as e:
            pytest.fail(f"clear_gpu_cache() 抛出异常: {e}")

    def test_format_gpu_info(self):
        """测试格式化 GPU 信息输出"""
        output = format_gpu_info()
        assert isinstance(output, str)
        assert len(output) > 0
        # 应包含关键标识
        assert "AMD GPU" in output or "GPU" in output


class TestDeviceMap:
    def test_get_device_map(self):
        """测试设备映射"""
        from modules.rocm_utils import get_device_map

        device_map = get_device_map()
        assert isinstance(device_map, dict)
        if is_rocm_available():
            assert device_map.get("device_map") == "auto"
            assert device_map.get("torch_dtype") == "float16"