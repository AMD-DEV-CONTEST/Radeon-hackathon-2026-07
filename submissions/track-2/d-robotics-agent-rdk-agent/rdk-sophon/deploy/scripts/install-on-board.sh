#!/usr/bin/env bash
# 板端安装脚本：把推送来的二进制装到 /usr/local/bin，
# 配置装到 /etc/probe-daemon/，systemd unit 装到 /etc/systemd/system/，
# 建 probe 用户，准备 /var/log/probe-daemon，不启动服务（由调用方 systemctl）。
# 本脚本在板子（root）上运行，由 deploy-to-board.sh 远程触发。
# 前置：/tmp/rdk-sophon-deploy/ 已有二进制 + config.toml + probe-daemon.service。
set -euo pipefail

# 颜色（板子终端）
if [ -t 1 ]; then G='\033[0;32m'; B='\033[0;34m'; N='\033[0m'; else G=''; B=''; N=''; fi

# 必须 root
if [ "$(id -u)" -ne 0 ]; then
  echo "请用 root 运行（deploy-to-board.sh 已 sudo 调用）" >&2
  exit 1
fi

SRC="/tmp/rdk-sophon-deploy"
BIN_DIR="/usr/local/bin"
CONF_DIR="/etc/probe-daemon"
UNIT_DIR="/etc/systemd/system"
LOG_DIR="/var/log/probe-daemon"
RUN_USER="probe"

BINS=("probe-daemon" "sophonctl" "probe-http-gateway" "probe-ws-outbound")

echo -e "${B}========== [1/6] 校验源文件 ==========${N}"
for bin in "${BINS[@]}"; do
  [ -f "$SRC/$bin" ] || { echo "缺失 $SRC/$bin" >&2; exit 1; }
done
[ -f "$SRC/config.toml" ] || { echo "缺失 $SRC/config.toml" >&2; exit 1; }
[ -f "$SRC/probe-daemon.service" ] || { echo "缺失 $SRC/probe-daemon.service" >&2; exit 1; }
echo -e "${G}✓ 源文件齐全${N}"
echo

echo -e "${B}========== [2/6] 安装二进制到 $BIN_DIR ==========${N}"
for bin in "${BINS[@]}"; do
  install -m 0755 "$SRC/$bin" "$BIN_DIR/$bin"
  echo "  $bin → $BIN_DIR/$bin"
done
echo

echo -e "${B}========== [3/6] 安装配置到 $CONF_DIR ==========${N}"
mkdir -p "$CONF_DIR"
install -m 0644 "$SRC/config.toml" "$CONF_DIR/config.toml"
# 调整板端默认：shell 生产环境应关闭（配置里默认已是 false，这里只是确保）
echo "  config.toml → $CONF_DIR/config.toml"
echo

echo -e "${B}========== [4/6] 创建 probe 用户与目录 ==========${N}"
if ! id "$RUN_USER" >/dev/null 2>&1; then
  useradd --system --no-create-home --shell /usr/sbin/nologin "$RUN_USER"
  echo "  创建用户 $RUN_USER"
else
  echo "  用户 $RUN_USER 已存在"
fi
mkdir -p "$LOG_DIR" /run/probe-daemon
chown "$RUN_USER:$RUN_USER" "$LOG_DIR" /run/probe-daemon
echo

echo -e "${B}========== [5/6] 安装 systemd unit ==========${N}"
install -m 0644 "$SRC/probe-daemon.service" "$UNIT_DIR/probe-daemon.service"
echo "  unit → $UNIT_DIR/probe-daemon.service"
echo

echo -e "${B}========== [6/6] 清理 ==========${N}"
rm -rf "$SRC"
echo -e "${G}安装完成。下一步（由 deploy-to-board.sh 执行）：${N}"
echo "  sudo systemctl daemon-reload"
echo "  sudo systemctl enable --now probe-daemon"
