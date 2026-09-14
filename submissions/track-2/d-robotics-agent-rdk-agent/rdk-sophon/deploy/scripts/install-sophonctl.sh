#!/usr/bin/env bash
# 在本机（开发机/运维机，Mac 或 Linux）安装 sophonctl 客户端工具。
#
# 和 deploy-to-board.sh 的区别：
#   deploy-to-board.sh  部署板端的 daemon + 配置 + systemd 服务（目标是 aarch64 板子）
#   install-sophonctl.sh  只装客户端工具 sophonctl 到本机（目标是开发机/运维机）
#
# 本脚本在本机原生编译（本机什么架构编什么：Mac 编 apple-darwin，Linux 编 gnu/musl），
# 产物只能在本机跑，不能拿去板子（板子是 aarch64-linux，要交叉编译见 deploy/scripts/build-release.sh）。
#
# Windows 不用本脚本，直接 cargo install --path crates/api-cli（cargo 跨平台装法）。
#
# 用法：./deploy/scripts/install-sophonctl.sh [选项]
#   --release        编 release（默认 debug，快；release 更小更快但编得久）
#   --bin-dir <dir>  装到指定目录（默认 ~/.local/bin，无权限时 fallback /usr/local/bin 需 sudo）
#   --board <name> <host>[:port]  顺手登记板子别名到 ~/.rdk-sophon/config.toml
#   --default        把登记的别名设为默认（配合 --board 用）
#   -h, --help       帮助
# 示例：
#   ./deploy/scripts/install-sophonctl.sh                                          # 最简：只装客户端，不登记别名
#   ./deploy/scripts/install-sophonctl.sh --release                                # 装 release 版（更小更快）
#   ./deploy/scripts/install-sophonctl.sh --board x5 192.168.128.10:7777 --default # 装的时候顺手登记别名 x5 并设默认（可选）
set -euo pipefail

cd "$(dirname "$0")/../.." || exit 2

# 探测 cargo 环境：非交互 shell 可能没有 source ~/.cargo/env，手动加上。
if ! command -v cargo >/dev/null 2>&1; then
  if [ -f "$HOME/.cargo/env" ]; then
    # shellcheck disable=SC1091
    . "$HOME/.cargo/env"
  elif [ -d "$HOME/.cargo/bin" ]; then
    export PATH="$HOME/.cargo/bin:$PATH"
  fi
fi
if ! command -v cargo >/dev/null 2>&1; then
  echo "错误：找不到 cargo。请先装 Rust（https://rustup.rs）。" >&2
  exit 1
fi

# 颜色
if [ -t 1 ]; then G='\033[0;32m'; R='\033[0;31m'; B='\033[0;34m'; Y='\033[0;33m'; N='\033[0m'; else G=''; R=''; B=''; Y=''; N=''; fi

PROFILE="debug"
BIN_DIR=""
BOARD_NAME=""
BOARD_HOST=""
SET_DEFAULT=0

while [ $# -gt 0 ]; do
  case "$1" in
    --release) PROFILE="release"; shift ;;
    --bin-dir) BIN_DIR="${2:?--bin-dir 需要参数}"; shift 2 ;;
    --board) BOARD_NAME="${2:?--board 需要别名}"; BOARD_HOST="${3:?--board 需要 host:port}"; shift 3 ;;
    --default) SET_DEFAULT=1; shift ;;
    -h|--help)
      sed -n '2,20p' "$0" | sed 's/^# \?//'
      exit 0 ;;
    *) echo "未知参数: $1（用 -h 看帮助）" >&2; exit 2 ;;
  esac
done

echo -e "${B}========== [1/4] 本机原生编译 sophonctl (${PROFILE}) ==========${N}"
# 本机原生编译，不指定 target（本机什么架构编什么）
if [ "$PROFILE" = "release" ]; then
  cargo build --release --bin sophonctl
else
  cargo build --bin sophonctl
fi
ART="target/$PROFILE/sophonctl"
if [ ! -f "$ART" ]; then
  echo -e "${R}✗ 编译产物 $ART 缺失${N}" >&2
  exit 1
fi
echo -e "${G}✓ 编译完成: $ART${N}"
echo

echo -e "${B}========== [2/4] 装到 PATH ==========${N}"
# 默认装 ~/.local/bin（用户级，无需 sudo，跨平台标准位置）。
# 不管它当前在不在 PATH——装完若不在，提示用户加进 PATH。
# 仅当 ~/.local/bin 创建不了（如家目录只读）才 fallback /usr/local/bin（需 sudo）。
if [ -z "$BIN_DIR" ]; then
  BIN_DIR="$HOME/.local/bin"
  if ! mkdir -p "$BIN_DIR" 2>/dev/null; then
    BIN_DIR="/usr/local/bin"
  fi
fi
mkdir -p "$BIN_DIR" 2>/dev/null || true
INSTALL_CMD="cp"
if [ ! -w "$BIN_DIR" ]; then
  echo -e "${Y}$BIN_DIR 需要权限，用 sudo 装${N}"
  INSTALL_CMD="sudo cp"
fi
$INSTALL_CMD "$ART" "$BIN_DIR/sophonctl"
chmod +x "$BIN_DIR/sophonctl" 2>/dev/null || sudo chmod +x "$BIN_DIR/sophonctl"
echo -e "${G}✓ 已装到 $BIN_DIR/sophonctl${N}"

# 若 ~/.local/bin 不在 PATH，提示用户加进 ~/.zshrc / ~/.bashrc。
if [ "$BIN_DIR" = "$HOME/.local/bin" ] && ! case ":$PATH:" in *":$HOME/.local/bin:"*) true ;; *) false ;; esac; then
  echo -e "${Y}提示：$BIN_DIR 不在 PATH。请加进 shell 配置：${N}"
  echo "  echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.zshrc   # macOS 默认 zsh"
  echo "  echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc  # Linux bash"
  echo "  然后 source 一下或新开终端，即可直接敲 sophonctl"
else
  echo -e "${Y}提示：当前 shell 可能需 hash -r 或新开终端才能直接敲 sophonctl${N}"
fi
echo

echo -e "${B}========== [3/4] 验证 ==========${N}"
if command -v sophonctl >/dev/null 2>&1; then
  echo -e "${G}✓ sophonctl 已在 PATH: $(command -v sophonctl)${N}"
  sophonctl --help 2>&1 | head -1
else
  echo -e "${Y}sophonctl 还不在当前 shell 的 PATH 缓存，新开终端或 hash -r 后可用${N}"
  echo "或直接用: $BIN_DIR/sophonctl --help"
fi
echo

echo -e "${B}========== [4/4] 登记板子别名（可选） ==========${N}"
if [ -n "$BOARD_NAME" ] && [ -n "$BOARD_HOST" ]; then
  DEFAULT_FLAG=""
  if [ "$SET_DEFAULT" -eq 1 ]; then DEFAULT_FLAG="--default"; fi
  "$BIN_DIR/sophonctl" config add "$BOARD_NAME" "$BOARD_HOST" $DEFAULT_FLAG
  echo -e "${G}✓ 别名 $BOARD_NAME → $BOARD_HOST 已登记${N}"
  echo "现在可直接: sophonctl --board $BOARD_NAME state"
  if [ "$SET_DEFAULT" -eq 1 ]; then
    echo "或（默认）: sophonctl state"
  fi
else
  echo -e "${Y}未指定 --board，跳过别名登记${N}"
  echo "之后可手动登记: sophonctl config add <别名> <ip:port> --default"
fi
echo
echo -e "${G}安装完成。${N}"
echo "用法: sophonctl --board <别名> state   或   sophonctl --host <ip:port> state"
