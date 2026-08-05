"""测试编辑传播引擎.

部分测试用 mock RAFT (避免依赖 torch); 一个端到端测试在 torch 可用时运行。
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

from utils.image_utils import warp_by_flow


def _torch_available() -> bool:
    """检查 torch 是否可用 (用于 skipif 标记)."""
    try:
        import torch  # noqa: F401
        return True
    except Exception:
        return False


def _make_propagator_with_mock_flow():
    """构造一个 Propagator, compute_flow 被 mock 为常量位移."""
    from core.edit_propagator import EditPropagator
    prop = EditPropagator.__new__(EditPropagator)
    prop.cfg = MagicMock(
        propagation_range=3, feather_sigma=5.0,
        ssim_threshold=0.6, raft_model_path="",
    )
    prop.device = "cpu"
    prop._raft = MagicMock()  # 跳过真实加载

    def fake_flow(a, b):
        h, w = a.shape[:2]
        # 简单常量位移 (0.5px), 保证一致性检查通过
        flow = np.zeros((h, w, 2), dtype=np.float32)
        flow[..., 0] = 0.5
        return flow

    prop.compute_flow = fake_flow
    return prop


def _make_frames(tmp_path: Path, n: int = 7):
    """创建 n 帧测试序列, 每帧为不同灰度的方块."""
    from core.frame_utils import frame_name
    d = tmp_path / "frames"
    d.mkdir()
    paths = []
    for i in range(1, n + 1):
        img = np.full((80, 80, 3), 100, dtype=np.uint8)
        # 每帧中央放一个不同颜色的方块, 模拟运动
        cv2.rectangle(img, (30, 30), (50, 50),
                      (i * 30, 0, 0), -1)
        p = d / frame_name(i)
        cv2.imwrite(str(p), img)
        paths.append(p)
    return d, paths


def test_propagate_creates_outputs_for_all_targets(tmp_path: Path, monkeypatch):
    """传播应覆盖关键帧前后各 N 帧, 并写入传播目录."""
    # 把 CONFIG 输出目录重定向到 tmp_path, 避免污染真实 outputs/
    import config as cfg_mod
    monkeypatch.setattr(cfg_mod, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(cfg_mod, "FRAMES_DIR", tmp_path / "frames")
    monkeypatch.setattr(cfg_mod, "EDITED_DIR", tmp_path / "edited")
    monkeypatch.setattr(cfg_mod, "MASKS_DIR", tmp_path / "masks")
    monkeypatch.setattr(cfg_mod, "PROPAGATED_DIR", tmp_path / "propagated")
    # core.frame_utils 在导入时已绑定, 需同步替换
    import core.frame_utils as fu
    monkeypatch.setattr(fu, "FRAMES_DIR", tmp_path / "frames")
    monkeypatch.setattr(fu, "EDITED_DIR", tmp_path / "edited")
    monkeypatch.setattr(fu, "MASKS_DIR", tmp_path / "masks")
    monkeypatch.setattr(fu, "PROPAGATED_DIR", tmp_path / "propagated")

    prop = _make_propagator_with_mock_flow()
    frames_dir, frames = _make_frames(tmp_path, n=9)

    # 关键帧第 5 帧, 编辑后中央变蓝
    edited = tmp_path / "edited_5.png"
    edited_img = np.full((80, 80, 3), 100, dtype=np.uint8)
    cv2.rectangle(edited_img, (30, 30), (50, 50), (0, 0, 255), -1)
    cv2.imwrite(str(edited), edited_img)

    mask = np.zeros((80, 80), dtype=np.uint8)
    mask[30:50, 30:50] = 255

    result = prop.propagate(
        edited_frame_path=str(edited),
        original_frames_dir=str(frames_dir),
        frame_index=5,
        mask=mask,
        propagation_range=3,
        session_id="test",
    )

    # 应覆盖前后各 3 帧 + 关键帧 = 7 帧
    assert len(result["propagated_indices"]) == 7
    assert 5 in result["propagated_indices"]
    assert 2 in result["propagated_indices"] and 8 in result["propagated_indices"]
    # 边界外的帧不应被传播
    assert 1 not in result["propagated_indices"]
    assert 9 not in result["propagated_indices"]
    # 传播目录应有 7 个帧文件
    from core.frame_utils import list_frames
    assert len(list_frames(result["propagated_frames_dir"])) == 7


def test_propagate_respects_range_bounds(tmp_path: Path, monkeypatch):
    """关键帧在左边界时, 只能向后传播."""
    import config as cfg_mod
    monkeypatch.setattr(cfg_mod, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(cfg_mod, "FRAMES_DIR", tmp_path / "frames")
    monkeypatch.setattr(cfg_mod, "EDITED_DIR", tmp_path / "edited")
    monkeypatch.setattr(cfg_mod, "MASKS_DIR", tmp_path / "masks")
    monkeypatch.setattr(cfg_mod, "PROPAGATED_DIR", tmp_path / "propagated")
    import core.frame_utils as fu
    monkeypatch.setattr(fu, "FRAMES_DIR", tmp_path / "frames")
    monkeypatch.setattr(fu, "EDITED_DIR", tmp_path / "edited")
    monkeypatch.setattr(fu, "MASKS_DIR", tmp_path / "masks")
    monkeypatch.setattr(fu, "PROPAGATED_DIR", tmp_path / "propagated")

    prop = _make_propagator_with_mock_flow()
    frames_dir, _ = _make_frames(tmp_path, n=5)

    edited = tmp_path / "edited_1.png"  # 第 1 帧 (左边界)
    cv2.imwrite(str(edited), np.full((80, 80, 3), 200, dtype=np.uint8))
    mask = np.zeros((80, 80), dtype=np.uint8)
    mask[20:60, 20:60] = 255

    result = prop.propagate(
        edited_frame_path=str(edited),
        original_frames_dir=str(frames_dir),
        frame_index=1,
        mask=mask,
        propagation_range=8,  # 但只有右边有帧
        session_id="test",
    )
    # 只能向后传播到第 2-5 帧 + 关键帧 = 5 帧
    assert len(result["propagated_indices"]) == 5


def test_warp_by_flow_preserves_masked_region():
    """warp 后的编辑区域应大致保留编辑内容."""
    base = np.zeros((60, 60, 3), dtype=np.uint8)
    overlay = np.full((60, 60, 3), 255, dtype=np.uint8)
    flow = np.zeros((60, 60, 2), dtype=np.float32)
    warped = warp_by_flow(overlay, flow)
    # 零位移, warp 后保持白色
    assert warped[30, 30, 0] == 255


@pytest.mark.skipif(
    not _torch_available(),
    reason="torch 不可用, 跳过 RAFT 端到端测试",
)
def test_propagator_real_raft_flow(tmp_path: Path):
    """torch 可用时, 验证 RAFT 真实加载与光流计算 (CPU 慢, 小图).

    RAFT 要求图像 ≥ 128x128 (经 8x 下采样后特征图需 ≥ 16).
    """
    import torch
    from core.edit_propagator import EditPropagator
    prop = EditPropagator(device="cpu")
    a = np.random.randint(0, 255, (128, 128, 3), dtype=np.uint8)
    b = np.random.randint(0, 255, (128, 128, 3), dtype=np.uint8)
    flow = prop.compute_flow(a, b)
    assert flow.shape == (128, 128, 2)
    assert flow.dtype == np.float32
