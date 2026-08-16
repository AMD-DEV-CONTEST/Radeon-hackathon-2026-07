#!/usr/bin/env bash
set -euo pipefail

ROOT=/persistent/silent-core
set -a
source "$ROOT/config.env"
set +a
AUTH="Authorization: Bearer $SILENT_CORE_API_KEY"
BASE=http://127.0.0.1:18000

curl --fail --silent --show-error "$BASE/health" >"$ROOT/logs/smoke-health.json"
curl --fail --silent --show-error -H "$AUTH" "$BASE/v1/models" >"$ROOT/logs/smoke-models.json"

curl --fail --silent --show-error --max-time 300 \
  -H "$AUTH" -H 'Content-Type: application/json' \
  "$BASE/v1/chat/completions" \
  -d '{"model":"silent-core/llm","messages":[{"role":"user","content":"Reply with exactly: Silent Core is ready."}],"max_tokens":32,"temperature":0,"chat_template_kwargs":{"enable_thinking":false}}' \
  >"$ROOT/logs/smoke-chat.json"

curl --fail --silent --show-error --max-time 300 \
  -H "$AUTH" -H 'Content-Type: application/json' \
  "$BASE/v1/audio/speech" \
  -d '{"model":"silent-core/tts","voice":"heart","input":"Silent Core English speech service is ready.","response_format":"wav"}' \
  >"$ROOT/logs/smoke-tts.wav"

curl --fail --silent --show-error --max-time 600 \
  -H "$AUTH" -H 'Content-Type: application/json' \
  "$BASE/v1/images/generations" \
  -d '{"model":"silent-core/image","prompt":"A silver compass on an ancient map, cinematic fantasy concept art","size":"512x512","response_format":"b64_json"}' \
  >"$ROOT/logs/smoke-image.json"

/opt/venv/bin/python - <<'PY'
import base64
import json
from pathlib import Path

root = Path('/persistent/silent-core/logs')
chat = json.loads((root / 'smoke-chat.json').read_text())
assert chat['choices'][0]['message']['content']
image = json.loads((root / 'smoke-image.json').read_text())
(root / 'smoke-image.png').write_bytes(base64.b64decode(image['data'][0]['b64_json']))
assert (root / 'smoke-tts.wav').stat().st_size > 1000
assert (root / 'smoke-image.png').stat().st_size > 1000
print(chat['choices'][0]['message']['content'])
print('tts_bytes', (root / 'smoke-tts.wav').stat().st_size)
print('image_bytes', (root / 'smoke-image.png').stat().st_size)
PY
