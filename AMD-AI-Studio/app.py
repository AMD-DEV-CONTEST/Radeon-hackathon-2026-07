"""
AMD AI Studio v2 — 本地 AI 创作工作室
功能：文生图、图生图、图生视频、图像编辑、模型管理、系统监控
特性：自动后台下载、智能显存管理、模型兼容性过滤
"""

import os, sys, time, json, logging, threading
from pathlib import Path
from datetime import datetime
from typing import Optional

import gradio as gr
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))

from modules.rocm_utils import is_rocm_available, get_gpu_info
from modules.model_loader import global_loader, DEFAULT_MODEL_REGISTRY
from modules.model_loader import STATUS_NOT_DOWNLOADED, STATUS_DOWNLOADING, STATUS_DOWNLOADED, STATUS_ERROR, STATUS_LOADING, STATUS_LOADED
from modules.system_monitor import global_monitor
from modules.smart_manager import SmartModelManager, get_total_vram_gb, get_available_vram_gb, get_compatible_models

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("amd-ai-studio")

OUTPUT_DIR = Path("outputs")
for sub in ["images", "videos", "gifs"]:
    (OUTPUT_DIR / sub).mkdir(parents=True, exist_ok=True)

# ============================================================
# 智能模型管理器
# ============================================================
smart_mgr = SmartModelManager(global_loader)
smart_mgr.start_monitoring()

def _auto_download_core():
    core_models = ["sdxl-base", "sdxl-vae-fp16"]
    for key in core_models:
        if not global_loader.is_model_downloaded(key) and not global_loader.is_downloading(key):
            global_loader.start_download(key)
            logger.info(f"自动后台下载核心模型: {key}")
            _wait_for_download(key, timeout=600)

def _wait_for_download(key: str, timeout: int = 600):
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = global_loader.get_model_status(key)
        if status.status in (STATUS_DOWNLOADED, STATUS_ERROR):
            return
        time.sleep(2)

threading.Thread(target=_auto_download_core, daemon=True).start()

# ============================================================
# CSS
# ============================================================
CUSTOM_CSS = """
/* ===== 全局重置 ===== */
.gradio-container {
  max-width: 100% !important;
  margin: 0 !important;
  padding: 0.5rem 0.75rem !important;
  font-family: 'Inter', 'Segoe UI', system-ui, sans-serif !important;
}
body { overflow: hidden; }

/* ===== 头部 ===== */
.app-header {
  text-align: center;
  padding: 0.6rem 0;
  background: linear-gradient(135deg, #1a1a2e, #16213e, #0f3460, #1a1a2e);
  border-radius: 12px;
  margin-bottom: 0.5rem;
  color: white;
  box-shadow: 0 2px 16px rgba(0,0,0,0.08);
}
.app-header h1 {
  font-size: 1.3rem;
  margin: 0;
  font-weight: 700;
  background: linear-gradient(135deg, #e94560, #ff6b35, #f5c518, #00BCD4);
  background-size: 300% 300%;
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  animation: gradientShift 4s ease-in-out infinite;
}
@keyframes gradientShift { 0%,100%{background-position:0% 50%} 50%{background-position:100% 50%} }
.app-header p { margin: 0; opacity: 0.7; font-size: 0.75rem; }

/* ===== 三栏滚动容器 ===== */
.scroll-col {
  height: calc(100vh - 120px);
  overflow-y: auto;
  overflow-x: hidden;
  padding-right: 4px;
}
.scroll-col::-webkit-scrollbar { width: 3px; }
.scroll-col::-webkit-scrollbar-thumb { background: #d1d5db; border-radius: 2px; }

/* ===== 卡片 ===== */
.card {
  background: white;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  padding: 0.5rem 0.7rem;
  box-shadow: 0 1px 6px rgba(0,0,0,0.04);
  margin-bottom: 0.4rem;
}
.card-title {
  font-size: 0.7rem;
  color: #6b7280;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  font-weight: 500;
  margin-bottom: 0.25rem;
}

/* ===== 监控网格 ===== */
.monitor-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.3rem;
}
.monitor-item {
  padding: 0.3rem 0.5rem;
  border-radius: 6px;
  background: #f9fafb;
  border: 1px solid #f3f4f6;
  contain: content;
}
.monitor-label { font-size: 0.6rem; color: #6b7280; text-transform: uppercase; }
.monitor-value { font-size: 0.85rem; font-weight: 600; color: #111827; }
.monitor-bar { height: 2px; background: #e5e7eb; border-radius: 1px; margin-top: 3px; overflow: hidden; }
.monitor-bar-fill { height: 100%; border-radius: 1px; transition: width 1.2s ease-out; }

/* ===== 模型列表 ===== */
.model-item {
  display: flex; align-items: center; gap: 4px; padding: 2px 0; font-size: 0.75rem;
}
.model-item .model-name { flex: 1; color: #374151; font-weight: 500; }
.model-item .model-status { font-size: 0.65rem; color: #6b7280; white-space: nowrap; }
.model-item .model-vram { font-size: 0.6rem; color: #3b82f6; white-space: nowrap; }
.progress-bar { height: 3px; background: #e5e7eb; border-radius: 1px; overflow: hidden; margin-top: 1px; }
.progress-bar-fill { height: 100%; background: linear-gradient(90deg, #2196F3, #00BCD4); border-radius: 1px; transition: width 1.2s ease-out; }

/* ===== 按钮 ===== */
.gr-button-primary {
  background: linear-gradient(135deg, #e94560, #ff6b35) !important;
  border: none !important; border-radius: 8px !important;
  font-weight: 600 !important; font-size: 0.85rem !important;
  padding: 0.4rem 1rem !important; color: white !important;
  box-shadow: 0 2px 12px rgba(233,69,96,0.25) !important;
}
.gr-button-secondary {
  background: #f3f4f6 !important; border: 1px solid #d1d5db !important;
  border-radius: 8px !important; color: #374151 !important;
  font-size: 0.8rem !important;
}
.download-btn {
  background: linear-gradient(135deg, #2196F3, #00BCD4) !important;
  color: white !important; border: none !important; border-radius: 8px !important;
  font-size: 0.8rem !important;
}

/* ===== 徽章 ===== */
.badge {
  display: inline-block; padding: 1px 8px; border-radius: 999px;
  font-size: 0.65rem; font-weight: 600;
}
.badge-downloaded { background: #d1fae5; color: #065f46; }
.badge-downloading { background: #fef3c7; color: #92400e; }
.badge-not-downloaded { background: #f3f4f6; color: #6b7280; }
.badge-error { background: #fee2e2; color: #991b1b; }
.badge-loading { background: #dbeafe; color: #1e40af; }
.badge-loaded { background: #d1fae5; color: #065f46; }

/* ===== 功能选择 Radio ===== */
.func-radio label { font-size: 0.85rem !important; padding: 2px 6px !important; }

/* ===== 页脚 ===== */
.app-footer { text-align: center; padding: 0.5rem; color: #9ca3af; font-size: 0.7rem; border-top: 1px solid #e5e7eb; margin-top: 0.5rem; }

/* ===== 滚动条全局 ===== */
::-webkit-scrollbar { width: 3px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: #d1d5db; border-radius: 2px; }

/* ===== 减少 Gradio 组件间距 ===== */
.gr-box, .gr-form { gap: 0.3rem !important; }
label { margin-bottom: 0 !important; font-size: 0.8rem !important; }
"""


def _save_image(img, prefix="gen"):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    path = OUTPUT_DIR / "images" / f"{prefix}_{ts}.png"
    img.save(path)
    return str(path)


# ============================================================
# 左侧面板 — 系统信息 + 模型信息
# ============================================================
def build_left_panel():
    gr.Markdown("### 🖥️ 系统", elem_classes="card-title")

    sys_html = gr.HTML("加载中...", elem_classes="card")
    model_html = gr.HTML("", elem_classes="card")

    def refresh():
        info = global_monitor.get_system_info()
        status = global_loader.get_all_status()
        total = len(status)
        downloaded = sum(1 for s in status.values() if s.status == STATUS_DOWNLOADED)
        downloading = sum(1 for s in status.values() if s.status == STATUS_DOWNLOADING)
        vram_total = get_total_vram_gb()
        vram_avail = get_available_vram_gb()
        vram_pct = round((vram_total - vram_avail) / vram_total * 100, 1) if vram_total > 0 else 0
        gpu_name = info.gpu_info[0]['name'] if info.gpu_info else 'N/A'

        # 系统信息（紧凑网格）
        sys = f"""<div class="monitor-grid">
<div class="monitor-item"><div class="monitor-label">CPU</div><div class="monitor-value">{info.cpu_cores}核 {info.cpu_usage_percent:.1f}%</div></div>
<div class="monitor-item"><div class="monitor-label">内存</div><div class="monitor-value">{info.memory_used_gb:.0f}/{info.memory_total_gb:.0f}GB</div><div class="monitor-bar"><div class="monitor-bar-fill" style="width:{info.memory_percent}%;background:{"#e94560" if info.memory_percent>80 else "#10b981"}"></div></div></div>
<div class="monitor-item"><div class="monitor-label">GPU</div><div class="monitor-value" title="{gpu_name}">{gpu_name.split()[-1] if len(gpu_name.split())>1 else gpu_name}</div></div>
<div class="monitor-item"><div class="monitor-label">显存</div><div class="monitor-value">{vram_avail:.1f}/{vram_total:.0f}GB</div><div class="monitor-bar"><div class="monitor-bar-fill" style="width:{vram_pct}%;background:{"#e94560" if vram_pct>80 else "#10b981"}"></div></div></div>
<div class="monitor-item"><div class="monitor-label">磁盘</div><div class="monitor-value">{info.disk_free_gb:.0f}GB 可用</div><div class="monitor-bar"><div class="monitor-bar-fill" style="width:{info.disk_percent}%;background:{"#e94560" if info.disk_percent>80 else "#10b981"}"></div></div></div>
<div class="monitor-item"><div class="monitor-label">运行</div><div class="monitor-value">{info.uptime_hours:.1f}h</div></div>
</div>"""

        # 模型列表（含加载状态和显存）
        loaded = global_loader._loaded_pipelines
        loaded_vram = 0
        try:
            import torch
            if torch.cuda.is_available():
                loaded_vram = torch.cuda.memory_allocated(0) / 1024**3
        except: pass

        mdl = f'<div style="display:flex;justify-content:space-between;font-size:0.7rem;color:#6b7280;margin-bottom:4px"><span>📦 模型 {downloaded}/{total}</span>'
        if downloading: mdl += f'<span style="color:#92400e">⏳ {downloading} 下载中</span>'
        if len(loaded): mdl += f'<span style="color:#3b82f6">⚡ {len(loaded)} 已加载</span>'
        mdl += '</div>'

        for key, ms in status.items():
            icon = {"downloaded":"✅","downloading":"⏳","not_downloaded":"⬜","error":"❌","loading":"🔄","loaded":"⚡"}.get(ms.status, "⬜")
            pct = ms.progress
            bar = f'<div class="progress-bar"><div class="progress-bar-fill" style="width:{pct}%"></div></div>' if ms.status == STATUS_DOWNLOADING else ''
            msg = f'{pct:.0f}%' if ms.status == STATUS_DOWNLOADING else (ms.message[:12] if ms.message else '')
            # 显示已加载模型的显存
            vram_info = ''
            if ms.status == STATUS_LOADED:
                vram_info = f'<span class="model-vram">~{loaded_vram/max(len(loaded),1):.1f}GB</span>'
            mdl += f'<div class="model-item"><span>{icon}</span><span class="model-name">{key}</span><span class="model-status">{msg}</span>{vram_info}{bar}</div>'

        return sys, mdl

    # 初始加载
    init_sys, init_mdl = refresh()
    sys_html.value = init_sys
    model_html.value = init_mdl

    # 3 秒定时刷新（CSS transition 保证平滑，不会闪烁）
    timer = gr.Timer(value=3)
    timer.tick(fn=refresh, outputs=[sys_html, model_html])


# ============================================================
# 右侧面板 — 功能 + 参数
# ============================================================
def build_right_panel():
    gr.Markdown("### 🎯 功能", elem_classes="card-title")

    # 功能选择
    function_type = gr.Radio(
        choices=[
            ("📝 文生图", "txt2img"),
            ("🔄 图生图", "img2img"),
            ("🎬 图生视频", "img2video"),
            ("🖌️ 局部重绘", "inpainting"),
            ("🖼️ 图像外延", "outpainting"),
        ],
        value="txt2img", label="", elem_classes="card func-radio",
    )

    # 模型选择
    model_selector = gr.Dropdown(
        choices=[("SDXL 文生图", "sdxl-base")], value="sdxl-base",
        label="🎯 模型", interactive=True,
    )
    model_status = gr.HTML("")

    # 操作按钮行
    with gr.Row():
        download_btn = gr.Button("📥", variant="secondary", size="sm", elem_classes="download-btn", scale=1)
        unload_btn = gr.Button("🗑️", variant="secondary", size="sm", scale=1)
        generate_btn = gr.Button("🚀 生成", variant="primary", size="lg", elem_classes="gr-button-primary", scale=3)

    # ===== 提示词 =====
    prompt = gr.Textbox(label="💡 提示词", placeholder="描述你想要的图像...", lines=2)
    neg_prompt = gr.Textbox(label="🚫 负面", placeholder="不想出现的内容...", lines=1)

    # ===== 图片上传（按功能显示） =====
    init_image = gr.Image(label="📷 参考图", type="pil", height=160)
    mask_image = gr.Image(label="🎭 蒙版（白色涂抹区域）", type="pil", height=160)

    # ===== 参数折叠面板 =====
    with gr.Accordion("⚙️ 参数", open=True):
        # 第一行：通用参数
        with gr.Row():
            steps = gr.Slider(1, 80, value=30, step=1, label="步数")
            guidance = gr.Slider(1.0, 20.0, value=7.5, step=0.5, label="引导")
            seed = gr.Number(value=42, label="种子", precision=0)

        # 第二行：尺寸/数量（文生图）
        with gr.Row(visible=True) as txt2img_row:
            width = gr.Slider(512, 1536, value=1024, step=64, label="宽度")
            height = gr.Slider(512, 1536, value=1024, step=64, label="高度")
            num_images = gr.Slider(1, 4, value=1, step=1, label="数量")

        # 强度（图生图/重绘）
        strength = gr.Slider(0.1, 1.0, value=0.7, step=0.05, label="强度", visible=False)

        # 视频参数（图生视频）
        with gr.Row(visible=False) as video_row:
            num_frames = gr.Slider(6, 25, value=14, step=1, label="帧数")
            fps = gr.Slider(3, 30, value=7, step=1, label="帧率")

        # 外延参数
        with gr.Row(visible=False) as outpaint_row:
            outpainting_direction = gr.Radio(
                choices=["all", "left", "right", "top", "bottom", "diagonal"],
                value="all", label="方向",
            )
            expand_size = gr.Slider(64, 512, value=256, step=64, label="像素")

    return (
        function_type, model_selector, model_status,
        prompt, neg_prompt, init_image, mask_image,
        steps, guidance, seed, width, height, num_images,
        strength, num_frames, fps,
        outpainting_direction, expand_size,
        txt2img_row, video_row, outpaint_row,
        download_btn, unload_btn, generate_btn,
    )


# ============================================================
# 主应用
# ============================================================
def create_app():
    with gr.Blocks(
        title="AMD AI Studio — 本地 AI 创作工作室",
        theme=gr.themes.Soft(primary_hue="red", secondary_hue="orange", neutral_hue="gray"),
        css=CUSTOM_CSS,
    ) as demo:
        # 头部
        gr.HTML("""
        <div class="app-header">
            <h1>🎨 AMD AI Studio</h1>
            <p>基于 AMD Radeon™ GPU + ROCm™ 的多模态 AI 创作平台</p>
        </div>
        """)

        # ========== 三栏布局（独立滚动） ==========
        with gr.Row(equal_height=False):
            # 左侧：系统 + 模型
            with gr.Column(scale=28, min_width=260, elem_classes="scroll-col"):
                build_left_panel()

            # 中间：生成结果
            with gr.Column(scale=44, min_width=380, elem_classes="scroll-col"):
                gr.Markdown("### 🎨 结果", elem_classes="card-title")
                gallery = gr.Gallery(label="", columns=2, height=500, object_fit="contain", visible=True)
                video_output = gr.Video(label="", height=400, visible=False)
                image_output = gr.Image(label="", height=400, visible=False)
                status = gr.HTML("")

            # 右侧：功能参数
            with gr.Column(scale=30, min_width=300, elem_classes="scroll-col"):
                (function_type, model_selector, model_status,
                 prompt, neg_prompt, init_image, mask_image,
                 steps, guidance, seed, width, height, num_images,
                 strength, num_frames, fps,
                 outpainting_direction, expand_size,
                 txt2img_row, video_row, outpaint_row,
                 download_btn, unload_btn, generate_btn) = build_right_panel()

        # 页脚
        gr.HTML('<div class="app-footer">AMD AI Studio | AMD AI DevMaster Hackathon 2026</div>')

        # ============================================================
        # 事件绑定
        # ============================================================

        # --- 功能切换 ---
        def on_function_change(func_type):
            compat = get_compatible_models()
            type_map = {
                "txt2img": ["txt2img"], "img2img": ["txt2img", "img2img"],
                "img2video": ["img2video"], "inpainting": ["inpainting"],
                "outpainting": ["inpainting"],
            }
            allowed_types = type_map.get(func_type, ["txt2img"])
            choices = [(v["description"], k) for k, v in DEFAULT_MODEL_REGISTRY.items()
                       if v.get("type") in allowed_types and k in compat]
            if not choices:
                choices = [(v["description"], k) for k, v in DEFAULT_MODEL_REGISTRY.items()
                           if v.get("type") in allowed_types]
            default_val = choices[0][1] if choices else "sdxl-base"

            show_upload = func_type in ("img2img", "img2video", "inpainting")
            show_mask = func_type == "inpainting"
            show_strength = func_type in ("img2img", "inpainting")

            return (
                gr.update(choices=choices, value=default_val),
                # init_image: 同时更新可见性和标签
                gr.update(visible=show_upload,
                          label="📷 参考图" if func_type == "img2img" else
                                "📷 首帧图" if func_type == "img2video" else
                                "📷 原图"),
                gr.update(visible=show_mask),
                gr.update(visible=func_type == "txt2img"),  # txt2img_row
                gr.update(visible=func_type == "img2video"),  # video_row
                gr.update(visible=func_type == "outpainting"),  # outpaint_row
                gr.update(visible=show_strength),  # strength
                gr.update(visible=func_type == "img2video"),  # num_frames
                gr.update(visible=func_type == "img2video"),  # fps
                gr.update(visible=func_type == "outpainting"),  # direction
                gr.update(visible=func_type == "outpainting"),  # expand_size
                gr.update(placeholder="描述你想要的图像..." if func_type in ("txt2img","img2img") else
                          "描述要生成的内容" if func_type == "inpainting" else
                          "描述扩展区域" if func_type == "outpainting" else "描述视频内容"),
            )

        function_type.change(
            fn=on_function_change,
            inputs=[function_type],
            outputs=[
                model_selector,
                init_image, mask_image,
                txt2img_row, video_row, outpaint_row,
                strength, num_frames, fps,
                outpainting_direction, expand_size,
                prompt,
            ],
        )

        # 页面加载时初始化功能状态（默认 txt2img 隐藏上传区域）
        demo.load(
            fn=on_function_change,
            inputs=[function_type],
            outputs=[
                model_selector,
                init_image, mask_image,
                txt2img_row, video_row, outpaint_row,
                strength, num_frames, fps,
                outpainting_direction, expand_size,
                prompt,
            ],
        )

        # --- 模型切换 ---
        def on_model_change(model_key):
            params = global_loader.get_model_params(model_key)
            ms = global_loader.get_model_status(model_key)
            can_load, msg = smart_mgr.should_load_model(model_key)
            status_text = f'<span class="badge badge-{ms.status}">{ms.status}</span> {ms.message}'
            if not can_load and ms.status != STATUS_DOWNLOADED:
                status_text += f'<br><span style="color:#e94560">⚠️ {msg}</span>'
            return (
                params.get("default_steps", 30),
                params.get("default_guidance", 7.5),
                params.get("default_width", 1024),
                params.get("default_height", 1024),
                status_text,
            )

        model_selector.change(on_model_change, model_selector, [steps, guidance, width, height, model_status])

        # --- 下载 ---
        def on_download(model_key):
            if global_loader.is_model_downloaded(model_key):
                return f'<span class="badge badge-downloaded">✅ 已下载</span>'
            if global_loader.is_downloading(model_key):
                return f'<span class="badge badge-downloading">⏳ 下载中</span>'
            global_loader.start_download(model_key)
            return f'<span class="badge badge-downloading">⏳ 已启动后台下载</span>'

        download_btn.click(on_download, model_selector, [status])

        # --- 卸载 ---
        def on_unload(model_key):
            freed = global_loader.unload_pipeline(model_key)
            return f'<span class="badge badge-downloaded">✅ 已卸载 (释放 {freed:.1f}GB)</span>'

        unload_btn.click(on_unload, model_selector, [status])

        # --- 生成分发 ---
        def on_generate(func_type, model_key, prompt, neg, s, g, sd,
                        w, h, ni, st, nf, fp, direction, expand, img, mask):
            try:
                if func_type == "img2video":
                    result, status_msg = _generate_video(model_key, img, nf, s, fp, sd, "gif")
                    return gr.update(), result, status_msg
                elif func_type == "txt2img":
                    result, status_msg = _generate_txt2img(model_key, prompt, neg, s, g, w, h, sd, ni)
                    return result, gr.update(), status_msg
                elif func_type == "img2img":
                    result, status_msg = _generate_img2img(model_key, img, prompt, neg, st, s, g, sd)
                    return result, gr.update(), status_msg
                elif func_type == "inpainting":
                    result, status_msg = _generate_inpaint(model_key, img, mask, prompt, s, st, sd)
                    return result, gr.update(), status_msg
                elif func_type == "outpainting":
                    result, status_msg = _generate_outpaint(img, prompt, direction, expand, sd)
                    return result, gr.update(), status_msg
                return None, gr.update(), '<span style="color:#e94560">❌ 未知功能</span>'
            except Exception as e:
                return None, gr.update(), f'<span style="color:#e94560">❌ {e}</span>'

        generate_btn.click(
            fn=on_generate,
            inputs=[
                function_type, model_selector, prompt, neg_prompt,
                steps, guidance, seed,
                width, height, num_images,
                strength, num_frames, fps,
                outpainting_direction, expand_size,
                init_image, mask_image,
            ],
            outputs=[gallery, video_output, status],
        )

    return demo


# ============================================================
# 各功能生成逻辑
# ============================================================

def _generate_txt2img(model_key, prompt, neg, s, g, w, h, sd, ni):
    if not prompt.strip():
        return [], '<span style="color:#e94560">⚠️ 请输入提示词</span>'
    if not global_loader.is_model_downloaded(model_key):
        return [], f'<span style="color:#e94560">❌ 模型 {model_key} 未下载</span>'
    can_load, msg = smart_mgr.should_load_model(model_key)
    if not can_load:
        return [], f'<span style="color:#e94560">⚠️ {msg}</span>'
    pipe = global_loader.load_pipeline(model_key, "txt2img")
    import torch
    seed_val = None if sd == -1 else int(sd)
    generator = torch.Generator(device="cpu").manual_seed(seed_val) if seed_val is not None else None
    images = []
    for i in range(int(ni)):
        img = pipe(
            prompt=prompt, negative_prompt=neg or None,
            width=int(w), height=int(h),
            num_inference_steps=int(s), guidance_scale=g,
            generator=generator,
        ).images[0]
        _save_image(img, "txt2img")
        images.append(img)
    return images, f'<span style="color:#10b981">✅ 生成完成，共 {len(images)} 张</span>'


def _generate_img2img(model_key, img, p, np, st, s, g, sd):
    if img is None:
        return None, '<span style="color:#e94560">⚠️ 请上传参考图</span>'
    if not global_loader.is_model_downloaded(model_key):
        return None, f'<span style="color:#e94560">❌ 模型 {model_key} 未下载</span>'
    pipe = global_loader.load_pipeline(model_key, "img2img")
    import torch
    gen = torch.Generator(device="cpu").manual_seed(int(sd) if sd != -1 else 42)
    result = pipe(
        prompt=p, image=img, strength=st,
        num_inference_steps=int(s), guidance_scale=g,
        negative_prompt=np or None, generator=gen,
    ).images[0]
    _save_image(result, "img2img")
    return [result], '<span style="color:#10b981">✅ 完成</span>'


def _generate_video(model_key, img, nf, s, fps_, sd, fmt="gif"):
    if img is None:
        return None, '<span style="color:#e94560">⚠️ 请上传首帧图</span>'
    if not global_loader.is_model_downloaded(model_key):
        return None, f'<span style="color:#e94560">❌ 模型 {model_key} 未下载</span>'
    pipe = global_loader.load_pipeline(model_key, "img2video")
    import torch
    gen = torch.Generator(device="cpu").manual_seed(int(sd) if sd != -1 else 42)
    # SVD pipeline 需要 PIL Image 或 torch.Tensor
    if hasattr(img, 'convert'):
        img = img.convert('RGB')
    frames = pipe(
        image=img, num_frames=int(nf), num_inference_steps=int(s),
        decode_chunk_size=2, generator=gen,
    ).frames[0]
    pil_frames = [Image.fromarray(f) if not isinstance(f, Image.Image) else f for f in frames]
    path = str(OUTPUT_DIR / "gifs" / f"svd_{int(time.time())}.gif")
    dur = int(1000 / int(fps_))
    pil_frames[0].save(path, save_all=True, append_images=pil_frames[1:], duration=dur, loop=0)
    return [path], '<span style="color:#10b981">✅ 完成</span>'


def _generate_inpaint(model_key, img, mask, p, s, st, sd):
    if img is None or mask is None:
        return None, '<span style="color:#e94560">⚠️ 请上传原图和蒙版</span>'
    if not global_loader.is_model_downloaded(model_key):
        return None, f'<span style="color:#e94560">❌ 模型 {model_key} 未下载</span>'
    pipe = global_loader.load_pipeline(model_key, "inpainting")
    import torch
    gen = torch.Generator(device="cpu").manual_seed(int(sd) if sd != -1 else 42)
    result = pipe(
        prompt=p, image=img, mask_image=mask,
        strength=st, num_inference_steps=int(s), generator=gen,
    ).images[0]
    _save_image(result, "inpaint")
    return [result], '<span style="color:#10b981">✅ 完成</span>'


def _generate_outpaint(img, p, direction, es, sd):
    if img is None:
        return None, '<span style="color:#e94560">⚠️ 请上传原图</span>'
    if not global_loader.is_model_downloaded("sd-inpaint"):
        return None, '<span style="color:#e94560">❌ 模型 sd-inpaint 未下载</span>'
    from modules.image_edit import generate_outpainting
    result = generate_outpainting(
        init_image=img, prompt=p,
        expansion_pixels=int(es), direction=direction,
        seed=int(sd) if sd != -1 else None,
    )
    _save_image(result, "outpaint")
    return [result], '<span style="color:#10b981">✅ 完成</span>'


if __name__ == "__main__":
    import torch
    print("=" * 60)
    print("  AMD AI Studio v2")
    print("=" * 60)
    print(f"  ROCm: {is_rocm_available()} | PyTorch: {torch.__version__}")
    if torch.cuda.is_available() and hasattr(torch.version, 'rocm'):
        print(f"  ROCm: {torch.version.rocm}")
    print(f"  GPU: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'N/A'}")
    print(f"  显存: {get_total_vram_gb():.0f}GB")
    print(f"  核心模型自动后台下载中...")
    print("=" * 60)
    print("  访问 http://localhost:7860")
    print("=" * 60)

    demo = create_app()
    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        debug=False,
    )