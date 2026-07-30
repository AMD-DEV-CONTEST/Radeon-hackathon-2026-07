"""
Open-source local image partial re-drawing tool based on ComfyUI workflow + Gradio, optimized exclusively for AMD ROCm GPU

start：
    source /workspace/comfyuipy/bin/activate
    python ch_app.py
    
"""

import gc
import io
import json
import os
import sys
import uuid
import time
import random
import signal
import logging
import threading
import subprocess
import traceback
from typing import Optional, Dict, Any, List, Tuple

import numpy as np
import requests
from PIL import Image
import gradio as gr


COMFYUI_DIR = os.environ.get("COMFYUI_DIR", "/workspace/ComfyUI")
COMFYUI_PYTHON = os.environ.get(
    "COMFYUI_PYTHON", "/workspace/comfyuipy/bin/python"
)
COMFYUI_PORT = int(os.environ.get("COMFYUI_PORT", "8188"))
COMFYUI_URL = os.environ.get(
    "COMFYUI_URL", f"http://127.0.0.1:{COMFYUI_PORT}"
).rstrip("/")
COMFYUI_INPUT_DIR = os.environ.get(
    "COMFYUI_INPUT_DIR", os.path.join(COMFYUI_DIR, "input")
)
SKIP_COMFYUI = os.environ.get("SKIP_COMFYUI", "0") == "1"


_COMFYUI_EXTRA_ARGS_DEFAULT = ""
COMFYUI_EXTRA_ARGS = os.environ.get(
    "COMFYUI_EXTRA_ARGS", _COMFYUI_EXTRA_ARGS_DEFAULT
)

SKIP_WARMUP = os.environ.get("SKIP_WARMUP", "0") == "1"

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WORKFLOW_PATH = os.path.join(_BASE_DIR, "workflow.json")

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ComfyUI
# ---------------------------------------------------------------------------

_comfyui_process: Optional[subprocess.Popen] = None
_stdout_thread: Optional[threading.Thread] = None
_stderr_thread: Optional[threading.Thread] = None


def _read_stream(stream, prefix: str):
    try:
        for line in iter(stream.readline, ""):
            if line:
                logger.info(f"[ComfyUI {prefix}] {line.rstrip()}")
    except (ValueError, OSError):
        pass
    finally:
        try:
            stream.close()
        except Exception:
            pass


def start_comfyui() -> subprocess.Popen:
    global _comfyui_process, _stdout_thread, _stderr_thread

    main_py = os.path.join(COMFYUI_DIR, "main.py")
    if not os.path.isfile(main_py):
        raise FileNotFoundError(f"ComfyUI main.py not found: {main_py}")
    if not os.path.isfile(COMFYUI_PYTHON):
        raise FileNotFoundError(f"Python Interpreter not found: {COMFYUI_PYTHON}")

    cmd = [
        COMFYUI_PYTHON,
        main_py,
        "--port", str(COMFYUI_PORT),
        "--listen", "0.0.0.0",
    ]

    if COMFYUI_EXTRA_ARGS.strip():
        cmd.extend(COMFYUI_EXTRA_ARGS.strip().split())

    logger.info(f"🚀 start ComfyUI: {' '.join(cmd)}")

    comfyui_env = {
        **os.environ,
        "PYTHONUNBUFFERED": "1",
        "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True",
    }

    _comfyui_process = subprocess.Popen(
        cmd,
        cwd=COMFYUI_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        env=comfyui_env,
    )

    _stdout_thread = threading.Thread(
        target=_read_stream,
        args=(_comfyui_process.stdout, "STDOUT"),
        daemon=True,
    )
    _stderr_thread = threading.Thread(
        target=_read_stream,
        args=(_comfyui_process.stderr, "STDERR"),
        daemon=True,
    )
    _stdout_thread.start()
    _stderr_thread.start()

    return _comfyui_process


def stop_comfyui():
    global _comfyui_process
    proc = _comfyui_process
    if proc is None or proc.poll() is not None:
        _comfyui_process = None
        return

    logger.info("🛑 stopping ComfyUI...")

    def _try_signal(sig, wait_sec):
        try:
            proc.send_signal(sig)
        except Exception:
            return False
        try:
            proc.wait(timeout=wait_sec)
            return True
        except subprocess.TimeoutExpired:
            return False

    if not _try_signal(signal.SIGINT, 15):
        logger.warning("ComfyUI no response SIGINT，send SIGTERM...")
        if not _try_signal(signal.SIGTERM, 10):
            logger.warning("ComfyUI no response SIGTERM， kill...")
            try:
                proc.kill()
                proc.wait(timeout=5)
            except Exception:
                pass

    logger.info("✅ ComfyUI stopped")
    _comfyui_process = None


def wait_for_comfyui_ready(timeout: int = 300) -> bool:
    start = time.time()
    consecutive_ok = 0

    while time.time() - start < timeout:
        proc = _comfyui_process
        if proc is not None and proc.poll() is not None:
            logger.error(f"ComfyUI process abnormal termination，res: {proc.returncode}")
            return False

        try:
            resp = requests.get(f"{COMFYUI_URL}/system_stats", timeout=5)
            if resp.status_code == 200:
                consecutive_ok += 1
                if consecutive_ok >= 2:
                    elapsed = time.time() - start
                    logger.info(f"✅ ComfyUI Ready (time {elapsed:.0f}s)")
                    return True
            else:
                consecutive_ok = 0
        except (requests.ConnectionError, requests.Timeout):
            consecutive_ok = 0

        time.sleep(2)

    logger.error(f"ComfyUI timeout occurred during startup ({timeout}s)")
    return False


def get_vram_info() -> Optional[Dict]:
    try:
        resp = requests.get(f"{COMFYUI_URL}/system_stats", timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            devices = data.get("devices", [])
            if devices:
                info = {}
                for i, d in enumerate(devices):
                    vram_total = d.get("vram_total", 0) / (1024**3)
                    vram_free = d.get("vram_free", 0) / (1024**3)
                    vram_used = vram_total - vram_free
                    pct = (vram_used / vram_total * 100) if vram_total > 0 else 0
                    info[f"GPU{i}"] = f"{vram_used:.1f}/{vram_total:.1f}GB ({pct:.0f}%)"
                return info
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def load_workflow() -> Dict[str, Any]:
    if not os.path.isfile(WORKFLOW_PATH):
        raise FileNotFoundError(f"workflow.json not find: {WORKFLOW_PATH}")
    with open(WORKFLOW_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def upload_image_to_comfyui(local_path: str, subfolder: str = "") -> Dict:
    url = f"{COMFYUI_URL}/upload/image"
    with open(local_path, "rb") as f:
        files = {"image": (os.path.basename(local_path), f, "image/png")}
        data = {"subfolder": subfolder, "overwrite": "true"}
        resp = requests.post(url, files=files, data=data, timeout=30)
    resp.raise_for_status()
    return resp.json()


def queue_prompt(workflow: Dict) -> str:
    url = f"{COMFYUI_URL}/prompt"
    payload = {"prompt": workflow}
    resp = requests.post(url, json=payload, timeout=30)
    resp.raise_for_status()
    result = resp.json()
    if "prompt_id" not in result:
        raise RuntimeError(f"workflow.json error: {result}")
    return result["prompt_id"]


def get_history(prompt_id: str) -> Dict:
    url = f"{COMFYUI_URL}/history/{prompt_id}"
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    return resp.json()


def wait_for_completion(
    prompt_id: str, timeout: int = 600, poll_interval: float = 1.5
) -> Dict:
    start = time.time()
    while time.time() - start < timeout:
        history = get_history(prompt_id)
        if prompt_id in history:
            entry = history[prompt_id]
            status = entry.get("status", {})
            if status.get("completed") is False:
                status_str = status.get("status_str", "未知错误")
                raise RuntimeError(f"workflow.json error: {status_str}")
            return entry
        time.sleep(poll_interval)
    raise TimeoutError(f"workflow.json timeout ({timeout}s)")


def download_output_images(history_entry: Dict) -> List:
    images: List = []
    for _node_id, node_output in history_entry.get("outputs", {}).items():
        if "images" not in node_output:
            continue
        for img_info in node_output["images"]:
            filename = img_info["filename"]
            subfolder = img_info.get("subfolder", "")
            img_type = img_info.get("type", "output")
            url = (
                f"{COMFYUI_URL}/view"
                f"?filename={filename}"
                f"&subfolder={subfolder}"
                f"&type={img_type}"
            )
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            img = Image.open(io.BytesIO(resp.content))
            img.load()
            images.append(img)
    return images


# ---------------------------------------------------------------------------
# ★ Start the preheating process
# ---------------------------------------------------------------------------

def _create_dummy_warmup_images() -> Tuple[str, str]:
    w, h = 64, 64
    session_id = "warmup_" + uuid.uuid4().hex[:6]

    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    rgba[:, :, :3] = 128
    rgba[16:48, 16:48, 3] = 255
    rgba[16:48, 16:48, :3] = 128

    main_filename = f"warmup_main_{session_id}.png"
    main_path = os.path.join(COMFYUI_INPUT_DIR, main_filename)
    Image.fromarray(rgba).save(main_path, "PNG")

    ref = np.full((h, w, 3), 128, dtype=np.uint8)
    ref_filename = f"warmup_ref_{session_id}.png"
    ref_path = os.path.join(COMFYUI_INPUT_DIR, ref_filename)
    Image.fromarray(ref).save(ref_path, "PNG")

    return main_filename, ref_filename


def warm_up_models(timeout: int = 180) -> bool:
    logger.info("=" * 60)
    logger.info("🔥 Start the preheating process...")
    logger.info("=" * 60)

    vram_before = get_vram_info()
    if vram_before:
        logger.info(f"   Preheating memory before operation: {vram_before}")

    os.makedirs(COMFYUI_INPUT_DIR, exist_ok=True)

    main_filename, ref_filename = _create_dummy_warmup_images()
    main_path = os.path.join(COMFYUI_INPUT_DIR, main_filename)
    ref_path = os.path.join(COMFYUI_INPUT_DIR, ref_filename)

    workflow = load_workflow()

    if "322" in workflow:
        workflow["322"]["inputs"]["image"] = main_filename
    if "325" in workflow:
        workflow["325"]["inputs"]["image"] = ref_filename
    if "223" in workflow:
        workflow["223"]["inputs"]["value"] = "keep"
    if "172" in workflow:
        workflow["172"]["inputs"]["seed"] = 42
        workflow["172"]["inputs"]["steps"] = 1
        workflow["172"]["inputs"]["cfg"] = 1.0
        workflow["172"]["inputs"]["denoise"] = 1.0

    t0 = time.time()

    try:
        prompt_id = queue_prompt(workflow)
        logger.info(f"   During the preheating reasoning process (prompt_id={prompt_id[:8]}...)...")

        wait_for_completion(prompt_id, timeout=timeout)

        elapsed = time.time() - t0
        logger.info(f"✅ Preheating completed! Time taken {elapsed:.1f}s")

        vram_after = get_vram_info()
        if vram_after:
            logger.info(f"   After preheating, the video memory: {vram_after}")
            logger.info("   🎯 All models have been loaded into the graphics memory, and subsequent inferences do not require reloading.")

    except RuntimeError as e:
        error_msg = str(e)
        if "out of memory" in error_msg.lower() or "oom" in error_msg.lower():
            logger.warning("⚠️  OOM！")
        else:
            logger.warning(f"⚠️  Preheating failed: {e}")
        return False
    except Exception as e:
        logger.warning(f"⚠️  Preheating failed（Does not affect normal use）: {e}")
        return False
    finally:
        for p in (main_path, ref_path):
            try:
                os.remove(p)
            except Exception:
                pass
        gc.collect()

    return True


# ---------------------------------------------------------------------------
# images
# ---------------------------------------------------------------------------

def create_rgba_with_mask(
    image_rgb: np.ndarray, mask_gray: np.ndarray
) -> np.ndarray:
    """ RGB → RGBA """
    h, w = image_rgb.shape[:2]

    if mask_gray.ndim == 3:
        if mask_gray.shape[2] == 4:
            mask_gray = mask_gray[:, :, 3]
        elif mask_gray.shape[2] == 3:
            mask_gray = np.mean(mask_gray, axis=2)
        elif mask_gray.shape[2] == 1:
            mask_gray = mask_gray[:, :, 0]

    if mask_gray.dtype in (np.float32, np.float64):
        mask_gray = (mask_gray * 255).astype(np.uint8) if mask_gray.max() <= 1.0 else mask_gray.astype(np.uint8)

    if mask_gray.shape[:2] != (h, w):
        mask_pil = Image.fromarray(mask_gray).resize((w, h), Image.LANCZOS)
        mask_gray = np.array(mask_pil)

    if image_rgb.ndim == 3 and image_rgb.shape[2] == 4:
        image_rgb = image_rgb[:, :, :3]

    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    rgba[:, :, :3] = image_rgb[:, :, :3] if image_rgb.ndim == 3 else image_rgb
    rgba[:, :, 3] = 255 - mask_gray

    return rgba


def extract_mask_from_image_editor(
    editor_output: Dict,
) -> Tuple[np.ndarray, np.ndarray]:
    if editor_output is None:
        raise gr.Error("请上传图像并绘制遮罩")
    if not isinstance(editor_output, dict):
        raise gr.Error(f"不支持的输入类型: {type(editor_output)}")

    background = editor_output.get("background")
    layers = editor_output.get("layers", [])
    composite = editor_output.get("composite")

    if background is None and composite is None:
        raise gr.Error("无法获取输入图像")

    mask = None
    if layers:
        for layer in layers:
            if isinstance(layer, np.ndarray):
                if layer.ndim == 3 and layer.shape[2] >= 4:
                    alpha = layer[:, :, 3]
                    if np.max(alpha) > 0:
                        mask = alpha
                        break
                elif layer.ndim == 2:
                    if np.max(layer) > 0:
                        mask = layer
                        break
            elif isinstance(layer, dict):
                layer_img = layer.get("image")
                if (
                    isinstance(layer_img, np.ndarray)
                    and layer_img.ndim == 3
                    and layer_img.shape[2] >= 4
                ):
                    alpha = layer_img[:, :, 3]
                    if np.max(alpha) > 0:
                        mask = alpha
                        break

    if mask is None and composite is not None and background is not None:
        bg = background[:, :, :3] if background.shape[2] >= 3 else background
        cp = composite[:, :, :3] if composite.shape[2] >= 3 else composite
        diff = np.abs(cp.astype(np.float32) - bg.astype(np.float32))
        mask = np.clip(np.max(diff, axis=2), 0, 255).astype(np.uint8)

    if mask is None:
        raise gr.Error("未能提取遮罩，请使用白色画笔在图像上绘制需要修改的区域")

    main_image = background if background is not None else composite
    return main_image, mask


def prepare_reference_image(ref_input) -> Tuple[np.ndarray, bool]:
    """
    参考图统一为 RGB numpy 数组。

    返回:
        (image_array, has_ref) — has_ref=False 表示用户未上传参考图

    支持：
    - None: 返回 64×64 白色占位图，标记 has_ref=False
    - str: 文件路径（gr.File type="filepath"）
    - np.ndarray: 已读取的图像
    """
    if ref_input is None:
        logger.info("   参考图未上传，将关闭参考图特征注入")
        return np.full((64, 64, 3), 255, dtype=np.uint8), False

    if isinstance(ref_input, str):
        img = Image.open(ref_input)
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGB")
        return np.array(img), True

    if isinstance(ref_input, np.ndarray):
        if ref_input.ndim == 3 and ref_input.shape[2] == 4:
            ref_input = ref_input[:, :, :3]
        return ref_input, True

    try:
        img = Image.open(ref_input)
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGB")
        return np.array(img), True
    except Exception:
        raise gr.Error(f"不支持的参考图类型: {type(ref_input)}")


# ---------------------------------------------------------------------------
# 核心处理
# ---------------------------------------------------------------------------

def process(
    input_image_editor: Dict,
    reference_image,
    prompt: str,
    seed_val: float,
    steps: int,
    cfg: float,
    denoise: float,
    mask_grow: int,
    mask_blur: int,
    progress=gr.Progress(),
) -> Optional[np.ndarray]:
    """
    主处理流程 —— 模型已在显存中，推理即时开始。

    返回:
        result_image — 生成图片
    """
    result = None

    try:
        try:
            requests.get(f"{COMFYUI_URL}/system_stats", timeout=3)
        except Exception:
            raise gr.Error(f"ComfyUI 服务不可用 ({COMFYUI_URL})，请确认服务已启动")

        vram_before = get_vram_info()
        if vram_before:
            logger.info(f"推理前显存: {vram_before}")

        seed = int(seed_val)
        if seed == -1:
            seed = random.randint(0, 2**63 - 1)

        progress(0.05, desc="加载工作流模板...")
        workflow = load_workflow()

        progress(0.10, desc="处理输入图像和遮罩...")
        main_image, mask = extract_mask_from_image_editor(input_image_editor)
        ref_image, has_ref = prepare_reference_image(reference_image)

        progress(0.15, desc="保存图像...")
        session_id = uuid.uuid4().hex[:10]
        input_filename = f"gradio_main_{session_id}.png"
        ref_filename = f"gradio_ref_{session_id}.png"

        os.makedirs(COMFYUI_INPUT_DIR, exist_ok=True)

        rgba = create_rgba_with_mask(main_image, mask)
        input_path = os.path.join(COMFYUI_INPUT_DIR, input_filename)
        Image.fromarray(rgba).save(input_path, "PNG")

        ref_path = os.path.join(COMFYUI_INPUT_DIR, ref_filename)
        Image.fromarray(ref_image).save(ref_path, "PNG")

        del main_image, mask, ref_image, rgba

        try:
            upload_image_to_comfyui(input_path)
            upload_image_to_comfyui(ref_path)
        except Exception:
            logger.debug("API 上传失败（文件已直接写入 input 目录，可忽略）")

        progress(0.20, desc="配置参数...")

        if "322" in workflow:
            workflow["322"]["inputs"]["image"] = input_filename
        if "325" in workflow:
            workflow["325"]["inputs"]["image"] = ref_filename
        if "223" in workflow:
            workflow["223"]["inputs"]["value"] = prompt

        # ★ 无参考图时关闭参考图特征注入，避免白色占位图造成残影
        if "196" in workflow:
            workflow["196"]["inputs"]["to_ref"] = has_ref
            if not has_ref:
                logger.info("   已关闭参考图特征注入 (to_ref=False)")

        if "172" in workflow:
            workflow["172"]["inputs"]["seed"] = seed
            workflow["172"]["inputs"]["steps"] = int(steps)
            workflow["172"]["inputs"]["cfg"] = float(cfg)
            workflow["172"]["inputs"]["denoise"] = float(denoise)
        if "326" in workflow:
            workflow["326"]["inputs"]["grow"] = int(mask_grow)
            workflow["326"]["inputs"]["blur"] = int(mask_blur)

        logger.info(
            f"参数: seed={seed} steps={steps} cfg={cfg} "
            f"denoise={denoise} grow={mask_grow} blur={mask_blur} "
            f"has_ref={has_ref}"
        )

        progress(0.25, desc="提交工作流...")
        prompt_id = queue_prompt(workflow)

        progress(0.30, desc=f"推理中 ({prompt_id[:8]}...)...")
        history_entry = wait_for_completion(prompt_id, timeout=600)

        progress(0.85, desc="下载结果...")
        output_images = download_output_images(history_entry)

        if not output_images:
            raise gr.Error("未生成输出图像，请检查 ComfyUI 控制台输出")

        result = np.array(output_images[0])

        output_images.clear()
        del output_images, history_entry, workflow

        progress(0.95, desc="完成!")
        return result

    except gr.Error:
        raise
    except Exception:
        logger.error(traceback.format_exc())
        last_line = traceback.format_exc(chain=False).strip().splitlines()[-1]
        raise gr.Error(f"处理失败: {last_line}")
    finally:
        gc.collect()

        vram_after = get_vram_info()
        if vram_after:
            logger.info(f"推理后显存: {vram_after}")

# ---------------------------------------------------------------------------
# Gradio UI
# ---------------------------------------------------------------------------

CSS = """
.gradio-container { max-width: 1200px !important; }

#generate_btn {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important;
    border: none !important;
    color: white !important;
    font-weight: bold !important;
    font-size: 1.1em !important;
}

#ref_file_upload .wrap {
    cursor: pointer !important;
}

/* ★ 提示词模板按钮 */
.template-btn-row {
    gap: 8px;
}
.template-btn-replace {
    background: linear-gradient(135deg, #43e97b 0%, #38f9d7 100%) !important;
    color: #1a1a2e !important;
    border: none !important;
    font-weight: 600 !important;
}
.template-btn-cloth {
    background: linear-gradient(135deg, #fa709a 0%, #fee140 100%) !important;
    color: #1a1a2e !important;
    border: none !important;
    font-weight: 600 !important;
}
.template-btn-erase {
    background: linear-gradient(135deg, #f5576c 0%, #ff6b35 100%) !important;
    color: white !important;
    border: none !important;
    font-weight: 600 !important;
}
.template-btn-hair {
    background: linear-gradient(135deg, #f7971e 0%, #ffd200 100%) !important;
    color: #1a1a2e !important;
    border: none !important;
    font-weight: 600 !important;
}

@media (max-width: 768px) {
    .gradio-container { padding: 8px !important; }
    #generate_btn { width: 100% !important; }
}
"""

DEFAULT_PROMPT = ""

PROMPT_TEMPLATES = {
    "风格化局部重绘": "替换为油画风格",
    "衣物替换": "将图中人物的衣服替换为参考图衣服",
    "文本引导局部生成": "生成",
    "物品消除": "去掉物品",
}


def build_ui():
    with gr.Blocks(title="局部重绘 - AMD Optimized Partial Inpainting WebUI") as app:

        gr.Markdown(
            """
            # 🎨 局部重绘 (Inpainting)

            基于 **Qwen-Image-Edit-2511** + **LoRA Lightning 4步** |
            遮罩区域替换，遮罩外完全保持原图 |
            🚀 模型预热完成，生成速度up↑
            """
        )

        # ★ 提示词模板按钮（两行）
        gr.Markdown("### 📋 常用提示词模板（点击自动填入，可补充）")
        with gr.Row(elem_classes="template-btn-row"):
            btn_replace = gr.Button("🔄 风格化局部重绘", elem_classes="template-btn-replace", scale=1)
            btn_cloth = gr.Button("👗 衣物替换", elem_classes="template-btn-cloth", scale=1)
            btn_hair = gr.Button("💇 文本引导局部生成", elem_classes="template-btn-hair", scale=1)
            btn_erase = gr.Button("🧹 物品消除", elem_classes="template-btn-erase", scale=1)

        with gr.Row(equal_height=True):
            with gr.Column(scale=1):
                input_editor = gr.ImageEditor(
                    label="📷 步骤 1：上传主图并用白色画笔绘制遮罩",
                    type="numpy",
                    sources=["upload"],
                    brush=gr.Brush(
                        default_size=30,
                        colors=["rgba(255,255,255,1.0)"],
                        color_mode="fixed",
                    ),
                    layers=True,
                    canvas_size=(768, 768),
                )

                ref_file = gr.File(
                    label="🔍 步骤 2：上传参考物体图（可选）",
                    file_types=["image"],
                    type="filepath",
                    elem_id="ref_file_upload",
                )

            with gr.Column(scale=1):
                output_image = gr.Image(
                    label="✨ 生成结果",
                    type="numpy",
                    height=512,
                )

        with gr.Accordion("📝 提示词", open=True):
            prompt_box = gr.Textbox(
                label="编辑提示词（可使用上方模板快速填入）",
                value=DEFAULT_PROMPT,
                lines=4,
                max_lines=10,
            )

        with gr.Accordion("⚙️ 高级参数", open=False):
            with gr.Row():
                seed_input = gr.Number(
                    label="🌱 随机种子 (-1=随机)",
                    value=-1, precision=0, minimum=-1,
                )
                steps_input = gr.Slider(
                    label="🔄 采样步数",
                    minimum=1, maximum=20, value=4, step=1,
                )
            with gr.Row():
                cfg_input = gr.Slider(
                    label="📐 CFG Scale",
                    minimum=0.5, maximum=5.0, value=1.0, step=0.1,
                )
                denoise_input = gr.Slider(
                    label="🎯 降噪强度",
                    minimum=0.0, maximum=1.0, value=1.0, step=0.01,
                )
            with gr.Row():
                grow_input = gr.Slider(
                    label="📏 遮罩扩展 (px)",
                    minimum=0, maximum=200, value=35, step=1,
                )
                blur_input = gr.Slider(
                    label="🖌 遮罩模糊 (px)",
                    minimum=0, maximum=100, value=10, step=1,
                )

        with gr.Row():
            generate_btn = gr.Button(
                "🚀 开始生成",
                variant="primary",
                size="lg",
                elem_id="generate_btn",
            )

        gr.Markdown(
            """
            ---
            ### 💡 使用说明
            | 模式 | 主图 | 参考图 | 说明 |
            |------|------|--------|------|
            | 🔄 **风格化局部重绘** | ✅ 上传 + 遮罩 | ✅ 可选 | 将遮罩区域替换为某种艺术风格（如油画、水彩、赛博朋克） |
            | 👗 **衣物替换** | ✅ 上传 + 遮罩衣物 | ✅ 需上传衣服图 | 将衣服替换为参考图款式 |
            | 💇 **文本引导局部生成** | ✅ 上传 + 遮罩  | ⭕ 无需上传 | 在遮罩区域根据文字描述凭空生成内容（text-to-mask-inpainting） |
            | 🧹 **物品消除** | ✅ 上传 + 遮罩物品 | ⭕ 无需上传 | 直接消除遮罩区域物体 |
            """
        )

        # ================================================================
        # 事件绑定
        # ================================================================

        def set_prompt(template_name: str):
            return PROMPT_TEMPLATES.get(template_name, DEFAULT_PROMPT)

        btn_replace.click(fn=lambda: set_prompt("风格化局部重绘"), inputs=[], outputs=[prompt_box])
        btn_cloth.click(fn=lambda: set_prompt("衣物替换"), inputs=[], outputs=[prompt_box])
        btn_hair.click(fn=lambda: set_prompt("文本引导局部生成"), inputs=[], outputs=[prompt_box])
        btn_erase.click(fn=lambda: set_prompt("物品消除"), inputs=[], outputs=[prompt_box])
        
        generate_btn.click(
            fn=process,
            inputs=[
                input_editor, ref_file, prompt_box,
                seed_input, steps_input, cfg_input, denoise_input,
                grow_input, blur_input,
            ],
            outputs=[output_image],
        )

    return app


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def _cleanup():
    stop_comfyui()


def main():
    signal.signal(signal.SIGINT, lambda *_: (_cleanup(), sys.exit(0)))
    signal.signal(signal.SIGTERM, lambda *_: (_cleanup(), sys.exit(0)))

    os.makedirs(COMFYUI_INPUT_DIR, exist_ok=True)

    logger.info("=" * 60)
    logger.info(f"ComfyUI 目录:      {COMFYUI_DIR}")
    logger.info(f"Python 解释器:     {COMFYUI_PYTHON}")
    logger.info(f"ComfyUI 端口:      {COMFYUI_PORT}")
    logger.info(f"ComfyUI URL:       {COMFYUI_URL}")
    logger.info(f"工作流文件:        {WORKFLOW_PATH}")
    logger.info(f"跳过启动:          {SKIP_COMFYUI}")
    logger.info(f"额外启动参数:      {COMFYUI_EXTRA_ARGS or '(无) — 模型常驻显存'}")
    logger.info(f"跳过预热:          {SKIP_WARMUP}")
    logger.info(f"显存:              AMD 51.5 GB (ROCm)")
    logger.info(f"策略:              全模型常驻显存 (~30 GB)")
    logger.info("=" * 60)

    if not SKIP_COMFYUI:
        logger.info("正在启动 ComfyUI 子进程（模型常驻模式，无 --lowvram）...")

        try:
            start_comfyui()
        except FileNotFoundError as e:
            logger.error(f"启动失败: {e}")
            sys.exit(1)

        logger.info("等待 ComfyUI 就绪...")
        if not wait_for_comfyui_ready(timeout=300):
            logger.error("ComfyUI 启动失败或超时")
            stop_comfyui()
            sys.exit(1)

        if not SKIP_WARMUP:
            warm_up_models(timeout=180)
        else:
            logger.info("⏭️  已跳过预热（SKIP_WARMUP=1），首次推理时加载模型")

    logger.info("正在启动 Gradio WebUI...")
    app = build_ui()
    try:
        app.queue(max_size=5, api_open=False)
        app.launch(
            server_name="0.0.0.0",
            server_port=7860,
            share=False,
            show_error=True,
            theme=gr.themes.Soft(),
            css=CSS,
        )
    finally:
        _cleanup()


if __name__ == "__main__":
    main()
