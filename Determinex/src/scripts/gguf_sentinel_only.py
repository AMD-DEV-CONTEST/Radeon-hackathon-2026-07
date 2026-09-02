#!/usr/bin/env python3
"""
Re-run ONLY the GGUF quantization for Sentinel v4-dsl.
Merged fp16 model already at /workspace/tmp_dsl_sen_merged/.
Skips retrain and adapter merge - jumps straight to convert + quantize.
"""

import shutil
import subprocess
import sys
import time
from pathlib import Path

MERGED_DIR = Path("/workspace/tmp_dsl_sen_merged")
OUT_DIR = Path("/workspace/outputs/determinex-sentinel-v4-dsl")
LLAMA_CPP = Path("/workspace/llama.cpp")
OUT_GGUF_F16 = OUT_DIR / "determinex-sentinel-v4-dsl-f16.gguf"
OUT_GGUF_FINAL = OUT_DIR / "determinex-sentinel-v4-dsl.gguf"
LOG_PATH = Path("/workspace/sentinel_gguf_retry.log")

log = open(LOG_PATH, "w", encoding="utf-8", buffering=1)


def log_print(msg):
    print(msg, flush=True)
    log.write(msg + "\n")
    log.flush()


def run(cmd, **kwargs):
    cmd_str = " ".join(str(c) for c in cmd)
    log_print(f"[CMD] {cmd_str}")
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, **kwargs)
    tail = r.stdout[-4000:] if len(r.stdout) > 4000 else r.stdout
    log_print(tail)
    if r.returncode != 0:
        log_print(f"[ERROR] exit code {r.returncode}")
        log.close()
        sys.exit(r.returncode)
    return r


# ── Verify merged model is intact ──────────────────────────────────────────
shards = sorted(MERGED_DIR.glob("model-*.safetensors"))
log_print(f"[INFO] Found {len(shards)} safetensor shards: {[s.name for s in shards]}")
assert len(shards) >= 1, "No safetensor shards found - merged model missing!"
total_gb = sum(s.stat().st_size for s in shards) / 1e9
log_print(f"[INFO] Total fp16 size: {total_gb:.1f} GB")
log_print(f"[INFO] config.json: {(MERGED_DIR / 'config.json').exists()}")

OUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Step 1: Convert fp16 safetensors -> GGUF F16 ───────────────────────────
log_print("\n[STEP 1] Converting fp16 safetensors -> GGUF F16...")
t0 = time.time()
run(
    [
        sys.executable,
        str(LLAMA_CPP / "convert_hf_to_gguf.py"),
        str(MERGED_DIR),
        "--outtype",
        "f16",
        "--outfile",
        str(OUT_GGUF_F16),
    ]
)
f16_gb = OUT_GGUF_F16.stat().st_size / 1e9
log_print(f"[INFO] F16 GGUF done in {time.time() - t0:.0f}s  size={f16_gb:.2f} GB")

# ── Step 2: Quantize F16 -> Q8_0 (or copy if no binary) ───────────────────
quantize_bin = LLAMA_CPP / "build" / "bin" / "llama-quantize"
log_print(f"\n[STEP 2] Quantize binary present: {quantize_bin.exists()}")

if quantize_bin.exists():
    log_print("[STEP 2] Quantizing F16 -> Q8_0...")
    t0 = time.time()
    run([str(quantize_bin), str(OUT_GGUF_F16), str(OUT_GGUF_FINAL), "Q8_0"])
    q8_gb = OUT_GGUF_FINAL.stat().st_size / 1e9
    log_print(f"[INFO] Q8_0 GGUF done in {time.time() - t0:.0f}s  size={q8_gb:.2f} GB")
    # Remove F16 intermediate to save workspace space
    OUT_GGUF_F16.unlink()
    log_print("[INFO] Removed F16 intermediate to save space")
else:
    log_print("[WARN] llama-quantize not found - using F16 GGUF as final (larger but valid)")
    shutil.move(str(OUT_GGUF_F16), str(OUT_GGUF_FINAL))

final_gb = OUT_GGUF_FINAL.stat().st_size / 1e9
log_print(f"\n[DONE] Sentinel GGUF ready: {OUT_GGUF_FINAL}")
log_print(f"[INFO] Final size: {final_gb:.2f} GB")
log_print("[INFO] Expected ~7.2 GB for Q8_0, ~14 GB for F16")
log.close()
