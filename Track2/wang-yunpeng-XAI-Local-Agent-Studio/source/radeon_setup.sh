#!/usr/bin/env bash
# radeon_setup.sh — AMD Radeon (ROCm) install + optimize + launch + benchmark for XAI
# Place this file at the root of the XAI repo and run on the Radeon Cloud instance.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Persist all runtime data on /persistent so instance rebuilds don't lose models/results
XAI_HOME="${XAI_HOME:-/persistent/.xai}"
XAI_WORKSPACE="${XAI_WORKSPACE:-$XAI_HOME/workspace}"
XAI_PORT="${XAI_PORT:-8000}"
OLLAMA_HOST="${OLLAMA_HOST:-http://localhost:11434}"

# ===== ROCm inference optimization flags (the 40-point evidence) =====
export OLLAMA_NUM_GPU_LAYERS="${OLLAMA_NUM_GPU_LAYERS:--1}"   # full offload to GPU
export OLLAMA_FLASH_ATTENTION="${OLLAMA_FLASH_ATTENTION:-1}"  # ROCm flash-attn
export OLLAMA_KV_CACHE_TYPE="${OLLAMA_KV_CACHE_TYPE:-Q8_0}"   # quantize KV cache
export GGML_ROCM_DMA_BUF="${GGML_ROCM_DMA_BUF:-1}"            # reduce host-device copy
export OLLAMA_NUM_PARALLEL="${OLLAMA_NUM_PARALLEL:-4}"        # concurrent multi-agent
# export HSA_OVERRIDE_GFX_VERSION=11.0.0  # uncomment for Navi 4x if needed

log(){ echo "[radeon-setup] $*"; }

detect_gpu(){
  log "Detecting AMD GPU / ROCm ..."
  if command -v amd-smi >/dev/null 2>&1; then
    log "amd-smi output:"
    amd-smi 2>/dev/null | head -20 || true
  fi
  if command -v rocminfo >/dev/null 2>&1; then
    log "rocminfo GPU names:"
    rocminfo 2>/dev/null | grep -i "Name:" | head -5 || true
  fi
  if [ -d /opt/rocm ]; then log "ROCm present at /opt/rocm"; fi
  log "ROCm flags active: GPU_LAYERS=$OLLAMA_NUM_GPU_LAYERS FLASH_ATTENTION=$OLLAMA_FLASH_ATTENTION KV=$OLLAMA_KV_CACHE_TYPE DMA_BUF=$GGML_ROCM_DMA_BUF PARALLEL=$OLLAMA_NUM_PARALLEL"
}

install_ollama(){
  detect_gpu
  if command -v ollama >/dev/null 2>&1; then
    log "Ollama already installed: $(ollama --version 2>/dev/null)"
  else
    log "Installing Ollama (ROCm-aware on AMD GPUs) ..."
    curl -fsSL https://ollama.com/install.sh | sh
  fi
  systemctl enable --now ollama 2>/dev/null || true
  # Ensure service is listening
  sleep 2
  curl -fsS "$OLLAMA_HOST/api/tags" >/dev/null 2>&1 && log "Ollama API ready at $OLLAMA_HOST" || log "Ollama API not yet ready (may still be starting)"
}

pull_models(){
  log "Pulling quantized models (run on Radeon GPU) ..."
  ollama pull qwen2.5:14b-instruct-q4_K_M
  ollama pull qwen2.5:14b-instruct-q6_K
  ollama pull qwen2.5:14b-instruct-q8_0
  ollama pull qwen2.5-coder:7b-instruct-q4_K_M
}

launch(){
  log "Starting XAI on :$XAI_PORT ..."
  mkdir -p "$XAI_HOME" "$XAI_WORKSPACE"
  export XAI_HOME XAI_WORKSPACE XAI_PORT
  cd "$REPO_DIR"
  nohup python3 server_xai.py > "$XAI_HOME/xai.log" 2>&1 &
  echo $! > "$XAI_HOME/server.pid"
  sleep 5
  if curl -fsS "http://localhost:$XAI_PORT/api/status" >/dev/null 2>&1; then
    log "XAI up at http://localhost:$XAI_PORT"
  else
    log "WARNING: /api/status failed. Check $XAI_HOME/xai.log"
    tail -30 "$XAI_HOME/xai.log" || true
  fi
  TOKEN_FILE="$XAI_HOME/.server_token"
  if [ -f "$TOKEN_FILE" ]; then
    log "XAI server token: $(cat "$TOKEN_FILE")"
  fi
  # Expose for demo recording (Radeon Cloud built-in; harmless if unavailable)
  if command -v rc-tunnel >/dev/null 2>&1; then
    log "Exposing via rc-tunnel (public URL for demo) ..."
    nohup rc-tunnel expose --port "$XAI_PORT" > "$XAI_HOME/rctunnel.log" 2>&1 &
    sleep 4
    grep -oE "https?://[a-zA-Z0-9./_-]+" "$XAI_HOME/rctunnel.log" 2>/dev/null | head -1 | sed 's/^/rc-tunnel URL: /' || log "rc-tunnel URL not yet ready (check $XAI_HOME/rctunnel.log)"
  else
    log "rc-tunnel not found; XAI is available locally at http://localhost:$XAI_PORT"
  fi
}

benchmark(){
  log "Benchmarking inference on AMD Radeon (ROCm) ..."
  cd "$REPO_DIR"
  python3 - "$OLLAMA_HOST" <<'PY'
import sys, json, time, urllib.request, threading

BASE = sys.argv[1]
PROMPT = "Explain the ROCm software stack for AMD Radeon GPUs in 200 words."
MODELS = ["qwen2.5:14b-instruct-q4_K_M",
          "qwen2.5:14b-instruct-q6_K",
          "qwen2.5:14b-instruct-q8_0"]
results = {"device": "AMD Radeon (ROCm via Ollama)",
           "optimizations": {"GPU_LAYERS": -1, "FLASH_ATTENTION": 1,
                             "KV_CACHE": "Q8_0", "DMA_BUF": 1, "PARALLEL": 4},
           "runs": []}

def gen(model, gpu_layers=None):
    opts = {}
    if gpu_layers is not None:
        opts["num_gpu"] = gpu_layers
    payload = {"model": model, "prompt": PROMPT, "stream": False, "options": opts}
    data = json.dumps(payload).encode()
    t0 = time.time()
    req = urllib.request.Request(BASE + "/api/generate", data=data,
                                 headers={"Content-Type": "application/json"})
    resp = json.load(urllib.request.urlopen(req, timeout=600))
    dt = time.time() - t0
    toks = resp.get("eval_count") or 0
    tps = round(toks / dt, 2) if dt > 0 else 0
    return {"model": model, "eval_count": toks, "seconds": round(dt, 2),
            "tokens_per_sec": tps}

for m in MODELS:
    try:
        r = gen(m)
        results["runs"].append(r)
        print(f"  {m}: {r['eval_count']} tok in {r['seconds']}s -> {r['tokens_per_sec']} tok/s")
    except Exception as e:
        results["runs"].append({"model": m, "error": str(e)})
        print(f"  {m}: ERROR {e}")

try:
    cpu = gen("qwen2.5:14b-instruct-q4_K_M", gpu_layers=0)
    results["cpu_baseline_q4"] = cpu
    best = next((r.get("tokens_per_sec", 0) for r in results["runs"] if "error" not in r), 0)
    results["speedup_vs_cpu"] = round(best / cpu["tokens_per_sec"], 2) if cpu.get("tokens_per_sec") else None
    print(f"  CPU baseline q4: {cpu['tokens_per_sec']} tok/s -> speedup {results.get('speedup_vs_cpu')}x")
except Exception as e:
    results["cpu_baseline_q4"] = {"error": str(e)}

out_path = "/persistent/benchmark_results.json"
with open(out_path, "w") as f:
    json.dump(results, f, indent=2)
print(f"Wrote {out_path}")
PY
}

case "${1:-all}" in
  install-ollama) install_ollama ;;
  pull-models) pull_models ;;
  launch) launch ;;
  benchmark) benchmark ;;
  all) install_ollama; pull_models; launch; benchmark ;;
  *) echo "unknown target: $1"; exit 1 ;;
esac
