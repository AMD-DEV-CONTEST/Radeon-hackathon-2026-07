"""图像处理工具.

mask 处理、羽化、光流 warp 后的混合、SSIM 评估等。
供 frame_editor 与 edit_propagator 共用。
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


# ---------------------------------------------------------------------- #
# Mask 操作
# ---------------------------------------------------------------------- #
def normalize_mask(mask: np.ndarray, threshold: int = 127) -> np.ndarray:
    """将任意 mask 二值化为 {0, 255} uint8.

    接受单通道或含 alpha 的 RGBA; 若为彩色图取最大通道。
    """
    if mask.ndim == 3:
        if mask.shape[2] == 4:
            mask = mask[:, :, 3]  # alpha
        else:
            mask = mask.max(axis=2)
    mask = mask.astype(np.uint8)
    _, binary = cv2.threshold(mask, threshold, 255, cv2.THRESH_BINARY)
    return binary


def dilate_mask(mask: np.ndarray, pixels: int = 5) -> np.ndarray:
    """膨胀 mask (扩大编辑区域)."""
    kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (pixels * 2 + 1, pixels * 2 + 1)
    )
    return cv2.dilate(mask, kernel, iterations=1)


def erode_mask(mask: np.ndarray, pixels: int = 5) -> np.ndarray:
    """腐蚀 mask (缩小编辑区域)."""
    kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (pixels * 2 + 1, pixels * 2 + 1)
    )
    return cv2.erode(mask, kernel, iterations=1)


def feather_mask(mask: np.ndarray, sigma: float = 5.0) -> np.ndarray:
    """对 mask 边缘做高斯羽化, 返回 [0, 255] 的软 mask."""
    blurred = cv2.GaussianBlur(
        mask.astype(np.float32), (0, 0), sigmaX=sigma, sigmaY=sigma,
    )
    return np.clip(blurred, 0, 255).astype(np.uint8)


def mask_to_alpha(mask: np.ndarray) -> np.ndarray:
    """mask 归一化到 [0, 1] float."""
    return mask.astype(np.float32) / 255.0


# ---------------------------------------------------------------------- #
# 混合
# ---------------------------------------------------------------------- #
def alpha_blend(base: np.ndarray, overlay: np.ndarray,
                mask: np.ndarray) -> np.ndarray:
    """按 mask 将 overlay 混合到 base 上.

    三者尺寸需一致。mask 为单通道 (0-255)。
    """
    if mask.ndim == 3:
        mask = mask[:, :, 0]
    a = mask_to_alpha(mask)
    if a.ndim == 2:
        a = a[:, :, None]
    base_f = base.astype(np.float32)
    over_f = overlay.astype(np.float32)
    out = base_f * (1 - a) + over_f * a
    return np.clip(out, 0, 255).astype(np.uint8)


def gaussian_feather_blend(
    base: np.ndarray,
    overlay: np.ndarray,
    mask: np.ndarray,
    sigma: float = 5.0,
) -> np.ndarray:
    """带高斯羽化的混合 (mask 边缘软化后再混合)."""
    soft = feather_mask(mask, sigma=sigma)
    return alpha_blend(base, overlay, soft)


# ---------------------------------------------------------------------- #
# 光流 warp
# ---------------------------------------------------------------------- #
def warp_by_flow(image: np.ndarray, flow: np.ndarray) -> np.ndarray:
    """按光流 warp 图像 (后向采样).

    flow 为 (H, W, 2) 的 (dx, dy) 偏移场, 表示 ``image`` 中每个像素
    在目标坐标系中的位移 (即像素 p 移动到 p + flow(p))。
    为了在目标坐标系重建图像, 目标位置 X 处采样源位置 ``X - flow(X)``。
    """
    h, w = image.shape[:2]
    grid_x, grid_y = np.meshgrid(np.arange(w), np.arange(h))
    map_x = (grid_x - flow[..., 0]).astype(np.float32)
    map_y = (grid_y - flow[..., 1]).astype(np.float32)
    return cv2.remap(
        image, map_x, map_y,
        interpolation=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REFLECT,
    )


def forward_backward_consistency(flow_fwd: np.ndarray,
                                 flow_bwd: np.ndarray,
                                 threshold: float = 1.0) -> np.ndarray:
    """前后向光流一致性检查, 返回可靠性 mask (255=可靠).

    一致像素: ``|F(x) + B(x + F(x))| < threshold``。
    """
    h, w = flow_fwd.shape[:2]
    warped_bwd = warp_by_flow(flow_bwd, flow_fwd)
    diff = flow_fwd + warped_bwd
    mag = np.sqrt(diff[..., 0] ** 2 + diff[..., 1] ** 2)
    reliable = (mag < threshold).astype(np.uint8) * 255
    return reliable


# ---------------------------------------------------------------------- #
# 结构提取 (ControlNet 预处理)
# ---------------------------------------------------------------------- #
def extract_canny(image: np.ndarray,
                  low_threshold: float = 0.4,
                  high_threshold: float = 0.8) -> np.ndarray:
    """提取 Canny 边缘 (输入 RGB, 返回单通道边缘图 0-255)."""
    if image.ndim == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    else:
        gray = image
    lt = int(low_threshold * 255)
    ht = int(high_threshold * 255)
    edges = cv2.Canny(gray, lt, ht)
    return edges


def extract_depth(image: np.ndarray) -> np.ndarray:
    """简化深度估计 (MiDaS 由 ComfyUI 节点处理; 此处仅占位回退).

    本地回退使用灰度图作为弱深度近似, 真正深度图由 ComfyUI
    ``MiDaS-DepthMapPreprocessor`` 节点产生。
    """
    if image.ndim == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    else:
        gray = image
    return cv2.applyColorMap(gray, cv2.COLORMAP_INFERNO)


# ---------------------------------------------------------------------- #
# 轮廓区域提取与标注 (替代手动画笔)
# ----------------------------------------------------------------------

# 16 色调色板 (足够区分大部分区域)
_REGION_COLORS = np.array([
    [231, 76, 60],    # 红
    [46, 204, 113],   # 绿
    [52, 152, 219],   # 蓝
    [241, 196, 15],   # 黄
    [155, 89, 182],   # 紫
    [230, 126, 34],   # 橙
    [26, 188, 156],   # 青
    [236, 240, 241],  # 白
    [149, 165, 166],  # 灰
    [255, 99, 132],   # 粉
    [54, 162, 235],   # 天蓝
    [75, 192, 192],   # 薄荷
    [153, 102, 255],  # 淡紫
    [255, 159, 64],   # 琥珀
    [201, 203, 207],  # 银灰
    [0, 0, 0],        # 黑 (兜底)
], dtype=np.uint8)


def extract_regions(image: np.ndarray, min_area: int = 200) -> np.ndarray:
    """提取画面中的连通区域, 返回与原图同尺寸的区域标签图.

    使用 Canny 边缘 + 形态学闭运算 + connectedComponents。
    每个像素的值表示所属区域编号 (0=背景)。

    Parameters
    ----------
    image : np.ndarray
        RGB 图像 (H, W, 3)。
    min_area : int
        小于此面积的区域被合并到背景。

    Returns
    -------
    np.ndarray
        int32 标签图 (H, W), 0=背景, 1..N=区域编号。
    """
    if image.ndim == 2:
        gray = image
    else:
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)

    # Canny 边缘
    edges = cv2.Canny(gray, 50, 120)

    # 形态学闭运算: 连接近邻边缘形成封闭区域
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=2)

    # 连通域
    num_labels, labels = cv2.connectedComponents(closed, connectivity=8)

    # 过滤小区域 -> 合并到背景 (0)
    if min_area > 0:
        for i in range(1, num_labels):
            area = int(np.sum(labels == i))
            if area < min_area:
                labels[labels == i] = 0

        # 重新编号
        unique = np.unique(labels)
        remap = np.zeros(unique.max() + 1, dtype=np.int32)
        for new_id, old_id in enumerate(unique):
            remap[old_id] = new_id
        labels = remap[labels]

    return labels.astype(np.int32)


def color_regions(image: np.ndarray, labels: np.ndarray,
                   alpha: float = 0.4) -> np.ndarray:
    """在原图上叠加半透明区域颜色 + 编号标签.

    Parameters
    ----------
    image : np.ndarray
        原始 RGB 图像 (H, W, 3)。
    labels : np.ndarray
        ``extract_regions`` 返回的标签图。
    alpha : float
        颜色叠加透明度 (0=原图, 1=纯色块)。

    Returns
    -------
    np.ndarray
        标注后的 RGB 图像。
    """
    overlay = image.copy().astype(np.float32)
    num_regions = int(labels.max())

    for rid in range(1, num_regions + 1):
        color = _REGION_COLORS[(rid - 1) % len(_REGION_COLORS)].astype(np.float32)
        mask = (labels == rid)
        overlay[mask] = overlay[mask] * (1 - alpha) + color * alpha

    result = np.clip(overlay, 0, 255).astype(np.uint8)

    # 在每个区域中心绘制编号
    for rid in range(1, num_regions + 1):
        mask = (labels == rid)
        ys, xs = np.where(mask)
        if len(ys) < 10:
            continue
        cx, cy = int(xs.mean()), int(ys.mean())
        color = _REGION_COLORS[(rid - 1) % len(_REGION_COLORS)].tolist()
        # 白色描边 + 彩色文字
        cv2.putText(result, str(rid), (cx - 8, cy + 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 3)
        cv2.putText(result, str(rid), (cx - 8, cy + 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 1)

    return result


def point_to_region_mask(point: tuple[int, int], labels: np.ndarray,
                          dilate: int = 3) -> np.ndarray:
    """将点击坐标转换为该区域的二值 mask.

    Parameters
    ----------
    point : (x, y)
        用户点击坐标。
    labels : np.ndarray
        ``extract_regions`` 返回的标签图。
    dilate : int
        mask 膨胀像素 (避免边缘留缝)。

    Returns
    -------
    np.ndarray
        uint8 二值 mask (0/255)。
    """
    x, y = int(point[0]), int(point[1])
    h, w = labels.shape[:2]
    x = max(0, min(w - 1, x))
    y = max(0, min(h - 1, y))

    region_id = labels[y, x]
    if region_id == 0:
        # 点击在背景: 用 floodfill 在原图上扩展
        return np.zeros((h, w), dtype=np.uint8)

    mask = (labels == region_id).astype(np.uint8) * 255

    if dilate > 0:
        mask = dilate_mask(mask, pixels=dilate)

    return mask


def regions_to_mask(labels: np.ndarray, region_ids: list[int],
                     dilate: int = 3) -> np.ndarray:
    """将多个区域编号合并为一个 mask.

    Parameters
    ----------
    labels : np.ndarray
        ``extract_regions`` 返回的标签图。
    region_ids : list[int]
        要选中的区域编号列表。
    dilate : int
        mask 膨胀像素。

    Returns
    -------
    np.ndarray
        uint8 二值 mask (0/255)。
    """
    h, w = labels.shape[:2]
    mask = np.zeros((h, w), dtype=np.uint8)
    for rid in region_ids:
        if rid <= 0:
            continue
        mask[labels == rid] = 255
    if dilate > 0 and mask.any():
        mask = dilate_mask(mask, pixels=dilate)
    return mask


# ---------------------------------------------------------------------- #
# 质量评估
# ---------------------------------------------------------------------- #
def compute_ssim(img_a: np.ndarray, img_b: np.ndarray) -> float:
    """计算两图的整体 SSIM (0-1)."""
    from skimage.metrics import structural_similarity as ssim

    if img_a.ndim == 3:
        img_a = cv2.cvtColor(img_a, cv2.COLOR_RGB2GRAY)
    if img_b.ndim == 3:
        img_b = cv2.cvtColor(img_b, cv2.COLOR_RGB2GRAY)
    return float(ssim(img_a, img_b, data_range=255))


def compute_local_ssim(img_a: np.ndarray, img_b: np.ndarray,
                       mask: np.ndarray | None = None) -> float:
    """在 mask 区域内计算 SSIM; mask 为 None 时同 compute_ssim."""
    if mask is None:
        return compute_ssim(img_a, img_b)
    if mask.ndim == 3:
        mask = mask[:, :, 0]
    ys, xs = np.where(mask > 127)
    if len(xs) < 4:
        return 0.0
    x0, x1 = xs.min(), xs.max()
    y0, y1 = ys.min(), ys.max()
    a = img_a[y0:y1 + 1, x0:x1 + 1]
    b = img_b[y0:y1 + 1, x0:x1 + 1]
    return compute_ssim(a, b)


# ---------------------------------------------------------------------- #
# IO
# ---------------------------------------------------------------------- #
def save_mask(mask: np.ndarray, path: str | Path) -> Path:
    """保存 mask 为 PNG (单通道)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if mask.ndim == 3:
        mask = mask[:, :, 0]
    cv2.imwrite(str(path), mask)
    return path


def load_rgb(path: str | Path) -> np.ndarray:
    """读取图像为 RGB."""
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(f"读取失败: {path}")
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
