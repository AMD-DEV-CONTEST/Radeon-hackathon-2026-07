"""模型加载管理器（safetensors 版本，vLLM 使用）。

管理 Qwen2.5-Instruct 系列模型的下载、路径查询。
"""

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


# 模型仓库配置
MODEL_CONFIGS = {
    "qwen2.5-7b": {
        "modelscope_id": "Qwen/Qwen2.5-7B-Instruct",
        "huggingface_id": "Qwen/Qwen2.5-7B-Instruct",
        "local_dir": "Qwen2.5-7B-Instruct",
    },
    "qwen2.5-14b": {
        "modelscope_id": "Qwen/Qwen2.5-14B-Instruct",
        "huggingface_id": "Qwen/Qwen2.5-14B-Instruct",
        "local_dir": "Qwen2.5-14B-Instruct",
    },
}


class ModelLoader:
    """管理本地模型的路径查询与下载。"""

    def __init__(self, models_dir: str = "./models"):
        self.models_dir = models_dir
        os.makedirs(models_dir, exist_ok=True)

    def get_model_path(self, model_name: str) -> Optional[str]:
        """获取模型本地路径（如果已下载）。

        Args:
            model_name: 模型名称，如 "qwen2.5-7b"

        Returns:
            模型目录路径，未下载返回 None
        """
        if model_name not in MODEL_CONFIGS:
            return None

        local_dir = MODEL_CONFIGS[model_name]["local_dir"]
        save_path = os.path.join(self.models_dir, local_dir)

        # 检查 config.json 是否存在（safetensors 模型的标志）
        if os.path.exists(save_path) and os.path.exists(os.path.join(save_path, "config.json")):
            return save_path
        return None

    def list_models(self) -> list:
        """列出已下载的模型。"""
        models = []
        if not os.path.exists(self.models_dir):
            return models

        for name in os.listdir(self.models_dir):
            model_path = os.path.join(self.models_dir, name)
            if os.path.isdir(model_path) and os.path.exists(os.path.join(model_path, "config.json")):
                models.append(name)
        return models

    def download_model(self, model_name: str) -> str:
        """下载模型（委托给 download_model.py 的逻辑）。

        Args:
            model_name: 模型名称

        Returns:
            模型本地路径
        """
        from scripts.download_model import download_model as _download
        return _download(model_name, self.models_dir)
