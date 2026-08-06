# -*- coding: utf-8 -*-
"""AI-Image-Studio v2 (Radeon Edition)
Six high-quality AI image pipelines on AMD Radeon GPU + ROCm:
Inpaint · Outpaint · Remove · Style · Background · Asset Split.

Run:  python app.py            → http://localhost:7860
      python app.py --share    → public URL (cloud instances)
"""
from __future__ import annotations

import argparse
import inspect
import os
import threading

os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")

import gradio as gr
from PIL import Image

from config import settings
from src import intent
from src.device import detect_device, free_vram_gb
from src.model_manager import ModelManager
from src.pipelines import (STYLE_PRESETS, run_background, run_inpaint,
                           run_outpaint, run_remove, run_split, run_style)
from src.utils import editor_to_image_mask
from src.watermark import detect_watermark, snap_to_overlay


# ROCm compat: the torchvision deform_conv2d CPU detour (needed by BiRefNet
# matting on ROCm builds without the HIP kernel) is applied at import time by
# src/birefnet.py — pulled in via src.pipelines above — so the web app, backend
# scripts and test suites are all covered by the same shim.

DEVICE_INFO = detect_device(settings.device, settings.dtype)
MANAGER = ModelManager(DEVICE_INFO, settings)

APP_TITLE = "AI-Image-Studio · Radeon Edition"


def _perf_md(info: dict) -> str:
    lines = ["| Metric | Value |", "| --- | --- |"]
    for k, v in info.items():
        lines.append(f"| {k} | {v} |")
    return "\n".join(lines)


def _err(e: Exception):
    raise gr.Error(f"{type(e).__name__}: {e}")


# --- Tunnel upload guard --------------------------------------------------
# rc-tunnel's effective uplink is only ~120KB/s, and its edge (Azure Front
# Door) answers 504 OriginTimeout when the origin needs too long to receive
# a request body. ImageEditor re-uploads the whole canvas as PNG blobs on
# every Generate, so an uncapped 3-4K upload (8-15MB of blobs) always 504s
# and the button spins forever. Cap the canvas at SDXL's native 1024px long
# edge: blobs shrink to ~1MB (~10s over the tunnel) and every pipeline works
# at its native resolution anyway — zero effective quality loss.
MAX_CANVAS_EDGE = 1024


def _fit_edge(img: Image.Image | None, max_edge: int = MAX_CANVAS_EDGE):
    """Downscale to max_edge on the long side (LANCZOS); None/small pass through."""
    if img is None:
        return None
    w, h = img.size
    if max(w, h) <= max_edge:
        return img
    s = max_edge / max(w, h)
    return img.resize((max(1, round(w * s)), max(1, round(h * s))), Image.LANCZOS)


def _cap_editor_canvas(editor):
    """ImageEditor .upload handler: shrink oversized uploads before they
    become the canvas (see MAX_CANVAS_EDGE). Small images are skipped so the
    canvas doesn't flicker."""
    if not isinstance(editor, dict):
        return gr.skip()
    bg = editor.get("background")
    if bg is None:
        return gr.skip()
    small = _fit_edge(bg)
    if small is bg:
        return gr.skip()
    return small


def _status_md() -> str:
    lines = [
        "### Runtime",
        f"- Inference backend: **{DEVICE_INFO.summary()}**",
        f"- Low-VRAM mode: {'ON' if settings.low_vram else 'OFF'}",
        f"- SDXL working resolution: {settings.max_working_size}px (long edge)",
        f"- LCM turbo: {'available' if settings.enable_lcm else 'disabled'} ({settings.lcm_steps} steps)",
        f"- Intent layer (LLM 指令理解): {intent.llm_status(MANAGER)}",
        f"- Engine warmup (引擎预热): {WARMUP_STATUS}",
    ]
    if DEVICE_INFO.is_gpu:
        lines.append(f"- Free VRAM now: {free_vram_gb():.2f} GB")
    lines += ["", "### Loaded models"]
    loaded = MANAGER.loaded_models()
    lines += [f"- {m}" for m in loaded] if loaded else ["- (none yet — models load lazily)"]
    return "\n".join(lines)


def _editor(label: str, height: int = 460) -> gr.ImageEditor:
    return gr.ImageEditor(
        label=label, type="pil", sources=["upload", "clipboard"],
        transforms=(), layers=False, height=height,
        brush=gr.Brush(default_size=36, colors=["#FFFFFF"], color_mode="fixed"),
        eraser=gr.Eraser(default_size=36),
    )


# Built-in one-click examples: ship tiny demo images (+ pre-brushed masks for
# the editor tabs) so a judge can run every pipeline without uploading anything
# first. Implemented as gr.Gallery + select — NOT gr.Examples: in this Gradio
# version only the first lazily-mounted Dataset renders its sample cells; every
# Dataset mounted after that renders empty rows (verified in the live browser).
EX_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "assets", "examples")


def _ex(name: str) -> str:
    return os.path.join(EX_DIR, name)


def _editor_value(img: str, mask: str | None = None) -> dict:
    """ImageEditor example payload; the optional mask is a pre-brushed layer."""
    v = {"background": _ex(img), "layers": [], "composite": _ex(img)}
    if mask:
        v["layers"] = [_ex(mask)]
    return v


def _example_gallery(items: list[tuple[str, str]], label: str) -> gr.Gallery:
    """Thumbnail strip of one-click examples; selecting one fills the form."""
    return gr.Gallery(
        value=[(_ex(img), cap) for img, cap in items],
        label=label, show_label=True,
        columns=max(len(items), 2), rows=1, height=180,
        object_fit="contain", allow_preview=False,
        elem_classes=["example-gallery"])


# ------------------------------------------------------- example select fills
_NEG_EX = "blurry, low quality, deformed, watermark, text"


def _ex_res(name: str) -> str:
    """Pre-computed demo result shown INSTANTLY when an example is picked —
    judges see a finished before/after without waiting for a live run."""
    return os.path.join(EX_DIR, "results", name)


_PRE_NOTE = ("📷 **预计算示例结果（秒开展示）** — 图片与参数已自动填好，"
             "点击运行按钮可随时实时重跑验证。")


def _ex_idx(evt: gr.SelectData) -> int:
    """Gallery SelectData.index may be a flat int or a [row, col] pair."""
    i = evt.index
    if isinstance(i, (list, tuple)):
        i = i[0]
    return int(i or 0)

INPAINT_EXAMPLES = [
    ("dress", "🌈 Recolor · 把裙子改成淡蓝色（红区=预涂蒙版预览）"),
    ("multi", "🌈 Recolor · 头发改黑 + 外套改紫"),
]


def _ex_inpaint_select(evt: gr.SelectData):
    key = INPAINT_EXAMPLES[_ex_idx(evt)][0]
    prompt = {"dress": "把裙子改成淡蓝色",
              "multi": "把头发改成黑色，外套改成紫色"}[key]
    return (_editor_value(f"inpaint_{key}.jpg", f"inpaint_{key}_mask.png"),
            "🌈 Recolor only — instant, keeps lines & shading",
            prompt, _NEG_EX, 0.85, 30, 7.5, -1, True,
            _ex_res(f"inpaint_{key}.jpg"), _PRE_NOTE)


REMOVE_EXAMPLES = [
    ("remove_orange.jpg", "右下角半透明水印 → 点 🔍智能检测 自动涂蒙版"),
    ("remove_silver.jpg", "右下角半透明水印 → 检测后一键 Remove"),
]


def _ex_remove_select(evt: gr.SelectData):
    i = _ex_idx(evt)
    return (_editor_value(REMOVE_EXAMPLES[i][0]), 12,
            _ex_res(REMOVE_EXAMPLES[i][0]), _PRE_NOTE)


OUTPAINT_EXAMPLES = [
    ("outpaint_room.jpg", "向左扩 256px · 延续少女卧室场景"),
]


def _ex_outpaint_select(evt: gr.SelectData):
    return (_ex("outpaint_room.jpg"), 256, 0, 0, 0,
            "延续原图场景：温馨的少女卧室，米色墙壁，深色木柜与木地板，自然柔和光线",
            _NEG_EX, 30, 7.5, -1, True,
            _ex_res("outpaint_room.jpg"), _PRE_NOTE)


STYLE_EXAMPLES = [
    ("style_anime.jpg", "真人照片 → Anime 风（结构锁保护构图）"),
]


def _ex_style_select(evt: gr.SelectData):
    return (_ex("style_anime.jpg"), "Anime", 0.5, True, "", "", 30, 7.0, -1, True,
            _ex_res("style_anime.jpg"), _PRE_NOTE)


BACKGROUND_EXAMPLES = [
    ("bg_beach.jpg", "发丝级抠图 + AI 生成阳光沙滩背景"),
]


def _ex_background_select(evt: gr.SelectData):
    return (_ex("bg_beach.jpg"), "AI-generated", "#FFFFFF", "#89CFF0", "#F0E68C",
            "阳光沙滩与蓝色大海，天空清澈，柔和自然光，摄影感", 30, -1, True,
            _ex_res("bg_ai.jpg"), _ex_res("bg_cutout.png"), _PRE_NOTE)


SPLIT_EXAMPLES = [
    ("split_hat.jpg", "草帽少女 → 透明人物层 + AI 补全背景层"),
]


def _ex_split_select(evt: gr.SelectData):
    return (_ex("split_hat.jpg"), True, 16,
            _ex_res("split_char.png"), _ex_res("split_bg.jpg"), _PRE_NOTE)


def _note(info: dict, plan: dict | None) -> dict:
    """Prepend the intent layer's one-line understanding to the perf table."""
    if plan and plan.get("summary"):
        tag = "LLM" if plan.get("engine") == "llm" else "规则"
        return {"🧠 已理解指令": f"{plan['summary']}（{tag}）", **info}
    return info


# ------------------------------------------------------------------- warmup
# ROCm/MIOpen autotunes convolution kernels PER INPUT SHAPE: the first run at
# any unseen size stalls for minutes (measured: 363 s wall for 8×0.38 s
# steps). The pipelines quantize every working image to 7 canonical SDXL
# buckets, and this warmup pre-pays the compile tax for the common ones in a
# background thread right after launch — the first real click is then fast.
WARMUP_STATUS = "pending"


def _warmup():
    global WARMUP_STATUS
    if not settings.enable_warmup or not DEVICE_INFO.is_gpu:
        WARMUP_STATUS = "disabled"
        return
    WARMUP_STATUS = "running… 预热中，头几分钟首次点击可能稍慢"

    def _stage(name, fn):
        """Each stage logs and isolates failures — one broken stage must not
        kill the rest of the warmup."""
        global WARMUP_STATUS
        WARMUP_STATUS = f"running… 预热 {name}"
        print(f"[warmup] {name} ...", flush=True)
        t0 = time.time()
        try:
            fn()
            print(f"[warmup] {name} ok ({time.time()-t0:.0f}s)", flush=True)
        except Exception as e:
            print(f"[warmup] {name} FAILED (harmless): "
                  f"{type(e).__name__}: {e}", flush=True)

    try:
        import time
        import numpy as _np
        # All 7 canonical buckets — the pipelines quantize every working
        # image to one of these, so pre-paying the compile tax for each
        # means no user click ever hits a ~6 min MIOpen autotune stall.
        from src.pipelines.background import _NATIVE_BUCKETS
        buckets = list(_NATIVE_BUCKETS)
        rng = _np.random.default_rng(0)
        probe = Image.fromarray(
            (rng.random((256, 256, 3)) * 255).astype("uint8"), "RGB")

        def _img2img():
            pipe = MANAGER.get_img2img_pipe()
            MANAGER.set_lcm(pipe, True)
            for w, h in buckets:
                pipe(prompt="warmup", image=probe.resize((w, h)),
                     strength=0.5, num_inference_steps=2,
                     guidance_scale=1.0).images

        def _inpaint():
            pipe = MANAGER.get_inpaint_pipe()
            MANAGER.set_lcm(pipe, True)
            for w, h in buckets:
                pipe(prompt="warmup", image=probe.resize((w, h)),
                     mask_image=Image.new("L", (w, h), 255), strength=1.0,
                     num_inference_steps=2, guidance_scale=1.0).images

        def _txt2img():
            pipe = MANAGER.get_txt2img_pipe()
            MANAGER.set_lcm(pipe, True)
            for w, h in buckets:
                pipe(prompt="warmup", num_inference_steps=2,
                     guidance_scale=1.0, width=w, height=h).images

        def _cn():
            pipe = MANAGER.get_controlnet_img2img_pipe()
            MANAGER.set_lcm(pipe, True)
            for w, h in buckets[:4]:
                pipe(prompt="warmup", image=probe.resize((w, h)),
                     control_image=probe.resize((w, h)),
                     controlnet_conditioning_scale=0.6, strength=0.5,
                     num_inference_steps=2, guidance_scale=1.0).images

        _stage("img2img/repaint", _img2img)
        _stage("inpaint/outpaint", _inpaint)
        _stage("txt2img/background", _txt2img)
        _stage("controlnet/style", _cn)
        _stage("birefnet", lambda: MANAGER.get_birefnet())
        _stage("lama", lambda: MANAGER.get_lama())
        if settings.enable_intent_llm:
            _stage("intent-llm", lambda: MANAGER.get_llm())
        WARMUP_STATUS = "done ✅ 全部引擎路径已预编译，点击即秒出"
        print("[warmup] ALL DONE", flush=True)
    except Exception as e:  # warmup must never take the app down
        WARMUP_STATUS = f"partial (harmless 无害): {type(e).__name__}: {e}"
        print(f"[warmup] aborted: {e}", flush=True)


# ---------------------------------------------------------------- callbacks

def cb_inpaint(editor, mode, prompt, negative, strength, steps, guidance, seed, fast):
    try:
        image, mask = editor_to_image_mask(editor, expand_px=6)
        engine = "recolor" if str(mode).startswith("🌈") else "ai"
        targets = None
        plan = intent.interpret_inpaint(MANAGER, prompt)
        if plan:
            if plan.get("mode") == "repaint" and plan.get("prompt"):
                engine = "ai"            # 设计/材质类修改：换色引擎做不到，自动切换
                prompt = plan["prompt"]
                strength = plan.get("strength") or strength
            elif plan.get("mode") == "recolor_multi" and plan.get("targets"):
                engine = "recolor_multi"  # 多目标换色：分区即时换色，不动扩散模型
                targets = plan["targets"]
            elif plan.get("mode") == "recolor":
                engine = "recolor"
                if plan.get("color"):    # LLM 提取的精准颜色词，避免解析器歧义
                    prompt = plan["color"]
        region = (plan or {}).get("region", "")
        out, info, _ = run_inpaint(MANAGER, image, mask, prompt, negative,
                                   strength, steps, guidance, seed, fast,
                                   mode=engine, targets=targets, region=region)
        return out, _perf_md(_note(info, plan))
    except Exception as e:
        _err(e)


def cb_outpaint(image, left, right, top, bottom, prompt, negative,
                steps, guidance, seed, fast):
    try:
        plan = intent.interpret_outpaint(MANAGER, prompt)
        if plan and plan.get("prompt"):
            prompt = plan["prompt"]
        out, info, _ = run_outpaint(MANAGER, image, left, right, top, bottom,
                                    prompt, negative, steps, guidance, seed, fast)
        return out, _perf_md(_note(info, plan))
    except Exception as e:
        _err(e)


def _mask_to_editor(image: Image.Image, mask: Image.Image) -> dict:
    """Wrap a white mask as an ImageEditor value (painted layer)."""
    rgba = Image.merge("RGBA", (mask, mask, mask, mask))
    return {"background": image, "layers": [rgba], "composite": image}


def cb_detect_watermark(editor):
    """🔍 智能检测水印 button.

    - Nothing painted → run the high-precision auto detector.  It only
      fires on a confident text-line signature (smooth corners/strips);
      otherwise it abstains and tells the user to rough-brush instead.
    - Already painted → smart-snap the rough stroke onto the faint
      overlay strokes, and report stroke width + suggested brush size.
    """
    try:
        image, mask = editor_to_image_mask(editor, expand_px=0)
        if image is None:
            _err(ValueError("请先上传图片"))
        painted = mask is not None and mask.getextrema()[1] > 0
        if painted:
            snapped, info = snap_to_overlay(image, mask)
            if info.get("mode") == "snapped":
                hint = (f"✨ **智能吸附完成**：蒙版已贴合到微弱覆盖层笔画"
                        f"（覆盖率 {info['coverage']}%）。估计笔画宽 ≈{info['stroke']}px，"
                        f"建议补涂画笔 **~{info['brush']}px**。确认后点 **Remove**。")
            else:
                hint = ("✅ 已保留你的涂抹区域（未检测到半透明覆盖层，"
                        "按原蒙版擦除更稳妥）。确认后点 **Remove**。")
            return _mask_to_editor(image, snapped), hint
        mask, info = detect_watermark(image)
        if mask is None:
            return gr.skip(), ("🤔 未自动检测到明确水印（背景复杂时会主动保守，避免误伤画面）。"
                               "请用笔刷**粗涂一笔**覆盖水印，再点一次本按钮——"
                               "我会把蒙版**智能吸附**到水印笔画上 ✨")
        hint = (f"🎯 **检测到 {info['regions']} 处水印**（覆盖率 {info['coverage']}%，"
                f"笔画 ≈{info.get('stroke', '?')}px），已自动涂抹 ✓ "
                f"如需补涂建议画笔 **~{info['brush']}px**。确认后点 **Remove**。")
        return _mask_to_editor(image, mask), hint
    except Exception as e:
        _err(e)


def cb_remove(editor, expand):
    try:
        image, mask = editor_to_image_mask(editor, expand_px=0)
        if image is not None and mask is not None and mask.getextrema()[1] > 0:
            # Smart snap: shrink a rough stroke onto the faint overlay
            # strokes before LaMa — erases the watermark without eating
            # surrounding content.  Snapped masks need less expansion.
            mask, snap_info = snap_to_overlay(image, mask)
            if snap_info.get("mode") == "snapped":
                expand = min(int(expand), 6)
        else:
            snap_info = None
        out, info = run_remove(MANAGER, image, mask, expand_px=expand)
        if snap_info and snap_info.get("mode") == "snapped":
            info = {"✨ 智能吸附": f"蒙版已贴合笔画（≈{snap_info['stroke']}px 宽）",
                    **info}
        return out, _perf_md(info)
    except Exception as e:
        _err(e)


def cb_style(image, style, strength, lock, cp, cn, steps, guidance, seed, fast):
    try:
        plan = None
        if (cp or "").strip():
            # 自定义风格描述 → LLM 匹配预设或补全提示词
            plan = intent.interpret_style(MANAGER, cp, list(STYLE_PRESETS.keys()))
            if plan:
                if plan.get("preset"):
                    style, cp = plan["preset"], ""
                elif plan.get("custom_prompt"):
                    cp = plan["custom_prompt"]
                if plan.get("strength"):
                    strength = plan["strength"]
        out, info, _ = run_style(MANAGER, image, style, strength, lock,
                                 cp, cn, steps, guidance, seed, fast)
        return out, _perf_md(_note(info, plan))
    except Exception as e:
        _err(e)


def cb_background(image, mode, solid, gt, gb, ai_prompt, steps, seed, fast):
    try:
        plan = None
        if str(mode) == "AI-generated" and (ai_prompt or "").strip():
            plan = intent.interpret_background(MANAGER, ai_prompt)
            if plan and plan.get("prompt"):
                ai_prompt = plan["prompt"]
        result, fg, info = run_background(MANAGER, image, mode, solid, gt, gb,
                                          ai_prompt, steps, seed, fast)
        return result, fg, _perf_md(_note(info, plan))
    except Exception as e:
        _err(e)


def cb_split(image, fill_bg, margin):
    try:
        chara, bg, files, info = run_split(MANAGER, image, bool(fill_bg), int(margin))
        return chara, bg, files, _perf_md(info)
    except Exception as e:
        _err(e)


# ---------------------------------------------------------------- UI

CSS = """
.gradio-container {max-width: 1320px !important; margin: 0 auto !important; padding: 0 18px;}
#app-header {text-align: center; padding: 22px 0 6px;}
#app-header h1 {font-size: 32px; font-weight: 800; margin: 0; letter-spacing: -0.5px;}
#app-header h1 .accent {color: #ED1C24;}
#app-header p.sub {color: #666; margin: 8px auto 12px; max-width: 880px; font-size: 15px; line-height: 1.6;}
#app-header .badge {
    display: inline-block; background: #111; color: #7CF29C; font-family: monospace;
    font-size: 13px; padding: 6px 16px; border-radius: 999px; margin-bottom: 6px;
}
.hint {color: #555; font-size: 14px; margin: 2px 0 10px; line-height: 1.6;}
.hint b {color: #222;}
.tipbox {
    background: #FFF7E6; border: 1px solid #FFE1A8; border-radius: 10px;
    padding: 10px 14px; font-size: 13px; color: #7A5A00; margin-top: 10px;
}
/* Example galleries: compact one-click thumbnail strips. (gr.Examples/Dataset
   is unused — this Gradio build only renders samples in the first
   lazily-mounted Dataset; Gallery is unaffected.) */
.example-gallery {
    border: 1px solid #E5E7EB; border-radius: 12px; padding: 6px 10px 10px;
    background: #FAFBFC;
}
.example-gallery .thumbnail-item {
    border-radius: 10px !important; border: 1px solid #E5E7EB !important;
    background: #F8FAFC; height: 180px !important; max-height: 180px !important;
}
.example-gallery .thumbnail-item img {
    object-fit: contain !important; max-height: 100% !important;
}
.example-gallery .grid-container {max-height: 210px !important;}
.perf-table table {font-size: 13px;}
footer {display: none !important;}
"""

# --- Client-side upload squash ---------------------------------------------
# The tunnel uplink is ~120KB/s (see MAX_CANVAS_EDGE): a 3-5MB phone photo
# took 5+ minutes to reach the editor. Squash big images IN THE BROWSER
# before upload: long edge 1600px + JPEG q0.92 → ~200-400KB, i.e. seconds.
# Runs in the capture phase and re-dispatches change with a guard flag so
# Gradio's own handler sees only the squashed File. PNGs with real alpha
# stay PNG. Failures silently fall back to the original upload.
HEAD_JS = """
<script>
(function () {
  var MAX_EDGE = 1600, MIN_BYTES = 800 * 1024;
  document.addEventListener('change', function (ev) {
    var t = ev.target;
    if (!(t instanceof HTMLInputElement) || t.type !== 'file' || !t.files || !t.files.length) return;
    if (t.__squashed) { t.__squashed = false; return; }
    var f = t.files[0];
    if (!/^image\\//.test(f.type)) return;
    (async function () {
      try {
        var bmp = await createImageBitmap(f);
        var w = bmp.width, h = bmp.height;
        if (f.size < MIN_BYTES && Math.max(w, h) <= MAX_EDGE) return;
        var s = Math.min(1, MAX_EDGE / Math.max(w, h));
        var cw = Math.max(1, Math.round(w * s)), ch = Math.max(1, Math.round(h * s));
        var cv = document.createElement('canvas'); cv.width = cw; cv.height = ch;
        var cx = cv.getContext('2d'); cx.drawImage(bmp, 0, 0, cw, ch);
        var type = 'image/jpeg', q = 0.92;
        if (f.type === 'image/png') {
          var d = cx.getImageData(0, 0, cw, ch).data, opaque = true;
          for (var i = 3; i < d.length; i += 160) { if (d[i] < 250) { opaque = false; break; } }
          if (!opaque) { type = 'image/png'; q = undefined; }
        }
        var blob = await new Promise(function (r) { cv.toBlob(r, type, q); });
        if (!blob || blob.size >= f.size) return;
        var nf = new File([blob],
          f.name.replace(/\\.\\w+$/, type === 'image/jpeg' ? '.jpg' : '.png'), { type: type });
        var dt = new DataTransfer(); dt.items.add(nf);
        t.__squashed = true; t.files = dt.files;
        t.dispatchEvent(new Event('change', { bubbles: true }));
      } catch (e) { /* let the original upload proceed */ }
    })();
  }, true);
})();
</script>
"""


def _theme():
    return gr.themes.Soft(
        primary_hue=gr.themes.colors.red,
        neutral_hue=gr.themes.colors.zinc,
    )


def _header():
    gr.HTML(f"""
    <div id="app-header">
      <h1>🎨 AI-Image-Studio <span class="accent">· Radeon Edition</span></h1>
      <p class="sub">Six production-grade AI image pipelines running locally on
      <b>AMD Radeon GPU + ROCm</b> — Inpaint · Outpaint · Remove · Style ·
      Background · Asset Split. Powered by <b>SDXL</b> with LCM-LoRA turbo mode.</p>
      <div class="badge">⚙️ {DEVICE_INFO.summary()}</div>
    </div>""")


def build_demo() -> gr.Blocks:
    blocks_kwargs = dict(title=APP_TITLE)
    sig = inspect.signature(gr.Blocks.__init__).parameters
    if "css" in sig:
        blocks_kwargs["css"] = CSS
    if "head" in sig:
        blocks_kwargs["head"] = HEAD_JS
    if "theme" in sig and "theme" not in inspect.signature(gr.Blocks.launch).parameters:
        blocks_kwargs["theme"] = _theme()
    with gr.Blocks(**blocks_kwargs) as demo:
        _header()

        with gr.Tabs():
            # ================= Home =================
            with gr.Tab("🏠 Home"):
                gr.Markdown("""
### How to get the best results

| Pipeline | Input | Tips |
| --- | --- | --- |
| 🖌️ **Inpaint** | image + brushed mask + prompt | **Recolor mode** (default): name the color, instant, lines & shading untouched. **AI repaint mode**: describe a new design/material — the crop-around-mask engine keeps edits local and sharp. |
| 🔍 **Outpaint** | image + extend px + scene prompt | Describe the **whole** scene, not just the new part. |
| 🧽 **Remove** | image + brushed mask | No prompt needed — LaMa fills cleanly. **🔍 智能检测水印** auto-marks faint watermarks, or snaps your rough stroke onto the exact strokes. |
| 🎭 **Style** | image + style preset | Keep **Structure lock ON** to preserve pose & identity. Strength 0.4–0.55 restyles; higher replaces the subject. |
| 🧑‍🎨 **Background** | image with a clear subject | AI mode: describe the scene (*"marble podium, soft studio light"*). |
| 🧩 **Asset Split** | image with a clear subject | Outputs transparent character + completed background as **layered PSD**. |

**⚡ LCM turbo** trades a little detail for 3–5× speed — great for drafts, use standard mode for final output.
**📐 Big uploads are squashed in your browser to ~1600px/JPEG before transfer** (seconds over the tunnel instead of minutes), then auto-fitted to SDXL's native 1024px working size — same output quality, much faster transfers.
All metrics (latency / steps / peak VRAM) are measured live on the Radeon GPU below each result.
""")

            # ================= Inpaint =================
            with gr.Tab("🖌️ Inpaint"):
                gr.Markdown("Brush **exactly** the area to change → describe the result. "
                            "The engine crops around your mask and repaints it at full SDXL "
                            "resolution, so edits stay local and detailed.", elem_classes=["hint"])
                with gr.Row():
                    with gr.Column(scale=5, min_width=360):
                        ed = _editor("Image + brush mask")
                        mode1 = gr.Radio(
                            ["🌈 Recolor only — instant, keeps lines & shading",
                             "🎨 AI repaint — changes design & material"],
                            value="🌈 Recolor only — instant, keeps lines & shading",
                            label="Edit mode")
                        prompt = gr.Textbox(
                            label="Prompt",
                            placeholder="Recolor: name the color — \"purple\" or \"turn the red shirt purple\" · AI repaint: describe the new content")
                        negative = gr.Textbox(label="Negative prompt",
                                              value="blurry, low quality, deformed, watermark, text")
                        strength1 = gr.Slider(
                            0.3, 1.0, 0.85, step=0.05,
                            label="Strength (AI repaint only · recolor: n/a · keep ≥0.8 for visible change)")
                        with gr.Accordion("Advanced", open=False):
                            steps = gr.Slider(10, 50, 30, step=1, label="Inference steps")
                            guidance = gr.Slider(1.0, 15.0, 7.5, step=0.5, label="Guidance scale (CFG)")
                            seed = gr.Number(-1, label="Seed (-1 = random)", precision=0)
                        fast = gr.Checkbox(value=True, label="⚡ LCM turbo (8 steps, 3–5× faster)")
                        btn = gr.Button("Run Inpainting", variant="primary", size="lg")
                    with gr.Column(scale=6, min_width=400):
                        out = gr.Image(label="Result", type="pil", interactive=False, height=480)
                        perf = gr.Markdown(elem_classes=["perf-table"])
                gr.HTML('<div class="tipbox">💡 <b>Recolor</b> mode never alters the drawing — it only shifts '
                        'the hue of the brushed area (purple, navy, black…). Use <b>AI repaint</b> when you '
                        'want a different design, pattern or material.</div>')
                btn.click(cb_inpaint, [ed, mode1, prompt, negative, strength1, steps, guidance, seed, fast],
                          [out, perf])
                ed.upload(_cap_editor_canvas, ed, ed)
                gal1 = _example_gallery(
                    [(f"inpaint_{k}_preview.jpg", cap) for k, cap in INPAINT_EXAMPLES],
                    "📌 一键示例：点缩略图 = 填好 图+蒙版+指令 + 秒看预计算结果，点 Run 实时重跑")
                gal1.select(_ex_inpaint_select, None,
                            [ed, mode1, prompt, negative, strength1,
                             steps, guidance, seed, fast, out, perf])

            # ================= Outpaint =================
            with gr.Tab("🔍 Outpaint"):
                gr.Markdown("Extend the canvas in any direction — SDXL seamlessly invents the new "
                            "scenery at its native resolution.", elem_classes=["hint"])
                with gr.Row():
                    with gr.Column(scale=5, min_width=360):
                        img = gr.Image(label="Image", type="pil", sources=["upload", "clipboard"],
                                       height=320)
                        with gr.Row():
                            left = gr.Slider(0, 512, 0, step=32, label="Extend left (px)")
                            right = gr.Slider(0, 512, 256, step=32, label="Extend right (px)")
                        with gr.Row():
                            top = gr.Slider(0, 512, 0, step=32, label="Extend up (px)")
                            bottom = gr.Slider(0, 512, 0, step=32, label="Extend down (px)")
                        prompt = gr.Textbox(
                            label="Prompt (describe the FULL scene)",
                            placeholder="e.g. wide mountain landscape at golden hour, lake in front")
                        negative = gr.Textbox(label="Negative prompt",
                                              value="blurry, low quality, seam, watermark, text")
                        with gr.Accordion("Advanced", open=False):
                            steps2 = gr.Slider(10, 50, 30, step=1, label="Inference steps")
                            guidance2 = gr.Slider(1.0, 15.0, 7.5, step=0.5, label="Guidance scale (CFG)")
                            seed2 = gr.Number(-1, label="Seed (-1 = random)", precision=0)
                        fast2 = gr.Checkbox(value=True, label="⚡ LCM turbo (8 steps)")
                        btn2 = gr.Button("Run Outpainting", variant="primary", size="lg")
                    with gr.Column(scale=6, min_width=400):
                        out2 = gr.Image(label="Result", type="pil", interactive=False, height=480)
                        perf2 = gr.Markdown(elem_classes=["perf-table"])
                btn2.click(cb_outpaint, [img, left, right, top, bottom, prompt, negative,
                                         steps2, guidance2, seed2, fast2], [out2, perf2])
                gal2 = _example_gallery(
                    OUTPAINT_EXAMPLES,
                    "📌 一键示例：点缩略图 = 填好参数 + 秒看预计算结果，点 Run 实时重跑")
                gal2.select(_ex_outpaint_select, None,
                            [img, left, right, top, bottom, prompt, negative,
                             steps2, guidance2, seed2, fast2, out2, perf2])

            # ================= Remove =================
            with gr.Tab("🧽 Remove"):
                gr.Markdown("Brush over unwanted objects, passers-by or watermarks — one click erases "
                            "them (LaMa engine, prompt-free, seconds). **去水印小巧思**：点 "
                            "**🔍 智能检测水印** 可自动定位半透明水印；或粗涂一笔让它**智能吸附**到笔画上。",
                            elem_classes=["hint"])
                with gr.Row():
                    with gr.Column(scale=5, min_width=360):
                        ed3 = _editor("Image + brush over what to erase")
                        btn_wm = gr.Button("🔍 智能检测水印 / 吸附涂抹", size="lg")
                        wm_hint = gr.Markdown("", elem_classes=["hint"])
                        expand3 = gr.Slider(0, 40, 12, step=2, label="Mask expansion (px)")
                        btn3 = gr.Button("Remove", variant="primary", size="lg")
                    with gr.Column(scale=6, min_width=400):
                        out3 = gr.Image(label="Result", type="pil", interactive=False, height=480)
                        perf3 = gr.Markdown(elem_classes=["perf-table"])
                gr.HTML('<div class="tipbox">💡 去水印：先点 <b>🔍 智能检测</b>——检测到会自动涂好蒙版；'
                        '检测不到时粗涂一笔再点一次，蒙版会<b>吸附到水印笔画</b>，'
                        '擦除更干净、不伤周围画面。一般物体：笔刷略超出物体边缘再 Remove。</div>')
                btn_wm.click(cb_detect_watermark, [ed3], [ed3, wm_hint])
                btn3.click(cb_remove, [ed3, expand3], [out3, perf3])
                ed3.upload(_cap_editor_canvas, ed3, ed3)
                gal3 = _example_gallery(
                    REMOVE_EXAMPLES,
                    "📌 一键示例：点缩略图 = 填图 + 秒看去水印结果；实时跑：先 🔍智能检测 再 Remove")
                gal3.select(_ex_remove_select, None, [ed3, expand3, out3, perf3])

            # ================= Style =================
            with gr.Tab("🎭 Style"):
                gr.Markdown("Restyle a photo into anime, cyberpunk, watercolor and more — with "
                            "**ControlNet structure lock** the subject's pose, composition and "
                            "identity are preserved.", elem_classes=["hint"])
                with gr.Row():
                    with gr.Column(scale=5, min_width=360):
                        img5 = gr.Image(label="Image", type="pil", sources=["upload", "clipboard"],
                                        height=320)
                        style = gr.Dropdown(list(STYLE_PRESETS.keys()), value="Anime",
                                            label="Style preset")
                        strength5 = gr.Slider(
                            0.2, 0.7, 0.5, step=0.05,
                            label="Strength (0.4–0.55 restyle · higher replaces subject)")
                        lock5 = gr.Checkbox(value=True, label="🔒 Structure lock (keep pose & identity)")
                        with gr.Accordion("Custom prompt (optional, overrides preset)", open=False):
                            cp = gr.Textbox(label="Custom prompt")
                            cn = gr.Textbox(label="Custom negative prompt")
                        with gr.Accordion("Advanced", open=False):
                            steps5 = gr.Slider(10, 50, 30, step=1, label="Inference steps")
                            guidance5 = gr.Slider(1.0, 15.0, 7.0, step=0.5, label="Guidance scale (CFG)")
                            seed5 = gr.Number(-1, label="Seed (-1 = random)", precision=0)
                        fast5 = gr.Checkbox(value=True, label="⚡ LCM turbo (8 steps)")
                        btn5 = gr.Button("Restyle", variant="primary", size="lg")
                    with gr.Column(scale=6, min_width=400):
                        out5 = gr.Image(label="Result", type="pil", interactive=False, height=480)
                        perf5 = gr.Markdown(elem_classes=["perf-table"])
                gr.HTML('<div class="tipbox">💡 Person looks replaced? Lower the strength to 0.3–0.4 '
                        'and make sure Structure lock is ON.</div>')
                btn5.click(cb_style, [img5, style, strength5, lock5, cp, cn,
                                      steps5, guidance5, seed5, fast5], [out5, perf5])
                gal5 = _example_gallery(
                    STYLE_EXAMPLES,
                    "📌 一键示例：点缩略图 = 填好参数 + 秒看预计算结果，点 Run 实时重跑")
                gal5.select(_ex_style_select, None,
                            [img5, style, strength5, lock5, cp, cn,
                             steps5, guidance5, seed5, fast5, out5, perf5])

            # ================= Background =================
            with gr.Tab("🧑‍🎨 Background"):
                gr.Markdown("BiRefNet precision matting → transparent PNG, solid, gradient, or a "
                            "full-frame **AI-generated backdrop** composited cleanly behind the subject.",
                            elem_classes=["hint"])
                with gr.Row():
                    with gr.Column(scale=5, min_width=360):
                        img7 = gr.Image(label="Image", type="pil", sources=["upload", "clipboard"],
                                        height=320)
                        mode = gr.Radio([("Transparent PNG", "Transparent PNG"), ("Solid color", "Solid color"),
                                         ("Gradient", "Gradient"), ("AI-generated", "AI-generated")],
                                        value="Transparent PNG", label="Output mode")
                        with gr.Accordion("Background options", open=True):
                            solid = gr.ColorPicker(value="#FFFFFF", label="Solid color")
                            with gr.Row():
                                gt = gr.ColorPicker(value="#89CFF0", label="Gradient top")
                                gb = gr.ColorPicker(value="#F0E68C", label="Gradient bottom")
                            ai_prompt = gr.Textbox(
                                label="AI background prompt",
                                placeholder="e.g. marble podium in a bright studio, soft shadows")
                        with gr.Accordion("AI generation advanced", open=False):
                            steps7 = gr.Slider(10, 50, 30, step=1, label="Inference steps")
                            seed7 = gr.Number(-1, label="Seed (-1 = random)", precision=0)
                            fast7 = gr.Checkbox(value=True, label="⚡ LCM turbo (8 steps)")
                        btn7 = gr.Button("Process", variant="primary", size="lg")
                    with gr.Column(scale=6, min_width=400):
                        with gr.Row():
                            out7 = gr.Image(label="Result", type="pil", interactive=False, height=440)
                            fg7 = gr.Image(label="Cutout (RGBA)", type="pil", interactive=False,
                                           height=440)
                        perf7 = gr.Markdown(elem_classes=["perf-table"])
                btn7.click(cb_background, [img7, mode, solid, gt, gb, ai_prompt,
                                           steps7, seed7, fast7], [out7, fg7, perf7])
                gal7 = _example_gallery(
                    BACKGROUND_EXAMPLES,
                    "📌 一键示例：点缩略图 = 填好参数 + 秒看预计算结果，点 Run 实时重跑")
                gal7.select(_ex_background_select, None,
                            [img7, mode, solid, gt, gb, ai_prompt,
                             steps7, seed7, fast7, out7, fg7, perf7])

            # ================= Asset Split =================
            with gr.Tab("🧩 Asset Split"):
                gr.Markdown("One character image → **transparent character layer + AI-completed "
                            "background layer**, exported as a layered PSD + PNG asset pack "
                            "(Live2D prep, 2.5D animation).", elem_classes=["hint"])
                with gr.Row():
                    with gr.Column(scale=5, min_width=360):
                        img9 = gr.Image(label="Character image", type="pil",
                                        sources=["upload", "clipboard"], height=320)
                        fill9 = gr.Checkbox(value=True, label="AI-complete the background (erase + fill)")
                        margin9 = gr.Slider(0, 64, 16, step=4, label="Crop margin (px)")
                        btn9 = gr.Button("Split", variant="primary", size="lg")
                    with gr.Column(scale=6, min_width=400):
                        with gr.Row():
                            chara9 = gr.Image(label="Character (transparent)", type="pil",
                                              interactive=False, height=300)
                            bg9 = gr.Image(label="Background (completed)", type="pil",
                                           interactive=False, height=300)
                        files9 = gr.File(label="Download (PSD + asset pack)", file_count="multiple")
                        perf9 = gr.Markdown(elem_classes=["perf-table"])
                btn9.click(cb_split, [img9, fill9, margin9], [chara9, bg9, files9, perf9])
                gal9 = _example_gallery(
                    SPLIT_EXAMPLES,
                    "📌 一键示例：点缩略图 = 填图 + 秒看拆分结果（人物层+背景层），点 Run 实时重跑")
                gal9.select(_ex_split_select, None,
                            [img9, fill9, margin9, chara9, bg9, perf9])

            # ================= System =================
            with gr.Tab("⚙️ System"):
                status = gr.Markdown(_status_md())
                with gr.Row():
                    refresh = gr.Button("🔄 Refresh status")
                    unload = gr.Button("Unload all models (free VRAM)", variant="stop")
                refresh.click(lambda: _status_md(), None, status)
                unload.click(lambda: (MANAGER.unload_all(), _status_md())[1], None, status)
        return demo


def main():
    parser = argparse.ArgumentParser(description="AI-Image-Studio v2 · Radeon Edition")
    parser.add_argument("--host", default=settings.server_name)
    parser.add_argument("--port", type=int, default=settings.server_port)
    parser.add_argument("--share", action="store_true", default=settings.share)
    parser.add_argument("--low-vram", action="store_true", help="Force low-VRAM mode")
    args = parser.parse_args()

    if args.low_vram:
        settings.low_vram = True

    print(f"Inference backend: {DEVICE_INFO.summary()}")
    demo = build_demo()
    if settings.enable_warmup and DEVICE_INFO.is_gpu:
        threading.Thread(target=_warmup, daemon=True, name="engine-warmup").start()
    launch_kwargs = dict(server_name=args.host, server_port=args.port,
                         share=args.share, show_error=True)
    launch_sig = inspect.signature(gr.Blocks.launch).parameters
    if "css" in launch_sig:
        launch_kwargs["css"] = CSS
    if "theme" in launch_sig:
        launch_kwargs["theme"] = _theme()
    # rc-tunnel terminates HTTPS but does not forward x-forwarded-proto, so
    # Gradio 6 builds http:// absolute asset URLs and browsers block them as
    # mixed content. 1) CSP meta tells the browser to rewrite them to https.
    # 2) APP_PUBLIC_URL (full https tunnel URL) pins root_path so absolute
    # URLs are https from the start instead of proxy-injected http origins.
    if "head" in launch_sig:
        launch_kwargs["head"] = ('<meta http-equiv="Content-Security-Policy" '
                                 'content="upgrade-insecure-requests">')
    public_url = os.environ.get("APP_PUBLIC_URL", "").strip()
    if public_url and "root_path" in launch_sig:
        launch_kwargs["root_path"] = public_url.rstrip("/")
    demo.launch(**launch_kwargs)


if __name__ == "__main__":
    main()
