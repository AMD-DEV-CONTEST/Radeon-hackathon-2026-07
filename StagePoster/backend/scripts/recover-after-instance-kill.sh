#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="/workspace/poster-engine"
BACKEND="$ROOT/backend"
PERSIST="${PERSIST_ROOT:-/workspace/persistence/stageposter}/prekill"

# venv 路径必须从 .env 读，不能写死。
#
# 这里原先两处都写死 "$ROOT/venv"，而 .env 里 COMFY_VENV=/workspace/venv ——
# 在项目目录之外。后果是第 118 行的验证在一台**完全健康**的机器上就 exit 1，
# 也就是说这个恢复脚本从来没有可能跑通。scripts/ 下其它脚本
# （start-all.sh、install-comfyui.sh、export-runtime-locks.sh）一直都认
# COMFY_VENV，只有这两个 kill/recover 脚本没跟上。
if [[ -f "$ROOT/.env" ]]; then
  COMFY_VENV="${COMFY_VENV:-$(
    grep -E '^COMFY_VENV=' "$ROOT/.env" | tail -1 | cut -d= -f2- || true
  )}"
  VLLM_VENV="${VLLM_VENV:-$(
    grep -E '^VLLM_VENV=' "$ROOT/.env" | tail -1 | cut -d= -f2- || true
  )}"
fi

COMFY_VENV="${COMFY_VENV:-$ROOT/venv}"
VLLM_VENV="${VLLM_VENV:-$ROOT/.venv-vllm}"

CHECK_ONLY=0

for argument in "$@"; do
  case "$argument" in
    --check | --dry-run)
      CHECK_ONLY=1
      ;;
    -h | --help)
      cat <<'USAGE'
用法：recover-after-instance-kill.sh [--check]

  --check   只做预检，不改动任何东西。用来演练恢复流程：
            确认实例现在被销毁的话，手上的备份是否真的够用。
            需要 root，因为要读 0600 的 private/backend.env。

不带参数则执行真实恢复（会 rm -rf /usr/local/go、覆盖 venv 软链、rsync 权重）。
USAGE
      exit 0
      ;;
    *)
      echo "Unknown argument: $argument" >&2
      exit 2
      ;;
  esac
done

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run this script as root." >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# 预检
#
# 未经演练的恢复流程是备份失效最经典的原因，而它只会在你最需要它的时候暴露。
# 但真实恢复会 rm -rf 工具链和 venv，在一台正在服务的机器上跑等于自伤。
# 所以把"断言"从"改动"里拆出来：--check 只跑断言，一个字节都不写。
# 断言和真实恢复读的是同一批变量，不会各自漂移。
# ---------------------------------------------------------------------------

CHECK_PASS=0
CHECK_FAIL=0
CHECK_WARN=0

check() {
  local level="$1"
  local label="$2"
  local detail="${3:-}"

  case "$level" in
    ok)
      CHECK_PASS=$((CHECK_PASS + 1))
      printf '  [ OK ]   %-42s %s\n' "$label" "$detail"
      ;;
    warn)
      CHECK_WARN=$((CHECK_WARN + 1))
      printf '  [WARN]   %-42s %s\n' "$label" "$detail"
      ;;
    fail)
      CHECK_FAIL=$((CHECK_FAIL + 1))
      printf '  [FAIL]   %-42s %s\n' "$label" "$detail"
      ;;
  esac
}

check_file() {
  local label="$1"
  local path="$2"
  local level="${3:-fail}"

  if [[ -f "$path" ]]; then
    check ok "$label" "$(du -h "$path" | cut -f1)  $path"
  else
    check "$level" "$label" "missing: $path"
  fi
}

run_preflight() {
  echo
  echo "===== PREFLIGHT (no changes will be made) ====="
  echo

  echo "-- 备份产物 --"

  if [[ -d "$PERSIST" ]]; then
    check ok "prekill 目录存在" "$PERSIST"
  else
    check fail "prekill 目录存在" "missing: $PERSIST"
  fi

  local snapshot=""

  if [[ -d "$PERSIST/snapshots" ]]; then
    snapshot="$(
      find "$PERSIST/snapshots" -maxdepth 1 -mindepth 1 -type d \
        | sort | tail -1
    )"
  fi

  if [[ -n "$snapshot" ]]; then
    check ok "最新快照" "$(basename "$snapshot")"
  else
    check fail "最新快照" "没有任何快照，恢复无从下手"
  fi

  if [[ -n "$snapshot" ]]; then
    if [[ -f "$snapshot/poster.db" ]]; then
      local integrity
      integrity="$(
        sqlite3 "$snapshot/poster.db" 'PRAGMA integrity_check;' 2>&1 \
          || echo "sqlite3 unavailable"
      )"

      if [[ "$integrity" == "ok" ]]; then
        local rows
        rows="$(
          sqlite3 "$snapshot/poster.db" \
            'SELECT COUNT(*) FROM poster_requests;' 2>/dev/null || echo '?'
        )"
        check ok "快照数据库可用" "integrity=ok  poster_requests=$rows"
      else
        check fail "快照数据库可用" "integrity=$integrity"
      fi
    else
      check fail "快照数据库存在" "missing: $snapshot/poster.db"
    fi

    check_file "权重尺寸清单" "$snapshot/model-sizes.txt"
    check_file "工作流模板" "$snapshot/workflows/z_image_poster_v1.json" warn
  fi

  check_file "backend.env（唯一副本，.gitignore 掉了）" \
    "$PERSIST/private/backend.env"

  echo
  echo "-- 工具链 --"

  if [[ -d "$ROOT/toolchains/go1.25.0" ]]; then
    check ok "Go 工具链已持久化" "$(du -sh "$ROOT/toolchains/go1.25.0" | cut -f1)"
  else
    check warn "Go 工具链已持久化" "缺失，恢复时会回落到 install-go.sh 联网下载"
  fi

  if [[ -x "$ROOT/tools/bin/cloudflared" ]]; then
    check ok "cloudflared 已持久化" "$ROOT/tools/bin/cloudflared"
  else
    check warn "cloudflared 已持久化" "缺失，会回落到 install-cloudflared.sh"
  fi

  if [[ -x "$ROOT/tools/bin/uv" ]]; then
    check ok "uv 已持久化" "$ROOT/tools/bin/uv"
  else
    check warn "uv 已持久化" "缺失"
  fi

  echo
  echo "-- Python 环境 --"

  local name venv freeze
  for name in comfyui vllm; do
    if [[ "$name" == "comfyui" ]]; then
      venv="$COMFY_VENV"
    else
      venv="$VLLM_VENV"
    fi

    if [[ -x "$venv/bin/python" ]]; then
      check ok "$name venv 可执行" \
        "$("$venv/bin/python" --version 2>&1)  $venv"
    else
      check fail "$name venv 可执行" "missing: $venv/bin/python"
    fi

    freeze="$PERSIST/private/${name}-requirements.txt"

    if [[ -f "$freeze" ]]; then
      check ok "$name 包清单已存档" \
        "$(wc -l < "$freeze") 个包  $(basename "$freeze")"
    else
      check fail "$name 包清单已存档" \
        "缺失。site-packages 太大无法备份，清单是唯一的重建依据"
    fi
  done

  echo
  echo "-- 模型权重 --"

  local weights_found=0
  local weights_missing=0
  local filename expected actual found

  if [[ -n "$snapshot" && -f "$snapshot/model-sizes.txt" ]]; then
    while read -r expected filename; do
      [[ -n "$filename" ]] || continue

      found="$(
        find -L "$ROOT/ComfyUI/models" "$PERSIST/models/comfyui" \
          -type f -name "$filename" -print 2>/dev/null | head -1
      )"

      if [[ -z "$found" ]]; then
        check fail "权重 $filename" "找不到"
        weights_missing=$((weights_missing + 1))
        continue
      fi

      actual="$(stat -c%s "$found")"

      if [[ "$actual" == "$expected" ]]; then
        check ok "权重 $filename" "$((actual / 1024 / 1024)) MB 字节数吻合"
        weights_found=$((weights_found + 1))
      else
        # hf-mirror 的 Xet 大文件会静默截断，退出码还可能是 0。
        # 只能按字节数核对，这就是为什么清单必须存在。
        check fail "权重 $filename" \
          "字节数不符：期望 $expected 实际 $actual（疑似 Xet 截断）"
        weights_missing=$((weights_missing + 1))
      fi
    done < "$snapshot/model-sizes.txt"
  else
    check fail "权重清单可比对" "没有 model-sizes.txt，无法判断权重是否完整"
  fi

  if [[ -d "$ROOT/models/Qwen3.5-9B" ]]; then
    check ok "Qwen 模型目录" "$(du -sh "$ROOT/models/Qwen3.5-9B" | cut -f1)"
  else
    check fail "Qwen 模型目录" "missing: $ROOT/models/Qwen3.5-9B"
  fi

  echo
  echo "-- 宿主机 --"

  if command -v rocm-smi >/dev/null 2>&1; then
    check ok "rocm-smi 可用" "$(rocm-smi --showproductname 2>/dev/null \
      | grep -m1 -i 'card series' | sed 's/^[[:space:]]*//' || echo present)"
  else
    check fail "rocm-smi 可用" "ROCm 不在 PATH 里"
  fi

  if command -v sqlite3 >/dev/null 2>&1; then
    check ok "sqlite3 可用" "$(sqlite3 --version | cut -d' ' -f1)"
  else
    check fail "sqlite3 可用" "恢复脚本靠它校验数据库"
  fi

  echo
  echo "-- 源码 --"

  if [[ -d "$BACKEND/.git" ]] || git -C "$BACKEND" rev-parse --git-dir >/dev/null 2>&1; then
    local unpushed
    unpushed="$(git -C "$BACKEND" log --oneline @{u}.. 2>/dev/null | wc -l || echo '?')"

    if [[ "$unpushed" == "0" ]]; then
      check ok "代码已推送" "HEAD=$(git -C "$BACKEND" rev-parse --short HEAD)"
    else
      check fail "代码已推送" "$unpushed 个提交只在本地，实例销毁即丢失"
    fi

    if [[ -z "$(git -C "$BACKEND" status --porcelain)" ]]; then
      check ok "工作区干净" ""
    else
      check warn "工作区干净" \
        "$(git -C "$BACKEND" status --porcelain | wc -l) 个文件未提交"
    fi
  else
    check fail "git 仓库存在" "$BACKEND 不是 git 仓库"
  fi

  echo
  echo "=================================================="
  printf ' PREFLIGHT: %d ok, %d warn, %d fail\n' \
    "$CHECK_PASS" "$CHECK_WARN" "$CHECK_FAIL"
  echo "=================================================="

  if [[ "$CHECK_FAIL" -gt 0 ]]; then
    echo
    echo "有 $CHECK_FAIL 项不满足。现在实例被销毁的话，恢复会卡在这些地方。"
    echo "先跑 prepare-before-instance-kill.sh 补齐，再重跑本预检。"
    return 1
  fi

  echo
  echo "预检通过。恢复所需的产物齐备。"
  return 0
}

# vLLM venv 的位置：.env 给的是绝对路径，老脚本用的是 $ROOT/.venv-vllm。
if [[ "$CHECK_ONLY" == "1" ]]; then
  run_preflight
  exit $?
fi

echo "=================================================="
echo " StagePoster instance recovery"
echo "=================================================="

echo
echo "===== INSTALL BASIC SYSTEM TOOLS ====="

apt-get update

apt-get install -y \
  build-essential \
  ca-certificates \
  curl \
  git \
  iproute2 \
  jq \
  lsof \
  procps \
  rsync \
  sqlite3 \
  unzip

echo
echo "===== RESTORE GO ====="

if [[ -d "$ROOT/toolchains/go1.25.0" ]]; then
  rm -rf /usr/local/go

  ln -s \
    "$ROOT/toolchains/go1.25.0" \
    /usr/local/go

  ln -sf \
    /usr/local/go/bin/go \
    /usr/local/bin/go

  ln -sf \
    /usr/local/go/bin/gofmt \
    /usr/local/bin/gofmt
else
  echo "Persistent Go toolchain not found."
  "$BACKEND/scripts/install-go.sh"
fi

go version

echo
echo "===== RESTORE CLOUDFLARED ====="

if [[ -x "$ROOT/tools/bin/cloudflared" ]]; then
  install -m 755 \
    "$ROOT/tools/bin/cloudflared" \
    /usr/local/bin/cloudflared
else
  "$BACKEND/scripts/install-cloudflared.sh"
fi

cloudflared --version

echo
echo "===== RESTORE UV ====="

if [[ -x "$ROOT/tools/bin/uv" ]]; then
  install -m 755 \
    "$ROOT/tools/bin/uv" \
    /usr/local/bin/uv
fi

restore_python_runtime() {
  local name="$1"
  local metadata="$PERSIST/${name}-python-runtime.env"

  [[ -f "$metadata" ]] || return 0

  unset ORIGINAL_ROOT
  unset PERSISTENT_ROOT

  source "$metadata"

  if [[ -z "${ORIGINAL_ROOT:-}" ]] ||
    [[ -z "${PERSISTENT_ROOT:-}" ]]; then
    return
  fi

  echo "Restoring $name Python runtime:"
  echo "  $ORIGINAL_ROOT -> $PERSISTENT_ROOT"

  mkdir -p "$(dirname "$ORIGINAL_ROOT")"

  rm -rf "$ORIGINAL_ROOT"

  ln -s \
    "$PERSISTENT_ROOT" \
    "$ORIGINAL_ROOT"
}

echo
echo "===== RESTORE PYTHON RUNTIMES ====="

restore_python_runtime "comfyui"
restore_python_runtime "vllm"

echo
echo "===== VERIFY PYTHON ENVIRONMENTS ====="

if ! "$COMFY_VENV/bin/python" --version; then
  echo "ComfyUI Python environment is broken: $COMFY_VENV" >&2
  echo "Run scripts/install-comfyui.sh to recreate it." >&2
  echo "Package list: $PERSIST/private/comfyui-requirements.txt" >&2
  exit 1
fi

if ! "$VLLM_VENV/bin/python" --version; then
  echo "vLLM Python environment is broken: $VLLM_VENV" >&2
  echo "Run scripts/install-vllm.sh to recreate it." >&2
  echo "Package list: $PERSIST/private/vllm-requirements.txt" >&2
  exit 1
fi

echo
echo "===== RESTORE COMFYUI MODELS ====="

COMFY_MODELS="$ROOT/ComfyUI/models"
MODEL_BACKUP="$PERSIST/models/comfyui"

if [[ -L "$COMFY_MODELS" ]]; then
  echo "Removing external ComfyUI models symlink:"
  ls -ld "$COMFY_MODELS"
  rm -f "$COMFY_MODELS"
fi

mkdir -p \
  "$COMFY_MODELS/diffusion_models" \
  "$COMFY_MODELS/text_encoders" \
  "$COMFY_MODELS/vae" \
  "$COMFY_MODELS/loras"

rsync -ah \
  "$MODEL_BACKUP/diffusion_models/" \
  "$COMFY_MODELS/diffusion_models/"

rsync -ah \
  "$MODEL_BACKUP/text_encoders/" \
  "$COMFY_MODELS/text_encoders/"

rsync -ah \
  "$MODEL_BACKUP/vae/" \
  "$COMFY_MODELS/vae/"

rsync -ah \
  "$MODEL_BACKUP/loras/" \
  "$COMFY_MODELS/loras/"

echo
echo "===== RESTORE ENV FILE ====="

# 还原到 prepare 记录的原始位置。写死 "$BACKEND/.env" 是错的：
# start-all.sh 优先取 backend/.env，所以在真实配置位于 $ROOT/.env 的机器上，
# 往 backend/.env 写一份 .env.example 会悄悄盖掉真实配置。
ENV_TARGET=""

if [[ -f "$PERSIST/private/backend.env.origin" ]]; then
  ENV_TARGET="$(tr -d '[:space:]' < "$PERSIST/private/backend.env.origin")"
fi

if [[ -z "$ENV_TARGET" ]]; then
  if [[ -f "$BACKEND/.env" ]]; then
    ENV_TARGET="$BACKEND/.env"
  else
    ENV_TARGET="$ROOT/.env"
  fi
fi

echo "ENV_TARGET=$ENV_TARGET"

if [[ ! -f "$ENV_TARGET" ]] &&
  [[ -f "$PERSIST/private/backend.env" ]]; then
  install -m 600 \
    "$PERSIST/private/backend.env" \
    "$ENV_TARGET"

  echo "Restored .env from backup."
fi

if [[ ! -f "$ENV_TARGET" ]]; then
  # 兜底用项目根的 .env.example（6542 字节，字段齐全），
  # 不用 backend/.env.example —— 那份是陈旧子集。
  cp \
    "$ROOT/.env.example" \
    "$ENV_TARGET"

  echo "Created a new .env file from .env.example."
  echo "Review it before starting services: $ENV_TARGET"
fi

# A Quick Tunnel URL never survives an instance kill.
sed -i \
  's|^PUBLIC_API_URL=.*|PUBLIC_API_URL=|' \
  "$ENV_TARGET"

echo
echo "===== REMOVE STALE PID FILES ====="

rm -f \
  "$BACKEND/run/"*.pid \
  "$BACKEND/backend.pid" \
  2>/dev/null || true

mkdir -p \
  "$BACKEND/logs" \
  "$BACKEND/run" \
  "$BACKEND/data" \
  "$BACKEND/storage/jobs" \
  "$BACKEND/storage/assets" \
  "$BACKEND/storage/posters"

echo
echo "===== VERIFY ROCM ====="

rocm-smi --showproductname
rocminfo | grep -m1 -E 'Name:.*gfx'
hipcc --version || true

echo
echo "===== VERIFY MODELS ====="

find "$COMFY_MODELS" \
  -type f \
  -name '*.safetensors' \
  -printf '%s\t%p\n' \
  | sort -n

find "$ROOT/models/Qwen3.5-9B" \
  -maxdepth 1 \
  -type f \
  -printf '%s\t%p\n' \
  | sort -n

echo
echo "===== TEST BACKEND SOURCE ====="

cd "$BACKEND"

go test ./...
go build ./...

echo
echo "=================================================="
echo " RECOVERY COMPLETE"
echo "=================================================="
echo
echo "Start services:"
echo "  cd $BACKEND"
echo "  ./scripts/start-all.sh"
echo
echo "Then:"
echo "  ./scripts/status.sh"
echo "  ./scripts/smoke-test.sh"
echo "  ./scripts/start-dev-tunnel.sh"
