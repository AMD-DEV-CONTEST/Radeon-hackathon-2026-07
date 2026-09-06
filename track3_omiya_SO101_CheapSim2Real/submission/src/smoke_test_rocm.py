"""Verify the whole simulation pipeline runs on a headless ROCm host.

Everything an evaluator needs is reproducible without the physical arm, but only if
Genesis can rasterise offscreen on this machine. Genesis' pyrender path defaults to a
pyglet window, which on a headless Linux box dies with
``IndexError: list index out of range`` from ``display.get_default_screen()``.
Set ``PYOPENGL_PLATFORM=egl`` (or ``osmesa``) before importing genesis; this script
checks that and reports which stages are usable.

Run:  python -m src.smoke_test_rocm
"""
from __future__ import annotations

import os
import sys
import traceback

CHECKS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    CHECKS.append((name, ok, detail))
    print(f"[{'OK ' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""), flush=True)


def check_torch() -> None:
    try:
        import torch
        ok = torch.cuda.is_available()
        name = torch.cuda.get_device_name(0) if ok else "no device"
        record("torch + ROCm", ok, f"{torch.__version__} / {name}")
    except Exception as exc:
        record("torch + ROCm", False, repr(exc))


def check_headless_gl() -> None:
    plat = os.environ.get("PYOPENGL_PLATFORM", "")
    if not plat:
        os.environ["PYOPENGL_PLATFORM"] = "egl"
        plat = "egl (set by this script)"
    record("PYOPENGL_PLATFORM", True, plat)


def check_genesis_build() -> None:
    """Build the SO-101 scene with cameras attached — the step data collection needs."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import genesis as gs
        from build_scene_so101 import build_scene_so101

        gs.init(backend=gs.cpu)      # physics backend is irrelevant to the render check
        bundle = build_scene_so101(show_viewer=False)
        record("Genesis scene build", True, "SO-101 + table + cube")

        out = bundle.render(rgb=True)
        shapes = {k: (None if v is None else getattr(v[0], "shape", None))
                  for k, v in out.items()}
        ok = all(s is not None for s in shapes.values())
        record("offscreen render (both cameras)", ok, str(shapes))
    except Exception as exc:
        record("Genesis scene build / render", False,
               f"{type(exc).__name__}: {exc}")
        traceback.print_exc()


def main() -> None:
    print("=== SO-101 pipeline smoke test (headless ROCm) ===\n", flush=True)
    check_headless_gl()
    check_torch()
    check_genesis_build()

    print()
    failed = [n for n, ok, _ in CHECKS if not ok]
    if failed:
        print(f"SMOKE_FAIL — {len(failed)} check(s) failed: {', '.join(failed)}")
        print("\nIf the render check failed, try:  PYOPENGL_PLATFORM=osmesa python -m src.smoke_test_rocm")
        sys.exit(1)
    print("SMOKE_OK — data collection, training and sim evaluation are all runnable here")


if __name__ == "__main__":
    main()
