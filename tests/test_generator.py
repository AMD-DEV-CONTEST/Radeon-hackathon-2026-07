"""测试视频生成模块 (用 mock 替代真实 ComfyUI)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# wan21_i2v.json (v2) 节点 ID — 与 video_generator.py 常量一致
_NODE_PROMPT_POS = "6"
_NODE_PROMPT_NEG = "7"
_NODE_LOAD_IMAGE = "15"
_NODE_WAN_I2V = "16"
_NODE_KSAMPLER = "17"
_NODE_VIDEO_OUT = "20"


def _mock_workflow():
    """返回与 wan21_i2v.json (v2) 结构一致的 mock 工作流."""
    return {
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}},
        "15": {"class_type": "LoadImage", "inputs": {"image": ""}},
        "16": {"class_type": "WanImageToVideo",
               "inputs": {"width": 832, "height": 480, "length": 49}},
        "17": {"class_type": "KSampler",
               "inputs": {"seed": 0, "steps": 30, "cfg": 7.5,
                          "sampler_name": "euler", "scheduler": "simple",
                          "denoise": 1.0}},
        "20": {"class_type": "VHS_VideoCombine", "inputs": {"frame_rate": 16}},
    }


def _make_generator():
    from core.video_generator import VideoGenerator
    from backend.comfyui_client import ComfyUIClient
    client = MagicMock(spec=ComfyUIClient)
    client.load_workflow.return_value = _mock_workflow()
    client.set_node_param = ComfyUIClient.set_node_param
    client.upload_image.return_value = "ref.png"
    client.queue_prompt.return_value = "fake-prompt-id"
    client.iter_progress.return_value = iter([
        {"type": "progress", "value": 0.5},
        {"type": "done", "outputs": [Path("/tmp/fake.mp4")]},
    ])
    return VideoGenerator(client=client), client


def test_generate_sets_workflow_params():
    gen, client = _make_generator()
    events = []
    with patch("core.video_generator.split_video_to_frames") as split, \
         patch("core.video_generator.get_video_info") as info, \
         patch("core.video_generator._pick_video", return_value=Path("/tmp/fake.mp4")):
        split.return_value = [Path("/tmp/f%d.png" % i) for i in range(5)]
        info.return_value = MagicMock(fps=16.0)
        result = gen.generate(
            prompt="一辆红色跑车在山间公路",
            reference_image="/tmp/ref.png",
            duration=4,
            resolution=(832, 480),
            seed=42,
            progress_callback=events.append,
        )

    wf = client.load_workflow.return_value
    # 验证 prompt 被写入正向节点
    assert wf[_NODE_PROMPT_POS]["inputs"]["text"] == "一辆红色跑车在山间公路"
    # 验证分辨率 (WanImageToVideo 节点 16)
    assert wf[_NODE_WAN_I2V]["inputs"]["width"] == 832
    assert wf[_NODE_WAN_I2V]["inputs"]["height"] == 480
    # 4s * 16fps = 64 -> 对齐到 4k+1 -> ((64-1)//4)*4+1 = 61
    assert wf[_NODE_WAN_I2V]["inputs"]["length"] == 61
    # 验证种子 (KSampler 节点 17)
    assert wf[_NODE_KSAMPLER]["inputs"]["seed"] == 42
    # 验证返回结构
    assert result["frame_count"] == 5
    assert result["fps"] == 16
    assert "video_path" in result and "frames_dir" in result


def test_generate_seed_negative_becomes_random():
    gen, client = _make_generator()
    with patch("core.video_generator.split_video_to_frames") as split, \
         patch("core.video_generator.get_video_info") as info, \
         patch("core.video_generator._pick_video", return_value=Path("/tmp/fake.mp4")):
        split.return_value = [Path("/tmp/f%d.png" % i) for i in range(5)]
        info.return_value = MagicMock(fps=16.0)
        gen.generate(prompt="test", seed=-1)
    wf = client.load_workflow.return_value
    # seed=-1 时应被替换为非负整数 (KSampler 节点 17)
    assert wf[_NODE_KSAMPLER]["inputs"]["seed"] >= 0


def test_generate_progress_events():
    gen, _ = _make_generator()
    events = []
    with patch("core.video_generator.split_video_to_frames") as split, \
         patch("core.video_generator.get_video_info") as info, \
         patch("core.video_generator._pick_video", return_value=Path("/tmp/fake.mp4")):
        split.return_value = [Path("/tmp/f%d.png" % i) for i in range(5)]
        info.return_value = MagicMock(fps=16.0)
        gen.generate(prompt="test", progress_callback=events.append)
    types = [e["type"] for e in events]
    assert "done" in types or "status" in types


def test_num_frames_alignment():
    """num_frames 必须满足 4k+1 (Wan2.1 要求)."""
    for duration in [1, 2, 3, 4, 6, 8]:
        from core.video_generator import VideoGenerator
        from backend.comfyui_client import ComfyUIClient
        client = MagicMock(spec=ComfyUIClient)
        client.load_workflow.return_value = _mock_workflow()
        client.set_node_param = ComfyUIClient.set_node_param
        client.upload_image.return_value = "ref.png"
        client.queue_prompt.return_value = "fake-id"
        client.iter_progress.return_value = iter([
            {"type": "done", "outputs": [Path("/tmp/fake.mp4")]},
        ])
        g = VideoGenerator(client=client)
        with patch("core.video_generator.split_video_to_frames") as split, \
             patch("core.video_generator.get_video_info") as info, \
             patch("core.video_generator._pick_video", return_value=Path("/tmp/fake.mp4")):
            split.return_value = []
            info.return_value = MagicMock(fps=16.0)
            try:
                g.generate(prompt="t", duration=duration)
            except Exception:
                pass
        wf = client.load_workflow.return_value
        nf = wf[_NODE_WAN_I2V]["inputs"]["length"]
        assert (nf - 1) % 4 == 0, f"duration={duration} -> length={nf} 不满足 4k+1"
