from __future__ import annotations

import traceback
from pathlib import Path
from typing import Any

import gradio as gr

from configs.prompt_templates import (
    ASPECT_RATIOS,
    CREATIVE_TYPES,
    DEFAULT_NEGATIVE_PROMPT,
    QUALITY_TEMPLATES,
    STYLE_TEMPLATES,
    build_prompt,
)
from pipeline.image_generator import ImageGenerator
from pipeline.image_enhancer import ImageEnhancer


# ============================================================
# 初始化模型
# ============================================================

generator = ImageGenerator()
enhancer = ImageEnhancer()


# 本次应用运行期间的生成记录。
# 每个元素结构：
# (
#     图片文件路径,
#     图片标题
# )
OUTPUT_HISTORY_LIMIT = 40


def refresh_history_gallery():
    """
    每次页面加载时重新扫描 outputs 目录。
    """
    global generation_history

    generation_history = load_generation_history()

    return list(generation_history)

def build_history_caption(image_path: Path) -> str:
    """
    根据文件名生成画廊标题。
    """
    filename = image_path.stem

    if "text2img" in filename:
        mode = "文字生成图片"
    elif "img2img" in filename:
        mode = "参考图重绘"
    elif "enhanced" in filename:
        mode = "图片增强"
    else:
        mode = "历史作品"

    modified_time = image_path.stat().st_mtime

    from datetime import datetime

    time_text = datetime.fromtimestamp(
        modified_time
    ).strftime("%Y-%m-%d %H:%M:%S")

    return f"{mode}｜{time_text}"


def load_generation_history() -> list[tuple[str, str]]:
    """
    从 outputs 目录读取历史图片。

    按文件修改时间倒序排列，
    最近生成的图片显示在最前面。
    """
    output_dir = Path("outputs")
    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    supported_extensions = {
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
    }

    image_files = [
        path
        for path in output_dir.iterdir()
        if path.is_file()
        and path.suffix.lower() in supported_extensions
    ]

    image_files.sort(
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )

    history: list[tuple[str, str]] = []

    for image_path in image_files[:OUTPUT_HISTORY_LIMIT]:
        history.append(
            (
                str(image_path.resolve()),
                build_history_caption(image_path),
            )
        )

    return history


generation_history: list[tuple[str, str]] = (
    load_generation_history()
)


# ============================================================
# 公共工具函数
# ============================================================

def preview_final_prompt(
    user_prompt: str,
    creative_type: str,
    style: str,
    quality: str,
) -> str:
    """
    根据用户输入、创作类型、视觉风格和质量等级，
    自动拼接最终发送给模型的 Prompt。
    """
    try:
        return build_prompt(
            user_prompt=user_prompt,
            creative_type=creative_type,
            style=style,
            quality=quality,
        )
    except Exception:
        return ""


def add_to_history(
    image_path: str,
    caption: str,
) -> list[tuple[str, str]]:
    """
    将新结果加入历史画廊。
    最多保存最近 20 张。
    """
    generation_history.insert(
        0,
        (
            image_path,
            caption,
        ),
    )

    del generation_history[OUTPUT_HISTORY_LIMIT:]

    return list(generation_history)


def build_gpu_markdown(
    result: dict[str, Any],
) -> str:
    """
    根据推理结果生成 AMD GPU 信息面板。
    """
    lines = [
        "### AMD GPU 推理信息",
        "",
        f"- **运行模式：** {result.get('mode', '未知')}",
        f"- **GPU：** {result.get('gpu_name', '未知')}",
        f"- **显存：** {result.get('vram_gb', '未知')} GB",
        "- **运行后端：** PyTorch ROCm",
        f"- **分辨率：** "
        f"{result.get('width', '未知')} × "
        f"{result.get('height', '未知')}",
        f"- **推理步数：** {result.get('steps', '未知')}",
    ]

    if "strength" in result:
        lines.append(
            f"- **重绘强度：** {result['strength']}"
        )

    lines.extend(
        [
            f"- **推理耗时：** {result.get('time', '未知')} 秒",
            f"- **随机种子：** {result.get('seed', '未知')}",
        ]
    )

    return "\n".join(lines)


# ============================================================
# Text-to-Image：文字生成图片
# ============================================================

def generate_image(
    user_prompt: str,
    creative_type: str,
    style: str,
    aspect_ratio: str,
    quality: str,
    negative_prompt: str,
    guidance_scale: float,
    seed: float,
):
    """
    文生图事件处理函数。
    """
    try:
        final_prompt = build_prompt(
            user_prompt=user_prompt,
            creative_type=creative_type,
            style=style,
            quality=quality,
        )

        width, height = ASPECT_RATIOS[aspect_ratio]
        steps = QUALITY_TEMPLATES[quality]["steps"]

        result = generator.generate(
            prompt=final_prompt,
            negative_prompt=negative_prompt,
            width=width,
            height=height,
            steps=steps,
            guidance_scale=guidance_scale,
            seed=int(seed),
        )

        caption = (
            f"文生图｜{creative_type}｜{style}｜"
            f"{result['width']}×{result['height']}｜"
            f"Seed {result['seed']}"
        )

        updated_history = add_to_history(
            image_path=result["path"],
            caption=caption,
        )

        gpu_info = build_gpu_markdown(result)

        status = (
            f"✅ 生成成功｜"
            f"耗时 {result['time']} 秒｜"
            f"分辨率 {result['width']}×{result['height']}｜"
            f"Seed {result['seed']}"
        )

        return (
            result["image"],
            result["path"],
            gpu_info,
            final_prompt,
            updated_history,
            status,
            result["seed"],
        )

    except Exception as error:
        traceback.print_exc()

        error_message = (
            f"❌ 生成失败："
            f"{type(error).__name__}: {error}"
        )

        return (
            None,
            None,
            "### AMD GPU 推理信息\n\n本次文生图任务失败。",
            "",
            list(generation_history),
            error_message,
            seed,
        )



def generate_batch_images(
    user_prompt: str,
    creative_type: str,
    style: str,
    aspect_ratio: str,
    quality: str,
    negative_prompt: str,
    guidance_scale: float,
    seed: float,
    batch_size: int,
):
    """
    批量生成候选创意方案。
    """
    try:
        final_prompt = build_prompt(
            user_prompt=user_prompt,
            creative_type=creative_type,
            style=style,
            quality=quality,
        )

        width, height = ASPECT_RATIOS[aspect_ratio]
        steps = QUALITY_TEMPLATES[quality]["steps"]

        result = generator.generate_batch(
            prompt=final_prompt,
            negative_prompt=negative_prompt,
            width=width,
            height=height,
            steps=steps,
            guidance_scale=guidance_scale,
            seed=int(seed),
            batch_size=int(batch_size),
        )

        batch_gallery = []

        for item in result["items"]:
            caption = (
                f"方案 {item['index']}｜"
                f"{creative_type}｜{style}｜"
                f"Seed {item['seed']}"
            )

            batch_gallery.append(
                (
                    item["path"],
                    caption,
                )
            )

            add_to_history(
                image_path=item["path"],
                caption=(
                    f"批量方案 {item['index']}｜"
                    f"{creative_type}｜{style}｜"
                    f"Seed {item['seed']}"
                ),
            )

        gpu_info = (
            "### AMD GPU 批量推理信息\n\n"
            f"- **运行模式：** {result['mode']}\n"
            f"- **GPU：** {result['gpu_name']}\n"
            f"- **显存：** {result['vram_gb']} GB\n"
            "- **运行后端：** PyTorch ROCm\n"
            f"- **生成数量：** {result['batch_size']} 张\n"
            f"- **单张分辨率：** "
            f"{result['width']} × {result['height']}\n"
            f"- **推理步数：** {result['steps']}\n"
            f"- **总推理耗时：** {result['time']} 秒\n"
            f"- **起始 Seed：** {result['base_seed']}"
        )

        status = (
            f"✅ 批量生成成功｜"
            f"共 {result['batch_size']} 张｜"
            f"总耗时 {result['time']} 秒｜"
            f"Seed {result['base_seed']}～"
            f"{result['base_seed'] + result['batch_size'] - 1}"
        )

        return (
            batch_gallery,
            gpu_info,
            final_prompt,
            list(generation_history),
            status,
            result["base_seed"],
        )

    except Exception as error:
        traceback.print_exc()

        error_message = (
            f"❌ 批量生成失败："
            f"{type(error).__name__}: {error}"
        )

        return (
            [],
            "### AMD GPU 批量推理信息\n\n本次批量任务失败。",
            "",
            list(generation_history),
            error_message,
            seed,
        )

# ============================================================
# Image-to-Image：参考图风格重绘
# ============================================================

def transform_image(
    reference_image,
    user_prompt: str,
    creative_type: str,
    style: str,
    aspect_ratio: str,
    quality: str,
    negative_prompt: str,
    guidance_scale: float,
    strength: float,
    seed: float,
):
    """
    图生图事件处理函数。
    """
    try:
        if reference_image is None:
            raise ValueError("请先上传一张参考图片。")

        final_prompt = build_prompt(
            user_prompt=user_prompt,
            creative_type=creative_type,
            style=style,
            quality=quality,
        )

        width, height = ASPECT_RATIOS[aspect_ratio]
        steps = QUALITY_TEMPLATES[quality]["steps"]

        result = generator.transform(
            reference_image=reference_image,
            prompt=final_prompt,
            negative_prompt=negative_prompt,
            width=width,
            height=height,
            steps=steps,
            guidance_scale=guidance_scale,
            strength=strength,
            seed=int(seed),
        )

        caption = (
            f"参考图重绘｜{creative_type}｜{style}｜"
            f"强度 {result['strength']}｜"
            f"Seed {result['seed']}"
        )

        updated_history = add_to_history(
            image_path=result["path"],
            caption=caption,
        )

        gpu_info = build_gpu_markdown(result)

        status = (
            f"✅ 参考图重绘成功｜"
            f"耗时 {result['time']} 秒｜"
            f"重绘强度 {result['strength']}｜"
            f"Seed {result['seed']}"
        )

        return (
            result["image"],
            result["path"],
            gpu_info,
            final_prompt,
            updated_history,
            status,
            result["seed"],
        )

    except Exception as error:
        traceback.print_exc()

        error_message = (
            f"❌ 参考图重绘失败："
            f"{type(error).__name__}: {error}"
        )

        return (
            None,
            None,
            "### AMD GPU 推理信息\n\n本次参考图重绘任务失败。",
            "",
            list(generation_history),
            error_message,
            seed,
        )



def enhance_image(
    source_image,
    brightness: float,
    contrast: float,
    color: float,
    sharpness: float,
    upscale_factor: str,
    auto_contrast: bool,
    detail_enhance: bool,
):
    """
    一键图片增强事件处理函数。
    """
    try:
        if source_image is None:
            raise ValueError("请先上传需要增强的图片。")

        result = enhancer.enhance(
            image=source_image,
            brightness=brightness,
            contrast=contrast,
            color=color,
            sharpness=sharpness,
            upscale_factor=upscale_factor,
            auto_contrast=auto_contrast,
            detail_enhance=detail_enhance,
        )

        caption = (
            f"图片增强｜"
            f"{result['original_width']}×"
            f"{result['original_height']} → "
            f"{result['width']}×"
            f"{result['height']}｜"
            f"{result['scale']}×"
        )

        updated_history = add_to_history(
            image_path=result["path"],
            caption=caption,
        )

        processing_info = (
            "### 图片增强信息\n\n"
            f"- **处理模式：** {result['mode']}\n"
            f"- **原始分辨率：** "
            f"{result['original_width']} × "
            f"{result['original_height']}\n"
            f"- **输出分辨率：** "
            f"{result['width']} × "
            f"{result['height']}\n"
            f"- **放大倍数：** {result['scale']}×\n"
            f"- **亮度系数：** {result['brightness']}\n"
            f"- **对比度系数：** {result['contrast']}\n"
            f"- **色彩系数：** {result['color']}\n"
            f"- **锐度系数：** {result['sharpness']}\n"
            f"- **自动对比度：** "
            f"{'开启' if result['auto_contrast'] else '关闭'}\n"
            f"- **细节增强：** "
            f"{'开启' if result['detail_enhance'] else '关闭'}\n"
            f"- **处理耗时：** {result['time']} 秒\n\n"
            "生成与重绘由 AMD Radeon GPU + ROCm 执行；"
            "此步骤为快速本地图像后处理。"
        )

        status = (
            f"✅ 图片增强成功｜"
            f"{result['original_width']}×"
            f"{result['original_height']} → "
            f"{result['width']}×"
            f"{result['height']}｜"
            f"耗时 {result['time']} 秒"
        )

        return (
            result["original"],
            result["image"],
            result["path"],
            processing_info,
            updated_history,
            status,
        )

    except Exception as error:
        traceback.print_exc()

        error_message = (
            f"❌ 图片增强失败："
            f"{type(error).__name__}: {error}"
        )

        return (
            source_image,
            None,
            None,
            "### 图片增强信息\n\n本次图片增强任务失败。",
            list(generation_history),
            error_message,
        )


# ============================================================
# 页面样式
# ============================================================

CUSTOM_CSS = """
#main-title {
    text-align: center;
    margin-top: 8px;
    margin-bottom: 4px;
}

#main-subtitle {
    text-align: center;
    color: #666666;
    margin-bottom: 18px;
}

.generate-button {
    min-height: 48px;
    font-size: 17px;
    font-weight: 700;
}

.status-box textarea {
    font-weight: 600;
}

.section-card {
    border-radius: 10px;
}
"""


# ============================================================
# Gradio 页面
# ============================================================

with gr.Blocks(
    title="Radeon AI Creative Studio",
    css=CUSTOM_CSS,
) as demo:

    # --------------------------------------------------------
    # 页面标题
    # --------------------------------------------------------

    gr.Markdown(
        """
        # Radeon AI Creative Studio
        """,
        elem_id="main-title",
    )

    gr.Markdown(
        """
        基于 **AMD Radeon GPU + ROCm** 的本地 AI 创意设计工作台  
        支持文字生成图片、参考图风格重绘、商业创意模板和本地隐私推理
        """,
        elem_id="main-subtitle",
    )

    # --------------------------------------------------------
    # 标签页区域
    # --------------------------------------------------------

    with gr.Tabs():

        # ====================================================
        # 标签页 1：文字生成图片
        # ====================================================

        with gr.Tab("文字生成图片"):

            with gr.Row():

                # ------------------------------
                # 文生图左侧参数区域
                # ------------------------------

                with gr.Column(scale=5):

                    gr.Markdown("## 1. 创作设置")

                    text_creative_type = gr.Dropdown(
                        choices=list(CREATIVE_TYPES.keys()),
                        value="室内设计",
                        label="创作类型",
                    )

                    text_style = gr.Dropdown(
                        choices=list(STYLE_TEMPLATES.keys()),
                        value="写实摄影",
                        label="视觉风格",
                    )

                    text_user_prompt = gr.Textbox(
                        label="画面描述",
                        placeholder=(
                            "例如：一个阳光充足的现代法式客厅，"
                            "落地窗、米色沙发和精致吊灯"
                        ),
                        value=(
                            "一个阳光充足的现代法式客厅，"
                            "落地窗、米色沙发和精致吊灯"
                        ),
                        lines=4,
                    )

                    with gr.Row():

                        text_aspect_ratio = gr.Dropdown(
                            choices=list(ASPECT_RATIOS.keys()),
                            value="1:1 正方形",
                            label="画幅比例",
                        )

                        text_quality = gr.Radio(
                            choices=list(QUALITY_TEMPLATES.keys()),
                            value="均衡",
                            label="生成质量",
                        )

                    with gr.Accordion(
                        "高级参数",
                        open=False,
                    ):

                        text_guidance_scale = gr.Slider(
                            minimum=1.0,
                            maximum=15.0,
                            value=7.5,
                            step=0.5,
                            label="Prompt 引导强度",
                        )

                        text_seed = gr.Number(
                            value=-1,
                            precision=0,
                            label="随机种子（-1 表示随机）",
                        )

                        text_negative_prompt = gr.Textbox(
                            value=DEFAULT_NEGATIVE_PROMPT,
                            label="负面提示词",
                            lines=3,
                        )

                    text_final_prompt_preview = gr.Textbox(
                        label="系统生成的完整 Prompt",
                        lines=5,
                        interactive=False,
                    )

                    text_generate_button = gr.Button(
                        "生成创意图片",
                        variant="primary",
                        elem_classes=["generate-button"],
                    )

                    text_status = gr.Textbox(
                        label="运行状态",
                        interactive=False,
                        elem_classes=["status-box"],
                    )

                # ------------------------------
                # 文生图右侧结果区域
                # ------------------------------

                with gr.Column(scale=7):

                    gr.Markdown("## 2. 生成结果")

                    text_output_image = gr.Image(
                        label="生成图片",
                        type="pil",
                        height=560,
                        format="png",
                    )

                    text_download_file = gr.DownloadButton(
                        label="下载原始 PNG 文件",
                        value=None,
                        variant="secondary",
                    )

                    text_gpu_info = gr.Markdown(
                        """
                        ### AMD GPU 推理信息

                        等待文字生成图片任务。
                        """
                    )

        # ====================================================
        # 标签页 2：参考图风格重绘
        # ====================================================

        with gr.Tab("参考图风格重绘"):

            with gr.Row():

                # ------------------------------
                # 图生图左侧参数区域
                # ------------------------------

                with gr.Column(scale=5):

                    gr.Markdown("## 1. 上传参考图并设置目标效果")

                    reference_image = gr.Image(
                        label="参考图片",
                        type="pil",
                        height=360,
                    )

                    img_creative_type = gr.Dropdown(
                        choices=list(CREATIVE_TYPES.keys()),
                        value="室内设计",
                        label="创作类型",
                    )

                    img_style = gr.Dropdown(
                        choices=list(STYLE_TEMPLATES.keys()),
                        value="法式奢华",
                        label="目标视觉风格",
                    )

                    img_user_prompt = gr.Textbox(
                        label="重绘要求",
                        value=(
                            "保留原图主要结构，升级材质和灯光，"
                            "呈现高端专业设计效果"
                        ),
                        placeholder=(
                            "例如：保留客厅布局，将整体改成法式奢华风格，"
                            "增加水晶吊灯和温暖阳光"
                        ),
                        lines=4,
                    )

                    with gr.Row():

                        img_aspect_ratio = gr.Dropdown(
                            choices=list(ASPECT_RATIOS.keys()),
                            value="1:1 正方形",
                            label="输出画幅",
                        )

                        img_quality = gr.Radio(
                            choices=list(QUALITY_TEMPLATES.keys()),
                            value="均衡",
                            label="生成质量",
                        )

                    img_strength = gr.Slider(
                        minimum=0.15,
                        maximum=0.95,
                        value=0.55,
                        step=0.05,
                        label="重绘强度",
                        info=(
                            "数值越低越保留原图，"
                            "数值越高变化越明显"
                        ),
                    )

                    with gr.Accordion(
                        "高级参数",
                        open=False,
                    ):

                        img_guidance_scale = gr.Slider(
                            minimum=1.0,
                            maximum=15.0,
                            value=7.5,
                            step=0.5,
                            label="Prompt 引导强度",
                        )

                        img_seed = gr.Number(
                            value=-1,
                            precision=0,
                            label="随机种子（-1 表示随机）",
                        )

                        img_negative_prompt = gr.Textbox(
                            value=DEFAULT_NEGATIVE_PROMPT,
                            label="负面提示词",
                            lines=3,
                        )

                    img_final_prompt_preview = gr.Textbox(
                        label="系统生成的完整 Prompt",
                        lines=5,
                        interactive=False,
                    )

                    img_transform_button = gr.Button(
                        "开始参考图重绘",
                        variant="primary",
                        elem_classes=["generate-button"],
                    )

                    img_status = gr.Textbox(
                        label="运行状态",
                        interactive=False,
                        elem_classes=["status-box"],
                    )

                # ------------------------------
                # 图生图右侧结果区域
                # ------------------------------

                with gr.Column(scale=7):

                    gr.Markdown("## 2. 重绘结果")

                    img_output_image = gr.Image(
                        label="重绘后的图片",
                        type="pil",
                        height=560,
                        format="png",
                    )

                    img_download_file = gr.DownloadButton(
                        label="下载重绘结果 PNG",
                        value=None,
                        variant="secondary",
                    )

                    img_gpu_info = gr.Markdown(
                        """
                        ### AMD GPU 推理信息

                        等待参考图重绘任务。
                        """
                    )


        # ====================================================
        # 标签页 3：图片增强
        # ====================================================

        with gr.Tab("一键图片增强"):

            with gr.Row():

                with gr.Column(scale=5):

                    gr.Markdown("## 1. 上传需要增强的图片")

                    enhance_source_image = gr.Image(
                        label="原始图片",
                        type="pil",
                        height=380,
                    )

                    gr.Markdown("## 2. 增强参数")

                    enhance_upscale = gr.Radio(
                        choices=[
                            "1×",
                            "2×",
                            "4×",
                        ],
                        value="2×",
                        label="输出放大倍数",
                    )

                    enhance_auto_contrast = gr.Checkbox(
                        value=True,
                        label="自动优化对比度",
                    )

                    enhance_detail = gr.Checkbox(
                        value=True,
                        label="启用细节增强",
                    )

                    with gr.Accordion(
                        "高级增强参数",
                        open=False,
                    ):

                        enhance_brightness = gr.Slider(
                            minimum=0.5,
                            maximum=1.5,
                            value=1.0,
                            step=0.05,
                            label="亮度",
                        )

                        enhance_contrast = gr.Slider(
                            minimum=0.5,
                            maximum=1.8,
                            value=1.08,
                            step=0.05,
                            label="对比度",
                        )

                        enhance_color = gr.Slider(
                            minimum=0.0,
                            maximum=2.0,
                            value=1.05,
                            step=0.05,
                            label="色彩饱和度",
                        )

                        enhance_sharpness = gr.Slider(
                            minimum=0.5,
                            maximum=2.5,
                            value=1.25,
                            step=0.05,
                            label="锐度",
                        )

                    enhance_button = gr.Button(
                        "开始一键增强",
                        variant="primary",
                        elem_classes=["generate-button"],
                    )

                    enhance_status = gr.Textbox(
                        label="运行状态",
                        interactive=False,
                        elem_classes=["status-box"],
                    )

                with gr.Column(scale=7):

                    gr.Markdown("## 3. 增强前后对比")

                    with gr.Row():

                        enhance_original_output = gr.Image(
                            label="增强前",
                            type="pil",
                            height=390,
                        )

                        enhance_result_output = gr.Image(
                            label="增强后",
                            type="pil",
                            height=390,
                            format="png",
                        )

                    enhance_download_file = gr.DownloadButton(
                        label="下载增强后的 PNG",
                        value=None,
                        variant="secondary",
                    )

                    enhance_processing_info = gr.Markdown(
                        """
                        ### 图片增强信息

                        等待图片增强任务。
                        """
                    )

        # ====================================================
        # 标签页 4：批量生成候选方案
        # ====================================================
        with gr.Tab("批量候选方案"):

            with gr.Row():

                with gr.Column(scale=5):

                    gr.Markdown("## 1. 批量创作设置")

                    batch_creative_type = gr.Dropdown(
                        choices=list(CREATIVE_TYPES.keys()),
                        value="电商海报",
                        label="创作类型",
                    )

                    batch_style = gr.Dropdown(
                        choices=list(STYLE_TEMPLATES.keys()),
                        value="现代简约",
                        label="视觉风格",
                    )

                    batch_user_prompt = gr.Textbox(
                        label="画面描述",
                        value=(
                            "一瓶高端香水放在白色大理石台面上，"
                            "旁边有白色花朵和柔和光影"
                        ),
                        lines=4,
                    )

                    with gr.Row():

                        batch_aspect_ratio = gr.Dropdown(
                            choices=list(ASPECT_RATIOS.keys()),
                            value="1:1 正方形",
                            label="画幅比例",
                        )

                        batch_quality = gr.Radio(
                            choices=list(
                                QUALITY_TEMPLATES.keys()
                            ),
                            value="快速",
                            label="生成质量",
                        )

                    batch_count = gr.Radio(
                        choices=[2, 3, 4],
                        value=4,
                        label="候选方案数量",
                    )

                    with gr.Accordion(
                        "高级参数",
                        open=False,
                    ):

                        batch_guidance_scale = gr.Slider(
                            minimum=1.0,
                            maximum=15.0,
                            value=7.5,
                            step=0.5,
                            label="Prompt 引导强度",
                        )

                        batch_seed = gr.Number(
                            value=-1,
                            precision=0,
                            label="起始 Seed（-1 表示随机）",
                        )

                        batch_negative_prompt = gr.Textbox(
                            value=DEFAULT_NEGATIVE_PROMPT,
                            label="负面提示词",
                            lines=3,
                        )

                    batch_prompt_preview = gr.Textbox(
                        label="系统生成的完整 Prompt",
                        lines=5,
                        interactive=False,
                    )

                    batch_generate_button = gr.Button(
                        "批量生成候选方案",
                        variant="primary",
                        elem_classes=["generate-button"],
                    )

                    batch_status = gr.Textbox(
                        label="运行状态",
                        interactive=False,
                        elem_classes=["status-box"],
                    )

                with gr.Column(scale=7):

                    gr.Markdown("## 2. 候选方案对比")

                    batch_result_gallery = gr.Gallery(
                        label="批量生成结果",
                        columns=2,
                        rows=2,
                        height=650,
                    )

                    batch_gpu_info = gr.Markdown(
                        """
                        ### AMD GPU 批量推理信息

                        等待批量生成任务。
                        """
                    ) 

    # --------------------------------------------------------
    # 公共历史画廊
    # 该画廊位于 Tabs 外部，因此两个功能共用
    # --------------------------------------------------------

        with gr.Row():
            gr.Markdown("## 历史作品")
        
            refresh_history_button = gr.Button(
                "刷新历史",
                size="sm",
            )

    history_gallery = gr.Gallery(
        value=generation_history,
        label="历史图片",
        columns=4,
        rows=2,
        height=420,
    )
    
    # ========================================================
    # Prompt 预览事件：文字生成图片
    # ========================================================

    for component in [
        text_user_prompt,
        text_creative_type,
        text_style,
        text_quality,
    ]:
        component.change(
            fn=preview_final_prompt,
            inputs=[
                text_user_prompt,
                text_creative_type,
                text_style,
                text_quality,
            ],
            outputs=text_final_prompt_preview,
        )

    # ========================================================
    # Prompt 预览事件：参考图重绘
    # ========================================================

    for component in [
        img_user_prompt,
        img_creative_type,
        img_style,
        img_quality,
    ]:
        component.change(
            fn=preview_final_prompt,
            inputs=[
                img_user_prompt,
                img_creative_type,
                img_style,
                img_quality,
            ],
            outputs=img_final_prompt_preview,
        )

    # ========================================================
    # Prompt 预览事件：批量生成
    # ========================================================

    for component in [
        batch_user_prompt,
        batch_creative_type,
        batch_style,
        batch_quality,
    ]:
        component.change(
            fn=preview_final_prompt,
            inputs=[
                batch_user_prompt,
                batch_creative_type,
                batch_style,
                batch_quality,
            ],
            outputs=batch_prompt_preview,
        )
    
    # ========================================================
    # 文生图按钮事件
    # ========================================================

    text_generate_button.click(
        fn=generate_image,
        inputs=[
            text_user_prompt,
            text_creative_type,
            text_style,
            text_aspect_ratio,
            text_quality,
            text_negative_prompt,
            text_guidance_scale,
            text_seed,
        ],
        outputs=[
            text_output_image,
            text_download_file,
            text_gpu_info,
            text_final_prompt_preview,
            history_gallery,
            text_status,
            text_seed,
        ],
    )

    # ========================================================
    # 图生图按钮事件
    # ========================================================

    img_transform_button.click(
        fn=transform_image,
        inputs=[
            reference_image,
            img_user_prompt,
            img_creative_type,
            img_style,
            img_aspect_ratio,
            img_quality,
            img_negative_prompt,
            img_guidance_scale,
            img_strength,
            img_seed,
        ],
        outputs=[
            img_output_image,
            img_download_file,
            img_gpu_info,
            img_final_prompt_preview,
            history_gallery,
            img_status,
            img_seed,
        ],
    )

    # ========================================================
    # 图片增强按钮事件
    # ========================================================

    enhance_button.click(
        fn=enhance_image,
        inputs=[
            enhance_source_image,
            enhance_brightness,
            enhance_contrast,
            enhance_color,
            enhance_sharpness,
            enhance_upscale,
            enhance_auto_contrast,
            enhance_detail,
        ],
        outputs=[
            enhance_original_output,
            enhance_result_output,
            enhance_download_file,
            enhance_processing_info,
            history_gallery,
            enhance_status,
        ],
    )

    # ========================================================
    # 批量生成按钮事件
    # ========================================================

    batch_generate_button.click(
        fn=generate_batch_images,
        inputs=[
            batch_user_prompt,
            batch_creative_type,
            batch_style,
            batch_aspect_ratio,
            batch_quality,
            batch_negative_prompt,
            batch_guidance_scale,
            batch_seed,
            batch_count,
        ],
        outputs=[
            batch_result_gallery,
            batch_gpu_info,
            batch_prompt_preview,
            history_gallery,
            batch_status,
            batch_seed,
        ],
    )
    

    refresh_history_button.click(
        fn=refresh_history_gallery,
        inputs=None,
        outputs=history_gallery,
        queue=False,
    )

    # ========================================================
    # 页面首次打开时初始化 Prompt 预览
    # ========================================================

    demo.load(
        fn=preview_final_prompt,
        inputs=[
            text_user_prompt,
            text_creative_type,
            text_style,
            text_quality,
        ],
        outputs=text_final_prompt_preview,
    )

    demo.load(
        fn=preview_final_prompt,
        inputs=[
            img_user_prompt,
            img_creative_type,
            img_style,
            img_quality,
        ],
        outputs=img_final_prompt_preview,
    )

    demo.load(
        fn=refresh_history_gallery,
        inputs=None,
        outputs=history_gallery,
    )

    demo.load(
        fn=preview_final_prompt,
        inputs=[
            batch_user_prompt,
            batch_creative_type,
            batch_style,
            batch_quality,
        ],
        outputs=batch_prompt_preview,
    )


# ============================================================
# 应用启动
# ============================================================

if __name__ == "__main__":
    demo.queue(
        default_concurrency_limit=1,
    ).launch(
        server_name="0.0.0.0",
        server_port=7860,
        show_error=True,
    )
