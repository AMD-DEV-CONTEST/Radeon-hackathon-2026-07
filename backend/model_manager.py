"""
ModelManager — 模型管理器单例

负责:
    - 模型加载/卸载/切换 (带回滚保护)
    - 文生图 / 图生图调度 (线程安全,同一时刻只允许一个生成任务)
    - LoRA 管理 (委托给当前 adapter)
    - GPU 状态查询
    - 模型注册表查询

线程安全设计:
    - _generation_lock : 生成任务互斥锁,同一时刻只允许一个生成任务
    - _switch_lock     : 模型切换互斥锁,防止并发切换
    - switch_model 同时获取两把锁,确保切换期间不会有生成任务运行

模型切换保护机制 (switch_model):
    1. 获取 _switch_lock + _generation_lock
    2. 保存旧 adapter 引用和 LoRA 状态
    3. 卸载旧模型 (adapter.unload 内部含 gc + empty_cache)
    4. 检查可用显存 (torch.cuda.mem_get_info)
    5. 创建新 adapter 并 load()
    6. 如果加载失败,回滚到旧模型 (重新 load 旧 adapter)
    7. 恢复兼容的 LoRA
"""

import logging
import threading
from typing import Optional

from PIL import Image

from config import (
    MODEL_REGISTRY,
    STYLE_PRESETS,
    RATIO_MAPPINGS,
    ARCHITECTURE_RATIO_FAMILY,
    LICENSE_INFO,
    DEFAULT_FAST_MODEL_ID,
)
from adapters import ADAPTER_REGISTRY

logger = logging.getLogger("model_manager")


class ModelManager:
    """
    模型管理器单例。

    通过 switch_model() 切换模型,通过 generate_from_text() /
    generate_from_image() 执行生成任务。所有操作线程安全。

    用法:
        manager = ModelManager()
        manager.switch_model("sdxl_lightning_4step")
        image = manager.generate_from_text("a cat", style="anime")
    """

    _instance: Optional["ModelManager"] = None

    def __new__(cls) -> "ModelManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        # 当前状态
        self._current_adapter = None
        self._current_mode: Optional[str] = None
        self._current_model_id: Optional[str] = None

        # 线程锁
        self._generation_lock = threading.Lock()
        self._switch_lock = threading.Lock()

        logger.info("ModelManager initialized (singleton)")

    # ------------------------------------------------------------------
    # 模型查询
    # ------------------------------------------------------------------

    def get_model_config(self, model_id: str) -> Optional[dict]:
        """
        获取模型配置。

        Args:
            model_id: 模型唯一标识

        Returns:
            模型配置字典,不存在时返回 None
        """
        return MODEL_REGISTRY.get(model_id)

    def get_available_models(self, mode: Optional[str] = None) -> list[dict]:
        """
        获取可用模型列表,可选按模式筛选。

        Args:
            mode: "fast" / "expert",或 None 返回全部

        Returns:
            模型配置列表 (含许可证信息)
        """
        models: list[dict] = []
        for model_id, config in MODEL_REGISTRY.items():
            if mode is None or config.get("mode") == mode:
                model_info = dict(config)
                # 附加许可证详情
                license_key = config.get("license", "")
                model_info["license_info"] = LICENSE_INFO.get(license_key, {})
                models.append(model_info)
        return models

    def get_current_model_info(self) -> dict:
        """
        获取当前模型信息。

        Returns:
            包含模型 ID、模式、加载状态、能力、参数等信息的字典。
            如果没有加载模型,返回 unloaded 状态。
        """
        if self._current_adapter is None:
            return {
                "loaded": False,
                "model_id": None,
                "mode": None,
                "name": None,
            }

        config = self.get_model_config(self._current_model_id) or {}
        return {
            "loaded": self._current_adapter.is_loaded(),
            "model_id": self._current_model_id,
            "mode": self._current_mode,
            "name": config.get("name"),
            "architecture": config.get("architecture"),
            "supports_img2img": self._current_adapter.supports_img2img(),
            "supports_strength": self._current_adapter.supports_strength_control(),
            "supports_lora": self._current_adapter.supports_lora(),
            "default_params": self._current_adapter.get_default_params(),
            "param_ranges": self._current_adapter.get_param_ranges(),
            "supported_ratios": self._current_adapter.get_supported_ratios(),
            "loaded_loras": self._current_adapter.get_loaded_loras(),
        }

    def get_available_ratios(self) -> list[dict]:
        """
        获取当前模型支持的可用比例列表。

        Returns:
            比例信息字典列表,每项含 ratio / width / height / recommended。
            如果没有加载模型,返回空列表。
        """
        if self._current_model_id is None:
            return []

        config = self.get_model_config(self._current_model_id)
        if config is None:
            return []

        family = ARCHITECTURE_RATIO_FAMILY.get(
            config.get("architecture", ""), ""
        )
        ratios = RATIO_MAPPINGS.get(family, {})
        supported = config.get("supported_ratios", [])

        return [ratios[r] for r in supported if r in ratios]

    def get_styles(self) -> dict:
        """返回可用的风格预设。"""
        return STYLE_PRESETS

    def is_loaded(self) -> bool:
        """检查当前是否有模型已加载。"""
        return (
            self._current_adapter is not None
            and self._current_adapter.is_loaded()
        )

    def load_default(self) -> dict:
        """
        加载默认快速模型 (SDXL-Lightning 4-step)。

        启动时由 FluxEngine.load() 调用。如果已有模型加载则跳过。

        Returns:
            当前模型信息 (get_current_model_info() 结果)
        """
        if self.is_loaded():
            logger.info("Default model already loaded, skipping")
            return self.get_current_model_info()
        logger.info(f"Loading default model: {DEFAULT_FAST_MODEL_ID}")
        return self.switch_model(DEFAULT_FAST_MODEL_ID)

    # ------------------------------------------------------------------
    # 模型切换 (带回滚保护)
    # ------------------------------------------------------------------

    def switch_model(self, model_id: str) -> dict:
        """
        切换到指定模型。

        流程 (审核报告要求):
            1. 获取 _switch_lock + _generation_lock (防止切换期间有生成任务)
            2. 保存旧 adapter 引用和 LoRA 状态
            3. 卸载旧模型 (adapter.unload 内部含 gc + empty_cache)
            4. 检查可用显存
            5. 创建新 adapter 并 load()
            6. 如果加载失败,回滚到旧模型
            7. 恢复兼容的 LoRA

        Args:
            model_id: 目标模型 ID

        Returns:
            当前模型信息 (get_current_model_info() 结果)

        Raises:
            ValueError: 未知的模型 ID
            RuntimeError: 切换失败 (显存不足 / 加载失败 / 回滚也失败)
        """
        with self._switch_lock:
            with self._generation_lock:
                return self._do_switch(model_id)

    def _do_switch(self, model_id: str) -> dict:
        """switch_model 的内部实现 (在锁保护下执行)。"""

        # 如果是同一个模型且已加载,跳过
        if (
            model_id == self._current_model_id
            and self._current_adapter is not None
            and self._current_adapter.is_loaded()
        ):
            logger.info(f"Model '{model_id}' is already loaded, skipping switch")
            return self.get_current_model_info()

        # 获取新模型配置
        new_config = self.get_model_config(model_id)
        if new_config is None:
            raise ValueError(
                f"Unknown model: '{model_id}'. "
                f"Available: {list(MODEL_REGISTRY.keys())}"
            )

        # 保存旧状态 (用于回滚)
        old_adapter = self._current_adapter
        old_model_id = self._current_model_id
        old_loras: dict = {}
        if old_adapter is not None:
            old_loras = old_adapter.get_loaded_loras()

        # 步骤 3: 卸载旧模型
        if old_adapter is not None:
            logger.info(f"Unloading current model: '{old_model_id}'")
            old_adapter.unload()

        # 步骤 4: 检查可用显存
        vram_ok, vram_error = self._check_vram(new_config)
        if not vram_ok:
            logger.error(f"VRAM check failed: {vram_error}")
            # 回滚到旧模型
            self._rollback(old_adapter, old_model_id, old_loras)
            raise RuntimeError(vram_error)

        # 步骤 5: 创建新 adapter 并加载
        architecture = new_config.get("architecture")
        adapter_class = ADAPTER_REGISTRY.get(architecture)
        if adapter_class is None:
            error_msg = f"Unsupported architecture: '{architecture}'"
            logger.error(error_msg)
            self._rollback(old_adapter, old_model_id, old_loras)
            raise ValueError(error_msg)

        logger.info(
            f"Switching to model '{model_id}' "
            f"(architecture={architecture}, mode={new_config.get('mode')})"
        )

        new_adapter = adapter_class(model_id, new_config)
        try:
            new_adapter.load()
        except Exception as e:
            logger.error(f"Failed to load model '{model_id}': {e}", exc_info=True)
            # 清理可能部分加载的资源
            new_adapter.unload()
            # 回滚到旧模型
            self._rollback(old_adapter, old_model_id, old_loras)
            raise RuntimeError(
                f"Failed to load model '{model_id}': {e}. "
                f"Rolled back to previous model."
            ) from e

        # 步骤 7: 恢复兼容的 LoRA
        if old_loras:
            restored_count = 0
            for lora_id, lora_info in old_loras.items():
                try:
                    new_adapter.load_lora(
                        lora_info["path"],
                        lora_info["weight"],
                        lora_id,
                    )
                    restored_count += 1
                except Exception as e:
                    logger.warning(
                        f"Could not restore LoRA '{lora_id}' on new model "
                        f"(incompatible?): {e}"
                    )
            if restored_count:
                logger.info(
                    f"Restored {restored_count}/{len(old_loras)} LoRA(s)"
                )

        # 更新当前状态
        self._current_adapter = new_adapter
        self._current_model_id = model_id
        self._current_mode = new_config.get("mode")

        logger.info(
            f"Successfully switched to '{model_id}' "
            f"(mode={self._current_mode})"
        )
        return self.get_current_model_info()

    def _check_vram(self, model_config: dict) -> tuple[bool, Optional[str]]:
        """
        检查可用显存是否足够加载目标模型。

        Args:
            model_config: 目标模型配置

        Returns:
            (ok, error_message): ok=True 表示显存足够;
            ok=False 时 error_message 包含错误描述
        """
        try:
            import torch
            if not torch.cuda.is_available():
                logger.warning(
                    "CUDA/ROCm not available, skipping VRAM check"
                )
                return True, None

            free_vram, total_vram = torch.cuda.mem_get_info()
            free_vram_gb = free_vram / 1e9
            required_vram = model_config.get("vram_gb", 8)

            # 留 1GB 缓冲给系统和其他进程
            if free_vram_gb < required_vram + 1:
                error_msg = (
                    f"Insufficient VRAM: need ~{required_vram}GB (+1GB buffer) "
                    f"for model '{model_config.get('id')}', "
                    f"but only {free_vram_gb:.2f}GB available "
                    f"(total: {total_vram / 1e9:.2f}GB)"
                )
                return False, error_msg

            logger.info(
                f"VRAM check passed: {free_vram_gb:.2f}GB free, "
                f"~{required_vram}GB required"
            )
            return True, None

        except ImportError:
            logger.warning("Could not check VRAM (torch not installed)")
            return True, None
        except Exception as e:
            logger.warning(f"VRAM check error (continuing anyway): {e}")
            return True, None

    def _rollback(
        self,
        old_adapter,
        old_model_id: Optional[str],
        old_loras: dict,
    ) -> None:
        """
        模型切换失败后回滚到旧模型。

        重新加载旧 adapter,并恢复其 LoRA 状态。
        如果回滚也失败,将当前状态置空并记录严重错误。
        """
        if old_adapter is None:
            logger.warning("No previous model to rollback to")
            self._current_adapter = None
            self._current_model_id = None
            self._current_mode = None
            return

        logger.info(f"Rolling back to previous model: '{old_model_id}'")
        try:
            old_adapter.load()

            # 恢复 LoRA
            for lora_id, lora_info in old_loras.items():
                try:
                    old_adapter.load_lora(
                        lora_info["path"],
                        lora_info["weight"],
                        lora_id,
                    )
                except Exception as e:
                    logger.warning(
                        f"Could not restore LoRA '{lora_id}' "
                        f"during rollback: {e}"
                    )

            self._current_adapter = old_adapter
            self._current_model_id = old_model_id
            self._current_mode = old_adapter.model_config.get("mode")
            logger.info(f"Rollback successful: restored '{old_model_id}'")

        except Exception as rollback_e:
            logger.error(
                f"Rollback also failed: {rollback_e}", exc_info=True
            )
            self._current_adapter = None
            self._current_model_id = None
            self._current_mode = None

    # ------------------------------------------------------------------
    # 生成任务 (线程安全)
    # ------------------------------------------------------------------

    def generate_from_text(self, prompt: str, **params) -> Image.Image:
        """
        文生图: 文字提示 -> 生成图片。

        获取 _generation_lock,委托给当前 adapter 执行。
        同一时刻只允许一个生成任务。

        Args:
            prompt: 文字提示
            **params: 生成参数 (width, height, ratio, steps, cfg, seed, style,
                      negative_prompt 等)

        Returns:
            PIL.Image.Image: 生成的图片

        Raises:
            RuntimeError: 没有模型加载或生成失败
            ValueError: 参数无效 (如 prompt 为空)
        """
        with self._generation_lock:
            if not self.is_loaded():
                raise RuntimeError(
                    "No model is currently loaded. "
                    "Please switch to a model first using switch_model()."
                )
            logger.info(
                f"generate_from_text: model='{self._current_model_id}', "
                f"prompt='{prompt[:60]}...'"
            )
            return self._current_adapter.generate_from_text(prompt, **params)

    def generate_from_image(
        self, image: Image.Image, prompt: str, **params
    ) -> Image.Image:
        """
        图生图: 参考图片 + 文字提示 -> 生成图片。

        获取 _generation_lock,委托给当前 adapter 执行。
        同一时刻只允许一个生成任务。

        Args:
            image: 参考图片 (PIL Image)
            prompt: 文字提示
            **params: 生成参数

        Returns:
            PIL.Image.Image: 生成的图片

        Raises:
            RuntimeError: 没有模型加载或生成失败
        """
        with self._generation_lock:
            if not self.is_loaded():
                raise RuntimeError(
                    "No model is currently loaded. "
                    "Please switch to a model first using switch_model()."
                )
            logger.info(
                f"generate_from_image: model='{self._current_model_id}', "
                f"image_size={image.size}, prompt='{prompt[:60]}...'"
            )
            return self._current_adapter.generate_from_image(
                image, prompt, **params
            )

    # ------------------------------------------------------------------
    # LoRA 管理 (委托给当前 adapter)
    # ------------------------------------------------------------------

    def load_lora(
        self,
        lora_path: str,
        weight: float = 0.8,
        lora_id: Optional[str] = None,
    ) -> str:
        """
        加载 LoRA 适配器。

        委托给当前 adapter。如果模型未加载,LoRA 会被注册,在模型加载时恢复。

        Args:
            lora_path: LoRA 文件路径或 HuggingFace repo
            weight: LoRA 权重 (0.0 - 1.0)
            lora_id: LoRA 标识符,为 None 时自动生成

        Returns:
            lora_id: LoRA 标识符

        Raises:
            RuntimeError: 没有当前 adapter 或加载失败
        """
        if self._current_adapter is None:
            raise RuntimeError(
                "No model is currently loaded. "
                "Please switch to a model first."
            )
        return self._current_adapter.load_lora(lora_path, weight, lora_id)

    def unload_lora(self, lora_id: str) -> None:
        """
        卸载 LoRA 适配器。

        Args:
            lora_id: LoRA 标识符

        Raises:
            RuntimeError: 没有当前 adapter
        """
        if self._current_adapter is None:
            raise RuntimeError(
                "No model is currently loaded. "
                "Please switch to a model first."
            )
        self._current_adapter.unload_lora(lora_id)

    def get_loaded_loras(self) -> dict:
        """
        获取当前已加载的 LoRA 列表。

        Returns:
            {lora_id: {"path": str, "weight": float}} 字典,
            如果没有模型加载返回空字典。
        """
        if self._current_adapter is None:
            return {}
        return self._current_adapter.get_loaded_loras()

    # ------------------------------------------------------------------
    # GPU 状态查询
    # ------------------------------------------------------------------

    def get_gpu_info(self) -> dict:
        """
        获取 GPU 状态信息。

        在 ROCm 环境下 torch.cuda API 同样可用。

        Returns:
            GPU 信息字典,包含:
            - available: GPU 是否可用
            - device_name: 设备名称
            - vram_total_gb: 总显存 (GB)
            - vram_free_gb: 可用显存 (GB)
            - vram_allocated_gb: 已分配显存 (GB)
            - vram_reserved_gb: 已保留显存 (GB)
            如果 GPU 不可用,返回 {"available": False}
        """
        try:
            import torch
            if torch.cuda.is_available():
                free_vram, total_vram = torch.cuda.mem_get_info()
                return {
                    "available": True,
                    "device_name": torch.cuda.get_device_name(0),
                    "vram_total_gb": round(total_vram / 1e9, 2),
                    "vram_free_gb": round(free_vram / 1e9, 2),
                    "vram_allocated_gb": round(
                        torch.cuda.memory_allocated() / 1e9, 2
                    ),
                    "vram_reserved_gb": round(
                        torch.cuda.memory_reserved() / 1e9, 2
                    ),
                }
            return {"available": False}
        except ImportError:
            return {"available": False, "error": "torch not installed"}
        except Exception as e:
            return {"available": False, "error": str(e)}

    # ------------------------------------------------------------------
    # 卸载当前模型
    # ------------------------------------------------------------------

    def unload_current(self) -> None:
        """
        卸载当前模型,释放显存。

        获取 _switch_lock + _generation_lock 确保安全卸载。
        """
        with self._switch_lock:
            with self._generation_lock:
                if self._current_adapter is not None:
                    logger.info(
                        f"Unloading current model: '{self._current_model_id}'"
                    )
                    self._current_adapter.unload()
                    self._current_adapter = None
                    self._current_model_id = None
                    self._current_mode = None
                    logger.info("Model unloaded")
                else:
                    logger.info("No model to unload")
