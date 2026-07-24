# -*- coding: utf-8 -*-
"""Textovid — Configuration Constants"""

import os

# ── Paths ──────────────────────────────────────────────────────────────
WORKSPACE = "/workspace/textovid"
OUTPUT_DIR = os.path.join(WORKSPACE, "outputs")
MODEL_CACHE = os.path.expanduser("~/.cache/huggingface/hub")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ── Model IDs (HuggingFace) ───────────────────────────────────────────
SDXL_BASE = "stabilityai/stable-diffusion-xl-base-1.0"
SDXL_REFINER = "stabilityai/stable-diffusion-xl-refiner-1.0"
LTX_VIDEO = "Lightricks/LTX-Video-0.9.5-dev"

# ── LLM API (Radeon Cloud — Qwen 35B) ────────────────────────────────
LLM_API_URL = os.environ.get(
    "LLM_API_URL",
    "https://cloud.radeon.com/api/v1/chat/completions",
)
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "Qwen/Qwen2.5-72B-Instruct")

# ── Image generation ──────────────────────────────────────────────────
IMG_WIDTH = 1024
IMG_HEIGHT = 1024
HIGHRES_SCALE = 2.0          # upscale to ~2048 px
HIGHRES_DENOISING = 0.35
NUM_INFERENCE_STEPS = 30
GUIDANCE_SCALE = 7.5
REFINER_STEPS = 25
REFINER_GUIDANCE = 7.0

# ── Comic page assembly ──────────────────────────────────────────────
PAGE_W = 2480                # A4 at 300 DPI
PAGE_H = 3508
PANELS_PER_PAGE = 4
GUTTER = 40                  # px between panels
MARGIN = 60                  # px page margin
BUBBLE_FONT_SIZE = 28
SFX_FONT_SIZE = 72
BUBBLE_PADDING = 20

# ── Uniqueness ───────────────────────────────────────────────────────
HASH_LENGTH = 32             # SHA-256 hex chars used in fingerprint

# ── Misc ──────────────────────────────────────────────────────────────
GRADIO_SERVER_NAME = "0.0.0.0"
GRADIO_SERVER_PORT = 7860
MAX_SEED = 2**32 - 1
