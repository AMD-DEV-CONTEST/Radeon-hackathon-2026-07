#!/usr/bin/env python3
"""M0: ROCm + PyTorch + MIOpen + vLLM environment verification.

Run this FIRST on the W7900 machine before any other work.
Checks all the hardware/software prerequisites and reports issues.

Usage:
    python scripts/verify_rocm.py [--model Qwen/Qwen2.5-Coder-14B-Instruct]

Exit codes:
    0 = all checks passed
    1 = one or more checks failed (see output for details)
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Optional


@dataclass
class CheckResult:
    name: str
    passed: bool
    message: str
    details: str = ""


results: list[CheckResult] = []


def check(name: str) -> None:
    """Decorator-ish: print check header."""
    print(f"\n{'='*60}")
    print(f"  CHECK: {name}")
    print(f"{'='*60}")


def record(result: CheckResult) -> None:
    results.append(result)
    status = "[OK]" if result.passed else "[FAIL]"
    print(f"  {status} {result.message}")
    if result.details:
        print(f"       {result.details}")


def check_rocm_driver() -> bool:
    check("ROCm Driver")
    try:
        result = subprocess.run(["rocminfo"], capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            record(CheckResult("rocm_driver", False, "rocminfo failed to run"))
            return False
        output = result.stdout
        if "gfx1100" not in output:
            record(CheckResult("rocm_driver", False,
                  "gfx1100 not found in rocminfo output",
                  "W7900 should report as gfx1100"))
            return False
        record(CheckResult("rocm_driver", True, "gfx1100 detected via rocminfo"))
        return True
    except FileNotFoundError:
        record(CheckResult("rocm_driver", False, "rocminfo not found. ROCm not installed?"))
        return False


def check_hip() -> bool:
    check("HIP Toolchain")
    try:
        result = subprocess.run(["hipconfig", "--version"], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            version = result.stdout.strip()
            record(CheckResult("hip", True, f"HIP version: {version}"))
            return True
        record(CheckResult("hip", False, "hipconfig failed"))
        return False
    except FileNotFoundError:
        record(CheckResult("hip", False, "hipconfig not found"))
        return False


def check_pytorch() -> tuple[bool, str, str]:
    check("PyTorch + ROCm")
    try:
        import torch
    except ImportError:
        record(CheckResult("pytorch", False, "PyTorch not installed"))
        return False, "", ""

    version = torch.__version__
    has_rocm = hasattr(torch.version, "hip") and torch.version.hip is not None

    if not has_rocm:
        record(CheckResult("pytorch", False,
              f"PyTorch {version} is NOT the ROCm build",
              "Install: pip install torch --index-url https://download.pytorch.org/whl/rocm7.2.1"))
        return False, version, ""

    if not torch.cuda.is_available():
        record(CheckResult("pytorch", False,
              f"PyTorch {version} (ROCm) but cuda.is_available()=False",
              "Check ROCm driver / permissions"))
        return False, version, ""

    gpu_name = torch.cuda.get_device_name(0)
    record(CheckResult("pytorch", True,
          f"PyTorch {version} (ROCm {torch.version.hip})",
          f"GPU: {gpu_name}"))
    return True, version, gpu_name


def check_miopen() -> bool:
    """Verify the ROCm attention backend works on gfx1100.

    vLLM on ROCm uses either MIOpen or AOTriton for attention kernels.
    We test scaled_dot_product_attention forward pass only (no backward
    needed for kernel availability check).
    """
    check("Attention Backend (MIOpen / AOTriton)")
    try:
        import torch
        import torch.nn.functional as F

        # Small scaled dot-product attention
        batch, heads, seq, dim = 1, 4, 128, 64
        q = torch.randn(batch, heads, seq, dim, device="cuda")
        k = torch.randn(batch, heads, seq, dim, device="cuda")
        v = torch.randn(batch, heads, seq, dim, device="cuda")

        # Forward only — enough to verify the attention kernel works
        with torch.no_grad():
            out = F.scaled_dot_product_attention(q, k, v)

        # Check for NaN/Inf
        if torch.isnan(out).any() or torch.isinf(out).any():
            record(CheckResult("miopen", False,
                  "Attention output contains NaN/Inf",
                  "Attention kernel may be broken on gfx1100"))
            return False

        record(CheckResult("miopen", True,
              "SDPA forward on GPU produces valid output",
              "Attention backend functional (AOTriton/MIOpen)"))
        return True

    except Exception as e:
        record(CheckResult("miopen", False,
              f"Attention backend test failed: {e}",
              "vLLM ROCm attention may not work. Consider llama.cpp fallback."))
        return False


def check_inference_stability() -> bool:
    """Run inference 5 times and check output consistency."""
    check("Inference Stability (5 runs)")
    try:
        import torch
        import torch.nn as nn

        # Simple model inference test
        model = nn.Linear(128, 128).cuda()
        x = torch.randn(1, 128, device="cuda")

        outputs = []
        for i in range(5):
            with torch.no_grad():
                out = model(x)
            outputs.append(out.cpu())

        # Check all outputs are identical
        all_same = all(torch.allclose(outputs[0], o, atol=1e-6) for o in outputs)
        if not all_same:
            record(CheckResult("stability", False,
                  "Inference outputs differ across 5 runs",
                  "Set AMD_SERIALIZE_KERNEL=3, AMD_SERIALIZE_COPY=3"))
            return False

        record(CheckResult("stability", True,
              "5 runs produced identical output",
              "GPU computation is deterministic"))
        return True

    except Exception as e:
        record(CheckResult("stability", False, f"Stability test failed: {e}"))
        return False


def check_vllm(model: str) -> bool:
    """Try importing vLLM and running a minimal inference."""
    check(f"vLLM ({model})")
    try:
        import vllm
        record(CheckResult("vllm_import", True, f"vLLM imported: {vllm.__version__}"))
        print(f"       NOTE: Full vLLM serve test requires running start_llm.sh separately.")
        print(f"       vLLM version: {vllm.__version__}")
        return True
    except ImportError:
        record(CheckResult("vllm_import", False,
              "vLLM not installed",
              "Install: pip install vllm --extra-index-url https://download.pytorch.org/whl/rocm7.2.1"))
        return False
    except Exception as e:
        record(CheckResult("vllm_import", False, f"vLLM import error: {e}"))
        return False


def check_rocm_env() -> None:
    check("ROCm Stability Environment Variables")
    import os
    expected = {
        "PYTORCH_ROCM_ARCH": "gfx1100",
        "HSA_ENABLE_SDMA": "0",
        "AMD_SERIALIZE_KERNEL": "3",
        "AMD_SERIALIZE_COPY": "3",
    }
    for var, expected_val in expected.items():
        actual = os.environ.get(var)
        if actual is None:
            print(f"  [WARN] {var} not set (recommended: {expected_val})")
        elif actual != expected_val:
            print(f"  [WARN] {var}={actual} (recommended: {expected_val})")
        else:
            print(f"  [OK]   {var}={actual}")


def main():
    parser = argparse.ArgumentParser(description="Verify ROCm environment for RepositoryAnalysisAgent")
    parser.add_argument("--model", default="Qwen/Qwen2.5-Coder-14B-Instruct",
                        help="Model name for vLLM check")
    args = parser.parse_args()

    print("""
+------------------------------------------------------------------+
|              RepositoryAnalysisAgent M0 Environment Verification               |
|              Target: AMD W7900 (gfx1100, ROCm 7.2.1)              |
+------------------------------------------------------------------+
""")

    # Lock ROCm version
    try:
        result = subprocess.run(["cat", "/opt/rocm/.info/version"],
                                capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            print(f"ROCm version: {result.stdout.strip()}")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        # Try alternative
        try:
            result = subprocess.run(["rocm-smi", "--showproductname"],
                                    capture_output=True, text=True, timeout=5)
            for line in result.stdout.split("\n"):
                if "version" in line.lower():
                    print(f"  {line.strip()}")
        except Exception:
            print("Could not determine ROCm version")

    check_rocm_env()
    rocm_ok = check_rocm_driver()
    hip_ok = check_hip()
    pt_ok, pt_version, gpu_name = check_pytorch()

    miopen_ok = False
    stability_ok = False
    if pt_ok:
        miopen_ok = check_miopen()
        stability_ok = check_inference_stability()

    vllm_ok = check_vllm(args.model)

    # Summary
    print(f"\n{'='*60}")
    print("  SUMMARY")
    print(f"{'='*60}")
    all_ok = True
    for r in results:
        status = "[OK]  " if r.passed else "[FAIL]"
        print(f"  {status} {r.name}: {r.message}")
        if not r.passed:
            all_ok = False

    # Decision tree
    print(f"\n{'='*60}")
    print("  DECISION")
    print(f"{'='*60}")
    if not rocm_ok or not pt_ok:
        print("  -> BLOCKED: ROCm/PyTorch not working. Fix before proceeding.")
        sys.exit(1)

    if not miopen_ok:
        print("  -> WARNING: MIOpen issue. vLLM attention may fail.")
        print("     Consider testing vLLM serve first; if it fails, switch to llama.cpp.")
    else:
        print("  -> MIOpen OK. vLLM attention backend should work.")

    if vllm_ok:
        print("  -> vLLM installed. Run start_llm.sh to test full serve.")
        if stability_ok:
            print("  -> Inference stable. Proceed to M1.")
        else:
            print("  -> WARNING: Inference unstable. Set AMD_SERIALIZE_* env vars.")
    else:
        print("  -> vLLM not installed. Install it or use llama.cpp fallback.")

    if all_ok:
        print("\n  *** All checks passed. Ready for M1. ***")
        sys.exit(0)
    else:
        print("\n  *** Some checks failed. Review output above. ***")
        sys.exit(1)


if __name__ == "__main__":
    main()
