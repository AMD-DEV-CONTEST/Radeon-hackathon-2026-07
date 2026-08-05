#!/usr/bin/env bash
# Foundry bring-up: from a bare instance to a verified-ready UI.
# Idempotent — safe to re-run. Env overrides:
#   FOUNDRY_CONFIG (default configs/cloud_radeon.toml)
#   FOUNDRY_VENV   (default /opt/venv; note: system pip on these images
#                   is PEP 668 locked — never install outside the venv)
#   FOUNDRY_MODEL_CACHE (model download dir shared across instance
#                   rebuilds; default /workspace/foundry-models when
#                   /workspace is writable; "none" disables)
#   LLAMA_CPP_HOME (llama.cpp checkout/install, if not /opt/llama.cpp)
#   LLAMA_CPP_BUILD=1  build llama.cpp from source if none is found
#   HOST (default 127.0.0.1), PORT (default 8300)
set -u
cd "$(dirname "$0")/.."

CONFIG="${FOUNDRY_CONFIG:-configs/cloud_radeon.toml}"
VENV="${FOUNDRY_VENV:-/opt/venv}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8300}"
FAIL=""

say() { printf '%s\n' "== $*"; }

# --- 1. venv -------------------------------------------------------------
if [ ! -x "$VENV/bin/python" ]; then
  say "venv not found at $VENV — creating"
  python3 -m venv "$VENV" || { echo "NOT READY: cannot create venv"; exit 1; }
fi
PY="$VENV/bin/python"; PIP="$VENV/bin/pip"

# --- 2. model cache ------------------------------------------------------
# /workspace is the volume the transfer tarball rides in on; if it
# persists across instance rebuilds, cached models turn the next
# bring-up's 19GB of downloads into zero.
link_into_cache() {
  # Point $1 at cache dir $2 unless real files already live at $1.
  target="$1"; cache="$2"
  [ -L "$target" ] && return 0
  if [ -d "$target" ] && [ -n "$(ls -A "$target" 2>/dev/null)" ]; then
    return 0
  fi
  rmdir "$target" 2>/dev/null
  ln -s "$cache" "$target"
}

CACHE="${FOUNDRY_MODEL_CACHE:-}"
if [ -z "$CACHE" ] && [ -d /workspace ] && [ -w /workspace ]; then
  CACHE=/workspace/foundry-models
fi
if [ -n "$CACHE" ] && [ "$CACHE" != "none" ]; then
  say "model cache: $CACHE"
  mkdir -p "$CACHE/teacher" "$CACHE/student/Qwen3-0.6B" models/student
  link_into_cache models/teacher "$CACHE/teacher"
  link_into_cache models/student/Qwen3-0.6B "$CACHE/student/Qwen3-0.6B"
fi

# --- 3. kick off downloads + deps FIRST (a source build may follow) ------
# hf_transfer/Xet saturate the pipe instead of single-streaming; either
# accel is optional — a plain retry covers repos or hub versions that
# reject it.
if "$PIP" install --quiet hf_transfer 2>/dev/null; then
  export HF_HUB_ENABLE_HF_TRANSFER=1
fi
export HF_XET_HIGH_PERFORMANCE=1

hf_fetch() {
  "$VENV/bin/hf" download "$@" && return 0
  if [ "${HF_HUB_ENABLE_HF_TRANSFER:-0}" = "1" ]; then
    echo "hf_transfer path failed; retrying standard download"
    HF_HUB_ENABLE_HF_TRANSFER=0 "$VENV/bin/hf" download "$@"
  fi
}

say "starting model downloads + deps in background (logs: pip.log, teacher-dl.log, student-dl.log)"
"$PIP" install --quiet requests sentencepiece protobuf matplotlib flask pytest \
    > pip.log 2>&1 & PIP_PID=$!
hf_fetch unsloth/Qwen3-30B-A3B-Instruct-2507-GGUF \
    Qwen3-30B-A3B-Instruct-2507-Q4_K_M.gguf --local-dir models/teacher \
    > teacher-dl.log 2>&1 & TDL_PID=$!
hf_fetch Qwen/Qwen3-0.6B --local-dir models/student/Qwen3-0.6B \
    > student-dl.log 2>&1 & SDL_PID=$!

# --- 4. llama.cpp (overlaps with the downloads above) --------------------
find_server() {
  for h in "${LLAMA_CPP_HOME:-}" /opt/llama.cpp "$HOME/llama.cpp"; do
    [ -n "$h" ] || continue
    for c in "$h/build/bin/llama-server" "$h/bin/llama-server" "$h/llama-server"; do
      [ -x "$c" ] && { echo "$c"; return 0; }
    done
  done
  return 1
}
SERVER="$(find_server || true)"
if [ -z "$SERVER" ]; then
  if [ "${LLAMA_CPP_BUILD:-0}" = "1" ]; then
    say "building llama.cpp (this takes ~10 min; downloads continue in background)"
    git clone --depth 1 https://github.com/ggml-org/llama.cpp "$HOME/llama.cpp"
    cmake -S "$HOME/llama.cpp" -B "$HOME/llama.cpp/build" -DGGML_HIP=ON -DCMAKE_BUILD_TYPE=Release
    cmake --build "$HOME/llama.cpp/build" -j"$(nproc)" --target llama-server llama-bench llama-quantize
    SERVER="$HOME/llama.cpp/build/bin/llama-server"
  else
    echo "NOT READY: no llama-server found (looked in \$LLAMA_CPP_HOME, /opt/llama.cpp, ~/llama.cpp)."
    echo "           Set LLAMA_CPP_HOME, or re-run with LLAMA_CPP_BUILD=1."
    echo "           (Background downloads keep running; a re-run resumes them.)"
    exit 1
  fi
fi
say "llama-server: $SERVER"
LLAMA_SRC="$(dirname "$(dirname "$(dirname "$SERVER")")")"
export LLAMA_CPP_HOME="${LLAMA_CPP_HOME:-$LLAMA_SRC}"

# gguf-py needs $LLAMA_SRC, and must not race the pip job above.
wait "$PIP_PID" || FAIL="$FAIL pip"
if [ -f "$LLAMA_SRC/gguf-py/pyproject.toml" ]; then
  "$PIP" install --quiet "$LLAMA_SRC/gguf-py" >> pip.log 2>&1 || FAIL="$FAIL gguf-py"
fi

# --- 5. wait for the downloads -------------------------------------------
TICKS=0
while kill -0 "$TDL_PID" 2>/dev/null; do
  sleep 5
  TICKS=$((TICKS + 1))
  if [ $((TICKS % 3)) -eq 0 ] && kill -0 "$TDL_PID" 2>/dev/null; then
    say "  teacher download: $(du -sh models/teacher/ 2>/dev/null | cut -f1) of ~18G"
  fi
done
wait "$TDL_PID" || FAIL="$FAIL teacher-model"
wait "$SDL_PID" || FAIL="$FAIL student-model"

# --- 6. start the UI (detached) -------------------------------------------
if curl -sf "http://127.0.0.1:$PORT/gpu" > /dev/null 2>&1; then
  say "UI already running on :$PORT — leaving it"
else
  say "starting serve_ui (log: ui.log)"
  nohup "$PY" serve_ui.py --config "$CONFIG" --host "$HOST" --port "$PORT" > ui.log 2>&1 &
fi

# --- 7. verify -----------------------------------------------------------
say "waiting for UI + teacher (30B model load takes ~2 min)"
UI_OK=""; TEACHER_OK=""
for _ in $(seq 1 260); do
  [ -z "$UI_OK" ] && curl -sf "http://127.0.0.1:$PORT/gpu" > /dev/null 2>&1 && UI_OK=1
  [ -z "$TEACHER_OK" ] && curl -sf "http://127.0.0.1:8123/health" > /dev/null 2>&1 && TEACHER_OK=1
  [ -n "$UI_OK" ] && [ -n "$TEACHER_OK" ] && break
  sleep 2
done

echo
if [ -n "$UI_OK" ] && [ -n "$TEACHER_OK" ] && [ -z "$FAIL" ]; then
  echo "READY  ->  http://127.0.0.1:$PORT   (bring-up took ${SECONDS}s)"
  echo "GPU:      $(curl -sf http://127.0.0.1:$PORT/gpu)"
  [ "$HOST" = "0.0.0.0" ] && echo "(bound to 0.0.0.0 — reachable on the instance's address)"
  exit 0
fi
echo "NOT READY:"
[ -z "$UI_OK" ]      && echo "  - UI on :$PORT never answered /gpu"
[ -z "$TEACHER_OK" ] && echo "  - teacher on :8123 never answered /health"
[ -n "$FAIL" ]       && echo "  - earlier step failed:$FAIL"
for f in ui.log teacher-dl.log student-dl.log pip.log; do
  [ -f "$f" ] && { echo "--- last 8 lines of $f ---"; tail -8 "$f"; }
done
exit 1
