"""
NodeFlow 模型适配器包

导出所有 adapter 类,供 model_manager 通过 architecture 字段选择。

用法:
    from adapters import SDXLAdapter, Flux2KleinAdapter, BaseModelAdapter
"""

from .base_adapter import BaseModelAdapter

# SDXL 系列 (Lightning / Animagine / Illustrious)
from .sdxl_adapter import SDXLAdapter

# Flux2Klein 系列 (distilled / base)
from .flux2klein_adapter import Flux2KleinAdapter, FLUX2KLEIN_AVAILABLE

# 架构 -> 适配器类 的映射表,供 model_manager 使用
ADAPTER_REGISTRY: dict[str, type[BaseModelAdapter]] = {
    "sdxl": SDXLAdapter,
    "flux2klein": Flux2KleinAdapter,
}

__all__ = [
    "BaseModelAdapter",
    "SDXLAdapter",
    "Flux2KleinAdapter",
    "FLUX2KLEIN_AVAILABLE",
    "ADAPTER_REGISTRY",
]
