# -*- coding: utf-8 -*-
"""Regenerate ALL pre-computed example results with the final v8 pipelines.

These land in assets/examples/results/ and are shown INSTANTLY when a judge
clicks an example thumbnail (the app still re-runs live on Run).
"""
import sys
import time
from pathlib import Path

from PIL import Image

sys.path.insert(0, "/workspace/persistent/AI-Image-Studio-v8")
from config import settings
from src.device import detect_device
from src.model_manager import ModelManager
from src.pipelines.inpaint import run_recolor, run_recolor_multi
from src.pipelines.outpaint import run_outpaint
from src.pipelines.style import run_style
from src.pipelines.background import run_background
from src.pipelines.split import run_split
from src.pipelines.remove import run_remove
from src.watermark import detect_watermark

EX = Path("/workspace/persistent/AI-Image-Studio-v8/assets/examples")
RES = EX / "results"
RES.mkdir(parents=True, exist_ok=True)
DBG = Path("/tmp/gradio/fetch")
DBG.mkdir(parents=True, exist_ok=True)

OUTPAINT_SEED = 123  # curated: bed + pillows continue the cozy bedroom, no ghost limbs
BG_PROMPT = ("sunny beach and blue sea, clear sky, soft natural light, "
             "photorealistic")

info = detect_device(settings.device, settings.dtype)
mgr = ModelManager(info, settings)


def step(name, fn):
    t0 = time.time()
    try:
        fn()
        print(f"[{name}] {time.time()-t0:.0f}s OK", flush=True)
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[{name}] FAILED {type(e).__name__}: {e}", flush=True)


def do_inpaint_dress():
    img = Image.open(EX / "inpaint_dress.jpg")
    msk = Image.open(EX / "inpaint_dress_mask.png").convert("L")
    res, _ = run_recolor(img, msk, "light blue", region="dress")
    res.save(RES / "inpaint_dress.jpg", quality=92)


def do_inpaint_multi():
    img = Image.open(EX / "inpaint_multi.jpg")
    msk = Image.open(EX / "inpaint_multi_mask.png").convert("L")
    res, _ = run_recolor_multi(
        img, msk, [{"region": "hair", "color": "black"},
                   {"region": "coat", "color": "purple"}])
    res.save(RES / "inpaint_multi.jpg", quality=92)


def do_remove(fname):
    from src.watermark import snap_to_overlay
    img = Image.open(EX / fname)
    mask, info = detect_watermark(img)
    expand = 8
    if mask is None:
        # auto-detect abstained -> simulate the app's fallback path: rough
        # brush over the bottom-right band, then smart-snap onto the strokes
        from PIL import ImageDraw
        w, h = img.size
        rough = Image.new("L", (w, h), 0)
        ImageDraw.Draw(rough).rectangle(
            [int(w * 0.55), int(h * 0.88), w, h], fill=255)
        mask, sinfo = snap_to_overlay(img, rough)
        if sinfo.get("mode") == "snapped":
            expand = 6
        print(f"  [{fname}] auto-detect abstained; rough-brush+snap "
              f"({sinfo.get('mode')})", flush=True)
    out, _ = run_remove(mgr, img, mask, expand_px=expand)
    out.save(RES / fname, quality=92)


def do_outpaint():
    img = Image.open(EX / "outpaint_room.jpg")
    prompt = ("cozy girl's bedroom, beige walls, dark wooden wardrobe and "
              "wooden floor, soft natural daylight, continue the original "
              "room scene, empty corner, no people")
    res, _, _ = run_outpaint(mgr, img, 256, 0, 0, 0, prompt,
                             steps=30, guidance=7.5, seed=OUTPAINT_SEED,
                             fast=False)
    res.save(RES / "outpaint_room.jpg", quality=92)


def do_style():
    img = Image.open(EX / "style_anime.jpg")
    res, _, _ = run_style(mgr, img, "Anime", fast=False, structure_lock=True,
                          strength=0.5, steps=30, guidance=7.0, seed=42)
    res.save(RES / "style_anime.jpg", quality=92)


def do_background():
    img = Image.open(EX / "bg_beach.jpg")
    res, fg, _ = run_background(mgr, img, mode="AI-generated",
                                ai_prompt=BG_PROMPT, steps=30, seed=42,
                                fast=False)
    res.convert("RGB").save(RES / "bg_ai.jpg", quality=92)
    fg.save(RES / "bg_cutout.png")


def do_split():
    img = Image.open(EX / "split_hat.jpg")
    char, bg, _, _ = run_split(mgr, img, fill_bg=True)
    char.save(RES / "split_char.png")
    bg.convert("RGB").save(RES / "split_bg.jpg", quality=92)


step("inpaint_dress", do_inpaint_dress)
step("inpaint_multi", do_inpaint_multi)
step("remove_orange", lambda: do_remove("remove_orange.jpg"))
import os
if os.environ.get("GEN_PARTIAL", "1") == "0":
    step("remove_silver", lambda: do_remove("remove_silver.jpg"))
    step("outpaint", do_outpaint)
    step("style", do_style)
step("background", do_background)   # cutout quality depends on birefnet.py
step("split", do_split)             # char layer depends on birefnet.py
print("PRECOMPUTE_DONE", flush=True)
