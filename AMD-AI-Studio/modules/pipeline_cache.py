"""
模型管道缓存 - 共享 pipeline 避免重复加载
"""

import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class PipelineCache:
    """模型管道缓存管理器"""
    _pipelines: Dict[str, Any] = field(default_factory=dict)

    def get(self, key: str):
        """获取缓存的 pipeline"""
        return self._pipelines.get(key)

    def set(self, key: str, pipeline):
        """缓存 pipeline"""
        self._pipelines[key] = pipeline
        logger.info(f"Pipeline [{key}] 已缓存")

    def clear(self):
        """清理所有缓存的 pipeline"""
        for key, pipe in self._pipelines.items():
            try:
                if hasattr(pipe, 'to'):
                    pipe.to("cpu")
                del pipe
            except Exception:
                pass
        self._pipelines.clear()
        logger.info("所有 pipeline 缓存已清理")

    def remove(self, key: str):
        """移除指定 pipeline"""
        pipe = self._pipelines.pop(key, None)
        if pipe is not None:
            try:
                del pipe
            except Exception:
                pass
            logger.info(f"Pipeline [{key}] 已移除")

    @property
    def keys(self):
        return list(self._pipelines.keys())


# 全局缓存实例
global_cache = PipelineCache()
