"""Phase 0: Environment check - GPU/ROCm/vLLM/PyTorch version validation.

References the Phase 0 logic of the AMD vLLM Optimize Skill v3:
- Detect GPU model, CU count, VRAM
- Detect ROCm/HIP version
- Verify whether PyTorch is the ROCm version
- Detect vLLM version
- Verify key environment variables (HSA_OVERRIDE_GFX_VERSION, etc.)
- Output env_info.json for use by later phases

Usage::

    python scripts/vllm_env_check.py
    python scripts/vllm_env_check.py --output docs/benchmarks/env_info.json
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _run(cmd: list[str], timeout: int = 10) -> tuple[int, str, str]:
    """Run a command, returning (returncode, stdout, stderr)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except FileNotFoundError:
        return -1, "", f"command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return -2, "", f"timeout({timeout}s)"


def check_gpu() -> dict[str, Any]:
    """Detect GPU information."""
    info: dict[str, Any] = {"available": False}

    # rocm-smi
    rc, out, _ = _run(["rocm-smi", "--showproductname", "--json"])
    if rc == 0:
        try:
            data = json.loads(out)
            for gpu_id, v in data.items():
                if gpu_id.startswith("card"):
                    info["available"] = True
                    info["gpu_id"] = gpu_id
                    info["product_name"] = v.get("Card series", v.get("Card model", "unknown"))
                    break
        except json.JSONDecodeError:
            pass

    # rocminfo
    rc, out, _ = _run(["rocminfo"])
    if rc == 0:
        for line in out.splitlines():
            line = line.strip()
            if "Marketing Name:" in line:
                info["marketing_name"] = line.split(":", 1)[1].strip()
            elif "Name:" in line and "gfx" in line.lower():
                info["gfx_arch"] = line.split(":", 1)[1].strip()
            elif "Compute Unit:" in line:
                try:
                    info["cu_count"] = int(line.split(":", 1)[1].strip())
                except ValueError:
                    pass
            elif "Memory Size:" in line:
                mem_str = line.split(":", 1)[1].strip()
                if "GB" in mem_str or "M" in mem_str.upper():
                    info["vram"] = mem_str

    # Python torch detection
    try:
        import torch
        info["torch_version"] = torch.__version__
        info["torch_hip_available"] = torch.cuda.is_available()
        if torch.cuda.is_available():
            info["torch_device_count"] = torch.cuda.device_count()
            info["torch_device_name"] = torch.cuda.get_device_name(0)
            props = torch.cuda.get_device_properties(0)
            info["torch_cu_count"] = props.multi_processor_count
            info["torch_total_vram_gb"] = round(props.total_memory / 1024**3, 1)
    except ImportError:
        info["torch_version"] = "not_installed"
    except Exception as e:
        info["torch_error"] = str(e)[:100]

    return info


def check_rocm() -> dict[str, Any]:
    """Detect the ROCm version."""
    info: dict[str, Any] = {}

    rc, out, _ = _run(["rocminfo", "--version"])
    if rc == 0:
        for line in out.splitlines():
            if "HIP" in line:
                info["hip_version"] = line.split(":", 1)[1].strip()
            elif "ROCm" in line or "ROCR" in line:
                info["rocm_version"] = line.split(":", 1)[1].strip()

    # Environment variables
    info["env"] = {
        "HSA_OVERRIDE_GFX_VERSION": os.environ.get("HSA_OVERRIDE_GFX_VERSION", "NOT_SET"),
        "HIP_VISIBLE_DEVICES": os.environ.get("HIP_VISIBLE_DEVICES", "NOT_SET"),
        "ROCBLAS_USE_HIPBLASLT": os.environ.get("ROCBLAS_USE_HIPBLASLT", "NOT_SET"),
        "PYTORCH_TUNABLEOP_ENABLED": os.environ.get("PYTORCH_TUNABLEOP_ENABLED", "NOT_SET"),
        "PYTORCH_TUNABLEOP_RECORD_UNTUNED": os.environ.get("PYTORCH_TUNABLEOP_RECORD_UNTUNED", "NOT_SET"),
    }

    return info


def check_vllm() -> dict[str, Any]:
    """Detect the vLLM version."""
    info: dict[str, Any] = {}
    try:
        import vllm
        info["vllm_version"] = getattr(vllm, "__version__", "unknown")
    except ImportError:
        info["vllm_version"] = "not_installed"
    except Exception as e:
        info["vllm_error"] = str(e)[:100]

    # Check whether the vLLM server is running
    try:
        import httpx
        with httpx.Client(timeout=5) as client:
            resp = client.get("http://localhost:8000/v1/models")
            if resp.status_code == 200:
                models = resp.json().get("data", [])
                info["server_running"] = True
                info["loaded_models"] = [m.get("id") for m in models]
            else:
                info["server_running"] = False
    except Exception:
        info["server_running"] = False

    return info


def validate(info: dict[str, Any]) -> list[dict[str, str]]:
    """Validate whether the environment meets requirements, returning a list of checks."""
    checks: list[dict[str, str]] = []
    gpu = info.get("gpu", {})

    # GPU availability
    ok = gpu.get("available", False)
    checks.append({
        "item": "GPU visible",
        "status": "PASS" if ok else "FAIL",
        "detail": gpu.get("marketing_name", gpu.get("product_name", "no GPU detected")),
    })

    # PyTorch ROCm
    torch_ok = gpu.get("torch_hip_available", False)
    checks.append({
        "item": "PyTorch ROCm",
        "status": "PASS" if torch_ok else "FAIL",
        "detail": f"torch {gpu.get('torch_version', '?')}, HIP={'available' if torch_ok else 'NOT available'}",
    })

    # gfx version
    gfx = gpu.get("gfx_arch", "")
    is_gfx1100 = "gfx1100" in gfx.lower() or "11.0.0" in gfx
    checks.append({
        "item": "gfx architecture",
        "status": "PASS" if gfx else "WARN",
        "detail": gfx or "not detected, may need HSA_OVERRIDE_GFX_VERSION",
    })

    # Environment variables
    env = info.get("rocm", {}).get("env", {})
    hsa_set = env.get("HSA_OVERRIDE_GFX_VERSION", "NOT_SET") != "NOT_SET"
    checks.append({
        "item": "HSA_OVERRIDE_GFX_VERSION",
        "status": "PASS" if hsa_set else "WARN",
        "detail": env.get("HSA_OVERRIDE_GFX_VERSION", "NOT_SET") + (" (required for gfx1100)" if not hsa_set else ""),
    })

    hip_set = env.get("HIP_VISIBLE_DEVICES", "NOT_SET") != "NOT_SET"
    checks.append({
        "item": "HIP_VISIBLE_DEVICES",
        "status": "PASS" if hip_set else "WARN",
        "detail": env.get("HIP_VISIBLE_DEVICES", "NOT_SET"),
    })

    # hipBLASLt
    hipblaslt = env.get("ROCBLAS_USE_HIPBLASLT", "NOT_SET") != "NOT_SET"
    checks.append({
        "item": "ROCBLAS_USE_HIPBLASLT",
        "status": "PASS" if hipblaslt else "WARN",
        "detail": env.get("ROCBLAS_USE_HIPBLASLT", "NOT_SET") + (" (if not set, throughput drops 2x)" if not hipblaslt else ""),
    })

    # vLLM
    vllm_ver = info.get("vllm", {}).get("vllm_version", "not_installed")
    vllm_ok = vllm_ver != "not_installed"
    checks.append({
        "item": "vLLM installed",
        "status": "PASS" if vllm_ok else "FAIL",
        "detail": vllm_ver,
    })

    # vLLM server
    server_ok = info.get("vllm", {}).get("server_running", False)
    checks.append({
        "item": "vLLM server running",
        "status": "PASS" if server_ok else "WARN",
        "detail": "port 8000 available" if server_ok else "port 8000 not responding, need to start vLLM first",
    })

    return checks


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 0: environment check (reference AMD vLLM Optimize Skill v3)")
    parser.add_argument("--output", type=Path, default=Path("docs/benchmarks/env_info.json"))
    args = parser.parse_args()

    print("=" * 70)
    print("Phase 0: Environment check - AMD vLLM Optimize Skill v3")
    print("=" * 70)
    print()

    # Check
    print("[1/3] Checking GPU...")
    gpu_info = check_gpu()
    print(f"  GPU: {gpu_info.get('marketing_name', gpu_info.get('product_name', 'unknown'))}")
    print(f"  Architecture: {gpu_info.get('gfx_arch', 'unknown')}")
    print(f"  CU: {gpu_info.get('cu_count', gpu_info.get('torch_cu_count', '?'))}")
    print(f"  VRAM: {gpu_info.get('vram', str(gpu_info.get('torch_total_vram_gb', '?')) + ' GB')}")
    print(f"  PyTorch: {gpu_info.get('torch_version', '?')}, HIP={gpu_info.get('torch_hip_available', False)}")
    print()

    print("[2/3] Checking ROCm...")
    rocm_info = check_rocm()
    for k, v in rocm_info.items():
        if k == "env":
            print("  Environment variables:")
            for ek, ev in v.items():
                marker = "OK" if ev != "NOT_SET" else "!!"
                print(f"    {ek}={ev}  [{marker}]")
        else:
            print(f"  {k}: {v}")
    print()

    print("[3/3] Checking vLLM...")
    vllm_info = check_vllm()
    print(f"  Version: {vllm_info.get('vllm_version', '?')}")
    print(f"  Server: {'running' if vllm_info.get('server_running') else 'not running'}")
    if vllm_info.get("loaded_models"):
        print(f"  Models: {vllm_info['loaded_models']}")
    print()

    # Validate
    info = {"gpu": gpu_info, "rocm": rocm_info, "vllm": vllm_info}
    checks = validate(info)

    print("Validation results:")
    print(f"  {'check item':<30} {'status':>6}  {'detail'}")
    print(f"  {'-'*30} {'-'*6}  {'-'*40}")
    pass_count = 0
    for c in checks:
        status = c["status"]
        if status == "PASS":
            pass_count += 1
        print(f"  {c['item']:<30} {status:>6}  {c['detail']}")
    print()

    total = len(checks)
    print(f"Passed: {pass_count}/{total}")

    # Save
    output_path = PROJECT_ROOT / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "phase": 0,
        "phase_name": "env",
        "checks": checks,
        "summary": {
            "total": total,
            "passed": pass_count,
            "warnings": sum(1 for c in checks if c["status"] == "WARN"),
            "failed": sum(1 for c in checks if c["status"] == "FAIL"),
        },
        "details": info,
    }
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nReport saved: {output_path}")

    if pass_count == total:
        print("\n=== Phase 0: env - DONE  all passed ===")
    else:
        failed = [c for c in checks if c["status"] == "FAIL"]
        if failed:
            print(f"\n=== Phase 0: env - FAILED: {len(failed)} checks failed ===")
            for f in failed:
                print(f"  {f['item']}: {f['detail']}")
            sys.exit(1)
        else:
            print("\n=== Phase 0: env - DONE  (warnings present but can continue) ===")


if __name__ == "__main__":
    main()
