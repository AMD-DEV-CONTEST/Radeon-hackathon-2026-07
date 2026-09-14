#!/usr/bin/env bash
# 一键部署到 RDK 板端：编译 → 推送 → 安装 → 起服务。
# 在开发机运行，通过 ssh/scp 操作板子。
#
# 编译策略（自动选，无需手动）：
#   1. 若已有交叉编译产物 target/aarch64-unknown-linux-gnu/release/* → 直接用
#   2. 若 Mac 装了 cargo-zigbuild + zig → 跑 build-release.sh 交叉编译（最快，不在板上编）
#   3. 否则 fallback：把源码 rsync 到板子，在板上 cargo build（板上 Rust 已装即可，约 3 分钟）
#
# 用法：./deploy/scripts/deploy-to-board.sh <board-host> [board-user] [--enable-plugins]
#   board-host   板子 ssh 主机名或 IP（如 x5-root 或 192.168.128.10）
#   board-user   可选，板子用户名（默认用 ssh config，如 x5-root 已含）
#   --enable-plugins  部署前把目标配置的 [plugins].enabled 改为 true
# 示例：./deploy/scripts/deploy-to-board.sh x5-root --enable-plugins
set -euo pipefail

SCRIPT_PATH="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)/$(basename -- "$0")"
cd "$(dirname "$SCRIPT_PATH")/../.." || exit 2

# 探测 cargo 环境：非交互 shell 可能没 source ~/.cargo/env。
if ! command -v cargo >/dev/null 2>&1; then
  if [ -f "$HOME/.cargo/env" ]; then
    # shellcheck disable=SC1091
    . "$HOME/.cargo/env"
  elif [ -d "$HOME/.cargo/bin" ]; then
    export PATH="$HOME/.cargo/bin:$PATH"
  fi
fi

TARGET="aarch64-unknown-linux-gnu"
BINS=("probe-daemon" "sophonctl" "probe-http-gateway" "probe-ws-outbound")
CROSS_DIR="target/$TARGET/release"
BOARD_HOST=""
BOARD_USER=""
ENABLE_PLUGINS=0

while [ $# -gt 0 ]; do
  case "$1" in
    --enable-plugins)
      ENABLE_PLUGINS=1
      shift
      ;;
    -h|--help)
      sed -n '2,14p' "$SCRIPT_PATH" | sed -E 's/^# ?//'
      exit 0
      ;;
    --*)
      echo "未知参数: $1" >&2
      exit 2
      ;;
    *)
      if [ -z "$BOARD_HOST" ]; then
        BOARD_HOST="$1"
      elif [ -z "$BOARD_USER" ]; then
        BOARD_USER="$1"
      else
        echo "位置参数过多: $1" >&2
        exit 2
      fi
      shift
      ;;
  esac
done

if [ -z "$BOARD_HOST" ]; then
  echo "用法: $0 <board-host> [board-user] [--enable-plugins]" >&2
  exit 2
fi

SSH_TARGET="$BOARD_HOST"
if [ -n "$BOARD_USER" ]; then SSH_TARGET="${BOARD_USER}@${BOARD_HOST}"; fi

CONFIG_SOURCE="config/config.toml"
TEMP_CONFIG=""
cleanup() {
  if [ -n "$TEMP_CONFIG" ]; then rm -f "$TEMP_CONFIG"; fi
}
trap cleanup EXIT

if [ "$ENABLE_PLUGINS" -eq 1 ]; then
  TEMP_CONFIG="$(mktemp "${TMPDIR:-/tmp}/rdk-sophon-config.XXXXXX")"
  awk '
    $0 == "[plugins]" { in_plugins = 1; print; next }
    in_plugins && /^\[/ { exit 42 }
    in_plugins && /^enabled[[:space:]]*=/ {
      print "enabled = true"
      in_plugins = 0
      updated = 1
      next
    }
    { print }
    END { if (!updated) exit 42 }
  ' "$CONFIG_SOURCE" > "$TEMP_CONFIG" || {
    echo "无法在 config/config.toml 中启用 [plugins]" >&2
    exit 1
  }
  CONFIG_SOURCE="$TEMP_CONFIG"
fi

# 颜色
if [ -t 1 ]; then G='\033[0;32m'; R='\033[0;31m'; B='\033[0;34m'; Y='\033[0;33m'; N='\033[0m'; else G=''; R=''; B=''; Y=''; N=''; fi

echo -e "${B}========== [1/6] 选择编译策略 ==========${N}"

# 判断产物来源：交叉编译(CROSS_DIR) 还是 板上编译(板上 target/release)
HAVE_CROSS=1
for bin in "${BINS[@]}"; do
  [ -f "$CROSS_DIR/$bin" ] || HAVE_CROSS=0
done

if [ "$HAVE_CROSS" -eq 1 ]; then
  echo -e "${G}✓ 已有交叉编译产物 $CROSS_DIR，直接用${N}"
  RELEASE_DIR="$CROSS_DIR"
  BUILD_MODE="cross"
elif command -v cargo-zigbuild >/dev/null 2>&1 && command -v zig >/dev/null 2>&1; then
  echo -e "${B}检测到 cargo-zigbuild + zig，交叉编译（不在板上编，最快）${N}"
  ./deploy/scripts/build-release.sh
  RELEASE_DIR="$CROSS_DIR"
  BUILD_MODE="cross"
else
  echo -e "${Y}无交叉编译工具链（需 cargo-zigbuild + zig），fallback 到板上编译${N}"
  echo -e "${Y}板上编译约 3 分钟（板上需已装 Rust，见 deploy/docs/build.md）${N}"
  RELEASE_DIR="target/release"   # 板上的产物路径
  BUILD_MODE="onboard"
fi
echo

# ───────── 板上编译分支 ─────────
if [ "$BUILD_MODE" = "onboard" ]; then
  echo -e "${B}========== [2/6] rsync 源码到板子 ==========${N}"
  rsync -az --delete --exclude='target' --exclude='.git' --exclude='*.output' \
    ./ "$SSH_TARGET:/root/rdk-sophon/"
  echo -e "${G}✓ 源码已同步${N}"
  echo

  echo -e "${B}========== [3/6] 板上编译 4 个 bin（release） ==========${N}"
  ssh -o ConnectTimeout=15 "$SSH_TARGET" "
    source \$HOME/.cargo/env 2>/dev/null
    cd /root/rdk-sophon
    cargo build --release --bin ${BINS[0]} --bin ${BINS[1]} --bin ${BINS[2]} --bin ${BINS[3]} 2>&1 | tail -5
    echo '--- 产物 ---'
    ls -la target/release/{${BINS[0]},${BINS[1]},${BINS[2]},${BINS[3]}} 2>/dev/null | awk '{print \$5, \$NF}'
  " || { echo -e "${R}板上编译失败，检查板上 Rust 是否装好（见 deploy/docs/build.md）${N}" >&2; exit 1; }
  echo

  echo -e "${B}========== [4/6] 准备临时部署目录 ==========${N}"
  REMOTE_TMP="/tmp/rdk-sophon-deploy"
  ssh -o ConnectTimeout=10 "$SSH_TARGET" "
    mkdir -p $REMOTE_TMP
    cd /root/rdk-sophon
    cp target/release/{${BINS[0]},${BINS[1]},${BINS[2]},${BINS[3]}} $REMOTE_TMP/
    cp config/config.toml $REMOTE_TMP/config.toml
    cp systemd/probe-daemon.service $REMOTE_TMP/probe-daemon.service
    cp deploy/scripts/install-on-board.sh $REMOTE_TMP/install-on-board.sh
    echo 临时目录就绪
  "
else
  echo -e "${B}========== [2/6] 推送二进制到板子 /tmp/rdk-sophon-deploy/ ==========${N}"
  REMOTE_TMP="/tmp/rdk-sophon-deploy"
  ssh -o ConnectTimeout=10 "$SSH_TARGET" "mkdir -p $REMOTE_TMP"
  for bin in "${BINS[@]}"; do
    echo -e "${B}  scp $bin${N}"
    scp -q "$RELEASE_DIR/$bin" "$SSH_TARGET:$REMOTE_TMP/$bin"
  done
  echo

  echo -e "${B}========== [3/6] 推送配置与 systemd unit ==========${N}"
  scp -q "$CONFIG_SOURCE" "$SSH_TARGET:$REMOTE_TMP/config.toml"
  scp -q systemd/probe-daemon.service "$SSH_TARGET:$REMOTE_TMP/probe-daemon.service"
  scp -q deploy/scripts/install-on-board.sh "$SSH_TARGET:$REMOTE_TMP/install-on-board.sh"
  echo -e "${G}✓ 二进制/配置/unit/安装脚本已推送${N}"
  echo
fi

# 板上编译分支会先从同步源码复制默认配置；启用插件时用临时配置覆盖它。
if [ "$BUILD_MODE" = "onboard" ] && [ "$ENABLE_PLUGINS" -eq 1 ]; then
  scp -q "$CONFIG_SOURCE" "$SSH_TARGET:$REMOTE_TMP/config.toml"
fi

# ───────── 通用安装 + 起服务 ─────────
echo -e "${B}========== [5/6] 远程执行安装脚本 ==========${N}"
ssh -o ConnectTimeout=10 "$SSH_TARGET" "sudo bash $REMOTE_TMP/install-on-board.sh"
echo

echo -e "${B}========== [6/6] 重启服务并验证 ==========${N}"
ssh -o ConnectTimeout=10 "$SSH_TARGET" "
  sudo systemctl daemon-reload
  sudo systemctl enable --now probe-daemon
  sleep 2
  echo '--- 服务状态 ---'
  sudo systemctl --no-pager --full status probe-daemon | head -n 12 || true
  echo '--- 监听端口 ---'
  ss -lnt 2>/dev/null | grep 7777 || netstat -lnt 2>/dev/null | grep 7777
"
echo
echo -e "${G}部署完成。板端 probe-daemon 已在 7777 监听。${N}"
echo "本地验证：sophonctl --host <board-ip>:7777 state"
echo "（若用了 ssh alias 如 x5-root，请用板子 IP 替换；或先 sophonctl config add <别名> <ip>:7777 --default）"
