"""Application configuration — loaded from environment variables with defaults."""
import os
from dotenv import load_dotenv

load_dotenv()

# ── Google AI Studio (Gemma 4) ───────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemma-4-26b-a4b-it")

# ── Kokoro TTS (local, free, no API key) ─────────────────────
KOKORO_LANG = os.getenv("KOKORO_LANG", "a")  # a = American English, b = British
KOKORO_VOICE = os.getenv("KOKORO_VOICE", "af_bella")
KOKORO_SAMPLE_RATE = int(os.getenv("KOKORO_SAMPLE_RATE", "24000"))
KOKORO_OUTPUT_DIR = os.getenv("KOKORO_OUTPUT_DIR", "audio_output")

# ── Limits ────────────────────────────────────────────────────
MAX_IMAGE_BYTES = 20 * 1024 * 1024  # 20 MB
MAX_TOKENS_TEXT = 2048
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif", "image/jpg"}

# ── CORS ─────────────────────────────────────────────────────
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")

# ── Server ────────────────────────────────────────────────────
DEBUG = os.getenv("DEBUG", "false").lower() in ("1", "true", "yes")
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
