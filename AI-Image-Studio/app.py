# -*- coding: utf-8 -*-
"""AI-Image-Studio（Radeon 智图工坊）—— 基于 AMD Radeon GPU + ROCm 的一站式智能图像编辑器。

功能：局部重绘 / 智能扩图 / 物体与水印移除 / 超分辨率 / 风格迁移（含批量）/ 背景移除与替换。
启动：python app.py 后浏览器打开 http://localhost:7860
"""
from __future__ import annotations

import argparse
import os

# 关闭 Gradio 遥测，避免在隔离网络（如 GPU 云主机）中启动时阻塞
os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")

import gradio as gr
from PIL import Image

from config import settings
from src.device import detect_device, free_vram_gb
from src.model_manager import ModelManager
from src.pipelines import (POSTER_SIZES, STYLE_PRESETS, run_background,
                           run_character_split, run_ecommerce, run_face_restore,
                           run_inpaint, run_outpaint, run_poster_batch, run_remove,
                           run_style, run_style_batch, run_upscale, run_video_upscale)
from src.utils import editor_to_image_mask

DEVICE_INFO = detect_device(settings.device, settings.dtype)
MANAGER = ModelManager(DEVICE_INFO, settings)

APP_TITLE = "🎨 AI-Image-Studio · Radeon 智图工坊"
APP_DESC = ("一站式智能图像与视频编辑器：局部重绘 · 智能扩图 · 物体移除 · 超分辨率 · 风格迁移 · "
            "背景替换 · 人像修复 · 素材拆分 · 海报批量 · 视频超分 · 电商工坊。"
            " 针对 **AMD Radeon GPU + ROCm** 优化，支持 LCM-LoRA 极速生成（快 3~5 倍），自动适配 ROCm / CUDA / CPU。")


# ------------------------- 公共辅助 -------------------------

def _perf_md(info: dict) -> str:
    lines = ["| 指标 | 数值 |", "| --- | --- |"]
    for k, v in info.items():
        lines.append(f"| {k} | {v} |")
    return "\n".join(lines)


def _err(e: Exception):
    raise gr.Error(f"{type(e).__name__}：{e}")


def _status_md() -> str:
    loaded = MANAGER.loaded_models()
    lines = [
        "### 运行环境",
        f"- 推理后端：**{DEVICE_INFO.summary()}**",
        f"- 低显存模式：{'开' if settings.low_vram else '关'}",
        f"- 扩散工作分辨率：最长边 {settings.max_diffusion_size}px",
    ]
    if DEVICE_INFO.device.type == "cuda":
        lines.append(f"- 当前空闲显存：{free_vram_gb():.2f} GB")
    lines += ["", "### 已加载模型"]
    lines += [f"- {m}" for m in loaded] if loaded else ["- （暂无，各模型按需懒加载）"]
    return "\n".join(lines)


def _editor(label: str, height: int = 460) -> gr.ImageEditor:
    return gr.ImageEditor(
        label=label, type="pil", sources=["upload", "clipboard"],
        transforms=(), layers=False, height=height,
        brush=gr.Brush(default_size=32, colors=["#FFFFFF"], color_mode="fixed"),
        eraser=gr.Eraser(default_size=32),
    )


# ------------------------- 各功能回调 -------------------------

def cb_inpaint(editor, prompt, negative, expand, steps, guidance, strength, seed, fast):
    try:
        image, mask = editor_to_image_mask(editor, expand_px=int(expand))
        out, info, _ = run_inpaint(MANAGER, image, mask, prompt, negative,
                                   steps, guidance, strength, seed, fast)
        return out, _perf_md(info)
    except Exception as e:
        _err(e)


def cb_outpaint(image, left, right, top, bottom, prompt, negative, steps, guidance, seed, fast):
    try:
        out, info, _ = run_outpaint(MANAGER, image, left, right, top, bottom,
                                    prompt, negative, steps, guidance, seed, fast)
        return out, _perf_md(info)
    except Exception as e:
        _err(e)


def cb_remove(editor, expand):
    try:
        image, mask = editor_to_image_mask(editor, expand_px=int(expand))
        out, info = run_remove(MANAGER, image, mask)
        return out, _perf_md(info)
    except Exception as e:
        _err(e)


def cb_upscale(image, quality, target_scale, tile):
    try:
        out, info = run_upscale(MANAGER, image, quality, float(target_scale), int(tile))
        return out, _perf_md(info)
    except Exception as e:
        _err(e)


def cb_style(image, style, strength, custom_prompt, custom_negative, steps, guidance, seed,
             fast, lora_ref, lora_scale):
    try:
        out, info, _ = run_style(MANAGER, image, style, custom_prompt, custom_negative,
                                 strength, steps, guidance, seed, fast, lora_ref, lora_scale)
        return out, _perf_md(info)
    except Exception as e:
        _err(e)


def cb_style_batch(files, style, strength, fast):
    try:
        images = [Image.open(p).convert("RGB") for p in (files or [])]
        if not images:
            raise ValueError("请先上传至少一张图片。")
        outs, summary = run_style_batch(MANAGER, images, style, "", "",
                                        strength, steps=25, guidance=7.5, fast=fast)
        return outs, _perf_md(summary)
    except Exception as e:
        _err(e)


def cb_background(image, mode, solid, gt, gb, ai_prompt):
    try:
        result, fg, info = run_background(MANAGER, image, mode, solid, gt, gb, ai_prompt)
        return result, fg, _perf_md(info)
    except Exception as e:
        _err(e)


def cb_face_restore(image, also_upscale):
    try:
        out, info = run_face_restore(MANAGER, image, bool(also_upscale))
        return out, _perf_md(info)
    except Exception as e:
        _err(e)


def cb_character_split(image, fill_bg, margin):
    try:
        character, background, psd_path, zip_path, info = run_character_split(
            MANAGER, image, bool(fill_bg), int(margin))
        files = [f for f in (psd_path, zip_path) if f]
        return character, background, files, _perf_md(info)
    except Exception as e:
        _err(e)


def cb_poster(prompt, negative, size_name, title, subtitle, tag, layout,
              count, steps, guidance, seed, do_upscale, fast, lora_ref, lora_scale):
    try:
        posters, info = run_poster_batch(
            MANAGER, prompt, negative, size_name, title, subtitle, tag, layout,
            count, steps, guidance, seed, bool(do_upscale), fast, lora_ref, lora_scale)
        return posters, _perf_md(info)
    except Exception as e:
        _err(e)


def cb_video(video_path, quality, scale, progress=gr.Progress()):
    try:
        out_path, info = run_video_upscale(MANAGER, video_path, quality, float(scale),
                                           progress_cb=lambda p, d: progress(p, desc=d))
        return out_path, _perf_md(info)
    except Exception as e:
        _err(e)


def cb_ecommerce(image, scene_prompt, title, subtitle, size_name, scene_count, do_upscale, fast):
    try:
        images, info = run_ecommerce(MANAGER, image, scene_prompt, title, subtitle,
                                     size_name, scene_count, bool(do_upscale), fast)
        return images, _perf_md(info)
    except Exception as e:
        _err(e)


# ------------------------- 界面 -------------------------

APP_CSS = """
.gradio-container {max-width: 1280px; margin: auto;}
#header {text-align: center; margin-bottom: 4px;}
"""


def build_demo() -> gr.Blocks:
    # Gradio 6 将 css 从 Blocks 移到了 launch()；此处仅传兼容参数
    with gr.Blocks(title=APP_TITLE) as demo:
        gr.Markdown(f"# {APP_TITLE}\n{APP_DESC}", elem_id="header")
        gr.Markdown(f"**运行后端：** {DEVICE_INFO.summary()}")

        with gr.Tabs():
            # ============ 1. 局部重绘 ============
            with gr.Tab("🖌️ 局部重绘"):
                gr.Markdown("上传图片 → 用画笔涂抹要修改的区域 → 用文字描述想要的内容（如：把衣服换成红色、添加一只猫）。")
                with gr.Row():
                    with gr.Column(scale=1):
                        ed = _editor("上传图片并涂抹区域")
                        prompt = gr.Textbox(label="提示词（描述该区域要生成的内容）",
                                            placeholder="例如：a red rose, crystal clear")
                        negative = gr.Textbox(label="负面提示词", value="blurry, low quality, deformed, watermark, text")
                        with gr.Accordion("高级参数", open=False):
                            expand = gr.Slider(0, 40, 8, step=1, label="遮罩边缘扩张（像素）")
                            steps = gr.Slider(10, 50, 25, step=1, label="推理步数")
                            guidance = gr.Slider(1.0, 15.0, 7.0, step=0.5, label="引导强度 CFG")
                            strength = gr.Slider(0.5, 1.0, 1.0, step=0.05, label="重绘幅度")
                            seed = gr.Number(-1, label="随机种子（-1 为随机）", precision=0)
                        fast = gr.Checkbox(value=False, label="⚡ LCM 极速模式（4~8 步，快 3~5 倍）")
                        btn = gr.Button("开始重绘", variant="primary")
                    with gr.Column(scale=1):
                        out = gr.Image(label="重绘结果", type="pil", interactive=False, height=460)
                        perf = gr.Markdown()
                btn.click(cb_inpaint, [ed, prompt, negative, expand, steps, guidance, strength, seed, fast],
                          [out, perf])

            # ============ 2. 智能扩图 ============
            with gr.Tab("🔍 智能扩图"):
                gr.Markdown("上传图片并设置四个方向的扩展像素，AI 将无缝补全延展画面。")
                with gr.Row():
                    with gr.Column(scale=1):
                        img = gr.Image(label="上传图片", type="pil", sources=["upload", "clipboard"], height=320)
                        with gr.Row():
                            left = gr.Slider(0, 512, 0, step=32, label="向左扩展 px")
                            right = gr.Slider(0, 512, 256, step=32, label="向右扩展 px")
                        with gr.Row():
                            top = gr.Slider(0, 512, 0, step=32, label="向上扩展 px")
                            bottom = gr.Slider(0, 512, 0, step=32, label="向下扩展 px")
                        prompt = gr.Textbox(label="提示词（描述延展后的完整画面）",
                                            placeholder="例如：wide landscape, mountains and lake, golden hour")
                        negative = gr.Textbox(label="负面提示词", value="blurry, low quality, seam, watermark, text")
                        with gr.Accordion("高级参数", open=False):
                            steps2 = gr.Slider(10, 50, 28, step=1, label="推理步数")
                            guidance2 = gr.Slider(1.0, 15.0, 7.0, step=0.5, label="引导强度 CFG")
                            seed2 = gr.Number(-1, label="随机种子（-1 为随机）", precision=0)
                        fast2 = gr.Checkbox(value=False, label="⚡ LCM 极速模式（4~8 步，快 3~5 倍）")
                        btn2 = gr.Button("开始扩图", variant="primary")
                    with gr.Column(scale=1):
                        out2 = gr.Image(label="扩图结果", type="pil", interactive=False, height=460)
                        perf2 = gr.Markdown()
                btn2.click(cb_outpaint, [img, left, right, top, bottom, prompt, negative,
                                         steps2, guidance2, seed2, fast2], [out2, perf2])

            # ============ 3. 物体 / 水印移除 ============
            with gr.Tab("🧽 物体/水印移除"):
                gr.Markdown("上传图片 → 用画笔涂抹要去除的物体、路人或水印 → 一键无痕移除（LaMa 引擎，无需提示词）。")
                with gr.Row():
                    with gr.Column(scale=1):
                        ed3 = _editor("上传图片并涂抹要移除的区域")
                        expand3 = gr.Slider(0, 40, 12, step=1, label="遮罩边缘扩张（像素）")
                        btn3 = gr.Button("一键移除", variant="primary")
                    with gr.Column(scale=1):
                        out3 = gr.Image(label="移除结果", type="pil", interactive=False, height=460)
                        perf3 = gr.Markdown()
                btn3.click(cb_remove, [ed3, expand3], [out3, perf3])

            # ============ 4. 超分辨率 ============
            with gr.Tab("✨ 超分辨率"):
                gr.Markdown("Real-ESRGAN 高清放大：修复模糊、提升分辨率，支持大图的低显存分块推理。")
                with gr.Row():
                    with gr.Column(scale=1):
                        img4 = gr.Image(label="上传图片", type="pil", sources=["upload", "clipboard"], height=320)
                        quality = gr.Radio([("轻量高速（x4v3，推荐批量）", "fast"),
                                            ("高画质（x4plus）", "hq")],
                                           value="fast", label="模型档位")
                        scale4 = gr.Slider(1.5, 4.0, 4.0, step=0.5, label="放大倍率")
                        tile = gr.Dropdown([("关闭（显存充足）", 0), ("512px 分块", 512), ("256px 分块（大图/低显存）", 256)],
                                           value=0, label="分块推理")
                        btn4 = gr.Button("开始放大", variant="primary")
                    with gr.Column(scale=1):
                        out4 = gr.Image(label="放大结果", type="pil", interactive=False, height=460)
                        perf4 = gr.Markdown()
                btn4.click(cb_upscale, [img4, quality, scale4, tile], [out4, perf4])

            # ============ 5. 风格迁移 ============
            with gr.Tab("🎭 风格迁移"):
                gr.Markdown("一键将照片重构为动漫、赛博朋克、水彩、油画等艺术风格，支持单张精调与批量处理。")
                with gr.Tabs():
                    with gr.Tab("单张精调"):
                        with gr.Row():
                            with gr.Column(scale=1):
                                img5 = gr.Image(label="上传图片", type="pil", sources=["upload", "clipboard"], height=320)
                                style = gr.Dropdown(list(STYLE_PRESETS.keys()), value="日系动漫", label="风格预设")
                                strength5 = gr.Slider(0.2, 0.95, 0.6, step=0.05, label="重绘幅度（越大越脱离原图）")
                                with gr.Accordion("自定义提示词（可选，覆盖预设）", open=False):
                                    cp = gr.Textbox(label="自定义提示词", placeholder="留空则使用风格预设")
                                    cn = gr.Textbox(label="自定义负面提示词")
                                with gr.Accordion("高级参数", open=False):
                                    steps5 = gr.Slider(10, 50, 25, step=1, label="推理步数")
                                    guidance5 = gr.Slider(1.0, 15.0, 7.5, step=0.5, label="引导强度 CFG")
                                    seed5 = gr.Number(-1, label="随机种子（-1 为随机）", precision=0)
                                with gr.Accordion("自定义 LoRA（可选）", open=False):
                                    lora5 = gr.Textbox(label="LoRA 仓库 ID 或本地 .safetensors 路径",
                                                       placeholder="例如：someone/my-style-lora")
                                    lora_scale5 = gr.Slider(0.0, 1.5, 0.8, step=0.05, label="LoRA 权重")
                                fast5 = gr.Checkbox(value=False, label="⚡ LCM 极速模式（4~8 步）")
                                btn5 = gr.Button("开始迁移", variant="primary")
                            with gr.Column(scale=1):
                                out5 = gr.Image(label="风格化结果", type="pil", interactive=False, height=460)
                                perf5 = gr.Markdown()
                        btn5.click(cb_style, [img5, style, strength5, cp, cn, steps5, guidance5, seed5,
                                              fast5, lora5, lora_scale5],
                                   [out5, perf5])
                    with gr.Tab("批量处理"):
                        with gr.Row():
                            with gr.Column(scale=1):
                                files = gr.File(label="上传多张图片", file_count="multiple",
                                                file_types=["image"], type="filepath")
                                style_b = gr.Dropdown(list(STYLE_PRESETS.keys()), value="赛博朋克", label="风格预设")
                                strength_b = gr.Slider(0.2, 0.95, 0.6, step=0.05, label="重绘幅度")
                                fast6 = gr.Checkbox(value=True, label="⚡ LCM 极速模式（批量推荐）")
                                btn6 = gr.Button("批量开始", variant="primary")
                            with gr.Column(scale=1):
                                gallery = gr.Gallery(label="批量结果", columns=3, height=460)
                                perf6 = gr.Markdown()
                        btn6.click(cb_style_batch, [files, style_b, strength_b, fast6], [gallery, perf6])

            # ============ 6. 背景移除与替换 ============
            with gr.Tab("🧑‍🎨 背景替换"):
                gr.Markdown("BiRefNet 高精度抠图：导出透明 PNG、替换纯色/渐变背景，或用 AI 生成全新背景。")
                with gr.Row():
                    with gr.Column(scale=1):
                        img7 = gr.Image(label="上传图片", type="pil", sources=["upload", "clipboard"], height=320)
                        mode = gr.Radio(["透明 PNG", "纯色背景", "渐变背景", "AI 生成背景"],
                                        value="透明 PNG", label="输出模式")
                        with gr.Accordion("背景选项", open=True):
                            solid = gr.ColorPicker(value="#FFFFFF", label="纯色背景颜色")
                            with gr.Row():
                                gt = gr.ColorPicker(value="#89CFF0", label="渐变顶部")
                                gb = gr.ColorPicker(value="#F0E68C", label="渐变底部")
                            ai_prompt = gr.Textbox(label="AI 背景提示词",
                                                   placeholder="例如：sunset beach, bokeh studio backdrop")
                        btn7 = gr.Button("开始处理", variant="primary")
                    with gr.Column(scale=1):
                        with gr.Row():
                            out7 = gr.Image(label="结果", type="pil", interactive=False, height=440)
                            fg7 = gr.Image(label="抠出的前景（RGBA）", type="pil", interactive=False, height=440)
                        perf7 = gr.Markdown()
                btn7.click(cb_background, [img7, mode, solid, gt, gb, ai_prompt], [out7, fg7, perf7])

            # ============ 7. 人像修复 ============
            with gr.Tab("😊 人像修复"):
                gr.Markdown("GFPGAN 盲人脸修复：模糊、低清、老照片人脸一键变清晰，支持多人脸，可联动超分放大整图。")
                with gr.Row():
                    with gr.Column(scale=1):
                        img8 = gr.Image(label="上传含人脸的图片", type="pil",
                                        sources=["upload", "clipboard"], height=320)
                        up8 = gr.Checkbox(value=False, label="修复后联动 2× 超分放大整图")
                        btn8 = gr.Button("开始修复", variant="primary")
                    with gr.Column(scale=1):
                        out8 = gr.Image(label="修复结果", type="pil", interactive=False, height=460)
                        perf8 = gr.Markdown()
                btn8.click(cb_face_restore, [img8, up8], [out8, perf8])

            # ============ 8. 素材拆分 ============
            with gr.Tab("🧩 素材拆分"):
                gr.Markdown("上传单张角色图，自动拆分为**透明角色层 + 完整背景层**，导出分层 PSD 与素材包（Live2D 前处理、2.5D 创作）。")
                with gr.Row():
                    with gr.Column(scale=1):
                        img9 = gr.Image(label="上传角色图片", type="pil",
                                        sources=["upload", "clipboard"], height=320)
                        fill9 = gr.Checkbox(value=True, label="AI 补全背景（抹除角色后填充）")
                        margin9 = gr.Slider(0, 64, 16, step=4, label="素材裁切边距（像素）")
                        btn9 = gr.Button("开始拆分", variant="primary")
                    with gr.Column(scale=1):
                        with gr.Row():
                            chara9 = gr.Image(label="角色层（透明）", type="pil", interactive=False, height=300)
                            bg9 = gr.Image(label="背景层", type="pil", interactive=False, height=300)
                        files9 = gr.File(label="下载分层文件（PSD + 素材包）", file_count="multiple")
                        perf9 = gr.Markdown()
                btn9.click(cb_character_split, [img9, fill9, margin9],
                           [chara9, bg9, files9, perf9])

            # ============ 9. 海报批量 ============
            with gr.Tab("🖼️ 海报批量"):
                gr.Markdown("文生图 → 2× 超分 → 模板排版，批量产出电商主图 / 活动海报 / 内容封面（中文精确排版，无乱码）。")
                with gr.Row():
                    with gr.Column(scale=1):
                        prompt10 = gr.Textbox(label="画面描述（提示词）", lines=2,
                                              placeholder="例如：fresh oranges splashing juice, studio lighting, commercial photography")
                        negative10 = gr.Textbox(label="负面提示词",
                                                value="blurry, low quality, watermark, text, logo")
                        with gr.Row():
                            size10 = gr.Dropdown(list(POSTER_SIZES.keys()),
                                                 value="竖版海报 2:3（1024×1536）", label="尺寸")
                            count10 = gr.Slider(1, 8, 2, step=1, label="批量数量")
                        with gr.Row():
                            title10 = gr.Textbox(label="主标题", placeholder="例如：夏日狂欢节")
                            subtitle10 = gr.Textbox(label="副标题", placeholder="例如：全场五折起")
                        with gr.Row():
                            tag10 = gr.Textbox(label="角标文字（可选）", placeholder="例如：限时特惠")
                            layout10 = gr.Radio(["底部横幅", "顶部标题", "居中大标题"],
                                                value="底部横幅", label="排版布局")
                        with gr.Accordion("高级参数", open=False):
                            steps10 = gr.Slider(10, 50, 25, step=1, label="推理步数")
                            guidance10 = gr.Slider(1.0, 15.0, 7.5, step=0.5, label="引导强度 CFG")
                            seed10 = gr.Number(-1, label="随机种子（-1 为随机，批量顺延）", precision=0)
                            up10 = gr.Checkbox(value=True, label="生成后 2× 超分（推荐）")
                            fast10 = gr.Checkbox(value=False, label="⚡ LCM 极速模式（4~8 步）")
                            lora10 = gr.Textbox(label="自定义 LoRA（可选）",
                                                placeholder="HF 仓库 ID 或本地 .safetensors 路径")
                            lora_scale10 = gr.Slider(0.0, 1.5, 0.8, step=0.05, label="LoRA 权重")
                        btn10 = gr.Button("批量生成海报", variant="primary")
                    with gr.Column(scale=1):
                        gallery10 = gr.Gallery(label="海报结果", columns=2, height=520)
                        perf10 = gr.Markdown()
                btn10.click(cb_poster, [prompt10, negative10, size10, title10, subtitle10,
                                        tag10, layout10, count10, steps10, guidance10,
                                        seed10, up10, fast10, lora10, lora_scale10], [gallery10, perf10])

            # ============ 10. 视频超分 ============
            with gr.Tab("🎬 视频超分"):
                gr.Markdown("AI 视频增强：逐帧超分放大 + 原音轨保留合成。面向短视频（默认 ≤30 秒、≤720p）。")
                with gr.Row():
                    with gr.Column(scale=1):
                        video11 = gr.Video(label="上传视频（建议 mp4）", sources=["upload"])
                        quality11 = gr.Radio([("轻量高速（推荐）", "fast"), ("高画质", "hq")],
                                             value="fast", label="超分档位")
                        scale11 = gr.Radio([("2×", 2.0), ("4×", 4.0)], value=2.0, label="放大倍率")
                        btn11 = gr.Button("开始增强", variant="primary")
                    with gr.Column(scale=1):
                        out11 = gr.Video(label="增强结果", interactive=False)
                        perf11 = gr.Markdown()
                btn11.click(cb_video, [video11, quality11, scale11], [out11, perf11])

            # ============ 11. 电商工坊 ============
            with gr.Tab("🛒 电商工坊"):
                gr.Markdown("上传一张产品图，一键产出整套电商素材：**白底主图 + AI 场景图 + 排版海报**。")
                with gr.Row():
                    with gr.Column(scale=1):
                        img12 = gr.Image(label="上传产品图", type="pil",
                                         sources=["upload", "clipboard"], height=300)
                        scene12 = gr.Textbox(
                            label="场景描述（提示词）", lines=2,
                            value="modern minimalist product photography, marble surface, soft studio lighting",
                            placeholder="描述想要的拍摄场景")
                        with gr.Row():
                            title12 = gr.Textbox(label="海报主标题", placeholder="例如：焕新上市")
                            subtitle12 = gr.Textbox(label="海报副标题", placeholder="例如：匠心之作")
                        with gr.Row():
                            size12 = gr.Dropdown(list(POSTER_SIZES.keys()),
                                                 value="方形主图 1:1（1024×1024）", label="尺寸")
                            count12 = gr.Slider(1, 4, 2, step=1, label="场景图数量")
                        with gr.Row():
                            up12 = gr.Checkbox(value=True, label="2× 超分（推荐）")
                            fast12 = gr.Checkbox(value=False, label="⚡ LCM 极速模式")
                        btn12 = gr.Button("一键生成整套素材", variant="primary")
                    with gr.Column(scale=1):
                        gallery12 = gr.Gallery(label="素材结果（主图/场景图/海报）", columns=3, height=520)
                        perf12 = gr.Markdown()
                btn12.click(cb_ecommerce, [img12, scene12, title12, subtitle12, size12,
                                           count12, up12, fast12], [gallery12, perf12])

            # ============ 12. 系统状态 ============
            with gr.Tab("⚙️ 系统状态"):
                status = gr.Markdown(_status_md())
                with gr.Row():
                    refresh = gr.Button("刷新状态")
                    unload = gr.Button("卸载全部模型（释放显存）", variant="stop")
                refresh.click(lambda: _status_md(), None, status)
                unload.click(lambda: (MANAGER.unload_all(), _status_md())[1], None, status)
        return demo


def main():
    parser = argparse.ArgumentParser(description="AI-Image-Studio · Radeon 智图工坊")
    parser.add_argument("--host", default=settings.server_name)
    parser.add_argument("--port", type=int, default=settings.server_port)
    parser.add_argument("--share", action="store_true", default=settings.share)
    parser.add_argument("--preload", action="store_true", help="启动时预载局部重绘模型")
    parser.add_argument("--low-vram", action="store_true", help="强制开启低显存模式")
    args = parser.parse_args()

    if args.low_vram:
        settings.low_vram = True
    if args.preload:
        print("正在预载局部重绘模型……")
        MANAGER.get_inpaint_pipe()

    print(f"推理后端：{DEVICE_INFO.summary()}")
    demo = build_demo()
    launch_kwargs = dict(server_name=args.host, server_port=args.port,
                         share=args.share, show_error=True)
    import inspect as _inspect
    if "css" in _inspect.signature(gr.Blocks.launch).parameters:
        launch_kwargs["css"] = APP_CSS  # Gradio 6+
    demo.launch(**launch_kwargs)


if __name__ == "__main__":
    main()
