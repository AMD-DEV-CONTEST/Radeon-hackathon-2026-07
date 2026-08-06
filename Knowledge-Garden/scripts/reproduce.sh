#!/bin/bash
# =============================================================================
# reproduce.sh — 一键复现 Knowledge Garden（Track 2, AMD AI DevMaster 2026-07）
#
# 作用：在一个全新实例上，从零完成：
#   1. 环境自检（GPU / ROCm / Python / vLLM）
#   2. 下载三个模型（已存在则跳过，断点续传）
#   3. 顺序启动 vLLM 双模型（14B 对话层 :8000 → 32B 批处理层 :8001）
#   4. 启动 FastAPI 后端 + Web UI（:8510）
#   5. 端到端健康检查
#
# 用法：bash reproduce.sh [--skip-models] [--models-dir <path>]
#   --skip-models   跳过模型下载（模型已存在时）
#   --models-dir    模型目录（默认 /persistent/models）
# =============================================================================
set -uo pipefail

# 比赛 fork 仓库（提交 PR 的目标仓库）。可用 --repo 覆盖。
REPO_URL="${REPO_URL:-https://github.com/mosyoyo/Radeon-hackathon-2026-07.git}"
REPO_BRANCH="${REPO_BRANCH:-main}"
WORK_ROOT="${WORK_ROOT:-/persistent}"
MODELS_DIR="${MODELS_DIR:-/persistent/models}"
SKIP_MODELS=0
for a in "$@"; do
  case "$a" in
    --skip-models) SKIP_MODELS=1 ;;
    --models-dir=*) MODELS_DIR="${a#*=}" ;;
    --repo=*) REPO_URL="${a#*=}" ;;
    --repo-branch=*) REPO_BRANCH="${a#*=}" ;;
  esac
done

log()  { printf '\033[1;33m[reproduce]\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m  ✓ %s\033[0m\n' "$*"; }
fail() { printf '\033[1;31m  ✗ %s\033[0m\n' "$*"; exit 1; }

# ---------------------------------------------------------------- 0. 获取代码
# 场景 A：已经在 Knowledge-Garden 目录内运行（scripts/reproduce.sh）
# 场景 B：在仓库根运行（Knowledge-Garden/scripts/reproduce.sh）
# 场景 C：全新实例 —— 从比赛 fork 仓库克隆
if [ -f "$(pwd)/app/main.py" ]; then
  ROOT="$(pwd)"
elif [ -f "$(pwd)/Knowledge-Garden/app/main.py" ]; then
  ROOT="$(pwd)/Knowledge-Garden"
elif [ -d "$WORK_ROOT/Knowledge-Garden/app" ]; then
  ROOT="$WORK_ROOT/Knowledge-Garden"
  ok "复用已有代码: $ROOT"
else
  log "0/5 从比赛 fork 仓库获取代码"
  mkdir -p "$WORK_ROOT"
  cd "$WORK_ROOT"
  if [ -d "$WORK_ROOT/Radeon-hackathon-2026-07" ]; then
    log "仓库已存在，更新..."
    cd "$WORK_ROOT/Radeon-hackathon-2026-07"
    git fetch origin "$REPO_BRANCH" 2>/dev/null || true
    git checkout "$REPO_BRANCH" 2>/dev/null || git checkout -b "$REPO_BRANCH" origin/"$REPO_BRANCH" 2>/dev/null || true
  else
    log "克隆 $REPO_URL (branch: $REPO_BRANCH)"
    git clone --depth 1 --branch "$REPO_BRANCH" "$REPO_URL" \
      "$WORK_ROOT/Radeon-hackathon-2026-07" || fail "克隆失败: $REPO_URL"
  fi
  ROOT="$WORK_ROOT/Radeon-hackathon-2026-07/Knowledge-Garden"
  [ -f "$ROOT/app/main.py" ] || fail "克隆后未找到 Knowledge-Garden（分支 $REPO_BRANCH 是否正确？）"
  ok "代码就绪: $ROOT"
fi
cd "$ROOT"

DIALOGUE_MODEL="${DIALOGUE_MODEL:-Qwen/Qwen2.5-14B-Instruct-AWQ}"
BATCH_MODEL="${BATCH_MODEL:-Qwen/Qwen2.5-32B-Instruct-AWQ}"
EMBED_MODEL="${EMBED_MODEL:-BAAI/bge-base-en-v1.5}"
DIALOGUE_DIR="$MODELS_DIR/Qwen2.5-14B-Instruct-AWQ"
BATCH_DIR="$MODELS_DIR/Qwen2.5-32B-Instruct-AWQ"
EMBED_DIR="$MODELS_DIR/bge-base-en-v1.5"
API_PORT="${API_PORT:-8510}"

# ---------------------------------------------------------------- 1. 环境自检
log "1/5 环境自检"
command -v rocm-smi >/dev/null && rocm-smi --showmeminfo vram >/dev/null 2>&1 \
  && ok "AMD GPU + ROCm 可见" || fail "未检测到 ROCm GPU（需 AMD Radeon + ROCm）"
command -v /opt/venv/bin/python >/dev/null 2>&1 \
  && ok "Python venv (/opt/venv)" || fail "缺少 /opt/venv（需含 ROCm torch + vLLM）"
/opt/venv/bin/python -c "import vllm" >/dev/null 2>&1 \
  && ok "vLLM 可用" || fail "vLLM 未安装（需 ROCm 构建）"

# ---------------------------------------------------------------- 2. 模型下载
if [ "$SKIP_MODELS" -eq 1 ]; then
  log "2/5 跳过模型下载（--skip-models）"
else
  log "2/5 下载模型（~31GB，已存在则跳过）"
  mkdir -p "$MODELS_DIR"
  export HF_ENDPOINT=https://hf-mirror.com
  for pair in "$DIALOGUE_MODEL:$DIALOGUE_DIR" "$BATCH_MODEL:$BATCH_DIR" "$EMBED_MODEL:$EMBED_DIR"; do
    repo="${pair%%:*}"; dir="${pair#*:}"
    # 完整性检查：config.json 存在 且 至少一个权重文件已就位（防断点续传漏下主体）
    has_cfg=""; has_wt=""
    [ -f "$dir/config.json" ] && has_cfg=1
    ls "$dir"/*.safetensors >/dev/null 2>&1 && has_wt=1
    ls "$dir"/*.bin >/dev/null 2>&1 && has_wt=1
    if [ -n "$has_cfg" ] && [ -n "$has_wt" ]; then
      ok "模型已存在: $repo"
    else
      log "下载 $repo → $dir（$([ -n "$has_cfg" ] && echo 续传 || echo 全新)）"
      /opt/venv/bin/python -m huggingface_hub.commands.huggingface_cli download \
        "$repo" --local-dir "$dir" --resume-download || fail "下载失败: $repo"
      ok "$repo"
    fi
  done
fi

# ---------------------------------------------------------------- 3. 启动 vLLM（顺序）
log "3/5 顺序启动 vLLM 双模型"
start_vllm() { # dir name port util maxlen
  if curl -sS --max-time 2 "http://127.0.0.1:$3/v1/models" >/dev/null 2>&1; then
    ok ":$3 已在运行"; return
  fi
  bash "$ROOT/scripts/start_vllm.sh" "$1" "$2" "$3" "$4" "$5" || fail "启动失败: $2"
  for i in $(seq 1 120); do
    curl -sS --max-time 2 "http://127.0.0.1:$3/v1/models" >/dev/null 2>&1 && { ok ":$3 $2 就绪"; return; }
    sleep 2
  done
  fail ":$3 $2 启动超时（看 /persistent/models/vllm_$3.log）"
}
[ -f "$DIALOGUE_DIR/config.json" ] && start_vllm "$DIALOGUE_DIR" Qwen2.5-14B-AWQ 8000 0.3 8192
[ -f "$BATCH_DIR/config.json" ]     && start_vllm "$BATCH_DIR"     Qwen2.5-32B-AWQ 8001 0.5 4096

# ---------------------------------------------------------------- 4. 后端 + Web
log "4/5 启动 FastAPI 后端 + Web UI"
if curl -sS --max-time 2 "http://127.0.0.1:$API_PORT/health" >/dev/null 2>&1; then
  ok ":$API_PORT 已在运行"
else
  cd "$ROOT"
  setsid env \
    LC_DB_PATH="${LC_DB_PATH:-$ROOT/data/learning.db}" \
    /opt/venv/bin/python -m uvicorn app.main:app \
      --host 127.0.0.1 --port "$API_PORT" \
    > /tmp/knowledge-garden-api.log 2>&1 < /dev/null &
  for i in $(seq 1 30); do
    curl -sS --max-time 2 "http://127.0.0.1:$API_PORT/health" >/dev/null 2>&1 && { ok "后端就绪"; break; }
    sleep 1
  done
fi

# ---------------------------------------------------------------- 5. 端到端验证
log "5/5 端到端健康检查"
curl -sS --max-time 5 "http://127.0.0.1:$API_PORT/health" >/dev/null 2>&1 && ok "后端 /health" || fail "后端未就绪"
curl -sS --max-time 5 "http://127.0.0.1:$API_PORT/api/garden" >/dev/null 2>&1 && ok "API /api/garden" || fail "API 异常"
[ -f "$ROOT/web/dist/index.html" ] && ok "Web UI 已构建（SPA）" || log "Web UI 未构建，可: cd web && npm install && npm run build"

echo
log "复现完成！打开: http://127.0.0.1:$API_PORT/"
log "模型: 14B@:8000 对话层 | 32B@:8001 批处理层 | 日志: /tmp/knowledge-garden-api.log"
