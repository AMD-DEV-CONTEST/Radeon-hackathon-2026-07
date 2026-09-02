#!/usr/bin/env bash

set -euo pipefail

COMFY_URL="${COMFY_URL:-http://127.0.0.1:8188}"
WORKFLOW_FILE="${1:-}"
PROJECT_ROOT="/workspace/poster-engine"
RESULT_DIR="$PROJECT_ROOT/results"

if [[ -z "$WORKFLOW_FILE" ]]; then
  echo "用法:"
  echo "  $0 /path/to/poster-v1-api.json"
  exit 1
fi

if [[ ! -f "$WORKFLOW_FILE" ]]; then
  echo "找不到 workflow 文件: $WORKFLOW_FILE"
  exit 1
fi

mkdir -p "$RESULT_DIR"

echo "1. 检查 ComfyUI..."
curl -fsS "$COMFY_URL/system_stats" >/tmp/comfy_system_stats.json
echo "ComfyUI 正常。"

echo "2. 验证 API Workflow 格式..."
python3 - "$WORKFLOW_FILE" <<'PY'
import json
import sys

path = sys.argv[1]

with open(path, "r", encoding="utf-8") as f:
    workflow = json.load(f)

if not isinstance(workflow, dict) or not workflow:
    raise SystemExit("Workflow 顶层必须是非空 JSON 对象")

invalid = []

for node_id, node in workflow.items():
    if not isinstance(node, dict):
        invalid.append(node_id)
        continue

    if "class_type" not in node or "inputs" not in node:
        invalid.append(node_id)

if invalid:
    raise SystemExit(
        "这可能不是 API 格式 Workflow。异常节点: "
        + ", ".join(map(str, invalid[:10]))
    )

print(f"Workflow 验证成功，共 {len(workflow)} 个节点")
PY

REQUEST_FILE="/tmp/comfy_request.json"
SUBMIT_FILE="/tmp/comfy_submit.json"
HISTORY_FILE="/tmp/comfy_history.json"

echo "3. 构造请求..."
python3 - "$WORKFLOW_FILE" "$REQUEST_FILE" <<'PY'
import json
import sys
import uuid

workflow_path = sys.argv[1]
request_path = sys.argv[2]

with open(workflow_path, "r", encoding="utf-8") as f:
    workflow = json.load(f)

payload = {
    "prompt": workflow,
    "client_id": f"poster-smoke-{uuid.uuid4()}",
}

with open(request_path, "w", encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False)

print(request_path)
PY

echo "4. 提交到 ComfyUI /prompt..."

HTTP_CODE="$(
  curl -sS \
    -o "$SUBMIT_FILE" \
    -w "%{http_code}" \
    -X POST "$COMFY_URL/prompt" \
    -H "Content-Type: application/json" \
    --data-binary "@$REQUEST_FILE"
)"

echo "HTTP 状态码: $HTTP_CODE"
cat "$SUBMIT_FILE"
echo

if [[ "$HTTP_CODE" != "200" ]]; then
  echo "提交失败。查看上面的 error 和 node_errors。"
  exit 1
fi

PROMPT_ID="$(
  python3 - "$SUBMIT_FILE" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as f:
    data = json.load(f)

prompt_id = data.get("prompt_id")

if not prompt_id:
    print(
        json.dumps(data, ensure_ascii=False, indent=2),
        file=sys.stderr,
    )
    raise SystemExit("响应里没有 prompt_id")

print(prompt_id)
PY
)"

echo
echo "prompt_id: $PROMPT_ID"
echo "5. 等待任务完成..."

COMPLETED=0

for i in $(seq 1 900); do
  curl -fsS \
    "$COMFY_URL/history/$PROMPT_ID" \
    -o "$HISTORY_FILE"

  STATE="$(
    python3 - "$HISTORY_FILE" "$PROMPT_ID" <<'PY'
import json
import sys

path = sys.argv[1]
prompt_id = sys.argv[2]

with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)

entry = data.get(prompt_id)

if not entry:
    print("waiting")
    raise SystemExit(0)

status = entry.get("status", {})

if status.get("status_str") == "error":
    print("error")
elif entry.get("outputs") is not None:
    print("done")
else:
    print("waiting")
PY
  )"

  if [[ "$STATE" == "done" ]]; then
    COMPLETED=1
    echo
    echo "任务完成。"
    break
  fi

  if [[ "$STATE" == "error" ]]; then
    echo
    echo "ComfyUI 执行失败："
    python3 -m json.tool "$HISTORY_FILE"
    exit 1
  fi

  printf "\r等待中: %s 秒" "$i"
  sleep 1
done

if [[ "$COMPLETED" != "1" ]]; then
  echo
  echo "等待超时。prompt_id: $PROMPT_ID"
  exit 1
fi

META_FILE="/tmp/comfy_output_meta.txt"

python3 - "$HISTORY_FILE" "$PROMPT_ID" >"$META_FILE" <<'PY'
import json
import sys

history_path = sys.argv[1]
prompt_id = sys.argv[2]

with open(history_path, "r", encoding="utf-8") as f:
    data = json.load(f)

entry = data[prompt_id]
outputs = entry.get("outputs", {})

for node_id, output in outputs.items():
    for image in output.get("images", []):
        print(image.get("filename", ""))
        print(image.get("subfolder", ""))
        print(image.get("type", "output"))
        raise SystemExit(0)

raise SystemExit("任务完成，但没有找到 images 输出")
PY

mapfile -t META <"$META_FILE"

FILENAME="${META[0]}"
SUBFOLDER="${META[1]}"
FILE_TYPE="${META[2]}"

QUERY="$(
  python3 - "$FILENAME" "$SUBFOLDER" "$FILE_TYPE" <<'PY'
import sys
from urllib.parse import urlencode

print(urlencode({
    "filename": sys.argv[1],
    "subfolder": sys.argv[2],
    "type": sys.argv[3],
}))
PY
)"

EXTENSION="${FILENAME##*.}"
OUTPUT_FILE="$RESULT_DIR/api-smoke-${PROMPT_ID}.${EXTENSION}"

echo "6. 下载生成结果..."
curl -fsS "$COMFY_URL/view?$QUERY" -o "$OUTPUT_FILE"

echo
echo "========================================"
echo "ComfyUI API 全链路测试成功"
echo "prompt_id: $PROMPT_ID"
echo "ComfyUI 文件: $FILENAME"
echo "本地结果: $OUTPUT_FILE"
echo "========================================"
