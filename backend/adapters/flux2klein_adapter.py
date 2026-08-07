"""
FLUX.2 Klein 模型适配器

覆盖 distilled (4步蒸馏) 和 base (50步可调) 两种变体,通过 model_config 的
is_distilled 字段区分运行时行为。

关键设计 (审核报告修正):
    - 使用 Flux2KleinPipeline (统一管线): 不传 image = 文生图,传 image = 图像编辑
    - 没有 strength 参数! generate_from_image 时通过 image 作为参考条件
    - distilled: steps=4, cfg=1.0, 参数锁定; base: steps=50, cfg=4.0, 参数可调
    - 尺寸必须是 16 的倍数
    - negative_prompt 特殊处理: Flux2Klein 用 negative_prompt_embeds,
      先尝试传字符串,如果报错则忽略并重试
    - torch_dtype = torch.bfloat16
    - Flux2KleinPipeline 的 import 用 try/except,因为当前 diffusers 可能未支持

降级处理:
    如果 diffusers 未安装 Flux2KleinPipeline,FLUX2KLEIN_AVAILABLE = False,
    load() 会抛出 ImportError 提示升级 diffusers。
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
    FLUX_SIZE_ALIGNMENT,
)

logger = logging.getLogger("adapters")

# Pillow 版本兼容
try:
    _LANCZOS = Image.Resampling.LANCZOS
except AttributeError:
    _LANCZOS = Image.LANCZOS

# ---------------------------------------------------------------------------
# Flux2KleinPipeline 导入 (降级处理)
# ---------------------------------------------------------------------------

FLUX2KLEIN_AVAILABLE: bool = False
Flux2KleinPipeline = None

try:
    from diffusers import Flux2KleinPipeline
    FLUX2KLEIN_AVAILABLE = True
    logger.info("Flux2KleinPipeline imported successfully")
except ImportError:
    FLUX2KLEIN_AVAILABLE = False
    logger.warning(
        "Flux2KleinPipeline is not available in current diffusers version. "
        "Please upgrade diffusers to support FLUX.2. "
        "Flux2Klein adapter will not be able to load models."
    )


class Flux2KleinAdapter(BaseModelAdapter):
    """
    FLUX.2 Klein 模型适配器。

    支持 distilled (4步) 和 base (50步) 两种模式,通过 is_distilled 区分。
    统一管线设计:不传 image = 文生图,传 image = 图像编辑 (无 strength)。
    """

    def __init__(self, model_id: str, model_config: dict):
        super().__init__(model_id, model_config)
        self._device: str = "cpu"
        self._dtype = None  # torch.dtype, 在 load() 中设置
        self._is_distilled: bool = model_config.get("is_distilled", False)

    # ------------------------------------------------------------------
    # 设备检测
    # ------------------------------------------------------------------

    def _detect_device(self) -> None:
        """检测可用设备 (CUDA/ROCm 优先)。Flux2Klein 使用 bfloat16。"""
        try:
            import torch
            if torch.cuda.is_available():
                self._device = "cuda"
                self._dtype = torch.bfloat16  # Flux2Klein 指定 bfloat16
                gpu_name = torch.cuda.get_device_name(0)
                gpu_mem = torch.cuda.get_device_properties(0).total_memory / 1e9
                logger.info(
                    f"[{self.model_id}] GPU detected: {gpu_name}, "
                    f"VRAM: {gpu_mem:.1f} GB"
                )
            else:
                self._device = "cpu"
                self._dtype = torch.bfloat16
                logger.warning(
                    f"[{self.model_id}] CUDA/ROCm not available, "
                    f"falling back to CPU (will be very slow)"
                )
        except ImportError:
            self._device = "cpu"
            self._dtype = None
            logger.error("torch not installed")

    # ------------------------------------------------------------------
    # 模型加载
    # ------------------------------------------------------------------

    def load(self) -> None:
        """
        加载 FLUX.2 Klein 模型到设备。

        通过 is_distilled 参数区分 distilled / base 版本。

        Raises:
            ImportError: Flux2KleinPipeline 不可用 (diffusers 版本过低)
            RuntimeError: 加载失败
        """
        if self._loaded:
            logger.info(f"[{self.model_id}] Already loaded, skipping")
            return

        if not FLUX2KLEIN_AVAILABLE or Flux2KleinPipeline is None:
            raise ImportError(
                "Flux2KleinPipeline is not available. "
                "Please upgrade diffusers to a version that supports FLUX.2: "
                "pip install --upgrade diffusers transformers"
            )

        self._detect_device()

        import torch

        hf_path = self.model_config["hf_path"]
        logger.info(
            f"[{self.model_id}] Loading FLUX.2 Klein from {hf_path} "
            f"(distilled={self._is_distilled}, dtype={self._dtype})"
        )

        # 尝试传递 is_distilled 参数;如果当前 diffusers 版本不支持该参数,降级处理
        try:
            self._pipe = Flux2KleinPipeline.from_pretrained(
                hf_path,
                torch_dtype=self._dtype,
                is_distilled=self._is_distilled,
            ).to(self._device)
        except TypeError:
            # is_distilled 参数不被支持,降级为无参数加载
            logger.warning(
                f"[{self.model_id}] is_distilled parameter not supported by "
                f"Flux2KleinPipeline.from_pretrained(), loading without it"
            )
            self._pipe = Flux2KleinPipeline.from_pretrained(
                hf_path,
                torch_dtype=self._dtype,
            ).to(self._device)

        self._loaded = True

        # 加载之前注册的 LoRA
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
        """加载在模型加载前注册的 LoRA。"""
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
    # 参数解析辅助方法
    # ------------------------------------------------------------------

    def _validate_dimensions(self, width: int, height: int) -> tuple[int, int]:
        """校验并对齐尺寸为 16 的倍数。"""
        width = max(MIN_RESOLUTION, min(MAX_RESOLUTION, width))
        height = max(MIN_RESOLUTION, min(MAX_RESOLUTION, height))
        width = (width // FLUX_SIZE_ALIGNMENT) * FLUX_SIZE_ALIGNMENT
        height = (height // FLUX_SIZE_ALIGNMENT) * FLUX_SIZE_ALIGNMENT
        return width, height

    def _parse_dimensions(self, params: dict) -> tuple[int, int]:
        """从参数中解析尺寸 (支持 ratio 或 width/height)。"""
        ratio = params.get("ratio")
        if ratio:
            family = ARCHITECTURE_RATIO_FAMILY.get(
                self.model_config.get("architecture", "flux2klein"), "flux"
            )
            ratios = RATIO_MAPPINGS.get(family, {})
            if ratio in ratios:
                w, h = ratios[ratio]["width"], ratios[ratio]["height"]
                return self._validate_dimensions(w, h)

        width = params.get("width", 1024)
        height = params.get("height", 1024)
        return self._validate_dimensions(width, height)

    def _get_inference_params(self, params: dict) -> tuple[int, float]:
        """
        从参数中解析推理参数 (步数 / guidance)。

        distilled 版本参数锁定 (steps=4, cfg=1.0)。
        base 版本参数可调。

        Returns:
            (num_inference_steps, guidance_scale)
        """
        defaults = self.get_default_params()
        ranges = self.get_param_ranges()

        steps = params.get(
            "num_inference_steps", defaults.get("num_inference_steps", 4)
        )
        guidance = params.get(
            "guidance_scale", defaults.get("guidance_scale", 1.0)
        )

        # 如果步数被锁定,强制使用默认值
        steps_range = ranges.get("num_inference_steps", {})
        if steps_range.get("locked", False):
            steps = defaults.get("num_inference_steps", steps)
        else:
            steps = max(
                steps_range.get("min", 1),
                min(steps_range.get("max", 100), steps),
            )

        guidance_range = ranges.get("guidance_scale", {})
        if guidance_range.get("locked", False):
            guidance = defaults.get("guidance_scale", guidance)
        else:
            guidance = max(
                guidance_range.get("min", 0.0),
                min(guidance_range.get("max", 20.0), guidance),
            )

        return int(steps), float(guidance)

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
        """获取 negative prompt (用户自定义优先)。"""
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

    def _generate_with_negative_fallback(
        self, kwargs: dict, negative_prompt: Optional[str]
    ):
        """
        执行生成,对 negative_prompt 做容错处理。

        Flux2Klein 可能不支持 negative_prompt 字符串 (使用 negative_prompt_embeds)。
        先尝试传字符串,如果报错则忽略 negative_prompt 重试。

        Args:
            kwargs: 生成参数 (不含 negative_prompt)
            negative_prompt: 负面提示字符串

        Returns:
            pipeline 调用结果
        """
        if negative_prompt:
            kwargs_with_neg = dict(kwargs)
            kwargs_with_neg["negative_prompt"] = negative_prompt
            try:
                return self._pipe(**kwargs_with_neg)
            except Exception as e:
                err_msg = str(e).lower()
                if "negative" in err_msg or "unexpected keyword" in err_msg:
                    logger.warning(
                        f"[{self.model_id}] negative_prompt not supported "
                        f"as string, retrying without it: {e}"
                    )
                    return self._pipe(**kwargs)
                raise
        return self._pipe(**kwargs)

    # ------------------------------------------------------------------
    # 文生图
    # ------------------------------------------------------------------

    def generate_from_text(self, prompt: str, **params) -> Image.Image:
        """
        文生图: 文字提示 -> 生成图片。

        Flux2Klein 统一管线:不传 image 参数即为文生图。

        Args:
            prompt: 文字提示 (非空)
            **params: 可选参数:
                - width / height / ratio: 尺寸控制
                - num_inference_steps (int): 推理步数 (distilled 锁定为 4)
                - guidance_scale (float): 引导尺度 (distilled 锁定为 1.0)
                - seed (int): 随机种子
                - style (str): 风格预设 key
                - negative_prompt (str): 负面提示 (可能不支持)

        Returns:
            PIL.Image.Image: 生成的图片

        Raises:
            RuntimeError: 模型未加载或生成失败
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
        steps, guidance = self._get_inference_params(params)
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
        if seed is not None:
            kwargs["generator"] = self._get_generator(seed)

        logger.info(
            f"[{self.model_id}] text2img: size={width}x{height}, "
            f"steps={steps}, cfg={guidance}, "
            f"prompt='{full_prompt[:80]}...'"
        )

        start = time.time()
        try:
            result = self._generate_with_negative_fallback(
                kwargs, negative_prompt
            )
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
    # 图生图 (图像编辑,无 strength 参数)
    # ------------------------------------------------------------------

    def generate_from_image(
        self, image: Image.Image, prompt: str, **params
    ) -> Image.Image:
        """
        图生图: 参考图片 + 文字提示 -> 图像编辑。

        Flux2Klein 统一管线:传 image 参数即为图像编辑。
        注意: Flux2Klein 图像编辑没有 strength 参数,通过 image 作为参考条件。

        Args:
            image: 参考图片 (PIL Image)
            prompt: 编辑提示
            **params: 可选参数:
                - width / height / ratio: 尺寸控制 (图片会缩放到此尺寸)
                - num_inference_steps (int): 推理步数
                - guidance_scale (float): 引导尺度
                - seed (int): 随机种子
                - style (str): 风格预设 key
                - negative_prompt (str): 负面提示 (可能不支持)

        Returns:
            PIL.Image.Image: 生成的图片

        Raises:
            RuntimeError: 模型未加载或生成失败
        """
        if not self._loaded or self._pipe is None:
            raise RuntimeError(
                f"Model '{self.model_id}' is not loaded. Call load() first."
            )

        width, height = self._parse_dimensions(params)
        steps, guidance = self._get_inference_params(params)
        style = params.get("style")
        seed = params.get("seed")
        negative_prompt = self._get_negative_prompt(params)

        full_prompt = self._apply_style(prompt, style)

        # 缩放输入图片到目标尺寸 (16 的倍数)
        image = image.convert("RGB").resize((width, height), _LANCZOS)

        # Flux2Klein 统一管线:传 image = 图像编辑 (无 strength)
        kwargs: dict = {
            "prompt": full_prompt,
            "image": image,
            "num_inference_steps": steps,
            "guidance_scale": guidance,
        }
        if seed is not None:
            kwargs["generator"] = self._get_generator(seed)

        logger.info(
            f"[{self.model_id}] img2img (edit): size={width}x{height}, "
            f"steps={steps}, cfg={guidance}"
        )

        start = time.time()
        try:
            result = self._generate_with_negative_fallback(
                kwargs, negative_prompt
            )
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
    # LoRA 管理 (覆盖基类)
    # ------------------------------------------------------------------

    def load_lora(
        self,
        lora_path: str,
        weight: float = 0.8,
        lora_id: Optional[str] = None,
    ) -> str:
        """
        加载 LoRA 适配器。

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
        卸载 LoRA 适配器。

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
