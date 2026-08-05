from typing import List
import threading
import logging
import time

import torch

from modules.model_loader import DEFAULT_MODEL_REGISTRY

logger = logging.getLogger("amd-ai-studio")

# 在 model_loader.py 末尾添加智能加载/卸载功能，加到 global_loader 定义之前

def get_available_vram_gb() -> float:
    """获取当前可用显存（GB）"""
    try:
        if torch.cuda.is_available():
            total = torch.cuda.get_device_properties(0).total_memory / 1024**3
            allocated = torch.cuda.memory_allocated(0) / 1024**3
            return total - allocated
        return 0
    except Exception:
        return 0


def get_total_vram_gb() -> float:
    """获取总显存（GB）"""
    try:
        if torch.cuda.is_available():
            return torch.cuda.get_device_properties(0).total_memory / 1024**3
        return 0
    except Exception:
        return 0


def get_compatible_models() -> List[str]:
    """根据系统显存返回兼容的模型列表"""
    vram = get_total_vram_gb()
    compatible = []
    for key, info in DEFAULT_MODEL_REGISTRY.items():
        size = info.get("size_gb", 0)
        # 模型需要至少 1.5 倍显存余量
        if vram >= size * 1.5 or vram >= 8:
            compatible.append(key)
        elif size <= 3:  # 小模型始终可用
            compatible.append(key)
    return compatible


class SmartModelManager:
    """智能模型管理器 — 根据 GPU 显存自动加载/卸载"""

    def __init__(self, loader: "ModelLoader"):
        self.loader = loader
        self._lock = threading.Lock()
        self._monitor_thread = None
        self._running = False
        self._vram_threshold_low = 0.15  # 剩余显存低于 15% 时卸载
        self._vram_threshold_high = 0.30  # 剩余显存高于 30% 时可加载

    def start_monitoring(self):
        """启动显存监控线程"""
        if self._monitor_thread and self._monitor_thread.is_alive():
            return
        self._running = True
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()
        logger.info("显存监控已启动")

    def stop_monitoring(self):
        self._running = False

    def _monitor_loop(self):
        """监控循环，定期检查显存并卸载模型"""
        while self._running:
            try:
                vram = get_total_vram_gb()
                available = get_available_vram_gb()
                if vram > 0 and available / vram < self._vram_threshold_low:
                    # 显存不足，卸载未使用的模型
                    loaded = dict(self.loader._loaded_pipelines)
                    if loaded:
                        # 只保留最近使用的模型
                        keys = list(loaded.keys())
                        for key in keys[:-1]:  # 保留最后一个
                            try:
                                self.loader.unload_pipeline(key)
                                logger.info(f"显存不足({available:.1f}/{vram:.1f}GB)，自动卸载模型: {key}")
                            except Exception:
                                pass
            except Exception:
                pass
            time.sleep(10)  # 每 10 秒检查一次

    def should_load_model(self, model_key: str) -> tuple[bool, str]:
        """检查是否可以加载模型"""
        registry = DEFAULT_MODEL_REGISTRY.get(model_key)
        if not registry:
            return False, "未知模型"

        size = registry.get("size_gb", 0)
        available = get_available_vram_gb()
        total = get_total_vram_gb()

        # 需要模型大小 + 2GB 余量
        needed = size * 1.2 + 2
        if available < needed and total > 0:
            # 尝试卸载一些模型
            self._emergency_unload(needed - available)
            available = get_available_vram_gb()

        if available < needed and total > 0:
            return False, f"显存不足: 需要{needed:.1f}GB，可用{available:.1f}GB"

        return True, f"可用显存: {available:.1f}GB"

    def _emergency_unload(self, needed_gb: float):
        """紧急卸载模型释放显存"""
        loaded = dict(self.loader._loaded_pipelines)
        for key in loaded:
            if needed_gb <= 0:
                break
            try:
                freed = self.loader.unload_pipeline(key)
                needed_gb -= freed
                logger.info(f"紧急卸载模型: {key}")
            except Exception:
                pass


# 更新 ModelLoader 类，添加 unload_pipeline 方法
# 这个需要在 model_loader.py 的 ModelLoader 类中添加