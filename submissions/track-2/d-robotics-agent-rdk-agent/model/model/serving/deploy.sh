#!/usr/bin/env bash
# One-command deployment of Qwen3-32B-Agentic-SFT-r1-v3 on an AMD Radeon (gfx1100) host.
#
#   bash deploy.sh
#
# Steps: preflight -> download base + adapter -> fail-closed SHA-256 check ->
# install pinned deps -> start server -> wait for /health.
# Every step is skipped if already satisfied, so re-running is safe.
#
# Environment overrides: BASE_MODEL, ADAPTER, API_KEY_FILE, PORT, SKIP_DEPS=1
# DRY_RUN=1 stops after the identity check (verify host + artifacts, start nothing).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_MODEL="${BASE_MODEL:-$HERE/base}"
ADAPTER="${ADAPTER:-$HERE/adapter}"
API_KEY_FILE="${API_KEY_FILE:-$HERE/api_key}"
PORT="${PORT:-8000}"

BASE_REPO="unsloth/Qwen3-32B-bnb-4bit"
BASE_REVISION="7f721e74a6a8cc9ee352f7e49303a2c1705f9083"
ADAPTER_REPO="ming01/Qwen3-32B-Agentic-SFT-r1-v3"
ADAPTER_SHA256="4dcee6914e3f9c61aeb33529208bf7e63f37c4c5ae5e0e37e7f7c6b3bfff20bf"

say() { printf '\n== %s ==\n' "$*"; }
die() { printf '\nFAILED: %s\n' "$*" >&2; exit 1; }
sha256_of() {
  if command -v sha256sum >/dev/null; then sha256sum "$1" | cut -d' ' -f1
  else shasum -a 256 "$1" | cut -d' ' -f1; fi
}

say "1/5 preflight"
command -v python3 >/dev/null || die "python3 not found"
PYV="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
python3 -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3,10) else 1)' \
  || die "python3 $PYV is too old; the proven environment is 3.12"
python3 - <<'PY' || die "PyTorch cannot see a GPU. Install a ROCm build first:
  pip install torch --index-url https://download.pytorch.org/whl/rocm7.2
(this script does not install ROCm itself; proven stack: ROCm 7.2.1 + torch 2.9.1+rocm7.2.0)"
import sys
try:
    import torch
except ModuleNotFoundError:
    sys.exit(1)
sys.exit(0 if torch.cuda.is_available() else 1)
PY
python3 -c 'import torch; p=torch.cuda.get_device_properties(0); print(f"  python {__import__("sys").version.split()[0]} | torch {torch.__version__} | {p.gcnArchName} | {p.total_memory//2**30} GiB")'

say "2/5 download weights (skipped if already present)"
if [ ! -f "$BASE_MODEL/config.json" ]; then
  if command -v hf >/dev/null; then HF=(hf download)
  elif command -v huggingface-cli >/dev/null; then HF=(huggingface-cli download)
  else die "no Hugging Face CLI; run: pip install -U huggingface_hub"; fi
  "${HF[@]}" "$BASE_REPO" --revision "$BASE_REVISION" --local-dir "$BASE_MODEL"
else
  echo "  base already at $BASE_MODEL"
fi
if [ ! -f "$ADAPTER/adapter_model.safetensors" ]; then
  command -v modelscope >/dev/null || die "modelscope CLI missing; run: pip install -U modelscope"
  modelscope download "$ADAPTER_REPO" --local_dir "$ADAPTER"
else
  echo "  adapter already at $ADAPTER"
fi

say "3/5 verify adapter identity (fail-closed)"
ACTUAL="$(sha256_of "$ADAPTER/adapter_model.safetensors")"
[ "$ACTUAL" = "$ADAPTER_SHA256" ] || die "adapter SHA-256 mismatch
  expected $ADAPTER_SHA256
  actual   $ACTUAL
Refusing to serve a model whose identity does not match the published artifact."
echo "  adapter_model.safetensors $ACTUAL  OK"
[ "${DRY_RUN:-0}" = "1" ] && { echo; echo "DRY_RUN=1: host and artifacts verified, nothing started."; exit 0; }

say "4/5 dependencies"
if [ "${SKIP_DEPS:-0}" = "1" ]; then
  echo "  SKIP_DEPS=1, skipping"
else
  python3 -m pip install -q -r "$HERE/requirements-serving.txt"
  echo "  pinned serving dependencies installed"
fi
[ -s "$API_KEY_FILE" ] || { python3 -c 'import secrets; print(secrets.token_urlsafe(32))' > "$API_KEY_FILE"; chmod 600 "$API_KEY_FILE"; echo "  generated $API_KEY_FILE"; }

say "5/5 start server and wait for /health"
BASE_MODEL="$BASE_MODEL" ADAPTER="$ADAPTER" API_KEY_FILE="$API_KEY_FILE" PORT="$PORT" \
  nohup bash "$HERE/serve.sh" > "$HERE/server.log" 2>&1 &
SERVER_PID=$!
for _ in $(seq 1 180); do
  if HEALTH="$(curl -fsS "http://127.0.0.1:$PORT/health" 2>/dev/null)"; then
    echo "  $HEALTH"
    case "$HEALTH" in
      *checkpoint-000119*) ;;
      *) die "service is up but does not report checkpoint-000119" ;;
    esac
    cat <<EOF

Ready. Model loaded with the verified adapter.

  Base URL   http://127.0.0.1:$PORT/v1
  Model      Qwen3-32B-Agentic-SFT-r1-v3
  API key    $API_KEY_FILE
  Log        $HERE/server.log   (stop with: kill $SERVER_PID)

Optional proof that the adapter is active:
  python3 ../ab-probe/probe.py "$API_KEY_FILE" probe-out.json
EOF
    exit 0
  fi
  kill -0 "$SERVER_PID" 2>/dev/null || die "server exited during startup; see $HERE/server.log"
  sleep 2
done
die "server did not become healthy within 360s; see $HERE/server.log"
