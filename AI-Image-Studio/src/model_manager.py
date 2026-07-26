# -*- coding: utf-8 -*-
"""模型管理器：按需懒加载 + 低显存模式下自动卸载，控制 GPU 显存占用。"""
from __future__ import annotations

import gc
from collections import OrderedDict

import torch

from .device import DeviceInfo, optimize_pipeline


class ModelManager:
    def __init__(self, info: DeviceInfo, settings):
        self.info = info
        self.settings = settings
        self._loaded: "OrderedDict[str, object]" = OrderedDict()

    # ---------------- 内部 ----------------
    def _evict_if_needed(self, keep: str) -> None:
        """低显存模式：加载新模型前卸载其它模型。"""
        if not self.settings.low_vram:
            return
        for name in list(self._loaded.keys()):
            if name != keep:
                self.unload(name)

    def unload(self, name: str) -> None:
        obj = self._loaded.pop(name, None)
        del obj
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def unload_all(self) -> None:
        for name in list(self._loaded.keys()):
            self.unload(name)

    def loaded_models(self):
        return list(self._loaded.keys())

    # ---------------- 扩散模型 ----------------
    def get_inpaint_pipe(self):
        if "inpaint" in self._loaded:
            self._loaded.move_to_end("inpaint")
            return self._loaded["inpaint"]
        self._evict_if_needed("inpaint")
        from diffusers import StableDiffusionInpaintPipeline
        pipe = StableDiffusionInpaintPipeline.from_pretrained(
            self.settings.inpaint_model_id,
            torch_dtype=self.info.dtype,
            safety_checker=None,
            requires_safety_checker=False,
        )
        pipe = optimize_pipeline(pipe, self.info, self.settings.low_vram)
        self._loaded["inpaint"] = pipe
        return pipe

    def get_img2img_pipe(self):
        if "img2img" in self._loaded:
            self._loaded.move_to_end("img2img")
            return self._loaded["img2img"]
        self._evict_if_needed("img2img")
        from diffusers import StableDiffusionImg2ImgPipeline
        pipe = StableDiffusionImg2ImgPipeline.from_pretrained(
            self.settings.img2img_model_id,
            torch_dtype=self.info.dtype,
            safety_checker=None,
            requires_safety_checker=False,
        )
        pipe = optimize_pipeline(pipe, self.info, self.settings.low_vram)
        self._loaded["img2img"] = pipe
        return pipe

    # ---------------- 超分 ----------------
    def get_upscaler(self, quality: str = "fast"):
        """quality: 'fast' (SRVGGNetCompact, 轻量高速) 或 'hq' (RRDBNet, 高画质)"""
        from .pipelines.upscale import TorchUpscaler
        key = f"upscale_{quality}"
        if key in self._loaded:
            self._loaded.move_to_end(key)
            return self._loaded[key]
        self._evict_if_needed(key)
        import os
        weight = (self.settings.esrgan_fast_weight if quality == "fast"
                  else self.settings.esrgan_hq_weight)
        path = os.path.join(self.settings.model_dir, weight)
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"未找到超分权重 {path}，请先运行 python scripts/download_models.py")
        upscaler = TorchUpscaler(path, self.info)
        self._loaded[key] = upscaler
        return upscaler

    # ---------------- 背景移除 ----------------
    def get_bg_remover(self):
        if "birefnet" in self._loaded:
            self._loaded.move_to_end("birefnet")
            return self._loaded["birefnet"]
        self._evict_if_needed("birefnet")
        from transformers import AutoModelForImageSegmentation
        model = AutoModelForImageSegmentation.from_pretrained(
            self.settings.birefnet_model_id,
            trust_remote_code=True,
            torch_dtype=self.info.dtype,
        )
        model = model.to(self.info.device).eval()
        self._loaded["birefnet"] = model
        return model

    # ---------------- LaMa 物体移除 ----------------
    def get_lama(self):
        if "lama" in self._loaded:
            self._loaded.move_to_end("lama")
            return self._loaded["lama"]
        self._evict_if_needed("lama")
        from simple_lama_inpainting import SimpleLama  # 惰性导入，未安装时给出友好提示
        lama = SimpleLama(device=self.info.device)
        self._loaded["lama"] = lama
        return lama

    # ---------------- 文生图（海报） ----------------
    def get_txt2img_pipe(self):
        if "txt2img" in self._loaded:
            self._loaded.move_to_end("txt2img")
            return self._loaded["txt2img"]
        self._evict_if_needed("txt2img")
        from diffusers import StableDiffusionPipeline
        pipe = StableDiffusionPipeline.from_pretrained(
            self.settings.img2img_model_id,  # 与 img2img 共用 SD1.5 底模，零额外下载
            torch_dtype=self.info.dtype,
            safety_checker=None,
            requires_safety_checker=False,
        )
        pipe = optimize_pipeline(pipe, self.info, self.settings.low_vram)
        self._loaded["txt2img"] = pipe
        return pipe

    # ---------------- GFPGAN 人像修复 ----------------
    def get_face_restorer(self):
        if "gfpgan" in self._loaded:
            self._loaded.move_to_end("gfpgan")
            return self._loaded["gfpgan"]
        self._evict_if_needed("gfpgan")
        import os
        from .pipelines.face_restore import FaceRestorer
        gfpgan_path = os.path.join(self.settings.model_dir, self.settings.gfpgan_weight)
        yunet_path = os.path.join(self.settings.model_dir, self.settings.yunet_weight)
        if not os.path.exists(gfpgan_path):
            raise FileNotFoundError(
                f"未找到 GFPGAN 权重 {gfpgan_path}，请先运行 python scripts/download_models.py")
        restorer = FaceRestorer(gfpgan_path, yunet_path, self.info)
        self._loaded["gfpgan"] = restorer
        return restorer
