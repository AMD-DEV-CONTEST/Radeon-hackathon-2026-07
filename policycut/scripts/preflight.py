#!/usr/bin/env python3
"""PolicyCut environment preflight check.

Reports on Python, PyTorch (ROCm/HIP or CUDA), GPU matmul smoke test with
timing, ffmpeg/ffprobe, model cache presence, OpenCV and Presidio.

Prints a PASS/FAIL table. Exits 1 when a CORE requirement is missing.
Core requirements: python>=3.10, torch, ffmpeg, ffprobe, opencv.
GPU, model caches and presidio are reported as WARN when missing (the app
degrades gracefully without them, but the demo needs the GPU + models).

Usage:
    python scripts/preflight.py
    python scripts/preflight.py --json            # also write artifacts/benchmarks/preflight.json
    python scripts/preflight.py --json /tmp/p.json
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_JSON = PROJECT_ROOT / "artifacts" / "benchmarks" / "preflight.json"

HF_MODEL_IDS = [
    "IDEA-Research/grounding-dino-tiny",
    "Qwen/Qwen3-4B-Instruct-2507",
    "openai/whisper-large-v3-turbo",
    "facebook/sam2.1-hiera-small",
]
YUNET_PATH = PROJECT_ROOT / "models" / "face_detection_yunet_2023mar.onnx"

PASS, FAIL, WARN = "PASS", "FAIL", "WARN"


class Check:
    def __init__(self, name: str, status: str, detail: str, core: bool):
        self.name = name
        self.status = status
        self.detail = detail
        self.core = core

    def as_dict(self) -> dict:
        return {"name": self.name, "status": self.status, "detail": self.detail, "core": self.core}


def check_python() -> Check:
    ver = sys.version_info
    detail = f"{platform.python_version()} ({sys.executable})"
    ok = (ver.major, ver.minor) >= (3, 10)
    return Check("python >= 3.10", PASS if ok else FAIL, detail, core=True)


def check_torch() -> tuple[Check, list[Check], object]:
    """Returns (torch check, gpu-related checks, torch module or None)."""
    try:
        import torch  # lazy heavy import
    except Exception as exc:
        return (
            Check("torch", FAIL, f"import failed: {exc}", core=True),
            [Check("gpu", WARN, "torch unavailable, cannot probe GPU", core=False)],
            None,
        )

    hip = getattr(torch.version, "hip", None)
    cuda = getattr(torch.version, "cuda", None)
    backend = f"hip={hip}" if hip else (f"cuda={cuda}" if cuda else "cpu-only build")
    torch_check = Check("torch", PASS, f"{torch.__version__} ({backend})", core=True)

    gpu_checks: list[Check] = []
    try:
        available = torch.cuda.is_available()
    except Exception as exc:
        available = False
        gpu_checks.append(Check("gpu available", WARN, f"torch.cuda probe failed: {exc}", core=False))

    if available:
        try:
            name = torch.cuda.get_device_name(0)
        except Exception:
            name = "unknown device"
        gpu_checks.append(Check("gpu available", PASS, f"{name} ({'ROCm/HIP' if hip else 'CUDA'})", core=False))
        gpu_checks.append(check_gpu_matmul(torch))
    else:
        gpu_checks.append(Check("gpu available", WARN, "torch.cuda.is_available() == False (CPU fallback)", core=False))
    return torch_check, gpu_checks, torch


def check_gpu_matmul(torch) -> Check:
    """Smoke-test a fp16 matmul on the GPU and time it."""
    n = 2048
    reps = 10
    try:
        a = torch.randn(n, n, device="cuda", dtype=torch.float16)
        b = torch.randn(n, n, device="cuda", dtype=torch.float16)
        for _ in range(3):  # warmup
            (a @ b)
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        for _ in range(reps):
            c = a @ b
        torch.cuda.synchronize()
        dt = time.perf_counter() - t0
        del c
        checksum_ok = True  # if we got here without exception the kernel ran
        tflops = (2 * n**3 * reps) / dt / 1e12
        detail = f"{n}x{n} fp16 x{reps}: {dt * 1000:.1f} ms total, ~{tflops:.1f} TFLOPS"
        return Check("gpu matmul smoke", PASS if checksum_ok else FAIL, detail, core=False)
    except Exception as exc:
        return Check("gpu matmul smoke", FAIL, f"matmul failed: {exc}", core=False)


def _tool_version(tool: str) -> str | None:
    path = shutil.which(tool)
    if not path:
        return None
    try:
        out = subprocess.run([tool, "-version"], capture_output=True, text=True, timeout=15)
        first = (out.stdout or out.stderr).splitlines()[0].strip() if (out.stdout or out.stderr) else tool
        return f"{first} ({path})"
    except Exception as exc:
        return f"{path} (version probe failed: {exc})"


def check_ffmpeg() -> list[Check]:
    checks = []
    for tool in ("ffmpeg", "ffprobe"):
        ver = _tool_version(tool)
        if ver:
            checks.append(Check(tool, PASS, ver, core=True))
        else:
            checks.append(Check(tool, FAIL, "not found on PATH", core=True))
    return checks


def check_opencv() -> Check:
    try:
        import cv2  # lazy import
        return Check("opencv", PASS, f"cv2 {cv2.__version__}", core=True)
    except Exception as exc:
        return Check("opencv", FAIL, f"import failed: {exc}", core=True)


def check_presidio() -> Check:
    try:
        import presidio_analyzer  # noqa: F401  lazy optional import
        ver = getattr(presidio_analyzer, "__version__", "?")
        return Check("presidio", PASS, f"presidio_analyzer {ver} (extra audio-PII recall)", core=False)
    except Exception:
        return Check("presidio", WARN, "not installed (regex + spoken-form PII still works)", core=False)


def hf_cache_dir() -> Path:
    try:
        from huggingface_hub.constants import HF_HUB_CACHE
        return Path(HF_HUB_CACHE)
    except Exception:
        return Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"


def check_model_cache() -> list[Check]:
    checks = []
    cache = hf_cache_dir()
    for repo_id in HF_MODEL_IDS:
        folder = cache / ("models--" + repo_id.replace("/", "--"))
        if folder.is_dir() and any(folder.rglob("*")):
            size = sum(p.stat().st_size for p in folder.rglob("*") if p.is_file() and not p.is_symlink())
            checks.append(Check(f"model {repo_id}", PASS, f"cached, ~{size / 1e9:.2f} GB", core=False))
        else:
            checks.append(Check(f"model {repo_id}", WARN, "not in HF cache (run scripts/download_models.py)", core=False))
    if YUNET_PATH.is_file() and YUNET_PATH.stat().st_size > 100_000:
        checks.append(Check("model yunet onnx", PASS, str(YUNET_PATH.relative_to(PROJECT_ROOT)), core=False))
    else:
        checks.append(Check("model yunet onnx", WARN, "models/face_detection_yunet_2023mar.onnx missing", core=False))
    return checks


def run_all() -> list[Check]:
    checks: list[Check] = [check_python()]
    torch_check, gpu_checks, _torch = check_torch()
    checks.append(torch_check)
    checks.extend(gpu_checks)
    checks.extend(check_ffmpeg())
    checks.append(check_opencv())
    checks.extend(check_model_cache())
    checks.append(check_presidio())
    return checks


def print_table(checks: list[Check]) -> None:
    name_w = max(len(c.name) for c in checks) + 2
    print("\n" + "=" * (name_w + 70))
    print(f"{'CHECK':<{name_w}} {'STATUS':<7} DETAIL")
    print("-" * (name_w + 70))
    for c in checks:
        core = " (core)" if c.core else ""
        print(f"{c.name:<{name_w}} {c.status:<7} {c.detail}{core}")
    print("=" * (name_w + 70))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PolicyCut environment preflight")
    parser.add_argument(
        "--json",
        nargs="?",
        const=str(DEFAULT_JSON),
        default=None,
        metavar="PATH",
        help=f"write JSON report (default path: {DEFAULT_JSON})",
    )
    args = parser.parse_args(argv)

    checks = run_all()
    print_table(checks)

    core_failed = [c for c in checks if c.core and c.status == FAIL]
    warned = [c for c in checks if c.status == WARN]
    if core_failed:
        print(f"\nRESULT: FAIL — missing core requirement(s): {', '.join(c.name for c in core_failed)}")
    elif warned:
        print(f"\nRESULT: PASS with {len(warned)} warning(s).")
    else:
        print("\nRESULT: PASS — environment fully ready.")

    if args.json:
        out_path = Path(args.json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "platform": platform.platform(),
            "result": "fail" if core_failed else "pass",
            "checks": [c.as_dict() for c in checks],
        }
        tmp = out_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(report, indent=2))
        os.replace(tmp, out_path)
        print(f"JSON report written to {out_path}")

    return 1 if core_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
