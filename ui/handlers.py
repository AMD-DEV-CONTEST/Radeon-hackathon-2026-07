"""Gradio 事件处理函数.

持有会话状态, 将 UI 事件转发给 core 模块。
所有 handler 接收 ``FrameForgeSession`` state (gr.State) 作为首参或末参。

当 ComfyUI 不可用时自动切换到 Mock 模式（生成占位图片/视频），
让用户可以完整体验 UI 流程。
"""
from __future__ import annotations

import io
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from config import CONFIG
from core.edit_propagator import EditPropagator
from core.frame_editor import FrameEditor
from core.frame_utils import (
    count_frames,
    ensure_session_dirs,
    frame_path,
    list_frames,
)
from core.video_composer import VideoComposer
from core.video_generator import VideoGenerator
from utils.gpu_monitor import format_gpu_status, get_gpu_info
from utils.image_utils import (
    color_regions,
    extract_regions,
    normalize_mask,
    point_to_region_mask,
    regions_to_mask,
)
from utils.video_utils import read_frame


# ---------------------------------------------------------------------- #
# Mock 模式：ComfyUI 不可用时生成占位内容
# ---------------------------------------------------------------------- #
def _check_comfyui() -> bool:
    """检查 ComfyUI 是否可用."""
    from backend.comfyui_client import get_default_client
    try:
        return get_default_client().health()
    except Exception:
        return False


def _mock_generate_frames(
    session_id: str, prompt: str, duration: int,
    resolution: tuple, fps: int,
) -> dict:
    """生成帧 + MP4。ComfyUI 可用时用 SDXL txt2img 真实生成，否则画占位图。"""
    from PIL import Image, ImageDraw, ImageFont

    dirs = ensure_session_dirs(session_id)
    frames_dir = dirs["frames"]
    width, height = resolution
    num_frames = max(9, int(duration * fps))
    num_frames = ((num_frames - 1) // 4) * 4 + 1  # 4k+1

    # 尝试用 ComfyUI + SDXL 生成真实图片
    use_comfyui = _check_comfyui()
    base_image = None

    if use_comfyui:
        try:
            import json, requests, time as _time
            from backend.comfyui_client import ComfyUIClient

            client = ComfyUIClient("http://127.0.0.1:8188",
                                   output_dir=dirs["frames"])
            workflow = client.load_workflow("sdxl_txt2img.json")
            client.set_node_param(workflow, "6", "text", prompt)
            client.set_node_param(workflow, "7", "text",
                "blurry, low quality, watermark, text, deformed, frameforge, label")
            client.set_node_param(workflow, "5", "width", width)
            client.set_node_param(workflow, "5", "height", height)
            client.set_node_param(workflow, "11", "seed",
                                  int(_time.time()) % (2**31))

            prompt_id = client.queue_prompt(workflow)
            # 轮询等待结果
            for _ in range(60):
                _time.sleep(2)
                hist = client.get_history(prompt_id)
                if hist:
                    outputs = client.get_output(prompt_id)
                    if outputs:
                        base_image = Image.open(outputs[0]).convert("RGB")
                        break
        except Exception:
            base_image = None

    for i in range(1, num_frames + 1):
        if base_image is not None:
            # 用 SDXL 生成的真实图片，加轻微亮度变化模拟视频
            img = base_image.copy()
            arr = np.array(img)
            factor = 1.0 + 0.05 * (i - num_frames / 2) / num_frames
            arr = (arr * factor).clip(0, 255).astype(np.uint8)
            img = Image.fromarray(arr)
        else:
            # 回退：画占位图（不含 FrameForge 文字）
            img = Image.new("RGB", (width, height), (30, 40, 70))
            draw = ImageDraw.Draw(img)
            for y in range(height):
                ratio = y / height
                r = int(20 + ratio * 60)
                g = int(30 + ratio * 80)
                b = int(60 + ratio * 100)
                draw.line([(0, y), (width, y)], fill=(r, g, b))

        img.save(frames_dir / f"frame_{i:05d}.png")

    # 生成占位 MP4
    import subprocess
    video_path = CONFIG.output_dir / f"{session_id}.mp4"
    video_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y", "-framerate", str(fps),
        "-i", str(frames_dir / "frame_%05d.png"),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", str(video_path),
    ]
    subprocess.run(cmd, capture_output=True, timeout=30)

    return {
        "video_path": str(video_path),
        "frames_dir": str(frames_dir),
        "frame_count": num_frames,
        "fps": fps,
        "session_id": session_id,
        "seed": 0,
    }


def _mock_edit_frame(
    frame_path_str: str, edit_prompt: str,
    session_id: str,
) -> dict:
    """生成编辑后的占位图."""
    from PIL import Image, ImageDraw, ImageFont

    # 读取原始帧
    orig = Image.open(frame_path_str).convert("RGB")
    w, h = orig.size

    # 在原图上叠加暖色调 + 文字
    overlay = Image.new("RGB", (w, h), (80, 40, 30))
    blended = Image.blend(orig, overlay, alpha=0.4)
    draw = ImageDraw.Draw(blended)

    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 28)
    except Exception:
        font = ImageFont.load_default()

    short = edit_prompt[:25] + "..." if len(edit_prompt) > 25 else edit_prompt
    draw.text((w // 2 - 100, h // 2 - 20), "EDITED", fill=(255, 200, 100), font=font)
    draw.text((w // 2 - 120, h // 2 + 20), short, fill=(255, 220, 150), font=font)

    # 保存
    dirs = ensure_session_dirs(session_id)
    edited_path = dirs["edited"] / f"edited_{Path(frame_path_str).stem}.png"
    blended.save(edited_path)

    # 保存 mask（全白占位）
    mask = Image.new("L", (w, h), 255)
    mask_path = dirs["masks"] / f"mask_{Path(frame_path_str).stem}.png"
    mask.save(mask_path)

    return {
        "edited_frame_path": str(edited_path),
        "mask_path": str(mask_path),
    }


def _mock_propagate(state, idx: int, propagation_range: int):
    """Mock 传播：复制编辑图到相邻帧."""
    from PIL import Image
    import shutil

    dirs = ensure_session_dirs(state.session_id)
    prop_dir = dirs["propagated"]
    state.propagated_dir = str(prop_dir)
    state.propagated_indices = []

    edited_path = state.edited_frames.get(idx)
    if not edited_path or not Path(edited_path).exists():
        return

    edited_img = Image.open(edited_path)
    start = max(1, idx - propagation_range)
    end = min(state.frame_count, idx + propagation_range)

    for i in range(start, end + 1):
        if i == idx:
            continue
        # 复制编辑图到传播目录（轻微变暗模拟传播质量下降）
        frame = edited_img.copy()
        # 根据距离调整亮度
        dist = abs(i - idx)
        factor = 1.0 - 0.1 * dist / propagation_range
        if factor < 0.5:
            factor = 0.5
        import numpy as np
        arr = np.array(frame)
        arr = (arr * factor).clip(0, 255).astype(np.uint8)
        frame = Image.fromarray(arr)
        frame.save(prop_dir / f"frame_{i:05d}.png")
        state.propagated_indices.append(i)


# ---------------------------------------------------------------------- #
# 会话状态
# ---------------------------------------------------------------------- #
@dataclass
class FrameForgeSession:
    """单次用户会话的状态."""
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    # 视频生成结果
    video_path: str | None = None
    original_video_path: str | None = None   # 用于抽音轨
    frames_dir: str | None = None
    frame_count: int = 0
    fps: int = 16
    resolution: tuple[int, int] = (832, 480)

    # 选帧 / 编辑
    current_frame_index: int = 1
    edited_frames: dict[int, str] = field(default_factory=dict)   # idx -> path
    masks: dict[int, str] = field(default_factory=dict)           # idx -> path

    # 传播
    propagated_dir: str | None = None
    propagated_indices: list[int] = field(default_factory=list)
    low_quality_frames: list[int] = field(default_factory=list)

    # 懒加载的模块实例
    _generator: VideoGenerator | None = None
    _editor: FrameEditor | None = None
    _propagator: EditPropagator | None = None
    _composer: VideoComposer | None = None

    # 最后一次输出
    output_video_path: str | None = None

    # 编辑后端 (跟随生成后端: sdxl / minimax_h3)
    _edit_backend: str = "sdxl"

    # 区域选择 (替代画笔)
    region_labels: np.ndarray | None = None  # 当前帧的区域标签图
    selected_regions: list = None  # 选中的区域编号列表

    def __post_init__(self):
        if self.selected_regions is None:
            self.selected_regions = []

    def generator(self) -> VideoGenerator:
        if self._generator is None:
            self._generator = VideoGenerator()
        return self._generator

    def editor(self) -> FrameEditor:
        if self._editor is None:
            self._editor = FrameEditor()
        return self._editor

    def propagator(self) -> EditPropagator:
        if self._propagator is None:
            self._propagator = EditPropagator()
        return self._propagator

    def composer(self) -> VideoComposer:
        if self._composer is None:
            self._composer = VideoComposer()
        return self._composer

    def has_video(self) -> bool:
        return self.frames_dir is not None and self.frame_count > 0


# ---------------------------------------------------------------------- #
# 全局会话持久化 — 断线重连后自动恢复
# ---------------------------------------------------------------------- #
_GLOBAL_SESSION: dict = {}


def _sync_to_global(session: FrameForgeSession):
    """把 session 的可序列化字段同步到全局存储。"""
    _GLOBAL_SESSION.update({
        "session_id": session.session_id,
        "video_path": session.video_path,
        "original_video_path": session.original_video_path,
        "frames_dir": session.frames_dir,
        "frame_count": session.frame_count,
        "fps": session.fps,
        "resolution": session.resolution,
        "current_frame_index": session.current_frame_index,
        "edited_frames": dict(session.edited_frames),
        "masks": dict(session.masks),
        "propagated_dir": session.propagated_dir,
        "propagated_indices": list(session.propagated_indices),
        "_edit_backend": session._edit_backend,
        "output_video_path": session.output_video_path,
    })


def _restore_from_global(session: FrameForgeSession):
    """从全局存储恢复 session 字段。"""
    if not _GLOBAL_SESSION:
        return
    session.session_id = _GLOBAL_SESSION.get("session_id", session.session_id)
    session.video_path = _GLOBAL_SESSION.get("video_path")
    session.original_video_path = _GLOBAL_SESSION.get("original_video_path")
    session.frames_dir = _GLOBAL_SESSION.get("frames_dir")
    session.frame_count = _GLOBAL_SESSION.get("frame_count", 0)
    session.fps = _GLOBAL_SESSION.get("fps", 16)
    session.resolution = _GLOBAL_SESSION.get("resolution", (832, 480))
    session.current_frame_index = _GLOBAL_SESSION.get("current_frame_index", 1)
    session.edited_frames = dict(_GLOBAL_SESSION.get("edited_frames", {}))
    session.masks = dict(_GLOBAL_SESSION.get("masks", {}))
    session.propagated_dir = _GLOBAL_SESSION.get("propagated_dir")
    session.propagated_indices = list(_GLOBAL_SESSION.get("propagated_indices", []))
    session._edit_backend = _GLOBAL_SESSION.get("_edit_backend", "sdxl")
    session.output_video_path = _GLOBAL_SESSION.get("output_video_path")


def handle_restore_session(st: FrameForgeSession | None = None):
    """页面加载/重连时恢复 UI 状态。"""
    import gradio as gr
    st = st or FrameForgeSession()
    if not _GLOBAL_SESSION or not _GLOBAL_SESSION.get("frames_dir"):
        return (st, None, gr.Slider(minimum=1, maximum=2, value=1),
                None, None, "")

    _restore_from_global(st)

    # 重建 UI 组件
    gallery = _build_gallery(st) if st.has_video() else None
    frame = _load_frame(st, st.current_frame_index) if st.has_video() else None
    max_f = max(2, st.frame_count)
    idx = min(st.current_frame_index, max_f)

    # 区域标注
    region_canvas = None
    region_info = ""
    if frame is not None:
        try:
            labels = extract_regions(frame)
            st.region_labels = labels
            region_canvas = color_regions(frame, labels)
            region_info = f"已自动提取区域，点击右侧图片选择编辑区域"
        except Exception:
            pass

    slider = gr.Slider(minimum=1, maximum=max_f, value=idx)
    return st, gallery, slider, frame, region_canvas, region_info


# ---------------------------------------------------------------------- #
# GPU 状态
# ---------------------------------------------------------------------- #
def handler_gpu_status() -> str:
    return format_gpu_status(get_gpu_info())


def handler_comfyui_status() -> str:
    from backend.comfyui_client import get_default_client
    try:
        client = get_default_client()
        ok = client.health()
        if ok:
            return f"ComfyUI: 已连接 ({client.base_url})"
        else:
            return f"ComfyUI: 未连接 -> Mock 模式 ({client.base_url})"
    except Exception:
        return "ComfyUI: 未连接 -> Mock 模式"


# ---------------------------------------------------------------------- #
# Step 1: 生成 / 导入
# ---------------------------------------------------------------------- #
def handle_generate(
    prompt: str,
    reference_image,
    duration: int,
    resolution_choice: str,
    seed: int,
    state: FrameForgeSession | None = None,
    progress=None,
    backend: str = "wan21",
    steps: int | None = None,
):
    """生成视频并拆帧, 返回时间轴/gallery/帧预览等更新."""
    state = state or FrameForgeSession()

    if not prompt or not prompt.strip():
        return state, "请输入提示词", None, 1, None, None

    # 解析分辨率
    res_map = {
        "832x480": (832, 480),
        "1280x720": (1280, 720),
        "480x832": (480, 832),
    }
    resolution = res_map.get(resolution_choice, (832, 480))

    # 进度回调
    progress_log: list[str] = []

    def cb(ev):
        if ev.get("type") == "status":
            progress_log.append(ev.get("message", ""))
            if progress is not None:
                msg = ev.get("message", "")
                progress(0.1, desc=msg)
        elif ev.get("type") == "progress":
            if progress is not None:
                progress(0.1 + 0.8 * ev.get("value", 0),
                         desc=ev.get("message", ""))

    try:
        # 检查 ComfyUI 是否可用
        comfyui_ok = _check_comfyui()
        use_mock = not comfyui_ok

        if comfyui_ok:
            # 真实模式：尝试调用 Wan2.1 生成
            try:
                ref_path = None
                if reference_image is not None:
                    ref_path = _save_pil_or_path(reference_image)

                result = state.generator().generate(
                    prompt=prompt.strip(),
                    reference_image=ref_path,
                    duration=int(duration),
                    resolution=resolution,
                    seed=int(seed),
                    fps=state.fps,
                    session_id=state.session_id,
                    progress_callback=cb,
                    backend=backend,
                    steps=steps,
                )
            except Exception as gen_e:
                # Wan2.1 模型不可用，回退到 Mock 生成
                use_mock = True
                if progress is not None:
                    progress(0.1, desc=f"Wan2.1 不可用({gen_e}), 切换 Mock 生成...")

        if use_mock:
            # Mock 模式生成占位帧
            if progress is not None:
                progress(0.2, desc="生成占位帧...")
            time.sleep(0.5)

            result = _mock_generate_frames(
                session_id=state.session_id,
                prompt=prompt.strip(),
                duration=int(duration),
                resolution=resolution,
                fps=state.fps,
            )

            if progress is not None:
                progress(0.8, desc="合成视频...")
                progress(1.0, desc="完成")

        state.video_path = result["video_path"]
        state.original_video_path = result["video_path"]
        state.frames_dir = result["frames_dir"]
        state.frame_count = result["frame_count"]
        state.fps = result["fps"]
        state.resolution = resolution
        state.current_frame_index = 1
        state.edited_frames.clear()
        state.masks.clear()
        state.propagated_dir = None
        state.propagated_indices.clear()
        # 编辑后端跟随生成后端
        state._edit_backend = "minimax_h3" if backend == "minimax_h3" else "sdxl"

        # 构建时间轴缩略图 gallery
        gallery = _build_gallery(state)
        # 当前帧预览
        first_frame = _load_frame(state, 1)
        if use_mock and comfyui_ok:
            mode_tag = "Mock帧 + ComfyUI编辑"
        elif use_mock:
            mode_tag = "Mock 模式"
        else:
            mode_tag = "ComfyUI"
        status = (f"[{mode_tag}] 生成完成: {state.frame_count} 帧, "
                  f"{state.fps} fps, {Path(state.video_path).name}")
        return state, status, gallery, 1, first_frame

    except Exception as e:
        err = f"生成失败: {e}"
        return state, err, None, 1, None


def handle_import_video(video_file, state: FrameForgeSession | None = None):
    """导入已有视频 (而非生成)."""
    state = state or FrameForgeSession()
    if video_file is None:
        return state, "请上传视频文件", None, 1, None
    from core.frame_utils import ensure_session_dirs
    from utils.video_utils import (
        VideoError, get_video_info, split_video_to_frames,
    )

    try:
        video_path = Path(video_file if isinstance(video_file, str)
                          else getattr(video_file, "name", video_file))
        state.original_video_path = str(video_path)
        dirs = ensure_session_dirs(state.session_id)
        frames = split_video_to_frames(video_path, dirs["frames"])
        info = get_video_info(video_path)
        state.video_path = str(video_path)
        state.frames_dir = str(dirs["frames"])
        state.frame_count = len(frames)
        state.fps = int(info.fps) if info.fps > 0 else 16
        state.resolution = (info.width, info.height)
        state.current_frame_index = 1
        state.edited_frames.clear()
        state.masks.clear()
        state.propagated_dir = None

        gallery = _build_gallery(state)
        first_frame = _load_frame(state, 1)
        status = (f"导入完成: {state.frame_count} 帧, {state.fps} fps, "
                  f"{video_path.name}")
        return state, status, gallery, 1, first_frame
    except Exception as e:
        return state, f"导入失败: {e}", None, 1, None


# ---------------------------------------------------------------------- #
# Step 2: 选帧 + 编辑
# ---------------------------------------------------------------------- #
def handle_frame_select(
    frame_index: int,
    state: FrameForgeSession | None = None,
):
    """时间轴滑块变化: 返回当前帧预览 + 区域标注画布 + 区域信息.

    替代旧画笔: 加载帧后自动 ``extract_regions`` 提取连通区域,
    ``color_regions`` 生成可点击的标注图, 标签存入 ``state.region_labels``。
    """
    state = state or FrameForgeSession()
    if not state.has_video():
        state.region_labels = None
        state.selected_regions = []
        return state, "请先生成或导入视频", None, None, None
    idx = int(frame_index)
    idx = max(1, min(state.frame_count, idx))
    state.current_frame_index = idx

    # 优先显示已编辑/已传播的帧
    frame_img = _load_frame_for_display(state, idx)

    # 提取连通区域并用颜色标注 (替代旧画笔)
    region_canvas = None
    region_info = ""
    if frame_img is not None:
        try:
            labels = extract_regions(frame_img)
            state.region_labels = labels
            state.selected_regions = []
            region_canvas = _render_region_canvas(state, frame_img, labels)
            num_regions = int(labels.max())
            region_info = (
                f"检测到 {num_regions} 个区域; "
                f"点击画面中的彩色区域以选择要编辑的范围"
            )
        except Exception as e:
            state.region_labels = None
            state.selected_regions = []
            region_canvas = frame_img
            region_info = f"区域提取失败: {e}"
    else:
        state.region_labels = None
        state.selected_regions = []
        region_info = "无法加载该帧"

    status = f"当前帧: {idx} / {state.frame_count}"
    return state, status, frame_img, region_canvas, region_info


def _render_region_canvas(
    state: FrameForgeSession,
    frame_img: np.ndarray | None = None,
    labels: np.ndarray | None = None,
) -> np.ndarray | None:
    """渲染区域标注图: 所有区域半透明着色, 选中的区域加亮高光.

    未选中区域使用 alpha=0.3 着色; 选中区域向白色混合 (alpha=0.5)
    以呈现更亮的高光, 便于辨认。
    """
    if labels is None:
        labels = state.region_labels
    if labels is None:
        return frame_img
    if frame_img is None:
        frame_img = _load_frame(state, state.current_frame_index)
    if frame_img is None:
        return None

    canvas = color_regions(frame_img, labels, alpha=0.3)

    if state.selected_regions:
        arr = canvas.astype(np.float32)
        for rid in state.selected_regions:
            if rid <= 0:
                continue
            rmask = labels == rid
            if not rmask.any():
                continue
            # 选中区域叠加更亮的高光 (向白色混合)
            arr[rmask] = arr[rmask] * 0.5 + 255.0 * 0.5
        canvas = np.clip(arr, 0, 255).astype(np.uint8)

    return canvas


def _region_summary(state: FrameForgeSession) -> str:
    """返回已选区域的文字摘要."""
    if not state.selected_regions:
        return "未选区域"
    ids = sorted(int(r) for r in state.selected_regions)
    return "已选区域: " + ", ".join(str(i) for i in ids)


def handle_region_click(evt, state: FrameForgeSession | None = None):
    """点击区域标注图: 切换该区域的选中状态.

    接收 gradio SelectData 事件, ``evt.index`` 为 ``[x, y]`` 坐标。
    使用 ``point_to_region_mask`` 定位点击命中的区域, 并在
    ``state.selected_regions`` 中切换其编号。
    返回 ``(state, region_canvas, summary)``。
    """
    state = state or FrameForgeSession()
    if state.region_labels is None:
        return state, None, "请先选择帧"

    idx = evt.index if evt is not None else None
    if not idx or len(idx) < 2:
        return state, _render_region_canvas(state), _region_summary(state)

    x, y = int(idx[0]), int(idx[1])
    labels = state.region_labels
    h, w = labels.shape[:2]
    if x < 0 or x >= w or y < 0 or y >= h:
        return state, _render_region_canvas(state), _region_summary(state)

    # 用 point_to_region_mask 找到点击位置所属区域
    clicked_mask = point_to_region_mask((x, y), labels)
    region_id = int(labels[y, x])

    if region_id == 0 or clicked_mask.max() == 0:
        # 点中背景, 不做切换
        return state, _render_region_canvas(state), _region_summary(state)

    if region_id in state.selected_regions:
        state.selected_regions.remove(region_id)
    else:
        state.selected_regions.append(region_id)

    region_canvas = _render_region_canvas(state)
    summary = _region_summary(state)
    return state, region_canvas, summary


def _get_frame_filepath(state: FrameForgeSession, idx: int):
    """返回 ImageEditor 兼容的字典格式（避免读取大图到内存）."""
    if not state.has_video():
        return None
    fp = None
    if state.propagated_dir:
        p = frame_path(idx, state.propagated_dir)
        if Path(p).exists():
            fp = p
    if fp is None and idx in state.edited_frames and Path(state.edited_frames[idx]).exists():
        fp = state.edited_frames[idx]
    if fp is None:
        p = frame_path(idx, state.frames_dir)
        if Path(p).exists():
            fp = p
    if fp is None:
        return None
    return {"background": str(fp), "layers": [], "composite": str(fp)}


def handle_apply_edit(
    edit_prompt: str,
    controlnet_type: str,
    denoise_strength: float,
    use_controlnet: bool,
    propagation_range: int,
    auto_propagate: bool,
    prop_mode: str = "bidirectional",
    state: FrameForgeSession | None = None,
    progress=None,
):
    """应用局部重绘 + (可选) 自动传播.

    使用 ``state.selected_regions`` + ``regions_to_mask`` 生成编辑 mask
    (替代旧画笔 sketch)。``prop_mode`` 控制传播方向:
    ``"none"`` / ``"forward"`` / ``"bidirectional"``。
    """
    state = state or FrameForgeSession()
    if not state.has_video():
        return state, "请先生成或导入视频", None, None, None, None

    if not edit_prompt or not edit_prompt.strip():
        return state, "请输入编辑提示词", None, None, None, None

    idx = state.current_frame_index
    # 从已选区域生成 mask (替代旧画笔 sketch)
    if state.region_labels is None or not state.selected_regions:
        return state, "请先在画面上点击选择要编辑的区域", None, None, None, None
    mask = regions_to_mask(state.region_labels, state.selected_regions)
    if mask is None or mask.max() == 0:
        return state, "所选区域无效, 请重新点击选择", None, None, None, None

    orig_frame_path = frame_path(idx, state.frames_dir)

    def cb(ev):
        if progress is not None:
            if ev.get("type") == "status":
                progress(0.05, desc=ev.get("message", ""))
            elif ev.get("type") == "progress":
                progress(0.05 + 0.3 * ev.get("value", 0),
                         desc=ev.get("message", ""))

    try:
        # 检查 ComfyUI 是否可用
        comfyui_ok = _check_comfyui()

        if not comfyui_ok:
            # Mock 模式
            if progress is not None:
                progress(0.2, desc="Mock 模式: 生成编辑图...")
            time.sleep(0.5)

            result = _mock_edit_frame(
                frame_path_str=orig_frame_path,
                edit_prompt=edit_prompt.strip(),
                session_id=state.session_id,
            )
            if progress is not None:
                progress(0.5, desc="Mock 模式: 编辑完成")
        else:
            # 真实模式
            result = state.editor().edit_frame(
                frame_path=orig_frame_path,
                mask=mask,
                edit_prompt=edit_prompt.strip(),
                controlnet_type=controlnet_type,
                denoising_strength=float(denoise_strength),
                use_controlnet=bool(use_controlnet),
                session_id=state.session_id,
                progress_callback=cb,
                backend=getattr(state, '_edit_backend', 'sdxl'),
            )

        edited_path = result["edited_frame_path"]
        state.edited_frames[idx] = edited_path
        state.masks[idx] = result["mask_path"]

        edited_img = read_frame(edited_path)

        # 自动传播: ComfyUI 可用时尝试真实 RAFT 传播, 失败则回退到 Mock
        propagated_gallery = None
        propagate_status = ""
        if auto_propagate and prop_mode != "none":
            direction = (
                prop_mode if prop_mode in ("forward", "backward", "bidirectional")
                else "bidirectional"
            )
            try:
                _do_propagate(state, idx, mask, propagation_range, progress,
                              direction=direction)
                propagated_gallery = _build_gallery(state, use_propagated=True)
                propagate_status = (
                    f"传播完成({direction}): {len(state.propagated_indices)} 帧"
                )
            except Exception as prop_e:
                # RAFT 传播失败 (如 ROCm segfault), 回退到 Mock 传播
                _mock_propagate(state, idx, propagation_range)
                propagated_gallery = _build_gallery(state, use_propagated=True)
                propagate_status = (
                    f"传播完成(Mock): {len(state.propagated_indices)} 帧 "
                    f"(RAFT 不可用: {prop_e})"
                )

        before_img = _load_frame(state, idx)
        mode_tag = "Mock" if not comfyui_ok else "ComfyUI"
        status = f"[{mode_tag}] 第 {idx} 帧重绘完成. {propagate_status}"
        if progress is not None:
            progress(1.0, desc="完成")
        return state, status, edited_img, before_img, edited_img, propagated_gallery

    except Exception as e:
        return state, f"编辑失败: {e}", None, None, None, None


def handle_propagate(
    propagation_range: int,
    state: FrameForgeSession | None = None,
    progress=None,
):
    """手动触发传播 (基于最近一次编辑)."""
    state = state or FrameForgeSession()
    if not state.edited_frames:
        return state, "请先对某帧应用编辑", None
    idx = state.current_frame_index
    if idx not in state.edited_frames:
        # 用最近编辑的帧
        idx = max(state.edited_frames.keys())
        state.current_frame_index = idx

    # 重新加载 mask
    mask = _load_mask(state, idx)
    if mask is None:
        return state, "找不到该帧的 mask", None

    try:
        _do_propagate(state, idx, mask, propagation_range, progress)
        gallery = _build_gallery(state, use_propagated=True)
        status = (f"传播完成: {len(state.propagated_indices)} 帧, "
                  f"低质量 {len(state.low_quality_frames)} 帧")
        return state, status, gallery
    except Exception as e:
        return state, f"传播失败: {e}", None


def _do_propagate(state, idx, mask, propagation_range, progress,
                  direction="bidirectional"):
    """执行传播 (内部).

    ``direction`` 透传给 ``EditPropagator.propagate``, 取值
    ``"forward"`` / ``"backward"`` / ``"bidirectional"``。
    """
    def cb(ev):
        if progress is not None:
            if ev.get("type") == "progress":
                # 传播阶段占 0.35-1.0
                progress(0.35 + 0.65 * ev.get("value", 0),
                         desc=ev.get("message", ""))

    edited_path = state.edited_frames[idx]
    result = state.propagator().propagate(
        edited_frame_path=edited_path,
        original_frames_dir=state.frames_dir,
        frame_index=idx,
        mask=mask,
        propagation_range=int(propagation_range),
        session_id=state.session_id,
        progress_callback=cb,
        direction=direction,
    )
    state.propagated_dir = result["propagated_frames_dir"]
    state.propagated_indices = result["propagated_indices"]
    state.low_quality_frames = result["low_quality_frames"]
    return result


# ---------------------------------------------------------------------- #
# Step 3: 对比 + 导出
# ---------------------------------------------------------------------- #
def handle_compare(
    frame_index: int,
    state: FrameForgeSession | None = None,
):
    """返回某帧的修改前 / 修改后."""
    state = state or FrameForgeSession()
    idx = int(frame_index)
    before = _load_frame(state, idx)
    after = _load_frame_for_display(state, idx)
    return state, before, after


def handle_export(
    keep_audio: bool,
    state: FrameForgeSession | None = None,
    progress=None,
):
    """导出最终视频."""
    state = state or FrameForgeSession()
    if not state.has_video():
        return state, "请先生成或导入视频", None

    if progress is not None:
        progress(0.3, desc="合成帧序列...")

    try:
        if keep_audio and state.original_video_path:
            result = state.composer().compose_with_original_audio(
                original_video_path=state.original_video_path,
                original_frames_dir=state.frames_dir,
                edited_indices=state.edited_frames,
                propagated_dir=state.propagated_dir,
                fps=state.fps,
                session_id=state.session_id,
            )
        else:
            result = state.composer().compose(
                original_frames_dir=state.frames_dir,
                edited_indices=state.edited_frames,
                propagated_dir=state.propagated_dir,
                fps=state.fps,
                session_id=state.session_id,
            )
        state.output_video_path = result["output_video_path"]
        if progress is not None:
            progress(1.0, desc="导出完成")
        status = (f"导出完成: {Path(result['output_video_path']).name} "
                  f"({result['frame_count']} 帧, "
                  f"{'含音轨' if result['has_audio'] else '无音轨'})")
        return state, status, result["output_video_path"]
    except Exception as e:
        return state, f"导出失败: {e}", None


# ---------------------------------------------------------------------- #
# 辅助
# ---------------------------------------------------------------------- #
def _save_pil_or_path(image) -> str | None:
    """把 gr.Image 输出 (路径或 PIL) 统一存为临时文件."""
    if image is None:
        return None
    if isinstance(image, str):
        return image
    # PIL Image 或 ndarray
    from PIL import Image
    if isinstance(image, np.ndarray):
        pil = Image.fromarray(image)
    elif isinstance(image, Image.Image):
        pil = image
    else:
        return None
    tmp = Path(CONFIG.output_dir) / f"ref_{uuid.uuid4().hex[:8]}.png"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    pil.save(tmp)
    return str(tmp)


def _load_frame(state: FrameForgeSession, idx: int):
    """加载原始帧."""
    if not state.has_video():
        return None
    p = frame_path(idx, state.frames_dir)
    if not Path(p).exists():
        return None
    return read_frame(p)


def _load_frame_for_display(state: FrameForgeSession, idx: int):
    """加载用于显示的帧 (优先 propagated > edited > original)."""
    if not state.has_video():
        return None
    if state.propagated_dir:
        p = frame_path(idx, state.propagated_dir)
        if Path(p).exists():
            return read_frame(p)
    if idx in state.edited_frames and Path(state.edited_frames[idx]).exists():
        return read_frame(state.edited_frames[idx])
    return _load_frame(state, idx)


def _load_mask(state: FrameForgeSession, idx: int):
    """加载已保存的 mask."""
    if idx in state.masks and Path(state.masks[idx]).exists():
        from utils.video_utils import read_frame
        # mask 是单通道, read_frame 返回 RGB; 取一通道
        m = read_frame(state.masks[idx])
        return normalize_mask(m)
    return None


def _build_gallery(state: FrameForgeSession, use_propagated: bool = False):
    """构建时间轴缩略图 gallery。返回文件路径列表（不读取到内存）。

    当 use_propagated=True 时, 优先显示传播/编辑后的帧而非原始帧。
    """
    if not state.has_video():
        return None
    frames = list_frames(state.frames_dir)
    step = max(1, len(frames) // 32)
    gallery = []
    for i, fp in enumerate(frames, start=1):
        if (i - 1) % step != 0 and i != state.current_frame_index:
            continue
        caption = _frame_caption(state, i)
        # 优先使用传播/编辑后的帧作为缩略图
        display_path = str(fp)
        if use_propagated:
            if state.propagated_dir:
                prop_p = frame_path(i, state.propagated_dir)
                if Path(prop_p).exists():
                    display_path = str(prop_p)
            elif i in state.edited_frames and Path(state.edited_frames[i]).exists():
                display_path = state.edited_frames[i]
        gallery.append((display_path, caption))
    return gallery


def _frame_caption(state: FrameForgeSession, idx: int) -> str:
    tags = []
    if idx in state.edited_frames:
        tags.append("edited")
    if state.propagated_indices and idx in state.propagated_indices:
        tags.append("prop")
    if idx in state.low_quality_frames:
        tags.append("low!")
    tag = f" [{','.join(tags)}]" if tags else ""
    return f"#{idx}{tag}"


def _extract_mask_from_sketch(sketch_editor) -> np.ndarray | None:
    """从 gr.ImageEditor / Sketchpad 输出提取二值 mask.

    Gradio 4.x ImageEditor 返回 ``{"background", "layers", "composite"}``,
    layers 是绘制层 (RGBA)。把所有 layer 的 alpha 通道合并即得 mask。
    也兼容旧式 ndarray 输入。
    """
    if sketch_editor is None:
        return None
    # 字典形式 (新 Gradio)
    if isinstance(sketch_editor, dict):
        layers = sketch_editor.get("layers", [])
        if not layers:
            return None
        mask = None
        for layer in layers:
            arr = _to_ndarray(layer)
            if arr is None:
                continue
            if arr.ndim == 3 and arr.shape[2] == 4:
                alpha = arr[:, :, 3]
            elif arr.ndim == 3:
                alpha = arr.max(axis=2)
            else:
                alpha = arr
            if mask is None:
                mask = np.zeros_like(alpha, dtype=np.uint8)
            mask = np.maximum(mask, alpha)
        return mask
    # ndarray 形式
    arr = _to_ndarray(sketch_editor)
    if arr is None:
        return None
    if arr.ndim == 3 and arr.shape[2] == 4:
        return arr[:, :, 3]
    return arr


def _to_ndarray(x) -> np.ndarray | None:
    """把 PIL / ndarray / 路径 转为 ndarray."""
    if x is None:
        return None
    if isinstance(x, np.ndarray):
        return x
    try:
        from PIL import Image
        if isinstance(x, Image.Image):
            return np.array(x)
        if isinstance(x, str):
            return np.array(Image.open(x).convert("RGBA"))
    except Exception:
        return None
    return None
