"""
测试: 智能显存管理器
"""

import pytest
import sys
import os
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from modules.smart_manager import (
    get_available_vram_gb,
    get_total_vram_gb,
    get_compatible_models,
    SmartModelManager,
)


class TestVramFunctions:
    def test_get_available_vram_gb(self):
        """测试获取可用显存"""
        vram = get_available_vram_gb()
        assert isinstance(vram, (int, float))
        assert vram >= 0

    def test_get_total_vram_gb(self):
        """测试获取总显存"""
        vram = get_total_vram_gb()
        assert isinstance(vram, (int, float))
        assert vram >= 0

    def test_get_compatible_models(self):
        """测试获取兼容模型列表"""
        models = get_compatible_models()
        assert isinstance(models, list)
        # 至少应返回兼容的模型
        assert len(models) > 0


class TestSmartModelManager:
    def setup_method(self):
        self.mock_loader = MagicMock()
        self.mock_loader._loaded_pipelines = {}
        self.manager = SmartModelManager(self.mock_loader)

    def test_initial_state(self):
        """测试初始状态"""
        assert self.manager._running is False
        assert self.manager._monitor_thread is None
        assert self.manager._vram_threshold_low == 0.15
        assert self.manager._vram_threshold_high == 0.30

    def test_start_monitoring(self):
        """测试启动监控"""
        self.manager.start_monitoring()
        assert self.manager._running is True
        assert self.manager._monitor_thread is not None
        assert self.manager._monitor_thread.is_alive() is True
        # 清理
        self.manager.stop_monitoring()

    def test_stop_monitoring(self):
        """测试停止监控"""
        self.manager.start_monitoring()
        self.manager.stop_monitoring()
        assert self.manager._running is False

    def test_double_start(self):
        """测试重复启动（不创建新线程）"""
        self.manager.start_monitoring()
        thread_id = id(self.manager._monitor_thread)
        self.manager.start_monitoring()
        assert id(self.manager._monitor_thread) == thread_id
        self.manager.stop_monitoring()

    @patch("modules.smart_manager.get_available_vram_gb", return_value=4.0)
    @patch("modules.smart_manager.get_total_vram_gb", return_value=8.0)
    def test_should_load_model_sufficient_vram(self, mock_total, mock_available):
        """测试显存充足时允许加载模型"""
        from modules.model_loader import DEFAULT_MODEL_REGISTRY
        # 找一个小模型
        small_model = "sdxl-vae-fp16"  # 0.3 GB
        can_load, msg = self.manager.should_load_model(small_model)
        # 0.3*1.2 + 2 = 2.36 GB, 可用 4 GB, 应该可以
        assert can_load is True
        assert "可用显存" in msg

    def test_should_load_model_unknown(self):
        """测试未知模型"""
        can_load, msg = self.manager.should_load_model("unknown-model")
        assert can_load is False
        assert "未知模型" in msg

    def test_emergency_unload(self):
        """测试紧急卸载"""
        # 模拟已加载的 pipeline
        class MockPipeline:
            def to(self, device):
                pass

        self.mock_loader._loaded_pipelines = {
            "model1": MockPipeline(),
            "model2": MockPipeline(),
        }
        self.mock_loader.unload_pipeline.return_value = 4.0

        # 调用紧急卸载
        self.manager._emergency_unload(6.0)
        assert self.mock_loader.unload_pipeline.called