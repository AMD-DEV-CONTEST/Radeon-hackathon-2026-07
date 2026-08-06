from pathlib import Path
import torch

PROJECT_ROOT = Path(__file__).resolve().parent.parent

GENERATED_DIR = PROJECT_ROOT / "backend" / "generated"

MODEL_CONFIG = {
    "qwen": {
        "name": "Qwen/Qwen2.5-VL-3B-Instruct",
        "dtype": torch.float16,
    },
    "flux": {
        "name": "black-forest-labs/FLUX.1-schnell",
    },
    "kokoro": {
        "name": "hexgrad/Kokoro-82M",
    },
}

DEVICE = "cuda"