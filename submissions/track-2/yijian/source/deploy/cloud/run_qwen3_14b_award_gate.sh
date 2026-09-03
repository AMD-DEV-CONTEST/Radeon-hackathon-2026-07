#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-train}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
PERSIST_ROOT="${YIJIAN_PERSIST_ROOT:-/persistent/yijian}"
CORPUS_ROOT="${YIJIAN_AGENT_CORPUS:-$PERSIST_ROOT/training-data/agent-sft-v1}"
MANIFEST="$CORPUS_ROOT/manifest.json"
PYTHON_BIN="${YIJIAN_TRAIN_PYTHON:-/workspace/yijian-venv/bin/python}"
WAS_27B_RUNNING=0

case "$MODE" in
  prepare|smoke|micro|full|train|coexist) ;;
  *) echo "用法: $0 [prepare|smoke|micro|full|train|coexist]" >&2; exit 2 ;;
esac

[[ -x "$PYTHON_BIN" ]] || { echo "缺少训练Python：$PYTHON_BIN" >&2; exit 2; }
if curl -fsS --max-time 2 http://127.0.0.1:8082/v1/models >/dev/null 2>&1; then
  WAS_27B_RUNNING=1
fi

restore_27b() {
  bash "$SCRIPT_DIR/stop_qwen3_14b_agent.sh" >/dev/null 2>&1 || true
  if [[ "$WAS_27B_RUNNING" == 1 ]]; then
    bash "$SCRIPT_DIR/start_qwen36_mentor.sh" || {
      echo "警告：27B自动恢复失败，请立即检查8082服务。" >&2
      return 1
    }
  fi
}
trap restore_27b EXIT

if [[ "$MODE" != "prepare" ]]; then
  [[ -f "$MANIFEST" ]] || { echo "缺少Agent训练manifest：$MANIFEST" >&2; exit 3; }
  "$PYTHON_BIN" - "$MANIFEST" <<'PY'
import json, sys
value=json.load(open(sys.argv[1], encoding="utf-8"))
expected={"planner":216,"answer":288,"followup":144,"memory_privacy":72}
if value.get("schemaVersion")!="yijian-agent-sft-v1" or value.get("passed") is not True:
    raise SystemExit("Agent训练manifest未通过")
if (value.get("counts") or {}).get("train") != 720:
    raise SystemExit("训练记录必须精确为720")
if value.get("taskCounts") != expected:
    raise SystemExit("任务配比不是216/288/144/72")
if value.get("split") != "video-game-position-isolated-three-way":
    raise SystemExit("三层隔离标记错误")
print("Agent 720条训练门禁通过")
PY
fi

if [[ "$WAS_27B_RUNNING" == 1 ]]; then
  bash "$SCRIPT_DIR/stop_qwen36_mentor.sh"
fi

case "$MODE" in
  prepare)
    bash "$SCRIPT_DIR/install_qwen3_14b_vllm.sh"
    ;;
  smoke|micro|full)
    bash "$PROJECT_ROOT/training/run_creator_lora.sh" "$MODE"
    ;;
  train)
    bash "$SCRIPT_DIR/install_qwen3_14b_vllm.sh"
    bash "$PROJECT_ROOT/training/run_creator_lora.sh" smoke
    bash "$PROJECT_ROOT/training/run_creator_lora.sh" micro
    bash "$PROJECT_ROOT/training/run_creator_lora.sh" full
    ;;
  coexist)
    bash "$SCRIPT_DIR/run_qwen3_14b_coexist_matrix.sh"
    ;;
esac
