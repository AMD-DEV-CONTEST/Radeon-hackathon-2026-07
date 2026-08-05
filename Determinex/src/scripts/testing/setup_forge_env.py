"""
setup_forge_env.py — One-shot GPU training stack installer for Determinex Forge

Installs PyTorch (CUDA 12.1) + Unsloth + training dependencies into the
active Python environment.

Usage:
  python setup_forge_env.py          # auto-detect CUDA version
  python setup_forge_env.py --check  # verify existing install only
"""

import argparse
import subprocess
import sys
from pathlib import Path

# Windows cp1252 terminals choke on box-drawing chars — force UTF-8 output
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

parser = argparse.ArgumentParser()
parser.add_argument("--check", action="store_true", help="Check existing install, don't install")
args = parser.parse_args()

PIP = [sys.executable, "-m", "pip"]
DETERMINEX_ROOT = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# ENVIRONMENT CHECK
# ---------------------------------------------------------------------------


def check_nvidia() -> tuple[bool, str]:
    """Returns (gpu_found, driver_version)."""
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if r.returncode == 0 and r.stdout.strip():
            return True, r.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return False, ""


def check_package(name: str) -> tuple[bool, str]:
    """Returns (installed, version_string)."""
    try:
        r = subprocess.run(
            [sys.executable, "-c", f"import {name}; print(getattr({name}, '__version__', 'ok'))"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if r.returncode == 0:
            return True, r.stdout.strip()
    except subprocess.TimeoutExpired:
        pass
    return False, ""


# ---------------------------------------------------------------------------
# INSTALL HELPERS
# ---------------------------------------------------------------------------


def run_pip(*pip_args: str) -> bool:
    """Run pip with the given arguments. Returns True on success."""
    cmd = PIP + list(pip_args)
    print(f"\n[SETUP] {' '.join(cmd[2:])}", flush=True)
    result = subprocess.run(cmd)
    return result.returncode == 0


def install_pytorch() -> bool:
    """
    Install PyTorch with CUDA 12.1 wheels.
    CUDA 12.1 wheels work with any driver >= 527.41.
    """
    print("\n[SETUP] Installing PyTorch 2.x (CUDA 12.1)...", flush=True)
    return run_pip(
        "install",
        "--upgrade",
        "torch",
        "torchvision",
        "torchaudio",
        "--index-url",
        "https://download.pytorch.org/whl/cu121",
    )


def install_unsloth() -> bool:
    """
    Install Unsloth [colab-new] variant.
    The colab-new extra avoids building triton from source — critical on Windows.
    """
    print("\n[SETUP] Installing Unsloth (colab-new — no triton build required)...", flush=True)
    # Try PyPI first; fall back to GitHub edge build if PyPI version lags
    ok = run_pip("install", "--upgrade", "unsloth[colab-new]")
    if not ok:
        print("[SETUP] PyPI install failed — trying GitHub edge build...", flush=True)
        ok = run_pip(
            "install",
            "--upgrade",
            "unsloth[colab-new] @ git+https://github.com/unslothai/unsloth.git",
        )
    return ok


def install_training_stack() -> bool:
    """Install TRL, PEFT, Transformers, Accelerate, Datasets."""
    print(
        "\n[SETUP] Installing training stack (trl, peft, transformers, accelerate, datasets)...",
        flush=True,
    )
    reqs = DETERMINEX_ROOT / "scripts" / "fine_tuning" / "requirements.txt"
    if reqs.exists():
        return run_pip("install", "--upgrade", "-r", str(reqs))
    # Fallback: install individually
    return run_pip(
        "install",
        "--upgrade",
        "trl>=0.11.0",
        "peft>=0.13.0",
        "transformers>=4.44.0",
        "accelerate>=0.34.0",
        "datasets>=3.0.0",
        "bitsandbytes>=0.43.0",
    )


# ---------------------------------------------------------------------------
# VERIFICATION
# ---------------------------------------------------------------------------


def verify_install() -> bool:
    """Run a quick smoke-test of the installed stack. Returns True if all good."""
    print("\n[SETUP] Verifying install...", flush=True)

    checks = [
        ("torch", "torch.cuda.is_available()"),
        ("unsloth", "'ok'"),
        ("datasets", "'ok'"),
        ("trl", "'ok'"),
        ("transformers", "'ok'"),
    ]

    all_ok = True
    for pkg, expr in checks:
        ok, ver = check_package(pkg)
        status = f"✓  {ver}" if ok else "✗  NOT FOUND"
        print(f"  {pkg:<15} {status}", flush=True)
        if not ok:
            all_ok = False

    # Check CUDA reachable through torch
    cuda_check = subprocess.run(
        [
            sys.executable,
            "-c",
            "import torch; print('CUDA:', torch.cuda.is_available(), '|', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'no GPU')",
        ],
        capture_output=True,
        text=True,
    )
    print(
        f"  {'cuda check':<15} {cuda_check.stdout.strip() or cuda_check.stderr.strip()}", flush=True
    )

    return all_ok


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------


def main():
    print("═" * 60)
    print("  DETERMINEX FORGE — Training Environment Setup")
    print(f"  Python: {sys.executable}")
    print("═" * 60 + "\n", flush=True)

    # GPU sanity check
    gpu_found, gpu_info = check_nvidia()
    if gpu_found:
        print(f"[SETUP] GPU detected: {gpu_info}", flush=True)
    else:
        print("[SETUP] WARNING: nvidia-smi not found or no GPU detected.", flush=True)
        print("[SETUP] Training requires an NVIDIA GPU with CUDA support.", flush=True)
        print(
            "[SETUP] Continuing install — PyTorch CPU wheels will be installed instead.", flush=True
        )

    if args.check:
        ok = verify_install()
        if ok:
            print("\n[SETUP] All dependencies installed and verified.", flush=True)
        else:
            print(
                "\n[SETUP] Missing packages — run setup_forge_env.py (without --check) to install.",
                flush=True,
            )
        return

    # Install sequence
    steps = [
        ("PyTorch (CUDA 12.1)", install_pytorch),
        ("Unsloth", install_unsloth),
        ("Training stack", install_training_stack),
    ]

    for name, fn in steps:
        print(f"\n{'─' * 40}", flush=True)
        print(f"[SETUP] Step: {name}", flush=True)
        ok = fn()
        if not ok:
            print(f"[SETUP] ERROR: {name} installation failed. Check the error above.", flush=True)
            print(
                "[SETUP] You can retry just this step by re-running setup_forge_env.py", flush=True
            )
            sys.exit(1)

    # Final verification
    print(f"\n{'─' * 40}", flush=True)
    all_ok = verify_install()

    if all_ok:
        print(
            f"\n{'═' * 60}\n"
            f"  SETUP COMPLETE\n"
            f"\n"
            f"  Run a single forge:     python ignite_loop.py --forge-only\n"
            f"  Run the full loop:      python ignite_loop.py\n"
            f"  Train on current data:  python ignite_loop.py --train-only\n"
            f"{'═' * 60}\n",
            flush=True,
        )
    else:
        print("\n[SETUP] Some packages failed to install. Check errors above.", flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
