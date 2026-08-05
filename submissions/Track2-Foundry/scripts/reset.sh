#!/usr/bin/env bash
# Foundry reset: stop everything, verify the GPU is actually released,
# archive runs/ (a tarball copy — runs/ itself is NOT deleted: it is the
# evidence trail), then bring the stack back up via up.sh.
set -u
cd "$(dirname "$0")/.."

say() { printf '%s\n' "== $*"; }

# --- 1. stop in-flight work ----------------------------------------------
say "stopping serve_ui, pipeline stages, llama-server"
pkill -f serve_ui.py     2>/dev/null && say "  serve_ui stopped"
pkill -f run_slice.py    2>/dev/null && say "  pipeline stage stopped"
pkill -f run_bench.py    2>/dev/null && say "  bench stopped"
pkill -f llama-server    2>/dev/null && say "  llama-server stopped"
sleep 3

# --- 2. verify GPU memory is released -------------------------------------
gpu_used_mb() {
  if command -v rocm-smi > /dev/null 2>&1; then
    rocm-smi --showmeminfo vram --json 2>/dev/null \
      | python3 -c "import json,sys; d=json.load(sys.stdin); print(int(next(iter(d.values()))['VRAM Total Used Memory (B)'])//2**20)" 2>/dev/null && return
  fi
  if command -v nvidia-smi > /dev/null 2>&1; then
    nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | head -1 && return
  fi
  echo "-1"
}

RELEASED=""
for _ in $(seq 1 15); do
  USED="$(gpu_used_mb)"
  if [ "$USED" = "-1" ] || [ "$USED" -lt 2048 ]; then RELEASED=1; break; fi
  sleep 2
done
if [ -n "$RELEASED" ]; then
  say "GPU memory released (${USED:-unknown} MB in use)"
else
  echo "NOT READY: GPU still holds ${USED} MB after 30s — a process is stuck."
  echo "Inspect with: ps aux | grep -E 'llama|python'"
  exit 1
fi

# --- 3. archive runs/ (copy, not move) ------------------------------------
if [ -d runs ]; then
  mkdir -p archives
  STAMP="$(date +%Y%m%d-%H%M%S)"
  tar --exclude='*.gguf' --exclude='merged' --exclude='adapter' \
      -czf "archives/runs-$STAMP.tar.gz" runs
  say "runs/ archived to archives/runs-$STAMP.tar.gz (runs/ left in place)"
fi

# --- 4. bring it back up ---------------------------------------------------
exec "$(dirname "$0")/up.sh"
