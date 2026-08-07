"""
SDXL 系列模型适配器

统一覆盖以下模型 (通过 model_config 的 is_distilled / hf_path 区分):
    - SDXL-Lightning (4-step / 8-step) : ByteDance 蒸馏模型,加载 base SDXL + 蒸馏 UNet
    - Animagine XL 4.0                  : 二次元风格 SDXL 模型
    - Illustrious XL                    : 插画风格 SDXL 模型

关键设计:
    - Lightning 模型: 加载 stabilityai/sd-xl-base-1.0 + ByteDance/SDXL-Lightning 蒸馏 UNet,
      配合 EulerDiscreteScheduler 调度器,步数锁定。
    - 常规 SDXL 模型: 直接 from_pretrained 加载完整 pipeline。
    - img2img: 通过 StableDiffusionXLImg2ImgPipeline.from_pipe() 复用权重,节省显存。
    - LoRA: pipe.load_lora_weights() + set_adapters() + delete_adapters()。
    - 尺寸: 必须为 64 的倍数,自动对齐。
    - negative_prompt: SDXL 原生支持,使用模型默认值或用户自定义。
    - dtype: torch.float16 (SDXL 官方推荐,ROCm 支持)。
"""

import logging
import time
from typing import Optional

from PIL import Image

from .base_adapter import BaseModelAdapter
from config import (
    STYLE_PRESETS,
    RATIO_MAPPINGS,
    ARCHITECTURE_RATIO_FAMILY,
    MIN_RESOLUTION,
    MAX_RESOLUTION,
    SDXL_SIZE_ALIGNMENT,
)

logger = logging.getLogger("adapters")

# Pillow 版本兼容: Resampling 枚举 (Pillow >= 9.0)
try:
    _LANCZOS = Image.Resampling.LANCZOS
except AttributeError:
    _LANCZOS = Image.LANCZOS


class SDXLAdapter(BaseModelAdapter):
    """
    SDXL 系列模型适配器。

    支持 Lightning (蒸馏) 和常规 SDXL (Animagine / Illustrious) 两种加载路径。
    img2img 通过 from_pipe 复用权重,strength 参数原生支持。
    """

    def __init__(self, model_id: str, model_config: dict):
        super().__init__(model_id, model_config)
        self._device: str = "cpu"
        self._dtype = None  # torch.dtype,在 load() 中设置
        self._pipe_i2i = None  # img2img pipeline (懒加载,共享权重)

    # ------------------------------------------------------------------
    # 设备检测
    # ------------------------------------------------------------------

    def _detect_device(self) -> None:
        """检测可用设备 (CUDA/ROCm 优先,CPU 降级) 并设置 dtype。"""
        try:
            import torch
            if torch.cuda.is_available():
                self._device = "cuda"
                self._dtype = torch.float16  # SDXL 官方推荐 float16
                gpu_name = torch.cuda.get_device_name(0)
                gpu_mem = torch.cuda.get_device_properties(0).total_memory / 1e9
                logger.info(
                    f"[{self.model_id}] GPU detected: {gpu_name}, VRAM: {gpu_mem:.1f} GB"
                )
            else:
                self._device = "cpu"
                self._dtype = torch.float32
                logger.warning(
                    f"[{self.model_id}] CUDA/ROCm not available, falling back to CPU"
                )
        except ImportError:
            self._device = "cpu"
            self._dtype = None
            logger.error("torch not installed")

    # ------------------------------------------------------------------
    # 模型加载
    # ------------------------------------------------------------------

    def load(self) -> None:
        """加载 SDXL 模型到设备。"""
        if self._loaded:
            logger.info(f"[{self.model_id}] Already loaded, skipping")
            return

        self._detect_device()

        import torch
        from diffusers import StableDiffusionXLPipeline

        is_lightning = self.model_config.get("is_distilled", False)
        defaults = self.get_default_params()

        if is_lightning and self.model_config.get("single_file_checkpoint"):
            # === Lightning 路径: 单文件 checkpoint (hf_hub_download + from_single_file) ===
            from diffusers import EulerDiscreteScheduler
            from huggingface_hub import hf_hub_download

            repo_id = self.model_config["hf_path"]
            filename = self.model_config["single_file_checkpoint"]

            logger.info(
                f"[{self.model_id}] Downloading Lightning single-file checkpoint: "
                f"{repo_id}/{filename}"
            )
            # hf_hub_download 自动读取 HF_ENDPOINT / HF_TOKEN / HF_HOME 环境变量
            ckpt_path = hf_hub_download(
                repo_id=repo_id,
                filename=filename,
            )
            logger.info(f"[{self.model_id}] Downloaded to: {ckpt_path}")

            self._pipe = StableDiffusionXLPipeline.from_single_file(
                ckpt_path,
                torch_dtype=self._dtype,
                use_safetensors=True,
            ).to(self._device)

            # Lightning 推荐 EulerDiscreteScheduler
            self._pipe.scheduler = EulerDiscreteScheduler.from_config(
                self._pipe.scheduler.config
            )
        else:
            # === 常规 SDXL 路径 (Animagine / Illustrious) ===
            logger.info(
                f"[{self.model_id}] Loading from {self.model_config['hf_path']}"
            )
            self._pipe = StableDiffusionXLPipeline.from_pretrained(
                self.model_config["hf_path"],
                torch_dtype=self._dtype,
            ).to(self._device)

        self._loaded = True

        # 加载之前注册的 LoRA (模型切换时恢复)
        self._load_pending_loras()

        # 打印显存占用
        if self._device == "cuda":
            allocated = torch.cuda.memory_allocated() / 1e9
            reserved = torch.cuda.memory_reserved() / 1e9
            logger.info(
                f"[{self.model_id}] Loaded on {self._device}. "
                f"VRAM: allocated={allocated:.2f} GB, reserved={reserved:.2f} GB"
            )
        else:
            logger.info(f"[{self.model_id}] Loaded on {self._device}")

    def _load_pending_loras(self) -> None:
        """加载在模型加载前注册的 LoRA (用于模型切换后恢复)。"""
        if not self._loras or self._pipe is None:
            return

        for lora_id, (path, weight) in list(self._loras.items()):
            try:
                self._pipe.load_lora_weights(path, adapter_name=lora_id)
                logger.info(
                    f"[{self.model_id}] Pending LoRA loaded: id={lora_id}"
                )
            except Exception as e:
                logger.warning(
                    f"[{self.model_id}] Could not load LoRA '{lora_id}': {e}"
                )
                if lora_id in self._loras:
                    del self._loras[lora_id]

        # 激活所有 LoRA 适配器
        self._activate_loras()

    def _activate_loras(self) -> None:
        """激活所有已注册的 LoRA 适配器并设置权重。"""
        if not self._loras or self._pipe is None:
            return
        names = list(self._loras.keys())
        weights = [w for _, w in self._loras.values()]
        try:
            self._pipe.set_adapters(names, adapter_weights=weights)
            logger.info(
                f"[{self.model_id}] Active LoRAs: {names} with weights {weights}"
            )
        except Exception as e:
            logger.warning(f"[{self.model_id}] Could not set LoRA adapters: {e}")

    # ------------------------------------------------------------------
    # img2img pipeline (懒加载,共享权重)
    # ------------------------------------------------------------------

    def _get_img2img_pipe(self):
        """获取 img2img pipeline,首次调用时通过 from_pipe 创建以共享权重。"""
        if self._pipe_i2i is None and self._pipe is not None:
            from diffusers import StableDiffusionXLImg2ImgPipeline
            logger.info(f"[{self.model_id}] Creating img2img pipeline (from_pipe)")
            self._pipe_i2i = StableDiffusionXLImg2ImgPipeline.from_pipe(self._pipe)
        return self._pipe_i2i

    # ------------------------------------------------------------------
    # 卸载 (清理额外的 img2img pipeline)
    # ------------------------------------------------------------------

    def unload(self) -> None:
        """卸载模型,同时清理 img2img pipeline。"""
        if self._pipe_i2i is not None:
            del self._pipe_i2i
            self._pipe_i2i = None
        super().unload()

    # ------------------------------------------------------------------
    # 参数解析辅助方法
    # ------------------------------------------------------------------

    def _validate_dimensions(self, width: int, height: int) -> tuple[int, int]:
        """校验并对齐尺寸为 64 的倍数。"""
        width = max(MIN_RESOLUTION, min(MAX_RESOLUTION, width))
        height = max(MIN_RESOLUTION, min(MAX_RESOLUTION, height))
        width = (width // SDXL_SIZE_ALIGNMENT) * SDXL_SIZE_ALIGNMENT
        height = (height // SDXL_SIZE_ALIGNMENT) * SDXL_SIZE_ALIGNMENT
        return width, height

    def _parse_dimensions(self, params: dict) -> tuple[int, int]:
        """从参数中解析尺寸 (支持 ratio 或 width/height)。"""
        ratio = params.get("ratio")
        if ratio:
            family = ARCHITECTURE_RATIO_FAMILY.get(
                self.model_config.get("architecture", "sdxl"), "sdxl"
            )
            ratios = RATIO_MAPPINGS.get(family, {})
            if ratio in ratios:
                return ratios[ratio]["width"], ratios[ratio]["height"]

        width = params.get("width", 1024)
        height = params.get("height", 1024)
        return self._validate_dimensions(width, height)

    def _get_inference_params(self, params: dict) -> tuple[int, float, float]:
        """
        从参数中解析推理参数 (步数 / guidance / strength)。

        如果参数被锁定 (locked=True),强制使用默认值。

        Returns:
            (num_inference_steps, guidance_scale, strength)
        """
        defaults = self.get_default_params()
        ranges = self.get_param_ranges()

        steps = params.get(
            "num_inference_steps", defaults.get("num_inference_steps", 25)
        )
        guidance = params.get(
            "guidance_scale", defaults.get("guidance_scale", 7.0)
        )
        strength = params.get("strength", defaults.get("strength", 0.8))

        # 如果步数被锁定,强制使用默认值
        steps_range = ranges.get("num_inference_steps", {})
        if steps_range.get("locked", False):
            steps = defaults.get("num_inference_steps", steps)
        else:
            steps = max(steps_range.get("min", 1), min(steps_range.get("max", 100), steps))

        guidance_range = ranges.get("guidance_scale", {})
        if guidance_range.get("locked", False):
            guidance = defaults.get("guidance_scale", guidance)
        else:
            guidance = max(
                guidance_range.get("min", 0.0),
                min(guidance_range.get("max", 20.0), guidance),
            )

        strength_range = ranges.get("strength", {})
        if strength_range:
            strength = max(
                strength_range.get("min", 0.1),
                min(strength_range.get("max", 1.0), strength),
            )
        else:
            strength = max(0.1, min(1.0, float(strength)))

        return int(steps), float(guidance), float(strength)

    def _apply_style(self, prompt: str, style: Optional[str] = None) -> str:
        """将风格预设应用到 prompt 上。"""
        quality_suffix = "high quality, detailed, professional"

        if style and style in STYLE_PRESETS:
            prefix = STYLE_PRESETS[style]
            if prompt.strip():
                return f"{prefix} {prompt}, {quality_suffix}"
            return f"{prefix} {quality_suffix}"

        if prompt.strip():
            return f"{prompt}, {quality_suffix}"
        return quality_suffix

    def _get_negative_prompt(self, params: dict) -> Optional[str]:
        """获取 negative prompt (用户自定义优先,否则使用模型默认)。"""
        neg = params.get("negative_prompt")
        if neg and neg.strip():
            return neg
        return self.get_default_params().get("negative_prompt")

    def _get_generator(self, seed: int):
        """创建指定 seed 的 torch.Generator。"""
        import torch
        gen = torch.Generator(device=self._device)
        gen.manual_seed(int(seed))
        return gen

    def _cleanup_on_error(self) -> None:
        """生成失败后清理 VRAM。"""
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

    # ------------------------------------------------------------------
    # 文生图
    # ------------------------------------------------------------------

    def generate_from_text(self, prompt: str, **params) -> Image.Image:
        """
        文生图: 文字提示 -> 生成图片。

        Args:
            prompt: 文字提示 (非空)
            **params: 可选参数:
                - width (int): 输出宽度 (默认 1024)
                - height (int): 输出高度 (默认 1024)
                - ratio (str): 比例 key (如 "1:1", "3:4"),优先于 width/height
                - num_inference_steps (int): 推理步数
                - guidance_scale (float): 引导尺度
                - seed (int): 随机种子
                - style (str): 风格预设 key
                - negative_prompt (str): 负面提示

        Returns:
            PIL.Image.Image: 生成的图片

        Raises:
            RuntimeError: 模型未加载
            ValueError: prompt 为空
        """
        if not self._loaded or self._pipe is None:
            raise RuntimeError(
                f"Model '{self.model_id}' is not loaded. Call load() first."
            )

        prompt = prompt.strip()
        if not prompt:
            raise ValueError("Prompt cannot be empty")

        width, height = self._parse_dimensions(params)
        steps, guidance, _ = self._get_inference_params(params)
        style = params.get("style")
        seed = params.get("seed")
        negative_prompt = self._get_negative_prompt(params)

        full_prompt = self._apply_style(prompt, style)

        kwargs: dict = {
            "prompt": full_prompt,
            "num_inference_steps": steps,
            "guidance_scale": guidance,
            "width": width,
            "height": height,
        }
        if negative_prompt:
            kwargs["negative_prompt"] = negative_prompt
        if seed is not None:
            kwargs["generator"] = self._get_generator(seed)

        logger.info(
            f"[{self.model_id}] text2img: size={width}x{height}, "
            f"steps={steps}, cfg={guidance}, "
            f"prompt='{full_prompt[:80]}...'"
        )

        start = time.time()
        try:
            result = self._pipe(**kwargs)
        except Exception as e:
            logger.error(
                f"[{self.model_id}] text2img failed: {e}", exc_info=True
            )
            self._cleanup_on_error()
            raise RuntimeError(
                f"Text-to-image generation failed for '{self.model_id}': {e}"
            ) from e

        elapsed = time.time() - start
        logger.info(f"[{self.model_id}] text2img completed in {elapsed:.2f}s")
        return result.images[0]

    # ------------------------------------------------------------------
    # 图生图
    # ------------------------------------------------------------------

    def generate_from_image(
        self, image: Image.Image, prompt: str, **params
    ) -> Image.Image:
        """
        图生图: 参考图片 + 文字提示 -> 生成图片。

        使用 StableDiffusionXLImg2ImgPipeline (通过 from_pipe 共享权重)。
        支持 strength 参数控制风格化强度。

        Args:
            image: 参考图片 (PIL Image)
            prompt: 文字提示
            **params: 可选参数:
                - width / height / ratio: 尺寸控制
                - num_inference_steps (int): 推理步数
                - guidance_scale (float): 引导尺度
                - strength (float): 风格化强度 (0.1 - 1.0)
                - seed (int): 随机种子
                - style (str): 风格预设 key
                - negative_prompt (str): 负面提示

        Returns:
            PIL.Image.Image: 生成的图片

        Raises:
            RuntimeError: 模型未加载
        """
        if not self._loaded or self._pipe is None:
            raise RuntimeError(
                f"Model '{self.model_id}' is not loaded. Call load() first."
            )

        width, height = self._parse_dimensions(params)
        steps, guidance, strength = self._get_inference_params(params)
        style = params.get("style")
        seed = params.get("seed")
        negative_prompt = self._get_negative_prompt(params)

        full_prompt = self._apply_style(prompt, style)

        # 缩放输入图片到目标尺寸 (LANCZOS 高质量重采样)
        image = image.convert("RGB").resize((width, height), _LANCZOS)

        # 获取 img2img pipeline (懒加载,共享权重)
        pipe_i2i = self._get_img2img_pipe()

        kwargs: dict = {
            "prompt": full_prompt,
            "image": image,
            "strength": strength,
            "num_inference_steps": steps,
            "guidance_scale": guidance,
        }
        if negative_prompt:
            kwargs["negative_prompt"] = negative_prompt
        if seed is not None:
            kwargs["generator"] = self._get_generator(seed)

        logger.info(
            f"[{self.model_id}] img2img: size={width}x{height}, "
            f"steps={steps}, cfg={guidance}, strength={strength}"
        )

        start = time.time()
        try:
            result = pipe_i2i(**kwargs)
        except Exception as e:
            logger.error(
                f"[{self.model_id}] img2img failed: {e}", exc_info=True
            )
            self._cleanup_on_error()
            raise RuntimeError(
                f"Image-to-image generation failed for '{self.model_id}': {e}"
            ) from e

        elapsed = time.time() - start
        logger.info(f"[{self.model_id}] img2img completed in {elapsed:.2f}s")
        return result.images[0]

    # ------------------------------------------------------------------
    # LoRA 管理 (覆盖基类,实现具体权重加载)
    # ------------------------------------------------------------------

    def load_lora(
        self,
        lora_path: str,
        weight: float = 0.8,
        lora_id: Optional[str] = None,
    ) -> str:
        """
        加载 LoRA 适配器。如果模型已加载,立即加载权重。

        Args:
            lora_path: LoRA 文件路径或 HuggingFace repo
            weight: LoRA 权重 (0.0 - 1.0)
            lora_id: LoRA 标识符,为 None 时自动生成

        Returns:
            lora_id: LoRA 标识符

        Raises:
            RuntimeError: 加载失败
        """
        lora_id = super().load_lora(lora_path, weight, lora_id)

        if self._loaded and self._pipe is not None:
            try:
                self._pipe.load_lora_weights(lora_path, adapter_name=lora_id)
                self._activate_loras()
                logger.info(
                    f"[{self.model_id}] LoRA loaded: id={lora_id}, weight={weight}"
                )
            except Exception as e:
                logger.error(
                    f"[{self.model_id}] Failed to load LoRA '{lora_id}': {e}"
                )
                if lora_id in self._loras:
                    del self._loras[lora_id]
                raise RuntimeError(
                    f"Failed to load LoRA '{lora_id}': {e}"
                ) from e

        return lora_id

    def unload_lora(self, lora_id: str) -> None:
        """
        卸载 LoRA 适配器。如果模型已加载,立即移除权重。

        Args:
            lora_id: LoRA 标识符
        """
        if lora_id not in self._loras:
            logger.warning(
                f"[{self.model_id}] LoRA '{lora_id}' not found, skipping unload"
            )
            return

        super().unload_lora(lora_id)

        if self._loaded and self._pipe is not None:
            try:
                self._pipe.delete_adapters([lora_id])
                # 重新激活剩余的 LoRA
                if self._loras:
                    self._activate_loras()
                logger.info(
                    f"[{self.model_id}] LoRA removed: id={lora_id}"
                )
            except Exception as e:
                logger.warning(
                    f"[{self.model_id}] Could not remove LoRA "
                    f"'{lora_id}' from pipeline: {e}"
                )
