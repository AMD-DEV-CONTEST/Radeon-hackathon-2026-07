from pathlib import Path

MODEL_NAME = "stable-diffusion-v1-5/stable-diffusion-v1-5"

DEVICE = "cuda"

DEFAULT_STEPS = 25
DEFAULT_GUIDANCE_SCALE = 7.5

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "outputs"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

