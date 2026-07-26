# -*- coding: utf-8 -*-
"""人像修复增强：YuNet 人脸检测 → 五点对齐 → GFPGAN 修复 → 羽化贴回。

- 检测：OpenCV YuNet（cv2.dnn，无需 onnxruntime），模型约 232KB
- 修复：GFPGAN v1.4（纯 PyTorch 实现，见 gfpgan_arch.py）
- 未检测到人脸时自动回退为整图修复
- 可选联动 Real-ESRGAN 超分：人脸修复后整图再放大
"""
from __future__ import annotations

import os

import cv2
import numpy as np
import torch
from PIL import Image

from ..device import DeviceInfo, Timer, peak_memory_gb, reset_peak_memory
from .gfpgan_arch import GFPGANv1Clean

# 512px 对齐模板（ArcFace 五点模板按比例放大），与 GFPGAN 官方保持一致
_REF_5PTS = np.array([
    [38.2946, 51.6963], [73.5318, 51.5014], [56.0252, 71.7366],
    [41.5493, 92.3655], [70.7299, 92.2041],
], dtype=np.float32) * (512.0 / 112.0)


def _umeyama(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """估计 src→dst 的相似变换（2x3 仿射矩阵），facexlib 同款实现。"""
    src, dst = np.asarray(src, np.float64), np.asarray(dst, np.float64)
    src_mean, dst_mean = src.mean(axis=0), dst.mean(axis=0)
    src_demean, dst_demean = src - src_mean, dst - dst_mean
    A = dst_demean.T @ src_demean / src.shape[0]
    d = np.ones(2)
    if np.linalg.det(A) < 0:
        d[1] = -1
    U, S, Vt = np.linalg.svd(A)
    rot = U @ np.diag(d) @ Vt
    scale = float(S @ d) / float(src_demean.var(axis=0).sum())
    M = np.empty((2, 3), dtype=np.float64)
    M[:, :2] = scale * rot
    M[:, 2] = dst_mean - scale * (rot @ src_mean)
    return M.astype(np.float32)


class FaceRestorer:
    """GFPGAN 人脸修复器（含 YuNet 检测与对齐贴回）。"""

    def __init__(self, gfpgan_path: str, yunet_path: str, info: DeviceInfo):
        self.info = info
        state = torch.load(gfpgan_path, map_location="cpu", weights_only=True)
        state = state.get("params_ema", state)
        model = GFPGANv1Clean(
            out_size=512, num_style_feat=512, channel_multiplier=2,
            decoder_load_path=None, fix_decoder=False, num_mlp=8,
            input_is_latent=True, different_w=True, narrow=1, sft_half=True)
        model.load_state_dict(state, strict=True)
        self.model = model.to(info.device, info.dtype).eval()

        self.detector = None
        if os.path.exists(yunet_path):
            self.detector = cv2.FaceDetectorYN.create(
                yunet_path, "", (320, 320), score_threshold=0.6,
                nms_threshold=0.3, top_k=5000)

    # ---------------- 检测与对齐 ----------------
    def _detect(self, img_rgb: np.ndarray):
        """返回每张脸的 5 点 landmarks（左眼/右眼/鼻/左嘴角/右嘴角）。"""
        if self.detector is None:
            return []
        h, w = img_rgb.shape[:2]
        self.detector.setInputSize((w, h))
        bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
        _, faces = self.detector.detect(bgr)
        if faces is None:
            return []
        results = []
        for f in faces:
            # YuNet 顺序：右眼、左眼、鼻、右嘴角、左嘴角 → 重排为模板顺序
            pts = np.array([[f[2], f[3]], [f[4], f[5]], [f[6], f[7]],
                            [f[8], f[9]], [f[10], f[11]]], dtype=np.float32)
            pts = pts[[1, 0, 2, 4, 3]]
            if f[14] >= 0.6:
                results.append(pts)
        return results

    @torch.inference_mode()
    def _restore_face(self, face_rgb: np.ndarray) -> np.ndarray:
        """对 512×512 对齐人脸执行 GFPGAN 修复。"""
        x = torch.from_numpy(face_rgb.astype(np.float32) / 255.0).permute(2, 0, 1)
        x = (x - 0.5) / 0.5
        x = x.unsqueeze(0).to(self.info.device, self.info.dtype)
        out, _ = self.model(x, return_rgb=False, randomize_noise=False)
        out = out.float().clamp_(-1, 1).squeeze(0).permute(1, 2, 0).cpu().numpy()
        return ((out + 1) / 2 * 255).round().astype(np.uint8)

    def _paste_back(self, img: np.ndarray, restored: np.ndarray,
                    affine: np.ndarray) -> np.ndarray:
        """逆仿射把修复脸贴回原图，边缘羽化融合。"""
        h, w = img.shape[:2]
        inv = cv2.invertAffineTransform(affine)
        warped = cv2.warpAffine(restored, inv, (w, h), flags=cv2.INTER_LINEAR,
                                borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0))
        mask = np.full((512, 512), 255, np.uint8)
        mask = cv2.warpAffine(mask, inv, (w, h), flags=cv2.INTER_LINEAR,
                              borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        k = max(3, min(h, w) // 40)
        mask = cv2.erode(mask, np.ones((k, k), np.uint8))
        mask = cv2.GaussianBlur(mask, (k * 2 + 1, k * 2 + 1), 0)
        alpha = (mask.astype(np.float32) / 255.0)[..., None]
        return (warped.astype(np.float32) * alpha + img.astype(np.float32) * (1 - alpha)).round().astype(np.uint8)

    @torch.inference_mode()
    def restore(self, image: Image.Image) -> tuple[Image.Image, int]:
        """修复图中全部人脸。返回 (结果图, 检测到的人脸数)。"""
        img = np.array(image.convert("RGB"))
        face_pts = self._detect(img)

        if not face_pts:
            # 回退：整图按 512 修复（适合裁剪好的单人头像）
            h, w = img.shape[:2]
            scale = 512.0 / max(h, w)
            small = cv2.resize(img, (max(1, int(w * scale)), max(1, int(h * scale))),
                               interpolation=cv2.INTER_AREA)
            canvas = np.zeros((512, 512, 3), np.uint8)
            canvas[:small.shape[0], :small.shape[1]] = small
            out = self._restore_face(canvas)
            out = out[:small.shape[0], :small.shape[1]]
            return Image.fromarray(cv2.resize(out, (w, h), interpolation=cv2.INTER_LANCZOS4)), 0

        result = img.copy()
        for pts in face_pts:
            affine = _umeyama(pts, _REF_5PTS)
            aligned = cv2.warpAffine(img, affine, (512, 512), flags=cv2.INTER_LINEAR)
            restored = self._restore_face(aligned)
            result = self._paste_back(result, restored, affine)
        return Image.fromarray(result), len(face_pts)


def run_face_restore(manager, image: Image.Image, also_upscale: bool = False,
                     upscale_quality: str = "fast"):
    """人像修复入口。返回 (结果图, 性能信息)。"""
    if image is None:
        raise ValueError("请先上传包含人脸的图片。")
    restorer = manager.get_face_restorer()

    reset_peak_memory()
    with Timer() as t:
        result, n_faces = restorer.restore(image)
        if also_upscale:
            upscaler = manager.get_upscaler(upscale_quality)
            result = upscaler.upscale_image(result, target_scale=2.0)

    info = {
        "耗时": f"{t.elapsed:.2f} s",
        "峰值显存": f"{peak_memory_gb():.2f} GB" if manager.info.device.type == "cuda" else "CPU 推理",
        "检测到人脸": f"{n_faces} 张" if n_faces else "未检测到（已按整图修复）",
        "修复分辨率": "512×512 / 人脸",
    }
    if also_upscale:
        info["整图放大"] = "2×（联动 Real-ESRGAN）"
    return result, info
