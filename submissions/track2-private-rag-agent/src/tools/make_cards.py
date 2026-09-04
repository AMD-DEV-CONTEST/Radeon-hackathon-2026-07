# -*- coding: utf-8 -*-
"""生成演示视频的标题卡与结尾卡（暗色 + AMD 红）。"""
import os
import sys
from PIL import Image, ImageDraw, ImageFont

OUT = "demo/video_frames"


def _font(size):
    for cand in ("C:/Windows/Fonts/msyhbd.ttc", "C:/Windows/Fonts/simhei.ttf"):
        if os.path.exists(cand):
            try:
                return ImageFont.truetype(cand, size)
            except Exception:
                pass
    return ImageFont.load_default()


def title_card(width, height, lines, out_name):
    img = Image.new("RGB", (width, height), (11, 13, 15))
    d = ImageDraw.Draw(img)
    # 顶部 AMD 红线
    d.rectangle([0, 0, width, 5], fill=(245, 67, 77))
    y = height * 0.38
    for i, (text, size, color) in enumerate(lines):
        f = _font(size)
        box = d.textbbox((0, 0), text, font=f)
        tw = box[2] - box[0]
        d.text(((width - tw) / 2, y), text, fill=color, font=f)
        y += size * 1.7
    img.save(os.path.join(OUT, out_name))
    print("card:", out_name)


def main():
    os.makedirs(OUT, exist_ok=True)
    W, H = 1280, 800
    # 标题卡
    title_card(W, H, [
        ("Private RAG Agent", 56, (232, 234, 237)),
        ("Fully offline multi-agent RAG on AMD Radeon", 24, (167, 173, 182)),
        ("Decompose · Parallel Research · Fact-Check · Synthesize", 20, (245, 67, 77)),
    ], "card_000_title.png")
    # 结尾卡
    title_card(W, H, [
        ("Retrieval you can trace", 40, (232, 234, 237)),
        ("Answers you can verify", 40, (232, 234, 237)),
        ("Data never leaves this machine", 40, (232, 234, 237)),
        ("Track 2 · MENG Yuxuan", 20, (167, 173, 182)),
    ], "card_999_end.png")


if __name__ == "__main__":
    main()
