"""测试 ComfyUI 客户端的工作流操作 (纯 JSON, 无需网络)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.comfyui_client import ComfyUIClient, ComfyUIError


def test_load_workflow_by_name(tmp_path: Path, monkeypatch):
    """load_workflow 应能按文件名从 WORKFLOWS_DIR 加载."""
    client = ComfyUIClient(base_url="http://localhost:8188",
                           output_dir=tmp_path)
    wf = client.load_workflow("sdxl_inpaint.json")
    assert isinstance(wf, dict)
    assert "6" in wf  # 正向 prompt 节点
    assert wf["6"]["class_type"] == "CLIPTextEncode"


def test_load_workflow_missing(tmp_path: Path):
    client = ComfyUIClient(base_url="http://localhost:8188",
                           output_dir=tmp_path)
    with pytest.raises(ComfyUIError):
        client.load_workflow("not_exist.json")


def test_set_node_param(tmp_path: Path):
    client = ComfyUIClient(base_url="http://localhost:8188",
                           output_dir=tmp_path)
    wf = client.load_workflow("sdxl_inpaint.json")
    ComfyUIClient.set_node_param(wf, "6", "text", "把红色汽车改成蓝色跑车")
    assert wf["6"]["inputs"]["text"] == "把红色汽车改成蓝色跑车"


def test_set_node_param_invalid_node(tmp_path: Path):
    client = ComfyUIClient(base_url="http://localhost:8188",
                           output_dir=tmp_path)
    wf = client.load_workflow("sdxl_inpaint.json")
    with pytest.raises(ComfyUIError):
        ComfyUIClient.set_node_param(wf, "999", "text", "x")


def test_workflow_files_are_valid_json():
    """所有工作流模板应为合法 JSON 且含节点."""
    wf_dir = Path(__file__).resolve().parent.parent / "backend" / "workflows"
    for jf in wf_dir.glob("*.json"):
        with jf.open() as f:
            wf = json.load(f)
        assert isinstance(wf, dict)
        # 至少有一个非 _comment 的节点
        nodes = {k: v for k, v in wf.items() if not k.startswith("_")}
        assert len(nodes) > 0, f"{jf.name} 无有效节点"
