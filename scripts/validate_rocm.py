"""AMD ROCm validation helper for hackathon demos and CI.

Prints the ROCm stack visible to torch and exits non-zero when ROCm is not
active, so it can be used as a pass/fail gate when producing Radeon proof.

Usage:

    python scripts/validate_rocm.py

Expected output on an RX 7900 XTX / ROCm box:

    torch version            : 2.6.0+rocm6.2
    torch.version.hip        : 6.2
    torch.cuda.is_available(): True
    GPU count                : 1
    GPU name                 : AMD Radeon RX 7900 XTX
    [OK] ROCm active.
"""

import sys


def main() -> int:
    try:
        import torch
    except ImportError as exc:
        print(f"[FAIL] torch is not installed: {exc}")
        return 1

    hip_version = getattr(torch.version, "hip", None)
    cuda_available = torch.cuda.is_available()
    n_gpus = torch.cuda.device_count()
    gpu_name = torch.cuda.get_device_name(0) if cuda_available and n_gpus > 0 else None

    print(f"torch version             : {torch.__version__}")
    print(f"torch.version.hip         : {hip_version}")
    print(f"torch.cuda.is_available() : {cuda_available}")
    print(f"GPU count                 : {n_gpus}")
    print(f"GPU name                  : {gpu_name}")

    if hip_version is None or not cuda_available:
        print("[FAIL] ROCm is not active in this torch build.")
        return 1
    print("[OK] ROCm active.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
