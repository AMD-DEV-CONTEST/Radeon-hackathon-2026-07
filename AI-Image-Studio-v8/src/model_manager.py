# -*- coding: utf-8 -*-
"""Model hub for AI-Image-Studio v2: SDXL pipelines, ControlNet, BiRefNet, LaMa.

- Lazy loading; models stay resident (48 GB VRAM) unless low_vram is on.
- SDXL base is shared between txt2img and img2img via from_pipe (one copy).
- LCM-LoRA turbo: scheduler swap + adapter enable/disable.
"""
from __future__ import annotations

import torch

from .device import DeviceInfo, optimize_pipeline

_ORIG_SCHED = "_v2_orig_scheduler"
_LCM_LOADED = "_v2_lcm_loaded"


class ModelManager:
    def __init__(self, info: DeviceInfo, settings):
        self.info = info
        self.settings = settings
        self._loaded = {}

    # ---------------------------------------------------------- helpers
    def _keep(self, key: str, model):
        self._loaded[key] = model
        return model

    def loaded_models(self) -> list[str]:
        return list(self._loaded.keys())

    def unload_all(self) -> None:
        self._loaded.clear()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    # --------------------------------------------------- SDXL inpainting
    def get_inpaint_pipe(self):
        if "inpaint" in self._loaded:
            return self._loaded["inpaint"]
        from diffusers import StableDiffusionXLInpaintPipeline
        pipe = StableDiffusionXLInpaintPipeline.from_pretrained(
            self.settings.sdxl_inpaint_id,
            torch_dtype=self.info.dtype,
            variant="fp16",
            use_safetensors=True,
        )
        pipe = optimize_pipeline(pipe, self.info, self.settings.low_vram)
        return self._keep("inpaint", pipe)

    # -------------------------------------- SDXL base (txt2img / img2img)
    def get_txt2img_pipe(self):
        if "txt2img" in self._loaded:
            return self._loaded["txt2img"]
        from diffusers import StableDiffusionXLPipeline
        pipe = StableDiffusionXLPipeline.from_pretrained(
            self.settings.sdxl_model_id,
            torch_dtype=self.info.dtype,
            variant="fp16",
            use_safetensors=True,
        )
        pipe = optimize_pipeline(pipe, self.info, self.settings.low_vram)
        return self._keep("txt2img", pipe)

    def get_img2img_pipe(self):
        if "img2img" in self._loaded:
            return self._loaded["img2img"]
        from diffusers import StableDiffusionXLImg2ImgPipeline
        pipe = StableDiffusionXLImg2ImgPipeline.from_pipe(self.get_txt2img_pipe())
        return self._keep("img2img", pipe)

    # --------------------------------- ControlNet (structure-locked style)
    def get_controlnet_img2img_pipe(self):
        if "cn_img2img" in self._loaded:
            return self._loaded["cn_img2img"]
        from diffusers import (ControlNetModel,
                               StableDiffusionXLControlNetImg2ImgPipeline)
        controlnet = ControlNetModel.from_pretrained(
            self.settings.controlnet_id,
            torch_dtype=self.info.dtype,
            variant="fp16",
            use_safetensors=True,
        )
        base = self.get_txt2img_pipe()
        pipe = StableDiffusionXLControlNetImg2ImgPipeline(
            vae=base.vae, text_encoder=base.text_encoder,
            text_encoder_2=base.text_encoder_2, tokenizer=base.tokenizer,
            tokenizer_2=base.tokenizer_2, unet=base.unet,
            controlnet=controlnet, scheduler=base.scheduler,
            force_zeros_for_empty_prompt=True,
        )
        pipe = optimize_pipeline(pipe, self.info, self.settings.low_vram)
        return self._keep("cn_img2img", pipe)

    # ------------------------------------------------------- LCM turbo
    def ensure_dtypes(self, pipe) -> None:
        """Cast shared components back to the runtime dtype when drifted.

        diffusers/PEFT internals can upcast the SHARED UNet to float32 during
        an img2img call. The next ControlNet run then mixes fp32 activations
        with fp16 weights and dies with "mat1 and mat2 must have the same
        dtype" — and even before crashing, fp32 compute runs ~2-3x slower.
        Every pipeline entry calls set_lcm(), so this is the chokepoint.
        """
        dt = self.info.dtype
        for name in ("unet", "controlnet", "text_encoder", "text_encoder_2"):
            m = getattr(pipe, name, None)
            if m is not None and getattr(m, "dtype", dt) != dt:
                m.to(dt)

    def set_lcm(self, pipe, fast: bool) -> None:
        """Toggle LCM-LoRA turbo mode on a pipeline (SDXL).

        txt2img / img2img / ControlNet pipes share ONE UNet (and the LoRA
        adapter lives in that UNet), so the loaded-state flag must be tracked
        on ``pipe.unet`` — a per-pipe flag double-loads the adapter
        (ValueError: adapter name already in use) and lets the enabled state
        leak into other pipes' standard-sampler runs.
        """
        s = self.settings
        self.ensure_dtypes(pipe)
        if not s.enable_lcm:
            return
        anchor = getattr(pipe, "unet", None) or pipe  # shared-UNet aware
        if fast:
            if not getattr(pipe, _ORIG_SCHED, None):
                pipe._v2_orig_scheduler = (type(pipe.scheduler), dict(pipe.scheduler.config))
            if not getattr(anchor, _LCM_LOADED, False):
                from diffusers import LCMScheduler
                try:
                    pipe.load_lora_weights(s.lcm_lora_id, adapter_name="lcm")
                except ValueError as e:
                    if "already in use" not in str(e):
                        raise
                anchor._v2_lcm_loaded = True
            if type(pipe.scheduler).__name__ != "LCMScheduler":
                from diffusers import LCMScheduler
                pipe.scheduler = LCMScheduler.from_config(pipe.scheduler.config)
            pipe.set_adapters(["lcm"], [1.0])
        else:
            if getattr(anchor, _LCM_LOADED, False):
                pipe.disable_lora()  # acts on the shared UNet: always enforce
            saved = getattr(pipe, _ORIG_SCHED, None)
            if saved and type(pipe.scheduler).__name__ == "LCMScheduler":
                cls, cfg = saved
                pipe.scheduler = cls.from_config(cfg)

    # ------------------------------------------------------------ BiRefNet
    def get_birefnet(self):
        if "birefnet" in self._loaded:
            return self._loaded["birefnet"]
        from transformers import AutoModelForImageSegmentation
        # Explicit dtype: transformers "auto" would keep the fp16 checkpoint
        # dtype even on CPU, causing float/half conv mismatches.
        model = AutoModelForImageSegmentation.from_pretrained(
            self.settings.birefnet_model_id, trust_remote_code=True,
            torch_dtype=self.info.dtype if self.info.is_gpu else torch.float32)
        model = model.to(self.info.device).eval()
        return self._keep("birefnet", model)

    # ------------------------------------------------- intent LLM (Qwen)
    def get_llm(self):
        """Small instruct LLM for the intent layer (lazy, resident)."""
        if "intent_llm" in self._loaded:
            return self._loaded["intent_llm"]
        from transformers import AutoModelForCausalLM, AutoTokenizer
        tok = AutoTokenizer.from_pretrained(self.settings.intent_model_id)
        model = AutoModelForCausalLM.from_pretrained(
            self.settings.intent_model_id,
            torch_dtype=self.info.dtype if self.info.is_gpu else torch.float32)
        model = model.to(self.info.device).eval()
        return self._keep("intent_llm", (tok, model))

    # --------------------------------------------------------------- LaMa
    def get_lama(self):
        if "lama" in self._loaded:
            return self._loaded["lama"]
        import os
        from simple_lama_inpainting import SimpleLama
        path = self.settings.lama_model_path
        if os.path.exists(path):
            os.environ["LAMA_MODEL"] = os.path.abspath(path)
        # SimpleLama.__init__ calls torch.jit.load WITHOUT map_location, which
        # crashes on machines where the archive's recorded device is missing
        # (e.g. CPU-only). Build the object manually with an explicit map_location.
        model_path = os.environ.get("LAMA_MODEL")
        if model_path:
            lama = SimpleLama.__new__(SimpleLama)
            lama.model = torch.jit.load(model_path, map_location=self.info.device)
            lama.model.eval()
            lama.model.to(self.info.device)
            lama.device = self.info.device
        else:
            lama = SimpleLama(device=self.info.device)
        return self._keep("lama", lama)
