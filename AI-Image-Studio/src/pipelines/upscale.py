# -*- coding: utf-8 -*-
"""超分辨率：Real-ESRGAN 权重的纯 PyTorch 推理实现。

- 不依赖 basicsr 编译包，在 ROCm/CUDA/CPU 上行为一致；
- 支持两种权重：RealESRGAN_x4plus（RRDBNet，高画质）、RealESR-general-x4v3（SRVGGNetCompact，轻量高速）；
- 支持分块（tile）推理，大图低显存友好。
"""
from __future__ import annotations

import math
import os

import torch
import torch.nn as nn
import torch.nn.functional as F
from PIL import Image

from ..device import DeviceInfo, Timer, peak_memory_gb, reset_peak_memory


# --------------------------- 网络结构 ---------------------------

class ResidualDenseBlock(nn.Module):
    def __init__(self, num_feat: int = 64, num_grow_ch: int = 32):
        super().__init__()
        self.conv1 = nn.Conv2d(num_feat, num_grow_ch, 3, 1, 1)
        self.conv2 = nn.Conv2d(num_feat + num_grow_ch, num_grow_ch, 3, 1, 1)
        self.conv3 = nn.Conv2d(num_feat + 2 * num_grow_ch, num_grow_ch, 3, 1, 1)
        self.conv4 = nn.Conv2d(num_feat + 3 * num_grow_ch, num_grow_ch, 3, 1, 1)
        self.conv5 = nn.Conv2d(num_feat + 4 * num_grow_ch, num_feat, 3, 1, 1)
        self.lrelu = nn.LeakyReLU(negative_slope=0.2, inplace=True)

    def forward(self, x):
        x1 = self.lrelu(self.conv1(x))
        x2 = self.lrelu(self.conv2(torch.cat((x, x1), 1)))
        x3 = self.lrelu(self.conv3(torch.cat((x, x1, x2), 1)))
        x4 = self.lrelu(self.conv4(torch.cat((x, x1, x2, x3), 1)))
        x5 = self.conv5(torch.cat((x, x1, x2, x3, x4), 1))
        return x5 * 0.2 + x


class RRDB(nn.Module):
    def __init__(self, num_feat: int, num_grow_ch: int = 32):
        super().__init__()
        self.rdb1 = ResidualDenseBlock(num_feat, num_grow_ch)
        self.rdb2 = ResidualDenseBlock(num_feat, num_grow_ch)
        self.rdb3 = ResidualDenseBlock(num_feat, num_grow_ch)

    def forward(self, x):
        out = self.rdb3(self.rdb2(self.rdb1(x)))
        return out * 0.2 + x


class RRDBNet(nn.Module):
    """ESRGAN 生成器（RealESRGAN_x4plus / x2plus 同款结构）。"""

    def __init__(self, num_in_ch=3, num_out_ch=3, scale=4, num_feat=64, num_block=23, num_grow_ch=32):
        super().__init__()
        self.scale = scale
        self.conv_first = nn.Conv2d(num_in_ch, num_feat, 3, 1, 1)
        self.body = nn.Sequential(*[RRDB(num_feat, num_grow_ch) for _ in range(num_block)])
        self.conv_body = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
        # upsample
        self.conv_up1 = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
        self.conv_up2 = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
        self.conv_hr = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
        self.conv_last = nn.Conv2d(num_feat, num_out_ch, 3, 1, 1)
        self.lrelu = nn.LeakyReLU(negative_slope=0.2, inplace=True)

    def forward(self, x):
        feat = self.conv_first(x)
        body_feat = self.conv_body(self.body(feat))
        feat = feat + body_feat
        feat = self.lrelu(self.conv_up1(F.interpolate(feat, scale_factor=2, mode="nearest")))
        feat = self.lrelu(self.conv_up2(F.interpolate(feat, scale_factor=2, mode="nearest")))
        out = self.conv_last(self.lrelu(self.conv_hr(feat)))
        return out


class SRVGGNetCompact(nn.Module):
    """RealESR-general-x4v3 轻量网络：体积小、速度快，适合实时批量场景。"""

    def __init__(self, num_in_ch=3, num_out_ch=3, num_feat=64, num_conv=16, upscale=4, act_type="prelu"):
        super().__init__()
        self.num_in_ch = num_in_ch
        self.num_out_ch = num_out_ch
        self.num_feat = num_feat
        self.num_conv = num_conv
        self.upscale = upscale
        self.act_type = act_type

        self.conv1 = nn.Conv2d(num_in_ch, num_feat, 3, 1, 1)
        body_convs = []
        for _ in range(num_conv):
            body_convs.append(nn.Conv2d(num_feat, num_feat, 3, 1, 1))
        self.body = nn.ModuleList(body_convs)
        self.conv2 = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
        self.upsampler = nn.Conv2d(num_feat, num_out_ch * upscale * upscale, 3, 1, 1)
        self.pixel_shuffle = nn.PixelShuffle(upscale)
        self.lrelu = nn.PReLU(num_parameters=num_feat)

    def forward(self, x):
        out = self.lrelu(self.conv1(x))
        for conv in self.body:
            out = self.lrelu(conv(out))
        out = self.conv2(out)
        out = self.upsampler(out)
        out = self.pixel_shuffle(out)
        return out


# --------------------------- 推理封装 ---------------------------

class TorchUpscaler:
    """加载 Real-ESRGAN 权重并执行（可选分块的）超分推理。"""

    def __init__(self, weight_path: str, info: DeviceInfo, tile: int = 0):
        self.info = info
        self.weight_path = weight_path
        state = torch.load(weight_path, map_location="cpu", weights_only=True)
        if "params_ema" in state:
            state = state["params_ema"]
        elif "params" in state:
            state = state["params"]

        if any(k.startswith("conv_up1") for k in state):
            model = RRDBNet(3, 3, scale=4, num_feat=64, num_block=23, num_grow_ch=32)
        else:
            model = SRVGGNetCompact(3, 3, num_feat=64, num_conv=16, upscale=4)
        model.load_state_dict(state, strict=True)
        self.model = model.to(info.device, info.dtype).eval()
        self.native_scale = 4
        self.tile = tile  # 0 = 不分块；GPU 上默认在外层按需要设置

    @torch.inference_mode()
    def upscale_tensor(self, img_t: torch.Tensor) -> torch.Tensor:
        """img_t: (1,3,H,W) in [0,1]"""
        if self.tile and self.info.device.type == "cuda":
            return self._tiled_forward(img_t)
        return self.model(img_t.to(self.info.device, self.info.dtype))

    def _tiled_forward(self, img_t: torch.Tensor, tile: int | None = None, pad: int = 16) -> torch.Tensor:
        """分块推理 + 重叠区域线性混合，避免拼缝。"""
        tile = tile or self.tile
        b, c, h, w = img_t.shape
        s = self.native_scale
        out = torch.zeros((b, 3, h * s, w * s), device=img_t.device, dtype=self.info.dtype)
        weight = torch.zeros_like(out)
        step = tile - 2 * pad
        for y in range(0, h, step):
            for x in range(0, w, step):
                y1, x1 = max(0, y - pad), max(0, x - pad)
                y2, x2 = min(h, y + step + pad), min(w, x + step + pad)
                patch = img_t[..., y1:y2, x1:x2].to(self.info.device, self.info.dtype)
                pred = self.model(patch)
                oy1, ox1, oy2, ox2 = y1 * s, x1 * s, y2 * s, x2 * s
                out[..., oy1:oy2, ox1:ox2] += pred
                weight[..., oy1:oy2, ox1:ox2] += 1.0
        return out / weight.clamp(min=1e-8)

    @torch.inference_mode()
    def upscale_image(self, img: Image.Image, target_scale: float = 4.0) -> Image.Image:
        """输入 PIL 图，输出放大 target_scale 倍的 PIL 图（内部 x4 后重采样到目标倍率）。"""
        import numpy as np
        arr = torch.from_numpy(np.array(img.convert("RGB"))).permute(2, 0, 1).float().div_(255.0).unsqueeze(0)
        out = self.upscale_tensor(arr)
        out = out.float().clamp_(0, 1).squeeze(0).permute(1, 2, 0).cpu().numpy()
        result = Image.fromarray((out * 255.0).round().astype("uint8"), "RGB")
        if abs(target_scale - self.native_scale) > 1e-6:
            tw = max(1, int(round(img.width * target_scale)))
            th = max(1, int(round(img.height * target_scale)))
            result = result.resize((tw, th), Image.LANCZOS)
        return result


def run_upscale(manager, image: Image.Image, quality: str = "fast",
                target_scale: float = 4.0, tile: int = 0):
    """执行超分，返回 (结果图, 性能信息 dict)。"""
    upscaler = manager.get_upscaler(quality)
    if tile:
        upscaler.tile = tile
    reset_peak_memory()
    with Timer() as t:
        result = upscaler.upscale_image(image, target_scale)
    return result, {
        "耗时": f"{t.elapsed:.2f} s",
        "峰值显存": f"{peak_memory_gb():.2f} GB" if manager.info.device.type == "cuda" else "CPU 推理",
        "输出尺寸": f"{result.width}×{result.height}",
        "模型": os.path.basename(getattr(upscaler, "weight_path", quality)),
    }
