"""把生成结果与处理后的图片打包到输出目录。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from content_studio.config import ImageConfig
from content_studio.core import image_pipeline
from content_studio.core.generator import WeChatContent, XHSContent


@dataclass
class ExportArtifacts:
    out_dir: Path
    wechat_text_path: Path
    xhs_text_path: Path
    wechat_images: list[Path]
    xhs_images: list[Path]


def format_wechat(wc: WeChatContent) -> str:
    lines = [f"标题：{wc.title}"]
    if wc.summary:
        lines.append(f"摘要：{wc.summary}")
    lines.append("")
    lines.append(wc.body_html or "")
    if wc.image_captions:
        lines.append("")
        lines.append("图注：")
        lines.extend(f"- {c}" for c in wc.image_captions)
    if wc.fell_back:
        lines.insert(0, "（⚠ 解析失败，以下为原始返回）")
    return "\n".join(lines)


def format_xhs(xh: XHSContent) -> str:
    lines = [f"标题：{xh.title}"]
    if xh.cover_text:
        lines.append(f"封面主标题：{xh.cover_text}")
    lines.append("")
    lines.append(xh.body or "")
    if xh.hashtags:
        lines.append("")
        lines.append(" ".join(xh.hashtags))
    if xh.fell_back:
        lines.insert(0, "（⚠ 解析失败，以下为原始返回）")
    return "\n".join(lines)


def export(
    wechat: WeChatContent,
    xhs: XHSContent,
    source_images: list[Image.Image],
    cfg: ImageConfig,
    out_dir: str | Path,
) -> ExportArtifacts:
    if wechat is None:
        wechat = WeChatContent()
    if xhs is None:
        xhs = XHSContent()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    wechat_dir = out_dir / "wechat"
    xhs_dir = out_dir / "xiaohongshu"

    wechat_imgs = image_pipeline.build_wechat_images(source_images, cfg)
    xhs_imgs = image_pipeline.build_xhs_images(source_images, cfg, xhs.cover_text)

    wechat_paths = [
        image_pipeline.save_jpeg(im, wechat_dir / f"img_{i + 1}.jpg", cfg.jpeg_quality)
        for i, im in enumerate(wechat_imgs)
    ]
    xhs_paths = [
        image_pipeline.save_jpeg(im, xhs_dir / f"img_{i + 1}.jpg", cfg.jpeg_quality)
        for i, im in enumerate(xhs_imgs)
    ]

    wechat_text_path = out_dir / "wechat.txt"
    xhs_text_path = out_dir / "xiaohongshu.txt"
    wechat_text_path.write_text(format_wechat(wechat), encoding="utf-8")
    xhs_text_path.write_text(format_xhs(xhs), encoding="utf-8")

    return ExportArtifacts(out_dir, wechat_text_path, xhs_text_path, wechat_paths, xhs_paths)
