# -*- coding: utf-8 -*-
"""LoRA 工具：LCM-LoRA 极速模式 + 用户自定义风格 LoRA。

极速模式原理：LCM-LoRA 将扩散采样从 25 步压缩到 4~8 步（低引导），
开启时加载 LoRA 并切换 LCMScheduler，关闭时恢复原始调度器并停用 LoRA。
"""
from __future__ import annotations

import os

_LCM_ATTR = "_aistudio_lcm_loaded"
_ORIG_SCHED_ATTR = "_aistudio_orig_scheduler"
_USER_LORA_ATTR = "_aistudio_user_lora"


def set_lcm(pipe, settings, enabled: bool) -> None:
    """开启/关闭管线的 LCM 极速模式。"""
    if not settings.enable_lcm:
        return
    if enabled:
        if not getattr(pipe, _LCM_ATTR, False):
            # 保存原始调度器以便恢复
            if not getattr(pipe, _ORIG_SCHED_ATTR, None):
                setattr(pipe, _ORIG_SCHED_ATTR, pipe.scheduler)
            pipe.load_lora_weights(settings.lcm_lora_id)
            setattr(pipe, _LCM_ATTR, True)
        from diffusers import LCMScheduler
        if not isinstance(pipe.scheduler, LCMScheduler):
            pipe.scheduler = LCMScheduler.from_config(pipe.scheduler.config)
        pipe.enable_lora()
    else:
        orig = getattr(pipe, _ORIG_SCHED_ATTR, None)
        if orig is not None and getattr(pipe, _LCM_ATTR, False):
            pipe.scheduler = orig
        if getattr(pipe, _LCM_ATTR, False):
            pipe.disable_lora()


def lcm_call_kwargs(settings) -> dict:
    """LCM 模式推荐的推理参数（低引导、少步数）。"""
    return {"num_inference_steps": settings.lcm_steps, "guidance_scale": 1.5}


def apply_user_lora(pipe, lora_ref: str, scale: float = 0.8) -> str:
    """加载/切换用户自定义 LoRA。

    lora_ref: HF 仓库 ID 或本地 .safetensors 文件路径；留空则卸载。
    返回状态描述字符串（用于界面提示）。
    """
    lora_ref = (lora_ref or "").strip()
    current = getattr(pipe, _USER_LORA_ATTR, None)

    if current and current != lora_ref:
        pipe.unload_lora_weights()
        setattr(pipe, _USER_LORA_ATTR, None)
        current = None

    if not lora_ref:
        if current:
            pipe.unload_lora_weights()
            setattr(pipe, _USER_LORA_ATTR, None)
        return "未使用自定义 LoRA"

    if current == lora_ref:
        pipe.set_adapters("style", adapter_weights=[float(scale)])
        return f"LoRA 已生效（权重 {scale:.2f}）"

    if os.path.isfile(lora_ref):
        pipe.load_lora_weights(os.path.dirname(lora_ref) or ".",
                               weight_name=os.path.basename(lora_ref),
                               adapter_name="style")
    else:
        pipe.load_lora_weights(lora_ref, adapter_name="style")
    pipe.set_adapters("style", adapter_weights=[float(scale)])
    setattr(pipe, _USER_LORA_ATTR, lora_ref)
    return f"LoRA 已加载：{lora_ref}（权重 {scale:.2f}）"
