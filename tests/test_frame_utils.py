"""测试帧工具: 命名、列举、最终帧序列构建 (需 numpy + cv2)."""
from __future__ import annotations

from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

from core.frame_utils import (
    build_final_sequence,
    copy_frame_sequence,
    count_frames,
    frame_name,
    frame_path,
    list_frames,
    materialize_final_sequence,
)


def test_frame_name_format():
    assert frame_name(1) == "frame_00001.png"
    assert frame_name(23) == "frame_00023.png"
    assert frame_name(12345) == "frame_12345.png"


def test_frame_path(tmp_frames_dir: Path):
    p = frame_path(3, tmp_frames_dir)
    assert p.name == "frame_00003.png"
    assert p.exists()


def test_list_and_count(tmp_frames_dir: Path):
    frames = list_frames(tmp_frames_dir)
    assert len(frames) == 5
    assert all(f.name.startswith("frame_") for f in frames)
    assert count_frames(tmp_frames_dir) == 5


def test_list_frames_empty_dir(tmp_path: Path):
    d = tmp_path / "empty"
    d.mkdir()
    assert list_frames(d) == []
    assert count_frames(d) == 0


def test_copy_frame_sequence(tmp_frames_dir: Path, tmp_path: Path):
    dst = tmp_path / "copied"
    copied = copy_frame_sequence(tmp_frames_dir, dst, indices=[1, 3, 5])
    assert len(copied) == 3
    # 目标目录帧重新从 1 开始编号
    names = [f.name for f in list_frames(dst)]
    assert names == ["frame_00001.png", "frame_00002.png", "frame_00003.png"]


def test_copy_frame_sequence_all(tmp_frames_dir: Path, tmp_path: Path):
    dst = tmp_path / "all"
    copied = copy_frame_sequence(tmp_frames_dir, dst)
    assert len(copied) == 5


def test_build_final_sequence_priority(tmp_frames_dir: Path, tmp_path: Path):
    """优先级: propagated > edited > original."""
    # 编辑第 3 帧
    import numpy as np
    import cv2
    edited_dir = tmp_path / "edited"
    edited_dir.mkdir()
    edited_img = np.full((100, 100, 3), 200, dtype=np.uint8)
    edited_path = edited_dir / "frame_00003.png"
    cv2.imwrite(str(edited_path), edited_img)

    # 传播结果 (含第 2 帧, 覆盖编辑)
    prop_dir = tmp_path / "propagated"
    prop_dir.mkdir()
    prop_img = np.full((100, 100, 3), 150, dtype=np.uint8)
    cv2.imwrite(str(prop_dir / "frame_00002.png"), prop_img)

    edited_map = {3: str(edited_path)}
    seq = build_final_sequence(tmp_frames_dir, edited_map, prop_dir)

    assert len(seq) == 5
    # 第 2 帧取自 propagated
    assert seq[1].parent.name == "propagated"
    # 第 3 帧取自 edited
    assert seq[2].parent.name == "edited"
    # 第 1/4/5 帧取自 original
    assert seq[0].parent.name == "frames"
    assert seq[3].parent.name == "frames"


def test_materialize_final_sequence(tmp_frames_dir: Path, tmp_path: Path):
    import numpy as np
    import cv2
    edited_dir = tmp_path / "edited"
    edited_dir.mkdir()
    edited_path = edited_dir / "frame_00002.png"
    cv2.imwrite(str(edited_path), np.full((100, 100, 3), 222, dtype=np.uint8))

    final_dir = tmp_path / "final"
    materialize_final_sequence(
        tmp_frames_dir, {2: str(edited_path)}, None, final_dir,
    )
    frames = list_frames(final_dir)
    assert len(frames) == 5
    # 第 2 帧应为编辑后的 (222)
    img = cv2.imread(str(frames[1]))
    assert img[0, 0, 0] == 222
