"""pytest 公共夹具: 把项目根加入 sys.path, 提供临时目录."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def tmp_frames_dir(tmp_path: Path) -> Path:
    """创建一个含若干合成 PNG 帧的临时目录."""
    import numpy as np
    try:
        import cv2
    except ImportError:
        pytest.skip("opencv 未安装")
    d = tmp_path / "frames"
    d.mkdir()
    for i in range(1, 6):
        img = np.full((100, 100, 3), i * 40, dtype=np.uint8)
        cv2.imwrite(str(d / f"frame_{i:05d}.png"), img)
    return d


@pytest.fixture
def random_mask():
    """返回一个 100x100 的二值 mask (中心方块为白)."""
    import numpy as np
    m = np.zeros((100, 100), dtype=np.uint8)
    m[30:70, 30:70] = 255
    return m
