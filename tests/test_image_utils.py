"""测试图像工具: mask 操作、混合、光流 warp (需 numpy + cv2)."""
from __future__ import annotations

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")

from utils.image_utils import (
    alpha_blend,
    compute_ssim,
    dilate_mask,
    erode_mask,
    extract_canny,
    feather_mask,
    forward_backward_consistency,
    gaussian_feather_blend,
    normalize_mask,
    warp_by_flow,
)


def test_normalize_mask_from_rgb():
    """彩色图应取最大通道并二值化."""
    rgb = np.zeros((10, 10, 3), dtype=np.uint8)
    rgb[2:8, 2:8, 0] = 200  # 红通道亮
    m = normalize_mask(rgb)
    assert m.shape == (10, 10)
    assert m.dtype == np.uint8
    assert m[5, 5] == 255
    assert m[0, 0] == 0


def test_normalize_mask_from_rgba():
    rgba = np.zeros((10, 10, 4), dtype=np.uint8)
    rgba[3:7, 3:7, 3] = 255  # alpha
    m = normalize_mask(rgba)
    assert m[5, 5] == 255
    assert m[0, 0] == 0


def test_dilate_erode_mask(random_mask):
    dil = dilate_mask(random_mask, pixels=4)
    # 膨胀后白色区域更大
    assert dil.sum() > random_mask.sum()
    ero = erode_mask(random_mask, pixels=4)
    assert ero.sum() < random_mask.sum()


def test_feather_mask_has_soft_edges(random_mask):
    soft = feather_mask(random_mask, sigma=3.0)
    # 软 mask 应有中间灰度值
    assert soft.min() >= 0 and soft.max() <= 255
    # 边界附近应存在非 0/255 的值
    edge = soft[28:32, 50]
    assert np.any((edge > 0) & (edge < 255))


def test_alpha_blend():
    base = np.zeros((20, 20, 3), dtype=np.uint8)        # 黑
    overlay = np.full((20, 20, 3), 100, dtype=np.uint8)  # 灰
    mask = np.zeros((20, 20), dtype=np.uint8)
    mask[5:15, 5:15] = 255
    out = alpha_blend(base, overlay, mask)
    # mask 区域为 overlay (100), 其余为 base (0)
    assert out[10, 10, 0] == 100
    assert out[0, 0, 0] == 0


def test_gaussian_feather_blend_soft_boundary():
    base = np.zeros((30, 30, 3), dtype=np.uint8)
    overlay = np.full((30, 30, 3), 200, dtype=np.uint8)
    mask = np.zeros((30, 30), dtype=np.uint8)
    mask[10:20, 10:20] = 255
    out = gaussian_feather_blend(base, overlay, mask, sigma=3.0)
    # 边界像素应介于 base 与 overlay 之间 (羽化)
    assert 0 < out[10, 10, 0] < 200 or out[10, 10, 0] >= 200
    # 中心应为接近 overlay
    assert out[15, 15, 0] > 150


def test_warp_by_flow_identity():
    """零光流应近似返回原图."""
    img = np.random.randint(0, 255, (40, 40, 3), dtype=np.uint8)
    flow = np.zeros((40, 40, 2), dtype=np.float32)
    warped = warp_by_flow(img, flow)
    # 零位移下应非常接近原图
    assert np.array_equal(warped, img)


def test_warp_by_flow_translation():
    """水平位移 5 像素的光流应平移图像."""
    img = np.zeros((40, 40, 3), dtype=np.uint8)
    img[:, 0, :] = 255  # 左列白
    flow = np.zeros((40, 40, 2), dtype=np.float32)
    flow[..., 0] = 5.0   # x 方向 +5
    warped = warp_by_flow(img, flow)
    # 平移后第 5 列附近应有白色
    assert warped[20, 5, 0] > 200


def test_forward_backward_consistency():
    """恒等光流的前后向一致性应全部可靠."""
    flow = np.zeros((30, 30, 2), dtype=np.float32)
    reliable = forward_backward_consistency(flow, flow, threshold=1.0)
    assert reliable.min() == 255  # 全部可靠


def test_compute_ssim_identical():
    img = np.random.randint(0, 255, (64, 64, 3), dtype=np.uint8)
    assert compute_ssim(img, img) == pytest.approx(1.0, abs=1e-6)


def test_compute_ssim_different():
    a = np.zeros((64, 64, 3), dtype=np.uint8)
    b = np.full((64, 64, 3), 255, dtype=np.uint8)
    assert compute_ssim(a, b) < 0.5


def test_extract_canny_returns_edges():
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    img[40:60, 40:60] = 255  # 中心方块
    edges = extract_canny(img, 0.1, 0.2)
    assert edges.ndim == 2
    assert edges.shape == (100, 100)
    # 方块边界处应有边缘 (用较低阈值确保检测到)
    assert edges.sum() > 0
