"""
verify_gguf.py — Run on pod before any SCP download
=====================================================
Checks:
  1. File exists and is newer than a given timestamp
  2. File size is within expected range
  3. llama.cpp can parse GGUF headers (gguf-dump or llama-cli)
  4. Quick first-token smoke test via llama-cli

Usage:
  python3 /workspace/verify_gguf.py engineer
  python3 /workspace/verify_gguf.py observer
  python3 /workspace/verify_gguf.py sentinel
"""

import subprocess
import sys
from datetime import datetime
from pathlib import Path

# ── Model specs ──────────────────────────────────────────────────────────────
MODELS = {
    "engineer": {
        "gguf": Path("/workspace/outputs/determinex-engineer-v9/determinex-engineer-v9.gguf"),
        "min_gb": 1.2,
        "max_gb": 2.2,
        "prompt": "Write a Rust function that counts chars in a string.",
    },
    "observer": {
        "gguf": Path("/workspace/outputs/determinex-observer-v4/determinex-observer-v4.gguf"),
        "min_gb": 2.5,
        "max_gb": 4.0,
        "prompt": 'Is this code safe? fn main() { let x = vec![1,2,3]; println!("{}", x[10]); }',
    },
    "sentinel": {
        "gguf": Path("/workspace/outputs/determinex-sentinel-v3/determinex-sentinel-v3.gguf"),
        "min_gb": 6.0,
        "max_gb": 9.0,
        "prompt": "Plan the steps to implement a REST API in Rust using Axum.",
    },
}

LLAMA_CLI = Path("/workspace/llama.cpp/llama-cli")
# Retrain started after whitelist patch at approximately this time
RETRAIN_CUTOFF_TS = 1744596900  # 2026-04-14 04:15 UTC (after patch applied)


def check(label, ok, detail=""):
    icon = "PASS" if ok else "FAIL"
    print(f"  [{icon}] {label}" + (f" -- {detail}" if detail else ""))
    return ok


def verify(model_name):
    spec = MODELS[model_name]
    gguf = spec["gguf"]
    passed = True

    print(f"\n{'=' * 60}")
    print(f"  VERIFYING: {gguf.name}")
    print(f"{'=' * 60}")

    # ── CHECK 1: File exists ──────────────────────────────────────
    exists = gguf.exists()
    passed &= check("File exists", exists, str(gguf))
    if not exists:
        print("  [ABORT] File not found. Has the retrain completed?")
        return False

    # ── CHECK 2: Timestamp — must be AFTER whitelist patch ────────
    mtime = gguf.stat().st_mtime
    is_fresh = mtime > RETRAIN_CUTOFF_TS
    age = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
    passed &= check(
        "Timestamp is post-patch", is_fresh, f"File time: {age} | Cutoff: 2026-04-14 04:15:00"
    )
    if not is_fresh:
        print(
            "  [WARN] This GGUF predates the whitelist patch -- it's the BAD contaminated version!"
        )

    # ── CHECK 3: File size in expected range ──────────────────────
    size_gb = gguf.stat().st_size / 1e9
    in_range = spec["min_gb"] <= size_gb <= spec["max_gb"]
    passed &= check(
        f"Size in range [{spec['min_gb']}-{spec['max_gb']}] GB", in_range, f"{size_gb:.2f} GB"
    )

    # ── CHECK 4: GGUF header parse ────────────────────────────────
    # Try gguf-dump first, fall back to llama-cli --help trick
    dump_bin = Path("/workspace/llama.cpp/gguf-dump")
    if dump_bin.exists():
        result = subprocess.run(
            [str(dump_bin), str(gguf)], capture_output=True, text=True, timeout=30
        )
        header_ok = result.returncode == 0 and "general.architecture" in result.stdout
        passed &= check(
            "GGUF headers parse cleanly",
            header_ok,
            result.stderr[:120] if not header_ok else "architecture field present",
        )
    else:
        # Fallback: llama-cli will error fast if GGUF is corrupt
        result = subprocess.run(
            [str(LLAMA_CLI), "-m", str(gguf), "-n", "1", "--prompt", "hi", "--n-gpu-layers", "0"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        # llama-cli exits non-zero if GGUF is unreadable
        header_ok = "error" not in result.stderr.lower()[:200] or result.returncode == 0
        passed &= check(
            "llama-cli loads GGUF",
            result.returncode == 0,
            result.stderr[:120] if result.returncode != 0 else "OK",
        )

    # ── CHECK 5: Smoke test — first coherent token ────────────────
    if LLAMA_CLI.exists():
        result = subprocess.run(
            [
                str(LLAMA_CLI),
                "-m",
                str(gguf),
                "-n",
                "32",
                "--prompt",
                spec["prompt"],
                "--n-gpu-layers",
                "0",  # CPU only for verification (no VRAM allocation)
                "--log-disable",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        output = (result.stdout + result.stderr).strip()
        has_output = len(output) > 20 and result.returncode == 0
        snippet = output[:100].replace("\n", " ")
        passed &= check("Smoke test produces output", has_output, snippet)
    else:
        print("  [SKIP] llama-cli not found -- skipping smoke test")

    # ── VERDICT ───────────────────────────────────────────────────
    print(f"\n{'=' * 60}")
    if passed:
        print(
            f"  VERDICT: PASS -- safe to SCP {model_name} to ${{DETERMINEX_MODELS_DIR:-~/determinex-models}}/"
        )
    else:
        print("  VERDICT: FAIL -- DO NOT DOWNLOAD. Investigate before overwriting.")
    print(f"{'=' * 60}\n")
    return passed


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in MODELS:
        print(f"Usage: python3 verify_gguf.py [{'|'.join(MODELS)}]")
        sys.exit(1)

    ok = verify(sys.argv[1])
    sys.exit(0 if ok else 1)
