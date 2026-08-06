#!/usr/bin/env bash
# 一键部署 rdk-agent 所需的板端与开发机环境。
#
# 默认约定：
#   SSH 别名：x5-root
#   sophonctl 板子别名：x5
#   probe-daemon 地址：从 `ssh -G x5-root` 推导主机，再使用 7777 端口
#
# 用法：./rdk-agent/deploy/install-rdk-agent-stack.sh [选项]
#   --ssh-host <alias>       板端 SSH 别名（默认 x5-root）
#   --board-address <host:port>  sophonctl 连接地址（默认从 SSH 配置推导）
#   --board-only           只部署板端交付物
#   --development-only     只部署开发机交付物
#   --preflight-only        检查基础命令、参数和板端 SSH（如适用），不执行部署
#   --skip-podman           不初始化或拉取开发沙箱镜像
#   --skip-servo-bootstrap  不预装 MagicBox servo 模板插件
#   -h, --help              显示帮助
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPOSITORY_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)"
SOPHON_DIR="$REPOSITORY_ROOT/rdk-sophon"
AGENT_DIR="$REPOSITORY_ROOT/rdk-agent"
SERVO_TEMPLATE="$AGENT_DIR/config/templates/magicbox-servo/examples/plugins/servo"

SSH_HOST="x5-root"
BOARD_ADDRESS=""
TARGET_MODE="all"
PREFLIGHT_ONLY=0
SKIP_PODMAN=0
SKIP_SERVO_BOOTSTRAP=0

while [ $# -gt 0 ]; do
  case "$1" in
    --ssh-host)
      SSH_HOST="${2:?--ssh-host 需要参数}"
      shift 2
      ;;
    --board-address)
      BOARD_ADDRESS="${2:?--board-address 需要 host:port}"
      shift 2
      ;;
    --board-only)
      if [ "$TARGET_MODE" = "development" ]; then
        echo "错误：--board-only 不能与 --development-only 同时使用" >&2
        exit 2
      fi
      TARGET_MODE="board"
      shift
      ;;
    --development-only)
      if [ "$TARGET_MODE" = "board" ]; then
        echo "错误：--board-only 不能与 --development-only 同时使用" >&2
        exit 2
      fi
      TARGET_MODE="development"
      shift
      ;;
    --preflight-only)
      PREFLIGHT_ONLY=1
      shift
      ;;
    --skip-podman)
      SKIP_PODMAN=1
      shift
      ;;
    --skip-servo-bootstrap)
      SKIP_SERVO_BOOTSTRAP=1
      shift
      ;;
    -h|--help)
      sed -n '2,17p' "$0" | sed -E 's/^# ?//'
      exit 0
      ;;
    *)
      echo "未知参数: $1（用 -h 查看帮助）" >&2
      exit 2
      ;;
  esac
done

if ! printf '%s' "$SSH_HOST" | grep -Eq '^[A-Za-z0-9._-]+$'; then
  echo "错误：--ssh-host 只能包含字母、数字、点、下划线和连字符" >&2
  exit 2
fi

REQUIRED_COMMANDS=()
if [ "$TARGET_MODE" != "development" ]; then
  REQUIRED_COMMANDS+=(ssh scp)
fi
if [ "$TARGET_MODE" != "board" ]; then
  REQUIRED_COMMANDS+=(node npm cargo)
  if [ "$SKIP_PODMAN" -eq 0 ]; then
    REQUIRED_COMMANDS+=(podman)
  fi
fi
for command_name in "${REQUIRED_COMMANDS[@]}"; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "错误：找不到 $command_name" >&2
    exit 1
  fi
done

if [ "$TARGET_MODE" != "board" ] && ! node -e 'const [major, minor] = process.versions.node.split(".").map(Number); process.exit(major > 22 || (major === 22 && minor >= 19) ? 0 : 1)'; then
  echo "错误：rdk-agent 要求 Node.js >= 22.19.0，当前为 $(node --version)" >&2
  exit 1
fi

if [ -z "$BOARD_ADDRESS" ]; then
  if ! command -v ssh >/dev/null 2>&1; then
    echo "错误：无法从 SSH 配置推导板子地址，请传入 --board-address host:port" >&2
    exit 2
  fi
  RESOLVED_HOST="$(ssh -G "$SSH_HOST" 2>/dev/null | awk '$1 == "hostname" { print $2; exit }')"
  BOARD_ADDRESS="${RESOLVED_HOST:-$SSH_HOST}:7777"
fi
if ! printf '%s' "$BOARD_ADDRESS" | grep -Eq '^[^[:space:]:]+:[0-9]+$'; then
  echo "错误：--board-address 必须是 host:port，例如 192.168.128.10:7777" >&2
  exit 2
fi

if [ -t 1 ]; then
  GREEN='\033[0;32m'
  BLUE='\033[0;34m'
  YELLOW='\033[0;33m'
  RESET='\033[0m'
else
  GREEN=''
  BLUE=''
  YELLOW=''
  RESET=''
fi

if [ "$TARGET_MODE" != "development" ]; then
  echo -e "${BLUE}========== [板端预检] 检查板端 SSH ==========${RESET}"
  ssh -o BatchMode=yes -o ConnectTimeout=10 "$SSH_HOST" 'uname -m && command -v sudo >/dev/null'
  echo -e "${GREEN}✓ SSH 可用：${SSH_HOST}；sophonctl 地址：${BOARD_ADDRESS}${RESET}"
else
  echo -e "${GREEN}✓ 开发机预检通过；sophonctl 地址：${BOARD_ADDRESS}${RESET}"
fi

if [ "$PREFLIGHT_ONLY" -eq 1 ]; then
  echo -e "${GREEN}预检完成（目标：${TARGET_MODE}），未执行任何安装或部署。${RESET}"
  exit 0
fi

if [ "$TARGET_MODE" != "development" ]; then
  echo -e "${BLUE}========== [板端 1/2] [rdk-sophon] 部署服务端 ==========${RESET}"
  "$SOPHON_DIR/deploy/scripts/deploy-to-board.sh" "$SSH_HOST" --enable-plugins

  echo -e "${BLUE}========== [板端 2/2] [rdk-agent] 安装 MagicBox servo 运行文件 ==========${RESET}"
  if [ "$SKIP_SERVO_BOOTSTRAP" -eq 1 ]; then
    echo -e "${YELLOW}已跳过 servo 模板插件安装${RESET}"
  else
    REMOTE_STAGE="/tmp/rdk-agent-servo-bootstrap-$$"
    ssh "$SSH_HOST" "mkdir -p '$REMOTE_STAGE'"
    scp -q "$SERVO_TEMPLATE/servo_ctrl.py" "$SSH_HOST:$REMOTE_STAGE/servo_ctrl.py"
    scp -q "$SERVO_TEMPLATE/plugin.toml" "$SSH_HOST:$REMOTE_STAGE/plugin.toml"
    ssh "$SSH_HOST" "
      sudo install -d -o probe -g probe -m 0755 /userdata/magicbox/scripts/servo_actions
      sudo install -d -m 0755 /opt/sophon/plugins/servo
      sudo install -m 0755 '$REMOTE_STAGE/servo_ctrl.py' /userdata/magicbox/scripts/servo_ctrl.py
      sudo install -m 0644 '$REMOTE_STAGE/plugin.toml' /opt/sophon/plugins/servo/plugin.toml
      rm -rf '$REMOTE_STAGE'
      sudo systemctl restart probe-daemon.service
      sudo systemctl is-active --quiet probe-daemon.service
    "
    echo -e "${GREEN}✓ servo_ctrl.py、动作包目录和 plugin.toml 已安装，probe-daemon 已重启${RESET}"
  fi
fi

if [ "$TARGET_MODE" != "board" ]; then
  echo -e "${BLUE}========== [开发机 1/4] [rdk-sophon] 安装 sophonctl ==========${RESET}"
  "$SOPHON_DIR/deploy/scripts/install-sophonctl.sh" \
    --release \
    --bin-dir "$HOME/.local/bin" \
    --board x5 "$BOARD_ADDRESS" \
    --default
  export PATH="$HOME/.local/bin:$PATH"

  echo -e "${BLUE}========== [开发机 2/4] [rdk-agent] 准备研发沙箱 ==========${RESET}"
  if [ "$SKIP_PODMAN" -eq 1 ]; then
    echo -e "${YELLOW}已跳过 Podman；机器人应用模式仍可用，研发模式需另行准备沙箱${RESET}"
  else
    if ! command -v podman >/dev/null 2>&1; then
      echo "错误：找不到 podman；安装 Podman Desktop/CLI，或使用 --skip-podman" >&2
      exit 1
    fi
    if [ "$(uname -s)" = "Darwin" ]; then
      if ! podman machine inspect >/dev/null 2>&1; then
        podman machine init
      fi
      podman machine start >/dev/null 2>&1 || podman info >/dev/null
    fi
    podman pull docker.io/library/python:3.12-slim
    echo -e "${GREEN}✓ Python 3.12 离线研发镜像已准备${RESET}"
  fi

  echo -e "${BLUE}========== [开发机 3/4] [rdk-agent] 安装 TUI 编排器 ==========${RESET}"
  "$AGENT_DIR/deploy/install-rdk-agent.sh"

  if [ "$SSH_HOST" != "x5-root" ]; then
    ACTIVE_CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}/rdk-agent/agents.yaml"
    SSH_HOST_VALUE="$SSH_HOST" node --input-type=module - "$ACTIVE_CONFIG" <<'NODE'
import { readFileSync, writeFileSync } from "node:fs";
const path = process.argv[2];
const host = process.env.SSH_HOST_VALUE;
const source = readFileSync(path, "utf8");
const updated = source.replace(/^(\s+host:) x5-root$/gm, `$1 ${host}`);
writeFileSync(path, updated);
NODE
    echo -e "${GREEN}✓ rdk-agent 部署目标已改为 SSH 别名 ${SSH_HOST}${RESET}"
  fi

  echo -e "${BLUE}========== [开发机 4/4] 两端只读联调检查 ==========${RESET}"
  sophonctl --board x5 state >/dev/null
  sophonctl --board x5 plugins list
  rdk-agent --help
fi

echo
case "$TARGET_MODE" in
  board)
    echo -e "${GREEN}板端交付物部署完成。${RESET}"
    echo "板端服务：ssh ${SSH_HOST} 'sudo systemctl status probe-daemon --no-pager'"
    ;;
  development)
    echo -e "${GREEN}开发机交付物部署完成。${RESET}"
    echo "启动 TUI：rdk-agent"
    echo "连接配置：sophonctl config list"
    ;;
  *)
    echo -e "${GREEN}板端与开发机交付物部署完成。${RESET}"
    echo "启动 TUI：rdk-agent"
    echo "板端服务：ssh ${SSH_HOST} 'sudo systemctl status probe-daemon --no-pager'"
    echo "连接配置：sophonctl config list"
    ;;
esac
