#!/usr/bin/env python3
"""Verify AMD Radeon / ROCm readiness for Track 2 local inference."""

from __future__ import annotations


def main() -> None:
    print("=== PrivateLocalAgent · GPU / ROCm check ===")
    try:
        from src.config import DEFAULT_PERSISTENCE_BASE, detect_data_root

        print(f"data_root: {detect_data_root()}")
        print(f"persistence_dir_exists: {DEFAULT_PERSISTENCE_BASE.is_dir()} ({DEFAULT_PERSISTENCE_BASE})")
    except Exception as exc:  # noqa: BLE001
        print(f"data_root check skipped: {exc}")
    try:
        import torch

        print(f"torch: {torch.__version__}")
        print(f"cuda_available: {torch.cuda.is_available()}")
        if hasattr(torch.version, "hip"):
            print(f"hip: {torch.version.hip}")
        if torch.cuda.is_available():
            print(f"device_count: {torch.cuda.device_count()}")
            print(f"device0: {torch.cuda.get_device_name(0)}")
            x = torch.randn(1024, 1024, device="cuda")
            y = x @ x
            print(f"matmul_ok: {y.shape}")
        else:
            print("No GPU visible. You can still use openai_compatible backend.")
    except Exception as exc:  # noqa: BLE001
        print(f"torch check failed: {exc}")
        print("Install ROCm PyTorch wheel on Radeon Cloud / Linux before local_transformers mode.")


if __name__ == "__main__":
    main()
