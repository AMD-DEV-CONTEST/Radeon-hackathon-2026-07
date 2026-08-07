"""
BaseModelAdapter — 模型适配器抽象基类

定义所有模型适配器的统一接口,包括:
    - 模型加载/卸载
    - 文生图 / 图生图
    - LoRA 加载/卸载
    - 能力查询 (img2img / strength / lora 支持)
    - 参数查询 (默认参数 / 参数范围 / 支持比例)

子类必须实现: load(), generate_from_text(), generate_from_image()
通用卸载逻辑在基类中实现 (del pipe + gc + empty_cache)。

设计要点 (审核报告修正):
    - unload() 内部完成 gc.collect() + torch.cuda.empty_cache(),无需外部重复调用
    - load_lora() / unload_lora() 只维护元数据,具体权重加载由子类覆盖
    - 能力查询方法从 model_config 读取,而非硬编码
"""

from abc import ABC, abstractmethod
from typing import Optional
from PIL import Image
import logging

logger = logging.getLogger("adapters")


class BaseModelAdapter(ABC):
    """模型适配器抽象基类,统一管理 pipeline 生命周期与推理接口。"""

    def __init__(self, model_id: str, model_config: dict):
        """
        初始化适配器。

        Args:
            model_id: 模型唯一标识 (对应 MODEL_REGISTRY 的 key)
            model_config: 模型配置字典 (来自 config.MODEL_REGISTRY)
        """
        self.model_id: str = model_id
        self.model_config: dict = model_config
        self._pipe = None          # diffusers pipeline 实例
        self._loaded: bool = False  # 是否已加载到 GPU/CPU
        self._loras: dict[str, tuple[str, float]] = {}  # {lora_id: (path, weight)}

    # ------------------------------------------------------------------
    # 抽象方法 — 子类必须实现
    # ------------------------------------------------------------------

    @abstractmethod
    def load(self) -> None:
        """加载模型到设备 (GPU 优先, CPU 降级)。子类实现具体加载逻辑。"""
        ...

    @abstractmethod
    def generate_from_text(self, prompt: str, **params) -> Image.Image:
        """
        文生图: 文字提示 -> 生成图片。

        Args:
            prompt: 文字提示
            **params: 生成参数 (width, height, num_inference_steps,
                       guidance_scale, seed, style, negative_prompt 等)

        Returns:
            PIL.Image.Image: 生成的图片
        """
        ...

    @abstractmethod
    def generate_from_image(
        self, image: Image.Image, prompt: str, **params
    ) -> Image.Image:
        """
        图生图: 参考图片 + 文字提示 -> 生成图片。

        Args:
            image: 参考图片 (PIL Image)
            prompt: 文字提示
            **params: 生成参数

        Returns:
            PIL.Image.Image: 生成的图片
        """
        ...

    # ------------------------------------------------------------------
    # 通用卸载逻辑
    # ------------------------------------------------------------------

    def unload(self) -> None:
        """
        通用卸载逻辑: del pipe + gc.collect + empty_cache。

        子类如有额外资源 (如独立的 img2img pipeline),应在调用
        super().unload() 之前清理。
        """
        if self._pipe is not None:
            del self._pipe
            self._pipe = None
        self._loaded = False
        self._loras.clear()

        import gc
        gc.collect()

        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                logger.info(
                    f"[{self.model_id}] Unloaded. "
                    f"VRAM allocated: {torch.cuda.memory_allocated() / 1e9:.2f} GB, "
                    f"reserved: {torch.cuda.memory_reserved() / 1e9:.2f} GB"
                )
        except ImportError:
            pass

    # ------------------------------------------------------------------
    # 能力查询
    # ------------------------------------------------------------------

    def supports_img2img(self) -> bool:
        """是否支持图生图。"""
        return self.model_config.get("supports_img2img", False)

    def supports_strength_control(self) -> bool:
        """是否支持 strength 参数 (img2img 风格化强度)。"""
        return self.model_config.get("supports_strength", False)

    def supports_lora(self) -> bool:
        """是否支持 LoRA。默认 True,子类可覆盖。"""
        return True

    def is_loaded(self) -> bool:
        """模型是否已加载。"""
        return self._loaded

    # ------------------------------------------------------------------
    # 参数查询
    # ------------------------------------------------------------------

    def get_default_params(self) -> dict:
        """获取模型默认参数。"""
        return self.model_config.get("default_params", {})

    def get_param_ranges(self) -> dict:
        """获取模型参数可调范围。"""
        return self.model_config.get("param_ranges", {})

    def get_supported_ratios(self) -> list:
        """获取模型支持的比例列表。"""
        return self.model_config.get("supported_ratios", [])

    # ------------------------------------------------------------------
    # LoRA 管理 (元数据层;子类可覆盖实现具体权重加载)
    # ------------------------------------------------------------------

    def load_lora(
        self, lora_path: str, weight: float = 0.8, lora_id: Optional[str] = None
    ) -> str:
        """
        注册一个 LoRA。如果模型已加载,子类应覆盖此方法以实际加载权重。

        Args:
            lora_path: LoRA 文件路径或 HuggingFace repo
            weight: LoRA 权重 (0.0 - 1.0)
            lora_id: LoRA 标识符,为 None 时自动生成

        Returns:
            lora_id: LoRA 标识符
        """
        if lora_id is None:
            lora_id = f"lora_{len(self._loras)}"
        self._loras[lora_id] = (lora_path, weight)
        logger.info(f"[{self.model_id}] LoRA registered: id={lora_id}, weight={weight}")
        return lora_id

    def unload_lora(self, lora_id: str) -> None:
        """
        移除一个 LoRA。如果模型已加载,子类应覆盖此方法以实际卸载权重。
        """
        if lora_id in self._loras:
            del self._loras[lora_id]
            logger.info(f"[{self.model_id}] LoRA removed: id={lora_id}")

    def get_loaded_loras(self) -> dict:
        """
        获取已注册的 LoRA 列表。

        Returns:
            {lora_id: {"path": str, "weight": float}} 字典
        """
        return {k: {"path": v[0], "weight": v[1]} for k, v in self._loras.items()}
