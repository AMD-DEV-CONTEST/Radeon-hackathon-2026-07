"""端到端生成编排：LLM 出文 -> ComfyUI 出图(可降级) -> image_pipeline 后处理。"""
from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from PIL import Image

from content_studio.config import AppConfig
from content_studio.core import image_pipeline
from content_studio.core.comfy import ComfyClient, ComfyError
from content_studio.core.generator import Generator
from content_studio.styles.registry import StylePreset, get_preset


@dataclass
class BuiltArticle:
    title: str = ""
    summary: str = ""
    body_html: str = ""
    image_captions: list[str] = field(default_factory=list)
    images: list[Image.Image] = field(default_factory=list)
    cover: Image.Image | None = None


@dataclass
class BuiltXHS:
    title: str = ""
    body: str = ""
    hashtags: list[str] = field(default_factory=list)
    cover_text: str = ""
    images: list[Image.Image] = field(default_factory=list)


@dataclass
class PipelineResult:
    target: str = "wechat"          # "wechat" | "xhs" —— 本次生成的目标
    wechat: BuiltArticle = field(default_factory=BuiltArticle)
    xhs: BuiltXHS = field(default_factory=BuiltXHS)
    used_comfyui: bool = False
    warnings: list[str] = field(default_factory=list)
    timings: dict = field(default_factory=dict)   # {"llm": 秒, "images": 秒}


def weave_images(body_html: str, img_srcs: list[str], captions: list[str] | None = None) -> str:
    """把 body_html 里的图片占位符替换为 img_srcs：
    - [[IMG:k]] 显式：放第 k 张（k 从 1 开始）→ img_srcs[k-1]
    - [[IMG]] 顺序：按出现顺序放未用过的图
    没被引用的图追加到末尾；占位符多于图则多余占位符留空。
    captions：每张图的图注（按索引），有则显示在图下。"""
    srcs = list(img_srcs)
    caps = list(captions) if captions else []
    used = [False] * len(srcs)

    def cap_of(k):  # k 从 1 开始
        return caps[k - 1] if 1 <= k <= len(caps) else None

    def IMG(url, cap=None):
        img = f'<img src="{url}" style="max-width:100%;height:auto;display:block;margin:0 auto;border-radius:8px;">'
        if cap:
            return f'<figure style="margin:12px 0;text-align:center;">{img}<figcaption style="font-size:13px;color:#888;margin-top:4px;">{cap}</figcaption></figure>'
        return f'<div style="margin:12px 0;">{img}</div>'

    # 把「图1」「图2」「图3」等自然引用转成 [[IMG:k]] 标记
    out = re.sub(r"图\s*(\d+)\s*[展示表是]", r"[[IMG:\1]]\n", body_html)
    out = re.sub(r"如\s*图\s*(\d+)", r"[[IMG:\1]]", out)
    body_html = out
    def _img_tag(m):
        k = int(m.group(1))
        if 1 <= k <= len(srcs):
            used[k - 1] = True
            return IMG(srcs[k - 1], cap_of(k))
        return ""
    out = re.sub(r"<img[^>]*\[\[IMG:(\d+)\]\][^>]*>", _img_tag, body_html)

    # 2) 裸 [[IMG:k]] → 整个 <img>
    def _explicit(m):
        k = int(m.group(1))
        if 1 <= k <= len(srcs):
            used[k - 1] = True
            return IMG(srcs[k - 1], cap_of(k))
        return ""
    out = re.sub(r"\[\[IMG:(\d+)\]\]", _explicit, out)
    ptr = 0

    def _pos(_m):
        nonlocal ptr
        while ptr < len(srcs) and used[ptr]:
            ptr += 1
        if ptr < len(srcs):
            used[ptr] = True
            ptr += 1
            return IMG(srcs[ptr - 1], cap_of(ptr))
        return ""

    out = re.sub(r"\[\[IMG\]\]", _pos, out)
    # 没被引用的图：如果有小节标题，分散插到标题后（从后往前插，避免位置错位）
    unused = [i for i in range(len(srcs)) if not used[i]]
    if unused:
        headers = list(re.finditer(r'(<h[23][^>]*>.*?</h[23]>)', out))
        if headers and len(unused) > 1:
            # 每个 header 后插一张图（从后往前，不影响前面的位置）
            pairs = []
            for idx, img_i in enumerate(unused):
                h_idx = min(idx, len(headers) - 1)
                pairs.append((headers[h_idx].end(), img_i))
            pairs.sort(reverse=True)  # 从后往前插
            for pos, img_i in pairs:
                img_html = IMG(srcs[img_i], cap_of(img_i + 1))
                out = out[:pos] + "\n" + img_html + "\n" + out[pos:]
        else:
            for i in unused:
                out += IMG(srcs[i], cap_of(i + 1))
    return out


def run_pipeline(
    material: str,
    image_paths: list[str],
    styles: list[StylePreset | None],
    cfg: AppConfig,
    generator: Generator,
    comfy: ComfyClient | None = None,
    target: str = "wechat",
    t2i_count: int = 0,
    t2i_prompt: str = "",
    progress: Callable[[str, float], None] = lambda _s, _p: None,
) -> PipelineResult:
    t0 = time.time()
    progress("llm", 0.1)
    wc = None
    xh = None
    if target == "xhs":
        xh = generator.generate_xhs(material)
    else:
        # 把原图传给 LLM；模型不支持视觉时由 LLM 层自动退回纯文本（靠手动放图）
        wc = generator.generate_wechat(material, None, images=image_paths)
    progress("llm", 0.5)
    t_llm = time.time() - t0

    # 每张照片一个风格（None = 用原图，不走 ComfyUI）；不足的补 None。
    t1 = time.time()
    padded = list(styles) + [None] * max(0, len(image_paths) - len(styles))

    styled: list[Image.Image] = []
    used = False
    warnings: list[str] = []

    for path, st in zip(image_paths, padded):
        if st is None or comfy is None or not cfg.comfy.enabled:
            styled.append(image_pipeline.load_image(path))
            continue
        try:
            styled.append(comfy.style_transfer(path, st))
            used = True
        except ComfyError as e:
            warnings.append(f"图片风格化失败，改用原图：{e}")
            styled.append(image_pipeline.load_image(path))
    progress("images", 0.8)

    wechat_imgs = [image_pipeline.resize_for_article(im) for im in styled] if target == "wechat" else []
    xhs_imgs = image_pipeline.build_xhs_images(styled, cfg.image, (xh.cover_text if xh else "")) if target == "xhs" else []

    # 用 ComfyUI 文生图补配图（用户自定义 prompt 优先，否则用文章的 image_prompts）
    if target == "wechat" and t2i_count and comfy is not None and cfg.comfy.enabled and wc is not None:
        gen_style = next((s for s in styles if s is not None), None) or get_preset("anime")
        if t2i_prompt.strip():
            prompts = [line.strip() for line in t2i_prompt.strip().splitlines() if line.strip()][:t2i_count]
        else:
            prompts = (wc.image_prompts or [])[:t2i_count]
        for prompt in prompts:
            try:
                wechat_imgs.append(comfy.text_to_image(prompt, gen_style))
            except ComfyError as e:
                warnings.append(f"AI image generation failed, skipped: {e}")

    # 用 ComfyUI 生成公众号卡片封面（2.35:1），放标题前
    wechat_cover = None
    if target == "wechat" and comfy is not None and cfg.comfy.enabled and wc is not None and (wc.cover_prompt or "").strip():
        gen_style = next((s for s in styles if s is not None), None) or get_preset("anime")
        try:
            cov = comfy.text_to_image(f"{wc.cover_prompt}, professional, clean, high quality, detailed", get_preset("anime"))
            wechat_cover = image_pipeline.to_wechat_cover(cov)
        except ComfyError as e:
            warnings.append(f"封面生成失败，跳过：{e}")
    progress("images", 0.97)
    t_img = time.time() - t1

    wechat = BuiltArticle(
        title=wc.title, summary=wc.summary, body_html=wc.body_html,
        image_captions=list(wc.image_captions), images=wechat_imgs, cover=wechat_cover,
    ) if wc else BuiltArticle()
    xhs = BuiltXHS(
        title=xh.title, body=xh.body, hashtags=list(xh.hashtags),
        cover_text=xh.cover_text, images=xhs_imgs,
    ) if xh else BuiltXHS()

    return PipelineResult(target=target, wechat=wechat, xhs=xhs, used_comfyui=used, warnings=warnings,
                          timings={"llm": round(t_llm, 1), "images": round(t_img, 1)})
