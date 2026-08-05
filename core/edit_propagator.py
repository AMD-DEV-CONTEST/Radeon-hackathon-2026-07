"""模块三: 编辑传播引擎 (核心创新).

将关键帧的编辑结果传播到相邻帧, 保持时序一致性。

算法:
  1. 对关键帧 edit_f 和每一相邻帧 orig_f_i:
     a. RAFT 计算 edit_f -> orig_f_i 的前向光流 F
     b. RAFT 计算 orig_f_i -> edit_f 的后向光流 B
     c. 用 F 将 edit_f 的编辑区域 warp 到 orig_f_i 的坐标系
     d. 前后向光流一致性检查: 排除不可靠像素
     e. 羽化混合 warp 结果与 orig_f_i
  2. 边界: 高斯羽化 + 颜色平滑过渡
  3. 质量检查: SSIM < 阈值则标记为低质量

光流由 torchvision 内置 RAFT 提供 (``torchvision.models.optical_flow.raft_large``)。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from config import CONFIG, PropagationConfig
from core.frame_utils import ensure_session_dirs, frame_path, list_frames
from utils.image_utils import (
    compute_local_ssim,
    forward_backward_consistency,
    gaussian_feather_blend,
    normalize_mask,
    warp_by_flow,
)
from utils.video_utils import read_frame, write_frame


class EditPropagator:
    """编辑传播引擎 (RAFT 光流传播)."""

    def __init__(self, raft_model_path: str | None = None,
                 device: str | None = None):
        self.cfg = PropagationConfig()
        self.raft_model_path = raft_model_path or self.cfg.raft_model_path
        self.device = device or _pick_device()
        self._raft = None  # 惰性加载

    # ------------------------------------------------------------------ #
    # RAFT 模型
    # ------------------------------------------------------------------ #
    def _load_raft(self):
        if self._raft is not None:
            return self._raft
        import torch
        from torchvision.models.optical_flow import raft_large, Raft_Large_Weights
        try:
            weights = Raft_Large_Weights.DEFAULT
            self._raft = raft_large(weights=weights, progress=False)
        except Exception:
            # 回退: 无预训练权重
            self._raft = raft_large(progress=False)
        self._raft = self._raft.to(self.device).eval()
        return self._raft

    def compute_flow(self, img_a: np.ndarray,
                     img_b: np.ndarray) -> np.ndarray:
        """计算 img_a -> img_b 的光流 (H, W, 2) float32.

        输入为 RGB uint8 ndarray。
        """
        import torch
        raft = self._load_raft()
        a = _to_tensor(img_a, self.device)
        b = _to_tensor(img_b, self.device)
        with torch.no_grad():
            flow_list = raft(a, b)
        flow = flow_list[-1]  # 最后一帧最精细
        flow_np = flow[0].permute(1, 2, 0).cpu().numpy().astype(np.float32)
        return flow_np

    # ------------------------------------------------------------------ #
    # 主传播流程
    # ------------------------------------------------------------------ #
    def propagate(
        self,
        edited_frame_path: str | Path,
        original_frames_dir: str | Path,
        frame_index: int,
        mask: np.ndarray,
        propagation_range: int | None = None,
        feather_sigma: float | None = None,
        ssim_threshold: float | None = None,
        session_id: str | None = None,
        progress_callback=None,
        direction: str = "bidirectional",
    ) -> dict:
        """将关键帧编辑传播到相邻帧.

        Parameters
        ----------
        frame_index : int
            关键帧索引 (1-based)。
        mask : np.ndarray
            编辑区域的 mask (与帧同尺寸, 白色为编辑区)。
        direction : str
            传播方向: "forward" (仅后续帧), "backward" (仅前序帧),
            "bidirectional" (双向, 默认)。

        Returns
        -------
        dict
            ``{"propagated_frames_dir", "propagated_indices",
            "quality_scores", "low_quality_frames"}``
        """
        def _cb(ev):
            if progress_callback:
                progress_callback(ev)

        prop_range = propagation_range or self.cfg.propagation_range
        sigma = feather_sigma or self.cfg.feather_sigma
        ssim_thr = ssim_threshold or self.cfg.ssim_threshold

        session_id = session_id or "default"
        dirs = ensure_session_dirs(session_id)
        out_dir = dirs["propagated"]
        # 清理旧传播结果
        for old in out_dir.glob("frame_*.png"):
            old.unlink()

        # 加载关键帧 (编辑后) 与原始帧列表
        edited_img = read_frame(edited_frame_path)
        original_frames = list_frames(original_frames_dir)
        n = len(original_frames)
        if frame_index < 1 or frame_index > n:
            raise IndexError(f"关键帧索引越界: {frame_index} / {n}")

        key_orig_path = original_frames[frame_index - 1]
        key_orig_img = read_frame(key_orig_path)

        # 对齐 mask 尺寸到帧尺寸
        mask_bin = normalize_mask(mask)
        if mask_bin.shape[:2] != edited_img.shape[:2]:
            import cv2
            mask_bin = cv2.resize(
                mask_bin, (edited_img.shape[1], edited_img.shape[0]),
                interpolation=cv2.INTER_NEAREST,
            )

        # 待传播索引 (根据方向选择前序/后续/双向, 排除关键帧本身)
        if direction == "forward":
            lo = frame_index + 1
            hi = min(n, frame_index + prop_range)
        elif direction == "backward":
            lo = max(1, frame_index - prop_range)
            hi = frame_index - 1
        else:  # bidirectional
            lo = max(1, frame_index - prop_range)
            hi = min(n, frame_index + prop_range)
        target_indices = [i for i in range(lo, hi + 1) if i != frame_index]

        # 先把关键帧编辑结果写入传播目录 (本身无需传播)
        key_out = out_dir / original_frames[frame_index - 1].name
        write_frame(key_out, edited_img)

        quality_scores: dict[int, float] = {frame_index: 1.0}
        low_quality: list[int] = []
        propagated: list[int] = [frame_index]

        _cb({"type": "status", "message": f"加载 RAFT 光流模型..."})
        self._load_raft()

        total = len(target_indices)
        for k, idx in enumerate(target_indices, start=1):
            _cb({"type": "progress", "value": k / max(1, total),
                 "message": f"传播到第 {idx} 帧 ({k}/{total})"})

            orig_img = read_frame(original_frames[idx - 1])

            # 尺寸对齐 (RAFT 要求两图同尺寸)
            if orig_img.shape != edited_img.shape:
                orig_resized = _resize_to(orig_img, edited_img.shape[:2])
            else:
                orig_resized = orig_img

            # 前向光流: edited -> orig (用于一致性检查)
            flow_fwd = self.compute_flow(edited_img, orig_resized)
            # 后向光流: orig -> edited (用于后向 warp: orig 位置 X 处采样 edited)
            flow_bwd = self.compute_flow(orig_resized, edited_img)

            # 一致性检查
            reliable = forward_backward_consistency(flow_fwd, flow_bwd,
                                                    threshold=1.0)

            # warp 编辑帧到 orig 坐标系:
            # flow_bwd 描述 orig 像素 -> edited 位置, 故 orig(X) = edited(X - flow_bwd(X))
            warped_edited = warp_by_flow(edited_img, flow_bwd)

            # 组合 mask: 编辑 mask ∩ 可靠区域
            combined_mask = _and_masks(mask_bin, reliable)
            if combined_mask.sum() == 0:
                # 无可靠像素, 退化为只用原 mask
                combined_mask = mask_bin

            # 羽化混合
            blended = gaussian_feather_blend(
                orig_resized, warped_edited, combined_mask, sigma=sigma,
            )

            # 若原帧被 resize 过, 还原尺寸
            if orig_img.shape != edited_img.shape:
                import cv2
                blended = cv2.resize(
                    blended, (orig_img.shape[1], orig_img.shape[0]),
                    interpolation=cv2.INTER_LINEAR,
                )
                # mask 也还原, 用于 SSIM
                combined_mask = cv2.resize(
                    combined_mask, (orig_img.shape[1], orig_img.shape[0]),
                    interpolation=cv2.INTER_NEAREST,
                )

            out_path = out_dir / original_frames[idx - 1].name
            write_frame(out_path, blended)

            # 质量评估: 在 mask 区域内比较 blended 与原帧的"应变化程度"
            # 这里用 warped 与 blended 的 SSIM 评估传播一致性
            ssim_val = compute_local_ssim(blended, orig_img, combined_mask)
            # SSIM 越低说明变化越大 (符合编辑预期), 但过低可能为瑕疵
            # 将 SSIM 反转为质量分: 接近 1 为高质, 远离 1 为低质
            quality = 1.0 - min(1.0, abs(1.0 - ssim_val))
            quality_scores[idx] = quality
            if quality < ssim_thr:
                low_quality.append(idx)
            propagated.append(idx)

        _cb({"type": "done", "message": f"传播完成: {len(propagated)} 帧"})
        return {
            "propagated_frames_dir": str(out_dir),
            "propagated_indices": sorted(propagated),
            "quality_scores": quality_scores,
            "low_quality_frames": low_quality,
        }


# ---------------------------------------------------------------------- #
# 辅助
# ---------------------------------------------------------------------- #
def _pick_device() -> str:
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"


def _to_tensor(img: np.ndarray, device: str):
    """RGB uint8 ndarray (H,W,3) -> torch tensor (1,3,H,W) [0,1]."""
    import torch
    t = torch.from_numpy(img).float().permute(2, 0, 1) / 255.0
    return t.unsqueeze(0).to(device)


def _resize_to(img: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    """resize 到 (H, W)."""
    import cv2
    h, w = shape
    return cv2.resize(img, (w, h), interpolation=cv2.INTER_LINEAR)


def _and_masks(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """两 mask 交集 (255 & 255 -> 255)."""
    if a.shape != b.shape:
        import cv2
        b = cv2.resize(b, (a.shape[1], a.shape[0]),
                       interpolation=cv2.INTER_NEAREST)
    return ((a > 127) & (b > 127)).astype(np.uint8) * 255
