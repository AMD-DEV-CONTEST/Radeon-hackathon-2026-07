"""Image generation via local stable-diffusion.cpp (FLUX.1-schnell Q4_0 GGUF).

Uses the exact setup in /mnt/data/zz/flux/ — sd-cli (CUDA build for the
RTX 4070) plus the quantized GGUF model — no diffusers/torch needed.

Each generation spawns a fresh sd-cli process; a lock serializes runs so
concurrent scene threads don't exhaust VRAM (one run needs ~8.75 GB while
the desktop holds ~2.9 GB of the 12 GB card).

Config via env vars:
  SDCPP_BIN       path to the sd-cli binary
  SDCPP_MODEL_DIR path to the models directory
  SDCPP_WIDTH     image width  (default 768 — 1024 OOMs with desktop running)
  SDCPP_HEIGHT    image height (default 768)
  SDCPP_STEPS     inference steps (default 4)
  SDCPP_MAX_VRAM  --max-vram budget in GB (default 10)
  SDCPP_BACKEND   --backend string (e.g. "diffusion=cuda,clip=cpu,vae=cuda,t5xxl=cpu").
                  Set to empty to omit the flag entirely (needed for newer sd.cpp
                  builds where the backend is compiled in — e.g. Vulkan builds).
"""

import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from .base import ImageProvider

DEFAULT_SD_CPP_DIR = "/mnt/data/zz/flux"
DEFAULT_BIN = os.path.join(DEFAULT_SD_CPP_DIR, "sd_cpp", "build", "bin", "sd-cli")
DEFAULT_MODEL_DIR = os.path.join(DEFAULT_SD_CPP_DIR, "models")

MODEL_FILES = {
    "diffusion": "flux1-schnell-Q4_0.gguf",
    "vae": "ae.safetensors",
    "clip_l": "clip_l.safetensors",
    "t5xxl": "t5xxl_fp16.safetensors",
}


class SdCppProvider(ImageProvider):
    """Generate images locally via stable-diffusion.cpp + FLUX.1-schnell Q4_0."""

    def __init__(
        self,
        bin_path: str | None = None,
        model_dir: str | None = None,
        width: int | None = None,
        height: int | None = None,
        steps: int | None = None,
        max_vram: int | None = None,
        seed: int = 42,
    ):
        self._bin = bin_path or os.environ.get("SDCPP_BIN") or DEFAULT_BIN
        self._model_dir = (
            model_dir or os.environ.get("SDCPP_MODEL_DIR") or DEFAULT_MODEL_DIR
        )
        # 4:3 aspect (960x720) so scene images match the video slide layout
        self._width = int(os.environ.get("SDCPP_WIDTH", width or 960))
        self._height = int(os.environ.get("SDCPP_HEIGHT", height or 720))
        self._steps = int(os.environ.get("SDCPP_STEPS", steps or 4))
        self._max_vram = int(os.environ.get("SDCPP_MAX_VRAM", max_vram or 10))
        self._backend = os.environ.get("SDCPP_BACKEND", None)
        self._seed = seed
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        return "Local sd-cpp (FLUX.1-schnell Q4_0)"

    @property
    def model_name(self) -> str:
        return "black-forest-labs/FLUX.1-schnell (Q4_0 GGUF via stable-diffusion.cpp)"

    # ── model file checks ────────────────────────────────────────────────

    def _model_paths(self) -> dict[str, str]:
        return {k: os.path.join(self._model_dir, v) for k, v in MODEL_FILES.items()}

    def _check_files(self) -> str | None:
        """Return an error string if the binary or model files are missing."""
        if not os.path.isfile(self._bin):
            return (
                f"sd-cli binary not found: {self._bin}\n"
                f"Set SDCPP_BIN or build stable-diffusion.cpp with CUDA."
            )
        for name, path in self._model_paths().items():
            if not os.path.isfile(path):
                return f"Model file missing: {path}"
        return None

    def _load_model(self):
        """No persistent pipeline — sd-cli loads per process. Just verify files."""
        err = self._check_files()
        if err:
            raise RuntimeError(err)

    # ── generation ───────────────────────────────────────────────────────

    def generate_image(self, prompt: str, scene_index: int = 0) -> str | None:
        err = self._check_files()
        if err:
            print(f"  Error: {err}")
            return None

        files = self._model_paths()
        temp_dir = Path(tempfile.mkdtemp(prefix=f"sdcpp_img_{scene_index}_"))
        out_path = str(temp_dir / f"scene_{scene_index:03d}.png")

        cmd = [
            self._bin,
            "--diffusion-model", files["diffusion"],
            "--vae", files["vae"],
            "--clip_l", files["clip_l"],
            "--t5xxl", files["t5xxl"],
            "--prompt", prompt,
            "--cfg-scale", "1.0",
            "--sampling-method", "euler",
            "--steps", str(self._steps),
            "--width", str(self._width),
            "--height", str(self._height),
            "--seed", str(self._seed),
            "--output", out_path,
            "--vae-tiling",
            "--max-vram", str(self._max_vram),
        ]
        # Newer sd.cpp builds compile the backend in (e.g. Vulkan) and reject
        # --backend. Omit it when SDCPP_BACKEND is set to empty; otherwise
        # default to the CUDA backend string for classic builds.
        if self._backend is None:
            self._backend = "diffusion=cuda,clip=cpu,vae=cuda,t5xxl=cpu"
        if self._backend:
            cmd += ["--backend", self._backend]

        print(
            f"  Generating image via sd-cpp "
            f"({self._width}x{self._height}, {self._steps} steps)..."
        )
        t0 = time.time()
        with self._lock:  # serialize: each run needs most of the GPU
            result = subprocess.run(cmd, capture_output=True, text=True)
        elapsed = time.time() - t0

        if result.returncode != 0:
            tail = "\n".join(
                line
                for line in result.stderr.splitlines()
                if "ERROR" in line or "error" in line or "failed" in line
            )
            print(f"  sd-cpp failed (rc={result.returncode}):")
            print(f"    {(tail or result.stderr[-1500:])[:2000]}")
            return None

        if not os.path.isfile(out_path):
            print(f"  sd-cpp reported success but no output file at {out_path}")
            return None

        print(f"  Image generated in {elapsed:.1f}s: {out_path}")
        return out_path
