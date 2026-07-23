"""
Textovid — AI Comic Studio
Configuration & Constants
AMD AI DevMaster Hackathon 2026 — Track 1
"""

import os

# ── LLM API (Free Qwen/DeepSeek via Radeon Cloud) ──────────────────────
LLM_API_BASE = "https://developer.amd.com.cn/radeon/api/v1/chat/completions"
LLM_API_KEY = os.environ.get("TEXTOVID_API_KEY", "")   # or paste in UI
LLM_MODEL   = "Qwen3.6-35B-A3B"

# ── Image Model ─────────────────────────────────────────────────────────
IMAGE_MODEL_ID = "stabilityai/stable-diffusion-xl-base-1.0"
IMAGE_REFINER_ID = "stabilityai/stable-diffusion-xl-refiner-1.0"
# Faster alternative (if GPU VRAM < 12 GB):
# IMAGE_MODEL_ID = "stabilityai/stable-diffusion-xl-turbo"

# ── Video Model (LTX Video) ─────────────────────────────────────────────
VIDEO_MODEL_ID = "Lightricks/LTX-Video-0.9.1-dev"
VIDEO_ENABLED   = os.environ.get("TEXTOVID_ENABLE_VIDEO", "0") == "1"

# ── Default Generation Settings ─────────────────────────────────────────
DEFAULT_WIDTH       = 1024
DEFAULT_HEIGHT      = 1024
DEFAULT_STEPS       = 25          # 25 for quality; 4 for turbo
DEFAULT_CFG_SCALE   = 7.5
DEFAULT_SEED        = -1          # -1 = random
BATCH_SIZE          = 1
HIGH_RES_FIX       = True         # Enable 2x upscale after SDXL
HIGH_RES_DENOISE   = 0.35         # Denoising strength for hi-res pass

# ── 4K Comic Page Layout ────────────────────────────────────────────────
COMIC_PAGE_W        = 2480        # pixels  (A4 at 210 DPI ≈ 4K-ish)
COMIC_PAGE_H        = 3508        # A4 portrait ratio
PANEL_GAP           = 14          # px between panels
PANEL_BORDER_W      = 5
PANEL_BORDER_COLOR  = (10, 10, 30)
PAGE_MARGIN         = 48
PAGE_BG_COLOR       = (245, 245, 250)
TITLE_PAGE_ENABLED  = True

# ── Speech Bubble Settings ─────────────────────────────────────────────
BUBBLE_PADDING      = 16
BUBBLE_FONT_SIZE    = 32
BUBBLE_MAX_WIDTH    = 420
NARRATION_FONT_SIZE = 26
SFX_FONT_SIZE       = 56

# ── Output ──────────────────────────────────────────────────────────────
OUTPUT_DIR = "output"

# ── Category Options ────────────────────────────────────────────────────
GENRES = [
    "Superhero", "Horror", "Romance", "Sci-Fi", "Fantasy",
    "Mystery", "Comedy", "Drama", "Thriller", "Slice-of-Life",
]

SUB_GENRES = [
    "Dark Fantasy", "Space Opera", "Rom-Com", "Psychological Horror",
    "Cyberpunk", "Steampunk", "Urban Fantasy", "Gothic", "Noir",
    "Surrealism", "Post-Apocalyptic", "Mythic", "Solarpunk",
]

ART_STYLES = [
    "Manga (Japanese comic)", "Western Comic (Marvel/DC style)",
    "Watercolor Illustration", "Pixel Art", "Film Noir",
    "Chibi / Kawaii", "Hyperrealistic Digital Art", "Art Nouveau",
    "Woodblock Print (Ukiyo-e)", "Pop Art", "Grisaille (Monochrome)",
]

THEMES = [
    "Redemption", "Discovery", "Betrayal", "Friendship", "Survival",
    "Coming-of-Age", "Sacrifice", "Rebellion", "Love", "Identity",
]

MOODS = [
    "Dark", "Lighthearted", "Epic", "Intimate", "Surreal",
    "Gritty", "Whimsical", "Tense", "Melancholic", "Triumphant",
]

LENGTHS = {
    "Short  (3 pages)":  3,
    "Medium (5 pages)":  5,
    "Long   (8 pages)":  8,
}