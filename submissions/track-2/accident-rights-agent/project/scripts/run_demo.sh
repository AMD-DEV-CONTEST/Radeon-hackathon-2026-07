#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir"

python_bin="${ACCIDENT_RIGHTS_PYTHON:-$repo_dir/.venv/bin/python}"
demo_mode="${DEMO_MODE:-mock}"
model_mode="${MODEL_MODE:-$demo_mode}"
server_name="${GRADIO_SERVER_NAME:-127.0.0.1}"
server_port="${GRADIO_SERVER_PORT:-7860}"
case_root="${CASE_ROOT:-data/cases}"
checkpoint_db="${ORCHESTRATOR_CHECKPOINT_DB:-data/checkpoints/orchestrator.sqlite3}"
qdrant_path="${QDRANT_PATH:-data/qdrant/legal}"
legal_corpus="${LEGAL_CORPUS_DB:-data/laws/legal_corpus.sqlite3}"
report_root="${REPORT_ROOT:-artifacts/demo_reports}"
runtime_dir="${DEMO_RUNTIME_DIR:-artifacts/demo_runtime}"

if [[ "$model_mode" != "mock" && "$model_mode" != "local_vllm" ]]; then
  echo "MODEL_MODE must be mock or local_vllm."
  exit 2
fi
if [[ ! -x "$python_bin" ]]; then
  echo "Python environment not found: $python_bin"
  echo "Create .venv and install requirements.lock first."
  exit 1
fi

mkdir -p "$runtime_dir" "$case_root" "$(dirname "$checkpoint_db")" "$report_root"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
log_path="$runtime_dir/gradio-$timestamp.log"

if [[ ! -f "$legal_corpus" || ! -f "$qdrant_path/meta.json" ]]; then
  echo "Preparing verified local legal corpus and hash index..."
  EMBEDDING_PROVIDER=hash "$python_bin" scripts/ingest_laws.py \
    --embedding-provider hash \
    --corpus-db "$legal_corpus" \
    --qdrant-path "$qdrant_path"
fi

MODEL_MODE="$model_mode" \
GRADIO_ANALYTICS_ENABLED=False \
  "$python_bin" -m app.ui.doctor \
  --mode "$model_mode" \
  --case-root "$case_root" \
  --checkpoint "$checkpoint_db" \
  --legal-corpus "$legal_corpus" \
  --qdrant "$qdrant_path" \
  --host "$server_name" \
  --port "$server_port" \
  --prepare

app_pid=""
shutdown() {
  if [[ -n "$app_pid" ]] && kill -0 "$app_pid" 2>/dev/null; then
    kill -TERM "$app_pid" 2>/dev/null || true
    wait "$app_pid" 2>/dev/null || true
  fi
}
trap shutdown INT TERM EXIT

echo "Starting Accident Rights Agent UI"
echo "Address: http://$server_name:$server_port"
echo "Mode: $model_mode"
echo "Golden fixture: CASE-GOLDEN-DEMO"
echo "Log: $log_path"

MODEL_MODE="$model_mode" \
GRADIO_ANALYTICS_ENABLED=False \
CASE_ROOT="$case_root" \
ORCHESTRATOR_CHECKPOINT_DB="$checkpoint_db" \
LEGAL_CORPUS_DB="$legal_corpus" \
QDRANT_PATH="$qdrant_path" \
REPORT_ROOT="$report_root" \
  "$python_bin" -m app.ui.gradio_app \
  --host "$server_name" \
  --port "$server_port" \
  --case-root "$case_root" \
  --checkpoint "$checkpoint_db" \
  --report-root "$report_root" \
  >"$log_path" 2>&1 &
app_pid="$!"
wait "$app_pid"
