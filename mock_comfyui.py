#!/usr/bin/env python3
"""Mock ComfyUI 服务.

模拟 ComfyUI 的 HTTP API，让 FrameForge 在无 GPU/ComfyUI 环境下也能完整演示。
生成的图片/视频为占位内容（渐变色 + 文字标注）。
"""
from __future__ import annotations

import io
import json
import os
import sys
import time
import uuid
import threading
from pathlib import Path

from flask import Flask, request, jsonify, send_file, Response

import numpy as np
from PIL import Image, ImageDraw, ImageFont

app = Flask(__name__)

# Mock ComfyUI 的输出目录
MOCK_OUTPUT_DIR = Path("/persistent/Radeon-hackathon-2026-07/outputs/mock_comfyui")
MOCK_INPUT_DIR = MOCK_OUTPUT_DIR / "input"
MOCK_OUTPUT_SUB = MOCK_OUTPUT_DIR / "output"
MOCK_OUTPUT_SUB.mkdir(parents=True, exist_ok=True)
MOCK_INPUT_DIR.mkdir(parents=True, exist_ok=True)

# 存储已提交的 prompt 及其结果
_prompts: dict[str, dict] = {}


# ---------------------------------------------------------------------- #
# 辅助：生成占位图片
# ---------------------------------------------------------------------- #
def _make_placeholder_image(
    width: int = 832,
    height: int = 480,
    text: str = "FrameForge",
    color: tuple = (30, 50, 80),
    frame_idx: int = 0,
    total: int = 1,
) -> bytes:
    """生成带渐变背景和文字的占位 PNG."""
    img = Image.new("RGB", (width, height), color)
    draw = ImageDraw.Draw(img)

    # 渐变背景
    for y in range(height):
        ratio = y / height
        r = int(color[0] + ratio * (80 - color[0]))
        g = int(color[1] + ratio * (120 - color[1]))
        b = int(color[2] + ratio * (160 - color[2]))
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    # 文字
    try:
        font_large = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36)
        font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18)
    except Exception:
        font_large = ImageFont.load_default()
        font_small = ImageFont.load_default()

    # 居中大字
    bbox = draw.textbbox((0, 0), text, font=font_large)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(
        ((width - tw) // 2, (height - th) // 2 - 20),
        text, fill=(255, 255, 255), font=font_large,
    )

    # 帧信息
    info = f"Frame {frame_idx} / {total}  ({width}x{height})"
    bbox2 = draw.textbbox((0, 0), info, font=font_small)
    tw2 = bbox2[2] - bbox2[0]
    draw.text(
        ((width - tw2) // 2, (height - th) // 2 + 30),
        info, fill=(200, 200, 200), font=font_small,
    )

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_edited_image(
    width: int = 832,
    height: int = 480,
    text: str = "Edited",
    frame_idx: int = 0,
) -> bytes:
    """生成编辑后的占位图片（暖色调表示已编辑）."""
    return _make_placeholder_image(
        width, height, text, (80, 30, 30), frame_idx, 1,
    )


def _make_video(frames: list[bytes], fps: int = 16) -> bytes:
    """用帧图片合成 MP4（用 ffmpeg）."""
    import subprocess
    import tempfile

    tmpdir = tempfile.mkdtemp()
    for i, frame_data in enumerate(frames):
        with open(f"{tmpdir}/frame_{i:05d}.png", "wb") as f:
            f.write(frame_data)

    output_path = f"{tmpdir}/output.mp4"
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-framerate", str(fps),
             "-i", f"{tmpdir}/frame_%05d.png",
             "-c:v", "libx264", "-pix_fmt", "yuv420p",
             "-movflags", "+faststart",
             output_path],
            capture_output=True, timeout=30,
        )
        with open(output_path, "rb") as f:
            return f.read()
    except Exception:
        # ffmpeg 不可用，返回空 MP4
        return b""


# ---------------------------------------------------------------------- #
# API 端点
# ---------------------------------------------------------------------- #
@app.route("/")
def index():
    return jsonify({"status": "ok", "message": "Mock ComfyUI for FrameForge"})


@app.route("/system_stats")
def system_stats():
    return jsonify({
        "system": {
            "os": "linux",
            "ram_total": 32768,
            "ram_free": 16384,
            "comfyui_version": "0.3.0-mock",
            "python_version": sys.version,
        },
        "devices": [
            {
                "name": "AMD Radeon RX 7900 XTX (Mock)",
                "type": "gpu",
                "memory": 24576,
                "vram_free": 20480,
            }
        ],
    })


@app.route("/upload/image", methods=["POST"])
def upload_image():
    if "image" not in request.files:
        return jsonify({"error": "no image"}), 400

    file = request.files["image"]
    filename = file.filename or f"upload_{uuid.uuid4().hex[:8]}.png"
    save_path = MOCK_INPUT_DIR / filename
    file.save(save_path)
    return jsonify({"name": filename, "subfolder": "", "type": "input"})


@app.route("/prompt", methods=["POST"])
def submit_prompt():
    """接收工作流，异步生成占位结果."""
    data = request.json or {}
    workflow = data.get("prompt", {})
    prompt_id = f"mock-{uuid.uuid4().hex[:12]}"

    # 分析 workflow 类型并生成占位输出
    thread = threading.Thread(
        target=_process_workflow, args=(prompt_id, workflow),
        daemon=True,
    )
    thread.start()

    return jsonify({"prompt_id": prompt_id, "number": 1, "node_errors": {}})


@app.route("/history/<prompt_id>")
def get_history(prompt_id):
    if prompt_id not in _prompts:
        return jsonify({})

    info = _prompts[prompt_id]
    if not info.get("done", False):
        return jsonify({})

    return jsonify({
        prompt_id: {
            "status": {"completed": True, "status_str": "success"},
            "outputs": info.get("outputs", {}),
        }
    })


@app.route("/view")
def view_file():
    filename = request.args.get("filename", "")
    ftype = request.args.get("type", "output")
    subfolder = request.args.get("subfolder", "")

    base = MOCK_OUTPUT_SUB if ftype == "output" else MOCK_INPUT_DIR
    fpath = base / subfolder / filename if subfolder else base / filename

    if not fpath.exists():
        return jsonify({"error": "file not found"}), 404

    return send_file(fpath, mimetype="application/octet-stream")


@app.route("/queue")
def queue_status():
    return jsonify({"queue_remaining": 0, "queue_running": 0})


@app.route("/object_info")
def object_info():
    return jsonify({})


@app.route("/object_info/<node_class>")
def object_info_node(node_class):
    return jsonify({})


# ---------------------------------------------------------------------- #
# 工作流处理
# ---------------------------------------------------------------------- #
def _process_workflow(prompt_id: str, workflow: dict):
    """分析 workflow 类型并生成占位输出."""
    _prompts[prompt_id] = {"done": False, "outputs": {}}

    time.sleep(1.5)  # 模拟处理延迟

    # 检查节点类型判断 workflow 类型
    node_types = {}
    for node_id, node in workflow.items():
        ct = node.get("class_type", "")
        inputs = node.get("inputs", {})
        node_types[node_id] = {"class_type": ct, "inputs": inputs}

    has_wan = any(nt["class_type"] == "WanImageToVideo" for nt in node_types.values())
    has_vae_inpaint = any(nt["class_type"] == "VAEEncodeForInpaint" for nt in node_types.values())

    outputs = {}

    if has_wan:
        # 视频生成：从 WanImageToVideo 节点获取参数
        for nid, nt in node_types.items():
            if nt["class_type"] == "WanImageToVideo":
                inputs = nt["inputs"]
                width = inputs.get("width", 832)
                height = inputs.get("height", 480)
                length = inputs.get("length", 49)
                break
        else:
            width, height, length = 832, 480, 49

        # 生成帧图片
        frame_files = []
        for i in range(1, length + 1):
            fname = f"frame_{i:04d}.png"
            fpath = MOCK_OUTPUT_SUB / fname
            fpath.write_bytes(
                _make_placeholder_image(width, height, "FrameForge", (20, 40, 70), i, length)
            )
            frame_files.append(fname)

        # 生成 MP4
        video_fname = "output_video.mp4"
        video_path = MOCK_OUTPUT_SUB / video_fname

        # 用 ffmpeg 合成视频
        import subprocess
        import tempfile

        tmpdir = tempfile.mkdtemp()
        for i, fname in enumerate(frame_files):
            src = MOCK_OUTPUT_SUB / fname
            import shutil
            shutil.copy(src, f"{tmpdir}/frame_{i:05d}.png")

        try:
            subprocess.run(
                ["ffmpeg", "-y", "-framerate", "16",
                 "-i", f"{tmpdir}/frame_%05d.png",
                 "-c:v", "libx264", "-pix_fmt", "yuv420p",
                 "-movflags", "+faststart", str(video_path)],
                capture_output=True, timeout=30,
            )
        except Exception:
            pass

        # 找到 VHS_VideoCombine 节点
        for nid, nt in node_types.items():
            if "Video" in nt["class_type"] or "VHS" in nt["class_type"]:
                outputs[nid] = {
                    "videos": [{"filename": video_fname, "subfolder": "", "type": "output"}],
                    "images": [{"filename": frame_files[-1], "subfolder": "", "type": "output"}],
                }
                break
        else:
            # 默认输出到最后一个节点
            last_nid = list(workflow.keys())[-1]
            outputs[last_nid] = {
                "images": [{"filename": frame_files[0], "subfolder": "", "type": "output"}],
                "videos": [{"filename": video_fname, "subfolder": "", "type": "output"}],
            }

    elif has_vae_inpaint:
        # 图片编辑：生成编辑后的占位图
        for nid, nt in node_types.items():
            if nt["class_type"] == "VAEEncodeForInpaint":
                inputs = nt["inputs"]
                # 从 pixels 获取尺寸信息（但这里只是 mock）
                break

        # 查找 SaveImage 节点
        for nid, nt in node_types.items():
            if nt["class_type"] == "SaveImage":
                edited_fname = f"edited_{prompt_id[:8]}.png"
                edited_path = MOCK_OUTPUT_SUB / edited_fname
                edited_path.write_bytes(
                    _make_edited_image(832, 480, "Edited", 0)
                )
                outputs[nid] = {
                    "images": [{"filename": edited_fname, "subfolder": "", "type": "output"}],
                }
                break
        else:
            last_nid = list(workflow.keys())[-1]
            edited_fname = f"edited_{prompt_id[:8]}.png"
            edited_path = MOCK_OUTPUT_SUB / edited_fname
            edited_path.write_bytes(
                _make_edited_image(832, 480, "Edited", 0)
            )
            outputs[last_nid] = {
                "images": [{"filename": edited_fname, "subfolder": "", "type": "output"}],
            }

    else:
        # 默认：生成一张占位图
        last_nid = list(workflow.keys())[-1]
        placeholder_fname = f"output_{prompt_id[:8]}.png"
        placeholder_path = MOCK_OUTPUT_SUB / placeholder_fname
        placeholder_path.write_bytes(
            _make_placeholder_image(832, 480, "FrameForge")
        )
        outputs[last_nid] = {
            "images": [{"filename": placeholder_fname, "subfolder": "", "type": "output"}],
        }

    _prompts[prompt_id] = {"done": True, "outputs": outputs}


# ---------------------------------------------------------------------- #
# 主入口
# ---------------------------------------------------------------------- #
if __name__ == "__main__":
    port = int(os.environ.get("MOCK_COMFYUI_PORT", "8188"))
    print(f"""
============================================================
  Mock ComfyUI 服务启动
  地址: http://127.0.0.1:{port}
  输出目录: {MOCK_OUTPUT_SUB}
============================================================
""")
    app.run(host="0.0.0.0", port=port, threaded=True)
