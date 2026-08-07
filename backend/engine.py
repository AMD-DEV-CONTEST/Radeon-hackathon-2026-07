"""
FluxEngine — 兼容层 (向后兼容门面)

历史背景:
    早期 NodeFlow 的 engine.py 直接加载 Flux schnell 单管线。重构为
    "多模型 + 双模式 (快速版/专家版)" 架构后,真正的模型加载、切换、LoRA
    管理等逻辑下沉到 ``model_manager.ModelManager``。

本模块的职责:
    * 保留 ``FluxEngine`` 类名与单例语义,使旧代码 (main.py、前端契约、
      外部脚本) 无需改动即可继续工作。
    * 作为一层薄薄的门面 (facade),把所有调用委托给全局单例
      ``model_manager``。
    * 不再持有任何 diffusers / torch 对象,保持本文件轻量可导入。

依赖说明:
    ``model_manager.py`` 由另一个 agent 同时开发。本文件按约定的接口调用它:
        model_manager = ModelManager()              # 单例
        model_manager.load_default()                # 初始化默认模型
        model_manager.switch_model(model_id)        # 切换模型
        model_manager.generate_from_text(prompt, style, **params) -> Image
        model_manager.generate_from_image(image, style, **params) -> Image
        model_manager.get_available_models(mode) -> list
        model_manager.get_current_model_info() -> dict
        model_manager.get_model_config(model_id) -> dict
        model_manager.load_lora(path, weight) -> str
        model_manager.unload_lora(lora_id) -> None
        model_manager.get_loaded_loras() -> dict
        model_manager.get_gpu_info() -> dict
        model_manager.is_loaded() -> bool
        model_manager.get_styles() -> dict
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from PIL import Image

# 共享常量从 config 导入,避免与本文件历史常量重复定义
from config import (
    DEFAULT_GUIDANCE_SCALE,
    DEFAULT_NUM_STEPS,
    MAX_RESOLUTION,
    MIN_RESOLUTION,
    STYLE_PRESETS,
)
from model_manager import ModelManager

logger = logging.getLogger("flux_engine")

# 全局 ModelManager 单例 (与 model_manager.py 内部单例等价)
# 在模块导入时构造一次;ModelManager.__init__ 应保持轻量 (不加载模型)。
model_manager: ModelManager = ModelManager()


class FluxEngine:
    """
    FluxEngine 兼容层 (单例门面)。

    所有方法均委托给模块级 ``model_manager`` 单例。保留单例是为了与旧版
    ``engine = FluxEngine()`` 的用法完全兼容。

    向后兼容方法:
        load / generate_from_text / generate_from_image / get_styles /
        get_gpu_info / is_loaded

    新增 (双模式 / 多模型 / LoRA) 委托方法:
        get_available_models / switch_model / get_current_model_info /
        get_model_config / load_lora / unload_lora / get_loaded_loras
    """

    _instance: Optional["FluxEngine"] = None

    def __new__(cls) -> "FluxEngine":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            logger.debug("FluxEngine singleton created (compat facade)")
        return cls._instance

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------
    def load(self) -> None:
        """
        初始化默认模型 (快速版 SDXL-Lightning 4 步)。

        委托给 ``model_manager.load_default()``。重复调用应幂等
        (由 ModelManager 保证)。
        """
        logger.info("FluxEngine.load() -> model_manager.load_default()")
        model_manager.load_default()

    def is_loaded(self) -> bool:
        """检查当前是否已有模型加载到 GPU。"""
        return bool(model_manager.is_loaded())

    # ------------------------------------------------------------------
    # 生成 (委托)
    # ------------------------------------------------------------------
    def generate_from_text(
        self,
        prompt: str,
        style: str = "cyberpunk",
        num_inference_steps: Optional[int] = None,
        guidance_scale: Optional[float] = None,
        width: int = 1024,
        height: int = 1024,
        **kwargs: Any,
    ) -> Image.Image:
        """
        文生图 (委托)。

        保留旧签名 (prompt/style/num_inference_steps/guidance_scale/width/height)
        以兼容历史调用;额外参数通过 ``**kwargs`` 透传给 ModelManager
        (如 seed / negative_prompt / loras / model 等)。

        关于默认值:
            ``num_inference_steps`` / ``guidance_scale`` 默认为 ``None``,表示
            "未指定",此时 **不** 透传给 ModelManager,由其使用各模型
            ``default_params`` 中的推荐值。这避免了用旧 Flux schnell 默认
            (guidance=0.0) 覆盖 SDXL-Lightning 等模型的真实默认 (guidance=1.5)。
            若调用方显式传入,则作为覆盖项透传。

        Args:
            prompt: 用户文字提示词。
            style: 风格 key (见 :data:`config.STYLE_PRESETS`)。
            num_inference_steps: 推理步数;``None`` 表示用模型默认。
            guidance_scale: CFG 引导强度;``None`` 表示用模型默认。
            width: 输出宽度。
            height: 输出高度。
            **kwargs: 透传给 ``ModelManager.generate_from_text`` 的额外参数。

        Returns:
            生成的 PIL Image。
        """
        params: dict[str, Any] = {"width": width, "height": height}
        if num_inference_steps is not None:
            params["num_inference_steps"] = num_inference_steps
        if guidance_scale is not None:
            params["guidance_scale"] = guidance_scale
        params.update(kwargs)
        return model_manager.generate_from_text(prompt=prompt, style=style, **params)

    def generate_from_image(
        self,
        image: Image.Image,
        style: str = "cyberpunk",
        strength: float = 0.8,
        num_inference_steps: Optional[int] = None,
        guidance_scale: Optional[float] = None,
        width: int = 1024,
        height: int = 1024,
        **kwargs: Any,
    ) -> Image.Image:
        """
        图生图 (委托)。

        Args:
            image: 输入图片 (PIL Image)。
            style: 风格 key。
            strength: 风格化强度 (0.1-1.0),越高越偏离原图。
            num_inference_steps: 推理步数;``None`` 表示用模型默认。
            guidance_scale: CFG 引导强度;``None`` 表示用模型默认。
            width: 输出宽度。
            height: 输出高度。
            **kwargs: 透传给 ``ModelManager.generate_from_image`` 的额外参数。

        Returns:
            生成的 PIL Image。
        """
        params: dict[str, Any] = {
            "strength": strength,
            "width": width,
            "height": height,
        }
        if num_inference_steps is not None:
            params["num_inference_steps"] = num_inference_steps
        if guidance_scale is not None:
            params["guidance_scale"] = guidance_scale
        params.update(kwargs)
        return model_manager.generate_from_image(image=image, style=style, **params)

    # ------------------------------------------------------------------
    # 查询 (委托)
    # ------------------------------------------------------------------
    def get_styles(self) -> dict[str, str]:
        """返回可用风格预设 {key: prompt_prefix}。"""
        return model_manager.get_styles()

    def get_gpu_info(self) -> dict[str, Any]:
        """返回 GPU / 显存状态。"""
        return model_manager.get_gpu_info()

    # ------------------------------------------------------------------
    # 多模型 / 双模式 (新增委托)
    # ------------------------------------------------------------------
    def get_available_models(self, mode: str = "fast") -> list[dict[str, Any]]:
        """
        获取指定模式下可用模型列表。

        Args:
            mode: ``"fast"`` 或 ``"expert"``。

        Returns:
            模型信息字典列表 (由 ModelManager 定义具体字段)。
        """
        return model_manager.get_available_models(mode)

    def switch_model(self, model_id: str) -> dict[str, Any]:
        """
        切换当前加载的模型。

        Args:
            model_id: 目标模型标识。

        Returns:
            切换结果 / 当前模型信息。
        """
        logger.info("FluxEngine.switch_model(%s)", model_id)
        return model_manager.switch_model(model_id)

    def get_current_model_info(self) -> dict[str, Any]:
        """获取当前已加载模型与模式的详细信息。"""
        return model_manager.get_current_model_info()

    def get_model_config(self, model_id: str) -> dict[str, Any]:
        """
        获取某模型的参数配置 (步数范围、引导范围、推荐宽高比等)。

        Args:
            model_id: 模型标识。

        Returns:
            模型配置字典。
        """
        return model_manager.get_model_config(model_id)

    # ------------------------------------------------------------------
    # LoRA (新增委托)
    # ------------------------------------------------------------------
    def load_lora(self, path: str, weight: float = 1.0) -> str:
        """
        加载 LoRA 权重。

        Args:
            path: LoRA 文件路径或远端标识。
            weight: LoRA 强度 (0.0-1.0+)。

        Returns:
            已加载 LoRA 的标识 (lora_id),用于后续卸载。
        """
        logger.info("FluxEngine.load_lora(%s, weight=%s)", path, weight)
        return model_manager.load_lora(path, weight)

    def unload_lora(self, lora_id: str) -> None:
        """
        卸载指定 LoRA。

        Args:
            lora_id: :meth:`load_lora` 返回的标识。
        """
        logger.info("FluxEngine.unload_lora(%s)", lora_id)
        return model_manager.unload_lora(lora_id)

    def get_loaded_loras(self) -> dict[str, Any]:
        """返回当前已加载的 LoRA {lora_id: {path, weight, ...}}。"""
        return model_manager.get_loaded_loras()


# ---------------------------------------------------------------------------
# 模块级常量再导出 (向后兼容:旧代码可能 `from engine import STYLE_PRESETS`)
# 这些值直接来自 config,确保单一数据源。
# ---------------------------------------------------------------------------
__all__ = [
    "FluxEngine",
    "model_manager",
    "STYLE_PRESETS",
    "DEFAULT_NUM_STEPS",
    "DEFAULT_GUIDANCE_SCALE",
    "MIN_RESOLUTION",
    "MAX_RESOLUTION",
]
