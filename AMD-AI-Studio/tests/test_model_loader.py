"""
测试: 模型加载管理器
"""

import pytest
import sys
import os
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from modules.model_loader import (
    ModelLoader,
    DEFAULT_MODEL_REGISTRY,
    STATUS_NOT_DOWNLOADED,
    STATUS_DOWNLOADING,
    STATUS_DOWNLOADED,
    STATUS_ERROR,
    STATUS_LOADING,
    STATUS_LOADED,
)


class TestConstants:
    def test_status_constants(self):
        """测试状态常量"""
        assert STATUS_NOT_DOWNLOADED == "not_downloaded"
        assert STATUS_DOWNLOADING == "downloading"
        assert STATUS_DOWNLOADED == "downloaded"
        assert STATUS_ERROR == "error"
        assert STATUS_LOADING == "loading"
        assert STATUS_LOADED == "loaded"


class TestModelRegistry:
    def test_registry_has_required_models(self):
        """测试模型注册表包含必需模型"""
        assert "sdxl-base" in DEFAULT_MODEL_REGISTRY
        assert "sdxl-vae-fp16" in DEFAULT_MODEL_REGISTRY

    def test_registry_has_optional_models(self):
        """测试模型注册表包含可选模型"""
        assert "svd" in DEFAULT_MODEL_REGISTRY
        assert "sd-inpaint" in DEFAULT_MODEL_REGISTRY
        assert "sdxl-turbo" in DEFAULT_MODEL_REGISTRY
        assert "lcm-lora-sdxl" in DEFAULT_MODEL_REGISTRY

    def test_model_entry_fields(self):
        """测试模型条目字段完整性"""
        for key, entry in DEFAULT_MODEL_REGISTRY.items():
            assert "repo_id" in entry, f"{key} 缺少 repo_id"
            assert "type" in entry, f"{key} 缺少 type"
            assert "size_gb" in entry, f"{key} 缺少 size_gb"
            assert isinstance(entry["size_gb"], (int, float))

    def test_model_types(self):
        """测试模型类型"""
        valid_types = {"txt2img", "img2video", "inpainting", "vae", "lora"}
        for key, entry in DEFAULT_MODEL_REGISTRY.items():
            assert entry["type"] in valid_types, f"{key} 类型 {entry['type']} 无效"

    def test_model_required_flag(self):
        """测试必需模型标记"""
        assert DEFAULT_MODEL_REGISTRY["sdxl-base"]["required"] is True
        assert DEFAULT_MODEL_REGISTRY["sdxl-vae-fp16"]["required"] is True
        assert DEFAULT_MODEL_REGISTRY["sd15"]["required"] is False

    def test_model_sizes_reasonable(self):
        """测试模型大小合理"""
        for key, entry in DEFAULT_MODEL_REGISTRY.items():
            size = entry["size_gb"]
            assert 0 < size < 50, f"{key} 大小 {size}GB 不合理"


class TestModelLoaderInit:
    def setup_method(self):
        self.loader = ModelLoader()

    def test_initial_state(self):
        """测试初始状态"""
        assert self.loader._loaded_pipelines == {}
        assert self.loader._download_threads == {}
        assert len(self.loader._model_status) == len(DEFAULT_MODEL_REGISTRY)

    def test_initial_model_status(self):
        """测试初始模型状态"""
        status = self.loader.get_all_status()
        assert isinstance(status, dict)
        for key in DEFAULT_MODEL_REGISTRY:
            assert key in status

    def test_list_models(self):
        """测试列出模型"""
        models = self.loader.list_models()
        assert isinstance(models, dict)
        assert len(models) == len(DEFAULT_MODEL_REGISTRY)

    def test_list_models_with_status(self):
        """测试列出模型含状态"""
        models = self.loader.list_models(status=True)
        for key, info in models.items():
            assert "status" in info

    def test_search_models(self):
        """测试搜索模型"""
        results = self.loader.search_models("sdxl")
        assert isinstance(results, dict)
        assert len(results) > 0
        # 搜索应返回不区分大小写的匹配
        results_lower = self.loader.search_models("sdxl")
        results_upper = self.loader.search_models("SDXL")
        assert len(results_lower) == len(results_upper)

    def test_search_no_results(self):
        """测试搜索无结果"""
        results = self.loader.search_models("nonexistent_model_xyz")
        assert results == {}

    def test_get_models_by_type(self):
        """测试按类型获取模型"""
        txt2img_models = self.loader.get_models_by_type("txt2img")
        assert len(txt2img_models) > 0
        for key in txt2img_models:
            assert DEFAULT_MODEL_REGISTRY[key]["type"] == "txt2img"

    def test_get_models_for_function(self):
        """测试按功能获取模型"""
        models = self.loader.get_models_for_function("txt2img")
        assert isinstance(models, list)
        assert len(models) > 0

    def test_get_model_params(self):
        """测试获取模型参数"""
        params = self.loader.get_model_params("sdxl-base")
        assert isinstance(params, dict)
        assert "default_steps" in params
        assert "default_guidance" in params

    def test_get_model_params_unknown(self):
        """测试获取未知模型参数"""
        params = self.loader.get_model_params("unknown-model")
        assert params == {}

    def test_global_loader(self):
        """测试全局加载器"""
        from modules.model_loader import global_loader
        assert global_loader is not None
        assert isinstance(global_loader, ModelLoader)


class TestModelDownload:
    def setup_method(self):
        self.loader = ModelLoader()

    def test_start_download_unknown_model(self):
        """测试下载未知模型（返回 False）"""
        result = self.loader.start_download("unknown-model")
        assert result is False

    def test_is_downloading_initially(self):
        """测试初始未下载状态"""
        for key in list(DEFAULT_MODEL_REGISTRY.keys())[:3]:
            assert self.loader.is_downloading(key) is False

    def test_get_download_progress(self):
        """测试获取下载进度"""
        progress = self.loader.get_download_progress("sdxl-base")
        assert progress == 0.0