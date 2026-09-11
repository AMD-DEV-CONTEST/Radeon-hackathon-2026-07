from __future__ import annotations

import importlib.util
import json
import sys
import time


def main() -> int:
    try:
        import torch
    except ImportError:
        print("ERROR: PyTorch is not installed in the selected cloud image.")
        return 2

    hip_version = getattr(torch.version, "hip", None)
    if hip_version is None:
        print("ERROR: PyTorch is not a ROCm build. Refusing to continue.")
        return 3
    if not torch.cuda.is_available():
        print("ERROR: ROCm PyTorch cannot access the Radeon GPU.")
        return 4
    if torch.cuda.device_count() != 1:
        print("ERROR: The competition baseline expects exactly one visible GPU.")
        return 5

    device = torch.device("cuda:0")
    left = torch.randn((2048, 2048), device=device)
    right = torch.randn((2048, 2048), device=device)
    torch.cuda.synchronize()
    started = time.perf_counter()
    output = left @ right
    torch.cuda.synchronize()

    report = {
        "python": sys.version.split()[0],
        "torch": torch.__version__,
        "rocm": hip_version,
        "device": torch.cuda.get_device_name(0),
        "device_count": torch.cuda.device_count(),
        "matmul_seconds": round(time.perf_counter() - started, 6),
        "checksum": round(output[0, 0].item(), 6),
        "genesis_installed": importlib.util.find_spec("genesis") is not None,
        "lerobot_installed": importlib.util.find_spec("lerobot") is not None,
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
