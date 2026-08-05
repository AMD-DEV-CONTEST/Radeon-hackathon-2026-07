"""端到端集成测试: 模拟 生成→选帧→编辑→传播→导出 完整流程.

所有 ComfyUI 调用通过 mock 替代, 验证模块间数据流和接口契约.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from PIL import Image

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config


# ─── fixtures ──────────────────────────────────────────────

@pytest.fixture
def tmp_frames(tmp_path):
    """创建 10 帧测试图像 (64x64)."""
    d = tmp_path / "frames"
    d.mkdir()
    for i in range(1, 11):
        img = Image.new("RGB", (64, 64), color=(i * 20, 0, 0))
        img.save(d / f"frame_{i:05d}.png")
    return d


@pytest.fixture
def mock_client():
    from backend.comfyui_client import ComfyUIClient
    c = MagicMock(spec=ComfyUIClient)
    c.set_node_param = ComfyUIClient.set_node_param
    c.upload_image.return_value = "img.png"
    c.upload_mask.return_value = "mask.png"
    c.queue_prompt.return_value = "fake-id"
    return c


# ─── Step 1: 视频生成 ─────────────────────────────────────

def test_step1_generate(tmp_path, mock_client):
    """Step 1: VideoGenerator 设置 workflow 参数并返回帧序列."""
    from core.video_generator import VideoGenerator

    wf = json.loads((config.WORKFLOWS_DIR / "wan21_i2v.json").read_text())
    mock_client.load_workflow.return_value = wf
    mock_client.iter_progress.return_value = iter([
        {"type": "done", "outputs": [tmp_path / "out.mp4"]},
    ])

    gen = VideoGenerator(client=mock_client)
    frames_dir = tmp_path / "gen"
    frames_dir.mkdir()

    with patch("core.video_generator.split_video_to_frames") as split, \
         patch("core.video_generator.get_video_info") as info, \
         patch("core.video_generator._pick_video", return_value=tmp_path / "out.mp4"):
        split.return_value = [frames_dir / f"frame_{i:05d}.png" for i in range(1, 50)]
        info.return_value = MagicMock(fps=16.0)
        result = gen.generate(prompt="跑车", reference_image="/tmp/r.png",
                              duration=3, seed=42)

    assert result["frame_count"] == 49
    assert result["fps"] == 16
    assert wf["6"]["inputs"]["text"] == "跑车"
    assert wf["16"]["inputs"]["width"] == 832
    assert wf["17"]["inputs"]["seed"] == 42


# ─── Step 2: 帧选择 ───────────────────────────────────────

def test_step2_select_frame(tmp_frames):
    """Step 2: list_frames + frame_name 接口验证."""
    from core.frame_utils import list_frames, frame_name, frame_path

    frames = list_frames(tmp_frames)
    assert len(frames) == 10

    # frame_name 接受 int
    assert frame_name(5) == "frame_00005.png"

    # frame_path 接受 int + dir
    p = frame_path(5, tmp_frames)
    assert p.exists()
    assert p.name == "frame_00005.png"


# ─── Step 3: 关键帧编辑 ──────────────────────────────────

def test_step3_edit_frame(tmp_frames, mock_client):
    """Step 3: FrameEditor.edit_frame 设置 workflow 参数."""
    from core.frame_editor import FrameEditor

    wf = json.loads((config.WORKFLOWS_DIR / "sdxl_inpaint_controlnet.json").read_text())
    mock_client.load_workflow.return_value = wf

    edited_path = tmp_frames / "edited_5.png"
    Image.new("RGB", (64, 64), (0, 0, 255)).save(edited_path)
    mock_client.iter_progress.return_value = iter([
        {"type": "done", "outputs": [edited_path]},
    ])

    editor = FrameEditor(client=mock_client)
    mask = np.zeros((64, 64), dtype=np.uint8)
    mask[:, :32] = 255

    result = editor.edit_frame(
        frame_path=str(tmp_frames / "frame_00005.png"),
        mask=mask,
        edit_prompt="把红色改成蓝色",
        controlnet_type="canny",
        denoising_strength=0.75,
        use_controlnet=True,
    )

    assert "edited_frame_path" in result
    assert "mask_path" in result
    # 验证 workflow 参数
    assert wf["6"]["inputs"]["text"] == "把红色改成蓝色"


# ─── Step 4: 编辑传播 ─────────────────────────────────────

def test_step4_propagate(tmp_frames):
    """Step 4: EditPropagator.propagate 传播到相邻帧."""
    from core.edit_propagator import EditPropagator

    propagator = EditPropagator()
    mask = np.zeros((64, 64), dtype=np.uint8)
    mask[:, :32] = 255
    edited_frame = tmp_frames / "frame_00005.png"

    with patch.object(propagator, "compute_flow") as mock_flow, \
         patch.object(propagator, "_load_raft"):
        mock_flow.return_value = np.zeros((64, 64, 2), dtype=np.float32)
        result = propagator.propagate(
            edited_frame_path=str(edited_frame),
            original_frames_dir=str(tmp_frames),
            frame_index=5,
            mask=mask,
            propagation_range=2,
        )

    assert "propagated_frames_dir" in result
    assert "propagated_indices" in result
    indices = result["propagated_indices"]
    # 应包含关键帧 (5) 和相邻帧 (3,4,6,7)
    assert 5 in indices
    assert 3 in indices
    assert 7 in indices
    assert len(indices) >= 4


# ─── Step 5: 导出最终视频 ─────────────────────────────────

def test_step5_export(tmp_frames):
    """Step 5: VideoComposer.compose + build_final_sequence."""
    from core.video_composer import VideoComposer
    from core.frame_utils import build_final_sequence, materialize_final_sequence

    edited_dir = tmp_frames.parent / "edited"
    edited_dir.mkdir()
    edited_5 = tmp_frames / "frame_00005.png"
    edited_copy = edited_dir / "frame_00005.png"
    shutil.copy2(edited_5, edited_copy)

    edited_indices = {5: str(edited_copy)}
    final_seq = build_final_sequence(tmp_frames, edited_indices)
    assert len(final_seq) == 10
    # 第 5 帧应来自 edited
    assert final_seq[4] == Path(edited_copy)

    final_dir = tmp_frames.parent / "final"
    materialized = materialize_final_sequence(
        tmp_frames, edited_indices, None, final_dir,
    )
    assert len(materialized) == 10
    for p in materialized:
        assert p.exists()

    composer = VideoComposer()
    output = tmp_frames.parent / "output.mp4"
    with patch("core.video_composer.frames_to_video") as mock_ftv:
        mock_ftv.return_value = output
        result = composer.compose(
            original_frames_dir=str(tmp_frames),
            edited_indices=edited_indices,
            output_path=str(output),
            fps=16,
        )
    mock_ftv.assert_called_once()
    assert result["frame_count"] == 10
    assert result["fps"] == 16


# ─── 完整流程串联 ───────────────────────────────────────────

def test_full_pipeline(tmp_path, mock_client):
    """完整流程: 生成→选帧→编辑→传播→导出."""
    # ── Step 1: 生成 ──
    from core.video_generator import VideoGenerator
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    for i in range(1, 11):
        Image.new("RGB", (64, 64), (i * 20, 0, 0)).save(
            frames_dir / f"frame_{i:05d}.png")

    wf = json.loads((config.WORKFLOWS_DIR / "wan21_i2v.json").read_text())
    mock_client.load_workflow.return_value = wf
    mock_client.iter_progress.return_value = iter([
        {"type": "done", "outputs": [tmp_path / "gen.mp4"]},
    ])
    gen = VideoGenerator(client=mock_client)
    with patch("core.video_generator.split_video_to_frames") as split, \
         patch("core.video_generator.get_video_info") as info, \
         patch("core.video_generator._pick_video", return_value=tmp_path / "gen.mp4"):
        split.return_value = list(frames_dir.glob("frame_*.png"))
        info.return_value = MagicMock(fps=16.0)
        gen_result = gen.generate(prompt="test", reference_image="/tmp/r.png",
                                  duration=1, seed=1)
    assert gen_result["frame_count"] == 10

    # ── Step 2: 选帧 ──
    from core.frame_utils import list_frames, frame_path
    frames = list_frames(frames_dir)
    assert len(frames) == 10
    selected = frame_path(5, frames_dir)

    # ── Step 3: 编辑 ──
    from core.frame_editor import FrameEditor
    wf_inpaint = json.loads(
        (config.WORKFLOWS_DIR / "sdxl_inpaint.json").read_text())
    mock_client.load_workflow.return_value = wf_inpaint

    edited_png = tmp_path / "edited_5.png"
    Image.new("RGB", (64, 64), (0, 0, 255)).save(edited_png)
    mock_client.iter_progress.return_value = iter([
        {"type": "done", "outputs": [edited_png]},
    ])

    editor = FrameEditor(client=mock_client)
    mask = np.zeros((64, 64), dtype=np.uint8)
    mask[:, :32] = 255
    edit_result = editor.edit_frame(
        frame_path=str(selected),
        mask=mask,
        edit_prompt="blue",
        use_controlnet=False,
    )
    assert "edited_frame_path" in edit_result

    # ── Step 4: 传播 ──
    from core.edit_propagator import EditPropagator
    propagator = EditPropagator()
    with patch.object(propagator, "compute_flow") as mock_flow, \
         patch.object(propagator, "_load_raft"):
        mock_flow.return_value = np.zeros((64, 64, 2), dtype=np.float32)
        prop_result = propagator.propagate(
            edited_frame_path=str(edited_png),
            original_frames_dir=str(frames_dir),
            frame_index=5,
            mask=mask,
            propagation_range=2,
        )
    assert len(prop_result["propagated_indices"]) >= 4

    # ── Step 5: 导出 ──
    from core.video_composer import VideoComposer
    from core.frame_utils import build_final_sequence
    prop_dir = Path(prop_result["propagated_frames_dir"])
    edited_indices = {5: str(edited_png)}
    final_seq = build_final_sequence(frames_dir, edited_indices, prop_dir)
    assert len(final_seq) == 10

    composer = VideoComposer()
    output = tmp_path / "final.mp4"
    with patch("core.video_composer.frames_to_video") as mock_ftv:
        mock_ftv.return_value = output
        export_result = composer.compose(
            original_frames_dir=str(frames_dir),
            edited_indices=edited_indices,
            propagated_dir=str(prop_dir),
            output_path=str(output),
            fps=16,
        )
    assert export_result["frame_count"] == 10
    assert export_result["fps"] == 16
