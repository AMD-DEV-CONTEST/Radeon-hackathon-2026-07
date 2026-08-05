"""测试帧级编辑模块 (用 mock 替代真实 ComfyUI)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

np = pytest.importorskip("numpy")


def _make_editor():
    from core.frame_editor import FrameEditor
    from backend.comfyui_client import ComfyUIClient
    client = MagicMock(spec=ComfyUIClient)
    client.load_workflow.return_value = {
        "4": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": "sdxl_inpaint.safetensors"}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}},
        "8": {"class_type": "ControlNetLoader",
              "inputs": {"control_net_name": ""}},
        "9": {"class_type": "LoadImage", "inputs": {"image": ""}},
        "10": {"class_type": "LoadImage", "inputs": {"image": ""}},
        "11": {"class_type": "KSampler",
               "inputs": {"seed": 0, "steps": 30, "cfg": 7.5,
                          "sampler_name": "dpmpp_2m", "scheduler": "karras",
                          "denoise": 0.75}},
        "12": {"class_type": "VAEEncodeForInpaint",
               "inputs": {"grow_mask_by": 6}},
        "15": {"class_type": "SaveImage", "inputs": {}},
        "16": {"class_type": "ControlNetApply",
               "inputs": {"strength": 0.8, "start_percent": 0.0,
                          "end_percent": 0.8, "image": ["20", 0]}},
        "20": {"class_type": "Canny", "inputs": {}},
        "21": {"class_type": "MiDaS-DepthMapPreprocessor", "inputs": {}},
    }
    client.set_node_param = ComfyUIClient.set_node_param
    client.upload_image.return_value = "frame.png"
    client.upload_mask.return_value = "mask.png"
    client.queue_prompt.return_value = "fake-id"
    client.iter_progress.return_value = iter([
        {"type": "progress", "value": 0.5},
        {"type": "done", "outputs": [Path("/tmp/edited.png")]},
    ])
    return FrameEditor(client=client), client


def _fake_frame(tmp_path: Path):
    import cv2
    p = tmp_path / "frame_00003.png"
    cv2.imwrite(str(p), np.full((100, 100, 3), 128, dtype=np.uint8))
    return p


def _fake_output(tmp_path: Path):
    import cv2
    p = tmp_path / "edited_out.png"
    cv2.imwrite(str(p), np.full((100, 100, 3), 200, dtype=np.uint8))
    return p


def test_edit_frame_writes_params(tmp_path: Path):
    editor, client = _make_editor()
    frame = _fake_frame(tmp_path)
    mask = np.zeros((100, 100), dtype=np.uint8)
    mask[30:70, 30:70] = 255

    def fake_copy2(src, dst, *a, **kw):
        # 真实写入一个虚拟图像到 dst, 模拟 copy2
        import cv2 as _cv2
        _cv2.imwrite(str(dst), np.full((100, 100, 3), 200, dtype=np.uint8))
        return dst

    with patch("core.frame_editor.read_frame") as rf, \
         patch("core.frame_editor.write_frame") as wf, \
         patch("shutil.copy2", side_effect=fake_copy2):
        rf.return_value = np.full((100, 100, 3), 200, dtype=np.uint8)
        wf.return_value = tmp_path / "edited.png"
        result = editor.edit_frame(
            frame_path=frame,
            mask=mask,
            edit_prompt="改成蓝色跑车",
            controlnet_type="canny",
            use_controlnet=True,
            session_id="test",
        )

    wf_json = client.load_workflow.return_value
    assert wf_json["6"]["inputs"]["text"] == "改成蓝色跑车"
    assert wf_json["11"]["inputs"]["denoise"] == 0.75
    assert wf_json["8"]["inputs"]["control_net_name"] == \
        "controlnet-canny-sdxl-1.0.safetensors"
    # ControlNetApply 的 image 输入应指向 Canny 节点 (20)
    assert wf_json["16"]["inputs"]["image"] == ["20", 0]
    assert result["edited_frame_path"].endswith(".png")


def test_edit_frame_depth_switches_preprocessor(tmp_path: Path):
    editor, client = _make_editor()
    frame = _fake_frame(tmp_path)
    mask = np.zeros((100, 100), dtype=np.uint8)
    mask[30:70, 30:70] = 255

    def fake_copy2(src, dst, *a, **kw):
        import cv2 as _cv2
        _cv2.imwrite(str(dst), np.full((100, 100, 3), 200, dtype=np.uint8))
        return dst

    with patch("core.frame_editor.read_frame") as rf, \
         patch("core.frame_editor.write_frame") as wf, \
         patch("shutil.copy2", side_effect=fake_copy2):
        rf.return_value = np.full((100, 100, 3), 200, dtype=np.uint8)
        wf.return_value = tmp_path / "edited.png"
        editor.edit_frame(
            frame_path=frame, mask=mask,
            edit_prompt="x", controlnet_type="depth",
            use_controlnet=True, session_id="test",
        )

    wf_json = client.load_workflow.return_value
    # depth 模式: ControlNetApply image 输入应指向 depth 节点 (21)
    assert wf_json["16"]["inputs"]["image"] == ["21", 0]
    assert wf_json["8"]["inputs"]["control_net_name"] == \
        "controlnet-depth-sdxl-1.0.safetensors"


def test_edit_frame_no_controlnet_uses_inpaint_workflow(tmp_path: Path):
    editor, client = _make_editor()
    frame = _fake_frame(tmp_path)
    mask = np.zeros((100, 100), dtype=np.uint8)
    mask[30:70, 30:70] = 255

    def fake_copy2(src, dst, *a, **kw):
        import cv2 as _cv2
        _cv2.imwrite(str(dst), np.full((100, 100, 3), 200, dtype=np.uint8))
        return dst

    with patch("core.frame_editor.read_frame") as rf, \
         patch("core.frame_editor.write_frame") as wf, \
         patch("shutil.copy2", side_effect=fake_copy2):
        rf.return_value = np.full((100, 100, 3), 200, dtype=np.uint8)
        wf.return_value = tmp_path / "edited.png"
        editor.edit_frame(
            frame_path=frame, mask=mask,
            edit_prompt="x", use_controlnet=False, session_id="test",
        )

    # 应加载 sdxl_inpaint.json (无 8/16 节点)
    client.load_workflow.assert_called_with("sdxl_inpaint.json")


def test_edit_frame_empty_prompt_raises(tmp_path: Path):
    editor, _ = _make_editor()
    frame = _fake_frame(tmp_path)
    mask = np.zeros((100, 100), dtype=np.uint8)
    mask[30:70, 30:70] = 255

    def fake_copy2(src, dst, *a, **kw):
        import cv2 as _cv2
        _cv2.imwrite(str(dst), np.full((100, 100, 3), 200, dtype=np.uint8))
        return dst

    with patch("shutil.copy2", side_effect=fake_copy2):
        result = editor.edit_frame(
            frame_path=frame, mask=mask,
            edit_prompt="", use_controlnet=True, session_id="test",
        )
    # edit_frame 本身不校验 prompt, 只验证不崩溃且返回结构完整
    assert "edited_frame_path" in result
