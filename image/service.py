"""Resident Z-Image-Turbo text-to-image service (diary image enrichment).

Runs in the `.venv_aitk` env (separate from the diary `.venv`), loads Z-Image-Turbo
ONCE via the ai-toolkit loader, and serves `POST /generate` over localhost. The diary
env NEVER imports this module or ai-toolkit — it only talks HTTP to this service and
to the 35B judge at `:8089`. Model stays resident so repeated thumbnail/poster calls
don't pay the ~30s load each time.

VRAM: Z-Image-Turbo ~14-18GB on gfx1100 (ROCm 7.2.1). Coexists with the ~20GB
llama-server and the ~0.9GB mmproj within the 51.5GB budget. Set
`PYTORCH_ALLOC_CONF=expandable_segments:True` to avoid fragmentation OOM.

Endpoints:
  POST /generate  {prompt, w, h, cfg, steps, seed, lora?, lora_scale?, out?}
                   -> PNG bytes (image/png). If `out` is given and the file already
                      exists, it is returned without regenerating (resume/skip).
  GET  /health    -> {"status":"ok"|"loading"|"error", ...}
"""

from __future__ import annotations

import io
import os
import sys
import threading
import time

import torch
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from PIL import Image
from pydantic import BaseModel

# --- ai-toolkit on the path (same layout as run_zimage_i2i.py) ----------
ROOT = "/home/pdfexe/dataset"
AITK = os.path.join(ROOT, "tools", "ai-toolkit")
if AITK not in sys.path:
    sys.path.insert(0, AITK)

from toolkit.config_modules import ModelConfig  # noqa: E402
from toolkit.stable_diffusion_model import StableDiffusion  # noqa: E402
from toolkit.util.get_model import get_model_class  # noqa: E402
from diffusers import ZImagePipeline  # noqa: E402

# --- weights / defaults (mirror image.md + run_zimage_i2i.py) -----------
BASE = os.environ.get("ZIMAGE_BASE", "/home/pdfexe/dataset/models/zimage_turbo_rebuild")
EXTRAS = os.environ.get("ZIMAGE_EXTRAS", "/home/pdfexe/dataset/models/zimage_turbo_extras")
ASSISTANT = os.environ.get(
    "ZIMAGE_ASSISTANT",
    "/home/pdfexe/dataset/models/zimage_turbo_rebuild/"
    "beyondREALITY_zTURBOREBUILDV30-adapter.safetensors",
)
# Optional PERSON LoRA merged into the resident transformer at startup (Phase C).
# Leave "none"/unset for the generic MVP service. Per-request lora is NOT supported
# because merge_lora() mutates the transformer in place (a process-global change).
STARTUP_LORA = os.environ.get("ZIMAGE_LORA", "none")
STARTUP_LORA_SCALE = float(os.environ.get("ZIMAGE_LORA_SCALE", "1.0"))

NEG = "blurry, low quality, deformed, extra limbs, bad anatomy"
DTYPE = "bf16"
DEVICE = "cuda:0"

# Quality note from image.md: keep the long edge <= 2048 (quality degrades past it).
MAX_LONG_EDGE = 2048
MIN_SHORT_EDGE = 512  # Z-Image native-ish floor; below this detail collapses.

app = FastAPI(title="Z-Image-Turbo diary service")

# One generation at a time: the transformer + VAE resident on the same GPU as the
# llama-server, so we must not let two requests race the weights / spike VRAM.
_gen_lock = threading.Lock()
_state = {"pipe": None, "status": "loading", "error": None, "loaded_at": None,
          "lora_merged": None}


class GenerateRequest(BaseModel):
    prompt: str
    w: int = 1024
    h: int = 1280
    cfg: float = 1.2          # Turbo distilled: guidance = cfg - 1 (~0.2)
    steps: int = 8            # Turbo distilled: 8 steps is the quality/speed sweet spot
    seed: int = 42
    lora: str | None = None   # accepted but, if set, merged once into resident weights
    lora_scale: float = 1.0
    out: str | None = None    # if set + exists -> return it; else save result here


def _clamp_resolution(w: int, h: int) -> tuple[int, int]:
    """Clamp to the safe Z-Image window (short>=512, long<=2048), keep aspect."""
    w = max(MIN_SHORT_EDGE, int(w))
    h = max(MIN_SHORT_EDGE, int(h))
    long_e, short_e = max(w, h), min(w, h)
    if long_e > MAX_LONG_EDGE:
        scale = MAX_LONG_EDGE / long_e
        w, h = int(round(w * scale)), int(round(h * scale))
    # Z-Image prefers multiples of 16 for the VAE tile grid.
    w = max(16, (w // 16) * 16)
    h = max(16, (h // 16) * 16)
    return w, h


def merge_lora(transformer, lora_path: str, scale: float = 1.0) -> int:
    """Merge an ai-toolkit Z-Image LoRA into the transformer weights in place.

    ai-toolkit's `arch="zimage"` loader ignores `model_config.lora_path`, so the
    LoRA is applied by hand (copied verbatim from run_zimage_i2i.py). rank==alpha==32
    for these LoRAs, so scale 1.0 is the identity-preserving merge. Returns #merged.
    """
    from safetensors.torch import load_file

    sd = load_file(lora_path)
    mods = dict(transformer.named_modules())
    merged = missing = 0
    for key in sorted(sd):
        if not key.endswith(".lora_A.weight"):
            continue
        stem = key[: -len(".lora_A.weight")].replace("diffusion_model.", "")
        mod = mods.get(stem)
        if mod is None or not hasattr(mod, "weight"):
            missing += 1
            continue
        a = sd[key]
        b = sd[key.replace(".lora_A.", ".lora_B.")]
        w = mod.weight
        delta = (b.to(torch.float32) @ a.to(torch.float32)) * scale
        if delta.shape != tuple(w.shape):
            missing += 1
            continue
        with torch.no_grad():
            w.add_(delta.to(w.device, dtype=w.dtype))
        merged += 1
    if merged == 0:
        raise RuntimeError(f"LoRA {lora_path} matched no transformer modules")
    return merged


def _load_model():
    """Load Z-Image-Turbo once (called at startup)."""
    t0 = time.time()
    use_assistant = bool(ASSISTANT) and ASSISTANT.lower() != "none"
    model_config = ModelConfig(
        name_or_path=BASE, arch="zimage",
        extras_name_or_path=EXTRAS, dtype=DTYPE,
        assistant_lora_path=ASSISTANT if use_assistant else None,
    )
    ModelClass = get_model_class(model_config)
    sd = ModelClass(device=DEVICE, model_config=model_config, dtype=model_config.dtype)
    sd.load_model()
    # ai-toolkit's own `sd.pipeline` is a subclass whose `.device` resolves wrongly
    # (text-encoder / scheduler on a different device), which makes the T2I forward
    # trip a CPU/CUDA mismatch. Rebuild a clean diffusers ZImagePipeline from the
    # already-loaded components — the exact pattern run_zimage_i2i.py uses for i2i
    # (there the freshly-built pipeline works; relying on sd.pipeline does not).
    src = sd.pipeline
    pipe = ZImagePipeline(
        scheduler=src.scheduler,
        vae=src.vae,
        text_encoder=src.text_encoder,
        tokenizer=src.tokenizer,
        transformer=src.transformer,
    ).to(DEVICE)
    if use_assistant and getattr(sd, "invert_assistant", False):
        # Only relevant when canceling the de-distill adapter; not used here.
        pass

    # Optional fixed person LoRA (Phase C). Merged once into resident weights.
    lora_name = None
    if STARTUP_LORA and STARTUP_LORA.lower() != "none" and os.path.isfile(STARTUP_LORA):
        merge_lora(pipe.transformer, STARTUP_LORA, STARTUP_LORA_SCALE)
        lora_name = STARTUP_LORA

    _state["pipe"] = pipe
    # ai-toolkit keeps the (de-distill / assistant) LoRA network alive only via a
    # weakref; if `sd` is dropped, the network is GC'd and the transformer forward
    # crashes with "'NoneType' object has no attribute 'is_lorm'". Keep it alive.
    _state["sd"] = sd
    _state["lora_merged"] = lora_name
    _state["status"] = "ok"
    _state["loaded_at"] = time.time()
    print(f"[zimage] model ready in {time.time() - t0:.1f}s"
          + (f" (+person LoRA {os.path.basename(lora_name)})" if lora_name else ""),
          flush=True)


def _generate(req: GenerateRequest) -> bytes:
    """Run one T2I and return PNG bytes. Caller holds _gen_lock."""
    pipe = _state["pipe"]
    if pipe is None:
        raise HTTPException(status_code=503, detail="model not loaded yet")

    # Resume: if a target path is given and it already exists, return it as-is.
    if req.out and os.path.isfile(req.out):
        with open(req.out, "rb") as f:
            return f.read()

    w, h = _clamp_resolution(req.w, req.h)
    guidance = max(0.0, req.cfg - 1.0)
    generator = torch.Generator(device="cpu").manual_seed(int(req.seed))

    with torch.inference_mode():
        out = pipe(
            prompt=req.prompt,
            negative_prompt=NEG,
            height=h,
            width=w,
            num_inference_steps=req.steps,
            guidance_scale=guidance,
            generator=generator,
            output_type="pil",
        )
    img: Image.Image = out.images[0]

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    data = buf.getvalue()
    if req.out:
        os.makedirs(os.path.dirname(os.path.abspath(req.out)), exist_ok=True)
        with open(req.out, "wb") as f:
            f.write(data)
    return data


@app.on_event("startup")
def _startup():
    try:
        _load_model()
    except Exception as e:  # keep the server up so /health reports the failure
        _state["status"] = "error"
        _state["error"] = f"{type(e).__name__}: {e}"
        import traceback
        traceback.print_exc()


@app.get("/health")
def health():
    return {
        "status": _state["status"],
        "error": _state["error"],
        "device": DEVICE,
        "lora_merged": _state["lora_merged"],
        "loaded_at": _state["loaded_at"],
    }


@app.post("/generate")
def generate(req: GenerateRequest):
    if req.steps <= 0 or req.steps > 50:
        raise HTTPException(status_code=400, detail="steps must be in (0, 50]")
    if not req.prompt or not req.prompt.strip():
        raise HTTPException(status_code=400, detail="prompt required")
    if _state["status"] != "ok":
        raise HTTPException(status_code=503, detail=f"model not ready: {_state['error']}")
    try:
        with _gen_lock:
            data = _generate(req)
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"generation failed: {e}")
    return Response(content=data, media_type="image/png")


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("ZIMAGE_PORT", "8090"))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
