#!/usr/bin/env python3
"""ROCm connectivity verification script.

Run this on the AMD GPU pod to confirm that ROCm is fully wired into the
Cortex deployment before starting the demo. Prints a structured report that
can be pasted directly into the demo README or submission artefacts.

Usage (on the pod):
    python scripts/rocm_verify.py
    python scripts/rocm_verify.py --json      # machine-readable output
    python scripts/rocm_verify.py --embed     # also run an embedding throughput test

Exit code 0 = ROCm confirmed active. Non-zero = degraded/CPU-only mode.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path  # noqa: F401 — kept for potential future use
from typing import Any


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(cmd: list[str], timeout: float = 5.0) -> tuple[int, str]:
    """Run a subprocess and return (returncode, stdout+stderr)."""
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        return r.returncode, (r.stdout + r.stderr).strip()
    except FileNotFoundError:
        return -1, f"{cmd[0]}: not found"
    except subprocess.TimeoutExpired:
        return -2, f"{cmd[0]}: timed out"


def _check_rocm_smi() -> dict[str, Any]:
    rc, out = _run(["rocm-smi", "--showallinfo", "--json"])
    if rc != 0:
        return {"available": False, "error": out}
    try:
        data = json.loads(out)
        # Grab first GPU card entry
        card = next(
            (v for k, v in data.items() if isinstance(v, dict)), {}
        )
        return {
            "available": True,
            "device_name": (
                card.get("Card SKU")
                or card.get("card_series")
                or card.get("product_name")
                or "unknown"
            ),
            "vram_total_gb": _bytes_to_gb(
                card.get("VRAM Total Memory (B)") or card.get("vram_total", 0)
            ),
            "vram_used_gb": _bytes_to_gb(
                card.get("VRAM Total Used Memory (B)") or card.get("vram_used", 0)
            ),
            "driver_version": card.get("Driver version", "unknown"),
            "raw": card,
        }
    except Exception as exc:
        return {"available": True, "parse_error": str(exc), "raw_output": out[:500]}


def _bytes_to_gb(val: Any) -> float:
    try:
        return round(float(val) / 1024 ** 3, 2)
    except Exception:
        return 0.0


def _check_torch_rocm() -> dict[str, Any]:
    try:
        import torch
    except ImportError:
        return {"available": False, "error": "torch not installed"}

    hip_ver = getattr(torch.version, "hip", None)
    cuda_avail = torch.cuda.is_available()
    result: dict[str, Any] = {
        "available": cuda_avail,
        "torch_version": torch.__version__,
        "hip_version": hip_ver,
        "cuda_available": cuda_avail,
    }
    if cuda_avail:
        try:
            result["device_count"] = torch.cuda.device_count()
            result["device_name"] = torch.cuda.get_device_name(0)
            props = torch.cuda.get_device_properties(0)
            result["vram_total_gb"] = round(props.total_memory / 1024 ** 3, 2)
        except Exception as exc:
            result["device_error"] = str(exc)
    return result


def _embed_throughput(batch: int = 16, warmup: int = 1, iters: int = 5) -> dict[str, Any]:
    """Run a quick embedding throughput test using the Cortex Embedder."""
    try:
        from cortex.node.embedder import Embedder
    except ImportError:
        return {"error": "cortex package not importable"}

    results = {}
    for backend_label, backend in [("radeon", "gpu"), ("cpu", "cpu")]:
        try:
            emb = Embedder(backend=backend, batch_size=batch)
        except Exception as exc:
            results[backend_label] = {"error": str(exc)}
            continue
        texts = ["APT29 T1059.001 encoded PowerShell C2 beacon"] * batch
        # warmup
        for _ in range(warmup):
            try:
                emb.embed(texts)
            except Exception:
                break
        times = []
        for _ in range(iters):
            t0 = time.perf_counter()
            try:
                emb.embed(texts)
            except Exception as exc:
                results[backend_label] = {"error": str(exc)}
                break
            times.append(time.perf_counter() - t0)
        if times:
            median_ms = sorted(times)[len(times) // 2] * 1000
            throughput = batch / (sum(times) / len(times))
            results[backend_label] = {
                "device": emb._device,
                "batch": batch,
                "iters": iters,
                "median_latency_ms": round(median_ms, 2),
                "throughput_embeds_per_sec": round(throughput, 1),
            }
    return results


# ---------------------------------------------------------------------------
# Main report
# ---------------------------------------------------------------------------

def build_report(run_embed: bool = False) -> dict[str, Any]:
    report: dict[str, Any] = {
        "rocm_smi": _check_rocm_smi(),
        "torch_rocm": _check_torch_rocm(),
    }
    if run_embed:
        report["embed_throughput"] = _embed_throughput()
    return report


def print_human(report: dict[str, Any]) -> None:
    smi = report["rocm_smi"]
    torch_r = report["torch_rocm"]

    print("\n╔══════════════════════════════════════════════════╗")
    print("║        Perciqa Cortex — ROCm Verify Report       ║")
    print("╚══════════════════════════════════════════════════╝\n")

    # rocm-smi section
    if smi.get("available"):
        print("  rocm-smi         ✅  available")
        print(f"  GPU device       {smi.get('device_name', 'unknown')}")
        print(f"  VRAM total       {smi.get('vram_total_gb', '?')} GB")
        print(f"  VRAM used        {smi.get('vram_used_gb', '?')} GB")
        print(f"  Driver           {smi.get('driver_version', 'unknown')}")
    else:
        print(f"  rocm-smi         ❌  {smi.get('error', 'unavailable')}")

    print()

    # torch section
    if torch_r.get("available"):
        print(f"  PyTorch          ✅  {torch_r.get('torch_version')}")
        print(f"  HIP version      {torch_r.get('hip_version') or 'N/A (CUDA path)'}")
        print(f"  CUDA available   {torch_r.get('cuda_available')}")
        print(f"  Device count     {torch_r.get('device_count', '?')}")
        print(f"  Device name      {torch_r.get('device_name', 'unknown')}")
        print(f"  VRAM (torch)     {torch_r.get('vram_total_gb', '?')} GB")
    elif torch_r.get("cuda_available") is False:
        print(f"  PyTorch          ⚠️   {torch_r.get('torch_version')} (no GPU visible)")
        print(f"  HIP version      {torch_r.get('hip_version') or 'none'}")
    else:
        print(f"  PyTorch          ❌  {torch_r.get('error', 'unavailable')}")

    print()

    # embed throughput
    if "embed_throughput" in report:
        print("  Embedding throughput (BAAI/bge-small-en-v1.5, batch=16):")
        for label, data in report["embed_throughput"].items():
            if "error" in data:
                print(f"    {label:8s}  ❌  {data['error']}")
            else:
                print(
                    f"    {label:8s}  {data['throughput_embeds_per_sec']:>7.1f} embeds/sec"
                    f"  (p50={data['median_latency_ms']:.1f} ms, device={data['device']})"
                )
        print()

    # overall verdict
    rocm_active = smi.get("available") and torch_r.get("available")
    if rocm_active:
        print("  ✅  ROCm is ACTIVE — Cortex embedding and inference will run on Radeon GPU.")
    elif torch_r.get("cuda_available") is False and not smi.get("available"):
        print("  ⚠️   ROCm NOT detected — Cortex will fall back to CPU embedder.")
        print("       Check: HSA_OVERRIDE_GFX_VERSION, ROCm driver install, docker GPU passthrough.")
    else:
        print("  ⚠️   Partial ROCm — check logs above for details.")
    print()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    ap.add_argument("--embed", action="store_true", help="Include embedding throughput benchmark")
    args = ap.parse_args()

    report = build_report(run_embed=args.embed)

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print_human(report)

    # Exit non-zero if ROCm is not confirmed active
    rocm_ok = (
        report["rocm_smi"].get("available", False)
        or report["torch_rocm"].get("available", False)
    )
    return 0 if rocm_ok else 1


if __name__ == "__main__":
    sys.exit(main())
