#!/usr/bin/env python
# ============================================================
# img2prompt.py  —  图生文模块（Qwen2.5-VL-3B-Instruct, ROCm/AMD）
#
# 用途（多模态联动验收：上传图 → Qwen-VL 解析 → 出图）：
#   ① 参考图反向出图：上传一张贴纸/角色图 → 解析角色/配色 → char_desc
#   ② 草图细化：       上传一张手绘草图 → 识别内容 → char_desc
#
# 设计原则：只产出「角色描述标签串」，严格对齐 sticker_pipeline.py
#           的 BASE_HEAD 槽位，出图管线一行不改：
#   prompt = BASE_HEAD_PREFIX + char_desc + BASE_TAIL
#
# 模型：本地 transformers 加载（主力镜像 HuggingFace workaround 已预装
#       transformers 5.x / qwen-vl-utils 0.0.14 / accelerate），
#       权重位于 /persistent/models/Qwen2.5-VL-3B-Instruct（FP16，~7GB）
# ============================================================
import os
from PIL import Image

# Qwen-VL-3B 安全分辨率上限：图像 token 序列过长会退化输出 '!' 占位符
# （实测 ≥2048px 原图 4 次重试全部 '!'；缩到 1280 内 100% 正常）
VL_MAX_SIDE = 1536  # Qwen-VL-3B 偶发退化在高分辨率概率略升；1536 兼顾识别质量与稳定性（1280太保守/1920偶发率偏高）

# ---- 与 sticker_pipeline.py 完全一致的风格锚（不可改） ----
BASE_HEAD_PREFIX = '1girl, solo, chibi, '   # 固定前缀（物种/比例）
BASE_TAIL = (', blush stickers, sticker, thick outline, white border, '
             'flat color, vivid colors, pastel green background, simple background, '
             'foreground, overlapping border, upper body, distant view, '
             'masterpiece, high score, great score, absurdres')

NEG = ('lowres, bad anatomy, bad hands, extra digits, fewer digits, cropped, '
       'worst quality, low quality, low score, bad score, average score, '
       'signature, watermark, jpeg artifacts, blurry, 3d, realistic, gradient background, '
       'close up, face closeup, filling frame')

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_HERE))
_pvc_model = '/persistent/models/Qwen2.5-VL-3B-Instruct'
MODEL_PATH = os.environ.get(
    'QWEN_VL_PATH',
    _pvc_model if os.path.isdir(_pvc_model) else os.path.join(_PROJECT_ROOT, 'models', 'Qwen2.5-VL-3B-Instruct')
)

# 单例缓存，避免重复加载（FP16 权重 ~7GB，加载后 ~6GB 显存，48GB 卡无压力）
_MODEL = None
_PROCESSOR = None


# ------------------------------------------------------------
# system prompt：约束 Qwen-VL 只输出 SDXL 风格的「角色标签串」
# 关键：不要 style 词（chibi/sticker/outline 由 BASE_TAIL 提供），
#       只描述角色本体，英文逗号分隔，<=12 个 tag，无解释。
# ------------------------------------------------------------
SYS_REFERENCE = (
    "You are a prompt engineer for an anime chibi sticker generator (SDXL). "
    "Given a reference sticker image, output ONLY a short comma-separated list "
    "of English tags describing the CHARACTER's visual features for an SDXL prompt. "
    "Format: plain noun-phrase tags separated by commas — e.g. "
    "'demon, horns, tail, dark purple hair, spiky hair, red eyes, school uniform, "
    "cape, bow tie, trident, dark purple, red, blue, white skin'. "
    "Do NOT use 'key: value', 'key/value', or 'category - item' structured format. "
    "Combine color + object into one tag where natural (e.g. 'purple hair' NOT 'hair color: purple'). "
    "Do NOT include style words (chibi, sticker, outline, background, foreground, masterpiece, "
    "absurdres, score, watermark). "
    "Keep under 14 tags. No explanations, no numbering, no prefixes — just the tag list. "
    "List each tag EXACTLY ONCE — do not repeat any tag (no duplicates)."
)

SYS_SKETCH = (
    "You are a prompt engineer for an anime chibi sticker generator (SDXL). "
    "Given a hand-drawn sketch, first recognize what character/creature the user "
    "drew, then output ONLY a short comma-separated list of English tags describing "
    "it as a CHARACTER for an SDXL prompt. "
    "Format: plain noun-phrase tags separated by commas — e.g. "
    "'cat girl, cat ears, pink hair, green eyes, school uniform'. "
    "Do NOT use 'key: value', 'key/value', or 'category - item' structured format. "
    "Combine color + object into one tag where natural (e.g. 'pink hair' NOT 'hair color: pink'). "
    "If the sketch is ambiguous, infer the most likely cute character. "
    "Do NOT include style words (chibi, sticker, outline, background, foreground). "
    "Keep under 14 tags. No explanations, no numbering, no prefixes — just the tag list. "
    "List each tag EXACTLY ONCE — do not repeat any tag (no duplicates)."
)


def load_vl_model(model_path: str = MODEL_PATH):
    """加载 Qwen2.5-VL（单例，GPU）。返回 (model, processor)。"""
    global _MODEL, _PROCESSOR
    if _MODEL is not None and _PROCESSOR is not None:
        return _MODEL, _PROCESSOR

    from transformers import AutoModelForImageTextToText, AutoProcessor
    import torch

    print(f'[img2prompt] loading Qwen2.5-VL (FP16) from {model_path} ...')
    t0 = __import__('time').time()
    # ROCm/AMD：FP16 权重直接 float16 上卡（~6GB 显存，48GB 卡无压力）
    _MODEL = AutoModelForImageTextToText.from_pretrained(
        model_path,
        torch_dtype=torch.float16,
        device_map='auto',
        low_cpu_mem_usage=True,
    )
    _PROCESSOR = AutoProcessor.from_pretrained(model_path)
    print(f'[img2prompt] model loaded in {__import__("time").time() - t0:.1f}s')
    return _MODEL, _PROCESSOR


# ─── 风格锚黑名单：这些词由 BASE_TAIL 提供，绝不能出现在 char_desc，
#     否则会与 SDXL 模板重复/污染构图。作为后处理确定性防线（不依赖模型"听话"）───
_BAD_SUBWORDS = {
    'chibi', 'sticker', 'kawaii', 'cartoon', 'cartoonish', 'anime', 'outline',
    'background', 'foreground', 'watermark', 'masterpiece', 'absurdres', 'score',
    'detailed', 'quality', 'high-quality',
}


def _clean_tags(raw: str, max_tags: int = 14) -> str:
    """
    清洗 Qwen-VL 输出：取第一行，去编号/前缀/多余空白，按逗号拆词去重；
    并剔除与 BASE_TAIL 冲突的风格锚词（chibi/sticker/outline/background…），
    最后截断到 max_tags 个，避免模型在熟悉题材上狂吐描述词（见 8/4 回归测试）。
    """
    if not raw:
        return ''
    line = raw.strip().splitlines()[0].strip()
    # 去掉常见的 "tags:" / "Answer:" 等前缀
    for p in ('tags:', 'tag:', 'answer:', 'characters:', 'character:'):
        if line.lower().startswith(p):
            line = line[len(p):].strip()
    # 去掉首尾标点
    line = line.strip(' ,.;')
    # 按逗号拆词 -> 过滤风格词 -> 保序去重 -> 截断
    seen = set()
    uniq = []
    for tok in line.split(','):
        t = tok.strip().strip(' .,;').lower()
        if not t:
            continue
        # 丢弃含风格锚子词的 tag（如 'sticker-like appearance' / 'chibi character'）；
        # 'star stickers' 保留——'stickers' 是装饰复数，不在黑名单）
        words = t.replace('-', ' ').replace('_', ' ').split()
        if any(w in _BAD_SUBWORDS for w in words):
            continue
        if t in seen:
            continue
        seen.add(t)
        uniq.append(t)
    # 截断，避免超长（模型在熟悉题材上会狂吐）
    return ', '.join(uniq[:max_tags])


def image_to_char_desc(image, mode: str = 'reference'):
    """
    输入 PIL.Image 或图片路径，输出角色描述标签串（英文逗号分隔）。

    mode:
        'reference' → 参考图反向出图（SYS_REFERENCE）
        'sketch'    → 草图细化（SYS_SKETCH）
    """
    if mode not in ('reference', 'sketch'):
        raise ValueError(f"mode must be 'reference' or 'sketch', got {mode!r}")

    # 安全 resize：Qwen-VL-3B 对 ≥2048px 图会退化输出 '!'（图像 token 序列过长）
    if hasattr(image, 'size'):
        w, h = image.size
        max_side = max(w, h)
        if max_side > VL_MAX_SIDE:
            scale = VL_MAX_SIDE / max_side
            image = image.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

    from qwen_vl_utils import process_vision_info

    model, processor = load_vl_model()
    system = SYS_REFERENCE if mode == 'reference' else SYS_SKETCH

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": [
            {"type": "image", "image": image},
            {"type": "text", "text": "Describe the character now."},
        ]},
    ]

    text = processor.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )
    image_inputs, video_inputs = process_vision_info(messages)
    inputs = processor(
        text=text, images=image_inputs, videos=video_inputs,
        padding=True, return_tensors="pt"
    ).to(model.device)

    import torch
    with torch.inference_mode():
        generated = model.generate(
            **inputs,
            max_new_tokens=96,  # 收紧生成长度，抑制熟悉题材上狂吐描述词
            do_sample=False,
            repetition_penalty=1.1,  # 防 Qwen-VL 复读长描述词
        )
    out = processor.batch_decode(generated, skip_special_tokens=True)[0]
    # Qwen-VL 输出含输入回显，取最后一段
    out = out.split('assistant')[-1] if 'assistant' in out else out
    return _clean_tags(out)


def build_sdxl_prompt(char_desc: str):
    """把角色描述串拼进现有模板，返回 (prompt, negative_prompt)。"""
    char_desc = char_desc.strip().strip(',').strip()
    prompt = BASE_HEAD_PREFIX + char_desc + BASE_TAIL
    return prompt, NEG


# ------------------------------------------------------------
# CLI：python img2prompt.py <image_path> [reference|sketch]
# ------------------------------------------------------------
if __name__ == '__main__':
    import sys
    from PIL import Image

    if len(sys.argv) < 2:
        print('usage: python img2prompt.py <image_path> [reference|sketch]')
        sys.exit(1)

    img_path = sys.argv[1]
    mode = sys.argv[2] if len(sys.argv) > 2 else 'reference'
    img = Image.open(img_path).convert('RGB')

    desc = image_to_char_desc(img, mode)
    prompt, neg = build_sdxl_prompt(desc)

    print('\n=== char_desc ===')
    print(desc)
    print('\n=== SDXL prompt (filled) ===')
    print(prompt)
    print('\n=== negative ===')
    print(neg)
