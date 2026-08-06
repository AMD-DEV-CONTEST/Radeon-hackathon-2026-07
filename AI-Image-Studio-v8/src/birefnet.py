# -*- coding: utf-8 -*-
"""BiRefNet matting helper (shared by background / asset split)."""
from __future__ import annotations

import numpy as np
import torch
from PIL import Image
from torchvision import transforms


# --- ROCm compat: torchvision deform_conv2d CPU detour ---------------------
# The ROCm torchvision wheel ships no HIP kernel for torchvision::deform_conv2d
# (BiRefNet matting needs it — the op is registered for CPU only). Detour just
# that op through the CPU in fp32 while the rest of the network stays on GPU:
# matting costs a few extra seconds, everything else is untouched. On builds
# where the kernel exists this shim never fires. Signature-agnostic on
# purpose: it survives torchvision version differences.
# Lives here (not in app.py) so EVERY entry point — the Gradio app, backend
# scripts and test suites — gets the detour, not just the web process.
def _patch_torchvision_deform_conv():
    try:
        import torchvision.ops
        import torchvision.ops.deform_conv as _dc_mod
    except Exception:
        return

    orig_fn = torchvision.ops.deform_conv2d
    if getattr(orig_fn, "_aistudio_detoured", False):
        return

    def _cast(t):
        return t.detach().to("cpu", torch.float32) if torch.is_tensor(t) else t

    def _detour_python(args, kwargs):
        """Fallback for python-level calls. Handles positional AND keyword
        call styles (BiRefNet's remote code passes kwargs)."""
        src = args[0] if args else kwargs.get("input")
        if not torch.is_tensor(src):  # last resort: any tensor argument
            src = next((a for a in list(args) + list(kwargs.values())
                        if torch.is_tensor(a)), None)
        dev, dt = (src.device, src.dtype) if src is not None else ("cpu", None)
        out = orig_fn(*[_cast(a) for a in args],
                      **{k: _cast(v) for k, v in kwargs.items()})
        return out.to(device=dev, dtype=dt) if dt is not None else out

    def wrapped(*args, **kwargs):
        input = args[0] if args else kwargs.get("input")
        if input is None or not input.is_cuda:
            return orig_fn(*args, **kwargs)
        try:
            return orig_fn(*args, **kwargs)
        except NotImplementedError:
            return _detour_python(args, kwargs)

    import functools
    functools.update_wrapper(wrapped, orig_fn)  # keep introspection intact
    wrapped._aistudio_detoured = True
    torchvision.ops.deform_conv2d = wrapped
    _dc_mod.deform_conv2d = wrapped  # DeformConv2d.forward resolves it here

    # Belt and braces: fill the missing dispatcher kernel so torch.ops-level
    # and early-bound callers are covered as well — but ONLY after a probe
    # proves the HIP kernel is really absent (never override an existing one).
    try:
        if torch.cuda.is_available():
            try:
                orig_fn(torch.zeros(1, 1, 4, 4, device="cuda"),
                        torch.zeros(1, 2, 4, 4, device="cuda"),
                        torch.zeros(1, 1, 1, 1, device="cuda"))
            except NotImplementedError:
                # NOTE: the Library object MUST be kept alive — its destructor
                # unregisters the impl. Stashing it on `wrapped` (itself held
                # by torchvision.ops) keeps the CUDA impl registered for the
                # process lifetime.
                lib = torch.library.Library("torchvision", "IMPL")

                def _cuda_impl(*args):  # args in torch.ops schema order
                    dev, dt = args[0].device, args[0].dtype
                    out = torch.ops.torchvision.deform_conv2d(
                        *[_cast(a) for a in args])  # CPU -> native kernel
                    return out.to(device=dev, dtype=dt)

                lib.impl("deform_conv2d", _cuda_impl, "CUDA")
                wrapped._detour_lib = lib  # pin: prevents GC unregister
                print("[compat] torchvision::deform_conv2d has no HIP kernel -> "
                      "armed CPU detour (BiRefNet matting)")
    except Exception as e:
        print(f"[compat] dispatcher probe/registration skipped ({e}); "
              "python-level detour armed")


_patch_torchvision_deform_conv()


def _transform(size: int):
    return transforms.Compose([
        transforms.Resize((size, size)),
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
    ])


@torch.no_grad()
def matte(manager, image: Image.Image) -> Image.Image:
    """Return the alpha matte (L mode, original size) for the foreground."""
    model = manager.get_birefnet()
    size = int(getattr(manager.settings, "matte_size", 1024))
    x = _transform(size)(image.convert("RGB")).unsqueeze(0).to(manager.info.device)
    if manager.info.is_gpu:
        x = x.half()
    pred = model(x)[-1].sigmoid().squeeze().float().cpu().numpy()
    pred = (pred - pred.min()) / max(pred.max() - pred.min(), 1e-8)
    # round() not truncate: 254.999 -> 255 so opaque cores stay fully opaque
    alpha = Image.fromarray(np.rint(pred * 255).astype(np.uint8), "L")
    return alpha.resize(image.size, Image.BILINEAR)


def _decontaminate(rgb: Image.Image, alpha: Image.Image) -> Image.Image:
    """Remove background color bleeding from the alpha edge (the 'blue ghost
    blobs around flying hair' failure). Semi-transparent matte pixels hold a
    MIX of foreground and background color; estimate the background color
    under the edge (inpaint the pure-background ring inwards) and unblend:
        fg = (observed - (1-a)*bg_est) / a
    Pixels whose recovered color is still ~the background are pure haze —
    their alpha is crushed so the cutout doesn't carry a colored ghost."""
    import cv2
    arr = np.asarray(rgb.convert("RGB"))
    a = np.asarray(alpha).astype(np.float32) / 255.0
    est_mask = np.where(a < 0.03, 0, 255).astype(np.uint8)
    if est_mask.max() == 0:
        return rgb.convert("RGBA")
    bg_est = cv2.inpaint(arr, est_mask, 9, cv2.INPAINT_NS).astype(np.float32)
    obs = arr.astype(np.float32)
    af = np.clip(a, 0.08, 1.0)[..., None]
    # unblend with bounded correction: at wispy alpha the 1/a term amplifies
    # JPEG noise into rainbow garbage — cap the per-channel shift and blend
    # the correction in only where the matte is solid enough to trust it.
    raw = (obs - (1 - af) * bg_est) / af
    unblend = np.clip(obs + np.clip(raw - obs, -60.0, 60.0), 0, 255)
    w = np.clip((a - 0.15) / 0.5, 0.0, 1.0)[..., None]
    semi = ((a > 0.03) & (a < 0.97))[..., None]
    out_rgb = np.where(semi, obs * (1 - w) + unblend * w, obs)
    diff = np.linalg.norm(out_rgb - bg_est, axis=-1)
    a2 = a.copy()
    a2[(a > 0.03) & (a < 0.97) & (diff < 18)] *= 0.25   # bg haze -> mostly gone
    # colored-background leakage: the matte over-claims background BETWEEN
    # flying hair strands as solid foreground (the 'blue swirl' blobs).
    # If a pixel's color ≈ a SATURATED bg estimate, it is mostly background
    # regardless of what the matte says — crush its alpha.  White/grey
    # backgrounds (low colorfulness) skip this, so a white dress on a white
    # wall is never eaten.
    bg_chroma = bg_est.max(-1) - bg_est.min(-1)
    leak = (diff < 26) & (bg_chroma > 40)
    a2[leak] = a2[leak] * np.clip(diff[leak] / 26.0, 0.05, 1.0)
    a2[a < 0.03] = 0.0
    fg = Image.fromarray(out_rgb.astype(np.uint8), "RGB").convert("RGBA")
    fg.putalpha(Image.fromarray(np.rint(a2 * 255).astype(np.uint8), "L"))
    return fg


@torch.no_grad()
def cutout(manager, image: Image.Image):
    """Return (fg_rgba, alpha) — foreground with transparent background."""
    from .utils import to_rgb_white
    rgb = to_rgb_white(image)
    alpha = matte(manager, rgb)
    return _decontaminate(rgb, alpha), alpha
