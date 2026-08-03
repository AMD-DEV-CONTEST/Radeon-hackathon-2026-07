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
# Initialize models
# ============================================================

generator = ImageGenerator()
enhancer = ImageEnhancer()


# Generation history for the current application session.
# Each item contains:
# (
#     image file path,
#     image caption
# )
OUTPUT_HISTORY_LIMIT = 40


def refresh_history_gallery():
    """
    Rescan the outputs directory whenever the page loads.
    """
    global generation_history

    generation_history = load_generation_history()

    return list(generation_history)

def build_history_caption(image_path: Path) -> str:
    """
    Build a gallery caption from the output filename.
    """
    filename = image_path.stem

    if "text2img" in filename:
        mode = "Text-to-Image"
    elif "img2img" in filename:
        mode = "Image-to-Image"
    elif "enhanced" in filename:
        mode = "Image Enhancement"
    else:
        mode = "History"

    modified_time = image_path.stat().st_mtime

    from datetime import datetime

    time_text = datetime.fromtimestamp(
        modified_time
    ).strftime("%Y-%m-%d %H:%M:%S")

    return f"{mode}｜{time_text}"


def load_generation_history() -> list[tuple[str, str]]:
    """
    Load previous images from the outputs directory.

    Sort by modification time so the newest image appears first.
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
# Shared utility functions
# ============================================================

def preview_final_prompt(
    user_prompt: str,
    creative_type: str,
    style: str,
    quality: str,
) -> str:
    """
    Build the final prompt from the user input, creative type, style, and quality.
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
    Add a new result to the history gallery and keep the latest 40 items.
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
    Build the AMD GPU inference information panel.
    """
    lines = [
        "### AMD GPU Inference Information",
        "",
        f"- **Mode:** {result.get('mode', 'Unknown')}",
        f"- **GPU:** {result.get('gpu_name', 'Unknown')}",
        f"- **VRAM:** {result.get('vram_gb', 'Unknown')} GB",
        "- **Backend:** PyTorch ROCm",
        f"- **Resolution:** "
        f"{result.get('width', 'Unknown')} × "
        f"{result.get('height', 'Unknown')}",
        f"- **Inference steps:** {result.get('steps', 'Unknown')}",
    ]

    if "strength" in result:
        lines.append(
            f"- **Strength:** {result['strength']}"
        )

    lines.extend(
        [
            f"- **Inference time:** {result.get('time', 'Unknown')} s",
            f"- **Seed:** {result.get('seed', 'Unknown')}",
        ]
    )

    return "\n".join(lines)


# ============================================================
# Text-to-Image
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
    Handle text-to-image generation.
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
            f"Text-to-Image | {creative_type} | {style} | "
            f"{result['width']}×{result['height']}｜"
            f"Seed {result['seed']}"
        )

        updated_history = add_to_history(
            image_path=result["path"],
            caption=caption,
        )

        gpu_info = build_gpu_markdown(result)

        status = (
            f"✅ Generation succeeded | "
            f"Time {result['time']} s | "
            f"Resolution {result['width']}×{result['height']} | "
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
            f"❌ Generation failed: "
            f"{type(error).__name__}: {error}"
        )

        return (
            None,
            None,
            "### AMD GPU Inference Information\n\nThe text-to-image task failed.",
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
    Generate multiple creative candidates.
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
                f"Candidate {item['index']} | "
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
                    f"Batch candidate {item['index']} | "
                    f"{creative_type}｜{style}｜"
                    f"Seed {item['seed']}"
                ),
            )

        gpu_info = (
            "### AMD GPU Batch Inference Information\n\n"
            f"- **Mode:** {result['mode']}\n"
            f"- **GPU:** {result['gpu_name']}\n"
            f"- **VRAM:** {result['vram_gb']} GB\n"
            "- **Backend:** PyTorch ROCm\n"
            f"- **Images generated:** {result['batch_size']}\n"
            f"- **Per-image resolution:** "
            f"{result['width']} × {result['height']}\n"
            f"- **Inference steps:** {result['steps']}\n"
            f"- **Total inference time:** {result['time']} s\n"
            f"- **Base seed:** {result['base_seed']}"
        )

        status = (
            f"✅ Batch generation succeeded | "
            f"{result['batch_size']} images | "
            f"Total time {result['time']} s | "
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
            f"❌ Batch generation failed: "
            f"{type(error).__name__}: {error}"
        )

        return (
            [],
            "### AMD GPU Batch Inference Information\n\nThe batch task failed.",
            "",
            list(generation_history),
            error_message,
            seed,
        )

# ============================================================
# Image-to-Image
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
    Handle image-to-image generation.
    """
    try:
        if reference_image is None:
            raise ValueError("Please upload a reference image first.")

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
            f"Image-to-Image | {creative_type} | {style} | "
            f"Strength {result['strength']} | "
            f"Seed {result['seed']}"
        )

        updated_history = add_to_history(
            image_path=result["path"],
            caption=caption,
        )

        gpu_info = build_gpu_markdown(result)

        status = (
            f"✅ Image-to-image succeeded | "
            f"Time {result['time']} s | "
            f"Strength {result['strength']} | "
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
            f"❌ Image-to-image failed: "
            f"{type(error).__name__}: {error}"
        )

        return (
            None,
            None,
            "### AMD GPU Inference Information\n\nThe image-to-image task failed.",
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
    Handle deterministic image enhancement.
    """
    try:
        if source_image is None:
            raise ValueError("Please upload an image to enhance first.")

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
            f"Image Enhancement | "
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
            "### Image Enhancement Information\n\n"
            f"- **Mode:** {result['mode']}\n"
            f"- **Original resolution:** "
            f"{result['original_width']} × "
            f"{result['original_height']}\n"
            f"- **Output resolution:** "
            f"{result['width']} × "
            f"{result['height']}\n"
            f"- **Upscale factor:** {result['scale']}×\n"
            f"- **Brightness:** {result['brightness']}\n"
            f"- **Contrast:** {result['contrast']}\n"
            f"- **Color:** {result['color']}\n"
            f"- **Sharpness:** {result['sharpness']}\n"
            f"- **Auto contrast:** "
            f"{'Enabled' if result['auto_contrast'] else 'Disabled'}\n"
            f"- **Detail enhancement:** "
            f"{'Enabled' if result['detail_enhance'] else 'Disabled'}\n"
            f"- **Processing time:** {result['time']} s\n\n"
            "Text-to-image and image-to-image use AMD Radeon GPU + ROCm; "
            "this step is fast local CPU post-processing."
        )

        status = (
            f"✅ Image enhancement succeeded | "
            f"{result['original_width']}×"
            f"{result['original_height']} → "
            f"{result['width']}×"
            f"{result['height']}｜"
            f"Time {result['time']} s"
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
            f"❌ Image enhancement failed: "
            f"{type(error).__name__}: {error}"
        )

        return (
            source_image,
            None,
            None,
            "### Image Enhancement Information\n\nThe image enhancement task failed.",
            list(generation_history),
            error_message,
        )


# ============================================================
# Page styling
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

/* Keep the public demo surface focused on the application itself. */
footer,
.gradio-container footer {
    display: none !important;
}
"""


UI_JAVASCRIPT = """
() => {
    document.documentElement.lang = "en";
    document.body.lang = "en";

    const replacements = {
        "\u5c06\u56fe\u50cf\u62d6\u653e\u5230\u6b64\u5904": "Drop an image here",
        "\u6216": "or",
        "\u70b9\u51fb\u4e0a\u4f20": "Click to upload",
        "\u4e0a\u4f20\u6587\u4ef6": "Upload file",
        "\u4ece\u6444\u50cf\u5934\u6355\u83b7": "Capture from camera",
        "\u4ece\u526a\u8d34\u677f\u7c98\u8d34": "Paste from clipboard",
    };

    const translateUploadText = () => {
        document.querySelectorAll("body *").forEach((element) => {
            if (element.childElementCount !== 0) {
                return;
            }

            const text = element.textContent.trim();
            if (replacements[text]) {
                element.textContent = replacements[text];
            }
        });
    };

    translateUploadText();
    new MutationObserver(translateUploadText).observe(document.body, {
        childList: true,
        subtree: true,
    });
}
"""


# ============================================================
# Gradio interface
# ============================================================

with gr.Blocks(
    title="Radeon AI Creative Studio",
    css=CUSTOM_CSS,
    js=UI_JAVASCRIPT,
) as demo:

    # --------------------------------------------------------
    # Page title
    # --------------------------------------------------------

    gr.Markdown(
        """
        # Radeon AI Creative Studio
        """,
        elem_id="main-title",
    )

    gr.Markdown(
        """
        Local AI creative workstation powered by **AMD Radeon GPU + ROCm**
        Supports text-to-image, image-to-image, batch ideation, and private local inference
        """,
        elem_id="main-subtitle",
    )

    # --------------------------------------------------------
    # Main tabs
    # --------------------------------------------------------

    with gr.Tabs():

        # ====================================================
        # Tab 1: Text-to-Image
        # ====================================================

        with gr.Tab("Text-to-Image"):

            with gr.Row():

                # ------------------------------
                # Text-to-image settings
                # ------------------------------

                with gr.Column(scale=5):

                    gr.Markdown("## 1. Creation Settings")

                    text_creative_type = gr.Dropdown(
                        choices=list(CREATIVE_TYPES.keys()),
                        value="Interior Design",
                        label="Creative Type",
                    )

                    text_style = gr.Dropdown(
                        choices=list(STYLE_TEMPLATES.keys()),
                        value="Photorealistic",
                        label="Visual Style",
                    )

                    text_user_prompt = gr.Textbox(
                        label="Scene Description",
                        placeholder=(
                            "For example: a sunlit modern French living room, "
                            "floor-to-ceiling windows, a beige sofa, and elegant pendant lights"
                        ),
                        value=(
                            "A sunlit modern French living room, floor-to-ceiling windows, "
                            "a beige sofa, and elegant pendant lights"
                        ),
                        lines=4,
                    )

                    with gr.Row():

                        text_aspect_ratio = gr.Dropdown(
                            choices=list(ASPECT_RATIOS.keys()),
                            value="1:1 Square",
                            label="Aspect Ratio",
                        )

                        text_quality = gr.Radio(
                            choices=list(QUALITY_TEMPLATES.keys()),
                            value="Balanced",
                            label="Generation Quality",
                        )

                    with gr.Accordion(
                        "Advanced Parameters",
                        open=False,
                    ):

                        text_guidance_scale = gr.Slider(
                            minimum=1.0,
                            maximum=15.0,
                            value=7.5,
                            step=0.5,
                            label="Prompt Guidance Scale",
                        )

                        text_seed = gr.Number(
                            value=-1,
                            precision=0,
                            label="Seed (-1 for random)",
                        )

                        text_negative_prompt = gr.Textbox(
                            value=DEFAULT_NEGATIVE_PROMPT,
                            label="Negative Prompt",
                            lines=3,
                        )

                    text_final_prompt_preview = gr.Textbox(
                        label="Final Generated Prompt",
                        lines=5,
                        interactive=False,
                    )

                    text_generate_button = gr.Button(
                        "Generate Creative Image",
                        variant="primary",
                        elem_classes=["generate-button"],
                    )

                    text_status = gr.Textbox(
                        label="Status",
                        interactive=False,
                        elem_classes=["status-box"],
                    )

                # ------------------------------
                # Text-to-image results
                # ------------------------------

                with gr.Column(scale=7):

                    gr.Markdown("## 2. Generation Result")

                    text_output_image = gr.Image(
                        label="Generated Image",
                        type="pil",
                        height=560,
                        format="png",
                    )

                    text_download_file = gr.DownloadButton(
                        label="Download Original PNG",
                        value=None,
                        variant="secondary",
                    )

                    text_gpu_info = gr.Markdown(
                        """
                        ### AMD GPU Inference Information

                        Waiting for a text-to-image task.
                        """
                    )

        # ====================================================
        # Tab 2: Image-to-Image
        # ====================================================

        with gr.Tab("Image-to-Image"):

            with gr.Row():

                # ------------------------------
                # Image-to-image settings
                # ------------------------------

                with gr.Column(scale=5):

                    gr.Markdown("## 1. Upload a Reference and Set the Target")

                    reference_image = gr.Image(
                        label="Reference Image",
                        type="pil",
                        height=360,
                    )

                    img_creative_type = gr.Dropdown(
                        choices=list(CREATIVE_TYPES.keys()),
                        value="Interior Design",
                        label="Creative Type",
                    )

                    img_style = gr.Dropdown(
                        choices=list(STYLE_TEMPLATES.keys()),
                        value="Luxury French",
                        label="Target Visual Style",
                    )

                    img_user_prompt = gr.Textbox(
                        label="Transformation Instruction",
                        value=(
                            "Preserve the main structure, upgrade materials and lighting, "
                            "and create a premium professional design"
                        ),
                        placeholder=(
                            "For example: preserve the living room layout, apply a luxury French style, "
                            "and add a crystal chandelier with warm sunlight"
                        ),
                        lines=4,
                    )

                    with gr.Row():

                        img_aspect_ratio = gr.Dropdown(
                            choices=list(ASPECT_RATIOS.keys()),
                            value="1:1 Square",
                            label="Output Aspect Ratio",
                        )

                        img_quality = gr.Radio(
                            choices=list(QUALITY_TEMPLATES.keys()),
                            value="Balanced",
                            label="Generation Quality",
                        )

                    img_strength = gr.Slider(
                        minimum=0.15,
                        maximum=0.95,
                        value=0.55,
                        step=0.05,
                        label="Transformation Strength",
                        info=(
                            "Lower values preserve more of the reference; "
                            "higher values create stronger changes"
                        ),
                    )

                    with gr.Accordion(
                        "Advanced Parameters",
                        open=False,
                    ):

                        img_guidance_scale = gr.Slider(
                            minimum=1.0,
                            maximum=15.0,
                            value=7.5,
                            step=0.5,
                            label="Prompt Guidance Scale",
                        )

                        img_seed = gr.Number(
                            value=-1,
                            precision=0,
                            label="Seed (-1 for random)",
                        )

                        img_negative_prompt = gr.Textbox(
                            value=DEFAULT_NEGATIVE_PROMPT,
                            label="Negative Prompt",
                            lines=3,
                        )

                    img_final_prompt_preview = gr.Textbox(
                        label="Final Generated Prompt",
                        lines=5,
                        interactive=False,
                    )

                    img_transform_button = gr.Button(
                        "Generate Image-to-Image Variation",
                        variant="primary",
                        elem_classes=["generate-button"],
                    )

                    img_status = gr.Textbox(
                        label="Status",
                        interactive=False,
                        elem_classes=["status-box"],
                    )

                # ------------------------------
                # Image-to-image results
                # ------------------------------

                with gr.Column(scale=7):

                    gr.Markdown("## 2. Transformation Result")

                    img_output_image = gr.Image(
                        label="Transformed Image",
                        type="pil",
                        height=560,
                        format="png",
                    )

                    img_download_file = gr.DownloadButton(
                        label="Download Transformed PNG",
                        value=None,
                        variant="secondary",
                    )

                    img_gpu_info = gr.Markdown(
                        """
                        ### AMD GPU Inference Information

                        Waiting for an image-to-image task.
                        """
                    )


        # ====================================================
        # Tab 3: Image Enhancement
        # ====================================================

        with gr.Tab("Image Enhancement"):

            with gr.Row():

                with gr.Column(scale=5):

                    gr.Markdown("## 1. Upload an Image to Enhance")

                    enhance_source_image = gr.Image(
                        label="Original Image",
                        type="pil",
                        height=380,
                    )

                    gr.Markdown("## 2. Enhancement Parameters")

                    enhance_upscale = gr.Radio(
                        choices=[
                            "1×",
                            "2×",
                            "4×",
                        ],
                        value="2×",
                        label="Output Upscale Factor",
                    )

                    enhance_auto_contrast = gr.Checkbox(
                        value=True,
                        label="Auto Contrast",
                    )

                    enhance_detail = gr.Checkbox(
                        value=True,
                        label="Enable Detail Enhancement",
                    )

                    with gr.Accordion(
                        "Advanced Enhancement Parameters",
                        open=False,
                    ):

                        enhance_brightness = gr.Slider(
                            minimum=0.5,
                            maximum=1.5,
                            value=1.0,
                            step=0.05,
                            label="Brightness",
                        )

                        enhance_contrast = gr.Slider(
                            minimum=0.5,
                            maximum=1.8,
                            value=1.08,
                            step=0.05,
                            label="Contrast",
                        )

                        enhance_color = gr.Slider(
                            minimum=0.0,
                            maximum=2.0,
                            value=1.05,
                            step=0.05,
                            label="Color Saturation",
                        )

                        enhance_sharpness = gr.Slider(
                            minimum=0.5,
                            maximum=2.5,
                            value=1.25,
                            step=0.05,
                            label="Sharpness",
                        )

                    enhance_button = gr.Button(
                        "Enhance Image",
                        variant="primary",
                        elem_classes=["generate-button"],
                    )

                    enhance_status = gr.Textbox(
                        label="Status",
                        interactive=False,
                        elem_classes=["status-box"],
                    )

                with gr.Column(scale=7):

                    gr.Markdown("## 3. Before and After")

                    with gr.Row():

                        enhance_original_output = gr.Image(
                            label="Before Enhancement",
                            type="pil",
                            height=390,
                        )

                        enhance_result_output = gr.Image(
                            label="After Enhancement",
                            type="pil",
                            height=390,
                            format="png",
                        )

                    enhance_download_file = gr.DownloadButton(
                        label="Download Enhanced PNG",
                        value=None,
                        variant="secondary",
                    )

                    enhance_processing_info = gr.Markdown(
                        """
                        ### Image Enhancement Information

                        Waiting for an image enhancement task.
                        """
                    )

        # ====================================================
        # Tab 4: Batch Candidates
        # ====================================================
        with gr.Tab("Batch Candidates"):

            with gr.Row():

                with gr.Column(scale=5):

                    gr.Markdown("## 1. Batch Creation Settings")

                    batch_creative_type = gr.Dropdown(
                        choices=list(CREATIVE_TYPES.keys()),
                        value="Commercial Poster",
                        label="Creative Type",
                    )

                    batch_style = gr.Dropdown(
                        choices=list(STYLE_TEMPLATES.keys()),
                        value="Modern Minimalist",
                        label="Visual Style",
                    )

                    batch_user_prompt = gr.Textbox(
                        label="Scene Description",
                        value=(
                            "A premium perfume bottle on a white marble table, "
                            "with white flowers and soft studio lighting nearby"
                        ),
                        lines=4,
                    )

                    with gr.Row():

                        batch_aspect_ratio = gr.Dropdown(
                            choices=list(ASPECT_RATIOS.keys()),
                            value="1:1 Square",
                            label="Aspect Ratio",
                        )

                        batch_quality = gr.Radio(
                            choices=list(
                                QUALITY_TEMPLATES.keys()
                            ),
                            value="Fast",
                            label="Generation Quality",
                        )

                    batch_count = gr.Radio(
                        choices=[2, 3, 4],
                        value=4,
                        label="Number of Candidates",
                    )

                    with gr.Accordion(
                        "Advanced Parameters",
                        open=False,
                    ):

                        batch_guidance_scale = gr.Slider(
                            minimum=1.0,
                            maximum=15.0,
                            value=7.5,
                            step=0.5,
                            label="Prompt Guidance Scale",
                        )

                        batch_seed = gr.Number(
                            value=-1,
                            precision=0,
                            label="Base Seed (-1 for random)",
                        )

                        batch_negative_prompt = gr.Textbox(
                            value=DEFAULT_NEGATIVE_PROMPT,
                            label="Negative Prompt",
                            lines=3,
                        )

                    batch_prompt_preview = gr.Textbox(
                        label="Final Generated Prompt",
                        lines=5,
                        interactive=False,
                    )

                    batch_generate_button = gr.Button(
                        "Generate Batch Candidates",
                        variant="primary",
                        elem_classes=["generate-button"],
                    )

                    batch_status = gr.Textbox(
                        label="Status",
                        interactive=False,
                        elem_classes=["status-box"],
                    )

                with gr.Column(scale=7):

                    gr.Markdown("## 2. Compare Candidates")

                    batch_result_gallery = gr.Gallery(
                        label="Batch Generation Results",
                        columns=2,
                        rows=2,
                        height=650,
                    )

                    batch_gpu_info = gr.Markdown(
                        """
                        ### AMD GPU Batch Inference Information

                        Waiting for a batch generation task.
                        """
                    ) 

    # --------------------------------------------------------
    # Shared history gallery outside the tabs.
    # --------------------------------------------------------

        with gr.Row():
            gr.Markdown("## Generation History")
        
            refresh_history_button = gr.Button(
                "Refresh History",
                size="sm",
            )

    history_gallery = gr.Gallery(
        value=generation_history,
        label="History Images",
        columns=4,
        rows=2,
        height=420,
    )
    
    # ========================================================
    # Prompt preview: text-to-image
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
    # Prompt preview: image-to-image
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
    # Prompt preview: batch generation
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
    # Text-to-image button event
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
    # Image-to-image button event
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
    # Image enhancement button event
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
    # Batch generation button event
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
    # Initialize prompt previews on first page load
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
# Application startup
# ============================================================

if __name__ == "__main__":
    demo.queue(
        default_concurrency_limit=1,
    ).launch(
        server_name="0.0.0.0",
        server_port=7860,
        show_error=True,
    )
